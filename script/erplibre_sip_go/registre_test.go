package main

import (
	"testing"
	"time"

	"github.com/emiago/sipgo/sip"
)

func inscriptionDe(t *testing.T, poste, source string, expires string) *sip.Request {
	t.Helper()
	req := sip.NewRequest(sip.REGISTER, sip.Uri{Host: "127.0.0.1"})
	req.AppendHeader(&sip.FromHeader{
		Address: sip.Uri{User: poste, Host: "127.0.0.1"},
		Params:  sip.NewParams(),
	})
	req.AppendHeader(&sip.ContactHeader{
		Address: sip.Uri{User: poste, Host: "cd0mq4gsv651.invalid"},
		Params:  sip.NewParams(),
	})
	if expires != "" {
		req.AppendHeader(sip.NewHeader("Expires", expires))
	}
	req.SetTransport("ws")
	req.SetSource(source)
	return req
}

// Le contact d'un softphone de navigateur ne mene nulle part : seule
// l'adresse D'OU l'inscription est venue permet de le rappeler.
func TestLInscriptionRetientLAdresseVueEtNonLeContact(t *testing.T) {
	registre := NouveauRegistre()
	maintenant := time.Now()

	inscrite, err := registre.Inscrire(
		inscriptionDe(t, "1001", "192.168.1.38:48774", "3600"), maintenant)
	if err != nil {
		t.Fatalf("inscription : %v", err)
	}
	if inscrite.Source != "192.168.1.38:48774" {
		t.Fatalf("source %q : on ne saura pas ou rappeler", inscrite.Source)
	}
	if inscrite.Contact.Host != "cd0mq4gsv651.invalid" {
		t.Fatalf("contact %q", inscrite.Contact.Host)
	}
	if inscrite.Transport != "ws" {
		t.Fatalf("transport %q : l'appel ne suivra pas la connexion", inscrite.Transport)
	}

	trouvée, connue := registre.Trouver("1001", maintenant)
	if !connue || trouvée.Source != inscrite.Source {
		t.Fatal("le poste inscrit ne se retrouve pas")
	}
}

// Une duree nulle est un DESABONNEMENT : le confondre avec une inscription
// qui expire aussitot laisserait une entree morte jusqu'au nettoyage.
func TestUneDureeNulleDesabonne(t *testing.T) {
	registre := NouveauRegistre()
	maintenant := time.Now()
	registre.Inscrire(inscriptionDe(t, "1001", "192.168.1.38:1", "3600"), maintenant)

	if _, connue := registre.Trouver("1001", maintenant); !connue {
		t.Fatal("le poste n'a pas été inscrit")
	}
	registre.Inscrire(inscriptionDe(t, "1001", "192.168.1.38:1", "0"), maintenant)
	if _, connue := registre.Trouver("1001", maintenant); connue {
		t.Fatal("le poste reste inscrit après un désabonnement")
	}
}

// Une inscription qui survit des jours designe longtemps une connexion morte,
// et l'appel entrant part alors vers personne.
func TestUneDureeExcessiveEstBornee(t *testing.T) {
	registre := NouveauRegistre()
	maintenant := time.Now()
	inscrite, _ := registre.Inscrire(
		inscriptionDe(t, "1001", "192.168.1.38:1", "999999"), maintenant)

	if inscrite.Expire.After(maintenant.Add(DuréeInscriptionMax + time.Second)) {
		t.Fatalf("expiration %v : la borne n'est pas appliquée", inscrite.Expire)
	}
}

func TestUneInscriptionExpireeNeSeTrouvePlus(t *testing.T) {
	registre := NouveauRegistre()
	départ := time.Now()
	registre.Inscrire(inscriptionDe(t, "1001", "192.168.1.38:1", "60"), départ)

	if _, connue := registre.Trouver("1001", départ.Add(30*time.Second)); !connue {
		t.Fatal("trouvée absente avant son terme")
	}
	if _, connue := registre.Trouver("1001", départ.Add(2*time.Minute)); connue {
		t.Fatal("une inscription expirée se trouve encore")
	}
	if len(registre.Joignables(départ.Add(2*time.Minute))) != 0 {
		t.Fatal("une inscription expirée est annoncée joignable")
	}
}

// Le parametre du contact prime sur l'en-tete : la RFC 3261 §10.2.4 le veut,
// et c'est par lui qu'un client se desabonne d'un seul contact.
func TestLeParametreDuContactPrimeSurLEntete(t *testing.T) {
	registre := NouveauRegistre()
	maintenant := time.Now()
	req := inscriptionDe(t, "1001", "192.168.1.38:1", "3600")
	req.Contact().Params.Add("expires", "0")

	registre.Inscrire(req, maintenant)
	if _, connue := registre.Trouver("1001", maintenant); connue {
		t.Fatal("le désabonnement par le contact a été ignoré")
	}
}

func TestUneInscriptionIncompleteEstRefusee(t *testing.T) {
	registre := NouveauRegistre()
	sansContact := sip.NewRequest(sip.REGISTER, sip.Uri{Host: "127.0.0.1"})
	sansContact.AppendHeader(&sip.FromHeader{
		Address: sip.Uri{User: "1001", Host: "127.0.0.1"},
		Params:  sip.NewParams(),
	})
	if _, err := registre.Inscrire(sansContact, time.Now()); err == nil {
		t.Fatal("acceptée sans contact : on ne saurait pas où rappeler")
	}
}

