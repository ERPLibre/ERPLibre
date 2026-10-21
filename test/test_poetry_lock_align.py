#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Alignement sur poetry.lock des paquets que Poetry amène dans son venv.

Poetry remplaçait virtualenv pendant l'installation parallèle, alors que ses
ouvriers s'en servaient pour compiler : un fichier supprimé faisait échouer
une compilation au hasard. Les paquets installés que le verrou épingle
autrement sont désormais posés à la version du verrou avant poetry install.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.poetry import poetry_lock_align as p  # noqa: E402

VERROU = """
[[package]]
name = "virtualenv"
version = "21.3.1"

[[package]]
name = "Pkg_Info"
version = "1.12.0"

[[package]]
name = "factur-x"
version = "3.16"

[[package]]
name = "factur-x"
version = "7.6"
"""


class TestAlignement(unittest.TestCase):
    def setUp(self):
        fichier = tempfile.NamedTemporaryFile(
            "w", suffix=".lock", delete=False
        )
        fichier.write(VERROU)
        fichier.close()
        self.chemin = fichier.name
        self.addCleanup(Path(self.chemin).unlink)

    def test_a_package_poetry_brought_at_another_version(self):
        verrou = p.versions_du_verrou(self.chemin)
        self.assertEqual(
            ["virtualenv==21.3.1"],
            p.a_aligner(["virtualenv==20.39.1"], verrou),
        )

    def test_names_are_compared_normalised(self):
        verrou = p.versions_du_verrou(self.chemin)
        self.assertEqual(
            ["pkg-info==1.12.0"], p.a_aligner(["pkg-info==1.11.0"], verrou)
        )

    def test_already_aligned_or_unknown_packages_are_left(self):
        verrou = p.versions_du_verrou(self.chemin)
        self.assertEqual(
            [],
            p.a_aligner(["virtualenv==21.3.1", "inconnu==1.0"], verrou),
        )

    def test_a_package_with_several_versions_is_left_to_poetry(self):
        """Versions distinctes selon un marqueur : seul Poetry sait
        laquelle s'applique ici."""
        verrou = p.versions_du_verrou(self.chemin)
        self.assertEqual([], p.a_aligner(["factur-x==1.0"], verrou))

    def test_the_command_line_reads_pip_freeze(self):
        res = subprocess.run(
            [sys.executable, str(RACINE / "script/poetry/poetry_lock_align.py"),
             self.chemin],
            input="virtualenv==20.39.1\nautre==1.0\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual("virtualenv==21.3.1\n", res.stdout, res.stderr)


class TestContraintes(unittest.TestCase):
    """Le fichier de contraintes laisse pip résoudre les dépendances des
    paquets alignés, mais aux seules versions du verrou : virtualenv 21
    réclame python-discovery, que « --no-deps » laissait manquer."""

    def test_constraints_list_every_single_version_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            verrou = Path(tmp, "poetry.lock")
            verrou.write_text(VERROU, encoding="utf-8")
            contraintes = Path(tmp, "contraintes.txt")
            res = subprocess.run(
                [
                    sys.executable,
                    str(RACINE / "script/poetry/poetry_lock_align.py"),
                    "--contraintes",
                    str(contraintes),
                    str(verrou),
                ],
                input="virtualenv==20.39.1\n",
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual("virtualenv==21.3.1\n", res.stdout, res.stderr)
            self.assertEqual(
                ["pkg-info==1.12.0", "virtualenv==21.3.1"],
                contraintes.read_text(encoding="utf-8").split(),
            )


class TestInstallLocally(unittest.TestCase):
    def test_alignment_runs_before_poetry_install(self):
        source = (RACINE / "script/install/install_locally.sh").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index("poetry_lock_align.py"),
            source.index("install --no-root ${POETRY_VERBOSE}"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)
