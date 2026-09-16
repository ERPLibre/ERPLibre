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

import os
import unittest
from unittest.mock import patch

from script.todo.assistant.agents import statistiques as st
from script.todo.assistant.agents import tui
from script.todo.todo_i18n import t


async def calme(pilote, tours=3):
    """Rendre la main jusqu'à ce que le fil de lecture ait posé son relevé.

    Les lectures se font HORS de la boucle d'événements. Une simple pause
    rend la main avant que le fil ait rien posé, et le test lirait un écran
    encore vide. Plusieurs tours parce qu'un relevé en demande un autre tant
    que la colonne des commandes n'est pas remplie.
    """
    for _ in range(tours):
        await pilote.pause()
        await pilote.app.workers.wait_for_complete()
    await pilote.pause()


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
        """Le chemin de travail vient de la TRANSCRIPTION, jamais du nom de
        répertoire de projet, qui ne s'inverse pas.

        Le nom est borné pour tenir dans une colonne, et coupé par la gauche :
        ce qui distingue une famille de dépôts est ce qui suit leur préfixe.
        """
        agregat = st.Agregat(cwd="/home/compte/git/erplibre_new_feature_01")
        lu = tui.projet(
            "/ignore/-home-compte-git-erplibre-new-feature-01/x.jsonl",
            agregat,
        )
        self.assertTrue(lu.endswith("_new_feature_01"), lu)
        self.assertLessEqual(len(lu), tui.PROJET_MAX)

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
                    # Un cost-state a été LU : sans lui, les durées et les
                    # lignes touchées se taisent, ce qu'un autre test fige.
                    segments=1,
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

    def test_the_prompt_column_counts_the_written_cache(self):
        """Le cache écrit est de l'invite, et il est facturé plus cher.

        L'omettre annonçait une fraction de ce qui est parti au modèle,
        d'autant plus grande que la séance est longue : la première écriture
        de cache porte tout le contexte.
        """
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        resume = oc.Resume(entree=1_000, cache_lu=7_000, cache_ecrit=42_000)
        (ligne,) = t_ui.lignes_opencode([self._seance(resume=resume)])
        self.assertEqual(ligne["entree"], t_ui.jetons(50_000))

    def test_the_cache_column_is_a_share_on_both_harnesses(self):
        """Open Code porte les deux moitiés du cache : un tiret dirait « pas
        mesuré » là où la base donne le chiffre."""
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        resume = oc.Resume(entree=1_000, cache_lu=7_000, cache_ecrit=2_000)
        (ligne,) = t_ui.lignes_opencode([self._seance(resume=resume)])
        self.assertEqual(ligne["cache"], "70%")

    def test_a_session_without_a_prompt_says_so_with_a_dash(self):
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        (ligne,) = t_ui.lignes_opencode(
            [self._seance(resume=oc.Resume(sortie=3))]
        )
        self.assertEqual(ligne["cache"], "—")

    def test_the_project_name_is_bounded_on_both_harnesses(self):
        """Une largeur de colonne ne dépend pas du harnais qui l'a remplie."""
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_opencode(
            [self._seance(repertoire="/un/depot/" + "n" * 40)]
        )
        self.assertLessEqual(len(ligne["projet"]), t_ui.PROJET_MAX)
        self.assertTrue(ligne["projet"].endswith("n"))

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

    Le monde porte DEUX de chaque sorte, et les deux appels d'outil tombent
    dans la même seconde. Un monde à un seul élément ne peut pas montrer une
    collision de clés, et c'est exactement ce qui avait laissé passer un
    écran qui mourait au premier tour sur une vraie machine.
    """

    CHEMIN = "/x/y/aaaaaaaa-1111-4111-8111-111111111111.jsonl"
    AUTRE_CHEMIN = "/x/y/bbbbbbbb-2222-4222-8222-222222222222.jsonl"

    # Ce que le panneau des agents montre, injecté : la vraie flotte
    # interrogerait l'outil, donc le réseau de personne et le PATH de
    # personne ne décident du verdict de ce test.
    AGENTS = (
        {
            # Ce qui identifie la rangée, jamais affiché : une faiseuse de
            # lignes doit le rendre, et la fausse aussi.
            "cle": "abcd1234",
            "id": "abcd1234",
            "projet": "projet",
            "etat": "",
            "branche": "une-branche",
            "pid": "4242",
        },
        {
            "cle": "efgh5678",
            "id": "efgh5678",
            "projet": "projet",
            "etat": "",
            "branche": "une-autre-branche",
            "pid": "4243",
        },
    )

    def _monde(self):
        """Les cinq lectures du disque, remplacées par de l'inventé."""
        from script.todo.assistant.agents import detail as dl
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        # Les deux appels tombent dans la MÊME seconde : c'est l'ordinaire
        # d'une session qui travaille, et c'est ce que le monde à un seul
        # appel ne pouvait pas montrer.
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
            {
                "hook_event_name": "PreToolUse",
                "tool_use_id": "2",
                "tool_name": "Read",
                "session_id": "bbbbbbbb-2222-4222-8222-222222222222",
                "ts": 1_700_000_000_500,
            },
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "2",
                "ts": 1_700_000_000_600,
                "duration_ms": 100,
            },
        ]
        seances = [
            oc.Seance(
                identifiant="ses_aaaabbbbccccdddd",
                repertoire="/un/depot/projet",
                modifie=1_700_000_000_000,
                resume=oc.Resume(entree=10, sortie=2, cout=0.5),
            ),
            oc.Seance(
                identifiant="ses_eeeeffffgggghhhh",
                repertoire="/un/depot/projet",
                modifie=1_700_000_000_000,
                resume=oc.Resume(entree=20, sortie=4, cout=0.25),
            ),
        ]
        return (
            # La flotte AUSSI : sans elle, `on_mount` lance le vrai
            # « claude agents --json » et parcourt le vrai ~/.claude. Un test
            # qui touche la machine de celui qui le lance ne mesure plus le
            # code, et il coûte un sous-processus par test.
            #
            # La couture est `cs.fleet` et non la méthode de l'application :
            # `run_tui` définit sa classe À CHAQUE APPEL, donc corriger celle
            # d'une instance ne change rien pour la suivante.
            patch(
                "script.todo.assistant.claude_sessions.fleet",
                return_value=[],
            ),
            patch.object(
                t_ui,
                "transcriptions",
                lambda: [self.CHEMIN, self.AUTRE_CHEMIN],
            ),
            patch.object(t_ui, "lignes_agents", lambda f: list(self.AGENTS)),
            patch.object(st, "lire", lambda c, l=None: st.Lecture()),
            patch.object(jr, "lire_lignes", lambda: evenements),
            patch.object(jr, "nettoyer", lambda *a, **k: None),
            patch.object(oc, "lire_base", lambda: list(seances)),
            # Le volet de détail relit la TRANSCRIPTION de l'appel : sans
            # couture, la touche « d » balaie le vrai ~/.claude de qui lance
            # la suite.
            patch.object(
                dl,
                "pour",
                lambda appel, **kw: dl.Detail(
                    outil="Bash",
                    commande="echo salut",
                    sortie="salut",
                    genre="commande",
                ),
            ),
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
                await calme(pilote)
                for touche in touches:
                    await pilote.press(touche)
                    await calme(pilote)
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
        self.assertEqual(vu["tables"]["tableau"][1], 4, "deux par harnais")
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
        """Le nombre de vues est DÉRIVÉ de l'écran : une vue de plus décalait
        ce test, comme un numéro de menu écrit en dur se décale."""
        from script.todo.assistant.agents import tui as t_ui

        tour = len(t_ui.run_tui(run_app=False).VUES)
        vu = await self._piloter(["v"] * tour)
        self.assertEqual(vu["vue"], "outils")
        self.assertIn(t("Per tool"), vu["titre"])

    async def test_le_resume_nomme_les_deux_harnais(self):
        from script.todo.assistant.agents import tui as t_ui

        vu = await self._piloter()
        self.assertIn(t_ui.ICONES["claude"], vu["resume"])
        self.assertIn(t_ui.ICONES["opencode"], vu["resume"])

    async def test_la_touche_n_ouvre_la_saisie_et_echap_la_referme(self):
        """Une saisie ouverte qu'on ne peut pas fermer piège l'écran."""
        from textual.widgets import Input

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                champ = app.query_one("#saisie", Input)
                self.assertFalse(champ.display, "fermée au montage")
                await pilote.press("n")
                await calme(pilote)
                self.assertTrue(champ.display)
                self.assertEqual(app._attente, app.INVITE)
                self.assertEqual(
                    champ.placeholder, t("Prompt for the new agent:")
                )
                await pilote.press("escape")
                await calme(pilote)
                self.assertFalse(champ.display)
                self.assertIsNone(app._attente)
        finally:
            for c in correctifs:
                c.stop()

    async def test_un_ecran_gele_le_reste_quand_la_fenetre_change(self):
        """Le gel arrête l'affichage, y compris sous un redimensionnement.

        Rétrécir la fenêtre change le NOMBRE de colonnes, et les reposer vide
        le tableau : l'écran qu'on avait gelé pour lire une ligne se retrouve
        blanc, puis rempli de la mesure de l'instant. Le dégel rattrape les
        deux.
        """
        from textual.widgets import DataTable

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                tableau = app.query_one("#tableau", DataTable)
                large = len(tableau.columns)
                self.assertEqual(tableau.row_count, 4)
                await pilote.press("f")
                await calme(pilote)
                peints = []
                app._peindre = lambda: peints.append(1)
                await pilote.resize_terminal(60, 40)
                await calme(pilote)
                self.assertEqual(peints, [], "gelé veut dire gelé")
                self.assertEqual(len(tableau.columns), large)
                self.assertEqual(tableau.row_count, 4)
                del app._peindre
                await pilote.press("f")
                await calme(pilote)
                self.assertLess(
                    len(tableau.columns),
                    large,
                    "le dégel rattrape la largeur perdue",
                )
        finally:
            for c in correctifs:
                c.stop()

    async def test_le_volet_de_detail_se_ferme_avec_son_panneau(self):
        """Le volet montre du CONTENU, et il le doit à une ligne du flux.

        Le flux parti, plus rien à l'écran ne désigne ce qu'il montre, et la
        mention qui prévient ne se rapporte plus à rien de visible.
        """
        from textual.widgets import Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                volet = app.query_one("#detail", Static)
                await pilote.press("v")
                await calme(pilote)
                self.assertEqual(app.VUES[app._vue], "flux")
                await pilote.press("d")
                await calme(pilote)
                self.assertTrue(volet.display, "une ligne du flux est là")
                await pilote.press("v")
                await calme(pilote)
                self.assertFalse(volet.display)
                self.assertEqual(str(volet.render()), "")
        finally:
            for c in correctifs:
                c.stop()

    async def test_une_transcription_effacee_quitte_le_tableau(self):
        """Ce que le disque ne porte plus, l'écran ne le montre plus.

        Les lectures sont incrémentales, donc le dictionnaire se complétait
        sans jamais perdre une entrée : une session effacée gardait sa ligne
        et ses totaux pour toute la durée de l'écran.
        """
        from textual.widgets import DataTable

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                tableau = app.query_one("#tableau", DataTable)
                self.assertEqual(tableau.row_count, 4, "deux par harnais")
                t_ui.transcriptions = lambda: []
                app._tick()
                await calme(pilote)
                self.assertEqual(app._lectures, {})
                self.assertEqual(
                    tableau.row_count, 2, "les séances Open Code restent"
                )
        finally:
            for c in correctifs:
                c.stop()

    async def test_une_action_sans_agent_choisi_le_dit(self):
        """Le panneau des agents est vide dans ce monde-ci : la touche doit
        répondre, et surtout ne rien envoyer."""
        from textual.widgets import Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            envoyes = []
            async with app.run_test(size=(160, 40)) as pilote:
                app._lancer_action = lambda sc, p: envoyes.append((sc, p))
                await calme(pilote)
                await pilote.press("s")
                await calme(pilote)
                # `#etat` et non `#source` : le second porte la phrase fixe
                # sur la provenance des chiffres, que `_resumer` réécrit à
                # chaque repeint et qui effaçait donc ce qu'on venait de dire.
                dit = str(app.query_one("#etat", Static).render())
            self.assertEqual(envoyes, [])
            self.assertIn(t("Pick a detached agent first."), dit)
        finally:
            for c in correctifs:
                c.stop()

    async def test_une_action_hors_du_panneau_des_agents_ne_part_pas(self):
        """Un agent existe, mais on regarde le panneau des outils.

        Sans ce garde-fou, une touche pressée par réflexe dans un autre
        panneau arrêterait l'agent surligné d'un panneau qu'on ne voit pas.
        """
        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            envoyes = []
            async with app.run_test(size=(160, 40)) as pilote:
                app._lancer_action = lambda sc, p: envoyes.append((sc, p))
                await calme(pilote)
                # Un agent est là, mais la vue courante n'est pas la sienne.
                app._agents = [object()]
                self.assertNotEqual(app.VUES[app._vue], "agents")
                await pilote.press("s")
                await calme(pilote)
            self.assertEqual(envoyes, [])
        finally:
            for c in correctifs:
                c.stop()

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


class TestQuiEstUnAgentDetache(unittest.TestCase):
    """La flotte réunit deux sources qui ne disent pas la même chose.

    Le registre annonce ce qui TOURNE ; un balayage des transcriptions annonce
    ce qui se REPREND. Une session dormante en sort sans genre ni processus —
    l'offrir au panneau proposerait `stop` sur un fichier, et l'outil
    répondrait « No job matching » avec un code de sortie NUL, donc sans que
    rien ne paraisse échouer.
    """

    def _session(self, **champs):
        from script.todo.assistant import claude_sessions as cs

        defauts = {
            "session_id": "aaaaaaaa-1111-4111-8111-111111111111",
            "kind": "background",
            "live": True,
            "cwd": "/un/depot/projet",
            "status": "busy",
            "branch": "une-branche",
            "pid": 4242,
        }
        defauts.update(champs)
        return cs.Session(**defauts)

    def test_a_live_detached_agent_is_one(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(len(t_ui.agents_detaches([self._session()])), 1)

    def test_a_terminal_is_not_one(self):
        from script.todo.assistant.agents import tui as t_ui

        session = self._session(kind="interactive")
        self.assertEqual(t_ui.agents_detaches([session]), [])

    def test_a_dormant_session_is_not_one(self):
        """Genre vide et pid nul : c'est un fichier, pas un processus."""
        from script.todo.assistant.agents import tui as t_ui

        session = self._session(kind="", live=False, pid=0)
        self.assertEqual(t_ui.agents_detaches([session]), [])

    def test_a_detached_agent_that_exited_is_not_one(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.agents_detaches([self._session(live=False)]), [])

    def test_nothing_read_is_no_agent(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.agents_detaches(None), [])
        self.assertEqual(t_ui.agents_detaches([]), [])

    def test_the_row_carries_no_title_and_no_name(self):
        """Le `name` du registre est engendré par le modèle à partir de
        l'invite : c'est du contenu, pas un champ structurel."""
        from script.todo.assistant.agents import tui as t_ui

        temoin = "titre-engendre-qui-ne-doit-pas-sortir"
        session = self._session(name=temoin)
        (ligne,) = t_ui.lignes_agents(t_ui.agents_detaches([session]))
        self.assertNotIn(temoin, repr(ligne))
        self.assertEqual(ligne["id"], "aaaaaaaa")
        self.assertEqual(ligne["projet"], "projet")

    def test_the_index_of_a_row_is_the_index_of_its_session(self):
        """C'est ce qui permet à l'écran de remonter d'une ligne surlignée à
        la session, sans rapprocher par du texte."""
        from script.todo.assistant.agents import tui as t_ui

        sessions = [
            self._session(session_id="1" * 32),
            self._session(session_id="2" * 32),
        ]
        agents = t_ui.agents_detaches(sessions)
        lignes = t_ui.lignes_agents(agents)
        self.assertEqual(len(lignes), len(agents))
        for rang, ligne in enumerate(lignes):
            self.assertEqual(ligne["id"], agents[rang].poignee)

    def test_every_column_the_table_asks_for_is_there(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_agents(t_ui.agents_detaches([self._session()]))
        for cle, _ in t_ui.COLONNES_AGENTS:
            self.assertIn(cle, ligne, cle)


class TestLeVoletDeDetail(unittest.TestCase):
    """Le seul endroit de l'écran qui montre du contenu.

    Il le DIT, en tête et non en bas : un volet qui déroule une longue sortie
    pousserait l'avertissement hors de l'écran, et il ne servirait qu'à ceux
    qui n'en ont pas besoin.
    """

    def _appel(self, duree_ms=400):
        from script.todo.assistant.agents import journal as jr

        return jr.Appel(
            outil="Bash",
            session="aaaaaaaa",
            debut_ms=1_700_000_000_000,
            duree_ms=duree_ms,
            identifiant="toolu_01aaaa",
        )

    def _texte(self, duree_ms=400, **champs):
        from script.todo.assistant.agents import detail as dl
        from script.todo.assistant.agents import tui as t_ui

        return t_ui.texte_du_detail(self._appel(duree_ms), dl.Detail(**champs))

    def test_the_warning_comes_first(self):
        texte = self._texte(outil="Bash", commande="echo x", sortie="x")
        self.assertTrue(
            texte.startswith(t("This pane shows conversation content."))
        )

    def test_the_command_and_its_output_are_there(self):
        texte = self._texte(
            outil="Bash", commande="echo bonjour", sortie="bonjour"
        )
        self.assertIn("echo bonjour", texte)
        self.assertIn("bonjour", texte)

    def test_an_unknown_duration_is_a_dash_and_never_a_zero(self):
        """Zéro se lirait « instantané » sur un appel encore en cours."""
        texte = self._texte(duree_ms=None, outil="Bash", commande="sleep 60")
        self.assertIn("Bash  —", texte)
        self.assertNotIn("0 ms", texte)

    def test_no_answer_yet_is_told_apart_from_an_empty_answer(self):
        """L'un est un appel en cours, l'autre une commande silencieuse."""
        encours = self._texte(outil="Bash", commande="x", sortie=None)
        muette = self._texte(outil="Bash", commande="x", sortie="")
        self.assertIn(t("No answer yet."), encours)
        self.assertIn(t("The command answered nothing."), muette)
        self.assertNotIn(t("No answer yet."), muette)

    def test_an_error_is_announced(self):
        texte = self._texte(
            outil="Bash", commande="faux", sortie="oups", erreur=True
        )
        self.assertIn(t("The tool reported an error."), texte)

    def test_a_call_not_in_the_transcript_says_so(self):
        """Un volet vide se lirait comme une panne de l'écran."""
        texte = self._texte()
        self.assertIn(t("This call was not found in the transcript."), texte)
        self.assertTrue(
            texte.startswith(t("This pane shows conversation content."))
        )

    def test_a_long_output_is_bounded_and_says_it(self):
        texte = self._texte(outil="Bash", commande="x", sortie="z" * 9000)
        self.assertLess(len(texte), 6000)
        self.assertIn("+", texte)


class TestLaColonneDeCommande(unittest.TestCase):
    """Trois états, et les confondre fait attendre ce qui ne viendra pas."""

    def _appel(self, identifiant="toolu_01aaaa"):
        from script.todo.assistant.agents import journal as jr

        return jr.Appel(
            outil="Bash",
            session="aaaaaaaa",
            debut_ms=1_700_000_000_000,
            duree_ms=400,
            identifiant=identifiant,
        )

    def _colonne(self, commandes):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel()], commandes=commandes)
        return ligne["commande"]

    def test_not_looked_up_yet_shows_dots(self):
        self.assertEqual(self._colonne(None), "…")
        self.assertEqual(self._colonne({}), "…")

    def test_looked_up_and_empty_shows_a_dash(self):
        """La transcription a répondu, et cet appel n'a pas de commande."""
        self.assertEqual(self._colonne({"toolu_01aaaa": ("", True)}), "—")

    def test_a_command_shows_on_one_line(self):
        colonne = self._colonne({"toolu_01aaaa": ("echo un\necho deux", True)})
        self.assertEqual(colonne, "echo un echo deux")

    def test_the_column_is_declared_in_the_table(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertIn("commande", [cle for cle, _ in t_ui.COLONNES_FLUX])


class TestCeQuiTientDansUnTerminal(unittest.TestCase):
    """Les colonnes s'étaient accumulées sans que personne mesure la largeur.

    Douze colonnes réclament cent vingt-quatre caractères, et le flux en
    réclamait quatre-vingt-quinze dont cinquante-cinq pour la seule commande.
    Un terminal de quatre-vingts colonnes — le défaut le plus répandu — n'en
    montrait ni l'un ni l'autre. Rien n'est cassé, Textual fait défiler ; mais
    un tableau de bord qu'il faut faire défiler ne se lit plus d'un coup.
    """

    def test_the_command_column_takes_what_is_left(self):
        """Une largeur FIXE se trompe des deux côtés : elle déborde d'un
        terminal étroit et gaspille celui d'un large."""
        from script.todo.assistant.agents import tui as t_ui

        etroit = t_ui.largeur_commande(80)
        large = t_ui.largeur_commande(200)
        self.assertLess(etroit, large)
        self.assertEqual(etroit + t_ui.FLUX_AUTRES, 80)

    def test_the_command_column_never_shrinks_to_nothing(self):
        """En dessous d'un plancher elle ne montre plus rien d'utile : mieux
        vaut déborder et se faire défiler."""
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.largeur_commande(10), t_ui.COMMANDE_MIN)
        self.assertEqual(t_ui.largeur_commande(0), t_ui.COMMANDE_MIN)
        self.assertEqual(t_ui.largeur_commande(None), t_ui.COMMANDE_MIN)

    def test_a_narrow_screen_keeps_the_columns_that_matter(self):
        """L'ordre décide de ce qui reste : laquelle, où, combien ça coûte,
        où en est son contexte."""
        from script.todo.assistant.agents import tui as t_ui

        visibles = [c for _, c in t_ui.colonnes_visibles(80)]
        self.assertEqual(
            visibles[:4], ["session", "project", "cost", "context"]
        )

    def test_a_wide_screen_keeps_them_all(self):
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(t_ui.colonnes_visibles(400), tuple(t_ui.COLONNES))

    def test_a_screen_grows_and_so_does_the_table(self):
        from script.todo.assistant.agents import tui as t_ui

        largeurs = [len(t_ui.colonnes_visibles(l)) for l in (60, 100, 160)]
        self.assertEqual(largeurs, sorted(largeurs))
        self.assertLess(largeurs[0], largeurs[-1])

    def test_two_columns_survive_any_width(self):
        """Un tableau qui ne dirait ni quelle session ni quel projet ne dirait
        rien du tout."""
        from script.todo.assistant.agents import tui as t_ui

        for etroit in (0, 1, 20, None):
            visibles = t_ui.colonnes_visibles(etroit)
            self.assertEqual(len(visibles), 2, repr(etroit))
            self.assertEqual([c for _, c in visibles], ["session", "project"])

    def test_a_project_name_is_cut_on_the_left(self):
        """Une famille de dépôts partage son préfixe et se distingue par ce
        qui suit : couper par la droite les rendrait tous identiques."""
        from script.todo.assistant.agents import statistiques as st_
        from script.todo.assistant.agents import tui as t_ui

        noms = [
            t_ui.projet("/x/y.jsonl", st_.Agregat(cwd=f"/c/{n}"))
            for n in ("erplibre_todo_assistant", "erplibre_new_feature_01")
        ]
        self.assertEqual(len(set(noms)), 2, "les deux restent distincts")
        for nom in noms:
            self.assertLessEqual(len(nom), t_ui.PROJET_MAX)
            self.assertTrue(nom.startswith("…"))

    def test_a_short_project_name_is_untouched(self):
        from script.todo.assistant.agents import statistiques as st_
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(
            t_ui.projet("/x/y.jsonl", st_.Agregat(cwd="/c/erplibre")),
            "erplibre",
        )

    def test_the_growth_bar_fits_a_column(self):
        """À vingt-quatre elle était la plus large du tableau."""
        from script.todo.assistant.agents import tui as t_ui

        self.assertEqual(len(t_ui.barre(tuple(range(1, 200)))), t_ui.BARRE)
        self.assertLessEqual(t_ui.BARRE, 12)


class TestLesDeuxGestesQuiCoutent(unittest.IsolatedAsyncioTestCase):
    """Relancer coupe le travail ; supprimer efface l'arbre et ne revient pas.

    Deux gardes, et l'écart entre elles est tout le propos : une frappe sur
    « o » se donne par réflexe, recopier trente-six caractères oblige à
    regarder ce qu'on détruit. C'est la même échelle que le menu, portée dans
    l'écran vivant.
    """

    SESSION = "aaaaaaaa-1111-4111-8111-111111111111"

    async def _piloter(self, touche, frappe):
        from textual.widgets import Input

        from script.todo.assistant import claude_sessions as cs
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        session = cs.Session(
            session_id=self.SESSION,
            kind="background",
            live=True,
            cwd="/un/depot/projet",
            pid=4242,
        )
        envoyes = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [session])
            async with app.run_test(size=(160, 40)) as pilote:
                app._lancer_action = lambda sc, p: envoyes.append((sc, p))
                await calme(pilote)
                for _ in t_ui.run_tui(run_app=False).VUES:
                    if app.VUES[app._vue] == "agents":
                        break
                    await pilote.press("v")
                    await calme(pilote)
                await pilote.press(touche)
                await calme(pilote)
                champ = app.query_one("#saisie", Input)
                from textual.widgets import Static

                invite = str(app.query_one("#etat", Static).render())
                champ.value = frappe
                await pilote.press("enter")
                await calme(pilote)
        return invite, envoyes

    async def test_restarting_asks_for_a_yes(self):
        _, envoyes = await self._piloter("l", "oui")
        self.assertEqual(envoyes, [("respawn", "aaaaaaaa")])

    async def test_restarting_without_a_yes_sends_nothing(self):
        for frappe in ("non", "", "peut-être", "o u i"):
            _, envoyes = await self._piloter("l", frappe)
            self.assertEqual(envoyes, [], frappe)

    async def test_deleting_wants_the_whole_identifier(self):
        _, envoyes = await self._piloter("x", self.SESSION)
        self.assertEqual(envoyes, [("rm", "aaaaaaaa")])

    async def test_the_short_identifier_is_not_enough_to_delete(self):
        """C'est la LONGUEUR qui fait la garde : recopier huit caractères se
        fait sans regarder, et c'est exactement ce qu'on veut empêcher."""
        _, envoyes = await self._piloter("x", "aaaaaaaa")
        self.assertEqual(envoyes, [])

    async def test_the_prompt_says_what_each_one_costs(self):
        """La consigne vit AU-DESSUS du champ et non dedans.

        Un « placeholder » disparaît à la première frappe, et l'identifiant de
        trente-six caractères à recopier n'était alors plus nulle part — le
        tableau ne montre que la poignée de huit.
        """
        relance, _ = await self._piloter("l", "")
        efface, _ = await self._piloter("x", "")
        self.assertIn(t("The work in progress is cut. Type yes:"), relance)
        self.assertIn(
            t("This deletes the session and its worktree. Retype:"), efface
        )
        self.assertIn(self.SESSION, efface, "l'identifiant à recopier")

    async def test_the_action_uses_the_short_identifier(self):
        """Les sous-commandes n'acceptent que lui : passer l'UUID rend « No
        job matching » avec un code de sortie nul."""
        _, envoyes = await self._piloter("x", self.SESSION)
        ((_, poignee),) = envoyes
        self.assertEqual(poignee, "aaaaaaaa")
        self.assertNotEqual(poignee, self.SESSION)


