#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le drapeau « suivi », l'étoile que tous les clients affichent.

`\\Flagged` est un drapeau système d'IMAP : ce que le client pose ici, le
téléphone et le client de bureau le montrent, et réciproquement. Il se
distingue de lu/non lu sur un point qui se voit à l'usage — on le met et on
l'enlève sur le MÊME message, d'où une bascule plutôt que deux touches.

La liste doit porter les deux marques à la fois : un message peut être non
lu ET suivi, et n'en afficher qu'une en perdrait une.
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
    def __init__(self):
        self.poses = []

    def select(self, folder):
        pass

    def store_flags(self, uid, add, remove):
        self.poses.append((uid, list(add), list(remove)))

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, transport):
        self.transport = transport


class FlaggedCase(unittest.IsolatedAsyncioTestCase):
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

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def _message(self, flags=""):
        self.store.upsert_messages(
            self.inbox,
            [
                MessageMeta(
                    uid=7,
                    date=1_780_000_000,
                    size=10,
                    flags=flags,
                    msgid="<7@e.ca>",
                    frm="ana@e.ca",
                    to="moi@x.ca",
                    subject="À suivre",
                    snippet="",
                )
            ],
        )

    def _drapeaux(self):
        return self.store.list_messages(self.inbox)[0].flags

    async def _app(self, online=True):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.transport = FauxTransport()
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
                        FauxSyncer(self.transport) if online else None,
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

    async def _basculer(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await pilot.press("asterisk")
        await pilot.pause()


class TestTheToggle(FlaggedCase):
    async def test_a_plain_message_becomes_flagged(self):
        self._message()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertTrue(is_flagged(self._drapeaux()))

    async def test_a_flagged_message_loses_it(self):
        """La même touche enlève : le suivi se met et s'ôte sur le même
        message."""
        self._message(flags="\\Flagged")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertFalse(is_flagged(self._drapeaux()))

    async def test_the_read_state_is_untouched(self):
        """Poser une étoile ne doit pas marquer le message lu au passage."""
        self._message(flags="\\Seen")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertIn("\\Seen", self._drapeaux())
            self.assertTrue(is_flagged(self._drapeaux()))

    async def test_the_server_is_told(self):
        """Un drapeau système : le téléphone et le client de bureau doivent
        le voir."""
        self._message()
        app = await self._app()
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertEqual(self.transport.poses, [(7, ["\\Flagged"], [])])

    async def test_removing_it_is_told_too(self):
        self._message(flags="\\Flagged")
        app = await self._app()
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertEqual(self.transport.poses, [(7, [], ["\\Flagged"])])

    async def test_an_offline_account_still_marks_the_cache(self):
        """Le cache vaut mieux que rien : la passe suivante portera le
        drapeau au serveur."""
        self._message()
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await self._basculer(pilot, app)
            self.assertTrue(is_flagged(self._drapeaux()))


class TestWhatTheListShows(FlaggedCase):
    def _marques(self, app, flags):
        meta = MessageMeta(
            uid=1,
            date=1,
            size=1,
            flags=flags,
            msgid="",
            frm="",
            to="",
            subject="",
            snippet="",
        )
        return app._marques(meta)

    async def test_an_unread_message_keeps_its_dot(self):
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("●", self._marques(app, ""))

    async def test_a_flagged_message_gets_a_star(self):
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIn("★", self._marques(app, "\\Seen \\Flagged"))

    async def test_unread_and_flagged_show_both(self):
        """Le point entier de deux caractères : choisir une seule marque
        en perdrait une."""
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            marques = self._marques(app, "\\Flagged")
            self.assertIn("●", marques)
            self.assertIn("★", marques)

    async def test_a_read_and_unflagged_message_shows_nothing(self):
        app = await self._app(online=False)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(self._marques(app, "\\Seen").strip(), "")


if __name__ == "__main__":
    unittest.main()
