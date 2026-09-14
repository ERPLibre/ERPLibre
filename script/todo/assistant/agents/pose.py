#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser et retirer les hooks de télémétrie, aux deux endroits possibles.

Claude Code lit ses réglages à deux endroits que ce dépôt peut écrire, et le
choix n'est pas indifférent :

| Endroit | Portée | Ce que ça coûte |
|---|---|---|
| `~/.claude/settings.json` | tous les dépôts de la machine | rien de suivi ne bouge |
| `.claude/settings.json` du dépôt | ce dépôt, tout clone | fichier SUIVI par git |

Le second n'est pas une idée neuve : ce dépôt y pose déjà un bloc `env`. Mais
il s'applique à quiconque travaille ici, alors que le premier ne mesure que la
machine de celui qui l'a posé. L'écran offre les deux et DIT lequel est actif —
sans quoi un utilisateur qui pose le global et voit ses appels manquer ne
saurait pas que le dépôt en avait un autre.

**Le bloc est FUSIONNÉ, jamais écrasé.** Un fichier de réglages porte
volontiers d'autres hooks — un formateur, un garde-fou de projet — et les
remplacer par les nôtres retirerait silencieusement le travail de quelqu'un
d'autre. La pose n'ajoute que ses propres entrées, reconnaissables à leur
commande, et le retrait n'enlève que celles-là.

**L'écriture est atomique.** Un fichier de réglages à moitié écrit empêche
Claude Code de démarrer, donc le nouveau contenu passe par un temporaire du
même répertoire puis un `os.replace`, qui ne laisse jamais de fichier
tronqué.
"""
from __future__ import annotations

import json
import os
import tempfile

from script.todo.assistant.agents import journal

# Les deux endroits, et la clé qui les nomme dans le menu.
GLOBAL = "global"
DEPOT = "depot"

CHEMINS = {
    GLOBAL: "~/.claude/settings.json",
    DEPOT: ".claude/settings.json",
}

# Ce qui reconnaît NOS entrées parmi celles d'un autre. Le chemin du script
# suffit et ne dépend pas du répertoire d'où le menu a été lancé.
SIGNATURE = "assistant/agents/hooks/evenement.py"

# Le hook vu depuis la racine du dépôt. Claude Code lance un hook avec le
# dépôt pour répertoire courant, donc ce chemin y suffit.
RELATIF = "script/todo/assistant/agents/hooks/evenement.py"

# Le délai laissé au hook, en secondes. Il écrit une ligne : au-delà d'une
# seconde, quelque chose est cassé et il vaut mieux que Claude Code passe
# outre que d'attendre.
DELAI = 5


def _script() -> str:
    """Le chemin absolu du hook, tel qu'il sera écrit dans les réglages."""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "hooks", "evenement.py")
    )


def commande(endroit=GLOBAL, *, python=None, script=None) -> str:
    """La ligne que Claude Code lancera, nommée selon l'endroit qui la porte.

    Dans `~/.claude/settings.json`, tout est ABSOLU. Ce fichier ne vaut que
    pour cette machine, et l'interpréteur nommé en entier ne dépend pas du
    PATH du shell qui a lancé la session — un « python3 » qui ne résout pas
    fait tomber la télémétrie en silence.

    Dans le `.claude/settings.json` du dépôt, RIEN ne l'est, et pour deux
    raisons qui vont dans le même sens. Ce fichier est suivi par git : un
    chemin absolu y inscrit le nom du compte qui a posé les hooks, ce que les
    conventions du dépôt interdisent partout hors de `private/`. Et il désigne
    un répertoire qu'aucun autre clone n'a, ce qui vide de son sens l'entrée
    « pour tout clone ». Le hook n'importe rien du dépôt et ne demande que la
    bibliothèque standard, donc `python3` et un chemin relatif suffisent.
    """
    import sys

    if endroit == DEPOT:
        return f"{python or 'python3'} {script or RELATIF}"
    return f"{python or sys.executable} {script or _script()}"


def bloc(endroit=GLOBAL, *, python=None, script=None) -> dict:
    """Le bloc `hooks` que la pose ajoute, un matcher par événement.

    `matcher` vaut « * » sur les événements d'outil : ce qui est compté, c'est
    l'appel de N'IMPORTE QUEL outil, et une liste d'outils à jour serait à
    refaire à chaque version de Claude Code.
    """
    ligne = commande(endroit, python=python, script=script)
    entree = {
        "hooks": [{"type": "command", "command": ligne, "timeout": DELAI}]
    }
    hooks = {}
    for evenement in journal.EVENEMENTS:
        forme = dict(entree)
        # Tout événement d'OUTIL porte un matcher : ce qui est compté est
        # l'appel de n'importe quel outil, échec compris.
        if "Tool" in evenement:
            forme = {"matcher": "*", **entree}
        hooks[evenement] = [forme]
    return hooks


def _charger(chemin) -> dict | None:
    """Les réglages d'un fichier, ou None quand il y a là quelque chose
    d'illisible.

    None et `{}` disent le contraire l'un de l'autre : le second est « il n'y
    a pas de fichier », le premier « il y en a un, et le décodage le
    refuse ». Les confondre fait écrire un fichier NEUF par-dessus des
    réglages existants — une virgule en trop suffit alors à effacer les hooks,
    les permissions et les variables de quelqu'un d'autre.
    """
    try:
        with open(chemin, encoding="utf-8") as fh:
            donnees = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


