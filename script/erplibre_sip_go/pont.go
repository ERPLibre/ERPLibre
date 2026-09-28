// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bufio"
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"log/slog"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/pion/rtp"
	"github.com/zaf/g711"
)

// Le pont entre le navigateur et la carte son du modem.
//
// Les deux formats se correspondent SANS rééchantillonnage, et c'est tout le
// bénéfice d'avoir négocié PCMU seul : le réseau téléphonique et le modem sont
// tous deux à 8 kHz. Il ne reste qu'un changement de largeur — un octet par
// échantillon d'un côté, deux de l'autre.
//
//	navigateur → 160 octets µ-law → 320 octets S16LE → carte du modem
//	carte du modem → 320 octets S16LE → 160 octets µ-law → navigateur

const (
	// ÉchantillonsParPaquet : 20 ms à 8 kHz. C'est la cadence du modem comme
	// celle qu'annonce notre SDP (« a=ptime:20 »).
	ÉchantillonsParPaquet = 160

	// OctetsPCMU et OctetsPCM disent la même durée dans les deux formats.
	OctetsPCMU = ÉchantillonsParPaquet
	OctetsPCM  = ÉchantillonsParPaquet * 2

	// SSRCSortant identifie NOTRE flux vers le navigateur.
	//
	// On émet sous notre propre identifiant plutôt que de recopier celui
	// d'en face : une pile qui reçoit son propre SSRC y voit une boucle et
	// jette le flux.
	SSRCSortant = 0x45524C42 // « ERLB »
)

// VersModem convertit une charge utile PCMU en ce que la carte attend.
func VersModem(mulaw []byte) []byte { return g711.DecodeUlaw(mulaw) }

// VersNavigateur convertit ce que la carte rend en charge utile PCMU.
func VersNavigateur(pcm []byte) []byte { return g711.EncodeUlaw(pcm) }

// SilencePCM rend un bloc muet, au format de la carte.
//
// Nourrir la carte de silence plutôt que de ne rien lui donner : elle attend
// un flux régulier, et l'en priver produit des ratés à la reprise. Le même
// raisonnement que dans `Combiné`.
func SilencePCM() []byte { return make([]byte, OctetsPCM) }

// PontModem tient les deux processus ALSA d'un appel.
type PontModem struct {
	carte string

	versCarte io.WriteCloser
	deCarte   io.ReadCloser
	procs     []*exec.Cmd
	plaintes  []*plainte
}

// plainte retient ce qu'un processus ALSA écrit sur sa sortie d'erreur.
//
// La jeter est le meilleur moyen de ne jamais savoir pourquoi un pont meurt :
// « EOF » ne dit pas si la carte est prise par le serveur audio, si le nom du
// périphérique est faux, ou si le format est refusé. C'est arecord qui le
// sait, et il le dit là.
type plainte struct {
	quoi   string
	mutex  sync.Mutex
	lignes []string
}

func (p *plainte) suivre(r io.Reader) {
	balayeur := bufio.NewScanner(r)
	for balayeur.Scan() {
		ligne := strings.TrimSpace(balayeur.Text())
		if ligne == "" {
			continue
		}
		slog.Warn("sortie d'erreur ALSA", "processus", p.quoi, "ligne", ligne)
		p.mutex.Lock()
		// Borné : un processus qui se plaint en boucle ne doit pas faire
		// enfler la mémoire d'un appel de plusieurs minutes.
		if len(p.lignes) < 20 {
			p.lignes = append(p.lignes, ligne)
		}
		p.mutex.Unlock()
	}
}

func (p *plainte) dernière() string {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	if len(p.lignes) == 0 {
		return ""
	}
	return p.lignes[len(p.lignes)-1]
}

// pourquoi rassemble ce que les processus ont dit, pour l'accrocher à
// l'erreur qui remonte.
func (p *PontModem) pourquoi() string {
	var dits []string
	for _, pl := range p.plaintes {
		if d := pl.dernière(); d != "" {
			dits = append(dits, pl.quoi+" : "+d)
		}
	}
	if dits == nil {
		return ""
	}
	return " — " + strings.Join(dits, " | ")
}

