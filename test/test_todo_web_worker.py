#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le worker d'une session web et son port.

`serve`, `run_inline`, `track_crumbs` et `restart` sont vérifiés sur des
doubles, sans TODO. `read_hello` et `main` lisent une socketpair ; `main`
s'arrête avant TODO, que remplace un double. `open_channel`, qui déplace un
descripteur, tourne dans un `python -c` jetable. PipePort pose ses
questions sur un vrai PTY et une socketpair, le test tenant le rôle du hub
et du clavier. Deux tests lancent le vrai worker, donc le vrai TODO, par
une session du hub : HOME et XDG_RUNTIME_DIR temporaires, la langue passée
par `hello`, SIGINT ignoré chez le parent comme sous un lanceur en
arrière-plan.
"""

import ast
import asyncio
import fcntl
import importlib.abc
import importlib.util
import io
import json
import os
import pty
import signal
import socket
import subprocess
import sys
import termios
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from todo_web_env import private_env

from script.todo import auto_ask, todo_i18n
from script.todo.ui import legacy, pipe_port, port
from script.todo.web import protocol, sessions, worker

REPO = Path(__file__).resolve().parent.parent

# `open_channel` dans un processus à part, qui dit par le canal ce qu'il en
# voit : le descripteur, son héritage, l'environnement, et si le
# descripteur reçu est fermé.
OPEN_CHANNEL = r"""
import json, os
from script.todo.web import worker
received = int(os.environ["TODO_WEB_FD"])
fd = worker.open_channel()
try:
    os.fstat(received)
    closed = False
except OSError:
    closed = True
