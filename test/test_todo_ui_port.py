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

    def test_every_question_ends_with_the_ended_callbacks(self):
        ended = []
        self.enterContext(patch.object(ui, "ENDED", [lambda: ended.append(1)]))
        view = port.menu_view("Menu", [])
        answers = ["x", "1", "2", "y", ""]
        with ui.bind(port.ScriptedPort(answers)):
            self.assertEqual(ui.ask("Name: "), "x")
            self.assertEqual(ui.choose("Which?", ["a"]), "a")
            self.assertEqual(ui.menu(view), "2")
            self.assertTrue(ui.confirm("Go?", default=True))
            self.assertIsNone(ui.pick_path(_forged_dir(self)))
            with self.assertRaises(EOFError):
                ui.secret("Password: ")
        self.assertEqual(ended, [1] * 6)

    def test_confirm_passes_each_argument_to_the_bound_port(self):
        seen = []

        class Port(port.ScriptedPort):
            def confirm(self, *args):
                seen.append(args)

        with ui.bind(Port()):
            ui.confirm("Go?", True, None, 5, True, {"b": "Back"})
            ui.confirm("Go?", default=False, back=True)
            ui.confirm("Type forged:", typed="forged")
        self.assertEqual(
            seen,
            [
                ("Go?", True, None, 5, True, {"b": "Back"}),
                ("Go?", False, None, None, True, None),
                ("Type forged:", None, "forged", None, False, None),
            ],
        )

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
        out = io.StringIO()
        self.assertEqual(terminal.ask("Name: "), "typed")
        with redirect_stdout(out):
            self.assertEqual(terminal.menu(view), "typed")
        self.assertEqual(terminal.secret("Password: "), "hunter2")
        self.assertEqual(terminal.ask("Go? ", "n", "countdown", 5), "n")
        self.assertEqual(
            calls,
            [
                ("input", "Name: "),
                ("input", ": "),
                ("getpass", "Password: "),
                ("countdown", "Go? ", "n", 5),
            ],
        )
        # Le menu s'imprime au-dessus de son invite, seule passée à input.
        self.assertEqual(out.getvalue(), "[1] One\n")

    def stop_with(self, error):
        """Chaque fonction d'origine du terminal lève `error`, comme
        Ctrl+D (EOFError) ou Ctrl+C (KeyboardInterrupt) à son invite."""

        def stopped(*args):
            raise error

        self.originals(input=stopped, getpass=stopped)
        self.originals(**{"auto_ask.ask": stopped})

    def test_ctrl_d_at_a_menu_ends_the_line(self):
        self.stop_with(EOFError())
        view = port.menu_view("[1] One\n: ", [])
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(EOFError):
            port.TerminalPort().menu(view)
        self.assertEqual(out.getvalue(), "[1] One\n\n")

    def test_ctrl_d_at_a_text_question_ends_the_line(self):
        self.stop_with(EOFError())
        for kind in ("text", "secret", "countdown"):
            with self.subTest(kind=kind):
                out = io.StringIO()
                with redirect_stdout(out), self.assertRaises(EOFError):
                    port.TerminalPort().ask("Name: ", "n", kind, 5)
                self.assertEqual(out.getvalue(), "\n")

    def test_ctrl_c_at_a_question_prints_nothing(self):
        self.stop_with(KeyboardInterrupt())
        view = port.menu_view(": ", [])
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(KeyboardInterrupt):
            port.TerminalPort().menu(view)
        self.assertEqual(out.getvalue(), "")
        for kind in ("text", "secret", "countdown"):
            with self.subTest(kind=kind):
                out = io.StringIO()
                with (
                    redirect_stdout(out),
                    self.assertRaises(KeyboardInterrupt),
                ):
                    port.TerminalPort().ask("Name: ", "n", kind, 5)
                self.assertEqual(out.getvalue(), "")

    def test_a_choice_is_asked_by_number_through_input(self):
        texts = []

        def fake_input(text):
            texts.append(text)
            return "2"

        _english(self)
        self.originals(input=fake_input)
        terminal = port.TerminalPort()
        out = io.StringIO()
        with redirect_stdout(out):
            chosen = terminal.choose("Which?", ["alpha", "beta"])
        self.assertEqual(chosen, "beta")
        self.assertEqual(texts, [": "])
        self.assertEqual(
            out.getvalue(), "Which?\n[1] alpha\n[2] beta\n[0] 🔙 Back\n"
        )

    def test_without_the_capture_the_process_input_answers(self):
        # Le double qu'un test pose sur `input`, après l'import du port,
        # répond au choix que pose un sélecteur par le terminal.
        _english(self)
        self.assertNotIn("input", port.ORIGINAL)
        out = io.StringIO()
        with patch("builtins.input", return_value="2") as typed:
            with redirect_stdout(out):
                chosen = port.TerminalPort().choose("Which?", ["a", "b"])
        self.assertEqual(chosen, "b")
        typed.assert_called_once_with(": ")
        self.assertEqual(out.getvalue(), "Which?\n[1] a\n[2] b\n[0] 🔙 Back\n")

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
        import urwid

        base = _forged_dir(self)
        loop = patch.object(urwid, "MainLoop", FakeLoop)
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
        _english(self)
        scripted = port.ScriptedPort(["maybe", "o", "", "yes", "no"])
        self.assertTrue(scripted.confirm("Go?", default=False))
        self.assertFalse(scripted.confirm("Go?", default=False))
        self.assertFalse(scripted.confirm("Delete?", typed="forged"))
        self.assertTrue(scripted.confirm("Delete?", typed="no"))
        texts = [e["text"] for e in scripted.events]
        self.assertEqual(
            texts[:4],
            ["Go? [y/N]: ", "Answer yes or no: maybe", *["Go? [y/N]: "] * 2],
        )
        self.assertEqual(scripted.events[0]["default"], "n")
        self.assertEqual(scripted.events[1]["level"], "error")
        self.assertEqual(scripted.events[4]["kind"], "typed")
        scripted = port.ScriptedPort(["4", "2", "1, 3"])
        options = ["alpha", "beta", "gamma"]
        self.assertEqual(scripted.choose("Which?", options), "beta")
        self.assertEqual(
            scripted.choose("Which?", options, multi=True), ["alpha", "gamma"]
        )
        single, refused, again, multi = scripted.events
        self.assertEqual(
            (single["t"], single["kind"], single["multi"], multi["multi"]),
            ("ask", "choose", False, True),
        )
        self.assertEqual(
            single["text"],
            "Which?\n[1] alpha\n[2] beta\n[3] gamma\n[0] 🔙 Back\n: ",
        )
        self.assertEqual(single["speak"], "Which?")
        self.assertEqual(
            [(o["key"], o["label"], o["speak"]) for o in single["options"]],
            [
                ("1", "alpha", "alpha"),
                ("2", "beta", "beta"),
                ("3", "gamma", "gamma"),
                ("0", "🔙 Back", "Back"),
            ],
        )
        self.assertEqual(refused["text"], "Invalid choice: 4")
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
        answers = ["absent.zip", "forged_dir", "../forged.zip", " "]
        scripted = port.ScriptedPort(
            [*answers, EOFError(), "forged.zip", "~/forged_dir", ".."]
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
            # Un répertoire refusé pour un fichier : la question revient
            # sur lui.
            [("path", base, False)] * 2
            + [("path", folder, False), ("path", base, False)]
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

    def test_a_path_is_read_as_typed_then_without_its_blanks(self):
        # Des blancs tapés autour d'un chemin ne le font pas refuser ; un
        # nom qui finit vraiment par une espace reste le sien.
        base = _forged_dir(self)
        Path(base, "forged.zip ").touch()
        scripted = port.ScriptedPort([" forged.zip\t", "forged.zip "])
        with ui.bind(scripted):
            trimmed = ui.pick_path(base)
            spaced = ui.pick_path(base)
        self.assertEqual(trimmed, os.path.join(base, "forged.zip"))
        self.assertEqual(spaced, os.path.join(base, "forged.zip "))
        self.assertFalse(
            [e for e in scripted.events if e["t"] == "notice"], "no re-ask"
        )

    def test_a_refused_path_is_asked_again_from_its_folder(self):
        # Un chemin refusé fait revenir la question sur le plus proche
        # répertoire existant qui le contient, où le sélecteur rouvre ;
        # un chemin relatif en part alors. Un répertoire donné pour un
        # fichier la fait revenir sur lui-même, où l'utilisateur est allé.
        _english(self)
        base = _forged_dir(self)
        folder = os.path.join(base, "forged_dir")
        inner = os.path.join(folder, "inner")
        os.mkdir(inner)
        Path(folder, "inner.zip").touch()
        answers = ["forged_dir/absent.zip", "gone/deeper/x.zip", "inner"]
        scripted = port.ScriptedPort([*answers, "../inner.zip"])
        with ui.bind(scripted):
            chosen = ui.pick_path(base)
        self.assertEqual(chosen, os.path.join(folder, "inner.zip"))
        asked = [e["start"] for e in scripted.events if e["t"] == "ask"]
        self.assertEqual(asked, [base, folder, folder, inner])
        self.assertEqual(
            [e["text"] for e in scripted.events if e["t"] == "notice"],
            [
                f"No such file: {folder}/absent.zip",
                f"No such file: {folder}/gone/deeper/x.zip",
                f"Not a file: {inner}",
            ],
        )

    def test_a_file_or_a_broken_link_refused_asks_again_from_its_folder(self):
        # Un fichier donné pour un répertoire fait revenir la question sur
        # son répertoire ; un lien dont la cible manque n'est ni un fichier
        # ni un répertoire, et se dit absent.
        _english(self)
        base = _forged_dir(self)
        folder = os.path.join(base, "forged_dir")
        Path(folder, "inner.zip").touch()
        os.symlink(os.path.join(base, "forged_absent"), f"{folder}/link")
        answers = ["forged_dir/inner.zip", "link", EOFError()]
        scripted = port.ScriptedPort(
            [*answers, "forged_dir/link", "inner.zip"]
        )
        with ui.bind(scripted):
            cancelled = ui.pick_path(base, directory=True)
            chosen = ui.pick_path(base)
        self.assertEqual(
            (cancelled, chosen), (None, os.path.join(folder, "inner.zip"))
        )
        asked = [e["start"] for e in scripted.events if e["t"] == "ask"]
        self.assertEqual(asked, [base, folder, folder, base, folder])
        self.assertEqual(
            [e["text"] for e in scripted.events if e["t"] == "notice"],
            [
                f"Not a directory: {folder}/inner.zip",
                f"No such directory: {folder}/link",
                f"No such file: {folder}/link",
            ],
        )

    def test_a_refusal_names_the_answer_as_typed_when_it_exists(self):
        # Un nom qui finit vraiment par une espace existe, mais pas du genre
        # demandé : le refus le nomme tel quel, et la question revient sur
        # lui s'il est un répertoire, sinon sur le sien, et non sur le nom
        # sans ses blancs, qui n'existe pas.
        _english(self)
        base = _forged_dir(self)
        folder = os.path.join(base, "forged_dir")
        spaced = os.path.join(folder, "spaced ")
        os.mkdir(spaced)
        Path(folder, "spaced.zip ").touch()
        scripted = port.ScriptedPort(
            ["forged_dir/spaced ", EOFError(), "forged_dir/spaced.zip "]
            + [EOFError()]
        )
        with ui.bind(scripted):
            self.assertIsNone(ui.pick_path(base))
            self.assertIsNone(ui.pick_path(base, directory=True))
        asked = [e["start"] for e in scripted.events if e["t"] == "ask"]
        self.assertEqual(asked, [base, spaced, base, folder])
        self.assertEqual(
            [e["text"] for e in scripted.events if e["t"] == "notice"],
            [
                f"Not a file: {spaced}",
                f"Not a directory: {folder}/spaced.zip ",
            ],
        )


class TestChoose(unittest.TestCase):
    """Les règles d'un choix, les mêmes à chaque sélecteur de TODO : un
    numéro tel qu'affiché ou le nom exact d'une option, [0] Retour, une
    réponse vide qui prend le défaut et jamais tout, « tout » et les
    plages en choix multiple seulement, une réponse invalide dite puis la
    question reposée, Ctrl+D qui revient."""

    def setUp(self):
        _english(self)

    def chosen(self, answers, *args, **rules):
        """(ce que rend le choix, les événements du port) quand il reçoit
        `answers`, puis Ctrl+D."""
        scripted = port.ScriptedPort(answers)
        return scripted.choose(*args, **rules), scripted.events

    def refusals(self, events) -> list:
        return [e["text"] for e in events if e["t"] == "notice"]

    def test_the_list_shows_numbers_letters_the_default_and_back(self):
        _, [asked] = self.chosen(
            [],
            "Which browser?",
            ["w3m", "lynx"],
            default="lynx",
            letters={"i": "Install another"},
        )
        self.assertEqual(
            asked["text"],
            "Which browser?\n[1] w3m\n[2] lynx (default)\n"
            "[i] Install another\n[0] 🔙 Back\n: ",
        )
        self.assertEqual(
            [o["key"] for o in asked["options"]], ["1", "2", "i", "0"]
        )
        # La page lit la question sans ses entrées, et les noms qu'elle
        # peut taper.
        self.assertEqual(
            (asked["prompt"], asked["default"], asked["names"]),
            ("Which browser?", "2", {"w3m": "1", "lynx": "2"}),
        )
        # Sur un libellé de plusieurs lignes, la marque suit la première.
        _, [asked] = self.chosen(
            [], "Mode?", ["a", "b"], default="b", labels=["a", "b\n    more"]
        )
        self.assertEqual(asked["options"][1]["label"], "b (default)\n    more")
        _, [several] = self.chosen([], "Which?", ["a"], multi=True)
        self.assertEqual(
            several["text"],
            "Which?\n[1] a\n[0] 🔙 Back\n"
            "Several: 1 3, 2-5 or all; empty for none: ",
        )

    def test_a_number_is_taken_only_as_the_list_shows_it(self):
        # « 01 », « +1 », « ١ » (un en écriture arabe), « ² », « -1 » et
        # « 1.0 » ne sont pas le numéro affiché : chacun est dit invalide,
        # puis la même question revient, à laquelle « 2 » répond.
        for answer in ("01", "+1", "١", "²", "-1", "1.0", "3"):
            with self.subTest(answer=answer):
                chosen, events = self.chosen(
                    [answer, " 2 "], "Which?", ["alpha", "beta"]
                )
                self.assertEqual(chosen, "beta")
                self.assertEqual(
                    self.refusals(events), [f"Invalid choice: {answer}"]
                )
                self.assertEqual(events[0], events[2])

    def test_an_option_that_is_a_string_is_also_chosen_by_its_exact_name(
        self,
    ):
        chosen, _ = self.chosen(["beta"], "Which?", ["alpha", "beta"])
        self.assertEqual(chosen, "beta")
        chosen, events = self.chosen(
            ["Beta", "beta "], "Which?", ["alpha", "beta"]
        )
        self.assertEqual(
            (chosen, self.refusals(events)), ("beta", ["Invalid choice: Beta"])
        )
        # Une option qui n'est pas une chaîne n'a que son numéro ; son
        # libellé n'est pas un nom.
        chosen, events = self.chosen(
            ["two", "2"], "Which?", [1, 2], labels=["one", "two"]
        )
        self.assertEqual((chosen, len(self.refusals(events))), (2, 1))

    def test_under_labels_only_a_declared_name_chooses(self):
        # Sous des libellés, le code d'une option, que la liste ne montre
        # pas, n'est pas un nom ; seul un nom de `names` en est un.
        rules = {"labels": ["Shown A", "Shown B"]}
        chosen, events = self.chosen(
            ["code_a", "Shown A", "1"], "?", ["code_a", "code_b"], **rules
        )
        self.assertEqual(chosen, "code_a")
        self.assertEqual(
            self.refusals(events),
            ["Invalid choice: code_a", "Invalid choice: Shown A"],
        )
        rules["names"] = {"Shown B": "code_b"}
        chosen, events = self.chosen(
            ["Shown B"], "?", ["code_a", "code_b"], **rules
        )
        self.assertEqual((chosen, self.refusals(events)), ("code_b", []))
        self.assertEqual(events[0]["names"], {"Shown B": "2"})

    def test_an_answer_read_two_ways_is_invalid(self):
        # Le nom d'une option qui est le numéro d'une autre, ou un mot de
        # tout : dit invalide plutôt que deviné. Un nom qui est le numéro de
        # sa propre option n'a qu'une lecture ; un nom qu'une lettre lirait
        # est refusé avant la question.
        cases = [
            (["2", "1"], (["2", "b"],), {}, "2"),
            (["all", "1"], (["all", "b"], True), {}, ["all"]),
        ]
        for answers, args, rules, expected in cases:
            with self.subTest(answers=answers):
                chosen, events = self.chosen(answers, "?", *args, **rules)
                self.assertEqual(chosen, expected)
                self.assertEqual(
                    self.refusals(events), [f"Invalid choice: {answers[0]}"]
                )
        self.assertEqual(self.chosen(["2"], "?", ["a", "2"])[0], "2")

    def test_zero_and_ctrl_d_go_back_and_ctrl_c_interrupts(self):
        self.assertEqual(self.chosen(["0"], "Which?", ["a"])[0], None)
        self.assertEqual(self.chosen(["0"], "Which?", ["a"], True)[0], None)
        self.assertEqual(
            self.chosen([], "Which?", ["a"], default="a")[0], None
        )
        self.assertEqual(self.chosen([], "Which?", ["a"], True)[0], None)
        with self.assertRaises(KeyboardInterrupt):
            self.chosen([KeyboardInterrupt()], "Which?", ["a"])

    def test_a_blank_answer_takes_the_default_or_goes_back_never_all(self):
        for blank in ("", "  \t"):
            with self.subTest(blank=blank):
                chosen, _ = self.chosen([blank], "?", ["a", "b"], default="b")
                self.assertEqual(chosen, "b")
                self.assertIsNone(self.chosen([blank], "?", ["a", "b"])[0])
                chosen, _ = self.chosen([blank], "?", ["a", "b"], multi=True)
                self.assertEqual(chosen, [])

    def test_all_ranges_and_separators_only_in_a_multiple_choice(self):
        options = ["a", "b", "c", "d"]
        cases = {
            "tout": options,
            "ALL": options,
            "*": options,
            "2-3": ["b", "c"],
            "4,1": ["a", "d"],
            "3, 1 1": ["a", "c"],
            "d b": ["b", "d"],
            "1-1 all": options,
        }
        for answer, expected in cases.items():
            with self.subTest(answer=answer):
                chosen, _ = self.chosen([answer], "?", options, multi=True)
                self.assertEqual(chosen, expected)
        # Une plage à l'envers ou hors de la liste, un « ; », « 0 » avec
        # d'autres réponses, ou un seul morceau faux refusent tout.
        for answer in ("3-2", "2-5", "1;3", "0 1", "1 x", "01-2"):
            with self.subTest(answer=answer):
                chosen, events = self.chosen(
                    [answer, "1"], "?", options, multi=True
                )
                self.assertEqual(chosen, ["a"])
                self.assertEqual(
                    self.refusals(events), [f"Invalid choice: {answer}"]
                )
        # Dans un choix simple, « tout » et une plage sont invalides.
        for answer in ("tout", "*", "1-2", "1 2"):
            with self.subTest(single=answer):
                chosen, events = self.chosen([answer, "2"], "?", options)
                self.assertEqual((chosen, len(events)), ("b", 3))

    def test_a_range_bound_that_is_no_shown_number_is_invalid(self):
        # Une borne de 5000 chiffres passe la limite de conversion d'`int`
        # (4300 chiffres) : n'étant pas un numéro affiché, elle rend la
        # réponse invalide, et le choix ne lève pas.
        huge = "1" * 5000
        for answer in (f"{huge}-2", f"1-{huge}"):
            with self.subTest(bound=answer.index("-")):
                chosen, events = self.chosen(
                    [answer, "1"], "?", ["a", "b"], multi=True
                )
                self.assertEqual(chosen, ["a"])
                self.assertEqual(
                    self.refusals(events), [f"Invalid choice: {answer}"]
                )

    def test_a_letter_answers_in_either_case_and_comes_back(self):
        for answer in ("i", "I", " i "):
            with self.subTest(answer=answer):
                chosen, _ = self.chosen(
                    [answer], "?", ["w3m"], letters={"i": "Install"}
                )
                self.assertEqual(chosen, "i")

    def test_a_letter_can_be_the_default(self):
        # Une action à lettre suit les règles d'une option : défaut, elle
        # est marquée, et une réponse vide la rend.
        rules = {"default": "c", "letters": {"c": "Continue"}}
        chosen, [asked] = self.chosen([""], "?", ["a"], **rules)
        self.assertEqual(chosen, "c")
        self.assertEqual(
            asked["text"], "?\n[1] a\n[c] Continue (default)\n[0] 🔙 Back\n: "
        )

    def test_a_letter_in_a_multiple_choice_answers_alone(self):
        # Une action à lettre suit aussi les numéros d'un choix multiple :
        # tapée seule, elle rend sa lettre ; mêlée à un numéro, à une autre
        # lettre ou à « tout », la réponse est dite invalide.
        rules = {"multi": True, "letters": {"p": "Main", "g": "Exact"}}
        _, [asked] = self.chosen([], "Which?", ["a", "b"], **rules)
        self.assertEqual(
            asked["text"],
            "Which?\n[1] a\n[2] b\n[p] Main\n[g] Exact\n[0] 🔙 Back\n"
            "Several: 1 3, 2-5 or all; empty for none: ",
        )
        for answer in ("p", "G", " p ", "p,p"):
            with self.subTest(answer=answer):
                chosen, _ = self.chosen([answer], "?", ["a", "b"], **rules)
                self.assertEqual(chosen, answer.strip()[0].lower())
        for answer in ("1 p", "p,g", "p tout", "p-g", "0 p"):
            with self.subTest(answer=answer):
                chosen, events = self.chosen(
                    [answer, "2"], "?", ["a", "b"], **rules
                )
                self.assertEqual(chosen, ["b"])
                self.assertEqual(
                    self.refusals(events), [f"Invalid choice: {answer}"]
                )
        chosen, _ = self.chosen(["tout"], "?", ["a", "b"], **rules)
        self.assertEqual(chosen, ["a", "b"])
        self.assertEqual(self.chosen([""], "?", ["a"], **rules)[0], [])

    def test_rules_that_contradict_each_other_are_refused_before_asking(
        self,
    ):
        scripted = port.ScriptedPort(["1"])
        with self.assertRaises(ValueError):
            scripted.choose("?", ["a"], multi=True, default="a")
        with self.assertRaises(ValueError):
            scripted.choose("?", ["a"], default="z")
        # Une lettre qui ne se tape pas telle quelle, qui se lit comme un
        # numéro ou comme le retour ; un libellé de trop ; un nom sans
        # option.
        for letter in ("R", "5", "0", "", "i j"):
            with self.subTest(letter=letter):
                with self.assertRaises(ValueError):
                    scripted.choose("?", ["a"], letters={letter: "x"})
        with self.assertRaises(ValueError):
            scripted.choose("?", ["a"], labels=["a", "b"])
        with self.assertRaises(ValueError):
            scripted.choose("?", ["a"], names={"b": "b"})
        self.assertEqual(scripted.events, [])

    def test_an_option_or_a_name_read_as_a_letter_is_refused(self):
        # Choisie par son numéro, une option égale à une lettre se rendrait
        # comme la lettre : l'appelant ne saurait laquelle on a voulue. Un
        # nom qu'une lettre lit à sa place, sans casse, ne se taperait pas :
        # « R », son propre nom, ou déclaré. Refusés avant la question. Sous
        # un libellé, « R » n'est pas un nom, se rend autrement, et passe.
        scripted = port.ScriptedPort(["1"])
        for args, names in (
            ((["r"],), None),
            ((["a", "r"], True), None),
            ((["R"],), None),
            ((["x"],), {"R": "x"}),
        ):
            with self.subTest(args=args, names=names):
                with self.assertRaises(ValueError):
                    scripted.choose(
                        "?", *args, letters={"r": "Reset"}, names=names
                    )
        self.assertEqual(scripted.events, [])
        chosen, _ = self.chosen(
            ["1"], "?", ["R"], labels=["Reset R"], letters={"r": "Reset"}
        )
        self.assertEqual(chosen, "R")

    def test_the_facade_passes_every_rule_to_the_bound_port(self):
        scripted = port.ScriptedPort(["", "one"])
        rules = {"labels": ["one", "two"], "letters": {}, "names": {"one": 1}}
        with ui.bind(scripted):
            self.assertEqual(ui.choose("?", [1, 2], default=2, **rules), 2)
            self.assertEqual(ui.choose("?", [1, 2], default=2, **rules), 1)


class TestConfirm(unittest.TestCase):
    """Les règles B d'une question oui/non, les mêmes à chaque question de
    TODO : o, oui, y, yes et n, non, no dans les deux langues, sans casse ;
    l'indice du défaut dans la langue choisie, que le port ajoute ; une
    réponse vide qui prend le défaut ; une faute dite, puis la même
    question ; Ctrl+D qui vaut non, None avec `back`, le défaut au compte
    à rebours ; Ctrl+C qui passe."""

    def setUp(self):
        _english(self)

    def confirmed(self, answers, *args, **rules):
        """(ce que rend la question, les événements du port) quand elle
        reçoit `answers`, puis Ctrl+D."""
        scripted = port.ScriptedPort(answers)
        return scripted.confirm(*args, **rules), scripted.events

    def test_yes_and_no_in_either_language_and_any_case(self):
        yes = ("o", "oui", "y", "yes", "OUI", "Yes", " o ", "O\t")
        no = ("n", "non", "no", "NON", "No", " n ")
        for lang in ("fr", "en"):
            todo_i18n.use_lang(lang)
            for answer in yes + no:
                for default in (True, False):
                    with self.subTest(
                        lang=lang, answer=answer, default=default
                    ):
                        got, events = self.confirmed([answer], "Go?", default)
                        self.assertIs(got, answer in yes)
                        self.assertEqual(len(events), 1)

    def test_the_port_shows_the_hint_of_the_language_and_default(self):
        cases = [
            ("fr", "Go ?", True, "Go ? [O/n] : ", "y"),
            ("fr", "Go ?", False, "Go ? [o/N] : ", "n"),
            ("en", "Go?", True, "Go? [Y/n]: ", "y"),
            ("en", "Go?", False, "Go? [y/N]: ", "n"),
        ]
        for lang, text, default, shown, value in cases:
            with self.subTest(lang=lang, default=default):
                todo_i18n.use_lang(lang)
                _, [asked] = self.confirmed([""], text, default)
                self.assertEqual(
                    (asked["t"], asked["kind"], asked["text"]),
                    ("ask", "confirm", shown),
                )
                # La page et la voix lisent la question sans son indice.
                self.assertEqual(
                    (asked["prompt"], asked["speak"], asked["default"]),
                    (text, text, value),
                )
                self.assertEqual(asked["requires"], [])
                self.assertNotIn("timeout_s", asked)
                self.assertNotIn("back", asked)

    def test_every_question_states_its_default(self):
        # Refusé avant la question : un défaut qui n'est pas un booléen,
        # qu'une valeur de protocole ou un entier ferait lire à l'envers.
        scripted = port.ScriptedPort(["y"])
        for default in (None, "n", "y", 0, 1):
            with self.subTest(default=default):
                with self.assertRaises(ValueError):
                    scripted.confirm("Go?", default)
        with self.assertRaises(ValueError):
            scripted.confirm("Go?")
        with self.assertRaises(ValueError):
            scripted.confirm("Type forged:", typed="forged", timeout=5)
        self.assertEqual(scripted.events, [])

    def test_a_blank_answer_takes_the_default_both_ways(self):
        for blank in ("", "  \t"):
            for default in (True, False):
                with self.subTest(blank=blank, default=default):
                    got, events = self.confirmed([blank], "Go?", default)
                    self.assertIs(got, default)
                    self.assertEqual(len(events), 1)

    def test_an_invalid_answer_says_so_and_asks_again(self):
        for answer in ("maybe", "1", "oui non", "yy", "0"):
            with self.subTest(answer=answer):
                got, events = self.confirmed([answer, "n"], "Go?", True)
                self.assertIs(got, False)
                asked, refused, again = events
                self.assertEqual(
                    refused,
                    {
                        "t": "notice",
                        "text": f"Answer yes or no: {answer}",
                        "level": "error",
                    },
                )
                self.assertEqual(again, asked)
        todo_i18n.use_lang("fr")
        _, events = self.confirmed([" peut-être ", "o"], "Go ?", False)
        self.assertEqual(
            events[1]["text"], "Répondez o/oui ou n/non : peut-être"
        )

    def test_ctrl_d_is_no_even_when_the_default_is_yes(self):
        # Ctrl+D au terminal, Annuler de la page, un port scripté épuisé ;
        # après une faute aussi. Ctrl+C passe.
        cases = (([EOFError()], 1), ([], 1), (["maybe", EOFError()], 3))
        for answers, asked in cases:
            for default in (True, False):
                with self.subTest(answers=answers, default=default):
                    got, events = self.confirmed(answers, "Go?", default)
                    self.assertIs(got, False)
                    self.assertEqual(len(events), asked)
        with self.assertRaises(KeyboardInterrupt):
            self.confirmed([KeyboardInterrupt()], "Go?", False)

    def test_ctrl_d_with_back_is_none(self):
        for default in (True, False):
            with self.subTest(default=default):
                got, [asked] = self.confirmed(
                    [EOFError()], "Go?", default, back=True
                )
                self.assertIsNone(got)
                self.assertIs(asked["back"], True)
        # Elle répond oui et non comme toute autre.
        self.assertIs(self.confirmed(["o"], "Go?", False, back=True)[0], True)
        self.assertIs(self.confirmed([""], "Go?", False, back=True)[0], False)

    def test_a_countdown_takes_the_default_at_its_end(self):
        _, [asked] = self.confirmed(["y"], "Go?", False, timeout=5)
        self.assertEqual(
            (asked["kind"], asked["timeout_s"], asked["default"]),
            ("confirm", 5, "n"),
        )
        # Ctrl+D au compte à rebours vaut Entrée, `back` compris.
        for default in (True, False):
            for back in (False, True):
                with self.subTest(default=default, back=back):
                    got, _ = self.confirmed(
                        [EOFError()], "Go?", default, timeout=5, back=back
                    )
                    self.assertIs(got, default)
        calls = []

        def deadline(text, default, seconds):
            calls.append((text, default, seconds))
            return default

        def closed(text, default, seconds):
            # Un stdin fermé, en mode automatique, rend une ligne vide.
            return ""

        for countdown in (deadline, closed):
            for default in (True, False):
                with (
                    self.subTest(
                        countdown=countdown.__name__, default=default
                    ),
                    patch.dict(port.ORIGINAL, {"auto_ask.ask": countdown}),
                    redirect_stdout(io.StringIO()),
                ):
                    got = port.TerminalPort().confirm(
                        "Go?", default, timeout=5
                    )
                    self.assertIs(got, default)
        # Le défaut passe au compte à rebours dans la langue choisie : c'est
        # lui que l'échéance affiche.
        self.assertEqual(
            calls, [("Go? [Y/n]: ", "Yes", 5), ("Go? [y/N]: ", "No", 5)]
        )
        todo_i18n.use_lang("fr")
        with (
            patch.dict(port.ORIGINAL, {"auto_ask.ask": deadline}),
            redirect_stdout(io.StringIO()),
        ):
            got = port.TerminalPort().confirm("Go ?", True, timeout=5)
        self.assertIs(got, True)
        self.assertEqual(calls[-1], ("Go ? [O/n] : ", "Oui", 5))

    def test_a_letter_answers_with_itself(self):
        letters = {"b": "go back a step", "t": "see the state"}
        for answer, want in (
            ("b", "b"),
            (" T ", "t"),
            ("o", True),
            ("", False),
        ):
            with self.subTest(answer=answer):
                got, events = self.confirmed(
                    [answer], "Go?", False, letters=letters
                )
                self.assertEqual((repr(got), len(events)), (repr(want), 1))
        _, [asked] = self.confirmed(["b"], "Go?", True, letters=letters)
        self.assertEqual(
            asked["options"],
            [{"key": k, "label": v, "speak": v} for k, v in letters.items()],
        )
        # Une lettre parmi d'autres mots est une faute ; Ctrl+D, `back` et
        # l'échéance gardent leur règle.
        got, events = self.confirmed(
            ["b t", "t"], "Go?", True, letters=letters
        )
        self.assertEqual(
            (got, events[1]["level"], len(events)), ("t", "error", 3)
        )
        self.assertIs(
            self.confirmed([], "Go?", True, letters=letters)[0], False
        )
        back = self.confirmed([], "Go?", True, back=True, letters=letters)
        self.assertIsNone(back[0])
        late = self.confirmed(
            [EOFError()], "Go?", True, timeout=5, letters=letters
        )
        self.assertIs(late[0], True)

    def test_a_letter_that_is_yes_or_no_is_refused_before_asking(self):
        scripted = port.ScriptedPort(["b"])
        for letter in ("y", "o", "n", "yes", "oui", "no", "non", "B", "1", ""):
            with self.subTest(letter=letter):
                with self.assertRaises(ValueError):
                    scripted.confirm("Go?", True, letters={letter: "Act"})
        with self.assertRaises(ValueError):
            scripted.confirm(
                "Type forged:", typed="forged", letters={"b": "Act"}
            )
        self.assertEqual(scripted.events, [])

    def test_letters_are_listed_after_the_hint(self):
        cases = [
            (
                "fr",
                True,
                {"b": "revenir d'une étape", "t": "voir l'état"},
                "Go ? [O/n, b = revenir d'une étape, t = voir l'état] : ",
            ),
            ("en", False, {"v": "view it"}, "Go ? [y/N, v = view it]: "),
        ]
        for lang, default, letters, shown in cases:
            with self.subTest(lang=lang):
                todo_i18n.use_lang(lang)
                _, [asked] = self.confirmed(
                    [""], "Go ?", default, letters=letters
                )
                self.assertEqual(asked["text"], shown)
                self.assertEqual(
                    (asked["prompt"], asked["speak"]), ("Go ?",) * 2
                )
        texts = []

        def fake_input(prompt):
            # Une seule réponse, puis Ctrl+D : une lettre que le port ne
            # reconnaît plus finit la question au lieu de la reposer.
            texts.append(prompt)
            if len(texts) > 1:
                raise EOFError
            return "V"

        with patch.dict(port.ORIGINAL, input=fake_input):
            got = port.TerminalPort().confirm(
                "Go ?", False, letters={"v": "view it"}
            )
        self.assertEqual((got, texts), ("v", ["Go ? [y/N, v = view it]: "]))

    def test_the_terminal_prints_the_screen_and_asks_the_last_line(self):
        # Ce que la question efface s'imprime au-dessus d'elle ; `input`
        # ne reçoit que la dernière ligne, l'indice compris. Un double
        # d'`input` posé par un test y répond aussi.
        text = "Deleted:\n  forged_yesno_db\nDelete them?"
        texts = []

        def fake_input(prompt):
            texts.append(prompt)
            return "oui"

        out = io.StringIO()
        with patch.dict(port.ORIGINAL, input=fake_input), redirect_stdout(out):
            self.assertIs(port.TerminalPort().confirm(text, False), True)
        self.assertEqual(texts, ["Delete them? [y/N]: "])
        self.assertEqual(out.getvalue(), "Deleted:\n  forged_yesno_db\n")
        self.assertNotIn("input", port.ORIGINAL)
        with (
            patch("builtins.input", return_value="n") as typed,
            redirect_stdout(io.StringIO()),
        ):
            self.assertIs(port.TerminalPort().confirm(text, True), False)
        typed.assert_called_once_with("Delete them? [Y/n]: ")
        _, [asked] = self.confirmed([""], text, False)
        self.assertEqual(asked["prompt"], text)
        self.assertEqual(asked["speak"], "Delete them?")


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
