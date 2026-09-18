// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"
)

// PortDéfaut est le lien stable posé par la règle udev.
//
// Un lien et non /dev/ttyUSB3 : le numéro change au rebranchement, et un
// service qui vise un numéro finit par parler au mauvais port — ou au GPS.
const PortDéfaut = "/dev/erplibre-modem-at"

// Modem parle au modem par son port AT réservé.
//
// Réservé, et c'est tout l'intérêt : ModemManager garde son port primaire et
// continue de fournir l'état de la SIM, l'opérateur et les SMS PENDANT qu'on
// place un appel. Sans la règle udev, chaque commande exigeait de l'arrêter,
// ce qui coupait la connexion de données.
type Modem struct {
	f  *os.File
	br *bufio.Reader

	// Un dialogue AT à la fois. Le port est une ressource unique : deux
	// commandes lancées en parallèle entrelacent leurs octets, et chacune
	// lit la réponse de l'autre. Le symptôme ne ressemble pas à la cause —
	// un +CLCC corrompu se lit comme une ligne qui a raccroché, et l'appel
	// se termine tout seul.
	parole sync.Mutex

	// Une CONVERSATION à la fois, ce qui n'est pas la même chose qu'une
	// commande à la fois. La SIM ne porte qu'un appel voix ; deux chemins
	// s'en servent — la veille des entrants et la composition sortante — et
	// rien ne les arbitrait. Le raccrochage du premier tombait alors sur le
	// second, qui perdait sa ligne quelques secondes après l'avoir prise,
	// sans qu'aucune erreur ne le dise.
	ligne sync.Mutex
}

// PrendreLaLigne réserve l'unique conversation de la SIM.
//
// Rend faux quand elle est déjà tenue, plutôt que d'attendre : un appel qu'on
// ne peut pas passer se refuse tout de suite, une attente muette laissant
// sonner un correspondant que personne ne prendra.
func (m *Modem) PrendreLaLigne() bool { return m.ligne.TryLock() }

// RendreLaLigne libère la conversation. À n'appeler qu'après avoir raccroché.
func (m *Modem) RendreLaLigne() { m.ligne.Unlock() }

// OuvrirModem ouvre le port en mode BRUT.
//
// Le mode brut est indispensable : la discipline de ligne par défaut
// traduirait les retours chariot et avalerait des caractères, ce qui casse
// le dialogue AT de façon déroutante — des réponses tronquées plutôt qu'une
// erreur franche.
//
// On ne touche PAS au débit. Sur un port série virtuel USB il n'a aucun
// effet : `stty 115200` échoue, le port reste à 9600, et le dialogue
// fonctionne quand même. Mesuré sur cet appareil.
func OuvrirModem(chemin string) (*Modem, error) {
	if chemin == "" {
		chemin = PortDéfaut
	}
	f, err := os.OpenFile(chemin, os.O_RDWR|unix.O_NOCTTY, 0)
	if err != nil {
		return nil, fmt.Errorf("port %s : %w", chemin, err)
	}
	fd := int(f.Fd())

	// UN SEUL lecteur à la fois sur ce port, et le noyau l'arbitre.
	//
	// Un port série s'ouvre autant de fois qu'on veut, sans que rien ne le
	// signale : deux processus entrelacent alors leurs commandes AT, et la
	// réponse de l'un part vers l'autre. Ce qu'on observe n'est pas une
	// erreur mais un SILENCE — un appel entrant que personne ne voit, un
	// relevé qui n'arrive jamais — et on cherche du côté du modem, du réseau
	// ou de l'opérateur, où il n'y a rien.
	//
	// Le verrou n'est PAS hérité par les processus fils et disparaît avec
	// celui qui le tient, y compris tué : rien à nettoyer après un plantage.
	if err := unix.Flock(fd, unix.LOCK_EX|unix.LOCK_NB); err != nil {
		f.Close()
		return nil, fmt.Errorf(
			"port %s deja tenu par un autre programme : arretez la veille, "+
				"le clavier de composition ou le service softphone avant "+
				"d'en lancer un second (%w)", chemin, err)
	}
	t, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("termios : %w", err)
	}
	// cfmakeraw, à la main : x/sys ne l'expose pas.
	t.Iflag &^= unix.IGNBRK | unix.BRKINT | unix.PARMRK | unix.ISTRIP |
		unix.INLCR | unix.IGNCR | unix.ICRNL | unix.IXON
	t.Oflag &^= unix.OPOST
	t.Lflag &^= unix.ECHO | unix.ECHONL | unix.ICANON | unix.ISIG | unix.IEXTEN
	t.Cflag &^= unix.CSIZE | unix.PARENB
	t.Cflag |= unix.CS8 | unix.CREAD | unix.CLOCAL
	if err := unix.IoctlSetTermios(fd, unix.TCSETS, t); err != nil {
		f.Close()
		return nil, fmt.Errorf("mode brut : %w", err)
	}
	return &Modem{f: f, br: bufio.NewReader(f)}, nil
}