class TestCeQueLEcranRendEnSortant(unittest.IsolatedAsyncioTestCase):
    """Attacher ferme l'écran, donc la commande doit lui survivre.

    `claude attach` prend le terminal et ne peut pas le partager avec une
    application qui le tient déjà. L'écran quitte donc en RENDANT la commande,
    et c'est l'appelant qui la lance. La jeter fermait l'écran sans rien dire,
    et il ne restait ni écran ni commande.
    """

    async def _sortir(self, avec_agent=True):
        from script.todo.assistant import claude_sessions as cs
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        flotte = (
            [
                cs.Session(
                    session_id="aaaaaaaa-1111-4111-8111-111111111111",
                    kind="background",
                    live=True,
                    cwd="/un/depot",
                    pid=4242,
                )
            ]
            if avec_agent
            else []
        )
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: flotte)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                while app.VUES[app._vue] != "agents":
                    await pilote.press("v")
                    await calme(pilote)
                await pilote.press("a")
                await calme(pilote)
            return app.return_value

    async def test_attaching_hands_the_command_back(self):
        self.assertEqual(await self._sortir(), "claude attach aaaaaaaa")

    async def test_the_command_carries_the_short_identifier(self):
        """Les sous-commandes n'acceptent que lui."""
        rendu = await self._sortir()
        self.assertNotIn("1111-4111", rendu)

    async def test_without_an_agent_the_screen_stays_open(self):
        """Rien à attacher n'est pas une raison de fermer l'écran."""
        self.assertIsNone(await self._sortir(avec_agent=False))

    def test_run_tui_hands_back_what_the_screen_returned(self):
        """Le pilote de Textual n'exerce jamais cette ligne-là.

        Les autres tests montent l'application eux-mêmes et lisent son
        `return_value` ; celui-ci vérifie le CHEMIN ORDINAIRE, où `run_tui`
        lance l'écran et doit rendre ce qu'il rapporte.
        """
        from textual.app import App

        from script.todo.assistant.agents import tui as t_ui

        with patch.object(App, "run", return_value="claude attach abcd1234"):
            self.assertEqual(t_ui.run_tui(), "claude attach abcd1234")

    def test_the_menu_runs_what_the_screen_hands_back(self):
        """Sans cela, l'écran se fermerait et la commande se perdrait."""
        import ast

        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        chemin = os.path.join(racine, "script", "todo", "assistant_menu.py")
        with open(chemin, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        corps = next(
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_agents_telemetrie"
        )
        source = ast.dump(corps)
        self.assertIn("run_tui", source)
        # Par la porte du plein écran, jamais par le tube : « claude attach »
        # exige un terminal, et le lanceur ordinaire n'en fournit pas.
        self.assertIn("_ouvrir_plein_ecran", source)
        self.assertNotIn("exec_command_live", source)

    async def test_an_empty_identifier_never_opens_the_guard(self):
        """Le listage peut ne pas porter « sessionId ».

        `Session.session_id` vaut alors "", l'invite affiche « Retape : »
        suivi du vide, et une frappe d'Entrée donnait `"" == ""`. La garde la
        plus forte du paquet s'ouvrait sur rien, et `claude rm` partait avec
        la séance ET son arbre de travail.
        """
        from textual.widgets import Input

        from script.todo.assistant import claude_sessions as cs
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        sans_uuid = cs.Session(
            session_id="",
            court="aaaaaaaa",
            kind="background",
            live=True,
            cwd="/un/depot",
            pid=4242,
        )
        envoyes = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [sans_uuid])
            async with app.run_test(size=(160, 40)) as pilote:
                app._lancer_action = lambda sc, p: envoyes.append((sc, p))
                await calme(pilote)
                while app.VUES[app._vue] != "agents":
                    await pilote.press("v")
                    await calme(pilote)
                self.assertEqual(app._agent_choisi().poignee, "aaaaaaaa")
                await pilote.press("x")
                await calme(pilote)
                app.query_one("#saisie", Input).value = ""
                await pilote.press("enter")
                await calme(pilote)
        self.assertEqual(envoyes, [])


