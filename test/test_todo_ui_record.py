#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mode enregistrement : le terminal répond, chaque événement s'écrit.

RecordingPort répond par des doubles des fonctions d'origine, et `main`
fait tourner un double de TODO. Un test lance `make todo_record`, donc le
vrai TODO, entrée scriptée, HOME et XDG_RUNTIME_DIR temporaires, sans
terminal de contrôle.
"""

import getpass
import io
import json
import os
import re
import stat
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import click
from todo_web_env import private_env

from script.todo import todo_i18n
from script.todo.ui import legacy, port, record

REPO = Path(__file__).resolve().parent.parent


class TestRecordingPort(unittest.TestCase):
    def test_the_terminal_answers_and_each_event_is_written(self):
        typed = iter(["forged", "y", EOFError()])

        def fake_input(text):
            answer = next(typed)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        sink = io.StringIO()
        recording = record.RecordingPort(sink)
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(
            patch.dict(
                port.ORIGINAL,
                input=fake_input,
                getpass=lambda text: "hunter2",
            )
        )
        self.addCleanup(legacy.install(recording))
        self.assertEqual(input("Name: "), "forged")
        self.assertEqual(getpass.getpass("Password: "), "hunter2")
        self.assertTrue(click.confirm("Go?"))
        recording.notice("done")
        recording.event({"t": "run_end", "rc": 0, "secs": 0.1})
        with self.assertRaises(EOFError):
            input("More: ")
        events = [json.loads(line) for line in sink.getvalue().splitlines()]
        brief = [
            (e["t"], e.get("qid"), e.get("kind"), e.get("value"))
            for e in events
        ]
        self.assertEqual(
            brief,
            [
                ("ask", 1, "text", None),
                ("answer", 1, None, "forged"),
                ("ask", 2, "secret", None),
                ("answer", 2, None, "•••"),
                ("ask", 3, "confirm", None),
                ("answer", 3, None, "y"),
                ("notice", None, None, None),
                ("run_end", None, None, None),
                ("ask", 4, "text", None),
                ("cancel", 4, None, None),
            ],
        )
        self.assertNotIn("hunter2", sink.getvalue())

    def test_a_record_is_a_new_private_file(self):
        base = private_env(self.addCleanup)
        path, sink = record.open_record(REPO)
        sink.close()
        self.assertTrue(path.is_relative_to(base / "home" / ".erplibre"))
        self.assertRegex(path.name, r"^record-\d{8}-\d{6}-\d+\.jsonl$")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        # Même pid, même seconde : TODO relancé par restart_script.
        with patch.object(
            record.time, "strftime", return_value=path.name[7:22]
        ):
            again, sink = record.open_record(REPO)
        sink.close()
        self.assertEqual(again.name, path.name[:-6] + "-2.jsonl")


class TestMain(unittest.TestCase):
    """`record.main` autour d'un double de TODO, servi par sys.modules."""

    def main(self, error):
        private_env(self.addCleanup)
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        seen = {}

        class TODO:
            def fill_help_info(self, choices):
                return ""

            def run(self):
                seen["argv"] = list(sys.argv)
                raise error

        todo = types.ModuleType("todo")
        todo.TODO, todo.ENABLE_CRASH = TODO, False
        todo.execute = types.SimpleNamespace(Execute=types.SimpleNamespace())
        out = io.StringIO()
        with (
            patch.dict(sys.modules, {"todo": todo}),
            patch.object(sys, "argv", ["record.py", "--forged"]),
            patch.object(sys, "path", list(sys.path)),
            redirect_stdout(out),
        ):
            try:
                code = record.main()
            except EOFError as caught:
                code = caught  # comme au CLI, Ctrl+D à un input remonte
        return code, seen["argv"], out.getvalue()

    def test_it_ends_like_make_todo(self):
        code, argv, out = self.main(click.exceptions.Abort())
        self.assertEqual(code, 0)
        # restart_script relance `python <argv>` depuis la racine.
        self.assertEqual(argv, ["-m", "script.todo.ui.record", "--forged"])
        self.assertIn("Keyboard interrupt", out)
        self.assertIn("TODO execution time", out)
        self.assertIn("Events recorded in:", out)
        code, _, out = self.main(EOFError())
        self.assertIsInstance(code, EOFError)
        self.assertNotIn("Keyboard interrupt", out)
        self.assertIn("TODO execution time", out)


class TestMakeTodoRecord(unittest.TestCase):
    def test_make_todo_record_writes_what_the_terminal_showed(self):
        base = private_env(self.addCleanup)
        # Configuration, Retour, Quitter.
        result = subprocess.run(
            ["make", "--no-print-directory", "todo_record"],
            input="5\n0\n0\n",
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        [path] = (base / "home" / ".erplibre" / "todo_web").glob("*/record-*")
        self.assertIn(str(path), result.stdout)
        events = [json.loads(line) for line in path.read_text().splitlines()]
        menus = [e for e in events if e["t"] == "menu"]
        answers = [e["value"] for e in events if e["t"] == "answer"]
        self.assertEqual(answers, ["5", "0", "0"])
        self.assertEqual(
            [(m["qid"], m["source"], m["crumbs"]) for m in menus],
            [
                (1, "text", ["TODO"]),
                (2, "fill_help_info", ["TODO", "Configuration"]),
                (3, "text", ["TODO"]),
            ],
        )
        shown = re.sub(r"\n+", "\n", result.stdout)
        for menu in menus:
            self.assertIn(re.sub(r"\n+", "\n", menu["text"]), shown)


if __name__ == "__main__":
    unittest.main()
