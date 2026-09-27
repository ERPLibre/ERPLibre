#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les unités systemd des tâches planifiées d'une instance de production.

Dolibarr ne lance pas ses tâches lui-même : scripts/cron/cron_run_jobs.php
doit être appelé de l'extérieur, toutes les 5 minutes, avec la clé CRON_KEY.
Ce qui se garde :
- le service tourne sous le compte de l'instance, jamais root ;
- la clé vient d'un fichier d'environnement, pas du texte de l'unité ;
- le service ne peut écrire que dans les données de l'instance ;
- la minuterie rattrape un passage manqué (machine éteinte).
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import units  # noqa: E402

CODE = "/opt/erplibre-dolibarr/erp"
DATA = "/var/lib/erplibre-dolibarr/erp"
ENV = "/etc/erplibre-dolibarr/erp/cron.env"


class TestNoms(unittest.TestCase):
    def test_unit_names_carry_the_instance(self):
        self.assertEqual(
            units.cron_unit_names("erp"),
            (
                "erplibre-dolibarr-cron-erp.service",
                "erplibre-dolibarr-cron-erp.timer",
            ),
        )


class TestService(unittest.TestCase):
    def setUp(self):
        texte = units.render_cron_service(
            "erp", "dolibarr_erp", CODE, DATA, ENV
        )
        self.lignes = texte.splitlines()

    def test_it_runs_the_upstream_script_as_the_instance(self):
        self.assertIn("User=dolibarr_erp", self.lignes)
        self.assertIn("Group=dolibarr_erp", self.lignes)
        self.assertIn(
            f"ExecStart=/usr/bin/php {CODE}/scripts/cron/cron_run_jobs.php"
            " ${CRON_KEY} firstadmin",
            self.lignes,
        )
        self.assertIn("Type=oneshot", self.lignes)

    def test_the_key_comes_from_the_environment_file(self):
        self.assertIn(f"EnvironmentFile={ENV}", self.lignes)
        self.assertFalse(
            [x for x in self.lignes if x.startswith("Environment=")]
        )

    def test_it_writes_only_to_the_instance_data(self):
        for ligne in (
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "PrivateTmp=yes",
            "NoNewPrivileges=yes",
            f"ReadWritePaths={DATA}",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, self.lignes)


class TestTimer(unittest.TestCase):
    def setUp(self):
        self.lignes = units.render_cron_timer("erp").splitlines()

    def test_every_five_minutes_and_catches_up(self):
        self.assertIn("OnCalendar=*:0/5", self.lignes)
        self.assertIn("Persistent=true", self.lignes)
        self.assertIn("Unit=erplibre-dolibarr-cron-erp.service", self.lignes)
        self.assertIn("WantedBy=timers.target", self.lignes)


class TestEnv(unittest.TestCase):
    def test_the_key_file_holds_only_the_key(self):
        self.assertEqual(
            units.render_cron_env("K3yInvente"), "CRON_KEY=K3yInvente\n"
        )

    def test_a_key_that_would_break_the_file_is_refused(self):
        for mauvais in ("", "a b", "a\nb", "a$b", "a;b"):
            with self.subTest(mauvais=mauvais):
                with self.assertRaises(ValueError):
                    units.render_cron_env(mauvais)


if __name__ == "__main__":
    unittest.main()
