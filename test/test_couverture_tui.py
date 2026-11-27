#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de couverture : l'arbre, la source annotée, l'historique et les
touches qui lancent un passage, sur un coverage.json et un historique
fabriqués dans un cache temporaire.

Aucune mesure n'est lancée : subprocess.run, App.suspend et l'ouverture du
navigateur sont remplacés.
"""

import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.argv = ["todo.py"]
sys.path.insert(0, "test")
from async_case import AsyncCase  # noqa: E402

from script.test import couverture  # noqa: E402
from script.test import couverture_tui as ct  # noqa: E402
from script.todo import todo as todo_module  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

# Un nom de fichier à crochets : le balisage rich le prendrait pour une
# balise, le texte brut le garde.
FICHIER_CROCHETS = "script/zorglub/[crochet].py"
SOURCE_CROCHETS = (
    "def f(x):\n"
    "    if x:\n"
    "        return '[bold]oui[/bold]'\n"
    "    return '[red]non'\n"
)


def resume(executees, manquantes, branches=0, branches_couvertes=0):
    total = len(executees) + len(manquantes)
    return {
        "covered_lines": len(executees),
        "num_statements": total,
        "missing_lines": len(manquantes),
        "excluded_lines": 0,
        "num_branches": branches,
        "covered_branches": branches_couvertes,
        "percent_covered": 100.0
        * (len(executees) + branches_couvertes)
        / (total + branches),
    }


def fichier(executees, manquantes, branches_manquantes=(), branches=0):
    couvertes = branches - len(branches_manquantes)
    return {
        "executed_lines": list(executees),
        "missing_lines": list(manquantes),
        "excluded_lines": [],
        "missing_branches": [list(b) for b in branches_manquantes],
        "summary": resume(executees, manquantes, branches, couvertes),
    }


RAPPORT = {
    "files": {
        FICHIER_CROCHETS: fichier(
            [1, 2, 3], [4], branches_manquantes=[(2, 4)], branches=2
        ),
        "script/zorglub/brique.py": fichier([1, 2, 3, 4], []),
        "script/quokka/pivot.py": fichier([1], [2, 3, 4, 5]),
    },
    "totals": {"percent_covered": 61.54},
}


def ligne_historique(pct, complet=True, incomplets=()):
    return {
        "date": "2001-02-03T04:05:06+00:00",
        "commit": "abcdef012345",
        "branche": "essai",
        "jeu": "erplibre",
        "complet": complet,
        "incomplets": list(incomplets),
        "duree_s": 1.0,
        "total": {"pourcentage": pct},
        "dossiers": {},
    }


HISTORIQUE = [
    ligne_historique(60.0),
    ligne_historique(40.0, complet=False),
    ligne_historique(62.5, incomplets=["test/test_x.py"]),
]


class CacheFictif:
    """Un XDG_CACHE_HOME et une racine de dépôt temporaires ; le jeu
    erplibre y porte RAPPORT et HISTORIQUE, le jeu odoo rien."""

    def preparer(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        cache = os.path.join(tmp.name, "cache")
        racine = os.path.join(tmp.name, "depot")
        for patch in (
            mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}),
            mock.patch.object(
                couverture, "CACHE", os.path.join(cache, "erplibre", "cov")
            ),
            mock.patch.object(ct, "RACINE", racine),
        ):
            patch.start()
            test.addCleanup(patch.stop)
        os.makedirs(couverture.dossier("erplibre"))
        with open(couverture.chemin_json("erplibre"), "w") as fh:
            json.dump(RAPPORT, fh)
        with open(couverture.chemin_historique("erplibre"), "w") as fh:
            for ligne in HISTORIQUE:
                fh.write(json.dumps(ligne) + "\n")
        sources = {
            FICHIER_CROCHETS: SOURCE_CROCHETS,
            "script/zorglub/brique.py": "a = 1\nb = 2\nc = 3\nd = 4\n",
            "script/quokka/pivot.py": "u = 1\nv = 2\nw = 3\nx = 4\ny = 5\n",
            "script/test/run_unit_test.sh": "",
        }
        for chemin, texte in sources.items():
            complet = os.path.join(racine, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w") as fh:
                fh.write(texte)
        return racine


class TestLArbre(unittest.TestCase):
    def test_directories_sum_their_files(self):
        racine = ct.construire(RAPPORT)
        self.assertEqual(sorted(racine.enfants), ["script"])
        zorglub = racine.enfants["script"].enfants["zorglub"]
        self.assertEqual(zorglub.lignes, 8)
        self.assertEqual(zorglub.couvertes, 7)
        self.assertEqual(zorglub.branches, 2)
        self.assertEqual(zorglub.branches_couvertes, 1)
        self.assertAlmostEqual(zorglub.pourcentage, 80.0)
        self.assertEqual(racine.nombre_de_fichiers(), 3)

    def test_the_filter_keeps_matching_paths_only(self):
        racine = ct.construire(RAPPORT, "QUOKKA")
        script = racine.enfants["script"]
        self.assertEqual(sorted(script.enfants), ["quokka"])
        self.assertEqual(racine.nombre_de_fichiers(), 1)

    def test_a_filter_matching_nothing_gives_an_empty_tree(self):
        self.assertEqual(ct.construire(RAPPORT, "rien-de-tel").enfants, {})

    def test_the_three_sorts(self):
        zorglub = ct.construire(RAPPORT).enfants["script"].enfants
        fichiers = list(zorglub["zorglub"].enfants.values()) + list(
            zorglub["quokka"].enfants.values()
        )
        noms = [n.nom for n in ct.trier(fichiers, "pourcentage")]
        self.assertEqual(noms, ["pivot.py", "[crochet].py", "brique.py"])
        noms = [n.nom for n in ct.trier(fichiers, "manquantes")]
        self.assertEqual(noms, ["pivot.py", "[crochet].py", "brique.py"])
        noms = [n.nom for n in ct.trier(fichiers, "nom")]
        self.assertEqual(noms, ["[crochet].py", "brique.py", "pivot.py"])

    def test_directories_come_before_files(self):
        racine = ct.construire(
            {
                "files": {
                    "a.py": fichier([1], [2]),
                    "z/b.py": fichier([1], []),
                }
            }
        )
        ordre = [n.nom for n in ct.trier(racine.enfants.values(), "nom")]
        self.assertEqual(ordre, ["z", "a.py"])

    def test_colour_thresholds(self):
        self.assertEqual(ct.couleur(80.0), "green")
        self.assertEqual(ct.couleur(79.9), "yellow")
        self.assertEqual(ct.couleur(50.0), "yellow")
        self.assertEqual(ct.couleur(49.9), "red")

    def test_the_label_is_text_not_markup(self):
        noeud = ct.construire(RAPPORT).enfants["script"].enfants["zorglub"]
        etiquette = ct.etiquette(noeud.enfants["[crochet].py"])
        self.assertIn("[crochet].py", etiquette.plain)


class TestLaSourceAnnotee(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(ct.plages([9, 3, 4, 5, 11]), "3-5, 9, 11")
        self.assertEqual(ct.plages([]), "")

    def test_each_kind_of_line(self):
        sortes = ct.sorte_des_lignes(RAPPORT["files"][FICHIER_CROCHETS])
        self.assertEqual(sortes[1], ct.EXECUTEE)
        self.assertEqual(sortes[2], ct.PARTIELLE)
        self.assertEqual(sortes[3], ct.EXECUTEE)
        self.assertEqual(sortes[4], ct.MANQUANTE)

    def test_brackets_survive_and_missing_lines_are_named(self):
        texte = ct.annoter(
            SOURCE_CROCHETS, RAPPORT["files"][FICHIER_CROCHETS], "x.py"
        )
        self.assertIn("'[bold]oui[/bold]'", texte.plain)
        self.assertIn("'[red]non'", texte.plain)
        self.assertIn("1 ligne(s) manquante(s) : 4", texte.plain)
        self.assertIn("4 ✗     return", texte.plain)
        self.assertIn("2 ◐     if x:", texte.plain)


class TestLHistorique(unittest.TestCase):
    def test_the_curve_keeps_complete_runs_only(self):
        self.assertEqual(ct.serie(HISTORIQUE), [60.0, 62.5])

    def test_partial_runs_are_greyed_and_named(self):
        texte = ct.texte_passages(HISTORIQUE)
        lignes = texte.plain.splitlines()
        self.assertEqual(len(lignes), 3)
        self.assertIn("62.50 %  complet, 1 tué(s)", lignes[0])
        self.assertIn("partiel", lignes[1])
        grises = [
            texte.plain[s.start : s.end]
            for s in texte.spans
            if s.style == "dim"
        ]
        self.assertTrue(any("40.00" in g for g in grises))
        self.assertFalse(any("60.00" in g for g in grises))

    def test_the_delta_line(self):
        self.assertIn("+2.50 pt", ct.texte_ecart(HISTORIQUE[-1], 2.5).plain)
        self.assertIn(
            "passage partiel",
            ct.texte_ecart(HISTORIQUE[1], None).plain,
        )
        self.assertIn("Aucun passage", ct.texte_ecart(None, None).plain)


@contextlib.contextmanager
def sans_terminal():
    yield


class TestLEcran(CacheFictif, AsyncCase):
    def setUp(self):
        self.racine = self.preparer(self)

    async def ouvrir(self, pilote):
        await pilote.app.workers.wait_for_complete()
        await pilote.pause()

    def feuilles(self, app):
        arbre = app.query_one("#arbre")
        trouvees = []

        def parcourir(noeud):
            for enfant in noeud.children:
                if enfant.data:
                    trouvees.append(enfant.data)
                parcourir(enfant)

        parcourir(arbre.root)
        return trouvees

    async def test_tree_history_and_delta_are_shown(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            self.assertFalse(app.query_one("#vide").display)
            self.assertEqual(
                self.feuilles(app),
                [
                    "script/quokka/pivot.py",
                    FICHIER_CROCHETS,
                    "script/zorglub/brique.py",
                ],
            )
            self.assertIn("61.5 %", str(app.query_one("#arbre").root.label))
            self.assertEqual(app.query_one("#courbe").data, [60.0, 62.5])
            ecart = app.query_one("#ecart").render()
            self.assertIn("+2.50 pt", str(ecart))

    async def test_selecting_a_file_shows_its_annotated_source(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            app.montrer(FICHIER_CROCHETS)
            await pilote.pause()
            code = str(app.query_one("#code").render())
            self.assertIn("'[bold]oui[/bold]'", code)
            self.assertIn("manquante(s) : 4", code)
            self.assertEqual(app.fichier_montre, FICHIER_CROCHETS)

    async def test_the_cursor_on_a_file_shows_it(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            arbre = app.query_one("#arbre")
            arbre.focus()
            # Racine, script/, quokka/, pivot.py.
            for _ in range(3):
                await pilote.press("down")
            await pilote.pause()
            self.assertEqual(app.fichier_montre, "script/quokka/pivot.py")

    async def test_the_filter_narrows_the_tree(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            await pilote.press("slash")
            for touche in "brique":
                await pilote.press(touche)
            await pilote.pause()
            self.assertEqual(self.feuilles(app), ["script/zorglub/brique.py"])
            self.assertIn("filtre : brique", app.sub_title)
            # Une lettre de touche dans le filtre ne quitte pas l'écran.
            await pilote.press("q")
            await pilote.pause()
            self.assertTrue(app.is_running)
            await pilote.press("escape")
            self.assertIs(app.focused, app.query_one("#arbre"))

    async def test_s_cycles_the_sort(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            await pilote.press("s")
            await pilote.pause()
            self.assertEqual(app.tri, "manquantes")
            await pilote.press("s")
            await pilote.pause()
            self.assertEqual(app.tri, "nom")
            self.assertEqual(
                self.feuilles(app),
                [
                    "script/quokka/pivot.py",
                    FICHIER_CROCHETS,
                    "script/zorglub/brique.py",
                ],
            )
            await pilote.press("s")
            self.assertEqual(app.tri, "pourcentage")

    async def test_a_set_without_data_says_how_to_measure(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            await pilote.press("j")
            await self.ouvrir(pilote)
            self.assertEqual(app.jeu, "odoo")
            self.assertTrue(app.query_one("#vide").display)
            self.assertFalse(app.query_one("#corps").display)
            self.assertIn(
                "aucune mesure : r pour lancer",
                str(app.query_one("#vide").render()),
            )
            self.assertEqual(app.query_one("#courbe").data, [])

    async def test_r_runs_the_full_campaign_then_reloads(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            with (
                mock.patch.object(
                    app, "suspend", side_effect=sans_terminal
                ) as suspendre,
                mock.patch.object(ct, "_jusqu_au_bout", return_value=0) as run,
                mock.patch.object(ct, "_attendre_entree"),
                mock.patch.object(app, "charger") as charger,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                await pilote.press("r")
                await pilote.pause()
            suspendre.assert_called_once()
            run.assert_called_once_with(
                ["./script/test/run_unit_test.sh", "--coverage"]
            )
            charger.assert_called_once()

    async def test_c_runs_the_changed_tests_for_erplibre_only(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            with (
                mock.patch.object(app, "suspend", side_effect=sans_terminal),
                mock.patch.object(ct, "_jusqu_au_bout", return_value=1) as run,
                mock.patch.object(ct, "_attendre_entree"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                await pilote.press("c")
                await pilote.pause()
                self.assertEqual(
                    run.call_args.args[0],
                    [
                        "./script/test/run_unit_test.sh",
                        "--changed",
                        "--coverage",
                    ],
                )
                run.reset_mock()
                await pilote.press("j")
                await self.ouvrir(pilote)
                await pilote.press("c")
                await pilote.pause()
                run.assert_not_called()

    async def test_r_on_a_missing_launcher_runs_nothing(self):
        app = ct.build_app("odoo")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            with mock.patch.object(ct, "_jusqu_au_bout") as run:
                await pilote.press("r")
                await pilote.pause()
            run.assert_not_called()

    async def test_h_produces_the_html_and_opens_it(self):
        app = ct.build_app("erplibre")
        async with app.run_test(size=(140, 50)) as pilote:
            await self.ouvrir(pilote)
            with (
                mock.patch.object(
                    couverture, "produire_html", return_value="/x/index.html"
                ) as produire,
                mock.patch.object(ct, "ouvrir", return_value=True) as ouvrir,
            ):
                await pilote.press("h")
                await app.workers.wait_for_complete()
                await pilote.pause()
            produire.assert_called_once_with("erplibre")
            ouvrir.assert_called_once_with("/x/index.html")


class TestOuvrir(unittest.TestCase):
    def test_detached_in_its_own_session(self):
        with (
            mock.patch.object(ct.shutil, "which", return_value="/bin/x"),
            mock.patch.object(ct.subprocess, "Popen") as popen,
        ):
            self.assertTrue(ct.ouvrir("/x/index.html"))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.args[0][-1], "/x/index.html")

    def test_without_an_opener(self):
        with (
            mock.patch.object(ct.shutil, "which", return_value=None),
            mock.patch.object(ct.subprocess, "Popen") as popen,
        ):
            self.assertFalse(ct.ouvrir("/x/index.html"))
        popen.assert_not_called()


class MenuSansEffet:
    """Un TODO dont l'en-tête de menu n'écrit pas la télémétrie, et dont
    les invites rendent `reponses` dans l'ordre."""

    def preparer_menu(self, test):
        for patch in (
            mock.patch("script.todo.todo_telemetry.record"),
            mock.patch.object(todo_i18n, "_current_lang", "en"),
        ):
            patch.start()
            test.addCleanup(patch.stop)
        return todo_module.TODO()

    def repondre(self, *reponses):
        affiches = []
        suite = iter(reponses)

        def invite(texte, *args, **kwargs):
            affiches.append(texte)
            return next(suite)

        return affiches, mock.patch.object(
            todo_module.click, "prompt", side_effect=invite
        )


