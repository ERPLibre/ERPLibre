// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
)

// Ce que le système déclare comme cartes son, et la vérification qu'un nom
// désigne bien l'une d'elles.
//
// Un nom « hw:N,0 » dont l'index n'existe pas ne se voit qu'à l'ouverture,
// c'est-à-dire une fois l'appel décroché : la minute est facturée, quelqu'un
// a répondu, et le seul message est « EOF ». On refuse donc AVANT de composer.

// FichierCartes est lu pour connaître les cartes. Variable pour que la
// vérification se teste sans dépendre du matériel de qui lance les tests.
var FichierCartes = "/proc/asound/cards"

var motifIndexCarte = regexp.MustCompile(`^(?:plug)?hw:(\d+)`)

// CartesDéclarées rend les cartes du système, index vers nom.
func CartesDéclarées() (map[int]string, error) {
	f, err := os.Open(FichierCartes)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	cartes := map[int]string{}
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		g := motifCarte.FindStringSubmatch(sc.Text())
		if g == nil {
			continue
		}
		index, err := strconv.Atoi(g[1])
		if err != nil {
			continue
		}
		cartes[index] = strings.TrimSpace(g[2])
	}
	return cartes, sc.Err()
}

// VérifierCarte refuse un nom qui ne désigne aucune carte présente.
//
// Ne juge QUE les noms « hw: » et « plughw: ». Un périphérique du serveur
// audio (préfixe « pw: ») ne figure pas dans ce fichier, et le refuser sur ce
// motif interdirait un usage parfaitement valable.
func VérifierCarte(nom string) error {
	groupes := motifIndexCarte.FindStringSubmatch(nom)
	if groupes == nil {
		return nil
	}
	voulu, err := strconv.Atoi(groupes[1])
	if err != nil {
		return nil
	}
	cartes, err := CartesDéclarées()
	if err != nil {
		return fmt.Errorf("lecture de %s : %w", FichierCartes, err)
	}
	if _, présente := cartes[voulu]; présente {
		return nil
	}
	return fmt.Errorf(
		"aucune carte son d'index %d : %q ne designe rien. Presentes : %s",
		voulu, nom, décrireCartes(cartes))
}

// décrireCartes rend « 0 (sof-hda-dsp), 1 (EC25AF) », ou dit qu'il n'y en a
// aucune — ce qui arrive quand l'UAC du modem n'est pas activé.
func décrireCartes(cartes map[int]string) string {
	if len(cartes) == 0 {
		return "aucune"
	}
	var décrites []string
	for index := 0; index < 32; index++ {
		if nom, présente := cartes[index]; présente {
			décrites = append(décrites, fmt.Sprintf("%d (%s)", index, nom))
		}
	}
	return strings.Join(décrites, ", ")
}
