// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"net"
	"strings"
	"sync"

	"github.com/pion/stun/v3"
)

// Un navigateur ne parle jamais RTP directement : il fait d'abord de l'ICE,
// puis DTLS, et le média ne circule qu'ensuite — le tout sur UN SEUL socket.
// Ce fichier tient la première des trois étapes.
//
// ICE-LITE et non ICE complet, et c'est le bon choix ici : l'agent allégé ne
// rassemble aucun candidat et n'envoie aucune vérification. Il publie son
// adresse, répond aux requêtes de l'autre, et laisse le navigateur mener. La
// RFC 8445 le réserve aux hôtes joignables directement, ce qui est le cas
// d'un programme qui écoute sur la machine où tourne le navigateur.

const (
	// LongueurUfrag et LongueurMotDePasse : minimums de la RFC 8445, §5.2.1.
	// On prend de la marge plutôt que le minimum — ces deux valeurs sont ce
	// qui empêche un tiers de détourner la session média.
	LongueurUfrag      = 8
	LongueurMotDePasse = 24
)

// NatureDuPaquet dit ce qui arrive sur le socket média.
type NatureDuPaquet int

const (
	PaquetInconnu NatureDuPaquet = iota
	PaquetSTUN
	PaquetDTLS
	PaquetRTP
	PaquetRTCP
)

// EstRTCP distingue le compte rendu du son, sur un port qu'ils partagent.
//
// « a=rtcp-mux » fait passer les deux par le même socket, et leur premier
// octet est identique — version 2, donc 128 à 191. C'est le SECOND octet qui
// tranche : la RFC 5761 §4 réserve les types 64 à 95 au RTCP, précisément
// pour que le tri reste possible.
//
// Sans cette distinction, un compte rendu passe au déchiffrement RTP, qui le
// refuse par « failed to verify auth tag ». Un tel message une fois par
// seconde ressemble à une clé fausse, et masquerait un vrai défaut de clé le
// jour où il s'en produirait un.
func EstRTCP(paquet []byte) bool {
	if len(paquet) < 2 {
		return false
	}
	type_ := paquet[1] & 0x7F
	return type_ >= 64 && type_ <= 95
}

// Nature démultiplexe les trois protocoles qui partagent le socket média.
//
// Le premier octet suffit, et c'est la RFC 7983 qui le garantit : les valeurs
// ont été choisies pour ne pas se recouvrir. Sans ce tri, une poignée de main
// DTLS finirait dans le décodeur RTP, qui la jetterait en silence — et l'appel
// resterait muet sans que rien n'explique pourquoi.
func Nature(paquet []byte) NatureDuPaquet {
	if len(paquet) == 0 {
		return PaquetInconnu
	}
	switch premier := paquet[0]; {
	case premier <= 3:
		return PaquetSTUN
	case premier >= 20 && premier <= 63:
		return PaquetDTLS
	case premier >= 128 && premier <= 191:
		if EstRTCP(paquet) {
			return PaquetRTCP
		}
		return PaquetRTP
	default:
		return PaquetInconnu
	}
}

// IdentitéICE est le couple que les deux pairs s'échangent par le SDP.
type IdentitéICE struct {
	Ufrag      string
	MotDePasse string
}

// NouvelleIdentitéICE tire une identité au hasard.
//
// Un mot de passe deviné laisse un tiers répondre aux vérifications à notre
// place et détourner le média : il vient donc du générateur cryptographique,
// jamais d'un compteur ni de l'horloge.
func NouvelleIdentitéICE() (IdentitéICE, error) {
	ufrag, err := chaîneAléatoire(LongueurUfrag)
	if err != nil {
		return IdentitéICE{}, err
	}
	motDePasse, err := chaîneAléatoire(LongueurMotDePasse)
	if err != nil {
		return IdentitéICE{}, err
	}
	return IdentitéICE{Ufrag: ufrag, MotDePasse: motDePasse}, nil
}

