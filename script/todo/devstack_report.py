#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un seul vocabulaire pour dire ce qu'un verbe a fait, et où.

Quatre besoins convergent ici, et les tenir séparés les fait diverger : le
CODE qu'un verbe rend, la CAPACITÉ que l'hôte a ou n'a pas, le VERDICT par
couche d'une vérification qui en traverse plusieurs, et la façon de les
écrire. Le dépôt porte déjà trois manières d'aligner un verdict ; celle-ci
généralise la plus ancienne, dont la largeur de colonne est déjà épinglée
par un test.

Quatre invariants tiennent ce module :

1. C'est une BIBLIOTHÈQUE. Elle n'ajuste aucun `sys.path` et ne s'exécute
   pas. Son jeu d'imports est clos à la bibliothèque standard et à la table
   de traduction, pour qu'un module pur d'une autre famille puisse la
   consommer sans traîner de dépendance tierce.
2. Les rendeurs RENDENT une chaîne, ils n'impriment pas. Un bloc rendu se
   compose ; un bloc imprimé ne se compose pas.
3. Le diagnostic part sur stderr, jamais sur stdout. C'est ce qui laisse
   tuber et asserter la sortie utile d'un essai à blanc.
4. `why` et `remedy` arrivent DÉJÀ traduits et formatés — plusieurs motifs
   portent un paramètre. Les rendeurs ne les retraduisent pas : chercher une
   chaîne française comme clé anglaise la rendrait telle quelle, ou pire.

Une COUCHE nomme l'ENDROIT où la vérification a eu lieu, pas le sujet
vérifié : une sauvegarde est un sujet, sa couche est « data ».
"""

from __future__ import annotations

import sys
from typing import NamedTuple, Sequence, TextIO

from script.todo.todo_i18n import t

# Le protocole de sortie. Un verbe rend l'un de ces cinq, et rien d'autre.
DS_OK = 0  # Le verbe a fait ce qu'il annonce, en entier.
DS_ERR = 1  # La commande, la machine ou la donnée n'a pas suivi.
DS_REFUSED = 10  # Une politique ou l'opérateur refuse ; rien n'a été tenté.
DS_SKIP = 20  # Une dépendance manque : retrait propre, et non un échec.
DS_UNIMPLEMENTED = 21  # Ce backend n'implémente pas ce verbe, et ne le fera
# pas. Presque mort dans un dépôt qui ne vise qu'un système ; le numéro est
# réservé pour que personne ne le réattribue à autre chose.

CODES = (DS_OK, DS_ERR, DS_REFUSED, DS_SKIP, DS_UNIMPLEMENTED)

# Une cellule par marque. Un glyphe de présentation émoji en occupe DEUX et
# décale toute la colonne qui suit ; la largeur ci-dessous ne suffit alors
# plus à aligner quoi que ce soit.
MARKS = {
    DS_OK: "✓",
    DS_ERR: "✗",
    DS_REFUSED: "!",
    DS_SKIP: "-",
    DS_UNIMPLEMENTED: "?",
}

# Jetons stables et NON traduits : c'est la seule forme de code qu'une sortie
# lisible par une machine peut porter, puisqu'elle ne dépend pas de la langue.
_TOKENS = {
    DS_OK: "ok",
    DS_ERR: "err",
    DS_REFUSED: "refused",
    DS_SKIP: "skip",
    DS_UNIMPLEMENTED: "unimplemented",
}

# L'ordre total de gravité : une panne domine un refus, qui domine une
# absence. C'est ce qui permet de réduire plusieurs verdicts à un seul code
# sans avoir à trancher au cas par cas chez l'appelant.
_SEVERITY = {
    DS_OK: 0,
    DS_SKIP: 1,
    DS_UNIMPLEMENTED: 2,
    DS_REFUSED: 3,
    DS_ERR: 4,
}

# Les endroits où un verdict se prend, de l'hôte vers la donnée. Les jetons
# se rendent BRUTS : les traduire les ferait entrer en collision avec des
# clés existantes, dont une porte un émoji qui casserait l'alignement.
LAYERS = (
    "host",
    "network",
    "dns",
    "transport",
    "firewall",
    "guest",
    "tls",
    "service",
    "data",
)

# La géométrie de la colonne, reprise de l'idiome le plus ancien du dépôt et
# déjà épinglée par un test de pilote VPN. Un seul endroit la décide, sinon
# deux listes voisines cessent de s'aligner entre elles.
LABEL_WIDTH = 34


class Capability(NamedTuple):
    """Une capacité de l'hôte : ce qu'elle est, si elle répond, et le remède.

    `why` explique une ABSENCE en clair ; `remedy` est le geste qui la lève,
    ou une chaîne vide quand il n'y en a pas. Les deux arrivent traduits.
    """

    name: str
    present: bool
    why: str = ""
    remedy: str = ""


class LayerVerdict(NamedTuple):
    """Ce qu'UNE couche rend, pour qu'un rapport puisse dire laquelle a tenu.

    Agréger plusieurs couches en un seul code perd l'information la plus
    utile : « le pare-feu de l'invité a tenu, c'est le réseau qui a cédé »
    ne se déduit pas d'un unique entier.
    """

    layer: str
    code: int
    detail: str = ""
    remedy: str = ""


def layer_verdict(
    layer: str, code: int, detail: str = "", remedy: str = ""
) -> LayerVerdict:
    """Construit un verdict, en refusant une couche hors vocabulaire.

    Le refus tombe au point d'ÉCRITURE, où le nom fautif est visible, plutôt
    qu'au rendu, où il ne serait qu'une ligne de plus qui ne s'aligne pas.
    """
    if layer not in LAYERS:
        raise ValueError(
            f"couche inconnue : {layer!r} — attendu {', '.join(LAYERS)}"
        )
    if code not in CODES:
        raise ValueError(f"code hors vocabulaire : {code!r}")
    return LayerVerdict(layer, code, detail, remedy)


def code_token(code: int) -> str:
    """Le jeton non traduit d'un code, pour une sortie lisible par machine."""
    return _TOKENS.get(code, "unexpected")


