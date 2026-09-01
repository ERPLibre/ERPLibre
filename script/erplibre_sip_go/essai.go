// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"log/slog"
	"time"
)

// PlafondEssai borne un essai qu'on oublierait de fermer.
const PlafondEssai = 5 * time.Minute

// EssaiCombiné ouvre le combiné SANS appeler personne.
//
// Sert à vérifier ce qui ne dépend pas de la ligne : que le micro est
// capté, que les touches répondent, que la carte du modem accepte les deux
// sens. Une conversation coûte un appel et l'attention de quelqu'un ; ces
// trois-là se vérifient seuls.
//
// Ce que l'essai NE PROUVE PAS : que la voix traverse. Hors appel le modem
// ne transporte rien, donc la barre du correspondant reste à zéro et c'est
// normal. Seule celle du micro doit bouger quand on parle.
func EssaiCombiné(ctx context.Context, carte string, micro, pilote bool) (Résultat, error) {
	res := Résultat{Numéro: "—"}
	c, err := OuvrirCombiné(ctx, carte, micro)
	if err != nil {
		res.Erreur = err.Error()
		return res, err
	}
	defer c.Fermer()
	res.Combiné = true

	slog.Info("essai du combiné — aucun appel n'est passé",
		"note", "la barre « lui » reste à zéro hors appel, c'est attendu")

	ctxEssai, arrêter := context.WithTimeout(ctx, PlafondEssai)
	defer arrêter()
	go PiloteCombiné(pilote)(ctxEssai, c, arrêter)

	début := time.Now()
	select {
	case <-ctxEssai.Done():
	case <-c.Fini:
	}
	res.DuréeSec = int(time.Since(début).Seconds())
	res.Micro = c.MicOuvert()
	return res, nil
}
