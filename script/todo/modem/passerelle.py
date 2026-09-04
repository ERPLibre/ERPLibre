#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Agent qui fait du modem USB la passerelle SMS d'un serveur ERPLibre.

Le serveur ne joint JAMAIS cette machine : c'est elle qui interroge, en HTTPS
sortant, à intervalle réglé par le serveur. L'hôte du modem peut donc vivre
derrière une IP dynamique et un NAT d'opérateur, sans port ouvert ni tunnel —
c'est la propriété sur laquelle repose le module `erplibre_mobile_gateway`, et
la raison pour laquelle cet agent interroge au lieu d'écouter.

Le protocole est celui de l'application Android, sans un octet de différence :
trois routes, un corps JSON signé en HMAC-SHA256, horodaté, et protégé du rejeu
par un nonce à usage unique. Rien dans ces routes n'est propre à Android — ce
qui l'est, ce sont les CLÉS D'ÉTAT que le serveur juge, et la correspondance
est posée dans `etat_modem`.

Trois invariants gouvernent le code, et chacun protège d'un silence :

- **La séquence des rapports survit au redémarrage.** Le serveur refuse un
  rapport sans numéro de séquence et ignore ceux qui régressent. Un compteur
  gardé en mémoire ferait rejeter tous les rapports d'un agent relancé, et
  chaque envoi finirait « expiré » alors qu'il est parti.
- **Un travail déjà envoyé se RE-RAPPORTE au lieu d'être ignoré.** Le serveur
  repropose ce qu'il n'a pas vu confirmer. L'ignorer parce qu'on le connaît
  laisserait un envoi réussi mourir à son échéance.
- **Tout appel réclamé reçoit une réponse.** Le module n'a pas de cron
  d'expiration pour les appels : un appel réclamé et jamais rapporté reste
  « publié » pour toujours. Voir `SansAppels`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.request

#: Routes du protocole. Elles ne portent pas le nom du module : le module a
#: ete renomme, le protocole non, et tout appareil deja installe continue de
#: les appeler.
ROUTE_POLL = "/erplibre_sms/poll"
ROUTE_RAPPORT = "/erplibre_sms/report"
ROUTE_ENTRANTS = "/erplibre_sms/inbound"

ENTETE_SIGNATURE = "X-Erplibre-Signature"
PREFIXE_SIGNATURE = "sha256="

#: Le secret vit dans l'environnement du processus, jamais dans un fichier
#: versionne : ce depot est publie sous AGPL-3.
VARIABLE_SECRET = "ERPLIBRE_SMS_HMAC_SECRET"
VARIABLE_URL = "ERPLIBRE_SMS_URL"
VARIABLE_APPAREIL = "ERPLIBRE_SMS_DEVICE"

#: Annoncee au serveur, qui l'affiche sur la fiche de la passerelle. Le
#: prefixe distingue cet agent de l'application Android, dont les versions
#: sont des dates.
VERSION = "modem-1.0"

#: Materiel declare a chaque interrogation. Le serveur porte le meme choix sur
#: la fiche de la passerelle et signale un desaccord : une fiche restee
#: « telephone » jugerait le modem sur des criteres qu'il n'a pas.
MATERIEL = "modem"

DELAI_HTTP = 20

#: Rythme retenu tant que le serveur n'en a pas impose un autre. Il en donne un
#: a chaque interrogation : celui-ci ne sert qu'au tout premier tour.
INTERVALLE_DEFAUT = 60
SEGMENTS_PAR_MINUTE_DEFAUT = 24

#: Repos apres un tour rate, pour ne pas marteler un serveur a terre. Progressif
#: puis plafonne : une coupure de deux minutes ne doit pas coincer l'agent une
#: heure.
REPOS_APRES_ECHEC = (5, 15, 30, 60, 120)

#: Un travail termine reste connu ce temps-la, pour pouvoir etre re-rapporte si
#: le serveur le repropose. Au-dela il est oublie : le serveur l'a de toute
#: facon declare expire depuis longtemps, son echeance par defaut valant quinze
#: minutes.
RETENTION_TERMINES = 7 * 24 * 3600

#: Etat local d'un travail -> etat du protocole. « incertain » se rapporte
#: « submitted » : remis au reseau, issue inconnue. C'est le seul etat non
#: terminal cote serveur, donc le seul qui n'affirme rien de faux.
ETATS_RAPPORTES = {
    "envoye": "delivered",
    "echec": "failed",
    "incertain": "submitted",
}