def _ecrire(chemin, donnees) -> None:
    """Écriture atomique : un temporaire du même répertoire, puis `os.replace`.

    Un fichier de réglages à moitié écrit empêche Claude Code de démarrer.

    Le chemin est d'abord résolu. Un `settings.json` est volontiers un lien
    vers un dépôt de fichiers de configuration, et `os.replace` sur le LIEN le
    remplacerait par un fichier ordinaire : le fichier se détacherait de son
    dépôt sans que rien ne le dise.
    """
    chemin = os.path.realpath(chemin)
    dossier = os.path.dirname(chemin) or "."
    os.makedirs(dossier, exist_ok=True)
    fd, provisoire = tempfile.mkstemp(dir=dossier, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(donnees, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(provisoire, chemin)
    except Exception:
        try:
            os.unlink(provisoire)
        except OSError:
            pass
        raise


def _est_le_notre(entree) -> bool:
    """Vrai si cette entrée de hook est celle que ce dépôt pose."""
    if not isinstance(entree, dict):
        return False
    for hook in entree.get("hooks") or ():
        if isinstance(hook, dict) and SIGNATURE in str(
            hook.get("command") or ""
        ):
            return True
    return False


def fusionner(reglages, nouveau) -> dict:
    """Ajouter nos entrées SANS toucher à celles des autres. Fonction pure.

    Une entrée à nous déjà présente est remplacée — le chemin de
    l'interpréteur change quand l'environnement virtuel est refait — et tout
    le reste est laissé exactement où il est.
    """
    fusion = dict(reglages)
    hooks = dict(fusion.get("hooks") or {})
    for evenement, entrees in nouveau.items():
        gardees = [
            e for e in (hooks.get(evenement) or []) if not _est_le_notre(e)
        ]
        hooks[evenement] = gardees + list(entrees)
    fusion["hooks"] = hooks
    return fusion


def retirer_de(reglages) -> dict:
    """Enlever nos entrées et rien d'autre. Fonction pure.

    Un événement qui n'a plus que les nôtres perd sa clé, et un fichier qui
    n'a plus aucun hook perd la clé `hooks` : laisser des coquilles vides
    ferait croire à une pose partielle.
    """
    fusion = dict(reglages)
    hooks = {}
    for evenement, entrees in (fusion.get("hooks") or {}).items():
        gardees = [e for e in (entrees or []) if not _est_le_notre(e)]
        if gardees:
            hooks[evenement] = gardees
    if hooks:
        fusion["hooks"] = hooks
    else:
        fusion.pop("hooks", None)
    return fusion


def actifs(reglages) -> tuple[str, ...]:
    """Les événements où NOS hooks sont posés, dans l'ordre du journal."""
    hooks = reglages.get("hooks") or {}
    return tuple(
        evenement
        for evenement in journal.EVENEMENTS
        if any(_est_le_notre(e) for e in (hooks.get(evenement) or []))
    )


def chemin_de(endroit, *, racine_depot=None) -> str:
    """Le fichier de réglages d'un endroit, chemin absolu."""
    brut = CHEMINS[endroit]
    if endroit == DEPOT:
        base = racine_depot or os.getcwd()
        return os.path.join(base, brut)
    return os.path.expanduser(brut)


def etat(*, racine_depot=None, charger=None) -> dict:
    """{endroit: (chemin, événements actifs)} — ce que l'écran affiche.

    Les deux endroits sont TOUJOURS rendus, même absents : c'est ce qui permet
    de dire « posé ici, pas là » plutôt que de taire celui qui manque. Les
    événements valent None quand le fichier est là sans être relisible, ce qui
    n'est pas « aucun hook posé » : on ne sait pas.
    """
    charger = charger or _charger
    rapport = {}
    for endroit in (GLOBAL, DEPOT):
        chemin = chemin_de(endroit, racine_depot=racine_depot)
        reglages = charger(chemin)
        rapport[endroit] = (
            chemin,
            None if reglages is None else actifs(reglages),
        )
    return rapport


def _relire(chemin, charger) -> dict:
    """Les réglages à modifier, ou une erreur qui refuse d'écrire à l'aveugle.

    C'est le seul endroit qui transforme « illisible » en refus. Écrire
    par-dessus un fichier qu'on n'a pas su relire remplacerait tout ce qu'il
    portait par nos seules entrées.
    """
    reglages = charger(chemin)
    if reglages is None:
        raise OSError(f"réglages illisibles, rien n'est écrit : {chemin}")
    return reglages


def poser(endroit, *, racine_depot=None, charger=None, ecrire=None, **kw):
    """Poser nos hooks à un endroit. Rend le chemin écrit."""
    charger = charger or _charger
    ecrire = ecrire or _ecrire
    chemin = chemin_de(endroit, racine_depot=racine_depot)
    ecrire(chemin, fusionner(_relire(chemin, charger), bloc(endroit, **kw)))
    return chemin


def retirer(endroit, *, racine_depot=None, charger=None, ecrire=None):
    """Retirer nos hooks d'un endroit. Rend le chemin écrit."""
    charger = charger or _charger
    ecrire = ecrire or _ecrire
    chemin = chemin_de(endroit, racine_depot=racine_depot)
    ecrire(chemin, retirer_de(_relire(chemin, charger)))
    return chemin
