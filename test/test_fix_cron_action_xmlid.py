#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'xmlid de l'action serveur d'un cron né avant Odoo 11.

Depuis la 11, ir.cron hérite d'ir.actions.server, et charger un cron
depuis le XML crée « <xmlid>_ir_actions_server ». Un cron né avant n'a
que son propre xmlid ; la 18 cite l'autre dans le menu de stock, et le
saut vers 18 casse sur « External ID not found ». Le correctif 17 → 18
crée l'xmlid manquant, exécuté ici contre un vrai PostgreSQL.
"""

import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(
    REPO, "script", "odoo", "migration", "fix_migration_odoo170_to_odoo180.sql"
)
BASE = "_erplibre_test_cron_action_xmlid"


def psql_disponible():
    try:
        done = subprocess.run(
            ["psql", "-X", "-w", "-l"], capture_output=True, timeout=20
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(psql_disponible(), "pas de PostgreSQL joignable")
class Base(unittest.TestCase):
    """Une base jetable : ir_model_data et ir_cron réduits à l'essentiel."""

    @classmethod
    def setUpClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)
        done = subprocess.run(["createdb", BASE], capture_output=True)
        if done.returncode:
            raise unittest.SkipTest(
                "createdb refusé : " + done.stderr.decode()
            )

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)

    def setUp(self):
        self.sql(
            "DROP TABLE IF EXISTS ir_model_data, ir_cron",
            "CREATE TABLE ir_cron (id serial PRIMARY KEY,"
            " ir_actions_server_id integer)",
            "CREATE TABLE ir_model_data (id serial PRIMARY KEY,"
            " module varchar NOT NULL, name varchar NOT NULL,"
            " model varchar NOT NULL, res_id integer, noupdate boolean,"
            " create_uid integer, write_uid integer,"
            " create_date timestamp, write_date timestamp,"
            " UNIQUE (module, name))",
        )

    def sql(self, *ordres):
        argv = ["psql", "-X", "-w", "-q", "-d", BASE]
        for ordre in ordres:
            argv += ["-c", ordre]
        done = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def lire(self, requete):
        done = subprocess.run(
            ["psql", "-X", "-w", "-q", "-At", "-d", BASE, "-c", requete],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout.strip()

    def appliquer(self):
        done = subprocess.run(
            ["psql", "-X", "-w", "-v", "ON_ERROR_STOP=1", "-d", BASE]
            + ["-f", FIX],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        return done.stdout + done.stderr

    def cron(self, action, nom, avec_parent=False, noupdate=True):
        cid = self.lire(
            f"INSERT INTO ir_cron (ir_actions_server_id) VALUES ({action})"
            " RETURNING id"
        ).splitlines()[0]
        self.sql(
            "INSERT INTO ir_model_data (module, name, model, res_id, noupdate)"
            f" VALUES ('demo', '{nom}', 'ir.cron', {cid}, {noupdate})"
        )
        if avec_parent:
            self.sql(
                "INSERT INTO ir_model_data (module, name, model, res_id)"
                f" VALUES ('demo', '{nom}_ir_actions_server',"
                " 'ir.actions.server', 999)"
            )


class TestLXmlidManquantEstCree(Base):
    def test_il_pointe_sur_l_action_du_cron(self):
        self.cron(41, "tache_ancienne")
        self.appliquer()
        self.assertEqual(
            "ir.actions.server|41|t",
            self.lire(
                "SELECT model, res_id, noupdate FROM ir_model_data"
                " WHERE name = 'tache_ancienne_ir_actions_server'"
            ),
        )

    def test_il_dit_combien(self):
        self.cron(41, "tache_a")
        self.cron(42, "tache_b")
        self.assertIn("2 xmlid", self.appliquer())

    def test_le_rejouer_ne_change_rien(self):
        self.cron(41, "tache_ancienne")
        self.appliquer()
        self.appliquer()
        self.assertEqual(
            "1",
            self.lire(
                "SELECT count(*) FROM ir_model_data"
                " WHERE name = 'tache_ancienne_ir_actions_server'"
            ),
        )


class TestCeQuIlNeTouchePas(Base):
    def test_un_xmlid_present_est_garde_tel_quel(self):
        self.cron(41, "tache_recente", avec_parent=True)
        self.appliquer()
        self.assertEqual(
            "999",
            self.lire(
                "SELECT res_id FROM ir_model_data"
                " WHERE name = 'tache_recente_ir_actions_server'"
            ),
        )

    def test_un_cron_sans_action_est_ignore(self):
        self.cron("NULL", "tache_orpheline")
        self.appliquer()
        self.assertEqual(
            "0",
            self.lire(
                "SELECT count(*) FROM ir_model_data"
                " WHERE name = 'tache_orpheline_ir_actions_server'"
            ),
        )


if __name__ == "__main__":
    unittest.main()
