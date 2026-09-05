// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

// Issues d'une requête, telles qu'elles paraissent au journal d'accès. Le
// journal EST la mesure : un test qui veut prouver que la seconde VM n'a rien
// tiré de l'amont compte les lignes, sans avoir à instrumenter l'invité.
const (
	OutcomeHit         = "hit"          // servi du disque
	OutcomeStored      = "stored"       // pris à l'amont, gardé
	OutcomeFetched     = "fetched"      // pris à l'amont, non gardé
	OutcomeStale       = "stale"        // amont muet, copie stockée servie
	OutcomeOfflineMiss = "offline-miss" // amont muet, rien en réserve
	OutcomePassthrough = "passthrough"  // méthode ou requête non cachable
	OutcomeError       = "error"        // amont joignable, mais en erreur
)

// AccessLog écrit une ligne JSON par requête. Un format à une ligne par
// requête se lit par « grep » et se compte par « wc », ce qui est exactement
// ce qu'un test de bout en bout a besoin de faire.
type AccessLog struct {
	mu sync.Mutex
	f  *os.File
}

func OpenAccessLog(path string) (*AccessLog, error) {
	if path == "" {
		return &AccessLog{}, nil
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return nil, err
	}
	return &AccessLog{f: f}, nil
}

type accessLine struct {
	Time    string `json:"time"`
	Method  string `json:"method"`
	URL     string `json:"url"`
	Class   string `json:"class"`
	Outcome string `json:"outcome"`
	Status  int    `json:"status"`
	Bytes   int64  `json:"bytes"`
	// Upstream dit si l'octet a traversé le réseau. C'est le champ que la
	// mesure regarde.
	Upstream bool `json:"upstream"`
}

func (a *AccessLog) Write(l accessLine) {
	if a == nil || a.f == nil {
		return
	}
	l.Time = time.Now().UTC().Format(time.RFC3339)
	raw, err := json.Marshal(l)
	if err != nil {
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.f.Write(append(raw, '\n'))
}

func (a *AccessLog) Close() {
	if a != nil && a.f != nil {
		a.f.Close()
	}
}

// Proxy sert les requêtes détournées vers lui.
type Proxy struct {
	Store  *Store
	Log    *AccessLog
	Client *http.Client
	// Verbose fait parler chaque requête sur la sortie standard, ce qu'un
	// service systemd envoie au journal.
	Verbose bool
}

// NewProxy monte le client amont. Aucun délai GLOBAL n'est posé : une image
// qcow2 met des minutes à descendre, et un délai global la couperait au
// milieu. Les délais portent donc sur l'établissement et sur l'attente des
// en-têtes, jamais sur la durée du corps.
func NewProxy(store *Store, alog *AccessLog) *Proxy {
	// Les délais sont bornés par la PATIENCE DU CLIENT, pas par la nôtre.
	// pacman abandonne un fichier après dix secondes sous un octet par
	// seconde ; si notre repli sur la copie stockée arrive plus tard, il
	// n'arrive jamais — et un pare-feu qui jette les paquets sans les refuser
	// fait justement pendre l'établissement jusqu'au délai.
	tr := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 4 * time.Second}).DialContext,
		TLSHandshakeTimeout:   5 * time.Second,
		ResponseHeaderTimeout: 8 * time.Second,
		MaxIdleConnsPerHost:   8,
		Proxy:                 http.ProxyFromEnvironment,
	}
	return &Proxy{
		Store: store,
		Log:   alog,
		Client: &http.Client{
			Transport: tr,
			// Une redirection est RENDUE au client plutôt que suivie : il la
			// redemandera au travers du cache, et la copie reste rangée sous
			// l'URL que l'invité a réellement demandée.
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
	}
}

// En-têtes que la norme réserve à un saut : les recopier vers l'amont ou vers
// le client casse la connexion.
var hopByHop = []string{
	"Connection", "Proxy-Connection", "Keep-Alive", "Proxy-Authenticate",
	"Proxy-Authorization", "Te", "Trailer", "Transfer-Encoding", "Upgrade",
}

