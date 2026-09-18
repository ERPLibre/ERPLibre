// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

// ÉtatCombiné est la photo publiée à qui pilote l'appel de l'extérieur.
//
// Publiée en JSON une ligne à la fois plutôt qu'en réponse à une question :
// une interface graphique doit suivre les NIVEAUX, qui bougent en
// permanence, et interroger cinq fois par seconde coûte plus qu'écouter.
type ÉtatCombiné struct {
	Type        string `json:"type"`
	Micro       bool   `json:"micro"`
	HP          bool   `json:"hp"`
	GainMicro   int    `json:"gain_micro"`
	GainHP      int    `json:"gain_hp"`
	NiveauMic   int    `json:"niveau_micro"`
	NiveauHP    int    `json:"niveau_hp"`
	Entrée      string `json:"entree"`
	Sortie      string `json:"sortie"`
	ÉchelleMax  int    `json:"echelle_niveau"`
	GainMax     int    `json:"gain_max"`
	AntiÉcho    bool   `json:"anti_echo"`
	VolumeModem int    `json:"volume_modem"`
	BruitModem  bool   `json:"bruit_modem"`
	SignalDBm   int    `json:"signal_dbm"`
	SignalTexte string `json:"signal_detail"`
	AppelsVoix  int    `json:"appels_voix"`
	FiltreMicro bool   `json:"filtre_micro"`
	Entrant     string `json:"appel_entrant"`
	EnLigne     bool   `json:"en_ligne"`
	Sonnerie    bool   `json:"sonnerie"`
	GainMicMdm  int    `json:"gain_micro_modem"`
	GainEcoMdm  int    `json:"gain_ecoute_modem"`
	GainMicUnit int    `json:"gain_micro_unite"`
	// La boîte vocale de l'OPÉRATEUR, lue sur la SIM. « Connue » distingue
	// « pas de message » d'une lecture qui n'a pas encore eu lieu ou qui
	// échoue : sans elle, une SIM muette s'afficherait comme une boîte vide.
	MessagerieConnue  bool   `json:"messagerie_connue"`
	MessagerieAttente bool   `json:"messagerie_attente"`
	MessagerieNuméro  string `json:"messagerie_numero"`
}

// ToursParSignal espace les mesures de signal.
//
// Interroger le modem coûte deux allers-retours sur le port AT, que la
// boucle d'état partage avec la surveillance de l'appel. Toutes les deux
// secondes suffit : la puissance reçue ne saute pas d'un cran par
// cinquième de seconde.
const ToursParSignal = 10

// ToursParMessagerie espace les lectures de la SIM : une par minute. Le
// drapeau se lève une vingtaine de secondes après le dépôt d'un message, et
// le relire plus souvent n'annoncerait rien plus tôt.
const ToursParMessagerie = 300

// PiloteCombiné rend qui commande l'appel : le clavier, ou un programme.
//
// Les deux lisent l'entrée standard et s'excluent donc : se la disputer
// ferait perdre une frappe sur deux.
func PiloteCombiné(parProgramme bool) func(context.Context, *Combiné, context.CancelFunc) {
	if parProgramme {
		return PiloterCombiné
	}
	return ConsoleCombiné
}

