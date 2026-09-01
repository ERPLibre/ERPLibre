package main

import (
	"encoding/binary"
	"math"
	"testing"
)

// générateur produit un sinus CONTINU d'un bloc à l'autre.
//
// La continuité de phase n'est pas un raffinement : remettre la phase à
// zéro à chaque bloc crée une marche toutes les vingt millisecondes, et une
// marche est large bande. Elle traverse le passe-haut et se mesure comme si
// le grave passait — on éprouve alors son propre générateur.
type générateur struct {
	hz, amplitude float64
	n             int
}

func (g *générateur) bloc(taille int) []byte {
	b := make([]byte, taille*2)
	for i := 0; i < taille; i++ {
		v := g.amplitude * math.Sin(2*math.Pi*g.hz*float64(g.n)/TauxVoixHz)
		binary.LittleEndian.PutUint16(b[i*2:], uint16(int16(v)))
		g.n++
	}
	return b
}

// sinus rend un bloc unique, pour les cas où la suite n'importe pas.
func sinus(hz, amplitude float64, n int) []byte {
	g := &générateur{hz: hz, amplitude: amplitude}
	return g.bloc(n)
}

func picDe(bloc []byte) float64 {
	pic := 0.0
	for i := 0; i+1 < len(bloc); i += 2 {
		v := math.Abs(float64(int16(binary.LittleEndian.Uint16(bloc[i:]))))
		if v > pic {
			pic = v
		}
	}
	return pic
}

// Le passe-haut doit écarter ce qui n'est pas de la voix — ventilateur,
// table, manipulation — sans toucher à la bande utile.
func TestPasseHautCoupeLesGravesEtGardeLaVoix(t *testing.T) {
	const blocs = 40 // 800 ms : assez pour que les filtres s'établissent
	cas := []struct {
		nom   string
		hz    float64
		garde bool
	}{
		{"ronflement 50 Hz", 50, false},
		{"grave 120 Hz", 120, false},
		{"voix 1000 Hz", 1000, true},
		{"voix 2500 Hz", 2500, true},
	}
	for _, c := range cas {
		t.Run(c.nom, func(t *testing.T) {
			tr := NouveauTraitement(TauxVoixHz)
			g := &générateur{hz: c.hz, amplitude: 8000}
			var dernier []byte
			for i := 0; i < blocs; i++ {
				dernier = g.bloc(TailleBloc / 2)
				// Porte et anti-écho désactivés : on éprouve le filtre seul.
				tr.Appliquer(dernier, 0, true, false)
			}
			pic := picDe(dernier)
			if c.garde && pic < 4000 {
				t.Fatalf("voix trop atténuée : pic %.0f pour 8000", pic)
			}
			if !c.garde && pic > 4000 {
				t.Fatalf("grave insuffisamment coupé : pic %.0f", pic)
			}
		})
	}
}

// Un souffle constant doit finir par être refermé : sinon le correspondant
// entend le ventilateur pendant toute la conversation.
func TestLaPorteRefermeUnSoufflePersistant(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	g := &générateur{hz: 1000, amplitude: 300}
	var pic float64
	// Dix secondes de bruit constant à 1 kHz, faible.
	for i := 0; i < 500; i++ {
		bloc := g.bloc(TailleBloc / 2)
		tr.Appliquer(bloc, 0, true, false)
		pic = picDe(bloc)
	}
	if pic > 300*FuitePorte+30 {
		t.Fatalf("souffle non refermé : pic %.0f", pic)
	}
}

// Mais la voix doit rouvrir la porte, et vite.
func TestLaPorteSOuvreSurLaVoix(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	fond := &générateur{hz: 1000, amplitude: 300}
	for i := 0; i < 500; i++ {
		tr.Appliquer(fond.bloc(TailleBloc/2), 0, true, false)
	}
	// Quelqu'un parle : vingt fois plus fort que le fond.
	voix := &générateur{hz: 1000, amplitude: 6000}
	var pic float64
	for i := 0; i < 15; i++ {
		bloc := voix.bloc(TailleBloc / 2)
		tr.Appliquer(bloc, 0, true, false)
		pic = picDe(bloc)
	}
	if pic < 3000 {
		t.Fatalf("la voix n'a pas rouvert la porte : pic %.0f", pic)
	}
}