func (m *Modem) Close() error { return m.f.Close() }

// Commande envoie une commande AT et lit jusqu'à OK, ERROR ou expiration.
//
// On lit jusqu'à un TERMINATEUR et non pendant un délai fixe : attendre
// « assez longtemps » rend chaque commande lente et rate quand même les
// réponses tardives.
func (m *Modem) Commande(cmd string, délai time.Duration) (string, error) {
	m.parole.Lock()
	defer m.parole.Unlock()

	if err := m.f.SetDeadline(time.Now().Add(délai)); err != nil {
		return "", err
	}
	defer m.f.SetDeadline(time.Time{})

	if _, err := m.f.Write([]byte(cmd + "\r\n")); err != nil {
		return "", fmt.Errorf("écriture %q : %w", cmd, err)
	}
	var b strings.Builder
	for {
		ligne, err := m.br.ReadString('\n')
		b.WriteString(ligne)
		if err != nil {
			// Expiration : on rend ce qu'on a lu. Une réponse partielle
			// renseigne davantage qu'une erreur nue.
			return b.String(), fmt.Errorf("commande %q : %w", cmd, err)
		}
		t := strings.TrimSpace(ligne)
		if t == "OK" {
			return b.String(), nil
		}
		if t == "ERROR" || strings.HasPrefix(t, "+CME ERROR") ||
			strings.HasPrefix(t, "+CMS ERROR") {
			return b.String(), fmt.Errorf("modem a refusé %q : %s", cmd, t)
		}
	}
}

// ÉtatAppel décrit une ligne de +CLCC.
type ÉtatAppel struct {
	Index   int
	Sortant bool
	État    int // 0 actif (DÉCROCHÉ), 2 composition, 3 sonnerie
	Mode    int // 0 VOIX, 1 données, 2 fax
	Numéro  string
}

// Voix distingue un appel téléphonique d'un porteur de données.
//
// Indispensable, et pas un raffinement : ModemManager maintient en
// permanence un porteur de données LTE, que +CLCC rapporte comme un appel
// d'état 0 — donc « actif ». Sans ce filtre, on croit avoir décroché à
// l'instant où l'on compose. Mesuré :
//
//	+CLCC: 1,1,0,1,0,"",128
//	             ^ état 0   ^ mode 1 = données
func (a ÉtatAppel) Voix() bool { return a.Mode == 0 }

var motifCLCC = regexp.MustCompile(
	`\+CLCC:\s*(\d+),(\d+),(\d+),(\d+),(\d+),"([^"]*)"`)

// Appels interroge le modem sur les appels en cours.
func (m *Modem) Appels() ([]ÉtatAppel, error) {
	rép, err := m.Commande("AT+CLCC", 5*time.Second)
	if err != nil {
		return nil, err
	}
	return analyserCLCC(rép), nil
}

