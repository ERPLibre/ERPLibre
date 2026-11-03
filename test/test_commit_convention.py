#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.git.commit_convention import (
    ERPLIBRE,
    OCA,
    ODOO,
    classify,
    classify_project,
    classify_urls,
    manifest_projects,
)

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
    <remote name="Exemple" fetch="https://github.com/Exemple/" />
    <default remote="Exemple" revision="18.0" />
    <project name="odoo.git" path="odoo18.0/odoo" remote="Exemple_origin_odoo"
        fork-upstream-remote="OCA" fork-upstream-name="OCB.git" />
    <project name="outils.git" path="odoo18.0/addons/OCA_outils" remote="OCA" />
    <project name="outils-fork.git" path="odoo18.0/addons/OCA_outils_fork"
        remote="Exemple_origin_OCA" fork-upstream-remote="OCA" />
    <project name="maison.git" path="odoo18.0/addons/Exemple_maison" />
    <project name="tiers.git" path="odoo18.0/addons/Tiers_modules"
        remote="Exemple_origin_Tiers" fork-upstream-remote="Tiers" />
</manifest>
"""


def _git_init(path: Path, remote_url: str = "") -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote_url:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", "origin", remote_url],
            check=True,
        )


class TestClassifyProject(unittest.TestCase):
    """Le verdict tiré des seuls attributs d'un <project>."""

    def test_core_is_odoo_despite_oca_upstream(self):
        attrs = {
            "name": "odoo.git",
            "remote": "Exemple_origin_odoo",
            "fork-upstream-remote": "OCA",
            "fork-upstream-name": "OCB.git",
        }
        self.assertEqual(classify_project(attrs)[0], ODOO)

    def test_odoo_remote_is_odoo(self):
        self.assertEqual(classify_project({"remote": "odoo"})[0], ODOO)

    def test_oca_remote_is_oca(self):
        self.assertEqual(classify_project({"remote": "OCA"})[0], OCA)

    def test_fork_of_oca_by_remote_name_is_oca(self):
        self.assertEqual(
            classify_project({"remote": "Exemple_origin_OCA"})[0], OCA
        )

    def test_fork_of_oca_by_upstream_attribute_is_oca(self):
        attrs = {"remote": "Exemple", "fork-upstream-remote": "OCA"}
        self.assertEqual(classify_project(attrs)[0], OCA)

    def test_third_party_fork_is_erplibre(self):
        attrs = {"remote": "Exemple_origin_Tiers", "fork-upstream-remote": "Tiers"}
        self.assertEqual(classify_project(attrs)[0], ERPLIBRE)


class TestClassifyUrls(unittest.TestCase):
    """Le repli sur les URL des remotes git, en HTTPS comme en SSH."""

    def test_odoo_organisation_is_odoo(self):
        self.assertEqual(
            classify_urls(["https://github.com/odoo/odoo.git"])[0], ODOO
        )

    def test_ocb_is_odoo(self):
        self.assertEqual(classify_urls(["git@github.com:OCA/OCB.git"])[0], ODOO)

    def test_oca_ssh_is_oca(self):
        self.assertEqual(
            classify_urls(["git@github.com:OCA/outils.git"])[0], OCA
        )

    def test_other_owner_is_erplibre(self):
        self.assertEqual(
            classify_urls(["https://github.com/Exemple/outils.git"])[0],
            ERPLIBRE,
        )

    def test_no_url_is_erplibre(self):
        self.assertEqual(classify_urls([])[0], ERPLIBRE)


class TestClassifyCheckout(unittest.TestCase):
    """Le verdict sur un checkout réel : manifestes, puis remotes git."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "manifest").mkdir()
        (self.root / "manifest" / "git_manifest_exemple.xml").write_text(MANIFEST)
        (self.root / "manifest" / "casse.xml").write_text("<manifest>")
        _git_init(self.root)

    def test_root_is_erplibre(self):
        self.assertEqual(classify(self.root, self.root)[0], ERPLIBRE)

    def test_broken_manifest_is_skipped(self):
        self.assertIn("odoo18.0/odoo", manifest_projects(self.root))

    def test_default_remote_fills_missing_attribute(self):
        projects = manifest_projects(self.root)
        self.assertEqual(
            projects["odoo18.0/addons/Exemple_maison"]["remote"], "Exemple"
        )

    def test_manifest_classes(self):
        cases = {
            "odoo18.0/odoo": ODOO,
            "odoo18.0/addons/OCA_outils": OCA,
            "odoo18.0/addons/OCA_outils_fork": OCA,
            "odoo18.0/addons/Exemple_maison": ERPLIBRE,
            "odoo18.0/addons/Tiers_modules": ERPLIBRE,
        }
        for relative, expected in cases.items():
            with self.subTest(relative=relative):
                _git_init(self.root / relative)
                self.assertEqual(
                    classify(self.root / relative, self.root)[0], expected
                )

    def test_subdirectory_resolves_to_its_repository(self):
        repo = self.root / "odoo18.0/addons/OCA_outils"
        _git_init(repo)
        (repo / "module_exemple" / "models").mkdir(parents=True)
        self.assertEqual(
            classify(repo / "module_exemple" / "models", self.root)[0], OCA
        )

    def test_repository_outside_manifests_uses_remote_url(self):
        repo = self.root / "hors_manifeste"
        _git_init(repo, "git@github.com:OCA/outils-hors.git")
        self.assertEqual(classify(repo, self.root)[0], OCA)

    def test_outside_any_repository_is_erplibre(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        self.assertEqual(classify(outside, self.root)[0], ERPLIBRE)


if __name__ == "__main__":
    unittest.main()
