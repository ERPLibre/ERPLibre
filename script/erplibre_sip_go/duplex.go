// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
	"math"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sys/unix"
)

// FormatVoix est celui que la carte du modem accepte, et le seul.
//
// « Format: S16_LE, Channels: 1, Rates: 8000 » sur l'EC25-AF. C'est aussi la
// bande passante téléphonique : rien à convertir, et rien de mieux à espérer
// — le réseau ne transporte pas davantage.
const (
	FormatVoix = "S16_LE"
	TauxVoix   = "8000"
	CanauxVoix = "1"

	// Le même débit en nombre, pour les filtres qui en ont besoin.
	TauxVoixHz = 8000.0

	// PériodeVoix et TamponVoix bornent la latence d'ALSA, en trames.
	//
	// INDISPENSABLE : par défaut, arecord et aplay se donnent un demi-seconde
	// de tampon CHACUN. Sur les deux sens, la voix accumule alors près d'une
	// seconde d'aller-retour, et la conversation devient impraticable — on
	// se coupe la parole sans arrêt.
	//
	// Une période de vingt millisecondes, quatre-vingts de tampon : cela
	// ramène le trajet sous le dixième de seconde. Le prix est un risque de
	// craquement si la machine est très chargée, ce qui s'entend moins
	// qu'un délai d'une seconde.
	PériodeVoix = "160" // 20 ms à 8000 Hz
	TamponVoix  = "640" // quatre périodes

	// TailleTuyau borne ce qu'un tuyau du système peut retenir, en octets.
	//
	// Par défaut il en garde soixante-cinq mille, soit QUATRE SECONDES de
	// voix. Ce n'est pas un tampon, c'est un retard : une fois rempli, il ne
	// se vide plus, et tout ce qui passe arrive avec ces quatre secondes.
	// Un décalage qu'aucun réglage d'ALSA ne fait disparaître, puisqu'il est
	// en amont.
	//
	// Une page, le minimum que le noyau accepte, soit un quart de seconde.
	// Plein, notre écriture bloque : la capture prend alors du retard et
	// ALSA jette les échantillons les plus anciens. Perdre un éclat de voix
	// vaut mieux que parler avec quatre secondes de décalage.
	TailleTuyau = 4096
)

// bornerTuyau limite ce qu'un tuyau retient. Sans effet ailleurs que sous
// Linux, où l'échec est sans conséquence : on retombe sur le défaut.
func bornerTuyau(bout any) {
	f, ok := bout.(*os.File)
	if !ok {
		return
	}
	if _, _, err := unix.Syscall(unix.SYS_FCNTL, f.Fd(),
		unix.F_SETPIPE_SZ, uintptr(TailleTuyau)); err != 0 {
		slog.Debug("taille du tuyau inchangée", "err", err)
	}
}

// PréfixePipeWire marque un périphérique servi par le serveur audio du
// bureau plutôt qu'ouvert directement en ALSA.
//
// Sur une machine de bureau, le serveur audio POSSÈDE les cartes et refuse
// l'ouverture directe : viser « hw:2,0 » échoue même quand la carte existe
// et fonctionne. Passer par lui est la seule façon de choisir un de ses
// périphériques — et la seule qui ne le prive pas de sa carte.
//
// La carte du modem fait exception : une règle la lui soustrait, et elle
// s'ouvre donc en ALSA direct.
const PréfixePipeWire = "pw:"

// LatencePipeWire borne le tampon du serveur audio, qui se donne cent
// millisecondes par défaut — de quoi doubler le trajet de la voix.
const LatencePipeWire = "20ms"

// argsALSA rend les arguments communs à arecord et aplay.
//
// Rassemblés en un seul endroit : quatre listes séparées finissaient par
// diverger, et un sens réglé plus large que l'autre ramène à lui seul tout
// le délai qu'on cherche à supprimer.
func argsALSA(périphérique string) []string {
	args := []string{
		"-f", FormatVoix, "-r", TauxVoix, "-c", CanauxVoix,
		"--period-size", PériodeVoix, "--buffer-size", TamponVoix,
		"-q", "-",
	}
	if périphérique != "" {
		args = append([]string{"-D", périphérique}, args...)
	}
	return args
}

// argsPipeWire rend les arguments de pw-record et pw-play pour une cible.
func argsPipeWire(cible string) []string {
	return []string{
		"--target", cible,
		"--rate", TauxVoix, "--channels", CanauxVoix, "--format", "s16",
		"--latency", LatencePipeWire, "--raw", "-",
	}
}

