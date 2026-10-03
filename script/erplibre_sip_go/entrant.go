// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"sync/atomic"
	"time"

	"github.com/emiago/sipgo"
	"github.com/emiago/sipgo/sip"
)

// Recevoir un appel, et non plus seulement en passer.
//
// Le sens est inverse de l'appel sortant, et deux choses changent avec lui.
// C'est NOUS qui offrons le SDP — le navigateur répond — donc le rôle DTLS
// passe à « actpass » et il choisit d'être actif. Et c'est nous qui présentons
// l'INVITE, à une adresse que seul le registre connaît : le contact d'un
// softphone de navigateur ne mène nulle part.

const (
	// CadenceSurveillanceEntrants espace les regards sur la ligne. Une
	// sonnerie dure des secondes ; regarder plus souvent ne gagne rien et
	// occupe le port AT, que les commandes d'un appel en cours se
	// disputeraient.
	CadenceSurveillanceEntrants = time.Second

	// ÉchecsAvantRéouverture : au bout de combien d'interrogations sans
	// réponse on reprend le port.
	//
	// Assez pour ne pas rouvrir sur un modem momentanément fâché — il refuse
	// une commande pendant qu'il bascule de réseau — et assez peu pour que
	// la ligne ne reste pas sourde une minute après un réveil. La veille
	// interroge chaque seconde, donc dix vaut dix secondes.
	ÉchecsAvantRéouverture = 10

	// DélaiSonnerieSoftphone borne l'attente d'un décroché au navigateur.
	// Au-delà, l'appelant a raccroché ou personne n'est devant l'écran.
	DélaiSonnerieSoftphone = 45 * time.Second
)

