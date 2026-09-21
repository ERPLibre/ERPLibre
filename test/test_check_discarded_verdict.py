#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le détecteur de verdicts jetés : ce qu'il voit, et ce qu'il laisse.

LA PREUVE EST DIFFÉRENTIELLE. L'outil ne juge pas ce qu'une valeur vaut : il
compare les appels entre eux. Une fonction que presque personne ne lit a
raison de n'être pas lue — c'est le cas des fonctions qui traitent leur
propre panne — et l'outil se tait. C'est ce réglage automatique qui remplace
une liste d'exemptions, et il est éprouvé ici dans les deux sens.
"""

import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.analyse import check_discarded_verdict as V  # noqa: E402


class CasDeDetecteur(unittest.TestCase):
    def analyse(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "module.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(source)
            return V.inspect(chemin)

    def noms(self, source):
        return [f["function"] for f in self.analyse(source)]


# Une fonction qui rend un verdict : deux retours de valeur, et le refus est
# l'un d'eux. C'est la forme de tout ce que ce dépôt appelle « rendre ».
RENDEUSE = (
    "def poser(x):\n"
    "    if not x:\n"
    "        return ''\n"
    "    return 'refus'\n"
)


class TestCeQuIlVoit(CasDeDetecteur):
    def test_a_bare_call_where_the_file_reads_it_elsewhere(self):
        """Le cas qui a coûté : le verdict d'un lot d'armement jeté, et
        l'installation qui part sur une machine non confinée."""
        self.assertEqual(
            ["poser"],
            self.noms(
                RENDEUSE
                + "def a():\n    r = poser(1)\n    return r\n"
                + "def b():\n    poser(2)\n"
            ),
        )

    def test_a_method_called_through_self(self):
        self.assertEqual(
            ["_poser"],
            self.noms(
                "class M:\n"
                "    def _poser(self, x):\n"
                "        if not x:\n"
                "            return ''\n"
                "        return 'refus'\n"
                "    def a(self):\n"
                "        return self._poser(1)\n"
                "    def b(self):\n"
                "        self._poser(2)\n"
            ),
        )

    def test_it_counts_both_sides(self):
        trouvailles = self.analyse(
            RENDEUSE
            + "def a():\n    return poser(1)\n"
            + "def b():\n    return poser(2)\n"
            + "def c():\n    poser(3)\n"
        )
        self.assertEqual(2, trouvailles[0]["read"])
        self.assertEqual(1, trouvailles[0]["ignored"])


class TestCeQuIlLaisse(CasDeDetecteur):
    """Un détecteur qui crie au loup est un détecteur qu'on désarme."""

    def test_a_function_almost_nobody_reads_is_the_house_convention(self):
        """Celle qui traite sa propre panne — elle interroge, elle rejoue —
        a raison d'être ignorée. Une liste d'exemptions aurait fait le même
        travail en vieillissant."""
        self.assertEqual(
            [],
            self.analyse(
                RENDEUSE
                + "def a():\n    return poser(1)\n"
                + "def b():\n    poser(2)\n"
                + "def c():\n    poser(3)\n"
                + "def d():\n    poser(4)\n"
            ),
        )

    def test_a_function_nobody_reads_says_nothing(self):
        self.assertEqual(
            [], self.analyse(RENDEUSE + "def b():\n    poser(2)\n")
        )

    def test_one_single_return_is_a_factory_not_a_verdict(self):
        """Un seul retour décrit une fabrique : elle rend toujours la même
        sorte de chose, et personne n'en attend un refus."""
        self.assertEqual(
            [],
            self.analyse(
                "def fabrique(x):\n    return {'a': x}\n"
                + "def a():\n    return fabrique(1)\n"
                + "def b():\n    fabrique(2)\n"
            ),
        )

    def test_a_procedure_is_not_a_verdict(self):
        """« return None » n'est pas une réponse : c'est une sortie. Deux
        d'entre eux ne font toujours pas un verdict, et les compter ferait
        de chaque procédure un manque."""
        self.assertEqual(
            [],
            self.analyse(
                "def pose(x):\n"
                "    if x:\n"
                "        return None\n"
                "    if not x:\n"
                "        return None\n"
                "    return None\n"
                + "def a():\n    return pose(1)\n"
                + "def b():\n    pose(2)\n"
            ),
        )

    def test_a_collaborator_is_out_of_reach_and_that_is_said(self):
        """`self.execute.lancer(...)` échappe : deux classes peuvent porter
        la même méthode, et deviner ferait crier au loup. La docstring du
        module le dit ; ce test le fige."""
        self.assertEqual(
            [],
            self.analyse(
                "class M:\n"
                "    def lancer(self, x):\n"
                "        if not x:\n"
                "            return ''\n"
                "        return 'refus'\n"
                "    def a(self):\n"
                "        return self.moteur.lancer(1)\n"
                "    def b(self):\n"
                "        self.moteur.lancer(2)\n"
            ),
        )


