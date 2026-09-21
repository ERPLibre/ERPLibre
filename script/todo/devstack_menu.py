#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Devstack : la pile de développement et de test.

Il n'affiche QUE ce qui existe. Poser d'emblée les familles à venir — VM,
IA, secrets, forge, sauvegarde, stockage — donnerait un menu dont chaque
entrée se retire faute d'être écrite, et un menu qui répond « non » partout
n'apprend rien à qui l'ouvre. Les entrées apparaissent à mesure.

Ses entrées se déclarent par « method » et non par un numéro : c'est la
forme dont le rang ne dépend pas de ce que la configuration a greffé plus
haut, donc la seule qui reste juste quand le menu s'allonge.
"""

from __future__ import annotations

import click

from script.todo import host_os
from script.todo.devstack_report import (
    DS_ERR,
    DS_OK,
    render_capabilities,
)
from script.todo.todo_i18n import t


class DevstackMenuMixin:
    """Menu Devstack : le docteur de l'hôte, puis les familles à venir."""

    def prompt_execute_devstack(self):
        """Le menu Devstack. Rend False pour rester dans le menu appelant."""
        choices = [
            {"section": t("Host")},
            {
                "prompt_description": t(
                    "Host doctor - what can this machine do?"
                ),
                "method": "_devstack_doctor",
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

    def _devstack_doctor(self):
        """Le rapport de capacités de l'hôte. Ne modifie rien.

        Une capacité absente est un AVERTISSEMENT et le rapport continue :
        c'est tout l'intérêt d'un docteur que de lister ce qui manque plutôt
        que de s'arrêter au premier manque. Seule une sonde qui LÈVE produit
        une ligne rouge, et cette ligne nomme la panne — un docteur qui
        remonte une trace ne se lit pas.
        """
        print(
            f"{t('Host OS:')} {host_os.host_os()}"
            f"    {t('Architecture:')} {host_os.arch_token()}"
        )
        try:
            chemin_coffre = (
                self.config_file.get_config_value(["kdbx", "path"]) or ""
            )
        except (AttributeError, KeyError, TypeError):
            chemin_coffre = ""
        try:
            capacites = host_os.capabilities(kdbx_path=chemin_coffre)
        except Exception as panne:  # noqa: BLE001 — un docteur ne remonte
            # pas de trace : il nomme ce qui a échoué et rend la main.
            print(f"{t('Probe failed:')} {panne}")
            return DS_ERR
        print(render_capabilities(capacites))
        return DS_OK
