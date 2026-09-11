// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// amontScripte monte un amont dont la réponse est dictée par le test, et qui
// compte ce qu'on lui demande. La réponse peut changer en cours de test :
// c'est ce qui fait rendre un 200 puis un 404 à la même URL.
type amontScripte struct {
	srv   *httptest.Server
	appel int64
	mu    sync.Mutex
	h     http.HandlerFunc
}

func nouvelAmontScripte(t *testing.T, h http.HandlerFunc) *amontScripte {
	t.Helper()
	a := &amontScripte{h: h}
	a.srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&a.appel, 1)
			a.mu.Lock()
			h := a.h
			a.mu.Unlock()
			h(w, r)
		}))
	t.Cleanup(a.srv.Close)
	return a
}

func (a *amontScripte) repondre(h http.HandlerFunc) {
	a.mu.Lock()
	a.h = h
	a.mu.Unlock()
}

func (a *amontScripte) appels() int64 { return atomic.LoadInt64(&a.appel) }

func (a *amontScripte) hote() string {
	u, _ := url.Parse(a.srv.URL)
	return u.Host
}

// couper rend l'amont injoignable et rend son adresse, qui refuse désormais
// toute connexion.
func (a *amontScripte) couper() string {
	h := a.hote()
	a.srv.Close()
	return h
}

func rediriger(code int, cible string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Location", cible)
		w.Header().Set("Set-Cookie", "session=temoin")
		w.WriteHeader(code)
		io.WriteString(w, "déplacé")
	}
}

func refuser(code int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		w.WriteHeader(code)
		io.WriteString(w, "introuvable")
	}
}

func servir(corps string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/octet-stream")
		io.WriteString(w, corps)
	}
}

// joue fait une requête de méthode et d'en-têtes choisis, telle que
// l'interception transparente la présente. Les en-têtes vont par paires :
// nom, valeur.
func joue(
	t *testing.T, p *Proxy, methode, hote, chemin string, entetes ...string,
) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(methode, chemin, nil)
	r.Host = hote
	for i := 0; i+1 < len(entetes); i += 2 {
		r.Header.Set(entetes[i], entetes[i+1])
	}
	w := httptest.NewRecorder()
	p.serve(w, r, "http")
	return w
}

// journalDeTest branche un journal d'accès sur fichier et rend son chemin.
func journalDeTest(t *testing.T, p *Proxy) string {
	t.Helper()
	chemin := filepath.Join(t.TempDir(), "acces.jsonl")
	alog, err := OpenAccessLog(chemin)
	if err != nil {
		t.Fatalf("journal : %v", err)
	}
	t.Cleanup(alog.Close)
	p.Log = alog
	return chemin
}

func lignesDuJournal(t *testing.T, chemin string) []accessLine {
	t.Helper()
	raw, err := os.ReadFile(chemin)
	if err != nil {
		t.Fatalf("journal illisible : %v", err)
	}
	var out []accessLine
	for _, l := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
		if l == "" {
			continue
		}
		var a accessLine
		if err := json.Unmarshal([]byte(l), &a); err != nil {
			t.Fatalf("ligne illisible %q : %v", l, err)
		}
		out = append(out, a)
	}
	return out
}

