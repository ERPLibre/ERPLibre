#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le repondeur du modem, vu depuis la TUI.

Le service `erplibre_sip_go` decroche et enregistre ; ce module ne fait que
REGLER et CONSULTER. La separation n'est pas cosmetique : le service tient le
port du modem, et un second programme qui l'ouvrirait entrelacerait ses
commandes AT avec les siennes.

Les fichiers vivent sous `private/`, seul endroit du depot autorise a porter
une donnee de client. Un message laisse sur un repondeur EST une donnee de
client : une voix, un numero, et ce que la personne a dit.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess

#: Ou vivent les reglages et les messages, sous la racine du depot.
CONF_RELATIF = "private/conf/sip_go/repondeur.json"
MESSAGES_RELATIF = "private/repondeur/messages"
ANNONCE_RELATIF = "private/repondeur/annonce.wav"

#: Ce que le service accepte. Reproduit ici pour que la TUI refuse une saisie
#: avant de l'ecrire, plutot que de la voir corrigee en silence au demarrage.
SONNERIES_MIN = 1
SONNERIES_MAX = 5
SONNERIES_DEFAUT = 4

#: La voix du telephone, et rien de plus : le message part sur une ligne a
#: 8 kHz, et enregistrer plus fin ne fait qu'un fichier plus gros.
TAUX = "8000"
CANAUX = "1"
FORMAT = "S16_LE"


def racine() -> str:
    """La racine du depot, deduite de l'emplacement de ce fichier."""
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )


def chemin_conf() -> str:
    return os.path.join(racine(), CONF_RELATIF)


def chemin_messages() -> str:
    return os.path.join(racine(), MESSAGES_RELATIF)


def chemin_annonce() -> str:
    return os.path.join(racine(), ANNONCE_RELATIF)


def reglages_par_defaut() -> dict:
    """Un repondeur ETEINT, avec ses chemins deja pointes.

    Eteint : decrocher a la place de quelqu'un s'entend, et un defaut actif
    ferait repondre une machine sur une ligne dont le proprietaire ignore
    qu'elle en a une.
    """
    return {
        "actif": False,
        "sonneries": SONNERIES_DEFAUT,
        "annonce": "",
        "dossier": chemin_messages(),
        "duree_max_secondes": 120,
    }


def lire() -> dict:
    """Les reglages courants, defauts compris.

    Un fichier absent rend les defauts : c'est l'etat d'une installation qui
    n'a pas encore de repondeur, pas une panne.
    """
    reglages = reglages_par_defaut()
    try:
        with open(chemin_conf(), encoding="utf-8") as flux:
            reglages.update(json.load(flux))
    except FileNotFoundError:
        return reglages
    except (OSError, ValueError):
        # Illisible : on rend les defauts pour que le menu s'affiche, et
        # l'ecriture suivante remplacera le fichier casse.
        return reglages
    return reglages


def ecrire(reglages: dict) -> str:
    """Pose les reglages et rend le chemin ecrit."""
    chemin = chemin_conf()
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as flux:
        json.dump(reglages, flux, indent=1, ensure_ascii=False)
        flux.write("\n")
    return chemin


def regler(**champs) -> dict:
    """Change quelques champs et rend les reglages complets."""
    reglages = lire()
    reglages.update(champs)
    ecrire(reglages)
    return reglages


def borner_sonneries(valeur) -> int:
    """Ramene un nombre de sonneries dans sa plage, ou rend le defaut.

    Le maximum n'est pas arbitraire : la boite vocale de l'operateur prend
    l'appel vers trente secondes, et une sonnerie complete en dure six. Au-dela
    de cinq, le repondeur ne decrocherait jamais.
    """
    try:
        nombre = int(valeur)
    except (TypeError, ValueError):
        return SONNERIES_DEFAUT
    # Sous le minimum, le DEFAUT et non le minimum : c'est ce que fait le
    # service, et une TUI qui ecrirait 1 la ou le service comprend 4 reglerait
    # le repondeur autrement que ce que son propre ecran affiche.
    if nombre < SONNERIES_MIN:
        return SONNERIES_DEFAUT
    return min(SONNERIES_MAX, nombre)


def lister() -> list:
    """Les messages, du plus recent au plus ancien.

    Un WAV sans description est ignore : sans appelant ni date, la ligne
    n'apprend rien et le message ne se rappelle pas.
    """
    dossier = lire().get("dossier") or chemin_messages()
    try:
        entrees = os.listdir(dossier)
    except OSError:
        return []
    messages = []
    for nom in entrees:
        if not nom.endswith(".json"):
            continue
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as flux:
                message = json.load(flux)
        except (OSError, ValueError):
            continue
        if message.get("fichier"):
            messages.append(message)
    messages.sort(key=lambda m: m.get("debut") or "", reverse=True)
    return messages


