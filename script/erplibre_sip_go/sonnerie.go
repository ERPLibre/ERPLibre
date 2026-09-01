// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"encoding/binary"
	"log/slog"
	"math"
	"time"
)

// Cadence de sonnerie nord-américaine : deux secondes de son, quatre de
// silence. On la reprend telle quelle plutôt que d'en inventer une : elle
// se reconnaît sans qu'on l'explique.
const (
	DuréeSonnerie = 2 * time.Second
	PauseSonnerie = 4 * time.Second

	// Deux fréquences mêlées, comme une tonalité d'appel. Une seule sonne
	// comme une alarme ; deux sonnent comme un téléphone.
	SonnerieGrave = 440.0
	SonnerieAigu  = 480.0

	// Amplitude de chaque composante. Deux tiers de la pleine échelle une
	// fois additionnées : assez pour s'entendre à travers une pièce, sans
	// saturer.
	AmplitudeSonnerie = 10000.0
)

// Sonnerie dit si le poste sonne à l'arrivée d'un appel.
func (c *Combiné) Sonnerie() bool { return c.sonnerie.Load() }

// BasculerSonnerie inverse la sonnerie et rend le nouvel état.
func (c *Combiné) BasculerSonnerie() bool {
	n := !c.sonnerie.Load()
	c.sonnerie.Store(n)
	return n
}

// SonnerÀLArrivée fait sonner le poste tant qu'un appel se présente.
//
// Le son sort sur la sortie LOCALE, jamais sur la carte du modem : celle-ci
// porte la ligne, et y verser une sonnerie la ferait entendre au
// correspondant. Elle ne touche donc à rien de ce que le décrochage
// réaffirme.
//
// Une salve à la fois, ouverte puis refermée : entre deux salves, le
// périphérique est rendu au système, qui peut ainsi servir autre chose.
func (c *Combiné) SonnerÀLArrivée(ctx context.Context) {
	salve := construireSalve()
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(CadenceÉtat):
		}
		if c.AppelEntrant == nil || c.AppelEntrant() == "" || !c.Sonnerie() {
			continue
		}
		if err := c.jouerSalve(ctx, salve); err != nil {
			slog.Warn("sonnerie muette", "err", err)
			// Ne pas réessayer sans répit : une sortie indisponible
			// tournerait en boucle pendant toute la sonnerie.
			select {
			case <-ctx.Done():
				return
			case <-time.After(PauseSonnerie):
			}
			continue
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(PauseSonnerie):
		}
	}
}

// jouerSalve écrit une salve sur la sortie locale et referme.
func (c *Combiné) jouerSalve(ctx context.Context, salve []byte) error {
	sortie, _ := c.périphHP.Load().(string)
	cmd := commandePour(ctx, sortie, "aplay", "pw-play")
	entrée, err := cmd.StdinPipe()
	if err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	_, err = entrée.Write(salve)
	_ = entrée.Close()
	_ = cmd.Wait()
	return err
}

// construireSalve fabrique la salve une fois pour toutes.
func construireSalve() []byte {
	n := int(TauxVoixHz * DuréeSonnerie.Seconds())
	b := make([]byte, n*2)
	for i := 0; i < n; i++ {
		t := float64(i) / TauxVoixHz
		v := AmplitudeSonnerie * (math.Sin(2*math.Pi*SonnerieGrave*t) +
			math.Sin(2*math.Pi*SonnerieAigu*t)) / 2
		// Fondu de dix millisecondes aux deux bouts : une salve qui démarre
		// net produit un claquement, plus désagréable que la sonnerie.
		v *= fondu(i, n, int(TauxVoixHz/100))
		binary.LittleEndian.PutUint16(b[i*2:], uint16(int16(v)))
	}
	return b
}

// fondu rend le facteur d'amplitude aux bords d'une salve.
func fondu(i, n, largeur int) float64 {
	if largeur <= 0 {
		return 1
	}
	if i < largeur {
		return float64(i) / float64(largeur)
	}
	if reste := n - 1 - i; reste < largeur {
		return float64(reste) / float64(largeur)
	}
	return 1
}
