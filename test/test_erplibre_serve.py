#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre-serve : la configuration rendue depuis l'environnement, et la
décision d'initialiser, de migrer, de servir ou de refuser."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.deployment import erplibre_serve as S

ENV = {
    "PGHOST": "sql-invente.exemple.test",
    "PGPORT": "5432",
    "PGDATABASE": "base_inventee",
    "PGUSER": "role_invente",
    "PGPASSWORD": "mdp-invente-pg",
    "PGSSLMODE": "verify-full",
    "ODOO_ADMIN_PASSWD": "mdp-invente-maitre",
}


class LaDecision(unittest.TestCase):
    def test_the_table(self):
        cas = [
            # (base vide, marquée, notée, code) -> action
            ((True, False, "", "a1"), S.INITIALISER),
            ((True, True, "a1", "a1"), S.REFUSER),
            ((True, True, "", ""), S.REFUSER),
            ((False, True, "a1", "b2"), S.MIGRER),
            ((False, True, "a1", "a1"), S.SERVIR),
            ((False, False, "", "a1"), S.SERVIR),
            ((False, True, "a1", ""), S.SERVIR),
            ((False, True, "", "a1"), S.SERVIR),
        ]
        for entree, attendu in cas:
            with self.subTest(entree=entree):
                self.assertEqual(attendu, S.decider(*entree)[0])

    def test_a_refusal_says_why(self):
        self.assertIn("restauration", S.decider(True, True, "", "")[1])


class LaConfiguration(unittest.TestCase):
    def lu(self, env=ENV):
        import configparser

        texte = S.rendre_conf(env, 20123, "/etat/filestore", "/a,/b")
        lecteur = configparser.ConfigParser(interpolation=None)
        lecteur.read_string(texte)
        return texte, dict(lecteur["options"])

    def test_one_database_closed_manager_tls_from_libpq(self):
        _t, o = self.lu()
        self.assertEqual("base_inventee", o["db_name"])
        self.assertEqual("^base_inventee$", o["dbfilter"])
        self.assertEqual("False", o["list_db"])
        self.assertEqual("verify-full", o["db_sslmode"])
        self.assertEqual("127.0.0.1", o["http_interface"])
        self.assertEqual("20123", o["http_port"])
        self.assertEqual("True", o["proxy_mode"])
        self.assertEqual("0", o["workers"])
        self.assertEqual("/a,/b", o["addons_path"])
        self.assertEqual("/etat/filestore", o["data_dir"])

    def test_the_database_password_never_enters_the_file(self):
        texte, o = self.lu()
        self.assertNotIn(ENV["PGPASSWORD"], texte)
        self.assertEqual("False", o["db_password"])
        self.assertEqual(ENV["ODOO_ADMIN_PASSWD"], o["admin_passwd"])

    def test_a_local_socket_keeps_odoo_defaults(self):
        env = {
            k: v
            for k, v in ENV.items()
            if k not in ("PGHOST", "PGPORT", "PGSSLMODE")
        }
        _t, o = self.lu(env)
        self.assertEqual("False", o["db_host"])
        self.assertEqual("prefer", o["db_sslmode"])

    def test_the_addons_path_comes_from_erplibre_s_config(self):
        texte = "[options]\naddons_path = /x/addons,/y\nadmin_passwd = a\n"
        self.assertEqual("/x/addons,/y", S.addons_path_de(texte))
        self.assertEqual("", S.addons_path_de("pas une conf"))

    def test_required_variables(self):
        self.assertEqual([], S.manques(ENV))
        self.assertEqual(
            ["ODOO_ADMIN_PASSWD"],
            S.manques(
                {k: v for k, v in ENV.items() if k != "ODOO_ADMIN_PASSWD"}
            ),
        )


