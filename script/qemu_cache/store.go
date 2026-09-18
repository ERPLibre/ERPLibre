// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Store garde les réponses sur disque, un objet valant deux fichiers : les
// métadonnées en JSON et le corps brut.
//
// Le corps ne passe jamais en mémoire : une image qcow2 pèse des gigaoctets,
// et un cache qui la charge pour la servir tue l'orchestrateur. Écriture par
// fichier temporaire puis renommage, si bien qu'un objet visible est toujours
// un objet complet — une interruption ne laisse qu'un temporaire, que le
// démarrage suivant balaie.
type Store struct {
	Dir string
}

// Meta accompagne chaque corps stocké.
type Meta struct {
	URL      string      `json:"url"`
	Method   string      `json:"method"`
	Status   int         `json:"status"`
	Header   http.Header `json:"header"`
	Size     int64       `json:"size"`
	StoredAt time.Time   `json:"stored_at"`
	Class    string      `json:"class"`
	// StatusOnly marque un objet gardé SANS corps, qui ne rejoue que son
	// statut. Le statut seul ne suffit pas à le dire : le 200 d'un HEAD est
	// un statut seul, et se lirait sinon comme un corps vide.
	//
	// Le marqueur décrit l'objet, il ne le protège pas : ce qui tient un
	// lecteur plus ancien à l'écart d'un statut seul, c'est la clé sous
	// laquelle il est rangé (voir CleStatut), pas un champ qu'un tel lecteur
	// ignore.
	StatusOnly bool `json:"status_only,omitempty"`
}

// StatutReel rend le statut gardé, 200 quand le méta n'en porte pas : un méta
// écrit avant que le magasin garde autre chose que des corps n'a pas de
// statut, et il décrivait toujours un 200.
func (m *Meta) StatutReel() int {
	if m.Status == 0 {
		return http.StatusOK
	}
	return m.Status
}

// StatutSeul dit si l'objet ne porte qu'un statut : marqué comme tel, ou de
// statut autre que 200 — seul un 200 a jamais été gardé avec son corps.
func (m *Meta) StatutSeul() bool {
	return m.StatusOnly || m.StatutReel() != http.StatusOK
}

// Stats répond au besoin de surveillance manuelle : aucune éviction n'est
// écrite, donc l'outil doit au moins dire ce qu'il occupe.
type Stats struct {
	Objects int
	Bytes   int64
	Oldest  time.Time
}

var errMiss = errors.New("cache: absent")

// Key mêle la méthode et l'URL : un HEAD et un GET sur la même adresse ne
// portent pas le même corps.
func Key(method, rawURL string) string {
	sum := sha256.Sum256([]byte(method + " " + rawURL))
	return hex.EncodeToString(sum[:])
}

// KeySansHote range un objet sous son CHEMIN, l'hôte écarté.
//
// Une liste de miroirs tourne : pacman tire un fichier de « fastly », le
// suivant de « geo », et une clé qui porte l'hôte réduit alors le cache à
// néant — même fichier, autre nom, défaut de cache. Le chemin, lui, identifie
// le fichier sur TOUS les miroirs d'une même distribution :
// « /core/os/x86_64/bash-5.3-1-x86_64.pkg.tar.zst » nomme le même octet
// partout, sa version et son architecture étant dans son nom.
//
// Réservé aux fichiers dont le NOM porte l'identité — paquets, index de
// dépôt. L'appliquer à tout ferait entrer en collision les « /index.html » de
// deux sites sans rapport.
//
// Le chemin ENTIER ne suffisait pas : un miroir le préfixe à sa guise —
// « /rocky/10.2/… », « /mirror/rocky-linux/10.2/… », « /pub/archive/fedora/… »
// — et le même octet prenait alors deux clés. Seule la FIN du chemin est
// retenue (voir SegmentsDeCle), ce qui réunit ces copies sans jamais
// confondre deux distributions.
// SegmentsDeCle : combien de segments de FIN de chemin identifient un fichier.
//
// Six, et pas moins : un chemin Debian en porte exactement six —
// « debian/pool/main/p/<paquet>/<fichier>.deb » — si bien que cinq
// effaceraient le segment de distribution et donneraient la même clé au
// paquet d'Ubuntu, qui porte le même nom pour d'autres octets.
const SegmentsDeCle = 6

