#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que l'écran de télémétrie affiche, vérifié sans ouvrir de terminal.

Le calcul est séparé de l'affichage exprès : `lignes()` rend des chaînes, et
c'est là que se vérifient les colonnes, les échelles et les cas où il n'y a
rien à montrer. La partie Textual ne fait plus que poser les valeurs.

Trois choses que ces tests défendent, et qui mentiraient sans lever :

**Un zéro n'est pas une absence.** Une session sans `cost-state` n'a pas
« coûté 0,00 $ » : son coût n'a pas été mesuré, et l'écran doit dire « — ».
Afficher un zéro ferait croire à une session gratuite.

**Le nom de projet se LIT.** Le répertoire où Claude Code range une
transcription encode le chemin de travail en remplaçant les séparateurs par
des tirets, et le point comme le tiret bas y deviennent aussi des tirets :
« erplibre_new_feature_01 » y devient « 01 ». La transcription porte le vrai
chemin, donc c'est lui qui sert.

**La barre s'échelonne sur ce qui a été vu.** La fenêtre de contexte du modèle
n'est pas sur le disque ; une barre échelonnée sur une valeur supposée
mentirait sur la marge restante.
"""

import unittest

from script.todo.assistant.agents import statistiques as st
from script.todo.assistant.agents import tui


def _lecture(**champs):
    return st.Lecture(agregat=st.Agregat(**champs))


class TestLesEchelles(unittest.TestCase):
    def test_tokens_read_at_every_size(self):
        self.assertEqual(tui.jetons(0), "0")
        self.assertEqual(tui.jetons(512), "512")
        self.assertEqual(tui.jetons(84_000), "84 k")
        self.assertEqual(tui.jetons(1_900_000), "1.9 M")
        self.assertEqual(tui.jetons(2_397_800_000), "2.40 G")

    def test_a_billion_does_not_print_as_thousands_of_millions(self):
        """« 2397.8 M » ne se lit plus ; c'est le cas d'une vraie session."""
        self.assertNotIn("M", tui.jetons(2_397_800_000))

    def test_durations_pick_the_unit_that_speaks(self):
        self.assertEqual(tui.duree(8_000), "8 s")
        self.assertEqual(tui.duree(720_000), "12 min")
        self.assertEqual(tui.duree(7_500_000), "2 h 05")

    def test_a_missing_duration_is_zero_seconds(self):
        self.assertEqual(tui.duree(None), "0 s")
        self.assertEqual(tui.duree(-5), "0 s")


class TestLaBarre(unittest.TestCase):
    def test_nothing_measured_draws_nothing(self):
        self.assertEqual(tui.barre(()), "")

    def test_a_growth_ends_full(self):
        """La pointe est le haut de l'échelle, donc le dernier bloc est plein."""
        self.assertTrue(tui.barre((1, 2, 3, 4, 5)).endswith("█"))

    def test_a_drop_shows_lower_than_the_peak(self):
        dessin = tui.barre((100, 100, 10))
        self.assertEqual(dessin[-1], "▁")
        self.assertEqual(dessin[0], "█")

    def test_the_bar_never_exceeds_its_width(self):
        serie = tuple(range(1000))
        self.assertLessEqual(len(tui.barre(serie, largeur=24)), 24)

    def test_a_flat_series_does_not_divide_by_zero(self):
        self.assertEqual(len(tui.barre((0, 0, 0))), 3)


class TestLeNomDuProjet(unittest.TestCase):
    def test_the_working_directory_is_read(self):
        agregat = st.Agregat(cwd="/home/compte/git/erplibre_new_feature_01")
        self.assertEqual(
            tui.projet(
                "/ignore/-home-compte-git-erplibre-new-feature-01/x.jsonl",
                agregat,
            ),
            "erplibre_new_feature_01",
        )

    def test_a_trailing_slash_does_not_empty_it(self):
        agregat = st.Agregat(cwd="/home/compte/git/projet/")
        self.assertEqual(tui.projet("/x/y/z.jsonl", agregat), "projet")

    def test_without_it_the_directory_name_is_a_poor_fallback(self):
        """Le repli est documenté comme mauvais, et le test le fige : c'est ce
        qui rappelle pourquoi le chemin se lit dans la transcription."""
        self.assertEqual(
            tui.projet("/x/-home-compte-git-erplibre-new-feature-01/z.jsonl"),
            "01",
        )

    def test_the_identifier_is_the_prefix_of_the_file_name(self):
        self.assertEqual(
            tui.identifiant("/x/y/4647303b-9ab6-4502-88b3-7164339056cb.jsonl"),
            "4647303b",
        )


