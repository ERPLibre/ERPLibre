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
	"os"
	"path/filepath"
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

func (s *Store) paths(key string) (metaPath, bodyPath string) {
	// Deux niveaux de répertoires : un seul répertoire de cent mille entrées
	// ralentit chaque ouverture sur la plupart des systèmes de fichiers.
	dir := filepath.Join(s.Dir, key[0:2], key[2:4])
	return filepath.Join(dir, key+".meta"), filepath.Join(dir, key+".body")
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
		return fmt.Errorf("corps tronqué : %d octets sur %d", w.written, expected)
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
func (s *Store) Stat() (Stats, error) {
	var st Stats
	err := filepath.Walk(s.Dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
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
		if err != nil || info.IsDir() {
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
		return fmt.Sprintf("%d o", n)
	}
	units := []string{"Kio", "Mio", "Gio", "Tio"}
	v := float64(n)
	for _, u := range units {
		v /= unit
		if v < unit {
			return fmt.Sprintf("%.1f %s", v, u)
		}
	}
	return fmt.Sprintf("%.1f Pio", v/unit)
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
