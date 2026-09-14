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

    def test_a_tool_duration_is_not_rounded_to_zero(self):
        """Une édition de quarante millisecondes n'a pas pris « 0 s ».

        C'est le même mensonge qu'un zéro mis à la place d'une absence, et il
        touchait toute la colonne des durées par outil."""
        self.assertEqual(tui.duree(40), "40 ms")
        self.assertEqual(tui.duree(999), "999 ms")
        self.assertEqual(tui.duree(1_000), "1 s")

    def test_a_missing_duration_is_zero_milliseconds(self):
        self.assertEqual(tui.duree(None), "0 ms")
        self.assertEqual(tui.duree(-5), "0 ms")


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
        # L'icône dit de quel harnais vient la ligne : le tableau en réunit
        # deux, et deux identifiants de huit caractères ne se distinguent pas.
        self.assertEqual(ligne["id"], f"{tui.ICONES['claude']} aaaaaaaa")
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


class TestLesDeuxHarnaisDansLeMemeTableau(unittest.TestCase):
    """Deux harnais qui ne mesurent pas les mêmes choses, un seul tableau.

    Ce que l'un porte et l'autre pas doit rendre un TIRET, jamais un zéro :
    une colonne à zéro se lit « mesuré, et nul », ce qui est faux et décourage
    de chercher ailleurs ce que l'autre harnais donne.
    """

    SANS_RESUME = object()

    def _seance(self, resume=None, **champs):
        """Une séance inventée. `resume=SANS_RESUME` rend celle du CLI, qui
        n'en porte pas — le sentinelle distingue « pas de résumé » de « prends
        le résumé par défaut »."""
        from script.todo.assistant.harness import opencode as oc

        defauts = {
            "identifiant": "ses_aaaabbbbccccdddd",
            "repertoire": "/un/depot/projet",
            "modifie": 1_700_000_000_000,
        }
        defauts.update(champs)
        if resume is self.SANS_RESUME:
            resume = None
        elif resume is None:
            resume = oc.Resume(
                entree=1_000, sortie=17, cache_lu=7_000, cout=0.5
            )
        return oc.Seance(resume=resume, **defauts)

    def _ligne_claude(self):
        """Une ligne de l'autre harnais, pour comparer les formes."""
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes({"/x/y/aaaaaaaa.jsonl": st.Lecture()})
        return ligne

    def test_a_session_becomes_a_row_of_the_same_shape(self):
        """Les deux sources nourrissent le MÊME tableau : une clé de plus ou
        de moins d'un côté lève au moment de peindre, pas avant."""
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_opencode([self._seance()])
        self.assertEqual(set(ligne), set(self._ligne_claude()))
        self.assertEqual(ligne["projet"], "projet")
        self.assertEqual(ligne["sortie"], "17")
        self.assertEqual(ligne["cout"], "0.50 $")

    def test_the_icon_tells_the_two_harnesses_apart(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_opencode([self._seance()])
        self.assertTrue(ligne["id"].startswith(t_ui.ICONES["opencode"]))
        self.assertIn("aaaabbbb", ligne["id"])
        self.assertNotIn("ses_", ligne["id"])

    def test_what_open_code_does_not_measure_is_a_dash(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_opencode([self._seance()])
        for absent in ("tours", "contexte", "api", "outils", "horloge"):
            self.assertEqual(ligne[absent], "—", absent)

    def test_an_unreadable_base_adds_no_row(self):
        """None veut dire « la base n'a pas répondu », pas « zéro séance »."""
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.lignes_opencode(None), [])

    def test_a_session_without_a_summary_is_skipped(self):
        """Le CLI rend des séances sans résumé : une ligne toute vide dans le
        tableau se lirait comme une session sans coût."""
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(
            t_ui.lignes_opencode([self._seance(resume=self.SANS_RESUME)]), []
        )

    def test_every_column_of_the_table_is_filled(self):
        """Une clé manquante lève au moment de peindre, pas avant."""
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_opencode([self._seance()])
        for cle, _ in t_ui.COLONNES:
            self.assertIn(cle, ligne, cle)

    def test_the_summary_keeps_the_two_harnesses_apart(self):
        """Un total fondu mêlerait un coût lu dans un `cost-state`, qu'une
        compaction remet à zéro, et un champ de base stable."""
        from script.todo.assistant.agents import tui as t_ui

        segment = t_ui.resume_opencode([self._seance(), self._seance()])
        self.assertIn(t_ui.ICONES["opencode"], segment)
        self.assertIn("2", segment)
        self.assertIn("1.00 $", segment)

    def test_the_summary_says_nothing_when_there_is_nothing(self):
        """Un segment vide vaut mieux qu'un « 0 · 0.00 $ » sur une machine
        qui n'a pas Open Code : zéro se lit « mesuré, et nul »."""
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.resume_opencode(None), "")
        self.assertEqual(t_ui.resume_opencode([]), "")
        self.assertEqual(
            t_ui.resume_opencode([self._seance(resume=self.SANS_RESUME)]), ""
        )


