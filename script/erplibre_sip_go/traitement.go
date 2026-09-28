// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"encoding/binary"
	"math"
)

// Réglages du traitement, tous exprimés en unités physiques : un chiffre
// magique en échantillons ne se relit pas, et se casse au premier
// changement de débit.
const (
	// CoupureGrave écarte ce qui n'est pas de la voix. Un micro de portable
	// capte le ventilateur, la table et le bruit de manipulation, tous sous
	// 200 Hz — bande que le réseau téléphonique ne transporte pas de toute
	// façon, mais qui consomme la dynamique avant lui.
	CoupureGrave = 200.0

	// MargePorte est ce qu'un signal doit dépasser le bruit de fond pour
	// être tenu pour de la voix, en décibels. Douze : la parole ordinaire
	// domine largement le souffle, et descendre plus bas fait ouvrir la
	// porte sur le ventilateur.
	MargePorte = 12.0

	// MaintienPorte garde la porte ouverte après la fin d'un mot. Sans lui,
	// elle se referme entre les syllabes et hache la voix.
	MaintienPorte = 300 * timeMilli

	// FuitePorte est ce qui passe porte fermée. Couper à zéro produit un
	// silence si net que le correspondant croit la ligne coupée ; un fond
	// résiduel rassure.
	FuitePorte = 0.12

	// MaintienÉcho prolonge l'atténuation après que l'autre s'est tu. La
	// queue d'une phrase et sa réverbération reviennent sinon dans le micro.
	MaintienÉcho = 400 * timeMilli

	// MargeÉcho est ce que le correspondant doit dépasser SON PROPRE bruit
	// de fond pour qu'on tienne qu'il parle, en décibels.
	//
	// Relatif et non absolu, et c'est tout l'enjeu : un seuil fixe qu'une
	// ligne bruyante franchit en permanence referme le micro pendant toute
	// la conversation, et le correspondant nous entend étouffés sans que
	// rien ne l'explique.
	MargeÉcho = 10.0

	// TempsMontée et TempsDescente lissent les changements de gain. Un saut
	// brutal s'entend comme un claquement, plus gênant que ce qu'il corrige.
	TempsMontée   = 60 * timeMilli
	TempsDescente = 15 * timeMilli

	// SuiviPlancher règle la montée de l'estimation du bruit de fond, une
	// fois PAR BLOC de vingt millisecondes. À 0,005, il faut quelques
	// secondes pour apprendre un ventilateur qui démarre — lent à dessein :
	// plus vif, l'estimation suivrait la voix et la porte se refermerait sur
	// qui parle longtemps. La descente, elle, est immédiate : les silences
	// entre les mots donnent la mesure du vrai plancher.
	SuiviPlancher = 0.005

	// timeMilli évite d'importer time pour de simples millisecondes.
	timeMilli = 1
)

// TraitementMicro nettoie la voix locale avant de l'envoyer.
//
// Trois étages, dans cet ordre, et l'ordre compte :
//
//  1. un passe-haut, parce que filtrer les graves AVANT de mesurer évite
//     que le ronflement du ventilateur ne fasse ouvrir la porte ;
//  2. une porte de bruit, qui referme le micro entre les mots plutôt que
//     d'envoyer le souffle en permanence ;
//  3. une atténuation pendant que le correspondant parle, avec maintien et
//     rampe.
//
// Ce n'est PAS une annulation d'écho : celle-ci soustrait du signal capté
// une copie filtrée de ce qui a été joué, ce qui demande d'estimer la
// réponse de la pièce. Ici on baisse le micro, ce qui coûte le duplex. Un
// casque reste supérieur puisqu'il supprime la cause.
//
// Prévu pour UN SEUL appelant : l'état des filtres n'est pas protégé, et
// deux goroutines produiraient un signal incohérent plutôt qu'un plantage.
type TraitementMicro struct {
	taux float64

	// Passe-haut à DEUX pôles, en cascade de deux sections identiques.
	//
	// Un seul pôle ne descend qu'à six décibels par octave : à 120 Hz il ne
	// retire que la moitié du ronflement, ce qui ne s'entend presque pas.
	// Deux sections doublent la pente et rendent le ventilateur inaudible
	// sans mordre sur la voix, qui commence bien au-dessus.
	aGrave  float64
	entrées [2]float64
	sorties [2]float64

	// Porte de bruit.
	plancher      float64
	maintienPorte int

	// Atténuation à l'alternat.
	plancherDistant float64
	maintienÉcho    int
	gainCourant     float64
}

// NouveauTraitement prépare les filtres pour un débit donné.
func NouveauTraitement(taux float64) *TraitementMicro {
	t := &TraitementMicro{taux: taux, gainCourant: 1, plancher: 50,
		plancherDistant: 50}
	// Constante du passe-haut : a = RC / (RC + dt), avec RC = 1/(2·pi·fc).
	rc := 1.0 / (2 * math.Pi * CoupureGrave)
	dt := 1.0 / taux
	t.aGrave = rc / (rc + dt)
	return t
}

