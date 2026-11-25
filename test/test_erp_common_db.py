#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le serveur de base commun aux installateurs d'ERP (script/erp_common).

Ce qui se garde :
- le nom de base et de compte porte le nom de l'ERP reçu, aucun autre :
  chaque test qui en dépend tourne pour deux noms ;
- le compte MariaDB est local, jamais « @'%' », et la base reçoit le jeu
  de caractères demandé ;
- le SQL est idempotent : il crée, ou réaligne le mot de passe ;
- l'initialisation du serveur ne vise que les familles qui en ont besoin,
  seulement quand la sonde constate l'absence des données, et jamais en
  essai à blanc ;
- les lignes pg_hba.conf passent par mot de passe, en IPv4 comme en IPv6,
  sur les seules familles qui initialisent en « ident ».
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import db  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")

MARIADB_INIT = [
    "sudo",
    "mariadb-install-db",
    "--user=mysql",
    "--basedir=/usr",
    "--datadir=/var/lib/mysql",
]
ARCH_INITDB = [
    "sudo",
    "-u",
    "postgres",
    "initdb",
    "--locale=C.UTF-8",
    "--encoding=UTF8",
    "--auth-local=peer",
    "--auth-host=scram-sha-256",
    "-D",
    "/var/lib/postgres/data",
]
RPM_INITDB = ["sudo", "postgresql-setup", "--initdb"]


class SondeRunner:
    """Runner réduit aux sondes : `test -e` répond selon `presents`.

    En essai à blanc, une sonde sous sudo rend None, comme le vrai Runner.
    """

    def __init__(self, presents=(), dry_run=False):
        self.presents = set(presents)
        self.dry_run = dry_run
        self.sondes = []

    def probe(self, argv, cwd=None):
        self.sondes.append(list(argv))
        if self.dry_run and argv[0] == "sudo":
            return None
        if argv[:3] == ["sudo", "test", "-e"]:
            return (0, "") if argv[3] in self.presents else (1, "")
        return None


class TestNoms(unittest.TestCase):
    def test_the_database_name_carries_the_erp_received(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                self.assertEqual(db.db_name(erp, "erp"), f"{erp}_erp")

    def test_the_unit_follows_the_database(self):
        self.assertEqual(db.db_unit("mariadb"), "mariadb")
        self.assertEqual(db.db_unit("postgresql"), "postgresql")


class TestSql(unittest.TestCase):
    def test_mariadb_account_is_local_and_charset_explicit(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                nom = db.db_name(erp, "erp")
                sql = db.mariadb_sql(
                    nom, nom, "Pw1", "utf8", "utf8_unicode_ci"
                )
                self.assertIn(
                    "CHARACTER SET utf8 COLLATE utf8_unicode_ci", sql
                )
                self.assertIn(f"'{nom}'@'localhost'", sql)
                self.assertNotIn("'%'", sql)

    def test_mariadb_charset_is_the_one_received(self):
        sql = db.mariadb_sql("a", "a", "Pw1", "utf8mb4", "utf8mb4_unicode_ci")
        self.assertIn("CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", sql)

    def test_mariadb_sql_is_idempotent(self):
        sql = db.mariadb_sql("acme_erp", "acme_erp", "Pw1", "c", "k")
        self.assertIn("CREATE DATABASE IF NOT EXISTS `acme_erp`", sql)
        self.assertIn("CREATE USER IF NOT EXISTS 'acme_erp'@'localhost'", sql)
        self.assertIn(
            "ALTER USER 'acme_erp'@'localhost' IDENTIFIED BY 'Pw1'", sql
        )
        self.assertIn("ON `acme_erp`.* TO 'acme_erp'@'localhost'", sql)

    def test_postgresql_role_is_created_or_its_password_reset(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                nom = db.db_name(erp, "erp")
                sql = db.postgresql_role_sql(nom, "Pw1")
                self.assertIn(f"ALTER ROLE {nom} LOGIN PASSWORD 'Pw1'", sql)
                self.assertIn(f"CREATE ROLE {nom} LOGIN PASSWORD 'Pw1'", sql)
                self.assertIn(f"rolname = '{nom}'", sql)


class TestInitialisation(unittest.TestCase):
    def test_arch_mariadb_is_initialised_when_its_data_is_absent(self):
        runner = SondeRunner()
        self.assertEqual(
            db.db_init_commands("pacman", "mariadb", runner), [MARIADB_INIT]
        )
        self.assertEqual(
            runner.sondes, [["sudo", "test", "-e", "/var/lib/mysql/mysql"]]
        )

    def test_arch_postgresql_gets_initdb_when_its_data_is_absent(self):
        runner = SondeRunner()
        self.assertEqual(
            db.db_init_commands("pacman", "postgresql", runner), [ARCH_INITDB]
        )

    def test_rpm_postgresql_gets_initdb_when_its_data_is_absent(self):
        runner = SondeRunner()
        self.assertEqual(
            db.db_init_commands("dnf", "postgresql", runner), [RPM_INITDB]
        )

    def test_an_initialised_server_is_left_alone(self):
        cas = (
            ("pacman", "mariadb", "/var/lib/mysql/mysql"),
            ("pacman", "postgresql", "/var/lib/postgres/data/PG_VERSION"),
            ("dnf", "postgresql", "/var/lib/pgsql/data/PG_VERSION"),
        )
        for family, base, chemin in cas:
            with self.subTest(family=family, db=base):
                runner = SondeRunner(presents={chemin})
                self.assertEqual(db.db_init_commands(family, base, runner), [])

    def test_families_that_initialise_alone_get_nothing_nor_probe(self):
        cas = (
            ("apt-get", "mariadb"),
            ("apt-get", "postgresql"),
            ("dnf", "mariadb"),
            ("zypper", "mariadb"),
            ("zypper", "postgresql"),
        )
        for family, base in cas:
            with self.subTest(family=family, db=base):
                runner = SondeRunner()
                self.assertEqual(db.db_init_commands(family, base, runner), [])
                self.assertEqual(runner.sondes, [])

    def test_a_dry_run_initialises_nothing(self):
        for family, base in (
            ("pacman", "mariadb"),
            ("pacman", "postgresql"),
            ("dnf", "postgresql"),
        ):
            with self.subTest(family=family, db=base):
                runner = SondeRunner(dry_run=True)
                self.assertEqual(db.db_init_commands(family, base, runner), [])


class TestPostgresql(unittest.TestCase):
    def test_psql_runs_as_postgres_and_stops_at_the_first_error(self):
        self.assertEqual(
            db.psql(["-q"]),
            [
                "sudo",
                "-u",
                "postgres",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-q",
            ],
        )

    def test_only_ident_families_need_a_password_line(self):
        for family in ("dnf", "zypper"):
            with self.subTest(family=family):
                self.assertTrue(db.pg_hba_needs_password_line(family))
        for family in ("apt-get", "pacman"):
            with self.subTest(family=family):
                self.assertFalse(db.pg_hba_needs_password_line(family))

    def test_hba_lines_use_a_password_over_ipv4_and_ipv6(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                nom = db.db_name(erp, "erp")
                self.assertEqual(
                    db.pg_hba_lines(nom, nom).splitlines(),
                    [
                        f"host {nom} {nom} 127.0.0.1/32 scram-sha-256",
                        f"host {nom} {nom} ::1/128 scram-sha-256",
                    ],
                )


if __name__ == "__main__":
    unittest.main()
