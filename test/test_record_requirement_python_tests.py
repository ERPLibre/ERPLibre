#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La consignation des tests Python des requis, sans serveur ni Odoo.

Le verdict d'une ligne passe par deux lectures : le journal de ./test.sh
vers les tests qui relèvent de sa référence, puis ces tests vers une valeur
record_result. Chacune peut rendre un vert immérité sans bruit — une classe
dont le setUpClass tombe lue comme « aucun échec », TestA qui ramasse les
tests de TestAB, un journal coupé avant ses échecs. Ces tests les fixent sur
des extraits de journaux au format d'Odoo 18 (odoo/tests/result.py et
suite.py), et un serveur XML-RPC simulé.

Modules, classes, codes et identifiants sont inventés.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.test import record_requirement_python_tests as rpt  # noqa: E402

BASE = "base_inventee"
MOD_A = "odoo.addons.module_alpha.tests.test_un"
MOD_B = "odoo.addons.module_beta.tests.test_deux"


def entete(seconde, logger, message, niveau="INFO", base=BASE):
    """Rend une ligne au format du journal d'Odoo, espace final compris."""
    return (
        f"2031-02-03 04:05:{seconde:06.3f}".replace(".", ",")
        + f" 4242 {niveau} {base} {logger}: {message} "
    )


def demarre(s, logger, test):
    return [entete(s, logger, f"Starting {test} ...")]


def echec(s, logger, sorte, desc, exception="AssertionError: 1 != 2"):
    return [
        entete(s, logger, "=" * 70),
        entete(s, logger, f"{sorte}: {desc}", niveau="ERROR"),
        "Traceback (most recent call last):",
        '  File "/chemin/invente/test_un.py", line 12, in test_x',
        "    self.assertEqual(1, 2)",
        exception,
        " ",
    ]


def saute(s, logger, desc, raison="raison inventee"):
    return [entete(s, logger, f"skipped {desc} : {raison}")]


def bilan(s, failed=0, errors=0, tests=1):
    return [
        entete(s, "odoo.service.server", f"{tests} post-tests in 1.00s"),
        entete(
            s,
            "odoo.tests.result",
            f"{failed} failed, {errors} error(s) of {tests} tests when"
            f" loading database '{BASE}'",
            niveau="ERROR" if failed or errors else "INFO",
        ),
    ]


def journal(*morceaux):
    lignes = [entete(0, "odoo.service.server", "Starting post tests")]
    for morceau in morceaux:
        lignes += morceau
    return [ligne + "\n" for ligne in lignes]


def ref(texte):
    decompose = rpt.lire_reference(texte)
    assert decompose, texte
    return decompose


def verdict(reference, lignes):
    return rpt.verdict_reference(ref(reference), rpt.analyser_journal(lignes))


class TestReference(unittest.TestCase):
    def test_methode_et_classe(self):
        self.assertEqual(
            rpt.lire_reference(f"{MOD_A}.TestA.test_x"),
            {
                "module": "module_alpha",
                "module_py": MOD_A,
                "classe": "TestA",
                "methode": "test_x",
            },
        )
        self.assertIsNone(rpt.lire_reference(f"{MOD_A}.TestA")["methode"])

    def test_sous_dossier_de_tests(self):
        r = rpt.lire_reference("odoo.addons.mod_x.tests.sous.test_y.TestZ")
        self.assertEqual(r["module_py"], "odoo.addons.mod_x.tests.sous.test_y")
        self.assertEqual(r["classe"], "TestZ")

    def test_illisibles(self):
        for texte in (
            "",
            "module_alpha.tests.test_un.TestA",
            f"{MOD_A}",
            f"{MOD_A}.test_x",
            f"{MOD_A}.TestA.helper",
            "odoo.addons.module_alpha.TestA",
            f"{MOD_A}.TestA.test x",
        ):
            self.assertIsNone(rpt.lire_reference(texte), texte)


