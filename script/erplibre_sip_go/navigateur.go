// © 2026 TechnoLibre (http://www.technolibre.ca)
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

package main

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"net"
	"strconv"
	"time"

	"github.com/emiago/diago"
	"github.com/emiago/sipgo"
	"github.com/emiago/sipgo/sip"
	"github.com/pion/rtp"
)

// Le softphone d'un navigateur, servi sans PBX.
//
// diago tient le SIP sur WebSocket ; tout le média est à nous, parce que le
// navigateur exige ICE et que diago n'en a pas. `RespondSDP` est le point
// d'accroche : il répond 200 OK avec NOTRE description et ne crée aucune
// session média de son côté.
//
// L'ordre est imposé par le protocole et ne se réarrange pas : SDP échangé,
// puis ICE conclu, puis DTLS, puis le son. Chaque étape a besoin de ce que la
// précédente a appris — l'adresse du pair vient d'ICE, les clés SRTP viennent
// de DTLS.

const (
	// DélaiPairICE borne l'attente d'une vérification de connectivité valide.
	// Un navigateur sur la même machine conclut en quelques millisecondes ;
	// au-delà de cinq secondes, c'est qu'il ne nous atteint pas.
	DélaiPairICE = 5 * time.Second

	// PériodeSondePair espace les regards sur l'agent ICE. C'est court parce
	// que le navigateur, lui, chronomètre.
	PériodeSondePair = 20 * time.Millisecond

	// DélaiRaccrochage borne l'envoi du BYE. Il part sur une connexion déjà
	// ouverte : au-delà de quelques secondes, c'est que le navigateur est
	// parti, et l'appel est de toute façon fini.
	DélaiRaccrochage = 5 * time.Second
)

// ServirNavigateur écoute les appels SIP sur WebSocket jusqu'à l'arrêt.
//
// `bind` s'écrit « hôte:port ». Sur la boucle locale, aucun certificat n'est
// nécessaire : les navigateurs tiennent « localhost » pour un contexte sûr et
// y ouvrent le micro. Depuis une autre machine il faudra du « wss:// », donc
// du TLS, donc un mandataire inverse.
func ServirNavigateur(ctx context.Context, bind string, o OptionsModem,
	écho bool, gardien *Gardien) error {
	hôte, portTexte, err := net.SplitHostPort(bind)
	if err != nil {
		return fmt.Errorf("adresse d'écoute %q : %w", bind, err)
	}
	port, err := strconv.Atoi(portTexte)
	if err != nil {
		return fmt.Errorf("port %q : %w", portTexte, err)
	}

	// Le matériel AVANT le service, et non au premier appel : un softphone
	// qui s'enregistre sur un service condamné laisse croire que tout est en
	// place, et la panne ne se découvre qu'une fois quelqu'un décroché.
	if !écho {
		carte, err := carteOuDéfaut(o.Carte)
		if err != nil {
			return err
		}
		slog.Info("carte son du modem retenue", "carte", carte)
	}

	ua, err := sipgo.NewUA()
	if err != nil {
		return err
	}
	defer ua.Close()

	// Un serveur à nous, pour y greffer REGISTER avant que diago n'y pose
	// ses propres gestionnaires. Sans cela sipgo répond « méthode non
	// permise », et un softphone qui échoue à s'enregistrer ne compose
	// jamais : l'appel n'est même pas tenté.
	srv, err := sipgo.NewServer(ua)
	if err != nil {
		return err
	}
	srv.OnRegister(func(req *sip.Request, tx sip.ServerTransaction) {
		if !gardien.Autoriser(req, tx) {
			return
		}
		accepterInscription(req, tx)
	})

	dg := diago.NewDiago(ua,
		diago.WithServer(srv),
		diago.WithTransport(diago.Transport{
			ID:        "ws",
			Transport: "ws",
			BindHost:  hôte,
			BindPort:  port,
		}))
	slog.Info("softphone en écoute", "ws", "ws://"+bind, "echo", écho)

	return dg.Serve(ctx, func(d *diago.DialogServerSession) {
		// L'INVITE est défié lui aussi : une inscription authentifiée ne
		// prouve rien de l'appel qui suit, et c'est l'appel qui dépense.
		if !gardien.AutoriserDialogue(d) {
			return
		}
		// PAS de `Hangup` ici. Un softphone de navigateur se présente avec un
		// contact en « .invalid » — la RFC 7118 le veut ainsi, il n'a aucune
		// adresse joignable — et un BYE construit dessus part en résolution
		// DNS qui échoue bruyamment. Un appel refusé se refuse par une
		// RÉPONSE à l'INVITE, ce que fait `servirUnAppel` ; un appel déjà
		// établi, c'est au navigateur de le raccrocher.
		if err := servirUnAppel(ctx, d, hôte, o, écho); err != nil {
			slog.Error("appel du navigateur abandonné", "err", err)
		}
		// On rend TOUJOURS sans erreur : diago raccrocherait de lui-même, et
		// son BYE partirait vers le contact « .invalid » du navigateur, en
		// résolution DNS vouée à l'échec. Le softphone constate le silence et
		// raccroche, ce qui est le seul chemin qui fonctionne des deux côtés.
	})
}

