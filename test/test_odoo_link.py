#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""`script/todo/odoo_link.py` : une base Odoo jointe par son API web ou
par `odoo-bin shell`.

L'API web parle à un faux serveur JSON-RPC lancé dans le processus (fil,
port 0), qui note chaque appel reçu. `odoo-bin shell` est joué de trois
façons : un hôte doublure qui rend une sortie préparée, le vrai script
`sh` lancé avec un faux `odoo_bin.sh`, et le corps Python exécuté contre un
faux `env`. Aucun Odoo, aucune base, aucun sudo. Toutes les valeurs sont
inventées (`*.exemple.test`, 192.0.2.x, 2001:db8::).
"""

import ast
import base64
import contextlib
import hashlib
import http.server
import io
import json
import logging
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from script.todo import ntfy_mobile as nm
from script.todo import odoo_link as ol

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE = "base_inventee"
LOGIN = "gestion@exemple.test"
PASSWORD = "Mot-de-passe-invente-77"
TURN_SECRET = "Secret-invente-Zq8Wv3Kp0Lm6Nx4Rt2Yb"
FIXED_PASSWORD = "Compte-fixe-invente-Hj5Gf7Ds9Aq1"
URLS = (
    "stun:turn.exemple.test:3478\n"
    "turn:turn.exemple.test:3478?transport=udp\n"
    "turn:turn.exemple.test:3478?transport=tcp\n"
    "turns:turn.exemple.test:5349?transport=tcp"
)
OWNED_ODOO = "https://erp.exemple.test"


def owned():
    return ol.owned_username(OWNED_ODOO, DATABASE)


def tool_rows(username=None, credential=FIXED_PASSWORD):
    name = username or owned()
    return [
        {
            "server_type": "stun",
            "uri": "turn.exemple.test:3478",
            "username": name,
        },
        {
            "server_type": "turn",
            "uri": "turn.exemple.test:3478?transport=udp",
            "username": name,
            "credential": credential,
        },
        {
            "server_type": "turn",
            "uri": "turn.exemple.test:3478?transport=tcp",
            "username": name,
            "credential": credential,
        },
    ]


class FakeOdoo:
    """L'état d'une base Odoo et la façon dont elle répond à `/jsonrpc` :
    `common.version`, `common.login`, `object.execute_kw`. Chaque appel
    reçu est noté dans `calls` (service, méthode, modèle, méthode objet)."""

    def __init__(self, version="18.0"):
        self.version = version
        self.users = {LOGIN: {"password": PASSWORD, "uid": 7, "admin": True}}
        self.modules = {"erplibre_turn": {"id": 41, "state": "uninstalled"}}
        self.params = {
            "erplibre_turn.ttl_hours": "12",
            "web.base.url": "https://erp.exemple.test",
        }
        self.rows = {}
        self.next_id = 100
        self.calls = []
        self.fail = {}
        self.status = 200
        self.raw = None
        self.ignore_domain = False

    def add_row(self, server_type, uri, username=False, credential=False):
        self.next_id += 1
        self.rows[self.next_id] = {
            "id": self.next_id,
            "server_type": server_type,
            "uri": uri,
            "username": username,
            "credential": credential,
        }
        return self.next_id

    def answer(self, payload):
        params = payload["params"]
        service, method, args = (
            params["service"],
            params["method"],
            params["args"],
        )
        if service == "common" and method == "version":
            self.calls.append(("common", "version", None, None))
            major = int(self.version.split(".")[0])
            return {
                "server_version": self.version,
                "server_version_info": [major, 0, 0, "final", 0, ""],
                "server_serie": self.version,
                "protocol_version": 1,
            }
        if service == "common" and method == "login":
            self.calls.append(("common", "login", None, None))
            database, login, password = args
            if database != DATABASE:
                raise RpcFault(
                    "psycopg2.OperationalError",
                    f'database "{database}" does not exist',
                )
            user = self.users.get(login)
            if not user or user["password"] != password:
                return False
            return user["uid"]
        if service == "object" and method == "execute_kw":
            database, uid, password, model, name, margs = args[:6]
            kwargs = args[6] if len(args) > 6 else {}
            self.calls.append(("object", "execute_kw", model, name))
            user = next(
                (u for u in self.users.values() if u["uid"] == uid), None
            )
            if (
                database != DATABASE
                or not user
                or user["password"] != password
            ):
                raise RpcFault("odoo.exceptions.AccessDenied", "Access Denied")
            return self.execute(user, model, name, margs, kwargs)
        raise RpcFault("KeyError", f"{service}.{method}")

    def execute(self, user, model, name, args, kwargs):
        if (model, name) in self.fail:
            raise RpcFault(
                "odoo.exceptions.AccessError", self.fail[model, name]
            )
        handler = getattr(self, f"_{model.replace('.', '_')}__{name}", None)
        if handler is None:
            raise RpcFault("KeyError", f"{model}.{name}")
        return handler(user, args, kwargs)

    def _res_users__has_group(self, user, args, kwargs):
        return user["admin"] and args[1] == "base.group_system"

    def _res_users__read(self, user, args, kwargs):
        login = next(k for k, u in self.users.items() if u is user)
        return [{"id": user["uid"], "login": login}]

    def _ir_module_module__search_read(self, user, args, kwargs):
        module = self.modules.get(args[0][0][2])
        return [dict(module)] if module else []

    def _ir_module_module__button_immediate_install(self, user, args, kwargs):
        for module in self.modules.values():
            if module["id"] in args[0]:
                module["state"] = "installed"
        return {"type": "ir.actions.client", "tag": "reload"}

    def _ir_config_parameter__search_read(self, user, args, kwargs):
        keys = args[0][0][2]
        return [
            {"id": i, "key": k, "value": v}
            for i, (k, v) in enumerate(self.params.items())
            if k in keys
        ]

    def _ir_config_parameter__set_param(self, user, args, kwargs):
        key, value = args
        old = self.params.get(key, False)
        if value is None or value is False:
            self.params.pop(key, None)
        else:
            self.params[key] = value
        return old

    def _mail_ice_server__search_read(self, user, args, kwargs):
        domain = args[0]
        fields = ["id"] + list(kwargs["fields"])
        return [
            {f: row[f] for f in fields}
            for row in self.rows.values()
            if self.ignore_domain
            or all(row.get(f) == v for f, op, v in domain if op == "=")
        ]

    def _mail_ice_server__create(self, user, args, kwargs):
        return [
            self.add_row(
                vals["server_type"],
                vals["uri"],
                vals.get("username", False),
                vals.get("credential", False),
            )
            for vals in args[0]
        ]

    def _mail_ice_server__unlink(self, user, args, kwargs):
        self.unlinked = list(args[0])
        for row_id in args[0]:
            del self.rows[row_id]
        return True


class RpcFault(Exception):
    def __init__(self, name, message):
        super().__init__(message)
        self.name = name
        self.message = message


class FakeServer:
    """`FakeOdoo` derrière un vrai serveur HTTP sur 127.0.0.1, port 0."""

    def __init__(self, odoo):
        self.odoo = odoo
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                if outer.odoo.status != 200 or self.path != "/jsonrpc":
                    self.send_response(
                        outer.odoo.status if self.path == "/jsonrpc" else 404
                    )
                    self.end_headers()
                    return
                if outer.odoo.raw is not None:
                    body = outer.odoo.raw
                else:
                    try:
                        answer = {"result": outer.odoo.answer(payload)}
                    except RpcFault as fault:
                        answer = {
                            "error": {
                                "code": 200,
                                "message": "Odoo Server Error",
                                "data": {
                                    "name": fault.name,
                                    "message": fault.message,
                                    "debug": "Traceback ...",
                                },
                            }
                        }
                    answer.update(jsonrpc="2.0", id=payload.get("id"))
                    body = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class WebCase(unittest.TestCase):
    def setUp(self):
        self.odoo = FakeOdoo()
        self.server = FakeServer(self.odoo)
        self.server.__enter__()
        self.addCleanup(self.server.__exit__)

    def api(self, login=LOGIN, password=PASSWORD, database=DATABASE):
        return ol.WebApi(self.server.url, database, login, password, timeout=5)

    def object_calls(self):
        return [c for c in self.odoo.calls if c[0] == "object"]


class TestIdentity(unittest.TestCase):
    def test_owned_username_is_a_digest_of_the_normalised_key(self):
        name = ol.owned_username("https://erp.exemple.test", DATABASE)
        self.assertRegex(name, r"^erplibre-[0-9a-f]{8}$")
        digest = hashlib.sha256(
            f"https://erp.exemple.test|{DATABASE}".encode()
        ).hexdigest()
        self.assertEqual(name, "erplibre-" + digest[:8])

    def test_one_odoo_whatever_the_spelling_of_its_url(self):
        spellings = (
            "https://erp.exemple.test",
            "HTTPS://ERP.Exemple.TEST/",
            "https://erp.exemple.test:443",
            "https://erp.exemple.test/odoo/discuss?debug=1#x",
        )
        keys = {ol.odoo_key(url, DATABASE) for url in spellings}
        self.assertEqual(keys, {f"https://erp.exemple.test|{DATABASE}"})
        names = {ol.owned_username(url, DATABASE) for url in spellings}
        self.assertEqual(len(names), 1)

    def test_scheme_port_and_database_tell_odoo_apart(self):
        names = {
            ol.owned_username("https://erp.exemple.test", DATABASE),
            ol.owned_username("http://erp.exemple.test", DATABASE),
            ol.owned_username("http://erp.exemple.test:8069", DATABASE),
            ol.owned_username("https://erp.exemple.test", "autre_base"),
        }
        self.assertEqual(len(names), 4)

    def test_ipv6_host_keeps_its_brackets(self):
        self.assertEqual(
            ol.normalize_url("http://[2001:DB8::1]:8069/"),
            "http://[2001:db8::1]:8069",
        )

    def test_bad_urls_are_refused(self):
        for url in (
            "erp.exemple.test",
            "ftp://erp.exemple.test",
            "https://",
            "https://compte:secret@erp.exemple.test",
            "https://erp.exemple.test:99999",
        ):
            with self.subTest(url), self.assertRaises(ol.OdooError) as caught:
                ol.normalize_url(url)
            self.assertEqual(caught.exception.key, "call_infra_odoo_url")
            self.assertNotIn("secret", str(caught.exception.values))

    def test_bad_database_names_are_refused(self):
        for name in ("", "a", "base inventee", "-base", "base;rm", "b\nx"):
            with self.subTest(name), self.assertRaises(ol.OdooError) as caught:
                ol.odoo_key(OWNED_ODOO, name)
            self.assertEqual(caught.exception.key, "call_infra_odoo_database")

    def test_secret_digest(self):
        self.assertEqual(
            ol.secret_digest(TURN_SECRET),
            "sha256:" + hashlib.sha256(TURN_SECRET.encode()).hexdigest(),
        )

    def test_major_of(self):
        self.assertEqual(ol.major_of("18.0"), 18)
        self.assertEqual(ol.major_of("18.0+e"), 18)
        self.assertEqual(ol.major_of("17.0"), 17)
        self.assertEqual(ol.major_of("saas~18.2"), 0)
        self.assertEqual(ol.major_of(""), 0)


class TestWebApiRefusals(WebCase):
    def test_odoo_17_is_refused_before_any_login_or_write(self):
        self.odoo.version = "17.0"
        api = self.api()
        for action in (
            api.facts,
            lambda: api.set_params({"erplibre_turn.secret": TURN_SECRET}),
            lambda: api.replace_rows(owned(), tool_rows()),
            api.install_module,
        ):
            with self.assertRaises(ol.OdooError) as caught:
                action()
            self.assertEqual(caught.exception.key, "call_infra_odoo_version")
            self.assertEqual(caught.exception.values, {"version": "17.0"})
        self.assertEqual(
            {c[1] for c in self.odoo.calls}, {"version"}, self.odoo.calls
        )
        self.assertNotIn("erplibre_turn.secret", self.odoo.params)

    def test_wrong_password_is_a_login_refusal(self):
        with self.assertRaises(ol.OdooError) as caught:
            self.api(password="Autre-mot-invente").facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_login")
        self.assertEqual(caught.exception.values, {"database": DATABASE})
        self.assertEqual(self.object_calls(), [])

    def test_unknown_database_is_a_login_refusal(self):
        with self.assertRaises(ol.OdooError) as caught:
            self.api(database="base_inventee_typo").facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_login")
        self.assertEqual(
            caught.exception.values, {"database": "base_inventee_typo"}
        )
        self.assertEqual(self.object_calls(), [])

    def test_an_account_outside_group_system_is_refused(self):
        self.odoo.users[LOGIN]["admin"] = False
        with self.assertRaises(ol.OdooError) as caught:
            self.api().facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_not_admin")
        self.assertEqual(caught.exception.values, {"login": LOGIN})
        self.assertEqual(
            [c[2:] for c in self.object_calls()],
            [("res.users", "has_group")],
        )

    def test_unreachable_server(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        with self.assertRaises(ol.OdooError) as caught:
            ol.WebApi(url, DATABASE, LOGIN, PASSWORD, timeout=2).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_unreachable")
        self.assertEqual(caught.exception.values["url"], url)

    def test_http_error_and_non_json_are_unreachable(self):
        self.odoo.status = 404
        with self.assertRaises(ol.OdooError) as caught:
            self.api().facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_unreachable")
        self.assertIn("404", caught.exception.values["reason"])
        self.odoo.status = 200
        self.odoo.raw = b"<html>not odoo</html>"
        with self.assertRaises(ol.OdooError) as caught:
            self.api().facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_unreachable")

    def redirector(self, code):
        """Un serveur qui renvoie chaque POST vers le faux Odoo par
        `code` ; son URL."""
        target = self.server.url

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.send_response(code)
                self.send_header("Location", target + self.path)
                self.send_header("Content-Length", "0")
                self.end_headers()

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_a_redirection_to_another_origin_names_the_destination(self):
        # 301 : urllib rejoue en GET sans corps, l'erreur vient de la
        # destination ; 308 : urllib ne suit pas un POST.
        for code in (301, 308):
            with self.subTest(code=code):
                url = self.redirector(code)
                api = ol.WebApi(url, DATABASE, LOGIN, PASSWORD, timeout=5)
                with self.assertRaises(ol.OdooError) as caught:
                    api.facts()
                self.assertEqual(
                    caught.exception.key, "call_infra_odoo_redirected"
                )
                self.assertEqual(
                    caught.exception.values,
                    {"url": url, "target": self.server.url},
                )

    def test_an_error_answer_to_version_is_unreachable(self):
        self.odoo.raw = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "error": {"message": "pas Odoo"}}
        ).encode()
        with self.assertRaises(ol.OdooError) as caught:
            self.api().facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_unreachable")
        self.assertEqual(caught.exception.values["reason"], "pas Odoo")

    def test_password_never_in_a_refusal_nor_a_log_line(self):
        self.odoo.users[LOGIN]["admin"] = False
        with self.assertLogs(ol.__name__, logging.DEBUG) as logs:
            with self.assertRaises(ol.OdooError) as caught:
                self.api().facts()
        text = "\n".join(logs.output) + str(caught.exception.values)
        self.assertNotIn(PASSWORD, text)


class TestWebApiFacts(WebCase):
    def test_facts(self):
        self.odoo.params["erplibre_turn.secret"] = TURN_SECRET
        self.odoo.params["erplibre_turn.urls"] = URLS
        hand = self.odoo.add_row(
            "turn", "turn.exemple.test:3478", "alice", "Cle-de-alice-inventee"
        )
        facts = self.api().facts()
        self.assertEqual(facts.version, "18.0")
        self.assertEqual(facts.major, 18)
        self.assertEqual(facts.module_state, "uninstalled")
        self.assertEqual(facts.host_name, "127.0.0.1")
        self.assertEqual(
            facts.params,
            {
                "erplibre_turn.secret": ol.secret_digest(TURN_SECRET),
                "erplibre_turn.urls": URLS,
                "erplibre_turn.ttl_hours": "12",
            },
        )
        self.assertEqual(
            facts.rows,
            (
                {
                    "id": hand,
                    "server_type": "turn",
                    "uri": "turn.exemple.test:3478",
                    "username": "alice",
                },
            ),
        )
        self.assertNotIn("Cle-de-alice-inventee", repr(facts))
        self.assertNotIn(TURN_SECRET, repr(facts))

    def test_row_without_username_reads_empty(self):
        self.odoo.add_row("stun", "stun.exemple.test:3478")
        (row,) = self.api().facts().rows
        self.assertEqual(row["username"], "")

    def test_module_states(self):
        del self.odoo.modules["erplibre_turn"]
        self.assertEqual(self.api().facts().module_state, "absent")
        self.odoo.modules["erplibre_turn"] = {"id": 41, "state": "to upgrade"}
        self.assertEqual(self.api().facts().module_state, "to upgrade")

    def test_whoami(self):
        self.assertEqual(self.api().whoami(), LOGIN)

    def test_one_login_per_link(self):
        api = self.api()
        api.facts()
        api.facts()
        self.assertEqual([c[1] for c in self.odoo.calls].count("login"), 1)


class TestWebApiWrites(WebCase):
    def test_set_params_writes_and_removes(self):
        api = self.api()
        with self.assertLogs(ol.__name__, logging.DEBUG) as logs:
            api.set_params(
                {
                    "erplibre_turn.urls": URLS,
                    "erplibre_turn.secret": TURN_SECRET,
                    "erplibre_turn.ttl_hours": None,
                }
            )
        self.assertEqual(self.odoo.params["erplibre_turn.secret"], TURN_SECRET)
        self.assertEqual(self.odoo.params["erplibre_turn.urls"], URLS)
        self.assertNotIn("erplibre_turn.ttl_hours", self.odoo.params)
        self.assertEqual(self.odoo.params["web.base.url"], OWNED_ODOO)
        text = "\n".join(logs.output)
        self.assertNotIn(TURN_SECRET, text)
        self.assertNotIn(PASSWORD, text)

    def test_set_params_only_writes_the_module_parameters(self):
        with self.assertRaises(ValueError):
            self.api().set_params({"web.base.url": "https://x.exemple.test"})
        with self.assertRaises(ValueError):
            self.api().set_params({"erplibre_turn.ttl_hours": 24})
        self.assertEqual(self.object_calls(), [])

    def test_a_failed_write_is_an_odoo_error_without_the_secret(self):
        self.odoo.fail["ir.config_parameter", "set_param"] = (
            f"refused writing {TURN_SECRET}"
        )
        with self.assertRaises(ol.OdooError) as caught:
            self.api().set_params({"erplibre_turn.secret": TURN_SECRET})
        self.assertEqual(caught.exception.key, "call_infra_odoo_rpc_error")
        self.assertIn("refused writing", caught.exception.values["message"])
        self.assertNotIn(TURN_SECRET, str(caught.exception.values))
        self.assertNotIn(TURN_SECRET, str(caught.exception))

    def test_replace_rows_touches_only_the_owned_username(self):
        hand_turn = self.odoo.add_row(
            "turn", "turn.exemple.test:3478", "alice", "Cle-de-alice-inventee"
        )
        hand_stun = self.odoo.add_row("stun", "turn.exemple.test:3478")
        other = self.odoo.add_row(
            "turn",
            "turn.exemple.test:3478?transport=udp",
            ol.owned_username("https://autre.exemple.test", DATABASE),
            "Autre-compte-invente",
        )
        old = [
            self.odoo.add_row("stun", "turn.exemple.test:3478", owned()),
            self.odoo.add_row(
                "turn",
                "turn.exemple.test:3478?transport=udp",
                owned(),
                "Ancien-mot-invente",
            ),
        ]
        with self.assertLogs(ol.__name__, logging.DEBUG) as logs:
            self.api().replace_rows(owned(), tool_rows())
        self.assertEqual(self.odoo.unlinked, old)
        for kept in (hand_turn, hand_stun, other):
            self.assertIn(kept, self.odoo.rows)
        mine = [r for r in self.odoo.rows.values() if r["username"] == owned()]
        self.assertEqual(len(mine), 3)
        self.assertEqual(
            sorted(r["credential"] or "" for r in mine),
            ["", FIXED_PASSWORD, FIXED_PASSWORD],
        )
        text = "\n".join(logs.output)
        self.assertNotIn(FIXED_PASSWORD, text)
        self.assertNotIn("Ancien-mot-invente", text)

    def test_replace_rows_rechecks_the_username_it_reads_back(self):
        """Une recherche qui rendrait trop de lignes (domaine ignoré) ne
        fait toujours effacer que les lignes du nom possédé."""
        self.odoo.ignore_domain = True
        hand = self.odoo.add_row("turn", "turn.exemple.test:3478", "alice")
        mine = self.odoo.add_row("stun", "turn.exemple.test:3478", owned())
        self.api().replace_rows(owned(), [])
        self.assertEqual(self.odoo.unlinked, [mine])
        self.assertEqual(list(self.odoo.rows), [hand])

    def test_replace_rows_with_nothing_removes_the_owned_rows(self):
        hand = self.odoo.add_row("turn", "turn.exemple.test:3478", "alice")
        mine = self.odoo.add_row("stun", "turn.exemple.test:3478", owned())
        self.api().replace_rows(owned(), [])
        self.assertEqual(list(self.odoo.rows), [hand])
        self.assertEqual(self.odoo.unlinked, [mine])
        self.assertNotIn(
            ("object", "execute_kw", "mail.ice.server", "create"),
            self.odoo.calls,
        )

    def test_replace_rows_refuses_rows_it_could_not_find_again(self):
        hand = self.odoo.add_row("turn", "turn.exemple.test:3478", "alice")
        cases = {
            "username alice": ("alice", tool_rows()),
            "empty owner": ("", tool_rows()),
            "row of another": (owned(), tool_rows("alice")),
            "bad type": (
                owned(),
                [{"server_type": "turns", "uri": "x", "username": owned()}],
            ),
            "no uri": (
                owned(),
                [{"server_type": "turn", "uri": "", "username": owned()}],
            ),
        }
        for label, (name, rows) in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                self.api().replace_rows(name, rows)
        self.assertEqual(list(self.odoo.rows), [hand])
        self.assertEqual(self.object_calls(), [])

    def test_install_module(self):
        api = self.api()
        api.install_module()
        self.assertEqual(
            self.odoo.modules["erplibre_turn"]["state"], "installed"
        )
        self.assertEqual(api.facts().module_state, "installed")

    def test_install_module_absent_is_refused(self):
        del self.odoo.modules["erplibre_turn"]
        with self.assertRaises(ol.OdooError) as caught:
            self.api().install_module()
        self.assertEqual(
            caught.exception.key, "call_infra_odoo_install_failed"
        )
        self.assertEqual(caught.exception.values, {"state": "absent"})


# --- odoo-bin shell -------------------------------------------------------

PRINTF_B64 = re.compile(r"^printf %s (\S+) \| base64 -d \|", re.M)


def python_of(script):
    """Le corps Python que le script `sh` envoie à `odoo-bin shell`."""
    (payload,) = PRINTF_B64.findall(script)
    return base64.b64decode(payload).decode("utf-8")


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeHost:
    """Runner doublure : note chaque (script, sudo_user), rend la sortie
    préparée."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def run(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        return self.outputs.pop(0)


