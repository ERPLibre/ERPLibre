#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La liste d'un dossier arrive par pages.

Elle s'arrêtait à 500 messages sans le dire : le dossier paraissait plus
court qu'il n'était, la recherche trouvait des messages que le parcours ne
montrait pas, et rien n'expliquait l'écart.

Tout charger d'un coup n'est pas la réponse : une boîte de trente mille
messages construirait trente mille lignes à chaque ouverture. Le dossier
arrive donc par pages, et c'est le curseur approchant du bas qui appelle la
suivante.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MARGE_PAGE, PAGE, MailboxRef, Session


def message(uid):
    return MessageMeta(
        uid=uid,
        # Décroissante avec l'UID : le plus récent d'abord, comme la liste
        # les ordonne.
        date=2_000_000_000 - uid,
        size=10,
        flags="",
        msgid=f"<{uid}@e.ca>",
        frm="ana@e.ca",
        to="moi@x.ca",
        subject=f"Message {uid}",
        snippet="",
    )


class PagingCase(unittest.IsolatedAsyncioTestCase):
    COMBIEN = PAGE + 120

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
        self.store.upsert_messages(
            self.inbox, [message(u) for u in range(1, self.COMBIEN + 1)]
        )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    async def _app(self):
        import textual.app

        from script.todo.mail.tui import run_tui

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
                    Session(self.account, self.store, None, password="x")
                ],
            )
        finally:
            textual.app.App.__init__ = orig
        app = captured[-1]
        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=0,
        )
        return app

    async def _ouvrir(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()


class TestTheFirstPage(PagingCase):
    async def test_only_one_page_is_loaded_at_first(self):
        """Ouvrir un dossier ne doit pas construire une ligne par message."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(len(app.metas), PAGE)

    async def test_the_newest_come_first(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(app.metas[0].uid, 1)

    async def test_what_is_left_in_the_cache_is_known(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(app.reste_a_charger(), self.COMBIEN - PAGE)


class TestLoadingTheNextPage(PagingCase):
    async def test_the_cursor_near_the_bottom_brings_it(self):
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            table = app.query_one("#list", DataTable)
            table.move_cursor(row=PAGE - MARGE_PAGE)
            await pilot.pause()
            self.assertGreater(len(app.metas), PAGE)

    async def test_the_cursor_high_up_brings_nothing(self):
        """Charger à chaque déplacement lirait le cache pour rien."""
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            app.query_one("#list", DataTable).move_cursor(row=10)
            await pilot.pause()
            self.assertEqual(len(app.metas), PAGE)

    async def test_the_cursor_stays_where_it_was(self):
        """La page arrive SOUS le curseur : le ramener en tête de liste
        renverrait au début quiconque descend."""
        from textual.widgets import DataTable

        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            table = app.query_one("#list", DataTable)
            vise = PAGE - MARGE_PAGE + 2
            table.move_cursor(row=vise)
            await pilot.pause()
            self.assertEqual(table.cursor_row, vise)

    async def test_the_whole_folder_ends_up_reachable(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            while app.charger_la_suite():
                pass
            self.assertEqual(len(app.metas), self.COMBIEN)
            self.assertEqual(app.reste_a_charger(), 0)

    async def test_the_end_of_the_folder_stops_asking(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            while app.charger_la_suite():
                pass
            self.assertFalse(app.charger_la_suite())

    async def test_a_search_does_not_page(self):
        """Avec une requête, la liste n'est plus le dossier mais le
        résultat, qui a son propre plafond."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            app.query = "message"
            self.assertFalse(app.charger_la_suite())


class TestAfterASync(PagingCase):
    async def test_the_depth_survives_a_refresh(self):
        """Une passe de synchronisation ne doit pas rendre à la liste la
        taille d'une page, sous un curseur descendu bien plus bas."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            app.charger_la_suite()
            avant = len(app.metas)
            app.refresh_current_folder()
            await pilot.pause()
            self.assertEqual(len(app.metas), avant)

    async def test_an_empty_folder_is_not_an_error(self):
        self.store.purge_folder("INBOX")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(app.metas, [])
            self.assertFalse(app.charger_la_suite())
            self.assertEqual(app.reste_a_charger(), 0)


if __name__ == "__main__":
    unittest.main()
