#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le cache garde pour libérer un message : l'origine scellée de
chaque ligne du journal, la libération à la main d'une revendication
incertaine ou en échec, son règlement après la réévaluation, et les
écritures de la file qu'un relâchement revendiqué demande.

Caches en dossier temporaire ; aucun serveur."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mail_cache_fixtures import FauxCoffre
from test_mail_cache_convert import ConvertCase, compte

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules.model import OUTCOMES
from script.todo.mail.store import (
    RELEASE_RESULTS,
    RULE_LOG_RELEASABLE,
    MessageMeta,
    Store,
)

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
REGLE = "regle-1"
AUTRE = "regle-2"
UIDV = 42


def meta(uid, msgid=""):
    return MessageMeta(
        uid=uid,
        date=1000 + uid,
        size=10,
        flags="",
        msgid=msgid,
        frm=CAROLE,
        to=OWN,
        subject=f"Question {uid}",
        snippet="",
    )


class ReleaseStoreCase(unittest.TestCase):
    MODE = "clear"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = self.ouvrir()
        self.fid = self.store.upsert_folder("INBOX", uidvalidity=UIDV)

    def ouvrir(self):
        store = Store(
            self.account,
            mode=self.MODE,
            secrets=FauxCoffre() if self.MODE == "encrypted" else None,
            base=self.base,
        )
        store.open()
        self.addCleanup(store.close)
        return store

    def recevoir(self, *uids, msgid=None):
        """Des messages dans le cache d'INBOX ; Message-ID `<uid@…>` par
        défaut, `msgid` pour tous sinon."""
        self.store.upsert_messages(
            self.fid,
            [
                meta(u, f"<{u}@example.net>" if msgid is None else msgid)
                for u in uids
            ],
        )

    def cle(self, uid, msgid=None):
        msgid = f"<{uid}@example.net>" if msgid is None else msgid
        return self.store.message_key(msgid, UIDV, uid)

    def ligne(
        self,
        uid=1,
        outcome="skipped",
        reason="claim_uncertain",
        *,
        rule=REGLE,
        at=1000,
        origin="auto",
        msgid=None,
    ):
        msgid = f"<{uid}@example.net>" if msgid is None else msgid
        if origin == "auto":
            origin = (UIDV, uid)
        return self.store.rule_log_claim(
            rule,
            self.store.message_key(msgid, UIDV, uid),
            outcome=outcome,
            reason=reason,
            at=at,
            sender=CAROLE,
            subject=f"Question {uid}",
            sender_hash=self.store.address_hash(CAROLE),
            msg_ref=self.store.message_ref(msgid, UIDV, uid),
            origin=origin,
        )

    def inbox(self):
        return {"inbox_folder_id": self.fid, "inbox_uidvalidity": UIDV}

    def liberer(self, uid=1, rule=REGLE, msgid=None):
        return self.store.rule_log_release(
            rule,
            self.cle(uid, msgid),
            inbox_folder_id=self.fid,
            inbox_uidvalidity=UIDV,
        )

    def etat(self, uid=1, rule=REGLE, msgid=None):
        e = self.store.rule_log_state(rule, self.cle(uid, msgid))
        return None if e is None else (e["outcome"], e["reason"])

    def echecs(self, uid=1):
        r = (
            self.store._db()
            .execute(
                "SELECT failures FROM rule_claim WHERE uidvalidity = ?"
                " AND uid = ?",
                (UIDV, uid),
            )
            .fetchone()
        )
        return None if r is None else r[0]

    def brut_journal(self):
        return [
            tuple(r)
            for r in self.store._db().execute(
                "SELECT * FROM rule_log ORDER BY id"
            )
        ]

    def brut_revendications(self):
        return [
            tuple(r)
            for r in self.store._db().execute(
                "SELECT * FROM rule_claim ORDER BY id"
            )
        ]


