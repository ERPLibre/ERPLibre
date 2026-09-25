#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La migration sait-elle quelles versions ont un OpenUpgrade ?

Chaque étape vers la version N exécute OpenUpgrade de la branche N, que
déclare manifest/git_manifest_odooN.0_dev.xml. OCA ne couvre une version
qu'après sa sortie : la cible est proposée quand même, la migration prévient
dès le choix, et s'arrête avant l'étape plutôt que de lancer un chemin vide.
"""

import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo.todo_upgrade import openupgrade_declared  # noqa: E402

AVEC = """<manifest>
    <project name="OpenUpgrade.git" revision="19.0"
        path="odoo19.0/OCA_OpenUpgrade" remote="OCA" />
</manifest>
"""
SANS = """<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />
</manifest>
"""


class TestOpenUpgradeDeclare(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name)
        (self.racine / "manifest").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _manifeste(self, version, contenu):
        (
            self.racine / "manifest" / f"git_manifest_odoo{version}.0_dev.xml"
        ).write_text(contenu)

    def test_une_branche_declaree(self):
        self._manifeste(19, AVEC)
        self.assertTrue(openupgrade_declared(19, racine=self.racine))

    def test_un_manifeste_sans_openupgrade(self):
        self._manifeste(20, SANS)
        self.assertFalse(openupgrade_declared(20, racine=self.racine))

    def test_une_version_sans_manifeste(self):
        self.assertFalse(openupgrade_declared(21, racine=self.racine))

    def test_la_branche_d_une_autre_version_ne_compte_pas(self):
        """Le chemin porte la version : un OpenUpgrade 19 ne sert pas 20."""
        self._manifeste(20, AVEC)
        self.assertFalse(openupgrade_declared(20, racine=self.racine))

    def test_les_manifestes_du_depot(self):
        """10 à 19 ont leur OpenUpgrade ; 20 pas encore."""
        for version in range(10, 20):
            with self.subTest(version=version):
                self.assertTrue(openupgrade_declared(version, racine=RACINE))


class TestLaCibleEstInstallee(unittest.TestCase):
    def test_la_plage_d_installation_comprend_la_cible(self):
        """La dernière étape bascule sur la cible : elle doit être installée."""
        source = (RACINE / "script/todo/todo_upgrade.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("range(start_version, end_version + 1)", source)


if __name__ == "__main__":
    unittest.main()
