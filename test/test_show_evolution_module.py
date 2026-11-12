#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les dépôts que clone la statistique d'évolution des modules : ceux des
manifestes d'Odoo, un fork remplacé par son amont.

Les manifestes sont fabriqués dans un répertoire jetable : le test ne lit
ni le réseau ni les manifestes du dépôt.
"""

import datetime
import importlib.util
import os
import sys
import tempfile
import unittest
import unittest.mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RACINE)
_spec = importlib.util.spec_from_file_location(
    "show_evolution_module",
    os.path.join(RACINE, "script", "statistic", "show_evolution_module.py"),
)
sem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sem)

MANIFESTE = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="OCA" fetch="https://github.com/OCA/" />
    <remote name="ERPLibre_origin_OCA" fetch="https://github.com/ERPLibre/" />
    <remote name="odoo" fetch="https://github.com/odoo" />
    <remote name="Exemple" fetch="https://github.com/Exemple/" />
    <project name="server-tools.git" path="odoo{v}/addons/OCA_server-tools"
        remote="ERPLibre_origin_OCA" fork-upstream-remote="OCA"
        fork-upstream="{v}" />
    <project name="OCB.git" path="odoo{v}/odoo" remote="ERPLibre_origin_OCA"
        fork-upstream-remote="odoo" fork-upstream-name="odoo.git" />
    <project name="addons-exemple" path="odoo{v}/addons/Exemple_addons"
        remote="Exemple" />
    <!-- <project name="retire.git" path="x" remote="OCA" /> -->
</manifest>
"""


class TestLesDepotsDesManifestes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for v in ("17.0", "18.0"):
            with open(
                os.path.join(self.tmp.name, f"git_manifest_odoo{v}.xml"), "w"
            ) as fh:
                fh.write(MANIFESTE.format(v=v))
        # Un fichier hors du motif n'est pas lu.
        with open(
            os.path.join(self.tmp.name, "default.staged.deprecated.xml"), "w"
        ) as fh:
            fh.write("<manifest><project name='x' remote='y'/></manifest>")

    def test_a_fork_is_replaced_by_its_upstream_once(self):
        self.assertEqual(
            sem.urls_des_manifestes(self.tmp.name),
            [
                "https://github.com/Exemple/addons-exemple.git",
                "https://github.com/OCA/server-tools.git",
                "https://github.com/odoo/odoo.git",
            ],
        )

    def test_filter_and_ignore_list(self):
        class Config:
            filter = "/OCA/"

        urls = sem.urls_des_manifestes(self.tmp.name)
        with (
            unittest.mock.patch.object(
                sem, "urls_des_manifestes", return_value=urls
            ),
            unittest.mock.patch.object(
                sem,
                "IGNORE_REPO_LIST",
                ("https://github.com/Exemple/addons-exemple.git",),
            ),
        ):
            self.assertEqual(
                sem.get_OCA_repo_list(Config),
                ["https://github.com/OCA/server-tools.git"],
            )
            Config.filter = None
            self.assertNotIn(
                "https://github.com/Exemple/addons-exemple.git",
                sem.get_OCA_repo_list(Config),
            )


class TestLesVersionsComptees(unittest.TestCase):
    """Un relevé compte les branches des versions sorties avant sa date."""

    def branches_au(self, date):
        return sem.get_branches_supported_date(
            sem.BRANCHES_PAR_DEFAUT.split(","), date
        )

    def test_default_branches_follow_the_release_table(self):
        branches = sem.BRANCHES_PAR_DEFAUT.split(",")
        self.assertEqual(branches[0], "6.1")
        self.assertEqual(branches[-1], list(sem.DCT_VERSION_RELEASE)[-1])
        self.assertIn("20.0", branches)

    def test_the_last_snapshot_counts_every_released_version(self):
        self.assertEqual(
            self.branches_au(datetime.date(2023, 1, 1))[-1], "16.0"
        )
        self.assertEqual(
            self.branches_au(datetime.date(2027, 1, 1))[-1], "20.0"
        )


if __name__ == "__main__":
    unittest.main()
