#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Dispositions de volets commutables (touche `v`) : `columns` (défaut,
dossiers | liste | aperçu), `split` (dossiers à gauche ; liste au-dessus de
l'aperçu) et `stacked` (les trois empilés).

`resolve_layout`/`next_layout` sont des fonctions pures, testées sans écran.
Le reste — la classe CSS réellement posée sur `#panes`, la persistance dans
`todo_prefs`, et surtout la NON-perturbation de ce que l'utilisateur regarde
— n'a de sens que sur l'application montée pour de vrai, comme
`test_mail_tui_refresh.py`.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import (
    MAIL_LAYOUTS,
    Session,
    next_layout,
    resolve_layout,
)


class TestResolveLayout(unittest.TestCase):
    def test_known_value_is_kept(self):
        self.assertEqual(resolve_layout("split"), "split")

    def test_unknown_value_falls_back_to_columns(self):
        self.assertEqual(resolve_layout("bogus"), "columns")

    def test_empty_value_falls_back_to_columns(self):
        self.assertEqual(resolve_layout(""), "columns")

    def test_none_falls_back_to_columns(self):
        self.assertEqual(resolve_layout(None), "columns")


class TestNextLayout(unittest.TestCase):
    def test_cycles_in_declared_order(self):
        ids = [layout_id for layout_id, _ in MAIL_LAYOUTS]
        self.assertEqual(ids, ["columns", "split", "stacked"])
        self.assertEqual(next_layout("columns"), "split")
        self.assertEqual(next_layout("split"), "stacked")

    def test_wraps_around_after_the_last(self):
        self.assertEqual(next_layout("stacked"), "columns")

    def test_an_invalid_current_value_starts_the_cycle_from_the_first(self):
        self.assertEqual(next_layout("bogus"), "split")


class LayoutCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné — même motif que
    `test_mail_tui_refresh.py` : `on_mount` lit `todo_prefs`, qui crée
    `~/.erplibre` s'il est absent.
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
        # Pas de syncer : ces tests portent sur la disposition et la
        # persistance de l'état affiché, jamais sur le réseau.
        self.session = Session(self.account, self.store, None, password="x")

    def tearDown(self):
        self.store.close()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    def _seed_two_messages(self):
        fid = self.store.upsert_folder("INBOX", "INBOX", "inbox")
        self.store.upsert_messages(
            fid,
            [
                MessageMeta(
                    uid=1,
                    date=1_000,
                    size=10,
                    flags="",
                    msgid="<1@x.ca>",
                    frm="a@x.ca",
                    to="moi@x.ca",
                    subject="Un",
                    snippet="",
                ),
                MessageMeta(
                    uid=2,
                    date=2_000,
                    size=10,
                    flags="",
                    msgid="<2@x.ca>",
                    frm="b@x.ca",
                    to="moi@x.ca",
                    subject="Deux",
                    snippet="",
                ),
            ],
        )

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


class TestDefaultLayout(LayoutCase):
    async def test_columns_is_the_default_on_first_run(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            panes = app.query_one("#panes")
            self.assertTrue(panes.has_class("layout-columns"))
            self.assertEqual(app.mail_layout, "columns")


class TestCycleLayout(LayoutCase):
    async def test_v_cycles_through_every_layout_and_wraps(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            panes = app.query_one("#panes")

            await pilot.press("v")
            await pilot.pause()
            self.assertTrue(panes.has_class("layout-split"))
            self.assertFalse(panes.has_class("layout-columns"))

            await pilot.press("v")
            await pilot.pause()
            self.assertTrue(panes.has_class("layout-stacked"))
            self.assertFalse(panes.has_class("layout-split"))

            await pilot.press("v")
            await pilot.pause()
            self.assertTrue(panes.has_class("layout-columns"))
            self.assertFalse(panes.has_class("layout-stacked"))

    async def test_the_binding_is_translated_in_the_footer(self):
        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            active = app.screen.active_bindings["v"]
            self.assertEqual(
                active.binding.description, t("mail_layout_binding")
            )

    async def test_switching_reports_the_new_layout_translated(self):
        from textual.widgets import Static

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("v")
            await pilot.pause()

            status = app.query_one("#status", Static)
            self.assertIn(t("mail_layout_split"), str(status.content))


class TestLayoutPersistence(LayoutCase):
    async def test_the_choice_is_written_to_preferences(self):
        from script.todo import todo_prefs

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()

        self.assertEqual(todo_prefs.get("mail_layout"), "split")

    async def test_a_fresh_mount_reads_back_the_stored_layout(self):
        from script.todo import todo_prefs

        todo_prefs.set("mail_layout", "stacked")
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app.mail_layout, "stacked")
            self.assertTrue(
                app.query_one("#panes").has_class("layout-stacked")
            )

    async def test_a_corrupt_stored_value_falls_back_to_columns(self):
        from script.todo import todo_prefs

        todo_prefs.set("mail_layout", "not-a-real-layout")
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app.mail_layout, "columns")
            self.assertTrue(
                app.query_one("#panes").has_class("layout-columns")
            )


class TestLayoutSwitchPreservesState(LayoutCase):
    """La propriété qui compte le plus : rien de ce que l'utilisateur
    regarde ne doit bouger quand la disposition change — seule la classe
    CSS de `#panes` doit changer.
    """

    async def test_folder_selection_survives_a_switch(self):
        self._seed_two_messages()
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            ref_before = app.current_ref

            await pilot.press("v")
            await pilot.pause()

            self.assertIs(app.current_ref, ref_before)

    async def test_the_highlighted_message_survives_a_switch(self):
        from textual.widgets import DataTable

        self._seed_two_messages()
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            table.move_cursor(row=1)
            await pilot.pause()
            highlighted_before = app.current_meta()
            self.assertIsNotNone(highlighted_before)

            await pilot.press("v")
            await pilot.pause()

            self.assertEqual(app.current_meta().uid, highlighted_before.uid)
            self.assertEqual(table.cursor_row, 1)

    async def test_the_search_filter_survives_a_switch(self):
        self._seed_two_messages()
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query = "Deux"
            app.refresh_list()
            from textual.widgets import DataTable

            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 1)

            await pilot.press("v")
            await pilot.pause()

            self.assertEqual(app.query, "Deux")
            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 1)

    async def test_fullscreen_state_survives_a_switch(self):
        self._seed_two_messages()
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            panes = app.query_one("#panes")
            panes.add_class("fullscreen")

            await pilot.press("v")
            await pilot.pause()

            self.assertTrue(panes.has_class("fullscreen"))
            self.assertTrue(panes.has_class("layout-split"))

    async def test_fullscreen_toggle_still_works_in_every_layout(self):
        """`enter` lui-même n'atteint `MailApp` que lorsque le focus n'est
        ni sur `#folders` (Tree) ni sur `#list` (DataTable) — les deux lient
        déjà `enter` à `select_cursor`, et Textual donne priorité à la
        liaison la plus proche du focus (voir le commentaire de
        `_SearchInput`) — un fait préexistant, sans rapport avec les
        dispositions. On passe donc par l'action elle-même pour entrer en
        plein écran, symétriquement à `escape` (jamais intercepté par ces
        deux widgets), qui lui reste testé au clavier.
        """
        self._seed_two_messages()
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            await pilot.press("v")  # split
            await pilot.pause()

            app.action_toggle_fullscreen()
            await pilot.pause()
            panes = app.query_one("#panes")
            self.assertTrue(panes.has_class("fullscreen"))
            self.assertTrue(panes.has_class("layout-split"))

            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(panes.has_class("fullscreen"))


