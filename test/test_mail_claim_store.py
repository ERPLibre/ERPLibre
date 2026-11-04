#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le cache et l'état du moteur gardent de la revendication des
messages : la table `rule_claim`, la limite par expéditeur qui compte les
envois d'une autre machine, le règlement des lignes `pending` d'une passe
morte, la conversion de cache et `claim_mode` dans `state.json`.

Caches clairs en dossier temporaire ; aucun serveur."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_mail_cache_convert import ConvertCase, compte

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.rules import storage
from script.todo.mail.rules.storage import EngineState
from script.todo.mail.store import RULE_LOG_SEND_LIKE, Store

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
REGLE = "regle-1"


class ClaimStoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = self.ouvrir()

    def ouvrir(self):
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        self.addCleanup(store.close)
        return store

    def tables(self, store=None):
        db = (store or self.store)._db()
        return {
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    def ligne(self, cle, outcome, reason=None, at=1000, sender=CAROLE):
        self.store.rule_log_claim(
            REGLE,
            cle,
            outcome=outcome,
            reason=reason,
            at=at,
            sender_hash=self.store.address_hash(sender),
        )


class TestClaimTable(ClaimStoreCase):
    def test_a_new_cache_has_the_claim_table(self):
        self.assertIn("rule_claim", self.tables())

    def test_an_existing_cache_gets_the_claim_table_at_opening(self):
        self.store._db().execute("DROP TABLE rule_claim")
        self.store._db().commit()
        self.store.close()
        store = self.ouvrir()
        self.assertIn("rule_claim", self.tables(store))
        self.assertEqual(store.rule_claim_intent(42, 1), "intent")

    def test_intent_is_written_once_and_returns_the_current_state(self):
        self.assertIsNone(self.store.rule_claim_state(42, 1))
        self.assertEqual(self.store.rule_claim_intent(42, 1), "intent")
        self.assertEqual(self.store.rule_claim_intent(42, 1), "intent")
        self.store.rule_claim_set(42, 1, "owned", mode="atomic")
        self.assertEqual(self.store.rule_claim_intent(42, 1), "owned")
        self.assertEqual(self.store.rule_claim_state(42, 1), "owned")

    def test_owned_lost_and_unclaimed_are_final(self):
        for uid, etat in enumerate(("owned", "lost", "unclaimed"), start=1):
            with self.subTest(etat=etat):
                self.assertEqual(
                    self.store.rule_claim_set(42, uid, etat), etat
                )
                for autre in ("owned", "lost", "unclaimed"):
                    self.assertEqual(
                        self.store.rule_claim_set(42, uid, autre), etat
                    )
                self.store.rule_claim_drop_intent(42, uid)
                self.assertEqual(self.store.rule_claim_state(42, uid), etat)

    def test_an_unknown_final_state_is_refused_before_any_write(self):
        for etat in ("intent", "retry", "autre"):
            with self.assertRaises(ValueError):
                self.store.rule_claim_set(42, 1, etat)
        self.assertIsNone(self.store.rule_claim_state(42, 1))

    def test_the_same_uid_under_another_uidvalidity_is_another_message(self):
        self.store.rule_claim_set(42, 1, "lost")
        self.assertIsNone(self.store.rule_claim_state(43, 1))
        self.assertEqual(self.store.rule_claim_intent(43, 1), "intent")
        self.assertEqual(self.store.rule_claim_state(42, 1), "lost")

    def test_dropping_an_intent_returns_it_to_retry_and_keeps_the_failures(
        self,
    ):
        self.assertEqual(self.store.rule_claim_failed(42, 1), 1)
        self.store.rule_claim_intent(42, 1)
        self.assertEqual(self.store.rule_claim_failed(42, 1), 2)
        self.store.rule_claim_drop_intent(42, 1)
        self.assertEqual(self.store.rule_claim_state(42, 1), "retry")
        self.assertEqual(self.store.rule_claim_failed(42, 1), 3)

    def test_drop_intent_leaves_a_final_state_untouched(self):
        self.store.rule_claim_set(42, 1, "owned")
        self.store.rule_claim_drop_intent(42, 1)
        self.assertEqual(self.store.rule_claim_state(42, 1), "owned")
        self.store.rule_claim_drop_intent(42, 2)
        self.assertIsNone(self.store.rule_claim_state(42, 2))

    def test_claim_failures_are_counted_without_changing_the_state(self):
        self.assertEqual(self.store.rule_claim_failed(42, 1), 1)
        self.assertEqual(self.store.rule_claim_state(42, 1), "retry")
        self.store.rule_claim_intent(42, 1)
        self.assertEqual(self.store.rule_claim_failed(42, 1), 2)
        self.assertEqual(self.store.rule_claim_state(42, 1), "intent")

    def test_an_intent_can_follow_a_retry_and_a_final_state_can_follow_both(
        self,
    ):
        self.store.rule_claim_failed(42, 1)
        self.assertEqual(self.store.rule_claim_intent(42, 1), "intent")
        self.assertEqual(
            self.store.rule_claim_set(42, 1, "owned", mode="plain"), "owned"
        )
        self.store.rule_claim_failed(42, 2)
        self.assertEqual(
            self.store.rule_claim_set(42, 2, "unclaimed", mode="none"),
            "unclaimed",
        )
        modes = dict(
            self.store._db().execute("SELECT uid, mode FROM rule_claim")
        )
        self.assertEqual(modes, {1: "plain", 2: "none"})

    def test_the_claim_table_has_no_time_column(self):
        colonnes = [
            r[1]
            for r in self.store._db().execute("PRAGMA table_info(rule_claim)")
        ]
        self.assertEqual(
            colonnes, ["id", "uidvalidity", "uid", "state", "mode", "failures"]
        )

    def test_purge_all_keeps_the_claims(self):
        self.store.rule_claim_set(42, 1, "owned")
        self.store.purge_all()
        self.assertEqual(self.store.rule_claim_state(42, 1), "owned")


class TestRuleLogWithClaims(ClaimStoreCase):
    def test_last_send_counts_claimed_elsewhere_claim_uncertain_and_send_uncertain(
        self,
    ):
        self.assertEqual(
            RULE_LOG_SEND_LIKE,
            (
                ("skipped", "claimed_elsewhere"),
                ("skipped", "claim_uncertain"),
                ("failed", "send_uncertain"),
            ),
        )
        empreinte = self.store.address_hash(CAROLE)
        self.ligne("k1", "skipped", "throttled", at=1000)
        self.ligne("k2", "failed", "smtp_permanent", at=2000)
        self.ligne("k3", "skipped", "claim_gone", at=2500)
        self.assertIsNone(self.store.rule_log_last_send(REGLE, empreinte))
        for at, (issue, raison) in enumerate(RULE_LOG_SEND_LIKE, start=3):
            with self.subTest(raison=raison):
                self.ligne(f"s{at}", issue, raison, at=at * 1000)
                self.assertEqual(
                    self.store.rule_log_last_send(REGLE, empreinte), at * 1000
                )

    def test_rule_log_state_reads_outcome_and_reason_or_none(self):
        self.ligne("k1", "pending", "ready")
        etat = self.store.rule_log_state(REGLE, "k1")
        self.assertEqual(
            (etat["outcome"], etat["reason"]), ("pending", "ready")
        )
        self.assertIsNone(self.store.rule_log_state(REGLE, "absente"))

    def test_resume_deletes_ready_rows_only(self):
        self.ligne("ready", "pending", "ready")
        self.ligne("sending", "pending", "sending")
        self.store.rule_log_resume()
        self.assertIsNone(self.store.rule_log_state(REGLE, "ready"))
        self.assertIsNotNone(self.store.rule_log_state(REGLE, "sending"))

    def test_resume_fails_sending_and_reasonless_pending_rows_as_send_uncertain(
        self,
    ):
        self.ligne("sending", "pending", "sending")
        self.ligne("ancienne", "pending", None)
        self.store.rule_log_resume()
        for cle in ("sending", "ancienne"):
            etat = self.store.rule_log_state(REGLE, cle)
            self.assertEqual(
                (etat["outcome"], etat["reason"]), ("failed", "send_uncertain")
            )

    def test_resume_leaves_queued_held_and_terminal_rows_untouched(self):
        lignes = (
            ("q", "queued", "offline"),
            ("h", "held", "hold_first"),
            ("s", "sent", None),
            ("p", "partial", "rcpt_retry"),
            ("k", "skipped", "claimed_elsewhere"),
            ("f", "failed", "smtp_permanent"),
            ("e", "expired", "rule_changed"),
        )
        for cle, issue, raison in lignes:
            self.ligne(cle, issue, raison)
        self.assertEqual(self.store.rule_log_resume(), (0, 0))
        for cle, issue, raison in lignes:
            etat = self.store.rule_log_state(REGLE, cle)
            self.assertEqual(
                (etat["outcome"], etat["reason"]), (issue, raison)
            )

    def test_resume_returns_its_two_counts(self):
        self.ligne("r1", "pending", "ready")
        self.ligne("r2", "pending", "ready")
        self.ligne("s1", "pending", "sending")
        self.assertEqual(self.store.rule_log_resume(), (2, 1))
        self.assertEqual(self.store.rule_log_resume(), (0, 0))


class TestClaimConversion(ConvertCase):
    def test_a_conversion_keeps_the_claims(self):
        self.creer("clear")
        store = Store(compte(), mode="clear", base=self.base)
        store.open()
        store.rule_claim_set(7, 1, "owned", mode="atomic")
        store.rule_claim_set(7, 2, "lost", mode="plain")
        store.rule_claim_intent(7, 3)
        store.rule_claim_failed(7, 3)
        store.close()
        avant = self.lire("SELECT * FROM rule_claim ORDER BY id")
        self.assertEqual(len(avant), 3)
        self.convertir("encrypted")
        self.assertEqual(
            self.lire("SELECT * FROM rule_claim ORDER BY id"), avant
        )
        self.convertir("clear")
        self.assertEqual(
            self.lire("SELECT * FROM rule_claim ORDER BY id"), avant
        )
        store = self.ouvrir()
        self.assertEqual(store.rule_claim_state(7, 1), "owned")
        self.assertEqual(store.rule_claim_state(7, 3), "intent")


class TestEngineStateClaimMode(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def ecrire(self, **champs):
        storage.save_state("perso", EngineState(cursor=3), base=self.base)
        chemin = storage.state_path("perso", self.base)
        data = json.loads(chemin.read_text())
        data.update(champs)
        chemin.write_text(json.dumps(data))

    def test_the_engine_state_round_trips_the_claim_mode(self):
        for mode in ("atomic", "plain", "none"):
            with self.subTest(mode=mode):
                storage.save_state(
                    "perso",
                    EngineState(cursor=3, claim_mode=mode),
                    base=self.base,
                )
                lu = storage.load_state("perso", self.base)
                self.assertEqual((lu.cursor, lu.claim_mode), (3, mode))
                self.assertEqual(
                    storage.load_claim_mode("perso", self.base), mode
                )

    def test_an_unknown_claim_mode_reads_as_empty(self):
        self.ecrire(claim_mode="quantique")
        self.assertEqual(storage.load_state("perso", self.base).claim_mode, "")
        self.assertEqual(EngineState().claim_mode, "")

    def test_a_claim_mode_of_another_type_reads_as_empty_without_raising(
        self,
    ):
        for valeur in (3, ["plain"], True):
            with self.subTest(valeur=valeur):
                self.ecrire(claim_mode=valeur)
                lu = storage.load_state("perso", self.base)
                self.assertEqual((lu.cursor, lu.claim_mode), (3, ""))

    def test_load_claim_mode_never_raises_on_an_unreadable_state(self):
        self.assertEqual(storage.load_claim_mode("perso", self.base), "")
        storage.account_dir("perso", self.base)
        storage.state_path("perso", self.base).write_text("{pas du json")
        self.assertEqual(storage.load_claim_mode("perso", self.base), "")
        self.assertEqual(storage.load_claim_mode("../x", self.base), "")


if __name__ == "__main__":
    unittest.main()
