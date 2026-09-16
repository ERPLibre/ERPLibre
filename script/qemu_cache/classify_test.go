// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/url"
	"strings"
	"testing"
)

func TestClassify(t *testing.T) {
	cas := []struct {
		brut     string
		attendue Class
		pourquoi string
	}{
		// Le nom porte la version : le contenu ne changera jamais.
		{"https://miroir.example/arch/core/os/x86_64/bash-5.2-1-x86_64.pkg.tar.zst",
			ClassImmutable, "paquet Arch"},
		{"https://miroir.example/debian/pool/main/b/bash/bash_5.2-1_amd64.deb",
			ClassImmutable, "paquet Debian"},
		{"https://miroir.example/fedora/Packages/b/bash-5.2-1.fc43.x86_64.rpm",
			ClassImmutable, "paquet Fedora"},
		{"https://pypi.example/packages/ab/cd/requests-2.33.0-py3-none-any.whl",
			ClassImmutable, "roue Python"},
		{"https://pypi.example/packages/ab/cd/requests-2.33.0-py3-none-any.whl.metadata",
			ClassImmutable, "métadonnées d'une roue (PEP 658)"},
		{"https://pypi.example/packages/ab/cd/requests-2.33.0.tar.gz.metadata",
			ClassImmutable, "métadonnées d'une archive source (PEP 658)"},
		{"https://images.example/arch/Arch-Linux-x86_64-cloudimg.qcow2",
			ClassImmutable, "image cloud"},

		// L'index décrit l'état COURANT du miroir.
		{"https://miroir.example/arch/core/os/x86_64/core.db",
			ClassVolatile, "base Arch"},
		{"https://miroir.example/arch/core/os/x86_64/core.db.sig",
			ClassVolatile, "signature de la base"},
		{"https://miroir.example/debian/dists/trixie/InRelease",
			ClassVolatile, "index Debian"},
		{"https://miroir.example/debian/dists/trixie/main/binary-amd64/Packages.gz",
			ClassVolatile, "liste Debian"},
		{"https://miroir.example/fedora/repodata/repomd.xml",
			ClassVolatile, "index Fedora"},
		{"https://pypi.example/simple/requests/",
			ClassVolatile, "index simple de PyPI"},

		// Le doute profite au volatile : une requête paramétrée décrit un
		// appel d'API, pas un fichier.
		{"https://api.example/v1/paquet?nom=bash&version=5.2",
			ClassVolatile, "chaîne de requête"},
		{"https://exemple.example/page-quelconque",
			ClassVolatile, "inconnu"},
	}

	for _, c := range cas {
		u, err := url.Parse(c.brut)
		if err != nil {
			t.Fatalf("URL de test invalide %q : %v", c.brut, err)
		}
		if got := Classify(u); got != c.attendue {
			t.Errorf("%s : %s classé « %s », attendu « %s »",
				c.pourquoi, c.brut, got, c.attendue)
		}
	}
}

// Une extension immuable portée par une chaîne de requête ne suffit pas : le
// paramètre peut changer la réponse.
func TestChaineDeRequeteEmportreSurExtension(t *testing.T) {
	u, _ := url.Parse("https://m.example/bash-5.2-1-x86_64.pkg.tar.zst?mirror=2")
	if got := Classify(u); got != ClassVolatile {
		t.Errorf("classé « %s », attendu « volatile »", got)
	}
}

func TestCacheableMethod(t *testing.T) {
	for _, m := range []string{"GET", "HEAD"} {
		if !CacheableMethod(m) {
			t.Errorf("%s devrait être cachable", m)
		}
	}
	for _, m := range []string{"POST", "PUT", "DELETE", "PATCH", "CONNECT"} {
		if CacheableMethod(m) {
			t.Errorf("%s ne doit pas être cachable", m)
		}
	}
}

func TestClassifyURLNulle(t *testing.T) {
	if got := Classify(nil); got != ClassNoStore {
		t.Errorf("une URL absente vaut « %s », attendu « no-store »", got)
	}
}

// Un même fichier, deux miroirs : le cache doit le reconnaître.
//
// Une liste de miroirs tourne, et pacman a réellement tiré « extra.db » de
// « geo » alors que le cache ne détenait que la copie de « fastly » — même
// fichier, autre nom d'hôte, défaut de cache et 504 hors ligne.
func TestMemeCheminSurDeuxMiroirs(t *testing.T) {
	a, _ := url.Parse("https://fastly.example/core/os/x86_64/bash-5.3-1-x86_64.pkg.tar.zst")
	b, _ := url.Parse("https://geo.example/core/os/x86_64/bash-5.3-1-x86_64.pkg.tar.zst")
	if !PortableParChemin(a) {
		t.Fatal("un paquet n'est pas reconnu portable")
	}
	if KeySansHote("GET", a) != KeySansHote("GET", b) {
		t.Error("deux miroirs du même fichier donnent deux clés")
	}
	if Key("GET", a.String()) == Key("GET", b.String()) {
		t.Error("la clé complète devrait, elle, distinguer les deux URL")
	}
}

