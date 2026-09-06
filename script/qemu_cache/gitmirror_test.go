// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"net"
	"net/http"
	"net/http/cgi"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDepotDeURL(t *testing.T) {
	cas := []struct {
		brut, depot, reste string
	}{
		{"https://h/o/d.git/info/refs?service=git-upload-pack",
			"https://h/o/d.git", "/info/refs"},
		{"https://h/o/d/info/refs?service=git-upload-pack",
			"https://h/o/d", "/info/refs"},
		{"https://h/o/d.git/git-upload-pack", "https://h/o/d.git",
			"/git-upload-pack"},
	}
	for _, c := range cas {
		u, _ := url.Parse(c.brut)
		depot, reste, ok := DepotDeURL(u)
		if !ok || depot != c.depot || reste != c.reste {
			t.Errorf("%s → (%q, %q, %v)", c.brut, depot, reste, ok)
		}
	}
}

func TestDepotDeURLRefuse(t *testing.T) {
	for _, brut := range []string{
		"https://h/o/d.git/objects/ab/cd",
		"https://h/info/refs",
		"https://h/miroir/core.db",
	} {
		u, _ := url.Parse(brut)
		if _, _, ok := DepotDeURL(u); ok {
			t.Errorf("%s pris pour une négociation", brut)
		}
	}
}

// Le chemin du miroir porte l'HÔTE : deux forges peuvent servir « /odoo/odoo »,
// et les confondre donnerait à l'une le contenu de l'autre.
func TestCheminMiroirSepareLesForges(t *testing.T) {
	g := &GitMirror{Dir: "/var/x"}
	a, err := g.CheminMiroir("https://github.com/odoo/odoo.git")
	if err != nil {
		t.Fatal(err)
	}
	b, _ := g.CheminMiroir("https://autre.example/odoo/odoo.git")
	if a == b {
		t.Error("deux forges partagent un miroir")
	}
	if !strings.HasSuffix(a, ".git") {
		t.Errorf("le miroir n'est pas un dépôt nu : %s", a)
	}
	// « .git » écrit ou non par l'amont donne le même miroir.
	c, _ := g.CheminMiroir("https://github.com/odoo/odoo")
	if a != c {
		t.Errorf("« .git » change le miroir : %s contre %s", a, c)
	}
}

// Un chemin qui remonte écrirait hors de la racine.
func TestCheminMiroirRefuseCeQuiRemonte(t *testing.T) {
	g := &GitMirror{Dir: "/var/x"}
	for _, brut := range []string{
		"https://h/../../etc/passwd",
		"https://h/o/../../..",
		"https://h/",
		"pas une url",
	} {
		if chemin, err := g.CheminMiroir(brut); err == nil {
			t.Errorf("%s accepté et rendu %q", brut, chemin)
		}
	}
}

func TestMiroirEteintQuandRienNestConfigure(t *testing.T) {
	if (&GitMirror{}).Actif() {
		t.Error("un miroir sans répertoire se dit actif")
	}
	// Un répertoire sans le programme de git ne sert à rien : mieux vaut le
	// relais vers l'amont, qui fonctionne.
	g := &GitMirror{Dir: "/var/x", Backend: "/nexiste/pas"}
	if g.Actif() {
		t.Error("un miroir sans git-http-backend se dit actif")
	}
}

// amontGit monte un dépôt nu ET le serveur qui le publie, comme le ferait une
// forge. L'URL rendue est celle qu'un client — ou le miroir — interroge.
func amontGit(t *testing.T) (string, *httptest.Server) {
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
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return srv.URL + "/" + filepath.Base(nu), srv
}

// depotDEssai fabrique un dépôt nu local, servi comme s'il était l'amont.
func depotDEssai(t *testing.T) string {
	t.Helper()
	racine := t.TempDir()
	nu := filepath.Join(racine, "amont.git")
	travail := filepath.Join(racine, "travail")
	lancer := func(dir string, args ...string) {
		t.Helper()
		c := exec.Command("git", args...)
		c.Dir = dir
		c.Env = append(os.Environ(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@e",
			"GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@e")
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("git %v : %v : %s", args, err, out)
		}
	}
	lancer(racine, "init", "-q", "--bare", "--initial-branch=main", nu)
	lancer(racine, "init", "-q", "--initial-branch=main", travail)
	if err := os.WriteFile(
		filepath.Join(travail, "f.txt"), []byte("bonjour"), 0o644,
	); err != nil {
		t.Fatal(err)
	}
	lancer(travail, "add", "f.txt")
	lancer(travail, "commit", "-qm", "premier")
	lancer(travail, "push", "-q", nu, "HEAD:refs/heads/main")
	return nu
}

