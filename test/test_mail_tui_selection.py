#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Agir sur plusieurs messages à la fois.

Chaque touche portait sur un seul message : archiver cinquante messages
coûtait cent frappes. `x` coche, et `d`, `m`, `s`, `u`, `*` agissent
alors sur ce qui est coché.

Ce que ces tests fixent d'abord : sans rien de coché, une touche agit
toujours sur le message sous le curseur — sinon le geste à un seul message
coûterait une frappe de PLUS qu'avant. Et ce qui a été traité cesse d'être
coché : le garder ferait agir la touche suivante sur des messages déjà
partis, dont les UID ne valent plus rien dans leur dossier d'origine.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session
from script.todo.mail.tui_text import is_flagged


class FauxTransport:
    def __init__(self, erreur=None):
        self.erreur = erreur
        self.deplacements = []
        self.drapeaux = []

    def select(self, folder):
        pass

    def move(self, uids, target):
        if self.erreur:
            raise self.erreur
        self.deplacements.append((sorted(uids), target))
        return True

    def store_flags(self, uid, add, remove):
        self.drapeaux.append((uid, list(add), list(remove)))

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class SelectionCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.store.upsert_folder("Archives", "Archives", None)
        self.store.upsert_folder("Trash", "Corbeille", "trash")
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=u,
                    date=1_780_000_000 - u,
                    size=10,
                    flags="",
                    msgid=f"<{u}@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject=f"Message {u}",
                    snippet="",
                )
                for u in (1, 2, 3)
            ],
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    async def _app(self, transport=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.transport = transport or FauxTransport()
        captured = []
        orig = textual.app.App.__init__

        def cap(app_self, *a, **k):
            orig(app_self, *a, **k)
            captured.append(app_self)

        textual.app.App.__init__ = cap
        try:
            run_tui(
                run_app=False,
                sessions=[
                    Session(
                        self.account,
                        self.store,
                        FauxSyncer(self.transport),
                        password="x",
                    )
                ],
            )
        finally:
            textual.app.App.__init__ = orig
        app = captured[-1]
        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=3,
        )
        return app

    async def _ouvrir(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()

    async def _cocher(self, pilot, app, combien):
        """Coche `combien` messages à partir du haut, en rafale."""
        from textual.widgets import DataTable

        app.query_one("#list", DataTable).move_cursor(row=0)
        await pilot.pause()
        for _ in range(combien):
            await pilot.press("x")
            await pilot.pause()

    def _restants(self):
        return sorted(m.uid for m in self.store.list_messages(self.inbox))

    def _statut(self, app):
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)


class TestTheSelectionItself(SelectionCase):
    async def test_x_selects_the_message_under_the_cursor(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 1)
            self.assertEqual(len(app.selection), 1)

    async def test_the_cursor_moves_on_so_it_can_be_done_in_a_run(self):
        """Remonter d'une ligne après chaque coche serait le geste le plus
        fatigant de l'écran."""
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 1)
            self.assertEqual(app.query_one("#list", DataTable).cursor_row, 1)

    async def test_pressing_it_twice_unselects(self):
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 1)
            app.query_one("#list", DataTable).move_cursor(row=0)
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            self.assertEqual(app.selection, {})

    async def test_the_count_is_said(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            self.assertIn("2", self._statut(app))

    async def test_a_selected_row_is_marked(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 1)
            premier = app.metas[0]
            self.assertIn("✓", app._marques(premier))
            self.assertNotIn("✓", app._marques(app.metas[2]))


class TestWhatTheKeysActOn(SelectionCase):
    async def test_without_a_selection_it_is_the_cursor(self):
        """Sinon le geste à un seul message coûterait une frappe de plus
        qu'avant."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            cibles = app.cibles()
            self.assertEqual(len(cibles), 1)
            self.assertEqual(cibles[0].uid, app.metas[0].uid)

    async def test_with_a_selection_it_is_the_selection(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            self.assertEqual(len(app.cibles()), 2)


class TestTrashingAndFilingABatch(SelectionCase):
    async def test_the_whole_batch_goes_in_one_move(self):
        """Un dossier, un COPY : cinquante allers-retours pour cinquante
        messages du même dossier seraient cinquante fois l'attente."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(self.transport.deplacements, [([1, 2], "Trash")])

    async def test_the_cache_loses_exactly_them(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(self._restants(), [3])

    async def test_the_selection_is_cleared_afterwards(self):
        """La garder ferait agir la touche suivante sur des UID qui ne
        valent plus rien dans leur dossier d'origine."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(app.selection, {})

    async def test_a_refusal_keeps_everything(self):
        from script.todo.mail.imap_transport import ImapError

        app = await self._app(FauxTransport(erreur=ImapError("refus")))
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIn("refus", self._statut(app))
            self.assertEqual(self._restants(), [1, 2, 3])


class TestFlaggingABatch(SelectionCase):
    async def test_every_selected_message_is_marked_read(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("s")
            await pilot.pause()
            self.assertEqual(self.store.count_unseen(self.inbox), 1)

    async def test_the_server_hears_about_each_one(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("s")
            await pilot.pause()
            self.assertEqual(
                sorted(u for u, _, _ in self.transport.drapeaux), [1, 2]
            )

    async def test_a_mixed_batch_becomes_all_flagged(self):
        """Le sens de la bascule est celui du GROUPE : basculer chacun de
        son côté rendrait le résultat imprévisible."""
        self.store.update_flags(self.inbox, 1, "\\Flagged")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("asterisk")
            await pilot.pause()
            suivis = [
                is_flagged(m.flags)
                for m in self.store.list_messages(self.inbox)
                if m.uid in (1, 2)
            ]
            self.assertTrue(all(suivis))

    async def test_an_all_flagged_batch_is_unflagged(self):
        for uid in (1, 2):
            self.store.update_flags(self.inbox, uid, "\\Flagged")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await self._cocher(pilot, app, 2)
            await pilot.press("asterisk")
            await pilot.pause()
            suivis = [
                is_flagged(m.flags)
                for m in self.store.list_messages(self.inbox)
                if m.uid in (1, 2)
            ]
            self.assertFalse(any(suivis))


if __name__ == "__main__":
    unittest.main()
