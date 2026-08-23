#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Qui dépend de qui, et ce qu'on peut retirer sans casser.

La question posée au palier 17 → 18 — « puis-je retirer web_responsive »
— a demandé une requête écrite à la main. L'outil y répond, et la réponse
qui compte n'est pas « deux modules en dépendent » mais « aucun de ceux
qui en dépendent n'est installé ».
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import check_module_dependency as dep  # noqa: E402
from script.analyse import check_module_dependency_tui as tui  # noqa: E402


def base(modules, depend=None):
    """Un rapport minimal. `modules` : {nom: état}."""
    recensement = {
        nom: (etat, f"Résumé {nom}", False, "TechnoLibre")
        for nom, etat in modules.items()
    }
    depend = (
        {nom: sorted(depend.get(nom, [])) for nom in recensement}
        if depend
        else {nom: [] for nom in recensement}
    )
    return {
        "database": "essai",
        "version": "18.0",
        "modules": recensement,
        "depends": depend,
        "dependents": dep.reverse(depend),
        "broken": dep.broken(recensement, depend),
    }


class TestReverse(unittest.TestCase):
    def test_it_inverts_the_arrows(self):
        self.assertEqual(
            dep.reverse({"zebre": ["alpha"], "alpha": []}),
            {"alpha": ["zebre"], "zebre": []},
        )

    def test_a_module_cited_but_absent_still_gets_an_entry(self):
        # C'est le cas qu'on cherche : quelqu'un dépend d'un module que la
        # base ne connaît pas. L'omettre le rendrait invisible.
        self.assertEqual(dep.reverse({"a": ["fantome"]})["fantome"], ["a"])

    def test_a_duplicate_dependency_is_counted_once(self):
        self.assertEqual(dep.reverse({"a": ["b", "b"]})["b"], ["a"])


class TestClosure(unittest.TestCase):
    def test_it_walks_through(self):
        graphe = {"zebre": ["milieu"], "milieu": ["alpha"], "alpha": []}
        self.assertEqual(dep.closure("zebre", graphe), ["alpha", "milieu"])

    def test_it_excludes_itself(self):
        self.assertNotIn("a", dep.closure("a", {"a": ["b"], "b": ["a"]}))

    def test_a_cycle_terminates(self):
        # Un cycle ne devrait pas exister en base ; s'il y en a un, on veut
        # un résultat, pas une boucle sans fin.
        self.assertEqual(
            dep.closure("a", {"a": ["b"], "b": ["c"], "c": ["a"]}),
            ["b", "c"],
        )

    def test_a_chain_longer_than_the_bound_is_cut_not_hung(self):
        chaine = {
            f"n{i}": [f"n{i + 1}"] for i in range(dep.PROFONDEUR_MAX + 8)
        }
        atteints = dep.closure("n0", chaine)
        self.assertEqual(len(atteints), dep.PROFONDEUR_MAX)

    def test_an_unknown_module_reaches_nothing(self):
        self.assertEqual(dep.closure("absent", {"a": ["b"]}), [])


class TestBroken(unittest.TestCase):
    def test_installed_on_an_uninstalled_dependency(self):
        rapport = base(
            {"chef": "installed", "socle": "uninstalled"},
            {"chef": ["socle"]},
        )
        self.assertEqual(rapport["broken"], [("chef", "socle", "uninstalled")])

    def test_installed_on_a_module_the_base_never_heard_of(self):
        rapport = base({"chef": "installed"}, {"chef": ["fantome"]})
        self.assertEqual(rapport["broken"], [("chef", "fantome", "unknown")])

    def test_an_uninstalled_module_may_depend_on_anything(self):
        # Il ne tourne pas : ses dépendances ne cassent rien.
        rapport = base(
            {"chef": "uninstalled", "socle": "uninstalled"},
            {"chef": ["socle"]},
        )
        self.assertEqual(rapport["broken"], [])

    def test_to_upgrade_counts_as_in_place(self):
        # Le module est chargé, il sera seulement rejoué.
        rapport = base(
            {"chef": "installed", "socle": "to upgrade"},
            {"chef": ["socle"]},
        )
        self.assertEqual(rapport["broken"], [])

    def test_to_install_is_not_in_place_yet(self):
        rapport = base(
            {"chef": "installed", "socle": "to install"},
            {"chef": ["socle"]},
        )
        self.assertEqual(rapport["broken"], [("chef", "socle", "to install")])