class TestEtiquettes(unittest.TestCase):
    def test_classe_absorbe_ses_methodes_et_forme_fichier(self):
        modules, tags = rpt.etiquettes_tests(
            [
                ref(f"{MOD_A}.TestA.test_x"),
                ref(f"{MOD_A}.TestA"),
                ref(f"{MOD_A}.TestAB.test_y"),
                ref(f"{MOD_B}.TestA.test_x"),
                ref(f"{MOD_B}.TestA.test_x"),
            ]
        )
        self.assertEqual(modules, ["module_alpha", "module_beta"])
        self.assertEqual(
            tags,
            [
                "*/module_alpha/tests/test_un.py:TestA",
                "*/module_alpha/tests/test_un.py:TestAB.test_y",
                "*/module_beta/tests/test_deux.py:TestA.test_x",
            ],
        )

    def test_impression(self):
        lignes, manquants = rpt.lignes_a_traiter(
            [
                {"requirement_id": [1, "R"], "reference": f"{MOD_A}.TestA"},
                {"requirement_id": [1, "R"], "reference": "pas.une.reference"},
            ],
            {1: "COD-01"},
            ["COD-01", "COD-99"],
        )
        sortie, erreurs = io.StringIO(), io.StringIO()
        code = rpt.imprimer_test_tags(lignes, manquants, sortie, erreurs)
        self.assertEqual(code, 2)
        self.assertEqual(
            sortie.getvalue().splitlines(),
            [
                "modules=module_alpha",
                "test_tags=*/module_alpha/tests/test_un.py:TestA",
            ],
        )
        self.assertIn("COD-99", erreurs.getvalue())
        self.assertIn("pas.une.reference", erreurs.getvalue())