// VeillerSurLesEntrants présente au softphone les appels qui arrivent.
func VeillerSurLesEntrants(ctx context.Context, m *Modem, o OptionsModem,
	hôte string, registre *Registre, dialogues *sipgo.DialogClientCache,
	vivants *RéglagesVivants, secrets *Secrets, dossierRecettes string) {

	if err := m.AnnoncerAppelant(); err != nil {
		// Sans CLIP l'appel se présente sans numéro : on continue, un appel
		// anonyme valant mieux qu'aucun appel.
		slog.Warn("annonce de l'appelant non activée", "err", err)
	}
	// Une ligne laissée ouverte se facture, et rien ne la libère : un
	// processus tué en pleine conversation n'exécute pas ses défausses, et
	// le modem tient l'appel jusqu'à ce que le correspondant raccroche. On
	// vérifie donc au démarrage, plutôt que de le découvrir en constatant
	// qu'aucun appel n'entre — un appel en cours occupe la ligne.
	libérerUneLigneOubliée(m)
	slog.Info("veille des appels entrants")

	var enCours bool
	var muets int
	// La messagerie de l'opérateur se lit dans la même boucle, et non dans
	// une seconde : les deux passent par le même port, et deux boucles
	// entrelaceraient leurs lectures avec celles d'un appel qui arrive.
	messagerie := &VeilleMessagerie{
		Lien: OuvrirLienOdoo(), Fichier: CheminÉtatMessagerie(),
	}
	var messagerieLueÀ time.Time
	relève := &Relève{}
	var refusDit string
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(CadenceSurveillanceEntrants):
		}

		// On interroge la ligne AVANT de demander un numéro : `AppelEntrant`
		// rend une chaîne vide aussi bien quand rien ne sonne que quand la
		// commande échoue, et les deux ne se réparent pas au même endroit.
		appels, err := m.Appels()
		if err != nil {
			muets++
			if muets == 1 || muets%60 == 0 {
				slog.Warn("la ligne ne repond pas a l'interrogation",
					"err", err, "tentatives", muets)
			}
			// Une serie d'echecs n'est pas un modem fache, c'est un port
			// mort : une mise en veille suffit a le faire disparaitre du bus
			// et revenir sous un autre ttyUSB. Sans cette reprise, le
			// service reste vivant et sourd — systemd ne le relance pas
			// puisqu'il n'est pas mort, et plus aucun appel n'entre.
			if muets%ÉchecsAvantRéouverture == 0 {
				if err := m.Rouvrir(); err != nil {
					slog.Warn("port du modem non rouvert",
						"err", err, "tentatives", muets)
				} else {
					slog.Info("port du modem rouvert", "apres_echecs", muets)
					muets = 0
				}
			}
			continue
		}
		muets = 0
		décrireLaLigne(appels)

		// Seulement ligne libre : pendant une sonnerie ou une conversation,
		// le port sert à l'appel, et le drapeau peut attendre une minute.
		if !uneLigneTient(appels) && time.Since(messagerieLueÀ) >= CadenceMessagerie {
			messagerieLueÀ = time.Now()
			attente, err := m.LireAttenteMessagerie()
			messagerie.Observer(attente, err, messagerieLueÀ)
			// Les reglages voyagent dans la meme respiration : un tour de plus
			// n'ajoute rien au port du modem, et un nombre de sonneries change
			// a l'ecran s'applique alors en moins d'une minute.
			vivants.Relire()

			// Le relèvement se décide ICI, la ligne libre et le drapeau tout
			// juste lu. Ailleurs, il faudrait relire l'un ou l'autre, et
			// appeler sur un drapeau d'il y a une minute ferait un appel que
			// rien ne justifie plus.
			décision := relève.Décider(vivants.Valeurs(), attente, err == nil,
				secrets.ADéjàLeNIP())
			if décision.Motif != "" && décision.Motif != refusDit {
				// Une fois par motif : répété chaque minute, il noierait le
				// journal et on cesserait de le lire.
				refusDit = décision.Motif
				slog.Warn("relevement de la boite vocale impossible",
					"motif", décision.Motif)
			}
			if décision.Relever {
				refusDit = ""
				if _, err := Relever(ctx, m, o, vivants.Valeurs(), décision,
					secrets.NIP(), dossierRecettes, time.Now()); err != nil {
					slog.Warn("relevement de la boite vocale en echec",
						"err", err)
				}
				// La ligne vient de servir : on repart sur un tour neuf
				// plutôt que d'enchaîner sur un état d'avant l'appel.
				continue
			}
		}

		numéro := m.AppelEntrant()
		if numéro == "" {
			enCours = false
			continue
		}
		if enCours {
			// La ligne sonne encore pour l'appel qu'on présente déjà : le
			// représenter ferait sonner le softphone en boucle.
			continue
		}
		enCours = true
		slog.Info("appel entrant", "de", numéro)
		// Une ligne tenue longtemps saute les lectures periodiques : on relit
		// ici si les valeurs sont vieilles, sous un delai court. La boite
		// vocale de l'operateur prend l'appel au bout d'une trentaine de
		// secondes, et ce chemin ne doit pas manger ce budget.
		vivants.RelireSiVieux(ÂgeRéglagesTolérable, DélaiRéglagesÀLAppel)
		// Une COPIE pour toute la duree de l'appel : des valeurs qui
		// changeraient en cours de route feraient decrocher selon un reglage
		// et enregistrer selon un autre.
		répondeur := vivants.Valeurs()
		if err := présenterAuSoftphone(ctx, m, o, hôte, registre, dialogues,
			numéro, répondeur); err != nil {
			slog.Error("appel entrant non presente", "de", numéro, "err", err)
			if err := m.Raccrocher(); err != nil {
				slog.Warn("raccrochage", "err", err)
			}
		}
	}
}

// libérerUneLigneOubliée raccroche ce qu'une exécution précédente a laissé.
func libérerUneLigneOubliée(m *Modem) {
	appels, err := m.Appels()
	if err != nil {
		slog.Warn("etat de la ligne inconnu au demarrage", "err", err)
		return
	}
	for _, a := range appels {
		if !a.Voix() {
			continue
		}
		slog.Warn("une ligne etait restee ouverte : on raccroche",
			"etat", a.État, "numero", a.Numéro)
		if err := m.Raccrocher(); err != nil {
			slog.Error("raccrochage impossible", "err", err)
		}
		return
	}
}

// décrireLaLigne annonce tout appel VOIX, quel que soit son état.
//
// Le veilleur ne présente que les états 4 et 5 — un appel entrant qui n'a pas
// été pris. Si le modem en montrait un autre, rien ne le dirait et la panne
// se lirait « aucun appel ne rentre » alors que la ligne parle. On journalise
// donc ce qu'elle dit, sans le juger.
//
// Le canal de données LTE est écarté : il est actif en permanence, et
// l'annoncer noierait le seul événement qui compte.
func décrireLaLigne(appels []ÉtatAppel) {
	for _, a := range appels {
		if !a.Voix() {
			continue
		}
		slog.Info("appel voix sur la ligne", "etat", a.État,
			"sortant", a.Sortant, "numero", a.Numéro,
			"presente", a.État == ÉtatSonnerie || a.État == ÉtatEnAttente)
	}
}

