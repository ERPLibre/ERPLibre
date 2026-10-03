// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"path/filepath"
	"testing"
)

func réglagesRelève(auto, efface bool, demande string) RéglagesRépondeur {
	return RéglagesRépondeur{
		RelèveAuto: auto, RelèveEfface: efface, RelèveDemandée: demande,
	}
}

func TestLeDrapeauLeveDeclencheUnSeulRelevement(t *testing.T) {
	r := &Relève{}
	rég := réglagesRelève(true, true, "")

	if d := r.Décider(rég, true, true, true); !d.Relever || !d.Efface {
		t.Fatalf("premiere montee : %+v", d)
	}
	// Sans effacement, le drapeau reste levé : rappeler à chaque minute
	// ferait une boucle d'appels facturés.
	if d := r.Décider(rég, true, true, true); d.Relever {
		t.Fatal("deuxieme tour sur le meme drapeau : la ligne boucle")
	}
	// Le drapeau retombe, puis remonte : c'est un nouveau message.
	r.Décider(rég, false, true, true)
	if d := r.Décider(rég, true, true, true); !d.Relever {
		t.Fatal("une nouvelle montee doit relever")
	}
}

func TestSansDrapeauOnNAppellePas(t *testing.T) {
	r := &Relève{}
	if d := r.Décider(réglagesRelève(true, true, ""), false, true, true); d.Relever {
		t.Fatal("appel sans rien a prendre : la ligne est occupee pour rien")
	}
}

func TestUnDrapeauIllisibleNeVautPasUnDrapeauLeve(t *testing.T) {
	r := &Relève{}
	if d := r.Décider(réglagesRelève(true, true, ""), true, false, true); d.Relever {
		t.Fatal("lecture en echec : on ne sait pas s'il y a un message")
	}
}

func TestLeReglageEteintEmpecheLAutomatique(t *testing.T) {
	r := &Relève{}
	if d := r.Décider(réglagesRelève(false, true, ""), true, true, true); d.Relever {
		t.Fatal("releve automatique eteinte")
	}
}

func TestLeBoutonReleveMemeSansDrapeau(t *testing.T) {
	r := &Relève{}
	rég := réglagesRelève(false, true, "2026-10-03T00:30:00")

	if d := r.Décider(rég, false, true, true); !d.Relever {
		t.Fatal("une demande explicite doit partir, drapeau ou non")
	}
	// La MÊME date revient à chaque interrogation : elle ne vaut qu'une fois.
	if d := r.Décider(rég, false, true, true); d.Relever {
		t.Fatal("la meme demande a releve deux fois")
	}
	rég.RelèveDemandée = "2026-10-03T00:35:00"
	if d := r.Décider(rég, false, true, true); !d.Relever {
		t.Fatal("une demande plus recente doit partir")
	}
}

func TestSansCodeOnDitPourquoiAuLieuDAppeler(t *testing.T) {
	r := &Relève{}
	d := r.Décider(réglagesRelève(true, true, ""), true, true, false)

	if d.Relever {
		t.Fatal("appeler sans code compose une messagerie qu'on ne peut pas ouvrir")
	}
	if d.Motif == "" {
		t.Fatal("un refus muet se cherche longtemps")
	}
}

func TestLaRecetteSuitLeReglageDEffacement(t *testing.T) {
	r := &Relève{}
	if d := r.Décider(réglagesRelève(true, false, ""), true, true, true); d.Efface {
		t.Fatal("effacement eteint et recette qui efface")
	}
}

func TestLesRelevesSeDeposentACoteDesMessages(t *testing.T) {
	dossier := DossierDesRelèves(filepath.Join("private", "repondeur", "messages"))

	if dossier != filepath.Join("private", "repondeur", "operateur") {
		t.Fatalf("depot en %q : l'agent regarde ailleurs", dossier)
	}
	if DossierDesRelèves("") != "" {
		t.Fatal("sans dossier de messages, il n'y a pas d'endroit ou deposer")
	}
}
