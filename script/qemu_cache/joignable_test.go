// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"context"
	"errors"
	"log"
	"net"
	"net/http"
	"net/http/cgi"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

// refusEtablissement est l'erreur que rend un établissement refusé : un
// « *net.OpError » d'opération « dial » portant ECONNREFUSED.
func refusEtablissement() error {
	return &net.OpError{Op: "dial", Net: "tcp", Err: &os.SyscallError{
		Syscall: "connect", Err: syscall.ECONNREFUSED,
	}}
}

// Seul un échec d'ÉTABLISSEMENT fait tenir un amont pour muet. Un serveur
// lent, une poignée de main manquée ou un nom inexistant disent autre chose.
func TestEstEchecDEtablissement(t *testing.T) {
	enveloppe := func(err error) error {
		return &url.Error{Op: "Get", URL: "http://amont.example/x", Err: err}
	}
	muets := []error{
		refusEtablissement(),
		enveloppe(refusEtablissement()),
		&net.OpError{Op: "dial", Err: os.ErrDeadlineExceeded},
		&net.OpError{Op: "dial", Err: &os.SyscallError{Err: syscall.EHOSTUNREACH}},
		&net.OpError{Op: "dial", Err: &os.SyscallError{Err: syscall.ENETUNREACH}},
	}
	for _, err := range muets {
		if !estEchecDEtablissement(err) {
			t.Errorf("%v n'est pas reconnu comme un établissement manqué", err)
		}
	}
	vivants := []error{
		nil,
		// Un serveur lent à répondre est LÀ : le tenir pour muet servirait
		// une copie périmée à la place d'une réponse qui venait.
		&net.OpError{Op: "read", Err: os.ErrDeadlineExceeded},
		enveloppe(errors.New("net/http: timeout awaiting response headers")),
		errors.New("net/http: TLS handshake timeout"),
		errors.New("remote error: tls: handshake failure"),
		&net.OpError{Op: "dial", Err: &net.DNSError{
			Err: "no such host", Name: "absent.example.invalid", IsNotFound: true,
		}},
		&net.OpError{Op: "dial", Err: context.Canceled},
	}
	for _, err := range vivants {
		if estEchecDEtablissement(err) {
			t.Errorf("%v pris pour un amont muet", err)
		}
	}
}

// La mémoire tient une fenêtre, puis rend l'amont à sa première chance.
func TestLaMemoireDUnAmontMuetSEteintAvecLaFenetre(t *testing.T) {
	maintenant := time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	j := &Joignabilite{
		Fenetre:    20 * time.Second,
		Maintenant: func() time.Time { return maintenant },
	}
	const a = "amont.example:443"
	if !j.Echec(a, refusEtablissement()) || !j.ConnuMuet(a) {
		t.Fatal("un établissement refusé n'est pas retenu")
	}
	maintenant = maintenant.Add(19 * time.Second)
	if !j.ConnuMuet(a) {
		t.Error("l'amont est oublié avant la fin de la fenêtre")
	}
	maintenant = maintenant.Add(time.Second)
	if j.ConnuMuet(a) {
		t.Error("l'amont reste muet au-delà de la fenêtre")
	}

	j.Echec(a, refusEtablissement())
	j.Reussite(a)
	if j.ConnuMuet(a) {
		t.Error("une réussite n'efface pas l'échec")
	}
	if j.Echec(a, errors.New("net/http: timeout awaiting response headers")) ||
		j.ConnuMuet(a) {
		t.Error("une erreur qui n'est pas un établissement est retenue")
	}
	var nulle *Joignabilite
	nulle.Echec(a, refusEtablissement())
	if nulle.ConnuMuet(a) {
		t.Error("une mémoire nulle retient quelque chose")
	}
}

