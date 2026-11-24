#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`make open_test_coverage` : le rapport HTML qu'ouvre le navigateur.

Avec JEU, la cible produit le rapport du jeu de `script/test/couverture.py`
et ne lance le navigateur que si ce rapport existe ; sans JEU, elle ouvre
htmlcov/, qu'écrivent les cibles du générateur de code. Le navigateur est
remplacé par un script qui note ce qu'il reçoit, et le cache de couverture
vit dans un dossier jetable.
"""

import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import couverture  # noqa: E402

PYTHON = os.path.join(RACINE, ".venv.erplibre", "bin", "python")


def environnement():
    """L'environnement du test, sans JEU — que `ifdef JEU` lirait aussi —
    ni les variables d'un passage mesuré du lanceur, qui mesurerait sinon
    les processus lancés ici."""
    return {
        k: v
        for k, v in os.environ.items()
        if k != "JEU" and not k.startswith("COVERAGE")
    }


def recette(*variables):
    """La recette de open_test_coverage telle que make la lancerait."""
    return subprocess.run(
        ["make", "-n", "-s", "open_test_coverage", "BROWSER=NAVIGATEUR"]
        + list(variables),
        cwd=RACINE,
        env=environnement(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class Recette(unittest.TestCase):
    def test_without_a_set_it_opens_htmlcov(self):
        self.assertEqual(recette(), "NAVIGATEUR htmlcov/index.html")

    def test_with_a_set_it_opens_what_couverture_produces(self):
        cmd = recette("JEU=odoo")
        self.assertIn("script/test/couverture.py html --jeu odoo", cmd)
        # couverture.py en échec arrête la cible avant le navigateur.
        self.assertIn("|| exit 1;", cmd)
        self.assertIn('NAVIGATEUR "$index"', cmd)


@unittest.skipUnless(
    couverture.disponible("erplibre"),
    "coverage 7.10 ou plus absent de .venv.erplibre",
)
class Passage(unittest.TestCase):
    """La cible lancée pour vrai, sur un cache de couverture jetable.

    Le rapport HTML couvre tout le jeu erplibre, mesuré ou non : quelque
    70 Mo dans TMPDIR, souvent en mémoire. Les données sont donc mesurées
    une fois pour la classe ; chaque test a son navigateur."""

    @classmethod
    def setUpClass(cls):
        cls.commun = tempfile.mkdtemp()
        cache = os.path.join(cls.commun, "cache")
        cls.donnees = os.path.join(cache, "erplibre", "couverture", "erplibre")
        os.makedirs(os.path.join(cls.donnees, "donnees"))
        env = dict(
            environnement(),
            XDG_CACHE_HOME=cache,
            COVERAGE_FILE=os.path.join(cls.donnees, "donnees", ".coverage"),
        )
        rc = os.path.join(RACINE, "conf", "coverage.erplibre.toml")
        try:
            for cmd in (
                [PYTHON, "-m", "coverage", "run", "-p", f"--rcfile={rc}"]
                + ["script/test/couverture.py", "historique"],
                [PYTHON, "script/test/couverture.py", "combiner"],
            ):
                subprocess.run(
                    cmd, cwd=RACINE, env=env, check=True, capture_output=True
                )
        except BaseException:
            shutil.rmtree(cls.commun, ignore_errors=True)
            raise
        cls.cache_mesure = cache
        cls.index = os.path.join(cls.donnees, "html", "index.html")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.commun, ignore_errors=True)

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.recu = os.path.join(self.dossier, "recu")
        self.navigateur = os.path.join(self.dossier, "navigateur")
        self.ecrire_navigateur(0)

    def ecrire_navigateur(self, code):
        """Un navigateur qui note le chemin reçu, puis sort en `code`."""
        with open(self.navigateur, "w", encoding="utf-8") as fh:
            fh.write(f'#!/bin/sh\nprintf %s "$1" > {self.recu}\nexit {code}\n')
        os.chmod(self.navigateur, stat.S_IRWXU)

    def ouvrir(self, cache):
        return subprocess.run(
            [
                "make",
                "-s",
                "open_test_coverage",
                "JEU=erplibre",
                f"BROWSER={self.navigateur}",
            ],
            cwd=RACINE,
            env=dict(environnement(), XDG_CACHE_HOME=cache),
            capture_output=True,
            text=True,
        )

    def test_no_data_opens_nothing_and_says_why(self):
        res = self.ouvrir(os.path.join(self.dossier, "vide"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("No data to report", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertFalse(os.path.exists(self.recu))

    def test_measured_data_opens_the_set_report(self):
        res = self.ouvrir(self.cache_mesure)
        self.assertEqual(res.returncode, 0, res.stderr)
        with open(self.recu, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.index)
        self.assertTrue(os.path.isfile(self.index))
        self.assertIn(self.index, res.stdout)

    def test_a_failing_browser_still_shows_the_report_path(self):
        """Sans affichage (ssh, CI), le navigateur échoue : le rapport est
        produit, son chemin s'affiche, et la cible réussit comme sans JEU."""
        self.ecrire_navigateur(1)
        res = self.ouvrir(self.cache_mesure)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(self.index, res.stdout)


class Erreur(unittest.TestCase):
    def test_a_coverage_failure_is_one_line_not_a_traceback(self):
        sortie = io.StringIO()
        with mock.patch.object(
            couverture,
            "produire_html",
            side_effect=RuntimeError("No data to report."),
        ):
            with redirect_stderr(sortie):
                code = couverture.main(["html"])
        self.assertEqual(code, 1)
        self.assertEqual(
            sortie.getvalue(), "couverture.py html : No data to report.\n"
        )

    def test_a_missing_interpreter_is_one_line_not_a_traceback(self):
        """Le venv d'un jeu absent, ou celui d'Odoo quand la version a
        changé : subprocess lèverait FileNotFoundError."""
        absent = os.path.join(tempfile.mkdtemp(), "python")
        self.addCleanup(shutil.rmtree, os.path.dirname(absent))
        jeu = couverture.jeu("erplibre")
        jeu.python = absent
        sortie = io.StringIO()
        with mock.patch.object(couverture, "jeu", return_value=jeu):
            with redirect_stderr(sortie):
                code = couverture.main(["html"])
        self.assertEqual(code, 1)
        self.assertEqual(
            sortie.getvalue(),
            f"couverture.py html : pas d'interpréteur pour le jeu erplibre"
            f" : {absent}\n",
        )


if __name__ == "__main__":
    unittest.main()
