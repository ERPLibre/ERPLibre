// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"net/http/cgi"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
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
	// Delai borne un CLONAGE. Un dépôt Odoo complet descend en minutes, pas
	// en secondes, et l'abandonner à mi-chemin ne laisse rien d'utilisable.
	Delai time.Duration
	// DelaiMaj borne un RAFRAÎCHISSEMENT, et il est court à dessein.
	//
	// Un miroir qui existe est déjà servable : si l'amont ne répond pas, la
	// bonne réponse est de servir ce qu'on a, tout de suite. Avec le délai du
	// clonage, un amont coupé ferait attendre chaque dépôt jusqu'à son terme —
	// pour les trois cents dépôts d'une installation, des heures d'attente
	// pour un déploiement qui aurait pu être servi en entier depuis le disque.
	DelaiMaj time.Duration
	// PlancherLibre est la place qu'on refuse d'entamer. En dessous, aucun
	// NOUVEAU miroir n'est créé et la requête repart vers l'amont : le cache
	// perd son avance, il ne remplit pas le disque de l'orchestrateur.
	//
	// Un miroir est complet là où « repo sync » clone en profondeur un : le
	// facteur entre les deux est celui de l'historique, et il ne se devine
	// pas. Les miroirs DÉJÀ tenus continuent d'être rafraîchis et servis —
	// une mise à jour ne coûte que ce qui a changé.
	PlancherLibre int64

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
		if !g.placeSuffisante() {
			log.Printf(
				"miroir refusé pour %s : moins de %s libres sur le disque",
				depot, HumanBytes(g.PlancherLibre))
			return "", false
		}
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
	if err := g.gitBorne(
		ctx, g.delaiMaj(), chemin, "remote", "update", "--prune",
	); err != nil {
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

// DelaiMajParDefaut : de quoi laisser un amont sain répondre, pas de quoi
// attendre un amont absent.
const DelaiMajParDefaut = 45 * time.Second

func (g *GitMirror) delaiMaj() time.Duration {
	if g.DelaiMaj > 0 {
		return g.DelaiMaj
	}
	return DelaiMajParDefaut
}

func (g *GitMirror) git(ctx context.Context, dir string, args ...string) error {
	delai := g.Delai
	if delai <= 0 {
		delai = 30 * time.Minute
	}
	return g.gitBorne(ctx, delai, dir, args...)
}

func (g *GitMirror) gitBorne(
	ctx context.Context, delai time.Duration, dir string, args ...string,
) error {
	ctx, annule := context.WithTimeout(ctx, delai)
	defer annule()
	cmd := exec.CommandContext(ctx, "git", args...)
	cmd.Dir = dir
	// Le délai tue « git », mais git délègue le réseau à un auxiliaire —
	// « git-remote-https » — qui SURVIT et garde le tube ouvert. Sans ce
	// second délai, la lecture de la sortie attend cet auxiliaire, donc pour
	// toujours quand l'amont accepte la connexion et ne répond jamais : le
	// délai qu'on vient de poser ne borne alors plus rien.
	cmd.WaitDelay = 5 * time.Second
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
// compteur retient ce qu'une réponse a réellement pesé.
//
// La passerelle CGI écrit directement dans la réponse : sans ce compteur, le
// journal note zéro octet pour tout ce que le miroir sert. Un outil dont le
// journal EST la mesure ne peut pas avoir un chemin qui ne compte pas — c'est
// justement celui qui porte l'essentiel du trafic d'une installation.
type compteur struct {
	http.ResponseWriter
	n int64
}

func (c *compteur) Write(p []byte) (int, error) {
	n, err := c.ResponseWriter.Write(p)
	c.n += int64(n)
	return n, err
}

// Servir répond depuis le miroir et rend ce que la réponse a pesé.
func (g *GitMirror) Servir(
	w http.ResponseWriter, r *http.Request, chemin, reste string,
) int64 {
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
	c := &compteur{ResponseWriter: w}
	h.ServeHTTP(c, r2)
	return c.n
}

// Occupation rend (nombre de dépôts, octets) du miroir.
//
// Le disque de l'orchestrateur est surveillé À LA MAIN — aucune éviction n'est
// écrite, ici pas plus qu'ailleurs — et un miroir est COMPLET : il pèse ce que
// pèse le dépôt amont, historique compris. Le relevé doit donc le dire, sans
// quoi la place disparaît sans que rien ne l'annonce.
func (g *GitMirror) Occupation() (int, int64) {
	if g == nil || g.Dir == "" {
		return 0, 0
	}
	depots, octets := 0, int64(0)
	filepath.Walk(g.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil {
			return nil
		}
		if info.IsDir() {
			if strings.HasSuffix(p, ".git") {
				depots++
			}
			return nil
		}
		octets += info.Size()
		return nil
	})
	return depots, octets
}

// Prefetch tient en miroir toute une liste de dépôts, d'avance.
//
// À la demande, le miroir se remplit au fil des requêtes : la PREMIÈRE machine
// paie chaque clonage, et pour un dépôt qui en tire trois cents cela déplace
// le coût plutôt que de le supprimer. Le pré-remplissage le paie une fois, à
// l'heure choisie par l'opérateur.
//
// Les dépôts sont pris à PLUSIEURS à la fois : un clonage passe l'essentiel de
// son temps à attendre le réseau, et les enchaîner un par un tiendrait des
// heures là où la bande passante n'est pas le facteur.
//
// Un dépôt qui échoue ne fait pas échouer les autres : sur une liste de cette
// taille, il y a toujours un dépôt privé, déplacé ou retiré, et tout arrêter
// pour lui perdrait le travail déjà fait. Rend (réussis, échoués).
func (g *GitMirror) Prefetch(
	ctx context.Context, depots []string, parallele int, dire func(string),
) (int, int) {
	if parallele < 1 {
		parallele = 1
	}
	type resultat struct {
		depot string
		ok    bool
	}
	taches := make(chan string)
	sorties := make(chan resultat)

	var wg sync.WaitGroup
	for i := 0; i < parallele; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for d := range taches {
				_, ok := g.Assurer(ctx, d)
				sorties <- resultat{d, ok}
			}
		}()
	}
	go func() {
		defer close(taches)
		for _, d := range depots {
			select {
			case taches <- d:
			case <-ctx.Done():
				return
			}
		}
	}()
	go func() { wg.Wait(); close(sorties) }()

	reussis, echoues, vus := 0, 0, 0
	for r := range sorties {
		vus++
		if r.ok {
			reussis++
		} else {
			echoues++
		}
		if dire != nil {
			etat := "✓"
			if !r.ok {
				etat = "✗"
			}
			dire(fmt.Sprintf("  %s %d/%d %s", etat, vus, len(depots), r.depot))
		}
	}
	return reussis, echoues
}

