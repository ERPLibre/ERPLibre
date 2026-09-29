#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les rapports du lanceur unitaire : --repeat, --slowest, --junit.

Les fichiers sont fabriqués dans l'état où le lanceur les laisse après un
passage : les rapports se jugent sans lancer un seul processus.
"""

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import run_unit_test as r  # noqa: E402


def fichier(nom, etat, passage=0, passages=1, tests=(), duree=1.0):
    f = r.Fichier(f"test/{nom}", passage, passages)
    f.etat = etat
    f.duree = duree
    f.tests = list(tests)
    return f


def test(ident, duree, etat="ok", message=""):
    classe, nom = ident.split(".")
    return {
        "id": f"mod.{ident}",
        "classe": classe,
        "nom": nom,
        "duree": duree,
        "etat": etat,
        "message": message,
    }


class Lanceur:
    def __init__(self, *fichiers):
        self.fichiers = list(fichiers)


class TestLesPassagesRepetes(unittest.TestCase):
    def test_a_file_whose_outcome_varies_is_unstable(self):
        lanceur = Lanceur(
            fichier("test_a.py", r.OK, 0, 3),
            fichier("test_a.py", r.ECHEC, 1, 3),
            fichier("test_a.py", r.OK, 2, 3),
            fichier("test_b.py", r.ECHEC, 0, 3),
            fichier("test_b.py", r.ECHEC, 1, 3),
        )
        # b échoue toujours : c'est un échec, pas une instabilité.
        self.assertEqual(
            r.instables(lanceur), {"test_a.py": {r.ECHEC: 1, r.OK: 2}}
        )

    def test_a_stopped_pass_proves_nothing(self):
        lanceur = Lanceur(
            fichier("test_a.py", r.OK, 0, 2),
            fichier("test_a.py", r.ARRETE, 1, 2),
        )
        self.assertEqual(r.instables(lanceur), {})

    def test_a_repeated_file_shows_its_pass_number(self):
        self.assertEqual(fichier("test_a.py", r.OK, 1, 3).nom, "test_a.py #2")
        self.assertEqual(fichier("test_a.py", r.OK).nom, "test_a.py")


class TestLesPlusLents(unittest.TestCase):
    def test_the_slowest_tests_across_files_longest_first(self):
        lanceur = Lanceur(
            fichier("test_a.py", r.OK, tests=[test("A.t1", 0.2)]),
            fichier(
                "test_b.py",
                r.OK,
                tests=[test("B.t1", 3.0), test("B.t2", 0.1)],
            ),
        )
        self.assertEqual(
            r.plus_lents(lanceur, 2),
            [(3.0, "test_b.py", "mod.B.t1"), (0.2, "test_a.py", "mod.A.t1")],
        )

    def test_a_repeated_test_counts_for_its_longest_run(self):
        lanceur = Lanceur(
            fichier("test_a.py", r.OK, 0, 2, tests=[test("A.t", 0.5)]),
            fichier("test_a.py", r.OK, 1, 2, tests=[test("A.t", 1.5)]),
        )
        self.assertEqual(
            r.plus_lents(lanceur, 5), [(1.5, "test_a.py", "mod.A.t")]
        )


class TestLeJUnit(unittest.TestCase):
    def junit(self, *fichiers):
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fh:
            chemin = fh.name
        self.addCleanup(os.unlink, chemin)
        r.ecrire_junit(Lanceur(*fichiers), chemin)
        return ET.parse(chemin).getroot()

    def test_each_outcome_has_its_element_and_its_count(self):
        racine = self.junit(
            fichier(
                "test_a.py",
                r.ECHEC,
                tests=[
                    test("A.bon", 0.1),
                    test(
                        "A.faux", 0.2, "echec", "Traceback\nAssertionError: 1"
                    ),
                    test("A.casse", 0.3, "erreur", "Traceback\nKeyError: 'x'"),
                    test("A.saute", 0.0, "ignore", "Textual absent"),
                ],
            )
        )
        suite = racine.find("testsuite")
        self.assertEqual(
            {
                k: suite.get(k)
                for k in ("tests", "failures", "errors", "skipped")
            },
            {"tests": "4", "failures": "1", "errors": "1", "skipped": "1"},
        )
        faux = suite.find("testcase[@name='faux']/failure")
        self.assertEqual(faux.get("message"), "AssertionError: 1")
        self.assertIsNotNone(suite.find("testcase[@name='casse']/error"))
        self.assertIsNotNone(suite.find("testcase[@name='saute']/skipped"))
        self.assertEqual(
            suite.find("testcase[@name='bon']").get("classname"), "test_a.A"
        )

    def test_a_file_without_detail_still_appears_as_an_error(self):
        """Tué par le délai, il n'a rien écrit : il ne doit pas disparaître
        du rapport."""
        racine = self.junit(fichier("test_lent.py", r.DELAI))
        suite = racine.find("testsuite")
        self.assertEqual(suite.get("errors"), "1")
        self.assertIn("aucun résultat", suite.find("testcase/error").text)


class TestLesEchecsRetenusSurPlusieursPassages(unittest.TestCase):
    def test_one_failure_out_of_n_keeps_the_file(self):
        passes, echoues = r.bilan_des_echecs(
            [
                fichier("test_a.py", r.OK, 0, 2),
                fichier("test_a.py", r.ECHEC, 1, 2),
                fichier("test_b.py", r.OK, 0, 2),
                fichier("test_b.py", r.OK, 1, 2),
                fichier("test_c.py", r.ARRETE, 0, 1),
            ]
        )
        self.assertEqual((passes, echoues), (["test_b.py"], ["test_a.py"]))


if __name__ == "__main__":
    unittest.main()