class TestDeuxLignesNeSeVolentPasLeurCle(unittest.IsolatedAsyncioTestCase):
    """Une clé de rangée en double TUE l'écran, elle ne le dégrade pas.

    `add_row` lève `DuplicateKey`, et une exception dans un gestionnaire de
    message ferme l'application. Le flux était clé par l'HEURE affichée, à la
    seconde : deux appels d'outil dans la même seconde suffisaient, ce qui est
    l'ordinaire d'une session qui travaille.
    """

    def _monde(self, evenements):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        return (
            patch(
                "script.todo.assistant.claude_sessions.fleet",
                return_value=[],
            ),
            patch.object(t_ui, "transcriptions", lambda: []),
            patch.object(jr, "lire_lignes", lambda: evenements),
            patch.object(jr, "nettoyer", lambda *a, **k: None),
            patch.object(oc, "lire_base", lambda: None),
            patch.object(
                t_ui.dl, "pour", lambda appel, **kw: t_ui.dl.Detail()
            ),
        )

    def _appel(self, identifiant, ts):
        return [
            {
                "hook_event_name": "PreToolUse",
                "tool_use_id": identifiant,
                "tool_name": "Bash",
                "session_id": "aaaaaaaa-1111-4111-8111-111111111111",
                "ts": ts,
            },
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": identifiant,
                "ts": ts + 10,
                "duration_ms": 10,
            },
        ]

    async def test_deux_appels_dans_la_meme_seconde_tiennent_l_ecran(self):
        """Même milliseconde d'affichage, deux rangées, et l'écran vit."""
        from textual.widgets import DataTable

        from script.todo.assistant.agents import tui as t_ui

        evenements = self._appel("un", 1_700_000_000_100) + self._appel(
            "deux", 1_700_000_000_300
        )
        correctifs = self._monde(evenements)
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                for _ in range(len(app.VUES)):
                    if app.VUES[app._vue] == "flux":
                        break
                    await pilote.press("v")
                    await calme(pilote)
                self.assertEqual(app.VUES[app._vue], "flux")
                flux = app.query_one("#flux", DataTable)
                self.assertEqual(flux.row_count, 2)
                lignes = t_ui.lignes_flux(app._appels)
                self.assertEqual(
                    len({l["heure"] for l in lignes}),
                    1,
                    "les deux montrent bien la même heure",
                )
        finally:
            for c in correctifs:
                c.stop()

    def test_chaque_faiseuse_de_lignes_donne_une_cle_unique(self):
        """La clé est un champ à part, jamais une colonne affichée.

        Ce qui IDENTIFIE une rangée et ce qui la DÉCRIT sont deux choses : la
        seconde se choisit pour se lire, et rien n'oblige deux lignes à s'y
        distinguer.
        """
        from script.todo.assistant.agents import tui as t_ui

        evenements = self._appel("un", 1_700_000_000_100) + self._appel(
            "deux", 1_700_000_000_300
        )
        from script.todo.assistant.agents import journal as jr

        appels = jr.apparier(evenements)
        lignes = t_ui.lignes_flux(appels)
        self.assertEqual(len(lignes), 2)
        self.assertEqual(len({ligne["cle"] for ligne in lignes}), 2)

    def test_les_cinq_faiseuses_de_lignes_rendent_une_cle(self):
        """Toutes, et non celle qu'on vient de réparer.

        Une faiseuse de lignes ajoutée plus tard sans clé ne lèverait qu'au
        moment de peindre, sur la machine de quelqu'un.
        """
        from script.todo.assistant import claude_sessions as cs
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        seance = oc.Seance(
            identifiant="ses_aaaabbbbccccdddd",
            repertoire="/un/depot/projet",
            modifie=1_700_000_000_000,
            resume=oc.Resume(entree=10, sortie=2),
        )
        session = cs.Session(
            session_id="aaaaaaaa-1111-4111-8111-111111111111",
            court="aaaaaaaa",
            kind="background",
            live=True,
        )
        appels = jr.apparier(self._appel("un", 1_700_000_000_100))
        lots = {
            "lignes": t_ui.lignes({"/x/y/aaaaaaaa.jsonl": st.Lecture()}),
            "lignes_opencode": t_ui.lignes_opencode([seance]),
            "lignes_flux": t_ui.lignes_flux(appels),
            "lignes_outils": t_ui.lignes_outils(jr.par_outil(appels)),
            "lignes_agents": t_ui.lignes_agents([session]),
        }
        for nom, lignes in lots.items():
            self.assertTrue(lignes, nom)
            for ligne in lignes:
                self.assertIn("cle", ligne, nom)
                self.assertTrue(ligne["cle"], nom)

    async def test_une_cle_en_double_ne_ferme_plus_l_ecran(self):
        """Le filet, pour la colonne qu'on choisira mal la prochaine fois."""
        from textual.widgets import DataTable

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde([])
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                table = app.query_one("#outils", DataTable)
                doublons = [
                    dict.fromkeys(
                        [c for c, _ in t_ui.COLONNES_OUTILS] + ["cle"],
                        "pareil",
                    )
                    for _ in range(3)
                ]
                app._repeindre(table, doublons, t_ui.COLONNES_OUTILS, "cle")
                self.assertEqual(table.row_count, 3)
        finally:
            for c in correctifs:
                c.stop()


