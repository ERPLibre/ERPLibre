#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La console web du moteur : une porte sans serrure, donc une porte sur la boucle.

LA CONSOLE N'A AUCUNE AUTHENTIFICATION. Ce qui atteint son port lit tout
l'inventaire — adresses, VLAN, noms d'hôtes — et déclenche ses gestes :
vérifier, déployer, pousser un flux. Il n'y a ni mot de passe, ni jeton
d'accès ; le jeton qu'elle porte garde ses exécutions les unes des autres, pas
sa porte.

D'OÙ LA BOUCLE LOCALE, ET RIEN D'AUTRE. Le script accepte `--hote`, et todo ne
le passe JAMAIS : le lier à `0.0.0.0` publierait sur le réseau une console sans
serrure qui peut déployer sur la flotte. Le moteur la lie à 127.0.0.1 par
défaut, et c'est ce défaut que todo laisse faire. Pour l'atteindre d'ailleurs,
on redirige un port par SSH : l'authentification revient à SSH, elle ne
disparaît pas.

UN DÉTACHÉ ÉCHOUE EN SILENCE. Le PID rendu par le lancement ne prouve pas que
le serveur écoute : le port se sonde après coup, sinon todo annoncerait une
console qui n'a jamais démarré.

UN PID SE RECYCLE. Rien n'est tué sans avoir relu la ligne de commande de ce
PID et y avoir retrouvé la marque : au moment du signal, un numéro enregistré
désigne parfois un autre travail que celui qu'on a lancé.

Rien ici ne lance ni n'arrête quoi que ce soit : les faits arrivent mesurés.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
from typing import NamedTuple

# La cible du moteur, et la marque qui doit se relire dans la ligne de
# commande du chef de groupe. C'est la MÊME chaîne : ce qui est lancé est ce
# qu'on retrouve, sans second nom à tenir à jour.
CIBLE = "inventaire-ui"
MARQUE = CIBLE

# Le nom de l'entrée de menu, déclaré là où vit la console : l'entrée et
# l'en-tête de l'écran sont la même phrase. Elle dit l'essentiel avant même
# qu'on entre — ce qui n'a pas de serrure ne se découvre pas à l'usage.
GESTE = "Set-OPS - Web console (loopback only, no authentication)"

# Ce que le moteur lie par défaut, et ce que todo laisse faire. Déclaré ici
# pour être VÉRIFIÉ et affiché, jamais pour être passé en argument.
ADRESSE = "127.0.0.1"
PORT = 8765

# Le suivi et le journal d'une console lancée d'ici. Ils vivent dans le
# dossier d'exécution de l'utilisateur quand il existe — il n'appartient qu'à
# lui — et dans le dossier temporaire sinon.
SUIVI = "setops-console.json"
JOURNAL = "setops-console.log"

# Les états, et le vocabulaire est CLOS. `TENU` n'est pas `VIVANTE` : le port
# répond, mais rien ne prouve que ce soit la console de todo — et ce qui
# occupe le port sans être à nous ne s'arrête pas d'ici.
ARRETEE = "arretee"
VIVANTE = "vivante"
TENU = "tenu"
INCONNU = "inconnu"
ETATS = (ARRETEE, VIVANTE, TENU, INCONNU)

# Ce qu'un arrêt a donné. Vocabulaire CLOS lui aussi.
ARRET_FAIT = "arret-fait"
ARRET_TENACE = "arret-tenace"
ARRET_REFUSE = "arret-refuse"
ARRET_IMPOSSIBLE = "arret-impossible"
ARRETS = (ARRET_FAIT, ARRET_TENACE, ARRET_REFUSE, ARRET_IMPOSSIBLE)


class Suivi(NamedTuple):
    """Ce que todo a noté du dernier lancement."""

    pid: int
    port: int