class TestVerdict(unittest.TestCase):
    def test_methode_passee(self):
        v = verdict(
            f"{MOD_A}.TestA.test_x",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                demarre(2, MOD_A, "TestA.test_x"),
                demarre(5, MOD_A, "TestA.test_y"),
                echec(6, MOD_A, "FAIL", "TestA.test_y"),
                bilan(7, failed=1, tests=3),
            ),
        )
        self.assertEqual(v["resultat"], "passed")
        self.assertEqual(
            v["tests"], [{"nom": "TestA.test_x", "resultat": "passed"}]
        )
        self.assertEqual(v["duree"], 3.0)
        self.assertIn("passed: TestA.test_x", v["journal"])

    def test_classe_entiere_passee(self):
        v = verdict(
            f"{MOD_A}.TestA",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                demarre(2, MOD_A, "TestA.test_x"),
                bilan(4, tests=2),
            ),
        )
        self.assertEqual(v["resultat"], "passed")
        self.assertEqual(len(v["tests"]), 2)
        self.assertEqual(v["duree"], 3.0)

    def test_fail(self):
        v = verdict(
            f"{MOD_A}.TestA",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                echec(1, MOD_A, "ERROR", "TestA.test_w", "RuntimeError: x"),
                demarre(2, MOD_A, "TestA.test_x"),
                echec(2, MOD_A, "FAIL", "TestA.test_x"),
                bilan(3, failed=1, errors=1, tests=2),
            ),
        )
        self.assertEqual(v["resultat"], "failed")
        self.assertIn("FAIL: TestA.test_x", v["journal"])
        self.assertIn("AssertionError: 1 != 2", v["journal"])
        self.assertIn("RuntimeError: x", v["journal"])

    def test_error(self):
        v = verdict(
            f"{MOD_A}.TestA.test_w",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                echec(1, MOD_A, "ERROR", "TestA.test_w", "RuntimeError: x"),
                bilan(2, errors=1),
            ),
        )
        self.assertEqual(v["resultat"], "error")

    def test_sous_test_en_echec(self):
        v = verdict(
            f"{MOD_A}.TestA.test_w",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                echec(1, MOD_A, "FAIL", "Subtest TestA.test_w (i=1)"),
                bilan(2, failed=1),
            ),
        )
        self.assertEqual(v["resultat"], "failed")

    def test_setupclass_en_echec_fait_tomber_la_classe(self):
        lignes = journal(
            echec(
                1,
                "odoo.tests.suite",
                "ERROR",
                f"setUpClass ({MOD_A}.TestA)",
                "ValueError: invente",
            ),
            bilan(2, errors=1, tests=0),
        )
        for reference in (f"{MOD_A}.TestA", f"{MOD_A}.TestA.test_x"):
            v = verdict(reference, lignes)
            self.assertEqual(v["resultat"], "error", reference)
            self.assertIn("ValueError: invente", v["journal"])
            self.assertIsNone(v["duree"])
        # Une classe dont le nom prolonge celui de la classe en échec
        self.assertIsNone(verdict(f"{MOD_A}.TestAB", lignes))

    def test_teardownclass_en_echec(self):
        v = verdict(
            f"{MOD_A}.TestA",
            journal(
                demarre(1, MOD_A, "TestA.test_x"),
                echec(
                    2,
                    "odoo.tests.suite",
                    "ERROR",
                    f"tearDownClass ({MOD_A}.TestA)",
                ),
                bilan(3, errors=1),
            ),
        )
        self.assertEqual(v["resultat"], "error")

    def test_saute(self):
        v = verdict(
            f"{MOD_A}.TestA",
            journal(
                demarre(1, MOD_A, "TestA.test_x"),
                saute(1, MOD_A, "TestA.test_x"),
                bilan(2),
            ),
        )
        self.assertEqual(v["resultat"], "skipped")
        self.assertIn("raison inventee", v["journal"])

    def test_classe_sautee_au_setupclass(self):
        v = verdict(
            f"{MOD_A}.TestA.test_x",
            journal(
                saute(1, "odoo.tests.suite", f"setUpClass ({MOD_A}.TestA)"),
                bilan(2, tests=0),
            ),
        )
        self.assertEqual(v["resultat"], "skipped")

    def test_un_saut_parmi_des_reussites_reste_passed(self):
        v = verdict(
            f"{MOD_A}.TestA",
            journal(
                demarre(1, MOD_A, "TestA.test_w"),
                demarre(2, MOD_A, "TestA.test_x"),
                saute(2, MOD_A, "TestA.test_x"),
                bilan(3, tests=2),
            ),
        )
        self.assertEqual(v["resultat"], "passed")
        self.assertIn("skipped: TestA.test_x (raison inventee)", v["journal"])

    def test_absent(self):
        lignes = journal(demarre(1, MOD_A, "TestA.test_w"), bilan(2))
        self.assertIsNone(verdict(f"{MOD_A}.TestA.test_x", lignes))
        self.assertIsNone(verdict(f"{MOD_A}.TestZ", lignes))

    def test_classe_prefixe_d_une_autre(self):
        lignes = journal(
            demarre(1, MOD_A, "TestAB.test_x"),
            echec(1, MOD_A, "FAIL", "TestAB.test_x"),
            demarre(2, MOD_A, "TestA.test_x"),
            bilan(3, failed=1, tests=2),
        )
        self.assertEqual(
            verdict(f"{MOD_A}.TestA", lignes)["resultat"], "passed"
        )
        self.assertEqual(
            verdict(f"{MOD_A}.TestAB", lignes)["resultat"], "failed"
        )
        self.assertEqual(
            verdict(f"{MOD_A}.TestA.test_x", lignes)["tests"],
            [{"nom": "TestA.test_x", "resultat": "passed"}],
        )

    def test_meme_classe_dans_deux_modules(self):
        lignes = journal(
            demarre(1, MOD_A, "TestA.test_x"),
            demarre(2, MOD_B, "TestA.test_x"),
            echec(2, MOD_B, "FAIL", "TestA.test_x"),
            bilan(3, failed=1, tests=2),
        )
        self.assertEqual(
            verdict(f"{MOD_A}.TestA.test_x", lignes)["resultat"], "passed"
        )
        self.assertEqual(
            verdict(f"{MOD_B}.TestA.test_x", lignes)["resultat"], "failed"
        )

    def test_journal_tronque(self):
        lignes = journal(demarre(1, MOD_A, "TestA.test_x"))
        with self.assertRaises(rpt.JournalInvalide):
            rpt.analyser_journal(lignes)

    def test_tentative_relancee_jugee_sur_la_derniere(self):
        # ODOO_TEST_FAILURE_RETRIES : le FAIL de la première tentative est
        # journalisé sous soft_fail, sans être compté au bilan.
        v = verdict(
            f"{MOD_A}.TestA.test_x",
            journal(
                demarre(1, MOD_A, "TestA.test_x"),
                echec(1, MOD_A, "FAIL", "TestA.test_x"),
                demarre(2, MOD_A, "TestA.test_x"),
                bilan(3, tests=2),
            ),
        )
        self.assertEqual(v["resultat"], "passed")
        self.assertIn("2 tentatives", v["journal"])

    def test_sous_test_saute_ne_saute_pas_le_test(self):
        v = verdict(
            f"{MOD_A}.TestA.test_x",
            journal(
                demarre(1, MOD_A, "TestA.test_x"),
                saute(1, MOD_A, "Subtest TestA.test_x (i=1)", "cas absent"),
                bilan(2),
            ),
        )
        self.assertEqual(v["resultat"], "passed")
        self.assertIn("sous-test sauté : cas absent", v["journal"])

    def test_passe_abandonnee_ou_coupee_refusee(self):
        # server.run écrit le bilan même après l'abandon : les tests
        # post_install manquent sans qu'aucun compte ne le montre.
        for logger, message in (
            ("odoo.service.server", "Failed to initialize database `x`."),
            ("odoo.modules.registry", "Failed to load registry"),
            (
                "odoo.tests.result",
                "Test suite halted: max failed tests already reached (1).",
            ),
        ):
            lignes = journal(
                demarre(1, MOD_A, "TestA.test_x"),
                [entete(2, logger, message, niveau="ERROR")],
                bilan(3),
            )
            with self.assertRaises(rpt.JournalInvalide, msg=message):
                rpt.analyser_journal(lignes)

    def test_bilan_qui_ne_recoupe_pas_refuse(self):
        for morceaux in (
            # un « Starting » manque : journal coupé ou niveau trop haut
            (demarre(1, MOD_A, "TestA.test_x"), bilan(2, tests=2)),
            # un échec compté au bilan n'est pas au journal
            (demarre(1, MOD_A, "TestA.test_x"), bilan(2, failed=1)),
            (
                demarre(1, MOD_A, "TestA.test_x"),
                echec(1, MOD_A, "ERROR", "TestA.test_x"),
                bilan(2, failed=1),
            ),
        ):
            with self.assertRaises(rpt.JournalInvalide):
                rpt.analyser_journal(journal(*morceaux))

    def test_journal_de_deux_passes_refuse(self):
        complete = journal(demarre(1, MOD_A, "TestA.test_x"), bilan(2))
        for suite in (
            journal(demarre(3, MOD_A, "TestA.test_y")),
            journal(demarre(3, MOD_A, "TestA.test_y"), bilan(4)),
        ):
            with self.assertRaises(rpt.JournalInvalide):
                rpt.analyser_journal(complete + suite)

    def test_tests_de_deux_bases_refuses(self):
        lignes = journal(
            [entete(1, MOD_A, "Starting TestA.test_x ...", base="autre_base")],
            bilan(2),
        )
        with self.assertRaises(rpt.JournalInvalide):
            rpt.analyser_journal(lignes)

    def test_couleurs_du_terminal(self):
        lignes = [
            "\x1b[1;32m" + x if "Starting TestA" in x else x
            for x in journal(demarre(1, MOD_A, "TestA.test_x"), bilan(2))
        ]
        self.assertEqual(
            verdict(f"{MOD_A}.TestA", lignes)["resultat"], "passed"
        )

    def test_trace_bornee_fin_gardee(self):
        longue = "x" * 5000 + "\nAssertionError: fin"
        bornee = rpt.borner_trace(longue)
        self.assertLessEqual(len(bornee), rpt.LIMITE_TRACE)
        self.assertTrue(bornee.endswith("AssertionError: fin"))
        self.assertLessEqual(
            len(rpt.tronquer("y" * 20000)), rpt.LIMITE_JOURNAL
        )


