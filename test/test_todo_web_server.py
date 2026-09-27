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
import datetime
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

from compression import zstd
from todo_web_env import CHILD, private_env
from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest
from tornado.websocket import websocket_connect

from script.todo import todo_i18n, todo_telemetry
from script.todo.web import (
    paths,
    protocol,
    server,
    sessions,
    tasklog,
    ttywatch,
)

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
        store.parent.mkdir(exist_ok=True)  # le hub y tient ses journaux
        store.write_text(
            json.dumps({"paths": {"TODO › Execute": 3}, "updated": 1234})
        )
        data = await self.get_json("/api/telemetry?lang=en")
        self.assertEqual(data["counts"], {"TODO › Execute": 3})
        self.assertEqual(data["updated"], 1234)

    async def test_malformed_counters_count_nothing(self):
        store = self.tmp / "home" / ".erplibre" / "todo_telemetry.json"
        store.parent.mkdir(exist_ok=True)  # le hub y tient ses journaux
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

    async def tab(self, reading=True, **hello):
        """Onglet qui a envoyé `hello` (complété) et reçu sa réponse ; avec
        `reading`, aussi un `tty_state` qui voit l'enfant lire son
        terminal : les frappes de l'onglet passent alors le filtre."""
        tab = await self.connect()
        message = {"t": "hello", "csrf": self.csrf, "lang": "en", "cols": 90}
        message.update(rows=20)
        message.update(hello)
        await tab.conn.write_message(json.dumps(message))
        await tab.until(lambda: tab.texts)
        if reading:
            await tab.until(lambda: any(t.get("reader") for t in tab.texts))
        return tab


class TestTerminal(TerminalCase):
    async def test_hello_opens_a_session_and_bytes_flow_both_ways(self):
        tab = await self.tab()
        reply = tab.texts[0]
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
        opened = {"t": "open_view", "view": "telemetry"}
        await tab.until(lambda: opened in tab.texts)

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


# Un worker qui demande un mot de passe, écho coupé, puis en dit la
# longueur.
ASKING = r"""
import fcntl, getpass, termios
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
print("length", len(getpass.getpass("pw: ")), flush=True)
"""

# Un worker qui attend `sleep` dans son propre groupe, sans lire son
# terminal ; SIGINT l'interrompt.
WAITING = r"""
import fcntl, signal, subprocess, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
print("ready", flush=True)
try:
    subprocess.run(["sleep", "30"])
except KeyboardInterrupt:
    print("INT", flush=True)
"""