func copyHeader(dst, src http.Header) {
	for k, vs := range src {
		for _, v := range vs {
			dst.Add(k, v)
		}
	}
	for _, h := range hopByHop {
		dst.Del(h)
	}
}

// absoluteURL reconstruit l'adresse demandée. En interception transparente le
// client parle comme s'il tenait le serveur en face de lui : la ligne de
// requête ne porte qu'un chemin, et l'hôte vient de l'en-tête « Host » pour
// HTTP, du SNI pour TLS.
func absoluteURL(r *http.Request, scheme string) (*url.URL, error) {
	if r.URL.IsAbs() {
		return r.URL, nil
	}
	host := r.Host
	if host == "" {
		return nil, fmt.Errorf("requête sans hôte : ni ligne absolue ni en-tête Host")
	}
	u := *r.URL
	u.Scheme = scheme
	u.Host = host
	return &u, nil
}

func (p *Proxy) handler(scheme string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p.serve(w, r, scheme)
	})
}

func (p *Proxy) serve(w http.ResponseWriter, r *http.Request, scheme string) {
	u, err := absoluteURL(r, scheme)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	class := Classify(u)
	// La clé écarte l'hôte quand le NOM du fichier l'identifie partout : une
	// liste de miroirs tourne, et une clé qui porte l'hôte ferait manquer le
	// cache au fichier déjà gardé sous un autre nom de miroir.
	key := Key(r.Method, u.String())
	if PortableParChemin(u) {
		key = KeySansHote(r.Method, u)
	}
	cacheable := CacheableMethod(r.Method) && class != ClassNoStore

	// Une requête partielle n'est servie du cache que si le corps ENTIER y
	// est ; sinon elle passe et ne se garde pas, un fragment ne valant rien
	// pour la requête suivante.
	partial := r.Header.Get("Range") != ""

	if cacheable && class == ClassImmutable {
		if p.serveFromStore(w, r, u, key, class, OutcomeHit) {
			return
		}
	}

	resp, upErr := p.fetch(r, u)
	if upErr != nil {
		// L'amont est injoignable : DNS muet, connexion refusée, délai
		// dépassé. C'est ici, et seulement ici, qu'une copie périmée sort —
		// y compris un index, ce qui rend le déploiement hors ligne possible.
		if cacheable && p.serveFromStore(w, r, u, key, class, OutcomeStale) {
			return
		}
		p.offlineMiss(w, u, class, r.Method, upErr)
		return
	}
	defer resp.Body.Close()

	store := cacheable && !partial && resp.StatusCode == http.StatusOK &&
		r.Method == "GET"

	var cw *Writer
	if store {
		m := Meta{
			URL:    u.String(),
			Method: r.Method,
			Status: resp.StatusCode,
			Header: resp.Header.Clone(),
			Class:  class.String(),
		}
		if cw, err = p.Store.NewWriter(key, m); err != nil {
			log.Printf("cache : écriture impossible pour %s : %v", u, err)
			cw = nil
		}
	}

	copyHeader(w.Header(), resp.Header)
	w.Header().Set("X-ERPLibre-Cache", "miss")
	w.WriteHeader(resp.StatusCode)

	var sink *Writer
	if cw != nil {
		sink = cw
	}
	var n int64
	if sink != nil {
		n, err = copyTee(w, sink, resp.Body)
	} else {
		n, err = copyTee(w, nil, resp.Body)
	}

	outcome := OutcomeFetched
	switch {
	case err != nil:
		// Le client s'est déconnecté ou l'amont a coupé : rien de partiel
		// n'entre au cache.
		if cw != nil {
			cw.Abort()
		}
		outcome = OutcomeError
	case cw != nil:
		if cerr := cw.Commit(resp.ContentLength); cerr != nil {
			log.Printf("cache : %s non gardé : %v", u, cerr)
			outcome = OutcomeFetched
		} else {
			outcome = OutcomeStored
		}
	case !cacheable:
		outcome = OutcomePassthrough
	}

	p.record(accessLine{
		Method: r.Method, URL: u.String(), Class: class.String(),
		Outcome: outcome, Status: resp.StatusCode, Bytes: n, Upstream: true,
	})
}

