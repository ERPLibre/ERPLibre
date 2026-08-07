#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Redimensionnement des volets (`+`/`-`/`0`) et bascule plein écran (`z`).

Comme `test_mail_tui_layout.py` : les fonctions pures (`clamp_pane_size`,
`resolve_pane_sizes`) se testent sans écran ; tout le reste — ce qui est
réellement posé sur les widgets, la persistance, la non-perturbation des
autres dispositions — n'a de sens que sur l'application montée pour de
vrai.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import Store
from script.todo.mail.tui import (
    MAIL_LAYOUTS,
    PANE_SIZE_MIN,
    Session,
    clamp_pane_size,
    resolve_pane_sizes,
)


class TestClampPaneSize(unittest.TestCase):
    def test_a_value_within_bounds_is_kept(self):
        self.assertEqual(clamp_pane_size(30, 80), 30)

    def test_a_value_below_the_minimum_is_raised_to_it(self):
        self.assertEqual(clamp_pane_size(1, 80, minimum=4), 4)

    def test_a_negative_value_is_raised_to_the_minimum(self):
        self.assertEqual(clamp_pane_size(-50, 80, minimum=4), 4)

    def test_a_value_that_would_crush_the_sibling_is_lowered(self):
        # total=80, minimum=4 : le voisin doit garder au moins 4 -> plafond 76
        self.assertEqual(clamp_pane_size(9999, 80, minimum=4), 76)

    def test_total_none_cannot_be_bounded(self):
        self.assertIsNone(clamp_pane_size(30, None))

    def test_total_zero_or_negative_cannot_be_bounded(self):
        self.assertIsNone(clamp_pane_size(30, 0))
        self.assertIsNone(clamp_pane_size(30, -10))

    def test_default_minimum_is_the_module_constant(self):
        self.assertEqual(clamp_pane_size(1, 80), PANE_SIZE_MIN)

    def test_sibling_minimum_defaults_to_minimum(self):
        # sibling_minimum omis == sibling_minimum=minimum : comportement
        # inchangé pour tout appelant qui ne le précise pas.
        self.assertEqual(
            clamp_pane_size(9999, 80, minimum=4),
            clamp_pane_size(9999, 80, minimum=4, sibling_minimum=4),
        )

    def test_a_larger_sibling_minimum_lowers_the_ceiling_further(self):
        # total=80, minimum=4, sibling_minimum=8 (le voisin est lui-même un
        # conteneur à deux enfants) -> plafond 72, pas 76.
        self.assertEqual(
            clamp_pane_size(9999, 80, minimum=4, sibling_minimum=8), 72
        )


class TestResolvePaneSizes(unittest.TestCase):
    def test_missing_store_yields_nothing(self):
        self.assertEqual(resolve_pane_sizes({}, "columns"), {})

    def test_none_store_yields_nothing(self):
        self.assertEqual(resolve_pane_sizes(None, "columns"), {})

    def test_store_not_a_dict_yields_nothing(self):
        self.assertEqual(resolve_pane_sizes("bogus", "columns"), {})

    def test_layout_absent_from_store_yields_nothing(self):
        self.assertEqual(
            resolve_pane_sizes({"split": {"folders": 30}}, "columns"), {}
        )

    def test_per_layout_entry_not_a_dict_yields_nothing(self):
        self.assertEqual(
            resolve_pane_sizes({"columns": "bogus"}, "columns"), {}
        )

    def test_valid_entries_are_kept(self):
        stored = {"columns": {"folders": 30, "list_pane": 22}}
        self.assertEqual(
            resolve_pane_sizes(stored, "columns"),
            {"folders": 30, "list_pane": 22},
        )

    def test_a_zero_or_negative_slot_value_is_dropped(self):
        stored = {"columns": {"folders": 0, "list_pane": -5}}
        self.assertEqual(resolve_pane_sizes(stored, "columns"), {})

    def test_a_non_numeric_slot_value_is_dropped(self):
        stored = {"columns": {"folders": "wide", "list_pane": None}}
        self.assertEqual(resolve_pane_sizes(stored, "columns"), {})

    def test_a_boolean_slot_value_is_dropped(self):
        # bool est une sous-classe d'int en Python -- True/False ne sont
        # jamais des tailles valides, un piège classique à garder fermé.
        stored = {"columns": {"folders": True}}
        self.assertEqual(resolve_pane_sizes(stored, "columns"), {})

    def test_an_unknown_slot_key_is_ignored(self):
        stored = {"columns": {"folders": 30, "bogus_slot": 99}}
        self.assertEqual(
            resolve_pane_sizes(stored, "columns"), {"folders": 30}
        )

    def test_a_float_slot_value_is_kept_as_int(self):
        stored = {"columns": {"folders": 30.7}}
        result = resolve_pane_sizes(stored, "columns")
        self.assertEqual(result["folders"], 30)
        self.assertIsInstance(result["folders"], int)


class ResizeCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné — même motif que
    `test_mail_tui_layout.py`.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

        self.cache_dir = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.account.cache_mode = "clear"
        self.store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        self.store.open()
        self.session = Session(self.account, self.store, None, password="x")

    def tearDown(self):
        self.store.close()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    def _fresh_session(self):
        """Une DEUXIÈME session sur le MÊME cache disque — pas
        `self.session` réutilisée : `MailApp.on_unmount` ferme la session
        (donc le `Store`) quand `run_test()` démonte l'appli, si bien que
        réutiliser le même objet `Session` pour un second montage
        planterait sur un cache déjà fermé. Un vrai redémarrage rouvre le
        cache depuis le DISQUE ; ceci en est le double fidèle.
        """
        store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        store.open()
        return Session(self.account, store, None, password="x")

    async def _mounted_app(self, sessions=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        sessions = sessions if sessions is not None else [self.session]
        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=sessions)
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]


class TestFocusedPaneSlot(ResizeCase):
    async def test_folders_has_focus_on_first_mount(self):
        from textual.widgets import Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.focused, Tree)
            self.assertEqual(app._focused_pane_slot(), "folders")

    async def test_the_list_maps_to_the_list_pane_slot(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            self.assertEqual(app._focused_pane_slot(), "list_pane")

    async def test_the_search_input_maps_to_the_list_pane_slot(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.action_focus_search()
            await pilot.pause()
            self.assertEqual(app._focused_pane_slot(), "list_pane")


class TestGrowShrinkColumns(ResizeCase):
    """Disposition par défaut : `#folders`/`#right` se partagent la LARGEUR
    de `#panes`, `#list_pane`/`#preview` la largeur de `#right`.
    """

    async def test_growing_the_focused_list_widens_it_and_narrows_preview(
        self,
    ):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")
            width_before = list_pane.region.width
            preview_before = preview.region.width

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.pause()

            self.assertEqual(list_pane.region.width, width_before + 4)
            self.assertEqual(preview.region.width, preview_before - 4)

    async def test_shrinking_the_focused_list_narrows_it_and_widens_preview(
        self,
    ):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")
            width_before = list_pane.region.width
            preview_before = preview.region.width

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("-")
            await pilot.pause()

            self.assertEqual(list_pane.region.width, width_before - 4)
            self.assertEqual(preview.region.width, preview_before + 4)

    async def test_growing_the_focused_folders_widens_it_and_narrows_right(
        self,
    ):
        from textual.widgets import Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            right = app.query_one("#right")
            self.assertIsInstance(app.focused, Tree)
            width_before = folders.region.width
            right_before = right.region.width

            await pilot.press("+")
            await pilot.pause()

            self.assertEqual(folders.region.width, width_before + 4)
            self.assertEqual(right.region.width, right_before - 4)

    async def test_shrinking_stops_at_the_minimum(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(30):
                await pilot.press("-")
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            self.assertEqual(list_pane.region.width, PANE_SIZE_MIN)
            # Une pression de plus ne descend pas sous le plancher.
            await pilot.press("-")
            await pilot.pause()
            self.assertEqual(list_pane.region.width, PANE_SIZE_MIN)

    async def test_growing_is_bounded_so_the_sibling_keeps_the_minimum(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(60):
                await pilot.press("+")
            await pilot.pause()

            preview = app.query_one("#preview")
            self.assertEqual(preview.region.width, PANE_SIZE_MIN)

    async def test_no_op_when_focus_is_outside_any_resizable_slot(self):
        """`#preview` n'est pas focalisable aujourd'hui, donc ce chemin
        n'est pas atteignable en pratique -- mais `_focused_pane_slot`
        doit rendre `None` plutôt que planter si le focus n'est ni dans
        `#folders` ni dans `#list_pane`, pour rester correct si un futur
        volet focalisable s'ajoute ailleurs.
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.set_focus(None)
            await pilot.pause()
            self.assertIsNone(app._focused_pane_slot())
            # Et l'action elle-même ne lève pas.
            app.action_grow_pane()
            app.action_shrink_pane()


class TestResetPaneSizes(ResizeCase):
    async def test_reset_restores_the_layout_defaults(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            width_before = list_pane.region.width

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.press("+")
            await pilot.pause()
            self.assertNotEqual(list_pane.region.width, width_before)

            await pilot.press("0")
            await pilot.pause()

            self.assertEqual(list_pane.region.width, width_before)

    async def test_reset_clears_the_stored_customization(self):
        from textual.widgets import DataTable

        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.pause()
            self.assertIn("columns", todo_prefs.get("mail_pane_sizes", {}))

            await pilot.press("0")
            await pilot.pause()

        sizes = todo_prefs.get("mail_pane_sizes", {})
        self.assertEqual(sizes.get("columns", {}), {})


class TestPaneSizePersistence(ResizeCase):
    async def test_a_customized_size_survives_a_restart(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.press("+")
            await pilot.pause()
            grown_width = app.query_one("#list_pane").region.width

        app2 = await self._mounted_app(sessions=[self._fresh_session()])
        async with app2.run_test() as pilot:
            await app2.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(
                app2.query_one("#list_pane").region.width, grown_width
            )

    async def test_a_corrupt_stored_size_falls_back_without_raising(self):
        from script.todo import todo_prefs

        todo_prefs.set(
            "mail_pane_sizes", {"columns": {"folders": "not-a-size"}}
        )
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            # Ne lève pas, et retombe sur la valeur de la feuille de style
            # (28, la même qu'avant cette tâche).
            self.assertEqual(app.query_one("#folders").region.width, 28)

    async def test_an_absurdly_large_stored_size_is_clamped(self):
        from script.todo import todo_prefs

        todo_prefs.set("mail_pane_sizes", {"columns": {"folders": 99999}})
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            panes = app.query_one("#panes")
            folders = app.query_one("#folders")
            self.assertLessEqual(
                folders.region.width, panes.region.width - PANE_SIZE_MIN
            )

    async def test_resizing_one_layout_does_not_disturb_another(self):
        from textual.widgets import DataTable

        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.press("+")
            await pilot.pause()

            await pilot.press("v")  # -> split
            await pilot.pause()

        sizes = todo_prefs.get("mail_pane_sizes", {})
        self.assertIn("columns", sizes)
        self.assertNotIn("split", sizes)


class TestFullscreenKey(ResizeCase):
    """`enter` est lié à `action_toggle_fullscreen` sur `MailApp`, mais
    `Tree`/`DataTable` lient déjà `enter` eux-mêmes (`select_cursor`) et
    gagnent toujours -- Textual donne priorité à la liaison la plus proche
    du nœud focalisé (`App._check_bindings`, chaîne `focused.ancestors_with_self`,
    voir le commentaire de `_SearchInput`). Comme l'un des deux a TOUJOURS le
    focus par défaut, `enter` n'atteint donc jamais `MailApp` en pratique --
    `z` (libre, non revendiqué par `Tree`/`DataTable`/`Input`) le remplace.
    """

    async def test_z_toggles_fullscreen_while_folders_has_focus(self):
        from textual.widgets import Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIsInstance(app.focused, Tree)

            panes = app.query_one("#panes")
            preview = app.query_one("#preview")
            await pilot.press("z")
            await pilot.pause()

            self.assertTrue(panes.has_class("fullscreen"))
            self.assertEqual(preview.region, panes.region)

            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(panes.has_class("fullscreen"))

    async def test_z_toggles_fullscreen_while_the_list_has_focus(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            app.query_one("#list", DataTable).focus()
            await pilot.pause()

            panes = app.query_one("#panes")
            await pilot.press("z")
            await pilot.pause()

            self.assertTrue(panes.has_class("fullscreen"))

    async def test_enter_no_longer_claims_a_binding_at_the_app_level(self):
        """`enter` reste lié à `Tree`/`DataTable` eux-mêmes (sélection) --
        mais `MailApp` ne le revendique plus pour le plein écran, pour ne
        pas laisser un pied d'écran annoncer une touche qui, depuis l'état
        focalisé par défaut, ne fait jamais rien.
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            bindings = app._bindings.key_to_bindings
            self.assertNotIn("enter", bindings)
            self.assertIn("z", bindings)

    async def test_the_binding_is_translated_in_the_footer(self):
        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            active = app.screen.active_bindings["z"]
            self.assertEqual(
                active.binding.description, t("mail_fullscreen_binding")
            )


class TestTerminalResizeRespectsMinimum(ResizeCase):
    """Fix round : un volet grandi, puis un TERMINAL rétréci sans qu'aucune
    touche ne soit pressée, ne repassait par aucune des actions qui
    bornent — la surcharge en ligne restait figée à l'ancienne valeur, et
    le voisin s'écrasait jusqu'à zéro, sans qu'aucune touche ne puisse le
    récupérer (le plafond du volet écrasé se calcule alors contre SA
    PROPRE région, déjà nulle). `on_resize` reborne maintenant contre
    l'espace RÉELLEMENT disponible à chaque redimensionnement du terminal
    — mesuré ici, jamais une classe ni une variable interne.
    """

    async def test_shrinking_the_terminal_keeps_every_pane_above_minimum(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            panes = app.query_one("#panes")
            folders = app.query_one("#folders")
            right = app.query_one("#right")
            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")

            for layout_id, _ in MAIL_LAYOUTS:
                while app.mail_layout != layout_id:
                    await pilot.press("v")
                    await pilot.pause()

                # Grandit le volet dossiers (focus par défaut) près du
                # maximum permis par le terminal 80x24 de départ.
                for _ in range(20):
                    await pilot.press("+")
                await pilot.pause()

                # 40x18 (aire de #panes ~15) : assez pour satisfaire les
                # planchers des TROIS volets même en « stacked », le pire
                # cas (folders>=4 ET #right>=8, puisque #right y héberge à
                # son tour list_pane/preview le long du MÊME axe -- voir
                # `_PANE_SIBLING_MIN`) ; en dessous de ~15, ce ne serait
                # plus une question de correctif mais de terminal
                # physiquement trop petit pour les trois planchers à la
                # fois, hors de portée de tout redimensionnement de volet.
                await pilot.resize_terminal(40, 18)
                await pilot.pause()
                await pilot.pause()  # laisse le correctif différé tourner

                folders_dim = app._pane_dimension(panes)
                list_dim = app._pane_dimension(right)

                for widget, dim, name in (
                    (folders, folders_dim, "folders"),
                    (right, folders_dim, "right"),
                    (list_pane, list_dim, "list_pane"),
                    (preview, list_dim, "preview"),
                ):
                    measured = getattr(widget.region, dim)
                    self.assertGreaterEqual(
                        measured,
                        PANE_SIZE_MIN,
                        f"disposition {layout_id!r} : {name}.{dim} ="
                        f" {measured}, attendu >= {PANE_SIZE_MIN}",
                    )

                # Repart d'un terminal et de tailles propres avant la
                # disposition suivante.
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                await pilot.pause()
                await pilot.press("0")
                await pilot.pause()

    async def test_growing_the_terminal_back_restores_the_stored_size(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(3):
                await pilot.press("+")
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            grown_width = list_pane.region.width

            await pilot.resize_terminal(40, 24)
            await pilot.pause()
            await pilot.pause()
            self.assertLess(list_pane.region.width, grown_width)

            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            await pilot.pause()
            # L'INTENTION (stockée, jamais écrasée par le rétrécissement
            # temporaire) revient dès que la place existe de nouveau.
            self.assertEqual(list_pane.region.width, grown_width)


class TestReSettlingDoesNotStarveTheUncustomizedSibling(ResizeCase):
    """Round 3 : `_apply_pane_size_for_slot` lisait `pane.region` juste
    après son PROPRE `self._clear_pane_size(slot)`, dans le MÊME appel --
    cette région est pré-rafraîchissement, exactement la même classe de
    bogue déjà corrigée pour la lecture de `#right`. Reproduit en poussant
    `#folders` à son plafond (11 pressions, `#right` = 8, `list_pane` déjà
    correctement à 4), puis en redéclenchant `_apply_pane_size_for_slot`
    une seconde fois SANS rien changer à `#folders` -- soit par une
    pression `+` de plus (déjà au plafond, donc sans effet sur `#folders`
    lui-même), soit par un redimensionnement du terminal. `list_pane`
    retombait alors à 3 et y restait, PAS transitoirement.

    N'affirme jamais un nombre précis (ce serait passer par parité, comme
    le test initial de ce correctif qui ne reproduisait pas ce cas) :
    seulement que chaque volet reste >= `PANE_SIZE_MIN`.
    """

    async def _grow_folders_to_ceiling(self, pilot):
        for _ in range(11):
            await pilot.press("+")
        await pilot.pause()

    def _assert_every_pane_at_or_above_minimum(self, app):
        folders = app.query_one("#folders")
        right = app.query_one("#right")
        list_pane = app.query_one("#list_pane")
        preview = app.query_one("#preview")
        for widget, name in (
            (folders, "folders"),
            (right, "right"),
            (list_pane, "list_pane"),
            (preview, "preview"),
        ):
            self.assertGreaterEqual(
                widget.region.width,
                PANE_SIZE_MIN,
                f"{name}.width = {widget.region.width}, attendu >="
                f" {PANE_SIZE_MIN}",
            )

    async def test_an_extra_no_op_grow_does_not_starve_list_pane(self):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)
            # #folders est déjà à son plafond : cette pression ne le
            # change PAS, mais redéclenche quand même la correction de
            # list_pane.
            await pilot.press("+")
            await pilot.pause()

            self._assert_every_pane_at_or_above_minimum(app)

    async def test_a_clean_resize_after_reaching_the_ceiling_does_not_starve_list_pane(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self._assert_every_pane_at_or_above_minimum(app)

    async def test_a_stored_list_pane_size_is_recapped_when_folders_grows(
        self,
    ):
        """Ce que `then=` sert encore à garantir, une fois le plancher
        confié à la feuille de style : la taille STOCKÉE de `list_pane` doit
        être re-bornée contre le `#right` qui RESTE après l'agrandissement
        de `#folders`, pas contre celui d'avant.

        Mesuré par le remplissage EXACT de `#right` par ses trois enfants :
        une taille bornée contre un `#right` périmé les fait déborder, ce
        qu'aucune assertion de plancher ne verrait — `min-width` maintient
        alors chaque volet au-dessus de son plancher pendant que la somme
        dépasse le conteneur.
        """
        from textual.widgets import DataTable, Tree

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            # Une taille de `list_pane` VOULUE par l'utilisateur, donc
            # stockée -- sans elle, rien à re-borner ici.
            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            for _ in range(3):
                await pilot.press("+")
            await pilot.pause()

            app.query_one("#folders", Tree).focus()
            await pilot.pause()
            await self._grow_folders_to_ceiling(pilot)

            right = app.query_one("#right")
            list_pane = app.query_one("#list_pane")
            list_splitter = app.query_one("#list_splitter")
            preview = app.query_one("#preview")
            self.assertEqual(
                list_pane.region.width
                + list_splitter.region.width
                + preview.region.width,
                right.region.width,
                f"list_pane {list_pane.region.width} + barre"
                f" {list_splitter.region.width} + preview"
                f" {preview.region.width} != #right"
                f" {right.region.width}",
            )
            self._assert_every_pane_at_or_above_minimum(app)


class _PaneThatMisreportsItsRegion:
    """Un volet qui MENT sur sa propre région, et note qu'on la lui a
    demandée. Tout le reste (`styles` compris) passe au vrai widget, si bien
    qu'une taille posée à travers ce mandataire arrive réellement sur
    l'écran.

    Sert à prouver une propriété STRUCTURELLE plutôt qu'à rejouer un
    scénario : la taille d'un volet ne doit dépendre en RIEN de la région de
    ce volet, parce qu'à l'instant où elle serait lue elle est encore
    pré-rafraîchissement (voir `_apply_pane_size_for_slot`). Une propriété
    ne se teste pas en attendant qu'une course se produise — 3 % des
    exécutions, la raison pour laquelle ce bogue a survécu à trois
    corrections.
    """

    # TOUTES les façons d'obtenir la géométrie RENDUE d'un widget, pas la
    # seule qui a servi au bogue : n'intercepter que `region` interdirait
    # une ORTHOGRAPHE, pas la classe -- `pane.size` rentrerait par la
    # fenêtre et les 46 tests resteraient verts.
    _MEASURED = frozenset(
        {
            "region",
            "size",
            "content_region",
            "content_size",
            "outer_size",
            "container_size",
            "virtual_size",
            "window_region",
            "scrollable_content_region",
        }
    )

    def __init__(self, widget, lie, reads):
        self._widget = widget
        self._lie = lie
        self._reads = reads

    def __getattr__(self, name):
        # `_widget`/`_lie`/`_reads` sont des attributs d'instance : la
        # recherche normale les trouve, `__getattr__` n'est jamais appelé
        # pour eux.
        if name in self._MEASURED:
            self._reads.append(f"{self._widget.id}.{name}")
            return self._lie
        return getattr(self._widget, name)


class TestPaneSizingIgnoresThePanesOwnRegion(ResizeCase):
    """Tâche 27. `_settle` prenait la région du volet comme base de bornage
    quand rien n'était stocké — une région que son PROPRE
    `_clear_pane_size`, deux lignes plus haut, venait d'invalider. Un
    `call_after_refresh` rendait la lecture juste presque toujours ; quand
    elle ne l'était pas, la base valait l'ancienne surcharge, le bornage
    retombait dessus, la branche « rien à corriger » sautait l'écriture, et
    `list_pane` restait DÉFINITIVEMENT à la part que la feuille de style lui
    donne (`2fr` de `#right`, soit 3 cellules).

    Les deux tests ci-dessous rendent ce cas DÉTERMINISTE.
    """

    async def _grow_folders_to_ceiling(self, pilot):
        for _ in range(11):
            await pilot.press("+")
        await pilot.pause()

    def _assert_every_pane_at_or_above_minimum(self, app):
        for name in ("#folders", "#right", "#list_pane", "#preview"):
            measured = app.query_one(name).region.width
            self.assertGreaterEqual(
                measured,
                PANE_SIZE_MIN,
                f"{name}.width = {measured}, attendu >= {PANE_SIZE_MIN}",
            )

    def _lie_about_pane_regions(self, app, lie, reads, calls):
        """Détourne `_pane_widgets` pour rendre un volet menteur, et note
        CHAQUE appel — les appels servent de contrôle positif : sans eux, un
        test qui n'affirme qu'une absence de lecture passerait tout aussi
        bien si le réglage des tailles n'avait pas tourné du tout.
        """
        original = app._pane_widgets

        def _patched(slot: str):
            calls.append(slot)
            pane, parent = original(slot)
            return _PaneThatMisreportsItsRegion(pane, lie, reads), parent

        app._pane_widgets = _patched

    async def test_the_floor_holds_even_when_the_pane_misreports_its_size(
        self,
    ):
        """Le volet rapporte EXACTEMENT le plancher : sous l'ancien code,
        `clamped == current` faisait sauter l'écriture et la feuille de
        style reprenait la main avec 3 cellules. Le plancher ne se mesure
        plus (`_PANE_MIN_CSS`), donc mentir ne peut plus l'abaisser.
        """
        from textual.geometry import Region

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            reads, calls = [], []
            self._lie_about_pane_regions(
                app,
                Region(0, 0, PANE_SIZE_MIN, PANE_SIZE_MIN),
                reads,
                calls,
            )
            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self.assertTrue(
                calls, "le réglage des tailles n'a pas tourné du tout"
            )
            self._assert_every_pane_at_or_above_minimum(app)

    async def test_settling_never_reads_the_region_of_the_pane_it_sizes(self):
        """La propriété elle-même, pas une de ses conséquences : aucune
        lecture, donc rien à lire trop tôt. Pour qu'une lecture périmée
        revienne, il faudrait la réintroduire ici — ce test l'interdit.
        """
        from textual.geometry import Region

        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._grow_folders_to_ceiling(pilot)

            reads, calls = [], []
            # Un redimensionnement du terminal, pas une touche `+`/`-` :
            # `_resize_focused_pane` lit LÉGITIMEMENT la région du volet (la
            # taille vive que l'utilisateur veut incrémenter), et cette
            # lecture-là ne suit aucun effacement.
            self._lie_about_pane_regions(
                app, Region(0, 0, 999, 999), reads, calls
            )
            await pilot.resize_terminal(81, 24)
            await pilot.pause()
            await pilot.pause()

            self.assertTrue(
                calls, "le réglage des tailles n'a pas tourné du tout"
            )
            self.assertEqual(
                reads,
                [],
                "le réglage des tailles a lu la région des volets"
                f" {reads} — une valeur encore pré-rafraîchissement",
            )
            # Et le mensonge n'a rien déréglé : la preuve que le chemin
            # exercé est bien le chemin mesuré.
            self._assert_every_pane_at_or_above_minimum(app)


class TestSmallTerminalsKeepEveryPaneOnScreen(ResizeCase):
    """Un volet qui DÉBORDE de son conteneur n'est pas seulement mal
    dimensionné : il n'est jamais composité. Aucune barre de défilement
    n'apparaît, `Tab` ne l'atteint pas, et rien à l'écran ne dit qu'il
    existe. C'est arrivé en « stacked » dès 80x20, dans l'état PAR DÉFAUT,
    sans qu'aucun test le voie : tous ceux qui approchent ces tailles
    pressent `+` d'abord, et une taille de `#folders` stockée réserve
    justement à `#right` de quoi tenir.

    `resolve_fraction_unit` (`_resolve.py:190-214`) épingle à son minimum
    tout enfant `fr` qui descendrait sous lui et le RETIRE du réservoir ;
    quand tous les frères `fr` s'épinglent, `1fr` vaut TOUT l'espace
    restant et chacun reçoit la totalité. Deux volets de 7 dans un
    conteneur de 8.

    Ces tests mesurent donc le REMPLISSAGE EXACT et la COMPOSITION, pas des
    planchers : un plancher tenu par un volet hors écran est tenu pour
    rien. Ils cassent aussi si Textual changeait la soustraction
    `border-box` de `_resolve_extrema`, qui décide ce que valent ces
    tailles.
    """

    # 13 lignes est le plancher réel de « stacked » : `#folders` ne descend
    # pas sous `PANE_SIZE_MIN`, `#right` a besoin d'au moins `PANE_SIZE_MIN`
    # + la barre pour que `#preview` garde une ligne, et `#panes` perd
    # l'en-tête, l'état et le pied. En dessous, aucune disposition des
    # trois volets ne tient — ce n'est plus un défaut de bornage.
    SMALL_SIZES = ((80, 20), (80, 18), (80, 16), (80, 14), (40, 18))

    def _assert_panes_fit_and_paint(self, app, label):
        panes = app.query_one("#panes")
        right = app.query_one("#right")
        outer = app._pane_dimension(panes)
        inner = app._pane_dimension(right)

        def measure(selector, dimension):
            return getattr(app.query_one(selector).region, dimension)

        outer_sum = (
            measure("#folders", outer)
            + measure("#folders_splitter", outer)
            + measure("#right", outer)
        )
        self.assertEqual(
            outer_sum,
            measure("#panes", outer),
            f"{label} : #folders + barre + #right = {outer_sum} !="
            f" #panes {measure('#panes', outer)} ({outer})",
        )
        inner_sum = (
            measure("#list_pane", inner)
            + measure("#list_splitter", inner)
            + measure("#preview", inner)
        )
        self.assertEqual(
            inner_sum,
            measure("#right", inner),
            f"{label} : #list_pane + barre + #preview = {inner_sum} !="
            f" #right {measure('#right', inner)} ({inner})",
        )

        # Le remplissage exact ne suffit pas à prouver qu'on VOIT les
        # volets : c'est le compositeur qui décide ce qui est peint.
        visible = app.screen._compositor.visible_widgets
        for selector in ("#folders", "#list_pane", "#preview"):
            self.assertIn(
                app.query_one(selector),
                visible,
                f"{label} : {selector} n'est pas composité — hors écran,"
                " sans barre de défilement ni accès au clavier",
            )

    async def test_a_fresh_launch_at_80x20_paints_every_pane(self):
        """Le scénario exact du signalement : premier lancement, aucune
        touche, une disposition par démarrage — pas un redimensionnement
        depuis une taille plus grande, qui n'emprunte pas le même chemin de
        montage.
        """
        from script.todo import todo_prefs

        for layout_id, _ in MAIL_LAYOUTS:
            todo_prefs.set("mail_layout", layout_id)
            app = await self._mounted_app(sessions=[self._fresh_session()])
            async with app.run_test(size=(80, 20)) as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()
                await pilot.pause()

                self.assertEqual(app.mail_layout, layout_id)
                self._assert_panes_fit_and_paint(
                    app, f"lancement 80x20 en {layout_id!r}"
                )

    async def test_no_pane_is_pushed_off_screen_at_small_sizes(self):
        """La même garantie sur une plage de tailles et les trois
        dispositions, toujours SANS personnalisation — c'est l'absence de
        taille stockée qui déclenchait le défaut.
        """
        app = await self._mounted_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            for width, height in self.SMALL_SIZES:
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                await pilot.pause()
                for layout_id, _ in MAIL_LAYOUTS:
                    while app.mail_layout != layout_id:
                        await pilot.press("v")
                        await pilot.pause()
                    await pilot.pause()
                    self._assert_panes_fit_and_paint(
                        app, f"{width}x{height} en {layout_id!r}"
                    )


if __name__ == "__main__":
    unittest.main()
