#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Refus partiel des destinataires, côté moteur et livraison directe.

Ce que ces tests figent : un envoi direct qu'un serveur accepte pour une
partie de son enveloppe est journalisé `partial`, compte un envoi dans la
passe sans tenir le serveur pour injoignable, et laisse en file un nouvel
essai pour les seuls refusés temporaires, avec l'échéance de la décision ;
une erreur de cette écriture ne fait jamais passer en échec un message
parti ; le journal applicatif ne nomme aucun destinataire ; `deliver`
rend les refus en attributs, et ne les nomme qu'à l'écran.
"""

import email
import email.policy
import logging
import sqlite3
import unittest
from types import SimpleNamespace
from unittest import mock

from test_mail_rules_engine import HOUR, OWN, T0, EngineCase

from script.todo.mail.imap_sync import HeaderInfo
from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import (
    RawOutgoing,
    Served,
    build_message,
    recipients,
)
from script.todo.mail.store import RcptResult
from script.todo.mail.tui import DeliverStatus, deliver
from script.todo.todo_i18n import TRANSLATIONS, t

CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
TEMP = "refus.temporaire@example.net"
DEF = "refus.definitif@example.net"
ADRESSES = (CAROLE, TEMP, DEF)


def original(uid):
    """Un message reçu de DENIS, adressé à la seule boîte."""
    return (
        f"From: {DENIS}\r\n"
        f"To: {OWN}\r\n"
        f"Subject: Question {uid}\r\n"
        f"Message-ID: <{uid}@example.org>\r\n"
        "\r\n"
        "Bonjour, une question.\r\n"
    ).encode()


class PartialEngineCase(EngineCase):
    """Le socle du moteur, une règle de transfert vers CAROLE, TEMP et
    DEF, et un `deliver` doublé qui refuse ce qu'on lui dit."""

    def setUp(self):
        super().setUp()
        self.refus = {TEMP: 450, DEF: 550}

    def deposer(self, uid):
        brut = original(uid)
        boite = self.imap.folders["INBOX"]
        boite["messages"][uid] = HeaderInfo(
            uid=uid,
            date=T0 + uid,
            size=len(brut),
            flags="",
            msgid=f"<{uid}@example.org>",
            frm=DENIS,
            to=OWN,
            subject=f"Question {uid}",
            internaldate=T0 + uid,
            extra={"return-path": f"<{DENIS}>"},
        )
        boite["bodies"][uid] = brut

    def renvoi(self, mode="inline", targets=ADRESSES, **champs):
        rule = new_rule("forward", "Renvoi")
        rule.action.body = "Message reçu par la boîte."
        rule.action.options.update(targets=list(targets), mode=mode)
        rule.throttle_enabled = False
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        armed = Armed(1, 1, T0 - HOUR)
        storage.upsert_rule("perso", rule, rearm=armed, base=self.base)
        rule.armed = armed
        self.deja_approuvee(rule)
        return rule

    def livreur(self, session, msg, verrou=None, **_kw):
        """`deliver` doublé : enveloppe du message, refus de `self.refus`
        (casse ignorée), rendus comme le vrai `deliver`."""
        self.envois.append(msg)
        if isinstance(msg, RawOutgoing):
            enveloppe = tuple(msg.envelope)
        else:
            enveloppe = tuple(recipients(msg))
        refus = {
            a: self.refus[a.lower()]
            for a in enveloppe
            if a.lower() in self.refus
        }
        servis = [a for a in enveloppe if a not in refus]
        return DeliverStatus(
            "ok", served=servis, envelope=enveloppe, refused=refus
        )

    def passe(self, report="sync", **kw):
        kw.setdefault("deliver_fn", self.livreur)
        return super().passe(report, **kw)

    def journal(self, rule):
        return [
            (e["outcome"], e["reason"])
            for e in reversed(self.store.rule_log_entries(rule.id))
            if e["at"] >= T0
        ]

    def ligne(self, rule):
        return next(
            e for e in self.store.rule_log_entries(rule.id) if e["at"] >= T0
        )


