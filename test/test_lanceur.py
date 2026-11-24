#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur des lanceurs (`script/test/lanceur.py`), sur de vrais
processus.

Ce que ces tests gardent :

- les phases s'enchaînent dans l'ordre, avec une barrière, même après un
  échec ; jamais après un arrêt ;
- le démontage de la campagne tourne dans tous les cas, après la mort des
  groupes, y compris quand un second Ctrl+C tombe pendant la grâce ;
- une faute du lanceur sur un élément fait échouer cet élément, et le
  passage continue ;
- le bilan ne dit jamais « tout vert » pour un élément jamais terminé, ni
  quand aucun test n'a tourné.
"""

import contextlib
import io
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import lanceur as moteur  # noqa: E402


class Campagne(moteur.Campagne):
    """Des éléments qui sont des commandes sh ; le journal de la campagne
    note l'ordre des phases et le démontage."""

    def __init__(self, grace=0.0):
        self.grace = grace
        self.journal = []

    def commande(self, lanceur, element, base):
        return ["sh", "-c", element.chemin]

    def entre_phases(self, lanceur, phase):
        self.journal.append(("phase", phase))

    def demontage(self, lanceur):
        vivants = [
            f.nom for f in lanceur.fichiers if f.etat == moteur.EN_COURS
        ]
        self.journal.append(("demontage", vivants))


def element(cmd, nom, phase=0):
    return moteur.Element(cmd, nom=nom, phase=phase)


def lanceur(elements, campagne, delai=30):
    l = moteur.Lanceur(
        elements, "python", jobs=4, delai=delai, durees={}, campagne=campagne
    )
    return l


class Phases(unittest.TestCase):
    def test_phases_run_in_order_after_a_failure(self):
        c = Campagne()
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        trace = os.path.join(d, "trace")
        l = lanceur(
            [
                element(f"sleep 0.3; echo a >> {trace}; exit 1", "a", 0),
                element(f"echo b >> {trace}", "b", 10),
            ],
            c,
        )
        self.addCleanup(l.nettoyer)
        l.lancer()
        with open(trace) as fh:
            self.assertEqual(fh.read().split(), ["a", "b"])
        etats = {f.nom: f.etat for f in l.fichiers}
        self.assertEqual(etats, {"a": moteur.ECHEC, "b": moteur.OK})
        self.assertEqual(c.journal, [("phase", 10), ("demontage", [])])

    def test_no_phase_after_a_stop(self):
        c = Campagne()
        l = lanceur([element("sleep 30", "a", 0), element("true", "b", 1)], c)
        self.addCleanup(l.nettoyer)
        fil = threading.Thread(target=l.lancer)
        fil.start()
        while not l.en_cours():
            time.sleep(0.02)
        l.arreter()
        fil.join(10)
        self.assertFalse(fil.is_alive())
        etats = {f.nom: f.etat for f in l.fichiers}
        self.assertEqual(etats, {"a": moteur.ARRETE, "b": moteur.ARRETE})
        self.assertEqual(c.journal, [("demontage", [])])


class ArretPendantLaGrace(unittest.TestCase):
    def test_second_ctrl_c_during_the_grace_still_tears_down(self):
        """Le premier Ctrl+C ouvre la grâce, le second tombe dedans : les
        groupes partent au SIGKILL, et le démontage a quand même lieu avant
        que le bilan ne rende la main."""
        ancien = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, ancien)
        c = Campagne(grace=30)
        l = lanceur(
            [element("trap '' TERM; while :; do sleep 0.05; done", "tenace")],
            c,
        )
        self.addCleanup(l.nettoyer)
        principal = threading.get_ident()

        def interrompre():
            while not l.en_cours():
                time.sleep(0.02)
            signal.pthread_kill(principal, signal.SIGINT)
            time.sleep(0.5)
            signal.pthread_kill(principal, signal.SIGINT)

        threading.Thread(target=interrompre, daemon=True).start()
        debut = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            code = moteur.en_ligne(l)
        self.assertLess(time.monotonic() - debut, 10)
        self.assertEqual(code, 130)
        self.assertEqual(c.journal, [("demontage", [])])


class Bilan(unittest.TestCase):
    def bilan(self, l):
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = moteur.bilan(l)
        return code, sortie.getvalue()

    def test_an_engine_fault_fails_its_element_only(self):
        class Fautive(Campagne):
            def commande(self, lanceur, element, base):
                if element.nom == "casse":
                    raise ValueError("commande impossible")
                return super().commande(lanceur, element, base)

        l = lanceur(
            [element("true", "casse"), element("true", "bon")], Fautive()
        )
        self.addCleanup(l.nettoyer)
        l.lancer()
        code, sortie = self.bilan(l)
        self.assertEqual(code, 1)
        self.assertIn("commande impossible", sortie)
        self.assertEqual(
            {f.nom: f.etat for f in l.fichiers},
            {"casse": moteur.ECHEC, "bon": moteur.OK},
        )

    def test_an_unfinished_element_is_never_green(self):
        l = lanceur([element("true", "jamais")], Campagne())
        self.addCleanup(l.nettoyer)
        l.debut = l.fin = time.monotonic()
        code, sortie = self.bilan(l)
        self.assertEqual(code, 1)
        self.assertIn("jamais", sortie)

    def test_no_test_run_is_not_green(self):
        l = lanceur([element("true", "vide")], Campagne())
        self.addCleanup(l.nettoyer)
        l.lancer()
        l.fichiers[0].ran = "0"
        code, sortie = self.bilan(l)
        self.assertEqual(code, 5)
        self.assertIn("aucun test", sortie)


if __name__ == "__main__":
    unittest.main()