// serveFromStore rend vrai quand la réponse est partie du disque.
func (p *Proxy) serveFromStore(
	w http.ResponseWriter, r *http.Request, u *url.URL, key string,
	class Class, outcome string,
) bool {
	m, f, err := p.Store.Get(key)
	if err != nil {
		return false
	}
	defer f.Close()

	copyHeader(w.Header(), m.Header)
	w.Header().Set("X-ERPLibre-Cache", outcome)
	if outcome == OutcomeStale {
		// L'opérateur doit pouvoir dire de quand datent les octets sur
		// lesquels sa VM se bâtit.
		w.Header().Set("X-ERPLibre-Cache-Date", m.StoredAt.Format(time.RFC3339))
	}
	// ServeContent tient les requêtes partielles et le code 206 : pacman
	// reprend un téléchargement interrompu par une plage.
	http.ServeContent(w, r, "", m.StoredAt, f)

	p.record(accessLine{
		Method: r.Method, URL: u.String(), Class: class.String(),
		Outcome: outcome, Status: http.StatusOK, Bytes: m.Size, Upstream: false,
	})
	if p.Verbose {
		log.Printf("%s %s -> %s (%s)", r.Method, u, outcome, HumanBytes(m.Size))
	}
	return true
}

// offlineMiss dit CE QUI manque. Un 404 nu ferait accuser le miroir : le
// client n'a aucun moyen de savoir qu'un cache s'est interposé, et le message
// est la seule chance de le lui apprendre.
func (p *Proxy) offlineMiss(
	w http.ResponseWriter, u *url.URL, class Class, method string, cause error,
) {
	msg := fmt.Sprintf(
		"erplibre_go_qemu_cache : amont injoignable et rien en réserve.\n"+
			"  demandé : %s\n"+
			"  classe  : %s\n"+
			"  cause   : %v\n"+
			"Ce fichier n'a jamais traversé ce cache. Rétablir le réseau, ou\n"+
			"déployer une VM identique à celle qui a rempli le cache.\n",
		u, class, cause)
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("X-ERPLibre-Cache", OutcomeOfflineMiss)
	w.WriteHeader(http.StatusGatewayTimeout)
	fmt.Fprint(w, msg)

	p.record(accessLine{
		Method: method, URL: u.String(), Class: class.String(),
		Outcome: OutcomeOfflineMiss, Status: http.StatusGatewayTimeout,
	})
	log.Printf("hors ligne, absent du cache : %s", u)
}

func (p *Proxy) fetch(r *http.Request, u *url.URL) (*http.Response, error) {
	out, err := http.NewRequestWithContext(r.Context(), r.Method, u.String(), r.Body)
	if err != nil {
		return nil, err
	}
	copyHeader(out.Header, r.Header)
	// L'identité de l'invité est conservée : certains miroirs répondent
	// différemment selon l'agent, et un paquet servi à un agent n'est pas
	// forcément celui servi à un autre.
	out.Header.Del("Accept-Encoding")
	return p.Client.Do(out)
}

func (p *Proxy) record(l accessLine) {
	p.Log.Write(l)
	if p.Verbose && l.Upstream {
		log.Printf("%s %s -> %s (%s)", l.Method, l.URL, l.Outcome, HumanBytes(l.Bytes))
	}
}

// hostOnly retire le port d'une autorité, le SNI n'en portant pas.
func hostOnly(hostport string) string {
	if h, _, err := net.SplitHostPort(hostport); err == nil {
		return h
	}
	return strings.TrimSuffix(hostport, ":")
}
