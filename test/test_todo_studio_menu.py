#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO › Exécution › Test › ERPLibre studio : les scénarios du générateur
de code, lancés par script/test/run_odoo_scenarios.sh.

Rien n'est lancé pour vrai : le lancement au terminal est remplacé, et le
test regarde la commande que chaque entrée construit.
"""

import ast
import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import (
    studio_menu,  # noqa: E402
    todo_i18n,  # noqa: E402
)
from script.todo.todo import TODO  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Fini:
    def __init__(self, returncode):
        self.returncode = returncode


class StudioTest(unittest.TestCase):
    def setUp(self):
        ancien = os.getcwd()
        os.chdir(RACINE)
        self.addCleanup(os.chdir, ancien)
        self.todo = TODO.__new__(TODO)
        lancer = mock.patch.object(
            studio_menu.todo_journal,
            "lancer_au_terminal",
            return_value=_Fini(0),
        )
        self.lancer = lancer.start()
        self.addCleanup(lancer.stop)

    def menu(self, *reponses, saisies=()):
        """Parcourt le menu studio avec ces réponses, puis 0 ; rend la
        sortie affichée."""
        sortie = io.StringIO()
        with (
            mock.patch.object(
                studio_menu.click, "prompt", side_effect=[*reponses, "0"]
            ),
            mock.patch("builtins.input", side_effect=list(saisies)),
            contextlib.redirect_stdout(sortie),
        ):
            self.assertFalse(self.todo.prompt_execute_studio())
        return sortie.getvalue()

    def commandes(self):
        return [c.args[0] for c in self.lancer.call_args_list]


class LeMenuTest(StudioTest):
    def test_the_test_menu_offers_it_as_entry_5(self):
        with (
            mock.patch("click.prompt", side_effect=["5", "0"]),
            mock.patch.object(
                TODO, "prompt_execute_studio", return_value=False
            ) as studio,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.todo.prompt_execute_test()
        studio.assert_called_once_with()

    def test_all_scenarios_run_with_the_table(self):
        self.menu("1")
        self.assertEqual(
            self.commandes(), [[studio_menu.STUDIO_LANCEUR, "--tui"]]
        )
        # Jusqu'au bout : un Ctrl+C laisse le lanceur supprimer ses bases.
        self.assertTrue(self.lancer.call_args.kwargs["jusqu_au_bout"])

    def test_failed_reruns_only_the_failures(self):
        self.menu("3")
        self.assertEqual(
            self.commandes(),
            [[studio_menu.STUDIO_LANCEUR, "--tui", "--failed"]],
        )

    def test_coverage_names_how_to_open_the_report(self):
        sortie = self.menu("4")
        self.assertEqual(
            self.commandes(),
            [[studio_menu.STUDIO_LANCEUR, "--tui", "--coverage"]],
        )
        self.assertIn("make open_test_coverage JEU=odoo", sortie)

    def test_the_coverage_menu_runs_the_same_command(self):
        """Développement › Couverture › [3] et Test › ERPLibre studio › [4]
        : une seule suite, donc une seule commande, tableau compris."""
        self.menu("4")
        with (
            mock.patch("click.prompt", side_effect=["3", "0"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.todo.prompt_execute_coverage()
        studio, couverture = self.commandes()
        self.assertEqual(studio, couverture)

    def test_purge_runs_without_the_table(self):
        """La purge demande avant de supprimer, au terminal : le tableau
        recouvrirait sa question."""
        self.menu("5")
        self.assertEqual(
            self.commandes(), [[studio_menu.STUDIO_LANCEUR, "--purge"]]
        )

    def test_a_missing_launcher_runs_nothing(self):
        vide = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, vide)
        os.chdir(vide)
        self.assertIsNone(self.todo._studio_run("--failed"))
        self.lancer.assert_not_called()


@unittest.skipUnless(
    os.path.exists(os.path.join(RACINE, ".odoo-version")),
    "pas de .odoo-version : aucune version Odoo active",
)
class UnScenarioTest(StudioTest):
    def noms(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.todo._studio_scenarios()

    def test_the_scenarios_are_those_of_the_active_version(self):
        noms = self.noms()
        self.assertTrue(noms)
        self.assertEqual(len(noms), len(set(noms)))

    def test_a_number_runs_that_scenario(self):
        premier = self.noms()[0]
        self.menu("2", saisies=["1"])
        self.assertEqual(
            self.commandes(),
            [
                [
                    studio_menu.STUDIO_LANCEUR,
                    "--tui",
                    f"--scenario={premier}",
                ]
            ],
        )

    def test_empty_or_out_of_range_runs_nothing(self):
        hors = str(len(self.noms()) + 1)
        for saisie in ("", hors, "abc", "0"):
            with self.subTest(saisie=saisie):
                self.menu("2", saisies=[saisie])
        self.lancer.assert_not_called()


class TraductionsTest(unittest.TestCase):
    def test_every_label_is_translated_in_both_languages(self):
        with open(studio_menu.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        cles = {
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        }
        self.assertGreater(len(cles), 10)
        for cle in sorted(cles):
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS.get(cle)
                self.assertIsNotNone(entree)
                self.assertTrue(entree.get("fr") and entree.get("en"))

    def test_the_test_menu_label_names_studio(self):
        libelle = todo_i18n.TRANSLATIONS["ERPLibre studio - code generator"]
        for langue in ("fr", "en"):
            self.assertTrue(
                re.search(r"ERPLibre studio", libelle[langue]), langue
            )


if __name__ == "__main__":
    unittest.main()
