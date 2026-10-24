#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Afficher chaque commande des outils git avant de la lancer.

`show(argv, cwd)` écrit « $ <commande> » sur la sortie d'ERREUR, une ligne
par commande, lectures comprises. La sortie standard reste aux données : le
JSON de repo_state.py, que erplibre_info lit par un tuyau, n'en reçoit
rien.

Actif quand la sortie d'erreur est un terminal : TODO et un lancement à la
main affichent tout, un appelant sans terminal (un service Odoo, un test)
n'est pas inondé. ERPLIBRE_GIT_ECHO=1 force l'affichage, =0 le coupe.

Un dossier sous la racine ERPLibre s'écrit en relatif, « git -C
odoo18.0/addons/OCA_web … » : c'est la commande à recopier depuis la
racine. Une URL perd ce qui peut porter un secret (utilisateur, mot de
passe, jeton) avant d'être affichée. Les passes parallèles écrivent sous un
verrou : une ligne ne se mêle jamais à une autre.

Bibliothèque standard seulement : repo_state.py tourne aussi sous le compte
d'un service Odoo.
"""

import os
import re
import shlex
import sys
import threading

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
VARIABLE = "ERPLIBRE_GIT_ECHO"

_verrou = threading.Lock()
# « https://utilisateur:jeton@hôte/… » : la partie avant « @ ».
_IDENTIFIANTS = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")


def active(flux=None) -> bool:
    """Vrai si les commandes s'affichent : ERPLIBRE_GIT_ECHO d'abord, sinon
    la sortie d'erreur est-elle un terminal."""
    valeur = os.environ.get(VARIABLE, "").strip()
    if valeur in ("1", "0"):
        return valeur == "1"
    flux = flux or sys.stderr
    try:
        return flux.isatty()
    except (AttributeError, ValueError):
        return False


def _chemin(cwd) -> str:
    """`cwd` relatif à la racine ERPLibre quand il est dessous, sinon tel
    quel."""
    absolu = os.path.abspath(cwd)
    try:
        relatif = os.path.relpath(absolu, RACINE)
    except ValueError:
        return absolu
    if relatif == os.curdir:
        return "."
    if relatif.startswith(os.pardir):
        return absolu
    return relatif


def render(argv, cwd=None) -> str:
    """La ligne affichée pour `argv` lancé dans `cwd`, sans secrets.

    Pour git, le dossier entre en « -C <dossier> » juste après « git »,
    sauf si la commande porte déjà un « -C ». Pour une autre commande, il
    la précède en « (cd <dossier>) ».
    """
    argv = [str(a) for a in argv]
    if cwd and argv[:1] == ["git"] and "-C" not in argv[1:3]:
        argv = ["git", "-C", _chemin(cwd), *argv[1:]]
    elif argv[:2] == ["git", "-C"] and len(argv) > 2:
        argv = ["git", "-C", _chemin(argv[2]), *argv[3:]]
    texte = shlex.join(argv)
    if cwd and argv[:1] != ["git"]:
        texte = f"(cd {shlex.quote(_chemin(cwd))}) {texte}"
    return _IDENTIFIANTS.sub(r"\1", texte)


def show(argv, cwd=None, flux=None) -> None:
    """Écrit « $ <commande> » avant son lancement, quand c'est actif."""
    flux = flux or sys.stderr
    if not active(flux):
        return
    ligne = f"$ {render(argv, cwd)}\n"
    with _verrou:
        try:
            flux.write(ligne)
            flux.flush()
        except (OSError, ValueError):
            pass
