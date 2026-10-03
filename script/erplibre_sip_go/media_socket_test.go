package main

import (
	"context"
	"errors"
	"net"
	"os"
	"testing"
	"time"

	"github.com/pion/stun/v3"
)

func socketDEssai(t *testing.T) (*SocketMédia, *AgentICELite, *net.UDPConn) {
	t.Helper()
	locale, err := NouvelleIdentitéICE()
	if err != nil {
		t.Fatalf("identité : %v", err)
	}
	agent := &AgentICELite{Locale: locale}
	socket, err := NouveauSocketMédia("127.0.0.1:0", agent)
	if err != nil {
		t.Fatalf("socket : %v", err)
	}
	t.Cleanup(func() { _ = socket.Fermer() })

	pair, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatalf("socket du pair : %v", err)
	}
	t.Cleanup(func() { _ = pair.Close() })

	ctx, arrêter := context.WithCancel(context.Background())
	t.Cleanup(arrêter)
	go func() { _ = socket.Trier(ctx) }()
	return socket, agent, pair
}

func destination(t *testing.T, s *SocketMédia) *net.UDPAddr {
	t.Helper()
	return &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: s.Port()}
}

// La vérification ICE se répond dans la boucle même : la faire attendre
// derrière un canal rallongerait ce que le navigateur chronomètre.
func TestUneVerificationICEEstRepondueParLeSocket(t *testing.T) {
	socket, agent, pair := socketDEssai(t)

	requête, err := stun.Build(stun.TransactionID, stun.BindingRequest,
		stun.NewUsername(agent.Locale.Ufrag+":navigateur"),
		stun.NewShortTermIntegrity(agent.Locale.MotDePasse),
		stun.Fingerprint)
	if err != nil {
		t.Fatalf("requête : %v", err)
	}
	if _, err := pair.WriteToUDP(requête.Raw, destination(t, socket)); err != nil {
		t.Fatalf("envoi : %v", err)
	}

	_ = pair.SetReadDeadline(time.Now().Add(3 * time.Second))
	tampon := make([]byte, TailleDatagramme)
	n, _, err := pair.ReadFromUDP(tampon)
	if err != nil {
		t.Fatalf("aucune réponse STUN : %v", err)
	}
	message := &stun.Message{Raw: tampon[:n]}
	if err := message.Decode(); err != nil || message.Type != stun.BindingSuccess {
		t.Fatalf("réponse inattendue : %v / %v", err, message.Type)
	}
	if agent.Pair() == nil {
		t.Fatal("le pair n'a pas été retenu")
	}
}

// Le média n'est accepté QUE du pair qu'ICE a validé : sans cette règle un
// tiers qui atteint le port s'intercale dans l'appel.
func TestLeMediaDUnInconnuEstIgnore(t *testing.T) {
	socket, _, pair := socketDEssai(t)

	rtp := append([]byte{0x80, 0x00}, make([]byte, 20)...)
	if _, err := pair.WriteToUDP(rtp, destination(t, socket)); err != nil {
		t.Fatalf("envoi : %v", err)
	}
	select {
	case <-socket.RTP():
		t.Fatal("du média d'un inconnu est passé")
	case <-time.After(300 * time.Millisecond):
	}
}

func validerLePair(t *testing.T, socket *SocketMédia, agent *AgentICELite, pair *net.UDPConn) {
	t.Helper()
	requête, _ := stun.Build(stun.TransactionID, stun.BindingRequest,
		stun.NewUsername(agent.Locale.Ufrag+":navigateur"),
		stun.NewShortTermIntegrity(agent.Locale.MotDePasse),
		stun.Fingerprint)
	_, _ = pair.WriteToUDP(requête.Raw, destination(t, socket))
	_ = pair.SetReadDeadline(time.Now().Add(3 * time.Second))
	tampon := make([]byte, TailleDatagramme)
	if _, _, err := pair.ReadFromUDP(tampon); err != nil {
		t.Fatalf("le pair n'a pas été validé : %v", err)
	}
}

func TestChaqueProtocoleVaVersSonConsommateur(t *testing.T) {
	socket, agent, pair := socketDEssai(t)
	validerLePair(t, socket, agent, pair)

	// Un paquet RTP : premier octet 0x80, dans la plage 128-191.
	rtp := append([]byte{0x80, 0x00}, make([]byte, 20)...)
	if _, err := pair.WriteToUDP(rtp, destination(t, socket)); err != nil {
		t.Fatalf("envoi RTP : %v", err)
	}
	select {
	case reçu := <-socket.RTP():
		if len(reçu) != len(rtp) {
			t.Fatalf("%d octets au lieu de %d", len(reçu), len(rtp))
		}
	case <-time.After(3 * time.Second):
		t.Fatal("le paquet RTP n'est jamais arrivé")
	}

	// Un paquet DTLS : premier octet 22, dans la plage 20-63.
	conduit := socket.ConduitDTLS()
	poignée := append([]byte{22, 0xFE, 0xFD}, make([]byte, 10)...)
	if _, err := pair.WriteToUDP(poignée, destination(t, socket)); err != nil {
		t.Fatalf("envoi DTLS : %v", err)
	}
	_ = conduit.SetReadDeadline(time.Now().Add(3 * time.Second))
	tampon := make([]byte, TailleDatagramme)
	n, source, err := conduit.ReadFrom(tampon)
	if err != nil {
		t.Fatalf("le paquet DTLS n'est pas arrivé au conduit : %v", err)
	}
	if n != len(poignée) || source.String() != pair.LocalAddr().String() {
		t.Fatalf("%d octets depuis %v", n, source)
	}
}

// pion/dtls reconnaît cette erreur-là comme une expiration et retransmet.
// Toute autre lui fait abandonner la poignée de main.
func TestUneEcheanceDepasseeSeSignaleCommePionLAttend(t *testing.T) {
	socket, _, _ := socketDEssai(t)
	conduit := socket.ConduitDTLS()

	_ = conduit.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
	_, _, err := conduit.ReadFrom(make([]byte, TailleDatagramme))
	if err == nil {
		t.Fatal("aucune erreur alors que l'échéance est passée")
	}
	if !isTimeout(err) {
		t.Fatalf("erreur %v, que pion ne prendra pas pour une expiration", err)
	}
}

func isTimeout(err error) bool {
	return errors.Is(err, os.ErrDeadlineExceeded)
}

// Repoussée pendant l'attente, la nouvelle échéance doit être celle qui
// compte : sinon le calendrier de retransmission de DTLS dérive.
func TestUneEcheanceRepousseeEstPriseEnCompte(t *testing.T) {
	socket, agent, pair := socketDEssai(t)
	validerLePair(t, socket, agent, pair)
	conduit := socket.ConduitDTLS()

	_ = conduit.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	fini := make(chan error, 1)
	go func() {
		_, _, err := conduit.ReadFrom(make([]byte, TailleDatagramme))
		fini <- err
	}()

	time.Sleep(50 * time.Millisecond)
	_ = conduit.SetReadDeadline(time.Now().Add(2 * time.Second))
	time.Sleep(400 * time.Millisecond)

	poignée := append([]byte{22, 0xFE, 0xFD}, make([]byte, 10)...)
	_, _ = pair.WriteToUDP(poignée, destination(t, socket))

	select {
	case err := <-fini:
		if err != nil {
			t.Fatalf("la lecture a expiré sur l'ancienne échéance : %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("la lecture ne rend jamais la main")
	}
}
