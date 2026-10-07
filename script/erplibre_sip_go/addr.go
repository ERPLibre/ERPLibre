package main

import (
	"net"
	"strconv"
)

// hôte et port découpent "adresse:port" en tolérant l'absence de port.
func hôte(bind string) string {
	h, _, err := net.SplitHostPort(bind)
	if err != nil {
		return bind
	}
	return h
}

func port(bind string) int {
	_, p, err := net.SplitHostPort(bind)
	if err != nil {
		return 5080
	}
	n, err := strconv.Atoi(p)
	if err != nil {
		return 5080
	}
	return n
}
