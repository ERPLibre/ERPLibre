#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/git/hooks/post-checkout : avertit quand un changement de commit
a écrit par-dessus le clone de l'extension GNOME, ou l'a vidé.

Chaque test pose un faux ERPLibre : un commit « avant » qui suit encore
script/gnome-extension/erplibre_home/, un commit « apres » qui l'ignore,
et un clone d'un dépôt d'extension à ce chemin. Les extractions passent
par le vrai hook (core.hooksPath).

Ce que ces tests gardent :

- extraire un commit qui suit le chemin écrit ses versions sur le clone,
  et le hook le dit, avec la commande qui le restaure ;
- revenir sur un commit qui ne le suit plus supprime les fichiers du
  clone, le hook nomme la commande, et elle les ramène tels quels ;
- entre deux commits qui ne suivent pas le chemin, une modification du
  clone ne déclenche rien ;
- le hook est un script bash exécutable et valide.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
HOOKS = RACINE / "script/git/hooks"
HOOK = HOOKS / "post-checkout"
EXT = "script/gnome-extension/erplibre_home"
IDENTITE = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]
SANS_HOOK = ["-c", "core.hooksPath=/dev/null"]
RESTAURER = "git -C %s checkout -- ." % EXT


def git(depot, *args):
    return subprocess.run(
        ["git", "-C", str(depot), *IDENTITE, *SANS_HOOK, *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@unittest.skipUnless(shutil.which("git"), "git absent")
class LeHook(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.depot = self.tmp / "erplibre"
        self.ext = self.depot / EXT
        git(self.tmp, "init", "-q", "-b", "main", str(self.depot))
        self.ext.mkdir(parents=True)
        (self.ext / "extension.js").write_text("ancienne\n")
        git(self.depot, "add", EXT)
        git(self.depot, "commit", "-q", "-m", "avant")
        git(self.depot, "branch", "avant")
        git(self.depot, "rm", "-r", "-q", "--cached", EXT)
        (self.depot / ".gitignore").write_text("/%s/\n" % EXT)
        git(self.depot, "add", ".gitignore")
        git(self.depot, "commit", "-q", "-m", "apres")
        shutil.rmtree(self.ext)
        source = self.tmp / "ext.git"
        git(self.tmp, "init", "-q", "-b", "main", str(source))
        (source / "extension.js").write_text("actuelle\n")
        (source / "metadata.json").write_text("{}\n")
        git(source, "add", "-A")
        git(source, "commit", "-q", "-m", "un")
        git(self.tmp, "clone", "-q", str(source), str(self.ext))

    def extraire(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.depot), "-c"]
            + ["core.hooksPath=%s" % HOOKS, "checkout", "-q", *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_a_commit_that_tracks_the_path_overwrites_and_warns(self):
        fini = self.extraire("avant")
        self.assertEqual("ancienne\n", (self.ext / "extension.js").read_text())
        self.assertIn("this commit tracks it", fini.stderr)
        self.assertIn("git worktree add", fini.stderr)
        self.assertIn(RESTAURER, fini.stderr)

    def test_coming_back_names_the_restore_and_it_works(self):
        self.extraire("avant")
        fini = self.extraire("main")
        self.assertFalse((self.ext / "extension.js").exists())
        self.assertIn("the previous commit tracked it", fini.stderr)
        self.assertIn(RESTAURER, fini.stderr)
        subprocess.run(RESTAURER.split(), cwd=self.depot, check=True)
        self.assertEqual("actuelle\n", (self.ext / "extension.js").read_text())
        self.assertEqual(
            "", git(self.ext, "status", "--porcelain", "--untracked-files=no")
        )

    def test_commits_that_do_not_track_it_leave_local_work_alone(self):
        git(self.depot, "commit", "-q", "--allow-empty", "-m", "suite")
        (self.ext / "extension.js").write_text("modifiée\n")
        fini = self.extraire("HEAD~1")
        self.assertEqual("", fini.stderr)
        fini = self.extraire("main")
        self.assertEqual("", fini.stderr)
        self.assertEqual("modifiée\n", (self.ext / "extension.js").read_text())

    def test_it_is_an_executable_valid_bash_script(self):
        self.assertTrue(os.access(HOOK, os.X_OK))
        fini = subprocess.run(
            ["bash", "-n", str(HOOK)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


if __name__ == "__main__":
    unittest.main()
