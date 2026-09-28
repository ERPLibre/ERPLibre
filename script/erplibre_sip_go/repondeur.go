// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"time"
)

// Prendre le message quand personne ne décroche.
//
// La boîte vocale de l'opérateur prend l'appel au bout d'une trentaine de
// secondes, et ce qu'elle garde n'est consultable qu'en l'appelant : aucune
// commande AT ne liste ses messages. Répondre AVANT elle est donc la seule
// façon d'avoir un historique.
//
// C'est une course, et elle décide des valeurs par défaut ci-dessous.

const (
	// SonneriesParDéfaut : le compromis entre laisser le temps de décrocher
	// et passer devant l'opérateur.
	SonneriesParDéfaut = 4

	// CycleSonnerie est le temps d'une sonnerie complète, courant et silence
	// compris — la cadence que `sonnerie.go` produit déjà. Le modem ne COMPTE
	// pas les sonneries : il dit qu'un appel entre, et c'est le temps écoulé
	// qui les traduit.
	CycleSonnerie = DuréeSonnerie + PauseSonnerie

	// SonneriesMax borne ce qu'un réglage peut demander. Au-delà, l'opérateur
	// a déjà pris l'appel et le répondeur ne s'enclencherait jamais — une
	// panne qui se lit « le répondeur ne marche pas » sans autre indice.
	SonneriesMax = 5

	// DuréeMaxMessageDéfaut borne un message. Une ligne laissée ouverte se
	// facture, et un appelant qui pose son combiné sans raccrocher tient la
	// ligne aussi longtemps qu'on l'accepte.
	DuréeMaxMessageDéfaut = 2 * time.Minute

	// SilenceFinMessage : après avoir parlé, ce silence termine le message.
	SilenceFinMessage = 4 * time.Second

	// DélaiPremierSon : sans un mot dans ce délai, il n'y a pas de message.
	// On raccroche et on n'écrit RIEN — un dossier rempli d'enregistrements
	// vides cache ceux qui comptent.
	DélaiPremierSon = 8 * time.Second

	// Ce que la carte du modem rend : la même chose que le réseau
	// téléphonique, sans rééchantillonnage. Le taux vient de `duplex.go`,
	// qui le donne déjà aux deux processus ALSA.
	CanauxMessage  = 1
	OctetsParÉchan = 2
)

// RéglagesRépondeur dit s'il répond, après combien, et ce qu'il annonce.
//
// Sérialisable : la TUI les écrit, le service les relit au démarrage de
// chaque appel. Relire à chaque appel plutôt qu'au lancement permet de
// changer l'annonce sans couper le service — et le service tourne des
// semaines.
type RéglagesRépondeur struct {
	Actif            bool   `json:"actif"`
	Sonneries        int    `json:"sonneries"`
	Annonce          string `json:"annonce"`
	Dossier          string `json:"dossier"`
	DuréeMaxSecondes int    `json:"duree_max_secondes"`
}

// RéglagesParDéfaut rend un répondeur ÉTEINT.
//
// Éteint et non allumé : décrocher à la place de quelqu'un est un acte
// visible par l'appelant, et il se demande. Un défaut actif ferait répondre
// une machine sur une ligne dont le propriétaire ignore qu'elle en a une.
func RéglagesParDéfaut() RéglagesRépondeur {
	return RéglagesRépondeur{
		Sonneries:        SonneriesParDéfaut,
		DuréeMaxSecondes: int(DuréeMaxMessageDéfaut / time.Second),
	}
}

// Normaliser ramène les valeurs hors bornes dans leur plage.
//
// On corrige plutôt que de refuser : un réglage aberrant vient d'une saisie,
// et refuser de démarrer pour « 40 sonneries » priverait la ligne de tout
// répondeur alors que l'intention est claire.
func (r RéglagesRépondeur) Normaliser() RéglagesRépondeur {
	if r.Sonneries < 1 {
		r.Sonneries = SonneriesParDéfaut
	}
	if r.Sonneries > SonneriesMax {
		r.Sonneries = SonneriesMax
	}
	if r.DuréeMaxSecondes <= 0 {
		r.DuréeMaxSecondes = int(DuréeMaxMessageDéfaut / time.Second)
	}
	return r
}

// DélaiAvantDécroché traduit les sonneries en temps d'attente.
func (r RéglagesRépondeur) DélaiAvantDécroché() time.Duration {
	return time.Duration(r.Normaliser().Sonneries) * CycleSonnerie
}

// DuréeMax rend la durée maximale d'un message.
func (r RéglagesRépondeur) DuréeMax() time.Duration {
	return time.Duration(r.Normaliser().DuréeMaxSecondes) * time.Second
}

