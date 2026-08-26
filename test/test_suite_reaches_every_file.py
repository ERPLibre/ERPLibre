#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un test qui ne tourne pas est pire qu'un test absent.

Absent, on le sait. Vert sans avoir tourné, il rassure. Le dépôt a
rencontré les deux formes de ce silence le même jour :

  · `unittest.main()` posé au MILIEU d'un fichier. Python exécute de haut
    en bas : l'appel part, découvre ce qui est défini jusque-là, et sort.
    Tout ce qui suit n'existe pas encore. Quatre fichiers, 87 tests.

  · Aucun bloc `__main__` du tout. Le fichier ne fait rien quand on le
    lance, le lanceur compte zéro test, et le total ne bouge pas. Huit
    fichiers, 174 tests.

À quoi s'ajoutait une liste de préfixes dans le lanceur, qui laissait 2400
tests hors de la suite. Trois façons différentes d'obtenir le même
résultat : du vert qui ne prouve rien.

Ce fichier est la garde. Il ne lit pas ce que les tests vérifient — il
vérifie qu'ils PEUVENT être vérifiés.
"""

import ast
import glob
import io
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANCEUR = os.path.join(REPO, "script", "test", "run_unit_test.sh")


def fichiers_de_test():
    return sorted(glob.glob(os.path.join(REPO, "test", "test_*.py")))


def bloc_main(arbre):
    """L'indice du `if __name__ == "__main__":` du module, ou None."""
    for rang, noeud in enumerate(arbre.body):
        if (
            isinstance(noeud, ast.If)
            and isinstance(noeud.test, ast.Compare)
            and getattr(noeud.test.left, "id", "") == "__name__"
        ):
            return rang
    return None


class TestEveryFileCanRun(unittest.TestCase):
    def setUp(self):
        self.fichiers = fichiers_de_test()
        self.assertTrue(self.fichiers, "aucun fichier de test trouvé")

    def test_every_file_has_a_way_to_run_itself(self):
        # Le lanceur exécute chaque fichier comme un programme. Sans ce
        # bloc, il ne fait rien et le lanceur compte zéro — sans erreur.
        for chemin in self.fichiers:
            arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
            self.assertIsNotNone(
                bloc_main(arbre),
                f"{os.path.basename(chemin)} : pas de bloc __main__",
            )

    def test_the_run_call_is_the_last_thing_in_the_file(self):
        # Au milieu, il coupe le fichier en deux et la seconde moitié
        # n'est jamais définie au moment où les tests sont découverts.
        for chemin in self.fichiers:
            arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
            rang = bloc_main(arbre)
            if rang is None:
                continue
            suivants = arbre.body[rang + 1 :]
            self.assertEqual(
                [],
                [type(n).__name__ for n in suivants],
                f"{os.path.basename(chemin)} : du code après unittest.main()",
            )

    def test_every_file_actually_declares_a_test(self):
        for chemin in self.fichiers:
            arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
            combien = sum(
                1
                for noeud in ast.walk(arbre)
                if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef))
                and noeud.name.startswith("test_")
            )
            self.assertTrue(
                combien, f"{os.path.basename(chemin)} : aucun test dedans"
            )


class TestTheRunnerLeavesNobodyOut(unittest.TestCase):
    """Une liste de préfixes oublie ; un glob, non."""

    def setUp(self):
        self.source = io.open(LANCEUR, encoding="utf-8").read()

    def test_it_takes_the_whole_directory(self):
        self.assertIn("ls test/test_*.py", self.source)

    def test_it_does_not_pick_families_by_name(self):
        # Le défaut d'origine : un fichier hors préfixe tombait dans le
        # même silence qu'un fichier absent.
        for prefixe in ("test/test_qemu_*.py", "test/test_todo_*.py"):
            self.assertNotIn(prefixe, self.source, prefixe)


if __name__ == "__main__":
    unittest.main()
