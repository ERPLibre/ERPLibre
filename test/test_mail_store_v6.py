#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache v6 : journal des règles, envois automatiques, file étendue,
`received_at` et `seen_at`.

Ce que ces tests figent : une base v5 migre sans perdre de ligne, le journal
n'accepte qu'une ligne par (règle, message) et n'en rétrograde jamais
l'issue, la file se réserve atomiquement entre deux connexions, et rien de
ce qui nomme une personne n'est écrit en clair dans un cache chiffré.
"""

import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import build_crypto, new_key
from script.todo.mail.store import (
    OUTBOX_CLAIM_STALE_S,
    OUTBOX_MAX_ATTEMPTS,
    SCHEMA_VERSION,
    MessageMeta,
    Store,
    cache_root,
)

COMPTE = "boite.regles@example.org"
HUMAIN = "carole.regle@example.org"
SECOND = "bruno.filtre@example.net"
REGLE = "3f9c0a1b2c4d"

V5_SQL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE folders (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, display TEXT,
  role TEXT, uidvalidity INTEGER, uidnext INTEGER,
  last_uid INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
  unseen INTEGER NOT NULL DEFAULT 0, synced_at INTEGER
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY,
  folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  uid INTEGER NOT NULL, date INTEGER, size INTEGER, flags TEXT,
  has_body INTEGER NOT NULL DEFAULT 0, msgid_hash TEXT, sealed_msgid BLOB,
  sealed_from BLOB, sealed_to BLOB, sealed_subject BLOB,
  sealed_snippet BLOB, in_reply_to_hash TEXT, references_hashes TEXT,
  UNIQUE(folder_id, uid)
);
CREATE TABLE outbox (
  id INTEGER PRIMARY KEY, created_at INTEGER NOT NULL,
  sealed_raw BLOB NOT NULL, sealed_to BLOB, sealed_subject BLOB,
  held INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
  sealed_error BLOB
);
INSERT INTO meta VALUES('schema_version', '5');
INSERT INTO folders(id, name, display, role)
  VALUES(1, 'INBOX', 'INBOX', 'inbox');
"""
# Les lignes de la v5, scellées comme le mode clair les scelle : un préfixe
# d'enveloppe devant le texte.
V5_ROWS = (
    "INSERT INTO messages(folder_id, uid, date, size, flags, msgid_hash,"
    " sealed_subject) VALUES(1, 4, 1000, 42, '\\Seen', 'h', ?)",
    "INSERT INTO outbox(created_at, sealed_raw, sealed_subject)"
    " VALUES(1000, ?, ?)",
)


def meta(uid, flags="", msgid=None, received_at=0):
    return MessageMeta(
        uid=uid,
        date=1000 + uid,
        size=42,
        flags=flags,
        msgid=f"<{uid}@example.org>" if msgid is None else msgid,
        frm=HUMAIN,
        to=COMPTE,
        subject=f"Sujet {uid}",
        snippet="",
        received_at=received_at,
    )


class StoreCase(unittest.TestCase):
    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", COMPTE, "generic")
        self.key = new_key() if self.mode != "clear" else None
        self.store = self.ouvrir()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def ouvrir(self):
        store = Store(
            self.account, mode=self.mode, key=self.key, base=self.base
        )
        store.open()
        return store

    def rouvrir(self):
        self.store.close()
        self.store = self.ouvrir()

    def colonnes(self, table):
        return {
            r["name"]
            for r in self.store._db().execute(f"PRAGMA table_info({table})")
        }

    def version(self):
        return (
            self.store._db()
            .execute("SELECT value FROM meta WHERE key='schema_version'")
            .fetchone()[0]
        )

    def inbox(self):
        return self.store.upsert_folder("INBOX", "INBOX", "inbox")

    def ligne(self, fid, uid):
        return (
            self.store._db()
            .execute(
                "SELECT received_at, seen_at FROM messages"
                " WHERE folder_id = ? AND uid = ?",
                (fid, uid),
            )
            .fetchone()
        )

    def reclamer(self, cle="k1", **champs):
        champs.setdefault("outcome", "pending")
        champs.setdefault("at", 1000)
        return self.store.rule_log_claim(REGLE, cle, **champs)


MESSAGES_V6 = {"received_at", "seen_at"}
OUTBOX_V6 = {
    "kind",
    "rule_id",
    "source_key",
    "expires_at",
    "max_attempts",
    "perm_attempts",
    "claimed_at",
}