// Un amont muet n'est pas recomposé à chaque requête : la première paie le
// délai d'établissement, les suivantes vont droit au repli — et le repli
// sert la copie gardée comme avant.
func TestUnAmontMuetNEstPasRecomposeAChaqueRequete(t *testing.T) {
	a := nouvelAmontScripte(t, servir("index courant"))
	p := proxyDeTest(t)
	maintenant := time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	p.Muets = &Joignabilite{Maintenant: func() time.Time { return maintenant }}

	var coupe atomic.Bool
	var composes int64
	cible := a.hote()
	tr := p.Client.Transport.(*http.Transport)
	tr.Proxy = nil
	// Chaque requête compose : une connexion gardée ouverte depuis le
	// remplissage répondrait à la place de l'amont coupé.
	tr.DisableKeepAlives = true
	tr.DialContext = func(ctx context.Context, reseau, _ string) (net.Conn, error) {
		if coupe.Load() {
			atomic.AddInt64(&composes, 1)
			return nil, refusEtablissement()
		}
		return (&net.Dialer{}).DialContext(ctx, reseau, cible)
	}
	const hote = "miroir.example.invalid"

	if w := joue(t, p, "GET", hote, "/depot/etat"); w.Code != http.StatusOK {
		t.Fatalf("remplissage : code %d", w.Code)
	}
	coupe.Store(true)
	for i := 1; i <= 3; i++ {
		w := joue(t, p, "GET", hote, "/depot/etat")
		if w.Code != http.StatusOK || w.Body.String() != "index courant" {
			t.Fatalf("hors ligne %d : %d %q", i, w.Code, w.Body.String())
		}
	}
	if n := atomic.LoadInt64(&composes); n != 1 {
		t.Errorf("%d tentatives d'établissement pour trois requêtes, attendu 1", n)
	}

	// Sans copie, rien ne remplace l'amont : la requête compose malgré la
	// mémoire, et le 504 dit la vraie cause, pas un amont non retenté.
	w := joue(t, p, "GET", hote, "/jamais-vu")
	if w.Code != http.StatusGatewayTimeout {
		t.Fatalf("code %d, attendu 504", w.Code)
	}
	if strings.Contains(w.Body.String(), "aucune connexion") {
		t.Errorf("le message dit l'amont non retenté alors qu'il l'a été :\n%s",
			w.Body.String())
	}
	if n := atomic.LoadInt64(&composes); n != 2 {
		t.Errorf("%d tentatives, attendu 2 : une requête sans repli n'a pas"+
			" composé", n)
	}

	// La fenêtre passée, l'amont a de nouveau sa chance, copie ou non.
	maintenant = maintenant.Add(FenetreMuetParDefaut)
	joue(t, p, "GET", hote, "/depot/etat")
	if n := atomic.LoadInt64(&composes); n != 3 {
		t.Errorf("%d tentatives après la fenêtre, attendu 3", n)
	}
}

// La mémoire ne fait sauter l'amont qu'aux requêtes qui ont un repli. Ici
// l'amont répond pendant tout le test : seul l'hôte est retenu comme muet,
// ce que laisse un établissement manqué une fois.
//
// Avec un repli — corps gardé, copie du client, statut gardé —, la réponse
// sort sans composer. Sans repli — rien en réserve, méthode d'écriture —, la
// requête compose, et l'amont la sert : un aléa passager ne devient pas un
// « 504 » pour tout ce que le magasin n'a pas.
func TestUnAmontConnuMuetNEstSauteQuAvecUnRepli(t *testing.T) {
	a := nouvelAmontScripte(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/refus" {
			refuser(http.StatusNotFound)(w, r)
			return
		}
		servir("réponse de l'amont")(w, r)
	})
	p := proxyDeTest(t)
	p.Muets = NouvelleJoignabilite()
	hote := a.hote()
	for _, c := range []string{"/depot/etat", "/refus"} {
		joue(t, p, "GET", hote, c)
	}
	muet := func() { p.Muets.Echec(hote, refusEtablissement()) }

	muet()
	avant := a.appels()
	for _, c := range []struct {
		chemin, issue string
		code          int
		entetes       []string
	}{
		{"/depot/etat", OutcomeStale, http.StatusOK, nil},
		{"/refus", OutcomeStaleStatus, http.StatusNotFound, nil},
		{"/autre/etat", OutcomeKeep, http.StatusNotModified,
			[]string{"If-None-Match", `"v1"`}},
	} {
		w := joue(t, p, "GET", hote, c.chemin, c.entetes...)
		if w.Code != c.code || w.Header().Get("X-ERPLibre-Cache") != c.issue {
			t.Errorf("%s : %d « %s », attendu %d « %s »", c.chemin, w.Code,
				w.Header().Get("X-ERPLibre-Cache"), c.code, c.issue)
		}
	}
	if n := a.appels() - avant; n != 0 {
		t.Errorf("%d requête(s) vers un amont connu muet, alors qu'un repli"+
			" existait", n)
	}

	w := joue(t, p, "GET", hote, "/jamais-vu")
	if w.Code != http.StatusOK || w.Body.String() != "réponse de l'amont" {
		t.Errorf("sans repli : %d %q, attendu la réponse de l'amont",
			w.Code, w.Body.String())
	}
	if p.Muets.ConnuMuet(hote) {
		t.Error("la réponse de l'amont n'a pas effacé l'hôte de la mémoire")
	}

	muet()
	avant = a.appels()
	if w := joue(t, p, "POST", hote, "/api/envoi"); w.Code != http.StatusOK {
		t.Errorf("POST : code %d, attendu la réponse de l'amont", w.Code)
	}
	if n := a.appels() - avant; n != 1 {
		t.Errorf("POST : %d requête(s) à l'amont, attendu 1", n)
	}
}