// Une nouvelle inscription remplace l'ancienne : un onglet rouvert change de
// port, et garder les deux ferait sonner une connexion morte.
func TestUneNouvelleInscriptionRemplaceLAncienne(t *testing.T) {
	registre := NouveauRegistre()
	maintenant := time.Now()
	registre.Inscrire(inscriptionDe(t, "1001", "192.168.1.38:1", "3600"), maintenant)
	registre.Inscrire(inscriptionDe(t, "1001", "192.168.1.38:2", "3600"), maintenant)

	trouvée, _ := registre.Trouver("1001", maintenant)
	if trouvée.Source != "192.168.1.38:2" {
		t.Fatalf("source %q : l'ancienne inscription survit", trouvée.Source)
	}
	if len(registre.Joignables(maintenant)) != 1 {
		t.Fatal("deux inscriptions pour un seul poste")
	}
}

// La RFC 3261 §8.1.1.3 exige un « tag » sur le « From » de toute requete qui
// etablit un dialogue : c'est une moitie de son identifiant. Sans lui la pile
// refuse la reponse, et l'appel entrant part en boite vocale.
func TestLInviteEntrantPorteUnTagDeDialogue(t *testing.T) {
	inscription := Inscription{
		Poste:     "1001",
		Contact:   sip.Uri{User: "1001", Host: "cd0mq4gsv651.invalid"},
		Source:    "192.168.1.38:48774",
		Transport: "ws",
	}
	invite := ConstruireInviteEntrant(inscription, "127.0.0.1", "15145550142",
		[]byte("v=0\r\n"))

	from := invite.From()
	if from == nil {
		t.Fatal("aucun en-tête From")
	}
	tag, présent := from.Params.Get("tag")
	if !présent || tag == "" {
		t.Fatal("From sans tag : la pile refusera la réponse du softphone")
	}
	if invite.Destination() != inscription.Source {
		t.Fatalf("destination %q : l'INVITE partira en résolution DNS",
			invite.Destination())
	}
	if invite.From().Address.User != "15145550142" {
		t.Fatalf("appelant affiché : %q", invite.From().Address.User)
	}
	if ct := invite.ContentType(); ct == nil || ct.Value() != "application/sdp" {
		t.Fatal("INVITE sans type de contenu SDP")
	}
}

// Deux appels ne doivent pas partager un identifiant de dialogue.
func TestDeuxInvitesNePartagentPasLeurTag(t *testing.T) {
	inscription := Inscription{Contact: sip.Uri{Host: "x.invalid"}, Source: "1.2.3.4:5"}
	une := ConstruireInviteEntrant(inscription, "127.0.0.1", "1", nil)
	deux := ConstruireInviteEntrant(inscription, "127.0.0.1", "1", nil)
	tagUne, _ := une.From().Params.Get("tag")
	tagDeux, _ := deux.From().Params.Get("tag")
	if tagUne == tagDeux {
		t.Fatal("deux appels partagent leur identifiant de dialogue")
	}
}

// Sans acquittement, le navigateur retransmet son 200 OK puis abandonne, et
// la ligne cellulaire est raccrochee pendant qu'elle sonnait : l'operateur la
// renvoie vers sa messagerie. L'acquittement doit donc viser la connexion
// ouverte, et non le contact « .invalid » de la reponse.
func TestLAcquittementViseLaConnexionOuverte(t *testing.T) {
	inscription := Inscription{
		Contact:   sip.Uri{User: "1001", Host: "8lk7a7svdi2b.invalid"},
		Source:    "192.168.1.38:48774",
		Transport: "ws",
	}
	invite := ConstruireInviteEntrant(inscription, "127.0.0.1", "15145550142", nil)
	invite.AppendHeader(sip.NewHeader("Call-ID", "appel-de-test"))
	cseq := sip.CSeqHeader{SeqNo: 7, MethodName: sip.INVITE}
	invite.AppendHeader(&cseq)

	réponse := sip.NewResponseFromRequest(invite, 200, "OK", nil)
	réponse.AppendHeader(&sip.ContactHeader{
		Address: sip.Uri{User: "1001", Host: "8lk7a7svdi2b.invalid"},
		Params:  sip.NewParams(),
	})
	àNous := sip.NewParams()
	àNous.Add("tag", "tag-du-softphone")
	réponse.RemoveHeader("To")
	réponse.AppendHeader(&sip.ToHeader{
		Address: sip.Uri{User: "1001", Host: "127.0.0.1"}, Params: àNous,
	})

	ack := ConstruireAckEntrant(invite, réponse, inscription.Source)

	if ack.Destination() != inscription.Source {
		t.Fatalf("destination %q : l'acquittement part en résolution DNS",
			ack.Destination())
	}
	if ack.Method != sip.ACK {
		t.Fatalf("méthode %v", ack.Method)
	}
	// Le numéro de séquence est celui de l'INVITE : c'est ce qui rattache
	// l'acquittement à la transaction qu'il clôt.
	if c := ack.CSeq(); c == nil || c.SeqNo != 7 || c.MethodName != sip.ACK {
		t.Fatalf("CSeq inattendu : %v", ack.CSeq())
	}
	// Le « To » vient de la REPONSE : c'est la que le softphone a pose sa
	// moitie de l'identifiant du dialogue.
	if to := ack.To(); to == nil {
		t.Fatal("acquittement sans To")
	} else if tag, _ := to.Params.Get("tag"); tag != "tag-du-softphone" {
		t.Fatalf("tag du To : %q — le dialogue ne sera pas reconnu", tag)
	}
	if id := ack.CallID(); id == nil || id.Value() != "appel-de-test" {
		t.Fatalf("Call-ID : %v", ack.CallID())
	}
}