// commandePour choisit l'outil selon le périphérique demandé.
//
// alsa et pipewire nomment les deux programmes équivalents : arecord ou
// aplay pour l'accès direct, pw-record ou pw-play pour le serveur.
func commandePour(ctx context.Context, périphérique, alsa, pipewire string) *exec.Cmd {
	if cible, ok := strings.CutPrefix(périphérique, PréfixePipeWire); ok {
		return exec.CommandContext(ctx, pipewire, argsPipeWire(cible)...)
	}
	return exec.CommandContext(ctx, alsa, argsALSA(périphérique)...)
}

const (
	// TailleBloc est la quantité d'octets relayée d'un coup : 20 ms de voix,
	// à 8000 échantillons de deux octets par seconde. Plus gros ajoute un
	// retard perceptible dans une conversation, plus petit réveille le
	// processus pour rien.
	TailleBloc = 320

	// DuréeBloc est le temps que représente TailleBloc. Cadence le silence
	// quand aucune capture ne le fait à notre place.
	DuréeBloc = 20 * time.Millisecond

	// GainNeutre est le volume qui ne change rien, en pour cent.
	GainNeutre = 100

	// VolumeModemInconnu marque un volume jamais posé, à distinguer d'un
	// volume réglé à zéro.
	VolumeModemInconnu = -1

	// ReposAprèsÉchec sépare deux tentatives sur un périphérique qui refuse
	// de s'ouvrir. Sans lui, la boucle relance un processus par tour et en
	// crée des dizaines par seconde.
	ReposAprèsÉchec = 500 * time.Millisecond

	// GainMax borne l'amplification logicielle.
	//
	// Élevé À DESSEIN, mais c'est un dernier recours : le gain logiciel
	// multiplie le bruit de fond autant que la voix. Un correspondant trop
	// faible se règle d'abord par AT+CLVL, qui amplifie DANS le modem, avant
	// que le souffle ne s'ajoute.
	GainMax = 1000

	// SeuilÉcho est le niveau au-dessus duquel on considère que le
	// correspondant parle.
	SeuilÉcho = 600

	// RapportNiveau espace les relevés de niveau dans le journal.
	//
	// Un relevé PÉRIODIQUE du maximum, et non une annonce au premier bloc
	// qui dépasse un seuil : le périphérique USB rend du rebut à
	// l'ouverture, et l'annoncer une fois faisait passer ce rebut pour du
	// son. Mesuré : niveau 6039 annoncé sur une carte dont la capture
	// brute rendait zéro exact.
	RapportNiveau = 5 * time.Second

	// ÉtablissementFlux écarte les premiers blocs, ceux du rebut.
	ÉtablissementFlux = 300 * time.Millisecond

	// AtténuationÉcho est ce qu'il reste du micro pendant qu'il parle, en
	// pour cent. Refermer complètement couperait les acquiescements et
	// donnerait une conversation en talkie-walkie.
	AtténuationÉcho = 15
)

