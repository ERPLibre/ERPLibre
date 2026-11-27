// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
)

// DepotPacman sert un dépôt pacman local à la place de N'IMPORTE QUEL miroir
// Arch : toute URL dont le chemin finit par « <dépôt>/os/<arch>/<fichier> »,
// quel que soit l'hôte et le préfixe, sort de Dir/<dépôt>/os/<arch>/.
//
// Le nom d'hôte ne compte pas, parce que la liste de miroirs de qui demande
// n'est pas la nôtre : celle du live, celle que pacstrap recopie dans la
// cible, et celle que les scripts d'ERPLibre complètent dans le chroot
// désignent toutes des miroirs différents, au préfixe différent. Toutes
// mènent ici, et la cible garde une liste de vrais miroirs, sans entrée morte
// à retirer après l'installation.
//
// Seul un dépôt PRÉSENT sous Dir est servi ; une URL d'un autre dépôt suit
// le chemin ordinaire du cache. Un fichier absent d'un dépôt présent rend
// « 404 » : pacman passe aussitôt au miroir suivant, et une signature de base
// facultative (« core.db.sig ») ne fait pas échouer la synchronisation.
type DepotPacman struct {
	Dir string
}

// Outcomes du dépôt local, au journal d'accès.
const (
	OutcomePacman       = "pacman"        // servi du dépôt local
	OutcomePacmanAbsent = "pacman-absent" // dépôt local présent, fichier absent
)

// composantPacman : un nom de dépôt, d'architecture ou de fichier. Ni
// séparateur ni « .. » : un point en tête est refusé à part. Le deux-points
// est celui de l'époque d'une version (« grub-2:2.16-1-x86_64.pkg.tar.zst »),
// que pacman demande tel quel : sans lui, tout paquet à époque sortirait du
// dépôt local et manquerait hors ligne.
var composantPacman = regexp.MustCompile(`^[A-Za-z0-9@_+.:-]+$`)

func composantSur(s string) bool {
	return composantPacman.MatchString(s) && !strings.HasPrefix(s, ".")
}

// Actif dit si un dépôt local est configuré.
func (d *DepotPacman) Actif() bool {
	return d != nil && d.Dir != ""
}

// Fichier rend le chemin local que désigne l'URL et dit si l'URL relève du
// dépôt local : son chemin a la forme d'un miroir Arch et le dépôt nommé
// existe sous Dir. Le fichier lui-même peut manquer.
func (d *DepotPacman) Fichier(u *url.URL) (string, bool) {
	if !d.Actif() || u == nil {
		return "", false
	}
	morceaux := strings.Split(strings.Trim(path.Clean("/"+u.Path), "/"), "/")
	if len(morceaux) < 4 {
		return "", false
	}
	queue := morceaux[len(morceaux)-4:]
	depot, segment, arch, nom := queue[0], queue[1], queue[2], queue[3]
	if segment != "os" || !composantSur(depot) || !composantSur(arch) ||
		!composantSur(nom) {
		return "", false
	}
	dossier := filepath.Join(d.Dir, depot, "os", arch)
	if st, err := os.Stat(dossier); err != nil || !st.IsDir() {
		return "", false
	}
	return filepath.Join(dossier, nom), true
}

// dansLeDepot dit si `chemin`, liens résolus, reste sous Dir : un lien
// symbolique du dépôt (« core.db » vers « core.db.tar.gz ») est suivi, un
// lien qui en sort ne l'est pas.
func (d *DepotPacman) dansLeDepot(chemin string) bool {
	racine, err := filepath.EvalSymlinks(d.Dir)
	if err != nil {
		return false
	}
	reel, err := filepath.EvalSymlinks(chemin)
	if err != nil {
		return false
	}
	rel, err := filepath.Rel(racine, reel)
	return err == nil && rel != ".." && !strings.HasPrefix(rel, "../")
}

// servirPacman répond à la requête si elle relève du dépôt local, et dit si elle a
// été traitée. Seuls GET et HEAD sont servis ; ServeContent tient les plages,
// par lesquelles pacman reprend un téléchargement interrompu.
func (p *Proxy) servirPacman(w http.ResponseWriter, r *http.Request, u *url.URL) bool {
	chemin, releve := p.Pacman.Fichier(u)
	if !releve {
		return false
	}
	client := clientDe(r.RemoteAddr)
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, T("dépôt pacman local : lecture seule"),
			http.StatusMethodNotAllowed)
		return true
	}
	var f *os.File
	var st os.FileInfo
	var err error
	if p.Pacman.dansLeDepot(chemin) {
		f, err = os.Open(chemin)
		if err == nil {
			st, err = f.Stat()
			if err == nil && st.IsDir() {
				err = fmt.Errorf("%s", T("répertoire"))
			}
		}
	} else {
		err = os.ErrNotExist
	}
	if err != nil {
		if f != nil {
			f.Close()
		}
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.Header().Set("X-ERPLibre-Cache", OutcomePacmanAbsent)
		w.WriteHeader(http.StatusNotFound)
		fmt.Fprint(w, enCommentaire(fmt.Sprintf(
			T("erplibre_go_qemu_cache : absent du dépôt pacman local.\n"+
				"  demandé : %s\n"), u)))
		p.record(accessLine{
			Method: r.Method, URL: u.String(), Class: "pacman",
			Outcome: OutcomePacmanAbsent, Status: http.StatusNotFound,
			Client: client,
		})
		return true
	}
	defer f.Close()
	w.Header().Set("X-ERPLibre-Cache", OutcomePacman)
	w.Header().Set("Content-Type", "application/octet-stream")
	http.ServeContent(w, r, "", st.ModTime(), f)
	p.record(accessLine{
		Method: r.Method, URL: u.String(), Class: "pacman",
		Outcome: OutcomePacman, Status: http.StatusOK, Bytes: st.Size(),
		Client: client,
	})
	return true
}
