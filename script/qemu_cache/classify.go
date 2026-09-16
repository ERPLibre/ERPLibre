// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/url"
	"path"
	"regexp"
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
	// métadonnées d'une distribution Python servies à part (PEP 658) : le nom
	// est celui de l'archive suivi de « .metadata », sous le même chemin
	// d'empreinte. Sans ces suffixes, « .metadata » ne correspond à rien et le
	// fichier tombe dans le volatil par défaut, repris à chaque installation.
	".whl.metadata", ".tar.gz.metadata", ".zip.metadata",
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

// parEmpreinte reconnaît un index Debian publié sous l'empreinte de son
// contenu : « …/by-hash/SHA256/<hexadécimal> ». Le nom EST la somme du
// contenu, si bien qu'un contenu différent porte un autre nom : le fichier est
// aussi figé qu'un paquet, quoiqu'il n'ait aucune extension.
//
// Il se range SANS son hôte, et c'est ce qui le distingue d'un index nommé
// par sa suite : deux miroirs qui servent ce chemin servent le même octet,
// ou l'un des deux est corrompu et son client le rejette sur la somme. Le
// raisonnement inverse — « le même chemin ne vaut que si le miroir publie la
// même suite » — vaut pour « Packages », dont le contenu varie d'un miroir à
// l'autre sous un nom identique ; il ne vaut pas pour un nom qui EST la somme
// de son contenu, et l'appliquer ici vide le cache de ses index dès qu'une
// liste de miroirs tourne.
var parEmpreinte = regexp.MustCompile(
	`/by-hash/(MD5Sum|SHA1|SHA256|SHA512)/[0-9a-fA-F]{32,128}$`)

// parEmpreinteDeDepot reconnaît une métadonnée de dépôt RPM nommée par
// l'empreinte de son contenu : « …/repodata/<hexadécimal>-primary.xml.zck ».
// Seul « repomd.xml » y est volatile : il désigne la version COURANTE de
// chaque métadonnée par ce nom, si bien qu'un contenu nouveau porte un nom
// nouveau. Le fichier nommé est aussi figé qu'un paquet.
//
// Volatile, il est repris en entier à chaque installation — un « primary »
// pèse des dizaines de mégaoctets par dépôt. Et dnf télécharge un « .zck » par
// plages, qu'aucun volatile ne garde : amont coupé, la VM suivante n'avait
// rien. Figé, il sort du disque, et une plage y déclenche la prise du fichier
// entier (voir completer).
var parEmpreinteDeDepot = regexp.MustCompile(
	`/repodata/[0-9a-fA-F]{32,128}-[^/]+$`)

// dernierePublication reconnaît « /<propriétaire>/<dépôt>/releases/latest/
// download/<fichier> » : un POINTEUR vers la dernière version publiée, dont
// la cible change à chaque publication.
//
// Son suffixe — « .tar.gz », « .zip » — le ferait passer pour figé : servi du
// disque sans jamais redemander, il resterait à la première version vue, et
// rangé sans son hôte il répondrait pour n'importe quelle forge. Il est donc
// volatile et attaché à son hôte, et la règle passe AVANT les suffixes.
var dernierePublication = regexp.MustCompile(
	`^/[^/]+/[^/]+/releases/latest/download/[^/]+$`)

// Chemins du protocole « smart HTTP » de git. Ce sont des points de
// NÉGOCIATION : le serveur calcule sa réponse en fonction de ce que le client
// détient déjà. Rien n'y est réutilisable d'une requête à l'autre, et servir
// une réponse gardée y ferait croire à des références qui n'existent plus.
//
// Les fichiers du protocole « dumb », eux, restent cachables : un objet
// « .../objects/ab/cdef… » porte son empreinte dans son nom.
var gitSmartPaths = []string{
	"/info/refs", "/git-upload-pack", "/git-receive-pack",
}

// EstGitSmart dit si l'URL vise l'un de ces points de négociation.
//
// Sert deux fois. Le contenu n'est ni gardé ni servi du cache. Et l'amont y a
// droit à BEAUCOUP plus de patience : un serveur git énumère ses références à
// la demande, ce qui prend des dizaines de secondes sur un dépôt chargé, là où
// un miroir de paquets répond en quelques centaines de millisecondes.
func EstGitSmart(u *url.URL) bool {
	if u == nil {
		return false
	}
	for _, s := range gitSmartPaths {
		if strings.HasSuffix(u.Path, s) {
			return true
		}
	}
	return false
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
	if EstGitSmart(u) {
		return ClassNoStore
	}
	name := strings.ToLower(path.Base(u.Path))

	// Une requête portant une chaîne de requête décrit un appel d'API et non
	// un fichier : deux paramètres différents rendent deux réponses, et son
	// nom de fichier ne dit rien de son contenu.
	if u.RawQuery != "" {
		return ClassVolatile
	}
	// Les deux règles de CHEMIN l'emportent sur celles du nom : l'une porte un
	// suffixe figé qui ment, l'autre n'en porte aucun et dit pourtant vrai.
	if dernierePublication.MatchString(u.Path) {
		return ClassVolatile
	}
	if parEmpreinte.MatchString(u.Path) || parEmpreinteDeDepot.MatchString(u.Path) {
		return ClassImmutable
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

// PortableParChemin dit si le NOM du fichier suffit à l'identifier sur
// n'importe quel miroir de la même distribution.
//
// Vrai pour un paquet — sa version et son architecture sont dans son nom — et
// pour un index de dépôt, dont le chemin est le même partout. Faux pour le
// reste : « /index.html » n'identifie rien.
func PortableParChemin(u *url.URL) bool {
	if u == nil || u.RawQuery != "" {
		return false
	}
	if dernierePublication.MatchString(u.Path) {
		return false
	}
	// Un objet adressé par son empreinte se range sans son hôte. La règle est
	// POSITIVE parce qu'aucune des tables suivantes ne le reconnaîtrait : une
	// somme hexadécimale n'a pas d'extension, et retirer la seule exclusion ne
	// suffirait donc pas à le rendre portable.
	if parEmpreinte.MatchString(u.Path) || parEmpreinteDeDepot.MatchString(u.Path) {
		return true
	}
	name := strings.ToLower(path.Base(u.Path))
	for _, s := range immutableSuffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	for _, s := range volatileSuffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	for _, n := range volatileNames {
		// « index.html » et « index.json » nomment n'importe quoi : ils sont
		// dans la table des index, mais pas portables pour autant.
		if name == n && !strings.HasPrefix(n, "index.") {
			return true
		}
	}
	return false
}

// CacheableMethod : seules les lectures entrent au cache. Un POST ou un PUT
// change un état à l'amont et n'a pas de copie qui vaille.
func CacheableMethod(method string) bool {
	return method == "GET" || method == "HEAD"
}