// présenterAuSoftphone fait sonner le navigateur, puis relie les deux bouts.
func présenterAuSoftphone(ctx context.Context, m *Modem, o OptionsModem,
	hôte string, registre *Registre, dialogues *sipgo.DialogClientCache,
	numéro string, répondeur RéglagesRépondeur) error {

	// L'operateur renvoie vers sa messagerie au bout de quelques dizaines de
	// secondes : le temps que met le softphone a decrocher est donc ce qui
	// decide du succes, et il doit se voir.
	sonnerieÀ := time.Now()

	inscription, joignable := premierJoignable(registre)
	if !joignable && !répondeur.Actif {
		return fmt.Errorf("aucun poste inscrit : personne a faire sonner")
	}

	// La SIM ne porte qu'une conversation : un appel sortant en cours a la
	// ligne, et la lui prendre couperait quelqu'un qui parle.
	if !m.PrendreLaLigne() {
		return fmt.Errorf("la ligne porte deja une conversation")
	}
	rendue := false
	rendre := func() {
		if !rendue {
			rendue = true
			m.RendreLaLigne()
		}
	}
	defer rendre()

	// Le mode audio AVANT le canal, comme à l'appel sortant : chaque réglage
	// referme et rouvre le périphérique USB, et les traitements prévus pour
	// un combiné brouillent un signal qui arrive déjà numérisé.
	if o.AudMod != ModeAudioInchangé {
		if err := m.RéglerModeAudio(o.AudMod); err != nil {
			slog.Warn("mode audio non réglé", "err", err)
		}
	}

	// Le canal voix AVANT que la voix ne s'établisse : le modem fige son
	// routage au décroché et refuse la commande ensuite. Même contrainte qu'à
	// l'appel sortant, dans l'autre sens.
	voixOuverte := true
	if err := m.OuvrirVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non ouvert", "err", err)
		voixOuverte = false
	}

	// Rendre le matériel est une chose, prévenir le softphone en est une
	// autre, et l'ORDRE compte : le second passe par le réseau et peut
	// prendre des secondes, pendant lesquelles la ligne est déjà libre. Les
	// faire dans l'autre ordre raccroche la SIM APRÈS qu'un appel suivant l'a
	// prise, et c'est cet appel-là qui tombe.
	libérée := false
	libérer := func() {
		if libérée {
			return
		}
		libérée = true
		if err := m.Raccrocher(); err != nil {
			slog.Warn("raccrochage", "err", err)
		}
		if voixOuverte {
			_ = m.FermerVoixUSB()
		}
		rendre()
	}
	defer libérer()

	// Personne d'inscrit, mais un répondeur : il prend l'appel sans qu'on
	// monte le média ni ICE, dont rien n'aurait l'usage.
	if !joignable {
		return prendreLeMessageSurLaLigne(ctx, m, o, répondeur, numéro)
	}

	locale, err := NouvelleIdentitéICE()
	if err != nil {
		return err
	}
	agent := &AgentICELite{Locale: locale}
	socket, err := NouveauSocketMédia(net.JoinHostPort(hôte, "0"), agent)
	if err != nil {
		return err
	}
	défiler, arrêter := context.WithCancel(ctx)
	defer arrêter()
	defer socket.Fermer()
	go func() {
		if err := socket.Trier(défiler); err != nil {
			slog.Error("tri des paquets média arrêté", "err", err)
		}
	}()

	certificat, empreinte, err := NouveauCertificat()
	if err != nil {
		return err
	}
	offre := DescriptionSDP{
		Adresse:   net.ParseIP(hôte),
		Port:      socket.Port(),
		Identité:  locale,
		Empreinte: empreinte,
		Mid:       "0",
		Bundle:    true,
		Session:   uint64(time.Now().Unix()),
		Rôle:      RôleAuChoix,
	}

	// La sonnerie du softphone est BORNÉE par le répondeur quand il en existe
	// un : au-delà, la boîte vocale de l'opérateur prend l'appel et le
	// message nous échappe. C'est une course, et on choisit de la gagner.
	sonnerie := défiler
	if répondeur.Actif {
		minuté, fin := context.WithTimeout(défiler, répondeur.DélaiAvantDécroché())
		defer fin()
		sonnerie = minuté
	}

	// L'appelant peut raccrocher PENDANT la sonnerie, et rien ne le disait au
	// softphone : il sonnait jusqu'au bout de son delai, et decrocher alors ne
	// trouvait plus personne. On surveille donc la ligne le temps qu'elle
	// sonne.
	raccroché := &atomic.Bool{}
	surveillé, couper := context.WithCancel(sonnerie)
	defer couper()
	go surveillerLAppelant(surveillé, m, raccroché, couper)

	session, err := sonner(surveillé, dialogues, inscription, hôte, numéro, offre.Construire())
	if err != nil {
		if raccroché.Load() {
			// Plus de ligne a enregistrer : prendre le message ferait decrocher
			// dans le vide, et le repondeur garderait un fichier muet.
			return fmt.Errorf("l'appelant a raccroche pendant la sonnerie")
		}
		if répondeur.Actif {
			// Le MOTIF, et pas seulement le fait : sans lui, un softphone qui
			// renonce en quelques millisecondes se lit comme une sonnerie qui
			// a dure son temps, et on cherche du cote du repondeur.
			slog.Info("le softphone n'a pas pris : le repondeur decroche",
				"de", numéro, "sonneries", répondeur.Normaliser().Sonneries,
				"attente", time.Since(sonnerieÀ).Round(time.Millisecond),
				"motif", err)
			return prendreLeMessageSurLaLigne(ctx, m, o, répondeur, numéro)
		}
		return err
	}
	defer session.Close()

	corps := session.InviteResponse.Body()
	slog.Info("softphone a repondu", "code", session.InviteResponse.StatusCode,
		"sdp_octets", len(corps))
	réponse, err := LireOffre(corps)
	if err != nil {
		// Le SDP au journal : sans lui, « reponse SDP du softphone » ne dit
		// pas QUEL attribut manque, et l'appel part en boite vocale pendant
		// qu'on cherche. Il ne porte que des identifiants ephemeres.
		slog.Debug("reponse SDP refusee", "sdp", string(corps))
		return fmt.Errorf("reponse SDP du softphone : %w", err)
	}
	agent.Distante = IdentitéICE{Ufrag: réponse.Ufrag, MotDePasse: réponse.MotDePasse}

	// Décrocher la ligne SEULEMENT quand le navigateur a répondu : décrocher
	// plus tôt ferait payer une communication que personne n'écoute.
	if err := m.Répondre(); err != nil {
		return fmt.Errorf("decrochage de la ligne (ATA) : %w", err)
	}
	slog.Info("ligne décrochée pour le softphone",
		"depuis_la_sonnerie", time.Since(sonnerieÀ).Round(time.Millisecond))

	// La ligne a-t-elle VRAIMENT ete prise ? « OK » a l'ATA ne prouve rien :
	// un appel deja renvoye vers la messagerie de l'operateur repond OK et
	// retombe aussitot. On regarde l'etat plutot que de croire la commande.
	if appels, err := m.Appels(); err == nil {
		tenue := false
		for _, a := range appels {
			if a.Voix() {
				tenue = true
			}
		}
		if !tenue {
			return fmt.Errorf(
				"la ligne ne tient plus apres le decroche : l'appel est " +
					"probablement parti vers la messagerie pendant la sonnerie")
		}
	}
	if o.VolumeÉcoute >= 0 {
		if err := m.RéglerVolumeÉcoute(o.VolumeÉcoute); err != nil {
			slog.Warn("volume d'écoute refusé", "err", err)
		}
	}
	if err := m.RéglerRéductionBruit(o.Bruit); err != nil {
		slog.Warn("réduction de bruit refusée", "err", err)
	}
	if voixOuverte {
		if err := m.RéaffirmerVoixUSB(o.ModePCM); err != nil {
			slog.Warn("canal voix USB non réaffirmé", "err", err)
		}
	}

	pair, err := attendreLePair(défiler, agent)
	if err != nil {
		return err
	}
	slog.Info("ICE conclu", "pair", pair)

	// Serveur DTLS ici aussi : on a offert « actpass », le navigateur a
	// répondu « active ».
	sécurité, err := ÉtablirDTLS(défiler, socket.ConduitDTLS(), pair,
		certificat, réponse.Empreinte)
	if err != nil {
		return err
	}
	slog.Info("DTLS établi, le son peut circuler")

	// Les deux bouts, comme pour un appel sortant : la ligne qui retombe
	// arrête le pont, et le raccrochage du softphone aussi. Sans le second,
	// l'appel cellulaire continuerait, facturé, après que l'écran a dit
	// « terminé ».
	go func() {
		attendreFinAppel(défiler, m)
		arrêter()
	}()
	go func() {
		select {
		case <-session.Context().Done():
			slog.Info("le softphone a raccroché, la ligne suit")
			arrêter()
		case <-défiler.Done():
		}
	}()

	err = RelierAuModem(défiler, socket, sécurité, o.Carte)
	libérer()

	// Le correspondant a raccroché : c'est à NOUS de le dire au softphone.
	// Rien d'autre ne le fera — il ne voit que du silence, et Odoo garde
	// l'appel affiché comme en cours. On ne le fait que si le dialogue tient
	// encore : quand c'est LUI qui a raccroché, son BYE nous est déjà
	// parvenu et en renvoyer un serait répondre à une porte fermée.
	if session.Context().Err() == nil {
		_ = raccrocherLAppelant(ctx, session, inscription.Source)
	}
	return err
}

