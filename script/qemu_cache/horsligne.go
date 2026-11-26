// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
)

// Le mode hors ligne sert un magasin FIGÉ : celui qu'une installation de
// référence a rempli, posé sur un support en lecture seule.
//
// Il ne compose jamais vers l'amont. Chaque requête suit alors le chemin du
// repli que le cache emprunte déjà quand l'amont est coupé — corps gardé,
// « 304 » au client qui détient sa copie, statut gardé, sinon « 504 » qui
// nomme ce qui manque — sans payer le moindre délai d'établissement, puisque
// aucune connexion n'est tentée. Le miroir git sert les dépôts présents sans
// les rafraîchir ni en cloner de nouveaux, et le front TLS déchiffre tout,
// aucun tunnel ne pouvant aboutir.
//
// Rien n'y écrit dans le magasin : aucune réponse d'amont n'arrive, donc
// rien à garder, et le balayage des écritures interrompues du démarrage est
// sauté. Seule la date d'usage d'un corps servi est tentée, et son échec sur
// un support en lecture seule est déjà ignoré (voir Store.Get).

// errHorsLigne dit qu'aucune connexion n'a été tentée : le service tourne
// en mode hors ligne.
var errHorsLigne = errors.New(
	T("mode hors ligne : l'amont n'est jamais joint"))

// decrireHorsLigne rend la phrase du message d'absence propre au mode hors
// ligne, ou "" pour toute autre cause.
func decrireHorsLigne(cause error) string {
	if !errors.Is(cause, errHorsLigne) {
		return ""
	}
	return T("Ce fichier n'est pas dans le paquet hors ligne : l'installation de\n" +
		"référence qui l'a rempli ne l'a jamais demandé.\n")
}

// adresseDEcoute rend « hôte:port » pour net.Listen. Un hôte vide écoute sur
// toutes les adresses, comme avant que l'écoute soit réglable.
func adresseDEcoute(hote string, port int) string {
	return net.JoinHostPort(hote, strconv.Itoa(port))
}

// verifierHorsLigne refuse de démarrer le mode hors ligne sans son magasin
// ni son autorité : le service ne les crée pas, le support étant en lecture
// seule, et une autorité fabriquée ici ne serait approuvée par personne.
func verifierHorsLigne(cacheDir, caDir string) error {
	st, err := os.Stat(cacheDir)
	if err != nil || !st.IsDir() {
		return fmt.Errorf(T("mode hors ligne : magasin introuvable : %s"), cacheDir)
	}
	if _, err := os.Stat(CertPath(caDir)); err != nil {
		return fmt.Errorf(T("mode hors ligne : autorité introuvable : %s"),
			CertPath(caDir))
	}
	return nil
}
