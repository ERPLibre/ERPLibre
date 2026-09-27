#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le lanceur du hub web : de vrais hubs, lancés depuis ce dépôt.

HOME et XDG_RUNTIME_DIR pointent vers un répertoire temporaire : le hub de
ces tests a sa propre socket et ne croise jamais celui de l'utilisateur. Un
lancement qui échoue passe par un faux interpréteur, un script shell.
"""

import contextlib
import http.client
import io
import json
import os
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import tornado
from todo_web_env import private_env

from script.todo.web import launcher, paths, server

REPO = Path(__file__).resolve().parent.parent
# Le lanceur et le hub refusent root : sous root, ces tests n'ont rien à
# lancer.
as_user = unittest.skipIf(os.geteuid() == 0, "le lanceur refuse root")


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _login(port, code):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(
            "POST",
            "/api/login",
            body=json.dumps({"code": code}),
            headers={"Origin": f"http://127.0.0.1:{port}"},
        )
        return conn.getresponse().status
    finally:
        conn.close()


def _fake_python(base, body):
    """Script shell qui tient lieu d'interpréteur du venv."""
    script = base / "fake_python"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


@as_user
class TestWithHub(unittest.TestCase):
    """Un vrai hub pour toute la classe, lancé par ensure_running."""

    @classmethod
    def setUpClass(cls):
        cls.base = private_env(cls.addClassCleanup)
        cls.info = launcher.ensure_running(REPO)
        cls.addClassCleanup(launcher.stop, REPO)

    def test_ensure_running_reuses_the_live_hub(self):
        with patch.object(launcher.subprocess, "Popen") as popen:
            again = launcher.ensure_running(REPO)
        popen.assert_not_called()
        self.assertEqual(again["pid"], self.info["pid"])
        self.assertEqual(again["root"], os.path.realpath(REPO))

    def test_runtime_and_data_files_are_private(self):
        # Chemins recomposés sans les fonctions de paths : elles resserrent
        # les modes à chaque appel et masqueraient un défaut du hub.
        cid = paths.checkout_id(REPO)
        rdir = Path(os.environ["XDG_RUNTIME_DIR"], paths.APP, cid)
        ddir = Path(os.environ["HOME"], ".erplibre", "todo_web", cid)
        for path, mode in (
            (rdir.parent, 0o700),
            (rdir, 0o700),
            (rdir / "ctl.sock", 0o600),
            (rdir / "hub.lock", 0o600),
            (rdir / "state.json", 0o600),
            (ddir, 0o700),
            (ddir / "server.log", 0o600),
        ):
            self.assertEqual(_mode(path), mode, path)

    def test_the_hub_leads_its_own_session(self):
        # Ctrl+C dans le terminal de TODO vise son groupe, pas celui du hub.
        self.assertEqual(os.getsid(self.info["pid"]), self.info["pid"])

    def test_the_browser_only_receives_a_file_uri(self):
        with (
            patch.dict(os.environ, {"DISPLAY": ":0"}),
            patch.object(
                launcher.webbrowser, "open_new_tab", return_value=True
            ) as browser,
        ):
            result = launcher.open_page(REPO, lang="en")
        [uri] = browser.call_args.args
        code = parse_qs(urlsplit(result.link).fragment)["login"][0]
        self.assertTrue(uri.startswith("file://"), uri)
        self.assertNotIn(code, uri)
        self.assertEqual((result.opened, result.headless), (True, False))
        redirect = paths.redirect_path(REPO)
        self.assertEqual(_mode(redirect), 0o600)
        self.assertIn(code, redirect.read_text())

    def test_headless_opens_nothing_and_returns_the_link(self):
        with patch.object(launcher.webbrowser, "open_new_tab") as browser:
            result = launcher.open_page(REPO)
        browser.assert_not_called()
        self.assertEqual((result.opened, result.headless), (False, True))
        self.assertEqual(result.url, f"http://127.0.0.1:{self.info['port']}/")
        fragment = parse_qs(urlsplit(result.link).fragment)
        self.assertEqual(fragment["view"], ["telemetry"])
        self.assertNotIn("lang", fragment)

    def test_the_link_logs_in_once_and_consumes_the_redirect(self):
        result = launcher.open_page(REPO, browser=False)
        code = parse_qs(urlsplit(result.link).fragment)["login"][0]
        self.assertEqual(_login(self.info["port"], code), 200)
        self.assertEqual(_login(self.info["port"], code), 403)
        self.assertFalse(paths.redirect_path(REPO).exists())

    def test_an_unwritable_redirect_file_is_a_launch_error(self):
        # Un répertoire à la place de redirect.html : os.replace échoue.
        blocker = paths.redirect_path(REPO)
        blocker.unlink(missing_ok=True)
        blocker.mkdir()
        self.addCleanup(blocker.rmdir)
        with self.assertRaisesRegex(launcher.LaunchError, "redirect"):
            launcher.open_page(REPO, browser=False)
        self.assertEqual(
            [p.name for p in blocker.parent.glob("redirect.html*")],
            ["redirect.html"],
        )

    def test_invalid_view_or_language_is_refused(self):
        with self.assertRaises(ValueError):
            launcher.open_page(REPO, view="x&login=y", browser=False)
        with self.assertRaises(ValueError):
            launcher.open_page(REPO, lang="de", browser=False)

    def test_main_status_prints_the_state(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = launcher.main(["status", "--root", str(REPO)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["pid"], self.info["pid"])

    def test_main_open_prints_url_and_link(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = launcher.main(["open", "--no-browser", "--root", str(REPO)])
        self.assertEqual(code, 0)
        port = self.info["port"]
        self.assertIn(f"url: http://127.0.0.1:{port}/", out.getvalue())
        self.assertIn(f"ssh -L {port}:127.0.0.1:{port}", out.getvalue())
        self.assertRegex(out.getvalue(), r"link: \S+#login=\S+")


@as_user
class TestOtherCheckout(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_a_hub_serving_another_checkout_is_ignored(self):
        other = self.base / "other"
        other.mkdir()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(os.fspath(paths.ctl_path(other)))
        srv.listen(1)
        reply = json.dumps({"pid": 1, "port": 1, "root": str(REPO)})

        def answer_once():
            with srv:
                conn, _ = srv.accept()
                with conn:
                    conn.recv(64)
                    conn.sendall(reply.encode() + b"\n")

        # daemon : si status() ne se connecte pas, accept() ne bloque pas la
        # sortie du test.
        thread = threading.Thread(target=answer_once, daemon=True)
        thread.start()
        with self.assertLogs(launcher.log, "WARNING"):
            self.assertIsNone(launcher.status(other))
        thread.join(5)


@as_user
class TestStartFailure(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_a_hub_that_dies_reports_the_end_of_its_log(self):
        fake = _fake_python(self.base, "echo boom-marker >&2\nexit 1\n")
        fd = paths.open_log(REPO)
        os.write(fd, b"line of an earlier run\n")
        os.close(fd)
        started = time.monotonic()
        with (
            patch.object(launcher, "venv_python", return_value=fake),
            self.assertRaises(launcher.LaunchError) as ctx,
        ):
            launcher.ensure_running(REPO)
        self.assertIn("boom-marker", ctx.exception.log_tail)
        self.assertNotIn("earlier run", ctx.exception.log_tail)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(
            (ctx.exception.kind, ctx.exception.pkg), ("start", None)
        )

    def test_a_venv_without_tornado_names_the_missing_package(self):
        # Le vrai hub sous un Python sans site-packages (-S) : son import
        # de tornado échoue comme dans un venv qui ne l'a pas.
        python = shlex.quote(sys.executable)
        fake = _fake_python(self.base, f'exec {python} -S "$@"\n')
        with (
            patch.object(launcher, "venv_python", return_value=fake),
            self.assertRaises(launcher.LaunchError) as ctx,
        ):
            launcher.ensure_running(REPO)
        self.assertEqual(ctx.exception.message, "the web hub did not start")
        self.assertEqual(
            (ctx.exception.kind, ctx.exception.pkg), ("missing", "tornado")
        )
        self.assertIn("No module named 'tornado'", ctx.exception.log_tail)

    def test_a_hub_that_never_answers_is_killed(self):
        pidfile = self.base / "pid"
        fake = _fake_python(self.base, f"echo $$ > {pidfile}\nexec sleep 30\n")
        with (
            patch.object(launcher, "venv_python", return_value=fake),
            patch.object(launcher, "START_TIMEOUT", 0.5),
            self.assertRaises(launcher.LaunchError),
        ):
            launcher.ensure_running(REPO)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertNotIn(pid, launcher._SPAWNED)

    def test_a_missing_interpreter_is_a_launch_error(self):
        missing = str(self.base / "no" / "python")
        with (
            patch.object(launcher, "venv_python", return_value=missing),
            self.assertRaisesRegex(launcher.LaunchError, "cannot run"),
        ):
            launcher.ensure_running(REPO)

    def test_an_unwritable_erplibre_dir_is_a_launch_error(self):
        erplibre = self.base / "home" / ".erplibre"
        erplibre.mkdir(mode=0o500)
        self.addCleanup(erplibre.chmod, 0o700)
        with (
            patch.object(launcher.subprocess, "Popen") as popen,
            self.assertRaisesRegex(launcher.LaunchError, "log"),
        ):
            launcher.ensure_running(REPO)
        popen.assert_not_called()

    def test_a_log_that_cannot_be_emptied_is_a_launch_error(self):
        boom = OSError("boom-marker")
        with (
            patch.object(launcher.os, "ftruncate", side_effect=boom),
            patch.object(launcher.subprocess, "Popen") as popen,
            self.assertRaisesRegex(launcher.LaunchError, "boom-marker"),
        ):
            launcher.ensure_running(REPO)
        popen.assert_not_called()

    def test_main_open_reports_the_failure(self):
        fake = _fake_python(self.base, "echo boom-marker >&2\nexit 1\n")
        err = io.StringIO()
        with (
            patch.object(launcher, "venv_python", return_value=fake),
            contextlib.redirect_stderr(err),
        ):
            code = launcher.main(["open", "--root", str(REPO)])
        self.assertEqual(code, 1)
        self.assertIn("did not start", err.getvalue())
        self.assertIn("boom-marker", err.getvalue())

    def test_a_socket_path_too_long_is_reported_from_the_log(self):
        deep = self.base / "run" / ("x" * 100)
        deep.mkdir(mode=0o700)
        os.environ["XDG_RUNTIME_DIR"] = str(deep)
        self.assertIsNone(launcher.status(REPO))
        with self.assertRaises(launcher.LaunchError) as ctx:
            launcher.ensure_running(REPO)
        limit = f"AF_UNIX allows {paths.MAX_SOCK_PATH}"
        self.assertIn(limit, ctx.exception.log_tail)

    def test_main_open_refuses_an_invalid_view_before_launching(self):
        err = io.StringIO()
        with (
            patch.object(launcher.subprocess, "Popen") as popen,
            contextlib.redirect_stderr(err),
        ):
            code = launcher.main(
                ["open", "--view", "a&b", "--root", str(REPO)]
            )
        self.assertEqual(code, 2)
        popen.assert_not_called()
        self.assertIn("invalid view", err.getvalue())


@as_user
class TestUnresponsiveHub(unittest.TestCase):
    """Une socket de contrôle servie par un thread, qui répond mal ou pas."""

    def setUp(self):
        self.base = private_env(self.addCleanup)
        self.status = json.dumps(
            {"pid": 1, "port": 1, "root": os.path.realpath(REPO)}
        )

    def fake_hub(self, replies):
        """Répond à chaque commande reçue par `replies[commande]`, ou ferme
        sans rien répondre si la commande n'y est pas. `replies` est lu à
        chaque connexion : le modifier change la réponse suivante."""
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(os.fspath(paths.ctl_path(REPO)))
        srv.listen(8)
        srv.settimeout(0.05)
        done = threading.Event()

        def serve():
            with srv:
                while not done.is_set():
                    try:
                        conn, _ = srv.accept()
                    except TimeoutError:
                        continue
                    with conn:
                        reply = replies.get(conn.recv(64).decode().strip())
                        if reply is not None:
                            conn.sendall(reply.encode() + b"\n")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(done.set)

    def test_mint_code_without_a_hub_is_a_launch_error(self):
        with self.assertRaisesRegex(launcher.LaunchError, "not running"):
            launcher.mint_code(REPO)

    def test_mint_code_without_an_answer_is_a_launch_error(self):
        self.fake_hub({})
        with self.assertRaisesRegex(launcher.LaunchError, "not running"):
            launcher.mint_code(REPO)

    def test_mint_code_refused_by_the_hub_is_a_launch_error(self):
        self.fake_hub({"mint": "error: unknown command"})
        with self.assertRaisesRegex(launcher.LaunchError, "not running"):
            launcher.mint_code(REPO)

    def test_open_page_with_a_refused_code_writes_no_link(self):
        self.fake_hub({"status": self.status, "mint": "error: no code"})
        with (
            patch.object(launcher.subprocess, "Popen") as popen,
            self.assertRaises(launcher.LaunchError),
        ):
            launcher.open_page(REPO, browser=False)
        popen.assert_not_called()
        self.assertFalse(paths.redirect_path(REPO).exists())

    def test_an_unreadable_status_is_no_hub(self):
        replies = {}
        self.fake_hub(replies)
        for reply in (None, "not json", "[1, 2]"):
            replies["status"] = reply
            self.assertIsNone(launcher.status(REPO), reply)

    def test_stop_without_an_answer_is_false(self):
        self.assertFalse(launcher.stop(REPO))
        self.fake_hub({})
        self.assertFalse(launcher.stop(REPO))

    def test_a_hub_that_ignores_stop_is_reported(self):
        self.fake_hub({"status": self.status, "stop": "ok"})
        err = io.StringIO()
        with patch.object(launcher, "STOP_TIMEOUT", 0.3):
            self.assertFalse(launcher.stop(REPO))
            with contextlib.redirect_stderr(err):
                code = launcher.main(["stop", "--root", str(REPO)])
        self.assertEqual(code, 1)
        self.assertIn("did not stop", err.getvalue())


@as_user
class TestConcurrentStart(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_a_hub_started_meanwhile_by_another_process_is_found(self):
        # Un autre démarreur tient le verrou : le hub lancé ici sort en code
        # 3, et le hub de l'autre ne répond qu'après cette sortie.
        popen = subprocess.Popen
        spawned = {}

        def concurrent_start(argv, **kwargs):
            held = server._hold_lock(paths.lock_path(REPO))
            try:
                spawned["ours"] = ours = popen(argv, **kwargs)
                ours.wait(10)
            finally:
                os.close(held)
            spawned["other"] = other = popen(
                argv,
                cwd=REPO,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.addCleanup(other.wait, 10)
            self.addCleanup(other.terminate)
            return ours

        with patch.object(
            launcher.subprocess, "Popen", side_effect=concurrent_start
        ):
            info = launcher.ensure_running(REPO)
        self.assertEqual(spawned["ours"].returncode, 3)
        self.assertEqual(info["pid"], spawned["other"].pid)


class TestRoot(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_root_is_refused_before_any_file(self):
        with (
            patch("os.geteuid", return_value=0),
            patch.object(launcher.subprocess, "Popen") as popen,
        ):
            self.assertIsNone(launcher.status(REPO))
            with self.assertRaisesRegex(launcher.LaunchError, "root") as ctx:
                launcher.ensure_running(REPO)
            self.assertEqual(ctx.exception.kind, "root")
            with self.assertRaisesRegex(launcher.LaunchError, "root"):
                launcher.open_page(REPO, browser=False)
            self.assertFalse(launcher.stop(REPO))
        popen.assert_not_called()
        self.assertFalse((self.base / "run" / paths.APP).exists())
        self.assertFalse((self.base / "home" / ".erplibre").exists())


@as_user
class TestStop(unittest.TestCase):
    def setUp(self):
        self.base = private_env(self.addCleanup)

    def test_stop_stops_reaps_and_cleans(self):
        pid = launcher.ensure_running(REPO)["pid"]
        self.addCleanup(launcher.stop, REPO)
        self.assertTrue(launcher.stop(REPO))
        self.assertIsNone(launcher.status(REPO))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse(paths.ctl_path(REPO).exists())
        self.assertFalse(paths.state_path(REPO).exists())
        self.assertFalse(launcher.stop(REPO))

    def test_sigterm_stops_and_cleans(self):
        pid = launcher.ensure_running(REPO)["pid"]
        self.addCleanup(launcher.stop, REPO)
        os.kill(pid, signal.SIGTERM)
        self.assertEqual(launcher._SPAWNED.pop(pid).wait(5), 0)
        self.assertFalse(paths.ctl_path(REPO).exists())
        self.assertFalse(paths.state_path(REPO).exists())

    def test_main_stop_without_a_hub(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = launcher.main(["stop", "--root", str(REPO)])
        self.assertEqual((code, out.getvalue()), (0, "not running\n"))


class TestInstallation(unittest.TestCase):
    def test_venv_python_follows_the_conf_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp, "conf")
            conf.mkdir()
            self.assertEqual(
                launcher.venv_python(tmp),
                str(Path(tmp, ".venv.erplibre", "bin", "python")),
            )
            (conf / "python-erplibre-venv").write_text("# x\n\n.venv.y\n")
            self.assertEqual(
                launcher.venv_python(tmp),
                str(Path(tmp, ".venv.y", "bin", "python")),
            )

    def test_make_targets_run_the_launcher(self):
        out = subprocess.run(
            ["make", "-n", "-f", "conf/make.todo.Makefile"]
            + ["todo_web", "todo_web_stop"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertIn("-m script.todo.web.launcher open", out)
        self.assertIn("-m script.todo.web.launcher stop", out)

    def test_tornado_is_declared_and_installed_in_range(self):
        text = (
            REPO / "requirement" / "erplibre_require-ments.txt"
        ).read_text()
        self.assertRegex(text, re.compile(r"^tornado>=6\.5\.10,<7$", re.M))
        self.assertIn(launcher.TORNADO, text.splitlines())
        self.assertGreaterEqual(tornado.version_info[:3], (6, 5, 10))
        self.assertLess(tornado.version_info[0], 7)


if __name__ == "__main__":
    unittest.main()
