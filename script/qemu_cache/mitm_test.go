// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestCreationEtRelectureDeLAutorite(t *testing.T) {
	dir := t.TempDir()
	ca1, err := LoadOrCreateCA(dir)
	if err != nil {
		t.Fatalf("création : %v", err)
	}
	// Relire ne doit PAS régénérer : une autorité neuve invaliderait les
	// certificats de toutes les VM déjà configurées.
	ca2, err := LoadOrCreateCA(dir)
	if err != nil {
		t.Fatalf("relecture : %v", err)
	}
	if ca1.Fingerprint() != ca2.Fingerprint() {
		t.Errorf("l'autorité a été régénérée :\n  %s\n  %s",
			ca1.Fingerprint(), ca2.Fingerprint())
	}
	if !ca1.cert.IsCA {
		t.Error("le certificat n'est pas une autorité")
	}
}

// La clé permet de se faire passer pour n'importe quel site auprès d'une VM
// qui approuve l'autorité : elle ne doit être lisible que par son
// propriétaire.
func TestCleDeLAutoriteEnMode0600(t *testing.T) {
	dir := t.TempDir()
	if _, err := LoadOrCreateCA(dir); err != nil {
		t.Fatalf("création : %v", err)
	}
	st, err := os.Stat(filepath.Join(dir, "ca.key"))
	if err != nil {
		t.Fatalf("clé absente : %v", err)
	}
	if mode := st.Mode().Perm(); mode != 0o600 {
		t.Errorf("clé en %o, attendu 600", mode)
	}
	// Le certificat, lui, part dans les VM : il doit rester lisible.
	stc, err := os.Stat(CertPath(dir))
	if err != nil {
		t.Fatalf("certificat absent : %v", err)
	}
	if mode := stc.Mode().Perm(); mode != 0o644 {
		t.Errorf("certificat en %o, attendu 644", mode)
	}
}

// Une feuille doit se vérifier CONTRE l'autorité, sans quoi l'invité la
// rejette malgré la confiance accordée.
func TestFeuilleVerifieeParLAutorite(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	crt, err := ca.leafFor("miroir.example")
	if err != nil {
		t.Fatalf("feuille : %v", err)
	}
	leaf, err := x509.ParseCertificate(crt.Certificate[0])
	if err != nil {
		t.Fatalf("feuille illisible : %v", err)
	}

	pool := x509.NewCertPool()
	pool.AddCert(ca.cert)
	if _, err := leaf.Verify(x509.VerifyOptions{
		DNSName: "miroir.example",
		Roots:   pool,
	}); err != nil {
		t.Errorf("la feuille ne se vérifie pas : %v", err)
	}

	// La chaîne envoyée porte l'autorité après la feuille : un invité qui ne
	// la connaît pas encore doit pouvoir la voir.
	if len(crt.Certificate) != 2 {
		t.Errorf("la chaîne porte %d certificats, attendu 2", len(crt.Certificate))
	}
}

// Un hôte demandé deux fois ne coûte qu'une génération : une installation
// touche des dizaines d'hôtes.
func TestFeuilleGardeeEnMemoire(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	a, _ := ca.leafFor("miroir.example")
	b, _ := ca.leafFor("miroir.example")
	if a != b {
		t.Error("la feuille est régénérée à chaque demande")
	}
}

// Un SNI qui est une adresse IP ne peut pas aller dans un nom DNS.
func TestFeuillePourUneAdresseIP(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	crt, err := ca.leafFor("192.168.122.50")
	if err != nil {
		t.Fatalf("feuille : %v", err)
	}
	leaf, _ := x509.ParseCertificate(crt.Certificate[0])
	if len(leaf.IPAddresses) != 1 {
		t.Errorf("%d adresse(s) dans le certificat, attendu 1", len(leaf.IPAddresses))
	}
	if len(leaf.DNSNames) != 0 {
		t.Errorf("une adresse IP est passée en nom DNS : %v", leaf.DNSNames)
	}
}

// errRefus est l'alerte qu'envoie un client qui a REGARDÉ notre certificat.
var errRefus = errors.New("remote error: tls: unknown certificate authority")

// Le repli ne se déclare pas d'avance : un hôte qui refuse le certificat est
// retenu, et la requête suivante vers lui n'essaie plus de le déchiffrer.
func TestRefusRetenu(t *testing.T) {
	r := NewRefusals(nil)
	if r.Has("api.example") {
		t.Fatal("un hôte est exclu avant tout refus")
	}
	r.Echec("api.example", errRefus)
	if !r.Has("api.example") {
		t.Error("le refus n'est pas retenu")
	}
	// Deux fois le même hôte ne double pas l'entrée.
	r.Echec("api.example", errRefus)
	if n := len(r.List()); n != 1 {
		t.Errorf("%d hôtes retenus, attendu 1", n)
	}
}