// analyserCLCC extrait les appels d'une réponse brute à AT+CLCC.
//
// Séparée de Appels pour être vérifiable sans modem : c'est ici que se joue
// la distinction voix/données, et une erreur y est invisible à l'œil.
func analyserCLCC(rép string) []ÉtatAppel {
	var out []ÉtatAppel
	for _, l := range strings.Split(rép, "\n") {
		g := motifCLCC.FindStringSubmatch(strings.TrimSpace(l))
		if g == nil {
			continue
		}
		idx, _ := strconv.Atoi(g[1])
		dir, _ := strconv.Atoi(g[2])
		st, _ := strconv.Atoi(g[3])
		md, _ := strconv.Atoi(g[4])
		out = append(out, ÉtatAppel{
			Index: idx, Sortant: dir == 0, État: st, Mode: md, Numéro: g[6],
		})
	}
	return out
}

// ModeVoixUSBDéfaut est le mode <mode> de AT+QPCMV=1,<mode>.
//
// Le modem accepte les trois valeurs que AT+QPCMV=? annonce sans dire
// laquelle correspond à la carte USB : la sonde audio le tranche par la
// mesure, pendant un appel.
const ModeVoixUSBDéfaut = 2

// ModeAudioSansDSP désactive le traitement du signal vocal.
const ModeAudioSansDSP = 3

// ModeAudioInchangé laisse le réglage du modem tel quel.
const ModeAudioInchangé = -1

const (
	// Tentatives de fermeture du canal voix, et pause entre elles.
	EssaisFermeture  = 4
	AttenteFermeture = 500 * time.Millisecond
)

// OuvrirVoixUSB relie la carte son USB au canal voix de l'appel.
//
// Indispensable, et facile à croire acquis : la carte son du modem existe
// dès que UAC est activé, accepte l'audio et rend un code de succès, mais
// n'en fait RIEN tant que ce canal est fermé — AT+QPCMV? rend alors « 0,0 »
// et la ligne reste muette dans les deux sens. Qu'aplay réussisse ne prouve
// donc rien sur ce que le correspondant entend.
//
// Le canal ne vit que pendant un appel : ouvert à vide, le DSP voix du
// modem ne tourne pas, et même la boucle interne AT+QAUDLOOP ne renvoie que
// du silence.
func (m *Modem) OuvrirVoixUSB(mode int) error {
	_, err := m.Commande(fmt.Sprintf("AT+QPCMV=1,%d", mode), 5*time.Second)
	return err
}

// RéaffirmerVoixUSB referme et rouvre le canal en UNE seule commande.
//
// Séquence employée par les pilotes Asterisk pour ces modules, appliquée AU
// DÉCROCHÉ. Deux raisons de ne pas se contenter de l'ouverture faite avant
// la composition : le modem refuse d'ouvrir un canal déjà ouvert, alors
// qu'il accepte cette forme combinée ; et c'est à l'établissement de la
// voix que le routage se fixe, donc une ouverture antérieure peut être
// perdue au passage.
func (m *Modem) RéaffirmerVoixUSB(mode int) error {
	_, err := m.Commande(fmt.Sprintf("AT+QPCMV=0;+QPCMV=1,%d", mode),
		5*time.Second)
	return err
}

// RéglerModeAudio choisit le traitement DSP appliqué à la voix.
//
// Le mode 3 le désactive. Les traitements prévus pour un combiné —
// réduction de bruit, écho, gain automatique — brouillent un signal qui
// arrive déjà numérisé par USB, jusqu'à le rendre inintelligible.
func (m *Modem) RéglerModeAudio(mode int) error {
	_, err := m.Commande(fmt.Sprintf("AT+QAUDMOD=%d", mode), 5*time.Second)
	return err
}

// FermerVoixUSB rend la voix à son routage d'origine.
//
// Réessaie, car juste après ATH le modem démonte encore la voix et refuse
// la commande par un ERROR sec. Échouer ici n'est pas anodin : le canal
// reste ouvert, le modem refuse alors tout changement de mode, et l'appel
// SUIVANT hérite silencieusement du mode du précédent — ce qui fait
// attribuer à un mode le résultat d'un autre.
func (m *Modem) FermerVoixUSB() error {
	var dernier error
	for essai := 0; essai < EssaisFermeture; essai++ {
		if essai > 0 {
			time.Sleep(AttenteFermeture)
		}
		_, err := m.Commande("AT+QPCMV=0", 5*time.Second)
		if err == nil {
			return nil
		}
		dernier = err
	}
	return dernier
}

