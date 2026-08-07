#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un message livré par une synchronisation ou un envoi doit apparaître dans
la liste SANS redémarrer le client — le bug réel qui a mené à cette tâche.

L'APPEND et la synchronisation fonctionnaient déjà : après un redémarrage, le
message est là. C'était donc l'ÉCRAN qui restait périmé — `reload_folders()`
ne rafraîchissait la liste de messages que quand AUCUN dossier n'était
sélectionné, or un dossier est toujours déjà ouvert en pratique. Chaque test
ci-dessous fait tourner le VRAI chemin (`_sync`, ou l'écran de composition
via `ctrl+s`) plutôt que d'appeler `refresh_current_folder()` directement :
un test qui ne franchit pas ce seuil ne prouverait rien sur le bug observé.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import (
    FolderInfo,
    HeaderInfo,
    SelectInfo,
    Syncer,
)
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import Session


class FakeImapTransport:
    """Assez de protocole IMAP en mémoire pour faire tourner le VRAI
    `Syncer` (copie allégée de celle de `test_mail_sync.py`) : la garantie
    que ces tests prouvent qu'une synchronisation RÉELLE rafraîchit l'écran,
    pas une simulation qui écrirait directement dans le store."""

    def __init__(self):
        self.folders = {}
        self.selected = None
        self.appended = []

    def add(self, folder, uid, subject="Sujet", date=None, flags=""):
        f = self.folders.setdefault(folder, {"uidvalidity": 1, "messages": {}})
        f["messages"][uid] = HeaderInfo(
            uid=uid,
            date=date if date is not None else 1_700_000_000 + uid,
            size=100,
            flags=flags,
            msgid=f"<{uid}@x.ca>",
            frm="eux@x.ca",
            to="moi@x.ca",
            subject=subject,
        )

    def list_folders(self):
        return [FolderInfo(name=n) for n in sorted(self.folders)]

    def select(self, folder):
        self.selected = folder
        f = self.folders.setdefault(folder, {"uidvalidity": 1, "messages": {}})
        uids = list(f["messages"])
        return SelectInfo(
            uidvalidity=f["uidvalidity"],
            uidnext=(max(uids) + 1) if uids else 1,
            exists=len(uids),
        )

    def search_uids(self, since_uid):
        f = self.folders[self.selected]
        return sorted(u for u in f["messages"] if u >= since_uid)

    def fetch_headers(self, uids):
        f = self.folders[self.selected]
        return [f["messages"][u] for u in uids if u in f["messages"]]

    def fetch_flags(self, uids):
        f = self.folders[self.selected]
        return [
            (u, f["messages"][u].flags) for u in uids if u in f["messages"]
        ]

    def append(self, folder, raw, flags):
        self.appended.append((folder, raw, flags))

    def logout(self):
        pass


class RefreshCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné — comme
    `test_mail_tui_log.py` : `on_mount` lit `todo_prefs`, qui crée
    `~/.erplibre` s'il est absent."""

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
        self.imap = FakeImapTransport()
        self.syncer = Syncer(self.store, self.imap)
        self.session = Session(
            self.account, self.store, self.syncer, password="hunter2"
        )

    def tearDown(self):
        self.store.close()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

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


class TestSyncRefreshesTheOpenFolder(RefreshCase):
    async def test_a_message_that_arrives_during_sync_appears_without_restart(
        self,
    ):
        from textual.widgets import DataTable

        self.imap.add("INBOX", 1, subject="Ancien")
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 1)
            # Le dossier est déjà ouvert — l'état exact où
            # `reload_folders()` ratait le rafraîchissement de la liste.
            self.assertIsNotNone(app.current_ref)

            self.imap.add("INBOX", 2, subject="Nouveau", date=1_800_000_000)
            app._sync([self.session])
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 2)
            subjects = [table.get_row_at(i)[2] for i in range(table.row_count)]
            self.assertIn("Nouveau", subjects)


class TestSyncPreservesCursor(RefreshCase):
    async def test_cursor_follows_the_same_message_across_a_refresh(self):
        from textual.widgets import DataTable

        self.imap.add("INBOX", 1, subject="Un", date=1_000)
        self.imap.add("INBOX", 2, subject="Deux", date=2_000)
        self.imap.add("INBOX", 3, subject="Trois", date=3_000)
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 3)
            # Trié par date décroissante : Trois, Deux, Un.
            table.move_cursor(row=1)
            await pilot.pause()
            highlighted = app.current_meta()
            self.assertEqual(highlighted.subject, "Deux")

            # Un message plus récent arrive : il se glisse EN TÊTE de
            # liste — sans un suivi par UID, l'index 1 resterait
            # sélectionné mais pointerait sur un autre message.
            self.imap.add("INBOX", 4, subject="Quatre", date=4_000)
            app._sync([self.session])
            await pilot.pause()

            self.assertEqual(table.row_count, 4)
            still_highlighted = app.current_meta()
            self.assertEqual(still_highlighted.subject, "Deux")

    async def test_cursor_falls_back_sensibly_when_the_message_is_gone(self):
        from textual.widgets import DataTable

        self.imap.add("INBOX", 1, subject="Un", date=1_000)
        self.imap.add("INBOX", 2, subject="Deux", date=2_000)
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            table.move_cursor(row=0)
            await pilot.pause()
            self.assertEqual(app.current_meta().subject, "Deux")

            # UIDVALIDITY change côté serveur (boîte recréée/renumérotée) :
            # le VRAI `Syncer` vide alors le dossier (`purge_folder`) avant
            # de le repeupler — le seul mécanisme réel par lequel un
            # message connu peut disparaître du cache. « Deux » ne revient
            # pas ; « Trois » prend sa place.
            self.imap.folders["INBOX"]["uidvalidity"] = 2
            del self.imap.folders["INBOX"]["messages"][2]
            self.imap.add("INBOX", 3, subject="Trois", date=3_000)
            app._sync([self.session])
            await pilot.pause()

            # Ne doit pas lever, et doit retomber sur un état affichable —
            # celui que `DataTable.clear()` laisse déjà : en tête de liste.
            # Vérifié par le CONTENU, pas seulement le compte de lignes :
            # sans rafraîchissement du tout, la liste resterait Un + Deux
            # (même compte de lignes, même index 0) — seul le contenu
            # trahit une liste réellement rechargée.
            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 2)  # Un + Trois
            self.assertEqual(table.cursor_row, 0)
            self.assertEqual(table.get_row_at(0)[2], "Trois")


