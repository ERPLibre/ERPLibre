#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""`script/todo/call_infra.py` : sonde d'un hôte, plan d'installation,
adoption, script d'installation et état de l'hôte.

La sonde et le script d'installation sont joués dans un bac à sable : un
dossier temporaire tient lieu de racine (`root`), et les commandes système
(`systemctl`, `ss`, `ufw`, `chown`, les installateurs lancés par `bash`...)
sont des bouchons qui notent leurs appels. Rien ne touche le système qui
lance les tests. Toutes les valeurs sont inventées (`*.exemple.test`,
192.0.2.x, 198.51.100.x, 2001:db8::).
"""

import ast
import base64
import dataclasses
import hashlib
import datetime
import http.server
import json
import os
import re
import shlex
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

from script.todo import call_infra as ci
from script.todo import ntfy_mobile as nm
from script.todo import turn_client as tc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COTURN_INSTALLER = os.path.join(REPO, "script", "install", "install_coturn.sh")
NTFY_INSTALLER = os.path.join(REPO, "script", "install", "install_ntfy.sh")

STAMP = "20261030-101500"
NOW = datetime.datetime.now(datetime.timezone.utc)
UTC = datetime.timezone.utc


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


DEBIAN_PROBE = (
    "\n"
    "@@OS debian 13 \n"
    "@@SYSTEMD yes\n"
    "@@HOSTNAME hote-exemple\n"
    "@@ADDR 192.0.2.10\n"
    "@@ADDR 2001:db8::10\n"
    "@@PORT tcp 22 sshd\n"
    "@@PORT udp 68 dhclient\n"
    "@@PORT tcp 22 sshd\n"
    "@@COTURN - - -\n"
    "@@NTFY - - /etc/ntfy/server.yml\n"
    "@@FIREWALL none\n"
    "@@END\n"
)

ARCH_COTURN = "listening-port=3478\nrealm=ancien.exemple.test\n"
ARCH_PROBE = (
    "@@OS arch rolling \r\n"
    "@@SYSTEMD yes\r\n"
    "@@HOSTNAME arch-exemple\r\n"
    "@@ADDR 198.51.100.7\r\n"
    "@@PORT udp 3478 turnserver\r\n"
    "@@PORT tcp 3478 turnserver\r\n"
    "@@COTURN turnserver active /etc/turnserver/turnserver.conf\r\n"
    "@@NTFY - - /etc/ntfy/server.yml\r\n"
    "@@FILE /etc/turnserver/turnserver.conf %s\r\n"
    "@@FIREWALL ufw\r\n"
    "@@END\r\n" % b64(ARCH_COTURN)
)


def base_facts(**changes):
    facts = ci.HostFacts(
        family="debian",
        os_id="debian",
        os_version="13",
        systemd=True,
        hostname="hote-exemple",
        addresses=("192.0.2.10",),
        busy_ports=(("tcp", 22, "sshd"),),
        coturn=None,
        ntfy=None,
        firewall="none",
        state=None,
    )
    return dataclasses.replace(facts, **changes)


def answers(**changes):
    values = dict(
        services=frozenset({"coturn", "ntfy"}),
        tls="none",
        cert_pem=None,
        key_pem=None,
        public_name="turn.exemple.test",
    )
    values.update(changes)
    return ci.Answers(**values)


def service(config, text, unit="coturn", active="active", pending=None):
    return {
        "unit": unit,
        "unit_found": True,
        "active": active,
        "config": config,
        "config_text": text,
        "managed": text.split("\n", 1)[0] == ci.MARKER,
        "pending": pending,
    }


def openssl(*args):
    subprocess.run(
        ["openssl", *args], check=True, capture_output=True, text=True
    )


class Certificates:
    """Certificats auto-signés inventés, créés une fois pour le module."""

    directory = None

    @classmethod
    def make(cls, name, subject, san, days=30):
        if cls.directory is None:
            cls.directory = tempfile.TemporaryDirectory()
        crt = os.path.join(cls.directory.name, name + ".crt")
        key = os.path.join(cls.directory.name, name + ".key")
        args = [
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            key,
            "-out",
            crt,
            "-days",
            str(days),
            "-subj",
            "/CN=" + subject,
        ]
        if san:
            args += ["-addext", "subjectAltName=" + san]
        openssl(*args)
        with open(crt) as c, open(key) as k:
            return c.read(), k.read()


def setUpModule():
    global TURN_CERT, TURN_KEY, OTHER_CERT, OTHER_KEY, WILD_CERT, WILD_KEY
    global BARE_CERT, BARE_KEY
    TURN_CERT, TURN_KEY = Certificates.make(
        "turn", "turn.exemple.test", "DNS:turn.exemple.test,IP:192.0.2.10"
    )
    OTHER_CERT, OTHER_KEY = Certificates.make(
        "other", "other.exemple.test", "DNS:other.exemple.test"
    )
    WILD_CERT, WILD_KEY = Certificates.make(
        "wild", "exemple.test", "DNS:*.exemple.test"
    )
    BARE_CERT, BARE_KEY = Certificates.make("bare", "turn.exemple.test", "")


def tearDownModule():
    if Certificates.directory is not None:
        Certificates.directory.cleanup()


def supplied(**changes):
    values = dict(tls="supplied", cert_pem=TURN_CERT, key_pem=TURN_KEY)
    values.update(changes)
    return answers(**values)


class TestParseProbe(unittest.TestCase):
    def test_debian_13(self):
        facts = ci.parse_probe(DEBIAN_PROBE)
        self.assertEqual(facts.family, "debian")
        self.assertEqual(facts.os_id, "debian")
        self.assertEqual(facts.os_version, "13")
        self.assertTrue(facts.systemd)
        self.assertEqual(facts.hostname, "hote-exemple")
        self.assertEqual(facts.addresses, ("192.0.2.10", "2001:db8::10"))
        # Une ligne répétée par ss (IPv4 et IPv6) ne compte qu'une fois.
        self.assertEqual(
            facts.busy_ports, (("tcp", 22, "sshd"), ("udp", 68, "dhclient"))
        )
        self.assertIsNone(facts.coturn)
        self.assertIsNone(facts.ntfy)
        self.assertEqual(facts.firewall, "none")
        self.assertIsNone(facts.state)

    def test_arch_with_a_foreign_coturn(self):
        facts = ci.parse_probe(ARCH_PROBE)
        self.assertEqual(facts.family, "arch")
        self.assertEqual(facts.os_version, "rolling")
        self.assertEqual(facts.firewall, "ufw")
        self.assertEqual(facts.coturn["unit"], "turnserver")
        self.assertEqual(facts.coturn["active"], "active")
        self.assertEqual(
            facts.coturn["config"], "/etc/turnserver/turnserver.conf"
        )
        self.assertEqual(facts.coturn["config_text"], ARCH_COTURN)
        self.assertFalse(facts.coturn["managed"])
        self.assertIn(("udp", 3478, "turnserver"), facts.busy_ports)

    def test_enabled_state_of_each_unit(self):
        text = ARCH_PROBE.replace(
            "@@FIREWALL ufw\r\n",
            "@@ENABLED coturn disabled\r\n@@FIREWALL ufw\r\n",
        )
        self.assertEqual(ci.parse_probe(text).coturn["enabled"], "disabled")
        self.assertIsNone(ci.parse_probe(ARCH_PROBE).coturn["enabled"])

    def test_arch_config_path_defaults_to_the_package_one(self):
        text = ARCH_PROBE.replace(
            "turnserver active /etc/turnserver/turnserver.conf",
            "turnserver inactive -",
        )
        facts = ci.parse_probe(text)
        self.assertEqual(
            facts.coturn["config"], "/etc/turnserver/turnserver.conf"
        )
        self.assertEqual(facts.coturn["active"], "inactive")

    def test_family_by_id_like(self):
        text = DEBIAN_PROBE.replace(
            "@@OS debian 13 ", "@@OS pop 24.04 ubuntu debian"
        )
        self.assertEqual(ci.parse_probe(text).family, "debian")
        text = DEBIAN_PROBE.replace("@@OS debian 13 ", "@@OS cachyos - arch")
        self.assertEqual(ci.parse_probe(text).family, "arch")
        text = DEBIAN_PROBE.replace("@@OS debian 13 ", "@@OS fedora 41 ")
        self.assertIsNone(ci.parse_probe(text).family)

    def test_managed_ntfy_state_and_pending(self):
        state = {"version": 1, "services": {}}
        pending = {"installed_by_tool": True, "adopted": False, "backup": None}
        yml = ci.MARKER + '\nlisten-http: ":8080"\n'
        text = DEBIAN_PROBE.replace(
            "@@NTFY - - /etc/ntfy/server.yml\n",
            "@@NTFY ntfy active /etc/ntfy/server.yml\n"
            "@@FILE /etc/ntfy/server.yml %s\n"
            "@@PENDING ntfy %s\n"
            "@@STATE %s\n"
            % (b64(yml), b64(json.dumps(pending)), b64(json.dumps(state))),
        )
        facts = ci.parse_probe(text)
        self.assertEqual(facts.ntfy["unit"], "ntfy")
        self.assertTrue(facts.ntfy["managed"])
        self.assertEqual(facts.ntfy["config_text"], yml)
        self.assertEqual(facts.ntfy["pending"], pending)
        self.assertEqual(facts.state, state)

    def test_truncated_output_is_refused(self):
        with self.assertRaises(ci.Refusal) as caught:
            ci.parse_probe(DEBIAN_PROBE.replace("@@END\n", ""))
        self.assertEqual(caught.exception.key, "call_infra_probe_incomplete")

    def test_marker_lines_keep_repeats_and_underscores(self):
        lines = ci.marker_lines(
            "x\n@@ACTIVE coturn active\n@@ADMIN_PASSWORD Ab1\n@@ACTIVE coturn failed\n"
        )
        self.assertEqual(
            lines,
            [
                ("ACTIVE", "coturn active"),
                ("ADMIN_PASSWORD", "Ab1"),
                ("ACTIVE", "coturn failed"),
            ],
        )


def write(path, text, mode=0o755):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    os.chmod(path, mode)


# ufw traduit ses messages : un bouchon qui ne parle anglais que sous la
# locale C, LANGUAGE vide (gettext le lit avant LC_ALL).
IN_C = '[ "${LC_ALL:-}" = C ] && [ -z "${LANGUAGE:-}" ]'
FRENCH = dict(LANG="fr_CA.UTF-8", LC_ALL="fr_CA.UTF-8", LANGUAGE="fr_CA:fr")


# Colonnes de `ss -Hlntup` : proto, état, files, local, distante, processus.
SS_OUTPUT = (
    "tcp   LISTEN 0      4096         0.0.0.0:8080       0.0.0.0:*    "
    'users:(("nginx",pid=812,fd=6))\n'
    "udp   UNCONN 0      0               [::]:3478          [::]:*    "
    'users:(("turnserver",pid=900,fd=12))\n'
    "tcp   LISTEN 0      128             [::]:22            [::]:*    "
    'users:(("sshd",pid=700,fd=4))\n'
)
COTURN_UNIT = (
    "# /usr/lib/systemd/system/coturn.service\n"
    "[Service]\n"
    "ExecStart=/usr/bin/turnserver -c /etc/turnserver.conf --pidfile=\n"
)


class TestProbeScript(unittest.TestCase):
    """La sonde jouée pour de vrai, racine et commandes en bouchons."""

    def run_probe(self, ufw="Status: active", state=None, added=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            stubs = os.path.join(tmp, "stubs")
            write(
                os.path.join(root, "etc/os-release"),
                'ID=debian\nVERSION_ID="13"\nNAME="Debian"\n',
                0o644,
            )
            os.makedirs(os.path.join(root, "run/systemd/system"))
            write(
                os.path.join(root, "etc/turnserver.conf"), ARCH_COTURN, 0o644
            )
            if state is not None:
                write(
                    os.path.join(root, "etc/erplibre-call/state.json"),
                    json.dumps(state),
                    0o600,
                )
            write(
                os.path.join(stubs, "ss"),
                "#!/bin/sh\ncat <<'EOF'\n%sEOF\n" % SS_OUTPUT,
            )
            write(
                os.path.join(stubs, "ip"),
                "#!/bin/sh\necho '2: eth0    inet 192.0.2.10/24"
                " brd 192.0.2.255 scope global eth0'\n",
            )
            write(
                os.path.join(stubs, "uname"), "#!/bin/sh\necho hote-exemple\n"
            )
            write(
                os.path.join(stubs, "systemctl"),
                (
                    "#!/bin/sh\n"
                    'case "$1 $2" in\n'
                    "  'cat coturn') cat <<'EOF'\n%sEOF\n;;\n"
                    "  'is-active coturn') echo active ;;\n"
                    "  'is-enabled coturn') echo disabled; exit 1 ;;\n"
                    "  *) exit 3 ;;\n"
                    "esac\n"
                )
                % COTURN_UNIT,
            )
            write(
                os.path.join(stubs, "ufw"),
                "#!/bin/sh\n"
                "if [ \"$1 $2\" = 'show added' ]; then cat <<'EOF'\n"
                "%sEOF\nexit 0; fi\n"
                "if %s; then echo '%s'; else echo 'État : traduit';"
                " fi\n" % (added, IN_C, ufw),
            )
            for name in ("nft", "iptables"):
                write(os.path.join(stubs, name), "#!/bin/sh\nexit 1\n")
            env = dict(
                os.environ, PATH=stubs + ":" + os.environ["PATH"], **FRENCH
            )
            done = subprocess.run(
                ["sh", "-c", ci.probe_script(root=root)],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            return done

    def test_probe_reads_the_host(self):
        state = {"version": 1, "services": {}}
        done = self.run_probe(state=state)
        self.assertEqual(done.returncode, 0, done.stderr)
        facts = ci.parse_probe(done.stdout)
        self.assertEqual(facts.family, "debian")
        self.assertEqual(facts.os_version, "13")
        self.assertTrue(facts.systemd)
        self.assertEqual(facts.hostname, "hote-exemple")
        self.assertEqual(facts.addresses, ("192.0.2.10",))
        self.assertEqual(
            set(facts.busy_ports),
            {
                ("tcp", 8080, "nginx"),
                ("udp", 3478, "turnserver"),
                ("tcp", 22, "sshd"),
            },
        )
        self.assertEqual(facts.coturn["unit"], "coturn")
        self.assertEqual(facts.coturn["config"], "/etc/turnserver.conf")
        self.assertEqual(facts.coturn["config_text"], ARCH_COTURN)
        self.assertFalse(facts.coturn["managed"])
        self.assertEqual(facts.coturn["enabled"], "disabled")
        self.assertIsNone(facts.ntfy)
        self.assertEqual(facts.firewall, "ufw")
        self.assertEqual(facts.state, state)

    def test_probe_lists_the_ufw_rules_of_an_active_ufw(self):
        added = (
            "Added user rules (see 'ufw status' for running firewall):\n"
            "ufw allow 22/tcp\n"
            "ufw limit 3478/udp\n"
        )
        facts = ci.parse_probe(self.run_probe(added=added).stdout)
        self.assertEqual(
            facts.ufw_added, ("ufw allow 22/tcp", "ufw limit 3478/udp")
        )
        idle = self.run_probe(ufw="Status: inactive", added=added)
        self.assertEqual(ci.parse_probe(idle.stdout).ufw_added, ())

    def test_inactive_ufw_and_no_nft_is_none(self):
        done = self.run_probe(ufw="Status: inactive")
        self.assertEqual(ci.parse_probe(done.stdout).firewall, "none")

    def test_probe_writes_nothing(self):
        script = ci.probe_script()
        stripped = re.sub(r"[0-9]?>(/dev/null|&1)", "", script)
        self.assertNotIn(">", stripped)
        for word in (
            "rm ",
            "mv ",
            "cp ",
            "tee ",
            "chmod ",
            "chown ",
            "ufw allow",
            "nft add",
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
        ):
            self.assertNotIn(word, script)


class TestRefusals(unittest.TestCase):
    def refusal(self, facts, ans, now=NOW):
        with self.assertRaises(ci.Refusal) as caught:
            ci.plan_install(facts, ans, now)
        return caught.exception

    def test_unsupported_os(self):
        facts = base_facts(family=None, os_id="fedora", os_version="41")
        refusal = self.refusal(facts, answers())
        self.assertEqual(refusal.key, "call_infra_unsupported_os")
        self.assertEqual(refusal.values["os"], "fedora")
        self.assertIn("Debian", refusal.values["supported"])

    def test_no_systemd(self):
        refusal = self.refusal(base_facts(systemd=False), answers())
        self.assertEqual(refusal.key, "call_infra_no_systemd")

    def test_port_busy_names_port_and_process(self):
        facts = ci.parse_probe(
            DEBIAN_PROBE.replace(
                "@@PORT udp 68", "@@PORT tcp 8080 nginx\n@@PORT udp 68"
            )
        )
        refusal = self.refusal(facts, answers(services=frozenset({"ntfy"})))
        self.assertEqual(refusal.key, "call_infra_port_busy")
        self.assertEqual(refusal.values["port"], 8080)
        self.assertEqual(refusal.values["proto"], "tcp")
        self.assertEqual(refusal.values["process"], "nginx")

    def test_port_held_by_the_other_service_is_busy(self):
        facts = base_facts(busy_ports=(("tcp", 3478, "ntfy"),))
        refusal = self.refusal(facts, answers(services=frozenset({"coturn"})))
        self.assertEqual(refusal.key, "call_infra_port_busy")

    def test_tls_ports_counted_only_with_a_certificate(self):
        facts = base_facts(busy_ports=(("tcp", 5349, "stunnel"),))
        ci.plan_install(facts, answers(), NOW)
        refusal = self.refusal(facts, supplied())
        self.assertEqual(refusal.values["port"], 5349)

    def test_https_ntfy_keeps_its_loopback_http_port(self):
        facts = base_facts(busy_ports=(("tcp", 8080, "nginx"),))
        refusal = self.refusal(facts, supplied(services=frozenset({"ntfy"})))
        self.assertEqual(refusal.values["port"], 8080)

    def test_cert_key_mismatch(self):
        refusal = self.refusal(base_facts(), supplied(key_pem=OTHER_KEY))
        self.assertEqual(refusal.key, "call_infra_cert_key_mismatch")

    def test_cert_expired(self):
        later = datetime.datetime(2100, 1, 1, tzinfo=UTC)
        refusal = self.refusal(base_facts(), supplied(), now=later)
        self.assertEqual(refusal.key, "call_infra_cert_expired")
        self.assertIn("date", refusal.values)

    def test_naive_now_is_read_as_utc(self):
        refusal = self.refusal(
            base_facts(), supplied(), now=datetime.datetime(2100, 1, 1)
        )
        self.assertEqual(refusal.key, "call_infra_cert_expired")

    def test_cert_for_another_name(self):
        refusal = self.refusal(
            base_facts(), supplied(cert_pem=OTHER_CERT, key_pem=OTHER_KEY)
        )
        self.assertEqual(refusal.key, "call_infra_cert_name_missing")
        self.assertEqual(refusal.values["name"], "turn.exemple.test")
        self.assertIn("other.exemple.test", refusal.values["names"])

    def test_ip_san_missing(self):
        refusal = self.refusal(
            base_facts(),
            supplied(
                cert_pem=WILD_CERT, key_pem=WILD_KEY, public_name="192.0.2.10"
            ),
        )
        self.assertEqual(refusal.key, "call_infra_cert_name_missing")

    def test_common_name_alone_does_not_cover(self):
        refusal = self.refusal(
            base_facts(), supplied(cert_pem=BARE_CERT, key_pem=BARE_KEY)
        )
        self.assertEqual(refusal.key, "call_infra_cert_name_missing")

    def test_names_that_are_covered(self):
        ci.plan_install(base_facts(), supplied(), NOW)
        ci.plan_install(base_facts(), supplied(public_name="192.0.2.10"), NOW)
        ci.plan_install(
            base_facts(), supplied(cert_pem=WILD_CERT, key_pem=WILD_KEY), NOW
        )

    def test_unreadable_certificate(self):
        refusal = self.refusal(
            base_facts(), supplied(cert_pem="pas un certificat\n")
        )
        self.assertEqual(refusal.key, "call_infra_cert_unreadable")

    def test_bad_values(self):
        for change in (
            {"public_name": "turn exemple"},
            {"public_name": "turn.exemple.test\nuser=x"},
            {"turn_port": 0},
            {"min_port": 50000, "max_port": 49000},
            {"external_ip": "198.51.100.7 x"},
            {"ntfy_port": 3478},
        ):
            with self.subTest(change=change):
                refusal = self.refusal(base_facts(), answers(**change))
                self.assertEqual(refusal.key, "call_infra_bad_value")

    def test_state_of_another_version(self):
        refusal = self.refusal(
            base_facts(state={"version": 99, "services": {}}), answers()
        )
        self.assertEqual(refusal.key, "call_infra_state_version")


class TestPlan(unittest.TestCase):
    def test_fresh_host(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        self.assertEqual(plan.adopt, ())
        self.assertEqual(plan.diffs, ())
        self.assertFalse(plan.nothing_to_do)
        coturn = plan.new_state["services"]["coturn"]
        self.assertTrue(coturn["installed_by_tool"])
        self.assertFalse(coturn["adopted"])
        self.assertEqual(coturn["unit"], "coturn")
        self.assertEqual(coturn["config"], "/etc/turnserver.conf")
        self.assertEqual(plan.new_state["version"], ci.STATE_VERSION)
        self.assertEqual(
            plan.new_state["services"]["ntfy"]["settings"]["port"], 8080
        )

    def test_arch_paths(self):
        plan = ci.plan_install(
            base_facts(family="arch", os_id="arch"), answers(), NOW
        )
        coturn = plan.new_state["services"]["coturn"]
        self.assertEqual(coturn["unit"], "turnserver")
        self.assertEqual(coturn["config"], "/etc/turnserver/turnserver.conf")

    def test_state_holds_no_secret(self):
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        text = json.dumps(ci.written_state(plan, STAMP))
        self.assertNotIn("PRIVATE KEY", text)
        self.assertNotIn(TURN_KEY.splitlines()[1], text)

    def adopted_coturn(self):
        facts = base_facts(
            coturn=service(
                "/etc/turnserver.conf",
                "listening-port=3478\nrealm=ancien.exemple.test\n",
            ),
            busy_ports=(
                ("udp", 3478, "turnserver"),
                ("tcp", 3478, "turnserver"),
            ),
        )
        return facts, answers(services=frozenset({"coturn"}))

    def test_adoption_records_whether_the_unit_ran_and_was_enabled(self):
        facts, ans = self.adopted_coturn()
        stopped = dict(facts.coturn, active="inactive", enabled="disabled")
        plan = ci.plan_install(
            dataclasses.replace(facts, coturn=stopped), ans, NOW
        )
        record = plan.new_state["services"]["coturn"]
        self.assertIs(record["was_active"], False)
        self.assertEqual(record["was_enabled"], "disabled")
        # La fiche d'attente porte la même origine : une relance après
        # une coupure voit l'unité que l'installateur a démarrée.
        origin = json.loads(
            base64.b64decode(
                re.search(
                    r"printf %s '?([A-Za-z0-9+/=]+)'? \| base64 -d >"
                    r' "\$PENDING/coturn.new"',
                    ci.install_script(plan, STAMP),
                ).group(1)
            )
        )
        self.assertIs(origin["was_active"], False)
        self.assertEqual(origin["was_enabled"], "disabled")
        rerun = dict(
            stopped, active="active", enabled="enabled", pending=origin
        )
        again = ci.plan_install(
            dataclasses.replace(facts, coturn=rerun), ans, NOW
        )
        self.assertIs(
            again.new_state["services"]["coturn"]["was_active"], False
        )

    def test_unmanaged_coturn_is_adopted_with_a_diff(self):
        facts, ans = self.adopted_coturn()
        plan = ci.plan_install(facts, ans, NOW)
        self.assertEqual(plan.adopt, ("coturn",))
        self.assertEqual(len(plan.diffs), 1)
        path, diff = plan.diffs[0]
        self.assertEqual(path, "/etc/turnserver.conf")
        self.assertIn("-realm=ancien.exemple.test", diff)
        self.assertIn("+realm=turn.exemple.test", diff)
        record = plan.new_state["services"]["coturn"]
        self.assertTrue(record["adopted"])
        self.assertFalse(record["installed_by_tool"])
        written = ci.written_state(plan, STAMP)["services"]["coturn"]
        self.assertEqual(
            written["backup"], "/etc/turnserver.conf.bak-" + STAMP
        )

    def test_the_adoption_diff_hides_secret_values(self):
        # Le diff s'affiche : une valeur secrète d'une configuration
        # étrangère n'y paraît qu'en « *** ». Valeurs inventées.
        coturn = (
            "listening-port=3478\n"
            "static-auth-secret=Inventesecret123\n"
            "user=alice:Inventemotdepasse\n"
            "cli-password Inventecli\n"
            "realm=ancien.exemple.test\n"
        )
        ntfy = (
            'listen-http: ":8080"\n'
            'smtp-sender-pass: "Inventesmtp"\n'
            'web-push-private-key: "Inventepush"\n'
            "auth-users:\n"
            '  - "phil:$2a$10$Inventehash:admin"\n'
            'auth-default-access: "deny-all"\n'
        )
        facts = base_facts(
            coturn=service("/etc/turnserver.conf", coturn),
            ntfy=service(ci.NTFY_CONFIG, ntfy, unit="ntfy"),
            busy_ports=(("udp", 3478, "turnserver"), ("tcp", 8080, "ntfy")),
        )
        plan = ci.plan_install(facts, answers(), NOW)
        shown = "".join(diff for _path, diff in plan.diffs)
        for secret in (
            "Inventesecret123",
            "Inventemotdepasse",
            "Inventecli",
            "Inventesmtp",
            "Inventepush",
            "Inventehash",
        ):
            self.assertNotIn(secret, shown)
        self.assertIn("-static-auth-secret=***", shown)
        self.assertIn("-user=alice:***", shown)
        self.assertIn('smtp-sender-pass: "***"', shown)
        # Le reste du diff est intact, et ce que l'outil écrit garde les
        # vraies valeurs.
        self.assertIn("-realm=ancien.exemple.test", shown)
        self.assertIn("Inventesmtp", plan.configs["ntfy"])

    def test_secret_lists_are_hidden_in_flow_form(self):
        # Valeurs inventées : une liste YAML entre crochets, sur une ligne
        # ou sur plusieurs, perd ses éléments comme la liste en tirets.
        text = (
            'auth-users: ["phil:$2a$10$Inventeflux:admin"]\n'
            "auth-users: [\n"
            '  "anne:$2b$12$Inventeplusieurs:user",\n'
            "]\n"
            "auth-tokens: [\n"
            '  "anne:tk_Inventejeton:telephone",\n'
            "]\n"
            'listen-http: ":8080"\n'
        )
        shown = ci.redact_secrets(text)
        for secret in ("Inventeflux", "Inventeplusieurs", "Inventejeton"):
            self.assertNotIn(secret, shown)
        self.assertIn("auth-users: [***]\n", shown)
        self.assertIn('listen-http: ":8080"\n', shown)

    def test_a_bcrypt_hash_is_hidden_wherever_it_sits(self):
        text = (
            '# ancien compte : "phil:$2y$10$Inventecommentaire:admin"\n'
            "comptes: phil:$2a$10$Inventeautre\n"
        )
        shown = ci.redact_secrets(text)
        self.assertNotIn("Inventecommentaire", shown)
        self.assertNotIn("Inventeautre", shown)
        self.assertIn("# ancien compte : ", shown)

    def test_second_plan_on_the_produced_state_has_nothing_to_do(self):
        facts, ans = self.adopted_coturn()
        first = ci.plan_install(facts, ans, NOW)
        after = dataclasses.replace(
            facts,
            coturn=service("/etc/turnserver.conf", ci.coturn_config(ans)),
            state=ci.written_state(first, STAMP),
        )
        second = ci.plan_install(after, ans, NOW)
        self.assertTrue(second.nothing_to_do)
        self.assertEqual(second.adopt, ())
        self.assertEqual(second.diffs, ())
        record = second.new_state["services"]["coturn"]
        self.assertTrue(record["adopted"])
        self.assertEqual(record["backup"], "/etc/turnserver.conf.bak-" + STAMP)

    def both_installed(self, ans):
        first = ci.plan_install(base_facts(), ans, NOW)
        return base_facts(
            coturn=service("/etc/turnserver.conf", ci.coturn_config(ans)),
            ntfy=service(ci.NTFY_CONFIG, ci.ntfy_config(ans), unit="ntfy"),
            busy_ports=(
                ("udp", 3478, "turnserver"),
                ("tcp", 3478, "turnserver"),
                ("tcp", 8080, "ntfy"),
            ),
            state=ci.written_state(first, STAMP),
        )

    def test_rerun_with_the_same_answers(self):
        ans = answers()
        self.assertTrue(
            ci.plan_install(self.both_installed(ans), ans, NOW).nothing_to_do
        )
        ans = supplied()
        self.assertTrue(
            ci.plan_install(self.both_installed(ans), ans, NOW).nothing_to_do
        )

    def test_rerun_with_a_subset_of_the_services(self):
        ans = answers()
        facts = self.both_installed(ans)
        plan = ci.plan_install(
            facts, answers(services=frozenset({"coturn"})), NOW
        )
        self.assertTrue(plan.nothing_to_do)
        # ntfy reste consigné : seule la désinstallation l'efface.
        self.assertIn("ntfy", plan.new_state["services"])

    def test_something_to_do(self):
        ans = answers()
        facts = self.both_installed(ans)
        cases = {
            "other port": (facts, answers(turn_port=3479)),
            "other name": (facts, answers(public_name="appel.exemple.test")),
            "inactive": (
                dataclasses.replace(
                    facts, ntfy=dict(facts.ntfy, active="failed")
                ),
                ans,
            ),
            "edited by hand": (
                dataclasses.replace(
                    facts,
                    coturn=dict(
                        facts.coturn,
                        config_text=facts.coturn["config_text"] + "verbose\n",
                    ),
                ),
                ans,
            ),
            "no state": (dataclasses.replace(facts, state=None), ans),
            "other certificate": (
                self.both_installed(supplied()),
                supplied(cert_pem=WILD_CERT, key_pem=WILD_KEY),
            ),
        }
        for name, (f, a) in cases.items():
            with self.subTest(name):
                self.assertFalse(ci.plan_install(f, a, NOW).nothing_to_do)

    def test_pending_record_is_honoured(self):
        ans = answers(services=frozenset({"coturn"}))
        pending = {
            "installed_by_tool": False,
            "adopted": True,
            "backup": "/etc/turnserver.conf.bak-20261029-080000",
        }
        facts = base_facts(
            coturn=service(
                "/etc/turnserver.conf",
                ci.coturn_config(ans),
                active="failed",
                pending=pending,
            )
        )
        plan = ci.plan_install(facts, ans, NOW)
        self.assertEqual(plan.adopt, ())
        record = ci.written_state(plan, STAMP)["services"]["coturn"]
        self.assertTrue(record["adopted"])
        self.assertFalse(record["installed_by_tool"])
        self.assertEqual(record["backup"], pending["backup"])

    def test_unknown_state_keys_are_carried(self):
        ans = answers()
        facts = self.both_installed(ans)
        state = dict(
            facts.state,
            firewall={"kind": "ufw", "rules": [], "persisted": True},
        )
        plan = ci.plan_install(
            dataclasses.replace(facts, state=state), ans, NOW
        )
        self.assertEqual(plan.new_state["firewall"]["kind"], "ufw")

    def test_unmanaged_ntfy_is_adopted_and_keeps_its_lines(self):
        old = (
            'base-url: "http://ancien.exemple.test:8080"\n'
            'listen-http: ":8080"\n'
            'auth-file: "/var/lib/ntfy/user.db"\n'
            'auth-default-access: "deny-all"\n'
            'visitor-request-limit-exempt-hosts: "odoo.exemple.test"\n'
        )
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, old, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        plan = ci.plan_install(
            facts, answers(services=frozenset({"ntfy"})), NOW
        )
        self.assertEqual(plan.adopt, ("ntfy",))
        path, diff = plan.diffs[0]
        self.assertEqual(path, ci.NTFY_CONFIG)
        self.assertIn('+base-url: "http://turn.exemple.test:8080"', diff)
        self.assertNotIn(
            "exempt-hosts",
            "".join(
                l
                for l in diff.splitlines(True)
                if l[:1] in "+-" and not l.startswith(("+++", "---"))
            ),
        )


class TestCoturnConfig(unittest.TestCase):
    """Le texte que rend Python est celui qu'écrit `install_coturn.sh`."""

    def installer_config(self, env):
        with open(COTURN_INSTALLER) as handle:
            text = handle.read()

        def function(name):
            start = re.search(r"^%s\(\) \{" % name, text, re.M).start()
            return text[start : text.index("\n}\n", start) + 3]

        constants = "".join(
            re.search(r'^%s="[^"]*"\n' % name, text, re.M).group(0)
            for name in ("MARKER", "TLS_DIR", "DB_FILE")
        )
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "turnserver.conf")
            script = (
                "set -euo pipefail\nlog() { :; }\nchown() { :; }\n"
                + constants
                + env
                + "SERVICE_GROUP=turnserver\nCONFIG_CHANGED=0\n"
                + function("has_cert")
                + function("refuse_linked_config")
                + function("write_config")
                + "write_config %s\n" % conf
            )
            done = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(conf) as handle:
                return handle.read()

    def env(self, ans, cert):
        # coturn_config décrit un plan de développement : les plages
        # privées y restent permises, l'installateur reçoit
        # TURN_ALLOW_PRIVATE=1.
        return (
            "TURN_REALM=%s\nTURN_PORT=%d\nTURN_TLS_PORT=%d\nTURN_MIN_PORT=%d\n"
            "TURN_MAX_PORT=%d\nTURN_CERT_FILE=%s\nTURN_KEY_FILE=%s\n"
            "TURN_EXTERNAL_IP=%s\nTURN_ALLOW_PRIVATE=1\n"
            % (
                ans.public_name,
                ans.turn_port,
                ans.turns_port,
                ans.min_port,
                ans.max_port,
                "/x.crt" if cert else "",
                "/x.key" if cert else "",
                ans.external_ip or "",
            )
        )

    def test_parity_without_certificate(self):
        ans = answers(turn_port=3479, min_port=50000, max_port=50100)
        self.assertEqual(
            ci.coturn_config(ans), self.installer_config(self.env(ans, False))
        )

    def test_parity_with_certificate_and_external_ip(self):
        ans = supplied(external_ip="198.51.100.7")
        self.assertEqual(
            ci.coturn_config(ans), self.installer_config(self.env(ans, True))
        )


