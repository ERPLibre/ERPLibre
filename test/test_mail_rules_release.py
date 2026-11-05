#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur des règles face aux deux gestes qui lèvent une décision :
une retenue qui ne revendique plus son message, la passe qui retire une
retenue dont le message porte le mot-clé d'une autre machine, et la
réévaluation d'un message libéré à la main.

Serveur en mémoire avec revendication (`ClaimImap`) ; la libération est
faite ici par le cache (`rule_log_release`), les gestes eux-mêmes sont
dans `test_mail_release_held.py`."""

import unittest
from unittest import mock

from test_mail_rules_claim import ClaimCase
from test_mail_rules_engine import BRUNO, HOUR, T0, Imap
from test_mail_service_run import SECRET_IMAP, ServiceCase

from script.todo.mail.claim import CLAIM_KEYWORD, has_claim
from script.todo.mail.imap_transport import ImapError
from script.todo.mail.rules import engine, run, storage
from script.todo.mail.rules.model import Condition, Group
from script.todo.todo_i18n import t


class _Tuee(BaseException):
    """L'arrêt brutal d'une passe : ni `Exception`, ni rattrapée."""


class ReleaseCase(ClaimCase):
    def setUp(self):
        super().setUp()
        self.session.connect_fn = lambda account, secret: self.imap

    def fid(self):
        return self.store.folder_state("INBOX")["id"]

    def liberer(self, rule, uid=1):
        return self.store.rule_log_release(
            rule.id,
            self.cle(uid),
            inbox_folder_id=self.fid(),
            inbox_uidvalidity=1,
        )

    def hors_ligne(self):
        rapport = self.session.sync()
        self.session.syncer = None
        return rapport

    def en_ligne(self):
        self.session.syncer = self.syncer

    def incertain(self, rule, uid=1, **kw):
        """Un message laissé `claim_uncertain` : STORE coupé après avoir
        posé le mot-clé, puis passe qui trouve l'intention."""
        self.imap.recevoir(uid, **kw)
        self.imap.store_error = OSError("lien coupé pendant le STORE")
        self.passe()
        self.passe()
        self.assertEqual(self.ligne(rule, uid), ("skipped", "claim_uncertain"))
        self.imap.calls.clear()
        self.imap.probes = self.imap.stores = 0

    def en_echec(self, rule, uid=1):
        """Un message laissé `failed/claim_failed` : la sonde lève à
        chaque passe."""
        self.imap.recevoir(uid)
        self.imap.probe_error = OSError("sonde impossible")
        for _ in range(engine.CLAIM_PASSES_MAX):
            self.passe()
        self.assertEqual(self.ligne(rule, uid), ("failed", "claim_failed"))
        self.imap.probe_error = None
        self.imap.calls.clear()
        self.imap.probes = self.imap.stores = 0

    def lignes_liberees(self):
        return [
            e
            for e in self.store.rule_log_entries()
            if (e["outcome"], e["reason"]) == ("skipped", "released")
        ]


