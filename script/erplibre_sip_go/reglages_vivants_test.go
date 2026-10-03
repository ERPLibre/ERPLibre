// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

// serveurRéglages rend un serveur qui répond ce qu'on lui dit, et compte les
// lectures.
func serveurRéglages(t *testing.T, sonneries *atomic.Int64,
	lectures *atomic.Int64) *httptest.Server {
	t.Helper()
	serveur := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			lectures.Add(1)
			fmt.Fprintf(w, `{"ok": true, "reglages": {"actif": true,`+
				`"sonneries": %d, "duree_max_secondes": 30}}`, sonneries.Load())
		}))
	t.Cleanup(serveur.Close)
	return serveur
}

// lienVers monte un lien comme le service le fait, avec le delai ORDINAIRE.
//
// Pas celui du chemin de l'appel : les deux se confondraient, et l'essai qui
// verifie que le lien d'origine n'est pas modifie passerait sans rien prouver.
func lienVers(url string) *LienOdoo {
	return &LienOdoo{URL: url, Secret: "s", Appareil: "a",
		Client: &http.Client{Timeout: DélaiOdoo}}
}

func TestLesReglagesSuiventOdooSansRedemarrage(t *testing.T) {
	// Lus une fois au demarrage, un nombre de sonneries change a l'ecran ne
	// s'appliquait jamais, et rien ne le disait.
	var sonneries, lectures atomic.Int64
	sonneries.Store(2)
	serveur := serveurRéglages(t, &sonneries, &lectures)

	vivants := NouveauxRéglagesVivants(lienVers(serveur.URL), RéglagesParDéfaut())
	vivants.Relire()
	if vivants.Valeurs().Sonneries != 2 {
		t.Fatalf("premiere lecture : %d sonneries", vivants.Valeurs().Sonneries)
	}

	sonneries.Store(5)
	if !vivants.Relire() {
		t.Fatal("un changement doit se dire")
	}
	if vivants.Valeurs().Sonneries != 5 {
		t.Fatalf("apres changement : %d sonneries", vivants.Valeurs().Sonneries)
	}
	if vivants.Relire() {
		t.Fatal("une lecture identique ne doit pas se declarer changee")
	}
}

func TestUneCoupureGardeLesDernieresValeursDOdoo(t *testing.T) {
	// Une coupure passagere ne doit pas ramener le repondeur a un reglage
	// qu'on a deja remplace : le disque disait 3 sonneries, Odoo en dit 5, et
	// l'appel suivant doit en voir 5.
	var sonneries, lectures atomic.Int64
	sonneries.Store(5)
	serveur := serveurRéglages(t, &sonneries, &lectures)
	locaux := RéglagesParDéfaut()
	locaux.Sonneries = 3

	vivants := NouveauxRéglagesVivants(lienVers(serveur.URL), locaux)
	vivants.Relire()
	serveur.Close()

	vivants.Relire()
	if got := vivants.Valeurs().Sonneries; got != 5 {
		t.Fatalf("apres la coupure : %d sonneries, attendu 5", got)
	}
}

func TestUneLectureEnEchecNePasseParPourFraiche(t *testing.T) {
	// Sinon un Odoo muet passerait pour frais, et la tentative suivante — au
	// moment ou un appel arrive — serait sautee.
	vivants := NouveauxRéglagesVivants(lienVers("http://127.0.0.1:1"),
		RéglagesParDéfaut())
	vivants.Relire()
	if !vivants.luÀ.IsZero() {
		t.Fatal("une lecture en echec a date les valeurs")
	}
	// La tolerance ne la protege donc pas : la tentative suivante a bien lieu.
	vivants.RelireSiVieux(time.Hour, 200*time.Millisecond)
	if !vivants.luÀ.IsZero() {
		t.Fatal("une seconde lecture en echec a date les valeurs")
	}
}

