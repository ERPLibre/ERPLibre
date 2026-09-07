// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Le cache ne diminue jamais de lui-même — c'est assumé, et la place se
// surveille à la main. Encore faut-il pouvoir la surveiller : savoir CE QUI
// occupe, et depuis QUAND, avant de décider ce qui peut partir.
//
// L'âge retenu est la date du dernier USAGE et non celle du stockage. Un
// paquet servi tous les jours depuis un an n'est pas vieux : le supprimer
// obligerait à le retélécharger le lendemain. C'est ce qu'un opérateur veut
// dire par « nettoyer ce qui ne sert plus », et c'est pour cela que le service
// remet la date d'un objet à chaque fois qu'il le sert.

// Tranche est un groupe d'objets d'un même âge.
type Tranche struct {
	// Debut est le premier instant de la tranche ; Libelle la nomme.
	Debut   time.Time
	Libelle string
	Objets  int
	Octets  int64
}

// Granularite dit comment les tranches sont découpées.
type Granularite string

const (
	ParJour    Granularite = "jour"
	ParSemaine Granularite = "semaine"
	ParMois    Granularite = "mois"
)

// LireGranularite tolère l'anglais comme le français : le CLI est bilingue
// partout ailleurs dans ce dépôt.
func LireGranularite(s string) (Granularite, error) {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "jour", "day", "j", "d":
		return ParJour, nil
	case "semaine", "week", "s", "w":
		return ParSemaine, nil
	case "mois", "month", "m":
		return ParMois, nil
	}
	return "", fmt.Errorf("granularité inconnue %q : jour, semaine ou mois", s)
}

// debutDeTranche ramène un instant au premier de sa tranche.
//
// La semaine commence le LUNDI : c'est la convention ISO, et celle que
// « %V » et les outils du système emploient. Ramener au dimanche donnerait des
// tranches qui ne correspondent à aucun autre relevé de la machine.
func debutDeTranche(t time.Time, g Granularite) time.Time {
	t = t.Local()
	jour := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location())
	switch g {
	case ParSemaine:
		recul := (int(jour.Weekday()) + 6) % 7
		return jour.AddDate(0, 0, -recul)
	case ParMois:
		return time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, t.Location())
	}
	return jour
}

func libelleDeTranche(t time.Time, g Granularite) string {
	switch g {
	case ParSemaine:
		an, sem := t.ISOWeek()
		return fmt.Sprintf("%d-S%02d", an, sem)
	case ParMois:
		return t.Format("2006-01")
	}
	return t.Format("2006-01-02")
}

// TranchesStore groupe les objets du magasin par âge, du plus récent au plus
// ancien.
func (s *Store) Tranches(g Granularite) []Tranche {
	par := map[time.Time]*Tranche{}
	filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil {
			return nil
		}
		if horsCasier(s.Dir, p, info) {
			return filepath.SkipDir
		}
		if info.IsDir() || filepath.Ext(p) != ".body" {
			return nil
		}
		d := debutDeTranche(info.ModTime(), g)
		tr, ok := par[d]
		if !ok {
			tr = &Tranche{Debut: d, Libelle: libelleDeTranche(d, g)}
			par[d] = tr
		}
		tr.Objets++
		tr.Octets += info.Size()
		return nil
	})
	return trier(par)
}

// TranchesMiroirs fait de même pour les dépôts git.
//
// Un dépôt entier par tranche, pas ses fichiers : ce qui s'efface est un
// dépôt, et le compter au fichier donnerait un relevé qu'on ne peut pas
// suivre d'un geste.
func (g *GitMirror) Tranches(gran Granularite) []Tranche {
	if g == nil || g.Dir == "" {
		return nil
	}
	par := map[time.Time]*Tranche{}
	for _, d := range g.Depots() {
		debut := debutDeTranche(d.Maj, gran)
		tr, ok := par[debut]
		if !ok {
			tr = &Tranche{Debut: debut, Libelle: libelleDeTranche(debut, gran)}
			par[debut] = tr
		}
		tr.Objets++
		tr.Octets += d.Octets
	}
	return trier(par)
}

func trier(par map[time.Time]*Tranche) []Tranche {
	out := make([]Tranche, 0, len(par))
	for _, tr := range par {
		out = append(out, *tr)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].Debut.After(out[j].Debut)
	})
	return out
}