class TestKeystrokes(TerminalCase):
    async def waiting(self):
        """Onglet d'une session dont le worker ne lit pas son terminal."""
        with patch.object(sessions, "WORKER", ("-c", WAITING)):
            tab = await self.tab(reading=False)
        await tab.until(lambda: b"ready" in tab.data)
        await tab.until(
            lambda: any(t.get("reader") is False for t in tab.texts)
        )
        return tab

    async def test_the_tab_learns_the_state_of_the_terminal(self):
        tab = await self.tab()
        state = {"t": "tty_state", "echo": True, "canon": True}
        state.update(reader=True, altscreen=False)
        await tab.until(lambda: state in tab.texts)

    async def test_what_nobody_reads_is_dropped_unless_in_raw_mode(self):
        tab = await self.waiting()
        await tab.conn.write_message(b"abc", binary=True)
        await tab.until(lambda: {"t": "dropped", "bytes": 3} in tab.texts)
        await tab.conn.write_message(json.dumps({"t": "raw", "on": True}))
        await tab.conn.write_message(b"xyz", binary=True)
        # L'écho du terminal : ces octets ont atteint le PTY, pas les autres.
        await tab.until(lambda: b"xyz" in tab.data)
        self.assertNotIn(b"abc", tab.data)

    async def test_a_paste_goes_line_by_line_unless_in_raw_mode(self):
        tab = await self.tab()
        session = self.hub.terminals[tab.texts[0]["id"]]
        calls, write = [], session.write

        def recorded(data, lines=False):
            calls.append((bytes(data), lines))
            return write(data, lines)

        session.write = recorded
        await tab.conn.write_message(b"big 1\nbig 2\n", binary=True)
        await tab.until(lambda: tab.data.count(b"END") == 2)
        await tab.conn.write_message(json.dumps({"t": "raw", "on": True}))
        await tab.conn.write_message(b"big 3\n", binary=True)
        await tab.until(lambda: tab.data.count(b"END") == 3)
        self.assertEqual(
            calls, [(b"big 1\nbig 2\n", True), (b"big 3\n", False)]
        )

    async def test_a_tab_that_comes_back_learns_what_was_dropped(self):
        first = await self.tab()
        sid = first.texts[0]["id"]
        session = self.hub.terminals[sid]
        first.conn.close()
        deadline = time.monotonic() + 10
        while session.client is not None:
            self.assertLess(time.monotonic(), deadline, "still attached")
            await asyncio.sleep(0.02)
        # Sans onglet, la session jette le reste d'un collage.
        session.held += b"later\n"
        session._drop_held()
        again = await self.tab(session=sid, after=0)
        lost = {"t": "dropped", "bytes": len(b"later\n")}
        self.assertEqual(again.texts[1], lost)
        self.assertEqual(session.unreported, 0)

    async def test_stop_and_ctrl_c_are_never_dropped(self):
        for stop in (json.dumps({"t": "interrupt"}), b"\x03"):
            with self.subTest(stop=stop):
                tab = await self.waiting()
                binary = isinstance(stop, bytes)
                await tab.conn.write_message(stop, binary=binary)
                await tab.until(lambda: b"INT" in tab.data)
                self.assertNotIn("dropped", [t["t"] for t in tab.texts])

    async def test_a_hidden_answer_reaches_only_a_secret_prompt(self):
        # Écho actif : la réponse s'afficherait, et l'anneau la garderait.
        tab = await self.tab()
        await tab.conn.write_message(json.dumps({"t": "secret"}))
        await tab.conn.write_message(b"hunter2\r", binary=True)
        lost = {"t": "dropped", "bytes": 8, "secret": True}
        await tab.until(lambda: lost in tab.texts)
        await tab.conn.write_message(b"typed\r", binary=True)
        await tab.until(lambda: b"typed" in tab.data)
        self.assertNotIn(b"hunter2", tab.data)
        with patch.object(sessions, "WORKER", ("-c", ASKING)):
            tab = await self.tab()
        await tab.until(lambda: any(t.get("echo") is False for t in tab.texts))
        await tab.conn.write_message(json.dumps({"t": "secret"}))
        await tab.conn.write_message(b"hunter2\r", binary=True)
        await tab.until(lambda: b"length 7" in tab.data)
        self.assertNotIn(b"hunter2", tab.data)


