#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les agents lancés en arrière-plan : ce qui tourne, et ce qui est revenu.

Un agent détaché survit au menu qui l'a lancé. Il n'a donc plus de terminal
où écrire, et sa sortie va dans un fichier ; ce qu'on sait de lui au départ
va dans un second, à côté. Deux fichiers plutôt qu'un parce que le premier
est écrit par le PROCESSUS et le second par le lanceur : les mêler ferait
écrire deux auteurs dans un fichier que l'un des deux tronque à l'ouverture.

**La sortie fait foi, le pid ne fait que deviner.** Un identifiant de
processus se recycle, et interroger celui d'un agent fini peut désigner un
inconnu bien vivant. Une sortie qui porte l'enveloppe complète dit donc FINI
quel que soit le pid ; le pid ne sert qu'à distinguer « pas encore fini » de
« parti sans rien rendre ».

**La question part sur l'entrée standard.** Une ligne de commande se lit par
tout compte de la machine, et une question porte du contexte. C'est la même
raison qui vaut pour l'appel synchrone, et elle ne change pas parce que
l'appel dure plus longtemps.

**Rien ici ne décide des outils.** Le lanceur reçoit l'argv tout fait :
c'est `backends.claude_argv` qui sait ce qu'un agent a le droit de toucher,
et le redécider ici ferait deux réponses à la même question.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Où vivent les traces d'un agent détaché, sous le dossier de l'utilisateur.
BASE = ("~", ".erplibre", "assistant", "agents")

# Les droits : une question et sa réponse portent ce qu'on y a mis.
MODE_DOSSIER = 0o700
MODE_FICHIER = 0o600

# Les suffixes des deux fichiers d'une course.
META = ".meta.json"
SORTIE = ".out"

# Les états qu'une course peut porter.
EN_COURS = "en cours"
FINI = "fini"
PERDU = "perdu"


@dataclass(frozen=True)
class Course:
    """Un agent lancé, et ce qu'on en sait.

    `resultat` est vide tant que l'enveloppe n'est pas revenue ; `cout` vaut
    `None` quand elle ne le dit pas, et non zéro — un coût inconnu n'est pas
    un coût nul.
    """

    cle: str
    agent: str
    debut: str
    pid: int
    cwd: str
    outils: tuple[str, ...]
    etat: str
    resultat: str
    cout: float | None


def racine(base=None) -> Path:
    """La racine des courses sur le disque. Jamais None."""
    if base is None:
        return Path(os.path.expanduser(os.path.join(*BASE)))
    return Path(base)


def maintenant() -> str:
    """L'instant, en ISO 8601 avec son décalage."""
    return (
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )


def vivant(pid) -> bool:
    """Le processus répond-il encore ? Jamais lève.

    Le signal zéro ne tue rien : il demande seulement si le noyau connaît ce
    processus et si l'on a le droit de lui parler. Un pid recyclé répond donc
    vrai pour un inconnu, ce que l'état d'une course corrige en lisant
    d'abord sa sortie.
    """
    try:
        os.kill(int(pid), 0)
    except (OSError, OverflowError, TypeError, ValueError):
        # `OverflowError` et non `OSError` : un pid plus grand que ce que
        # l'appel système accepte lève AVANT d'atteindre le noyau, et une
        # fiche abîmée emporterait la liste entière.
        return False
    return True


def enveloppe(texte) -> dict:
    """L'enveloppe JSON d'un `claude -p`, ou {} si elle n'est pas là.

    Fonction PURE. La sortie peut porter des lignes de diagnostic avant le
    JSON : la DERNIÈRE ligne qui s'analyse en objet est retenue, les autres
    n'étant pas le résultat.
    """
    trouve = {}
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne.startswith("{"):
            continue
        try:
            lu = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(lu, dict):
            trouve = lu
    return trouve


def etat_de(sortie, pid) -> str:
    """L'état d'une course. Fonction PURE une fois la liveness donnée.

    `pid` est ici un BOOLÉEN — le processus répond ou non. L'ordre des tests
    est ce qui compte : une sortie complète l'emporte sur un pid vivant,
    parce qu'un pid se recycle et qu'une enveloppe ne s'invente pas.
    """
    if enveloppe(sortie):
        return FINI
    return EN_COURS if pid else PERDU


