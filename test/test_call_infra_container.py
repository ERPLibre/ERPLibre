#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""`script/todo/call_infra_container.py` : constantes des conteneurs, sonde
des moteurs, fichier compose, commandes du moteur et paquets à ajouter.

La sonde est jouée dans un bac à sable : un dossier temporaire tient lieu
de racine, et le PATH ne contient QUE des bouchons et des liens vers
quelques outils de base (`sh`, `awk`, `sed`...). Aucun vrai `docker`,
`podman`, `runuser` ni `systemctl` n'est joignable : chaque bouchon note
son argv dans un journal, et les assertions lisent ce journal. Toutes les
valeurs sont inventées.
"""

import ast
import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from script.todo import call_infra as ci
from script.todo import call_infra_container as cc
from script.todo import container_runtime as cr

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


COTURN_REF = (
    "docker.io/coturn/coturn:4.18.0@sha256:"
    "bbefd3e1fdfdc0d58770fe01b581fd8b00d9f3a5580d00acb77cf719a6bc78e3"
)
NTFY_REF = (
    "docker.io/binwiederhier/ntfy:v2.36.0@sha256:"
    "fb48c413eb11d50339962b5d62cddce0f800e7f77c626d638a7c20cb7e9c4465"
)

PROBE_PAIRS = [
    ("ENGINE", "docker 26.1.5"),
    ("ENGINE", "podman 5.4.2"),
    ("COMPOSE", "docker docker compose"),
    ("COMPOSE", "podman podman-compose"),
    ("DOCKER_SERVICE", "active enabled"),
    ("PODMAN_RESTART", "disabled"),
    ("UNPRIV_PORT", "1024"),
    ("ACCOUNT", "turnserver 998 998"),
    ("ACCOUNT", "ntfy 997 997"),
    ("ROOTLESS", "0 0 0 1 -"),
    ("CONTAINER", "erplibre-call-coturn docker 0 running " + COTURN_REF),
    ("IMAGE", "docker 0 " + COTURN_REF),
    ("NTFY_HOST", "2.11.0"),
    ("SQLITE", "1"),
    ("COMPOSE_FILE", b64("# erplibre-call: managed\n")),
]


def rootless_block(**changes):
    block = {
        "engine": "podman",
        "rootless": True,
        "account": "erplibre-call",
        "uid": 990,
        "compose": ["podman-compose"],
        "compose_file": cc.COMPOSE_FILE,
        "project": cc.PROJECT,
    }
    block.update(changes)
    return block


def rootful_block(**changes):
    block = {
        "engine": "docker",
        "rootless": False,
        "account": None,
        "uid": None,
        "compose": ["docker", "compose"],
        "compose_file": cc.COMPOSE_FILE,
        "project": cc.PROJECT,
    }
    block.update(changes)
    return block


def container_state(block=None, **services):
    records = {
        "coturn": {
            "container": "erplibre-call-coturn",
            "account": "turnserver",
            "uid": 998,
            "gid": 998,
        },
        "ntfy": {
            "container": "erplibre-call-ntfy",
            "account": "ntfy",
            "uid": 997,
            "gid": 997,
        },
    }
    for svc, changes in services.items():
        records[svc].update(changes)
    return {
        "version": 2,
        "method": "container",
        "container": block if block is not None else rootful_block(),
        "services": records,
    }


class TestConstants(unittest.TestCase):
    def test_pinned_images(self):
        self.assertEqual(cc.IMAGES, {"coturn": COTURN_REF, "ntfy": NTFY_REF})
        self.assertEqual(
            cc.IMAGE_VERSIONS, {"coturn": "4.18.0", "ntfy": "2.36.0"}
        )

    def test_fixed_names(self):
        self.assertEqual(cc.PROJECT, "erplibre-call")
        self.assertEqual(
            cc.CONTAINERS,
            {"coturn": "erplibre-call-coturn", "ntfy": "erplibre-call-ntfy"},
        )
        self.assertEqual(cc.COMPOSE_FILE, "/etc/erplibre-call/compose.yml")
        self.assertEqual(cc.ROOTLESS_ACCOUNT, "erplibre-call")
        self.assertEqual(cc.ROOTLESS_HOME, "/var/lib/erplibre-call-podman")
        self.assertEqual(cc.COTURN_ACCOUNTS, ("turnserver", "erplibre-coturn"))
        self.assertEqual(cc.NTFY_ACCOUNT, "ntfy")
        self.assertTrue(cc.ACCOUNT_RE.match("erplibre-coturn"))
        self.assertFalse(cc.ACCOUNT_RE.match("Root"))
        self.assertFalse(cc.ACCOUNT_RE.match("-x"))
        self.assertFalse(cc.ACCOUNT_RE.match("ntfy\n"))

    def test_engines_are_the_local_runtime_ones(self):
        self.assertEqual(cc.ENGINES, cr.MOTEURS)

    def test_compose_providers_follow_the_local_order_without_podman_compose_wrapper(
        self,
    ):
        # Docker : le greffon v2, puis le binaire ; Podman : podman-compose
        # appelé directement, jamais le relais « podman compose ».
        self.assertEqual(
            cc.COMPOSE_PROVIDERS["docker"],
            tuple(tuple(c) for c in cr.COMPOSE["docker"]),
        )
        self.assertEqual(
            cc.COMPOSE_PROVIDERS["podman"], (("podman-compose",),)
        )

    def test_mount_paths_are_the_packages_paths(self):
        self.assertEqual(cc.COTURN_DATA_DIR, os.path.dirname(ci.COTURN_DB))
        self.assertEqual(cc.COTURN_TLS_DIR, ci.COTURN_TLS_DIR)
        self.assertEqual(cc.NTFY_CONFIG_DIR, os.path.dirname(ci.NTFY_CONFIG))
        self.assertEqual(cc.NTFY_DATA_DIR, os.path.dirname(ci.NTFY_AUTH_FILE))
        self.assertEqual(cc.NTFY_CACHE_DIR, "/var/cache/ntfy")
        self.assertTrue(ci.NTFY_TLS_DIR.startswith(cc.NTFY_CONFIG_DIR + "/"))
        self.assertEqual(cc.MANAGED_LINE, ci.MARKER)


class TestParseEngineLines(unittest.TestCase):
    def test_full_probe(self):
        facts = cc.parse_engine_lines(PROBE_PAIRS)
        self.assertEqual(
            facts.engines, {"docker": "26.1.5", "podman": "5.4.2"}
        )
        self.assertEqual(
            facts.compose,
            {"docker": ("docker", "compose"), "podman": ("podman-compose",)},
        )
        self.assertEqual(facts.docker_service, ("active", "enabled"))
        self.assertEqual(facts.podman_restart, "disabled")
        self.assertEqual(facts.unpriv_port_start, 1024)
        self.assertEqual(
            facts.accounts, {"turnserver": (998, 998), "ntfy": (997, 997)}
        )
        # Sans compte rootless, rien à dire de lui ; newuidmap reste su.
        self.assertIsNone(facts.rootless)
        self.assertTrue(facts.newuidmap)
        self.assertEqual(
            facts.containers,
            (
                (
                    "erplibre-call-coturn",
                    "docker",
                    False,
                    "running",
                    COTURN_REF,
                ),
            ),
        )
        self.assertEqual(facts.images, (("docker", False, COTURN_REF),))
        self.assertEqual(facts.ntfy_host_version, "2.11.0")
        self.assertTrue(facts.sqlite3)
        self.assertEqual(facts.compose_text, "# erplibre-call: managed\n")

    def test_rootless_account_facts(self):
        pairs = [
            ("ACCOUNT", "erplibre-call 990 990"),
            ("ROOTLESS", "1 1 1 1 enabled"),
            ("CONTAINER", "erplibre-call-ntfy podman 1 exited " + NTFY_REF),
            ("IMAGE", "podman 1 " + NTFY_REF),
        ]
        facts = cc.parse_engine_lines(pairs)
        self.assertEqual(
            facts.rootless,
            {
                "subuid": True,
                "subgid": True,
                "linger": True,
                "newuidmap": True,
                "user_restart": "enabled",
            },
        )
        self.assertEqual(
            facts.containers,
            (("erplibre-call-ntfy", "podman", True, "exited", NTFY_REF),),
        )
        self.assertEqual(facts.images, (("podman", True, NTFY_REF),))

    def test_defaults_without_markers(self):
        facts = cc.parse_engine_lines([])
        self.assertEqual(facts.engines, {})
        self.assertEqual(facts.compose, {})
        self.assertIsNone(facts.docker_service)
        self.assertIsNone(facts.podman_restart)
        self.assertEqual(facts.unpriv_port_start, 1024)
        self.assertEqual(facts.accounts, {})
        self.assertIsNone(facts.rootless)
        self.assertFalse(facts.newuidmap)
        self.assertEqual(facts.containers, ())
        self.assertEqual(facts.images, ())
        self.assertIsNone(facts.ntfy_host_version)
        self.assertFalse(facts.sqlite3)
        self.assertEqual(facts.compose_text, "")

    def test_malformed_lines_are_dropped(self):
        pairs = [
            ("ENGINE", "lxc 1.0"),
            ("ENGINE", "docker not-a-version;"),
            ("COMPOSE", "podman podman compose"),
            ("COMPOSE", "docker rm -rf"),
            ("UNPRIV_PORT", "abc"),
            ("ACCOUNT", "intrus 1000 1000"),
            ("ACCOUNT", "ntfy x 997"),
            ("CONTAINER", "erplibre-call-coturn lxc 0 running x"),
            ("CONTAINER", "erplibre-call-coturn docker 2 running x"),
            ("IMAGE", "docker 0 docker.io/autre/image:1"),
            ("NTFY_HOST", "$(id)"),
            ("SQLITE", "oui"),
            ("COMPOSE_FILE", "pas du base64 !"),
            ("DOCKER_SERVICE", "active"),
            ("PODMAN_RESTART", "en marche;"),
        ]
        facts = cc.parse_engine_lines(pairs)
        self.assertEqual(facts.engines, {})
        self.assertEqual(facts.compose, {})
        self.assertEqual(facts.unpriv_port_start, 1024)
        self.assertEqual(facts.accounts, {})
        self.assertEqual(facts.containers, ())
        self.assertEqual(facts.images, ())
        self.assertIsNone(facts.ntfy_host_version)
        self.assertFalse(facts.sqlite3)
        self.assertEqual(facts.compose_text, "")
        self.assertIsNone(facts.docker_service)
        self.assertIsNone(facts.podman_restart)

    def test_first_compose_provider_wins(self):
        facts = cc.parse_engine_lines(
            [
                ("COMPOSE", "docker docker-compose"),
                ("COMPOSE", "docker docker compose"),
            ]
        )
        self.assertEqual(facts.compose, {"docker": ("docker-compose",)})


class TestComposeText(unittest.TestCase):
    def test_rootful_both_services(self):
        text = cc.compose_text(
            ("coturn", "ntfy"), "/etc/turnserver.conf", False
        )
        self.assertEqual(text.splitlines()[0], "# erplibre-call: managed")
        self.assertEqual(text.count("network_mode: host"), 2)
        self.assertEqual(text.count("restart: always"), 2)
        self.assertIn("image: " + COTURN_REF, text)
        self.assertIn("image: " + NTFY_REF, text)
        self.assertIn('user: "@USER_COTURN@"', text)
        self.assertIn('user: "@USER_NTFY@"', text)
        self.assertIn("container_name: erplibre-call-coturn", text)
        self.assertIn("container_name: erplibre-call-ntfy", text)
        self.assertNotIn("keep-id", text)
        self.assertNotIn("no-new-privileges", text)
        self.assertNotIn("ports:", text)
        self.assertIn('command: ["-c", "/etc/turnserver.conf"]', text)
        self.assertIn('command: ["serve"]', text)
        for mount in (
            "/var/lib/erplibre-call:/var/lib/erplibre-call",
            "/etc/erplibre-call/tls:/etc/erplibre-call/tls:ro",
            "/etc/turnserver.conf:/etc/turnserver.conf:ro",
            "/etc/ntfy:/etc/ntfy:ro",
            "/var/cache/ntfy:/var/cache/ntfy",
            "/var/lib/ntfy:/var/lib/ntfy",
        ):
            self.assertIn("      - " + mount + "\n", text)
        # podman-compose met chaque conteneur dans un pod par défaut, et
        # Podman refuse alors --userns comme le réseau de l'hôte.
        self.assertIn("x-podman:\n  in_pod: false\n", text)

    def test_rootless_adds_keep_id_on_both(self):
        text = cc.compose_text(
            ("coturn", "ntfy"), "/etc/turnserver.conf", True
        )
        self.assertEqual(text.count("userns_mode: keep-id"), 2)

    def test_one_service_and_arch_config(self):
        text = cc.compose_text(
            ("coturn",), "/etc/turnserver/turnserver.conf", False
        )
        self.assertNotIn("ntfy", text)
        self.assertIn(
            "/etc/turnserver/turnserver.conf:/etc/turnserver/turnserver.conf:ro",
            text,
        )
        text = cc.compose_text(("ntfy",), "/etc/turnserver.conf", False)
        self.assertNotIn("coturn", text)

    def test_order_does_not_depend_on_the_argument(self):
        self.assertEqual(
            cc.compose_text(("ntfy", "coturn"), "/etc/turnserver.conf", False),
            cc.compose_text(("coturn", "ntfy"), "/etc/turnserver.conf", False),
        )

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            cc.compose_text(("nginx",), "/etc/turnserver.conf", False)
        with self.assertRaises(ValueError):
            cc.compose_text((), "/etc/turnserver.conf", False)
        with self.assertRaises(ValueError):
            cc.compose_text(("coturn",), "etc/turnserver.conf", False)
        with self.assertRaises(ValueError):
            cc.compose_text(("coturn",), "/etc/a b.conf", False)

    def test_resolved(self):
        template = cc.compose_text(
            ("coturn", "ntfy"), "/etc/turnserver.conf", False
        )
        text = cc.compose_resolved(
            template, {"coturn": "998:998", "ntfy": "997:997"}
        )
        self.assertIn('user: "998:998"', text)
        self.assertIn('user: "997:997"', text)
        self.assertNotIn("@USER_", text)

    def test_resolved_refuses_missing_or_bad_users(self):
        template = cc.compose_text(
            ("coturn", "ntfy"), "/etc/turnserver.conf", False
        )
        with self.assertRaises(ValueError):
            cc.compose_resolved(template, {"coturn": "998:998"})
        with self.assertRaises(ValueError):
            cc.compose_resolved(
                template, {"coturn": "998:998", "ntfy": "root"}
            )
        with self.assertRaises(ValueError):
            cc.compose_resolved(template, {"coturn": "0:0", "ntfy": "997:997"})


class TestArgv(unittest.TestCase):
    def test_rootless_prefix(self):
        self.assertEqual(
            cc.rootless_prefix("erplibre-call", 990),
            [
                "runuser",
                "-u",
                "erplibre-call",
                "--",
                "env",
                "XDG_RUNTIME_DIR=/run/user/990",
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/990/bus",
            ],
        )

    def test_compose_argv_rootless(self):
        argv = cc.compose_argv(rootless_block())
        self.assertEqual(
            argv[:6],
            [
                "runuser",
                "-u",
                "erplibre-call",
                "--",
                "env",
                "XDG_RUNTIME_DIR=/run/user/990",
            ],
        )
        self.assertEqual(
            argv[7:],
            ["podman-compose", "-f", cc.COMPOSE_FILE, "-p", cc.PROJECT],
        )

    def test_compose_argv_rootful(self):
        self.assertEqual(
            cc.compose_argv(rootful_block()),
            ["docker", "compose", "-f", cc.COMPOSE_FILE, "-p", cc.PROJECT],
        )
        self.assertEqual(
            cc.compose_argv(rootful_block(compose=["docker-compose"])),
            ["docker-compose", "-f", cc.COMPOSE_FILE, "-p", cc.PROJECT],
        )

    def test_engine_argv(self):
        self.assertEqual(cc.engine_argv(rootful_block()), ["docker"])
        self.assertEqual(
            cc.engine_argv(rootless_block()),
            cc.rootless_prefix("erplibre-call", 990) + ["podman"],
        )

    def test_argv_refuses_a_tampered_block(self):
        for block in (
            rootful_block(engine="sh"),
            rootful_block(compose=["sh", "-c"]),
            rootless_block(account="root"),
            rootless_block(uid=0),
        ):
            with self.assertRaises(ValueError):
                cc.engine_argv(block)
            with self.assertRaises(ValueError):
                cc.compose_argv(block)


class TestContainerBlockProblem(unittest.TestCase):
    def test_valid_states(self):
        self.assertIsNone(cc.container_block_problem(container_state()))
        state = container_state(
            rootless_block(),
            coturn={"account": "erplibre-call", "uid": 990, "gid": 990},
            ntfy={"account": "erplibre-call", "uid": 990, "gid": 990},
        )
        self.assertIsNone(cc.container_block_problem(state))
        state = container_state(rootful_block(compose=["docker-compose"]))
        self.assertIsNone(cc.container_block_problem(state))
        del state["services"]["ntfy"]
        self.assertIsNone(cc.container_block_problem(state))

    def test_first_invalid_field_is_named(self):
        cases = [
            (container_state(rootful_block(engine="lxc")), "engine"),
            (container_state(rootful_block(rootless="no")), "rootless"),
            (container_state(rootful_block(rootless=True)), "rootless"),
            (container_state(rootless_block(account="root")), "account"),
            (container_state(rootless_block(account="A;b")), "account"),
            (container_state(rootless_block(uid=0)), "uid"),
            (container_state(rootless_block(uid=True)), "uid"),
            (container_state(rootless_block(uid=2**31)), "uid"),
            (container_state(rootless_block(uid="990")), "uid"),
            (container_state(rootful_block(account="ntfy")), "account"),
            (container_state(rootful_block(uid=997)), "uid"),
            (
                container_state(rootful_block(compose=["podman-compose"])),
                "compose",
            ),
            (
                container_state(rootful_block(compose="docker compose")),
                "compose",
            ),
            (
                container_state(rootless_block(compose=["docker", "compose"])),
                "compose",
            ),
            (
                container_state(rootful_block(compose_file="/tmp/x.yml")),
                "compose_file",
            ),
            (container_state(rootful_block(project="autre")), "project"),
            (
                container_state(coturn={"container": "--privileged"}),
                "services.coturn.container",
            ),
            (
                container_state(ntfy={"container": "erplibre-call-coturn"}),
                "services.ntfy.container",
            ),
            (
                container_state(coturn={"account": "root"}),
                "services.coturn.account",
            ),
            (container_state(ntfy={"uid": -1}), "services.ntfy.uid"),
            (container_state(ntfy={"gid": None}), "services.ntfy.gid"),
            (
                container_state(rootless_block(account="erplibre-call\n")),
                "account",
            ),
            (
                container_state(coturn={"account": "turnserver\n"}),
                "services.coturn.account",
            ),
        ]
        for state, field in cases:
            with self.subTest(field=field, state=state):
                self.assertEqual(cc.container_block_problem(state), field)

    def test_missing_or_wrong_shapes(self):
        self.assertEqual(cc.container_block_problem({}), "container")
        self.assertEqual(
            cc.container_block_problem({"container": []}), "container"
        )
        state = container_state()
        state["services"] = []
        self.assertEqual(cc.container_block_problem(state), "services")
        state = container_state()
        state["services"]["nginx"] = {}
        self.assertEqual(cc.container_block_problem(state), "services.nginx")
        state = container_state()
        state["services"]["coturn"] = "x"
        self.assertEqual(cc.container_block_problem(state), "services.coturn")


class TestEnginePackages(unittest.TestCase):
    NONE = cc.EngineFacts()

    def test_per_distribution(self):
        cases = [
            (
                ("ubuntu", "debian", "docker", False),
                ("docker.io", "docker-compose-v2"),
            ),
            (
                ("debian", "debian", "docker", False),
                ("docker.io", "docker-compose"),
            ),
            (("arch", "arch", "docker", False), ("docker", "docker-compose")),
            (
                ("debian", "debian", "podman", False),
                ("podman", "podman-compose"),
            ),
            (("arch", "arch", "podman", False), ("podman", "podman-compose")),
            (
                ("debian", "debian", "podman", True),
                ("podman", "podman-compose", "uidmap"),
            ),
            (
                ("ubuntu", "debian", "podman", True),
                ("podman", "podman-compose", "uidmap"),
            ),
            (("arch", "arch", "podman", True), ("podman", "podman-compose")),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(
                    cc.engine_packages(*args, self.NONE), expected
                )

    def test_none_facts_means_nothing_present(self):
        self.assertEqual(
            cc.engine_packages("ubuntu", "debian", "docker", False, None),
            ("docker.io", "docker-compose-v2"),
        )

    def test_only_what_is_missing(self):
        facts = cc.parse_engine_lines(PROBE_PAIRS)
        self.assertEqual(
            cc.engine_packages("debian", "debian", "docker", False, facts), ()
        )
        self.assertEqual(
            cc.engine_packages("debian", "debian", "podman", True, facts), ()
        )
        facts = cc.parse_engine_lines(
            [("ENGINE", "docker 26.1.5"), ("DOCKER_SERVICE", "active enabled")]
        )
        self.assertEqual(
            cc.engine_packages("debian", "debian", "docker", False, facts),
            ("docker-compose",),
        )

    def test_docker_client_without_its_daemon_unit_is_not_an_engine(self):
        # Le client seul parle à un démon d'ailleurs : le paquet du moteur
        # est proposé, comme sur un hôte sans Docker.
        for service in ("inactive -", "inactive not-found", None):
            with self.subTest(service=service):
                pairs = [("ENGINE", "docker 26.1.5")]
                if service:
                    pairs.append(("DOCKER_SERVICE", service))
                pairs.append(("COMPOSE", "docker docker compose"))
                facts = cc.parse_engine_lines(pairs)
                self.assertFalse(cc.engine_present(facts, "docker"))
                self.assertEqual(
                    cc.engine_packages(
                        "debian", "debian", "docker", False, facts
                    ),
                    ("docker.io",),
                )
        facts = cc.parse_engine_lines(
            [
                ("ENGINE", "docker 26.1.5"),
                ("DOCKER_SERVICE", "inactive disabled"),
            ]
        )
        self.assertTrue(cc.engine_present(facts, "docker"))
        self.assertTrue(
            cc.engine_present(
                cc.parse_engine_lines([("ENGINE", "podman 5.4.2")]), "podman"
            )
        )

    def test_unknown_engine_or_family(self):
        with self.assertRaises(ValueError):
            cc.engine_packages("debian", "debian", "lxc", False, self.NONE)
        with self.assertRaises(ValueError):
            cc.engine_packages("fedora", None, "docker", False, self.NONE)
        with self.assertRaises(ValueError):
            cc.engine_packages("debian", "debian", "docker", True, self.NONE)


class TestSmallRules(unittest.TestCase):
    def test_classify_pull(self):
        self.assertEqual(
            cc.classify_pull(
                "toomanyrequests: You have reached your pull rate limit."
            ),
            "rate-limit",
        )
        self.assertEqual(
            cc.classify_pull("Error response from daemon: TOOMANYREQUESTS"),
            "rate-limit",
        )
        self.assertEqual(
            cc.classify_pull("reading manifest: received 429 Too Many"),
            "rate-limit",
        )
        self.assertEqual(
            cc.classify_pull("dial tcp: lookup registry: no such host"),
            "failed",
        )
        self.assertEqual(cc.classify_pull("size 14290 bytes"), "failed")
        self.assertEqual(cc.classify_pull(""), "failed")

    def test_version_older(self):
        self.assertTrue(cc.version_older("2.11.0", "2.36.0"))
        self.assertFalse(cc.version_older("2.36.0", "2.36.0"))
        self.assertFalse(cc.version_older("v2.37.1", "2.36.0"))
        self.assertTrue(cc.version_older("2.34", "2.36.0"))
        self.assertFalse(cc.version_older("26.1.5+dfsg1", "26.1.5"))
        self.assertFalse(cc.version_older("10.0.0", "9.99.99"))
        # Une version illisible compte pour plus ancienne : le doute ne
        # laisse pas passer une base que le binaire ne relirait pas.
        self.assertTrue(cc.version_older("inconnue", "2.36.0"))
        with self.assertRaises(ValueError):
            cc.version_older("2.0", "x")

    def test_foreign_containers(self):
        facts = cc.parse_engine_lines(
            [
                (
                    "CONTAINER",
                    "erplibre-call-coturn docker 0 running " + COTURN_REF,
                ),
                (
                    "CONTAINER",
                    "erplibre-call-ntfy docker 0 exited " + NTFY_REF,
                ),
                ("CONTAINER", "mon-ntfy podman 1 running " + NTFY_REF),
            ]
        )
        self.assertEqual(
            cc.foreign_containers(facts, None),
            ("erplibre-call-coturn", "erplibre-call-ntfy", "mon-ntfy"),
        )
        self.assertEqual(
            cc.foreign_containers(facts, {"version": 1, "services": {}}),
            ("erplibre-call-coturn", "erplibre-call-ntfy", "mon-ntfy"),
        )
        self.assertEqual(
            cc.foreign_containers(facts, container_state()), ("mon-ntfy",)
        )
        # Les mêmes noms sous un autre moteur ne sont pas les nôtres.
        state = container_state(
            rootless_block(),
            coturn={"account": "erplibre-call", "uid": 990, "gid": 990},
            ntfy={"account": "erplibre-call", "uid": 990, "gid": 990},
        )
        self.assertEqual(
            cc.foreign_containers(facts, state),
            ("erplibre-call-coturn", "erplibre-call-ntfy", "mon-ntfy"),
        )
        # Un service que l'état ne consigne pas n'a pas de conteneur à nous.
        state = container_state()
        del state["services"]["ntfy"]
        self.assertEqual(
            cc.foreign_containers(facts, state),
            ("erplibre-call-ntfy", "mon-ntfy"),
        )
        self.assertEqual(cc.foreign_containers(None, None), ())


# Outils réels que la sonde emploie ; tout le reste est un bouchon ou absent.
BASE_TOOLS = (
    "sh",
    "awk",
    "sed",
    "grep",
    "base64",
    "cat",
    "head",
    "env",
    "tr",
    "basename",
)

# Toute commande qu'un bouchon reçoit est notée, une ligne par appel.
LOGGER = '#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >> "$LOG"\n'

PASSWD = {
    "turnserver": "turnserver:x:998:998::/var/lib/turnserver:/bin/false",
    "ntfy": "ntfy:x:997:997::/var/lib/ntfy:/usr/sbin/nologin",
    "erplibre-call": (
        "erplibre-call:x:990:990::/var/lib/erplibre-call-podman:/bin/sh"
    ),
}


def write(path, text, mode=0o755):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    os.chmod(path, mode)


def engine_stubs(stubs, docker_active=True, rootless=True, absent=()):
    """Bouchons de chaque commande que la sonde peut lancer. `absent` : noms
    à ne pas poser, la sonde doit alors les dire absents."""
    ps = (
        "erplibre-call-coturn running %s\n"
        "autre-chose running docker.io/library/nginx:1\n"
        "mon-ntfy exited docker.io/binwiederhier/ntfy:v2.30.0\n" % COTURN_REF
    )
    scripts = {
        "docker": LOGGER + 'case "$1" in\n'
        "  --version) echo 'Docker version 26.1.5+dfsg1, build a72d7cd' ;;\n"
        '  compose) [ "$2" = version ] && echo \'Docker Compose version'
        " 2.26.1' ;;\n"
        "  ps) cat <<'EOF'\n" + ps + "EOF\n;;\n"
        '  image) [ "$3" = ' + COTURN_REF + " ] || exit 1 ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        "podman": LOGGER + 'case "$1" in\n'
        "  --version) echo 'podman version 5.4.2' ;;\n"
        "  ps) echo 'erplibre-call-ntfy running " + NTFY_REF + "' ;;\n"
        '  image) [ "$3" = ' + NTFY_REF + " ] || exit 1 ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        "docker-compose": LOGGER,
        "podman-compose": LOGGER,
        "newuidmap": LOGGER,
        "sqlite3": LOGGER,
        "ntfy": LOGGER
        + "[ \"$1\" = --version ] && echo 'ntfy 2.11.0 (2.11.0-2), runtime go'\n",
        "timeout": LOGGER + 'shift\nexec "$@"\n',
        # runuser saute ses options jusqu'à « -- » puis lance le reste.
        "runuser": LOGGER
        + 'while [ "$#" -gt 0 ] && [ "$1" != -- ]; do shift; done\n'
        'shift\nexec "$@"\n',
        "getent": LOGGER
        + 'case "$2" in\n'
        + "".join(
            "  %s) echo '%s' ;;\n" % (name, line)
            for name, line in PASSWD.items()
            if rootless or name != "erplibre-call"
        )
        + "  *) exit 2 ;;\n"
        "esac\n",
        "systemctl": LOGGER + 'case "$*" in\n'
        "  'is-active docker.service') echo %s ;;\n"
        "  'is-enabled docker.service') echo enabled ;;\n"
        "  'is-enabled podman-restart.service') echo disabled ;;\n"
        "  '--user is-enabled podman-restart.service') echo enabled ;;\n"
        "  *) exit 3 ;;\n"
        "esac\n" % ("active" if docker_active else "inactive"),
    }
    for name in (
        "loginctl",
        "useradd",
        "usermod",
        "userdel",
        "apt-get",
        "pacman",
        "sudo",
    ):
        scripts[name] = LOGGER + "exit 99\n"
    for name, text in scripts.items():
        if name not in absent:
            write(os.path.join(stubs, name), text)


class TestEngineProbeRun(unittest.TestCase):
    """La section de sonde jouée pour de vrai, PATH fermé sur les bouchons."""

    def run_probe(self, root_files=(), **stub_options):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            stubs = os.path.join(tmp, "stubs")
            tools = os.path.join(tmp, "tools")
            log = os.path.join(tmp, "argv.log")
            os.makedirs(root)
            os.makedirs(tools)
            for name in BASE_TOOLS:
                os.symlink(shutil.which(name), os.path.join(tools, name))
            engine_stubs(stubs, **stub_options)
            for path, text in root_files:
                if text is None:
                    os.makedirs(os.path.join(root, path.lstrip("/")))
                else:
                    write(os.path.join(root, path.lstrip("/")), text, 0o644)
            done = subprocess.run(
                [
                    os.path.join(tools, "sh"),
                    "-c",
                    "\n".join(cc.engine_probe_lines(root)),
                ],
                capture_output=True,
                text=True,
                env={"PATH": stubs + ":" + tools, "LOG": log, "LC_ALL": "C"},
                timeout=30,
            )
            calls = []
            if os.path.exists(log):
                with open(log) as handle:
                    calls = handle.read().splitlines()
            return done, calls

    FULL_ROOT = (
        ("/proc/sys/net/ipv4/ip_unprivileged_port_start", "80\n"),
        ("/etc/subuid", "erplibre-call:100000:65536\n"),
        ("/etc/subgid", "autre:100000:65536\n"),
        ("/var/lib/systemd/linger/erplibre-call", ""),
        ("/run/user/990", None),
        ("/var/lib/containers/storage", None),
        (
            "/var/lib/erplibre-call-podman/.local/share/containers/storage",
            None,
        ),
        ("/etc/erplibre-call/compose.yml", "# erplibre-call: managed\nx: 1\n"),
    )

    def assert_read_only(self, calls):
        for call in calls:
            words = call.split()
            for forbidden in (
                "pull",
                "run",
                "rm",
                "rmi",
                "create",
                "start",
                "stop",
                "up",
                "down",
                "kill",
                "exec",
                "info",
                "enable",
                "enable-linger",
            ):
                self.assertNotIn(forbidden, words[1:], call)
            self.assertNotIn(
                words[0],
                (
                    "loginctl",
                    "useradd",
                    "usermod",
                    "userdel",
                    "apt-get",
                    "pacman",
                    "sudo",
                    "docker-compose",
                    "podman-compose",
                    "sqlite3",
                    "newuidmap",
                ),
                call,
            )

    def test_full_host(self):
        done, calls = self.run_probe(self.FULL_ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        facts = cc.parse_engine_lines(ci.marker_lines(done.stdout))
        self.assertEqual(
            facts.engines, {"docker": "26.1.5+dfsg1", "podman": "5.4.2"}
        )
        self.assertEqual(
            facts.compose,
            {"docker": ("docker", "compose"), "podman": ("podman-compose",)},
        )
        self.assertEqual(facts.docker_service, ("active", "enabled"))
        self.assertEqual(facts.podman_restart, "disabled")
        self.assertEqual(facts.unpriv_port_start, 80)
        self.assertEqual(
            facts.accounts,
            {
                "turnserver": (998, 998),
                "ntfy": (997, 997),
                "erplibre-call": (990, 990),
            },
        )
        self.assertEqual(
            facts.rootless,
            {
                "subuid": True,
                "subgid": False,
                "linger": True,
                "newuidmap": True,
                "user_restart": "enabled",
            },
        )
        self.assertEqual(
            set(facts.containers),
            {
                (
                    "erplibre-call-coturn",
                    "docker",
                    False,
                    "running",
                    COTURN_REF,
                ),
                (
                    "mon-ntfy",
                    "docker",
                    False,
                    "exited",
                    "docker.io/binwiederhier/ntfy:v2.30.0",
                ),
                ("erplibre-call-ntfy", "podman", False, "running", NTFY_REF),
                ("erplibre-call-ntfy", "podman", True, "running", NTFY_REF),
            },
        )
        self.assertIn(("docker", False, COTURN_REF), facts.images)
        self.assertIn(("podman", True, NTFY_REF), facts.images)
        self.assertNotIn(("docker", False, NTFY_REF), facts.images)
        self.assertEqual(facts.ntfy_host_version, "2.11.0")
        self.assertTrue(facts.sqlite3)
        self.assertEqual(
            facts.compose_text, "# erplibre-call: managed\nx: 1\n"
        )
        self.assert_read_only(calls)
        # Chaque appel d'un moteur passe par « timeout 20 ».
        for call in calls:
            if call.split()[0] in ("docker", "podman"):
                self.assertTrue(
                    any(
                        c.startswith("timeout 20 ") and c.endswith(call)
                        for c in calls
                    ),
                    call,
                )
        # Le moteur rootless passe par runuser, avec l'environnement du compte.
        self.assertIn(
            "runuser -u erplibre-call -- env XDG_RUNTIME_DIR=/run/user/990"
            " DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/990/bus podman ps"
            " -a --format {{.Names}} {{.State}} {{.Image}}",
            calls,
        )

    def test_nothing_installed(self):
        done, calls = self.run_probe(
            absent=(
                "docker",
                "podman",
                "docker-compose",
                "podman-compose",
                "newuidmap",
                "sqlite3",
                "ntfy",
            ),
            rootless=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("@@ENGINE", done.stdout)
        facts = cc.parse_engine_lines(ci.marker_lines(done.stdout))
        self.assertEqual(facts.engines, {})
        self.assertEqual(facts.compose, {})
        self.assertIsNone(facts.docker_service)
        self.assertIsNone(facts.podman_restart)
        self.assertEqual(facts.unpriv_port_start, 1024)
        self.assertIsNone(facts.rootless)
        self.assertFalse(facts.newuidmap)
        self.assertFalse(facts.sqlite3)
        self.assertIsNone(facts.ntfy_host_version)
        self.assertEqual(facts.compose_text, "")
        self.assertFalse([c for c in calls if c.startswith("runuser")])

    def test_inactive_docker_is_not_woken(self):
        # Une socket active démarrerait dockerd au premier « docker ps » :
        # la sonde ne parle au démon que s'il tourne déjà.
        done, calls = self.run_probe(self.FULL_ROOT, docker_active=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        facts = cc.parse_engine_lines(ci.marker_lines(done.stdout))
        self.assertEqual(facts.engines["docker"], "26.1.5+dfsg1")
        self.assertEqual(facts.docker_service, ("inactive", "enabled"))
        docker_calls = [c.split()[1] for c in calls if c.startswith("docker ")]
        self.assertEqual(sorted(set(docker_calls)), ["--version", "compose"])
        self.assertFalse([c for c in facts.containers if c[1] == "docker"])

    def test_podman_without_storage_is_not_asked(self):
        # Sans stockage, « podman ps » le créerait ; sans /run/user/<uid>, le
        # compte rootless n'a pas de session à interroger.
        done, calls = self.run_probe(
            (("/etc/subuid", "erplibre-call:100000:65536\n"),)
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        podman_calls = [c.split()[1] for c in calls if c.startswith("podman ")]
        self.assertEqual(podman_calls, ["--version"])
        self.assertFalse([c for c in calls if c.startswith("runuser")])
        facts = cc.parse_engine_lines(ci.marker_lines(done.stdout))
        self.assertEqual(facts.rootless["user_restart"], None)
        self.assertTrue(facts.rootless["subuid"])

    def test_probe_text_writes_nothing(self):
        script = "\n".join(cc.engine_probe_lines())
        stripped = script.replace("2>/dev/null", "").replace(">/dev/null", "")
        stripped = stripped.replace("2>&1", "")
        self.assertNotIn(">", stripped)
        for word in ("pull", " run ", " rm ", "rmi", " up ", "loginctl"):
            self.assertNotIn(word, script)


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        path = os.path.join(REPO, "script", "todo", "call_infra_container.py")
        with open(path) as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(
                        alias.name.split(".")[0], sys.stdlib_module_names
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertTrue(node.module, "import relatif")
                self.assertIn(
                    node.module.split(".")[0], sys.stdlib_module_names
                )

    def test_module_runs_nothing_locally(self):
        path = os.path.join(REPO, "script", "todo", "call_infra_container.py")
        with open(path) as handle:
            text = handle.read()
        self.assertNotIn("subprocess", text)
        self.assertNotIn("os.system", text)


if __name__ == "__main__":
    unittest.main()
