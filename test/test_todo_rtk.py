#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu RTK : dit-il ce qui s'est réellement passé ?

Deux modes de défaillance se ressemblent à l'écran et n'ont pas le même
remède. Le binaire peut être absent — l'installation a échoué. Il peut aussi
être posé sur le disque sans que le PATH du processus y mène : un processus
garde le PATH qu'il avait au démarrage, donc une installation faite pendant
que TODO tourne lui reste invisible jusqu'au redémarrage. Lancer « rtk » nu
rend alors 127, que rien ne distingue d'une absence.

Ce test vérifie que les deux cas sont annoncés séparément, et que les
commandes passent par le chemin absolu du binaire plutôt que par le PATH.
"""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from script.todo.todo import TODO

FALLBACK = os.path.expanduser("~/.local/bin/rtk")
PATH_HINT = 'export PATH="$HOME/.local/bin:$PATH"'


class TestRtkLocate(unittest.TestCase):
    """rtk_locate distingue « dans le PATH », « posé ailleurs » et « absent »."""

    def test_found_in_path(self):
        with patch(
            "script.todo.todo.shutil.which", return_value="/usr/bin/rtk"
        ):
            self.assertEqual(TODO().rtk_locate(), ("/usr/bin/rtk", True))

    def test_found_outside_path(self):
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            self.assertEqual(TODO().rtk_locate(), (FALLBACK, False))

    def test_absent(self):
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            self.assertEqual(TODO().rtk_locate(), (None, False))


class TestRtkExec(unittest.TestCase):
    """rtk_exec appelle le binaire par son chemin absolu, jamais « rtk » nu."""

    def test_uses_absolute_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 0
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            todo.rtk_exec("gain")
        command = todo.execute.exec_command_live.call_args[0][0]
        self.assertTrue(command.startswith(FALLBACK), command)
        self.assertTrue(command.endswith(" gain"), command)

    def test_absent_runs_nothing(self):
        todo = TODO()
        todo.execute = MagicMock()
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            with redirect_stdout(io.StringIO()):
                status = todo.rtk_exec("gain")
        self.assertEqual(status, 1)
        todo.execute.exec_command_live.assert_not_called()


class TestRtkReportInstall(unittest.TestCase):
    """Le compte rendu d'installation nomme le résultat, sans le supposer."""

    def report(self, todo, exit_code):
        out = io.StringIO()
        with redirect_stdout(out):
            todo.rtk_report_install(exit_code)
        return out.getvalue()

    def test_failure_is_not_announced_as_success(self):
        todo = TODO()
        todo.execute = MagicMock()
        output = self.report(todo, 1)
        self.assertIn("❌", output)
        self.assertNotIn("✅", output)
        todo.execute.exec_command_live.assert_not_called()

    def test_success_reports_version_and_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["rtk 0.47.0"])
        with patch(
            "script.todo.todo.shutil.which", return_value="/usr/bin/rtk"
        ):
            output = self.report(todo, 0)
        self.assertIn("✅", output)
        self.assertIn("rtk 0.47.0", output)
        self.assertIn("/usr/bin/rtk", output)
        self.assertNotIn(PATH_HINT, output)

    def test_success_outside_path_tells_how_to_reach_it(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["rtk 0.47.0"])
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=True
        ):
            output = self.report(todo, 0)
        self.assertIn("✅", output)
        self.assertIn(PATH_HINT, output)

    def test_success_without_binary_is_not_a_success(self):
        todo = TODO()
        todo.execute = MagicMock()
        with patch("script.todo.todo.shutil.which", return_value=None), patch(
            "script.todo.todo.os.access", return_value=False
        ):
            output = self.report(todo, 0)
        self.assertIn("❌", output)
        self.assertNotIn("✅", output)


if __name__ == "__main__":
    unittest.main()
