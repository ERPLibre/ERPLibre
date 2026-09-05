// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/cgi"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Pourquoi un MIROIR et non un cache pour git.
//
// Le protocole « smart HTTP » de git est une NÉGOCIATION : le client annonce
// ce qu'il détient, le serveur calcule et envoie ce qui manque. Deux clients
// dans des états différents reçoivent des octets différents pour la même URL,
// si bien qu'aucune réponse ne se réutilise — c'est pour cela que le cache ne
// garde rien de ces échanges.
//
// Or c'est là que part l'essentiel du réseau d'une installation ERPLibre : le
// dépôt tire plus de trois cents dépôts, et le trafic git y pèse plusieurs
// fois celui des paquets. Un cache qui l'ignore laisse donc le gros du travail
// sortir deux fois.
//
// La réponse n'est pas de garder des réponses mais de tenir des DÉPÔTS. Un
// miroir nu par dépôt amont, rafraîchi quand l'amont répond, et le protocole
// servi depuis ce miroir par « git http-backend » — le programme de git
// lui-même, plutôt qu'une réimplémentation qui divergerait à la première
// version du protocole.
//
// Ce que cela coûte, et qu'il faut savoir : un miroir est COMPLET. Trois cents
// dépôts Odoo pèsent plusieurs gigaoctets sur le disque de l'orchestrateur, et
// rien ne les efface, comme pour le reste de ce cache.

// GitMirror tient les dépôts nus et les sert.
type GitMirror struct {
	// Dir est la racine des miroirs. Vide, le miroir est éteint et git
	// retombe sur le simple relais vers l'amont.
	Dir string
	// Frais borne le rafraîchissement : deux requêtes rapprochées sur le même
	// dépôt ne déclenchent qu'une récupération. « repo sync » interroge chaque
	// dépôt plusieurs fois de suite, et sans cette borne chacune paierait un
	// aller-retour vers l'amont.
	Frais time.Duration
	// Backend est le chemin de « git-http-backend ». Vide, il est cherché aux
	// endroits usuels.
	Backend string
	// Delai borne un clonage ou une récupération. Un dépôt Odoo complet
	// descend en minutes, pas en secondes.
	Delai time.Duration

	mu      sync.Mutex
	verrous map[string]*sync.Mutex
	vus     map[string]time.Time
}

// backendsUsuels : les chemins où les distributions posent git-http-backend.
// Aucune ne les met au même endroit, et il n'est pas dans le PATH.
var backendsUsuels = []string{
	"/usr/lib/git-core/git-http-backend",
	"/usr/libexec/git-core/git-http-backend",
	"/usr/local/libexec/git-core/git-http-backend",
}

// TrouverBackend rend le chemin de git-http-backend, ou "" s'il manque.
func TrouverBackend() string {
	for _, c := range backendsUsuels {
		if st, err := os.Stat(c); err == nil && !st.IsDir() {
			return c
		}
	}
	return ""
}

// Actif dit si le miroir peut servir. Un répertoire sans le programme de git
// ne sert à rien : mieux vaut le relais vers l'amont, qui fonctionne.
func (g *GitMirror) Actif() bool {
	return g != nil && g.Dir != "" && g.backend() != ""
}

func (g *GitMirror) backend() string {
	if g.Backend == "" {
		return TrouverBackend()
	}
	// Le chemin imposé est vérifié comme les autres : un miroir qui se dirait
	// actif avec un programme absent servirait des 500 à chaque dépôt, là où
	// le relais vers l'amont, lui, fonctionne.
	if st, err := os.Stat(g.Backend); err == nil && !st.IsDir() {
		return g.Backend
	}
	return ""
}

// DepotDeURL découpe une URL de négociation en (URL du dépôt amont, reste).
//
// « https://h/o/d.git/info/refs?service=… » rend « https://h/o/d.git » et
// « /info/refs ». Rend faux quand l'URL n'est pas une négociation : le
// découpage n'aurait alors aucun sens.
func DepotDeURL(u *url.URL) (string, string, bool) {
	if u == nil {
		return "", "", false
	}
	for _, s := range gitSmartPaths {
		if strings.HasSuffix(u.Path, s) {
			base := strings.TrimSuffix(u.Path, s)
			if base == "" || base == "/" {
				return "", "", false
			}
			amont := *u
			amont.Path = base
			amont.RawQuery = ""
			return amont.String(), s, true
		}
	}
	return "", "", false
}

// CheminMiroir rend le répertoire du miroir d'un dépôt.
//
// L'hôte fait partie du chemin : deux forges peuvent servir « /odoo/odoo », et
// les confondre donnerait à l'une le contenu de l'autre. Le « .git » final est
// posé une seule fois, l'amont l'écrivant tantôt et tantôt non.
func (g *GitMirror) CheminMiroir(depot string) (string, error) {
	u, err := url.Parse(depot)
	if err != nil || u.Host == "" {
		return "", fmt.Errorf("dépôt illisible %q", depot)
	}
	chemin := strings.Trim(u.Path, "/")
	chemin = strings.TrimSuffix(chemin, ".git")
	if chemin == "" {
		return "", fmt.Errorf("dépôt sans chemin %q", depot)
	}
	// Un « .. » dans le chemin ferait écrire hors de la racine.
	for _, seg := range strings.Split(chemin, "/") {
		if seg == "." || seg == ".." || seg == "" {
			return "", fmt.Errorf("chemin de dépôt refusé %q", depot)
		}
	}
	return filepath.Join(g.Dir, u.Host, chemin+".git"), nil
}

