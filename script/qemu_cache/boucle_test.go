// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// portDeLAmont rend le port d'un amont de test, sous ses deux formes.
func portDeLAmont(t *testing.T, a *amontScripte) (int, string) {
	t.Helper()
	_, brut, err := net.SplitHostPort(a.hote())
	if err != nil {
		t.Fatal(err)
	}
	n, err := strconv.Atoi(brut)
	if err != nil {
		t.Fatal(err)
	}
	return n, brut
}

// Une requête qui vise le cache lui-même est refusée sans être relayée : la
// relayer la renverrait vers cette même écoute, qui la relaierait encore.
//
// L'amont de test JOUE le cache : son port est déclaré comme écoute. Un seul
// appel reçu prouve que la requête est partie.
func TestUneRequeteAuCacheLuiMemeEstRefusee(t *testing.T) {
	soi := nouvelAmontScripte(t, servir("ne doit jamais répondre"))
	port, brut := portDeLAmont(t, soi)
	p := proxyDeTest(t)
	journal := journalDeTest(t, p)
	p.Ecoutes = []int{port}

	for _, hote := range []string{"127.0.0.1:" + brut, "localhost:" + brut} {
		w := joue(t, p, "GET", hote, "/boucle")
		if w.Code != http.StatusLoopDetected {
			t.Fatalf("%s : code %d, attendu 508", hote, w.Code)
		}
		if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeError {
			t.Errorf("%s : servi « %s », attendu « %s »", hote, got, OutcomeError)
		}
		for _, l := range strings.Split(strings.TrimRight(w.Body.String(), "\n"), "\n") {
			if !strings.HasPrefix(l, "#") {
				t.Errorf("ligne exécutable par un shell : %q", l)
			}
		}
	}
	if n := soi.appels(); n != 0 {
		t.Errorf("la requête est partie %d fois vers le cache lui-même", n)
	}
	for _, l := range lignesDuJournal(t, journal) {
		if l.Outcome != OutcomeError || l.Status != http.StatusLoopDetected {
			t.Errorf("journal : %s %d, attendu error 508", l.Outcome, l.Status)
		}
	}

	// Un autre port de la même machine reste un amont comme un autre.
	autre := nouvelAmontScripte(t, servir("amont légitime"))
	if w := joue(t, p, "GET", autre.hote(), "/fichier"); w.Code != http.StatusOK {
		t.Errorf("un amont local sur un autre port est refusé : %d", w.Code)
	}
}

// Une redirection qui pointe vers le cache n'est pas suivie par lui.
func TestUneRedirectionVersLeCacheNEstPasSuivie(t *testing.T) {
	soi := nouvelAmontScripte(t, servir("ne doit jamais répondre"))
	port, brut := portDeLAmont(t, soi)
	pub := nouvelAmontScripte(t, rediriger(http.StatusFound,
		"http://127.0.0.1:"+brut+"/outil_1.0_amd64.deb"))
	p := proxyDeTest(t)
	p.Ecoutes = []int{port}

	w := joue(t, p, "GET", pub.hote(), "/outil_1.0_amd64.deb")
	if w.Code != http.StatusFound {
		t.Errorf("code %d, attendu la redirection rendue au client", w.Code)
	}
	if n := soi.appels(); n != 0 {
		t.Errorf("la redirection a été suivie %d fois vers le cache", n)
	}
}

