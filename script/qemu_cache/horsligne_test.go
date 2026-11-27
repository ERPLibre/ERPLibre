// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// remplir fait passer `chemins` par un cache EN LIGNE sur `dir`, comme
// l'installation de référence remplit le magasin d'un paquet hors ligne.
func remplir(t *testing.T, a *amont, dir string, chemins ...string) {
	t.Helper()
	alog, _ := OpenAccessLog("")
	p := NewProxy(&Store{Dir: dir}, alog)
	for _, c := range chemins {
		if w := demande(t, p, a.hote(), c); w.Code != 200 {
			t.Fatalf("remplissage de %s : code %d", c, w.Code)
		}
	}
}

func proxyHorsLigne(dir string) *Proxy {
	alog, _ := OpenAccessLog("")
	p := NewProxy(&Store{Dir: dir}, alog)
	p.HorsLigne = true
	return p
}

// listing rend les fichiers sous dir, triés : ce qu'un mode qui n'écrit rien
// doit laisser intact.
func listing(t *testing.T, dir string) []string {
	t.Helper()
	var out []string
	filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err == nil {
			out = append(out, p+" "+info.Mode().String())
		}
		return nil
	})
	sort.Strings(out)
	return out
}

// Le mode hors ligne sert ce que le magasin tient — paquet figé comme index
// volatil — sans qu'une seule requête parte vers l'amont, même joignable.
func TestHorsLigneServiSansJamaisJoindreLAmont(t *testing.T) {
	a := nouvelAmont(t, "contenu gardé")
	dir := t.TempDir()
	paquet := "/simple/paquet-1.0-py3-none-any.whl"
	index := "/simple/paquet/"
	remplir(t, a, dir, paquet, index)
	avant := a.appels()

	p := proxyHorsLigne(dir)
	for _, c := range []string{paquet, index} {
		w := demande(t, p, a.hote(), c)
		if w.Code != 200 || w.Body.String() != "contenu gardé" {
			t.Errorf("%s : code %d, corps %q", c, w.Code, w.Body.String())
		}
	}
	if n := a.appels(); n != avant {
		t.Errorf("l'amont a reçu %d requête(s) en mode hors ligne", n-avant)
	}
}

// Ce que le magasin ne tient pas rend un 504 qui nomme le paquet hors ligne,
// et l'amont n'est pas joint pour autant.
func TestHorsLigneAbsentNommeLePaquet(t *testing.T) {
	a := nouvelAmont(t, "jamais servi")
	p := proxyHorsLigne(t.TempDir())
	w := demande(t, p, a.hote(), "/jamais/vu.tar.gz")
	if w.Code != http.StatusGatewayTimeout {
		t.Fatalf("code %d, attendu 504", w.Code)
	}
	if !strings.Contains(w.Body.String(), "paquet hors ligne") {
		t.Errorf("le message ne nomme pas le paquet : %q", w.Body.String())
	}
	if a.appels() != 0 {
		t.Errorf("l'amont a été joint")
	}
}

// Un magasin en lecture seule sert, et rien n'y est créé ni changé de mode.
func TestHorsLigneNEcritRienDansLeMagasin(t *testing.T) {
	a := nouvelAmont(t, "figé")
	dir := t.TempDir()
	remplir(t, a, dir, "/f/paquet.tar.gz")
	filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err == nil && info.IsDir() {
			os.Chmod(p, 0o555)
		}
		return nil
	})
	t.Cleanup(func() {
		filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
			if err == nil && info.IsDir() {
				os.Chmod(p, 0o755)
			}
			return nil
		})
	})
	avant := listing(t, dir)

	p := proxyHorsLigne(dir)
	if w := demande(t, p, a.hote(), "/f/paquet.tar.gz"); w.Code != 200 {
		t.Fatalf("code %d sur un magasin en lecture seule", w.Code)
	}
	demande(t, p, a.hote(), "/f/absent.tar.gz")
	if apres := listing(t, dir); strings.Join(apres, "\n") != strings.Join(avant, "\n") {
		t.Errorf("le magasin a changé :\navant %v\naprès %v", avant, apres)
	}
}

func TestAdresseDEcoute(t *testing.T) {
	for _, c := range []struct {
		hote string
		port int
		veut string
	}{
		{"", 8898, ":8898"},
		{"127.0.0.1", 8899, "127.0.0.1:8899"},
		{"::1", 8898, "[::1]:8898"},
	} {
		if got := adresseDEcoute(c.hote, c.port); got != c.veut {
			t.Errorf("adresseDEcoute(%q, %d) = %q, attendu %q",
				c.hote, c.port, got, c.veut)
		}
	}
}

// Sans magasin ni autorité, le mode hors ligne refuse de démarrer plutôt que
// de fabriquer une autorité que personne n'approuve.
func TestVerifierHorsLigne(t *testing.T) {
	magasin, ca := t.TempDir(), t.TempDir()
	if err := verifierHorsLigne(filepath.Join(magasin, "absent"), ca); err == nil {
		t.Error("magasin absent accepté")
	}
	if err := verifierHorsLigne(magasin, ca); err == nil {
		t.Error("autorité absente acceptée")
	}
	if _, err := LoadOrCreateCA(ca); err != nil {
		t.Fatal(err)
	}
	if err := verifierHorsLigne(magasin, ca); err != nil {
		t.Errorf("refusé avec magasin et autorité : %v", err)
	}
}

