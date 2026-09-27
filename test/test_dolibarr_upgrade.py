#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Monter une instance Dolibarr à la version épinglée.

Un système simulé répond aux commandes et à la base ; les faits viennent
d'une montée réelle 23.0.4 → 24.0.1 (natif et conteneur). Ce qui se garde :
- une sauvegarde précède toute montée, et son échec arrête tout ;
- descendre est refusé ; même version et même commit, rien à faire ; même
  version et autre commit, le schéma peut avoir changé : on monte ;
- un saut majeur à la fois pour upgrade.php et upgrade2.php, step5.php
  une fois ;
- le code de sortie ne suffit pas : MAIN_VERSION_LAST_UPGRADE doit valoir
  la cible ; sinon retour arrière (ancien code, sauvegarde restaurée) ;
- le registre ne change qu'après une montée réussie.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import upgrade  # noqa: E402

ANCIEN = "a" * 40
NOUVEAU = "b" * 40


class Systeme:
    def __init__(self):
        self.appels = []
        self.base = {"MAIN_VERSION_LAST_INSTALL": "23.0.4"}
        self.echec = set()
        self.page = "<title>Login @ 24.0.1</title>"
        self.apres_step5 = "24.0.1"

    def run(self, argv, env=None, stdin_path=None):
        self.appels.append(list(argv))
        joint = " ".join(argv)
        if any(m in joint for m in self.echec):
            return 1, "ERROR"
        if "llx_const" in joint:
            for nom, valeur in self.base.items():
                if nom in joint:
                    return 0, valeur + "\n"
            return 0, ""
        if "step5.php" in joint and self.apres_step5:
            self.base["MAIN_VERSION_LAST_UPGRADE"] = self.apres_step5
        return 0, ""

    def http_get(self, url, host):
        return self.page

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        (self.etat / "documents").mkdir(parents=True)
        (self.etat / "secrets.env").write_text("DB_PASSWORD=Mdp1\n")
        self.checkout = self.racine / "dolibarr" / "dolibarr"
        (self.checkout / "htdocs" / "install").mkdir(parents=True)
        self.pin = {
            "commit": NOUVEAU,
            "version": "24.0.1",
            "path": "dolibarr/dolibarr",
            "docker_image": "docker.io/dolibarr/dolibarr:24.0.0@sha256:"
            + "1" * 64,
        }
        self.entree = {
            "mode": "dev",
            "runtime": "native",
            "db": "mariadb",
            "db_name": "dolibarr_erp",
            "code_root": str(self.checkout),
            "data_root": str(self.etat / "documents"),
            "state_dir": str(self.etat),
            "url": "http://127.0.0.1:8080",
            "version": "23.0.4",
            "commit": ANCIEN,
            "secrets": f"file:{self.etat}/secrets.env",
        }
        self.sys = Systeme()
        self.sauvegarde = str(self.racine / "erp-pre-upgrade.tar.gz")
        patches = [
            mock.patch.object(
                upgrade.backup, "create", lambda *a, **k: self.sauvegarde
            ),
            mock.patch.object(upgrade, "stop_dev", lambda name, root: None),
            mock.patch.object(upgrade, "start_dev", lambda name, root: 0),
            mock.patch.object(upgrade.time, "sleep"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def registre(self):
        chemin = self.racine / "private" / "dolibarr" / "instances.json"
        return json.loads(chemin.read_text())["instances"]["erp"]

    def monter(self, restaure=None):
        chemin = self.racine / "private" / "dolibarr" / "instances.json"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"instances": {"erp": self.entree}}))
        sortie = io.StringIO()
        restaure = restaure or mock.MagicMock(return_value=0)
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch.object(upgrade.restore, "restore", restaure),
        ):
            code = upgrade.upgrade(
                "erp",
                self.entree,
                self.pin,
                self.sys,
                str(self.racine),
                "20260927-100000",
            )
        return code, sortie.getvalue(), restaure

    def cmds(self):
        return [" ".join(a) for a in self.sys.appels]


class TestSauts(unittest.TestCase):
    def test_one_major_at_a_time(self):
        self.assertEqual(
            upgrade.hops("23.0.4", "24.0.1"), [("23.0.4", "24.0.1")]
        )
        self.assertEqual(
            upgrade.hops("22.0.5", "24.0.1"),
            [("22.0.5", "23.0.0"), ("23.0.0", "24.0.1")],
        )
        self.assertEqual(
            upgrade.hops("24.0.1", "24.0.1"), [("24.0.1", "24.0.1")]
        )


