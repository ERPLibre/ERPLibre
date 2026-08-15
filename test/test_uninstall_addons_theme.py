#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Désinstaller un thème n'est pas désinstaller son module.

`--install-theme` appelle `button_choose_theme()`, qui fait deux choses :
copier les vues et ressources du thème dans chaque site, et écrire dans
`user_values.scss` une personnalisation qui DÉFINIT `$o-theme-font-number`
et ses trois voisines. Le chemin de retrait d'Odoo, `_theme_remove()`, défait
les deux — et son premier geste est `_reset_default_config()`, celui qui écrit
ces définitions.

Un `--uninstall` nu saute tout cela. Mesuré sur une migration réelle 12 → 13 :
le bundle `web.assets_frontend` s'arrête sur « Undefined variable:
$o-theme-font-number ». La variable venait des fichiers `option_font_body_*`
d'Odoo 12, supprimés en 13.0 ; seul le thème la redéfinissait encore, et le
retirer a mis à nu un SCSS personnalisé figé depuis 2020.

Ces tests portent sur ce que le script fait, pas sur son texte.
"""

import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "script", "addons", "uninstall_addons_theme.sh")

sys.path.insert(0, os.path.join(REPO, "script", "addons"))
import theme_leftover  # noqa: E402


class TestTheScriptShape(unittest.TestCase):
    def source(self):
        with open(SCRIPT) as handle:
            return handle.read()

    def test_it_exists_and_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_parses(self):
        done = subprocess.run(
            ["bash", "-n", SCRIPT], capture_output=True, text=True
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_it_goes_through_theme_remove(self):
        # LE point : sans cet appel, le script ne serait qu'un --uninstall
        # sous un autre nom, et laisserait la même panne derrière lui.
        self.assertIn("_theme_remove(website)", self.source())

    def test_it_walks_every_website(self):
        # Un site par thème : n'en traiter qu'un laisserait les autres avec
        # des copies dont le module est parti.
        source = self.source()
        self.assertIn('env["website"].search([])', source)

    def test_it_still_uninstalls_the_module(self):
        self.assertIn("--uninstall", self.source())

    def test_it_mirrors_the_installer_checks(self):
        # Même garde-fou que install_addons_theme.sh : un nom de module
        # inexistant doit s'arrêter avant de toucher la base.
        self.assertIn("check_addons_exist.py", self.source())

    def test_a_missing_argument_stops_before_anything(self):
        done = subprocess.run(
            ["bash", SCRIPT, "onlydb"],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("Usage", done.stdout + done.stderr)


class TestTheLeftoverReport(unittest.TestCase):
    """Ce que le déchargement ne prend pas, et qu'il faut au moins savoir."""

    def setUp(self):
        # PAS set_lang() : il persiste la langue dans env_var.sh, suivi par
        # git. On épingle la mémoïsation — sans quoi ces tests liraient la
        # langue du poste, et passeraient ou non selon la machine.
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_nothing_left_is_said_plainly(self):
        text = theme_leftover.render("theme_x", [], [])
        self.assertIn("✅", text)

    def test_attachments_are_listed_with_their_date(self):
        rows = ["4457|/theme_x/static/a.scss|2021-03-04"]
        text = theme_leftover.render("theme_x", rows, [])
        self.assertIn("4457", text)
        self.assertIn("2021-03-04", text)

    def test_a_long_list_says_how_many_it_hid(self):
        # Tronquer sans le dire se lit comme « c'est tout ».
        rows = [f"{i}|/theme_x/a{i}.scss|2021-01-01" for i in range(30)]
        text = theme_leftover.render("theme_x", rows, [])
        self.assertIn("10", text)

    def test_it_never_offers_to_delete(self):
        # Le contenu d'une pièce jointe peut être la seule trace d'une
        # personnalisation : c'est une décision, pas un ménage.
        text = theme_leftover.render("theme_x", ["1|/theme_x/a|d"], [])
        self.assertIn("Nothing was deleted", text)

    def test_the_sql_escapes_a_quote_in_the_theme_name(self):
        self.assertEqual(theme_leftover.quote_literal("a'b"), "'a''b'")

    def test_the_query_is_read_only_on_the_server_side(self):
        # Pas une promesse de l'outil : PostgreSQL refuse l'écriture.
        with open(theme_leftover.__file__) as handle:
            source = handle.read()
        self.assertIn("default_transaction_read_only=on", source)


class TestTheMigrationOffersIt(unittest.TestCase):
    """La question doit venir AVANT le premier palier, et par défaut non.

    Un thème installé traverse la migration : ses copies de vues et ses SCSS
    suivent chaque palier, et chaque palier peut renommer ce dont ils
    dépendent. Le proposer tôt retire d'un coup une famille de pannes.

    Par défaut non : retirer un thème change l'apparence d'un site, et ce
    n'est pas à une migration de trancher cela à la place de quelqu'un.
    """

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def upgrade(self, lst_theme, answer):
        from script.todo.todo_upgrade import TodoUpgrade

        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {}
        obj.lst_command_executed = []
        obj.write_config = lambda: None
        obj.installed_theme = lambda db: lst_theme
        self.lst_cmd = []
        obj.todo_upgrade_execute = lambda cmd, **kw: (
            self.lst_cmd.append(cmd),
            (False, cmd, []),
        )[1]
        obj.ask_gate = lambda prompt: answer
        return obj

    def run_prompt(self, lst_theme, answer):
        import contextlib
        import io

        obj = self.upgrade(lst_theme, answer)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            obj.prompt_uninstall_theme("db")
        return self.lst_cmd, out.getvalue()

    def test_the_default_answer_uninstalls_nothing(self):
        # « Entrée » ne doit RIEN faire : la migration ne décide pas de
        # l'apparence d'un site à la place de son propriétaire.
        lst_cmd, text = self.run_prompt(["theme_technolibre"], "")
        self.assertEqual(lst_cmd, [])
        self.assertIn("Kept", text)

    def test_no_theme_means_no_question(self):
        lst_cmd, text = self.run_prompt([], "y")
        self.assertEqual(lst_cmd, [])
        self.assertEqual(text, "")

    def test_yes_runs_the_proper_uninstaller(self):
        lst_cmd, _ = self.run_prompt(["theme_technolibre"], "y")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn(
            "uninstall_addons_theme.sh db theme_technolibre", lst_cmd[0]
        )

    def test_every_theme_is_offered_together(self):
        lst_cmd, _ = self.run_prompt(["theme_a", "theme_b"], "Y")
        self.assertEqual(len(lst_cmd), 2)

    def test_it_is_asked_before_the_first_bump(self):
        # L'ordre est le point : posée après le premier palier, la question
        # arrive quand les copies ont déjà traversé un renommage.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        appel = source.index("prompt_uninstall_theme")
        palier = source.index("4 - Upgrade version with OpenUpgrade")
        self.assertLess(appel, palier)

    def test_theme_default_is_not_a_theme_to_remove(self):
        # theme_default EST l'absence de thème : le proposer au retrait
        # ferait poser une question sans objet à chaque migration.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.installed_theme)
        self.assertIn("name <> 'theme_default'", source)


class TestExitCodes(unittest.TestCase):
    """0 rien, 1 des restes, 2 l'outil a échoué — comme les outils voisins."""

    def test_a_dead_database_is_a_tool_failure(self):
        done = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO, "script", "addons", "theme_leftover.py"),
                "-d",
                "erplibre_no_such_database_zz",
                "-t",
                "theme_x",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        self.assertEqual(done.returncode, 2, done.stdout)


if __name__ == "__main__":
    unittest.main()