class TestCounts(unittest.TestCase):
    def rapport(self):
        return base(
            {
                "web_responsive": "installed",
                "erplibre_base": "uninstalled",
                "web_responsive_company": "uninstalled",
                "mail": "installed",
            },
            {
                "web_responsive": ["mail"],
                "erplibre_base": ["web_responsive"],
                "web_responsive_company": ["web_responsive"],
            },
        )

    def test_the_third_number_counts_only_what_is_in_place(self):
        # Le cas réel : deux dépendants déclarés, aucun installé. Ne
        # montrer que « 2 » ferait renoncer à un retrait sans danger.
        self.assertEqual(
            dep.counts(self.rapport(), "web_responsive"), (1, 2, 0)
        )

    def test_an_installed_dependent_is_counted(self):
        rapport = self.rapport()
        rapport["modules"]["erplibre_base"] = ("installed", "", False, "")
        self.assertEqual(dep.counts(rapport, "web_responsive")[2], 1)

    def test_a_module_nobody_needs(self):
        self.assertEqual(
            dep.counts(self.rapport(), "erplibre_base"), (1, 0, 0)
        )


class TestRows(unittest.TestCase):
    def rapport(self):
        return base(
            {
                "zebre": "installed",
                "alpha": "uninstalled",
                "milieu": "installed",
            },
            {"zebre": ["alpha"]},
        )

    def test_they_come_out_sorted_by_name(self):
        # Les noms sont posés dans un ordre qui CONTREDIT l'alphabet :
        # sans tri, la liste sortirait zebre, alpha, milieu.
        self.assertEqual(
            [row["name"] for row in dep.rows(self.rapport())],
            ["alpha", "milieu", "zebre"],
        )

    def test_the_installed_filter_keeps_only_those(self):
        self.assertEqual(
            [r["name"] for r in dep.rows(self.rapport(), "installed")],
            ["milieu", "zebre"],
        )

    def test_the_absent_filter_is_the_complement(self):
        self.assertEqual(
            [r["name"] for r in dep.rows(self.rapport(), "absent")], ["alpha"]
        )

    def test_the_broken_filter_keeps_the_guilty_only(self):
        # zebre est installé et dépend d'alpha qui ne l'est pas.
        self.assertEqual(
            [r["name"] for r in dep.rows(self.rapport(), "broken")], ["zebre"]
        )

    def test_the_detail_column_shows_both_counts(self):
        row = [r for r in dep.rows(self.rapport()) if r["name"] == "alpha"][0]
        self.assertEqual(row["detail"], "0↓ 1/1↑")

    def test_every_filter_is_understood(self):
        # Un filtre inconnu ne doit pas vider la liste en silence.
        for filtre in dep.FILTRES:
            dep.rows(self.rapport(), filtre)


class TestListing(unittest.TestCase):
    def rapport(self):
        return base(
            {"haut": "installed", "milieu": "installed", "bas": "installed"},
            {"haut": ["milieu"], "milieu": ["bas"]},
        )

    def test_depends_is_direct_only(self):
        self.assertEqual(
            dep.listing(self.rapport(), "haut", "depends"), ["milieu"]
        )

    def test_pulls_goes_all_the_way_down(self):
        self.assertEqual(
            dep.listing(self.rapport(), "haut", "pulls"), ["bas", "milieu"]
        )

    def test_dependents_is_direct_only(self):
        self.assertEqual(
            dep.listing(self.rapport(), "bas", "dependents"), ["milieu"]
        )

    def test_falls_goes_all_the_way_up(self):
        self.assertEqual(
            dep.listing(self.rapport(), "bas", "falls"), ["haut", "milieu"]
        )

    def test_every_mode_has_a_title(self):
        for mode in dep.DETAILS:
            self.assertIn(mode, dep.TITRE_DETAIL)


