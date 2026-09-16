// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// CA signe les certificats que le cache présente aux invités.
//
// Déchiffrer suppose que l'invité approuve cette autorité, ce qui est la
// SEULE configuration que l'interception transparente ne peut pas éviter : la
// redirection TCP est invisible, la confiance TLS ne l'est pas. La clé reste
// en 0600 et ne quitte jamais l'orchestrateur ; seul le certificat part dans
// les VM.
type CA struct {
	cert    *x509.Certificate
	key     *rsa.PrivateKey
	certPEM []byte

	mu     sync.Mutex
	leaves map[string]*tls.Certificate
}

// LoadOrCreateCA lit l'autorité, et la fabrique si elle manque.
//
// Une autorité créée à l'installation et jamais remplacée : la régénérer
// invaliderait les certificats de toutes les VM déjà configurées, qui
// tomberaient sur une erreur de certificat sans rapport apparent avec le
// cache.
func LoadOrCreateCA(dir string) (*CA, error) {
	certPath := filepath.Join(dir, "ca.crt")
	keyPath := filepath.Join(dir, "ca.key")

	if certPEM, err := os.ReadFile(certPath); err == nil {
		keyPEM, err := os.ReadFile(keyPath)
		if err != nil {
			return nil, fmt.Errorf(T("clé de l'autorité illisible : %w"), err)
		}
		cb, _ := pem.Decode(certPEM)
		kb, _ := pem.Decode(keyPEM)
		if cb == nil || kb == nil {
			return nil, errors.New(T("autorité illisible : PEM invalide"))
		}
		cert, err := x509.ParseCertificate(cb.Bytes)
		if err != nil {
			return nil, err
		}
		key, err := x509.ParsePKCS1PrivateKey(kb.Bytes)
		if err != nil {
			return nil, err
		}
		return &CA{cert: cert, key: key, certPEM: certPEM,
			leaves: map[string]*tls.Certificate{}}, nil
	}

	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return nil, err
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName:   "ERPLibre QEMU cache",
			Organization: []string{"ERPLibre"},
		},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().AddDate(10, 0, 0),
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		return nil, err
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		return nil, err
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{
		Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})

	if err := os.WriteFile(certPath, certPEM, 0o644); err != nil {
		return nil, err
	}
	// 0600 : la clé de cette autorité permet de se faire passer pour
	// n'importe quel site auprès d'une VM qui l'approuve.
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		return nil, err
	}
	return &CA{cert: cert, key: key, certPEM: certPEM,
		leaves: map[string]*tls.Certificate{}}, nil
}

// CertPath rend le chemin du certificat à poser dans les VM.
func CertPath(dir string) string { return filepath.Join(dir, "ca.crt") }

// Fingerprint permet de vérifier de visu que la VM approuve BIEN cette
// autorité et non une autre.
func (c *CA) Fingerprint() string {
	sum := sha256.Sum256(c.cert.Raw)
	h := hex.EncodeToString(sum[:])
	var b strings.Builder
	for i := 0; i < len(h); i += 2 {
		if i > 0 {
			b.WriteByte(':')
		}
		b.WriteString(strings.ToUpper(h[i : i+2]))
	}
	return b.String()
}

// leafFor fabrique, et garde en mémoire, le certificat d'un nom d'hôte. Les
// feuilles sont en ECDSA : une VM demande des dizaines d'hôtes pendant une
// installation, et générer une clé RSA à chacun se verrait.
func (c *CA) leafFor(host string) (*tls.Certificate, error) {
	c.mu.Lock()
	if crt, ok := c.leaves[host]; ok {
		c.mu.Unlock()
		return crt, nil
	}
	c.mu.Unlock()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return nil, err
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: host},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().AddDate(1, 0, 0),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	if ip := net.ParseIP(host); ip != nil {
		tmpl.IPAddresses = []net.IP{ip}
	} else {
		tmpl.DNSNames = []string{host}
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, c.cert, &key.PublicKey, c.key)
	if err != nil {
		return nil, err
	}
	crt := &tls.Certificate{Certificate: [][]byte{der, c.cert.Raw}, PrivateKey: key}

	c.mu.Lock()
	c.leaves[host] = crt
	c.mu.Unlock()
	return crt, nil
}