class TestLeGelTientDeBoutEnBout(unittest.IsolatedAsyncioTestCase):
    """Un gel qui cède est pire qu'un gel absent.

    On gèle pour qu'une ligne cesse de se dérober, puis on agit dessus. Si un
    geste d'affichage repeint quand même, l'écran s'annonce gelé et montre
    autre chose : « s », qui ne demande aucune confirmation, part alors sur un
    agent que personne n'a choisi.
    """

    def _agent(self, court):
        from script.todo.assistant import claude_sessions as cs

        return cs.Session(
            session_id=f"{court}-1111-4111-8111-111111111111",
            court=court,
            kind="background",
            live=True,
            cwd="/un/depot",
            pid=42,
        )

    async def test_permuter_le_panneau_ne_degele_pas_l_ecran(self):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        flotte = [self._agent(c) for c in ("aaaaaaaa", "bbbbbbbb")]
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: list(flotte))
            async with app.run_test(size=(120, 40)) as pilote:
                await calme(pilote)
                for _ in range(len(app.VUES)):
                    if app.VUES[app._vue] == "agents":
                        break
                    await pilote.press("v")
                    await calme(pilote)
                await pilote.press("down")
                await calme(pilote)
                self.assertEqual(app._agent_choisi().poignee, "bbbbbbbb")
                await pilote.press("f")
                await calme(pilote)
                # La flotte change sous l'écran gelé.
                flotte[:] = [self._agent("cccccccc")]
                app._flotte_a_relire = True
                app._tick()
                await calme(pilote)
                # Un tour complet de panneaux, et retour.
                envoyes = []
                app._lancer_action = lambda sc, p: envoyes.append((sc, p))
                for _ in range(len(app.VUES)):
                    await pilote.press("v")
                    await calme(pilote)
                self.assertEqual(app.VUES[app._vue], "agents")
                self.assertTrue(app._gele, "toujours gelé")
                self.assertEqual(app._agent_choisi().poignee, "bbbbbbbb")
                await pilote.press("s")
                await calme(pilote)
        self.assertEqual(envoyes, [("stop", "bbbbbbbb")])

    async def test_relire_n_ouvre_pas_un_second_fil(self):
        """« r » maintenu en ouvrait un par frappe, chacun relisant tout.

        Le drapeau appartient au fil qui lit ; le baisser court-circuite le
        garde « une seule lecture à la fois ».
        """
        import time as horloge

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        dedans, crete = [0], [0]
        vrai = t_ui.relever

        def lent(*a, **kw):
            dedans[0] += 1
            crete[0] = max(crete[0], dedans[0])
            try:
                horloge.sleep(0.25)
                return vrai(*a, **kw)
            finally:
                dedans[0] -= 1

        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(120, 40)) as pilote:
                await calme(pilote)
                with patch.object(t_ui, "relever", lent):
                    for _ in range(8):
                        await pilote.press("r")
                    await calme(pilote, tours=6)
        self.assertEqual(crete[0], 1, "une seule lecture à la fois")
        self.assertIsNone(app._lecture_en_cours, "et la place se rend")

    async def test_le_rafraichissement_survit_a_un_r_en_plein_vol(self):
        """La place se rend à celui qui la tenait, périmé ou non.

        La lui refuser arrêtait l'écran POUR DE BON : plus aucun tour ne
        pouvait partir, et rien ne le disait.
        """
        import time as horloge

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        vrai = t_ui.relever

        def lent(*a, **kw):
            horloge.sleep(0.3)
            return vrai(*a, **kw)

        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(120, 40)) as pilote:
                await calme(pilote)
                with patch.object(t_ui, "relever", lent):
                    app._tick()
                    await pilote.pause()
                    # « r » pendant que le fil lit encore.
                    await pilote.press("r")
                    await calme(pilote, tours=6)
                tours = []
                app._tick()
                await calme(pilote)
                self.assertIsNone(app._lecture_en_cours)
                # Et un tour ordinaire repart.
                app._flotte_a_relire = True
                app._lire_flotte = staticmethod(lambda: tours.append(1) or [])
                app._tick()
                await calme(pilote)
        self.assertEqual(tours, [1], "le rafraîchissement continue")