// Une redirection volatile est gardée, mais ne sort QUE l'amont muet : tant
// qu'il répond, chaque requête lui revient, et le client reçoit ce que
// l'amont dit aujourd'hui.
func TestUneRedirectionVolatileNeSortQueHorsLigne(t *testing.T) {
	const cible = "https://ailleurs.example/bootstrap.sh"
	a := nouvelAmontScripte(t, rediriger(http.StatusFound, cible))
	p := proxyDeTest(t)
	journal := journalDeTest(t, p)

	for i := 1; i <= 2; i++ {
		w := joue(t, p, "GET", a.hote(), "/installer.sh")
		if w.Code != http.StatusFound {
			t.Fatalf("en ligne %d : code %d, attendu 302", i, w.Code)
		}
		if got := w.Header().Get("X-ERPLibre-Cache"); got != "miss" {
			t.Errorf("en ligne %d : servi « %s », attendu « miss »", i, got)
		}
	}
	if n := a.appels(); n != 2 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 2 : un statut gardé"+
			" est sorti alors qu'il répondait", n)
	}

	hote := a.couper()
	w := joue(t, p, "GET", hote, "/installer.sh")
	if w.Code != http.StatusFound {
		t.Fatalf("hors ligne : code %d, attendu 302", w.Code)
	}
	if got := w.Header().Get("Location"); got != cible {
		t.Errorf("Location %q, attendu %q", got, cible)
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeStaleStatus {
		t.Errorf("servi « %s », attendu « %s »", got, OutcomeStaleStatus)
	}
	if w.Header().Get("X-ERPLibre-Cache-Date") == "" {
		t.Error("la date du statut rejoué manque")
	}
	if w.Body.Len() != 0 {
		t.Errorf("un statut rejoué porte un corps de %d octets", w.Body.Len())
	}
	if got := w.Header().Get("Set-Cookie"); got != "" {
		t.Errorf("le témoin d'une autre machine est rejoué : %q", got)
	}
	if got := w.Header().Get("Content-Length"); got != "" {
		t.Errorf("une longueur %q est annoncée sans corps", got)
	}

	// Le journal dit le VRAI statut, et sous des noms qui ne se confondent
	// pas avec ceux d'un corps.
	var garde, rejoue bool
	for _, l := range lignesDuJournal(t, journal) {
		switch l.Outcome {
		case OutcomeStoredStatus:
			garde = l.Status == http.StatusFound && l.Upstream
		case OutcomeStaleStatus:
			rejoue = l.Status == http.StatusFound && !l.Upstream
		case OutcomeStored, OutcomeStale:
			t.Errorf("un statut seul est journalisé « %s »", l.Outcome)
		}
	}
	if !garde || !rejoue {
		t.Errorf("journal : gardé=%v rejoué=%v, attendu les deux avec 302",
			garde, rejoue)
	}
}

// Un refus définitif ressort tel quel : un client qui sonde un fichier
// optionnel s'arrête sur le 404 et poursuit, là où un 504 l'arrête net.
func TestUnRefusDefinitifSeRejoueHorsLigne(t *testing.T) {
	for _, code := range []int{http.StatusNotFound, http.StatusGone} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			a := nouvelAmontScripte(t, refuser(code))
			p := proxyDeTest(t)
			if w := joue(t, p, "GET", a.hote(), "/sonde/2.root.json"); w.Code != code {
				t.Fatalf("en ligne : code %d, attendu %d", w.Code, code)
			}
			hote := a.couper()
			w := joue(t, p, "GET", hote, "/sonde/2.root.json")
			if w.Code != code {
				t.Fatalf("hors ligne : code %d, attendu %d", w.Code, code)
			}
			if w.Body.Len() != 0 {
				t.Errorf("corps de %d octets rejoué", w.Body.Len())
			}
		})
	}
}

// Un refus n'écrase jamais un corps : un amont qui perd un fichier un jour
// ne doit pas priver le hors-ligne de la copie qu'il avait rendue.
func TestUnRefusNeRemplacePasUnCorps(t *testing.T) {
	a := nouvelAmontScripte(t, servir("corps publié"))
	p := proxyDeTest(t)
	chemin := "/metadonnees/etat.json"

	joue(t, p, "GET", a.hote(), chemin)
	a.repondre(refuser(http.StatusNotFound))
	if w := joue(t, p, "GET", a.hote(), chemin); w.Code != http.StatusNotFound {
		t.Fatalf("en ligne, le refus de l'amont n'est pas relayé : %d", w.Code)
	}

	hote := a.couper()
	w := joue(t, p, "GET", hote, chemin)
	if w.Code != http.StatusOK || w.Body.String() != "corps publié" {
		t.Fatalf("hors ligne : %d %q, attendu le corps gardé", w.Code, w.Body.String())
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeStale {
		t.Errorf("servi « %s », attendu « %s »", got, OutcomeStale)
	}
}

// Un corps, lui, l'emporte sur un statut seul — y compris quand le client
// pose une condition : le statut ne vaut pas détention, la condition est donc
// retirée, et l'amont rend le corps entier au lieu d'un 304.
func TestUnCorpsRemplaceUnStatutSeul(t *testing.T) {
	a := nouvelAmontScripte(t, refuser(http.StatusNotFound))
	p := proxyDeTest(t)
	chemin := "/metadonnees/etat.json"
	joue(t, p, "GET", a.hote(), chemin)

	a.repondre(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("If-None-Match") != "" {
			w.WriteHeader(http.StatusNotModified)
			return
		}
		io.WriteString(w, "corps publié")
	})
	w := joue(t, p, "GET", a.hote(), chemin, "If-None-Match", `"v1"`)
	if w.Code != http.StatusOK {
		t.Fatalf("code %d, attendu 200 : la condition est partie à l'amont"+
			" alors que le cache n'a qu'un statut", w.Code)
	}

	hote := a.couper()
	w = joue(t, p, "GET", hote, chemin)
	if w.Code != http.StatusOK || w.Body.String() != "corps publié" {
		t.Fatalf("hors ligne : %d %q, attendu le corps", w.Code, w.Body.String())
	}
}

