#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les rapports du lanceur unitaire : --repeat, --slowest, --junit.

Les fichiers sont fabriqués dans l'état où le lanceur les laisse après un
passage : les rapports se jugent sans lancer un seul processus. Seuls les
temporaires oubliés se jugent sur de vrais passages : c'est le lanceur qui
pose le TMPDIR de chaque fichier, et lui seul qui le compte et le supprime.
"""

import glob
import os
import sys
import tempfile
import threading
import time
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


# Un fichier de tests qui oublie un temporaire et dit où il l'a laissé.
OUBLI = """import os, tempfile, unittest
class T(unittest.TestCase):
    def test_oubli(self):
        tempfile.NamedTemporaryFile(delete=False).close()
        print('TMPDIR=' + os.environ['TMPDIR'])
if __name__ == '__main__':
    unittest.main()
"""

# Un fichier qui laisse un temporaire puis attend qu'on le tue.
TUE = """import tempfile, time
tempfile.NamedTemporaryFile(delete=False).close()
time.sleep(600)
"""


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


class TestLesTemporairesOublies(unittest.TestCase):
    def test_the_summary_names_the_files_that_leave_temporaries(self):
        propre = fichier("test_propre.py", r.OK)
        sale = fichier("test_sale.py", r.OK)
        sale.restes = 3
        lignes = r.restes_temporaires(Lanceur(propre, sale))
        self.assertEqual(len(lignes), 2)
        self.assertIn("test_sale.py  (3)", lignes[1])
        self.assertEqual(r.restes_temporaires(Lanceur(propre)), [])

    def test_a_file_gets_its_own_tmpdir_counted_then_removed(self):
        # Un vrai passage : le fichier oublie un temporaire, le lanceur le
        # compte, puis supprime le TMPDIR du fichier.
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "test_oubli.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(OUBLI)
            lanceur = r.Lanceur([chemin], sys.executable, 1, 60, {})
            self.addCleanup(lanceur.nettoyer)
            lanceur.lancer()
            (f,) = lanceur.fichiers
            self.assertEqual(f.etat, r.OK)
            self.assertEqual(f.restes, 1)
            tmp = r._lire(f.log).split("TMPDIR=")[1].split()[0]
            self.assertTrue(tmp.startswith(lanceur.travail))
            self.assertFalse(os.path.exists(tmp))

    def test_a_killed_file_has_its_temporaries_removed_not_reported(self):
        """Tué par Ctrl+C ou par le délai, un fichier n'a pas pu nettoyer :
        ses restes sont supprimés sans être imputés au test."""
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "test_tue.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(TUE)
            # Ctrl+C : arrêté dès que le temporaire existe.
            lanceur = r.Lanceur([chemin], sys.executable, 1, 600, {})
            self.addCleanup(lanceur.nettoyer)
            fil = threading.Thread(target=lanceur.lancer)
            fil.start()
            limite = time.monotonic() + 60
            while not glob.glob(os.path.join(lanceur.travail, "*.tmp", "*")):
                self.assertLess(time.monotonic(), limite, "aucun temporaire")
                time.sleep(0.05)
            lanceur.arreter()
            fil.join()
            # Le délai : la même chose, sans personne pour interrompre.
            lent = r.Lanceur([chemin], sys.executable, 1, 1, {})
            self.addCleanup(lent.nettoyer)
            lent.lancer()
            for lanceur, etat in ((lanceur, r.ARRETE), (lent, r.DELAI)):
                with self.subTest(etat):
                    (f,) = lanceur.fichiers
                    self.assertEqual(f.etat, etat)
                    self.assertEqual(f.restes, 0)
                    self.assertEqual(r.restes_temporaires(lanceur), [])
                    self.assertEqual(
                        glob.glob(os.path.join(lanceur.travail, "*.tmp")), []
                    )

    def test_two_files_of_the_same_name_never_share_a_tmpdir(self):
        """Le même fichier deux fois, ou deux fichiers de même nom dans deux
        répertoires : chacun son TMPDIR et son journal, et la suppression
        de l'un n'emporte pas les restes de l'autre."""
        with tempfile.TemporaryDirectory() as dossier:
            chemins = []
            for sous in ("a", "b"):
                os.mkdir(os.path.join(dossier, sous))
                chemins.append(os.path.join(dossier, sous, "test_oubli.py"))
                with open(chemins[-1], "w", encoding="utf-8") as fh:
                    fh.write(OUBLI)
            for liste in ([chemins[0], chemins[0]], chemins):
                with self.subTest(liste=liste):
                    lanceur = r.Lanceur(liste, sys.executable, 2, 60, {})
                    self.addCleanup(lanceur.nettoyer)
                    lanceur.lancer()
                    self.assertEqual(
                        [(f.etat, f.restes) for f in lanceur.fichiers],
                        [(r.OK, 1), (r.OK, 1)],
                    )
                    journaux = {f.log for f in lanceur.fichiers}
                    tmps = {
                        r._lire(f.log).split("TMPDIR=")[1].split()[0]
                        for f in lanceur.fichiers
                    }
                    self.assertEqual((len(journaux), len(tmps)), (2, 2))


if __name__ == "__main__":
    unittest.main()
