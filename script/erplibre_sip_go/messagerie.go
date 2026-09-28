// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Savoir qu'un message attend dans la boîte vocale de l'OPÉRATEUR.
//
// Le réseau l'annonce par une indication silencieuse que le modem ne remonte
// pas : ce modem n'expose aucun indicateur « message » par AT+CIND, et
// l'opérateur n'envoie pas forcément de SMS. Le téléphone inscrit en revanche
// l'état sur la SIM, dans le fichier standard EF_MWIS (3GPP TS 31.102), qui
// se lit en lecture seule. Le drapeau suit les deux sens : il se lève quand un
// message est déposé, et retombe quand la boîte est vidée.
//
// Il ne porte PAS de compte fiable : le réseau peut laisser le nombre à zéro.
// On sait donc « au moins un message », jamais combien.

const (
	// CommandeMWIS lit l'enregistrement 1 d'EF_MWIS (identifiant 6FCA, soit
	// 28618), cinq octets. 178 est READ RECORD, 4 le mode absolu.
	CommandeMWIS = "AT+CRSM=178,28618,1,4,5"

	// CadenceMessagerie espace les lectures. Le drapeau se lève une vingtaine
	// de secondes après le dépôt : lire plus souvent n'annoncerait rien plus
	// tôt, et occuperait le port que les appels se disputent.
	CadenceMessagerie = time.Minute

	// BitMessagerieVocale est le premier bit du premier octet d'EF_MWIS.
	BitMessagerieVocale = 0x01

	// CommandeNuméroMessagerie lit le numéro que l'opérateur a inscrit sur la
	// SIM. C'est le seul qui mène à coup sûr à SA messagerie.
	CommandeNuméroMessagerie = "AT+CSVM?"
)

var motifCSVM = regexp.MustCompile(`\+CSVM:\s*(\d+),\s*"([^"]*)"`)

var motifCRSM = regexp.MustCompile(`\+CRSM:\s*(\d+),\s*(\d+)(?:,\s*"([0-9A-Fa-f]*)")?`)

// DécoderMWIS rend l'état du drapeau à partir d'une réponse brute à la
// commande de lecture.
//
// Séparée de la lecture pour être vérifiable sans modem. Un statut autre que
// 144 ou 145 est une ERREUR et non un « pas de message » : une SIM sans ce
// fichier ne peut rien annoncer, et le taire laisserait croire à une boîte
// vide.
func DécoderMWIS(réponse string) (bool, error) {
	g := motifCRSM.FindStringSubmatch(réponse)
	if g == nil {
		return false, fmt.Errorf("reponse CRSM illisible : %q", strings.TrimSpace(réponse))
	}
	sw1, _ := strconv.Atoi(g[1])
	sw2, _ := strconv.Atoi(g[2])
	if sw1 != 144 && sw1 != 145 {
		return false, fmt.Errorf("EF_MWIS illisible sur cette SIM (statut %d,%d)", sw1, sw2)
	}
	octets, err := hex.DecodeString(g[3])
	if err != nil || len(octets) == 0 {
		return false, fmt.Errorf("EF_MWIS vide ou mal forme : %q", g[3])
	}
	return octets[0]&BitMessagerieVocale != 0, nil
}

// LireAttenteMessagerie interroge la SIM.
func (m *Modem) LireAttenteMessagerie() (bool, error) {
	rép, err := m.Commande(CommandeMWIS, 5*time.Second)
	if err != nil {
		return false, err
	}
	return DécoderMWIS(rép)
}

// NuméroMessagerie rend le numéro à composer, ou une erreur.
//
// Un premier champ à zéro dit que la SIM n'en porte aucun : ce n'est pas une
// panne, c'est une messagerie non provisionnée.
func (m *Modem) NuméroMessagerie() (string, error) {
	rép, err := m.Commande(CommandeNuméroMessagerie, 5*time.Second)
	if err != nil {
		return "", err
	}
	g := motifCSVM.FindStringSubmatch(rép)
	if g == nil {
		return "", fmt.Errorf("reponse CSVM illisible : %q", strings.TrimSpace(rép))
	}
	if g[1] == "0" || g[2] == "" {
		return "", fmt.Errorf("aucun numero de messagerie inscrit sur la SIM")
	}
	return g[2], nil
}