class TestOrigin(ReleaseStoreCase):
    def colonnes(self, store=None):
        return {
            r["name"]
            for r in (store or self.store)
            ._db()
            .execute("PRAGMA table_info(rule_log)")
        }

    def test_a_new_cache_has_the_origin_column_and_an_old_one_gets_it(self):
        self.assertIn("sealed_origin", self.colonnes())
        db = self.store._db()
        colonnes = [
            r["name"] for r in db.execute("PRAGMA table_info(rule_log)")
        ]
        gardees = [c for c in colonnes if c != "sealed_origin"]
        liste = ", ".join(gardees)
        db.execute(f"CREATE TABLE ancien AS SELECT {liste} FROM rule_log")
        db.execute("DROP TABLE rule_log")
        db.execute("ALTER TABLE ancien RENAME TO rule_log")
        db.commit()
        self.assertNotIn("sealed_origin", self.colonnes())
        self.store.close()
        store = self.ouvrir()
        self.assertIn("sealed_origin", self.colonnes(store))

    def test_the_origin_is_read_back(self):
        self.ligne(7)
        self.assertEqual(
            self.store.rule_log_origin(REGLE, self.cle(7)), (UIDV, 7)
        )

    def test_a_row_without_origin_or_with_a_malformed_one_reads_none(self):
        self.ligne(1, origin=None)
        self.assertIsNone(self.store.rule_log_origin(REGLE, self.cle(1)))
        self.assertIsNone(self.store.rule_log_origin(REGLE, "absente"))
        for valeur in ("x:1", "42", "42:", ":7", "-1:3", "0:3", "42:7:1"):
            with self.subTest(valeur=valeur):
                self.store._db().execute(
                    "UPDATE rule_log SET sealed_origin = ?",
                    (self.store._seal(valeur),),
                )
                self.store._db().commit()
                self.assertIsNone(
                    self.store.rule_log_origin(REGLE, self.cle(1))
                )


class TestSealedOrigin(ReleaseStoreCase):
    MODE = "encrypted"

    def test_the_origin_is_sealed_and_read_back(self):
        self.ligne(7)
        brut = (
            self.store._db()
            .execute("SELECT sealed_origin FROM rule_log")
            .fetchone()[0]
        )
        self.assertNotIn(b"42:7", bytes(brut))
        self.assertEqual(
            self.store.rule_log_origin(REGLE, self.cle(7)), (UIDV, 7)
        )


class TestReleasedRows(ReleaseStoreCase):
    def test_a_released_row_is_not_seen_as_logged(self):
        self.recevoir(1)
        self.ligne(1)
        self.assertTrue(self.store.rule_log_seen(REGLE, self.cle(1)))
        self.assertEqual(self.liberer(1), "released")
        self.assertFalse(self.store.rule_log_seen(REGLE, self.cle(1)))

    def test_a_released_row_is_taken_over_by_the_next_claim_once(self):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.assertTrue(self.ligne(1, "pending", "ready", at=5000))
        self.assertEqual(self.etat(1), ("pending", "ready_released"))
        self.assertFalse(self.ligne(1, "pending", "ready", at=6000))
        self.assertEqual(self.store.rule_log_entries()[0]["at"], 5000)

    def test_a_dead_pass_gives_a_taken_over_release_back(self):
        self.recevoir(1)
        self.recevoir(2)
        self.ligne(1)
        self.liberer(1)
        self.assertTrue(self.ligne(1, "pending", "ready"))
        self.assertTrue(self.ligne(2, "pending", "ready"))
        self.assertEqual(self.store.rule_log_resume(), (1, 0))
        self.assertEqual(self.etat(1), ("skipped", "released"))
        self.assertIsNone(self.etat(2))
        self.assertEqual(self.store.rule_log_released_uids(UIDV), [1])

    def test_a_taken_over_release_already_sending_is_uncertain(self):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.assertTrue(self.ligne(1, "pending", "ready"))
        self.store.rule_log_set_outcome(
            REGLE, self.cle(1), "pending", "sending"
        )
        self.assertEqual(self.store.rule_log_resume(), (0, 1))
        self.assertEqual(self.etat(1), ("failed", "send_uncertain"))
        self.assertEqual(self.store.rule_log_released_uids(UIDV), [])

    def test_any_other_row_still_blocks_a_second_claim(self):
        couples = [(o, None) for o in OUTCOMES] + [
            ("skipped", "claim_uncertain"),
            ("skipped", "release_unmatched"),
        ]
        for outcome, reason in couples:
            with self.subTest(outcome=outcome, reason=reason):
                self.store._db().execute("DELETE FROM rule_log")
                self.store._db().commit()
                self.assertTrue(self.ligne(1, outcome, reason))
                self.assertFalse(self.ligne(1, "pending", "ready"))
                self.assertEqual(self.etat(1), (outcome, reason))

    def test_taking_over_a_released_row_clears_the_departure_columns(self):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.store._db().execute(
            "UPDATE rule_log SET sent_at = 9, rcpt_total = 2,"
            " rcpt_dropped = '550', rcpt_pending = '450',"
            " retry_sent_at = 9"
        )
        self.store._db().commit()
        self.assertTrue(self.ligne(1, "pending", "ready"))
        ligne = self.store._db().execute("SELECT * FROM rule_log").fetchone()
        self.assertEqual(
            (
                ligne["sent_at"],
                ligne["rcpt_total"],
                ligne["rcpt_dropped"],
                ligne["rcpt_pending"],
                ligne["retry_sent_at"],
            ),
            (None,) * 5,
        )

    def test_released_rows_count_neither_as_pending_nor_for_the_sender_limit(
        self,
    ):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.assertEqual(self.store.rule_log_resume(), (0, 0))
        self.assertEqual(self.etat(1), ("skipped", "released"))
        self.assertIsNone(
            self.store.rule_log_last_send(
                REGLE, self.store.address_hash(CAROLE)
            )
        )


