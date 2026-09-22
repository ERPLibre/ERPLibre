#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Set-OPS : todo pilote le moteur, il ne le recopie pas.

Le moteur Set-OPS reste la seule source de vérité de ses gestes : un geste
s'ajoute ici en LANÇANT le moteur, jamais en recopiant ce qu'il fait. Le
menu n'affiche que ce qui existe — l'écran d'état de l'intégration, en
lecture seule ; les familles de gestes s'y ajoutent par sections.

Ses entrées se déclarent par « method » et non par un numéro : c'est la
forme dont le rang ne dépend pas de ce qui est posé plus haut.
"""

from __future__ import annotations

import os

import click

from script.setops import state
from script.todo import state_screen
from script.todo.todo_i18n import t

# La racine d'ERPLibre, deux niveaux au-dessus de ce fichier : c'est sous
# elle que le relevé lit le manifeste du moteur et le chemin qu'il déclare.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


class SetopsMenuMixin:
    """Menu Set-OPS, mixin de la classe TODO : ses entrées vivent sur la
    même instance que celles des autres menus."""

    def prompt_execute_setops(self):
        """Le menu Set-OPS. Rend False pour rester dans le menu appelant."""
        choices = [
            {"section": t("Integration")},
            {
                "prompt_description": t(
                    "Set-OPS - State of the integration, line by line"
                ),
                "method": "_setops_state",
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif not self._menu_dispatch_extra(choices, status):
                print(t("Command not found !"))

    def _setops_state(self):
        """Les dix lignes de l'intégration de Set-OPS sur ce poste.

        LECTURE SEULE : le relevé de `script.setops.state` ne lance ni
        `make`, ni réseau, et n'écrit rien. Les lignes se décident sur ce
        relevé et s'impriment par le rendu commun des écrans d'état ; chaque
        ligne « à régler ici » nomme le geste qui la règle, et l'écran ne le
        lance pas.
        """
        print(f"\n{t('Set-OPS integration, line by line')}")
        vu = state.releve(RACINE)
        for ligne in state_screen.render(state.lignes(vu)):
            print(ligne)
        print(
            "\n  "
            + t(
                "Each « to set up here » line names the gesture that"
                " settles it; this screen launches nothing."
            )
        )
