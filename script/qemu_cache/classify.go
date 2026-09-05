// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/url"
	"path"
	"strings"
)

// Class dit ce que le cache a le droit de faire d'une réponse.
//
// La distinction porte tout l'outil. Un fichier de paquet est IMMUABLE :
// son nom porte sa version, son contenu ne change jamais, et le servir du
// disque est exactement le gain cherché. Un index de dépôt est VOLATILE :
// il nomme les versions qui existent en ce moment, et servir un index périmé
// fait échouer l'installation sur un fichier retiré des miroirs — « failed
// retrieving file … 404 », le mode de défaillance que la préparation d'un
// invité Arch documente déjà.
//
// D'où la règle : seul l'immuable est servi du cache tant que l'amont répond.
// Le volatile est STOCKÉ quand même, et ne ressort que si l'amont est
// injoignable, ce qui rend le déploiement hors ligne possible sans jamais
// ouvrir de fenêtre de péremption quand le réseau est là.
type Class int

const (
	// ClassImmutable : servi du disque dès qu'il y est.
	ClassImmutable Class = iota
	// ClassVolatile : toujours pris à l'amont, stocké, servi hors ligne seul.
	ClassVolatile
	// ClassNoStore : ni servi ni stocké.
	ClassNoStore
)

func (c Class) String() string {
	switch c {
	case ClassImmutable:
		return "immutable"
	case ClassVolatile:
		return "volatile"
	default:
		return "no-store"
	}
}

// Suffixes d'un fichier dont le nom porte sa version. L'ordre n'importe pas ;
// le premier qui correspond gagne.
var immutableSuffixes = []string{
	// paquets de distribution
	".pkg.tar.zst", ".pkg.tar.xz", ".deb", ".rpm", ".apk",
	// signatures détachées, aussi figées que ce qu'elles signent
	".pkg.tar.zst.sig", ".pkg.tar.xz.sig",
	// écosystèmes Python et Node
	".whl", ".tgz",
	// images et supports d'installation
	".qcow2", ".iso", ".img", ".raw", ".vmdk",
	// archives amont
	".tar.gz", ".tar.xz", ".tar.bz2", ".tar.zst", ".zip",
}

// Noms et suffixes d'un index de dépôt. Un « .db » d'Arch, un « InRelease »
// de Debian et un « repomd.xml » de Fedora décrivent tous l'état COURANT du
// miroir.
var volatileNames = []string{
	"inrelease", "release", "release.gpg",
	"packages", "packages.gz", "packages.xz", "packages.bz2",
	"sources", "sources.gz", "sources.xz",
	"repomd.xml", "repomd.xml.asc", "repomd.xml.key",
	"index.json", "index.html",
}

var volatileSuffixes = []string{
	".db", ".db.sig", ".db.tar.gz", ".files", ".files.tar.gz",
	".xml.gz", ".xml.zck", ".sqlite.bz2", ".sqlite.gz",
}

// Classify tranche pour une URL, sans regarder la réponse : la décision doit
// être prise AVANT d'interroger l'amont, puisqu'elle décide s'il faut
// l'interroger.
//
// Le doute profite au volatile. Une URL inconnue est donc toujours reprise à
// l'amont quand il répond, et ne sert de copie que hors ligne : le pire cas
// est une requête inutile, jamais une réponse fausse.
func Classify(u *url.URL) Class {
	if u == nil {
		return ClassNoStore
	}
	name := strings.ToLower(path.Base(u.Path))

	// Une requête portant une chaîne de requête décrit un appel d'API et non
	// un fichier : deux paramètres différents rendent deux réponses, et son
	// nom de fichier ne dit rien de son contenu.
	if u.RawQuery != "" {
		return ClassVolatile
	}
	for _, n := range volatileNames {
		if name == n {
			return ClassVolatile
		}
	}
	for _, s := range volatileSuffixes {
		if strings.HasSuffix(name, s) {
			return ClassVolatile
		}
	}
	// L'index « simple » de PyPI est une page sans extension sous /simple/.
	if strings.Contains(u.Path, "/simple/") {
		return ClassVolatile
	}
	for _, s := range immutableSuffixes {
		if strings.HasSuffix(name, s) {
			return ClassImmutable
		}
	}
	return ClassVolatile
}

// CacheableMethod : seules les lectures entrent au cache. Un POST ou un PUT
// change un état à l'amont et n'a pas de copie qui vaille.
func CacheableMethod(method string) bool {
	return method == "GET" || method == "HEAD"
}