func (g *GitMirror) verrou(cle string) *sync.Mutex {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.verrous == nil {
		g.verrous = map[string]*sync.Mutex{}
	}
	if _, ok := g.verrous[cle]; !ok {
		g.verrous[cle] = &sync.Mutex{}
	}
	return g.verrous[cle]
}

// Assurer rend le miroir prêt et dit s'il est utilisable.
//
// Trois issues, et la troisième est celle qui rend le hors-ligne possible :
// le miroir est créé, le miroir est rafraîchi, ou l'amont est muet mais un
// miroir existe déjà — il sert alors tel quel. Un amont muet SANS miroir rend
// faux, et l'appelant retombe sur le relais, qui donnera au client la vraie
// erreur du réseau plutôt qu'une erreur inventée ici.
func (g *GitMirror) Assurer(ctx context.Context, depot string) (string, bool) {
	chemin, err := g.CheminMiroir(depot)
	if err != nil {
		return "", false
	}
	v := g.verrou(chemin)
	v.Lock()
	defer v.Unlock()

	_, statErr := os.Stat(filepath.Join(chemin, "HEAD"))
	existe := statErr == nil

	if existe && g.recent(chemin) {
		return chemin, true
	}
	if !existe {
		if err := os.MkdirAll(filepath.Dir(chemin), 0o755); err != nil {
			return "", false
		}
		if err := g.git(ctx, "", "clone", "--mirror", depot, chemin); err != nil {
			// Un clonage à moitié fait laisserait un répertoire que la
			// prochaine requête prendrait pour un miroir valide.
			os.RemoveAll(chemin)
			return "", false
		}
		g.noter(chemin)
		return chemin, true
	}
	if err := g.git(ctx, chemin, "remote", "update", "--prune"); err != nil {
		// L'amont est muet : le miroir d'hier vaut mieux que rien, et c'est
		// exactement ce qui permet de déployer sans réseau.
		return chemin, true
	}
	g.noter(chemin)
	return chemin, true
}

func (g *GitMirror) recent(chemin string) bool {
	if g.Frais <= 0 {
		return false
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	t, ok := g.vus[chemin]
	return ok && time.Since(t) < g.Frais
}

func (g *GitMirror) noter(chemin string) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.vus == nil {
		g.vus = map[string]time.Time{}
	}
	g.vus[chemin] = time.Now()
}

func (g *GitMirror) git(ctx context.Context, dir string, args ...string) error {
	delai := g.Delai
	if delai <= 0 {
		delai = 30 * time.Minute
	}
	ctx, annule := context.WithTimeout(ctx, delai)
	defer annule()
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	// Aucune invite : un dépôt privé doit ÉCHOUER et retomber sur le relais,
	// et non bloquer le service en attendant un mot de passe que personne ne
	// tapera jamais.
	cmd.Env = append(os.Environ(),
		"GIT_TERMINAL_PROMPT=0",
		"GIT_ASKPASS=/bin/true",
		"GCM_INTERACTIVE=never",
	)
	sortie, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("git %s : %v : %s",
			strings.Join(args, " "), err, court(string(sortie)))
	}
	return nil
}

func court(s string) string {
	s = strings.TrimSpace(s)
	if len(s) > 300 {
		return s[:300] + "…"
	}
	return s
}

// Servir répond depuis le miroir, par le programme de git lui-même.
//
// « git http-backend » est une passerelle CGI : il attend le chemin du dépôt
// dans PATH_INFO, la racine dans GIT_PROJECT_ROOT, et rend le protocole exact,
// version 0 comme version 2. Le réimplémenter reviendrait à le suivre à chaque
// version.
func (g *GitMirror) Servir(
	w http.ResponseWriter, r *http.Request, chemin, reste string,
) {
	racine := filepath.Dir(chemin)
	h := &cgi.Handler{
		Path: g.backend(),
		Dir:  racine,
		Env: []string{
			"GIT_PROJECT_ROOT=" + racine,
			// Le miroir n'a pas de « git-daemon-export-ok », et n'en aura
			// pas : il ne sert que le pont des VM de cet hôte.
			"GIT_HTTP_EXPORT_ALL=1",
		},
		InheritEnv: []string{"PATH"},
	}
	// La passerelle lit le chemin du dépôt dans l'URL qu'on lui présente : ce
	// n'est pas celle que la VM a demandée, mais celle du miroir local.
	r2 := r.Clone(r.Context())
	r2.URL = &url.URL{
		Path:     "/" + filepath.Base(chemin) + reste,
		RawQuery: r.URL.RawQuery,
	}
	r2.RequestURI = ""
	h.ServeHTTP(w, r2)
}
