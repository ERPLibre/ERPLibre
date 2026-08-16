#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Barres de partage glissables à la souris (tâche 25) : un bouton par
frontière ajustable (`#folders_splitter`, `#list_splitter`), qui redimensionne
en direct pendant le glissement et persiste au relâchement — par le MÊME
`_store_pane_size` que `+`/`-`/`0` au clavier (tâche 24), jamais un second
magasin.

Comme `test_mail_tui_resize.py` : tout ce qui compte ici n'a de sens que sur
l'application montée pour de vrai — les RÉGIONS mesurées avant/après un
glissement, jamais un attribut interne de `MailApp`. `Pilot.mouse_down`/
`hover`/`mouse_up` composent le glissement ; `hover`/`mouse_up` visent une
coordonnée ÉCRAN absolue (`widget=None`), pas la barre elle-même, parce que
la barre se déplace pendant le glissement (son voisin redimensionné la
pousse) — cibler à nouveau la barre par sélecteur dériverait.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import Store
from script.todo.mail.tui import PANE_SIZE_MIN, Session


class SplitterCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné — même motif que
    `test_mail_tui_resize.py`.
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

    async def _mounted_app(self):
        import textual.app

        from script.todo.mail.tui import run_tui

        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=[self.session])
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]

    async def _press_down(self, pilot, splitter_id: str):
        """`MouseDown` sur la barre `splitter_id`, à sa propre position
        (offset (0, 0) relatif à la barre) — rend son point de départ, en
        coordonnées ÉCRAN, pour que les étapes suivantes du glissement
        (`_move_to`/`_release_at`) ciblent une coordonnée ABSOLUE plutôt que
        la barre elle-même, qui se déplace pendant le glissement.
        """
        splitter = pilot.app.query_one(f"#{splitter_id}")
        start = splitter.region.offset
        await pilot.mouse_down(f"#{splitter_id}", offset=(0, 0))
        await pilot.pause()
        return start

    async def _move_to(self, pilot, offset):
        await pilot.hover(offset=offset)
        await pilot.pause()

    async def _release_at(self, pilot, offset):
        await pilot.mouse_up(offset=offset)
        await pilot.pause()

    async def _drag(self, pilot, splitter_id: str, delta_x=0, delta_y=0):
        """Glissement complet (presser, déplacer, relâcher) de `delta_x`/
        `delta_y` cellules ÉCRAN, à partir de la position actuelle de la
        barre.
        """
        start = await self._press_down(pilot, splitter_id)
        target = (start.x + delta_x, start.y + delta_y)
        await self._move_to(pilot, target)
        await self._release_at(pilot, target)


