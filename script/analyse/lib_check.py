#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que les contrôleurs de `script/analyse/` partagent.

Ils lisent les mêmes fichiers, obéissent au même hook, et sortent selon la
même convention : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué.
Écrire cette mécanique dans chacun d'eux en ferait autant de façons de se
taire — un délai changé d'un côté, un répertoire ignoré de l'autre, et le
plus jeune des outils cesse de voir sans que rien ne le dise.

Ce module ne connaît AUCUNE convention de code. Il dit quels fichiers
regarder et comment rendre compte ; ce qu'il faut y chercher appartient à
chaque outil.
"""

from __future__ import annotations

import os
import subprocess

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

SUFFIXES = (".py",)

# Ce qui n'est pas balayé : ce qui n'est pas à nous, et ce qui n'est pas lu.
IGNORES = (
    ".git/",
    ".venv",
    "__pycache__/",
    "addons/",
    "node_modules/",
)


def a_balayer(chemin: str) -> bool:
    """Ce chemin est-il du code de ce dépôt ?"""
    nu = chemin.replace(os.sep, "/")
    return not any(motif in nu for motif in IGNORES)


def fichiers_indexes(suffixes=SUFFIXES):
    """Les fichiers ajoutés à l'index git, filtrés sur les suffixes lus."""
    sortie = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        cwd=RACINE,
    )
    chemins = []
    for nom in sortie.stdout.split("\n"):
        nom = nom.strip()
        if (
            nom.endswith(suffixes)
            and a_balayer(nom)
            and os.path.isfile(os.path.join(RACINE, nom))
        ):
            chemins.append(os.path.join(RACINE, nom))
    return chemins


def etend(chemins, suffixes=SUFFIXES):
    """Les fichiers lisibles d'une liste de chemins, répertoires parcourus."""
    trouves = []
    for chemin in chemins:
        if os.path.isdir(chemin):
            for base, _sous, noms in os.walk(chemin):
                if not a_balayer(base + "/"):
                    continue
                for nom in sorted(noms):
                    complet = os.path.join(base, nom)
                    if nom.endswith(suffixes) and a_balayer(complet):
                        trouves.append(complet)
        elif chemin.endswith(suffixes) and a_balayer(chemin):
            trouves.append(chemin)
    return trouves


def peindre(texte, code, colour=True):
    """Un texte coloré pour un terminal, nu pour un fichier ou un hook."""
    return f"\033[{code}m{texte}\033[0m" if colour else str(texte)


def relatif(chemin: str) -> str:
    """Le chemin tel qu'un lecteur le retape, depuis la racine du dépôt."""
    return os.path.relpath(chemin, RACINE)