// ConstruireInviteEntrant prépare l'INVITE qui fait sonner le softphone.
//
// Isolée pour être vérifiable : une omission ici ne se voit qu'en appelant, et
// le prix d'un essai est un appel qui part en boîte vocale.
func ConstruireInviteEntrant(inscription Inscription, hôte, numéro string,
	offre []byte) *sip.Request {

	invite := sip.NewRequest(sip.INVITE, inscription.Contact)
	// Le « tag » n'est pas décoratif : la RFC 3261 §8.1.1.3 l'exige sur le
	// « From » de toute requête qui établit un dialogue, et c'est une moitié
	// de son identifiant. Sans lui la pile refuse la réponse — « missing tag
	// param in From header » — et l'appel part en boîte vocale pendant qu'on
	// cherche du côté du SDP.
	de := sip.NewParams()
	de.Add("tag", sip.GenerateTagN(16))
	invite.AppendHeader(&sip.FromHeader{
		// Le numéro de l'appelant en guise d'identité : c'est ce que le
		// softphone affiche, et la seule chose utile à qui décroche.
		Address: sip.Uri{User: numéro, Host: hôte},
		Params:  de,
	})
	invite.AppendHeader(sip.NewHeader("Content-Type", "application/sdp"))
	invite.SetBody(offre)
	invite.SetTransport(inscription.Transport)
	// La destination est celle d'où l'inscription est venue : viser le
	// contact enverrait la requête en résolution DNS d'un nom « .invalid ».
	invite.SetDestination(inscription.Source)

	return invite
}

