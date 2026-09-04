// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"log/slog"
	"strings"

	"github.com/emiago/diago"
	"github.com/emiago/sipgo/sip"
	"github.com/icholy/digest"
)

// Qui a le droit de faire composer la carte SIM.
//
// Un service qui compose est un service qui dépense. Le vol de ligne est le
// mode d'attaque ordinaire d'un serveur SIP : on s'y inscrit, on compose des
// numéros surtaxés, et la facture arrive. Rien ici ne remplace un plafond de
// dépense chez l'opérateur, mais l'inscription libre était la porte ouverte.

const (
	// VariablePostes porte les comptes, « poste:motdepasse » séparés par des
	// points-virgules. Dans l'environnement du processus et non dans un
	// fichier du dépôt : ce code est publié sous AGPL-3.
	VariablePostes = "VOIP_POSTES"

	// RoyaumeParDéfaut est le « realm » annoncé dans le défi. Il n'est pas
	// secret et ne protège rien ; il sert au client à choisir le bon mot de
	// passe quand il en connaît plusieurs.
	RoyaumeParDéfaut = "erplibre"

	// motDePasseFactice répond à un poste inconnu.
	//
	// On défie et on refuse un compte qui n'existe pas EXACTEMENT comme un
	// mot de passe faux : distinguer les deux dirait à qui sonde quels postes
	// existent, et lui épargnerait la moitié du travail.
	motDePasseFactice = "\x00aucun-compte-de-ce-nom"
)

// Comptes associe un nom de poste à son mot de passe.
type Comptes map[string]string

// LireComptes analyse « 1001:mdp;1002:autre ».
//
// Refuse une entrée mal formée plutôt que de l'ignorer : un point-virgule de
// trop laisserait un poste sans mot de passe, donc inutilisable, et la panne
// se présenterait comme un refus d'inscription sans cause visible.
func LireComptes(brut string) (Comptes, error) {
	comptes := Comptes{}
	for _, entrée := range strings.Split(brut, ";") {
		entrée = strings.TrimSpace(entrée)
		if entrée == "" {
			continue
		}
		poste, motDePasse, coupé := strings.Cut(entrée, ":")
		poste = strings.TrimSpace(poste)
		if !coupé || poste == "" || motDePasse == "" {
			return nil, fmt.Errorf(
				"compte mal forme %q : attendu « poste:motdepasse »", entrée)
		}
		comptes[poste] = motDePasse
	}
	return comptes, nil
}

// Gardien authentifie les requêtes qui engagent la ligne.
type Gardien struct {
	comptes   Comptes
	royaume   string
	serveur   *diago.DigestAuthServer
	désactivé bool
}

// NouveauGardien prépare l'authentification, ou son absence assumée.
//
// Sans compte ET sans renoncement explicite, il n'y a pas de service : un
// démarrage qui réussit en laissant la ligne ouverte à tous est le pire des
// deux mondes, puisque rien ne le signale ensuite.
func NouveauGardien(brut string, sansAuthentification bool) (*Gardien, error) {
	comptes, err := LireComptes(brut)
	if err != nil {
		return nil, err
	}
	if len(comptes) == 0 && !sansAuthentification {
		return nil, fmt.Errorf(
			"aucun poste dans %s : ce service fait composer une carte SIM, et "+
				"une inscription libre laisse composer n'importe qui. Poser "+
				"%s=\"1001:motdepasse\", ou assumer l'ouverture par "+
				"« -sans-authentification »", VariablePostes, VariablePostes)
	}
	if sansAuthentification {
		slog.Warn("AUCUNE AUTHENTIFICATION : quiconque atteint ce port peut " +
			"faire composer la carte SIM")
	}
	return &Gardien{
		comptes:   comptes,
		royaume:   RoyaumeParDéfaut,
		serveur:   diago.NewDigestServer(),
		désactivé: sansAuthentification && len(comptes) == 0,
	}, nil
}

// Fermer libère les défis en attente.
func (g *Gardien) Fermer() {
	if g.serveur != nil {
		g.serveur.Close()
	}
}

// Autoriser rend vrai quand la requête peut passer.
//
// Quand elle ne peut pas, la réponse est DÉJÀ transmise — un défi 401 la
// première fois, un refus ensuite. L'appelant n'a plus qu'à s'arrêter.
func (g *Gardien) Autoriser(req *sip.Request, tx sip.ServerTransaction) bool {
	if g.désactivé {
		return true
	}
	poste := posteDemandé(req)
	motDePasse, connu := g.comptes[poste]
	if !connu {
		motDePasse = motDePasseFactice
	}

	réponse, err := g.serveur.AuthorizeRequest(req, diago.DigestAuth{
		Username: poste,
		Password: motDePasse,
		Realm:    g.royaume,
	})
	if err == nil && réponse != nil && réponse.StatusCode == sip.StatusOK {
		return true
	}
	if réponse == nil {
		slog.Error("authentification sans reponse a transmettre", "err", err)
		return false
	}
	// Un défi n'est pas un échec : c'est le premier tour normal, le client
	// rejoue aussitôt avec ses identifiants. Le distinguer d'un refus évite
	// un journal qui crie à l'intrusion à chaque inscription.
	if réponse.StatusCode == sip.StatusUnauthorized && req.GetHeader("Authorization") == nil {
		slog.Debug("défi envoyé", "poste", poste, "methode", req.Method)
	} else {
		slog.Warn("requete refusee", "poste", poste, "methode", req.Method,
			"err", err)
	}
	if err := tx.Respond(réponse); err != nil {
		slog.Error("reponse d'authentification non transmise", "err", err)
	}
	return false
}

// AutoriserDialogue défie l'INVITE d'un appel.
//
// Un dialogue passe par un chemin à lui : la réponse se transmet par la
// session, non par une transaction que l'appelant tiendrait.
func (g *Gardien) AutoriserDialogue(d *diago.DialogServerSession) bool {
	if g.désactivé {
		return true
	}
	req := d.InviteRequest
	poste := posteDemandé(req)
	motDePasse, connu := g.comptes[poste]
	if !connu {
		motDePasse = motDePasseFactice
	}

	réponse, err := g.serveur.AuthorizeRequest(req, diago.DigestAuth{
		Username: poste,
		Password: motDePasse,
		Realm:    g.royaume,
	})
	if err == nil && réponse != nil && réponse.StatusCode == sip.StatusOK {
		return true
	}
	if réponse == nil {
		slog.Error("authentification sans reponse a transmettre", "err", err)
		return false
	}
	if err := d.WriteResponse(réponse); err != nil {
		slog.Error("reponse d'authentification non transmise", "err", err)
	}
	return false
}

// posteDemandé rend le nom sous lequel la requête se présente.
//
// Celui de l'en-tête « Authorization » quand il existe, car c'est le compte
// dont le client prétend connaître le mot de passe ; sinon celui de « From ».
// Se fier au seul « From » laisserait présenter un compte et en signer un
// autre.
func posteDemandé(req *sip.Request) string {
	if h := req.GetHeader("Authorization"); h != nil {
		// L'analyse est confiée à la bibliothèque qui produit ces en-têtes :
		// elle connaît le préfixe du schéma, les guillemets et les champs
		// facultatifs, là où un découpage à la main les manque un par un.
		if cred, err := digest.ParseCredentials(h.Value()); err == nil &&
			cred.Username != "" {
			return cred.Username
		}
	}
	if from := req.From(); from != nil {
		return from.Address.User
	}
	return ""
}