// Refusals retient les hôtes dont le client a refusé notre certificat.
//
// Certains clients épinglent leur autorité et n'accepteront jamais la nôtre —
// snapd est le cas connu. Plutôt qu'une liste à tenir à jour, le repli ne se
// déclare pas d'avance : la première poignée de main échoue, l'hôte est
// retenu, et toutes les suivantes passent en tunnel opaque. La première
// requête est perdue, c'est le prix de n'avoir rien à configurer.
// Un refus APPRIS s'oublie, un refus DÉCLARÉ jamais.
//
// Les deux ne disent pas la même chose. Un hôte déclaré épingle son autorité
// pour toujours, et le réessayer coûterait une requête à chaque fois. Un refus
// appris, lui, peut n'avoir rien de définitif : une VM dont le magasin de
// confiance n'est pas encore posé refuse la première poignée de main, et
// l'hôte se retrouvait alors condamné au tunnel POUR LA VIE DU SERVICE — donc
// à ne plus jamais être caché, y compris pour toutes les VM suivantes, qui
// elles font confiance.
//
// L'oubli remet le doute : au bout du délai, une poignée de main est retentée.
// Un vrai épingleur la refuse à nouveau et le refus est réappris, au prix
// d'une requête perdue par délai. Un hôte qui n'avait qu'un magasin en retard
// redevient cachable.
// refus retient QUAND un hôte a été appris, et POURQUOI.
//
// La nature commande la durée. Une alerte est une décision : le client a
// regardé notre certificat et l'a rejeté, il ne se ravisera pas. Une
// répétition de coupures n'est qu'un SOUPÇON — trois erreurs de transport
// ressemblent à un épingleur sans en être un — et un soupçon doit pouvoir se
// rouvrir. Les confondre condamne un miroir de distribution aussi
// définitivement qu'un épingleur, et prive alors le cache de tout ce qu'il
// détient pour lui : un tunnel recopie des octets, il ne consulte jamais le
// magasin.
type refus struct {
	quand  time.Time
	alerte bool
}

type Refusals struct {
	mu       sync.RWMutex
	declares map[string]bool
	apprises map[string]refus
	echecs   map[string]int
	// Oubli borne la mémoire d'un refus de TRANSPORT. Nul, il ne s'oublie
	// jamais. Une ALERTE ne s'oublie en aucun cas, quel que soit ce réglage.
	Oubli time.Duration
	// Seuil : combien de poignées de main de suite doivent échouer avant de
	// conclure. Nul, la valeur par défaut s'applique.
	Seuil int
	// Rafale : deux coupures plus rapprochées que cela ne comptent que pour
	// une. Nulle, la valeur par défaut s'applique ; négative, chaque coupure
	// compte, ce dont un test se sert pour condamner sans attendre.
	Rafale time.Duration
	// Maintenant rend l'instant courant. Nulle, time.Now : un test injecte
	// son horloge pour espacer des coupures sans dormir.
	Maintenant func() time.Time
	// dernier : quand a été COMPTÉE la dernière coupure d'un hôte, ce qui
	// distingue une rafale d'un échec qui se répète.
	dernier map[string]time.Time
}

// RafaleParDefaut : en deçà, deux poignées de main coupées sont le MÊME
// incident.
//
// apt ouvre plusieurs connexions de front vers un dépôt et ferme celles dont
// il ne se sert pas : trois coupures dans la même seconde atteignaient le
// seuil sans que rien n'ait rejeté notre certificat. Un client qui refuse
// vraiment réessaie et échoue encore, à des secondes de là.
const RafaleParDefaut = 2 * time.Second

// SeuilParDefaut : trois échecs de suite avant de renoncer à déchiffrer.
//
// Un client qui ne nous fera jamais confiance échoue à CHAQUE fois ; une
// coupure de transport, elle, ne se répète pas. Compter permet de servir les
// deux sans les distinguer à la première vue — ce qui est impossible, npm
// rejetant notre certificat sans envoyer d'alerte : le serveur ne voit qu'un
// EOF, exactement comme sur une VM qui démarre et coupe.
const SeuilParDefaut = 3

// OubliParDefaut : au bout de ce délai, un refus de TRANSPORT est rouvert.
//
// Une ALERTE, elle, ne s'oublie jamais, et ce réglage ne l'atteint pas : le
// client a regardé notre certificat et l'a rejeté. Ceux qui font cela portent
// leur propre magasin de confiance et ne changeront pas d'avis ; les
// ré-intercepter ferait échouer de nouveau une installation qui les traverse.
//
// Un refus appris par SEUIL n'est pas de cette nature. Trois coupures de
// suite — un flux corrompu, une fin de flux — ne disent rien de ce que le
// client pense de nous ; estRefusTLS le sait, mais le seuil conclut quand
// même. Condamner sur ce soupçon prive le cache de TOUT ce qu'il détient pour
// cet hôte, un tunnel ne servant jamais le magasin : un miroir de
// distribution banni sur une rafale renvoie alors tout son trafic à l'amont,
// y compris ce qui est en réserve.
//
// Dix minutes : assez pour ne pas repayer le délai pendant la rafale qui a
// condamné l'hôte, assez peu pour que l'installation suivante le retrouve. Le
// prix du doute est une poignée de main perdue de loin en loin.
const OubliParDefaut = 10 * time.Minute

