#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rendu commun des écrans d'état : trois états, une ligne, un compte.

Chaque écran d'état — devstack, Set-OPS — relève ce qui décide et en tire
ses lignes ; il les imprime ICI. Deux rendus diraient tôt ou tard deux
choses différentes avec les mêmes signes : une marque, un compte ou une
colonne qui divergent d'un écran à l'autre se lisent comme un état qui
diverge.

DEUX AXES, ET LES CONFONDRE FAIT MENTIR L'ÉCRAN. « Le dépôt sait le faire »
et « ce site l'a réglé » sont deux questions distinctes : une forge que le
code sait piloter sans profil déclaré n'est pas une forge en service, et le
dire « fait » enverrait chercher une panne là où il n'y a qu'un réglage
absent. D'où trois états et non deux.

Tout y est PUR : ce module ne lit ni fichier ni machine.
"""

from __future__ import annotations

from typing import NamedTuple

from script.todo.todo_i18n import t

# Les trois états, et le vocabulaire est CLOS. « Partiel » n'existe pas :
# il dirait à la fois trop et pas assez, là où « le dépôt sait, ce site n'a
# pas réglé » nomme exactement ce qui manque et qui doit agir.
PORTE = "porte"
A_REGLER = "a-regler"
ABSENT = "absent"
ETATS = (PORTE, A_REGLER, ABSENT)

MARQUES = {PORTE: "✓", A_REGLER: "◐", ABSENT: "○"}


class Ligne(NamedTuple):
    """Un segment, son état, et D'OÙ il le tient.

    `source` n'est pas décoratif : c'est ce qui permet de contredire cet
    écran sans lire ce module. Une ligne dont personne ne peut vérifier
    l'origine est une affirmation de plus.
    """

    segment: str
    etat: str
    detail: str
    source: str


def compte(rendu) -> dict:
    """{état: nombre}, tous les états présents même à zéro.

    Un état absent de la table se lirait « aucun segment dans cet état »
    aussi bien que « cet état n'existe pas » — et l'un est une nouvelle,
    l'autre un défaut de rendu.
    """
    return {etat: sum(1 for l in rendu if l.etat == etat) for etat in ETATS}


def render(rendu) -> list:
    """Les lignes prêtes à imprimer. Fonction PURE."""
    largeur = max(len(l.segment) for l in rendu)
    out = []
    for ligne in rendu:
        out.append(
            f"  {MARQUES[ligne.etat]} {ligne.segment:<{largeur}}"
            f"  {ligne.detail}"
        )
        out.append(f"    {'':<{largeur}}  ↳ {ligne.source}")
    n = compte(rendu)
    out.append("")
    out.append(
        f"  {n[PORTE]} {t('carried')} · {n[A_REGLER]} {t('to set up here')}"
        f" · {n[ABSENT]} {t('not in the repository')}"
    )
    return out