class TestRelease(ReleaseStoreCase):
    def test_release_marks_every_row_of_the_message_with_its_issue(self):
        self.recevoir(1)
        self.store.rule_claim_intent(UIDV, 1)
        self.ligne(1, rule=REGLE)
        self.ligne(1, rule=AUTRE)
        self.assertEqual(self.liberer(1), "released")
        self.assertEqual(self.etat(1, REGLE), ("skipped", "released"))
        self.assertEqual(self.etat(1, AUTRE), ("skipped", "released"))
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "released")
        self.assertEqual(self.echecs(1), 0)

    def test_a_failed_claim_is_released_with_its_failures_reset(self):
        """Une revendication en échec n'est pas affirmée : ses échecs
        repartent de zéro, son état reste, et la passe suivante
        revendique normalement."""
        self.recevoir(1)
        for _ in range(5):
            self.store.rule_claim_failed(UIDV, 1)
        self.ligne(1, "failed", "claim_failed")
        self.ligne(1, "failed", "claim_failed", rule=AUTRE)
        self.assertEqual(self.liberer(1), "released")
        self.assertEqual(self.etat(1, REGLE), ("skipped", "released"))
        self.assertEqual(self.etat(1, AUTRE), ("skipped", "released"))
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "retry")
        self.assertEqual(self.echecs(1), 0)

    def test_a_failed_claim_after_an_unknown_store_keeps_its_intent(self):
        self.recevoir(1)
        self.store.rule_claim_intent(UIDV, 1)
        self.store.rule_claim_failed(UIDV, 1)
        self.ligne(1, "failed", "claim_failed")
        self.liberer(1)
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "intent")
        self.assertEqual(self.echecs(1), 0)

    def test_release_leaves_the_rows_of_the_message_with_another_issue(self):
        self.recevoir(1)
        self.ligne(1, rule=REGLE)
        self.ligne(1, "failed", "claim_failed", rule=AUTRE)
        self.liberer(1, rule=REGLE)
        self.assertEqual(self.etat(1, AUTRE), ("failed", "claim_failed"))

    def test_release_leaves_a_row_of_another_copy_with_the_same_message_id(
        self,
    ):
        self.recevoir(1, 2, msgid="<double@example.net>")
        self.ligne(1, rule=REGLE, msgid="<double@example.net>")
        self.ligne(2, rule=AUTRE, msgid="<double@example.net>")
        self.assertEqual(
            self.liberer(1, msgid="<double@example.net>"), "released"
        )
        self.assertEqual(
            self.etat(2, AUTRE, msgid="<double@example.net>"),
            ("skipped", "claim_uncertain"),
        )
        self.assertIsNone(self.store.rule_claim_state(UIDV, 2))

    def test_release_refuses_a_row_that_is_not_releasable(self):
        self.recevoir(1)
        for outcome, reason in (
            ("skipped", "claimed_elsewhere"),
            ("failed", "send_uncertain"),
            ("sent", None),
            (None, None),
        ):
            with self.subTest(outcome=outcome, reason=reason):
                self.store._db().execute("DELETE FROM rule_log")
                self.store._db().commit()
                if outcome:
                    self.ligne(1, outcome, reason)
                avant = (self.brut_journal(), self.brut_revendications())
                self.assertEqual(self.liberer(1), "not_releasable")
                self.assertEqual(
                    (self.brut_journal(), self.brut_revendications()), avant
                )

    def test_release_refuses_a_row_without_origin(self):
        self.recevoir(1, 2, msgid="<double@example.net>")
        self.ligne(1, origin=None, msgid="<double@example.net>")
        avant = (self.brut_journal(), self.brut_revendications())
        self.assertEqual(
            self.liberer(1, msgid="<double@example.net>"), "no_origin"
        )
        self.store._db().execute("DELETE FROM messages")
        self.store._db().commit()
        self.assertEqual(
            self.liberer(1, msgid="<double@example.net>"), "no_origin"
        )
        self.assertEqual(
            (self.brut_journal(), self.brut_revendications()), avant
        )

    def test_release_refuses_a_renumbered_inbox(self):
        self.recevoir(1)
        self.ligne(1, origin=(41, 1))
        self.store.rule_claim_intent(UIDV, 1)
        avant = (self.brut_journal(), self.brut_revendications())
        self.assertEqual(self.liberer(1), "renumbered")
        self.assertEqual(
            (self.brut_journal(), self.brut_revendications()), avant
        )

    def test_release_refuses_a_message_no_longer_in_the_inbox_cache(self):
        self.ligne(1)
        self.store.rule_claim_intent(UIDV, 1)
        avant = (self.brut_journal(), self.brut_revendications())
        self.assertEqual(self.liberer(1), "absent")
        self.assertEqual(
            (self.brut_journal(), self.brut_revendications()), avant
        )

    def test_release_finds_the_origin_of_an_older_row(self):
        with self.subTest("sans Message-ID, par la préimage"):
            self.recevoir(3, msgid="")
            self.ligne(3, origin=None, msgid="")
            self.assertEqual(self.liberer(3, msgid=""), "released")
            self.assertEqual(
                self.store.rule_log_origin(REGLE, self.cle(3, "")), (UIDV, 3)
            )
        with self.subTest("une seule copie, par l'empreinte"):
            self.recevoir(4)
            self.ligne(4, origin=None)
            self.assertEqual(self.liberer(4), "released")
            self.assertEqual(
                self.store.rule_log_origin(REGLE, self.cle(4)), (UIDV, 4)
            )

    def test_release_keeps_the_time_of_the_row(self):
        self.recevoir(1)
        self.ligne(1, at=1234)
        self.liberer(1)
        self.assertEqual(self.store.rule_log_entries()[0]["at"], 1234)

    def test_release_overrides_any_claim_state(self):
        for etat in ("intent", "retry", "lost", None):
            with self.subTest(etat=etat):
                self.store._db().execute("DELETE FROM rule_log")
                self.store._db().execute("DELETE FROM rule_claim")
                self.store._db().commit()
                self.recevoir(1)
                if etat is not None:
                    self.store._db().execute(
                        "INSERT INTO rule_claim(uidvalidity, uid, state,"
                        " failures) VALUES(?, 1, ?, 5)",
                        (UIDV, etat),
                    )
                    self.store._db().commit()
                self.ligne(1)
                self.assertEqual(self.liberer(1), "released")
                self.assertEqual(
                    self.store.rule_claim_state(UIDV, 1), "released"
                )
                self.assertEqual(self.echecs(1), 0)

    def test_the_results_are_those_announced(self):
        self.assertEqual(
            RELEASE_RESULTS,
            (
                "released",
                "not_releasable",
                "no_origin",
                "renumbered",
                "absent",
            ),
        )
        self.assertEqual(
            RULE_LOG_RELEASABLE,
            (("skipped", "claim_uncertain"), ("failed", "claim_failed")),
        )


