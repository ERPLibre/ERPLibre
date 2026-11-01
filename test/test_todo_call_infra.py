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
import os
import socket
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.todo import call_infra as ci
from script.todo import call_infra_menu as cim
from script.todo import ntfy_mobile as nm
from script.todo import odoo_link as ol
from script.todo.todo_i18n import TRANSLATIONS, t

REPO = Path(__file__).resolve().parent.parent
MENU_PY = REPO / "script" / "todo" / "call_infra_menu.py"
CALL_INFRA_PY = REPO / "script" / "todo" / "call_infra.py"
ODOO_LINK_PY = REPO / "script" / "todo" / "odoo_link.py"

CHECK_KEY = "0123456789abcdef0123456789abcdef"
ADMIN_PASSWORD = "Mot-de-passe-invente-42"
FOREIGN_COTURN = "listening-port=3478\nrealm=ancien.exemple.test\n"
UTC = datetime.timezone.utc


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# La ligne de `_state_write_lines` qui pose l'état : la doublure en relit
# le base64, comme l'hôte l'écrirait.
STATE_LINE = re.compile(r'printf %s (\S+) \| base64 -d > "\$STATE\.new"')
# Quand l'état prend des valeurs à la sortie des installateurs, il passe
# par un gabarit : la variante qui porte `admin_added` vient en premier, et
# chaque "__RUN_<nom>__" vaut la valeur de plan `J_<nom>` (aucun marqueur
# d'installateur dans la sortie de la doublure).
TEMPLATE_LINE = re.compile(r'printf %s (\S+) \| base64 -d > "\$D/state\.tpl"')
RUN_VALUE = re.compile(r"^\s*J_(\w+)=(.*)$", re.M)


def state_of(script, admin_added=False):
    found = STATE_LINE.search(script)
    if found:
        payload = shlex.split(found.group(1))[0]
        return json.loads(base64.b64decode(payload))
    variants = TEMPLATE_LINE.findall(script)
    chosen = variants[0] if admin_added and len(variants) > 1 else variants[-1]
    text = base64.b64decode(shlex.split(chosen)[0]).decode("utf-8")
    defaults = {}
    for name, value in RUN_VALUE.findall(script):
        defaults.setdefault(name, shlex.split(value)[0])
    for name, value in defaults.items():
        text = text.replace(f'"__RUN_{name}__"', value)
    return json.loads(text)


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
        probe_extra=(),
        check_extra=(),
        odoo_add_ok=True,
        odoo_remove_ok=True,
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
        # Lignes de sonde de production (`@@NGINX ...`, `@@CERTBOT ...`).
        self.probe_extra = list(probe_extra)
        # Lignes de la base de coturn que la vérification lit
        # (`@@TURN_SECRET ...`, `@@TURN_USER ...`).
        self.check_extra = list(check_extra)
        # Issue des scripts d'un serveur Odoo : l'ajout et le retrait
        # réussissent, ou s'arrêtent à l'étape « coturn ».
        self.odoo_add_ok = odoo_add_ok
        self.odoo_remove_ok = odoo_remove_ok
        self.calls = []

    @staticmethod
    def kind(script):
        # Les scripts d'un serveur Odoo d'abord : celui d'ajout peut porter
        # l'installateur de coturn et l'écriture de l'état.
        if "@@ODOO_ADDED" in script:
            return "odoo-add"
        if "@@ODOO_REMOVED" in script:
            return "odoo-remove"
        if "@@ODOO_ROLLBACK" in script:
            return "odoo-rollback"
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
            *self.probe_extra,
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

    def _odoo_answer(self, kind, script):
        """Sortie d'un script d'un serveur Odoo ; l'ajout qui bascule le
        mode, ou purge, et le retrait écrivent l'état dès ce script."""
        if kind == "odoo-add":
            if not self.odoo_add_ok:
                return 1, "@@FAILED coturn\n@@ODOO_ADDED no\n"
            if STATE_LINE.search(script):
                self.state = state_of(script)
            return 0, "@@TURN_MODE secret\n@@ODOO_ADDED yes\n"
        if kind == "odoo-remove":
            if not self.odoo_remove_ok:
                return 1, "@@FAILED coturn\n@@ODOO_REMOVED no\n"
            self.state = state_of(script)
            return 0, "@@ODOO_REMOVED yes\n"
        return 0, "@@ODOO_ROLLBACK yes\n"

    def _answer(self, script, sudo_user):
        self.calls.append((script, sudo_user))
        if self.sudo_error:
            return self.sudo_code, f"{self.sudo_error}\n"
        kind = self.kind(script)
        if kind == "probe":
            return 0, self.probe_output()
        if kind.startswith("odoo-"):
            return self._odoo_answer(kind, script)
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
            self.state = state_of(script, bool(self.admin_password))
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
            extra = "".join(line + "\n" for line in self.check_extra)
            return 0, out + f"@@CHECK_KEY {CHECK_KEY}\n{extra}@@END\n"
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
        # {nom: [adresses]} que la résolution doublure rend ; un nom absent
        # ne résout pas. Aucune requête DNS ne part des tests.
        self.dns = {}
        self.prompts = []
        # Les invites passées à getpass(), saisie sans écho.
        self.hidden = []
        # Le lien vers Odoo que rend la fabrique doublure, et les
        # arguments de chaque construction.
        self.link = None
        self.made = []

    def make_link(self, method, url, database, **how):
        self.made.append((method, url, database, how))
        return self.link

    def resolve(self, name, port):
        if name not in self.dns:
            raise socket.gaierror(socket.EAI_NONAME, "Name not known")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))
            for address in self.dns[name]
        ]

    def reply(self, pending, prompt=""):
        self.prompts.append(prompt)
        return pending.pop(0)

    def reply_hidden(self, pending, prompt=""):
        self.hidden.append(prompt)
        return self.reply(pending, prompt)

    def drive(self, method, host, replies, lines=None):
        """Lance `method` avec `replies` pour input() ; rend la sortie.
        Les invites passées à input() sont gardées dans `self.prompts`."""
        pending = list(replies)
        out = io.StringIO()
        self.check_local = mock.Mock(return_value=lines or LINES)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(cim, "_resolve", self.resolve)
            )
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(
                mock.patch.object(
                    self.todo, "_call_infra_host", return_value=host
                )
            )
            stack.enter_context(
                mock.patch(
                    "builtins.input",
                    side_effect=lambda *a: self.reply(pending, *a),
                )
            )
            stack.enter_context(
                mock.patch(
                    "getpass.getpass",
                    side_effect=lambda *a: self.reply_hidden(pending, *a),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    self.todo, "_call_infra_make_link", self.make_link
                )
            )
            stack.enter_context(
                mock.patch.object(ci, "check_local", self.check_local)
            )
            getattr(self.todo, method)()
        self.assertEqual(pending, [], "answers unused")
        return out.getvalue()


