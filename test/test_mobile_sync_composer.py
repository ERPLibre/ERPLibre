#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le script des corps de référence du compositeur, sans Odoo ni Chromium :
il refuse d'écrire des références qu'un autre Odoo que le 18 produirait."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "long_test"))

import mobile_sync_composer as composer  # noqa: E402


class TestVersion(unittest.TestCase):
    def lancer(self, majeure):
        """main() contre un serveur qui dit être Odoo majeure ; rend (code,
        référence écrite ?). Rien d'autre ne doit être appelé."""
        with tempfile.TemporaryDirectory() as dossier:
            sortie = Path(dossier) / "composer-golden.json"
            with mock.patch.object(
                composer, "version_repondue", return_value=majeure
            ), mock.patch.object(
                composer, "REFERENCE", sortie
            ), mock.patch.object(
                composer, "session", side_effect=AssertionError("connexion")
            ), mock.patch(
                "builtins.print"
            ):
                code = composer.main(
                    ["http://127.0.0.1:1", "admin", "admin", "--base", "b"]
                )
            return code, sortie.exists()

    def test_refuse_un_autre_odoo_que_18(self):
        self.assertEqual(self.lancer(17), (composer.SORTIE_VERSION, False))

    def test_refuse_un_serveur_muet(self):
        self.assertEqual(self.lancer(None), (composer.SORTIE_VERSION, False))


if __name__ == "__main__":
    unittest.main()
