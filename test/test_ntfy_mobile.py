#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Fonctions pures de `script/todo/ntfy_mobile.py` : contrôles du serveur
ntfy, script d'accès du téléphone, édition de `server.yml`, lien et QR."""

import ast
import contextlib
import io
import os
import re
import sys
import unittest
from unittest import mock

from script.todo import ntfy_mobile as nm

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Exemple inventé, partagé avec le côté application.
EXAMPLE_LINK = (
    "erplibre-ntfy:setup?v=1"
    "&url=http%3A%2F%2Fntfy.exemple.test%3A8080"
    "&token=tk_exempleexempleexempleexemple"
    "&prefix=upab12cd34&cache=43200"
    "&odoo=http%3A%2F%2Fodoo-ntfy.exemple.test%3A8080"
)

YML = (
    '# keepalive-interval: "45s"\n'
    'keepalive-interval: "45s"\n'
    'visitor-request-limit-exempt-hosts: "odoo.exemple.test"\n'
    'listen-http: ":8080"\n'
)


def installer_server_yml():
    """Le `server.yml` que `install_ntfy.sh` écrit, variables résolues."""
    path = os.path.join(REPO, "script", "install", "install_ntfy.sh")
    with open(path) as handle:
        text = handle.read()
    body = text.split("<<YAML\n", 1)[1].split("\nYAML\n", 1)[0]
    body = body.replace("${TLS_BLOCK}", "# no tls")
    body = body.replace("${DEFAULT_ACCESS}", "deny-all")
    return re.sub(r"\$\{[A-Z_]+\}", "/x", body)


class TestIdentifiers(unittest.TestCase):
    def test_prefix_shape_and_randomness(self):
        seen = {nm.random_prefix() for _ in range(20)}
        self.assertGreater(len(seen), 1)
        for prefix in seen:
            self.assertRegex(prefix, r"^up[a-z0-9]{8}$")

    def test_phone_user_sanitized(self):
        self.assertEqual(
            nm.phone_user("Téléphone de Bruno"), "erm_telephonedebruno"
        )
        with self.assertRaises(ValueError):
            nm.phone_user("!!")


class TestServerConfig(unittest.TestCase):
    def test_config_problems(self):
        self.assertEqual(
            nm.config_problems({}),
            ["ntfy_mobile_no_auth_file", "ntfy_mobile_not_deny_all"],
        )
        keys = {
            "auth-file": "/x",
            "auth-default-access": "read-write",
            "visitor-subscriber-rate-limiting": "true",
        }
        self.assertEqual(
            nm.config_problems(keys),
            [
                "ntfy_mobile_not_deny_all",
                "ntfy_mobile_subscriber_rate_limiting",
            ],
        )
        installer = nm.read_yml_keys(installer_server_yml())
        self.assertEqual(nm.config_problems(installer), [])

    def test_read_yml_keys(self):
        keys = nm.read_yml_keys(YML + "other: plain # note\n  nested: 1\n")
        self.assertEqual(keys["keepalive-interval"], "45s")
        self.assertEqual(keys["other"], "plain")
        self.assertNotIn("nested", keys)

    def test_cache_seconds_units(self):
        for text, expected in (
            ("12h", 43200),
            ("30m", 1800),
            ("3600s", 3600),
            ("2d", 172800),
        ):
            self.assertEqual(
                nm.cache_seconds({"cache-duration": text}), expected
            )
        self.assertEqual(nm.cache_seconds({}), 43200)

    def test_exempt_hosts_merge_keeps_other_lines_byte_identical(self):
        new = nm.with_exempt_hosts(YML, ["127.0.0.1"])
        self.assertIn(
            'visitor-request-limit-exempt-hosts: "odoo.exemple.test,127.0.0.1"',
            new,
        )
        old_lines = YML.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        self.assertEqual(len(old_lines), len(new_lines))
        changed = [
            i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b
        ]
        self.assertEqual(changed, [2])
        self.assertEqual(nm.with_exempt_hosts(new, ["odoo.exemple.test"]), new)
        appended = nm.with_exempt_hosts("a: 1", ["127.0.0.1"])
        self.assertEqual(
            appended, 'a: 1\nvisitor-request-limit-exempt-hosts: "127.0.0.1"\n'
        )

    def test_subscriber_rate_limiting_turned_off(self):
        src = "a: 1\nvisitor-subscriber-rate-limiting: true\nb: 2\n"
        self.assertEqual(
            nm.with_subscriber_rate_limiting_off(src),
            "a: 1\nvisitor-subscriber-rate-limiting: false\nb: 2\n",
        )
        off = "visitor-subscriber-rate-limiting: false\n"
        self.assertEqual(nm.with_subscriber_rate_limiting_off(off), off)
        self.assertEqual(
            nm.with_subscriber_rate_limiting_off("a: 1\n"),
            "a: 1\nvisitor-subscriber-rate-limiting: false\n",
        )

    def test_unified_diff(self):
        diff = nm.unified_diff("a\n", "b\n", "/etc/x.yml")
        self.assertIn("--- /etc/x.yml", diff)
        self.assertIn("+b", diff)


CONFIG_CALL = re.compile(
    r"\bntfy\s+(?:(?:user|token|access)\s+)?--config\s+\S+"
)


def ntfy_calls(script):
    return [
        line
        for line in script.splitlines()
        if re.search(r"(^|[\s;(\"])ntfy\s", line)
    ]