// L'index aussi : c'est lui qui a échoué hors ligne.
func TestIndexPortableEntreMiroirs(t *testing.T) {
	a, _ := url.Parse("https://fastly.example/extra/os/x86_64/extra.db")
	b, _ := url.Parse("https://geo.example/extra/os/x86_64/extra.db")
	if !PortableParChemin(a) {
		t.Fatal("un index de dépôt n'est pas reconnu portable")
	}
	if KeySansHote("GET", a) != KeySansHote("GET", b) {
		t.Error("deux miroirs du même index donnent deux clés")
	}
}

// Mais pas n'importe quoi : « /index.html » ne nomme rien, et deux sites sans
// rapport en portent un.
func TestUnePageQuelconqueNestPasPortable(t *testing.T) {
	for _, brut := range []string{
		"https://a.example/index.html",
		"https://a.example/quelque-chose",
		"https://a.example/simple/requests/",
		"https://a.example/core.db?miroir=2",
	} {
		u, _ := url.Parse(brut)
		if PortableParChemin(u) {
			t.Errorf("%s est jugé portable, à tort", brut)
		}
	}
}

// Le protocole « smart » de git est une NÉGOCIATION : le serveur calcule sa
// réponse d'après ce que le client détient déjà. Rien n'y est réutilisable, et
// servir une réponse gardée ferait croire à des références disparues.
func TestGitSmartNestJamaisGarde(t *testing.T) {
	for _, brut := range []string{
		"https://git.example/org/depot.git/info/refs?service=git-upload-pack",
		"https://git.example/org/depot.git/git-upload-pack",
		"https://git.example/org/depot.git/git-receive-pack",
	} {
		u, _ := url.Parse(brut)
		if !EstGitSmart(u) {
			t.Errorf("%s n'est pas reconnu comme négociation git", brut)
		}
		if got := Classify(u); got != ClassNoStore {
			t.Errorf("%s classé « %s », attendu « no-store »", brut, got)
		}
	}
}

// Le protocole « dumb », lui, sert des fichiers : un objet porte son empreinte
// dans son nom et se garde comme n'importe quel fichier figé.
func TestLesObjetsGitRestentCachables(t *testing.T) {
	for _, brut := range []string{
		"https://git.example/org/depot.git/objects/ab/cdef0123456789",
		"https://git.example/org/depot.git/objects/pack/pack-abc.pack",
	} {
		u, _ := url.Parse(brut)
		if EstGitSmart(u) {
			t.Errorf("%s pris pour une négociation, à tort", brut)
		}
	}
}

func TestEstGitSmartURLNulle(t *testing.T) {
	if EstGitSmart(nil) {
		t.Error("une URL absente est prise pour du git")
	}
}

// Un index Debian publié sous l'empreinte de son contenu est aussi figé
// qu'un paquet : son nom EST sa somme. Il se range donc SANS son hôte, un
// contenu différent portant forcément un autre nom.
func TestLesIndexParEmpreinteSontImmuables(t *testing.T) {
	sha256 := strings.Repeat("0123456789abcdef", 4)
	md5 := strings.Repeat("0123456789abcdef", 2)
	for _, brut := range []string{
		"https://miroir.example/debian/dists/trixie/main/binary-amd64/by-hash/SHA256/" + sha256,
		"https://miroir.example/debian/dists/trixie/main/i18n/by-hash/MD5Sum/" + md5,
	} {
		u, _ := url.Parse(brut)
		if got := Classify(u); got != ClassImmutable {
			t.Errorf("%s classé « %s », attendu « immutable »", brut, got)
		}
		if !PortableParChemin(u) {
			t.Errorf("%s n'est pas jugé portable", brut)
		}
	}
	// Ce qui n'est pas une empreinte garde la règle d'avant.
	for _, brut := range []string{
		"https://miroir.example/debian/dists/trixie/by-hash/SHA256/pas-une-somme",
		"https://miroir.example/debian/dists/trixie/by-hash/SHA256/" + sha256 + "?v=2",
	} {
		u, _ := url.Parse(brut)
		if got := Classify(u); got != ClassVolatile {
			t.Errorf("%s classé « %s », attendu « volatile »", brut, got)
		}
	}
}

