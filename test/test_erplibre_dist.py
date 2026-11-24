#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre-dist : un ERPLibre installé devient un dépôt livrable, figé, sans
module propriétaire, installable hors ligne."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.deployment import erplibre_dist as X
from script.deployment import erplibre_serve as S

SHA_CŒUR = "a" * 40
SHA_ADDONS = "b" * 40
MANIFESTE = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="Org" fetch="https://forge.invente.test/Org/" />
  <project name="odoo.git" path="odoo18.0/odoo" remote="Org"
           freeze-revision="{SHA_CŒUR}" groups="odoo,odoo18.0" />
  <project name="outils.git" path="odoo18.0/addons/Org_outils" remote="Org"
           freeze-revision="{SHA_ADDONS}" groups="addons,odoo18.0" />
  <project name="dev.git" path="odoo18.0/addons/Org_dev" remote="Org"
           freeze-revision="{"c" * 40}" groups="migration" />
  <project name="outil.git" path="script/Org_outil" remote="Org"
           revision="main" groups="odoo,code_generator" />
  <project name="fige.git" path="odoo18.0/addons/Org_fige" remote="Org"
           revision="{"e" * 40}" upstream="18.0" groups="addons,odoo18.0" />
  <!-- <project name="eteint.git" path="x" remote="Org" groups="addons" /> -->
