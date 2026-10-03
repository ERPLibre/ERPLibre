package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Deux cartes, telles que le noyau les ecrit : un portable et un modem USB.
const cartesDEssai = ` 0 [sofhdadsp      ]: sof-hda-dsp - sof-hda-dsp
                      LENOVO ThinkPad
 1 [EC25AF         ]: USB-Audio - EC25-AF
                      Quectel EC25-AF at usb-0000:00:14.0-9, high speed
`

func poserCartes(t *testing.T, contenu string) {
	t.Helper()
	chemin := filepath.Join(t.TempDir(), "cards")
	if err := os.WriteFile(chemin, []byte(contenu), 0o600); err != nil {
		t.Fatalf("écriture : %v", err)
	}
	ancien := FichierCartes
	FichierCartes = chemin
	t.Cleanup(func() { FichierCartes = ancien })
}

func TestLesCartesSeLisentAvecLeurIndex(t *testing.T) {
	poserCartes(t, cartesDEssai)
	cartes, err := CartesDéclarées()
	if err != nil {
		t.Fatalf("lecture : %v", err)
	}
	if len(cartes) != 2 || cartes[0] != "sofhdadsp" || cartes[1] != "EC25AF" {
		t.Fatalf("cartes lues : %v", cartes)
	}
}

// Le defaut vecu : « hw:2,0 » sur une machine qui n'a que 0 et 1. Sans ce
// refus, il ne se voit qu'a l'ouverture — donc apres le decroche.
func TestUneCarteInexistanteEstRefusee(t *testing.T) {
	poserCartes(t, cartesDEssai)
	err := VérifierCarte("hw:2,0")
	if err == nil {
		t.Fatal("acceptée alors qu'aucune carte n'a l'index 2")
	}
	message := err.Error()
	// Le message doit dire CE QU'IL Y A, sinon il faut aller chercher
	// ailleurs ce que le programme savait déjà.
	for _, attendu := range []string{"hw:2,0", "0 (sofhdadsp)", "1 (EC25AF)"} {
		if !strings.Contains(message, attendu) {
			t.Fatalf("« %s » absent du message : %s", attendu, message)
		}
	}
}

func TestUneCartePresenteEstAcceptee(t *testing.T) {
	poserCartes(t, cartesDEssai)
	for _, nom := range []string{"hw:0,0", "hw:1,0", "plughw:1,0"} {
		if err := VérifierCarte(nom); err != nil {
			t.Fatalf("%s refusée : %v", nom, err)
		}
	}
}

// Un peripherique du serveur audio ne figure pas dans ce fichier : le refuser
// sur ce motif interdirait un usage valable.
func TestUnPeripheriqueDuServeurAudioNEstPasJuge(t *testing.T) {
	poserCartes(t, cartesDEssai)
	for _, nom := range []string{"pw:alsa_output.usb-x", "default", ""} {
		if err := VérifierCarte(nom); err != nil {
			t.Fatalf("%q refusé alors qu'il n'est pas une carte ALSA : %v", nom, err)
		}
	}
}

// Aucune carte du tout : c'est ce qu'on voit quand l'UAC du modem n'est pas
// active, et le message doit le laisser deviner plutot que de dire « rien ».
func TestSansAucuneCarteLeMessageLeDit(t *testing.T) {
	poserCartes(t, "--- no soundcards ---\n")
	err := VérifierCarte("hw:1,0")
	if err == nil {
		t.Fatal("acceptée alors qu'il n'y a aucune carte")
	}
	if !strings.Contains(err.Error(), "aucune") {
		t.Fatalf("message peu parlant : %s", err)
	}
}

// La carte nommee a la main passe par la meme verification que celle qui est
// detectee : c'est justement celle-la qu'on se trompe a ecrire.
func TestLaCarteNommeeAlaMainEstVerifiee(t *testing.T) {
	poserCartes(t, cartesDEssai)
	if _, err := carteOuDéfaut("hw:2,0"); err == nil {
		t.Fatal("une carte nommée à la main échappe à la vérification")
	}
	if carte, err := carteOuDéfaut("hw:1,0"); err != nil || carte != "hw:1,0" {
		t.Fatalf("carte valide refusée : %q / %v", carte, err)
	}
}

func TestLaDetectionTrouveLeModemParSonNom(t *testing.T) {
	poserCartes(t, cartesDEssai)
	carte, err := CarteModem()
	if err != nil {
		t.Fatalf("modem non trouvé : %v", err)
	}
	if carte != "hw:1,0" {
		t.Fatalf("carte %q au lieu de hw:1,0", carte)
	}
}