class TestCodeDeSortie(unittest.TestCase):
    def ligne(self, resultat, **kw):
        ligne = rpt._ligne_rapport("COD-01", "r")
        ligne["resultat"] = resultat
        ligne.update(kw)
        return ligne

    def test_issues(self):
        self.assertEqual(rpt.code_de_sortie([self.ligne("passed")]), 0)
        self.assertEqual(
            rpt.code_de_sortie([self.ligne("passed"), self.ligne(None)]), 0
        )
        self.assertEqual(rpt.code_de_sortie([self.ligne("skipped")]), 0)
        self.assertEqual(rpt.code_de_sortie([self.ligne("error")]), 1)
        self.assertEqual(rpt.code_de_sortie([self.ligne("failed")]), 1)
        self.assertEqual(rpt.code_de_sortie([self.ligne(None)]), 2)
        self.assertEqual(rpt.code_de_sortie([]), 2)
        self.assertEqual(
            rpt.code_de_sortie([self.ligne("passed", remonte=False)]), 2
        )
        self.assertEqual(
            rpt.code_de_sortie(
                [self.ligne("failed"), self.ligne(None, erreur="illisible")]
            ),
            2,
        )
        self.assertEqual(rpt.code_de_sortie([self.ligne("passed")], "x"), 2)


class FauxRpc:
    def __init__(self, lignes, codes, retour=True):
        self.lignes = lignes
        self.codes = codes
        self.retour = retour
        self.ecrits = []

    def appel(self, modele, methode, args, kwargs=None):
        if methode == "search_read":
            return self.lignes
        if methode == "read":
            return [{"id": i, "code": c} for i, c in self.codes.items()]
        if methode == "record_result":
            self.ecrits.append((args, kwargs))
            return self.retour
        raise AssertionError(methode)


