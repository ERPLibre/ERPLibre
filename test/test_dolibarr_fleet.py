#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le parc d'instances Dolibarr : les lister, en retirer une.

Retirer défait ce que l'installation a posé, selon l'exécution. Ce qui se
garde :
- rien ne s'enlève sans le nom retapé en entier ; l'essai à blanc montre
  chaque étape sans rien toucher ;
- chaque commande est rejouable (IF EXISTS, -f, rm -rf) : un retrait
  interrompu se relance ;
- l'entrée du registre ne part que si tout a réussi ;
- en développement conteneur, custom/ reste : c'est le code du
  développeur, son chemin est dit.
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

from script.dolibarr import fleet  # noqa: E402


class Systeme:
    def __init__(self):
        self.appels = []
        self.echec = set()
        self.pages = {}

    def run(self, argv):
        self.appels.append(list(argv))
        if any(m in " ".join(argv) for m in self.echec):
            return 1, "ERROR"
        return 0, ""

    def engine(self, moteur):
        return {
            "moteur": moteur,
            "sans_sudo": True,
            "avec_sudo": False,
            "rootless": True,
            "docker_host": None,
        }

    def http_get(self, url, host):
        return self.pages.get(url, "ERROR connection refused")


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        self.etat = self.racine / "etat" / "erp"
        (self.etat / "secrets").mkdir(parents=True)
        (self.etat / "custom" / "monmodule").mkdir(parents=True)
        self.checkout = self.racine / "dolibarr"
        (self.checkout / "htdocs" / "conf").mkdir(parents=True)
        (self.checkout / "htdocs" / "conf" / "conf.php").write_text("<?php\n")
        (self.checkout / "htdocs" / "install.lock").write_text("")
        self.sys = Systeme()
        self.instances = {}

    def registre(self):
        chemin = self.racine / "private" / "dolibarr" / "instances.json"
        return json.loads(chemin.read_text())["instances"]

    def ecrire(self):
        chemin = self.racine / "private" / "dolibarr" / "instances.json"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps({"instances": self.instances}))

    def lancer(self, *argv):
        self.ecrire()
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch.object(fleet, "stop_dev", lambda name, root: None),
        ):
            code = fleet.main(
                list(argv), root=str(self.racine), system=self.sys
            )
        return code, sortie.getvalue()

    def cmds(self):
        return [" ".join(a) for a in self.sys.appels]


class TestConteneur(Banc):
    def setUp(self):
        super().setUp()
        self.noms = [
            f"erplibre-dolibarr-erp-{r}" for r in ("db", "web", "cron")
        ]
        self.instances = {
            "erp": {
                "mode": "dev",
                "runtime": "container",
                "engine": "podman",
                "containers": self.noms,
                "custom_dir": str(self.etat / "custom"),
                "state_dir": str(self.etat),
                "url": "http://127.0.0.1:8081",
            }
        }

    def test_nothing_goes_without_the_name_retyped(self):
        for mauvais in ("", "er"):
            with self.subTest(mauvais=mauvais):
                code, _s = self.lancer(
                    "remove", "--instance", "erp", "--confirm", mauvais
                )
                self.assertEqual(code, 2)
        self.assertEqual(self.sys.appels, [])
        self.assertIn("erp", self.registre())

    def test_the_dry_run_shows_every_step_and_touches_nothing(self):
        code, sortie = self.lancer("remove", "--instance", "erp", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.sys.appels, [])
        self.assertIn("podman rm -f", sortie)
        self.assertIn("erplibre-dolibarr-erp-dbdata", sortie)
        self.assertTrue((self.etat / "secrets").exists())
        self.assertIn("erp", self.registre())

    def test_containers_volumes_network_and_state_go_custom_stays(self):
        code, sortie = self.lancer(
            "remove", "--instance", "erp", "--confirm", "erp"
        )
        self.assertEqual(code, 0, sortie)
        cmds = self.cmds()
        self.assertIn("podman rm -f " + " ".join(reversed(self.noms)), cmds)
        self.assertIn(
            "podman volume rm -f erplibre-dolibarr-erp-dbdata"
            " erplibre-dolibarr-erp-documents",
            cmds,
        )
        # Sans -f : Docker ne le connaît que dans ses versions récentes.
        self.assertIn("podman network rm erplibre-dolibarr-erp", cmds)
        self.assertFalse((self.etat / "secrets").exists())
        self.assertTrue((self.etat / "custom" / "monmodule").exists())
        self.assertIn(str(self.etat / "custom"), sortie)
        self.assertNotIn("erp", self.registre())

    def test_production_containers_lose_their_custom_volume_too(self):
        self.instances["erp"].update(mode="prod", custom_dir=None)
        self.lancer("remove", "--instance", "erp", "--confirm", "erp")
        volumes = next(c for c in self.cmds() if "volume rm" in c)
        self.assertIn("erplibre-dolibarr-erp-custom", volumes)

    def test_what_is_already_gone_counts_as_removed(self):
        # Relancer un retrait interrompu : les conteneurs ne sont plus là.
        self.sys.run = lambda argv: (
            self.sys.appels.append(list(argv))
            or (
                (1, "Error: no such container")
                if " rm " in f" {' '.join(argv)} "
                else (0, "")
            )
        )
        code, _s = self.lancer(
            "remove", "--instance", "erp", "--confirm", "erp"
        )
        self.assertEqual(code, 0)
        self.assertNotIn("erp", self.registre())

    def test_a_failed_step_keeps_the_registry_entry(self):
        self.sys.echec.add("volume rm")
        code, _s = self.lancer(
            "remove", "--instance", "erp", "--confirm", "erp"
        )
        self.assertEqual(code, 1)
        self.assertIn("erp", self.registre())


