// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// Le cache écoute sur toutes les adresses de l'hôte. Une requête qui le
// désigne LUI — son port, sur une adresse de cette machine — serait relayée
// vers sa propre écoute, qui la relaierait à son tour : chaque tour ouvre une
// connexion de plus, et la boucle épuise les descripteurs jusqu'à arrêter le
// service entier. Ce fichier la reconnaît et la refuse.

// viseLeCache dit si une URL désigne le cache lui-même.
//
// Le port d'abord : il ne coûte rien, et seul un port d'écoute du cache peut
// boucler. L'hôte ensuite — « localhost », une adresse de bouclage, une
// adresse non spécifiée ou celle d'une interface de cette machine. Un NOM
// n'est résolu que dans ce cas rare où le port concorde : le résoudre à
// chaque requête coûterait un aller-retour DNS à tout le trafic.
func (p *Proxy) viseLeCache(u *url.URL) bool {
	if p == nil || len(p.Ecoutes) == 0 || u == nil {
		return false
	}
	port := portDe(u)
	concorde := false
	for _, e := range p.Ecoutes {
		if e == port {
			concorde = true
			break
		}
	}
	if !concorde {
		return false
	}
	hote := strings.ToLower(strings.TrimSuffix(u.Hostname(), "."))
	if hote == "localhost" || strings.HasSuffix(hote, ".localhost") {
		return true
	}
	if ip := net.ParseIP(hote); ip != nil {
		return estAdresseLocale(ip)
	}
	ctx, annule := context.WithTimeout(context.Background(), 2*time.Second)
	defer annule()
	ips, err := net.DefaultResolver.LookupIPAddr(ctx, hote)
	if err != nil {
		return false
	}
	for _, a := range ips {
		if estAdresseLocale(a.IP) {
			return true
		}
	}
	return false
}

// portDe rend le port d'une URL, déduit du schéma quand elle n'en porte pas,
// et -1 quand il ne se déduit pas.
func portDe(u *url.URL) int {
	if brut := u.Port(); brut != "" {
		n, err := strconv.Atoi(brut)
		if err != nil {
			return -1
		}
		return n
	}
	switch strings.ToLower(u.Scheme) {
	case "https":
		return 443
	case "http":
		return 80
	}
	return -1
}

// estAdresseLocale dit si une adresse joint cette machine : bouclage,
// adresse non spécifiée — qu'une connexion traite comme l'hôte local — ou
// adresse de l'une de ses interfaces.
func estAdresseLocale(ip net.IP) bool {
	if ip.IsLoopback() || ip.IsUnspecified() {
		return true
	}
	adresses, err := net.InterfaceAddrs()
	if err != nil {
		return false
	}
	for _, a := range adresses {
		if n, ok := a.(*net.IPNet); ok && n.IP.Equal(ip) {
			return true
		}
	}
	return false
}

// boucle répond « 508 Loop Detected » sans rien demander à personne, et le
// journal le compte comme une erreur. Le message est inerte pour un shell,
// comme celui du hors-ligne : il peut finir dans « curl … | bash ».
func (p *Proxy) boucle(
	w http.ResponseWriter, u *url.URL, class Class, method, client string,
) {
	msg := enCommentaire(fmt.Sprintf(
		"erplibre_go_qemu_cache : requête adressée au cache lui-même, refusée.\n"+
			"  demandé : %s\n"+
			"La relayer la renverrait vers cette même écoute, sans fin.\n",
		u))
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.Header().Set("X-ERPLibre-Cache", OutcomeError)
	w.WriteHeader(http.StatusLoopDetected)
	fmt.Fprint(w, msg)

	p.record(accessLine{
		Method: method, URL: u.String(), Class: class.String(),
		Outcome: OutcomeError, Status: http.StatusLoopDetected,
		Client: client,
	})
	log.Printf("boucle refusée : %s vise le cache lui-même", u)
}

// memeAdresse compare deux « hôte:port » par leur VALEUR : « ::ffff:a.b.c.d »
// et « a.b.c.d » désignent la même machine, et une comparaison de textes les
// séparerait.
func memeAdresse(a, b string) bool {
	ha, pa, err := net.SplitHostPort(a)
	if err != nil {
		return false
	}
	hb, pb, err := net.SplitHostPort(b)
	if err != nil || pa != pb {
		return false
	}
	ia, ib := net.ParseIP(ha), net.ParseIP(hb)
	if ia == nil || ib == nil {
		return strings.EqualFold(ha, hb)
	}
	return ia.Equal(ib)
}
