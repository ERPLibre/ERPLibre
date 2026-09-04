// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"fmt"
	"strconv"
	"sync"
	"time"

	"github.com/emiago/sipgo/sip"
)

// Qui est joignable, et par où.
//
// Répondre 200 OK à une inscription sans rien en retenir suffit tant que le
// service ne fait qu'ATTENDRE des appels. Dès qu'il doit en présenter un, il
// lui faut savoir où frapper — et le contact d'un softphone de navigateur ne
// le dit pas : la RFC 7118 lui impose un domaine « .invalid », faute d'adresse
// joignable. Seule l'adresse D'OÙ l'inscription est venue mène quelque part.

const (
	// DuréeInscriptionDéfaut vaut quand la requête n'exprime rien. Une heure
	// est ce que proposent les clients courants.
	DuréeInscriptionDéfaut = time.Hour

	// DuréeInscriptionMax borne ce qu'un client peut demander. Une
	// inscription qui survit des jours désigne longtemps une connexion morte,
	// et un appel entrant part alors vers personne.
	DuréeInscriptionMax = 12 * time.Hour
)

// Inscription retient ce qu'il faut pour rappeler un poste.
type Inscription struct {
	Poste     string
	Contact   sip.Uri
	Source    string
	Transport string
	Expire    time.Time
}

// Expirée dit si l'inscription ne vaut plus.
func (i Inscription) Expirée(maintenant time.Time) bool {
	return !i.Expire.After(maintenant)
}

// Registre garde les postes joignables.
type Registre struct {
	mutex  sync.Mutex
	postes map[string]Inscription
}

// NouveauRegistre rend un registre vide.
func NouveauRegistre() *Registre {
	return &Registre{postes: map[string]Inscription{}}
}

// Inscrire retient un poste d'après sa requête, ou le retire.
//
// Une durée nulle est un DÉSABONNEMENT et non une inscription qui expire
// aussitôt : c'est ainsi qu'un client annonce qu'il s'en va, et le confondre
// avec une inscription laisserait une entrée morte le temps d'un nettoyage.
func (r *Registre) Inscrire(req *sip.Request, maintenant time.Time) (Inscription, error) {
	contact := req.Contact()
	if contact == nil {
		return Inscription{}, fmt.Errorf("inscription sans contact")
	}
	from := req.From()
	if from == nil || from.Address.User == "" {
		return Inscription{}, fmt.Errorf("inscription sans nom de poste")
	}

	durée := duréeDemandée(req, contact)
	poste := from.Address.User
	if durée <= 0 {
		r.Retirer(poste)
		return Inscription{Poste: poste}, nil
	}
	if durée > DuréeInscriptionMax {
		durée = DuréeInscriptionMax
	}

	inscription := Inscription{
		Poste:   poste,
		Contact: contact.Address,
		// L'adresse VUE, et non l'hôte du contact : c'est la seule qui mène
		// au navigateur, dont le contact ne porte qu'un nom en « .invalid ».
		Source:    req.Source(),
		Transport: req.Transport(),
		Expire:    maintenant.Add(durée),
	}
	r.mutex.Lock()
	r.postes[poste] = inscription
	r.mutex.Unlock()
	return inscription, nil
}

// Trouver rend l'inscription d'un poste, si elle vaut encore.
func (r *Registre) Trouver(poste string, maintenant time.Time) (Inscription, bool) {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	inscription, connue := r.postes[poste]
	if !connue || inscription.Expirée(maintenant) {
		return Inscription{}, false
	}
	return inscription, true
}

// Joignables rend les inscriptions encore valides.
func (r *Registre) Joignables(maintenant time.Time) []Inscription {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	var vivantes []Inscription
	for _, inscription := range r.postes {
		if !inscription.Expirée(maintenant) {
			vivantes = append(vivantes, inscription)
		}
	}
	return vivantes
}

// Retirer oublie un poste.
func (r *Registre) Retirer(poste string) {
	r.mutex.Lock()
	delete(r.postes, poste)
	r.mutex.Unlock()
}

// duréeDemandée lit la durée voulue, du contact d'abord puis de l'en-tête.
//
// L'ordre n'est pas indifférent : la RFC 3261 §10.2.4 fait primer le paramètre
// du contact sur l'en-tête « Expires », et un client qui se désabonne d'un
// seul contact le fait par ce paramètre.
func duréeDemandée(req *sip.Request, contact *sip.ContactHeader) time.Duration {
	if valeur, présent := contact.Params.Get("expires"); présent {
		if secondes, err := strconv.Atoi(valeur); err == nil {
			return time.Duration(secondes) * time.Second
		}
	}
	if entête := req.GetHeader("Expires"); entête != nil {
		if secondes, err := strconv.Atoi(entête.Value()); err == nil {
			return time.Duration(secondes) * time.Second
		}
	}
	return DuréeInscriptionDéfaut
}