class TestDecision(Banc):
    def test_a_downgrade_is_refused(self):
        self.entree["version"] = "25.0.0"
        code, _s, _r = self.monter()
        self.assertEqual(code, 1)
        self.assertEqual(self.sys.appels, [])

    def test_same_version_same_commit_is_up_to_date(self):
        self.entree.update(version="24.0.1", commit=NOUVEAU)
        code, _s, _r = self.monter()
        self.assertEqual(code, 0)
        self.assertEqual(self.sys.appels, [])

    def test_same_version_new_commit_still_upgrades(self):
        # Le schéma a changé entre le tag et le commit épinglé.
        self.entree.update(version="24.0.1", commit=ANCIEN)
        self.sys.base["MAIN_VERSION_LAST_UPGRADE"] = "24.0.1"
        code, sortie, _r = self.monter()
        self.assertEqual(code, 0, sortie)
        self.assertIn("php upgrade.php 24.0.1 24.0.1", " ; ".join(self.cmds()))

    def test_the_database_says_where_it_is_not_the_registry(self):
        # LAST_INSTALL reste à la version installée après une montée.
        self.sys.base["MAIN_VERSION_LAST_UPGRADE"] = "23.0.5"
        self.monter()
        self.assertIn("php upgrade.php 23.0.5 24.0.1", " ; ".join(self.cmds()))

    def test_a_failed_backup_stops_everything(self):
        with mock.patch.object(upgrade.backup, "create", lambda *a, **k: None):
            code, _s, _r = self.monter()
        self.assertEqual(code, 1)
        self.assertFalse([c for c in self.cmds() if "php" in c])


class TestNatifDev(Banc):
    def test_checkout_unlock_scripts_relock_and_record(self):
        code, sortie, _r = self.monter()
        self.assertEqual(code, 0, sortie)
        cmds = self.cmds()
        git = f"git -C {self.checkout}"
        self.assertIn(f"{git} checkout --detach {NOUVEAU}", cmds)
        joint = " ; ".join(cmds)
        u = joint.index("php upgrade.php 23.0.4 24.0.1")
        u2 = joint.index("php upgrade2.php 23.0.4 24.0.1")
        s5 = joint.index("php step5.php 23.0.4 24.0.1")
        self.assertLess(u, u2)
        self.assertLess(u2, s5)
        self.assertFalse((self.etat / "documents" / "upgrade.unlock").exists())
        fiche = self.registre()
        self.assertEqual(
            (fiche["version"], fiche["commit"]), ("24.0.1", NOUVEAU)
        )

    def test_modified_core_files_stop_before_anything(self):
        self.sys.run_original = self.sys.run

        def run(argv, env=None, stdin_path=None):
            if "status" in argv:
                self.sys.appels.append(list(argv))
                return 0, " M htdocs/core/lib/functions.lib.php\n"
            return self.sys.run_original(argv, env, stdin_path)

        self.sys.run = run
        code, _s, _r = self.monter()
        self.assertEqual(code, 1)
        self.assertFalse([c for c in self.cmds() if "checkout --detach" in c])

    def test_a_silent_step5_rolls_back(self):
        # step5 sort 0 sans rien faire quand la base est tombée.
        self.sys.apres_step5 = None
        code, sortie, restaure = self.monter()
        self.assertEqual(code, 1)
        self.assertIn(
            f"git -C {self.checkout} checkout --detach {ANCIEN}", self.cmds()
        )
        restaure.assert_called_once()
        self.assertEqual(restaure.call_args[0][2], self.sauvegarde)
        self.assertEqual(self.registre()["version"], "23.0.4")

    def test_a_failing_script_stops_the_rest(self):
        self.sys.echec.add("upgrade2.php")
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        self.assertFalse([c for c in self.cmds() if "step5.php" in c])
        restaure.assert_called_once()


