// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"errors"
	"net"
	"net/url"
	"os"
	"strings"
	"sync"
	"syscall"
	"time"
)

// DelaiEtablissement borne l'établissement d'une connexion vers l'amont, pour
// le relais comme pour la sonde du miroir git.
//
// Un pare-feu qui JETTE les paquets sans les refuser fait pendre
// l'établissement jusqu'à ce délai : c'est le prix que paie chaque tentative
// vers un amont coupé, et la raison d'être de la mémoire qui suit.
const DelaiEtablissement = 4 * time.Second

// FenetreMuetParDefaut : combien de temps un amont dont l'établissement vient
// d'échouer est tenu pour muet sans être retenté.
//
// Courte à dessein. Elle suffit à épargner le délai d'établissement aux
// dizaines de requêtes qui visent le même hôte en rafale, et elle rend l'amont
// à sa première chance dès qu'il revient.
const FenetreMuetParDefaut = 20 * time.Second

// SentinelleAmonts nomme le témoin que la levée d'une coupure touche dans le
// magasin pour annuler la mémoire des amonts muets. Le nom est tenu en accord
// avec le code qui pose la coupure : toucher un fichier que rien ne lit
// laisserait les amonts muets jusqu'à la fin de leur fenêtre.
const SentinelleAmonts = ".amonts-oublies"

// errAmontConnuMuet dit qu'aucune connexion n'a été tentée : l'établissement
// vers cet amont a échoué il y a moins d'une fenêtre.
var errAmontConnuMuet = errors.New(
	"amont connu muet : l'établissement vient d'échouer, il n'est pas retenté")

// Joignabilite retient, par « hôte:port », l'instant du dernier
// établissement de connexion manqué.
//
// Sans elle, chaque requête vers un amont coupé repaie le délai
// d'établissement entier avant de rabattre sur la copie gardée : une
// installation hors ligne en enchaîne des centaines, et l'attente domine
// alors tout le reste. Avec elle, la première requête paie, les suivantes
// passent directement au repli.
//
// Seul un échec d'ÉTABLISSEMENT compte : délai de connexion, refus, hôte ou
// réseau injoignable. Un serveur lent à rendre ses en-têtes, une poignée de
// main TLS manquée ou un statut HTTP disent que l'amont est LÀ, et le tenir
// pour muet servirait une copie périmée à la place d'une réponse qui venait.
//
// Partagée entre le relais et le miroir git : un hôte coupé l'est pour les
// deux. Toutes les méthodes acceptent un récepteur nul, qui ne retient rien.
type Joignabilite struct {
	// Fenetre borne la mémoire d'un échec. Nulle, la valeur par défaut
	// s'applique.
	Fenetre time.Duration
	// Maintenant rend l'heure courante ; les tests la remplacent pour faire
	// passer une fenêtre sans l'attendre.
	Maintenant func() time.Time
	// Sentinelle est un fichier dont la date annule la mémoire : tout échec
	// antérieur est oublié. Il n'existe aucun canal vers le service en
	// marche, et sans ce témoin les amonts notés muets PENDANT une coupure
	// le restent jusqu'à la fin de la fenêtre — la première requête d'après
	// la levée tombe alors dans le repli alors que le réseau est revenu.
	// Vide, rien n'est consulté.
	Sentinelle string

	mu     sync.Mutex
	echecs map[string]time.Time
}

// NouvelleJoignabilite rend une mémoire vide, à la fenêtre par défaut.
func NouvelleJoignabilite() *Joignabilite {
	return &Joignabilite{Fenetre: FenetreMuetParDefaut}
}

func (j *Joignabilite) maintenant() time.Time {
	if j.Maintenant != nil {
		return j.Maintenant()
	}
	return time.Now()
}

func (j *Joignabilite) fenetre() time.Duration {
	if j.Fenetre > 0 {
		return j.Fenetre
	}
	return FenetreMuetParDefaut
}

