// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
)

// « --oublie » efface du magasin ce qu'une méthode et une URL désignent.
//
// LE MANQUE QU'IL COMBLE. Rien n'invalide une entrée quand la somme d'un
// fichier servi ne correspond pas : le magasin continue de le rendre, et
// retélécharger ne change rien puisque c'est lui qui répond. Les deux purges
// existantes ne l'atteignent pas — « --purge » efface TOUT, et
// « --purge-older-than » saute ce dont la date est récente, or Store.Get remet
// cette date à maintenant à CHAQUE service. Un objet empoisonné qui continue
// d'être servi rajeunit donc à chaque VM et ne vieillit jamais : aucun délai
// ne le rattrape.
//
// SYMÉTRIQUE DE « --detient », et c'est ce qui le rend sûr : mêmes lignes en
// entrée, mêmes fonctions de classement et de clé, mêmes verdicts de refus.
// Ce que l'un dit « garde », l'autre l'efface ; ce que l'un dit
// « non-cachable », l'autre n'a rien à effacer. Deux calculs de clé finiraient
// par diverger, et l'on croirait avoir effacé ce que le service sert encore.
//
// ÉCRITURE : le service écrit ses objets en root, et les effacer demande le
// même droit. Un refus est DIT plutôt que compté comme un succès — croire un
// magasin nettoyé qui ne l'est pas est la seule issue vraiment mauvaise.

// Verdicts de « --oublie ».
const (
	// OubliEfface : le magasin tenait quelque chose, il ne l'a plus.
	OubliEfface = "oublié"
	// OubliAbsent : la requête est cachable, le magasin ne tenait rien.
	OubliAbsent = "absent"
	// OubliNonCachable : le magasin ne tiendra jamais cette requête, il n'y
	// a donc rien à y effacer.
	OubliNonCachable = "non-cachable"
	// OubliRefus : un objet était là et n'a pas pu être retiré — droits,
	// système de fichiers en lecture seule. Surtout pas « oublié ».
	OubliRefus = "refus"
)

// Oubli dit ce que le magasin a cessé de tenir pour une méthode et une URL.
type Oubli struct {
	Verdict string
	// Octets rendus au disque. Nul quand rien n'a été effacé.
	Octets  int64
	Classe  string
	Methode string
	URL     string
}

// Ligne rend l'oubli en une ligne séparée par des tabulations : verdict,
// octets, classe, méthode, URL. Un champ sans valeur vaut « - », pour que
// chaque ligne ait cinq champs.
func (o Oubli) Ligne() string {
	octets, classe := "-", "-"
	if o.Octets != 0 {
		octets = fmt.Sprintf("%d", o.Octets)
	}
	if o.Classe != "" {
		classe = o.Classe
	}
	return strings.Join(
		[]string{o.Verdict, octets, classe, o.Methode, o.URL}, "\t")
}

// Oublier efface du magasin ce que la requête désigne, et dit ce qu'il en est.
//
// LES DEUX CLÉS, toujours : le corps (CleDe) et le statut seul (CleStatut)
// vivent dans des espaces séparés, et n'en effacer qu'une laisserait le rejeu
// resservir une redirection vers l'octet qu'on vient de retirer.
//
// Le méta part AVEC le corps, comme dans Purger : un méta orphelin ferait
// croire à une copie présente, et la lecture échouerait au moment de servir.
func (s *Store) Oublier(methode, brut string) Oubli {
	methode = strings.ToUpper(methode)
	o := Oubli{Verdict: OubliNonCachable, Methode: methode, URL: brut}
	u, err := url.Parse(brut)
	if err != nil || !u.IsAbs() || u.Host == "" {
		return o
	}
	class := Classify(u)
	o.Classe = class.String()
	if !CacheableMethod(methode) || class == ClassNoStore {
		return o
	}
	if methode == "HEAD" && (class != ClassVolatile || PortableParChemin(u)) {
		return o
	}
	o.Verdict = OubliAbsent
	for _, key := range []string{
		CleDe(methode, u), CleStatut(methode, u),
	} {
		octets, etat := s.effacer(key)
		o.Octets += octets
		switch etat {
		case OubliRefus:
			o.Verdict = OubliRefus
		case OubliEfface:
			if o.Verdict != OubliRefus {
				o.Verdict = OubliEfface
			}
		}
	}
	return o
}

// effacer retire le corps et le méta d'une clé. Rend (octets rendus, verdict
// de cette clé seule).
//
// Un fichier absent n'est pas une erreur : une clé sans objet est le cas
// ordinaire, et deux clés sont essayées pour chaque requête. Un fichier
// PRÉSENT qui résiste en est une, et elle remonte.
func (s *Store) effacer(key string) (int64, string) {
	metaPath, bodyPath := s.paths(key)
	octets := int64(0)
	etat := OubliAbsent
	if fi, err := os.Stat(bodyPath); err == nil {
		if e := os.Remove(bodyPath); e != nil {
			return 0, OubliRefus
		}
		octets = fi.Size()
		etat = OubliEfface
	}
	if _, err := os.Stat(metaPath); err == nil {
		if e := os.Remove(metaPath); e != nil {
			return octets, OubliRefus
		}
		etat = OubliEfface
	}
	return octets, etat
}

// EcrireOublis lit des lignes « MÉTHODE URL » et écrit une ligne d'oubli pour
// chacune, dans l'ordre. Une ligne vide ou commençant par « # » est sautée ;
// une ligne d'un seul champ vaut « GET <champ> ». Chaque réponse part aussitôt
// écrite, comme pour « --detient ».
func EcrireOublis(s *Store, entree io.Reader, sortie io.Writer) error {
	sc := bufio.NewScanner(entree)
	// Une URL signée dépasse volontiers les 64 Kio de la ligne par défaut.
	sc.Buffer(make([]byte, 64*1024), 1<<20)
	w := bufio.NewWriter(sortie)
	for sc.Scan() {
		ligne := strings.TrimSpace(sc.Text())
		if ligne == "" || strings.HasPrefix(ligne, "#") {
			continue
		}
		champs := strings.Fields(ligne)
		methode, brut := "GET", champs[0]
		if len(champs) >= 2 {
			methode, brut = champs[0], champs[1]
		}
		fmt.Fprintln(w, s.Oublier(methode, brut).Ligne())
		if err := w.Flush(); err != nil {
			return err
		}
	}
	return sc.Err()
}