# Réponses d'une installation acceptée telle que proposée : services, mode
# (développement), TLS, nom public, port TURN, plage des relais, port de
# ntfy.
DEFAULTS = ["", "", "", "", "", "", ""]


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

    def test_the_probe_never_echoes_a_host_config(self):
        text = "listening-port=3478\nstatic-auth-secret=Inventesecret123\n"
        host = FakeHost(
            coturn="coturn active /etc/turnserver.conf",
            files={"/etc/turnserver.conf": text},
            ports=(("udp", 3478, "turnserver"),),
        )
        out = self.drive("_call_infra_install", host, DEFAULTS + ["n"])
        self.assertNotIn(b64(text), out)
        self.assertNotIn("Inventesecret123", out)

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
        replies = ["2", "", "", "", "", "", "n"]
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

    def test_the_admin_added_to_an_adopted_ntfy_is_recorded(self):
        foreign = 'listen-http: ":8080"\nauth-default-access: "deny-all"\n'
        host = FakeHost(
            admin_password=ADMIN_PASSWORD,
            ntfy="ntfy active /etc/ntfy/server.yml",
            files={"/etc/ntfy/server.yml": foreign},
            ports=(("tcp", 22, "sshd"), ("tcp", 8080, "ntfy")),
        )
        self.drive("_call_infra_install", host, DEFAULTS + ["o", ""])
        self.assertIs(host.state["services"]["ntfy"]["admin_added"], True)

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
        replies = ["", "", "2", "/nonexistent/exemple.crt"]
        out = self.drive("_call_infra_install", host, replies)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("/nonexistent/exemple.crt", out)

    def test_a_port_that_is_not_a_number_stops(self):
        host = FakeHost()
        out = self.drive("_call_infra_install", host, ["", "", "", "", "abc"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("abc", out)

    def test_ssh_default_public_name_is_the_real_host(self):
        host = FakeHost()
        ssh = nm.SshHost("alias-exemple", hostname="turn.exemple.test")
        ssh.run = host.run
        self.drive("_call_infra_install", ssh, DEFAULTS + ["o", ""])
        settings = host.state["services"]["ntfy"]["settings"]
        self.assertEqual(settings["public_name"], "turn.exemple.test")


DOMAIN = "exemple.test"
NTFY_NAME, TURN_NAME = "ntfy.exemple.test", "turn.exemple.test"
EMAIL = "admin@exemple.test"
DNS_SECRET = "dns_cloudflare_api_token = Jeton-invente-0123456789\n"


def production_answers(**changes):
    values = dict(
        mode="production",
        public_name=DOMAIN,
        ntfy_name=NTFY_NAME,
        turn_name=TURN_NAME,
        tls="letsencrypt",
        acme="http-nginx",
        nginx="install",
        email=EMAIL,
    )
    values.update(changes)
    return answers(**values)


class ProductionCase(MenuCase):
    def setUp(self):
        super().setUp()
        self.dns = {NTFY_NAME: ["192.0.2.10"], TURN_NAME: ["192.0.2.10"]}

    def planned(self, host, replies):
        """(sortie, réponses passées à `plan_install`) ; None sans plan."""
        with mock.patch.object(
            ci, "plan_install", wraps=ci.plan_install
        ) as built:
            out = self.drive("_call_infra_install", host, replies)
        if not built.called:
            return out, None
        return out, built.call_args.args[1]


# Production, les deux services, Let's Encrypt par HTTP : services, mode,
# domaine, nom de ntfy, nom de TURN, certificat, défi, courriel, interface
# web de ntfy, port TURN, port TURNS, plage des relais, port de ntfy.
PROD_BOTH = ["", "2", DOMAIN, "", "", "", "", EMAIL, "", "", "", "", ""]
# coturn seul, Let's Encrypt par certbot seul sur 80 : services, mode,
# domaine, nom de TURN, certificat, défi, voie du défi HTTP, courriel, port
# TURN, 443 (question posée : ni nginx ni 443 pris), port TURNS, plage.
PROD_COTURN = ["2", "2", DOMAIN, "", "", "", "", EMAIL, "", "", "", ""]


class TestProductionInstall(ProductionCase):
    def test_lets_encrypt_through_an_installed_nginx(self):
        host = FakeHost()
        out = self.drive("_call_infra_install", host, PROD_BOTH + ["o", ""])
        self.assertEqual(host.kinds(), ["probe", "install", "state", "check"])
        script = host.script_of("install")
        self.assertIn(ci._installer_payload("nginx"), script)
        self.assertIn(ci._installer_payload("certbot"), script)
        self.assertEqual(host.state["mode"], "production")
        coturn = host.state["services"]["coturn"]["settings"]
        ntfy = host.state["services"]["ntfy"]["settings"]
        self.assertEqual(coturn["turn_name"], TURN_NAME)
        self.assertEqual(ntfy["ntfy_name"], NTFY_NAME)
        self.assertEqual(ntfy["acme"], "http-nginx")
        self.assertIs(ntfy["web"], False)
        self.assertIsNone(coturn["external_ip"])
        self.assertIs(host.state["nginx"]["installed_by_tool"], True)
        self.assertEqual(host.state["certbot"]["email"], EMAIL)
        # Le résumé : mode, noms, source du certificat, défi, règles.
        self.assertIn(f"{t('Mode:')} {t('production')}", out)
        self.assertIn(NTFY_NAME, out)
        self.assertIn(t("call_infra_cert_letsencrypt"), out)
        self.assertIn(t("call_infra_challenge_http_nginx"), out)
        self.assertIn(t("call_infra_nginx_install"), out)
        self.assertIn("80/tcp nginx", out)
        self.assertIn("443/tcp nginx", out)
        self.assertIn(t("call_infra_private_ranges_denied"), out)
        self.assertNotIn(t("call_infra_private_ranges_allowed"), out)
        self.assertNotIn(t("call_infra_email_none"), out)
        # La plage proposée est celle de la production, pas celle du
        # développement.
        self.assertTrue(
            any(
                f"[{ci.PROD_MIN_PORT}-{ci.PROD_MAX_PORT}]" in p
                for p in self.prompts
            )
        )
        # Les noms sont sur l'hôte : aucun avertissement DNS.
        self.assertNotIn(t("call_infra_dns_le_fails"), out)
        for name in (NTFY_NAME, TURN_NAME):
            self.assertNotIn(
                t("call_infra_dns_elsewhere").format(
                    name=name, found="192.0.2.10"
                ),
                out,
            )
        # En production, le domaine peut ne pas joindre l'hôte : la
        # vérification vise le nom de TURN.
        _remote, address, cafile = self.check_local.call_args.args
        self.assertEqual((address, cafile), (TURN_NAME, None))

    def test_http_challenge_offers_the_firewall_before_the_install(self):
        # Le défi HTTP-01 passe pendant le script d'installation : un
        # pare-feu actif qui ne laisse passer que ssh le ferait échouer à
        # chaque passage si le port 80 n'était proposé qu'après.
        for replies in (PROD_BOTH, PROD_COTURN):
            with self.subTest(replies=replies):
                host = FakeHost(firewall="ufw")
                out = self.drive(
                    "_call_infra_install", host, replies + ["o", "o", ""]
                )
                self.assertEqual(
                    host.kinds(),
                    ["probe", "firewall", "install", "state", "check"],
                )
                # Une seule question : le oui d'avant vaut pour l'état.
                rules = t("Add these rules? (y/N): ")
                asked = [p for p in self.prompts if p == rules]
                self.assertEqual(len(asked), 1, self.prompts)
                self.assertIn("80/tcp", out)
                self.assertEqual(
                    host.state["firewall"]["rules"],
                    [["tcp", "3478", "coturn"], ["udp", "3478", "coturn"]],
                )
                self.prompts.clear()

    def test_a_failed_http_challenge_after_the_firewall_keeps_no_state(self):
        host = FakeHost(firewall="ufw", install_ok=False)
        self.drive("_call_infra_install", host, PROD_BOTH + ["o", "o"])
        self.assertEqual(host.kinds(), ["probe", "firewall", "install"])
        self.assertIsNone(host.state)

    def test_dns_challenge_never_prints_the_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cloudflare.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(DNS_SECRET)
            replies = ["", "2", DOMAIN, "", "", "", "2", "1", path, ""]
            replies += ["", "", "", "", ""]
            host = FakeHost()
            out = self.drive("_call_infra_install", host, replies + ["o", ""])
        self.assertNotIn("Jeton-invente", out)
        self.assertNotIn(b64(DNS_SECRET), out)
        self.assertIn(b64(DNS_SECRET), host.script_of("install"))
        certbot = host.state["certbot"]
        self.assertEqual(certbot["plugin"], "cloudflare")
        self.assertEqual(
            certbot["dns_credentials"], f"{ci.DNS_DIR}/cloudflare.ini"
        )
        self.assertNotIn("Jeton-invente", json.dumps(host.state))
        # Debian n'empaquette que trois greffons : seuls ceux-là sont
        # offerts.
        self.assertIn("[1] cloudflare", out)
        self.assertIn("[3] rfc2136", out)
        self.assertNotIn("ovh", out)
        # Courriel vide : permis, et dit.
        self.assertIn(t("call_infra_email_none"), out)
        self.assertEqual(certbot["email"], "")

    def test_arch_offers_every_dns_plugin(self):
        host = FakeHost(os_line="arch -")
        replies = ["", "2", DOMAIN, "", "", "", "2", "99"]
        out = self.drive("_call_infra_install", host, replies)
        self.assertEqual(host.kinds(), ["probe"])
        for number, plugin in enumerate(ci.DNS_PLUGINS, 1):
            self.assertIn(f"[{number}] {plugin}", out)
        self.assertIn(t("Invalid selection!"), out)

    def test_an_unreadable_credentials_file_stops(self):
        host = FakeHost()
        replies = ["", "2", DOMAIN, "", "", "", "2", "1"]
        out = self.drive(
            "_call_infra_install", host, replies + ["/nonexistent/x.ini"]
        )
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn("/nonexistent/x.ini", out)

    def test_nat_proposes_the_public_ip_and_the_plan_carries_it(self):
        self.dns = {TURN_NAME: ["203.0.113.7"]}
        host = FakeHost()
        out = self.drive(
            "_call_infra_install", host, PROD_COTURN + ["", "o", ""]
        )
        self.assertEqual(host.kinds(), ["probe", "install", "state", "check"])
        self.assertIn(
            t("call_infra_turn_name_nat").format(
                name=TURN_NAME, address="203.0.113.7"
            ),
            out,
        )
        self.assertTrue(any("203.0.113.7" in p for p in self.prompts))
        coturn = host.state["services"]["coturn"]["settings"]
        self.assertEqual(coturn["external_ip"], "203.0.113.7")
        script = host.script_of("install")
        self.assertIn(ci._installer_payload("certbot"), script)
        self.assertNotIn(ci._installer_payload("nginx"), script)
        self.assertIn("80/tcp certbot", out)
        self.assertIn(t("call_infra_challenge_http_standalone"), out)
        # Le nom résout vers l'IP publique confirmée : pas d'avertissement.
        self.assertNotIn(t("call_infra_dns_le_fails"), out)

    def test_a_typed_public_ip_wins_and_a_name_elsewhere_is_warned(self):
        self.dns = {TURN_NAME: ["203.0.113.7"]}
        out, ans = self.planned(FakeHost(), PROD_COTURN + ["203.0.113.8", "n"])
        self.assertEqual(ans.external_ip, "203.0.113.8")
        self.assertIn(
            t("call_infra_dns_elsewhere").format(
                name=TURN_NAME, found="203.0.113.7"
            ),
            out,
        )
        self.assertIn(t("call_infra_dns_le_fails"), out)
        self.assertIn(t("Nothing installed."), out)

    def test_an_unresolved_turn_name_needs_a_typed_ip(self):
        self.dns = {}
        host = FakeHost()
        out, ans = self.planned(host, PROD_COTURN + [""])
        self.assertIsNone(ans)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_turn_name_unresolved").format(name=TURN_NAME), out
        )
        self.assertIn(t("call_infra_public_ip_required"), out)
        out, ans = self.planned(FakeHost(), PROD_COTURN + ["203.0.113.9", "n"])
        self.assertEqual(ans.external_ip, "203.0.113.9")
        self.assertIn(
            t("call_infra_dns_unresolved").format(name=TURN_NAME), out
        )

    def test_nginx_already_on_80_answers_the_challenge(self):
        host = FakeHost(
            probe_extra=["@@NGINX active debian"],
            ports=(("tcp", 22, "sshd"), ("tcp", 80, "nginx")),
        )
        # Ni la voie du défi HTTP ni 443 ne sont demandés : nginx sert.
        replies = ["2", "2", DOMAIN, "", "", "", EMAIL, "", "", "", "n"]
        out, ans = self.planned(host, replies)
        self.assertEqual((ans.acme, ans.nginx), ("http-nginx", "existing"))
        self.assertIs(ans.turns_443, False)
        self.assertIn(t("call_infra_nginx_serves_challenge"), out)
        self.assertIn(
            t("call_infra_nginx_existing").format(layout="debian"), out
        )

    def test_nginx_installed_for_the_challenge_on_a_coturn_host(self):
        replies = ["2", "2", DOMAIN, "", "", "", "2", EMAIL, "", "", "", "n"]
        out, ans = self.planned(FakeHost(), replies)
        self.assertEqual((ans.acme, ans.nginx), ("http-nginx", "install"))
        self.assertIn(t("call_infra_nginx_install"), out)

    def test_443_is_asked_without_nginx_when_it_is_free(self):
        replies = list(PROD_COTURN)
        replies[9:11] = ["o"]
        out, ans = self.planned(FakeHost(), replies + ["n"])
        self.assertIs(ans.turns_443, True)
        self.assertTrue(
            any(
                t("call_infra_ask_turns_443").format(port=5349) in p
                for p in self.prompts
            )
        )
        self.assertIn("443/tcp coturn", out)

    def test_443_held_by_another_process_is_not_asked(self):
        host = FakeHost(ports=(("tcp", 22, "sshd"), ("tcp", 443, "caddy")))
        replies = list(PROD_COTURN)
        del replies[9]
        _out, ans = self.planned(host, replies + ["n"])
        self.assertIs(ans.turns_443, False)
        self.assertFalse(
            any(
                t("call_infra_ask_turns_443").format(port=5349) in p
                for p in self.prompts
            )
        )

    def test_ntfy_alone_behind_nat_says_the_name_cannot_be_checked(self):
        # Sans coturn, aucune IP publique n'est demandée : un nom qui
        # pointe hors de l'hôte peut être son NAT, rien ne dit qu'il faut
        # corriger le DNS.
        self.dns = {NTFY_NAME: ["203.0.113.7"]}
        replies = ["3", "2", DOMAIN, "", "", "", EMAIL, "", ""]
        out, ans = self.planned(FakeHost(), replies + ["n"])
        self.assertEqual(ans.services, frozenset({"ntfy"}))
        self.assertIn(
            t("call_infra_dns_unverifiable").format(
                name=NTFY_NAME, found="203.0.113.7"
            ),
            out,
        )
        self.assertNotIn(
            t("call_infra_dns_elsewhere").format(
                name=NTFY_NAME, found="203.0.113.7"
            ),
            out,
        )
        self.assertNotIn(t("call_infra_dns_le_fails"), out)

    def test_443_held_by_coturn_itself_is_asked_again(self):
        # Relance d'un coturn déjà sur 443 : la question revient, oui par
        # défaut, et coturn ne repart pas en silence sur 5349.
        replies = list(PROD_COTURN)
        replies[9:11] = ["o"]
        host = FakeHost()
        self.drive("_call_infra_install", host, replies + ["o", ""])
        host.ports = (("tcp", 22, "sshd"), ("tcp", 443, "turnserver"))
        self.prompts = []
        again = [""] * 11
        _out, ans = self.planned(host, again + ["n"])
        self.assertIs(ans.turns_443, True)
        self.assertTrue(
            any(
                t("call_infra_ask_turns_443").format(port=5349) in p
                for p in self.prompts
            )
        )

    def test_443_is_not_asked_when_nginx_is_present_but_unused(self):
        # nginx est là sans servir ce plan (défi DNS, coturn seul) : 443
        # reste à lui.
        host = FakeHost(probe_extra=["@@NGINX active debian"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cloudflare.ini")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(DNS_SECRET)
            replies = ["2", "2", DOMAIN, "", "", "2", "1", path, ""]
            replies += ["", "", ""]
            _out, ans = self.planned(host, replies + ["n"])
        self.assertIsNone(ans.nginx)
        self.assertIs(ans.turns_443, False)
        self.assertFalse(
            any(
                t("call_infra_ask_turns_443").format(port=5349) in p
                for p in self.prompts
            )
        )

    def test_ubuntu_and_installed_plugins_are_offered(self):
        host = FakeHost(os_line="ubuntu 24.04")
        replies = ["", "2", DOMAIN, "", "", "", "2", "99"]
        out = self.drive("_call_infra_install", host, replies)
        self.assertIn("[6] ovh", out)
        self.assertNotIn("] luadns", out)
        self.assertNotIn("] nsone", out)
        # Un greffon déjà installé est offert même sans paquet Debian.
        host = FakeHost(
            probe_extra=["@@CERTBOT 4.0.0", "@@CERTBOT_PLUGIN ovh"]
        )
        out = self.drive("_call_infra_install", host, replies)
        self.assertIn("[3] ovh", out)
        self.assertNotIn("] luadns", out)

    def test_a_domain_that_is_an_address_is_refused(self):
        for typed in ("192.0.2.10", "2001:db8::1", "hote-exemple"):
            with self.subTest(typed=typed):
                host = FakeHost()
                out = self.drive("_call_infra_install", host, ["", "2", typed])
                self.assertEqual(host.kinds(), ["probe"])
                self.assertIn(t("call_infra_domain_needed"), out)

    def test_an_address_is_never_proposed_as_the_domain(self):
        # Sans ssh ni état, le nom proposé est l'adresse de l'hôte : rien
        # n'est proposé, et une réponse vide est refusée.
        host = FakeHost()
        out = self.drive("_call_infra_install", host, ["", "2", ""])
        self.assertNotIn("[192.0.2.10]", self.prompts[2])
        self.assertIn(t("call_infra_domain_needed"), out)

    def test_the_ssh_host_name_is_proposed_as_the_domain(self):
        host = FakeHost()
        ssh = nm.SshHost("alias-exemple", hostname="vps.exemple.test")
        ssh.run = host.run
        self.drive("_call_infra_install", ssh, ["", "2", "", "", "", "9"])
        self.assertIn("[vps.exemple.test]", self.prompts[2])
        self.assertIn("[ntfy.vps.exemple.test]", self.prompts[3])

    def test_names_are_proposed_from_the_domain_and_editable(self):
        replies = list(PROD_BOTH)
        replies[3] = "push.exemple.test"
        _out, ans = self.planned(FakeHost(), replies + ["n"])
        self.assertEqual(ans.ntfy_name, "push.exemple.test")
        self.assertEqual(ans.turn_name, TURN_NAME)
        self.assertEqual(ans.public_name, DOMAIN)
        self.assertTrue(any(f"[{NTFY_NAME}]" in p for p in self.prompts))

    def test_a_rerun_is_prefilled_from_the_production_state(self):
        host = FakeHost()
        self.drive("_call_infra_install", host, PROD_BOTH + ["o", ""])
        self.prompts = []
        replies = [""] * 13
        out, ans = self.planned(host, replies + ["n"])
        self.assertEqual(ans.mode, "production")
        self.assertEqual(
            (ans.public_name, ans.ntfy_name, ans.turn_name),
            (DOMAIN, NTFY_NAME, TURN_NAME),
        )
        self.assertEqual((ans.tls, ans.acme), ("letsencrypt", "http-nginx"))
        self.assertEqual(ans.email, EMAIL)
        self.assertEqual(
            (ans.min_port, ans.max_port), (ci.PROD_MIN_PORT, ci.PROD_MAX_PORT)
        )

    def test_a_dash_clears_the_recorded_email(self):
        host = FakeHost()
        self.drive("_call_infra_install", host, PROD_BOTH + ["o", ""])
        replies = [""] * 13
        replies[7] = "-"
        out, ans = self.planned(host, replies + ["n"])
        self.assertEqual(ans.email, "")
        self.assertIn(t("call_infra_email_none"), out)

    def test_the_development_branch_carries_no_production_answer(self):
        host = FakeHost()
        self.drive("_call_infra_install", host, PROD_BOTH + ["o", ""])
        replies = ["", "1", "", "192.0.2.10", "", "", "", "n"]
        out, ans = self.planned(host, replies)
        self.assertEqual(ans.mode, "development")
        self.assertEqual(
            ans, answers(public_name="192.0.2.10", ntfy_port=8080)
        )
        self.assertIn(f"{t('Mode:')} {t('development')}", out)

    def test_development_after_production_drops_the_nat_address(self):
        # L'adresse publique d'un hôte derrière un NAT n'a pas de sens pour
        # un coturn de réseau local, et le domaine peut ne pas joindre
        # l'hôte : le nom proposé est celui de TURN.
        self.dns = {TURN_NAME: ["203.0.113.7"]}
        host = FakeHost()
        self.drive("_call_infra_install", host, PROD_COTURN + ["", "o", ""])
        self.assertEqual(
            host.state["services"]["coturn"]["settings"]["external_ip"],
            "203.0.113.7",
        )
        self.prompts = []
        replies = ["", "1", "", "", "", "", "n"]
        _out, ans = self.planned(host, replies)
        self.assertEqual(ans.mode, "development")
        self.assertIsNone(ans.external_ip)
        self.assertEqual(ans.public_name, TURN_NAME)
        self.assertTrue(any(f"[{TURN_NAME}]" in p for p in self.prompts))


class TestProductionScreens(ProductionCase):
    def test_new_check_lines_have_labels(self):
        for name, key, label in (
            (
                "private-denied",
                "call_infra_check_private_denied",
                "Private ranges denied",
            ),
            (
                "cert-issuer",
                "call_infra_check_cert_issuer",
                "Certificate issuer",
            ),
            ("renewal", "call_infra_check_renewal_ok", "Certificate renewal"),
        ):
            with self.subTest(name=name):
                line = ci.CheckLine(
                    name,
                    True,
                    key,
                    {"peer": "10.0.0.1", "issuer": "x", "label": "x"},
                )
                self.assertTrue(
                    self.todo._call_infra_line(line).startswith(
                        f"✓ {t(label)} : "
                    )
                )

    def test_the_check_of_a_ntfy_host_aims_at_the_ntfy_name(self):
        state = installed_state(
            production_answers(services=frozenset({"ntfy"}))
        )
        host = FakeHost(state=state)
        self.drive("_call_infra_check", host, [""])
        _remote, address, _cafile = self.check_local.call_args.args
        self.assertEqual(address, NTFY_NAME)

    def test_uninstall_lists_nginx_and_the_certificate(self):
        host = FakeHost(state=installed_state(production_answers()))
        out = self.drive("_call_infra_uninstall", host, ["n", "n"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(t("call_infra_uninstall_nginx_purges"), out)
        self.assertIn(t("call_infra_uninstall_certificate"), out)
        self.assertIn(t("call_infra_uninstall_hook"), out)


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

    def test_coturn_secrets_and_user_keys_stay_off_screen(self):
        secret = "SecretInventePourEcran_0123456789abcdefg"
        hexkey = "e" * 32
        host = FakeHost(
            state=installed_state(),
            check_extra=[
                f"@@TURN_SECRET turn.exemple.test {secret}",
                f"@@TURN_USER turn.exemple.test erplibre-0a1b2c3d {hexkey}",
            ],
        )
        out = self.drive("_call_infra_check", host, [""])
        self.assertNotIn(secret, out)
        self.assertNotIn(hexkey, out)
        self.assertIn("@@TURN_SECRET ***", out)
        self.assertIn("@@TURN_USER ***", out)
        remote = self.check_local.call_args[0][0]
        self.assertEqual(
            remote["turn_secrets"], [("turn.exemple.test", secret)]
        )

    def supplied_host(self):
        state = installed_state()
        for record in state["services"].values():
            record["settings"]["tls"] = "supplied"
        return FakeHost(state=state)

    def test_supplied_tls_asks_for_the_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            ca = os.path.join(tmp, "ca.crt")
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "ec",
                    "-pkeyopt",
                    "ec_paramgen_curve:prime256v1",
                    "-nodes",
                    "-keyout",
                    os.path.join(tmp, "ca.key"),
                    "-out",
                    ca,
                    "-days",
                    "2",
                    "-subj",
                    "/CN=ca.exemple.test",
                ],
                check=True,
                capture_output=True,
            )
            self.drive(
                "_call_infra_check",
                self.supplied_host(),
                ["turn.exemple.test", ca],
            )
        _remote, address, cafile = self.check_local.call_args.args
        self.assertEqual(address, "turn.exemple.test")
        self.assertEqual(cafile, ca)

    def test_an_authority_that_does_not_load_stops_the_check(self):
        # Sans ce contrôle, un chemin mal tapé se lit « relais injoignable ».
        with tempfile.TemporaryDirectory() as tmp:
            garbage = os.path.join(tmp, "pas-un-pem.crt")
            with open(garbage, "w") as handle:
                handle.write("pas un certificat\n")
            for path in ("/nonexistent/exemple-ca.crt", garbage):
                with self.subTest(path=path):
                    out = self.drive(
                        "_call_infra_check",
                        self.supplied_host(),
                        ["turn.exemple.test", path],
                    )
                    self.check_local.assert_not_called()
                    self.assertIn(path, out)
                    self.assertIn(t("The file could not be read:"), out)

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

    def test_a_malformed_state_is_refused_without_a_traceback(self):
        state = installed_state()
        state["services"]["ntfy"]["tls_files"] = [["x"]]
        host = FakeHost(state=state)
        out = self.drive("_call_infra_uninstall", host, [])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_state_invalid").format(service="ntfy"), out
        )

    def test_a_state_of_another_version_is_refused(self):
        state = installed_state()
        state["version"] = 99
        host = FakeHost(state=state)
        out = self.drive("_call_infra_uninstall", host, [])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            t("call_infra_state_version").format(found=99, expected="1, 2"),
            out,
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


# --- Serveurs Odoo ------------------------------------------------------------

ODOO_URL = "https://odoo.exemple.test"
ODOO_DB = "base_exemple"
ODOO_KEY = ol.odoo_key(ODOO_URL, ODOO_DB)
OWNED = ol.owned_username(ODOO_URL, ODOO_DB)
OTHER_KEY = ol.odoo_key("https://autre.exemple.test", "autre_base")
ODOO_PASSWORD = "Mot-de-passe-Odoo-invente-77"
USER_PASSWORD = "Mot-de-passe-utilisateur-invente-31"
ODOO_ADDRESS = "198.51.100.20"
# Réponses jusqu'aux faits de la base, par l'API web : méthode (1),
# URL, base, identifiant (admin proposé), mot de passe (sans écho).
ADD_WEB = ["", ODOO_URL, ODOO_DB, "", ODOO_PASSWORD]
# Débrancher une base par l'API web : méthode consignée, identifiant, mot
# de passe.
REMOVE_ONE = ["", "", ODOO_PASSWORD]
# « Retirer » : choix de la base (1), oui au résumé, puis REMOVE_ONE.
REMOVE_WEB = ["", "o"] + REMOVE_ONE


def odoo_facts(module_state="installed", rows=(), params=None, version="18.0"):
    return ol.OdooFacts(
        version=version,
        major=ol.major_of(version),
        module_state=module_state,
        params=dict(params or {}),
        rows=tuple(rows),
        host_name="odoo.exemple.test",
    )


class FakeLink(ol.WebApi):
    """Lien vers Odoo doublure : rend des faits préparés et garde chaque
    appel. Il dérive de WebApi pour que l'état consigne « webapi », sans
    jamais en appeler le constructeur ni le réseau."""

    def __init__(self, facts=None, fail=(), error=None):
        self._facts = facts or odoo_facts()
        self.fail = set(fail)
        self.error = error or ol.OdooError(
            "call_infra_odoo_unreachable",
            url=ODOO_URL,
            reason="connexion refusée",
        )
        self.calls = []

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.error

    def facts(self):
        self._record("facts")
        return self._facts

    def install_module(self):
        self._record("install_module")

    def set_params(self, values):
        self._record("set_params", dict(values))

    def replace_rows(self, owned, rows):
        self._record("replace_rows", owned, [dict(r) for r in rows])

    def whoami(self):
        return "admin"

    def names(self):
        return [call[0] for call in self.calls]


def plugged_state(kind="secret", keys=(ODOO_KEY,), method="webapi", **how):
    """Un état d'installation où `keys` sont branchés sur coturn."""
    state = installed_state(how.pop("ans", None))
    state["turn_mode"] = "secret" if kind == "secret" else "fixed"
    if kind == "secret":
        state["check_secret_sha256"] = "c" * 64
    state["odoos"] = {}
    for key in keys:
        url, _, database = key.rpartition("|")
        credential = (
            {"kind": "secret", "value_sha256": "a" * 64}
            if kind == "secret"
            else {"kind": "user", "user": ol.owned_username(url, database)}
        )
        state["odoos"][key] = {
            "method": method,
            "module": kind == "secret",
            "credential": credential,
            "retired": [],
            "rows": kind != "secret",
            "exempt": how.get("exempt"),
            "added_at": "2026-10-31T10:00:00+00:00",
        }
    return state


def odoo_line(key=ODOO_KEY, n=1):
    return ci.CheckLine(
        f"odoo-{n}",
        True,
        "call_infra_check_odoo_relayed",
        {"odoo": key, "relayed": "192.0.2.10:50000"},
    )


class OdooCase(MenuCase):
    def setUp(self):
        super().setUp()
        self.dns = {"odoo.exemple.test": [ODOO_ADDRESS]}
        self.link = FakeLink()

    def text(self, key, **values):
        return t(key).format(**values)


class TestAddOdoo(OdooCase):
    def test_add_with_the_module_installed(self):
        host = FakeHost(state=installed_state())
        out = self.drive(
            "_call_infra_add_odoo",
            host,
            ADD_WEB + ["", "o"],
            lines=[odoo_line(OTHER_KEY, 1), odoo_line(ODOO_KEY, 2)],
        )
        self.assertEqual(host.kinds(), ["probe", "odoo-add", "state", "check"])
        self.assertEqual(
            self.made,
            [
                (
                    "webapi",
                    ODOO_URL,
                    ODOO_DB,
                    {"login": "admin", "secret": ODOO_PASSWORD},
                )
            ],
        )
        # Le script de l'hôte d'abord, puis Odoo : les paramètres en
        # dernier, le secret à la fin.
        self.assertEqual(
            self.link.names(), ["facts", "replace_rows", "set_params"]
        )
        self.assertEqual(self.link.calls[1][1:], (OWNED, []))
        params = self.link.calls[2][1]
        self.assertEqual(list(params), [ol.PARAM_URLS, ol.PARAM_SECRET])
        self.assertIn(t("call_infra_odoo_kind_secret"), out)
        self.assertIn(
            "identifiants temporaires",
            TRANSLATIONS["call_infra_odoo_kind_secret"]["fr"],
        )
        self.assertIn("turn:192.0.2.10:3478?transport=udp", out)
        entry = host.state["odoos"][ODOO_KEY]
        self.assertEqual(entry["credential"]["kind"], "secret")
        self.assertEqual(entry["method"], "webapi")
        self.assertEqual(entry["exempt"], ODOO_ADDRESS)
        self.assertEqual(host.state["turn_mode"], "secret")
        self.assertIn(self.text("call_infra_odoo_added", odoo=ODOO_KEY), out)
        # Seule la ligne de cette base est montrée après l'ajout.
        check_line = re.compile(rf"^. {re.escape(t('Odoo server'))} \d+ : ")
        shown = [line for line in out.splitlines() if check_line.match(line)]
        self.assertEqual(len(shown), 1)
        self.assertTrue(shown[0].startswith(f"✓ {t('Odoo server')} 2 : "))
        self.assertEqual(
            self.check_local.call_args.args[1:], ("192.0.2.10", None)
        )

    def test_passwords_and_the_drawn_secret_never_reach_the_screen(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "o"])
        secret = self.link.calls[-1][1][ol.PARAM_SECRET]
        self.assertTrue(secret)
        for hidden in (ODOO_PASSWORD, secret):
            self.assertNotIn(hidden, out)
            self.assertFalse(any(hidden in p for p in self.prompts))
        self.assertNotIn(secret, json.dumps(host.state))
        # Le mot de passe se demande sans écho.
        self.assertIn(t("call_infra_ask_odoo_password"), self.prompts[4])

    def test_an_installable_module_is_offered_and_installed_first(self):
        self.link = FakeLink(odoo_facts("uninstalled"))
        host = FakeHost(state=installed_state())
        self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "", "o"])
        self.assertIn(t("call_infra_ask_install_module"), self.prompts[5])
        self.assertEqual(
            self.link.names(),
            ["facts", "install_module", "replace_rows", "set_params"],
        )
        self.assertEqual(host.state["turn_mode"], "secret")

    def test_a_declined_install_gives_a_fixed_account(self):
        self.link = FakeLink(odoo_facts("uninstalled"))
        host = FakeHost(state=installed_state())
        out = self.drive(
            "_call_infra_add_odoo", host, ADD_WEB + ["n", "", "o"]
        )
        self.assertNotIn("install_module", self.link.names())
        self.assertIn(t("call_infra_odoo_kind_user"), out)
        self.assertIn(t("call_infra_no_turns"), out)
        self.assertEqual(
            host.state["odoos"][ODOO_KEY]["credential"]["kind"], "user"
        )

    def test_the_install_defaults_to_no_on_a_fixed_coturn_in_use(self):
        # Installer le module serait refusé : la réponse par défaut garde
        # le compte fixe que ce coturn accepte.
        self.link = FakeLink(odoo_facts("uninstalled"))
        host = FakeHost(state=plugged_state("user", (OTHER_KEY,)))
        self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "", "o"])
        self.assertIn(t("call_infra_hint_no"), self.prompts[len(ADD_WEB)])
        self.assertNotIn("install_module", self.link.names())
        self.assertEqual(
            host.state["odoos"][ODOO_KEY]["credential"]["kind"], "user"
        )

    def test_a_rerun_summary_says_the_credential_changes(self):
        cases = (
            (
                "secret",
                odoo_facts("installed"),
                "call_infra_odoo_rotates_secret",
            ),
            ("user", odoo_facts("absent"), "call_infra_odoo_rotates_user"),
        )
        for kind, facts, key in cases:
            with self.subTest(kind=kind):
                self.link = FakeLink(facts)
                host = FakeHost(state=plugged_state(kind))
                answers = ["o"] if kind == "user" else []
                out = self.drive(
                    "_call_infra_add_odoo", host, ADD_WEB + answers + ["", "n"]
                )
                self.assertIn(self.text(key, hours=24), out)

    def test_a_first_add_summary_says_no_rotation(self):
        self.link = FakeLink(odoo_facts("installed"))
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "n"])
        self.assertNotIn(
            self.text("call_infra_odoo_rotates_secret", hours=24), out
        )

    def test_plain_http_to_another_machine_asks_first(self):
        url = "http://odoo.exemple.test:8069"
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ["", url, ODOO_DB, ""])
        self.assertIn(self.text("call_infra_odoo_http_clear", url=url), out)
        self.assertIn(t("call_infra_ask_http_anyway"), self.prompts[-1])
        self.assertEqual(self.made, [])
        self.assertEqual(host.kinds(), ["probe"])

    def test_plain_http_on_this_machine_asks_nothing_more(self):
        url = "http://127.0.0.1:8069"
        host = FakeHost(state=installed_state())
        self.drive(
            "_call_infra_add_odoo",
            host,
            ["", url, ODOO_DB, "", ODOO_PASSWORD, "", "n"],
        )
        self.assertEqual(self.made[0][1], url)
        for prompt in self.prompts:
            self.assertNotIn(t("call_infra_ask_http_anyway"), prompt)

    def test_module_absent_explains_then_asks_the_fallback(self):
        self.link = FakeLink(odoo_facts("absent"))
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + [""])
        self.assertIn(t("call_infra_module_absent"), out)
        self.assertIn(t("call_infra_ask_fixed_fallback"), self.prompts[-1])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertEqual(self.link.names(), ["facts"])
        self.assertIn(t("Nothing added."), out)

    def test_the_fixed_fallback_writes_three_owned_rows(self):
        self.link = FakeLink(odoo_facts("absent"))
        host = FakeHost(state=installed_state())
        out = self.drive(
            "_call_infra_add_odoo", host, ADD_WEB + ["o", "", "o"]
        )
        self.assertEqual(host.kinds(), ["probe", "odoo-add", "state", "check"])
        self.assertEqual(self.link.names(), ["facts", "replace_rows"])
        owned, rows = self.link.calls[1][1:]
        self.assertEqual(owned, OWNED)
        self.assertEqual(
            [(r["server_type"], r["username"]) for r in rows],
            [("stun", OWNED), ("turn", OWNED), ("turn", OWNED)],
        )
        self.assertNotIn("credential", rows[0])
        password = rows[1]["credential"]
        self.assertNotIn(password, out)
        self.assertIn(t("call_infra_no_turns"), out)
        # L'explication ne se répète pas dans le résumé.
        self.assertEqual(out.count(t("call_infra_module_absent")), 1)
        self.assertEqual(host.state["turn_mode"], "fixed")

    def test_mixing_modes_is_refused_with_its_reason(self):
        # Un coturn en mode secret qui sert déjà un Odoo : un Odoo sans
        # module ne se voit pas offrir le compte fixe.
        self.link = FakeLink(odoo_facts("absent"))
        host = FakeHost(state=plugged_state("secret", (OTHER_KEY,)))
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB)
        self.assertIn(t("call_infra_module_absent"), out)
        self.assertIn(
            self.text(
                "call_infra_turn_mode_mismatch", mode="secret", odoos=OTHER_KEY
            ),
            out,
        )
        self.assertEqual(host.kinds(), ["probe"])

    def test_a_module_odoo_on_a_fixed_coturn_is_refused(self):
        host = FakeHost(state=plugged_state("user", (OTHER_KEY,)))
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB)
        self.assertIn(
            self.text(
                "call_infra_turn_mode_mismatch", mode="fixed", odoos=OTHER_KEY
            ),
            out,
        )
        self.assertEqual(host.kinds(), ["probe"])
        self.assertEqual(self.link.names(), ["facts"])

    def test_no_coturn_is_refused_before_any_question(self):
        state = installed_state(answers(services=frozenset({"ntfy"})))
        host = FakeHost(state=state)
        out = self.drive("_call_infra_add_odoo", host, [])
        self.assertIn(t("call_infra_odoo_no_coturn"), out)
        self.assertEqual(host.kinds(), ["probe"])

    def test_an_odoo_17_is_refused_with_its_version(self):
        self.link = FakeLink(
            fail={"facts"},
            error=ol.OdooError("call_infra_odoo_version", version="17.0"),
        )
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB)
        self.assertIn(
            self.text("call_infra_odoo_version", version="17.0"), out
        )
        self.assertEqual(host.kinds(), ["probe"])

    def test_existing_rows_are_listed_without_credential(self):
        rows = (
            {
                "id": 7,
                "server_type": "turn",
                "uri": "turn.exemple.test:3478",
                "username": "alice",
            },
            {
                "id": 8,
                "server_type": "stun",
                "uri": "stun.exemple.test",
                "username": "",
            },
        )
        self.link = FakeLink(odoo_facts(rows=rows))
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "n"])
        self.assertIn("turn:turn.exemple.test:3478 (alice)", out)
        self.assertIn("stun:stun.exemple.test", out)

    def test_declined_writes_nothing(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", ""])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertEqual(self.link.names(), ["facts"])
        self.assertIn(t("Nothing added."), out)

    def test_a_loopback_url_proposes_no_exempt_address(self):
        self.dns = {"odoo.exemple.test": ["127.0.0.1"]}
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "o"])
        self.assertIn(
            self.text("call_infra_odoo_exempt_local", address="127.0.0.1"), out
        )
        self.assertIsNone(host.state["odoos"][ODOO_KEY]["exempt"])

    def test_a_typed_exempt_address_wins_and_a_dash_gives_none(self):
        for typed, expected in (("203.0.113.7", "203.0.113.7"), ("-", None)):
            with self.subTest(typed=typed):
                self.link = FakeLink()
                host = FakeHost(state=installed_state())
                self.drive(
                    "_call_infra_add_odoo", host, ADD_WEB + [typed, "o"]
                )
                self.assertEqual(
                    host.state["odoos"][ODOO_KEY]["exempt"], expected
                )

    def test_a_loopback_typed_as_exempt_is_refused(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["127.0.0.1"])
        self.assertIn(
            self.text("call_infra_odoo_exempt", address="127.0.0.1"), out
        )
        self.assertEqual(host.kinds(), ["probe"])

    def test_without_ntfy_on_the_host_no_exempt_is_asked(self):
        state = installed_state(answers(services=frozenset({"coturn"})))
        host = FakeHost(state=state)
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["o"])
        self.assertIn(t("call_infra_odoo_exempt_no_ntfy"), out)
        self.assertIsNone(host.state["odoos"][ODOO_KEY]["exempt"])

    def test_a_failed_odoo_write_rolls_coturn_back(self):
        self.link = FakeLink(
            fail={"set_params"},
            error=ol.OdooError(
                "call_infra_odoo_rpc_error", message="AccessError inventée"
            ),
        )
        # Un coturn déjà en mode secret : l'ajout ne bascule rien, l'état
        # de l'hôte reste octet pour octet celui d'avant.
        host = FakeHost(state=plugged_state("secret", (OTHER_KEY,)))
        before = json.loads(json.dumps(host.state))
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "o"])
        self.assertEqual(host.kinds(), ["probe", "odoo-add", "odoo-rollback"])
        self.assertIn(t("call_infra_odoo_write_failed"), out)
        self.assertIn("AccessError inventée", out)
        self.assertEqual(host.state, before)

    def test_a_failed_host_script_writes_nothing_in_odoo(self):
        host = FakeHost(state=installed_state(), odoo_add_ok=False)
        out = self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "o"])
        self.assertIn(
            self.text("call_infra_odoo_host_failed", step="coturn"), out
        )
        self.assertEqual(self.link.names(), ["facts"])
        self.assertEqual(host.kinds(), ["probe", "odoo-add"])

    def test_every_script_runs_as_root(self):
        host = FakeHost(state=installed_state())
        self.drive("_call_infra_add_odoo", host, ADD_WEB + ["", "o"])
        self.assertEqual({user for _, user in host.calls}, {None})