func NewRefusals(static []string) *Refusals {
	r := &Refusals{
		declares: map[string]bool{},
		apprises: map[string]refus{},
		echecs:   map[string]int{},
		dernier:  map[string]time.Time{},
		Oubli:    OubliParDefaut,
		Seuil:    SeuilParDefaut,
		Rafale:   RafaleParDefaut,
	}
	for _, h := range static {
		if h = strings.TrimSpace(strings.ToLower(h)); h != "" {
			r.declares[h] = true
		}
	}
	return r
}

// DefaultExclusions : les hôtes dont l'épinglage est connu d'avance. Les y
// mettre évite de perdre une requête pour l'apprendre.
var DefaultExclusions = []string{
	"api.snapcraft.io",
	"dashboard.snapcraft.io",
	"login.ubuntu.com",
}

func (r *Refusals) Has(host string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.declares[host] {
		return true
	}
	// Un suffixe couvre un domaine entier : « .snapcraft.io » vaut pour tous
	// ses sous-domaines.
	for h := range r.declares {
		if strings.HasPrefix(h, ".") && strings.HasSuffix(host, h) {
			return true
		}
	}
	vu, appris := r.apprises[host]
	if !appris {
		return false
	}
	// Une décision ne se révise pas ; un soupçon, si.
	if vu.alerte {
		return true
	}
	if r.Oubli > 0 && r.maintenant().Sub(vu.quand) >= r.Oubli {
		r.oublier(host)
		return false
	}
	return true
}

// oublier rouvre un soupçon de transport, compte compris. Garder le compte
// ferait condamner l'hôte rouvert dès sa première coupure : le doute rendu
// par l'oubli doit se reconstruire sur un seuil entier. Appelant verrouillé.
func (r *Refusals) oublier(host string) {
	delete(r.apprises, host)
	delete(r.echecs, host)
	delete(r.dernier, host)
}

// Echec note une poignée de main manquée et dit si l'hôte passe en tunnel.
//
// Une ALERTE tranche tout de suite : le client a regardé notre certificat et
// l'a rejeté, il n'y a rien à réessayer. Tout le reste — coupure, fin de flux —
// doit se RÉPÉTER pour compter : un client qui ne nous fera jamais confiance
// échoue à chaque fois, une VM qui démarre coupe une fois puis réussit.
//
// La raison journalisée est celle que la bibliothèque rend, jamais une
// interprétation : « certificat refusé » a longtemps été écrit là où l'erreur
// disait autre chose, et l'on cherchait une autorité manquante alors que la
// poignée de main échouait pour un motif sans rapport.
func (r *Refusals) Echec(host string, raison error) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	seuil := r.Seuil
	if seuil < 1 {
		seuil = SeuilParDefaut
	}
	alerte := estRefusTLS(raison)
	maintenant := r.maintenant()
	// Une rafale ne compte qu'une fois. Sans cela, un client qui ouvre
	// plusieurs connexions de front et ferme les inutiles atteint le seuil
	// seul : l'hôte passe en tunnel, le magasin cesse de le servir, et le
	// client qui attend sur ce tunnel n'a plus rien pour s'en sortir.
	if !alerte {
		if precedent, vu := r.dernier[host]; vu &&
			maintenant.Sub(precedent) < r.rafale() {
			return false
		}
		r.dernier[host] = maintenant
	}
	r.echecs[host]++
	if !alerte && r.echecs[host] < seuil {
		return false
	}
	if _, deja := r.apprises[host]; !deja {
		log.Printf(T("tunnel opaque retenu pour %s (%d échec(s)) : %v"),
			host, r.echecs[host], raison)
	}
	// La NATURE est retenue avec l'instant : elle décide si ce refus se
	// rouvrira. Un seuil atteint sur des coupures reste un soupçon, même
	// répété trois fois.
	r.apprises[host] = refus{quand: maintenant, alerte: alerte}
	return true
}