def effacer(message: dict) -> None:
    """Retire le son ET sa description.

    Les deux ensemble : une description orpheline ferait reapparaitre dans la
    liste un message dont le son n'existe plus.
    """
    son = message.get("fichier") or ""
    for chemin in (son, os.path.splitext(son)[0] + ".json"):
        try:
            os.remove(chemin)
        except OSError:
            pass


def _outil(*noms) -> str:
    for nom in noms:
        if shutil.which(nom):
            return nom
    return ""


def jouer(chemin: str, timeout: int = 300) -> tuple:
    """Joue un fichier sur la sortie audio de la MACHINE.

    Pas sur la carte du modem : celle-ci est la ligne telephonique, et y jouer
    un message le ferait entendre au correspondant plutot qu'a soi. Rend
    (succes, explication).
    """
    if not os.path.exists(chemin):
        return False, "fichier introuvable : " + chemin
    outil = _outil("aplay", "paplay", "pw-play")
    if not outil:
        return False, "aucun lecteur audio (aplay, paplay ou pw-play)"
    try:
        fait = subprocess.run(
            [outil, chemin], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "lecture interrompue apres %s s" % timeout
    if fait.returncode != 0:
        return False, (fait.stderr or "").strip() or outil + " a echoue"
    return True, ""


def enregistrer_annonce(secondes: int = 20, chemin: str = "") -> tuple:
    """Capte l'annonce depuis le MICRO de la machine.

    Le micro et non la ligne : l'annonce se prepare hors appel, et passer par
    la SIM demanderait d'occuper la ligne pour s'enregistrer soi-meme.

    L'ecriture se fait dans un fichier temporaire renomme a la fin : une
    capture interrompue laisserait sinon une annonce tronquee EN PLACE, et le
    repondeur la jouerait au prochain appelant.
    """
    chemin = chemin or chemin_annonce()
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    outil = _outil("arecord")
    if not outil:
        return False, "arecord absent : installez alsa-utils"
    provisoire = chemin + ".partiel"
    try:
        fait = subprocess.run(
            [
                outil,
                "-f",
                FORMAT,
                "-r",
                TAUX,
                "-c",
                CANAUX,
                "-d",
                str(secondes),
                provisoire,
            ],
            capture_output=True,
            text=True,
            timeout=secondes + 15,
        )
    except subprocess.TimeoutExpired:
        _retirer(provisoire)
        return False, "enregistrement interrompu"
    if fait.returncode != 0 or not os.path.exists(provisoire):
        _retirer(provisoire)
        return False, (fait.stderr or "").strip() or "arecord a echoue"
    os.replace(provisoire, chemin)
    return True, chemin


#: Octets lus en queue du fichier pour mesurer le niveau. 0,1 s a 8 kHz sur
#: 16 bits : assez pour qu'une voix fasse bouger la barre, assez peu pour que
#: la lecture ne coute rien.
FENETRE_NIVEAU = 1600


def captures_vivantes(provisoire: str, lister=None) -> list:
    """Les captures d'annonce encore en vie, par identifiant de processus.

    Une capture sans duree ne s'arrete QUE sur demande. Une TUI fermee
    brutalement, un terminal coupe, et elle tient le microphone du poste
    indefiniment. Ce qu'elle encombre n'est pas le disque — le fichier
    provisoire peut meme avoir ete efface sous elle — mais la CAPTURE des
    autres programmes : plusieurs clients sur le micro numerique font hacher
    ce que chacun recoit.
    """
    lister = lister or _processus_arecord
    return [pid for pid, commande in lister() if provisoire in commande]


def _processus_arecord():
    """(pid, ligne de commande) de chaque arecord du systeme."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % pid, encoding="utf-8") as flux:
                if flux.read().strip() != "arecord":
                    continue
            with open("/proc/%s/cmdline" % pid, "rb") as flux:
                commande = flux.read().decode("utf-8", "replace")
        except OSError:
            continue
        yield int(pid), commande


def _retirer_les_survivants(provisoire: str, lister=None, tuer=None) -> int:
    """Termine les captures d'annonce oubliees. Rend combien.

    Avant d'en lancer une neuve, et pas apres : toutes ecrivent dans le MEME
    fichier provisoire, et deux captures simultanees s'y melangent.
    """
    tuer = tuer or (lambda pid: os.kill(pid, signal.SIGTERM))
    retires = 0
    for pid in captures_vivantes(provisoire, lister):
        try:
            tuer(pid)
            retires += 1
        except OSError:
            pass
    return retires


def demarrer_enregistrement(chemin: str = "") -> tuple:
    """Lance une capture SANS duree et rend (processus, chemin_provisoire).

    La duree d'une annonce ne se connait pas d'avance : la demander avant de
    parler oblige a deviner, et un compte a rebours muet ne dit meme pas si la
    capture a commence. On enregistre donc jusqu'a l'arret demande.

    L'ecriture va dans un fichier provisoire : une capture abandonnee laisserait
    sinon une annonce tronquee EN PLACE, que le repondeur jouerait au prochain
    appelant.
    """
    chemin = chemin or chemin_annonce()
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    outil = _outil("arecord")
    if not outil:
        return None, "arecord absent : installez alsa-utils"
    provisoire = chemin + ".partiel"
    oubliees = _retirer_les_survivants(provisoire)
    if oubliees:
        print("  %d capture(s) oubliee(s) arretee(s)" % oubliees)
    _retirer(provisoire)
    try:
        proc = subprocess.Popen(
            [outil, "-f", FORMAT, "-r", TAUX, "-c", CANAUX, provisoire],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return None, str(exc)
    return proc, provisoire


def abandonner_enregistrement(proc, provisoire: str = "") -> None:
    """Termine la capture et jette ce qu'elle avait pris.

    Ce que fait QUITTER, par opposition a conclure : une annonce qu'on n'a pas
    validee ne doit pas se retrouver en place parce qu'une fenetre s'est
    fermee — le repondeur la jouerait au prochain appelant. Ne leve jamais :
    on l'appelle sur un chemin de sortie, ou il n'y a plus personne a qui
    rapporter une erreur.
    """
    try:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)
    except Exception:  # noqa: BLE001 - voir la docstring
        pass
    if provisoire:
        _retirer(provisoire)


def arreter_enregistrement(proc, provisoire: str, chemin: str = "") -> tuple:
    """Arrete la capture et met l'annonce en place. Rend (succes, detail).

    Par SIGINT et non SIGKILL : `arecord` ferme alors son fichier en corrigeant
    la taille declaree dans l'entete. Tue net, il laisse un WAV dont l'entete
    annonce zero octet, que la plupart des lecteurs refusent — dont celui qui
    joue l'annonce a l'appelant.
    """
    chemin = chemin or chemin_annonce()
    if proc is None:
        return False, "aucun enregistrement en cours"
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        _retirer(provisoire)
        return False, "arecord n'a pas rendu la main"
    except OSError as exc:
        _retirer(provisoire)
        return False, str(exc)
    if not os.path.exists(provisoire) or os.path.getsize(provisoire) <= 44:
        # 44 octets : l'entete WAV seule, donc pas un echantillon de son.
        _retirer(provisoire)
        return False, "rien n'a ete capte"
    os.replace(provisoire, chemin)
    return True, chemin


def niveau_capte(provisoire: str) -> float:
    """Crete du son capte le plus recemment, entre 0 et 1.

    Lit la QUEUE du fichier pendant qu'il grossit : `arecord` n'annonce aucun
    niveau, et sans retour visible on ne sait pas si le micro entend quelque
    chose. Rend 0 quand il n'y a pas encore d'echantillon.
    """
    try:
        taille = os.path.getsize(provisoire)
        if taille <= 44:
            return 0.0
        with open(provisoire, "rb") as flux:
            flux.seek(max(44, taille - FENETRE_NIVEAU))
            brut = flux.read()
    except OSError:
        return 0.0
    if len(brut) < 2:
        return 0.0
    crete = 0
    for index in range(0, len(brut) - 1, 2):
        valeur = int.from_bytes(brut[index:index + 2], "little", signed=True)
        crete = max(crete, abs(valeur))
    return min(1.0, crete / 32768.0)


def duree_captee(provisoire: str) -> float:
    """Secondes deja captees, deduites de la taille du fichier."""
    try:
        octets = max(0, os.path.getsize(provisoire) - 44)
    except OSError:
        return 0.0
    return octets / (int(TAUX) * int(CANAUX) * 2)


def _retirer(chemin: str) -> None:
    try:
        os.remove(chemin)
    except OSError:
        pass
