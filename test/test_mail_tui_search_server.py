#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Étendre une recherche au serveur, depuis le client.

`/` cherche dans le cache et répond tout de suite. Une touche de plus pose
la même question au serveur, pour le dossier ouvert : c'est le seul moyen
de retrouver un message plus ancien que ce qui a été téléchargé.

Le geste est explicite, et il le reste : étendre à chaque frappe ferait
payer un aller-retour réseau à une recherche qui répond déjà.

Ce que ces tests couvrent surtout, ce sont les refus — pas de terme, compte
hors ligne, serveur qui ne trouve rien. Chacun doit se DIRE : une touche
qui ne fait rien en silence se lit comme une touche cassée.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class FauxTransport:
    """Le lien réseau d'une session, réduit à ce que l'extension emploie."""

    def __init__(self, uids=(), erreur=None):
        self.uids = list(uids)
        self.erreur = erreur
        self.selections = []
        self.recherches = []

    def select(self, folder):
        self.selections.append(folder)

    def search(self, query, limit=500):
        self.recherches.append(query)
        if self.erreur:
            raise self.erreur
        return list(self.uids)

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport, ramenes=0):
        self.transport = transport
        self.ramenes = ramenes
        self.demandes = []

    def fetch_uids(self, folder, uids):
        self.demandes.append((folder, list(uids)))
        return self.ramenes


class ServerSearchCase(unittest.IsolatedAsyncioTestCase):
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
            self.inbox,
            [
                MessageMeta(
                    uid=1,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid="<1@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="Devis",
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

    async def _app(self, syncer=None):
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
                    Session(self.account, self.store, syncer, password="x")
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

    async def _chercher(self, pilot, app, terme):
        app.query = terme
        await pilot.press("S")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()


class TestWhatItRefuses(ServerSearchCase):
    async def test_without_a_term_it_says_so_and_asks_nothing(self):
        """Une touche qui ne fait rien en silence se lit comme une touche
        cassée."""
        transport = FauxTransport(uids=[7])
        app = await self._app(FauxSyncer(transport))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "")
            self.assertEqual(transport.recherches, [])
            self.assertTrue(self._statut(app))

    async def test_an_offline_account_is_told_not_left_waiting(self):
        app = await self._app(syncer=None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "devis")
            self.assertTrue(self._statut(app))

    async def test_a_server_that_refuses_does_not_take_down_the_client(self):
        from script.todo.mail.imap_transport import ImapError

        transport = FauxTransport(erreur=ImapError("serveur fâché"))
        app = await self._app(FauxSyncer(transport))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "devis")
            self.assertIn("fâché", self._statut(app))


class TestWhatItBringsBack(ServerSearchCase):
    async def test_it_asks_the_server_about_the_open_folder(self):
        transport = FauxTransport(uids=[7, 8])
        syncer = FauxSyncer(transport, ramenes=2)
        app = await self._app(syncer)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "devis")
        self.assertEqual(transport.recherches, ["devis"])
        self.assertEqual(transport.selections, ["INBOX"])
        self.assertEqual(syncer.demandes, [("INBOX", [7, 8])])

    async def test_the_count_it_brought_back_is_said(self):
        transport = FauxTransport(uids=[7, 8])
        app = await self._app(FauxSyncer(transport, ramenes=2))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "devis")
            self.assertIn("2", self._statut(app))

    async def test_finding_nothing_more_is_said_too(self):
        """« Rien de plus » est une réponse : sans elle, l'utilisateur ne
        sait pas si la question est partie."""
        transport = FauxTransport(uids=[])
        app = await self._app(FauxSyncer(transport, ramenes=0))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "zzzz")
            self.assertTrue(self._statut(app))

    async def test_the_term_is_kept_so_the_list_shows_what_arrived(self):
        """Ce que le serveur ramène entre dans le cache : la recherche
        locale doit donc le trouver juste après, sans rien retaper."""
        transport = FauxTransport(uids=[7])
        app = await self._app(FauxSyncer(transport, ramenes=1))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._chercher(pilot, app, "devis")
            self.assertEqual(app.query, "devis")


if __name__ == "__main__":
    unittest.main()
