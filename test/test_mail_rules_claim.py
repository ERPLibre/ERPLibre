#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La revendication d'un message par le moteur des règles, avant tout envoi.

Le serveur en mémoire du moteur (`Imap`) gagne ici une sonde et un STORE
de revendication réglables (`ClaimImap`) : mode du serveur, changement
glissé entre la sonde et le STORE, refus, lien coupé, mot-clé jeté. Les
« autres machines » n'existent qu'à travers le mot-clé qu'elles posent sur
le serveur ; les tests à deux bases réelles sont dans
`test_mail_rules_claim_sandbox.py`.
"""

import dataclasses
import unittest
from unittest import mock

from test_mail_rules_engine import (
    BRUNO,
    CAROLE,
    DENIS,
    HOUR,
    OWN,
    T0,
    EngineCase,
    FauxSmtp,
    Imap,
)

from script.todo.mail.claim import CLAIM_KEYWORD, ClaimProbe, has_claim
from script.todo.mail.imap_transport import ImapError
from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.model import Armed, message_view, new_rule
from script.todo.mail.smtp_send import SmtpError
from script.todo.mail.tui import DeliverOffline, DeliverStatus, flush_outbox
from script.todo.todo_i18n import t


class Crash(BaseException):
    """Un processus tué : rien ne l'attrape dans le moteur."""


class ClaimImap(Imap):
    """Le serveur en mémoire, avec la revendication.

    `mode` : `atomic`, `plain`, ou `none` (sonde `unsupported`). `race`
    est appelé avant chaque STORE et peut poser un drapeau comme une autre
    machine ; `store_error` pose le mot-clé PUIS lève (lien coupé après
    application) ; `probe_error` fait lever la sonde ; `store_reject` fait
    répondre NO au STORE ; `store_unknown` accepte un STORE puis rend
    `unknown` (relecture refusée) ; `drops_keyword` accepte le STORE et
    jette le mot-clé ; `store_retry` rend `retry` autant de fois, puis la sonde
    passe en mode simple ; `renumber` fait dire `renumbered` à la sonde.
    """

    def __init__(self, mode="plain"):
        super().__init__()
        self.mode = mode
        self.modseq = {}
        self.race = None
        self.store_error = None
        self.probe_error = None
        self.store_reject = False
        self.store_unknown = False
        self.drops_keyword = False
        self.store_retry = 0
        self.renumber = False
        self.sans_condstore = False
        self.probes = 0
        self.stores = 0
        self.calls = []

    def messages(self):
        return self.folders["INBOX"]["messages"]

    def poser(self, uid, *flags):
        """Ajoute des drapeaux côté serveur, MODSEQ avancé. Remplace
        l'en-tête au lieu de le modifier : un rapport de synchronisation
        déjà rendu garde ce qu'il a lu."""
        header = self.messages()[uid]
        actuels = header.flags.split()
        for flag in flags:
            if flag not in actuels:
                actuels.append(flag)
        self.messages()[uid] = dataclasses.replace(
            header, flags=" ".join(actuels)
        )
        self.modseq[uid] = self.modseq.get(uid, 1) + 1

    def claim_probe(self, folder, uid, *, uidvalidity):
        self.probes += 1
        self.calls.append("probe")
        if self.probe_error is not None:
            raise self.probe_error
        mode = "plain" if self.sans_condstore else self.mode
        if self.renumber:
            return ClaimProbe("renumbered", mode)
        if self.mode == "none":
            return ClaimProbe("unsupported", "none", reason="keywords")
        if uid not in self.messages():
            return ClaimProbe("gone", mode)
        modseq = self.modseq.get(uid, 1) if mode == "atomic" else None
        statut = "present" if has_claim(self.messages()[uid].flags) else "free"
        return ClaimProbe(statut, mode, modseq)

    def claim_store(self, uid, probe):
        self.stores += 1
        self.calls.append("store")
        if self.race is not None:
            self.race(uid)
        if self.store_reject:
            raise ImapError("STORE CLAIM NO")
        if self.store_retry:
            self.store_retry -= 1
            self.sans_condstore = True
            return "retry"
        if uid not in self.messages():
            return "gone"
        if probe.mode == "atomic" and self.modseq.get(uid, 1) > probe.modseq:
            return "modified"
        if self.store_unknown:
            self.store_unknown = False
            if not self.drops_keyword:
                self.poser(uid, CLAIM_KEYWORD)
            return "unknown"
        if self.drops_keyword:
            return "refused"
        self.poser(uid, CLAIM_KEYWORD)
        if self.store_error is not None:
            erreur, self.store_error = self.store_error, None
            raise erreur
        return "stored"


