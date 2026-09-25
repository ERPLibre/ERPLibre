#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chaque version du catalogue a-t-elle les fichiers qui l'installent ?

conf/supported_version_erplibre.json est lu par les menus, par
update_env_version.py et par la construction Docker : une entrée y rend la
version choisissable partout. Or l'installer exige, sous le couple
« odooX.Y_pythonA.B.C » de la clé, le pyproject et le verrou que Poetry
applique, la liste de priorité et la liste d'exclusion que lit
poetry_update.py, et les deux manifestes que clone Google Repo. Qu'un seul
manque, et la version se choisit sans broncher puis échoue à l'installation.
"""

import json
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CATALOGUE = json.loads(
    (RACINE / "conf/supported_version_erplibre.json").read_text(
        encoding="utf-8"
    )
)


class TestFichiersDuCatalogue(unittest.TestCase):
    def test_chaque_version_a_ses_fichiers(self):
        for cle, entree in CATALOGUE.items():
            odoo = entree["odoo_version"]
            attendus = [
                f"requirement/pyproject.{cle}.toml",
                f"requirement/poetry.{cle}.lock",
                f"requirement/requirements.{cle}.txt",
                f"requirement/ignore_requirements.{cle}.txt",
                f"manifest/git_manifest_odoo{odoo}.xml",
                f"manifest/git_manifest_odoo{odoo}_dev.xml",
            ]
            for chemin in attendus:
                with self.subTest(version=cle, fichier=chemin):
                    self.assertTrue((RACINE / chemin).is_file())

    def test_la_cle_porte_les_versions_de_l_entree(self):
        """La clé nomme les fichiers ; l'entrée, ce qui est installé."""
        for cle, entree in CATALOGUE.items():
            with self.subTest(version=cle):
                self.assertEqual(
                    f"odoo{entree['odoo_version']}"
                    f"_python{entree['python_version']}",
                    cle,
                )


if __name__ == "__main__":
    unittest.main()