class TestRemoveOdoo(OdooCase):
    def test_remove_cleans_odoo_then_revokes_on_coturn(self):
        host = FakeHost(state=plugged_state())
        out = self.drive("_call_infra_remove_odoo", host, REMOVE_WEB)
        self.assertEqual(host.kinds(), ["probe", "odoo-remove"])
        self.assertEqual(
            self.link.calls,
            [
                ("set_params", {ol.PARAM_SECRET: None, ol.PARAM_URLS: None}),
                ("replace_rows", OWNED, []),
            ],
        )
        self.assertEqual(host.state["odoos"], {})
        self.assertIn(self.text("call_infra_odoo_removed", odoo=ODOO_KEY), out)
        self.assertNotIn(ODOO_PASSWORD, out)
        self.assertEqual(self.made[0][:3], ("webapi", ODOO_URL, ODOO_DB))

    def test_the_list_names_each_odoo_and_its_method(self):
        host = FakeHost(state=plugged_state(keys=(ODOO_KEY, OTHER_KEY)))
        out = self.drive(
            "_call_infra_remove_odoo", host, ["2", "o"] + REMOVE_ONE
        )
        listed = sorted([ODOO_KEY, OTHER_KEY])
        for n, key in enumerate(listed, 1):
            self.assertIn(
                f"[{n}] {key} ({t('call_infra_odoo_method_webapi')})", out
            )
        self.assertEqual(list(host.state["odoos"]), [listed[0]])
        url, _, database = listed[1].rpartition("|")
        self.assertEqual(self.made[0][1:3], (url, database))

    def test_the_summary_comes_before_any_question_on_the_link(self):
        host = FakeHost(state=plugged_state(exempt="198.51.100.20"))
        before = json.loads(json.dumps(host.state))
        out = self.drive("_call_infra_remove_odoo", host, ["", ""])
        self.assertIn(t("call_infra_remove_revokes_secret"), out)
        self.assertIn(
            self.text(
                "call_infra_remove_drops_exempt", exempt="198.51.100.20"
            ),
            out,
        )
        self.assertIn(
            t("Remove this Odoo server now? (y/N): "), self.prompts[1]
        )
        self.assertIn(t("Nothing removed."), out)
        self.assertEqual(host.kinds(), ["probe"])
        self.assertEqual(self.made, [])
        self.assertEqual(host.state, before)

    def test_the_summary_of_a_fixed_account(self):
        host = FakeHost(state=plugged_state("user"))
        out = self.drive("_call_infra_remove_odoo", host, ["", "n"])
        self.assertIn(
            self.text("call_infra_remove_deletes_user", user=OWNED), out
        )
        self.assertEqual(host.kinds(), ["probe"])

    def test_an_unreachable_odoo_asks_before_revoking_anyway(self):
        self.link = FakeLink(fail={"set_params"})
        host = FakeHost(state=plugged_state())
        out = self.drive("_call_infra_remove_odoo", host, REMOVE_WEB + ["o"])
        self.assertIn(t("call_infra_odoo_remove_unreachable"), out)
        self.assertIn("connexion refusée", out)
        self.assertIn(t("call_infra_ask_revoke_anyway"), self.prompts[-1])
        self.assertEqual(host.kinds(), ["probe", "odoo-remove"])
        self.assertEqual(host.state["odoos"], {})

    def test_declining_the_revocation_changes_nothing(self):
        self.link = FakeLink(fail={"set_params"})
        state = plugged_state()
        host = FakeHost(state=state)
        out = self.drive("_call_infra_remove_odoo", host, REMOVE_WEB + [""])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(ODOO_KEY, host.state["odoos"])
        self.assertIn(t("Nothing revoked."), out)

    def test_no_odoo_plugged_says_so(self):
        host = FakeHost(state=installed_state())
        out = self.drive("_call_infra_remove_odoo", host, [])
        self.assertIn(t("call_infra_no_odoo"), out)
        self.assertEqual(host.kinds(), ["probe"])

    def test_a_failed_remove_script_is_shown(self):
        host = FakeHost(state=plugged_state(), odoo_remove_ok=False)
        out = self.drive("_call_infra_remove_odoo", host, REMOVE_WEB)
        self.assertIn(
            self.text("call_infra_odoo_host_failed", step="coturn"), out
        )
        self.assertIn(ODOO_KEY, host.state["odoos"])


