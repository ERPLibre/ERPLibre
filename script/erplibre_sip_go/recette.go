// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"
	"time"
)

// Piloter une messagerie vocale sans la comprendre.
//
// Une messagerie d'opérateur suit toujours le même déroulé : accueil, mot de
// passe, « appuyez sur 1 », messages. Il ne s'agit pas de comprendre ce
// qu'elle dit, seulement de savoir QUAND elle se tait pour jouer la touche
// suivante. Une recette décrit ces étapes ; le moteur les enchaîne en
// écoutant le niveau sonore de la ligne, chaque attente bornée par un délai
// maximal — un appel ouvert se facture, et une messagerie qui ne se tait pas
// ne doit pas retenir la ligne.
//
// Toute la communication est enregistrée d'un seul tenant, avec une courbe
// des niveaux : c'est ce qui permet de régler une recette après coup, en
// voyant où la voix parlait et où la touche est partie.

const (
	// PlaceholderCode est remplacé par le code de la messagerie au moment de
	// composer. Le code ne figure donc jamais dans le fichier de recette.
	PlaceholderCode = "{code}"

	// PasCourbe est la résolution de la courbe des niveaux : cinq blocs de
	// 20 ms. Plus fin n'apprend rien sur une voix ; plus grossier cache le
	// silence d'une demi-seconde entre deux phrases.
	PasCourbe = 100 * time.Millisecond

	// CadenceLigne espace les vérifications que la ligne tient encore.
	CadenceLigne = time.Second

	// DuréeMaxRecette borne une recette entière, quelles que soient ses
	// étapes : aucune consultation de messagerie ne justifie une heure.
	DuréeMaxRecette = 10 * time.Minute

	// ParoleMinDéfaut est la parole cumulée qui compte comme « la ligne a
	// parlé ». Le décroché produit un claquement de 100 ms à pleine échelle :
	// le compter comme de la parole ferait taper le code AVANT que la
	// messagerie ne le demande.
	ParoleMinDéfaut = 300 * time.Millisecond
)

// Étape est une instruction de recette. Une seule de ses parties est posée.
type Étape struct {
	AttendreSilence *AttenteSilence `json:"attendre_silence,omitempty"`
	Touches         string          `json:"touches,omitempty"`
	PauseMs         int             `json:"pause_ms,omitempty"`
	Enregistrer     *Écoute         `json:"enregistrer,omitempty"`
	VérifierParole  *VérifParole    `json:"verifier_parole,omitempty"`
}

// AttenteSilence attend que la ligne se taise.
type AttenteSilence struct {
	// SilenceMs est la durée de silence qui clôt l'attente.
	SilenceMs int `json:"silence_ms"`
	// MaxS borne l'attente. Atteint, on passe à l'étape suivante : un
	// fond sonore permanent ne doit pas retenir la ligne.
	MaxS int `json:"max_s"`
	// ExigerParole : le silence ne compte qu'après que la ligne a parlé.
	// Sans lui, le silence qui précède l'accueil clôturerait l'attente.
	ExigerParole bool `json:"exiger_parole"`
	// ParoleMinMs : la parole cumulée exigée. Zéro vaut ParoleMinDéfaut.
	ParoleMinMs int `json:"parole_min_ms"`
}

// VérifParole est une GARDE : elle arrête la recette, et donc raccroche
// sans rien jouer de plus, si la ligne n'a pas assez parlé depuis la
// dernière touche. Elle se place avant un geste irréversible — un effacement
// — pour qu'il n'ait lieu que si ce qui devait être entendu l'a été.
type VérifParole struct {
	MinS int `json:"min_s"`
}

// Écoute garde la ligne ouverte pour entendre ce qu'elle rend.
type Écoute struct {
	MaxS int `json:"max_s"`
	// SilenceFinS : ce silence, après parole, termine l'écoute. Zéro : on
	// écoute jusqu'au maximum, ce que demande un repérage.
	SilenceFinS int `json:"silence_fin_s"`
}

// Recette est une suite d'étapes.
type Recette struct {
	Étapes []Étape `json:"etapes"`
}

// ChargerRecette lit une recette et la vérifie avant tout appel.
func ChargerRecette(chemin string) (Recette, error) {
	brut, err := os.ReadFile(chemin)
	if err != nil {
		return Recette{}, err
	}
	var r Recette
	if err := json.Unmarshal(brut, &r); err != nil {
		return Recette{}, fmt.Errorf("recette %s : %w", chemin, err)
	}
	return r, r.Vérifier()
}

