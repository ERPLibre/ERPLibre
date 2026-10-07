package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"strings"
	"testing"
	"time"
)

// flux fabrique des blocs de 20 ms : parole (forte amplitude) ou silence.
func flux(morceaux ...struct {
	parole bool
	durée  time.Duration
}) *bytes.Reader {
	var b bytes.Buffer
	for _, m := range morceaux {
		blocs := int(m.durée / DuréeBloc)
		for i := 0; i < blocs; i++ {
			bloc := make([]byte, OctetsPCM)
			if m.parole {
				for j := 0; j+1 < len(bloc); j += 2 {
					binary.LittleEndian.PutUint16(bloc[j:], uint16(8000))
				}
			}
			b.Write(bloc)
		}
	}
	return bytes.NewReader(b.Bytes())
}

type morceau = struct {
	parole bool
	durée  time.Duration
}

func parle(d time.Duration) morceau { return morceau{true, d} }
func tait(d time.Duration) morceau  { return morceau{false, d} }

// Le deroule type d'une messagerie : accueil, silence, code, annonce,
// silence, touche 1, message.
func TestUneRecetteSEnchaineSurLesSilences(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{AttendreSilence: &AttenteSilence{SilenceMs: 1000, MaxS: 20, ExigerParole: true}},
		{Touches: PlaceholderCode + "#"},
		{AttendreSilence: &AttenteSilence{SilenceMs: 1000, MaxS: 20, ExigerParole: true}},
		{Touches: "1"},
		{Enregistrer: &Écoute{MaxS: 60, SilenceFinS: 3}},
	}}
	source := flux(tait(2*time.Second), parle(4*time.Second), tait(1500*time.Millisecond),
		parle(3*time.Second), tait(1500*time.Millisecond),
		parle(5*time.Second), tait(4*time.Second))
	var envoyées []string
	bilan := JouerRecette(context.Background(), r, source, nil,
		Ligne{Touches: func(s string) error { envoyées = append(envoyées, s); return nil }},
		"8642")
	if !bilan.Complète {
		t.Fatalf("recette incomplète : %s %+v", bilan.Erreur, bilan.Événements)
	}
	if strings.Join(envoyées, ",") != "8642#,1" {
		t.Fatalf("touches %v", envoyées)
	}
	// Le code partait APRÈS l'accueil : 2 s de silence initial + 4 s de
	// parole + 1 s de silence exigé.
	for _, é := range bilan.Événements {
		if strings.Contains(é.Quoi, "touches") && é.Ms < 7000 {
			t.Fatalf("code envoyé à %d ms, pendant l'accueil", é.Ms)
		}
	}
}

// Le silence qui precede l'accueil ne doit pas declencher le code : il
// partirait avant que la messagerie ne le demande.
func TestLeSilenceAvantLaParoleNeCompteQuSiOnLeDemande(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{AttendreSilence: &AttenteSilence{SilenceMs: 1000, MaxS: 20, ExigerParole: true}},
		{Touches: "1"},
	}}
	bilan := JouerRecette(context.Background(), r,
		flux(tait(3*time.Second), parle(2*time.Second), tait(2*time.Second)),
		nil, Ligne{Touches: func(string) error { return nil }}, "")
	for _, é := range bilan.Événements {
		if strings.Contains(é.Quoi, "touches") && é.Ms < 6000 {
			t.Fatalf("touche partie à %d ms, avant la fin de la parole", é.Ms)
		}
	}
}

// Un fond sonore permanent ne doit pas retenir la ligne : le maximum passe.
func TestUnFondSonoreNeRetientPasLaLigne(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{AttendreSilence: &AttenteSilence{SilenceMs: 1000, MaxS: 2, ExigerParole: true}},
		{Touches: "1"},
	}}
	var envoyée bool
	bilan := JouerRecette(context.Background(), r, flux(parle(10*time.Second)), nil,
		Ligne{Touches: func(string) error { envoyée = true; return nil }}, "")
	if !envoyée || !bilan.Complète {
		t.Fatalf("recette bloquée par un bruit continu : %+v", bilan)
	}
}

// Le code ne doit jamais apparaitre dans le bilan, qui est ecrit sur disque.
func TestLeCodeNApparaitPasDansLeBilan(t *testing.T) {
	r := Recette{Étapes: []Étape{{Touches: PlaceholderCode + "#"}}}
	bilan := JouerRecette(context.Background(), r, flux(), nil,
		Ligne{Touches: func(string) error { return nil }}, "97531")
	for _, é := range bilan.Événements {
		if strings.Contains(é.Quoi, "97531") {
			t.Fatalf("code dans le bilan : %q", é.Quoi)
		}
	}
}

func TestUneRecetteQuiDemandeLeCodeRefuseDePartirSansLui(t *testing.T) {
	r := Recette{Étapes: []Étape{{Touches: PlaceholderCode}}}
	bilan := JouerRecette(context.Background(), r, flux(), nil, Ligne{}, "")
	if bilan.Erreur == "" {
		t.Fatal("recette jouée sans code")
	}
}

