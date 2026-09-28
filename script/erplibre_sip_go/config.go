// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"
)

// Config décrit une ligne SIP et ce qu'on en fait.
//
// Les secrets viennent de l'ENVIRONNEMENT et jamais d'un fichier versionné :
// ce dépôt est publié, et un mot de passe de trunk vaut de l'argent réel —
// une ligne volée sert à composer des numéros surtaxés à l'étranger.
type Config struct {
	Trunk    string // hôte du fournisseur
	User     string
	Password string
	From     string // numéro présenté ; vide = User
	Bind     string // adresse:port d'écoute SIP local
}

// numéroValide accepte le plan de numérotation nord-américain et rien d'autre.
//
// La validation est ici et pas seulement dans l'interface : un numéro mal
// formé part quand même sur le réseau, et le refus doit se produire avant
// qu'un appel n'atteigne quelqu'un qui n'a rien demandé.
var motifNumero = regexp.MustCompile(`^\+?1?([2-9]\d{2}[2-9]\d{6})$`)

func NuméroValide(brut string) (string, error) {
	chiffres := strings.Map(func(r rune) rune {
		if (r >= '0' && r <= '9') || r == '+' {
			return r
		}
		return -1
	}, brut)
	m := motifNumero.FindStringSubmatch(chiffres)
	if m == nil {
		return "", fmt.Errorf("numéro hors plan nord-américain : %q", brut)
	}
	return "1" + m[1], nil
}

// ChargerConfig lit l'environnement et refuse de démarrer si incomplet.
//
// On échoue au démarrage plutôt qu'au premier appel : découvrir un secret
// manquant au moment où quelqu'un attend une annonce est la pire façon de
// l'apprendre.
func ChargerConfig() (Config, error) {
	c := Config{
		Trunk:    os.Getenv("VOIP_TRUNK"),
		User:     os.Getenv("VOIP_USER"),
		Password: os.Getenv("VOIP_PASSWORD"),
		From:     os.Getenv("VOIP_FROM"),
		Bind:     os.Getenv("VOIP_BIND"),
	}
	if c.Bind == "" {
		// Boucle locale par défaut. Un service SIP qui écoute sur toutes les
		// interfaces est scanné en continu ; ouvrir est un geste explicite.
		c.Bind = "127.0.0.1:5080"
	}
	if c.From == "" {
		c.From = c.User
	}
	var manque []string
	if c.Trunk == "" {
		manque = append(manque, "VOIP_TRUNK")
	}
	if c.User == "" {
		manque = append(manque, "VOIP_USER")
	}
	if c.Password == "" {
		manque = append(manque, "VOIP_PASSWORD")
	}
	if len(manque) > 0 {
		return c, errors.New("variables absentes : " + strings.Join(manque, ", "))
	}
	return c, nil
}