seen = {
    "fd": fd,
    "inheritable": os.get_inheritable(fd),
    "closed": closed,
    "env": os.environ["TODO_WEB_FD"],
    "pid": os.environ["TODO_WEB_PID"] == str(os.getpid()),
}
os.write(fd, json.dumps(seen).encode() + b"\n")
"""


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

    def test_a_crash_is_a_notice_when_the_port_takes_them(self):
        todo, notices = FakeTodo(ValueError("boom-marker"), None), []
        interrupts = (KeyboardInterrupt, EOFError, Abort)
        code = worker.serve(
            todo, interrupts, lambda: None, lambda *n: notices.append(n)
        )
        self.assertEqual((code, todo.runs), (0, 2))
        [(tail, level)] = notices
        self.assertEqual(level, "error")
        self.assertTrue(tail.endswith("ValueError: boom-marker"), tail)

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
        events = [].append
        worker.run_inline(module, ".venv.forged", events)
        exe = module.Execute()
        self.assertEqual(
            exe.cmd_source_erplibre, "source ./.venv.forged/bin/activate;%s"
        )
        self.assertEqual(exe.cmd_source_default, "")
        self.assertIs(exe.job_control, True)
        self.assertIs(exe.events, events)

    def test_the_configuration_menu_cannot_write_env_var_sh(self):
        module = types.SimpleNamespace(
            lang_is_configured=lambda: False, set_lang=None
        )
        worker.use_web_lang(module)
        self.assertTrue(module.lang_is_configured())
        self.assertIs(module.set_lang, todo_i18n.use_lang)

    def test_signals_ignored_by_the_launcher_are_restored(self):
        for sig in (*worker.SIGNALS, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
            signal.signal(sig, signal.SIG_IGN)
        worker.restore_signals()
        for sig in worker.SIGNALS:
            self.assertIs(signal.getsignal(sig), signal.SIG_DFL)
        handler = signal.getsignal(signal.SIGINT)
        self.assertIs(handler, signal.default_int_handler)

    def test_a_spare_imports_its_libraries_between_channel_and_hello(self):
        # Le canal d'abord : un descripteur qu'une bibliothèque ouvre à son
        # import ne prend pas le fd 3, que `dup2` remplacerait sans un mot.
        order = []

        def open_channel():
            order.append("channel")
            return 3

        def read_hello(fd):
            order.append("hello")
            raise ValueError("no hello on the channel")

        with (
            patch.object(worker, "restore_signals"),
            patch.object(worker.fcntl, "ioctl"),
            patch.object(worker, "preload", lambda: order.append("preload")),
            patch.object(worker, "open_channel", open_channel),
            patch.object(worker, "read_hello", read_hello),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(worker.main(), worker.BAD_HELLO)
        self.assertEqual(order, ["channel", "preload", "hello"])

    def test_a_library_that_fails_is_left_to_todo(self):
        # Absente, ou qui lève à son import : les suivantes s'importent.
        sys.modules.pop("colorsys", None)
        real = worker.importlib.import_module

        def import_module(name):
            if name == "forged_broken_module":
                raise RuntimeError("raised on import")
            return real(name)

        forged = ("forged_missing_module", "forged_broken_module", "colorsys")
        with (
            patch.object(worker, "PRELOAD", forged),
            patch.object(worker.importlib, "import_module", import_module),
        ):
            worker.preload()
        self.assertIn("colorsys", sys.modules)
        self.assertNotIn("forged_missing_module", sys.modules)

    def test_a_spare_preloads_only_what_todo_requires(self):
        # Une bibliothèque que TODO ne demande plus ne reste pas préchargée.
        todo = (REPO / "script" / "todo" / "todo.py").read_text(
            encoding="utf-8"
        )
        [required] = [
            node.value
            for node in ast.parse(todo).body
            if isinstance(node, ast.Assign)
            and ast.unparse(node.targets[0]) == "REQUIRED_MODULES"
        ]
        # REQUIRED_MODULES = ("<noms>".split())
        names = ast.literal_eval(required.func.value).split()
        self.assertLessEqual(set(worker.PRELOAD), set(names))

    def test_the_crumbs_are_the_first_line_of_the_last_header(self):
        class Todo:
            def _menu_header(self, state=None):
                return f"📍 TODO › Execute\n{state}\nCommand:"

        where = worker.track_crumbs(Todo)
        self.assertIsNone(where())
        header = Todo()._menu_header(state="forged")
        self.assertEqual(header, "📍 TODO › Execute\nforged\nCommand:")
        self.assertEqual(where(), "📍 TODO › Execute")


def _channel(test, data) -> int:
    """Descripteur du worker sur une socketpair où le hub a écrit `data`,
    puis fermé son extrémité."""
    hub, end = socket.socketpair()
    test.addCleanup(end.close)
    with hub:
        hub.sendall(data)
    return end.fileno()


class TestHello(unittest.TestCase):
    def test_the_hello_line(self):
        fd = _channel(self, b'{"t": "hello", "lang": "en"}\n')
        self.assertEqual(worker.read_hello(fd), {"t": "hello", "lang": "en"})

    def test_a_channel_closed_before_the_end_of_the_line(self):
        for data in (b"", b'{"t": "hello"'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                worker.read_hello(_channel(self, data))

    def test_a_line_beyond_the_limit(self):
        line = b'{"t": "hello", "lang": "en"' + b" " * 100 + b"}\n"
        with patch.object(worker, "HELLO_LIMIT", len(line) - 1):
            with self.assertRaises(ValueError):
                worker.read_hello(_channel(self, line))
        with patch.object(worker, "HELLO_LIMIT", len(line)):
            self.assertEqual(
                worker.read_hello(_channel(self, line))["t"], "hello"
            )

    def test_anything_but_a_hello_object(self):
        for data in (b"not json\n", b"\xff\n", b"[1]\n", b'{"t": "bye"}\n'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                worker.read_hello(_channel(self, data))


class TestOpenChannel(unittest.TestCase):
    def test_the_channel_moves_to_fd_3_not_inherited(self):
        hub, end = socket.socketpair()
        self.addCleanup(hub.close)
        # Reçu ailleurs que sur 3 : `open_channel` l'y déplace.
        with end:
            received = fcntl.fcntl(end, fcntl.F_DUPFD_CLOEXEC, 10)
        try:
            result = subprocess.run(
                [sys.executable, "-c", OPEN_CHANNEL],
                cwd=REPO,
                env=dict(os.environ, TODO_WEB_FD=str(received)),
                pass_fds=(received,),
                capture_output=True,
                timeout=30,
            )
        finally:
            os.close(received)
        self.assertEqual(result.returncode, 0, result.stderr)
        hub.settimeout(10)
        with hub.makefile("rb") as channel:
            seen = json.loads(channel.readline())
        self.assertEqual(
            seen,
            {
                "fd": worker.CHANNEL_FD,
                "inheritable": False,
                "closed": True,
                "env": str(worker.CHANNEL_FD),
                "pid": True,
            },
        )


class TodoFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Sert `module` à `import todo`, et note l'import dans `order`."""

    def __init__(self, module, order):
        self.module, self.order = module, order

    def find_spec(self, name, path=None, target=None):
        if name != "todo":
            return None
        self.order.append("import todo")
        return importlib.util.spec_from_loader(name, self)

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        pass