def worst_code(codes: Sequence[int]) -> int:
    """Le pire code de la suite, selon la gravité.

    Une suite VIDE rend DS_SKIP et non DS_OK : une vérification qui n'a rien
    sondé n'a rien prouvé, et l'annoncer comme un succès est le mensonge que
    ce module existe pour empêcher. Un code hors vocabulaire compte pour une
    panne — le rendre tel quel ferait entrer un sixième code par la bande.
    """
    if not codes:
        return DS_SKIP
    pire = DS_OK
    for code in codes:
        if code not in _SEVERITY:
            return DS_ERR
        if _SEVERITY[code] > _SEVERITY[pire]:
            pire = code
    return pire


def aggregate_layers(verdicts: Sequence[LayerVerdict]) -> int:
    """Réduit des verdicts par couche à un seul code, par la règle du pire."""
    return worst_code([verdict.code for verdict in verdicts])


def report(code: int) -> str:
    """La ligne humaine d'un code : sa marque, puis son verdict traduit."""
    if code not in _TOKENS:
        return f"{MARKS.get(code, '?')} {t('Unexpected exit code')} : {code}"
    verdicts = {
        DS_OK: "Done",
        DS_ERR: "Failed",
        DS_REFUSED: "Refused",
        DS_SKIP: "Dependency absent - skipped",
        DS_UNIMPLEMENTED: "Not implemented by this backend",
    }
    return f"{MARKS[code]} {t(verdicts[code])}"


def _line(mark: str, label: str, detail: str) -> str:
    """Une ligne de verdict, en colonnes, RENDUE et non imprimée."""
    return f"  {mark} {label:<{LABEL_WIDTH}} {detail}"


def _section(title: str, lines: Sequence[str]) -> str:
    """Un bloc « ── titre ── » et ses lignes, sans saut de ligne aux bords."""
    return "\n".join([f"── {title} ──"] + list(lines))


def render_capabilities(caps: Sequence[Capability]) -> str:
    """Le bloc des capacités : une ligne chacune, son remède en dessous.

    Une liste VIDE le dit, au lieu de rendre un bloc muet qu'on lirait comme
    « tout va bien ».
    """
    if not caps:
        return _section(
            t("Capabilities"), [_line("-", t("Nothing was probed"), "")]
        )
    lignes = []
    for cap in caps:
        marque = MARKS[DS_OK] if cap.present else MARKS[DS_SKIP]
        etat = t("present") if cap.present else t("absent")
        detail = f"{etat}{'  ' + cap.why if cap.why else ''}"
        lignes.append(_line(marque, cap.name, detail))
        if not cap.present and cap.remedy:
            lignes.append(_line(" ", "", f"{t('To install:')} {cap.remedy}"))
    return _section(t("Capabilities"), lignes)


def diag(text: str, stream: TextIO | None = None) -> None:
    """Écrit un diagnostic sur stderr.

    Le flux se résout à L'APPEL et non à l'import : autrement une redirection
    posée par un test ne serait jamais vue, et le contrat de flux deviendrait
    invérifiable.
    """
    print(text, file=stream if stream is not None else sys.stderr)
