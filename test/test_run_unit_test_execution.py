#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le lanceur unitaire garantit à chaque fichier qu'il exécute.

Deux garanties, jugées sur de vrais processus, le seul endroit où elles
existent :
 - une commande qui toucherait l'hôte, adb compris, est remplacée par une
   doublure qui refuse en le disant ;
 - le journal d'un fichier en échec finit sur le verdict d'unittest, même
   quand le test imprime : ce sont ces dernières lignes que le bilan montre.
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import run_unit_test as r  # noqa: E402

# Un fichier de tests qui imprime plus de lignes que le bilan n'en montre,
# puis échoue.
BAVARD = """import unittest


class TestBavard(unittest.TestCase):
    def test_imprime_puis_echoue(self):
        for numero in range(30):
            print("ligne", numero)
        self.fail("le verdict attendu")


if __name__ == "__main__":
    unittest.main()
"""


class TestLesCommandesRefusees(unittest.TestCase):
    def test_adb_is_refused_like_sudo(self):
        """adb atteint le téléphone branché au poste : un appel non
        bouchonné doit échouer sur tous les postes, sans rien toucher."""
        self.assertIn("adb", r.REFUSEES)
        with tempfile.TemporaryDirectory() as dossier:
            r.poser_doublures(dossier)
            for commande, code in r.REFUSEES.items():
                with self.subTest(commande):
                    res = subprocess.run(
                        [os.path.join(dossier, commande), "devices"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    self.assertEqual(res.returncode, code)
                    self.assertIn(f"{commande} devices", res.stderr)


class TestLeBilanMontreLeVerdict(unittest.TestCase):
    def test_a_failing_file_that_prints_ends_on_its_verdict(self):
        """Sans terminal, la sortie standard d'un test ne se vide qu'à la fin
        du processus, après le verdict écrit sur la sortie d'erreur : le
        bilan, qui montre la fin du journal, ne montrerait qu'elle."""
        for detaille in (False, True):
            with self.subTest(detaille=detaille):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = os.path.join(dossier, "test_bavard.py")
                    with open(chemin, "w", encoding="utf-8") as fh:
                        fh.write(BAVARD)
                    lanceur = r.Lanceur(
                        [chemin],
                        sys.executable,
                        jobs=1,
                        delai=60,
                        durees={},
                        detaille=detaille,
                    )
                    affiche = io.StringIO()
                    try:
                        lanceur.lancer()
                        with contextlib.redirect_stdout(affiche):
                            code = r.bilan(lanceur)
                    finally:
                        lanceur.nettoyer()
                self.assertEqual(code, 1)
                self.assertIn("le verdict attendu", affiche.getvalue())
                self.assertIn("FAILED (failures=1)", affiche.getvalue())


if __name__ == "__main__":
    unittest.main()