func TestDesValeursFraichesNeSontPasRelues(t *testing.T) {
	// Le chemin de l'appel court apres la boite vocale de l'operateur : une
	// lecture inutile y mangerait du budget.
	var sonneries, lectures atomic.Int64
	sonneries.Store(2)
	serveur := serveurRéglages(t, &sonneries, &lectures)

	vivants := NouveauxRéglagesVivants(lienVers(serveur.URL), RéglagesParDéfaut())
	vivants.Relire()
	avant := lectures.Load()
	vivants.RelireSiVieux(time.Hour, time.Second)
	if lectures.Load() != avant {
		t.Fatal("des valeurs fraiches ont ete relues pour rien")
	}
}

func TestDesValeursVieillesSontReluesALAppel(t *testing.T) {
	var sonneries, lectures atomic.Int64
	sonneries.Store(2)
	serveur := serveurRéglages(t, &sonneries, &lectures)

	vivants := NouveauxRéglagesVivants(lienVers(serveur.URL), RéglagesParDéfaut())
	vivants.Relire()
	avant := lectures.Load()
	vivants.RelireSiVieux(time.Nanosecond, time.Second)
	if lectures.Load() <= avant {
		t.Fatal("des valeurs vieilles n'ont pas ete relues")
	}
}

func TestLaRelectureALAppelEstPlusPresseeQueLeReste(t *testing.T) {
	// Le televersement d'un message porte un WAV et a besoin de tout son
	// delai ; la relecture pendant une sonnerie, non.
	if DélaiRéglagesÀLAppel >= DélaiOdoo {
		t.Fatalf("delai a l'appel %s, delai ordinaire %s : le chemin de"+
			" l'appel doit etre le plus court", DélaiRéglagesÀLAppel, DélaiOdoo)
	}
	vivants := NouveauxRéglagesVivants(lienVers("http://127.0.0.1:1"),
		RéglagesParDéfaut())
	if pressé := vivants.lienPressé(DélaiRéglagesÀLAppel); pressé.Client.Timeout != DélaiRéglagesÀLAppel {
		t.Fatalf("delai du lien presse : %s", pressé.Client.Timeout)
	}
	if vivants.lien.Client.Timeout == DélaiRéglagesÀLAppel {
		t.Fatal("le lien d'origine a ete modifie")
	}
}

func TestLAnnonceNEstReecriteQueSiElleChange(t *testing.T) {
	// La route renvoie l'annonce a CHAQUE lecture : reecrire le fichier chaque
	// minute l'userait pour rien, et changerait sa date sans raison.
	dossier := t.TempDir()
	locaux := RéglagesParDéfaut()
	locaux.Dossier = dossier

	chemin := écrireAnnonce(locaux, "annonce.wav", "UklGRg==")
	if chemin == "" {
		t.Fatal("annonce non ecrite")
	}
	avant, err := os.Stat(chemin)
	if err != nil {
		t.Fatal(err)
	}
	// Une seconde de recul : la resolution de l'horodatage d'un fichier ne
	// distingue pas deux ecritures dans la meme milliseconde.
	if err := os.Chtimes(chemin, avant.ModTime().Add(-time.Second),
		avant.ModTime().Add(-time.Second)); err != nil {
		t.Fatal(err)
	}
	repere, _ := os.Stat(chemin)

	écrireAnnonce(locaux, "annonce.wav", "UklGRg==")
	après, _ := os.Stat(chemin)
	if !après.ModTime().Equal(repere.ModTime()) {
		t.Fatal("une annonce identique a ete reecrite")
	}

	écrireAnnonce(locaux, "annonce.wav", "UklGRhIhIQ==")
	octets, err := os.ReadFile(filepath.Join(dossier, "odoo_annonce.wav"))
	if err != nil {
		t.Fatal(err)
	}
	if len(octets) == len("RIFF") {
		t.Fatal("une annonce differente n'a pas remplace l'ancienne")
	}
}