class TestLeMenuCouverture(MenuSansEffet, unittest.TestCase):
    def setUp(self):
        self.todo = self.preparer_menu(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (
            mock.patch.dict(os.environ, {"XDG_CACHE_HOME": tmp.name}),
            mock.patch.object(couverture, "CACHE", tmp.name),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_entry_11_of_development_opens_coverage(self):
        affiches, invite = self.repondre("11")
        with (
            invite,
            mock.patch.object(
                todo_module.TODO, "prompt_execute_coverage"
            ) as couverture_menu,
        ):
            self.todo.prompt_execute()
        couverture_menu.assert_called_once_with()
        menu = affiches[0]
        self.assertIn(
            "[10] "
            + todo_i18n.t("Git repository - Repositories and git tools"),
            menu,
        )
        self.assertIn(
            "[11] "
            + todo_i18n.t("Coverage - Track the code covered by tests"),
            menu,
        )
        self.assertIn("[12] " + todo_i18n.t("Database - Database tools"), menu)
        self.assertIn(
            "[23] " + todo_i18n.t("System - Diagnostic and disk space"), menu
        )

    def test_each_entry_reaches_its_action(self):
        actions = (
            "_coverage_tui",
            "_coverage_run_unit",
            "_studio_run_coverage",
            "_coverage_html",
            "_coverage_erase",
        )
        affiches, invite = self.repondre("1", "2", "3", "4", "5", "0")
        with contextlib.ExitStack() as pile:
            pile.enter_context(invite)
            pile.enter_context(contextlib.redirect_stdout(io.StringIO()))
            doublures = {
                nom: pile.enter_context(
                    mock.patch.object(todo_module.TODO, nom)
                )
                for nom in actions
            }
            self.assertIs(self.todo.prompt_execute_coverage(), False)
        for nom, doublure in doublures.items():
            doublure.assert_called_once_with()
        self.assertIn("Coverage", affiches[0])
        self.assertIn(
            "[5] " + todo_i18n.t("Erase the coverage data of a set"),
            affiches[0],
        )

    def lancer(self, rc=0):
        return mock.patch.object(
            todo_module.todo_journal,
            "lancer_au_terminal",
            return_value=mock.Mock(returncode=rc),
        )

    def test_unit_run_goes_through_the_terminal_with_tui(self):
        with (
            self.lancer(1) as lancer,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.todo._coverage_run_unit(), 1)
        lancer.assert_called_once_with(
            ["./script/test/run_unit_test.sh", "--tui", "--coverage"],
            check=False,
            jusqu_au_bout=True,
        )

    def test_the_screen_runs_in_its_own_process(self):
        with (
            self.lancer() as lancer,
            mock.patch("script.todo.textual_setup.ensure", return_value=True),
        ):
            self.assertEqual(self.todo._coverage_tui(), 0)
        lancer.assert_called_once_with(
            [sys.executable, "script/test/couverture_tui.py"],
            check=False,
            jusqu_au_bout=True,
        )

    def test_the_screen_without_textual_runs_nothing(self):
        with (
            self.lancer() as lancer,
            mock.patch("script.todo.textual_setup.ensure", return_value=False),
        ):
            self.assertIsNone(self.todo._coverage_tui())
        lancer.assert_not_called()

    def test_html_without_data_produces_nothing(self):
        _, invite = self.repondre("1")
        with (
            invite,
            mock.patch.object(couverture, "produire_html") as produire,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsNone(self.todo._coverage_html())
        produire.assert_not_called()

    def test_html_of_the_odoo_set_is_produced_and_opened(self):
        os.makedirs(couverture.dossier("odoo"))
        with open(couverture.chemin_json("odoo"), "w") as fh:
            json.dump(RAPPORT, fh)
        _, invite = self.repondre("2")
        with (
            invite,
            mock.patch.object(
                couverture, "produire_html", return_value="/x/index.html"
            ) as produire,
            mock.patch.object(ct, "ouvrir", return_value=True) as ouvrir,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.todo._coverage_html(), "/x/index.html")
        produire.assert_called_once_with("odoo")
        ouvrir.assert_called_once_with("/x/index.html")

    def test_erase_asks_and_defaults_to_no(self):
        _, invite = self.repondre("1")
        with (
            invite,
            mock.patch.object(
                todo_module.click, "confirm", return_value=False
            ) as confirmer,
            mock.patch.object(couverture, "effacer") as effacer,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsNone(self.todo._coverage_erase())
        self.assertIs(confirmer.call_args.kwargs["default"], False)
        effacer.assert_not_called()

    def test_erase_once_confirmed(self):
        _, invite = self.repondre("2")
        with (
            invite,
            mock.patch.object(todo_module.click, "confirm", return_value=True),
            mock.patch.object(couverture, "effacer") as effacer,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.todo._coverage_erase(), "odoo")
        effacer.assert_called_once_with("odoo")

    def test_back_from_the_set_choice_does_nothing(self):
        _, invite = self.repondre("0")
        with (
            invite,
            mock.patch.object(couverture, "effacer") as effacer,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIsNone(self.todo._coverage_erase())
        effacer.assert_not_called()


class TestAttenteJusquAuBout(unittest.TestCase):
    """Ctrl+C pendant qu'un lanceur de tests tourne : le parent attend sa
    fin au lieu de le tuer, pour que le démontage se fasse."""

    def _interrompre_pendant(self, attendre):
        ancien = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, ancien)
        principal = threading.get_ident()
        threading.Timer(
            0.1, signal.pthread_kill, (principal, signal.SIGINT)
        ).start()
        return attendre(["sh", "-c", "sleep 0.5; exit 3"])

    def test_the_screen_waits_for_the_launcher(self):
        self.assertEqual(self._interrompre_pendant(ct._jusqu_au_bout), 3)

    def test_the_menu_waits_for_the_launcher(self):
        from script.todo import todo_journal

        fini = self._interrompre_pendant(todo_journal.attendre_jusqu_au_bout)
        self.assertEqual(fini.returncode, 3)


if __name__ == "__main__":
    unittest.main()
