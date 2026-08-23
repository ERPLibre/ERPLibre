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
        # Le désinstalleur ne passe PLUS par l'exécuteur qui capture : il
        # pose une question, et un tube la rendrait invisible.
        obj.run_on_terminal = lambda cmd: self.lst_cmd.append(cmd) or 0
        # Le doublon HONORE le défaut, comme le vrai `ask_gate` : sinon
        # les tests de défaut ne testeraient que le doublon.
        obj.ask_gate = lambda prompt, default="": answer or default
        return obj

    def run_prompt(self, lst_theme, answer):
        import contextlib
        import io

        obj = self.upgrade(lst_theme, answer)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            obj.prompt_uninstall_theme("db")
        return self.lst_cmd, out.getvalue()

    def test_the_default_answer_uninstalls_them(self):
        # « Entrée » désinstalle : c'est la réponse qu'on donnait à chaque
        # migration, et un thème traversé sans être retiré est justement ce
        # qui casse au palier suivant.
        lst_cmd, _text = self.run_prompt(["theme_technolibre"], "")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("uninstall_addons_theme.sh", lst_cmd[0])

    def test_saying_no_still_keeps_them(self):
        # Le défaut ne doit pas retirer le choix : il ne fait qu'en proposer
        # un. Sans cette issue, la question ne serait plus une question.
        lst_cmd, text = self.run_prompt(["theme_technolibre"], "n")
        self.assertEqual(lst_cmd, [])
        self.assertIn("Kept", text)

    def test_the_question_says_that_enter_uninstalls(self):
        # Une invite qui annonce « y/N » et fait l'inverse est pire que pas
        # d'invite du tout.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.prompt_uninstall_theme)
        self.assertIn("(Y/n,", source)
        self.assertNotIn("(y/N,", source)

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


class TestKeepOrDeleteTheLeftovers(unittest.TestCase):
    """Signaler sans offrir le geste oblige à le composer soi-même.

    Le rapport listait quinze pièces jointes et s'arrêtait là. Les effacer
    demandait de retrouver les identifiants et d'écrire un unlink() à la
    main — au milieu d'une migration, c'est ce qu'on ne fait pas.

    « Garder » reste le défaut, et rien n'est effacé sans avoir été écrit sur
    disque d'abord : c'est la condition pour pouvoir répondre « efface ».
    """

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        self.rows = ["4457|/theme_x/static/a.scss|2021-03-04"]
        self.saved = []
        self.deleted = []
        self.original_backup = theme_leftover.backup_attachments
        self.original_delete = theme_leftover.delete_attachments
        theme_leftover.backup_attachments = (
            lambda db, th, rows, fs=None: self.saved.append(rows) or ["/tmp/x"]
        )
        theme_leftover.delete_attachments = (
            lambda db, rows, cfg="./config.conf": (
                self.deleted.append(rows),
                (0, "ok"),
            )[1]
        )
        self.addCleanup(
            setattr,
            theme_leftover,
            "backup_attachments",
            self.original_backup,
        )
        self.addCleanup(
            setattr, theme_leftover, "delete_attachments", self.original_delete
        )

    def run_prompt(self, answer, rows=None):
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            done = theme_leftover.prompt(
                "db",
                "theme_x",
                self.rows if rows is None else rows,
                [],
                "./config.conf",
                ask=lambda prompt: answer,
            )
        return done, out.getvalue()

    def test_enter_keeps_them(self):
        done, text = self.run_prompt("")
        self.assertFalse(done)
        self.assertEqual(self.deleted, [])
        self.assertIn("Kept", text)

    def test_d_saves_before_deleting(self):
        # L'ORDRE est le point : effacer d'abord rendrait la sauvegarde vide.
        done, _ = self.run_prompt("d")
        self.assertTrue(done)
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(len(self.deleted), 1)

    def test_a_failed_deletion_says_nothing_was_removed(self):
        theme_leftover.delete_attachments = (
            lambda db, rows, cfg="./config.conf": (1, "boom")
        )
        done, text = self.run_prompt("d")
        self.assertFalse(done)
        self.assertIn("nothing was removed", text)

    def test_no_leftover_asks_nothing(self):
        done, text = self.run_prompt("d", rows=[])
        self.assertFalse(done)
        self.assertEqual(text, "")

    def test_the_prompt_stays_out_of_a_pipe(self):
        with open(theme_leftover.__file__) as handle:
            self.assertIn("sys.stdin.isatty()", handle.read())


