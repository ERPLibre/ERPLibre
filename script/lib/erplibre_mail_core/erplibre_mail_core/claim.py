#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La revendication d'un message sur le serveur IMAP, avant un envoi
automatique.

Plusieurs machines peuvent porter les mêmes règles sur un même compte.
Avant de répondre, de transférer ou de rediriger, une passe POSE le
mot-clé `CLAIM_KEYWORD` sur le message d'origine ; une machine qui le
trouve déjà posé s'abstient. Le serveur est le seul état que toutes
partagent.

Un seul mot-clé pour toutes les règles : il dit « ce message a déjà sa
réponse automatique », et non laquelle. Il ne porte pas l'identité de la
machine qui l'a posé ; chacune reconnaît SA revendication dans sa propre
base.

Le module n'importe rien : le transport, la base, le moteur et l'interface
de l'appelant le lisent tous, et un import ici créerait un cycle entre eux.
"""

from __future__ import annotations

from dataclasses import dataclass

# Le mot-clé IMAP que pose une machine avant tout envoi automatique en
# réponse à un message ; un seul pour toutes les règles.
CLAIM_KEYWORD = "$ErpLibreRule"
# Les modes de revendication d'un serveur : STORE conditionnel (CONDSTORE),
# STORE simple puis relecture, ou aucune revendication possible.
CLAIM_MODES = ("atomic", "plain", "none")
# Les issues d'une sonde (`claim_probe`).
PROBE_STATUSES = ("free", "present", "gone", "renumbered", "unsupported")
# Les issues d'un STORE de revendication (`claim_store`) ; `retry` : le
# STORE n'a pas été appliqué (BAD d'une syntaxe CONDSTORE), à relire ;
# `unknown` : le STORE est accepté mais sa relecture est refusée, le
# mot-clé est peut-être posé.
STORE_RESULTS = ("stored", "modified", "refused", "gone", "retry", "unknown")


@dataclass(frozen=True)
class ClaimProbe:
    """Ce qu'une sonde a lu d'un message avant de le revendiquer.

    `status` est l'un de `PROBE_STATUSES`, `mode` l'un de `CLAIM_MODES`.
    `modseq` est le MODSEQ de la ligne FETCH lue, en mode `atomic`
    seulement : le STORE conditionnel le reprend tel quel. `reason` vaut
    `keywords` pour `unsupported` (PERMANENTFLAGS sans mot-clé admis).
    """

    status: str
    mode: str
    modseq: int | None = None
    reason: str = ""


def _jetons(flags) -> list[str]:
    """Les jetons non vides d'une chaîne de drapeaux, ou d'une suite."""
    if not flags:
        return []
    if isinstance(flags, str):
        return flags.split()
    return [str(f) for f in flags if str(f).strip()]


def has_claim(flags) -> bool:
    """Vrai si un JETON de `flags` est le mot-clé, casse ignorée.

    `flags` est une chaîne de drapeaux séparés par des blancs (forme de
    `HeaderInfo.flags` et de `messages.flags`), une suite de drapeaux, ou
    None. Un jeton qui ne fait que commencer par le mot-clé ne compte pas.
    """
    cible = CLAIM_KEYWORD.lower()
    return any(j.lower() == cible for j in _jetons(flags))


def without_claim(flags) -> list[str]:
    """Les jetons non vides de `flags`, dans l'ordre, moins le mot-clé."""
    cible = CLAIM_KEYWORD.lower()
    return [j for j in _jetons(flags) if j.lower() != cible]
