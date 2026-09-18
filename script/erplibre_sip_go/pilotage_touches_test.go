package main

import "testing"

// La commande « touches » du protocole de pilotage atteint le modem : sans
// elle, une messagerie d'operateur s'ecoute jusqu'a l'accueil et pas plus loin.
func TestLaCommandeTouchesAtteintLeModem(t *testing.T) {
	var reçues string
	c := &Combiné{Touches: func(s string) error { reçues += s; return nil }}
	if appliquerCommande(c, "touches 1234#", func() {}) {
		t.Fatal("« touches » a demandé l'arrêt")
	}
	if reçues != "1234#" {
		t.Fatalf("touches reçues %q", reçues)
	}
	// Hors mode modem, aucune fonction : la commande est ignorée sans panique.
	appliquerCommande(&Combiné{}, "touches 1", func() {})
}