class TestMigrationFromV5(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", COMPTE, "generic")
        racine = cache_root(self.account, "clear", Path(self.tmp.name))
        racine.mkdir(parents=True)
        conn = sqlite3.connect(racine / "cache.db")
        conn.executescript(V5_SQL)
        clair = build_crypto("clear", None)
        conn.execute(V5_ROWS[0], (clair.seal("Sujet v5".encode()),))
        conn.execute(
            V5_ROWS[1],
            (clair.seal(b"brut"), clair.seal("En attente".encode())),
        )
        conn.commit()
        conn.close()
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def colonnes(self, table):
        return {
            r["name"]
            for r in self.store._db().execute(f"PRAGMA table_info({table})")
        }

    def test_v6_columns_are_added(self):
        self.assertTrue(MESSAGES_V6 <= self.colonnes("messages"))
        self.assertTrue(OUTBOX_V6 <= self.colonnes("outbox"))

    def test_v6_tables_are_created(self):
        self.assertTrue({"rule_id", "msg_key"} <= self.colonnes("rule_log"))
        self.assertTrue({"msgid_hash"} <= self.colonnes("auto_sent"))

    def test_the_message_row_is_intact(self):
        fid = self.store.folder_state("INBOX")["id"]
        [message] = self.store.list_messages(fid)
        self.assertEqual((message.uid, message.subject), (4, "Sujet v5"))
        self.assertEqual((message.received_at, message.seen_at), (0, 0))

    def test_the_outbox_row_is_intact_with_defaults(self):
        [entree] = self.store.outbox()
        self.assertEqual(entree["subject"], "En attente")
        self.assertEqual(entree["kind"], "manual")
        self.assertEqual(entree["max_attempts"], OUTBOX_MAX_ATTEMPTS)
        self.assertEqual(entree["perm_attempts"], 0)
        self.assertIsNone(entree["claimed_at"])

    def test_the_version_becomes_six(self):
        ligne = (
            self.store._db()
            .execute("SELECT value FROM meta WHERE key='schema_version'")
            .fetchone()
        )
        self.assertEqual(ligne[0], "6")
        self.assertEqual(SCHEMA_VERSION, 6)


class TestFreshCache(StoreCase):
    def test_a_fresh_cache_has_every_v6_column(self):
        self.assertTrue(MESSAGES_V6 <= self.colonnes("messages"))
        self.assertTrue(OUTBOX_V6 <= self.colonnes("outbox"))
        self.assertEqual(self.version(), str(SCHEMA_VERSION))

    def test_dropping_an_outbox_column_succeeds(self):
        """SQLite reconstruit le CREATE pour un DROP COLUMN : un commentaire
        resté dans la parenthèse le ferait échouer."""
        db = self.store._db()
        db.execute("ALTER TABLE outbox DROP COLUMN perm_attempts")
        db.commit()
        self.assertNotIn("perm_attempts", self.colonnes("outbox"))

    def test_reopening_twice_is_harmless(self):
        self.rouvrir()
        self.rouvrir()
        self.assertTrue(OUTBOX_V6 <= self.colonnes("outbox"))


class TestRuleLog(StoreCase):
    def test_claim_creates_once_then_refuses(self):
        self.assertTrue(self.reclamer())
        self.assertFalse(self.reclamer(outcome="sent"))
        self.assertEqual(self.store.rule_log_outcome(REGLE, "k1"), "pending")

    def test_the_same_message_under_another_rule_is_a_new_line(self):
        self.reclamer()
        self.assertTrue(
            self.store.rule_log_claim("autre", "k1", outcome="sent", at=1)
        )

    def test_seen_says_whether_a_line_exists(self):
        self.assertFalse(self.store.rule_log_seen(REGLE, "k1"))
        self.reclamer(outcome="skipped", reason="list")
        self.assertTrue(self.store.rule_log_seen(REGLE, "k1"))

    def test_unknown_line_has_no_outcome_nor_fingerprint(self):
        self.assertIsNone(self.store.rule_log_outcome(REGLE, "absent"))
        self.assertIsNone(self.store.rule_log_fingerprint(REGLE, "absent"))

    def test_fingerprint_is_read_back(self):
        self.reclamer(fingerprint="fp1")
        self.assertEqual(self.store.rule_log_fingerprint(REGLE, "k1"), "fp1")

    def test_set_outcome_advances_a_pending_line(self):
        self.reclamer()
        self.assertTrue(
            self.store.rule_log_set_outcome(
                REGLE, "k1", "queued", "offline", queue_id=5
            )
        )
        [ligne] = self.store.rule_log_entries(REGLE)
        self.assertEqual(
            (ligne["outcome"], ligne["reason"], ligne["queue_id"]),
            ("queued", "offline", 5),
        )

    def test_set_outcome_never_demotes_sent_to_queued(self):
        """Une vidange concurrente peut avoir envoyé l'entrée avant que le
        moteur n'écrive `queued`."""
        self.reclamer()
        self.store.rule_log_set_outcome(REGLE, "k1", "sent")
        self.assertFalse(
            self.store.rule_log_set_outcome(REGLE, "k1", "queued", "offline")
        )
        self.assertEqual(self.store.rule_log_outcome(REGLE, "k1"), "sent")

    def test_set_outcome_never_rewrites_any_terminal_outcome(self):
        for issue in ("skipped", "failed", "expired"):
            cle = f"k-{issue}"
            self.reclamer(cle, outcome=issue)
            self.assertFalse(
                self.store.rule_log_set_outcome(REGLE, cle, "sent")
            )
            self.assertEqual(self.store.rule_log_outcome(REGLE, cle), issue)

    def test_set_outcome_keeps_the_queue_link_when_sent(self):
        self.reclamer(queue_id=9, outcome="queued")
        self.store.rule_log_set_outcome(REGLE, "k1", "sent")
        self.assertEqual(self.store.rule_log_entries()[0]["queue_id"], 9)

    def test_set_outcome_on_a_missing_line_changes_nothing(self):
        self.assertFalse(
            self.store.rule_log_set_outcome(REGLE, "absent", "sent")
        )

    def test_entries_are_most_recent_first_and_opened(self):
        self.reclamer("k1", at=100, sender=HUMAIN, subject="Premier")
        self.reclamer("k2", at=300, sender=SECOND, subject="Second")
        self.store.rule_log_claim("autre", "k3", outcome="sent", at=200)
        entrees = self.store.rule_log_entries()
        self.assertEqual([e["at"] for e in entrees], [300, 200, 100])
        self.assertEqual(
            (entrees[0]["sender"], entrees[0]["subject"]), (SECOND, "Second")
        )
        self.assertEqual(
            set(entrees[0]),
            {
                "rule_id",
                "at",
                "received_at",
                "outcome",
                "reason",
                "sender",
                "subject",
                "queue_id",
            },
        )

    def test_entries_filter_by_rule_and_limit(self):
        for rang in range(5):
            self.reclamer(f"k{rang}", at=rang)
        self.store.rule_log_claim("autre", "x", outcome="sent", at=99)
        self.assertEqual(len(self.store.rule_log_entries(REGLE)), 5)
        self.assertEqual(len(self.store.rule_log_entries(REGLE, limit=2)), 2)

    def test_received_at_zero_is_stored_null(self):
        self.reclamer(received_at=0)
        self.assertIsNone(self.store.rule_log_entries()[0]["received_at"])


class TestLastSend(StoreCase):
    def setUp(self):
        super().setUp()
        self.de = self.store.address_hash(HUMAIN)
        self.cible = self.store.address_hash(SECOND)

    def test_none_without_any_line(self):
        self.assertIsNone(self.store.rule_log_last_send(REGLE, self.de))

    def test_non_sending_outcomes_are_ignored(self):
        for rang, issue in enumerate(("skipped", "failed", "expired")):
            self.reclamer(
                f"k{rang}", outcome=issue, at=500, sender_hash=self.de
            )
        self.assertIsNone(self.store.rule_log_last_send(REGLE, self.de))

    def test_every_sending_outcome_counts(self):
        for rang, issue in enumerate(("pending", "sent", "queued", "held")):
            self.reclamer(
                f"k{rang}", outcome=issue, at=100 + rang, sender_hash=self.de
            )
        self.assertEqual(self.store.rule_log_last_send(REGLE, self.de), 103)

    def test_found_by_sender_hash(self):
        self.reclamer(outcome="sent", at=700, sender_hash=self.de)
        self.assertEqual(
            self.store.rule_log_last_send(REGLE, self.de, self.cible), 700
        )

    def test_found_by_target_hash_when_the_sender_differs(self):
        """L'adresse d'enveloppe sert de seconde clé."""
        self.reclamer(
            outcome="sent",
            at=800,
            sender_hash=self.store.address_hash("denis.tri@example.org"),
            target_hash=self.cible,
        )
        self.assertEqual(
            self.store.rule_log_last_send(REGLE, self.de, self.cible), 800
        )

    def test_a_changing_envelope_does_not_escape_the_sender_key(self):
        """VERP, BATV, SRS : la cible change à chaque message, le From
        reste."""
        self.reclamer(
            "k1",
            outcome="sent",
            at=900,
            sender_hash=self.de,
            target_hash=self.cible,
        )
        nouvelle = self.store.address_hash("denis.tri@example.org")
        self.assertEqual(
            self.store.rule_log_last_send(REGLE, self.de, nouvelle), 900
        )

    def test_another_rule_does_not_count(self):
        self.store.rule_log_claim(
            "autre", "k1", outcome="sent", at=900, sender_hash=self.de
        )
        self.assertIsNone(self.store.rule_log_last_send(REGLE, self.de))

    def test_an_empty_hash_matches_nothing(self):
        self.reclamer(outcome="sent", at=900)
        self.assertIsNone(self.store.rule_log_last_send(REGLE, "", None))


class TestSentCount(StoreCase):
    def test_only_sent_lines_of_this_fingerprint_count(self):
        self.reclamer("k1", outcome="sent", fingerprint="fp1")
        self.reclamer("k2", outcome="sent", fingerprint="fp1")
        self.reclamer("k3", outcome="held", fingerprint="fp1")
        self.reclamer("k4", outcome="sent", fingerprint="fp2")
        self.assertEqual(self.store.rule_log_sent_count(REGLE, "fp1"), 2)
        self.assertEqual(self.store.rule_log_sent_count(REGLE, "fp2"), 1)
        self.assertEqual(self.store.rule_log_sent_count(REGLE, "fp3"), 0)


class TestHashes(StoreCase):
    def test_address_hash_ignores_case_and_spaces(self):
        self.assertEqual(
            self.store.address_hash(" Carole.Regle@Example.ORG "),
            self.store.address_hash(HUMAIN),
        )

    def test_address_hash_of_nothing_is_empty(self):
        self.assertEqual(self.store.address_hash(""), "")
        self.assertEqual(self.store.address_hash("   "), "")

    def test_address_hash_differs_between_addresses(self):
        self.assertNotEqual(
            self.store.address_hash(HUMAIN), self.store.address_hash(SECOND)
        )

    def test_message_key_equals_msgid_hash_with_a_message_id(self):
        fid = self.inbox()
        self.store.upsert_messages(fid, [meta(1)])
        [message] = self.store.list_messages(fid)
        self.assertEqual(
            self.store.message_key(" <1@example.org> ", 42, 1),
            message.msgid_hash,
        )

    def test_message_keys_differ_without_a_message_id(self):
        self.assertNotEqual(
            self.store.message_key("", 42, 1),
            self.store.message_key("", 42, 2),
        )
        self.assertNotEqual(
            self.store.message_key("", 42, 1),
            self.store.message_key("", 43, 1),
        )

    def test_message_key_without_message_id_is_stable(self):
        self.assertEqual(
            self.store.message_key("  ", 42, 1),
            self.store.message_key("", 42, 1),
        )

    def test_a_message_id_cannot_take_the_key_of_a_message_without_one(self):
        """Un Message-ID écrit comme la clé de repli ne la reproduit pas :
        sinon il réserverait d'avance la place d'un message à venir."""
        for forge in ("uid:1:7", " uid:1:7 ", "<uid:1:7>"):
            self.assertNotEqual(
                self.store.message_key(forge, 9, 9),
                self.store.message_key("", 1, 7),
            )


class TestUidsBetween(StoreCase):
    def test_bounds_are_open_then_closed_and_sorted(self):
        fid = self.inbox()
        self.store.upsert_messages(fid, [meta(u) for u in (7, 3, 5, 9, 1)])
        self.assertEqual(self.store.uids_between(fid, 3, 9), [5, 7, 9])
        self.assertEqual(self.store.uids_between(fid, 9, 20), [])

    def test_another_folder_is_not_read(self):
        fid = self.inbox()
        autre = self.store.upsert_folder("Archives")
        self.store.upsert_messages(autre, [meta(4)])
        self.assertEqual(self.store.uids_between(fid, 0, 10), [])


class TestAutoSent(StoreCase):
    def test_a_marked_message_id_is_recognised_by_its_hash(self):
        self.store.mark_auto_sent(" <auto-1@example.org> ", REGLE, 100)
        empreinte = self.store.message_key("<auto-1@example.org>", 0, 0)
        self.assertTrue(self.store.is_auto_sent(empreinte))
        self.assertFalse(
            self.store.is_auto_sent(
                self.store.message_key("<autre@example.org>", 0, 0)
            )
        )

    def test_marking_twice_is_harmless(self):
        self.store.mark_auto_sent("<auto-1@example.org>", REGLE, 100)
        self.store.mark_auto_sent("<auto-1@example.org>", REGLE, 200)
        compte = (
            self.store._db()
            .execute("SELECT COUNT(*) FROM auto_sent")
            .fetchone()[0]
        )
        self.assertEqual(compte, 1)

    def test_an_empty_message_id_is_not_marked(self):
        """Son empreinte serait celle de tous les messages sans
        Message-ID."""
        self.store.mark_auto_sent("", REGLE, 100)
        self.store.mark_auto_sent(None, REGLE, 100)
        compte = (
            self.store._db()
            .execute("SELECT COUNT(*) FROM auto_sent")
            .fetchone()[0]
        )
        self.assertEqual(compte, 0)

    def test_an_auto_reply_is_not_a_reply_in_the_statistics(self):
        """Sa copie dans Envoyés porte `In-Reply-To` comme une réponse
        écrite à la main ; comptée, elle ferait chuter la médiane."""
        fid = self.inbox()

        def meta(uid, date, msgid, irt=""):
            return MessageMeta(
                uid,
                date,
                1,
                "",
                msgid,
                HUMAIN,
                COMPTE,
                "Devis",
                "",
                in_reply_to=irt,
            )

        self.store.upsert_messages(
            fid,
            [
                meta(1, 1000, "<q1@example.org>"),
                meta(2, 1005, "<auto@example.org>", "<q1@example.org>"),
                meta(3, 2000, "<q2@example.org>"),
                meta(4, 9000, "<main@example.org>", "<q2@example.org>"),
            ],
        )
        self.assertEqual(sorted(self.store.stats_reply_delays()), [5, 7000])
        self.store.mark_auto_sent("<auto@example.org>", REGLE, 1005)
        self.assertEqual(self.store.stats_reply_delays(), [7000])


class TestQueueV6(StoreCase):
    def test_the_legacy_call_queues_a_manual_entry(self):
        self.store.queue_message(b"brut", HUMAIN, "Devis")
        [entree] = self.store.outbox()
        self.assertEqual(entree["kind"], "manual")
        self.assertFalse(entree["held"])
        self.assertIsNone(entree["rule_id"])
        self.assertEqual(entree["max_attempts"], OUTBOX_MAX_ATTEMPTS)

    def test_keywords_are_stored_and_returned(self):
        ident = self.store.queue_message(
            b"brut",
            HUMAIN,
            "Auto: Devis",
            held=True,
            kind="auto_reply",
            rule_id=REGLE,
            source_key="k1",
            expires_at=5000,
            max_attempts=7,
        )
        [entree] = self.store.outbox()
        self.assertEqual(entree["id"], ident)
        self.assertTrue(entree["held"])
        self.assertEqual(
            (
                entree["kind"],
                entree["rule_id"],
                entree["source_key"],
                entree["expires_at"],
                entree["max_attempts"],
                entree["perm_attempts"],
                entree["claimed_at"],
            ),
            ("auto_reply", REGLE, "k1", 5000, 7, 0, None),
        )
        self.assertEqual(self.store.queued_raw(ident), b"brut")

    def test_queue_auto_writes_queue_and_log_together(self):
        self.reclamer(outcome="pending")
        ident = self.store.queue_auto(
            b"brut",
            HUMAIN,
            "Auto: Devis",
            held=True,
            rule_id=REGLE,
            source_key="k1",
            expires_at=9000,
            outcome="held",
            reason="hold_first",
        )
        [entree] = self.store.outbox()
        self.assertEqual(
            (entree["id"], entree["kind"], entree["source_key"]),
            (ident, "auto_reply", "k1"),
        )
        self.assertTrue(entree["held"])
        [ligne] = self.store.rule_log_entries()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"], ligne["queue_id"]),
            ("held", "hold_first", ident),
        )

    def test_queue_auto_rolls_back_the_queue_when_the_log_fails(self):
        """Une file sans journal ferait partir une réponse que le journal
        ne connaît pas."""
        self.reclamer(outcome="pending")
        with patch.object(
            Store, "_avancer_issue", side_effect=sqlite3.OperationalError("x")
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.queue_auto(
                    b"brut",
                    HUMAIN,
                    "Auto: Devis",
                    held=False,
                    rule_id=REGLE,
                    source_key="k1",
                    expires_at=9000,
                    outcome="queued",
                    reason="offline",
                )
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(REGLE, "k1"), "pending")

    def test_queue_auto_does_not_demote_a_sent_line(self):
        self.reclamer(outcome="sent")
        self.store.queue_auto(
            b"brut",
            HUMAIN,
            "Auto: Devis",
            held=False,
            rule_id=REGLE,
            source_key="k1",
            expires_at=9000,
            outcome="queued",
            reason="smtp_transient",
        )
        self.assertEqual(self.store.rule_log_outcome(REGLE, "k1"), "sent")

    def mettre_auto(self, cle, **kw):
        self.reclamer(cle=cle, outcome="pending")
        return self.store.queue_auto(
            b"brut",
            HUMAIN,
            "Fwd: Devis",
            held=False,
            rule_id=REGLE,
            source_key=cle,
            expires_at=9000,
            outcome="queued",
            reason="offline",
            **kw,
        )

    def test_queue_auto_records_the_kind(self):
        self.mettre_auto("k1")
        self.mettre_auto("k2", kind="auto_forward")
        self.mettre_auto("k3", kind="auto_redirect")
        self.assertEqual(
            [e["kind"] for e in self.store.outbox()],
            ["auto_reply", "auto_forward", "auto_redirect"],
        )

    def test_a_queued_redirect_gives_no_recipient_to_a_naive_reader(self):
        """Un code qui ignore `auto_redirect` lit les octets scellés comme
        un message : il n'y trouve aucun destinataire, donc rien ne part
        vers les To/Cc de l'original. `queued_raw` rend les octets mis en
        file."""
        import email

        from script.todo.mail.smtp_send import recipients

        brut = (
            b"Resent-From: boite.regles@example.org\r\n"
            b"From: bruno.filtre@example.net\r\n"
            b"To: boite.regles@example.org\r\n"
            b"Cc: temoin.cci@example.com\r\n"
            b"Subject: Devis\r\n\r\nBonjour.\r\n"
        )
        self.reclamer(cle="k1", outcome="pending")
        ident = self.store.queue_auto(
            brut,
            "carole.regle@example.org",
            "Devis",
            held=True,
            rule_id=REGLE,
            source_key="k1",
            expires_at=9000,
            outcome="held",
            reason="hold_first",
            kind="auto_redirect",
        )
        self.assertEqual(self.store.queued_raw(ident), brut)
        [scelle] = (
            self.store._db()
            .execute("SELECT sealed_raw FROM outbox WHERE id = ?", (ident,))
            .fetchone()
        )
        naif = email.message_from_bytes(self.store._crypto.open(scelle))
        self.assertEqual(naif.keys(), [])
        self.assertEqual(recipients(naif), [])

    def test_queue_auto_refuses_an_unknown_kind(self):
        """Refusé avant toute écriture : ni file, ni journal avancé."""
        for kind in ("manual", "auto_later", ""):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.mettre_auto("k1", kind=kind)
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_outcome(REGLE, "k1"), "pending")

    def test_outbox_listing_does_not_read_the_raw_bytes(self):
        """La liste se relit à chaque passe : une file de transferts lourds
        n'y fait lire aucun octet scellé."""
        self.store.queue_message(b"brut", HUMAIN, "Devis")
        requetes = []
        db = self.store._db()
        db.set_trace_callback(requetes.append)
        try:
            [entree] = self.store.outbox()
        finally:
            db.set_trace_callback(None)
        self.assertEqual(entree["to"], HUMAIN)
        lues = [r for r in requetes if "outbox" in r.lower()]
        self.assertTrue(lues)
        for requete in lues:
            self.assertNotIn("sealed_raw", requete)
            self.assertNotIn("*", requete)