class TestEnginePartial(PartialEngineCase):
    def test_a_partly_refused_forward_logs_partial_and_counts_one_send(self):
        rule = self.renvoi()
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual(
            (bilan.sent, bilan.partial, bilan.retried, bilan.failed),
            (1, 1, 1, 0),
        )
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(self.journal(rule), [("partial", "rcpt_retry")])
        ligne = self.ligne(rule)
        self.assertEqual(
            (
                ligne["rcpt_total"],
                ligne["rcpt_dropped"],
                ligne["rcpt_pending"],
            ),
            (3, [550], [450]),
        )
        self.assertEqual(ligne["sent_at"], self.horloge())

    def test_the_4xx_recipient_gets_a_retry_expiring_with_the_decision_window(
        self,
    ):
        rule = self.renvoi()
        self.deposer(1)
        self.passe()
        [entree] = self.store.outbox()
        self.assertTrue(entree["retry"])
        self.assertEqual(entree["to"], TEMP)
        self.assertEqual(entree["kind"], "auto_forward")
        self.assertEqual(
            entree["expires_at"], self.horloge() + engine.OUTBOX_AUTO_TTL_S
        )
        self.assertEqual(
            (entree["rule_id"], entree["source_key"]),
            (rule.id, self.ligne_cle(rule)),
        )
        self.assertEqual(self.ligne(rule)["queue_id"], entree["id"])

    def ligne_cle(self, rule):
        return (
            self.store._db()
            .execute(
                "SELECT msg_key FROM rule_log WHERE rule_id = ? AND at >= ?",
                (rule.id, T0),
            )
            .fetchone()[0]
        )

    def test_a_5xx_recipient_is_dropped_without_retry(self):
        self.refus = {DEF: 550}
        rule = self.renvoi()
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.partial, bilan.retried), (1, 1, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.journal(rule), [("partial", "rcpt_refused")])
        self.assertEqual(self.ligne(rule)["rcpt_dropped"], [550])

    def test_a_redirect_retry_keeps_the_bytes_and_one_resent_block(self):
        self.renvoi(mode="redirect")
        self.deposer(1)
        self.passe()
        [entree] = self.store.outbox()
        self.assertEqual(entree["kind"], "auto_redirect")
        octets = self.store.queued_raw(entree["id"])
        self.assertEqual(octets, self.envois[0].raw)
        self.assertEqual(octets.count(b"Resent-From:"), 1)

    def test_a_forward_retry_carries_no_internal_bcc(self):
        self.renvoi()
        self.deposer(1)
        self.passe()
        [entree] = self.store.outbox()
        octets = self.store.queued_raw(entree["id"])
        self.assertNotIn(b"X-ERPLibre-Bcc", octets)
        for adresse in (CAROLE, DEF):
            self.assertNotIn(adresse.encode(), octets)
        relu = email.message_from_bytes(octets, policy=email.policy.default)
        self.assertEqual(relu["Message-ID"], self.envois[0]["Message-ID"])
        self.assertEqual(relu["Subject"], self.envois[0]["Subject"])

    def test_the_retry_is_not_held_even_before_any_approval(self):
        """La règle exige une approbation par envoi (`hold_first` = 2,
        une seule approuvée) : le message qui part est relâché à la main,
        mais le nouvel essai créé par le départ direct suivant n'attend
        aucune approbation."""
        rule = self.renvoi(hold_first=2)
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual(bilan.held, 1)
        self.store.rule_log_claim(
            rule.id,
            "approuve-2",
            outcome="sent",
            at=T0 - 86400,
            fingerprint=rule.fingerprint(),
        )
        self.deposer(2)
        self.horloge.instant += 10
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.retried), (1, 1))
        essais = [e for e in self.store.outbox() if e["retry"]]
        self.assertEqual(len(essais), 1)
        self.assertFalse(essais[0]["held"])

    def test_a_partial_send_takes_one_slot_of_the_pass_cap(self):
        self.renvoi()
        self.deposer(1)
        self.deposer(2)
        bilan = self.passe(max_per_pass=1)
        self.assertEqual((bilan.sent, bilan.held), (1, 1))
        self.assertEqual(len(self.envois), 1)

    def test_a_partial_send_does_not_mark_the_server_down(self):
        rule = self.renvoi()
        self.deposer(1)
        self.deposer(2)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.queued, bilan.partial), (2, 0, 2))
        self.assertEqual(len(self.envois), 2)
        self.assertEqual(
            self.journal(rule),
            [("partial", "rcpt_retry"), ("partial", "rcpt_retry")],
        )

    def test_the_application_log_names_no_refused_address(self):
        self.renvoi()
        self.deposer(1)
        with self.assertLogs(level=logging.DEBUG) as journal:
            logging.getLogger("garde").info("passe")
            self.passe()
        texte = "\n".join(journal.output)
        self.assertIn("partial", texte)
        for adresse in ADRESSES:
            self.assertNotIn(adresse, texte)
            self.assertNotIn(adresse.split("@")[0], texte)

    def test_a_failing_log_write_after_departure_still_counts_the_send(self):
        rule = self.renvoi()
        self.deposer(1)
        with (
            mock.patch.object(
                self.store,
                "rule_log_rcpt_result",
                side_effect=ValueError("refus.temporaire@example.net"),
            ),
            self.assertLogs(level=logging.INFO) as journal,
        ):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed, bilan.retried), (1, 0, 0))
        self.assertEqual(self.journal(rule), [("sent", None)])
        self.assertEqual(self.store.outbox(), [])
        texte = "\n".join(journal.output)
        self.assertIn("ValueError", texte)
        for adresse in ADRESSES:
            self.assertNotIn(adresse, texte)

    def test_a_store_failure_after_departure_goes_through(self):
        rule = self.renvoi()
        self.deposer(1)
        with (
            mock.patch.object(
                self.store,
                "rule_log_rcpt_result",
                side_effect=sqlite3.OperationalError("database is locked"),
            ),
            self.assertLogs(level=logging.ERROR),
        ):
            bilan = self.passe()
        self.assertEqual(bilan.status, "error")
        self.assertEqual(bilan.failed, 0)
        # Remis à l'envoi : la passe suivante le dira `send_uncertain`
        # au lieu de le renvoyer.
        self.assertEqual(self.journal(rule), [("pending", "sending")])

    def test_the_engine_reads_the_envelope_from_the_delivery_status(self):
        """Le statut écrit TEMP autrement que le message : c'est sa forme,
        celle des clés des refus, qui part au nouvel essai."""
        ecrite = "Refus.Temporaire@example.net"

        def livreur(session, msg, verrou=None, **_kw):
            self.envois.append(msg)
            return DeliverStatus(
                "ok",
                served=[CAROLE, DEF],
                envelope=(CAROLE, ecrite, DEF),
                refused={ecrite: 451},
            )

        self.renvoi()
        self.deposer(1)
        self.passe(deliver_fn=livreur)
        [entree] = self.store.outbox()
        self.assertEqual(entree["to"], ecrite)

    def test_a_terminal_line_logs_that_no_retry_was_created(self):
        self.renvoi()
        self.deposer(1)
        with (
            mock.patch.object(
                self.store,
                "rule_log_rcpt_result",
                return_value=RcptResult(False),
            ),
            self.assertLogs(level=logging.INFO) as journal,
        ):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.partial, bilan.retried), (1, 1, 0))
        self.assertIn("nouvel essai non créé", "\n".join(journal.output))
        self.assertEqual(self.store.outbox(), [])