class TestReleasableLists(ReleaseStoreCase):
    def test_releasable_offers_only_rows_whose_origin_is_found(self):
        self.recevoir(1, 2, msgid="<double@example.net>")
        self.ligne(1, origin=None, msgid="<double@example.net>")
        self.recevoir(5)
        self.ligne(5, origin=None, at=900)
        offertes = self.store.rule_log_releasable(
            inbox_folder_id=self.fid, inbox_uidvalidity=UIDV
        )
        self.assertEqual([e["msg_key"] for e in offertes], [self.cle(5)])
        par_cle = {
            e["msg_key"]: e["releasable"]
            for e in self.store.rule_log_entries(
                inbox_folder_id=self.fid, inbox_uidvalidity=UIDV
            )
        }
        self.assertFalse(par_cle[self.cle(1, "<double@example.net>")])
        self.assertTrue(par_cle[self.cle(5)])

    def test_releasable_lists_only_uncertain_and_failed_claims_most_recent_first(
        self,
    ):
        self.recevoir(1, 2, 3, 4, 5)
        self.ligne(1, at=100)
        self.ligne(2, "failed", "claim_failed", at=300)
        self.ligne(3, "skipped", "claimed_elsewhere", at=400)
        self.ligne(4, "sent", None, at=500)
        self.ligne(5, at=200)
        offertes = self.store.rule_log_releasable(**self.inbox())
        self.assertEqual(
            [e["msg_key"] for e in offertes],
            [self.cle(2), self.cle(5), self.cle(1)],
        )
        self.assertTrue(all(e["releasable"] for e in offertes))
        self.assertEqual(
            len(self.store.rule_log_releasable(limit=2, **self.inbox())), 2
        )

    def test_a_row_the_release_would_refuse_is_neither_offered_nor_releasable(
        self,
    ):
        self.recevoir(1, 3)
        self.ligne(1, origin=(UIDV - 1, 1))
        self.ligne(2)
        self.ligne(3)
        self.ligne(4, "sent", None)
        self.assertEqual(
            [
                e["msg_key"]
                for e in self.store.rule_log_releasable(**self.inbox())
            ],
            [self.cle(3)],
        )
        par_cle = {
            e["msg_key"]: e["releasable"]
            for e in self.store.rule_log_entries(**self.inbox())
        }
        self.assertEqual(
            par_cle,
            {
                self.cle(1): False,
                self.cle(2): False,
                self.cle(3): True,
                self.cle(4): False,
            },
        )
        self.assertEqual(self.store.rule_log_releasable(), [])
        for uid, refus in (
            (1, "renumbered"),
            (2, "absent"),
            (3, None),
            (4, "not_releasable"),
        ):
            with self.subTest(uid=uid):
                self.assertEqual(
                    self.store.rule_log_release_check(
                        REGLE, self.cle(uid), **self.inbox()
                    ),
                    refus,
                )
                if refus is not None:
                    self.assertEqual(self.liberer(uid), refus)

    def test_log_entries_carry_id_key_and_releasable(self):
        self.recevoir(1, 2)
        self.ligne(1)
        self.ligne(2, "sent", None)
        entrees = {
            e["msg_key"]: e
            for e in self.store.rule_log_entries(**self.inbox())
        }
        self.assertTrue(entrees[self.cle(1)]["releasable"])
        self.assertFalse(entrees[self.cle(2)]["releasable"])
        ids = {
            r["msg_key"]: r["id"]
            for r in self.store._db().execute(
                "SELECT id, msg_key FROM rule_log"
            )
        }
        for cle, entree in entrees.items():
            self.assertEqual(entree["id"], ids[cle])

    def test_released_uids_are_listed_per_uidvalidity(self):
        self.recevoir(3, 1)
        self.ligne(3)
        self.ligne(1)
        self.ligne(1, rule=AUTRE)
        self.liberer(3)
        self.liberer(1)
        self.ligne(9, origin=(41, 9))
        self.store._db().execute(
            "UPDATE rule_log SET reason = 'released' WHERE sealed_origin = ?",
            (self.store._seal("41:9"),),
        )
        self.store._db().commit()
        self.assertEqual(self.store.rule_log_released_uids(UIDV), [1, 3])
        self.assertEqual(self.store.rule_log_released_uids(41), [9])