class TestIsRuleSend(StoreCase):
    def test_is_rule_send_ignores_messages_marked_by_the_sync(self):
        self.store.mark_auto_sent("<tiers@example.net>", "", 100)
        self.store.mark_auto_sent("<regle@example.org>", REGLE, 100)
        self.assertFalse(self.store.is_rule_send("<tiers@example.net>"))
        self.assertTrue(self.store.is_rule_send(" <regle@example.org> "))
        self.assertFalse(self.store.is_rule_send("<inconnu@example.org>"))

    def test_is_rule_send_with_an_empty_message_id_is_false(self):
        self.store.mark_auto_sent("<regle@example.org>", REGLE, 100)
        for msgid in ("", "  ", None):
            with self.subTest(msgid=msgid):
                self.assertFalse(self.store.is_rule_send(msgid))
                self.assertFalse(
                    self.store.is_rule_send(msgid, rule_ids=[REGLE])
                )

    def test_is_rule_send_can_be_limited_to_some_rules(self):
        self.store.mark_auto_sent("<regle@example.org>", REGLE, 100)
        msgid = "<regle@example.org>"
        self.assertTrue(self.store.is_rule_send(msgid, rule_ids=[REGLE]))
        self.assertTrue(
            self.store.is_rule_send(msgid, rule_ids=("autre", REGLE))
        )
        self.assertFalse(self.store.is_rule_send(msgid, rule_ids=["autre"]))
        self.assertFalse(self.store.is_rule_send(msgid, rule_ids=[]))
        self.assertFalse(self.store.is_rule_send(msgid, rule_ids=set()))


