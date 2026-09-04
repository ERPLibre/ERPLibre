package main

import (
	"errors"
	"io/fs"
	"strings"
	"testing"

	"github.com/emiago/sipgo/sip"
)

// « id » montre le bon groupe et l'ouverture echoue quand meme : sans cette
// phrase, on cherche du cote des droits du fichier, ou il n'y a rien.
func TestUnRefusDAccesNommeLaCauseQuiLeProduit(t *testing.T) {
	refus := errors.New("port /dev/erplibre-modem-at : " + fs.ErrPermission.Error())
	expliqué := expliquerPort(&erreurPermission{refus})
	message := expliqué.Error()

	for _, attendu := range []string{"dialout", "sg dialout", "session"} {
		if !strings.Contains(message, attendu) {
			t.Fatalf("« %s » absent du message : %s", attendu, message)
		}
	}
	if !errors.Is(expliqué, fs.ErrPermission) {
		t.Fatal("la cause d'origine ne se retrouve plus")
	}
}

// Une panne qui n'est PAS un refus d'acces ne doit pas recevoir un conseil
// sur les groupes : envoyer chercher au mauvais endroit coute plus cher que
// de ne rien dire.
func TestUneAutrePanneNEstPasHabilleeEnProblemeDeGroupe(t *testing.T) {
	autre := errors.New("le modem ne repond pas")
	if expliquerPort(autre).Error() != autre.Error() {
		t.Fatalf("message modifié : %s", expliquerPort(autre))
	}
}

type erreurPermission struct{ cause error }

func (e *erreurPermission) Error() string { return e.cause.Error() }
func (e *erreurPermission) Is(cible error) bool {
	return cible == fs.ErrPermission
}

// Le contact d'un softphone de navigateur porte un domaine « .invalid » : la
// RFC 7118 l'impose, puisqu'il n'a aucune adresse joignable. Un BYE qui vise
// ce nom part en resolution DNS et n'arrive jamais — l'appel reste alors
// affiche comme actif alors que la ligne est retombee.
func TestLeByeViseLaConnexionEtNonLeContactInvalide(t *testing.T) {
	invite := sip.NewRequest(sip.INVITE, sip.Uri{User: "15145550142", Host: "127.0.0.1"})
	invite.AppendHeader(&sip.ContactHeader{
		Address: sip.Uri{User: "1001", Host: "cd0mq4gsv651.invalid"},
	})
	invite.SetTransport("ws")
	invite.SetSource("192.168.1.38:48774")

	bye, err := ConstruireBye(invite)
	if err != nil {
		t.Fatalf("construction : %v", err)
	}
	if bye.Destination() != "192.168.1.38:48774" {
		t.Fatalf("destination %q : le BYE partira en resolution DNS",
			bye.Destination())
	}
	if bye.Transport() != "ws" {
		t.Fatalf("transport %q : le BYE ne suivra pas la connexion", bye.Transport())
	}
	if bye.Method != sip.BYE {
		t.Fatalf("methode %v", bye.Method)
	}
}

func TestUnInviteSansContactNeProduitPasDeBye(t *testing.T) {
	invite := sip.NewRequest(sip.INVITE, sip.Uri{User: "1", Host: "127.0.0.1"})
	if _, err := ConstruireBye(invite); err == nil {
		t.Fatal("un BYE a ete construit sans contact a viser")
	}
}