class ClaimCase(EngineCase):
    MODE = "plain"

    def setUp(self):
        super().setUp()
        self.imap = ClaimImap(self.MODE)
        self.syncer.transport = self.imap

    def espion(self, session, msg, verrou=None, **_kw):
        getattr(self.imap, "calls", []).append("deliver")
        return super().espion(session, msg, verrou=verrou, **_kw)

    def cle(self, uid):
        return self.store.message_key(f"<{uid}@example.net>", 1, uid)

    def ligne(self, rule, uid=1):
        etat = self.store.rule_log_state(rule.id, self.cle(uid))
        return None if etat is None else (etat["outcome"], etat["reason"])

    def revendication(self, uid=1):
        return self.store.rule_claim_state(1, uid)

    def recu_puis_revendique_ailleurs(self, uid=1, **kw):
        """Le message arrive, la synchronisation le lit sans mot-clé, puis
        une autre machine le revendique : seule la sonde le voit."""
        self.imap.recevoir(uid, **kw)
        rapport = self.session.sync()
        self.imap.poser(uid, CLAIM_KEYWORD)
        return rapport

    def vider(self, send_fn=None):
        return flush_outbox(
            self.session,
            send_fn=send_fn
            or (lambda a, m, tr: self.envois.append(m) or [CAROLE]),
            connect_fn=lambda a, p: FauxSmtp(),
            now=self.horloge,
        )


class TestClaimBeforeSending(ClaimCase):
    def test_a_send_is_preceded_by_a_claim_on_the_server(self):
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.imap.calls, ["probe", "store", "deliver"])
        self.assertTrue(has_claim(self.imap.messages()[1].flags))
        self.assertEqual(self.revendication(), "owned")

    def test_two_rules_on_one_message_claim_it_once(self):
        self.regle(name="A")
        self.regle(name="B")
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))

    def test_the_claim_mode_is_saved_in_the_engine_state_and_report(self):
        self.imap.mode = "atomic"
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual(bilan.claim_mode, "atomic")
        self.assertEqual(self.etat().claim_mode, "atomic")
        self.assertEqual(self.passe().claim_mode, "atomic")


