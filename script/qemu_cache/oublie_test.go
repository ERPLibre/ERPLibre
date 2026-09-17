// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Le magasin est rempli PAR le service, comme pour « --detient » : c'est la
// seule façon de voir une divergence entre le calcul de clé du service et
// celui de la commande. Effacer sous une clé que le service n'écrit pas
// laisserait l'objet empoisonné en place tout en disant l'avoir retiré.
func TestOublieRetireCeQueLeMagasinSert(t *testing.T) {
	paquet := "/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst"
	a := nouvelAmontScripte(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/installer.sh":
			rediriger(http.StatusFound,
				"https://ailleurs.example/bootstrap.sh")(w, r)
		default:
			servir("contenu du paquet")(w, r)
		}
	})
	p := proxyDeTest(t)
	for _, c := range []string{"/installer.sh", "/depot/etat", paquet} {
		joue(t, p, "GET", a.hote(), c)
	}

	base := "http://" + a.hote()
	questions := []string{
		"GET " + base + paquet,
		"GET " + base + "/installer.sh",
		"GET " + base + "/jamais-vu.sh",
		"POST " + base + "/depot/etat",
		"",
		"# un commentaire",
		"GET pas-une-url",
	}
	var sortie bytes.Buffer
	if err := EcrireOublis(
		p.Store, strings.NewReader(strings.Join(questions, "\n")), &sortie,
	); err != nil {
		t.Fatal(err)
	}
	attendus := []struct{ verdict, classe, methode, url string }{
		{"oublié", "immutable", "GET", base + paquet},
		// Une redirection est un STATUT SEUL : sans la seconde clé, le rejeu
		// la resservirait vers l'octet qu'on vient de retirer.
		{"oublié", "volatile", "GET", base + "/installer.sh"},
		{"absent", "volatile", "GET", base + "/jamais-vu.sh"},
		{"non-cachable", "volatile", "POST", base + "/depot/etat"},
		{"non-cachable", "-", "GET", "pas-une-url"},
	}
	lignes := strings.Split(strings.TrimRight(sortie.String(), "\n"), "\n")
	if len(lignes) != len(attendus) {
		t.Fatalf("%d lignes, attendu %d :\n%s",
			len(lignes), len(attendus), sortie.String())
	}
	for i, at := range attendus {
		champs := strings.Split(lignes[i], "\t")
		if len(champs) != 5 {
			t.Errorf("ligne %d : %d champs, attendu 5 : %q",
				i+1, len(champs), lignes[i])
			continue
		}
		if champs[0] != at.verdict || champs[2] != at.classe ||
			champs[3] != at.methode || champs[4] != at.url {
			t.Errorf("ligne %d : %q, attendu %s … %s %s %s",
				i+1, lignes[i], at.verdict, at.classe, at.methode, at.url)
		}
	}
	// Les octets ne sont comptés que pour ce qui est parti.
	if champs := strings.Split(lignes[0], "\t"); champs[1] == "-" {
		t.Error("un objet effacé doit dire les octets rendus")
	}
	if champs := strings.Split(lignes[2], "\t"); champs[1] != "-" {
		t.Errorf("rien d'effacé, octets %q", champs[1])
	}
}

// L'INVARIANT qui rend la commande sûre : ce que « --detient » dit tenir,
// « --oublie » l'efface, et « --detient » ne le tient plus. Deux calculs de
// clé qui divergeraient se verraient ici, et nulle part ailleurs.
func TestCeQueDetientVoitOublieLeRetire(t *testing.T) {
	paquet := "/core/os/x86_64/outil-2.0-1-x86_64.pkg.tar.zst"
	a := nouvelAmontScripte(t, servir("contenu du paquet"))
	p := proxyDeTest(t)
	joue(t, p, "GET", a.hote(), paquet)

	question := "GET http://" + a.hote() + paquet
	avant := ligneUnique(t, p, question, EcrireDetentions)
	if verdict := strings.Split(avant, "\t")[0]; verdict != "garde" {
		t.Fatalf("le magasin devrait garder : %q", avant)
	}
	efface := ligneUnique(t, p, question, EcrireOublis)
	if verdict := strings.Split(efface, "\t")[0]; verdict != "oublié" {
		t.Fatalf("l'oubli devrait effacer : %q", efface)
	}
	apres := ligneUnique(t, p, question, EcrireDetentions)
	if verdict := strings.Split(apres, "\t")[0]; verdict != "absent" {
		t.Fatalf("le magasin tient encore : %q", apres)
	}
}

// Ce que ni « --purge » ni « --purge-older-than » ne savent faire : retirer
// UNE entrée. La voisine reste, et c'est tout l'intérêt — un objet empoisonné
// ne doit pas coûter le cache entier.
func TestOublieNeTouchePasLaVoisine(t *testing.T) {
	a := nouvelAmontScripte(t, servir("contenu du paquet"))
	p := proxyDeTest(t)
	garde := "/core/os/x86_64/garde-1.0-1-x86_64.pkg.tar.zst"
	part := "/core/os/x86_64/part-1.0-1-x86_64.pkg.tar.zst"
	joue(t, p, "GET", a.hote(), garde)
	joue(t, p, "GET", a.hote(), part)

	ligneUnique(t, p, "GET http://"+a.hote()+part, EcrireOublis)
	reste := ligneUnique(t, p, "GET http://"+a.hote()+garde, EcrireDetentions)
	if verdict := strings.Split(reste, "\t")[0]; verdict != "garde" {
		t.Fatalf("la voisine a disparu : %q", reste)
	}
}

// Un objet présent qui résiste est un REFUS, jamais un oubli : croire un
// magasin nettoyé qui ne l'est pas est la seule issue vraiment mauvaise.
func TestUnObjetQuiResisteEstUnRefus(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root efface dans un répertoire en lecture seule")
	}
	a := nouvelAmontScripte(t, servir("contenu du paquet"))
	p := proxyDeTest(t)
	paquet := "/core/os/x86_64/dur-1.0-1-x86_64.pkg.tar.zst"
	joue(t, p, "GET", a.hote(), paquet)

	u := "http://" + a.hote() + paquet
	casier := casierDe(t, p, u)
	fige(t, casier, 0o500)

	ligne := ligneUnique(t, p, "GET "+u, EcrireOublis)
	if verdict := strings.Split(ligne, "\t")[0]; verdict != "refus" {
		t.Fatalf("un effacement impossible doit se dire : %q", ligne)
	}
}

// ligneUnique pose UNE question et rend la ligne rendue, sans son saut.
func ligneUnique(
	t *testing.T, p *Proxy, question string,
	ecrire func(*Store, io.Reader, io.Writer) error,
) string {
	t.Helper()
	var sortie bytes.Buffer
	if err := ecrire(p.Store, strings.NewReader(question), &sortie); err != nil {
		t.Fatal(err)
	}
	return strings.TrimRight(sortie.String(), "\n")
}

// casierDe rend le répertoire où le magasin range le corps d'une URL.
func casierDe(t *testing.T, p *Proxy, brut string) string {
	t.Helper()
	u, err := url.Parse(brut)
	if err != nil {
		t.Fatal(err)
	}
	_, corps := p.Store.paths(CleDe("GET", u))
	return filepath.Dir(corps)
}

// fige retire le droit d'écrire dans un répertoire, et le rend au nettoyage :
// sans cela le répertoire temporaire du test ne pourrait plus être effacé.
func fige(t *testing.T, dir string, mode os.FileMode) {
	t.Helper()
	avant, err := os.Stat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, mode); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chmod(dir, avant.Mode()) })
}
