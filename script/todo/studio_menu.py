#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre studio : les scénarios du générateur de code.

Chaque scénario de `script/test/config_testcase.odoo<V>.json` génère des
modules Odoo, les installe sur une base qu'il crée, puis contrôle le code
produit. Ce menu les lance par `script/test/run_odoo_scenarios.sh`, le même
moteur que la suite unitaire : délai, Ctrl+C qui démonte, tableau `--tui`.

Le tableau a besoin du terminal, et un Ctrl+C doit laisser le lanceur
supprimer les bases du passage : la commande hérite donc du terminal et
le menu l'attend jusqu'au bout.
"""

import os

import click

from script.todo import todo_journal
from script.todo.todo_i18n import t

# Le lanceur des scénarios, relatif à la racine du dépôt.
STUDIO_LANCEUR = "./script/test/run_odoo_scenarios.sh"


class StudioMenuMixin:
    def prompt_execute_studio(self):
        print(f"🏗  {t('ERPLibre studio: code generator scenarios.')}")
        choices = [
            {"prompt_description": t("All scenarios")},
            {"prompt_description": t("One scenario")},
            {"prompt_description": t("Failed scenarios of the last run")},
            {
                "prompt_description": t(
                    "All scenarios, with Odoo module coverage"
                )
            },
            {
                "prompt_description": t(
                    "Drop databases left by an interrupted run"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._studio_run()
            elif status == "2":
                nom = self._studio_choose_scenario()
                if nom:
                    self._studio_run(f"--scenario={nom}")
            elif status == "3":
                self._studio_run("--failed")
            elif status == "4":
                self._studio_run_coverage()
            elif status == "5":
                # Sans --tui : la purge liste les bases et demande avant
                # de supprimer, ce qu'elle fait au terminal.
                self._studio_run("--purge", tableau=False)
            else:
                print(t("Command not found !"))

    @staticmethod
    def _studio_scenarios():
        """Les noms des scénarios de la version Odoo active, dans l'ordre
        du fichier ; [] et un message quand il manque ou est invalide."""
        from script.test import scenarios_odoo

        racine = os.getcwd()
        try:
            version = scenarios_odoo.lire_version(racine)
            chemin = scenarios_odoo.json_par_defaut(racine, version)
            with open(chemin, encoding="utf-8") as fh:
                entrees = scenarios_odoo.charger_et_valider(fh.read())
        except (OSError, scenarios_odoo.SchemaInvalide) as exc:
            print(f"❌ {t('Scenarios unreadable:')} {exc}")
            return []
        return [e["test_name"] for e in entrees]

    def _studio_choose_scenario(self):
        """Le nom du scénario choisi par son numéro, ou None."""
        noms = self._studio_scenarios()
        if not noms:
            return None
        for i, nom in enumerate(noms, 1):
            print(f"  [{i}] {nom}")
        choix = input(t("Scenario number (empty to cancel): ")).strip()
        if not choix:
            return None
        if not choix.isdigit() or not 1 <= int(choix) <= len(noms):
            print(t("Command not found !"))
            return None
        return noms[int(choix) - 1]

    def _studio_run_coverage(self):
        """Tous les scénarios mesurés, jeu « odoo » de couverture.py.

        Test › ERPLibre studio et Développement › Couverture passent tous
        deux par ici : une seule commande pour une seule suite. Rend le code
        du lanceur, ou None quand il manque."""
        code = self._studio_run("--coverage")
        if code is not None:
            print(f"   {t('HTML report:')} make open_test_coverage JEU=odoo")
        return code

    def _studio_run(self, *args, tableau=True):
        """Lance le lanceur des scénarios au terminal, jusqu'au bout.

        Rend son code de retour, ou None quand le lanceur manque au
        checkout."""
        if not os.path.exists(STUDIO_LANCEUR):
            print(
                f"❌ {t('Odoo scenario launcher missing:')} {STUDIO_LANCEUR}"
            )
            return None
        cmd = [STUDIO_LANCEUR] + (["--tui"] if tableau else []) + list(args)
        code = todo_journal.lancer_au_terminal(
            cmd, check=False, jusqu_au_bout=True
        ).returncode
        if code == 0:
            print(f"\n✅ {t('Scenarios done')}")
        else:
            print(f"\n❌ {t('Scenarios failed, exit code')}: {code}")
        return code