// Purger efface les objets dont le dernier usage précède `avant`.
//
// Le méta part AVEC le corps : un méta orphelin ferait croire à une copie
// présente, et la lecture échouerait au moment de servir, c'est-à-dire au pire
// moment. Rend (objets effacés, octets rendus).
func (s *Store) Purger(avant time.Time) (int, int64, error) {
	n, octets := 0, int64(0)
	err := filepath.Walk(s.Dir, func(
		p string, info os.FileInfo, err error,
	) error {
		if err != nil || info == nil {
			return nil
		}
		if horsCasier(s.Dir, p, info) {
			return filepath.SkipDir
		}
		if info.IsDir() || filepath.Ext(p) != ".body" {
			return nil
		}
		if !info.ModTime().Before(avant) {
			return nil
		}
		taille := info.Size()
		if e := os.Remove(p); e != nil {
			return nil
		}
		os.Remove(strings.TrimSuffix(p, ".body") + ".meta")
		n++
		octets += taille
		return nil
	})
	return n, octets, err
}

// PurgerMiroirs efface les dépôts qui n'ont pas été rafraîchis depuis
// `avant`. Rend (dépôts effacés, octets rendus).
func (g *GitMirror) PurgerMiroirs(avant time.Time) (int, int64, error) {
	if g == nil || g.Dir == "" {
		return 0, 0, nil
	}
	n, octets := 0, int64(0)
	for _, d := range g.Depots() {
		if !d.Maj.Before(avant) {
			continue
		}
		if err := g.Retirer(d.Chemin); err != nil {
			return n, octets, err
		}
		n++
		octets += d.Octets
	}
	return n, octets, nil
}

// LireDuree accepte les suffixes de Go et, en plus, « j » pour un jour.
//
// « 30d » n'existe pas dans la bibliothèque, et un opérateur qui nettoie
// raisonne en jours, pas en sept cent vingt heures.
func LireDuree(s string) (time.Duration, error) {
	s = strings.ToLower(strings.TrimSpace(s))
	if s == "" {
		return 0, fmt.Errorf("durée vide")
	}
	if n, unite := s[:len(s)-1], s[len(s)-1]; unite == 'j' || unite == 'd' {
		var jours float64
		if _, err := fmt.Sscanf(n, "%g", &jours); err != nil || jours < 0 {
			return 0, fmt.Errorf("durée illisible %q", s)
		}
		return time.Duration(jours * 24 * float64(time.Hour)), nil
	}
	d, err := time.ParseDuration(s)
	if err != nil || d < 0 {
		return 0, fmt.Errorf(
			"durée illisible %q : essayer 30j, 12h, 90m", s)
	}
	return d, nil
}

// printAge écrit le relevé par âge : les objets, puis les dépôts.
//
// Les deux SÉPARÉMENT : ils ne s'effacent pas de la même façon — un objet est
// un fichier, un dépôt est un arbre — et un total commun cacherait qu'un seul
// dépôt pèse plus que mille objets.
func printAge(store *Store, miroir *GitMirror, gran Granularite) {
	fmt.Printf("Âge du dernier usage, par %s.\n", gran)
	fmt.Printf(
		"\nUn objet servi voit sa date remise à jour : « vieux » veut donc " +
			"dire\n« n'a plus servi », et non « est entré il y a " +
			"longtemps ».\n")

	ecrire := func(titre string, tranches []Tranche, quoi string) {
		fmt.Printf("\n%s\n", titre)
		if len(tranches) == 0 {
			fmt.Println("  rien")
			return
		}
		var n int
		var octets int64
		for _, tr := range tranches {
			fmt.Printf("  %-12s %6d %-8s %10s\n",
				tr.Libelle, tr.Objets, quoi, HumanBytes(tr.Octets))
			n += tr.Objets
			octets += tr.Octets
		}
		fmt.Printf("  %-12s %6d %-8s %10s\n", "total", n, quoi,
			HumanBytes(octets))
	}
	ecrire("Objets du cache :", store.Tranches(gran), "objets")
	if miroir.Actif() {
		ecrire("Dépôts en miroir :", miroir.Tranches(gran), "dépôts")
	}
}

// printPurgeABlanc dit ce qu'une purge emporterait, sans rien effacer.
//
// Une purge ne se rattrape pas — les octets sont rendus, il faut les
// retélécharger — et c'est le genre de geste qu'on veut relire avant.
func printPurgeABlanc(store *Store, miroir *GitMirror, avant time.Time) {
	var n int
	var octets int64
	for _, tr := range store.Tranches(ParJour) {
		if tr.Debut.Before(avant) {
			n += tr.Objets
			octets += tr.Octets
		}
	}
	fmt.Printf("[à blanc] objets qui partiraient : %d, %s\n",
		n, HumanBytes(octets))

	var nd int
	var octd int64
	for _, d := range miroir.Depots() {
		if d.Maj.Before(avant) {
			nd++
			octd += d.Octets
		}
	}
	fmt.Printf("[à blanc] dépôts qui partiraient : %d, %s\n",
		nd, HumanBytes(octd))
	fmt.Println("[à blanc] rien n'a été effacé.")
}
