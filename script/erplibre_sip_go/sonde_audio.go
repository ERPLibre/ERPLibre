// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"math"
	"os/exec"
	"strings"
	"time"
)

// DuréeSonde est le temps d'écoute accordé à la ligne.
//
// Huit secondes : la personne au bout du fil doit avoir entendu la consigne,
// pris son souffle et parlé. Une fenêtre courte mesure surtout le silence
// de quelqu'un qui vient de décrocher, et fait conclure à tort que rien ne
// passe.
const DuréeSonde = 8 * time.Second

// SeuilSilence sépare une ligne muette d'une ligne qui porte du signal.
//
// Sur seize bits signés, une capture réellement morte rend exactement 0 ;
// un canal ouvert sur une ligne calme rend tout de même le bruit de fond du
// codec. Le seuil reste bas pour ne pas exiger que quelqu'un parle.
const SeuilSilence = 30.0

// RésultatSonde est ce qu'un mode a donné à l'oreille de la machine.
type RésultatSonde struct {
	Mode  int     `json:"mode"`
	RMS   float64 `json:"rms"`
	Vivan bool    `json:"vivant"`
	Err   string  `json:"erreur,omitempty"`
}

// SonderMode mesure les deux sens du chemin audio pour le mode en cours.
//
// UN SEUL mode par appel, et c'est une contrainte du modem, pas un choix :
// il fige le routage voix quand la voix s'établit et refuse ensuite
// AT+QPCMV par un ERROR. Comparer plusieurs modes demande donc un appel par
// mode, le mode étant posé avant la composition.
//
// Les deux sens ne se mesurent pas de la même façon. La DESCENTE se mesure
// ici : ce que la carte capture est ce que le modem reçoit du réseau, donc
// la voix du correspondant. La MONTÉE ne se mesure pas depuis cette
// machine — seule l'oreille au bout du fil dit si l'annonce est passée,
// d'où sa lecture au début.
func SonderMode(ctx context.Context, carte string, mode int, annonce string) []RésultatSonde {
	r := RésultatSonde{Mode: mode}
	if annonce != "" {
		// Joue d'abord : le correspondant sait alors quoi écouter, et sa
		// réponse renseigne la montée que la mesure ne voit pas.
		if err := jouerSurCarte(ctx, carte, annonce); err != nil {
			slog.Warn("annonce non jouée", "err", err)
		} else {
			slog.Info("annonce jouée — le correspondant l'a-t-il entendue ?")
		}
	}
	slog.Info("écoute de la descente — que le correspondant parle MAINTENANT",
		"duree_s", int(DuréeSonde.Seconds()))
	rms, err := écouterRMS(ctx, carte, DuréeSonde)
	if err != nil {
		r.Err = err.Error()
	} else {
		r.RMS = rms
		r.Vivan = rms >= SeuilSilence
	}
	slog.Info("sonde audio", "mode", mode, "rms", fmt.Sprintf("%.1f", rms),
		"vivant", r.Vivan)
	return []RésultatSonde{r}
}

// écouterRMS capture la carte et rend l'énergie moyenne du signal.
//
// Capture en brut plutôt qu'en WAV : il n'y a alors pas d'en-tête à sauter,
// dont la taille varie selon l'outil qui l'écrit.
func écouterRMS(ctx context.Context, carte string, durée time.Duration) (float64, error) {
	c := exec.CommandContext(ctx, "arecord",
		"-D", carte,
		"-f", FormatVoix,
		"-c", "1",
		"-r", TauxVoix,
		"-t", "raw",
		"-d", fmt.Sprintf("%d", int(durée.Seconds())))
	var sortie, plainte bytes.Buffer
	c.Stdout = &sortie
	// La plainte d'arecord dit CE QUI a échoué — « périphérique occupé »
	// quand un serveur audio s'est approprié la carte. La jeter ne laissait
	// qu'un « exit status 1 » qui n'oriente vers rien.
	c.Stderr = &plainte
	if err := c.Run(); err != nil {
		return 0, fmt.Errorf("arecord : %w : %s", err,
			strings.TrimSpace(plainte.String()))
	}
	données := sortie.Bytes()
	if len(données) < 2 {
		return 0, fmt.Errorf("capture vide")
	}
	var somme float64
	n := len(données) / 2
	for i := 0; i < n; i++ {
		é := int16(binary.LittleEndian.Uint16(données[i*2:]))
		somme += float64(é) * float64(é)
	}
	return math.Sqrt(somme / float64(n)), nil
}
