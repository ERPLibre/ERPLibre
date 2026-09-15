// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

// « --detient » dit ce que le magasin tient, une ligne par question, avec la
// clé que le service calcule. Le magasin est rempli ici PAR le service, pour
// que toute divergence entre les deux calculs de clé se voie.
func TestDetientDitCeQueLeMagasinTient(t *testing.T) {
	paquet := "/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst"
	a := nouvelAmontScripte(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/installer.sh":
			rediriger(http.StatusFound, "https://ailleurs.example/bootstrap.sh")(w, r)
		case "/depot/etat":
			servir("état courant")(w, r)
		default:
			servir("contenu du paquet")(w, r)
		}
	})
	p := proxyDeTest(t)
	for _, c := range []string{"/installer.sh", "/depot/etat", paquet} {
		joue(t, p, "GET", a.hote(), c)
	}
	joue(t, p, "HEAD", a.hote(), "/installer.sh")

	base := "http://" + a.hote()
	questions := []string{
		"GET " + base + "/depot/etat",
		"GET " + base + "/installer.sh",
		"HEAD " + base + "/installer.sh",
		"get " + base + "/jamais-vu.sh",
		"POST " + base + "/depot/etat",
		"GET " + base + "/o/d.git/info/refs?service=git-upload-pack",
		// Un paquet est portable : le même chemin sur un autre miroir est
		// le même fichier.
		"GET http://autre-miroir.example.invalid" + paquet,
		"",
		"# une ligne de commentaire",
		base + "/depot/etat",
		"GET pas-une-url",
	}
	var sortie bytes.Buffer
	if err := EcrireDetentions(
		p.Store, strings.NewReader(strings.Join(questions, "\n")), &sortie,
	); err != nil {
		t.Fatal(err)
	}

	attendus := []struct {
		verdict, statut, classe, methode, url string
		date                                  bool
	}{
		{"garde", "200", "volatile", "GET", base + "/depot/etat", true},
		{"statut", "302", "volatile", "GET", base + "/installer.sh", true},
		{"statut", "302", "volatile", "HEAD", base + "/installer.sh", true},
		{"absent", "-", "volatile", "GET", base + "/jamais-vu.sh", false},
		{"non-cachable", "-", "volatile", "POST", base + "/depot/etat", false},
		{"non-cachable", "-", "no-store", "GET",
			base + "/o/d.git/info/refs?service=git-upload-pack", false},
		{"garde", "200", "immutable", "GET",
			"http://autre-miroir.example.invalid" + paquet, true},
		{"garde", "200", "volatile", "GET", base + "/depot/etat", true},
		{"non-cachable", "-", "-", "GET", "pas-une-url", false},
	}
	lignes := strings.Split(strings.TrimRight(sortie.String(), "\n"), "\n")
	if len(lignes) != len(attendus) {
		t.Fatalf("%d lignes, attendu %d :\n%s", len(lignes), len(attendus), sortie.String())
	}
	for i, a := range attendus {
		champs := strings.Split(lignes[i], "\t")
		if len(champs) != 6 {
			t.Errorf("ligne %d : %d champs, attendu 6 : %q", i+1, len(champs), lignes[i])
			continue
		}
		if champs[0] != a.verdict || champs[1] != a.statut ||
			champs[3] != a.classe || champs[4] != a.methode || champs[5] != a.url {
			t.Errorf("ligne %d : %q, attendu %s %s … %s %s %s",
				i+1, lignes[i], a.verdict, a.statut, a.classe, a.methode, a.url)
		}
		if a.date {
			if _, err := time.Parse(time.RFC3339, champs[2]); err != nil {
				t.Errorf("ligne %d : date %q illisible", i+1, champs[2])
			}
		} else if champs[2] != "-" {
			t.Errorf("ligne %d : date %q pour un objet absent", i+1, champs[2])
		}
	}
}