class TestPaneText(unittest.TestCase):
    def rapport(self):
        return base(
            {"web_responsive": "installed", "compagnon": "uninstalled"},
            {"compagnon": ["web_responsive"]},
        )

    def test_it_answers_the_removal_question_in_words(self):
        # Deux chiffres à comparer soi-même, ce n'est pas une réponse.
        texte = dep.pane_text(self.rapport(), "web_responsive")
        self.assertIn("rien d'installé n'en dépend", texte)

    def test_it_stays_silent_when_something_does_depend_on_it(self):
        rapport = self.rapport()
        rapport["modules"]["compagnon"] = ("installed", "", False, "")
        self.assertNotIn(
            "rien d'installé n'en dépend",
            dep.pane_text(rapport, "web_responsive"),
        )

    def test_an_absent_dependent_is_marked_as_such(self):
        texte = dep.pane_text(
            self.rapport(), "web_responsive", mode="dependents"
        )
        self.assertIn("compagnon", texte)
        self.assertIn("absent", texte)

    def test_an_unknown_module_says_so(self):
        self.assertIn("inconnu", dep.pane_text(self.rapport(), "jamais_vu"))

    def test_nothing_selected_is_not_a_crash(self):
        self.assertTrue(dep.pane_text(self.rapport(), None))

    def test_an_empty_listing_says_nothing_rather_than_showing_blank(self):
        texte = dep.pane_text(self.rapport(), "web_responsive", mode="depends")
        self.assertIn("rien", texte.lower())

    def test_the_limit_announces_what_it_cut(self):
        rapport = base(
            dict(
                {"chef": "installed"},
                **{f"d{i}": "installed" for i in range(9)},
            ),
            {"chef": [f"d{i}" for i in range(9)]},
        )
        texte = dep.pane_text(rapport, "chef", mode="depends", limit=4)
        self.assertIn("5", texte)


class TestRenderText(unittest.TestCase):
    def rapport(self):
        return base({f"m{i:02d}": "installed" for i in range(30)})

    def test_without_a_cap_everything_is_there(self):
        lignes = dep.render_text(self.rapport())
        self.assertEqual(sum(1 for x in lignes if x.startswith("✅")), 30)

    def test_the_cap_bounds_the_module_list(self):
        # Sur une vraie base c'est 3035 modules et 6046 lignes : sans
        # borne, le repli du menu est une seconde panne.
        lignes = dep.render_text(self.rapport(), cap=5)
        self.assertEqual(sum(1 for x in lignes if x.startswith("✅")), 5)

    def test_the_cap_says_how_many_it_hid(self):
        self.assertTrue(
            any("25" in x for x in dep.render_text(self.rapport(), cap=5))
        )

    def test_an_unreadable_database_says_so(self):
        lignes = dep.render_text({"database": "x", "unavailable": True})
        self.assertEqual(len(lignes), 1)
        self.assertIn("x", lignes[0])


class TestSurvey(unittest.TestCase):
    def setUp(self):
        from script.analyse import check_module_package as package

        self.package = package
        self.vrai = (package.census, package.dependencies, package.db_version)

    def tearDown(self):
        (
            self.package.census,
            self.package.dependencies,
            self.package.db_version,
        ) = self.vrai

    def poser(self, recensement, depend):
        self.package.census = lambda d: recensement
        self.package.dependencies = lambda d: depend
        self.package.db_version = lambda d: "18.0"

    def test_a_module_without_dependency_still_exists_in_the_graph(self):
        # Sans cela, `closure` et l'écran le traitent comme inconnu.
        self.poser({"seul": ("installed", "", False, "")}, {})
        self.assertEqual(dep.survey("x")["depends"], {"seul": []})

    def test_an_unreadable_base_is_not_an_empty_one(self):
        self.poser(None, {})
        self.assertTrue(dep.survey("x").get("unavailable"))

    def test_an_empty_base_is_readable(self):
        self.poser({}, {})
        self.assertFalse(dep.survey("x").get("unavailable"))

    def test_it_reads_the_base_once_for_both_views(self):
        appels = []
        self.poser({"a": ("installed", "", False, "")}, {})
        vrai = self.package.census
        self.package.census = lambda d: (appels.append(d), vrai(d))[1]
        dep.survey("x")
        self.assertEqual(appels, ["x"])


