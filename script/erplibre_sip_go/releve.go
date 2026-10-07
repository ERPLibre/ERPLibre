// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"
)

// Relever la boîte vocale de l'opérateur, sans personne devant la machine.
//
// Le déclencheur est le DRAPEAU de la SIM et non une horloge : un relèvement
// appelle pour de bon, occupe la ligne et se facture, et il n'a de raison de
// partir que lorsqu'il y a quelque chose à prendre. Le bouton d'Odoo est
// l'exception explicite — quelqu'un a demandé, on obéit même sans drapeau.
//
// Le service fait l'appel et DÉPOSE l'enregistrement ; il ne le découpe pas.
// La découpe vit du côté de l'agent, réglée sur une vraie messagerie, et en
// porter une seconde version ici ferait deux heuristiques qui divergent.

const (
	// RecetteAvecEffacement prend le message puis l'efface chez l'opérateur.
	// RecetteSansEffacement écoute sans rien détruire.
	RecetteAvecEffacement = "recuperer_un_message"
	RecetteSansEffacement = "reperage_code_ecoute"

	// DossierRecettesDéfaut est relatif au répertoire de travail, que
	// l'unité systemd pose sur le dépôt.
	DossierRecettesDéfaut = "script/todo/modem/recettes"

	// MarqueÀTraiter signale à l'agent un dépôt qui lui revient. Le menu
	// n'en pose pas : ce qu'il relève, il le traite lui-même, et sans cette
	// marque les deux chemins se marcheraient dessus.
	MarqueÀTraiter = ".a_traiter"
)

// Relève décide s'il faut appeler la boîte vocale, et retient ce qui a déjà
// été tenté.
type Relève struct {
	// dernièreDemande est la dernière date posée par Odoo qu'on ait
	// traitée. On la COMPARE : une valeur nouvelle vaut un relèvement, la
	// même rejouée à chaque minute n'en déclenche pas un second.
	dernièreDemande string
	// tentée empêche de rappeler sans fin tant que le drapeau reste levé.
	// Sans effacement, il reste levé par construction : un relèvement par
	// montée est la seule cadence qui ne boucle pas.
	tentée bool
}

// Décision dit s'il faut relever, et pourquoi quand on s'en abstient.
type Décision struct {
	Relever bool
	Efface  bool
	Motif   string
}

// Décider applique les règles. `lectureSûre` dit si le drapeau vient d'être
// lu sans erreur : un drapeau qu'on n'a pas pu lire ne vaut pas un drapeau
// baissé, et appeler là-dessus ferait un appel pour rien.
func (r *Relève) Décider(rég RéglagesRépondeur, attente, lectureSûre, aLeNIP bool) Décision {
	if !attente {
		// Le drapeau est retombé : la montée suivante aura droit à son essai.
		r.tentée = false
	}

	demande := rég.RelèveDemandée
	demandée := demande != "" && demande != r.dernièreDemande

	if !demandée && !(rég.RelèveAuto && attente && lectureSûre && !r.tentée) {
		return Décision{}
	}
	if !aLeNIP {
		return Décision{Motif: "le service n'a pas le code de la messagerie :" +
			" remettez-le par le menu, il est perdu a chaque redemarrage"}
	}

	// On note l'essai AVANT de le faire : un relèvement qui échoue ne doit
	// pas repartir à la minute suivante, sans quoi une recette qui ne
	// convient plus appellerait en boucle.
	if demandée {
		r.dernièreDemande = demande
	}
	if attente {
		r.tentée = true
	}
	return Décision{Relever: true, Efface: rég.RelèveEfface}
}

// DossierDesRelèves rend où déposer, d'après le dossier des messages.
//
// Déduit et non réglé : les deux vivent sous `private/repondeur/`, et une
// seconde option finirait par désigner un autre endroit que celui où l'agent
// regarde.
func DossierDesRelèves(dossierMessages string) string {
	if dossierMessages == "" {
		return ""
	}
	return filepath.Join(filepath.Dir(dossierMessages), "operateur")
}

// Relever appelle la boîte vocale et dépose l'enregistrement pour l'agent.
//
// Prend la LIGNE : composer par-dessus une conversation la couperait. Rend le
// chemin déposé, ou une erreur.
func Relever(ctx context.Context, m *Modem, o OptionsModem, r RéglagesRépondeur,
	d Décision, code, dossierRecettes string, maintenant time.Time) (string, error) {

	nom := RecetteSansEffacement
	if d.Efface {
		nom = RecetteAvecEffacement
	}
	recette, err := ChargerRecette(filepath.Join(dossierRecettes, nom+".json"))
	if err != nil {
		return "", err
	}
	dossier := DossierDesRelèves(r.Dossier)
	if dossier == "" {
		return "", fmt.Errorf("aucun dossier ou deposer le relevement")
	}
	if err := os.MkdirAll(dossier, 0o700); err != nil {
		return "", err
	}

	if !m.PrendreLaLigne() {
		return "", fmt.Errorf("la ligne porte deja une conversation")
	}
	defer m.RendreLaLigne()

	numéro, err := m.NuméroMessagerie()
	if err != nil {
		return "", err
	}
	o.Numéro = numéro

	chemin := filepath.Join(dossier,
		fmt.Sprintf("%s-%s.wav", nom, maintenant.Format("20060102-150405")))
	slog.Info("relevement de la boite vocale", "recette", nom, "efface", d.Efface)
	bilan := RécupérerMessagerieAvecModem(ctx, m, o, recette, chemin, code)

	// Le bilan est écrit MÊME en échec : il porte la courbe et les touches,
	// qui sont ce par quoi on règle une recette qui ne convient plus.
	brut, _ := json.MarshalIndent(bilan, "", " ")
	_ = os.WriteFile(CheminCompagnon(chemin), append(brut, '\n'), 0o600)
	if bilan.Erreur != "" {
		return chemin, fmt.Errorf("%s", bilan.Erreur)
	}
	if err := os.WriteFile(chemin+MarqueÀTraiter, nil, 0o600); err != nil {
		return chemin, err
	}
	slog.Info("relevement depose", "fichier", chemin,
		"secondes", bilan.DuréeMs/1000)
	return chemin, nil
}