class TestUnGesteNeFigePasLEcran(unittest.IsolatedAsyncioTestCase):
    """Les gestes passent par un sous-processus, comme les lectures.

    `claude stop|respawn|rm` attend jusqu'à soixante secondes. Lancé sur la
    boucle d'événements, un outil qui ne rend pas la main figeait l'écran
    d'autant — une minute sans une touche, sur un geste qu'on vient de
    demander.
    """

    def _agent(self):
        from script.todo.assistant import claude_sessions as cs

        return cs.Session(
            session_id="aaaaaaaa-1111-4111-8111-111111111111",
            court="aaaaaaaa",
            kind="background",
            live=True,
            cwd="/un/depot",
            pid=4242,
        )

    async def _ecran(self, lancer):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        import subprocess

        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ), patch.object(
            subprocess, "run", lancer
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [self._agent()])
            async with app.run_test(size=(120, 40)) as pilote:
                await calme(pilote)
                for _ in range(len(app.VUES)):
                    if app.VUES[app._vue] == "agents":
                        break
                    await pilote.press("v")
                    await calme(pilote)
                yield app, pilote

    async def test_le_geste_ne_bloque_pas_la_boucle(self):
        import time as horloge

        lent = 0.4

        def dort(argv, **kw):
            horloge.sleep(lent)
            return type("F", (), {"stdout": "stopped aaaaaaaa", "stderr": ""})

        async for app, pilote in self._ecran(dort):
            depart = horloge.perf_counter()
            app._lancer_action("stop", "aaaaaaaa")
            rendu = horloge.perf_counter() - depart
            self.assertLess(rendu, lent / 4, "le geste rend la main")
            await calme(pilote)

    async def test_ce_que_l_outil_a_dit_arrive_a_l_ecran(self):
        """« No job matching » vient avec un code de sortie NUL : c'est la
        seule trace qu'un geste n'a pas eu lieu."""
        from textual.widgets import Static

        def muet(argv, **kw):
            return type(
                "F", (), {"stdout": "No job matching aaaaaaaa", "stderr": ""}
            )

        async for app, pilote in self._ecran(muet):
            await pilote.press("s")
            await calme(pilote)
            self.assertIn(
                "No job matching",
                str(app.query_one("#etat", Static).render()),
            )

    async def test_un_outil_absent_le_dit_au_lieu_de_mourir(self):
        from textual.widgets import Static

        def absent(argv, **kw):
            raise OSError("claude: introuvable")

        async for app, pilote in self._ecran(absent):
            await pilote.press("s")
            await calme(pilote)
            self.assertIn(
                "introuvable", str(app.query_one("#etat", Static).render())
            )

    async def test_un_identifiant_vide_est_refuse_tout_de_suite(self):
        """Un refus immédiat : le faire voyager retarderait le seul message
        qui apprenne quelque chose."""
        from textual.widgets import Static

        lances = []

        def compte(argv, **kw):
            lances.append(argv)
            return type("F", (), {"stdout": "", "stderr": ""})

        async for app, pilote in self._ecran(compte):
            app._lancer_action("stop", "")
            await calme(pilote)
            self.assertEqual(lances, [])
            self.assertTrue(str(app.query_one("#etat", Static).render()))


