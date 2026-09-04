// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"fmt"
	"math/big"
	"net"
	"strings"
	"time"

	"github.com/pion/dtls/v3"
	"github.com/pion/rtp"
	"github.com/pion/srtp/v3"
)

// Le média d'un navigateur est chiffré, sans option : DTLS établit un secret,
// et SRTP s'en sert pour protéger chaque paquet RTP. Ce fichier tient les deux
// étapes qui suivent ICE.

const (
	// ÉtiquetteSRTP est celle que la RFC 5764 impose pour tirer les clés SRTP
	// du secret DTLS. Elle n'est pas configurable : les deux pairs dérivent
	// leurs clés du même secret, et le moindre écart donne des paquets que
	// l'autre jette sans rien dire.
	ÉtiquetteSRTP = "EXTRACTOR-dtls_srtp"

	// ValiditéCertificat borne la vie du certificat auto-signé.
	//
	// Il ne prouve aucune identité — c'est son EMPREINTE, publiée dans le SDP
	// par un canal déjà authentifié, qui joue ce rôle. Un an sert seulement à
	// ce qu'un processus qui ne redémarre jamais finisse par en changer.
	ValiditéCertificat = 365 * 24 * time.Hour

	// DélaiPoignéeDeMain borne l'établissement. Un navigateur qui a conclu
	// son ICE enchaîne en quelques dizaines de millisecondes ; au-delà de
	// quelques secondes, c'est que les paquets n'arrivent pas.
	DélaiPoignéeDeMain = 10 * time.Second
)

// NouveauCertificat tire un certificat auto-signé et rend son empreinte au
// format du SDP.
//
// ECDSA P-256 : c'est ce que tout navigateur accepte, et la courbe que les
// implémentations WebRTC utilisent entre elles.
func NouveauCertificat() (tls.Certificate, string, error) {
	clé, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, "", err
	}
	série, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return tls.Certificate{}, "", err
	}
	gabarit := x509.Certificate{
		SerialNumber: série,
		Subject:      pkix.Name{CommonName: "erplibre-sip-go"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(ValiditéCertificat),
	}
	brut, err := x509.CreateCertificate(rand.Reader, &gabarit, &gabarit,
		&clé.PublicKey, clé)
	if err != nil {
		return tls.Certificate{}, "", err
	}
	certificat := tls.Certificate{
		Certificate: [][]byte{brut},
		PrivateKey:  clé,
	}
	return certificat, EmpreinteSDP(brut), nil
}

// EmpreinteSDP rend « sha-256 AB:CD:... », tel que le SDP l'attend.
//
// L'empreinte porte sur le certificat DER, en majuscules, octets séparés par
// des deux-points : la RFC 8122 le prescrit, et un navigateur compare la
// chaîne telle quelle.
func EmpreinteSDP(certificatDER []byte) string {
	somme := sha256.Sum256(certificatDER)
	octets := make([]string, len(somme))
	for i, o := range somme {
		octets[i] = strings.ToUpper(hex.EncodeToString([]byte{o}))
	}
	return "sha-256 " + strings.Join(octets, ":")
}

// EmpreinteConcorde compare deux empreintes SDP sans se laisser arrêter par
// la casse ni par l'espacement.
//
// Vérification INDISPENSABLE : sans elle, n'importe qui capable d'atteindre
// le socket peut terminer la poignée de main avec son propre certificat, et
// le média part chez lui. Le SDP est le seul canal qui dise quel certificat
// attendre.
func EmpreinteConcorde(annoncée, présentée string) bool {
	normaliser := func(s string) string {
		return strings.ToUpper(strings.Join(strings.Fields(s), " "))
	}
	return normaliser(annoncée) == normaliser(présentée)
}

// SessionSRTP protège et déprotège les paquets d'un appel.
type SessionSRTP struct {
	sortant *srtp.Context
	entrant *srtp.Context
}