// Vérifier refuse une recette qui échouerait en ligne.
//
// En ligne, une erreur se paie : l'appel est déjà facturé. Tout ce qui peut
// se juger sur le papier se juge donc avant de composer.
func (r Recette) Vérifier() error {
	if len(r.Étapes) == 0 {
		return errors.New("recette vide")
	}
	for i, é := range r.Étapes {
		posées := 0
		if é.AttendreSilence != nil {
			posées++
			if é.AttendreSilence.MaxS <= 0 || é.AttendreSilence.SilenceMs <= 0 {
				return fmt.Errorf("étape %d : attendre_silence demande silence_ms et max_s", i+1)
			}
		}
		if é.Touches != "" {
			posées++
			sans := strings.ReplaceAll(é.Touches, PlaceholderCode, "0000")
			if _, err := TouchesValides(sans); err != nil {
				return fmt.Errorf("étape %d : %w", i+1, err)
			}
		}
		if é.PauseMs > 0 {
			posées++
		}
		if é.Enregistrer != nil {
			posées++
			if é.Enregistrer.MaxS <= 0 {
				return fmt.Errorf("étape %d : enregistrer demande max_s", i+1)
			}
		}
		if é.VérifierParole != nil {
			posées++
			if é.VérifierParole.MinS <= 0 {
				return fmt.Errorf("étape %d : verifier_parole demande min_s", i+1)
			}
		}
		if posées != 1 {
			return fmt.Errorf("étape %d : une instruction et une seule", i+1)
		}
	}
	return nil
}

// DemandeCode dit si la recette compose le code de la messagerie.
func (r Recette) DemandeCode() bool {
	for _, é := range r.Étapes {
		if strings.Contains(é.Touches, PlaceholderCode) {
			return true
		}
	}
	return false
}

// Événement marque un instant de la communication.
type Événement struct {
	Ms   int    `json:"ms"`
	Quoi string `json:"quoi"`
}

// Bilan est ce que le moteur rend d'une recette jouée.
type Bilan struct {
	Fichier    string      `json:"fichier,omitempty"`
	DuréeMs    int         `json:"duree_ms"`
	Courbe     []int       `json:"courbe_crete_100ms"`
	Événements []Événement `json:"evenements"`
	Complète   bool        `json:"complete"`
	Erreur     string      `json:"erreur,omitempty"`
}

// Ligne est ce que le moteur demande à la communication en cours.
type Ligne struct {
	Touches func(string) error
	Tient   func() bool
}

// moteur tient l'état commun à toutes les étapes.
type moteur struct {
	ctx      context.Context
	source   io.Reader
	copie    io.Writer
	ligne    Ligne
	bilan    *Bilan
	écoulé   time.Duration
	pic      int
	blocsPas int
	vérifiéÀ time.Duration
	// paroleDepuisTouches cumule la parole entendue depuis la dernière
	// touche : c'est ce que mesure la garde.
	paroleDepuisTouches time.Duration
}

// JouerRecette enchaîne les étapes en lisant la ligne en continu.
//
// Le flux est lu À CHAQUE INSTANT, étape d'attente comme étape de touche :
// laissé sans lecteur, le tuyau de capture se remplit, le processus audio se
// bloque, et le son reçu ensuite arrive en retard ou pas du tout.
func JouerRecette(ctx context.Context, r Recette, source io.Reader, copie io.Writer,
	ligne Ligne, code string) Bilan {

	bilan := Bilan{}
	m := &moteur{ctx: ctx, source: source, copie: copie, ligne: ligne, bilan: &bilan}
	if err := r.Vérifier(); err != nil {
		bilan.Erreur = err.Error()
		return bilan
	}
	if r.DemandeCode() && code == "" {
		bilan.Erreur = "la recette compose le code, et aucun code n'a été fourni"
		return bilan
	}
	for i, é := range r.Étapes {
		if err := m.jouer(i+1, é, code); err != nil {
			bilan.Erreur = err.Error()
			m.noter("arrêt : " + err.Error())
			bilan.DuréeMs = int(m.écoulé / time.Millisecond)
			return bilan
		}
	}
	bilan.Complète = true
	bilan.DuréeMs = int(m.écoulé / time.Millisecond)
	return bilan
}

func (m *moteur) noter(quoi string) {
	m.bilan.Événements = append(m.bilan.Événements,
		Événement{Ms: int(m.écoulé / time.Millisecond), Quoi: quoi})
}

