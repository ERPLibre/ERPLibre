package main

import (
	"context"
	"crypto/tls"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/pion/dtls/v3"
	"github.com/pion/rtp"
	"github.com/pion/srtp/v3"
)

// La RFC 8122 fixe la forme, et un navigateur compare la chaine telle quelle.
func TestLEmpreinteSuitLeFormatDuSDP(t *testing.T) {
	_, empreinte, err := NouveauCertificat()
	if err != nil {
		t.Fatalf("certificat : %v", err)
	}
	algo, valeur, coupé := strings.Cut(empreinte, " ")
	if !coupé || algo != "sha-256" {
		t.Fatalf("prefixe inattendu : %q", empreinte)
	}
	octets := strings.Split(valeur, ":")
	if len(octets) != 32 {
		t.Fatalf("%d octets au lieu de 32", len(octets))
	}
	for _, o := range octets {
		if len(o) != 2 || strings.ToUpper(o) != o {
			t.Fatalf("octet mal forme : %q", o)
		}
	}
}

func TestDeuxCertificatsOntDesEmpreintesDifferentes(t *testing.T) {
	_, une, _ := NouveauCertificat()
	_, deux, _ := NouveauCertificat()
	if une == deux {
		t.Fatal("deux certificats partagent une empreinte")
	}
}

func TestLaComparaisonDEmpreinteToleraLaMiseEnForme(t *testing.T) {
	if !EmpreinteConcorde("sha-256 AA:BB:CC", "SHA-256   aa:bb:cc") {
		t.Fatal("la meme empreinte est declaree differente")
	}
	if EmpreinteConcorde("sha-256 AA:BB:CC", "sha-256 AA:BB:CD") {
		t.Fatal("deux empreintes differentes sont declarees egales")
	}
}

// Les cles du client et du serveur sortent du meme secret DANS UN ORDRE
// FIXE. Les intervertir donne un flux que l'autre jette sans rien dire, et
// c'est exactement le defaut qui se presente comme un appel muet.
func clésMiroir(t *testing.T, conn *dtls.Conn) (*srtp.Context, *srtp.Context) {
	t.Helper()
	profil, ok := conn.SelectedSRTPProtectionProfile()
	if !ok {
		t.Fatal("aucun profil SRTP negocie cote client")
	}
	profilSRTP := srtp.ProtectionProfile(profil)
	tailleClé, _ := profilSRTP.KeyLen()
	tailleSel, _ := profilSRTP.SaltLen()
	état, ok := conn.ConnectionState()
	if !ok {
		t.Fatal("etat DTLS indisponible cote client")
	}
	matériel, err := état.ExportKeyingMaterial(
		ÉtiquetteSRTP, nil, tailleClé*2+tailleSel*2)
	if err != nil {
		t.Fatalf("export cote client : %v", err)
	}
	cléClient := matériel[:tailleClé]
	cléServeur := matériel[tailleClé : tailleClé*2]
	selClient := matériel[tailleClé*2 : tailleClé*2+tailleSel]
	selServeur := matériel[tailleClé*2+tailleSel:]

	// En CLIENT, on chiffre avec la paire client et on dechiffre avec celle
	// du serveur : l'inverse exact de ce que fait `tirerLesClés`.
	sortant, err := srtp.CreateContext(cléClient, selClient, profilSRTP)
	if err != nil {
		t.Fatalf("contexte sortant : %v", err)
	}
	entrant, err := srtp.CreateContext(cléServeur, selServeur, profilSRTP)
	if err != nil {
		t.Fatalf("contexte entrant : %v", err)
	}
	return sortant, entrant
}

func paquetRTP(t *testing.T, charge []byte) []byte {
	t.Helper()
	paquet := &rtp.Packet{
		Header:  rtp.Header{Version: 2, PayloadType: ChargePCMU, SequenceNumber: 7, Timestamp: 160, SSRC: 0x1234},
		Payload: charge,
	}
	brut, err := paquet.Marshal()
	if err != nil {
		t.Fatalf("paquet RTP : %v", err)
	}
	return brut
}

