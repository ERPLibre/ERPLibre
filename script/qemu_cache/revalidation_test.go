// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"testing"
)

// amontValidant sert un corps sous un ETag et rend « 304 » à qui présente le
// bon. Il compte les CORPS envoyés, qui sont ce que la revalidation épargne,
// et note la condition reçue à chaque requête.
type amontValidant struct {
	srv        *httptest.Server
	mu         sync.Mutex
	etag       string // vide : aucune ETag, seulement une date
	corps      string
	corpsParti int
	requetes   int
	conditions []string
}

func nouvelAmontValidant(t *testing.T, etag, corps string) *amontValidant {
	t.Helper()
	a := &amontValidant{etag: etag, corps: corps}
	a.srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			a.mu.Lock()
			defer a.mu.Unlock()
			a.requetes++
			cond := r.Header.Get("If-None-Match")
			if cond == "" && r.Header.Get("If-Modified-Since") != "" {
				cond = "date:" + r.Header.Get("If-Modified-Since")
			}
			a.conditions = append(a.conditions, cond)
			if a.etag == "" {
				w.Header().Set("Last-Modified", "Mon, 14 Sep 2026 14:53:55 GMT")
			} else {
				w.Header().Set("ETag", a.etag)
				if cond == a.etag {
					w.WriteHeader(http.StatusNotModified)
					return
				}
			}
			a.corpsParti++
			io.WriteString(w, a.corps)
		}))
	t.Cleanup(a.srv.Close)
	return a
}

func (a *amontValidant) changer(etag, corps string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.etag, a.corps = etag, corps
}

func (a *amontValidant) releve() (requetes, corps int, conditions []string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.requetes, a.corpsParti, append([]string(nil), a.conditions...)
}

func (a *amontValidant) hote() string {
	u, _ := url.Parse(a.srv.URL)
	return u.Host
}

// indexPip est un index volatil rangé avec son hôte : la revalidation lui est
// ouverte. Le test l'éprouve avant de s'en servir, pour ne pas mesurer une
// règle d'exclusion à la place de celle qu'il nomme.
const indexPip = "/simple/requests/"

func exigerIndexRevalidable(t *testing.T, hote string) {
	t.Helper()
	u := &url.URL{Scheme: "http", Host: hote, Path: indexPip}
	if Classify(u) != ClassVolatile {
		t.Fatalf("%s n'est plus volatil : le test mesurerait autre chose", indexPip)
	}
}

// Un index que l'amont déclare inchangé sort du disque, et son corps ne
// repart pas : c'est tout le gain. L'amont est pourtant interrogé à CHAQUE
// demande — un index n'est jamais servi sans son accord tant qu'il répond.
func TestUnIndexConfirmeParLAmontSortDuDisque(t *testing.T) {
	a := nouvelAmontValidant(t, `"v1"`, "index pip, version 1")
	exigerIndexRevalidable(t, a.hote())
	p := proxyDeTest(t)

	for i := 1; i <= 3; i++ {
		w := demande(t, p, a.hote(), indexPip)
		if w.Code != http.StatusOK || w.Body.String() != "index pip, version 1" {
			t.Fatalf("demande %d : %d %q", i, w.Code, w.Body.String())
		}
		veut := OutcomeRevalidated
		if i == 1 {
			veut = "miss"
		}
		if got := w.Header().Get("X-ERPLibre-Cache"); got != veut {
			t.Errorf("demande %d servie « %s », attendu « %s »", i, got, veut)
		}
	}
	requetes, corps, conditions := a.releve()
	if requetes != 3 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 3 : il doit juger chacune", requetes)
	}
	if corps != 1 {
		t.Errorf("%d corps envoyés, attendu 1 : la copie confirmée a été retéléchargée", corps)
	}
	if conditions[0] != "" || conditions[1] != `"v1"` || conditions[2] != `"v1"` {
		t.Errorf("conditions reçues %q : la première sans, les suivantes avec l'ETag gardé", conditions)
	}
}

