#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que .ruff.toml formate, et ce qu'il laisse aux dépôts rapatriés.

ruff lit le code sur son entrée avec `--stdin-filename` : le chemin n'a
pas besoin d'exister, seules les exclusions de .ruff.toml décident. Un
fichier formaté revient réécrit, un fichier écarté revient tel quel —
`force-exclude` vaut pour un chemin nommé comme pour un chemin découvert.
"""

import os
import subprocess
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUFF = os.path.join(RACINE, ".venv.erplibre", "bin", "ruff")
CONFIG = os.path.join(RACINE, ".ruff.toml")
NON_FORMATE = "x=1\n"


def formate(chemin):
    """Vrai si ruff, réglé par .ruff.toml, formate le fichier `chemin`."""
    sortie = subprocess.run(
        [
            RUFF,
            "format",
            "--config",
            CONFIG,
            "--force-exclude",
            "--stdin-filename",
            chemin,
            "-",
        ],
        input=NON_FORMATE,
        capture_output=True,
        text=True,
        cwd=RACINE,
        check=True,
        timeout=60,
    ).stdout
    return sortie != NON_FORMATE


@unittest.skipUnless(os.access(RUFF, os.X_OK), "ruff absent de .venv.erplibre")
class TestLesExclusions(unittest.TestCase):
    def test_tooling_named_after_odoo_is_formatted(self):
        """Un script de l'outillage dont le nom commence par « odoo » n'est
        pas un dépôt d'Odoo."""
        for chemin in (
            "script/test/odoo_test_report.py",
            "script/odoo/warmup_http.py",
            "script/database/odoo_db_legacy.py",
            "test/test_odoo_test_report.py",
        ):
            with self.subTest(chemin=chemin):
                self.assertTrue(formate(chemin))

    def test_fetched_repositories_are_left_alone(self):
        for chemin in (
            "odoo18.0/addons/invented_repo/invented_module/models.py",
            "odoo12.0/odoo/odoo/invented.py",
            "addons/invented_repo/invented_module/models.py",
            "script/OCA_maintainer-tools/invented.py",
            "script/stream_deck/games/invented.py",
            "script/gnome-extension/erplibre_home/invented.py",
        ):
            with self.subTest(chemin=chemin):
                self.assertFalse(formate(chemin))


if __name__ == "__main__":
    unittest.main()