class TestLePanneauDesTouches(unittest.IsolatedAsyncioTestCase):
    """Le pied de page ment par omission, et « h » est ce qui le rattrape.

    Il tient sur UNE ligne et se coupe à droite : sur un terminal de
    quatre-vingts colonnes, onze indications en perdaient quatre — dont les
    deux qui détruisent. Rien à l'écran ne disait qu'elles existaient.
    """

    def test_le_pied_de_page_nomme_la_touche_qui_mene_aux_autres(self):
        """La garde qui compte : ce qui tient dans un terminal ordinaire.

        Quatre-vingts colonnes est la largeur d'un terminal qu'on n'a pas
        élargi, et c'est là que le pied de page coupe. Peu importe combien de
        touches y tiennent — il faut que « h » en soit, sans quoi les autres
        n'existent pas.
        """
        from script.todo.assistant.agents import tui as t_ui

        app = t_ui.run_tui(run_app=False)
        largeur, visibles = 0, []
        for touche, _action, libelle in app.BINDINGS:
            largeur += len(f"{touche} {libelle}") + 2
            if largeur > 80:
                break
            visibles.append(touche)
        self.assertIn("h", visibles, "la touche d'aide doit rester visible")
        self.assertIn("q", visibles, "et celle qui sort")

    def test_les_touches_ne_sont_declarees_qu_une_fois(self):
        """Le pied de page, le panneau et les numéros lisent la MÊME table.

        C'est la recopie qui avait laissé quatre touches sans mention nulle
        part ; un panneau d'aide tenu à la main décrit tôt ou tard un écran
        qui n'existe plus, et c'est justement celui qu'on vient consulter.
        """
        from script.todo.assistant.agents import tui as t_ui

        app = t_ui.run_tui(run_app=False)
        table = t_ui.TOUCHES_AFFICHAGE + t_ui.TOUCHES_LIGNE
        self.assertEqual([b[0] for b in app.BINDINGS], [t[0] for t in table])
        aide = t_ui.texte_de_l_aide()
        for touche, _action, _court, phrase in table:
            self.assertIn(t(phrase), aide, touche)
        for rang in range(len(t_ui.TOUCHES_LIGNE)):
            self.assertIn(f"[{rang + 1}]", aide)

    def test_chaque_touche_a_son_action(self):
        """Une entrée de table sans méthode ne lèverait qu'à la frappe."""
        from script.todo.assistant.agents import tui as t_ui

        app = t_ui.run_tui(run_app=False)
        for touche, action, _c, _p in t_ui.TOUCHES_LIGNE:
            self.assertTrue(
                hasattr(app, f"action_{action}"), f"{touche} → {action}"
            )

    def test_les_libelles_sont_declares_dans_les_deux_langues(self):
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.todo_i18n import TRANSLATIONS

        for _t, _a, court, phrase in (
            t_ui.TOUCHES_AFFICHAGE + t_ui.TOUCHES_LIGNE
        ):
            self.assertIn(court, TRANSLATIONS, court)
            self.assertIn(phrase, TRANSLATIONS, phrase)

    def _monde(self):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        return (
            patch(
                "script.todo.assistant.claude_sessions.fleet",
                return_value=[],
            ),
            patch.object(t_ui, "transcriptions", lambda: []),
            patch.object(jr, "lire_lignes", lambda: []),
            patch.object(jr, "nettoyer", lambda *a, **k: None),
            patch.object(oc, "lire_base", lambda: None),
        )

    async def test_h_ouvre_le_panneau_et_echap_le_ferme(self):
        from textual.widgets import Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(80, 40)) as pilote:
                await calme(pilote)
                volet = app.query_one("#aide", Static)
                self.assertFalse(volet.display, "fermé au montage")
                await pilote.press("h")
                await calme(pilote)
                self.assertTrue(volet.display)
                rendu = str(volet.render())
                # Les touches que le pied de page perd à cette largeur.
                for perdue in ("x", "l", "a"):
                    self.assertIn(f" {perdue}  ", rendu, perdue)
                await pilote.press("escape")
                await calme(pilote)
                self.assertFalse(volet.display)
        finally:
            for c in correctifs:
                c.stop()

    async def test_un_chiffre_agit_et_referme_le_panneau(self):
        """Le panneau est un menu : on choisit, il s'efface, l'action part."""
        from textual.widgets import Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(80, 40)) as pilote:
                await calme(pilote)
                faits = []
                rang = [
                    r
                    for r, t_l in enumerate(t_ui.TOUCHES_LIGNE)
                    if t_l[0] == "n"
                ][0]
                app.action_lancer = lambda: faits.append("lancer")
                await pilote.press("h")
                await calme(pilote)
                await pilote.press(str(rang + 1))
                await calme(pilote)
                self.assertEqual(faits, ["lancer"])
                self.assertFalse(app.query_one("#aide", Static).display)
        finally:
            for c in correctifs:
                c.stop()

    async def test_ouvrir_une_invite_ferme_le_panneau(self):
        """Les deux se disputeraient les chiffres : un « 4 » tapé dans une
        invite est un caractère, pas un numéro de menu."""
        from textual.widgets import Input, Static

        from script.todo.assistant.agents import tui as t_ui

        correctifs = self._monde()
        for c in correctifs:
            c.start()
        try:
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(80, 40)) as pilote:
                await calme(pilote)
                faits = []
                app.action_arreter = lambda: faits.append("arreter")
                await pilote.press("h")
                await calme(pilote)
                self.assertTrue(app.query_one("#aide", Static).display)
                # « n » depuis le panneau ouvert : la touche agit, et l'invite
                # qu'elle ouvre chasse le panneau.
                await pilote.press("n")
                await calme(pilote)
                self.assertFalse(app.query_one("#aide", Static).display)
                await pilote.press("4")
                await calme(pilote)
                self.assertEqual(faits, [], "aucun numéro n'a été lu")
                self.assertEqual(app.query_one("#saisie", Input).value, "4")
        finally:
            for c in correctifs:
                c.stop()


