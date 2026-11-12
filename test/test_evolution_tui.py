#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'évolution des modules par année : le fichier de données qu'écrit une
passe, le tracé braille, l'écran Textual et l'entrée 5 du menu Analyse
module, qui n'ouvre rien sans données.

Les données sont fabriquées ; aucun dépôt n'est cloné.
"""

import asyncio
import datetime
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, RACINE)
from script.statistic import evolution_tui as ev  # noqa: E402
from script.todo import module_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "show_evolution_module",
    os.path.join(RACINE, "script", "statistic", "show_evolution_module.py"),
)
sem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sem)

D = datetime.date


def donnees(filtre=""):
    return sem.donnees_evolution(
        {
            D(2017, 1, 1): {"10.0": 4},
            D(2016, 1, 1): {"9.0": 2, "10.0": 1},
            D(2018, 1, 1): {"10.0": 6, "11.0": 3},
        },
        {
            D(2016, 1, 1): {"a", "b"},
            D(2017, 1, 1): {"a", "b", "c"},
            D(2018, 1, 1): {"a", "b", "c", "d", "e"},
        },
        filtre,
        3,
        "2026-01-01T00:00:00+00:00",
    )


class TestLeFichierDeDonnees(unittest.TestCase):
    def test_one_file_per_filter(self):
        self.assertEqual(
            os.path.basename(sem.fichier_donnees("", "/x")),
            "evolution_modules.json",
        )
        self.assertEqual(
            os.path.basename(sem.fichier_donnees("/OCA/", "/x")),
            "evolution_modules_OCA.json",
        )

    def test_years_sorted_versions_sorted_and_uniques_counted(self):
        d = donnees("/OCA/")
        self.assertEqual(
            [a["date"] for a in d["annees"]],
            ["2016-01-01", "2017-01-01", "2018-01-01"],
        )
        self.assertEqual(list(d["annees"][0]["par_version"]), ["9.0", "10.0"])
        self.assertEqual([a["uniques"] for a in d["annees"]], [2, 3, 5])
        self.assertEqual((d["filtre"], d["depots"]), ("/OCA/", 3))

    def test_written_atomically_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = sem.fichier_donnees("", tmp)
            sem.ecrire_donnees(chemin, donnees())
            self.assertEqual(os.listdir(tmp), ["evolution_modules.json"])
            with open(
                os.path.join(tmp, "evolution_modules_x.json"), "w"
            ) as fh:
                fh.write("{pas du json")
            jeux = ev.lire_jeux(tmp)
        self.assertEqual(len(jeux), 1)


class TestLesSeries(unittest.TestCase):
    def test_a_version_starts_the_year_it_exists(self):
        etiquettes, courbes = ev.series(donnees())
        self.assertEqual(etiquettes, ["2016", "2017", "2018"])
        self.assertEqual(list(courbes), ["9.0", "10.0", "11.0", ev.UNIQUES])
        self.assertEqual(courbes["11.0"], [None, None, 3])
        self.assertEqual(courbes[ev.UNIQUES], [2, 3, 5])

    def test_uniques_are_drawn_last_with_their_own_style(self):
        styles = ev.couleurs(["9.0", "10.0", ev.UNIQUES])
        self.assertEqual(styles[ev.UNIQUES], ev.COULEUR_UNIQUES)
        self.assertNotEqual(styles["9.0"], styles["10.0"])


class TestLeTrace(unittest.TestCase):
    def test_corners_and_scale(self):
        lignes, ymax = ev.tracer({"a": [0, 10]}, largeur=4, hauteur=2)
        self.assertEqual(ymax, 10)
        self.assertEqual(len(lignes), 2)
        self.assertTrue(all(len(l) == 4 for l in lignes))
        # Le premier point est en bas à gauche, le dernier en haut à droite.
        self.assertTrue(ord(lignes[1][0][0]) & 0x40)
        self.assertTrue(ord(lignes[0][3][0]) & 0x08)
        self.assertEqual(lignes[0][3][1], "a")

    def test_the_last_curve_owns_a_shared_cell(self):
        lignes, _ = ev.tracer(
            {"a": [5, 5], "b": [5, 5]}, largeur=3, hauteur=2, ymax=10
        )
        proprietaires = {c[1] for l in lignes for c in l if c[1]}
        self.assertEqual(proprietaires, {"b"})

    def test_a_gap_is_not_bridged(self):
        lignes, _ = ev.tracer({"a": [None, 1]}, largeur=4, hauteur=2, ymax=1)
        dessines = [c for l in lignes for c in l if c[1]]
        self.assertEqual(len(dessines), 1)

    def test_the_chart_has_axis_and_years(self):
        texte = ev.graphique(donnees(), 60, 12).plain
        self.assertIn("2016", texte)
        self.assertIn("2018", texte)
        self.assertIn("└", texte)
        self.assertIn("     6 ", texte)


class TestCacherDesVersions(unittest.TestCase):
    def test_the_list_holds_every_version_then_the_uniques(self):
        jeux = [("/a", donnees()), ("/b", donnees())]
        self.assertEqual(
            ev.noms_des_courbes(jeux), ["9.0", "10.0", "11.0", ev.UNIQUES]
        )

    def test_a_hidden_curve_is_not_drawn_and_the_scale_follows(self):
        etiquettes, courbes = ev.series(donnees())
        tout = ev.graphique(donnees(), 60, 12).plain
        self.assertIn("     6 ", tout)
        # Sans les uniques (6 au plus), la plus haute courbe vaut 6 aussi :
        # on cache aussi 10.0 pour voir l'axe suivre la plus haute restante.
        sans = ev.graphique(
            donnees(), 60, 12, frozenset({ev.UNIQUES, "10.0"})
        ).plain
        self.assertIn("     3 ", sans)

    def test_colours_do_not_move_when_a_curve_is_hidden(self):
        texte = ev.graphique(donnees(), 60, 12, frozenset({"9.0"}))
        styles = {str(span.style) for span in texte.spans}
        self.assertNotIn(
            ev.couleurs(["9.0", "10.0", "11.0", ev.UNIQUES])["9.0"], styles
        )
        self.assertIn(
            ev.couleurs(["9.0", "10.0", "11.0", ev.UNIQUES])["10.0"], styles
        )

    def test_the_legend_keeps_a_hidden_curve_struck(self):
        texte = ev.legende(donnees(), frozenset({"9.0"}))
        barres = [
            texte.plain[span.start : span.end]
            for span in texte.spans
            if "strike" in str(span.style)
        ]
        self.assertEqual(barres, ["── 9.0   "])

    def test_unticking_hides_and_a_shows_all_again(self):
        app = ev.build_app([("/a", donnees())])

        async def scenario():
            async with app.run_test(size=(120, 60)) as pilote:
                await pilote.pause()
                liste = app.query_one("#courbes")
                liste.deselect("10.0")
                await pilote.pause()
                self.assertEqual(app.cachees, {"10.0"})
                await pilote.press("a")
                await pilote.pause()
                self.assertEqual(app.cachees, set())

        asyncio.run(scenario())


class TestLEcran(unittest.TestCase):
    def test_one_set_then_both(self):
        jeux = [("/a.json", donnees()), ("/b.json", donnees("/OCA/"))]
        app = ev.build_app(jeux)

        async def scenario():
            async with app.run_test(size=(100, 60)) as pilote:
                await pilote.pause()
                titres = [w for w in app.query(".titre")]
                self.assertEqual(len(titres), 1)
                await pilote.press("b")
                await pilote.pause()
                self.assertEqual(len(app.query(".titre")), 2)
                await pilote.press("2")
                await pilote.pause()
                self.assertEqual(len(app.query(".titre")), 1)
                self.assertIn("OCA", str(app.query(".titre").first().render()))

        asyncio.run(scenario())

    def test_no_data_opens_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ev.run(tmp), 0)


class TestLEntreeCinq(unittest.TestCase):
    def setUp(self):
        ancienne = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)

    def lancer(self, dossier):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = []
        with (
            mock.patch.object(module_menu, "STAT_DOSSIER", dossier),
            mock.patch.object(ev, "run", return_value=1) as run,
            mock.patch("script.todo.textual_setup.ensure", return_value=True),
            mock.patch("click.prompt", side_effect=["5", "0"]),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: vus.append(" ".join(map(str, a))),
            ),
        ):
            todo.prompt_execute_module_analysis()
        return run, "\n".join(vus)

    def test_without_data_it_says_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, vu = self.lancer(tmp)
        run.assert_not_called()
        self.assertIn("Aucune statistique de modules", vu)

    def test_with_data_it_opens_the_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            sem.ecrire_donnees(sem.fichier_donnees("", tmp), donnees())
            run, _ = self.lancer(tmp)
            run.assert_called_once_with(tmp)

    def test_the_more_year_window_reaches_next_january(self):
        self.assertEqual(module_menu.stat_annees(D(2026, 5, 1)), "11")


if __name__ == "__main__":
    unittest.main()
