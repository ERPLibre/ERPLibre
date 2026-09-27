#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La capture héritée : les questions de TODO passent par le port lié.

Un ScriptedPort répond et garde ce qu'on lui a demandé ; aucune question
ne lit un vrai terminal. L'ordre d'import (les `ask=input` liés à
l'import, le sys.stdout d'urwid) se vérifie dans un processus à part,
HOME temporaire, la capture posée avant tout import de TODO comme dans le
worker.
"""

import builtins
import getpass
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import click
from todo_web_env import private_env

from script.todo import auto_ask, ui
from script.todo.ui import legacy, port

REPO = Path(__file__).resolve().parent.parent

# Le vrai TODO sous la capture, dans l'ordre du worker : urwid, la
# capture, puis `import todo` en mode script. Écrit dans argv[2] ce que les
# `ask=input` liés à l'import désignent et ce que le port a vu.
REAL_TODO = r"""
import builtins, json, os, sys
import urwid
import urwid.display._posix_raw_display as raw
from script.todo import todo_i18n
from script.todo.ui import legacy, port
todo_i18n.use_lang("en")
scripted = port.ScriptedPort(json.loads(sys.argv[1]))
legacy.install(scripted)
sys.path.insert(0, os.path.join(os.getcwd(), "script", "todo"))
import todo
from script.todo import textual_setup, transform_setup
from script.vpn import vault
todo.lang_is_configured = lambda: True
hooked = builtins.input
bound = {
    "transform_setup.create": transform_setup.create.__defaults__[0],
    "transform_setup.ensure": transform_setup.ensure.__defaults__[-1],
    "textual_setup.ensure": textual_setup.ensure.__defaults__[-1],
    "vault.ensure_vault": vault.VpnVault.ensure_vault.__defaults__[0],
}
report = {name: ask is hooked for name, ask in bound.items()}
defaults = raw.Screen.__init__.__defaults__
report["urwid"] = not any(isinstance(d, legacy.Tee) for d in defaults)
try:
    todo.TODO().run()
except EOFError:
    pass
with open(sys.argv[2], "w") as out:
    json.dump({"bound": report, "events": scripted.events}, out)