// Combiné relie le micro et les haut-parleurs de la machine à l'appel.
//
// Deux flux indépendants, et c'est ce qui en fait un vrai téléphone plutôt
// qu'un diffuseur : le micro va VERS le correspondant, sa voix REVIENT vers
// les haut-parleurs. La carte du modem expose les deux sens, ce que le
// téléphone Android ne permet pas — chez lui le flux montant appartient au
// modem, hors d'atteinte.
//
// Les octets transitent PAR ce programme au lieu d'un tuyau entre deux
// commandes. Cela coûte une recopie et rend possibles le gain, la mesure de
// niveau, le changement de périphérique en cours d'appel, et une fermeture
// qui n'oublie personne.
//
// Aucun traitement d'écho. Haut-parleurs ouverts près du micro, le
// correspondant s'entend revenir : un casque supprime la cause, ce qui vaut
// mieux qu'un filtre approximatif.
type Combiné struct {
	carte string

	mutex sync.Mutex
	procs []*exec.Cmd

	// micOuvert commande la CAPTURE du micro. Fermé, aucune capture n'a
	// lieu : le micro est rendu au système, ce qu'un voyant de portable
	// reflète. Couper seulement en aval le laisse allumé pour qui regarde,
	// et « fermé » devient un mensonge.
	//
	// La carte du modem reçoit tout de même du silence : elle attend un flux
	// régulier, et l'en priver produit des ratés à la reprise.
	micOuvert atomic.Bool

	// hpOuvert commande l'écoute. Fermé, la carte du modem n'est plus captée
	// du tout, donc rien n'arrive aux haut-parleurs.
	hpOuvert atomic.Bool

	// filtreMicro allume le passe-haut et la porte de bruit. Allumé par
	// défaut : un micro de portable envoie sinon son ventilateur en
	// permanence, et le correspondant l'entend plus que la voix.
	filtreMicro atomic.Bool

	// sonnerie fait entendre l'appel qui se présente, sur la sortie locale.
	sonnerie atomic.Bool

	// antiÉcho referme le micro pendant que le correspondant parle.
	//
	// Ce n'est PAS une annulation d'écho : celle-ci soustrait le signal
	// connu du signal capté, ce qui demande un traitement dont on ne dispose
	// pas ici. C'est une atténuation à l'alternat, qui empêche les
	// haut-parleurs de repartir dans le micro au prix d'un demi-duplex. Un
	// casque reste supérieur, puisqu'il supprime la cause.
	antiÉcho atomic.Bool

	// Trois accès au modem, tous optionnels : l'essai audio n'ouvre aucun
	// port, et l'interface doit alors se contenter de ce qu'elle a.
	//
	// Signal rend la puissance reçue. VolumeModem monte le volume DANS le
	// modem, ce qui vaut mieux qu'un gain logiciel. BruitModem rallume la
	// suppression de bruit que AT+QAUDMOD=3 a éteinte.
	Signal          func() (int, string)
	VolumeModem     func(int) error
	BruitModem      func(bool) error
	GainMicroModem  func(int) error
	GainÉcouteModem func(int) error

	// Trois gestes de conférence, tous portés par le réseau : compter les
	// appels, en composer un second, et les réunir.
	AppelsVoix func() int
	Composer   func(string) error
	Fusionner  func() error
	Attente    func() error

	// Touches envoie des tonalités DTMF pendant l'appel. Une messagerie
	// d'opérateur se pilote ainsi — mot de passe, « 1 pour écouter » — et
	// sans elles on entend l'accueil sans pouvoir aller plus loin.
	Touches func(string) error

	// AppelEntrant rend le numéro qui sonne, vide sinon. Répondre décroche.
	// Absents hors du mode veille : un appel sortant n'a personne à prendre.
	AppelEntrant func() string
	Répondre     func() error

	// RéaffirmerVoix rouvre le canal voix USB. Toucher au traitement du
	// signal le rompt : le son disparaît des deux côtés et ne revient
	// qu'en raccrochant. La séquence qui l'ouvre au décroché le rétablit,
	// ce qui évite de recomposer.
	RéaffirmerVoix func() error

	// Dernières valeurs posées dans le modem, pour les afficher : le module
	// ne les republie pas, et les relire à chaque tour encombrerait le port
	// AT pendant que la voix passe.
	volumeModem     atomic.Int64
	bruitModem      atomic.Bool
	gainMicroModem  atomic.Int64
	gainÉcouteModem atomic.Int64

	// Gains en pour cent appliqués aux échantillons. 100 ne change rien.
	gainMic atomic.Int64
	gainHP  atomic.Int64

	// Périphériques ALSA choisis, vide pour celui du système. Un changement
	// s'applique au vol : le flux concerné se referme et rouvre ailleurs.
	périphMic atomic.Value
	périphHP  atomic.Value

	// Niveaux courants, en valeur efficace sur seize bits signés. Ils
	// distinguent un chemin mort d'un correspondant muet, là où « je
	// n'entends rien » ne dit pas lequel des deux. Un sens fermé retombe à
	// zéro : il n'y a plus rien à mesurer.
	niveauMic atomic.Int64
	niveauHP  atomic.Int64

	// Fini se ferme quand un des deux sens s'arrête pour de bon.
	Fini chan struct{}

	une     sync.Once
	uneFini sync.Once
}

// ouvreurCapture démarre une capture et rend de quoi la lire et l'arrêter.
//
// Passé en paramètre plutôt qu'appelé directement : la bascule et le gain se
// vérifient alors sans carte son ni processus.
type ouvreurCapture func(ctx context.Context, périphérique string) (io.ReadCloser, func(), error)

// NouveauCombiné prépare un combiné sans rien démarrer.
func NouveauCombiné(carte string) *Combiné {
	c := &Combiné{carte: carte, Fini: make(chan struct{})}
	c.gainMic.Store(GainNeutre)
	c.gainHP.Store(GainNeutre)
	// Négatif tant que rien n'a été posé : sans quoi l'affichage annonce un
	// volume de zéro là où il n'y a simplement pas de modem à interroger.
	c.volumeModem.Store(VolumeModemInconnu)
	c.gainMicroModem.Store(VolumeModemInconnu)
	c.gainÉcouteModem.Store(VolumeModemInconnu)
	c.périphMic.Store("")
	c.périphHP.Store("")
	c.hpOuvert.Store(true)
	c.filtreMicro.Store(true)
	c.sonnerie.Store(true)
	// L'anti-écho est allumé par défaut : sans casque, les haut-parleurs
	// repartent dans le micro et le correspondant s'entend revenir. Le
	// demi-duplex qu'il coûte se remarque moins que l'écho qu'il évite.
	c.antiÉcho.Store(true)
	return c
}

// MicOuvert dit si la voix locale part vers le correspondant.
func (c *Combiné) MicOuvert() bool { return c.micOuvert.Load() }

