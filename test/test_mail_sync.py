#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

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
from script.todo.mail.store import Store


class FakeImapTransport:
    """Un serveur IMAP en mémoire : assez pour exercer tout le moteur."""

    def __init__(self, folders=None):
        # {nom: {"uidvalidity": int, "messages": {uid: HeaderInfo},
        #        "bodies": {uid: bytes}}}
        self.folders = folders or {}
        self.selected = None
        self.appended = []
        self.stored_flags = []
        self.logged_out = False
        self.select_errors = set()

    # -- helpers de test ------------------------------------------------

    def add(self, folder, uid, subject="Sujet", flags="", body=b"corps"):
        f = self.folders.setdefault(
            folder, {"uidvalidity": 1, "messages": {}, "bodies": {}}
        )
        f["messages"][uid] = HeaderInfo(
            uid=uid,
            date=1000 + uid,
            size=len(body),
            flags=flags,
            msgid=f"<{uid}@x.ca>",
            frm="alice@x.ca",
            to="moi@x.ca",
            subject=subject,
        )
        f["bodies"][uid] = body

    # -- protocole ------------------------------------------------------

    def list_folders(self):
        return [FolderInfo(name=n) for n in sorted(self.folders)]

    def select(self, folder):
        if folder in self.select_errors:
            raise OSError(f"select refusé sur {folder}")
        self.selected = folder
        f = self.folders[folder]
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

    def fetch_body(self, uid):
        return self.folders[self.selected]["bodies"][uid]

    def store_flags(self, uid, add, remove):
        self.stored_flags.append((uid, tuple(add), tuple(remove)))

    def append(self, folder, raw, flags):
        self.appended.append((folder, raw, tuple(flags)))

    def logout(self):
        self.logged_out = True


class SyncCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.imap = FakeImapTransport()
        self.syncer = Syncer(self.store, self.imap)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def folder_id(self, name):
        return self.store.folder_state(name)["id"]


class TestFirstSync(SyncCase):
    def test_creates_folders(self):
        self.imap.add("INBOX", 1)
        self.imap.add("Sent", 1)
        report = self.syncer.sync()
        self.assertEqual(report.folders, 2)
        self.assertEqual(
            {f["name"] for f in self.store.folders()}, {"INBOX", "Sent"}
        )

    def test_stores_messages(self):
        self.imap.add("INBOX", 1, subject="Devis")
        self.imap.add("INBOX", 2, subject="Facture")
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 2)
        subjects = {
            m.subject
            for m in self.store.list_messages(self.folder_id("INBOX"))
        }
        self.assertEqual(subjects, {"Devis", "Facture"})

    def test_records_last_uid(self):
        self.imap.add("INBOX", 7)
        self.imap.add("INBOX", 9)
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["last_uid"], 9)

    def test_records_uidvalidity(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["uidvalidity"], 1)

    def test_counts_unseen(self):
        self.imap.add("INBOX", 1, flags="\\Seen")
        self.imap.add("INBOX", 2, flags="")
        self.syncer.sync()
        self.assertEqual(self.store.folder_state("INBOX")["unseen"], 1)

    def test_empty_folder_is_fine(self):
        self.imap.folders["INBOX"] = {
            "uidvalidity": 1,
            "messages": {},
            "bodies": {},
        }
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 0)

    def test_no_body_downloaded_during_sync(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertFalse(
            self.store.list_messages(self.folder_id("INBOX"))[0].has_body
        )


class TestIncrementalSync(SyncCase):
    def test_second_pass_fetches_only_new(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.imap.add("INBOX", 2)
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 1)

    def test_nothing_new_reports_zero(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.syncer.sync().new_messages, 0)

    def test_flags_are_refreshed(self):
        self.imap.add("INBOX", 1, flags="")
        self.syncer.sync()
        self.imap.folders["INBOX"]["messages"][1].flags = "\\Seen"
        self.syncer.sync()
        self.assertEqual(
            self.store.list_messages(self.folder_id("INBOX"))[0].flags,
            "\\Seen",
        )


class TestUidValidity(SyncCase):
    def test_change_purges_and_resyncs(self):
        self.imap.add("INBOX", 1, subject="ancien")
        self.syncer.sync()
        # Le serveur a rebâti la boîte : mêmes UID, autres messages.
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        self.imap.folders["INBOX"]["messages"][1].subject = "nouveau"
        report = self.syncer.sync()
        self.assertIn("INBOX", report.purged)
        got = self.store.list_messages(self.folder_id("INBOX"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].subject, "nouveau")

    def test_same_uidvalidity_does_not_purge(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.syncer.sync().purged, [])


class TestBatching(SyncCase):
    def test_large_folder_is_fetched_in_batches(self):
        for uid in range(1, 451):
            self.imap.add("INBOX", uid)
        calls = []
        original = self.imap.fetch_headers

        def spy(uids):
            calls.append(len(uids))
            return original(uids)

        self.imap.fetch_headers = spy
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 450)
        self.assertEqual(calls, [200, 200, 50])


