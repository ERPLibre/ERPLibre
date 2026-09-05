// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

//go:build !linux

package main

import (
	"errors"
	"net"
)

// originalDst n'a de sens que là où Netfilter garde la destination d'une
// connexion redirigée. Ailleurs, le tunnel opaque est impossible et le dire
// vaut mieux que de deviner une adresse.
func originalDst(net.Conn) (string, error) {
	return "", errors.New("interception transparente : Linux seulement")
}