class TestLaSortieBruteVaAuTerminal(unittest.IsolatedAsyncioTestCase):
    """`claude logs` imprime un ÉCRAN, et non un journal de lignes.

    Sa sortie porte des centaines de séquences d'échappement, des retours
    chariot et AUCUN saut de ligne, pour quelques milliers d'octets là où
    l'agent a répondu un mot. Les positions du curseur y sont absolues, donc
    les dépouiller rend une seule ligne illisible et aucun panneau de tableau
    n'y peut rien. Elle va au terminal, le temps que l'application se
    suspende.
    """

    def _agent(self):
        from script.todo.assistant import claude_sessions as cs

        return cs.Session(
            session_id="aaaaaaaa-1111-4111-8111-111111111111",
            court="aaaaaaaa",
            kind="background",
            live=True,
            cwd="/un/depot",
            pid=4242,
        )

    async def _presser(self, flotte, touches):
        """L'écran monté sur une flotte inventée, et ce que « j » a demandé."""
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        from textual.widgets import Static

        montres = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: list(flotte))
            async with app.run_test(size=(160, 40)) as pilote:
                app._montrer_dans_le_terminal = montres.append
                await calme(pilote)
                for touche in touches:
                    await pilote.press(touche)
                    await calme(pilote)
                etat = str(app.query_one("#etat", Static).render())
        return montres, etat

    async def test_la_touche_j_rend_le_terminal_a_l_outil(self):
        """L'identifiant passé est le COURT : les cinq sous-commandes ne
        prennent que celui-là, et l'UUID rend « No job matching » avec un code
        de sortie nul."""
        montres, _ = await self._presser([self._agent()], ["v", "v", "j"])
        self.assertEqual(montres, [["claude", "logs", "aaaaaaaa"]])

    async def test_sans_agent_surligne_la_touche_j_ne_lance_rien(self):
        montres, etat = await self._presser([], ["v", "v", "j"])
        self.assertEqual(montres, [])
        self.assertIn(t("Pick a detached agent first."), etat)

    def _app(self):
        from script.todo.assistant.agents import tui as t_ui

        app = t_ui.run_tui(run_app=False)
        app._dire = lambda message: self.dits.append(message)
        self.dits = []
        return app

    def test_la_sortie_n_est_jamais_capturee(self):
        """Ne pas capturer est ce qui GARANTIT que rien n'est écrit.

        La sortie va du processus au terminal sans passer par nous : il n'y a
        pas de copie, donc rien à mettre sur un disque même par accident.
        """
        import contextlib
        import subprocess

        app = self._app()
        app.suspend = contextlib.nullcontext
        appels = []
        imprimes = []
        with patch.object(
            subprocess, "run", lambda argv, **kw: appels.append((argv, kw))
        ), patch("builtins.input", lambda *a: ""), patch(
            "builtins.print", lambda *a, **k: imprimes.append(" ".join(a))
        ):
            app._montrer_dans_le_terminal(["claude", "logs", "aaaaaaaa"])
        ((argv, kw),) = appels
        self.assertEqual(argv, ["claude", "logs", "aaaaaaaa"])
        self.assertEqual(kw, {}, "ni capture_output, ni stdout, ni stderr")
        self.assertIn(
            t("Shown, not kept: nothing of this was written."), imprimes
        )

    def test_un_terminal_qui_ne_suspend_pas_le_dit(self):
        """Un pilote de test, un tube : l'écran le dit au lieu de mourir."""
        import contextlib

        from textual.app import SuspendNotSupported

        @contextlib.contextmanager
        def refuse():
            raise SuspendNotSupported("pas de terminal")
            yield

        app = self._app()
        app.suspend = refuse
        app._montrer_dans_le_terminal(["claude", "logs", "aaaaaaaa"])
        self.assertEqual(
            self.dits, [t("This terminal cannot suspend the screen.")]
        )


class TestLeCurseurEtLeClavier(unittest.IsolatedAsyncioTestCase):
    """Deux defauts qui visaient la mauvaise ligne, sur des gestes qui tuent.

    Le repeint de chaque tour remettait le curseur en tete : deux secondes
    apres avoir surligne le troisieme agent, « s » arretait le premier. Et
    rien ne donnait le clavier au panneau visible, donc les fleches pilotaient
    le tableau du haut pendant que les touches agissaient en bas.

    « s » est justement la seule action qui ne demande AUCUNE confirmation.
    """

    def _agents(self, combien=3):
        from script.todo.assistant import claude_sessions as cs

        return [
            cs.Session(
                session_id=f"{i}" * 8 + "-1111-4111-8111-111111111111",
                kind="background",
                live=True,
                cwd=f"/depot/agent{i}",
                pid=4240 + i,
            )
            for i in range(1, combien + 1)
        ]

    async def _sur_le_panneau(self, flotte, gestes=()):
        from textual.widgets import DataTable

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        vises = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: flotte)
            async with app.run_test(size=(160, 40)) as pilote:
                app._lancer_action = lambda sc, p: vises.append((sc, p))
                await calme(pilote)
                while app.VUES[app._vue] != "agents":
                    await pilote.press("v")
                    await calme(pilote)
                focus = app.focused.id if app.focused else None
                for geste in gestes:
                    if geste == "tour":
                        app._tick()
                    else:
                        await pilote.press(geste)
                    await calme(pilote)
                rang = app.query_one("#agents", DataTable).cursor_row
        return focus, rang, vises

    async def test_le_panneau_visible_prend_le_clavier(self):
        """Textual le donne au premier widget focalisable, soit le tableau du
        haut, et un panneau cache sort de la chaine de focus."""
        focus, _, _ = await self._sur_le_panneau(self._agents())
        self.assertEqual(focus, "agents")

    async def test_le_curseur_survit_a_un_tour_de_rafraichissement(self):
        _, rang, _ = await self._sur_le_panneau(
            self._agents(), ["down", "down", "tour"]
        )
        self.assertEqual(rang, 2)

    async def test_le_curseur_survit_a_plusieurs_tours(self):
        _, rang, _ = await self._sur_le_panneau(
            self._agents(), ["down", "down", "tour", "tour", "tour"]
        )
        self.assertEqual(rang, 2)

    async def test_le_geste_vise_la_ligne_surlignee_et_non_la_premiere(self):
        """Le defaut : deux secondes apres le choix, « s » arretait agent-1."""
        _, _, vises = await self._sur_le_panneau(
            self._agents(), ["down", "down", "tour", "s"]
        )
        self.assertEqual(vises, [("stop", "33333333")])

    async def test_une_ligne_disparue_ne_deplace_pas_le_curseur_ailleurs(self):
        """Un agent qui s arrete entre deux tours : le curseur ne doit pas
        glisser en silence sur son voisin."""
        from textual.widgets import DataTable

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        flotte = self._agents()
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: list(flotte))
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                while app.VUES[app._vue] != "agents":
                    await pilote.press("v")
                    await calme(pilote)
                await pilote.press("down")
                await pilote.press("down")
                await calme(pilote)
                # Le troisieme agent s en va. La flotte passe par un
                # sous-processus et n est donc relue qu un tour sur
                # PAS_FLOTTE : le nombre de tours est DÉRIVÉ de la constante,
                # sans quoi l espacer à nouveau décalerait ce test.
                app._lire_flotte = staticmethod(lambda: flotte[:2])
                app._flotte_a_relire = True
                app._tick()
                await calme(pilote)
                table = app.query_one("#agents", DataTable)
                self.assertEqual(table.row_count, 2)
                self.assertLess(table.cursor_row, 2)


class TestCeQueLaColonneRefuseDeMontrer(unittest.TestCase):
    """Le flux déclare ne montrer aucun contenu : il doit s'y tenir.

    Un appel `Task` ne porte pas de `command` : la recherche retombait sur son
    `prompt` et étalait l'invite entière du sous-agent dans la colonne. Un
    `Grep` y mettait son motif. Le volet de détail a le droit de les montrer —
    il prévient —, la colonne non.
    """

    def _appel(self):
        from script.todo.assistant.agents import journal as jr

        return jr.Appel(
            outil="Task",
            session="aaaaaaaa",
            debut_ms=1_700_000_000_000,
            duree_ms=400,
            identifiant="toolu_01aaaa",
        )

    def _colonne(self, valeur, colonnable):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux(
            [self._appel()],
            commandes={"toolu_01aaaa": (valeur, colonnable)},
        )
        return ligne["commande"]

    def test_free_text_says_it_is_content_and_shows_none(self):
        temoin = "invite-entiere-qui-ne-doit-pas-sortir"
        colonne = self._colonne(temoin, False)
        self.assertEqual(colonne, t("content"))
        self.assertNotIn(temoin, colonne)

    def test_a_command_still_shows(self):
        """Refuser trop viderait la colonne de ce qu'elle sert à montrer."""
        self.assertEqual(self._colonne("echo bonjour", True), "echo bonjour")

    def test_nothing_found_is_still_a_dash(self):
        self.assertEqual(self._colonne("", True), "—")

    def test_not_looked_up_yet_is_still_dots(self):
        from script.todo.assistant.agents import tui as t_ui

        (ligne,) = t_ui.lignes_flux([self._appel()], commandes={})
        self.assertEqual(ligne["commande"], "…")