class TestCheckOdoo(OdooCase):
    ICE = [
        {
            "urls": "turn:192.0.2.10:3478?transport=udp",
            "username": "1893542400:odoo-u6",
            "credential": "Identifiant-invente-remis-par-odoo",
        }
    ]

    def ice_lines(self):
        return [
            ci.CheckLine(
                "odoo-ice-turn:192.0.2.10:3478?transport=udp",
                True,
                "call_infra_check_ice_relayed",
                {
                    "url": "turn:192.0.2.10:3478?transport=udp",
                    "relayed": "192.0.2.10:50001",
                },
            )
        ]

    def test_check_through_odoo_after_the_report(self):
        host = FakeHost(state=plugged_state())
        through = mock.Mock(return_value=self.ice_lines())
        with (
            mock.patch.object(
                ol.WebApi, "join_call_ice", return_value=self.ICE
            ) as join,
            mock.patch.object(ci, "check_through_odoo", through),
        ):
            out = self.drive(
                "_call_infra_check",
                host,
                ["", "o", "", "utilisateur", USER_PASSWORD],
            )
        self.assertEqual(host.kinds(), ["check"])
        join.assert_called_once_with("utilisateur", USER_PASSWORD)
        ice, realm, address, cafile = through.call_args.args
        self.assertEqual(
            (ice, realm, address, cafile),
            (self.ICE, "192.0.2.10", "192.0.2.10", None),
        )
        self.assertEqual(through.call_args.kwargs["turn_host"], "192.0.2.10")
        self.assertIn(t("call_infra_check_odoo_notice"), out)
        self.assertIn(f"✓ {t('ICE handed out by Odoo')} : ", out)
        self.assertNotIn(USER_PASSWORD, out)
        self.assertNotIn(self.ICE[0]["credential"], out)
        # La notice vient avant la question, qui vient après le rapport.
        self.assertIn(t("call_infra_ask_check_odoo"), self.prompts[1])
        # Le mot de passe de l'utilisateur se tape sans écho.
        self.assertEqual(
            self.hidden, [f"{t('call_infra_ask_odoo_user_password')}: "]
        )

    def test_declined_joins_nothing(self):
        host = FakeHost(state=plugged_state())
        with mock.patch.object(ol.WebApi, "join_call_ice") as join:
            self.drive("_call_infra_check", host, ["", ""])
        join.assert_not_called()

    def test_a_refused_user_login_is_shown(self):
        host = FakeHost(state=plugged_state())
        error = ol.OdooError("call_infra_odoo_user_login", login="utilisateur")
        with mock.patch.object(ol.WebApi, "join_call_ice", side_effect=error):
            out = self.drive(
                "_call_infra_check",
                host,
                ["", "o", "", "utilisateur", USER_PASSWORD],
            )
        self.assertIn(
            self.text("call_infra_odoo_user_login", login="utilisateur"), out
        )

    def test_without_odoo_the_question_is_not_asked(self):
        host = FakeHost(state=installed_state())
        self.drive("_call_infra_check", host, [""])
        self.assertFalse(
            any(t("call_infra_ask_check_odoo") in p for p in self.prompts)
        )

    def test_the_install_report_never_asks_it(self):
        # Le rapport d'après l'installation ne pose pas la question.
        host = FakeHost(state=plugged_state())
        with mock.patch.object(ol.WebApi, "join_call_ice") as join:
            self.todo_report(host)
        join.assert_not_called()

    def todo_report(self, host):
        pending = [""]
        with (
            mock.patch(
                "builtins.input", side_effect=lambda *a: pending.pop(0)
            ),
            mock.patch.object(ci, "check_local", return_value=LINES),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.todo._call_infra_report(host)
        self.assertEqual(pending, [])

    def test_odoo_lines_have_labels(self):
        line = odoo_line(ODOO_KEY, 3)
        self.assertTrue(
            self.todo._call_infra_line(line).startswith(
                f"✓ {t('Odoo server')} 3 : "
            )
        )
        for name in (
            "odoo-ice",
            "odoo-ice-turns:192.0.2.10:5349?transport=tcp",
        ):
            line = ci.CheckLine(
                name, False, "call_infra_check_ice_none", {"url": "x"}
            )
            self.assertTrue(
                self.todo._call_infra_line(line).startswith(
                    f"✗ {t('ICE handed out by Odoo')} : "
                )
            )


class TestUninstallOdoo(OdooCase):
    def test_each_odoo_is_offered_for_removal_first(self):
        host = FakeHost(state=plugged_state())
        self.drive(
            "_call_infra_uninstall",
            host,
            ["", "n", "o"] + REMOVE_ONE,
        )
        self.assertEqual(
            host.kinds(), ["probe", "odoo-remove", "probe", "uninstall"]
        )
        self.assertEqual(self.link.names(), ["set_params", "replace_rows"])
        self.assertIn(
            self.text("call_infra_ask_remove_odoo_first", odoo=ODOO_KEY),
            self.prompts[0],
        )

    def test_declining_the_uninstall_leaves_each_odoo_plugged(self):
        host = FakeHost(state=plugged_state())
        out = self.drive("_call_infra_uninstall", host, ["", "n", "n"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertEqual(self.made, [])
        self.assertIn(ODOO_KEY, host.state["odoos"])
        self.assertIn(t("Nothing uninstalled."), out)

    def test_the_odoo_kept_are_listed(self):
        host = FakeHost(state=plugged_state())
        out = self.drive("_call_infra_uninstall", host, ["n", "n", "n"])
        self.assertEqual(host.kinds(), ["probe"])
        self.assertIn(
            self.text("call_infra_uninstall_odoos_kept", odoos=ODOO_KEY), out
        )

    def test_without_odoo_nothing_more_is_asked(self):
        host = FakeHost(state=installed_state())
        self.drive("_call_infra_uninstall", host, ["n", "n"])
        self.assertEqual(host.kinds(), ["probe"])


class TestInstallWithOdoo(OdooCase):
    def test_a_port_change_names_the_odoo_to_add_again(self):
        host = FakeHost(state=plugged_state())
        out = self.drive(
            "_call_infra_install",
            host,
            ["", "", "", "", "3479", "", "", "n"],
        )
        self.assertIn(self.text("call_infra_odoo_readd", odoos=ODOO_KEY), out)
        self.assertEqual(host.kinds(), ["probe"])


class TestOdooLink(unittest.TestCase):
    """Construction réelle des liens : aucun ne joint Odoo avant le premier
    appel, rien ne part sur le réseau."""

    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO()

    def link(self, method, replies, runner=None, hidden=()):
        """Construit le lien : `replies` pour input(), `hidden` pour la
        saisie sans écho, chacune épuisée."""
        pending, secrets = list(replies), list(hidden)
        out = io.StringIO()
        self.getpass = mock.Mock(side_effect=lambda *a: secrets.pop(0))
        with (
            mock.patch(
                "builtins.input", side_effect=lambda *a: pending.pop(0)
            ),
            mock.patch("getpass.getpass", self.getpass),
            mock.patch.object(
                self.todo, "_ntfy_mobile_host", return_value=runner
            ),
            contextlib.redirect_stdout(out),
        ):
            found = self.todo._call_infra_odoo_link(ODOO_URL, ODOO_DB, method)
        self.assertEqual((pending, secrets), ([], []))
        return found, out.getvalue()

    def test_the_web_api_takes_the_hidden_password(self):
        (link, runner), out = self.link("webapi", [""], hidden=[ODOO_PASSWORD])
        self.getpass.assert_called_once()
        self.assertIn(
            t("call_infra_ask_odoo_password"), self.getpass.call_args.args[0]
        )
        self.assertIsInstance(link, ol.WebApi)
        self.assertIsNone(runner)
        self.assertEqual(
            (link.url, link.database, link.login), (ODOO_URL, ODOO_DB, "admin")
        )
        self.assertNotIn(ODOO_PASSWORD, out)
        self.assertEqual(link._secret, ODOO_PASSWORD)

    def test_the_shell_here_defaults_to_this_erplibre(self):
        local = nm.LocalHost()
        (link, runner), _out = self.link("shell", [""], runner=local)
        self.assertIsInstance(link, ol.OdooShell)
        self.assertIs(runner, local)
        self.assertEqual(link.erplibre_dir, str(REPO))
        self.assertEqual(link.url, ODOO_URL)

    def test_the_shell_over_ssh_needs_a_typed_directory(self):
        remote = nm.SshHost("alias-exemple")
        (link, _runner), _out = self.link(
            "shell", ["/srv/erplibre-exemple"], runner=remote
        )
        self.assertEqual(link.erplibre_dir, "/srv/erplibre-exemple")
        self.assertEqual(link.host.target, "alias-exemple")
        # Le runner passe par le masque des lignes de paramètres.
        self.assertIsInstance(link.host, cim._QuietHost)
        self.assertEqual(link.host._hide, cim.ODOO_HIDDEN)

    def test_a_relative_directory_is_refused(self):
        (link, _runner), out = self.link(
            "shell", ["relatif"], runner=nm.SshHost("alias-exemple")
        )
        self.assertIsNone(link)
        self.assertIn(
            t("call_infra_odoo_dir").format(directory="relatif"), out
        )

    def test_shell_parameter_and_row_lines_stay_off_screen(self):
        class Runner:
            target = "alias-exemple"

            def run(self, script, sudo_user):
                text = (
                    "@@ODOO_PARAM erplibre_turn.urls dXJs\n@@ODOO_DONE facts\n"
                )
                sys.stdout.buffer.write(text.encode())
                return 0, text

        quiet = cim._QuietHost(Runner(), cim.ODOO_HIDDEN)
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        with contextlib.redirect_stdout(out):
            code, captured = quiet.run("script", None)
        out.flush()
        shown = out.buffer.getvalue().decode()
        self.assertIn("dXJs", captured)
        self.assertNotIn("dXJs", shown)
        self.assertIn("@@ODOO_DONE facts", shown)
        self.assertEqual(quiet.target, "alias-exemple")


class TestOdooModuleStates(unittest.TestCase):
    def test_the_menu_reads_module_states_as_the_plan_does(self):
        state = installed_state()
        for module_state in (
            "installed",
            "to upgrade",
            "uninstalled",
            "to install",
            "to remove",
            "uninstallable",
            "absent",
        ):
            with self.subTest(module_state=module_state):
                facts = odoo_facts(module_state)
                kept = ci.plan_odoo_add(
                    state, facts, ODOO_URL, ODOO_DB, False, None
                )
                offered = ci.plan_odoo_add(
                    state, facts, ODOO_URL, ODOO_DB, True, None
                )
                expected = (
                    "installed"
                    if kept.kind == "secret"
                    else "installable" if offered.install_module else "absent"
                )
                self.assertEqual(
                    cim.CallInfraMenuMixin._call_infra_module_kind(facts),
                    expected,
                )


class TestSubmenu(unittest.TestCase):
    def test_dispatches_to_the_six_actions(self):
        from script.todo.todo import TODO

        todo = TODO()
        order = []
        names = (
            "_call_infra_install",
            "_call_infra_add_odoo",
            "_call_infra_remove_odoo",
            "prompt_execute_ntfy_mobile",
            "_call_infra_check",
            "_call_infra_uninstall",
        )
        with contextlib.ExitStack() as stack:
            for name in names:
                stack.enter_context(
                    mock.patch.object(
                        TODO,
                        name,
                        side_effect=lambda name=name: order.append(name),
                    )
                )
            stack.enter_context(
                mock.patch(
                    "click.prompt",
                    side_effect=["1", "2", "3", "4", "5", "6", "0"],
                )
            )
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            todo.prompt_execute_call_infra()
        self.assertEqual(order, list(names))

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
        aucun `t("…")` littéral ne les montre au test précédent. Les refus
        d'`odoo_link` (`OdooError`) arrivent au menu de la même façon."""
        source = CALL_INFRA_PY.read_text(encoding="utf-8")
        source += MENU_PY.read_text(encoding="utf-8")
        source += ODOO_LINK_PY.read_text(encoding="utf-8")
        keys = set(re.findall(r'"(call_infra_[a-z0-9_]+)"', source))
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
            "Call infra - Add an Odoo server": "Ajouter un serveur Odoo",
            "Call infra - Remove an Odoo server": "Retirer un serveur Odoo",
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
    # Chaque chemin de OLD_PATHS, ses mots séparés par n'importe quelle
    # suite de blancs, saut de ligne compris.
    OLD_PATTERNS = tuple(
        re.compile(r"\s+".join(re.escape(word) for word in old.split()))
        for old in OLD_PATHS
    )

    def _read(self, relative):
        return (REPO / relative).read_text(encoding="utf-8")

    def _names_old_path(self, text):
        return any(pattern.search(text) for pattern in self.OLD_PATTERNS)

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
            with self.subTest(relative=relative):
                self.assertFalse(
                    self._names_old_path(self._read(relative)), relative
                )

    def test_an_old_path_wrapped_across_lines_is_caught(self):
        """Un paragraphe reformaté coupe le chemin n'importe où : entre
        ses mots, l'espace peut devenir un saut de ligne ou plusieurs
        espaces."""
        for text in (
            "`TODO › Déployer ›\nPréparer ntfy pour ERPLibre mobile`",
            "TODO › Deploy  ›   Prepare\n  ntfy for ERPLibre mobile",
            "Deploy › Prepare ntfy",
        ):
            with self.subTest(text=text):
                self.assertTrue(self._names_old_path(text))
        self.assertFalse(
            self._names_old_path(self.MENU_FR + " › Préparer ntfy")
        )

    def test_the_changelog_names_the_menu_in_both_languages(self):
        unreleased = self._read("CHANGELOG.base.md").split("## [1.8.0]")[0]
        for needle in (self.MENU_EN, self.MENU_FR, "coturn"):
            self.assertIn(needle, unreleased)
        self.assertIn(self.MENU_EN, self._read("CHANGELOG.md"))
        self.assertIn(self.MENU_FR, self._read("CHANGELOG.fr.md"))

    def test_the_changelog_quotes_the_odoo_server_screens(self):
        """Chaque moitié du journal cite l'écran dans sa langue, mot pour
        mot depuis TRANSLATIONS : une entrée renommée dans le menu fait
        échouer ce test tant que le journal n'a pas suivi."""
        keys = (
            "Call infra - Add an Odoo server",
            "Call infra - Remove an Odoo server",
            "call_infra_ask_check_odoo",
            "call_infra_ask_fixed_fallback",
        )
        for lang, generated in (
            ("en", "CHANGELOG.md"),
            ("fr", "CHANGELOG.fr.md"),
        ):
            unreleased = self._read(generated).split("## [1.8.0]")[0]
            for key in keys:
                with self.subTest(lang=lang, key=key):
                    self.assertIn(TRANSLATIONS[key][lang], unreleased)
            for needle in ("erplibre_turn", "use-auth-secret", "lt-cred-mech"):
                with self.subTest(lang=lang, needle=needle):
                    self.assertIn(needle, unreleased)

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
