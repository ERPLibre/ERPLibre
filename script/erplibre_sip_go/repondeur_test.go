package main

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Un repondeur allume par defaut decrocherait sur une ligne dont le
// proprietaire ignore qu'il en a un. L'appelant, lui, l'entend.
func TestLeRepondeurEstEteintParDefaut(t *testing.T) {
	if RéglagesParDéfaut().Actif {
		t.Fatal("répondeur actif sans qu'on l'ait demandé")
	}
}

// Un fichier ABSENT est l'etat d'une installation sans repondeur : le service
// doit demarrer. Un fichier PRESENT mais illisible est une erreur — quelqu'un
// a voulu un repondeur, et le taire laisserait croire qu'il fonctionne.
func TestUnReglageAbsentNEmpechePasDeDemarrer(t *testing.T) {
	r, err := ChargerRéglagesRépondeur(filepath.Join(t.TempDir(), "rien.json"))
	if err != nil {
		t.Fatalf("fichier absent traité en erreur : %v", err)
	}
	if r.Actif {
		t.Fatal("répondeur actif alors qu'aucun réglage n'existe")
	}
}

func TestUnReglageIllisibleSeDit(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "casse.json")
	if err := os.WriteFile(chemin, []byte("{ceci n'est pas du JSON"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := ChargerRéglagesRépondeur(chemin); err == nil {
		t.Fatal("réglage illisible accepté en silence")
	}
}

func TestLesReglagesFontLAllerRetour(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "conf", "repondeur.json")
	posé := RéglagesRépondeur{
		Actif: true, Sonneries: 3, Annonce: "/tmp/annonce.wav",
		Dossier: "/tmp/messages", DuréeMaxSecondes: 90,
	}
	if err := posé.Enregistrer(chemin); err != nil {
		t.Fatalf("écriture : %v", err)
	}
	relu, err := ChargerRéglagesRépondeur(chemin)
	if err != nil {
		t.Fatalf("lecture : %v", err)
	}
	if relu != posé {
		t.Fatalf("relu %+v au lieu de %+v", relu, posé)
	}
}

// Un reglage aberrant vient d'une saisie, et refuser de demarrer priverait la
// ligne de tout repondeur alors que l'intention est claire.
func TestUnNombreDeSonneriesAberrantEstRamene(t *testing.T) {
	for _, cas := range []struct{ demandé, attendu int }{
		{0, SonneriesParDéfaut},
		{-3, SonneriesParDéfaut},
		{40, SonneriesMax},
	} {
		r := RéglagesRépondeur{Sonneries: cas.demandé}.Normaliser()
		if r.Sonneries != cas.attendu {
			t.Fatalf("%d sonneries ramenées à %d, attendu %d",
				cas.demandé, r.Sonneries, cas.attendu)
		}
	}
}

// C'est une course contre la boite vocale de l'operateur, qui prend l'appel
// vers trente secondes. Un repondeur qui decroche apres elle n'enregistre
// jamais rien, et la panne se lit « le repondeur ne marche pas ».
func TestLeRepondeurDecrocheAvantLOperateur(t *testing.T) {
	max := RéglagesRépondeur{Sonneries: SonneriesMax}.DélaiAvantDécroché()
	if max > 30*time.Second {
		t.Fatalf("décroché possible à %v, après la boîte vocale de l'opérateur", max)
	}
	défaut := RéglagesParDéfaut().DélaiAvantDécroché()
	if défaut >= max {
		t.Fatalf("le défaut (%v) ne laisse aucune marge sous le maximum (%v)",
			défaut, max)
	}
}