#: Intervalle minimal entre deux remises au modem. Un envoi en rafale fait
#: refuser le suivant par le SMSC plus souvent qu'il ne gagne de temps.
ESPACEMENT_ENVOIS = 2.0

#: Alphabet GSM 03.38 de base. Recopie de la NORME, pas du module : les deux
#: processus peuvent tourner sur deux machines et ne partagent aucun code. Le
#: piege francophone est le meme des deux cotes — « Ç » majuscule y est, « ç »
#: minuscule N'Y EST PAS, si bien qu'un texte correctement accentue bascule en
#: UCS-2 et tombe a 70 caracteres par segment.
GSM7_BASE = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
#: Table d'extension : ces caracteres comptent DOUBLE.
GSM7_ETENDU = set("^{}\\[~]|€")


def segments(texte):
    """Nombre de segments qu'occupera ce texte sur le reseau.

    Sert au cadencement, et il faut le compter juste : sous-estimer envoie trop
    vite, surestimer ralentit un canal d'alerte. Les quatre bornes 160/153/70/67
    sont celles de la norme.
    """
    texte = texte or ""
    if all(c in GSM7_BASE or c in GSM7_ETENDU for c in texte):
        septets = sum(2 if c in GSM7_ETENDU else 1 for c in texte)
        if septets == 0:
            return 0
        return 1 if septets <= 160 else math.ceil(septets / 153)
    unites = len(texte.encode("utf-16-le")) // 2
    if unites == 0:
        return 0
    return 1 if unites <= 70 else math.ceil(unites / 67)


class ErreurTransport(Exception):
    """Le serveur n'a pas repondu, ou a repondu autre chose qu'un succes."""


def signer(secret, corps):
    """Signature de ces octets EXACTS, tels qu'ils partiront.

    Signer un dictionnaire puis le reserialiser produirait deux corps
    differents : la signature porte sur les octets, jamais sur la structure.
    """
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    empreinte = hmac.new(secret, corps, hashlib.sha256).hexdigest()
    return PREFIXE_SIGNATURE + empreinte