// HPOuvert dit si la voix du correspondant sort des haut-parleurs.
func (c *Combiné) HPOuvert() bool { return c.hpOuvert.Load() }

// BasculerMic ouvre ou ferme le micro et rend le nouvel état.
func (c *Combiné) BasculerMic() bool {
	n := !c.micOuvert.Load()
	c.micOuvert.Store(n)
	return n
}

// VolumeModem rend le dernier cran d'écoute posé dans le modem.
func (c *Combiné) VolumeModemPosé() int { return int(c.volumeModem.Load()) }

// BruitModemActif dit si la suppression de bruit du modem est allumée.
func (c *Combiné) BruitModemActif() bool { return c.bruitModem.Load() }

// poserRéglageAudioModem applique un réglage et rétablit le canal voix.
//
// TOUT réglage audio du module rompt le canal voix USB : le son disparaît
// des deux côtés et ne revient qu'en recomposant. Constaté sur le filtre de
// bruit, puis sur le gain de montée — il n'y a aucune raison de croire les
// autres épargnés, d'où un passage OBLIGÉ par ici.
//
// La séquence qui ouvre le canal au décroché le rétablit, ce qui rend le
// réglage possible en pleine conversation.
func (c *Combiné) poserRéglageAudioModem(appliquer func() error) error {
	if err := appliquer(); err != nil {
		return err
	}
	if c.RéaffirmerVoix == nil {
		return nil
	}
	if err := c.RéaffirmerVoix(); err != nil {
		slog.Warn("canal voix non rétabli après un réglage", "err", err)
		return err
	}
	return nil
}

// PoserVolumeModem transmet le cran au modem et le retient pour l'affichage.
func (c *Combiné) PoserVolumeModem(cran int) error {
	if c.VolumeModem == nil {
		return nil
	}
	if err := c.poserRéglageAudioModem(func() error {
		return c.VolumeModem(cran)
	}); err != nil {
		return err
	}
	c.volumeModem.Store(int64(cran))
	return nil
}

// lireRéglagesModem relève les réglages que le modem porte DÉJÀ.
//
// Ils persistent d'un appel à l'autre : un volume d'écoute laissé au plus
// bas par un réglage précédent rend la ligne quasi muette, et l'afficher
// comme inconnu fait chercher la panne dans le logiciel — ce qui coûte des
// heures.
func (c *Combiné) lireRéglagesModem(m *Modem) {
	if v, err := m.LireVolumeÉcoute(); err == nil {
		c.volumeModem.Store(int64(v))
		if v <= VolumeÉcouteBas {
			// Un cran laissé au plus bas ressemble EXACTEMENT à une panne :
			// la ligne est établie, les flux tournent, et l'on n'entend
			// rien. Le dire au début de l'appel, pas après.
			slog.Warn("volume d'écoute du modem très bas, on n'entendra presque rien",
				"cran", v, "maximum", VolumeÉcouteMax)
		}
	} else {
		slog.Warn("volume d'écoute illisible", "err", err)
	}
	if g, err := m.LireGainMicroModem(); err == nil {
		c.gainMicroModem.Store(int64(g))
	} else {
		slog.Warn("gain de montée illisible", "err", err)
	}
	if g, err := m.LireGainÉcouteModem(); err == nil {
		c.gainÉcouteModem.Store(int64(g))
	} else {
		slog.Warn("gain de descente illisible", "err", err)
	}
}

// GainMicroModemPosé rend le dernier gain de montée posé, ou -1.
func (c *Combiné) GainMicroModemPosé() int {
	return int(c.gainMicroModem.Load())
}

// PoserGainMicroModem transmet le gain de montée au modem.
func (c *Combiné) PoserGainMicroModem(gain int) error {
	if c.GainMicroModem == nil {
		return nil
	}
	if err := c.poserRéglageAudioModem(func() error {
		return c.GainMicroModem(gain)
	}); err != nil {
		return err
	}
	c.gainMicroModem.Store(int64(gain))
	return nil
}

// GainÉcouteModemPosé rend le dernier gain de descente posé, ou -1.
func (c *Combiné) GainÉcouteModemPosé() int {
	return int(c.gainÉcouteModem.Load())
}

// PoserGainÉcouteModem transmet le gain de descente au modem.
func (c *Combiné) PoserGainÉcouteModem(gain int) error {
	if c.GainÉcouteModem == nil {
		return nil
	}
	if err := c.poserRéglageAudioModem(func() error {
		return c.GainÉcouteModem(gain)
	}); err != nil {
		return err
	}
	c.gainÉcouteModem.Store(int64(gain))
	return nil
}

// PoserBruitModem allume ou éteint la suppression de bruit du modem.
func (c *Combiné) PoserBruitModem(actif bool) error {
	if c.BruitModem == nil {
		return nil
	}
	if err := c.poserRéglageAudioModem(func() error {
		return c.BruitModem(actif)
	}); err != nil {
		return err
	}
	c.bruitModem.Store(actif)
	return nil
}