// ÉtablirDTLS mène la poignée de main en SERVEUR, puis tire les clés SRTP.
//
// Serveur parce que le SDP annonce « a=setup:passive » : le navigateur offre
// « actpass » et devient client. Les deux rôles ne sont pas symétriques pour
// SRTP — les clés du client et celles du serveur sortent du même secret mais
// dans un ordre fixe, et les intervertir donne un flux que l'autre jette.
func ÉtablirDTLS(ctx context.Context, socket net.PacketConn, pair net.Addr,
	certificat tls.Certificate, empreinteAnnoncée string) (*SessionSRTP, error) {

	conf := &dtls.Config{
		Certificates: []tls.Certificate{certificat},
		SRTPProtectionProfiles: []dtls.SRTPProtectionProfile{
			dtls.SRTP_AES128_CM_HMAC_SHA1_80,
		},
		// EXIGER un certificat du pair, et ne pas s'en remettre au defaut.
		//
		// Sans cette ligne le serveur n'en DEMANDE pas, le navigateur n'en
		// envoie pas, et le rappel de verification n'est jamais appele : la
		// poignee de main aboutit avec n'importe qui. En WebRTC les deux
		// bouts presentent toujours un certificat, exiger est donc conforme
		// autant que necessaire.
		ClientAuth: dtls.RequireAnyClientCert,
		// On vérifie l'empreinte nous-mêmes, contre celle du SDP : aucune
		// autorité de certification n'a de sens ici, les deux bouts
		// s'auto-signent.
		InsecureSkipVerify: true,
		VerifyPeerCertificate: func(chaînes [][]byte, _ [][]*x509.Certificate) error {
			if len(chaînes) == 0 {
				return fmt.Errorf("le pair n'a présenté aucun certificat")
			}
			présentée := EmpreinteSDP(chaînes[0])
			if !EmpreinteConcorde(empreinteAnnoncée, présentée) {
				return fmt.Errorf(
					"empreinte du pair differente de celle annoncee dans le SDP")
			}
			return nil
		},
	}

	// `Server` prepare la connexion sans rien echanger ; c'est
	// `HandshakeContext` qui parle au reseau, et lui seul accepte une borne
	// de temps. Lire directement apres `Server` bloquerait sans limite si le
	// navigateur ne repond jamais.
	conn, err := dtls.Server(socket, pair, conf)
	if err != nil {
		return nil, fmt.Errorf("preparation DTLS : %w", err)
	}
	minuté, arrêter := context.WithTimeout(ctx, DélaiPoignéeDeMain)
	defer arrêter()
	if err := conn.HandshakeContext(minuté); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("poignee de main DTLS : %w", err)
	}

	profil, ok := conn.SelectedSRTPProtectionProfile()
	if !ok {
		// Sans profil négocié il n'y a pas de clés à tirer, et le média ne
		// pourra pas être protégé : autant le dire ici.
		return nil, fmt.Errorf("aucun profil SRTP negocie")
	}
	return tirerLesClés(conn, profil)
}

// tirerLesClés découpe le matériel exporté selon la RFC 5764, §4.2.
//
// L'ordre est imposé et n'a rien d'arbitraire : clé client, clé serveur, sel
// client, sel serveur. En serveur, on chiffre avec la paire SERVEUR et on
// déchiffre avec la paire CLIENT.
func tirerLesClés(conn *dtls.Conn, profil dtls.SRTPProtectionProfile) (*SessionSRTP, error) {
	profilSRTP := srtp.ProtectionProfile(profil)
	tailleClé, err := profilSRTP.KeyLen()
	if err != nil {
		return nil, err
	}
	tailleSel, err := profilSRTP.SaltLen()
	if err != nil {
		return nil, err
	}

	état, ok := conn.ConnectionState()
	if !ok {
		return nil, fmt.Errorf("connexion DTLS sans etat exploitable")
	}
	matériel, err := état.ExportKeyingMaterial(
		ÉtiquetteSRTP, nil, tailleClé*2+tailleSel*2)
	if err != nil {
		return nil, fmt.Errorf("export du materiel de cle : %w", err)
	}
	décalage := 0
	prendre := func(n int) []byte {
		morceau := matériel[décalage : décalage+n]
		décalage += n
		return morceau
	}
	cléClient := prendre(tailleClé)
	cléServeur := prendre(tailleClé)
	selClient := prendre(tailleSel)
	selServeur := prendre(tailleSel)

	sortant, err := srtp.CreateContext(cléServeur, selServeur, profilSRTP)
	if err != nil {
		return nil, err
	}
	entrant, err := srtp.CreateContext(cléClient, selClient, profilSRTP)
	if err != nil {
		return nil, err
	}
	return &SessionSRTP{sortant: sortant, entrant: entrant}, nil
}

// Protéger chiffre un paquet RTP pour le navigateur.
func (s *SessionSRTP) Protéger(paquet []byte) ([]byte, error) {
	var entête rtp.Header
	if _, err := entête.Unmarshal(paquet); err != nil {
		return nil, err
	}
	return s.sortant.EncryptRTP(nil, paquet, &entête)
}

// Déprotéger déchiffre un paquet venu du navigateur.
func (s *SessionSRTP) Déprotéger(paquet []byte) ([]byte, error) {
	var entête rtp.Header
	if _, err := entête.Unmarshal(paquet); err != nil {
		return nil, err
	}
	return s.entrant.DecryptRTP(nil, paquet, &entête)
}