class TestOutboxClaim(StoreCase):
    def setUp(self):
        super().setUp()
        self.ident = self.store.queue_message(b"brut", HUMAIN, "Devis")

    def test_two_stores_on_the_same_file_claim_once(self):
        """Deux processus — TUI et menu — partagent `cache.db`."""
        second = self.ouvrir()
        self.addCleanup(second.close)
        resultats = [
            self.store.outbox_claim(self.ident, 1000),
            second.outbox_claim(self.ident, 1000),
        ]
        self.assertEqual(resultats, [True, False])

    def test_a_stale_claim_is_taken_over(self):
        self.store.outbox_claim(self.ident, 1000)
        self.assertFalse(
            self.store.outbox_claim(self.ident, 1000 + OUTBOX_CLAIM_STALE_S)
        )
        self.assertTrue(
            self.store.outbox_claim(self.ident, 1001 + OUTBOX_CLAIM_STALE_S)
        )

    def test_release_frees_the_entry(self):
        self.store.outbox_claim(self.ident, 1000)
        self.store.outbox_release(self.ident)
        self.assertIsNone(self.store.outbox()[0]["claimed_at"])
        self.assertTrue(self.store.outbox_claim(self.ident, 1001))

    def test_a_missing_entry_cannot_be_claimed(self):
        self.assertFalse(self.store.outbox_claim(self.ident + 99, 1000))

    def test_record_send_failure_releases_and_counts(self):
        self.store.outbox_claim(self.ident, 1000)
        compteurs = self.store.record_send_failure(self.ident, "421 plus tard")
        self.assertEqual(
            compteurs,
            {
                "attempts": 1,
                "perm_attempts": 0,
                "max_attempts": OUTBOX_MAX_ATTEMPTS,
            },
        )
        [entree] = self.store.outbox()
        self.assertIsNone(entree["claimed_at"])
        self.assertEqual(entree["last_error"], "421 plus tard")

    def test_record_send_failure_permanent_counts_twice(self):
        self.store.record_send_failure(self.ident, "550 refus", permanent=True)
        compteurs = self.store.record_send_failure(
            self.ident, "550 refus", permanent=True
        )
        self.assertEqual(
            (compteurs["attempts"], compteurs["perm_attempts"]), (2, 2)
        )

    def test_record_send_failure_on_a_missing_entry_returns_zeros(self):
        compteurs = self.store.record_send_failure(self.ident + 99, "x")
        self.assertEqual(
            (compteurs["attempts"], compteurs["perm_attempts"]), (0, 0)
        )


