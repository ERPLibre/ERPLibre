#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un spec de VM dit de sa posture, et ce que ce couple autorise.

TROIS QUESTIONS, TROIS CHAMPS, ET AUCUN NE SE DÉDUIT DES AUTRES :

    install.prod   OÙ ça s'installe — un chemin système et une unité, ou un
                   dépôt sous un répertoire personnel.
    posture        CE QUE LE RÉSEAU atteint.
    real_data      SI LA MACHINE porte des données réelles.

Les confondre est ce qui produit les deux accidents symétriques : une
maquette de démonstration qui parle à tout l'Internet parce qu'elle n'est
« pas en production », et une machine de production confinée au point de ne
plus pouvoir se mettre à jour. Une épreuve tient leur indépendance.

Ce module lit un spec ; il n'en écrit aucun et n'affiche rien. Le verdict est
un jeton, que l'écran traduit — c'est ce qui permet de l'éprouver sans
terminal, et à deux écrans de le rendre différemment.
"""

from __future__ import annotations

from script.posture.registry import (
    DEFAULT_POSTURE,
    allows_real_data,
    get_posture,
)

# Les clés, nommées ici et nulle part ailleurs : un `spec.get("posture")`
# recopié chez chaque consommateur devient une faute de frappe silencieuse
# le jour où la clé change.
POSTURE_KEY = "posture"
REAL_DATA_KEY = "real_data"

# Le vocabulaire des verdicts, clos.
OK = "ok"
UNKNOWN_POSTURE = "unknown-posture"
REAL_DATA_UNCONFINED = "real-data-unconfined"
SPEC_VERDICTS = (OK, UNKNOWN_POSTURE, REAL_DATA_UNCONFINED)


def posture_name(spec) -> str:
    """Le nom de posture que le spec porte, ou celui par défaut.

    Un spec écrit avant que les postures existent n'en nomme aucune, et doit
    continuer de se déployer comme avant.
    """
    return str((spec or {}).get(POSTURE_KEY) or DEFAULT_POSTURE)


def posture_of(spec):
    """La posture du spec, ou None si elle nomme une posture inconnue.

    None plutôt qu'un repli silencieux sur la posture par défaut : replier
    ferait déployer en sortie libre un spec qui demandait du confinement, ce
    qui est exactement le sens inverse de la demande.
    """
    return get_posture(posture_name(spec))


def real_data(spec) -> bool:
    """La machine porte-t-elle des données réelles ?

    Faux par défaut. L'inverse ferait d'un spec incomplet une machine qu'on
    croit protégée, et le doute doit pencher du côté qui ne promet rien.
    """
    return bool((spec or {}).get(REAL_DATA_KEY))


def check(spec) -> str:
    """Le verdict du couple (posture, données réelles). Ne lève pas.

    C'est la règle d'or au point où elle se décide : un spec, et la réponse
    « ce déploiement est-il cohérent ». Le refus arrive AVANT que la machine
    existe, ce qui est le seul moment où il coûte quelque chose de nul.
    """
    posture = posture_of(spec)
    if posture is None:
        return UNKNOWN_POSTURE
    if real_data(spec) and not allows_real_data(posture):
        return REAL_DATA_UNCONFINED
    return OK