class TestSplitterWidgetsPresent(SplitterCase):
    async def test_both_splitters_exist_and_are_not_focusable(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders_splitter = app.query_one("#folders_splitter")
            list_splitter = app.query_one("#list_splitter")
            self.assertFalse(folders_splitter.can_focus)
            self.assertFalse(list_splitter.can_focus)
            # Ni l'une ni l'autre ne doit jamais recevoir le focus par
            # défaut (`Screen.AUTO_FOCUS`) à la place de `#folders`.
            from textual.widgets import Tree

            self.assertIsInstance(app.focused, Tree)


class TestDragResizesColumns(SplitterCase):
    """Disposition par défaut (`columns`) : les deux barres sont
    verticales — glisser HORIZONTALEMENT redimensionne.
    """

    async def test_dragging_folders_splitter_widens_folders_and_narrows_right(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            right = app.query_one("#right")
            width_before = folders.region.width
            right_before = right.region.width

            await self._drag(pilot, "folders_splitter", delta_x=6)

            self.assertEqual(folders.region.width, width_before + 6)
            self.assertEqual(right.region.width, right_before - 6)

    async def test_dragging_list_splitter_widens_list_and_narrows_preview(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")
            width_before = list_pane.region.width
            preview_before = preview.region.width

            await self._drag(pilot, "list_splitter", delta_x=5)

            self.assertEqual(list_pane.region.width, width_before + 5)
            self.assertEqual(preview.region.width, preview_before - 5)

    async def test_dragging_left_narrows_folders_and_widens_right(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            right = app.query_one("#right")
            width_before = folders.region.width
            right_before = right.region.width

            await self._drag(pilot, "folders_splitter", delta_x=-6)

            self.assertEqual(folders.region.width, width_before - 6)
            self.assertEqual(right.region.width, right_before + 6)


class TestDragIsLive(SplitterCase):
    async def test_the_pane_resizes_before_release_not_only_after(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            width_before = folders.region.width

            start = await self._press_down(pilot, "folders_splitter")
            target = (start.x + 6, start.y)
            await self._move_to(pilot, target)

            # Toujours en cours de glissement : le volet a DÉJÀ bougé.
            self.assertEqual(folders.region.width, width_before + 6)

            await self._release_at(pilot, target)
            self.assertEqual(folders.region.width, width_before + 6)


class TestDragPersistenceAndSharedStore(SplitterCase):
    async def test_nothing_is_written_to_disk_before_release(self):
        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            start = await self._press_down(pilot, "folders_splitter")
            target = (start.x + 6, start.y)
            await self._move_to(pilot, target)

            # `_store_pane_size` fait un aller-retour disque à chaque appel
            # -- il ne doit tourner qu'À LA LEVÉE, jamais pendant le
            # glissement lui-même.
            self.assertEqual(todo_prefs.get("mail_pane_sizes"), {})

            await self._release_at(pilot, target)
            self.assertIn("columns", todo_prefs.get("mail_pane_sizes"))

    async def test_the_released_size_is_stored_under_the_same_key_only(self):
        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            await self._drag(pilot, "folders_splitter", delta_x=6)
            width_after = folders.region.width

            sizes = todo_prefs.get("mail_pane_sizes")
            # AUCUNE autre clé de premier niveau : un seul magasin, celui
            # que la tâche 24 a créé -- jamais un second, parallèle.
            self.assertEqual(set(sizes.keys()), {"columns"})
            self.assertEqual(set(sizes["columns"].keys()), {"folders"})
            self.assertEqual(sizes["columns"]["folders"], width_after)

    async def test_the_keyboard_sees_the_size_the_mouse_just_set(self):
        from textual.widgets import DataTable

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            await self._drag(pilot, "list_splitter", delta_x=5)
            width_after_drag = list_pane.region.width

            app.query_one("#list", DataTable).focus()
            await pilot.pause()
            await pilot.press("+")
            await pilot.pause()

            # Le clavier reprend EXACTEMENT où la souris a laissé la
            # taille -- la preuve qu'il n'y a qu'un seul magasin.
            from script.todo.mail.tui import PANE_SIZE_STEP

            self.assertEqual(
                list_pane.region.width, width_after_drag + PANE_SIZE_STEP
            )


class TestDragStopsAtTheMinimum(SplitterCase):
    async def test_dragging_far_left_stops_folders_at_the_minimum(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            await self._press_down(pilot, "folders_splitter")
            # Bord gauche de l'écran : un delta négatif bien au-delà de ce
            # qu'aucun terminal ne pourrait fournir, mais une coordonnée
            # ÉCRAN toujours VALIDE (donc jamais `OutOfBounds`).
            await self._move_to(pilot, (0, 0))
            await self._release_at(pilot, (0, 0))

            self.assertEqual(folders.region.width, PANE_SIZE_MIN)

    async def test_dragging_far_right_leaves_rights_own_children_above_the_minimum(
        self,
    ):
        """`#right` n'est pas une feuille : il héberge à son tour
        `list_pane`/`list_splitter`/`preview` (voir `_PANE_SIBLING_MIN`,
        tâche 24). Pousser `#folders` jusqu'à son plafond ne doit donc PAS
        écraser `#right` à `PANE_SIZE_MIN` -- ce plancher est celui de
        `list_pane`/`preview` eux-mêmes, chacun encore mesuré ICI plutôt que
        supposé, exactement l'invariant que la tâche 24 a fini par tester
        après avoir été mordue une première fois par un nombre figé plutôt
        que par l'invariant réel (voir son rapport, « round 2 »).
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            right = app.query_one("#right")
            list_pane = app.query_one("#list_pane")
            list_splitter = app.query_one("#list_splitter")
            preview = app.query_one("#preview")
            screen_width = app.screen.size.width
            await self._press_down(pilot, "folders_splitter")
            edge = (screen_width - 1, 0)
            await self._move_to(pilot, edge)
            await self._release_at(pilot, edge)

            self.assertGreaterEqual(list_pane.region.width, PANE_SIZE_MIN)
            self.assertGreaterEqual(preview.region.width, PANE_SIZE_MIN)
            self.assertEqual(
                right.region.width,
                list_pane.region.width
                + list_splitter.region.width
                + preview.region.width,
            )

    async def test_dragging_far_left_stops_list_pane_at_the_minimum(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            list_pane = app.query_one("#list_pane")
            await self._press_down(pilot, "list_splitter")
            await self._move_to(pilot, (0, 0))
            await self._release_at(pilot, (0, 0))

            self.assertEqual(list_pane.region.width, PANE_SIZE_MIN)

    async def test_dragging_far_right_stops_preview_at_the_minimum(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            preview = app.query_one("#preview")
            screen_width = app.screen.size.width
            await self._press_down(pilot, "list_splitter")
            edge = (screen_width - 1, 0)
            await self._move_to(pilot, edge)
            await self._release_at(pilot, edge)

            self.assertEqual(preview.region.width, PANE_SIZE_MIN)


class TestDragOrientationFollowsLayout(SplitterCase):
    """Les deux barres suivent l'orientation RÉELLE du conteneur qu'elles
    jouxtent (`MailApp._pane_dimension`), jamais une table par disposition.
    """

    async def test_dragging_in_stacked_resizes_by_height_not_width(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("v")  # split
            await pilot.pause()
            await pilot.press("v")  # stacked
            await pilot.pause()
            self.assertTrue(
                app.query_one("#panes").has_class("layout-stacked")
            )

            folders = app.query_one("#folders")
            right = app.query_one("#right")
            width_before = folders.region.width
            height_before = folders.region.height
            right_height_before = right.region.height

            # `delta_y=1`, pas davantage : en `stacked`, `#panes` ne fait que
            # 21 lignes de haut (écran 80x24, moins l'en-tête/le pied) --
            # `#right` doit en garder au moins 9 (`list_pane` + la barre +
            # `preview`, chacun `>= PANE_SIZE_MIN`), donc `folders` ne peut
            # grandir que de 1 avant de buter sur ce plafond ; un delta plus
            # grand serait borné et ce test mesurerait le bornage, pas le
            # suivi d'axe qu'il vérifie ici (voir `TestDragStopsAtTheMinimum`
            # pour le bornage lui-même).
            await self._drag(pilot, "folders_splitter", delta_y=1)

            self.assertEqual(folders.region.height, height_before + 1)
            self.assertEqual(right.region.height, right_height_before - 1)
            # La largeur, elle, ne bouge pas -- ce n'est plus l'axe partagé.
            self.assertEqual(folders.region.width, width_before)

    async def test_dragging_in_split_list_splitter_resizes_by_height(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("v")  # split
            await pilot.pause()
            self.assertTrue(app.query_one("#panes").has_class("layout-split"))

            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")
            height_before = list_pane.region.height
            preview_height_before = preview.region.height

            await self._drag(pilot, "list_splitter", delta_y=3)

            self.assertEqual(list_pane.region.height, height_before + 3)
            self.assertEqual(preview.region.height, preview_height_before - 3)


class TestInterruptedDragDoesNotStick(SplitterCase):
    async def test_release_captures_only_via_the_bar_not_the_release_point(
        self,
    ):
        """Le relâchement arrive loin de la barre (une seule cellule de
        large) -- la capture de souris doit tout de même router le
        `MouseUp` vers elle (voir `Screen._forward_event`), et la libérer :
        rien de coincé après.
        """
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await self._drag(pilot, "folders_splitter", delta_x=6)

            self.assertIsNone(app.mouse_captured)

            # L'app reste utilisable : un second glissement, ailleurs,
            # fonctionne normalement -- la preuve qu'aucun état ne traîne.
            list_pane = app.query_one("#list_pane")
            width_before = list_pane.region.width
            await self._drag(pilot, "list_splitter", delta_x=3)
            self.assertEqual(list_pane.region.width, width_before + 3)

    async def test_app_blur_mid_drag_ends_it_and_persists_the_last_value(
        self,
    ):
        from textual import events

        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            start = await self._press_down(pilot, "folders_splitter")
            target = (start.x + 6, start.y)
            await self._move_to(pilot, target)

            self.assertIsNotNone(app.mouse_captured)

            app.post_message(events.AppBlur())
            await pilot.pause()

            self.assertIsNone(app.mouse_captured)
            self.assertIn(
                "folders", todo_prefs.get("mail_pane_sizes").get("columns", {})
            )

    async def test_fullscreen_mid_drag_ends_it_without_getting_stuck(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            start = await self._press_down(pilot, "folders_splitter")
            target = (start.x + 6, start.y)
            await self._move_to(pilot, target)
            self.assertIsNotNone(app.mouse_captured)

            app.action_toggle_fullscreen()
            await pilot.pause()

            self.assertIsNone(app.mouse_captured)
            self.assertTrue(app.query_one("#panes").has_class("fullscreen"))


class TestSplittersHiddenInFullscreen(SplitterCase):
    async def test_both_splitters_vanish_in_fullscreen_in_every_layout(self):
        from script.todo.mail.tui import MAIL_LAYOUTS

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            panes = app.query_one("#panes")
            folders_splitter = app.query_one("#folders_splitter")
            list_splitter = app.query_one("#list_splitter")

            for layout_id, _ in MAIL_LAYOUTS:
                while app.mail_layout != layout_id:
                    await pilot.press("v")
                    await pilot.pause()

                panes.add_class("fullscreen")
                await pilot.pause()

                self.assertEqual(folders_splitter.region.width, 0)
                self.assertEqual(folders_splitter.region.height, 0)
                self.assertEqual(list_splitter.region.width, 0)
                self.assertEqual(list_splitter.region.height, 0)

                panes.remove_class("fullscreen")
                await pilot.pause()


class TestModalPushEndsAnyPendingDrag(SplitterCase):
    """`App.push_screen` (`app.py:2937`) revokes mouse capture out from
    under a drag that hasn't been released yet -- `App.capture_mouse`
    (`app.py:3222`) posts `MouseRelease` to whatever WAS captured whenever
    capture changes, including to `None`. `_PaneSplitter` must react to
    that (`on_mouse_release`), or `MailApp`'s drag state stays pointed at
    the ABANDONED slot: since capture is now cleared, the very first
    (synthetic, pre-`MouseDown`) `MouseMove` of the NEXT, entirely
    unrelated drag is routed by ordinary hit-testing to whatever's under
    the pointer, and gets misapplied to the STALE slot before that new
    drag's own `MouseDown` has a chance to reset the state.
    """

    async def test_pushing_a_modal_mid_drag_does_not_corrupt_the_next_drag(
        self,
    ):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            folders = app.query_one("#folders")
            list_pane = app.query_one("#list_pane")
            preview = app.query_one("#preview")

            # Glissement de `folders` JAMAIS relâché : le bouton de la
            # souris est toujours, conceptuellement, enfoncé au moment où
            # le modal ci-dessous est poussé.
            start = await self._press_down(pilot, "folders_splitter")
            target = (start.x + 5, start.y)
            await self._move_to(pilot, target)
            width_mid_drag = folders.region.width

            await pilot.press("l")  # LogScreen (push_screen)
            await pilot.pause()
            await pilot.press("escape")  # ferme LogScreen (dismiss)
            await pilot.pause()

            list_width_before = list_pane.region.width
            preview_width_before = preview.region.width

            # Glissement SUIVANT, SANS RAPPORT, sur l'AUTRE barre.
            await self._drag(pilot, "list_splitter", delta_x=3)

            # `folders` n'a plus bougé depuis le modal -- rien de périmé ne
            # devait plus le toucher.
            self.assertEqual(folders.region.width, width_mid_drag)
            # Le glissement de `list_splitter` a atterri exactement là où
            # il atterrirait sans aucun modal impliqué.
            self.assertEqual(list_pane.region.width, list_width_before + 3)
            self.assertEqual(preview.region.width, preview_width_before - 3)


if __name__ == "__main__":
    unittest.main()