class TestTheQuestionMustBeVisible(unittest.TestCase):
    """Une invite qu'on ne voit pas est une invite à laquelle on répond mal.

    Le script se termine par theme_leftover.py, qui pose une question. Lancé
    par l'exécuteur qui CAPTURE la sortie, son stdout est un tube : Python
    bufferise par blocs et l'invite reste invisible pendant que le processus
    attend. Vécu — on croit à un blocage, on tape Entrée plusieurs fois, la
    première frappe répond à l'aveugle et les suivantes vont à la question
    d'après.

    Deux verrous, car un seul ne suffit pas : la migration lance ce script
    sur le vrai terminal, ET l'outil refuse de questionner s'il ne peut pas
    se faire voir.
    """

    def test_the_migration_runs_it_on_the_real_terminal(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.prompt_uninstall_theme)
        self.assertIn("run_on_terminal", source)
        self.assertNotIn("todo_upgrade_execute", source)

    def test_asking_needs_stdout_not_just_stdin(self):
        # LE défaut : ne tester que stdin laisse poser une question dans un
        # tube. Il faut de quoi LIRE la réponse ET MONTRER la question.
        import io
        import sys

        class Fake(io.StringIO):
            def __init__(self, tty):
                super().__init__()
                self.tty = tty

            def isatty(self):
                return self.tty

        real_in, real_out = sys.stdin, sys.stdout
        self.addCleanup(setattr, sys, "stdin", real_in)
        self.addCleanup(setattr, sys, "stdout", real_out)
        for stdin_tty, stdout_tty, expected in (
            (True, True, True),
            (True, False, False),  # le cas mesuré
            (False, True, False),
            (False, False, False),
        ):
            sys.stdin, sys.stdout = Fake(stdin_tty), Fake(stdout_tty)
            got = theme_leftover.can_ask()
            sys.stdin, sys.stdout = real_in, real_out
            with self.subTest(stdin=stdin_tty, stdout=stdout_tty):
                self.assertEqual(got, expected)

    def test_the_other_tools_guard_the_same_way(self):
        # Trois outils posent des questions ; un seul corrigé laisserait le
        # même piège ailleurs.
        import os

        REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for relative in (
            "script/odoo/migration/smoke_public_url.py",
            "script/odoo/migration/check_stale_scss.py",
            "script/addons/theme_leftover.py",
        ):
            with open(os.path.join(REPO_ROOT, relative)) as handle:
                source = handle.read()
            with self.subTest(tool=relative):
                self.assertIn("def can_ask()", source)
                self.assertIn("sys.stdout.isatty()", source)


class TestTheIdentifiersSentToOdoo(unittest.TestCase):
    """browse() veut des ENTIERS ; psql rend des chaînes.

    Mesuré sur une vraie base : browse(['4457']) fait échouer Odoo sur
    « la recherche en base n'a pas les identifiants (('4457',)) et a des
    identifiants supplémentaires ((4457,)) ». Il compare des chaînes à des
    entiers, ne retrouve rien, et refuse. L'effacement n'a rien retiré —
    heureusement, la sauvegarde était déjà faite.
    """

    def test_the_script_browses_integers(self):
        import inspect

        source = inspect.getsource(theme_leftover.delete_attachments)
        self.assertIn("int(row.split", source)

    def test_the_pushed_script_carries_no_quoted_id(self):
        # Le rendu exact de ce qui part dans le shell : une seule apostrophe
        # autour d'un identifiant et Odoo refuse tout le lot.
        pushed = {}
        original = theme_leftover.subprocess.run
        theme_leftover.subprocess.run = (
            lambda *a, **kw: pushed.update(script=kw.get("input", ""))
            or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        )
        self.addCleanup(setattr, theme_leftover.subprocess, "run", original)
        theme_leftover.delete_attachments(
            "db", ["4457|/theme_x/a.scss|2021-03-04", "4768|/b.css|d"]
        )
        self.assertIn("browse([4457, 4768])", pushed["script"])
        self.assertNotIn("'4457'", pushed["script"])

    def test_a_non_numeric_row_is_not_sent_silently(self):
        # Mieux vaut échouer ici que pousser un script qu'Odoo refusera.
        with self.assertRaises(ValueError):
            theme_leftover.delete_attachments("db", ["zz|/a|d"])


class TestTheMisleadingErrorCode(unittest.TestCase):
    """« 1 » veut dire « il reste des choses », pas « ça a raté »."""

    def test_the_uninstaller_does_not_fail_on_leftovers(self):
        # Le rapport était la dernière commande du script : son code
        # devenait celui du script, et la migration annonçait une erreur sur
        # un thème correctement retiré.
        with open(SCRIPT) as handle:
            source = handle.read()
        self.assertIn("theme_leftover.py", source)
        queue = source[source.index("theme_leftover.py") :]
        self.assertIn("|| true", queue)
        self.assertIn("exit 0", queue)

    def test_the_cow_check_no_longer_goes_through_the_capturing_executor(self):
        # exec_command_live imprime « Command returned error code: 1 » dès
        # qu'un code non nul sort, y compris sur un rapport qui va bien.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        avant = source[: source.index("check_cow_views.py")]
        self.assertGreater(
            avant.rfind("run_on_terminal("),
            avant.rfind("todo_upgrade_execute("),
        )


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