def _lire(chemin) -> str:
    try:
        return Path(chemin).read_text(encoding="utf-8")
    except OSError:
        return ""


def lancer(
    cle,
    agent,
    question,
    argv,
    *,
    cwd="",
    outils=(),
    base=None,
    demarrer=None,
) -> Course | None:
    """Détache un agent et rend sa course, ou None si rien n'a démarré.

    `demarrer(argv, question, sortie)` est le lanceur injecté ; laissé à
    `None`, il ouvre un vrai processus dans sa PROPRE session — sans quoi la
    fermeture du terminal l'emporterait avec elle.
    """
    ou = racine(base)
    debut = maintenant()
    try:
        ou.mkdir(parents=True, mode=MODE_DOSSIER, exist_ok=True)
        os.chmod(ou, MODE_DOSSIER)
    except OSError:
        return None
    chemin_sortie = ou / f"{cle}{SORTIE}"
    demarrer = _demarrer if demarrer is None else demarrer
    try:
        pid = demarrer(list(argv), question, chemin_sortie)
    except OSError:
        return None
    if not pid:
        return None
    meta = {
        "cle": cle,
        "agent": agent,
        "debut": debut,
        "pid": int(pid),
        "cwd": str(cwd),
        "outils": list(outils),
    }
    try:
        drapeaux = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        with os.fdopen(
            os.open(ou / f"{cle}{META}", drapeaux, MODE_FICHIER),
            "w",
            encoding="utf-8",
        ) as fichier:
            json.dump(meta, fichier, ensure_ascii=False)
    except OSError:
        # Le processus TOURNE déjà : perdre sa fiche coûte son suivi, pas son
        # travail, et l'annoncer perdu serait faux.
        pass
    return Course(
        cle=cle,
        agent=agent,
        debut=debut,
        pid=int(pid),
        cwd=str(cwd),
        outils=tuple(outils),
        etat=EN_COURS,
        resultat="",
        cout=None,
    )


def _demarrer(argv, question, chemin_sortie) -> int:
    """Ouvre le processus détaché et rend son pid.

    `start_new_session` lui donne sa propre session : sans elle, fermer le
    terminal enverrait un signal au groupe entier et l'agent mourrait avec
    le menu qui l'a lancé.
    """
    drapeaux = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    sortie = os.fdopen(os.open(chemin_sortie, drapeaux, MODE_FICHIER), "wb")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=sortie,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        sortie.close()
    try:
        proc.stdin.write((question or "").encode("utf-8"))
    finally:
        # La fermeture DIT à l'agent que la question est finie : sans elle il
        # attendrait une suite qui ne vient pas.
        proc.stdin.close()
    return proc.pid


def courses(*, base=None, en_vie=None) -> list[Course]:
    """Les courses connues, la plus récente d'abord.

    `en_vie` remplace l'interrogation du noyau, ce qui permet d'éprouver les
    trois états sans lancer de processus.
    """
    ou = racine(base)
    en_vie = vivant if en_vie is None else en_vie
    try:
        fiches = sorted(ou.glob(f"*{META}"), reverse=True)
    except OSError:
        return []
    trouves = []
    for fiche in fiches:
        try:
            meta = json.loads(fiche.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or not meta.get("cle"):
            continue
        sortie = _lire(ou / f"{meta['cle']}{SORTIE}")
        lu = enveloppe(sortie)
        trouves.append(
            Course(
                cle=str(meta.get("cle", "")),
                agent=str(meta.get("agent", "")),
                debut=str(meta.get("debut", "")),
                pid=int(meta.get("pid", 0) or 0),
                cwd=str(meta.get("cwd", "")),
                outils=tuple(meta.get("outils") or ()),
                etat=etat_de(sortie, en_vie(meta.get("pid", 0))),
                resultat=str(lu.get("result", "") or ""),
                cout=_cout(lu),
            )
        )
    return trouves


def _cout(lu) -> float | None:
    """Le coût que l'enveloppe déclare, ou None. Jamais zéro par défaut :
    un coût inconnu n'est pas un coût nul."""
    for champ in ("total_cost_usd", "cost_usd"):
        valeur = lu.get(champ)
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            return float(valeur)
    return None