class TestClaimedElsewhere(ClaimCase):
    MODE = "atomic"

    def test_a_message_claimed_elsewhere_is_skipped_with_its_reason(self):
        rule = self.regle()
        bilan = self.passe(report=self.recu_puis_revendique_ailleurs())
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertEqual(self.ligne(rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.revendication(), "lost")
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 0))
        self.assertEqual(self.envois, [])

    def test_the_hint_skips_without_any_server_exchange(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.poser(1, CLAIM_KEYWORD)
        with mock.patch.object(
            engine.markup, "render_reply", side_effect=AssertionError
        ):
            bilan = self.passe()
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertEqual(self.ligne(rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual((self.imap.probes, self.imap.stores), (0, 0))

    def test_the_hint_downloads_nothing_for_a_forward_rule(self):
        renvoi = new_rule("forward", "Renvoi")
        renvoi.action.options.update(targets=[DENIS], mode="inline")
        armed = Armed(1, 1, T0 - HOUR)
        storage.upsert_rule("perso", renvoi, rearm=armed, base=self.base)
        renvoi.armed = armed
        self.deja_approuvee(renvoi)
        self.imap.recevoir(1, extra={"return-path": f"<{CAROLE}>"})
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertEqual(self.imap.body_fetches, [])
        self.assertEqual(self.imap.probes, 0)

    def test_a_claim_lost_at_store_time_is_skipped(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.race = lambda uid: self.imap.poser(uid, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.revendication(), "lost")
        self.assertEqual((self.imap.probes, self.imap.stores), (2, 1))

    def test_a_flag_change_between_probe_and_store_is_retried(self):
        self.regle()
        self.imap.recevoir(1)
        coups = []

        def vu_ailleurs(uid):
            if not coups:
                coups.append(uid)
                self.imap.poser(uid, "\\Seen")

        self.imap.race = vu_ailleurs
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.imap.stores, 2)
        self.assertEqual(self.revendication(), "owned")

    def test_three_modified_stores_leave_a_hole_then_the_next_pass_sends(
        self,
    ):
        self.regle()
        self.imap.recevoir(1)
        self.imap.race = lambda uid: self.imap.modseq.__setitem__(
            uid, self.imap.modseq.get(uid, 1) + 1
        )
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (0, "ok"))
        self.assertEqual(self.imap.stores, engine.CLAIM_ATTEMPTS)
        self.assertIn(t("mail_rules_claim_failed"), bilan.warnings)
        self.assertEqual(self.etat().cursor, 0)
        self.assertEqual(self.revendication(), "retry")
        self.imap.race = None
        self.assertEqual(self.passe().sent, 1)

    def test_three_modified_then_a_claim_elsewhere_is_claimed_elsewhere_not_uncertain(
        self,
    ):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.race = lambda uid: self.imap.modseq.__setitem__(
            uid, self.imap.modseq.get(uid, 1) + 1
        )
        self.passe()
        self.imap.race = None
        self.imap.poser(1, CLAIM_KEYWORD)
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("skipped", "claimed_elsewhere"))
        self.assertNotIn(
            t("mail_rules_claim_uncertain_warning"), bilan.warnings
        )
        self.assertEqual(self.envois, [])

    def test_a_rejected_store_drops_the_intent(self):
        self.regle()
        self.imap.recevoir(1)
        self.imap.store_reject = True
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.revendication(), "retry")
        self.assertIn(t("mail_rules_claim_failed"), bilan.warnings)

    def test_an_unknown_store_keeps_the_intent_and_ends_uncertain(self):
        """STORE accepté, relecture refusée : le mot-clé est posé, et
        personne ne sait par qui à la passe suivante ; rien ne part."""
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.store_unknown = True
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.revendication(), "intent")
        self.assertIn(t("mail_rules_claim_failed"), bilan.warnings)
        self.assertIsNone(self.ligne(rule))
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 0)
        self.assertIn(t("mail_rules_claim_uncertain_warning"), bilan.warnings)
        self.assertEqual(self.envois, [])

    def test_an_unknown_store_that_set_nothing_is_claimed_again(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.store_unknown = True
        self.imap.drops_keyword = True
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(self.revendication(), "intent")
        self.imap.drops_keyword = False
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.revendication(), "owned")
        self.assertEqual(self.ligne(rule)[0], "sent")

    def test_claimed_elsewhere_still_honours_stop_after(self):
        premiere = self.regle(name="A", stop_after=True)
        seconde = self.regle(name="B")
        self.passe(report=self.recu_puis_revendique_ailleurs())
        self.assertEqual(
            self.ligne(premiere), ("skipped", "claimed_elsewhere")
        )
        self.assertIsNone(self.ligne(seconde))

    def test_a_second_message_from_the_same_sender_is_throttled_after_a_claim_elsewhere(
        self,
    ):
        rule = self.regle(throttle_minutes=180)
        self.passe(report=self.recu_puis_revendique_ailleurs())
        sondes = self.imap.probes
        self.horloge.instant += HOUR
        self.imap.recevoir(2, internaldate=self.horloge() - 10)
        bilan = self.passe()
        self.assertEqual(bilan.skipped["throttled"], 1)
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(rule, 2), ("skipped", "throttled"))
        self.assertEqual(self.imap.probes, sondes)

    def test_the_uncertain_warning_is_given_once_per_message(self):
        rule = self.regle(throttle_enabled=False)
        self.imap.recevoir(1)
        self.imap.poser(1, CLAIM_KEYWORD)
        self.store.rule_claim_intent(1, 1)
        premiere = self.passe()
        self.assertIn(
            t("mail_rules_claim_uncertain_warning"), premiere.warnings
        )
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        # Le même message vu une seconde fois sans que les garde-fous ne
        # le disent journalisé (une autre passe l'a inscrit entre-temps).
        storage.save_state(
            "perso",
            dataclasses.replace(self.etat(), cursor=0, done=[]),
            base=self.base,
        )
        with mock.patch.object(
            self.store, "rule_log_seen", return_value=False
        ):
            seconde = self.passe()
        self.assertEqual(self.imap.header_fetches[-1], [1])
        self.assertNotIn(
            t("mail_rules_claim_uncertain_warning"), seconde.warnings
        )
        self.assertEqual(self.envois, [])


