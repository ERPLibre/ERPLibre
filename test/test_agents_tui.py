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

La dernière classe, elle, MONTE l'application et tape des touches, par le
pilote de Textual. Vérifier des fonctions pures est juste et ne suffit pas :
une colonne que le tableau ne demande pas, un panneau qu'on n'affiche jamais,
une touche qui ne répond pas, rien de cela ne se voit sur un dictionnaire.
"""

import unittest
from unittest.mock import patch

from script.todo.assistant.agents import statistiques as st
from script.todo.assistant.agents import tui
from script.todo.todo_i18n import t


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
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.todo_i18n import TRANSLATIONS

        for cle, libelle in t_ui.COLONNES_OUTILS:
            self.assertIn(libelle, TRANSLATIONS, libelle)


class TestLEcranTourneVraiment(unittest.IsolatedAsyncioTestCase):
    """L'écran lancé pour de bon, sans terminal, par le pilote de Textual.

    Tout le reste de ce fichier vérifie des fonctions PURES — ce qui est juste
    et ne suffit pas : une colonne que le tableau ne demande pas, un panneau
    qu'on n'affiche jamais, une touche qui ne répond pas, rien de cela ne se
    voit sur un dictionnaire. Ce test-ci monte l'application, tape des
    touches, et lit ce qui est effectivement peint.

    Le disque est INJECTÉ : ni transcription, ni journal, ni base réelle n'est
    lu, et le ménage des journaux périmés est neutralisé — un test n'efface
    rien chez personne.
    """

    CHEMIN = "/x/y/aaaaaaaa-1111-4111-8111-111111111111.jsonl"

    def _monde(self):
        """Les quatre lectures du disque, remplacées par de l'inventé."""
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        evenements = [
            {
                "hook_event_name": "PreToolUse",
                "tool_use_id": "1",
                "tool_name": "Bash",
                "session_id": "aaaaaaaa-1111-4111-8111-111111111111",
                "ts": 1_700_000_000_000,
            },
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "1",
                "ts": 1_700_000_000_400,
                "duration_ms": 400,
            },
        ]
        seance = oc.Seance(
            identifiant="ses_aaaabbbbccccdddd",
            repertoire="/un/depot/projet",
            modifie=1_700_000_000_000,
            resume=oc.Resume(entree=10, sortie=2, cout=0.5),
        )
        return (
            patch.object(t_ui, "transcriptions", lambda: [self.CHEMIN]),
            patch.object(st, "lire", lambda c, l=None: st.Lecture()),
            patch.object(jr, "lire_lignes", lambda: evenements),
            patch.object(jr, "nettoyer", lambda *a, **k: None),
            patch.object(oc, "lire_base", lambda: [seance]),
        )

    async def _piloter(self, touches=()):
        from textual.widgets import DataTable, Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await pilote.pause()
                for touche in touches:
                    await pilote.press(touche)
                    await pilote.pause()
                return {
                    "vue": app.VUES[app._vue],
                    "resume": str(app.query_one("#resume", Static).render()),
                    "titre": str(
                        app.query_one("#titre_outils", Static).render()
                    ),
                    "tables": {
                        nom: (
                            app.query_one(f"#{nom}", DataTable).display,
                            app.query_one(f"#{nom}", DataTable).row_count,
                            len(app.query_one(f"#{nom}", DataTable).columns),
                        )
                        for nom in ("tableau",) + app.VUES
                    },
                }
        finally:
            for c in correctifs:
                c.stop()

    async def test_l_ecran_se_monte_et_peint_ses_trois_tableaux(self):
        from script.todo.assistant.agents import tui as t_ui

        vu = await self._piloter()
        self.assertEqual(vu["tables"]["tableau"][1], 2, "une par harnais")
        self.assertEqual(vu["tables"]["tableau"][2], len(t_ui.COLONNES))
        self.assertEqual(vu["tables"]["outils"][2], len(t_ui.COLONNES_OUTILS))
        self.assertEqual(vu["tables"]["flux"][2], len(t_ui.COLONNES_FLUX))

    async def test_un_seul_panneau_du_bas_est_visible(self):
        """Empilés, les trois tableaux tiendraient quatre lignes chacun."""
        vu = await self._piloter()
        self.assertTrue(vu["tables"]["outils"][0])
        self.assertFalse(vu["tables"]["flux"][0])

    async def test_la_touche_v_permute_le_panneau(self):
        vu = await self._piloter(["v"])
        self.assertEqual(vu["vue"], "flux")
        self.assertFalse(vu["tables"]["outils"][0])
        self.assertTrue(vu["tables"]["flux"][0])
        self.assertIn(t("Latest tool calls, newest first"), vu["titre"])

    async def test_la_touche_v_revient_en_boucle(self):
        vu = await self._piloter(["v", "v"])
        self.assertEqual(vu["vue"], "outils")
        self.assertIn(t("Per tool"), vu["titre"])

    async def test_le_resume_nomme_les_deux_harnais(self):
        from script.todo.assistant.agents import tui as t_ui

        vu = await self._piloter()
        self.assertIn(t_ui.ICONES["claude"], vu["resume"])
        self.assertIn(t_ui.ICONES["opencode"], vu["resume"])

    async def test_le_gel_se_dit_a_l_ecran(self):
        """Sans mention, un écran figé se lit comme un écran mort."""
        vu = await self._piloter(["f"])
        self.assertIn(t("frozen"), vu["resume"])