class TestSpare(TerminalCase):
    async def sessions_list(self):
        resp = await self.fetch("/api/sessions", Cookie=self.session_cookie)
        self.assertEqual(resp.code, 200)

    async def test_the_list_warms_a_spare_that_the_next_session_takes(self):
        await self.sessions_list()
        spare = self.hub.spare
        self.assertTrue(spare.ready)
        self.assertEqual(json.loads(await self.ctl("status"))["sessions"], 0)
        tab = await self.tab()
        self.assertIs(self.hub.terminals[tab.texts[0]["id"]], spare)
        self.assertIsNone(self.hub.spare)
        await tab.until(lambda: b"ready en 90x20" in tab.data)
        await self.sessions_list()
        self.assertIsNot(self.hub.spare, spare)

    async def test_no_spare_beyond_the_session_limit(self):
        for _ in range(sessions.MAX_SESSIONS):
            await self.tab()
        await self.sessions_list()
        self.assertIsNone(self.hub.spare)

    async def test_a_dead_spare_leaves_a_cold_start(self):
        await self.sessions_list()
        spare = self.hub.spare
        os.killpg(spare.proc.pid, signal.SIGKILL)
        await asyncio.wait_for(spare.ended.wait(), 10)
        self.assertIsNone(self.hub.spare)
        tab = await self.tab()
        self.assertIsNot(self.hub.terminals[tab.texts[0]["id"]], spare)
        await tab.until(lambda: b"ready en 90x20" in tab.data)

    async def test_a_dead_spare_not_yet_reaped_is_never_adopted(self):
        await self.sessions_list()
        spare = self.hub.spare
        os.killpg(spare.proc.pid, signal.SIGKILL)
        # Sans rendre la main à la boucle, qui l'attendrait : un zombie dont
        # `returncode` vaut encore None.
        deadline = time.monotonic() + 5
        while not ttywatch._ended(spare.proc.pid):
            self.assertLess(time.monotonic(), deadline, "still alive")
            time.sleep(0.01)
        self.assertIsNone(spare.proc.returncode)
        session = await self.hub.open_terminal("en", 80, 24)
        self.assertIsNot(session, spare)

    async def test_a_spare_closed_while_starting_delays_nothing(self):
        # Une session vient pendant que la réserve se lance : celle-ci est
        # fermée, et la suivante part dès la liste suivante.
        warming = asyncio.ensure_future(self.hub.warm())
        await asyncio.sleep(0)
        spare = self.hub.spare
        self.assertFalse(spare.ready)
        session = await self.hub.open_terminal("en", 80, 24)
        self.assertIsNot(session, spare)
        await asyncio.wait_for(warming, 10)
        self.assertTrue(spare.ended.is_set())
        self.assertLessEqual(self.hub.spare_after, time.monotonic())
        await self.sessions_list()
        self.assertNotIn(self.hub.spare, (None, spare))

    async def test_a_spare_that_ends_by_itself_delays_the_next(self):
        with patch.object(sessions, "WORKER", ("-c", "raise SystemExit(1)")):
            await self.sessions_list()
            spare = self.hub.spare
            await asyncio.wait_for(spare.ended.wait(), 10)
            await self.sessions_list()
        self.assertIsNone(self.hub.spare)

    async def test_stopping_the_hub_leaves_no_spare(self):
        await self.sessions_list()
        pid = self.hub.spare.proc.pid
        self.assertEqual(await self.ctl("stop"), "ok")
        await asyncio.wait_for(self.hub.stopped.wait(), 10)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_the_hub_stops_after_the_spare_it_is_starting(self):
        warming = asyncio.ensure_future(self.hub.warm())
        await asyncio.sleep(0)
        spare = self.hub.spare
        self.assertEqual(self.hub.opening, 1)
        self.assertEqual(await self.ctl("stop"), "ok")
        await asyncio.wait_for(self.hub.stopped.wait(), 10)
        self.assertTrue(warming.done())
        with self.assertRaises(ProcessLookupError):
            os.kill(spare.proc.pid, 0)


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
        # Mode brut : la commande part avant que l'enfant lise le terminal.
        writer.write(_masked(0x1, b'{"t": "raw", "on": true}'))
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


