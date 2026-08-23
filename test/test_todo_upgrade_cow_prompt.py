#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'étape 2 annonce des copies COW cassées, et ne demandait rien.

Le message disait le problème, invitait à arbitrer, puis passait à la suite :
« la migration proposera de neutraliser au palier ». Des dizaines de minutes
plus tard, donc — alors que REGARDER n'écrit rien, et que neutraliser ici vaut
pour tous les paliers, chaque base de palier étant un clone de celle-ci.

Ces tests portent sur ce que chaque réponse déclenche réellement, pas sur le
texte de l'invite.
"""

import builtins
import contextlib
import io
import os
import unittest

from script.todo import todo_i18n
from script.todo.todo_upgrade import TodoUpgrade

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PromptCase(unittest.TestCase):
    def setUp(self):
        # PAS set_lang() : il persiste la langue dans env_var.sh, suivi par
        # git. On écrit la mémoïsation, et on la rend.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def run_prompt(self, answers, database="db", version=13):
        """(commandes lancées, texte affiché) après ces réponses."""
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        lst_cmd = []
        upgrade.todo_upgrade_execute = lambda cmd, **kw: (
            lst_cmd.append(cmd),
            (False, cmd),
        )[1]
        # Les afficheurs ne passent PLUS par todo_upgrade_execute : il capture
        # la sortie par un tube, et un plein écran refuse de s'ouvrir sur un
        # stdout qui n'est pas un terminal. Sans ce bouchon, ces tests
        # lanceraient les vraies commandes.
        upgrade.run_on_terminal = lambda cmd: lst_cmd.append(cmd) or 0
        seq = iter(answers)
        original = builtins.input
        builtins.input = lambda *a: next(seq)
        self.addCleanup(setattr, builtins, "input", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upgrade.prompt_cow_prediction(database, version)
        return lst_cmd, out.getvalue()


class TestWhatEachAnswerRuns(PromptCase):
    def test_enter_neutralizes_now(self):
        # Entrée neutralise : c'est réversible — l'arch est conservée — et
        # ce qu'on neutralise ici vaut pour TOUS les paliers, au lieu
        # d'attendre des dizaines de minutes pour redécider à chaque fois.
        lst_cmd, _text = self.run_prompt([""])
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("--apply", lst_cmd[0])

    def test_n_runs_nothing_and_says_so(self):
        # Le défaut ne retire pas le choix : il ne fait qu'en proposer un.
        lst_cmd, text = self.run_prompt(["n"])
        self.assertEqual(lst_cmd, [])
        self.assertIn("version bump", text)

    def test_v_shows_what_the_copies_hold(self):
        lst_cmd, _ = self.run_prompt(["v", "n"])
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("cow_drift.py", lst_cmd[0])
        self.assertIn("-d db -t odoo13.0", lst_cmd[0])
        self.assertNotIn("--shape", lst_cmd[0])

    def test_s_shows_why_it_breaks(self):
        lst_cmd, _ = self.run_prompt(["s", "n"])
        self.assertTrue(lst_cmd[0].endswith("--shape"))

    def test_w_opens_the_full_screen_view(self):
        lst_cmd, _ = self.run_prompt(["w", "n"])
        self.assertTrue(lst_cmd[0].endswith("--tui"))

    def test_looking_does_not_answer_the_question(self):
        # LE piège de l'invite précédente : montrer puis passer à la suite.
        # Après avoir regardé, on doit pouvoir encore choisir.
        lst_cmd, _ = self.run_prompt(["v", "s", "w", "a"])
        self.assertEqual(len(lst_cmd), 4)
        self.assertIn("--apply", lst_cmd[-1])


class TestNeutralizingNow(PromptCase):
    def test_a_applies_and_stops_asking(self):
        lst_cmd, _ = self.run_prompt(["a"])
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("neutralize_cow_views.py", lst_cmd[0])
        self.assertIn("-d db -t odoo13.0 --apply", lst_cmd[0])

    def test_the_way_back_is_printed_and_is_valid(self):
        # `--restore` refuse `-t` : une commande d'annulation qu'on ne peut
        # pas coller est une commande d'annulation qui n'existe pas.
        _, text = self.run_prompt(["a"])
        self.assertIn("--restore", text)
        ligne = [x for x in text.splitlines() if "--restore" in x][0]
        self.assertIn("-d db", ligne)
        self.assertNotIn("-t odoo", ligne)

    def test_applying_says_nothing_about_deciding_later(self):
        _, text = self.run_prompt(["a"])
        self.assertNotIn("ask again", text)


class TestTheFullScreenViewGetsARealTerminal(PromptCase):
    """« w » réaffichait le rapport texte au lieu d'ouvrir le plein écran.

    `todo_upgrade_execute` capture la sortie par un tube pour que le pilote
    puisse la relire. La TUI y voit un stdout qui n'est PAS un terminal,
    renonce — c'est son repli délibéré — et retombe sur le même rapport que
    « v » venait d'afficher. Aucune erreur, aucune trace : deux touches
    différentes donnant le même écran.
    """

    def test_the_viewers_do_not_go_through_the_piped_executor(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.show_cow_drift)
        self.assertNotIn("todo_upgrade_execute", source)
        self.assertIn("self.run_on_terminal(", source)

    def test_run_on_terminal_does_not_capture_anything(self):
        # Capturer, c'est justement ce qui referme le plein écran.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.run_on_terminal)
        self.assertNotIn("PIPE", source)
        self.assertNotIn("capture_output", source)
        self.assertIn("subprocess.call(", source)

    def test_the_tui_refuses_a_pipe_and_accepts_a_terminal(self):
        # La raison même du défaut, vérifiée sur le code qui décide.
        import sys

        sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
        self.addCleanup(sys.path.remove, sys.path[0])
        from cow_drift_tui import run_tui

        finding = {
            "id": 1,
            "key": "k",
            "website_id": 1,
            "reason": "r",
            "module_id": 2,
            "module_arch": "a",
            "copy_arch": "b",
            "decl_current": None,
            "decl_target": None,
            "current_version": "odoo12.0",
            "target_version": "odoo13.0",
        }

        # Un vrai objet fichier : run_tui ÉCRIT maintenant la raison de son
        # refus, et un faux sans write() ne mesurait plus le comportement mais
        # sa propre incomplétude.
        class FakeStdout(io.StringIO):
            def __init__(self, tty):
                super().__init__()
                self.tty = tty

            def isatty(self):
                return self.tty

        real = sys.stdout
        self.addCleanup(setattr, sys, "stdout", real)
        sys.stdout = piped = FakeStdout(False)
        refused = run_tui([finding], run_app=False)
        sys.stdout = real
        self.assertFalse(refused)
        self.assertIn("terminal", piped.getvalue())

        sys.stdout = FakeStdout(True)
        opened = run_tui([finding], run_app=False)
        sys.stdout = real
        self.assertTrue(opened)


class TestTheBumpPromptSharesTheSameView(PromptCase):
    """Les deux invites doivent montrer la même chose, sans se dupliquer."""

    def test_show_cow_drift_builds_the_three_modes(self):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        lst_cmd = []
        upgrade.run_on_terminal = lambda cmd: lst_cmd.append(cmd) or 0
        for mode in ("diff", "shape", "tui"):
            upgrade.show_cow_drift("db", 13, mode)
        self.assertNotIn("--", lst_cmd[0].split("odoo13.0")[1])
        self.assertTrue(lst_cmd[1].endswith("--shape"))
        self.assertTrue(lst_cmd[2].endswith("--tui"))

    def test_the_bump_prompt_no_longer_builds_its_own_command(self):
        # Sans cela les deux invites peuvent diverger en silence.
        import inspect

        source = inspect.getsource(TodoUpgrade.neutralize_cow_views)
        self.assertNotIn("cow_drift.py", source)
        self.assertIn("self.show_cow_drift(", source)


if __name__ == "__main__":
    unittest.main()