</manifest>
"""


class LesProjets(unittest.TestCase):
    def test_groups_and_tree_filter_and_url(self):
        liste = X.projets([MANIFESTE], prefixe="odoo18.0/")
        self.assertEqual(
            [
                "odoo18.0/addons/Org_fige",
                "odoo18.0/addons/Org_outils",
                "odoo18.0/odoo",
            ],
            [p.chemin for p in liste],
        )
        self.assertEqual(
            "https://forge.invente.test/Org/odoo.git",
            [p for p in liste if p.nom == "odoo.git"][0].url,
        )

    def test_a_sha_revision_is_the_frozen_commit_a_branch_is_not(self):
        par_chemin = {p.chemin: p.freeze for p in X.projets([MANIFESTE])}
        self.assertEqual("e" * 40, par_chemin["odoo18.0/addons/Org_fige"])
        self.assertEqual("", par_chemin["script/Org_outil"])

    def test_freeze_mismatch_or_absence_is_an_ecart(self):
        liste = X.projets([MANIFESTE], prefixe="odoo18.0/odoo")
        liste += X.projets([MANIFESTE], prefixe="odoo18.0/addons/Org_outils")
        tetes = {
            "odoo18.0/odoo": SHA_CŒUR,
            "odoo18.0/addons/Org_outils": "d" * 40,
        }
        ecarts = X.ecarts_de_freeze(liste, tetes)
        self.assertEqual(1, len(ecarts))
        self.assertIn("Org_outils", ecarts[0])
        sans = liste[0]._replace(freeze="")
        self.assertIn(
            "suit sa branche",
            X.ecarts_de_freeze([sans], {sans.chemin: "x"})[0],
        )
        self.assertEqual(
            [],
            X.ecarts_de_freeze(
                liste,
                {
                    "odoo18.0/odoo": SHA_CŒUR,
                    "odoo18.0/addons/Org_outils": SHA_ADDONS,
                },
            ),
        )


class LesLicences(unittest.TestCase):
    def test_declared_default_and_unreadable(self):
        self.assertEqual("OPL-1", X.licence_de("{'license': 'OPL-1'}"))
        self.assertEqual("LGPL-3", X.licence_de("{'name': 'x'}"))
        self.assertEqual("", X.licence_de("pas un dict ("))

    def test_proprietary_modules_and_git_are_not_copied(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        source = d / "Org_outils"
        for module, licence in (
            ("libre", "AGPL-3"),
            ("prive", "OPL-1"),
            ("ferme", "Other proprietary"),
            ("sans", None),
        ):
            (source / module / ".git").mkdir(parents=True)
            texte = {"name": module}
            if licence:
                texte["license"] = licence
            (source / module / "__manifest__.py").write_text(repr(texte))
        (source / ".git").mkdir()
        exclus = X.modules_proprietaires(source)
        self.assertEqual(
            [("ferme", "Other proprietary"), ("prive", "OPL-1")], exclus
        )
        shutil.copytree(
            source,
            d / "copie",
            ignore=X.ignore_pour(source, {m for m, _l in exclus}),
        )
        self.assertEqual(
            ["libre", "sans"],
            sorted(p.name for p in (d / "copie").iterdir()),
        )
        self.assertFalse(any((d / "copie").rglob(".git")))


class LesPieces(unittest.TestCase):
    def test_lock_line_from_a_wheel_name(self):
        self.assertEqual(
            "psycopg2==2.9.10 --hash=sha256:ab",
            X.ligne_lock("psycopg2-2.9.10-cp312-cp312-linux_x86_64.whl", "ab"),
        )
        self.assertEqual(
            "zope.event==5.0 --hash=sha256:cd",
            X.ligne_lock("zope.event-5.0-1-py3-none-any.whl", "cd"),
        )
        with self.assertRaises(ValueError):
            X.ligne_lock("pas-une-roue.tar.gz", "x")

    def test_addons_path_keeps_only_copied_projects_relative(self):
        self.assertEqual(
            "odoo18.0/odoo/addons,odoo18.0/addons/Org_outils",
            X.addons_path_relatif(
                "/r/odoo18.0/odoo/addons, /r/odoo18.0/addons/Org_outils/,"
                "/r/odoo18.0/addons/addons,/r/odoo18.0/addons/Org_outils2,"
                "/ailleurs/addons",
                "/r",
                ["odoo18.0/odoo", "odoo18.0/addons/Org_outils"],
            ),
        )

    def test_the_launcher_resolves_relative_entries(self):
        self.assertEqual(
            "/srv/l/odoo18.0/odoo/addons,/abs",
            S.resoudre_addons_path(
                "odoo18.0/odoo/addons,/abs", Path("/srv/l")
            ),
        )

    def test_provenance_first_line_follows_the_frozen_code(self):
        liste = X.projets([MANIFESTE])
        a = X.texte_provenance(liste, [], "odoo18.0_python3.12.16")
        b = X.texte_provenance(
            [liste[0]._replace(freeze="f" * 40)] + liste[1:],
            [],
            "odoo18.0_python3.12.16",
        )
        self.assertTrue(a.startswith("odoo18.0_python3.12.16-"))
        self.assertNotEqual(a.splitlines()[0], b.splitlines()[0])


class LaConstruction(unittest.TestCase):
    """De bout en bout sur un faux ERPLibre, un faux exécuteur à la place de
    git, pip et Odoo."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        r = self.racine = self.d / "erplibre"
        (r / ".repo" / "local_manifests").mkdir(parents=True)
        (r / X.MANIFESTE_FUSIONNE).write_text(MANIFESTE)
        (r / ".erplibre-version").write_text("odoo18.0_python3.12.16")
        (r / ".odoo-version").write_text("18.0")
        (r / "conf").mkdir()
        (r / "conf" / "supported_version_erplibre.json").write_text(
            json.dumps({"odoo18.0_python3.12.16": {"odoo_version": "18.0"}})
        )
        (r / "script" / "deployment").mkdir(parents=True)
        (r / "script" / "deployment" / "erplibre_serve.py").write_text("# x")
        (r / "config.conf").write_text(
            f"[options]\naddons_path = {r}/odoo18.0/odoo/addons,"
            f"{r}/odoo18.0/addons/Org_outils\n"
        )
        (r / "odoo18.0" / "odoo" / "odoo-bin").parent.mkdir(parents=True)
        (r / "odoo18.0" / "odoo" / "odoo-bin").write_text("")
        (r / "odoo18.0" / "odoo" / ".git").mkdir()
        (r / "odoo18.0" / "addons" / "Org_fige").mkdir(parents=True)
        outils = r / "odoo18.0" / "addons" / "Org_outils"
        for module, licence in (("libre", "AGPL-3"), ("prive", "OPL-1")):
            (outils / module).mkdir(parents=True)
            (outils / module / "__manifest__.py").write_text(
                repr({"license": licence})
            )
        self.sortie = self.d / "dist"
        self.joues = []

    def executer(self, tetes=None, odoo_rc=0):
        tetes = tetes or {}

        def faux(argv, capture_output=False, text=False, **_k):
            self.joues.append(argv)
            if argv[0] == "git":
                chemin = argv[2]
                defaut = {"odoo": SHA_CŒUR, "Org_fige": "e" * 40}
                sha = tetes.get(
                    chemin, defaut.get(Path(chemin).name, SHA_ADDONS)
                )
                return subprocess.CompletedProcess(argv, 0, sha + "\n", "")
            if argv[1:3] == ["-m", "pip"] and argv[3] == "freeze":
                return subprocess.CompletedProcess(
                    argv, 0, "aaa==1.0\nbbb==2.0\npkg_resources==0.0.0\n", ""
                )
            if argv[1:3] == ["-m", "pip"] and argv[3] == "wheel":
                dossier = Path(argv[argv.index("-w") + 1])
                dossier.mkdir(parents=True, exist_ok=True)
                for nom in (
                    "aaa-1.0-py3-none-any.whl",
                    "bbb-2.0-cp312-cp312-linux_x86_64.whl",
                ):
                    (dossier / nom).write_bytes(nom.encode())
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "-c" in argv and "_base_executable" in argv[-1]:
                return subprocess.CompletedProcess(argv, 0, "/py\n", "")
            if "--stop-after-init" in argv:
                return subprocess.CompletedProcess(argv, odoo_rc, "", "boum")
            return subprocess.CompletedProcess(argv, 0, "", "")

        return faux

    def test_a_built_distribution_is_complete_and_free(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(),
            epreuve=False,
            dire=lambda *_a: None,
        )
        self.assertEqual([], ecarts)
        s = self.sortie
        self.assertTrue((s / "odoo18.0/addons/Org_outils/libre").is_dir())
        self.assertFalse((s / "odoo18.0/addons/Org_outils/prive").exists())
        self.assertFalse((s / "odoo18.0/odoo/.git").exists())
        self.assertFalse((s / "odoo18.0/addons/Org_dev").exists())
        self.assertTrue((s / "odoo18.0/addons/Org_fige").is_dir())
        self.assertFalse((s / "script/Org_outil").exists())
        verrou = (s / "requirements.lock.txt").read_text().splitlines()
        self.assertEqual(2, len(verrou))
        self.assertTrue(all("--hash=sha256:" in ligne for ligne in verrou))
        self.assertNotIn("pkg_resources", (s / "requirements.txt").read_text())
        self.assertEqual(
            "odoo18.0/odoo/addons,odoo18.0/addons/Org_outils",
            S.addons_path_de((s / "config.conf").read_text()),
        )
        self.assertIn("prive\tOPL-1", (s / "PROVENANCE.lock").read_text())
        self.assertEqual(
            S.Versions("odoo18.0_python3.12.16", "18.0"), S.versions(s)
        )

    def test_an_unfrozen_project_refuses_and_writes_nothing(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(
                {str(self.racine / "odoo18.0/odoo"): "f" * 40}
            ),
            epreuve=False,
            dire=lambda *_a: None,
        )
        self.assertEqual(1, len(ecarts))
        self.assertFalse(self.sortie.exists())

    def test_the_proof_installs_offline_and_drops_its_base(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(),
            dire=lambda *_a: None,
        )
        self.assertEqual([], ecarts)
        installe = [j for j in self.joues if "install" in j]
        self.assertTrue(installe)
        self.assertIn("--no-index", installe[0])
        self.assertIn("--require-hashes", installe[0])
        self.assertEqual(
            ["dropdb", "--if-exists", X.BASE_EPREUVE], self.joues[-1]
        )

    def test_a_failed_proof_is_an_ecart_and_still_drops_its_base(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(odoo_rc=1),
            dire=lambda *_a: None,
        )
        self.assertEqual(1, len(ecarts))
        self.assertIn("épreuve", ecarts[0])
        self.assertEqual("dropdb", self.joues[-1][0])


if __name__ == "__main__":
    unittest.main()
