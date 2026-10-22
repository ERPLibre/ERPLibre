#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""git_merge_repo_manifest.py et la version d'Odoo de .odoo-version.

Le script lit conf/ et manifest/ depuis le répertoire courant : il tourne
ici dans une copie de ces deux répertoires, sans mobile/ ni .repo/.

Ce que ce test garde : un .odoo-version terminé par un saut de ligne, comme
l'écrit un éditeur, donne le même manifeste fusionné que sans, avec les
modules de cette version d'Odoo et sans ligne d'erreur.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/git/git_merge_repo_manifest.py"
VERSION = "18.0"


def chemins(manifeste):
    return sorted(
        p.get("path") for p in ET.parse(manifeste).getroot().iter("project")
    )


class LaVersionDOdoo(unittest.TestCase):
    def fusionner(self, contenu):
        with tempfile.TemporaryDirectory() as dossier:
            for nom in ("conf", "manifest"):
                shutil.copytree(RACINE / nom, Path(dossier, nom))
            Path(dossier, ".odoo-version").write_text(contenu)
            sortie = os.path.join(dossier, "fusion.xml")
            fini = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", sortie],
                cwd=dossier,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(0, fini.returncode, fini.stderr)
            return fini.stdout, chemins(sortie)

    def test_a_trailing_newline_changes_nothing(self):
        attendus = chemins(RACINE / f"manifest/git_manifest_odoo{VERSION}.xml")
        sans_saut, projets = self.fusionner(VERSION)
        avec_saut, projets_avec_saut = self.fusionner(VERSION + "\n")
        self.assertNotIn("ERROR", avec_saut)
        self.assertNotIn("ERROR", sans_saut)
        self.assertEqual(projets, projets_avec_saut)
        self.assertTrue(set(attendus) <= set(projets_avec_saut))


if __name__ == "__main__":
    unittest.main()