// AntiÉcho dit si le micro se referme pendant que l'autre parle.
func (c *Combiné) AntiÉcho() bool { return c.antiÉcho.Load() }

// BasculerAntiÉcho inverse l'atténuation à l'alternat et rend le nouvel état.
func (c *Combiné) BasculerAntiÉcho() bool {
	n := !c.antiÉcho.Load()
	c.antiÉcho.Store(n)
	return n
}

// FiltreMicro dit si le passe-haut et la porte de bruit sont allumés.
func (c *Combiné) FiltreMicro() bool { return c.filtreMicro.Load() }

// BasculerFiltreMicro inverse le nettoyage du micro et rend le nouvel état.
func (c *Combiné) BasculerFiltreMicro() bool {
	n := !c.filtreMicro.Load()
	c.filtreMicro.Store(n)
	return n
}

// BasculerHP ouvre ou ferme les haut-parleurs et rend le nouvel état.
func (c *Combiné) BasculerHP() bool {
	n := !c.hpOuvert.Load()
	c.hpOuvert.Store(n)
	return n
}

// Gains rend le gain du micro puis celui des haut-parleurs, en pour cent.
func (c *Combiné) Gains() (int, int) {
	return int(c.gainMic.Load()), int(c.gainHP.Load())
}

// RéglerGainMic borne puis applique le gain du micro. Rend la valeur retenue.
func (c *Combiné) RéglerGainMic(pourCent int) int {
	v := bornerGain(pourCent)
	c.gainMic.Store(int64(v))
	return v
}

// RéglerGainHP borne puis applique le gain d'écoute. Rend la valeur retenue.
func (c *Combiné) RéglerGainHP(pourCent int) int {
	v := bornerGain(pourCent)
	c.gainHP.Store(int64(v))
	return v
}

func bornerGain(v int) int {
	if v < 0 {
		return 0
	}
	if v > GainMax {
		return GainMax
	}
	return v
}

// Périphériques rend celui du micro puis celui des haut-parleurs.
func (c *Combiné) Périphériques() (string, string) {
	m, _ := c.périphMic.Load().(string)
	h, _ := c.périphHP.Load().(string)
	return m, h
}

// ChoisirMicro change la source captée. Vide remet celle du système.
func (c *Combiné) ChoisirMicro(périphérique string) {
	c.périphMic.Store(périphérique)
}

// ChoisirSortie change la destination écoutée. Vide remet celle du système.
func (c *Combiné) ChoisirSortie(périphérique string) {
	c.périphHP.Store(périphérique)
}

// Niveaux rend le niveau du micro puis celui du correspondant.
func (c *Combiné) Niveaux() (int, int) {
	return int(c.niveauMic.Load()), int(c.niveauHP.Load())
}

// OuvrirCombiné démarre les deux sens.
//
// L'appel doit être DÉJÀ décroché : écrire dans la carte avant que la
// liaison montante existe ne va nulle part. micOuvert donne l'état initial
// du micro ; fermé, on entend le correspondant sans être entendu.
func OuvrirCombiné(ctx context.Context, carte string, micOuvert bool) (*Combiné, error) {
	résolue, err := carteOuDéfaut(carte)
	if err != nil {
		return nil, err
	}
	c := NouveauCombiné(résolue)
	if err := c.Démarrer(ctx, micOuvert); err != nil {
		c.Fermer()
		return nil, err
	}
	return c, nil
}

// Démarrer ouvre les flux audio. À appeler UNE fois, et seulement quand la
// voix est établie.
//
// Séparé de la construction parce que l'instant compte : réaffirmer le
// routage voix du modem ferme et rouvre son périphérique USB, ce qui tue
// tout flux ALSA déjà ouvert dessus. Les réglages du modem doivent donc
// tous être posés AVANT que les flux ne démarrent.
func (c *Combiné) Démarrer(ctx context.Context, micOuvert bool) error {
	carte := c.carte
	c.micOuvert.Store(micOuvert)

	// Montée : micro de la machine → carte du modem.
	go func() {
		c.pomperVersLigne(ctx, carte)
		c.finir("micro vers la ligne")
	}()

	// Descente : carte du modem → haut-parleurs.
	go func() {
		c.pomperVersSortie(ctx, carte)
		c.finir("ligne vers les haut-parleurs")
	}()

	slog.Info("combiné ouvert", "carte", carte, "micro", micOuvert)
	return nil
}

func (c *Combiné) finir(quoi string) {
	c.uneFini.Do(func() { close(c.Fini) })
	slog.Info("flux audio terminé", "sens", quoi)
}