// accepterInscription répond 200 OK à toute inscription.
//
// Aucune authentification, et c'est un choix qu'il faut voir : le service
// n'écoute que sur la boucle locale, où quiconque peut de toute façon lire la
// mémoire du processus. Le jour où il écoutera ailleurs, cette fonction est
// le premier endroit à reprendre — avant même le TLS.
func accepterInscription(req *sip.Request, tx sip.ServerTransaction) {
	réponse := sip.NewResponseFromRequest(req, sip.StatusOK, "OK", nil)
	// Le contact est renvoyé tel quel, avec la durée demandée : sip.js s'en
	// sert pour programmer son renouvellement.
	if contact := req.Contact(); contact != nil {
		réponse.AppendHeader(sip.HeaderClone(contact))
	}
	if expire := req.GetHeader("Expires"); expire != nil {
		réponse.AppendHeader(sip.HeaderClone(expire))
	}
	slog.Info("inscription acceptée", "de", req.From().Address.User)
	if err := tx.Respond(réponse); err != nil {
		slog.Error("réponse d'inscription non transmise", "err", err)
	}
}

// ConstruireBye prépare un BYE que le navigateur puisse recevoir.
//
// La destination est la SOURCE de l'INVITE et non le contact : celui d'un
// softphone de navigateur porte un domaine en « .invalid », que la RFC 7118
// impose puisqu'il n'a aucune adresse joignable. Résolu en DNS, il ne mène
// nulle part. Imposer la source fait repartir la requête par la connexion
// WebSocket déjà ouverte, ce que la RFC 5626 prescrit pour un dialogue établi
// par ce transport.
func ConstruireBye(invite *sip.Request) (*sip.Request, error) {
	contact := invite.Contact()
	if contact == nil {
		return nil, fmt.Errorf("aucun contact dans l'INVITE")
	}
	bye := sip.NewRequest(sip.BYE, contact.Address)
	bye.SetTransport(invite.Transport())
	bye.SetDestination(invite.Source())
	return bye, nil
}

