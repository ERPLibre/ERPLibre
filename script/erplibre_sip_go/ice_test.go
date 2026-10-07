package main

import (
	"net"
	"testing"

	"github.com/pion/stun/v3"
)

// Le socket média porte TROIS protocoles. Les confondre donne un appel qui
// s'établit et reste muet, sans rien dans les journaux.
func TestLesTroisProtocolesSeDistinguent(t *testing.T) {
	cas := []struct {
		nom     string
		premier byte
		attendu NatureDuPaquet
	}{
		{"STUN, borne basse", 0, PaquetSTUN},
		{"STUN, borne haute", 3, PaquetSTUN},
		{"DTLS, borne basse", 20, PaquetDTLS},
		{"DTLS, borne haute", 63, PaquetDTLS},
		{"RTP, borne basse", 128, PaquetRTP},
		{"RTP, borne haute", 191, PaquetRTP},
		{"entre DTLS et RTP", 100, PaquetInconnu},
	}
	for _, k := range cas {
		t.Run(k.nom, func(t *testing.T) {
			if got := Nature([]byte{k.premier, 0, 0, 0}); got != k.attendu {
				t.Fatalf("octet %d classe %v, attendu %v", k.premier, got, k.attendu)
			}
		})
	}
	if Nature(nil) != PaquetInconnu {
		t.Fatal("un paquet vide doit rester inconnu")
	}
}

func identités(t *testing.T) (IdentitéICE, IdentitéICE) {
	t.Helper()
	locale, err := NouvelleIdentitéICE()
	if err != nil {
		t.Fatalf("identité locale : %v", err)
	}
	distante, err := NouvelleIdentitéICE()
	if err != nil {
		t.Fatalf("identité distante : %v", err)
	}
	return locale, distante
}

// Construit la requête telle que le navigateur l'envoie.
func requêteDuNavigateur(t *testing.T, nom, motDePasse string) []byte {
	t.Helper()
	message, err := stun.Build(
		stun.TransactionID,
		stun.BindingRequest,
		stun.NewUsername(nom),
		stun.NewShortTermIntegrity(motDePasse),
		stun.Fingerprint,
	)
	if err != nil {
		t.Fatalf("construction : %v", err)
	}
	return message.Raw
}

func TestUneVerificationValideEstAcceptee(t *testing.T) {
	locale, distante := identités(t)
	agent := &AgentICELite{Locale: locale, Distante: distante}
	source := &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 51234}

	brut := requêteDuNavigateur(t, locale.Ufrag+":"+distante.Ufrag, locale.MotDePasse)
	réponse, err := agent.Répondre(brut, source)
	if err != nil {
		t.Fatalf("refusée : %v", err)
	}
	if réponse == nil {
		t.Fatal("aucune réponse : le navigateur conclura que la voie est morte")
	}

	message := &stun.Message{Raw: réponse}
	if err := message.Decode(); err != nil {
		t.Fatalf("réponse illisible : %v", err)
	}
	if message.Type != stun.BindingSuccess {
		t.Fatalf("type %v au lieu d'un succès", message.Type)
	}
	// Le navigateur vérifie les deux, et jette la réponse si l'une manque.
	if err := stun.NewShortTermIntegrity(locale.MotDePasse).Check(message); err != nil {
		t.Fatalf("intégrité absente ou fausse : %v", err)
	}
	if err := stun.Fingerprint.Check(message); err != nil {
		t.Fatalf("empreinte absente ou fausse : %v", err)
	}
}

// L'adresse VUE, et non celle que le SDP annonçait : c'est la seule qui mène
// au navigateur quand il est derrière une traduction d'adresses.
func TestLaReponsePorteLAdresseVue(t *testing.T) {
	locale, distante := identités(t)
	agent := &AgentICELite{Locale: locale, Distante: distante}
	source := &net.UDPAddr{IP: net.IPv4(192, 0, 2, 33), Port: 41000}

	réponse, _ := agent.Répondre(
		requêteDuNavigateur(t, locale.Ufrag+":"+distante.Ufrag, locale.MotDePasse),
		source,
	)
	message := &stun.Message{Raw: réponse}
	if err := message.Decode(); err != nil {
		t.Fatalf("réponse illisible : %v", err)
	}
	var vue stun.XORMappedAddress
	if err := vue.GetFrom(message); err != nil {
		t.Fatalf("adresse absente : %v", err)
	}
	if !vue.IP.Equal(source.IP) || vue.Port != source.Port {
		t.Fatalf("adresse %v:%d au lieu de %v", vue.IP, vue.Port, source)
	}
	if agent.Pair().String() != source.String() {
		t.Fatalf("pair retenu %v au lieu de %v", agent.Pair(), source)
	}
}