// SegmentsDeCleArch : les paquets d'Arch en demandent moins.
//
// Un miroir d'Arch sert « archlinux/core/os/x86_64/<paquet> » là où un autre
// sert « core/os/x86_64/<paquet> » : quatre et cinq segments, donc plus COURTS
// que la borne commune, qui les garde alors entiers et en fait deux clés.
//
// Quatre, et non moins : la clé garde ainsi le nom du dépôt — « core »,
// « extra » — et ne perd que le segment décoratif du miroir. Deux ou trois
// réuniraient les mêmes copies, mais effaceraient cette distinction sans
// nécessité.
//
// Le cas est sûr là où celui de Debian ne l'est pas : Ubuntu reprend les
// paquets de Debian en gardant leur version, si bien qu'un même nom « .deb »
// porte deux contenus selon la distribution. Un espace de noms partagé exige
// la borne haute ; celui d'Arch n'appartient qu'à lui.
const SegmentsDeCleArch = 4

// estPaquetArch reconnaît un paquet de la famille pacman à son nom.
func estPaquetArch(nom string) bool {
	nom = strings.ToLower(nom)
	return strings.HasSuffix(nom, ".pkg.tar.zst") ||
		strings.HasSuffix(nom, ".pkg.tar.xz")
}

func KeySansHote(method string, u *url.URL) string {
	segments := make([]string, 0, SegmentsDeCle+2)
	for _, s := range strings.Split(u.Path, "/") {
		// Les segments vides tombent : un miroir écrit « /pub/rocky//10.2 »,
		// et deux écritures d'un même chemin feraient sinon deux clés.
		if s != "" {
			segments = append(segments, s)
		}
	}
	borne := SegmentsDeCle
	if len(segments) > 0 && estPaquetArch(segments[len(segments)-1]) {
		borne = SegmentsDeCleArch
	}
	if len(segments) > borne {
		segments = segments[len(segments)-borne:]
	}
	chemin := strings.Join(segments, "/")
	if u.RawQuery != "" {
		chemin += "?" + u.RawQuery
	}
	sum := sha256.Sum256([]byte(method + " path " + chemin))
	return hex.EncodeToString(sum[:])
}

// CleDe rend la clé sous laquelle une réponse est rangée et cherchée.
//
// La clé écarte l'hôte quand le NOM du fichier l'identifie partout : une
// liste de miroirs tourne, et une clé qui porte l'hôte ferait manquer le
// cache au fichier déjà gardé sous un autre nom de miroir. Le service et la
// lecture « --detient » passent tous deux par ici : deux calculs de la clé
// finiraient par diverger, et le relevé dirait absent ce que le service sert.
func CleDe(method string, u *url.URL) string {
	if PortableParChemin(u) {
		return KeySansHote(method, u)
	}
	return Key(method, u.String())
}

// CleVariante rend la clé d'une REPRÉSENTATION de l'objet rangé sous key,
// celle que choisit l'en-tête Accept de la requête.
//
// Un amont qui répond « Vary: Accept » sert sous une même URL plusieurs corps
// selon ce que le client accepte : une fiche de paquet complète ou abrégée.
// Rangés sous la seule clé de l'URL, ils se remplacent l'un l'autre, si bien
// qu'une installation qui demande les deux tour à tour les retélécharge
// chaque fois. La clé de base reste écrite comme avant ; la variante s'y
// ajoute. Rend "" pour un Accept vide : la requête n'en choisit aucune.
func CleVariante(key, accept string) string {
	accept = strings.Join(strings.Fields(strings.ToLower(accept)), " ")
	if accept == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(key + " accept " + accept))
	return hex.EncodeToString(sum[:])
}