func TestViseLeCache(t *testing.T) {
	p := &Proxy{Ecoutes: []int{8898, 8899}}
	cas := map[string]bool{
		"http://127.0.0.1:8898/x":      true,
		"http://localhost:8898/x":      true,
		"https://LOCALHOST.:8899/x":    true,
		"http://[::1]:8899/x":          true,
		"http://0.0.0.0:8898/x":        true,
		"http://127.0.0.1:8897/x":      false,
		"http://192.0.2.10:8898/x":     false,
		"https://miroir.example/x.deb": false,
	}
	for brut, attendu := range cas {
		u, _ := url.Parse(brut)
		if got := p.viseLeCache(u); got != attendu {
			t.Errorf("%s : %v, attendu %v", brut, got, attendu)
		}
	}
	// Une adresse d'une interface de CETTE machine joint aussi l'écoute.
	if adresses, err := net.InterfaceAddrs(); err == nil {
		for _, a := range adresses {
			n, ok := a.(*net.IPNet)
			if !ok || n.IP.IsLoopback() || n.IP.To4() == nil {
				continue
			}
			u, _ := url.Parse("http://" + n.IP.String() + ":8898/x")
			if !p.viseLeCache(u) {
				t.Errorf("%s, adresse de cette machine, n'est pas reconnue", u)
			}
			break
		}
	}
	// Sans écoute déclarée, rien n'est refusé.
	u, _ := url.Parse("http://127.0.0.1:8898/x")
	if (&Proxy{}).viseLeCache(u) {
		t.Error("un proxy sans écoute déclarée refuse une requête")
	}
}

func TestMemeAdresse(t *testing.T) {
	cas := []struct {
		a, b    string
		attendu bool
	}{
		{"127.0.0.1:8899", "127.0.0.1:8899", true},
		{"127.0.0.1:8899", "[::ffff:127.0.0.1]:8899", true},
		{"127.0.0.1:8899", "127.0.0.1:8898", false},
		{"192.0.2.1:443", "127.0.0.1:443", false},
		{"pas une adresse", "127.0.0.1:443", false},
	}
	for _, c := range cas {
		if got := memeAdresse(c.a, c.b); got != c.attendu {
			t.Errorf("%s / %s : %v, attendu %v", c.a, c.b, got, c.attendu)
		}
	}
}

// ecouteComptee compte dans Accept et rend la socket TCP BRUTE : une
// connexion enveloppée ferait échouer originalDst avant le tunnel, et le test
// ne prouverait plus rien. Au plafond, elle se ferme : une boucle doit rester
// bornée, pour que l'échec du test ne fasse pas tomber la machine qui le
// lance.
type ecouteComptee struct {
	*net.TCPListener
	acceptees int64
	plafond   int64
}

func (l *ecouteComptee) Accept() (net.Conn, error) {
	c, err := l.AcceptTCP()
	if err != nil {
		return nil, err
	}
	if atomic.AddInt64(&l.acceptees, 1) >= l.plafond {
		l.TCPListener.Close()
	}
	return c, nil
}

// sondeOriginalDst saute le test là où le noyau ne rend pas, pour une
// connexion locale non détournée, l'écoute elle-même comme destination
// d'origine : sans suivi de connexion, originalDst échoue avant le tunnel et
// la garde n'a rien à garder.
func sondeOriginalDst(t *testing.T) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	client, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	c, err := ln.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	dst, err := originalDst(c)
	if err != nil || !memeAdresse(dst, ln.Addr().String()) {
		t.Skipf("destination d'origine indisponible ici (%q, %v)", dst, err)
	}
}

// Une connexion non détournée vers le front TLS, pour un hôte en tunnel, a
// pour destination d'origine l'écoute elle-même. Le tunnel la rappelait :
// chaque tour acceptait une connexion de plus.
func TestUnTunnelNeSeRappellePasLuiMeme(t *testing.T) {
	sondeOriginalDst(t)
	brut, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ln := &ecouteComptee{TCPListener: brut.(*net.TCPListener), plafond: 16}
	t.Cleanup(func() { ln.Close() })

	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	const hote = "tunnel.example.invalid"
	front := &TLSFront{
		CA: ca, Proxy: proxyDeTest(t), Refusals: NewRefusals([]string{hote}),
	}
	go front.Serve(ln)

	c, err := net.DialTimeout("tcp", ln.Addr().String(), 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if _, err := c.Write(clientHelloBrut(t, hote)); err != nil {
		t.Fatal(err)
	}
	c.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, err := io.ReadAll(c); err != nil {
		t.Errorf("la connexion n'est pas refermée : %v", err)
	}
	if n := atomic.LoadInt64(&ln.acceptees); n != 1 {
		t.Errorf("%d connexions acceptées pour une seule demande :"+
			" le tunnel s'est rappelé lui-même", n)
	}
}
