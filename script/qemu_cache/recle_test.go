// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// ancienneCle reproduit la règle d'AVANT : le chemin entier, tel que le
// magasin le hachait jusqu'à la normalisation. Les objets déjà rangés sur un
// disque portent cette clé-là, et c'est d'eux que la passe s'occupe.
func ancienneCle(methode string, u *url.URL) string {
	sum := sha256.Sum256([]byte(methode + " path " + u.Path))
	return hex.EncodeToString(sum[:])
}

// planter écrit un objet sous la clé donnée, comme le magasin l'aurait fait.
func planter(t *testing.T, s *Store, cle, brut, corps string) {
	t.Helper()
	w, err := s.NewWriter(cle, Meta{
		URL: brut, Method: "GET", Status: 200, Class: "immutable",
	})
	if err != nil {
		t.Fatalf("écriture de %s : %v", brut, err)
	}
	if _, err := w.Write([]byte(corps)); err != nil {
		t.Fatal(err)
	}
	if err := w.Commit(int64(len(corps))); err != nil {
		t.Fatalf("publication de %s : %v", brut, err)
	}
}

const (
	rockyA = "https://a.example/rocky/10.2/AppStream/x86_64/os/Packages/r/rust-1.92.0-2.el10_2.x86_64.rpm"
	rockyB = "https://b.example/mirror/rocky-linux/10.2/AppStream/x86_64/os/Packages/r/rust-1.92.0-2.el10_2.x86_64.rpm"
)

// Un objet rangé sous l'ancienne clé est introuvable : le service le
// redemande à l'amont alors qu'il est sur le disque. La passe le range sous la
// clé courante, sans rien retélécharger.
func TestReclerRendTrouvableUnObjetAncien(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	u, _ := url.Parse(rockyA)
	planter(t, s, ancienneCle("GET", u), rockyA, "le paquet")

	if s.Detient(CleDe("GET", u)) {
		t.Fatal("l'objet est déjà trouvable : le test ne mesure rien")
	}
	bilan, err := s.Recler(false)
	if err != nil {
		t.Fatal(err)
	}
	if bilan.Deplaces != 1 || bilan.Fondus != 0 {
		t.Errorf("bilan %+v, attendu un seul déplacement", bilan)
	}
	if !s.Detient(CleDe("GET", u)) {
		t.Error("l'objet reste introuvable après la passe")
	}
	m, f, err := s.Get(CleDe("GET", u))
	if err != nil {
		t.Fatalf("lecture après passe : %v", err)
	}
	defer f.Close()
	if m.URL != rockyA {
		t.Errorf("méta perdu en route : %q", m.URL)
	}
}

// Deux chemins de miroir pour le même fichier : la clé courante les réunit, et
// la passe n'en garde qu'un — le plus récemment rangé.
//
// Les deux DIRECTIONS sont éprouvées, et l'ordre est fixé en plantant d'abord
// l'objet de destination : laisser le parcours décider laquelle des deux
// copies arrive la première ne couvrait qu'une branche sur deux, au gré du
// hachage, et la branche non couverte est passée au travers d'une mutation.
func TestReclerFondLesCopiesDeMiroir(t *testing.T) {
	ua, _ := url.Parse(rockyA)

	t.Run("entrante plus ancienne", func(t *testing.T) {
		s := &Store{Dir: t.TempDir()}
		planter(t, s, ancienneCle("GET", ua), rockyA, "copie ancienne")
		planter(t, s, CleDe("GET", ua), rockyB, "copie en place, plus recente")

		bilan, err := s.Recler(false)
		if err != nil {
			t.Fatal(err)
		}
		if bilan.Fondus != 1 || bilan.OctetsRendus == 0 {
			t.Errorf("bilan %+v, attendu une fusion qui rend des octets", bilan)
		}
		if corps := corpsDuMagasin(t, s); corps != 1 {
			t.Errorf("%d corps sur le disque, attendu 1", corps)
		}
		if lu := lireCorps(t, s, CleDe("GET", ua)); lu != "copie en place, plus recente" {
			t.Errorf("la copie gardée est %q : la plus récente devait rester", lu)
		}
	})

	t.Run("entrante plus récente", func(t *testing.T) {
		s := &Store{Dir: t.TempDir()}
		planter(t, s, CleDe("GET", ua), rockyB, "copie en place, ancienne")
		planter(t, s, ancienneCle("GET", ua), rockyA, "copie entrante, recente")

		bilan, err := s.Recler(false)
		if err != nil {
			t.Fatal(err)
		}
		if bilan.Fondus != 1 || bilan.Deplaces != 1 {
			t.Errorf("bilan %+v, attendu une fusion et un déplacement", bilan)
		}
		if corps := corpsDuMagasin(t, s); corps != 1 {
			t.Errorf("%d corps sur le disque, attendu 1", corps)
		}
		if lu := lireCorps(t, s, CleDe("GET", ua)); lu != "copie entrante, recente" {
			t.Errorf("la copie gardée est %q : la plus récente devait rester", lu)
		}
	})
}

