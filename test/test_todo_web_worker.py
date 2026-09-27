#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le worker d'une session web.

`serve`, `run_inline`, `track_crumbs` et `restart` sont vérifiés sur des
doubles, sans TODO. Un seul test lance le vrai worker, donc le vrai TODO,
par une session du hub : HOME et XDG_RUNTIME_DIR temporaires, la langue
passée par `hello`, SIGINT ignoré chez le parent comme sous un lanceur en
arrière-plan.
"""

import asyncio
import io
import signal
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from todo_web_env import private_env

from script.todo import todo_i18n
from script.todo.web import sessions, worker

REPO = Path(__file__).resolve().parent.parent


class Abort(Exception):
    """Double de click.exceptions.Abort."""


class FakeTodo:
    """Double de TODO : chaque `run()` lève l'étape suivante, ou rend."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.runs = 0

    def run(self):
        self.runs += 1
        step = self.steps.pop(0)
        if step is not None:
            raise step


def serve(todo, where=lambda: None):
    out = io.StringIO()
    with redirect_stdout(out):
        code = worker.serve(todo, (KeyboardInterrupt, EOFError, Abort), where)
    return code, out.getvalue()


class TestServe(unittest.TestCase):
    def test_quit_ends_with_zero(self):
        self.assertEqual(serve(FakeTodo(None))[0], 0)

    def test_system_exit_ends_with_its_code(self):
        for code, expected in ((4, 4), (None, 0), ("bye-marker", 1)):
            result, out = serve(FakeTodo(SystemExit(code)))
            self.assertEqual(result, expected, code)
        self.assertIn("bye-marker", out)

    def test_ctrl_c_ctrl_d_and_abort_come_back_to_the_main_menu(self):
        todo = FakeTodo(KeyboardInterrupt(), EOFError(), Abort(), None)
        self.assertEqual(serve(todo)[0], 0)
        self.assertEqual(todo.runs, 4)

    def test_a_crash_shows_the_end_of_its_trace_and_comes_back(self):
        todo = FakeTodo(ValueError("boom-marker"), None)
        code, out = serve(todo)
        self.assertEqual((code, todo.runs), (0, 2))
        self.assertIn("ValueError: boom-marker", out)
        self.assertLessEqual(len(out.splitlines()), worker.TRACE_TAIL)

    def test_three_crashes_at_the_same_crumbs_end_the_session(self):
        todo = FakeTodo(*[ValueError("boom")] * 3, None)
        code, _ = serve(todo, lambda: "📍 TODO › Execute")
        self.assertEqual((code, todo.runs), (worker.CRASHED, 3))

    def test_elsewhere_or_after_an_interrupt_the_count_starts_over(self):
        crumbs = iter(["📍 A", "📍 A", "📍 B", "📍 B", "📍 B"])
        boom = ValueError("boom")
        todo = FakeTodo(
            boom, boom, boom, boom, KeyboardInterrupt(), boom, None
        )
        self.assertEqual(serve(todo, lambda: next(crumbs))[0], 0)
        self.assertEqual(todo.runs, 7)

    def test_restart_script_ends_the_worker_with_restart(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            worker.restart("forged")
        self.assertEqual(ctx.exception.code, worker.RESTART)
        self.assertEqual(out.getvalue(), "Reboot TODO ...\n")


class TestHooks(unittest.TestCase):
    def test_every_execute_runs_inline_with_job_control(self):
        class Execute:
            job_control = False

            def __init__(self):
                self.cmd_source_erplibre = "gnome-terminal -- bash -c '%s'"
                self.cmd_source_default = "gnome-terminal -- bash -c '%s'"

        module = types.SimpleNamespace(Execute=Execute)
        worker.run_inline(module, ".venv.forged")
        exe = module.Execute()
        self.assertEqual(
            exe.cmd_source_erplibre, "source ./.venv.forged/bin/activate;%s"
        )
        self.assertEqual(exe.cmd_source_default, "")
        self.assertIs(exe.job_control, True)

    def test_signals_ignored_by_the_launcher_are_restored(self):
        for sig in (*worker.SIGNALS, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
            signal.signal(sig, signal.SIG_IGN)
        worker.restore_signals()
        for sig in worker.SIGNALS:
            self.assertIs(signal.getsignal(sig), signal.SIG_DFL)
        handler = signal.getsignal(signal.SIGINT)
        self.assertIs(handler, signal.default_int_handler)

    def test_the_crumbs_are_the_first_line_of_the_last_header(self):
        class Todo:
            def _menu_header(self, state=None):
                return f"📍 TODO › Execute\n{state}\nCommand:"

        where = worker.track_crumbs(Todo)
        self.assertIsNone(where())
        header = Todo()._menu_header(state="forged")
        self.assertEqual(header, "📍 TODO › Execute\nforged\nCommand:")
        self.assertEqual(where(), "📍 TODO › Execute")


class TestRealWorker(unittest.IsolatedAsyncioTestCase):
    async def shown(self, session, prompt, count):
        """Attend la `count`-ième apparition de `prompt` dans la sortie."""
        deadline = time.monotonic() + 20
        while session.ring.data.count(prompt) < count:
            if session.ended.is_set() or time.monotonic() > deadline:
                tail = bytes(session.ring.data[-600:])
                self.fail(f"{prompt!r} × {count} not seen: {tail!r}")
            await asyncio.sleep(0.02)

    async def test_the_real_todo_answers_zero_and_ends_with_zero(self):
        private_env(self.addCleanup)
        # Un SIGINT ignoré s'hérite : le worker doit rétablir le sien.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        started = time.monotonic()
        session = sessions.Session("w1", str(REPO), "en", 100, 40)
        await session.start()
        self.addAsyncCleanup(session.close)
        main_menu = "[0] 🚪 Quit\r\n: ".encode()
        await self.shown(session, main_menu, 1)
        # Ctrl+C à un sous-menu, sans commande : retour au menu principal.
        # Arrêter, lui, n'y fait rien : TODO n'a rien lancé.
        session.write(b"1\n")
        await self.shown(session, "[0] 🔙 Back\r\n: ".encode(), 1)
        self.assertFalse(session.interrupt())
        session.write(b"\x03")
        await self.shown(session, main_menu, 2)
        session.write(b"0\n")
        await asyncio.wait_for(session.ended.wait(), 20)
        self.assertEqual(session.code, 0)
        text = session.ring.data.decode()
        self.assertIn("Opening TODO ...", text)
        self.assertNotIn("Ouverture de TODO", text)
        self.assertLess(time.monotonic() - started, 10)


if __name__ == "__main__":
    unittest.main()