class TestFullscreenFillsThePanes(LayoutCase):
    """Ce que la revue a trouvé, et qu'aucune assertion sur la classe
    `fullscreen` ne peut voir : `.fullscreen #folders, .fullscreen #list`
    n'effaçait que les WIDGETS, pas leurs conteneurs enveloppants
    (`#list_pane`, `#right`), qui gardaient la taille que leur donne le
    bloc CSS de la disposition active — l'aperçu ne prenait donc jamais
    tout l'écran. En `columns` cela laissait ~40 % de l'écran vide (le
    conteneur de liste, toujours large de 2fr) ; en `split`/`stacked`,
    ~49 % (le conteneur de liste, toujours haut de 1fr). Il faut donc
    MESURER la région réellement occupée par `#preview`, pas seulement
    lire une classe CSS.
    """

    async def test_the_preview_fills_the_panes_area_in_every_layout(self):
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            panes = app.query_one("#panes")
            preview = app.query_one("#preview")
            list_pane = app.query_one("#list_pane")
            folders = app.query_one("#folders")

            for layout_id, _ in MAIL_LAYOUTS:
                while app.mail_layout != layout_id:
                    await pilot.press("v")
                    await pilot.pause()

                panes.add_class("fullscreen")
                await pilot.pause()

                # La preuve qui compte : l'aperçu occupe TOUTE la région de
                # `#panes`, pas seulement une fraction — c'est le contraire
                # exact de ce qui a été mesuré avant le correctif (largeur
                # ou hauteur de l'aperçu strictement inférieure à celle de
                # `#panes`).
                self.assertEqual(
                    preview.region,
                    panes.region,
                    f"disposition {layout_id!r} : aperçu {preview.region},"
                    f" attendu {panes.region}",
                )
                # Les deux conteneurs masqués n'occupent plus rien du tout
                # (et pas seulement leur CONTENU) — c'est précisément ce que
                # `#list_pane` corrige par rapport à l'ancien `#list`.
                self.assertEqual(list_pane.region.width, 0)
                self.assertEqual(list_pane.region.height, 0)
                self.assertEqual(folders.region.width, 0)
                self.assertEqual(folders.region.height, 0)

                panes.remove_class("fullscreen")
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