// L'epreuve de l'etage : une vraie poignee de main sur de vraies sockets, et
// le son protege d'un cote se relit de l'autre. C'est ce qui prouve que
// l'ordre des cles est le bon.
func TestUnePoigneeDeMainAboutitEtProtegeLeSon(t *testing.T) {
	serveurSock, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("socket serveur : %v", err)
	}
	defer serveurSock.Close()
	clientSock, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("socket client : %v", err)
	}
	defer clientSock.Close()

	certServeur, empreinteServeur, err := NouveauCertificat()
	if err != nil {
		t.Fatalf("certificat serveur : %v", err)
	}
	certClient, empreinteClient, err := NouveauCertificat()
	if err != nil {
		t.Fatalf("certificat client : %v", err)
	}

	ctx, arrêter := context.WithTimeout(context.Background(), 20*time.Second)
	defer arrêter()

	type issue struct {
		session *SessionSRTP
		err     error
	}
	côtéServeur := make(chan issue, 1)
	go func() {
		session, err := ÉtablirDTLS(ctx, serveurSock, clientSock.LocalAddr(),
			certServeur, empreinteClient)
		côtéServeur <- issue{session, err}
	}()

	conf := &dtls.Config{
		Certificates:           []tls.Certificate{certClient},
		SRTPProtectionProfiles: []dtls.SRTPProtectionProfile{dtls.SRTP_AES128_CM_HMAC_SHA1_80},
		InsecureSkipVerify:     true,
	}
	conn, err := dtls.Client(clientSock, serveurSock.LocalAddr(), conf)
	if err != nil {
		t.Fatalf("preparation client : %v", err)
	}
	defer conn.Close()
	if err := conn.HandshakeContext(ctx); err != nil {
		t.Fatalf("poignee de main cote client : %v", err)
	}

	résultat := <-côtéServeur
	if résultat.err != nil {
		t.Fatalf("poignee de main cote serveur : %v", résultat.err)
	}
	_ = empreinteServeur

	// Serveur -> client : ce que l'un protege, l'autre doit le relire.
	charge := []byte{0xFF, 0xFE, 0xFD, 0xFC, 0xFB, 0xFA, 0xF9, 0xF8}
	clair := paquetRTP(t, charge)
	protégé, err := résultat.session.Protéger(clair)
	if err != nil {
		t.Fatalf("protection : %v", err)
	}
	if len(protégé) <= len(clair) {
		t.Fatal("le paquet protege n'est pas plus long : rien n'a ete signe")
	}

	_, entrantClient := clésMiroir(t, conn)
	var entête rtp.Header
	if _, err := entête.Unmarshal(protégé); err != nil {
		t.Fatalf("entete illisible : %v", err)
	}
	relu, err := entrantClient.DecryptRTP(nil, protégé, &entête)
	if err != nil {
		t.Fatalf("le client ne relit pas ce que le serveur a protege : %v", err)
	}
	var paquet rtp.Packet
	if err := paquet.Unmarshal(relu); err != nil {
		t.Fatalf("paquet relu illisible : %v", err)
	}
	if string(paquet.Payload) != string(charge) {
		t.Fatalf("charge alteree : %v", paquet.Payload)
	}
}

// Sans cette verification, quiconque atteint le socket termine la poignee de
// main avec son propre certificat, et le media part chez lui.
func TestUnCertificatQuiNeCorrespondPasAuSDPEstRefuse(t *testing.T) {
	serveurSock, _ := net.ListenPacket("udp", "127.0.0.1:0")
	defer serveurSock.Close()
	clientSock, _ := net.ListenPacket("udp", "127.0.0.1:0")
	defer clientSock.Close()

	certServeur, _, _ := NouveauCertificat()
	certClient, _, _ := NouveauCertificat()
	_, empreinteEtrangere, _ := NouveauCertificat()

	ctx, arrêter := context.WithTimeout(context.Background(), 20*time.Second)
	defer arrêter()

	erreurs := make(chan error, 1)
	go func() {
		_, err := ÉtablirDTLS(ctx, serveurSock, clientSock.LocalAddr(),
			certServeur, empreinteEtrangere)
		erreurs <- err
	}()

	conf := &dtls.Config{
		Certificates:           []tls.Certificate{certClient},
		SRTPProtectionProfiles: []dtls.SRTPProtectionProfile{dtls.SRTP_AES128_CM_HMAC_SHA1_80},
		InsecureSkipVerify:     true,
	}
	if conn, err := dtls.Client(clientSock, serveurSock.LocalAddr(), conf); err == nil {
		_ = conn.HandshakeContext(ctx)
		defer conn.Close()
	}

	select {
	case err := <-erreurs:
		if err == nil {
			t.Fatal("poignee de main acceptee avec un certificat etranger")
		}
	case <-ctx.Done():
		t.Fatal("le serveur n'a jamais conclu")
	}
}
