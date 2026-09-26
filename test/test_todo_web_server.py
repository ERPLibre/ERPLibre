#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le hub web de TODO sur de vrais sockets.

Un serveur sur 127.0.0.1:0 par test, piloté par le client HTTP de tornado,
par des requêtes brutes et par la socket de contrôle. HOME et
XDG_RUNTIME_DIR pointent vers un répertoire temporaire : aucun test ne
touche le vrai ~/.erplibre ni le hub de l'utilisateur.
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import socket
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from tornado.httpclient import AsyncHTTPClient

from script.todo.web import paths, server

# Les réponses 4xx sont journalisées en avertissement ; sans handler, le
# dernier recours de logging les écrirait sur stderr.
logging.getLogger().addHandler(logging.NullHandler())

IMPORT_MAP = b'{"imports": {}}'
INDEX = (
    b"<!doctype html>\n<html><head>"
    b'<script type="importmap">' + IMPORT_MAP + b"</script>"
    b"</head><body></body></html>\n"
)


def _short_tmp() -> str:
    """Base des répertoires temporaires : celle du système si elle tient en
    40 octets, /tmp sinon. Le chemin de ctl.sock y ajoute 56 octets, et
    AF_UNIX n'en accepte que 103 à 107."""
    base = tempfile.gettempdir()
    return base if len(os.fsencode(base)) <= 40 else "/tmp"


