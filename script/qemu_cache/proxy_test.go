// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
)

// amont monte un serveur qui compte ce qu'on lui demande. Le compteur EST la
// mesure de tous ces tests : le cache n'a d'intérêt que s'il fait baisser le
// nombre de requêtes qui sortent.
type amont struct {
	srv   *httptest.Server
	appel int64
	corps string
}

func nouvelAmont(t *testing.T, corps string) *amont {
	t.Helper()
	a := &amont{corps: corps}
	a.srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&a.appel, 1)
			w.Header().Set("Content-Type", "application/octet-stream")
			io.WriteString(w, a.corps)
		}))
	t.Cleanup(a.srv.Close)
	return a
}

func (a *amont) appels() int64 { return atomic.LoadInt64(&a.appel) }

func (a *amont) hote() string {
	u, _ := url.Parse(a.srv.URL)
	return u.Host
}

func proxyDeTest(t *testing.T) *Proxy {
	t.Helper()
	alog, err := OpenAccessLog("")
	if err != nil {
		t.Fatalf("journal : %v", err)
	}
	return NewProxy(&Store{Dir: t.TempDir()}, alog)
}

// demande joue une requête telle que l'interception transparente la présente :
// une ligne de requête sans hôte, l'hôte venant de l'en-tête.
func demande(t *testing.T, p *Proxy, hote, chemin string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest("GET", chemin, nil)
	r.Host = hote
	w := httptest.NewRecorder()
	p.serve(w, r, "http")
	return w
}

// Invariant 1 : un index n'est JAMAIS servi du cache tant que l'amont répond.
//
// C'est la règle qui empêche le cache de provoquer le « failed retrieving
// file … 404 » sur un paquet retiré des miroirs : servir un index périmé
// promet des fichiers qui n'existent plus.
func TestIndexJamaisServiQuandAmontRepond(t *testing.T) {
	a := nouvelAmont(t, "base de paquets")
	p := proxyDeTest(t)

	for i := 1; i <= 3; i++ {
		w := demande(t, p, a.hote(), "/arch/core/os/x86_64/core.db")
		if w.Code != 200 {
			t.Fatalf("requête %d : code %d", i, w.Code)
		}
		if got := w.Header().Get("X-ERPLibre-Cache"); got != "miss" {
			t.Errorf("requête %d : servie « %s », attendu « miss »", i, got)
		}
	}
	if n := a.appels(); n != 3 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 3 : un index a été servi du cache", n)
	}
}

// Invariant 2 : un fichier de paquet est servi du cache dès la seconde
// demande. C'est le gain que l'outil existe pour produire.
func TestPaquetServiDuCache(t *testing.T) {
	a := nouvelAmont(t, "contenu du paquet")
	p := proxyDeTest(t)
	chemin := "/arch/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst"

	w1 := demande(t, p, a.hote(), chemin)
	if w1.Header().Get("X-ERPLibre-Cache") != "miss" {
		t.Fatalf("première demande servie du cache : %s",
			w1.Header().Get("X-ERPLibre-Cache"))
	}
	w2 := demande(t, p, a.hote(), chemin)
	if got := w2.Header().Get("X-ERPLibre-Cache"); got != OutcomeHit {
		t.Errorf("seconde demande servie « %s », attendu « %s »", got, OutcomeHit)
	}
	if w2.Body.String() != a.corps {
		t.Errorf("corps servi %q, attendu %q", w2.Body.String(), a.corps)
	}
	if n := a.appels(); n != 1 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 1", n)
	}
}

// Invariant 3 : l'amont muet fait sortir la copie stockée, index compris.
// C'est ce qui rend un déploiement possible sans réseau du tout.
func TestIndexServiQuandAmontMuet(t *testing.T) {
	a := nouvelAmont(t, "base de paquets")
	p := proxyDeTest(t)
	chemin := "/arch/core/os/x86_64/core.db"

	if w := demande(t, p, a.hote(), chemin); w.Code != 200 {
		t.Fatalf("remplissage : code %d", w.Code)
	}
	hote := a.hote()
	a.srv.Close() // l'amont devient injoignable

	w := demande(t, p, hote, chemin)
	if w.Code != 200 {
		t.Fatalf("hors ligne : code %d, attendu 200", w.Code)
	}
	if got := w.Header().Get("X-ERPLibre-Cache"); got != OutcomeStale {
		t.Errorf("servi « %s », attendu « %s »", got, OutcomeStale)
	}
	if w.Header().Get("X-ERPLibre-Cache-Date") == "" {
		t.Error("la date de l'instantané manque : l'opérateur ne peut pas savoir de quand datent ses octets")
	}
	if w.Body.String() != a.corps {
		t.Errorf("corps servi %q, attendu %q", w.Body.String(), a.corps)
	}
}

