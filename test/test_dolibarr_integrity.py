#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'intégrité d'un code Dolibarr exporté, contre son commit épinglé.

Un vrai dépôt git est créé ici, puis « exporté » à la main comme le fait
`git archive` : ce qu'il exporte fait foi, export-ignore compris. Ce qui se garde :
- un fichier modifié, absent ou AJOUTÉ hors custom/ est signalé : un PHP
  inconnu dans le code est la forme d'un web shell ;
- conf.php et install.lock, posés par l'installation, ne sont pas des
  écarts ; custom/ se liste à part, ses modules sont voulus.
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import integrity  # noqa: E402

FICHIERS = {
    "htdocs/index.php": "<?php echo 1;\n",
    "htdocs/main.inc.php": "<?php\n",
    "htdocs/core/lib/a.lib.php": "<?php function a() {}\n",
    "scripts/cron/cron_run_jobs.php": "#!/usr/bin/env php\n<?php\n",
    # Livré par Dolibarr lui-même, à la racine de custom/.
    "htdocs/custom/README.md": "# custom\n",
}


def git(depot, *args):
    return subprocess.run(
        ["git", "-C", str(depot), *args],
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
            "PATH": os.environ["PATH"],
            "HOME": str(depot),
        },
    ).stdout.strip()


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.depot = Path(tmp.name, "depot")
        self.code = Path(tmp.name, "opt", "erp")
        for chemin, texte in FICHIERS.items():
            for base in (self.depot, self.code):
                f = base / chemin
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(texte)
        # Ce que `git archive` écarte n'est pas exporté : pas un manque.
        (self.depot / "doc").mkdir()
        (self.depot / "doc/guide.md").write_text("# guide\n")
        (self.depot / ".gitattributes").write_text(
            "/doc export-ignore\n.gitattributes export-ignore\n"
        )
        git(self.depot, "init", "-q")
        git(self.depot, "add", ".")
        git(self.depot, "commit", "-q", "-m", "x")
        self.commit = git(self.depot, "rev-parse", "HEAD")

    def comparer(self):
        blobs = integrity.archive_blobs(str(self.depot), self.commit)
        return integrity.compare_tree(str(self.code), blobs)


class TestEmpreinte(unittest.TestCase):
    def test_a_file_hashes_like_its_git_blob(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("<?php echo 1;\n")
        self.addCleanup(os.unlink, f.name)
        attendu = hashlib.sha1(b"blob 14\x00<?php echo 1;\n").hexdigest()
        self.assertEqual(integrity.blob_hash(f.name), attendu)


class TestComparaison(Banc):
    def test_an_intact_export_has_no_difference(self):
        ecart = self.comparer()
        self.assertEqual(
            (ecart["modified"], ecart["missing"], ecart["added"]), ([], [], [])
        )

    def test_a_modified_core_file_is_reported(self):
        (self.code / "htdocs/core/lib/a.lib.php").write_text("<?php evil();\n")
        self.assertEqual(
            self.comparer()["modified"], ["htdocs/core/lib/a.lib.php"]
        )

    def test_a_missing_file_is_reported(self):
        (self.code / "htdocs/index.php").unlink()
        self.assertEqual(self.comparer()["missing"], ["htdocs/index.php"])

    def test_an_added_php_file_outside_custom_is_reported(self):
        (self.code / "htdocs/core/shell.php").write_text(
            "<?php system($_GET[0]);\n"
        )
        self.assertEqual(self.comparer()["added"], ["htdocs/core/shell.php"])

    def test_what_the_install_writes_is_not_a_difference(self):
        (self.code / "htdocs/conf").mkdir()
        (self.code / "htdocs/conf/conf.php").write_text("<?php\n")
        (self.code / "htdocs/install.lock").write_text("")
        self.assertEqual(self.comparer()["added"], [])

    def test_custom_modules_are_listed_apart(self):
        module = self.code / "htdocs/custom/monmodule/core/modules"
        module.mkdir(parents=True)
        (module / "modMonModule.class.php").write_text("<?php\n")
        ecart = self.comparer()
        self.assertEqual(ecart["added"], [])
        self.assertEqual(ecart["custom"], ["monmodule"])

    def test_files_dolibarr_ships_in_custom_are_checked(self):
        (self.code / "htdocs/custom/README.md").write_text("autre\n")
        ecart = self.comparer()
        self.assertEqual(ecart["modified"], ["htdocs/custom/README.md"])
        self.assertEqual(ecart["custom"], [])

    def test_an_unreadable_file_is_reported_not_skipped(self):
        f = self.code / "htdocs/main.inc.php"
        f.chmod(0)
        self.addCleanup(f.chmod, 0o644)
        self.assertEqual(
            self.comparer()["unreadable"], ["htdocs/main.inc.php"]
        )


class TestDossierIllisible(Banc):
    def test_an_unreadable_directory_is_unreadable_not_missing(self):
        d = self.code / "htdocs/core"
        d.chmod(0)
        self.addCleanup(d.chmod, 0o755)
        ecart = self.comparer()
        self.assertEqual(ecart["unreadable"], ["htdocs/core/"])
        self.assertEqual(ecart["missing"], [])


class TestCommit(Banc):
    def test_an_unknown_commit_is_refused(self):
        with self.assertRaises(integrity.IntegrityError):
            integrity.archive_blobs(str(self.depot), "0" * 40)


if __name__ == "__main__":
    unittest.main()