// VolumeÉcouteMax est le cran le plus fort de AT+CLVL sur ce module.
const VolumeÉcouteMax = 5

// VolumeÉcouteBas est le cran en dessous duquel un appel n'est plus
// audible, et sur lequel on avertit.
const VolumeÉcouteBas = 2

// VolumeÉcouteInchangé laisse le réglage du modem tel qu'il est.
//
// C'est le DÉFAUT, et ce n'est pas de la prudence excessive : pousser le
// volume de réception au maximum a dégradé l'écoute au lieu de la
// renforcer, le module saturant avant d'amplifier. Le cran se monte donc à
// la demande, en écoutant le résultat.
const VolumeÉcouteInchangé = -1

// RéglerVolumeÉcoute monte le volume de réception DANS LE MODEM.
//
// À préférer au gain logiciel, et de loin : ici le signal est amplifié
// avant que le bruit de fond ne s'y ajoute, alors qu'un gain applique après
// coup multiplie les deux également. Un correspondant trop faible se règle
// d'abord ici, et seulement ensuite en logiciel.
func (m *Modem) RéglerVolumeÉcoute(cran int) error {
	if cran < 0 {
		cran = 0
	}
	if cran > VolumeÉcouteMax {
		cran = VolumeÉcouteMax
	}
	_, err := m.Commande(fmt.Sprintf("AT+CLVL=%d", cran), 5*time.Second)
	return err
}

// GainMicroUnité est le gain de montée qui ne change rien.
//
// Huit mille cent quatre-vingt-douze, soit deux puissance treize : le
// module travaille en virgule fixe, et cette valeur y vaut « un ». Le
// réglage d'usine était plus haut ; AT+QAUDMOD=3 l'a ramené à l'unité, ce
// qui fait perdre du niveau au correspondant sans rien annoncer.
const GainMicroUnité = 8192

// GainMicroMax borne le gain de montée du modem.
const GainMicroMax = 65535

// RéglerGainMicroModem fixe le gain de montée DANS le modem.
//
// Amplifie avant le codec, là où le gain logiciel amplifie après la
// capture : à niveau égal, ce qui part sur la ligne y perd moins.
func (m *Modem) RéglerGainMicroModem(gain int) error {
	if gain < 0 {
		gain = 0
	}
	if gain > GainMicroMax {
		gain = GainMicroMax
	}
	_, err := m.Commande(fmt.Sprintf("AT+QMIC=%d,%d", gain, gain),
		5*time.Second)
	return err
}

// LireVolumeÉcoute rend le cran de réception actuellement posé.
//
// À lire au début de chaque appel, et non à supposer. Ces réglages sont
// PERSISTANTS : ils survivent à l'appel, au redémarrage du programme et à
// celui du modem. Un volume laissé à un cran par un réglage précédent rend
// la ligne quasi muette, et l'afficher comme inconnu fait chercher la
// panne dans le logiciel.
func (m *Modem) LireVolumeÉcoute() (int, error) {
	return m.lireEntier("AT+CLVL?", motifCLVL)
}

// RéglerGainÉcouteModem fixe le gain de DESCENTE dans le modem.
//
// C'est le pendant de QMIC pour la voix qui arrive. Il amplifie dans le
// décodeur, avant que le signal n'atteigne la carte USB : à niveau égal, ce
// qu'on entend y perd moins qu'avec un gain logiciel, qui multiplie le
// souffle autant que la voix. Les six crans de AT+CLVL sont grossiers ;
// celui-ci se règle finement.
func (m *Modem) RéglerGainÉcouteModem(gain int) error {
	if gain < 0 {
		gain = 0
	}
	if gain > GainMicroMax {
		gain = GainMicroMax
	}
	_, err := m.Commande(fmt.Sprintf("AT+QAUDCFG=\"decgain\",%d", gain),
		5*time.Second)
	return err
}

