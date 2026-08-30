#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Choisir une copie à réinitialiser dans une LISTE, pas de mémoire.

L'aide affichée après une erreur disait « --reset <key> --apply » et laissait
retrouver la clé dans un diff de mille lignes. On la recopie, on se trompe
d'un caractère, et la commande ne fait RIEN sans le dire — une clé qui ne
correspond à aucune copie n'est pas une erreur pour l'outil.

D'où l'option [3] : elle demande les clés à l'outil, les numérote, et offre
« toutes ». Ces tests portent sur ce que chaque réponse lance.
"""

import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class PromptCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def run_prompt(self, answer, lst_key=None):
        """(commandes lancées, texte affiché) après cette réponse."""
        import contextlib
        import io

        if lst_key is None:
            lst_key = ["website_sale.product", "web.layout", "website_blog.x"]
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        upgrade.stale_cow_keys = lambda db: lst_key
        lst_cmd = []
        upgrade.run_captured = lambda cmd: lst_cmd.append(cmd) or 0
        # Le doublon HONORE le défaut, comme le vrai `ask_gate` : sinon
        # les tests de défaut ne testeraient que le doublon.
        upgrade.ask_gate = lambda prompt, default="": answer or default
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upgrade.prompt_reset_stale_cow_views("db")
        return lst_cmd, out.getvalue()


class TestTheMenu(PromptCase):
    def test_every_key_is_numbered(self):
        # C'est tout l'objet : on ne connaît pas les clés de tête.
        _cmd, text = self.run_prompt("")
        self.assertIn("[1] website_sale.product", text)
        self.assertIn("[2] web.layout", text)
        self.assertIn("[3] website_blog.x", text)

    def test_all_is_offered(self):
        _cmd, text = self.run_prompt("")
        self.assertIn("[a]", text)

    def test_nothing_drifted_asks_nothing(self):
        lst_cmd, text = self.run_prompt("a", lst_key=[])
        self.assertEqual(lst_cmd, [])
        self.assertIn("No COW copy", text)


class TestWhatEachAnswerRuns(PromptCase):
    def test_a_number_resets_that_key(self):
        lst_cmd, _ = self.run_prompt("2")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("--reset web.layout", lst_cmd[0])
        self.assertIn("--apply", lst_cmd[0])
        self.assertNotIn("website_sale", lst_cmd[0])

    def test_several_numbers_reset_several_keys(self):
        lst_cmd, _ = self.run_prompt("1,3")
        self.assertIn("--reset website_sale.product", lst_cmd[0])
        self.assertIn("--reset website_blog.x", lst_cmd[0])
        self.assertNotIn("web.layout", lst_cmd[0])

    def test_a_resets_them_all(self):
        lst_cmd, _ = self.run_prompt("a")
        self.assertIn("--reset all", lst_cmd[0])

    def test_enter_resets_them_all(self):
        # Entrée les prend TOUTES : elles ne sont dans cette liste que
        # parce qu'un enfant n'y trouve plus son ancrage, et l'outil sauve
        # ce que chaque copie portait avant de la réinitialiser.
        lst_cmd, _text = self.run_prompt("")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("--reset all", lst_cmd[0])

    def test_n_resets_nothing(self):
        # Le défaut ne retire pas le choix : il ne fait qu'en proposer un.
        lst_cmd, text = self.run_prompt("n")
        self.assertEqual(lst_cmd, [])
        self.assertIn("Kept", text)

    def test_an_out_of_range_number_resets_nothing(self):
        # Le piège serait de tomber en silence sur « all » ou sur la
        # première clé : on ne devine pas ce qui n'a pas été demandé.
        lst_cmd, text = self.run_prompt("9")
        self.assertEqual(lst_cmd, [])
        self.assertIn("Unknown choice", text)

    def test_garbage_resets_nothing(self):
        lst_cmd, text = self.run_prompt("zzz")
        self.assertEqual(lst_cmd, [])
        self.assertIn("Unknown choice", text)


class TestTheKeysComeFromTheTool(unittest.TestCase):
    """La liste est demandée à l'outil, pas devinée."""

    def test_list_keys_prints_only_keys(self):
        script = os.path.join(
            REPO, "script", "odoo", "migration", "reset_stale_cow_views.py"
        )
        with open(script) as handle:
            source = handle.read()
        self.assertIn("--list-keys", source)
        self.assertIn('print(cow_view["key"])', source)

    def test_a_dead_database_yields_no_key(self):
        # Sans ce garde-fou, un menu vide se lirait comme « rien n'a dérivé ».
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        upgrade.todo_upgrade_execute = lambda cmd, **kw: (2, cmd, [])
        self.assertEqual(upgrade.stale_cow_keys("nope"), [])

    def test_the_error_prompt_offers_it(self):
        import inspect

        # Le menu d'erreur vit dans `_prompt_on_error`, extrait de
        # `todo_upgrade_execute` quand celui-ci a passé le seuil de
        # complexité. Lire les deux : c'est le CHEMIN d'erreur qu'on
        # éprouve, pas une méthode en particulier.
        source = inspect.getsource(
            TodoUpgrade.todo_upgrade_execute
        ) + inspect.getsource(TodoUpgrade._prompt_on_error)
        self.assertIn("prompt_reset_stale_cow_views", source)
        self.assertIn("Reset one of them onto its module view", source)


class TestTheToolAcceptsWhatWeSend(unittest.TestCase):
    def test_reset_can_be_repeated_and_accepts_all(self):
        done = subprocess.run(
            [
                sys.executable,
                "./script/odoo/migration/reset_stale_cow_views.py",
                "--help",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        self.assertEqual(done.returncode, 0)
        self.assertIn("--list-keys", done.stdout)
        self.assertIn("--reset", done.stdout)


if __name__ == "__main__":
    unittest.main()