class TestOutputsKeepTheClaim(ClaimCase):
    def test_a_held_reply_is_held_without_any_claim(self):
        self.regle(approuvee=False)
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (0, 1))
        self.assertEqual(self.imap.calls, [])
        self.assertIsNone(self.revendication())
        self.assertFalse(has_claim(self.imap.messages()[1].flags))

    def test_a_reply_queued_after_a_transient_refusal_is_flushed_without_a_new_claim(
        self,
    ):
        rule = self.regle()
        self.imap.recevoir(1)

        def refuse(session, msg, verrou=None, **_kw):
            raise SmtpError("421 plus tard", code=421)

        bilan = self.passe(deliver_fn=refuse)
        self.assertEqual(bilan.queued, 1)
        self.assertEqual(self.ligne(rule), ("queued", "smtp_transient"))
        self.assertEqual(self.vider()[0], 1)
        self.assertEqual(self.ligne(rule)[0], "sent")
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))

    def test_a_partial_retry_entry_needs_no_new_claim(self):
        rule = self.regle()
        self.imap.recevoir(1, to=f"{OWN}, {BRUNO}")

        def partiel(session, msg, verrou=None, **_kw):
            self.envois.append(msg)
            return DeliverStatus(
                "ok", served=[], envelope=(CAROLE,), refused={CAROLE: 450}
            )

        bilan = self.passe(deliver_fn=partiel)
        self.assertEqual(bilan.retried, 1)
        self.assertEqual(self.ligne(rule), ("partial", "rcpt_retry"))
        self.vider()
        self.assertEqual(self.ligne(rule)[0], "sent")
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))

    def test_stats_cap_skips_without_claiming(self):
        rule = self.regle()
        self.imap.recevoir(1)
        with mock.patch.object(
            engine, "hold_reason", return_value="stats_cap"
        ):
            bilan = self.passe()
        self.assertEqual(bilan.skipped["stats_cap"], 1)
        self.assertEqual(self.ligne(rule), ("skipped", "stats_cap"))
        self.assertEqual(self.imap.probes, 0)
        self.assertIsNone(self.revendication())


