#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que le vocabulaire de rapport promet, et que rien d'autre ne garde.

Un code renuméroté, une marque devenue émoji, une suite vide rendue « tout
va bien », un rendeur qui se met à imprimer : chacun casse en silence un
appelant qui n'existe pas encore. Ces épreuves sont ce qui rend le contrat
opposable avant qu'il ait des consommateurs.
"""

import ast
import contextlib
import io
import os
import sys
import unicodedata
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import devstack_report as R  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

SOURCE = os.path.join(RACINE, "script", "todo", "devstack_report.py")


def en_francais(case):
    """Fixe la langue pour la durée d'un test, et la rend ensuite.

    `set_lang` écrirait la langue dans un fichier SUIVI : un test qui la
    change laisserait une modification derrière lui.
    """
    case.addCleanup(
        setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
    )
    todo_i18n._current_lang = "fr"


class TestLesCinqCodes(unittest.TestCase):
    """Un code renuméroté casse un appelant qui lit un entier nu."""

    def test_the_five_codes_keep_their_documented_values(self):
        self.assertEqual(0, R.DS_OK)
        self.assertEqual(1, R.DS_ERR)
        self.assertEqual(10, R.DS_REFUSED)
        self.assertEqual(20, R.DS_SKIP)
        self.assertEqual(21, R.DS_UNIMPLEMENTED)

    def test_they_are_pairwise_distinct(self):
        self.assertEqual(5, len(set(R.CODES)))

    def test_every_code_has_a_mark_and_a_token(self):
        self.assertEqual(
            5, len(R.CODES), "vocabulaire vidé : rien n'est prouvé"
        )
        for code in R.CODES:
            with self.subTest(code=code):
                self.assertIn(code, R.MARKS)
                self.assertNotEqual("unexpected", R.code_token(code))

    def test_report_tells_the_five_apart(self):
        en_francais(self)
        rendus = [R.report(code) for code in R.CODES]
        self.assertEqual(5, len(set(rendus)), rendus)
        for code, rendu in zip(R.CODES, rendus):
            self.assertTrue(rendu.startswith(R.MARKS[code] + " "), rendu)

    def test_an_unknown_code_is_named_not_hidden(self):
        en_francais(self)
        self.assertIn("7", R.report(7))
        self.assertEqual("unexpected", R.code_token(7))


class TestLePireGagne(unittest.TestCase):
    """Réduire plusieurs verdicts à un seul code ne doit rien absoudre."""

    def test_an_empty_run_is_a_skip_and_never_a_success(self):
        self.assertEqual(R.DS_SKIP, R.worst_code([]))
        self.assertEqual(R.DS_SKIP, R.aggregate_layers([]))
        self.assertNotEqual(R.DS_OK, R.worst_code([]))

    def test_all_ok_stays_ok(self):
        self.assertEqual(R.DS_OK, R.worst_code([R.DS_OK, R.DS_OK]))

    def test_the_severity_chain_is_total(self):
        self.assertEqual(R.DS_SKIP, R.worst_code([R.DS_OK, R.DS_SKIP]))
        self.assertEqual(
            R.DS_UNIMPLEMENTED,
            R.worst_code([R.DS_SKIP, R.DS_UNIMPLEMENTED]),
        )
        self.assertEqual(
            R.DS_REFUSED, R.worst_code([R.DS_UNIMPLEMENTED, R.DS_REFUSED])
        )
        self.assertEqual(R.DS_ERR, R.worst_code([R.DS_REFUSED, R.DS_ERR]))

    def test_an_error_wins_whatever_the_order(self):
        self.assertEqual(
            5, len(R.CODES), "vocabulaire vidé : rien n'est prouvé"
        )
        for code in R.CODES:
            with self.subTest(code=code):
                self.assertEqual(R.DS_ERR, R.worst_code([code, R.DS_ERR]))
                self.assertEqual(R.DS_ERR, R.worst_code([R.DS_ERR, code]))

    def test_a_code_outside_the_vocabulary_counts_as_a_failure(self):
        """Le rendre tel quel ferait entrer un sixième code par la bande."""
        self.assertEqual(R.DS_ERR, R.worst_code([R.DS_OK, 7]))


class TestLesCouches(unittest.TestCase):
    """Une couche nomme un ENDROIT ; le vocabulaire en est clos."""

    def test_the_layers_are_exactly_the_nine_declared(self):
        self.assertEqual(
            (
                "host",
                "network",
                "dns",
                "transport",
                "firewall",
                "guest",
                "tls",
                "service",
                "data",
            ),
            R.LAYERS,
        )

    def test_an_unknown_layer_is_refused_at_the_point_of_writing(self):
        with self.assertRaises(ValueError) as leve:
            R.layer_verdict("vm", R.DS_OK)
        self.assertIn("vm", str(leve.exception))
        self.assertIn("firewall", str(leve.exception))

    def test_a_code_outside_the_vocabulary_is_refused_too(self):
        with self.assertRaises(ValueError):
            R.layer_verdict("host", 7)

    def test_every_declared_layer_is_accepted(self):
        """Contrôle positif : sans lui, une implémentation qui refuse TOUT
        passerait les deux épreuves ci-dessus."""
        self.assertEqual(
            9, len(R.LAYERS), "vocabulaire vidé : rien n'est prouvé"
        )
        for couche in R.LAYERS:
            with self.subTest(couche=couche):
                verdict = R.layer_verdict(couche, R.DS_OK)
                self.assertEqual(couche, verdict.layer)

    def test_a_layer_token_fits_the_column(self):
        for couche in R.LAYERS:
            self.assertLessEqual(len(couche), R.LABEL_WIDTH)


class TestLesMarquesRestentEtroites(unittest.TestCase):
    """Un glyphe émoji occupe DEUX cellules et décale toute la colonne."""

    def test_every_mark_is_a_single_narrow_glyph(self):
        self.assertEqual(5, len(R.MARKS), "table vidée : rien n'est prouvé")
        for code, marque in R.MARKS.items():
            with self.subTest(code=code):
                self.assertEqual(1, len(marque))
                self.assertNotIn(
                    unicodedata.east_asian_width(marque), ("W", "F")
                )

    def test_the_width_test_would_reject_an_emoji(self):
        """Contrôle positif du prédicat lui-même."""
        self.assertEqual("W", unicodedata.east_asian_width("✅"))


class TestLesRendeursRendent(unittest.TestCase):
    """Un bloc rendu se compose ; un bloc imprimé ne se compose pas."""

    def _sans_flux(self, appel):
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(
            erreur
        ):
            rendu = appel()
        return rendu, sortie.getvalue(), erreur.getvalue()

    def test_no_renderer_touches_a_stream(self):
        en_francais(self)
        caps = [R.Capability("git", True), R.Capability("limactl", False)]
        for appel in (
            lambda: R.report(R.DS_OK),
            lambda: R.render_capabilities(caps),
            lambda: R.render_capabilities([]),
        ):
            rendu, sortie, erreur = self._sans_flux(appel)
            self.assertTrue(rendu, "rendu vide : l'épreuve ne prouve rien")
            self.assertEqual("", sortie)
            self.assertEqual("", erreur)

    def test_a_capability_block_names_state_why_and_remedy(self):
        en_francais(self)
        bloc = R.render_capabilities(
            [
                R.Capability("git", True),
                R.Capability(
                    "limactl",
                    False,
                    "aucun binaire dans le PATH",
                    "voir Devstack",
                ),
            ]
        )
        self.assertIn("git", bloc)
        self.assertIn("présent", bloc)
        self.assertIn("absent", bloc)
        self.assertIn("aucun binaire dans le PATH", bloc)
        self.assertIn("voir Devstack", bloc)

    def test_an_empty_block_says_nothing_was_probed(self):
        en_francais(self)
        bloc = R.render_capabilities([])
        self.assertIn("sondé", bloc)
        self.assertNotIn("présent", bloc)

    def test_a_block_carries_no_newline_at_its_edges(self):
        bloc = R.render_capabilities([R.Capability("git", True)])
        self.assertFalse(bloc.startswith("\n"))
        self.assertFalse(bloc.endswith("\n"))

    def test_the_detail_column_starts_where_the_vpn_line_starts(self):
        """Deux indentations, la marque, une espace, la colonne, une espace."""
        self.assertEqual(34, R.LABEL_WIDTH)
        self.assertEqual(39, R._line("✓", "git", "présent").index("présent"))

    def test_a_why_already_translated_is_not_looked_up_again(self):
        """Le motif arrive traduit ; le retraduire le dénaturerait.

        Le motif choisi est lui-même une CLÉ connue de la table. Une chaîne
        quelconque ne prouverait rien : `t` rend une clé inconnue telle
        quelle, donc la retraduction y serait invisible.
        """
        en_francais(self)
        self.assertEqual(
            "présent", todo_i18n.t("present"), "la clé témoin a changé"
        )
        bloc = R.render_capabilities([R.Capability("kvm", False, "present")])
        self.assertIn("present", bloc.replace("présent", ""))


class TestLeDiagnosticVaSurStderr(unittest.TestCase):
    """C'est ce qui laisse tuber et asserter la sortie utile."""

    def test_diag_writes_on_stderr_and_leaves_stdout_empty(self):
        sortie, erreur = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(
            erreur
        ):
            R.diag("une dépendance manque")
        self.assertEqual("", sortie.getvalue())
        self.assertIn("une dépendance manque", erreur.getvalue())

    def test_it_resolves_its_stream_at_call_time(self):
        """Résolu à l'import, une redirection posée par un test ne serait
        jamais vue, et le contrat de flux deviendrait invérifiable."""
        erreur = io.StringIO()
        with contextlib.redirect_stderr(erreur):
            R.diag("x")
        self.assertIn("x", erreur.getvalue())


class TestLeModuleResteUneBibliotheque(unittest.TestCase):
    """Un module pur d'une autre famille doit pouvoir le consommer."""

    def _arbre(self):
        with io.open(SOURCE, encoding="utf-8") as handle:
            return ast.parse(handle.read())

    def _appels_print(self, arbre):
        return [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "print"
        ]

    def test_only_diag_prints(self):
        arbre = self._arbre()
        fonctions = {
            noeud.name: noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
        }
        self.assertIn("diag", fonctions, "module vidé : rien n'est prouvé")
        imprimeurs = sorted(
            nom
            for nom, noeud in fonctions.items()
            if self._appels_print(noeud)
        )
        self.assertEqual(["diag"], imprimeurs)

    def test_the_scan_would_notice_another_print(self):
        """Contrôle positif : sans lui, un scanner cassé rend zéro partout."""
        faux = ast.parse('def f():\n    print("x")\n')
        self.assertEqual(1, len(self._appels_print(faux)))

    def test_it_imports_only_the_standard_library_and_the_translations(self):
        racines = set()
        for noeud in ast.walk(self._arbre()):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        self.assertEqual({"script"}, racines - set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
