package main

import "testing"

// La SIM ne porte qu'UNE conversation. Deux chemins s'en servent — la veille
// des appels entrants et la composition sortante — et rien ne les arbitrait :
// le raccrochage du premier tombait sur le second, qui perdait sa ligne
// quelques secondes apres l'avoir prise, sans qu'aucune erreur ne le dise.
func TestLaLigneNeSePrendPasDeuxFois(t *testing.T) {
	m := &Modem{}
	if !m.PrendreLaLigne() {
		t.Fatal("ligne libre refusée")
	}
	if m.PrendreLaLigne() {
		t.Fatal("ligne prise deux fois : un appel en couperait un autre")
	}
	m.RendreLaLigne()
	if !m.PrendreLaLigne() {
		t.Fatal("ligne non rendue : plus aucun appel ne passera")
	}
	m.RendreLaLigne()
}

// Un refus doit etre IMMEDIAT et non une attente : un appel qu'on ne peut pas
// passer se refuse tout de suite, une attente muette laissant sonner un
// correspondant que personne ne prendra.
func TestUneLigneOccupeeRefuseSansAttendre(t *testing.T) {
	m := &Modem{}
	m.PrendreLaLigne()
	defer m.RendreLaLigne()

	fini := make(chan bool, 1)
	go func() { fini <- m.PrendreLaLigne() }()
	if <-fini {
		t.Fatal("ligne accordée alors qu'elle est tenue")
	}
}

// `Fermer` rend la ligne, sans quoi le premier appel sortant la garderait pour
// toujours et la passerelle deviendrait sourde apres lui.
func TestFermerUneLigneModemLaRend(t *testing.T) {
	m := &Modem{}
	ligne := &LigneModem{modem: m}
	if !m.PrendreLaLigne() {
		t.Fatal("ligne libre refusée")
	}
	ligne.Fermer()
	if !m.PrendreLaLigne() {
		t.Fatal("ligne non rendue à la fermeture")
	}
	m.RendreLaLigne()
}