class LesVersions(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_the_installed_files_win(self):
        (self.d / ".erplibre-version").write_text("odoo18.0_python3.12.16\n")
        (self.d / ".odoo-version").write_text("18.0\n")
        self.assertEqual(
            S.Versions("odoo18.0_python3.12.16", "18.0"), S.versions(self.d)
        )

    def test_otherwise_the_default_pair_of_the_registry(self):
        (self.d / "conf").mkdir()
        (self.d / S.CONF_VERSIONS).write_text(
            json.dumps(
                {
                    "odoo17.0_python3.10.18": {"odoo_version": "17.0"},
                    "odoo18.0_python3.12.16": {
                        "default": True,
                        "odoo_version": "18.0",
                    },
                }
            )
        )
        self.assertEqual(
            S.Versions("odoo18.0_python3.12.16", "18.0"), S.versions(self.d)
        )

    def test_the_repository_s_own_registry_has_a_default(self):
        racine = Path(__file__).resolve().parents[1]
        v = S.versions_du_registre(racine)
        self.assertTrue(v.couple.startswith(f"odoo{v.odoo}_python"))

    def test_nothing_readable_is_none(self):
        self.assertIsNone(S.versions(self.d))

    def test_paths_follow_the_versions(self):
        python, odoo_bin = S.chemins(
            Path("/r"), S.Versions("odoo18.0_python3.12.16", "18.0")
        )
        self.assertEqual(
            Path("/r/.venv.odoo18.0_python3.12.16/bin/python"), python
        )
        self.assertEqual(Path("/r/odoo18.0/odoo/odoo-bin"), odoo_bin)


class LeDemarrage(unittest.TestCase):
    """L'orchestration, avec un faux exécuteur et un faux `exec`."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.racine = self.d / "erplibre"
        v = S.Versions("odoo18.0_python3.12.16", "18.0")
        python, odoo_bin = S.chemins(self.racine, v)
        for f in (python, odoo_bin):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("")
        (self.racine / ".erplibre-version").write_text(v.couple)
        (self.racine / ".odoo-version").write_text(v.odoo)
        (self.racine / "PROVENANCE.lock").write_text("v1\n")
        (self.racine / "config.conf").write_text(
            "[options]\naddons_path = /x\n"
        )
        self.etat = self.d / "etat"

    def lance(self, tables="0", init_code=0):
        joues, remplace = [], []

        def executer(argv, env=None, capture_output=False, text=False):
            joues.append(argv)
            if "-c" in argv and argv[argv.index("-c") + 1] == S.SONDE_BASE:
                return subprocess.CompletedProcess(argv, 0, tables + "\n", "")
            return subprocess.CompletedProcess(argv, init_code, "", "")

        code = S.principal(
            [
                "--port",
                "20123",
                "--etat",
                str(self.etat),
                "--racine",
                str(self.racine),
            ],
            env=dict(ENV),
            executer=executer,
            remplacer=lambda *a: remplace.append(a),
        )
        return code, joues, remplace

    def test_an_empty_base_is_initialised_then_served(self):
        code, joues, remplace = self.lance(tables="0")
        self.assertEqual(0, code)
        self.assertIn(
            ["-i", ",".join(S.PROFIL_MINIMAL)], [j[-3:-1] for j in joues]
        )
        self.assertTrue((self.etat / S.MARQUE_INITIALISEE).exists())
        self.assertEqual(
            "v1", (self.etat / S.VERSION_NOTEE).read_text().strip()
        )
        self.assertEqual(1, len(remplace))
        self.assertEqual(
            0o600, (self.etat / "odoo.conf").stat().st_mode & 0o777
        )

    def test_an_empty_base_with_a_marker_is_refused_and_nothing_runs(self):
        self.etat.mkdir()
        (self.etat / S.MARQUE_INITIALISEE).touch()
        code, joues, remplace = self.lance(tables="0")
        self.assertEqual(4, code)
        self.assertEqual([], remplace)
        self.assertFalse(any("--stop-after-init" in j for j in joues))

    def test_a_new_code_migrates(self):
        self.etat.mkdir()
        (self.etat / S.MARQUE_INITIALISEE).touch()
        (self.etat / S.VERSION_NOTEE).write_text("v0\n")
        code, joues, remplace = self.lance(tables="1")
        self.assertEqual(0, code)
        self.assertTrue(any(j[-3:-1] == ["-u", "all"] for j in joues))
        self.assertEqual(
            "v1", (self.etat / S.VERSION_NOTEE).read_text().strip()
        )

    def test_a_failed_initialisation_does_not_mark_nor_serve(self):
        code, _j, remplace = self.lance(tables="0", init_code=1)
        self.assertNotEqual(0, code)
        self.assertFalse((self.etat / S.MARQUE_INITIALISEE).exists())
        self.assertEqual([], remplace)

    def test_a_silent_base_refuses(self):
        code, _j, remplace = self.lance(tables="")
        self.assertEqual(3, code)
        self.assertEqual([], remplace)


class LaVersionDuCode(unittest.TestCase):
    def test_a_bundle_s_provenance_wins_over_its_own_git(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / ".git").mkdir()
        (d / "PROVENANCE.lock").write_text("odoo18.0_python3.12.16-abc\n")
        joues = []
        self.assertEqual(
            "odoo18.0_python3.12.16-abc",
            S.version_du_code(d, lambda argv, **_k: joues.append(argv)),
        )
        self.assertEqual([], joues)

    def test_without_provenance_the_checkout_s_commit_is_read(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / ".git").mkdir()
        self.assertEqual(
            "c0ffee",
            S.version_du_code(
                d,
                lambda argv, **_k: subprocess.CompletedProcess(
                    argv, 0, "c0ffee\n", ""
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