// LireGainÉcouteModem rend le gain de descente actuellement posé.
func (m *Modem) LireGainÉcouteModem() (int, error) {
	return m.lireEntier("AT+QAUDCFG=\"decgain\"", motifDecgain)
}

// LireGainMicroModem rend le gain de montée actuellement posé.
func (m *Modem) LireGainMicroModem() (int, error) {
	return m.lireEntier("AT+QMIC?", motifQMIC)
}

func (m *Modem) lireEntier(commande string, motif *regexp.Regexp) (int, error) {
	rép, err := m.Commande(commande, 5*time.Second)
	if err != nil {
		return 0, err
	}
	g := motif.FindStringSubmatch(rép)
	if g == nil {
		return 0, fmt.Errorf("réponse illisible : %q", strings.TrimSpace(rép))
	}
	return strconv.Atoi(g[1])
}

var (
	motifCLVL = regexp.MustCompile(`\+CLVL:\s*(\d+)`)
	motifQMIC = regexp.MustCompile(`\+QMIC:\s*(\d+)`)
	// L'espace après la virgule est celui du module, pas une coquille :
	// « +QCFG: "decgain", 8192 ».
	motifDecgain = regexp.MustCompile(`"decgain",\s*(\d+)`)
)

// RéglerRéductionBruit allume ou éteint la suppression de bruit du modem.
//
// Éteinte par AT+QAUDMOD=3, qui coupe tout le traitement du signal — d'où
// un souffle continu que le gain logiciel amplifie ensuite. La rallumer
// séparément garde le routage qui fait passer la voix et récupère le
// filtre.
//
// Elle ne se pose qu'AVANT le premier flux audio : comme tout réglage audio
// du module, elle ferme et rouvre le périphérique USB, et un flux déjà
// ouvert dessus en meurt.
func (m *Modem) RéglerRéductionBruit(actif bool) error {
	n := 0
	if actif {
		n = 1
	}
	_, err := m.Commande(fmt.Sprintf("AT+QAUDCFG=\"fns\",0,%d", n),
		5*time.Second)
	return err
}

// Signal rend la puissance reçue en dBm et le détail de la porteuse.
//
// Deux commandes parce qu'elles ne disent pas la même chose : +CSQ donne un
// indice normalisé, qui se convertit en dBm par une formule du 3GPP ; +QCSQ
// donne les mesures propres au module, plus fines mais dont l'encodage
// dépend du firmware. On rend la première comme chiffre et la seconde comme
// texte, faute de pouvoir garantir son interprétation.
func (m *Modem) Signal() (int, string) {
	dBm := 0
	if rép, err := m.Commande("AT+CSQ", 5*time.Second); err == nil {
		if g := motifCSQ.FindStringSubmatch(rép); g != nil {
			if n, err := strconv.Atoi(g[1]); err == nil && n <= 31 {
				// 0 vaut -113 dBm et chaque cran en ajoute deux ; 99 signale
				// une mesure indisponible, d'où le rejet au-dessus de 31.
				dBm = -113 + 2*n
			}
		}
	}
	détail := ""
	if rép, err := m.Commande("AT+QCSQ", 5*time.Second); err == nil {
		if g := motifQCSQ.FindStringSubmatch(rép); g != nil {
			détail = strings.TrimSpace(g[1])
		}
	}
	return dBm, détail
}

var (
	motifCSQ  = regexp.MustCompile(`\+CSQ:\s*(\d+),`)
	motifQCSQ = regexp.MustCompile(`\+QCSQ:\s*(.+)`)
)