// L'en-tete est ecrit A ZERO avant la capture puis reecrit : la taille n'est
// connue qu'une fois l'appelant parti, et un en-tete pose seulement a la fin
// laisserait un fichier illisible si le service s'arretait en cours.
func TestLEnteteWAVDecritLaVoixDuModem(t *testing.T) {
	e := entêteWAV(320)
	if string(e[0:4]) != "RIFF" || string(e[8:12]) != "WAVE" {
		t.Fatalf("ce n'est pas un WAV : %q", e[:12])
	}
	if got := binary.LittleEndian.Uint32(e[24:]); got != 8000 {
		t.Fatalf("taux %d au lieu de 8000 : le message serait joué trop vite", got)
	}
	if got := binary.LittleEndian.Uint16(e[22:]); got != 1 {
		t.Fatalf("%d canaux au lieu d'un", got)
	}
	if got := binary.LittleEndian.Uint16(e[34:]); got != 16 {
		t.Fatalf("%d bits par échantillon au lieu de 16", got)
	}
	if got := binary.LittleEndian.Uint32(e[40:]); got != 320 {
		t.Fatalf("taille des données %d au lieu de 320", got)
	}
	if got := binary.LittleEndian.Uint32(e[4:]); got != 356 {
		t.Fatalf("taille RIFF %d au lieu de 356", got)
	}
}

func écrireMessage(t *testing.T, dossier, nom, début string) string {
	t.Helper()
	wav := filepath.Join(dossier, nom)
	if err := os.WriteFile(wav, entêteWAV(0), 0o600); err != nil {
		t.Fatal(err)
	}
	m := &Message{Numéro: "15555550142", Début: début, Fichier: wav}
	if err := ÉcrireCompagnon(m); err != nil {
		t.Fatal(err)
	}
	return wav
}

// Le plus recent d'abord : un repondeur se consulte pour ce qui vient
// d'arriver, pas pour ce qui date.
func TestLesMessagesSortentDuPlusRecent(t *testing.T) {
	dossier := t.TempDir()
	écrireMessage(t, dossier, "vieux.wav", "2026-09-01T08:00:00-04:00")
	écrireMessage(t, dossier, "neuf.wav", "2026-09-05T08:00:00-04:00")

	messages, err := ListerMessages(dossier)
	if err != nil {
		t.Fatal(err)
	}
	if len(messages) != 2 {
		t.Fatalf("%d messages au lieu de 2", len(messages))
	}
	if filepath.Base(messages[0].Fichier) != "neuf.wav" {
		t.Fatalf("le plus ancien est présenté en premier : %v", messages[0].Fichier)
	}
}

// Un WAV sans compagnon ne se rappelle pas : ni appelant, ni date. L'afficher
// donnerait une ligne qui n'apprend rien.
func TestUnSonSansDescriptionEstIgnore(t *testing.T) {
	dossier := t.TempDir()
	if err := os.WriteFile(filepath.Join(dossier, "orphelin.wav"),
		entêteWAV(0), 0o600); err != nil {
		t.Fatal(err)
	}
	messages, err := ListerMessages(dossier)
	if err != nil {
		t.Fatal(err)
	}
	if len(messages) != 0 {
		t.Fatalf("%d messages sans description retenus", len(messages))
	}
}

func TestUnDossierAbsentNEstPasUneErreur(t *testing.T) {
	messages, err := ListerMessages(filepath.Join(t.TempDir(), "jamais"))
	if err != nil || messages != nil {
		t.Fatalf("dossier absent : %v / %v", messages, err)
	}
}

// Le son ET sa description : un compagnon orphelin ferait reapparaitre dans
// la liste un message dont le son n'existe plus.
func TestEffacerEmporteLesDeuxFichiers(t *testing.T) {
	dossier := t.TempDir()
	wav := écrireMessage(t, dossier, "message.wav", "2026-09-05T08:00:00-04:00")
	if err := EffacerMessage(wav); err != nil {
		t.Fatalf("effacement : %v", err)
	}
	if _, err := os.Stat(CheminCompagnon(wav)); !os.IsNotExist(err) {
		t.Fatal("la description survit au son")
	}
	messages, _ := ListerMessages(dossier)
	if len(messages) != 0 {
		t.Fatalf("%d messages après effacement", len(messages))
	}
	// Effacer deux fois n'est pas une erreur : la TUI et Odoo peuvent le
	// demander tous les deux.
	if err := EffacerMessage(wav); err != nil {
		t.Fatalf("second effacement : %v", err)
	}
}