// Un serveur lent n'est pas un serveur mort : l'attente des en-têtes échoue,
// mais la requête suivante le retente.
func TestUnServeurLentNEstPasTenuPourMuet(t *testing.T) {
	var recues int64
	libere := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&recues, 1)
			<-libere
		}))
	t.Cleanup(srv.Close)
	t.Cleanup(func() { close(libere) })

	p := proxyDeTest(t)
	p.Muets = NouvelleJoignabilite()
	p.Client.Transport.(*http.Transport).ResponseHeaderTimeout = 200 * time.Millisecond
	u, _ := url.Parse(srv.URL)

	for i := 0; i < 2; i++ {
		joue(t, p, "GET", u.Host, "/api/lente")
	}
	if n := atomic.LoadInt64(&recues); n != 2 {
		t.Errorf("le serveur a reçu %d requêtes, attendu 2 : un serveur lent"+
			" a été tenu pour muet", n)
	}
}

// amontGitCompte monte un amont git qui compte ses requêtes, et qu'on peut
// mettre en panne en cours de test.
func amontGitCompte(t *testing.T) (string, *int64, *atomic.Bool) {
	t.Helper()
	depot, _, n, panne := amontGitEnPanne(t)
	return depot, n, panne
}

// amontGitEnPanne est amontGitCompte qui rend aussi le chemin du dépôt nu
// servi, pour y pousser des commits en cours de test.
func amontGitEnPanne(t *testing.T) (string, string, *int64, *atomic.Bool) {
	t.Helper()
	if TrouverBackend() == "" {
		t.Skip("git-http-backend absent de cette machine")
	}
	nu := depotDEssai(t)
	racine := filepath.Dir(nu)
	h := &cgi.Handler{
		Path: TrouverBackend(),
		Dir:  racine,
		Env: []string{
			"GIT_PROJECT_ROOT=" + racine,
			"GIT_HTTP_EXPORT_ALL=1",
		},
		InheritEnv: []string{"PATH"},
	}
	var n int64
	var panne atomic.Bool
	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&n, 1)
			if panne.Load() {
				http.Error(w, "panne", http.StatusInternalServerError)
				return
			}
			h.ServeHTTP(w, r)
		}))
	t.Cleanup(srv.Close)
	return srv.URL + "/" + filepath.Base(nu), nu, &n, &panne
}

// Un amont connu muet ne fait pas payer au miroir le délai d'une mise à jour
// vouée à l'échec : le miroir existant sert tel quel.
func TestUnAmontConnuMuetNeRafraichitPasLeMiroir(t *testing.T) {
	depot, appels, _ := amontGitCompte(t)
	g := &GitMirror{
		Dir: t.TempDir(), Delai: 30 * time.Second, Muets: NouvelleJoignabilite(),
	}
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	avant := atomic.LoadInt64(appels)

	g.Muets.Echec(hoteDe(t, depot), refusEtablissement())
	g.Frais = 0
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir existant n'est pas servi")
	}
	if n := atomic.LoadInt64(appels); n != avant {
		t.Errorf("%d requête(s) vers un amont connu muet", n-avant)
	}
}

// Une sonde refusée retient l'hôte et sert le miroir sans le rafraîchir ; le
// dépôt suivant du même hôte ne sonde même plus.
func TestUneSondeRefuseeRetientLHoteEtSertLeMiroir(t *testing.T) {
	depot, appels, _ := amontGitCompte(t)
	g := &GitMirror{
		Dir: t.TempDir(), Delai: 30 * time.Second, Muets: NouvelleJoignabilite(),
	}
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	avant := atomic.LoadInt64(appels)

	var sondes int64
	g.Sonder = func(context.Context, string) error {
		atomic.AddInt64(&sondes, 1)
		return refusEtablissement()
	}
	g.Frais = 0
	for i := 0; i < 2; i++ {
		if _, pret := g.Assurer(context.Background(), depot); !pret {
			t.Fatal("le miroir existant n'est pas servi")
		}
	}
	if n := atomic.LoadInt64(appels); n != avant {
		t.Errorf("%d requête(s) vers un amont qui refuse la sonde", n-avant)
	}
	if n := atomic.LoadInt64(&sondes); n != 1 {
		t.Errorf("%d sondes, attendu 1 : l'échec n'a pas été retenu", n)
	}
	if !g.Muets.ConnuMuet(hoteDe(t, depot)) {
		t.Error("l'hôte n'est pas retenu comme muet")
	}
}

