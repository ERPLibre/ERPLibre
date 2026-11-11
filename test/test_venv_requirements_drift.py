#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""script/poetry/venv_requirements_drift.py : un venv face à ses
exigences pip, sans lock.

Les distributions sont factices : un nom, une version et des dépendances
déclarées, comme importlib.metadata les rend. Un test lance aussi le
script pour de vrai, avec l'interpréteur des tests."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from script.poetry import venv_requirements_drift as vrd

RACINE = Path(__file__).resolve().parents[1]


def dist(nom, version, *requires):
    return SimpleNamespace(
        metadata={"Name": nom}, version=version, requires=list(requires)
    )


class TestAnalyser(unittest.TestCase):
    def analyser(self, lignes, *dists):
        return vrd.analyser(lignes, list(dists))

    def test_manquante_hors_bornes_et_de_trop(self):
        etat = self.analyser(
            ["requests>=2", "black==26.10.1", "absent"],
            dist("requests", "2.32.3", "idna>=2"),
            dist("idna", "3.7"),
            dist("black", "25.1.0"),
            dist("ajoute-a-la-main", "0.1"),
            dist("pip", "26.0"),
        )
        self.assertEqual(etat["manquantes"], ["absent"])
        self.assertEqual(
            etat["hors_bornes"],
            [{"exigence": "black==26.10.1", "installee": "25.1.0"}],
        )
        # idna vient de requests ; pip outille le venv : ni l'un ni l'autre
        # n'est de trop.
        self.assertEqual(etat["de_trop"], [["ajoute-a-la-main", "0.1"]])

    def test_les_extras_et_les_marqueurs_sont_suivis(self):
        etat = self.analyser(
            ["outil[securite]"],
            dist(
                "outil",
                "1.0",
                'crypto>=1; extra == "securite"',
                'jamais; extra == "autre"',
                'windows-seul; sys_platform == "win32"',
            ),
            dist("crypto", "2.0"),
            dist("jamais", "1.0"),
        )
        self.assertEqual(etat["de_trop"], [["jamais", "1.0"]])

    def test_une_exigence_hors_de_sa_plateforme_ne_manque_pas(self):
        etat = self.analyser(['pywin32; sys_platform == "win32"'])
        self.assertEqual(etat["manquantes"], [])

    def test_les_noms_se_comparent_normalises(self):
        etat = self.analyser(["GitPython>=3"], dist("gitpython", "3.2.1"))
        self.assertEqual((etat["manquantes"], etat["de_trop"]), ([], []))


class TestLireExigences(unittest.TestCase):
    def test_commentaires_options_et_inclusion(self):
        dossier = tempfile.mkdtemp(prefix="el_exigences_")
        self.addCleanup(lambda: __import__("shutil").rmtree(dossier, True))
        Path(dossier, "autre.txt").write_text("inclus\n")
        Path(dossier, "exigences.txt").write_text(
            "# un commentaire\n"
            "\n"
            "requests>=2  # après le nom\n"
            "--index-url https://exemple.invalid/simple\n"
            "-r autre.txt\n"
        )
        self.assertEqual(
            vrd.lire_exigences(os.path.join(dossier, "exigences.txt")),
            ["requests>=2", "inclus"],
        )


class TestLeScript(unittest.TestCase):
    def test_un_vrai_lancement_rend_du_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as fh:
            fh.write("packaging\n")
            fh.flush()
            fini = subprocess.run(
                [
                    sys.executable,
                    str(RACINE / "script/poetry/venv_requirements_drift.py"),
                    fh.name,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        etat = json.loads(fini.stdout)
        self.assertEqual(etat["manquantes"], [])

    def test_un_fichier_absent_rend_2(self):
        fini = subprocess.run(
            [
                sys.executable,
                str(RACINE / "script/poetry/venv_requirements_drift.py"),
                "/nulle/part.txt",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(fini.returncode, 2)


if __name__ == "__main__":
    unittest.main()