class TestMain(unittest.TestCase):
    """`main` jusqu'à TODO exclu : signaux, terminal de contrôle, canal et
    capture sont des doubles ; `todo`, servi par TodoFinder, aussi, comme
    click et urwid dans sys.modules."""

    def main(self, hello, todo=None):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        fd = self.fd = _channel(self, hello)
        modules = {name: types.ModuleType(name) for name in ("click", "urwid")}
        self.order = []
        finder = TodoFinder(todo, self.order)
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(worker, "restore_signals"),
            patch.object(worker, "fcntl"),
            patch.object(worker, "open_channel", return_value=fd),
            patch.object(
                worker.legacy,
                "install",
                lambda port: self.order.append(("install", port.channel)),
            ),
            patch.object(sys, "path", list(sys.path)),
            patch.object(sys, "meta_path", [finder, *sys.meta_path]),
            patch.dict(sys.modules, modules),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            sys.modules.pop("todo", None)
            code = worker.main()
        return code, out.getvalue(), err.getvalue()

    def test_a_bad_hello_ends_with_bad_hello(self):
        for hello in (
            b"",
            b"not json\n",
            b'{"t": "hello"}\n',
            b'{"t": "hello", "lang": "de"}\n',
        ):
            with self.subTest(hello=hello):
                code, out, err = self.main(hello)
                self.assertEqual(code, worker.BAD_HELLO)
                self.assertTrue(err.startswith("todo web worker: "), err)
                self.assertEqual(out, "")

    def test_a_todo_that_cannot_start_ends_with_crashed(self):
        todo = types.ModuleType("todo")
        todo.ENABLE_CRASH, todo.CRASH_E = True, "boom-marker"
        code, out, _ = self.main(b'{"t": "hello", "lang": "en"}\n', todo)
        self.assertEqual(code, worker.CRASHED)
        self.assertEqual(out, "boom-marker\n")
        self.assertEqual(todo_i18n.get_lang(), "en")

    def test_the_capture_is_bound_to_the_channel_before_todo_loads(self):
        todo = types.ModuleType("todo")
        todo.ENABLE_CRASH, todo.CRASH_E = True, "boom-marker"
        self.main(b'{"t": "hello", "lang": "en"}\n', todo)
        [(step, channel), imported] = self.order
        self.assertEqual((step, imported), ("install", "import todo"))
        self.assertEqual(channel, self.fd)