class TestTuiPureParts(unittest.TestCase):
    def test_the_mode_cycles_through_all_of_them_and_returns(self):
        vus, mode = [], None
        for _ in range(len(dep.DETAILS) + 1):
            mode = tui.next_mode(mode)
            vus.append(mode)
        self.assertEqual(vus, list(dep.DETAILS) + [None])

    def test_an_unknown_mode_restarts_the_cycle(self):
        self.assertEqual(tui.next_mode("n'importe quoi"), dep.DETAILS[0])

    def test_the_filter_cycles(self):
        self.assertEqual(tui.next_filter(dep.FILTRES[-1]), dep.FILTRES[0])

    def test_the_cursor_out_of_range_is_not_a_crash(self):
        # La table garde son curseur quand la liste raccourcit.
        self.assertIsNone(tui.current_name([{"name": "a"}], 7))
        self.assertIsNone(tui.current_name([], 0))
        self.assertIsNone(tui.current_name([{"name": "a"}], None))

    def test_the_cursor_follows_the_module_across_a_filter(self):
        lst = [{"name": "alpha"}, {"name": "zebre"}]
        self.assertEqual(tui.cursor_for(lst, "zebre"), 1)

    def test_a_module_filtered_away_loses_the_cursor(self):
        self.assertIsNone(tui.cursor_for([{"name": "alpha"}], "zebre"))

    def test_the_search_ignores_the_case(self):
        lst = [{"name": "Web_Responsive"}, {"name": "mail"}]
        self.assertEqual(len(tui.matching(lst, "web")), 1)

    def test_an_empty_search_keeps_everything(self):
        lst = [{"name": "a"}, {"name": "b"}]
        self.assertIs(tui.matching(lst, ""), lst)

    def test_the_subtitle_names_the_three_states(self):
        texte = tui.subtitle("depends", "installed", "web")
        self.assertIn("directement", texte)
        self.assertIn("installés", texte)
        self.assertIn("web", texte)


class FausseTable:
    """Le contrat de DataTable, réduit à ce que `populate` en utilise."""

    def __init__(self):
        self.lignes = []
        self.curseur = None

    def clear(self):
        self.lignes = []

    def add_row(self, *cellules):
        self.lignes.append(cellules)

    def move_cursor(self, row=None):
        self.curseur = row


class TestPopulate(unittest.TestCase):
    def test_it_fills_and_keeps_the_cursor_on_the_module(self):
        table = FausseTable()
        lst = [
            {"name": "alpha", "label": "✅ alpha", "detail": "0↓ 0/0↑"},
            {"name": "zebre", "label": "✅ zebre", "detail": "1↓ 0/0↑"},
        ]
        self.assertEqual(tui.populate(table, lst, "zebre"), 1)
        self.assertEqual(len(table.lignes), 2)
        self.assertEqual(table.curseur, 1)

    def test_it_clears_before_refilling(self):
        table = FausseTable()
        table.add_row("vieux")
        tui.populate(table, [{"name": "a", "label": "a", "detail": ""}])
        self.assertEqual(len(table.lignes), 1)

    def test_a_vanished_module_leaves_the_cursor_alone(self):
        table = FausseTable()
        tui.populate(
            table, [{"name": "a", "label": "a", "detail": ""}], "parti"
        )
        self.assertIsNone(table.curseur)


class FauxChamp:
    """Le contrat d'Input, réduit à ce que `hide_find` en utilise."""

    def __init__(self):
        self.value = "web"
        self.classes = {"visible"}

    def remove_class(self, nom):
        self.classes.discard(nom)

    def has_class(self, nom):
        return nom in self.classes


class FausseTableFocus(FausseTable):
    def __init__(self):
        super().__init__()
        self.focalisee = False

    def focus(self):
        self.focalisee = True


class TestHideFind(unittest.TestCase):
    def test_it_hands_the_keyboard_back_to_the_list(self):
        # Le geste qui compte : sans lui, Textual laisse le clavier au
        # champ de recherche et plus aucune touche n'agit.
        champ, table = FauxChamp(), FausseTableFocus()
        tui.hide_find(champ, table)
        self.assertTrue(table.focalisee)

    def test_it_hides_the_field(self):
        champ, table = FauxChamp(), FausseTableFocus()
        tui.hide_find(champ, table)
        self.assertFalse(champ.has_class("visible"))

    def test_it_leaves_the_text_alone(self):
        # Effacer ici ferait deux chemins pour le même état : l'appelant
        # vide le champ, et c'est CE geste qui redéclenche le filtrage.
        champ, table = FauxChamp(), FausseTableFocus()
        tui.hide_find(champ, table)
        self.assertEqual(champ.value, "web")


class TestTheScreenRefusesWhenItCannot(unittest.TestCase):
    def test_an_unreadable_report_opens_nothing(self):
        self.assertFalse(tui.run_tui({"unavailable": True}))

    def test_an_empty_base_opens_nothing(self):
        self.assertFalse(tui.run_tui({"modules": {}}))

    def test_nothing_at_all_opens_nothing(self):
        self.assertFalse(tui.run_tui(None))