class TestLOutilSurLeDepot(unittest.TestCase):
    def test_it_finds_something(self):
        """Un détecteur qui ne détecte rien passe tous les tests d'à côté
        sans rien garder."""
        trouves = []
        for chemin in V.etend([os.path.join(RACINE, "script")]):
            trouves.extend(V.inspect(chemin))
        self.assertGreater(len(trouves), 5)

    def test_its_rate_stays_a_signal_and_not_a_wall(self):
        """Mesuré avant d'être branché : au-delà, le rapport cesse d'être
        une invitation. Ce nombre est écrit pour qu'il faille le CHANGER
        sciemment si le seuil bouge."""
        trouves = []
        for chemin in V.etend(
            [os.path.join(RACINE, "script"), os.path.join(RACINE, "long_test")]
        ):
            trouves.extend(V.inspect(chemin))
        self.assertLess(len(trouves), 40, "le détecteur crie au loup")

    def test_a_file_that_does_not_parse_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "casse.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write("def x(:\n")
            self.assertEqual([], V.inspect(chemin))


class TestLesTroisOutilsPartagentUneMecanique(unittest.TestCase):
    """Trois contrôleurs, un seul endroit qui dit quels fichiers regarder.

    Une copie par outil aurait donné autant de façons de se taire : un
    répertoire ignoré d'un côté, un suffixe de l'autre, et le plus jeune
    cesse de voir sans que rien ne le dise.
    """

    OUTILS = (
        "script/analyse/check_guard_shape.py",
        "script/analyse/check_discarded_verdict.py",
    )

    def test_each_one_takes_its_reading_from_the_shared_library(self):
        for relatif in self.OUTILS:
            with self.subTest(outil=relatif):
                with open(
                    os.path.join(RACINE, relatif), encoding="utf-8"
                ) as fh:
                    source = fh.read()
                self.assertIn("from script.analyse.lib_check import", source)

    def test_none_of_them_walks_the_tree_itself(self):
        """DÉRIVÉ : c'est le parcours qui divergerait en silence."""
        import ast

        for relatif in self.OUTILS:
            with self.subTest(outil=relatif):
                with open(
                    os.path.join(RACINE, relatif), encoding="utf-8"
                ) as fh:
                    arbre = ast.parse(fh.read())
                marches = [
                    n.lineno
                    for n in ast.walk(arbre)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "walk"
                    and getattr(n.func.value, "id", "") == "os"
                ]
                self.assertEqual([], marches)

    def test_the_hook_carries_the_three_of_them(self):
        with open(
            os.path.join(RACINE, "script", "git", "hooks", "pre-commit"),
            encoding="utf-8",
        ) as fh:
            hook = fh.read()
        for outil in (
            "check_comment_hygiene.py",
            "check_guard_shape.py",
            "check_discarded_verdict.py",
        ):
            self.assertIn(outil, hook)


if __name__ == "__main__":
    unittest.main()
