package main

import (
	"path/filepath"
	"testing"
)

// Les recettes livrees avec la TUI sont verifiees par le MEME code que le
// service : une recette qui passerait cote Python et serait refusee ici
// echouerait au moment de composer, appel deja facture.
func TestLesRecettesLivreesSontValides(t *testing.T) {
	fichiers, err := filepath.Glob("../todo/modem/recettes/*.json")
	if err != nil || len(fichiers) == 0 {
		t.Fatalf("aucune recette trouvée : %v", err)
	}
	for _, f := range fichiers {
		if _, err := ChargerRecette(f); err != nil {
			t.Fatalf("%s : %v", f, err)
		}
	}
}