class TestAccessScript(unittest.TestCase):
    def script(self, **kw):
        args = dict(
            config="/etc/ntfy/server.yml",
            user="erm_alice",
            prefix="upab12cd34",
        )
        args.update(kw)
        return nm.access_script(**args)

    def test_access_script_every_ntfy_call_has_config(self):
        script = self.script()
        calls = ntfy_calls(script)
        self.assertEqual(len(calls), 4)
        for line in calls:
            self.assertRegex(line, CONFIG_CALL)
        # Le garde-fou échoue bien sur un appel sans --config.
        self.assertIsNone(CONFIG_CALL.search("ntfy user add --config X u"))
        self.assertIsNone(CONFIG_CALL.search("ntfy token add u"))
        self.assertIn("ntfy user --config", script)
        self.assertIn("ntfy token --config", script)
        self.assertTrue(script.startswith("set -e\n"))

    def test_access_script_never_sets_expiry_or_keepalive(self):
        script = self.script()
        self.assertNotIn("--expires", script)
        self.assertNotIn("keepalive", script)
        self.assertIn("write-only", script)
        self.assertIn("'upab12cd34*' read-only", script)
        self.assertIn("--ignore-exists", script)

    def test_access_script_quotes_values(self):
        script = self.script(label="x'; touch /tmp/pwned; '")
        for line in script.splitlines():
            if "--label" in line:
                import shlex

                words = shlex.split(line)
                self.assertIn("--label=x'; touch /tmp/pwned; '", words)
                self.assertEqual(words[-1], "erm_alice")

    def test_other_scripts_carry_config(self):
        for script in (
            nm.revoke_script("/c.yml", "erm_alice"),
            nm.list_script("/c.yml"),
        ):
            calls = ntfy_calls(script)
            self.assertTrue(calls)
            for line in calls:
                self.assertRegex(line, CONFIG_CALL)
        self.assertIn("del erm_alice", nm.revoke_script("/c.yml", "erm_alice"))

    def test_inspect_and_write_scripts(self):
        inspect = nm.inspect_script("/c.yml")
        for marker in ("@@VERSION", "@@OWNER", "@@YML", "@@HEALTH"):
            self.assertIn(marker, inspect)
        write = nm.write_yml_script("/c.yml", "a: 1\n", "20260101")
        self.assertIn("/c.yml.bak-20260101", write)
        self.assertIn("base64 -d", write)
        self.assertIn("systemctl restart ntfy", nm.restart_script())

    def test_phone_users(self):
        out = (
            "user erm_alice (role: user, tier: none)\n- read-only access to "
            "topic upab12cd34*\nuser bob (role: admin, tier: none)\n"
            "user erm_bruno (role: user, tier: none)\n"
        )
        self.assertEqual(nm.phone_users(out), ["erm_alice", "erm_bruno"])


class TestParsers(unittest.TestCase):
    def test_parse_token(self):
        line = (
            "token tk_abcdEFGH1234 created for user erm_alice, never expires\n"
        )
        self.assertEqual(nm.parse_token("x\n" + line), "tk_abcdEFGH1234")
        self.assertIsNone(nm.parse_token("Error: user does not exist"))

    def test_parse_markers(self):
        out = "noise\n@@VERSION ntfy 2.34.0\n@@OWNER ntfy\n@@HEALTH ?\n"
        self.assertEqual(
            nm.parse_markers(out),
            {"VERSION": "ntfy 2.34.0", "OWNER": "ntfy", "HEALTH": "?"},
        )


class TestLinkAndQr(unittest.TestCase):
    def test_link_round_trip(self):
        link = nm.build_link(
            "http://ntfy.exemple.test:8080",
            "tk_exempleexempleexempleexemple",
            "upab12cd34",
            43200,
            "http://odoo-ntfy.exemple.test:8080",
        )
        self.assertEqual(link, EXAMPLE_LINK)
        self.assertNotIn("&odoo", nm.build_link("http://h", "tk_a", "upx", 1))

    def test_render_qr_none_without_segno(self):
        with mock.patch.dict(sys.modules, {"segno": None}):
            self.assertIsNone(nm.render_qr(EXAMPLE_LINK))

    def test_render_qr_draws_with_segno(self):
        try:
            import segno  # noqa: F401
        except ImportError:
            self.skipTest("segno absent")
        drawing = nm.render_qr(EXAMPLE_LINK)
        self.assertIsInstance(drawing, str)
        self.assertGreater(len(drawing.splitlines()), 10)


class TestRunners(unittest.TestCase):
    def test_local_runner_tees_and_captures(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code, text = nm.LocalHost(sudo=()).run(
                "printf 'a'; printf '@@TOKEN x\\n'", None
            )
        self.assertEqual(code, 0)
        self.assertEqual(text, "a@@TOKEN x\n")
        self.assertEqual(out.getvalue(), "a@@TOKEN x\n")

    def test_local_runner_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code, _ = nm.LocalHost(sudo=()).run("exit 3", None)
        self.assertEqual(code, 3)

    def test_argv_shapes(self):
        host = nm.LocalHost()
        self.assertEqual(
            host.argv("true", "ntfy"),
            ["sudo", "-u", "ntfy", "sh", "-c", "true"],
        )
        self.assertEqual(host.argv("true", None), ["sudo", "sh", "-c", "true"])
        ssh = nm.SshHost("alice@ntfy.exemple.test").argv("echo 'a b'", "ntfy")
        self.assertEqual(ssh[:3], ["ssh", "-t", "alice@ntfy.exemple.test"])
        self.assertEqual(ssh[3], "sudo -u ntfy sh -c 'echo '\"'\"'a b'\"'\"''")


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        with open(os.path.join(REPO, "script", "todo", "ntfy_mobile.py")) as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                self.assertIn(name, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
