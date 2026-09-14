// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLireGranularite(t *testing.T) {
	for _, cas := range []struct {
		brut     string
		attendue Granularite
	}{
		{"jour", ParJour}, {"day", ParJour}, {"J", ParJour},
		{"semaine", ParSemaine}, {"week", ParSemaine}, {" W ", ParSemaine},
		{"mois", ParMois}, {"month", ParMois}, {"m", ParMois},
	} {
		g, err := LireGranularite(cas.brut)
		if err != nil || g != cas.attendue {
			t.Errorf("%q → %q, %v", cas.brut, g, err)
		}
	}
	if _, err := LireGranularite("trimestre"); err == nil {
		t.Error("une granularité inconnue est acceptée")
	}
}

// « 30d » n'existe pas dans la bibliothèque, et un opérateur qui nettoie
// raisonne en jours, pas en sept cent vingt heures.
func TestLireDuree(t *testing.T) {
	for _, cas := range []struct {
		brut     string
		attendue time.Duration
	}{
		{"30j", 30 * 24 * time.Hour},
		{"7d", 7 * 24 * time.Hour},
		{"12h", 12 * time.Hour},
		{"90m", 90 * time.Minute},
		{"0.5j", 12 * time.Hour},
	} {
		d, err := LireDuree(cas.brut)
		if err != nil || d != cas.attendue {
			t.Errorf("%q → %v, %v (attendu %v)", cas.brut, d, err, cas.attendue)
		}
	}
	for _, brut := range []string{"", "3lunes", "-5j", "abc"} {
		if d, err := LireDuree(brut); err == nil {
			t.Errorf("%q accepté et rendu %v", brut, d)
		}
	}
}

// La semaine commence le LUNDI : c'est la convention ISO, celle des outils du
// système. La ramener au dimanche donnerait des tranches qui ne correspondent
// à aucun autre relevé de la machine.
func TestLaSemaineCommenceLundi(t *testing.T) {
	// Un mercredi, et le dimanche qui le suit.
	mercredi := time.Date(2026, 9, 2, 15, 0, 0, 0, time.Local)
	dimanche := time.Date(2026, 9, 6, 15, 0, 0, 0, time.Local)
	a := debutDeTranche(mercredi, ParSemaine)
	b := debutDeTranche(dimanche, ParSemaine)
	if !a.Equal(b) {
		t.Errorf("mercredi et le dimanche suivant tombent dans deux"+
			" semaines : %s contre %s", a, b)
	}
	if a.Weekday() != time.Monday {
		t.Errorf("la semaine commence un %s", a.Weekday())
	}
}

// magasinDate pose un objet du magasin avec une date choisie.
func magasinDate(t *testing.T, s *Store, cle string, quand time.Time, n int) {
	t.Helper()
	meta, corps := s.paths(cle)
	if err := os.MkdirAll(filepath.Dir(corps), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(corps, make([]byte, n), 0o644); err != nil {
		t.Fatal(err)
	}
	// La taille est écrite dans le méta : le magasin refuse un corps dont
	// elle ne correspond plus, y voyant une écriture interrompue.
	if err := os.WriteFile(
		meta, []byte(fmt.Sprintf(`{"size":%d}`, n)), 0o644,
	); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(corps, quand, quand); err != nil {
		t.Fatal(err)
	}
}

func TestTranchesGroupentParAge(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	maintenant := time.Now()
	magasinDate(t, s, "aaaa1111", maintenant, 100)
	magasinDate(t, s, "bbbb2222", maintenant, 200)
	magasinDate(t, s, "cccc3333", maintenant.AddDate(0, 0, -40), 300)

	jours := s.Tranches(ParJour)
	if len(jours) != 2 {
		t.Fatalf("%d tranches par jour : %+v", len(jours), jours)
	}
	// Du plus récent au plus ancien : c'est l'ordre de lecture.
	if !jours[0].Debut.After(jours[1].Debut) {
		t.Error("les tranches ne descendent pas dans le temps")
	}
	if jours[0].Objets != 2 || jours[0].Octets != 300 {
		t.Errorf("tranche du jour : %+v", jours[0])
	}
	if n := len(s.Tranches(ParMois)); n != 2 {
		t.Errorf("%d tranches par mois, deux attendues", n)
	}
}

// Le méta part AVEC le corps : un méta orphelin ferait croire à une copie
// présente, et la lecture échouerait au moment de servir.
func TestPurgerEmporteLeMetaAvecLeCorps(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	vieux := time.Now().AddDate(0, 0, -40)
	magasinDate(t, s, "aaaa1111", vieux, 500)
	magasinDate(t, s, "bbbb2222", time.Now(), 700)

	n, octets, err := s.Purger(time.Now().AddDate(0, 0, -30))
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 || octets != 500 {
		t.Fatalf("purge : %d objets, %d octets", n, octets)
	}
	meta, corps := s.paths("aaaa1111")
	for _, f := range []string{meta, corps} {
		if _, err := os.Stat(f); !os.IsNotExist(err) {
			t.Errorf("%s subsiste", filepath.Base(f))
		}
	}
	// Et le récent est INTACT : une purge par âge ne touche pas au reste.
	if _, f, err := s.Get("bbbb2222"); err != nil {
		t.Errorf("l'objet récent a été emporté : %v", err)
	} else {
		f.Close()
	}
}

func TestPurgerToutNeLaisseRien(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	for i, cle := range []string{"aaaa1111", "bbbb2222", "cccc3333"} {
		magasinDate(t, s, cle, time.Now().AddDate(0, 0, -i), 100)
	}
	if n, _, err := s.Purger(time.Now().Add(time.Minute)); err != nil ||
		n != 3 {
		t.Fatalf("purge totale : %d objets, %v", n, err)
	}
	if st, err := s.Stat(); err != nil || st.Objects != 0 {
		t.Errorf("il reste %d objets", st.Objects)
	}
}

// L'âge d'un objet est celui de son dernier USAGE, pas de son entrée.
//
// Sans cela, « nettoyer ce qui ne sert plus » emporterait un paquet servi tous
// les jours depuis un an, et il faudrait le retélécharger le lendemain — le
// contraire de ce qu'un cache est là pour faire.
func TestServirRajeunitUnObjet(t *testing.T) {
	a := nouvelAmont(t, "charge utile")
	p := proxyDeTest(t)
	chemin := "/arch/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst"

	if w := demande(t, p, a.hote(), chemin); w.Code != 200 {
		t.Fatalf("premier appel : %d", w.Code)
	}
	// L'objet est vieilli à la main, comme s'il dormait depuis quarante jours.
	var corps string
	filepath.Walk(p.Store.Dir, func(q string, i os.FileInfo, e error) error {
		if e == nil && i != nil && filepath.Ext(q) == ".body" {
			corps = q
		}
		return nil
	})
	if corps == "" {
		t.Fatal("aucun objet gardé")
	}
	vieux := time.Now().AddDate(0, 0, -40)
	if err := os.Chtimes(corps, vieux, vieux); err != nil {
		t.Fatal(err)
	}

	if w := demande(t, p, a.hote(), chemin); w.Code != 200 {
		t.Fatalf("second appel : %d", w.Code)
	}
	info, err := os.Stat(corps)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(info.ModTime()) > time.Minute {
		t.Errorf("l'objet servi garde sa vieille date (%s) : un nettoyage"+
			" par âge l'emporterait alors qu'il sert", info.ModTime())
	}
}