class TestProduction(Banc):
    CODE = "/opt/erplibre-dolibarr/erp"
    DATA = "/var/lib/erplibre-dolibarr/erp/documents"

    def setUp(self):
        super().setUp()
        self.entree.update(
            mode="prod",
            user="dolibarr_erp",
            code_root=self.CODE,
            data_root=self.DATA,
            state_dir="/var/lib/erplibre-dolibarr/erp",
            cron_timer="erplibre-dolibarr-cron-erp.timer",
            domain="erp.example.org",
            tls="local",
            url="https://erp.example.org",
        )
        p = mock.patch.object(
            upgrade,
            "host_facts",
            lambda system: {"family": "apt-get", "php_version": "8.2"},
        )
        p.start()
        self.addCleanup(p.stop)

    def test_stage_swap_then_scripts_as_the_instance_account(self):
        code, sortie, _r = self.monter()
        self.assertEqual(code, 0, sortie)
        cmds = self.cmds()
        joint = " ; ".join(cmds)
        new = f"{self.CODE}.new"
        ordre = [
            f"sudo tar -x -C {new}",
            f"sudo cp -a {self.CODE}/htdocs/conf/conf.php {new}/htdocs/conf/conf.php",
            f"sudo cp -a -n {self.CODE}/htdocs/custom/. {new}/htdocs/custom/",
            f"sudo cp -a {self.CODE}/htdocs/install.lock {new}/htdocs/install.lock",
            "sudo systemctl stop erplibre-dolibarr-cron-erp.timer",
            f"sudo mv {self.CODE} {self.CODE}.prev",
            f"sudo mv {new} {self.CODE}",
            f"sudo -u dolibarr_erp touch {self.DATA}/upgrade.unlock",
            "php upgrade.php 23.0.4 24.0.1",
            "php step5.php 23.0.4 24.0.1",
            f"sudo rm -f {self.DATA}/upgrade.unlock {self.CODE}/htdocs/upgrade.unlock",
            "sudo systemctl reload-or-restart php8.2-fpm.service",
            "sudo systemctl start erplibre-dolibarr-cron-erp.timer",
        ]
        positions = [joint.index(x) for x in ordre]
        self.assertEqual(positions, sorted(positions))
        script = next(c for c in cmds if "php upgrade.php" in c)
        self.assertTrue(script.startswith("sudo -u dolibarr_erp sh -c"))
        self.assertIn(f"cd {self.CODE}/htdocs/install", script)
        self.assertEqual(self.registre()["version"], "24.0.1")

    def test_a_failure_after_the_swap_puts_the_old_code_back(self):
        self.sys.echec.add("upgrade2.php")
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        cmds = self.cmds()
        self.assertIn(f"sudo mv {self.CODE} {self.CODE}.failed", cmds)
        self.assertIn(f"sudo mv {self.CODE}.prev {self.CODE}", cmds)
        restaure.assert_called_once()
        self.assertEqual(self.registre()["version"], "23.0.4")

    def test_a_failure_before_the_swap_touches_nothing_live(self):
        self.sys.echec.add("tar -x")
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        cmds = self.cmds()
        self.assertFalse(
            [c for c in cmds if c.startswith(f"sudo mv {self.CODE} ")]
        )
        self.assertFalse([c for c in cmds if "systemctl stop" in c])
        restaure.assert_not_called()

    def test_a_failure_between_the_timer_and_the_swap_restarts_the_timer(self):
        self.sys.echec.add(f"mv {self.CODE} {self.CODE}.prev")
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        cmds = self.cmds()
        arret = cmds.index(
            "sudo systemctl stop erplibre-dolibarr-cron-erp.timer"
        )
        self.assertIn(
            "sudo systemctl start erplibre-dolibarr-cron-erp.timer",
            cmds[arret:],
        )
        restaure.assert_not_called()

    def test_a_site_still_serving_the_old_version_rolls_back(self):
        # PHP-FPM gardé sur l'ancien code (opcache, pool non rechargé).
        self.sys.page = "<title>Login @ 23.0.4</title>"
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        restaure.assert_called_once()

    def test_the_database_is_read_through_sudo(self):
        self.monter()
        requete = next(
            c for c in self.cmds() if "MAIN_VERSION_LAST_UPGRADE" in c
        )
        self.assertTrue(requete.startswith("sudo mariadb -N -D dolibarr_erp"))


