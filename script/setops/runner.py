#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'exécuteur des gestes du moteur : argv cité, environnement neuf, verdict lu.

Trois règles, et chacune répare une façon précise de se tromper.

**L'ENVIRONNEMENT EST CONSTRUIT À NEUF**, jamais hérité. Hérité, il porte
trois choses qui décident à la place de l'opérateur : un `CONFIRMER=true`
resté d'un geste précédent, que les applicateurs du moteur lisent pour écrire
au lieu de simuler ; les surcharges du make parent (`MAKEFLAGS`, `MAKELEVEL`),
puisque todo se lance lui-même par `make todo` ; et les `ANSIBLE_*` ou
`SETOPS_*` que le moteur laisse gagner sur ses propres défauts — dont celui
qui désigne la grappe sur laquelle un geste destructeur porterait.

**LA COMMANDE PORTE SON `CONFIRMER`**, en clair, sur la ligne qu'on affiche.
Une variable passée à `make` sur la ligne de commande arrive dans
l'environnement du script appelé ET l'emporte sur celle qui serait héritée :
la ligne montrée est donc la ligne qui décide, et un `CONFIRMER=false` visible
vaut mieux qu'une absence qu'il faut savoir interpréter.

**LE VERDICT SE LIT**, code ET sortie. Plusieurs gestes du moteur rendent 0 en
ayant trouvé un écart : le code seul ne suffit pas, et un appelant qui ne lit
rien annonce une réussite qui n'a pas eu lieu.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import NamedTuple

# Les seules variables qui traversent. Tout le reste est écarté, y compris
# ce qui semble inoffensif : une liste blanche se relit, une liste noire
# s'oublie. `SSH_AUTH_SOCK` est là parce que les gestes qui joignent une
# machine passent par l'agent ; `XDG_CONFIG_HOME` et `HOME` disent où le
# moteur cherche les clés de voûte.
ENV_TRANSMIS = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_MESSAGES",
    "LOGNAME",
    "PATH",
    "SSH_AUTH_SOCK",
    "TERM",
    "USER",
    "XDG_CONFIG_HOME",
)

# Le venv d'ERPLibre n'a rien à faire dans le PATH d'un geste du moteur : il
# porte un autre Python et d'autres bibliothèques, et la garde du moteur
# interroge `python3` NU. Ses entrées sont retirées du PATH transmis.
VENV_ERPLIBRE = ".venv.erplibre"

# Le nom que les applicateurs du moteur lisent dans l'environnement. Rien
# d'autre que la chaîne « true » ne les fait écrire.
CONFIRMER = "CONFIRMER"
CONFIRME = "true"
SIMULE = "false"

# Borne d'un geste, en secondes. Un déploiement dure des minutes ; la borne
# existe pour qu'une machine qui ne répond plus rende la main.
DELAI = 3600


class Verdict(NamedTuple):
    """Ce qu'un geste a rendu.

    `code` vaut None quand le processus n'a pas pu tourner jusqu'au bout —
    introuvable, délai dépassé, argument invalide. C'est un verdict, pas une
    absence de verdict : l'appelant doit le distinguer d'un zéro.
    """

    code: int | None
    sortie: str

    @property
    def reussi(self) -> bool:
        """Le geste a-t-il rendu zéro ? Une panne de lancement vaut non."""
        return self.code == 0


def sans_venv_erplibre(path):
    """`path`, débarrassé des entrées qui vivent dans le venv d'ERPLibre.

    La comparaison porte sur un SEGMENT de chemin entier, jamais sur une
    sous-chaîne : un dossier qui contiendrait ce nom sans être ce venv reste
    en place, et une entrée relative n'est pas jugée sur son orthographe.
    """
    gardees = [
        entree
        for entree in (path or "").split(os.pathsep)
        if entree and VENV_ERPLIBRE not in entree.split(os.sep)
    ]
    return os.pathsep.join(gardees)


def base(source=None):
    """L'environnement d'un geste, construit à neuf : `ENV_TRANSMIS` seul.

    `source` remplace `os.environ` pour les épreuves. Le PATH transmis est
    débarrassé du venv d'ERPLibre ; `CONFIRMER` n'est PAS transmis, si bien
    qu'un `true` resté d'ailleurs ne peut pas atteindre le moteur.
    """
    vu = os.environ if source is None else source
    env = {cle: vu[cle] for cle in ENV_TRANSMIS if cle in vu}
    if "PATH" in env:
        env["PATH"] = sans_venv_erplibre(env["PATH"])
    return env


def cite(argv) -> str:
    """La commande, telle qu'un shell la lirait — ce qu'on affiche.

    Dérivée de l'argv et non écrite à côté : une ligne montrée qui n'est pas
    la ligne lancée est pire que pas de ligne du tout.
    """
    return shlex.join(argv)


def cible(moteur, nom, variables=(), confirmer=False):
    """L'argv d'une cible `make` du moteur, `CONFIRMER` toujours écrit.

    `variables` est une suite de (nom, valeur) posées après la cible, comme
    `make` les attend. `CONFIRMER` vient EN DERNIER et n'est jamais omis :
    une ligne sans lui laisse ignorer si le geste simule ou écrit.
    """
    # `--no-print-directory` retire les deux lignes « on entre / on quitte
    # le répertoire » : elles encadrent toute sortie, portent un chemin
    # absolu — donc un nom de compte — et un adaptateur fermé par défaut
    # les prendrait pour une forme inattendue.
    argv = ["make", "--no-print-directory", "-C", moteur, nom]
    argv += [f"{cle}={valeur}" for cle, valeur in variables]
    argv.append(f"{CONFIRMER}={CONFIRME if confirmer else SIMULE}")
    return tuple(argv)


def jouer(argv, env=None, cwd=None, capture=True, delai=DELAI, fusionner=True):
    """Joue `argv` et rend son `Verdict`. Ne lève jamais.

    Sans `capture`, la sortie va au terminal de l'opérateur et le verdict ne
    porte que le code : c'est ce qu'il faut d'un geste long, qu'on regarde
    avancer, ou d'un geste qui demande une phrase de passe.

    `fusionner` mêle la sortie d'erreur à la sortie standard, ce que veut un
    geste dont on lit le compte rendu. Une SONDE la refuse : un avertissement
    imprimé sur l'erreur ferait passer une réponse d'une ligne pour une
    réponse bavarde, donc illisible.
    """
    sortie = subprocess.PIPE if capture else None
    erreur = (
        (subprocess.STDOUT if fusionner else subprocess.DEVNULL)
        if capture
        else None
    )
    try:
        fait = subprocess.run(
            list(argv),
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=sortie,
            stderr=erreur,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=delai,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Verdict(None, "")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return Verdict(None, "")
    return Verdict(fait.returncode, fait.stdout or "")