// maintenant rend l'instant courant, celui de l'horloge injectée s'il y en a.
func (r *Refusals) maintenant() time.Time {
	if r.Maintenant != nil {
		return r.Maintenant()
	}
	return time.Now()
}

// rafale rend la distance en deçà de laquelle deux coupures n'en font qu'une.
// Négative, elle les fait toutes compter.
func (r *Refusals) rafale() time.Duration {
	if r.Rafale != 0 {
		return r.Rafale
	}
	return RafaleParDefaut
}

// Reussite efface le compte d'un hôte : la coupure d'avant n'était qu'un
// incident, et deux incidents éloignés ne doivent pas s'additionner jusqu'au
// seuil.
func (r *Refusals) Reussite(host string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.echecs, host)
	delete(r.dernier, host)
}

func (r *Refusals) List() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]string, 0, len(r.declares)+len(r.apprises))
	for h := range r.declares {
		out = append(out, h)
	}
	for h, vu := range r.apprises {
		if !vu.alerte && r.Oubli > 0 && r.maintenant().Sub(vu.quand) >= r.Oubli {
			r.oublier(h)
			continue
		}
		out = append(out, h)
	}
	return out
}

// estRefusTLS dit si l'échec vient d'une DÉCISION du client.
//
// Le pair qui refuse envoie une alerte, que la bibliothèque rend comme une
// « remote error ». Tout le reste — coupure, fin de flux, délai — est du
// transport, et ne dit rien de ce que le client pense de notre autorité.
func estRefusTLS(err error) bool {
	if err == nil {
		return false
	}
	var alerte tls.AlertError
	if errors.As(err, &alerte) {
		return true
	}
	return strings.Contains(err.Error(), "remote error: tls:")
}

// TLSFront écoute le port vers lequel le 443 des invités est détourné.
type TLSFront struct {
	CA       *CA
	Proxy    *Proxy
	Refusals *Refusals
	// Origine rend la destination qu'avait la connexion avant le détournement.
	// Nulle, originalDst s'applique ; les tests la remplacent pour viser une
	// destination sans poser de règle de détournement.
	Origine func(net.Conn) (string, error)
}

// Serve accepte et traite chaque connexion détournée.
func (t *TLSFront) Serve(ln net.Listener) error {
	for {
		c, err := ln.Accept()
		if err != nil {
			return err
		}
		go t.handle(c)
	}
}

func (t *TLSFront) handle(c net.Conn) {
	defer c.Close()

	// Le premier enregistrement TLS est lu en entier avant toute décision :
	// il porte le SNI, donc le nom d'hôte, donc la réponse à « déchiffrer ou
	// laisser passer ». Ses octets sont rejoués ensuite, l'invité ne devant
	// pas s'apercevoir qu'on les a regardés.
	raw, err := readFirstRecord(c)
	if err != nil {
		return
	}
	host := ""
	if hello, err := peekSNI(raw); err == nil && hello.ServerName != "" {
		host = strings.ToLower(hello.ServerName)
	}
	peeked := &replayed{Conn: c, buf: bytes.NewBuffer(raw)}

	if host == "" || t.Refusals.Has(host) {
		// Sans SNI il n'y a pas de nom à certifier ; avec un refus connu il
		// n'y a rien à tenter. Les deux passent en tunnel vers la
		// destination que le noyau a gardée.
		//
		// Un tunnel dont l'amont ne répond pas ne peut que couper le client,
		// alors que le magasin détient peut-être ce qu'il demande. Rien n'a
		// encore été écrit vers le client, et le ClientHello est gardé : la
		// même connexion est alors déchiffrée. Un client qui refuse vraiment
		// notre autorité échoue de toute façon, l'amont étant coupé.
		if !t.tunnel(peeked, host) || host == "" {
			return
		}
	}

	cfg := &tls.Config{
		GetCertificate: func(chi *tls.ClientHelloInfo) (*tls.Certificate, error) {
			name := strings.ToLower(chi.ServerName)
			if name == "" {
				name = host
			}
			return t.CA.leafFor(name)
		},
		MinVersion: tls.VersionTLS12,
	}
	tc := tls.Server(peeked, cfg)
	if err := tc.Handshake(); err != nil {
		// Un REFUS et une COUPURE ne disent pas la même chose, et les
		// confondre coûte cher. Le client qui rejette notre autorité envoie
		// une alerte TLS : c'est une décision, et l'hôte doit passer en
		// tunnel. Une connexion coupée en cours de route — « connection reset
		// by peer », une fin de flux — n'est qu'un incident de transport, que
		// la requête suivante ne reproduira pas.
		//
		// Les traiter pareil condamnait un miroir de distribution au tunnel
		// sur une seule coupure, et tout son trafic repartait à l'amont.
		if !t.Refusals.Echec(host, err) {
			log.Printf(T("poignée de main interrompue pour %s : %v"), host, err)
		}
		return
	}
	t.Refusals.Reussite(host)
	defer tc.Close()

	// Chaque requête de la connexion est servie comme du HTTPS : le schéma
	// compte, l'URL stockée devant être celle que l'invité a demandée.
	serveConn(tc, t.Proxy.handler("https"))
}

