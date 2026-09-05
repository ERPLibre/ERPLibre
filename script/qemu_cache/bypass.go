// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Le détournement est TRANSPARENT : il vaut pour tout ce qui sort du pont, et
// une VM n'a aucun moyen de s'y soustraire depuis l'intérieur. Ne pas lui
// donner l'autorité ne la dispense pas d'être interceptée — cela lui fait
// seulement refuser un certificat qu'elle ne reconnaît pas, et échouer sur
// « self-signed certificate in certificate chain ».
//
// Une exception doit donc être posée sur l'HÔTE, avant que la VM démarre, et
// elle a besoin d'un identifiant que la VM porte de façon stable. L'adresse
// IP ne convient pas : elle vient d'un bail qui change. L'adresse MAC est
// fixée dans la définition du domaine et ne bouge plus.
//
// Elle est tenue dans un ensemble nommé nftables plutôt que dans les règles
// elles-mêmes : un élément s'ajoute et se retire à chaud, sans reposer le
// jeu de règles, donc sans couper les téléchargements des autres VM.

// BypassSetName : le nom de l'ensemble à l'intérieur de la table.
const BypassSetName = "bypass"

// BypassEntry associe l'adresse MAC soustraite au nom de la VM qui la porte.
//
// Le nom n'entre dans aucune règle ; il existe pour que la liste soit
// relisible et pour que l'on sache quelle entrée retirer quand la VM meurt.
// Une MAC orpheline est le mode de défaillance de ce fichier : réattribuée à
// une VM neuve, elle la soustrairait au cache sans que personne l'ait
// demandé, et rien ne le dirait.
type BypassEntry struct {
	MAC  string
	Name string
}

// NormalizeMAC rend la forme canonique — six octets, minuscules,
// deux-points — ou dit pourquoi l'entrée ne peut pas en être une.
//
// Deux refus qui ne sont pas des caprices. L'adresse nulle correspond à tout
// ce qui n'a pas d'adresse et n'identifie donc rien. Une adresse de diffusion
// ou de groupe — bit de poids faible du premier octet à 1 — ne peut JAMAIS
// apparaître comme adresse SOURCE : l'entrée serait morte à l'écriture, et
// une exception qui ne s'applique jamais est pire qu'absente, puisqu'on la
// croit posée.
func NormalizeMAC(s string) (string, error) {
	brut := strings.TrimSpace(s)
	if brut == "" {
		return "", fmt.Errorf("adresse MAC vide")
	}
	// Douze caractères hexadécimaux sans séparateur : la forme que rendent
	// plusieurs outils, que net.ParseMAC ne lit pas.
	if len(brut) == 12 && !strings.ContainsAny(brut, ":-.") {
		var parts []string
		for i := 0; i < 12; i += 2 {
			parts = append(parts, brut[i:i+2])
		}
		brut = strings.Join(parts, ":")
	}
	adr, err := net.ParseMAC(brut)
	if err != nil {
		return "", fmt.Errorf("adresse MAC illisible %q", s)
	}
	if len(adr) != 6 {
		return "", fmt.Errorf("adresse MAC de %d octets, six attendus", len(adr))
	}
	if adr[0]&1 == 1 {
		return "", fmt.Errorf(
			"%s est une adresse de groupe : jamais une adresse source", adr)
	}
	nulle := true
	for _, o := range adr {
		if o != 0 {
			nulle = false
			break
		}
	}
	if nulle {
		return "", fmt.Errorf("l'adresse nulle n'identifie aucune machine")
	}
	return strings.ToLower(adr.String()), nil
}

// BypassFile est la liste DURABLE. L'ensemble nftables vit dans le noyau et
// disparaît avec la table ; ce fichier est ce que le service relit à chaque
// démarrage pour reposer les mêmes exceptions.
type BypassFile struct {
	Path string
}