class TestHoldWithoutClaim(ReleaseCase):
    def test_every_hold_reason_holds_without_claiming(self):
        with self.subTest("hold_first"):
            regle = self.regle(approuvee=False, throttle_enabled=False)
            self.imap.recevoir(1)
            self.assertEqual(self.passe().held, 1)
            self.assertEqual(self.ligne(regle, 1), ("held", "hold_first"))
        self.deja_approuvee(regle)
        for uid, code in (
            (2, "pass_cap"),
            (3, "hour_cap"),
            (4, "cache_rebuilt"),
        ):
            with self.subTest(code):
                self.imap.recevoir(uid)
                with mock.patch.object(
                    engine, "hold_reason", return_value=code
                ):
                    self.assertEqual(self.passe().held, 1)
                self.assertEqual(self.ligne(regle, uid), ("held", code))
        self.assertEqual((self.imap.probes, self.imap.stores), (0, 0))
        self.assertEqual(
            self.store._db()
            .execute("SELECT COUNT(*) FROM rule_claim")
            .fetchone()[0],
            0,
        )
        self.assertTrue(all(e["held"] for e in self.store.outbox()))
        self.assertEqual(len(self.store.outbox()), 4)
        for uid in (1, 2, 3, 4):
            self.assertFalse(has_claim(self.imap.messages()[uid].flags))

    def test_a_hold_on_a_message_known_lost_is_skipped_claimed_elsewhere(self):
        regle = self.regle(approuvee=False)
        self.imap.recevoir(1)
        self.store.rule_claim_set(1, 1, "lost")
        bilan = self.passe()
        self.assertEqual(bilan.held, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.imap.probes, 0)

    def test_a_hold_offline_still_leaves_a_hole(self):
        regle = self.regle(approuvee=False)
        self.imap.recevoir(1)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.status, "offline")
        self.assertEqual(self.store.outbox(), [])
        self.assertIsNone(self.ligne(regle))
        self.en_ligne()
        self.assertEqual(self.passe().held, 1)
        self.assertEqual(self.imap.probes, 0)

    def test_a_hold_offline_on_a_server_without_keywords_is_held(self):
        regle = self.regle(approuvee=False)
        storage.save_state(
            "perso", storage.EngineState(claim_mode="none"), base=self.base
        )
        self.imap.recevoir(1)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.held, 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))

    def test_a_hold_after_an_earlier_rule_claimed_the_message_is_held_owned(
        self,
    ):
        self.regle(name="A")
        b = self.regle(name="B", approuvee=False)
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (1, 1))
        self.assertEqual(self.ligne(b), ("held", "hold_first"))
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))
        self.assertEqual(self.revendication(), "owned")

    def test_the_hint_still_skips_a_hold_whose_message_carries_the_keyword(
        self,
    ):
        regle = self.regle(approuvee=False)
        self.imap.recevoir(1)
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(bilan.held, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.imap.probes, 0)

    def test_every_row_written_by_the_engine_carries_its_origin(self):
        envoi = self.regle(name="envoi", throttle_enabled=True)
        self.imap.recevoir(1)
        self.imap.recevoir(2)
        self.imap.recevoir(3, frm=BRUNO)
        retenue = self.regle(
            name="retenue",
            approuvee=False,
            filter=Group("all", [Condition("subject", "Question 1")]),
        )
        self.passe()
        self.assertEqual(self.ligne(envoi, 1), ("sent", None))
        self.assertEqual(self.ligne(envoi, 2), ("skipped", "throttled"))
        self.assertEqual(self.ligne(retenue, 1), ("held", "hold_first"))
        self.assertEqual(self.ligne(envoi, 3), ("sent", None))
        for rule, uid in ((envoi, 1), (envoi, 2), (retenue, 1), (envoi, 3)):
            with self.subTest(rule=rule.name, uid=uid):
                self.assertEqual(
                    self.store.rule_log_origin(rule.id, self.cle(uid)),
                    (1, uid),
                )

    def test_a_failed_row_carries_its_origin(self):
        regle = self.regle()
        self.imap.recevoir(1)
        with mock.patch.object(
            engine._Pass, "_send", side_effect=ValueError("construction")
        ):
            self.passe()
        self.assertEqual(self.ligne(regle), ("failed", "build_error"))
        self.assertEqual(
            self.store.rule_log_origin(regle.id, self.cle(1)), (1, 1)
        )


class TestHeldSettlement(ReleaseCase):
    def retenir(self):
        regle = self.regle(approuvee=False)
        self.imap.recevoir(1)
        self.assertEqual(self.passe().held, 1)
        return regle

    def test_a_held_entry_whose_message_got_the_keyword_is_dropped_at_the_next_pass(
        self,
    ):
        regle = self.retenir()
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.ligne(regle), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.revendication(), "lost")
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertIn(t("mail_rules_held_claimed_elsewhere"), bilan.warnings)
        self.assertEqual(self.imap.probes, 0)

    def test_a_held_entry_is_kept_while_its_message_has_no_keyword(self):
        regle = self.retenir()
        bilan = self.passe()
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))
        self.assertNotIn(
            t("mail_rules_held_claimed_elsewhere"), bilan.warnings
        )

    def test_a_held_entry_of_a_message_owned_or_released_here_is_kept(self):
        regle = self.retenir()
        self.imap.poser(1, CLAIM_KEYWORD)
        for etat in ("owned", "released", "unclaimed"):
            with self.subTest(etat=etat):
                self.store._db().execute("DELETE FROM rule_claim")
                self.store._db().commit()
                if etat == "released":
                    self.store.rule_claim_affirm(1, 1, "released")
                else:
                    self.store.rule_claim_set(1, 1, etat)
                self.passe()
                self.assertEqual(len(self.store.outbox()), 1)
                self.assertEqual(self.ligne(regle), ("held", "hold_first"))

    def test_a_held_entry_with_an_intent_is_kept(self):
        regle = self.retenir()
        self.imap.poser(1, CLAIM_KEYWORD)
        self.store.rule_claim_intent(1, 1)
        self.passe()
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))

    def test_a_held_entry_without_origin_is_kept(self):
        regle = self.retenir()
        self.store._db().execute("UPDATE rule_log SET sealed_origin = NULL")
        self.store._db().commit()
        self.imap.poser(1, CLAIM_KEYWORD)
        self.passe()
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))

    def test_settlement_ignores_another_uidvalidity(self):
        regle = self.retenir()
        self.store._db().execute(
            "UPDATE rule_log SET sealed_origin = ?", (self.store._seal("2:1"),)
        )
        self.store._db().commit()
        self.imap.poser(1, CLAIM_KEYWORD)
        self.passe()
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))

    def test_settlement_works_offline_from_the_cached_flags(self):
        regle = self.retenir()
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.ligne(regle), ("skipped", "claimed_elsewhere"))
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)

    def test_a_retry_entry_is_never_settled(self):
        regle = self.retenir()
        self.store._db().execute("UPDATE outbox SET retry = 1")
        self.store._db().commit()
        self.imap.poser(1, CLAIM_KEYWORD)
        self.passe()
        self.assertEqual(len(self.store.outbox()), 1)
        self.assertEqual(self.ligne(regle), ("held", "hold_first"))