"""


class CaptureCase(unittest.TestCase):
    def capture(self, *answers, target=None):
        """La capture liée à un ScriptedPort de `answers` (ou à `target`) ;
        la sortie, Tee compris, va dans `self.out`."""
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        scripted = target or port.ScriptedPort(answers)
        self.addCleanup(legacy.install(scripted))
        return scripted


class TestClick(CaptureCase):
    def test_click_keeps_its_validation_loop(self):
        scripted = self.capture("forged", "4")
        self.assertEqual(click.prompt("Count", type=int), 4)
        self.assertEqual([e["text"] for e in scripted.events], ["Count: "] * 2)
        self.assertIn(
            "Error: 'forged' is not a valid integer.", self.out.getvalue()
        )

    def test_a_default_and_a_hidden_input(self):
        scripted = self.capture("", "hunter2")
        self.assertEqual(click.prompt("Mode", default="2"), "2")
        self.assertEqual(click.prompt("Password", hide_input=True), "hunter2")
        ask, secret = scripted.events
        self.assertEqual(
            (ask["kind"], ask["text"], ask["default"]),
            ("text", "Mode [2]: ", "2"),
        )
        self.assertEqual(
            (secret["kind"], secret["text"]), ("secret", "Password: ")
        )

    def test_confirm_is_a_confirmation_with_its_default(self):
        scripted = self.capture("maybe", "y", "")
        self.assertTrue(click.confirm("Go?"))
        self.assertTrue(click.confirm("Keep?", default=True))
        kinds = [(e["kind"], e["text"], e["default"]) for e in scripted.events]
        self.assertEqual(
            kinds,
            [
                ("confirm", "Go? [y/N]: ", "n"),
                ("confirm", "Go? [y/N]: ", "n"),
                ("confirm", "Keep? [Y/n]: ", "y"),
            ],
        )

    def test_cancel_is_ctrl_d_and_ctrl_c_stays_an_interrupt(self):
        self.capture(EOFError(), EOFError(), KeyboardInterrupt())
        with self.assertRaises(click.exceptions.Abort):
            click.prompt("Name")
        with self.assertRaises(EOFError):
            input("Name: ")
        with self.assertRaises(KeyboardInterrupt):
            input("Name: ")


class TestInput(CaptureCase):
    def test_answers_ending_the_prompt_make_a_confirmation(self):
        cases = [
            ("Continue anyway? (y/N): ", "n"),
            ("💬 Continue? (Y/N): ", None),
            ("Show the differences? [o/N] ", "n"),
            ("Keep it? (O/n) : ", "y"),
            ("Replace it? (y/Y): ", "n"),
            ("Run it now? [y/o/N] ", "n"),
        ]
        scripted = self.capture(*["y"] * len(cases))
        for text, _ in cases:
            self.assertEqual(input(text), "y")
        seen = [(e["kind"], e["text"], e["default"]) for e in scripted.events]
        self.assertEqual(seen, [("confirm", text, d) for text, d in cases])

    def test_typed_confirmations_secrets_and_the_rest(self):
        scripted = self.capture("forged", "o", "hunter2", "addons_forged")
        input("Type the database name to confirm (empty to cancel): ")
        input("Tapez o pour confirmer le risque (o/N, défaut : non) : ")
        getpass.getpass("Password: ")
        input("Module name to test: ")
        kinds = [(e["kind"], e["default"]) for e in scripted.events]
        self.assertEqual(
            kinds,
            [
                ("typed", None),
                ("typed", None),
                ("secret", None),
                ("text", None),
            ],
        )


class TestAutoAsk(CaptureCase):
    def test_the_auto_mode_counts_down_to_the_default(self):
        scripted = self.capture("", "n")
        with patch.dict(os.environ, {auto_ask.ENV_ENABLED: "1"}):
            self.assertEqual(auto_ask.ask("Go? (Y/n) ", "y", 7), "y")
            self.assertEqual(auto_ask.make_ask("y", 7)("Go? (Y/n) "), "n")
        [first, _] = scripted.events
        self.assertEqual(
            (first["kind"], first["default"], first["timeout_s"]),
            ("countdown", "y", 7),
        )

    def test_otherwise_its_question_is_what_its_text_says(self):
        scripted = self.capture("", "")
        with patch.dict(os.environ, {auto_ask.ENV_ENABLED: ""}):
            self.assertEqual(auto_ask.ask("Go? (Y/n) ", "y"), "y")
            self.assertEqual(auto_ask.ask("Name: "), "")
        kinds = [(e["kind"], e["default"]) for e in scripted.events]
        self.assertEqual(kinds, [("confirm", "y"), ("text", None)])


class TestInstall(CaptureCase):
    def test_the_tee_keeps_the_end_of_what_was_printed(self):
        inner = io.StringIO()
        tee = legacy.Tee(inner)
        with patch.object(legacy, "TEE_LIMIT", 10):
            for n in range(30):
                tee.write(f"{n % 10}")
            self.assertEqual(tee.since(), "0123456789")
        self.assertEqual(len(inner.getvalue()), 30)
        tee.clear()
        self.assertEqual(tee.since(), "")
        self.assertEqual(tee.getvalue(), "0123456789" * 3)

    def test_the_terminal_port_calls_the_originals_under_the_capture(self):
        typed = []

        def fake_input(text):
            typed.append(text)
            return "forged"

        self.enterContext(patch.dict(port.ORIGINAL, input=fake_input))
        self.capture(target=port.TerminalPort())
        self.assertEqual(input("Name: "), "forged")
        self.assertEqual(click.prompt("Mode", default="2"), "forged")
        self.assertEqual(typed, ["Name: ", "Mode [2]: "])

    def test_uninstall_puts_everything_back(self):
        hooked = (click.termui, "visible_prompt_func")
        before = (builtins.input, getpass.getpass, click.prompt, sys.stdout)
        before += (click.confirm, getattr(*hooked), auto_ask.ask)
        uninstall = legacy.install(port.ScriptedPort())
        self.assertIs(ui.current().__class__, port.ScriptedPort)
        with self.assertRaises(RuntimeError):
            legacy.install(port.ScriptedPort())
        uninstall()
        after = (builtins.input, getpass.getpass, click.prompt, sys.stdout)
        after += (click.confirm, getattr(*hooked), auto_ask.ask)
        self.assertEqual(before, after)
        self.assertIs(ui.current(), ui.TERMINAL)


class TestRealTodo(unittest.TestCase):
    def real_todo(self, *answers) -> dict:
        """Ce que REAL_TODO rapporte, le vrai TODO répondu par `answers`."""
        base = private_env(self.addCleanup)
        report = base / "report.json"
        result = subprocess.run(
            [sys.executable, "-c", REAL_TODO, json.dumps(answers), report],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(report.read_text())

    def test_the_ask_defaults_bound_at_import_are_the_capture(self):
        seen = self.real_todo("0")
        self.assertEqual(set(seen["bound"].values()), {True}, seen["bound"])


if __name__ == "__main__":
    unittest.main()
