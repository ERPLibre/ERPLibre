// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

const (
	// Cadence d'interrogation de l'état d'appel. Une seconde : le décroché
	// n'a pas besoin d'être daté à la milliseconde, et interroger plus vite
	// remplit le port de trafic inutile pendant que la voix passe.
	CadenceÉtat = time.Second

	// Au-delà, on considère l'appel perdu. Quatre-vingt-dix secondes : une
	// sonnerie dépasse rarement soixante, et la messagerie répond avant.
	DélaiDécroché = 90 * time.Second

	// État 0 de +CLCC : l'appel est actif, donc DÉCROCHÉ. C'est le signal
	// que le téléphone Android ne peut pas donner — chez lui, l'état de
	// ligne passe à « décroché » dès la composition.
	ÉtatActif = 0
)

// AppelerParModem compose par la SIM et joue une annonce AU DÉCROCHÉ.
//
// Aucun tiers n'intervient : ni trunk SIP, ni fournisseur, ni compte
// mensuel. La seule dépendance est l'opérateur de la carte SIM, qui est
// incontournable pour joindre un numéro de téléphone.
// OptionsModem rassemble ce qui gouverne un appel par la SIM.
//
// Une structure plutôt qu'une liste d'arguments : ils sont nombreux, de
// types voisins, et deux booléens côte à côte s'inversent sans bruit.
type OptionsModem struct {
	Port    string // port AT ; vide = PortDéfaut
	Carte   string // carte ALSA ; vide = détection
	Numéro  string
	Annonce string // WAV joué au décroché ; vide = aucun
	Combiné bool   // relier micro et haut-parleurs à la ligne
	ModePCM int    // mode de AT+QPCMV
	Sonder  bool   // mesurer les modes au lieu de jouer l'annonce
	AudMod  int    // AT+QAUDMOD ; ModeAudioInchangé pour ne pas y toucher
	Micro   bool   // ouvrir le micro dès le décroché plutôt qu'à la demande
	Pilote  bool   // commander l'appel par l'entrée standard, non au clavier

	// VolumeÉcoute est le cran de AT+CLVL posé au décroché. Négatif pour ne
	// pas y toucher.
	VolumeÉcoute int

	// Bruit allume la suppression de bruit du modem au décroché.
	//
	// Elle se pose APRÈS l'ouverture du canal voix, jamais avant : toucher
	// au traitement du signal rompt la voix, et le chemin qui l'applique la
	// rétablit derrière lui. Se coupe en cours d'appel, ce qui permet de
	// juger à l'oreille sur la même communication.
	Bruit bool
}

