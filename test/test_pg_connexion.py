#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La connexion d'Odoo rendue à psql (script/database/pg_connexion), et ses
deux appelants : db_restore et lib_analyse doivent rendre le même
environnement pour la même configuration."""

import os
import sys
import tempfile
import unittest
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.analyse import lib_analyse  # noqa: E402
from script.database import db_restore  # noqa: E402
from script.database import pg_connexion as pc  # noqa: E402

CONFIG = (
    "[options]\ndb_host = hote-essai\ndb_port = False\n"
    "db_user = role_essai\ndb_password = mot%de%passe\n"
    "db_sslmode = verify-full\n"
)


class Base(unittest.TestCase):
    def setUp(self):
        # Ni ODOO_RC ni PG* du shell qui lance : ils changeraient le
        # résultat sans que le code ait changé.
        propre = {
            k: v
            for k, v in os.environ.items()
            if k != "ODOO_RC" and not k.startswith("PG")
        }
        env = mock.patch.dict(os.environ, propre, clear=True)
        env.start()
        self.addCleanup(env.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name

    def ecrire(self, nom, contenu=CONFIG):
        chemin = os.path.join(self.tmp, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        return chemin


class TestCheminConfig(Base):
    def test_odoo_rc_wins_over_the_checkout(self):
        self.ecrire("config.conf")
        autre = self.ecrire("autre.conf")
        os.environ["ODOO_RC"] = autre
        self.assertEqual(pc.chemin_config(self.tmp), autre)

    def test_the_checkout_config_without_odoo_rc(self):
        chemin = self.ecrire("config.conf")
        self.assertEqual(pc.chemin_config(self.tmp), chemin)

    def test_the_first_existing_file_is_kept_even_without_options(self):
        # Odoo lit le premier fichier présent : en sauter un sans
        # [options] ferait lire à psql un autre fichier qu'Odoo.
        chemin = self.ecrire("config.conf", "[autre]\nx = 1\n")
        self.assertEqual(pc.chemin_config(self.tmp), chemin)
        self.assertEqual(pc.options(chemin), {})


class TestEnvironnement(Base):
    def test_odoo_options_become_libpq_variables(self):
        env = pc.environnement(self.ecrire("c.conf"), base="a=b")
        self.assertEqual(env["PGHOST"], "hote-essai")
        self.assertEqual(env["PGUSER"], "role_essai")
        self.assertEqual(env["PGPASSWORD"], "mot%de%passe")
        self.assertEqual(env["PGSSLMODE"], "verify-full")
        self.assertEqual(env["PGDATABASE"], "a=b")
        self.assertNotIn("PGPORT", env)

    def test_read_only_bounded_and_without_psqlrc(self):
        env = pc.environnement("/nulle/part.conf", delai_requete=7)
        self.assertIn("default_transaction_read_only=on", env["PGOPTIONS"])
        self.assertIn("statement_timeout=7s", env["PGOPTIONS"])
        self.assertEqual(env["PGCONNECT_TIMEOUT"], "10")
        self.assertEqual(env["PSQLRC"], "")
        self.assertNotIn("PGDATABASE", env)

    def test_overrides_win_and_empty_ones_do_not_count(self):
        env = pc.environnement(
            self.ecrire("c.conf"),
            surcharges={"PGHOST": "127.0.0.1", "PGPORT": ""},
        )
        self.assertEqual(env["PGHOST"], "127.0.0.1")
        self.assertNotIn("PGPORT", env)

    def test_without_a_path_the_config_odoo_reads_is_used(self):
        self.ecrire("config.conf")
        self.assertEqual(
            pc.environnement(racine=self.tmp)["PGHOST"], "hote-essai"
        )


class TestLesDeuxAppelants(Base):
    def test_db_restore_and_lib_analyse_agree(self):
        os.environ["ODOO_RC"] = self.ecrire("c.conf")
        restaure = db_restore.environnement_pg("postgres")
        analyse = lib_analyse.pg_env(timeout=db_restore.PSQL_DELAI)
        analyse["PGDATABASE"] = "postgres"
        self.assertEqual(restaure, analyse)

    def test_lib_analyse_reads_the_repository_config_without_odoo_rc(self):
        with mock.patch.object(lib_analyse, "REPO_ROOT", self.tmp):
            self.ecrire("config.conf")
            self.assertEqual(lib_analyse.pg_env()["PGUSER"], "role_essai")
            self.assertEqual(
                lib_analyse.read_config()["db_host"], "hote-essai"
            )


if __name__ == "__main__":
    unittest.main()