// PiloterCombiné commande l'appel par l'entrée standard.
//
// Sert quand une interface tient la place de l'utilisateur : elle écrit des
// commandes, elle lit l'état. La console au clavier et ce mode s'excluent —
// tous deux lisent l'entrée standard, et se la disputer ferait perdre une
// frappe sur deux.
//
// Le dialogue est en lignes de texte plutôt qu'en socket ou en signal : il
// se lit dans un journal, se rejoue à la main, et ne demande aucun port.
func PiloterCombiné(ctx context.Context, c *Combiné, raccrocher context.CancelFunc) {
	commandes := lireLignes(ctx)
	tic := time.NewTicker(CadenceAffichage)
	defer tic.Stop()

	tours := 0
	dBm, détail := 0, ""
	var msgConnue, msgAttente bool
	msgNuméro := ""
	if c.NuméroMessagerie != nil {
		// Une seule fois : le numéro de la messagerie ne change pas d'une
		// minute à l'autre, et chaque lecture occupe le port.
		if numéro, err := c.NuméroMessagerie(); err == nil {
			msgNuméro = numéro
		}
	}
	publier := func() {
		m, h := c.Niveaux()
		gm, gh := c.Gains()
		e, s := c.Périphériques()
		if c.Signal != nil && tours%ToursParSignal == 0 {
			dBm, détail = c.Signal()
		}
		// Ligne libre seulement : pendant une conversation, le port sert à
		// l'appel, et le drapeau peut attendre la minute suivante.
		if c.Messagerie != nil && tours%ToursParMessagerie == 0 && appelsVoix(c) <= 0 {
			if attente, err := c.Messagerie(); err == nil {
				msgConnue, msgAttente = true, attente
			}
		}
		tours++
		é := ÉtatCombiné{
			Type: "etat", Micro: c.MicOuvert(), HP: c.HPOuvert(),
			GainMicro: gm, GainHP: gh, NiveauMic: m, NiveauHP: h,
			Entrée: e, Sortie: s, ÉchelleMax: ÉchelleNiveau,
			GainMax: GainMax, AntiÉcho: c.AntiÉcho(),
			VolumeModem: c.VolumeModemPosé(), BruitModem: c.BruitModemActif(),
			SignalDBm: dBm, SignalTexte: détail,
			AppelsVoix: appelsVoix(c), FiltreMicro: c.FiltreMicro(),
			Entrant: entrant(c), EnLigne: enLigne(c),
			Sonnerie:   c.Sonnerie(),
			GainMicMdm: c.GainMicroModemPosé(),
			GainEcoMdm: c.GainÉcouteModemPosé(), GainMicUnit: GainMicroUnité,
			MessagerieConnue: msgConnue, MessagerieAttente: msgAttente,
			MessagerieNuméro: msgNuméro,
		}
		if b, err := json.Marshal(é); err == nil {
			fmt.Println(string(b))
		}
	}
	publier()

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.Fini:
			return
		case <-tic.C:
			publier()
		case ligne, ouvert := <-commandes:
			if !ouvert {
				// L'entrée s'est tarie : celui qui pilotait est parti, et
				// laisser l'appel ouvert le laisserait facturer sans
				// personne pour le voir.
				raccrocher()
				return
			}
			if appliquerCommande(c, ligne, raccrocher) {
				return
			}
			publier()
		}
	}
}

// appelsVoix compte les appels en cours, ou -1 si on ne peut pas savoir.
//
// Distinguer « aucun » de « on l'ignore » compte : l'interface propose la
// fusion à partir de deux appels, et un zéro faux la rendrait inatteignable.
func appelsVoix(c *Combiné) int {
	if c.AppelsVoix == nil {
		return -1
	}
	return c.AppelsVoix()
}

// entrant rend le numéro qui sonne, vide s'il n'y a personne ou si l'on ne
// peut pas savoir — en veille seulement, un appel sortant n'ayant personne
// à prendre.
func entrant(c *Combiné) string {
	if c.AppelEntrant == nil {
		return ""
	}
	return c.AppelEntrant()
}

// enLigne dit si une conversation est établie.
//
// Les deux sens ne se reconnaissent pas pareil. Un appel SORTANT n'ouvre le
// combiné qu'une fois décroché : sa seule existence vaut conversation. En
// veille, le combiné est ouvert bien avant la sonnerie, et c'est l'écoute
// qui s'ouvre au moment où l'on prend l'appel.
func enLigne(c *Combiné) bool {
	if c.Répondre == nil {
		return true
	}
	return c.HPOuvert()
}