// VeilleMessagerie retient ce qui a été vu et ce qui a été annoncé.
//
// Les deux sont distincts : un état vu mais que Odoo n'a pas reçu doit être
// renvoyé au tour suivant. Ne retenir que le vu perdrait l'annonce au premier
// refus du serveur, et la fiche resterait fausse jusqu'au prochain changement
// — potentiellement des jours.
type VeilleMessagerie struct {
	Lien *LienOdoo
	// Fichier est l'état local relu par la TUI. Vide : aucun fichier.
	Fichier string

	vu       bool
	connu    bool
	annoncé  bool
	aAnnoncé bool
	échecs   int
}

// Observer intègre une lecture et annonce ce qui doit l'être.
//
// Rend vrai quand l'état vient de CHANGER, pour le journal. La première
// lecture compte comme un changement : au démarrage, Odoo ignore tout de
// l'état courant.
func (v *VeilleMessagerie) Observer(attente bool, err error, maintenant time.Time) bool {
	if err != nil {
		v.échecs++
		// Une fois, puis toutes les heures : une SIM sans le fichier échoue
		// à chaque lecture, et le répéter chaque minute noierait le journal.
		if v.échecs == 1 || v.échecs%60 == 0 {
			slog.Warn("lecture du drapeau de messagerie impossible",
				"err", err, "tentatives", v.échecs)
		}
		return false
	}
	v.échecs = 0
	if err := ÉcrireÉtatMessagerie(v.Fichier, attente, maintenant); err != nil {
		slog.Warn("etat local de la messagerie non ecrit", "err", err)
	}
	changé := !v.connu || attente != v.vu
	v.vu, v.connu = attente, true
	if changé {
		slog.Info("messagerie de l'operateur", "message_en_attente", attente)
	}
	if !v.aAnnoncé || v.annoncé != attente {
		if err := SignalerMessagerie(v.Lien, attente, maintenant); err != nil {
			slog.Warn("etat de la messagerie non transmis a Odoo : nouvel essai"+
				" au prochain tour", "err", err)
		} else if v.Lien != nil && v.Lien.Appareil != "" {
			v.annoncé, v.aAnnoncé = attente, true
		}
	}
	return changé
}

// ÉtatMessagerie est ce que le service laisse pour la TUI.
type ÉtatMessagerie struct {
	Attente bool   `json:"attente"`
	LuLe    string `json:"lu_le"`
}

// CheminÉtatMessagerie rend l'emplacement de l'état local.
//
// Un chemin FIXE, sous le répertoire d'état de l'utilisateur, et non une
// option : la TUI doit le retrouver sans rien savoir de la façon dont le
// service a été lancé. Le service tenant le port du modem, c'est le seul
// moyen pour elle de connaître l'état pendant qu'il tourne.
func CheminÉtatMessagerie() string {
	base := os.Getenv("XDG_STATE_HOME")
	if base == "" {
		maison, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		base = filepath.Join(maison, ".local", "state")
	}
	return filepath.Join(base, "erplibre", "messagerie.json")
}

// ÉcrireÉtatMessagerie dépose l'état à CHAQUE lecture réussie, et pas
// seulement aux changements : la date dit à la TUI que la lecture continue,
// et un état ancien de plusieurs heures ne se présente pas comme frais.
//
// L'écriture passe par un fichier temporaire renommé : la TUI peut lire à
// tout instant, et un fichier à moitié écrit ne se décode pas.
func ÉcrireÉtatMessagerie(chemin string, attente bool, lu time.Time) error {
	if chemin == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(chemin), 0o700); err != nil {
		return err
	}
	brut, err := json.Marshal(ÉtatMessagerie{
		Attente: attente, LuLe: lu.Format(time.RFC3339),
	})
	if err != nil {
		return err
	}
	provisoire := chemin + ".partiel"
	if err := os.WriteFile(provisoire, append(brut, '\n'), 0o600); err != nil {
		return err
	}
	return os.Rename(provisoire, chemin)
}