// sonner présente l'INVITE au poste inscrit et attend son décroché.
func sonner(ctx context.Context, dialogues *sipgo.DialogClientCache,
	inscription Inscription, hôte, numéro string, offre []byte) (
	*sipgo.DialogClientSession, error) {

	invite := ConstruireInviteEntrant(inscription, hôte, numéro, offre)

	session, err := dialogues.WriteInvite(ctx, invite)
	if err != nil {
		return nil, fmt.Errorf("presentation au softphone : %w", err)
	}

	// La fenêtre de sonnerie se referme avec la CAUSE que sipgo reconnaît,
	// d'où qu'elle vienne — le répondeur la borne par le contexte reçu, et
	// notre propre délai la borne à défaut. Sans cette cause, sipgo annule
	// lui-même l'INVITE avec une requête qui ne porte pas de destination :
	// elle part résoudre en DNS le contact « .invalid » du navigateur,
	// échoue, et c'est CETTE panne de résolution qui remonte à la place du
	// seul fait utile — personne n'a décroché. L'annulation est alors la
	// nôtre, qui vise la connexion ouverte.
	// Détaché du contexte reçu, et rattaché à la main juste après : un
	// contexte dérivé hérite de la CAUSE de son parent dès que celui-ci
	// expire, et cette cause-là gagnerait la course contre la nôtre.
	sonnerie, cesser := context.WithCancelCause(context.WithoutCancel(ctx))
	defer cesser(nil)
	échéance := time.AfterFunc(DélaiSonnerieSoftphone, func() {
		cesser(sipgo.WaitAnswerForceCancelErr)
	})
	defer échéance.Stop()
	fini := make(chan struct{})
	defer close(fini)
	go func() {
		select {
		case <-ctx.Done():
			cesser(sipgo.WaitAnswerForceCancelErr)
		case <-fini:
		}
	}()

	début := time.Now()
	if err := session.WaitAnswer(sonnerie, sipgo.AnswerOptions{}); err != nil {
		if context.Cause(sonnerie) == sipgo.WaitAnswerForceCancelErr {
			err = fmt.Errorf("aucun decroche en %s",
				time.Since(début).Round(time.Millisecond))
		}
		// On ANNULE avant de fermer : fermer ne dit rien au navigateur, qui
		// sonnerait alors jusqu'a ce que quelqu'un decroche une ligne deja
		// retombee.
		annulation := ConstruireAnnulation(invite, inscription.Source)
		if erreurAnnulation := session.WriteRequest(annulation); erreurAnnulation != nil {
			slog.Warn("annulation de la sonnerie non transmise",
				"err", erreurAnnulation)
		}
		_ = session.Close()
		return nil, fmt.Errorf("sans reponse du softphone : %w", err)
	}
	// L'acquittement est construit ici plutot que par `Ack` : celui-ci vise
	// le contact de la reponse, en « .invalid », et part en resolution DNS.
	if err := session.WriteAck(ctx,
		ConstruireAckEntrant(invite, session.InviteResponse, inscription.Source)); err != nil {
		_ = session.Close()
		return nil, fmt.Errorf("acquittement : %w", err)
	}
	slog.Info("softphone décroché", "poste", inscription.Poste)
	return session, nil
}