// démarrerLecture ouvre un aplay et rend de quoi l'alimenter.
func (c *Combiné) démarrerLecture(ctx context.Context, périphérique, quoi string) (
	*exec.Cmd, io.WriteCloser, error) {
	cmd := commandePour(ctx, périphérique, "aplay", "pw-play")
	entrée, err := cmd.StdinPipe()
	if err != nil {
		return nil, nil, fmt.Errorf("%s : %w", quoi, err)
	}
	bornerTuyau(entrée)
	if err := cmd.Start(); err != nil {
		return nil, nil, fmt.Errorf("%s : %w", quoi, err)
	}
	c.mutex.Lock()
	c.procs = append(c.procs, cmd)
	c.mutex.Unlock()
	// Sur QUOI l'on joue, dit une fois par ouverture. Sans cela, un son qui
	// part vers une sortie muette — un port vidéo, un périphérique
	// débranché — se lit exactement comme un son qui ne part pas.
	slog.Info("lecture ouverte", "sens", quoi,
		"peripherique", nomLisible(périphérique))
	return cmd, entrée, nil
}

// nomLisible rend un nom de périphérique affichable.
//
// Le vide est le cas le plus fréquent et le plus trompeur : il ne veut pas
// dire « aucun » mais « celui du système », et le lire comme une absence
// fait chercher une panne là où il n'y en a pas.
func nomLisible(périphérique string) string {
	if périphérique == "" {
		return "(systeme)"
	}
	return périphérique
}

// captureALSA démarre un arecord sur le périphérique demandé.
func captureALSA(ctx context.Context, périphérique string) (io.ReadCloser, func(), error) {
	cmd := commandePour(ctx, périphérique, "arecord", "pw-record")
	flux, err := cmd.StdoutPipe()
	if err != nil {
		return nil, nil, err
	}
	bornerTuyau(flux)
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}
	arrêt := func() {
		if cmd.Process != nil {
			_ = cmd.Process.Kill()
		}
		_ = cmd.Wait()
	}
	return flux, arrêt, nil
}