// Un statut seul vit sous sa propre clé. Un lecteur qui ne connaît que les
// corps — qui ne calcule que Key — n'y trouve rien, et ne peut donc pas le
// servir en « 200 » vide. Le rejeu, lui, le trouve ; et un corps gardé plus
// tard sous la clé du corps coexiste avec lui et sort en premier.
func TestUnStatutSeulResteHorsDesClesDeCorps(t *testing.T) {
	a := nouvelAmontScripte(t, rediriger(http.StatusFound,
		"https://ailleurs.example/bootstrap.sh"))
	p := proxyDeTest(t)
	p.Muets = NouvelleJoignabilite()
	chemin := "/installer.sh"
	u, _ := url.Parse("http://" + a.hote() + chemin)
	joue(t, p, "GET", a.hote(), chemin)

	if _, err := p.Store.LireMeta(Key("GET", u.String())); err == nil {
		t.Error("un statut seul est lisible sous la clé d'un corps")
	}
	if !p.Store.TientStatut(CleStatut("GET", u)) {
		t.Fatal("le statut seul n'est pas sous sa propre clé")
	}

	// L'hôte retenu muet : le repli sort sans composer, et c'est le rejeu.
	p.Muets.Echec(a.hote(), refusEtablissement())
	w := joue(t, p, "GET", a.hote(), chemin)
	if w.Code != http.StatusFound ||
		w.Header().Get("X-ERPLibre-Cache") != OutcomeStaleStatus {
		t.Fatalf("rejeu : %d « %s », attendu 302 « %s »", w.Code,
			w.Header().Get("X-ERPLibre-Cache"), OutcomeStaleStatus)
	}
	p.Muets.Reussite(a.hote())

	a.repondre(servir("echo bonjour"))
	if w := joue(t, p, "GET", a.hote(), chemin); w.Code != http.StatusOK {
		t.Fatalf("en ligne : code %d, attendu 200", w.Code)
	}
	if !p.Store.Detient(Key("GET", u.String())) {
		t.Fatal("le corps n'est pas gardé sous la clé du corps")
	}
	if !p.Store.TientStatut(CleStatut("GET", u)) {
		t.Error("le statut seul a disparu : il devait coexister avec le corps")
	}

	hote := a.couper()
	w = joue(t, p, "GET", hote, chemin)
	if w.Code != http.StatusOK || w.Body.String() != "echo bonjour" {
		t.Fatalf("hors ligne : %d %q, attendu le corps", w.Code, w.Body.String())
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeStale {
		t.Errorf("servi « %s », attendu « %s »", got, OutcomeStale)
	}
}

// Un statut passager ne se garde pas : le rejouer figerait une panne d'un
// moment, et le hors-ligne dirait 403 ou 503 pour toujours.
func TestUnStatutPassagerNestPasGarde(t *testing.T) {
	for _, code := range []int{403, 429, 500, 503} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			a := nouvelAmontScripte(t, refuser(code))
			p, dir := proxyEtCasier(t)
			joue(t, p, "GET", a.hote(), "/api/etat")
			hote := a.couper()
			if w := joue(t, p, "GET", hote, "/api/etat"); w.Code != http.StatusGatewayTimeout {
				t.Errorf("hors ligne : code %d, attendu 504", w.Code)
			}
			if n := corpsGardes(t, dir); n != 0 {
				t.Errorf("%d objet(s) gardé(s) pour un %d", n, code)
			}
		})
	}
}

// Une clé portable est partagée par tous les miroirs : le refus d'un miroir
// en retard y prendrait la place de l'index qu'un autre a rendu.
func TestUnCheminPortableNeGardeNiRedirectionNiRefus(t *testing.T) {
	for nom, h := range map[string]http.HandlerFunc{
		"redirection": rediriger(http.StatusFound, "https://ailleurs.example/core.db"),
		"refus":       refuser(http.StatusNotFound),
	} {
		t.Run(nom, func(t *testing.T) {
			a := nouvelAmontScripte(t, h)
			p, dir := proxyEtCasier(t)
			joue(t, p, "GET", a.hote(), "/arch/core/os/x86_64/core.db")
			hote := a.couper()
			w := joue(t, p, "GET", hote, "/arch/core/os/x86_64/core.db")
			if w.Code != http.StatusGatewayTimeout {
				t.Errorf("hors ligne : code %d, attendu 504", w.Code)
			}
			if n := corpsGardes(t, dir); n != 0 {
				t.Errorf("%d objet(s) gardé(s) sous une clé portable", n)
			}
		})
	}
}