// L'atténuation doit SURVIVRE au silence du correspondant : la queue d'une
// phrase et la réverbération de la pièce reviennent sinon dans le micro.
func TestLAntiÉchoTientApresLeSilenceDuCorrespondant(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	// Le correspondant parle : le micro se referme.
	for i := 0; i < 20; i++ {
		tr.Appliquer(sinus(1000, 6000, TailleBloc/2), SeuilÉcho*2, false, true)
	}
	pendant := picDe(dernierBloc(tr, SeuilÉcho*2))
	// Il se tait. Cent millisecondes plus tard, le micro doit rester fermé.
	var après float64
	for i := 0; i < 5; i++ {
		bloc := sinus(1000, 6000, TailleBloc/2)
		tr.Appliquer(bloc, 0, false, true)
		après = picDe(bloc)
	}
	if après > pendant*3 {
		t.Fatalf("le micro rouvre trop tôt : %.0f contre %.0f", après, pendant)
	}
	// Une seconde plus tard, il doit être revenu.
	var plusTard float64
	for i := 0; i < 50; i++ {
		bloc := sinus(1000, 6000, TailleBloc/2)
		tr.Appliquer(bloc, 0, false, true)
		plusTard = picDe(bloc)
	}
	if plusTard < 3000 {
		t.Fatalf("le micro ne rouvre jamais : pic %.0f", plusTard)
	}
}

func dernierBloc(tr *TraitementMicro, distant int) []byte {
	bloc := sinus(1000, 6000, TailleBloc/2)
	tr.Appliquer(bloc, distant, false, true)
	return bloc
}

// Le gain glisse au lieu de sauter : un saut s'entend comme un claquement,
// plus gênant que ce qu'il corrige.
func TestLeGainGlisseAuLieuDeSauter(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	// Premier bloc avec le correspondant qui parle : la descente vers
	// l'atténuation prend quelques millisecondes, donc le début du bloc
	// reste fort et la fin est basse.
	bloc := sinus(1000, 8000, TailleBloc/2)
	tr.Appliquer(bloc, SeuilÉcho*2, false, true)
	début := picDe(bloc[:40])
	fin := picDe(bloc[len(bloc)-40:])
	if début <= fin {
		t.Fatalf("aucune rampe : début %.0f, fin %.0f", début, fin)
	}
}

// Le niveau rendu doit être celui de la VOIX, mesuré avant les
// atténuations : sinon l'indicateur retombe à zéro entre les mots et fait
// croire à un micro mort.
func TestLeNiveauRenduIgnoreLesAttenuations(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	// Plusieurs blocs : la rampe met quelques millisecondes à descendre, et
	// juger sur le premier mesurerait la rampe, pas l'atténuation.
	var bloc []byte
	var niveau int
	for i := 0; i < 10; i++ {
		bloc = sinus(1000, 6000, TailleBloc/2)
		niveau = tr.Appliquer(bloc, SeuilÉcho*10, true, true)
	}
	if niveau < 2000 {
		t.Fatalf("niveau %d : il doit refléter la voix, pas ce qui en reste",
			niveau)
	}
	if picDe(bloc) > 3000 {
		t.Fatal("le bloc devait pourtant être atténué")
	}
}

// Tout désactivé, le signal doit ressortir INTACT : c'est ce qui rend la
// comparaison honnête quand on cherche si le traitement aide ou nuit.
func TestSansFiltreNiAntiÉchoLeSignalPasse(t *testing.T) {
	tr := NouveauTraitement(TauxVoixHz)
	original := sinus(1000, 6000, TailleBloc/2)
	bloc := sinus(1000, 6000, TailleBloc/2)
	tr.Appliquer(bloc, SeuilÉcho*10, false, false)
	for i := range bloc {
		if bloc[i] != original[i] {
			t.Fatalf("octet %d modifié alors que tout est désactivé", i)
		}
	}
}