// Un index qui a changé est repris en entier, remplace la copie, et c'est son
// NOUVEL ETag qui part ensuite.
func TestUnIndexChangeEstRepris(t *testing.T) {
	a := nouvelAmontValidant(t, `"v1"`, "version 1")
	exigerIndexRevalidable(t, a.hote())
	p := proxyDeTest(t)

	demande(t, p, a.hote(), indexPip)
	a.changer(`"v2"`, "version 2")
	if w := demande(t, p, a.hote(), indexPip); w.Body.String() != "version 2" {
		t.Fatalf("après changement, corps %q", w.Body.String())
	}
	w := demande(t, p, a.hote(), indexPip)
	if w.Body.String() != "version 2" || w.Header().Get("X-ERPLibre-Cache") != OutcomeRevalidated {
		t.Errorf("troisième demande : %q servie « %s »", w.Body.String(), w.Header().Get("X-ERPLibre-Cache"))
	}
	_, corps, conditions := a.releve()
	if corps != 2 {
		t.Errorf("%d corps envoyés, attendu 2", corps)
	}
	if conditions[2] != `"v2"` {
		t.Errorf("condition de la troisième demande %q, attendu l'ETag de la copie remplacée", conditions[2])
	}
}

// Sans ETag, rien ne part : une date seule validerait, sous « Vary: Accept »,
// une représentation qui n'est pas celle gardée.
func TestSansETagLIndexRepartEntier(t *testing.T) {
	a := nouvelAmontValidant(t, "", "index sans ETag")
	exigerIndexRevalidable(t, a.hote())
	p := proxyDeTest(t)

	demande(t, p, a.hote(), indexPip)
	w := demande(t, p, a.hote(), indexPip)
	if got := w.Header().Get("X-ERPLibre-Cache"); got != "miss" {
		t.Errorf("seconde demande servie « %s », attendu « miss »", got)
	}
	_, corps, conditions := a.releve()
	if corps != 2 || conditions[1] != "" {
		t.Errorf("%d corps, condition %q : attendu 2 corps et aucune condition", corps, conditions[1])
	}
}

// La condition du client reste la sienne : il demande si SA copie a changé,
// et lui substituer l'ETag du cache répondrait à une autre question.
func TestLaConditionDuClientNEstPasRemplacee(t *testing.T) {
	a := nouvelAmontValidant(t, `"v1"`, "version 1")
	exigerIndexRevalidable(t, a.hote())
	p := proxyDeTest(t)

	demande(t, p, a.hote(), indexPip)
	r := httptest.NewRequest("GET", indexPip, nil)
	r.Host = a.hote()
	r.Header.Set("If-None-Match", `"copie-du-client"`)
	w := httptest.NewRecorder()
	p.serve(w, r, "http")

	if w.Code != http.StatusOK || w.Body.String() != "version 1" {
		t.Errorf("client dont la copie diffère : %d %q", w.Code, w.Body.String())
	}
	_, _, conditions := a.releve()
	if conditions[1] != `"copie-du-client"` {
		t.Errorf("condition envoyée %q, attendu celle du client", conditions[1])
	}
}

// Une clé sans hôte est partagée par tous les miroirs d'une liste qui tourne :
// présenter à l'un l'ETag gardé depuis un autre ne se fait pas, et l'index
// repart entier comme avant.
func TestUneCleSansHoteNeRevalidePas(t *testing.T) {
	a := nouvelAmontValidant(t, `"v1"`, "base de paquets")
	const chemin = "/arch/core/os/x86_64/core.db"
	u := &url.URL{Scheme: "http", Host: a.hote(), Path: chemin}
	if !PortableParChemin(u) || Classify(u) != ClassVolatile {
		t.Fatalf("%s n'est plus un index volatil rangé sans hôte", chemin)
	}
	p := proxyDeTest(t)

	demande(t, p, a.hote(), chemin)
	w := demande(t, p, a.hote(), chemin)
	if got := w.Header().Get("X-ERPLibre-Cache"); got != "miss" {
		t.Errorf("seconde demande servie « %s », attendu « miss »", got)
	}
	_, corps, conditions := a.releve()
	if corps != 2 || conditions[1] != "" {
		t.Errorf("%d corps, condition %q : attendu 2 corps et aucune condition", corps, conditions[1])
	}
}