func servirUnAppel(ctx context.Context, d *diago.DialogServerSession, hôte string,
	o OptionsModem, écho bool) error {
	offre, err := LireOffre(d.InviteRequest.Body())
	if err != nil {
		return err
	}
	slog.Info("offre reçue", "de", d.FromUser(), "mid", offre.Mid)

	// La ligne AVANT la réponse, et c'est tout l'ordre qui compte ici.
	//
	// Répondre 200 OK puis découvrir que le modem est inaccessible laisse un
	// dialogue établi qu'il faut défaire — et un softphone de navigateur ne
	// se raccroche pas depuis le serveur. En ouvrant la ligne d'abord, un
	// échec devient une simple réponse d'erreur à l'INVITE : le softphone
	// affiche « indisponible » et rien ne reste ouvert.
	var ligne *LigneModem
	if !écho {
		ligne, err = OuvrirLigne(ctx, d, o)
		if err != nil {
			refuser(d, err)
			return err
		}
		defer ligne.Fermer()
	}

	locale, err := NouvelleIdentitéICE()
	if err != nil {
		return err
	}
	agent := &AgentICELite{
		Locale:   locale,
		Distante: IdentitéICE{Ufrag: offre.Ufrag, MotDePasse: offre.MotDePasse},
	}

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

	réponse := RéponseSDP{
		Adresse:   net.ParseIP(hôte),
		Port:      socket.Port(),
		Identité:  locale,
		Empreinte: empreinte,
		Mid:       offre.Mid,
		Bundle:    offre.Bundle,
		Session:   uint64(time.Now().Unix()),
	}
	if err := d.RespondSDP(réponse.Construire()); err != nil {
		return fmt.Errorf("réponse SDP : %w", err)
	}

	pair, err := attendreLePair(défiler, agent)
	if err != nil {
		return err
	}
	slog.Info("ICE conclu", "pair", pair)

	session, err := ÉtablirDTLS(défiler, socket.ConduitDTLS(), pair,
		certificat, offre.Empreinte)
	if err != nil {
		return err
	}
	slog.Info("DTLS établi, le son peut circuler")

	if écho {
		return renvoyerLeSon(défiler, socket, session)
	}

	// Les deux bouts peuvent raccrocher, et chacun doit emporter l'autre.
	//
	// Côté ligne : le modem est la seule source qui sache que le
	// correspondant a raccroché — sans cette veille, le softphone afficherait
	// un appel en cours sur une ligne retombée.
	//
	// Côté navigateur : son BYE termine le dialogue SIP, et rien n'en
	// découlerait pour le modem. L'appel cellulaire resterait ouvert, donc
	// facturé, après que l'écran a dit « terminé ».
	go func() {
		ligne.AttendreFin(défiler)
		arrêter()
	}()
	go func() {
		select {
		case <-d.Context().Done():
			slog.Info("le softphone a raccroché")
			arrêter()
		case <-défiler.Done():
		}
	}()

	err = RelierAuModem(défiler, socket, session, ligne.Carte)
	// Raccrocher le SIP à notre tour : le navigateur ne peut pas deviner que
	// la ligne cellulaire est tombée, et personne d'autre ne le lui dira.
	raccrocherLeSoftphone(ctx, d)
	return err
}

// raccrocherLeSoftphone envoie un BYE que le navigateur puisse recevoir.
//
// Le BYE ordinaire vise le contact de l'appelant, et celui d'un softphone de
// navigateur porte un domaine en « .invalid » — la RFC 7118 le veut ainsi,
// puisqu'il n'a aucune adresse joignable. Résolu en DNS, ce nom ne mène nulle
// part et le BYE n'est jamais transmis : l'appel reste affiché comme actif.
//
// On lui impose donc la SOURCE de l'INVITE comme destination, ce qui le fait
// repartir par la connexion WebSocket déjà ouverte — le chemin que la RFC 5626
// prescrit pour les requêtes d'un dialogue établi par ce transport.
func raccrocherLeSoftphone(ctx context.Context, d *diago.DialogServerSession) {
	invite := d.InviteRequest
	bye, err := ConstruireBye(invite)
	if err != nil {
		slog.Warn("le softphone ne sera pas raccroché", "err", err)
		return
	}

	minuté, arrêter := context.WithTimeout(ctx, DélaiRaccrochage)
	defer arrêter()
	if err := d.WriteBye(minuté, bye); err != nil {
		slog.Warn("raccrochage du softphone", "err", err)
		return
	}
	slog.Info("softphone raccroché", "vers", invite.Source())
}

// refuser répond à l'INVITE plutôt que d'établir puis défaire.
func refuser(d *diago.DialogServerSession, cause error) {
	slog.Warn("appel refusé avant d'être établi", "err", cause)
	if err := d.Respond(sip.StatusServiceUnavailable, "Service Unavailable", nil); err != nil {
		slog.Error("refus non transmis", "err", err)
	}
}

