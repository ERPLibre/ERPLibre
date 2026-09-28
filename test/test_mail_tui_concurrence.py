#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une seule connexion IMAP, et tout ce qui lui parle prend le verrou.

`imaplib` n'est pas sûr entre fils. Le client garde UNE connexion par
compte, et les fils de travail — synchronisation, rangement, corbeille,
marquage, recherche serveur — prennent `_sync_lock` avant d'échanger.
L'aperçu d'un message, lui, parlait au serveur depuis le fil de
l'interface, sans verrou : deux dialogues sur une même socket, l'un lisant
la réponse de l'autre, et trente secondes plus tard un délai dépassé qui
condamne le lien pour toute la session.

Deux fils partageant un vrai lien le montrent : l'un lève « abort command:
UID => unexpected response », l'autre « timed out ».

L'autre moitié de la réparation est la REPRISE : elle ne vivait que dans
la passe de synchronisation, donc un lien mort laissait `m`, `d`, `D`,
`Shift+M` et `Shift+S` cassés jusqu'à ce qu'une passe le remplace.
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import MailboxRef, Session

CORPS = (
    b"From: ana@e.ca\r\nTo: moi@x.ca\r\nSubject: Question\r\n"
    b"Message-ID: <7@e.ca>\r\n\r\nle corps\r\n"
)


class FauxTransport:
    """Un lien qui note QUI le tient quand on lui parle."""

    def __init__(self, verrou=None, morts=0):
        self.verrou = verrou
        # Nombre d'échanges qui échoueront comme une socket morte avant que
        # le lien ne se mette à répondre.
        self.morts = morts
        self.sans_verrou = []
        self.echanges = []

    def _noter(self, quoi):
        self.echanges.append(quoi)
        if self.verrou is not None and not self.verrou.tenu():
            self.sans_verrou.append(quoi)
        if self.morts:
            self.morts -= 1
            raise OSError("cannot read from timed out object")

    def select(self, folder):
        self._noter(("select", folder))

    def fetch_body(self, uid):
        self._noter(("fetch_body", uid))
        return CORPS

    def store_flags(self, uid, add, remove):
        self._noter(("store_flags", uid))

    def store_flags_all(self, add, remove):
        self._noter(("store_flags_all",))

    def move(self, uids, target):
        self._noter(("move", tuple(uids), target))
        return True

    def empty_folder(self, folder):
        self._noter(("empty_folder", folder))
        return 1

    def logout(self):
        pass


class VerrouEspion:
    """Un `RLock` qui sait dire s'il est tenu par le fil courant."""

    def __init__(self):
        self._verrou = threading.RLock()
        self._tenu = set()

    def __enter__(self):
        self._verrou.acquire()
        self._tenu.add(threading.get_ident())
        return self

    def __exit__(self, *exc):
        self._tenu.discard(threading.get_ident())
        self._verrou.release()
        return False

    def tenu(self) -> bool:
        return threading.get_ident() in self._tenu


class FauxSyncer:
    def __init__(self, transport, store, dossier="INBOX"):
        self.transport = transport
        self.store = store
        self.dossier = dossier

    def fetch_body(self, folder, uid):
        # Comme le vrai : il passe par le transport, donc par la socket.
        self.transport.select(folder)
        raw = self.transport.fetch_body(uid)
        self.store.write_body(folder, uid, raw)
        return raw

    def sync_one(self, folder):
        pass


class ConcurrenceCase(unittest.IsolatedAsyncioTestCase):
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
        self.store.upsert_folder("Trash", "Corbeille", "trash")
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
                    subject="Question",
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

    async def _app(self, morts=0):
        import textual.app

        from script.todo.mail.tui import run_tui

        self.verrou = VerrouEspion()
        self.transport = FauxTransport(self.verrou, morts=morts)
        self.ouvertures = []

        def connect_fn(account, secret):
            lien = FauxTransport(self.verrou)
            self.ouvertures.append(lien)
            self.session.syncer.transport = lien
            return lien

        self.session = Session(
            self.account,
            self.store,
            FauxSyncer(self.transport, self.store),
            password="x",
            connect_fn=connect_fn,
        )
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
        app._sync_lock = self.verrou
        app.current_ref = MailboxRef(
            account_name="perso",
            folder_name="INBOX",
            display="Boîte",
            unseen=1,
        )
        return app

    async def _ouvrir(self, pilot, app):
        app.select_ref(app.current_ref)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()


class TestNothingTalksWithoutTheLock(ConcurrenceCase):
    async def test_the_preview_fetches_under_the_lock(self):
        """Le défaut d'origine : ce téléchargement partait du fil de
        l'interface, sans verrou, sur la socket d'une passe en cours."""
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertIn(("fetch_body", 7), self.transport.echanges)
            self.assertEqual(self.transport.sans_verrou, [])

    async def test_marking_read_talks_under_the_lock(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertIn(("store_flags", 7), self.transport.echanges)
            self.assertEqual(self.transport.sans_verrou, [])

    async def test_flagging_talks_under_the_lock(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("asterisk")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(self.transport.sans_verrou, [])

    async def test_trashing_talks_under_the_lock(self):
        app = await self._app()
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(self.transport.sans_verrou, [])


class TestEveryGestureSurvivesADeadLink(ConcurrenceCase):
    """La reprise ne vivait que dans la passe de synchronisation.

    Un lien mort laissait donc tous les autres gestes échouer jusqu'à ce
    qu'une passe le remplace — et rien ne disait qu'il suffisait de
    synchroniser.
    """

    async def test_the_preview_reopens_the_link(self):
        app = await self._app(morts=1)
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertEqual(len(self.ouvertures), 1)
            self.assertIsNotNone(self.store.read_body("INBOX", 7))

    async def test_trashing_reopens_the_link(self):
        app = await self._app(morts=1)
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.ouvertures.clear()
            self.session.syncer.transport.morts = 1
            await pilot.press("d")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            self.assertEqual(len(self.ouvertures), 1)
            self.assertEqual(
                [m.uid for m in self.store.list_messages(self.inbox)], []
            )

    async def test_the_new_link_is_the_one_used_afterwards(self):
        """Rouvrir sans donner le lien neuf au moteur laisserait le geste
        suivant repartir sur le mort."""
        app = await self._app(morts=1)
        async with app.run_test() as pilot:
            await self._ouvrir(pilot, app)
            self.assertIs(self.session.syncer.transport, self.ouvertures[-1])


if __name__ == "__main__":
    unittest.main()