def textual_present():
    try:
        import textual  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(textual_present(), "textual absent")
class TestTheScreenActuallyDrives(unittest.TestCase):
    """Conduire l'écran, touche par touche.

    Les fonctions pures étaient toutes vertes et l'écran, lui, ne
    répondait pas : le champ de recherche caché prenait le focus au
    démarrage — « display: none » ne retire pas un widget du parcours du
    clavier — donc « d » tapait dans une boîte invisible. Seul un test
    qui PRESSE les touches pouvait le voir.
    """

    def rapport(self):
        return base(
            {
                "web_responsive": "installed",
                "mail": "installed",
                "compagnon": "uninstalled",
                "casse": "installed",
                "zebre": "installed",
            },
            {
                "web_responsive": ["mail"],
                "compagnon": ["web_responsive"],
                "casse": ["fantome"],
                "zebre": ["web_responsive"],
            },
        )

    def conduire(self, scenario):
        import asyncio

        app = tui.build_app(self.rapport())

        async def piloter():
            async with app.run_test() as pilote:
                await scenario(app, pilote)

        asyncio.run(piloter())
        return app

    def test_the_keyboard_starts_on_the_list_not_in_the_search(self):
        vus = []

        async def scenario(app, pilote):
            vus.append(type(app.focused).__name__)

        self.conduire(scenario)
        self.assertEqual(vus, ["DataTable"])

    def test_pressing_d_walks_every_relation_and_comes_back(self):
        vus = []

        async def scenario(app, pilote):
            for _ in range(len(dep.DETAILS) + 1):
                await pilote.press("d")
                vus.append(app.mode)

        self.conduire(scenario)
        self.assertEqual(vus, list(dep.DETAILS) + [None])

    def test_pressing_f_narrows_the_list(self):
        vus = {}

        async def scenario(app, pilote):
            table = app.query_one("#left")
            for _ in range(len(dep.FILTRES)):
                await pilote.press("f")
                vus[app.filtre] = table.row_count

        self.conduire(scenario)
        self.assertEqual(vus["all"], 5)
        self.assertEqual(vus["installed"], 4)
        self.assertEqual(vus["absent"], 1)
        self.assertEqual(vus["broken"], 1)

    def test_the_search_filters_then_gives_the_keyboard_back(self):
        vus = {}

        async def scenario(app, pilote):
            await pilote.press("slash")
            vus["focus_ouvert"] = type(app.focused).__name__
            for lettre in "web":
                await pilote.press(lettre)
            await pilote.pause()
            vus["lignes"] = app.query_one("#left").row_count
            await pilote.press("enter")
            vus["focus_rendu"] = type(app.focused).__name__
            await pilote.press("d")
            vus["mode"] = app.mode

        self.conduire(scenario)
        self.assertEqual(vus["focus_ouvert"], "Input")
        self.assertEqual(vus["lignes"], 1)
        self.assertEqual(vus["focus_rendu"], "DataTable")
        # « d » doit remarcher une fois la recherche finie : sans cela on
        # ne peut plus rien faire après avoir cherché.
        self.assertEqual(vus["mode"], dep.DETAILS[0])

    def test_escape_closes_the_search_before_it_closes_the_screen(self):
        vus = {}

        async def scenario(app, pilote):
            await pilote.press("slash")
            for lettre in "web":
                await pilote.press(lettre)
            await pilote.pause()
            await pilote.press("escape")
            await pilote.pause()
            vus["motif"] = app.motif
            vus["lignes"] = app.query_one("#left").row_count
            vus["vivant"] = app.is_running
            # La tabulation ne doit pas non plus retomber dans le champ
            # refermé : « display: none » ne l'en retire pas, seul
            # can_focus le fait.
            await pilote.press("tab")
            vus["apres_tab"] = type(app.focused).__name__
            await pilote.press("escape")
            await pilote.pause()
            vus["apres_second_echap"] = app.is_running

        self.conduire(scenario)
        self.assertNotEqual(vus["apres_tab"], "Input")
        # …et le second échap, lui, ferme bien l'écran.
        self.assertFalse(vus["apres_second_echap"])
        # Renoncer à une recherche ne doit pas fermer l'écran : on a
        # parfois filtré trois mille modules pour arriver là.
        self.assertTrue(vus["vivant"])
        self.assertEqual(vus["motif"], "")
        self.assertEqual(vus["lignes"], 5)


if __name__ == "__main__":
    unittest.main()
