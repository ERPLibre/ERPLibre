package main

import (
	"strings"
	"testing"
	"time"

	"github.com/emiago/sipgo/sip"
	"github.com/icholy/digest"
)

func TestLesComptesSeLisent(t *testing.T) {
	comptes, err := LireComptes("1001:premier;1002:second")
	if err != nil {
		t.Fatalf("lecture : %v", err)
	}
	if comptes["1001"] != "premier" || comptes["1002"] != "second" {
		t.Fatalf("comptes lus : %v", comptes)
	}
}

// Un point-virgule de trop laisserait un poste sans mot de passe, et la panne
// se presenterait comme un refus d'inscription sans cause visible.
func TestUnCompteMalFormeEstRefuse(t *testing.T) {
	for _, brut := range []string{"1001", "1001:", ":motdepasse", "1001:mdp;1002"} {
		if _, err := LireComptes(brut); err == nil {
			t.Fatalf("%q accepté alors qu'il est mal formé", brut)
		}
	}
}

// Le choix qui compte : sans compte et sans renoncement explicite, il n'y a
// PAS de service. Demarrer en laissant la ligne ouverte a tous serait le pire
// des deux mondes, puisque plus rien ne le signale ensuite.
func TestSansCompteLeServiceRefuseDeDemarrer(t *testing.T) {
	if _, err := NouveauGardien("", false); err == nil {
		t.Fatal("le service démarre sans aucun compte configuré")
	}
	gardien, err := NouveauGardien("", true)
	if err != nil {
		t.Fatalf("le renoncement explicite est refusé : %v", err)
	}
	defer gardien.Fermer()
}

func requêteRegister(t *testing.T, poste string) *sip.Request {
	t.Helper()
	req := sip.NewRequest(sip.REGISTER, sip.Uri{Host: "127.0.0.1"})
	req.AppendHeader(&sip.FromHeader{
		Address: sip.Uri{User: poste, Host: "127.0.0.1"},
		Params:  sip.NewParams(),
	})
	return req
}

// Un transport de test : on garde la reponse au lieu de l'envoyer.
type transactionMuette struct {
	sip.ServerTransaction
	réponse *sip.Response
}

func (t *transactionMuette) Respond(res *sip.Response) error {
	t.réponse = res
	return nil
}

func TestUnePremiereRequeteRecoitUnDefi(t *testing.T) {
	gardien, err := NouveauGardien("1001:motdepasse", false)
	if err != nil {
		t.Fatalf("gardien : %v", err)
	}
	defer gardien.Fermer()

	tx := &transactionMuette{}
	if gardien.Autoriser(requêteRegister(t, "1001"), tx) {
		t.Fatal("acceptée sans le moindre identifiant")
	}
	if tx.réponse == nil || tx.réponse.StatusCode != 401 {
		t.Fatalf("réponse %v au lieu d'un défi 401", tx.réponse)
	}
	if tx.réponse.GetHeader("WWW-Authenticate") == nil {
		t.Fatal("défi sans en-tête WWW-Authenticate : le client ne peut pas répondre")
	}
}

// Le tour complet : defi, puis reponse signee avec le bon mot de passe.
func TestLeBonMotDePasseOuvre(t *testing.T) {
	gardien, err := NouveauGardien("1001:motdepasse", false)
	if err != nil {
		t.Fatalf("gardien : %v", err)
	}
	defer gardien.Fermer()

	défi := &transactionMuette{}
	gardien.Autoriser(requêteRegister(t, "1001"), défi)
	chal, err := digest.ParseChallenge(défi.réponse.GetHeader("WWW-Authenticate").Value())
	if err != nil {
		t.Fatalf("défi illisible : %v", err)
	}

	signée := requêteRegister(t, "1001")
	cred, err := digest.Digest(chal, digest.Options{
		Method: "REGISTER", URI: "sip:127.0.0.1",
		Username: "1001", Password: "motdepasse",
	})
	if err != nil {
		t.Fatalf("signature : %v", err)
	}
	signée.AppendHeader(sip.NewHeader("Authorization", cred.String()))

	if !gardien.Autoriser(signée, &transactionMuette{}) {
		t.Fatal("le bon mot de passe est refusé")
	}
}