class TestProtocol(unittest.TestCase):
    def test_a_worker_line_always_fits_the_hub(self):
        items = [
            {"key": str(n), "label": "🧰" * 5000, "section": "s" * 5000}
            for n in range(1000)
        ]
        huge = {"t": "menu", "qid": 1, "text": "x" * 10**6 + "Choice: "}
        line = protocol.encode(dict(huge, items=items, crumbs=["c" * 10**6]))
        self.assertLessEqual(len(line), protocol.LINE_LIMIT)
        message = json.loads(line)
        self.assertEqual(len(message["text"]), protocol.TEXT_LIMIT)
        self.assertTrue(message["text"].endswith("xChoice: "))
        self.assertEqual(len(message["items"]), protocol.ITEM_LIMIT)
        self.assertEqual(message["items"][0]["key"], "0")
        small = {"t": "notice", "text": "t" * 100, "level": "info"}
        self.assertEqual(json.loads(protocol.encode(small)), small)
        # Un caractère de contrôle s'écrit en six octets (\u0001) : même
        # coupées, ces listes dépasseraient la borne.
        control = "\x01" * protocol.LABEL_LIMIT
        item = dict.fromkeys(("key", "label", "section", "speak"), control)
        lists = {"items": [item] * 300, "crumbs": [control] * 300}
        line = protocol.encode(dict(huge, **lists, sections=[control] * 300))
        self.assertLessEqual(len(line), protocol.LINE_LIMIT)
        self.assertTrue(json.loads(line)["text"].endswith("xChoice: "))

    def test_a_name_that_is_not_utf_8_never_breaks_the_line(self):
        # Un nom de fichier non UTF-8, tel que os.listdir le rend.
        name = b"backup-\xff.zip".decode(errors="surrogateescape")
        line = protocol.encode({"t": "ask", "qid": 1, "text": f"{name}: "})
        self.assertEqual(json.loads(line)["text"], "backup-?.zip: ")

    def test_the_worker_takes_only_answers_and_cancels(self):
        answer = {"t": "answer", "qid": 2, "value": "ok"}
        self.assertEqual(protocol.reply(json.dumps(answer)), answer)
        cancel = {"t": "cancel", "qid": 2}
        self.assertEqual(protocol.reply(json.dumps(cancel)), cancel)
        for line in (
            b'{"t": "answer", "qid": 2}',
            b'{"t": "answer", "qid": 0, "value": "x"}',
            b'{"t": "answer", "qid": "2", "value": "x"}',
            b'{"t": "hello", "qid": 2, "value": "x"}',
            b"[2]",
            b"not json",
        ):
            self.assertIsNone(protocol.reply(line), line)