// Copier publie sous dst le corps et les métadonnées rangés sous src, par le
// même temporaire et le même renommage qu'une écriture ordinaire : une copie
// interrompue ne laisse rien de visible. La date d'usage de src n'est pas
// touchée.
func (s *Store) Copier(src, dst string) error {
	m, err := s.LireMeta(src)
	if err != nil {
		return err
	}
	_, bodyPath := s.paths(src)
	f, err := os.Open(bodyPath)
	if err != nil {
		return err
	}
	defer f.Close()
	w, err := s.NewWriter(dst, *m)
	if err != nil {
		return err
	}
	if _, err := io.Copy(w, f); err != nil {
		w.Abort()
		return err
	}
	return w.Commit(m.Size)
}

// Toucher remet à maintenant la date d'usage du corps rangé sous key, s'il
// existe. Servir une variante sert aussi l'objet de base : sans cela, un
// nettoyage par âge retirerait la base qu'on sert encore par sa variante, et
// --detient la dirait absente.
func (s *Store) Toucher(key string) {
	_, bodyPath := s.paths(key)
	maintenant := time.Now()
	_ = os.Chtimes(bodyPath, maintenant, maintenant)
}

// CleStatut rend la clé sous laquelle un STATUT SEUL est rangé et cherché.
//
// Un espace de clés à part, et non la clé du corps : un lecteur qui ne
// connaît que les corps ne lit que Key et KeySansHote, et ne tombe donc
// jamais sur un statut seul. Rangé sous la clé du corps, un tel objet — un
// méta 302 et un corps de zéro octet de la bonne taille — ressortirait chez
// lui en « 200 » vide, que « curl … | bash » exécuterait comme un script
// vide qui réussit.
//
// Aucune clé de corps ne peut la rejoindre : une méthode HTTP ne porte pas
// d'espace, si bien que « STATUT GET … » n'est la méthode d'aucune requête.
// L'URL entière, hôte compris : un statut seul ne se garde jamais sous une
// clé portable.
func CleStatut(method string, u *url.URL) string {
	return Key("STATUT "+method, u.String())
}

// TientStatut dit si la clé porte un statut seul que le rejeu servirait : un
// méta lisible, marqué statut seul, dont le corps a la taille annoncée — les
// conditions mêmes auxquelles Get le rend.
func (s *Store) TientStatut(key string) bool {
	m, err := s.LireMeta(key)
	if err != nil || !m.StatutSeul() {
		return false
	}
	_, bodyPath := s.paths(key)
	fi, err := os.Stat(bodyPath)
	return err == nil && fi.Size() == m.Size
}

func (s *Store) paths(key string) (metaPath, bodyPath string) {
	// Deux niveaux de répertoires : un seul répertoire de cent mille entrées
	// ralentit chaque ouverture sur la plupart des systèmes de fichiers.
	dir := filepath.Join(s.Dir, key[0:2], key[2:4])
	return filepath.Join(dir, key+".meta"), filepath.Join(dir, key+".body")
}

// LireMeta rend les métadonnées d'une clé sans toucher au corps.
//
// Get, lui, remet la date du corps à maintenant : un relevé qui passerait par
// lui rajeunirait tout ce qu'il regarde, et l'âge du dernier usage ne
// voudrait plus rien dire. Un méta illisible vaut absent.
func (s *Store) LireMeta(key string) (*Meta, error) {
	metaPath, _ := s.paths(key)
	raw, err := os.ReadFile(metaPath)
	if err != nil {
		return nil, errMiss
	}
	var m Meta
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, errMiss
	}
	return &m, nil
}

