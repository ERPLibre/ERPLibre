#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le verdict de chaque test unitaire, poussé vers le registre des requis.

Aucun test n'ouvre de connexion : `urllib.request.urlopen` est remplacé par
un faux registre qui répond comme Odoo en JSON-RPC et garde chaque appel.
Les références se jugent sur de vrais passages de unittest, par le lanceur
et unit_file.py : c'est leur forme réelle que le registre doit reconnaître.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RACINE, "script", "test"))

import requirement_report as rr  # noqa: E402
import run_unit_test as r  # noqa: E402

CLE = "cle-inventee-0123456789"

ENV = {
    "ERPLIBRE_REQUIREMENT_URL": "http://registre.invalid:8069/",
    "ERPLIBRE_REQUIREMENT_DB": "registre",
    "ERPLIBRE_REQUIREMENT_LOGIN": "lanceur",
    "ERPLIBRE_REQUIREMENT_KEY": CLE,
}

# Chaque issue que unittest connaît, sous-test et fixture de classe compris.
DEMO = """import unittest


class A(unittest.TestCase):
    def test_ok(self):
        pass

    def test_sub(self):
        for i in range(3):
            with self.subTest(i=i):
                self.assertNotEqual(i, 1)

    @unittest.skip("absent")
    def test_skip(self):
        pass

    def test_err(self):
        raise KeyError("x")


class B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raise RuntimeError("fixture")

    def test_b(self):
        pass


if __name__ == "__main__":
    unittest.main()
"""

PASSE = """import unittest


class T(unittest.TestCase):
    def test_vrai(self):
        pass


if __name__ == "__main__":
    unittest.main()
"""

FAUX = """import unittest


class T(unittest.TestCase):
    def test_faux(self):
        self.assertEqual(1, 2)


if __name__ == "__main__":
    unittest.main()
"""


def ref(fichier, test):
    return f"erplibre:test/{fichier}::{test}"


def entree(test, etat="ok", message="", duree=0.1):
    classe, nom = test.split("::")
    return {
        "id": f"mod.{classe}.{nom}",
        "classe": classe,
        "nom": nom,
        "duree": duree,
        "etat": etat,
        "message": message,
    }


class FauxRegistre:
    """Répond aux appels JSON-RPC du registre comme Odoo, et les garde.

    `declarees` : les références que search_read rend ; `lignes` : le nombre
    de lignes que chaque référence met à jour (1 par défaut) ; `uid` : ce
    que rend login ; `erreur` : {méthode: réponse d'erreur JSON-RPC}."""

    def __init__(self, declarees=(), lignes=None, uid=7, erreur=None):
        self.declarees = list(declarees)
        self.lignes = lignes or {}
        self.uid = uid
        self.erreur = erreur or {}
        self.appels = []

    def __call__(self, requete, timeout=None):
        corps = json.loads(requete.data.decode("utf-8"))
        params = corps["params"]
        self.appels.append((requete.full_url, params))
        methode = params["method"]
        if methode == "execute_kw":
            methode = params["args"][4]
        if methode in self.erreur:
            reponse = {"jsonrpc": "2.0", "id": corps["id"]}
            reponse["error"] = self.erreur[methode]
        else:
            reponse = {
                "jsonrpc": "2.0",
                "id": corps["id"],
                "result": self._resultat(methode, params["args"]),
            }
        return io.BytesIO(json.dumps(reponse).encode("utf-8"))

    def _resultat(self, methode, args):
        if methode == "login":
            return self.uid
        if methode == "search_read":
            return [
                {"id": n, "reference": reference}
                for n, reference in enumerate(self.declarees, 1)
            ]
        if methode == "record_result_by_reference":
            return self.lignes.get(args[5][1], 1)
        raise AssertionError(f"appel inattendu : {methode}")

    def envois(self):
        """(args, kwargs) de chaque record_result_by_reference, dans l'ordre."""
        return [
            (p["args"][5], p["args"][6])
            for _, p in self.appels
            if p["method"] == "execute_kw"
            and p["args"][4] == "record_result_by_reference"
        ]


def registre():
    return rr.Registre(
        "http://registre.invalid:8069", "registre", "lanceur", CLE
    )


def pousser(faux, essais, racine="/depot"):
    sortie = io.StringIO()
    with mock.patch("urllib.request.urlopen", faux):
        registre().pousser(essais, racine=racine, sortie=sortie)
    return sortie.getvalue()


