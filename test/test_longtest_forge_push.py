#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long de la forge Forgejo, vu du menu et de son défaire.

Ce qu'ils tiennent, sans VM :
- le menu des tests longs le lance à blanc (15) et pour de vrai (16) ;
- il partage le verrou des autres tests longs et le défaire du menu ;
- « --detruire » refuse tant qu'un test long tourne, sans lire de rapport.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))

import descente  # noqa: E402
import forge_push  # noqa: E402

from script.todo import longtest_menu  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402


class Menu(longtest_menu.LongTestMenuMixin):
    def __init__(self):
        self.lances = []

    def fill_help_info(self, choices):
        return ""

    def _longtest_run(self, nom, args="", demander=None):
        self.lances.append((nom, args))


class TestLeMenu(unittest.TestCase):
    def test_15_plans_and_16_runs(self):
        menu = Menu()
        with (
            mock.patch.object(
                longtest_menu.click, "prompt", side_effect=["15", "16", "0"]
            ),
            mock.patch("builtins.print"),
        ):
            menu.prompt_execute_longtest()
        self.assertEqual(
            menu.lances,
            [("forge_push.py", "--dry-run"), ("forge_push.py", "")],
        )

    def test_it_shares_the_lock_and_the_undo(self):
        self.assertIn("forge_push.py", descente.SCRIPTS)
        self.assertIn("forge_push.py", longtest_menu.SCRIPTS_DEFAISABLES)

    def test_every_label_is_translated(self):
        for cle in (
            "Forgejo forge receives the project: plan only (dry-run)",
            "Forgejo forge receives the project: run it",
        ):
            with self.subTest(cle=cle):
                self.assertTrue(TRANSLATIONS[cle].get("fr"))


class TestLeDefaire(unittest.TestCase):
    def test_a_running_long_test_blocks_the_undo(self):
        with (
            mock.patch.object(
                forge_push, "autre_descente", return_value=[4242]
            ),
            mock.patch.object(forge_push, "dernier_rapport") as rapport,
            mock.patch.object(forge_push, "detruire_etage1") as detruire,
            mock.patch.object(forge_push, "dire"),
        ):
            self.assertEqual(forge_push.detruire(), 1)
        rapport.assert_not_called()
        detruire.assert_not_called()

    def test_nothing_running_reads_the_last_report(self):
        with (
            mock.patch.object(forge_push, "autre_descente", return_value=[]),
            mock.patch.object(
                forge_push, "dernier_rapport", return_value=(None, {})
            ),
            mock.patch.object(forge_push, "detruire_etage1") as detruire,
            mock.patch.object(forge_push, "dire"),
        ):
            self.assertEqual(forge_push.detruire(), 0)
        detruire.assert_not_called()


if __name__ == "__main__":
    unittest.main()