class TestLeTempsDAttention(unittest.TestCase):
    """La colonne qui sépare le temps passé du temps écoulé.

    L'horloge d'une session compte aussi les heures où personne ne regardait.
    Le temps d'attention vient du journal des hooks, qui porte l'instant de
    chaque événement : rien n'est à collecter, seulement à rapprocher.
    """

    CHEMIN = "/x/y/aaaaaaaa-1111-4111-8111-111111111111.jsonl"

    def _ligne(self, temps=None):
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes({self.CHEMIN: st.Lecture()}, temps)
        return ligne

    def test_the_measured_time_shows(self):
        from script.todo.assistant.agents import tui as t_ui

        session = t_ui.session_de(self.CHEMIN)
        self.assertEqual(self._ligne({session: 125_000})["attention"], "2 min")

    def test_without_hooks_it_is_a_dash_and_never_a_zero(self):
        """Zéro dirait « cette session n'a pas travaillé », ce qui est le
        contraire de « on ne mesure pas »."""
        self.assertEqual(self._ligne()["attention"], "—")
        self.assertEqual(self._ligne({})["attention"], "—")

    def test_a_session_absent_from_the_log_is_a_dash(self):
        """Des hooks posés après coup ne savent rien des sessions qui les
        précèdent."""
        self.assertEqual(self._ligne({"une-autre": 9_000})["attention"], "—")

    def test_the_full_identifier_is_what_joins_the_two_sources(self):
        """Le journal nomme les sessions en entier ; rapprocher sur huit
        caractères marierait un jour deux sessions sans rapport."""
        from script.todo.assistant.agents import tui as t_ui

        entier = t_ui.session_de(self.CHEMIN)
        self.assertEqual(entier, "aaaaaaaa-1111-4111-8111-111111111111")
        self.assertNotEqual(entier, t_ui.identifiant(self.CHEMIN))
        self.assertEqual(self._ligne({entier[:8]: 9_000})["attention"], "—")

    def test_open_code_has_no_such_measure(self):
        """Ses séances ne passent pas par les hooks de Claude Code."""
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        (ligne,) = t_ui.lignes_opencode(
            [oc.Seance(identifiant="ses_aaaabbbb", resume=oc.Resume())]
        )
        self.assertEqual(ligne["attention"], "—")


class TestLesTroisColonnesDEchec(unittest.TestCase):
    """Trois façons de mal finir, trois colonnes.

    Une colonne reste VIDE plutôt que d'afficher zéro : un tableau semé de
    zéros se lit mal, et ce qui compte ici est qu'une valeur y paraisse.
    """

    def _ligne(self, **comptes):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_outils(
            [jr.ParOutil(outil="Bash", appels=9, **comptes)]
        )
        return ligne

    def test_each_kind_has_its_own_column(self):
        ligne = self._ligne(echoues=2, interrompus=1, inacheves=3)
        self.assertEqual(ligne["echoues"], "2")
        self.assertEqual(ligne["interrompus"], "1")
        self.assertEqual(ligne["inacheves"], "3")

    def test_a_kind_that_never_happened_leaves_its_cell_empty(self):
        """Les TROIS colonnes, chacune vérifiée à zéro : un tableau semé de
        zéros se lit mal, et ce qui compte est qu'une valeur y paraisse."""
        vide = self._ligne()
        for colonne in ("echoues", "interrompus", "inacheves"):
            self.assertEqual(vide[colonne], "", colonne)
        ligne = self._ligne(echoues=2)
        self.assertEqual(ligne["echoues"], "2")
        self.assertEqual(ligne["interrompus"], "")
        self.assertEqual(ligne["inacheves"], "")

    def test_the_table_asks_for_every_key_the_row_gives(self):
        from script.todo.assistant.agents import tui as t_ui

        ligne = self._ligne(echoues=1)
        for cle, _ in t_ui.COLONNES_OUTILS:
            self.assertIn(cle, ligne, cle)

    def test_the_three_columns_are_declared_in_both_languages(self):
        from script.todo.todo_i18n import TRANSLATIONS
        from script.todo.assistant.agents import tui as t_ui

        for cle, libelle in t_ui.COLONNES_OUTILS:
            self.assertIn(libelle, TRANSLATIONS, libelle)
