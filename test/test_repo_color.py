#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La couleur de repo, réglée d'avance pour que « repo init » ne demande rien.

Sur un terminal, « repo init » pose « Enable color display in this user
account (y/N)? » tant que la config git de l'utilisateur ne porte aucune
clé color.ui, color.diff ou color.status. Ces tests gardent :

- script/manifest/repo_color.sh écrit color.ui = auto, la valeur de la
  réponse « y », dans le fichier que lit repo : la config XDG quand elle
  existe, ~/.gitconfig sinon ;
- un choix déjà présent, même venu d'un fichier inclus, reste intact ;
- chaque script de script/manifest/ appelle le fragment avant « repo init ».

Chaque test tourne sur un HOME temporaire : la config de qui lance les tests
n'est jamais lue ni écrite.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
FRAGMENT = RACINE / "script/manifest/repo_color.sh"
SCRIPTS = sorted((RACINE / "script/manifest").glob("update_manifest_*.sh"))


class TestRepoColorDefault(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"
        }
        self.env["HOME"] = str(self.home)
        self.gitconfig = self.home / ".gitconfig"
        self.xdg = self.home / ".config/git/config"

    def tearDown(self):
        self._tmp.cleanup()

    def _lancer(self):
        done = subprocess.run(
            ["bash", "-c", f'. "{FRAGMENT}" && repo_color_default'],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def _lire(self, fichier, cle):
        done = subprocess.run(
            ["git", "config", "--file", str(fichier), "--get", cle],
            env=self.env,
            capture_output=True,
            text=True,
        )
        return done.stdout.strip() if done.returncode == 0 else None

    def test_config_absente_cree_gitconfig(self):
        self._lancer()
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "auto")

    def test_choix_existant_respecte(self):
        self.gitconfig.write_text("[color]\n\tui = never\n")
        self._lancer()
        self.assertEqual(self._lire(self.gitconfig, "color.ui"), "never")

    def test_color_diff_suffit(self):
        self.gitconfig.write_text("[color]\n\tdiff = false\n")
        self._lancer()
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))

    def test_config_xdg_prioritaire(self):
        self.xdg.parent.mkdir(parents=True)
        self.xdg.write_text("[user]\n\tname = Test\n")
        self.gitconfig.write_text("[core]\n\tpager = less\n")
        self._lancer()
        self.assertEqual(self._lire(self.xdg, "color.ui"), "auto")
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))

    def test_xdg_config_home_respecte(self):
        ailleurs = self.home / "ailleurs"
        (ailleurs / "git").mkdir(parents=True)
        (ailleurs / "git/config").write_text("")
        self.env["XDG_CONFIG_HOME"] = str(ailleurs)
        self._lancer()
        self.assertEqual(self._lire(ailleurs / "git/config", "color.ui"), "auto")
        self.assertFalse(self.gitconfig.exists())

    def test_inclusion_suivie(self):
        inclus = self.home / "inclus.conf"
        inclus.write_text("[color]\n\tstatus = false\n")
        self.gitconfig.write_text(f"[include]\n\tpath = {inclus}\n")
        self._lancer()
        self.assertIsNone(self._lire(self.gitconfig, "color.ui"))


class TestScriptsDeManifeste(unittest.TestCase):
    def test_couleur_reglee_avant_repo_init(self):
        self.assertEqual(len(SCRIPTS), 6, [s.name for s in SCRIPTS])
        for script in SCRIPTS:
            texte = script.read_text(encoding="utf-8")
            with self.subTest(script=script.name):
                init = re.search(r"^[ \t]*[^#\n]*repo init ", texte, re.M)
                appel = re.search(r"^[ \t]*repo_color_default$", texte, re.M)
                source = texte.find(". ./script/manifest/repo_color.sh")
                self.assertTrue(init and appel and source >= 0)
                self.assertLess(source, appel.start())
                self.assertLess(appel.start(), init.start())


if __name__ == "__main__":
    unittest.main()
