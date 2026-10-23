#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Exécution › Dolibarr : installer, lancer, arrêter, suivre.

Le menu choisit l'instance et lance script/dolibarr/run.py avec elle. Ce qui
se garde :
- chaque entrée affichée a sa branche, au bon numéro (MenuCoherence) ;
- une seule instance de développement est prise d'office, plusieurs se
  choisissent, aucune se dit ;
- l'état se demande pour toutes les instances, sans choix préalable.
"""

import builtins
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

import test_todo_menu as menus  # noqa: E402

from script.todo import dolibarr_menu  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RUN = "./.venv.erplibre/bin/python -u script/dolibarr/run.py"


class TestDolibarrMenuNumbering(menus.MenuCoherence, unittest.TestCase):
    SOURCE = RACINE / "script" / "todo" / "dolibarr_menu.py"
    ENTRY = "def prompt_execute_dolibarr(self):"
    END = "def _dolibarr_run(self, action):"
    MINIMUM = 4
    EXPECTED = {
        "Dolibarr - Install an instance": "prompt_install_dolibarr",
        "Dolibarr - Start an instance": "_dolibarr_run",
        "Dolibarr - Stop an instance": "_dolibarr_run",
        "Dolibarr - Instance status": "_dolibarr_run",
        "Dolibarr - Instance logs": "_dolibarr_run",
    }


class Banc(unittest.TestCase):
    def setUp(self):
        self.registre = {}
        p = mock.patch.object(
            dolibarr_menu.lib_dolibarr,
            "load_registry",
            lambda root: self.registre,
        )
        p.start()
        self.addCleanup(p.stop)

    def lancer(self, action, reponses=()):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)

        def repondre(prompt=""):
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question imprévue : {prompt!r}"
                ) from None

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            contextlib.redirect_stdout(sortie),
        ):
            todo._dolibarr_run(action)
        return lances, sortie.getvalue()


DEV = {"mode": "dev", "runtime": "native", "url": "http://127.0.0.1:8080"}


class TestChoixDeLInstance(Banc):
    def test_a_single_instance_is_taken_without_asking(self):
        self.registre = {"erp": dict(DEV)}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [f"{RUN} start --instance erp"])

    def test_several_instances_are_chosen_by_number(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("stop", reponses=["2"])
        self.assertEqual(lances, [f"{RUN} stop --instance zzz"])

    def test_back_at_the_choice_runs_nothing(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("logs", reponses=["0"])
        self.assertEqual(lances, [])

    def test_no_instance_says_so(self):
        lances, sortie = self.lancer("start")
        self.assertEqual(lances, [])
        self.assertIn(
            dolibarr_menu.t("No development Dolibarr instance."), sortie
        )

    def test_production_instances_are_not_offered_here(self):
        self.registre = {"erp": dict(DEV, mode="prod")}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [])

    def test_status_covers_every_instance_without_asking(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("status")
        self.assertEqual(lances, [f"{RUN} status"])


class TestExecuteMenu(unittest.TestCase):
    def test_the_execute_menu_leads_to_dolibarr(self):
        self.assertEqual(
            menus.TestExecuteMenuNumbering.EXPECTED.get("Dolibarr"),
            "prompt_execute_dolibarr",
        )
        self.assertEqual(
            TODO._MENU_LABELS.get("prompt_execute_dolibarr"), "Dolibarr"
        )


if __name__ == "__main__":
    unittest.main()
