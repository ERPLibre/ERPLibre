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
	OutcomeKeep        = "keep"         // amont muet, le client garde la sienne
	OutcomePassthrough = "passthrough"  // méthode ou requête non cachable
	OutcomeError       = "error"        // amont joignable, mais en erreur
	OutcomeMirror      = "mirror"       // servi d'un dépôt git tenu sur l'hôte

	// Un statut gardé sans corps a ses PROPRES noms : les lecteurs du
	// journal tiennent « stored » et « stale » pour la preuve qu'un corps est
	// en réserve, et un refus gardé ne l'est pas.
	OutcomeStoredStatus = "stored-status" // pris à l'amont, statut seul gardé
	OutcomeStaleStatus  = "stale-status"  // amont muet, statut seul rejoué
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
	// Client est l'adresse de l'invité qui a demandé.
	//
	// Sans elle, le journal dit ce que le cache a fait mais pas POUR QUI. Un
	// doute sur l'accélération reste alors sans réponse : rien ne sépare ce
	// qu'une VM a tiré du réseau de ce qu'une autre a été servie du disque.
	// Le port est retiré — il change à chaque connexion et empêcherait tout
	// regroupement.
	Client string `json:"client,omitempty"`
}

// clientDe rend l'adresse de l'invité, sans son port.
func clientDe(adresse string) string {
	if h, _, err := net.SplitHostPort(adresse); err == nil {
		return h
	}
	return adresse
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
	// ClientPatient sert les échanges où l'amont CALCULE avant de répondre.
	// Un serveur git énumère ses références à la demande, ce qui demande des
	// dizaines de secondes avant le premier octet sur un dépôt chargé, quand
	// un miroir de paquets répond en quelques centaines de millisecondes. Le
	// délai court,
	// qui existe pour que le repli hors ligne arrive avant que le client
	// renonce, prenait ce calcul pour un amont injoignable et rendait un 504 :
	// « repo sync » échouait alors sur un dépôt parfaitement joignable.
	ClientPatient *http.Client
	// Git tient les dépôts en miroir sur l'hôte. Nul ou éteint, la
	// négociation git est simplement relayée vers l'amont.
	Git *GitMirror
	// Verbose fait parler chaque requête sur la sortie standard, ce qu'un
	// service systemd envoie au journal.
	Verbose bool
	// Muets retient les amonts dont l'établissement vient d'échouer, et la
	// mémoire est partagée avec le miroir git. Nulle, chaque requête retente
	// l'amont et repaie le délai d'établissement.
	Muets *Joignabilite
	// Ecoutes porte les ports où le cache lui-même écoute. Une requête qui
	// vise l'un d'eux sur une adresse de cette machine est une boucle. Vide,
	// rien n'est refusé.
	Ecoutes []int
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
		DialContext:           (&net.Dialer{Timeout: DelaiEtablissement}).DialContext,
		TLSHandshakeTimeout:   5 * time.Second,
		ResponseHeaderTimeout: 8 * time.Second,
		MaxIdleConnsPerHost:   8,
		Proxy:                 http.ProxyFromEnvironment,
	}
	// Le même transport, la seule attente des en-têtes allongée : un serveur
	// injoignable est toujours détecté à l'établissement, en quatre secondes.
	trPatient := tr.Clone()
	trPatient.ResponseHeaderTimeout = 120 * time.Second

	// Une redirection est RENDUE au client plutôt que suivie : il la
	// redemandera au travers du cache, et la copie reste rangée sous l'URL que
	// l'invité a réellement demandée.
	sansSuivre := func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &Proxy{
		Store:  store,
		Log:    alog,
		Client: &http.Client{Transport: tr, CheckRedirect: sansSuivre},
		ClientPatient: &http.Client{
			Transport: trPatient, CheckRedirect: sansSuivre,
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
		return nil, fmt.Errorf("%s", T("requête sans hôte : ni ligne absolue ni en-tête Host"))
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
	key := CleDe(r.Method, u)
	cacheable := CacheableMethod(r.Method) && class != ClassNoStore

	// Une requête adressée au cache lui-même serait relayée vers sa propre
	// écoute, qui la relaierait de nouveau, sans fin : chaque tour ouvre une
	// connexion, jusqu'à épuiser les descripteurs et arrêter le service. Elle
	// est refusée avant toute autre chose.
	if p.viseLeCache(u) {
		p.boucle(w, u, class, r.Method, clientDe(r.RemoteAddr))
		return
	}

	// Une requête partielle n'est servie du cache que si le corps ENTIER y
	// est ; sinon elle passe et ne se garde pas, un fragment ne valant rien
	// pour la requête suivante.
	partial := r.Header.Get("Range") != ""

	if cacheable && class == ClassImmutable {
		if p.serveFromStore(w, r, u, key, class, OutcomeHit) {
			return
		}
	}

	// La négociation git n'est pas relayée quand un miroir peut la servir :
	// c'est un DÉPÔT que l'on tient, pas des réponses, aucune réponse de ce
	// protocole ne se réutilisant d'un client à l'autre.
	if p.Git.Actif() && EstGitSmart(u) && !strings.HasSuffix(
		u.Path, "/git-receive-pack",
	) {
		if depot, reste, ok := DepotDeURL(u); ok {
			if chemin, pret := p.Git.Assurer(r.Context(), depot); pret {
				// Le relevé vient APRÈS : c'est la seule façon de dire ce que
				// la réponse a réellement pesé, et ce chemin porte l'essentiel
				// du trafic d'une installation.
				n := p.Git.Servir(w, r, chemin, reste)
				p.record(accessLine{
					URL: u.String(), Method: r.Method, Class: class.String(),
					Outcome: OutcomeMirror, Status: http.StatusOK, Bytes: n,
					Client: clientDe(r.RemoteAddr),
				})
				return
			}
		}
	}

	// Le client détient-il déjà une copie ? Relevé AVANT tout, et jamais
	// relu sur la requête d'amont : celle-ci peut avoir perdu sa condition
	// juste en dessous, et l'oubli ferait rendre « 504 » à un client qui
	// avait de quoi se passer de nous.
	conditionnelle := estConditionnelle(r)

	// Une requête conditionnelle sur une ressource dont NOUS n'avons pas le
	// corps rapporte « 304 », donc rien à garder. Le cache resterait vide
	// aussi longtemps que ses clients en détiennent une copie — c'est-à-dire
	// toujours, une image cloud livrant déjà l'index de sa suite de base.
	// La condition est donc retirée pour ce seul aller : l'amont envoie le
	// corps entier, une fois, et toute VM suivante est servie, hors ligne
	// comprise. Le corps une fois en réserve, la condition repart et le
	// « 304 » économise de nouveau la bande passante.
	detient := cacheable && p.Store.Detient(key)
	amont := r
	if cacheable && r.Method == "GET" && conditionnelle && !detient {
		amont = sansCondition(r)
	}

	// Un statut seul vit sous sa propre clé, que les lecteurs de corps ne
	// calculent pas : voir CleStatut.
	cleStatut := CleStatut(r.Method, u)

	// repli dit si la branche hors ligne a de quoi répondre : un corps 200,
	// la copie du client (requête conditionnelle d'ORIGINE) ou un statut
	// gardé. Seul un repli autorise à ne pas composer vers un amont connu
	// muet ; sans lui, sauter la tentative changerait un aléa passager en
	// « 504 » certain, pour une requête que l'amont revenu aurait servie.
	repli := cacheable &&
		(detient || conditionnelle || p.Store.TientStatut(cleStatut))

	resp, upErr := p.fetch(amont, u, repli)
	// Une redirection est SUIVIE quand le nom du fichier demandé porte déjà
	// son identité, et le contenu est gardé sous l'URL DEMANDÉE.
	//
	// Sans cela, un paquet publié derrière une redirection n'entre jamais au
	// cache : la cible est une URL SIGNÉE qui change à chaque requête, si bien
	// que la machine suivante ne retrouve rien et retélécharge. Rendre la
	// redirection au client suppose une cible stable, ce qu'une signature à
	// péremption n'est pas.
	//
	// Chaque étape part de la requête d'AMONT : ses conditions sont retirées
	// quand le cache ne détient rien, et la requête d'origine ferait répondre
	// « 304 » à la cible — il n'y aurait alors rien à garder.
	if upErr == nil && class == ClassImmutable && r.Method == "GET" {
		resp = p.suivreRedirections(amont, u, resp)
	}
	if upErr != nil {
		// L'amont est injoignable : DNS muet, connexion refusée, délai
		// dépassé. C'est ici, et seulement ici, qu'une copie périmée sort —
		// y compris un index, ce qui rend le déploiement hors ligne possible.
		// Un index plus récent que la signature qui l'annonce n'est PAS
		// servi : voir indexIncoherent. Le client tombe alors sur le « 304 »
		// qui le laisse garder ses listes, ou sur le refus qui suit.
		if cacheable && !p.indexIncoherent(u, key) &&
			p.serveFromStore(w, r, u, key, class, OutcomeStale) {
			return
		}
		// Le client a posé une condition : il DÉTIENT déjà une copie, et ne
		// demandait qu'à savoir si elle avait changé. Ne pouvant plus le
		// vérifier, lui rendre « 304 » le laisse garder la sienne — c'est ce
		// que « stale-if-error » veut dire pour une requête conditionnelle.
		//
		// Un « 504 » à sa place fait échouer toute la suite de dépôt : apt
		// ne trouve alors plus un paquet de la suite de base, alors que la
		// machine avait chez elle de quoi le nommer.
		if conditionnelle {
			w.Header().Set("X-ERPLibre-Cache", OutcomeKeep)
			w.WriteHeader(http.StatusNotModified)
			p.record(accessLine{
				Method: r.Method, URL: u.String(), Class: class.String(),
				Outcome: OutcomeKeep, Status: http.StatusNotModified,
				Client: clientDe(r.RemoteAddr),
			})
			return
		}
		// Ni corps en réserve ni copie chez le client : reste le STATUT que
		// l'amont a rendu la dernière fois, une redirection ou un refus. Le
		// client qui suit la redirection, ou qui s'arrête sur le 404, reçoit
		// ce qu'il aurait reçu en ligne, là où un 504 l'arrêterait net.
		//
		// Rejoué en DERNIER recours : un corps gardé l'emporte toujours, et le
		// client qui détient sa copie garde son 304 plutôt qu'un refus.
		if cacheable && p.rejouerStatut(w, r, u, cleStatut, class) {
			return
		}
		p.offlineMiss(
			w, u, class, r.Method, clientDe(r.RemoteAddr), upErr,
		)
		return
	}
	defer resp.Body.Close()

	store := cacheable && !partial && resp.StatusCode == http.StatusOK &&
		r.Method == "GET"
	// Un statut est gardé SEUL, sans corps, quand il porte une réponse
	// qu'aucun corps ne remplace : redirection ou refus définitif pour un GET,
	// et en plus le 200 d'un HEAD, qui n'a jamais de corps. Il est rangé
	// sous CleStatut, jamais sous la clé du corps, et ne ressort que l'amont
	// muet. Trois bornes :
	//   - le volatile seul : l'immuable suit ses redirections, et un 404
	//     servi du disque y masquerait le fichier publié ensuite ;
	//   - jamais sous une clé portable : partagée par tous les miroirs, elle
	//     recevrait le refus d'un miroir en retard à la place de l'index
	//     qu'un autre a rendu ;
	//   - jamais quand la clé du CORPS tient un 200 : le rejeu ne passe
	//     qu'après lui, et le garder ne servirait qu'à le faire mentir le
	//     jour où ce corps disparaît.
	// Un statut passager — 403, 429, 5xx — ne se garde pas : le rejouer
	// figerait une panne qui n'a duré qu'un moment.
	//
	// Detenir, dans « --detient », tient la négation exacte de cette
	// condition pour un HEAD : les deux sont à changer ensemble.
	statutSeul := !store && cacheable && !partial &&
		class == ClassVolatile && !PortableParChemin(u) &&
		statutSansCorps(r.Method, resp) && !detient

	var cw *Writer
	if store || statutSeul {
		cle := key
		if statutSeul {
			cle = cleStatut
		}
		m := Meta{
			URL:    u.String(),
			Method: r.Method,
			Status: resp.StatusCode,
			Header: resp.Header.Clone(),
			Class:  class.String(),
		}
		if statutSeul {
			m.StatusOnly = true
			sansLongueurMenteuse(r.Method, m.Header)
			// Le témoin de session appartient à la machine qui l'a reçu.
			m.Header.Del("Set-Cookie")
		}
		if cw, err = p.Store.NewWriter(cle, m); err != nil {
			log.Printf(T("cache : écriture impossible pour %s : %v"), u, err)
			cw = nil
		}
	}

	copyHeader(w.Header(), resp.Header)
	w.Header().Set("X-ERPLibre-Cache", "miss")
	w.WriteHeader(resp.StatusCode)

	// Le corps d'un statut seul va au client tel quel, jamais au disque.
	var sink *Writer
	if cw != nil && store {
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
		// Un statut seul se publie VIDE, quelle que soit la longueur
		// annoncée : pour un HEAD, la bibliothèque la tire de l'en-tête alors
		// qu'aucun corps ne suit, et la comparer ferait tout refuser.
		attendu := resp.ContentLength
		if statutSeul {
			attendu = 0
		}
		if cerr := cw.Commit(attendu); cerr != nil {
			log.Printf(T("cache : %s non gardé : %v"), u, cerr)
			outcome = OutcomeFetched
		} else if statutSeul {
			outcome = OutcomeStoredStatus
		} else {
			outcome = OutcomeStored
		}
	case !cacheable:
		outcome = OutcomePassthrough
	}

	p.record(accessLine{
		Method: r.Method, URL: u.String(), Class: class.String(),
		Outcome: outcome, Status: resp.StatusCode, Bytes: n, Upstream: true,
		Client: clientDe(r.RemoteAddr),
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
	// Seul un corps 200 sort par ici. Un statut seul a son propre chemin,
	// réservé à l'amont muet : ServeContent en ferait un 200 vide, et sur le
	// chemin de l'immuable il sortirait même quand l'amont répond.
	if m.StatutSeul() {
		return false
	}

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
		Client: clientDe(r.RemoteAddr),
	})
	if p.Verbose {
		log.Printf("%s %s -> %s (%s)", r.Method, u, outcome, HumanBytes(m.Size))
	}
	return true
}

// rejouerStatut rend, sans corps, le statut gardé sous la clé — une clé de
// CleStatut : ses en-têtes, « Location » compris et tel que l'amont l'a
// écrit, puis le code. Rend faux quand la clé ne porte pas de statut seul.
//
// ServeContent est évité entièrement : il réécrirait le code en 200, et
// ferait d'une redirection un « 304 » ou un « 206 » selon ce que le client
// pose. La longueur d'un GET est retirée une seconde fois, un méta écrit à
// la main pouvant la porter ; celle d'un HEAD ressort telle que l'amont l'a
// annoncée.
func (p *Proxy) rejouerStatut(
	w http.ResponseWriter, r *http.Request, u *url.URL, key string,
	class Class,
) bool {
	m, f, err := p.Store.Get(key)
	if err != nil {
		return false
	}
	f.Close()
	if !m.StatutSeul() {
		return false
	}

	copyHeader(w.Header(), m.Header)
	sansLongueurMenteuse(m.Method, w.Header())
	w.Header().Set("X-ERPLibre-Cache", OutcomeStaleStatus)
	w.Header().Set("X-ERPLibre-Cache-Date", m.StoredAt.Format(time.RFC3339))
	w.WriteHeader(m.Status)

	p.record(accessLine{
		Method: r.Method, URL: u.String(), Class: class.String(),
		Outcome: OutcomeStaleStatus, Status: m.Status, Upstream: false,
		Client: clientDe(r.RemoteAddr),
	})
	if p.Verbose {
		log.Printf("%s %s -> %s (%d)", r.Method, u, OutcomeStaleStatus, m.Status)
	}
	return true
}

// sansLongueurMenteuse retire la longueur d'un statut seul, sauf pour un HEAD.
//
// Pour un GET, la longueur annoncée sans corps mentirait : le client
// attendrait des octets qui ne viendront jamais, et échouerait sur une fin de
// flux inattendue. Pour un HEAD, elle ne ment pas — la norme (RFC 9110) en
// fait la taille du corps que rendrait le GET, et aucun client ne lit de
// corps après un HEAD. C'est même la seule chose qu'il apprend du corps :
// l'installateur qui compare une taille par « curl -I » recevrait sinon hors
// ligne une autre réponse qu'en ligne.
func sansLongueurMenteuse(methode string, h http.Header) {
	if methode != http.MethodHead {
		h.Del("Content-Length")
	}
}

// statutSansCorps dit si la réponse porte un statut qui vaut d'être gardé
// seul : une redirection qui dit où aller, un refus définitif, et pour un
// HEAD aussi le 200 — le HEAD n'a de toute façon jamais de corps.
//
// Une redirection sans « Location » ne mène nulle part : elle n'est pas
// gardée.
func statutSansCorps(methode string, resp *http.Response) bool {
	switch resp.StatusCode {
	case http.StatusMovedPermanently, http.StatusFound, http.StatusSeeOther,
		http.StatusTemporaryRedirect, http.StatusPermanentRedirect:
		return resp.Header.Get("Location") != ""
	case http.StatusNotFound, http.StatusGone:
		return true
	case http.StatusOK:
		return methode == "HEAD"
	}
	return false
}

// offlineMiss dit CE QUI manque. Un 404 nu ferait accuser le miroir : le
// client n'a aucun moyen de savoir qu'un cache s'est interposé, et le message
// est la seule chance de le lui apprendre.
func (p *Proxy) offlineMiss(
	w http.ResponseWriter, u *url.URL, class Class, method, client string,
	cause error,
) {
	msg := enCommentaire(fmt.Sprintf(
		T("erplibre_go_qemu_cache : amont injoignable et rien en réserve.\n"+
			"  demandé : %s\n"+
			"  classe  : %s\n"+
			"  cause   : %v\n"+
			"%s"+
			"Ce fichier n'a jamais traversé ce cache. Rétablir le réseau, ou\n"+
			"déployer une VM identique à celle qui a rempli le cache.\n"),
		u, class, cause, decrireMuet(cause)))
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("X-ERPLibre-Cache", OutcomeOfflineMiss)
	w.WriteHeader(http.StatusGatewayTimeout)
	fmt.Fprint(w, msg)

	p.record(accessLine{
		Method: method, URL: u.String(), Class: class.String(),
		Outcome: OutcomeOfflineMiss, Status: http.StatusGatewayTimeout,
		Client: client,
	})
	log.Printf(T("hors ligne, absent du cache : %s"), u)
}

// maxRedirections borne la chaîne : une boucle de redirections tournerait
// jusqu'à épuiser la mémoire, et aucune publication légitime n'en enchaîne
// autant.
const maxRedirections = 5

// suivreRedirections rend la réponse FINALE d'une chaîne de redirections, ou
// la dernière obtenue si quelque chose s'y oppose.
//
// Chaque étape rejoue `r`, la requête d'amont partie vers `depart`. Les
// identifiants — « Authorization », « Cookie », « Proxy-Authorization » — ne
// suivent pas une étape qui quitte l'hôte de départ : ils ont été confiés à
// cet hôte, et une redirection vers un stockage tiers les lui livrerait. Le
// client HTTP de la bibliothèque les retire de même ; un suivi à la main doit
// le faire lui-même.
//
// Une cible qui désigne le cache lui-même arrête la chaîne : la suivre
// renverrait la requête ici.
//
// Le corps de chaque étape est refermé : une redirection en porte un, court,
// que personne ne lira. Une erreur en route rend l'étape courante plutôt que
// rien : le client verra la redirection et se débrouillera, ce qui est le
// comportement d'avant.
func (p *Proxy) suivreRedirections(
	r *http.Request, depart *url.URL, resp *http.Response,
) *http.Response {
	origine := adresseAmont(depart)
	for i := 0; i < maxRedirections; i++ {
		if resp.StatusCode < 300 || resp.StatusCode > 399 {
			return resp
		}
		cible, err := resp.Location()
		if err != nil || cible == nil || p.viseLeCache(cible) {
			return resp
		}
		etape := r
		if adresseAmont(cible) != origine {
			etape = sansIdentifiants(r)
		}
		// Sans repli : l'étape qui échoue rend la redirection au client,
		// qui la redemandera au travers du cache — la tenter coûte au plus
		// le délai d'établissement, la sauter ne ferait que le déplacer.
		suivante, err := p.fetch(etape, cible, false)
		if err != nil {
			return resp
		}
		resp.Body.Close()
		resp = suivante
	}
	return resp
}

// enTetesDIdentite : ce par quoi un client s'authentifie auprès d'un hôte.
var enTetesDIdentite = []string{
	"Authorization", "Cookie", "Proxy-Authorization",
}

// sansIdentifiants rend une COPIE de la requête, ses identifiants retirés.
func sansIdentifiants(r *http.Request) *http.Request {
	out := r.Clone(r.Context())
	for _, h := range enTetesDIdentite {
		out.Header.Del(h)
	}
	return out
}

// enCommentaire rend un texte INERTE pour un interpréteur de commandes.
//
// Un corps d'erreur finit régulièrement dans un shell : l'idiome
// « curl … | bash » est celui de la moitié des installateurs, et « curl »
// sans « -f » lui livre le corps d'un 504 comme s'il l'avait demandé. Chaque
// ligne du message devenait alors une commande, et le lecteur recevait une
// cascade de « command not found » à la place de la cause.
//
// Chaque ligne est donc préfixée — y compris celles d'une cause qui en
// porterait plusieurs, sans quoi la première suffirait à sortir du
// commentaire. Le texte reste lisible pour l'humain, et ne fait rien.
func enCommentaire(texte string) string {
	lignes := strings.Split(strings.TrimRight(texte, "\n"), "\n")
	for i, l := range lignes {
		lignes[i] = "# " + l
	}
	return strings.Join(lignes, "\n") + "\n"
}

// enTetesConditionnels : ce par quoi un client dit « seulement si ça a
// changé ». Le « Range » n'en est pas — il demande un fragment, pas une
// validation, et il est traité ailleurs.
var enTetesConditionnels = []string{
	"If-None-Match", "If-Modified-Since", "If-Match", "If-Unmodified-Since",
}

// estConditionnelle dit si le client détient déjà une copie de la ressource.
func estConditionnelle(r *http.Request) bool {
	for _, h := range enTetesConditionnels {
		if r.Header.Get(h) != "" {
			return true
		}
	}
	return false
}

// sansCondition rend une COPIE de la requête, ses conditions retirées.
//
// Une copie : la requête d'origine est celle du serveur HTTP, et la modifier
// changerait ce que voit tout ce qui la lit ensuite — le relevé, notamment.
func sansCondition(r *http.Request) *http.Request {
	out := r.Clone(r.Context())
	for _, h := range enTetesConditionnels {
		out.Header.Del(h)
	}
	return out
}

// fetch interroge l'amont.
//
// repli dit que l'appelant a de quoi répondre sans l'amont : corps gardé,
// copie du client ou statut gardé. Avec lui, un amont dont l'établissement
// vient d'échouer n'est pas retenté : fetch rend aussitôt une erreur qui
// enveloppe errAmontConnuMuet, et l'appelant sert son repli sans repayer le
// délai d'établissement. Un pare-feu qui jette les paquets fait attendre ce
// délai entier à chaque tentative ; le repli, lui, n'a rien à attendre.
//
// Sans repli, fetch compose toujours, mémoire ou non : un échec
// d'établissement passager — un paquet perdu, un miroir qui redémarre —
// ferait sinon rendre « 504 » à toute requête vers cet hôte pendant la
// fenêtre, alors que l'amont revenu l'aurait servie.
//
// Chaque échec d'établissement est retenu et chaque réponse efface l'hôte,
// avec ou sans repli : la mémoire ne retient que les établissements manqués.
func (p *Proxy) fetch(
	r *http.Request, u *url.URL, repli bool,
) (*http.Response, error) {
	adresse := adresseAmont(u)
	if repli && p.Muets.ConnuMuet(adresse) {
		return nil, fmt.Errorf("%w (%s)", errAmontConnuMuet, adresse)
	}
	out, err := http.NewRequestWithContext(r.Context(), r.Method, u.String(), r.Body)
	if err != nil {
		return nil, err
	}
	copyHeader(out.Header, r.Header)
	// L'identité de l'invité est conservée : certains miroirs répondent
	// différemment selon l'agent, et un paquet servi à un agent n'est pas
	// forcément celui servi à un autre.
	out.Header.Del("Accept-Encoding")
	client := p.Client
	if EstGitSmart(u) {
		client = p.ClientPatient
	}
	resp, err := client.Do(out)
	if err != nil {
		p.Muets.Echec(adresse, err)
		return nil, err
	}
	p.Muets.Reussite(adresse)
	return resp, nil
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
