// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"net"
	"strconv"
	"strings"
)

// Le SDP échangé avec un navigateur est étroit et rigide : une seule piste
// audio, un seul codec, et une poignée d'attributs sans lesquels rien ne
// circule. On l'écrit et on le lit à la main plutôt que d'ajouter une
// bibliothèque — ce qui suit tient en un écran, et chaque ligne est là pour
// une raison qu'un test nomme.

const (
	// ChargePCMU est le type de charge utile de G.711 µ-law. C'est une valeur
	// STATIQUE de la RFC 3551 : elle ne se négocie pas, elle vaut 0 partout.
	ChargePCMU = 0

	// ProtoWebRTC est le seul profil qu'un navigateur accepte pour l'audio :
	// RTP sécurisé par DTLS, avec retour d'information. Répondre en RTP/AVP
	// clair fait rejeter la réponse sans autre explication.
	ProtoWebRTC = "UDP/TLS/RTP/SAVPF"

	// PrioritéCandidatHôte : formule de la RFC 8445 §5.1.2.1 pour un candidat
	// hôte, composante RTP unique — (2^24)*126 + (2^8)*65535 + 256-1.
	PrioritéCandidatHôte = 2130706431

	// PaquetisationMs est la durée d'un paquet RTP. Vingt millisecondes est
	// ce que le modem produit et ce que tout navigateur attend.
	PaquetisationMs = 20
)

// OffreNavigateur retient d'une offre SDP ce dont la réponse a besoin, et
// rien de plus.
type OffreNavigateur struct {
	Ufrag          string
	MotDePasse     string
	Empreinte      string // « sha-256 AB:CD:... », tel quel
	Mid            string
	Bundle         bool
	AccepteRTCPMux bool
	AcceptePCMU    bool
}

// LireOffre extrait d'une offre ce qu'il faut pour y répondre.
//
// Refuse plutôt que de deviner : une offre sans identifiants ICE, sans
// empreinte ou sans PCMU ne mène à aucune réponse utilisable, et l'échec doit
// se voir ici plutôt que trois étapes plus loin, sur un appel muet.
func LireOffre(brut []byte) (OffreNavigateur, error) {
	var offre OffreNavigateur
	for _, ligne := range strings.Split(string(brut), "\n") {
		ligne = strings.TrimRight(ligne, "\r")
		valeur, estAttribut := strings.CutPrefix(ligne, "a=")
		if !estAttribut {
			continue
		}
		nom, reste, _ := strings.Cut(valeur, ":")
		switch nom {
		case "ice-ufrag":
			offre.Ufrag = reste
		case "ice-pwd":
			offre.MotDePasse = reste
		case "fingerprint":
			offre.Empreinte = reste
		case "mid":
			offre.Mid = reste
		case "group":
			offre.Bundle = strings.HasPrefix(reste, "BUNDLE")
		case "rtcp-mux":
			offre.AccepteRTCPMux = true
		case "rtpmap":
			// « 0 PCMU/8000 » — le type statique peut aussi n'être annoncé
			// que sur la ligne m=, d'où la seconde lecture plus bas.
			if charge, _, _ := strings.Cut(reste, " "); charge == "0" {
				offre.AcceptePCMU = true
			}
		}
	}
	if !offre.AcceptePCMU {
		offre.AcceptePCMU = ligneMédiaPorteLaCharge(brut, ChargePCMU)
	}

	var manque []string
	if offre.Ufrag == "" {
		manque = append(manque, "ice-ufrag")
	}
	if offre.MotDePasse == "" {
		manque = append(manque, "ice-pwd")
	}
	if offre.Empreinte == "" {
		manque = append(manque, "fingerprint")
	}
	if !offre.AcceptePCMU {
		manque = append(manque, "PCMU")
	}
	if manque != nil {
		return offre, fmt.Errorf("offre inutilisable, il manque : %s",
			strings.Join(manque, ", "))
	}
	return offre, nil
}

// ligneMédiaPorteLaCharge dit si la ligne « m=audio » liste ce type.
func ligneMédiaPorteLaCharge(brut []byte, charge int) bool {
	for _, ligne := range strings.Split(string(brut), "\n") {
		ligne = strings.TrimRight(ligne, "\r")
		if !strings.HasPrefix(ligne, "m=audio ") {
			continue
		}
		champs := strings.Fields(ligne)
		for _, champ := range champs[3:] {
			if n, err := strconv.Atoi(champ); err == nil && n == charge {
				return true
			}
		}
	}
	return false
}

// RéponseSDP décrit ce qu'on annonce au navigateur.
type RéponseSDP struct {
	Adresse   net.IP
	Port      int
	Identité  IdentitéICE
	Empreinte string // « sha-256 AB:CD:... »
	Mid       string
	Bundle    bool
	Session   uint64
}

// Construire rend la réponse SDP, prête à partir dans le 200 OK.
//
// Quatre attributs décident à eux seuls que le son circule, et leur absence
// ne produit aucun message d'erreur :
//
//   - « a=ice-lite », qui dit au navigateur de mener la vérification seul ;
//   - « a=setup:passive », qui fait de nous le SERVEUR DTLS. Le navigateur
//     offre « actpass » et devient client ; répondre « active » laisserait
//     les deux attendre l'autre ;
//   - « a=rtcp-mux », sans quoi le navigateur ouvre un second flux dont
//     personne ici ne s'occupe ;
//   - le candidat hôte, qui donne l'adresse où envoyer les vérifications.
func (r RéponseSDP) Construire() []byte {
	adresse := r.Adresse.String()
	lignes := []string{
		"v=0",
		fmt.Sprintf("o=- %d 1 IN IP4 %s", r.Session, adresse),
		"s=-",
		"t=0 0",
		// Un agent allégé le déclare : le navigateur cesse alors d'attendre
		// nos propres vérifications de connectivité, qui ne viendront pas.
		"a=ice-lite",
	}
	if r.Bundle && r.Mid != "" {
		lignes = append(lignes, "a=group:BUNDLE "+r.Mid)
	}
	lignes = append(lignes,
		fmt.Sprintf("m=audio %d %s %d", r.Port, ProtoWebRTC, ChargePCMU),
		"c=IN IP4 "+adresse,
		"a=rtcp-mux",
		"a=ice-ufrag:"+r.Identité.Ufrag,
		"a=ice-pwd:"+r.Identité.MotDePasse,
		fmt.Sprintf("a=candidate:1 1 udp %d %s %d typ host",
			PrioritéCandidatHôte, adresse, r.Port),
		// Sans cette ligne le navigateur attend d'autres candidats jusqu'à
		// l'expiration de son minuteur avant de conclure.
		"a=end-of-candidates",
		"a=fingerprint:"+r.Empreinte,
		"a=setup:passive",
		"a=sendrecv",
		fmt.Sprintf("a=rtpmap:%d PCMU/8000", ChargePCMU),
		fmt.Sprintf("a=ptime:%d", PaquetisationMs),
	)
	if r.Mid != "" {
		lignes = append(lignes, "a=mid:"+r.Mid)
	}
	return []byte(strings.Join(lignes, "\r\n") + "\r\n")
}