def facts_output(version="18.0", module="installed", code=0):
    row = {
        "id": 5,
        "server_type": "turn",
        "uri": "turn.exemple.test:3478",
        "username": "alice",
    }
    lines = [
        f"@@ODOO_VERSION {version}",
        f"@@ODOO_MODULE {module}",
        "@@ODOO_USER __system__",
        f"@@ODOO_PARAM erplibre_turn.secret {b64(ol.secret_digest(TURN_SECRET))}",
        f"@@ODOO_PARAM erplibre_turn.urls {b64(URLS)}",
        f"@@ODOO_ROW {b64(json.dumps(row))}",
        "@@ODOO_DONE facts",
    ]
    return code, "[sudo] mot de passe : \n" + "\n".join(lines) + "\n"


class TestOdooShell(unittest.TestCase):
    def shell(self, host, **kw):
        return ol.OdooShell(host, "/opt/erplibre", DATABASE, **kw)

    def test_facts_parses_the_marker_lines(self):
        host = FakeHost([facts_output()])
        facts = self.shell(host, url="https://ERP.exemple.test/").facts()
        self.assertEqual(facts.version, "18.0")
        self.assertEqual(facts.major, 18)
        self.assertEqual(facts.module_state, "installed")
        self.assertEqual(
            facts.params,
            {
                "erplibre_turn.secret": ol.secret_digest(TURN_SECRET),
                "erplibre_turn.urls": URLS,
            },
        )
        self.assertEqual(
            facts.rows,
            (
                {
                    "id": 5,
                    "server_type": "turn",
                    "uri": "turn.exemple.test:3478",
                    "username": "alice",
                },
            ),
        )
        self.assertEqual(facts.host_name, "erp.exemple.test")
        ((script, sudo_user),) = host.calls
        self.assertIsNone(sudo_user)
        self.assertTrue(python_of(script).rstrip().endswith("env.cr.commit()"))

    def test_whoami_comes_from_the_shell(self):
        host = FakeHost([facts_output()])
        shell = self.shell(host)
        self.assertEqual(shell.whoami(), "__system__")
        self.assertEqual(shell.whoami(), "__system__")
        self.assertEqual(len(host.calls), 1)

    def test_host_name_without_url_is_the_ssh_host(self):
        host = FakeHost([facts_output()])
        host.hostname = "odoo.exemple.test"
        self.assertEqual(
            self.shell(host).facts().host_name, "odoo.exemple.test"
        )

    def test_odoo_17_is_refused(self):
        host = FakeHost([(4, "@@ODOO_VERSION 17.0\n")])
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).set_params({"erplibre_turn.secret": TURN_SECRET})
        self.assertEqual(caught.exception.key, "call_infra_odoo_version")
        self.assertEqual(caught.exception.values, {"version": "17.0"})
        python = python_of(host.calls[0][0])
        self.assertLess(
            python.index("version_info[0] != 18"), python.index("set_param")
        )

    def test_set_params_sends_one_script_with_the_secret_in_its_body(self):
        host = FakeHost([(0, "@@ODOO_VERSION 18.0\n@@ODOO_DONE set_params\n")])
        self.shell(host).set_params(
            {"erplibre_turn.secret": TURN_SECRET, "erplibre_turn.urls": None}
        )
        ((script, sudo_user),) = host.calls
        self.assertIsNone(sudo_user)
        self.assertNotIn(TURN_SECRET, script)
        python = python_of(script)
        self.assertIn(TURN_SECRET, python)
        self.assertTrue(python.rstrip().endswith("env.cr.commit()"))
        command = [
            line for line in script.splitlines() if "odoo_bin.sh" in line
        ]
        self.assertTrue(command)
        self.assertTrue(all(TURN_SECRET not in line for line in command))
        self.assertIn(f"./odoo_bin.sh shell -d {DATABASE} --no-http", script)

    def test_the_runners_never_put_the_secret_in_argv(self):
        argvs, staged = [], []

        def tee(argv, env=None):
            argvs.append(argv)
            with open(argv[-1], encoding="utf-8") as handle:
                staged.append(handle.read())
            return 0, "@@ODOO_VERSION 18.0\n@@ODOO_DONE set_params\n"

        with mock.patch.object(nm, "_tee_run", side_effect=tee):
            ol.OdooShell(nm.LocalHost(), "/opt/erplibre", DATABASE).set_params(
                {"erplibre_turn.secret": TURN_SECRET}
            )
        self.assertTrue(argvs)
        self.assertNotIn(TURN_SECRET, " ".join(argvs[0]))
        self.assertIn(TURN_SECRET, python_of(staged[0]))

        sent = []

        def stage(argv, input=None, stdout=None, env=None):
            sent.append((argv, input))
            return subprocess.CompletedProcess(argv, 0, b"/tmp/tmp.inv\n")

        with mock.patch.object(
            nm.subprocess, "run", side_effect=stage
        ), mock.patch.object(
            nm,
            "_tee_run",
            return_value=(0, "@@ODOO_VERSION 18.0\n@@ODOO_DONE set_params\n"),
        ) as run:
            ol.OdooShell(
                nm.SshHost("odoo.exemple.test"), "/opt/erplibre", DATABASE
            ).set_params({"erplibre_turn.secret": TURN_SECRET})
        self.assertNotIn(TURN_SECRET, " ".join(sent[0][0]))
        self.assertNotIn(TURN_SECRET, " ".join(run.call_args[0][0]))
        self.assertIn(TURN_SECRET, python_of(sent[0][1].decode()))

    def test_replace_rows_script(self):
        host = FakeHost(
            [(0, "@@ODOO_VERSION 18.0\n@@ODOO_DONE replace_rows\n")]
        )
        self.shell(host).replace_rows(owned(), tool_rows())
        ((script, _),) = host.calls
        self.assertNotIn(FIXED_PASSWORD, script)
        python = python_of(script)
        self.assertIn(FIXED_PASSWORD, python)
        self.assertIn(owned(), python)
        self.assertTrue(python.rstrip().endswith("env.cr.commit()"))

    def test_replace_rows_refuses_foreign_rows_before_running(self):
        host = FakeHost([])
        with self.assertRaises(ValueError):
            self.shell(host).replace_rows("alice", tool_rows("alice"))
        self.assertEqual(host.calls, [])

    def test_shell_failure_gives_its_last_line_without_the_secret(self):
        line = f'psycopg2.OperationalError: value "{TURN_SECRET}" rejected'
        host = FakeHost(
            [(1, f"@@ODOO_VERSION 18.0\n@@ODOO_LAST {b64(line)}\n")]
        )
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).set_params({"erplibre_turn.secret": TURN_SECRET})
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertIn(
            "psycopg2.OperationalError", caught.exception.values["line"]
        )
        self.assertNotIn(TURN_SECRET, str(caught.exception.values))

    def test_missing_database_is_a_shell_failure(self):
        line = 'psycopg2.OperationalError: database "base_typo" does not exist'
        host = FakeHost([(1, f"@@ODOO_LAST {b64(line)}\n")])
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertEqual(caught.exception.values, {"line": line})

    def test_exit_zero_without_the_done_marker_is_a_failure(self):
        host = FakeHost([(0, "@@ODOO_VERSION 18.0\n")])
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).install_module()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")

    def test_a_refused_sudo_is_a_failure_with_its_message(self):
        host = FakeHost(
            [(1, "Sorry, try again.\nsudo: 3 incorrect attempts\n")]
        )
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertEqual(
            caught.exception.values, {"line": "sudo: 3 incorrect attempts"}
        )

    def test_ssh_failure_is_unreachable(self):
        host = FakeHost([(255, "ssh: connect to host: Connection refused\n")])
        host.target = "odoo.exemple.test"
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_unreachable")
        self.assertEqual(caught.exception.values["url"], "odoo.exemple.test")

    def test_install_module(self):
        host = FakeHost(
            [
                (
                    0,
                    "@@ODOO_VERSION 18.0\n@@ODOO_MODULE installed\n"
                    "@@ODOO_DONE install_module\n",
                )
            ]
        )
        self.shell(host).install_module()
        self.assertIn("button_immediate_install", python_of(host.calls[0][0]))
        host = FakeHost(
            [
                (
                    0,
                    "@@ODOO_VERSION 18.0\n@@ODOO_MODULE absent\n"
                    "@@ODOO_DONE install_module\n",
                )
            ]
        )
        with self.assertRaises(ol.OdooError) as caught:
            self.shell(host).install_module()
        self.assertEqual(
            caught.exception.key, "call_infra_odoo_install_failed"
        )
        self.assertEqual(caught.exception.values, {"state": "absent"})

    def test_directory_and_database_are_checked(self):
        for directory in ("relative/dir", "", "/opt/erp\nlibre"):
            with self.subTest(directory), self.assertRaises(ol.OdooError) as c:
                ol.OdooShell(FakeHost([]), directory, DATABASE)
            self.assertEqual(c.exception.key, "call_infra_odoo_dir")
        with self.assertRaises(ol.OdooError) as caught:
            ol.OdooShell(FakeHost([]), "/opt/erplibre", "base;rm -rf")
        self.assertEqual(caught.exception.key, "call_infra_odoo_database")

    def test_the_directory_is_quoted(self):
        host = FakeHost([facts_output()])
        ol.OdooShell(host, "/opt/erp libre's", DATABASE).facts()
        self.assertIn(shlex.quote("/opt/erp libre's"), host.calls[0][0])


