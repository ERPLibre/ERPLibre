// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

//go:build linux

package main

import (
	"errors"
	"fmt"
	"net"
	"syscall"
)

// SO_ORIGINAL_DST : l'option que Netfilter renseigne sur une socket
// redirigée. Elle n'est pas dans le paquet « syscall », d'où la constante.
const soOriginalDst = 80

// originalDst rend l'adresse que l'invité voulait joindre.
//
// En interception transparente le client croit parler au serveur amont : la
// socket acceptée porte l'adresse du cache, et la destination d'origine n'est
// connue que du noyau, qui la garde pour cette redirection. Sans elle, un
// tunnel opaque n'a nulle part à aller.
func originalDst(c net.Conn) (string, error) {
	// La connexion peut être enveloppée par le rejeu du ClientHello : c'est
	// la socket dessous qui porte l'option.
	for {
		if r, ok := c.(*replayed); ok {
			c = r.Conn
			continue
		}
		break
	}
	tcp, ok := c.(*net.TCPConn)
	if !ok {
		return "", errors.New("la connexion n'est pas une socket TCP")
	}
	raw, err := tcp.SyscallConn()
	if err != nil {
		return "", err
	}
	var addr string
	var inner error
	err = raw.Control(func(fd uintptr) {
		// GetsockoptIPv6Mreq rend seize octets bruts, ce qui est exactement
		// la taille d'un « sockaddr_in » : famille, port, adresse. Le nom de
		// l'appel ne correspond pas à l'usage, mais c'est le seul du paquet
		// « syscall » qui rende un tampon de cette taille.
		mreq, e := syscall.GetsockoptIPv6Mreq(int(fd), syscall.IPPROTO_IP, soOriginalDst)
		if e != nil {
			inner = e
			return
		}
		port := int(mreq.Multiaddr[2])<<8 | int(mreq.Multiaddr[3])
		ip := net.IPv4(
			mreq.Multiaddr[4], mreq.Multiaddr[5],
			mreq.Multiaddr[6], mreq.Multiaddr[7],
		)
		addr = fmt.Sprintf("%s:%d", ip.String(), port)
	})
	if err != nil {
		return "", err
	}
	if inner != nil {
		return "", inner
	}
	if addr == "" || addr == "0.0.0.0:0" {
		return "", errors.New("aucune destination d'origine : la connexion n'est pas redirigée")
	}
	return addr, nil
}
