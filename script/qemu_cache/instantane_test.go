// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/http"
	"net/url"
	"testing"
)

// vendredi et samedi : deux instantanés d'un dépôt apt, à un jour d'écart.
const (
	vendredi = "Fri, 11 Sep 2026 07:18:59 GMT"
	samedi   = "Sat, 12 Sep 2026 13:06:19 GMT"
)

// garnir range un corps sous son URL, avec la date que l'amont lui donne.
func garnir(t *testing.T, p *Proxy, brut, corps, lastModified string) {
	t.Helper()
	u, err := url.Parse(brut)
	if err != nil {
		t.Fatal(err)
	}
	w, err := p.Store.NewWriter(CleDe("GET", u), Meta{
		URL: u.String(), Method: "GET", Status: http.StatusOK,
		Header: http.Header{"Last-Modified": []string{lastModified}},
		Class:  ClassVolatile.String(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := w.Write([]byte(corps)); err != nil {
		t.Fatal(err)
	}
	if err := w.Commit(int64(len(corps))); err != nil {
		t.Fatal(err)
	}
}

// Un index plus récent que la signature qui l'annonce n'est pas servi.
//
// apt exige de chaque index la taille et la somme écrites dans la
// signature : un index pris à un autre instantané le fait échouer sur
// « File has unexpected size », et l'installation s'arrête plus bas sur des
// dépendances introuvables — un message qui accuse le dépôt, jamais le
// cache.
func TestUnIndexPlusRecentQueSaSignatureNeSortPas(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	p := proxyDeTest(t)
	base := "http://" + a.hote() + "/ubuntu/dists/resolute-updates/"
	garnir(t, p, base+"InRelease", "signature de vendredi", vendredi)
	garnir(t, p, base+"main/binary-amd64/Packages.xz", "index de samedi", samedi)
	hote := a.hote()
	a.srv.Close()

	w := joue(t, p, "GET", hote, "/ubuntu/dists/resolute-updates/InRelease")
	if w.Code != http.StatusOK {
		t.Fatalf("la signature gardée doit sortir : code %d", w.Code)
	}
	w = joue(t, p, "GET", hote,
		"/ubuntu/dists/resolute-updates/main/binary-amd64/Packages.xz")
	if w.Code == http.StatusOK {
		t.Errorf("l'index de samedi est sorti sous la signature de vendredi")
	}
}

// L'inverse est le cas NORMAL : les deux viennent du même passage en ligne,
// et refuser de servir là romprait le déploiement hors ligne.
func TestUnIndexAussiVieuxQueSaSignatureSort(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	p := proxyDeTest(t)
	base := "http://" + a.hote() + "/ubuntu/dists/resolute/"
	garnir(t, p, base+"InRelease", "signature", vendredi)
	garnir(t, p, base+"main/binary-amd64/Packages.xz", "index", vendredi)
	hote := a.hote()
	a.srv.Close()

	w := joue(t, p, "GET", hote,
		"/ubuntu/dists/resolute/main/binary-amd64/Packages.xz")
	if w.Code != http.StatusOK || w.Body.String() != "index" {
		t.Fatalf("code %d, corps %q : l'index du même instantané doit sortir",
			w.Code, w.Body.String())
	}
}

// Un objet adressé par son contenu ne se juge pas : son nom EST sa somme,
// et apt l'accepte quelle que soit la date de la signature.
func TestUnObjetParEmpreinteSortQuandMeme(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	p := proxyDeTest(t)
	base := "http://" + a.hote() + "/ubuntu/dists/resolute-updates/"
	garnir(t, p, base+"InRelease", "signature de vendredi", vendredi)
	parHash := base + "main/binary-amd64/by-hash/SHA256/" +
		"e55707cc7a5ad03d7f700ccb6646fd5c6ecbc852c4c826f5edbb5a321358d0ee"
	garnir(t, p, parHash, "index de samedi", samedi)
	hote := a.hote()
	a.srv.Close()

	w := joue(t, p, "GET", hote,
		"/ubuntu/dists/resolute-updates/main/binary-amd64/by-hash/SHA256/"+
			"e55707cc7a5ad03d7f700ccb6646fd5c6ecbc852c4c826f5edbb5a321358d0ee")
	if w.Code != http.StatusOK {
		t.Errorf("un objet par empreinte a été retenu : code %d", w.Code)
	}
}

// Sans signature gardée, il n'y a rien à contredire : l'index gardé est tout
// ce que le hors-ligne possède, et le retenir ne servirait personne.
func TestSansSignatureLIndexSortQuandMeme(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	p := proxyDeTest(t)
	garnir(t, p, "http://"+a.hote()+
		"/ubuntu/dists/orpheline/main/binary-amd64/Packages.xz",
		"index seul", samedi)
	hote := a.hote()
	a.srv.Close()

	w := joue(t, p, "GET", hote,
		"/ubuntu/dists/orpheline/main/binary-amd64/Packages.xz")
	if w.Code != http.StatusOK || w.Body.String() != "index seul" {
		t.Errorf("code %d, corps %q : l'index sans signature doit sortir",
			w.Code, w.Body.String())
	}
}

// Hors de « /dists/ », aucune signature n'entre en jeu : un paquet ne se
// juge pas sur la date d'un index.
func TestHorsDeDistsRienNestJuge(t *testing.T) {
	a := nouvelAmont(t, "peu importe")
	p := proxyDeTest(t)
	garnir(t, p, "http://"+a.hote()+"/ubuntu/pool/main/x/xz_5.6_amd64.deb",
		"le paquet", samedi)
	hote := a.hote()
	a.srv.Close()

	w := joue(t, p, "GET", hote, "/ubuntu/pool/main/x/xz_5.6_amd64.deb")
	if w.Code != http.StatusOK {
		t.Errorf("un paquet a été retenu : code %d", w.Code)
	}
}
