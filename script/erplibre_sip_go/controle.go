// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

// Remettre au service un secret qu'il ne doit pas garder sur disque.
//
// Le NIP de la messagerie de l'opérateur vit dans un coffre, qu'un humain
// seul peut ouvrir. Le service, lui, tourne sans personne : il ne peut ni
// l'ouvrir, ni le lire dans un fichier — l'y écrire reviendrait à annuler le
// coffre. Il le reçoit donc d'un humain qui vient de l'ouvrir, et le garde EN
// MÉMOIRE jusqu'à son arrêt.
//
// Ce que cela ne protège pas, et qu'il faut savoir : root lit la mémoire de
// n'importe quel processus, et un vidage mémoire emporterait le secret. C'est
// une posture meilleure qu'un fichier, pas une garantie.

const (
	// CommandeNIP remet le code de la messagerie. CommandeÉtat demande ce
	// que le service détient, sans jamais le rendre.
	CommandeNIP  = "NIP"
	CommandeÉtat = "ETAT"

	// TailleMaxCommande borne une ligne reçue. Un correspondant qui n'envoie
	// jamais de fin de ligne retiendrait sinon la lecture sans fin.
	TailleMaxCommande = 4096
)

// Secrets garde ce qu'un humain a remis au service.
//
// Rien n'en sort : `NIP()` sert à composer, `ADéjàLeNIP` à l'afficher. Un
// accesseur qui rendrait la valeur à un appelant quelconque ferait du journal
// et des messages d'erreur autant d'endroits où elle peut fuir.
type Secrets struct {
	verrou sync.RWMutex
	nip    string
}

// PoserNIP remplace le code détenu.
func (s *Secrets) PoserNIP(code string) {
	s.verrou.Lock()
	defer s.verrou.Unlock()
	s.nip = code
}

// NIP rend le code détenu, ou une chaîne vide.
func (s *Secrets) NIP() string {
	s.verrou.RLock()
	defer s.verrou.RUnlock()
	return s.nip
}

// ADéjàLeNIP dit si le service en détient un, sans le rendre.
func (s *Secrets) ADéjàLeNIP() bool {
	s.verrou.RLock()
	defer s.verrou.RUnlock()
	return s.nip != ""
}

// CheminContrôle rend l'emplacement de la socket de commande.
//
// Un chemin FIXE sous le répertoire d'état, comme l'état de la messagerie :
// le CLI doit la trouver sans rien savoir de la façon dont le service a été
// lancé.
func CheminContrôle() string {
	base := os.Getenv("XDG_STATE_HOME")
	if base == "" {
		maison, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		base = filepath.Join(maison, ".local", "state")
	}
	return filepath.Join(base, "erplibre", "controle.sock")
}

// ÉcouterLesCommandes ouvre la socket de commande et sert jusqu'à l'arrêt.
//
// Une socket de DOMAINE UNIX et non un port : rien n'est joignable par le
// réseau, et ce sont les droits du fichier qui autorisent — 0600, donc le
// compte du service et lui seul. Un fichier déposé ferait aussi bien passer
// la valeur, mais il la laisserait au repos sur un disque et ne dirait pas
// s'il a été lu.
func ÉcouterLesCommandes(ctx context.Context, chemin string, secrets *Secrets) error {
	if chemin == "" {
		return fmt.Errorf("aucun chemin de controle")
	}
	if err := os.MkdirAll(filepath.Dir(chemin), 0o700); err != nil {
		return err
	}
	// Une socket d'un service mort reste sur le disque et fait échouer
	// l'écoute suivante : on retire la précédente, après s'être assuré que
	// personne n'écoute dessus.
	if c, err := net.Dial("unix", chemin); err == nil {
		c.Close()
		return fmt.Errorf("une autre instance ecoute deja sur %s", chemin)
	}
	_ = os.Remove(chemin)

	écouteur, err := net.Listen("unix", chemin)
	if err != nil {
		return err
	}
	if err := os.Chmod(chemin, 0o600); err != nil {
		écouteur.Close()
		return err
	}
	slog.Info("commandes locales en écoute", "socket", chemin)

	go func() {
		<-ctx.Done()
		écouteur.Close()
		_ = os.Remove(chemin)
	}()

	for {
		conn, err := écouteur.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		go servirUneCommande(conn, secrets)
	}
}

// servirUneCommande lit une ligne, agit, répond, et ferme.
//
// Une commande par connexion : le secret ne traîne pas dans un tampon de
// session, et une connexion oubliée ouverte ne retient rien.
func servirUneCommande(conn net.Conn, secrets *Secrets) {
	defer conn.Close()
	lecteur := bufio.NewReaderSize(conn, TailleMaxCommande)
	ligne, err := lecteur.ReadString('\n')
	if err != nil && ligne == "" {
		return
	}
	réponse := TraiterCommande(strings.TrimRight(ligne, "\r\n"), secrets)
	_, _ = conn.Write([]byte(réponse + "\n"))
}

// TraiterCommande applique une ligne et rend la réponse à écrire.
//
// Séparée du réseau pour se vérifier sans socket. Le journal ne porte JAMAIS
// l'argument : une commande mal formée se dit « refusée », sans citer ce
// qu'elle contenait, car ce qu'elle contenait est précisément le secret.
func TraiterCommande(ligne string, secrets *Secrets) string {
	verbe, reste, _ := strings.Cut(ligne, " ")
	switch strings.ToUpper(strings.TrimSpace(verbe)) {
	case CommandeNIP:
		code := strings.TrimSpace(reste)
		if code == "" {
			slog.Warn("commande NIP refusee : aucun code")
			return "ERREUR aucun code"
		}
		secrets.PoserNIP(code)
		slog.Info("code de la messagerie recu et garde en memoire")
		return "OK"
	case CommandeÉtat:
		if secrets.ADéjàLeNIP() {
			return "OK nip=oui"
		}
		return "OK nip=non"
	default:
		slog.Warn("commande locale inconnue")
		return "ERREUR commande inconnue"
	}
}