// Invariant 4 : hors ligne et sans copie, l'erreur NOMME le fichier.
//
// Un 404 nu ferait accuser le miroir : le client n'a aucun moyen de savoir
// qu'un cache s'est interposé.
func TestDefautHorsLigneNommeLeFichier(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	hote := a.hote()
	a.srv.Close()
	p := proxyDeTest(t)

	w := demande(t, p, hote, "/arch/core/os/x86_64/jamais-vu.pkg.tar.zst")
	if w.Code != http.StatusGatewayTimeout {
		t.Fatalf("code %d, attendu %d", w.Code, http.StatusGatewayTimeout)
	}
	corps := w.Body.String()
	for _, attendu := range []string{"jamais-vu.pkg.tar.zst", hote, "erplibre_go_qemu_cache"} {
		if !strings.Contains(corps, attendu) {
			t.Errorf("le message ne dit pas %q :\n%s", attendu, corps)
		}
	}
}

// Une requête partielle ne remplit pas le cache : un fragment ne sert à rien
// à la demande suivante, et le garder comme un corps entier servirait un
// paquet tronqué.
func TestRequetePartielleNonGardee(t *testing.T) {
	a := nouvelAmont(t, "0123456789")
	p := proxyDeTest(t)
	chemin := "/x/paquet-1-1-x86_64.pkg.tar.zst"

	r := httptest.NewRequest("GET", chemin, nil)
	r.Host = a.hote()
	r.Header.Set("Range", "bytes=0-4")
	p.serve(httptest.NewRecorder(), r, "http")

	// Une demande entière ensuite doit ressortir à l'amont.
	w := demande(t, p, a.hote(), chemin)
	if got := w.Header().Get("X-ERPLibre-Cache"); got == OutcomeHit {
		t.Error("un fragment est entré au cache et a été servi comme un corps entier")
	}
	if n := a.appels(); n != 2 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 2", n)
	}
}

// Un POST ne se cache pas : il change un état à l'amont.
func TestPostNonCache(t *testing.T) {
	a := nouvelAmont(t, "réponse")
	p := proxyDeTest(t)

	for i := 0; i < 2; i++ {
		r := httptest.NewRequest("POST", "/api/quelque-chose.whl", strings.NewReader("x"))
		r.Host = a.hote()
		p.serve(httptest.NewRecorder(), r, "http")
	}
	if n := a.appels(); n != 2 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 2 : un POST a été caché", n)
	}
}

// Un transport qui note le client par lequel la requête est passée.
type transportTemoin struct {
	nom  string
	vues *[]string
}

func (t transportTemoin) RoundTrip(r *http.Request) (*http.Response, error) {
	*t.vues = append(*t.vues, t.nom)
	return &http.Response{
		StatusCode: 200,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader("")),
		Request:    r,
	}, nil
}

// Le délai court existe pour que le repli hors ligne arrive AVANT que le
// client renonce. Il prenait le calcul d'un serveur git pour un amont
// injoignable — mesuré à seize secondes avant le premier octet — et rendait un
// 504 sur un dépôt parfaitement joignable, faisant échouer « repo sync ».
func TestGitPasseParLeClientPatient(t *testing.T) {
	var vues []string
	p := &Proxy{
		Client: &http.Client{
			Transport: transportTemoin{"court", &vues},
		},
		ClientPatient: &http.Client{
			Transport: transportTemoin{"patient", &vues},
		},
	}
	cas := []struct {
		brut    string
		attendu string
	}{
		{"https://git.example/o/d.git/info/refs?service=git-upload-pack",
			"patient"},
		{"https://git.example/o/d.git/git-upload-pack", "patient"},
		{"https://miroir.example/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst",
			"court"},
		{"https://miroir.example/core/os/x86_64/core.db", "court"},
	}
	for _, c := range cas {
		vues = nil
		u, _ := url.Parse(c.brut)
		r, _ := http.NewRequest("GET", c.brut, nil)
		if _, err := p.fetch(r, u); err != nil {
			t.Fatalf("%s : %v", c.brut, err)
		}
		if len(vues) != 1 || vues[0] != c.attendu {
			t.Errorf("%s passé par %v, attendu « %s »",
				c.brut, vues, c.attendu)
		}
	}
}

