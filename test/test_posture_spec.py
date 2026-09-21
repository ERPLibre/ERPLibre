#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Trois champs, trois questions, et la preuve qu'aucun n'en cache un autre.

Les confondre produit deux accidents symétriques : une maquette de
démonstration qui parle à tout l'Internet parce qu'elle n'est « pas en
production », et une machine de production confinée au point de ne plus
pouvoir se mettre à jour. L'indépendance n'est pas une intention de
conception — c'est une propriété, et elle s'éprouve.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script import posture as P  # noqa: E402


class TestLIndependanceDesTroisChamps(unittest.TestCase):
    def test_each_field_reads_back_what_was_put_there(self):
        """Seize combinaisons : aucune n'est réécrite en chemin."""
        vus = 0
        for prod in (False, True):
            for reelles in (False, True):
                for nom in P.posture_names():
                    spec = {
                        "install": {"prod": prod},
                        "posture": nom,
                        "real_data": reelles,
                    }
                    with self.subTest(
                        prod=prod, real_data=reelles, posture=nom
                    ):
                        self.assertEqual(nom, P.posture_name(spec))
                        self.assertEqual(reelles, P.real_data(spec))
                        self.assertEqual(prod, spec["install"]["prod"])
                    vus += 1
        self.assertEqual(4 * len(P.posture_names()), vus)

    def test_the_verdict_ignores_where_it_installs(self):
        """« En production » ne dit RIEN de ce que le réseau atteint, et
        laisser l'un décider de l'autre est l'erreur que ces champs
        séparent."""
        for nom in P.posture_names():
            for reelles in (False, True):
                with self.subTest(posture=nom, real_data=reelles):
                    base = {"posture": nom, "real_data": reelles}
                    self.assertEqual(
                        P.check(base),
                        P.check(dict(base, install={"prod": True})),
                    )
                    self.assertEqual(
                        P.check(base),
                        P.check(dict(base, install={"prod": False})),
                    )

    def test_the_posture_does_not_decide_the_data(self):
        """Une posture confinée n'implique pas qu'on y METTE des données
        réelles ; c'est une permission, pas une déclaration."""
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                self.assertFalse(P.real_data({"posture": nom}))


class TestCeQuUnSpecMuetVeutDire(unittest.TestCase):
    def test_a_spec_written_before_postures_still_deploys(self):
        """Il n'en nomme aucune, et doit se comporter comme avant."""
        self.assertEqual(P.DEFAULT_POSTURE, P.posture_name({}))
        self.assertEqual(P.OK, P.check({}))
        self.assertEqual(P.OK, P.check(None))

    def test_real_data_defaults_to_no(self):
        """Le doute penche du côté qui ne promet rien : l'inverse ferait
        d'un spec incomplet une machine qu'on croit protégée."""
        self.assertFalse(P.real_data({}))
        self.assertFalse(P.real_data(None))

    def test_an_empty_posture_field_is_the_default_and_not_an_error(self):
        self.assertEqual(P.DEFAULT_POSTURE, P.posture_name({"posture": ""}))


class TestUnePostureInconnueNeSeReplieePas(unittest.TestCase):
    """Se replier déploierait en sortie libre un spec qui demandait du
    confinement — le sens exactement inverse de la demande."""

    def test_it_answers_none_rather_than_the_default(self):
        self.assertIsNone(P.posture_of({"posture": "jamais-vue"}))

    def test_the_verdict_names_it(self):
        self.assertEqual(P.UNKNOWN_POSTURE, P.check({"posture": "jamais-vue"}))

    def test_a_known_posture_resolves(self):
        """Contrôle positif : tout refuser passerait les deux d'au-dessus."""
        self.assertIsNotNone(P.posture_of({"posture": "paranoid"}))


class TestLaRegleDOrAuPointOuElleSeDecide(unittest.TestCase):
    def test_real_data_under_an_unconfined_posture_is_refused(self):
        self.assertEqual(
            P.REAL_DATA_UNCONFINED,
            P.check({"posture": "open", "real_data": True}),
        )

    def test_real_data_under_a_confined_posture_passes(self):
        self.assertEqual(
            P.OK, P.check({"posture": "local-only", "real_data": True})
        )

    def test_without_real_data_every_posture_passes(self):
        """Une maquette a le droit d'être ouverte ; c'est la donnée qui
        contraint, pas la posture."""
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                self.assertEqual(P.OK, P.check({"posture": nom}))

    def test_the_refusal_agrees_with_the_registry(self):
        """Deux endroits qui répondent séparément finiraient par diverger."""
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                attendu = (
                    P.OK
                    if P.allows_real_data(P.get_posture(nom))
                    else P.REAL_DATA_UNCONFINED
                )
                self.assertEqual(
                    attendu, P.check({"posture": nom, "real_data": True})
                )

    def test_every_verdict_is_in_the_closed_vocabulary(self):
        self.assertTrue(P.SPEC_VERDICTS)
        cas = (
            {},
            {"posture": "jamais-vue"},
            {"posture": "open", "real_data": True},
            {"posture": "local-only", "real_data": True},
        )
        for spec in cas:
            with self.subTest(spec=spec):
                self.assertIn(P.check(spec), P.SPEC_VERDICTS)


class TestElleNAfficheRien(unittest.TestCase):
    """Le verdict est un jeton ; deux écrans le rendent différemment."""

    def test_the_module_neither_prints_nor_translates(self):
        import ast

        chemin = os.path.join(RACINE, "script", "posture", "spec.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertTrue(appels, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "t"):
            self.assertNotIn(interdit, appels)


if __name__ == "__main__":
    unittest.main()