// sansMandataire : aucune URL ne sort par un mandataire, quel que soit
// l'environnement du test.
func sansMandataire(*http.Request) (*url.URL, error) { return nil, nil }

// miroirCree tient un miroir du dépôt dans un répertoire neuf et le rend.
func miroirCree(t *testing.T, depot string) string {
	t.Helper()
	dir := t.TempDir()
	creation := &GitMirror{Dir: dir, Delai: 30 * time.Second}
	if _, pret := creation.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	return dir
}

// Une mise à jour manquée sur un amont qui accepte la connexion — un 5xx, une
// poignée de main coupée — n'est pas notée : la requête suivante retente, et
// l'hôte n'est pas tenu pour muet.
func TestUnRafraichissementManqueSurUnAmontJoignableEstRetente(t *testing.T) {
	depot, appels, panne := amontGitCompte(t)
	g := &GitMirror{
		Dir: miroirCree(t, depot), Delai: 30 * time.Second, Frais: time.Minute,
		Muets:  NouvelleJoignabilite(),
		Sonder: func(context.Context, string) error { return nil },
	}
	panne.Store(true)
	g.Assurer(context.Background(), depot)
	avant := atomic.LoadInt64(appels)
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir existant n'est pas servi")
	}
	if n := atomic.LoadInt64(appels); n == avant {
		t.Error("la mise à jour manquée sur un amont joignable n'est pas" +
			" retentée : elle a été notée comme un rafraîchissement")
	}
	if g.Muets.ConnuMuet(hoteDe(t, depot)) {
		t.Error("un 500 a fait tenir l'hôte pour muet")
	}
}

// Une mise à jour manquée sur un amont qui refuse désormais la connexion est
// notée, et l'hôte retenu : pendant « Frais », le dépôt ne la retente pas.
func TestUnRafraichissementManqueSurUnAmontQuiRefuseEstNote(t *testing.T) {
	depot, appels, panne := amontGitCompte(t)
	var sondes int64
	g := &GitMirror{
		Dir: miroirCree(t, depot), Delai: 30 * time.Second, Frais: time.Minute,
		Muets: NouvelleJoignabilite(),
		// La sonde d'avant la mise à jour passe ; celle d'après trouve
		// l'amont tombé entre les deux.
		Sonder: func(context.Context, string) error {
			if atomic.AddInt64(&sondes, 1) == 1 {
				return nil
			}
			return refusEtablissement()
		},
	}
	panne.Store(true)
	chemin, _ := g.Assurer(context.Background(), depot)
	if n := atomic.LoadInt64(&sondes); n != 2 {
		t.Errorf("%d sonde(s), attendu 2 : l'échec de la mise à jour n'a pas"+
			" été sondé", n)
	}
	if !g.recent(chemin) {
		t.Error("la mise à jour manquée sur un amont qui refuse n'est pas notée")
	}
	if !g.Muets.ConnuMuet(hoteDe(t, depot)) {
		t.Error("l'hôte qui refuse n'est pas retenu comme muet")
	}
	avant := atomic.LoadInt64(appels)
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir existant n'est pas servi")
	}
	if n := atomic.LoadInt64(appels); n != avant {
		t.Errorf("%d requête(s) dans la fraîcheur d'un amont qui refuse", n-avant)
	}
}

