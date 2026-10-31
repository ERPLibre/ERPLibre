#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Sous-menu « Infrastructure d'appel » : installer, vérifier, désinstaller.

Aucun installateur, aucun sudo, aucun réseau : l'hôte est une doublure qui
reconnaît chaque script aux lignes `@@NOM` qu'il imprime, rend une sortie
préparée et garde l'état que le menu lui fait écrire. Toutes les valeurs
sont inventées (`*.exemple.test`, 192.0.2.x).
"""

import ast
import base64
import contextlib
import datetime
import io
import json
import re
import shlex
import string
import sys
import unittest
from pathlib import Path
from unittest import mock

from script.todo import call_infra as ci
from script.todo import call_infra_menu as cim
from script.todo import ntfy_mobile as nm
from script.todo.todo_i18n import TRANSLATIONS, t

REPO = Path(__file__).resolve().parent.parent
MENU_PY = REPO / "script" / "todo" / "call_infra_menu.py"
CALL_INFRA_PY = REPO / "script" / "todo" / "call_infra.py"

CHECK_KEY = "0123456789abcdef0123456789abcdef"
ADMIN_PASSWORD = "Mot-de-passe-invente-42"
FOREIGN_COTURN = "listening-port=3478\nrealm=ancien.exemple.test\n"
UTC = datetime.timezone.utc


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# La ligne de `_state_write_lines` qui pose l'état : la doublure en relit
# le base64, comme l'hôte l'écrirait.
STATE_LINE = re.compile(r'printf %s (\S+) \| base64 -d > "\$STATE\.new"')


def state_of(script):
    payload = shlex.split(STATE_LINE.search(script).group(1))[0]
    return json.loads(base64.b64decode(payload))


class FakeHost:
    """Hôte doublure. Un script se reconnaît aux marqueurs qu'il imprime,
    jamais à une sous-chaîne de commande : le script d'installation porte
    les installateurs, qui contiennent presque tous les mots."""

    def __init__(
        self,
        os_line="debian 13",
        systemd=True,
        firewall="none",
        coturn="- - -",
        ntfy="- - /etc/ntfy/server.yml",
        files=None,
        ports=(("tcp", 22, "sshd"),),
        state=None,
        install_ok=True,
        admin_password=None,
        sudo_error=None,
        sudo_code=1,
        firewall_out=None,
        uninstall_out="@@REMOVED state\n@@DONE yes\n",
        uninstall_code=0,
        firewall_pending=(),
        state_code=0,
    ):
        self.os_line = os_line
        self.systemd = systemd
        self.firewall = firewall
        self.coturn = coturn
        self.ntfy = ntfy
        self.files = dict(files or {})
        self.ports = ports
        self.state = state
        self.install_ok = install_ok
        self.admin_password = admin_password
        self.sudo_error = sudo_error
        self.sudo_code = sudo_code
        self.firewall_out = firewall_out
        self.uninstall_out = uninstall_out
        self.uninstall_code = uninstall_code
        self.firewall_pending = list(firewall_pending)
        self.state_code = state_code
        self.calls = []

    @staticmethod
    def kind(script):
        if "@@OS" in script:
            return "probe"
        if "@@CHECK_KEY" in script:
            return "check"
        if "@@NOTHING" in script:
            return "uninstall-empty"
        if "@@DONE" in script:
            return "uninstall"
        if "@@SAVED" in script and "@@ACTIVE" in script:
            return "install"
        if "@@SAVED" in script:
            return "state"
        # Après les autres : la sonde et la vérification nomment aussi des
        # lignes @@FIREWALL_*.
        if "@@FIREWALL_" in script:
            return "firewall"
        return "unknown"

    def kinds(self):
        return [self.kind(s) for s, _ in self.calls]

    def script_of(self, kind):
        return next(s for s, _ in self.calls if self.kind(s) == kind)

    def probe_output(self):
        lines = [
            f"@@OS {self.os_line} ",
            f"@@SYSTEMD {'yes' if self.systemd else 'no'}",
            "@@HOSTNAME hote-exemple",
            "@@ADDR 192.0.2.10",
            *[f"@@PORT {p} {n} {proc}" for p, n, proc in self.ports],
            f"@@COTURN {self.coturn}",
            f"@@NTFY {self.ntfy}",
            *[
                f"@@FILE {path} {b64(text)}"
                for path, text in self.files.items()
            ],
            f"@@FIREWALL {self.firewall}",
        ]
        if self.state is not None:
            lines.append(f"@@STATE {b64(json.dumps(self.state))}")
        lines += [
            f"@@FIREWALL_PENDING {line}" for line in self.firewall_pending
        ]
        lines.append("@@END")
        return "\n".join(lines) + "\n"

    def run(self, script, sudo_user):
        """Rend (code, sortie) et recopie la sortie à l'écran par
        `sys.stdout.buffer`, comme `ntfy_mobile._tee_run`."""
        code, out = self._answer(script, sudo_user)
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(out.encode("utf-8"))
            buffer.flush()
        else:
            sys.stdout.write(out)
        return code, out

    def _answer(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        if self.sudo_error:
            return self.sudo_code, f"{self.sudo_error}\n"
        kind = self.kind(script)
        if kind == "probe":
            return 0, self.probe_output()
        if kind == "install":
            out = "".join(
                f"@@ACTIVE {svc} active\n"
                for svc in ci.SERVICES
                if f"RC_{svc}" in script
            )
            if self.admin_password:
                out = f"@@ADMIN_PASSWORD {self.admin_password}\n" + out
            if not self.install_ok:
                return 1, out + "@@ACTIVE ntfy failed\n@@SAVED no\n"
            self.state = state_of(script)
            return 0, out + "@@SAVED yes\n"
        if kind == "state":
            if self.state_code:
                return self.state_code, "@@FAILED state\n@@SAVED no\n"
            self.state = state_of(script)
            self.firewall_pending = []
            return 0, "@@SAVED yes\n"
        if kind == "firewall":
            out = self.firewall_out
            if out is None:
                out = (
                    "@@FIREWALL_ADDED udp 3478 coturn\n"
                    "@@FIREWALL_ADDED tcp 3478 coturn\n"
                    "@@FIREWALL_PERSISTED yes\n@@END\n"
                )
            return 0, out
        if kind == "check":
            out = "\n@@ACTIVE coturn active\n@@ACTIVE ntfy active\n"
            if self.state is not None:
                out = f"\n@@STATE {b64(json.dumps(self.state))}" + out
            return 0, out + f"@@CHECK_KEY {CHECK_KEY}\n@@END\n"
        if kind == "uninstall-empty":
            return 0, "@@NOTHING\n"
        if kind == "uninstall":
            if self.uninstall_code == 0:
                self.state = None
            return self.uninstall_code, self.uninstall_out
        return 0, ""


def answers(**changes):
    values = dict(
        services=frozenset({"coturn", "ntfy"}),
        tls="none",
        cert_pem=None,
        key_pem=None,
        public_name="192.0.2.10",
    )
    values.update(changes)
    return ci.Answers(**values)


def installed_state(ans=None):
    facts = ci.parse_probe(FakeHost().probe_output())
    plan = ci.plan_install(facts, ans or answers(), datetime.datetime.now(UTC))
    return ci.written_state(plan, "20261030-101500")


LINES = [
    ci.CheckLine(
        "turn-udp",
        True,
        "call_infra_check_relayed",
        {"relayed": "192.0.2.10:50000"},
    ),
    ci.CheckLine(
        "ntfy-health", False, "call_infra_check_unhealthy", {"status": 503}
    ),
    ci.CheckLine(
        "firewall", None, "call_infra_check_firewall_none", {"kind": "none"}
    ),
]


class MenuCase(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO()

    def drive(self, method, host, replies, lines=None):
        """Lance `method` avec `replies` pour input() ; rend la sortie."""
        pending = list(replies)
        out = io.StringIO()
        self.check_local = mock.Mock(return_value=lines or LINES)
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(
                mock.patch.object(
                    self.todo, "_call_infra_host", return_value=host
                )
            )
            stack.enter_context(
                mock.patch(
                    "builtins.input", side_effect=lambda *_: pending.pop(0)
                )
            )
            stack.enter_context(
                mock.patch.object(ci, "check_local", self.check_local)
            )
            getattr(self.todo, method)()
        self.assertEqual(pending, [], "answers unused")
        return out.getvalue()


# Réponses d'une installation acceptée telle que proposée : services, TLS,
# nom public, port TURN, plage des relais, port de ntfy, oui.
DEFAULTS = ["", "", "", "", "", ""]


class TestInstall(MenuCase):
    def test_full_install_on_a_fake_debian(self):
        host = FakeHost()
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertEqual(host.kinds(), ["probe", "install", "state", "check"])
        self.assertEqual(set(host.state["services"]), {"coturn", "ntfy"})
        self.assertEqual(
            host.state["firewall"],
            {"kind": "none", "rules": [], "persisted": False},
        )
        self.assertEqual(
            host.state["services"]["coturn"]["settings"]["public_name"],
            "192.0.2.10",
        )
        self.assertIn(t("call_infra_tls_none"), out)
        self.assertIn(t("call_infra_private_ranges_allowed"), out)
        self.assertIn(t("call_infra_firewall_none"), out)
        self.assertIn(t("call_infra_cloud_firewall"), out)
        self.check_local.assert_called_once()
        remote, address, cafile = self.check_local.call_args.args
        self.assertEqual((address, cafile), ("192.0.2.10", None))
        self.assertEqual(remote["check_key"], CHECK_KEY)
        self.assertIn(t("call_infra_installed"), out)
        self.assertIn("coturn : active", out)

    def test_every_script_runs_as_root(self):
        host = FakeHost()
        self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertEqual({user for _, user in host.calls}, {None})

    def test_the_install_script_carries_no_check_password(self):
        # Le mot de passe du compte de contrôle naît sur l'hôte : rien de
        # secret ne part d'ici pour lui.
        host = FakeHost()
        self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertNotIn("TURN_CHECK_PASSWORD", host.script_of("install"))
        self.assertFalse(hasattr(cim, "secrets"))

    def test_a_rerun_with_the_same_answers_changes_nothing(self):
        ans = answers()
        host = FakeHost(
            state=installed_state(ans),
            coturn="coturn active /etc/turnserver.conf",
            ntfy="ntfy active /etc/ntfy/server.yml",
            files={
                "/etc/turnserver.conf": ci.coturn_config(ans),
                "/etc/ntfy/server.yml": ci.ntfy_config(ans),
            },
            ports=(("udp", 3478, "turnserver"), ("tcp", 8080, "ntfy")),
        )
        out = self.drive("_call_infra_install", host, DEFAULTS)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(t("call_infra_nothing_to_change"), out)

    def rerun_host(self, **changes):
        ans = answers()
        values = dict(
            state=installed_state(ans),
            coturn="coturn active /etc/turnserver.conf",
            ntfy="ntfy active /etc/ntfy/server.yml",
            files={
                "/etc/turnserver.conf": ci.coturn_config(ans),
                "/etc/ntfy/server.yml": ci.ntfy_config(ans),
            },
            ports=(("udp", 3478, "turnserver"), ("tcp", 8080, "ntfy")),
        )
        values.update(changes)
        return FakeHost(**values)

    def test_a_rerun_still_offers_the_firewall_rules_not_recorded(self):
        # Un « non » au pare-feu, ou un état qui n'a pas pu s'écrire après
        # l'ajout, ne ferme pas la porte à la relance.
        host = self.rerun_host(firewall="ufw")
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o"])
        self.assertIn(t("call_infra_nothing_to_change"), out)
        self.assertEqual(host.kinds(), ["probe", "firewall", "state"])
        self.assertEqual(
            host.state["firewall"]["rules"],
            [["tcp", "3478", "coturn"], ["udp", "3478", "coturn"]],
        )

    def test_a_rerun_records_the_rules_a_failed_save_left_pending(self):
        host = self.rerun_host(
            firewall="ufw", firewall_pending=["ufw udp 49152:49252 coturn"]
        )
        self.drive("_call_infra_install", host, DEFAULTS + ["n"])
        self.assertEqual(host.kinds(), ["probe", "state"])
        self.assertEqual(
            host.state["firewall"]["rules"], [["udp", "49152:49252", "coturn"]]
        )

    def test_a_refused_state_save_says_the_state_is_not_saved(self):
        host = self.rerun_host(firewall="ufw")
        host.state_code = 0
        original = host._answer

        def answer(script, sudo_user):
            if host.kind(script) == "state":
                host.calls.append((script, sudo_user))
                return 1, "sudo: 3 saisies de mots de passe incorrectes\n"
            return original(script, sudo_user)

        host._answer = answer
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o"])
        self.assertIn(t("call_infra_sudo_refused"), out)
        self.assertIn(t("call_infra_state_not_saved"), out)

    def test_fedora_is_refused_before_any_question(self):
        host = FakeHost(os_line="fedora 41")
        out = self.drive("_call_infra_install", host, [])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_unsupported_os").format(
                os="fedora", supported=ci.SUPPORTED
            ),
            out,
        )

    def test_no_systemd_is_refused(self):
        host = FakeHost(systemd=False)
        out = self.drive("_call_infra_install", host, [])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(t("call_infra_no_systemd"), out)

    def test_a_refused_plan_shows_its_reason_and_installs_nothing(self):
        host = FakeHost(ports=(("tcp", 8080, "nginx"),))
        out = self.drive("_call_infra_install", host, DEFAULTS)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_port_busy").format(
                proto="tcp", port=8080, process="nginx"
            ),
            out,
        )

    def test_adoption_diff_is_shown_and_no_runs_nothing(self):
        host = FakeHost(
            coturn="coturn active /etc/turnserver.conf",
            files={"/etc/turnserver.conf": FOREIGN_COTURN},
            ports=(("udp", 3478, "turnserver"),),
        )
        replies = ["2", "", "", "", "", "n"]
        out = self.drive("_call_infra_install", host, replies)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("-realm=ancien.exemple.test", out)
        self.assertIn("+" + ci.MARKER, out)
        self.assertIn(
            t("call_infra_adopted").format(
                service="coturn", config="/etc/turnserver.conf"
            ),
            out,
        )
        self.assertIn(t("Nothing installed."), out)

    def test_firewall_no_leaves_no_rule(self):
        host = FakeHost(firewall="ufw")
        out = self.drive(
            "_call_infra_install", host, DEFAULTS + ["o", "n", ""]
        )
        self.assertEqual(host.kinds(), ["probe", "install", "state", "check"])
        self.assertIn("ufw allow 3478/udp comment 'erplibre-call coturn'", out)
        self.assertEqual(
            host.state["firewall"],
            {"kind": "ufw", "rules": [], "persisted": False},
        )

    def test_firewall_yes_records_the_rules_added(self):
        host = FakeHost(firewall="ufw")
        self.drive("_call_infra_install", host, DEFAULTS + ["o", "o", ""])
        self.assertEqual(
            host.kinds(), ["probe", "install", "firewall", "state", "check"]
        )
        self.assertEqual(
            host.state["firewall"]["rules"],
            [["tcp", "3478", "coturn"], ["udp", "3478", "coturn"]],
        )
        self.assertTrue(host.state["firewall"]["persisted"])

    def test_nftables_without_a_single_chain_says_to_open_by_hand(self):
        host = FakeHost(firewall="nftables")
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertNotIn("firewall", host.kinds())
        self.assertIn(t("call_infra_firewall_manual"), out)

    def test_a_failed_install_writes_no_state_and_stops(self):
        host = FakeHost(install_ok=False)
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o"])
        self.assertEqual(host.kinds(), ["probe", "install"])
        self.assertIsNone(host.state)
        self.assertIn(t("call_infra_install_failed"), out)
        self.assertIn("ntfy : failed", out)

    def test_the_admin_password_is_shown_once(self):
        host = FakeHost(admin_password=ADMIN_PASSWORD)
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertEqual(out.count(ADMIN_PASSWORD), 1)

    def test_the_admin_password_survives_a_failed_install(self):
        host = FakeHost(admin_password=ADMIN_PASSWORD, install_ok=False)
        out = self.drive("_call_infra_install", host, DEFAULTS + ["o"])
        self.assertEqual(out.count(ADMIN_PASSWORD), 1)

    def test_sudo_refused_gives_a_clear_line(self):
        # Décidé par la forme de la sortie, pas par son texte : sudo parle
        # la langue de l'utilisateur, et aucun message n'est prévisible.
        for error in (
            "sudo: 3 incorrect password attempts",
            "sudo: a password is required",
            "sudo: 3 saisies de mots de passe incorrectes",
            "alice is not in the sudoers file.",
        ):
            with self.subTest(error=error):
                host = FakeHost(sudo_error=error)
                out = self.drive("_call_infra_install", host, [])
                self.assertEqual(host.kinds(), ["probe"])
                self.assertIn(t("call_infra_sudo_refused"), out)
                self.assertNotIn("Traceback", out)

    def test_a_failed_ssh_connection_is_not_a_sudo_refusal(self):
        # ssh rend 255 quand la connexion (ou le dépôt du script) échoue.
        host = FakeHost(
            sudo_error="ssh: connect to host: refused", sudo_code=255
        )
        out = self.drive("_call_infra_install", host, [])
        self.assertNotIn(t("call_infra_sudo_refused"), out)
        self.assertIn(t("call_infra_probe_incomplete"), out)

    def test_an_unreadable_certificate_stops_before_installing(self):
        host = FakeHost()
        replies = ["", "2", "/nonexistent/exemple.crt"]
        out = self.drive("_call_infra_install", host, replies)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("/nonexistent/exemple.crt", out)

    def test_a_port_that_is_not_a_number_stops(self):
        host = FakeHost()
        out = self.drive("_call_infra_install", host, ["", "", "", "abc"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("abc", out)

    def test_ssh_default_public_name_is_the_real_host(self):
        host = FakeHost()
        ssh = nm.SshHost("alias-exemple", hostname="turn.exemple.test")
        ssh.run = host.run
        self.drive("_call_infra_install", ssh, DEFAULTS + ["o", ""])
        settings = host.state["services"]["ntfy"]["settings"]
        self.assertEqual(settings["public_name"], "turn.exemple.test")


class TestCheck(MenuCase):
    def test_one_line_per_check_line(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_check", host, [""])
        self.assertEqual(host.kinds(), ["check"])
        shown = [
            line for line in out.splitlines() if line[:2] in ("✓ ", "✗ ", "? ")
        ]
        self.assertEqual(len(shown), len(LINES))
        self.assertTrue(shown[0].startswith("✓ "))
        self.assertTrue(shown[1].startswith("✗ "))
        self.assertTrue(shown[2].startswith("? "))
        self.assertIn(
            t("call_infra_check_unhealthy").format(status=503), shown[1]
        )
        self.assertNotIn(CHECK_KEY, out)

    def test_supplied_tls_asks_for_the_authority(self):
        state = installed_state()
        for record in state["services"].values():
            record["settings"]["tls"] = "supplied"
        host = FakeHost(state=state)
        self.drive(
            "_call_infra_check", host, ["turn.exemple.test", "/ca/exemple.crt"]
        )
        _remote, address, cafile = self.check_local.call_args.args
        self.assertEqual(address, "turn.exemple.test")
        self.assertEqual(cafile, "/ca/exemple.crt")

    def test_no_state_asks_nothing(self):
        host = FakeHost()
        lines = [ci.CheckLine("state", False, "call_infra_check_no_state")]
        out = self.drive("_call_infra_check", host, [], lines=lines)
        self.assertIn(t("call_infra_check_no_state"), out)

    def test_the_check_key_line_is_hidden_on_screen(self):
        """Joué pour vrai par `sh`, sous l'utilisateur courant : la clé
        reste dans la sortie rendue et ne paraît pas à l'écran."""
        host = nm.LocalHost(sudo=())
        script = (
            "printf '[sudo] password: '; echo; "
            f"echo '@@CHECK_KEY {CHECK_KEY}'; echo '@@CHECK ok'"
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code, captured = self.todo._call_infra_run(
                host, script, hide=("@@CHECK_KEY",)
            )
        self.assertEqual(code, 0)
        self.assertIn(CHECK_KEY, captured)
        self.assertNotIn(CHECK_KEY, out.getvalue())
        self.assertIn("[sudo] password: ", out.getvalue())
        self.assertIn("@@CHECK_KEY ***", out.getvalue())
        self.assertIn("@@CHECK ok", out.getvalue())


class TestHiddenLines(unittest.TestCase):
    def feed(self, data, prefixes=("@@CHECK_KEY",)):
        target = io.StringIO()
        writer = cim._HiddenLines(target, prefixes)
        for byte in data:
            writer.buffer.write(bytes([byte]))
        writer.finish()
        return target.getvalue()

    def test_a_prompt_without_newline_is_shown_at_once(self):
        target = io.StringIO()
        writer = cim._HiddenLines(target, ("@@CHECK_KEY",))
        for byte in b"[sudo] password: ":
            writer.buffer.write(bytes([byte]))
        self.assertEqual(target.getvalue(), "[sudo] password: ")

    def test_a_hidden_line_with_crlf(self):
        self.assertEqual(
            self.feed(b"a\r\n@@CHECK_KEY abc\r\n@@CHECK x\r\n"),
            "a\r\n@@CHECK_KEY ***\n@@CHECK x\r\n",
        )

    def test_a_partial_prefix_at_the_end_is_kept(self):
        self.assertEqual(self.feed(b"ok\n@@CHE"), "ok\n@@CHE")

    def test_utf8_survives_byte_by_byte(self):
        self.assertEqual(self.feed("déjà\n".encode()), "déjà\n")


class TestUninstall(MenuCase):
    def test_uninstall_twice(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_uninstall", host, ["n", "o"])
        self.assertEqual(host.kinds(), ["probe", "uninstall"])
        self.assertIn(t("call_infra_uninstalled"), out)
        self.assertIsNone(host.state)
        out = self.drive("_call_infra_uninstall", host, [])
        self.assertEqual(host.kinds()[2:], ["probe", "uninstall-empty"])
        self.assertIn(t("Nothing to uninstall."), out)
        self.assertEqual(
            TRANSLATIONS["Nothing to uninstall."]["fr"], "Rien à désinstaller."
        )

    def test_remove_data_follows_the_answer(self):
        for reply, expected in (("o", True), ("n", False)):
            with self.subTest(reply=reply):
                host = FakeHost(state=installed_state())
                with mock.patch.object(
                    ci, "uninstall_script", wraps=ci.uninstall_script
                ) as built:
                    self.drive("_call_infra_uninstall", host, [reply, "o"])
                self.assertEqual(built.call_args.args[1], expected)

    def test_declined_runs_nothing(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_uninstall", host, ["n", "n"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(t("Nothing uninstalled."), out)

    def test_a_failed_uninstall_keeps_the_state_and_says_so(self):
        host = FakeHost(
            state=installed_state(),
            uninstall_out="@@FAILED purge-ntfy\n@@DONE no\n",
            uninstall_code=1,
        )
        out = self.drive("_call_infra_uninstall", host, ["n", "o"])
        self.assertIn("purge-ntfy", out)
        self.assertIn(t("call_infra_uninstall_failed"), out)
        self.assertIsNotNone(host.state)

    def test_a_missing_backup_ends_partial(self):
        host = FakeHost(
            state=installed_state(),
            uninstall_out=(
                "@@BACKUP_MISSING coturn /etc/turnserver.conf.bak-1\n"
                "@@DONE partial\n"
            ),
            uninstall_code=1,
        )
        out = self.drive("_call_infra_uninstall", host, ["n", "o"])
        self.assertIn(
            t("call_infra_backup_missing").format(
                service="coturn", backup="/etc/turnserver.conf.bak-1"
            ),
            out,
        )

    def test_a_lost_backup_after_a_purge_is_said(self):
        host = FakeHost(
            state=installed_state(),
            uninstall_out=(
                "@@BACKUP_LOST coturn /etc/turnserver.conf.bak-1\n"
                "@@DONE yes\n"
            ),
        )
        out = self.drive("_call_infra_uninstall", host, ["n", "o"])
        self.assertIn(
            t("call_infra_backup_lost").format(
                service="coturn", backup="/etc/turnserver.conf.bak-1"
            ),
            out,
        )
        self.assertIn(t("call_infra_uninstalled"), out)

    def test_pending_firewall_rules_are_removed_too(self):
        host = FakeHost(
            state=installed_state(), firewall_pending=["ufw udp 3478 coturn"]
        )
        with mock.patch.object(
            ci, "uninstall_script", wraps=ci.uninstall_script
        ) as built:
            out = self.drive("_call_infra_uninstall", host, ["n", "o"])
        self.assertEqual(
            ci.rules_from_state(built.call_args.args[0]),
            (ci.Rule("udp", "3478", "coturn"),),
        )
        self.assertIn("3478/udp", out)

    def test_a_state_of_another_version_is_refused(self):
        state = installed_state()
        state["version"] = 99
        host = FakeHost(state=state)
        out = self.drive("_call_infra_uninstall", host, [])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_state_version").format(found=99, expected=1), out
        )


class TestHost(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO()

    def host(self, chosen):
        out = io.StringIO()
        with (
            mock.patch.object(
                self.todo, "_ntfy_mobile_host", return_value=chosen
            ),
            contextlib.redirect_stdout(out),
        ):
            return self.todo._call_infra_host(), out.getvalue()

    def test_the_host_choice_says_nothing(self):
        # L'avertissement d'adoption est celui de l'installation : la
        # vérification et la désinstallation passent aussi par ici.
        for chosen in (nm.LocalHost(), nm.SshHost("alias-exemple")):
            with self.subTest(host=type(chosen).__name__):
                host, out = self.host(chosen)
                self.assertIs(host, chosen)
                self.assertEqual(out, "")

    def test_cancelled(self):
        host, _out = self.host(None)
        self.assertIsNone(host)


class LocalFakeHost(FakeHost, nm.LocalHost):
    """FakeHost qui passe pour cette machine."""


NTFY_FOREIGN = 'listen-http: ":8080"\nauth-default-access: "read-write"\n'


class TestLocalNtfyWarning(MenuCase):
    def ntfy_host(self, cls, text):
        return cls(
            ntfy="ntfy active /etc/ntfy/server.yml",
            files={"/etc/ntfy/server.yml": text},
            ports=(("tcp", 22, "sshd"), ("tcp", 8080, "ntfy")),
        )

    def test_install_here_warns_for_a_foreign_ntfy(self):
        host = self.ntfy_host(LocalFakeHost, NTFY_FOREIGN)
        out = self.drive("_call_infra_install", host, DEFAULTS + ["n"])
        self.assertIn(t("call_infra_local_ntfy_adopted"), out)

    def test_install_here_says_nothing_for_the_tool_config(self):
        ans = answers()
        host = self.ntfy_host(LocalFakeHost, ci.ntfy_config(ans))
        out = self.drive("_call_infra_install", host, DEFAULTS + ["n"])
        self.assertNotIn(t("call_infra_local_ntfy_adopted"), out)

    def test_install_over_ssh_says_nothing(self):
        host = self.ntfy_host(FakeHost, NTFY_FOREIGN)
        out = self.drive("_call_infra_install", host, DEFAULTS + ["n"])
        self.assertNotIn(t("call_infra_local_ntfy_adopted"), out)

    def test_check_and_uninstall_say_nothing(self):
        state = installed_state()
        for method, replies in (
            ("_call_infra_check", [""]),
            ("_call_infra_uninstall", ["n", "n"]),
        ):
            with self.subTest(method=method):
                host = self.ntfy_host(LocalFakeHost, NTFY_FOREIGN)
                host.state = state
                out = self.drive(method, host, replies)
                self.assertNotIn(t("call_infra_local_ntfy_adopted"), out)


class TestSubmenu(unittest.TestCase):
    def test_dispatches_to_the_four_actions(self):
        from script.todo.todo import TODO

        todo = TODO()
        with (
            mock.patch.object(TODO, "_call_infra_install") as install,
            mock.patch.object(TODO, "prompt_execute_ntfy_mobile") as mobile,
            mock.patch.object(TODO, "_call_infra_check") as check,
            mock.patch.object(TODO, "_call_infra_uninstall") as uninstall,
            mock.patch("click.prompt", side_effect=["1", "2", "3", "4", "0"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_execute_call_infra()
        for called in (install, mobile, check, uninstall):
            called.assert_called_once_with()

    def test_breadcrumb_label(self):
        from script.todo.todo import TODO

        self.assertEqual(
            TODO._MENU_LABELS["prompt_execute_call_infra"],
            "Call infrastructure",
        )

    def test_the_old_local_ntfy_install_is_gone(self):
        from script.todo.todo import TODO

        self.assertFalse(hasattr(TODO, "_deploy_ntfy_server"))


def _literal_t_keys(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "t"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }


def _fields(text):
    return {
        name
        for _, name, _, _ in string.Formatter().parse(text)
        if name is not None
    }


class TestTranslations(unittest.TestCase):
    def test_every_literal_key_exists_in_fr_and_en(self):
        keys = _literal_t_keys(MENU_PY)
        self.assertGreater(len(keys), 30)
        for key in sorted(keys):
            self.assertIn(key, TRANSLATIONS, key)
            for lang in ("fr", "en"):
                self.assertTrue(TRANSLATIONS[key].get(lang), (key, lang))

    def test_every_key_call_infra_hands_out_is_translated(self):
        """Refus, notes du pare-feu et verdicts arrivent par une variable :
        aucun `t("…")` littéral ne les montre au test précédent."""
        source = CALL_INFRA_PY.read_text(encoding="utf-8")
        source += MENU_PY.read_text(encoding="utf-8")
        keys = set(re.findall(r'"(call_infra_[a-z_]+)"', source))
        keys |= set(ci.CHECK_KEYS)
        self.assertGreater(len(keys), 25)
        for key in sorted(keys):
            self.assertIn(key, TRANSLATIONS, key)
            fr, en = TRANSLATIONS[key]["fr"], TRANSLATIONS[key]["en"]
            self.assertTrue(fr and en, key)
            self.assertEqual(_fields(fr), _fields(en), key)

    def test_every_message_formats_with_its_fields(self):
        class Any(dict):
            def __missing__(self, key):
                return "x"

        for key, entry in TRANSLATIONS.items():
            if not key.startswith("call_infra_"):
                continue
            for lang in ("fr", "en"):
                entry[lang].format_map(Any())

    def test_menu_entries(self):
        self.assertEqual(
            TRANSLATIONS["Deploy - Call infrastructure"]["fr"],
            "📞 Déployer - Infrastructure d'appel",
        )
        expected = {
            "Call infra - Install on a host (coturn, ntfy)": (
                "Installer sur un hôte (coturn, ntfy)"
            ),
            "Call infra - Prepare ntfy for ERPLibre mobile": (
                "Préparer ntfy pour ERPLibre mobile"
            ),
            "Call infra - Check": "Vérifier",
            "Call infra - Uninstall": "Désinstaller",
        }
        for key, fr in expected.items():
            self.assertEqual(TRANSLATIONS[key]["fr"], fr, key)

    def test_the_removed_install_keys_are_gone(self):
        for key in (
            "Deploy - Install NTFY notification server",
            "Fix this with: Deploy - Install NTFY notification server.",
        ):
            self.assertNotIn(key, TRANSLATIONS)


class TestDocumentation(unittest.TestCase):
    """La documentation nomme le menu à sa place actuelle.

    Les `.base.md` sont les sources ; les `.md` et `.fr.md` sont générés
    par mmg, donc les lire prouve aussi que la génération a été faite.
    `docs/superpowers/` est exclu : plans et specs datés décrivent l'état
    du jour où ils ont été écrits."""

    MENU_EN = "TODO › Deploy › Call infrastructure"
    MENU_FR = "TODO › Déployer › Infrastructure d'appel"
    OLD_PATHS = ("Deploy › Prepare ntfy", "Déployer › Préparer ntfy")

    def _read(self, relative):
        return (REPO / relative).read_text(encoding="utf-8")

    def test_no_source_doc_names_the_old_deploy_path(self):
        import subprocess

        listed = subprocess.run(
            ["git", "ls-files", "*.base.md"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.split()
        sources = [p for p in listed if not p.startswith("docs/superpowers/")]
        self.assertIn("CHANGELOG.base.md", sources)
        for relative in sources:
            text = self._read(relative)
            for old in self.OLD_PATHS:
                self.assertNotIn(old, text, relative)

    def test_the_changelog_names_the_menu_in_both_languages(self):
        unreleased = self._read("CHANGELOG.base.md").split("## [1.8.0]")[0]
        for needle in (self.MENU_EN, self.MENU_FR, "coturn"):
            self.assertIn(needle, unreleased)
        self.assertIn(self.MENU_EN, self._read("CHANGELOG.md"))
        self.assertIn(self.MENU_FR, self._read("CHANGELOG.fr.md"))

    def test_the_long_test_readme_names_the_menu_in_both_languages(self):
        self.assertIn(
            self.MENU_EN + " › Prepare ntfy for ERPLibre mobile",
            self._read("long_test/README.md"),
        )
        self.assertIn(
            self.MENU_FR + " › Préparer ntfy pour ERPLibre mobile",
            self._read("long_test/README.fr.md"),
        )


if __name__ == "__main__":
    unittest.main()
