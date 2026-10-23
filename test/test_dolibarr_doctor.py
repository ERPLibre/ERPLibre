#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le bilan de santé d'une instance Dolibarr inscrite au registre.

Un système simulé répond aux commandes (git, systemctl, php, moteur) et au
HTTP ; conf.php et install.lock sont de vrais fichiers, pour leurs modes.
Ce qui se garde :
- chaque vérification rend ok, warn ou fail, avec ce qui la fonde ;
- une production est plus stricte qu'un développement : code modifié,
  install.lock absent, /install/ servi ou conf.php lisible de tous y sont
  des échecs ;
- le code de production se juge contre l'archive du commit épinglé ;
- un seul échec suffit pour que le code de sortie le dise.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import doctor  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
AUTRE = "f" * 40
PAGE = "<title>Login @ 24.0.1</title>"


class Systeme:
    def __init__(self):
        self.pages = {}  # url -> page
        self.commandes = {}  # tuple(argv) -> (code, sortie)
        self.appels = []

    def run(self, argv):
        self.appels.append(list(argv))
        return self.commandes.get(tuple(argv), (1, ""))

    def http_get(self, url, host):
        return self.pages.get(url, "ERROR connection refused")


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.sys = Systeme()
        self.pin = {
            "commit": COMMIT,
            "version": "24.0.1",
            "php_min": "7.2",
            "php_max": "8.5",
            "path": "dolibarr/dolibarr",
            "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
        }
        self.sys.commandes[
            ("php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;')
        ] = (0, "8.3")

    def verifier(self, nom, entree):
        return {
            r.key: r
            for r in doctor.check_instance(
                nom, entree, self.pin, self.sys, str(self.racine)
            )
        }


class TestDeveloppement(Banc):
    def setUp(self):
        super().setUp()
        self.checkout = self.racine / "dolibarr" / "dolibarr"
        htdocs = self.checkout / "htdocs"
        (htdocs / "conf").mkdir(parents=True)
        conf = htdocs / "conf" / "conf.php"
        conf.write_text("<?php\n")
        conf.chmod(0o600)
        (htdocs / "install.lock").write_text("")
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "url": "http://127.0.0.1:8080",
            "version": "24.0.1",
            "commit": COMMIT,
            "code_root": str(self.checkout),
        }
        self.sys.pages["http://127.0.0.1:8080/"] = PAGE
        g = ("git", "-C", str(self.checkout))
        self.sys.commandes[g + ("rev-parse", "HEAD")] = (0, COMMIT + "\n")
        self.sys.commandes[
            g + ("status", "--porcelain", "--untracked-files=no")
        ] = (0, "")

    def test_a_healthy_development_instance_is_all_ok(self):
        r = self.verifier("erp", self.entree)
        self.assertEqual(
            {k: v.level for k, v in r.items()},
            {
                "served": "ok",
                "pin": "ok",
                "code": "ok",
                "conf": "ok",
                "lock": "ok",
                "php": "ok",
            },
        )

    def test_core_changes_in_development_are_a_warning(self):
        g = ("git", "-C", str(self.checkout))
        self.sys.commandes[
            g + ("status", "--porcelain", "--untracked-files=no")
        ] = (0, " M htdocs/core/lib/functions.lib.php\n")
        r = self.verifier("erp", self.entree)
        self.assertEqual(r["code"].level, "warn")
        self.assertIn("1", r["code"].detail)

    def test_a_checkout_away_from_the_pin_is_a_warning(self):
        g = ("git", "-C", str(self.checkout))
        self.sys.commandes[g + ("rev-parse", "HEAD")] = (0, AUTRE + "\n")
        r = self.verifier("erp", self.entree)
        self.assertEqual(r["code"].level, "warn")
        self.assertIn(AUTRE[:7], r["code"].detail)

    def test_an_instance_behind_the_pin_is_a_warning(self):
        # Après une montée revenue en arrière, rien d'autre ne le dirait.
        self.pin["commit"] = AUTRE
        r = self.verifier("erp", self.entree)
        self.assertEqual(r["pin"].level, "warn")
        self.assertIn(AUTRE[:7], r["pin"].detail)

    def test_a_site_that_does_not_answer_fails(self):
        self.sys.pages = {}
        self.assertEqual(
            self.verifier("erp", self.entree)["served"].level, "fail"
        )

    def test_another_served_version_is_a_warning(self):
        self.sys.pages["http://127.0.0.1:8080/"] = (
            "<title>Login @ 24.0.2</title>"
        )
        self.assertEqual(
            self.verifier("erp", self.entree)["served"].level, "warn"
        )

    def test_a_conf_readable_by_all_fails(self):
        (self.checkout / "htdocs" / "conf" / "conf.php").chmod(0o644)
        self.assertEqual(
            self.verifier("erp", self.entree)["conf"].level, "fail"
        )

    def test_php_outside_the_supported_range_fails(self):
        self.sys.commandes[
            ("php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;')
        ] = (0, "8.6")
        self.assertEqual(
            self.verifier("erp", self.entree)["php"].level, "fail"
        )


class TestProduction(Banc):
    def setUp(self):
        super().setUp()
        self.code = self.racine / "opt" / "erp"
        conf = self.code / "htdocs" / "conf" / "conf.php"
        conf.parent.mkdir(parents=True)
        conf.write_text("<?php\n")
        conf.chmod(0o440)
        (self.code / "htdocs" / "install.lock").write_text("")
        self.entree = {
            "mode": "prod",
            "runtime": "native",
            "url": "https://erp.example.org",
            "domain": "erp.example.org",
            "tls": "local",
            "version": "24.0.1",
            "commit": COMMIT,
            "code_root": str(self.code),
            "cron_timer": "erplibre-dolibarr-cron-erp.timer",
        }
        self.sys.pages["https://127.0.0.1/"] = PAGE
        self.sys.pages["https://127.0.0.1/install/"] = "ERROR HTTP Error 403"
        s = "erplibre-dolibarr-cron-erp"
        self.sys.commandes[("systemctl", "is-active", f"{s}.timer")] = (
            0,
            "active\n",
        )
        self.sys.commandes[
            ("systemctl", "show", f"{s}.service", "-p", "Result", "--value")
        ] = (0, "success\n")
        self.ecart = {
            "modified": [],
            "missing": [],
            "added": [],
            "unreadable": [],
            "custom": [],
        }
        patches = [
            mock.patch.object(
                doctor.integrity, "archive_blobs", lambda c, commit: {"x": 1}
            ),
            mock.patch.object(
                doctor.integrity, "compare_tree", lambda root, b: self.ecart
            ),
            mock.patch.object(doctor, "owner_is_expected", lambda st, e: True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_a_healthy_production_is_all_ok(self):
        r = self.verifier("erp", self.entree)
        self.assertEqual(
            {k: v.level for k, v in r.items()},
            {
                "served": "ok",
                "pin": "ok",
                "code": "ok",
                "conf": "ok",
                "lock": "ok",
                "install": "ok",
                "cron": "ok",
                "php": "ok",
            },
        )

    def test_an_added_file_in_the_code_fails(self):
        self.ecart["added"] = ["htdocs/core/shell.php"]
        r = self.verifier("erp", self.entree)
        self.assertEqual(r["code"].level, "fail")
        self.assertIn("htdocs/core/shell.php", r["code"].detail)

    def test_unreadable_code_is_a_warning_not_a_pass(self):
        self.ecart["unreadable"] = ["htdocs/core/"]
        r = self.verifier("erp", self.entree)
        self.assertEqual(r["code"].level, "warn")

    def test_a_conf_owned_by_the_wrong_account_fails(self):
        with mock.patch.object(
            doctor, "owner_is_expected", lambda st, e: False
        ):
            self.assertEqual(
                self.verifier("erp", self.entree)["conf"].level, "fail"
            )

    def test_a_served_install_page_fails(self):
        self.sys.pages["https://127.0.0.1/install/"] = "<title>Install</title>"
        self.assertEqual(
            self.verifier("erp", self.entree)["install"].level, "fail"
        )

    def test_a_missing_lock_fails_in_production(self):
        (self.code / "htdocs" / "install.lock").unlink()
        self.assertEqual(
            self.verifier("erp", self.entree)["lock"].level, "fail"
        )

    def test_a_writable_conf_fails_in_production(self):
        (self.code / "htdocs" / "conf" / "conf.php").chmod(0o640)
        self.assertEqual(
            self.verifier("erp", self.entree)["conf"].level, "fail"
        )

    def test_a_failed_scheduled_run_fails(self):
        s = "erplibre-dolibarr-cron-erp"
        self.sys.commandes[
            ("systemctl", "show", f"{s}.service", "-p", "Result", "--value")
        ] = (0, "exit-code\n")
        self.assertEqual(
            self.verifier("erp", self.entree)["cron"].level, "fail"
        )

    def test_an_inactive_timer_fails(self):
        s = "erplibre-dolibarr-cron-erp"
        self.sys.commandes[("systemctl", "is-active", f"{s}.timer")] = (
            3,
            "inactive\n",
        )
        self.assertEqual(
            self.verifier("erp", self.entree)["cron"].level, "fail"
        )


class TestProprietaire(unittest.TestCase):
    def stat(self, uid, gid):
        return type("St", (), {"st_uid": uid, "st_gid": gid})()

    def test_production_wants_root_and_the_instance_group(self):
        import grp

        groupe = grp.getgrgid(os.getgid()).gr_name
        entree = {"mode": "prod", "user": groupe}
        self.assertTrue(
            doctor.owner_is_expected(self.stat(0, os.getgid()), entree)
        )
        self.assertFalse(
            doctor.owner_is_expected(
                self.stat(os.getuid() or 1, os.getgid()), entree
            )
        )
        autre = dict(entree, user="dolibarr_autre_inconnu")
        self.assertFalse(
            doctor.owner_is_expected(self.stat(0, os.getgid()), autre)
        )

    def test_development_wants_the_current_account(self):
        entree = {"mode": "dev"}
        self.assertTrue(
            doctor.owner_is_expected(self.stat(os.getuid(), 0), entree)
        )
        self.assertFalse(
            doctor.owner_is_expected(self.stat(os.getuid() + 1, 0), entree)
        )


class TestConteneurs(Banc):
    def setUp(self):
        super().setUp()
        self.noms = [
            f"erplibre-dolibarr-ctr-{r}" for r in ("db", "web", "cron")
        ]
        self.entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "containers": self.noms,
            "url": "http://127.0.0.1:8081",
            "version": "24.0.0",
            "image": "docker.io/dolibarr/dolibarr:24.0.0",
        }
        self.sys.pages["http://127.0.0.1:8081/"] = (
            "<title>Login @ 24.0.0</title>"
        )
        self.sys.engine = lambda moteur: {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }
        for nom in self.noms:
            self.sys.commandes[
                (
                    "podman",
                    "container",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    nom,
                )
            ] = (0, "true\n")

    def test_three_running_containers_serving_is_ok(self):
        r = self.verifier("ctr", self.entree)
        self.assertEqual(
            {k: v.level for k, v in r.items()},
            {"served": "ok", "pin": "ok", "containers": "ok"},
        )

    def test_a_container_on_another_image_than_the_pin_is_a_warning(self):
        self.entree["image"] = "docker.io/dolibarr/dolibarr:23.0.4"
        self.pin["docker_image"] = "docker.io/dolibarr/dolibarr:24.0.0"
        self.assertEqual(
            self.verifier("ctr", self.entree)["pin"].level, "warn"
        )

    def test_a_stopped_container_is_a_warning(self):
        self.sys.commandes[
            (
                "podman",
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                self.noms[2],
            )
        ] = (0, "false\n")
        r = self.verifier("ctr", self.entree)
        self.assertEqual(r["containers"].level, "warn")
        self.assertIn(self.noms[2], r["containers"].detail)

    def test_a_missing_container_fails(self):
        del self.sys.commandes[
            (
                "podman",
                "container",
                "inspect",
                "--format",
                "{{.State.Running}}",
                self.noms[1],
            )
        ]
        self.assertEqual(
            self.verifier("ctr", self.entree)["containers"].level, "fail"
        )


class TestCommande(Banc):
    def setUp(self):
        super().setUp()
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True)
        registre.write_text(
            json.dumps({"instances": {"erp": {"mode": "dev"}}})
        )

    def lancer(self, *argv, resultats=()):
        sortie = io.StringIO()
        with (
            mock.patch.object(
                doctor,
                "check_instance",
                lambda n, e, p, s, r: list(resultats),
            ),
            mock.patch.object(
                doctor.lib_dolibarr, "read_pin", lambda r: self.pin
            ),
            contextlib.redirect_stdout(sortie),
        ):
            code = doctor.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def test_one_failure_makes_the_exit_code_say_so(self):
        code, sortie = self.lancer(
            "--instance",
            "erp",
            resultats=[doctor.Result("served", "fail", "no answer")],
        )
        self.assertEqual(code, 1)
        self.assertIn("no answer", sortie)

    def test_warnings_alone_are_success(self):
        code, _s = self.lancer(
            "--all", resultats=[doctor.Result("code", "warn", "1 file")]
        )
        self.assertEqual(code, 0)

    def test_an_unknown_instance_exits_2(self):
        code, _s = self.lancer("--instance", "nope")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