class TestSettle(ReleaseStoreCase):
    def test_settle_marks_released_rows_unmatched_and_owns_the_claim(self):
        self.recevoir(1)
        self.ligne(1)
        self.ligne(1, rule=AUTRE)
        self.liberer(1)
        self.ligne(1, "sent", None, rule=AUTRE)
        self.store._db().execute(
            "UPDATE rule_log SET outcome = 'sent', reason = NULL"
            " WHERE rule_id = ?",
            (AUTRE,),
        )
        self.store._db().commit()
        self.assertEqual(
            self.store.rule_release_settle(UIDV, 1, gone=False), 1
        )
        self.assertEqual(self.etat(1), ("skipped", "release_unmatched"))
        self.assertEqual(self.etat(1, AUTRE), ("sent", None))
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "owned")

    def test_settle_of_a_gone_message_logs_claim_gone(self):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.assertEqual(self.store.rule_release_settle(UIDV, 1, gone=True), 1)
        self.assertEqual(self.etat(1), ("skipped", "claim_gone"))
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "owned")

    def test_settle_leaves_the_rows_of_other_messages(self):
        self.recevoir(1, 2)
        self.ligne(1)
        self.ligne(2)
        self.liberer(1)
        self.liberer(2)
        self.store.rule_release_settle(UIDV, 1, gone=False)
        self.assertEqual(self.etat(2), ("skipped", "released"))
        self.assertEqual(self.store.rule_claim_state(UIDV, 2), "released")

    def test_settle_stale_closes_released_rows_of_another_uidvalidity(self):
        self.recevoir(1)
        self.ligne(1)
        self.liberer(1)
        self.ligne(9, origin=(41, 9))
        self.store._db().execute(
            "UPDATE rule_log SET reason = 'released' WHERE sealed_origin = ?",
            (self.store._seal("41:9"),),
        )
        self.store.rule_claim_affirm(41, 9, "released")
        self.store._db().commit()
        self.assertEqual(self.store.rule_release_settle_stale(UIDV), 1)
        self.assertEqual(self.etat(9), ("skipped", "claim_gone"))
        self.assertEqual(self.store.rule_claim_state(41, 9), "owned")
        self.assertEqual(self.etat(1), ("skipped", "released"))
        self.assertEqual(self.store.rule_claim_state(UIDV, 1), "released")


