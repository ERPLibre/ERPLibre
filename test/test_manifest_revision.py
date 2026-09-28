#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La révision que les scripts de manifeste passent à « repo init -b ».

« repo init -b <sha> » échoue sur un espace de travail neuf ; un .repo déjà
initialisé l'accepte, si bien que le défaut ne se voit que sur une
installation neuve. Ces tests gardent :

- script/manifest/manifest_revision.sh rend une branche : celle qui est
  extraite, ou sur un HEAD détaché une branche qui contient le commit, et
  rend 1 sans rien écrire sur stdout quand aucune ne le contient ;
- aucun script de script/manifest/ ne passe plus de SHA à « repo init » :
  tous résolvent la révision par ce fragment, et les scripts qui lancent un
  démon git la résolvent AVANT lui, pour qu'une sortie ne le laisse pas
  tourner.
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FRAGMENT = RACINE / "script/manifest/manifest_revision.sh"
SCRIPTS = sorted((RACINE / "script/manifest").glob("update_manifest_*.sh"))


def _git(depot, *args):
    return subprocess.run(
        ["git", "-C", str(depot), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _revision(depot):
    """(code, stdout, stderr) de manifest_revision lancé dans `depot`."""
    done = subprocess.run(
        ["bash", "-c", f'. "{FRAGMENT}" && manifest_revision'],
        cwd=depot,
        capture_output=True,
        text=True,
    )
    return done.returncode, done.stdout.strip(), done.stderr


class TestManifestRevision(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.depot = Path(self._tmp.name)
        _git(self.depot, "init", "-q", "-b", "fictive_main")
        _git(self.depot, "config", "user.email", "test@example.invalid")
        _git(self.depot, "config", "user.name", "Test")
        _git(self.depot, "config", "commit.gpgsign", "false")
        _git(self.depot, "commit", "-q", "--allow-empty", "-m", "un")

    def tearDown(self):
        self._tmp.cleanup()

    def test_branche_extraite(self):
        self.assertEqual(_revision(self.depot), (0, "fictive_main", ""))

    def test_tete_detachee_dans_une_branche(self):
        _git(self.depot, "checkout", "-q", "--detach")
        code, rev, _ = _revision(self.depot)
        self.assertEqual((code, rev), (0, "fictive_main"))

    def test_commit_hors_de_toute_branche(self):
        _git(self.depot, "checkout", "-q", "--detach")
        _git(self.depot, "commit", "-q", "--allow-empty", "-m", "orphelin")
        code, rev, err = _revision(self.depot)
        self.assertEqual((code, rev), (1, ""))
        self.assertIn("aucune branche ne contient ce commit", err)


class TestScriptsDeManifeste(unittest.TestCase):
    def test_les_sept_scripts_sont_vus(self):
        self.assertEqual(len(SCRIPTS), 7, [s.name for s in SCRIPTS])

    def test_aucun_sha_passe_a_repo_init(self):
        for script in SCRIPTS:
            texte = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                inits = re.findall(r"^[^#\n]*repo init .*$", texte, re.M)
                self.assertTrue(inits)
                for ligne in inits:
                    self.assertIn('-b "${MANIFEST_REV}"', ligne)
                # Un refus est TRAITÉ : il sort, ou s'ajoute aux gardes
                # d'un script qui les fait toutes parler avant de sortir.
                self.assertRegex(
                    texte, r"MANIFEST_REV=\$\(manifest_revision\) \|\| \S"
                )

    def test_revision_resolue_avant_le_demon(self):
        for script in SCRIPTS:
            texte = script.read_text(encoding="utf-8")
            demon = re.search(r"^git daemon ", texte, re.M)
            if not demon:
                continue
            with self.subTest(script=script.name):
                piege = re.search(r"^trap .*EXIT", texte, re.M)
                if piege and piege.start() < texte.index("manifest_revision)"):
                    continue
                self.assertLess(
                    texte.index("MANIFEST_REV=$(manifest_revision)"),
                    demon.start(),
                )


if __name__ == "__main__":
    unittest.main()
