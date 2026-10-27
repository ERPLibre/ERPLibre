#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les en-têtes des nouveaux messages d'INBOX, rendus par `SyncReport`.

Les règles de courriel entrant lisent ce que la passe vient de télécharger
au lieu de refaire un FETCH. Ce que ces tests figent : seule la boîte de
réception alimente le rapport, seulement par ses UID nouveaux, au plus
`INBOX_REPORT_MAX` en-têtes, et ni `sync_one` ni `fetch_uids` n'y
contribuent.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_mail_sync import FakeImapTransport

from script.todo.mail import imap_sync
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import (
    FolderInfo,
    HeaderInfo,
    Syncer,
    SyncReport,
    is_inbox,
)
from script.todo.mail.store import Store

RECU = 1785924000


class TransportARoles(FakeImapTransport):
    """`FakeImapTransport` dont les dossiers peuvent porter un rôle."""

    def __init__(self, folders=None, roles=None):
        super().__init__(folders)
        self.roles = roles or {}

    def list_folders(self):
        return [
            FolderInfo(name=n, role=self.roles.get(n))
            for n in sorted(self.folders)
        ]

    def ajouter(self, folder, uid, **champs):
        """Un message dont l'en-tête porte les champs v6."""
        self.add(folder, uid, subject=f"Sujet {uid}")
        entete = self.folders[folder]["messages"][uid]
        entete.internaldate = champs.get("internaldate", RECU + uid)
        entete.cc = champs.get("cc", "")
        entete.extra = champs.get("extra", {})


class InboxCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset(
            "perso", "boite.regles@example.org", "generic"
        )
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.imap = TransportARoles()
        self.syncer = Syncer(self.store, self.imap)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def stockes(self, dossier):
        fid = self.store.folder_state(dossier)["id"]
        return {m.uid: m for m in self.store.list_messages(fid)}


class TestIsInbox(unittest.TestCase):
    def test_the_inbox_role_is_enough(self):
        self.assertTrue(is_inbox(FolderInfo(name="Réception", role="inbox")))

    def test_the_name_is_enough_whatever_its_case(self):
        self.assertTrue(is_inbox(FolderInfo(name="Inbox")))

    def test_another_folder_is_not_the_inbox(self):
        self.assertFalse(is_inbox(FolderInfo(name="Sent", role="sent")))


class TestOnlyTheInboxFillsTheReport(InboxCase):
    def test_new_inbox_uids_are_reported_by_name(self):
        for uid in (1, 2, 3):
            self.imap.ajouter("INBOX", uid)
        rapport = self.syncer.sync()
        self.assertEqual(rapport.inbox_folder, "INBOX")
        self.assertEqual([h.uid for h in rapport.inbox], [1, 2, 3])
        self.assertFalse(rapport.inbox_truncated)

    def test_new_inbox_uids_are_reported_by_role(self):
        """Un serveur peut nommer sa boîte de réception autrement : son
        rôle suffit."""
        self.imap.roles = {"Reception": "inbox"}
        self.imap.ajouter("Reception", 4)
        rapport = self.syncer.sync()
        self.assertEqual(rapport.inbox_folder, "Reception")
        self.assertEqual([h.uid for h in rapport.inbox], [4])

    def test_the_sent_folder_does_not_enter_the_report(self):
        self.imap.roles = {"Sent": "sent"}
        self.imap.ajouter("Sent", 9)
        self.imap.ajouter("INBOX", 1)
        rapport = self.syncer.sync()
        self.assertEqual([h.uid for h in rapport.inbox], [1])

    def test_a_folder_without_inbox_leaves_the_report_empty(self):
        self.imap.ajouter("Archives", 1)
        rapport = self.syncer.sync()
        self.assertEqual((rapport.inbox_folder, rapport.inbox), ("", []))

    def test_only_uids_new_to_this_pass_are_reported(self):
        self.imap.ajouter("INBOX", 1)
        self.syncer.sync()
        self.imap.ajouter("INBOX", 2)
        rapport = self.syncer.sync()
        self.assertEqual([h.uid for h in rapport.inbox], [2])

    def test_a_pass_without_arrival_reports_nothing(self):
        self.imap.ajouter("INBOX", 1)
        self.syncer.sync()
        self.assertEqual(self.syncer.sync().inbox, [])

    def test_the_reported_headers_keep_the_v6_fields(self):
        self.imap.ajouter(
            "INBOX",
            1,
            cc="bruno.filtre@example.net",
            extra={"auto-submitted": "auto-replied"},
        )
        entete = self.syncer.sync().inbox[0]
        self.assertEqual(entete.cc, "bruno.filtre@example.net")
        self.assertEqual(entete.internaldate, RECU + 1)
        self.assertEqual(entete.extra, {"auto-submitted": "auto-replied"})