// pomper alimente une destination depuis une capture qu'il ouvre et ferme.
//
// Cœur du combiné, et le seul endroit où fermer un sens a un effet RÉEL :
// aucune capture n'existe alors, donc le périphérique est rendu au système.
// La destination reçoit tout de même du silence à la bonne cadence, faute de
// quoi la carte du modem hoquette à la reprise.
// repliPossible autorise le retour au périphérique du système quand celui
// qu'on vise refuse de s'ouvrir. Il vaut faux pour la DESCENTE, dont la
// source est la carte du modem et rien d'autre : y substituer le
// périphérique du système ferait écouter le micro de la machine à la place
// de la ligne, ce qui s'entend comme un écho et non comme une panne.
//
// traiter peut être nil ; sinon il nettoie chaque bloc EN PLACE et rend le
// niveau utile du signal — celui de la voix, mesuré avant que la porte de
// bruit ne la referme, sans quoi l'indicateur retomberait à zéro entre les
// mots.
func (c *Combiné) pomper(ctx context.Context, dst io.WriteCloser,
	ouvrir ouvreurCapture, ouvert *atomic.Bool, périph *atomic.Value,
	gain, niveau *atomic.Int64, quoi string, traiter func([]byte) int,
	repliPossible bool) {
	defer dst.Close()
	silence := make([]byte, TailleBloc)
	bloc := make([]byte, TailleBloc)

	var source io.ReadCloser
	var arrêt func()
	var périphOuvert string
	var ouvertÀ time.Time
	// Instant de la bascule, pour dater la reprise du son. Un changement de
	// périphérique qui coûte plusieurs secondes ne se voit pas autrement :
	// on entend un trou, sans savoir s'il vient de l'ouverture, de la
	// fermeture, ou d'un tampon qui se vide.
	var basculeÀ time.Time
	// Deux jalons, une seule fois chacun : l'ouverture du flux, et le
	// premier son qui y passe. Leur absence dit OU la chaîne s'arrête —
	// jamais ouverte, ou ouverte et muette — ce qu'aucune trace ne disait.
	annoncéOuvert := false
	maxNiveau := 0
	dernierRapport := time.Now()
	fermer := func() {
		if arrêt != nil {
			arrêt()
			arrêt, source = nil, nil
		}
		niveau.Store(0)
	}
	defer fermer()

	rythme := time.NewTicker(DuréeBloc)
	defer rythme.Stop()

	for {
		if ctx.Err() != nil {
			return
		}
		voulu, _ := périph.Load().(string)
		if source != nil && voulu != périphOuvert {
			basculeÀ = time.Now()
			fermer()
		}
		if !ouvert.Load() {
			fermer()
			select {
			case <-ctx.Done():
				return
			case <-rythme.C:
			}
			if _, err := dst.Write(silence); err != nil {
				return
			}
			continue
		}
		if source == nil {
			f, a, err := ouvrir(ctx, voulu)
			if err != nil {
				slog.Warn("capture impossible", "sens", quoi,
					"peripherique", voulu, "err", err)
				if repliPossible && voulu != "" {
					// RETOUR au périphérique du système plutôt que silence :
					// un serveur audio de bureau possède les cartes de la
					// machine et refuse l'ouverture directe. Couper le sens
					// laisserait croire à une panne du micro.
					slog.Info("retour au périphérique du système", "sens", quoi)
					périph.Store("")
					continue
				}
				// Plus rien à substituer : on RÉESSAIE le même, après un
				// repos. La carte du modem s'absente quelques instants
				// quand son canal voix se rouvre, et abandonner là
				// laisserait l'appel sourd pour de bon.
				slog.Info("nouvel essai après un repos", "sens", quoi,
					"peripherique", voulu)
				select {
				case <-ctx.Done():
					return
				case <-time.After(ReposAprèsÉchec):
				}
				continue
			}
			source, arrêt, périphOuvert, ouvertÀ = f, a, voulu, time.Now()
			if !annoncéOuvert {
				annoncéOuvert = true
				slog.Info("capture ouverte", "sens", quoi,
					"peripherique", nomLisible(voulu))
			}
			if !basculeÀ.IsZero() {
				slog.Info("périphérique change", "sens", quoi,
					"vers", voulu, "trou_ms", time.Since(basculeÀ).Milliseconds())
				basculeÀ = time.Time{}
			}
		}
		n, err := io.ReadFull(source, bloc)
		if n > 0 {
			appliquerGain(bloc[:n], int(gain.Load()))
			if time.Since(ouvertÀ) > ÉtablissementFlux {
				if v := valeurEfficace(bloc[:n]); v > maxNiveau {
					maxNiveau = v
				}
			}
			if time.Since(dernierRapport) >= RapportNiveau {
				slog.Info("niveau", "sens", quoi, "max", maxNiveau,
					"peripherique", nomLisible(périphOuvert))
				maxNiveau = 0
				dernierRapport = time.Now()
			}
			if traiter != nil {
				niveau.Store(int64(traiter(bloc[:n])))
			} else {
				niveau.Store(int64(valeurEfficace(bloc[:n])))
			}
			if _, e := dst.Write(bloc[:n]); e != nil {
				return
			}
		}
		if err != nil {
			// Une capture qui meurt AUSSITÔT signale un périphérique que le
			// système ne rend pas : le processus démarre, puis rend la main
			// à la première lecture. L'échec n'apparaît donc pas à
			// l'ouverture, et sans ce garde-fou la boucle le relance
			// indéfiniment — micro muet, sans rien dans les traces.
			jeune := time.Since(ouvertÀ) < ReposAprèsÉchec
			fermer()
			if jeune && repliPossible && voulu != "" {
				slog.Warn("périphérique refusé par le système, retour au défaut",
					"sens", quoi, "peripherique", voulu)
				périph.Store("")
			} else if jeune {
				select {
				case <-ctx.Done():
					return
				case <-time.After(ReposAprèsÉchec):
				}
			}
		}
	}
}

// pomperVersLigne relaie le micro vers la carte du modem, et REPART si le
// flux meurt.
//
// Repartir n'est pas du zèle : tout réglage audio du modem ferme et rouvre
// son périphérique USB, ce qui tue l'écriture en cours. Sans reprise, un
// simple changement de volume en pleine conversation coupait la parole pour
// de bon et terminait l'appel.
func (c *Combiné) pomperVersLigne(ctx context.Context, carte string) {
	// Le traitement vit ici et nulle part ailleurs : ses filtres gardent une
	// mémoire d'un échantillon à l'autre, que deux appelants rendraient
	// incohérente. Il survit aux reprises, ce qui évite de réapprendre le
	// bruit de fond à chaque fois.
	nettoyage := NouveauTraitement(TauxVoixHz)
	for {
		if ctx.Err() != nil {
			return
		}
		ctxLigne, arrêter := context.WithCancel(ctx)
		_, entrée, err := c.démarrerLecture(ctxLigne, carte, "micro vers la ligne")
		if err != nil {
			arrêter()
			slog.Warn("écriture vers la ligne impossible", "err", err)
			return
		}
		début := time.Now()
		c.pomper(ctxLigne, entrée, captureALSA, &c.micOuvert, &c.périphMic,
			&c.gainMic, &c.niveauMic, "micro vers la ligne",
			func(bloc []byte) int {
				return nettoyage.Appliquer(bloc, int(c.niveauHP.Load()),
					c.filtreMicro.Load(), c.antiÉcho.Load())
			}, true)
		arrêter()
		if ctx.Err() != nil {
			return
		}
		if time.Since(début) < ReposAprèsÉchec {
			select {
			case <-ctx.Done():
				return
			case <-time.After(ReposAprèsÉchec):
			}
		}
		slog.Info("reprise du flux vers la ligne")
	}
}