class TestOfflineAndFailures(ClaimCase):
    def hors_ligne(self):
        rapport = self.session.sync()
        self.session.syncer = None
        return rapport

    def test_offline_without_a_known_unclaimable_server_leaves_a_hole(self):
        rule = self.regle()
        self.imap.recevoir(1)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual((bilan.sent, bilan.queued), (0, 0))
        self.assertEqual(bilan.status, "offline")
        self.assertEqual(self.store.outbox(), [])
        self.assertIsNone(self.ligne(rule))
        self.session.syncer = self.syncer
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.revendication(), "owned")

    def test_offline_on_a_server_without_keywords_still_queues(self):
        rule = self.regle()
        storage.save_state(
            "perso", storage.EngineState(claim_mode="none"), base=self.base
        )
        self.imap.recevoir(1)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.queued, 1)
        entree = self.store.outbox()[0]
        self.assertEqual(entree["expires_at"], self.horloge() + 86400)
        self.assertFalse(entree["held"])
        self.assertEqual(self.ligne(rule), ("queued", "offline"))
        self.assertEqual(self.revendication(), None)

    def test_going_offline_after_the_claim_queues_as_before(self):
        rule = self.regle()
        self.imap.recevoir(1)

        def tombe(session, msg, verrou=None, **_kw):
            raise DeliverOffline()

        bilan = self.passe(deliver_fn=tombe)
        self.assertEqual(bilan.queued, 1)
        self.assertEqual(self.ligne(rule), ("queued", "offline"))
        self.assertEqual(self.revendication(), "owned")

    def test_a_claim_failure_leaves_a_hole_and_warns(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.probe_error = OSError("lien coupé")
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (0, "ok"))
        self.assertIn(t("mail_rules_claim_failed"), bilan.warnings)
        self.assertIsNone(self.ligne(rule))
        self.imap.probe_error = None
        self.assertEqual(self.passe().sent, 1)

    def test_a_claim_hole_keeps_the_status_ok_in_the_summary(self):
        self.regle()
        self.imap.recevoir(1)
        self.imap.probe_error = OSError("lien coupé")
        items = engine.summary_items(self.passe())
        self.assertNotIn(t("mail_rules_offline"), items)
        self.assertIn(t("mail_rules_claim_failed"), items)

    def test_repeated_claim_failures_end_as_failed_after_the_limit(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.probe_error = OSError("lien coupé")
        for _ in range(engine.CLAIM_PASSES_MAX - 1):
            bilan = self.passe()
            self.assertIsNone(self.ligne(rule))
            self.assertEqual(self.etat().cursor, 0)
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("failed", "claim_failed"))
        self.assertEqual(bilan.failed, 1)
        self.assertIn(t("mail_rules_claim_failed_final"), bilan.warnings)
        self.assertEqual(self.etat().cursor, 1)
        self.assertEqual(self.imap.probes, engine.CLAIM_PASSES_MAX)
        self.imap.probe_error = None
        self.passe()
        self.assertEqual(self.imap.probes, engine.CLAIM_PASSES_MAX)
        self.assertEqual(self.envois, [])

    def test_a_store_answered_no_is_bounded_like_any_failure(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.store_reject = True
        for _ in range(engine.CLAIM_PASSES_MAX):
            self.passe()
        self.assertEqual(self.ligne(rule), ("failed", "claim_failed"))
        self.assertEqual(self.revendication(), "retry")
        self.assertEqual(self.envois, [])

    def test_a_transient_read_only_inbox_leaves_a_hole_and_never_sends_unclaimed(
        self,
    ):
        self.regle()
        self.imap.recevoir(1)
        self.imap.probe_error = ImapError("boîte en lecture seule")
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.claim_mode), (0, ""))
        self.assertEqual(self.etat().claim_mode, "")
        self.assertEqual(self.envois, [])

    def test_offline_still_says_offline_and_counts_no_failure(self):
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe(report=self.hors_ligne())
        self.assertEqual(bilan.status, "offline")
        self.assertNotIn(t("mail_rules_claim_failed"), bilan.warnings)
        self.assertIsNone(self.revendication())

    def test_a_renumbered_inbox_leaves_a_hole_without_warning(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.renumber = True
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (0, "ok"))
        self.assertEqual(bilan.warnings, [])
        self.assertIsNone(self.revendication())
        self.assertIsNone(self.ligne(rule))

    def test_a_gone_message_is_skipped_claim_gone(self):
        rule = self.regle()
        self.imap.recevoir(1)
        rapport = self.session.sync()
        del self.imap.messages()[1]
        bilan = self.passe(report=rapport)
        self.assertEqual(bilan.skipped["claim_gone"], 1)
        self.assertEqual(self.ligne(rule), ("skipped", "claim_gone"))
        self.assertEqual(self.etat().cursor, 1)


