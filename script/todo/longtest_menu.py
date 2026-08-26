#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests LONGS : de vraies machines, des heures.

Ils vivent dans `LongTest/` et non dans `test/`, et ce n'est pas un rangement
de confort : le lanceur unitaire balaie `test/test_*.py` et doit rester
lançable en quelques secondes, partout. Un test qui crée dix VM n'a rien à y
faire — il le ferait échouer sur toute machine sans virtualisation, et
personne ne l'attendrait.

Ce menu ne fait que les lancer, en montrant leur sortie en direct : ces
scripts durent des heures, et une sortie capturée jusqu'à la fin ne dirait
rien pendant tout ce temps.
"""

import os

import click

from script.todo.todo_i18n import t

# Le répertoire des tests longs, à la racine du dépôt.
LONGTEST_DIR = "LongTest"


class LongTestMenuMixin:
    def _longtest_script(self, nom):
        """Chemin d'un test long, ou "" s'il n'est pas là."""
        chemin = os.path.join(os.getcwd(), LONGTEST_DIR, nom)
        return chemin if os.path.exists(chemin) else ""

    def _longtest_run(self, nom, args=""):
        """Lance un test long, sortie en DIRECT.

        En direct parce qu'il dure des heures : capturer sa sortie pour
        l'afficher à la fin, c'est ne rien montrer pendant tout ce temps —
        et c'est justement la progression étage par étage qui intéresse.
        """
        chemin = self._longtest_script(nom)
        if not chemin:
            print(f"  ✗ {t('Script not found:')} {LONGTEST_DIR}/{nom}")
            return
        cmd = f"./.venv.erplibre/bin/python {chemin}"
        if args:
            cmd += f" {args}"
        print(f"\n{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def prompt_execute_longtest(self):
        print(f"⏳ {t('Long tests: real VMs, hours. Not the unit suite.')}")
        choices = [
            {
                "prompt_description": t(
                    "Nested Proxmox depth: plan only (dry-run)"
                )
            },
            {"prompt_description": t("Nested Proxmox depth: run it")},
            {"prompt_description": t("Undo what the descent created")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status == "1":
                self._longtest_run(
                    "deep_proxmox.py",
                    f"--depth {self._longtest_depth()} --dry-run",
                )
            elif status == "2":
                # La profondeur est DEMANDÉE : c'est le seul réglage du test,
                # et il décide de sa durée — dix étages, c'est une nuit.
                self._longtest_run(
                    "deep_proxmox.py", f"--depth {self._longtest_depth()}"
                )
            elif status == "3":
                # Le script demande « OUI » avant de détruire, mais il liste
                # d'abord : on lui fait faire cette liste À BLANC pour que le
                # choix « 3 » d'une touche ne mène pas directement à un
                # « qm destroy --purge ».
                self._longtest_run("deep_proxmox.py", "--detruire --dry-run")
                if self._is_yes(input(f"\n{t('Destroy all that? (y/N): ')}")):
                    self._longtest_run("deep_proxmox.py", "--detruire")
            else:
                print(t("Command not found !"))

    def _longtest_depth(self):
        """Profondeur demandée. Dix par défaut : c'est ce qu'on veut mesurer."""
        brut = input(f"{t('Depth (default 10): ')}").strip()
        return int(brut) if brut.isdigit() and int(brut) > 0 else 10
