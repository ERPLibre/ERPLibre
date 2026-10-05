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

func TestRouvrirReprendLePortSousLeMemeNom(t *testing.T) {
	// Ce que fait une mise en veille : le noeud disparait du bus et revient,
	// et le lien udev pointe alors un nouveau ttyUSB sous le meme nom. Le
	// descripteur d'avant ne rend plus qu'une erreur.
	chemin := pseudoPort(t)
	m, err := OuvrirModem(chemin)
	if err != nil {
		t.Fatalf("ouverture : %v", err)
	}
	defer m.Close()
	avant := m.f

	if err := m.Rouvrir(); err != nil {
		t.Fatalf("reouverture : %v", err)
	}
	if m.f == avant {
		t.Fatal("le descripteur n'a pas change : rien n'a ete rouvert")
	}
	// Le verrou du noyau suit le nouveau descripteur : sans la fermeture de
	// l'ancien, il tiendrait encore et la reouverture aurait echoue.
	if m.br == nil {
		t.Fatal("le lecteur tamponne pointe encore l'ancien descripteur")
	}
}

func TestRouvrirRefusePendantUneConversation(t *testing.T) {
	// Le port sert a l'appel en cours : le reprendre le couperait. Et une
	// ligne qui tient encore dit justement que le port n'est pas mort.
	m, err := OuvrirModem(pseudoPort(t))
	if err != nil {
		t.Fatalf("ouverture : %v", err)
	}
	defer m.Close()
	if !m.PrendreLaLigne() {
		t.Fatal("la ligne devrait etre libre")
	}
	defer m.RendreLaLigne()

	if err := m.Rouvrir(); err == nil {
		t.Fatal("une conversation en cours n'a pas empeche la reprise du port")
	}
}

func TestUnPortDisparuSeRefuseAuLieuDeSeTaire(t *testing.T) {
	// Rouvrir ce qui n'existe plus doit RENDRE une erreur : avalee, elle
	// laisserait le service croire qu'il a repris la main.
	m, err := OuvrirModem(pseudoPort(t))
	if err != nil {
		t.Fatalf("ouverture : %v", err)
	}
	defer m.Close()
	m.chemin = "/dev/ce-port-n-existe-pas"

	if err := m.Rouvrir(); err == nil {
		t.Fatal("la reouverture d'un port absent s'est dite reussie")
	}
}