// ChargerRéglagesRépondeur lit le fichier, ou rend les défauts s'il manque.
//
// Un fichier ABSENT n'est pas une erreur : c'est l'état d'une installation
// qui n'a pas de répondeur, et le service doit démarrer. Un fichier PRÉSENT
// mais illisible en est une : quelqu'un a voulu un répondeur, et le taire
// laisserait croire qu'il fonctionne.
func ChargerRéglagesRépondeur(chemin string) (RéglagesRépondeur, error) {
	défauts := RéglagesParDéfaut()
	if chemin == "" {
		return défauts, nil
	}
	brut, err := os.ReadFile(chemin)
	if os.IsNotExist(err) {
		return défauts, nil
	}
	if err != nil {
		return défauts, fmt.Errorf("reglages du repondeur %s : %w", chemin, err)
	}
	réglages := défauts
	if err := json.Unmarshal(brut, &réglages); err != nil {
		return défauts, fmt.Errorf("reglages du repondeur %s : %w", chemin, err)
	}
	return réglages.Normaliser(), nil
}

// Enregistrer écrit les réglages, en créant le dossier au besoin.
func (r RéglagesRépondeur) Enregistrer(chemin string) error {
	if err := os.MkdirAll(filepath.Dir(chemin), 0o755); err != nil {
		return err
	}
	brut, err := json.MarshalIndent(r.Normaliser(), "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(chemin, append(brut, '\n'), 0o644)
}

// Message décrit ce qu'un appelant a laissé.
//
// Le compagnon JSON vit à côté du son : un dossier de fichiers WAV sans
// numéro ni date ne se lit pas, et l'horodatage du système de fichiers se
// perd à la première copie.
type Message struct {
	Numéro        string `json:"numero"`
	Début         string `json:"debut"`
	DuréeSecondes int    `json:"duree_secondes"`
	Fichier       string `json:"fichier"`
	CrêteMaximale int    `json:"crete_maximale"`
	TéléverséOdoo bool   `json:"televerse_odoo"`
}

// PrendreLeMessage joue l'annonce puis enregistre l'appelant.
//
// La ligne est DÉJÀ décrochée quand on entre ici : décrocher appartient à
// l'appelant de cette fonction, qui seul sait si le softphone a renoncé.
//
// L'annonce passe par `aplay` et l'enregistrement par `arecord`, l'un APRÈS
// l'autre et jamais ensemble : les deux voudraient la carte du modem, et le
// second échouerait sur un périphérique occupé.
func PrendreLeMessage(ctx context.Context, carte string, r RéglagesRépondeur,
	numéro string) (*Message, error) {

	r = r.Normaliser()
	if r.Dossier == "" {
		return nil, fmt.Errorf("aucun dossier de messages : rien a enregistrer")
	}
	if err := os.MkdirAll(r.Dossier, 0o700); err != nil {
		return nil, err
	}

	if r.Annonce != "" {
		if err := jouerSurCarte(ctx, carte, r.Annonce); err != nil {
			// L'annonce manquante n'annule pas le message : mieux vaut un
			// enregistrement sans invite qu'un appel perdu.
			slog.Warn("annonce du repondeur non jouee", "err", err,
				"annonce", r.Annonce)
		}
	}

	début := time.Now()
	nom := fmt.Sprintf("%s_%s.wav", début.Format("20060102-150405"),
		chiffresSeuls(numéro))
	chemin := filepath.Join(r.Dossier, nom)

	durée, crête, err := enregistrerLaVoix(ctx, carte, chemin, r.DuréeMax())
	if err != nil {
		_ = os.Remove(chemin)
		return nil, err
	}
	if durée == 0 {
		// Personne n'a parlé : on ne garde rien, et on le dit.
		_ = os.Remove(chemin)
		slog.Info("appel sans message", "de", numéro)
		return nil, nil
	}

	message := &Message{
		Numéro:        numéro,
		Début:         début.Format(time.RFC3339),
		DuréeSecondes: int(durée / time.Second),
		Fichier:       chemin,
		CrêteMaximale: crête,
	}
	if err := ÉcrireCompagnon(message); err != nil {
		slog.Warn("compagnon du message non ecrit", "err", err)
	}
	slog.Info("message enregistre", "de", numéro, "secondes",
		message.DuréeSecondes, "fichier", chemin)
	return message, nil
}

// CheminCompagnon rend le fichier de description d'un enregistrement.
func CheminCompagnon(wav string) string {
	return wav[:len(wav)-len(filepath.Ext(wav))] + ".json"
}

// ÉcrireCompagnon dépose la description à côté du son.
func ÉcrireCompagnon(m *Message) error {
	brut, err := json.MarshalIndent(m, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(CheminCompagnon(m.Fichier), append(brut, '\n'), 0o600)
}

// ListerMessages rend ce que le dossier contient, du plus récent au plus
// ancien.
//
// Un WAV sans compagnon est ignoré plutôt qu'inventé : afficher un message
// dont on ne connaît ni l'appelant ni la date donne une ligne qui n'apprend
// rien et qu'on ne peut pas rappeler.
func ListerMessages(dossier string) ([]Message, error) {
	entrées, err := os.ReadDir(dossier)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var messages []Message
	for _, e := range entrées {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		brut, err := os.ReadFile(filepath.Join(dossier, e.Name()))
		if err != nil {
			continue
		}
		var m Message
		if json.Unmarshal(brut, &m) != nil || m.Fichier == "" {
			continue
		}
		messages = append(messages, m)
	}
	sort.Slice(messages, func(i, j int) bool {
		return messages[i].Début > messages[j].Début
	})
	return messages, nil
}

// EffacerMessage retire le son ET sa description.
//
// Les deux ensemble : un compagnon orphelin ferait réapparaître dans la liste
// un message dont le son n'existe plus.
func EffacerMessage(wav string) error {
	err := os.Remove(wav)
	if erreurCompagnon := os.Remove(CheminCompagnon(wav)); err == nil {
		err = erreurCompagnon
	}
	if os.IsNotExist(err) {
		return nil
	}
	return err
}

// enregistrerLaVoix capture jusqu'au silence, à la durée maximale, ou à
// l'abandon du contexte. Rend la durée retenue et la crête observée.
//
// Une durée NULLE dit que personne n'a parlé, ce qui n'est pas une erreur.
func enregistrerLaVoix(ctx context.Context, carte, chemin string,
	max time.Duration) (time.Duration, int, error) {

	capture := commandePour(ctx, carte, "arecord", "pw-record")
	flux, err := capture.StdoutPipe()
	if err != nil {
		return 0, 0, err
	}
	pont := &PontModem{}
	if err := pont.écouterErreurs(capture, "arecord"); err != nil {
		return 0, 0, err
	}
	if err := capture.Start(); err != nil {
		return 0, 0, fmt.Errorf("arecord sur %s : %w%s", carte, err, pont.pourquoi())
	}
	defer func() {
		if capture.Process != nil {
			_ = capture.Process.Kill()
		}
	}()

	fichier, err := os.OpenFile(chemin, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return 0, 0, err
	}
	defer fichier.Close()
	if _, err := fichier.Write(entêteWAV(0)); err != nil {
		return 0, 0, err
	}

	var (
		écrits    int
		crête     int
		aParlé    bool
		depuisSon time.Duration
		écoulé    time.Duration
		bloc      = make([]byte, OctetsPCM)
	)
	for écoulé < max {
		if _, err := io.ReadFull(flux, bloc); err != nil {
			// Le flux se ferme quand la ligne retombe : c'est la fin normale
			// d'un message, pas une panne.
			break
		}
		if _, err := fichier.Write(bloc); err != nil {
			return 0, 0, err
		}
		écrits += len(bloc)
		écoulé += DuréeBloc

		niveau := niveauCrête(bloc)
		if niveau > crête {
			crête = niveau
		}
		if niveau > SeuilÉcho {
			aParlé = true
			depuisSon = 0
			continue
		}
		depuisSon += DuréeBloc
		if aParlé && depuisSon >= SilenceFinMessage {
			break
		}
		if !aParlé && depuisSon >= DélaiPremierSon {
			return 0, crête, nil
		}
	}

	if _, err := fichier.WriteAt(entêteWAV(écrits), 0); err != nil {
		return 0, crête, err
	}
	// Le silence de fin ne fait pas partie du message : le garder ajoute
	// quatre secondes de rien à chaque écoute.
	durée := écoulé
	if aParlé && durée > SilenceFinMessage {
		durée -= SilenceFinMessage
	}
	return durée, crête, nil
}

// entêteWAV rend l'en-tête canonique de 44 octets pour `octets` de PCM.
//
// Écrit à zéro AVANT la capture puis réécrit à la fin : la taille n'est
// connue qu'une fois l'appelant parti, et un en-tête écrit seulement à la fin
// laisserait un fichier illisible si le service s'arrêtait en cours.
func entêteWAV(octets int) []byte {
	taux := int(TauxVoixHz)
	débit := taux * CanauxMessage * OctetsParÉchan
	e := make([]byte, 44)
	copy(e[0:], "RIFF")
	binary.LittleEndian.PutUint32(e[4:], uint32(36+octets))
	copy(e[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(e[16:], 16)
	binary.LittleEndian.PutUint16(e[20:], 1) // PCM
	binary.LittleEndian.PutUint16(e[22:], CanauxMessage)
	binary.LittleEndian.PutUint32(e[24:], uint32(taux))
	binary.LittleEndian.PutUint32(e[28:], uint32(débit))
	binary.LittleEndian.PutUint16(e[32:], CanauxMessage*OctetsParÉchan)
	binary.LittleEndian.PutUint16(e[34:], 8*OctetsParÉchan)
	copy(e[36:], "data")
	binary.LittleEndian.PutUint32(e[40:], uint32(octets))
	return e
}

// chiffresSeuls rend le numéro dépouillé, pour nommer un fichier.
func chiffresSeuls(numéro string) string {
	var chiffres []rune
	for _, r := range numéro {
		if r >= '0' && r <= '9' {
			chiffres = append(chiffres, r)
		}
	}
	if len(chiffres) == 0 {
		return "inconnu"
	}
	return string(chiffres)
}
