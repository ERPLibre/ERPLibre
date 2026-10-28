#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.crypto import new_key
from script.todo.mail.store import ActivityRow, MessageMeta, Store

COMPTE = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
DENIS = "denis.tri@example.org"
T0 = 1_790_000_000
HEURE = 3600


def meta(
    uid,
    *,
    msgid=None,
    frm=CAROLE,
    date=None,
    received=T0,
    flags="",
    in_reply_to="",
    subject="Sujet",
):
    return MessageMeta(
        uid=uid,
        date=received if date is None else date,
        size=10,
        flags=flags,
        msgid=f"<m{uid}@example.org>" if msgid is None else msgid,
        frm=frm,
        to=COMPTE,
        subject=subject,
        snippet="",
        in_reply_to=in_reply_to,
        received_at=received,
    )


class ActivityCase(unittest.TestCase):
    """Cache temporaire : INBOX (rôle inbox) et Sent (nom du dossier
    d'envoi du préréglage, sans rôle)."""

    mode = "clear"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", COMPTE, "generic")
        key = new_key() if self.mode == "encrypted" else None
        self.store = Store(
            self.account, mode=self.mode, key=key, base=Path(self.tmp.name)
        )
        self.store.open()
        self.inbox = self.store.upsert_folder("INBOX", "Boîte", "inbox")
        self.sent = self.store.upsert_folder("Sent", "Envoyés")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def recevoir(self, *metas):
        self.store.upsert_messages(self.inbox, list(metas))

    def envoyer(self, *metas, folder=None):
        self.store.upsert_messages(folder or self.sent, list(metas))

    def reponse(self, uid, original_uid, at, **kw):
        return meta(
            uid,
            msgid=f"<r{uid}@example.org>",
            frm=COMPTE,
            received=at,
            in_reply_to=f"<m{original_uid}@example.org>",
            **kw,
        )

    def lignes(self, since=T0 - 10 * HEURE, until=T0 + 100 * HEURE, **kw):
        return self.store.stats_activity(since, until, **kw)


