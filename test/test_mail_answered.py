#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""`\\Answered` sur l'original d'une réponse MANUELLE, et envoi hors du fil
de l'interface.

Une réponse partie en ligne pose le drapeau sur le serveur et dans le
cache, en gardant ceux qui y étaient ; hors ligne (message mis en file) ou
pour un transfert, rien n'est posé. L'envoi lui-même tourne dans un fil de
travail : sur le fil de l'interface, l'attente du verrou d'une passe en
cours gèlerait l'application.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUT = (
    f"From: Carole <{CAROLE}>\r\nTo: {OWN}\r\nSubject: Question\r\n"
    "Message-ID: <7@example.org>\r\n\r\nUne question.\r\n"
).encode()


class FauxTransport:
    def __init__(self):
        self.stored_flags = []
        self.appended = []

    def select(self, folder):
        pass

    def store_flags(self, uid, add, remove):
        self.stored_flags.append((uid, tuple(add), tuple(remove)))

    def append(self, folder, raw, flags):
        self.appended.append(folder)

    def logout(self):
        pass


class FauxSyncer:
    def __init__(self, store):
        self.transport = FauxTransport()
        self.store = store

    def sync_one(self, folder):
        pass

    def sync(self, progress=None):
        from script.todo.mail.imap_sync import SyncReport

        return SyncReport()


class FauxSmtp:
    def quit(self):
        pass


class AnsweredCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", OWN, "generic")
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
                    size=len(BRUT),
                    flags="\\Seen \\Flagged",
                    msgid="<7@example.org>",
                    frm=CAROLE,
                    to=OWN,
                    subject="Question",
                    snippet="",
                )
            ],
        )
        self.store.write_body("INBOX", 7, BRUT)
        self.syncer = FauxSyncer(self.store)
        self.session = Session(
            self.account, self.store, self.syncer, password="x"
        )
        patcheurs = [
            mock.patch(
                "script.todo.mail.smtp_send.connect",
                lambda account, secret: FauxSmtp(),
            ),
            mock.patch(
                "script.todo.mail.smtp_send.send",
                lambda account, msg, transport: [CAROLE],
            ),
        ]
        for patcheur in patcheurs:
            patcheur.start()
            self.addCleanup(patcheur.stop)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

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
            run_tui(run_app=False, sessions=[self.session])
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

    async def _attendre(self, pilot, app):
        for _ in range(5):
            await app.workers.wait_for_complete()
            await pilot.pause()

    async def _repondre(self, touche="a"):
        from textual.screen import ModalScreen

        app = await self._app()
        async with app.run_test() as pilot:
            await self._attendre(pilot, app)
            app.select_ref(app.current_ref)
            await self._attendre(pilot, app)
            await pilot.press(touche)
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)
            if touche == "f":
                from textual.widgets import Input

                app.screen.query_one("#to", Input).value = CAROLE
            await pilot.press("ctrl+s")
            await self._attendre(pilot, app)
            self.assertNotIsInstance(app.screen, ModalScreen)
            # L'application ferme les caches en sortant : lu avant.
            self.flags_apres = set(
                self.store.list_messages(self.inbox)[0].flags.split()
            )
            self.file_apres = len(self.store.outbox())
        return app

    def drapeaux_en_cache(self):
        return self.flags_apres


class TestManualReplySetsAnswered(AnsweredCase):
    async def test_online_reply_flags_server_and_cache(self):
        await self._repondre()
        self.assertIn(
            (7, ("\\Answered",), ()), self.syncer.transport.stored_flags
        )
        self.assertEqual(
            self.drapeaux_en_cache(), {"\\Seen", "\\Flagged", "\\Answered"}
        )

    async def test_offline_reply_sets_nothing(self):
        self.session.syncer = None
        await self._repondre()
        self.assertEqual(self.syncer.transport.stored_flags, [])
        self.assertEqual(self.drapeaux_en_cache(), {"\\Seen", "\\Flagged"})
        self.assertEqual(self.file_apres, 1)

    async def test_forward_sets_nothing(self):
        await self._repondre("f")
        self.assertEqual(self.syncer.transport.stored_flags, [])
        self.assertNotIn("\\Answered", self.drapeaux_en_cache())


class TestSendRunsOffTheUiThread(AnsweredCase):
    async def test_deliver_is_called_from_a_worker_thread(self):
        fils = []

        def espion(session, msg, verrou=None, **kw):
            fils.append(threading.current_thread())
            return "ok"

        with mock.patch("script.todo.mail.tui.deliver", espion):
            await self._repondre()
        self.assertEqual(len(fils), 1)
        self.assertIsNot(fils[0], threading.main_thread())


class TestComposeWhileSending(AnsweredCase):
    """Pendant l'envoi, le brouillon ne se ferme pas et ne repart pas ;
    après un succès, il ne peut plus repartir."""

    def setUp(self):
        super().setUp()
        self.libere = threading.Event()
        self.appels = []

        def lent(session, msg, verrou=None, **kw):
            self.appels.append(msg)
            self.libere.wait(5)
            return "ok"

        patcheur = mock.patch("script.todo.mail.tui.deliver", lent)
        patcheur.start()
        self.addCleanup(patcheur.stop)
        self.addCleanup(self.libere.set)

    async def _ouvrir(self, pilot, app):
        await self._attendre(pilot, app)
        app.select_ref(app.current_ref)
        await self._attendre(pilot, app)
        await pilot.press("a")
        await pilot.pause()
        return app.screen

    async def _envoi_lance(self, pilot):
        import asyncio

        await pilot.press("ctrl+s")
        for _ in range(100):
            if self.appels:
                return
            await asyncio.sleep(0.01)
        self.fail("deliver n'a pas été appelé")

    async def test_escape_and_a_second_send_are_ignored(self):
        from textual.widgets import Button

        app = await self._app()
        async with app.run_test() as pilot:
            compose = await self._ouvrir(pilot, app)
            await self._envoi_lance(pilot)
            self.assertTrue(compose.query_one("#send", Button).disabled)
            await pilot.press("escape")
            await pilot.press("ctrl+s")
            await pilot.pause()
            self.assertIs(app.screen, compose)
            self.libere.set()
            await self._attendre(pilot, app)
            self.assertIsNot(app.screen, compose)
        self.assertEqual(len(self.appels), 1)

    async def test_a_send_finished_under_another_screen_closes_on_return(
        self,
    ):
        from textual.screen import ModalScreen

        class Dessus(ModalScreen):
            pass

        app = await self._app()
        async with app.run_test() as pilot:
            compose = await self._ouvrir(pilot, app)
            await self._envoi_lance(pilot)
            app.push_screen(Dessus())
            await pilot.pause()
            self.libere.set()
            await self._attendre(pilot, app)
            self.assertIn(compose, app.screen_stack)
            compose.action_send()
            app.pop_screen()
            await self._attendre(pilot, app)
            self.assertNotIn(compose, app.screen_stack)
        self.assertEqual(len(self.appels), 1)


if __name__ == "__main__":
    unittest.main()