class TestRedo(ReleaseCase):
    def test_a_released_uncertain_message_is_evaluated_again_and_sent_without_a_claim(
        self,
    ):
        regle = self.regle()
        self.incertain(regle)
        self.assertEqual(self.liberer(regle), "released")
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.imap.probes, 0)
        self.assertEqual(self.ligne(regle), ("sent", None))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.lignes_liberees(), [])
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(len(self.envois), 1)

    def test_a_released_failed_claim_is_claimed_normally_then_sent(self):
        regle = self.regle()
        self.en_echec(regle)
        self.assertEqual(self.liberer(regle), "released")
        self.assertEqual(self.revendication(), "retry")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))
        self.assertTrue(has_claim(self.imap.messages()[1].flags))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.ligne(regle), ("sent", None))

    def test_a_released_failed_claim_already_claimed_elsewhere_does_not_leave(
        self,
    ):
        regle = self.regle()
        self.en_echec(regle)
        self.liberer(regle)
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.envois, [])

    def test_a_released_failed_claim_failing_again_stays_released(self):
        regle = self.regle()
        self.en_echec(regle)
        self.liberer(regle)
        self.imap.probe_error = OSError("sonde impossible")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        self.assertIn(t("mail_rules_claim_failed"), bilan.warnings)
        self.imap.probe_error = None
        self.assertEqual(self.passe().sent, 1)

    def _tuee_pendant_la_reevaluation(self, regle):
        """Une passe tuée entre la réservation et l'envoi du message
        libéré : `mark_auto_sent` lève une exception hors d'`Exception`,
        comme un arrêt du processus. La ligne reste `pending`."""
        with mock.patch.object(
            self.store, "mark_auto_sent", side_effect=_Tuee()
        ):
            with self.assertRaises(_Tuee):
                self.passe()
        self.assertEqual(self.ligne(regle), ("pending", "ready_released"))

    def test_a_pass_killed_while_a_released_uncertain_message_is_evaluated_keeps_the_release(
        self,
    ):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        self._tuee_pendant_la_reevaluation(regle)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.ligne(regle), ("sent", None))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(len(self.envois), 1)

    def test_a_pass_killed_while_a_released_failed_claim_is_evaluated_keeps_the_release(
        self,
    ):
        regle = self.regle()
        self.en_echec(regle)
        self.liberer(regle)
        self._tuee_pendant_la_reevaluation(regle)
        self.assertTrue(has_claim(self.imap.messages()[1].flags))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.ligne(regle), ("sent", None))
        self.assertEqual(self.imap.stores, 1)
        self.assertEqual(len(self.envois), 1)

    def test_a_pass_killed_on_a_new_message_still_evaluates_it_as_new(self):
        regle = self.regle()
        self.imap.recevoir(1)
        with mock.patch.object(
            self.store, "mark_auto_sent", side_effect=_Tuee()
        ):
            with self.assertRaises(_Tuee):
                self.passe()
        self.assertEqual(self.ligne(regle), ("pending", "ready"))
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.ligne(regle), ("sent", None))

    def test_a_released_message_is_evaluated_through_every_rule_in_order(self):
        with self.subTest("arrêter ici"):
            a = self.regle(name="A", stop_after=True)
            b = self.regle(name="B")
            self.incertain(a)
            self.assertIsNone(self.ligne(b))
            self.liberer(a)
            self.assertEqual(self.passe().sent, 1)
            self.assertEqual(self.ligne(a), ("sent", None))
            self.assertIsNone(self.ligne(b))

    def test_a_released_message_without_stop_after_answers_with_every_rule(
        self,
    ):
        a = self.regle(name="A")
        b = self.regle(name="B")
        self.incertain(a)
        self.assertEqual(self.ligne(b), ("skipped", "claim_uncertain"))
        self.liberer(a)
        self.assertEqual(self.ligne(b), ("skipped", "released"))
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual(self.ligne(a), ("sent", None))
        self.assertEqual(self.ligne(b), ("sent", None))

    def test_a_released_message_offline_waits_for_the_next_online_pass(self):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.status, "offline")
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        self.assertEqual(self.revendication(), "released")
        self.en_ligne()
        self.assertEqual(self.passe().sent, 1)

    def test_a_released_message_gone_from_the_server_is_logged_claim_gone(
        self,
    ):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        del self.imap.messages()[1]
        bilan = self.passe(report=self.session.sync())
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "claim_gone"))
        self.assertEqual(self.revendication(), "owned")

    def sans_decision(self, changer):
        """Un message libéré dont la règle ne décide plus rien à la
        réévaluation : sa ligne le dit, elle n'est pas supprimée. Une
        seconde règle, qui n'apparie rien, garde la passe active."""
        regle = self.regle()
        self.regle(
            name="Autre",
            filter=Group("all", [Condition("subject", "jamais vu")]),
        )
        self.incertain(regle)
        self.liberer(regle)
        changer(regle)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "release_unmatched"))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.passe().sent, 0)

    def activer(self, regle, actif):
        storage.set_enabled(
            "perso", regle.id, actif, armed=None, base=self.base
        )

    def test_a_released_row_of_a_disabled_rule_says_so(self):
        self.sans_decision(lambda regle: self.activer(regle, False))

    def test_a_released_row_whose_filter_changed_says_so(self):
        def changer(regle):
            regle.filter = Group("all", [Condition("subject", "autre")])
            storage.upsert_rule("perso", regle, base=self.base)

        self.sans_decision(changer)

    def test_a_released_row_of_a_rearmed_rule_says_so(self):
        def changer(regle):
            self.activer(regle, False)
            self.activer(regle, True)

        self.sans_decision(changer)

    def test_a_released_message_older_than_the_rule_window_is_still_sent(self):
        regle = self.regle(throttle_enabled=False)
        self.incertain(regle)
        self.imap.recevoir(2, frm=BRUNO, internaldate=T0 + 2)
        self.liberer(regle)
        self.horloge.instant = T0 + 72 * HOUR
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.ligne(regle, 1), ("sent", None))
        self.assertEqual(self.ligne(regle, 2), ("skipped", "too_old"))

    def test_a_released_message_without_a_date_stays_too_old(self):
        regle = self.regle()
        self.imap.recevoir(1, internaldate=0)
        self.session.sync()
        self.store.rule_log_claim(
            regle.id,
            self.cle(1),
            outcome="skipped",
            reason="claim_uncertain",
            at=T0,
            origin=(1, 1),
        )
        self.store.rule_claim_intent(1, 1)
        self.assertEqual(self.liberer(regle), "released")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "too_old"))

    def test_released_rows_of_another_uidvalidity_are_closed_claim_gone(self):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        bilan = self.passe()
        self.assertEqual(bilan.status, "rearmed")
        self.assertEqual(self.ligne(regle), ("skipped", "claim_gone"))
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(self.envois, [])

    def test_a_released_message_can_be_held_again(self):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        with mock.patch.object(engine, "hold_reason", return_value="pass_cap"):
            bilan = self.passe()
        self.assertEqual(bilan.held, 1)
        self.assertEqual(self.ligne(regle), ("held", "pass_cap"))
        self.assertTrue(self.store.outbox()[0]["held"])
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.imap.probes, 0)

    def test_a_released_message_is_not_throttled_by_its_own_row(self):
        regle = self.regle(throttle_enabled=True)
        self.incertain(regle)
        self.liberer(regle)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.ligne(regle), ("sent", None))

    def test_a_released_message_counts_for_the_sender_limit_of_new_messages(
        self,
    ):
        regle = self.regle(throttle_enabled=True)
        self.incertain(regle)
        self.liberer(regle)
        self.imap.recevoir(2)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.ligne(regle, 1), ("sent", None))
        self.assertEqual(self.ligne(regle, 2), ("skipped", "throttled"))

    def test_a_released_message_above_the_cursor_is_not_evaluated_twice(self):
        regle = self.regle()
        self.passe()
        self.imap.recevoir(1)
        self.session.sync()
        self.store.rule_log_claim(
            regle.id,
            self.cle(1),
            outcome="skipped",
            reason="claim_uncertain",
            at=T0,
            origin=(1, 1),
        )
        self.store.rule_claim_intent(1, 1)
        self.assertEqual(self.etat().cursor, 0)
        self.liberer(regle)
        vus = []
        vrai = engine._Pass._message

        def compte(pas, header):
            vus.append(header.uid)
            return vrai(pas, header)

        with mock.patch.object(engine._Pass, "_message", compte):
            bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(vus, [1])
        self.assertEqual(self.etat().cursor, 1)

    def test_a_hole_during_a_redo_keeps_the_message_released(self):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        rapport = self.session.sync()
        with mock.patch.object(
            self.imap, "fetch_headers", side_effect=ImapError("FETCH NO")
        ):
            bilan = self.passe(report=rapport)
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(regle), ("skipped", "released"))
        self.assertEqual(self.revendication(), "released")
        self.assertEqual(self.passe().sent, 1)

    def test_the_hint_does_not_skip_a_released_message(self):
        regle = self.regle()
        self.incertain(regle)
        self.assertTrue(has_claim(self.imap.messages()[1].flags))
        self.liberer(regle)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.imap.calls, ["deliver"])

    def test_the_trial_says_claimed_here_for_a_released_message(self):
        regle = self.regle()
        self.incertain(regle)
        self.liberer(regle)
        sim = engine.simulate(
            self.session,
            regle,
            self.imap.messages()[1],
            uidvalidity=1,
            body_loader=lambda: "Bonjour, une question.",
            all_accounts=[],
            now=self.horloge,
        )
        self.assertEqual(sim.claim, "here")