class TestLaConfiguration(unittest.TestCase):
    def test_unset_environment_means_no_registry_and_no_output(self):
        sortie = io.StringIO()
        self.assertIsNone(rr.depuis_environnement({}, sortie))
        self.assertEqual(sortie.getvalue(), "")

    def test_a_partial_configuration_warns_once_and_sends_nothing(self):
        env = dict(ENV)
        del env["ERPLIBRE_REQUIREMENT_LOGIN"]
        sortie = io.StringIO()
        with mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("réseau")
        ):
            self.assertIsNone(rr.depuis_environnement(env, sortie))
        lignes = sortie.getvalue().splitlines()
        self.assertEqual(len(lignes), 1)
        self.assertIn("ERPLIBRE_REQUIREMENT_LOGIN", lignes[0])
        self.assertNotIn(CLE, sortie.getvalue())

    def test_only_an_http_url_is_accepted(self):
        for url in ("file:///etc/hosts", "ftp://registre.invalid/"):
            with self.subTest(url=url):
                sortie = io.StringIO()
                env = dict(ENV, ERPLIBRE_REQUIREMENT_URL=url)
                self.assertIsNone(rr.depuis_environnement(env, sortie))
                self.assertEqual(len(sortie.getvalue().splitlines()), 1)

    def test_a_complete_configuration_gives_a_silent_registry(self):
        sortie = io.StringIO()
        registre = rr.depuis_environnement(ENV, sortie)
        self.assertIsInstance(registre, rr.Registre)
        self.assertEqual(sortie.getvalue(), "")


class TestLesReferences(unittest.TestCase):
    def verdicts(self, *essais, declarees=(), racine="/depot"):
        return rr.verdicts_declares(essais, set(declarees), racine)

    def test_each_outcome_maps_to_a_registry_result(self):
        essai = rr.Essai(
            "/depot/test/test_demo.py",
            [
                entree("A::test_ok", duree=0.5),
                entree("A::test_faux", "echec", "AssertionError: 1"),
                entree("A::test_casse", "erreur", "KeyError: 'x'"),
                entree("A::test_saute", "ignore", "Textual absent"),
            ],
            None,
        )
        refs = {
            t: ref("test_demo.py", f"A::{t}")
            for t in ("test_ok", "test_faux", "test_casse", "test_saute")
        }
        verdicts = self.verdicts(essai, declarees=refs.values())
        self.assertEqual(
            {t: verdicts[refs[t]]["result"] for t in refs},
            {
                "test_ok": "passed",
                "test_faux": "failed",
                "test_casse": "error",
                "test_saute": "skipped",
            },
        )
        self.assertEqual(verdicts[refs["test_ok"]]["duration"], 0.5)
        self.assertIn("AssertionError: 1", verdicts[refs["test_faux"]]["log"])
        self.assertIn("Textual absent", verdicts[refs["test_saute"]]["log"])

    def test_only_declared_references_get_a_verdict(self):
        essai = rr.Essai(
            "/depot/test/test_demo.py",
            [entree("A::test_ok"), entree("A::test_cite_par_personne")],
            None,
        )
        declaree = ref("test_demo.py", "A::test_ok")
        self.assertEqual(
            list(self.verdicts(essai, declarees=[declaree])), [declaree]
        )

    def test_the_path_is_relative_to_the_repository_root(self):
        declaree = ref("test_demo.py", "A::test_ok")
        with tempfile.TemporaryDirectory() as racine:
            for chemin in (
                os.path.join(racine, "test", "test_demo.py"),
                os.path.join(racine, "test", "..", "test", "test_demo.py"),
            ):
                with self.subTest(chemin=chemin):
                    essai = rr.Essai(chemin, [entree("A::test_ok")], None)
                    self.assertIn(
                        declaree,
                        self.verdicts(
                            essai, declarees=[declaree], racine=racine
                        ),
                    )
            # Un fichier hors du dépôt n'a pas de référence « erplibre: ».
            dehors = rr.Essai("/ailleurs/test_demo.py", [entree("A::x")], None)
            self.assertEqual(rr.references(dehors, racine), {})

    def test_a_failing_subtest_fails_its_test(self):
        essai = rr.Essai(
            "/depot/test/test_demo.py",
            [
                entree("A::test_sub (i=0)", "ignore", "plus tard"),
                entree("A::test_sub (i=1)", "echec", "AssertionError: 1"),
            ],
            None,
        )
        declaree = ref("test_demo.py", "A::test_sub")
        verdict = self.verdicts(essai, declarees=[declaree])[declaree]
        self.assertEqual(verdict["result"], "failed")
        self.assertIn("AssertionError: 1", verdict["log"])

    def test_a_repeated_test_keeps_its_worst_outcome(self):
        chemin = "/depot/test/test_demo.py"
        declaree = ref("test_demo.py", "A::test_x")
        essais = [
            rr.Essai(chemin, [entree("A::test_x", duree=1.0)], None),
            rr.Essai(chemin, [entree("A::test_x", "echec", duree=2.0)], None),
            rr.Essai(chemin, [entree("A::test_x", duree=0.5)], None),
        ]
        verdict = self.verdicts(*essais, declarees=[declaree])[declaree]
        self.assertEqual(
            (verdict["result"], verdict["duration"]), ("failed", 2.0)
        )

    def test_a_class_fixture_reaches_the_declared_tests_of_its_class(self):
        essai = rr.Essai(
            "/depot/test/test_demo.py",
            [
                entree("A::test_ok"),
                entree("B::setUpClass", "erreur", "RuntimeError: fixture"),
                entree("C::setUpClass", "ignore", "dépôt absent"),
            ],
            None,
        )
        refs = [
            ref("test_demo.py", t)
            for t in ("A::test_ok", "B::test_b", "C::test_c")
        ]
        verdicts = self.verdicts(essai, declarees=refs)
        self.assertEqual(
            [verdicts[x]["result"] for x in refs],
            ["passed", "error", "skipped"],
        )
        self.assertIn("RuntimeError: fixture", verdicts[refs[1]]["log"])

    def test_a_file_without_detail_is_an_error_for_its_declared_tests(self):
        """Mort à l'import ou tué par le délai, le fichier n'a noté aucun
        test : ceux que le registre déclare passent en erreur plutôt que de
        garder un verdict qui n'est plus vrai."""
        casse = rr.Essai(
            "/depot/test/test_casse.py", [], "ImportError: no module x"
        )
        sain = rr.Essai("/depot/test/test_sain.py", [entree("S::t")], None)
        refs = [ref("test_casse.py", "K::t"), ref("test_sain.py", "S::t")]
        verdicts = self.verdicts(casse, sain, declarees=refs)
        self.assertEqual(verdicts[refs[0]]["result"], "error")
        self.assertIn("ImportError", verdicts[refs[0]]["log"])
        self.assertEqual(verdicts[refs[1]]["result"], "passed")