// Les deux clients ne se distinguent que par leur patience : un amont
// injoignable reste détecté à l'établissement, en quatre secondes, dans les
// deux cas.
func TestLeClientPatientLestUniquementSurLesEnTetes(t *testing.T) {
	p := NewProxy(&Store{Dir: t.TempDir()}, nil)
	court := p.Client.Transport.(*http.Transport)
	patient := p.ClientPatient.Transport.(*http.Transport)
	if patient.ResponseHeaderTimeout <= court.ResponseHeaderTimeout {
		t.Errorf("le client patient n'attend pas plus : %v contre %v",
			patient.ResponseHeaderTimeout, court.ResponseHeaderTimeout)
	}
	if patient.TLSHandshakeTimeout != court.TLSHandshakeTimeout {
		t.Error("le délai de poignée de main ne doit pas changer")
	}
}

// Un paquet publié derrière une redirection vers une URL SIGNÉE.
//
// La cible change à chaque requête — c'est ce que fait une signature à
// péremption. Rendre la redirection au client, en comptant qu'il la
// redemandera au travers du cache, suppose une cible stable : ici la machine
// suivante ne retrouve rien et retélécharge le paquet en entier.
func TestPaquetDerriereUneRedirectionSignee(t *testing.T) {
	var telechargements, signature int64
	contenu := strings.Repeat("charge utile", 64)

	stockage := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&telechargements, 1)
			io.WriteString(w, contenu)
		}))
	t.Cleanup(stockage.Close)

	publication := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			n := atomic.AddInt64(&signature, 1)
			http.Redirect(w, r,
				stockage.URL+"/objet?signature="+string(rune('a'+n)),
				http.StatusFound)
		}))
	t.Cleanup(publication.Close)

	u, _ := url.Parse(publication.URL)
	p := proxyDeTest(t)
	chemin := "/paquets/releases/download/1.0/outil_1.0_amd64.deb"

	for i := 1; i <= 3; i++ {
		w := demande(t, p, u.Host, chemin)
		if w.Code != 200 {
			t.Fatalf("requête %d : code %d, attendu 200", i, w.Code)
		}
		if w.Body.String() != contenu {
			t.Fatalf("requête %d : corps de %d octets", i, w.Body.Len())
		}
	}
	if n := atomic.LoadInt64(&telechargements); n != 1 {
		t.Errorf("le paquet est descendu %d fois, attendu 1 :"+
			" la redirection empêche le cache de servir", n)
	}
}

// Un index, lui, garde l'ancien comportement : la redirection lui est rendue,
// et il la redemandera. Rien n'est gardé d'un index tant que l'amont répond,
// donc suivre la chaîne n'apporterait rien et masquerait au client l'hôte qui
// lui a réellement répondu.
func TestUnIndexRecoitSaRedirection(t *testing.T) {
	cible := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			io.WriteString(w, "base")
		}))
	t.Cleanup(cible.Close)
	publication := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			http.Redirect(w, r, cible.URL+"/vraie.db", http.StatusFound)
		}))
	t.Cleanup(publication.Close)

	u, _ := url.Parse(publication.URL)
	w := demande(t, proxyDeTest(t), u.Host, "/arch/core/os/x86_64/core.db")
	if w.Code != http.StatusFound {
		t.Errorf("code %d, attendu 302 : la redirection a été suivie", w.Code)
	}
}

// Une boucle de redirections doit rendre la main plutôt que tourner.
func TestUneBoucleDeRedirectionsSarrete(t *testing.T) {
	var vues int64
	var srv *httptest.Server
	srv = httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&vues, 1)
			http.Redirect(w, r, srv.URL+"/tourne.deb", http.StatusFound)
		}))
	t.Cleanup(srv.Close)

	u, _ := url.Parse(srv.URL)
	w := demande(t, proxyDeTest(t), u.Host, "/tourne.deb")
	if w.Code != http.StatusFound {
		t.Errorf("code %d, attendu 302 au bout de la chaîne", w.Code)
	}
	if n := atomic.LoadInt64(&vues); n > maxRedirections+1 {
		t.Errorf("%d requêtes pour une boucle, borne %d",
			n, maxRedirections+1)
	}
}