// écouterErreurs branche la sortie d'erreur d'un processus.
func (p *PontModem) écouterErreurs(cmd *exec.Cmd, quoi string) error {
	flux, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	pl := &plainte{quoi: quoi}
	p.plaintes = append(p.plaintes, pl)
	go pl.suivre(flux)
	return nil
}

// OuvrirPontModem lance la lecture et la capture sur la carte du modem.
//
// Les mêmes arguments que le combiné, par les mêmes fonctions : période et
// tampon courts, tuyaux bornés. Une seconde liste de réglages finirait par
// diverger, et un sens réglé plus large que l'autre ramène à lui seul tout le
// délai qu'on cherche à supprimer.
func OuvrirPontModem(ctx context.Context, carte string) (*PontModem, error) {
	pont := &PontModem{carte: carte}

	lecture := commandePour(ctx, carte, "aplay", "pw-play")
	versCarte, err := lecture.StdinPipe()
	if err != nil {
		return nil, err
	}
	bornerTuyau(versCarte)
	if err := pont.écouterErreurs(lecture, "aplay"); err != nil {
		return nil, err
	}
	if err := lecture.Start(); err != nil {
		return nil, fmt.Errorf("aplay sur %s : %w", carte, err)
	}
	pont.versCarte = versCarte
	pont.procs = append(pont.procs, lecture)

	capture := commandePour(ctx, carte, "arecord", "pw-record")
	deCarte, err := capture.StdoutPipe()
	if err != nil {
		pont.Fermer()
		return nil, err
	}
	bornerTuyau(deCarte)
	if err := pont.écouterErreurs(capture, "arecord"); err != nil {
		pont.Fermer()
		return nil, err
	}
	if err := capture.Start(); err != nil {
		pont.Fermer()
		return nil, fmt.Errorf("arecord sur %s : %w", carte, err)
	}
	pont.deCarte = deCarte
	pont.procs = append(pont.procs, capture)

	slog.Info("pont audio ouvert vers le modem", "carte", carte)
	return pont, nil
}

// Fermer arrête les deux processus.
//
// Les TUER et non seulement fermer les tuyaux : un aplay qui survit garde la
// carte du modem, et l'appel suivant échoue sur un périphérique occupé sans
// que rien n'explique pourquoi.
func (p *PontModem) Fermer() {
	for _, proc := range p.procs {
		if proc.Process != nil {
			_ = proc.Process.Kill()
		}
	}
	p.procs = nil
}

// ÉcrireVersModem envoie une charge utile PCMU à la carte.
func (p *PontModem) ÉcrireVersModem(mulaw []byte) error {
	if p.versCarte == nil {
		return io.ErrClosedPipe
	}
	_, err := p.versCarte.Write(VersModem(mulaw))
	return err
}

// LireDeModem rend un bloc de 20 ms, en PCMU.
//
// Lecture COMPLÈTE : un tuyau rend ce qu'il a, et se contenter d'une lecture
// partielle désaligne les échantillons pour toute la durée de l'appel — la
// voix devient un grésillement qu'aucun réglage ne rattrape.
func (p *PontModem) LireDeModem() ([]byte, int, error) {
	if p.deCarte == nil {
		return nil, 0, io.ErrClosedPipe
	}
	bloc := make([]byte, OctetsPCM)
	if _, err := io.ReadFull(p.deCarte, bloc); err != nil {
		return nil, 0, err
	}
	return VersNavigateur(bloc), niveauCrête(bloc), nil
}

// ÉmetteurRTP numérote les paquets sortants.
//
// La numérotation appartient à l'émetteur et ne se recopie pas de l'entrant :
// le modem et le navigateur produisent chacun leur cadence, et reprendre les
// numéros de l'un pour l'autre fait voir des sauts au récepteur, qui jette
// alors ce qu'il croit être des paquets en désordre.
type ÉmetteurRTP struct {
	séquence   uint16
	horodatage uint32
	ssrc       uint32
}

// NouvelÉmetteurRTP part d'un identifiant de source donné.
func NouvelÉmetteurRTP(ssrc uint32) *ÉmetteurRTP {
	return &ÉmetteurRTP{ssrc: ssrc}
}

