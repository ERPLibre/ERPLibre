#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le lanceur unitaire garantit à chaque fichier qu'il exécute.

Deux garanties, jugées sur de vrais processus, le seul endroit où elles
existent :
 - une commande qui toucherait l'hôte, adb compris, est remplacée par une
   doublure qui refuse en le disant, même quand le cache où elle vit
   d'ordinaire ne peut être écrit ;
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
from unittest import mock

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

    def test_an_unwritable_cache_falls_back_to_the_work_dir(self):
        """Un cache qui ne peut être créé — XDG_CACHE_HOME en lecture
        seule, ou un fichier à sa place — ne doit pas empêcher la suite de
        tourner : les doublures vont alors sous le répertoire de travail."""
        with tempfile.TemporaryDirectory() as dossier:
            bouchon = os.path.join(dossier, "fichier")
            open(bouchon, "w").close()
            with mock.patch.object(
                r, "DOUBLURES", os.path.join(bouchon, "bin")
            ):
                lanceur = r.Lanceur([], sys.executable, 1, 60, {})
            self.addCleanup(lanceur.nettoyer)
            premier = lanceur.env["PATH"].split(os.pathsep)[0]
            self.assertEqual(premier, os.path.join(lanceur.travail, "bin"))
            res = subprocess.run(
                ["sudo", "-n", "true"],
                env=lanceur.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("refusé", res.stderr)


class TestLeTempsEcoule(unittest.TestCase):
    """Le temps affiché par la vue Textual s'arrête à la fin de la passe."""

    def test_une_passe_finie_garde_sa_duree(self):
        from types import SimpleNamespace

        lanceur = SimpleNamespace(debut=100.0, fin=147.0)
        self.assertEqual(r.ecoule_total(lanceur, 500.0), 47.0)

    def test_une_passe_en_cours_compte_jusqu_a_maintenant(self):
        from types import SimpleNamespace

        lanceur = SimpleNamespace(debut=100.0, fin=None)
        self.assertEqual(r.ecoule_total(lanceur, 130.0), 30.0)

    def test_une_passe_pas_commencee_vaut_zero(self):
        from types import SimpleNamespace

        lanceur = SimpleNamespace(debut=None, fin=None)
        self.assertEqual(r.ecoule_total(lanceur, 130.0), 0.0)


# Cinq tests sur deux classes, pour les tranches.
CINQ = """import unittest


class A(unittest.TestCase):
    def test_1(self):
        pass

    def test_2(self):
        pass

    def test_3(self):
        pass


class B(unittest.TestCase):
    def test_4(self):
        pass

    def test_5(self):
        pass


if __name__ == "__main__":
    unittest.main()
"""


class TestLesTranches(unittest.TestCase):
    """Un fichier lent tourne en plusieurs processus, une tranche chacun."""

    def test_le_nombre_de_tranches(self):
        self.assertEqual(r.nombre_de_tranches(None, 16, seuil=30), 1)
        self.assertEqual(r.nombre_de_tranches(30, 16, seuil=30), 1)
        self.assertEqual(r.nombre_de_tranches(69, 16, seuil=30), 3)
        self.assertEqual(r.nombre_de_tranches(600, 4, seuil=30), 4)
        self.assertEqual(r.nombre_de_tranches(600, 16, seuil=0), 1)

    def lancer_tranche(self, rang, nombre):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "test_cinq.py")
            with open(chemin, "w") as fh:
                fh.write(CINQ)
            fini = subprocess.run(
                [
                    sys.executable,
                    r.UNIT_FILE,
                    chemin,
                    os.path.join(dossier, "sortie.json"),
                    "--tranche",
                    f"{rang}/{nombre}",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        return fini

    def test_chaque_tranche_lance_sa_part_et_toutes_couvrent_tout(self):
        lances = []
        for rang in range(2):
            fini = self.lancer_tranche(rang, 2)
            self.assertEqual(fini.returncode, 0, fini.stderr)
            lances.append(int(fini.stderr.split("Ran ")[1].split()[0]))
        self.assertEqual(lances, [3, 2])

    def test_une_tranche_vide_reussit(self):
        fini = self.lancer_tranche(5, 6)
        self.assertEqual(fini.returncode, 0, fini.stderr)
        self.assertIn("Ran 0 tests", fini.stderr)
        self.assertIn("OK", fini.stderr)

    def test_le_lanceur_decoupe_un_fichier_lent(self):
        # Le seuil par défaut, quel que soit UNIT_TRANCHE dans le shell.
        seuil = mock.patch.object(r, "SEUIL_TRANCHE", 30)
        seuil.start()
        self.addCleanup(seuil.stop)
        lanceur = r.Lanceur(
            ["test/test_lent.py", "test/test_court.py"],
            py=sys.executable,
            jobs=16,
            delai=60,
            durees={"test_lent.py": 69, "test_court.py": 5},
        )
        self.addCleanup(lanceur.nettoyer)
        noms = sorted(f.nom for f in lanceur.fichiers)
        self.assertEqual(
            noms,
            [
                "test_court.py",
                "test_lent.py [1/3]",
                "test_lent.py [2/3]",
                "test_lent.py [3/3]",
            ],
        )

    def tranches_finies(self, *etats_durees):
        fichiers = []
        for rang, (etat, duree) in enumerate(etats_durees):
            f = r.Fichier(
                "test/test_lent.py", tranche=(rang, len(etats_durees))
            )
            f.etat, f.duree = etat, duree
            fichiers.append(f)
        return fichiers

    def test_la_duree_retenue_est_la_somme_des_tranches(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "durees")
            r.ecrire_durees(
                self.tranches_finies((r.OK, 20.2), (r.OK, 25.0), (r.OK, 24.0)),
                chemin,
            )
            self.assertEqual(r.lire_durees(chemin), {"test_lent.py": 69})

    def test_deux_tranches_d_un_passage_ne_font_pas_un_instable(self):
        from types import SimpleNamespace

        lanceur = SimpleNamespace(
            fichiers=self.tranches_finies((r.OK, 1.0), (r.ECHEC, 1.0))
        )
        self.assertEqual(r.instables(lanceur), {})


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