class TestSyncPreservesSearchFilter(RefreshCase):
    async def test_filtered_out_messages_stay_hidden_after_a_refresh(self):
        from textual.widgets import DataTable

        self.imap.add("INBOX", 1, subject="Alpha")
        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query = "Alpha"
            app.refresh_list()
            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 1)

            self.imap.add("INBOX", 2, subject="Beta")
            app._sync([self.session])
            await pilot.pause()

            # Le cache SOUS le filtre doit avoir bougé — sinon ce test ne
            # prouverait rien sur le rafraîchissement lui-même, seulement
            # que « Beta » reste caché, vrai aussi bien quand rien ne se
            # rafraîchit du tout.
            self.assertEqual(len(app.metas), 2)
            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 1)
            self.assertEqual(table.get_row_at(0)[2], "Alpha")


class TestRefreshWithNoFolderSelected(RefreshCase):
    async def test_does_not_raise_when_nothing_is_selected(self):
        app = await self._mounted_app(sessions=[])
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            self.assertIsNone(app.current_ref)
            app.refresh_current_folder()  # ne doit pas lever


class TestSendRefreshesTheOpenFolder(RefreshCase):
    """`deliver()` classe une copie dans Envoyés via `sync_one` après un
    envoi réussi (tâche 19) — sans le correctif de cette tâche, l'écran
    reste périmé si Envoyés est déjà ouvert au moment d'envoyer, exactement
    comme pour `_sync`."""

    class _FakeSentSyncOne:
        """`sync_one` réel écrit dans le store après l'APPEND — cette
        version fait la même écriture, sans re-simuler tout un serveur
        IMAP : seul le point sous test compte ici, le rafraîchissement de
        l'écran une fois le store à jour."""

        def __init__(self, store, transport):
            self.store = store
            self.transport = transport
            self.sync_one_calls = []

        def sync(self, progress=None):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=0, errors=[], purged=[])

        def sync_one(self, folder_name):
            from types import SimpleNamespace

            self.sync_one_calls.append(folder_name)
            fid = self.store.upsert_folder(folder_name, folder_name, "sent")
            self.store.upsert_messages(
                fid,
                [
                    MessageMeta(
                        uid=1,
                        date=1_700_000_000,
                        size=10,
                        flags="\\Seen",
                        msgid="<sent@x.ca>",
                        frm="moi@x.ca",
                        to="dest@example.com",
                        subject="Sujet",
                        snippet="",
                    )
                ],
            )
            return SimpleNamespace(new_messages=1, errors=[], folders=1)

        def fetch_body(self, folder, uid):
            return None

    class _FakeSMTPTransport:
        def quit(self):
            pass

    async def test_the_sent_folder_refreshes_after_sending(self):
        from textual.screen import ModalScreen
        from textual.widgets import DataTable, Input, TextArea

        import script.todo.mail.smtp_send as smtp_send_mod

        # Envoyés déjà connu du cache, comme après une synchronisation
        # antérieure — le scénario du rapport : l'utilisateur regarde déjà
        # ce dossier au moment d'envoyer.
        self.store.upsert_folder(
            self.account.sent_folder, self.account.sent_folder, "sent"
        )
        fake_syncer = self._FakeSentSyncOne(self.store, self.imap)
        session = Session(
            self.account, self.store, fake_syncer, password="hunter2"
        )

        app = await self._mounted_app(sessions=[session])
        orig_connect, orig_send = smtp_send_mod.connect, smtp_send_mod.send
        smtp_send_mod.connect = (
            lambda account, password: self._FakeSMTPTransport()
        )
        smtp_send_mod.send = lambda account, msg, transport: [
            "dest@example.com"
        ]
        try:
            async with app.run_test() as pilot:
                await app.workers.wait_for_complete()
                await pilot.pause()

                self.assertEqual(
                    app.current_ref.folder_name, self.account.sent_folder
                )
                table = app.query_one("#list", DataTable)
                self.assertEqual(table.row_count, 0)

                await pilot.press("c")
                await pilot.pause()
                app.screen.query_one("#to", Input).value = "dest@example.com"
                app.screen.query_one("#subject", Input).value = "Sujet"
                app.screen.query_one("#body", TextArea).text = "Corps"

                await pilot.press("ctrl+s")
                await pilot.pause()

                self.assertNotIsInstance(app.screen, ModalScreen)
                self.assertEqual(
                    fake_syncer.sync_one_calls, [self.account.sent_folder]
                )

                table = app.query_one("#list", DataTable)
                self.assertEqual(table.row_count, 1)
        finally:
            smtp_send_mod.connect = orig_connect
            smtp_send_mod.send = orig_send


if __name__ == "__main__":
    unittest.main()