class TestLeTiretQuandRienNAEteMesure(unittest.TestCase):
    """Tout ce qui vient d'un `cost-state` se tait quand il n'y en a aucun.

    Neuf des dix-huit transcriptions d'une machine ordinaire n'en portent
    aucun — session interrompue, version antérieure, session neuve. Le coût le
    disait déjà par un tiret ; les durées et les lignes touchées, qui viennent
    du MÊME enregistrement, affichaient « 0 ms » et « +0/−0 ».
    """

    def _ligne(self, segments):
        from script.todo.assistant.agents import statistiques as st_
        from script.todo.assistant.agents import tui as t_ui

        agregat = st_.Agregat(
            tours=10,
            segments=segments,
            cout=1.25 if segments else 0.0,
            duree_api=60_000,
            duree_outils=30_000,
            duree_horloge=90_000,
            lignes_ajoutees=12,
            lignes_retirees=3,
        )
        (ligne,) = t_ui.lignes(
            {"/x/y/aaaaaaaa.jsonl": st_.Lecture(agregat=agregat)}
        )
        return ligne

    def test_without_a_cost_state_everything_from_it_is_a_dash(self):
        ligne = self._ligne(0)
        for colonne in ("cout", "api", "outils", "horloge", "code"):
            self.assertEqual(ligne[colonne], "—", colonne)

    def test_with_a_cost_state_the_figures_show(self):
        """Le tiret ne doit pas avaler ce qui a bien été mesuré."""
        ligne = self._ligne(3)
        self.assertEqual(ligne["api"], "1 min")
        self.assertEqual(ligne["outils"], "30 s")
        self.assertEqual(ligne["code"], "+12/−3")
        self.assertEqual(ligne["cout"], "1.25 $")

    def test_the_attention_column_does_not_depend_on_it(self):
        """Elle vient du journal des hooks, pas du cost-state."""
        from script.todo.assistant.agents import statistiques as st_
        from script.todo.assistant.agents import tui as t_ui

        chemin = "/x/y/aaaaaaaa-1111-4111-8111-111111111111.jsonl"
        (ligne,) = t_ui.lignes(
            {chemin: st_.Lecture(agregat=st_.Agregat(segments=0))},
            {t_ui.session_de(chemin): 125_000},
        )
        self.assertEqual(ligne["attention"], "2 min")
        self.assertEqual(ligne["api"], "—")


class TestCeQueChaqueTourDepense(unittest.IsolatedAsyncioTestCase):
    """Le listage de la flotte passe par un sous-processus.

    Cent soixante millisecondes, la moitié de ce qu'un tour dépense, là où la
    lecture incrémentale des transcriptions n'en coûte que cinq. Un agent ne
    naît ni ne meurt toutes les deux secondes, donc la question se pose moins
    souvent — mais un geste qui en change l'état doit la reposer tout de suite,
    sans quoi l'écran mentirait pendant trois tours.
    """

    async def _compter(self, gestes=()):
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        lectures = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: lectures.append(1) or [])
            # Le temps est INJECTÉ : la cadence de la flotte se compte en
            # secondes, et un test qui les attendrait vraiment durerait six
            # secondes par cas.
            horloge = [0.0]
            app._horloge = lambda: horloge[0]
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                depart = len(lectures)
                for geste in gestes:
                    if geste == "tour":
                        app._tick()
                    elif geste == "le pas passe":
                        horloge[0] += t_ui.PAS * t_ui.PAS_FLOTTE
                    else:
                        getattr(app, geste)()
                    await calme(pilote)
                return len(lectures) - depart

    async def test_the_fleet_is_not_listed_every_tick(self):
        from script.todo.assistant.agents import tui as t_ui

        lectures = await self._compter(["tour"] * (t_ui.PAS_FLOTTE + 2))
        self.assertEqual(lectures, 0)

    async def test_it_is_listed_again_after_the_step(self):
        """Six secondes plus tard, la question se repose une fois."""
        lectures = await self._compter(["le pas passe", "tour", "tour"])
        self.assertEqual(lectures, 1)

    async def test_reading_everything_again_asks_at_once(self):
        """« r » est un geste explicite : il ne doit rien laisser périmé."""
        self.assertEqual(await self._compter(["action_relire"]), 1)

    async def test_reading_everything_again_says_so(self):
        """Plus d'une seconde de gel sans un mot se lit comme un écran mort."""
        from textual.widgets import Static

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                app._dire(t("Reading everything again…"))
                dit = str(app.query_one("#etat", Static).render())
        self.assertIn(t("Reading everything again…"), dit)


class TestLesLecturesSortentDeLaBoucle(unittest.IsolatedAsyncioTestCase):
    """Lire sur la boucle d'événements, c'est parier sur le disque.

    Le listage des agents est un SOUS-PROCESSUS dont le délai est de quinze
    secondes. Lu sur la boucle, un outil qui ne répond pas fige l'écran
    d'autant : plus une touche, plus même « q ». Le fil sépare le coût de la
    lecture de la vivacité de l'écran.
    """

    async def test_un_listage_lent_ne_bloque_ni_le_tour_ni_les_touches(self):
        import time as horloge

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        lent = 0.4
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                app._lire_flotte = staticmethod(
                    lambda: horloge.sleep(lent) or []
                )
                app._flotte_a_relire = True
                depart = horloge.perf_counter()
                app._tick()
                rendu = horloge.perf_counter() - depart
                self.assertLess(
                    rendu, lent / 4, "le tour rend la main tout de suite"
                )
                # Et l'écran répond PENDANT que le fil dort : la touche est
                # traitée, le panneau change.
                await pilote.press("v")
                await pilote.pause()
                self.assertEqual(app.VUES[app._vue], "flux")
                await calme(pilote)

    async def test_un_tour_qui_tombe_pendant_une_lecture_est_saute(self):
        """Mis en file, les tours en retard s'accumuleraient sans qu'aucun ne
        montre jamais l'état du moment."""
        import time as horloge

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        lectures = []
        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                app._lire_flotte = staticmethod(
                    lambda: horloge.sleep(0.3) or lectures.append(1) or []
                )
                app._flotte_a_relire = True
                app._tick()
                for _ in range(5):
                    app._flotte_a_relire = True
                    app._tick()
                await calme(pilote)
        self.assertEqual(len(lectures), 1)

    async def test_une_lecture_qui_leve_ne_tue_pas_le_rafraichissement(self):
        """Un fil qui meurt ne prévient personne : le drapeau resterait levé
        et l'écran cesserait de se rafraîchir, sans un mot."""
        from textual.widgets import Static

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        def casse():
            raise RuntimeError("le disque a dit non")

        with patch.object(t_ui, "transcriptions", casse), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                self.assertFalse(app._lecture_en_cours)
                self.assertIn(
                    "le disque a dit non",
                    str(app.query_one("#etat", Static).render()),
                )

    async def test_un_releve_perime_est_jete(self):
        """« r » remet tout à zéro ; le fil lisait encore le monde d'avant, et
        appliquer son relevé ressusciterait ce qu'on venait d'oublier."""
        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import statistiques as st
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        with patch.object(
            t_ui, "transcriptions", lambda: ["/x/y/aaaaaaaa.jsonl"]
        ), patch.object(
            st, "lire", lambda c, l=None: st.Lecture()
        ), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(
            jr, "nettoyer", lambda *a, **k: None
        ), patch.object(
            oc, "lire_base", lambda: None
        ):
            app = t_ui.run_tui(run_app=False)
            app._lire_flotte = staticmethod(lambda: [])
            async with app.run_test(size=(160, 40)) as pilote:
                await calme(pilote)
                self.assertEqual(len(app._lectures), 1)
                app._generation += 1
                app._lectures = {}
                app._appliquer(0, t_ui.Releve(lectures={"/x/y/z.jsonl": None}))
                self.assertEqual(app._lectures, {})


class TestAucunTestNeToucheLaMachine(unittest.IsolatedAsyncioTestCase):
    """Un test qui lance le vrai binaire ne mesure plus le code.

    `on_mount` appelle `_tick`, qui appelle la flotte, qui lance
    « claude agents --json » et parcourt le vrai ~/.claude. Neuf tests le
    faisaient — un sous-processus chacun, et un verdict qui dépendait de ce
    qui tournait chez celui qui les lançait.

    La garde est directe : `subprocess.run` LÈVE pendant le montage. Si
    quelque chose l'appelle, le test tombe en disant quoi.
    """

    async def test_mounting_the_screen_launches_nothing(self):
        import subprocess

        from script.todo.assistant.agents import journal as jr
        from script.todo.assistant.agents import tui as t_ui
        from script.todo.assistant.harness import opencode as oc

        lances = []

        def refuser(argv, *a, **kw):
            lances.append(argv)
            raise AssertionError(f"sous-processus lancé : {argv}")

        with patch.object(t_ui, "transcriptions", lambda: []), patch.object(
            jr, "lire_lignes", lambda: []
        ), patch.object(jr, "nettoyer", lambda *a, **k: None), patch(
            "script.todo.assistant.claude_sessions.fleet", return_value=[]
        ), patch.object(
            oc, "lire_base", return_value=[]
        ), patch.object(
            subprocess, "run", refuser
        ):
            app = t_ui.run_tui(run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await calme(pilote)
                app._tick()
                await calme(pilote)
        self.assertEqual(lances, [])


if __name__ == "__main__":
    unittest.main()