class TestNtfyConfig(unittest.TestCase):
    def test_http(self):
        text = ci.ntfy_config(answers())
        self.assertEqual(text.splitlines()[0], ci.MARKER)
        keys = nm.read_yml_keys(text)
        self.assertEqual(keys["base-url"], "http://turn.exemple.test:8080")
        self.assertEqual(keys["listen-http"], ":8080")
        self.assertNotIn("listen-https", keys)
        self.assertEqual(nm.config_problems(keys), [])

    def test_https_with_loopback_http(self):
        keys = nm.read_yml_keys(ci.ntfy_config(supplied()))
        self.assertEqual(keys["base-url"], "https://turn.exemple.test:8443")
        self.assertEqual(keys["listen-https"], ":8443")
        self.assertEqual(keys["listen-http"], "127.0.0.1:8080")
        self.assertEqual(keys["cert-file"], "/etc/ntfy/tls/ntfy.crt")
        self.assertEqual(keys["key-file"], "/etc/ntfy/tls/ntfy.key")

    def test_https_on_8080_moves_the_loopback_port(self):
        keys = nm.read_yml_keys(ci.ntfy_config(supplied(ntfy_port=8080)))
        self.assertEqual(keys["listen-https"], ":8080")
        self.assertEqual(keys["listen-http"], "127.0.0.1:8081")

    def test_ipv6_name_in_brackets(self):
        keys = nm.read_yml_keys(
            ci.ntfy_config(answers(public_name="2001:db8::10"))
        )
        self.assertEqual(keys["base-url"], "http://[2001:db8::10]:8080")

    def test_idempotent_and_back_to_http(self):
        for ans in (answers(), supplied()):
            once = ci.ntfy_config(ans)
            self.assertEqual(ci.ntfy_config(ans, once), once)
        keys = nm.read_yml_keys(
            ci.ntfy_config(answers(), ci.ntfy_config(supplied()))
        )
        for key in ("listen-https", "cert-file", "key-file"):
            self.assertNotIn(key, keys)
        self.assertEqual(keys["listen-http"], ":8080")

    def test_adopted_text_keeps_other_lines_and_access(self):
        old = (
            '# mes notes\nlisten-http: ":8080"\n'
            'auth-default-access: "read-only"\nkeepalive-interval: "45s"\n'
        )
        new = ci.ntfy_config(answers(), old)
        self.assertIn("# mes notes\n", new)
        self.assertIn('keepalive-interval: "45s"\n', new)
        self.assertEqual(
            nm.read_yml_keys(new)["auth-default-access"], "read-only"
        )
        self.assertEqual(
            nm.read_yml_keys(new)["auth-file"], "/var/lib/ntfy/user.db"
        )

    def test_access_control_added_when_missing(self):
        new = ci.ntfy_config(answers(), 'listen-http: ":8080"\n')
        self.assertEqual(
            nm.read_yml_keys(new)["auth-default-access"], "deny-all"
        )


STUB_BASH = r"""#!/bin/sh
name=$(basename "$1" .sh)
cp "$1" "$LOG/$name.payload"
env | grep -E '^(TURN|NTFY)_' | sort > "$LOG/$name.env"
umask > "$LOG/$name.umask"
echo "$*" >> "$LOG/argv"
for f in $SEEN; do [ -e "$f" ] && echo "$f" >> "$LOG/$name.seen"; done
[ -n "${TURN_CERT_FILE:-}" ] && cat "$TURN_CERT_FILE" > "$LOG/$name.cert"
if [ "${KILL_AT:-}" = "$name" ]; then kill -KILL 0; fi
eval "exit \${RC_$name:-0}"
"""
STUB_SYSTEMCTL = r"""#!/bin/sh
[ "$1" = is-active ] || exit 0
eval "v=\${ACTIVE_$2:-active}"
echo "$v"
[ "$v" = active ]
"""


