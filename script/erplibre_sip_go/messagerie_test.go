package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Les reponses sont celles que rend un EC25 : l'enregistrement 1 d'EF_MWIS,
// cinq octets, drapeau leve puis baisse, et le statut d'un fichier absent.
func TestLeDrapeauSeLitDansLesDeuxSens(t *testing.T) {
	for _, cas := range []struct {
		réponse string
		attente bool
	}{
		{"AT+CRSM=178,28618,1,4,5\r\n+CRSM: 144,0,\"0100000000\"\r\n\r\nOK", true},
		{"+CRSM: 144,0,\"0000000000\"\r\nOK", false},
		// Fax levé, messagerie vocale non : seul le premier bit compte.
		{"+CRSM: 144,0,\"0200000000\"\r\nOK", false},
		// Un compte fourni par le réseau ne change rien au drapeau.
		{"+CRSM: 144,0,\"0103000000\"\r\nOK", true},
	} {
		attente, err := DécoderMWIS(cas.réponse)
		if err != nil {
			t.Fatalf("%q : %v", cas.réponse, err)
		}
		if attente != cas.attente {
			t.Fatalf("%q lu %v au lieu de %v", cas.réponse, attente, cas.attente)
		}
	}
}

// Une SIM sans le fichier ne peut rien annoncer. Le lire « pas de message »
// laisserait croire a une boite vide, alors qu'on ne sait rien.
func TestUnFichierAbsentEstUneErreurEtNonUneBoiteVide(t *testing.T) {
	for _, réponse := range []string{
		"+CRSM: 106,130,\"\"\r\nOK",
		"ERROR",
		"+CRSM: 144,0,\"\"\r\nOK",
	} {
		if _, err := DécoderMWIS(réponse); err == nil {
			t.Fatalf("%q accepté comme une boîte vide", réponse)
		}
	}
}

func serveurPasserelle(t *testing.T, code int, reçus *[]map[string]any) *LienOdoo {
	t.Helper()
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			var charge map[string]any
			_ = json.NewDecoder(r.Body).Decode(&charge)
			charge["route"] = r.URL.Path
			*reçus = append(*reçus, charge)
			w.WriteHeader(code)
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": code == http.StatusOK})
		}))
	t.Cleanup(serveur.Close)
	return &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client(),
		Appareil: "modem-essai"}
}

// Au demarrage Odoo ignore tout de l'etat courant : la premiere lecture part,
// meme si le drapeau est baisse. Ensuite, seuls les changements partent.
func TestSeulsLesChangementsSontAnnonces(t *testing.T) {
	var reçus []map[string]any
	veille := &VeilleMessagerie{Lien: serveurPasserelle(t, http.StatusOK, &reçus)}
	maintenant := time.Now()

	veille.Observer(false, nil, maintenant)
	veille.Observer(false, nil, maintenant)
	veille.Observer(false, nil, maintenant)
	veille.Observer(true, nil, maintenant)
	veille.Observer(true, nil, maintenant)

	if len(reçus) != 2 {
		t.Fatalf("%d annonces au lieu de 2 (départ, puis levée)", len(reçus))
	}
	if reçus[0]["attente"] != false || reçus[1]["attente"] != true {
		t.Fatalf("annonces dans le désordre : %v", reçus)
	}
	if reçus[1]["route"] != "/erplibre_sms/voicemail" {
		t.Fatalf("route %v", reçus[1]["route"])
	}
	// La passerelle retrouve sa fiche par cet identifiant : un nom de service
	// à la place ne correspondrait à aucune fiche.
	if reçus[1]["device"] != "modem-essai" {
		t.Fatalf("appareil %v au lieu de celui de la fiche", reçus[1]["device"])
	}
}

// Un etat vu mais refuse par Odoo doit repartir. Ne retenir que le vu
// laisserait la fiche fausse jusqu'au prochain changement — des jours.
func TestUnRefusDOdooEstRetenteAuTourSuivant(t *testing.T) {
	var reçus []map[string]any
	lien := serveurPasserelle(t, http.StatusServiceUnavailable, &reçus)
	veille := &VeilleMessagerie{Lien: lien}

	veille.Observer(true, nil, time.Now())
	veille.Observer(true, nil, time.Now())
	if len(reçus) != 2 {
		t.Fatalf("%d envois : l'état refusé n'a pas été renvoyé", len(reçus))
	}
}

