package main

import "testing"

// Le porteur de données LTE que ModemManager maintient en permanence se
// présente dans +CLCC comme un appel d'état 0, donc « actif ». Le prendre
// pour un appel vocal fait conclure au décroché à l'instant où l'on compose,
// alors que le téléphone visé n'a même pas sonné.
func TestPorteurDeDonnéesNEstPasUnAppelVocal(t *testing.T) {
	appels := analyserCLCC("+CLCC: 1,1,0,1,0,\"\",128\r\n\r\nOK")
	if len(appels) != 1 {
		t.Fatalf("une entrée attendue, %d obtenues", len(appels))
	}
	a := appels[0]
	if a.État != ÉtatActif {
		t.Fatalf("état 0 attendu, %d obtenu", a.État)
	}
	if a.Voix() {
		t.Fatal("mode 1 = données : ne doit PAS compter comme appel vocal")
	}
}

func TestAppelVocalReconnu(t *testing.T) {
	cas := []struct {
		nom   string
		ligne string
		état  int
	}{
		{"sonnerie", `+CLCC: 1,0,3,0,0,"+15551234567",145`, 3},
		{"décroché", `+CLCC: 1,0,0,0,0,"+15551234567",145`, ÉtatActif},
	}
	for _, c := range cas {
		t.Run(c.nom, func(t *testing.T) {
			appels := analyserCLCC(c.ligne + "\r\n\r\nOK")
			if len(appels) != 1 {
				t.Fatalf("une entrée attendue, %d obtenues", len(appels))
			}
			a := appels[0]
			if !a.Voix() {
				t.Fatal("mode 0 = voix : doit compter comme appel vocal")
			}
			if !a.Sortant {
				t.Fatal("dir 0 = sortant")
			}
			if a.État != c.état {
				t.Fatalf("état %d attendu, %d obtenu", c.état, a.État)
			}
		})
	}
}

// Les deux coexistent pendant un appel : le porteur ne doit pas masquer la
// fin de l'appel vocal, ni la sonnerie passer pour un décroché.
func TestVoixEtDonnéesMêlées(t *testing.T) {
	appels := analyserCLCC(
		"+CLCC: 1,1,0,1,0,\"\",128\r\n" +
			"+CLCC: 2,0,3,0,0,\"+15551234567\",145\r\n\r\nOK")
	var voix int
	for _, a := range appels {
		if a.Voix() {
			voix++
			if a.État == ÉtatActif {
				t.Fatal("la sonnerie ne doit pas compter comme décrochée")
			}
		}
	}
	if voix != 1 {
		t.Fatalf("un seul appel vocal attendu, %d obtenus", voix)
	}
}

// Un caractere inattendu dans AT+VTS rend ERROR au milieu de la sequence :
// le filtre le refuse avant, en le nommant.
func TestSeulesLesTouchesDUnClavierPassent(t *testing.T) {
	if got, err := TouchesValides(" 1234*#a "); err != nil || got != "1234*#A" {
		t.Fatalf("%q, %v", got, err)
	}
	for _, mauvais := range []string{"", "12x", "1 2", "+1"} {
		if _, err := TouchesValides(mauvais); err == nil {
			t.Fatalf("%q accepté", mauvais)
		}
	}
}
