#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le port d'interaction de TODO : la façade `ui`, ses ports et `shell`.

Aucun test ne lance TODO ni ne lit un vrai terminal : les fonctions
d'origine de TerminalPort sont des doubles posés dans `port.ORIGINAL`, et
la boucle d'urwid du navigateur de fichiers est simulée (`FakeLoop`).
"""

import io
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from script.execute import execute
from script.todo import todo_i18n, ui
from script.todo.ui import port

REPO = Path(__file__).resolve().parent.parent


class FakeLoop:
    """`urwid.MainLoop` simulé : `run` presse le bouton d'étiquette `press`
    du navigateur qu'il montre, ou tape « q » sans lui, comme
    l'utilisateur ; une ExitMainLoop le finit, comme la boucle d'urwid."""

    press = None

    def __init__(self, frame, palette, unhandled_input):
        self.browser, self.key = frame.body, unhandled_input

    def run(self):
        import urwid

        try:
            if self.press is None:
                self.key("q")
            for widget in list(self.browser.list_walker):
                if getattr(widget, "label", None) == self.press:
                    widget.keypress((40,), "enter")
        except urwid.ExitMainLoop:
            pass


def _english(test):
    """TODO parle anglais le temps du test `test`."""
    saved = todo_i18n._current_lang
    test.addCleanup(setattr, todo_i18n, "_current_lang", saved)
    todo_i18n.use_lang("en")


def _forged_dir(test) -> str:
    """Un répertoire temporaire qui porte `forged.zip` et `forged_dir/`,
    retiré au nettoyage de `test`."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    Path(tmp.name, "forged.zip").touch()
    Path(tmp.name, "forged_dir").mkdir()
    return tmp.name