// L'immuable ne garde pas son refus : servi du disque sans jamais
// redemander, un 404 masquerait le fichier publié ensuite.
//
// L'index par empreinte est le cas qui isole la règle : immuable mais
// attaché à son hôte, la borne des clés portables ne l'écarte pas.
func TestLImmuableNeGardePasSonRefus(t *testing.T) {
	for _, chemin := range []string{
		"/outils/outil-2.0.tar.gz",
		"/debian/dists/trixie/by-hash/SHA256/" + strings.Repeat("ab", 32),
	} {
		a := nouvelAmontScripte(t, refuser(http.StatusNotFound))
		p, dir := proxyEtCasier(t)
		joue(t, p, "GET", a.hote(), chemin)
		hote := a.couper()
		if w := joue(t, p, "GET", hote, chemin); w.Code != http.StatusGatewayTimeout {
			t.Errorf("%s hors ligne : code %d, attendu 504", chemin, w.Code)
		}
		if n := corpsGardes(t, dir); n != 0 {
			t.Errorf("%s : %d objet(s) gardé(s) pour un 404 immuable", chemin, n)
		}
	}
}

// Un HEAD garde son statut : un installateur lit la version publiée dans le
// « Location » d'un HEAD, et n'a besoin de rien d'autre.
//
// L'amont annonce une longueur sans corps — c'est ce que fait un HEAD. La
// comparer au corps écrit ferait refuser l'objet comme tronqué.
func TestUnHeadGardeSonStatut(t *testing.T) {
	a := nouvelAmontScripte(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/o/d/releases/latest" {
			rediriger(http.StatusFound, "/o/d/releases/tag/v1.2.3")(w, r)
			return
		}
		w.Header().Set("Content-Length", "1234")
		w.WriteHeader(http.StatusOK)
	})
	p := proxyDeTest(t)
	joue(t, p, "HEAD", a.hote(), "/o/d/releases/latest")
	joue(t, p, "HEAD", a.hote(), "/api/bonjour")

	hote := a.couper()
	w := joue(t, p, "HEAD", hote, "/o/d/releases/latest")
	if w.Code != http.StatusFound {
		t.Fatalf("HEAD hors ligne : code %d, attendu 302", w.Code)
	}
	if got := w.Header().Get("Location"); got != "/o/d/releases/tag/v1.2.3" {
		t.Errorf("Location %q : une cible relative doit ressortir telle quelle", got)
	}
	w = joue(t, p, "HEAD", hote, "/api/bonjour")
	if w.Code != http.StatusOK {
		t.Fatalf("HEAD 200 hors ligne : code %d, attendu 200", w.Code)
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeStaleStatus {
		t.Errorf("servi « %s », attendu « %s »", got, OutcomeStaleStatus)
	}
	// La longueur d'un HEAD est celle du corps que rendrait le GET : elle
	// ressort telle que l'amont l'a annoncée, comme en ligne.
	if got := w.Header().Get("Content-Length"); got != "1234" {
		t.Errorf("HEAD rejoué avec la longueur %q, attendu « 1234 »", got)
	}
	// Le HEAD n'a rien donné à garder pour un GET.
	if w := joue(t, p, "GET", hote, "/api/bonjour"); w.Code != http.StatusGatewayTimeout {
		t.Errorf("GET hors ligne : code %d, attendu 504", w.Code)
	}
}

// Un client qui détient sa copie garde son 304, même quand un statut seul est
// en réserve : le lui remplacer par un refus lui ferait jeter une copie
// valide.
func TestUneConditionnelleGardeSaCopieMalgreUnStatutSeul(t *testing.T) {
	for nom, h := range map[string]http.HandlerFunc{
		"refus":       refuser(http.StatusNotFound),
		"redirection": rediriger(http.StatusFound, "https://ailleurs.example/x"),
	} {
		t.Run(nom, func(t *testing.T) {
			a := nouvelAmontScripte(t, h)
			p := proxyDeTest(t)
			joue(t, p, "GET", a.hote(), "/depot/etat")
			hote := a.couper()

			w := joue(t, p, "GET", hote, "/depot/etat", "If-None-Match", `"v1"`)
			if w.Code != http.StatusNotModified {
				t.Fatalf("code %d, attendu 304", w.Code)
			}
			if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeKeep {
				t.Errorf("servi « %s », attendu « %s »", got, OutcomeKeep)
			}
			// Sans condition, le statut ressort.
			if w := joue(t, p, "GET", hote, "/depot/etat"); w.Code == http.StatusGatewayTimeout {
				t.Error("sans condition, le statut gardé ne ressort pas")
			}
		})
	}
}

