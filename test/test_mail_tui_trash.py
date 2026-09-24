#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jeter un message depuis le client.

Le geste quotidien d'un client courriel, et celui qui manquait. `d` déplace
le message vers la corbeille du compte : rien n'est détruit, le serveur
garde ce qu'il garde, et une corbeille se vide ailleurs.

Ce que ces tests couvrent d'abord, ce sont les cas où le client doit
REFUSER et le dire : pas de corbeille chez ce fournisseur, compte hors
ligne, serveur qui n'a pas pu vider la source. Un message qui disparaît de
l'écran sans avoir bougé sur le serveur serait pire que pas de touche du
tout.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session


class FauxTransport:
    def __init__(self, vide_la_source=True, erreur=None):
        self.vide_la_source = vide_la_source
        self.erreur = erreur
        self.deplacements = []

    def select(self, folder):
        pass

    def move(self, uids, target):
        if self.erreur:
            raise self.erreur
        self.deplacements.append((list(uids), target))
        return self.vide_la_source

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class TrashCase(unittest.IsolatedAsyncioTestCase):
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
                    subject="À jeter",
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

    def _corbeille(self):
        self.store.upsert_folder("Trash", "Corbeille", "trash")

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
        # Posée seulement : `select_ref` remplit le tableau, donc exige un
        # écran monté — ce que `run_test()` fait, plus tard.
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

    async def _jeter(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    def _restants(self):
        return [m.uid for m in self.store.list_messages(self.inbox)]


class TestWhatItRefuses(TrashCase):
    async def test_without_a_trash_folder_it_says_so_and_moves_nothing(self):
        """Tous les fournisseurs n'en annoncent pas. Inventer un nom
        créerait un dossier que personne n'a demandé."""
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
            self.assertEqual(transport.deplacements, [])
            self.assertTrue(self._statut(app))
            self.assertEqual(self._restants(), [7])

    async def test_an_offline_account_is_told(self):
        self._corbeille()
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
            self.assertTrue(self._statut(app))
            self.assertEqual(self._restants(), [7])

    async def test_a_server_that_refuses_keeps_the_message_in_the_cache(self):
        """Le cache ne doit jamais devancer le serveur : un message retiré
        de l'écran alors qu'il est resté là-bas revient à la passe
        suivante, et l'utilisateur ne sait plus ce qui est vrai."""
        from script.todo.mail.imap_transport import ImapError

        self._corbeille()
        transport = FauxTransport(erreur=ImapError("serveur fâché"))
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
            self.assertIn("fâché", self._statut(app))
            self.assertEqual(self._restants(), [7])


class TestWhatItDoes(TrashCase):
    async def test_the_message_goes_to_the_trash_folder(self):
        self._corbeille()
        transport = FauxTransport()
        app = await self._app(transport)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
        self.assertEqual(transport.deplacements, [([7], "Trash")])

    async def test_it_leaves_the_cache_too(self):
        """Sans cela, le message reste à l'écran jusqu'à la prochaine passe
        et la touche paraît sans effet."""
        self._corbeille()
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
            # DANS le bloc : en sortant, l'application ferme ses sessions,
            # donc le cache, et le relire lèverait.
            self.assertEqual(self._restants(), [])

    async def test_a_source_the_server_could_not_clear_is_said(self):
        """Le serveur n'a pas UIDPLUS : le message est copié mais reste
        marqué dans le dossier d'origine. Le taire ferait passer pour un
        bogue ce qu'un autre client montrera."""
        self._corbeille()
        app = await self._app(FauxTransport(vide_la_source=False))
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)
            self.assertTrue(self._statut(app))

    async def test_an_empty_list_is_not_an_error(self):
        self._corbeille()
        self.store.purge_folder("INBOX")
        app = await self._app(FauxTransport())
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._jeter(pilot, app)


if __name__ == "__main__":
    unittest.main()
