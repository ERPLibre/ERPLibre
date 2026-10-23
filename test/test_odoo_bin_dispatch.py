#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""./odoo_bin.sh passe « db », « module » et « theme » au traducteur quand
le cœur de la version active garde l'ancienne commande « db » à drapeaux,
que le module erplibre_odoo_cli_base soit là ou non, et rien d'autre. Sur
un cœur d'OCB sans le module, ces trois commandes sortent en 2.

Banc jetable : une copie de odoo_bin.sh, de lib_odoo_rc.sh et du
traducteur, un venv vide, un odoo/cli/db.py réduit à ce qui distingue les
cœurs, et deux bouchons qui impriment ce qu'ils reçoivent — odoo-bin (argv
en JSON, ODOO_RC, et pour « shell » le thème demandé et la première ligne
de l'entrée standard) et run.sh (argv).
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

RACINE = pathlib.Path(__file__).resolve().parents[1]

BOUCHON_ODOO = """#!/usr/bin/env python3
import json, os, sys
print("ARGV:" + json.dumps(sys.argv[1:]))
print("RC:" + os.environ.get("ODOO_RC", ""))
if sys.argv[1:2] == ["shell"]:
    print("THEME:" + os.environ.get("ERPLIBRE_THEME_APPLY", ""))
    print("STDIN:" + (sys.stdin.read().splitlines() or [""])[0])
"""

BOUCHON_RUN = """#!/usr/bin/env bash
printf 'RUN:'; printf '[%s]' "$@"; printf '\\n'
"""

# Le odoo/cli/db.py de chaque sorte de cœur, réduit à ce qui les distingue :
# celui d'OCB a Db._check_target, l'ancien à drapeaux a --restore_image.
# « absent » : pas de db.py du tout.
DB_PY = {
    "ocb": "class Db:\n    def _check_target(self, target):\n        pass\n",
    "ancien": "class Db:\n    restore_image = '--restore_image'\n",
    "absent": None,
}


class Banc:
    def __init__(self, version, module=False, coeur="ancien"):
        self.dossier = pathlib.Path(tempfile.mkdtemp(prefix="el_dispatch_"))
        d = self.dossier
        (d / "script" / "database").mkdir(parents=True)
        shutil.copy(RACINE / "odoo_bin.sh", d / "odoo_bin.sh")
        shutil.copy(
            RACINE / "script" / "lib_odoo_rc.sh",
            d / "script" / "lib_odoo_rc.sh",
        )
        shutil.copy(
            RACINE / "script" / "database" / "odoo_db_legacy.py",
            d / "script" / "database" / "odoo_db_legacy.py",
        )
        (d / ".erplibre-version").write_text("x\n")
        (d / ".venv.x" / "bin").mkdir(parents=True)
        (d / ".venv.x" / "bin" / "activate").write_text("")
        (d / ".odoo-version").write_text(version + "\n")
        (d / "config.conf").write_text("[options]\n")
        odoo_bin = d / ("odoo" + version) / "odoo" / "odoo-bin"
        odoo_bin.parent.mkdir(parents=True)
        odoo_bin.write_text(BOUCHON_ODOO)
        if DB_PY[coeur] is not None:
            db_py = odoo_bin.parent / "odoo" / "cli" / "db.py"
            db_py.parent.mkdir(parents=True)
            db_py.write_text(DB_PY[coeur])
        (d / "run.sh").write_text(BOUCHON_RUN)
        if module:
            manifeste = (
                d
                / ("odoo" + version)
                / "addons"
                / "ERPLibre_erplibre_addons"
                / "erplibre_odoo_cli_base"
                / "__manifest__.py"
            )
            manifeste.parent.mkdir(parents=True)
            manifeste.write_text("{}\n")
        for script in (d / "odoo_bin.sh", d / "run.sh", odoo_bin):
            script.chmod(0o755)

    def nettoyer(self):
        shutil.rmtree(self.dossier, ignore_errors=True)

    def lancer(self, *argv, env=None):
        milieu = {
            k: v
            for k, v in os.environ.items()
            if k not in ("ODOO_RC", "ERPLIBRE_ODOO_CLI_LEGACY")
        }
        milieu.pop("ODOO_MODE_COVERAGE", None)
        milieu.update(env or {})
        return subprocess.run(
            ["./odoo_bin.sh", *argv],
            cwd=self.dossier,
            capture_output=True,
            text=True,
            timeout=30,
            env=milieu,
        )

    def argv_odoo(self, res):
        return [
            json.loads(ligne[len("ARGV:") :])
            for ligne in res.stdout.splitlines()
            if ligne.startswith("ARGV:")
        ]


class BancTest(unittest.TestCase):
    version = "14.0"
    module = False
    coeur = "ancien"

    def setUp(self):
        self.banc = Banc(self.version, self.module, self.coeur)
        self.addCleanup(self.banc.nettoyer)


