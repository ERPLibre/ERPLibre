#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire une copie COW avant d'accepter de la perdre, en plein écran.

Le rapport texte met à mille lignes d'écart les deux choses qui décident :
ce que la copie porte en propre — la seule chose qu'une réinitialisation
abandonne — et quel enfant ne trouve plus son ancrage, qui est la raison
pour laquelle quoi que ce soit casse. L'espace bascule entre les deux.

La commande de réparation prend une CLÉ. La recopier à la main depuis un
diff défilé est l'endroit où un caractère se perd, et une clé sans
correspondance n'est pas une erreur pour l'outil : il tourne et ne fait
rien. D'où « c ».
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))

import reset_stale_cow_tui as tui  # noqa: E402
import reset_stale_cow_views as reset  # noqa: E402


def finding(**override):
    cow = {
        "id": 2841,
        "key": "website_blog.blog_post_complete",
        "website_id": 1,
        "arch": "<t>\n  <div/>\n  <span>vieux</span>\n</t>",
    }
    module = {
        "id": 1826,
        "key": "website_blog.blog_post_complete",
        "website_id": None,
        "arch": "<t>\n  <div/>\n  <section id='o_wblog_post_footer'/>\n</t>",
    }
    broken = [(3288, "//section[@id='o_wblog_post_footer']")]
    if "cow" in override:
        cow.update(override["cow"])
    return cow, override.get("module", module), override.get("broken", broken)


class TestBothScreens(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_the_diff_shows_what_the_copy_holds(self):
        cow, module, _broken = finding()
        text = reset.render_diff(module, cow, indent="  ")
        self.assertIn("vieux", text)
        self.assertIn("o_wblog_post_footer", text)

    def test_the_why_screen_names_the_failing_child(self):
        # Sans lui, on lit un diff sans savoir pourquoi il compte.
        text = tui.render_broken(*finding())
        self.assertIn("3288", text)
        self.assertIn("//section[@id='o_wblog_post_footer']", text)

    def test_the_why_screen_says_what_a_reset_costs(self):
        text = tui.render_broken(*finding())
        self.assertIn("INHERITING", text)

    def test_a_copy_without_broken_child_is_said_so(self):
        # Elle a dérivé sans rien casser ENCORE : le taire ferait croire à
        # une erreur de détection.
        cow, module, _ = finding()
        text = tui.render_broken(cow, module, [])
        self.assertIn("without", text)

    def test_the_two_screens_use_the_same_diff_as_the_cli(self):
        # Deux rendus séparés dériveraient sans que rien ne le signale.
        import inspect

        source = inspect.getsource(tui)
        self.assertIn("from reset_stale_cow_views import", source)
        self.assertIn("render_diff", source)


class TestTheTriageColumn(unittest.TestCase):
    def test_the_weight_counts_both_directions(self):
        cow, module, _ = finding()
        self.assertEqual(tui.weight(cow, module), "+1/-1")

    def test_no_module_twin_has_no_weight(self):
        cow, _module, _ = finding()
        self.assertEqual(tui.weight(cow, None), "—")


class TestTheRefusalIsNeverSilent(unittest.TestCase):
    """Un refus muet ferait réafficher le rapport texte sans le dire."""

    def test_a_pipe_is_explained(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            result = tui.run_tui([finding()], "db")
        self.assertFalse(result)
        self.assertTrue(out.getvalue().strip(), "refus muet")

    def test_nothing_to_show_stays_silent(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(tui.run_tui([], "db"))
        self.assertEqual(out.getvalue(), "")


class TestTheToolAndTheMigrationOfferIt(unittest.TestCase):
    def test_the_tool_has_a_tui_flag(self):
        import subprocess

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
        self.assertIn("--tui", done.stdout)

    def test_the_error_prompt_offers_it_as_option_four(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.todo_upgrade_execute)
        self.assertIn("Browse the differences full screen", source)
        self.assertIn('wait_status == "4"', source)

    def test_it_gets_a_real_terminal(self):
        # Un plein écran lancé par l'exécuteur qui capture retomberait sur
        # le rapport texte, sans que rien ne distingue les deux.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.todo_upgrade_execute)
        start = source.index('wait_status == "4"')
        window = source[start : start + 620]
        self.assertIn("run_on_terminal", window)
        self.assertIn("--tui", window)


if __name__ == "__main__":
    unittest.main()