class TestCacheEpoch(StoreCase):
    def test_the_epoch_is_stable_across_reopening(self):
        epoque = self.store.cache_epoch()
        self.assertEqual(len(epoque), 16)
        self.rouvrir()
        self.assertEqual(self.store.cache_epoch(), epoque)

    def test_purge_all_keeps_the_epoch_and_the_log(self):
        epoque = self.store.cache_epoch()
        self.reclamer(outcome="sent")
        self.store.purge_all()
        self.assertEqual(self.store.cache_epoch(), epoque)
        self.assertTrue(self.store.rule_log_seen(REGLE, "k1"))

    def test_a_recreated_cache_gets_a_new_epoch(self):
        epoque = self.store.cache_epoch()
        self.store.close()
        shutil.rmtree(self.store.root)
        self.store = self.ouvrir()
        self.assertNotEqual(self.store.cache_epoch(), epoque)

    def test_two_stores_read_the_same_epoch(self):
        second = self.ouvrir()
        self.addCleanup(second.close)
        self.assertEqual(second.cache_epoch(), self.store.cache_epoch())

    def test_an_epoch_without_its_check_is_drawn_again(self):
        """Une époque que rien ne lie au sel ne prouve pas que le journal
        est lisible : elle est retirée, le journal reste."""
        self.reclamer(outcome="sent")
        db = self.store._db()
        db.execute(
            "INSERT OR REPLACE INTO meta(key, value)"
            " VALUES('cache_epoch', 'ancienne')"
        )
        db.commit()
        epoque = self.store.cache_epoch()
        self.assertNotEqual(epoque, "ancienne")
        self.assertEqual(self.store.cache_epoch(), epoque)
        self.assertTrue(self.store.rule_log_seen(REGLE, "k1"))