func TestUnDossierAbsentSeDeduitAuLieuDEchouer(t *testing.T) {
	// Odoo n'envoie pas de dossier — un chemin de cette machine n'est pas son
	// affaire — et le CLI le comble sans forcement l'ecrire. Sans repli, un
	// repondeur actif decroche, refuse d'enregistrer, et l'appelant perd son
	// message apres avoir parle.
	dossier := t.TempDir()
	chemin := filepath.Join(dossier, "repondeur.json")
	if err := os.WriteFile(chemin,
		[]byte(`{"actif": true, "sonneries": 3}`), 0o600); err != nil {
		t.Fatal(err)
	}
	réglages, err := ChargerRéglagesRépondeur(chemin)
	if err != nil {
		t.Fatal(err)
	}
	if réglages.Dossier == "" {
		t.Fatal("dossier vide : le repondeur decrocherait sans pouvoir enregistrer")
	}
	if attendu := filepath.Join(dossier, "messages"); réglages.Dossier != attendu {
		t.Fatalf("dossier %q, attendu %q", réglages.Dossier, attendu)
	}
}

func TestUnDossierEcritEstRespecte(t *testing.T) {
	dossier := t.TempDir()
	chemin := filepath.Join(dossier, "repondeur.json")
	if err := os.WriteFile(chemin,
		[]byte(`{"actif": true, "dossier": "/ailleurs/messages"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	réglages, err := ChargerRéglagesRépondeur(chemin)
	if err != nil {
		t.Fatal(err)
	}
	if réglages.Dossier != "/ailleurs/messages" {
		t.Fatalf("le dossier du fichier a ete remplace : %q", réglages.Dossier)
	}
}

func TestLeJournalNeRetientQueLesFaitsNouveaux(t *testing.T) {
	// Relus chaque minute, les reglages ecrivaient une ligne par lecture :
	// mille lignes identiques pour cent qui disent quelque chose, et la panne
	// qu'on cherche noyee dedans.
	var sonneries, lectures atomic.Int64
	sonneries.Store(2)
	serveur := serveurRéglages(t, &sonneries, &lectures)

	écrites := 0
	ancien := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(écrivainComptant{&écrites},
		&slog.HandlerOptions{Level: slog.LevelInfo})))
	t.Cleanup(func() { slog.SetDefault(ancien) })

	vivants := NouveauxRéglagesVivants(lienVers(serveur.URL), RéglagesParDéfaut())
	vivants.Relire()
	if écrites != 1 {
		t.Fatalf("la premiere lecture doit se dire une fois, %d ligne(s)", écrites)
	}
	for i := 0; i < 5; i++ {
		vivants.Relire()
	}
	if écrites != 1 {
		t.Fatalf("des lectures sans changement ont ecrit : %d ligne(s)", écrites)
	}
	sonneries.Store(5)
	vivants.Relire()
	if écrites != 2 {
		t.Fatalf("un changement doit se dire, %d ligne(s)", écrites)
	}
}

// écrivainComptant compte les lignes de journal au lieu de les afficher.
type écrivainComptant struct{ lignes *int }

func (e écrivainComptant) Write(p []byte) (int, error) {
	*e.lignes++
	return len(p), nil
}

func TestUnArretDemandeNEstPasUnePanne(t *testing.T) {
	// Le serveur rend l'erreur de son ecouteur ferme quand on l'arrete, et la
	// compter comme une panne faisait afficher « failed » a systemd pour un
	// arret normal. L'exploitant lit cet etat avant tout le reste.
	ctx, arrêter := context.WithCancel(context.Background())
	erreur := errors.New("accept tcp 127.0.0.1:8189: use of closed network connection")

	if arrêtDemandé(ctx, erreur) {
		t.Fatal("une erreur sans arret demande doit rester une panne")
	}
	arrêter()
	if !arrêtDemandé(ctx, erreur) {
		t.Fatal("l'erreur qui suit un arret demande n'est pas une panne")
	}
	if arrêtDemandé(ctx, nil) {
		t.Fatal("sans erreur, il n'y a rien a classer")
	}
}
