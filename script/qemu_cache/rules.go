// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"strings"
)

// RuleSet décrit le détournement à poser sur le pont de l'orchestrateur.
//
// Les règles sont RENDUES sous forme de texte et jamais exécutées depuis ce
// paquet : le script d'installation les applique, et un test peut donc les
// vérifier au caractère près sans toucher au pare-feu de la machine qui
// exécute les tests.
type RuleSet struct {
	// Bridge est le pont que libvirt donne à ses VM, « virbr0 » par défaut.
	Bridge string
	// Subnet est le /24 que ce réseau sert.
	Subnet string
	// HTTPPort et TLSPort sont les deux écoutes du cache.
	HTTPPort int
	TLSPort  int
	// Bypass : les adresses MAC soustraites au détournement, déjà
	// canoniques. Vide, l'ensemble existe quand même — il est peuplé à
	// chaud, et une règle qui viserait un ensemble absent ferait échouer
	// TOUT le jeu de règles, donc le démarrage du service.
	Bypass []string
}

// TableName : une table à nous, effaçable d'un geste, plutôt que des règles
// ajoutées dans les chaînes d'autrui — que le retrait devrait alors retrouver
// une par une.
const TableName = "erplibre_qemu_cache"

// NftLines rend les lignes à passer à « nft -f - ».
//
// La clause « ip daddr != <subnet> » est la garde qui compte : sans elle, une
// VM qui joint l'orchestrateur lui-même — ssh, Odoo, un service quelconque
// sur la passerelle du /24 — se retrouve détournée vers le cache, qui ne sait
// rien en faire. Seul ce qui SORT du sous-réseau est intercepté. Une règle
// réseau posée trop large sur le pont d'un hôte est la classe de panne qui
// prive une machine de son propre réseau.
//
// L'exception par MAC passe AVANT les deux détournements, sans quoi elle
// n'aurait aucun effet : la première règle qui rend un verdict l'emporte.
// « accept » clôt cette chaîne-ci et non le hook : les chaînes des autres
// tables — le masquage de libvirt, notamment — sont évaluées ensuite, donc
// une VM exceptée garde son réseau normal.
func (r RuleSet) NftLines() []string {
	lignes := []string{
		fmt.Sprintf("table ip %s {", TableName),
		fmt.Sprintf("  set %s {", BypassSetName),
		"    type ether_addr",
	}
	if len(r.Bypass) > 0 {
		lignes = append(lignes, fmt.Sprintf(
			"    elements = { %s }", strings.Join(r.Bypass, ", ")))
	}
	lignes = append(lignes,
		"  }",
		"  chain prerouting {",
		"    type nat hook prerouting priority dstnat; policy accept;",
		fmt.Sprintf(
			`    iifname "%s" ether saddr @%s accept`,
			r.Bridge, BypassSetName),
		fmt.Sprintf(
			`    iifname "%s" ip saddr %s ip daddr != %s tcp dport 80 redirect to :%d`,
			r.Bridge, r.Subnet, r.Subnet, r.HTTPPort),
		fmt.Sprintf(
			`    iifname "%s" ip saddr %s ip daddr != %s tcp dport 443 redirect to :%d`,
			r.Bridge, r.Subnet, r.Subnet, r.TLSPort),
		"  }",
		"}",
	)
	return lignes
}

// NftDeleteLine rend le geste de retrait. Une seule table à effacer, donc un
// seul geste : le désarmement ne peut pas être à moitié fait.
func (r RuleSet) NftDeleteLine() string {
	return fmt.Sprintf("nft delete table ip %s", TableName)
}

// IptablesLines rend l'équivalent pour un hôte qui n'a pas nft. Le script
// d'installation choisit selon ce qui répond ; les deux jeux disent la même
// chose.
//
// Les exceptions sont émises en tête : iptables n'a pas d'ensemble nommé, la
// chaîne est bâtie par « -A » successifs, et un RETURN posé après les
// redirections ne serait jamais atteint. Le corollaire est qu'ici une
// exception neuve demande de reposer les règles, là où nft en ajoute une à
// chaud.
func (r RuleSet) IptablesLines() []string {
	var lignes []string
	for _, mac := range r.Bypass {
		lignes = append(lignes, fmt.Sprintf(
			"iptables -t nat -A PREROUTING -i %s -m mac --mac-source %s "+
				"-j RETURN", r.Bridge, mac))
	}
	return append(lignes,
		fmt.Sprintf(
			"iptables -t nat -A PREROUTING -i %s -s %s ! -d %s "+
				"-p tcp --dport 80 -j REDIRECT --to-ports %d",
			r.Bridge, r.Subnet, r.Subnet, r.HTTPPort),
		fmt.Sprintf(
			"iptables -t nat -A PREROUTING -i %s -s %s ! -d %s "+
				"-p tcp --dport 443 -j REDIRECT --to-ports %d",
			r.Bridge, r.Subnet, r.Subnet, r.TLSPort),
	)
}

// GuestEnvLines rend ce qu'une VM doit poser en plus de l'autorité.
//
// pip embarque son propre jeu de certificats et IGNORE le magasin système ;
// npm fait de même. Poser l'autorité ne suffit donc pas pour eux, alors
// qu'elle suffit pour pacman et pour apt, qui lisent le magasin.
//
// La valeur visée est le FAISCEAU système, que la commande de confiance
// régénère avec notre autorité dedans — et non le seul certificat du cache :
// pointer celui-là ferait perdre à pip toutes les autres autorités, donc
// échouer sur le premier hôte que le cache ne déchiffre pas, et le jour où le
// cache disparaît.
func GuestEnvLines(caPath string) []string {
	return []string{
		fmt.Sprintf("PIP_CERT=%s", caPath),
		fmt.Sprintf("REQUESTS_CA_BUNDLE=%s", caPath),
		fmt.Sprintf("NODE_EXTRA_CA_CERTS=%s", caPath),
	}
}

// GuestTrustCommand rend la commande qui fait approuver l'autorité, par
// famille de distribution. Le chemin ET la commande changent, et se tromper
// laisse une VM qui échoue sur chaque téléchargement HTTPS.
//
// Les familles portent le nom de leur gestionnaire de paquets, comme partout
// ailleurs dans le dépôt. La même table existe côté déploiement, qui écrit le
// fichier dans l'invité ; un test les compare, la dérive entre deux copies
// étant le seul risque de cette duplication.
func GuestTrustCommand(family string) (dir, cmd, bundle string, ok bool) {
	switch family {
	case "pacman":
		return "/etc/ca-certificates/trust-source/anchors", "trust extract-compat",
			"/etc/ssl/certs/ca-certificates.crt", true
	case "apt":
		return "/usr/local/share/ca-certificates", "update-ca-certificates",
			"/etc/ssl/certs/ca-certificates.crt", true
	case "dnf":
		return "/etc/pki/ca-trust/source/anchors", "update-ca-trust",
			"/etc/pki/tls/certs/ca-bundle.crt", true
	case "zypper":
		// openSUSE range ses ancres ailleurs que la famille RHEL, tout en
		// employant la même commande que Debian.
		return "/etc/pki/trust/anchors", "update-ca-certificates",
			"/etc/ssl/certs/ca-certificates.crt", true
	}
	return "", "", "", false
}