// Paquet emballe une charge utile PCMU et avance les compteurs.
func (e *ÉmetteurRTP) Paquet(mulaw []byte) ([]byte, error) {
	paquet := &rtp.Packet{
		Header: rtp.Header{
			Version:        2,
			PayloadType:    ChargePCMU,
			SequenceNumber: e.séquence,
			Timestamp:      e.horodatage,
			SSRC:           e.ssrc,
		},
		Payload: mulaw,
	}
	e.séquence++
	// Un échantillon par octet en PCMU : l'horodatage avance de la taille.
	e.horodatage += uint32(len(mulaw))
	return paquet.Marshal()
}

// niveauCrête rend l'amplitude maximale d'un bloc S16LE.
//
// Sert au diagnostic : un pont qui compte des paquets mais reste à zéro dit
// que rien n'entre dans la carte, ce que les compteurs seuls ne distinguent
// pas d'un silence légitime.
func niveauCrête(pcm []byte) int {
	crête := 0
	for i := 0; i+1 < len(pcm); i += 2 {
		valeur := int(int16(binary.LittleEndian.Uint16(pcm[i:])))
		if valeur < 0 {
			valeur = -valeur
		}
		if valeur > crête {
			crête = valeur
		}
	}
	return crête
}

// RelierAuModem remplace l'écho par la carte du modem, dans les deux sens.
func RelierAuModem(ctx context.Context, socket *SocketMédia, session *SessionSRTP,
	carte string) error {

	pont, err := OuvrirPontModem(ctx, carte)
	if err != nil {
		return err
	}
	defer pont.Fermer()

	fini := make(chan error, 2)
	go func() { fini <- versLeNavigateur(ctx, socket, session, pont) }()
	go func() { fini <- versLaLigne(ctx, socket, session, pont) }()

	// Le premier sens qui s'arrête emporte l'appel : un pont à sens unique
	// est plus trompeur qu'un appel coupé — on parle sans être entendu.
	select {
	case err := <-fini:
		return err
	case <-ctx.Done():
		return nil
	}
}

// versLaLigne : ce que le navigateur envoie part vers la carte du modem.
func versLaLigne(ctx context.Context, socket *SocketMédia, session *SessionSRTP,
	pont *PontModem) error {

	var reçus, écrits, illisibles int
	relevé := time.NewTicker(5 * time.Second)
	defer relevé.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-relevé.C:
			slog.Info("navigateur vers la ligne",
				"recus", reçus, "ecrits", écrits, "illisibles", illisibles)
		case protégé, ouvert := <-socket.RTP():
			if !ouvert {
				return nil
			}
			reçus++
			clair, err := session.Déprotéger(protégé)
			if err != nil {
				illisibles++
				continue
			}
			var paquet rtp.Packet
			if err := paquet.Unmarshal(clair); err != nil {
				illisibles++
				continue
			}
			if err := pont.ÉcrireVersModem(paquet.Payload); err != nil {
				return fmt.Errorf("ecriture vers la carte du modem : %w%s",
					err, pont.pourquoi())
			}
			écrits++
		}
	}
}

// versLeNavigateur : ce que la carte du modem rend part vers le navigateur.
func versLeNavigateur(ctx context.Context, socket *SocketMédia,
	session *SessionSRTP, pont *PontModem) error {

	émetteur := NouvelÉmetteurRTP(SSRCSortant)
	var lus, émis, crête int
	relevé := time.NewTicker(5 * time.Second)
	defer relevé.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-relevé.C:
			slog.Info("ligne vers le navigateur",
				"lus", lus, "emis", émis, "crete", crête)
			crête = 0
		default:
		}

		mulaw, niveau, err := pont.LireDeModem()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("lecture de la carte du modem : %w%s",
				err, pont.pourquoi())
		}
		lus++
		if niveau > crête {
			crête = niveau
		}

		brut, err := émetteur.Paquet(mulaw)
		if err != nil {
			continue
		}
		sortant, err := session.Protéger(brut)
		if err != nil {
			continue
		}
		if err := socket.Émettre(sortant); err != nil {
			return err
		}
		émis++
		if émis == 1 {
			slog.Info("premier paquet du modem transmis au navigateur")
		}
	}
}