// L'épreuve qui compte : un client clone à travers le miroir, sans que rien
// dans l'invité soit configuré, et le dépôt arrive complet.
func TestClonerAuTraversDuMiroir(t *testing.T) {
	if TrouverBackend() == "" {
		t.Skip("git-http-backend absent de cette machine")
	}
	amont, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 2 * time.Minute}

	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			u := &url.URL{Path: r.URL.Path, RawQuery: r.URL.RawQuery}
			_, reste, ok := DepotDeURL(u)
			if !ok {
				http.NotFound(w, r)
				return
			}
			// Tout chemin demandé désigne le dépôt qui joue l'amont : ce test
			// mesure le miroir, pas le routage.
			chemin, pret := g.Assurer(r.Context(), amont)
			if !pret {
				http.Error(w, "miroir indisponible", 502)
				return
			}
			g.Servir(w, r, chemin, reste)
		}))
	defer srv.Close()

	for essai := 1; essai <= 2; essai++ {
		dest := filepath.Join(t.TempDir(), "copie")
		c := exec.Command("git", "clone", "-q", srv.URL+"/essai.git", dest)
		c.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
		if out, err := c.CombinedOutput(); err != nil {
			t.Fatalf("clone %d : %v : %s", essai, err, out)
		}
		contenu, err := os.ReadFile(filepath.Join(dest, "f.txt"))
		if err != nil || string(contenu) != "bonjour" {
			t.Fatalf("clone %d : contenu %q, err %v", essai, contenu, err)
		}
	}
}

// Un amont muet mais un miroir déjà là : le miroir sert. C'est ce qui rend un
// déploiement sans réseau possible pour git, ce qu'aucun cache de réponses ne
// peut faire de ce protocole.
func TestUnMiroirExistantSertQuandLAmontEstMuet(t *testing.T) {
	amont, srvAmont := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: time.Minute}
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	// L'amont disparaît : le serveur qui le publiait est fermé, exactement ce
	// que voit une VM quand le réseau tombe.
	srvAmont.Close()
	g.Frais = 0 // forcer une tentative de rafraîchissement
	chemin, pret := g.Assurer(context.Background(), amont)
	if !pret {
		t.Error("le miroir refuse de servir alors qu'il existe")
	}
	if _, err := os.Stat(filepath.Join(chemin, "HEAD")); err != nil {
		t.Errorf("le miroir a été effacé : %v", err)
	}
}

// Un amont muet SANS miroir doit rendre faux : l'appelant retombe alors sur le
// relais, qui donnera au client la vraie erreur du réseau plutôt qu'une erreur
// inventée ici.
func TestAucunMiroirEtAucunAmont(t *testing.T) {
	g := &GitMirror{Dir: t.TempDir(), Delai: 20 * time.Second}
	chemin, pret := g.Assurer(
		context.Background(), "https://127.0.0.1:1/nexiste/pas.git")
	if pret {
		t.Errorf("se dit prêt avec %q", chemin)
	}
	// Aucun DÉPÔT ne doit rester derrière : un clonage à moitié fait serait
	// pris pour un miroir valide à la requête suivante. Un répertoire vide,
	// lui, ne trompe personne.
	filepath.Walk(g.Dir, func(p string, info os.FileInfo, err error) error {
		if err == nil && info != nil && info.Name() == "HEAD" {
			t.Errorf("un miroir incomplet subsiste : %s", p)
		}
		return nil
	})
}

