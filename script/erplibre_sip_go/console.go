// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

// CadenceAffichage règle le rafraîchissement de la ligne d'état.
//
// Cinq fois par seconde : assez pour que le niveau suive la voix et serve
// d'indicateur, assez peu pour ne pas noyer un terminal lent.
const CadenceAffichage = 200 * time.Millisecond

// ÉchelleNiveau borne la barre de niveau.
//
// Un signal téléphonique confortable tourne autour de quelques milliers en
// valeur efficace sur seize bits, loin du maximum théorique de 32767 qui
// n'est atteint que par de la saturation. Cadrer sur 8000 rend la barre
// lisible plutôt que constamment au ras du sol.
const ÉchelleNiveau = 8000

// ConsoleCombiné pilote l'appel au clavier tant qu'il dure.
//
// Rend la main quand le contexte s'arrête, quand le média se tarit, ou
// quand on demande à raccrocher — auquel cas elle appelle raccrocher.
//
// Sans terminal — sortie redirigée, exécution par un service — elle ne fait
// rien d'autre que le dire : lire des touches sur une entrée qui n'en
// portera jamais consommerait un cœur pour rien.
func ConsoleCombiné(ctx context.Context, c *Combiné, raccrocher context.CancelFunc) {
	restaurer, err := modeBrutTerminal()
	if err != nil {
		slog.Info("pas de terminal : combiné sans commandes au clavier",
			"micro", c.MicOuvert())
		return
	}
	defer restaurer()

	touches := lireTouches(ctx)
	fmt.Fprint(os.Stderr, "\r\n"+AideConsole+"\r\n")

	tic := time.NewTicker(CadenceAffichage)
	defer tic.Stop()
	defer fmt.Fprint(os.Stderr, "\r\n")

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.Fini:
			return
		case <-tic.C:
			fmt.Fprint(os.Stderr, "\r"+ligneÉtat(c))
		case t, ouvert := <-touches:
			if !ouvert {
				return
			}
			switch t {
			case 'm', 'M', ' ':
				slog.Info("micro", "ouvert", c.BasculerMic())
			case 's', 'S':
				slog.Info("haut-parleurs", "ouverts", c.BasculerHP())
			case '+', '=':
				c.RéglerGainHP(arrondiPas(gainHP(c) + PasGain))
			case '-', '_':
				c.RéglerGainHP(arrondiPas(gainHP(c) - PasGain))
			case '>', '.':
				c.RéglerGainMic(arrondiPas(gainMic(c) + PasGain))
			case '<', ',':
				c.RéglerGainMic(arrondiPas(gainMic(c) - PasGain))
			case 'q', 'Q', 3: // 3 = Ctrl-C
				fmt.Fprint(os.Stderr, "\r\n")
				raccrocher()
				return
			}
		}
	}
}

// AideConsole rappelle les touches. Affichée une fois, puis rappelée en
// bout de ligne d'état : une aide qui défile hors de l'écran n'aide plus.
const AideConsole = "  [m] micro  [s] haut-parleurs  [+/-] écoute" +
	"  [</>] micro  [q] raccrocher"

// PasGain est l'incrément de volume, en pour cent.
//
// Vingt : dix se remarque à peine sur une bande passante téléphonique, et
// cinquante fait passer d'inaudible à saturé sans palier utile.
const PasGain = 20

func gainMic(c *Combiné) int { m, _ := c.Gains(); return m }
func gainHP(c *Combiné) int  { _, h := c.Gains(); return h }

// arrondiPas cale une valeur sur le pas, pour que les paliers restent ronds
// quel que soit le point de départ.
func arrondiPas(v int) int {
	return (v + PasGain/2) / PasGain * PasGain
}

// ligneÉtat rend l'état du combiné sur une ligne, sans retour chariot.
func ligneÉtat(c *Combiné) string {
	moi, lui := c.Niveaux()
	gm, gh := c.Gains()
	return fmt.Sprintf("  MIC %s %3d%% %s   HP %s %3d%% %s   [m s +- <> q]  ",
		voyant(c.MicOuvert()), gm, barre(moi),
		voyant(c.HPOuvert()), gh, barre(lui))
}

// voyant distingue ouvert de fermé sans couleur : un terminal qui n'en
// affiche pas laisserait les deux états identiques.
func voyant(ouvert bool) string {
	if ouvert {
		return "ON "
	}
	return "OFF"
}

// barre dessine un niveau sur dix caractères.
func barre(niveau int) string {
	n := niveau * 10 / ÉchelleNiveau
	if n > 10 {
		n = 10
	}
	if n < 0 {
		n = 0
	}
	return "[" + strings.Repeat("#", n) + strings.Repeat(".", 10-n) + "]"
}

// lireTouches rend un canal des touches frappées.
//
// La lecture de l'entrée standard est bloquante et rien ne l'interrompt :
// on l'isole donc dans sa goroutine, que la fin du programme emporte. Le
// canal se ferme quand l'entrée se tarit.
func lireTouches(ctx context.Context) <-chan byte {
	sortie := make(chan byte, 8)
	go func() {
		defer close(sortie)
		tampon := make([]byte, 1)
		for {
			n, err := os.Stdin.Read(tampon)
			if err != nil {
				return
			}
			if n == 0 {
				continue
			}
			select {
			case sortie <- tampon[0]:
			case <-ctx.Done():
				return
			}
		}
	}()
	return sortie
}

// modeBrutTerminal fait rendre chaque touche sans attendre d'entrée.
//
// Rend la fonction qui remet le terminal dans son état d'origine, et une
// erreur si l'entrée standard n'est pas un terminal. NE PAS oublier de la
// rappeler : un terminal laissé en mode brut n'affiche plus ce qu'on tape
// et ne réagit plus à Ctrl-C, ce qui donne un shell qui semble figé.
func modeBrutTerminal() (func(), error) {
	fd := int(os.Stdin.Fd())
	avant, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		return nil, err
	}
	brut := *avant
	// On garde ISIG : Ctrl-C doit continuer d'interrompre le programme, qui
	// sait alors raccrocher. Seuls l'écho et le tampon de ligne partent.
	brut.Lflag &^= unix.ICANON | unix.ECHO
	brut.Cc[unix.VMIN] = 1
	brut.Cc[unix.VTIME] = 0
	if err := unix.IoctlSetTermios(fd, unix.TCSETS, &brut); err != nil {
		return nil, err
	}
	return func() {
		_ = unix.IoctlSetTermios(fd, unix.TCSETS, avant)
	}, nil
}
