#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`run_unit_test.py --coverage` et `couverture.py`, sur de vrais processus.

Ce que ces tests gardent :

- un passage sous --coverage mesure le fichier de tests ET les
  sous-processus Python qu'il lance (patch = subprocess) ;
- un fichier tué au délai reçoit SIGTERM avant SIGKILL : ses données sont
  écrites, et l'historique le nomme comme incomplet ;
- l'historique marque un passage partiel, et ne le compare jamais à un
  passage complet ;
- un passage mesuré n'écrit pas de durées, qui fausseraient l'ordre et les
  tranches du passage suivant ;
- --coverage refuse --watch ;
- la commande d'un fichier : unit_file.py pour -k et l'ordre aléatoire,
  « coverage run -p » sous --coverage ;
- une seconde campagne est refusée tant que la première tient le verrou,
  et le refus la nomme.

Les passages mesurés tournent dans un XDG_CACHE_HOME temporaire : ni les
données, ni les durées, ni le verrou de l'utilisateur ne sont touchés.
Sautés, en le disant, si coverage 7.10 manque dans .venv.erplibre.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import couverture  # noqa: E402
import lanceur as moteur  # noqa: E402
import run_unit_test as r  # noqa: E402

PY = os.path.join(RACINE, ".venv.erplibre", "bin", "python")


def _coverage_present():
    res = subprocess.run(
        [
            PY,
            "-c",
            "import coverage, sys;"
            "sys.exit(0 if coverage.version_info >= (7, 10) else 1)",
        ],
        capture_output=True,
    )
    return res.returncode == 0


AVEC_COVERAGE = unittest.skipUnless(
    os.path.exists(PY) and _coverage_present(),
    "coverage 7.10 ou plus absent de .venv.erplibre",
)


class Passage(unittest.TestCase):
    """Un vrai run_unit_test.py --coverage, dans un cache temporaire."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.cache = os.path.join(self.d, "cache")
        self.jeu = os.path.join(
            self.cache, "erplibre", "couverture", "erplibre"
        )

    def ecrire_test(self, nom, corps):
        chemin = os.path.join(self.d, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(corps))
        return chemin

    def passer(self, *arguments, delai=60):
        env = dict(os.environ, XDG_CACHE_HOME=self.cache, UNIT_JOBS="2")
        for nom in (
            "COVERAGE_FILE",
            "COVERAGE_RCFILE",
            "COVERAGE_PROCESS_CONFIG",
        ):
            env.pop(nom, None)
        return subprocess.run(
            [PY, "script/test/run_unit_test.py", *arguments],
            cwd=RACINE,
            env=env,
            capture_output=True,
            text=True,
            timeout=delai,
        )

    def historique(self):
        with open(os.path.join(self.jeu, "historique.jsonl")) as fh:
            return [json.loads(ligne) for ligne in fh]

    def rapport(self):
        with open(os.path.join(self.jeu, "coverage.json")) as fh:
            return json.load(fh)

    @AVEC_COVERAGE
    def test_measures_the_test_and_its_python_subprocesses(self):
        test = self.ecrire_test(
            "test_mesure.py",
            """
            import subprocess, sys, unittest
            from script import lib_processus

            class T(unittest.TestCase):
                def test_import_et_sous_processus(self):
                    lib_processus.Lot().arreter()
                    subprocess.run(
                        [sys.executable, "-c",
                         "from script.todo import todo_couleur"],
                        check=True,
                    )

            if __name__ == "__main__":
                unittest.main()
            """,
        )
        res = self.passer("--coverage", "--", test)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        fichiers = self.rapport()["files"]
        self.assertGreater(
            len(fichiers["script/lib_processus.py"]["executed_lines"]), 0
        )
        # Importé seulement par le sous-processus : mesuré par
        # patch = subprocess.
        self.assertGreater(
            len(fichiers["script/todo/todo_couleur.py"]["executed_lines"]), 0
        )
        ligne = self.historique()[-1]
        self.assertFalse(ligne["complet"])
        self.assertEqual(ligne["incomplets"], [])
        self.assertIn("Couverture :", res.stdout)
        self.assertIn("passage partiel", res.stdout)
        # Les durées d'un passage mesuré ne sont pas retenues.
        self.assertFalse(
            os.path.exists(
                os.path.join(self.cache, "erplibre", "run_unit_test.durations")
            )
        )

    @AVEC_COVERAGE
    def test_a_file_killed_at_the_timeout_keeps_its_data(self):
        test = self.ecrire_test(
            "test_lent.py",
            """
            import time, unittest
            from script import lib_processus

            class T(unittest.TestCase):
                def test_trop_long(self):
                    lib_processus.Lot().arreter()
                    print("pret", flush=True)
                    time.sleep(60)

            if __name__ == "__main__":
                unittest.main()
            """,
        )
        res = self.passer("--coverage", "--timeout", "3", "--", test)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(r.DELAI, res.stdout)
        ligne = self.historique()[-1]
        self.assertEqual(ligne["incomplets"], ["test_lent.py"])
        # SIGTERM pendant la grâce : coverage a écrit ce que le fichier
        # avait exécuté avant d'être tué.
        self.assertGreater(
            len(
                self.rapport()["files"]["script/lib_processus.py"][
                    "executed_lines"
                ]
            ),
            0,
        )

    def test_coverage_refuses_watch(self):
        res = self.passer("--coverage", "--watch", "--", "test/test_x.py")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--watch", res.stdout)


class Commande(unittest.TestCase):
    """La commande que la campagne unitaire construit pour un fichier."""

    class Lanceur:
        py = "/venv/bin/python"
        detaille = False

    def commande(self, **reglages):
        campagne = r.CampagneUnitaire(**reglages)
        element = moteur.Element("test/test_exemple.py")
        return campagne.commande(self.Lanceur(), element, "/travail/0")

    def test_plain_file_runs_as_a_program(self):
        self.assertEqual(
            self.commande(), ["/venv/bin/python", "-u", "test/test_exemple.py"]
        )

    def test_k_and_random_order_go_through_unit_file(self):
        cmd = self.commande(motifs=["recherche"], ordre_aleatoire="42")
        self.assertIn(r.UNIT_FILE, cmd)
        self.assertEqual(cmd[cmd.index("-k") + 1], "recherche")
        self.assertIn("--ordre-aleatoire=42", cmd)

    def test_coverage_wraps_with_coverage_run(self):
        cmd = self.commande(couverture=True)
        self.assertEqual(
            cmd[:6], ["/venv/bin/python", "-u", "-m", "coverage", "run", "-p"]
        )
        self.assertTrue(cmd[6].startswith("--rcfile="))
        self.assertEqual(cmd[-1], "test/test_exemple.py")

    def test_coverage_gives_a_grace_by_default(self):
        ancien = os.environ.pop("UNIT_GRACE", None)
        self.addCleanup(
            lambda: ancien is not None and os.environ.update(UNIT_GRACE=ancien)
        )
        self.assertEqual(r.CampagneUnitaire(couverture=True).grace, 5)
        self.assertEqual(r.CampagneUnitaire().grace, 0)


class Historique(unittest.TestCase):
    """couverture.historiser et ecart, sur un coverage.json fabriqué."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)
        self.ancien = couverture.CACHE
        couverture.CACHE = self.d
        self.addCleanup(setattr, couverture, "CACHE", self.ancien)

    def ecrire_rapport(self, couvertes):
        os.makedirs(couverture.dossier("erplibre"), exist_ok=True)
        rapport = {
            "files": {
                "script/todo/a.py": {
                    "summary": {
                        "num_statements": 10,
                        "covered_lines": couvertes,
                        "num_branches": 0,
                        "covered_branches": 0,
                    }
                }
            },
            "totals": {
                "percent_covered": 10.0 * couvertes,
                "num_statements": 10,
                "covered_lines": couvertes,
                "num_branches": 0,
                "covered_branches": 0,
            },
        }
        with open(couverture.chemin_json("erplibre"), "w") as fh:
            json.dump(rapport, fh)

    def test_partial_runs_are_never_the_reference(self):
        self.ecrire_rapport(5)
        couverture.historiser("erplibre", complet=True)
        self.ecrire_rapport(2)
        couverture.historiser("erplibre", complet=False)
        self.ecrire_rapport(7)
        couverture.historiser("erplibre", complet=True)
        dernier, delta = couverture.ecart("erplibre")
        self.assertEqual(dernier["total"]["pourcentage"], 70.0)
        # Comparé au complet à 50 %, pas au partiel à 20 %.
        self.assertEqual(delta, 20.0)

    def test_summary_groups_by_directory(self):
        self.ecrire_rapport(4)
        ligne = couverture.historiser("erplibre", complet=True)
        self.assertEqual(ligne["dossiers"]["script/todo"]["couvertes"], 4)
        self.assertEqual(ligne["total"]["fichiers"], 1)

    def test_wrapping_keeps_interpreter_options_first(self):
        cmd = couverture.envelopper("erplibre", ["py", "-u", "f.py", "a"])
        self.assertEqual(cmd[:5], ["py", "-u", "-m", "coverage", "run"])
        self.assertEqual(cmd[-2:], ["f.py", "a"])


