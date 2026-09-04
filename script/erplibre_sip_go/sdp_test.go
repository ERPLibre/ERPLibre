package main

import (
	"net"
	"strings"
	"testing"
)

// Offre telle qu'un navigateur la produit pour une piste audio, reduite a ce
// qui compte ici. Les valeurs sont inventees : une empreinte ou un ufrag pris
// dans une vraie session n'apprendrait rien de plus et vivrait pour toujours
// dans le depot.
const offreDuNavigateur = `v=0
o=- 4611731400430051336 2 IN IP4 127.0.0.1
s=-
t=0 0
a=group:BUNDLE 0
m=audio 51234 UDP/TLS/RTP/SAVPF 111 0 8
c=IN IP4 0.0.0.0
a=rtcp-mux
a=ice-ufrag:F7gI
a=ice-pwd:x9cml/YzichV2+XlhiMu8g
a=fingerprint:sha-256 11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00
a=setup:actpass
a=mid:0
a=sendrecv
a=rtpmap:111 opus/48000/2
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
`

func TestLOffreEstLuePourCeQuiSert(t *testing.T) {
	offre, err := LireOffre([]byte(offreDuNavigateur))
	if err != nil {
		t.Fatalf("offre refusée : %v", err)
	}
	if offre.Ufrag != "F7gI" || offre.MotDePasse != "x9cml/YzichV2+XlhiMu8g" {
		t.Fatalf("identifiants ICE : %q / %q", offre.Ufrag, offre.MotDePasse)
	}
	if !strings.HasPrefix(offre.Empreinte, "sha-256 ") {
		t.Fatalf("empreinte : %q", offre.Empreinte)
	}
	if offre.Mid != "0" || !offre.Bundle || !offre.AccepteRTCPMux || !offre.AcceptePCMU {
		t.Fatalf("attributs manqués : %+v", offre)
	}
}

// PCMU peut n'apparaître QUE sur la ligne m= : c'est un type statique, et
// rien n'oblige un navigateur à le décrire par un rtpmap.
func TestPCMUSeulementSurLaLigneMedia(t *testing.T) {
	sans := strings.ReplaceAll(offreDuNavigateur, "a=rtpmap:0 PCMU/8000\n", "")
	offre, err := LireOffre([]byte(sans))
	if err != nil {
		t.Fatalf("offre refusée : %v", err)
	}
	if !offre.AcceptePCMU {
		t.Fatal("PCMU manqué alors que la ligne m= le liste")
	}
}

// Refuser ici plutôt que trois étapes plus loin, sur un appel muet.
func TestUneOffreInutilisableEstRefuseeTot(t *testing.T) {
	cas := map[string]string{
		"sans ufrag":        "a=ice-ufrag:F7gI\n",
		"sans mot de passe": "a=ice-pwd:x9cml/YzichV2+XlhiMu8g\n",
		"sans empreinte":    "a=fingerprint:sha-256 11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00\n",
	}
	for nom, ligne := range cas {
		t.Run(nom, func(t *testing.T) {
			amputee := strings.ReplaceAll(offreDuNavigateur, ligne, "")
			if _, err := LireOffre([]byte(amputee)); err == nil {
				t.Fatal("acceptée alors qu'un attribut indispensable manque")
			}
		})
	}
	t.Run("sans PCMU", func(t *testing.T) {
		sans := strings.ReplaceAll(offreDuNavigateur, "a=rtpmap:0 PCMU/8000\n", "")
		sans = strings.ReplaceAll(sans, " 111 0 8", " 111")
		if _, err := LireOffre([]byte(sans)); err == nil {
			t.Fatal("acceptée alors que le seul codec commun manque")
		}
	})
}

func réponseDeTest() RéponseSDP {
	identité, _ := NouvelleIdentitéICE()
	return RéponseSDP{
		Adresse:   net.IPv4(127, 0, 0, 1),
		Port:      40100,
		Identité:  identité,
		Empreinte: "sha-256 AA:BB:CC",
		Mid:       "0",
		Bundle:    true,
		Session:   1,
	}
}

// Ces quatre attributs decident que le son circule, et leur absence ne
// produit AUCUN message d'erreur cote navigateur.
func TestLaReponsePorteCeQuiFaitCirculerLeSon(t *testing.T) {
	rendu := string(réponseDeTest().Construire())
	for _, attendu := range []string{
		"a=ice-lite",
		"a=setup:passive",
		"a=rtcp-mux",
		"typ host",
		"a=end-of-candidates",
	} {
		if !strings.Contains(rendu, attendu) {
			t.Fatalf("« %s » absent :\n%s", attendu, rendu)
		}
	}
}

// Un navigateur rejette une reponse en RTP clair, sans autre explication.
func TestLaReponseAnnonceLeProfilSecurise(t *testing.T) {
	rendu := string(réponseDeTest().Construire())
	if !strings.Contains(rendu, "m=audio 40100 UDP/TLS/RTP/SAVPF 0") {
		t.Fatalf("ligne média inattendue :\n%s", rendu)
	}
}

// Un seul codec annonce : le modem est en 8 kHz, comme PCMU. Laisser passer
// Opus imposerait transcodage ET reechantillonnage des deux cotes.
func TestLaReponseNAnnonceQuUnSeulCodec(t *testing.T) {
	rendu := string(réponseDeTest().Construire())
	if strings.Contains(rendu, "opus") || strings.Contains(rendu, "PCMA") {
		t.Fatalf("un autre codec est annoncé :\n%s", rendu)
	}
	if strings.Count(rendu, "a=rtpmap:") != 1 {
		t.Fatalf("plus d'un rtpmap :\n%s", rendu)
	}
}

// Le mid et le groupe BUNDLE viennent de l'offre : les inventer ferait
// rejeter la reponse.
func TestLeMidEtLeBundleSuiventLOffre(t *testing.T) {
	rendu := string(réponseDeTest().Construire())
	if !strings.Contains(rendu, "a=mid:0") || !strings.Contains(rendu, "a=group:BUNDLE 0") {
		t.Fatalf("mid ou bundle absent :\n%s", rendu)
	}
	sans := réponseDeTest()
	sans.Bundle, sans.Mid = false, ""
	if strings.Contains(string(sans.Construire()), "BUNDLE") {
		t.Fatal("un groupe BUNDLE est annoncé alors que l'offre n'en a pas")
	}
}

// Le SDP se termine par CRLF, ligne par ligne : un simple saut de ligne fait
// echouer l'analyse chez certaines piles.
func TestLesLignesSeTerminentEnCRLF(t *testing.T) {
	rendu := string(réponseDeTest().Construire())
	if strings.Contains(strings.ReplaceAll(rendu, "\r\n", ""), "\n") {
		t.Fatal("une ligne se termine sans retour chariot")
	}
	if !strings.HasSuffix(rendu, "\r\n") {
		t.Fatal("le SDP ne se termine pas par CRLF")
	}
}

// L'identite ICE annoncee doit etre celle que l'agent verifiera : deux
// tirages differents donnent un appel qui sonne et reste muet.
func TestLIdentiteAnnonceeEstCelleDeLAgent(t *testing.T) {
	réponse := réponseDeTest()
	rendu := string(réponse.Construire())
	if !strings.Contains(rendu, "a=ice-ufrag:"+réponse.Identité.Ufrag) ||
		!strings.Contains(rendu, "a=ice-pwd:"+réponse.Identité.MotDePasse) {
		t.Fatalf("identité annoncée différente :\n%s", rendu)
	}
}