// serveConn fait traiter une connexion DÉJÀ établie par le serveur HTTP de la
// bibliothèque standard, en la lui présentant comme un écouteur d'une seule
// connexion. Passer par « Serve » plutôt que par une lecture à la main donne
// gratuitement la persistance, le pipelining et les délais.
func serveConn(c net.Conn, h http.Handler) {
	srv := &http.Server{
		Handler:           h,
		ReadHeaderTimeout: 30 * time.Second,
	}
	// « Serve » traite chaque connexion dans une GOROUTINE puis reboucle sur
	// « Accept ». Un écouteur qui rendrait la fin de flux tout de suite ferait
	// donc rendre la main à « Serve » — et à l'appelant, dont le « defer
	// Close » couperait la connexion pendant que le handler y écrit encore :
	// le client reçoit « Empty reply from server », sans une ligne au journal.
	//
	// Le second « Accept » attend donc la fermeture de la connexion servie.
	srv.Serve(&oneConn{c: c, fini: make(chan struct{})})
}

// oneConn présente une connexion unique sous la forme d'un écouteur.
type oneConn struct {
	c    net.Conn
	fini chan struct{}
	pris bool
	mu   sync.Mutex
}

func (l *oneConn) Accept() (net.Conn, error) {
	l.mu.Lock()
	if l.pris {
		l.mu.Unlock()
		// La connexion est déjà partie : on attend qu'elle soit refermée
		// avant d'annoncer la fin, sans quoi « Serve » rendrait la main
		// pendant que la réponse s'écrit.
		<-l.fini
		return nil, io.EOF
	}
	l.pris = true
	l.mu.Unlock()
	return &connSignalee{Conn: l.c, fini: l.fini}, nil
}

func (l *oneConn) Close() error   { return nil }
func (l *oneConn) Addr() net.Addr { return l.c.LocalAddr() }

// connSignalee prévient l'écouteur de sa fermeture, qui est le seul moment où
// « Serve » peut rendre la main sans couper une réponse.
type connSignalee struct {
	net.Conn
	une  sync.Once
	fini chan struct{}
}

func (c *connSignalee) Close() error {
	err := c.Conn.Close()
	c.une.Do(func() { close(c.fini) })
	return err
}

// tunnel relie l'invité à sa destination sans rien comprendre à ce qui passe.
//
// Rend vrai quand l'établissement vers l'amont a échoué — refus, délai, réseau
// injoignable — et que rien n'a été écrit vers le client : la connexion reste
// alors utilisable par l'appelant. Faux dans tous les autres cas, connexion
// relayée ou abandonnée.
func (t *TLSFront) tunnel(c net.Conn, host string) bool {
	origine := t.Origine
	if origine == nil {
		origine = originalDst
	}
	dst, err := origine(c)
	if err != nil {
		log.Printf(T("tunnel impossible pour %q : destination inconnue (%v)"), host, err)
		return false
	}
	// Une connexion NON détournée — ouverte directement sur l'écoute — a pour
	// destination d'origine l'écoute elle-même. La relayer la renverrait ici,
	// où elle serait relayée de nouveau, sans fin : chaque tour ouvre une
	// connexion, jusqu'à épuiser les descripteurs et arrêter le service.
	if memeAdresse(dst, c.LocalAddr().String()) {
		log.Printf(T("tunnel refusé pour %q : connexion non détournée, sa"+
			" destination %s est cette écoute même"), host, dst)
		t.Proxy.record(accessLine{
			Method: "CONNECT", URL: "tcp://" + dst, Class: "tunnel",
			Outcome: OutcomeError, Status: http.StatusLoopDetected,
			Client: clientDe(c.RemoteAddr().String()),
		})
		return false
	}
	up, err := net.DialTimeout("tcp", dst, 10*time.Second)
	if err != nil {
		injoignable := estEchecDEtablissement(err)
		if injoignable && host != "" {
			log.Printf(T("tunnel vers %s : %v ; %s est déchiffré à la place"),
				dst, err, host)
		} else {
			log.Printf(T("tunnel vers %s : %v"), dst, err)
		}
		return injoignable
	}
	defer up.Close()

	t.Proxy.record(accessLine{
		Method: "CONNECT", URL: "tcp://" + dst, Class: "tunnel",
		Outcome: OutcomePassthrough, Upstream: true,
		Client: clientDe(c.RemoteAddr().String()),
	})

	// Un tunnel qui se referme ne laissait AUCUNE trace : le client qui
	// attendait dessus paraissait bloqué sans cause, et rien au journal ne
	// disait lequel des deux bouts s'était taire. La durée et les octets par
	// direction le disent — un tunnel qui meurt sans avoir rien rendu à
	// l'invité est l'empreinte d'un amont qui coupe.
	debut := time.Now()
	var versAmont, versClient atomic.Int64
	done := make(chan struct{}, 2)
	go func() {
		n, _ := io.Copy(up, c)
		versAmont.Store(n)
		done <- struct{}{}
	}()
	go func() {
		n, _ := io.Copy(c, up)
		versClient.Store(n)
		done <- struct{}{}
	}()
	<-done
	log.Printf(T("tunnel vers %s refermé après %s : %s vers l'amont, %s vers l'invité"),
		dst, time.Since(debut).Round(time.Second),
		HumanBytes(versAmont.Load()), HumanBytes(versClient.Load()))
	return false
}

