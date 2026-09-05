package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// Ne pas avoir d'Odoo est une installation valide : la TUI suffit a regler le
// repondeur et a lire ses messages.
func TestSansConfigurationIlNYAPasDeLien(t *testing.T) {
	t.Setenv(VariableOdooURL, "")
	t.Setenv(VariableSecret, "")
	if OuvrirLienOdoo() != nil {
		t.Fatal("lien ouvert sans URL ni secret")
	}
	t.Setenv(VariableOdooURL, "http://127.0.0.1:8069")
	if OuvrirLienOdoo() != nil {
		t.Fatal("lien ouvert sans secret : les requêtes partiraient non signées")
	}
}

// Le secret authentifie ce qui ECRIT dans la base : une requete non signee,
// ou signee d'autre chose que le corps REELLEMENT transmis, doit etre
// rejetable par le controleur.
func TestLaSignatureCouvreLeCorpsTransmis(t *testing.T) {
	const secret = "secret-de-test"
	var vu struct {
		signature string
		corps     []byte
	}
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			vu.signature = r.Header.Get(EnTêteSignature)
			vu.corps, _ = os.ReadFile(os.DevNull)
			tampon := make([]byte, r.ContentLength)
			_, _ = r.Body.Read(tampon)
			vu.corps = tampon
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
		}))
	defer serveur.Close()

	lien := &LienOdoo{URL: serveur.URL, Secret: secret, Client: serveur.Client()}
	if _, err := lien.envoyer("/essai", map[string]any{"numero": "1"}); err != nil {
		t.Fatalf("envoi : %v", err)
	}

	somme := hmac.New(sha256.New, []byte(secret))
	somme.Write(vu.corps)
	attendue := "sha256=" + hex.EncodeToString(somme.Sum(nil))
	if vu.signature != attendue {
		t.Fatalf("signature %q ne couvre pas le corps transmis", vu.signature)
	}
}

// Horodatage et jeton voyagent dans le CORPS : c'est ce que le controleur
// verifie contre le rejeu, et un jeton reutilise serait accepte deux fois.
func TestChaqueEnvoiPorteUnJetonNeuf(t *testing.T) {
	var jetons []string
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			var charge map[string]any
			_ = json.NewDecoder(r.Body).Decode(&charge)
			jetons = append(jetons, charge["nonce"].(string))
			if charge["ts"] == nil {
				t.Error("envoi sans horodatage : le contrôleur le refusera")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
		}))
	defer serveur.Close()

	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	for i := 0; i < 3; i++ {
		if _, err := lien.envoyer("/essai", map[string]any{}); err != nil {
			t.Fatal(err)
		}
	}
	vus := map[string]bool{}
	for _, jeton := range jetons {
		if vus[jeton] {
			t.Fatalf("jeton %q rejoué : le second envoi serait refusé", jeton)
		}
		vus[jeton] = true
	}
}

// C'est precisement pendant une panne du serveur que quelqu'un laisse un
// message : la ligne ne doit pas devenir muette avec lui.
func TestUnOdooMuetLaisseLesReglagesDuDisque(t *testing.T) {
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte("{}"))
		}))
	defer serveur.Close()

	locaux := RéglagesRépondeur{Actif: true, Sonneries: 2, Annonce: "/local.wav"}
	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	if fusionnés := RéglagesDepuisOdoo(lien, locaux); fusionnés.Sonneries != 2 ||
		!fusionnés.Actif || fusionnés.Annonce != "/local.wav" {
		t.Fatalf("réglages perdus quand Odoo se tait : %+v", fusionnés)
	}
	// Aucun lien du tout : le cas d'une installation sans Odoo.
	if fusionnés := RéglagesDepuisOdoo(nil, locaux); fusionnés != locaux {
		t.Fatalf("réglages modifiés sans Odoo : %+v", fusionnés)
	}
}

