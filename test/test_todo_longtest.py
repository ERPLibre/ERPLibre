#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests LONGS : qu'ils existent, qu'ils annoncent, et qu'ils ne
polluent pas la suite unitaire.

Un test qui crée dix VM n'a rien à faire dans `test/` : le lanceur unitaire
doit rester lançable en quelques secondes, partout, y compris sur une machine
sans virtualisation. Ce fichier-ci vérifie la frontière, et que l'essai à
blanc du test long dit quelque chose sans rien créer.
"""

import os
import subprocess
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(RACINE, ".venv.erplibre/bin/python")


class TestLaFrontiere(unittest.TestCase):
    """LongTest est hors de portée du lanceur unitaire, et ce n'est pas un
    rangement de confort."""

    def test_the_unit_runner_does_not_sweep_LongTest(self):
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            lanceur = fh.read()
        # Le lanceur ne liste que des fichiers de test/ : rien qui parte de
        # LongTest, sinon la suite unitaire créerait des VM.
        self.assertNotIn("LongTest", lanceur)

    def test_the_naming_rule_is_written_where_it_is_read(self):
        # Un fichier hors préfixe tombe dans le même silence qu'un fichier
        # absent : douze tests écrits, jamais lancés.
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            self.assertIn("NOMMER UN NOUVEAU FICHIER", fh.read())

    def test_the_script_is_executable_and_documented(self):
        script = os.path.join(RACINE, "LongTest/deep_proxmox.py")
        self.assertTrue(os.access(script, os.X_OK), "doit être exécutable")
        # La doc est un .base.md : un .md généré se perd au prochain
        # « make doc_markdown ».
        self.assertTrue(
            os.path.exists(os.path.join(RACINE, "LongTest/README.base.md"))
        )


class TestLEssaiABlanc(unittest.TestCase):
    """L'essai à blanc annonce le plan et n'exécute RIEN.

    C'est ce qui rend un test de plusieurs heures relisable avant de le
    lancer : on voit les ressources de chaque étage et les commandes, sans
    créer une machine."""

    @classmethod
    def setUpClass(cls):
        cls.res = subprocess.run(
            [
                PYTHON,
                os.path.join(RACINE, "LongTest/deep_proxmox.py"),
                "--depth",
                "4",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
            env=dict(os.environ, PYTHONPATH=RACINE),
        )

    def test_it_exits_cleanly(self):
        self.assertEqual(self.res.returncode, 0, self.res.stderr[-800:])

    def test_it_announces_the_plan_before_anything(self):
        sortie = self.res.stdout
        self.assertIn("étage", sortie)
        # Quatre étages demandés, quatre lignes de plan.
        for niveau in ("1", "2", "3", "4"):
            self.assertIn(niveau, sortie)
        self.assertIn("dry-run", sortie)

    def test_it_shows_the_commands_it_would_send(self):
        # Une étape affichée est une étape rejouable à la main : c'est ainsi
        # que les pannes de ce module ont été diagnostiquées.
        self.assertIn("qm create", self.res.stdout)
        self.assertIn("install_proxmox.sh", self.res.stdout)

    def test_the_first_level_is_wide_and_the_others_are_not(self):
        # 12 vCPU au quatrième étage ont gelé un noyau invité ; deux
        # avançaient.
        # Par expression exacte : la ligne « machine : … Mo … Go » du haut
        # contient les mêmes unités et décalait l'index d'un cran.
        import re

        plan = re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(\d+) Mo\s+(\d+) Go\s*$",
            self.res.stdout,
            re.M,
        )
        self.assertEqual(len(plan), 4, plan)
        niveaux = {int(n): int(v) for n, v, _r, _d in plan}
        self.assertGreater(niveaux[1], 1, "le premier étage peut être large")
        for niveau in (2, 3, 4):
            self.assertEqual(niveaux[niveau], 2, f"étage {niveau}")


class TestLeMenu(unittest.TestCase):
    def test_the_mixin_is_wired_into_TODO(self):
        todo = TODO.__new__(TODO)
        self.assertTrue(hasattr(todo, "prompt_execute_longtest"))

    def test_the_script_is_found_from_the_repository_root(self):
        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        try:
            os.chdir(RACINE)
            self.assertTrue(todo._longtest_script("deep_proxmox.py"))
            self.assertFalse(todo._longtest_script("nexiste-pas.py"))
        finally:
            os.chdir(ancien)

    def test_the_test_menu_offers_it(self):
        import inspect

        src = inspect.getsource(TODO.prompt_execute_test)
        self.assertIn("prompt_execute_longtest", src)
        self.assertIn("Long tests", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
