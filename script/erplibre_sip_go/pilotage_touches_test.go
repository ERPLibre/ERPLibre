package main

import (
	"reflect"
	"testing"
)

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

// L'etat publie porte la boite vocale : la TUI ne peut pas la lire elle-meme,
// le service tenant le port du modem.
func TestLEtatPublieDitLaBoiteVocale(t *testing.T) {
	champs := reflect.VisibleFields(reflect.TypeOf(ÉtatCombiné{}))
	attendus := map[string]bool{
		"messagerie_connue": false, "messagerie_attente": false,
		"messagerie_numero": false,
	}
	for _, champ := range champs {
		nom := champ.Tag.Get("json")
		if _, voulu := attendus[nom]; voulu {
			attendus[nom] = true
		}
	}
	for nom, présent := range attendus {
		if !présent {
			t.Fatalf("l'état publié ne porte pas %q", nom)
		}
	}
}

// « Connue » distingue « pas de message » d'une lecture qui n'a pas eu lieu :
// sans elle, une SIM muette s'afficherait comme une boite vide.
func TestUneLectureImpossibleNeDitPasBoiteVide(t *testing.T) {
	é := ÉtatCombiné{}
	if é.MessagerieConnue {
		t.Fatal("état neuf déclaré connu")
	}
}