// raccrocherLAppelant met fin au dialogue vers le softphone.
func raccrocherLAppelant(ctx context.Context, session *sipgo.DialogClientSession,
	destination string) error {

	if session.InviteResponse == nil {
		return nil
	}
	bye := ConstruireByeSortant(session.InviteRequest, session.InviteResponse,
		destination)
	minuté, arrêter := context.WithTimeout(ctx, DélaiRaccrochage)
	defer arrêter()
	if err := session.WriteBye(minuté, bye); err != nil {
		// La ligne cellulaire est DÉJÀ rendue quand on arrive ici : ce qui
		// manque est l'acquittement du poste, et sans lui son écran peut
		// garder l'appel affiché alors que plus personne n'est au bout.
		slog.Warn("raccrochage du softphone sans acquittement",
			"err", err, "delai", DélaiRaccrochage)
		return err
	}
	slog.Info("softphone raccroché : la ligne est retombée")
	return nil
}

// surveillerLAppelant coupe la sonnerie dès que la ligne cellulaire retombe.
//
// Le modem sérialise ses commandes AT : interroger la ligne depuis ce fil est
// sûr, et n'entrelace rien avec ce que fait la présentation.
func surveillerLAppelant(ctx context.Context, m *Modem, raccroché *atomic.Bool,
	couper func()) {

	tic := time.NewTicker(CadenceSurveillanceEntrants)
	defer tic.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tic.C:
			appels, err := m.Appels()
			// Une interrogation en échec ne prouve pas un raccrochage : couper
			// la sonnerie dessus renverrait l'appel en boîte vocale pour un
			// port occupé une fraction de seconde.
			if err != nil || uneLigneTient(appels) {
				continue
			}
			slog.Info("l'appelant a raccroche pendant la sonnerie")
			raccroché.Store(true)
			couper()
			return
		}
	}
}