class TestSummaryAndReason(unittest.TestCase):
    def test_the_summary_counts_partial_sends_and_retries(self):
        rapport = engine.EngineReport(
            "perso", active_rules=1, sent=2, partial=1, retried=1
        )
        items = engine.summary_items(rapport)
        self.assertEqual(
            items[:3],
            [
                f"{t('mail_rules_status_sent')} 2",
                f"{t('mail_rules_status_partial')} 1",
                f"{t('mail_rules_status_retried')} 1",
            ],
        )
        sobre = engine.EngineReport("perso", active_rules=1, sent=2)
        self.assertEqual(
            engine.summary_items(sobre), [f"{t('mail_rules_status_sent')} 2"]
        )

    def test_log_reason_text_counts_the_refused_with_their_codes(self):
        ligne = {
            "outcome": "partial",
            "reason": "rcpt_retry",
            "rcpt_total": 3,
            "rcpt_dropped": [550],
            "rcpt_pending": [450],
        }
        detail = t("mail_rules_rcpt_detail").format(
            refused=2, total=3, codes="450, 550"
        )
        self.assertEqual(
            engine.log_reason_text(ligne),
            f"{t('mail_rules_reason_rcpt_retry')} — {detail}",
        )

    def test_an_unknown_code_reads_as_a_question_mark(self):
        ligne = {
            "outcome": "partial",
            "reason": "rcpt_refused",
            "rcpt_total": None,
            "rcpt_dropped": [0, 550],
            "rcpt_pending": [],
        }
        texte = engine.log_reason_text(ligne)
        self.assertIn(
            t("mail_rules_rcpt_detail").format(
                refused=2, total=2, codes="?, 550"
            ),
            texte,
        )

    def test_a_line_sent_after_a_retry_shows_no_count(self):
        ligne = {
            "outcome": "sent",
            "reason": "rcpt_retried",
            "rcpt_total": 3,
            "rcpt_dropped": [],
            "rcpt_pending": [],
        }
        self.assertEqual(
            engine.log_reason_text(ligne), t("mail_rules_reason_rcpt_retried")
        )
        self.assertEqual(
            engine.log_reason_text({"outcome": "sent", "reason": None}), ""
        )

    def test_a_closed_retry_reads_as_a_closed_retry_not_as_an_expired_message(
        self,
    ):
        ligne = {
            "outcome": "partial",
            "reason": "expired",
            "rcpt_total": 3,
            "rcpt_dropped": [450, 550],
            "rcpt_pending": [],
        }
        texte = engine.log_reason_text(ligne)
        clos = t("mail_rules_retry_closed").format(
            reason=t("mail_rules_reason_expired")
        )
        self.assertTrue(texte.startswith(f"{clos} — "))
        self.assertIn("450, 550", texte)


