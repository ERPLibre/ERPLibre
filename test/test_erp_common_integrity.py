#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Intégrité d'un code exporté (script/erp_common/integrity).

Un vrai dépôt git est créé ici, puis « exporté » à la main comme le fait
`git archive` : ce qu'il exporte fait foi, export-ignore compris. Ce qui se
garde :
- un fichier modifié, absent ou AJOUTÉ hors du dossier de modules est
  signalé : un fichier inconnu dans le code est la forme d'un web shell ;
- un fichier illisible, ou un dossier, est « unreadable », jamais sauté ni
  « missing » ;
- les fichiers que l'appelant dit posés par l'installation ne sont pas des
  écarts ; les sous-dossiers du dossier de modules se listent à part.
Chaque test tourne pour deux dispositions : celle de Dolibarr et une
inventée, pour prouver que rien n'est écrit en dur.
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

from script.erp_common import integrity  # noqa: E402

# Disposition d'un ERP : racine du code, fichiers posés par l'installation,
# dossier de modules.
LAYOUTS = {
    "dolibarr": (
        "htdocs",
        {"htdocs/conf/conf.php", "htdocs/install.lock"},
        "htdocs/custom/",
    ),
    "acme": ("app", {"app/site.cfg"}, "app/modules/"),
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
    """Un dépôt et son export, construits pour la disposition `erp`."""

    def banc(self, erp):
        top, installed, custom = LAYOUTS[erp]
        self.installed, self.custom, self.top = installed, custom, top
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.depot = Path(tmp.name, "depot")
        self.code = Path(tmp.name, "opt", "erp")
        fichiers = {
            f"{top}/index.php": "<?php echo 1;\n",
            f"{top}/main.inc.php": "<?php\n",
            f"{top}/core/lib/a.lib.php": "<?php function a() {}\n",
            "scripts/cron/cron_run_jobs.php": "#!/usr/bin/env php\n<?php\n",
            # Livré par l'ERP lui-même, à la racine du dossier de modules.
            f"{custom}README.md": "# custom\n",
        }
        for chemin, texte in fichiers.items():
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

    def comparer(self, **kw):
        kw.setdefault("installed", self.installed)
        kw.setdefault("custom", self.custom)
        blobs = integrity.archive_blobs(str(self.depot), self.commit)
        return integrity.compare_tree(str(self.code), blobs, **kw)

    def each(self):
        """Itère sur les dispositions, banc reconstruit pour chacune."""
        for erp in LAYOUTS:
            with self.subTest(erp=erp):
                self.banc(erp)
                yield erp


class TestEmpreinte(unittest.TestCase):
    def test_a_file_hashes_like_its_git_blob(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("<?php echo 1;\n")
        self.addCleanup(os.unlink, f.name)
        attendu = hashlib.sha1(b"blob 14\x00<?php echo 1;\n").hexdigest()
        self.assertEqual(integrity.blob_hash(f.name), attendu)


class TestComparaison(Banc):
    def test_an_intact_export_has_no_difference(self):
        for _erp in self.each():
            ecart = self.comparer()
            self.assertEqual(
                (ecart["modified"], ecart["missing"], ecart["added"]),
                ([], [], []),
            )

    def test_a_modified_core_file_is_reported(self):
        for _erp in self.each():
            rel = f"{self.top}/core/lib/a.lib.php"
            (self.code / rel).write_text("<?php evil();\n")
            self.assertEqual(self.comparer()["modified"], [rel])

    def test_a_missing_file_is_reported(self):
        for _erp in self.each():
            rel = f"{self.top}/index.php"
            (self.code / rel).unlink()
            self.assertEqual(self.comparer()["missing"], [rel])

    def test_an_added_file_outside_custom_is_reported(self):
        for _erp in self.each():
            rel = f"{self.top}/core/shell.php"
            (self.code / rel).write_text("<?php system($_GET[0]);\n")
            self.assertEqual(self.comparer()["added"], [rel])

    def test_what_the_install_writes_is_not_a_difference(self):
        for _erp in self.each():
            for rel in self.installed:
                f = self.code / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("")
            self.assertEqual(self.comparer()["added"], [])
            # Sans la liste de l'appelant, ils sont des ajouts.
            self.assertEqual(
                self.comparer(installed=())["added"], sorted(self.installed)
            )

    def test_custom_modules_are_listed_apart(self):
        for _erp in self.each():
            module = self.code / f"{self.custom}monmodule/core/modules"
            module.mkdir(parents=True)
            (module / "modMonModule.class.php").write_text("<?php\n")
            ecart = self.comparer()
            self.assertEqual(ecart["added"], [])
            self.assertEqual(ecart["custom"], ["monmodule"])

    def test_files_shipped_in_custom_are_checked(self):
        for _erp in self.each():
            rel = f"{self.custom}README.md"
            (self.code / rel).write_text("autre\n")
            ecart = self.comparer()
            self.assertEqual(ecart["modified"], [rel])
            self.assertEqual(ecart["custom"], [])

    def test_without_a_module_directory_everything_is_checked(self):
        for _erp in self.each():
            module = self.code / f"{self.custom}monmodule"
            module.mkdir(parents=True)
            (module / "x.php").write_text("<?php\n")
            ecart = self.comparer(custom=None)
            self.assertEqual(ecart["added"], [f"{self.custom}monmodule/x.php"])
            self.assertEqual(ecart["custom"], [])

    def test_an_unreadable_file_is_reported_not_skipped(self):
        for _erp in self.each():
            rel = f"{self.top}/main.inc.php"
            f = self.code / rel
            f.chmod(0)
            self.addCleanup(f.chmod, 0o644)
            self.assertEqual(self.comparer()["unreadable"], [rel])


class TestDossierIllisible(Banc):
    def test_an_unreadable_directory_is_unreadable_not_missing(self):
        for _erp in self.each():
            d = self.code / f"{self.top}/core"
            d.chmod(0)
            self.addCleanup(d.chmod, 0o755)
            ecart = self.comparer()
            self.assertEqual(ecart["unreadable"], [f"{self.top}/core/"])
            self.assertEqual(ecart["missing"], [])


class TestCommit(Banc):
    def test_an_unknown_commit_is_refused(self):
        self.banc("acme")
        with self.assertRaises(integrity.IntegrityError):
            integrity.archive_blobs(str(self.depot), "0" * 40)


if __name__ == "__main__":
    unittest.main()