// bloc lit 20 ms, les recopie, et rend leur crête.
func (m *moteur) bloc() (int, error) {
	if err := m.ctx.Err(); err != nil {
		return 0, err
	}
	if m.écoulé >= DuréeMaxRecette {
		return 0, fmt.Errorf("durée maximale d'une recette atteinte (%v)", DuréeMaxRecette)
	}
	tampon := make([]byte, OctetsPCM)
	if _, err := io.ReadFull(m.source, tampon); err != nil {
		return 0, fmt.Errorf("flux audio interrompu : %w", err)
	}
	if m.copie != nil {
		if _, err := m.copie.Write(tampon); err != nil {
			return 0, err
		}
	}
	m.écoulé += DuréeBloc
	niveau := niveauCrête(tampon)
	if niveau > SeuilÉcho {
		m.paroleDepuisTouches += DuréeBloc
	}
	if niveau > m.pic {
		m.pic = niveau
	}
	m.blocsPas++
	if time.Duration(m.blocsPas)*DuréeBloc >= PasCourbe {
		m.bilan.Courbe = append(m.bilan.Courbe, m.pic)
		m.pic, m.blocsPas = 0, 0
	}
	if m.ligne.Tient != nil && m.écoulé-m.vérifiéÀ >= CadenceLigne {
		m.vérifiéÀ = m.écoulé
		if !m.ligne.Tient() {
			return 0, errors.New("la ligne est retombée")
		}
	}
	return niveau, nil
}

func (m *moteur) jouer(n int, é Étape, code string) error {
	switch {
	case é.AttendreSilence != nil:
		return m.attendreSilence(n, *é.AttendreSilence)
	case é.Touches != "":
		touches := strings.ReplaceAll(é.Touches, PlaceholderCode, code)
		// Le journal nomme l'étape, JAMAIS les touches : elles portent le
		// code dès qu'il fait partie de la séquence.
		affichées := é.Touches
		if strings.Contains(affichées, PlaceholderCode) {
			affichées = strings.ReplaceAll(affichées, PlaceholderCode, "<code>")
		}
		m.noter(fmt.Sprintf("étape %d : touches %s", n, affichées))
		if m.ligne.Touches == nil {
			return errors.New("aucun moyen d'envoyer des touches sur cette ligne")
		}
		m.paroleDepuisTouches = 0
		return m.ligne.Touches(touches)
	case é.PauseMs > 0:
		fin := m.écoulé + time.Duration(é.PauseMs)*time.Millisecond
		for m.écoulé < fin {
			if _, err := m.bloc(); err != nil {
				return err
			}
		}
		return nil
	case é.Enregistrer != nil:
		return m.écouter(n, *é.Enregistrer)
	case é.VérifierParole != nil:
		exigé := time.Duration(é.VérifierParole.MinS) * time.Second
		if m.paroleDepuisTouches < exigé {
			return fmt.Errorf("garde de l'étape %d : %.1f s de parole depuis la dernière touche, %d s exigées ; la recette s'arrête sans aller plus loin",
				n, m.paroleDepuisTouches.Seconds(), é.VérifierParole.MinS)
		}
		m.noter(fmt.Sprintf("étape %d : garde franchie (%.1f s de parole)", n, m.paroleDepuisTouches.Seconds()))
		return nil
	}
	return fmt.Errorf("étape %d vide", n)
}

func (m *moteur) attendreSilence(n int, a AttenteSilence) error {
	début := m.écoulé
	silence := time.Duration(a.SilenceMs) * time.Millisecond
	max := time.Duration(a.MaxS) * time.Second
	minimum := time.Duration(a.ParoleMinMs) * time.Millisecond
	if minimum <= 0 {
		minimum = ParoleMinDéfaut
	}
	var calme, parole time.Duration
	for m.écoulé-début < max {
		niveau, err := m.bloc()
		if err != nil {
			return err
		}
		if niveau > SeuilÉcho {
			parole += DuréeBloc
			calme = 0
			continue
		}
		calme += DuréeBloc
		if calme >= silence && (parole >= minimum || !a.ExigerParole) {
			m.noter(fmt.Sprintf("étape %d : silence atteint", n))
			return nil
		}
	}
	m.noter(fmt.Sprintf("étape %d : délai maximal atteint, on continue", n))
	return nil
}

func (m *moteur) écouter(n int, e Écoute) error {
	début := m.écoulé
	max := time.Duration(e.MaxS) * time.Second
	fin := time.Duration(e.SilenceFinS) * time.Second
	m.noter(fmt.Sprintf("étape %d : écoute", n))
	var calme, parole time.Duration
	for m.écoulé-début < max {
		niveau, err := m.bloc()
		if err != nil {
			return err
		}
		if niveau > SeuilÉcho {
			parole += DuréeBloc
			calme = 0
			continue
		}
		calme += DuréeBloc
		if fin > 0 && parole >= ParoleMinDéfaut && calme >= fin {
			m.noter(fmt.Sprintf("étape %d : fin sur silence", n))
			return nil
		}
	}
	m.noter(fmt.Sprintf("étape %d : durée maximale d'écoute", n))
	return nil
}