// Le silence est voulu : repondre apprendrait a qui sonde quel champ corriger.
func TestCeQuiNeSePresentePasBienResteSansReponse(t *testing.T) {
	locale, distante := identités(t)
	source := &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 51234}

	cas := []struct {
		nom  string
		brut func() []byte
	}{
		{"mot de passe faux", func() []byte {
			return requêteDuNavigateur(t, locale.Ufrag+":"+distante.Ufrag, "pas-le-bon")
		}},
		{"destinataire etranger", func() []byte {
			return requêteDuNavigateur(t, "quelquun-dautre:"+distante.Ufrag, locale.MotDePasse)
		}},
		{"emetteur inattendu", func() []byte {
			return requêteDuNavigateur(t, locale.Ufrag+":inconnu", locale.MotDePasse)
		}},
		{"nom sans deux-points", func() []byte {
			return requêteDuNavigateur(t, locale.Ufrag, locale.MotDePasse)
		}},
		{"octets quelconques", func() []byte { return []byte{0, 1, 2, 3, 4, 5} }},
	}
	for _, k := range cas {
		t.Run(k.nom, func(t *testing.T) {
			agent := &AgentICELite{Locale: locale, Distante: distante}
			réponse, err := agent.Répondre(k.brut(), source)
			if err != nil {
				t.Fatalf("erreur inattendue : %v", err)
			}
			if réponse != nil {
				t.Fatal("une reponse est partie")
			}
			if agent.Pair() != nil {
				t.Fatal("un pair a ete retenu sur une verification refusee")
			}
		})
	}
}

// Le navigateur envoie parfois sa premiere verification avant que sa reponse
// SDP ne nous parvienne : la refuser ferait echouer l'appel par une course.
func TestUnPairEncoreInconnuEstAccepte(t *testing.T) {
	locale, _ := identités(t)
	agent := &AgentICELite{Locale: locale}
	source := &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 51234}

	réponse, err := agent.Répondre(
		requêteDuNavigateur(t, locale.Ufrag+":pas-encore-connu", locale.MotDePasse),
		source,
	)
	if err != nil || réponse == nil {
		t.Fatalf("refusée alors que l'ufrag distant est encore inconnu (%v)", err)
	}
}

func TestDeuxIdentitesNeSeRessemblentPas(t *testing.T) {
	une, deux := identités(t)
	if une.Ufrag == deux.Ufrag || une.MotDePasse == deux.MotDePasse {
		t.Fatal("identités identiques : le générateur ne tire rien")
	}
	if len(une.Ufrag) != LongueurUfrag || len(une.MotDePasse) != LongueurMotDePasse {
		t.Fatalf("longueurs %d/%d hors des bornes de la RFC 8445",
			len(une.Ufrag), len(une.MotDePasse))
	}
}

// Le compte rendu et le son partagent un port et un premier octet. Confondre
// les deux fait passer un RTCP pour du son abime, une fois par seconde.
func TestLeCompteRenduNEstPasPrisPourDuSon(t *testing.T) {
	// Second octet 200 : « sender report », le plus courant. Le bit de poids
	// fort est celui du marqueur RTP, d'ou le masque.
	rapport := []byte{0x80, 200, 0, 6}
	if Nature(rapport) != PaquetRTCP {
		t.Fatalf("un rapport d'emetteur est classe %v", Nature(rapport))
	}
	// Type 0 : PCMU. C'est du son, et il doit le rester.
	son := []byte{0x80, 0, 0, 7}
	if Nature(son) != PaquetRTP {
		t.Fatalf("du son PCMU est classe %v", Nature(son))
	}
	// Le marqueur RTP met le bit de poids fort du second octet : un paquet
	// marque reste du son.
	marqué := []byte{0x80, 0x80, 0, 7}
	if Nature(marqué) != PaquetRTP {
		t.Fatalf("du son marque est classe %v", Nature(marqué))
	}
	for _, type_ := range []byte{64, 95} {
		if !EstRTCP([]byte{0x80, type_}) {
			t.Fatalf("le type %d est dans la plage RTCP", type_)
		}
	}
	for _, type_ := range []byte{63, 96} {
		if EstRTCP([]byte{0x80, type_}) {
			t.Fatalf("le type %d est hors de la plage RTCP", type_)
		}
	}
}