func AppelerParModem(ctx context.Context, o OptionsModem) (Résultat, error) {
	numéro, annonce, carte := o.Numéro, o.Annonce, o.Carte
	res := Résultat{Numéro: numéro, ModePCM: o.ModePCM}

	norm, err := NuméroValide(numéro)
	if err != nil {
		res.Erreur = err.Error()
		return res, err
	}
	if annonce != "" {
		if _, err := os.Stat(annonce); err != nil {
			res.Erreur = "annonce introuvable : " + err.Error()
			return res, err
		}
	}

	m, err := OuvrirModem(o.Port)
	if err != nil {
		res.Erreur = err.Error()
		return res, err
	}
	defer m.Close()

	if o.AudMod != ModeAudioInchangé {
		if err := m.RéglerModeAudio(o.AudMod); err != nil {
			slog.Warn("mode audio non réglé", "err", err)
		}
	}

	// Le pont AVANT la composition, et non après le décroché : le modem fige
	// le routage voix quand la voix s'établit, et refuse alors AT+QPCMV par
	// un ERROR sec. Ouvert trop tard, le canal est accepté sans effet.
	if err := m.OuvrirVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non ouvert", "err", err)
		res.Erreur = "canal voix USB non ouvert : " + err.Error()
	} else {
		res.VoixUSB = true
		defer func() {
			if err := m.FermerVoixUSB(); err != nil {
				slog.Warn("canal voix USB non refermé", "err", err)
			}
		}()
	}

	if err := m.Composer(norm); err != nil {
		res.Erreur = err.Error()
		return res, err
	}
	slog.Info("composition lancée", "numero", norm)

	// On raccroche QUOI QU'IL ARRIVE. Un appel laissé ouvert continue de
	// facturer, et le modem ne le libère pas de lui-même.
	défaireAppel := func() {
		if err := m.Raccrocher(); err != nil {
			slog.Warn("raccrochage", "err", err)
		}
	}

	décrochéÀ, err := attendreDécroché(ctx, m)
	if err != nil {
		défaireAppel()
		// Sans réponse n'est PAS un appel de durée nulle : c'est un appel
		// qui n'a pas eu lieu, et la distinction compte pour qui relit.
		res.Erreur = err.Error()
		return res, nil
	}
	res.Décroché = true
	res.DécrochéÀ = décrochéÀ.Format(time.RFC3339)
	slog.Info("décroché")

	// TOUS les réglages du modem ici, AVANT le moindre flux audio.
	//
	// Chacun ferme et rouvre le périphérique USB du modem : un flux déjà
	// ouvert dessus reçoit une erreur et meurt, et l'appel devient muet sans
	// que rien ne le dise. Une seule reprise, à la fin, les couvre tous.
	if o.VolumeÉcoute >= 0 {
		if err := m.RéglerVolumeÉcoute(o.VolumeÉcoute); err != nil {
			slog.Warn("volume d'écoute refusé", "err", err)
		}
	}
	if err := m.RéglerRéductionBruit(o.Bruit); err != nil {
		slog.Warn("réduction de bruit refusée", "err", err)
	}
	if res.VoixUSB {
		if err := m.RéaffirmerVoixUSB(o.ModePCM); err != nil {
			slog.Warn("canal voix USB non réaffirmé", "err", err)
		} else {
			slog.Info("canal voix USB réaffirmé", "mode", o.ModePCM)
		}
	}

	if o.Sonder {
		// La sonde REMPLACE l'annonce : les deux se disputeraient la carte.
		if c, err := carteOuDéfaut(carte); err != nil {
			res.Erreur = err.Error()
		} else {
			res.Sonde = SonderMode(ctx, c, o.ModePCM, annonce)
		}
		défaireAppel()
		res.DuréeSec = int(time.Since(décrochéÀ).Seconds())
		return res, nil
	}

	if annonce != "" {
		if err := jouerSurCarte(ctx, carte, annonce); err != nil {
			res.Erreur = "annonce non jouée : " + err.Error()
		} else {
			res.Annonce = true
		}
	}

	if o.Combiné {
		// Le combiné vient APRÈS l'annonce : les deux écrivent dans la même
		// carte, et se les disputer donnerait un mélange inaudible.
		c, err := OuvrirCombiné(ctx, carte, o.Micro)
		if err != nil {
			res.Erreur = "combiné non ouvert : " + err.Error()
		} else {
			defer c.Fermer()
			res.Combiné = true
			// Le combiné peut désormais atteindre le modem : le volume de
			// réception et la suppression de bruit valent mieux que le gain
			// logiciel, qui amplifie le souffle avec la voix.
			c.Signal = m.Signal
			c.VolumeModem = m.RéglerVolumeÉcoute
			c.BruitModem = m.RéglerRéductionBruit
			c.GainMicroModem = m.RéglerGainMicroModem
			c.GainÉcouteModem = m.RéglerGainÉcouteModem
			// On LIT ce que le modem porte, on ne le suppose pas : ces
			// réglages persistent d'un appel à l'autre, et en afficher un
			// faux ou un « inconnu » fait chercher la panne ailleurs.
			c.lireRéglagesModem(m)
			c.bruitModem.Store(o.Bruit)
			c.RéaffirmerVoix = func() error {
				return m.RéaffirmerVoixUSB(o.ModePCM)
			}
			c.Composer = m.Composer
			c.Fusionner = m.FusionnerAppels
			c.Attente = m.MettreEnAttente
			c.AppelsVoix = func() int { return compterVoix(m) }
			// La console raccroche par ce contexte : « q » doit sortir de
			// l'attente ci-dessous, qui autrement tiendrait jusqu'à ce que
			// le correspondant se lasse.
			ctxCombiné, arrêter := context.WithCancel(ctx)
			defer arrêter()
			go PiloteCombiné(o.Pilote)(ctxCombiné, c, arrêter)
			attendreFinAppel(ctxCombiné, m)
			res.Micro = c.MicOuvert()
		}
	}

	défaireAppel()
	res.DuréeSec = int(time.Since(décrochéÀ).Seconds())
	return res, nil
}

