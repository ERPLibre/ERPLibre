#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ranger un message dans un dossier choisi.

`d` ne connaît que la corbeille ; `m` ouvre la liste des dossiers du compte
et range le message dans celui qu'on désigne. C'est le geste de tri d'une
boîte, et il emprunte exactement le même chemin que la corbeille : copie,
marquage, retrait nommé.

Ce que ces tests couvrent d'abord : ce qui NE doit pas être proposé — le
dossier où le message se trouve déjà —, ce qui ne doit rien faire — Échap —
et le fait que le cache ne bouge qu'après l'accord du serveur.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class FauxTransport:
    def __init__(self, erreur=None):
        self.erreur = erreur
        self.deplacements = []

    def select(self, folder):
        pass

    def move(self, uids, target):
        if self.erreur:
            raise self.erreur
        self.deplacements.append((list(uids), target))
        return True

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class MoveCase(unittest.IsolatedAsyncioTestCase):
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
        self.store.upsert_folder("Archives", "Archives", "archive")
        self.store.upsert_folder("Projets", "Projets", None)
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=7,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid="<7@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="À ranger",
                    snippet="",
                )
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

    async def _app(self, transport=None, online=True):
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
                    Session(
                        self.account,
                        self.store,
                        FauxSyncer(transport) if online else None,
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
            unseen=0,
        )
        return app

    def _statut(self, app):
        from textual.widgets import Static

        return str(app.query_one("#status", Static).content)

    async def _ouvrir(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        return app.screen

    def _restants(self):
        return [m.uid for m in self.store.list_messages(self.inbox)]


class TestWhatTheListOffers(MoveCase):
    async def test_it_lists_the_other_folders(self):
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertEqual(sorted(ecran.dossiers), ["Archives", "Projets"])

    async def test_the_folder_we_are_in_is_not_offered(self):
        """S'y déplacer ne ferait rien, et le proposer laisse croire que
        ça ferait quelque chose."""
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            ecran = await self._ouvrir(pilot, app)
            self.assertNotIn("INBOX", ecran.dossiers)

    async def test_escape_closes_without_moving_anything(self):
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._ouvrir(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(transport.deplacements, [])
            self.assertEqual(self._restants(), [7])

    async def test_an_offline_account_never_opens_the_list(self):
        from textual.screen import ModalScreen

        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._ouvrir(pilot, app)
            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertTrue(self._statut(app))


class TestWhatItMoves(MoveCase):
    async def _choisir(self, pilot, app):
        await self._ouvrir(pilot, app)
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_the_message_goes_where_it_was_sent(self):
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app)
            self.assertEqual(len(transport.deplacements), 1)
            uids, cible = transport.deplacements[0]
            self.assertEqual(uids, [7])
            self.assertIn(cible, ("Archives", "Projets"))

    async def test_it_leaves_the_source_in_the_cache(self):
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app)
            self.assertEqual(self._restants(), [])

    async def test_a_server_that_refuses_keeps_the_message(self):
        from script.todo.mail.imap_transport import ImapError

        app = await self._app(FauxTransport(erreur=ImapError("refus")))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._choisir(pilot, app)
            self.assertIn("refus", self._statut(app))
            self.assertEqual(self._restants(), [7])


if __name__ == "__main__":
    unittest.main()