// Composer lance un appel VOIX.
//
// Le point-virgule final n'est pas décoratif : sans lui le modem tente un
// appel de DONNÉES, qui échoue sur une ligne ordinaire avec un message qui
// n'explique rien.
// TouchesValides refuse ce qu'un clavier téléphonique n'a pas.
//
// Filtré AVANT le modem : un caractère inattendu dans AT+VTS rend ERROR et
// arrête la séquence au milieu, sans dire lequel a gêné.
func TouchesValides(touches string) (string, error) {
	touches = strings.ToUpper(strings.TrimSpace(touches))
	if touches == "" {
		return "", fmt.Errorf("aucune touche")
	}
	for _, r := range touches {
		if !strings.ContainsRune("0123456789*#ABCD", r) {
			return "", fmt.Errorf("touche %q absente d'un clavier téléphonique", r)
		}
	}
	return touches, nil
}

// EnvoyerTouches joue des tonalités DTMF sur l'appel en cours.
//
// Une touche par commande, et non la séquence d'un bloc : c'est la forme
// que tous les micrologiciels acceptent, et une touche refusée s'y nomme.
func (m *Modem) EnvoyerTouches(touches string) error {
	valides, err := TouchesValides(touches)
	if err != nil {
		return err
	}
	for _, r := range valides {
		if _, err := m.Commande(fmt.Sprintf("AT+VTS=%c", r), 5*time.Second); err != nil {
			return fmt.Errorf("touche %c : %w", r, err)
		}
	}
	return nil
}

func (m *Modem) Composer(numéro string) error {
	_, err := m.Commande("ATD+"+numéro+";", 20*time.Second)
	return err
}

// ÉtatSonnerie et ÉtatEnAttente : un appel entrant qui n'a pas été pris.
//
// +CLCC distingue celui qui sonne sur une ligne libre de celui qui attend
// pendant une conversation. Les deux se répondent par ATA.
const (
	ÉtatSonnerie  = 4
	ÉtatEnAttente = 5
)

// AnnoncerAppelant demande au réseau le numéro de qui appelle.
//
// Sans elle, +CLCC rend un numéro vide sur un appel entrant : la
// présentation n'est pas active par défaut, et l'on ne saurait pas qui
// sonne.
func (m *Modem) AnnoncerAppelant() error {
	_, err := m.Commande("AT+CLIP=1", 5*time.Second)
	return err
}

// Répondre décroche l'appel entrant.
func (m *Modem) Répondre() error {
	_, err := m.Commande("ATA", 20*time.Second)
	return err
}

// AppelEntrant rend le numéro qui sonne, ou une chaîne vide.
func (m *Modem) AppelEntrant() string {
	appels, err := m.Appels()
	if err != nil {
		return ""
	}
	for _, a := range appels {
		if !a.Voix() || a.Sortant {
			continue
		}
		if a.État == ÉtatSonnerie || a.État == ÉtatEnAttente {
			if a.Numéro == "" {
				// Numéro masqué ou présentation refusée : on annonce tout de
				// même la sonnerie, sans quoi le poste reste muet devant un
				// appel bien réel.
				return "inconnu"
			}
			return a.Numéro
		}
	}
	return ""
}

// MettreEnAttente bascule l'appel actif et celui qui patiente.
//
// AT+CHLD=2. Le réseau doit porter le service « appel en attente » ; sans
// lui la commande est refusée, ce qui n'a rien d'anormal.
func (m *Modem) MettreEnAttente() error {
	_, err := m.Commande("AT+CHLD=2", 10*time.Second)
	return err
}

// FusionnerAppels réunit l'appel actif et celui en attente.
//
// AT+CHLD=3, la conférence du 3GPP. Elle se fait DANS LE RÉSEAU et non dans
// le modem : c'est l'opérateur qui mélange les voix. Cela explique qu'elle
// échoue sur une ligne dont l'abonnement ne porte pas le service, et
// qu'aucun réglage local n'y change rien.
//
// Deux appels doivent exister, l'un actif et l'autre en attente : composer
// un second numéro pendant le premier met celui-ci en attente de lui-même.
func (m *Modem) FusionnerAppels() error {
	_, err := m.Commande("AT+CHLD=3", 10*time.Second)
	return err
}

func (m *Modem) Raccrocher() error {
	_, err := m.Commande("ATH", 10*time.Second)
	return err
}
