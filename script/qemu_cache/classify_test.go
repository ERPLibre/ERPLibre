// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/url"
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