class TestQuestions(TerminalCase):
    """Les questions du worker vont à la page, ses réponses au worker ;
    l'enfant jetable écrit une question par `send`, et `recv` répète la
    ligne que le hub lui porte."""

    async def ask(self, tab, qid):
        message = {"t": "ask", "qid": qid, "kind": "text", "text": "Name: "}
        line = b"send " + json.dumps(message).encode() + b"\n"
        await tab.conn.write_message(line, binary=True)
        await tab.until(lambda: message in tab.texts)
        return message

    async def answer(self, tab, **message):
        await tab.conn.write_message(json.dumps(message))

    async def test_only_the_open_question_is_answered(self):
        tab = await self.tab()
        await self.ask(tab, 1)
        await tab.conn.write_message(b"recv\n", binary=True)
        await self.answer(tab, t="answer", qid=2, value="stale")
        await self.answer(tab, t="answer", qid="1", value="stale")
        await self.answer(tab, t="answer", qid=1, value="forged")
        got = b'got {"t": "answer", "qid": 1, "value": "forged"}'
        await tab.until(lambda: got in tab.data)
        await self.ask(tab, 2)
        await tab.conn.write_message(b"recv\n", binary=True)
        await self.answer(tab, t="answer", qid=1, value="stale")
        await self.answer(tab, t="cancel", qid=2)
        await tab.until(lambda: b'got {"t": "cancel", "qid": 2}' in tab.data)
        self.assertNotIn(b"stale", tab.data)

    async def test_an_answer_is_one_line_of_bounded_text(self):
        tab = await self.tab()
        await self.ask(tab, 1)
        await tab.conn.write_message(b"recv\n", binary=True)
        longest = "x" * protocol.ANSWER_LIMIT
        # Rien qui, écrit dans le terminal, y lancerait une séquence.
        escapes = ("\x1b]0;x\x07", "\x9b2J", "del\x7f", "tab\t")
        for value in (longest + "x", 5, None, "two\nlines", "cr\r", *escapes):
            await self.answer(tab, t="answer", qid=1, value=value)
        await self.answer(tab, t="answer", qid=1, value=longest)
        got = f'got {{"t": "answer", "qid": 1, "value": "{longest}"}}\r\n'
        await tab.until(
            lambda: b"got" in tab.data and tab.data.endswith(b"\n")
        )
        self.assertEqual(tab.data.split(b"\n")[-2] + b"\n", got.encode())

    async def test_a_tab_that_takes_over_gets_the_open_question(self):
        first = await self.tab()
        asked = await self.ask(first, 1)
        sid = first.texts[0]["id"]
        second = await self.tab(session=sid, after=0)
        self.assertEqual(second.texts[1], asked)

    async def test_a_tab_that_comes_back_gets_the_open_question(self):
        first = await self.tab()
        asked = await self.ask(first, 1)
        sid = first.texts[0]["id"]
        session = self.hub.terminals[sid]
        first.conn.close()
        deadline = time.monotonic() + 10
        while session.client is not None:
            self.assertLess(time.monotonic(), deadline, "still attached")
            await asyncio.sleep(0.02)
        again = await self.tab(session=sid, after=0)
        self.assertEqual(again.texts[1], asked)

    async def test_an_answer_is_never_logged(self):
        records = []
        handler = logging.Handler(logging.DEBUG)
        handler.emit = records.append
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        self.addCleanup(root.setLevel, root.level)
        root.setLevel(logging.DEBUG)
        tab = await self.tab()
        await self.ask(tab, 1)
        await tab.conn.write_message(b"recv\n", binary=True)
        await self.answer(tab, t="answer", qid=1, value="hunter2")
        await tab.until(lambda: b"hunter2" in tab.data)
        self.assertTrue(records)
        logged = [record.getMessage() for record in records]
        self.assertFalse([line for line in logged if "hunter2" in line])


class TestProtocol(unittest.TestCase):
    def test_the_hub_relays_only_what_the_protocol_names(self):
        relayed = [
            b'{"t": "ask", "qid": 3, "kind": "text", "text": "Name: "}',
            b'{"t": "menu", "qid": 4, "items": []}',
            b'{"t": "notice", "text": "done", "level": "info"}',
            b'{"t": "run_start", "cmd": "true"}',
            b'{"t": "run_end", "rc": 0, "secs": 0.1}',
            b'{"t": "open_view", "view": "telemetry"}',
            b'{"t": "answered", "qid": 3}',
        ]
        refused = [
            b'{"t": "ask", "kind": "text"}',
            b'{"t": "answered"}',
            b'{"t": "ask", "qid": true}',
            b'{"t": "menu", "qid": 0}',
            b'{"t": "open_view", "view": "shell"}',
            b'{"t": "spawn", "argv": ["sh"]}',
            b"[1]",
            b"not json",
        ]
        for line in relayed:
            self.assertEqual(protocol.from_worker(line), json.loads(line))
        for line in refused:
            self.assertIsNone(protocol.from_worker(line), line)

    def test_replies_travel_only_for_the_open_question(self):
        answer = {"t": "answer", "qid": 2, "value": "ok"}
        line = protocol.reply_line(answer, 2)
        self.assertEqual(protocol.reply(line), answer)
        self.assertIsNone(protocol.reply_line(answer, 3))
        self.assertIsNone(protocol.reply_line(answer, None))
        cancel = protocol.reply_line({"t": "cancel", "qid": 2, "value": 1}, 2)
        self.assertEqual(json.loads(cancel), {"t": "cancel", "qid": 2})
        self.assertIsNone(protocol.reply_line({"t": "hello", "qid": 2}, 2))
        # Demi-substitut UTF-16 isolé : `_dump` ne saurait pas l'encoder.
        surrogate = {"t": "answer", "qid": 2, "value": "a\ud800b"}
        self.assertIsNone(protocol.reply_line(surrogate, 2))


