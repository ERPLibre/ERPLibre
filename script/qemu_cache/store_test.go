// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func ecrire(t *testing.T, s *Store, key, corps string, taille int64) error {
	t.Helper()
	w, err := s.NewWriter(key, Meta{
		URL: "https://exemple.example/x", Method: "GET", Status: 200,
		Header: http.Header{"Content-Type": []string{"application/octet-stream"}},
		Class:  ClassImmutable.String(),
	})
	if err != nil {
		t.Fatalf("ouverture : %v", err)
	}
	io.WriteString(w, corps)
	return w.Commit(taille)
}

func TestStorePuisGet(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	key := Key("GET", "https://exemple.example/x")
	if err := ecrire(t, s, key, "bonjour", 7); err != nil {
		t.Fatalf("commit : %v", err)
	}
	m, f, err := s.Get(key)
	if err != nil {
		t.Fatalf("get : %v", err)
	}
	defer f.Close()
	if m.Size != 7 {
		t.Errorf("taille %d, attendu 7", m.Size)
	}
	raw, _ := io.ReadAll(f)
	if string(raw) != "bonjour" {
		t.Errorf("corps %q, attendu %q", raw, "bonjour")
	}
	if m.StoredAt.IsZero() {
		t.Error("la date de stockage manque")
	}
}

// Une réponse tronquée par une coupure réseau ressemble à une réponse
// complète pour tout le reste du code : la taille annoncée est donc vérifiée.
func TestCorpsTronqueRefuse(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	key := Key("GET", "https://exemple.example/tronque")
	err := ecrire(t, s, key, "court", 4096)
	if err == nil {
		t.Fatal("un corps tronqué a été accepté")
	}
	if !strings.Contains(err.Error(), "tronqué") {
		t.Errorf("erreur %q, attendu qu'elle dise « tronqué »", err)
	}
	if _, _, err := s.Get(key); err == nil {
		t.Error("l'objet refusé est pourtant lisible")
	}
}

// Une taille inconnue à l'amont — pas de Content-Length — vaut -1 et ne
// déclenche aucune vérification.
func TestTailleInconnueAcceptee(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	key := Key("GET", "https://exemple.example/inconnue")
	if err := ecrire(t, s, key, "quoi que ce soit", -1); err != nil {
		t.Fatalf("commit : %v", err)
	}
	if _, f, err := s.Get(key); err != nil {
		t.Errorf("get : %v", err)
	} else {
		f.Close()
	}
}

// Un objet dont le corps ne correspond plus aux métadonnées vaut absent
// plutôt que faux.
func TestCorpsAlteréVautAbsent(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	key := Key("GET", "https://exemple.example/altere")
	if err := ecrire(t, s, key, "bonjour", 7); err != nil {
		t.Fatalf("commit : %v", err)
	}
	_, body := s.paths(key)
	if err := os.WriteFile(body, []byte("plus court"), 0o644); err != nil {
		t.Fatalf("altération : %v", err)
	}
	if _, _, err := s.Get(key); err == nil {
		t.Error("un corps de taille inattendue a été servi")
	}
}

func TestAbortNeLaisseRien(t *testing.T) {
	dir := t.TempDir()
	s := &Store{Dir: dir}
	key := Key("GET", "https://exemple.example/abandon")
	w, err := s.NewWriter(key, Meta{URL: "x", Method: "GET", Status: 200})
	if err != nil {
		t.Fatalf("ouverture : %v", err)
	}
	io.WriteString(w, "à moitié")
	w.Abort()

	if _, _, err := s.Get(key); err == nil {
		t.Error("un objet abandonné est lisible")
	}
	var restes []string
	filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err == nil && !info.IsDir() {
			restes = append(restes, p)
		}
		return nil
	})
	if len(restes) != 0 {
		t.Errorf("l'abandon laisse %v", restes)
	}
}

func TestSweepPartials(t *testing.T) {
	dir := t.TempDir()
	s := &Store{Dir: dir}
	sub := filepath.Join(dir, "ab", "cd")
	os.MkdirAll(sub, 0o755)
	os.WriteFile(filepath.Join(sub, "clef.part-123"), []byte("x"), 0o644)
	os.WriteFile(filepath.Join(sub, "clef.body"), []byte("x"), 0o644)

	if n := s.SweepPartials(); n != 1 {
		t.Errorf("%d fichier(s) balayé(s), attendu 1", n)
	}
	if _, err := os.Stat(filepath.Join(sub, "clef.body")); err != nil {
		t.Error("le balayage a emporté un corps complet")
	}
}

func TestStat(t *testing.T) {
	s := &Store{Dir: t.TempDir()}
	for _, u := range []string{"a", "b", "c"} {
		if err := ecrire(t, s, Key("GET", u), "12345", 5); err != nil {
			t.Fatalf("commit %s : %v", u, err)
		}
	}
	st, err := s.Stat()
	if err != nil {
		t.Fatalf("stat : %v", err)
	}
	if st.Objects != 3 {
		t.Errorf("%d objets, attendu 3", st.Objects)
	}
	if st.Bytes != 15 {
		t.Errorf("%d octets, attendu 15", st.Bytes)
	}
	if st.Oldest.IsZero() {
		t.Error("aucune date pour le plus ancien objet")
	}
}

// Un répertoire de cache qui n'existe pas encore rend un état vide et non une
// erreur : « --status » doit répondre avant le premier démarrage.
func TestStatSansRepertoire(t *testing.T) {
	s := &Store{Dir: filepath.Join(t.TempDir(), "jamais-cree")}
	st, err := s.Stat()
	if err != nil {
		t.Fatalf("stat : %v", err)
	}
	if st.Objects != 0 || st.Bytes != 0 {
		t.Errorf("état %+v, attendu vide", st)
	}
}

func TestKeyDistingueMethode(t *testing.T) {
	if Key("GET", "https://x/y") == Key("HEAD", "https://x/y") {
		t.Error("GET et HEAD partagent une clé : un HEAD servirait un corps")
	}
}

func TestHumanBytes(t *testing.T) {
	cas := map[int64]string{
		512:                    "512 o",
		2048:                   "2.0 Kio",
		5 * 1024 * 1024:        "5.0 Mio",
		3 * 1024 * 1024 * 1024: "3.0 Gio",
	}
	for n, attendu := range cas {
		if got := HumanBytes(n); got != attendu {
			t.Errorf("%d octets rendus %q, attendu %q", n, got, attendu)
		}
	}
}