class TestConteneur(Banc):
    ANCIENNE = "docker.io/dolibarr/dolibarr:23.0.4"

    def setUp(self):
        super().setUp()
        (self.etat / "secrets").mkdir()
        self.noms = [
            f"erplibre-dolibarr-erp-{r}" for r in ("db", "web", "cron")
        ]
        self.entree = {
            "mode": "dev",
            "runtime": "container",
            "engine": "podman",
            "db": "mariadb",
            "containers": self.noms,
            "custom_dir": str(self.etat / "custom"),
            "state_dir": str(self.etat),
            "port": 8081,
            "url": "http://127.0.0.1:8081",
            "admin_login": "admin",
            "image": self.ANCIENNE,
            "version": "23.0.4",
        }
        self.sys.page = "<title>Login @ 24.0.0</title>"
        self.sys.base = {"MAIN_VERSION_LAST_INSTALL": "23.0.4"}
        self.sys.apres_step5 = None
        # L'entrée de l'image migre la base quand le site repart.
        origine = self.sys.run

        def run(argv, env=None, stdin_path=None):
            if (
                argv[:2] == ["podman", "run"]
                and "erplibre-dolibarr-erp-web" in argv
            ):
                self.sys.base["MAIN_VERSION_LAST_UPGRADE"] = "24.0.0"
            return origine(argv, env, stdin_path)

        self.sys.run = run

    def test_the_site_is_recreated_on_the_new_image_without_the_lock(self):
        code, sortie, _r = self.monter()
        self.assertEqual(code, 0, sortie)
        cmds = self.cmds()
        nouvelle = self.pin["docker_image"]
        ordre = [
            f"podman pull {nouvelle}",
            "podman rm -f erplibre-dolibarr-erp-cron",
            "podman exec erplibre-dolibarr-erp-web rm -f /var/www/documents/install.lock",
            "podman rm -f erplibre-dolibarr-erp-web",
        ]
        positions = [cmds.index(x) for x in ordre]
        self.assertEqual(positions, sorted(positions))
        relances = [a for a in self.sys.appels if a[:2] == ["podman", "run"]]
        self.assertEqual([a[-1] for a in relances], [nouvelle, nouvelle])
        self.assertIn("erplibre-dolibarr-erp-web", relances[0])
        self.assertIn("erplibre-dolibarr-erp-cron", relances[1])
        self.assertTrue(
            [
                c
                for c in cmds
                if "backup-before-upgrade.sql" in c and " rm " in f" {c} "
            ]
        )
        fiche = self.registre()
        self.assertEqual(
            (fiche["image"], fiche["version"]), (nouvelle, "24.0.0")
        )

    def test_the_same_image_is_up_to_date(self):
        self.entree.update(image=self.pin["docker_image"], version="24.0.0")
        code, _s, _r = self.monter()
        self.assertEqual(code, 0)
        self.assertEqual(self.sys.appels, [])

    def test_more_than_one_major_is_refused(self):
        # L'entrée de l'image ne migre qu'un saut majeur.
        self.entree["version"] = "22.0.5"
        self.sys.base = {"MAIN_VERSION_LAST_INSTALL": "22.0.5"}
        code, _s, _r = self.monter()
        self.assertEqual(code, 1)
        self.assertFalse([c for c in self.cmds() if "pull" in c])

    def test_a_site_that_never_serves_the_new_version_rolls_back(self):
        self.sys.page = "<title>Login @ 23.0.4</title>"
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        restaure.assert_called_once()
        self.assertEqual(self.registre()["image"], self.ANCIENNE)
        # La restauration recrée site et tâches : rien de plus ici.
        anciennes = [
            a
            for a in self.sys.appels
            if a[:2] == ["podman", "run"] and a[-1] == self.ANCIENNE
        ]
        self.assertEqual(anciennes, [])

    def test_a_failure_after_the_lock_went_puts_it_back(self):
        self.sys.echec.add("rm -f erplibre-dolibarr-erp-web")
        code, _s, _r = self.monter()
        self.assertEqual(code, 1)
        self.assertIn(
            "podman exec -u www-data erplibre-dolibarr-erp-web touch"
            " /var/www/documents/install.lock",
            self.cmds(),
        )

    def test_a_failure_before_the_site_is_recreated_restores_cron_and_lock(
        self,
    ):
        self.sys.echec.add("rm -f /var/www/documents/install.lock")
        code, _s, restaure = self.monter()
        self.assertEqual(code, 1)
        restaure.assert_not_called()
        relance = [a for a in self.sys.appels if a[:2] == ["podman", "run"]]
        self.assertEqual(len(relance), 1)
        self.assertIn("erplibre-dolibarr-erp-cron", relance[0])
        self.assertEqual(relance[0][-1], self.ANCIENNE)


if __name__ == "__main__":
    unittest.main()