class TestTaskLogs(TerminalCase):
    """Le journal d'une vraie session : l'enfant jetable écrit sur le canal
    ce qu'un worker enverrait, et chaque ligne tapée s'affiche par l'écho."""

    MENU = {
        "t": "menu",
        "qid": 1,
        "crumbs": ["TODO", "Code"],
        "items": [{"key": "1", "label": "Show code status"}],
        "text": "[1] Show code status\n",
    }

    async def send(self, tab, message):
        line = b"send " + json.dumps(message).encode() + b"\n"
        await tab.conn.write_message(line, binary=True)
        await tab.until(lambda: message in tab.texts)

    async def closed(self):
        """L'entrée d'index de la tâche, une fois close."""
        deadline = time.monotonic() + 10
        while not tasklog.entries(self.hub.tasks_dir):
            self.assertLess(time.monotonic(), deadline, "never closed")
            await asyncio.sleep(0.05)
        [entry] = tasklog.entries(self.hub.tasks_dir)
        return entry

    async def test_a_task_runs_from_a_menu_answer_to_the_next_menu(self):
        patcher = patch.object(tasklog, "SETTLE_SECONDS", 0.2)
        patcher.start()
        self.addCleanup(patcher.stop)
        tab = await self.tab()
        await self.send(tab, self.MENU)
        await self.send(tab, {"t": "answered", "qid": 1, "key": "1"})
        await self.send(tab, {"t": "run_start", "cmd": "make forged"})
        await tab.conn.write_message(b"big 3\n", binary=True)
        await tab.until(lambda: b"END" in tab.data)
        # La page répond à un secret, puis à une question texte dont
        # l'invite ne nomme aucun secret.
        for qid, kind, text, value in (
            (2, "secret", "Passphrase: ", "hunter2"),
            (3, "text", "Name: ", "x"),
        ):
            await self.send(
                tab, {"t": "ask", "qid": qid, "kind": kind, "text": text}
            )
            answer = {"t": "answer", "qid": qid, "value": value}
            await tab.conn.write_message(json.dumps(answer))
            await self.send(tab, {"t": "answered", "qid": qid})
        await self.send(tab, {"t": "run_end", "rc": 0, "secs": 0.1})
        await self.send(tab, {**self.MENU, "qid": 4})
        entry = await self.closed()  # le texte ne paraît pas : SETTLE
        self.assertEqual(
            (entry["crumbs"], entry["entry"], entry["state"]),
            (["TODO", "Code"], "Show code status", "done"),
        )
        self.assertEqual(entry["commands"][0]["cmd"], "make forged")
        page = tasklog.read(self.hub.tasks_dir, entry["id"], 1, 100)
        texts = [r["d"] for r in page["lines"] if r["s"] == "out"]
        self.assertIn("xxx", texts)
        events = [r["d"] for r in page["lines"] if r["s"] == "event"]
        self.assertIn({"t": "answer", "value": "•••"}, events)
        self.assertIn({"t": "answer", "value": "x"}, events)
        for path in self.tmp.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                if path.suffix == ".zst":
                    data = zstd.decompress(data)
                self.assertNotIn(b"hunter2", data, path)

    async def test_the_menu_text_in_the_output_closes_the_task(self):
        tab = await self.tab()  # SETTLE_SECONDS, 2 s, ne joue pas ici
        menu = {**self.MENU, "text": "[1] forged menu text\n"}
        await self.send(tab, menu)
        await self.send(tab, {"t": "answered", "qid": 1, "key": "1"})
        await tab.conn.write_message(b"big 2\n", binary=True)
        await tab.until(lambda: b"END" in tab.data)
        await self.send(tab, {**menu, "qid": 3})
        # Tapé, le texte du menu revient par l'écho, comme TODO l'imprime.
        await tab.conn.write_message(b"[1] forged menu text\n", binary=True)
        entry = await asyncio.wait_for(self.closed(), 1.5)
        page = tasklog.read(self.hub.tasks_dir, entry["id"], 1, 100)
        texts = [r["d"] for r in page["lines"] if r["s"] == "out"]
        self.assertIn("xx", texts)
        self.assertNotIn("[1] forged menu text", texts)

    async def test_a_running_task_reaches_the_disk_within_a_second(self):
        tab = await self.tab()
        await self.send(tab, self.MENU)
        await self.send(tab, {"t": "answered", "qid": 1, "key": "1"})
        await tab.conn.write_message(b"big 4\n", binary=True)
        await tab.until(lambda: b"END" in tab.data)
        [session] = self.hub.terminals.values()
        task_id = session.recorder.task.info["id"]
        deadline = time.monotonic() + 1.5
        while True:
            page = tasklog.read(self.hub.tasks_dir, task_id, 1, 100)
            lines = page["lines"] if page else []
            if "xxxx" in [r["d"] for r in lines if r["s"] == "out"]:
                break
            self.assertLess(time.monotonic(), deadline, "still held")
            await asyncio.sleep(0.05)
        self.assertEqual(page["state"], "open")


