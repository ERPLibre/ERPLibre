#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le hub web de TODO sur de vrais sockets.

Un serveur sur 127.0.0.1:0 par test, piloté par le client HTTP de tornado,
par son client WebSocket, par des requêtes brutes et par la socket de
contrôle. HOME et XDG_RUNTIME_DIR pointent vers un répertoire temporaire :
aucun test ne touche le vrai ~/.erplibre ni le hub de l'utilisateur. Une
session lance le worker jetable de todo_web_env, jamais TODO.
"""

import asyncio
import base64
import errno
import hashlib
import io
import json
import logging
import os
import signal
import socket
import stat
import sys
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from todo_web_env import CHILD, private_env
from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest
from tornado.websocket import websocket_connect

from script.todo import todo_i18n, todo_telemetry
from script.todo.web import paths, server, sessions

# Les réponses 4xx sont journalisées en avertissement ; sans handler, le
# dernier recours de logging les écrirait sur stderr.
logging.getLogger().addHandler(logging.NullHandler())

IMPORT_MAP = b'{"imports": {}}'
INDEX = (
    b"<!doctype html>\n<html><head>"
    b'<script type="importmap">' + IMPORT_MAP + b"</script>"
    b"</head><body></body></html>\n"
)


class EnvCase:
    """HOME, XDG_RUNTIME_DIR, checkout et statiques temporaires."""

    def make_env(self):
        self.tmp = private_env(self.addCleanup)
        self.run_dir = self.tmp / "run"
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
            "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'",
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

    async def test_login_removes_only_the_redirect_file_of_its_code(self):
        # Le lanceur réécrit redirect.html pour chaque code : un code plus
        # ancien qui sert ne retire pas le lien plus récent, encore inutilisé.
        first, second = await self.ctl("mint"), await self.ctl("mint")
        self.hub.redirect_path.write_text(f"#login={second}&view=telemetry")
        self.assertEqual((await self.login(first)).code, 200)
        self.assertTrue(self.hub.redirect_path.exists())
        self.assertEqual((await self.login(second)).code, 200)
        self.assertFalse(self.hub.redirect_path.exists())
        self.assertEqual((await self.login()).code, 200, "no redirect file")

    async def test_every_writing_method_needs_the_session_csrf_token(self):
        cookie = await self.cookie()
        session = await self.fetch("/api/session", Cookie=cookie)
        csrf = json.loads(session.body)["csrf"]
        base = {"Cookie": cookie, "Origin": self.origin}
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            body = None if method == "DELETE" else "{}"
            for token, expected in ((None, 403), ("forged", 403), (csrf, 405)):
                headers = dict(base)
                if token is not None:
                    headers["X-CSRF-Token"] = token
                resp = await self.fetch(
                    "/api/session", method, body, **headers
                )
                self.assertEqual(resp.code, expected, (method, token))
        # Seul le POST de la connexion se passe de session.
        resp = await self.fetch("/api/login", "PUT", "{}", Origin=self.origin)
        self.assertEqual(resp.code, 403)
        resp = await self.fetch("/api/session", "OPTIONS", Origin=self.origin)
        self.assertEqual(resp.code, 405)


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
        self.assertEqual((after["sessions"], after["running"]), (0, 0))

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


# Un todo.py minimal : un menu Execute, une feuille « Quit » sous une
# section. build_code_tree le lit par AST, sans l'importer.
FAKE_TODO = """\
class TODO:
    _MENU_LABELS = {"run": "TODO", "prompt_execute": "Execute"}

    def run(self):
        choices = [{"prompt_description": t("Execute")}]
        status = input()
        if status == "1":
            self.prompt_execute()

    def prompt_execute(self):
        choices = [
            {"section": t("Configuration")},
            {"prompt_description": t("Quit")},
        ]
        status = input()
        if status == "1":
            self.leave()
