// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// amontAPlages sert un corps fixe et honore « Range » comme un miroir : 206
// et le seul fragment demandé. Il compte séparément les plages et les corps
// entiers envoyés.
type amontAPlages struct {
	srv     *httptest.Server
	plages  int64
	entiers int64
}

func nouvelAmontAPlages(t *testing.T, corps string) *amontAPlages {
	t.Helper()
	a := &amontAPlages{}
	a.srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("Range") != "" {
				atomic.AddInt64(&a.plages, 1)
			} else {
				atomic.AddInt64(&a.entiers, 1)
			}
			http.ServeContent(w, r, "", time.Time{}, bytes.NewReader([]byte(corps)))
		}))
	t.Cleanup(a.srv.Close)
	return a
}

func (a *amontAPlages) hote() string {
	return strings.TrimPrefix(a.srv.URL, "http://")
}

func demandePlage(t *testing.T, p *Proxy, hote, chemin, plage string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest("GET", chemin, nil)
	r.Host = hote
	r.Header.Set("Range", plage)
	w := httptest.NewRecorder()
	p.serve(w, r, "http")
	return w
}

const metadonneeZck = "/fedora/updates/repodata/" +
	"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" +
	"-primary.xml.zck"

// Une plage sur une métadonnée figée absente fait prendre le fichier entier,
// une fois ; les plages suivantes sortent du disque sans rien demander à
// l'amont.
func TestUnePlageFaitGarderLeFichierEntier(t *testing.T) {
	a := nouvelAmontAPlages(t, "en-tete|morceau-1|morceau-2")
	p := proxyDeTest(t)

	w := demandePlage(t, p, a.hote(), metadonneeZck, "bytes=0-6")
	if w.Code != http.StatusPartialContent || w.Body.String() != "en-tete" {
		t.Fatalf("première plage : %d %q", w.Code, w.Body.String())
	}
	p.attendreCompletions()

	w = demandePlage(t, p, a.hote(), metadonneeZck, "bytes=8-16")
	if w.Code != http.StatusPartialContent || w.Body.String() != "morceau-1" {
		t.Errorf("seconde plage : %d %q", w.Code, w.Body.String())
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeHit {
		t.Errorf("seconde plage servie « %s », attendu « %s »", got, OutcomeHit)
	}
	if n := atomic.LoadInt64(&a.entiers); n != 1 {
		t.Errorf("%d corps entiers pris à l'amont, attendu 1", n)
	}
	if n := atomic.LoadInt64(&a.plages); n != 1 {
		t.Errorf("%d plages envoyées à l'amont, attendu 1", n)
	}
}

// Amont coupé, la plage d'une VM suivante sort du disque : c'est ce qui manquait
// à une installation hors ligne.
func TestHorsLigneLaPlageSortDuDisque(t *testing.T) {
	a := nouvelAmontAPlages(t, "en-tete|morceau-1|morceau-2")
	p := proxyDeTest(t)
	hote := a.hote()
	demandePlage(t, p, hote, metadonneeZck, "bytes=0-6")
	p.attendreCompletions()
	a.srv.Close()

	w := demandePlage(t, p, hote, metadonneeZck, "bytes=18-26")
	if w.Code != http.StatusPartialContent || w.Body.String() != "morceau-2" {
		t.Errorf("hors ligne : %d %q", w.Code, w.Body.String())
	}
}

// Un index volatile demandé par plage ne déclenche aucune prise : il n'est
// jamais servi du disque tant que l'amont répond, le garder n'épargnerait rien.
func TestUnePlageSurUnIndexNePrendRien(t *testing.T) {
	a := nouvelAmontAPlages(t, "index de dépôt")
	p := proxyDeTest(t)

	demandePlage(t, p, a.hote(), "/fedora/repodata/repomd.xml", "bytes=0-4")
	p.attendreCompletions()
	if n := atomic.LoadInt64(&a.entiers); n != 0 {
		t.Errorf("%d corps entiers pris pour un index volatile, attendu 0", n)
	}
}

// Plusieurs plages simultanées sur le même fichier ne prennent le corps entier
// qu'une fois.
func TestDesPlagesSimultaneesNePrennentQuUneFois(t *testing.T) {
	a := nouvelAmontAPlages(t, strings.Repeat("x", 1<<16))
	p := proxyDeTest(t)
	u, _ := url.Parse("http://" + a.hote() + metadonneeZck)
	key := CleDe("GET", u)
	p.completions.Store(key, true) // une prise est déjà en cours

	for i := 0; i < 5; i++ {
		demandePlage(t, p, a.hote(), metadonneeZck, "bytes=0-9")
	}
	p.attendreCompletions()
	if n := atomic.LoadInt64(&a.entiers); n != 0 {
		t.Errorf("%d prises lancées alors qu'une était en cours, attendu 0", n)
	}
	p.completions.Delete(key)
	demandePlage(t, p, a.hote(), metadonneeZck, "bytes=0-9")
	p.attendreCompletions()
	if n := atomic.LoadInt64(&a.entiers); n != 1 {
		t.Errorf("%d prises après la fin de la première, attendu 1", n)
	}
}