// ConstruireAnnulation prépare le CANCEL d'un INVITE resté sans réponse.
//
// Sans lui, le softphone sonne INDÉFINIMENT : la bibliothèque n'expose pas
// d'annulation, et fermer la session côté serveur ne dit rien au navigateur.
// Il continue donc de sonner après que l'appelant a raccroché, et décrocher
// alors ne trouve plus personne — la ligne cellulaire est déjà retombée.
//
// Un CANCEL ne s'adresse pas au dialogue mais à la TRANSACTION, et trois
// choses l'y rattachent : la même branche de Via, le même numéro de séquence,
// et l'URI de requête de l'INVITE — pas le contact de la réponse, qui n'existe
// pas encore. Le « To » reste donc sans étiquette.
func ConstruireAnnulation(invite *sip.Request, destination string) *sip.Request {
	annulation := sip.NewRequest(sip.CANCEL, *invite.Recipient.Clone())
	annulation.SipVersion = invite.SipVersion

	// La branche du Via est ce qui désigne la transaction à annuler : elle se
	// recopie telle quelle, et une branche neuve ouvrirait une transaction
	// inconnue du navigateur.
	if h := invite.Via(); h != nil {
		annulation.AppendHeader(sip.HeaderClone(h))
	}
	sauts := sip.MaxForwardsHeader(70)
	annulation.AppendHeader(&sauts)
	if h := invite.From(); h != nil {
		annulation.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.To(); h != nil {
		annulation.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.CallID(); h != nil {
		annulation.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.CSeq(); h != nil {
		séquence := sip.CSeqHeader{SeqNo: h.SeqNo, MethodName: sip.CANCEL}
		annulation.AppendHeader(&séquence)
	}

	annulation.SetTransport(invite.Transport())
	annulation.SetSource(invite.Source())
	annulation.SetDestination(destination)
	return annulation
}

// ConstruireByeSortant prépare le BYE d'un appel présenté par ce service.
//
// Le dernier de la famille : INVITE, acquittement et maintenant raccrochage
// visent tous le contact du softphone, en « .invalid », et partent en
// résolution DNS. La destination est donc imposée ici aussi — la connexion
// WebSocket déjà ouverte, comme la RFC 5626 le prescrit.
//
// Le numéro de séquence n'est pas incrémenté ici : la bibliothèque le fait à
// l'écriture, à partir du dernier numéro du dialogue. L'avancer une seconde
// fois ferait sauter un cran et le softphone jetterait la requête.
func ConstruireByeSortant(invite *sip.Request, réponse *sip.Response,
	destination string) *sip.Request {

	cible := &invite.Recipient
	if contact := réponse.Contact(); contact != nil {
		cible = &contact.Address
	}
	bye := sip.NewRequest(sip.BYE, *cible.Clone())
	bye.SipVersion = invite.SipVersion

	sauts := sip.MaxForwardsHeader(70)
	bye.AppendHeader(&sauts)
	if h := invite.From(); h != nil {
		bye.AppendHeader(sip.HeaderClone(h))
	}
	// Le « To » vient de la RÉPONSE : c'est là que le softphone a posé sa
	// moitié de l'identifiant du dialogue.
	if h := réponse.To(); h != nil {
		bye.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.CallID(); h != nil {
		bye.AppendHeader(sip.HeaderClone(h))
	}

	bye.SetTransport(invite.Transport())
	bye.SetSource(invite.Source())
	bye.SetDestination(destination)
	return bye
}

// ConstruireAckEntrant prépare l'acquittement du 200 OK du softphone.
//
// Recopie de ce que fait la bibliothèque, à une chose près qui décide de
// tout : la DESTINATION. Son acquittement vise le contact de la réponse, en
// « .invalid » — la RFC 7118 l'impose à un softphone de navigateur, faute
// d'adresse joignable — et part en résolution DNS. Sans acquittement, le
// navigateur retransmet son 200 OK puis abandonne, et la ligne cellulaire est
// raccrochee pendant qu'elle sonnait encore : l'operateur la renvoie alors
// vers sa messagerie.
func ConstruireAckEntrant(invite *sip.Request, réponse *sip.Response,
	destination string) *sip.Request {

	cible := &invite.Recipient
	if contact := réponse.Contact(); contact != nil {
		cible = &contact.Address
	}
	ack := sip.NewRequest(sip.ACK, *cible.Clone())
	ack.SipVersion = invite.SipVersion

	// Le « From » vient de la requête et le « To » de la RÉPONSE : c'est là
	// que le softphone a posé sa moitié de l'identifiant du dialogue.
	if h := invite.From(); h != nil {
		ack.AppendHeader(sip.HeaderClone(h))
	}
	if h := réponse.To(); h != nil {
		ack.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.CallID(); h != nil {
		ack.AppendHeader(sip.HeaderClone(h))
	}
	if h := invite.CSeq(); h != nil {
		ack.AppendHeader(sip.HeaderClone(h))
	}
	if cseq := ack.CSeq(); cseq != nil {
		// Même numéro que l'INVITE, méthode changée : c'est ce qui rattache
		// l'acquittement à la transaction qu'il clôt.
		cseq.MethodName = sip.ACK
	}
	sauts := sip.MaxForwardsHeader(70)
	ack.AppendHeader(&sauts)
	if h := invite.Contact(); h != nil {
		ack.AppendHeader(sip.HeaderClone(h))
	}

	ack.SetTransport(invite.Transport())
	ack.SetSource(invite.Source())
	ack.Laddr = invite.Laddr
	ack.SetDestination(destination)
	return ack
}

// premierJoignable rend un poste inscrit, s'il y en a un.
//
// Un seul poste est fait sonner, et non tous : la ligne cellulaire ne porte
// qu'une conversation, et présenter le même appel à plusieurs écrans ferait
// décrocher deux personnes sur une seule ligne.
func premierJoignable(registre *Registre) (Inscription, bool) {
	joignables := registre.Joignables(time.Now())
	if len(joignables) == 0 {
		return Inscription{}, false
	}
	return joignables[0], true
}

// prendreLeMessageSurLaLigne décroche à la place de personne et enregistre.
//
// Le décroché est ici et non chez l'appelant : il ne se produit QU'UNE FOIS
// le softphone renoncé, et décrocher plus tôt ferait payer une communication
// que personne n'écoute — la même règle que pour un appel présenté.
//
// La ligne est raccrochée par la défausse de l'appelant, avec le canal voix :
// deux chemins qui raccrochent laisseraient l'un des deux le faire en trop.
func prendreLeMessageSurLaLigne(ctx context.Context, m *Modem, o OptionsModem,
	r RéglagesRépondeur, numéro string) error {

	carte, err := carteOuDéfaut(o.Carte)
	if err != nil {
		return fmt.Errorf("repondeur sans carte son : %w", err)
	}
	if err := m.Répondre(); err != nil {
		return fmt.Errorf("decrochage du repondeur (ATA) : %w", err)
	}
	// La ligne a-t-elle VRAIMENT été prise ? « OK » à l'ATA ne prouve rien :
	// un appel déjà renvoyé vers la messagerie de l'opérateur répond OK et
	// retombe aussitôt. On enregistrerait alors sa musique d'attente.
	if appels, err := m.Appels(); err == nil && !uneLigneTient(appels) {
		return fmt.Errorf(
			"la ligne ne tient plus apres le decroche du repondeur : " +
				"l'appel est probablement parti vers la messagerie")
	}
	// Le canal voix se RÉAFFIRME au décroché : l'ouverture faite avant la
	// sonnerie ne survit pas à l'établissement de la voix, et sans cela on
	// enregistre le silence d'un canal qui n'est plus routé vers l'USB.
	if err := m.RéaffirmerVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non réaffirmé", "err", err)
	}
	// Ce que le modem dit de son canal, et non ce qu'on lui a demandé : la
	// commande rend OK même quand le routage reste fermé, et le message est
	// alors muet dans les deux sens sans que rien d'autre ne le signale.
	if état, err := m.ÉtatVoixUSB(); err != nil {
		slog.Warn("canal voix du repondeur illisible", "err", err)
	} else {
		slog.Info("canal voix du repondeur", "qpcmv", état,
			"mode_demande", o.ModePCM)
	}
	message, err := PrendreLeMessage(ctx, carte, r, numéro)
	if err != nil || message == nil {
		return err
	}
	// Le téléversement est fait ICI et non par une file : un message qui ne
	// monte pas reste sur disque avec son compagnon, et le démarrage suivant
	// le rattrape. Une file en mémoire le perdrait au premier redémarrage.
	if err := TéléverserMessage(OuvrirLienOdoo(), message); err != nil {
		slog.Warn("message non televerse : il attend sur disque",
			"fichier", message.Fichier, "err", err)
	}
	return nil
}

// uneLigneTient dit si un appel VOIX est encore établi.
func uneLigneTient(appels []ÉtatAppel) bool {
	for _, a := range appels {
		if a.Voix() {
			return true
		}
	}
	return false
}