// Le relevé ne rajeunit rien : l'âge d'un objet est celui de son dernier
// SERVICE, et une question posée au magasin n'en est pas un.
func TestDetientNeRajeunitPas(t *testing.T) {
	a := nouvelAmontScripte(t, servir("état courant"))
	p, _ := proxyEtCasier(t)
	joue(t, p, "GET", a.hote(), "/depot/etat")

	u, _ := url.Parse("http://" + a.hote() + "/depot/etat")
	_, corps := p.Store.paths(CleDe("GET", u))
	ancien := time.Date(2020, 1, 2, 3, 4, 5, 0, time.UTC)
	if err := os.Chtimes(corps, ancien, ancien); err != nil {
		t.Fatal(err)
	}
	var sortie bytes.Buffer
	EcrireDetentions(p.Store, strings.NewReader("GET "+u.String()+"\n"), &sortie)
	if !strings.HasPrefix(sortie.String(), VerdictGarde+"\t") {
		t.Fatalf("l'objet n'a pas été vu : %q", sortie.String())
	}
	fi, err := os.Stat(corps)
	if err != nil {
		t.Fatal(err)
	}
	if !fi.ModTime().Equal(ancien) {
		t.Errorf("le relevé a rajeuni l'objet : %v au lieu de %v", fi.ModTime(), ancien)
	}
}

// Un HEAD que le service ne gardera jamais est non-cachable, pas absent :
// l'appelant le croirait sinon à remplir, et le rejouerait pour rien. Le
// magasin est rempli ici PAR le service, l'amont répondant 200 à chaque
// HEAD : seul celui dont la classe garde un statut seul doit y entrer, et
// c'est le seul que « --detient » ne dit pas non-cachable.
func TestDetientUnHeadQueLeMagasinNeGardeJamais(t *testing.T) {
	a := nouvelAmontScripte(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "1234")
		w.WriteHeader(http.StatusOK)
	})
	p, dir := proxyEtCasier(t)
	base := "http://" + a.hote()
	attendus := map[string]string{
		// Immuable et portable : un paquet.
		"/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst": VerdictNonCachable,
		// Immuable attaché à son hôte : un index par empreinte.
		"/debian/dists/trixie/by-hash/SHA256/" + strings.Repeat("ab", 32): VerdictNonCachable,
		// Volatile mais portable : un index de dépôt.
		"/arch/core/os/x86_64/core.db": VerdictNonCachable,
		// Volatile attaché à son hôte : le seul qui se garde.
		"/api/bonjour": VerdictStatut,
	}
	for chemin, attendu := range attendus {
		if got := p.Store.Detenir("HEAD", base+chemin).Verdict; got != VerdictNonCachable &&
			got != VerdictAbsent {
			t.Errorf("%s avant remplissage : %q", chemin, got)
		}
		joue(t, p, "HEAD", a.hote(), chemin)
		if got := p.Store.Detenir("HEAD", base+chemin).Verdict; got != attendu {
			t.Errorf("HEAD %s : %q, attendu %q", chemin, got, attendu)
		}
		// Le GET de la même URL reste à remplir : un corps s'y garde.
		if got := p.Store.Detenir("GET", base+chemin).Verdict; got != VerdictAbsent {
			t.Errorf("GET %s : %q, attendu %q", chemin, got, VerdictAbsent)
		}
	}
	if n := corpsGardes(t, dir); n != 1 {
		t.Errorf("%d objet(s) gardé(s), attendu 1 : le service et --detient"+
			" divergent sur ce qu'un HEAD laisse au magasin", n)
	}
	if got := p.Store.Detenir("HEAD", base+"/api/jamais-vu").Verdict; got != VerdictAbsent {
		t.Errorf("HEAD volatile jamais vu : %q, attendu %q", got, VerdictAbsent)
	}
}

// Un corps dont la taille ne correspond plus à son méta n'est pas en
// réserve : le service refuserait de le servir.
func TestDetientRefuseUnCorpsAltere(t *testing.T) {
	a := nouvelAmontScripte(t, servir("état courant"))
	p, _ := proxyEtCasier(t)
	joue(t, p, "GET", a.hote(), "/depot/etat")
	u, _ := url.Parse("http://" + a.hote() + "/depot/etat")
	_, corps := p.Store.paths(CleDe("GET", u))
	if err := os.WriteFile(corps, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if d := p.Store.Detenir("GET", u.String()); d.Verdict != VerdictAbsent {
		t.Errorf("verdict %q pour un corps altéré", d.Verdict)
	}
	EcrireDetentions(p.Store, strings.NewReader(""), io.Discard)
}