// LoadCA ne crée jamais rien : le répertoire vide le reste.
func TestLoadCANeCreeRien(t *testing.T) {
	dir := t.TempDir()
	if _, err := LoadCA(dir); err == nil {
		t.Fatal("une autorité absente a été lue")
	}
	if entrees, _ := os.ReadDir(dir); len(entrees) != 0 {
		t.Errorf("LoadCA a écrit %d fichier(s)", len(entrees))
	}
	if _, err := LoadOrCreateCA(dir); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadCA(dir); err != nil {
		t.Errorf("autorité créée puis illisible : %v", err)
	}
}

// Le miroir hors ligne sert un dépôt présent sans le rafraîchir, et ne clone
// pas un dépôt absent, amont joignable ou non.
func TestMiroirHorsLigneNeJointPasLAmont(t *testing.T) {
	amont, appels, _ := amontGitCompte(t)
	g := &GitMirror{
		PlancherLibre: plancherDEssai, Dir: t.TempDir(), Delai: time.Minute}
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	avant := atomic.LoadInt64(appels)

	g.HorsLigne = true
	g.Frais = 0
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Error("le miroir présent ne sert pas en mode hors ligne")
	}
	if n := atomic.LoadInt64(appels); n != avant {
		t.Errorf("l'amont a reçu %d requête(s) en mode hors ligne", n-avant)
	}

	autre := &GitMirror{Dir: t.TempDir(), HorsLigne: true}
	if _, pret := autre.Assurer(context.Background(), amont); pret {
		t.Error("un dépôt absent se dit prêt en mode hors ligne")
	}
	if n := atomic.LoadInt64(appels); n != avant {
		t.Error("un dépôt absent a été cloné en mode hors ligne")
	}
	if entrees, _ := os.ReadDir(autre.Dir); len(entrees) != 0 {
		t.Errorf("le mode hors ligne a créé %d entrée(s)", len(entrees))
	}
}

// En mode hors ligne, git-http-backend reçoit l'exception safe.directory :
// les miroirs du paquet appartiennent au compte qui les a fabriqués. Le
// programme est remplacé par un script qui rend son environnement.
func TestServirHorsLigneAccepteUnDepotDAutrui(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "backend.sh")
	if err := os.WriteFile(script, []byte(
		"#!/bin/sh\nprintf 'Content-Type: text/plain\\r\\n\\r\\n'\nenv\n",
	), 0o755); err != nil {
		t.Fatal(err)
	}
	depot := filepath.Join(dir, "d.git")
	os.MkdirAll(depot, 0o755)
	for _, horsLigne := range []bool{false, true} {
		g := &GitMirror{Dir: dir, Backend: script, HorsLigne: horsLigne}
		r := httptest.NewRequest("GET", "/d.git/info/refs", nil)
		w := httptest.NewRecorder()
		g.Servir(w, r, depot, "/info/refs")
		vu := strings.Contains(w.Body.String(), "GIT_CONFIG_VALUE_0=*")
		if vu != horsLigne {
			t.Errorf("hors ligne %v : exception safe.directory présente %v",
				horsLigne, vu)
		}
	}
}