class TestExtraction(ReleaseCase):
    def test_claim_exchange_stores_and_reports_the_mode(self):
        self.imap.recevoir(1)
        self.assertEqual(
            engine.claim_exchange(self.imap, self.store, "INBOX", 1, 1),
            ("stored", "plain"),
        )
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.imap.calls, ["probe", "store"])

    def test_claim_exchange_without_a_claim_probe_is_silent(self):
        self.assertEqual(
            engine.claim_exchange(Imap(), self.store, "INBOX", 1, 1),
            ("silent", ""),
        )

    def test_claim_mode_after_follows_the_engine_rule(self):
        cas = (
            ("plain", "", False, "plain"),
            ("plain", "plain", False, "plain"),
            ("none", "plain", False, "none"),
            ("none", "plain", True, "plain"),
            ("", "atomic", False, "atomic"),
            ("plain", "atomic", False, "atomic"),
            ("atomic", "none", False, "none"),
        )
        for actuel, mode, impose, attendu in cas:
            with self.subTest(actuel=actuel, mode=mode, impose=impose):
                self.assertEqual(
                    engine.claim_mode_after(actuel, mode, impose=impose),
                    attendu,
                )


class TestServiceTexts(ServiceCase):
    def test_the_service_output_keeps_the_held_claimed_elsewhere_warning(self):
        bilan = engine.EngineReport(account="perso", active_rules=1)
        bilan.warnings.append(t("mail_rules_held_claimed_elsewhere"))
        bilan.warnings.append("avertissement libre")
        sur = run._journal_safe(bilan, "perso")
        self.assertIn(t("mail_rules_held_claimed_elsewhere"), sur.warnings)
        self.assertNotIn("avertissement libre", sur.warnings)

    def test_the_service_line_for_held_sends_names_the_service_menu(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        muet = engine.EngineReport(account="perso", active_rules=1)
        with mock.patch.object(engine, "run_pass", return_value=muet):
            with mock.patch(
                "script.todo.mail.tui.held_auto_counts",
                return_value=[("perso", 2)],
            ):
                _code, sortie = self.lancer()
        self.assertIn(f"({t('mail_service_held_where')})", sortie)
        self.assertNotIn("(o)", sortie)


if __name__ == "__main__":
    unittest.main()
