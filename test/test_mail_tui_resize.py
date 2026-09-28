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
import sys
import unittest

from script.todo.mail.tui import (
    PANE_SIZE_MIN,
    clamp_pane_size,
    resolve_pane_sizes,
)

# Le module d'appui voisin, comme llm_fake_server : test/ n'est pas un
# paquet, son répertoire entre donc à la main dans le chemin.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mail_tui_resize_case import ResizeCase  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