class TestBoutEnBout(unittest.TestCase):
    """main() sur un serveur simulé : écriture, dry_run, refus."""

    ENV = {
        rpt.ENV_LOGIN_DEFAUT: "exec_invente",
        rpt.ENV_PASSWORD_DEFAUT: "mdp-invente-5150",
    }

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.journal = os.path.join(self.dossier.name, "test.log")
        self.rapport = os.path.join(self.dossier.name, "rapport.json")
        with open(self.journal, "w", encoding="utf-8") as f:
            f.writelines(
                journal(
                    demarre(1, MOD_A, "TestA.test_x"),
                    demarre(2, MOD_A, "TestAB.test_y"),
                    echec(2, MOD_A, "FAIL", "TestAB.test_y"),
                    bilan(3, failed=1, tests=2),
                )
            )
        self.faux = FauxRpc(
            [
                {"requirement_id": [1, "R1"], "reference": f"{MOD_A}.TestA"},
                {"requirement_id": [2, "R2"], "reference": f"{MOD_A}.TestAB"},
                {"requirement_id": [2, "R2"], "reference": f"{MOD_B}.TestC"},
            ],
            {1: "COD-01", 2: "COD-02"},
        )

    def lancer(self, *argv, environ=None):
        argv = ["--db", BASE, "--report_json", self.rapport] + list(argv)
        with mock.patch.object(
            rpt.Rpc, "authentifier", return_value=7
        ), mock.patch.object(
            rpt.Rpc, "appel", side_effect=self.faux.appel
        ), mock.patch(
            "builtins.print"
        ):
            code = rpt.main(
                argv, environ=self.ENV if environ is None else environ
            )
        return code

    def lire_rapport(self):
        with open(self.rapport, encoding="utf-8") as f:
            return json.load(f)

    def test_consigne_et_rapporte(self):
        self.assertEqual(self.lancer("--log", self.journal), 1)
        ecrits = {a[2]: (a[3], kw) for a, kw in self.faux.ecrits}
        self.assertEqual(set(ecrits), {f"{MOD_A}.TestA", f"{MOD_A}.TestAB"})
        self.assertEqual(ecrits[f"{MOD_A}.TestA"][0], "passed")
        self.assertEqual(ecrits[f"{MOD_A}.TestAB"][0], "failed")
        self.assertEqual(self.faux.ecrits[0][0][1], "python")
        rapport = self.lire_rapport()
        self.assertEqual(rapport["totaux"]["non_vu"], 1)
        self.assertEqual(rapport["bilan_journal"]["failed"], 1)
        self.assertNotIn("mdp-invente-5150", json.dumps(rapport))

    def test_require_all_seen_ecrit_les_vues_et_sort_a_2(self):
        self.assertEqual(
            self.lancer("--log", self.journal, "--require_all_seen"), 2
        )
        self.assertEqual(len(self.faux.ecrits), 2)
        self.assertIn("non vue", self.lire_rapport()["erreur_outil"])

    def test_dry_run_n_ecrit_rien(self):
        self.assertEqual(self.lancer("--log", self.journal, "--dry_run"), 1)
        self.assertEqual(self.faux.ecrits, [])

    def test_journal_tronque_n_ecrit_rien(self):
        with open(self.journal, "w", encoding="utf-8") as f:
            f.writelines(journal(demarre(1, MOD_A, "TestA.test_x")))
        self.assertEqual(self.lancer("--log", self.journal), 2)
        self.assertEqual(self.faux.ecrits, [])
        self.assertIn("tronqué", self.lire_rapport()["erreur_outil"])

    def test_verdict_non_remonte(self):
        self.faux.retour = False
        self.assertEqual(self.lancer("--log", self.journal), 2)

    def test_sans_identifiants(self):
        self.assertEqual(self.lancer("--log", self.journal, environ={}), 2)
        self.assertEqual(self.faux.ecrits, [])

    def test_print_test_tags_n_ecrit_rien(self):
        sortie = io.StringIO()
        with mock.patch("sys.stdout", sortie):
            code = self.lancer("--print-test-tags")
        self.assertEqual(code, 0)
        self.assertEqual(self.faux.ecrits, [])
        self.assertFalse(os.path.exists(self.rapport))

    def test_abreviation_refusee(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.lancer("--print-test")


if __name__ == "__main__":
    unittest.main()
