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
        # {nom: [adresses]} que la résolution doublure rend ; un nom absent
        # ne résout pas. Aucune requête DNS ne part des tests.
        self.dns = {}
        self.prompts = []

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
