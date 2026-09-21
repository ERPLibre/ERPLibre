#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'outil qui distingue une commande écrite en dur d'une prose qui la cite.

Un outil d'épreuve SANS épreuve est ce qui a manqué : ce contrôle a été
recopié trois fois et la troisième copie levait un TypeError sur le premier
fichier portant une expression conditionnelle. Les cas ci-dessous sont
INVENTÉS, et c'est le point : ils exercent des formes qu'aucun fichier du
dépôt ne porte encore.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from code_literals import (  # noqa: E402
    code_string_literals,
    literals_in_file,
    literals_matching,
)


class TestLesDocstringsSontExclues(unittest.TestCase):
    def test_a_module_docstring_is_not_a_literal(self):
        self.assertEqual([], code_string_literals('"""limactl doc."""\n'))

    def test_a_function_docstring_is_not_a_literal(self):
        source = 'def f():\n    """limactl doc."""\n    return 1\n'
        self.assertEqual([], code_string_literals(source))

    def test_a_class_docstring_is_not_a_literal(self):
        source = 'class C:\n    """limactl doc."""\n'
        self.assertEqual([], code_string_literals(source))

    def test_an_async_function_docstring_is_not_a_literal(self):
        source = 'async def f():\n    """limactl doc."""\n'
        self.assertEqual([], code_string_literals(source))

    def test_a_real_literal_is_kept(self):
        """Contrôle positif : tout exclure passerait chaque épreuve sans
        rien lire."""
        self.assertEqual(
            ["limactl list"], code_string_literals('x = "limactl list"\n')
        )

    def test_the_two_are_told_apart_in_one_file(self):
        source = (
            '"""limactl, expliqué."""\n'
            "def f():\n"
            '    """limactl, encore expliqué."""\n'
            '    return "limactl list"\n'
        )
        self.assertEqual(["limactl list"], code_string_literals(source))

    def test_a_string_that_is_not_the_first_statement_is_a_literal(self):
        """Une chaîne posée APRÈS du code n'est pas une docstring, même
        seule sur sa ligne — et elle vaut ce qu'elle dit."""
        source = 'def f():\n    x = 1\n    "limactl list"\n    return x\n'
        self.assertEqual(["limactl list"], code_string_literals(source))


class TestLesFormesQuiOntCasseLaCopie(unittest.TestCase):
    """LE DÉFAUT de la troisième copie, figé ici pour toujours."""

    def test_a_conditional_expression_does_not_crash_it(self):
        """`ast.IfExp` porte un « body » qui est une EXPRESSION, pas une
        liste : le deviner par la présence de l'attribut lève un
        TypeError."""
        source = 'x = "limactl a" if True else "limactl b"\n'
        self.assertEqual(
            ["limactl a", "limactl b"], code_string_literals(source)
        )

    def test_a_lambda_does_not_crash_it(self):
        """Elle porte aussi un « body » qui est une expression."""
        self.assertEqual(
            ["limactl x"], code_string_literals('f = lambda: "limactl x"\n')
        )

    def test_a_comprehension_does_not_crash_it(self):
        source = 'x = ["limactl y" for _ in range(2)]\n'
        self.assertEqual(["limactl y"], code_string_literals(source))

    def test_an_f_string_constant_part_is_a_literal(self):
        """« f"limactl shell {nom}" » écrit bien la commande en dur, et
        l'AST en fait un morceau constant."""
        trouves = literals_matching('x = f"limactl shell {nom}"\n', "limactl")
        self.assertEqual(["limactl shell "], trouves)

    def test_a_nested_function_docstring_is_still_excluded(self):
        source = (
            "def outer():\n"
            "    def inner():\n"
            '        """limactl doc."""\n'
            "    return inner\n"
        )
        self.assertEqual([], code_string_literals(source))

    def test_nothing_is_an_empty_list_and_not_a_crash(self):
        self.assertEqual([], code_string_literals(""))
        self.assertEqual([], code_string_literals(None))


class TestCeQueLaRechercheRend(unittest.TestCase):
    def test_it_returns_what_it_found_and_not_a_boolean(self):
        """Une épreuve qui tombe doit montrer ce qu'elle a trouvé, sans
        quoi il faut relire le fichier entier."""
        trouves = literals_matching(
            'a = "limactl list"\nb = "autre"\n', "limactl"
        )
        self.assertEqual(["limactl list"], trouves)

    def test_a_needle_absent_gives_an_empty_list(self):
        self.assertEqual([], literals_matching('a = "autre"\n', "limactl"))

    def test_it_reads_a_real_file_of_the_repository(self):
        """Le contrôle du banc : si la lecture échouait, les invariants
        bâtis dessus passeraient sur une liste vide."""
        chemin = os.path.join(RACINE, "script", "vm", "lima.py")
        self.assertTrue(literals_in_file(chemin, "limactl"))


if __name__ == "__main__":
    unittest.main()
