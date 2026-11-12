#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La section Statistique du menu Analyse module : l'évolution des modules
par année, lancée seulement après confirmation, car elle clone chaque dépôt
amont des manifestes.

La commande n'est jamais exécutée : `execute` et la confirmation sont
remplacés.
"""

import ast
import inspect
import sys
import textwrap
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import module_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


class TestLaStatistique(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def todo(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo.execute = mock.Mock()
        todo.execute.exec_command_live.return_value = 0
        return todo

    def menu(self, saisies, confirme=True):
        todo = self.todo()
        with (
            mock.patch("click.prompt", side_effect=saisies) as prompt,
            mock.patch("click.confirm", return_value=confirme),
            mock.patch("builtins.print"),
        ):
            todo.prompt_execute_module_analysis()
        appels = [
            c.args[0] for c in todo.execute.exec_command_live.call_args_list
        ]
        return prompt.call_args_list[0].args[0], appels

    def test_the_menu_shows_a_statistic_section(self):
        texte, _ = self.menu(["0"])
        self.assertIn("── Statistique ──", texte)
        self.assertIn("[3]", texte)
        self.assertIn("[4]", texte)

    def test_entry_3_runs_every_repository(self):
        _, appels = self.menu(["3", "0"])
        self.assertEqual(len(appels), 1)
        self.assertIn("script/statistic/show_evolution_module.py", appels[0])
        self.assertIn("--before_date 2016-01-01 --more_year 7", appels[0])
        self.assertNotIn("--filter", appels[0])

    def test_entry_4_keeps_oca_only(self):
        _, appels = self.menu(["4", "0"])
        self.assertTrue(appels[0].endswith("--filter /OCA/"))

    def test_nothing_runs_without_confirmation(self):
        _, appels = self.menu(["3", "4", "0"], confirme=False)
        self.assertEqual(appels, [])

    def test_every_message_is_translated(self):
        cles = []
        for methode in (
            module_menu.ModuleMenuMixin.prompt_execute_module_analysis,
            module_menu.ModuleMenuMixin._module_statistique,
        ):
            arbre = ast.parse(textwrap.dedent(inspect.getsource(methode)))
            cles += [
                n.args[0].value
                for n in ast.walk(arbre)
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "t"
                and isinstance(n.args[0], ast.Constant)
            ]
        for cle in cles:
            self.assertIn(cle, todo_i18n.TRANSLATIONS, cle)


if __name__ == "__main__":
    unittest.main()
