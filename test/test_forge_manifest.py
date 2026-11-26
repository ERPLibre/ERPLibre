#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La surcouche privée qui fait synchroniser les dépôts depuis une forge.

Propriétés gardées :
- la surcouche ne porte que des `<remote>`, au fetch « <base>/<propriétaire>/ »,
  et la VRAIE fusion des manifestes lui donne le dernier mot sur ces
  remotes sans toucher aux projets ;
- elle s'inscrit en DERNIER dans private/default_git_manifest.csv, une
  seule fois, et son retrait n'efface que sa ligne ;
- les projets servis par un remote redirigé sans être sur la forge sont
  listés ;
- un nom de remote qui ne ferait pas un nom de fichier sûr est refusé.

Les adresses sont inventées (domaine réservé « .invalid »).
"""

import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from script.git import forge_manifest as fm

RACINE = Path(__file__).resolve().parents[1]
FUSION = RACINE / "script" / "git" / "git_merge_repo_manifest.py"
BASE = "ssh://git@forge.exemple.invalid:2222"

MANIFESTE = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Amont" fetch="https://github.com/Amont/" />
    <remote name="Autre" fetch="https://github.com/Autre/" />
    <project name="a.git" path="odooX.0/a" remote="Amont" revision="X.0" />
    <project name="b.git" path="odooX.0/b" remote="Amont" revision="X.0" />
    <project name="c.git" path="odooX.0/c" remote="Autre" revision="X.0" />
</manifest>
"""


def projet(chemin, nom, remote, proprietaire):
    return {
        "cle": f"{nom}+{chemin}",
        "chemin": chemin,
        "nom": nom,
        "remote": remote,
        "proprietaire": proprietaire,
    }


class Racine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def csv(self):
        chemin = os.path.join(
            self.racine, "private", "default_git_manifest.csv"
        )
        with open(chemin, encoding="utf-8") as fh:
            return fh.read().splitlines()


class TestTexte(Racine):
    def test_only_remotes_on_the_forge_layout(self):
        remotes = fm.remotes_rediriges(
            [
                projet("odooX.0/a", "a.git", "Amont", "Amont"),
                projet("odooX.0/b", "b.git", "Amont", "Amont"),
                projet("odooX.0/d", "d.git", "Sans", None),
            ],
            BASE + "/",
        )
        self.assertEqual(remotes, {"Amont": f"{BASE}/Amont/"})
        racine = ET.fromstring(fm.texte(remotes))
        self.assertEqual(racine.findall("project"), [])
        self.assertEqual(
            [
                (e.get("name"), e.get("fetch"))
                for e in racine.findall("remote")
            ],
            [("Amont", f"{BASE}/Amont/")],
        )

    def test_attributes_are_escaped(self):
        racine = ET.fromstring(fm.texte({'a"b': "x&y<"}))
        self.assertEqual(racine.find("remote").get("name"), 'a"b')
        self.assertEqual(racine.find("remote").get("fetch"), "x&y<")

    def test_an_unsafe_name_is_refused(self):
        for nom in ("", "../x", "a/b", ".cache", "a b"):
            with self.assertRaises(ValueError, msg=nom):
                fm.chemin(nom)
        self.assertEqual(
            fm.chemin("forge"),
            os.path.join(
                "private", "manifest", "git_manifest_forge_forge.xml"
            ),
        )


class TestEcrireRetirer(Racine):
    def test_written_last_once_then_removed_alone(self):
        os.makedirs(os.path.join(self.racine, "private"))
        with open(
            os.path.join(self.racine, "private", "default_git_manifest.csv"),
            "w",
        ) as fh:
            fh.write('"filepath"\n')
            fh.write("private/manifest/git_manifest_forge_forge.xml\n")
            fh.write("private/manifest/git_manifest_private_odooX.0.xml\n")
        chemin = fm.ecrire(self.racine, "forge", {"Amont": f"{BASE}/Amont/"})
        fm.ecrire(self.racine, "forge", {"Amont": f"{BASE}/Amont/"})
        self.assertEqual(
            self.csv(),
            [
                '"filepath"',
                "private/manifest/git_manifest_private_odooX.0.xml",
                chemin,
            ],
        )
        self.assertEqual(fm.surcouches(self.racine), ["forge"])
        self.assertEqual(
            fm.lire(self.racine, "forge"), {"Amont": f"{BASE}/Amont/"}
        )
        self.assertTrue(fm.retirer(self.racine, "forge"))
        self.assertEqual(
            self.csv(),
            [
                '"filepath"',
                "private/manifest/git_manifest_private_odooX.0.xml",
            ],
        )
        self.assertEqual(fm.surcouches(self.racine), [])
        self.assertFalse(fm.retirer(self.racine, "forge"))

    def test_the_real_merge_gives_the_overlay_the_last_word(self):
        """La fusion des manifestes, lancée comme en vrai : le remote
        redirigé prend le fetch de la forge, l'autre garde le sien, et les
        projets ne changent pas."""
        base = os.path.join(self.racine, "base.xml")
        with open(base, "w") as fh:
            fh.write(MANIFESTE)
        surcouche = fm.ecrire(
            self.racine, "forge", {"Amont": f"{BASE}/Amont/"}
        )
        sortie = os.path.join(self.racine, "fusion.xml")
        fini = subprocess.run(
            [
                sys.executable,
                str(FUSION),
                "--input",
                f"base.xml;{surcouche}",
                "--output",
                sortie,
            ],
            cwd=self.racine,
            capture_output=True,
            text=True,
            env=dict(os.environ, PYTHONPATH=str(RACINE)),
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        fusion = ET.parse(sortie).getroot()
        fetch = {
            e.get("name"): e.get("fetch") for e in fusion.findall("remote")
        }
        self.assertEqual(fetch["Amont"], f"{BASE}/Amont/")
        self.assertEqual(fetch["Autre"], "https://github.com/Autre/")
        self.assertEqual(
            sorted(
                (e.get("name"), e.get("remote"), e.get("revision"))
                for e in fusion.findall("project")
            ),
            [
                ("a.git", "Amont", "X.0"),
                ("b.git", "Amont", "X.0"),
                ("c.git", "Autre", "X.0"),
            ],
        )


class TestNonCouverts(Racine):
    def test_projects_of_a_redirected_remote_not_on_the_forge(self):
        base = os.path.join(self.racine, "base.xml")
        with open(base, "w") as fh:
            fh.write(MANIFESTE)
        self.assertEqual(
            fm.projets_non_couverts(
                {"Amont"}, {"a.git+odooX.0/a"}, sources=[base]
            ),
            {"b.git+odooX.0/b": "Amont"},
        )
        self.assertEqual(
            fm.projets_non_couverts(
                {"Amont"},
                {"a.git+odooX.0/a", "b.git+odooX.0/b"},
                sources=[base],
            ),
            {},
        )


class TestBaseDuRemote(Racine):
    def test_the_base_is_the_url_without_owner_and_repository(self):
        clone = os.path.join(self.racine, "a")
        subprocess.run(["git", "init", "-q", clone], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                clone,
                "remote",
                "add",
                "forge",
                f"{BASE}/Amont/a.git",
            ],
            check=True,
        )
        p = projet(clone, "a.git", "Amont", "Amont")
        self.assertEqual(fm.base_du_remote([p], "forge"), BASE)
        self.assertIsNone(fm.base_du_remote([p], "absent"))
        autre = dict(p, proprietaire="Autre")
        self.assertIsNone(fm.base_du_remote([autre], "forge"))


if __name__ == "__main__":
    unittest.main()