// DepotsDuFichier lit une liste de dépôts, un par ligne.
//
// Les lignes vides et les commentaires sautent, les doublons aussi : un même
// dépôt figure dans plusieurs manifestes, et le cloner deux fois ne ferait que
// perdre du temps.
func DepotsDuFichier(chemin string) ([]string, error) {
	data, err := os.ReadFile(chemin)
	if err != nil {
		return nil, err
	}
	vus := map[string]bool{}
	var out []string
	for _, l := range strings.Split(string(data), "\n") {
		l = strings.TrimSpace(l)
		if l == "" || strings.HasPrefix(l, "#") {
			continue
		}
		if !vus[l] {
			vus[l] = true
			out = append(out, l)
		}
	}
	return out, nil
}

// PlancherParDefaut : ce qu'on laisse au disque de l'orchestrateur. Assez pour
// qu'une VM en cours de déploiement finisse, et pour que le système respire.
const PlancherParDefaut int64 = 10 << 30

// placeSuffisante dit s'il reste de quoi créer un miroir de plus.
//
// La place est relue à CHAQUE appel : le disque se remplit pendant qu'on le
// remplit, et une valeur retenue au démarrage ne dirait rien de l'état où l'on
// est rendu.
func (g *GitMirror) placeSuffisante() bool {
	plancher := g.PlancherLibre
	if plancher <= 0 {
		plancher = PlancherParDefaut
	}
	var st syscall.Statfs_t
	if err := syscall.Statfs(g.Dir, &st); err != nil {
		// Illisible : on laisse passer plutôt que de bloquer sur une mesure
		// qu'on ne sait pas faire.
		return true
	}
	return int64(st.Bavail)*int64(st.Bsize) > plancher
}

// Depot décrit un miroir tenu sur le disque.
type Depot struct {
	// Chemin est le répertoire du dépôt nu.
	Chemin string
	// Nom est ce qu'il vaut mieux montrer : « github.com/OCA/server-tools ».
	Nom string
	// Octets est ce qu'il occupe, Maj la dernière fois qu'il a été rafraîchi.
	Octets int64
	Maj    time.Time
}

// Depots rend les miroirs tenus, du plus lourd au plus léger.
//
// Par la TAILLE et non par le nom : la place se surveille à la main — aucune
// éviction n'est écrite — et ce qu'on cherche en la surveillant, c'est ce qui
// pèse. Trois dépôts font ici les trois quarts du total ; les lister par ordre
// alphabétique obligerait à les chercher.
func (g *GitMirror) Depots() []Depot {
	if g == nil || g.Dir == "" {
		return nil
	}
	var out []Depot
	filepath.Walk(g.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil || !info.IsDir() ||
			!strings.HasSuffix(p, ".git") {
			return nil
		}
		d := Depot{
			Chemin: p,
			Nom: strings.TrimSuffix(
				strings.TrimPrefix(p, g.Dir+string(os.PathSeparator)), ".git"),
			Maj: info.ModTime(),
		}
		filepath.Walk(p, func(_ string, i os.FileInfo, e error) error {
			if e == nil && i != nil && !i.IsDir() {
				d.Octets += i.Size()
			}
			return nil
		})
		out = append(out, d)
		// Un dépôt nu n'en contient pas d'autre : inutile de descendre.
		return filepath.SkipDir
	})
	sort.Slice(out, func(i, j int) bool { return out[i].Octets > out[j].Octets })
	return out
}

// Retirer efface un miroir. Il se refera au prochain besoin, au prix du
// clonage — c'est la propriété qui rend l'effacement sans danger.
//
// Le chemin est vérifié comme appartenant à la racine des miroirs : un appel
// mal formé ne doit pas pouvoir effacer autre chose.
func (g *GitMirror) Retirer(chemin string) error {
	if g == nil || g.Dir == "" {
		return fmt.Errorf("miroir éteint")
	}
	abs, err := filepath.Abs(chemin)
	if err != nil {
		return err
	}
	racine, err := filepath.Abs(g.Dir)
	if err != nil {
		return err
	}
	if !strings.HasPrefix(abs, racine+string(os.PathSeparator)) ||
		!strings.HasSuffix(abs, ".git") {
		return fmt.Errorf("hors des miroirs : %s", chemin)
	}
	v := g.verrou(abs)
	v.Lock()
	defer v.Unlock()
	return os.RemoveAll(abs)
}