class TestInstallScriptText(unittest.TestCase):
    def test_no_check_password_and_key_only_in_base64(self):
        # Le mot de passe du compte de contrôle naît sur l'hôte, dans
        # install_coturn.sh : le script n'en porte aucun.
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        script = ci.install_script(plan, STAMP)
        self.assertNotIn("TURN_CHECK_PASSWORD", script)
        self.assertNotIn("PRIVATE KEY", script)
        for line in TURN_KEY.splitlines()[1:-1]:
            self.assertNotIn(line, script)

    def test_state_written_after_the_last_active_check_and_guarded(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        script = ci.install_script(plan, STAMP)
        last_active = script.rindex("@@ACTIVE")
        guard = script.index('if [ "$OK" = 1 ]; then')
        write_state = script.index('> "$STATE.new"')
        self.assertLess(last_active, guard)
        self.assertLess(guard, write_state)
        self.assertEqual(script.count('> "$STATE.new"'), 1)
        for svc in ("coturn", "ntfy"):
            self.assertIn('[ "$RC_%s" = 0 ] || OK=0' % svc, script)
            self.assertIn("@@ACTIVE %s " % svc, script)

    def test_fits_in_one_argument(self):
        # Le test long passe le script en UN argument de « sh -c » : Linux
        # borne un argument à 128 Kio (MAX_ARG_STRLEN), guillemets compris.
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        script = ci.install_script(plan, STAMP)
        self.assertLess(len(shlex.quote(script).encode()), 128 * 1024 - 4096)

    def test_bad_inputs(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        with self.assertRaises(ValueError):
            ci.install_script(plan, "../x")


class TestInstallScriptRun(unittest.TestCase):
    """Le script d'installation joué dans une racine temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "root")
        self.log = os.path.join(self.tmp.name, "log")
        self.stubs = os.path.join(self.tmp.name, "stubs")
        self.scratch = os.path.join(self.tmp.name, "scratch")
        for path in (self.root, self.log, self.scratch):
            os.makedirs(path)
        write(os.path.join(self.stubs, "bash"), STUB_BASH)
        write(os.path.join(self.stubs, "systemctl"), STUB_SYSTEMCTL)
        for name in ("chown", "useradd"):
            write(
                os.path.join(self.stubs, name),
                '#!/bin/sh\necho "%s $*" >> "$LOG/calls"\n' % name,
            )
        write(os.path.join(self.stubs, "id"), "#!/bin/sh\nexit 0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, host_path):
        return self.root + host_path

    def run_script(self, plan, seen=(), **env):
        script = ci.install_script(plan, STAMP, root=self.root)
        full = dict(
            os.environ,
            PATH=self.stubs + ":" + os.environ["PATH"],
            LOG=self.log,
            TMPDIR=self.scratch,
            SEEN=" ".join(self.path(p) for p in seen),
        )
        full.update(env)
        return subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            env=full,
            timeout=60,
            start_new_session=True,
        )

    def read(self, path):
        with open(path) as handle:
            return handle.read()

    def env_of(self, name):
        return dict(
            line.split("=", 1)
            for line in self.read(
                os.path.join(self.log, name + ".env")
            ).splitlines()
        )

    def test_success_writes_the_state_last(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state_file = self.path(ci.STATE_PATH)
        self.assertEqual(
            json.loads(self.read(state_file)), ci.written_state(plan, STAMP)
        )
        self.assertEqual(stat.S_IMODE(os.stat(state_file).st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path("/etc/erplibre-call")).st_mode),
            0o755,
        )
        self.assertFalse(
            os.path.exists(self.path("/etc/erplibre-call/pending/coturn.json"))
        )
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH + ".new")))
        markers = ci.marker_lines(done.stdout)
        self.assertIn(("ACTIVE", "coturn active"), markers)
        self.assertIn(("ACTIVE", "ntfy active"), markers)
        self.assertEqual(markers[-1], ("SAVED", "yes"))
        # Le dossier de travail (installateurs, certificat) est effacé.
        self.assertEqual(os.listdir(self.scratch), [])

    def test_installers_sent_whole_with_their_env(self):
        plan = ci.plan_install(
            base_facts(), answers(external_ip="198.51.100.7"), NOW
        )
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.read(os.path.join(self.log, "install_coturn.payload")),
            self.read(COTURN_INSTALLER),
        )
        self.assertEqual(
            self.read(os.path.join(self.log, "install_ntfy.payload")),
            self.read(NTFY_INSTALLER),
        )
        coturn = self.env_of("install_coturn")
        self.assertEqual(coturn["TURN_REALM"], "turn.exemple.test")
        self.assertNotIn("TURN_CHECK_PASSWORD", coturn)
        self.assertEqual(coturn["TURN_EXTERNAL_IP"], "198.51.100.7")
        self.assertEqual(coturn["TURN_MIN_PORT"], "49152")
        # Le plan de développement permet les plages privées : la
        # configuration écrite est celle que montre coturn_config.
        self.assertEqual(coturn["TURN_ALLOW_PRIVATE"], "1")
        self.assertNotIn("TURN_GARDER_CONFIG", coturn)
        self.assertNotIn("TURN_CERT_FILE", coturn)
        ntfy = self.env_of("install_ntfy")
        self.assertEqual(ntfy["NTFY_NON_INTERACTIVE"], "1")
        self.assertEqual(ntfy["NTFY_PORT"], "8080")
        self.assertEqual(
            ntfy["NTFY_BASE_URL"], "http://turn.exemple.test:8080"
        )
        self.assertNotIn("TURN_CHECK_PASSWORD", "".join(ntfy))
        for name in ("install_coturn", "install_ntfy"):
            self.assertEqual(
                self.read(os.path.join(self.log, name + ".umask")).strip(),
                "0022",
            )

    def test_ntfy_config_written_before_its_installer(self):
        ans = answers(services=frozenset({"ntfy"}))
        plan = ci.plan_install(base_facts(), ans, NOW)
        done = self.run_script(plan, seen=(ci.NTFY_CONFIG,))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.read(self.path(ci.NTFY_CONFIG)), ci.ntfy_config(ans)
        )
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path(ci.NTFY_CONFIG)).st_mode), 0o644
        )
        self.assertIn(
            self.path(ci.NTFY_CONFIG),
            self.read(os.path.join(self.log, "install_ntfy.seen")),
        )

    def test_a_new_ntfy_config_dir_is_traversable(self):
        # Le script tourne sous umask 077, et ntfy, sous son propre compte,
        # doit atteindre server.yml : faute de quoi il démarre sur ses
        # valeurs par défaut, sans contrôle d'accès.
        for ans in (answers(services=frozenset({"ntfy"})), supplied()):
            with self.subTest(tls=ans.tls):
                self.tearDown()
                self.setUp()
                done = self.run_script(ci.plan_install(base_facts(), ans, NOW))
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(
                    stat.S_IMODE(os.stat(self.path("/etc/ntfy")).st_mode),
                    0o755,
                )

    def test_an_existing_ntfy_config_dir_keeps_its_mode(self):
        os.makedirs(self.path("/etc/ntfy"))
        os.chmod(self.path("/etc/ntfy"), 0o750)
        ans = answers(services=frozenset({"ntfy"}))
        done = self.run_script(ci.plan_install(base_facts(), ans, NOW))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path("/etc/ntfy")).st_mode), 0o750
        )

    def test_back_to_http_removes_the_ntfy_certificate(self):
        for name in ("ntfy.crt", "ntfy.key"):
            write(self.path("/etc/ntfy/tls/" + name), "ancien\n", 0o640)
        ans = answers(services=frozenset({"ntfy"}))
        done = self.run_script(ci.plan_install(base_facts(), ans, NOW))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(os.listdir(self.path("/etc/ntfy/tls")), [])

    def test_supplied_certificate_placed_for_both(self):
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.read(os.path.join(self.log, "install_coturn.cert")), TURN_CERT
        )
        key = self.path("/etc/ntfy/tls/ntfy.key")
        self.assertEqual(self.read(key), TURN_KEY)
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o640)
        self.assertEqual(
            self.read(self.path("/etc/ntfy/tls/ntfy.crt")), TURN_CERT
        )
        calls = self.read(os.path.join(self.log, "calls"))
        self.assertIn("chown root:ntfy " + key, calls)
        ntfy = self.env_of("install_ntfy")
        self.assertEqual(ntfy["NTFY_HTTPS_PORT"], "8443")
        self.assertEqual(ntfy["NTFY_CERT_FILE"], "/etc/ntfy/tls/ntfy.crt")

    def test_adopted_config_backed_up_before_the_installer(self):
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        write(self.path("/etc/turnserver.conf"), original, 0o640)
        facts = base_facts(
            coturn=service("/etc/turnserver.conf", original),
            busy_ports=(("udp", 3478, "turnserver"),),
        )
        plan = ci.plan_install(
            facts, answers(services=frozenset({"coturn"})), NOW
        )
        backup = "/etc/turnserver.conf.bak-" + STAMP
        done = self.run_script(plan, seen=(backup,))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.read(self.path(backup)), original)
        self.assertIn(
            self.path(backup),
            self.read(os.path.join(self.log, "install_coturn.seen")),
        )
        self.assertEqual(
            self.env_of("install_coturn")["TURN_GARDER_CONFIG"], "1"
        )
        state = json.loads(self.read(self.path(ci.STATE_PATH)))
        self.assertEqual(state["services"]["coturn"]["backup"], backup)

    def rerun_after_a_cut_backup(self, first_copy):
        # Le passage précédent a déposé sa fiche, dont la copie porte son
        # tampon, puis s'est arrêté avant ou après son `cp -p`.
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        old = "/etc/turnserver.conf.bak-20261029-080000"
        write(self.path("/etc/turnserver.conf"), original, 0o640)
        if first_copy is not None:
            write(self.path(old), first_copy, 0o640)
        pending = {
            "installed_by_tool": False,
            "adopted": True,
            "backup": old,
            "config": "/etc/turnserver.conf",
        }
        write(
            self.path(ci.PENDING_DIR + "/coturn.json"),
            json.dumps(pending),
            0o600,
        )
        facts = base_facts(
            coturn=service("/etc/turnserver.conf", original, pending=pending),
            busy_ports=(("udp", 3478, "turnserver"),),
        )
        plan = ci.plan_install(
            facts, answers(services=frozenset({"coturn"})), NOW
        )
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = json.loads(self.read(self.path(ci.STATE_PATH)))
        self.assertEqual(state["services"]["coturn"]["backup"], old)
        extra = self.path("/etc/turnserver.conf.bak-" + STAMP)
        if first_copy in (None, original):
            self.assertFalse(os.path.exists(extra))
        else:
            self.assertEqual(self.read(extra), original)
        return self.read(self.path(old)), original

    def test_rerun_copies_to_the_recorded_backup(self):
        copy, original = self.rerun_after_a_cut_backup(None)
        self.assertEqual(copy, original)

    def test_rerun_keeps_a_backup_already_written(self):
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        copy, _original = self.rerun_after_a_cut_backup(original)
        self.assertEqual(copy, original)

    def test_rerun_never_loses_a_config_remade_since(self):
        # La copie consignée garde l'original d'avant l'outil ; une
        # configuration refaite à la main depuis est copiée à part.
        copy, original = self.rerun_after_a_cut_backup("avant l'outil\n")
        self.assertEqual(copy, "avant l'outil\n")

    def test_a_config_without_its_package_is_moved_aside_after_the_copy(self):
        # pacman refuse d'installer un paquet dont un fichier existe déjà
        # sans propriétaire : la configuration étrangère sans paquet quitte
        # sa place une fois copiée, et l'installateur la remplace.
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        write(self.path("/etc/turnserver/turnserver.conf"), original, 0o640)
        current = service("/etc/turnserver/turnserver.conf", original)
        current.update(unit="turnserver", unit_found=False, active="inactive")
        facts = base_facts(family="arch", os_id="arch", coturn=current)
        plan = ci.plan_install(
            facts, answers(services=frozenset({"coturn"})), NOW
        )
        record = plan.new_state["services"]["coturn"]
        self.assertTrue(record["installed_by_tool"] and record["adopted"])
        done = self.run_script(plan, seen=("/etc/turnserver/turnserver.conf",))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        backup = "/etc/turnserver/turnserver.conf.bak-" + STAMP
        self.assertEqual(self.read(self.path(backup)), original)
        self.assertFalse(
            os.path.exists(os.path.join(self.log, "install_coturn.seen"))
        )
        self.assertEqual(
            self.env_of("install_coturn")["TURN_GARDER_CONFIG"], "1"
        )

    def assert_no_state(self, done):
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH + ".new")))

    def test_failed_installer_leaves_no_state(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        done = self.run_script(plan, RC_install_coturn="1")
        self.assert_no_state(done)
        self.assertEqual(ci.marker_lines(done.stdout)[-1], ("SAVED", "no"))
        pending = json.loads(
            self.read(self.path("/etc/erplibre-call/pending/coturn.json"))
        )
        self.assertTrue(pending["installed_by_tool"])

    def test_inactive_service_leaves_no_state(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        done = self.run_script(plan, ACTIVE_ntfy="failed")
        self.assert_no_state(done)
        self.assertIn(("ACTIVE", "ntfy failed"), ci.marker_lines(done.stdout))

    def test_connection_cut_mid_install_leaves_no_state(self):
        # La coupure de ssh tue le groupe du script pendant un installateur.
        plan = ci.plan_install(base_facts(), answers(), NOW)
        done = self.run_script(plan, KILL_AT="install_ntfy")
        self.assert_no_state(done)
        self.assertTrue(
            os.path.exists(self.path("/etc/erplibre-call/pending/ntfy.json"))
        )

    def test_pending_kept_from_the_first_attempt(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        first = {
            "installed_by_tool": True,
            "adopted": True,
            "backup": "/x.bak-1",
        }
        write(
            self.path("/etc/erplibre-call/pending/coturn.json"),
            json.dumps(first),
            0o600,
        )
        self.run_script(plan, RC_install_coturn="1")
        self.assertEqual(
            json.loads(
                self.read(self.path("/etc/erplibre-call/pending/coturn.json"))
            ),
            first,
        )


class TestStateAnswers(unittest.TestCase):
    def test_round_trip(self):
        ans = supplied(
            turn_port=3479, external_ip="198.51.100.7", ntfy_port=9443
        )
        plan = ci.plan_install(base_facts(), ans, NOW)
        back = ci.state_answers(ci.written_state(plan, STAMP))
        self.assertEqual(
            back, dataclasses.replace(ans, cert_pem=None, key_pem=None)
        )

    def test_settings_that_are_not_a_dict_are_ignored(self):
        state = installed_state(answers())
        for bad in ("texte", ["liste"], 3):
            with self.subTest(bad=bad):
                broken = json.loads(json.dumps(state))
                broken["services"]["coturn"]["settings"] = bad
                back = ci.state_answers(broken)
                self.assertEqual(back.turn_port, 3478)
                self.assertEqual(back.public_name, "turn.exemple.test")

    def test_coturn_only(self):
        ans = answers(services=frozenset({"coturn"}))
        plan = ci.plan_install(base_facts(), ans, NOW)
        back = ci.state_answers(plan.new_state)
        self.assertEqual(back.services, frozenset({"coturn"}))
        self.assertIsNone(back.ntfy_port)

    def test_unusable_states(self):
        for state in (
            None,
            [],
            {},
            {"version": 2, "services": {}},
            {"version": 1, "services": {}},
            {"version": 1, "services": {"coturn": "x"}},
        ):
            with self.subTest(state=state):
                self.assertIsNone(ci.state_answers(state))

    def test_malformed_record_beside_a_good_one_is_skipped(self):
        ans = answers(services=frozenset({"ntfy"}))
        state = ci.plan_install(base_facts(), ans, NOW).new_state
        state["services"]["coturn"] = "x"
        back = ci.state_answers(state)
        self.assertEqual(back.services, frozenset({"ntfy"}))
        self.assertEqual(back.public_name, "turn.exemple.test")


# Jeux de règles nftables inventés, au format de `nft list ruleset`.
NFT_ONE_DROP = """table inet filter {
	chain input {
		type filter hook input priority filter; policy drop;
		ct state established,related accept
		tcp dport 22 accept
	}
	chain forward {
		type filter hook forward priority filter; policy drop;
	}
	chain output {
		type filter hook output priority filter; policy accept;
	}
}
"""
NFT_TWO_DROPS = """table ip filter {
	chain INPUT {
		type filter hook input priority filter; policy drop;
		tcp dport 22 accept
	}
}
table ip6 filter {
	chain INPUT {
		type filter hook input priority filter; policy drop;
	}
}
"""
NFT_BRIDGE_DROP = (
    NFT_ONE_DROP
    + """table bridge pont {
	chain entree {
		type filter hook input priority filter; policy drop;
	}
}
"""
)
# `nft -a list ruleset` : la règle de l'outil (handle 7) à côté de celles de
# l'administrateur (ssh, 8080 sans commentaire) et d'une règle de l'outil
# sur un autre port (34780), que rien ne doit toucher.
NFT_HANDLES = """table inet filter { # handle 1
	chain input { # handle 2
		type filter hook input priority filter; policy drop;
		udp dport 3478 accept comment "erplibre-call coturn" # handle 7
		ct state established,related accept # handle 4
		tcp dport 22 accept # handle 5
		udp dport 34780 accept comment "erplibre-call coturn" # handle 8
		tcp dport 8080 accept # handle 9
	}
}
"""
# iptables-nft : la table « ip filter » et sa chaîne « INPUT » en drop,
# celles d'ip6tables laissées en accept. iptables-persistent recharge cette
# table entière, une règle nft native qui s'y trouve disparaîtrait.
NFT_IPTABLES_V4 = """table ip filter {
	chain INPUT {
		type filter hook input priority filter; policy drop;
		tcp dport 22 counter packets 0 bytes 0 accept
	}
}
table ip6 filter {
	chain INPUT {
		type filter hook input priority filter; policy accept;
	}
}
"""
NFT_INCLUDE = 'flush ruleset\ninclude "/etc/nftables.d/*.nft"\n'

UFW_ADDED = (
    "Added user rules (see 'ufw status' for running firewall):\n"
    "ufw allow 22/tcp\n"
    "ufw allow 8080/tcp\n"
    "ufw allow 3478/udp comment 'erplibre-call coturn'\n"
)
# Règles de l'administrateur sur les mêmes ports, qui ne diffèrent des
# nôtres que par l'action ou le journal : `ufw allow` les remplacerait
# (« Rule updated »).
UFW_ADDED_OTHER_ACTIONS = (
    "Added user rules (see 'ufw status' for running firewall):\n"
    "ufw deny 3478/udp\n"
    "ufw limit 8080/tcp\n"
    "ufw allow log 49152:49252/udp comment 'erplibre-call coturn'\n"
)


def rule(proto, port, svc):
    return ci.Rule(proto=proto, port=port, service=svc)


class TestFirewall(unittest.TestCase):
    """Règles d'ouverture, aperçu, scripts ufw et nftables (texte), notes
    et état du pare-feu."""

    HTTP_RULES = (
        rule("udp", "3478", "coturn"),
        rule("tcp", "3478", "coturn"),
        rule("udp", "49152:49252", "coturn"),
        rule("tcp", "8080", "ntfy"),
    )

    def test_rules_dev_http_have_no_turns_port(self):
        rules = ci.firewall_rules(answers())
        self.assertEqual(rules, self.HTTP_RULES)
        self.assertNotIn("5349", [r.port for r in rules])

    def test_rules_dev_supplied_open_turns(self):
        rules = ci.firewall_rules(supplied())
        self.assertEqual(
            rules,
            (
                rule("udp", "3478", "coturn"),
                rule("tcp", "3478", "coturn"),
                rule("tcp", "5349", "coturn"),
                rule("udp", "49152:49252", "coturn"),
                rule("tcp", "8443", "ntfy"),
            ),
        )

    def test_rules_follow_the_chosen_services_and_ports(self):
        only_ntfy = answers(services=frozenset({"ntfy"}), ntfy_port=9090)
        self.assertEqual(
            ci.firewall_rules(only_ntfy), (rule("tcp", "9090", "ntfy"),)
        )
        same = answers(
            services=frozenset({"coturn"}), min_port=50000, max_port=50000
        )
        self.assertIn(rule("udp", "50000", "coturn"), ci.firewall_rules(same))

    def test_no_rule_on_the_ssh_port(self):
        for changes in (
            {"min_port": 10, "max_port": 30},
            {"turn_port": 22},
            {"services": frozenset({"ntfy"}), "ntfy_port": 22},
        ):
            with self.subTest(changes=changes):
                ans = answers(**changes)
                with self.assertRaises(ci.Refusal) as caught:
                    ci.firewall_rules(ans)
                self.assertEqual(caught.exception.key, "call_infra_bad_value")
                with self.assertRaises(ci.Refusal):
                    ci.plan_install(base_facts(busy_ports=()), ans, NOW)
        for bad in (rule("tcp", "22", "ntfy"), rule("udp", "1:100", "coturn")):
            for kind in ("ufw", "nftables"):
                with self.subTest(rule=bad, kind=kind):
                    with self.assertRaises(ValueError):
                        ci.firewall_script(kind, [bad], "allow")

    def test_rules_from_the_state_are_checked(self):
        state = {
            "firewall": {
                "kind": "ufw",
                "rules": [
                    ["udp", "3478", "coturn"],
                    ["tcp", "3478; reboot", "coturn"],
                    ["tcp", "22", "ntfy"],
                    ["icmp", "8", "ntfy"],
                    ["tcp", "8080", "autre"],
                    ["udp", "49252:49152", "coturn"],
                    "x",
                    ["tcp", "8080"],
                ],
                "persisted": True,
            }
        }
        self.assertEqual(
            ci.rules_from_state(state), (rule("udp", "3478", "coturn"),)
        )
        self.assertEqual(ci.rules_from_state({}), ())
        self.assertEqual(ci.rules_from_state(None), ())
        with self.assertRaises(ValueError):
            ci.firewall_script(
                "ufw", [rule("tcp", "3478; reboot", "coturn")], "allow"
            )

    def test_ufw_preview_is_exact(self):
        self.assertEqual(
            ci.firewall_preview("ufw", self.HTTP_RULES),
            [
                "ufw allow 3478/udp comment 'erplibre-call coturn'",
                "ufw allow 3478/tcp comment 'erplibre-call coturn'",
                "ufw allow 49152:49252/udp comment 'erplibre-call coturn'",
                "ufw allow 8080/tcp comment 'erplibre-call ntfy'",
            ],
        )

    def test_nftables_preview_names_the_chain(self):
        self.assertEqual(
            ci.firewall_preview(
                "nftables", self.HTTP_RULES[2:], ("inet", "filter", "input")
            ),
            [
                "nft insert rule inet filter input udp dport 49152-49252"
                ' accept comment "erplibre-call coturn"',
                "nft insert rule inet filter input tcp dport 8080"
                ' accept comment "erplibre-call ntfy"',
            ],
        )
        self.assertEqual(ci.firewall_preview("nftables", self.HTTP_RULES), [])
        for kind in ("none", "unknown"):
            self.assertEqual(ci.firewall_preview(kind, self.HTTP_RULES), [])

    def test_nftables_script_never_flushes_nor_opens_ssh(self):
        rules = ci.firewall_rules(supplied())
        for action in ("allow", "delete"):
            script = ci.firewall_script("nftables", rules, action)
            with self.subTest(action=action):
                self.assertNotIn("flush", script)
                self.assertNotIn("policy accept", script)
                self.assertNotIn("policy", script.replace("policy drop", ""))
                self.assertNotIn("22", script)
        allow = ci.firewall_script("nftables", rules, "allow")
        self.assertIn("@@FIREWALL_MANUAL", allow)

    def test_ufw_script_never_enables(self):
        rules = ci.firewall_rules(supplied())
        for action in ("allow", "delete"):
            script = ci.firewall_script("ufw", rules, action)
            with self.subTest(action=action):
                self.assertNotIn("enable", script)
                self.assertNotIn("default", script)
                self.assertNotIn("22", script)
                self.assertNotIn("reset", script)

    def test_no_firewall_gives_an_empty_script_and_no_rule(self):
        rules = ci.firewall_rules(answers())
        for kind in ("none", "unknown"):
            with self.subTest(kind=kind):
                self.assertEqual(ci.firewall_script(kind, rules, "allow"), "")
                self.assertEqual(ci.firewall_script(kind, rules, "delete"), "")
                record = ci.firewall_record(kind, "")
                self.assertEqual(
                    record, {"kind": kind, "rules": [], "persisted": False}
                )
                state = ci.with_firewall({"version": 1}, record)
                self.assertEqual(ci.rules_from_state(state), ())

    def test_bad_kind_or_action(self):
        with self.assertRaises(ValueError):
            ci.firewall_script("firewalld", self.HTTP_RULES, "allow")
        with self.assertRaises(ValueError):
            ci.firewall_script("ufw", self.HTTP_RULES, "enable")
        with self.assertRaises(ValueError):
            ci.firewall_preview("iptables", self.HTTP_RULES)

    def test_cloud_reminder_for_every_kind(self):
        for kind in ci.FIREWALLS:
            with self.subTest(kind=kind):
                notes = ci.firewall_notes(kind)
                self.assertIn("call_infra_cloud_firewall", notes)
        self.assertIn("call_infra_firewall_none", ci.firewall_notes("none"))
        self.assertIn(
            "call_infra_firewall_unknown", ci.firewall_notes("unknown")
        )
        self.assertEqual(
            ci.firewall_notes("ufw"), ["call_infra_cloud_firewall"]
        )

    def test_record_keeps_only_the_tool_rules(self):
        output = (
            "@@FIREWALL_ADDED udp 3478 coturn\n"
            "@@FIREWALL_KEPT tcp 3478 coturn\n"
            "@@FIREWALL_FOREIGN tcp 8080 ntfy\n"
            "@@FIREWALL_FAILED udp 49152:49252 coturn\n"
            "@@FIREWALL_PERSISTED yes\n"
            "@@END\n"
        )
        self.assertEqual(
            ci.firewall_record("ufw", output),
            {
                "kind": "ufw",
                "rules": [
                    ["tcp", "3478", "coturn"],
                    ["udp", "3478", "coturn"],
                ],
                "persisted": True,
            },
        )

    def test_record_merges_with_the_previous_one(self):
        previous = {
            "kind": "nftables",
            "rules": [["tcp", "8080", "ntfy"]],
            "persisted": True,
        }
        added = ci.firewall_record(
            "nftables",
            "@@FIREWALL_CHAIN inet filter input\n"
            "@@FIREWALL_ADDED udp 3478 coturn\n"
            "@@FIREWALL_RUNTIME_ONLY\n@@END\n",
            previous,
        )
        self.assertEqual(
            added["rules"],
            [["tcp", "8080", "ntfy"], ["udp", "3478", "coturn"]],
        )
        self.assertFalse(added["persisted"])
        removed = ci.firewall_record(
            "nftables",
            "@@FIREWALL_REMOVED tcp 8080 ntfy\n"
            "@@FIREWALL_ABSENT udp 3478 coturn\n@@END\n",
            added,
        )
        self.assertEqual(removed["rules"], [])
        manual = ci.firewall_record(
            "nftables", "@@FIREWALL_MANUAL 2\n@@END\n", previous
        )
        self.assertEqual(manual, previous)
        other_kind = ci.firewall_record(
            "ufw", "@@FIREWALL_ADDED udp 3478 coturn\n@@END\n", previous
        )
        self.assertEqual(other_kind["rules"], [["udp", "3478", "coturn"]])

    def test_firewall_survives_a_rerun_of_the_plan(self):
        record = ci.firewall_record(
            "ufw", "@@FIREWALL_ADDED udp 3478 coturn\n@@END\n"
        )
        state = ci.with_firewall(
            ci.plan_install(base_facts(), answers(), NOW).new_state, record
        )
        again = ci.plan_install(base_facts(state=state), answers(), NOW)
        self.assertEqual(again.new_state["firewall"], record)

    def test_parse_probe_reads_the_nftables_chains(self):
        probe = DEBIAN_PROBE.replace(
            "@@FIREWALL none\n",
            "@@FIREWALL nftables\n@@NFT_INPUT inet filter input\n"
            "@@NFT_INPUT ip filter IN PUT\n",
        )
        facts = ci.parse_probe(probe)
        self.assertEqual(facts.firewall, "nftables")
        self.assertEqual(facts.nft_chains, (("inet", "filter", "input"),))
        self.assertEqual(ci.parse_probe(DEBIAN_PROBE).nft_chains, ())


class TestPendingFirewall(unittest.TestCase):
    PENDING = (
        ("ufw", rule("udp", "3478", "coturn")),
        ("nftables", rule("tcp", "8080", "ntfy")),
    )

    def test_record_merges_the_pending_rules_of_its_kind(self):
        record = ci.firewall_record("ufw", "", None, self.PENDING)
        self.assertEqual(record["rules"], [["udp", "3478", "coturn"]])

    def test_uninstall_state_carries_the_pending_rules(self):
        state = installed_state(firewall=ufw_record("udp 49152:49252 coturn"))
        merged = ci.merge_pending_firewall(state, self.PENDING)
        self.assertEqual(
            set(ci.rules_from_state(merged)),
            {
                rule("udp", "3478", "coturn"),
                rule("udp", "49152:49252", "coturn"),
            },
        )
        self.assertEqual(
            ci.rules_from_state(state), (rule("udp", "49152:49252", "coturn"),)
        )
        bare = ci.merge_pending_firewall(installed_state(), self.PENDING[1:])
        self.assertEqual(bare["firewall"]["kind"], "nftables")
        self.assertIs(ci.merge_pending_firewall(None, self.PENDING), None)

    def test_firewall_missing(self):
        ans = answers()
        full = ci.firewall_record(
            "ufw",
            "".join(
                f"@@FIREWALL_ADDED {r.proto} {r.port} {r.service}\n"
                for r in ci.firewall_rules(ans)
            ),
        )
        recorded = base_facts(
            firewall="ufw", state=installed_state(ans, firewall=full)
        )
        self.assertFalse(ci.firewall_missing(recorded, ans))
        bare = base_facts(firewall="ufw", state=installed_state(ans))
        self.assertTrue(ci.firewall_missing(bare, ans))
        pending = dataclasses.replace(
            recorded, firewall_pending=self.PENDING[:1]
        )
        self.assertTrue(ci.firewall_missing(pending, ans))
        for kind in ("none", "unknown"):
            self.assertFalse(
                ci.firewall_missing(
                    dataclasses.replace(bare, firewall=kind), ans
                )
            )
        # nftables sans chaîne unique : rien à proposer.
        self.assertFalse(
            ci.firewall_missing(
                dataclasses.replace(bare, firewall="nftables"), ans
            )
        )

    def test_a_port_the_admin_already_opens_is_not_missing(self):
        # Une règle de l'administrateur couvre le port (FOREIGN) : jamais
        # consignée, elle ne fait pas reposer la question à chaque relance.
        ans = answers()
        rules = ci.firewall_rules(ans)
        theirs = tuple(
            f"ufw {action} {r.port}/{r.proto}"
            for action, r in zip(("allow", "limit", "deny") * 9, rules)
        )
        bare = base_facts(
            firewall="ufw", state=installed_state(ans), ufw_added=theirs
        )
        self.assertFalse(ci.firewall_missing(bare, ans))
        self.assertEqual(ci.rules_from_state(bare.state), ())
        # Une seule règle non couverte suffit à proposer le pare-feu.
        self.assertTrue(
            ci.firewall_missing(
                dataclasses.replace(bare, ufw_added=theirs[1:]), ans
            )
        )
        # La ligne exacte de l'outil, non consignée, reste à consigner.
        ours = tuple(ci.firewall_preview("ufw", rules))
        self.assertTrue(
            ci.firewall_missing(dataclasses.replace(bare, ufw_added=ours), ans)
        )
        # Un port voisin ne couvre pas le nôtre.
        near = tuple(f"ufw allow {r.port}0/{r.proto}" for r in rules)
        self.assertTrue(
            ci.firewall_missing(dataclasses.replace(bare, ufw_added=near), ans)
        )
        # Les lignes de ufw ne comptent que pour ufw.
        nft = dataclasses.replace(
            bare,
            firewall="nftables",
            nft_chains=(("inet", "filter", "input"),),
        )
        self.assertTrue(ci.firewall_missing(nft, ans))


class TestAdminAdded(unittest.TestCase):
    def adopted_ntfy_state(self):
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, NTFY_FOREIGN, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        ans = answers(services=frozenset({"ntfy"}))
        return facts, ans, installed_state(ans, facts=facts)

    def test_the_admin_created_in_an_adopted_ntfy_is_recorded(self):
        _facts, _ans, state = self.adopted_ntfy_state()
        out = "@@ADMIN_PASSWORD Ab1\n@@SAVED yes\n"
        marked = ci.mark_admin_added(state, out)
        self.assertIs(marked["services"]["ntfy"]["admin_added"], True)
        self.assertNotIn("admin_added", state["services"]["ntfy"])
        self.assertEqual(ci.mark_admin_added(state, "@@SAVED yes\n"), state)
        # Un ntfy posé par l'outil part en entier, base des comptes avec.
        tool = installed_state(answers(services=frozenset({"ntfy"})))
        self.assertEqual(ci.mark_admin_added(tool, out), tool)

    def test_a_rerun_keeps_the_record(self):
        facts, ans, state = self.adopted_ntfy_state()
        marked = ci.mark_admin_added(state, "@@ADMIN_PASSWORD Ab1\n")
        managed = service(
            ci.NTFY_CONFIG, ci.ntfy_config(ans, NTFY_FOREIGN), unit="ntfy"
        )
        again = ci.plan_install(
            dataclasses.replace(facts, ntfy=managed, state=marked), ans, NOW
        )
        self.assertIs(again.new_state["services"]["ntfy"]["admin_added"], True)


class TestFirewallRun(unittest.TestCase):
    """Scripts du pare-feu joués pour de vrai : `nft` et `ufw` sont des
    bouchons qui notent leurs appels, la racine est un dossier temporaire."""

    RULES = (
        rule("udp", "3478", "coturn"),
        rule("udp", "49152:49252", "coturn"),
        rule("tcp", "8080", "ntfy"),
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        self.root = os.path.join(base, "root")
        self.stubs = os.path.join(base, "stubs")
        self.log = os.path.join(base, "log")
        os.makedirs(self.root)
        write(
            os.path.join(self.stubs, "nft"),
            "#!/bin/sh\n"
            'echo "$*" >> "$LOG"\n'
            'case "$*" in\n'
            '  "list ruleset") cat "$RULESET" ;;\n'
            '  "-a list ruleset") cat "$HANDLES" ;;\n'
            '  "-f "*) cat "$2" >> "$LOG.f"; exit "${NFT_F_RC:-0}" ;;\n'
            '  "-c -f "*) exit "${NFT_C_RC:-0}" ;;\n'
            '  "delete rule "*) exit 0 ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n",
        )
        write(
            os.path.join(self.stubs, "ufw"),
            "#!/bin/sh\n"
            'echo "$*" >> "$LOG"\n'
            'case "$1 $2" in\n'
            '  "show added") cat "$ADDED" ;;\n'
            '  "allow "*) echo "${UFW_ALLOW_OUT:-Rule added}" ;;\n'
            '  "delete allow") echo "Rule deleted" ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n",
        )

    def run_script(self, script, ruleset="", handles="", added="", **env):
        files = {}
        for name, text in (
            ("RULESET", ruleset),
            ("HANDLES", handles),
            ("ADDED", added),
        ):
            files[name] = os.path.join(self.tmp.name, name.lower())
            write(files[name], text, 0o644)
        full = dict(
            os.environ,
            PATH=self.stubs + ":" + os.environ["PATH"],
            LOG=self.log,
            TMPDIR=self.tmp.name,
            **files,
            **env,
        )
        return subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            env=full,
            timeout=30,
        )

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return handle.read().splitlines()

    def applied(self):
        path = self.log + ".f"
        if not os.path.exists(path):
            return ""
        with open(path) as handle:
            return handle.read()

    def markers(self, done):
        return [
            f"{name} {value}".strip()
            for name, value in ci.marker_lines(done.stdout)
        ]

    def nft(self, action="allow"):
        return ci.firewall_script(
            "nftables", self.RULES, action, root=self.root
        )

    def test_two_drop_input_chains_change_nothing(self):
        done = self.run_script(self.nft(), ruleset=NFT_TWO_DROPS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("FIREWALL_MANUAL 2", self.markers(done))
        self.assertEqual(self.calls(), ["list ruleset"])
        self.assertEqual(self.applied(), "")
        record = ci.firewall_record("nftables", done.stdout)
        self.assertEqual(record["rules"], [])

    def test_no_drop_input_chain_changes_nothing(self):
        ruleset = NFT_ONE_DROP.replace(
            "hook input priority filter; policy drop",
            "hook input priority filter; policy accept",
        )
        done = self.run_script(self.nft(), ruleset=ruleset)
        self.assertIn("FIREWALL_MANUAL 0", self.markers(done))
        self.assertEqual(self.calls(), ["list ruleset"])

    def test_an_unexpected_chain_name_changes_nothing(self):
        ruleset = NFT_ONE_DROP.replace("table inet filter", "table inet f;x")
        done = self.run_script(self.nft(), ruleset=ruleset)
        self.assertIn("FIREWALL_MANUAL 1", self.markers(done))
        self.assertEqual(self.calls(), ["list ruleset"])

    def test_an_iptables_nft_chain_changes_nothing(self):
        done = self.run_script(self.nft(), ruleset=NFT_IPTABLES_V4)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("FIREWALL_MANUAL 1", self.markers(done))
        self.assertEqual(self.calls(), ["list ruleset"])
        self.assertEqual(self.applied(), "")

    def test_a_bridge_chain_is_not_an_input_chain(self):
        done = self.run_script(self.nft(), ruleset=NFT_BRIDGE_DROP)
        self.assertIn("FIREWALL_CHAIN inet filter input", self.markers(done))

    def test_rules_inserted_in_the_drop_chain_runtime_only(self):
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self.applied().splitlines(),
            [
                "insert rule inet filter input udp dport 3478 accept"
                ' comment "erplibre-call coturn"',
                "insert rule inet filter input udp dport 49152-49252 accept"
                ' comment "erplibre-call coturn"',
                "insert rule inet filter input tcp dport 8080 accept"
                ' comment "erplibre-call ntfy"',
            ],
        )
        markers = self.markers(done)
        self.assertIn("FIREWALL_ADDED udp 49152:49252 coturn", markers)
        self.assertIn("FIREWALL_RUNTIME_ONLY", markers)
        self.assertEqual(markers[-1], "END")
        self.assertNotIn("delete", " ".join(self.calls()))
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "etc/nftables.d"))
        )
        record = ci.firewall_record("nftables", done.stdout)
        self.assertEqual(len(record["rules"]), 3)
        self.assertFalse(record["persisted"])

    def test_a_failed_insert_records_nothing(self):
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP, NFT_F_RC="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("FIREWALL_FAILED tcp 8080 ntfy", self.markers(done))
        self.assertEqual(
            ci.firewall_record("nftables", done.stdout)["rules"], []
        )

    def test_rules_already_there_are_kept_not_doubled(self):
        done = self.run_script(
            self.nft(), ruleset=NFT_ONE_DROP, handles=NFT_HANDLES
        )
        markers = self.markers(done)
        self.assertIn("FIREWALL_KEPT udp 3478 coturn", markers)
        self.assertIn("FIREWALL_ADDED tcp 8080 ntfy", markers)
        self.assertNotIn("dport 3478 ", self.applied())

    def test_persisted_when_the_conf_includes_the_directory(self):
        write(os.path.join(self.root, "etc/nftables.conf"), NFT_INCLUDE, 0o644)
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP)
        self.assertIn("FIREWALL_PERSISTED yes", self.markers(done))
        path = os.path.join(self.root, "etc/nftables.d/erplibre-call.nft")
        with open(path) as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines[0], ci.MARKER)
        self.assertEqual(lines[1:], self.applied().splitlines())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)
        self.assertIn(
            "-c -f " + os.path.join(self.root, "etc/nftables.conf"),
            self.calls(),
        )
        self.assertTrue(
            ci.firewall_record("nftables", done.stdout)["persisted"]
        )
        # Une relance n'ajoute aucune ligne au fichier.
        again = self.run_script(
            self.nft(), ruleset=NFT_ONE_DROP, handles=NFT_HANDLES
        )
        self.assertIn("FIREWALL_PERSISTED yes", self.markers(again))
        with open(path) as handle:
            self.assertEqual(handle.read().splitlines(), lines)

    def test_a_conf_that_no_longer_loads_is_not_persisted(self):
        write(os.path.join(self.root, "etc/nftables.conf"), NFT_INCLUDE, 0o644)
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP, NFT_C_RC="1")
        self.assertIn("FIREWALL_RUNTIME_ONLY check", self.markers(done))
        self.assertFalse(
            os.path.exists(
                os.path.join(self.root, "etc/nftables.d/erplibre-call.nft")
            )
        )

    def test_a_conf_without_the_include_is_not_persisted(self):
        write(
            os.path.join(self.root, "etc/nftables.conf"),
            'include "/etc/nftables.d/*.conf"\n',
            0o644,
        )
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP)
        self.assertIn("FIREWALL_RUNTIME_ONLY", self.markers(done))
        self.assertNotIn("-c -f", " ".join(self.calls()))

    def test_delete_by_handle_of_the_tool_rule_only(self):
        path = os.path.join(self.root, "etc/nftables.d/erplibre-call.nft")
        mine = (
            "insert rule inet filter input udp dport 3478 accept"
            ' comment "erplibre-call coturn"'
        )
        write(path, ci.MARKER + "\n" + mine + "\n", 0o644)
        done = self.run_script(self.nft("delete"), handles=NFT_HANDLES)
        self.assertEqual(done.returncode, 0, done.stderr)
        deletes = [c for c in self.calls() if c.startswith("delete")]
        self.assertEqual(deletes, ["delete rule inet filter input handle 7"])
        markers = self.markers(done)
        self.assertIn("FIREWALL_REMOVED udp 3478 coturn", markers)
        self.assertIn("FIREWALL_ABSENT tcp 8080 ntfy", markers)
        self.assertFalse(os.path.exists(path))
        self.assertNotIn("list ruleset", self.calls())

    def test_delete_keeps_the_other_persisted_lines(self):
        path = os.path.join(self.root, "etc/nftables.d/erplibre-call.nft")
        other = (
            "insert rule inet filter input tcp dport 9443 accept"
            ' comment "erplibre-call ntfy"'
        )
        write(path, ci.MARKER + "\n" + other + "\n", 0o644)
        self.run_script(self.nft("delete"), handles=NFT_HANDLES)
        with open(path) as handle:
            self.assertEqual(handle.read(), ci.MARKER + "\n" + other + "\n")

    def test_ufw_allow_skips_a_rule_the_user_already_has(self):
        script = ci.firewall_script("ufw", self.RULES, "allow", root=self.root)
        done = self.run_script(script, added=UFW_ADDED)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self.calls(),
            [
                "show added",
                "allow 49152:49252/udp comment erplibre-call coturn",
            ],
        )
        markers = self.markers(done)
        self.assertIn("FIREWALL_KEPT udp 3478 coturn", markers)
        self.assertIn("FIREWALL_ADDED udp 49152:49252 coturn", markers)
        self.assertIn("FIREWALL_FOREIGN tcp 8080 ntfy", markers)
        self.assertEqual(
            ci.firewall_record("ufw", done.stdout)["rules"],
            [["udp", "3478", "coturn"], ["udp", "49152:49252", "coturn"]],
        )

    def test_ufw_allow_never_rewrites_another_action_on_the_port(self):
        script = ci.firewall_script("ufw", self.RULES, "allow", root=self.root)
        done = self.run_script(script, added=UFW_ADDED_OTHER_ACTIONS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), ["show added"])
        markers = self.markers(done)
        for r in self.RULES:
            self.assertIn(
                f"FIREWALL_FOREIGN {r.proto} {r.port} {r.service}", markers
            )
        self.assertEqual(ci.firewall_record("ufw", done.stdout)["rules"], [])

    def test_ufw_delete_leaves_another_action_on_the_port(self):
        script = ci.firewall_script(
            "ufw", self.RULES, "delete", root=self.root
        )
        done = self.run_script(script, added=UFW_ADDED_OTHER_ACTIONS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), ["show added"])
        self.assertIn(
            "FIREWALL_FOREIGN udp 49152:49252 coturn", self.markers(done)
        )

    def test_ufw_rule_updated_is_never_recorded(self):
        script = ci.firewall_script("ufw", self.RULES, "allow", root=self.root)
        done = self.run_script(
            script,
            added=UFW_ADDED.split("\n", 1)[0] + "\n",
            UFW_ALLOW_OUT="Rule updated\nRule updated (v6)",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        markers = self.markers(done)
        self.assertIn("FIREWALL_FOREIGN udp 3478 coturn", markers)
        self.assertNotIn("FIREWALL_ADDED udp 3478 coturn", markers)
        self.assertEqual(ci.firewall_record("ufw", done.stdout)["rules"], [])

    def test_ufw_delete_only_removes_the_tool_rules(self):
        script = ci.firewall_script(
            "ufw", self.RULES, "delete", root=self.root
        )
        done = self.run_script(script, added=UFW_ADDED)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), ["show added", "delete allow 3478/udp"])
        markers = self.markers(done)
        self.assertIn("FIREWALL_REMOVED udp 3478 coturn", markers)
        self.assertIn("FIREWALL_ABSENT udp 49152:49252 coturn", markers)
        self.assertIn("FIREWALL_FOREIGN tcp 8080 ntfy", markers)

    def test_ufw_reply_read_in_english_whatever_the_locale(self):
        write(
            os.path.join(self.stubs, "ufw"),
            "#!/bin/sh\n"
            'case "$1 $2" in\n'
            '  "show added") cat "$ADDED" ;;\n'
            '  "allow "*) if %s; then echo "Skipping adding existing rule";'
            ' else echo "Saut de la règle existante"; fi ;;\n'
            "  *) exit 1 ;;\n"
            "esac\n" % IN_C,
        )
        script = ci.firewall_script(
            "ufw", self.RULES[:1], "allow", root=self.root
        )
        done = self.run_script(script, **FRENCH)
        self.assertIn("FIREWALL_FOREIGN udp 3478 coturn", self.markers(done))

    def pending_firewall(self):
        path = os.path.join(self.root, ci.PENDING_DIR.lstrip("/"), "firewall")
        if not os.path.exists(path):
            return None
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path) as handle:
            return sorted(set(handle.read().splitlines()))

    def test_ufw_rules_are_recorded_in_the_run_that_adds_them(self):
        # Un enregistrement de l'état raté ensuite ne les perd pas : la
        # sonde suivante relit cette fiche.
        script = ci.firewall_script("ufw", self.RULES, "allow", root=self.root)
        done = self.run_script(script, added=UFW_ADDED)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self.pending_firewall(),
            ["ufw udp 3478 coturn", "ufw udp 49152:49252 coturn"],
        )

    def test_nft_rules_are_recorded_in_the_run_that_adds_them(self):
        done = self.run_script(
            self.nft(), ruleset=NFT_ONE_DROP, handles=NFT_HANDLES
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            self.pending_firewall(),
            [
                "nftables tcp 8080 ntfy",
                "nftables udp 3478 coturn",
                "nftables udp 49152:49252 coturn",
            ],
        )

    def test_a_failed_nft_insert_records_no_pending_rule(self):
        done = self.run_script(self.nft(), ruleset=NFT_ONE_DROP, NFT_F_RC="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIsNone(self.pending_firewall())

    def test_state_write_clears_the_pending_rules(self):
        write(
            os.path.join(self.root, ci.PENDING_DIR.lstrip("/"), "firewall"),
            "ufw udp 3478 coturn\n",
            0o600,
        )
        write(os.path.join(self.stubs, "chown"), "#!/bin/sh\nexit 0\n")
        done = self.run_script(
            ci.state_write_script({"version": 1}, root=self.root)
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNone(self.pending_firewall())

    def test_probe_reads_the_pending_rules(self):
        write(
            os.path.join(self.root, ci.PENDING_DIR.lstrip("/"), "firewall"),
            "ufw udp 3478 coturn\nufw udp 3478 coturn\nufw tcp 22 ntfy\n"
            "nftables tcp 8080 ntfy\n",
            0o600,
        )
        for name in ("systemctl", "ss", "ip", "iptables", "nft", "ufw"):
            write(os.path.join(self.stubs, name), "#!/bin/sh\nexit 1\n")
        done = self.run_script(ci.probe_script(root=self.root))
        facts = ci.parse_probe(done.stdout)
        # Une règle sur le port de ssh est écartée, une répétée compte une
        # fois.
        self.assertEqual(
            facts.firewall_pending,
            (
                ("ufw", rule("udp", "3478", "coturn")),
                ("nftables", rule("tcp", "8080", "ntfy")),
            ),
        )

    def test_state_write_script(self):
        state = {"version": 1, "firewall": {"kind": "ufw", "rules": []}}
        write(os.path.join(self.stubs, "chown"), "#!/bin/sh\nexit 0\n")
        done = self.run_script(ci.state_write_script(state, root=self.root))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("SAVED yes", self.markers(done))
        path = os.path.join(self.root, ci.STATE_PATH.lstrip("/"))
        with open(path) as handle:
            self.assertEqual(json.load(handle), state)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertFalse(os.path.exists(path + ".new"))

    def test_probe_lists_the_drop_input_chains(self):
        script = ci.probe_script(root=self.root)
        for name in ("systemctl", "ss", "ip", "iptables"):
            write(os.path.join(self.stubs, name), "#!/bin/sh\nexit 1\n")
        write(os.path.join(self.stubs, "ufw"), "#!/bin/sh\nexit 1\n")
        done = self.run_script(script, ruleset=NFT_BRIDGE_DROP)
        facts = ci.parse_probe(done.stdout)
        self.assertEqual(facts.firewall, "nftables")
        self.assertEqual(facts.nft_chains, (("inet", "filter", "input"),))

    def test_probe_calls_an_iptables_nft_drop_unknown(self):
        script = ci.probe_script(root=self.root)
        for name in ("systemctl", "ss", "ip", "iptables"):
            write(os.path.join(self.stubs, name), "#!/bin/sh\nexit 1\n")
        write(os.path.join(self.stubs, "ufw"), "#!/bin/sh\nexit 1\n")
        done = self.run_script(script, ruleset=NFT_IPTABLES_V4)
        facts = ci.parse_probe(done.stdout)
        self.assertEqual(facts.firewall, "unknown")
        self.assertEqual(facts.nft_chains, ())


# --- Vérification et désinstallation ----------------------------------------

CHECK_KEY = "0123456789abcdef0123456789abcdef"
RELAYED = ("192.0.2.10", 50000)
HOST = "192.0.2.10"


def installed_state(ans=None, facts=None, firewall=None):
    """L'état qu'écrit une installation réussie de `ans`."""
    plan = ci.plan_install(facts or base_facts(), ans or answers(), NOW)
    state = ci.written_state(plan, STAMP)
    if firewall is not None:
        state = ci.with_firewall(state, firewall)
    return state


def ufw_record(*specs):
    """`state["firewall"]` d'un ufw où l'outil a posé `specs`
    (« udp 3478 coturn »)."""
    output = "".join(f"@@FIREWALL_ADDED {s}\n" for s in specs) + "@@END\n"
    return ci.firewall_record("ufw", output)


HTTP_RULES = (
    "udp 3478 coturn",
    "tcp 3478 coturn",
    "udp 49152:49252 coturn",
    "tcp 8080 ntfy",
)


def remote_output(state, active=None, key=CHECK_KEY, rules=(), certs=None):
    """Sortie de `check_remote_script` sur un hôte inventé."""
    lines = [""]
    if state is not None:
        lines.append("@@STATE " + b64(json.dumps(state)))
    for svc, value in (active or {}).items():
        lines.append(f"@@ACTIVE {svc} {value}")
    if key:
        lines.append("@@CHECK_KEY " + key)
    lines += ["@@FIREWALL_RULE " + r for r in rules]
    for svc, pem in (certs or {}).items():
        lines.append(f"@@CERT {svc} {b64(pem)}")
    lines.append("@@END")
    return "\n".join(lines) + "\n"


class FakeAllocate:
    """`turn_client.allocate` qui note ses appels et répond par transport."""

    def __init__(self, **results):
        self.results = results
        self.calls = []

    def __call__(
        self,
        host,
        port,
        transport,
        username,
        key,
        timeout=5.0,
        cafile=None,
        server_name=None,
    ):
        self.calls.append(
            dict(
                host=host,
                port=port,
                transport=transport,
                username=username,
                key=key,
                cafile=cafile,
                server_name=server_name,
            )
        )
        return self.results.get(transport, tc.Allocation(True, RELAYED, None))


class FakeGet:
    """`https_get` qui note ses appels ; `result` est rendu ou levé."""

    def __init__(self, result=(200, '{"healthy":true}\n')):
        self.result = result
        self.calls = []

    def __call__(
        self, address, port, path, tls, server_name=None, cafile=None, **kw
    ):
        self.calls.append(
            dict(
                address=address,
                port=port,
                path=path,
                tls=tls,
                server_name=server_name,
                cafile=cafile,
            )
        )
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def by_name(lines):
    return {line.name: line for line in lines}


class TestCheck(unittest.TestCase):
    def check(
        self,
        state,
        active=None,
        key=CHECK_KEY,
        rules=(),
        certs=None,
        allocate=None,
        get=None,
        cafile=None,
        now=None,
    ):
        if active is None:
            active = {"coturn": "active", "ntfy": "active"}
        facts = ci.parse_check_remote(
            remote_output(state, active, key, rules, certs)
        )
        self.allocate = allocate or FakeAllocate()
        self.get = get or FakeGet()
        return ci.check_local(
            facts,
            HOST,
            cafile,
            allocate=self.allocate,
            https_get=self.get,
            now=now or NOW,
        )

    def http_state(self):
        return installed_state(firewall=ufw_record(*HTTP_RULES))

    def test_everything_answers_in_http(self):
        lines = self.check(
            self.http_state(), rules=["ufw " + r for r in HTTP_RULES]
        )
        self.assertEqual(
            [line.name for line in lines],
            [
                "turn-udp",
                "turn-tcp",
                "ntfy-health",
                "firewall",
                "service-coturn",
                "service-ntfy",
            ],
        )
        for line in lines:
            self.assertIs(line.ok, True, line)
        self.assertEqual(
            by_name(lines)["turn-udp"].values, {"relayed": "192.0.2.10:50000"}
        )
        self.assertEqual(
            [(c["transport"], c["port"]) for c in self.allocate.calls],
            [("udp", 3478), ("tcp", 3478)],
        )
        for call in self.allocate.calls:
            self.assertEqual(call["host"], HOST)
            self.assertEqual(call["username"], "erplibre-check")
            self.assertEqual(call["key"], bytes.fromhex(CHECK_KEY))
            self.assertIsNone(call["cafile"])
        self.assertEqual(
            self.get.calls,
            [
                dict(
                    address=HOST,
                    port=8080,
                    path="/v1/health",
                    tls=False,
                    server_name="turn.exemple.test",
                    cafile=None,
                )
            ],
        )

    def test_turn_refused_credentials_and_timeout(self):
        allocate = FakeAllocate(
            udp=tc.Allocation(False, None, "401 Unauthorized"),
            tcp=tc.Allocation(False, None, "timeout"),
        )
        lines = by_name(self.check(self.http_state(), allocate=allocate))
        self.assertIs(lines["turn-udp"].ok, False)
        self.assertEqual(
            lines["turn-udp"].detail, "call_infra_check_turn_error"
        )
        self.assertEqual(
            lines["turn-udp"].values, {"error": "401 Unauthorized"}
        )
        self.assertIs(lines["turn-tcp"].ok, False)
        self.assertEqual(lines["turn-tcp"].values, {"error": "timeout"})

    def test_an_open_relay_is_a_failure_that_says_so(self):
        allocate = FakeAllocate(udp=tc.Allocation(False, None, "no-auth"))
        line = by_name(self.check(self.http_state(), allocate=allocate))[
            "turn-udp"
        ]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_open_relay")

    def test_no_check_key_means_turn_not_checked(self):
        lines = by_name(self.check(self.http_state(), key=None))
        for name in ("turn-udp", "turn-tcp"):
            self.assertIsNone(lines[name].ok)
            self.assertEqual(lines[name].detail, "call_infra_check_no_key")
        self.assertEqual(self.allocate.calls, [])

    def test_supplied_certificate(self):
        state = installed_state(supplied())
        lines = self.check(
            state,
            certs={"coturn": TURN_CERT, "ntfy": TURN_CERT},
            cafile="/ca/exemple.pem",
        )
        names = [line.name for line in lines]
        self.assertEqual(
            names[:5],
            ["turn-udp", "turn-tcp", "turn-tls", "ntfy-health", "cert-expiry"],
        )
        tls = self.allocate.calls[2]
        self.assertEqual(
            (tls["transport"], tls["port"], tls["cafile"], tls["server_name"]),
            ("tls", 5349, "/ca/exemple.pem", "turn.exemple.test"),
        )
        self.assertEqual(self.get.calls[0]["port"], 8443)
        self.assertIs(self.get.calls[0]["tls"], True)
        self.assertEqual(self.get.calls[0]["cafile"], "/ca/exemple.pem")
        expiry = by_name(lines)["cert-expiry"]
        self.assertIs(expiry.ok, True)
        self.assertIn(expiry.values["days"], (29, 30))

    def test_unverified_certificate_is_not_checked(self):
        error = ssl.SSLCertVerificationError("self-signed certificate")
        state = installed_state(supplied())
        lines = by_name(
            self.check(
                state,
                certs={"coturn": TURN_CERT, "ntfy": TURN_CERT},
                get=FakeGet(error),
                allocate=FakeAllocate(tls=tc.Allocation(False, None, "tls")),
            )
        )
        self.assertIsNone(lines["ntfy-health"].ok)
        self.assertEqual(
            lines["ntfy-health"].detail, "call_infra_check_cert_unverified"
        )
        # Sans autorité fournie, un échec TLS ne prouve pas une panne.
        self.assertIsNone(lines["turn-tls"].ok)

    def test_tls_failure_with_the_supplied_authority_is_a_failure(self):
        state = installed_state(supplied())
        line = by_name(
            self.check(
                state,
                certs={"coturn": TURN_CERT, "ntfy": TURN_CERT},
                cafile="/ca/exemple.pem",
                allocate=FakeAllocate(tls=tc.Allocation(False, None, "tls")),
            )
        )["turn-tls"]
        self.assertIs(line.ok, False)

    def test_certificate_with_ten_days_left(self):
        cert, key = Certificates.make(
            "soon", "turn.exemple.test", "DNS:turn.exemple.test", days=10
        )
        state = installed_state(supplied(cert_pem=cert, key_pem=key))
        line = by_name(
            self.check(state, certs={"coturn": cert, "ntfy": cert})
        )["cert-expiry"]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_cert_days")
        self.assertIn(line.values["days"], (9, 10))

    def test_the_earliest_certificate_counts(self):
        cert, key = Certificates.make(
            "soon2", "turn.exemple.test", "DNS:turn.exemple.test", days=10
        )
        state = installed_state(supplied())
        line = by_name(
            self.check(state, certs={"coturn": TURN_CERT, "ntfy": cert})
        )["cert-expiry"]
        self.assertIs(line.ok, False)

    def test_certificate_missing_on_the_host(self):
        state = installed_state(supplied())
        line = by_name(self.check(state, certs={"coturn": TURN_CERT}))[
            "cert-expiry"
        ]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_cert_missing")

    def test_unhealthy_ntfy(self):
        lines = by_name(
            self.check(self.http_state(), get=FakeGet((503, "busy")))
        )
        self.assertIs(lines["ntfy-health"].ok, False)
        self.assertEqual(lines["ntfy-health"].values, {"status": 503})
        lines = by_name(
            self.check(
                self.http_state(), get=FakeGet(ConnectionRefusedError())
            )
        )
        self.assertIs(lines["ntfy-health"].ok, False)
        self.assertEqual(
            lines["ntfy-health"].detail, "call_infra_check_http_error"
        )

    def test_a_recorded_rule_gone_from_the_firewall(self):
        present = ["ufw " + r for r in HTTP_RULES[:-1]]
        # Une règle de l'outil dans un AUTRE pare-feu ne compte pas.
        present.append("nftables tcp 8080 ntfy")
        line = by_name(self.check(self.http_state(), rules=present))[
            "firewall"
        ]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_firewall_missing")
        self.assertEqual(line.values, {"rules": "8080/tcp"})

    def test_no_firewall_rule_recorded_is_not_checked(self):
        state = installed_state(firewall=ci.firewall_record("none", ""))
        line = by_name(self.check(state))["firewall"]
        self.assertIsNone(line.ok)
        self.assertEqual(line.values, {"kind": "none"})
        line = by_name(self.check(installed_state()))["firewall"]
        self.assertIsNone(line.ok)

    def test_nftables_range_is_read_back(self):
        record = ci.firewall_record(
            "nftables", "@@FIREWALL_ADDED udp 49152:49252 coturn\n"
        )
        state = installed_state(firewall=record)
        line = by_name(
            self.check(state, rules=["nftables udp 49152-49252 coturn"])
        )["firewall"]
        self.assertIs(line.ok, True)

    def test_inactive_service(self):
        lines = by_name(
            self.check(
                self.http_state(),
                active={"coturn": "active", "ntfy": "failed"},
            )
        )
        self.assertIs(lines["service-coturn"].ok, True)
        self.assertIs(lines["service-ntfy"].ok, False)
        self.assertEqual(lines["service-ntfy"].values, {"state": "failed"})

    def test_only_the_recorded_services_are_checked(self):
        state = installed_state(answers(services=frozenset({"ntfy"})))
        names = [line.name for line in self.check(state)]
        self.assertEqual(names, ["ntfy-health", "firewall", "service-ntfy"])
        self.assertEqual(self.allocate.calls, [])

    def test_no_state_on_the_host(self):
        lines = self.check(None)
        self.assertEqual(
            lines, [ci.CheckLine("state", False, "call_infra_check_no_state")]
        )

    def test_truncated_output_is_refused(self):
        with self.assertRaises(ci.Refusal) as caught:
            ci.parse_check_remote("@@STATE e30=\n")
        self.assertEqual(caught.exception.key, "call_infra_probe_incomplete")

    def test_parse_ignores_what_it_cannot_trust(self):
        facts = ci.parse_check_remote(
            "@@CHECK_KEY pas-hexa\n"
            "@@CHECK_KEY " + CHECK_KEY + "\n"
            "@@FIREWALL_RULE ufw tcp 22 ntfy\n"
            "@@FIREWALL_RULE ufw tcp 8080; ntfy\n"
            "@@FIREWALL_RULE ufw tcp 8080 ntfy\n"
            "@@END\n"
        )
        self.assertEqual(facts["check_key"], CHECK_KEY)
        self.assertEqual(
            facts["firewall_rules"], [("ufw", rule("tcp", "8080", "ntfy"))]
        )
        self.assertIsNone(facts["state"])

    def test_remote_script_writes_nothing(self):
        script = ci.check_remote_script()
        # Les motifs de `sed -n -E` décrivent les lignes de règles lues ;
        # ils citent « ufw allow » sans le lancer, et finissent par « /p ».
        quoted = r"""'(?:[^']|'"'"')*'"""
        patterns = re.findall(r"sed -n -E (" + quoted + ")", script)
        self.assertEqual(len(patterns), 2)
        for pattern in patterns:
            self.assertTrue(pattern.endswith("/p'"), pattern)
        script = re.sub(r"sed -n -E " + quoted, "sed", script)
        stripped = re.sub(r"[0-9]?>(/dev/null|&1)", "", script)
        self.assertNotIn(">", stripped)
        for word in (
            "rm ",
            "mv ",
            "cp ",
            "tee ",
            "chmod ",
            "chown ",
            "turnadmin",
            "ufw allow",
            "ufw delete",
            "nft add",
            "nft insert",
            "nft delete",
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "insert into",
            "delete from",
        ):
            self.assertNotIn(word, script.lower() if " " in word else script)
        self.assertIn(
            "select hmackey from turnusers_lt where name='erplibre-check'",
            script,
        )
        self.assertIn("-readonly", script)

    def test_every_detail_key_is_listed(self):
        with open(os.path.join(REPO, "script", "todo", "call_infra.py")) as f:
            found = set(re.findall(r'"(call_infra_check_[a-z_]+)"', f.read()))
        self.assertEqual(found, set(ci.CHECK_KEYS))


class TestCheckRemoteRun(unittest.TestCase):
    """`check_remote_script` joué dans une racine temporaire."""

    def test_reads_state_units_key_rules_and_certificates(self):
        state = installed_state(
            supplied(), firewall=ufw_record("udp 3478 coturn", "tcp 8443 ntfy")
        )
        added = (
            "Added user rules (see 'ufw status' for running firewall):\n"
            "ufw allow 22/tcp\n"
            "ufw allow 3478/udp comment 'erplibre-call coturn'\n"
            "ufw allow 49152:49252/udp comment 'erplibre-call coturn'\n"
            "ufw allow 8443/tcp comment 'erplibre-call ntfy'\n"
            "ufw deny 5349/tcp comment 'erplibre-call coturn' log\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            stubs = os.path.join(tmp, "stubs")
            log = os.path.join(tmp, "log")
            write(root + ci.STATE_PATH, json.dumps(state), 0o600)
            write(root + "/etc/erplibre-call/tls/turn.crt", TURN_CERT, 0o640)
            write(root + "/etc/ntfy/tls/ntfy.crt", TURN_CERT, 0o644)
            write(root + ci.COTURN_DB, "base", 0o640)
            write(
                os.path.join(stubs, "systemctl"),
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                "  'cat coturn'|'cat ntfy') exit 0 ;;\n"
                "  'is-active coturn') echo active ;;\n"
                "  'is-active ntfy') echo failed; exit 3 ;;\n"
                "  'show -p') echo turnserver ;;\n"
                "  *) exit 3 ;;\n"
                "esac\n",
            )
            write(
                os.path.join(stubs, "runuser"),
                '#!/bin/sh\necho "runuser $*" >> "$LOG"\n'
                'while [ "$1" != -- ]; do shift; done; shift; exec "$@"\n',
            )
            write(
                os.path.join(stubs, "sqlite3"),
                '#!/bin/sh\necho "sqlite3 $*" >> "$LOG"\n'
                "echo %s\n" % CHECK_KEY,
            )
            write(
                os.path.join(stubs, "ufw"),
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                "  'status ') if %s; then echo 'Status: active';"
                " else echo 'État : actif'; fi ;;\n"
                "  'show added') cat <<'EOF'\n%sEOF\n;;\n"
                "  *) exit 1 ;;\n"
                "esac\n" % (IN_C, added),
            )
            write(os.path.join(stubs, "nft"), "#!/bin/sh\nexit 1\n")
            before = snapshot(root)
            done = subprocess.run(
                ["sh", "-c", ci.check_remote_script(root=root)],
                capture_output=True,
                text=True,
                env=dict(
                    os.environ,
                    PATH=stubs + ":" + os.environ["PATH"],
                    LOG=log,
                    **FRENCH,
                ),
                timeout=30,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(snapshot(root), before)
            with open(log) as handle:
                calls = handle.read()
        facts = ci.parse_check_remote(done.stdout)
        self.assertEqual(facts["state"], state)
        self.assertEqual(
            facts["active"], {"coturn": "active", "ntfy": "failed"}
        )
        self.assertEqual(facts["check_key"], CHECK_KEY)
        self.assertEqual(
            facts["firewall_rules"],
            [
                ("ufw", rule("udp", "3478", "coturn")),
                ("ufw", rule("udp", "49152:49252", "coturn")),
                ("ufw", rule("tcp", "8443", "ntfy")),
            ],
        )
        self.assertEqual(
            facts["certs"], {"coturn": TURN_CERT, "ntfy": TURN_CERT}
        )
        self.assertIn("runuser -u turnserver -- sqlite3 -readonly", calls)
        self.assertIn(root + ci.COTURN_DB, calls)

    def test_nftables_rules_of_the_tool_only(self):
        handles = (
            "table inet filter {\n"
            "\tchain input {\n"
            "\t\ttype filter hook input priority filter; policy drop;\n"
            '\t\tudp dport 3478 accept comment "erplibre-call coturn"\n'
            '\t\tudp dport 49152-49252 accept comment "erplibre-call coturn"\n'
            "\t\ttcp dport 8080 accept\n"
            '\t\ttcp dport 8443 accept comment "autre chose"\n'
            "\t}\n}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            stubs = os.path.join(tmp, "stubs")
            write(
                os.path.join(stubs, "nft"),
                "#!/bin/sh\ncat <<'EOF'\n%sEOF\n" % handles,
            )
            for name in ("ufw", "systemctl"):
                write(os.path.join(stubs, name), "#!/bin/sh\nexit 1\n")
            done = subprocess.run(
                ["sh", "-c", ci.check_remote_script(root=tmp)],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=stubs + ":" + os.environ["PATH"]),
                timeout=30,
            )
        facts = ci.parse_check_remote(done.stdout)
        self.assertEqual(
            facts["firewall_rules"],
            [
                ("nftables", rule("udp", "3478", "coturn")),
                ("nftables", rule("udp", "49152:49252", "coturn")),
            ],
        )
        self.assertIsNone(facts["state"])
        self.assertIsNone(facts["check_key"])
        self.assertEqual(
            facts["active"], {"coturn": "absent", "ntfy": "absent"}
        )


class _QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass


class _Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"healthy":true}\n' if self.path == "/v1/health" else b""
        self.send_response(200 if body else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestHttpsGet(unittest.TestCase):
    """`https_get` contre un vrai serveur sur 127.0.0.1, port libre."""

    def serve(self, tls):
        server = _QuietServer(("127.0.0.1", 0), _Health)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            directory = Certificates.directory.name
            context.load_cert_chain(
                os.path.join(directory, "turn.crt"),
                os.path.join(directory, "turn.key"),
            )
            server.socket = context.wrap_socket(
                server.socket, server_side=True
            )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_http(self):
        port = self.serve(tls=False)
        status, body = ci.https_get("127.0.0.1", port, "/v1/health", False)
        self.assertEqual((status, json.loads(body)), (200, {"healthy": True}))

    def test_https_verified_under_the_public_name(self):
        port = self.serve(tls=True)
        cafile = os.path.join(Certificates.directory.name, "turn.crt")
        status, _ = ci.https_get(
            "127.0.0.1",
            port,
            "/v1/health",
            True,
            server_name="turn.exemple.test",
            cafile=cafile,
            timeout=5,
        )
        self.assertEqual(status, 200)
        with self.assertRaises(ssl.SSLCertVerificationError):
            ci.https_get(
                "127.0.0.1",
                port,
                "/v1/health",
                True,
                server_name="turn.exemple.test",
                timeout=5,
            )

    def test_check_local_with_the_real_client(self):
        port = self.serve(tls=False)
        state = installed_state(
            answers(services=frozenset({"ntfy"}), ntfy_port=port)
        )
        facts = ci.parse_check_remote(remote_output(state, {"ntfy": "active"}))
        line = by_name(ci.check_local(facts, "127.0.0.1", None))["ntfy-health"]
        self.assertIs(line.ok, True, line)


def snapshot(root):
    """{chemin relatif: contenu} de tout ce qui vit sous `root`."""
    found = {}
    for base, dirs, files in os.walk(root):
        for name in dirs:
            found[os.path.relpath(os.path.join(base, name), root) + "/"] = ""
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = handle.read()
    return found


STUB_UNINSTALL_SYSTEMCTL = r"""#!/bin/sh
echo "systemctl $*" >> "$LOG"
case "$1" in
  cat) case " ${UNITS:-} " in *" $2 "*) exit 0 ;; *) exit 1 ;; esac ;;
  try-restart) exit "${RESTART_RC:-0}" ;;
esac
exit 0
"""
# DPKG_STATUS remplace l'état rendu pour les paquets de PKGS : une
# opération dpkg coupée les laisse « half-configured », « unpacked »...
STUB_DPKG_QUERY = r"""#!/bin/sh
for p; do :; done
case " ${PKGS:-} " in
  *" $p "*) echo "${DPKG_STATUS:-install ok installed}" ;;
  *) exit 1 ;;
esac
"""
# DPKG_V : ce que « dpkg -V » imprime (fichiers de configuration modifiés).
STUB_DPKG = r"""#!/bin/sh
echo "dpkg $*" >> "$LOG"
[ "$1" = -V ] && printf '%s' "${DPKG_V:-}"
exit 0
"""
# La purge de ntfy peut emporter ses dossiers (script postrm du paquet) :
# POSTRM=1 le simule.
STUB_APT_GET = r"""#!/bin/sh
echo "apt-get $*" >> "$LOG"
if [ "${POSTRM:-}" = 1 ] && [ "$2 $3" = "-y ntfy" ]; then
  rm -rf "$ROOT/var/lib/ntfy" "$ROOT/etc/ntfy"
fi
exit "${APT_RC:-0}"
"""
STUB_PACMAN = r"""#!/bin/sh
echo "pacman $*" >> "$LOG"
case "$1" in
  -Qq) case " ${PKGS:-} " in *" $2 "*) exit 0 ;; *) exit 1 ;; esac ;;
esac
exit 0
"""
STUB_UFW = r"""#!/bin/sh
echo "ufw $*" >> "$LOG"
case "$1 $2" in
  "show added") cat "$ADDED" ;;
  "delete allow") echo "Rule deleted"; exit "${UFW_DELETE_RC:-0}" ;;
  *) exit 1 ;;
esac
"""
# NGINX_T_RC : code de « nginx -t », son message d'erreur sur stderr.
STUB_NGINX = r"""#!/bin/sh
echo "nginx $*" >> "$LOG"
if [ "$1" = -t ] && [ "${NGINX_T_RC:-0}" != 0 ]; then
  echo "nginx: [emerg] directive inventee in /etc/nginx/nginx.conf:1" >&2
  exit "$NGINX_T_RC"
fi
exit 0
"""
# « certbot delete » retire la lignée sous le --config-dir reçu, comme
# certbot ; CERTBOT_RC le fait échouer sans rien retirer.
STUB_CERTBOT = r"""#!/bin/sh
echo "certbot $*" >> "$LOG"
dir=/etc/letsencrypt
prev=
for a; do [ "$prev" = --config-dir ] && dir=$a; prev=$a; done
[ "${CERTBOT_RC:-0}" = 0 ] || { echo "erreur inventee" >&2; exit 1; }
if [ "$1" = delete ]; then
  rm -rf "$dir/live/erplibre-call" "$dir/archive/erplibre-call" \
    "$dir/renewal/erplibre-call.conf"
fi
exit 0
"""
NTFY_FOREIGN = (
    'base-url: "http://ancien.exemple.test:8080"\n'
    'listen-http: ":8080"\n'
    'auth-file: "/var/lib/ntfy/user.db"\n'
    'auth-default-access: "deny-all"\n'
)


class UninstallSandbox(unittest.TestCase):
    """Racine temporaire et commandes du système en bouchons pour jouer
    `uninstall_script` ; aucune méthode de test ici."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        self.root = os.path.join(base, "root")
        self.stubs = os.path.join(base, "stubs")
        self.scratch = os.path.join(base, "scratch")
        self.log = os.path.join(base, "log")
        self.added = os.path.join(base, "added")
        os.makedirs(self.scratch)
        write(self.added, "", 0o644)
        write(
            self.path("/etc/os-release"),
            'ID=debian\nVERSION_ID="13"\n',
            0o644,
        )
        for name, text in (
            ("systemctl", STUB_UNINSTALL_SYSTEMCTL),
            ("dpkg-query", STUB_DPKG_QUERY),
            ("dpkg", STUB_DPKG),
            ("apt-get", STUB_APT_GET),
            ("pacman", STUB_PACMAN),
            ("ufw", STUB_UFW),
            ("nginx", STUB_NGINX),
            ("certbot", STUB_CERTBOT),
        ):
            write(os.path.join(self.stubs, name), text)

    def path(self, host_path):
        return self.root + host_path

    def run_script(self, script, **env):
        full = dict(
            os.environ,
            PATH=self.stubs + ":" + os.environ["PATH"],
            LOG=self.log,
            ROOT=self.root,
            ADDED=self.added,
            TMPDIR=self.scratch,
        )
        full.update(env)
        return subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            env=full,
            timeout=60,
        )

    def uninstall(self, state, remove_data=False, **env):
        script = ci.uninstall_script(state, remove_data, STAMP, root=self.root)
        return self.run_script(script, **env)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return handle.read().splitlines()

    def markers(self, done):
        return [
            f"{name} {value}".strip()
            for name, value in ci.marker_lines(done.stdout)
        ]

    def place_state(self, state):
        write(self.path(ci.STATE_PATH), json.dumps(state), 0o600)

    def tool_installed_ntfy(self, ans=None):
        """Un ntfy posé par l'outil : paquet, configuration, base des
        comptes, certificat."""
        ans = ans or answers(services=frozenset({"ntfy"}))
        state = installed_state(ans)
        self.place_state(state)
        write(self.path(ci.NTFY_CONFIG), ci.ntfy_config(ans), 0o644)
        write(self.path("/var/lib/ntfy/user.db"), "comptes", 0o640)
        write(self.path("/var/cache/ntfy/cache.db"), "cache", 0o640)
        if ans.tls == "supplied":
            write(self.path("/etc/ntfy/tls/ntfy.crt"), TURN_CERT, 0o644)
            write(self.path("/etc/ntfy/tls/ntfy.key"), TURN_KEY, 0o640)
        return state


class TestUninstall(UninstallSandbox):
    # Sans état, rien ne change.
    def test_no_state_prints_nothing_and_changes_nothing(self):
        write(self.path("/etc/turnserver.conf"), "listening-port=3478\n")
        before = snapshot(self.root)
        done = self.uninstall(None, remove_data=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.markers(done), ["NOTHING"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(os.listdir(self.scratch), [])

    def test_no_state_reports_an_interrupted_install(self):
        write(self.path("/etc/erplibre-call/pending/coturn.json"), "{}", 0o600)
        before = snapshot(self.root)
        done = self.uninstall(None)
        self.assertEqual(self.markers(done), ["PENDING coturn", "NOTHING"])
        self.assertEqual(snapshot(self.root), before)

    def test_adopted_ntfy_is_restored_and_its_package_left(self):
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, NTFY_FOREIGN, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        ans = answers(services=frozenset({"ntfy"}))
        state = installed_state(ans, facts=facts)
        backup = ci.NTFY_CONFIG + ".bak-" + STAMP
        self.assertEqual(state["services"]["ntfy"]["backup"], backup)
        script = ci.uninstall_script(state, True, STAMP)
        self.assertIn(backup, script)
        self.assertNotIn("pkg_purge ntfy", script)

        self.place_state(state)
        write(self.path(backup), NTFY_FOREIGN, 0o640)
        write(self.path(ci.NTFY_CONFIG), ci.ntfy_config(ans), 0o644)
        write(self.path("/var/lib/ntfy/user.db"), "comptes", 0o640)
        done = self.uninstall(
            state, remove_data=True, UNITS="ntfy", PKGS="ntfy"
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(self.path(ci.NTFY_CONFIG)) as handle:
            self.assertEqual(handle.read(), NTFY_FOREIGN)
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path(ci.NTFY_CONFIG)).st_mode), 0o640
        )
        self.assertFalse(os.path.exists(self.path(backup)))
        # Les comptes et jetons d'avant l'outil restent, même avec
        # remove_data : ils ne sont pas à lui.
        self.assertTrue(os.path.exists(self.path("/var/lib/ntfy/user.db")))
        calls = self.calls()
        self.assertFalse([c for c in calls if c.startswith("apt-get")])
        self.assertIn("systemctl try-restart ntfy", calls)
        self.assertNotIn("systemctl disable --now ntfy", calls)
        self.assertIn(
            f"RESTORED {ci.NTFY_CONFIG} {backup}", self.markers(done)
        )
        self.assertFalse(os.path.exists(self.path(ci.CALL_DIR)))

    def test_an_interrupted_package_of_the_tool_is_repaired_then_purged(
        self,
    ):
        for status in (
            "half-installed",
            "unpacked",
            "half-configured",
            "triggers-awaited",
            "triggers-pending",
        ):
            with self.subTest(status=status):
                if os.path.exists(self.log):
                    os.remove(self.log)
                state = self.tool_installed_ntfy()
                done = self.uninstall(
                    state,
                    UNITS="ntfy",
                    PKGS="ntfy",
                    DPKG_STATUS=f"install ok {status}",
                )
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                calls = self.calls()
                repair = "dpkg --configure -a --force-confdef --force-confold"
                self.assertIn(repair, calls)
                self.assertIn("apt-get purge -y ntfy", calls)
                self.assertLess(
                    calls.index(repair), calls.index("apt-get purge -y ntfy")
                )
                self.assertIn("REMOVED package ntfy", self.markers(done))

    def test_a_fully_installed_package_is_purged_without_dpkg_repair(self):
        state = self.tool_installed_ntfy()
        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("apt-get purge -y ntfy", calls)
        self.assertFalse([c for c in calls if c.startswith("dpkg ")], calls)

    def test_a_package_left_as_config_files_is_not_purged(self):
        state = self.tool_installed_ntfy()
        done = self.uninstall(
            state,
            UNITS="ntfy",
            PKGS="ntfy",
            DPKG_STATUS="deinstall ok config-files",
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(
            [c for c in self.calls() if c.startswith(("apt-get", "dpkg "))]
        )

    def test_remove_data_false_keeps_the_ntfy_user_database(self):
        state = self.tool_installed_ntfy(
            supplied(services=frozenset({"ntfy"}))
        )
        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy", POSTRM="1")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(self.path("/var/lib/ntfy/user.db")) as handle:
            self.assertEqual(handle.read(), "comptes")
        self.assertTrue(os.path.exists(self.path("/etc/ntfy/tls/ntfy.key")))
        self.assertFalse(os.path.exists(self.path(ci.NTFY_CONFIG)))
        self.assertFalse(os.path.exists(self.path("/var/cache/ntfy")))
        self.assertIn("apt-get purge -y ntfy", self.calls())
        markers = self.markers(done)
        self.assertIn("KEPT /var/lib/ntfy/user.db", markers)
        self.assertEqual(markers[-1], "DONE yes")
        # Le dossier de mise de côté ne survit pas au passage.
        self.assertEqual(
            [n for n in os.listdir(self.path("/var/lib")) if "hold" in n], []
        )

    def test_remove_data_true_removes_everything_the_tool_added(self):
        ans = supplied()
        record = ufw_record("udp 3478 coturn", "tcp 8443 ntfy")
        state = installed_state(ans, firewall=record)
        self.place_state(state)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        write(self.path("/etc/erplibre-call/coturn.applied"), "x", 0o600)
        write(self.path("/etc/erplibre-call/tls/turn.crt"), TURN_CERT)
        write(self.path("/etc/erplibre-call/tls/turn.key"), TURN_KEY)
        write(self.path("/var/lib/erplibre-call/turndb"), "db", 0o640)
        write(self.path(ci.NTFY_CONFIG), ci.ntfy_config(ans), 0o644)
        write(self.path("/var/lib/ntfy/user.db"), "comptes", 0o640)
        write(self.path("/etc/ntfy/tls/ntfy.crt"), TURN_CERT, 0o644)
        write(self.path("/etc/ntfy/tls/ntfy.key"), TURN_KEY, 0o640)
        write(
            self.added,
            "ufw allow 22/tcp\n"
            "ufw allow 3478/udp comment 'erplibre-call coturn'\n"
            "ufw allow 8443/tcp comment 'erplibre-call ntfy'\n",
            0o644,
        )
        done = self.uninstall(
            state, remove_data=True, UNITS="coturn ntfy", PKGS="coturn ntfy"
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for path in (
            ci.CALL_DIR,
            "/var/lib/erplibre-call",
            "/var/lib/ntfy",
            "/etc/ntfy",
            "/etc/turnserver.conf",
        ):
            self.assertFalse(os.path.exists(self.path(path)), path)
        calls = self.calls()
        for call in (
            "systemctl disable --now coturn",
            "systemctl disable --now ntfy",
            "apt-get purge -y coturn",
            "apt-get purge -y ntfy",
            "ufw delete allow 3478/udp",
            "ufw delete allow 8443/tcp",
        ):
            self.assertIn(call, calls)
        self.assertNotIn("ufw delete allow 22/tcp", calls)
        markers = self.markers(done)
        self.assertIn("FIREWALL_REMOVED udp 3478 coturn", markers)
        self.assertNotIn("END", markers)
        self.assertEqual(markers[-2:], ["REMOVED state", "DONE yes"])

    def test_tool_binary_and_unit_of_ntfy_are_removed(self):
        state = self.tool_installed_ntfy()
        write(
            self.path("/etc/systemd/system/ntfy.service"),
            "[Unit]\nDescription=ntfy push notification server\n"
            "[Service]\nExecStart=/usr/local/bin/ntfy serve\n",
            0o644,
        )
        write(self.path("/usr/local/bin/ntfy"), "binaire")
        write(self.path("/usr/local/bin/autre"), "binaire")
        done = self.uninstall(state, UNITS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(
            os.path.exists(self.path("/etc/systemd/system/ntfy.service"))
        )
        self.assertFalse(os.path.exists(self.path("/usr/local/bin/ntfy")))
        self.assertTrue(os.path.exists(self.path("/usr/local/bin/autre")))
        self.assertIn("systemctl daemon-reload", self.calls())
        self.assertFalse([c for c in self.calls() if "purge" in c])

    def test_a_unit_written_by_someone_else_stays(self):
        state = self.tool_installed_ntfy()
        unit = (
            "[Unit]\nDescription=ntfy local\n"
            "[Service]\nExecStart=/usr/local/bin/ntfy serve\n"
        )
        write(self.path("/etc/systemd/system/ntfy.service"), unit, 0o644)
        write(self.path("/usr/local/bin/ntfy"), "binaire")
        self.uninstall(state, UNITS="ntfy")
        self.assertTrue(
            os.path.exists(self.path("/etc/systemd/system/ntfy.service"))
        )
        self.assertTrue(os.path.exists(self.path("/usr/local/bin/ntfy")))

    def test_arch_removes_with_pacman(self):
        write(self.path("/etc/os-release"), "ID=arch\n", 0o644)
        ans = answers(services=frozenset({"coturn"}))
        state = installed_state(ans, facts=base_facts(family="arch"))
        self.place_state(state)
        done = self.uninstall(state, UNITS="turnserver", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("pacman -Rn --noconfirm coturn", calls)
        self.assertIn("systemctl disable --now turnserver", calls)
        self.assertFalse([c for c in calls if c.startswith("apt-get")])

    # Une coupure ou un échec garde l'état ; la relance
    # termine ; une désinstallation de plus ne trouve rien.
    def test_failure_keeps_the_state_and_a_rerun_converges(self):
        state = self.tool_installed_ntfy()
        pending = self.path("/etc/erplibre-call/pending/ntfy.json")
        write(pending, "{}", 0o600)
        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy", APT_RC="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("FAILED package-ntfy", self.markers(done))
        self.assertEqual(self.markers(done)[-1], "DONE no")
        self.assertTrue(os.path.exists(self.path(ci.STATE_PATH)))
        self.assertTrue(os.path.exists(pending))
        # La base des comptes revient même quand la purge a échoué.
        self.assertTrue(os.path.exists(self.path("/var/lib/ntfy/user.db")))

        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))

        before = snapshot(self.root)
        open(self.log, "w").close()
        done = self.uninstall(None)
        self.assertEqual(self.markers(done), ["NOTHING"])
        self.assertEqual(self.calls(), [])
        self.assertEqual(snapshot(self.root), before)

    def test_a_firewall_rule_that_stays_keeps_the_state(self):
        state = installed_state(
            answers(services=frozenset({"coturn"})),
            firewall=ufw_record("udp 3478 coturn"),
        )
        self.place_state(state)
        write(
            self.added,
            "ufw allow 3478/udp comment 'erplibre-call coturn'\n",
            0o644,
        )
        done = self.uninstall(state, UFW_DELETE_RC="1")
        self.assertNotEqual(done.returncode, 0)
        markers = self.markers(done)
        self.assertIn("FIREWALL_FAILED udp 3478 coturn", markers)
        self.assertIn("FAILED firewall", markers)
        self.assertTrue(os.path.exists(self.path(ci.STATE_PATH)))

    @unittest.skipIf(os.geteuid() == 0, "root passe outre les droits")
    def test_state_stays_while_the_directory_cannot_be_emptied(self):
        state = installed_state(answers(services=frozenset({"coturn"})))
        self.place_state(state)
        stuck = self.path("/etc/erplibre-call/autre")
        write(os.path.join(stuck, "fichier"), "x", 0o600)
        os.chmod(stuck, 0o500)
        self.addCleanup(os.chmod, stuck, 0o700)
        done = self.uninstall(state)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("FAILED call-dir", self.markers(done))
        self.assertTrue(os.path.exists(self.path(ci.STATE_PATH)))

    def test_data_set_aside_by_a_cut_run_comes_back(self):
        state = self.tool_installed_ntfy()
        hold = self.path("/var/lib/erplibre-call.hold-20261029-090000")
        os.makedirs(hold)
        os.rename(self.path("/var/lib/ntfy"), hold + "/ntfy-data")
        done = self.uninstall(state, UNITS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(self.path("/var/lib/ntfy/user.db")) as handle:
            self.assertEqual(handle.read(), "comptes")
        self.assertFalse(os.path.exists(hold))

    def test_installed_and_adopted_purges_then_restores_the_original(self):
        # Une configuration étrangère sans unité (paquet retiré sans
        # purge) : l'outil pose le paquet ET adopte la configuration.
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        current = service("/etc/turnserver.conf", original)
        current.update(unit_found=False, active="inactive")
        ans = answers(services=frozenset({"coturn"}))
        state = installed_state(ans, facts=base_facts(coturn=current))
        record = state["services"]["coturn"]
        self.assertTrue(record["installed_by_tool"] and record["adopted"])
        backup = "/etc/turnserver.conf.bak-" + STAMP
        self.assertEqual(record["backup"], backup)
        self.place_state(state)
        write(self.path(backup), original, 0o640)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("apt-get purge -y coturn", calls)
        self.assertNotIn("systemctl try-restart coturn", calls)
        with open(self.path("/etc/turnserver.conf")) as handle:
            self.assertEqual(handle.read(), original)
        self.assertFalse(os.path.exists(self.path(backup)))
        markers = self.markers(done)
        self.assertIn(f"RESTORED /etc/turnserver.conf {backup}", markers)
        self.assertEqual(markers[-1], "DONE yes")

    def test_installed_and_adopted_without_its_copy_says_it_is_lost(self):
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        current = service("/etc/turnserver.conf", original)
        current.update(unit_found=False, active="inactive")
        ans = answers(services=frozenset({"coturn"}))
        state = installed_state(ans, facts=base_facts(coturn=current))
        self.place_state(state)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        self.assertIn(
            "BACKUP_LOST coturn /etc/turnserver.conf.bak-" + STAMP, markers
        )
        self.assertEqual(markers[-1], "DONE yes")

    def test_adopted_unit_stopped_before_is_stopped_again(self):
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        current = service("/etc/turnserver.conf", original)
        current.update(active="inactive", enabled="disabled")
        ans = answers(services=frozenset({"coturn"}))
        state = installed_state(
            ans,
            facts=base_facts(
                coturn=current, busy_ports=(("udp", 3478, "turnserver"),)
            ),
        )
        backup = state["services"]["coturn"]["backup"]
        self.place_state(state)
        write(self.path(backup), original, 0o640)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("systemctl stop coturn", calls)
        self.assertIn("systemctl disable coturn", calls)
        self.assertNotIn("systemctl try-restart coturn", calls)
        with open(self.path("/etc/turnserver.conf")) as handle:
            self.assertEqual(handle.read(), original)

    def test_adopted_unit_running_and_enabled_is_restarted(self):
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        current = service("/etc/turnserver.conf", original)
        current.update(enabled="enabled")
        ans = answers(services=frozenset({"coturn"}))
        state = installed_state(
            ans,
            facts=base_facts(
                coturn=current, busy_ports=(("udp", 3478, "turnserver"),)
            ),
        )
        self.place_state(state)
        write(self.path(state["services"]["coturn"]["backup"]), original)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("systemctl try-restart coturn", calls)
        self.assertNotIn("systemctl stop coturn", calls)
        self.assertNotIn("systemctl disable coturn", calls)

    def test_success_removes_the_pending_firewall_rules(self):
        state = self.tool_installed_ntfy()
        write(
            self.path(ci.PENDING_DIR + "/firewall"),
            "ufw tcp 8080 ntfy\n",
            0o600,
        )
        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(os.path.exists(self.path(ci.CALL_DIR)))

    def test_adopted_ntfy_loses_the_admin_the_tool_added(self):
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, NTFY_FOREIGN, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        ans = answers(services=frozenset({"ntfy"}))
        state = ci.mark_admin_added(
            installed_state(ans, facts=facts), "@@ADMIN_PASSWORD Ab1\n"
        )
        backup = state["services"]["ntfy"]["backup"]
        self.place_state(state)
        write(self.path(backup), NTFY_FOREIGN, 0o640)
        write(self.path(ci.NTFY_CONFIG), ci.ntfy_config(ans, NTFY_FOREIGN))
        write(os.path.join(self.stubs, "id"), "#!/bin/sh\nexit 0\n")
        write(
            os.path.join(self.stubs, "runuser"),
            '#!/bin/sh\necho "runuser $*" >> "$LOG"\n'
            'while [ "$1" != -- ]; do shift; done; shift; exec "$@"\n',
        )
        write(
            os.path.join(self.stubs, "ntfy"),
            "#!/bin/sh\n"
            'echo "ntfy $* $(head -n 1 "$ROOT/etc/ntfy/server.yml")" >> "$LOG"\n'
            'case "$*" in\n'
            '  *" list") echo "user erplibre (role: admin, tier: none)" >&2 ;;\n'
            "esac\n",
        )
        done = self.uninstall(state, UNITS="ntfy", PKGS="ntfy")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        # Retiré sous la configuration de l'outil, avant la remise de
        # l'originale, et sous le compte du service.
        config = self.path(ci.NTFY_CONFIG)
        self.assertIn(
            f"ntfy user --config {config} del erplibre {ci.MARKER}", calls
        )
        self.assertIn(
            f"runuser -u ntfy -- ntfy user --config {config} del erplibre",
            calls,
        )
        self.assertIn("REMOVED account erplibre", self.markers(done))
        with open(self.path(ci.NTFY_CONFIG)) as handle:
            self.assertEqual(handle.read(), NTFY_FOREIGN)

    def adopted_coturn(self, ans, **facts):
        """Un coturn adopté dont la copie de la configuration d'origine a
        disparu : la configuration de l'outil est en place."""
        original = "listening-port=3478\nrealm=ancien.exemple.test\n"
        facts = base_facts(
            coturn=service("/etc/turnserver.conf", original),
            busy_ports=(("udp", 3478, "turnserver"),),
            **facts,
        )
        state = installed_state(ans, facts=facts)
        self.place_state(state)
        write(self.path("/etc/turnserver.conf"), ci.coturn_config(ans))
        return state, original

    def test_adopted_backup_missing_is_said_and_the_rest_goes(self):
        state, _ = self.adopted_coturn(answers())
        write(self.path(ci.NTFY_CONFIG), ci.ntfy_config(answers()), 0o644)
        done = self.uninstall(state, UNITS="coturn ntfy", PKGS="coturn ntfy")
        backup = "/etc/turnserver.conf.bak-" + STAMP
        markers = self.markers(done)
        self.assertIn(f"BACKUP_MISSING coturn {backup}", markers)
        # La configuration en place n'est pas retirée : le service tourne.
        self.assertTrue(os.path.exists(self.path("/etc/turnserver.conf")))
        calls = self.calls()
        self.assertNotIn("apt-get purge -y coturn", calls)
        self.assertNotIn("systemctl try-restart coturn", calls)
        # Le service d'à côté, lui, est désinstallé.
        self.assertIn("apt-get purge -y ntfy", calls)
        self.assertFalse(os.path.exists(self.path(ci.NTFY_CONFIG)))
        self.assertNotIn("FAILED", " ".join(markers))
        self.assertEqual(markers[-1], "DONE partial")
        self.assertNotEqual(done.returncode, 0)
        self.assertTrue(os.path.exists(self.path(ci.STATE_PATH)))

    # Un service gardé n'est pas désinstallé ; l'état et
    # ce que sa configuration utilise restent, jusqu'à ce que la relance
    # puisse le défaire.
    def test_kept_service_keeps_its_tls_database_and_the_state(self):
        ans = supplied(services=frozenset({"coturn"}))
        state, original = self.adopted_coturn(ans)
        kept = (
            "/etc/turnserver.conf",
            "/etc/erplibre-call/tls/turn.crt",
            "/etc/erplibre-call/tls/turn.key",
            "/var/lib/erplibre-call/turndb",
            "/etc/erplibre-call/pending/coturn.json",
            ci.STATE_PATH,
        )
        write(self.path("/etc/erplibre-call/tls/turn.crt"), TURN_CERT)
        write(self.path("/etc/erplibre-call/tls/turn.key"), TURN_KEY)
        write(self.path("/var/lib/erplibre-call/turndb"), "db", 0o640)
        write(self.path("/etc/erplibre-call/pending/coturn.json"), "{}")
        for _ in range(2):
            done = self.uninstall(
                state, remove_data=True, UNITS="coturn", PKGS="coturn"
            )
            self.assertNotEqual(done.returncode, 0)
            markers = self.markers(done)
            self.assertIn(
                f"BACKUP_MISSING coturn /etc/turnserver.conf.bak-{STAMP}",
                markers,
            )
            self.assertNotIn("REMOVED state", markers)
            self.assertNotIn("NOTHING", markers)
            self.assertEqual(markers[-1], "DONE partial")
            for path in kept:
                self.assertTrue(os.path.exists(self.path(path)), path)

        # L'administrateur remet sa configuration : la relance termine.
        write(self.path("/etc/turnserver.conf"), original, 0o644)
        done = self.uninstall(
            state, remove_data=True, UNITS="coturn", PKGS="coturn"
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.markers(done)[-2:], ["REMOVED state", "DONE yes"]
        )
        with open(self.path("/etc/turnserver.conf")) as handle:
            self.assertEqual(handle.read(), original)
        for path in kept[1:]:
            self.assertFalse(os.path.exists(self.path(path)), path)
        self.assertIn("systemctl try-restart coturn", self.calls())
        self.assertNotIn("apt-get purge -y coturn", self.calls())

    def path_without(self, *names):
        """PATH fait d'un dossier de liens vers les bouchons puis les
        commandes du PATH courant, sauf `names` : ces commandes y manquent,
        quoi que la machine des tests ait d'installé."""
        farm = os.path.join(self.tmp.name, "farm")
        os.makedirs(farm)
        folders = [self.stubs] + os.environ["PATH"].split(os.pathsep)
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                target = os.path.join(folder, name)
                link = os.path.join(farm, name)
                if (
                    name in names
                    or os.path.lexists(link)
                    or os.path.isdir(target)
                    or not os.access(target, os.X_OK)
                ):
                    continue
                os.symlink(target, link)
        return farm

    # Le pare-feu consigné a été désinstallé depuis : aucune de ses
    # règles ne peut rester, la désinstallation se termine.
    def test_firewall_tool_gone_reports_its_rules_absent(self):
        rule = ci.Rule("udp", "3478", "coturn")
        nft_line = "insert rule inet filter input " + ci._nft_rule(rule)
        records = {
            "ufw": ufw_record("udp 3478 coturn", "tcp 3478 coturn"),
            "nftables": ci.firewall_record(
                "nftables",
                "@@FIREWALL_CHAIN inet filter input\n"
                "@@FIREWALL_ADDED udp 3478 coturn\n"
                "@@FIREWALL_ADDED tcp 3478 coturn\n"
                "@@FIREWALL_PERSISTED yes\n@@END\n",
            ),
        }
        bare = self.path_without("ufw", "nft")
        for kind, record in records.items():
            with self.subTest(kind):
                state = installed_state(
                    answers(services=frozenset({"coturn"})), firewall=record
                )
                self.place_state(state)
                persist = self.path(ci.NFT_PERSIST_FILE)
                write(persist, ci.MARKER + "\n" + nft_line + "\n", 0o644)
                done = self.uninstall(state, PATH=bare)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                markers = self.markers(done)
                self.assertIn("FIREWALL_ABSENT udp 3478 coturn", markers)
                self.assertIn("FIREWALL_ABSENT tcp 3478 coturn", markers)
                self.assertEqual(markers[-1], "DONE yes")
                self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))
                # Les lignes de l'outil partent aussi du fichier chargé au
                # démarrage, nft absent ou non.
                self.assertEqual(os.path.exists(persist), kind == "ufw")
                self.assertFalse(
                    [c for c in self.calls() if c.startswith(("ufw", "nft"))]
                )

    def test_pending_record_of_a_service_not_in_the_state_is_kept(self):
        state = installed_state(answers(services=frozenset({"coturn"})))
        self.place_state(state)
        pending = self.path("/etc/erplibre-call/pending/ntfy.json")
        write(pending, "{}", 0o600)
        write(self.path("/etc/erplibre-call/pending/coturn.json"), "{}", 0o600)
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("PENDING_LEFT ntfy", self.markers(done))
        self.assertTrue(os.path.exists(pending))
        self.assertFalse(
            os.path.exists(self.path("/etc/erplibre-call/pending/coturn.json"))
        )
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))

    def test_kept_tls_directory_of_coturn(self):
        ans = supplied(services=frozenset({"coturn"}))
        state = installed_state(ans)
        self.place_state(state)
        write(self.path("/etc/erplibre-call/tls/turn.key"), TURN_KEY)
        done = self.uninstall(state, UNITS="coturn", PKGS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(
            os.path.exists(self.path("/etc/erplibre-call/tls/turn.key"))
        )
        self.assertEqual(os.listdir(self.path(ci.CALL_DIR)), ["tls"])

    def test_values_read_from_the_state_are_checked(self):
        good = installed_state(supplied())
        cases = {
            "unit": ("coturn", "unit", "coturn; reboot"),
            "config": ("coturn", "config", "etc/turnserver.conf"),
            "dots": ("coturn", "config", "/etc/../root/x"),
            "backup": ("coturn", "backup", "/tmp/autre.bak-1"),
            "tls": ("ntfy", "tls_files", ["/root/.ssh/id_ed25519"]),
            "tls-list": ("ntfy", "tls_files", [["x"]]),
            "tls-dict": ("ntfy", "tls_files", [{"x": 1}]),
            "unit-list": ("coturn", "unit", ["coturn"]),
            "was_active": ("coturn", "was_active", "oui"),
            "was_enabled": ("coturn", "was_enabled", ["enabled"]),
            "record": ("ntfy", None, "pas un dict"),
        }
        for label, (svc, key, value) in cases.items():
            with self.subTest(label):
                state = json.loads(json.dumps(good))
                if key is None:
                    state["services"][svc] = value
                else:
                    state["services"][svc][key] = value
                with self.assertRaises(ci.Refusal) as caught:
                    ci.uninstall_script(state, False, STAMP)
                self.assertEqual(
                    caught.exception.key, "call_infra_state_invalid"
                )
        with self.assertRaises(ci.Refusal) as caught:
            ci.uninstall_script(dict(good, version=99), False, STAMP)
        self.assertEqual(caught.exception.key, "call_infra_state_version")

    def test_bad_stamp(self):
        with self.assertRaises(ValueError):
            ci.uninstall_script(None, False, "a b")


def production(**changes):
    """Réponses de production inventées : les deux services, Let's Encrypt
    par HTTP à travers un nginx installé par l'outil."""
    values = dict(
        mode="production",
        tls="letsencrypt",
        acme="http-nginx",
        nginx="install",
        public_name="exemple.test",
        ntfy_name="ntfy.exemple.test",
        turn_name="turn.exemple.test",
        email="admin@exemple.test",
    )
    values.update(changes)
    return answers(**values)


def coturn_only(**changes):
    values = dict(
        services=frozenset({"coturn"}),
        acme="http-standalone",
        nginx=None,
        ntfy_name=None,
    )
    values.update(changes)
    return production(**values)


def nginx_facts(
    state="active", layout="debian", names=(), include=False, enabled=None
):
    return {
        "state": state,
        "layout": layout,
        "include": include,
        "names": tuple(names),
        "enabled": enabled,
        "pending": None,
    }


def certbot_facts(
    lineage=None, held=False, plugins=(), version="4.0.0", authenticator=None
):
    return {
        "version": version,
        "lineage": tuple(lineage) if lineage is not None else None,
        "held": held,
        "plugins": tuple(plugins),
        "authenticator": authenticator,
        "pending": None,
    }


def production_installed(ans, **changes):
    """Les faits d'un hôte où une installation de production de `ans` a
    réussi : services actifs sur leur configuration, nginx actif quand il
    sert, lignée certbot aux noms du certificat avec Let's Encrypt."""
    first = ci.plan_install(base_facts(), ans, NOW)
    ports = [("udp", 3478, "turnserver"), ("tcp", 3478, "turnserver")]
    ntfy = None
    if "ntfy" in ans.services:
        ntfy = service(ci.NTFY_CONFIG, ci.ntfy_config(ans), unit="ntfy")
        ports.append(("tcp", 8080, "ntfy"))
    nginx = certbot = None
    if ans.nginx:
        ports += [("tcp", 80, "nginx"), ("tcp", 443, "nginx")]
        nginx = nginx_facts()
    if ans.tls == "letsencrypt":
        certbot = certbot_facts(
            lineage=ci.certificate_names(ans),
            authenticator=ci.certbot_authenticator(ans),
        )
    values = dict(
        coturn=service("/etc/turnserver.conf", ci.coturn_config(ans)),
        ntfy=ntfy,
        busy_ports=tuple(ports),
        state=ci.written_state(first, STAMP),
        nginx=nginx,
        certbot=certbot,
    )
    values.update(changes)
    return base_facts(**values)


def installer_ranges_block():
    """Le tableau DENIED_PEER_RANGES d'install_coturn.sh, tel quel."""
    with open(COTURN_INSTALLER) as handle:
        text = handle.read()
    return re.search(
        r"^DENIED_PEER_RANGES=\(\n.*?^\)\n", text, re.M | re.S
    ).group(0)


def installer_ranges():
    """Les plages de DENIED_PEER_RANGES, lues dans install_coturn.sh."""
    return tuple(
        line.strip() for line in installer_ranges_block().splitlines()[1:-1]
    )


class TestProduction(unittest.TestCase):
    """Mode production : réponses, refus, configurations de coturn et ntfy,
    ports, pare-feu et relecture de l'état."""

    def refusal(self, facts, ans):
        with self.assertRaises(ci.Refusal) as caught:
            ci.plan_install(facts, ans, NOW)
        return caught.exception

    def test_constants(self):
        self.assertEqual(ci.MODES, ("development", "production"))
        self.assertEqual(ci.TLS_MODES, ("none", "supplied", "letsencrypt"))
        self.assertEqual(
            ci.ACME_METHODS, ("http-nginx", "http-standalone", "dns")
        )
        self.assertEqual(
            ci.DNS_PLUGINS,
            (
                "cloudflare",
                "digitalocean",
                "dnsimple",
                "google",
                "linode",
                "luadns",
                "nsone",
                "ovh",
                "rfc2136",
            ),
        )
        self.assertEqual((ci.PROD_MIN_PORT, ci.PROD_MAX_PORT), (49152, 65535))
        self.assertEqual(
            ci.FIREWALL_LABELS, ci.SERVICES + ("nginx", "certbot")
        )

    def test_lot_1_answers_keep_their_defaults(self):
        ans = answers()
        self.assertEqual(ans.mode, "development")
        self.assertIsNone(ans.ntfy_name)
        self.assertIsNone(ans.turn_name)
        self.assertIsNone(ans.acme)
        self.assertIsNone(ans.nginx)
        self.assertFalse(ans.turns_443)
        self.assertFalse(ans.ntfy_web)
        self.assertEqual(ans.email, "")
        plan = ci.plan_install(base_facts(), ans, NOW)
        self.assertEqual(plan.new_state["mode"], "development")

    def test_default_names(self):
        self.assertEqual(
            ci.default_names("exemple.test"),
            ("ntfy.exemple.test", "turn.exemple.test"),
        )
        self.assertEqual(
            ci.default_names(" exemple.test. "),
            ("ntfy.exemple.test", "turn.exemple.test"),
        )

    def test_names_fall_back_to_the_public_name(self):
        ans = production(ntfy_name=None, turn_name=None)
        self.assertEqual(ci.ntfy_host(ans), "exemple.test")
        self.assertEqual(ci.turn_host(ans), "exemple.test")
        ans = production()
        self.assertEqual(ci.ntfy_host(ans), "ntfy.exemple.test")
        self.assertEqual(ci.turn_host(ans), "turn.exemple.test")

    # --- Refus ------------------------------------------------------------

    def test_production_without_tls_is_refused(self):
        refusal = self.refusal(base_facts(), production(tls="none", acme=None))
        self.assertEqual(refusal.key, "call_infra_prod_needs_tls")

    def test_ntfy_in_production_needs_nginx(self):
        refusal = self.refusal(base_facts(), production(nginx=None))
        self.assertEqual(refusal.key, "call_infra_prod_needs_nginx")
        # coturn seul se passe de nginx.
        ci.plan_install(base_facts(), coturn_only(), NOW)

    def test_supplied_certificate_must_cover_every_name_used(self):
        ans = production(
            tls="supplied", acme=None, cert_pem=TURN_CERT, key_pem=TURN_KEY
        )
        refusal = self.refusal(base_facts(), ans)
        self.assertEqual(refusal.key, "call_infra_cert_name_missing")
        self.assertEqual(refusal.values["name"], "ntfy.exemple.test")
        # Un certificat générique couvre les deux noms.
        ci.plan_install(
            base_facts(),
            dataclasses.replace(ans, cert_pem=WILD_CERT, key_pem=WILD_KEY),
            NOW,
        )
        # Sur un hôte de coturn seul, seul le nom de TURN compte.
        ci.plan_install(
            base_facts(),
            coturn_only(
                tls="supplied", acme=None, cert_pem=TURN_CERT, key_pem=TURN_KEY
            ),
            NOW,
        )

    def test_acme_method_must_suit_the_services(self):
        cases = {
            "standalone while nginx is used": (
                base_facts(),
                production(acme="http-standalone"),
            ),
            "standalone while nginx answers on 80": (
                base_facts(busy_ports=(("tcp", 80, "nginx"),)),
                coturn_only(),
            ),
            "webroot without nginx": (
                base_facts(),
                coturn_only(acme="http-nginx"),
            ),
        }
        for name, (facts, ans) in cases.items():
            with self.subTest(name):
                refusal = self.refusal(facts, ans)
                self.assertEqual(refusal.key, "call_infra_acme_method")
                self.assertEqual(refusal.values["method"], ans.acme)

    def test_standalone_certbot_needs_port_80_free(self):
        refusal = self.refusal(
            base_facts(busy_ports=(("tcp", 80, "lighttpd"),)), coturn_only()
        )
        self.assertEqual(refusal.key, "call_infra_port_busy")
        self.assertEqual(refusal.values["port"], 80)

    def test_dns_plugin_needs_a_known_plugin_and_credentials(self):
        good = dict(
            acme="dns",
            dns_plugin="cloudflare",
            dns_credentials="dns_cloudflare_api_token = Inventejeton\n",
        )
        for changes in (
            {"dns_plugin": "inconnu"},
            {"dns_plugin": None},
            {"dns_credentials": ""},
            {"dns_credentials": "  \n"},
            {"dns_credentials": None},
        ):
            with self.subTest(changes=changes):
                refusal = self.refusal(
                    base_facts(), coturn_only(**(good | changes))
                )
                self.assertEqual(refusal.key, "call_infra_dns_plugin")
        plan = ci.plan_install(base_facts(), coturn_only(**good), NOW)
        # Le fichier d'identifiants est un secret : jamais dans l'état.
        self.assertNotIn("Inventejeton", json.dumps(plan.new_state))

    def test_turns_443_replaces_the_tls_port_on_a_coturn_only_host(self):
        ans = coturn_only(turns_443=True)
        plan = ci.plan_install(base_facts(), ans, NOW)
        config = ci.coturn_config(ans)
        self.assertIn("tls-listening-port=443\n", config)
        self.assertNotIn("tls-listening-port=5349", config)
        rules = ci.firewall_rules(ans)
        self.assertIn(rule("tcp", "443", "coturn"), rules)
        self.assertNotIn(rule("tcp", "5349", "coturn"), rules)
        self.assertIn(("tcp", 443, "coturn"), ci.needed_ports(ans))
        block = "\n".join(ci._coturn_block(plan))
        self.assertIn("  TURN_ALT_TLS_PORT=443\n", block)
        self.assertTrue(
            plan.new_state["services"]["coturn"]["settings"]["turns_443"]
        )
        # Sans le choix, rien de 443 pour coturn.
        plain = ci.plan_install(base_facts(), coturn_only(), NOW)
        self.assertNotIn(
            "TURN_ALT_TLS_PORT", "\n".join(ci._coturn_block(plain))
        )

    def test_turns_443_is_refused_when_443_is_taken(self):
        cases = {
            "nginx used": (
                base_facts(),
                coturn_only(
                    turns_443=True, acme="http-nginx", nginx="install"
                ),
                "nginx",
            ),
            "443 busy": (
                base_facts(busy_ports=(("tcp", 443, "caddy"),)),
                coturn_only(turns_443=True),
                "caddy",
            ),
        }
        for name, (facts, ans, holder) in cases.items():
            with self.subTest(name):
                refusal = self.refusal(facts, ans)
                self.assertEqual(refusal.key, "call_infra_turns_443")
                self.assertEqual(refusal.values["holder"], holder)
                self.assertEqual(refusal.values["port"], 5349)
        # coturn qui tient déjà 443 (relance) n'est pas un refus.
        ci.plan_install(
            base_facts(busy_ports=(("tcp", 443, "turnserver"),)),
            coturn_only(turns_443=True),
            NOW,
        )

    def test_answers_out_of_contract(self):
        for ans in (
            answers(mode="staging"),
            answers(tls="letsencrypt", acme="http-nginx"),
            production(nginx="ailleurs"),
            production(acme=None),
            production(acme="tls-alpn"),
            answers(turns_443=True),
        ):
            with self.subTest(ans=ans):
                with self.assertRaises(ValueError):
                    ci.plan_install(base_facts(), ans, NOW)

    def test_bad_names_and_email_are_refused(self):
        for changes, name in (
            ({"ntfy_name": "ntfy exemple"}, "ntfy_name"),
            ({"turn_name": "-turn.exemple.test"}, "turn_name"),
            ({"email": "pas une adresse"}, "email"),
            ({"email": "a@b.test;reboot"}, "email"),
        ):
            with self.subTest(changes=changes):
                refusal = self.refusal(base_facts(), production(**changes))
                self.assertEqual(refusal.key, "call_infra_bad_value")
                self.assertEqual(refusal.values["name"], name)
        ci.plan_install(base_facts(), production(email=""), NOW)

    # --- coturn -----------------------------------------------------------

    def test_coturn_production_denies_the_installer_ranges(self):
        self.assertEqual(ci.DENIED_PEER_RANGES, installer_ranges())
        config = ci.coturn_config(production())
        self.assertIn("denied-peer-ip=10.0.0.0-10.255.255.255\n", config)
        denied = tuple(
            line.split("=", 1)[1]
            for line in config.splitlines()
            if line.startswith("denied-peer-ip=")
        )
        self.assertEqual(denied, installer_ranges())
        self.assertNotIn("denied-peer-ip", ci.coturn_config(answers()))
        self.assertNotIn("denied-peer-ip", ci.coturn_config(supplied()))

    def test_coturn_production_parity_with_the_installer(self):
        ans = production(
            tls="supplied",
            acme=None,
            cert_pem=WILD_CERT,
            key_pem=WILD_KEY,
            external_ip="203.0.113.7",
        )
        lo, hi = ci.relay_range(ans)
        env = (
            "TURN_REALM=%s\nTURN_PORT=%d\nTURN_TLS_PORT=%d\nTURN_MIN_PORT=%d\n"
            "TURN_MAX_PORT=%d\nTURN_CERT_FILE=/x.crt\nTURN_KEY_FILE=/x.key\n"
            "TURN_EXTERNAL_IP=%s\nTURN_ALLOW_PRIVATE=\n"
            % (
                ans.public_name,
                ans.turn_port,
                ans.turns_port,
                lo,
                hi,
                ans.external_ip,
            )
        ) + installer_ranges_block()
        self.assertEqual(
            ci.coturn_config(ans), TestCoturnConfig.installer_config(self, env)
        )

    def test_coturn_turns_443_parity_with_the_installer(self):
        # Ce que `_coturn_block` exporte pour turns_443 (TURN_TLS_PORT reste
        # le port configuré, TURN_ALT_TLS_PORT=443 le remplace) donne au
        # caractère près le texte de `coturn_config`.
        ans = coturn_only(
            turns_443=True,
            tls="supplied",
            acme=None,
            cert_pem=WILD_CERT,
            key_pem=WILD_KEY,
        )
        plan = ci.plan_install(base_facts(), ans, NOW)
        block = "\n".join(ci._coturn_block(plan))
        self.assertIn("  TURN_TLS_PORT=%d\n" % ans.turns_port, block)
        self.assertIn("  TURN_ALT_TLS_PORT=443\n", block)
        lo, hi = ci.relay_range(ans)
        env = (
            "TURN_REALM=%s\nTURN_PORT=%d\nTURN_TLS_PORT=%d\nTURN_MIN_PORT=%d\n"
            "TURN_MAX_PORT=%d\nTURN_CERT_FILE=/x.crt\nTURN_KEY_FILE=/x.key\n"
            "TURN_EXTERNAL_IP=\nTURN_ALLOW_PRIVATE=\nTURN_ALT_TLS_PORT=443\n"
            % (ans.public_name, ans.turn_port, ans.turns_port, lo, hi)
        ) + installer_ranges_block()
        self.assertEqual(
            ci.coturn_config(ans), TestCoturnConfig.installer_config(self, env)
        )
        self.assertIn("tls-listening-port=443\n", ci.coturn_config(ans))

    def test_coturn_block_follows_the_mode(self):
        prod = ci.plan_install(base_facts(), production(), NOW)
        block = "\n".join(ci._coturn_block(prod))
        self.assertNotIn("TURN_ALLOW_PRIVATE", block)
        self.assertIn("  TURN_MIN_PORT=49152\n", block)
        self.assertIn("  TURN_MAX_PORT=65535\n", block)
        dev = ci.plan_install(base_facts(), answers(), NOW)
        self.assertIn(
            "  TURN_ALLOW_PRIVATE=1\n", "\n".join(ci._coturn_block(dev))
        )

    def test_letsencrypt_counts_as_tls_for_coturn(self):
        config = ci.coturn_config(production())
        self.assertIn("tls-listening-port=5349\n", config)
        self.assertIn("cert=/etc/erplibre-call/tls/turn.crt\n", config)
        self.assertNotIn("no-tls", config)
        plan = ci.plan_install(base_facts(), production(), NOW)
        self.assertEqual(
            plan.new_state["services"]["coturn"]["tls_files"],
            [
                "/etc/erplibre-call/tls/turn.crt",
                "/etc/erplibre-call/tls/turn.key",
            ],
        )

    def test_external_ip_lands_in_the_coturn_config(self):
        # Hôte derrière un NAT : le nom de TURN résout vers une adresse
        # absente des interfaces, l'adresse confirmée part dans la config.
        facts = base_facts(addresses=("10.0.0.5",))
        ans = coturn_only(external_ip="203.0.113.7")
        plan = ci.plan_install(facts, ans, NOW)
        self.assertIn("external-ip=203.0.113.7\n", ci.coturn_config(ans))
        self.assertIn(
            "  TURN_EXTERNAL_IP=203.0.113.7\n",
            "\n".join(ci._coturn_block(plan)),
        )

    def test_media_range_default_in_production(self):
        self.assertEqual(ci.relay_range(production()), (49152, 65535))
        self.assertEqual(ci.relay_range(answers()), (49152, 49252))
        chosen = production(min_port=50000, max_port=50100)
        self.assertEqual(ci.relay_range(chosen), (50000, 50100))
        config = ci.coturn_config(production())
        self.assertIn("min-port=49152\nmax-port=65535\n", config)
        settings = ci.plan_install(base_facts(), production(), NOW).new_state[
            "services"
        ]["coturn"]["settings"]
        self.assertEqual(
            (settings["min_port"], settings["max_port"]), (49152, 65535)
        )

    # --- external-ip ------------------------------------------------------

    @staticmethod
    def resolver(*addresses):
        def resolve(name, port, *args, **kwargs):
            if not addresses:
                raise OSError("name does not resolve")
            return [
                (
                    10 if ":" in a else 2,
                    1,
                    6,
                    "",
                    (a, 0, 0, 0) if ":" in a else (a, 0),
                )
                for a in addresses
            ]

        return resolve

    def test_external_ip_for(self):
        name = "turn.exemple.test"
        self.assertEqual(
            ci.external_ip_for(
                name, ("10.0.0.5",), self.resolver("203.0.113.7")
            ),
            ("203.0.113.7", "nat"),
        )
        self.assertEqual(
            ci.external_ip_for(
                name, ("10.0.0.5", "203.0.113.7"), self.resolver("203.0.113.7")
            ),
            ("203.0.113.7", "local"),
        )
        self.assertEqual(
            ci.external_ip_for(name, ("10.0.0.5",), self.resolver()),
            (None, "unresolved"),
        )

    def test_external_ip_for_judges_on_ipv4_first(self):
        # L'IPv6 est sur l'hôte mais l'IPv4 passe par un NAT : coturn a
        # besoin d'external-ip pour ses relais IPv4.
        resolve = self.resolver("2001:db8::10", "203.0.113.7")
        self.assertEqual(
            ci.external_ip_for(
                "turn.exemple.test", ("2001:db8::10",), resolve
            ),
            ("203.0.113.7", "nat"),
        )
        # Seulement de l'IPv6, présente sur l'hôte, sous une autre graphie.
        self.assertEqual(
            ci.external_ip_for(
                "turn.exemple.test",
                ("2001:db8:0:0::10",),
                self.resolver("2001:db8::10"),
            ),
            ("2001:db8::10", "local"),
        )

    # --- ntfy -------------------------------------------------------------

    def test_ntfy_production_config(self):
        text = ci.ntfy_config(production())
        keys = nm.read_yml_keys(text)
        self.assertEqual(keys["behind-proxy"], "true")
        self.assertEqual(keys["web-root"], "disable")
        self.assertEqual(keys["base-url"], "https://ntfy.exemple.test")
        self.assertTrue(keys["listen-http"].startswith("127.0.0.1:"))
        self.assertEqual(keys["listen-http"], "127.0.0.1:8080")
        for key in ("listen-https", "cert-file", "key-file"):
            self.assertNotIn(key, keys)
        self.assertIn("behind-proxy: true\n", text)
        self.assertEqual(nm.config_problems(keys), [])
        web = nm.read_yml_keys(ci.ntfy_config(production(ntfy_web=True)))
        self.assertEqual(web["web-root"], "app")
        self.assertEqual(
            ci.ntfy_base_url(production()), "https://ntfy.exemple.test"
        )
        # Appliquée à son propre résultat, elle le rend inchangé.
        self.assertEqual(ci.ntfy_config(production(), text), text)

    def test_ntfy_from_development_https_to_production(self):
        dev = ci.ntfy_config(supplied())
        keys = nm.read_yml_keys(ci.ntfy_config(production(), dev))
        for key in ("listen-https", "cert-file", "key-file"):
            self.assertNotIn(key, keys)
        self.assertEqual(keys["listen-http"], "127.0.0.1:8080")

    def test_development_ntfy_is_unchanged(self):
        keys = nm.read_yml_keys(ci.ntfy_config(answers()))
        self.assertNotIn("behind-proxy", keys)
        self.assertNotIn("web-root", keys)

    def test_ntfy_block_in_production(self):
        ans = production(
            tls="supplied", acme=None, cert_pem=WILD_CERT, key_pem=WILD_KEY
        )
        plan = ci.plan_install(base_facts(), ans, NOW)
        block = "\n".join(ci._ntfy_block(plan))
        self.assertIn("  NTFY_PORT=8080\n", block)
        self.assertIn("  NTFY_BASE_URL=https://ntfy.exemple.test\n", block)
        self.assertNotIn("NTFY_HTTPS_PORT", block)
        self.assertNotIn("NTFY_CERT_FILE", block)
        self.assertEqual(plan.new_state["services"]["ntfy"]["tls_files"], [])

    # --- Ports et pare-feu ------------------------------------------------

    def test_firewall_rules_production_both_services(self):
        self.assertEqual(
            ci.firewall_rules(production()),
            (
                rule("tcp", "80", "nginx"),
                rule("tcp", "443", "nginx"),
                rule("udp", "3478", "coturn"),
                rule("tcp", "3478", "coturn"),
                rule("tcp", "5349", "coturn"),
                rule("udp", "49152:65535", "coturn"),
            ),
        )
        ports = [r.port for r in ci.firewall_rules(production(ntfy_port=8090))]
        self.assertNotIn("8090", ports)
        self.assertNotIn("8080", ports)

    def test_firewall_rules_production_coturn_only(self):
        self.assertEqual(
            ci.firewall_rules(coturn_only()),
            (
                rule("tcp", "80", "certbot"),
                rule("udp", "3478", "coturn"),
                rule("tcp", "3478", "coturn"),
                rule("tcp", "5349", "coturn"),
                rule("udp", "49152:65535", "coturn"),
            ),
        )
        # nginx installé pour le seul défi ACME : il n'écoute que sur 80.
        self.assertEqual(
            ci.firewall_rules(coturn_only(acme="http-nginx", nginx="install"))[
                0
            ],
            rule("tcp", "80", "nginx"),
        )
        self.assertNotIn(
            rule("tcp", "443", "nginx"),
            ci.firewall_rules(coturn_only(acme="http-nginx", nginx="install")),
        )
        # DNS-01 n'ouvre rien pour le certificat.
        dns = coturn_only(
            acme="dns", dns_plugin="ovh", dns_credentials="dns_ovh_key = x\n"
        )
        self.assertEqual(
            [r.service for r in ci.firewall_rules(dns)], ["coturn"] * 4
        )

    def test_needed_ports_production(self):
        ports = ci.needed_ports(production())
        self.assertIn(("tcp", 80, "nginx"), ports)
        self.assertIn(("tcp", 443, "nginx"), ports)
        self.assertIn(("tcp", 5349, "coturn"), ports)
        # Le port de boucle locale de ntfy n'est pas une ouverture, mais il
        # doit être libre : ntfy y écoute.
        self.assertIn(("tcp", 8080, "ntfy"), ports)
        self.assertIn(("tcp", 80, "certbot"), ci.needed_ports(coturn_only()))

    def test_existing_nginx_holds_its_ports_without_refusal(self):
        facts = base_facts(
            busy_ports=(("tcp", 80, "nginx"), ("tcp", 443, "nginx"))
        )
        ci.plan_install(facts, production(nginx="existing"), NOW)
        refusal = self.refusal(
            base_facts(busy_ports=(("tcp", 443, "apache2"),)), production()
        )
        self.assertEqual(refusal.key, "call_infra_port_busy")
        self.assertEqual(refusal.values["process"], "apache2")

    def test_ntfy_port_clashing_with_nginx_is_refused(self):
        refusal = self.refusal(base_facts(), production(ntfy_port=443))
        self.assertEqual(refusal.key, "call_infra_bad_value")

    def test_firewall_labels_for_nginx_and_certbot(self):
        for label in ("nginx", "certbot", "coturn", "ntfy"):
            ci._check_rule(rule("tcp", "80", label))
        with self.assertRaises(ValueError):
            ci._check_rule(rule("tcp", "80", "apache"))
        state = {
            "firewall": {
                "kind": "ufw",
                "rules": [["tcp", "80", "nginx"], ["tcp", "80", "certbot"]],
            }
        }
        self.assertEqual(
            ci.rules_from_state(state),
            (rule("tcp", "80", "nginx"), rule("tcp", "80", "certbot")),
        )
        record = ci.firewall_record("ufw", "@@FIREWALL_ADDED tcp 443 nginx\n")
        self.assertEqual(record["rules"], [["tcp", "443", "nginx"]])

    def test_check_reads_back_nginx_and_certbot_rules(self):
        lines = (
            "ufw allow 443/tcp comment 'erplibre-call nginx'\n"
            "ufw allow 80/tcp comment 'erplibre-call certbot'\n"
            "ufw allow 8443/tcp comment 'erplibre-call apache'\n"
        )
        done = subprocess.run(
            ["sed", "-n", "-E", ci._CHECK_UFW_SED],
            input=lines,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            done.stdout,
            "@@FIREWALL_RULE ufw tcp 443 nginx\n"
            "@@FIREWALL_RULE ufw tcp 80 certbot\n",
        )
        nft = '\t\ttcp dport 443 accept comment "erplibre-call nginx" # handle 7\n'
        done = subprocess.run(
            ["sed", "-n", "-E", ci._CHECK_NFT_SED],
            input=nft,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            done.stdout, "@@FIREWALL_RULE nftables tcp 443 nginx\n"
        )

    # --- État -------------------------------------------------------------

    def test_new_state_mode_and_settings(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        self.assertEqual(plan.new_state["mode"], "production")
        coturn = plan.new_state["services"]["coturn"]["settings"]
        ntfy = plan.new_state["services"]["ntfy"]["settings"]
        self.assertEqual(coturn["turn_name"], "turn.exemple.test")
        self.assertEqual(ntfy["ntfy_name"], "ntfy.exemple.test")
        self.assertEqual(ntfy["base_url"], "https://ntfy.exemple.test")
        self.assertEqual(coturn["acme"], "http-nginx")
        self.assertIs(ntfy["nginx"], True)
        self.assertFalse(ntfy["web"])

    def test_lot_1_state_reads_back_as_development(self):
        state = installed_state(answers())
        del state["mode"]
        back = ci.state_answers(state)
        self.assertEqual(back.mode, "development")
        self.assertIsNone(back.ntfy_name)
        self.assertFalse(back.turns_443)
        # Les réglages d'un état de lot 1 n'ont pas changé de forme.
        self.assertNotIn(
            "turn_name",
            installed_state(answers())["services"]["coturn"]["settings"],
        )

    def test_production_round_trip(self):
        cases = (
            production(max_port=65535, ntfy_web=True, ntfy_port=8090),
            coturn_only(
                acme="dns",
                dns_plugin="rfc2136",
                dns_credentials="dns_rfc2136_secret = Invente\n",
                turns_443=True,
                max_port=65535,
                external_ip="203.0.113.7",
            ),
            production(
                tls="supplied",
                acme=None,
                cert_pem=WILD_CERT,
                key_pem=WILD_KEY,
                max_port=65535,
                ntfy_port=8080,
                email="",
            ),
        )
        for ans in cases:
            with self.subTest(ans=ans):
                plan = ci.plan_install(base_facts(), ans, NOW)
                back = ci.state_answers(ci.written_state(plan, STAMP))
                # Un nginx installé par l'outil se relit comme existant.
                self.assertEqual(
                    back,
                    dataclasses.replace(
                        ans,
                        cert_pem=None,
                        key_pem=None,
                        dns_credentials=None,
                        nginx="existing" if ans.nginx else None,
                    ),
                )

    def installed(self, ans):
        return production_installed(ans)

    def test_rerun_with_the_same_production_answers(self):
        for ans in (
            production(),
            production(
                tls="supplied", acme=None, cert_pem=WILD_CERT, key_pem=WILD_KEY
            ),
            coturn_only(turns_443=True),
        ):
            with self.subTest(ans=ans):
                facts = self.installed(ans)
                # Le nginx que l'outil a installé existe à la relance.
                if ans.nginx:
                    ans = dataclasses.replace(ans, nginx="existing")
                self.assertTrue(ci.plan_install(facts, ans, NOW).nothing_to_do)

    def test_switching_mode_is_something_to_do(self):
        dev = answers()
        facts = TestPlan.both_installed(self, dev)
        prod = production(public_name="turn.exemple.test")
        self.assertFalse(
            ci.plan_install(
                facts, dataclasses.replace(prod, nginx="existing"), NOW
            ).nothing_to_do
        )


NGINX_PROBE = DEBIAN_PROBE.replace(
    "@@FIREWALL none\n",
    "@@NGINX active debian\n"
    "@@NGINX_NAME _ /etc/nginx/sites-enabled/default\n"
    "@@NGINX_NAME ntfy.exemple.test /etc/nginx/sites-enabled/x\n"
    "@@NGINX_NAME *.exemple.test /etc/nginx/sites-enabled/joker\n"
    "@@CERTBOT 4.0.0\n"
    "@@CERTBOT_PLUGIN cloudflare\n"
    "@@LINEAGE erplibre-call turn.exemple.test ntfy.exemple.test\n"
    "@@HELD erplibre-call\n"
    "@@AUTHENTICATOR erplibre-call dns-cloudflare\n"
    "@@FIREWALL none\n",
)


class TestProductionProbe(unittest.TestCase):
    """Sonde de production : nginx (état, disposition, noms des sites
    étrangers), certbot (version, greffons DNS, lignée, fichier mis de
    côté) et leur refus avant toute installation."""

    def test_parse_nginx_and_certbot_lines(self):
        facts = ci.parse_probe(NGINX_PROBE)
        self.assertEqual(
            facts.nginx,
            nginx_facts(
                names=(
                    ("_", "/etc/nginx/sites-enabled/default"),
                    ("ntfy.exemple.test", "/etc/nginx/sites-enabled/x"),
                    ("*.exemple.test", "/etc/nginx/sites-enabled/joker"),
                )
            ),
        )
        self.assertEqual(
            facts.certbot,
            certbot_facts(
                lineage=("turn.exemple.test", "ntfy.exemple.test"),
                held=True,
                plugins=("cloudflare",),
                authenticator="dns-cloudflare",
            ),
        )

    def test_nginx_enabled_state(self):
        text = NGINX_PROBE.replace(
            "@@NGINX active debian\n",
            "@@NGINX inactive debian\n@@NGINX_ENABLED disabled\n",
        )
        facts = ci.parse_probe(text)
        self.assertEqual(facts.nginx["state"], "inactive")
        self.assertEqual(facts.nginx["enabled"], "disabled")
        bad = text.replace("disabled", "dis abled;x")
        self.assertIsNone(ci.parse_probe(bad).nginx["enabled"])

    def test_existing_nginx_records_how_it_was_found(self):
        # Les installateurs activent et démarrent nginx : la
        # désinstallation doit savoir ce qu'il était avant l'outil.
        facts = base_facts(
            nginx=nginx_facts(state="inactive", enabled="disabled")
        )
        ans = production(nginx="existing")
        record = ci.plan_install(facts, ans, NOW).new_state["nginx"]
        self.assertIs(record["was_active"], False)
        self.assertEqual(record["was_enabled"], "disabled")
        # La relance le trouve actif et activé : l'état fait foi.
        state = ci.written_state(ci.plan_install(facts, ans, NOW), STAMP)
        again = base_facts(
            nginx=nginx_facts(enabled="enabled"), state=state
        )
        record = ci.plan_install(again, ans, NOW).new_state["nginx"]
        self.assertIs(record["was_active"], False)
        self.assertEqual(record["was_enabled"], "disabled")
        # Posé par l'outil : rien à remettre, la purge l'emporte.
        record = ci.plan_install(base_facts(), production(), NOW).new_state[
            "nginx"
        ]
        self.assertIsNone(record["was_active"])
        self.assertIsNone(record["was_enabled"])

    def test_an_unknown_authenticator_is_none(self):
        text = NGINX_PROBE.replace("dns-cloudflare", "manual;rm")
        self.assertIsNone(ci.parse_probe(text).certbot["authenticator"])

    def test_a_lot_1_probe_has_neither(self):
        facts = ci.parse_probe(DEBIAN_PROBE)
        self.assertIsNone(facts.nginx)
        self.assertIsNone(facts.certbot)

    def test_absent_nginx_and_certbot(self):
        text = DEBIAN_PROBE.replace(
            "@@FIREWALL none\n",
            "@@NGINX absent -\n@@CERTBOT absent\n@@FIREWALL none\n",
        )
        facts = ci.parse_probe(text)
        self.assertIsNone(facts.nginx)
        self.assertIsNone(facts.certbot)

    def test_pending_nginx_and_certbot(self):
        nginx = {"installed_by_tool": True}
        certbot = {"installed_by_tool": True, "plugins_installed": []}
        text = DEBIAN_PROBE.replace(
            "@@FIREWALL none\n",
            "@@NGINX active debian\n@@CERTBOT 4.0.0\n"
            f"@@PENDING nginx {b64(json.dumps(nginx))}\n"
            f"@@PENDING certbot {b64(json.dumps(certbot))}\n"
            "@@FIREWALL none\n",
        )
        facts = ci.parse_probe(text)
        self.assertEqual(facts.nginx["pending"], nginx)
        self.assertEqual(facts.certbot["pending"], certbot)
        # Une fiche sans nginx sur l'hôte (passage coupé avant son paquet).
        bare = text.replace("@@NGINX active debian\n", "@@NGINX absent -\n")
        self.assertEqual(ci.parse_probe(bare).nginx["state"], "absent")

    def test_name_served_by_a_foreign_site_is_refused(self):
        # Le nom est pris : le refus nomme le fichier qui le sert.
        facts = ci.parse_probe(NGINX_PROBE)
        with self.assertRaises(ci.Refusal) as caught:
            ci.plan_install(facts, production(nginx="existing"), NOW)
        self.assertEqual(caught.exception.key, "call_infra_nginx_name_taken")
        self.assertEqual(
            caught.exception.values,
            {
                "name": "ntfy.exemple.test",
                "file": "/etc/nginx/sites-enabled/x",
            },
        )
        self.assertIn("call_infra_nginx_name_taken", ci_i18n_keys())

    def test_name_match_ignores_case_and_covers_the_turn_name(self):
        text = NGINX_PROBE.replace(
            "ntfy.exemple.test /etc/nginx/sites-enabled/x",
            "TURN.Exemple.test /etc/nginx/sites-enabled/y",
        )
        with self.assertRaises(ci.Refusal) as caught:
            ci.plan_install(ci.parse_probe(text), production(), NOW)
        self.assertEqual(caught.exception.values["name"], "turn.exemple.test")
        self.assertEqual(
            caught.exception.values["file"], "/etc/nginx/sites-enabled/y"
        )

    def test_wildcards_and_the_catch_all_name_are_not_taken(self):
        # nginx préfère un nom exact à un joker et à « _ » : rien à refuser.
        text = NGINX_PROBE.replace(
            "@@NGINX_NAME ntfy.exemple.test /etc/nginx/sites-enabled/x\n", ""
        )
        plan = ci.plan_install(ci.parse_probe(text), production(), NOW)
        self.assertFalse(plan.nothing_to_do)

    def test_nginx_and_certbot_ports_are_not_busy_for_themselves(self):
        self.assertEqual(ci.PROCESSES["nginx"], "nginx")
        self.assertEqual(ci.PROCESSES["certbot"], "certbot")
        facts = base_facts(
            busy_ports=(("tcp", 80, "nginx"), ("tcp", 443, "nginx")),
            nginx=nginx_facts(),
        )
        ci.plan_install(facts, production(nginx="existing"), NOW)
        facts = base_facts(busy_ports=(("tcp", 80, "certbot"),))
        ci.plan_install(facts, coturn_only(), NOW)

    def sandbox(self, nginx_conf, files=None, links=None, dump=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = os.path.join(tmp.name, "root")
        stubs = os.path.join(tmp.name, "stubs")
        write(
            os.path.join(root, "etc/os-release"),
            'ID=debian\nVERSION_ID="13"\n',
            0o644,
        )
        os.makedirs(os.path.join(root, "run/systemd/system"))
        if nginx_conf is not None:
            write(
                os.path.join(root, "etc/nginx/nginx.conf"), nginx_conf, 0o644
            )
        for path, text in (files or {}).items():
            write(os.path.join(root, path.lstrip("/")), text, 0o644)
        for path, target in (links or {}).items():
            os.symlink(target, os.path.join(root, path.lstrip("/")))
        write(
            os.path.join(stubs, "systemctl"),
            "#!/bin/sh\n"
            'case "$1 $2" in\n'
            "  'is-active nginx') echo active ;;\n"
            "  *) exit 3 ;;\n"
            "esac\n",
        )
        write(
            os.path.join(stubs, "certbot"),
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  --version) echo 'certbot 4.0.0' ;;\n"
            "  certificates) cat <<'EOF'\n"
            "Found the following certs:\n"
            "  Certificate Name: erplibre-call\n"
            "    Domains: ntfy.exemple.test turn.exemple.test\n"
            "    Expiry Date: 2027-01-29 10:00:00+00:00 (VALID: 89 days)\n"
            "EOF\n"
            "  ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n",
        )
        write(
            os.path.join(stubs, "dpkg-query"),
            "#!/bin/sh\n"
            "echo 'install ok installed python3-certbot-dns-cloudflare'\n"
            "echo 'deinstall ok config-files python3-certbot-dns-ovh'\n",
        )
        nginx = "#!/bin/sh\nexit 0\n"
        if dump is not None:
            write(os.path.join(tmp.name, "dump"), dump, 0o644)
            nginx = (
                "#!/bin/sh\n"
                f'[ "$1" = -T ] && cat {shlex.quote(tmp.name)}/dump\n'
            )
        write(os.path.join(stubs, "nginx"), nginx)
        write(os.path.join(stubs, "uname"), "#!/bin/sh\necho hote\n")
        for name in ("ss", "ip", "ufw", "nft", "iptables", "pacman"):
            write(os.path.join(stubs, name), "#!/bin/sh\nexit 1\n")
        env = dict(os.environ, PATH=stubs + ":" + os.environ["PATH"])
        done = subprocess.run(
            ["sh", "-c", ci.probe_script(root=root)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return root, ci.parse_probe(done.stdout)

    DEBIAN_NGINX_CONF = (
        "http {\n"
        "    include /etc/nginx/conf.d/*.conf;\n"
        "    include /etc/nginx/sites-enabled/*;\n"
        "}\n"
    )

    def test_probe_reads_nginx_and_certbot_on_the_host(self):
        ours = ci.MARKER + "\nserver { server_name ntfy.exemple.test; }\n"
        _root, facts = self.sandbox(
            self.DEBIAN_NGINX_CONF,
            {
                "/etc/nginx/sites-enabled/x": (
                    "server {\n"
                    "  listen 80;\n"
                    "  server_name ntfy.exemple.test # server_name faux\n"
                    "      www.exemple.test;\n"
                    "  proxy_ssl_server_name on;\n"
                    "}\n"
                ),
                "/etc/nginx/sites-available/erplibre-call-ntfy.conf": ours,
                "/etc/nginx/conf.d/autre.conf": (
                    "server { server_name autre.exemple.test; }\n"
                ),
                "/etc/letsencrypt/live/erplibre-call/cert.pem": "x\n",
                "/etc/letsencrypt/renewal/erplibre-call.conf.erplibre-hold": (
                    "[renewalparams]\nauthenticator = webroot\n"
                ),
            },
            # Le lien de l'outil dans sites-enabled n'est pas un site
            # étranger.
            links={
                "/etc/nginx/sites-enabled/erplibre-call-ntfy.conf": (
                    "../sites-available/erplibre-call-ntfy.conf"
                )
            },
        )
        self.assertEqual(facts.nginx["state"], "active")
        self.assertEqual(facts.nginx["layout"], "debian")
        self.assertFalse(facts.nginx["include"])
        self.assertEqual(
            set(facts.nginx["names"]),
            {
                ("ntfy.exemple.test", "/etc/nginx/sites-enabled/x"),
                ("www.exemple.test", "/etc/nginx/sites-enabled/x"),
                ("autre.exemple.test", "/etc/nginx/conf.d/autre.conf"),
            },
        )
        self.assertEqual(facts.certbot["version"], "4.0.0")
        self.assertEqual(
            facts.certbot["lineage"],
            ("ntfy.exemple.test", "turn.exemple.test"),
        )
        self.assertTrue(facts.certbot["held"])
        self.assertEqual(facts.certbot["plugins"], ("cloudflare",))
        # Lu dans le fichier mis de côté quand il n'y en a pas d'actif.
        self.assertEqual(facts.certbot["authenticator"], "webroot")

    def test_probe_reads_every_included_file_from_nginx_t(self):
        # Un dossier inclus hors des emplacements connus porte un nom pris :
        # « nginx -T » imprime chaque fichier lu, sous son chemin.
        dump = (
            "# configuration file /etc/nginx/nginx.conf:\n"
            "http {\n"
            "    include /etc/nginx/vhosts/*.conf;\n"
            "    include /etc/nginx/erplibre-call.d/*.conf;\n"
            "}\n"
            "\n"
            "# configuration file /etc/nginx/vhosts/a.conf:\n"
            "server { server_name ntfy.exemple.test\n"
            "    www.exemple.test; }\n"
            "\n"
            "# configuration file /etc/nginx/erplibre-call.d/"
            "erplibre-call-ntfy.conf:\n"
            f"{ci.MARKER}\n"
            "server { server_name turn.exemple.test; }\n"
            "\n"
        )
        _root, facts = self.sandbox(
            "http {\n    include /etc/nginx/erplibre-call.d/*.conf;\n}\n",
            # Lu seulement quand nginx -T ne répond pas.
            {"/etc/nginx/conf.d/autre.conf": "server_name autre.test;\n"},
            dump=dump,
        )
        self.assertEqual(
            facts.nginx["names"],
            (
                ("ntfy.exemple.test", "/etc/nginx/vhosts/a.conf"),
                ("www.exemple.test", "/etc/nginx/vhosts/a.conf"),
            ),
        )
        with self.assertRaises(ci.Refusal) as caught:
            ci.plan_install(facts, production(nginx="existing"), NOW)
        self.assertEqual(
            caught.exception.values["file"], "/etc/nginx/vhosts/a.conf"
        )

    def test_probe_skips_the_tool_site(self):
        ours = ci.MARKER + "\nserver { server_name ntfy.exemple.test; }\n"
        _root, facts = self.sandbox(
            self.DEBIAN_NGINX_CONF,
            {"/etc/nginx/sites-enabled/erplibre-call-ntfy.conf": ours},
        )
        self.assertEqual(facts.nginx["names"], ())

    def test_probe_arch_layouts(self):
        bare = "http {\n    server { server_name localhost; }\n}\n"
        _root, facts = self.sandbox(bare)
        self.assertEqual(facts.nginx["layout"], "arch-include")
        self.assertFalse(facts.nginx["include"])
        self.assertEqual(
            facts.nginx["names"], (("localhost", "/etc/nginx/nginx.conf"),)
        )
        ours = "http {\n    include /etc/nginx/erplibre-call.d/*.conf;\n}\n"
        _root, facts = self.sandbox(ours)
        self.assertEqual(facts.nginx["layout"], "arch-include")
        self.assertTrue(facts.nginx["include"])
        confd = "http {\n    include conf.d/*.conf;\n}\n"
        self.assertEqual(self.sandbox(confd)[1].nginx["layout"], "confd")

    def test_probe_without_nginx_conf_says_absent(self):
        _root, facts = self.sandbox(None)
        self.assertIsNone(facts.nginx)


def ci_i18n_keys():
    from script.todo import todo_i18n

    return set(todo_i18n.TRANSLATIONS)


# Bouchon des installateurs de production : note l'ordre des appels (avec
# l'étape de nginx), leur environnement (un fichier par appel), imprime la
# sortie préparée pour cet appel et rend le code demandé. SIGNAL_AT=<étape>
# envoie TERM au script joué pendant cette étape.
STUB_BASH_PROD = r"""#!/bin/sh
name=$(basename "$1" .sh)
tag=$name${NGINX_STAGE:+-$NGINX_STAGE}
echo "$tag" >> "$LOG/order"
cp "$1" "$LOG/$tag.payload"
n=0
while [ -e "$LOG/$tag.$n.env" ]; do n=$((n + 1)); done
env | grep -E '^(TURN|NTFY|NGINX|CERTBOT|RENEWED|ERPLIBRE)_' | sort \
    > "$LOG/$tag.$n.env"
[ -n "${TURN_CERT_FILE:-}" ] && cat "$TURN_CERT_FILE" > "$LOG/$tag.$n.cert"
[ -f "$OUT/$tag" ] && cat "$OUT/$tag"
if [ "${SIGNAL_AT:-}" = "$tag" ]; then
    # Le script joué mène sa session : son pid est le groupe de ce bouchon.
    read -r _ _ _ _ group _ < /proc/$$/stat
    kill -TERM "$group"
fi
v=$(echo "$tag" | tr -- '-.' '__')
eval "exit \${RC_$v:-0}"
"""

LINEAGE = "/etc/letsencrypt/live/erplibre-call"
RENEWAL = "/etc/letsencrypt/renewal/erplibre-call.conf"
CREDENTIALS = "dns_cloudflare_api_token = Inventejeton0123456789abcdef\n"
CERTBOT_ISSUED = (
    "@@CERTBOT staging-ok\n"
    "@@CERTBOT_TIMER certbot.timer present\n"
    f"@@CERTBOT issued {LINEAGE}\n"
)


class TestProductionInstall(unittest.TestCase):
    """Script d'installation de production joué dans une racine
    temporaire : ordre nginx (acme), certbot, crochet, nginx (full), état ;
    arrêt avant l'état à chaque échec ; état consigné par ce passage même."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "root")
        self.log = os.path.join(tmp.name, "log")
        self.out = os.path.join(tmp.name, "out")
        self.stubs = os.path.join(tmp.name, "stubs")
        self.scratch = os.path.join(tmp.name, "scratch")
        for path in (self.root, self.log, self.out, self.scratch):
            os.makedirs(path)
        write(os.path.join(self.stubs, "bash"), STUB_BASH_PROD)
        write(os.path.join(self.stubs, "systemctl"), STUB_SYSTEMCTL)
        for name in ("chown", "useradd"):
            write(
                os.path.join(self.stubs, name),
                '#!/bin/sh\necho "%s $*" >> "$LOG/calls"\n' % name,
            )
        write(os.path.join(self.stubs, "id"), "#!/bin/sh\nexit 0\n")

    def path(self, host_path):
        return self.root + host_path

    def read(self, path):
        with open(path) as handle:
            return handle.read()

    def run_script(self, plan, outputs=None, **env):
        for tag, text in (outputs or {}).items():
            write(os.path.join(self.out, tag), text, 0o644)
        script = ci.install_script(plan, STAMP, root=self.root)
        full = dict(
            os.environ,
            PATH=self.stubs + ":" + os.environ["PATH"],
            LOG=self.log,
            OUT=self.out,
            TMPDIR=self.scratch,
        )
        full.update(env)
        return subprocess.run(
            ["sh", "-c", script],
            capture_output=True,
            text=True,
            env=full,
            timeout=60,
            start_new_session=True,
        )

    def order(self):
        path = os.path.join(self.log, "order")
        return self.read(path).split() if os.path.exists(path) else []

    def env_of(self, tag, n=0):
        return dict(
            line.split("=", 1)
            for line in self.read(
                os.path.join(self.log, f"{tag}.{n}.env")
            ).splitlines()
        )

    def state(self):
        return json.loads(self.read(self.path(ci.STATE_PATH)))

    def assert_no_state(self, done):
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))
        self.assertEqual(ci.marker_lines(done.stdout)[-1], ("SAVED", "no"))

    def lineage_on_disk(self):
        write(self.path(LINEAGE + "/fullchain.pem"), "chaine\n", 0o644)
        write(self.path(LINEAGE + "/privkey.pem"), "cle\n", 0o600)

    # --- Ordre ---------------------------------------------------------

    def test_script_order_acme_certbot_hook_full_state(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        script = ci.install_script(plan, STAMP)
        acme = script.index("NS=acme")
        certbot = script.index('exec bash "$D/install_certbot.sh"')
        guard = script.index("step_rc certbot || fail certbot")
        hook = script.index("RENEWED_LINEAGE=")
        full = script.index("NGINX_STAGE=full")
        state = script.index('> "$STATE.new"')
        self.assertLess(acme, certbot)
        self.assertLess(certbot, guard)
        self.assertLess(guard, hook)
        self.assertLess(hook, full)
        self.assertLess(full, state)
        self.assertEqual(script.count('> "$STATE.new"'), 1)
        self.assertIn("NGINX_ACME_ROOT=/var/lib/erplibre-call-acme", script)
        self.assertIn("CERTBOT_WEBROOT=/var/lib/erplibre-call-acme", script)

    def test_first_run_order_on_the_host(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.order(),
            [
                "install_coturn",
                "install_ntfy",
                "install_nginx-acme",
                "install_certbot",
                "erplibre-call",
                "install_coturn",
                "install_nginx-full",
            ],
        )
        markers = ci.marker_lines(done.stdout)
        self.assertIn(("ACTIVE", "nginx active"), markers)
        self.assertEqual(markers[-1], ("SAVED", "yes"))
        self.assertEqual(os.listdir(self.scratch), [])

    def test_installer_environments(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        acme = self.env_of("install_nginx-acme")
        self.assertEqual(
            acme["NGINX_NAMES"], "turn.exemple.test ntfy.exemple.test"
        )
        self.assertEqual(acme["NGINX_NTFY_NAME"], "ntfy.exemple.test")
        self.assertEqual(acme["NGINX_ACME_ROOT"], ci.ACME_ROOT)
        self.assertEqual(acme["NGINX_INSTALL"], "1")
        # Le paquet Debian inclut sites-enabled : nginx.conf ne change pas.
        self.assertNotIn("NGINX_ADOPT_INCLUDE", acme)
        certbot = self.env_of("install_certbot")
        self.assertEqual(
            certbot["CERTBOT_NAMES"], "turn.exemple.test ntfy.exemple.test"
        )
        self.assertEqual(certbot["CERTBOT_METHOD"], "webroot")
        self.assertEqual(certbot["CERTBOT_WEBROOT"], ci.ACME_ROOT)
        self.assertEqual(certbot["CERTBOT_EMAIL"], "admin@exemple.test")
        self.assertNotIn("CERTBOT_SKIP_STAGING", certbot)
        full = self.env_of("install_nginx-full")
        self.assertEqual(full["NGINX_CERT_FILE"], LINEAGE + "/fullchain.pem")
        self.assertEqual(full["NGINX_KEY_FILE"], LINEAGE + "/privkey.pem")
        self.assertEqual(full["NGINX_UPSTREAM_PORT"], "8080")
        hook = self.env_of("erplibre-call")
        self.assertEqual(hook["RENEWED_LINEAGE"], self.path(LINEAGE))
        self.assertEqual(hook["ERPLIBRE_CALL_ROOT"], self.root)
        # Aucun `export` nu, qui imprimerait l'environnement du script.
        script = ci.install_script(plan, STAMP)
        self.assertNotRegex(script, r"(?m)^\s*export\s*$")
        self.assertNotIn("export PATH", done.stdout)

    # --- Ligne include de nginx.conf -------------------------------------

    INCLUDE_LINE = "+    include /etc/nginx/erplibre-call.d/*.conf;"

    def existing_nginx(self, **nginx):
        return base_facts(
            busy_ports=(("tcp", 22, "sshd"), ("tcp", 80, "nginx")),
            nginx=nginx_facts(**nginx),
        )

    def test_include_line_is_announced_before_it_is_accepted(self):
        # Un nginx.conf qui n'inclut aucun dossier de sites reçoit une
        # ligne : le résumé la montre avant le oui, le script l'accepte.
        facts = self.existing_nginx(layout="arch-include")
        plan = ci.plan_install(facts, production(nginx="existing"), NOW)
        shown = dict(plan.diffs)
        self.assertIn(ci.NGINX_CONF, shown)
        self.assertIn(self.INCLUDE_LINE, shown[ci.NGINX_CONF].splitlines())
        self.assertIn("NGINX_ADOPT_INCLUDE=1", ci.install_script(plan, STAMP))

    def test_no_include_consent_when_nginx_conf_does_not_change(self):
        for nginx in (
            {"layout": "arch-include", "include": True},
            {"layout": "debian"},
            {"layout": "confd"},
        ):
            with self.subTest(nginx=nginx):
                facts = self.existing_nginx(**nginx)
                plan = ci.plan_install(
                    facts, production(nginx="existing"), NOW
                )
                self.assertNotIn(ci.NGINX_CONF, dict(plan.diffs))
                self.assertNotIn(
                    "NGINX_ADOPT_INCLUDE", ci.install_script(plan, STAMP)
                )

    def test_nginx_installed_on_arch_takes_the_include_line(self):
        # Le nginx.conf est celui du paquet que ce passage installe :
        # aucun fichier de l'administrateur à montrer.
        facts = base_facts(family="arch", os_id="arch")
        plan = ci.plan_install(facts, production(), NOW)
        self.assertNotIn(ci.NGINX_CONF, dict(plan.diffs))
        self.assertIn("NGINX_ADOPT_INCLUDE=1", ci.install_script(plan, STAMP))

    def test_missing_include_line_is_never_nothing_to_do(self):
        ans = production()
        there = nginx_facts(layout="arch-include", include=True)
        facts = production_installed(ans, nginx=there)
        ans = dataclasses.replace(ans, nginx="existing")
        self.assertTrue(ci.plan_install(facts, ans, NOW).nothing_to_do)
        gone = nginx_facts(layout="arch-include")
        facts = production_installed(ans, nginx=gone)
        self.assertFalse(ci.plan_install(facts, ans, NOW).nothing_to_do)

    def test_hook_installed_from_the_product_file(self):
        with open(ci.HOOK_SOURCE) as handle:
            self.assertEqual(ci.deploy_hook_text(), handle.read())
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        hook = self.path(ci.HOOK_PATH)
        self.assertEqual(self.read(hook), ci.deploy_hook_text())
        self.assertEqual(stat.S_IMODE(os.stat(hook).st_mode), 0o755)
        self.assertEqual(
            ci.HOOK_PATH, "/etc/letsencrypt/renewal-hooks/deploy/erplibre-call"
        )

    # --- coturn et la lignée --------------------------------------------

    def test_first_run_coturn_without_then_with_the_certificate(self):
        # Pas de TURN_ALT_TLS_PORT tant qu'aucun certificat n'existe ;
        # coturn reprend la lignée après la délivrance. Le crochet ne le
        # peut pas : aucun état ne nomme encore coturn.
        plan = ci.plan_install(base_facts(), coturn_only(turns_443=True), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.order(),
            [
                "install_coturn",
                "install_certbot",
                "erplibre-call",
                "install_coturn",
            ],
        )
        first = self.env_of("install_coturn", 0)
        self.assertNotIn("TURN_CERT_FILE", first)
        self.assertNotIn("TURN_ALT_TLS_PORT", first)
        second = self.env_of("install_coturn", 1)
        self.assertEqual(
            second["TURN_CERT_FILE"], self.path(LINEAGE + "/fullchain.pem")
        )
        self.assertEqual(
            second["TURN_KEY_FILE"], self.path(LINEAGE + "/privkey.pem")
        )
        self.assertEqual(second["TURN_ALT_TLS_PORT"], "443")
        self.assertNotIn("TURN_ALLOW_PRIVATE", second)
        self.assertEqual(
            self.env_of("install_certbot")["CERTBOT_METHOD"], "standalone"
        )

    def test_lineage_already_there_coturn_runs_once_with_it(self):
        self.lineage_on_disk()
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(
            plan,
            {"install_certbot": CERTBOT_ISSUED.replace("issued", "unchanged")},
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        # Le site complet sert déjà le défi : 443 ne tombe pas le temps de
        # certbot.
        self.assertEqual(
            self.order(),
            [
                "install_coturn",
                "install_ntfy",
                "install_nginx-full",
                "install_certbot",
                "erplibre-call",
                "install_nginx-full",
            ],
        )
        coturn = self.env_of("install_coturn")
        self.assertEqual(
            coturn["TURN_CERT_FILE"], self.path(LINEAGE + "/fullchain.pem")
        )
        self.assertEqual(
            self.read(os.path.join(self.log, "install_coturn.0.cert")),
            "chaine\n",
        )

    def test_reinstall_with_a_reissued_lineage_hands_it_to_coturn(self):
        # Pas d'état encore : le crochet ne connaît pas coturn, qui reprend
        # la nouvelle lignée par son installateur.
        self.lineage_on_disk()
        plan = ci.plan_install(base_facts(), coturn_only(), NOW)
        skipped = "@@HOOK coturn-skip not-in-state\n"
        done = self.run_script(
            plan, {"install_certbot": CERTBOT_ISSUED, "erplibre-call": skipped}
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.order().count("install_coturn"), 2)
        self.assertEqual(
            self.env_of("install_coturn", 1)["TURN_CERT_FILE"],
            self.path(LINEAGE + "/fullchain.pem"),
        )

    def test_hook_that_handed_the_lineage_spares_coturn_a_restart(self):
        # Relance : le crochet a copié la lignée et signalé coturn (SIGUSR2)
        # ; aucun second passage de l'installateur, qui le redémarrerait.
        self.lineage_on_disk()
        plan = ci.plan_install(base_facts(), coturn_only(), NOW)
        handed = "@@HOOK signal coturn\n@@HOOK applied\n"
        done = self.run_script(
            plan, {"install_certbot": CERTBOT_ISSUED, "erplibre-call": handed}
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.order().count("install_coturn"), 1)

    # --- Échecs ---------------------------------------------------------

    def test_certbot_failure_stops_before_the_state(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(
            plan,
            {"install_certbot": "@@CERTBOT failed Detail: refus du serveur\n"},
            RC_install_certbot="1",
        )
        self.assert_no_state(done)
        self.assertEqual(self.order()[-1], "install_certbot")
        self.assertIn(("FAILED", "certbot"), ci.marker_lines(done.stdout))
        self.assertTrue(
            os.path.exists(self.path(ci.PENDING_DIR + "/certbot.json"))
        )
        self.assertTrue(
            os.path.exists(self.path(ci.PENDING_DIR + "/nginx.json"))
        )

    def test_each_step_failure_stops_before_the_state(self):
        cases = {
            "RC_install_coturn": "install_coturn",
            "RC_install_ntfy": "install_ntfy",
            "RC_install_nginx_acme": "install_nginx-acme",
            "RC_erplibre_call": "erplibre-call",
            "RC_install_nginx_full": "install_nginx-full",
        }
        for variable, last in cases.items():
            with self.subTest(variable=variable):
                self.tearDown_root()
                plan = ci.plan_install(base_facts(), production(), NOW)
                done = self.run_script(
                    plan,
                    {"install_certbot": CERTBOT_ISSUED},
                    **{variable: "1"},
                )
                self.assert_no_state(done)
                self.assertEqual(self.order()[-1], last)

    def tearDown_root(self):
        for path in (self.root, self.log):
            subprocess.run(["rm", "-rf", path], check=True)
            os.makedirs(path)

    def test_inactive_nginx_leaves_no_state(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(
            plan, {"install_certbot": CERTBOT_ISSUED}, ACTIVE_nginx="failed"
        )
        self.assert_no_state(done)
        self.assertIn(("ACTIVE", "nginx failed"), ci.marker_lines(done.stdout))

    def test_renewal_file_held_again_when_a_later_step_fails(self):
        # install_certbot.sh remet le fichier mis de côté ; un échec après
        # lui (crochet, nginx full, unité inactive) le remet de côté, faute
        # d'état qui consigne Let's Encrypt.
        unheld = f"@@CERTBOT_UNHELD {RENEWAL}\n" + CERTBOT_ISSUED
        for env in ({"RC_erplibre_call": "1"}, {"ACTIVE_nginx": "failed"}):
            with self.subTest(env=env):
                self.tearDown_root()
                write(self.path(RENEWAL), "renouvellement\n", 0o644)
                plan = ci.plan_install(base_facts(), production(), NOW)
                done = self.run_script(
                    plan, {"install_certbot": unheld}, **env
                )
                self.assert_no_state(done)
                self.assertFalse(os.path.exists(self.path(RENEWAL)))
                self.assertEqual(
                    self.read(self.path(RENEWAL + ".erplibre-hold")),
                    "renouvellement\n",
                )
                self.assertIn(
                    ("CERTBOT_REHELD", RENEWAL), ci.marker_lines(done.stdout)
                )

    def test_renewal_file_held_again_when_the_run_is_interrupted(self):
        # Une session coupée (HUP, INT, TERM) après certbot laisse le même
        # trou qu'un échec : aucun état ne consigne Let's Encrypt.
        unheld = f"@@CERTBOT_UNHELD {RENEWAL}\n" + CERTBOT_ISSUED
        write(self.path(RENEWAL), "renouvellement\n", 0o644)
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(
            plan, {"install_certbot": unheld}, SIGNAL_AT="erplibre-call"
        )
        self.assertEqual(done.returncode, 129, done.stdout + done.stderr)
        self.assertFalse(os.path.exists(self.path(ci.STATE_PATH)))
        self.assertFalse(os.path.exists(self.path(RENEWAL)))
        self.assertEqual(
            self.read(self.path(RENEWAL + ".erplibre-hold")),
            "renouvellement\n",
        )
        self.assertNotIn("install_nginx-full", self.order())
        self.assertEqual(os.listdir(self.scratch), [])

    def test_renewal_file_left_alone_when_certbot_held_it_itself(self):
        write(self.path(RENEWAL + ".erplibre-hold"), "garde\n", 0o644)
        out = (
            f"@@CERTBOT_UNHELD {RENEWAL}\n@@CERTBOT_REHELD {RENEWAL}\n"
            "@@CERTBOT failed Detail: refus\n"
        )
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(
            plan, {"install_certbot": out}, RC_install_certbot="1"
        )
        self.assert_no_state(done)
        self.assertEqual(
            [
                v
                for n, v in ci.marker_lines(done.stdout)
                if n == "CERTBOT_REHELD"
            ],
            [RENEWAL],
        )

    # --- DNS, certificat fourni -----------------------------------------

    def dns_answers(self, **changes):
        values = dict(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        values.update(changes)
        return coturn_only(**values)

    def test_dns_credentials_only_in_base64(self):
        plan = ci.plan_install(base_facts(), self.dns_answers(), NOW)
        script = ci.install_script(plan, STAMP)
        self.assertNotIn("Inventejeton0123456789abcdef", script)
        self.assertNotIn("dns_cloudflare_api_token", script)
        self.assertIn(b64(CREDENTIALS), script)
        self.assertNotIn(
            "Inventejeton", json.dumps(ci.written_state(plan, STAMP))
        )

    def test_dns_credentials_placed_root_0600(self):
        plan = ci.plan_install(base_facts(), self.dns_answers(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        path = self.path("/etc/erplibre-call/dns/cloudflare.ini")
        self.assertEqual(self.read(path), CREDENTIALS)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700
        )
        certbot = self.env_of("install_certbot")
        self.assertEqual(certbot["CERTBOT_METHOD"], "dns")
        self.assertEqual(certbot["CERTBOT_DNS_PLUGIN"], "cloudflare")
        self.assertEqual(
            certbot["CERTBOT_DNS_CREDENTIALS"],
            "/etc/erplibre-call/dns/cloudflare.ini",
        )
        self.assertNotIn("install_nginx", " ".join(self.order()))
        record = self.state()["certbot"]
        self.assertEqual(
            record["dns_credentials"], "/etc/erplibre-call/dns/cloudflare.ini"
        )
        self.assertEqual(record["plugin"], "cloudflare")

    def supplied_production(self):
        return production(
            tls="supplied", acme=None, cert_pem=WILD_CERT, key_pem=WILD_KEY
        )

    def test_supplied_production_skips_certbot_and_hook(self):
        plan = ci.plan_install(base_facts(), self.supplied_production(), NOW)
        script = ci.install_script(plan, STAMP)
        self.assertNotIn("install_certbot", script)
        self.assertNotIn("RENEWED_LINEAGE", script)
        self.assertNotIn(ci.HOOK_PATH, script)
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.order(),
            ["install_coturn", "install_ntfy", "install_nginx-full"],
        )
        for name, text in (("site.crt", WILD_CERT), ("site.key", WILD_KEY)):
            path = self.path("/etc/erplibre-call/tls/" + name)
            self.assertEqual(self.read(path), text)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        full = self.env_of("install_nginx-full")
        self.assertEqual(
            full["NGINX_CERT_FILE"], "/etc/erplibre-call/tls/site.crt"
        )
        self.assertEqual(
            full["NGINX_KEY_FILE"], "/etc/erplibre-call/tls/site.key"
        )
        self.assertEqual(full["NGINX_ACME_ROOT"], "")
        # coturn reçoit le même certificat, qu'il copie en turn.{crt,key}.
        self.assertEqual(
            self.read(os.path.join(self.log, "install_coturn.0.cert")),
            WILD_CERT,
        )
        state = self.state()
        self.assertNotIn("certbot", state)
        self.assertNotIn("hook", state)
        self.assertEqual(
            state["nginx"]["tls_files"],
            [
                "/etc/erplibre-call/tls/site.crt",
                "/etc/erplibre-call/tls/site.key",
            ],
        )

    # --- État -----------------------------------------------------------

    def test_state_records_what_the_installers_reported(self):
        facts = base_facts(family="arch", os_id="arch")
        ans = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        plan = ci.plan_install(facts, ans, NOW)
        nginx_out = (
            "@@NGINX_INSTALLED 1\n"
            "@@NGINX_LAYOUT arch-include\n"
            "@@NGINX_INCLUDE /etc/nginx/nginx.conf\n"
            "@@NGINX_BACKUP /etc/nginx/nginx.conf.bak-20261031101500\n"
            "@@NGINX_SITE /etc/nginx/erplibre-call.d/erplibre-call-ntfy.conf\n"
            "@@NGINX active\n"
        )
        certbot_out = (
            "@@CERTBOT_INSTALLED 1\n"
            "@@CERTBOT_PLUGIN_INSTALLED certbot-dns-cloudflare\n"
            "@@CERTBOT staging-ok\n"
            "@@CERTBOT_TIMER certbot-renew.timer added\n"
            f"@@CERTBOT issued {LINEAGE}\n"
        )
        done = self.run_script(
            plan,
            {"install_nginx-full": nginx_out, "install_certbot": certbot_out},
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertEqual(state, ci.installed_state(plan, STAMP, done.stdout))
        nginx = state["nginx"]
        self.assertTrue(nginx["installed_by_tool"])
        self.assertEqual(nginx["layout"], "arch-include")
        self.assertEqual(
            nginx["site"], "/etc/nginx/erplibre-call.d/erplibre-call-ntfy.conf"
        )
        self.assertIsNone(nginx["link"])
        self.assertEqual(nginx["include"], "/etc/nginx/nginx.conf")
        self.assertEqual(
            nginx["backup"], "/etc/nginx/nginx.conf.bak-20261031101500"
        )
        certbot = state["certbot"]
        self.assertTrue(certbot["installed_by_tool"])
        self.assertEqual(
            certbot["plugins_installed"], ["certbot-dns-cloudflare"]
        )
        self.assertEqual(
            certbot["timer"], {"unit": "certbot-renew.timer", "added": True}
        )
        self.assertEqual(certbot["method"], "dns")
        self.assertEqual(
            certbot["names"], ["turn.exemple.test", "ntfy.exemple.test"]
        )
        self.assertEqual(certbot["lineage"], LINEAGE)
        self.assertEqual(
            state["hook"], {"path": ci.HOOK_PATH, "installed_by_tool": True}
        )
        self.assertFalse(
            os.path.exists(self.path(ci.PENDING_DIR + "/nginx.json"))
        )
        self.assertFalse(
            os.path.exists(self.path(ci.PENDING_DIR + "/certbot.json"))
        )

    def test_state_keeps_plan_values_without_markers(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertEqual(state, ci.installed_state(plan, STAMP, done.stdout))
        nginx = state["nginx"]
        self.assertEqual(nginx["layout"], "debian")
        self.assertEqual(
            nginx["link"], "/etc/nginx/sites-enabled/erplibre-call-ntfy.conf"
        )
        self.assertIsNone(nginx["include"])
        self.assertIsNone(nginx["backup"])
        self.assertEqual(
            state["certbot"]["timer"],
            {"unit": "certbot.timer", "added": False},
        )

    def test_layout_reported_by_the_installer_wins(self):
        # Le plan prévoit « debian » sur un nginx absent de la sonde ; un
        # paquet amont de nginx n'inclut que conf.d, ce qu'imprime
        # install_nginx.sh.
        plan = ci.plan_install(base_facts(), production(), NOW)
        self.assertEqual(plan.new_state["nginx"]["layout"], "debian")
        out = (
            "@@NGINX_INSTALLED 1\n@@NGINX_LAYOUT confd\n"
            "@@NGINX_SITE /etc/nginx/conf.d/erplibre-call-ntfy.conf\n"
        )
        done = self.run_script(
            plan,
            {"install_nginx-acme": out, "install_certbot": CERTBOT_ISSUED},
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertEqual(state, ci.installed_state(plan, STAMP, done.stdout))
        self.assertEqual(state["nginx"]["layout"], "confd")
        self.assertEqual(
            state["nginx"]["site"], "/etc/nginx/conf.d/erplibre-call-ntfy.conf"
        )
        self.assertIsNone(state["nginx"]["link"])

    def test_a_marker_outside_its_form_is_ignored(self):
        plan = ci.plan_install(base_facts(), production(), NOW)
        out = (
            "@@NGINX_LAYOUT ailleurs\n"
            "@@NGINX_BACKUP /etc/nginx/x;rm -rf /\n"
        )
        cert = CERTBOT_ISSUED.replace("certbot.timer present", "x|y added")
        done = self.run_script(
            plan, {"install_nginx-full": out, "install_certbot": cert}
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertEqual(state, ci.installed_state(plan, STAMP, done.stdout))
        self.assertEqual(state["nginx"]["layout"], "debian")
        self.assertIsNone(state["nginx"]["backup"])
        self.assertIsNone(state["certbot"]["timer"])

    def test_pending_origin_survives_a_failed_run(self):
        # Un premier passage installe nginx puis certbot échoue : la relance
        # voit nginx présent, la fiche dit qu'il vient de l'outil.
        plan = ci.plan_install(base_facts(), production(), NOW)
        self.run_script(plan, RC_install_certbot="1")
        pending = json.loads(
            self.read(self.path(ci.PENDING_DIR + "/nginx.json"))
        )
        self.assertEqual(
            pending,
            {"installed_by_tool": True, "was_active": None, "was_enabled": None},
        )
        facts = base_facts(
            nginx=dict(nginx_facts(), pending=pending),
            busy_ports=(("tcp", 80, "nginx"),),
        )
        again = ci.plan_install(facts, production(nginx="existing"), NOW)
        self.assertTrue(again.new_state["nginx"]["installed_by_tool"])
        certbot = json.loads(
            self.read(self.path(ci.PENDING_DIR + "/certbot.json"))
        )
        self.assertEqual(
            certbot, {"installed_by_tool": True, "plugins_installed": []}
        )

    def test_plugins_of_a_failed_run_stay_recorded(self):
        # Un état sans greffon, une relance DNS qui pose le paquet puis
        # échoue : la suivante le trouve installé, la fiche seule le dit.
        ans = production()
        prior = production_installed(ans)
        dns = dataclasses.replace(
            ans,
            nginx="existing",
            acme="dns",
            dns_plugin="cloudflare",
            dns_credentials=CREDENTIALS,
        )
        pending = {
            "installed_by_tool": False,
            "plugins_installed": ["python3-certbot-dns-cloudflare"],
        }
        facts = dataclasses.replace(
            prior,
            certbot=dict(
                prior.certbot, plugins=("cloudflare",), pending=pending
            ),
        )
        record = ci.plan_install(facts, dns, NOW).new_state["certbot"]
        self.assertEqual(
            record["plugins_installed"], ["python3-certbot-dns-cloudflare"]
        )

    def test_other_dns_credentials_leave_after_certbot(self):
        dns_dir = ci.DNS_DIR
        for name in ("google", "cloudflare"):
            write(self.path(f"{dns_dir}/{name}.ini"), "x\n", 0o600)
        ans = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        plan = ci.plan_install(base_facts(), ans, NOW)
        # certbot en échec : l'ancien fichier de renouvellement nomme
        # encore l'ancien greffon, ses identifiants restent.
        self.run_script(plan, RC_install_certbot="1")
        self.assertTrue(os.path.exists(self.path(f"{dns_dir}/google.ini")))
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            sorted(os.listdir(self.path(dns_dir))), ["cloudflare.ini"]
        )
        # HTTP-01 : plus aucun identifiant DNS sur l'hôte.
        plan = ci.plan_install(base_facts(), production(), NOW)
        done = self.run_script(plan, {"install_certbot": CERTBOT_ISSUED})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(os.path.exists(self.path(dns_dir)))

    def test_fiches_of_a_failed_production_run_are_carried(self):
        # Un passage de production pose nginx, certbot et un greffon puis
        # échoue ; la relance part en développement : l'état consigne ce
        # que les fiches disent, la désinstallation le défait.
        nginx_pending = {"installed_by_tool": True}
        certbot_pending = {
            "installed_by_tool": True,
            "plugins_installed": ["python3-certbot-dns-cloudflare"],
        }
        for layout in ("debian", "arch-include"):
            with self.subTest(layout=layout):
                facts = base_facts(
                    nginx=dict(nginx_facts(layout=layout), pending=nginx_pending),
                    certbot=dict(certbot_facts(), pending=certbot_pending),
                    busy_ports=(("tcp", 80, "nginx"),),
                )
                plan = ci.plan_install(facts, answers(), NOW)
                nginx = plan.new_state["nginx"]
                self.assertIs(nginx["installed_by_tool"], True)
                self.assertEqual(nginx["layout"], layout)
                self.assertEqual(
                    (nginx["site"], nginx["link"], nginx["include"]),
                    ci._nginx_paths(layout),
                )
                certbot = plan.new_state["certbot"]
                self.assertIs(certbot["installed_by_tool"], True)
                self.assertEqual(
                    certbot["plugins_installed"],
                    ["python3-certbot-dns-cloudflare"],
                )
                script = ci.uninstall_script(plan.new_state, False, STAMP)
                self.assertIn("pkg_purge python3-certbot-dns-cloudflare", script)
                self.assertIn(nginx["site"], script)
                self.assertIn(ci.HOOK_PATH, script)
        # Un certificat fourni en production : nginx sert, certbot non.
        facts = base_facts(
            nginx=nginx_facts(),
            certbot=dict(certbot_facts(), pending=certbot_pending),
            busy_ports=(("tcp", 80, "nginx"), ("tcp", 443, "nginx")),
        )
        ans = production(
            tls="supplied",
            acme=None,
            nginx="existing",
            cert_pem=WILD_CERT,
            key_pem=WILD_KEY,
        )
        plan = ci.plan_install(facts, ans, NOW)
        self.assertEqual(
            plan.new_state["certbot"]["plugins_installed"],
            ["python3-certbot-dns-cloudflare"],
        )

    def test_carried_fiches_leave_with_the_state_written(self):
        write(
            self.path(ci.PENDING_DIR + "/certbot.json"),
            json.dumps({"installed_by_tool": True, "plugins_installed": []}),
            0o600,
        )
        facts = base_facts(
            certbot=dict(
                certbot_facts(),
                pending={"installed_by_tool": True, "plugins_installed": []},
            )
        )
        plan = ci.plan_install(facts, answers(), NOW)
        installed = TestPlan.both_installed(self, answers())
        self.assertFalse(
            ci.plan_install(
                dataclasses.replace(installed, certbot=facts.certbot),
                answers(),
                NOW,
            ).nothing_to_do
        )
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(
            os.path.exists(self.path(ci.PENDING_DIR + "/certbot.json"))
        )
        self.assertIs(self.state()["certbot"]["installed_by_tool"], True)

    def test_a_kept_record_gains_the_plugins_of_its_fiche(self):
        ans = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        prior = production_installed(ans)
        pending = {
            "installed_by_tool": False,
            "plugins_installed": ["python3-certbot-dns-google"],
        }
        facts = dataclasses.replace(
            prior, certbot=dict(prior.certbot, pending=pending)
        )
        plan = ci.plan_install(facts, answers(), NOW)
        self.assertEqual(
            sorted(plan.new_state["certbot"]["plugins_installed"]),
            ["python3-certbot-dns-cloudflare", "python3-certbot-dns-google"],
        )

    def test_plugin_origin_from_the_probe(self):
        ans = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        fresh = ci.plan_install(base_facts(), ans, NOW).new_state["certbot"]
        self.assertTrue(fresh["installed_by_tool"])
        self.assertEqual(
            fresh["plugins_installed"], ["python3-certbot-dns-cloudflare"]
        )
        there = base_facts(certbot=certbot_facts(plugins=("cloudflare",)))
        record = ci.plan_install(there, ans, NOW).new_state["certbot"]
        self.assertFalse(record["installed_by_tool"])
        self.assertEqual(record["plugins_installed"], [])

    def test_admin_added_written_by_the_install_run(self):
        # L'état de ce passage porte admin_added, sans attendre un second
        # passage root.
        foreign = 'listen-http: ":8080"\n'
        write(self.path(ci.NTFY_CONFIG), foreign, 0o644)
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, foreign, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        plan = ci.plan_install(
            facts, answers(services=frozenset({"ntfy"})), NOW
        )
        self.assertEqual(plan.adopt, ("ntfy",))
        done = self.run_script(
            plan, {"install_ntfy": "@@ADMIN_PASSWORD Ab1\n"}
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertIs(state["services"]["ntfy"]["admin_added"], True)
        self.assertEqual(state, ci.installed_state(plan, STAMP, done.stdout))
        self.assertEqual(
            state,
            ci.mark_admin_added(ci.written_state(plan, STAMP), done.stdout),
        )
        # Le mot de passe reste sur la sortie, nulle part sur le disque.
        self.assertIn("@@ADMIN_PASSWORD Ab1", done.stdout)
        self.assertNotIn("Ab1", self.read(self.path(ci.STATE_PATH)))

    def test_no_admin_added_without_the_password_line(self):
        foreign = 'listen-http: ":8080"\n'
        write(self.path(ci.NTFY_CONFIG), foreign, 0o644)
        facts = base_facts(
            ntfy=service(ci.NTFY_CONFIG, foreign, unit="ntfy"),
            busy_ports=(("tcp", 8080, "ntfy"),),
        )
        plan = ci.plan_install(
            facts, answers(services=frozenset({"ntfy"})), NOW
        )
        done = self.run_script(plan)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        state = self.state()
        self.assertNotIn("admin_added", state["services"]["ntfy"])
        self.assertEqual(state, ci.written_state(plan, STAMP))

    def test_dropin_recorded_with_turns_443(self):
        record = ci.plan_install(
            base_facts(), coturn_only(turns_443=True), NOW
        ).new_state["services"]["coturn"]
        self.assertEqual(
            record["dropin"],
            "/etc/systemd/system/coturn.service.d/erplibre-call.conf",
        )
        arch = base_facts(family="arch", os_id="arch")
        record = ci.plan_install(
            arch, coturn_only(turns_443=True), NOW
        ).new_state["services"]["coturn"]
        self.assertEqual(
            record["dropin"],
            "/etc/systemd/system/turnserver.service.d/erplibre-call.conf",
        )
        record = ci.plan_install(base_facts(), coturn_only(), NOW).new_state[
            "services"
        ]["coturn"]
        self.assertIsNone(record["dropin"])

    # --- Relance --------------------------------------------------------

    def test_rerun_with_an_unchanged_lineage(self):
        ans = production()
        facts = production_installed(ans)
        ans = dataclasses.replace(ans, nginx="existing")
        self.assertTrue(ci.plan_install(facts, ans, NOW).nothing_to_do)
        changed = dataclasses.replace(ans, ntfy_web=True)
        plan = ci.plan_install(facts, changed, NOW)
        self.assertFalse(plan.nothing_to_do)
        self.assertIn("CERTBOT_SKIP_STAGING=1", ci.install_script(plan, STAMP))

    def test_rerun_with_another_lineage_runs_staging(self):
        ans = production()
        others = {
            "names": certbot_facts(lineage=("turn.exemple.test",)),
            "held": certbot_facts(
                lineage=("turn.exemple.test", "ntfy.exemple.test"), held=True
            ),
            "none": certbot_facts(),
        }
        for name, certbot in others.items():
            with self.subTest(name):
                facts = production_installed(ans, certbot=certbot)
                plan = ci.plan_install(
                    facts, dataclasses.replace(ans, nginx="existing"), NOW
                )
                self.assertFalse(plan.nothing_to_do)
                self.assertNotIn(
                    "CERTBOT_SKIP_STAGING", ci.install_script(plan, STAMP)
                )

    def test_method_change_with_the_same_names_forces_a_renewal(self):
        # Sans renouvellement forcé, certbot dit « pas à échéance » et son
        # fichier de renouvellement garde l'ancien authentificateur.
        ans = production()
        facts = production_installed(ans)
        dns = dataclasses.replace(
            ans,
            nginx="existing",
            acme="dns",
            dns_plugin="cloudflare",
            dns_credentials=CREDENTIALS,
        )
        plan = ci.plan_install(facts, dns, NOW)
        self.assertFalse(plan.nothing_to_do)
        self.assertFalse(plan.lineage_unchanged)
        self.assertTrue(plan.certbot_force)
        script = ci.install_script(plan, STAMP)
        self.assertIn("CERTBOT_FORCE_RENEWAL=1", script)
        self.assertNotIn("CERTBOT_SKIP_STAGING", script)
        # Même méthode, autre greffon : renouvellement forcé aussi.
        facts = production_installed(dns)
        google = dataclasses.replace(dns, dns_plugin="google")
        self.assertTrue(ci.plan_install(facts, google, NOW).certbot_force)
        # Même méthode, même greffon : rien de forcé.
        self.assertFalse(ci.plan_install(facts, dns, NOW).certbot_force)
        # Lignée mise de côté sous une autre méthode : forcé aussi.
        held = production_installed(
            dns,
            state=None,
            certbot=certbot_facts(
                lineage=ci.certificate_names(dns),
                held=True,
                authenticator="webroot",
            ),
        )
        self.assertTrue(ci.plan_install(held, dns, NOW).certbot_force)

    def test_new_dns_credentials_are_something_to_do(self):
        old = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        facts = production_installed(old)
        old = dataclasses.replace(old, nginx="existing")
        self.assertTrue(ci.plan_install(facts, old, NOW).nothing_to_do)
        new = dataclasses.replace(
            old, dns_credentials=CREDENTIALS.replace("0123", "9876")
        )
        plan = ci.plan_install(facts, new, NOW)
        self.assertFalse(plan.nothing_to_do)
        # L'essai à blanc éprouve les nouveaux identifiants.
        self.assertFalse(plan.lineage_unchanged)
        self.assertFalse(plan.certbot_force)
        # Le secret n'est consigné que par son empreinte.
        state = json.dumps(plan.new_state)
        self.assertNotIn("Inventejeton", state)
        self.assertEqual(
            plan.new_state["certbot"]["credentials_sha256"],
            hashlib.sha256(new.dns_credentials.encode()).hexdigest(),
        )

    def test_rerun_needs_an_active_nginx(self):
        ans = production()
        facts = production_installed(ans, nginx=nginx_facts(state="inactive"))
        plan = ci.plan_install(
            facts, dataclasses.replace(ans, nginx="existing"), NOW
        )
        self.assertFalse(plan.nothing_to_do)

    def test_development_ntfy_drops_the_production_keys(self):
        # De la production au développement, behind-proxy et web-root
        # partent.
        prod = ci.ntfy_config(production())
        dev = ci.ntfy_config(answers(), existing=prod)
        keys = nm.read_yml_keys(dev)
        self.assertNotIn("behind-proxy", keys)
        self.assertNotIn("web-root", keys)

    def test_fits_in_one_argument(self):
        ans = production(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        script = ci.install_script(
            ci.plan_install(base_facts(), ans, NOW), STAMP
        )
        self.assertLess(len(shlex.quote(script).encode()), 128 * 1024 - 4096)


class FakePermission:
    """`turn_client.permission` qui note ses appels et rend `result`."""

    def __init__(self, result=None):
        self.result = result or tc.Allocation(False, None, "403 Forbidden")
        self.calls = []

    def __call__(
        self,
        host,
        port,
        transport,
        username,
        key,
        peer,
        timeout=5.0,
        cafile=None,
        server_name=None,
    ):
        self.calls.append(
            dict(
                host=host,
                port=port,
                transport=transport,
                username=username,
                key=key,
                peer=peer,
            )
        )
        return self.result


def production_state(ans=None, output="", facts=None):
    """L'état qu'écrit une installation de production réussie de `ans`
    (Let's Encrypt par nginx par défaut), marqueurs des installateurs
    compris."""
    plan = ci.plan_install(facts or base_facts(), ans or production(), NOW)
    return ci.installed_state(plan, STAMP, output)


def production_remote(
    state,
    certs=None,
    hook="exec",
    renewal="active",
    timers=(("certbot.timer", "active"),),
):
    """Sortie de `check_remote_script` d'un hôte de production inventé."""
    lines = remote_output(
        state,
        {"coturn": "active", "ntfy": "active"},
        certs=certs,
    ).splitlines()[:-1]
    if hook:
        lines.append(f"@@HOOK {hook}")
    if renewal:
        lines.append(f"@@RENEWAL {renewal}")
    lines += [f"@@TIMER {unit} {value}" for unit, value in timers]
    lines.append("@@END")
    return "\n".join(lines) + "\n"


class TestProductionCheck(unittest.TestCase):
    """`check_local` sur un état de production : TLS de Let's Encrypt,
    émetteur, renouvellement, ntfy par nginx sur 443, plages privées."""

    def setUp(self):
        global STAGING_CERT, PROD_CERT, PROD_KEY
        if "STAGING_CERT" not in globals():
            STAGING_CERT, _key = Certificates.make(
                "staging",
                "(STAGING) Faux Navet R99",
                "DNS:ntfy.exemple.test,DNS:turn.exemple.test",
            )
            PROD_CERT, PROD_KEY = Certificates.make(
                "prod",
                "exemple.test",
                "DNS:ntfy.exemple.test,DNS:turn.exemple.test",
            )

    def check(
        self,
        state,
        permission=None,
        allocate=None,
        get=None,
        cafile=None,
        **remote,
    ):
        remote.setdefault("certs", {"coturn": TURN_CERT, "lineage": TURN_CERT})
        facts = ci.parse_check_remote(production_remote(state, **remote))
        self.allocate = allocate or FakeAllocate()
        self.get = get or FakeGet()
        self.permission = permission or FakePermission()
        return ci.check_local(
            facts,
            HOST,
            cafile,
            allocate=self.allocate,
            https_get=self.get,
            now=NOW,
            permission=self.permission,
        )

    def test_lets_encrypt_lines_and_their_targets(self):
        lines = self.check(production_state())
        self.assertEqual(
            [line.name for line in lines],
            [
                "turn-udp",
                "turn-tcp",
                "turn-tls",
                "private-denied",
                "ntfy-health",
                "cert-expiry",
                "cert-issuer",
                "renewal",
                "firewall",
                "service-coturn",
                "service-ntfy",
            ],
        )
        named = by_name(lines)
        for name in (
            "turn-tls",
            "private-denied",
            "ntfy-health",
            "cert-expiry",
            "cert-issuer",
            "renewal",
        ):
            self.assertIs(named[name].ok, True, named[name])
        tls = self.allocate.calls[2]
        self.assertEqual(
            (tls["transport"], tls["port"], tls["cafile"], tls["server_name"]),
            ("tls", 5349, None, "turn.exemple.test"),
        )
        self.assertEqual(
            self.get.calls,
            [
                dict(
                    address=HOST,
                    port=443,
                    path="/v1/health",
                    tls=True,
                    server_name="ntfy.exemple.test",
                    cafile=None,
                )
            ],
        )
        self.assertEqual(
            self.permission.calls,
            [
                dict(
                    host=HOST,
                    port=3478,
                    transport="udp",
                    username="erplibre-check",
                    key=bytes.fromhex(CHECK_KEY),
                    peer="10.0.0.1",
                )
            ],
        )
        self.assertEqual(
            named["private-denied"].detail, "call_infra_check_private_denied"
        )
        self.assertEqual(
            named["cert-issuer"].values, {"issuer": "turn.exemple.test"}
        )

    def test_a_granted_private_peer_is_an_open_relay_to_the_network(self):
        granted = FakePermission(tc.Allocation(True, RELAYED, None))
        line = by_name(self.check(production_state(), permission=granted))[
            "private-denied"
        ]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_private_open")
        self.assertEqual(line.values, {"peer": "10.0.0.1"})

    def test_a_failed_allocation_leaves_the_private_ranges_unknown(self):
        failed = FakePermission(tc.Allocation(False, None, "timeout"))
        line = by_name(self.check(production_state(), permission=failed))[
            "private-denied"
        ]
        self.assertIsNone(line.ok)
        self.assertEqual(line.detail, "call_infra_check_private_unknown")
        self.assertEqual(line.values, {"error": "timeout"})

    def test_no_check_key_checks_no_private_range(self):
        state = production_state()
        facts = ci.parse_check_remote(
            production_remote(state).replace(
                "@@CHECK_KEY " + CHECK_KEY + "\n", ""
            )
        )
        permission = FakePermission()
        line = by_name(
            ci.check_local(
                facts,
                HOST,
                None,
                allocate=FakeAllocate(),
                https_get=FakeGet(),
                now=NOW,
                permission=permission,
            )
        )["private-denied"]
        self.assertIsNone(line.ok)
        self.assertEqual(line.detail, "call_infra_check_no_key")
        self.assertEqual(permission.calls, [])

    def test_development_checks_no_private_range(self):
        names = [
            line.name
            for line in ci.check_local(
                ci.parse_check_remote(remote_output(installed_state())),
                HOST,
                None,
                allocate=FakeAllocate(),
                https_get=FakeGet(),
                now=NOW,
                permission=FakePermission(),
            )
        ]
        self.assertNotIn("private-denied", names)
        self.assertNotIn("renewal", names)

    def test_staging_issuer_is_a_failure(self):
        line = by_name(
            self.check(
                production_state(),
                certs={"coturn": STAGING_CERT, "lineage": STAGING_CERT},
            )
        )["cert-issuer"]
        self.assertIs(line.ok, False)
        self.assertEqual(line.detail, "call_infra_check_cert_staging")
        self.assertEqual(line.values, {"issuer": "(STAGING) Faux Navet R99"})

    def test_turns_on_443(self):
        ans = coturn_only(turns_443=True)
        self.check(production_state(ans), certs={"coturn": TURN_CERT})
        self.assertEqual(self.allocate.calls[2]["port"], 443)
        self.assertEqual(self.get.calls, [])

    def test_lets_encrypt_tls_failure_is_a_failure(self):
        # Les autorités du système vérifient un certificat de Let's
        # Encrypt : un échec TLS n'y est pas un « non vérifié ».
        error = ssl.SSLCertVerificationError("unable to get local issuer")
        lines = by_name(
            self.check(
                production_state(),
                get=FakeGet(error),
                allocate=FakeAllocate(tls=tc.Allocation(False, None, "tls")),
            )
        )
        self.assertIs(lines["turn-tls"].ok, False)
        self.assertIs(lines["ntfy-health"].ok, False)
        self.assertEqual(
            lines["ntfy-health"].detail, "call_infra_check_http_error"
        )

    def test_renewal_needs_an_executable_hook_an_active_timer_and_no_hold(
        self,
    ):
        state = production_state()
        cases = (
            (dict(hook=None), "call_infra_check_renewal_no_hook"),
            (dict(hook="present"), "call_infra_check_renewal_no_hook"),
            (dict(renewal="held"), "call_infra_check_renewal_held"),
            (dict(renewal=None), "call_infra_check_renewal_held"),
            (
                dict(timers=(("certbot.timer", "inactive"),)),
                "call_infra_check_renewal_timer",
            ),
            (dict(timers=()), "call_infra_check_renewal_timer"),
        )
        for remote, detail in cases:
            with self.subTest(remote=remote):
                line = by_name(self.check(state, **remote))["renewal"]
                self.assertIs(line.ok, False)
                self.assertEqual(line.detail, detail)

    def test_the_recorded_timer_is_the_one_read(self):
        state = production_state(
            output="@@CERTBOT_TIMER certbot-renew.timer added\n"
        )
        timers = (
            ("certbot.timer", "active"),
            ("certbot-renew.timer", "inactive"),
        )
        line = by_name(self.check(state, timers=timers))["renewal"]
        self.assertIs(line.ok, False)
        self.assertEqual(
            line.values, {"timer": "certbot-renew.timer", "state": "inactive"}
        )
        timers = (("certbot-renew.timer", "active"),)
        line = by_name(self.check(state, timers=timers))["renewal"]
        self.assertIs(line.ok, True)
        self.assertEqual(line.values, {"timer": "certbot-renew.timer"})

    def test_supplied_certificate_behind_nginx(self):
        ans = production(tls="supplied", cert_pem=PROD_CERT, key_pem=PROD_KEY)
        state = production_state(ans)
        lines = self.check(
            state,
            certs={"coturn": PROD_CERT, "site": PROD_CERT},
            cafile="/ca/exemple.pem",
            hook=None,
            renewal=None,
            timers=(),
        )
        names = [line.name for line in lines]
        self.assertNotIn("renewal", names)
        self.assertIn("private-denied", names)
        named = by_name(lines)
        self.assertIs(named["cert-expiry"].ok, True)
        self.assertIs(named["cert-issuer"].ok, True)
        self.assertEqual(self.get.calls[0]["port"], 443)
        self.assertEqual(self.get.calls[0]["cafile"], "/ca/exemple.pem")
        self.assertEqual(self.allocate.calls[2]["cafile"], "/ca/exemple.pem")
        # Le certificat de nginx manque : l'échéance le dit.
        line = by_name(
            self.check(
                state,
                certs={"coturn": PROD_CERT},
                hook=None,
                renewal=None,
                timers=(),
            )
        )["cert-expiry"]
        self.assertIs(line.ok, False)
        self.assertEqual(line.values, {"service": "site"})

    def test_lets_encrypt_certificate_missing(self):
        line = by_name(
            self.check(production_state(), certs={"coturn": TURN_CERT})
        )["cert-expiry"]
        self.assertIs(line.ok, False)
        self.assertEqual(line.values, {"service": "lineage"})

    def test_remote_script_reads_hook_renewal_timers_and_certificates(self):
        state = production_state()
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            stubs = os.path.join(tmp, "stubs")
            write(root + ci.STATE_PATH, json.dumps(state), 0o600)
            write(root + ci.HOOK_PATH, "#!/bin/sh\n", 0o755)
            write(root + ci.RENEWAL_FILE, "version = 4.0.0\n", 0o644)
            write(
                root + "/etc/letsencrypt/archive/erplibre-call/cert1.pem",
                TURN_CERT,
                0o644,
            )
            os.makedirs(root + ci.LINEAGE_DIR)
            os.symlink(
                "../../archive/erplibre-call/cert1.pem",
                root + ci.LINEAGE_DIR + "/cert.pem",
            )
            write(root + ci.SITE_CERT, OTHER_CERT, 0o644)
            write(
                os.path.join(stubs, "systemctl"),
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                "  'cat certbot.timer'|'cat erplibre-call-certbot.timer')"
                " exit 0 ;;\n"
                "  'is-active certbot.timer') echo active ;;\n"
                "  'is-active erplibre-call-certbot.timer') echo inactive;"
                " exit 3 ;;\n"
                "  *) exit 3 ;;\n"
                "esac\n",
            )
            for name in ("ufw", "nft"):
                write(os.path.join(stubs, name), "#!/bin/sh\nexit 1\n")
            before = snapshot(root)
            done = subprocess.run(
                ["sh", "-c", ci.check_remote_script(root=root)],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=stubs + ":" + os.environ["PATH"]),
                timeout=30,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(snapshot(root), before)
            write(root + ci.HOOK_PATH, "#!/bin/sh\n", 0o644)
            os.rename(root + ci.RENEWAL_FILE, root + ci.RENEWAL_HOLD)
            second = subprocess.run(
                ["sh", "-c", ci.check_remote_script(root=root)],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=stubs + ":" + os.environ["PATH"]),
                timeout=30,
            )
        facts = ci.parse_check_remote(done.stdout)
        self.assertEqual(facts["hook"], "exec")
        self.assertEqual(facts["renewal"], "active")
        self.assertEqual(
            facts["timers"],
            {
                "certbot.timer": "active",
                "erplibre-call-certbot.timer": "inactive",
            },
        )
        self.assertEqual(
            facts["certs"], {"lineage": TURN_CERT, "site": OTHER_CERT}
        )
        facts = ci.parse_check_remote(second.stdout)
        self.assertEqual(facts["hook"], "present")
        self.assertEqual(facts["renewal"], "held")

    def test_parse_ignores_unknown_hook_renewal_and_timer_values(self):
        facts = ci.parse_check_remote(
            "@@HOOK ouvert\n@@RENEWAL peut-etre\n"
            "@@TIMER x;y.timer active\n@@TIMER certbot.timer\n"
            "@@CERT inconnu " + b64(TURN_CERT) + "\n@@END\n"
        )
        self.assertIsNone(facts["hook"])
        self.assertIsNone(facts["renewal"])
        self.assertEqual(facts["timers"], {})
        self.assertEqual(facts["certs"], {})


SITE_DEBIAN = "/etc/nginx/sites-available/erplibre-call-ntfy.conf"
LINK_DEBIAN = "/etc/nginx/sites-enabled/erplibre-call-ntfy.conf"
SITE_ARCH = "/etc/nginx/erplibre-call.d/erplibre-call-ntfy.conf"
NGINX_BACKUP = "/etc/nginx/nginx.conf.bak-20261030101500"
ARCH_NGINX_CONF = (
    "worker_processes 1;\n"
    "http {\n"
    "    include mime.types;\n"
    "    server {\n"
    "        listen 80;\n"
    "        server_name localhost;\n"
    "    }\n"
    "}\n"
)
INCLUDE_LINE = "    include /etc/nginx/erplibre-call.d/*.conf;\n"
LE_OUTPUT = (
    "@@NGINX_INSTALLED 1\n"
    "@@NGINX_LAYOUT debian\n"
    "@@CERTBOT_INSTALLED 1\n"
    "@@CERTBOT_TIMER certbot.timer present\n"
)
DEBIAN_PKGS = "nginx nginx-common certbot"


class TestProductionUninstall(UninstallSandbox):
    """`uninstall_script` d'un état de production : site nginx, ligne
    include, crochet, minuteur ajouté, identifiants DNS, lignée gardée
    (mise de côté) ou retirée par certbot, paquets purgés seulement quand
    l'outil les a posés et que rien d'autre n'en dépend."""

    def place_production(self, state, layout="debian"):
        """L'hôte tel qu'une installation de production l'a laissé."""
        self.place_state(state)
        for svc, record in state["services"].items():
            write(self.path(record["config"]), ci.MARKER + "\n", 0o644)
        nginx = state.get("nginx")
        if nginx:
            write(self.path(nginx["site"]), ci.MARKER + "\nserver {}\n", 0o644)
            if nginx["link"]:
                os.makedirs(os.path.dirname(self.path(nginx["link"])))
                os.symlink(nginx["site"], self.path(nginx["link"]))
            write(self.path(ci.NGINX_APPLIED), "empreinte\n", 0o600)
        if state.get("certbot"):
            write(self.path(ci.ACME_ROOT + "/.well-known/x"), "defi", 0o644)
            write(self.path(ci.HOOK_PATH), ci.deploy_hook_text(), 0o755)
            write(self.path(RENEWAL), "version = 4.0.0\n", 0o644)
            for name in ("cert.pem", "privkey.pem", "fullchain.pem"):
                write(self.path(LINEAGE + "/" + name), name, 0o600)
        return state

    def read(self, host_path):
        with open(self.path(host_path)) as handle:
            return handle.read()

    def exists(self, host_path):
        return os.path.lexists(self.path(host_path))

    def test_kept_certificate_is_held_and_tool_nginx_purged(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        for expected in (
            f"REMOVED hook {ci.HOOK_PATH}",
            f"HELD {ci.RENEWAL_FILE}",
            f"KEPT {ci.LINEAGE_DIR}",
            f"REMOVED nginx-site {SITE_DEBIAN}",
            f"REMOVED nginx-link {LINK_DEBIAN}",
            f"REMOVED acme {ci.ACME_ROOT}",
            "REMOVED package nginx",
            "REMOVED package nginx-common",
            "KEPT package certbot",
            "REMOVED state",
        ):
            self.assertIn(expected, markers)
        self.assertEqual(markers[-1], "DONE yes")
        self.assertFalse(self.exists(ci.HOOK_PATH))
        self.assertFalse(self.exists(ci.RENEWAL_FILE))
        self.assertEqual(self.read(ci.RENEWAL_HOLD), "version = 4.0.0\n")
        self.assertTrue(self.exists(LINEAGE + "/cert.pem"))
        for path in (SITE_DEBIAN, LINK_DEBIAN, ci.ACME_ROOT, ci.CALL_DIR):
            self.assertFalse(self.exists(path), path)
        calls = self.calls()
        self.assertFalse([c for c in calls if c.startswith("certbot")])
        self.assertIn("systemctl disable --now nginx", calls)
        self.assertIn("apt-get purge -y nginx", calls)
        self.assertNotIn("apt-get purge -y certbot", calls)
        # nginx part avec son paquet : rien à tester ni à recharger.
        self.assertNotIn("nginx -t", calls)
        self.assertNotIn("systemctl reload nginx", calls)

    def test_remove_data_deletes_the_lineage_through_certbot(self):
        for held in (False, True):
            with self.subTest(held=held):
                self.setUp()
                state = self.place_production(
                    production_state(output=LE_OUTPUT)
                )
                if held:
                    os.rename(self.path(RENEWAL), self.path(ci.RENEWAL_HOLD))
                done = self.uninstall(
                    state, remove_data=True, UNITS="nginx", PKGS=DEBIAN_PKGS
                )
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                markers = self.markers(done)
                self.assertIn("REMOVED certificate erplibre-call", markers)
                self.assertIn("REMOVED package certbot", markers)
                self.assertEqual(markers[-1], "DONE yes")
                deletes = [
                    c for c in self.calls() if c.startswith("certbot delete")
                ]
                self.assertEqual(len(deletes), 1)
                self.assertIn("--cert-name erplibre-call", deletes[0])
                self.assertIn("--non-interactive", deletes[0])
                for path in (LINEAGE, ci.RENEWAL_FILE, ci.RENEWAL_HOLD):
                    self.assertFalse(self.exists(path), path)
                self.assertIn("apt-get purge -y certbot", self.calls())

    def test_failed_certbot_delete_holds_the_renewal_again(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        os.rename(self.path(RENEWAL), self.path(ci.RENEWAL_HOLD))
        done = self.uninstall(
            state,
            remove_data=True,
            UNITS="nginx",
            PKGS=DEBIAN_PKGS,
            CERTBOT_RC="1",
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("FAILED certbot-delete", self.markers(done))
        self.assertTrue(self.exists(ci.RENEWAL_HOLD))
        self.assertFalse(self.exists(ci.RENEWAL_FILE))
        self.assertTrue(self.exists(ci.STATE_PATH))
        self.assertNotIn("apt-get purge -y certbot", self.calls())

    def test_nginx_not_installed_by_the_tool_is_tested_reloaded_not_purged(
        self,
    ):
        state = production_state(output=LE_OUTPUT)
        state["nginx"]["installed_by_tool"] = False
        state["certbot"]["installed_by_tool"] = False
        self.place_production(state)
        done = self.uninstall(
            state, remove_data=True, UNITS="nginx", PKGS=DEBIAN_PKGS
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertLess(
            calls.index("nginx -t"), calls.index("systemctl reload nginx")
        )
        self.assertFalse([c for c in calls if c.startswith("apt-get")])
        self.assertNotIn("systemctl disable --now nginx", calls)
        markers = self.markers(done)
        self.assertNotIn("KEPT package nginx", markers)
        self.assertNotIn("KEPT package certbot", markers)
        self.assertFalse(self.exists(SITE_DEBIAN))

    def test_an_existing_stopped_nginx_is_stopped_again(self):
        facts = base_facts(
            nginx=nginx_facts(state="inactive", enabled="disabled")
        )
        state = production_state(production(nginx="existing"), facts=facts)
        state["certbot"]["installed_by_tool"] = False
        self.place_production(state)
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertIn("systemctl stop nginx", calls)
        self.assertIn("systemctl disable nginx", calls)
        self.assertLess(calls.index("nginx -t"), calls.index("systemctl stop nginx"))
        self.assertFalse([c for c in calls if c.startswith("apt-get")])
        # Trouvé actif et activé : il le reste.
        self.setUp()
        facts = base_facts(nginx=nginx_facts(enabled="enabled"))
        state = production_state(production(nginx="existing"), facts=facts)
        self.place_production(state)
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        calls = self.calls()
        self.assertNotIn("systemctl stop nginx", calls)
        self.assertNotIn("systemctl disable nginx", calls)

    def test_another_enabled_site_keeps_the_tool_nginx(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        write(self.path("/etc/nginx/sites-enabled/autre"), "server {}\n")
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        self.assertIn(
            "NGINX_OTHER_SITE /etc/nginx/sites-enabled/autre", markers
        )
        self.assertIn("KEPT package nginx", markers)
        calls = self.calls()
        self.assertNotIn("apt-get purge -y nginx", calls)
        self.assertIn("systemctl reload nginx", calls)
        self.assertTrue(self.exists("/etc/nginx/sites-enabled/autre"))

    def test_the_package_default_site_alone_does_not_keep_nginx(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        os.symlink(
            "/etc/nginx/sites-available/default",
            self.path("/etc/nginx/sites-enabled/default"),
        )
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("apt-get purge -y nginx", self.calls())

    def test_a_modified_package_configuration_keeps_nginx(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        done = self.uninstall(
            state,
            UNITS="nginx",
            PKGS=DEBIAN_PKGS,
            DPKG_V="??5?????? c /etc/nginx/nginx.conf\n",
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        self.assertIn("NGINX_MODIFIED /etc/nginx/nginx.conf", markers)
        self.assertIn("KEPT package nginx", markers)
        self.assertNotIn("apt-get purge -y nginx", self.calls())

    def test_failing_nginx_test_puts_our_files_back_and_reloads_nothing(self):
        state = production_state(output=LE_OUTPUT)
        state["nginx"]["installed_by_tool"] = False
        self.place_production(state)
        done = self.uninstall(
            state, remove_data=True, UNITS="nginx", NGINX_T_RC="1"
        )
        self.assertNotEqual(done.returncode, 0)
        markers = self.markers(done)
        self.assertIn(
            "NGINX_TEST_FAILED nginx: [emerg] directive inventee in"
            " /etc/nginx/nginx.conf:1",
            markers,
        )
        self.assertIn("FAILED nginx-test", markers)
        self.assertEqual(markers[-1], "DONE no")
        self.assertNotIn("systemctl reload nginx", self.calls())
        self.assertEqual(self.read(SITE_DEBIAN), ci.MARKER + "\nserver {}\n")
        self.assertEqual(os.readlink(self.path(LINK_DEBIAN)), SITE_DEBIAN)
        # Le site remis lit encore la lignée et le dossier du défi.
        self.assertTrue(self.exists(LINEAGE + "/cert.pem"))
        self.assertTrue(self.exists(ci.ACME_ROOT))
        self.assertFalse([c for c in self.calls() if "certbot" in c])
        self.assertTrue(self.exists(ci.STATE_PATH))
        # La relance, nginx réparé, va au bout.
        done = self.uninstall(state, remove_data=True, UNITS="nginx")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(self.exists(SITE_DEBIAN))
        self.assertFalse(self.exists(LINEAGE))
        self.assertFalse(self.exists(ci.STATE_PATH))

    def arch_state(self, installed=False):
        write(self.path("/etc/os-release"), "ID=arch\n", 0o644)
        facts = base_facts(family="arch", os_id="arch")
        output = (
            "@@NGINX_LAYOUT arch-include\n"
            f"@@NGINX_BACKUP {NGINX_BACKUP}\n"
            "@@CERTBOT_TIMER certbot-renew.timer added\n"
        )
        state = production_state(output=output, facts=facts)
        self.assertEqual(state["nginx"]["backup"], NGINX_BACKUP)
        state["nginx"]["installed_by_tool"] = installed
        return self.place_production(state)

    def test_arch_include_line_goes_and_the_backup_comes_back(self):
        state = self.arch_state()
        conf = ARCH_NGINX_CONF[:-2] + INCLUDE_LINE + "}\n"
        write(self.path(ci.NGINX_CONF), conf, 0o644)
        write(self.path(NGINX_BACKUP), ARCH_NGINX_CONF, 0o644)
        done = self.uninstall(state, UNITS="nginx certbot-renew.timer")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        # Le motif de la ligne include est une ERE sans échappement que grep
        # signalerait.
        self.assertEqual(done.stderr, "")
        self.assertEqual(self.read(ci.NGINX_CONF), ARCH_NGINX_CONF)
        self.assertFalse(self.exists(NGINX_BACKUP))
        self.assertFalse(self.exists(ci.NGINX_INCLUDE_DIR))
        markers = self.markers(done)
        self.assertIn(f"REMOVED nginx-include {ci.NGINX_CONF}", markers)
        self.assertIn(f"RESTORED {ci.NGINX_CONF} {NGINX_BACKUP}", markers)
        self.assertIn(f"REMOVED nginx-site {SITE_ARCH}", markers)
        calls = self.calls()
        self.assertIn("nginx -t", calls)
        self.assertIn("systemctl disable --now certbot-renew.timer", calls)

    def test_arch_include_line_goes_and_an_edited_conf_keeps_its_edits(self):
        state = self.arch_state()
        edited = "# ajout de l'admin\n" + ARCH_NGINX_CONF
        write(
            self.path(ci.NGINX_CONF),
            edited[:-2] + INCLUDE_LINE + "}\n",
            0o640,
        )
        write(self.path(NGINX_BACKUP), ARCH_NGINX_CONF, 0o644)
        done = self.uninstall(state, UNITS="nginx")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.read(ci.NGINX_CONF), edited)
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path(ci.NGINX_CONF)).st_mode), 0o640
        )
        self.assertTrue(self.exists(NGINX_BACKUP))
        self.assertIn(f"KEPT {NGINX_BACKUP}", self.markers(done))

    def test_arch_tool_nginx_purged_with_pacman(self):
        state = self.arch_state(installed=True)
        write(
            self.path(ci.NGINX_CONF),
            ARCH_NGINX_CONF[:-2] + INCLUDE_LINE + "}\n",
            0o644,
        )
        write(self.path(NGINX_BACKUP), ARCH_NGINX_CONF, 0o644)
        done = self.uninstall(state, UNITS="nginx", PKGS="nginx")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("pacman -Rn --noconfirm nginx", self.calls())
        self.assertEqual(self.read(ci.NGINX_CONF), ARCH_NGINX_CONF)

    def test_dropin_of_coturn_on_443_goes_with_a_daemon_reload(self):
        state = production_state(coturn_only(turns_443=True))
        dropin = state["services"]["coturn"]["dropin"]
        self.assertEqual(
            dropin, "/etc/systemd/system/coturn.service.d/erplibre-call.conf"
        )
        self.place_production(state)
        write(self.path(dropin), ci.MARKER + "\n[Service]\n", 0o644)
        done = self.uninstall(state, UNITS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(f"REMOVED dropin {dropin}", self.markers(done))
        self.assertFalse(self.exists(os.path.dirname(dropin)))
        self.assertIn("systemctl daemon-reload", self.calls())

    def test_a_foreign_dropin_stays(self):
        state = production_state(coturn_only(turns_443=True))
        dropin = state["services"]["coturn"]["dropin"]
        self.place_production(state)
        write(self.path(dropin), "[Service]\nNice=5\n", 0o644)
        done = self.uninstall(state, UNITS="coturn")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(self.exists(dropin))

    def test_timer_added_by_the_tool_is_stopped_a_present_one_left(self):
        cases = (
            ("certbot-renew.timer added", True),
            ("certbot.timer present", False),
        )
        for marker, stopped in cases:
            with self.subTest(marker=marker):
                self.setUp()
                state = self.place_production(
                    production_state(
                        coturn_only(), output=f"@@CERTBOT_TIMER {marker}\n"
                    )
                )
                unit = marker.split()[0]
                done = self.uninstall(state, UNITS=f"coturn {unit}")
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertEqual(
                    f"systemctl disable --now {unit}" in self.calls(), stopped
                )

    def test_own_timer_units_are_removed(self):
        state = self.place_production(
            production_state(
                coturn_only(),
                output="@@CERTBOT_TIMER erplibre-call-certbot.timer added\n",
            )
        )
        units = "/etc/systemd/system/erplibre-call-certbot"
        for suffix in (".service", ".timer"):
            write(self.path(units + suffix), ci.MARKER + "\n", 0o644)
        done = self.uninstall(
            state, UNITS="coturn erplibre-call-certbot.timer"
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for suffix in (".service", ".timer"):
            self.assertFalse(self.exists(units + suffix))
        calls = self.calls()
        self.assertIn(
            "systemctl disable --now erplibre-call-certbot.timer", calls
        )
        self.assertIn("systemctl daemon-reload", calls)

    def test_another_lineage_keeps_the_timer_certbot_and_plugins(self):
        ans = coturn_only(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        state = production_state(
            ans,
            output="@@CERTBOT_INSTALLED 1\n"
            "@@CERTBOT_TIMER certbot-renew.timer added\n",
        )
        self.place_production(state)
        write(self.path("/etc/letsencrypt/renewal/autre.conf"), "x\n")
        done = self.uninstall(
            state,
            remove_data=True,
            UNITS="coturn certbot-renew.timer",
            PKGS="certbot python3-certbot-dns-cloudflare",
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        self.assertIn("KEPT timer certbot-renew.timer", markers)
        self.assertIn("KEPT package certbot", markers)
        self.assertIn("KEPT package python3-certbot-dns-cloudflare", markers)
        calls = self.calls()
        self.assertFalse([c for c in calls if c.startswith("apt-get")])
        self.assertNotIn("systemctl disable --now certbot-renew.timer", calls)
        # La lignée de l'outil part quand même.
        self.assertIn("REMOVED certificate erplibre-call", markers)

    def test_dns_credentials_go_and_the_tool_plugin_is_purged(self):
        ans = coturn_only(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        state = production_state(ans)
        self.assertEqual(
            state["certbot"]["plugins_installed"],
            ["python3-certbot-dns-cloudflare"],
        )
        self.place_production(state)
        credentials = ci.DNS_DIR + "/cloudflare.ini"
        write(self.path(credentials), CREDENTIALS, 0o600)
        # Ceux d'un greffon d'un passage précédent partent aussi.
        write(self.path(ci.DNS_DIR + "/google.ini"), "{}", 0o600)
        done = self.uninstall(
            state,
            UNITS="coturn",
            PKGS="python3-certbot-dns-cloudflare",
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        markers = self.markers(done)
        self.assertIn(f"REMOVED dns {credentials}", markers)
        self.assertIn(f"REMOVED dns {ci.DNS_DIR}/google.ini", markers)
        self.assertIn(
            "REMOVED package python3-certbot-dns-cloudflare", markers
        )
        self.assertNotIn(CREDENTIALS.strip(), done.stdout + done.stderr)
        self.assertFalse(self.exists(ci.DNS_DIR))

    def test_credentials_go_even_when_another_step_fails(self):
        ans = coturn_only(
            acme="dns", dns_plugin="cloudflare", dns_credentials=CREDENTIALS
        )
        state = self.place_production(production_state(ans))
        credentials = ci.DNS_DIR + "/cloudflare.ini"
        write(self.path(credentials), CREDENTIALS, 0o600)
        done = self.uninstall(
            state, remove_data=True, UNITS="coturn", CERTBOT_RC="1"
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(self.exists(credentials))
        self.assertTrue(self.exists(ci.STATE_PATH))

    def test_supplied_certificate_copies_for_nginx(self):
        cert, key = Certificates.make(
            "prod-uninstall",
            "exemple.test",
            "DNS:ntfy.exemple.test,DNS:turn.exemple.test",
        )
        ans = production(tls="supplied", cert_pem=cert, key_pem=key)
        for remove_data in (False, True):
            with self.subTest(remove_data=remove_data):
                self.setUp()
                state = self.place_production(production_state(ans))
                self.assertNotIn("certbot", state)
                for path in (ci.SITE_CERT, ci.SITE_KEY):
                    write(self.path(path), "pem", 0o600)
                done = self.uninstall(
                    state,
                    remove_data=remove_data,
                    UNITS="nginx",
                    PKGS="nginx",
                )
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                markers = self.markers(done)
                word = "REMOVED tls" if remove_data else "KEPT"
                self.assertIn(f"{word} {ci.SITE_CERT}", markers)
                self.assertEqual(self.exists(ci.SITE_KEY), not remove_data)
                self.assertFalse([c for c in self.calls() if "certbot" in c])

    def test_uninstall_twice_says_nothing_the_second_time(self):
        state = self.place_production(production_state(output=LE_OUTPUT))
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(self.exists(ci.STATE_PATH))
        again = self.uninstall(None)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.markers(again), ["NOTHING"])

    def test_pending_records_of_nginx_and_certbot(self):
        for name in ("nginx", "certbot"):
            write(self.path(f"{ci.PENDING_DIR}/{name}.json"), "{}", 0o600)
        done = self.uninstall(None)
        self.assertEqual(
            self.markers(done), ["PENDING nginx", "PENDING certbot", "NOTHING"]
        )
        state = self.place_production(production_state(output=LE_OUTPUT))
        done = self.uninstall(state, UNITS="nginx", PKGS=DEBIAN_PKGS)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertFalse(self.exists(ci.PENDING_DIR))

    def test_production_values_read_from_the_state_are_checked(self):
        good = production_state(
            production(
                acme="dns",
                dns_plugin="cloudflare",
                dns_credentials=CREDENTIALS,
            ),
            output=LE_OUTPUT,
        )
        ci.uninstall_script(good, True, STAMP)
        cases = {
            "site": ("nginx", "site", "/etc/nginx/sites-available/autre"),
            "link": ("nginx", "link", "/etc/nginx/sites-enabled/autre"),
            "layout": ("nginx", "layout", "autre"),
            "include": ("nginx", "include", "/etc/nginx/autre.conf"),
            "backup": ("nginx", "backup", "/etc/nginx/nginx.conf.bak-x;y"),
            "backup-elsewhere": ("nginx", "backup", "/tmp/nginx.conf.bak-1"),
            "acme": ("nginx", "acme_root", "/var/lib"),
            "site-tls": ("nginx", "tls_files", ["/root/.ssh/id_ed25519"]),
            "nginx-record": ("nginx", None, "pas un dict"),
            "plugin": ("certbot", "plugins_installed", ["openssh-server"]),
            "timer": (
                "certbot",
                "timer",
                {"unit": "ssh.timer", "added": True},
            ),
            "credentials": ("certbot", "dns_credentials", "/root/x.ini"),
            "renewal": ("certbot", "renewal", "/etc/letsencrypt/renewal/x"),
            "cert-name": ("certbot", "cert_name", "autre"),
            "hook": ("hook", "path", "/usr/local/bin/x"),
        }
        for label, (record, key, value) in cases.items():
            with self.subTest(label):
                state = json.loads(json.dumps(good))
                if key is None:
                    state[record] = value
                else:
                    state[record][key] = value
                with self.assertRaises(ci.Refusal) as caught:
                    ci.uninstall_script(state, False, STAMP)
                self.assertEqual(
                    caught.exception.key, "call_infra_state_invalid"
                )
        state = json.loads(json.dumps(good))
        state["services"]["coturn"]["dropin"] = "/etc/systemd/system/x.conf"
        with self.assertRaises(ci.Refusal):
            ci.uninstall_script(state, False, STAMP)


class TestStdlibOnly(unittest.TestCase):
    ALLOWED_SIBLINGS = {"script.todo.ntfy_mobile", "script.todo.turn_client"}

    def test_module_imports_only_stdlib(self):
        with open(os.path.join(REPO, "script", "todo", "call_infra.py")) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(
                        alias.name.split(".")[0], sys.stdlib_module_names
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "script.todo":
                    for alias in node.names:
                        self.assertIn(
                            "script.todo." + alias.name, self.ALLOWED_SIBLINGS
                        )
                else:
                    self.assertIn(
                        node.module.split(".")[0], sys.stdlib_module_names
                    )


if __name__ == "__main__":
    unittest.main()
