// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

// dossierSuite isole « …/dists/<suite>/ » du chemin d'un index apt.
var dossierSuite = regexp.MustCompile(`^(.*/dists/[^/]+/)`)

// indexIncoherent dit si le corps gardé sous cette clé appartient à un
// instantané PLUS RÉCENT que la signature gardée pour la même suite.
//
// apt lit d'abord « InRelease », puis exige de chaque index la taille et la
// somme qui y sont écrites. Hors ligne, chaque objet sort du magasin avec sa
// propre date : un index rafraîchi samedi, servi sous une signature gardée
// depuis vendredi, fait échouer apt sur « File has unexpected size » ou
// « Hash Sum mismatch ». L'installation s'arrête plus bas sur des
// dépendances introuvables — un message qui accuse le dépôt, jamais le
// cache. Ne rien servir vaut mieux : apt garde alors ses propres listes,
// dit « old ones used instead » et poursuit.
//
// La comparaison porte sur le « Last-Modified » de l'AMONT, jamais sur la
// date de stockage : celle-ci est renouvelée à chaque service, si bien
// qu'une signature servie après l'index paraîtrait plus jeune que lui.
//
// Trois objets échappent au jugement : ceux qui sont adressés par leur
// contenu (« by-hash »), dont le nom EST la somme ; les signatures
// elles-mêmes, qui sont l'étalon ; et tout ce qui ne vit pas sous
// « /dists/ ».
func (p *Proxy) indexIncoherent(u *url.URL, key string) bool {
	if p == nil || p.Store == nil || u == nil {
		return false
	}
	if strings.Contains(u.Path, "/by-hash/") {
		return false
	}
	if strings.HasSuffix(u.Path, "/InRelease") ||
		strings.HasSuffix(u.Path, "/Release") ||
		strings.HasSuffix(u.Path, "/Release.gpg") {
		return false
	}
	trouve := dossierSuite.FindStringSubmatch(u.Path)
	if trouve == nil {
		return false
	}
	signature := *u
	signature.Path = trouve[1] + "InRelease"
	signature.RawQuery = ""
	metaSig, err := p.Store.LireMeta(CleDe("GET", &signature))
	if err != nil {
		// Aucune signature gardée : rien à contredire, et l'index gardé est
		// tout ce que le hors-ligne possède.
		return false
	}
	metaIdx, err := p.Store.LireMeta(key)
	if err != nil {
		return false
	}
	dateSig, okSig := dateAmont(metaSig)
	dateIdx, okIdx := dateAmont(metaIdx)
	if !okSig || !okIdx {
		// Sans les deux dates, on ne sait pas : servir reste le comportement
		// qui rend un déploiement hors ligne possible.
		return false
	}
	return dateIdx.After(dateSig)
}

// dateAmont rend le « Last-Modified » écrit par l'amont, et dit s'il y en a
// un. C'est la seule date que le magasin ne retouche jamais.
func dateAmont(m *Meta) (t time.Time, ok bool) {
	if m == nil || m.Header == nil {
		return time.Time{}, false
	}
	brut := http.Header(m.Header).Get("Last-Modified")
	if brut == "" {
		return time.Time{}, false
	}
	quand, err := http.ParseTime(brut)
	if err != nil {
		return time.Time{}, false
	}
	return quand, true
}
