#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installer plusieurs versions d'Odoo, ou toutes : un seul chemin.

script/version/install_odoo_versions.py sert la sélection multiple de
TODO › Installation, son « w » et « make install_odoo_all_version ». Chaque
installation récrit la version active ; le lot revient ensuite sur la
version active avant lui, ou laisse la dernière installée. Pour --all, la
version par défaut du catalogue vient en dernier : une machine neuve finit
sur elle, la version que le service et les images de référence attendent.
"""

import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from script.version import install_odoo_versions as lot

RACINE = Path(__file__).resolve().parents[1]
MAKEFILE = RACINE / "conf/make.installation.Makefile"
VERSIONS = RACINE / "conf/supported_version_erplibre.json"


def _catalogue():
    with VERSIONS.open(encoding="utf-8") as fh:
        return [dict(v, erplibre_version=k) for k, v in json.load(fh).items()]


class LOrdreDeToutesLesVersions(unittest.TestCase):
    def test_it_covers_the_catalogue_and_ends_on_the_default(self):
        ordre = lot.ordre_tout(_catalogue())
        self.assertEqual(len(ordre), len(_catalogue()))
        self.assertTrue(ordre[-1].get("default"))
        self.assertEqual(1, sum(1 for e in ordre if e.get("default")))

    def test_the_others_go_from_newest_to_oldest(self):
        majeures = [
            int(e["odoo_version"].split(".")[0])
            for e in lot.ordre_tout(_catalogue())[:-1]
        ]
        self.assertEqual(majeures, sorted(majeures, reverse=True))

    def test_make_target_goes_through_the_same_path(self):
        recette = re.search(
            r"^install_odoo_all_version:[^\n]*\n((?:\t[^\n]*\n?)+)",
            MAKEFILE.read_text("utf-8"),
            re.M,
        ).group(1)
        self.assertEqual(
            recette.strip(), "./script/version/install_odoo_versions.py --all"
        )


class LeRetourApresLeLot(unittest.TestCase):
    def test_the_previous_version_comes_back_when_still_installed(self):
        cible = lot.cible_retour(
            "odoo17.0_python3.10.18",
            ["odoo12.0_python3.7.17"],
            ["odoo12.0", "odoo17.0"],
            "odoo12.0_python3.7.17",
        )
        self.assertEqual(cible, "odoo17.0_python3.10.18")

    def test_a_fresh_machine_stays_on_the_last_installed(self):
        self.assertIsNone(
            lot.cible_retour(
                "",
                ["odoo12.0_python3.7.17", "odoo18.0_python3.12.16"],
                ["odoo12.0", "odoo18.0"],
                "odoo18.0_python3.12.16",
            )
        )

    def test_nothing_succeeded_switches_nothing(self):
        self.assertIsNone(lot.cible_retour("", [], [], "x"))


class LaLigneDeCommande(unittest.TestCase):
    """main() avec l'exécution simulée : chaque commande rend un code."""

    def jouer(self, argv, codes=None, active="odoo18.0_python3.12.16"):
        etat = {"active": active, "installees": []}
        lancees = []

        def run(cmd, shell=False, executable=None):
            lancees.append(cmd)
            version = cmd.split("--erplibre_version ", 1)[1].split()[0]
            code = (codes or {}).get(version, 0)
            if not code:
                etat["active"] = version
                etat["installees"].append(version.split("_python", 1)[0])
            return mock.Mock(returncode=code)

        catalogue = _catalogue()
        sortie = io.StringIO()
        with (
            mock.patch.object(lot.subprocess, "run", run),
            mock.patch.object(
                lot,
                "get_odoo_version",
                lambda: (catalogue, etat["installees"], None),
            ),
            mock.patch.object(lot, "_active", lambda: etat["active"]),
            mock.patch.object(lot, "_marquer", lambda v: None),
            redirect_stdout(sortie),
        ):
            code = lot.main(argv)
        return code, lancees, sortie.getvalue(), etat

    def test_versions_install_in_the_order_given(self):
        code, lancees, _, _ = self.jouer(["12.0", "17.0"])
        self.assertEqual(code, 0)
        self.assertEqual(
            [c.split("--erplibre_version ")[1].split()[0] for c in lancees],
            ["odoo12.0_python3.7.17", "odoo17.0_python3.10.18"],
        )

    def test_a_failure_goes_on_and_the_exit_code_says_it(self):
        code, lancees, sortie, _ = self.jouer(
            ["12.0", "17.0"], codes={"odoo12.0_python3.7.17": 3}
        )
        self.assertEqual(code, 1)
        self.assertEqual(len([c for c in lancees if "--install_dev" in c]), 2)
        self.assertIn("❌ Odoo 12.0", sortie)
        self.assertIn("✅ Odoo 17.0", sortie)

    def test_all_installs_every_version_and_ends_on_the_default(self):
        code, lancees, _, etat = self.jouer(["--all"], active="")
        self.assertEqual(code, 0)
        self.assertEqual(len(lancees), len(_catalogue()))
        defaut = [e for e in _catalogue() if e.get("default")][0]
        self.assertEqual(etat["active"], defaut["erplibre_version"])

    def test_versions_and_all_together_are_refused(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            with mock.patch("sys.stderr", io.StringIO()):
                lot.main(["--all", "12.0"])


if __name__ == "__main__":
    unittest.main()
