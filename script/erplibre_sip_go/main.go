// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
//
// erplibre-voip : place un appel par un trunk SIP et joue une annonce AU
// DÉCROCHÉ, puis rapporte le résultat en JSON sur la sortie standard.
//
// Pourquoi ce service existe plutôt qu'un PBX : le besoin est étroit —
// s'enregistrer, composer, savoir quand ça décroche, jouer un fichier,
// rapporter. Un PBX généraliste apporterait des postes, des files d'attente,
// un serveur vocal et des transferts dont rien n'est utilisé, mais qu'il
// faudrait sécuriser et maintenir. Asterisk et PJSIP ont d'ailleurs tous
// deux été RETIRÉS de Debian 12 et 13 faute de mainteneurs : les compiler
// depuis les sources prive de toute mise à jour de sécurité par la
// distribution. Ici l'arbre de dépendances est en Go, pas en paquets C de la
// distribution, et le résultat est un binaire unique.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	numéro := flag.String("numero", "", "numéro à composer (plan nord-américain)")
	annonce := flag.String("annonce", "", "fichier WAV à jouer au décroché")
	verbeux := flag.Bool("v", false, "journal détaillé")
	// Le modem par défaut, et non SIP : c'est la voie SANS TIERS. Un trunk
	// SIP ajoute une société qui voit passer les appels et facture au mois ;
	// la SIM ne dépend que de l'opérateur, incontournable de toute façon.
	transport := flag.String("transport", "modem",
		"modem (carte SIM, aucun tiers) ou sip (trunk d'un fournisseur)")
	port := flag.String("port", PortDéfaut, "port AT du modem")
	carte := flag.String("carte", "",
		"carte son ALSA du modem ; vide = détection automatique")
	combiné := flag.Bool("combine", false,
		"relier le micro et les haut-parleurs à l'appel (vrai téléphone)")
	modePCM := flag.Int("pcm", ModeVoixUSBDéfaut,
		"mode de AT+QPCMV reliant la carte son à la ligne")
	micro := flag.Bool("micro", false,
		"ouvrir le micro dès le décroché ; sinon il s'ouvre par la touche m")
	audmod := flag.Int("audmod", ModeAudioSansDSP,
		"AT+QAUDMOD ; 3 désactive le traitement DSP, -1 n'y touche pas")
	sonder := flag.Bool("sonder-audio", false,
		"mesurer chaque mode PCM pendant l'appel au lieu de jouer l'annonce")
	clvl := flag.Int("clvl", VolumeÉcouteInchangé,
		"volume de réception DANS le modem, 0 à 5 ; -1 n'y touche pas")
	bruit := flag.Bool("bruit", true,
		"suppression de bruit du modem, posée au décroché")
	pilote := flag.Bool("pilotage", false,
		"commander l'appel par l'entrée standard et publier l'état en JSON")
	veille := flag.Bool("veille", false,
		"tenir la ligne et decrocher sur commande, au lieu de composer")
	essai := flag.Bool("essai-audio", false,
		"ouvrir le combiné SANS appeler, pour vérifier micro et touches")
	flag.Parse()

	niveau := slog.LevelWarn
	if *verbeux {
		niveau = slog.LevelInfo
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr,
		&slog.HandlerOptions{Level: niveau})))

	if *numéro == "" && !*essai && !*veille {
		échouer("numéro requis : -numero 5551234567")
	}

	// Ctrl-C raccroche au lieu de laisser un appel ouvert : un dialogue
	// abandonné continue de facturer chez le fournisseur.
	ctx, arrêter := signal.NotifyContext(context.Background(),
		os.Interrupt, syscall.SIGTERM)
	defer arrêter()

	var res Résultat
	var err error
	if *essai {
		res, err = EssaiCombiné(ctx, *carte, *micro, *pilote)
		rendre(res, err)
		return
	}
	if *veille {
		res, err = AttendreAppel(ctx, OptionsModem{
			Port: *port, Carte: *carte, Micro: *micro, Pilote: *pilote,
			ModePCM: *modePCM, AudMod: *audmod, Bruit: *bruit,
			VolumeÉcoute: *clvl,
		})
		rendre(res, err)
		return
	}
	switch *transport {
	case "modem":
		res, err = AppelerParModem(ctx, OptionsModem{
			Port:    *port,
			Carte:   *carte,
			Numéro:  *numéro,
			Annonce: *annonce,
			Combiné: *combiné,
			ModePCM: *modePCM,
			Sonder:  *sonder,
			AudMod:  *audmod,
			Micro:   *micro,
			Pilote:  *pilote,

			VolumeÉcoute: *clvl,
			Bruit:        *bruit,
		})
	case "sip":
		// La voie SIP reste disponible pour qui possède déjà un trunk, mais
		// elle n'est pas le défaut : elle réintroduit une dépendance.
		var cfg Config
		cfg, err = ChargerConfig()
		if err != nil {
			échouer(err.Error())
		}
		res, err = Appeler(ctx, cfg, *numéro, *annonce)
	default:
		échouer("transport inconnu : " + *transport + " (modem ou sip)")
	}
	rendre(res, err)
}

// rendre écrit le résultat en JSON et fixe le code de sortie.
func rendre(res Résultat, err error) {
	sortie, _ := json.MarshalIndent(res, "", "  ")
	fmt.Println(string(sortie))
	if err != nil {
		os.Exit(1)
	}
}

func échouer(msg string) {
	res := Résultat{Erreur: msg}
	sortie, _ := json.MarshalIndent(res, "", "  ")
	fmt.Println(string(sortie))
	os.Exit(2)
}