class TestErrors(SyncCase):
    def test_failing_folder_does_not_stop_the_others(self):
        self.imap.add("INBOX", 1)
        self.imap.add("Archives", 1)
        self.imap.select_errors.add("Archives")
        report = self.syncer.sync()
        self.assertEqual(report.new_messages, 1)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("Archives", report.errors[0])

    def test_failing_folder_is_logged(self):
        """`report.errors` seul ne suffit pas : avant ce correctif, rien
        dans `script/todo/mail/` ne journalisait quoi que ce soit (à part un
        `_logger` déclaré mais jamais utilisé dans `secrets.py`), donc une
        panne perdue au-delà de la ligne de statut ne laissait AUCUNE
        trace."""
        self.imap.add("INBOX", 1)
        self.imap.add("Archives", 1)
        self.imap.select_errors.add("Archives")
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            self.syncer.sync()


class TestSyncOne(SyncCase):
    """`sync_one` : la sync ciblée qu'utilise `deliver()` (`tui.py`) juste
    après un APPEND réussi dans Envoyés, pour que le message parti
    apparaisse sans attendre la prochaine passe complète (voir
    `docs/superpowers/specs/2026-08-02-email-tui-design.md`, ligne 308)."""

    def test_syncs_only_the_named_folder(self):
        self.imap.add("INBOX", 1)
        self.imap.add("Sent", 1)
        report = self.syncer.sync_one("Sent")
        self.assertEqual(report.new_messages, 1)
        self.assertIsNone(self.store.folder_state("INBOX"))

    def test_report_covers_a_single_folder(self):
        self.imap.add("Sent", 1)
        self.assertEqual(self.syncer.sync_one("Sent").folders, 1)

    def test_stores_the_message(self):
        self.imap.add("Sent", 1, subject="Devis")
        self.syncer.sync_one("Sent")
        subjects = {
            m.subject for m in self.store.list_messages(self.folder_id("Sent"))
        }
        self.assertEqual(subjects, {"Devis"})

    def test_does_not_raise_when_the_folder_refuses(self):
        self.imap.folders["Sent"] = {
            "uidvalidity": 1,
            "messages": {},
            "bodies": {},
        }
        self.imap.select_errors.add("Sent")
        report = self.syncer.sync_one("Sent")  # ne doit pas lever
        self.assertEqual(len(report.errors), 1)
        self.assertIn("Sent", report.errors[0])

    def test_failure_is_logged(self):
        self.imap.folders["Sent"] = {
            "uidvalidity": 1,
            "messages": {},
            "bodies": {},
        }
        self.imap.select_errors.add("Sent")
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            self.syncer.sync_one("Sent")

    def test_does_not_erase_a_previously_known_display_or_role(self):
        """`sync_one` ne connaît que le nom du dossier : il ne doit pas
        écraser le libellé/rôle déjà appris d'un LIST complet (voir le
        COALESCE dans `store.upsert_folder`)."""
        self.imap.add("Sent", 1)
        self.syncer.sync()  # premier passage : enregistre display/role
        self.store.upsert_folder("Sent", "Envoyés", "sent")
        self.syncer.sync_one("Sent")
        state = self.store.folder_state("Sent")
        self.assertEqual(state["display"], "Envoyés")
        self.assertEqual(state["role"], "sent")


class TestProgress(SyncCase):
    def test_callback_receives_folder_and_counts(self):
        self.imap.add("INBOX", 1)
        self.imap.add("INBOX", 2)
        seen = []
        self.syncer.sync(
            progress=lambda name, done, total: seen.append((name, done, total))
        )
        self.assertEqual(seen[-1], ("INBOX", 2, 2))


class TestFetchBody(SyncCase):
    def test_downloads_and_caches(self):
        self.imap.add("INBOX", 1, body=b"From: a@x.ca\r\n\r\nBonjour Alice")
        self.syncer.sync()
        raw = self.syncer.fetch_body("INBOX", 1)
        self.assertIn(b"Bonjour Alice", raw)
        self.assertEqual(self.store.read_body("INBOX", 1), raw)

    def test_second_call_uses_the_cache(self):
        self.imap.add("INBOX", 1, body=b"corps")
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        self.imap.fetch_body = lambda uid: self.fail("le réseau a été rappelé")
        self.assertEqual(self.syncer.fetch_body("INBOX", 1), b"corps")

    def test_marks_has_body(self):
        self.imap.add("INBOX", 1)
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        self.assertTrue(
            self.store.list_messages(self.folder_id("INBOX"))[0].has_body
        )

    def test_snippet_survives_an_unknown_charset(self):
        """Un charset bidon ne doit pas faire tomber l'ouverture du message."""
        from script.todo.mail.imap_sync import snippet_from_raw

        raw = (
            b'Content-Type: text/plain; charset="bogus-charset-xyz"\r\n\r\n'
            b"Bonjour Alice"
        )
        self.assertIn("Bonjour", snippet_from_raw(raw))

    def test_snippet_survives_unknown_8bit(self):
        """Étiquette réelle observée en usage (voir `decode_header_value` /
        `script/todo/mail/charset.py`), pas seulement un charset inventé."""
        from script.todo.mail.imap_sync import snippet_from_raw

        raw = (
            b'Content-Type: text/plain; charset="unknown-8bit"\r\n\r\n'
            b"Bonjour Alice"
        )
        self.assertIn("Bonjour", snippet_from_raw(raw))

    def test_fills_the_snippet(self):
        self.imap.add(
            "INBOX", 1, body=b"Subject: Devis\r\n\r\nBonjour, voici le devis."
        )
        self.syncer.sync()
        self.syncer.fetch_body("INBOX", 1)
        snippet = self.store.list_messages(self.folder_id("INBOX"))[0].snippet
        self.assertIn("Bonjour", snippet)


if __name__ == "__main__":
    unittest.main()