// Get rend les métadonnées et un lecteur positionné sur le corps. Le lecteur
// est à refermer par l'appelant.
func (s *Store) Get(key string) (*Meta, *os.File, error) {
	metaPath, bodyPath := s.paths(key)
	raw, err := os.ReadFile(metaPath)
	if err != nil {
		return nil, nil, errMiss
	}
	var m Meta
	if err := json.Unmarshal(raw, &m); err != nil {
		// Métadonnées illisibles : l'objet vaut absent plutôt que faux.
		return nil, nil, errMiss
	}
	f, err := os.Open(bodyPath)
	if err != nil {
		return nil, nil, errMiss
	}
	// La date du corps est remise à MAINTENANT parce qu'on va le servir.
	//
	// C'est ce qui permet à un nettoyage par âge de vouloir dire « ce qui ne
	// sert plus » et non « ce qui est entré il y a longtemps ». Un paquet
	// servi tous les jours depuis un an n'est pas vieux : l'effacer
	// obligerait à le retélécharger le lendemain, ce qui est exactement le
	// contraire de ce qu'un cache est là pour faire.
	//
	// L'échec est ignoré : un magasin en lecture seule doit servir, pas
	// refuser parce qu'il n'a pas pu noter une date.
	maintenant := time.Now()
	_ = os.Chtimes(bodyPath, maintenant, maintenant)
	st, err := f.Stat()
	if err != nil || st.Size() != m.Size {
		// Un corps dont la taille ne correspond plus est une écriture
		// interrompue par un moyen qui a contourné le renommage.
		f.Close()
		return nil, nil, errMiss
	}
	return &m, f, nil
}

// Writer accumule un corps dans un temporaire et ne le publie qu'à la
// fermeture réussie.
type Writer struct {
	store    *Store
	key      string
	meta     Meta
	tmp      *os.File
	written  int64
	finished bool
}

// Detient dit si une clé porte le corps d'une réponse 200, sans l'ouvrir.
//
// Sert à décider si une requête conditionnelle peut partir telle quelle :
// sans corps en réserve, un « 304 » de l'amont ne laisserait rien à garder,
// et le cache resterait vide pour cette ressource aussi longtemps que ses
// clients en détiennent une copie — c'est-à-dire toujours.
//
// Un objet de statut seul ne compte pas : il vit sous sa propre clé
// (CleStatut), et un méta de statut qui se trouverait sous une clé de corps
// n'en fait pas un corps. La condition est alors retirée, pour que le premier
// 200 que l'amont rendra vienne entier. C'est aussi le test qui interdit de
// garder un refus quand un corps est en réserve : un statut seul ne s'écrit
// que là où Detient est faux pour la clé du corps.
func (s *Store) Detient(key string) bool {
	m, err := s.LireMeta(key)
	if err != nil || m.StatutSeul() {
		return false
	}
	_, bodyPath := s.paths(key)
	fi, err := os.Stat(bodyPath)
	return err == nil && fi.Size() > 0
}

// NewWriter ouvre un temporaire dans le répertoire de destination : un
// renommage n'est atomique qu'au sein d'un même système de fichiers.
func (s *Store) NewWriter(key string, m Meta) (*Writer, error) {
	metaPath, _ := s.paths(key)
	if err := os.MkdirAll(filepath.Dir(metaPath), 0o755); err != nil {
		return nil, err
	}
	tmp, err := os.CreateTemp(filepath.Dir(metaPath), key+".part-*")
	if err != nil {
		return nil, err
	}
	return &Writer{store: s, key: key, meta: m, tmp: tmp}, nil
}

func (w *Writer) Write(p []byte) (int, error) {
	n, err := w.tmp.Write(p)
	w.written += int64(n)
	return n, err
}

// Commit publie l'objet. La taille annoncée par l'amont, quand il l'annonce,
// est vérifiée : une réponse tronquée par une coupure réseau ressemble à une
// réponse complète pour tout le reste du code.
func (w *Writer) Commit(expected int64) error {
	defer w.cleanup()
	if expected >= 0 && w.written != expected {
		return fmt.Errorf(T("corps tronqué : %d octets sur %d"), w.written, expected)
	}
	if err := w.tmp.Sync(); err != nil {
		return err
	}
	if err := w.tmp.Close(); err != nil {
		return err
	}
	w.meta.Size = w.written
	w.meta.StoredAt = time.Now().UTC()
	raw, err := json.Marshal(w.meta)
	if err != nil {
		return err
	}
	metaPath, bodyPath := w.store.paths(w.key)
	if err := os.Rename(w.tmp.Name(), bodyPath); err != nil {
		return err
	}
	// Les métadonnées en DERNIER : leur présence est ce qui rend l'objet
	// visible, et un corps sans métadonnées est simplement ignoré.
	if err := os.WriteFile(metaPath+".part", raw, 0o644); err != nil {
		return err
	}
	w.finished = true
	return os.Rename(metaPath+".part", metaPath)
}

