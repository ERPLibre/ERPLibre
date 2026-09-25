#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'environnement Ansible du CONTRÔLEUR : ce qu'il exige, comment le poser.

Le moteur n'en pose pas. Son rôle `serveur_ops` équipe une CIBLE — un runner
qu'on déploie — et non le poste qui la pilote. Ce module pose donc le venv du
contrôleur, en LISANT dans le moteur tout ce qui s'y lit : la plage
d'ansible-core, les bibliothèques Python, les collections. Aucune de ces
valeurs n'est recopiée ici.

LE MINEUR DE PYTHON EST UNE CONTRAINTE, PAS UN GOÛT. Le rôle `serveur_ops`
exige que contrôleur et cible partagent leur `major.minor`, et il fabrique le
cache de roues hors ligne avec le `python3` du PATH — pas avec l'interpréteur
d'Ansible. Un contrôleur en 3.14 produit donc des roues `cp314` qu'une cible
en 3.13 refuse à l'installation, et la garde du rôle arrête le geste avant
d'en arriver là. D'où deux exigences que ce module tient ensemble : le venv
est posé dans `MINEUR_CIBLE`, et `environnement()` met son `bin` en TÊTE du
PATH.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from typing import NamedTuple

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

# Le venv Ansible dédié, sous la racine d'ERPLibre. Son nom commence par
# « .venv », motif déjà ignoré par git.
VENV = ".venv.todo.setops"

# Le major.minor que la cible porte. Debian 13 livre `python3` en 3.13, et
# `serveur_ops` refuse un contrôleur dont le mineur diffère de celui de la
# cible. RIEN DANS LE MOTEUR NE LE DÉCLARE : il tient au système du gabarit,
# d'où une constante plutôt qu'une lecture. Une flotte sur un autre gabarit
# change cette ligne, et l'écran affiche toujours ce qui est posé.
MINEUR_CIBLE = "3.13"

# Les fichiers du moteur qui déclarent ses exigences.
DEFAULTS_ANSIBLE = os.path.join("roles", "serveur_ops", "defaults", "main.yml")
CLE_PLAGE = "serveur_ops_ansible"
REQUIREMENTS_PY = "requirements-python.txt"
REQUIREMENTS_YML = "requirements.yml"
PAQUET_ANSIBLE = "ansible-core"

# Les collections épinglées vont SOUS le moteur, dans un dossier que son
# `.gitignore` couvre : l'arbre reste propre, donc la ligne « Moteur » de
# l'écran d'état ne bouge pas. Elles ne se mêlent pas non plus à ce que le
# poste porte déjà, ce que `requirements.yml` du moteur exige explicitement.
# `ansible.cfg` du moteur ne déclare aucun `collections_path` et le défaut
# d'Ansible pointe ailleurs : `environnement()` le dit donc par variable.
COLLECTIONS = os.path.join(".ansible", "collections")
# Le sous-dossier qu'`ansible-galaxy` crée sous la destination, et le fichier
# qui porte la version posée.
ARBRE_COLLECTIONS = "ansible_collections"
MANIFESTE_COLLECTION = "MANIFEST.json"

# Le Python d'un venv dit la version d'un paquet qu'IL importe. Une seule
# ligne, pour qu'une sortie bavarde se voie comme illisible.
SONDE_VERSION = "import importlib.metadata as m; print(m.version({paquet!r}))"

# Le major.minor d'un interpréteur, en une ligne.
SONDE_MINEUR = "import sys; print('%d.%d' % sys.version_info[:2])"

# Borne des sondes de vérification, en secondes. Aucune ne touche le réseau.
DELAI_SONDE = 30

# L'action d'une étape que ce module joue lui-même, faute de commande à
# montrer : seule la suppression du venv en est une.
SUPPRIMER = "supprimer"


class Etape(NamedTuple):
    """Un geste de la pose.

    `argv` porte la commande ; `libelle` ne sert qu'aux étapes sans commande,
    que `action` nomme. CE QUI EST MONTRÉ EST CE QUI EST LANCÉ : l'affichage
    dérive d'`argv` par `montre()`, il n'est pas écrit une seconde fois.
    """

    argv: tuple | None
    libelle: str = ""
    action: str = ""


def montre(etape) -> str:
    """La ligne à afficher pour `etape`, citée comme un shell la lirait."""
    if etape.argv is None:
        return etape.libelle
    return shlex.join(etape.argv)


# ---------------------------------------------------------------------------
# Ce que le moteur exige
# ---------------------------------------------------------------------------