// Un suffixe couvre un domaine entier, sous-domaines compris.
func TestExclusionParSuffixe(t *testing.T) {
	r := NewRefusals([]string{".snapcraft.io"})
	for _, h := range []string{"api.snapcraft.io", "dashboard.snapcraft.io"} {
		if !r.Has(h) {
			t.Errorf("%s n'est pas couvert par le suffixe", h)
		}
	}
	if r.Has("snapcraft.io.example.com") {
		t.Error("le suffixe attrape un domaine qui ne fait que le contenir")
	}
}

// Les hôtes dont l'épinglage est connu d'avance évitent de perdre une requête
// pour l'apprendre.
func TestExclusionsParDefaut(t *testing.T) {
	r := NewRefusals(DefaultExclusions)
	if !r.Has("api.snapcraft.io") {
		t.Error("snapd n'est pas exclu d'avance, alors qu'il épingle")
	}
}

// La casse d'un nom d'hôte n'a pas de sens en DNS.
func TestExclusionInsensibleALaCasse(t *testing.T) {
	r := NewRefusals([]string{"API.Example"})
	if !r.Has("api.example") {
		t.Error("l'exclusion dépend de la casse")
	}
}

// L'empreinte sert à vérifier de visu qu'une VM approuve BIEN cette autorité.
func TestEmpreinteLisible(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	fp := ca.Fingerprint()
	if n := strings.Count(fp, ":"); n != 31 {
		t.Errorf("%d séparateurs, attendu 31 pour un SHA-256", n)
	}
	if fp != strings.ToUpper(fp) {
		t.Errorf("empreinte en minuscules : %s", fp)
	}
}

// Un premier enregistrement qui n'est pas une poignée de main TLS est refusé
// tôt : le port du 443 détourné ne reçoit rien d'autre.
func TestPremierEnregistrementNonTLS(t *testing.T) {
	if _, err := peekSNI([]byte{0x17, 0x03, 0x03, 0x00, 0x01, 0x00}); err == nil {
		t.Error("un enregistrement qui n'est pas un handshake est accepté")
	}
}

// Une coupure isolée ne condamne pas ; une coupure QUI SE RÉPÈTE, oui.
//
// Les deux se ressemblent au serveur : npm rejette notre certificat sans
// envoyer d'alerte, si bien qu'on ne voit qu'un EOF — exactement ce que
// produit une VM qui démarre et coupe. Seule la répétition les sépare.
func TestUneCoupureIsoleeNeCondamnePas(t *testing.T) {
	r := NewRefusals(nil)
	coupure := errors.New("read: connection reset by peer")
	for i := 1; i < r.Seuil; i++ {
		if r.Echec("miroir.example", coupure) {
			t.Fatalf("condamné dès l'échec %d, seuil %d", i, r.Seuil)
		}
	}
	if r.Has("miroir.example") {
		t.Error("condamné avant le seuil")
	}
}

func TestUneCoupureRepeteeFinitParCondamner(t *testing.T) {
	r := NewRefusals(nil)
	coupure := errors.New("EOF")
	for i := 0; i < r.Seuil; i++ {
		r.Echec("npm.example", coupure)
	}
	if !r.Has("npm.example") {
		t.Error("un client qui échoue à chaque fois n'est jamais mis en" +
			" tunnel : son installation s'arrêtera là")
	}
}

// Un soupçon se rouvre ; une décision, jamais.
//
// Trois coupures de suite condamnent l'hôte, et c'est voulu — mais elles ne
// disent rien de ce que le client pense de notre autorité. Le garder banni
// pour toujours prive le cache de tout ce qu'il détient pour lui : un tunnel
// recopie des octets sans consulter le magasin. Un miroir de distribution
// banni sur une rafale de flux corrompus renvoie alors à l'amont jusqu'à ce
// qui est en réserve.
func TestUnRefusDeTransportSeRouvre(t *testing.T) {
	r := NewRefusals(nil)
	r.Oubli = 50 * time.Millisecond
	coupure := errors.New("local error: tls: bad record MAC")
	for i := 0; i < r.Seuil; i++ {
		r.Echec("miroir.example", coupure)
	}
	if !r.Has("miroir.example") {
		t.Fatal("le seuil ne condamne plus")
	}
	time.Sleep(60 * time.Millisecond)
	if r.Has("miroir.example") {
		t.Error("un soupçon de transport ne se rouvre jamais")
	}
	if slices.Contains(r.List(), "miroir.example") {
		t.Error("un refus expiré figure encore dans la liste")
	}
}

// Une ALERTE ne se rouvre pas, quel que soit le réglage d'oubli : le client a
// REGARDÉ notre certificat. Le ré-intercepter ferait échouer de nouveau
// l'installation qui le traverse.
func TestUneAlerteNeSeRouvreJamais(t *testing.T) {
	r := NewRefusals(nil)
	r.Oubli = time.Millisecond
	r.Echec("epingleur.example", errRefus)
	time.Sleep(10 * time.Millisecond)
	if !r.Has("epingleur.example") {
		t.Error("une décision du client a été oubliée")
	}
	if !slices.Contains(r.List(), "epingleur.example") {
		t.Error("une alerte a disparu de la liste")
	}
}