// appliquerCommande exécute une ligne. Rend true s'il faut tout arrêter.
func appliquerCommande(c *Combiné, ligne string, raccrocher context.CancelFunc) bool {
	champs := strings.Fields(strings.TrimSpace(ligne))
	if len(champs) == 0 {
		return false
	}
	verbe := strings.ToLower(champs[0])
	arg := ""
	if len(champs) > 1 {
		arg = strings.Join(champs[1:], " ")
	}
	switch verbe {
	case "micro":
		régler(&c.micOuvert, arg, c.BasculerMic)
	case "hp":
		régler(&c.hpOuvert, arg, c.BasculerHP)
	case "gain-micro":
		if n, err := strconv.Atoi(arg); err == nil {
			c.RéglerGainMic(n)
		}
	case "gain-hp":
		if n, err := strconv.Atoi(arg); err == nil {
			c.RéglerGainHP(n)
		}
	case "composer":
		// Composer pendant un appel met le premier en attente : c'est le
		// réseau qui le fait, pas nous.
		if c.Composer != nil && arg != "" {
			if err := c.Composer(arg); err != nil {
				slog.Warn("second appel refusé", "err", err)
			}
		}
	case "touches":
		if c.Touches != nil && arg != "" {
			if err := c.Touches(arg); err != nil {
				slog.Warn("touches refusées", "err", err)
			}
		}
	case "fusionner":
		if c.Fusionner != nil {
			if err := c.Fusionner(); err != nil {
				slog.Warn("fusion refusée", "err", err)
			}
		}
	case "attente":
		if c.Attente != nil {
			if err := c.Attente(); err != nil {
				slog.Warn("mise en attente refusée", "err", err)
			}
		}
	case "repondre":
		if c.Répondre != nil {
			if err := c.Répondre(); err != nil {
				slog.Warn("decrochage refuse", "err", err)
			}
		}
	case "sonnerie":
		régler(&c.sonnerie, arg, c.BasculerSonnerie)
	case "anti-echo":
		régler(&c.antiÉcho, arg, c.BasculerAntiÉcho)
	case "filtre":
		régler(&c.filtreMicro, arg, c.BasculerFiltreMicro)
	case "gain-ecoute-modem":
		if n, err := strconv.Atoi(arg); err == nil {
			if err := c.PoserGainÉcouteModem(n); err != nil {
				slog.Warn("gain d'écoute du modem refusé", "err", err)
			}
		}
	case "gain-micro-modem":
		if n, err := strconv.Atoi(arg); err == nil {
			if err := c.PoserGainMicroModem(n); err != nil {
				slog.Warn("gain micro du modem refusé", "err", err)
			}
		}
	case "volume-modem":
		if n, err := strconv.Atoi(arg); err == nil {
			if err := c.PoserVolumeModem(n); err != nil {
				slog.Warn("volume du modem refusé", "err", err)
			}
		}
	case "bruit-modem":
		actif := strings.EqualFold(arg, "on") || arg == "1"
		if err := c.PoserBruitModem(actif); err != nil {
			slog.Warn("reduction de bruit refusee", "err", err)
		}
	case "entree":
		// Un argument vide remet le périphérique du système : c'est le seul
		// moyen d'annuler un choix, et il doit rester atteignable.
		c.ChoisirMicro(arg)
	case "sortie":
		c.ChoisirSortie(arg)
	case "raccrocher":
		raccrocher()
		return true
	default:
		slog.Warn("commande inconnue", "verbe", verbe)
	}
	return false
}

// régler applique on, off ou une bascule à un interrupteur.
func régler(cible *atomic.Bool, arg string, basculer func() bool) {
	switch strings.ToLower(arg) {
	case "on", "1", "true", "ouvert":
		cible.Store(true)
	case "off", "0", "false", "ferme", "fermé":
		cible.Store(false)
	default:
		basculer()
	}
}

// lireLignes rend un canal des lignes reçues sur l'entrée standard.
func lireLignes(ctx context.Context) <-chan string {
	sortie := make(chan string, 8)
	go func() {
		defer close(sortie)
		lecteur := bufio.NewScanner(os.Stdin)
		for lecteur.Scan() {
			select {
			case sortie <- lecteur.Text():
			case <-ctx.Done():
				return
			}
		}
	}()
	return sortie
}
