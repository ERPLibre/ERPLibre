#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'on a CONSTATÉ d'une sauvegarde, et quand.

Un vérificateur dit ce qu'il voit à l'instant où on le lance ; personne ne
le relance avant d'en avoir besoin. Le témoin est ce qui permet de répondre
« la dernière fois qu'on a regardé, c'était il y a trois semaines » — une
réponse que ni le fichier ni le vérificateur ne portent.

IL PORTE UN CONSTAT, JAMAIS UNE SAISIE. Rien ici ne vient d'une réponse
d'opérateur : poser la question, recevoir « oui » et ne rien vérifier
reproduit exactement l'illusion qu'on veut retirer.

IL VIT HORS DU DÉPÔT, dans le répertoire personnel. Deux raisons, et la
seconde est la vraie : une sauvegarde survit à une copie de travail, donc
son constat aussi ; et un fichier posé dans le dépôt se fait emporter par
un ratissage d'indexation, ce contre quoi la convention met déjà en garde.
Ce n'est pas non plus une préférence d'écran — celles-là se remettent à
zéro d'un geste, et le constat disparaîtrait avec elles.

CE QU'IL REFUSE À LA RELECTURE. Un verdict hors vocabulaire ou une date mal
formée trahissent un fichier modifié à la main : l'entrée est écartée plutôt
que crue. Un témoin qu'on peut éditer pour se rassurer ne vaut rien.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from script.database import backup_verify

# Le fichier de constats, et la variable qui le déplace. Résolu à CHAQUE
# appel : figé à l'import, il rendrait la couture inopérante pour qui pose
# la variable après le chargement.
WITNESS_PATH = os.path.join("~", ".erplibre", "backup_witness.json")
WITNESS_VAR = "EL_BACKUP_WITNESS"

# La forme d'un horodatage acceptable. Une date libre laisserait entrer une
# tournure de langage, qu'aucune soustraction ne sait lire.
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def witness_path() -> str:
    """Le chemin du témoin, la variable d'environnement d'abord."""
    return os.path.expanduser(os.environ.get(WITNESS_VAR) or WITNESS_PATH)


def stamp(now=None) -> str:
    """L'horodatage UTC à la seconde que porte un constat.

    Injectable pour qu'une épreuve puisse figer l'instant : sans cela, elle
    comparerait à une horloge qui avance pendant qu'elle lit.
    """
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lisible(entree) -> bool:
    """L'entrée a-t-elle la forme d'un constat, ou a-t-elle été retouchée ?"""
    if not isinstance(entree, dict):
        return False
    if entree.get("verdict") not in backup_verify.VERDICTS:
        return False
    return bool(STAMP_RE.match(str(entree.get("checked_at", ""))))


def entries() -> dict:
    """{chemin: constat}, les entrées retouchées écartées.

    Un fichier absent rend un dictionnaire vide : personne n'a encore
    regardé, ce qui n'est pas « rien à signaler ».
    """
    try:
        with open(witness_path(), encoding="utf-8") as fichier:
            data = json.load(fichier)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        chemin: entree for chemin, entree in data.items() if _lisible(entree)
    }


def _ecrire(data) -> None:
    """Écrit le témoin de façon atomique, en 0600 sous un parent en 0700.

    Le fichier réel n'est jamais vu à moitié écrit, et un fichier déjà là
    avec des permissions trop larges se retrouve corrigé.
    """
    chemin = witness_path()
    parent = os.path.dirname(chemin) or "."
    os.makedirs(parent, exist_ok=True)
    os.chmod(parent, 0o700)
    provisoire = f"{chemin}.tmp"
    descripteur = os.open(
        provisoire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        json.dump(data, fichier, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(provisoire, chemin)


def record(verification, now=None) -> dict:
    """Écrit le constat d'UNE sauvegarde et rend l'entrée posée.

    Indexé par chemin ABSOLU : deux façons d'écrire le même fichier ne
    doivent pas donner deux constats qui se contredisent.
    """
    entree = {
        "verdict": verification.verdict,
        "size": int(verification.size or 0),
        "checks": list(verification.checks),
        "checked_at": stamp(now),
    }
    if verification.detail:
        entree["detail"] = verification.detail
    data = dict(entries())
    data[os.path.abspath(verification.path)] = entree
    _ecrire(data)
    return entree