class TestNatifDev(Banc):
    def setUp(self):
        super().setUp()
        self.instances = {
            "erp": {
                "mode": "dev",
                "runtime": "native",
                "db": "mariadb",
                "db_name": "dolibarr_erp",
                "code_root": str(self.checkout),
                "state_dir": str(self.etat),
                "url": "http://127.0.0.1:8080",
            }
        }

    def test_the_database_and_account_go_the_checkout_is_freed(self):
        code, sortie = self.lancer(
            "remove", "--instance", "erp", "--confirm", "erp"
        )
        self.assertEqual(code, 0, sortie)
        sql = next(c for c in self.cmds() if c.startswith("sudo mariadb -e"))
        self.assertIn("DROP DATABASE IF EXISTS dolibarr_erp", sql)
        self.assertIn("DROP USER IF EXISTS 'dolibarr_erp'@'localhost'", sql)
        self.assertFalse(self.etat.exists())
        htdocs = self.checkout / "htdocs"
        self.assertFalse((htdocs / "conf" / "conf.php").exists())
        self.assertFalse((htdocs / "install.lock").exists())

    def test_postgresql_drops_its_database_and_role(self):
        self.instances["erp"]["db"] = "postgresql"
        self.lancer("remove", "--instance", "erp", "--confirm", "erp")
        cmds = self.cmds()
        self.assertIn("sudo -u postgres dropdb --if-exists dolibarr_erp", cmds)
        self.assertIn(
            "sudo -u postgres dropuser --if-exists dolibarr_erp", cmds
        )


class TestProduction(Banc):
    def setUp(self):
        super().setUp()
        self.instances = {
            "erp": {
                "mode": "prod",
                "runtime": "native",
                "db": "mariadb",
                "db_name": "dolibarr_erp",
                "user": "dolibarr_erp",
                "code_root": "/opt/erplibre-dolibarr/erp",
                "state_dir": "/var/lib/erplibre-dolibarr/erp",
                "cron_timer": "erplibre-dolibarr-cron-erp.timer",
                "domain": "erp.example.org",
                "tls": "certbot",
                "url": "https://erp.example.org",
            }
        }
        self.faits = {"family": "apt-get", "php_version": "8.2"}

    def lancer_prod(self):
        with mock.patch.object(fleet, "host_facts", lambda system: self.faits):
            return self.lancer(
                "remove", "--instance", "erp", "--confirm", "erp"
            )

    def test_everything_the_install_laid_down_is_undone(self):
        code, sortie = self.lancer_prod()
        self.assertEqual(code, 0, sortie)
        cmds = self.cmds()
        attendus = [
            "sudo systemctl disable --now erplibre-dolibarr-cron-erp.timer",
            "sudo rm -f /etc/systemd/system/erplibre-dolibarr-cron-erp.service"
            " /etc/systemd/system/erplibre-dolibarr-cron-erp.timer",
            "sudo rm -f /etc/php/8.2/fpm/pool.d/erplibre-dolibarr-erp.conf",
            "sudo systemctl reload-or-restart php8.2-fpm.service",
            "sudo rm -f /etc/nginx/sites-available/erplibre-dolibarr-erp"
            " /etc/nginx/sites-enabled/erplibre-dolibarr-erp",
            "sudo systemctl reload nginx",
            "sudo rm -rf /opt/erplibre-dolibarr/erp",
            "sudo rm -rf /var/lib/erplibre-dolibarr/erp",
            "sudo rm -rf /etc/erplibre-dolibarr/erp",
        ]
        for attendu in attendus:
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, cmds)
        self.assertLess(
            cmds.index(attendus[0]),
            cmds.index("sudo rm -rf /opt/erplibre-dolibarr/erp"),
        )
        compte = [c for c in cmds if c.startswith("sudo userdel")]
        self.assertEqual(compte, ["sudo userdel dolibarr_erp"])
        # certbot garde son certificat : dit, pas supprimé.
        self.assertIn("certbot", sortie)
        self.assertFalse([c for c in cmds if "certbot" in c])


class TestListe(Banc):
    def test_each_instance_with_its_runtime_and_what_it_serves(self):
        self.instances = {
            "aaa": {
                "mode": "dev",
                "runtime": "native",
                "url": "http://127.0.0.1:8080",
            },
            "zzz": {
                "mode": "prod",
                "runtime": "native",
                "url": "https://z.example.org",
                "domain": "z.example.org",
                "tls": "local",
            },
        }
        self.sys.pages["http://127.0.0.1:8080/"] = (
            "<title>Login @ 24.0.1</title>"
        )
        code, sortie = self.lancer("list")
        self.assertEqual(code, 0)
        lignes = [x for x in sortie.splitlines() if x.strip()]
        self.assertIn("aaa", lignes[0])
        self.assertIn("24.0.1", lignes[0])
        self.assertIn("zzz", lignes[1])
        self.assertIn("prod", lignes[1])


if __name__ == "__main__":
    unittest.main()
