// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// LireTaille lit une taille : un nombre, suivi ou non d'une unité binaire.
//
// « 50G », « 50Gio », « 50GiB », « 1.5 G », « 500M », « 2T » ou un nombre
// d'octets. Les unités valent des puissances de 1024 : c'est ce qu'affiche
// HumanBytes, et un plafond lu autrement que la taille affichée ne se
// comparerait pas à elle.
func LireTaille(s string) (int64, error) {
	brut := strings.TrimSpace(s)
	if brut == "" {
		return 0, fmt.Errorf("%s", T("taille vide"))
	}
	t := strings.ToUpper(strings.ReplaceAll(brut, " ", ""))
	for _, suffixe := range []string{"IB", "IO", "B", "O"} {
		if strings.HasSuffix(t, suffixe) && len(t) > len(suffixe) {
			t = strings.TrimSuffix(t, suffixe)
			break
		}
	}
	facteur := int64(1)
	if n := len(t); n > 0 {
		switch t[n-1] {
		case 'K':
			facteur = 1 << 10
		case 'M':
			facteur = 1 << 20
		case 'G':
			facteur = 1 << 30
		case 'T':
			facteur = 1 << 40
		}
		if facteur > 1 {
			t = t[:n-1]
		}
	}
	v, err := strconv.ParseFloat(t, 64)
	if err != nil || v <= 0 {
		return 0, fmt.Errorf(T("taille illisible %q : essayer 50G, 500M, 2T"), brut)
	}
	return int64(v * float64(facteur)), nil
}

// BilanPlafond dit ce qu'une purge au plafond a effacé, ou effacerait.
type BilanPlafond struct {
	Objets       int
	OctetsObjets int64
	Depots       int
	OctetsDepots int64
	Avant        int64
	Apres        int64
}

// candidat est un objet du magasin ou un dépôt en miroir, avec son dernier
// usage : ce qui décide de l'ordre d'éviction.
type candidat struct {
	chemin string
	octets int64
	usage  time.Time
	depot  bool
}

// PurgerJusqua efface le moins récemment servi, objets et dépôts confondus,
// jusqu'à ce que l'ensemble tienne sous le plafond. aBlanc compte sans rien
// effacer.
//
// Confondus, parce que le plafond porte sur le disque et que les deux s'y
// disputent la place : un dépôt oublié depuis des mois pèse plus que mille
// paquets servis récemment. L'usage d'un objet est la date de son corps, remise à
// jour à chaque service ; celle d'un dépôt, son dernier rafraîchissement.
// Rien ne part quand le cache tient déjà sous le plafond.
func PurgerJusqua(store *Store, miroir *GitMirror, plafond int64, aBlanc bool) (BilanPlafond, error) {
	var b BilanPlafond
	var tous []candidat
	if store != nil && store.Dir != "" {
		filepath.Walk(store.Dir, func(p string, info os.FileInfo, err error) error {
			if err != nil || info == nil {
				return nil
			}
			if horsCasier(store.Dir, p, info) {
				return filepath.SkipDir
			}
			if info.IsDir() || filepath.Ext(p) != ".body" {
				return nil
			}
			tous = append(tous, candidat{p, info.Size(), info.ModTime(), false})
			return nil
		})
	}
	for _, d := range miroir.Depots() {
		tous = append(tous, candidat{d.Chemin, d.Octets, d.Maj, true})
	}
	for _, c := range tous {
		b.Avant += c.octets
	}
	b.Apres = b.Avant
	if b.Avant <= plafond {
		return b, nil
	}
	sort.SliceStable(tous, func(i, j int) bool { return tous[i].usage.Before(tous[j].usage) })
	for _, c := range tous {
		if b.Apres <= plafond {
			break
		}
		if !aBlanc {
			if c.depot {
				if err := miroir.Retirer(c.chemin); err != nil {
					return b, err
				}
			} else {
				if err := os.Remove(c.chemin); err != nil {
					continue
				}
				// Le méta part AVEC le corps : orphelin, il ferait croire à
				// une copie présente.
				os.Remove(strings.TrimSuffix(c.chemin, ".body") + ".meta")
			}
		}
		b.Apres -= c.octets
		if c.depot {
			b.Depots++
			b.OctetsDepots += c.octets
		} else {
			b.Objets++
			b.OctetsObjets += c.octets
		}
	}
	return b, nil
}
