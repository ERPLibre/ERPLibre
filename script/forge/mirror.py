#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le manifeste déclare, ce que la forge porte, et l'écart.

CE MODULE DÉCIDE ET N'APPELLE RIEN. Il reçoit deux listes de noms et rend un
plan ; l'appelant exécute. C'est ce qui rend le rapprochement vérifiable sur
deux cents noms sans forge, et ce qui permet de MONTRER le plan avant de
créer quoi que ce soit.

TROIS PIÈGES, ET CHACUN COÛTE CHER DANS UN SENS DIFFÉRENT.

LE SUFFIXE « .git ». Le manifeste écrit « account-analytic.git » là où la
forge nomme « account-analytic ». Ne pas le retirer fait paraître TOUS les
dépôts manquants, et crée deux cents doublons portant « .git » dans leur
nom. Le retirer avec `rstrip` est pire encore : `rstrip` enlève un ENSEMBLE
de caractères et non un suffixe, si bien que « digit.git » devient « d » et
« tigit.git » la chaîne vide. Seul `removesuffix` fait ce qu'on croit.

LA CASSE. Une forge Gitea ou Forgejo tient l'unicité d'un nom de dépôt sans
égard à la casse : « Server-Tools » et « server-tools » ne peuvent pas
coexister. Comparer en respectant la casse ferait paraître manquant un dépôt
présent, et sa création échouerait en 409 sur toute une liste.

LES COLLISIONS. Deux entrées de manifeste dont le nom se réduit au même nom
de forge ne peuvent pas y coexister. Créer la première et taire la seconde
laisserait un miroir silencieusement incomplet, alors le plan les NOMME et
l'appelant décide.
"""
from __future__ import annotations

from typing import NamedTuple


class Plan(NamedTuple):
    """L'écart entre le manifeste et la forge, sans rien avoir changé.

    `to_create` porte les noms de FORGE à créer, dans l'ordre du manifeste :
    un plan qu'on relit doit se lire dans l'ordre où on l'a écrit.

    `already` porte ceux qui sont déjà là — utile pour dire « 198 sur 200 »
    plutôt que « 2 », qui ne dit pas si le reste va bien ou n'a pas été vu.

    `collisions` est un dictionnaire {nom de forge: [noms de manifeste]} pour
    les seuls noms que plus d'une entrée revendique.
    """

    to_create: tuple
    already: tuple
    collisions: dict


def forge_name(manifest_name: str) -> str:
    """Le nom que ce projet de manifeste porte sur la forge.

    Le dernier segment du chemin, sans son « .git » final. Un nom qui
    contient un point sans finir par « .git » — « whisper.cpp » — est rendu
    tel quel : c'est son nom.
    """
    dernier = (manifest_name or "").strip().rstrip("/").rsplit("/", 1)[-1]
    return dernier.removesuffix(".git")


def _clef(nom: str) -> str:
    """Ce sur quoi deux noms sont LE MÊME nom pour la forge."""
    return forge_name(nom).lower()


def plan(declared, present) -> Plan:
    """Le plan de rapprochement. Ne touche à rien.

    `declared` est la liste des noms du manifeste, `present` celle des noms
    que la forge porte — soit son « name », soit son « full_name » : les deux
    se réduisent au même nom de forge, donc l'appelant n'a pas à choisir.

    Un nom vide est IGNORÉ plutôt que créé : un manifeste peut porter une
    entrée sans nom, et « créer un dépôt sans nom » n'a pas de sens.
    """
    deja = {_clef(nom) for nom in (present or []) if _clef(nom)}

    # Les noms DISTINCTS qui revendiquent une même clé. Le même projet
    # listé deux fois — ce que donnent deux manifestes fusionnés — n'est pas
    # un conflit de nommage : le signaler ferait crier au loup à chaque
    # fusion, et un avertissement qui se lève toujours ne se lit plus.
    revendique: dict = {}
    for nom in declared or []:
        clef = _clef(nom)
        if not clef:
            continue
        connus = revendique.setdefault(clef, [])
        if nom not in connus:
            connus.append(nom)

    collisions = {
        forge_name(noms[0]): list(noms)
        for noms in revendique.values()
        if len(noms) > 1
    }

    a_creer, presents = [], []
    vus = set()
    for nom in declared or []:
        clef = _clef(nom)
        if not clef or clef in vus:
            continue
        vus.add(clef)
        (presents if clef in deja else a_creer).append(forge_name(nom))
    return Plan(tuple(a_creer), tuple(presents), collisions)
