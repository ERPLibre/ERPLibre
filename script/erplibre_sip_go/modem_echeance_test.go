// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"os"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// TestUneLectureSansReponseRendLaMain tient la correction la plus couteuse de
// ce fichier : `Fd()` sortait le port du scrutateur de Go et le repassait en
// mode bloquant, `SetDeadline` cessait d'avoir le moindre effet SANS rendre
// d'erreur, et une commande AT restee sans reponse bloquait pour toujours — le
// verrou de parole avec elle. La ligne restait ouverte et facturee, et plus
// aucun appel n'entrait.
//
// Une paire de sockets tient lieu de port : l'ecriture y reussit, personne ne
// repond, et la lecture ne peut donc aboutir que par l'echeance.
func TestUneLectureSansReponseRendLaMain(t *testing.T) {
	paire, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	// Non bloquant AVANT `os.NewFile`, comme le vrai port : c'est ce qui met
	// le descripteur sous le scrutateur de Go, et donc ce qui rend
	// `SetDeadline` effectif.
	if err := unix.SetNonblock(paire[0], true); err != nil {
		t.Fatal(err)
	}
	notre := os.NewFile(uintptr(paire[0]), "faux-port-at")
	muet := os.NewFile(uintptr(paire[1]), "bout-muet")
	defer notre.Close()
	defer muet.Close()

	m := &Modem{f: notre, br: bufio.NewReader(notre)}
	départ := time.Now()
	_, err = m.Commande("AT+RIEN", 300*time.Millisecond)
	écoulé := time.Since(départ)

	if err == nil {
		t.Fatal("une commande sans reponse doit rendre une erreur")
	}
	if écoulé < 200*time.Millisecond {
		t.Fatalf("rendu en %s : l'ecriture a echoue, l'echeance n'est pas"+
			" ce qui a borne la lecture", écoulé)
	}
	if écoulé > 3*time.Second {
		t.Fatalf("la lecture a dure %s : l'echeance n'a pas pris effet", écoulé)
	}
}

// TestLePortRefuseDEtreOuvertSansEcheance dit pourquoi l'ouverture controle.
func TestLePortRefuseDEtreOuvertSansEcheance(t *testing.T) {
	// Un fichier ORDINAIRE n'est pas scrutable : `SetDeadline` y rend
	// `ErrNoDeadline`, ce qui est exactement le cas qu'on refuse a l'ouverture.
	chemin := t.TempDir() + "/pas-un-port"
	f, err := os.Create(chemin)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err := f.SetDeadline(time.Now().Add(time.Second)); err == nil {
		t.Skip("ce systeme borne meme un fichier ordinaire")
	}
	if _, err := OuvrirModem(chemin); err == nil {
		t.Fatal("un port dont les lectures ne se bornent pas doit etre refuse")
	}
}
