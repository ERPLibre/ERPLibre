// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"strings"
	"testing"
)

func jeuDeTest() RuleSet {
	return RuleSet{
		Bridge: "virbr0", Subnet: "192.168.122.0/24",
		HTTPPort: 8898, TLSPort: 8899,
	}
}

// La garde qui compte : seul ce qui SORT du sous-réseau est détourné. Sans
// elle, une VM qui joint l'orchestrateur lui-même — ssh, Odoo, un service sur
// la passerelle du /24 — part vers le cache, qui n'en sait rien faire.
func TestNftEpargneLeTraficInterne(t *testing.T) {
	lignes := jeuDeTest().NftLines()
	texte := strings.Join(lignes, "\n")

	if !strings.Contains(texte, "ip daddr != 192.168.122.0/24") {
		t.Errorf("l'exclusion du trafic interne manque :\n%s", texte)
	}
	for _, port := range []string{"tcp dport 80", "tcp dport 443"} {
		if !strings.Contains(texte, port) {
			t.Errorf("%q absent des règles", port)
		}
	}
	if !strings.Contains(texte, "redirect to :8898") {
		t.Error("le 80 ne part pas vers l'écoute HTTP")
	}
	if !strings.Contains(texte, "redirect to :8899") {
		t.Error("le 443 ne part pas vers l'écoute TLS")
	}
	if !strings.Contains(texte, `iifname "virbr0"`) {
		t.Error("les règles ne sont pas bornées au pont des VM")
	}
}

// Chaque règle porte l'exclusion : une seule qui l'oublie suffit à couper le
// trafic interne du port qu'elle vise.
func TestChaqueRegleDeRedirectionPorteLExclusion(t *testing.T) {
	for _, l := range jeuDeTest().NftLines() {
		if !strings.Contains(l, "redirect to") {
			continue
		}
		if !strings.Contains(l, "ip daddr != 192.168.122.0/24") {
			t.Errorf("règle sans exclusion : %s", l)
		}
	}
	for _, l := range jeuDeTest().IptablesLines() {
		if !strings.Contains(l, "! -d 192.168.122.0/24") {
			t.Errorf("règle iptables sans exclusion : %s", l)
		}
	}
}

// Le retrait est UN geste : un désarmement à moitié fait laisserait une VM
// détournée vers un cache éteint.
func TestRetraitEnUnGeste(t *testing.T) {
	l := jeuDeTest().NftDeleteLine()
	if !strings.Contains(l, "delete table ip "+TableName) {
		t.Errorf("le retrait n'efface pas la table : %s", l)
	}
	if strings.Count(l, "\n") != 0 {
		t.Errorf("le retrait tient sur plusieurs lignes : %q", l)
	}
}

// La table porte un nom à nous : des règles ajoutées dans les chaînes
// d'autrui devraient être retrouvées une par une pour être retirées.
func TestTableNommee(t *testing.T) {
	if !strings.Contains(jeuDeTest().NftLines()[0], TableName) {
		t.Error("les règles ne vivent pas dans une table nommée")
	}
}

// pip et npm ignorent le magasin système : poser l'autorité ne suffit pas
// pour eux, alors qu'elle suffit pour pacman et pour apt.
func TestVariablesDeLInvite(t *testing.T) {
	lignes := GuestEnvLines("/etc/ssl/certs/ca-certificates.crt")
	attendues := []string{"PIP_CERT=", "REQUESTS_CA_BUNDLE=", "NODE_EXTRA_CA_CERTS="}
	if len(lignes) != len(attendues) {
		t.Fatalf("%d variables, attendu %d", len(lignes), len(attendues))
	}
	texte := strings.Join(lignes, "\n")
	for _, a := range attendues {
		if !strings.Contains(texte, a) {
			t.Errorf("%q manque :\n%s", a, texte)
		}
	}
	for _, l := range lignes {
		if !strings.HasSuffix(l, "/etc/ssl/certs/ca-certificates.crt") {
			t.Errorf("la variable ne pointe pas l'autorité : %s", l)
		}
	}
}

// Le chemin ET la commande changent par famille : se tromper laisse une VM
// qui échoue sur chaque téléchargement HTTPS.
func TestCommandeDeConfiance(t *testing.T) {
	cas := map[string][3]string{
		"pacman": {
			"/etc/ca-certificates/trust-source/anchors", "trust extract-compat",
			"/etc/ssl/certs/ca-certificates.crt",
		},
		"apt": {
			"/usr/local/share/ca-certificates", "update-ca-certificates",
			"/etc/ssl/certs/ca-certificates.crt",
		},
		"dnf": {
			"/etc/pki/ca-trust/source/anchors", "update-ca-trust",
			"/etc/pki/tls/certs/ca-bundle.crt",
		},
		"zypper": {
			"/etc/pki/trust/anchors", "update-ca-certificates",
			"/etc/ssl/certs/ca-certificates.crt",
		},
	}
	for famille, attendu := range cas {
		dir, cmd, bundle, ok := GuestTrustCommand(famille)
		if !ok {
			t.Errorf("%s : famille inconnue", famille)
			continue
		}
		if dir != attendu[0] {
			t.Errorf("%s : répertoire %q, attendu %q", famille, dir, attendu[0])
		}
		if cmd != attendu[1] {
			t.Errorf("%s : commande %q, attendu %q", famille, cmd, attendu[1])
		}
		if bundle != attendu[2] {
			t.Errorf("%s : faisceau %q, attendu %q", famille, bundle, attendu[2])
		}
	}
	if _, _, _, ok := GuestTrustCommand("plan9"); ok {
		t.Error("une famille inconnue est pourtant acceptée")
	}
}