class Verrou(unittest.TestCase):
    def setUp(self):
        # Ce test tourne lui-même dans une campagne, que le verrou laisse
        # passer : il s'en sort pour éprouver le verrou d'une campagne neuve.
        hors = mock.patch.dict(os.environ)
        hors.start()
        self.addCleanup(hors.stop)
        os.environ.pop(moteur.DANS_UNE_CAMPAGNE, None)

    def test_a_second_campaign_is_refused_and_named(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        chemin = os.path.join(d, "campagne.lock")
        with moteur.verrou_campagne("scénarios", chemin):
            code = (
                "import sys; sys.path.insert(0, 'script/test');"
                "import lanceur;"
                f"lanceur.verrou_campagne('autre', {chemin!r}).__enter__()"
            )
            res = subprocess.run(
                [sys.executable, "-c", code],
                cwd=RACINE,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("scénarios", res.stderr)
        # Libéré à la sortie du with : la suivante passe.
        with moteur.verrou_campagne("suivante", chemin):
            pass

    def test_a_process_of_the_campaign_is_not_refused(self):
        """Un test qui exécute un passage du lanceur fait partie de la
        campagne qui l'a lancé : le verrou qu'elle tient le laisse passer."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        chemin = os.path.join(d, "campagne.lock")
        with moteur.verrou_campagne("tests unitaires", chemin):
            code = (
                "import sys; sys.path.insert(0, 'script/test');"
                "import lanceur;"
                f"lanceur.verrou_campagne('imbriquee', {chemin!r}).__enter__()"
            )
            res = subprocess.run(
                [sys.executable, "-c", code],
                cwd=RACINE,
                env=dict(os.environ, **{moteur.DANS_UNE_CAMPAGNE: "unitaire"}),
                capture_output=True,
                text=True,
            )
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
