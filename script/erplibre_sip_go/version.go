// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"os"
	"time"
)

// EmpreinteBinaire décrit l'exécutable en cours, pour le distinguer d'un
// autre.
//
// La date de l'exécutable ET sa taille : la date seule ne bouge pas quand une
// reconstruction rend le même horodatage à la seconde près, et la taille seule
// ne bouge pas non plus quand un changement n'ajoute aucun octet.
//
// Rend « inconnu » plutôt que d'échouer : ne pas pouvoir se décrire n'est pas
// une raison de refuser de servir.
func EmpreinteBinaire() string {
	chemin, err := os.Executable()
	if err != nil {
		return "inconnu"
	}
	état, err := os.Stat(chemin)
	if err != nil {
		return "inconnu"
	}
	return fmt.Sprintf("%s/%do",
		état.ModTime().Format(time.DateTime), état.Size())
}