class EnvCase:
    """HOME, XDG_RUNTIME_DIR, checkout et statiques temporaires."""

    def make_env(self):
        tmp = tempfile.TemporaryDirectory(dir=_short_tmp())
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir(mode=0o700)
        (self.tmp / "home").mkdir()
        env = {
            "HOME": str(self.tmp / "home"),
            "XDG_RUNTIME_DIR": str(self.run_dir),
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = self.tmp / "checkout"
        self.root.mkdir()
        self.static = self.tmp / "static"
        (self.static / "src").mkdir(parents=True)
        (self.static / "index.html").write_bytes(INDEX)
        (self.static / "src" / "main.js").write_text("export {};\n")


class HubCase(EnvCase, unittest.IsolatedAsyncioTestCase):
    IDLE = 60.0

    async def asyncSetUp(self):
        self.make_env()
        self.hub = server.Hub(
            self.root, static_dir=self.static, idle_seconds=self.IDLE
        )
        await self.hub.start()
        self.addAsyncCleanup(self._stop)
        self.host = f"127.0.0.1:{self.hub.port}"
        self.origin = f"http://{self.host}"
        self.http = AsyncHTTPClient(force_instance=True)
        self.addCleanup(self.http.close)

    async def _stop(self):
        self.hub.request_stop()
        await asyncio.wait_for(self.hub.stopped.wait(), 10)

    async def ctl(self, command):
        reader, writer = await asyncio.open_unix_connection(self.hub.ctl_path)
        writer.write(command.encode() + b"\n")
        await writer.drain()
        reply = (await reader.read()).decode().strip()
        writer.close()
        await writer.wait_closed()
        return reply

    async def fetch(self, path, method="GET", body=None, **headers):
        headers.setdefault("Host", self.host)
        return await self.http.fetch(
            f"http://127.0.0.1:{self.hub.port}{path}",
            method=method,
            body=body,
            headers=headers,
            raise_error=False,
        )

    async def raw_get(self, target):
        """Statut d'un GET envoyé tel quel : aucun client ne normalise
        la cible (`..`, `%2e`)."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.hub.port
        )
        writer.write(
            f"GET {target} HTTP/1.1\r\nHost: {self.host}\r\n"
            "Connection: close\r\n\r\n".encode()
        )
        await writer.drain()
        status_line = await reader.readline()
        writer.close()
        await writer.wait_closed()
        return int(status_line.split()[1])

    async def login(self, code=None, **headers):
        headers.setdefault("Origin", self.origin)
        code = code or await self.ctl("mint")
        return await self.fetch(
            "/api/login", "POST", json.dumps({"code": code}), **headers
        )

    async def cookie(self):
        resp = await self.login()
        self.assertEqual(resp.code, 200)
        return resp.headers["Set-Cookie"].split(";")[0]


class TestHttp(HubCase):
    async def test_index_and_security_headers(self):
        resp = await self.fetch("/")
        self.assertEqual(resp.code, 200)
        self.assertEqual(resp.body, INDEX)
        digest = base64.b64encode(hashlib.sha256(IMPORT_MAP).digest())
        self.assertEqual(
            resp.headers["Content-Security-Policy"],
            "default-src 'none'; "
            f"script-src 'self' 'sha256-{digest.decode()}' 'unsafe-eval'; "
            "style-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertNotIn("Server", resp.headers)

    async def test_static_file_and_type(self):
        resp = await self.fetch("/static/src/main.js")
        self.assertEqual(resp.code, 200)
        self.assertEqual(
            resp.headers["Content-Type"], "text/javascript; charset=utf-8"
        )

    async def test_unknown_path_404(self):
        self.assertEqual((await self.fetch("/nope")).code, 404)
        self.assertEqual((await self.fetch("/static/nope.js")).code, 404)

    async def test_traversal_finds_nothing(self):
        for target in (
            "/static/../server.py",
            "/static/%2e%2e/server.py",
            "/static/src/../../paths.py",
            "/static//etc/passwd",
        ):
            self.assertEqual(await self.raw_get(target), 404, target)

    async def test_bad_host_403(self):
        port = self.hub.port
        for host in ("evil.example", f"evil.example:{port}", "127.0.0.1"):
            self.assertEqual(
                (await self.fetch("/", Host=host)).code, 403, host
            )
        resp = await self.fetch("/", Host=f"localhost:{port}")
        self.assertEqual(resp.code, 200)

    async def test_a_refusal_keeps_the_security_headers(self):
        resp = await self.fetch("/", Host="evil.example")
        self.assertEqual(resp.code, 403)
        self.assertEqual(resp.headers["Content-Security-Policy"], self.hub.csp)
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")

    async def test_login_cookie_flags_and_session(self):
        resp = await self.login()
        self.assertEqual(resp.code, 200)
        set_cookie = resp.headers["Set-Cookie"]
        self.assertTrue(
            set_cookie.startswith(f"erplibre_todo_{self.hub.port}=")
        )
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/", set_cookie)
        cookie = set_cookie.split(";")[0]
        session = await self.fetch("/api/session", Cookie=cookie)
        self.assertEqual(session.code, 200)
        data = json.loads(session.body)
        self.assertTrue(data["csrf"])
        self.assertIn(data["lang"], ("fr", "en"))
        self.assertEqual(data["root"], os.path.realpath(self.root))
        self.assertEqual((await self.fetch("/api/session")).code, 403)
        forged = f"erplibre_todo_{self.hub.port}=forged"
        resp = await self.fetch("/api/session", Cookie=forged)
        self.assertEqual(resp.code, 403)

    async def test_reused_code_403(self):
        code = await self.ctl("mint")
        self.assertEqual((await self.login(code)).code, 200)
        self.assertEqual((await self.login(code)).code, 403)

    async def test_code_older_than_120_s_403(self):
        code = await self.ctl("mint")
        self.hub.codes[code] -= server.CODE_TTL + 1
        self.assertEqual((await self.login(code)).code, 403)

    async def test_foreign_origin_403(self):
        for origin in ("http://evil.example", f"https://{self.host}", "null"):
            code = await self.ctl("mint")
            resp = await self.login(code, Origin=origin)
            self.assertEqual(resp.code, 403, origin)
            self.assertIn(code, self.hub.codes, "a refusal burns no code")

    async def test_websocket_handshake_needs_the_exact_origin(self):
        cookie = await self.cookie()
        ws = {
            "Cookie": cookie,
            "Upgrade": "websocket",
            "Connection": "Upgrade",
        }
        self.assertEqual((await self.fetch("/api/session", **ws)).code, 403)
        evil = await self.fetch(
            "/api/session", Origin="http://evil.example", **ws
        )
        self.assertEqual(evil.code, 403)
        resp = await self.fetch("/api/session", Origin=self.origin, **ws)
        self.assertEqual(resp.code, 200)

    async def test_missing_origin_post_403(self):
        code = await self.ctl("mint")
        resp = await self.fetch(
            "/api/login", "POST", json.dumps({"code": code})
        )
        self.assertEqual(resp.code, 403)
        self.assertIn(code, self.hub.codes, "a refusal burns no code")

    async def test_oversized_body_refused(self):
        code = await self.ctl("mint")
        body = json.dumps({"code": code, "pad": "x" * 100000})
        resp = await self.fetch("/api/login", "POST", body, Origin=self.origin)
        self.assertEqual(resp.code, 400)
        self.assertIn(code, self.hub.codes, "the handler never saw the body")

    async def test_malformed_login(self):
        post = {"Origin": self.origin}
        for body, expected in (("[]", 400), ("{", 400), ('{"code": 5}', 403)):
            resp = await self.fetch("/api/login", "POST", body, **post)
            self.assertEqual(resp.code, expected, body)

    async def test_login_removes_the_redirect_file(self):
        self.hub.redirect_path.write_text("code inside")
        self.assertEqual((await self.login()).code, 200)
        self.assertFalse(self.hub.redirect_path.exists())

    async def test_post_needs_the_session_csrf_token(self):
        cookie = await self.cookie()
        session = await self.fetch("/api/session", Cookie=cookie)
        csrf = json.loads(session.body)["csrf"]
        base = {"Cookie": cookie, "Origin": self.origin}
        for token, expected in ((None, 403), ("forged", 403), (csrf, 405)):
            headers = dict(base)
            if token is not None:
                headers["X-CSRF-Token"] = token
            resp = await self.fetch("/api/session", "POST", "{}", **headers)
            self.assertEqual(resp.code, expected, token)


class TestControl(HubCase):
    async def test_ctl_socket_mode_0600(self):
        mode = stat.S_IMODE(os.stat(self.hub.ctl_path).st_mode)
        self.assertEqual(mode, 0o600)

    async def test_state_file(self):
        state = json.loads(self.hub.state_path.read_text())
        self.assertEqual(state["pid"], os.getpid())
        self.assertEqual(state["port"], self.hub.port)
        self.assertEqual(state["root"], os.path.realpath(self.root))
        self.assertIsInstance(state["started"], int)
        mode = stat.S_IMODE(os.stat(self.hub.state_path).st_mode)
        self.assertEqual(mode, 0o600)

    async def test_status_counts_sessions(self):
        before = json.loads(await self.ctl("status"))
        self.assertEqual(
            set(before),
            {
                "pid",
                "port",
                "root",
                "sessions",
                "running",
                "started",
                "idle_seconds",
            },
        )
        self.assertEqual((before["sessions"], before["running"]), (0, 0))
        await self.cookie()
        after = json.loads(await self.ctl("status"))
        self.assertEqual((after["sessions"], after["running"]), (1, 0))

    async def test_tasks_lists_the_idle_watcher(self):
        self.assertIn("watch_idle", await self.ctl("tasks"))

    async def test_unknown_command(self):
        self.assertTrue((await self.ctl("spawn")).startswith("error"))

    async def test_ctl_stop_stops_everything(self):
        self.hub.redirect_path.write_text("code inside")
        self.assertEqual(await self.ctl("stop"), "ok")
        await asyncio.wait_for(self.hub.stopped.wait(), 10)
        self.assertFalse(self.hub.ctl_path.exists())
        self.assertFalse(self.hub.state_path.exists())
        self.assertFalse(self.hub.redirect_path.exists())
        with self.assertRaises(ConnectionRefusedError):
            await asyncio.open_connection("127.0.0.1", self.hub.port)

    async def test_a_live_hub_is_never_robbed(self):
        other = server.Hub(self.root, static_dir=self.static)
        with self.assertRaises(server.HubRunning):
            await other.start()
            self.addAsyncCleanup(other.stop)  # seulement si start() a volé
        self.assertEqual(
            json.loads(await self.ctl("status"))["pid"], os.getpid()
        )


class TestIdle(HubCase):
    IDLE = 1.0

    async def test_idle_hub_stops_by_itself(self):
        await asyncio.wait_for(self.hub.stopped.wait(), 5)
        self.assertFalse(self.hub.ctl_path.exists())
        self.assertFalse(self.hub.state_path.exists())

    async def test_authenticated_requests_keep_it_alive(self):
        cookie = await self.cookie()
        for _ in range(6):
            await asyncio.sleep(0.25)
            resp = await self.fetch("/api/session", Cookie=cookie)
            self.assertEqual(resp.code, 200)
        self.assertFalse(self.hub.stopped.is_set())

    async def test_a_minted_code_keeps_it_alive(self):
        # Le lanceur émet un code juste avant que le navigateur se connecte :
        # le hub ne doit pas s'arrêter entre les deux. `status`, qu'un menu
        # peut interroger à chaque affichage, ne compte pas.
        for _ in range(6):
            await asyncio.sleep(0.25)
            await self.ctl("mint")
        self.assertFalse(self.hub.stopped.is_set())
        await self.ctl("status")
        await asyncio.wait_for(self.hub.stopped.wait(), 5)


class TestStartup(EnvCase, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.make_env()

    async def test_stale_socket_is_replaced(self):
        ctl = paths.ctl_path(self.root)
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(os.fspath(ctl))
        dead.close()  # le fichier reste, personne n'écoute
        hub = server.Hub(self.root, static_dir=self.static)
        await hub.start()
        self.addAsyncCleanup(hub.stopped.wait)
        self.addCleanup(hub.request_stop)
        mode = stat.S_IMODE(os.stat(ctl).st_mode)
        self.assertEqual(mode, 0o600)

    async def test_a_claimed_socket_is_never_claimed_twice(self):
        ctl = paths.ctl_path(self.root)
        first = server._claim_ctl(ctl)
        self.addCleanup(first.close)
        with self.assertRaises(server.HubRunning):
            server._claim_ctl(ctl)

    async def test_a_held_lock_refuses_a_second_hub(self):
        # Un démarrage concurrent tient le verrou : la socket morte qu'il
        # s'apprête à remplacer reste la sienne.
        ctl = paths.ctl_path(self.root)
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(os.fspath(ctl))
        dead.close()
        inode = os.stat(ctl).st_ino
        held = server._hold_lock(paths.lock_path(self.root))
        self.addCleanup(os.close, held)
        hub = server.Hub(self.root, static_dir=self.static)
        with self.assertRaises(server.HubRunning):
            await hub.start()
        self.assertEqual(os.stat(ctl).st_ino, inode)

    async def test_ctl_socket_is_0600_through_the_umask_elsewhere(self):
        with patch.object(server.sys, "platform", "darwin"):
            ctl = server._claim_ctl(paths.ctl_path(self.root))
        self.addCleanup(ctl.close)
        mode = stat.S_IMODE(os.stat(paths.ctl_path(self.root)).st_mode)
        self.assertEqual(mode, 0o600)


class TestMain(EnvCase, unittest.TestCase):
    def setUp(self):
        self.make_env()

    def test_root_is_refused_before_any_file(self):
        err = io.StringIO()
        with patch("os.geteuid", return_value=0), redirect_stderr(err):
            code = server.main(["--root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("root", err.getvalue())
        self.assertFalse((self.run_dir / paths.APP).exists())

    @unittest.skipIf(os.geteuid() == 0, "main() refuse root, code 2")
    def test_a_live_hub_gives_exit_code_3(self):
        live = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(live.close)
        live.bind(os.fspath(paths.ctl_path(self.root)))
        live.listen()
        err = io.StringIO()
        # --idle-seconds : si main() servait malgré tout, il rendrait la main.
        argv = ["--root", str(self.root), "--idle-seconds", "1"]
        with redirect_stderr(err):
            code = server.main(argv)
        self.assertEqual(code, 3)
        self.assertTrue(paths.ctl_path(self.root).exists())

    def test_tornado_access_goes_to_server_log(self):
        handler = server.log_to_file(self.root)
        try:
            logging.getLogger("tornado.access").warning("probe-line")
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()
        log = paths.log_path(self.root)
        self.assertIn("probe-line", log.read_text())
        self.assertEqual(stat.S_IMODE(os.stat(log).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