class TestDeVraisPassages(unittest.TestCase):
    """unit_file.py note chaque test, et ses notes deviennent les références
    que le registre déclare."""

    def test_every_outcome_of_a_real_run_reaches_its_reference(self):
        with tempfile.TemporaryDirectory() as racine:
            os.mkdir(os.path.join(racine, "test"))
            chemin = os.path.join(racine, "test", "test_demo.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(DEMO)
            lanceur = r.Lanceur(
                [chemin], sys.executable, 1, 60, {}, detaille=True
            )
            self.addCleanup(lanceur.nettoyer)
            lanceur.lancer()
            (f,) = lanceur.fichiers
            essai = rr.Essai(f.chemin, f.tests, None)
            refs = {
                t: ref("test_demo.py", t)
                for t in (
                    "A::test_ok",
                    "A::test_sub",
                    "A::test_skip",
                    "A::test_err",
                    "B::test_b",
                )
            }
            verdicts = rr.verdicts_declares(
                [essai], set(refs.values()), racine
            )
        self.assertEqual(
            {t: verdicts[x]["result"] for t, x in refs.items()},
            {
                "A::test_ok": "passed",
                "A::test_sub": "failed",
                "A::test_skip": "skipped",
                "A::test_err": "error",
                "B::test_b": "error",
            },
        )


class TestLEnvoi(unittest.TestCase):
    ESSAI = rr.Essai(
        "/depot/test/test_demo.py",
        [
            entree("A::test_ok", duree=0.25),
            entree("A::test_faux", "echec", "AssertionError: 1"),
            entree("A::test_cite_par_personne"),
        ],
        None,
    )
    OK = ref("test_demo.py", "A::test_ok")
    FAUX = ref("test_demo.py", "A::test_faux")
    PAS_LANCE = ref("test_demo.py", "A::test_pas_lance")

    def test_one_call_per_declared_reference_that_ran(self):
        faux = FauxRegistre(
            declarees=[self.OK, self.FAUX, self.FAUX, self.PAS_LANCE],
            lignes={self.OK: 2},
        )
        sortie = pousser(faux, [self.ESSAI])
        url, login = faux.appels[0]
        self.assertEqual(url, "http://registre.invalid:8069/jsonrpc")
        self.assertEqual(
            (login["service"], login["method"], login["args"]),
            ("common", "login", ["registre", "lanceur", CLE]),
        )
        lecture = faux.appels[1][1]["args"]
        self.assertEqual(
            lecture[:5],
            ["registre", 7, CLE, "devops.requirement.test", "search_read"],
        )
        self.assertEqual(
            lecture[5],
            [
                [
                    ["kind", "=", "repo_unittest"],
                    ["reference", "=like", "erplibre:%"],
                ]
            ],
        )
        self.assertEqual(
            sorted(faux.envois(), key=lambda e: e[0][1]),
            [
                (
                    ["repo_unittest", self.FAUX, "failed"],
                    {"log": "AssertionError: 1", "duration": 0.1},
                ),
                (
                    ["repo_unittest", self.OK, "passed"],
                    {"log": None, "duration": 0.25},
                ),
            ],
        )
        lignes = sortie.splitlines()
        self.assertEqual(len(lignes), 1)
        self.assertIn("2 verdicts", lignes[0])
        self.assertIn("3 lignes", lignes[0])
        self.assertNotIn(CLE, sortie)

    def test_a_failed_push_prints_one_warning_line(self):
        refuse = mock.Mock(
            side_effect=urllib.error.URLError("Connection refused")
        )
        sortie = pousser(refuse, [self.ESSAI])
        self.assertEqual(len(sortie.splitlines()), 1)
        self.assertIn("Connection refused", sortie)
        self.assertEqual(refuse.call_count, 1)

    def test_refused_credentials_stop_before_any_push(self):
        faux = FauxRegistre(declarees=[self.OK], uid=False)
        sortie = pousser(faux, [self.ESSAI])
        self.assertEqual(len(faux.appels), 1)
        self.assertEqual(len(sortie.splitlines()), 1)
        self.assertNotIn(CLE, sortie)

    def test_a_push_failing_midway_stops_at_the_first_failure(self):
        faux = FauxRegistre(
            declarees=[self.OK, self.FAUX],
            erreur={
                "record_result_by_reference": {
                    "code": 200,
                    "message": "Odoo Server Error",
                    "data": {
                        "name": "odoo.exceptions.AccessError",
                        "message": "Only a requirement test runner can "
                        "record a test result.",
                    },
                }
            },
        )
        sortie = pousser(faux, [self.ESSAI])
        self.assertEqual(len(faux.envois()), 1)
        lignes = sortie.splitlines()
        self.assertEqual(len(lignes), 1)
        self.assertIn("Only a requirement test runner", lignes[0])

    def test_the_key_is_never_printed_even_when_a_server_echoes_it(self):
        faux = FauxRegistre(
            erreur={
                "login": {
                    "code": 200,
                    "message": "Odoo Server Error",
                    "data": {"message": f"bad credentials\n{CLE}\nend"},
                }
            }
        )
        sortie = pousser(faux, [self.ESSAI])
        self.assertEqual(len(sortie.splitlines()), 1)
        self.assertNotIn(CLE, sortie)
        self.assertIn("bad credentials", sortie)


class TestLeLanceur(unittest.TestCase):
    """lancer_une_fois avec et sans le registre : le code de sortie est
    celui de la suite dans tous les cas."""

    def lancer(self, source, env):
        args = argparse.Namespace(
            tui=False, repeat=1, slowest=0, junit=None, jobs=1, timeout=60
        )
        sortie = io.StringIO()
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "test_lot.py")
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(source)
            reseau = mock.Mock(side_effect=urllib.error.URLError("refusé"))
            # Le cache des durées et des échecs est celui du poste : le test
            # ne le touche pas.
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch("urllib.request.urlopen", reseau),
                mock.patch.object(r, "lire_durees", return_value={}),
                mock.patch.object(r, "ecrire_durees"),
                mock.patch.object(r.unit_selection, "retenir_echecs"),
                mock.patch.object(r, "Lanceur", wraps=r.Lanceur) as lanceur,
                contextlib.redirect_stdout(sortie),
            ):
                for nom in rr.VARIABLES:
                    if nom not in env:
                        os.environ.pop(nom, None)
                code = r.lancer_une_fois([chemin], args)
        return code, sortie.getvalue(), reseau, lanceur

    def test_unset_environment_runs_as_before_and_opens_no_connection(self):
        for source, attendu in ((PASSE, 0), (FAUX, 1)):
            with self.subTest(attendu=attendu):
                code, sortie, reseau, lanceur = self.lancer(source, {})
                self.assertEqual(code, attendu)
                reseau.assert_not_called()
                self.assertNotIn("Registre", sortie)
                self.assertFalse(lanceur.call_args.kwargs["detaille"])

    def test_a_failed_push_leaves_the_exit_code_alone(self):
        for source, attendu in ((PASSE, 0), (FAUX, 1)):
            with self.subTest(attendu=attendu):
                code, sortie, reseau, lanceur = self.lancer(source, ENV)
                self.assertEqual(code, attendu)
                self.assertEqual(reseau.call_count, 1)
                registre = [x for x in sortie.splitlines() if "Registre" in x]
                self.assertEqual(len(registre), 1)
                self.assertNotIn(CLE, sortie)
                self.assertTrue(lanceur.call_args.kwargs["detaille"])


if __name__ == "__main__":
    unittest.main()
