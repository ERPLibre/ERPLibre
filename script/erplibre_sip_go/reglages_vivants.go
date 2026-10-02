// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"log/slog"
	"net/http"
	"sync"
	"time"
)

const (
	// ÂgeRéglagesTolérable borne la vieillesse des réglages au moment de
	// décider si le répondeur prend l'appel.
	//
	// Deux fois la cadence de la veille : au-delà, la lecture périodique n'a
	// pas eu lieu — une ligne tenue longtemps, ou un Odoo muet — et les
	// valeurs peuvent dater d'avant un changement à l'écran.
	ÂgeRéglagesTolérable = 2 * CadenceMessagerie

	// DélaiRéglagesÀLAppel borne la relecture faite pendant qu'un appel
	// arrive.
	//
	// Bien plus court que `DélaiOdoo` : la boîte vocale de l'opérateur prend
	// l'appel au bout d'une trentaine de secondes, et le répondeur court après
	// elle. Attendre Odoo cinq secondes sur ce chemin mangerait un sixième du
	// budget pour un réglage qui n'a probablement pas changé.
	DélaiRéglagesÀLAppel = 2 * time.Second
)

// RéglagesVivants garde les réglages du répondeur et les relit.
//
// Ils étaient lus UNE fois au démarrage et passés par valeur : changer le
// nombre de sonneries ou l'annonce dans Odoo ne produisait alors aucun effet
// avant un redémarrage du service, et rien ne le disait. Un réglage qui ne
// s'applique pas est pire qu'un réglage absent.
//
// Deux chemins de lecture, pour deux besoins qui ne se recouvrent pas :
// la veille relit à intervalle, ligne libre ; l'arrivée d'un appel relit
// seulement si les valeurs sont vieilles, et sous un délai court.
type RéglagesVivants struct {
	mu      sync.RWMutex
	valeurs RéglagesRépondeur
	// Dernière lecture RÉUSSIE. Une lecture en échec ne la déplace pas : sinon
	// un Odoo muet passerait pour frais et empêcherait la prochaine tentative.
	luÀ  time.Time
	lien *LienOdoo
}

// NouveauxRéglagesVivants part des réglages du disque.
//
// Sans lien Odoo, ils ne changeront jamais et c'est une installation valide :
// la TUI suffit à régler le répondeur.
func NouveauxRéglagesVivants(lien *LienOdoo, locaux RéglagesRépondeur) *RéglagesVivants {
	return &RéglagesVivants{valeurs: locaux.Normaliser(), lien: lien}
}

// Valeurs rend une COPIE des réglages courants.
//
// Une copie et non un pointeur : l'appel qui décide s'en sert sur plusieurs
// secondes, et des valeurs qui changeraient en cours de route donneraient un
// répondeur qui décroche selon un réglage et enregistre selon un autre.
func (r *RéglagesVivants) Valeurs() RéglagesRépondeur {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.valeurs
}

// Relire interroge Odoo et garde ce qu'il dit. Rend true si quelque chose a
// changé, ce qui est la seule chose qui mérite une ligne de journal.
func (r *RéglagesVivants) Relire() bool {
	return r.relire(r.lien)
}

// RelireSiVieux ne relit que si la dernière lecture réussie est trop ancienne,
// et sous un délai court : ce chemin sert pendant qu'un appel arrive.
func (r *RéglagesVivants) RelireSiVieux(âge, délai time.Duration) bool {
	r.mu.RLock()
	fraîche := !r.luÀ.IsZero() && time.Since(r.luÀ) < âge
	r.mu.RUnlock()
	if fraîche {
		return false
	}
	return r.relire(r.lienPressé(délai))
}

// lienPressé rend le même lien avec un client plus impatient.
//
// Le lien d'origine n'est pas modifié : il sert aussi au téléversement d'un
// message, qui porte un WAV et a besoin de tout son délai.
func (r *RéglagesVivants) lienPressé(délai time.Duration) *LienOdoo {
	if r.lien == nil {
		return nil
	}
	pressé := *r.lien
	pressé.Client = &http.Client{Timeout: délai}
	return &pressé
}

func (r *RéglagesVivants) relire(lien *LienOdoo) bool {
	if lien == nil {
		return false
	}
	// Les valeurs COURANTES servent de repli, et non celles du disque : une
	// coupure passagère ne doit pas ramener le répondeur à un réglage qu'on a
	// déjà remplacé. `RéglagesDepuisOdoo` les rend telles quelles en cas
	// d'échec.
	avant := r.Valeurs()
	r.mu.RLock()
	premier := r.luÀ.IsZero()
	r.mu.RUnlock()
	après, err := RéglagesDepuisOdoo(lien, avant)

	r.mu.Lock()
	changé := après != avant
	r.valeurs = après
	// La date ne bouge que sur une lecture qui a ABOUTI : sinon un Odoo muet
	// passerait pour frais, et la tentative suivante serait sautee.
	if err == nil {
		r.luÀ = time.Now()
	}
	r.mu.Unlock()

	// Deux faits nouveaux, et eux seuls : qu'Odoo ait repondu une premiere
	// fois, et qu'il dise autre chose qu'avant. Une ligne a chaque lecture
	// remplirait le journal de la meme phrase, et la panne qu'on y cherche
	// serait noyee dedans.
	switch {
	case err != nil:
		// `RéglagesDepuisOdoo` a deja dit pourquoi.
	case premier:
		slog.Info("reglages du repondeur pris dans Odoo",
			"actif", après.Actif, "sonneries", après.Sonneries,
			"duree_max_s", après.DuréeMaxSecondes)
	case changé:
		slog.Info("reglages du repondeur changes dans Odoo",
			"actif", après.Actif, "sonneries", après.Sonneries,
			"duree_max_s", après.DuréeMaxSecondes)
	}
	return changé
}