// Une métadonnée RPM nommée par sa somme est figée, quelle que soit sa
// compression ; « repomd.xml », qui la désigne, reste volatile, et un nom sans
// somme en tête garde la règle de son suffixe.
func TestLesMetadonneesRPMParEmpreinteSontImmuables(t *testing.T) {
	somme := strings.Repeat("0123456789abcdef", 4)
	for _, nom := range []string{
		somme + "-primary.xml.zck", somme + "-primary.xml.gz",
		somme + "-updateinfo.xml.zst", somme + "-comps-BaseOS.x86_64.xml",
	} {
		u, _ := url.Parse("https://miroir.example/fedora/linux/updates/42/Everything/x86_64/repodata/" + nom)
		if got := Classify(u); got != ClassImmutable {
			t.Errorf("%s classé « %s », attendu « immutable »", nom, got)
		}
		if !PortableParChemin(u) {
			t.Errorf("%s n'est pas jugé portable", nom)
		}
	}
	for _, brut := range []string{
		"https://miroir.example/fedora/repodata/repomd.xml",
		"https://miroir.example/fedora/repodata/primary.xml.gz",
		"https://miroir.example/fedora/repodata/pas-une-somme-primary.xml.zck",
		"https://miroir.example/fedora/ailleurs/" + somme + "-primary.xml.zck",
	} {
		u, _ := url.Parse(brut)
		if got := Classify(u); got != ClassVolatile {
			t.Errorf("%s classé « %s », attendu « volatile »", brut, got)
		}
	}
}

// Le même index par empreinte, servi par deux miroirs. Sans clé portable,
// changer de miroir vide le cache de ses index : une installation hors ligne
// échoue alors sur des octets que le magasin détient pourtant, et le message
// accuse le dépôt.
func TestUnIndexParEmpreinteVautSurDeuxMiroirs(t *testing.T) {
	somme := strings.Repeat("0123456789abcdef", 4)
	chemin := "/debian/dists/trixie/main/binary-amd64/by-hash/SHA256/" + somme
	a, _ := url.Parse("https://miroir-a.example" + chemin)
	b, _ := url.Parse("https://miroir-b.example" + chemin)
	if CleDe("GET", a) != CleDe("GET", b) {
		t.Error("deux miroirs du même index donnent deux clés")
	}
	// La clé complète doit, elle, continuer de les distinguer : c'est ce qui
	// prouve que le rangement passe bien par la clé SANS hôte, et non que les
	// deux fonctions se sont mises à rendre la même chose.
	if Key("GET", a.String()) == Key("GET", b.String()) {
		t.Error("la clé complète ne distingue plus les deux URL")
	}
}

// Un pointeur vers la dernière version publiée change de cible à chaque
// publication : son suffixe d'archive ne doit pas le figer sur le disque, ni
// le ranger sans son hôte.
func TestUnPointeurDeDerniereVersionEstVolatile(t *testing.T) {
	for _, brut := range []string{
		"https://forge.example/o/d/releases/latest/download/outil-x86_64-linux.tar.gz",
		"https://forge.example/o/d/releases/latest/download/outil.zip",
	} {
		u, _ := url.Parse(brut)
		if got := Classify(u); got != ClassVolatile {
			t.Errorf("%s classé « %s », attendu « volatile »", brut, got)
		}
		if PortableParChemin(u) {
			t.Errorf("%s jugé portable", brut)
		}
	}
	// Une version NOMMÉE reste figée par son suffixe.
	u, _ := url.Parse("https://forge.example/o/d/releases/download/v1.2.3/outil.tar.gz")
	if got := Classify(u); got != ClassImmutable {
		t.Errorf("une version nommée classée « %s », attendu « immutable »", got)
	}
}

// Les métadonnées PEP 658 se rangent sans leur hôte, comme l'archive qu'elles
// décrivent : leur chemin porte déjà l'empreinte du contenu.
func TestLesMetadonneesPythonSontPortables(t *testing.T) {
	for _, brut := range []string{
		"https://pypi.example/packages/ab/cd/requests-2.33.0-py3-none-any.whl.metadata",
		"https://pypi.example/packages/ab/cd/requests-2.33.0.zip.metadata",
	} {
		u, err := url.Parse(brut)
		if err != nil {
			t.Fatal(err)
		}
		if !PortableParChemin(u) {
			t.Errorf("%s n'est pas portable", brut)
		}
	}
}