"""


class ApiCase(HubCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.todo_py = self.root / "script" / "todo" / "todo.py"
        self.todo_py.parent.mkdir(parents=True)
        self.todo_py.write_text(FAKE_TODO)
        self.session_cookie = await self.cookie()

    async def get_json(self, path):
        resp = await self.fetch(path, Cookie=self.session_cookie)
        self.assertEqual(resp.code, 200, path)
        return json.loads(resp.body)


class TestTelemetryApi(ApiCase):
    async def test_tree_is_translated_and_carries_telemetry_paths(self):
        tree = (await self.get_json("/api/telemetry?lang=fr"))["tree"]
        self.assertEqual((tree["key"], tree["path"]), ("TODO", "TODO"))
        [execute] = tree["children"]
        self.assertEqual(execute["key"], "Execute")
        self.assertEqual(
            execute["label"], todo_i18n.translate("Execute", "fr")
        )
        self.assertEqual(execute["path"], "TODO › Execute")
        self.assertTrue(execute["menu"])
        [leaf] = execute["children"]
        self.assertEqual(
            leaf,
            {
                "key": "Quit",
                "label": "Quitter",
                "path": "TODO › Execute › Quit",
                "menu": False,
                "children": [],
                "section": todo_i18n.translate("Configuration", "fr"),
            },
        )
        english = await self.get_json("/api/telemetry?lang=en")
        leaf = english["tree"]["children"][0]["children"][0]
        self.assertEqual(leaf["label"], "Quit")

    async def test_counts_come_from_the_telemetry_file(self):
        store = self.tmp / "home" / ".erplibre" / "todo_telemetry.json"
        store.parent.mkdir()
        store.write_text(
            json.dumps({"paths": {"TODO › Execute": 3}, "updated": 1234})
        )
        data = await self.get_json("/api/telemetry?lang=en")
        self.assertEqual(data["counts"], {"TODO › Execute": 3})
        self.assertEqual(data["updated"], 1234)

    async def test_malformed_counters_count_nothing(self):
        store = self.tmp / "home" / ".erplibre" / "todo_telemetry.json"
        store.parent.mkdir()
        for text in ("[1, 2]", '{"paths": [1, 2]}'):
            store.write_text(text)
            data = await self.get_json("/api/telemetry?lang=en")
            self.assertEqual((data["counts"], data["updated"]), ({}, None))

    async def test_the_tree_is_built_off_the_event_loop(self):
        entered, release = threading.Event(), threading.Event()
        waited = []

        def slow(_todo_py):
            # Appelée sur la boucle, elle la bloque : rien ne libère alors
            # `release`, et wait rend False au bout de 2 s.
            entered.set()
            waited.append(release.wait(2))

        with patch.object(todo_telemetry, "build_code_tree", slow):
            pending = asyncio.ensure_future(
                self.get_json("/api/telemetry?lang=en")
            )
            while not (entered.is_set() or pending.done()):
                await asyncio.sleep(0.01)
            status = json.loads(await self.ctl("status"))
            release.set()
            data = await pending
        self.assertEqual(waited, [True])
        self.assertEqual(status["pid"], os.getpid())
        self.assertIsNone(data["tree"])

    async def test_tree_is_rebuilt_only_when_a_source_changes(self):
        build = todo_telemetry.build_code_tree
        with patch.object(
            todo_telemetry, "build_code_tree", wraps=build
        ) as spy:
            await self.get_json("/api/telemetry?lang=en")
            await self.get_json("/api/telemetry?lang=en")
            self.assertEqual(spy.call_count, 1)
            self.todo_py.write_text(
                FAKE_TODO.replace(
                    '{"prompt_description": t("Quit")},',
                    '{"prompt_description": t("Quit")},\n'
                    '            {"prompt_description": t("Back")},',
                ).replace(
                    "self.leave()\n",
                    'self.leave()\n        if status == "2":\n'
                    "            self.back()\n",
                )
            )
            data = await self.get_json("/api/telemetry?lang=en")
            self.assertEqual(spy.call_count, 2)
            leaves = data["tree"]["children"][0]["children"]
            self.assertEqual([c["key"] for c in leaves], ["Quit", "Back"])
            (self.root / "script" / "todo" / "todo.json").write_text("{}")
            await self.get_json("/api/telemetry?lang=en")
            self.assertEqual(spy.call_count, 3)
            # build_code_tree ne lit pas les surcharges privées.
            private = self.root / "private" / "todo" / "todo_override.json"
            private.parent.mkdir(parents=True)
            private.write_text("{}")
            await self.get_json("/api/telemetry?lang=en")
            self.assertEqual(spy.call_count, 3)

    async def test_an_unreadable_tree_is_null_not_an_error(self):
        self.todo_py.unlink()
        data = await self.get_json("/api/telemetry?lang=en")
        self.assertIsNone(data["tree"])
        self.assertIsInstance(data["counts"], dict)

    async def test_a_failing_tree_build_is_logged_and_null(self):
        boom = ValueError("boom-marker")
        with (
            patch.object(todo_telemetry, "build_code_tree", side_effect=boom),
            self.assertLogs(server.log, "ERROR") as logs,
        ):
            terms = await self.get_json("/api/i18n?lang=en")
            data = await self.get_json("/api/telemetry?lang=en")
        self.assertEqual(terms["Quit"], "Quit")
        self.assertIsNone(data["tree"])
        self.assertIsInstance(data["counts"], dict)
        self.assertEqual([r.exc_info[1] for r in logs.records], [boom])

    async def test_unknown_language_400_and_no_cookie_403(self):
        cookie = {"Cookie": self.session_cookie}
        resp = await self.fetch("/api/telemetry?lang=de", **cookie)
        self.assertEqual(resp.code, 400)
        self.assertEqual((await self.fetch("/api/telemetry")).code, 403)

    async def test_the_hub_never_imports_todo_py(self):
        await self.get_json("/api/telemetry?lang=en")
        self.assertNotIn("script.todo.todo", sys.modules)


class TestI18nApi(ApiCase):
    async def test_whole_table_in_the_requested_language(self):
        english = await self.get_json("/api/i18n?lang=en")
        self.assertEqual(len(english), len(todo_i18n.TRANSLATIONS))
        self.assertEqual(english["Quit"], "Quit")
        french = await self.get_json("/api/i18n?lang=fr")
        self.assertEqual(french["Quit"], "Quitter")

    async def test_unknown_language_400_and_no_cookie_403(self):
        cookie = {"Cookie": self.session_cookie}
        resp = await self.fetch("/api/i18n?lang=xx", **cookie)
        self.assertEqual(resp.code, 400)
        self.assertEqual((await self.fetch("/api/i18n?lang=en")).code, 403)

    async def test_a_changed_translation_file_is_reloaded(self):
        i18n_py = self.root / "script" / "todo" / "todo_i18n.py"
        with patch.object(server.importlib, "reload") as reload:
            await self.get_json("/api/i18n?lang=en")
            reload.assert_not_called()
            i18n_py.write_text("# une clé de plus\n")
            await self.get_json("/api/i18n?lang=en")
        reload.assert_called_once_with(todo_i18n)

    async def test_the_table_travels_gzipped(self):
        resp = await self.fetch(
            "/api/i18n?lang=en", Cookie=self.session_cookie
        )
        self.assertEqual(
            resp.headers.get("X-Consumed-Content-Encoding"), "gzip"
        )


class TestSystemApi(ApiCase):
    async def test_a_real_snapshot_carries_the_temperature_first(self):
        data = await self.get_json("/api/system")
        self.assertTrue(data["full"])
        self.assertEqual(
            set(data["metrics"]),
            {
                "cpu",
                "net",
                "mem",
                "disk",
                "battery",
                "temp",
                "uptime",
                "load",
                "ncpu",
            },
        )
        self.assertGreaterEqual(data["metrics"]["ncpu"], 1)

    async def test_no_cookie_403(self):
        self.assertEqual((await self.fetch("/api/system")).code, 403)

    async def test_each_session_keeps_its_previous_sample(self):
        calls = []

        def snapshot(prev, full):
            calls.append((prev, full))
            return {"prev": prev}, len(calls)

        other = await self.cookie()
        with patch.object(todo_telemetry, "system_snapshot", snapshot):
            await self.get_json("/api/system")
            await self.get_json("/api/system")
            resp = await self.fetch("/api/system", Cookie=other)
        self.assertEqual(calls, [(None, True), (1, False), (None, True)])
        self.assertEqual(json.loads(resp.body)["metrics"], {"prev": None})

    async def test_the_temperature_is_read_once_in_five_calls(self):
        fulls = []

        def snapshot(prev, full):
            fulls.append(full)
            return {}, None

        with patch.object(todo_telemetry, "system_snapshot", snapshot):
            for _ in range(11):
                data = await self.get_json("/api/system")
                self.assertEqual(data["full"], fulls[-1])
        self.assertEqual(
            fulls, [True, False, False, False, False] * 2 + [True]
        )


class Tab:
    """Un onglet sur `/ws` : octets reçus, messages texte, code de fin."""

    def __init__(self, conn):
        self.conn = conn
        self.data = bytearray()
        self.texts = []

    async def read(self, timeout=10.0):
        """Un message rangé dans `data` ou `texts` ; faux à la fermeture."""
        message = await asyncio.wait_for(self.conn.read_message(), timeout)
        if message is None:
            return False
        if isinstance(message, bytes):
            self.data += message
        else:
            self.texts.append(json.loads(message))
        return True

    async def until(self, predicate):
        while not predicate():
            if not await self.read():
                raise AssertionError(f"closed: {self.conn.close_code}")

    async def closed(self):
        """Code de fermeture, une fois tout lu."""
        while await self.read():
            pass
        return self.conn.close_code


class TerminalCase(HubCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = patch.object(sessions, "WORKER", ("-c", CHILD))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session_cookie = await self.cookie()
        resp = await self.fetch("/api/session", Cookie=self.session_cookie)
        self.csrf = json.loads(resp.body)["csrf"]

    async def connect(self, **headers):
        """Poignée de main sur `/ws` ; un en-tête qui vaut None est omis."""
        headers = {
            "Host": self.host,
            "Cookie": self.session_cookie,
            "Origin": self.origin,
            **headers,
        }
        url = f"ws://127.0.0.1:{self.hub.port}/ws"
        sent = {name: value for name, value in headers.items() if value}
        request = HTTPRequest(url, headers=sent)
        conn = await websocket_connect(request)
        self.addCleanup(conn.close)
        return Tab(conn)

    async def tab(self, **hello):
        """Onglet qui a envoyé `hello` (complété) et reçu sa réponse."""
        tab = await self.connect()
        message = {"t": "hello", "csrf": self.csrf, "lang": "en", "cols": 90}
        message.update(rows=20)
        message.update(hello)
        await tab.conn.write_message(json.dumps(message))
        await tab.until(lambda: tab.texts)
        return tab


class TestTerminal(TerminalCase):
    async def test_hello_opens_a_session_and_bytes_flow_both_ways(self):
        tab = await self.tab()
        [reply] = tab.texts
        self.assertEqual(
            reply,
            {
                "t": "session",
                "id": reply["id"],
                "offset": 0,
                "truncated": False,
            },
        )
        await tab.until(lambda: b"ready en 90x20" in tab.data)
        status = json.loads(await self.ctl("status"))
        self.assertEqual((status["sessions"], status["running"]), (1, 0))
        await tab.conn.write_message(b"exit 3\n", binary=True)
        self.assertEqual(await tab.closed(), 1000)
        self.assertEqual(tab.texts[-1], {"t": "bye", "code": 3})
        self.assertEqual(self.hub.terminals, {})

    async def test_hello_is_required_within_the_delay(self):
        # Chaque cas change UN champ d'un hello par ailleurs valide : le
        # rejet vient bien de ce champ, jamais d'une taille absente.
        valid = {"t": "hello", "csrf": self.csrf, "lang": "en", "cols": 80}
        valid.update(rows=24)
        bad = [
            json.dumps({**valid, "csrf": "forged"}),
            json.dumps({**valid, "lang": "de"}),
            json.dumps({**valid, "cols": 0}),
            json.dumps({**valid, "cols": server.MAX_TERMINAL + 1}),
            json.dumps({**valid, "cols": True}),
            json.dumps({**valid, "after": -1}),
            json.dumps({**valid, "session": 5}),
            b"binary first",
        ]
        for message in bad:
            tab = await self.connect()
            await tab.conn.write_message(
                message, binary=isinstance(message, bytes)
            )
            self.assertEqual(await tab.closed(), 1008, message)
        with patch.object(server, "HELLO_SECONDS", 0.2):
            tab = await self.connect()
            self.assertEqual(await tab.closed(), 1008)
        self.assertEqual(self.hub.terminals, {})

    async def test_the_handshake_needs_cookie_and_exact_origin(self):
        for headers in (
            {"Origin": "http://evil.example"},
            {"Origin": None},
            {"Cookie": f"erplibre_todo_{self.hub.port}=forged"},
            {"Cookie": None},
        ):
            with self.assertRaises(HTTPClientError) as ctx:
                await self.connect(**headers)
            self.assertEqual(ctx.exception.code, 403, headers)

    async def test_a_fourth_session_waits(self):
        for _ in range(sessions.MAX_SESSIONS):
            await self.tab()
        tab = await self.connect()
        hello = {"t": "hello", "csrf": self.csrf, "lang": "en"}
        await tab.conn.write_message(
            json.dumps({**hello, "cols": 80, "rows": 24})
        )
        self.assertEqual(await tab.closed(), 1013)
        self.assertEqual(len(self.hub.terminals), sessions.MAX_SESSIONS)

    async def test_a_reload_replays_and_takes_the_session_over(self):
        first = await self.tab()
        sid = first.texts[0]["id"]
        await first.until(lambda: b"ready" in first.data)
        session = self.hub.terminals[sid]
        old = session.client
        second = await self.tab(session=sid, after=0, cols=70, rows=15)
        self.assertEqual(second.texts[0]["id"], sid)
        self.assertEqual(await first.closed(), 4001)
        await second.until(lambda: b"ready en 90x20" in second.data)
        self.assertEqual(os.get_terminal_size(session.master), (70, 15))
        # Ce que l'ancien onglet envoyait encore n'atteint plus la session.
        await old.on_message(b"exit 7\n")
        await old.on_message(json.dumps({"t": "close"}))
        await asyncio.sleep(0.3)
        self.assertFalse(session.ended.is_set())
        unknown = await self.connect()
        hello = {"t": "hello", "csrf": self.csrf, "lang": "en", "cols": 80}
        hello.update(rows=24, session="forged")
        await unknown.conn.write_message(json.dumps(hello))
        self.assertEqual(await unknown.closed(), 4404)

    async def test_resize_interrupt_and_close(self):
        tab = await self.tab()
        session = self.hub.terminals[tab.texts[0]["id"]]
        await tab.until(lambda: b"ready" in tab.data)
        await tab.conn.write_message(
            json.dumps({"t": "resize", "cols": 60, "rows": 10})
        )
        await tab.conn.write_message(json.dumps({"t": "unknown"}))
        # Rien de lancé : Arrêter ne change rien, la session répond encore.
        await tab.conn.write_message(json.dumps({"t": "interrupt"}))
        await tab.conn.write_message(b"big 10\n", binary=True)
        await tab.until(lambda: b"END" in tab.data)
        # L'octet Ctrl+C, lui, atteint le worker.
        await tab.conn.write_message(b"\x03", binary=True)
        self.assertEqual(await tab.closed(), 1000)
        self.assertIn(b"INT", tab.data)
        self.assertEqual(tab.texts[-1], {"t": "bye", "code": 5})
        self.assertEqual((session.cols, session.rows), (60, 10))
        tab = await self.tab()
        await tab.conn.write_message(json.dumps({"t": "close"}))
        self.assertEqual(await tab.closed(), 1000)
        self.assertEqual(tab.texts[-1], {"t": "bye", "code": -signal.SIGHUP})

    async def test_input_beyond_the_limit_closes_with_1008(self):
        tab = await self.tab()
        await tab.until(lambda: b"ready" in tab.data)
        with patch.object(sessions, "INPUT_LIMIT", 1000):
            await tab.conn.write_message(b"x" * 1001, binary=True)
            self.assertEqual(await tab.closed(), 1008)

    async def test_open_view_is_relayed(self):
        tab = await self.tab()
        line = b'send {"t":"open_view","view":"telemetry"}\n'
        await tab.conn.write_message(line, binary=True)
        await tab.until(lambda: len(tab.texts) == 2)
        self.assertEqual(tab.texts[1], {"t": "open_view", "view": "telemetry"})

    async def test_the_session_list(self):
        tab = await self.tab()
        sid = tab.texts[0]["id"]
        resp = await self.fetch("/api/sessions", Cookie=self.session_cookie)
        self.assertEqual(
            json.loads(resp.body),
            {
                "sessions": [{"id": sid, "running": False, "attached": True}],
                "max": sessions.MAX_SESSIONS,
            },
        )
        self.assertEqual((await self.fetch("/api/sessions")).code, 403)

    async def test_stopping_the_hub_leaves_no_worker(self):
        tab = await self.tab()
        pid = self.hub.terminals[tab.texts[0]["id"]].proc.pid
        self.assertEqual(await self.ctl("stop"), "ok")
        self.assertEqual(await tab.closed(), 1000)
        self.assertEqual(tab.texts[-1], {"t": "bye", "code": -signal.SIGHUP})
        await asyncio.wait_for(self.hub.stopped.wait(), 10)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_a_tab_lost_while_its_session_starts_is_not_attached(self):
        handlers, done = [], asyncio.get_running_loop().create_future()
        hello, opening = server.Terminal.hello, self.hub.open_terminal

        async def said_hello(handler, message):
            handlers.append(handler)
            await hello(handler, message)
            done.set_result(handler)

        async def open_terminal(*args):
            session = await opening(*args)
            # La connexion se perd pendant le lancement : tornado appelle
            # ce crochet.
            handlers[0].on_connection_close()
            return session

        with (
            patch.object(server.Terminal, "hello", said_hello),
            patch.object(self.hub, "open_terminal", open_terminal),
        ):
            tab = await self.connect()
            message = {"t": "hello", "csrf": self.csrf, "lang": "en"}
            message.update(cols=80, rows=24)
            await tab.conn.write_message(json.dumps(message))
            handler = await asyncio.wait_for(done, 10)
        [session] = self.hub.terminals.values()
        self.assertIsNone(handler.session)
        self.assertIsNone(session.client)
        # Sans client, elle finit par inactivité, comme un onglet fermé.
        self.assertFalse(session.closing)

    async def test_stopping_the_hub_reaps_a_session_still_starting(self):
        spawn = sessions.Session._spawn
        held, release = asyncio.Event(), asyncio.Event()

        async def hold(session):
            held.set()
            await release.wait()
            await spawn(session)

        with patch.object(sessions.Session, "_spawn", hold):
            tab = await self.connect()
            message = {"t": "hello", "csrf": self.csrf, "lang": "en"}
            message.update(cols=80, rows=24)
            await tab.conn.write_message(json.dumps(message))
            await asyncio.wait_for(held.wait(), 10)
            [session] = self.hub.terminals.values()
            self.hub.request_stop()
            # `close` rend aussitôt : la session n'est pas encore lancée.
            deadline = time.monotonic() + 10
            while not session.closing:
                self.assertLess(time.monotonic(), deadline, "not closing")
                await asyncio.sleep(0.01)
            release.set()
            await asyncio.wait_for(self.hub.stopped.wait(), 10)
        # Lancée puis arrêtée avant que le hub ne se dise arrêté.
        self.assertTrue(session.ended.is_set())
        self.assertEqual(session.code, -signal.SIGHUP)
        self.assertEqual(self.hub.terminals, {})
        self.assertEqual(await tab.closed(), 1011)


def _masked(opcode, payload):
    """Trame WebSocket finale d'un client, masquée comme la RFC 6455 le
    veut ; `payload` de moins de 64 Kio."""
    mask = os.urandom(4)
    size = len(payload)
    if size < 126:
        head = bytes([0x80 | opcode, 0x80 | size])
    else:
        head = bytes([0x80 | opcode, 0x80 | 126]) + size.to_bytes(2, "big")
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + body


class TestDeadClient(TerminalCase):
    async def asyncSetUp(self):
        patcher = patch.object(server, "PING_SECONDS", 0.2)
        patcher.start()
        self.addCleanup(patcher.stop)
        await super().asyncSetUp()

    async def test_a_client_that_stops_reading_is_detached(self):
        # Un client qui ne lit plus sa socket, comme un tunnel SSH d'un poste
        # en veille : les envois du hub restent en attente.
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", self.hub.port
        )
        self.addCleanup(writer.close)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            (
                f"GET /ws HTTP/1.1\r\nHost: {self.host}\r\n"
                f"Origin: {self.origin}\r\nCookie: {self.session_cookie}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).encode()
        )
        head = await reader.readuntil(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 101 "))
        hello = {"t": "hello", "csrf": self.csrf, "lang": "en", "cols": 80}
        hello["rows"] = 24
        writer.write(_masked(0x1, json.dumps(hello).encode()))
        writer.write(_masked(0x2, b"big 50000000\n"))
        # Sans pong, le hub ferme ; tornado laisse 5 s au client pour
        # répondre, puis l'envoi en attente échoue et la session le détache.
        deadline = time.monotonic() + 20
        while len(self.hub.terminals) != 1:
            self.assertLess(time.monotonic(), deadline, "no session")
            await asyncio.sleep(0.05)
        [session] = self.hub.terminals.values()
        while session.client is not None or b"END" not in session.ring.data:
            self.assertLess(time.monotonic(), deadline, "still attached")
            await asyncio.sleep(0.05)


class TestTerminalIdle(TerminalCase):
    IDLE = 1.0

    async def test_a_session_keeps_the_hub_until_it_idles_out(self):
        self.hub.session_idle = 1.5
        tab = await self.tab()
        pid = self.hub.terminals[tab.texts[0]["id"]].proc.pid
        tab.conn.close()
        # La session s'éteint seule vers 1.6-1.85 s ; le hub, occupé tant
        # qu'elle existe, ne s'arrête qu'ensuite — deux faits distincts.
        deadline = time.monotonic() + 10
        while self.hub.terminals:
            self.assertLess(time.monotonic(), deadline, "session still open")
            await asyncio.sleep(0.05)
        self.assertFalse(self.hub.stopped.is_set())
        await asyncio.wait_for(self.hub.stopped.wait(), 10)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)


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

    async def assert_released(self):
        """Verrou libre, aucun ctl.sock, et un hub suivant démarre."""
        os.close(server._hold_lock(paths.lock_path(self.root)))
        self.assertFalse(paths.ctl_path(self.root).exists())
        hub = server.Hub(self.root, static_dir=self.static)
        await hub.start()
        hub.request_stop()
        await asyncio.wait_for(hub.stopped.wait(), 10)

    async def test_a_start_failing_after_the_lock_releases_it(self):
        boom = OSError(errno.EADDRINUSE, "boom-marker")
        hub = server.Hub(self.root, static_dir=self.static)
        with (
            patch.object(
                server.tornado.netutil, "bind_sockets", side_effect=boom
            ),
            self.assertRaisesRegex(OSError, "boom-marker"),
        ):
            await hub.start()
        await self.assert_released()

    async def test_a_start_failing_last_closes_its_sockets(self):
        hub = server.Hub(self.root, static_dir=self.static)
        with (
            patch.object(
                server.paths, "write_private", side_effect=OSError("boom")
            ),
            self.assertRaisesRegex(OSError, "boom"),
        ):
            await hub.start()
        with self.assertRaises(ConnectionRefusedError):
            await asyncio.open_connection("127.0.0.1", hub.port)
        await self.assert_released()

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