// Sans fiche designee, rien ne part et le service continue : une
// installation sans Odoo garde l'etat dans son journal.
func TestSansFicheRienNePart(t *testing.T) {
	var reçus []map[string]any
	lien := serveurPasserelle(t, http.StatusOK, &reçus)
	lien.Appareil = ""
	veille := &VeilleMessagerie{Lien: lien}
	if !veille.Observer(true, nil, time.Now()) {
		t.Fatal("changement non signalé au journal")
	}
	if len(reçus) != 0 {
		t.Fatalf("%d envois sans fiche désignée", len(reçus))
	}
	veille = &VeilleMessagerie{}
	veille.Observer(true, nil, time.Now())
}

// Une lecture ratee ne change pas l'etat connu : ce n'est ni un message ni
// une boite videe.
func TestUneLectureRateeNeChangeRien(t *testing.T) {
	var reçus []map[string]any
	veille := &VeilleMessagerie{Lien: serveurPasserelle(t, http.StatusOK, &reçus)}
	veille.Observer(true, nil, time.Now())
	if veille.Observer(false, errors.New("port muet"), time.Now()) {
		t.Fatal("une lecture ratée compte comme un changement")
	}
	if len(reçus) != 1 {
		t.Fatalf("%d annonces : la lecture ratée a été transmise", len(reçus))
	}
}

// La TUI lit ce fichier pendant que le service tient le port : chaque lecture
// reussie le reecrit, pour que la date dise que la surveillance continue.
func TestLEtatLocalSuitChaqueLecture(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "etat", "messagerie.json")
	veille := &VeilleMessagerie{Fichier: chemin}

	premier := time.Date(2026, 9, 17, 10, 0, 0, 0, time.UTC)
	veille.Observer(true, nil, premier)
	second := premier.Add(time.Minute)
	veille.Observer(true, nil, second)

	var état ÉtatMessagerie
	brut, err := os.ReadFile(chemin)
	if err != nil {
		t.Fatalf("état local absent : %v", err)
	}
	if err := json.Unmarshal(brut, &état); err != nil {
		t.Fatalf("état local illisible : %v", err)
	}
	if !état.Attente || état.LuLe != second.Format(time.RFC3339) {
		t.Fatalf("état %+v : la seconde lecture n'a pas rafraîchi la date", état)
	}
	if _, err := os.Stat(chemin + ".partiel"); !os.IsNotExist(err) {
		t.Fatal("fichier temporaire laissé derrière")
	}
}

// Une lecture ratee ne touche pas au fichier : la TUI verra alors une date
// qui vieillit, ce qui est vrai.
func TestUneLectureRateeNEcritPasDEtat(t *testing.T) {
	chemin := filepath.Join(t.TempDir(), "messagerie.json")
	veille := &VeilleMessagerie{Fichier: chemin}
	veille.Observer(false, errors.New("port muet"), time.Now())
	if _, err := os.Stat(chemin); !os.IsNotExist(err) {
		t.Fatal("état écrit après une lecture ratée")
	}
}

// Le chemin est fixe pour que la TUI le retrouve sans configuration.
func TestLeCheminSuitLeRepertoireDEtat(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", "/tmp/etat-essai")
	if got := CheminÉtatMessagerie(); got != "/tmp/etat-essai/erplibre/messagerie.json" {
		t.Fatalf("chemin %q", got)
	}
}

// Le numero de la messagerie est celui que l'operateur a inscrit sur la SIM :
// c'est le seul qui mene a coup sur a SA messagerie.
func TestLeNumeroDeMessagerieSeLitSurLaSIM(t *testing.T) {
	// Les reponses sont de la forme que rend un EC25.
	for _, cas := range []struct {
		réponse string
		numéro  string
		erreur  bool
	}{
		{"AT+CSVM?\r\n+CSVM: 1,\"+15145550199\",145\r\n\r\nOK", "+15145550199", false},
		{"+CSVM: 0,\"\",129\r\nOK", "", true},
		{"ERROR", "", true},
	} {
		g := motifCSVM.FindStringSubmatch(cas.réponse)
		if cas.erreur {
			if g != nil && g[1] != "0" && g[2] != "" {
				t.Fatalf("%q accepté", cas.réponse)
			}
			continue
		}
		if g == nil || g[2] != cas.numéro {
			t.Fatalf("%q lu %v", cas.réponse, g)
		}
	}
}