class TestFacade(unittest.TestCase):
    def test_each_call_resolves_the_bound_port(self):
        self.assertIs(ui.current(), ui.TERMINAL)
        outer, inner = port.ScriptedPort(["a"]), port.ScriptedPort(["b"])
        with ui.bind(outer):
            with ui.bind(inner):
                self.assertEqual(ui.ask("Name: "), "b")
            self.assertEqual(ui.ask("Name: "), "a")
        self.assertIs(ui.current(), ui.TERMINAL)
        token = ui.attach(outer)
        self.assertIs(ui.current(), outer)
        ui.detach(token)
        self.assertIs(ui.current(), ui.TERMINAL)

    def test_two_threads_keep_distinct_ports(self):
        both_bound = threading.Barrier(2, timeout=10)
        seen = {}

        def session(name):
            scripted = port.ScriptedPort([name])
            with ui.bind(scripted):
                both_bound.wait()
                seen[name] = (ui.ask("Who? "), ui.current() is scripted)

        threads = [
            threading.Thread(target=session, args=(name,))
            for name in ("first", "second")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(
            seen, {"first": ("first", True), "second": ("second", True)}
        )
        self.assertIs(ui.current(), ui.TERMINAL)

    def test_the_port_imports_no_interface_library(self):
        code = (
            "import sys\n"
            "from script.todo import ui\n"
            "libs = ('click', 'urwid', 'textual', 'tornado')\n"
            "print(sorted(name for name in libs if name in sys.modules))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.stdout, "[]\n", result.stderr)


class TestTerminalPort(unittest.TestCase):
    def originals(self, **fakes):
        patcher = patch.dict(port.ORIGINAL, fakes)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_questions_call_the_original_functions(self):
        calls = []

        def fake_input(text):
            calls.append(("input", text))
            return "typed"

        def fake_getpass(text):
            calls.append(("getpass", text))
            return "hunter2"

        def fake_countdown(text, default, seconds):
            calls.append(("countdown", text, default, seconds))
            return default

        self.originals(input=fake_input, getpass=fake_getpass)
        self.originals(**{"auto_ask.ask": fake_countdown})
        terminal = port.TerminalPort()
        view = port.menu_view("[1] One\n: ", [])
        self.assertEqual(terminal.ask("Name: "), "typed")
        self.assertEqual(terminal.menu(view), "typed")
        self.assertEqual(terminal.secret("Password: "), "hunter2")
        self.assertEqual(terminal.ask("Go? ", "n", "countdown", 5), "n")
        self.assertEqual(
            calls,
            [
                ("input", "Name: "),
                ("input", "[1] One\n: "),
                ("getpass", "Password: "),
                ("countdown", "Go? ", "n", 5),
            ],
        )

    def test_a_choice_is_asked_by_number_through_input(self):
        texts = []

        def fake_input(text):
            texts.append(text)
            return "2"

        self.originals(input=fake_input)
        terminal = port.TerminalPort()
        self.assertEqual(terminal.choose("Which?", ["alpha", "beta"]), "beta")
        self.assertEqual(texts, ["Which?\n[1] alpha\n[2] beta\n: "])

    def test_run_calls_exec_command_live_and_notice_prints(self):
        with patch.object(
            execute.Execute, "exec_command_live", return_value=3
        ) as live:
            rc = port.TerminalPort().run("true", source_erplibre=False)
        self.assertEqual(rc, 3)
        live.assert_called_once_with("true", source_erplibre=False)
        out = io.StringIO()
        with redirect_stdout(out):
            port.TerminalPort().notice("forged notice")
        self.assertEqual(out.getvalue(), "forged notice\n")
        self.assertFalse(port.TerminalPort().open_view("telemetry"))

    def test_a_path_is_chosen_in_the_urwid_browser(self):
        from script.todo import todo_file_browser

        base = _forged_dir(self)
        loop = patch.object(todo_file_browser.urwid, "MainLoop", FakeLoop)
        with loop, patch.object(FakeLoop, "press", "forged.zip"):
            chosen = port.TerminalPort().pick_path(base)
        with loop:
            cancelled = port.TerminalPort().pick_path(base)
        with loop, patch.object(FakeLoop, "press", "."):
            folder = port.TerminalPort().pick_path(base, directory=True)
        self.assertEqual(chosen, os.path.join(base, "forged.zip"))
        self.assertIsNone(cancelled)
        self.assertEqual(folder, base)


class TestScriptedPort(unittest.TestCase):
    def test_answers_in_order_then_end_of_file(self):
        scripted = port.ScriptedPort(["1", KeyboardInterrupt()], codes=[4])
        self.assertEqual(scripted.ask("Choice: ", "2"), "1")
        with self.assertRaises(KeyboardInterrupt):
            scripted.secret("Password: ")
        with self.assertRaises(EOFError):
            scripted.ask("More? ")
        scripted.notice("done", "error")
        self.assertEqual(scripted.run("make forged", quiet=True), 4)
        self.assertEqual(scripted.run("true"), 0)
        self.assertTrue(scripted.open_view("telemetry"))
        kinds = [(e["t"], e.get("kind")) for e in scripted.events]
        self.assertEqual(
            kinds,
            [
                ("ask", "text"),
                ("ask", "secret"),
                ("ask", "text"),
                ("notice", None),
                ("run", None),
                ("run", None),
                ("open_view", None),
            ],
        )
        self.assertEqual(scripted.events[0]["default"], "2")
        self.assertEqual(scripted.events[4]["opts"], {"quiet": True})

    def test_confirm_and_choose_ask_again_until_they_can_answer(self):
        scripted = port.ScriptedPort(["maybe", "o", "", "yes", "no"])
        self.assertTrue(scripted.confirm("Go?"))
        self.assertFalse(scripted.confirm("Go?"))
        self.assertFalse(scripted.confirm("Delete?", typed="forged"))
        self.assertTrue(scripted.confirm("Delete?", typed="no"))
        texts = [e["text"] for e in scripted.events]
        self.assertEqual(texts[:3], ["Go? [y/N]: "] * 3)
        self.assertEqual(scripted.events[0]["default"], "n")
        self.assertEqual(scripted.events[3]["kind"], "typed")
        scripted = port.ScriptedPort(["4", "2", "1, 3"])
        options = ["alpha", "beta", "gamma"]
        self.assertEqual(scripted.choose("Which?", options), "beta")
        self.assertEqual(
            scripted.choose("Which?", options, multi=True), ["alpha", "gamma"]
        )
        single, again, multi = scripted.events
        self.assertEqual(
            (single["t"], single["kind"], single["multi"], multi["multi"]),
            ("ask", "choose", False, True),
        )
        self.assertEqual(
            single["text"], "Which?\n[1] alpha\n[2] beta\n[3] gamma\n: "
        )
        self.assertEqual(single["speak"], "Which?")
        self.assertEqual(
            [(o["key"], o["label"], o["speak"]) for o in single["options"]],
            [
                ("1", "alpha", "alpha"),
                ("2", "beta", "beta"),
                ("3", "gamma", "gamma"),
            ],
        )
        self.assertEqual(again, single)

    def test_a_typed_confirmation_carries_the_text_it_expects(self):
        # La page n'active sa réponse qu'à l'égalité ; le port vérifie.
        scripted = port.ScriptedPort([" forged ", "forged-other"])
        self.assertTrue(scripted.confirm("Type forged:", typed="forged"))
        self.assertFalse(scripted.confirm("Type forged:", typed="forged"))
        asked = scripted.events[0]
        self.assertEqual(
            (asked["t"], asked["kind"], asked["expected"], asked["text"]),
            ("ask", "typed", "forged", "Type forged:"),
        )
        self.assertEqual(asked["requires"], ["typed"])

    def test_a_path_is_checked_on_disk_and_asked_again(self):
        _english(self)
        base = _forged_dir(self)
        folder = os.path.join(base, "forged_dir")
        answers = ["absent.zip", "forged_dir", "forged.zip", " ", EOFError()]
        scripted = port.ScriptedPort(
            [*answers, "forged.zip", "~/forged_dir", ".."]
        )
        with ui.bind(scripted), patch.dict(os.environ, {"HOME": base}):
            chosen = ui.pick_path(base)
            blank = ui.pick_path(base)
            cancelled = ui.pick_path(base, directory=True)
            home = ui.pick_path(base, directory=True)
            parent = ui.pick_path(folder, directory=True)
        self.assertEqual(chosen, os.path.join(base, "forged.zip"))
        self.assertEqual((blank, cancelled), (None, None))
        self.assertEqual((home, parent), (folder, base))
        asked = [e for e in scripted.events if e["t"] == "ask"]
        self.assertEqual(
            [(e["kind"], e["start"], e["directory"]) for e in asked],
            [("path", base, False)] * 4
            + [("path", base, True)] * 3
            + [("path", folder, True)],
        )
        self.assertEqual(
            asked[0]["text"], f"📂 {base}\nFile path (empty to cancel): "
        )
        self.assertEqual(
            asked[-1]["speak"], "Directory path (empty to cancel)"
        )
        self.assertEqual(asked[0]["requires"], ["free_text"])
        notices = [e["text"] for e in scripted.events if e["t"] == "notice"]
        self.assertEqual(
            notices,
            [
                f"No such file: {base}/absent.zip",
                f"Not a file: {folder}",
                f"Not a directory: {base}/forged.zip",
            ],
        )


class TestMessages(unittest.TestCase):
    def test_each_question_carries_speak_requires_and_fallback(self):
        cases = {
            "text": ["free_text"],
            "secret": ["secret"],
            "confirm": [],
            "typed": ["typed"],
            "countdown": [],
            "choose": [],
        }
        for kind, requires in cases.items():
            message = port.question(kind, "💬 Continue anyway? :  ")
            self.assertEqual(message["speak"], "Continue anyway?", kind)
            self.assertEqual(message["requires"], requires, kind)
            self.assertEqual(message["fallback"], "pty", kind)
        self.assertEqual(
            port.question("countdown", "Go?", "n", 15)["timeout_s"], 15
        )
        self.assertNotIn("timeout_s", port.question("text", "Name: "))

    def test_a_menu_speaks_its_last_crumb_and_each_entry(self):
        items = [{"key": "1", "label": "🚪 Quit", "section": None}]
        view = port.menu_view("x", items, crumbs=["TODO", "Execute"])
        self.assertEqual(view["speak"], "Execute")
        self.assertEqual(view["items"][0]["speak"], "Quit")
        self.assertEqual(view["requires"], [])
        self.assertEqual(port.speak("Header\n[1] Code\n: "), "[1] Code")
        self.assertEqual(port.speak("\n  \n:"), "")


class TestShell(unittest.TestCase):
    def test_each_interpolation_stays_one_word(self):
        path = "/srv/forged dir;touch forged"
        days = 30
        command = ui.shell(t"find {path} -mtime +{days:03d} -delete")
        self.assertEqual(
            command, "find '/srv/forged dir;touch forged' -mtime +030 -delete"
        )
        self.assertEqual(
            shlex.split(command), ["find", path, "-mtime", "+030", "-delete"]
        )
        # La conversion passe avant la citation : `!r` ajoute ses
        # apostrophes, que la citation garde.
        self.assertEqual(
            shlex.split(ui.shell(t"echo {path!r}")), ["echo", repr(path)]
        )

    def test_quotes_around_an_interpolation_undo_its_quoting(self):
        # La citation est déjà faite : des guillemets de plus la referment,
        # et la valeur redevient plusieurs mots, `;` compris.
        path = "/srv/forged dir;touch forged"
        command = ui.shell(t"echo '{path}'")
        self.assertEqual(command, "echo ''/srv/forged dir;touch forged''")
        self.assertEqual(
            shlex.split(command),
            ["echo", "/srv/forged", "dir;touch", "forged"],
        )

    def test_a_plain_string_passes_unchanged_and_others_are_refused(self):
        self.assertEqual(ui.shell("ls -l; true"), "ls -l; true")
        with self.assertRaises(TypeError):
            ui.shell(["ls", "-l"])

    def test_run_hands_the_quoted_command_to_the_bound_port(self):
        name = "a b"
        scripted = port.ScriptedPort()
        with ui.bind(scripted):
            self.assertEqual(ui.run(t"rm -- {name}", quiet=True), 0)
        self.assertEqual(
            scripted.events,
            [{"t": "run", "cmd": "rm -- 'a b'", "opts": {"quiet": True}}],
        )


if __name__ == "__main__":
    unittest.main()
