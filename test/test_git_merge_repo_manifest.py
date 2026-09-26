#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fusion des manifests Google Repo : qui gagne, et qui entre.

Le script lit ses listes (conf/*.csv, private/default_git_manifest.csv) par
chemins relatifs au répertoire courant ; il est donc lancé comme en vrai, en
sous-processus, depuis une racine jetable.

Deux propriétés gardées :
- l'ordre des manifests est celui des listes : private/ est lu en dernier et
  l'emporte, quel que soit PYTHONHASHSEED (un ensemble le rendait aléatoire) ;
- le projet Dolibarr entre dans la fusion avec --with_dolibarr, ou d'office
  quand son checkout existe. Sorti de la fusion, il serait effacé par le
  prochain « repo sync », conf.php compris.
"""

import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script" / "git" / "git_merge_repo_manifest.py"

# Commits inventés.
PIN_A = "a" * 40
PIN_B = "b" * 40


def manifest(revision, upstream="24.0"):
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Dolibarr" fetch="https://github.com/Dolibarr/" />
    <project
        name="dolibarr.git"
        path="dolibarr/dolibarr"
        remote="Dolibarr"
        revision="{revision}"
        upstream="{upstream}"
        dest-branch="{upstream}"
        clone-depth="1"
        groups="dolibarr"
    />
</manifest>
"""


class Racine:
    """Une racine de dépôt jetable où lancer le script."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("conf", "manifest", "private", ".repo/local_manifests"):
            (self.root / d).mkdir(parents=True)
        (self.root / "manifest/git_manifest_erplibre.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8" ?>\n<manifest />\n'
        )

    def ecrire(self, rel, texte):
        chemin = self.root / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(texte)

    def liste(self, rel, *manifests):
        self.ecrire(rel, '"filepath"\n' + "".join(m + "\n" for m in manifests))

    def fusionner(self, *args, seed="0"):
        env = dict(os.environ, PYTHONPATH=str(RACINE), PYTHONHASHSEED=seed)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        sortie = self.root / "out.xml"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(sortie), *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        projets = ET.parse(sortie).getroot().findall("project")
        return {p.get("path"): p for p in projets}

    def close(self):
        self.tmp.cleanup()


class Banc(unittest.TestCase):
    def setUp(self):
        self.racine = Racine()
        self.addCleanup(self.racine.close)


class TestOrdreDeFusion(Banc):
    def test_the_last_listed_manifest_wins_whatever_the_hash_seed(self):
        r = self.racine
        r.ecrire("manifest/pin_a.xml", manifest(PIN_A))
        r.ecrire("manifest/pin_b.xml", manifest(PIN_B))
        r.liste(
            "private/default_git_manifest.csv",
            "manifest/pin_a.xml",
            "manifest/pin_b.xml",
        )
        for seed in ("0", "1", "2", "3", "4", "5"):
            with self.subTest(seed=seed):
                projets = r.fusionner(seed=seed)
                self.assertEqual(
                    projets["dolibarr/dolibarr"].get("revision"), PIN_B
                )


class TestProjetDolibarr(Banc):
    def setUp(self):
        super().setUp()
        self.racine.ecrire(
            "manifest/git_manifest_dolibarr.xml", manifest(PIN_A)
        )
        self.racine.liste(
            "conf/git_manifest_dolibarr.csv",
            "manifest/git_manifest_erplibre.xml",
            "manifest/git_manifest_dolibarr.xml",
        )

    def test_it_stays_out_without_the_flag_or_a_checkout(self):
        self.assertNotIn("dolibarr/dolibarr", self.racine.fusionner())

    def test_the_flag_merges_it_with_its_pin_and_branch(self):
        projet = self.racine.fusionner("--with_dolibarr")["dolibarr/dolibarr"]
        self.assertEqual(projet.get("revision"), PIN_A)
        self.assertEqual(projet.get("upstream"), "24.0")
        self.assertEqual(projet.get("clone-depth"), "1")

    def test_an_existing_checkout_keeps_it_in_the_merge(self):
        # Sorti de la fusion, le prochain « repo sync » effacerait le
        # checkout, conf.php compris : il y reste dès qu'il existe.
        (self.racine.root / "dolibarr" / "dolibarr").mkdir(parents=True)
        self.assertIn("dolibarr/dolibarr", self.racine.fusionner())


if __name__ == "__main__":
    unittest.main()