// readFirstRecord lit l'en-tête de cinq octets d'un enregistrement TLS puis
// exactement la longueur qu'il annonce. Aucune heuristique : la taille est
// écrite dans le protocole.
func readFirstRecord(c net.Conn) ([]byte, error) {
	head := make([]byte, 5)
	if _, err := io.ReadFull(c, head); err != nil {
		return nil, err
	}
	if head[0] != 0x16 { // handshake
		return nil, fmt.Errorf(T("ce n'est pas une poignée de main TLS (type %d)"), head[0])
	}
	n := int(head[3])<<8 | int(head[4])
	if n <= 0 || n > 1<<16 {
		return nil, fmt.Errorf(T("longueur d'enregistrement invraisemblable : %d"), n)
	}
	body := make([]byte, n)
	if _, err := io.ReadFull(c, body); err != nil {
		return nil, err
	}
	return append(head, body...), nil
}

// peekSNI fait analyser le ClientHello par la bibliothèque standard plutôt
// que par un analyseur écrit à la main : le format a des extensions, des
// versions et des pièges, et un analyseur maison les découvrirait un par un.
func peekSNI(raw []byte) (*tls.ClientHelloInfo, error) {
	var hello *tls.ClientHelloInfo
	err := tls.Server(&readOnly{r: bytes.NewReader(raw)}, &tls.Config{
		GetConfigForClient: func(chi *tls.ClientHelloInfo) (*tls.Config, error) {
			clone := *chi
			hello = &clone
			return nil, nil
		},
	}).Handshake()
	if hello != nil {
		return hello, nil
	}
	return nil, err
}

// replayed rejoue les octets déjà lus avant de rendre la main à la
// connexion.
type replayed struct {
	net.Conn
	buf *bytes.Buffer
}

func (c *replayed) Read(p []byte) (int, error) {
	if c.buf.Len() > 0 {
		return c.buf.Read(p)
	}
	return c.Conn.Read(p)
}

// readOnly sert le ClientHello à l'analyseur et refuse d'écrire : la poignée
// de main s'arrête donc juste après l'analyse, ce qui est tout ce qu'on veut.
type readOnly struct {
	r io.Reader
}

var errNoWrite = errors.New("analyse seule")

func (c *readOnly) Read(p []byte) (int, error)       { return c.r.Read(p) }
func (c *readOnly) Write([]byte) (int, error)        { return 0, errNoWrite }
func (c *readOnly) Close() error                     { return nil }
func (c *readOnly) LocalAddr() net.Addr              { return dummyAddr{} }
func (c *readOnly) RemoteAddr() net.Addr             { return dummyAddr{} }
func (c *readOnly) SetDeadline(time.Time) error      { return nil }
func (c *readOnly) SetReadDeadline(time.Time) error  { return nil }
func (c *readOnly) SetWriteDeadline(time.Time) error { return nil }

type dummyAddr struct{}

func (dummyAddr) Network() string { return "peek" }
func (dummyAddr) String() string  { return "peek" }