// corpsDuMagasin compte les corps réellement sur le disque : une copie qui
// n'est plus référencée mais reste écrite occupe la place qu'on croyait rendue.
func corpsDuMagasin(t *testing.T, s *Store) int {
	t.Helper()
	n := 0
	err := filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err == nil && info != nil && !info.IsDir() &&
			strings.HasSuffix(p, ".body") {
			n++
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return n
}

func lireCorps(t *testing.T, s *Store, cle string) string {
	t.Helper()
	_, f, err := s.Get(cle)
	if err != nil {
		t.Fatalf("lecture de %s : %v", cle, err)
	}
	defer f.Close()
	b, err := io.ReadAll(f)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// Un chemin court tient tout entier dans la clé : rien ne doit bouger.
func TestReclerNeTouchePasUnCheminCourt(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	brut := "https://a.example/core/os/x86_64/bash-5.3-1-x86_64.pkg.tar.zst"
	u, _ := url.Parse(brut)
	planter(t, s, CleDe("GET", u), brut, "paquet arch")

	bilan, err := s.Recler(false)
	if err != nil {
		t.Fatal(err)
	}
	if bilan.Deplaces != 0 || bilan.Inchanges != 1 {
		t.Errorf("bilan %+v, attendu un objet inchangé", bilan)
	}
	if !s.Detient(CleDe("GET", u)) {
		t.Error("un objet qui ne devait pas bouger a disparu")
	}
}

// Un statut seul est rangé sous une clé qui porte l'HÔTE : la règle du chemin
// ne le concerne pas, et le déplacer l'enverrait là où personne ne le lit.
func TestReclerLaisseLesStatutsSeuls(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	brut := "https://a.example/depot/releases/latest/download/outil.tar.gz"
	u, _ := url.Parse(brut)
	cle := CleStatut("GET", u)
	w, err := s.NewWriter(cle, Meta{
		URL: brut, Method: "GET", Status: 302, Class: "volatile",
		StatusOnly: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := w.Commit(0); err != nil {
		t.Fatal(err)
	}

	bilan, err := s.Recler(false)
	if err != nil {
		t.Fatal(err)
	}
	if bilan.Deplaces != 0 {
		t.Errorf("bilan %+v : un statut seul a été déplacé", bilan)
	}
	if _, err := s.LireMeta(cle); err != nil {
		t.Error("le statut seul n'est plus sous sa clé")
	}
}

// À blanc, la passe compte sans rien écrire : c'est ce qui permet de la lancer
// avant de décider.
func TestReclerABlancNeDeplaceRien(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	u, _ := url.Parse(rockyA)
	ancienne := ancienneCle("GET", u)
	planter(t, s, ancienne, rockyA, "le paquet")

	bilan, err := s.Recler(true)
	if err != nil {
		t.Fatal(err)
	}
	if bilan.Deplaces != 1 {
		t.Errorf("bilan %+v, attendu un déplacement annoncé", bilan)
	}
	if _, err := s.LireMeta(ancienne); err != nil {
		t.Error("l'objet a bougé alors que la passe était à blanc")
	}
	if s.Detient(CleDe("GET", u)) {
		t.Error("un objet est apparu sous la clé courante, à blanc")
	}
}