func attendreDécroché(ctx context.Context, m *Modem) (time.Time, error) {
	échéance := time.Now().Add(DélaiDécroché)
	for {
		select {
		case <-ctx.Done():
			return time.Time{}, ctx.Err()
		case <-time.After(CadenceÉtat):
		}
		appels, err := m.Appels()
		if err != nil {
			slog.Warn("état d'appel illisible", "err", err)
			continue
		}
		// On ne compte QUE les appels vocaux : le porteur de données est
		// toujours là, toujours « actif », et le prendre pour notre appel
		// donnait un décroché instantané et faux.
		var voix []ÉtatAppel
		for _, a := range appels {
			if a.Voix() {
				voix = append(voix, a)
			}
		}
		if len(voix) == 0 {
			// La ligne est retombée sans passer par l'état actif : occupé,
			// refusé, ou personne.
			return time.Time{}, fmt.Errorf("sans réponse : la ligne est retombée")
		}
		for _, a := range voix {
			if a.État == ÉtatActif {
				return time.Now(), nil
			}
		}
		if time.Now().After(échéance) {
			return time.Time{}, fmt.Errorf("sans réponse après %s", DélaiDécroché)
		}
	}
}

// jouerSurCarte écrit le fichier dans la carte son du modem.
//
// On délègue à `aplay` plutôt que de piloter ALSA nous-mêmes : l'interface
// ALSA n'est accessible en Go que par CGO, ce qui coûterait le binaire
// statique — la propriété même qui a fait choisir Go. `aplay` fait partie
// d'alsa-utils, analyse l'en-tête WAV et adapte le format.
func jouerSurCarte(ctx context.Context, carte, fichier string) error {
	carte, err := carteOuDéfaut(carte)
	if err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, "aplay", "-D", carte, "-q", fichier)
	sortie, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("aplay : %w : %s", err, strings.TrimSpace(string(sortie)))
	}
	return nil
}

// carteOuDéfaut rend la carte imposée, ou celle du modem à défaut.
//
// Une seule résolution pour l'annonce, le combiné et la sonde : trois
// copies finiraient par viser trois cartes différentes le jour où l'ordre
// des périphériques change.
func carteOuDéfaut(carte string) (string, error) {
	if carte != "" {
		// Une carte NOMMÉE se vérifie aussi : « hw:2,0 » sur une machine qui
		// n'a que deux cartes se lit comme un choix délibéré, et ne révèle
		// son inexistence qu'à l'ouverture — soit après le décroché.
		if err := VérifierCarte(carte); err != nil {
			return "", err
		}
		return carte, nil
	}
	return CarteModem()
}

var motifCarte = regexp.MustCompile(`^\s*(\d+)\s*\[([^\]]+)\]`)

// CarteModem trouve la carte son du modem dans /proc/asound/cards.
//
// On la cherche au lieu de la coder en dur : son index change selon l'ordre
// de branchement, et `hw:1,0` figé finirait par écrire dans les haut-parleurs
// de la machine — donc à jouer l'annonce dans le bureau plutôt que dans
// l'appel.
func CarteModem() (string, error) {
	f, err := os.Open(FichierCartes)
	if err != nil {
		return "", err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		g := motifCarte.FindStringSubmatch(sc.Text())
		if g == nil {
			continue
		}
		nom := strings.ToUpper(strings.TrimSpace(g[2]))
		for _, indice := range []string{"EC25", "EG25", "QUECTEL"} {
			if strings.Contains(nom, indice) {
				return "hw:" + g[1] + ",0", nil
			}
		}
	}
	return "", fmt.Errorf(
		"aucune carte son du modem : activez l'UAC (menu Modem)")
}

// attendreFinAppel rend la main quand la ligne retombe ou que le contexte
// s'annule. Sans cela le combiné se fermerait aussitôt ouvert.
func attendreFinAppel(ctx context.Context, m *Modem) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(CadenceÉtat):
		}
		appels, err := m.Appels()
		if err != nil {
			continue
		}
		encore := false
		for _, a := range appels {
			if a.Voix() {
				encore = true
			}
		}
		if !encore {
			slog.Info("le correspondant a raccroché")
			return
		}
	}
}