class TestPipePort(unittest.TestCase):
    """PipePort sur un vrai PTY (l'esclave pour terminal) et une
    socketpair (le canal) ; la question tourne dans un fil, le test tient
    le rôle du hub et du clavier."""

    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("en")
        self.master, slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, slave)
        self.slave = slave
        self.hub, end = socket.socketpair()
        self.addCleanup(self.hub.close)
        self.addCleanup(end.close)
        self.hub.settimeout(10)
        self.lines = self.hub.makefile("rb")
        self.addCleanup(self.lines.close)
        self.out = io.StringIO()
        self.port = pipe_port.PipePort(end.fileno(), slave, self.out)
        self.pool = ThreadPoolExecutor(1)
        self.addCleanup(self.pool.shutdown)
        # Nettoyé d'abord : une ligne vide au clavier répond à la question
        # qu'un test en échec laisse posée, et le fil finit.
        self.addCleanup(os.write, self.master, b"\n")

    def received(self):
        """Le message suivant que le hub reçoit du port."""
        return json.loads(self.lines.readline())

    def asking(self, method, *args):
        """La question posée dans un fil ; rend son futur et le message
        que le hub en reçoit, le `answered` de la précédente sauté."""
        future = self.pool.submit(method, *args)
        message = self.received()
        while message["t"] == "answered":
            message = self.received()
        return future, message

    def reply(self, **message):
        self.hub.sendall(json.dumps(message).encode() + b"\n")

    def typed(self, data):
        """Écrit `data` au clavier et attend que l'esclave la tienne."""
        os.write(self.master, data)
        deadline = time.monotonic() + 5
        size = bytearray(4)
        while True:
            fcntl.ioctl(self.slave, termios.FIONREAD, size)
            if int.from_bytes(size, sys.byteorder) >= len(data):
                return
            self.assertLess(time.monotonic(), deadline, "never queued")
            time.sleep(0.01)

    def test_the_channel_answers_the_question_of_its_qid(self):
        future, asked = self.asking(self.port.ask, "Name: ", "x")
        # La base est propre au processus : le qid 1 d'un worker d'avant
        # une relance ne répond pas.
        qid = os.getpid() * 1000 + 1
        self.assertEqual(
            (asked["t"], asked["kind"], asked["qid"], asked["default"]),
            ("ask", "text", qid, "x"),
        )
        self.reply(t="answer", qid=1, value="stale")
        self.reply(t="answer", qid=qid, value="forged")
        self.assertEqual(future.result(10), "forged")
        self.assertEqual(self.received(), {"t": "answered", "qid": qid})
        self.assertEqual(self.out.getvalue(), "Name: forged\n")

    def test_an_answer_split_across_two_reads_still_answers(self):
        future, asked = self.asking(self.port.ask, "Name: ")
        answer = {"t": "answer", "qid": asked["qid"], "value": "forged"}
        line = json.dumps(answer).encode() + b"\n"
        self.hub.sendall(line[:10])
        deadline = time.monotonic() + 5
        while self.port.pending != line[:10]:
            self.assertLess(time.monotonic(), deadline, "never read")
            time.sleep(0.01)
        self.hub.sendall(line[10:])
        self.assertEqual(future.result(10), "forged")

    def test_a_terminal_that_refuses_the_echo_off_has_nothing_to_restore(self):
        refused = termios.error(5, "Input/output error")
        with patch.object(pipe_port.termios, "tcsetattr", side_effect=refused):
            self.assertIsNone(pipe_port._echo_off(self.slave))
        self.assertTrue(termios.tcgetattr(self.slave)[3] & termios.ECHO)

    def test_typeahead_never_answers_and_the_terminal_does(self):
        self.typed(b"typeahead\n")
        future, asked = self.asking(self.port.ask, "Name: ")
        os.write(self.master, b"real\n")
        self.assertEqual(future.result(10), "real")
        self.assertEqual(self.received()["t"], "answered")
        # Tapée, la réponse s'affiche par l'écho : rien n'est transcrit.
        self.assertEqual(self.out.getvalue(), "Name: ")

    def test_a_secret_is_asked_with_the_echo_off_then_masked(self):
        future, asked = self.asking(self.port.secret, "Password: ")
        self.assertEqual(
            (asked["kind"], asked["requires"]), ("secret", ["secret"])
        )
        self.assertFalse(termios.tcgetattr(self.master)[3] & termios.ECHO)
        os.write(self.master, b"hunter2\n")
        self.assertEqual(future.result(10), "hunter2")
        self.assertTrue(termios.tcgetattr(self.master)[3] & termios.ECHO)
        future, asked = self.asking(self.port.secret, "Password: ")
        self.reply(t="answer", qid=asked["qid"], value="hunter2")
        self.assertEqual(future.result(10), "hunter2")
        self.assertEqual(self.out.getvalue(), "Password: •••\n" * 2)

    def test_cancel_and_ctrl_d_end_the_question_like_input(self):
        future, asked = self.asking(self.port.secret, "Password: ")
        self.reply(t="cancel", qid=asked["qid"])
        with self.assertRaises(EOFError):
            future.result(10)
        # Comme getpass : l'écho revient, même annulé.
        self.assertTrue(termios.tcgetattr(self.master)[3] & termios.ECHO)
        closed = {"t": "answered", "qid": asked["qid"], "end": "cancel"}
        self.assertEqual(self.received(), closed)
        future, asked = self.asking(self.port.ask, "Name: ")
        os.write(self.master, b"\x04")
        with self.assertRaises(EOFError):
            future.result(10)
        self.assertEqual(self.received(), {**closed, "qid": asked["qid"]})

    def test_a_cancel_from_the_page_is_abort_in_click_eof_in_input(self):
        # La capture posée dans le fil de la question, comme dans le
        # worker : Annuler vaut Ctrl+D, que click change en Abort.
        import click

        def captured(ask):
            uninstall = legacy.install(self.port)
            try:
                return ask()
            finally:
                uninstall()

        cases = (
            (lambda: click.prompt("Name"), click.exceptions.Abort),
            (lambda: input("Name: "), EOFError),
        )
        for ask, error in cases:
            with self.subTest(error=error.__name__):
                future, asked = self.asking(captured, ask)
                self.assertEqual((asked["t"], asked["kind"]), ("ask", "text"))
                self.reply(t="cancel", qid=asked["qid"])
                with self.assertRaises(error):
                    future.result(10)
                closed = {"t": "answered", "qid": asked["qid"]}
                self.assertEqual(self.received(), {**closed, "end": "cancel"})

    def test_the_countdown_ends_at_its_deadline_or_at_ctrl_d(self):
        future, asked = self.asking(
            self.port.ask, "Go? ", "n", "countdown", 0.2
        )
        self.assertEqual(asked["timeout_s"], 0.2)
        self.assertEqual(future.result(10), "n")
        self.assertEqual(self.out.getvalue(), "⏱0.2s Go?  ⏱ → Enter (n)\n")
        timed_out = {"t": "answered", "qid": asked["qid"], "end": "timeout"}
        self.assertEqual(self.received(), timed_out)
        # Ctrl+D vaut Entrée, comme dans auto_ask.ask, dont readline()
        # vide rend le défaut : "" ici, que la capture change en défaut.
        future, asked = self.asking(
            self.port.ask, "Go? ", "n", "countdown", 30
        )
        os.write(self.master, b"\x04")
        self.assertEqual(future.result(10), "")

    def test_cancel_at_a_countdown_is_enter_as_ctrl_d(self):
        # Annuler, comme Ctrl+D au terminal, n'abandonne pas la tâche : la
        # question rend "", que la capture change en défaut.
        future, asked = self.asking(
            self.port.ask, "Go? ", "n", "countdown", 30
        )
        self.reply(t="cancel", qid=asked["qid"])
        self.assertEqual(future.result(10), "")
        self.assertEqual(
            self.received(), {"t": "answered", "qid": asked["qid"]}
        )
        self.assertEqual(self.out.getvalue(), "⏱30s Go? \n")

        def captured():
            uninstall = legacy.install(self.port)
            try:
                with patch.dict(os.environ, {auto_ask.ENV_ENABLED: "1"}):
                    return auto_ask.ask("Go on? ", "n", 30)
            finally:
                uninstall()

        future, asked = self.asking(captured)
        self.assertEqual(asked["kind"], "countdown")
        self.reply(t="cancel", qid=asked["qid"])
        self.assertEqual(future.result(10), "n")

    def test_a_menu_answer_shows_its_entry(self):
        item = {"key": "1", "label": "Execute", "section": None}
        view = port.menu_view("[1] Execute\n: ", [item], crumbs=["TODO"])
        future, asked = self.asking(self.port.menu, view)
        self.assertEqual((asked["t"], asked["source"]), ("menu", "text"))
        self.reply(t="answer", qid=asked["qid"], value="1")
        self.assertEqual(future.result(10), "1")
        self.assertEqual(self.out.getvalue(), "[1] Execute\n: 1 → Execute\n")

    def test_a_choice_is_an_ask_with_its_options(self):
        # Entrée seule redemande un choix : Ctrl+D, lui, le finit.
        self.addCleanup(os.write, self.master, b"\x04")
        future, asked = self.asking(
            self.port.choose, "Which?", ["alpha", "beta"], True
        )
        self.assertEqual(
            (asked["t"], asked["kind"], asked["multi"]),
            ("ask", "choose", True),
        )
        self.assertEqual(
            [o["label"] for o in asked["options"]], ["alpha", "beta"]
        )
        self.reply(t="answer", qid=asked["qid"], value="2")
        self.assertEqual(future.result(10), ["beta"])
        self.assertEqual(
            self.out.getvalue(), "Which?\n[1] alpha\n[2] beta\n: 2 → beta\n"
        )

    def test_the_end_of_a_menu_names_the_entry_chosen(self):
        items = [{"key": "1", "label": "Execute", "section": None}]
        view = port.menu_view("[1] Execute\n: ", items, crumbs=["TODO"])
        future, asked = self.asking(self.port.menu, view)
        os.write(self.master, b" 1 \n")
        self.assertEqual(future.result(10), " 1 ")
        closed = {"t": "answered", "qid": asked["qid"], "key": "1"}
        self.assertEqual(self.received(), closed)
        # Une réponse hors des entrées, fût-elle de la page, n'en nomme
        # aucune.
        future, asked = self.asking(self.port.menu, view)
        self.reply(t="answer", qid=asked["qid"], value="9")
        self.assertEqual(future.result(10), "9")
        self.assertEqual(
            self.received(), {"t": "answered", "qid": asked["qid"]}
        )

    def test_without_the_hub_the_terminal_answers_alone(self):
        self.lines.close()
        self.hub.close()
        future = self.pool.submit(self.port.ask, "Name: ")
        deadline = time.monotonic() + 10
        while self.out.getvalue() != "Name: ":
            self.assertLess(time.monotonic(), deadline, "never asked")
            time.sleep(0.01)
        os.write(self.master, b"alone\n")
        self.assertEqual(future.result(10), "alone")
        self.assertIsNone(self.port.channel)

    def test_notices_and_command_events_go_to_the_hub(self):
        self.port.notice("forged notice", "error")
        self.port.event({"t": "run_start", "cmd": "true"})
        self.assertTrue(self.port.open_view("telemetry"))
        received = [json.loads(self.lines.readline()) for _ in range(3)]
        self.assertEqual(
            received,
            [
                {"t": "notice", "text": "forged notice", "level": "error"},
                {"t": "run_start", "cmd": "true"},
                {"t": "open_view", "view": "telemetry"},
            ],
        )
        self.assertEqual(self.out.getvalue(), "forged notice\n")