// Un dossier vide n'est pas un enregistrement : sans dossier, on refuse
// plutot que d'ecrire dans le repertoire courant du service.
func TestSansDossierLeRepondeurRefuse(t *testing.T) {
	_, err := PrendreLeMessage(t.Context(), "", RéglagesRépondeur{Actif: true}, "1")
	if err == nil {
		t.Fatal("message accepté sans dossier de destination")
	}
}

// rejouerNiveaux rejoue une suite de niveaux et rend la mesure, comme la capture le
// ferait bloc par bloc.
func rejouerNiveaux(max time.Duration, niveaux ...int) *mesureMessage {
	m := &mesureMessage{max: max}
	for _, n := range niveaux {
		if !m.ajouter(n) {
			break
		}
	}
	return m
}

func blocs(n int, niveau int) []int {
	suite := make([]int, n)
	for i := range suite {
		suite[i] = niveau
	}
	return suite
}

func TestUnClaquementDePriseDeLigneNEstPasUnMessage(t *testing.T) {
	// Un seul bloc saturé, puis le silence : c'est ce que la carte du modem
	// rend quand l'appelant ne dit rien.
	m := rejouerNiveaux(2*time.Minute, append([]int{32768}, blocs(400, 0)...)...)

	if d := m.retenue(); d != 0 {
		t.Fatalf("un claquement vaut un message de %s", d)
	}
	if m.crête != 32768 {
		t.Fatalf("crête %d, la saturation doit rester visible", m.crête)
	}
}

func TestLeSilenceDeFinNeComptePasDansLaDuree(t *testing.T) {
	// Deux secondes de parole, puis le silence qui termine le message.
	suite := append(blocs(100, 5000), blocs(400, 0)...)
	m := rejouerNiveaux(2*time.Minute, suite...)

	if d := m.retenue(); d != 2*time.Second {
		t.Fatalf("durée %s, attendu 2s", d)
	}
	if m.écoulé != 2*time.Second+SilenceFinMessage {
		t.Fatalf("capté %s, attendu la parole plus le silence de fin", m.écoulé)
	}
}

func TestLaDureeAnnonceeDecritLesOctetsGardes(t *testing.T) {
	// L'invariant qui tient le fichier et sa description ensemble : ce qu'on
	// coupe plus ce qu'on garde fait ce qu'on a écrit.
	suite := append(blocs(75, 5000), blocs(400, 0)...)
	m := rejouerNiveaux(2*time.Minute, suite...)

	écrits := int(m.écoulé/DuréeBloc) * OctetsPCM
	if gardés := octetsPour(m.retenue()); gardés+octetsPour(m.depuisSon) != écrits {
		t.Fatalf("%d octets gardés + %d coupés != %d écrits",
			gardés, octetsPour(m.depuisSon), écrits)
	}
}

func TestSansUnMotOnSArreteAvantLaDureeMaximale(t *testing.T) {
	m := rejouerNiveaux(2*time.Minute, blocs(3000, 0)...)

	if m.écoulé != DélaiPremierSon {
		t.Fatalf("capté %s, attendu %s", m.écoulé, DélaiPremierSon)
	}
	if d := m.retenue(); d != 0 {
		t.Fatalf("durée %s sans un mot", d)
	}
}

func TestUnAppelantQuiPoseSonCombineEstBorne(t *testing.T) {
	// Parole continue : seule la durée maximale arrête la capture, car la
	// ligne ouverte se facture.
	m := rejouerNiveaux(3*time.Second, blocs(1000, 5000)...)

	if m.écoulé != 3*time.Second {
		t.Fatalf("capté %s, attendu la borne de 3s", m.écoulé)
	}
	if d := m.retenue(); d != 3*time.Second {
		t.Fatalf("durée %s, attendu 3s", d)
	}
}