class TestStatsActivity(ActivityCase):
    def test_a_received_message_is_counted_once(self):
        self.recevoir(meta(1))
        self.assertEqual(
            self.lignes(), [ActivityRow(T0, False, False, None, "")]
        )

    def test_received_at_wins_over_the_date_header(self):
        self.recevoir(meta(1, date=T0 - 5 * HEURE, received=T0))
        self.assertEqual(self.lignes()[0].received_at, T0)

    def test_without_received_at_the_date_header_is_the_fallback(self):
        self.recevoir(meta(1, date=T0 - HEURE, received=0))
        self.assertEqual(self.lignes()[0].received_at, T0 - HEURE)

    def test_without_any_date_the_message_is_left_out(self):
        self.recevoir(meta(1, date=0, received=0))
        self.assertEqual(self.store.stats_activity(0, 2**40), [])

    def test_seen_follows_the_seen_flag(self):
        self.recevoir(
            meta(1, flags="\\Seen"),
            meta(2, flags="\\Flagged", received=T0 + 1),
        )
        self.assertEqual([r.seen for r in self.lignes()], [True, False])

    def test_answered_by_a_reply_filed_in_sent(self):
        self.recevoir(meta(1))
        self.envoyer(self.reponse(10, 1, T0 + 2 * HEURE))
        row = self.lignes()[0]
        self.assertTrue(row.answered)
        self.assertEqual(row.first_reply_at, T0 + 2 * HEURE)

    def test_answered_by_the_answered_flag_alone_has_no_delay(self):
        self.recevoir(meta(1, flags="\\Answered"))
        row = self.lignes()[0]
        self.assertTrue(row.answered)
        self.assertIsNone(row.first_reply_at)

    def test_an_automatic_reply_in_sent_does_not_answer(self):
        self.recevoir(meta(1))
        self.envoyer(self.reponse(10, 1, T0 + 60))
        self.store.mark_auto_sent("<r10@example.org>", "regle", T0 + 60)
        row = self.lignes()[0]
        self.assertFalse(row.answered)
        self.assertIsNone(row.first_reply_at)

    def test_an_automatic_message_in_the_inbox_is_not_received(self):
        self.recevoir(meta(1), meta(2))
        self.store.mark_auto_sent_many([("<m2@example.org>", "", T0)])
        self.assertEqual(len(self.lignes()), 1)

    def test_the_first_reply_is_the_earliest_of_several(self):
        self.recevoir(meta(1))
        self.envoyer(
            self.reponse(10, 1, T0 + 5 * HEURE),
            self.reponse(11, 1, T0 + 2 * HEURE),
        )
        self.assertEqual(self.lignes()[0].first_reply_at, T0 + 2 * HEURE)

    def test_a_reply_older_than_its_original_answers_without_a_delay(self):
        self.recevoir(meta(1))
        self.envoyer(self.reponse(10, 1, T0 - HEURE))
        row = self.lignes()[0]
        self.assertTrue(row.answered)
        self.assertIsNone(row.first_reply_at)

    def test_an_older_and_a_later_reply_give_the_later_delay(self):
        self.recevoir(meta(1))
        self.envoyer(
            self.reponse(10, 1, T0 - HEURE),
            self.reponse(11, 1, T0 + 3 * HEURE),
        )
        self.assertEqual(self.lignes()[0].first_reply_at, T0 + 3 * HEURE)

    def test_a_reply_outside_the_sent_folders_does_not_count(self):
        archives = self.store.upsert_folder("Archives", "Archives", "archive")
        self.recevoir(meta(1))
        self.envoyer(self.reponse(10, 1, T0 + HEURE), folder=archives)
        row = self.lignes()[0]
        self.assertFalse(row.answered)
        self.assertIsNone(row.first_reply_at)

    def test_a_sent_folder_found_by_its_role(self):
        envoyes = self.store.upsert_folder("Envoyes", "Envoyés", "sent")
        self.recevoir(meta(1))
        self.envoyer(self.reponse(10, 1, T0 + HEURE), folder=envoyes)
        self.assertEqual(self.lignes()[0].first_reply_at, T0 + HEURE)
        inbox, sent = self.store.activity_folders()
        self.assertEqual(inbox, [self.inbox])
        self.assertEqual(sorted(sent), sorted([self.sent, envoyes]))

    def test_without_a_sent_folder_only_the_flag_answers(self):
        self.account.sent_folder = "Aucun"
        self.recevoir(meta(1, flags="\\Answered"), meta(2, received=T0 + 1))
        self.envoyer(self.reponse(10, 2, T0 + HEURE))
        self.assertEqual(self.store.activity_folders()[1], [])
        rows = self.lignes()
        self.assertEqual([r.answered for r in rows], [True, False])
        self.assertEqual([r.first_reply_at for r in rows], [None, None])

    def test_with_sender_gives_the_normalized_from(self):
        self.recevoir(
            meta(1, frm="Carole <Carole.Regle@EXAMPLE.org>"),
            meta(2, frm=f"{BRUNO}, {DENIS}", received=T0 + 1),
        )
        rows = self.lignes(with_sender=True)
        self.assertEqual([r.sender for r in rows], [CAROLE, ""])
        self.assertEqual([r.sender for r in self.lignes()], ["", ""])

    def test_without_sender_no_sealed_column_is_opened(self):
        self.recevoir(meta(1), meta(2, flags="\\Seen"))
        self.envoyer(self.reponse(10, 1, T0 + HEURE))
        ouvertures = []
        vrai_open = self.store._open

        def espion(blob):
            ouvertures.append(blob)
            return vrai_open(blob)

        self.store._open = espion
        try:
            self.assertEqual(len(self.lignes()), 2)
        finally:
            self.store._open = vrai_open
        self.assertEqual(ouvertures, [])

    def test_bounds_are_half_open(self):
        self.recevoir(meta(1, received=T0), meta(2, received=T0 + HEURE))
        rows = self.store.stats_activity(T0, T0 + HEURE)
        self.assertEqual([r.received_at for r in rows], [T0])

    def test_a_duplicate_message_id_is_counted_once(self):
        self.recevoir(
            meta(1, msgid="<double@example.org>", received=T0 + HEURE),
            meta(2, msgid="<double@example.org>", received=T0),
        )
        self.assertEqual([r.received_at for r in self.lignes()], [T0])

    def test_a_reused_message_id_does_not_lend_its_delay(self):
        self.recevoir(
            meta(1, frm=DENIS, received=T0),
            meta(2, msgid="<m1@example.org>", frm=CAROLE, received=T0 + 1),
        )
        self.envoyer(self.reponse(10, 1, T0 + HEURE))
        rows = self.lignes(with_sender=True)
        self.assertEqual([r.sender for r in rows], [DENIS])
        self.assertEqual(rows[0].first_reply_at, T0 + HEURE)

    def test_messages_without_message_id_are_all_counted(self):
        self.recevoir(meta(1, msgid=""), meta(2, msgid=""), meta(3, msgid=""))
        self.assertEqual(len(self.lignes()), 3)

    def test_rule_log_rule_sends_counts_only_that_rule_and_send_outcomes(self):
        issues = ("sent", "queued", "held", "skipped", "failed", "pending")
        for index, outcome in enumerate(issues):
            self.store.rule_log_claim(
                "stats1", f"k{index}", outcome=outcome, at=T0 + index
            )
        self.store.rule_log_claim("autre", "k9", outcome="sent", at=T0)
        self.store.rule_log_claim("stats1", "vieux", outcome="sent", at=T0 - 1)
        self.assertEqual(self.store.rule_log_rule_sends("stats1", T0), 3)
        self.assertEqual(self.store.rule_log_rule_sends("stats1", T0 + 2), 1)
        self.assertEqual(self.store.rule_log_rule_sends("autre", T0), 1)

    def test_mark_auto_sent_many_ignores_empty_message_ids(self):
        self.recevoir(meta(1, msgid=""), meta(2))
        self.store.mark_auto_sent_many(
            [("", "", T0), ("  ", "", T0), ("<m2@example.org>", "", T0)]
        )
        self.assertEqual(len(self.lignes()), 1)


class TestStatsActivityEncrypted(ActivityCase):
    mode = "encrypted"

    def test_an_encrypted_cache_gives_the_same_rows(self):
        self.recevoir(
            meta(1, flags="\\Seen"),
            meta(2, frm=BRUNO, received=T0 + HEURE),
            meta(3, msgid="<m1@example.org>", received=T0 + 2 * HEURE),
        )
        self.envoyer(self.reponse(10, 1, T0 + 3 * HEURE))
        self.assertEqual(
            self.lignes(with_sender=True),
            [
                ActivityRow(T0, True, True, T0 + 3 * HEURE, CAROLE),
                ActivityRow(T0 + HEURE, False, False, None, BRUNO),
            ],
        )


if __name__ == "__main__":
    unittest.main()
