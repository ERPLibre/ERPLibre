#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le docteur de l'hôte : ce qu'il montre, et ce qu'il ne casse pas.

C'est la première entrée du menu Devstack et elle est en LECTURE SEULE. Deux
promesses la tiennent : une capacité absente est un avertissement et le
rapport continue jusqu'au bout, et une sonde qui lève nomme la panne au lieu
de remonter une trace au milieu d'un menu.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo import devstack_report as R  # noqa: E402
from script.todo import host_os as H  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class DocteurCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "fr"
        self.todo = TODO()

    def _docteur(self):
        """Rend (code, texte affiché)."""
        vu = io.StringIO()
        with redirect_stdout(vu):
            code = self.todo._devstack_doctor()
        return code, vu.getvalue()


class TestLeDocteurRapporte(DocteurCase):
    def test_it_names_the_host_and_the_architecture(self):
        _, vu = self._docteur()
        self.assertIn(H.host_os(), vu)
        self.assertIn(H.arch_token(), vu)

    def test_it_lists_every_capability(self):
        _, vu = self._docteur()
        noms = [cap.name for cap in H.capabilities()]
        self.assertTrue(noms, "aucune capacité : rien n'est prouvé")
        for nom in noms:
            self.assertIn(nom, vu)

    def test_an_absent_capability_is_a_warning_and_the_report_goes_on(self):
        """Un docteur qui s'arrête au premier manque n'en est pas un."""
        absente = R.Capability("outil-absent", False, "", "poser l'outil")
        presente = R.Capability("outil-present", True, "", "")
        with patch.object(H, "capabilities", return_value=[absente, presente]):
            code, vu = self._docteur()
        self.assertEqual(R.DS_OK, code)
        self.assertIn("outil-absent", vu)
        self.assertIn("outil-present", vu)
        self.assertIn("poser l'outil", vu)

    def test_a_probe_that_raises_is_named_not_traced(self):
        with patch.object(
            H, "capabilities", side_effect=OSError("socket illisible")
        ):
            code, vu = self._docteur()
        self.assertEqual(R.DS_ERR, code)
        self.assertIn("socket illisible", vu)
        self.assertNotIn("Traceback", vu)

    def test_an_unreadable_configuration_does_not_stop_it(self):
        """Le coffre est une capacité parmi d'autres, pas un prérequis."""
        with patch.object(
            self.todo.config_file,
            "get_config_value",
            side_effect=TypeError("configuration illisible"),
        ):
            code, vu = self._docteur()
        self.assertEqual(R.DS_OK, code)
        self.assertIn("kdbx", vu)

    def test_it_changes_nothing(self):
        """En lecture seule : aucune écriture, aucun sous-processus."""
        with patch(
            "subprocess.run",
            side_effect=AssertionError("le docteur ne lance rien"),
        ), patch(
            "subprocess.Popen",
            side_effect=AssertionError("le docteur ne lance rien"),
        ):
            code, _ = self._docteur()
        self.assertEqual(R.DS_OK, code)


class TestLeMenuDevstack(unittest.TestCase):
    """Il n'affiche que ce qui existe."""

    def setUp(self):
        sys.argv = ["todo.py"]
        self.todo = TODO()

    def test_the_entry_declares_its_method_and_not_a_number(self):
        """La forme dont le rang ne dépend pas de ce qui est greffé plus
        haut : c'est la seule qui reste juste quand le menu s'allonge."""
        chemin = os.path.join(RACINE, "script", "todo", "devstack_menu.py")
        with io.open(chemin, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"method": "_devstack_doctor"', source)
        self.assertNotIn('elif status == "1"', source)

    def test_the_menu_reaches_the_doctor(self):
        joues = []
        self.todo._devstack_doctor = lambda: joues.append("docteur")
        with patch("click.prompt", side_effect=["1", "0"]), redirect_stdout(
            io.StringIO()
        ):
            self.assertFalse(self.todo.prompt_execute_devstack())
        self.assertEqual(["docteur"], joues)

    def test_an_unknown_number_says_so_instead_of_acting(self):
        joues = []
        self.todo._devstack_doctor = lambda: joues.append("docteur")
        vu = io.StringIO()
        with patch("click.prompt", side_effect=["9", "0"]), redirect_stdout(
            vu
        ):
            self.todo.prompt_execute_devstack()
        self.assertEqual([], joues)
        self.assertIn(todo_i18n.t("Command not found !"), vu.getvalue())

    def test_the_mixin_is_composed_into_todo(self):
        from script.todo.devstack_menu import DevstackMenuMixin

        self.assertIsInstance(self.todo, DevstackMenuMixin)
        self.assertIn("prompt_execute_devstack", TODO._MENU_LABELS)


if __name__ == "__main__":
    unittest.main()