// Le front hors ligne ne tente aucun tunnel, même pour un hôte qui en
// relèverait : la connexion est déchiffrée et le magasin répond.
func TestFrontHorsLigneNeTunnellePas(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	p := proxyHorsLigne(t.TempDir())
	var origines int64
	front := &TLSFront{
		CA: ca, Proxy: p, Refusals: NewRefusals([]string{HOTE_AMONT}),
		HorsLigne: true,
		Origine: func(net.Conn) (string, error) {
			atomic.AddInt64(&origines, 1)
			return "127.0.0.1:1", nil
		},
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	go front.Serve(ln)

	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(ca.certPEM)
	client := &http.Client{Transport: &http.Transport{
		TLSClientConfig: &tls.Config{RootCAs: pool, ServerName: HOTE_AMONT},
		DialContext: func(ctx context.Context, reseau, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, reseau, ln.Addr().String())
		},
	}}
	resp, err := client.Get("https://" + HOTE_AMONT + "/absent.tar.gz")
	if err != nil {
		t.Fatalf("requête : %v", err)
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusGatewayTimeout {
		t.Errorf("code %d, attendu 504 du magasin hors ligne", resp.StatusCode)
	}
	if n := atomic.LoadInt64(&origines); n != 0 {
		t.Errorf("un tunnel a été tenté %d fois", n)
	}
}

// depotPacmanDEssai pose un dépôt « core » de deux fichiers, et un lien
// symbolique qui sort du dépôt.
func depotPacmanDEssai(t *testing.T) string {
	t.Helper()
	racine := t.TempDir()
	dir := filepath.Join(racine, "repo")
	dossier := filepath.Join(dir, "core", "os", "x86_64")
	if err := os.MkdirAll(dossier, 0o755); err != nil {
		t.Fatal(err)
	}
	ecrire := func(nom, contenu string) {
		if err := os.WriteFile(filepath.Join(dossier, nom), []byte(contenu), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	ecrire("core.db.tar.gz", "base inventée")
	ecrire("outil-1.0-1-x86_64.pkg.tar.zst", "paquet inventé")
	ecrire("epoque-2:1.0-1-x86_64.pkg.tar.zst", "paquet à époque inventé")
	os.Symlink("core.db.tar.gz", filepath.Join(dossier, "core.db"))
	secret := filepath.Join(racine, "dehors")
	os.WriteFile(secret, []byte("hors du dépôt"), 0o644)
	os.Symlink(secret, filepath.Join(dossier, "fuite.pkg.tar.zst"))
	return dir
}

func TestFichierPacman(t *testing.T) {
	d := &DepotPacman{Dir: depotPacmanDEssai(t)}
	for _, c := range []struct {
		chemin string
		releve bool
	}{
		{"/core/os/x86_64/core.db", true},
		{"/archlinux/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst", true},
		{"/pub/mirror/core/os/x86_64/absent.pkg.tar.zst", true},
		{"/core/os/x86_64/epoque-2:1.0-1-x86_64.pkg.tar.zst", true}, // époque
		{"/extra/os/x86_64/extra.db", false},                        // dépôt absent du paquet
		{"/core/os/aarch64/core.db", false},                         // architecture absente
		{"/core/x/x86_64/core.db", false},                           // pas un chemin de miroir
		{"/core/os/x86_64/.cache", false},                           // point en tête
		{"/core/os/x86_64/../../../etc", false},                     // remonte
		{"/os/x86_64/core.db", false},                               // trop court
		{"/core/os/x86_64/a b.pkg.tar.zst", false},                  // caractère refusé
	} {
		u := &url.URL{Scheme: "https", Host: "miroir.example", Path: c.chemin}
		if _, got := d.Fichier(u); got != c.releve {
			t.Errorf("%s : relève %v, attendu %v", c.chemin, got, c.releve)
		}
	}
	if _, ok := (&DepotPacman{}).Fichier(&url.URL{Path: "/core/os/x86_64/core.db"}); ok {
		t.Error("un dépôt non configuré relève une URL")
	}
}

// Tout miroir Arch, quel que soit son hôte et son préfixe, sort du dépôt
// local ; un fichier absent rend 404 et non 504, pour que pacman passe au
// miroir suivant ; un lien qui sort du dépôt n'est pas suivi.
func TestDepotPacmanServiPourToutMiroir(t *testing.T) {
	p := proxyHorsLigne(t.TempDir())
	p.Pacman = &DepotPacman{Dir: depotPacmanDEssai(t)}

	cas := []struct {
		hote, chemin string
		code         int
		corps        string
	}{
		{"geo.mirror.example", "/core/os/x86_64/core.db", 200, "base inventée"},
		{"autre.example", "/archlinux/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst",
			200, "paquet inventé"},
		{"geo.mirror.example", "/core/os/x86_64/epoque-2:1.0-1-x86_64.pkg.tar.zst",
			200, "paquet à époque inventé"},
		{"geo.mirror.example", "/core/os/x86_64/core.db.sig", 404, ""},
		{"geo.mirror.example", "/core/os/x86_64/fuite.pkg.tar.zst", 404, ""},
		{"geo.mirror.example", "/extra/os/x86_64/extra.db", 504, ""},
	}
	for _, c := range cas {
		w := demande(t, p, c.hote, c.chemin)
		if w.Code != c.code {
			t.Errorf("%s%s : code %d, attendu %d", c.hote, c.chemin, w.Code, c.code)
		}
		if c.corps != "" && w.Body.String() != c.corps {
			t.Errorf("%s : corps %q", c.chemin, w.Body.String())
		}
		if strings.Contains(w.Body.String(), "hors du dépôt") {
			t.Errorf("%s : le lien sortant a été suivi", c.chemin)
		}
	}

	// Une plage : pacman reprend ainsi un téléchargement interrompu.
	r := httptest.NewRequest("GET", "/core/os/x86_64/outil-1.0-1-x86_64.pkg.tar.zst", nil)
	r.Host = "geo.mirror.example"
	r.Header.Set("Range", "bytes=0-5")
	w := httptest.NewRecorder()
	p.serve(w, r, "https")
	if w.Code != http.StatusPartialContent || w.Body.String() != "paquet" {
		t.Errorf("plage : code %d, corps %q", w.Code, w.Body.String())
	}

	r = httptest.NewRequest("POST", "/core/os/x86_64/core.db", nil)
	r.Host = "geo.mirror.example"
	w = httptest.NewRecorder()
	p.serve(w, r, "https")
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("POST : code %d, attendu 405", w.Code)
	}
}
