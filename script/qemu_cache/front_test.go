// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Le front TLS de bout en bout : un vrai client, une vraie poignée de main,
// une vraie réponse.
//
// Les autres tests appellent le proxy en direct et ne traversent jamais ce
// chemin. Il portait un défaut qu'aucun d'eux ne pouvait voir : « Serve »
// traite la connexion dans une goroutine puis reboucle sur « Accept », si
// bien qu'un écouteur rendant la fin de flux tout de suite faisait fermer la
// connexion pendant que la réponse s'écrivait. Le client recevait « Empty
// reply from server » et le journal ne disait rien, la requête n'étant jamais
// arrivée au bout.

// frontDeTest monte le front TLS devant un amont qui compte ses requêtes.
//
// L'amont parle TLS, comme un vrai miroir : le front étiquette « https » ce
// qui lui arrive, et un amont en clair ferait échouer la reprise. Et le
// composeur du proxy est détourné vers cet amont, parce que le SNI doit
// porter un NOM — un client qui se connecte à une adresse IP n'envoie aucun
// SNI, et le front n'aurait alors rien à certifier.
const HOTE_AMONT = "miroir.example"

func frontDeTest(t *testing.T, corps string) (*amont, string, *CA) {
	t.Helper()
	a := &amont{corps: corps}
	a.srv = httptest.NewTLSServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			atomic.AddInt64(&a.appel, 1)
			w.Header().Set("Content-Type", "application/octet-stream")
			io.WriteString(w, a.corps)
		}))
	t.Cleanup(a.srv.Close)

	alog, err := OpenAccessLog("")
	if err != nil {
		t.Fatalf("journal : %v", err)
	}
	proxy := NewProxy(&Store{Dir: t.TempDir()}, alog)
	tr := proxy.Client.Transport.(*http.Transport)
	cible := a.hote()
	tr.DialContext = func(ctx context.Context, reseau, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, reseau, cible)
	}
	// L'amont de test signe lui-même son certificat : le vérifier n'apprendrait
	// rien sur le cache, qui est ce qu'on mesure ici.
	tr.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}

	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	front := &TLSFront{CA: ca, Proxy: proxy, Refusals: NewRefusals(nil)}

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("écoute : %v", err)
	}
	t.Cleanup(func() { ln.Close() })
	go front.Serve(ln)
	return a, ln.Addr().String(), ca
}

// dialogueTLS fait UNE requête au front, en TLS, et rend la réponse.
func dialogueTLS(
	t *testing.T, ca *CA, ecoute, hoteAmont, chemin string,
) (*http.Response, string) {
	t.Helper()
	pool := x509.NewCertPool()
	pool.AddCert(ca.cert)

	brut, err := net.DialTimeout("tcp", ecoute, 5*time.Second)
	if err != nil {
		t.Fatalf("connexion : %v", err)
	}
	defer brut.Close()
	// Le SNI porte le nom de l'AMONT : c'est lui qui dit au front quel
	// certificat fabriquer et où aller chercher.
	tc := tls.Client(brut, &tls.Config{
		ServerName: hoteAmont,
		RootCAs:    pool,
	})
	tc.SetDeadline(time.Now().Add(15 * time.Second))
	if err := tc.Handshake(); err != nil {
		t.Fatalf("poignée de main : %v", err)
	}
	fmt.Fprintf(tc, "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n",
		chemin, hoteAmont)
	brutRep, err := io.ReadAll(tc)
	if err != nil && len(brutRep) == 0 {
		t.Fatalf("lecture : %v", err)
	}
	texte := string(brutRep)
	if texte == "" {
		t.Fatal("réponse vide : la connexion s'est fermée avant la réponse")
	}
	return nil, texte
}

// L'invariant que le défaut violait : une requête TLS reçoit sa réponse.
func TestFrontTLSRendUneReponse(t *testing.T) {
	a, ecoute, ca := frontDeTest(t, "contenu du paquet")

	_, rep := dialogueTLS(
		t, ca, ecoute, HOTE_AMONT,
		"/arch/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst",
	)
	if !strings.HasPrefix(rep, "HTTP/1.1 200") {
		t.Errorf("réponse inattendue :\n%s", rep[:min(len(rep), 200)])
	}
	if !strings.Contains(rep, "contenu du paquet") {
		t.Error("le corps de l'amont n'est pas parvenu au client")
	}
	if atomic.LoadInt64(&a.appel) != 1 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 1", a.appel)
	}
}

// Et la seconde demande vient du disque, sans toucher au réseau : le gain de
// l'outil doit exister À TRAVERS le front, pas seulement dans le proxy nu.
func TestFrontTLSSertDuCacheALaSeconde(t *testing.T) {
	a, ecoute, ca := frontDeTest(t, "contenu du paquet")
	chemin := "/arch/core/os/x86_64/git-2.51-1-x86_64.pkg.tar.zst"

	dialogueTLS(t, ca, ecoute, HOTE_AMONT, chemin)
	_, rep := dialogueTLS(t, ca, ecoute, HOTE_AMONT, chemin)

	if !strings.Contains(rep, "X-Erplibre-Cache: hit") &&
		!strings.Contains(rep, "X-ERPLibre-Cache: hit") {
		t.Errorf("la seconde demande n'a pas été servie du disque :\n%s",
			rep[:min(len(rep), 300)])
	}
	if n := atomic.LoadInt64(&a.appel); n != 1 {
		t.Errorf("l'amont a reçu %d requêtes, attendu 1", n)
	}
}

// Le certificat présenté doit porter le nom demandé, sinon le client le
// rejette avant même d'envoyer sa requête.
func TestFrontTLSPresenteLeBonNom(t *testing.T) {
	_, ecoute, ca := frontDeTest(t, "x")
	hote := HOTE_AMONT

	pool := x509.NewCertPool()
	pool.AddCert(ca.cert)
	brut, err := net.DialTimeout("tcp", ecoute, 5*time.Second)
	if err != nil {
		t.Fatalf("connexion : %v", err)
	}
	defer brut.Close()
	tc := tls.Client(brut, &tls.Config{ServerName: hote, RootCAs: pool})
	tc.SetDeadline(time.Now().Add(10 * time.Second))
	if err := tc.Handshake(); err != nil {
		t.Fatalf("poignée de main : %v", err)
	}
	vu := tc.ConnectionState().PeerCertificates[0]
	if vu.Subject.CommonName != hote {
		t.Errorf("certificat pour %q, attendu %q", vu.Subject.CommonName, hote)
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