// LigneModem est un appel cellulaire en cours, prêt à porter du son.
type LigneModem struct {
	Carte string

	modem *Modem
}

// AttendreFin rend la main quand le correspondant raccroche.
//
// Le modem est la SEULE source qui le sache : ni le navigateur ni le SIP n'ont
// de vue sur la ligne cellulaire. On l'interroge donc, à la cadence que
// `attendreFinAppel` fixe.
func (l *LigneModem) AttendreFin(ctx context.Context) {
	if l.modem == nil {
		return
	}
	attendreFinAppel(ctx, l.modem)
}

// Fermer raccroche et referme le canal voix.
//
// On raccroche QUOI QU'IL ARRIVE : un appel laissé ouvert continue de
// facturer, et le modem ne le libère pas de lui-même.
func (l *LigneModem) Fermer() {
	if l.modem == nil {
		return
	}
	if err := l.modem.Raccrocher(); err != nil {
		slog.Warn("raccrochage", "err", err)
	}
	if err := l.modem.FermerVoixUSB(); err != nil {
		slog.Warn("canal voix USB non refermé", "err", err)
	}
	_ = l.modem.Close()
	l.modem = nil
}

// appelerParLaSIM compose le numéro du softphone et relie les deux sens.
//
// L'ordre des réglages du modem est celui d'`AppelerParModem`, et il n'est pas
// arrangeable : le canal voix USB s'ouvre AVANT la composition — le modem fige
// son routage quand la voix s'établit et refuse alors la commande — puis se
// RÉAFFIRME au décroché, l'ouverture faite avant ne survivant pas à
// l'établissement. Chaque réglage referme et rouvre le périphérique USB : tous
// passent avant le moindre flux audio, sans quoi le pont meurt et l'appel
// devient muet sans rien dire.
func OuvrirLigne(ctx context.Context, d *diago.DialogServerSession,
	o OptionsModem) (*LigneModem, error) {

	numéro, err := NuméroValide(d.ToUser())
	if err != nil {
		return nil, fmt.Errorf("numero compose (%q) : %w", d.ToUser(), err)
	}

	// La carte AVANT la composition : la chercher après le décroché ferait
	// découvrir son absence quand quelqu'un a déjà répondu, et la minute est
	// alors facturée pour rien.
	carte, err := carteOuDéfaut(o.Carte)
	if err != nil {
		return nil, err
	}

	m, err := OuvrirModem(o.Port)
	if err != nil {
		return nil, expliquerPort(err)
	}

	ligne := &LigneModem{modem: m, Carte: carte}
	if o.AudMod != ModeAudioInchangé {
		if err := m.RéglerModeAudio(o.AudMod); err != nil {
			slog.Warn("mode audio non réglé", "err", err)
		}
	}
	voixOuverte := true
	if err := m.OuvrirVoixUSB(o.ModePCM); err != nil {
		slog.Warn("canal voix USB non ouvert", "err", err)
		voixOuverte = false
	}

	if err := m.Composer(numéro); err != nil {
		ligne.Fermer()
		return nil, err
	}
	slog.Info("composition lancée par la SIM", "numero", numéro)

	// Le softphone sonne pendant que la ligne sonne : sans ce 180, il reste
	// muet et l'appelant croit que rien ne part.
	if err := d.Ringing(); err != nil {
		slog.Warn("sonnerie non annoncée au softphone", "err", err)
	}

	if _, err := attendreDécroché(ctx, m); err != nil {
		ligne.Fermer()
		return nil, fmt.Errorf("sans reponse : %w", err)
	}
	slog.Info("décroché sur la ligne cellulaire")

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

	return ligne, nil
}