// Load rend les entrées, triées par MAC. Un fichier absent n'est pas une
// erreur : c'est l'état d'une installation où personne n'a rien excepté.
//
// Une ligne illisible est SAUTÉE et non fatale. Le fichier est éditable à la
// main, et refuser de démarrer le service pour une faute de frappe dans une
// exception coûterait plus que d'ignorer la ligne.
func (b BypassFile) Load() ([]BypassEntry, error) {
	fh, err := os.Open(b.Path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer fh.Close()

	vues := map[string]bool{}
	var out []BypassEntry
	sc := bufio.NewScanner(fh)
	for sc.Scan() {
		ligne := strings.TrimSpace(sc.Text())
		if i := strings.IndexByte(ligne, '#'); i >= 0 {
			ligne = strings.TrimSpace(ligne[:i])
		}
		if ligne == "" {
			continue
		}
		champs := strings.Fields(ligne)
		mac, err := NormalizeMAC(champs[0])
		if err != nil || vues[mac] {
			continue
		}
		vues[mac] = true
		nom := ""
		if len(champs) > 1 {
			nom = strings.Join(champs[1:], " ")
		}
		out = append(out, BypassEntry{MAC: mac, Name: nom})
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].MAC < out[j].MAC })
	return out, nil
}

// Save réécrit le fichier en entier, par un remplacement atomique : une
// écriture coupée en deux laisserait une liste tronquée que le prochain
// démarrage prendrait pour la vérité.
func (b BypassFile) Save(entries []BypassEntry) error {
	if err := os.MkdirAll(filepath.Dir(b.Path), 0o755); err != nil {
		return err
	}
	var sb strings.Builder
	sb.WriteString("# Exceptions du cache de téléchargement des VM QEMU.\n")
	sb.WriteString("# Une ligne « <MAC> <nom de la VM> » par machine que le\n")
	sb.WriteString("# détournement doit ignorer. Relu à chaque démarrage du\n")
	sb.WriteString("# service ; une MAC dont la VM n'existe plus est à retirer.\n")
	for _, e := range entries {
		if e.Name == "" {
			sb.WriteString(e.MAC + "\n")
			continue
		}
		fmt.Fprintf(&sb, "%s %s\n", e.MAC, e.Name)
	}
	tmp := b.Path + ".part"
	if err := os.WriteFile(tmp, []byte(sb.String()), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, b.Path)
}

// Add pose une exception et rend la MAC canonique. Reposer une MAC déjà
// présente met son nom à jour au lieu de créer un doublon : le déploiement
// est relancé, et deux lignes pour une machine rendraient le retrait
// incomplet.
func (b BypassFile) Add(mac, nom string) (string, error) {
	canon, err := NormalizeMAC(mac)
	if err != nil {
		return "", err
	}
	entries, err := b.Load()
	if err != nil {
		return "", err
	}
	remplacee := false
	for i := range entries {
		if entries[i].MAC == canon {
			entries[i].Name = nom
			remplacee = true
			break
		}
	}
	if !remplacee {
		entries = append(entries, BypassEntry{MAC: canon, Name: nom})
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].MAC < entries[j].MAC
		})
	}
	return canon, b.Save(entries)
}

// Del retire une exception. Rend faux si elle n'y était pas — retirer deux
// fois n'est pas une erreur, mais l'appelant doit pouvoir le dire.
func (b BypassFile) Del(mac string) (string, bool, error) {
	canon, err := NormalizeMAC(mac)
	if err != nil {
		return "", false, err
	}
	entries, err := b.Load()
	if err != nil {
		return "", false, err
	}
	var reste []BypassEntry
	trouvee := false
	for _, e := range entries {
		if e.MAC == canon {
			trouvee = true
			continue
		}
		reste = append(reste, e)
	}
	if !trouvee {
		return canon, false, nil
	}
	return canon, true, b.Save(reste)
}

// MACs rend les seules adresses, dans l'ordre du fichier.
func MACs(entries []BypassEntry) []string {
	out := make([]string, 0, len(entries))
	for _, e := range entries {
		out = append(out, e.MAC)
	}
	return out
}

// BypassAddElement et BypassDelElement rendent le geste À CHAUD, à passer à
// « nft -f - ». Modifier l'ensemble ne repose pas les règles : les
// téléchargements des autres VM ne sont pas coupés, ce qu'un redémarrage du
// service ferait.
//
// Comme le reste de ce paquet, ces lignes sont RENDUES et jamais exécutées :
// l'appelant les applique, et un test les vérifie sans toucher au pare-feu de
// la machine qui l'exécute.
func BypassAddElement(mac string) string {
	return fmt.Sprintf("add element ip %s %s { %s }",
		TableName, BypassSetName, mac)
}

func BypassDelElement(mac string) string {
	return fmt.Sprintf("delete element ip %s %s { %s }",
		TableName, BypassSetName, mac)
}
