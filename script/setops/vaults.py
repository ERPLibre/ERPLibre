#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les voûtes du moteur : ce qu'une machine peut ouvrir, et ce qu'elle ne doit pas.

UNE CLÉ ABSENTE N'EST PAS UNE FAUTE, et c'est le moteur qui l'écrit en
capitales. Sur le runner d'un locataire, la clé du SITE doit manquer : ce
runner porte la carte de la fabric et ne doit jamais pouvoir l'ouvrir. Une
absence y est donc une séparation RÉUSSIE, et un écran qui la présenterait
comme une panne enverrait réparer ce qui fonctionne. Seule l'absence de la clé
de l'INSTANCE MONTÉE empêche la machine de travailler ; elle seule décide du
code de sortie.

LA CLÉ NE S'AFFICHE JAMAIS ET NE SE JOURNALISE JAMAIS. `poser_cle` écrit les
octets et rend un verdict qui ne les porte pas : aucune fonction d'ici ne rend,
n'imprime ni ne journalise le contenu d'un fichier-clé.

Une seule chose s'écrit ici — ce fichier-clé. Tout le reste est de la lecture :
le texte arrive de l'exécuteur.
"""

from __future__ import annotations

import base64
import errno
import os
from typing import NamedTuple

# Ce que todo demande au moteur. `etat` rend 1 quand la clé de l'instance
# montée manque, 0 sinon — une absence ailleurs ne change pas le code.
ARGV_ETAT = ("python3", "-B", "scripts/voutes.py", "etat")

# La cible du moteur qui montre ce qui n'existe QUE sur ce poste. Lecture.
CIBLE_RECENSER = "cles-recenser"

# CE QUE TODO NE LANCE PAS, et la variable que chacune exige. Ces cibles
# passent par `gpg`, qui demande une phrase de passe : elle doit aller de la
# main au terminal sans traverser un outil qui pourrait la retenir. Le moteur
# réserve donc ces gestes à un terminal tenu par un humain, et todo les REMET
# plutôt que de les conduire — le même parti que les cibles dont il garde la
# confirmation. La variable accompagne la cible parce qu'une ligne remise sans
# elle se fait refuser par le moteur, et la remise n'aurait rien donné.
CIBLES_GPG = {
    "cles-exporter": "VERS",
    "cles-compagnons": "VERS",
    "cles-restaurer": "ARCHIVE",
}

# Les rôles que le rapport nomme, et le vocabulaire est CLOS. `bloquante` se
# décide sur `instance` : si ce mot changeait en amont, un rôle inconnu doit
# faire refuser la lecture et non rendre un calme trompeur sur une machine qui
# ne peut rien configurer.
INSTANCE = "instance"
HEBERGEUR = "hebergeur"
VOISIN = "voisin"
ROLES = (INSTANCE, HEBERGEUR, VOISIN)

# Les trois états, tels que le moteur les étiquette.
PRESENTE = "presente"
ABSENTE_BLOQUANTE = "absente-bloquante"
SANS_CLE = "sans-cle"
ETATS = (PRESENTE, ABSENTE_BLOQUANTE, SANS_CLE)

# La correspondance entre ce que le moteur ÉCRIT et ce que todo en retient.
# Le moteur cadre ses colonnes : l'étiquette se retrouve sans ses blancs.
ETIQUETTES = {
    "cle presente": PRESENTE,
    "CLE ABSENTE": ABSENTE_BLOQUANTE,
    "sans cle": SANS_CLE,
}

# Ce que le moteur imprime quand il n'y a rien à nommer : ni instance montée,
# ni underlay. C'est une réponse VALIDE, à distinguer d'un rapport illisible.
AUCUNE = "Aucune voute a nommer"

# Les verdicts de la pose, et ils sont CLOS. `DEJA_LA` est le plus important :
# voir `poser_cle`.
POSEE = "posee"
DEJA_LA = "deja-la"
SANS_CHEMIN = "sans-chemin"
ECHEC = "echec"
POSES = (POSEE, DEJA_LA, SANS_CHEMIN, ECHEC)

# La forme que le moteur documente : 48 octets tirés au sort, en base64 sur une
# seule ligne. 48 octets donnent 64 caractères sans remplissage.
OCTETS = 48

# Le fichier naît en 0600 et ne l'est pas devenu : entre une création large et
# un resserrement, la clé est lisible par tout le monde.
MODE = 0o600


class Voute(NamedTuple):
    """Une voûte, telle que le rapport du moteur la décrit."""

    role: str
    nom: str
    etat: str
    chemin: str


class Pose(NamedTuple):
    """Ce qu'a donné la pose d'un fichier-clé. NE PORTE JAMAIS LA CLÉ."""

    resultat: str
    souci: str = ""

    @property
    def reussi(self) -> bool:
        return self.resultat == POSEE


def _ligne(ligne):
    """La `Voute` que porte une ligne du rapport, ou None.

    Le chemin est pris APRÈS l'étiquette et non comme dernier mot : un dossier
    de configuration dont le nom contient une espace ne rendrait qu'une queue
    de chemin, et todo proposerait de créer la clé ailleurs. Le nom du dépôt se
    lit de la même façon, entre le rôle et l'étiquette.
    """
    if not ligne or ligne[:1].isspace():
        return None
    role, _, reste = ligne.partition(" ")
    if role not in ROLES:
        return None
    for brute, etat in ETIQUETTES.items():
        avant, marque, apres = reste.partition(brute)
        if not marque:
            continue
        return Voute(
            role=role, nom=avant.strip(), etat=etat, chemin=apres.strip()
        )
    return None


def lit_etat(sortie):
    """Les voûtes que le rapport nomme, `()` s'il n'y en a aucune, None sinon.

    `()` et None sont deux nouvelles : la première dit « ni instance montée ni
    underlay », la seconde « le rapport n'a pas la forme attendue ».

    Fermé par défaut : un rôle hors des trois connus, ou une ligne sans
    étiquette connue, fait refuser TOUT le rapport. Sauter la ligne qu'on ne
    comprend pas ferait taire l'absence que cet écran existe pour montrer.
    """
    lignes = (sortie or "").splitlines()
    if any(ligne.lstrip().startswith(AUCUNE) for ligne in lignes):
        return ()
    trouvees, tableau = [], False
    for ligne in lignes:
        if not ligne.strip():
            continue
        lue = _ligne(ligne)
        if lue is not None:
            trouvees.append(lue)
            tableau = True
        elif tableau:
            # Sous le tableau, le moteur explique le blocage en prose et cite
            # la commande qui le règle : ces lignes ne sont pas des voûtes.
            break
        elif ligne[:1].isspace():
            continue
        else:
            return None
    return tuple(trouvees) or None


def bloquante(voutes):
    """La voûte dont l'absence empêche la machine de travailler, ou None.

    Celle de l'instance montée, et elle seule : c'est elle qui décide du code
    de sortie du moteur.
    """
    for voute in voutes or ():
        if voute.role == INSTANCE and voute.etat == ABSENTE_BLOQUANTE:
            return voute
    return None


def separation(voutes):
    """Les voûtes que cette machine n'ouvre pas, et ne doit pas ouvrir.

    Les nommer à part évite qu'un écran les compte comme des manques à régler,
    et POSER UNE CLÉ NEUVE POUR L'UNE D'ELLES N'EN OUVRIRAIT AUCUNE : le
    secret de la voûte existe déjà ailleurs. Rien ici ne les propose.
    """
    return tuple(v for v in voutes or () if v.etat == SANS_CLE)


def poser_cle(chemin) -> Pose:
    """Pose un fichier-clé neuf, et rend un verdict qui ne le contient pas.

    N'ÉCRASE JAMAIS UN FICHIER EXISTANT. Une clé remplacée rend sa voûte
    définitivement illisible : le contenu chiffré ne s'ouvre qu'avec le secret
    qui l'a chiffré. La création est donc exclusive, et l'existence d'un
    fichier rend `DEJA_LA` au lieu de le tronquer — là où la redirection que
    documente le moteur tronque.

    UNE CLÉ NEUVE N'OUVRE QUE CE QUI N'EST PAS ENCORE CHIFFRÉ. Sur une voûte
    qui porte déjà du contenu, elle ne récupère rien : ce secret-là revient de
    son archive. L'appelant tranche AVANT d'appeler ; cette fonction ne sait
    pas distinguer les deux cas.

    Le mode est posé à la création, pas après : entre une création large et un
    resserrement, la clé est lisible par tout le monde.
    """
    chemin = (chemin or "").strip()
    if not chemin:
        return Pose(SANS_CHEMIN)
    try:
        descripteur = os.open(
            chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, MODE
        )
    except FileExistsError:
        return Pose(DEJA_LA)
    except OSError as souci:
        return Pose(
            ECHEC, souci.strerror or errno.errorcode.get(souci.errno, "")
        )
    try:
        # Les octets ne passent par aucun retour, aucun journal, aucun écran.
        os.write(descripteur, base64.b64encode(os.urandom(OCTETS)))
    except OSError as souci:
        os.close(descripteur)
        return Pose(ECHEC, souci.strerror or "")
    os.close(descripteur)
    return Pose(POSEE)