class ShHost:
    """Runner qui joue vraiment le script avec `sh`, sous l'utilisateur
    courant, sans sudo ni terminal."""

    def __init__(self):
        self.calls = []

    def run(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        done = subprocess.run(
            ["sh", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        return done.returncode, done.stdout.decode("utf-8", "replace")


FAKE_ODOO_BIN = """#!/bin/sh
# Faux odoo_bin.sh : garde ses arguments et l'entrée standard, imprime du
# bruit de journal, puis la sortie préparée, et rend le code demandé.
printf '%s\\n' "$*" > "$(dirname "$0")/args"
cat > "$(dirname "$0")/stdin"
echo "2026-01-01 00:00:00,000 1 INFO base_inventee odoo: bruit de journal" >&2
cat "$(dirname "$0")/answer"
exit "$(cat "$(dirname "$0")/code")"
"""


class TestShellScriptForReal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="odoo-link-")
        self.addCleanup(subprocess.run, ["rm", "-rf", self.dir])
        path = os.path.join(self.dir, "odoo_bin.sh")
        with open(path, "w") as handle:
            handle.write(FAKE_ODOO_BIN)
        os.chmod(path, stat.S_IRWXU)

    def prepare(self, answer, code=0):
        with open(os.path.join(self.dir, "answer"), "w") as handle:
            handle.write(answer)
        with open(os.path.join(self.dir, "code"), "w") as handle:
            handle.write(str(code))

    def read(self, name):
        with open(os.path.join(self.dir, name)) as handle:
            return handle.read()

    def test_python_on_stdin_markers_out_noise_hidden(self):
        self.prepare("@@ODOO_VERSION 18.0\n@@ODOO_DONE set_params\n")
        host = ShHost()
        ol.OdooShell(host, self.dir, DATABASE).set_params(
            {"erplibre_turn.secret": TURN_SECRET}
        )
        self.assertEqual(self.read("args"), f"shell -d {DATABASE} --no-http\n")
        self.assertEqual(self.read("stdin"), python_of(host.calls[0][0]))
        self.assertIn(TURN_SECRET, self.read("stdin"))

    def test_output_holds_only_marker_lines(self):
        self.prepare("@@ODOO_VERSION 18.0\nautre ligne\n@@ODOO_DONE facts\n")
        host = ShHost()
        code, out = host.run(
            ol.OdooShell(host, self.dir, DATABASE).script("pass\n"), None
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "@@ODOO_VERSION 18.0\n@@ODOO_DONE facts\n")

    def test_failure_returns_the_code_and_the_last_line(self):
        self.prepare(
            "Traceback (most recent call last):\n"
            "KeyError: 'erplibre_turn.inconnu'\n\n",
            code=1,
        )
        with self.assertRaises(ol.OdooError) as caught:
            ol.OdooShell(ShHost(), self.dir, DATABASE).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertEqual(
            caught.exception.values,
            {"line": "KeyError: 'erplibre_turn.inconnu'"},
        )

    def test_a_directory_without_odoo_bin_sh(self):
        os.unlink(os.path.join(self.dir, "odoo_bin.sh"))
        with self.assertRaises(ol.OdooError) as caught:
            ol.OdooShell(ShHost(), self.dir, DATABASE).facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertIn("odoo_bin.sh", caught.exception.values["line"])


# Faux `stat` : la ligne de `stat.table` dont le premier champ est le
# chemin RÉSOLU du fichier demandé donne « uid nom ».
STUB_STAT = """#!/bin/sh
here=$(dirname "$0")
fmt=$3
real=$(readlink -f -- "$4")
line=$(awk -F '\\t' -v f="$real" '$1 == f {print $2}' "$here/stat.table")
[ -n "$line" ] || exit 1
set -- $line
case "$fmt" in
'%u %U') echo "$1 $2" ;;
'%u') echo "$1" ;;
*) exit 1 ;;
esac
"""

STUB_ID = """#!/bin/sh
[ "$1" = -u ] || exit 1
cat "$(dirname "$0")/id.uid"
"""

# Faux `runuser` : garde ses arguments, puis lance ce qui suit « -- ».
STUB_RUNUSER = """#!/bin/sh
printf '%s\\n' "$*" > "$(dirname "$0")/runuser.argv"
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
exec "$@"
"""

# Faux `readlink` : échoue quand `readlink.fail` existe, sinon passe la
# main au vrai, `{real}`.
STUB_READLINK = """#!/bin/sh
[ -e "$(dirname "$0")/readlink.fail" ] && exit 1
exec {real} "$@"
"""


class StubHost(ShHost):
    """ShHost dont le PATH commence par les faux `id`, `stat`, `runuser`
    et `readlink` de `stubs`."""

    def __init__(self, stubs):
        super().__init__()
        self.env = dict(
            os.environ, PATH=stubs + os.pathsep + os.environ["PATH"]
        )

    def run(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        done = subprocess.run(
            ["sh", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=self.env,
        )
        return done.returncode, done.stdout.decode("utf-8", "replace")


class TestShellScriptAccount(unittest.TestCase):
    """Le compte sous lequel le script root lance `odoo_bin.sh`, avec des
    propriétaires que seuls de faux `stat` et `id` peuvent simuler."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="odoo-link-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", self.tmp])
        self.checkout = os.path.join(self.tmp, "checkout")
        self.stubs = os.path.join(self.tmp, "stubs")
        os.mkdir(self.checkout)
        os.mkdir(self.stubs)
        self.bin = os.path.join(self.checkout, "odoo_bin.sh")
        self.write(self.bin, FAKE_ODOO_BIN, stat.S_IRWXU)
        self.write(
            os.path.join(self.checkout, "answer"),
            "@@ODOO_VERSION 18.0\n@@ODOO_DONE facts\n",
        )
        self.write(os.path.join(self.checkout, "code"), "0")
        readlink = STUB_READLINK.replace(
            "{real}", shlex.quote(shutil.which("readlink"))
        )
        for name, text in (
            ("stat", STUB_STAT),
            ("id", STUB_ID),
            ("runuser", STUB_RUNUSER),
            ("readlink", readlink),
        ):
            self.write(os.path.join(self.stubs, name), text, stat.S_IRWXU)
        self.running_as("0")

    def write(self, path, text, mode=None):
        with open(path, "w") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(path, mode)

    def running_as(self, uid):
        self.write(os.path.join(self.stubs, "id.uid"), uid + "\n")

    def owners(self, directory, odoo_bin):
        """`directory` : « uid nom » du dossier ; `odoo_bin` : « uid » de
        son odoo_bin.sh."""
        self.write(
            os.path.join(self.stubs, "stat.table"),
            f"{self.checkout}\t{directory}\n{self.bin}\t{odoo_bin}\n",
        )

    def facts(self, directory=None):
        return ol.OdooShell(
            StubHost(self.stubs), directory or self.checkout, DATABASE
        ).facts()

    def exists(self, *parts):
        return os.path.exists(os.path.join(*parts))

    def assert_not_run(self):
        self.assertFalse(self.exists(self.checkout, "args"))
        self.assertFalse(self.exists(self.stubs, "runuser.argv"))

    def test_root_runs_the_owner_side_through_runuser(self):
        self.owners("1001 erplibre", "1001")
        self.facts()
        with open(os.path.join(self.stubs, "runuser.argv")) as handle:
            self.assertEqual(
                handle.read(),
                f"-u erplibre -- ./odoo_bin.sh shell -d {DATABASE} --no-http\n",
            )
        self.assertTrue(self.exists(self.checkout, "args"))

    def test_the_owner_itself_runs_it_directly(self):
        self.running_as("1001")
        self.owners("1001 erplibre", "1001")
        self.facts()
        self.assertFalse(self.exists(self.stubs, "runuser.argv"))
        self.assertTrue(self.exists(self.checkout, "args"))

    def test_a_symlink_is_resolved_before_the_owner_is_read(self):
        # Le lien appartiendrait à root ; c'est le dossier pointé qui
        # décide du compte.
        link = os.path.join(self.tmp, "lien")
        os.symlink(self.checkout, link)
        self.owners("1001 erplibre", "1001")
        with open(os.path.join(self.stubs, "stat.table"), "a") as handle:
            handle.write(f"{link}\t0 root\n")
        self.facts(directory=link)
        with open(os.path.join(self.stubs, "runuser.argv")) as handle:
            self.assertTrue(handle.read().startswith("-u erplibre -- "))

    def test_a_directory_that_does_not_resolve_is_refused(self):
        # Le chemin tel quel mènerait à un dossier valide : il ne sert
        # pas de repli quand `readlink -f` échoue.
        self.owners("1001 erplibre", "1001")
        self.write(os.path.join(self.stubs, "readlink.fail"), "")
        with self.assertRaises(ol.OdooError) as caught:
            self.facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_shell_failed")
        self.assertIn("cannot resolve", caught.exception.values["line"])
        self.assert_not_run()

    def test_owners_that_differ_are_refused(self):
        self.owners("1001 erplibre", "1002")
        with self.assertRaises(ol.OdooError) as caught:
            self.facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_dir_owner")
        self.assertEqual(caught.exception.values, {"directory": self.checkout})
        self.assert_not_run()

    def test_a_root_owned_checkout_is_refused_even_when_closed(self):
        self.owners("0 root", "0")
        with self.assertRaises(ol.OdooError) as caught:
            self.facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_dir_root")
        self.assertEqual(caught.exception.values, {"directory": self.checkout})
        self.assert_not_run()

    def test_a_root_owned_checkout_is_refused_for_any_caller(self):
        self.running_as("1001")
        self.owners("0 root", "0")
        with self.assertRaises(ol.OdooError) as caught:
            self.facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_dir_root")
        self.assert_not_run()

    def test_a_root_odoo_bin_in_another_account_s_directory_is_refused(self):
        self.owners("1001 erplibre", "0")
        with self.assertRaises(ol.OdooError) as caught:
            self.facts()
        self.assertEqual(caught.exception.key, "call_infra_odoo_dir_owner")
        self.assert_not_run()


# --- Le corps Python contre un faux env ----------------------------------


class FakeRecords:
    def __init__(self, model, ids):
        self.model, self.ids = model, list(ids)

    def __bool__(self):
        return bool(self.ids)

    @property
    def state(self):
        return self.model.store[self.ids[0]]["state"]

    def unlink(self):
        for i in self.ids:
            del self.model.store[i]

    def button_immediate_install(self):
        for i in self.ids:
            self.model.store[i]["state"] = "installed"


class FakeModel:
    def __init__(self, store):
        self.store = store

    def sudo(self):
        return self

    def search(self, domain, limit=None):
        ids = [
            i
            for i, rec in self.store.items()
            if all(rec.get(f) == v for f, _, v in domain)
        ]
        return FakeRecords(self, ids[:limit] if limit else ids)

    def search_read(self, domain, fields):
        return [
            dict({"id": i}, **{f: self.store[i].get(f, False) for f in fields})
            for i in self.search(domain).ids
        ]

    def create(self, vals_list):
        for vals in vals_list:
            new_id = max(self.store, default=0) + 1
            self.store[new_id] = dict(vals)


class FakeParams:
    def __init__(self, values):
        self.values = values

    def sudo(self):
        return self

    def get_param(self, key, default=False):
        return self.values.get(key, default)

    def set_param(self, key, value):
        if value is None or value is False:
            self.values.pop(key, None)
        else:
            self.values[key] = value


class FakeCursor:
    def __init__(self, modules):
        self.modules = modules
        self.commits = 0
        self.row = None

    def commit(self):
        self.commits += 1

    def execute(self, query, params):
        found = [
            m["state"] for m in self.modules.values() if m["name"] == params[0]
        ]
        self.row = (found[0],) if found else None

    def fetchone(self):
        return self.row


class FakeEnv:
    def __init__(self):
        self.modules = {1: {"name": "erplibre_turn", "state": "uninstalled"}}
        self.params = {"erplibre_turn.ttl_hours": "24"}
        self.rows = {
            1: {
                "server_type": "turn",
                "uri": "turn.exemple.test:3478",
                "username": "alice",
                "credential": "Cle-de-alice-inventee",
            },
            2: {
                "server_type": "stun",
                "uri": "turn.exemple.test:3478",
                "username": False,
                "credential": False,
            },
            3: {
                "server_type": "stun",
                "uri": "turn.exemple.test:3478",
                "username": owned(),
                "credential": False,
            },
        }
        self.cr = FakeCursor(self.modules)
        self.user = types.SimpleNamespace(login="__system__")
        self.models = {
            "ir.module.module": FakeModel(self.modules),
            "ir.config_parameter": FakeParams(self.params),
            "mail.ice.server": FakeModel(self.rows),
        }

    def __getitem__(self, name):
        return self.models[name]


class TestShellPythonBody(unittest.TestCase):
    """Le corps Python, joué tel quel contre un faux `env` et un faux
    `odoo.release` : il se compile, imprime les marqueurs attendus et fait
    les écritures demandées."""

    def run_python(self, method, *args, version=(18, 0, 0, "final", 0, "")):
        host = FakeHost([(0, "@@ODOO_VERSION 18.0\n")])
        shell = ol.OdooShell(host, "/opt/erplibre", DATABASE)
        with contextlib.suppress(ol.OdooError):
            getattr(shell, method)(*args)
        python = python_of(host.calls[0][0])
        release = types.ModuleType("odoo.release")
        release.version = f"{version[0]}.{version[1]}"
        release.version_info = version
        odoo = types.ModuleType("odoo")
        odoo.release = release
        env = FakeEnv()
        out = io.StringIO()
        with mock.patch.dict(
            sys.modules, {"odoo": odoo, "odoo.release": release}
        ), contextlib.redirect_stdout(out):
            try:
                exec(python, {"env": env, "__name__": "__main__"})
            except SystemExit as stop:
                env.exit = stop.code
        return env, out.getvalue()

    def test_facts(self):
        env, out = self.run_python("facts")
        host = FakeHost([(0, out)])
        facts = ol.OdooShell(host, "/opt/erplibre", DATABASE).facts()
        self.assertEqual(facts.module_state, "uninstalled")
        self.assertEqual(facts.params, {"erplibre_turn.ttl_hours": "24"})
        self.assertEqual([r["id"] for r in facts.rows], [1, 2, 3])
        self.assertEqual(facts.rows[1]["username"], "")
        self.assertNotIn("Cle-de-alice-inventee", out)
        self.assertEqual(env.cr.commits, 1)

    def test_facts_reports_the_secret_as_a_digest(self):
        host = FakeHost([(0, "@@ODOO_VERSION 18.0\n")])
        with contextlib.suppress(ol.OdooError):
            ol.OdooShell(host, "/opt/erplibre", DATABASE).facts()
        python = python_of(host.calls[0][0])
        release = types.ModuleType("odoo.release")
        release.version, release.version_info = "18.0", (18, 0)
        odoo = types.ModuleType("odoo")
        odoo.release = release
        env = FakeEnv()
        env.params["erplibre_turn.secret"] = TURN_SECRET
        out = io.StringIO()
        with mock.patch.dict(
            sys.modules, {"odoo": odoo, "odoo.release": release}
        ), contextlib.redirect_stdout(out):
            exec(python, {"env": env, "__name__": "__main__"})
        self.assertNotIn(TURN_SECRET, out.getvalue())
        facts = ol.OdooShell(
            FakeHost([(0, out.getvalue())]), "/opt/erplibre", DATABASE
        ).facts()
        self.assertEqual(
            facts.params["erplibre_turn.secret"], ol.secret_digest(TURN_SECRET)
        )

    def test_set_params(self):
        host = FakeHost([(0, "@@ODOO_VERSION 18.0\n")])
        shell = ol.OdooShell(host, "/opt/erplibre", DATABASE)
        with contextlib.suppress(ol.OdooError):
            shell.set_params(
                {
                    "erplibre_turn.secret": TURN_SECRET,
                    "erplibre_turn.urls": URLS,
                    "erplibre_turn.ttl_hours": None,
                }
            )
        python = python_of(host.calls[0][0])
        release = types.ModuleType("odoo.release")
        release.version, release.version_info = "18.0", (18, 0)
        odoo = types.ModuleType("odoo")
        odoo.release = release
        env = FakeEnv()
        out = io.StringIO()
        with mock.patch.dict(
            sys.modules, {"odoo": odoo, "odoo.release": release}
        ), contextlib.redirect_stdout(out):
            exec(python, {"env": env, "__name__": "__main__"})
        self.assertEqual(
            env.params,
            {"erplibre_turn.secret": TURN_SECRET, "erplibre_turn.urls": URLS},
        )
        self.assertIn("@@ODOO_DONE set_params", out.getvalue())
        self.assertNotIn(TURN_SECRET, out.getvalue())
        self.assertEqual(env.cr.commits, 1)

    def test_replace_rows(self):
        env, out = self.run_python("replace_rows", owned(), tool_rows())
        self.assertIn("@@ODOO_DONE replace_rows", out)
        self.assertIn(1, env.rows)
        self.assertIn(2, env.rows)
        self.assertNotIn(3, env.rows)
        mine = [r for r in env.rows.values() if r["username"] == owned()]
        self.assertEqual(len(mine), 3)
        self.assertNotIn(FIXED_PASSWORD, out)
        self.assertEqual(env.cr.commits, 1)

    def test_install_module(self):
        env, out = self.run_python("install_module")
        self.assertEqual(env.modules[1]["state"], "installed")
        self.assertIn("@@ODOO_MODULE installed", out)
        self.assertIn("@@ODOO_DONE install_module", out)

    def test_odoo_17_stops_before_any_write(self):
        env, out = self.run_python(
            "set_params",
            {"erplibre_turn.secret": TURN_SECRET},
            version=(17, 0, 0, "final", 0, ""),
        )
        self.assertEqual(env.exit, 4)
        self.assertNotIn("erplibre_turn.secret", env.params)
        self.assertEqual(env.cr.commits, 0)
        self.assertEqual(out, "@@ODOO_VERSION 17.0\n")


# --- Entrée dans un appel : la liste ICE qu'Odoo remet ----------------------

CALLER = "appelant@exemple.test"
CALLER_PASSWORD = "Appelant-invente-31"
CALLER_PARTNER = 31
CHAT_ID = 55
GUEST_CHANNEL = 60
INVITATION_TOKEN = "3c1f0e2a-invente-4b7d-9a65-0d8e2f1b7c44"
ICE_CREDENTIAL = "Q2xlLWludmVudGVlLXBvdXItbGUtdGVzdA=="
ICE_SERVERS = [
    {"urls": "stun:turn.exemple.test:3478"},
    {
        "urls": "turn:turn.exemple.test:3478?transport=udp",
        "username": "1893542400:odoo-u9",
        "credential": ICE_CREDENTIAL,
    },
]


class _DiscussHandler(http.server.BaseHTTPRequestHandler):
    """Requêtes HTTP vers le `FakeDiscuss` du serveur (`server.fake`)."""

    def log_message(self, *args):
        pass

    def cookies(self):
        jar = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, sep, value = part.strip().partition("=")
            if sep:
                jar[name] = value
        return jar

    def send(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        fake = self.server.fake
        path, _, query = self.path.partition("?")
        jar = self.cookies()
        fake.calls.append((path, query, jar))
        self.send(*fake.page(path, query, jar))

    def do_POST(self):
        fake = self.server.fake
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        params = dict(payload.get("params") or {})
        jar = self.cookies()
        logged = dict(params)
        logged.pop("password", None)
        fake.calls.append((self.path, logged, jar))
        headers = []
        try:
            if self.path in fake.fail:
                raise RpcFault("odoo.exceptions.UserError", "refus")
            answer = {"result": fake.route(self.path, params, jar, headers)}
        except LookupError:
            self.send(404)
            return
        except RpcFault as fault:
            answer = {
                "error": {
                    "code": 200,
                    "message": "Odoo Server Error",
                    "data": {"name": fault.name, "message": fault.message},
                }
            }
        answer.update(jsonrpc="2.0", id=payload.get("id"))
        body = json.dumps(answer).encode()
        self.send(200, body, [("Content-Type", "application/json")] + headers)


class FakeDiscuss:
    """Les routes de session et d'appel d'Odoo 18 derrière un vrai serveur
    HTTP sur 127.0.0.1 : `/web/session/authenticate`, `channel_get` par
    `/web/dataset/call_kw`, `/mail/rtc/channel/join_call` et `leave_call`,
    et pour un invité `/web/login?db=` puis le lien `/chat/<id>/<jeton>`.
    Les cookies de session (`session_id`) et d'invité (`dgid`) se posent et
    se lisent comme dans Odoo. `calls` note (chemin, paramètres sans mot de
    passe, cookies reçus)."""

    def __init__(self, version="18.0"):
        self.version = version
        self.sessions = {}
        self.calls = []
        self.ice = list(ICE_SERVERS)
        self.fail = set()
        self.rtc = True
        self.httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), _DiscussHandler
        )
        self.httpd.fake = self
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.02},
            daemon=True,
        )

    def page(self, path, query, jar):
        """(statut, corps, en-têtes) d'un GET : `/web/login?db=` pose la
        base dans une nouvelle session puis redirige vers lui-même ; le
        lien d'invitation fait de la session un invité (`dgid`)."""
        if path == "/web/login":
            sid = jar.get("session_id")
            if sid in self.sessions:
                return 200, b"<html>login</html>", ()
            sid = f"sid{len(self.sessions) + 1}"
            self.sessions[sid] = {"db": query.split("db=")[1]}
            return (
                302,
                b"",
                (
                    ("Location", f"{path}?{query}"),
                    ("Set-Cookie", f"session_id={sid}; Path=/"),
                ),
            )
        if path == f"/chat/{GUEST_CHANNEL}/{INVITATION_TOKEN}":
            session = self.sessions.get(jar.get("session_id"))
            if session and session.get("db") == DATABASE:
                cookie = ("Set-Cookie", "dgid=4|jeton-invite; Path=/")
                return 200, b"<html>chat</html>", (cookie,)
        return 404, b"", ()

    def route(self, path, params, jar, headers):
        session = self.sessions.get(jar.get("session_id"))
        if path == "/jsonrpc":
            major = int(self.version.split(".")[0])
            return {"server_version": self.version, "server_serie": major}
        if path == "/web/session/authenticate":
            if params.get("db") != DATABASE:
                raise RpcFault(
                    "odoo.exceptions.AccessError", "Database not found."
                )
            if (params.get("login"), params.get("password")) != (
                CALLER,
                CALLER_PASSWORD,
            ):
                raise RpcFault("odoo.exceptions.AccessDenied", "Access Denied")
            sid = f"sid{len(self.sessions) + 1}"
            self.sessions[sid] = {"db": DATABASE, "uid": 9}
            headers.append(("Set-Cookie", f"session_id={sid}; Path=/"))
            return {"uid": 9, "partner_id": CALLER_PARTNER, "db": DATABASE}
        if path == "/web/dataset/call_kw/discuss.channel/channel_get":
            if not session or not session.get("uid"):
                raise RpcFault(
                    "odoo.http.SessionExpiredException", "Session expired"
                )
            return {
                "discuss.channel": [{"id": CHAT_ID, "channel_type": "chat"}],
                "res.partner": [{"id": CALLER_PARTNER}],
            }
        if path in (
            "/mail/rtc/channel/join_call",
            "/mail/rtc/channel/leave_call",
        ):
            channel = params.get("channel_id")
            allowed = (session or {}).get("uid") and channel == CHAT_ID
            guest = (
                jar.get("dgid") == "4|jeton-invite"
                and channel == GUEST_CHANNEL
            )
            if not (allowed or guest):
                raise LookupError(path)
            if path.endswith("leave_call"):
                return None
            store = {"discuss.channel": [{"id": channel}]}
            if self.rtc:
                store["Rtc"] = {
                    "iceServers": self.ice,
                    "selfSession": {"id": 3},
                }
            return store
        raise LookupError(path)

    def paths(self):
        return [call[0] for call in self.calls]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestJoinCall(unittest.TestCase):
    def setUp(self):
        self.odoo = FakeDiscuss()
        self.odoo.__enter__()
        self.addCleanup(self.odoo.__exit__)

    def api(self):
        return ol.WebApi(self.odoo.url, DATABASE, None, None, timeout=5)

    def test_a_user_joins_their_own_chat_and_leaves(self):
        ice = self.api().join_call_ice(CALLER, CALLER_PASSWORD)
        self.assertEqual(ice, ICE_SERVERS)
        self.assertEqual(
            self.odoo.paths(),
            [
                "/jsonrpc",
                "/web/session/authenticate",
                "/web/dataset/call_kw/discuss.channel/channel_get",
                "/mail/rtc/channel/join_call",
                "/mail/rtc/channel/leave_call",
            ],
        )
        _, auth, _ = self.odoo.calls[1]
        self.assertEqual((auth["db"], auth["login"]), (DATABASE, CALLER))
        _, channel_get, jar = self.odoo.calls[2]
        self.assertEqual(
            (channel_get["model"], channel_get["method"], channel_get["args"]),
            ("discuss.channel", "channel_get", []),
        )
        self.assertEqual(
            channel_get["kwargs"], {"partners_to": [CALLER_PARTNER]}
        )
        self.assertIn("session_id", jar)
        for path, params, _ in self.odoo.calls[3:]:
            self.assertEqual(params, {"channel_id": CHAT_ID}, path)

    def test_no_ice_servers_is_an_empty_list(self):
        self.odoo.ice = False
        self.assertEqual(self.api().join_call_ice(CALLER, CALLER_PASSWORD), [])
        self.odoo.rtc = False
        self.assertEqual(self.api().join_call_ice(CALLER, CALLER_PASSWORD), [])

    def test_a_wrong_password_is_refused_before_any_channel(self):
        with self.assertRaises(ol.OdooError) as caught:
            self.api().join_call_ice(CALLER, "Faux-mot-de-passe-invente")
        self.assertEqual(caught.exception.key, "call_infra_odoo_user_login")
        self.assertEqual(caught.exception.values, {"login": CALLER})
        self.assertEqual(
            self.odoo.paths(), ["/jsonrpc", "/web/session/authenticate"]
        )

    def test_an_odoo_17_is_refused_before_login(self):
        self.odoo.version = "17.0"
        with self.assertRaises(ol.OdooError) as caught:
            self.api().join_call_ice(CALLER, CALLER_PASSWORD)
        self.assertEqual(caught.exception.key, "call_infra_odoo_version")
        self.assertEqual(self.odoo.paths(), ["/jsonrpc"])

    def test_a_failed_join_still_leaves(self):
        self.odoo.fail.add("/mail/rtc/channel/join_call")
        with self.assertRaises(ol.OdooError) as caught:
            self.api().join_call_ice(CALLER, CALLER_PASSWORD)
        self.assertEqual(caught.exception.key, "call_infra_odoo_rpc_error")
        self.assertEqual(self.odoo.paths()[-1], "/mail/rtc/channel/leave_call")

    def test_a_failed_leave_keeps_the_ice_list(self):
        self.odoo.fail.add("/mail/rtc/channel/leave_call")
        ice = self.api().join_call_ice(CALLER, CALLER_PASSWORD)
        self.assertEqual(ice, ICE_SERVERS)

    def test_neither_password_nor_credential_reaches_the_log(self):
        with self.assertLogs("script.todo.odoo_link", logging.DEBUG) as logs:
            self.api().join_call_ice(CALLER, CALLER_PASSWORD)
        text = "\n".join(logs.output)
        self.assertNotIn(CALLER_PASSWORD, text)
        self.assertNotIn(ICE_CREDENTIAL, text)

    def test_a_guest_joins_by_the_invitation_link(self):
        link = f"{self.odoo.url}/chat/{GUEST_CHANNEL}/{INVITATION_TOKEN}"
        ice = self.api().join_call_ice_guest(link)
        self.assertEqual(ice, ICE_SERVERS)
        self.assertEqual(
            self.odoo.paths(),
            [
                "/jsonrpc",
                "/web/login",
                "/web/login",
                f"/chat/{GUEST_CHANNEL}/{INVITATION_TOKEN}",
                "/mail/rtc/channel/join_call",
                "/mail/rtc/channel/leave_call",
            ],
        )
        self.assertEqual(self.odoo.calls[1][1], f"db={DATABASE}")
        _, params, jar = self.odoo.calls[4]
        self.assertEqual(params, {"channel_id": GUEST_CHANNEL})
        self.assertEqual(jar.get("dgid"), "4|jeton-invite")

    def test_the_invitation_token_stays_out_of_the_log(self):
        link = f"{self.odoo.url}/chat/{GUEST_CHANNEL}/{INVITATION_TOKEN}"
        with self.assertLogs("script.todo.odoo_link", logging.DEBUG) as logs:
            self.api().join_call_ice_guest(link)
        text = "\n".join(logs.output)
        self.assertIn(f"/chat/{GUEST_CHANNEL}/", text)
        self.assertNotIn(INVITATION_TOKEN, text)

    def test_an_invitation_odoo_does_not_know_is_refused(self):
        link = f"{self.odoo.url}/chat/{GUEST_CHANNEL}/jeton-inconnu"
        with self.assertRaises(ol.OdooError) as caught:
            self.api().join_call_ice_guest(link)
        self.assertEqual(caught.exception.key, "call_infra_odoo_invitation")
        self.assertEqual(caught.exception.values, {})
        self.assertNotIn("/mail/rtc/channel/join_call", self.odoo.paths())

    def test_an_invitation_of_another_odoo_or_shape_is_refused_unsent(self):
        for link in (
            f"https://autre.exemple.test/chat/{GUEST_CHANNEL}/{INVITATION_TOKEN}",
            f"{self.odoo.url}/odoo/discuss",
            f"{self.odoo.url}/chat/abc/{INVITATION_TOKEN}",
            "pas un lien",
        ):
            with self.assertRaises(ol.OdooError) as caught:
                self.api().join_call_ice_guest(link)
            self.assertEqual(
                caught.exception.key, "call_infra_odoo_invitation"
            )
        self.assertEqual(self.odoo.calls, [])

    def test_both_refusals_format_in_french_and_english(self):
        from script.todo.todo_i18n import TRANSLATIONS

        errors = []
        for action in (
            lambda: self.api().join_call_ice(CALLER, "Faux-invente"),
            lambda: self.api().join_call_ice_guest("pas un lien"),
        ):
            with self.assertRaises(ol.OdooError) as caught:
                action()
            errors.append(caught.exception)
        for error in errors:
            for lang in ("fr", "en"):
                text = TRANSLATIONS[error.key][lang].format(**error.values)
                self.assertNotIn("{", text, error.key)


class TestMessages(WebCase):
    """Chaque refus se formate, en français et en anglais, avec les
    valeurs que le code lui passe."""

    def refusals(self):
        def caught(action):
            try:
                action()
            except ol.OdooError as error:
                return error
            self.fail(action)

        shell = ol.OdooShell(FakeHost([]), "/opt/erplibre", DATABASE)
        yield caught(lambda: ol.normalize_url("ftp://x.exemple.test"))
        yield caught(lambda: ol.odoo_key(OWNED_ODOO, "-"))
        yield caught(lambda: ol.OdooShell(FakeHost([]), "rel", DATABASE))
        yield caught(lambda: self.api(password="Faux-invente").facts())
        self.odoo.users[LOGIN]["admin"] = False
        yield caught(lambda: self.api().facts())
        self.odoo.users[LOGIN]["admin"] = True
        self.odoo.fail["ir.config_parameter", "set_param"] = "refus inventé"
        yield caught(lambda: self.api().set_params({ol.PARAM_URLS: URLS}))
        del self.odoo.modules["erplibre_turn"]
        yield caught(self.api().install_module)
        self.odoo.version = "17.0"
        yield caught(lambda: self.api().facts())
        self.odoo.status = 500
        yield caught(lambda: self.api().facts())
        shell.host = FakeHost([(1, "trace\nKeyError: 'x'\n")])
        yield caught(shell.facts)

    def test_every_refusal_formats(self):
        from script.todo.todo_i18n import TRANSLATIONS

        keys = set()
        for error in self.refusals():
            keys.add(error.key)
            for lang in ("fr", "en"):
                text = TRANSLATIONS[error.key][lang].format(**error.values)
                self.assertNotIn("{", text, error.key)
        self.assertEqual(len(keys), 10, keys)


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        with open(os.path.join(REPO, "script", "todo", "odoo_link.py")) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(
                        alias.name.split(".")[0], sys.stdlib_module_names
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertTrue(node.module, "relative import")
                self.assertIn(
                    node.module.split(".")[0], sys.stdlib_module_names
                )


if __name__ == "__main__":
    unittest.main()