class TestTheReportIsCapped(InboxCase):
    def test_only_the_highest_uids_are_kept_in_order(self):
        """Les lots coupent en cours de route : le résultat est le même
        que si l'on triait tout à la fin."""
        self.syncer.BATCH = 4
        for uid in range(1, 13):
            self.imap.ajouter("INBOX", uid)
        with patch.object(imap_sync, "INBOX_REPORT_MAX", 5):
            rapport = self.syncer.sync()
        self.assertEqual([h.uid for h in rapport.inbox], [8, 9, 10, 11, 12])
        self.assertTrue(rapport.inbox_truncated)

    def test_exactly_the_cap_is_not_a_truncation(self):
        for uid in range(1, 6):
            self.imap.ajouter("INBOX", uid)
        with patch.object(imap_sync, "INBOX_REPORT_MAX", 5):
            rapport = self.syncer.sync()
        self.assertEqual(len(rapport.inbox), 5)
        self.assertFalse(rapport.inbox_truncated)

    def test_the_real_cap_bounds_a_first_synchronisation(self):
        for uid in range(1, imap_sync.INBOX_REPORT_MAX + 2):
            self.imap.ajouter("INBOX", uid)
        rapport = self.syncer.sync()
        self.assertEqual(len(rapport.inbox), imap_sync.INBOX_REPORT_MAX)
        self.assertEqual(rapport.inbox[0].uid, 2)
        self.assertTrue(rapport.inbox_truncated)

    def test_the_cache_still_receives_every_message(self):
        """Le plafond borne le RAPPORT, jamais ce que le cache reçoit."""
        for uid in range(1, 13):
            self.imap.ajouter("INBOX", uid)
        with patch.object(imap_sync, "INBOX_REPORT_MAX", 5):
            self.syncer.sync()
        self.assertEqual(len(self.stockes("INBOX")), 12)


class TestParallelMerge(InboxCase):
    def _copie(self):
        return TransportARoles(
            {
                nom: {
                    "uidvalidity": f["uidvalidity"],
                    "messages": dict(f["messages"]),
                    "bodies": dict(f["bodies"]),
                }
                for nom, f in self.imap.folders.items()
            }
        )

    def test_the_inbox_survives_the_merge_of_several_links(self):
        for nom in ("Archives", "Projets", "Sent"):
            self.imap.ajouter(nom, 1)
        self.imap.ajouter("INBOX", 7)
        self.imap.ajouter("INBOX", 8)
        syncer = Syncer(
            self.store, self._copie(), open_transport=self._copie, parallele=3
        )
        rapport = syncer.sync()
        self.assertEqual(rapport.inbox_folder, "INBOX")
        self.assertEqual([h.uid for h in rapport.inbox], [7, 8])

    def test_merge_keeps_the_first_folder_and_ors_truncation(self):
        entete = HeaderInfo(1, 0, 0, "", "", "", "", "")
        vide = SyncReport()
        plein = SyncReport(
            inbox_folder="INBOX", inbox=[entete], inbox_truncated=True
        )
        autre = SyncReport(inbox_folder="Reception")
        total = Syncer._fusion([vide, plein, autre])
        self.assertEqual(total.inbox_folder, "INBOX")
        self.assertEqual(total.inbox, [entete])
        self.assertTrue(total.inbox_truncated)


class TestNotArrivals(InboxCase):
    def test_sync_one_on_the_inbox_reports_nothing(self):
        """Une relecture ciblée après un envoi n'est pas une arrivée."""
        self.imap.ajouter("INBOX", 1)
        rapport = self.syncer.sync_one("INBOX")
        self.assertEqual(rapport.inbox, [])
        self.assertEqual(rapport.inbox_folder, "")
        self.assertIn(1, self.stockes("INBOX"))

    def test_fetch_uids_stores_without_a_report(self):
        self.imap.ajouter("INBOX", 3, internaldate=RECU)
        self.assertEqual(self.syncer.fetch_uids("INBOX", [3]), 1)
        self.assertEqual(self.stockes("INBOX")[3].received_at, RECU)


class TestReceivedAtIsStored(InboxCase):
    def test_the_internaldate_becomes_received_at(self):
        self.imap.ajouter("INBOX", 1, internaldate=RECU)
        self.syncer.sync()
        self.assertEqual(self.stockes("INBOX")[1].received_at, RECU)

    def test_an_unknown_internaldate_is_stored_as_zero(self):
        self.imap.ajouter("INBOX", 1, internaldate=0)
        self.syncer.sync()
        self.assertEqual(self.stockes("INBOX")[1].received_at, 0)

    def test_a_header_without_v6_fields_still_syncs(self):
        """Un double qui ne connaît pas `internaldate` reste valide."""

        class Ancien:
            def __init__(self, uid):
                self.uid, self.date, self.size, self.flags = uid, 1, 1, ""
                self.msgid, self.frm, self.to = f"<{uid}@x>", "", ""
                self.subject, self.in_reply_to, self.references = "", "", ""

        self.imap.add("INBOX", 1)
        self.imap.folders["INBOX"]["messages"][1] = Ancien(1)
        self.syncer.sync()
        self.assertEqual(self.stockes("INBOX")[1].received_at, 0)


if __name__ == "__main__":
    unittest.main()