def _valeur_de_premier_niveau(texte, cle):
    """La valeur scalaire de `cle` au premier niveau d'un YAML, ou None.

    Lecture ligne à ligne, sans PyYAML : `cle: valeur`, entre guillemets
    simples ou doubles, ou nue, commentaire final permis. Toute autre forme
    — bloc, échappement, clé répétée, clé absente — rend None : une forme
    inattendue refuse au lieu de deviner.
    """
    motif = re.compile(
        re.escape(cle)
        + r":[ \t]*(?:\"([^\"\\]*)\"|'([^']*)'|([^\s#\"'][^#]*?))"
        + r"[ \t]*(?:#.*)?"
    )
    trouvees = []
    for ligne in texte.splitlines():
        if not ligne.startswith(cle + ":"):
            continue
        prise = motif.fullmatch(ligne)
        if prise is None:
            return None
        trouvees.append(next(g for g in prise.groups() if g is not None))
    if len(trouvees) != 1 or not trouvees[0].strip():
        return None
    return trouvees[0].strip()


def plage_ansible(moteur):
    """L'exigence `CLE_PLAGE` des défauts du moteur, telle qu'il l'écrit."""
    try:
        with open(
            os.path.join(moteur, DEFAULTS_ANSIBLE), encoding="utf-8"
        ) as fichier:
            texte = fichier.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return _valeur_de_premier_niveau(texte, CLE_PLAGE)


def specifieur(texte):
    """La plage de versions de l'exigence `texte`, ou None.

    None pour tout ce qui n'est pas une exigence d'ansible-core bornée :
    un texte illisible, un autre paquet, une URL, des extras, un marqueur,
    ou aucune borne — une plage qui accepte tout n'épingle rien.
    """
    if not isinstance(texte, str):
        return None
    try:
        exigence = Requirement(texte)
    except InvalidRequirement:
        return None
    if (
        canonicalize_name(exigence.name) != PAQUET_ANSIBLE
        or exigence.url
        or exigence.extras
        or exigence.marker is not None
        or not len(exigence.specifier)
    ):
        return None
    return exigence.specifier


def version(texte):
    """La version PEP 440 écrite dans `texte`, ou None."""
    try:
        return Version(texte)
    except (InvalidVersion, TypeError):
        return None


def dans_la_plage(version_texte, plage_texte):
    """La version est-elle dans la plage ? None si l'un des deux est illisible.

    La règle des pré-versions est passée explicitement : laissée au défaut,
    elle dépendrait de la version de `packaging` installée sur le poste.
    """
    plage = specifieur(plage_texte)
    lue = version(version_texte)
    if plage is None or lue is None:
        return None
    return plage.contains(lue, prereleases=bool(plage.prereleases))


def bibliotheques_epinglees(moteur):
    """(nom, version) de chaque bibliothèque que le moteur épingle, ou None
    quand le fichier ne se lit pas.

    LA DIFFÉRENCE COMPTE : un tuple vide dit « le moteur n'épingle rien »,
    et None dit « on ne sait pas ». Les confondre ferait porter la ligne
    d'état sur un fichier illisible, en annonçant zéro écart.

    Seules les épingles exactes comptent : une ligne sans `==` ne dit pas
    quoi vérifier après la pose, et une ligne illisible est ignorée plutôt
    que de faire échouer la lecture entière.
    """
    try:
        with open(
            os.path.join(moteur, REQUIREMENTS_PY), encoding="utf-8"
        ) as fichier:
            lignes = fichier.read().splitlines()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    trouvees = []
    for ligne in lignes:
        nue = ligne.split("#", 1)[0].strip()
        if not nue:
            continue
        try:
            exigence = Requirement(nue)
        except InvalidRequirement:
            continue
        exactes = [s.version for s in exigence.specifier if s.operator == "=="]
        if len(exactes) == 1:
            trouvees.append((exigence.name, exactes[0]))
    return tuple(trouvees)


def collections_epinglees(moteur):
    """(nom, version) de chaque collection que le moteur épingle, ou None
    quand le fichier ne se lit pas ou n'a pas la forme attendue.

    PyYAML plutôt qu'une expression : ce fichier est de la donnée simple,
    là où les défauts du rôle portent du Jinja qu'on ne veut pas traverser.
    Une entrée sans version est ignorée — elle ne dit pas quoi vérifier —
    mais un fichier sans liste `collections` rend None : une forme
    inattendue refuse au lieu de deviner qu'il n'y a rien.
    """
    try:
        with open(
            os.path.join(moteur, REQUIREMENTS_YML), encoding="utf-8"
        ) as fichier:
            lu = yaml.safe_load(fichier)
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(lu, dict):
        return None
    entrees = lu.get("collections")
    if not isinstance(entrees, list):
        return None
    trouvees = []
    for entree in entrees:
        if not isinstance(entree, dict):
            continue
        nom, pose = entree.get("name"), entree.get("version")
        if isinstance(nom, str) and isinstance(pose, (str, int, float)):
            trouvees.append((nom, str(pose)))
    return tuple(trouvees)