// pousserUnCommit ajoute un commit au dépôt nu que sert l'amont et rend son
// empreinte. Le dépôt de travail est celui que depotDEssai laisse à côté.
func pousserUnCommit(t *testing.T, nu string) string {
	t.Helper()
	travail := filepath.Join(filepath.Dir(nu), "travail")
	lancer := func(args ...string) string {
		t.Helper()
		c := exec.Command("git", args...)
		c.Dir = travail
		c.Env = append(os.Environ(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@e",
			"GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@e")
		out, err := c.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v : %v : %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	if err := os.WriteFile(
		filepath.Join(travail, "g.txt"), []byte("suite"), 0o644,
	); err != nil {
		t.Fatal(err)
	}
	lancer("add", "g.txt")
	lancer("commit", "-qm", "second")
	lancer("push", "-q", nu, "HEAD:refs/heads/main")
	return lancer("rev-parse", "HEAD")
}

// Un 500 de la forge ne fige pas le miroir : l'amont publie un commit juste
// après, et la requête suivante le voit, sans attendre la fin de « Frais ».
// La sonde est la vraie, vers l'amont local qui accepte la connexion.
func TestUnRafraichissementEn500NeFigePasLeMiroir(t *testing.T) {
	depot, nu, _, panne := amontGitEnPanne(t)
	g := &GitMirror{
		Dir: miroirCree(t, depot), Delai: 30 * time.Second, Frais: time.Minute,
		Muets: NouvelleJoignabilite(), Mandataire: sansMandataire,
	}
	panne.Store(true)
	if _, pret := g.Assurer(context.Background(), depot); !pret {
		t.Fatal("le miroir existant n'est pas servi pendant la panne")
	}
	panne.Store(false)
	attendu := pousserUnCommit(t, nu)

	chemin, pret := g.Assurer(context.Background(), depot)
	if !pret {
		t.Fatal("le miroir n'est pas servi")
	}
	out, err := exec.Command(
		"git", "--git-dir", chemin, "rev-parse", "refs/heads/main",
	).CombinedOutput()
	if err != nil {
		t.Fatalf("rev-parse : %v : %s", err, out)
	}
	if got := strings.TrimSpace(string(out)); got != attendu {
		t.Errorf("le miroir sert %s, attendu %s : il est resté figé après"+
			" le 500", got, attendu)
	}
}

// Quand un mandataire porte l'URL du dépôt, aucune sonde directe : git passe
// par lui, et la connexion directe, refusée sur un hôte dont c'est la seule
// sortie, figerait le miroir pour toujours.
func TestUnMandataireDispenseDeLaSonde(t *testing.T) {
	var sondes int64
	g := &GitMirror{
		Sonder: func(context.Context, string) error {
			atomic.AddInt64(&sondes, 1)
			return refusEtablissement()
		},
		Mandataire: func(*http.Request) (*url.URL, error) {
			return url.Parse("http://mandataire.example:3128")
		},
	}
	const depot = "https://forge.example/o/d.git"
	ctx := context.Background()
	if !g.amontJoignable(ctx, depot) || g.sondeRefusee(ctx, depot) {
		t.Error("l'amont derrière un mandataire est tenu pour injoignable")
	}
	if n := atomic.LoadInt64(&sondes); n != 0 {
		t.Errorf("%d sonde(s) directe(s) malgré le mandataire", n)
	}

	g.Mandataire = sansMandataire
	if g.amontJoignable(ctx, depot) {
		t.Error("sans mandataire, une sonde refusée laisse l'amont joignable")
	}
	if n := atomic.LoadInt64(&sondes); n != 1 {
		t.Errorf("%d sonde(s) sans mandataire, attendu 1", n)
	}
}

// Une sonde manquée se dit au journal UNE fois par panne et par hôte : un
// miroir servi sans rafraîchissement doit se voir, sans une ligne par dépôt.
// La réponse de l'hôte clôt la panne ; la suivante se dit de nouveau.
func TestUneSondeManqueeSeDitUneFoisParPanne(t *testing.T) {
	var journal bytes.Buffer
	avant := log.Writer()
	log.SetOutput(&journal)
	t.Cleanup(func() { log.SetOutput(avant) })

	var enPanne atomic.Bool
	enPanne.Store(true)
	g := &GitMirror{
		Mandataire: sansMandataire,
		Sonder: func(context.Context, string) error {
			if enPanne.Load() {
				return refusEtablissement()
			}
			return nil
		},
	}
	const depot = "https://forge.example/o/d.git"
	const adresse = "forge.example:443"
	ctx := context.Background()
	for i := 0; i < 3; i++ {
		g.amontJoignable(ctx, depot)
	}
	if n := strings.Count(journal.String(), adresse); n != 1 {
		t.Errorf("%d ligne(s) pour trois sondes manquées, attendu 1 :\n%s",
			n, journal.String())
	}
	enPanne.Store(false)
	g.amontJoignable(ctx, depot)
	enPanne.Store(true)
	g.amontJoignable(ctx, depot)
	if n := strings.Count(journal.String(), adresse); n != 2 {
		t.Errorf("%d ligne(s) après une seconde panne, attendu 2", n)
	}
}