// Odoo FAIT AUTORITE quand il repond : c'est la que le nombre de sonneries et
// l'annonce se reglent a plusieurs.
func TestOdooLEmporteQuandIlRepond(t *testing.T) {
	dossier := t.TempDir()
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "reglages": map[string]any{
				"actif": true, "sonneries": 5, "duree_max_secondes": 60,
				"annonce_nom": "bonjour.wav",
				"annonce_b64": base64.StdEncoding.EncodeToString([]byte("RIFF")),
			}})
		}))
	defer serveur.Close()

	locaux := RéglagesRépondeur{Sonneries: 2, Dossier: dossier, Annonce: "/local.wav"}
	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	fusionnés := RéglagesDepuisOdoo(lien, locaux)
	if fusionnés.Sonneries != 5 || !fusionnés.Actif {
		t.Fatalf("réglages d'Odoo ignorés : %+v", fusionnés)
	}
	if fusionnés.Dossier != dossier {
		t.Fatal("le dossier local a été écrasé : Odoo ne connaît pas ce disque")
	}
	// L'annonce est écrite À CÔTÉ de la locale : garder les deux permet de
	// repartir sur celle du disque si Odoo en sert une illisible.
	if fusionnés.Annonce == "/local.wav" {
		t.Fatal("annonce d'Odoo non écrite")
	}
	if _, err := os.Stat(fusionnés.Annonce); err != nil {
		t.Fatalf("annonce annoncée mais absente : %v", err)
	}
}

// Une annonce illisible ne doit pas priver le repondeur de celle qui marchait.
func TestUneAnnonceIllisibleGardeCelleDuDisque(t *testing.T) {
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "reglages": map[string]any{
				"actif": true, "sonneries": 3,
				"annonce_b64": "ceci n'est pas du base64 !!",
			}})
		}))
	defer serveur.Close()

	locaux := RéglagesRépondeur{Sonneries: 2, Dossier: t.TempDir(), Annonce: "/local.wav"}
	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	if fusionnés := RéglagesDepuisOdoo(lien, locaux); fusionnés.Annonce != "/local.wav" {
		t.Fatalf("annonce du disque perdue : %q", fusionnés.Annonce)
	}
}

// Le compagnon est marque APRES la reponse : une reponse perdue fait
// reessayer au prochain demarrage, et le controleur reconnait la reference.
// L'inverse perdrait le message pour de bon.
func TestUnTeleversementRefuseLaisseLeMessageSurDisque(t *testing.T) {
	dossier := t.TempDir()
	wav := filepath.Join(dossier, "message.wav")
	if err := os.WriteFile(wav, entêteWAV(0), 0o600); err != nil {
		t.Fatal(err)
	}
	m := &Message{Numéro: "15555550142", Début: "2026-09-05T08:00:00-04:00", Fichier: wav}
	if err := ÉcrireCompagnon(m); err != nil {
		t.Fatal(err)
	}

	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusForbidden)
			_, _ = w.Write([]byte(`{"ok": false, "error": "invalid signature"}`))
		}))
	defer serveur.Close()

	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	if err := TéléverserMessage(lien, m); err == nil {
		t.Fatal("refus d'Odoo passé sous silence")
	}
	messages, _ := ListerMessages(dossier)
	if len(messages) != 1 || messages[0].TéléverséOdoo {
		t.Fatal("message marqué monté alors qu'Odoo l'a refusé : il est perdu")
	}
}

// Un message enregistre pendant une panne d'Odoo n'a aucune autre occasion de
// monter que le demarrage suivant.
func TestLeDemarrageRattrapeCeQuiAttend(t *testing.T) {
	dossier := t.TempDir()
	for _, nom := range []string{"un", "deux"} {
		wav := filepath.Join(dossier, nom+".wav")
		if err := os.WriteFile(wav, entêteWAV(0), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := ÉcrireCompagnon(&Message{
			Numéro: "15555550142", Début: "2026-09-05T08:00:00-04:00", Fichier: wav,
		}); err != nil {
			t.Fatal(err)
		}
	}
	reçus := 0
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			reçus++
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "id": reçus})
		}))
	defer serveur.Close()

	lien := &LienOdoo{URL: serveur.URL, Secret: "s", Client: serveur.Client()}
	if montés := TéléverserCeQuiAttend(lien, dossier); montés != 2 {
		t.Fatalf("%d messages montés au lieu de 2", montés)
	}
	// Un second passage ne les remonte pas : le compagnon porte la marque.
	if montés := TéléverserCeQuiAttend(lien, dossier); montés != 0 {
		t.Fatalf("%d messages remontés une seconde fois", montés)
	}
}

// Odoo stocke en UTC sans fuseau : un horodatage local y serait lu comme de
// l'UTC, et les messages s'afficheraient decales de plusieurs heures.
func TestLHorodatagePartEnUTC(t *testing.T) {
	if got := horodatageOdoo("2026-09-05T08:00:00-04:00"); got != "2026-09-05 12:00:00" {
		t.Fatalf("horodatage %q : le message s'affichera à la mauvaise heure", got)
	}
}