# ---------------------------------------------------------------------------
# Ce que le poste offre
# ---------------------------------------------------------------------------


def _lancer(argv, env=None, cwd=None, capture=True):
    """Lance `argv` dans `cwd`, entrée fermée, borné par `DELAI_SONDE`.

    Rend le CompletedProcess, ou None quand le processus n'a pas pu tourner
    jusqu'au bout (introuvable, délai dépassé, argument invalide).
    """
    sortie = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        return subprocess.run(
            argv,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=sortie,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DELAI_SONDE,
            check=False,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def _mise_ou(mineur=MINEUR_CIBLE):
    """Le dossier où `mise` a posé `mineur`, ou None.

    `mise where python@X` rend 0 et le chemin quand la version est posée, 1
    sinon. `mise which` ne répond QUE depuis un dossier où la version est
    activée : il dit l'activation, pas la présence.
    """
    if shutil.which("mise") is None:
        return None
    fait = _lancer(("mise", "where", f"python@{mineur}"))
    if fait is None or fait.returncode != 0:
        return None
    dossier = fait.stdout.strip()
    return dossier if dossier and os.path.isdir(dossier) else None


def interprete(mineur=MINEUR_CIBLE):
    """Un Python `mineur` utilisable, et d'où il vient.

    Rend (chemin, provenance) ou (None, ""). L'ordre est celui du moindre
    ajout : un interpréteur déjà posé sur le PATH — ce qu'une Debian 13
    livre — avant celui d'un gestionnaire de versions.
    """
    nom = "python" + mineur
    trouve = shutil.which(nom)
    if trouve:
        return trouve, "PATH"
    dossier = _mise_ou(mineur)
    if dossier:
        chemin = os.path.join(dossier, "bin", nom)
        if os.access(chemin, os.X_OK):
            return chemin, "mise"
    return None, ""


def geste_mise(mineur=MINEUR_CIBLE):
    """La commande qui poserait `mineur` par mise, ou None s'il est absent.

    Nommée pour être MONTRÉE quand aucun interpréteur ne convient : le menu
    ne pose pas un gestionnaire de versions dans le dos de l'opérateur.
    """
    if shutil.which("mise") is None:
        return None
    return ("mise", "install", f"python@{mineur}")


# ---------------------------------------------------------------------------
# Poser, et vérifier
# ---------------------------------------------------------------------------


def chemin_venv(racine):
    """Le venv du contrôleur sous `racine`, en chemin ABSOLU.

    L'absolu n'est pas une coquetterie : les sondes tournent avec `cwd`
    DANS le venv, et un argv relatif s'y résoudrait alors par rapport à
    lui-même — la sonde ne trouverait rien et l'écran dirait « illisible »
    pendant qu'une vérification lancée depuis ailleurs lit la version.
    """
    return os.path.join(os.path.abspath(racine), VENV)


def etapes(racine, moteur, python, plage, refaire=False):
    """Les gestes de la pose, dans l'ordre, prêts à être montrés puis joués.

    `plage` est l'exigence TELLE QUE LE MOTEUR L'ÉCRIT : elle part à pip sans
    être reformulée, pour qu'un désaccord se voie plutôt que de se corriger
    en silence. `refaire` ouvre la suite par la suppression du venv, seule
    façon de changer l'INTERPRÉTEUR d'un venv déjà posé — réinstaller
    par-dessus laisse le mauvais.
    """
    venv = chemin_venv(racine)
    pas = []
    if refaire:
        pas.append(
            Etape(
                argv=None,
                libelle=f"rm -rf {shlex.quote(venv)}",
                action=SUPPRIMER,
            )
        )
    pas.append(Etape(argv=(python, "-m", "venv", venv)))
    pip = os.path.join(venv, "bin", "pip")
    pas.append(Etape(argv=(pip, "install", plage)))
    pas.append(
        Etape(
            argv=(pip, "install", "-r", os.path.join(moteur, REQUIREMENTS_PY))
        )
    )
    pas.append(
        Etape(
            argv=(
                os.path.join(venv, "bin", "ansible-galaxy"),
                "collection",
                "install",
                "-r",
                os.path.join(moteur, REQUIREMENTS_YML),
                "-p",
                os.path.join(moteur, COLLECTIONS),
            )
        )
    )
    return tuple(pas)


def environnement(racine, moteur, base=None):
    """L'environnement sous lequel jouer un geste du moteur.

    LE VENV EN TÊTE DU PATH, et pas seulement un chemin absolu vers
    `bin/ansible-playbook` : la garde de `serveur_ops` lance `python3` NU
    (`delegate_to: localhost`) et le téléchargement des roues aussi. Sur un
    poste dont le `python3` de shell est en 3.14, le même venv en 3.13 rend
    un refus quand on l'appelle par chemin absolu, et passe quand son `bin`
    est en tête.

    ANSIBLE_COLLECTIONS_PATH : `ansible.cfg` du moteur n'en déclare pas, et
    le défaut d'Ansible ne regarde pas sous le moteur.
    """
    env = dict(os.environ if base is None else base)
    venv = chemin_venv(racine)
    env["VIRTUAL_ENV"] = venv
    env["PATH"] = os.path.join(venv, "bin") + os.pathsep + env.get("PATH", "")
    env["ANSIBLE_COLLECTIONS_PATH"] = os.path.join(moteur, COLLECTIONS)
    return env


def version_posee(racine, paquet):
    """La version de `paquet` que le Python du venv importe, ou None.

    LANCÉ DEPUIS LE VENV : `-c` met le dossier courant en tête de
    `sys.path`, et la racine d'ERPLibre n'a rien à y faire — un dossier ou
    des métadonnées qui y porteraient le nom du paquet seraient lus à la
    place de ce que le venv a posé. Une seule ligne non vide est une
    réponse ; toute autre sortie est illisible.
    """
    venv = chemin_venv(racine)
    fait = _lancer(
        (
            os.path.join(venv, "bin", "python"),
            "-c",
            SONDE_VERSION.format(paquet=paquet),
        ),
        cwd=venv,
    )
    if fait is None or fait.returncode != 0:
        return None
    lues = fait.stdout.strip().splitlines()
    if len(lues) != 1 or not lues[0].strip():
        return None
    return lues[0].strip()


def version_collection(moteur, nom):
    """La version de la collection `nom` posée sous le moteur, ou None."""
    parts = nom.split(".")
    if len(parts) != 2 or not all(parts):
        return None
    chemin = os.path.join(
        moteur, COLLECTIONS, ARBRE_COLLECTIONS, *parts, MANIFESTE_COLLECTION
    )
    try:
        with open(chemin, encoding="utf-8") as fichier:
            lu = json.load(fichier)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    info = lu.get("collection_info") if isinstance(lu, dict) else None
    pose = info.get("version") if isinstance(info, dict) else None
    return str(pose) if isinstance(pose, (str, int, float)) else None


def mineur_du_path(racine, moteur):
    """Le `major.minor` que rend `python3` RÉSOLU PAR LE PATH du geste, ou
    None quand la sonde ne répond pas.

    C'est la mesure que fera la garde du moteur, qui lance `python3` NU. Un
    venv effacé sous les pieds se voit ainsi, là où un chemin absolu vers
    `bin/python` répondrait encore. La conformité se DÉDUIT de ce qui est
    rendu — deux champs, l'un disant « 3.14 » et l'autre « conforme », se
    contrediraient sans que rien ne l'empêche.
    """
    fait = _lancer(
        (
            "python3",
            "-c",
            SONDE_MINEUR,
        ),
        env=environnement(racine, moteur),
    )
    if fait is None or fait.returncode != 0:
        return None
    lu = fait.stdout.strip()
    return lu or None


# Borne de chaque étape de la pose. `pip` et `ansible-galaxy` sortent vers
# le réseau : la borne est large, mais elle existe, pour qu'un miroir qui ne
# répond plus rende la main au lieu de figer le menu.
DELAI_POSE = 1800


def _supprimer_venv(racine):
    """Efface le venv du contrôleur. Rend 0 s'il n'en reste rien.

    LE GARDE PORTE SUR LA FORME DU CHEMIN : un dossier réel, nommé `VENV`,
    directement sous la racine. Un lien n'est pas suivi — le suivre
    effacerait ce qu'il désigne, qui n'est pas ce que l'écran a nommé.
    """
    racine = os.path.abspath(racine)
    cible = os.path.join(racine, VENV)
    if os.path.dirname(cible) != racine or os.path.basename(cible) != VENV:
        return 1
    if os.path.islink(cible) or not os.path.isdir(cible):
        return 1
    try:
        shutil.rmtree(cible)
    except OSError:
        return 1
    return 0


def jouer(etape, racine, env=None):
    """Joue `etape` et rend son code de retour ; 0 vaut réussite.

    La sortie n'est PAS capturée : une pose dure des minutes, et un
    opérateur qui ne voit rien ne sait pas distinguer un téléchargement lent
    d'un blocage. Un processus qui n'a pas pu tourner jusqu'au bout rend un
    code non nul plutôt que de lever : l'appelant arrête la suite.
    """
    if etape.action == SUPPRIMER:
        return _supprimer_venv(racine)
    if etape.argv is None:
        return 1
    try:
        fait = subprocess.run(
            etape.argv,
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=DELAI_POSE,
            check=False,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return 1
    return fait.returncode