// Abort jette le temporaire. Appelé quand le client se déconnecte ou que
// l'amont coupe : rien de partiel n'entre au cache.
func (w *Writer) Abort() {
	w.cleanup()
}

func (w *Writer) cleanup() {
	if w.finished {
		return
	}
	name := w.tmp.Name()
	w.tmp.Close()
	os.Remove(name)
}

// Stat parcourt le cache. Coûteux sur un grand cache, donc appelé à la
// demande et non à chaque requête.
// horsCasier écarte, à la racine du magasin, tout répertoire qui n'est pas un
// casier à lui.
//
// Les objets sont rangés sous deux niveaux de deux caractères hexadécimaux.
// Ce qui vit à côté — les dépôts git tenus en miroir, par exemple — n'a rien à
// faire dans un parcours du magasin : le traverser coûterait un appel système
// par fichier de chaque dépôt, à chaque relevé et à chaque démarrage.
func horsCasier(racine, chemin string, info os.FileInfo) bool {
	if !info.IsDir() || filepath.Dir(chemin) != filepath.Clean(racine) {
		return false
	}
	nom := filepath.Base(chemin)
	if len(nom) != 2 {
		return true
	}
	for _, c := range nom {
		if !strings.ContainsRune("0123456789abcdefABCDEF", c) {
			return true
		}
	}
	return false
}

func (s *Store) Stat() (Stats, error) {
	var st Stats
	err := filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil {
			return nil
		}
		if horsCasier(s.Dir, p, info) {
			return filepath.SkipDir
		}
		if info.IsDir() {
			return nil
		}
		if filepath.Ext(p) != ".body" {
			return nil
		}
		st.Objects++
		st.Bytes += info.Size()
		if st.Oldest.IsZero() || info.ModTime().Before(st.Oldest) {
			st.Oldest = info.ModTime()
		}
		return nil
	})
	if os.IsNotExist(err) {
		return st, nil
	}
	return st, err
}

// SweepPartials retire ce qu'une interruption a laissé. Lancé au démarrage,
// jamais pendant le service : un « .part » y appartient à une écriture vivante.
func (s *Store) SweepPartials() int {
	n := 0
	filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info == nil {
			return nil
		}
		if horsCasier(s.Dir, p, info) {
			return filepath.SkipDir
		}
		if info.IsDir() {
			return nil
		}
		name := filepath.Base(p)
		if filepath.Ext(p) == ".part" || containsPart(name) {
			if os.Remove(p) == nil {
				n++
			}
		}
		return nil
	})
	return n
}

func containsPart(name string) bool {
	for i := 0; i+5 <= len(name); i++ {
		if name[i:i+5] == ".part" {
			return true
		}
	}
	return false
}

// HumanBytes rend une taille lisible par un opérateur, la surveillance du
// disque étant manuelle.
func HumanBytes(n int64) string {
	const unit = 1024
	if n < unit {
		return fmt.Sprintf(T("%d o"), n)
	}
	units := []string{T("Kio"), T("Mio"), T("Gio"), T("Tio")}
	v := float64(n)
	for _, u := range units {
		v /= unit
		if v < unit {
			return fmt.Sprintf("%.1f %s", v, u)
		}
	}
	return fmt.Sprintf(T("%.1f Pio"), v/unit)
}

// copyTee écrit dans le cache ET vers le client en une seule lecture de
// l'amont : lire deux fois doublerait le trafic que l'outil existe pour
// supprimer.
func copyTee(dst io.Writer, cache io.Writer, src io.Reader) (int64, error) {
	if cache == nil {
		return io.Copy(dst, src)
	}
	return io.Copy(io.MultiWriter(dst, cache), src)
}
