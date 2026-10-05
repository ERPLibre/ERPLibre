// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"os"
	"sync"
	"time"
)

// Un navigateur fait passer STUN, DTLS et SRTP par le MÊME port. Ce fichier
// tient le socket, trie ce qui arrive, et sert chacun des trois par un canal
// séparé. Sans ce tri, pion/dtls recevrait des paquets RTP et le décodeur RTP
// des poignées de main : les deux les jettent en silence, et l'appel reste
// muet sans que rien ne l'explique.

const (
	// TailleDatagramme borne la lecture. Le MTU d'Ethernet est de 1500 ; on
	// prend au-dessus pour qu'un paquet trop grand soit tronqué visiblement
	// plutôt que perdu.
	TailleDatagramme = 2048

	// ProfondeurCanal absorbe une rafale sans bloquer la boucle de lecture.
	// Une poignée de main DTLS tient en quelques paquets ; le son arrive à
	// cinquante par seconde.
	ProfondeurCanal = 64
)

type datagramme struct {
	charge []byte
	source net.Addr
}

// SocketMédia lit un port UDP et distribue selon la nature du paquet.
type SocketMédia struct {
	conn  *net.UDPConn
	agent *AgentICELite

	versDTLS chan datagramme
	versRTP  chan []byte

	mutex     sync.Mutex
	échéance  time.Time
	réveil    chan struct{}
	étrangers map[string]bool
}

// NouveauSocketMédia ouvre un port et prépare le tri.
func NouveauSocketMédia(adresse string, agent *AgentICELite) (*SocketMédia, error) {
	résolue, err := net.ResolveUDPAddr("udp", adresse)
	if err != nil {
		return nil, err
	}
	conn, err := net.ListenUDP("udp", résolue)
	if err != nil {
		return nil, err
	}
	return &SocketMédia{
		conn:     conn,
		agent:    agent,
		versDTLS: make(chan datagramme, ProfondeurCanal),
		versRTP:  make(chan []byte, ProfondeurCanal),
		réveil:   make(chan struct{}, 1),
	}, nil
}

// Port rend le port réellement attribué, qui va dans le SDP.
func (s *SocketMédia) Port() int {
	return s.conn.LocalAddr().(*net.UDPAddr).Port
}

// RTP rend le canal des paquets protégés venus du pair.
func (s *SocketMédia) RTP() <-chan []byte { return s.versRTP }

// Fermer libère le port et débloque tout ce qui attend.
func (s *SocketMédia) Fermer() error { return s.conn.Close() }

// Trier lit le socket jusqu'à l'arrêt du contexte.
//
// Les requêtes STUN sont traitées ICI, à même la boucle : elles se répondent
// en quelques microsecondes, et les faire attendre derrière un canal
// rallongerait la vérification de connectivité que le navigateur chronomètre.
func (s *SocketMédia) Trier(ctx context.Context) error {
	go func() {
		<-ctx.Done()
		_ = s.conn.Close()
	}()

	tampon := make([]byte, TailleDatagramme)
	for {
		n, source, err := s.conn.ReadFromUDP(tampon)
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		charge := append([]byte(nil), tampon[:n]...)

		switch Nature(charge) {
		case PaquetSTUN:
			s.répondreSTUN(charge, source)
		case PaquetDTLS:
			// Rien d'autre que le pair validé par ICE : accepter une poignée
			// de main venue d'ailleurs laisserait un tiers s'intercaler.
			if s.vientDuPair(source) {
				s.déposer(datagramme{charge, source})
			}
		case PaquetRTCP:
			// Rien à en faire pour l'instant : l'écho comme le pont vers le
			// modem n'ont pas besoin des comptes rendus. On les reconnaît
			// pour ne pas les prendre pour du son abîmé.
			continue
		case PaquetRTP:
			if !s.vientDuPair(source) {
				// Écarter du média en silence est le meilleur moyen de
				// chercher la panne ailleurs : on le dit, avec les deux
				// adresses, une seule fois par source.
				s.signalerÉtranger(source)
				continue
			}
			select {
			case s.versRTP <- charge:
			default:
				// Le son est périssable : un paquet en retard ne sert plus à
				// rien, et bloquer ici arrêterait aussi STUN.
				slog.Debug("paquet RTP jeté, canal plein")
			}
		}
	}
}