// chaîneAléatoire rend n caractères pris dans l'alphabet que la RFC 8445
// autorise pour ces champs : base64 « URL », sans le remplissage.
func chaîneAléatoire(n int) (string, error) {
	brut := make([]byte, n)
	if _, err := rand.Read(brut); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(brut)[:n], nil
}

// AgentICELite répond aux vérifications de connectivité, et rien de plus.
//
// Il apprend l'adresse du pair de la PREMIÈRE requête valide : c'est la seule
// façon de savoir où envoyer le média. Un navigateur derrière un NAT présente
// une adresse que son SDP n'annonçait pas, et croire le SDP enverrait le son
// dans le vide.
type AgentICELite struct {
	Locale   IdentitéICE
	Distante IdentitéICE

	mutex sync.Mutex
	pair  net.Addr
}

// Pair rend l'adresse d'où est venue la dernière vérification valide, ou nil.
func (a *AgentICELite) Pair() net.Addr {
	a.mutex.Lock()
	defer a.mutex.Unlock()
	return a.pair
}

// Répondre traite une requête STUN et rend la réponse à renvoyer.
//
// Rend (nil, nil) quand il n'y a rien à répondre : un paquet qui n'est pas une
// requête de liaison, ou dont l'intégrité ne tient pas. Le silence est
// VOULU — répondre à une requête mal signée apprendrait à qui sonde que
// l'adresse porte un agent ICE, et lui dirait quel champ corriger.
func (a *AgentICELite) Répondre(paquet []byte, source net.Addr) ([]byte, error) {
	message := &stun.Message{Raw: append([]byte(nil), paquet...)}
	if err := message.Decode(); err != nil {
		return nil, nil
	}
	if message.Type != stun.BindingRequest {
		return nil, nil
	}

	// L'ordre compte : le nom d'utilisateur dit à qui la requête s'adresse,
	// et l'intégrité prouve que l'émetteur connaît le mot de passe. Vérifier
	// l'intégrité d'abord ferait travailler le HMAC pour des paquets qui ne
	// nous concernent pas.
	var utilisateur stun.Username
	if err := utilisateur.GetFrom(message); err != nil {
		return nil, nil
	}
	if !a.nomAttendu(string(utilisateur)) {
		return nil, nil
	}
	intégrité := stun.NewShortTermIntegrity(a.Locale.MotDePasse)
	if err := intégrité.Check(message); err != nil {
		return nil, nil
	}

	adresse, err := adresseUDP(source)
	if err != nil {
		return nil, err
	}
	réponse, err := stun.Build(
		stun.NewTransactionIDSetter(message.TransactionID),
		stun.BindingSuccess,
		&stun.XORMappedAddress{IP: adresse.IP, Port: adresse.Port},
		intégrité,
		stun.Fingerprint,
	)
	if err != nil {
		return nil, err
	}

	a.mutex.Lock()
	a.pair = source
	a.mutex.Unlock()
	return réponse.Raw, nil
}

// nomAttendu vérifie que la requête nous est bien destinée.
//
// La RFC 8445 impose « <ufrag du destinataire>:<ufrag de l'émetteur> ». On
// n'exige la seconde moitié que si l'on connaît déjà celle du pair : le
// navigateur envoie parfois sa première vérification avant que sa réponse SDP
// nous soit parvenue.
func (a *AgentICELite) nomAttendu(nom string) bool {
	destinataire, émetteur, coupé := strings.Cut(nom, ":")
	if !coupé || destinataire != a.Locale.Ufrag {
		return false
	}
	if a.Distante.Ufrag == "" {
		return true
	}
	return émetteur == a.Distante.Ufrag
}

func adresseUDP(source net.Addr) (*net.UDPAddr, error) {
	if udp, ok := source.(*net.UDPAddr); ok {
		return udp, nil
	}
	return nil, fmt.Errorf("adresse non UDP : %T", source)
}