func TestDepotsDuFichier(t *testing.T) {
	f := filepath.Join(t.TempDir(), "liste")
	contenu := strings.Join([]string{
		"# un commentaire",
		"",
		"https://h/a.git",
		"  https://h/b.git  ",
		"https://h/a.git", // le même dépôt figure dans plusieurs manifestes
	}, "\n")
	if err := os.WriteFile(f, []byte(contenu), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := DepotsDuFichier(f)
	if err != nil {
		t.Fatal(err)
	}
	attendu := []string{"https://h/a.git", "https://h/b.git"}
	if len(got) != len(attendu) {
		t.Fatalf("%d dépôts, %d attendus : %v", len(got), len(attendu), got)
	}
	for i := range attendu {
		if got[i] != attendu[i] {
			t.Errorf("dépôt %d : %q, attendu %q", i, got[i], attendu[i])
		}
	}
}

// Un dépôt qui échoue ne doit pas emporter les autres : sur une liste de
// trois cents, il y a toujours un dépôt privé, déplacé ou retiré, et tout
// arrêter pour lui perdrait le travail déjà fait.
func TestUnDepotEnEchecNEmportePasLesAutres(t *testing.T) {
	bon, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 30 * time.Second}
	depots := []string{
		bon,
		"https://127.0.0.1:1/absent.git",
		bon + "-autre",
	}
	reussis, echoues := g.Prefetch(context.Background(), depots, 3, nil)
	if reussis < 1 {
		t.Errorf("%d réussite(s) : le dépôt joignable n'a pas été pris",
			reussis)
	}
	if echoues < 1 {
		t.Error("aucun échec compté alors qu'un dépôt est injoignable")
	}
	if reussis+echoues != len(depots) {
		t.Errorf("%d + %d ne fait pas %d", reussis, echoues, len(depots))
	}
}

// Le pré-remplissage rend le miroir prêt : la machine suivante n'a plus qu'à
// être servie, ce qui est tout l'objet de l'avance.
func TestApresPrefetchLeMiroirEstPret(t *testing.T) {
	amont, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 30 * time.Second}
	if r, e := g.Prefetch(
		context.Background(), []string{amont}, 2, nil,
	); r != 1 || e != 0 {
		t.Fatalf("pré-remplissage : %d réussis, %d échoués", r, e)
	}
	depots, octets := g.Occupation()
	if depots != 1 || octets == 0 {
		t.Errorf("occupation : %d dépôts, %d octets", depots, octets)
	}
}

// Le plancher protège le disque de l'orchestrateur.
//
// Un miroir est COMPLET là où « repo sync » clone en profondeur un : le
// facteur entre les deux est celui de l'historique, et il ne se devine pas.
// Sans plancher, une seule installation qui tire trois cents dépôts peut
// remplir le disque de la machine qui héberge toutes les VM.
func TestLePlancherRefuseUnMiroirDeplus(t *testing.T) {
	amont, _ := amontGit(t)
	g := &GitMirror{
		Dir:   t.TempDir(),
		Delai: 30 * time.Second,
		// Plus que tout disque n'en offre : aucun miroir NEUF ne doit passer.
		PlancherLibre: 1 << 62,
	}
	if chemin, pret := g.Assurer(context.Background(), amont); pret {
		t.Errorf("un miroir a été créé sous le plancher : %s", chemin)
	}
	if depots, _ := g.Occupation(); depots != 0 {
		t.Errorf("%d dépôt(s) créés malgré le plancher", depots)
	}
}

// Un miroir DÉJÀ tenu continue d'être servi : une mise à jour ne coûte que ce
// qui a changé, et le refuser priverait de tout ce qui est déjà là.
func TestLePlancherNEmpechePasDeServirLexistant(t *testing.T) {
	amont, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 30 * time.Second}
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	g.PlancherLibre = 1 << 62
	g.Frais = 0
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Error("un miroir existant est refusé à cause du plancher")
	}
}

// Ce que le miroir sert doit être COMPTÉ.
//
// La passerelle CGI écrit directement dans la réponse : le journal notait zéro
// octet pour tout ce que le miroir servait, et c'est le chemin qui porte
// l'essentiel du trafic d'une installation. Un outil dont le journal EST la
// mesure ne peut pas avoir un chemin muet.
func TestCeQueLeMiroirSertEstCompte(t *testing.T) {
	amont, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 30 * time.Second}
	chemin, pret := g.Assurer(context.Background(), amont)
	if !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}

	var pese int64
	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			u := &url.URL{Path: r.URL.Path, RawQuery: r.URL.RawQuery}
			_, reste, ok := DepotDeURL(u)
			if !ok {
				http.NotFound(w, r)
				return
			}
			pese += g.Servir(w, r, chemin, reste)
		}))
	defer srv.Close()

	dest := filepath.Join(t.TempDir(), "copie")
	c := exec.Command("git", "clone", "-q", srv.URL+"/essai.git", dest)
	c.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("clone : %v : %s", err, out)
	}
	if pese <= 0 {
		t.Error("le miroir a servi un clone entier et le journal dirait zéro")
	}
}