class TestAffirm(ReleaseStoreCase):
    def test_affirm_writes_owned_or_released_and_refuses_any_other_state(
        self,
    ):
        self.store.rule_claim_intent(UIDV, 1)
        self.store.rule_claim_failed(UIDV, 1)
        self.assertEqual(
            self.store.rule_claim_affirm(UIDV, 1, "owned"), "owned"
        )
        self.assertEqual(self.echecs(1), 0)
        self.store.rule_claim_set(UIDV, 2, "lost")
        self.assertEqual(
            self.store.rule_claim_affirm(UIDV, 2, "released"), "released"
        )
        avant = self.brut_revendications()
        for etat in ("lost", "intent", "x"):
            with self.subTest(etat=etat):
                with self.assertRaises(ValueError):
                    self.store.rule_claim_affirm(UIDV, 3, etat)
        self.assertEqual(self.brut_revendications(), avant)


class TestOutboxForRelease(ReleaseStoreCase):
    def retenir(self, expires_at=5000, uid=1):
        self.ligne(uid, "pending", "ready")
        return self.store.queue_auto(
            b"Subject: s\r\n\r\nx",
            CAROLE,
            "s",
            held=True,
            rule_id=REGLE,
            source_key=self.cle(uid),
            expires_at=expires_at,
            outcome="held",
            reason="hold_first",
        )

    def expiration(self, ident):
        return self.store.queued_entry(ident)["expires_at"]

    def test_unhold_claimed_releases_and_pushes_back_a_close_deadline(self):
        with self.subTest("échéance passée"):
            ident = self.retenir(expires_at=100)
            self.assertTrue(
                self.store.outbox_unhold_claimed(ident, expires_floor=1060)
            )
            self.assertFalse(self.store.queued_entry(ident)["held"])
            self.assertEqual(self.expiration(ident), 1060)
        with self.subTest("échéance lointaine"):
            ident = self.retenir(expires_at=9000, uid=2)
            self.store.outbox_unhold_claimed(ident, expires_floor=1060)
            self.assertEqual(self.expiration(ident), 9000)
        with self.subTest("sans échéance"):
            ident = self.retenir(expires_at=5000, uid=3)
            self.store._db().execute(
                "UPDATE outbox SET expires_at = NULL WHERE id = ?", (ident,)
            )
            self.store._db().commit()
            self.store.outbox_unhold_claimed(ident, expires_floor=1060)
            self.assertIsNone(self.expiration(ident))
        with self.subTest("entrée non retenue"):
            self.assertFalse(
                self.store.outbox_unhold_claimed(ident, expires_floor=99999)
            )
            self.assertIsNone(self.expiration(ident))

    def test_drop_claimed_removes_a_held_entry_and_logs_claimed_elsewhere(
        self,
    ):
        ident = self.retenir()
        self.assertEqual(self.etat(1), ("held", "hold_first"))
        self.assertTrue(
            self.store.outbox_drop_claimed(ident, REGLE, self.cle(1))
        )
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.etat(1), ("skipped", "claimed_elsewhere"))

    def test_drop_claimed_refuses_an_entry_not_held_or_reserved(self):
        ident = self.retenir()
        self.store.set_held(ident, False)
        self.assertFalse(
            self.store.outbox_drop_claimed(ident, REGLE, self.cle(1))
        )
        self.store.set_held(ident, True)
        self.assertTrue(self.store.outbox_claim(ident, 1000))
        self.assertFalse(
            self.store.outbox_drop_claimed(ident, REGLE, self.cle(1))
        )
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.etat(1), ("held", "hold_first"))

    def test_drop_claimed_is_one_transaction(self):
        ident = self.retenir()

        def leve(*_a, **_k):
            raise RuntimeError("panne")

        with mock.patch.object(self.store, "_avancer_issue", leve):
            with self.assertRaises(RuntimeError):
                self.store.outbox_drop_claimed(ident, REGLE, self.cle(1))
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.etat(1), ("held", "hold_first"))

    def test_message_flags_reads_the_cache_or_none(self):
        self.recevoir(1)
        self.assertEqual(self.store.message_flags(self.fid, 1), "")
        self.store.update_flags(self.fid, 1, "\\Seen $ErpLibreRule")
        self.assertEqual(
            self.store.message_flags(self.fid, 1), "\\Seen $ErpLibreRule"
        )
        self.assertIsNone(self.store.message_flags(self.fid, 2))


class TestReleaseConversion(ConvertCase):
    def test_a_conversion_keeps_the_origin_and_the_released_state(self):
        self.creer("clear")
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        ref = "<7@example.net>"
        store.rule_log_claim(
            REGLE,
            store.message_key(ref, UIDV, 7),
            outcome="skipped",
            reason="released",
            at=1000,
            msg_ref=ref,
            origin=(UIDV, 7),
        )
        store.rule_claim_affirm(UIDV, 7, "released")
        store.close()
        for cible in ("encrypted", "clear"):
            self.convertir(cible)
            store = self.ouvrir()
            try:
                self.assertEqual(
                    store.rule_log_origin(
                        REGLE, store.message_key(ref, UIDV, 7)
                    ),
                    (UIDV, 7),
                    cible,
                )
                self.assertEqual(store.rule_claim_state(UIDV, 7), "released")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