// Le défaut n'est plus « jamais » : sans lui, une rafale condamne un hôte
// jusqu'au redémarrage du service.
func TestLOubliEstActifParDefaut(t *testing.T) {
	if NewRefusals(nil).Oubli <= 0 {
		t.Error("un refus de transport ne se rouvre jamais par défaut")
	}
}

// Une réussite efface le compte : deux incidents éloignés ne doivent pas
// s'additionner jusqu'au seuil.
func TestUneReussiteEffaceLeCompte(t *testing.T) {
	r := NewRefusals(nil)
	coupure := errors.New("EOF")
	for i := 1; i < r.Seuil; i++ {
		r.Echec("h.example", coupure)
	}
	r.Reussite("h.example")
	for i := 1; i < r.Seuil; i++ {
		r.Echec("h.example", coupure)
	}
	if r.Has("h.example") {
		t.Error("des incidents éloignés se sont additionnés")
	}
}

// Une ALERTE tranche tout de suite : le client a REGARDÉ notre certificat.
func TestUneAlerteCondamneDesLePremierEchec(t *testing.T) {
	r := NewRefusals(nil)
	if !r.Echec("epingleur.example", errors.New("remote error: tls: bad certificate")) {
		t.Error("une alerte n'est pas retenue immédiatement")
	}
}

// Un REFUS et une COUPURE ne disent pas la même chose.
//
// Le code les confondait : « connection reset by peer » était journalisé
// « certificat refusé » et faisait passer l'hôte en tunnel opaque. Un miroir
// de distribution se retrouve alors soustrait au cache sur une seule coupure,
// et tout son trafic repart à l'amont.
func TestUneCoupureNestPasUnRefus(t *testing.T) {
	coupures := []error{
		errors.New("read tcp 10.0.0.1:8899->10.0.0.2:33918: read:" +
			" connection reset by peer"),
		io.EOF,
		errors.New("read tcp: i/o timeout"),
		nil,
	}
	for _, err := range coupures {
		if estRefusTLS(err) {
			t.Errorf("%v pris pour un refus du client", err)
		}
	}
}

func TestUneAlerteEstUnRefus(t *testing.T) {
	refus := []error{
		errors.New("remote error: tls: bad certificate"),
		errors.New("remote error: tls: unknown certificate authority"),
		tls.AlertError(42),
	}
	for _, err := range refus {
		if !estRefusTLS(err) {
			t.Errorf("%v n'est pas reconnu comme un refus", err)
		}
	}
}

// L'erreur enveloppée compte autant : la bibliothèque en emballe parfois.
func TestUnRefusEnveloppeEstReconnu(t *testing.T) {
	err := fmt.Errorf("poignée de main : %w", tls.AlertError(48))
	if !estRefusTLS(err) {
		t.Error("un refus enveloppé n'est pas reconnu")
	}
}

// clientHelloBrut fabrique un ClientHello valide portant ce nom, sans rien
// engager : les octets sont capturés sur un tuyau, puis rejoués à la main.
func clientHelloBrut(t *testing.T, nom string) []byte {
	t.Helper()
	a, b := net.Pipe()
	defer a.Close()
	go func() {
		tc := tls.Client(a, &tls.Config{ServerName: nom})
		_ = tc.Handshake()
	}()
	b.SetReadDeadline(time.Now().Add(2 * time.Second))
	brut, err := readFirstRecord(b)
	b.Close()
	if err != nil {
		t.Fatalf("ClientHello : %v", err)
	}
	return brut
}

// Le contrôle précédent vérifie la RÈGLE ; celui-ci vérifie qu'elle est
// branchée. Sans lui, remettre les deux cas dans le même sac laisse les tests
// verts et recondamne un miroir au tunnel dès la première coupure.
func TestUneCoupureNeCondamnePasLHote(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	refus := NewRefusals(nil)
	front := &TLSFront{CA: ca, Refusals: refus, Proxy: proxyDeTest(t)}
	hello := clientHelloBrut(t, "miroir.example")

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	fini := make(chan struct{})
	go func() {
		if c, err := ln.Accept(); err == nil {
			front.handle(c)
		}
		close(fini)
	}()

	c, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	// Le ClientHello part, puis la connexion est coupée BRUTALEMENT : c'est
	// la coupure de transport que le code prenait pour un rejet d'autorité.
	// Aucune alerte n'est émise — ce serait l'autre cas.
	if _, err := c.Write(hello); err != nil {
		t.Fatal(err)
	}
	c.(*net.TCPConn).SetLinger(0)
	c.Close()

	select {
	case <-fini:
	case <-time.After(3 * time.Second):
		t.Fatal("la connexion n'a pas été traitée")
	}
	if refus.Has("miroir.example") {
		t.Error("une coupure a condamné l'hôte au tunnel opaque")
	}
}