// signalerÉtranger annonce une source écartée, une fois par adresse.
func (s *SocketMédia) signalerÉtranger(source net.Addr) {
	s.mutex.Lock()
	defer s.mutex.Unlock()
	if s.étrangers == nil {
		s.étrangers = map[string]bool{}
	}
	clé := source.String()
	if s.étrangers[clé] {
		return
	}
	s.étrangers[clé] = true
	pair := "aucun"
	if p := s.agent.Pair(); p != nil {
		pair = p.String()
	}
	slog.Warn("média écarté : source inconnue d'ICE",
		"source", clé, "pair_valide", pair)
}

func (s *SocketMédia) répondreSTUN(charge []byte, source net.Addr) {
	réponse, err := s.agent.Répondre(charge, source)
	if err != nil || réponse == nil {
		return
	}
	if _, err := s.conn.WriteToUDP(réponse, source.(*net.UDPAddr)); err != nil {
		slog.Debug("réponse STUN non transmise", "err", err)
	}
}

// vientDuPair n'accepte que l'adresse qu'ICE a validée.
func (s *SocketMédia) vientDuPair(source net.Addr) bool {
	pair := s.agent.Pair()
	return pair != nil && pair.String() == source.String()
}

func (s *SocketMédia) déposer(d datagramme) {
	select {
	case s.versDTLS <- d:
	default:
		// Perdre un paquet de poignée de main n'est pas fatal : DTLS
		// retransmet. Bloquer, si.
		slog.Debug("paquet DTLS jeté, canal plein")
	}
}

// Émettre envoie vers le pair validé par ICE.
func (s *SocketMédia) Émettre(charge []byte) error {
	pair := s.agent.Pair()
	if pair == nil {
		return errors.New("aucun pair valide : rien a qui emettre")
	}
	_, err := s.conn.WriteToUDP(charge, pair.(*net.UDPAddr))
	return err
}

// ConduitDTLS présente le seul flux DTLS sous la forme que pion/dtls attend.
//
// pion/dtls veut un `net.PacketConn` a lui : lui donner le socket brut le
// ferait recevoir le son et les vérifications ICE, qu'il jetterait en
// signalant des erreurs de protocole.
func (s *SocketMédia) ConduitDTLS() net.PacketConn { return &conduitDTLS{socket: s} }

type conduitDTLS struct {
	socket *SocketMédia
}

func (c *conduitDTLS) ReadFrom(p []byte) (int, net.Addr, error) {
	for {
		attente := c.attente()
		select {
		case d, ouvert := <-c.socket.versDTLS:
			if !ouvert {
				return 0, nil, net.ErrClosed
			}
			return copy(p, d.charge), d.source, nil
		case <-attente:
			// `os.ErrDeadlineExceeded` et non une erreur a nous : pion/dtls
			// la reconnait comme une expiration et retransmet, la ou toute
			// autre erreur ferait abandonner la poignee de main.
			return 0, nil, os.ErrDeadlineExceeded
		case <-c.socket.réveil:
			// L'echeance a change pendant l'attente : on recommence avec la
			// nouvelle.
		}
	}
}

// attente rend un canal qui se déclenche à l'échéance, ou jamais.
func (c *conduitDTLS) attente() <-chan time.Time {
	c.socket.mutex.Lock()
	échéance := c.socket.échéance
	c.socket.mutex.Unlock()
	if échéance.IsZero() {
		return nil
	}
	return time.After(time.Until(échéance))
}

func (c *conduitDTLS) WriteTo(p []byte, addr net.Addr) (int, error) {
	udp, ok := addr.(*net.UDPAddr)
	if !ok {
		return 0, errors.New("adresse non UDP")
	}
	return c.socket.conn.WriteToUDP(p, udp)
}

func (c *conduitDTLS) Close() error        { return nil }
func (c *conduitDTLS) LocalAddr() net.Addr { return c.socket.conn.LocalAddr() }

func (c *conduitDTLS) SetDeadline(t time.Time) error {
	return c.SetReadDeadline(t)
}

func (c *conduitDTLS) SetReadDeadline(t time.Time) error {
	c.socket.mutex.Lock()
	c.socket.échéance = t
	c.socket.mutex.Unlock()
	// Reveiller une lecture deja engagee : sans cela elle attendrait
	// l'ancienne echeance, et le calendrier de retransmission de DTLS
	// deriverait jusqu'a l'abandon.
	select {
	case c.socket.réveil <- struct{}{}:
	default:
	}
	return nil
}

func (c *conduitDTLS) SetWriteDeadline(time.Time) error { return nil }
