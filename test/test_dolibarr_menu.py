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
    MINIMUM = 5
    EXPECTED = {
        "Dolibarr - Install an instance": "prompt_install_dolibarr",
        "Dolibarr - Start an instance": "_dolibarr_run",
        "Dolibarr - Stop an instance": "_dolibarr_run",
        "Dolibarr - Instance status": "_dolibarr_run",
        "Dolibarr - Instance logs": "_dolibarr_run",
        "Dolibarr - Update the pinned commit": "_dolibarr_pin",
        "Dolibarr - Health, security and integrity": "_dolibarr_doctor",
        "Dolibarr - Find installations (local or SSH)": "_dolibarr_detect",
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

    def test_a_development_container_instance_is_offered_too(self):
        # run.py la pilote par son moteur.
        self.registre = {"ctr": dict(DEV, runtime="container")}
        lances, _s = self.lancer("start")
        self.assertEqual(lances, [f"{RUN} start --instance ctr"])

    def test_status_covers_every_instance_without_asking(self):
        self.registre = {"aaa": dict(DEV), "zzz": dict(DEV)}
        lances, _s = self.lancer("status")
        self.assertEqual(lances, [f"{RUN} status"])


DETECT = "./.venv.erplibre/bin/python -u script/dolibarr/detect.py"
DOCTOR = "./.venv.erplibre/bin/python -u script/dolibarr/doctor.py"


class TestBilan(unittest.TestCase):
    def test_every_instance_is_checked_at_once(self):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 1

        todo.execute = Execute()
        with contextlib.redirect_stdout(io.StringIO()):
            todo._dolibarr_doctor()
        self.assertEqual(lances, [f"{DOCTOR} --all"])


class TestDetection(unittest.TestCase):
    def lancer(self, alias, reponses):
        todo = TODO.__new__(TODO)
        lances = []

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return 0

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(
                TODO, "_ssh_config_hosts", staticmethod(lambda: list(alias))
            ),
            mock.patch.object(builtins, "input", lambda p="": next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_detect()
        return lances

    def test_this_machine(self):
        self.assertEqual(self.lancer([], ["1"]), [f"{DETECT} --local"])

    def test_one_host_of_the_ssh_config(self):
        lances = self.lancer(["hote-a", "hote-b"], ["4"])
        self.assertEqual(lances, [f"{DETECT} --ssh hote-b"])

    def test_every_host_of_the_ssh_config(self):
        lances = self.lancer(["hote-a", "hote-b"], ["2"])
        self.assertEqual(lances, [f"{DETECT} --ssh hote-a --ssh hote-b"])

    def test_an_alias_is_quoted_for_the_shell(self):
        lances = self.lancer(["a b"], ["3"])
        self.assertEqual(lances, [f"{DETECT} --ssh 'a b'"])

    def test_back_runs_nothing(self):
        self.assertEqual(self.lancer(["hote-a"], ["0"]), [])


PIN = "./.venv.erplibre/bin/python -u script/dolibarr/pin.py"
SYNC = "./script/manifest/update_manifest_local_dolibarr.sh"


class TestEpinglage(unittest.TestCase):
    def lancer(self, codes, reponses):
        todo = TODO.__new__(TODO)
        lances = []
        suite_codes = iter(codes)

        class Execute:
            def exec_command_live(inner, cmd, **kwargs):
                lances.append(cmd)
                return next(suite_codes)

        todo.execute = Execute()
        suite = iter(reponses)
        with (
            mock.patch.object(builtins, "input", lambda *a: next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo._dolibarr_pin()
        return lances

    def test_the_menu_and_pin_py_agree_on_the_pending_code(self):
        from script.dolibarr import pin

        self.assertEqual(dolibarr_menu.PIN_PENDING, pin.PENDING)

    def test_nothing_pending_asks_nothing(self):
        self.assertEqual(self.lancer([0], []), [f"{PIN} update"])

    def test_pending_changes_apply_then_sync_on_yes(self):
        self.assertEqual(
            self.lancer([3, 0, 0], ["y", "y"]),
            [f"{PIN} update", f"{PIN} update --apply", SYNC],
        )

    def test_no_writes_nothing(self):
        self.assertEqual(self.lancer([3], ["n"]), [f"{PIN} update"])

    def test_a_failed_apply_does_not_sync(self):
        self.assertEqual(
            self.lancer([3, 1], ["y"]),
            [f"{PIN} update", f"{PIN} update --apply"],
        )


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