// SegmentsDeParole résume la courbe en plages où la ligne parlait.
//
// Deux plages séparées par moins de `pont` se fondent : une phrase contient
// des respirations, et les couper en dix morceaux rendrait le repérage
// illisible.
func SegmentsDeParole(courbe []int, pont time.Duration) [][2]int {
	var segments [][2]int
	pas := int(PasCourbe / time.Millisecond)
	for i, niveau := range courbe {
		if niveau <= SeuilÉcho {
			continue
		}
		t := i * pas
		if n := len(segments); n > 0 && t-segments[n-1][1] <= int(pont/time.Millisecond) {
			segments[n-1][1] = t + pas
			continue
		}
		segments = append(segments, [2]int{t, t + pas})
	}
	return segments
}

// lireCode prend le code sur l'entrée standard.
//
// Ni argument, ni variable d'environnement : les deux se lisent par d'autres
// programmes de la même machine, le premier par n'importe qui.
func lireCode(entrée io.Reader) string {
	ligne, _ := bufio.NewReader(entrée).ReadString('\n')
	return strings.TrimSpace(ligne)
}

// RécupérerMessagerie compose un numéro, joue la recette et enregistre tout.
func RécupérerMessagerie(ctx context.Context, o OptionsModem, r Recette,
	fichier string, code string) Bilan {

	bilan := Bilan{Fichier: fichier}
	échec := func(err error) Bilan {
		bilan.Erreur = err.Error()
		return bilan
	}
	if err := r.Vérifier(); err != nil {
		return échec(err)
	}
	norm, err := NuméroValide(o.Numéro)
	if err != nil {
		return échec(err)
	}
	carte, err := carteOuDéfaut(o.Carte)
	if err != nil {
		return échec(err)
	}
	m, err := OuvrirModem(o.Port)
	if err != nil {
		return échec(expliquerPort(err))
	}
	defer m.Close()

	if o.AudMod != ModeAudioInchangé {
		if err := m.RéglerModeAudio(o.AudMod); err != nil {
			slog.Warn("mode audio non réglé", "err", err)
		}
	}
	// Le canal voix AVANT la composition : le modem fige son routage au
	// décroché et refuse la commande ensuite.
	if err := m.OuvrirVoixUSB(o.ModePCM); err != nil {
		return échec(fmt.Errorf("canal voix USB non ouvert : %w", err))
	}
	defer func() { _ = m.FermerVoixUSB() }()

	if err := m.Composer(norm); err != nil {
		return échec(err)
	}
	// Raccrocher QUOI QU'IL ARRIVE : un appel ouvert se facture.
	defer func() {
		if err := m.Raccrocher(); err != nil {
			slog.Warn("raccrochage", "err", err)
		}
	}()
	if _, err := attendreDécroché(ctx, m); err != nil {
		return échec(err)
	}
	if err := m.RéglerRéductionBruit(o.Bruit); err != nil {
		slog.Warn("réduction de bruit refusée", "err", err)
	}
	if err := m.RéaffirmerVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non réaffirmé", "err", err)
	}

	capture := commandePour(ctx, carte, "arecord", "pw-record")
	flux, err := capture.StdoutPipe()
	if err != nil {
		return échec(err)
	}
	plaintes := &PontModem{}
	if err := plaintes.écouterErreurs(capture, "arecord"); err != nil {
		return échec(err)
	}
	if err := capture.Start(); err != nil {
		return échec(fmt.Errorf("arecord sur %s : %w", carte, err))
	}
	defer func() {
		if capture.Process != nil {
			_ = capture.Process.Kill()
		}
	}()

	var copie *os.File
	if fichier != "" {
		copie, err = os.OpenFile(fichier, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
		if err != nil {
			return échec(err)
		}
		defer copie.Close()
		if _, err := copie.Write(entêteWAV(0)); err != nil {
			return échec(err)
		}
	}
	compteur := &compteurÉcriture{w: copie}

	ligne := Ligne{
		Touches: m.EnvoyerTouches,
		Tient: func() bool {
			appels, err := m.Appels()
			return err != nil || uneLigneTient(appels)
		},
	}
	var destination io.Writer
	if copie != nil {
		destination = compteur
	}
	joué := JouerRecette(ctx, r, flux, destination, ligne, code)
	joué.Fichier = fichier
	if copie != nil {
		if _, err := copie.WriteAt(entêteWAV(compteur.n), 0); err != nil && joué.Erreur == "" {
			joué.Erreur = err.Error()
		}
	}
	if joué.Erreur != "" && plaintes.pourquoi() != "" {
		joué.Erreur += plaintes.pourquoi()
	}
	return joué
}

type compteurÉcriture struct {
	w io.Writer
	n int
}

func (c *compteurÉcriture) Write(p []byte) (int, error) {
	n, err := c.w.Write(p)
	c.n += n
	return n, err
}
