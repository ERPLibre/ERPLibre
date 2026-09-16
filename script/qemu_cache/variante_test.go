// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// Les deux en-têtes Accept d'un client de registre : la fiche abrégée, et la
// fiche complète.
const (
	acceptAbrege  = "application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8, */*"
	acceptComplet = "application/json"
)

// amontAVariantes sert deux représentations d'une même URL selon Accept, chacune
// sous son ETag, avec « Vary: Accept » ; « 304 » à qui présente l'ETag de la
// représentation qu'il demande. Il compte les corps envoyés par représentation.
type amontAVariantes struct {
	srv   *httptest.Server
	mu    sync.Mutex
	vary  bool
	corps map[string]int
}

func nouvelAmontAVariantes(t *testing.T, vary bool) *amontAVariantes {
	t.Helper()
	a := &amontAVariantes{vary: vary, corps: map[string]int{}}
	a.srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			a.mu.Lock()
			defer a.mu.Unlock()
			rep, etag, corps := "complète", `"complet"`, "fiche complète, très longue"
			if strings.Contains(r.Header.Get("Accept"), "install-v1") {
				rep, etag, corps = "abrégée", `"abrege"`, "fiche abrégée"
			}
			if a.vary {
				w.Header().Set("Vary", "accept-encoding, accept")
			}
			w.Header().Set("ETag", etag)
			if r.Header.Get("If-None-Match") == etag {
				w.WriteHeader(http.StatusNotModified)
				return
			}
			a.corps[rep]++
			io.WriteString(w, corps)
		}))
	t.Cleanup(a.srv.Close)
	return a
}

func (a *amontAVariantes) envoyes(rep string) int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.corps[rep]
}

func (a *amontAVariantes) hote() string {
	u, _ := url.Parse(a.srv.URL)
	return u.Host
}

const ficheNpm = "/npm"

func demandeAccept(t *testing.T, p *Proxy, hote, accept string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest("GET", ficheNpm, nil)
	r.Host = hote
	if accept != "" {
		r.Header.Set("Accept", accept)
	}
	w := httptest.NewRecorder()
	p.serve(w, r, "http")
	return w
}

// Deux représentations demandées tour à tour ne repartent qu'une fois chacune :
// rangée à part, l'une ne remplace plus l'autre.
func TestDeuxRepresentationsQuiAlternentNeRepartentQuUneFois(t *testing.T) {
	a := nouvelAmontAVariantes(t, true)
	u := &url.URL{Scheme: "http", Host: a.hote(), Path: ficheNpm}
	if Classify(u) != ClassVolatile || PortableParChemin(u) {
		t.Fatalf("%s n'est plus un volatil rangé avec son hôte", ficheNpm)
	}
	p := proxyDeTest(t)

	ordre := []string{acceptAbrege, acceptComplet, acceptAbrege, acceptComplet, acceptAbrege}
	for i, accept := range ordre {
		w := demandeAccept(t, p, a.hote(), accept)
		veut := "fiche complète, très longue"
		if accept == acceptAbrege {
			veut = "fiche abrégée"
		}
		if w.Body.String() != veut {
			t.Fatalf("demande %d : corps %q, attendu %q", i+1, w.Body.String(), veut)
		}
	}
	if n := a.envoyes("abrégée"); n != 1 {
		t.Errorf("fiche abrégée envoyée %d fois, attendu 1", n)
	}
	if n := a.envoyes("complète"); n != 1 {
		t.Errorf("fiche complète envoyée %d fois, attendu 1", n)
	}
}

// La clé de base reste tenue : --detient, le pré-vol et le rattrapage hors
// ligne ne connaissent pas l'en-tête Accept.
func TestLaCleDeBaseResteTenuePourDetient(t *testing.T) {
	a := nouvelAmontAVariantes(t, true)
	p := proxyDeTest(t)
	demandeAccept(t, p, a.hote(), acceptAbrege)

	d := p.Store.Detenir("GET", "http://"+a.hote()+ficheNpm)
	if d.Verdict != VerdictGarde {
		t.Errorf("--detient dit %q pour une fiche gardée", d.Verdict)
	}
}

// Sans « Vary: Accept », rien n'est rangé à part : la réponse ne varie pas, et
// la dupliquer ne ferait que doubler le disque.
func TestSansVaryAcceptAucuneVariante(t *testing.T) {
	a := nouvelAmontAVariantes(t, false)
	p := proxyDeTest(t)
	demandeAccept(t, p, a.hote(), acceptAbrege)

	base := CleDe("GET", &url.URL{Scheme: "http", Host: a.hote(), Path: ficheNpm})
	if p.Store.Detient(CleVariante(base, acceptAbrege)) {
		t.Error("une variante a été rangée pour une réponse sans Vary: Accept")
	}
	if !p.Store.Detient(base) {
		t.Error("la clé de base n'est plus écrite")
	}
}

// Amont muet : le client reçoit SA représentation, pas la dernière rangée sous
// la base, qui peut être l'autre.
func TestHorsLigneLaRepresentationDuClientSort(t *testing.T) {
	a := nouvelAmontAVariantes(t, true)
	p := proxyDeTest(t)
	hote := a.hote()
	demandeAccept(t, p, hote, acceptAbrege)
	demandeAccept(t, p, hote, acceptComplet) // la base porte désormais la complète
	a.srv.Close()

	w := demandeAccept(t, p, hote, acceptAbrege)
	if w.Code != http.StatusOK || w.Body.String() != "fiche abrégée" {
		t.Errorf("hors ligne : %d %q, attendu la fiche abrégée", w.Code, w.Body.String())
	}
}

// Une requête sans Accept ne choisit aucune représentation : elle suit la clé
// de base, comme avant.
func TestSansAcceptLaBaseSeule(t *testing.T) {
	if CleVariante("cle", "") != "" || CleVariante("cle", "   ") != "" {
		t.Error("un Accept vide produit une clé de variante")
	}
	if CleVariante("cle", "Application/JSON") != CleVariante("cle", "application/json") {
		t.Error("la casse d'Accept change la variante")
	}
	if !varieSurAccept(http.Header{"Vary": {"accept-encoding, Accept"}}) ||
		varieSurAccept(http.Header{"Vary": {"accept-encoding"}}) {
		t.Error("lecture de Vary erronée")
	}
}

// Servir une variante sert aussi l'objet de base : sa date d'usage suit, sans
// quoi un nettoyage par âge retirerait la base qu'on sert encore, et --detient
// la dirait absente.
func TestServirUneVarianteRajeunitLaBase(t *testing.T) {
	a := nouvelAmontAVariantes(t, true)
	p := proxyDeTest(t)
	demandeAccept(t, p, a.hote(), acceptAbrege)

	base := CleDe("GET", &url.URL{Scheme: "http", Host: a.hote(), Path: ficheNpm})
	_, corpsBase := p.Store.paths(base)
	vieux := time.Now().Add(-90 * 24 * time.Hour)
	if err := os.Chtimes(corpsBase, vieux, vieux); err != nil {
		t.Fatal(err)
	}
	w := demandeAccept(t, p, a.hote(), acceptAbrege)
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeRevalidated {
		t.Fatalf("seconde demande servie « %s », attendu « %s »", got, OutcomeRevalidated)
	}
	fi, err := os.Stat(corpsBase)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(fi.ModTime()) > time.Hour {
		t.Errorf("la base date encore du %s : son usage n'a pas été noté", fi.ModTime())
	}
}
