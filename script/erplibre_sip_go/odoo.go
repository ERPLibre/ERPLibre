// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// Le service parle à Odoo, et se passe de lui quand il ne répond pas.
//
// Deux échanges, tous deux signés : on demande les réglages au démarrage, on
// dépose les messages après coup. Le reste du temps la ligne n'a besoin de
// personne — un serveur arrêté ne doit pas rendre le répondeur muet, et c'est
// précisément quand tout va mal que quelqu'un laisse un message.

const (
	// VariableOdooURL et VariableSecret nomment ce qui vient de
	// l'environnement. Le secret n'est ni dans le dépôt — publié sous
	// AGPL-3 — ni dans la base : il authentifie justement ce qui écrit
	// dedans.
	VariableOdooURL = "ERPLIBRE_ODOO_URL"
	VariableSecret  = "ERPLIBRE_SMS_HMAC_SECRET"

	// EnTêteSignature est celle que le contrôleur vérifie.
	EnTêteSignature = "X-Erplibre-Signature"

	// DélaiOdoo borne chaque échange. Court À DESSEIN : Odoo est une
	// commodité ici, pas une dépendance, et l'attendre longtemps retarderait
	// un décroché qui, lui, court après la boîte vocale de l'opérateur.
	DélaiOdoo = 5 * time.Second

	// NomAppareil sert à cloisonner les jetons anti-rejeu.
	NomAppareil = "repondeur"

	// VariableAppareil nomme la fiche de passerelle que ce modem représente.
	// C'est la même que celle de l'agent SMS du modem : le même matériel ne
	// doit pas apparaître sous deux fiches dans Odoo.
	VariableAppareil = "ERPLIBRE_SMS_DEVICE"
)

// LienOdoo dit où joindre Odoo et avec quel secret.
type LienOdoo struct {
	URL    string
	Secret string
	Client *http.Client
	// Appareil est l'identifiant de la passerelle dans Odoo. Vide, ce qui
	// dépend d'une fiche de passerelle ne part pas.
	Appareil string
}

// OuvrirLienOdoo lit l'environnement. Rend nil quand rien n'est configuré.
//
// Nil et non une erreur : ne pas avoir d'Odoo est une installation valide —
// la TUI suffit à régler le répondeur et à lire ses messages.
func OuvrirLienOdoo() *LienOdoo {
	url, secret := os.Getenv(VariableOdooURL), os.Getenv(VariableSecret)
	if url == "" || secret == "" {
		return nil
	}
	return &LienOdoo{
		URL:      url,
		Secret:   secret,
		Client:   &http.Client{Timeout: DélaiOdoo},
		Appareil: os.Getenv(VariableAppareil),
	}
}

// envoyer signe la charge au nom du répondeur et rend la réponse décodée.
func (l *LienOdoo) envoyer(route string, charge map[string]any) (map[string]any, error) {
	return l.envoyerComme(route, charge, NomAppareil)
}

// envoyerComme signe la charge au nom d'un appareil donné.
//
// Les routes de la passerelle retrouvent leur fiche PAR cet identifiant : il
// doit être celui de la fiche, et non un nom de service.
func (l *LienOdoo) envoyerComme(route string, charge map[string]any,
	appareil string) (map[string]any, error) {
	jeton := make([]byte, 16)
	if _, err := rand.Read(jeton); err != nil {
		return nil, err
	}
	charge["ts"] = time.Now().Unix()
	charge["nonce"] = hex.EncodeToString(jeton)
	charge["device"] = appareil

	corps, err := json.Marshal(charge)
	if err != nil {
		return nil, err
	}
	somme := hmac.New(sha256.New, []byte(l.Secret))
	somme.Write(corps)

	requête, err := http.NewRequest(http.MethodPost, l.URL+route, bytes.NewReader(corps))
	if err != nil {
		return nil, err
	}
	requête.Header.Set("Content-Type", "application/json")
	requête.Header.Set(EnTêteSignature, "sha256="+hex.EncodeToString(somme.Sum(nil)))

	réponse, err := l.Client.Do(requête)
	if err != nil {
		return nil, err
	}
	defer réponse.Body.Close()

	var rendu map[string]any
	if err := json.NewDecoder(réponse.Body).Decode(&rendu); err != nil {
		return nil, fmt.Errorf("reponse illisible (%d) : %w", réponse.StatusCode, err)
	}
	if réponse.StatusCode != http.StatusOK || rendu["ok"] != true {
		return nil, fmt.Errorf("refus d'Odoo (%d) : %v", réponse.StatusCode, rendu["error"])
	}
	return rendu, nil
}

