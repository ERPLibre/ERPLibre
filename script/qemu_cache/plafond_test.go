// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestLireTaille(t *testing.T) {
	cas := map[string]int64{
		"50G":   50 << 30,
		"50Gio": 50 << 30,
		"50GiB": 50 << 30,
		"1.5 G": 3 << 29,
		"500M":  500 << 20,
		"2t":    2 << 40,
		"1024":  1024,
		"64K":   64 << 10,
	}
	for brut, veut := range cas {
		if got, err := LireTaille(brut); err != nil || got != veut {
			t.Errorf("%q : %d (%v), attendu %d", brut, got, err, veut)
		}
	}
	for _, brut := range []string{"", "abc", "5X", "-1G", "0"} {
		if _, err := LireTaille(brut); err == nil {
			t.Errorf("%q accepté", brut)
		}
	}
}

// objetGarde range un corps de n octets, daté d'il y a `age`, et rend sa clé.
func objetGarde(t *testing.T, s *Store, nom string, n int, age time.Duration) string {
	t.Helper()
	cle := Key("GET", "http://miroir.example/"+nom)
	w, err := s.NewWriter(cle, Meta{URL: "http://miroir.example/" + nom, Method: "GET", Status: 200})
	if err != nil {
		t.Fatal(err)
	}
	w.Write([]byte(strings.Repeat("x", n)))
	if err := w.Commit(int64(n)); err != nil {
		t.Fatal(err)
	}
	_, corps := s.paths(cle)
	quand := time.Now().Add(-age)
	os.Chtimes(corps, quand, quand)
	return cle
}

// Le moins récemment servi part d'abord, et la purge s'arrête dès que le
// cache tient sous le plafond : effacer plus rendrait de la place qu'on ne
// demandait pas, au prix de téléchargements repayés.
func TestLePlafondEffaceLePlusAncienDAbord(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	vieux := objetGarde(t, s, "vieux", 100, 90*24*time.Hour)
	moyen := objetGarde(t, s, "moyen", 100, 30*24*time.Hour)
	recent := objetGarde(t, s, "recent", 100, time.Hour)

	b, err := PurgerJusqua(s, &GitMirror{}, 250, false)
	if err != nil {
		t.Fatal(err)
	}
	if b.Objets != 1 || b.Avant != 300 || b.Apres != 200 {
		t.Errorf("bilan %+v, attendu 1 objet, 300 → 200", b)
	}
	if s.Detient(vieux) {
		t.Error("le plus ancien est resté")
	}
	if !s.Detient(moyen) || !s.Detient(recent) {
		t.Error("un objet plus récent est parti")
	}
	if metaPath, _ := s.paths(vieux); fichierExiste(metaPath) {
		t.Error("le méta de l'objet effacé est resté")
	}
}

func fichierExiste(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func TestSousLePlafondRienNePart(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	cle := objetGarde(t, s, "seul", 100, 90*24*time.Hour)
	b, _ := PurgerJusqua(s, &GitMirror{}, 1000, false)
	if b.Objets != 0 || !s.Detient(cle) {
		t.Errorf("sous le plafond, %d objet(s) effacé(s)", b.Objets)
	}
}

func TestABlancRienNEstEfface(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	cle := objetGarde(t, s, "vieux", 100, 90*24*time.Hour)
	objetGarde(t, s, "recent", 100, time.Hour)
	b, _ := PurgerJusqua(s, &GitMirror{}, 150, true)
	if b.Objets != 1 || b.Apres != 100 {
		t.Errorf("bilan à blanc %+v, attendu 1 objet compté", b)
	}
	if !s.Detient(cle) {
		t.Error("une purge à blanc a effacé un objet")
	}
}

// Objets et dépôts se disputent le même disque : un dépôt oublié depuis des
// mois part avant des paquets servis récemment.
func TestUnDepotOublieCedeSaPlaceAvantLesObjets(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	objet := objetGarde(t, s, "paquet", 100, time.Hour)
	m := &GitMirror{Dir: t.TempDir()}
	depot := filepath.Join(m.Dir, "forge.example", "vieux.git")
	if err := os.MkdirAll(depot, 0o755); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(depot, "pack"), []byte(strings.Repeat("y", 500)), 0o644)
	quand := time.Now().Add(-120 * 24 * time.Hour)
	os.Chtimes(depot, quand, quand)

	b, err := PurgerJusqua(s, m, 200, false)
	if err != nil {
		t.Fatal(err)
	}
	if b.Depots != 1 || b.Objets != 0 {
		t.Errorf("bilan %+v, attendu le seul dépôt", b)
	}
	if fichierExiste(depot) {
		t.Error("le dépôt oublié est resté")
	}
	if !s.Detient(objet) {
		t.Error("l'objet récent est parti avant le dépôt oublié")
	}
}