class TestDeliverStatus(unittest.TestCase):
    def setUp(self):
        from script.todo.mail.accounts import account_from_preset

        self.account = account_from_preset("perso", OWN, "generic")
        self.session = SimpleNamespace(online=True, account=self.account)

    def redirect(self):
        return RawOutgoing(b"Subject: x\r\n\r\ny\r\n", ADRESSES)

    def test_deliver_status_carries_the_refusals_of_served(self):
        servis = Served(
            [CAROLE], envelope=ADRESSES, refused={TEMP: 450, DEF: 550}
        )
        statut = deliver(
            self.session, self.redirect(), send_fn=lambda *a: servis
        )
        self.assertIsInstance(statut, DeliverStatus)
        self.assertEqual(statut.refused, {TEMP: 450, DEF: 550})
        self.assertEqual(statut.envelope, ADRESSES)
        self.assertEqual(statut.served, [CAROLE])

    def test_deliver_with_a_plain_list_derives_refusals_with_code_zero(self):
        ecrite = "Carole.Regle@example.org"
        sortie = RawOutgoing(b"Subject: x\r\n\r\ny\r\n", (ecrite, TEMP, DEF))
        statut = deliver(self.session, sortie, send_fn=lambda *a: [CAROLE])
        self.assertEqual(statut.refused, {TEMP: 0, DEF: 0})
        self.assertEqual(statut.envelope, (ecrite, TEMP, DEF))

    def test_deliver_keeps_the_refusals_when_filing_in_sent_fails(self):
        msg = build_message(self.account, [CAROLE, TEMP], "Devis", "B")
        servis = Served([CAROLE], envelope=(CAROLE, TEMP), refused={TEMP: 450})
        with (
            mock.patch(
                "script.todo.mail.tui.resolve_sent_folder",
                return_value="Sent",
            ),
            mock.patch(
                "script.todo.mail.tui.file_in_sent",
                return_value=OSError("APPEND"),
            ),
            self.assertLogs(level=logging.ERROR),
        ):
            statut = deliver(self.session, msg, send_fn=lambda *a: servis)
        self.assertIn(t("mail_sent_not_filed"), statut)
        self.assertEqual(statut.refused, {TEMP: 450})

    def test_deliver_names_the_refused_with_their_codes_on_screen(self):
        servis = Served(
            [CAROLE], envelope=ADRESSES, refused={DEF: 550, TEMP: 0}
        )
        statut = deliver(
            self.session, self.redirect(), send_fn=lambda *a: servis
        )
        self.assertEqual(
            statut,
            f"{t('mail_sent_to')} {CAROLE} — {t('mail_refused_by_server')}"
            f" {TEMP} (?), {DEF} (550)",
        )

    def test_a_full_delivery_has_no_refusal_text(self):
        servis = Served(list(ADRESSES), envelope=ADRESSES)
        statut = deliver(
            self.session, self.redirect(), send_fn=lambda *a: servis
        )
        self.assertEqual(statut, f"{t('mail_sent_to')} {', '.join(ADRESSES)}")
        self.assertEqual(statut.refused, {})


class TestTranslations(unittest.TestCase):
    def test_every_partial_key_has_both_languages(self):
        for cle in (
            "mail_rules_rcpt_detail",
            "mail_rules_retry_closed",
            "mail_rules_status_partial",
            "mail_rules_status_retried",
            "mail_outbox_partial",
            "mail_outbox_retried",
            "mail_outbox_release_partial",
            "mail_outbox_release_gone_partial",
            "mail_outbox_release_retried",
            "mail_outbox_retry",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


if __name__ == "__main__":
    unittest.main()