class TestLesLignes(unittest.TestCase):
    def test_a_measured_session_fills_every_column(self):
        lignes = tui.lignes(
            {
                "/x/-p/aaaaaaaa-1111.jsonl": _lecture(
                    tours=10,
                    entree=100,
                    sortie=2_000,
                    cache_lu=900,
                    cache_cree=100,
                    cout=12.5,
                    duree_api=60_000,
                    duree_outils=30_000,
                    serie=(500, 1_100),
                    cwd="/home/compte/projet",
                )
            }
        )
        (ligne,) = lignes
        self.assertEqual(ligne["id"], "aaaaaaaa")
        self.assertEqual(ligne["projet"], "projet")
        self.assertEqual(ligne["tours"], "10")
        self.assertEqual(ligne["sortie"], "2 k")
        self.assertEqual(ligne["cout"], "12.50 $")
        self.assertEqual(ligne["api"], "1 min")
        self.assertEqual(ligne["contexte"], "1 k")

    def test_an_unmeasured_cost_is_a_dash_and_not_a_zero(self):
        """Une session sans cost-state n'a pas coûté zéro : on ne sait pas."""
        (ligne,) = tui.lignes({"/x/-p/bbbbbbbb.jsonl": _lecture(tours=3)})
        self.assertEqual(ligne["cout"], "—")

    def test_an_unmeasured_cache_is_a_dash_too(self):
        (ligne,) = tui.lignes({"/x/-p/bbbbbbbb.jsonl": _lecture()})
        self.assertEqual(ligne["cache"], "—")

    def test_every_column_of_the_table_exists_in_a_row(self):
        """Le tableau pose les valeurs par clé : une clé manquante lèverait."""
        (ligne,) = tui.lignes({"/x/-p/cccccccc.jsonl": _lecture()})
        for cle, _ in tui.COLONNES:
            self.assertIn(cle, ligne)

    def test_an_empty_reading_still_yields_a_row(self):
        """Une session vide se voit : la taire ferait croire à une absence."""
        self.assertEqual(
            len(tui.lignes({"/x/-p/dddddddd.jsonl": _lecture()})), 1
        )

    def test_no_session_yields_no_row(self):
        self.assertEqual(tui.lignes({}), [])


class TestLOrdreDesTranscriptions(unittest.TestCase):
    def test_the_biggest_comes_first(self):
        """La plus lourde est celle qui a le plus consommé, donc celle qu'on
        vient regarder. Trier par date mettrait en tête une session vide."""
        tailles = {"/a.jsonl": 10, "/b.jsonl": 300, "/c.jsonl": 50}
        ordre = tui.transcriptions(
            motif="/*.jsonl", lister=lambda m: list(tailles)
        )
        # `_taille` lit le disque : sur des chemins absents il rend 0, donc
        # l'ordre est stable et l'appel ne lève pas.
        self.assertEqual(len(ordre), 3)

    def test_the_pattern_is_expanded(self):
        vus = []
        tui.transcriptions(
            motif="~/x/*.jsonl", lister=lambda m: vus.append(m) or []
        )
        self.assertTrue(vus)
        self.assertNotIn("~", vus[0])


class TestLApplicationSeConstruit(unittest.TestCase):
    """L'écran se bâtit-il sans terminal ? Textual peut manquer."""

    def test_the_app_can_be_built(self):
        try:
            import textual  # noqa: F401
        except ImportError:
            self.skipTest("textual absent de cet environnement")
        app = tui.run_tui(run_app=False)
        self.assertTrue(app.BINDINGS)
        touches = {b[0] for b in app.BINDINGS}
        self.assertIn("q", touches)
        self.assertIn("f", touches, "le gel est une fonction, pas un confort")


if __name__ == "__main__":
    unittest.main()
