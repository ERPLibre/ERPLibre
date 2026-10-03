// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/emiago/sipgo"
	"github.com/emiago/sipgo/sip"
)

// portLibre rend un port TCP que personne ne tient, puis le rend.
func portLibre(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().String()
}

// softphoneDEssai monte un poste qui s'inscrit en WebSocket et annonce, comme
// un navigateur, un contact en « .invalid » que nul DNS ne résout.
//
// C'est la seule façon de rejouer la présentation d'un appel entrant sans
// modem ni carte SIM : le défaut qu'il attrape ne se voit autrement qu'en
// appelant un vrai numéro.
func softphoneDEssai(t *testing.T, adresseServeur, poste, contact string,
	invites chan<- *sip.Request, décroche bool, byes chan<- *sip.Request) {

	t.Helper()
	ua, err := sipgo.NewUA()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ua.Close() })

	srv, err := sipgo.NewServer(ua)
	if err != nil {
		t.Fatal(err)
	}
	srv.OnInvite(func(req *sip.Request, tx sip.ServerTransaction) {
		invites <- req
		_ = tx.Respond(sip.NewResponseFromRequest(req, 180, "Ringing", nil))
		if !décroche {
			return
		}
		réponse := sip.NewResponseFromRequest(req, 200, "OK", []byte("v=0\r\n"))
		réponse.AppendHeader(&sip.ContactHeader{
			Address: sip.Uri{User: poste, Host: contact, UriParams: sip.NewParams()},
			Params:  sip.NewParams(),
		})
		_ = tx.Respond(réponse)
	})
	srv.OnAck(func(req *sip.Request, tx sip.ServerTransaction) {})
	srv.OnBye(func(req *sip.Request, tx sip.ServerTransaction) {
		if byes != nil {
			byes <- req
		}
		_ = tx.Respond(sip.NewResponseFromRequest(req, 200, "OK", nil))
	})

	client, err := sipgo.NewClient(ua)
	if err != nil {
		t.Fatal(err)
	}

	de := sip.Uri{User: poste, Host: adresseServeur}
	req := sip.NewRequest(sip.REGISTER, sip.Uri{Host: adresseServeur})
	req.AppendHeader(&sip.FromHeader{Address: de, Params: sip.NewParams()})
	req.AppendHeader(&sip.ToHeader{Address: de, Params: sip.NewParams()})
	req.AppendHeader(&sip.ContactHeader{
		Address: sip.Uri{User: poste, Host: contact, UriParams: sip.NewParams()},
		Params:  sip.NewParams(),
	})
	req.AppendHeader(sip.NewHeader("Expires", "3600"))
	req.SetTransport("ws")
	req.SetDestination(adresseServeur)

	ctx, arrêter := context.WithTimeout(context.Background(), 5*time.Second)
	defer arrêter()
	tx, err := client.TransactionRequest(ctx, req)
	if err != nil {
		t.Fatalf("inscription du poste d'essai : %v", err)
	}
	defer tx.Terminate()
	select {
	case rép := <-tx.Responses():
		if rép.StatusCode != 200 {
			t.Fatalf("inscription refusee : %d", rép.StatusCode)
		}
	case <-ctx.Done():
		t.Fatal("aucune reponse a l'inscription")
	}
}

