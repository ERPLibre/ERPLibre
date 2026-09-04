package main

import (
	"encoding/binary"
	"math"
	"testing"

	"github.com/pion/rtp"
)

// Les deux formats disent la MEME duree : 20 ms a 8 kHz. Un octet contre
// deux, meme cadence — c'est ce qui evite tout reechantillonnage.
func TestLesDeuxFormatsDisentLaMemeDuree(t *testing.T) {
	pcm := make([]byte, OctetsPCM)
	if len(VersNavigateur(pcm)) != OctetsPCMU {
		t.Fatalf("%d octets en PCMU au lieu de %d",
			len(VersNavigateur(pcm)), OctetsPCMU)
	}
	mulaw := make([]byte, OctetsPCMU)
	if len(VersModem(mulaw)) != OctetsPCM {
		t.Fatalf("%d octets en PCM au lieu de %d",
			len(VersModem(mulaw)), OctetsPCM)
	}
}

// L'aller-retour ne rend pas l'original : µ-law est une compression avec
// pertes. Ce qui compte est que la FORME survive — sinon la voix devient un
// grésillement, et aucun réglage ne la rattrape.
func TestLAllerRetourGardeLaForme(t *testing.T) {
	const échantillons = 160
	original := make([]byte, échantillons*2)
	for i := 0; i < échantillons; i++ {
		// Une sinusoïde à 1 kHz, dans la bande de la voix.
		valeur := int16(8000 * math.Sin(2*math.Pi*1000*float64(i)/8000))
		binary.LittleEndian.PutUint16(original[i*2:], uint16(valeur))
	}

	retour := VersModem(VersNavigateur(original))
	if len(retour) != len(original) {
		t.Fatalf("%d octets au retour au lieu de %d", len(retour), len(original))
	}

	var écartMax float64
	for i := 0; i < échantillons; i++ {
		avant := float64(int16(binary.LittleEndian.Uint16(original[i*2:])))
		après := float64(int16(binary.LittleEndian.Uint16(retour[i*2:])))
		if écart := math.Abs(avant - après); écart > écartMax {
			écartMax = écart
		}
	}
	// µ-law garde environ 8 bits utiles sur 14 : l'écart reste sous quelques
	// pour cent de la pleine échelle. Au-delà, c'est que les octets sont
	// désalignés, pas que la compression est imprécise.
	if écartMax > 0.02*32768 {
		t.Fatalf("écart maximal %.0f : les échantillons sont désalignés", écartMax)
	}
}

func TestLeSilenceResteSilencieux(t *testing.T) {
	if niveauCrête(SilencePCM()) != 0 {
		t.Fatal("le silence n'est pas à zéro")
	}
	if len(SilencePCM()) != OctetsPCM {
		t.Fatal("un bloc de silence ne fait pas la durée attendue")
	}
}

func TestLaCreteDitCeQuiEntre(t *testing.T) {
	bloc := make([]byte, OctetsPCM)
	var grave int16 = -9000
	var aigu int16 = 4000
	binary.LittleEndian.PutUint16(bloc[10:], uint16(grave))
	binary.LittleEndian.PutUint16(bloc[20:], uint16(aigu))
	if crête := niveauCrête(bloc); crête != 9000 {
		t.Fatalf("crête %d au lieu de 9000 : la valeur absolue est manquée", crête)
	}
}

// La numerotation appartient a l'emetteur : recopier celle de l'entrant fait
// voir des sauts au recepteur, qui jette ce qu'il croit desordonne.
func TestLEmetteurNumeroteSaPropreSuite(t *testing.T) {
	émetteur := NouvelÉmetteurRTP(0x1234)
	charge := make([]byte, OctetsPCMU)

	var précédent rtp.Packet
	for i := 0; i < 3; i++ {
		brut, err := émetteur.Paquet(charge)
		if err != nil {
			t.Fatalf("emballage : %v", err)
		}
		var paquet rtp.Packet
		if err := paquet.Unmarshal(brut); err != nil {
			t.Fatalf("paquet illisible : %v", err)
		}
		if paquet.SSRC != 0x1234 || paquet.PayloadType != ChargePCMU {
			t.Fatalf("entête inattendue : %+v", paquet.Header)
		}
		if i > 0 {
			if paquet.SequenceNumber != précédent.SequenceNumber+1 {
				t.Fatalf("séquence %d après %d",
					paquet.SequenceNumber, précédent.SequenceNumber)
			}
			// Un échantillon par octet en PCMU : l'horodatage avance d'autant.
			if paquet.Timestamp != précédent.Timestamp+OctetsPCMU {
				t.Fatalf("horodatage %d après %d, écart attendu %d",
					paquet.Timestamp, précédent.Timestamp, OctetsPCMU)
			}
		}
		précédent = paquet
	}
}
