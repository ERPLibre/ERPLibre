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
La comparaison vient de script/erp_common/integrity et s'éprouve dans
test_erp_common_integrity ; ici, sa liaison aux chemins de Dolibarr.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import integrity  # noqa: E402
from script.erp_common import integrity as common_integrity  # noqa: E402

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


class TestWiring(unittest.TestCase):
    """La mécanique vient de script/erp_common/integrity, liée à Dolibarr."""

    def test_the_mechanism_is_the_shared_one(self):
        for name in ("IntegrityError", "archive_blobs", "blob_hash"):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(integrity, name), getattr(common_integrity, name)
                )


class TestComparaison(Banc):
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


if __name__ == "__main__":
    unittest.main()
