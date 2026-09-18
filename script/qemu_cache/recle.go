// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

// « --recle » range à nouveau les objets sous la clé que le service calcule
// AUJOURD'HUI.
//
// LE MANQUE QU'IL COMBLE. La clé d'un fichier portable a changé : seule la fin
// du chemin compte désormais (voir SegmentsDeCle), là où le chemin entier
// comptait. Les objets écrits sous l'ancienne règle restent sur le disque mais
// deviennent introuvables : le service les redemande à l'amont, et l'espace
// qu'ils occupent ne sert plus personne. La passe les range sous la clé
// courante, sans rien retélécharger.
//
// ELLE FOND AUSSI LES COPIES. Un même fichier vivait sous plusieurs chemins de
// miroir, donc sous plusieurs clés ; la clé courante les réunit, et deux
// objets tombent alors au même endroit. Le plus récemment rangé est gardé —
// les octets sont les mêmes, seule la date de service les sépare — et l'autre
// rend sa place.
//
// CE QU'ELLE NE TOUCHE PAS. Un statut seul est rangé sous CleStatut, qui hache
// l'URL ENTIÈRE : la règle du chemin ne l'atteint pas, et recalculer sa clé
// avec CleDe la déplacerait là où personne ne la lit.
//
// QUAND LA LANCER. Le service doit être arrêté : la passe renomme des fichiers
// qu'il sert, et un objet déplacé entre la lecture du méta et celle du corps
// ressort en défaut de cache. Rien n'est perdu dans ce cas, mais la mesure
// d'une campagne qui tournerait en même temps ne voudrait rien dire.

// Reclassement compte ce qu'une passe a fait.
type Reclassement struct {
	Lus        int
	Deplaces   int
	Fondus     int
	Inchanges  int
	Illisibles int
	Refus      int
	// OctetsRendus : ce que les copies fondues rendent au disque.
	OctetsRendus int64
}

// Ligne rend le compte en une ligne lisible.
func (r Reclassement) Ligne() string {
	return fmt.Sprintf(
		"lus %d, déplacés %d, fondus %d (%s rendus), inchangés %d,"+
			" illisibles %d, refus %d",
		r.Lus, r.Deplaces, r.Fondus, HumanBytes(r.OctetsRendus),
		r.Inchanges, r.Illisibles, r.Refus)
}

// Recler range chaque objet sous la clé courante. À blanc, rien n'est écrit et
// le compte dit ce qui bougerait.
func (s *Store) Recler(aBlanc bool) (Reclassement, error) {
	var r Reclassement
	// La liste est faite AVANT de renommer : déplacer un fichier sous un
	// répertoire que le parcours n'a pas encore visité le lui ferait
	// rencontrer deux fois.
	var metas []string
	err := filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil {
			return nil
		}
		if horsCasier(s.Dir, p, info) {
			return filepath.SkipDir
		}
		if !info.IsDir() && filepath.Ext(p) == ".meta" {
			metas = append(metas, p)
		}
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return r, err
	}

	for _, chemin := range metas {
		r.Lus++
		ancienne := strings.TrimSuffix(filepath.Base(chemin), ".meta")
		m, err := s.LireMeta(ancienne)
		if err != nil {
			r.Illisibles++
			continue
		}
		// Un statut seul vit sous une clé qui porte l'hôte : la règle du
		// chemin ne le concerne pas.
		if m.StatutSeul() {
			r.Inchanges++
			continue
		}
		u, err := url.Parse(m.URL)
		if err != nil || !u.IsAbs() || u.Host == "" {
			r.Illisibles++
			continue
		}
		nouvelle := CleDe(m.Method, u)
		if nouvelle == ancienne {
			r.Inchanges++
			continue
		}
		s.deplacer(&r, ancienne, nouvelle, m, aBlanc)
	}
	return r, nil
}

// deplacer range un objet sous sa nouvelle clé, ou le fond dans la copie qui
// s'y trouve déjà.
//
// Le CORPS part en premier et le méta ensuite : c'est l'ordre qui publie un
// objet, et l'interrompre laisse au pire un corps sans méta — que le magasin
// ignore — plutôt qu'un méta qui promet un corps absent.
func (s *Store) deplacer(
	r *Reclassement, ancienne, nouvelle string, m *Meta, aBlanc bool,
) {
	ancienMeta, ancienCorps := s.paths(ancienne)
	nouveauMeta, nouveauCorps := s.paths(nouvelle)

	if autre, err := s.LireMeta(nouvelle); err == nil {
		// Deux chemins de miroir pour le même fichier. Le plus récemment
		// rangé reste : les octets sont les mêmes, seule leur date diffère.
		garde, rendus := autre.StoredAt, m.Size
		if m.StoredAt.After(garde) {
			rendus = autre.Size
			if !aBlanc {
				if err := s.retirerPaire(nouveauMeta, nouveauCorps); err != nil {
					r.Refus++
					return
				}
				if err := s.renommerPaire(
					ancienMeta, ancienCorps, nouveauMeta, nouveauCorps,
				); err != nil {
					r.Refus++
					return
				}
			}
			r.Deplaces++
		} else if !aBlanc {
			if err := s.retirerPaire(ancienMeta, ancienCorps); err != nil {
				r.Refus++
				return
			}
		}
		r.Fondus++
		r.OctetsRendus += rendus
		return
	}

	if !aBlanc {
		if err := os.MkdirAll(filepath.Dir(nouveauMeta), 0o755); err != nil {
			r.Refus++
			return
		}
		if err := s.renommerPaire(
			ancienMeta, ancienCorps, nouveauMeta, nouveauCorps,
		); err != nil {
			r.Refus++
			return
		}
	}
	r.Deplaces++
}

func (s *Store) renommerPaire(ancienMeta, ancienCorps, nouveauMeta, nouveauCorps string) error {
	if err := os.Rename(ancienCorps, nouveauCorps); err != nil {
		return err
	}
	return os.Rename(ancienMeta, nouveauMeta)
}

func (s *Store) retirerPaire(meta, corps string) error {
	if err := os.Remove(corps); err != nil && !os.IsNotExist(err) {
		return err
	}
	if err := os.Remove(meta); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}