// pomperVersSortie relaie la carte du modem vers les haut-parleurs.
//
// À part du sens montant parce que c'est la LECTURE qui change ici quand on
// choisit une autre sortie : il faut refermer l'aplay et en rouvrir un
// ailleurs, là où l'autre sens ne refait que sa capture.
func (c *Combiné) pomperVersSortie(ctx context.Context, carte string) {
	for {
		if ctx.Err() != nil {
			return
		}
		voulu, _ := c.périphHP.Load().(string)
		// La lecture naît et meurt avec CE contexte-ci, et non celui de
		// l'appel : rattachée au second, elle survivrait au changement de
		// sortie et garderait l'ancien périphérique ouvert, que le système
		// refuserait alors au suivant.
		ctxSortie, arrêter := context.WithCancel(ctx)
		_, entrée, err := c.démarrerLecture(ctxSortie, voulu,
			"ligne vers les haut-parleurs")
		if err != nil {
			arrêter()
			slog.Warn("sortie impossible", "peripherique", voulu, "err", err)
			if voulu == "" {
				return
			}
			c.périphHP.Store("")
			continue
		}
		reprise := time.Now()
		c.surveillerSortie(ctxSortie, arrêter, voulu)
		fixe := &atomic.Value{}
		// La capture vise TOUJOURS la carte du modem : c'est la sortie qui
		// bouge, pas la source.
		fixe.Store(carte)
		c.pomper(ctxSortie, entrée, captureALSA, &c.hpOuvert, fixe,
			&c.gainHP, &c.niveauHP, "ligne vers les haut-parleurs", nil,
			false)
		arrêter()
		début := reprise
		// Un flux qui meurt AUSSITÔT signale une sortie que le système
		// refuse : « aplay » démarre, puis rend la main sur la première
		// écriture. Sans ce garde-fou, la boucle en relance sept par
		// seconde, et rien dans les traces ne dit pourquoi.
		if time.Since(début) < ReposAprèsÉchec && voulu != "" {
			slog.Warn("sortie refusée par le système, retour au défaut",
				"peripherique", voulu)
			c.périphHP.Store("")
		}
	}
}

// surveillerSortie arrête le flux dès que la sortie demandée change.
func (c *Combiné) surveillerSortie(ctx context.Context,
	arrêter context.CancelFunc, ouverte string) {
	go func() {
		veille := time.NewTicker(DuréeBloc * 5)
		defer veille.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-veille.C:
				if v, _ := c.périphHP.Load().(string); v != ouverte {
					arrêter()
					return
				}
			}
		}
	}()
}

// appliquerGain multiplie les échantillons en SATURANT plutôt qu'en
// débordant : un dépassement d'entier ferait claquer un son fort en son
// inversé, ce qui s'entend bien pire qu'une saturation.
func appliquerGain(bloc []byte, pourCent int) {
	if pourCent == GainNeutre {
		return
	}
	for i := 0; i+1 < len(bloc); i += 2 {
		v := int32(int16(binary.LittleEndian.Uint16(bloc[i:])))
		v = v * int32(pourCent) / 100
		if v > math.MaxInt16 {
			v = math.MaxInt16
		} else if v < math.MinInt16 {
			v = math.MinInt16
		}
		binary.LittleEndian.PutUint16(bloc[i:], uint16(int16(v)))
	}
}

// valeurEfficace rend l'énergie moyenne d'un bloc d'échantillons 16 bits.
func valeurEfficace(bloc []byte) int {
	n := len(bloc) / 2
	if n == 0 {
		return 0
	}
	var somme float64
	for i := 0; i < n; i++ {
		é := float64(int16(binary.LittleEndian.Uint16(bloc[i*2:])))
		somme += é * é
	}
	return int(math.Sqrt(somme / float64(n)))
}

// Fermer coupe les deux sens.
//
// Idempotent, et appelé aussi bien depuis un `defer` que depuis le chemin
// d'erreur. Tue TOUS les processus démarrés : n'en oublier qu'un laisse la
// carte du modem occupée, et l'appel suivant échoue sur « périphérique
// occupé » sans que rien n'explique pourquoi.
func (c *Combiné) Fermer() {
	c.une.Do(func() {
		c.mutex.Lock()
		procs := append([]*exec.Cmd(nil), c.procs...)
		c.mutex.Unlock()
		for _, p := range procs {
			if p != nil && p.Process != nil {
				_ = p.Process.Kill()
				_ = p.Wait()
			}
		}
		c.uneFini.Do(func() { close(c.Fini) })
	})
}