// Le chemin de l'immuable ne sert qu'un corps 200 : un méta de statut sous
// une clé immuable sortirait sinon en « 200 » vide, même l'amont joignable.
func TestLeCheminDeLImmuableRefuseUnStatut(t *testing.T) {
	a := nouvelAmontScripte(t, servir("vrai corps"))
	p, _ := proxyEtCasier(t)
	chemin := "/outils/outil-1.0.tar.gz"
	u, _ := url.Parse("http://" + a.hote() + chemin)
	cw, err := p.Store.NewWriter(CleDe("GET", u), Meta{
		URL: u.String(), Method: "GET", Status: http.StatusFound,
		Header: http.Header{"Location": []string{"https://ailleurs.example/"}},
		Class:  ClassImmutable.String(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := cw.Commit(0); err != nil {
		t.Fatal(err)
	}

	w := joue(t, p, "GET", a.hote(), chemin)
	if w.Code != http.StatusOK || w.Body.String() != "vrai corps" {
		t.Fatalf("code %d, corps %q : le statut a été servi comme un corps",
			w.Code, w.Body.String())
	}
	if a.appels() != 1 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 1", a.appels())
	}
}

// clientIntercepte rend un client HTTP dont toute connexion aboutit au cache,
// quelle que soit l'adresse demandée : c'est ce que fait le détournement du
// 80 pour une VM.
func clientIntercepte(t *testing.T, p *Proxy) *http.Client {
	t.Helper()
	front := httptest.NewServer(p.handler("http"))
	t.Cleanup(front.Close)
	cache := front.Listener.Addr().String()
	return &http.Client{
		Transport: &http.Transport{
			DialContext: func(
				ctx context.Context, reseau, _ string,
			) (net.Conn, error) {
				return (&net.Dialer{}).DialContext(ctx, reseau, cache)
			},
			DisableKeepAlives: true,
		},
		Timeout: 10 * time.Second,
	}
}

// Sur le fil, un refus rejoué est une réponse BIEN FORMÉE : une longueur
// annoncée sans corps laisse le client attendre des octets qui ne viennent
// pas, et il échoue sur une fin de flux inattendue.
func TestLeRejeuDUnRefusEstBienFormeSurLeFil(t *testing.T) {
	a := nouvelAmontScripte(t, refuser(http.StatusNotFound))
	p := proxyDeTest(t)
	client := clientIntercepte(t, p)
	adresse := a.srv.URL + "/sonde/2.root.json"

	rep, err := client.Get(adresse)
	if err != nil {
		t.Fatalf("en ligne : %v", err)
	}
	io.Copy(io.Discard, rep.Body)
	rep.Body.Close()

	a.couper()
	rep, err = client.Get(adresse)
	if err != nil {
		t.Fatalf("hors ligne : %v", err)
	}
	defer rep.Body.Close()
	corps, err := io.ReadAll(rep.Body)
	if err != nil {
		t.Fatalf("lecture du corps : %v", err)
	}
	if rep.StatusCode != http.StatusNotFound || len(corps) != 0 {
		t.Errorf("reçu %d et %d octets, attendu 404 sans corps",
			rep.StatusCode, len(corps))
	}
}

// Hors ligne, un vrai client suit la redirection rejouée jusqu'au corps
// gardé de sa cible : c'est la chaîne entière d'un installateur publié
// derrière une redirection qui redevient servable.
func TestHorsLigneLeClientSuitLaRedirectionJusquAuCorps(t *testing.T) {
	cible := nouvelAmontScripte(t, servir("echo bonjour"))
	pub := nouvelAmontScripte(t, rediriger(http.StatusFound, cible.srv.URL+"/bootstrap.sh"))
	p := proxyDeTest(t)
	client := clientIntercepte(t, p)

	lire := func(quand string) string {
		t.Helper()
		rep, err := client.Get(pub.srv.URL + "/installer.sh")
		if err != nil {
			t.Fatalf("%s : %v", quand, err)
		}
		defer rep.Body.Close()
		corps, _ := io.ReadAll(rep.Body)
		if rep.StatusCode != http.StatusOK {
			t.Fatalf("%s : code %d", quand, rep.StatusCode)
		}
		return string(corps)
	}
	if got := lire("en ligne"); got != "echo bonjour" {
		t.Fatalf("en ligne : corps %q", got)
	}
	cible.couper()
	pub.couper()
	if got := lire("hors ligne"); got != "echo bonjour" {
		t.Errorf("hors ligne : corps %q, attendu celui de la cible", got)
	}
}