class TestCacheEpochAcrossKeys(StoreCase):
    """Une clé neuve sur un `cache.db` conservé : chaque empreinte du
    journal est salée par l'ancienne, il ne correspond donc plus à rien."""

    mode = "encrypted"

    def changer_de_cle(self):
        self.store.close()
        self.key = new_key()
        self.store = self.ouvrir()

    def test_the_same_key_keeps_the_epoch(self):
        epoque = self.store.cache_epoch()
        self.rouvrir()
        self.assertEqual(self.store.cache_epoch(), epoque)

    def test_a_new_key_draws_a_new_epoch_and_drops_the_old_log(self):
        epoque = self.store.cache_epoch()
        cle = self.store.message_key("<cle@example.org>", 1, 1)
        self.store.rule_log_claim(
            REGLE,
            cle,
            outcome="sent",
            at=1000,
            sender_hash=self.store.address_hash(HUMAIN),
            sender=HUMAIN,
            subject="Sujet",
        )
        self.store.mark_auto_sent("<auto@example.org>", REGLE, 1000)
        self.changer_de_cle()
        nouvelle = self.store.cache_epoch()
        self.assertNotEqual(nouvelle, epoque)
        self.assertEqual(self.store.cache_epoch(), nouvelle)
        # Illisibles sous la clé neuve, les anciennes lignes ne font plus
        # lever l'écran du journal : elles sont parties.
        self.assertEqual(self.store.rule_log_entries(), [])
        self.assertEqual(
            self.store._db()
            .execute("SELECT COUNT(*) FROM auto_sent")
            .fetchone()[0],
            0,
        )