// expliquerPort ajoute à un refus d'accès la seule cause qui le produise ici.
//
// L'utilisateur peut être DANS le groupe « dialout » selon /etc/group et ne
// pas l'avoir dans ce processus : la liste des groupes se fige à l'ouverture
// de session. « id » montre alors le bon groupe et l'ouverture échoue quand
// même, ce qui envoie chercher du côté des droits du fichier, où il n'y a
// rien.
func expliquerPort(err error) error {
	if !errors.Is(err, fs.ErrPermission) {
		return err
	}
	return fmt.Errorf("%w — le groupe « dialout » manque a CE processus meme "+
		"si « id » le montre : relancer par « sg dialout -c ... », ou rouvrir "+
		"la session", err)
}

// attendreLePair rend l'adresse dès qu'une vérification ICE valide arrive.
//
// On SONDE au lieu d'attendre un signal : l'agent est déjà partagé entre la
// boucle de tri et cet appel, et lui ajouter un canal ferait un second
// chemin de synchronisation pour la même information.
func attendreLePair(ctx context.Context, agent *AgentICELite) (net.Addr, error) {
	limite := time.After(DélaiPairICE)
	tic := time.NewTicker(PériodeSondePair)
	defer tic.Stop()
	for {
		if pair := agent.Pair(); pair != nil {
			return pair, nil
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-limite:
			return nil, fmt.Errorf(
				"aucune verification ICE valide en %s : le navigateur ne nous atteint pas",
				DélaiPairICE)
		case <-tic.C:
		}
	}
}

// renvoyerLeSon déprotège ce qui arrive et le renvoie tel quel.
//
// C'est l'épreuve de l'étage : entendre sa propre voix prouve qu'ICE, DTLS,
// SRTP et RTP tiennent tous les quatre, sans qu'aucun modem soit en jeu. Ce
// qui suit remplacera ce renvoi par le pont vers la carte du modem.
func renvoyerLeSon(ctx context.Context, socket *SocketMédia, session *SessionSRTP) error {
	var séquence uint16
	var horodatage uint32
	var reçus, renvoyés, illisibles int

	// Un silence peut venir de partout ; ce relevé dit LEQUEL des trois
	// endroits est muet — rien ne rentre, rien ne se déchiffre, ou rien ne
	// sort. Sans lui, un appel sans son ne laisse aucune trace.
	relevé := time.NewTicker(2 * time.Second)
	defer relevé.Stop()

	for {
		select {
		case <-ctx.Done():
			slog.Info("fin du renvoi", "recus", reçus, "renvoyes", renvoyés,
				"illisibles", illisibles)
			return nil
		case <-relevé.C:
			slog.Info("son", "recus", reçus, "renvoyes", renvoyés,
				"illisibles", illisibles)
		case protégé, ouvert := <-socket.RTP():
			if !ouvert {
				return nil
			}
			reçus++
			clair, err := session.Déprotéger(protégé)
			if err != nil {
				illisibles++
				if illisibles == 1 {
					// La première dit la cause ; les suivantes seraient la
					// même erreur cinquante fois par seconde.
					slog.Warn("paquet indéchiffrable — clés SRTP ou profil",
						"err", err)
				}
				continue
			}
			var reçu rtp.Packet
			if err := reçu.Unmarshal(clair); err != nil {
				continue
			}

			renvoi := &rtp.Packet{
				Header: rtp.Header{
					Version:        2,
					PayloadType:    ChargePCMU,
					SequenceNumber: séquence,
					Timestamp:      horodatage,
					SSRC:           SSRCSortant,
				},
				Payload: reçu.Payload,
			}
			séquence++
			// Un échantillon par octet en PCMU, à 8 kHz : l'horodatage RTP
			// avance donc de la taille de la charge utile.
			horodatage += uint32(len(reçu.Payload))

			brut, err := renvoi.Marshal()
			if err != nil {
				continue
			}
			sortant, err := session.Protéger(brut)
			if err != nil {
				slog.Debug("protection impossible", "err", err)
				continue
			}
			if err := socket.Émettre(sortant); err != nil {
				return err
			}
			renvoyés++
			if renvoyés == 1 {
				slog.Info("premier paquet renvoyé : le son circule")
			}
		}
	}
}
