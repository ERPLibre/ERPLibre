#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le correctif de palier 16 → 17, exécuté contre un vrai PostgreSQL.

Il retire les règles d'automatisation dont l'action serveur porte l'état
`refresh` de muk_web_client_refresh, module d'Odoo 12 qui les laisse en
partant : le script de fin de migration de base_automation en 17 meurt
sur cet état que plus rien ne déclare. Les clés étrangères RESTRICT de
base_automation et d'ir_cron fixent l'ordre des suppressions, et seule
l'exécution le prouve.
"""

import os
import shutil
import subprocess
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SQL = os.path.join(
    RACINE,
    "script",
    "odoo",
    "migration",
    "fix_migration_odoo160_to_odoo170.sql",
)


class TestRefreshMuk(unittest.TestCase):
    BASE = "tmp_fix_160_170_test"

    @classmethod
    def setUpClass(cls):
        if not shutil.which("psql") or not shutil.which("createdb"):
            raise unittest.SkipTest("PostgreSQL absent")
        subprocess.run(
            ["dropdb", "-w", "--if-exists", cls.BASE], capture_output=True
        )
        if subprocess.run(
            ["createdb", "-w", cls.BASE], capture_output=True
        ).returncode:
            raise unittest.SkipTest("createdb impossible")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(
            ["dropdb", "-w", "--if-exists", cls.BASE], capture_output=True
        )

    def sql(self, requete):
        fait = subprocess.run(
            ["psql", "-X", "-w", "-q", "-d", self.BASE, "-tAc", requete],
            capture_output=True,
            text=True,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.strip()

    def appliquer(self):
        fait = subprocess.run(
            ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-d", self.BASE]
            + ["-f", SQL],
            capture_output=True,
            text=True,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)

    def setUp(self):
        self.sql(
            "DROP TABLE IF EXISTS base_automation, ir_cron, ir_act_server"
        )
        self.sql(
            "CREATE TABLE ir_act_server"
            " (id serial PRIMARY KEY, state varchar NOT NULL)"
        )
        for table, colonne in (
            ("base_automation", "action_server_id"),
            ("ir_cron", "ir_actions_server_id"),
        ):
            self.sql(
                f"CREATE TABLE {table} (id serial PRIMARY KEY, {colonne}"
                " integer REFERENCES ir_act_server ON DELETE RESTRICT)"
            )

    def action(self, etat):
        return self.sql(
            f"INSERT INTO ir_act_server (state) VALUES ('{etat}') RETURNING id"
        )

    def test_refresh_rules_go_and_other_rules_stay(self):
        refresh, code = self.action("refresh"), self.action("code")
        self.sql(
            "INSERT INTO base_automation (action_server_id)"
            f" VALUES ({refresh}), ({code})"
        )
        self.appliquer()
        self.assertEqual(
            self.sql("SELECT state FROM ir_act_server ORDER BY id"), "code"
        )
        self.assertEqual(
            self.sql("SELECT action_server_id FROM base_automation"), code
        )

    def test_an_action_a_cron_points_at_stays(self):
        refresh = self.action("refresh")
        self.sql(
            f"INSERT INTO ir_cron (ir_actions_server_id) VALUES ({refresh})"
        )
        self.appliquer()
        self.assertEqual(self.sql("SELECT count(*) FROM ir_act_server"), "1")

    def test_it_can_run_twice(self):
        refresh = self.action("refresh")
        self.sql(
            "INSERT INTO base_automation (action_server_id)"
            f" VALUES ({refresh})"
        )
        self.appliquer()
        self.appliquer()
        self.assertEqual(self.sql("SELECT count(*) FROM ir_act_server"), "0")

    def test_without_base_automation_it_does_nothing_wrong(self):
        self.sql("DROP TABLE base_automation")
        self.action("refresh")
        self.appliquer()
        self.assertEqual(self.sql("SELECT count(*) FROM ir_act_server"), "0")


if __name__ == "__main__":
    unittest.main()
