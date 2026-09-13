#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où en est l'installation d'Apertus, machine par machine.

Le fichier vit dans ~/.erplibre, HORS du dépôt, et la raison n'est pas le
confort. Une progression d'installation nomme sa machine — un alias SSH, un
nom d'hôte, une adresse. Un seul fichier du dépôt est réellement ignoré par
git ; tout le reste suit le dépôt en amont et devient public avec lui sur un
fork rendu public. Écrire ici met la question hors de portée plutôt que de la
confier à une ligne d'exclusion qu'un jour on déplace. Les préférences du CLI
suivent déjà ce chemin, pour la même raison.

Ce fichier ne sert qu'à REPRENDRE. Le serveur retenu, lui, passe par le
registre des serveurs et par son seul écrivain : rien ici n'est une source
de vérité sur ce qui répond.

`cibles` et `echecs` sont séparés exprès. Recommencer une installation remet
`cibles[...]` à neuf ; si l'historique vivait là, le geste effacerait
justement ce que l'écran de reprise doit montrer. `echecs` ne fait que
croître, et se borne à ses dernières entrées.

Tout est au mieux : un fichier illisible, un disque plein ou un
répertoire personnel en lecture seule rendent un état vide, jamais une
exception. Perdre une reprise coûte un téléchargement ; empêcher le CLI de
démarrer coûte davantage.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

# Version du schéma. Un fichier écrit par une version inconnue est ignoré
# plutôt que réinterprété de travers.
VERSION = 1

# Nombre d'échecs conservés. Au-delà, les plus anciens tombent : l'historique
# sert à comprendre la dernière séance, pas à tenir un journal.
ECHECS_MAX = 50

# Longueur maximale de la sortie d'erreur conservée, en caractères. Une
# compilation bavarde produit des mégaoctets, et seule la fin porte la cause.
QUEUE_MAX = 4000


def _path() -> Path:
    base = Path(os.path.expanduser("~/.erplibre"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "apertus_install.json"


def _charge() -> dict:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"version": VERSION, "cibles": {}, "echecs": []}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {"version": VERSION, "cibles": {}, "echecs": []}
    data.setdefault("cibles", {})
    data.setdefault("echecs", [])
    if not isinstance(data["cibles"], dict):
        data["cibles"] = {}
    if not isinstance(data["echecs"], list):
        data["echecs"] = []
    return data


def _sauve(data: dict) -> None:
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def _horodatage() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def lire(cible: str) -> dict:
    """L'état enregistré pour une cible, ou un dictionnaire vide."""
    etat = _charge()["cibles"].get(cible)
    return dict(etat) if isinstance(etat, dict) else {}


def ecrire(cible: str, **champs) -> None:
    """Fusionne des champs dans l'état d'une cible, et date la mise à jour."""
    data = _charge()
    etat = data["cibles"].get(cible)
    etat = dict(etat) if isinstance(etat, dict) else {}
    etat.update(champs)
    etat["cible"] = cible
    etat["maj"] = _horodatage()
    data["cibles"][cible] = etat
    _sauve(data)


def commencer(cible: str, moteur: str, modele: str, total: int) -> None:
    """Ouvre une tentative NEUVE : le compteur d'étapes repart de zéro.

    C'est le chemin d'une première installation et celui d'un « tout
    recommencer ». Une reprise passe par `reprendre`, qui compte aussi la
    tentative mais garde les étapes déjà franchies.
    """
    ancien = lire(cible)
    ecrire(
        cible,
        moteur=moteur,
        modele=modele,
        etapes_total=total,
        etape_faite=0,
        etape_echouee="",
        erreur="",
        code=None,
        debut=_horodatage(),
        fin="",
        secondes=0,
        tentatives=int(ancien.get("tentatives") or 0) + 1,
    )


def reprendre(cible: str) -> None:
    """Rouvre une tentative SANS effacer les étapes déjà franchies.

    Le compteur de tentatives s'incrémente ici comme dans `commencer` : une
    installation reprise trois fois s'est bien tentée trois fois, et l'écran
    de reprise le dit. Le marqueur d'échec est levé, sans quoi la cible
    paraîtrait cassée pendant qu'elle tourne.
    """
    etat = lire(cible)
    ecrire(
        cible,
        etape_echouee="",
        erreur="",
        code=None,
        tentatives=int(etat.get("tentatives") or 0) + 1,
    )


def avancer(cible: str, rang: int, secondes: int = 0) -> None:
    """Note qu'une étape est franchie, et le temps cumulé depuis le début."""
    ecrire(cible, etape_faite=rang, secondes=secondes, etape_echouee="")


def terminer(cible: str, secondes: int = 0) -> None:
    """Note l'installation complète : plus rien à reprendre pour cette cible."""
    ecrire(
        cible,
        fin=_horodatage(),
        secondes=secondes,
        etape_echouee="",
        erreur="",
        code=None,
    )


def noter_echec(
    cible: str, etape_cle: str, label: str, code: int, queue: str
) -> None:
    """Enregistre l'étape en échec sur la cible, et l'ajoute à l'historique.

    La sortie est tronquée par la FIN : c'est là que se trouve la cause, et
    un début de compilation ne dit rien de l'erreur qui l'a close.
    """
    extrait = (queue or "")[-QUEUE_MAX:]
    ecrire(cible, etape_echouee=etape_cle, erreur=extrait, code=code)
    data = _charge()
    data["echecs"].append(
        {
            "cible": cible,
            "etape": etape_cle,
            "label": label,
            "code": code,
            "queue": extrait,
            "ts": _horodatage(),
        }
    )
    data["echecs"] = data["echecs"][-ECHECS_MAX:]
    _sauve(data)


def oublier(cible: str) -> None:
    """Efface la progression d'une cible. L'historique des échecs demeure."""
    data = _charge()
    if data["cibles"].pop(cible, None) is not None:
        _sauve(data)


def dernier_echec(cible: str) -> dict:
    """Le dernier échec enregistré pour une cible, ou un dictionnaire vide."""
    for entree in reversed(_charge()["echecs"]):
        if entree.get("cible") == cible:
            return dict(entree)
    return {}


def a_reprendre(cible: str) -> bool:
    """Vrai si une installation s'est interrompue sur cette cible."""
    etat = lire(cible)
    return bool(etat.get("etape_echouee")) and not etat.get("fin")


def resume(cible: str) -> str:
    """L'état en un mot, pour le suffixe de l'entrée de menu.

    Rend une CLÉ de traduction et ses arguments, pas une phrase : la
    traduction appartient à l'appelant, et ce module n'importe pas le CLI.
    """
    etat = lire(cible)
    if not etat:
        return "never run"
    if etat.get("etape_echouee"):
        return "step %s/%s - failed"
    if etat.get("fin"):
        return "installed on %s"
    if etat.get("debut"):
        return "in progress"
    return "never run"
