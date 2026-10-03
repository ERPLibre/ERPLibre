// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestLeNIPSeRemetEtNeRessortPas(t *testing.T) {
	secrets := &Secrets{}

	if r := TraiterCommande("ETAT", secrets); r != "OK nip=non" {
		t.Fatalf("etat initial : %q", r)
	}
	if r := TraiterCommande("NIP 864209", secrets); r != "OK" {
		t.Fatalf("remise refusee : %q", r)
	}
	if secrets.NIP() != "864209" {
		t.Fatalf("code garde : %q", secrets.NIP())
	}
	// L'état DIT qu'un code est là ; il ne le rend pas. Un état bavard
	// ferait du journal et de l'écran autant d'endroits où le lire.
	état := TraiterCommande("ETAT", secrets)
	if état != "OK nip=oui" {
		t.Fatalf("etat apres remise : %q", état)
	}
	if strings.Contains(état, "864209") {
		t.Fatal("l'etat rend le code")
	}
}

func TestUneRemiseRemplaceLaPrecedente(t *testing.T) {
	secrets := &Secrets{}
	TraiterCommande("NIP 111111", secrets)
	TraiterCommande("NIP 222222", secrets)

	if secrets.NIP() != "222222" {
		t.Fatalf("code garde : %q — une correction doit prendre", secrets.NIP())
	}
}

func TestUneCommandeVideOuInconnueEstRefusee(t *testing.T) {
	secrets := &Secrets{}
	for _, ligne := range []string{"NIP", "NIP   ", "RIEN", "", "nip"} {
		if r := TraiterCommande(ligne, secrets); !strings.HasPrefix(r, "ERREUR") {
			// « nip » en minuscules DOIT passer : le verbe est insensible à
			// la casse, et cette ligne-là n'a pas de code.
			if strings.EqualFold(strings.Fields(ligne + " x")[0], CommandeNIP) {
				continue
			}
			t.Fatalf("%q acceptee : %q", ligne, r)
		}
	}
	if secrets.ADéjàLeNIP() {
		t.Fatal("un refus a quand meme pose un code")
	}
}

func TestLaSocketNEstLisibleQueParSonCompte(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "controle.sock")
	secrets := &Secrets{}
	ctx, arrêter := context.WithCancel(context.Background())
	defer arrêter()
	go func() {
		if err := ÉcouterLesCommandes(ctx, chemin, secrets); err != nil {
			t.Errorf("ecoute : %v", err)
		}
	}()
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(chemin); err == nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	info, err := os.Stat(chemin)
	if err != nil {
		t.Fatal(err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Fatalf("droits %o : le secret passe par la, seul son compte y touche",
			mode)
	}

	conn, err := net.Dial("unix", chemin)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Write([]byte("NIP 864209\n")); err != nil {
		t.Fatal(err)
	}
	réponse, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(réponse) != "OK" {
		t.Fatalf("reponse %q", réponse)
	}
	if secrets.NIP() != "864209" {
		t.Fatalf("le code n'a pas traverse la socket : %q", secrets.NIP())
	}

	// L'arrêt retire la socket : laissée en place, elle ferait croire à un
	// service vivant et la remise suivante attendrait une réponse qui ne
	// vient pas.
	arrêter()
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(chemin); os.IsNotExist(err) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("la socket survit a l'arret du service")
}
