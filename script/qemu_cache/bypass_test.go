// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestNormalizeMAC(t *testing.T) {
	bons := map[string]string{
		"52:54:00:AA:BB:CC":   "52:54:00:aa:bb:cc",
		"52-54-00-aa-bb-cc":   "52:54:00:aa:bb:cc",
		"525400aabbcc":        "52:54:00:aa:bb:cc",
		" 52:54:00:01:02:03 ": "52:54:00:01:02:03",
	}
	for brut, attendu := range bons {
		got, err := NormalizeMAC(brut)
		if err != nil {
			t.Errorf("%q refusée : %v", brut, err)
			continue
		}
		if got != attendu {
			t.Errorf("%q → %q, attendu %q", brut, got, attendu)
		}
	}
}

// Deux refus qui protègent d'une exception morte à l'écriture.
func TestNormalizeMACRefuse(t *testing.T) {
	for _, brut := range []string{
		"",
		"pas une adresse",
		"52:54:00:aa:bb",          // cinq octets
		"52:54:00:aa:bb:cc:dd:ee", // huit : une adresse InfiniBand
		"00:00:00:00:00:00",       // n'identifie rien
		"ff:ff:ff:ff:ff:ff",       // diffusion : jamais une source
		"01:00:5e:00:00:01",       // groupe : jamais une source
	} {
		if got, err := NormalizeMAC(brut); err == nil {
			t.Errorf("%q acceptée et rendue %q", brut, got)
		}
	}
}

func fichierNeuf(t *testing.T) BypassFile {
	t.Helper()
	return BypassFile{Path: filepath.Join(t.TempDir(), "bypass")}
}

// Un fichier absent est l'état normal d'une installation neuve, pas une
// panne : le service doit démarrer.
func TestChargerUnFichierAbsent(t *testing.T) {
	b := BypassFile{Path: filepath.Join(t.TempDir(), "jamais-ecrit")}
	entries, err := b.Load()
	if err != nil {
		t.Fatalf("un fichier absent lève : %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("%d entrées sorties de rien", len(entries))
	}
}

func TestAjouterPuisRetirer(t *testing.T) {
	b := fichierNeuf(t)
	mac, err := b.Add("52:54:00:AA:BB:CC", "vm-essai")
	if err != nil {
		t.Fatalf("ajout : %v", err)
	}
	if mac != "52:54:00:aa:bb:cc" {
		t.Errorf("MAC rendue %q", mac)
	}
	entries, _ := b.Load()
	if len(entries) != 1 || entries[0].Name != "vm-essai" {
		t.Fatalf("relecture : %+v", entries)
	}
	// La forme d'écriture ne doit pas décider du retrait.
	_, avait, err := b.Del("525400AABBCC")
	if err != nil || !avait {
		t.Fatalf("retrait : avait=%v err=%v", avait, err)
	}
	entries, _ = b.Load()
	if len(entries) != 0 {
		t.Errorf("%d entrée(s) survivent au retrait", len(entries))
	}
}

// Le déploiement est relancé : la même VM ne doit pas produire deux lignes,
// sans quoi un seul retrait laisserait l'exception en place.
func TestReposerLaMemeMACMetAJour(t *testing.T) {
	b := fichierNeuf(t)
	if _, err := b.Add("52:54:00:aa:bb:cc", "ancien"); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Add("52:54:00:AA:BB:CC", "neuf"); err != nil {
		t.Fatal(err)
	}
	entries, _ := b.Load()
	if len(entries) != 1 {
		t.Fatalf("%d entrées pour une machine : %+v", len(entries), entries)
	}
	if entries[0].Name != "neuf" {
		t.Errorf("nom resté %q", entries[0].Name)
	}
}

func TestRetirerCeQuiNyEstPas(t *testing.T) {
	b := fichierNeuf(t)
	mac, avait, err := b.Del("52:54:00:00:00:09")
	if err != nil {
		t.Fatalf("un retrait à vide lève : %v", err)
	}
	if avait {
		t.Error("dit avoir retiré une exception absente")
	}
	if mac == "" {
		t.Error("la MAC canonique doit être rendue pour le geste à chaud")
	}
}

// Le fichier est éditable à la main : une faute de frappe ne doit pas
// empêcher le service de démarrer, seulement perdre sa ligne.
func TestUneLigneIllisibleEstSautee(t *testing.T) {
	b := fichierNeuf(t)
	contenu := strings.Join([]string{
		"# un commentaire",
		"",
		"52:54:00:11:22:33 vm-une   # en fin de ligne",
		"ceci n'est pas une adresse",
		"ff:ff:ff:ff:ff:ff diffusion",
		"52:54:00:44:55:66",
		"52:54:00:11:22:33 doublon",
	}, "\n")
	if err := os.WriteFile(b.Path, []byte(contenu), 0o644); err != nil {
		t.Fatal(err)
	}
	entries, err := b.Load()
	if err != nil {
		t.Fatalf("lecture : %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("%d entrées retenues : %+v", len(entries), entries)
	}
	if entries[0].MAC != "52:54:00:11:22:33" || entries[0].Name != "vm-une" {
		t.Errorf("première entrée : %+v", entries[0])
	}
	if entries[1].MAC != "52:54:00:44:55:66" {
		t.Errorf("seconde entrée : %+v", entries[1])
	}
}

// Le nom voyage avec la MAC : c'est lui qui dit quelle entrée retirer quand
// la VM meurt. Une entrée orpheline soustrairait au cache une machine neuve
// qui hériterait de la MAC, sans que personne l'ait demandé.
func TestLeNomSurvitAuxAllersRetours(t *testing.T) {
	b := fichierNeuf(t)
	if _, err := b.Add("52:54:00:77:88:99", "vm de démonstration"); err != nil {
		t.Fatal(err)
	}
	entries, _ := b.Load()
	if len(entries) != 1 || entries[0].Name != "vm de démonstration" {
		t.Fatalf("nom perdu : %+v", entries)
	}
}

func TestGestesAChaud(t *testing.T) {
	mac := "52:54:00:aa:bb:cc"
	ajout := BypassAddElement(mac)
	retrait := BypassDelElement(mac)
	for _, l := range []string{ajout, retrait} {
		if !strings.Contains(l, TableName) ||
			!strings.Contains(l, BypassSetName) ||
			!strings.Contains(l, mac) {
			t.Errorf("geste incomplet : %q", l)
		}
	}
	if !strings.HasPrefix(ajout, "add element") {
		t.Errorf("ajout : %q", ajout)
	}
	if !strings.HasPrefix(retrait, "delete element") {
		t.Errorf("retrait : %q", retrait)
	}
}