class TestSeenAt(StoreCase):
    def setUp(self):
        super().setUp()
        self.fid = self.inbox()

    def poser_seen_at(self, uid, valeur):
        db = self.store._db()
        db.execute(
            "UPDATE messages SET seen_at = ? WHERE folder_id = ? AND uid = ?",
            (valeur, self.fid, uid),
        )
        db.commit()

    def test_update_flags_sets_it_when_the_message_becomes_read(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        avant = int(time.time())
        self.store.update_flags(self.fid, 1, "\\Seen")
        vu = self.ligne(self.fid, 1)["seen_at"]
        self.assertTrue(avant <= vu <= int(time.time()))

    def test_update_flags_clears_it_back_to_unread(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        self.store.update_flags(self.fid, 1, "\\Seen")
        self.store.update_flags(self.fid, 1, "")
        self.assertIsNone(self.ligne(self.fid, 1)["seen_at"])

    def test_update_flags_without_transition_keeps_it(self):
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.poser_seen_at(1, 1234)
        self.store.update_flags(self.fid, 1, "\\Seen \\Flagged")
        self.assertEqual(self.ligne(self.fid, 1)["seen_at"], 1234)

    def test_mark_all_seen_sets_it_on_the_rows_it_changes_only(self):
        self.store.upsert_messages(
            self.fid, [meta(1), meta(2, flags="\\Seen")]
        )
        self.poser_seen_at(2, 1234)
        avant = int(time.time())
        self.store.mark_all_seen(self.fid)
        self.assertGreaterEqual(self.ligne(self.fid, 1)["seen_at"], avant)
        self.assertEqual(self.ligne(self.fid, 2)["seen_at"], 1234)

    def test_inserting_an_already_read_message_leaves_it_null(self):
        """Lu ailleurs, avant que le cache ne le voie : moment inconnu."""
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.assertIsNone(self.ligne(self.fid, 1)["seen_at"])

    def test_an_upsert_that_makes_it_read_sets_it(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        avant = int(time.time())
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.assertGreaterEqual(self.ligne(self.fid, 1)["seen_at"], avant)

    def test_an_upsert_that_stays_read_keeps_it(self):
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.poser_seen_at(1, 1234)
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.assertEqual(self.ligne(self.fid, 1)["seen_at"], 1234)

    def test_an_upsert_back_to_unread_clears_it(self):
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.poser_seen_at(1, 1234)
        self.store.upsert_messages(self.fid, [meta(1)])
        self.assertIsNone(self.ligne(self.fid, 1)["seen_at"])

    def test_the_meta_reads_it_back(self):
        self.store.upsert_messages(self.fid, [meta(1, flags="\\Seen")])
        self.poser_seen_at(1, 1234)
        [message] = self.store.list_messages(self.fid)
        self.assertEqual(message.seen_at, 1234)


class TestReceivedAt(StoreCase):
    def setUp(self):
        super().setUp()
        self.fid = self.inbox()

    def test_it_is_stored_and_read_back(self):
        self.store.upsert_messages(self.fid, [meta(1, received_at=1785924000)])
        [message] = self.store.list_messages(self.fid)
        self.assertEqual(message.received_at, 1785924000)

    def test_zero_is_stored_null(self):
        self.store.upsert_messages(self.fid, [meta(1)])
        self.assertIsNone(self.ligne(self.fid, 1)["received_at"])

    def test_a_resync_bringing_zero_keeps_the_known_date(self):
        self.store.upsert_messages(self.fid, [meta(1, received_at=1785924000)])
        self.store.upsert_messages(self.fid, [meta(1, received_at=0)])
        self.assertEqual(self.ligne(self.fid, 1)["received_at"], 1785924000)

    def test_a_resync_bringing_a_date_replaces_it(self):
        self.store.upsert_messages(self.fid, [meta(1, received_at=1785924000)])
        self.store.upsert_messages(self.fid, [meta(1, received_at=1785924060)])
        self.assertEqual(self.ligne(self.fid, 1)["received_at"], 1785924060)


class TestEncryptedCacheKeepsNamesSealed(StoreCase):
    mode = "encrypted"

    def test_sender_and_subject_never_reach_the_file_in_clear(self):
        self.store.rule_log_claim(
            REGLE,
            self.store.message_key("<v6@example.org>", 1, 1),
            outcome="skipped",
            reason="list",
            at=1000,
            sender_hash=self.store.address_hash(HUMAIN),
            sender=HUMAIN,
            subject="Sujet tout à fait reconnaissable",
        )
        self.store.queue_auto(
            b"To: carole.regle@example.org\r\n\r\ncorps",
            HUMAIN,
            "Auto: Sujet tout à fait reconnaissable",
            held=True,
            rule_id=REGLE,
            source_key="k1",
            expires_at=9000,
            outcome="held",
            reason="hold_first",
        )
        [ligne] = self.store.rule_log_entries()
        self.assertEqual(ligne["sender"], HUMAIN)
        self.store.close()
        brut = (self.store.root / "cache.db").read_bytes()
        self.assertNotIn(HUMAIN.encode(), brut)
        self.assertNotIn("reconnaissable".encode(), brut)
        self.assertNotIn(b"<v6@example.org>", brut)


if __name__ == "__main__":
    unittest.main()
