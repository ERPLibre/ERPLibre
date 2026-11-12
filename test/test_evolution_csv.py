#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le détail par dépôt des statistiques de modules : enregistré par la
passe, exporté en CSV, montré par l'écran (« d ») et l'entrée 6 du menu
Analyse module. Les données sont fabriquées ; aucun dépôt n'est cloné."""

import asyncio
import csv
import datetime
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.statistic import evolution_csv as ec  # noqa: E402
from script.statistic import evolution_tui as ev  # noqa: E402
from script.todo import module_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_evolution_tui import donnees, sem  # noqa: E402

D = datetime.date


def detaillees():
    return sem.donnees_evolution(
        {D(2017, 1, 1): {"10.0": 4}, D(2018, 1, 1): {"10.0": 6, "9.0": 3}},
        {D(2017, 1, 1): {"a"}, D(2018, 1, 1): {"a", "b"}},
        "",
        2,
        "2026-01-01T00:00:00+00:00",
        {
            D(2017, 1, 1): {"OCA_web": {"10.0": 4}},
            D(2018, 1, 1): {
                "OCA_web": {"10.0": 2},
                "OCA_tools": {"9.0": 3, "10.0": 4},
            },
        },
    )


class TestLeDetail(unittest.TestCase):
    def test_the_pass_records_each_repository_sorted(self):
        annees = detaillees()["annees"]
        self.assertEqual(annees[0]["par_depot"], {"OCA_web": {"10.0": 4}})
        self.assertEqual(
            list(annees[1]["par_depot"]), ["OCA_tools", "OCA_web"]
        )
        self.assertEqual(
            list(annees[1]["par_depot"]["OCA_tools"]), ["9.0", "10.0"]
        )
        self.assertNotIn("par_depot", donnees()["annees"][0])

    def test_the_last_year_biggest_repository_first(self):
        date, entetes, rangees = ev.lignes_par_depot(detaillees())
        self.assertEqual(date, "2018-01-01")
        self.assertEqual(entetes[1:3], ["9.0", "10.0"])
        self.assertEqual(
            rangees, [["OCA_tools", "3", "4", "7"], ["OCA_web", "", "2", "2"]]
        )
        self.assertEqual(ev.lignes_par_depot(donnees())[2], [])
        self.assertEqual(ev.lignes_par_depot({}), ("", [], []))


class TestLeCSV(unittest.TestCase):
    def test_long_format_totals_uniques_then_repositories(self):
        rangees = ec.rangees(detaillees())
        self.assertEqual(
            rangees[:3],
            [
                ["2017-01-01", "ALL", "10.0", 4],
                ["2017-01-01", "ALL", "unique", 1],
                ["2017-01-01", "OCA_web", "10.0", 4],
            ],
        )
        self.assertIn(["2018-01-01", "OCA_tools", "9.0", 3], rangees)
        self.assertEqual(len(rangees), 3 + 3 + 3)

    def test_one_csv_beside_each_data_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sem.ecrire_donnees(sem.fichier_donnees("", tmp), detaillees())
            sem.ecrire_donnees(
                sem.fichier_donnees("/OCA/", tmp), donnees("/OCA/")
            )
            chemins = ec.exporter(tmp)
            self.assertEqual(
                [os.path.basename(c) for c in chemins],
                ["evolution_modules.csv", "evolution_modules_OCA.csv"],
            )
            with open(chemins[0], newline="", encoding="utf-8") as fh:
                lu = list(csv.reader(fh))
            self.assertEqual(lu[0], ec.ENTETES)
            self.assertEqual(lu[1], ["2017-01-01", "ALL", "10.0", "4"])
            self.assertEqual(
                sorted(os.listdir(tmp))[0], "evolution_modules.csv"
            )
            self.assertFalse(
                [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ec.exporter(tmp), [])


class TestLEcran(unittest.TestCase):
    def test_d_toggles_the_per_repository_table(self):
        app = ev.build_app(
            [("/a.json", detaillees()), ("/b.json", donnees("/OCA/"))]
        )

        async def scenario():
            async with app.run_test(size=(120, 80)) as pilote:
                await pilote.pause()
                self.assertEqual(len(app.query("DataTable.detail")), 0)
                await pilote.press("d")
                await pilote.pause()
                self.assertEqual(len(app.query("DataTable.detail")), 1)
                await pilote.press("b")
                await pilote.pause()
                self.assertEqual(len(app.query("DataTable.detail")), 1)
                await pilote.press("d")
                await pilote.pause()
                self.assertEqual(len(app.query("DataTable.detail")), 0)

        asyncio.run(scenario())


class TestLEntreeSix(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, dossier):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        with (
            mock.patch.object(module_menu, "STAT_DOSSIER", dossier),
            mock.patch("click.prompt", side_effect=["6", "0"]),
            mock.patch("builtins.print") as sortie,
        ):
            todo.prompt_execute_module_analysis()
        return "\n".join(
            str(c.args[0]) for c in sortie.call_args_list if c.args
        )

    def test_entry_6_exports_or_says_there_is_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("lancez d'abord", self.lancer(tmp).lower())
            sem.ecrire_donnees(sem.fichier_donnees("", tmp), detaillees())
            self.assertIn("evolution_modules.csv", self.lancer(tmp))
            self.assertTrue(
                os.path.isfile(os.path.join(tmp, "evolution_modules.csv"))
            )


if __name__ == "__main__":
    unittest.main()