class Client:
    """Double du client d'une session : garde les messages reçus."""

    def __init__(self):
        self.events = []

    async def send(self, data):
        pass

    def event(self, message):
        self.events.append(message)

    def close(self, code, reason):
        pass


class TestRealWorker(unittest.IsolatedAsyncioTestCase):
    async def shown(self, session, prompt, count):
        """Attend la `count`-ième apparition de `prompt` dans la sortie."""
        deadline = time.monotonic() + 20
        while session.ring.data.count(prompt) < count:
            if session.ended.is_set() or time.monotonic() > deadline:
                tail = bytes(session.ring.data[-600:])
                self.fail(f"{prompt!r} × {count} not seen: {tail!r}")
            await asyncio.sleep(0.02)

    async def reading(self, session):
        """Attend que TODO lise son terminal : ses frappes passent alors le
        filtre du hub."""
        deadline = time.monotonic() + 5
        while await session.gate(b"1") != b"1":
            self.assertLess(time.monotonic(), deadline, "TODO does not read")
            await asyncio.sleep(0.02)

    async def test_the_real_todo_answers_zero_and_ends_with_zero(self):
        private_env(self.addCleanup)
        # Un SIGINT ignoré s'hérite : le worker doit rétablir le sien.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGINT, previous)
        session = sessions.Session("w1", str(REPO), "en", 100, 40)
        await session.start()
        self.addAsyncCleanup(session.close)
        main_menu = "[0] 🚪 Quit\r\n: ".encode()
        await self.shown(session, main_menu, 1)
        await self.reading(session)
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

    async def question(self, client, count):
        """La `count`-ième question que le client a reçue."""
        deadline = time.monotonic() + 20
        while True:
            asked = [e for e in client.events if e["t"] in ("menu", "ask")]
            if len(asked) >= count:
                return asked[count - 1]
            self.assertLess(time.monotonic(), deadline, client.events)
            await asyncio.sleep(0.02)

    async def test_the_real_todo_asks_its_menus_through_the_channel(self):
        private_env(self.addCleanup)
        session = sessions.Session("w2", str(REPO), "en", 100, 40)
        await session.start()
        self.addAsyncCleanup(session.close)
        client = Client()
        session.attach(client)
        main = await self.question(client, 1)
        self.assertEqual((main["t"], main["crumbs"]), ("menu", ["TODO"]))
        # Les libellés portent leur icône ; `speak` la laisse.
        self.assertEqual(
            [(i["key"], i["speak"]) for i in main["items"]],
            [
                ("1", "Execute"),
                ("2", "Install"),
                ("3", "Assistant"),
                ("4", "Navigation telemetry"),
                ("5", "Configuration"),
                ("0", "Quit"),
            ],
        )
        answer = {"t": "answer", "qid": main["qid"], "value": "1"}
        self.assertTrue(session.answer(answer))
        execute = await self.question(client, 2)
        self.assertEqual(execute["crumbs"], ["TODO", "Execute"])
        self.assertFalse(session.answer(answer))
        # Annuler vaut Ctrl+D : retour au menu principal.
        session.answer({"t": "cancel", "qid": execute["qid"]})
        again = await self.question(client, 3)
        self.assertEqual(again["crumbs"], ["TODO"])
        session.answer({"t": "answer", "qid": again["qid"], "value": "0"})
        await asyncio.wait_for(session.ended.wait(), 20)
        self.assertEqual(session.code, 0)
        chosen = f"\r\n: 1 → {main['items'][0]['label']}\r\n"
        self.assertIn(chosen, session.ring.data.decode())

    async def test_a_page_answer_reaches_the_leaf(self):
        # Execute › Test › Test a module, par des réponses de la page : la
        # feuille pose sa question, dont la réponse vide la fait finir.
        private_env(self.addCleanup)
        session = sessions.Session("w3", str(REPO), "en", 100, 40)
        await session.start()
        self.addAsyncCleanup(session.close)
        client = Client()
        session.attach(client)

        def entry(menu, name):
            """La clé de l'entrée `name`, avec ou sans sa description."""
            [key] = [
                i["key"]
                for i in menu["items"]
                if i["speak"] == name or i["speak"].startswith(f"{name} - ")
            ]
            return key

        count = 1
        for name in ("Execute", "Test", "Test a module"):
            menu = await self.question(client, count)
            value = entry(menu, name)
            session.answer({"t": "answer", "qid": menu["qid"], "value": value})
            count += 1
        leaf = await self.question(client, count)
        self.assertEqual(
            (leaf["t"], leaf["kind"], leaf["text"]),
            ("ask", "text", "Module name to test: "),
        )
        session.answer({"t": "answer", "qid": leaf["qid"], "value": ""})
        back = await self.question(client, count + 1)
        self.assertEqual(back["crumbs"], ["TODO", "Execute", "Test"])
        self.assertIn("Module name is required!", session.ring.data.decode())
        # Annuler un menu de click : Abort, retour au menu principal.
        session.answer({"t": "cancel", "qid": back["qid"]})
        main = await self.question(client, count + 2)
        self.assertEqual(main["crumbs"], ["TODO"])
        session.answer({"t": "answer", "qid": main["qid"], "value": "0"})
        await asyncio.wait_for(session.ended.wait(), 20)
        self.assertEqual(session.code, 0)


if __name__ == "__main__":
    unittest.main()
