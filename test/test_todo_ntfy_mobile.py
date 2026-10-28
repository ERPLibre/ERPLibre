#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Menu « Préparer ntfy pour ERPLibre mobile » : prépare, liste, révoque.

Aucun ntfy, aucun réseau, aucun sudo : l'hôte est une doublure qui note les
scripts reçus et rend des sorties canned.
"""

import ast
import base64
import builtins
import contextlib
import io
import re
import shlex
import unittest
from pathlib import Path
from unittest import mock

from script.todo import ntfy_mobile as nm
from script.todo.todo_i18n import TRANSLATIONS, t

REPO = Path(__file__).resolve().parent.parent
TODO_PY = REPO / "script" / "todo" / "todo.py"
MENU_PY = REPO / "script" / "todo" / "ntfy_mobile_menu.py"

TOKEN = "tk_exempleexempleexempleexemple"
YML = (
    'auth-file: "/var/lib/ntfy/user.db"\n'
    'auth-default-access: "deny-all"\n'
    'listen-http: ":8080"\n'
    'base-url: "http://ntfy.exemple.test"\n'
)
YML_EXEMPT = YML + 'visitor-request-limit-exempt-hosts: "127.0.0.1"\n'
YML_NO_AUTH = 'listen-http: ":8080"\n'
YML_RATE = YML_EXEMPT + "visitor-subscriber-rate-limiting: true\n"
YML_LOCAL_URL = YML_EXEMPT.replace(
    "http://ntfy.exemple.test", "http://localhost"
)
ACCESS_LIST = (
    "user erm_alice (role: user, tier: none)\n"
    "- read-only access to topic upab12cd34*\n"
    "user erm_bruno (role: user, tier: none)\n"
    "user * (role: anonymous, tier: none)\n"
)


class FakeHost:
    """Note (script, sudo_user) et répond selon le contenu du script."""

    def __init__(
        self, yml=YML_EXEMPT, owner="ntfy", states=("active",), token_out=None
    ):
        self.yml = yml
        self.owner = owner
        self.states = list(states)
        self.token_out = (
            f"token {TOKEN} created for user erm_alice\n"
            if token_out is None
            else token_out
        )
        self.calls = []

    def kinds(self):
        return [self.kind(s) for s, _ in self.calls]

    @staticmethod
    def kind(script):
        if "@@YML" in script:
            return "inspect"
        if "base64 -d" in script:
            return "write"
        if "systemctl restart" in script:
            return "restart"
        if "is-active" in script:
            return "recheck"
        if "token --config" in script:
            return "access"
        if " del " in script:
            return "revoke"
        return "list"

    def run(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        kind = self.kind(script)
        if kind == "inspect":
            b64 = base64.b64encode(self.yml.encode()).decode()
            return 0, f"@@OWNER {self.owner}\n@@YML {b64}\n@@HEALTH ?\n"
        if kind == "restart":
            return 0, f"@@ACTIVE {self.states.pop(0)}\n"
        if kind == "recheck":
            return 0, f"{self.states.pop(0)}\n"
        if kind == "access":
            return 0, self.token_out
        if kind == "list":
            return 0, ACCESS_LIST
        return 0, ""

    def script_of(self, kind):
        return next(s for s, _ in self.calls if self.kind(s) == kind)

    def user_of(self, kind):
        return next(u for s, u in self.calls if self.kind(s) == kind)


class MenuCase(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO()
        patcher = mock.patch("time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def drive(self, method, host, answers, qr="QRART\n", lan="192.0.2.7"):
        """Lance `method` avec `answers` pour input(); rend la sortie."""
        answers = list(answers)
        pending = answers
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(
                mock.patch.object(
                    self.todo, "_ntfy_mobile_host", return_value=host
                )
            )
            stack.enter_context(
                mock.patch(
                    "builtins.input", side_effect=lambda *_: pending.pop(0)
                )
            )
            stack.enter_context(
                mock.patch.object(nm, "render_qr", return_value=qr)
            )
            stack.enter_context(
                mock.patch.object(
                    self.todo, "_ntfy_mobile_lan_address", return_value=lan
                )
            )
            getattr(self.todo, method)()
        self.assertEqual(pending, [], "answers unused")
        return out.getvalue()


class TestNumbering(unittest.TestCase):
    def test_menu_entry_after_install_and_numbering_shifted(self):
        src = TODO_PY.read_text(encoding="utf-8")
        start = src.index("def prompt_execute_deploy(self):")
        end = src.index("def prompt_execute_deploy_ssh(self):", start)
        body = src[start:end]
        dispatch = dict(
            re.findall(r'elif status == "(\d+)":\s*\n\s*self\.(\w+)\(\)', body)
        )
        self.assertEqual(
            dispatch,
            {
                "2": "_configure_sshfs",
                "3": "_deploy_port_forward",
                "4": "_deploy_socks_proxy",
                "5": "prompt_execute_deploy_ssh",
                "6": "prompt_execute_qemu",
                "7": "prompt_execute_proxmox",
                "8": "_deploy_ntfy_server",
                "9": "prompt_execute_ntfy_mobile",
                "10": "prompt_execute_qemu_cache",
                "11": "_deploy_asterisk_server",
                "12": "prompt_execute_vpn",
                "1": "_deploy_clone_erplibre",
            },
        )
        labels = re.findall(r't\(\s*"(Deploy - [^"]+|QEMU cache[^"]+)"', body)
        self.assertEqual(
            labels[:3],
            [
                "Deploy - Install NTFY notification server",
                "Deploy - Prepare ntfy for ERPLibre mobile",
                "QEMU cache - Download mirror for local VMs",
            ],
        )

    def test_submenu_dispatches_to_the_three_actions(self):
        from script.todo.todo import TODO

        todo = TODO()
        with (
            mock.patch.object(TODO, "_ntfy_mobile_prepare") as prep,
            mock.patch.object(TODO, "_ntfy_mobile_list") as lst,
            mock.patch.object(TODO, "_ntfy_mobile_revoke") as rev,
            mock.patch("click.prompt", side_effect=["1", "2", "3", "0"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_execute_ntfy_mobile()
        prep.assert_called_once_with()
        lst.assert_called_once_with()
        rev.assert_called_once_with()


class TestPrepare(MenuCase):
    # Réponses : config, adresses exemptées, [diff, redémarrage,] nom du
    # téléphone, URL du téléphone, URL côté Odoo.
    def test_prepare_stops_on_missing_auth_file(self):
        host = FakeHost(yml=YML_NO_AUTH)
        out = self.drive("_ntfy_mobile_prepare", host, [""])
        self.assertIn(t("ntfy_mobile_no_auth_file"), out)
        self.assertEqual(host.kinds(), ["inspect"])

    def test_prepare_shows_diff_and_writes_only_after_yes(self):
        host = FakeHost(yml=YML)
        out = self.drive(
            "_ntfy_mobile_prepare",
            host,
            ["", "", "y", "y", "Alice", "", ""],
        )
        self.assertIn("+visitor-request-limit-exempt-hosts", out)
        kinds = host.kinds()
        self.assertLess(kinds.index("inspect"), kinds.index("write"))
        self.assertLess(kinds.index("write"), kinds.index("restart"))
        self.assertLess(kinds.index("restart"), kinds.index("access"))
        self.assertIsNone(host.user_of("write"))
        self.assertIn(
            "127.0.0.1",
            base64.b64decode(
                re.search(
                    r"printf %s '?([A-Za-z0-9+/=]+)'? \|",
                    host.script_of("write"),
                ).group(1)
            ).decode(),
        )

    def test_prepare_no_to_diff_writes_nothing_and_warns(self):
        host = FakeHost(
            yml=YML_RATE.replace(
                'visitor-request-limit-exempt-hosts: "127.0.0.1"\n', ""
            )
        )
        out = self.drive(
            "_ntfy_mobile_prepare", host, ["", "", "n", "Alice", "", ""]
        )
        self.assertNotIn("write", host.kinds())
        self.assertNotIn("restart", host.kinds())
        self.assertIn("visitor-subscriber-rate-limiting", out)
        self.assertIn("visitor-request-limit-exempt-hosts", out)
        self.assertIn("access", host.kinds())

    def test_rate_limiting_fixed_in_the_same_diff(self):
        host = FakeHost(yml=YML_RATE)
        out = self.drive(
            "_ntfy_mobile_prepare",
            host,
            ["", "", "y", "n", "Alice", "", ""],
        )
        self.assertIn("+visitor-subscriber-rate-limiting: false", out)

    def test_restart_asked_separately(self):
        host = FakeHost(yml=YML)
        self.drive(
            "_ntfy_mobile_prepare",
            host,
            ["", "", "y", "n", "Alice", "", ""],
        )
        self.assertIn("write", host.kinds())
        self.assertNotIn("restart", host.kinds())

    def test_restart_activating_rechecks_then_succeeds(self):
        host = FakeHost(yml=YML, states=("activating", "activating", "active"))
        self.drive(
            "_ntfy_mobile_prepare",
            host,
            ["", "", "y", "y", "Alice", "", ""],
        )
        self.assertEqual(host.kinds().count("recheck"), 2)
        self.assertIn("access", host.kinds())

    def test_restart_failed_stops_before_access(self):
        host = FakeHost(yml=YML, states=("failed",))
        out = self.drive("_ntfy_mobile_prepare", host, ["", "", "y", "y"])
        self.assertNotIn("access", host.kinds())
        self.assertIn("failed", out)

    def test_restart_stuck_activating_gives_up(self):
        host = FakeHost(yml=YML, states=("activating",) * 7)
        self.drive("_ntfy_mobile_prepare", host, ["", "", "y", "y"])
        self.assertEqual(host.kinds().count("recheck"), 5)
        self.assertNotIn("access", host.kinds())

    def test_prepare_runs_access_as_auth_file_owner(self):
        host = FakeHost(owner="ntfy")
        self.drive("_ntfy_mobile_prepare", host, ["", "", "Alice", "", ""])
        self.assertEqual(host.user_of("access"), "ntfy")
        self.assertIsNone(host.user_of("inspect"))
        self.assertIn("erm_alice", host.script_of("access"))

    def test_prepare_stops_when_no_token(self):
        host = FakeHost(token_out="error: boom\n")
        out = self.drive("_ntfy_mobile_prepare", host, ["", "", "Alice"])
        self.assertNotIn(TOKEN, out)
        self.assertNotIn("erplibre-ntfy:", out)

    def test_prepare_prints_link_and_never_writes_token(self):
        host = FakeHost()
        real_open = builtins.open
        written = []

        def spy(file, mode="r", *a, **k):
            if any(c in str(mode) for c in "wax+"):
                written.append((file, mode))
            return real_open(file, mode, *a, **k)

        with mock.patch("builtins.open", spy):
            out = self.drive(
                "_ntfy_mobile_prepare", host, ["", "", "Alice", "", ""]
            )
        self.assertEqual(written, [])
        link = re.search(r"erplibre-ntfy:\S+", out).group(0)
        self.assertIn(TOKEN, link)
        self.assertIn("QRART", out)
        self.assertLess(out.index("QRART"), out.index(link))
        self.assertIn("prefix=up", link)

    def test_default_phone_url_uses_base_url_else_lan(self):
        host = FakeHost()
        out = self.drive(
            "_ntfy_mobile_prepare", host, ["", "", "Alice", "", ""]
        )
        self.assertIn("url=http%3A%2F%2Fntfy.exemple.test", out)
        host = FakeHost(yml=YML_LOCAL_URL)
        out = self.drive(
            "_ntfy_mobile_prepare", host, ["", "", "Alice", "", ""]
        )
        self.assertIn("url=http%3A%2F%2F192.0.2.7%3A8080", out)

    def test_explicit_urls_land_in_the_link(self):
        host = FakeHost()
        out = self.drive(
            "_ntfy_mobile_prepare",
            host,
            [
                "",
                "",
                "Alice",
                "http://p.exemple.test",
                "http://o.exemple.test",
            ],
        )
        self.assertIn("url=http%3A%2F%2Fp.exemple.test&", out)
        self.assertIn("odoo=http%3A%2F%2Fo.exemple.test", out)

    def test_prepare_without_segno_prints_install_hint(self):
        host = FakeHost()
        out = self.drive(
            "_ntfy_mobile_prepare",
            host,
            ["", "", "Alice", "", ""],
            qr=None,
        )
        self.assertIn("requirement/erplibre_require-ments.txt", out)
        self.assertIn("erplibre-ntfy:", out)

    def test_dash_skips_exempt_hosts_and_warns(self):
        host = FakeHost(yml=YML)
        out = self.drive(
            "_ntfy_mobile_prepare", host, ["", "-", "Alice", "", ""]
        )
        self.assertIn("429", out)
        self.assertNotIn("write", host.kinds())


class TestHost(MenuCase):
    def test_ssh_host_quotes_the_script_once(self):
        target = (
            "me@ntfy.exemple.test",
            "me",
            "ntfy.exemple.test",
            "x",
            False,
        )
        with (
            mock.patch("builtins.input", side_effect=["2"]),
            mock.patch.object(
                self.todo, "_ask_ssh_target", return_value=target
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            host = self.todo._ntfy_mobile_host()
        self.assertIsInstance(host, nm.SshHost)
        script = "echo 'a b'; echo \"$X\"\n"
        argv = host.argv(script, "ntfy")
        self.assertEqual(argv[:3], ["ssh", "-t", "me@ntfy.exemple.test"])
        self.assertEqual(
            shlex.split(argv[3]), ["sudo", "-u", "ntfy", "sh", "-c", script]
        )

    def test_ssh_cancelled_gives_none(self):
        with (
            mock.patch("builtins.input", side_effect=["2"]),
            mock.patch.object(self.todo, "_ask_ssh_target", return_value=None),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsNone(self.todo._ntfy_mobile_host())

    def test_local_host_default(self):
        with (
            mock.patch("builtins.input", side_effect=[""]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsInstance(self.todo._ntfy_mobile_host(), nm.LocalHost)


class TestListRevoke(MenuCase):
    def test_list_prints_phone_users_only(self):
        host = FakeHost()
        out = self.drive("_ntfy_mobile_list", host, [""])
        self.assertIn("erm_alice", out)
        self.assertIn("erm_bruno", out)
        self.assertNotIn("anonymous", out)
        self.assertEqual(host.user_of("list"), "ntfy")

    def test_revoke_confirms_then_deletes_user(self):
        host = FakeHost()
        self.drive("_ntfy_mobile_revoke", host, ["", "2", "y"])
        script = host.script_of("revoke")
        self.assertIn("erm_bruno", script)
        self.assertEqual(host.user_of("revoke"), "ntfy")

    def test_revoke_declined_deletes_nothing(self):
        host = FakeHost()
        self.drive("_ntfy_mobile_revoke", host, ["", "1", "n"])
        self.assertNotIn("revoke", host.kinds())

    def test_revoke_invalid_choice_deletes_nothing(self):
        host = FakeHost()
        self.drive("_ntfy_mobile_revoke", host, ["", "9"])
        self.assertNotIn("revoke", host.kinds())


class TestTranslations(unittest.TestCase):
    def test_every_new_string_translated(self):
        tree = ast.parse(MENU_PY.read_text(encoding="utf-8"))
        keys = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "t"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        keys |= {
            "ntfy_mobile_no_auth_file",
            "ntfy_mobile_not_deny_all",
            "ntfy_mobile_subscriber_rate_limiting",
            "Deploy - Prepare ntfy for ERPLibre mobile",
        }
        self.assertGreater(len(keys), 20)
        for key in sorted(keys):
            self.assertIn(key, TRANSLATIONS, key)
            for lang in ("fr", "en"):
                self.assertTrue(TRANSLATIONS[key].get(lang), (key, lang))
        self.assertTrue(
            TRANSLATIONS["Deploy - Prepare ntfy for ERPLibre mobile"][
                "fr"
            ].startswith("📱 Déployer - Préparer ntfy pour ERPLibre mobile")
        )

    def test_dynamic_t_calls_are_only_the_problem_keys(self):
        tree = ast.parse(MENU_PY.read_text(encoding="utf-8"))
        dynamic = [
            ast.unparse(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "t"
            and node.args
            and not isinstance(node.args[0], ast.Constant)
        ]
        self.assertTrue(set(dynamic) <= {"problem"}, dynamic)


if __name__ == "__main__":
    unittest.main()