class TestTasksApi(ApiCase):
    """L'historique : liste, journal paginé, purge."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        resp = await self.fetch("/api/session", Cookie=self.session_cookie)
        self.csrf = json.loads(resp.body)["csrf"]
        self.ids = []
        for when, text in ((time.time() - 60, b"old\r\n"), (None, b"new\r\n")):
            now = time.time() if when is None else when
            info = {"id": tasklog.new_id(now), "session": "s1", "start": now}
            info.update(crumbs=["TODO"], entry="Show code status", key="1")
            task = tasklog.TaskLog(self.hub.tasks_dir, info)
            task.output(text * 3)
            task.close("done")
            self.ids.append(info["id"])

    async def test_the_list_is_newest_first_and_pages_by_id(self):
        old, new = self.ids
        listed = await self.get_json("/api/tasks")
        self.assertEqual([e["id"] for e in listed["tasks"]], [new, old])
        self.assertFalse(listed["more"])
        first = await self.get_json("/api/tasks?limit=1")
        self.assertEqual(
            ([e["id"] for e in first["tasks"]], first["more"]), ([new], True)
        )
        rest = await self.get_json(f"/api/tasks?limit=1&before={new}")
        self.assertEqual([e["id"] for e in rest["tasks"]], [old])
        for query in ("limit=0", "limit=x", "limit=201", "before=../x"):
            resp = await self.fetch(
                f"/api/tasks?{query}", Cookie=self.session_cookie
            )
            self.assertEqual(resp.code, 400, query)

    async def test_a_log_reads_in_pages(self):
        new = self.ids[1]
        page = await self.get_json(f"/api/tasks/{new}?from=2&limit=2")
        self.assertEqual([r["d"] for r in page["lines"]], ["new", "new"])
        self.assertEqual(
            (page["next"], page["eof"], page["state"]), (4, False, "done")
        )

    async def test_without_a_cookie_or_with_a_bad_id_nothing_is_read(self):
        new = self.ids[1]
        for path in ("/api/tasks", f"/api/tasks/{new}"):
            self.assertEqual((await self.fetch(path)).code, 403, path)
        other = tasklog.new_id(time.time() - 3 * 24 * 3600)
        for task_id in ("..%2F..%2Fserver.log", "x", other):
            resp = await self.fetch(
                f"/api/tasks/{task_id}", Cookie=self.session_cookie
            )
            self.assertEqual(resp.code, 404, task_id)

    async def test_purge_needs_the_csrf_token(self):
        post = {"Cookie": self.session_cookie, "Origin": self.origin}
        resp = await self.fetch("/api/tasks/purge", "POST", "{}", **post)
        self.assertEqual(resp.code, 403)
        post["X-CSRF-Token"] = self.csrf
        for body in ('{"before": "tomorrow"}', '{"before": 5}', "[]"):
            resp = await self.fetch("/api/tasks/purge", "POST", body, **post)
            self.assertEqual(resp.code, 400, body)
        self.assertEqual(len((await self.get_json("/api/tasks"))["tasks"]), 2)
        resp = await self.fetch("/api/tasks/purge", "POST", "{}", **post)
        self.assertEqual(json.loads(resp.body), {"removed": 2})
        self.assertEqual((await self.get_json("/api/tasks"))["tasks"], [])

    async def test_the_control_socket_purges_past_the_retention(self):
        old = datetime.date.today() - datetime.timedelta(31)
        stamp = time.mktime(old.timetuple()) + 12 * 3600
        info = {"id": tasklog.new_id(stamp), "session": "s1", "start": stamp}
        task = tasklog.TaskLog(self.hub.tasks_dir, info)
        task.output(b"old\r\n")
        task.close("done")
        self.assertEqual(await self.ctl("purge"), "1")
        self.assertEqual(await self.ctl("purge all"), "2")


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

    async def test_a_restart_closes_open_tasks_and_orphans(self):
        info = {"id": tasklog.new_id(time.time()), "session": "s1"}
        info["start"] = time.time()
        task = tasklog.TaskLog(paths.tasks_dir(self.root), info)
        task.output(b"working\r\n")
        task.abandon()  # le hub est tué pendant la tâche
        orphan = paths.runtime_dir(self.root) / "state.json.x1.tmp"
        orphan.write_text("{}")
        past = time.time() - paths.ORPHAN_SECONDS - 1
        os.utime(orphan, (past, past))
        hub = server.Hub(self.root, static_dir=self.static)
        await hub.start()
        self.addAsyncCleanup(hub.stopped.wait)
        self.addCleanup(hub.request_stop)
        [entry] = tasklog.entries(hub.tasks_dir)
        self.assertEqual(
            (entry["id"], entry["state"]), (info["id"], "interrupted")
        )
        self.assertFalse(orphan.exists())

    def abandoned(self, when):
        """Une tâche commencée à `when`, une ligne écrite, puis laissée
        ouverte comme par un hub tué."""
        info = {"id": tasklog.new_id(when), "session": "s1", "start": when}
        task = tasklog.TaskLog(paths.tasks_dir(self.root), info)
        task.output(b"working\r\n")
        task.abandon()
        return task

    async def test_a_failed_orphan_sweep_still_closes_open_tasks(self):
        task = self.abandoned(time.time())
        hub = server.Hub(self.root, static_dir=self.static)
        with (
            patch.object(
                server.paths, "remove_orphans", side_effect=OSError("boom")
            ),
            self.assertLogs(server.log, "ERROR"),
        ):
            await hub.start()
        self.addAsyncCleanup(hub.stopped.wait)
        self.addCleanup(hub.request_stop)
        [entry] = tasklog.entries(hub.tasks_dir)
        self.assertEqual(
            (entry["id"], entry["state"]), (task.info["id"], "interrupted")
        )

    async def test_a_log_that_cannot_be_sealed_leaves_the_purge_to_run(self):
        # Disque plein : la tâche restée ouverte ne se scelle pas, le hub
        # démarre et purge à son démarrage le jour de 40 jours.
        day = datetime.date.today() - datetime.timedelta(40)
        noon = datetime.datetime.combine(day, datetime.time(12)).timestamp()
        old = self.abandoned(noon)
        tasklog.recover(paths.tasks_dir(self.root))  # close, 40 jours
        stuck = self.abandoned(time.time())
        full = OSError(errno.ENOSPC, "No space left on device")
        hub = server.Hub(self.root, static_dir=self.static)
        with (
            patch.object(tasklog, "_seal", side_effect=full),
            self.assertLogs(tasklog.log, "WARNING"),
        ):
            await hub.start()
        self.addAsyncCleanup(hub.stopped.wait)
        self.addCleanup(hub.request_stop)
        deadline = time.monotonic() + 5
        while old.path.parent.exists():
            self.assertLess(time.monotonic(), deadline, "never purged")
            await asyncio.sleep(0.05)
        self.assertTrue(stuck.path.exists())

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