func TestUnMauvaisMotDePasseEstRefuse(t *testing.T) {
	gardien, _ := NouveauGardien("1001:motdepasse", false)
	defer gardien.Fermer()

	défi := &transactionMuette{}
	gardien.Autoriser(requêteRegister(t, "1001"), défi)
	chal, _ := digest.ParseChallenge(défi.réponse.GetHeader("WWW-Authenticate").Value())

	signée := requêteRegister(t, "1001")
	cred, _ := digest.Digest(chal, digest.Options{
		Method: "REGISTER", URI: "sip:127.0.0.1",
		Username: "1001", Password: "pas-le-bon",
	})
	signée.AppendHeader(sip.NewHeader("Authorization", cred.String()))

	tx := &transactionMuette{}
	if gardien.Autoriser(signée, tx) {
		t.Fatal("un mot de passe faux est accepté")
	}
	if tx.réponse == nil || tx.réponse.StatusCode == 200 {
		t.Fatalf("réponse inattendue : %v", tx.réponse)
	}
}

// Un poste inconnu doit etre traite EXACTEMENT comme un mot de passe faux :
// distinguer les deux dirait a qui sonde quels comptes existent.
func TestUnPosteInconnuNeSeDistinguePasDUnMauvaisMotDePasse(t *testing.T) {
	gardien, _ := NouveauGardien("1001:motdepasse", false)
	defer gardien.Fermer()

	connu := &transactionMuette{}
	gardien.Autoriser(requêteRegister(t, "1001"), connu)
	inconnu := &transactionMuette{}
	gardien.Autoriser(requêteRegister(t, "9999"), inconnu)

	if connu.réponse.StatusCode != inconnu.réponse.StatusCode {
		t.Fatalf("codes différents : %d pour un poste connu, %d pour un inconnu",
			connu.réponse.StatusCode, inconnu.réponse.StatusCode)
	}
}

// Se fier au seul « From » laisserait presenter un compte et en signer un
// autre.
func TestLeNomSigneLemporteSurCeluiAnnonce(t *testing.T) {
	req := requêteRegister(t, "1001")
	req.AppendHeader(sip.NewHeader("Authorization",
		`Digest username="9999", realm="erplibre", nonce="x", uri="sip:x", response="y"`))
	if poste := posteDemandé(req); poste != "9999" {
		t.Fatalf("poste retenu %q : c'est celui de « From », pas celui signé", poste)
	}
	if poste := posteDemandé(requêteRegister(t, "1001")); poste != "1001" {
		t.Fatalf("sans en-tête signé, « From » doit servir : %q", poste)
	}
}

func TestLeRenoncementExpliciteLaisseToutPasser(t *testing.T) {
	gardien, _ := NouveauGardien("", true)
	defer gardien.Fermer()
	if !gardien.Autoriser(requêteRegister(t, "nimporte-qui"), &transactionMuette{}) {
		t.Fatal("refusé alors que l'authentification est explicitement levée")
	}
}

func TestLeMessageDeRefusDitCommentSeConfigurer(t *testing.T) {
	_, err := NouveauGardien("", false)
	if err == nil {
		t.Fatal("aucune erreur")
	}
	for _, attendu := range []string{VariablePostes, "sans-authentification"} {
		if !strings.Contains(err.Error(), attendu) {
			t.Fatalf("« %s » absent du message : %s", attendu, err)
		}
	}
}

// Un nonce que le service ne connait pas n'est PAS un refus : c'est un defi
// perime, ou celui d'avant un redemarrage, qu'un client rejoue de bonne foi.
// La bibliotheque rend alors un 401 SANS defi — un client ne peut rien en
// faire et attend l'expiration d'un minuteur avant de repartir de zero.
func TestUnNonceInconnuRedonneUnDefi(t *testing.T) {
	gardien, err := NouveauGardien("1001:motdepasse", false)
	if err != nil {
		t.Fatalf("gardien : %v", err)
	}
	defer gardien.Fermer()

	rejouée := requêteRegister(t, "1001")
	rejouée.AppendHeader(sip.NewHeader("Authorization",
		`Digest username="1001", realm="erplibre", nonce="nonce-d-avant-le-redemarrage", `+
			`uri="sip:127.0.0.1", response="00000000000000000000000000000000"`))

	tx := &transactionMuette{}
	if gardien.Autoriser(rejouée, tx) {
		t.Fatal("acceptée avec un nonce inconnu")
	}
	if tx.réponse == nil || tx.réponse.StatusCode != 401 {
		t.Fatalf("réponse %v", tx.réponse)
	}
	if tx.réponse.GetHeader("WWW-Authenticate") == nil {
		t.Fatal("401 sans défi : le client ne peut rien en faire et attendra " +
			"l'expiration d'un minuteur")
	}
}

// Cinq secondes est le defaut de la bibliotheque, et il ne tient pas : un
// client renouvelle son inscription toutes les dix minutes.
func TestLeDefiVitAssezLongtempsPourUnRenouvellement(t *testing.T) {
	if DuréeDéfi < time.Minute {
		t.Fatalf("un défi de %v sera périmé à chaque renouvellement", DuréeDéfi)
	}
}
