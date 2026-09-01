// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/emiago/diago"
	"github.com/emiago/sipgo"
	"github.com/emiago/sipgo/sip"
)

// DélaiSonnerie borne l'attente d'un décroché.
//
// Quatre-vingt-dix secondes : une sonnerie dépasse rarement soixante, et la
// messagerie répond avant. Plus court abandonnerait un appel qui allait
// aboutir ; plus long laisserait la file bloquée.
const DélaiSonnerie = 90 * time.Second

// Résultat de l'appel, tel qu'il sera rapporté à Odoo.
type Résultat struct {
	Numéro    string          `json:"numero"`
	Décroché  bool            `json:"decroche"`
	DuréeSec  int             `json:"duree_seconds"`
	Annonce   bool            `json:"annonce_jouee"`
	Combiné   bool            `json:"combine_actif"`
	VoixUSB   bool            `json:"voix_usb_ouverte"`
	Micro     bool            `json:"micro_ouvert"`
	ModePCM   int             `json:"mode_pcm,omitempty"`
	Sonde     []RésultatSonde `json:"sonde_audio,omitempty"`
	Erreur    string          `json:"erreur,omitempty"`
	DécrochéÀ string          `json:"decroche_a,omitempty"`
}

// Appeler compose un numéro et joue un fichier AU DÉCROCHÉ.
//
// C'est tout l'intérêt de cette voie par rapport au téléphone Android :
// ici le service tient les deux bouts du média, donc « quand ça décroche »
// est un événement du dialogue SIP et non une heuristique, et injecter du
// son est une écriture dans un flux qu'on possède.
func Appeler(ctx context.Context, cfg Config, numéro, annonce string) (Résultat, error) {
	res := Résultat{Numéro: numéro}

	norm, err := NuméroValide(numéro)
	if err != nil {
		res.Erreur = err.Error()
		return res, err
	}

	ua, err := sipgo.NewUA(sipgo.WithUserAgent("ERPLibre"))
	if err != nil {
		return res, fmt.Errorf("agent SIP : %w", err)
	}
	defer ua.Close()

	dg := diago.NewDiago(ua,
		diago.WithTransport(diago.Transport{
			Transport: "udp",
			BindHost:  hôte(cfg.Bind),
			BindPort:  port(cfg.Bind),
		}),
	)

	// S'enregistrer AVANT d'appeler : un trunk qui ne nous connaît pas
	// refuse l'INVITE avec un 403 dont le message n'explique rien.
	recipient := sip.Uri{User: cfg.User, Host: cfg.Trunk}
	if err := dg.Register(ctx, recipient, diago.RegisterOptions{
		Username: cfg.User,
		Password: cfg.Password,
	}); err != nil {
		res.Erreur = "enregistrement refusé : " + err.Error()
		return res, err
	}
	slog.Info("enregistré sur le trunk", "trunk", cfg.Trunk)

	ctxAppel, annule := context.WithTimeout(ctx, DélaiSonnerie)
	defer annule()

	dest := sip.Uri{User: norm, Host: cfg.Trunk}
	dialog, err := dg.Invite(ctxAppel, dest, diago.InviteOptions{})
	if err != nil {
		// Pas de décroché : occupé, refusé, ou personne. Ce n'est pas un
		// appel de durée nulle, c'est un appel qui n'a pas eu lieu — et la
		// distinction compte pour qui relit le journal.
		res.Erreur = "sans réponse : " + err.Error()
		return res, nil
	}
	defer dialog.Close()

	décrochéÀ := time.Now()
	res.Décroché = true
	res.DécrochéÀ = décrochéÀ.Format(time.RFC3339)
	slog.Info("décroché", "numero", norm)

	if annonce != "" {
		if err := jouer(dialog, annonce); err != nil {
			res.Erreur = "annonce non jouée : " + err.Error()
		} else {
			res.Annonce = true
		}
	}

	_ = dialog.Hangup(context.Background())
	res.DuréeSec = int(time.Since(décrochéÀ).Seconds())
	return res, nil
}

func jouer(dialog *diago.DialogClientSession, fichier string) error {
	if _, err := os.Stat(fichier); err != nil {
		return fmt.Errorf("annonce introuvable : %w", err)
	}
	pb, err := dialog.PlaybackCreate()
	if err != nil {
		return err
	}
	_, err = pb.PlayFile(fichier)
	return err
}