class TestFallback(ClaimCase):
    def test_a_server_without_keywords_sends_unclaimed_and_warns_once(self):
        self.imap.mode = "none"
        self.regle(throttle_enabled=False)
        self.imap.recevoir(1)
        premiere = self.passe()
        self.imap.recevoir(2)
        seconde = self.passe()
        self.assertEqual((premiere.sent, seconde.sent), (1, 1))
        avertissement = t("mail_rules_claim_none_warning")
        self.assertIn(avertissement, premiere.warnings)
        self.assertNotIn(avertissement, seconde.warnings)
        self.assertEqual(self.etat().claim_mode, "none")
        self.assertEqual(self.imap.stores, 0)

    def test_two_rules_on_a_server_without_keywords_probe_once(self):
        self.imap.mode = "none"
        self.regle(name="A")
        self.regle(name="B")
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual(self.imap.probes, 1)

    def test_a_refused_store_sets_none_and_a_later_plain_probe_keeps_it(self):
        self.imap.drops_keyword = True
        self.regle(throttle_enabled=False)
        avertissement = t("mail_rules_claim_none_warning")
        self.imap.recevoir(1)
        premiere = self.passe()
        self.assertEqual(self.etat().claim_mode, "none")
        self.assertEqual(self.revendication(), "unclaimed")
        self.imap.recevoir(2)
        seconde = self.passe()
        self.assertEqual(self.etat().claim_mode, "none")
        self.assertIn(avertissement, premiere.warnings)
        self.assertNotIn(avertissement, seconde.warnings)
        self.assertEqual(len(self.envois), 2)
        # Une sonde simple sans STORE (mot-clé déjà là) ne fait pas
        # quitter `none`.
        self.passe(report=self.recu_puis_revendique_ailleurs(3))
        self.assertEqual(self.etat().claim_mode, "none")

    def test_a_confirmed_store_leaves_none_without_warning(self):
        self.imap.drops_keyword = True
        self.regle(throttle_enabled=False)
        self.imap.recevoir(1)
        self.passe()
        self.imap.drops_keyword = False
        self.imap.recevoir(2)
        bilan = self.passe()
        self.assertEqual(self.etat().claim_mode, "plain")
        self.assertEqual(bilan.claim_mode, "plain")
        self.assertEqual(bilan.warnings, [])

    def test_an_interrupted_claim_on_a_server_that_now_refuses_is_uncertain(
        self,
    ):
        rule = self.regle()
        self.imap.recevoir(1)
        self.store.rule_claim_intent(1, 1)
        self.imap.mode = "none"
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        self.assertEqual(bilan.sent, 0)
        self.assertIn(t("mail_rules_claim_uncertain_warning"), bilan.warnings)

    def test_an_interrupted_claim_whose_new_store_is_refused_is_uncertain(
        self,
    ):
        """Une intention antérieure et un STORE dont le serveur jette le
        mot-clé : le STORE précédent a peut-être été gardé, rien ne part."""
        rule = self.regle()
        self.imap.recevoir(1)
        self.store.rule_claim_intent(1, 1)
        self.imap.drops_keyword = True
        bilan = self.passe()
        self.assertEqual(self.imap.stores, 1)
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.revendication(), "intent")
        self.assertEqual(self.etat().claim_mode, "none")
        self.assertIn(t("mail_rules_claim_uncertain_warning"), bilan.warnings)

    def test_a_keyword_dropped_by_the_server_turns_the_mode_to_none(self):
        self.imap.mode = "atomic"
        self.imap.drops_keyword = True
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(bilan.claim_mode, "none")
        self.assertEqual(self.revendication(), "unclaimed")

    def test_a_bad_conditional_store_is_retried_in_plain(self):
        self.imap.mode = "atomic"
        self.imap.store_retry = 1
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.imap.stores, 2)
        self.assertEqual(self.etat().claim_mode, "plain")

    def test_a_transport_without_claim_support_sends_silently(self):
        self.syncer.transport = Imap()
        self.imap = self.syncer.transport
        self.regle()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual((bilan.warnings, bilan.claim_mode), ([], ""))
        self.assertIsNone(self.revendication())