// serveurDEssai monte le registre et la pile SIP du service, en WebSocket.
//
// Rend l'adresse d'écoute, le registre et le cache de dialogues : de quoi
// présenter un appel entrant à un poste, sans modem ni carte SIM.
func serveurDEssai(t *testing.T) (string, *Registre, *sipgo.DialogClientCache,
	context.Context) {

	t.Helper()
	adresse := portLibre(t)

	ua, err := sipgo.NewUA()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ua.Close() })
	srv, err := sipgo.NewServer(ua)
	if err != nil {
		t.Fatal(err)
	}
	registre := NouveauRegistre()
	srv.OnRegister(func(req *sip.Request, tx sip.ServerTransaction) {
		if _, err := registre.Inscrire(req, time.Now()); err != nil {
			t.Errorf("inscription non retenue : %v", err)
		}
		_ = tx.Respond(sip.NewResponseFromRequest(req, 200, "OK", nil))
	})
	client, err := sipgo.NewClient(ua)
	if err != nil {
		t.Fatal(err)
	}
	dialogues := sipgo.NewDialogClientCache(client, sip.ContactHeader{
		Address: sip.Uri{User: "erplibre", Host: adresse},
	})

	ctx, arrêter := context.WithCancel(context.Background())
	t.Cleanup(arrêter)
	go func() {
		_ = srv.ListenAndServe(ctx, "ws", adresse)
	}()
	// Le serveur met un instant à tenir le port ; sans cette attente le poste
	// d'essai se verrait refuser sa connexion.
	for i := 0; i < 50; i++ {
		c, err := net.Dial("tcp", adresse)
		if err == nil {
			c.Close()
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	return adresse, registre, dialogues, ctx
}

func TestLInviteAtteintUnSoftphoneAuContactInvalide(t *testing.T) {
	adresse, registre, dialogues, ctx := serveurDEssai(t)

	invites := make(chan *sip.Request, 1)
	softphoneDEssai(t, adresse, "1001", "abc123xyz.invalid", invites, false, nil)

	inscription, joignable := registre.Trouver("1001", time.Now())
	if !joignable {
		t.Fatal("le poste ne s'est pas inscrit")
	}
	t.Logf("inscription : source=%q transport=%q contact=%q",
		inscription.Source, inscription.Transport, inscription.Contact.String())

	// La fenêtre de sonnerie, courte ici, est celle que le répondeur impose
	// en service : c'est le contexte REÇU qui la porte.
	minuté, finir := context.WithTimeout(ctx, 700*time.Millisecond)
	defer finir()
	session, err := sonner(minuté, dialogues, inscription, adresse, "15550100",
		[]byte("v=0\r\n"))
	if session != nil {
		defer session.Close()
	}

	select {
	case req := <-invites:
		t.Logf("le softphone a recu l'INVITE : %s", req.StartLine())
	default:
		t.Fatalf("le softphone n'a recu aucun INVITE ; sonner a rendu : %v", err)
	}

	// Le poste d'essai ne décroche jamais : sonner doit le DIRE, et non
	// rapporter l'échec de résolution du contact « .invalid » que sipgo
	// produit en annulant de son côté.
	if err == nil {
		t.Fatal("sonner a rendu un decroche alors que personne n'a repondu")
	}
	if !strings.Contains(err.Error(), "aucun decroche") {
		t.Fatalf("motif %q, attendu qu'il nomme l'absence de decroche", err)
	}
	if strings.Contains(err.Error(), "lookup") || strings.Contains(err.Error(), "SRV") {
		t.Fatalf("motif %q : la resolution DNS du contact masque la cause", err)
	}
}

func TestLeRaccrochageAtteintLeSoftphoneQuiADecroche(t *testing.T) {
	adresse, registre, dialogues, ctx := serveurDEssai(t)

	invites := make(chan *sip.Request, 1)
	byes := make(chan *sip.Request, 1)
	softphoneDEssai(t, adresse, "1001", "zzz999plq.invalid", invites, true, byes)

	inscription, joignable := registre.Trouver("1001", time.Now())
	if !joignable {
		t.Fatal("le poste ne s'est pas inscrit")
	}

	minuté, finir := context.WithTimeout(ctx, 5*time.Second)
	defer finir()
	session, err := sonner(minuté, dialogues, inscription, adresse, "15550100",
		[]byte("v=0\r\n"))
	if err != nil {
		t.Fatalf("le poste a decroche mais sonner a echoue : %v", err)
	}
	defer session.Close()

	// Le correspondant raccroche : c'est à NOUS de le dire au poste. Sans
	// acquittement de sa part, l'appel reste affiché à l'écran et le
	// raccrochage attend son échéance entière.
	if err := raccrocherLAppelant(ctx, session, inscription.Source); err != nil {
		t.Fatalf("raccrochage : %v", err)
	}
	select {
	case <-byes:
	case <-time.After(3 * time.Second):
		t.Fatal("le softphone n'a recu aucun BYE")
	}
}