class TestOdoo14Traduit(BancTest):
    def test_db_list(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))

    def test_c_devient_odoo_rc_de_l_enfant(self):
        res = self.banc.lancer("db", "-c", "/srv/x/autre.conf", "version")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([["db", "--version"]], self.banc.argv_odoo(res))
        self.assertIn("RC:/srv/x/autre.conf", res.stdout)

    def test_module_uninstall_passe_par_run_sh(self):
        res = self.banc.lancer("module", "uninstall", "-d", "b", "m1,m2")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn(
            "RUN:[--no-http][--stop-after-init][-d][b][--uninstall][m1,m2]",
            res.stdout,
        )

    def test_theme_apply_passe_par_le_shell(self):
        res = self.banc.lancer("theme", "apply", "-d", "b", "theme_bidon")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            [["shell", "--no-http", "-d", "b"]], self.banc.argv_odoo(res)
        )
        self.assertIn("THEME:theme_bidon", res.stdout)
        self.assertIn("STDIN:import os", res.stdout)

    def test_i18n_passe_tel_quel(self):
        res = self.banc.lancer("i18n", "-d", "b", "--module", "m")
        self.assertEqual(
            [["i18n", "-d", "b", "--module", "m"]], self.banc.argv_odoo(res)
        )

    def test_une_option_serveur_passe_telle_quelle(self):
        res = self.banc.lancer("--stop-after-init", "-d", "b")
        self.assertEqual(
            [["--stop-after-init", "-d", "b"]], self.banc.argv_odoo(res)
        )

    def test_la_variable_court_circuite_la_traduction(self):
        res = self.banc.lancer(
            "db", "--list", env={"ERPLIBRE_ODOO_CLI_LEGACY": "1"}
        )
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))

    def test_une_erreur_d_usage_sort_en_2(self):
        res = self.banc.lancer("db", "rename", "a", "b")
        self.assertEqual(2, res.returncode)
        self.assertEqual([], self.banc.argv_odoo(res))


class TestOdoo12Traduit(BancTest):
    """Un cœur sans odoo/cli/db.py n'est pas celui d'OCB : traduit."""

    version = "12.0"
    coeur = "absent"

    def test_db_list(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))


class TestOdoo18Direct(BancTest):
    version = "18.0"
    module = True
    coeur = "ocb"

    def test_db_list_n_est_pas_traduit(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([["db", "list"]], self.banc.argv_odoo(res))

    def test_module_n_est_pas_traduit(self):
        res = self.banc.lancer("module", "uninstall", "-d", "b", "m")
        self.assertEqual(
            [["module", "uninstall", "-d", "b", "m"]],
            self.banc.argv_odoo(res),
        )
        self.assertNotIn("RUN:", res.stdout)


class TestOdoo16Direct(BancTest):
    version = "16.0"
    module = True
    coeur = "ocb"

    def test_db_list_n_est_pas_traduit(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual([["db", "list"]], self.banc.argv_odoo(res))


class TestOdoo16AncienCoeurTraduit(BancTest):
    """Un fork 16 resté sur ses anciens commits garde la commande à
    drapeaux."""

    version = "16.0"

    def test_db_list(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))

    def test_load_neutralize(self):
        res = self.banc.lancer("db", "load", "b", "--image", "i", "-n")
        self.assertEqual(0, res.returncode, res.stderr)
        argv = self.banc.argv_odoo(res)
        self.assertEqual(1, len(argv))
        self.assertIn("--restore", argv[0])
        self.assertIn("--neutralize", argv[0])

    def test_module_uninstall_passe_par_run_sh(self):
        res = self.banc.lancer("module", "uninstall", "-d", "b", "m")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("[--uninstall][m]", res.stdout)


class TestOdoo16AncienCoeurAvecModuleTraduit(BancTest):
    """Le module à côté d'un ancien cœur ne change rien : le cœur décide."""

    version = "16.0"
    module = True

    def test_db_list(self):
        res = self.banc.lancer("db", "list")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))

    def test_module_uninstall_passe_par_run_sh(self):
        res = self.banc.lancer("module", "uninstall", "-d", "b", "m")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("[--uninstall][m]", res.stdout)


class TestCoeurOcbSansModule(BancTest):
    """Un cœur d'OCB sans le module n'a ni « db list » ni « module » :
    sortie 2 et un message qui nomme le module, sans appeler Odoo."""

    version = "18.0"
    coeur = "ocb"

    def test_db_module_theme_sortent_en_2(self):
        for argv in (
            ("db", "list"),
            ("module", "uninstall", "-d", "b", "m"),
            ("theme", "apply", "-d", "b", "theme_bidon"),
        ):
            with self.subTest(argv=argv):
                res = self.banc.lancer(*argv)
                self.assertEqual(2, res.returncode)
                self.assertIn("erplibre_odoo_cli_base", res.stderr)
                self.assertIn("odoo18.0", res.stderr)
                self.assertEqual([], self.banc.argv_odoo(res))
                self.assertNotIn("RUN:", res.stdout)

    def test_les_autres_commandes_passent(self):
        res = self.banc.lancer("i18n", "-d", "b", "--module", "m")
        self.assertEqual(
            [["i18n", "-d", "b", "--module", "m"]], self.banc.argv_odoo(res)
        )

    def test_la_variable_court_circuite_le_refus(self):
        res = self.banc.lancer(
            "db", "--list", env={"ERPLIBRE_ODOO_CLI_LEGACY": "1"}
        )
        self.assertEqual([["db", "--list"]], self.banc.argv_odoo(res))


if __name__ == "__main__":
    unittest.main()