// La liste est triée par TAILLE : c'est ce qu'on cherche quand on surveille
// la place à la main, et trois dépôts font les trois quarts du total.
func TestLesDepotsSontTriesParTaille(t *testing.T) {
	g := &GitMirror{Dir: t.TempDir()}
	for nom, poids := range map[string]int{
		"h/petit.git": 10, "h/gros.git": 5000, "h/moyen.git": 500,
	} {
		d := filepath.Join(g.Dir, nom)
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(
			filepath.Join(d, "HEAD"), make([]byte, poids), 0o644,
		); err != nil {
			t.Fatal(err)
		}
	}
	depots := g.Depots()
	if len(depots) != 3 {
		t.Fatalf("%d dépôts vus", len(depots))
	}
	for i, attendu := range []string{"h/gros", "h/moyen", "h/petit"} {
		if depots[i].Nom != attendu {
			t.Errorf("rang %d : %q, attendu %q", i, depots[i].Nom, attendu)
		}
	}
	if depots[0].Octets <= depots[2].Octets {
		t.Error("les tailles ne sont pas mesurées")
	}
}

// Effacer un miroir est sans danger : il se refait au prochain besoin. Mais
// l'effacement doit rester DANS les miroirs — un appel mal formé ne doit pas
// pouvoir emporter autre chose.
func TestRetirerRefuseCeQuiEstDehors(t *testing.T) {
	g := &GitMirror{Dir: t.TempDir()}
	dehors := filepath.Join(t.TempDir(), "ailleurs.git")
	if err := os.MkdirAll(dehors, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, cible := range []string{dehors, "/etc", g.Dir, g.Dir + "/x"} {
		if err := g.Retirer(cible); err == nil {
			t.Errorf("%s a été accepté", cible)
		}
	}
	if _, err := os.Stat(dehors); err != nil {
		t.Errorf("un répertoire hors des miroirs a été effacé : %v", err)
	}
}

func TestRetirerEffaceLeMiroir(t *testing.T) {
	amont, _ := amontGit(t)
	g := &GitMirror{Dir: t.TempDir(), Delai: 30 * time.Second}
	chemin, pret := g.Assurer(context.Background(), amont)
	if !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	if err := g.Retirer(chemin); err != nil {
		t.Fatalf("effacement : %v", err)
	}
	if depots, _ := g.Occupation(); depots != 0 {
		t.Errorf("%d dépôt(s) subsistent", depots)
	}
	// Et il se refait : c'est ce qui rend l'effacement sans danger.
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Error("le miroir ne se refait pas après effacement")
	}
}

// Un miroir qui existe est déjà servable : quand l'amont ne répond pas, il
// doit sortir TOUT DE SUITE, pas au terme du délai d'un clonage.
//
// Sans ce délai propre, un amont coupé faisait attendre chaque dépôt jusqu'à
// son terme : pour les trois cents dépôts d'une installation, des heures pour
// un déploiement que le disque pouvait servir en entier.
func TestUnRafraichissementNattendPasCommeUnClonage(t *testing.T) {
	amont, srv := amontGit(t)
	g := &GitMirror{
		Dir:      t.TempDir(),
		Delai:    30 * time.Minute,
		DelaiMaj: 2 * time.Second,
	}
	if _, pret := g.Assurer(context.Background(), amont); !pret {
		t.Fatal("le miroir n'a pas pu être créé")
	}
	// L'amont devient MUET : il accepte la connexion et ne répond jamais,
	// exactement ce que fait un paquet jeté sans être refusé.
	srv.Close()
	muet, err := net.Listen("tcp", hoteDe(t, amont))
	if err != nil {
		t.Skipf("le port de l'amont n'a pas pu être repris : %v", err)
	}
	defer muet.Close()
	go func() {
		for {
			c, err := muet.Accept()
			if err != nil {
				return
			}
			_ = c // accepté, jamais répondu
		}
	}()

	g.Frais = 0
	debut := time.Now()
	chemin, pret := g.Assurer(context.Background(), amont)
	ecoule := time.Since(debut)
	if !pret || chemin == "" {
		t.Fatal("le miroir existant n'a pas été servi")
	}
	if ecoule > 20*time.Second {
		t.Errorf("le rafraîchissement a duré %v : le délai du clonage a"+
			" été appliqué", ecoule)
	}
}

func hoteDe(t *testing.T, brut string) string {
	t.Helper()
	u, err := url.Parse(brut)
	if err != nil {
		t.Fatal(err)
	}
	return u.Host
}