class TestResume(ClaimCase):
    def test_a_crash_before_the_send_is_resumed_by_the_same_machine(self):
        rule = self.regle()
        self.imap.recevoir(1)
        vrai = self.store.mark_auto_sent
        coups = []

        def plante(*args, **kw):
            if not coups:
                coups.append(1)
                raise Crash()
            return vrai(*args, **kw)

        with mock.patch.object(self.store, "mark_auto_sent", plante):
            with self.assertRaises(Crash):
                self.passe()
        self.assertEqual(self.ligne(rule), ("pending", "ready"))
        self.assertEqual(self.revendication(), "owned")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 1)
        self.assertEqual(self.ligne(rule), ("sent", None))
        self.assertEqual((self.imap.probes, self.imap.stores), (1, 1))

    def crash_pendant_l_envoi(self):
        def plante(session, msg, verrou=None, **_kw):
            self.envois.append(msg)
            raise Crash()

        with self.assertRaises(Crash):
            self.passe(deliver_fn=plante)

    def test_a_crash_during_the_send_is_never_resent(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.crash_pendant_l_envoi()
        self.assertEqual(self.ligne(rule), ("pending", "sending"))
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("failed", "send_uncertain"))
        self.assertIn(t("mail_rules_send_uncertain_warning"), bilan.warnings)
        self.assertEqual((bilan.sent, len(self.envois)), (0, 1))

    def test_a_reasonless_pending_row_from_an_older_version_is_failed_not_resent(
        self,
    ):
        rule = self.regle()
        self.imap.recevoir(1)
        self.store.rule_log_claim(
            rule.id, self.cle(1), outcome="pending", at=T0
        )
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("failed", "send_uncertain"))
        self.assertEqual(self.envois, [])
        self.assertIn(t("mail_rules_send_uncertain_warning"), bilan.warnings)

    def test_a_crash_during_the_send_still_stops_the_following_rules(self):
        premiere = self.regle(name="A", stop_after=True)
        seconde = self.regle(name="B")
        self.imap.recevoir(1)
        self.crash_pendant_l_envoi()
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.ligne(premiere), ("failed", "send_uncertain"))
        self.assertIsNone(self.ligne(seconde))

    def test_a_crash_after_a_sent_reply_still_stops_the_following_rules(self):
        premiere = self.regle(name="A", stop_after=True)
        seconde = self.regle(name="B")
        self.imap.recevoir(1)
        self.store.rule_log_claim(
            premiere.id, self.cle(1), outcome="sent", at=T0 + 900
        )
        self.store.rule_claim_set(1, 1, "owned", mode="plain")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertIsNone(self.ligne(seconde))
        self.assertEqual(self.etat().cursor, 1)

    def test_a_too_old_row_does_not_stop_the_following_rules(self):
        premiere = self.regle(name="A", stop_after=True)
        seconde = self.regle(name="B")
        self.imap.recevoir(1)
        self.store.rule_log_claim(
            premiere.id,
            self.cle(1),
            outcome="skipped",
            reason="too_old",
            at=T0 + 900,
        )
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.ligne(seconde), ("sent", None))

    def test_a_send_uncertain_row_still_throttles_the_same_sender(self):
        rule = self.regle(throttle_minutes=180)
        self.imap.recevoir(1)
        self.crash_pendant_l_envoi()
        self.horloge.instant += HOUR
        self.imap.recevoir(2, internaldate=self.horloge() - 10)
        bilan = self.passe()
        self.assertEqual(self.ligne(rule, 1), ("failed", "send_uncertain"))
        self.assertEqual(self.ligne(rule, 2), ("skipped", "throttled"))
        self.assertEqual(bilan.sent, 0)

    def test_rearming_keeps_the_claim_mode(self):
        self.regle()
        self.imap.recevoir(1)
        self.passe()
        self.assertEqual(self.etat().claim_mode, "plain")
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        bilan = self.passe()
        self.assertEqual(bilan.status, "rearmed")
        self.assertEqual(self.etat().claim_mode, "plain")
        self.assertEqual(self.etat().uidvalidity, 2)

    def test_an_interrupted_store_makes_the_claim_uncertain(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.imap.store_error = OSError("lien coupé pendant le STORE")
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(self.revendication(), "intent")
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        self.assertIn(t("mail_rules_claim_uncertain_warning"), bilan.warnings)
        self.assertEqual(self.envois, [])

    def test_a_lost_link_during_the_store_is_uncertain_on_the_reconnection(
        self,
    ):
        rule = self.regle()
        self.imap.recevoir(1)
        self.session.connect_fn = lambda account, secret: self.imap
        self.imap.store_error = OSError("lien coupé pendant le STORE")
        bilan = self.passe()
        self.assertEqual(self.ligne(rule), ("skipped", "claim_uncertain"))
        self.assertIn(t("mail_rules_claim_uncertain_warning"), bilan.warnings)
        self.assertEqual((self.imap.probes, self.imap.stores), (2, 1))
        self.assertEqual(self.envois, [])


class TestTrial(ClaimCase):
    def essai(self, rule, uid=1):
        header = self.imap.messages()[uid]
        return engine.simulate(
            self.session,
            rule,
            header,
            uidvalidity=1,
            body_loader=lambda: "Bonjour, une question.",
            all_accounts=[],
            now=self.horloge,
        )

    def test_the_trial_never_claims(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.session.sync()
        sim = self.essai(rule)
        self.assertEqual(sim.reason, "send")
        engine.send_trial(self.session, rule, sim, deliver_fn=self.espion)
        self.assertEqual(len(self.envois), 1)
        self.assertEqual((self.imap.probes, self.imap.stores), (0, 0))
        self.assertIsNone(self.revendication())
        self.assertFalse(has_claim(self.imap.messages()[1].flags))

    def test_the_trial_says_whether_a_message_is_claimed_here_or_elsewhere(
        self,
    ):
        rule = self.regle()
        for uid in (1, 2, 3, 4):
            self.imap.recevoir(uid)
        self.imap.poser(2, CLAIM_KEYWORD)
        self.imap.poser(3, CLAIM_KEYWORD)
        self.store.rule_claim_intent(1, 3)
        self.store.rule_claim_set(1, 4, "owned")
        attendus = {1: "", 2: "elsewhere", 3: "uncertain", 4: "here"}
        for uid, attendu in attendus.items():
            with self.subTest(uid=uid):
                self.assertEqual(self.essai(rule, uid).claim, attendu)
        self.store.rule_claim_set(1, 1, "lost")
        self.assertEqual(self.essai(rule, 1).claim, "elsewhere")


class TestModel(unittest.TestCase):
    def test_message_view_carries_the_flags(self):
        imap = ClaimImap()
        imap.recevoir(1)
        imap.poser(1, "\\Seen", CLAIM_KEYWORD)
        vue = message_view(imap.messages()[1], 1)
        self.assertEqual(vue.flags, f"\\Seen {CLAIM_KEYWORD}")
        ligne = type("Ligne", (), {"uid": 1})()
        self.assertEqual(message_view(ligne, 1).flags, "")


if __name__ == "__main__":
    unittest.main()
