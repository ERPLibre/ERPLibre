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
import datetime
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest

from script.todo import call_infra as ci
from script.todo import ntfy_mobile as nm

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COTURN_INSTALLER = os.path.join(REPO, "script", "install", "install_coturn.sh")
NTFY_INSTALLER = os.path.join(REPO, "script", "install", "install_ntfy.sh")

STAMP = "20261030-101500"
PASSWORD = "Kq4-controle-invente-77"
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
    def make(cls, name, subject, san):
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
            "30",
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

    def run_probe(self, ufw="Status: active", state=None):
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
                    "  *) exit 3 ;;\n"
                    "esac\n"
                )
                % COTURN_UNIT,
            )
            write(os.path.join(stubs, "ufw"), "#!/bin/sh\necho '%s'\n" % ufw)
            for name in ("nft", "iptables"):
                write(os.path.join(stubs, name), "#!/bin/sh\nexit 1\n")
            env = dict(os.environ, PATH=stubs + ":" + os.environ["PATH"])
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
        self.assertIsNone(facts.ntfy)
        self.assertEqual(facts.firewall, "ufw")
        self.assertEqual(facts.state, state)

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
        self.assertNotIn(PASSWORD, text)

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
        return (
            "TURN_REALM=%s\nTURN_PORT=%d\nTURN_TLS_PORT=%d\nTURN_MIN_PORT=%d\n"
            "TURN_MAX_PORT=%d\nTURN_CERT_FILE=%s\nTURN_KEY_FILE=%s\n"
            "TURN_EXTERNAL_IP=%s\n"
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
    def test_password_and_key_only_in_base64(self):
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        script = ci.install_script(plan, STAMP, PASSWORD)
        self.assertNotIn(PASSWORD, script)
        self.assertIn(base64.b64encode(PASSWORD.encode()).decode(), script)
        self.assertNotIn("PRIVATE KEY", script)
        for line in TURN_KEY.splitlines()[1:-1]:
            self.assertNotIn(line, script)

    def test_state_written_after_the_last_active_check_and_guarded(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        script = ci.install_script(plan, STAMP, PASSWORD)
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
        # Le script voyage en UN argument de « sh -c » : Linux borne un
        # argument à 128 Kio (MAX_ARG_STRLEN), guillemets de ssh compris.
        plan = ci.plan_install(base_facts(), supplied(), NOW)
        script = ci.install_script(plan, STAMP, PASSWORD)
        self.assertLess(len(shlex.quote(script).encode()), 128 * 1024 - 4096)

    def test_bad_inputs(self):
        plan = ci.plan_install(base_facts(), answers(), NOW)
        with self.assertRaises(ValueError):
            ci.install_script(plan, "../x", PASSWORD)
        with self.assertRaises(ValueError):
            ci.install_script(plan, STAMP, "")
        ntfy_only = ci.plan_install(
            base_facts(), answers(services=frozenset({"ntfy"})), NOW
        )
        self.assertNotIn(
            "TURN_CHECK_PASSWORD", ci.install_script(ntfy_only, STAMP, "")
        )


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
        script = ci.install_script(plan, STAMP, PASSWORD, root=self.root)
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
        self.assertEqual(coturn["TURN_CHECK_PASSWORD"], PASSWORD)
        self.assertEqual(coturn["TURN_EXTERNAL_IP"], "198.51.100.7")
        self.assertEqual(coturn["TURN_MIN_PORT"], "49152")
        self.assertNotIn("TURN_GARDER_CONFIG", coturn)
        self.assertNotIn("TURN_CERT_FILE", coturn)
        ntfy = self.env_of("install_ntfy")
        self.assertEqual(ntfy["NTFY_NON_INTERACTIVE"], "1")
        self.assertEqual(ntfy["NTFY_PORT"], "8080")
        self.assertEqual(
            ntfy["NTFY_BASE_URL"], "http://turn.exemple.test:8080"
        )
        self.assertNotIn(PASSWORD, self.read(os.path.join(self.log, "argv")))
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
