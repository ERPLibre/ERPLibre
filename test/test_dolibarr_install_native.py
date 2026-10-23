#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur natif de Dolibarr, sur un système simulé.

Rien n'est installé : un Runner factice répond aux sondes (paquets
présents, service actif, base installée…) et enregistre ce qui aurait été
lancé. Les fichiers qu'il écrit sans sudo vont dans une racine jetable ;
ceux qu'il écrirait sous sudo sont seulement notés.

Ce qui se garde :
- aucun secret sur argv, jamais ;
- install.forced.php, qui porte les mots de passe, disparaît même quand
  l'installation échoue ;
- un checkout qui sert déjà une instance n'est pas réécrit ;
- chaque étape constate avant d'agir : relancer ne refait pas ce qui est
  fait, et garde le même mot de passe de base ;
- les particularités mesurées des familles (initdb, pg_hba, extensions
  d'Arch) sont appliquées là, et seulement là.
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

from script.dolibarr import install_native  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"

FAITS = {
    "system": "Linux",
    "family": "apt-get",
    "is_nixos": False,
    "has_systemd": True,
}


class FauxRunner:
    """Runner simulé. `repondre(argv)` rend (code, sortie) ou None."""

    def __init__(self, repondre, dry_run=False):
        self.repondre = repondre
        self.dry_run = dry_run
        self.lances = []  # (argv, stdin)
        self.sondes = []
        self.ecrits_sudo = {}  # chemin -> texte
        self.sortie = []

    def out(self, texte):
        self.sortie.append(texte)

    def run(self, argv, input=None, cwd=None, env=None):
        self.lances.append((list(argv), input))
        if self.dry_run:
            return 0, ""
        return self.repondre(list(argv)) or (0, "")

    def probe(self, argv, cwd=None):
        self.sondes.append(list(argv))
        if self.dry_run and argv[0] == "sudo":
            return None
        return self.repondre(list(argv))

    def write(self, path, text, mode=0o600, sudo=False):
        if self.dry_run:
            return
        if sudo:
            self.ecrits_sudo[path] = text
            return
        Path(path).write_text(text)
        os.chmod(path, mode)


class Systeme:
    """Un système Debian simulé, que chaque test ajuste."""

    def __init__(self, racine):
        self.racine = racine
        self.paquets_presents = set()
        self.service_actif = False
        self.version_installee = None
        self.echec = {}  # nom d'étape php -> (code, sortie)
        self.php = "8.3"
        self.extensions = set(
            install_native.REQUIRED_EXTENSIONS + ("mysqli", "pgsql")
        )
        self.hba = "local all all peer\nhost all all 127.0.0.1/32 ident\n"
        self.pg_db_existe = False
        self.head = COMMIT
        self.marqueur = "ERPLIBRE_CHECK 24.0.1 24.0.1"

    def repondre(self, argv):
        joint = " ".join(argv)
        if argv[0] == "dpkg-query":
            ok = argv[-1] in self.paquets_presents
            return (0, "install ok installed") if ok else (1, "")
        if argv[:2] == ["pacman", "-Q"] or argv[:2] == ["rpm", "-q"]:
            return (0, "") if argv[-1] in self.paquets_presents else (1, "")
        if argv[:2] == ["systemctl", "is-active"]:
            return (0, "") if self.service_actif else (3, "")
        if argv[:2] == ["sudo", "test"]:
            return (1, "")  # rien d'initialisé
        if argv[0] == "php" and argv[1] == "-r" and "PHP_MAJOR" in argv[2]:
            return 0, self.php
        if argv == ["php", "-m"]:
            return 0, "\n".join(sorted(self.extensions))
        if argv[0] == "php" and argv[1].startswith("step"):
            if argv[1] in self.echec:
                return self.echec[argv[1]]
            if argv[1] == "step1.php":
                conf = Path(argv[4], "conf", "conf.php")
                conf.write_text(
                    "<?php\n$dolibarr_main_db_type='mysqli';\n"
                    "$dolibarr_main_db_type='pgsql';\n"
                )
            if argv[1] == "step5.php":
                self.version_installee = "24.0.1"
                Path(self.data_root, "install.lock").write_text("")
            return 0, f"{argv[1]} ok"
        if argv[0] == "php" and argv[1] == "-r":
            return 0, self.marqueur
        if "MAIN_VERSION_LAST_INSTALL" in joint:
            if self.version_installee:
                return 0, self.version_installee
            return 1, "ERROR 1146: Table doesn't exist"
        if "pg_database" in joint:
            return (0, "1") if self.pg_db_existe else (0, "")
        if "SHOW hba_file" in joint:
            return 0, "/var/lib/pgsql/data/pg_hba.conf"
        if argv[:2] == ["sudo", "cat"]:
            return 0, self.hba
        if argv[:3] == ["git", "-C", str(self.checkout)]:
            return 0, self.head
        return None


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name, "erplibre")
        (self.racine / "conf").mkdir(parents=True)
        (self.racine / "manifest").mkdir()
        (self.racine / "conf" / "supported_version_dolibarr.json").write_text(
            json.dumps(
                {
                    "version": "24.0.1",
                    "branch": "24.0",
                    "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
                    "mariadb_image": "docker.io/library/mariadb:11.4",
                    "php_min": "7.2",
                    "php_max": "8.5",
                }
            )
        )
        (self.racine / "manifest" / "git_manifest_dolibarr.xml").write_text(
            '<manifest><project name="dolibarr.git" path="dolibarr/dolibarr"'
            f' remote="Dolibarr" revision="{COMMIT}" upstream="24.0"'
            ' groups="dolibarr" /></manifest>'
        )
        self.htdocs = self.racine / "dolibarr" / "dolibarr" / "htdocs"
        (self.htdocs / "conf").mkdir(parents=True)
        (self.htdocs / "install").mkdir()
        (self.htdocs / "version.inc.php").write_text("<?php\n")
        self.xdg = Path(tmp.name, "xdg")
        patches = [
            mock.patch.object(install_native, "ROOT", str(self.racine)),
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.xdg)}),
            mock.patch.object(install_native, "_remove_install_log"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(install_native.lib_dolibarr.ENV_ADMIN_PASSWORD, None)
        self.sys = Systeme(self.racine)
        self.sys.checkout = self.racine / "dolibarr" / "dolibarr"
        self.sys.data_root = (
            self.xdg / "ERPLibre" / "dolibarr" / "erp" / "documents"
        )
        self.faits = dict(FAITS)

    def installer(self, *extra, db="mariadb", dry_run=False, reponses=()):
        runner = FauxRunner(self.sys.repondre, dry_run=dry_run)
        argv = ["--mode", "dev", "--db", db, "--instance", "erp", *extra]
        suite = iter(reponses)
        with (
            mock.patch("builtins.input", lambda *a: next(suite)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = install_native.main(argv, facts=self.faits, runner=runner)
        return code, runner

    def secrets(self):
        f = self.xdg / "ERPLibre" / "dolibarr" / "erp" / "secrets.env"
        return install_native.read_secrets(str(f))


class TestParcoursComplet(Banc):
    def test_a_full_development_install_succeeds(self):
        code, runner = self.installer("--yes")
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertTrue((self.htdocs / "install.lock").exists())
        registre = json.loads(
            (self.racine / "private/dolibarr/instances.json").read_text()
        )
        self.assertEqual(
            registre["instances"]["erp"]["db_name"], "dolibarr_erp"
        )

    def test_no_secret_ever_reaches_argv(self):
        os.environ[install_native.lib_dolibarr.ENV_ADMIN_PASSWORD] = "adm-TAPE"
        self.addCleanup(
            os.environ.pop,
            install_native.lib_dolibarr.ENV_ADMIN_PASSWORD,
            None,
        )
        code, runner = self.installer("--yes")
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        s = self.secrets()
        for secret in (s["DB_PASSWORD"], s["ADMIN_PASSWORD"]):
            for argv, _stdin in runner.lances:
                self.assertFalse(any(secret in a for a in argv), argv)
            self.assertFalse(any(secret in x for x in runner.sortie))
        self.assertEqual(s["ADMIN_PASSWORD"], "adm-TAPE")
        # Le mot de passe de base passe par stdin, dans le SQL.
        sql = [
            stdin
            for argv, stdin in runner.lances
            if argv == ["sudo", "mariadb"]
        ]
        self.assertIn(s["DB_PASSWORD"], sql[0])

    def test_the_secrets_file_is_private(self):
        self.installer("--yes")
        f = self.xdg / "ERPLibre" / "dolibarr" / "erp" / "secrets.env"
        self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_generated_secrets_avoid_what_dolibarr_rewrites(self):
        self.installer("--yes")
        for valeur in self.secrets().values():
            self.assertRegex(valeur, r"^[A-Za-z0-9]+$")


class TestInstallForced(Banc):
    def test_it_is_gone_after_a_success(self):
        self.installer("--yes")
        self.assertFalse(
            (self.htdocs / "install" / "install.forced.php").exists()
        )

    def test_it_is_gone_after_a_failure(self):
        self.sys.echec["step2.php"] = (1, "SQL error")
        code, runner = self.installer("--yes")
        self.assertEqual(code, 1)
        self.assertFalse(
            (self.htdocs / "install" / "install.forced.php").exists()
        )
        self.assertTrue(any("step2.php" in x for x in runner.sortie))

    def test_a_silent_failure_is_caught_by_the_database(self):
        # step5 rend 0 même quand l'administrateur n'est pas créé : c'est la
        # base, pas le code de sortie, qui juge.
        self.sys.echec["step5.php"] = (0, "setupnotcomplete")
        code, _runner = self.installer("--yes")
        self.assertEqual(code, 1)


class TestUnCheckoutUneInstance(Banc):
    def test_a_configured_checkout_is_not_overwritten(self):
        conf = self.htdocs / "conf" / "conf.php"
        conf.write_text("<?php $dolibarr_main_db_name='autre';\n")
        code, runner = self.installer("--yes")
        self.assertEqual(code, 1)
        self.assertEqual(
            conf.read_text(), "<?php $dolibarr_main_db_name='autre';\n"
        )
        self.assertFalse(
            [a for a, _ in runner.lances if a[:2] == ["php", "step1.php"]]
        )


class TestRejouer(Banc):
    def test_an_installed_database_is_not_installed_again(self):
        self.sys.version_installee = "24.0.1"
        (self.htdocs / "conf" / "conf.php").write_text(
            "<?php $dolibarr_main_db_type='mysqli';\n"
        )
        code, runner = self.installer("--yes")
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertFalse([a for a, _ in runner.lances if "step1.php" in a])

    def test_a_second_run_keeps_the_database_password(self):
        dossier = self.xdg / "ERPLibre" / "dolibarr" / "erp"
        dossier.mkdir(parents=True)
        (dossier / "secrets.env").write_text("DB_PASSWORD=Deja1Genere\n")
        _code, runner = self.installer("--yes")
        sql = [s for a, s in runner.lances if a == ["sudo", "mariadb"]][0]
        self.assertIn("IDENTIFIED BY 'Deja1Genere'", sql)

    def test_present_packages_are_not_installed_again(self):
        self.sys.paquets_presents = set(
            install_native.packages.packages_for("apt-get", "mariadb")
        )
        _code, runner = self.installer("--yes")
        self.assertFalse([a for a, _ in runner.lances if "apt-get" in a])

    def test_an_active_database_server_is_left_alone(self):
        self.sys.service_actif = True
        _code, runner = self.installer("--yes")
        self.assertFalse([a for a, _ in runner.lances if "systemctl" in a])


class TestPaquets(Banc):
    def test_missing_packages_are_refreshed_then_installed(self):
        _code, runner = self.installer("--yes")
        lances = [a for a, _ in runner.lances]
        i = lances.index(["sudo", "apt-get", "update"])
        self.assertEqual(
            lances[i + 1][:4], ["sudo", "apt-get", "install", "-y"]
        )

    def test_refusing_the_packages_stops_before_anything(self):
        code, runner = self.installer(reponses=["n"])
        self.assertEqual(code, 1)
        self.assertFalse([a for a, _ in runner.lances if "apt-get" in a])

    def test_arch_turns_extensions_on_through_sudo(self):
        self.faits["family"] = "pacman"
        _code, runner = self.installer("--yes", db="postgresql")
        texte = runner.ecrits_sudo["/etc/php/conf.d/erplibre-dolibarr.ini"]
        self.assertIn("extension=pgsql", texte)


class TestServeurDeBase(Banc):
    def test_arch_mariadb_is_initialised_before_it_starts(self):
        self.faits["family"] = "pacman"
        _code, runner = self.installer("--yes")
        lances = [a for a, _ in runner.lances]
        i_init = lances.index(
            [
                "sudo",
                "mariadb-install-db",
                "--user=mysql",
                "--basedir=/usr",
                "--datadir=/var/lib/mysql",
            ]
        )
        i_start = lances.index(
            ["sudo", "systemctl", "enable", "--now", "mariadb"]
        )
        self.assertLess(i_init, i_start)

    def test_rpm_postgresql_gets_initdb_and_a_password_line(self):
        self.faits["family"] = "dnf"
        _code, runner = self.installer("--yes", db="postgresql")
        lances = [a for a, _ in runner.lances]
        self.assertIn(["sudo", "postgresql-setup", "--initdb"], lances)
        hba = runner.ecrits_sudo["/var/lib/pgsql/data/pg_hba.conf"]
        premiere = hba.splitlines()[0]
        self.assertEqual(
            premiere,
            "host dolibarr_erp dolibarr_erp 127.0.0.1/32 scram-sha-256",
        )
        # Les lignes ident d'origine restent, APRÈS.
        self.assertIn("host all all 127.0.0.1/32 ident", hba)

    def test_suse_postgresql_gets_the_password_line_too(self):
        # openSUSE initialise au premier démarrage, lui aussi en ident.
        self.faits["family"] = "zypper"
        _code, runner = self.installer("--yes", db="postgresql")
        hba = runner.ecrits_sudo["/var/lib/pgsql/data/pg_hba.conf"]
        self.assertTrue(hba.startswith("host dolibarr_erp dolibarr_erp"))

    def test_debian_postgresql_needs_no_hba_edit(self):
        _code, runner = self.installer("--yes", db="postgresql")
        self.assertFalse(runner.ecrits_sudo)


class TestSql(unittest.TestCase):
    def test_mariadb_account_is_local_and_charset_explicit(self):
        sql = install_native.mariadb_sql("dolibarr_erp", "dolibarr_erp", "Pw1")
        self.assertIn("CHARACTER SET utf8 COLLATE utf8_unicode_ci", sql)
        self.assertIn("'dolibarr_erp'@'localhost'", sql)
        self.assertNotIn("'%'", sql)

    def test_postgresql_role_is_created_or_its_password_reset(self):
        sql = install_native.postgresql_role_sql("dolibarr_erp", "Pw1")
        self.assertIn("ALTER ROLE dolibarr_erp LOGIN PASSWORD 'Pw1'", sql)
        self.assertIn("CREATE ROLE dolibarr_erp LOGIN PASSWORD 'Pw1'", sql)


def sans_saisie():
    """input() qui échoue : un refus doit tomber AVANT toute question."""
    return mock.patch(
        "builtins.input", side_effect=AssertionError("input() appelé")
    )


class TestRefus(Banc):
    def test_production_is_not_offered_yet(self):
        runner = FauxRunner(self.sys.repondre)
        with contextlib.redirect_stdout(io.StringIO()), sans_saisie():
            code = install_native.main(
                ["--mode", "prod", "--db", "mariadb", "--instance", "erp"],
                facts=self.faits,
                runner=runner,
            )
        self.assertEqual(code, 1)
        self.assertFalse(runner.lances)

    def test_an_existing_instance_is_refused(self):
        registre = self.racine / "private" / "dolibarr" / "instances.json"
        registre.parent.mkdir(parents=True)
        registre.write_text(json.dumps({"instances": {"erp": {}}}))
        code, runner = self.installer("--yes")
        self.assertEqual(code, 1)
        self.assertFalse(runner.lances)

    def test_php_out_of_range_stops(self):
        self.sys.php = "8.6"
        code, runner = self.installer("--yes")
        self.assertEqual(code, 1)
        self.assertTrue(any("8.6" in x for x in runner.sortie))

    def test_a_missing_extension_is_named(self):
        self.sys.extensions.discard("openssl")
        code, runner = self.installer("--yes")
        self.assertEqual(code, 1)
        self.assertTrue(any("openssl" in x for x in runner.sortie))

    def test_the_php_check_needs_its_marker(self):
        self.sys.marqueur = "Error: Dolibarr config file content seems wrong"
        code, _runner = self.installer("--yes")
        self.assertEqual(code, 1)

    def test_invalid_names_are_refused_before_anything(self):
        runner = FauxRunner(self.sys.repondre)
        with contextlib.redirect_stdout(io.StringIO()), sans_saisie():
            code = install_native.main(
                ["--mode", "dev", "--db", "mariadb", "--instance", "Bad-Name"],
                facts=self.faits,
                runner=runner,
            )
        self.assertEqual(code, 2)
        self.assertFalse(runner.lances)


class TestEssaiABlanc(Banc):
    def test_dry_run_changes_nothing(self):
        code, runner = self.installer("--dry-run", "--yes", dry_run=True)
        self.assertEqual(code, 0, "\n".join(runner.sortie))
        self.assertFalse((self.racine / "private").exists())
        self.assertFalse((self.htdocs / "conf" / "conf.php").exists())
        self.assertFalse(runner.ecrits_sudo)


if __name__ == "__main__":
    unittest.main()
