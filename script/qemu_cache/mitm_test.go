// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"crypto/x509"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCreationEtRelectureDeLAutorite(t *testing.T) {
	dir := t.TempDir()
	ca1, err := LoadOrCreateCA(dir)
	if err != nil {
		t.Fatalf("création : %v", err)
	}
	// Relire ne doit PAS régénérer : une autorité neuve invaliderait les
	// certificats de toutes les VM déjà configurées.
	ca2, err := LoadOrCreateCA(dir)
	if err != nil {
		t.Fatalf("relecture : %v", err)
	}
	if ca1.Fingerprint() != ca2.Fingerprint() {
		t.Errorf("l'autorité a été régénérée :\n  %s\n  %s",
			ca1.Fingerprint(), ca2.Fingerprint())
	}
	if !ca1.cert.IsCA {
		t.Error("le certificat n'est pas une autorité")
	}
}

// La clé permet de se faire passer pour n'importe quel site auprès d'une VM
// qui approuve l'autorité : elle ne doit être lisible que par son
// propriétaire.
func TestCleDeLAutoriteEnMode0600(t *testing.T) {
	dir := t.TempDir()
	if _, err := LoadOrCreateCA(dir); err != nil {
		t.Fatalf("création : %v", err)
	}
	st, err := os.Stat(filepath.Join(dir, "ca.key"))
	if err != nil {
		t.Fatalf("clé absente : %v", err)
	}
	if mode := st.Mode().Perm(); mode != 0o600 {
		t.Errorf("clé en %o, attendu 600", mode)
	}
	// Le certificat, lui, part dans les VM : il doit rester lisible.
	stc, err := os.Stat(CertPath(dir))
	if err != nil {
		t.Fatalf("certificat absent : %v", err)
	}
	if mode := stc.Mode().Perm(); mode != 0o644 {
		t.Errorf("certificat en %o, attendu 644", mode)
	}
}

// Une feuille doit se vérifier CONTRE l'autorité, sans quoi l'invité la
// rejette malgré la confiance accordée.
func TestFeuilleVerifieeParLAutorite(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	crt, err := ca.leafFor("miroir.example")
	if err != nil {
		t.Fatalf("feuille : %v", err)
	}
	leaf, err := x509.ParseCertificate(crt.Certificate[0])
	if err != nil {
		t.Fatalf("feuille illisible : %v", err)
	}

	pool := x509.NewCertPool()
	pool.AddCert(ca.cert)
	if _, err := leaf.Verify(x509.VerifyOptions{
		DNSName: "miroir.example",
		Roots:   pool,
	}); err != nil {
		t.Errorf("la feuille ne se vérifie pas : %v", err)
	}

	// La chaîne envoyée porte l'autorité après la feuille : un invité qui ne
	// la connaît pas encore doit pouvoir la voir.
	if len(crt.Certificate) != 2 {
		t.Errorf("la chaîne porte %d certificats, attendu 2", len(crt.Certificate))
	}
}

// Un hôte demandé deux fois ne coûte qu'une génération : une installation
// touche des dizaines d'hôtes.
func TestFeuilleGardeeEnMemoire(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	a, _ := ca.leafFor("miroir.example")
	b, _ := ca.leafFor("miroir.example")
	if a != b {
		t.Error("la feuille est régénérée à chaque demande")
	}
}

// Un SNI qui est une adresse IP ne peut pas aller dans un nom DNS.
func TestFeuillePourUneAdresseIP(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	crt, err := ca.leafFor("192.168.122.50")
	if err != nil {
		t.Fatalf("feuille : %v", err)
	}
	leaf, _ := x509.ParseCertificate(crt.Certificate[0])
	if len(leaf.IPAddresses) != 1 {
		t.Errorf("%d adresse(s) dans le certificat, attendu 1", len(leaf.IPAddresses))
	}
	if len(leaf.DNSNames) != 0 {
		t.Errorf("une adresse IP est passée en nom DNS : %v", leaf.DNSNames)
	}
}

// Le repli ne se déclare pas d'avance : un hôte qui refuse le certificat est
// retenu, et la requête suivante vers lui n'essaie plus de le déchiffrer.
func TestRefusRetenu(t *testing.T) {
	r := NewRefusals(nil)
	if r.Has("api.example") {
		t.Fatal("un hôte est exclu avant tout refus")
	}
	r.Add("api.example")
	if !r.Has("api.example") {
		t.Error("le refus n'est pas retenu")
	}
	// Deux fois le même hôte ne double pas l'entrée.
	r.Add("api.example")
	if n := len(r.List()); n != 1 {
		t.Errorf("%d hôtes retenus, attendu 1", n)
	}
}

// Un suffixe couvre un domaine entier, sous-domaines compris.
func TestExclusionParSuffixe(t *testing.T) {
	r := NewRefusals([]string{".snapcraft.io"})
	for _, h := range []string{"api.snapcraft.io", "dashboard.snapcraft.io"} {
		if !r.Has(h) {
			t.Errorf("%s n'est pas couvert par le suffixe", h)
		}
	}
	if r.Has("snapcraft.io.example.com") {
		t.Error("le suffixe attrape un domaine qui ne fait que le contenir")
	}
}

// Les hôtes dont l'épinglage est connu d'avance évitent de perdre une requête
// pour l'apprendre.
func TestExclusionsParDefaut(t *testing.T) {
	r := NewRefusals(DefaultExclusions)
	if !r.Has("api.snapcraft.io") {
		t.Error("snapd n'est pas exclu d'avance, alors qu'il épingle")
	}
}

// La casse d'un nom d'hôte n'a pas de sens en DNS.
func TestExclusionInsensibleALaCasse(t *testing.T) {
	r := NewRefusals([]string{"API.Example"})
	if !r.Has("api.example") {
		t.Error("l'exclusion dépend de la casse")
	}
}

// L'empreinte sert à vérifier de visu qu'une VM approuve BIEN cette autorité.
func TestEmpreinteLisible(t *testing.T) {
	ca, err := LoadOrCreateCA(t.TempDir())
	if err != nil {
		t.Fatalf("autorité : %v", err)
	}
	fp := ca.Fingerprint()
	if n := strings.Count(fp, ":"); n != 31 {
		t.Errorf("%d séparateurs, attendu 31 pour un SHA-256", n)
	}
	if fp != strings.ToUpper(fp) {
		t.Errorf("empreinte en minuscules : %s", fp)
	}
}

// Un premier enregistrement qui n'est pas une poignée de main TLS est refusé
// tôt : le port du 443 détourné ne reçoit rien d'autre.
func TestPremierEnregistrementNonTLS(t *testing.T) {
	if _, err := peekSNI([]byte{0x17, 0x03, 0x03, 0x00, 0x01, 0x00}); err == nil {
		t.Error("un enregistrement qui n'est pas un handshake est accepté")
	}
}
