// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"testing"

	"github.com/emiago/sipgo/sip"
)

// inviteÀAnnuler monte un INVITE tel qu'il part vers le softphone, Via compris :
// c'est la bibliothèque qui pose le Via au moment de l'envoi, et la branche
// qu'elle y écrit est ce qui désigne la transaction.
func inviteÀAnnuler() *sip.Request {
	invite := sip.NewRequest(sip.INVITE, sip.Uri{User: "15550001", Host: "127.0.0.1"})
	branche := sip.NewParams()
	branche.Add("branch", "z9hG4bK-essai-42")
	via := sip.ViaHeader{ProtocolName: "SIP", ProtocolVersion: "2.0",
		Transport: "WS", Host: "127.0.0.1", Params: branche}
	invite.AppendHeader(&via)
	étiquette := sip.NewParams()
	étiquette.Add("tag", "etiquette-de-depart")
	de := sip.FromHeader{Address: sip.Uri{User: "modem", Host: "127.0.0.1"},
		Params: étiquette}
	invite.AppendHeader(&de)
	vers := sip.ToHeader{Address: sip.Uri{User: "1001", Host: "127.0.0.1"}}
	invite.AppendHeader(&vers)
	identifiant := sip.CallIDHeader("appel-essai")
	invite.AppendHeader(&identifiant)
	séquence := sip.CSeqHeader{SeqNo: 7, MethodName: sip.INVITE}
	invite.AppendHeader(&séquence)
	return invite
}

func TestLAnnulationDesigneLaMemeTransaction(t *testing.T) {
	// Trois choses rattachent un CANCEL a l'INVITE qu'il annule. Une seule qui
	// differe, et le navigateur ignore l'annulation : il sonne alors jusqu'au
	// bout de son delai, et decrocher ne trouve plus personne.
	invite := inviteÀAnnuler()
	annulation := ConstruireAnnulation(invite, "127.0.0.1:36688")

	if annulation.Method != sip.CANCEL {
		t.Fatalf("methode %s", annulation.Method)
	}
	if annulation.Recipient.String() != invite.Recipient.String() {
		t.Fatalf("URI de requete %s", annulation.Recipient.String())
	}
	brancheAnnulée := annulation.Via().Params.GetOr("branch", "")
	if brancheAnnulée != invite.Via().Params.GetOr("branch", "") {
		t.Fatalf("branche %q", brancheAnnulée)
	}
	if annulation.CSeq().SeqNo != invite.CSeq().SeqNo {
		t.Fatalf("sequence %d", annulation.CSeq().SeqNo)
	}
	if annulation.CSeq().MethodName != sip.CANCEL {
		t.Fatalf("methode de sequence %s", annulation.CSeq().MethodName)
	}
	if annulation.CallID().Value() != invite.CallID().Value() {
		t.Fatal("identifiant d'appel different")
	}
	if annulation.From().Params.GetOr("tag", "") != invite.From().Params.GetOr("tag", "") {
		t.Fatal("etiquette de depart differente")
	}
}

func TestLAnnulationNePorteAucuneEtiquetteDArrivee(t *testing.T) {
	// L'INVITE n'a pas encore de reponse : y poser une etiquette d'arrivee
	// designerait un dialogue qui n'existe pas.
	annulation := ConstruireAnnulation(inviteÀAnnuler(), "127.0.0.1:36688")
	if annulation.To().Params.Has("tag") {
		t.Fatal("le CANCEL porte une etiquette d'arrivee")
	}
}

func TestLAnnulationViseLaConnexionDejaOuverte(t *testing.T) {
	// Le contact d'un softphone de navigateur est en « .invalid » : une
	// destination deduite de lui partirait en resolution DNS vouee a l'echec.
	annulation := ConstruireAnnulation(inviteÀAnnuler(), "127.0.0.1:36688")
	if annulation.Destination() != "127.0.0.1:36688" {
		t.Fatalf("destination %q", annulation.Destination())
	}
}