class Transport:
    """Parle au serveur : serialise, signe, poste, rend le JSON de reponse.

    `ouvrir` est injectable pour que le protocole se teste sans reseau. Sa
    signature : (url, corps, entetes) -> (statut, octets de reponse).
    """

    def __init__(self, base_url, secret, appareil, ouvrir=None, horloge=None):
        self.base_url = (base_url or "").rstrip("/")
        self.secret = secret
        self.appareil = appareil
        self.ouvrir = ouvrir or _ouvrir_http
        self.horloge = horloge or time.time

    def poster(self, route, charge):
        corps = json.dumps(
            dict(charge, device=self.appareil, ts=int(self.horloge()),
                 nonce=secrets.token_hex(16)),
            separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        entetes = {
            "Content-Type": "application/json",
            ENTETE_SIGNATURE: signer(self.secret, corps),
        }
        statut, reponse = self.ouvrir(self.base_url + route, corps, entetes)
        if statut != 200:
            raise ErreurTransport(
                "%s a repondu %s : %s" % (route, statut, _extrait(reponse))
            )
        try:
            return json.loads(reponse.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ErreurTransport("%s : reponse illisible (%s)" % (route, exc))


def _extrait(octets, limite=200):
    try:
        return octets.decode("utf-8", "replace")[:limite]
    except Exception:  # pragma: no cover - une erreur ne doit pas en cacher une
        return "<illisible>"


def _ouvrir_http(url, corps, entetes):
    requete = urllib.request.Request(url, data=corps, headers=entetes, method="POST")
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_HTTP) as reponse:
            return reponse.status, reponse.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ErreurTransport(str(exc))


class Etat:
    """Ce qui doit survivre a un redemarrage, dans un seul fichier JSON.

    Ecrit en 0600 et remplace d'un coup : il porte des numeros de telephone et
    le texte des messages, qui sont des donnees personnelles, et un fichier
    tronque par une coupure de courant perdrait la file d'envoi.
    """

    def __init__(self, chemin):
        self.chemin = chemin
        self.sequence = 0
        self.travaux = {}
        self.entrants_vus = []
        self._charger()

    def _charger(self):
        try:
            with open(self.chemin, encoding="utf-8") as fichier:
                donnees = json.load(fichier)
        except (OSError, ValueError):
            return
        self.sequence = int(donnees.get("sequence") or 0)
        self.travaux = dict(donnees.get("travaux") or {})
        self.entrants_vus = list(donnees.get("entrants_vus") or [])

    def enregistrer(self):
        dossier = os.path.dirname(self.chemin) or "."
        os.makedirs(dossier, exist_ok=True)
        descripteur, provisoire = tempfile.mkstemp(dir=dossier, prefix=".passerelle-")
        try:
            with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
                json.dump({
                    "sequence": self.sequence,
                    "travaux": self.travaux,
                    "entrants_vus": self.entrants_vus,
                }, fichier, ensure_ascii=False)
            os.chmod(provisoire, 0o600)
            os.replace(provisoire, self.chemin)
        except Exception:
            os.unlink(provisoire)
            raise

    def suivant(self):
        """Numero de sequence suivant, ecrit AVANT d'etre utilise.

        Le serveur refuse un rapport sans sequence et ignore une regression.
        Incrementer puis enregistrer, dans cet ordre, fait qu'une panne entre
        les deux saute des numeros — sans consequence, seule la croissance
        compte — la ou l'ordre inverse en rejouerait un.
        """
        self.sequence += 1
        self.enregistrer()
        return self.sequence

    def oublier_les_vieux(self, maintenant):
        """Retire les travaux termines depuis assez longtemps."""
        garde = {}
        for uuid, travail in self.travaux.items():
            fini = travail.get("fini_a")
            if fini and maintenant - fini > RETENTION_TERMINES:
                continue
            garde[uuid] = travail
        retires = len(self.travaux) - len(garde)
        self.travaux = garde
        # Les identifiants entrants suivent la meme borne, faute de date : on
        # garde les derniers, en nombre.
        if len(self.entrants_vus) > 500:
            self.entrants_vus = self.entrants_vus[-500:]
        return retires


class SansAppels:
    """Refuse tout appel, en le disant au serveur.

    Ce n'est PAS un bouchon : refuser est obligatoire. Le module tient les
    appels sans cron d'expiration — un appel reclame et jamais rapporte reste
    « publie » indefiniment, et personne ne saura qu'il n'a pas eu lieu.

    Pourquoi refuser plutot que composer : un appel dure des minutes, et le
    cycle de cet agent doit rendre la main en quelques secondes. Le tenir dans
    la boucle ferait manquer les interrogations, et le serveur declarerait la
    passerelle muette au bout de trois intervalles — l'alarme meme que cet
    agent existe pour ne pas declencher. Composer demande donc une execution
    separee, ce qui est un autre travail que celui-ci.
    """

    MOTIF = ("Cet agent tient les SMS, pas les appels : composer demande une "
             "execution separee du cycle d'interrogation.")

    def placer(self, numero):
        return False, self.MOTIF


class ModemManagerSMS:
    """Le modem, vu par ModemManager. Injectable pour que le reste se teste.

    On ne descend pas en AT : ModemManager gere l'encodage, le decoupage en
    segments et tient deja les ports. Lui reprendre le modem pour refaire ce
    qu'il fait bien n'ajouterait que des occasions de se tromper.
    """

    def __init__(self, index=None, device=None, messaging=None):
        from script.todo.modem import device as device_mod
        from script.todo.modem import messaging as messaging_mod

        self.device = device or device_mod
        self.messaging = messaging or messaging_mod
        self.index = index

    def _index(self):
        if self.index is None:
            self.index = self.device.premier_modem()
        return self.index

    def pret(self):
        """(pret, motif). « Pret » veut dire : la SIM est enregistree au reseau.

        Un modem muet fait OUBLIER son index. ModemManager en attribue un
        nouveau a un appareil rebranche, et un index retenu pour la vie de
        l'agent le laisserait interroger un modem qui n'existe plus — donc
        muet pour toujours apres un simple debranchement.
        """
        if not self.device.mmcli_present():
            return False, "ModemManager absent de cette machine."
        index = self._index()
        if index is None:
            return False, "Aucun modem visible."
        etat = self.device.etat(index)
        if not etat:
            self.index = None
            return False, "Le modem ne repond pas."
        if etat.get("etat") not in ("registered", "connected"):
            return False, "Modem non enregistre au reseau : %s." % etat.get("etat", "?")
        return True, etat.get("operateur") or ""

    def envoyer(self, numero, texte):
        index = self._index()
        if index is None:
            return False, "GATEWAY_SIM_ABSENT", "Aucun modem visible."
        ok, detail = self.messaging.envoyer(index, numero, texte)
        if ok:
            return True, "", ""
        return False, "GATEWAY_MODEM_ERROR", (detail or "").strip()[:256]

    def entrants(self):
        """Messages recus par le modem, non encore effaces."""
        index = self._index()
        if index is None:
            return []
        recus = []
        for ident, etat in self.messaging.lister(index):
            if etat != "received":
                continue
            message = self.messaging.lire(ident)
            if not message:
                continue
            recus.append({
                "id": _identifiant(message),
                "interne": ident,
                "from": message.get("numero") or "",
                "body": message.get("texte") or "",
                "at": _epoque(message.get("horodatage")),
            })
        return recus

    def oublier(self, interne):
        """Efface un message du modem. Sa memoire est petite et se remplit."""
        index = self._index()
        if index is None:
            return False
        return self.messaging.supprimer(index, interne)


def _identifiant(message):
    """Identifiant stable d'un message entrant, tire de son CONTENU.

    Surtout pas l'index de ModemManager : il se reutilise apres effacement, et
    le serveur refuse un identifiant deja vu. Un message vraiment nouveau
    arrivant sur un index libere serait donc jete en silence, alors qu'il porte
    peut-etre un desabonnement.
    """
    graine = "|".join((
        message.get("numero") or "",
        str(message.get("horodatage") or ""),
        message.get("texte") or "",
    ))
    return "modem-" + hashlib.sha256(graine.encode("utf-8")).hexdigest()[:24]


def _epoque(horodatage):
    """Convertit l'horodatage de ModemManager en secondes, ou rend None.

    Rendre None est SUFFISANT : le serveur retient alors l'heure de reception,
    ce qui pour un message qu'on vient de lire ne s'ecarte que de secondes.
    """
    if not horodatage:
        return None
    texte = str(horodatage).strip().strip('"')
    for gabarit in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return int(time.mktime(time.strptime(texte, gabarit)))
        except ValueError:
            continue
    return None


def etat_modem(modem, en_attente):
    """Ce que le serveur juge, et rien de plus.

    On declare le materiel, et le serveur n'applique alors que les criteres qui
    concernent un modem. D'ou l'absence de batterie, de dispense d'economie
    d'energie et de permission d'alarme exacte : les annoncer aurait demande
    d'inventer des valeurs pour des choses qui n'existent pas ici, et une
    valeur inventee finit toujours par etre lue comme une mesure.

    Restent les deux criteres communs a tout materiel :

    - `sms_permission` : cet appareil peut-il, en ce moment, remettre un SMS au
      reseau. Pour un modem, ModemManager present et un modem visible.
    - `sim_ready` : la SIM est enregistree au reseau. Meme sens des deux cotes.
    """
    pret, _motif = modem.pret()
    return {
        "kind": MATERIEL,
        "sms_permission": pret,
        "sim_ready": pret,
        "outbox_pending": en_attente,
        "app_version": VERSION,
    }


class Passerelle:
    """Un tour = une interrogation, des envois, un rapport, les entrants.

    L'ordre n'est pas indifferent : on interroge d'abord, ce qui vaut signal de
    vie meme quand tout le reste echoue ensuite. Une passerelle qui n'interroge
    plus est declaree muette au bout de trois intervalles ; garder
    l'interrogation en tete de cycle est ce qui evite qu'un modem fache fasse
    passer l'agent pour mort.
    """

    def __init__(self, transport, modem, etat, appels=None,
                 horloge=None, dormir=None):
        self.transport = transport
        self.modem = modem
        self.etat = etat
        self.appels = appels or SansAppels()
        self.horloge = horloge or time.time
        self.dormir = dormir or time.sleep
        self.intervalle = INTERVALLE_DEFAUT
        self.segments_par_minute = SEGMENTS_PAR_MINUTE_DEFAUT
        self._fenetre = []
        self._dernier_envoi = 0.0
        self._echecs = 0

    # ------------------------------------------------------------------
    def cycle(self):
        """Un tour complet. Rend un compte rendu, ne leve que sur transport."""
        maintenant = self.horloge()
        en_attente = sum(
            1 for t in self.etat.travaux.values() if t.get("etat") == "attente"
        )
        reponse = self.transport.poster(ROUTE_POLL, {
            "status": etat_modem(self.modem, en_attente),
        })
        self.intervalle = int(reponse.get("poll_interval") or self.intervalle)
        self.segments_par_minute = int(
            reponse.get("segments_per_minute") or self.segments_par_minute
        )

        recus, rejoues = self._ingerer(reponse.get("groups") or [], maintenant)
        evenements = list(rejoues)
        evenements.extend(self._solder_les_interrompus())
        evenements.extend(self._envoyer())
        appels = self._repondre_aux_appels(reponse.get("calls") or [])

        if evenements or appels:
            self.transport.poster(ROUTE_RAPPORT, {
                "events": evenements, "calls": appels,
            })
        entrants = self._remonter_les_entrants()

        self.etat.oublier_les_vieux(self.horloge())
        self.etat.enregistrer()
        return {
            "recus": recus, "rejoues": len(rejoues),
            "rapportes": len(evenements), "appels": len(appels),
            "entrants": entrants,
        }

    # ------------------------------------------------------------------
    def _ingerer(self, groupes, maintenant):
        """Range les travaux offerts, et prepare le re-rapport de ceux qu'on connait.

        Un travail deja termine que le serveur repropose n'a pas ete confirme :
        son rapport s'est perdu. Le renvoyer est la seule facon de fermer la
        boucle — l'ignorer laisserait un envoi reussi mourir a son echeance.
        """
        recus, rejoues = 0, []
        for groupe in groupes:
            texte = groupe.get("body") or ""
            for cible in groupe.get("to") or []:
                uuid = cible.get("u")
                numero = (cible.get("n") or "").strip()
                if not uuid or not numero:
                    continue
                connu = self.etat.travaux.get(uuid)
                if connu is None:
                    self.etat.travaux[uuid] = {
                        "numero": numero, "texte": texte,
                        "etat": "attente", "recu_a": maintenant,
                    }
                    recus += 1
                elif connu.get("etat") != "attente":
                    rejoues.append(self._evenement(uuid, connu))
        return recus, rejoues

    def _evenement(self, uuid, travail):
        """Rapport d'un travail, avec un numero de sequence tout neuf."""
        evenement = {
            "uuid": uuid,
            "seq": self.etat.suivant(),
            "state": ETATS_RAPPORTES.get(travail.get("etat"), "failed"),
            "at": int(travail.get("fini_a") or self.horloge()),
        }
        if travail.get("code"):
            evenement["code"] = travail["code"]
        if travail.get("raison"):
            evenement["reason"] = travail["raison"]
        return evenement

    def _solder_les_interrompus(self):
        """Solde les travaux qu'une execution a laisses en cours de remise.

        Marque « en cours », un travail a ete confie au modem par un processus
        qui ne s'est pas termine : rien ne dit s'il est parti. Le renvoyer
        risquerait un doublon a chaque redemarrage, et une boucle de plantage
        en produirait autant qu'elle compte de tours. Le declarer echoue serait
        un mensonge, et l'echec est terminal cote serveur.

        On le rapporte donc « submitted », qui dit exactement ce qu'on sait :
        remis au reseau, issue inconnue. Le serveur le declarera expire a son
        echeance si personne ne confirme, ce qui est la bonne conclusion.
        """
        evenements = []
        for uuid, travail in self.etat.travaux.items():
            if travail.get("etat") != "en_cours":
                continue
            travail["etat"] = "incertain"
            travail["fini_a"] = self.horloge()
            travail["raison"] = (
                "Remis au modem par une execution interrompue : issue inconnue."
            )
            evenements.append(self._evenement(uuid, travail))
        if evenements:
            self.etat.enregistrer()
        return evenements

    # ------------------------------------------------------------------
    def _budget(self):
        """Segments encore permis dans la minute qui glisse."""
        limite = self.horloge() - 60
        self._fenetre = [(t, n) for t, n in self._fenetre if t > limite]
        utilises = sum(n for _t, n in self._fenetre)
        return max(self.segments_par_minute - utilises, 0)

    def _envoyer(self):
        """Remet au modem ce qui tient dans le budget. Rend les rapports."""
        evenements = []
        pret, _motif = self.modem.pret()
        for uuid, travail in sorted(
            self.etat.travaux.items(), key=lambda p: p[1].get("recu_a") or 0
        ):
            if travail.get("etat") != "attente":
                continue
            if not pret:
                # On NE marque PAS l'echec : le modem peut revenir avant
                # l'echeance, et un echec est terminal cote serveur.
                break
            taille = max(segments(travail.get("texte")), 1)
            if taille > self._budget():
                break
            depuis = self.horloge() - self._dernier_envoi
            if depuis < ESPACEMENT_ENVOIS:
                self.dormir(ESPACEMENT_ENVOIS - depuis)

            # Marque AVANT la remise, et sur le disque : une panne entre les
            # deux laisse une trace, la ou l'ordre inverse ferait renvoyer le
            # message au demarrage suivant sans savoir qu'il est deja parti.
            travail["etat"] = "en_cours"
            self.etat.enregistrer()
            ok, code, detail = self.modem.envoyer(
                travail.get("numero"), travail.get("texte")
            )
            self._dernier_envoi = self.horloge()
            self._fenetre.append((self._dernier_envoi, taille))
            travail["etat"] = "envoye" if ok else "echec"
            travail["fini_a"] = self._dernier_envoi
            travail["code"] = code
            travail["raison"] = detail
            self.etat.enregistrer()
            evenements.append(self._evenement(uuid, travail))
        return evenements

    # ------------------------------------------------------------------
    def _repondre_aux_appels(self, appels):
        """Chaque appel reclame reçoit une reponse. Aucun ne reste en suspens."""
        evenements = []
        for appel in appels:
            uuid = appel.get("uuid")
            numero = (appel.get("number") or "").strip()
            if not uuid:
                continue
            ok, motif = self.appels.placer(numero)
            evenement = {
                "uuid": uuid,
                "seq": self.etat.suivant(),
                # `erplibre.mobile.call._apply_event` ne prend pas de code :
                # seul le motif porte l'explication.
                "state": "connected" if ok else "failed",
                "at": int(self.horloge()),
            }
            if motif:
                evenement["reason"] = motif
            evenements.append(evenement)
        return evenements

    # ------------------------------------------------------------------
    def _remonter_les_entrants(self):
        """Remonte les SMS reçus, puis les efface DU MODEM une fois enregistres.

        L'effacement n'a lieu qu'apres la reponse du serveur : la memoire du
        modem est petite et se remplit, mais un message efface avant d'etre
        enregistre est perdu, et c'est la piece justificative d'un
        desabonnement.
        """
        messages = [m for m in self.modem.entrants()
                    if m["id"] not in self.etat.entrants_vus]
        if not messages:
            return 0
        self.transport.poster(ROUTE_ENTRANTS, {
            "messages": [
                {k: m[k] for k in ("id", "from", "body", "at") if m[k] is not None}
                for m in messages
            ],
        })
        for message in messages:
            self.etat.entrants_vus.append(message["id"])
            self.modem.oublier(message["interne"])
        self.etat.enregistrer()
        return len(messages)

    # ------------------------------------------------------------------
    def boucle(self, arret=None, tours=None, journal=print):
        """Tourne jusqu'a l'arret. `tours` borne l'execution, pour les tests."""
        fait = 0
        while not (arret and arret()):
            try:
                compte = self.cycle()
                self._echecs = 0
                if any(compte.values()):
                    journal("passerelle : %s" % compte)
                attente = self.intervalle
            except ErreurTransport as exc:
                rang = min(self._echecs, len(REPOS_APRES_ECHEC) - 1)
                attente = REPOS_APRES_ECHEC[rang]
                self._echecs += 1
                journal("passerelle : %s — nouvel essai dans %s s" % (exc, attente))
            fait += 1
            if tours is not None and fait >= tours:
                return fait
            self.dormir(attente)
        return fait


def chemin_etat():
    """Fichier d'etat, sous le repertoire d'etat de l'utilisateur."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "erplibre", "passerelle_modem.json")


def depuis_environnement(ouvrir=None):
    """Construit la passerelle a partir de l'environnement. Leve si incomplet."""
    manquants = [
        nom for nom in (VARIABLE_URL, VARIABLE_APPAREIL, VARIABLE_SECRET)
        if not os.environ.get(nom)
    ]
    if manquants:
        raise ErreurTransport(
            "Variables absentes de l'environnement : " + ", ".join(manquants)
        )
    transport = Transport(
        os.environ[VARIABLE_URL], os.environ[VARIABLE_SECRET],
        os.environ[VARIABLE_APPAREIL], ouvrir=ouvrir,
    )
    return Passerelle(transport, ModemManagerSMS(), Etat(chemin_etat()))


def main():
    """Point d'entree de l'agent, pour un service ou un lancement a la main.

    Rend 1 sur une configuration incomplete plutot que de tourner en boucle
    sur des interrogations vouees a echouer : un service qui redemarre sans
    fin masque la variable manquante au lieu de la signaler.
    """
    import logging
    import sys

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        agent = depuis_environnement()
    except ErreurTransport as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        agent.boucle(journal=lambda message: print(message, flush=True))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
