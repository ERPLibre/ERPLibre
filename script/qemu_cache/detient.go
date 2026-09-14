// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"fmt"
	"io"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// « --detient » répond depuis le MAGASIN et non depuis le journal d'accès.
// Le journal dit qu'un objet est entré un jour ; un objet effacé depuis — par
// une purge, par âge ou en entier — y garde ses lignes « stored ». Seul le
// magasin sait ce qui sortira hors ligne.
//
// La lecture ne passe pas par Store.Get, qui remet la date du corps à
// maintenant : le relevé rajeunirait tout ce qu'il regarde, et l'âge du
// dernier usage ne voudrait plus rien dire. Elle ne lit que des métas (0644)
// et des casiers (0755) : aucun privilège n'est requis.

// Verdicts de « --detient ».
const (
	// VerdictGarde : un corps 200 est en réserve, il sortira hors ligne.
	VerdictGarde = "garde"
	// VerdictStatut : un statut seul — redirection, refus, 200 d'un HEAD —
	// est en réserve, rejoué sans corps quand l'amont est muet.
	VerdictStatut = "statut"
	// VerdictAbsent : la requête est cachable, rien n'est en réserve.
	VerdictAbsent = "absent"
	// VerdictNonCachable : le magasin ne tiendra jamais cette requête —
	// méthode d'écriture, négociation git, URL illisible, ou HEAD d'une
	// classe qui ne garde pas de statut seul.
	VerdictNonCachable = "non-cachable"
)

// Detention dit ce que le magasin tient pour une méthode et une URL.
type Detention struct {
	Verdict string
	// Statut et StockeLe sont nuls quand rien n'est en réserve.
	Statut   int
	StockeLe time.Time
	Classe   string
	Methode  string
	URL      string
}

// Ligne rend la détention en une ligne séparée par des tabulations :
// verdict, statut, date de stockage en RFC 3339, classe, méthode, URL. Un
// champ sans valeur vaut « - », pour que chaque ligne ait six champs.
func (d Detention) Ligne() string {
	statut, date, classe := "-", "-", "-"
	if d.Statut != 0 {
		statut = strconv.Itoa(d.Statut)
	}
	if !d.StockeLe.IsZero() {
		date = d.StockeLe.UTC().Format(time.RFC3339)
	}
	if d.Classe != "" {
		classe = d.Classe
	}
	return strings.Join(
		[]string{d.Verdict, statut, date, classe, d.Methode, d.URL}, "\t")
}

// Detenir dit ce que le magasin tient pour une requête, sans rien modifier.
//
// Les clés sont calculées comme le service les calcule — classe, méthode
// cachable, clé portable ou non —, par les mêmes fonctions, et lues dans le
// même ordre que la branche hors ligne : la clé du corps d'abord, qui ne
// compte que pour un 200 ; la clé du statut seul (CleStatut) ensuite. Un
// objet n'est tenu que si son corps a la taille que son méta annonce : c'est
// la condition à laquelle le service le sert, et un objet que le service
// refuserait n'est pas en réserve. L'URL est rendue telle que reçue, pour que
// l'appelant retrouve sa ligne.
//
// Un HEAD n'a jamais de corps gardé, et son statut ne se garde que pour une
// classe volatile sous une clé attachée à l'hôte : ailleurs, il est
// non-cachable et non absent, sans quoi l'appelant le croirait à remplir et
// le rejouerait pour rien, indéfiniment. C'est la négation exacte de la
// condition du statut seul dans Proxy.serve.
func (s *Store) Detenir(methode, brut string) Detention {
	methode = strings.ToUpper(methode)
	d := Detention{Verdict: VerdictNonCachable, Methode: methode, URL: brut}
	u, err := url.Parse(brut)
	if err != nil || !u.IsAbs() || u.Host == "" {
		return d
	}
	class := Classify(u)
	d.Classe = class.String()
	if !CacheableMethod(methode) || class == ClassNoStore {
		return d
	}
	if methode == "HEAD" && (class != ClassVolatile || PortableParChemin(u)) {
		return d
	}
	d.Verdict = VerdictAbsent
	if m, ok := s.lirePresent(CleDe(methode, u)); ok && !m.StatutSeul() {
		d.Verdict, d.Statut, d.StockeLe = VerdictGarde, m.StatutReel(), m.StoredAt
		return d
	}
	if m, ok := s.lirePresent(CleStatut(methode, u)); ok && m.StatutSeul() {
		d.Verdict, d.Statut, d.StockeLe = VerdictStatut, m.StatutReel(), m.StoredAt
	}
	return d
}

// lirePresent rend le méta d'une clé quand l'objet est complet : méta lisible
// et corps de la taille annoncée. Ni l'un ni l'autre n'est modifié.
func (s *Store) lirePresent(key string) (*Meta, bool) {
	m, err := s.LireMeta(key)
	if err != nil {
		return nil, false
	}
	_, bodyPath := s.paths(key)
	if fi, err := os.Stat(bodyPath); err != nil || fi.Size() != m.Size {
		return nil, false
	}
	return m, true
}

// EcrireDetentions lit des lignes « MÉTHODE URL » et écrit une ligne de
// détention pour chacune, dans l'ordre. Une ligne vide ou commençant par
// « # » est sautée ; une ligne d'un seul champ vaut « GET <champ> ». Chaque
// réponse part aussitôt écrite, pour qu'un appelant qui lit au fil de ses
// questions ne reste pas bloqué.
func EcrireDetentions(s *Store, entree io.Reader, sortie io.Writer) error {
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
		fmt.Fprintln(w, s.Detenir(methode, brut).Ligne())
		if err := w.Flush(); err != nil {
			return err
		}
	}
	return sc.Err()
}
