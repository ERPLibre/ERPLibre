// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"os"
	"strings"
	"sync"
)

// Langues servies. Le français est la langue du code source : chaque message y
// est écrit tel quel et sert de clé au catalogue anglais (catalogue_en.go).
const (
	LangueFr = "fr"
	LangueEn = "en"
)

var (
	langueUne sync.Once
	langue    string
)

// T rend un message humain dans la langue du binaire.
//
// La clé EST le texte français : le message reste lisible à l'endroit où il
// est écrit, et un texte absent du catalogue sort en français plutôt que vide.
// Seuls les textes destinés à une personne passent par ici — journaux,
// sorties affichées, aide des options, erreurs montrées, corps d'une réponse
// d'erreur. Une règle nft, une ligne de protocole, un code de verdict ou une
// clé JSON sont lus par des programmes et ne se traduisent jamais.
func T(fr string) string {
	if Langue() == LangueEn {
		if en, ok := anglais[fr]; ok {
			return en
		}
	}
	return fr
}

// Langue rend la langue retenue, résolue une seule fois à la première demande.
//
// Paresseuse, et non posée par main après l'analyse des options : des erreurs
// sont construites à l'initialisation du paquet, et l'aide des options est
// écrite avant flag.Parse. L'option --lang passe avant EL_LANG, parce que sudo
// retire l'environnement : un binaire lancé par « sudo » ne verrait jamais la
// langue de qui l'appelle.
func Langue() string {
	langueUne.Do(func() {
		langue = langueDemandee(os.Args[1:], os.Getenv)
	})
	return langue
}

// definirLangue impose une langue, en court-circuitant la résolution.
func definirLangue(l string) {
	langueUne.Do(func() {})
	langue = normaliserLangue(l)
}

// langueDemandee lit « --lang X », « --lang=X », « -lang X » ou « -lang=X »
// dans les arguments, puis EL_LANG. Rend « fr » par défaut, et pour toute
// valeur qui n'est pas de l'anglais. La lecture s'arrête à « -- », au-delà
// duquel un argument n'est plus une option.
func langueDemandee(args []string, env func(string) string) string {
	for i, a := range args {
		if a == "--" {
			break
		}
		if !strings.HasPrefix(a, "-") {
			continue
		}
		nom, valeur, egal := strings.Cut(strings.TrimLeft(a, "-"), "=")
		if nom != "lang" {
			continue
		}
		if !egal {
			if i+1 >= len(args) {
				break
			}
			valeur = args[i+1]
		}
		return normaliserLangue(valeur)
	}
	return normaliserLangue(env("EL_LANG"))
}

// normaliserLangue ramène une valeur libre à une langue servie : « en »,
// « EN », « en_CA.UTF-8 » donnent l'anglais, tout le reste le français.
func normaliserLangue(s string) string {
	if strings.HasPrefix(strings.ToLower(strings.TrimSpace(s)), LangueEn) {
		return LangueEn
	}
	return LangueFr
}