// échantillonsPour convertit des millisecondes en nombre d'échantillons.
func (t *TraitementMicro) échantillonsPour(ms int) int {
	return int(float64(ms) * t.taux / 1000.0)
}

// Appliquer nettoie un bloc EN PLACE et rend son niveau efficace utile.
//
// niveauDistant est le niveau courant du correspondant ; au-delà du seuil,
// le micro se referme. filtrer permet de tout désactiver sans changer le
// chemin du signal, ce qui rend la comparaison honnête.
func (t *TraitementMicro) Appliquer(bloc []byte, niveauDistant int,
	filtrer, antiÉcho bool) int {
	n := len(bloc) / 2
	if n == 0 {
		return 0
	}
	échantillons := make([]float64, n)
	for i := 0; i < n; i++ {
		échantillons[i] = float64(int16(binary.LittleEndian.Uint16(bloc[i*2:])))
	}

	if filtrer {
		t.passeHaut(échantillons)
	}

	// Niveau mesuré APRÈS le filtre et AVANT les atténuations : c'est ce que
	// vaut la voix, et non ce qu'il en reste une fois la porte fermée.
	niveau := efficace(échantillons)

	cible := 1.0
	if filtrer {
		cible *= t.porte(niveau)
	}
	if antiÉcho {
		cible *= t.alternat(niveauDistant)
	}
	t.appliquerRampe(échantillons, cible)

	for i := 0; i < n; i++ {
		v := math.Round(échantillons[i])
		if v > math.MaxInt16 {
			v = math.MaxInt16
		} else if v < math.MinInt16 {
			v = math.MinInt16
		}
		binary.LittleEndian.PutUint16(bloc[i*2:], uint16(int16(v)))
	}
	return int(niveau)
}

// passeHaut retire les graves, en place.
func (t *TraitementMicro) passeHaut(v []float64) {
	for i, x := range v {
		for s := 0; s < len(t.entrées); s++ {
			y := t.aGrave * (t.sorties[s] + x - t.entrées[s])
			t.entrées[s] = x
			t.sorties[s] = y
			x = y
		}
		v[i] = x
	}
}

// porte rend le gain voulu par la porte de bruit.
//
// Le plancher ne monte que lentement et redescend d'un coup : il doit
// suivre un ventilateur qui démarre sans jamais suivre une voix qui dure.
func (t *TraitementMicro) porte(niveau float64) float64 {
	if niveau < t.plancher {
		t.plancher = niveau
	} else {
		t.plancher += (niveau - t.plancher) * SuiviPlancher
	}
	if t.plancher < 1 {
		t.plancher = 1
	}
	seuil := t.plancher * math.Pow(10, MargePorte/20)
	if niveau >= seuil {
		t.maintienPorte = t.échantillonsPour(MaintienPorte)
	}
	if t.maintienPorte > 0 {
		return 1
	}
	return FuitePorte
}

// alternat rend le gain voulu pendant que le correspondant parle.
//
// Le seuil suit le bruit de LA LIGNE, avec SeuilÉcho pour plancher absolu :
// une ligne calme ne doit pas faire refermer le micro sur un souffle, et
// une ligne bruyante ne doit pas le refermer en permanence.
func (t *TraitementMicro) alternat(niveauDistant int) float64 {
	d := float64(niveauDistant)
	if d < t.plancherDistant {
		t.plancherDistant = d
	} else {
		t.plancherDistant += (d - t.plancherDistant) * SuiviPlancher
	}
	if t.plancherDistant < 1 {
		t.plancherDistant = 1
	}
	seuil := math.Max(float64(SeuilÉcho),
		t.plancherDistant*math.Pow(10, MargeÉcho/20))
	if d >= seuil {
		t.maintienÉcho = t.échantillonsPour(MaintienÉcho)
	}
	if t.maintienÉcho > 0 {
		return float64(AtténuationÉcho) / 100.0
	}
	return 1
}

// appliquerRampe glisse vers le gain visé au lieu d'y sauter.
func (t *TraitementMicro) appliquerRampe(v []float64, cible float64) {
	monte := t.pasRampe(TempsMontée)
	descend := t.pasRampe(TempsDescente)
	for i := range v {
		if t.gainCourant < cible {
			t.gainCourant = math.Min(cible, t.gainCourant+monte)
		} else if t.gainCourant > cible {
			t.gainCourant = math.Max(cible, t.gainCourant-descend)
		}
		v[i] *= t.gainCourant
		if t.maintienPorte > 0 {
			t.maintienPorte--
		}
		if t.maintienÉcho > 0 {
			t.maintienÉcho--
		}
	}
}

// pasRampe rend l'incrément de gain par échantillon pour une durée donnée.
func (t *TraitementMicro) pasRampe(ms int) float64 {
	n := t.échantillonsPour(ms)
	if n < 1 {
		return 1
	}
	return 1.0 / float64(n)
}

// efficace rend la valeur efficace d'un bloc d'échantillons.
func efficace(v []float64) float64 {
	if len(v) == 0 {
		return 0
	}
	var somme float64
	for _, x := range v {
		somme += x * x
	}
	return math.Sqrt(somme / float64(len(v)))
}
