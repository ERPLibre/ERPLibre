package main

import (
	"fmt"
	"os"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

// pseudoPort rend un port serie de laboratoire.
//
// Un fichier ordinaire ne convient pas : `OuvrirModem` pose le mode brut par
// un ioctl que seul un terminal accepte, et le test s'ignorerait — ce qui ne
// prouve rien. Un pseudo-terminal en est un vrai, sans materiel.
func pseudoPort(t *testing.T) string {
	t.Helper()
	maitre, err := os.OpenFile("/dev/ptmx", os.O_RDWR, 0)
	if err != nil {
		t.Skipf("pas de pseudo-terminal sur cette machine : %v", err)
	}
	t.Cleanup(func() { _ = maitre.Close() })

	// Deverrouiller l'esclave, puis demander son numero : sans le premier,
	// l'ouverture du second echoue.
	if err := unix.IoctlSetPointerInt(int(maitre.Fd()), unix.TIOCSPTLCK, 0); err != nil {
		t.Fatalf("deverrouillage : %v", err)
	}
	numero, err := unix.IoctlGetInt(int(maitre.Fd()), unix.TIOCGPTN)
	if err != nil {
		t.Fatalf("numero du pseudo-terminal : %v", err)
	}
	return fmt.Sprintf("/dev/pts/%d", numero)
}

// Un port serie s'ouvre autant de fois qu'on veut, sans que rien ne le
// signale : deux processus entrelacent alors leurs commandes AT, et ce qu'on
// observe n'est pas une erreur mais un SILENCE — un appel entrant que
// personne ne voit. Le verrou transforme ce silence en refus.
func TestUnSecondAccesAuPortEstRefuse(t *testing.T) {
	port := pseudoPort(t)

	premier, err := OuvrirModem(port)
	if err != nil {
		t.Fatalf("premier accès refusé : %v", err)
	}
	defer premier.Close()

	_, err = OuvrirModem(port)
	if err == nil {
		t.Fatal("un second accès est accepté : les commandes AT s'entrelaceront")
	}
	// Le message doit dire QUOI ARRETER, sinon on cherche du cote du modem,
	// du reseau ou de l'operateur, ou il n'y a rien.
	for _, attendu := range []string{"deja tenu", "veille", "softphone"} {
		if !strings.Contains(err.Error(), attendu) {
			t.Fatalf("« %s » absent du message : %s", attendu, err)
		}
	}
}

// Le verrou disparait avec le processus qui le tient : rien a nettoyer apres
// un plantage, et le port se reprend au demarrage suivant.
func TestLePortSeLibereALaFermeture(t *testing.T) {
	port := pseudoPort(t)

	premier, err := OuvrirModem(port)
	if err != nil {
		t.Fatalf("premier accès refusé : %v", err)
	}
	_ = premier.Close()

	second, err := OuvrirModem(port)
	if err != nil {
		t.Fatalf("le port reste verrouillé après fermeture : %v", err)
	}
	_ = second.Close()
}