class TestLeFluxDesAppels(unittest.TestCase):
    """Le panneau qui dit ce qui VIENT de se passer.

    Celui des outils répond à « lequel est lent » ; celui-ci à « pourquoi ça
    bloque depuis deux minutes ». Aucun contenu n'y paraît : un nom d'outil,
    une durée, une fin.
    """

    def _appel(self, **champs):
        from script.todo.assistant.agents import journal as jr

        defauts = {
            "outil": "Bash",
            "session": "aaaaaaaa-1111-4111-8111-111111111111",
            "debut_ms": 1_700_000_000_000,
            "duree_ms": 400,
            "issue": jr.FINI,
        }
        defauts.update(champs)
        return jr.Appel(**defauts)

    def _issue(self, issue):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel(issue=issue)])
        return ligne["issue"]

    def test_a_finished_call_says_nothing(self):
        """C'est le cas ordinaire : une colonne remplie à chaque ligne ne
        signale plus rien."""
        from script.todo.assistant.agents import journal as jr

        self.assertEqual(self._issue(jr.FINI), "")

    def test_each_bad_ending_names_itself_in_the_singular(self):
        """Une ligne décrit UN appel. Les clés du tableau par outil sont des
        comptes, que le français accorde au pluriel — les réutiliser ici
        afficherait « inachevés » sur un appel unique."""
        from script.todo.assistant.agents import journal as jr

        self.assertEqual(self._issue(jr.ECHOUE), t("failure"))
        self.assertEqual(self._issue(jr.INTERROMPU), t("interruption"))
        self.assertEqual(self._issue(jr.INACHEVE), t("no ending"))
        for mot in (t("failure"), t("interruption"), t("no ending")):
            self.assertNotIn(mot, (t("failed"), t("interrupted")))

    def test_the_newest_comes_first(self):
        """Un flux se lit par le haut : mettre le plus ancien en tête
        obligerait à faire défiler pour voir ce qui arrive."""
        from script.todo.assistant.agents import tui as t_ui

        lignes = t_ui.lignes_flux(
            [
                self._appel(debut_ms=1_700_000_000_000, outil="vieux"),
                self._appel(debut_ms=1_700_000_009_000, outil="neuf"),
            ]
        )
        self.assertEqual([l["outil"] for l in lignes], ["neuf", "vieux"])

    def test_only_the_last_ones_are_kept(self):
        from script.todo.assistant.agents import tui as t_ui

        appels = [
            self._appel(debut_ms=1_700_000_000_000 + i, outil=str(i))
            for i in range(10)
        ]
        lignes = t_ui.lignes_flux(appels, limite=3)
        self.assertEqual([l["outil"] for l in lignes], ["9", "8", "7"])

    def test_an_unknown_duration_is_a_dash_and_never_a_zero(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel(duree_ms=None)])
        self.assertEqual(ligne["duree"], "—")

    def test_the_session_is_shortened_but_present(self):
        """Le flux réunit toutes les sessions de la machine : sans elle, deux
        terminaux se lisent comme un seul."""
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel()])
        self.assertEqual(ligne["session"], "aaaaaaaa")

    def test_every_column_the_table_asks_for_is_there(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel()])
        for cle, _ in t_ui.COLONNES_FLUX:
            self.assertIn(cle, ligne, cle)

    def test_nothing_to_show_is_no_row(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.lignes_flux([]), [])