def dossier(env=None):
    """Où poser le suivi et le journal.

    `XDG_RUNTIME_DIR` d'abord : il n'appartient qu'à l'utilisateur, quand le
    dossier temporaire est partagé. Un suivi qu'un autre compte peut écrire
    désignerait le PID de son choix — la relecture de la ligne de commande
    reste le garde, mais autant ne pas offrir la prise.
    """
    vu = os.environ if env is None else env
    execution = vu.get("XDG_RUNTIME_DIR")
    if execution and os.path.isdir(execution):
        return execution
    return tempfile.gettempdir()


def chemin_suivi(env=None):
    return os.path.join(dossier(env), SUIVI)


def chemin_journal(env=None):
    return os.path.join(dossier(env), JOURNAL)


def lit_suivi(texte):
    """Le `Suivi` que porte `texte`, ou None.

    Fermé par défaut : un PID qui n'est pas un entier positif rend None. Un
    zéro, un négatif ou une chaîne désigneraient un groupe de processus au
    lieu d'un seul — `kill(0)` porte sur TOUT le groupe de l'appelant, et
    `kill(-1)` sur tout ce que l'utilisateur possède.
    """
    try:
        lu = json.loads(texte or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(lu, dict):
        return None
    pid, port = lu.get("pid"), lu.get("port")
    for valeur in (pid, port):
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            return None
    if pid < 1 or not 0 < port < 65536:
        return None
    return Suivi(pid=pid, port=port)


def ecrit_suivi(chemin, pid, port) -> bool:
    """Note le lancement. Rend False sans lever si rien ne s'écrit.

    Un suivi perdu ne casse rien de grave : l'écran retombe sur « le port est
    tenu », et l'arrêt se fait à la main. Faire échouer le lancement pour
    autant serait pire.
    """
    try:
        with open(chemin, "w", encoding="utf-8") as tenu:
            json.dump({"pid": int(pid), "port": int(port)}, tenu)
    except (OSError, ValueError, TypeError):
        return False
    return True


def oublie(chemin) -> None:
    """Retire le suivi. L'absence de fichier est le résultat attendu."""
    try:
        os.unlink(chemin)
    except OSError:
        pass


# Ce que rend la relecture quand le processus N'EXISTE PLUS. C'est un FAIT, et
# il se distingue de « on ne sait pas » : confondus, un lancement raté laisse
# un PID mort dans le suivi, l'écran reste indécidable, et la console ne peut
# plus jamais être lancée d'ici. Un objet plutôt qu'une chaîne : aucune vraie
# ligne de commande ne peut lui être égale.
ABSENT = object()


def ligne_de_commande(pid, procfs="/proc"):
    """La ligne de commande de `pid`, `ABSENT`, ou None.

    Trois réponses, parce qu'il y a trois cas. La ligne dit ce que le PID
    exécute ; `ABSENT` dit que ce PID n'existe plus, ce que le système AFFIRME
    quand son dossier a disparu d'un procfs par ailleurs monté ; None dit
    qu'on ne sait pas — et sur un doute, rien n'est tué ni déclaré arrêté.
    """
    try:
        dossier_pid = f"{procfs}/{int(pid)}"
    except (ValueError, TypeError):
        return None
    try:
        with open(f"{dossier_pid}/cmdline", "rb") as tenu:
            return tenu.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except FileNotFoundError:
        # Le procfs est là mais le dossier du PID n'y est plus : le processus
        # est bel et bien parti. Sans procfs — un autre système — on ne sait
        # rien, et on le dit.
        if os.path.isdir(procfs) and not os.path.exists(dossier_pid):
            return ABSENT
        return None
    except OSError:
        return None


def tenue(ligne, marque=MARQUE):
    """Cette ligne de commande est-elle celle de NOTRE console ?

    Rend None quand la ligne ne se lit pas — l'appelant refuse alors d'agir.
    C'est LE garde contre le PID recyclé : au moment du signal, un numéro
    enregistré désigne parfois un autre travail, et le signal irait au GROUPE
    entier de ce travail.
    """
    if ligne is None:
        return None
    if ligne is ABSENT:
        return False
    return marque in ligne


def port_occupe(adresse=ADRESSE, port=PORT, delai=0.4):
    """Quelque chose écoute-t-il là ? None si la sonde elle-même échoue.

    Sondé par une connexion et non par une liaison d'essai : lier pour voir
    prendrait le port, et le rendrait au moment précis où la console cherche
    à le prendre.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
            prise.settimeout(delai)
            return prise.connect_ex((adresse, port)) == 0
    except OSError:
        return None


def situation(suivi, portee, occupe):
    """(état, pid) de la console, depuis trois faits mesurés ailleurs.

    Nommée `situation` et non `etat` : `coexistence.etat` porte déjà ce nom
    dans le paquet, et une prose qui nomme « etat(…) » ne désignerait plus une
    seule fonction.

    `portee` est ce que rend `tenue()` : True, False, ou None quand la ligne
    de commande ne se lit pas. `occupe` est ce que rend `port_occupe()`.

    Un fait manquant rend `INCONNU` plutôt qu'une supposition : sur un doute,
    l'écran n'offre ni de lancer — deux consoles se disputeraient le port —
    ni d'arrêter.
    """
    if portee is None or occupe is None:
        return INCONNU, suivi.pid if suivi else 0
    if suivi is not None and portee:
        return VIVANTE, suivi.pid
    if occupe:
        # Le port répond sans que notre PID le tienne : un autre programme, ou
        # une console lancée hors de todo. Elle ne s'arrête pas d'ici.
        return TENU, 0
    return ARRETEE, 0


def url(adresse=ADRESSE, port=PORT) -> str:
    return f"http://{adresse}:{port}/"


def redirection(hote, utilisateur="", port=PORT) -> str:
    """La ligne qui amène la console sur le poste de l'opérateur, ou « ».

    C'EST L'ALTERNATIVE À LIER LARGE, et elle ne perd rien : le port reste sur
    la boucle locale des deux côtés, et c'est SSH qui authentifie. `-N`
    n'ouvre aucun interpréteur : ce tunnel ne sert qu'à porter le port.
    """
    hote = (hote or "").strip()
    if not hote:
        return ""
    cible = (
        f"{utilisateur.strip()}@{hote}"
        if (utilisateur or "").strip()
        else hote
    )
    return f"ssh -N -L {port}:{ADRESSE}:{port} {cible}"


def arreter(suivi, portee, signal_au_groupe):
    """Arrête la console suivie, et rend un mot du vocabulaire clos.

    RIEN N'EST TUÉ SANS PREUVE. `portee` doit valoir True — la ligne de
    commande de ce PID porte encore la marque. False refuse (le PID a été
    recyclé), None refuse aussi (on ne sait pas), et dans les deux cas le
    signal n'est pas envoyé.

    `signal_au_groupe(pid)` porte sur le GROUPE : le lancement a fait du
    processus un chef de session, et la recette `make` comme le serveur qu'elle
    lance y sont. Signaler le seul `make` laisserait le serveur tenir le port.
    """
    if suivi is None or portee is not True:
        return ARRET_REFUSE
    try:
        signal_au_groupe(suivi.pid)
    except (OSError, ValueError, TypeError):
        return ARRET_IMPOSSIBLE
    return ARRET_FAIT


def attendre(sonde, attendu, essais=25, pause=None):
    """Sonde jusqu'à ce qu'elle rende `attendu`, ou rend le dernier vu.

    Le port ne s'ouvre ni ne se libère à l'instant du geste : sans cette
    attente, l'écran conclurait sur l'état d'avant. `pause` est injectable
    pour que les épreuves ne dorment pas.
    """
    dernier = None
    for rang in range(max(1, int(essais))):
        dernier = sonde()
        if dernier == attendu:
            return dernier
        if pause is not None and rang + 1 < essais:
            pause()
    return dernier