// ConnuMuet dit si l'établissement vers cette adresse a échoué depuis moins
// d'une fenêtre. Une entrée échue est oubliée au passage.
func (j *Joignabilite) ConnuMuet(adresse string) bool {
	if j == nil {
		return false
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	quand, ok := j.echecs[adresse]
	if !ok {
		return false
	}
	if j.maintenant().Sub(quand) >= j.fenetre() {
		delete(j.echecs, adresse)
		return false
	}
	// Le témoin touché après l'échec : la coupure a été levée depuis, et
	// l'amont mérite une nouvelle chance immédiate. Un témoin illisible ou
	// absent ne change rien — la fenêtre reprend seule son office.
	if j.Sentinelle != "" {
		if info, err := os.Stat(j.Sentinelle); err == nil &&
			info.ModTime().After(quand) {
			delete(j.echecs, adresse)
			return false
		}
	}
	return true
}

// Echec retient l'adresse si l'erreur est un échec d'établissement, et dit
// si elle l'a été. Toute autre erreur est ignorée.
func (j *Joignabilite) Echec(adresse string, err error) bool {
	if j == nil || !estEchecDEtablissement(err) {
		return false
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.echecs == nil {
		j.echecs = map[string]time.Time{}
	}
	j.echecs[adresse] = j.maintenant()
	return true
}

// Reussite oublie l'adresse : l'amont vient de répondre.
func (j *Joignabilite) Reussite(adresse string) {
	if j == nil {
		return
	}
	j.mu.Lock()
	defer j.mu.Unlock()
	delete(j.echecs, adresse)
}

// estEchecDEtablissement dit si l'erreur vient de l'ÉTABLISSEMENT de la
// connexion, et non de ce qui la suit.
//
// La bibliothèque rend un établissement manqué comme un « *net.OpError »
// d'opération « dial », enveloppé par le client HTTP dans un « *url.Error » :
// errors.As traverse les deux. Le délai compte, et parmi les codes système
// ceux qui disent « personne ne répond à cette adresse ». Un nom qui n'existe
// pas n'en est pas : ce n'est pas un amont coupé, c'est un amont inexistant.
func estEchecDEtablissement(err error) bool {
	var op *net.OpError
	if err == nil || !errors.As(err, &op) || op.Op != "dial" {
		return false
	}
	if op.Timeout() {
		return true
	}
	var errno syscall.Errno
	if errors.As(op.Err, &errno) {
		switch errno {
		case syscall.ECONNREFUSED, syscall.EHOSTUNREACH,
			syscall.ENETUNREACH, syscall.ETIMEDOUT:
			return true
		}
	}
	return false
}

// adresseAmont rend la clé « hôte:port » d'une URL, le port déduit du schéma
// quand l'URL n'en porte pas : « https://h/x » et « https://h:443/y » visent
// la même machine et doivent partager leur mémoire.
func adresseAmont(u *url.URL) string {
	if u == nil {
		return ""
	}
	hote := strings.ToLower(u.Hostname())
	port := u.Port()
	if port == "" {
		switch strings.ToLower(u.Scheme) {
		case "https":
			port = "443"
		case "http":
			port = "80"
		default:
			return hote
		}
	}
	return net.JoinHostPort(hote, port)
}

// sonderTCP ouvre puis referme une connexion vers l'adresse, sans rien y
// dire. Rend l'erreur d'établissement, nulle quand l'amont a accepté.
func sonderTCP(ctx context.Context, adresse string) error {
	d := net.Dialer{Timeout: DelaiEtablissement}
	c, err := d.DialContext(ctx, "tcp", adresse)
	if err != nil {
		return err
	}
	return c.Close()
}

// decrireMuet rend la phrase du message hors ligne qui dit que l'amont n'a
// pas été retenté, ou "" quand la cause est un vrai échec du réseau.
func decrireMuet(cause error) string {
	if !errors.Is(cause, errAmontConnuMuet) {
		return ""
	}
	return "L'établissement vers cet amont vient d'échouer : aucune connexion\n" +
		"n'a été tentée pour cette requête, l'amont sera retenté sous peu.\n"
}
