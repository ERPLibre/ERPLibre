// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"log/slog"
	"time"
)

// CadenceVeille règle la surveillance de la ligne au repos.
//
// Une seconde : une sonnerie dure plusieurs dizaines de secondes, et
// interroger plus vite remplit le port AT sans rien apprendre de plus.
const CadenceVeille = time.Second

// DélaiRoutage laisse au modem le temps de reposer son routage voix avant
// qu'on ouvre les flux dessus.
//
// L'ordre est la seule chose qui compte ici. Réaffirmer le canal ferme et
// rouvre le périphérique USB du modem : tout flux ALSA déjà ouvert dessus
// reçoit une erreur et meurt, et l'appel devient muet sans que rien ne le
// dise. Les réglages du modem passent donc TOUS avant le premier flux,
// comme sur un appel sortant, où le combiné n'existe qu'une fois la voix
// établie.
const DélaiRoutage = 300 * time.Millisecond

// AttendreAppel tient la ligne et décroche sur commande.
//
// Le combiné est ouvert AVANT que le téléphone ne sonne, micro et écoute
// fermés : ouvrir la carte du modem prend du temps, et le faire au moment
// de décrocher ferait manquer les premiers mots. Répondre ne fait donc que
// poser ATA et rouvrir les deux sens.
//
// Le canal voix USB s'ouvre lui aussi d'emblée, pour la même raison qu'à la
// composition : le modem fige son routage quand la voix s'établit, et une
// ouverture tardive est acceptée sans effet.
func AttendreAppel(ctx context.Context, o OptionsModem) (Résultat, error) {
	res := Résultat{Numéro: "—"}

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
	if err := m.AnnoncerAppelant(); err != nil {
		slog.Warn("présentation du numéro refusée", "err", err)
	}
	if err := m.OuvrirVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non ouvert", "err", err)
	} else {
		res.VoixUSB = true
		defer func() { _ = m.FermerVoixUSB() }()
	}

	// Construit SANS démarrer : les flux n'ouvriront qu'une fois l'appel
	// pris et le routage du modem posé. Les commandes de l'interface et la
	// publication de l'état fonctionnent dès maintenant.
	carte, err := carteOuDéfaut(o.Carte)
	if err != nil {
		res.Erreur = err.Error()
		return res, err
	}
	c := NouveauCombiné(carte)
	defer c.Fermer()
	c.hpOuvert.Store(false)

	c.Signal = m.Signal
	c.VolumeModem = m.RéglerVolumeÉcoute
	c.BruitModem = m.RéglerRéductionBruit
	c.GainMicroModem = m.RéglerGainMicroModem
	c.GainÉcouteModem = m.RéglerGainÉcouteModem
	c.RéaffirmerVoix = func() error { return m.RéaffirmerVoixUSB(o.ModePCM) }
	c.AppelsVoix = func() int { return compterVoix(m) }
	c.Composer = m.Composer
	c.Fusionner = m.FusionnerAppels
	c.Touches = m.EnvoyerTouches
	c.Messagerie = m.LireAttenteMessagerie
	c.NuméroMessagerie = m.NuméroMessagerie
	c.Attente = m.MettreEnAttente
	c.AppelEntrant = m.AppelEntrant
	c.lireRéglagesModem(m)

	ctxVeille, arrêter := context.WithCancel(ctx)
	defer arrêter()

	var décrochéÀ time.Time
	c.Répondre = func() error {
		if err := m.Répondre(); err != nil {
			return err
		}
		décrochéÀ = time.Now()

		// Tous les réglages du modem D'ABORD, aucun flux encore ouvert :
		// chacun ferme et rouvre le périphérique USB, ce qui tuerait un
		// flux déjà en place.
		//
		// On les pose SANS passer par les méthodes du combiné : chacune
		// réaffirme le canal derrière elle, et l'on démonterait le
		// périphérique trois fois de suite. Une seule réaffirmation, à la
		// fin, suffit et laisse la carte se rétablir une seule fois.
		if o.VolumeÉcoute >= 0 {
			if err := m.RéglerVolumeÉcoute(o.VolumeÉcoute); err != nil {
				slog.Warn("volume d'écoute refusé", "err", err)
			} else {
				c.volumeModem.Store(int64(o.VolumeÉcoute))
			}
		}
		if err := m.RéglerRéductionBruit(o.Bruit); err != nil {
			slog.Warn("réduction de bruit refusée", "err", err)
		} else {
			c.bruitModem.Store(o.Bruit)
		}
		if err := m.RéaffirmerVoixUSB(o.ModePCM); err != nil {
			slog.Warn("canal voix non réaffirmé", "err", err)
		}
		time.Sleep(DélaiRoutage)

		c.hpOuvert.Store(true)
		if err := c.Démarrer(ctx, o.Micro); err != nil {
			slog.Warn("combiné non démarré", "err", err)
			return err
		}
		res.Combiné = true
		slog.Info("appel pris")
		return nil
	}

	go c.SonnerÀLArrivée(ctxVeille)
	go PiloteCombiné(o.Pilote)(ctxVeille, c, arrêter)
	surveiller(ctxVeille, m, &décrochéÀ)

	if !décrochéÀ.IsZero() {
		res.Décroché = true
		res.DécrochéÀ = décrochéÀ.Format(time.RFC3339)
		res.DuréeSec = int(time.Since(décrochéÀ).Seconds())
		if err := m.Raccrocher(); err != nil {
			slog.Warn("raccrochage", "err", err)
		}
	}
	res.Micro = c.MicOuvert()
	return res, nil
}

// surveiller rend la main quand la conversation prise se termine.
//
// Tant que rien n'a été décroché, on attend indéfiniment : c'est le propre
// d'un poste en veille. Une fois l'appel pris, sa disparition de +CLCC vaut
// raccrochage du correspondant.
func surveiller(ctx context.Context, m *Modem, décrochéÀ *time.Time) {
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(CadenceVeille):
		}
		if décrochéÀ.IsZero() {
			continue
		}
		if compterVoix(m) == 0 {
			slog.Info("le correspondant a raccroché")
			return
		}
	}
}

// compterVoix rend le nombre d'appels VOCAUX, ou -1 si on ne peut pas lire.
//
// Le porteur de données LTE apparaît dans +CLCC comme un appel actif : le
// compter ferait croire à une conversation en cours en permanence.
func compterVoix(m *Modem) int {
	appels, err := m.Appels()
	if err != nil {
		return -1
	}
	n := 0
	for _, a := range appels {
		if a.Voix() {
			n++
		}
	}
	return n
}