// En ligne, une erreur se paie : ce qui se juge sur le papier se juge avant.
func TestUneRecetteMalFormeeEstRefuseeAvantLAppel(t *testing.T) {
	for _, r := range []Recette{
		{},
		{Étapes: []Étape{{}}},
		{Étapes: []Étape{{Touches: "1x"}}},
		{Étapes: []Étape{{Enregistrer: &Écoute{}}}},
		{Étapes: []Étape{{Touches: "1", PauseMs: 10}}},
	} {
		if r.Vérifier() == nil {
			t.Fatalf("recette acceptée : %+v", r)
		}
	}
}

// Une ligne qui retombe arrete la recette au lieu d'ecouter du vide.
func TestUneLigneRetombeeArreteLaRecette(t *testing.T) {
	r := Recette{Étapes: []Étape{{Enregistrer: &Écoute{MaxS: 60}}}}
	bilan := JouerRecette(context.Background(), r, flux(parle(5*time.Second)), nil,
		Ligne{Tient: func() bool { return false }}, "")
	if !strings.Contains(bilan.Erreur, "retombée") {
		t.Fatalf("erreur %q", bilan.Erreur)
	}
}

// La courbe permet de regler une recette : une entree par 100 ms.
func TestLaCourbeEtLesSegmentsDeParole(t *testing.T) {
	r := Recette{Étapes: []Étape{{Enregistrer: &Écoute{MaxS: 5}}}}
	bilan := JouerRecette(context.Background(), r,
		flux(tait(time.Second), parle(time.Second), tait(200*time.Millisecond),
			parle(time.Second), tait(2*time.Second)),
		nil, Ligne{}, "")
	if len(bilan.Courbe) != 50 {
		t.Fatalf("%d points de courbe pour 5 s", len(bilan.Courbe))
	}
	segments := SegmentsDeParole(bilan.Courbe, 500*time.Millisecond)
	if len(segments) != 1 || segments[0][0] != 1000 || segments[0][1] != 3200 {
		t.Fatalf("segments %v : la respiration de 200 ms a coupé la phrase", segments)
	}
}

func TestLeCodeSeLitSurLEntreeStandard(t *testing.T) {
	if got := lireCode(strings.NewReader("123456\n")); got != "123456" {
		t.Fatalf("%q", got)
	}
}

// Le decroche produit un claquement de 100 ms a pleine echelle. Compte comme
// de la parole, il faisait taper le code avant que la messagerie ne le
// demande.
func TestUnClaquementAuDecrocheNEstPasDeLaParole(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{AttendreSilence: &AttenteSilence{SilenceMs: 1000, MaxS: 20, ExigerParole: true}},
		{Touches: "1"},
	}}
	source := flux(parle(100*time.Millisecond), tait(time.Second),
		parle(1400*time.Millisecond), tait(2*time.Second))
	bilan := JouerRecette(context.Background(), r, source, nil,
		Ligne{Touches: func(string) error { return nil }}, "")
	for _, é := range bilan.Événements {
		if strings.Contains(é.Quoi, "touches") && é.Ms < 2500 {
			t.Fatalf("touche partie à %d ms, sur le claquement du décroché", é.Ms)
		}
	}
}

// La garde se place avant un effacement : sans assez de parole entendue
// depuis la derniere touche, la recette s'arrete et la touche suivante ne
// part JAMAIS.
func TestLaGardeEmpecheLEffacementSiRienNAEteEntendu(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{Touches: "1"},
		{Enregistrer: &Écoute{MaxS: 5}},
		{VérifierParole: &VérifParole{MinS: 15}},
		{Touches: "7"},
	}}
	var envoyées []string
	bilan := JouerRecette(context.Background(), r, flux(parle(3*time.Second), tait(2*time.Second)),
		nil, Ligne{Touches: func(s string) error { envoyées = append(envoyées, s); return nil }}, "")
	if bilan.Complète || strings.Join(envoyées, ",") != "1" {
		t.Fatalf("7 envoyé malgré la garde : %v / %+v", envoyées, bilan)
	}
	if !strings.Contains(bilan.Erreur, "garde") {
		t.Fatalf("erreur %q", bilan.Erreur)
	}
}

func TestLaGardeLaissePasserQuandLeMessageAEteEntendu(t *testing.T) {
	r := Recette{Étapes: []Étape{
		{Touches: "1"},
		{Enregistrer: &Écoute{MaxS: 30}},
		{VérifierParole: &VérifParole{MinS: 15}},
		{Touches: "7"},
	}}
	var envoyées []string
	bilan := JouerRecette(context.Background(), r, flux(parle(20*time.Second), tait(10*time.Second)),
		nil, Ligne{Touches: func(s string) error { envoyées = append(envoyées, s); return nil }}, "")
	if !bilan.Complète || strings.Join(envoyées, ",") != "1,7" {
		t.Fatalf("garde bloquante à tort : %v / %s", envoyées, bilan.Erreur)
	}
}
