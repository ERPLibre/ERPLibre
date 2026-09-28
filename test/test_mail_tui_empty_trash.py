#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Vider la corbeille depuis le client.

`d` remplit, `D` vide. C'est le seul geste du client qui ne se répare
pas : rien ne ramènera ce qui part, ni le serveur ni la passe de
synchronisation suivante.

Ce que ces tests couvrent d'abord, c'est donc la CONFIRMATION — renoncer,
se tromper de mot, ne rien taper — parce qu'un vidage déclenché par une
frappe de trop est le défaut que ce geste ne peut pas se permettre.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class FauxTransport:
    def __init__(self, nombre=2, erreur=None):
        self.nombre = nombre
        self.erreur = erreur
        self.vidages = []

    def select(self, folder):
        pass

    def empty_folder(self, folder):
        if self.erreur:
            raise self.erreur
        self.vidages.append(folder)
        return self.nombre

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class EmptyTrashCase(unittest.IsolatedAsyncioTestCase):
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
                    uid=7,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid="<7@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="Gardé",
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

    def _corbeille(self, contenu=1):
        dossier = self.store.upsert_folder("Trash", "Corbeille", "trash")
        self.store.upsert_messages(
            dossier,
            [
                MessageMeta(
                    uid=100 + n,
                    date=1_780_000_000,
                    size=10,
                    flags="",
                    msgid=f"<{n}@e.ca>",
                    frm="bo@e.ca",
                    to="moi@x.ca",
                    subject="Jeté",
                    snippet="",
                )
                for n in range(contenu)
            ],
        )
        self.store.set_folder_state("Trash", total=contenu)
        return dossier

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

    async def _demander(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("D")
        await pilot.pause()

    async def _repondre(self, pilot, app, mot):
        from textual.widgets import Input

        await self._demander(pilot, app)
        app.screen.query_one("#empty_input", Input).value = mot
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    def _restants(self, dossier):
        return [m.uid for m in self.store.list_messages(dossier)]


class TestWhatItRefuses(EmptyTrashCase):
    async def test_without_a_trash_folder_it_says_so(self):
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._demander(pilot, app)
            self.assertEqual(transport.vidages, [])
            self.assertTrue(self._statut(app))

    async def test_an_offline_account_is_told(self):
        self._corbeille()
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._demander(pilot, app)
            self.assertTrue(self._statut(app))

    async def test_giving_up_destroys_nothing(self):
        corbeille = self._corbeille()
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._demander(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(transport.vidages, [])
            self.assertEqual(len(self._restants(corbeille)), 1)

    async def test_another_word_destroys_nothing(self):
        """La confirmation se TAPE : une touche de trop ne doit pas
        pouvoir la donner."""
        corbeille = self._corbeille()
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "oui")
            self.assertEqual(transport.vidages, [])
            self.assertEqual(len(self._restants(corbeille)), 1)

    async def test_a_server_that_refuses_keeps_the_cache(self):
        from script.todo.mail.imap_transport import ImapError

        corbeille = self._corbeille()
        app = await self._app(FauxTransport(erreur=ImapError("refus")))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "supprimer")
            self.assertIn("refus", self._statut(app))
            self.assertEqual(len(self._restants(corbeille)), 1)


class TestWhatItDestroys(EmptyTrashCase):
    async def test_it_empties_the_trash_and_nothing_else(self):
        self._corbeille()
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "supprimer")
            self.assertEqual(transport.vidages, ["Trash"])
            self.assertEqual(self._restants(self.inbox), [7])

    async def test_the_cache_follows_the_server(self):
        corbeille = self._corbeille()
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "supprimer")
            self.assertEqual(self._restants(corbeille), [])

    async def test_the_number_said_is_the_one_the_server_removed(self):
        """Le cache retarde toujours sur la corbeille : annoncer son
        compte ferait mentir le client sur ce qu'il vient de détruire."""
        self._corbeille(contenu=1)
        app = await self._app(FauxTransport(nombre=5))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "supprimer")
            self.assertIn("5", self._statut(app))

    async def test_a_trash_the_server_found_empty_is_said(self):
        self._corbeille()
        app = await self._app(FauxTransport(nombre=0))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._repondre(pilot, app, "supprimer")
            self.assertTrue(self._statut(app))


if __name__ == "__main__":
    unittest.main()