// RéglagesDepuisOdoo remplace ce que le disque disait, ou le laisse tel quel.
//
// Odoo FAIT AUTORITÉ quand il répond : c'est là que le nombre de sonneries et
// l'annonce se règlent à plusieurs. Quand il ne répond pas, les réglages
// locaux tiennent — c'est tout l'intérêt d'en garder une copie, et le moment
// où on en a le plus besoin.
//
// L'annonce est écrite À CÔTÉ de celle du disque et non par-dessus : garder
// les deux permet de repartir sur la locale si Odoo en sert une illisible.
func RéglagesDepuisOdoo(l *LienOdoo, locaux RéglagesRépondeur) RéglagesRépondeur {
	if l == nil {
		return locaux
	}
	rendu, err := l.envoyer("/erplibre_repondeur/reglages", map[string]any{})
	if err != nil {
		slog.Warn("reglages du repondeur non obtenus d'Odoo : ceux du disque"+
			" font foi", "err", err)
		return locaux
	}
	brut, _ := json.Marshal(rendu["reglages"])
	var distants struct {
		Actif            bool   `json:"actif"`
		Sonneries        int    `json:"sonneries"`
		DuréeMaxSecondes int    `json:"duree_max_secondes"`
		AnnonceNom       string `json:"annonce_nom"`
		AnnonceB64       string `json:"annonce_b64"`
	}
	if err := json.Unmarshal(brut, &distants); err != nil {
		slog.Warn("reglages d'Odoo illisibles : ceux du disque font foi", "err", err)
		return locaux
	}

	fusionnés := locaux
	fusionnés.Actif = distants.Actif
	fusionnés.Sonneries = distants.Sonneries
	fusionnés.DuréeMaxSecondes = distants.DuréeMaxSecondes
	if annonce := écrireAnnonce(locaux, distants.AnnonceNom, distants.AnnonceB64); annonce != "" {
		fusionnés.Annonce = annonce
	}
	slog.Info("reglages du repondeur pris dans Odoo",
		"actif", fusionnés.Actif, "sonneries", fusionnés.Sonneries)
	return fusionnés.Normaliser()
}

// écrireAnnonce dépose l'annonce d'Odoo et rend son chemin, ou une chaîne
// vide quand il n'y en a pas.
func écrireAnnonce(locaux RéglagesRépondeur, nom, b64 string) string {
	if b64 == "" {
		return ""
	}
	son, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		slog.Warn("annonce d'Odoo illisible : celle du disque est gardée", "err", err)
		return ""
	}
	dossier := locaux.Dossier
	if dossier == "" {
		dossier = os.TempDir()
	}
	if err := os.MkdirAll(dossier, 0o700); err != nil {
		slog.Warn("annonce d'Odoo non ecrite", "err", err)
		return ""
	}
	if nom == "" {
		nom = "annonce.wav"
	}
	chemin := filepath.Join(dossier, "odoo_"+filepath.Base(nom))
	if err := os.WriteFile(chemin, son, 0o600); err != nil {
		slog.Warn("annonce d'Odoo non ecrite", "err", err)
		return ""
	}
	return chemin
}

// TéléverserMessage dépose un message dans Odoo et marque le compagnon.
//
// Le compagnon est marqué APRÈS la réponse et non avant : une réponse perdue
// fait réessayer au prochain démarrage, et le contrôleur reconnaît la
// référence plutôt que de créer un doublon. L'inverse — marquer puis envoyer
// — perdrait le message pour de bon.
func TéléverserMessage(l *LienOdoo, m *Message) error {
	if l == nil {
		return nil
	}
	son, err := os.ReadFile(m.Fichier)
	if err != nil {
		return err
	}
	_, err = l.envoyer("/erplibre_repondeur/message", map[string]any{
		"numero":         m.Numéro,
		"recu_le":        horodatageOdoo(m.Début),
		"duree_secondes": m.DuréeSecondes,
		"crete":          m.CrêteMaximale,
		"nom_fichier":    filepath.Base(m.Fichier),
		"audio_b64":      base64.StdEncoding.EncodeToString(son),
		"reference":      filepath.Base(m.Fichier),
	})
	if err != nil {
		return err
	}
	m.TéléverséOdoo = true
	return ÉcrireCompagnon(m)
}

// TéléverserCeQuiAttend rattrape ce qu'une panne d'Odoo a laissé sur disque.
//
// Appelé au démarrage : c'est le seul moment où l'on sait qu'Odoo vient
// peut-être de revenir, et un message enregistré pendant sa panne n'a sinon
// aucune occasion de monter.
func TéléverserCeQuiAttend(l *LienOdoo, dossier string) int {
	if l == nil || dossier == "" {
		return 0
	}
	messages, err := ListerMessages(dossier)
	if err != nil {
		return 0
	}
	montés := 0
	for i := range messages {
		if messages[i].TéléverséOdoo {
			continue
		}
		if err := TéléverserMessage(l, &messages[i]); err != nil {
			slog.Warn("message non televerse : il reste sur disque",
				"fichier", messages[i].Fichier, "err", err)
			continue
		}
		montés++
	}
	if montés > 0 {
		slog.Info("messages en attente televerses", "nombre", montés)
	}
	return montés
}

// horodatageOdoo traduit un instant RFC 3339 vers ce qu'Odoo stocke : UTC,
// sans fuseau. Un horodatage local y serait lu comme de l'UTC, et les
// messages s'afficheraient décalés de plusieurs heures.
func horodatageOdoo(rfc string) string {
	instant, err := time.Parse(time.RFC3339, rfc)
	if err != nil {
		return time.Now().UTC().Format("2006-01-02 15:04:05")
	}
	return instant.UTC().Format("2006-01-02 15:04:05")
}

// SignalerMessagerie transmet à la passerelle l'état de la boîte vocale.
//
// Sans lien ou sans fiche désignée, rien ne part et ce n'est pas une erreur :
// l'état reste au journal du service, ce qui suffit à une installation sans
// Odoo.
func SignalerMessagerie(l *LienOdoo, attente bool, lu time.Time) error {
	if l == nil || l.Appareil == "" {
		return nil
	}
	_, err := l.envoyerComme("/erplibre_sms/voicemail", map[string]any{
		"attente": attente,
		"lu_le":   lu.UTC().Format("2006-01-02 15:04:05"),
	}, l.Appareil)
	return err
}
