#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Refus partiel des destinataires, côté vidange de la file.

Ce que ces tests figent : une entrée automatique refusée en partie quitte
la file comme partie et laisse un nouvel essai qui ne porte que les refusés
temporaires, avec la même échéance ; ce nouvel essai ne part qu'à son
enveloppe, jamais vers un destinataire servi, jamais classé dans Envoyés,
sous les mêmes plafonds que tout envoi automatique ; sa clôture laisse la
ligne `partial` ; aucune écriture après un départ ne fait lever la vidange
ni renvoyer l'entrée ; le journal applicatif ne nomme personne.
"""

import logging
import sqlite3
import time
import unittest
from unittest import mock

from test_mail_rules_engine import HOUR, OWN, T0, EngineCase

from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Armed, new_rule
from script.todo.mail.smtp_send import (
    build_forward_inline,
    build_message,
    build_redirect,
    recipients,
    strip_header_fields,
    to_crlf,
)
from script.todo.mail.store import Store
from script.todo.mail.tui import (
    FlushResult,
    Session,
    _released_gone_text,
    flush_outbox,
    send_released,
)
from script.todo.todo_i18n import t

CAROLE = "carole.regle@example.org"
DENIS = "denis.tri@example.org"
TEMP = "refus.temporaire@example.net"
DEF = "refus.definitif@example.net"
ADRESSES = (CAROLE, TEMP, DEF)
JOUR = 24 * HOUR

ORIGINAL = (
    f"From: {DENIS}\r\n"
    f"To: {OWN}\r\n"
    "Subject: Devis\r\n"
    "Date: Wed, 28 Oct 2026 09:00:00 +0000\r\n"
    "Message-ID: <orig-file@example.org>\r\n"
    "\r\n"
    "Bonjour.\r\n"
).encode()


class SmtpEspion:
    """Un transport qui note chaque enveloppe et refuse au RCPT TO les
    adresses de `refus` ({minuscules: code}) ; tous refusés : il lève
    comme `smtplib`. `panne`, si posée, est levée après la note de
    l'enveloppe (refus au DATA)."""

    def __init__(self):
        self.refus = {}
        self.envois = []
        self.panne = None

    def _remettre(self, to_addrs, octets):
        import smtplib

        self.envois.append((list(to_addrs), octets))
        if self.panne is not None:
            raise self.panne
        refuses = {
            a: (self.refus[a.lower()], b"refus")
            for a in to_addrs
            if a.lower() in self.refus
        }
        if refuses and len(refuses) == len(to_addrs):
            raise smtplib.SMTPRecipientsRefused(refuses)
        return refuses

    def send_raw(self, raw, from_addr, to_addrs):
        return self._remettre(to_addrs, to_crlf(raw))

    def send_message(self, msg, from_addr, to_addrs):
        return self._remettre(to_addrs, msg.as_bytes())

    def quit(self):
        pass

    def enveloppes(self):
        return [e for e, _ in self.envois]


class OutboxCase(EngineCase):
    def setUp(self):
        super().setUp()
        self.smtp = SmtpEspion()
        self.smtp.refus = {TEMP: 450, DEF: 550}
        self.horloge.instant = T0 + 1000
        self.classes = []
        patcher = mock.patch(
            "script.todo.mail.tui.file_in_sent",
            side_effect=lambda session, msg, verrou=None: self.classes.append(
                msg
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def renvoi(self, mode="inline", **champs):
        rule = new_rule("forward", "Renvoi")
        rule.action.body = "Message reçu par la boîte."
        rule.action.options.update(targets=list(ADRESSES), mode=mode)
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        armed = Armed(1, 1, T0 - HOUR)
        storage.upsert_rule("perso", rule, rearm=armed, base=self.base)
        rule.armed = armed
        self.rule = rule
        return rule

    def plafonds(self, per_pass=20, per_hour=60):
        storage.save_caps(
            "perso",
            storage.Caps(per_pass=per_pass, per_hour=per_hour),
            base=self.base,
        )

    def en_file(
        self, cle="k1", *, mode="inline", at=None, held=False, expires=None
    ):
        """Une ligne au journal et son entrée en file, comme le moteur les
        écrit ; rend l'identifiant de l'entrée."""
        rule = self.rule
        at = self.horloge() if at is None else at
        self.store.rule_log_claim(
            rule.id,
            cle,
            outcome="pending",
            at=at,
            fingerprint=rule.fingerprint(),
        )
        if mode == "redirect":
            sortie = build_redirect(
                self.account,
                ORIGINAL,
                list(ADRESSES),
                msgid=f"<resent-{cle}@example.org>",
            )
            brut, to_text, kind = (
                sortie.raw,
                ", ".join(ADRESSES),
                "auto_redirect",
            )
            sujet = sortie.subject
        else:
            msg = build_forward_inline(
                self.account,
                ORIGINAL,
                list(ADRESSES),
                msgid=f"<transfert-{cle}@example.org>",
            )
            brut, to_text = msg.as_bytes(), ", ".join(recipients(msg))
            kind, sujet = "auto_forward", msg["Subject"]
        return self.store.queue_auto(
            brut,
            to_text,
            sujet,
            held=held,
            rule_id=rule.id,
            source_key=cle,
            expires_at=(at + JOUR) if expires is None else expires,
            outcome="held" if held else "queued",
            reason="hold_first" if held else "smtp_transient",
            kind=kind,
        )

    def vider(self, **kw):
        kw.setdefault("now", self.horloge)
        return flush_outbox(
            self.session, connect_fn=lambda a, p: self.smtp, **kw
        )

    def lire(self, cle="k1"):
        """La ligne du journal de `cle`, colonnes du refus partiel
        comprises, telle qu'écrite."""
        ligne = (
            self.store._db()
            .execute(
                "SELECT outcome, reason, rcpt_total, rcpt_dropped, rcpt_pending,"
                " sent_at, retry_sent_at, queue_id FROM rule_log"
                " WHERE rule_id = ? AND msg_key = ?",
                (self.rule.id, cle),
            )
            .fetchone()
        )
        return dict(ligne)

    def essais(self):
        return [e for e in self.store.outbox() if e["retry"]]


class TestFirstDeparture(OutboxCase):
    def test_a_queued_forward_partly_refused_leaves_a_retry_with_the_same_expiry(
        self,
    ):
        self.renvoi()
        origine = self.en_file()
        echeance = self.store.outbox()[0]["expires_at"]
        resultat = self.vider()
        self.assertEqual(resultat, (1, 0, 0))
        self.assertEqual(
            (resultat.partial, resultat.refused, resultat.retried), (1, 2, 1)
        )
        [essai] = self.store.outbox()
        self.assertNotEqual(essai["id"], origine)
        self.assertTrue(essai["retry"])
        self.assertFalse(essai["held"])
        self.assertEqual(essai["to"], TEMP)
        self.assertEqual(essai["expires_at"], echeance)
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(
            (
                ligne["rcpt_total"],
                ligne["rcpt_dropped"],
                ligne["rcpt_pending"],
            ),
            (3, "550", "450"),
        )
        self.assertEqual(ligne["queue_id"], essai["id"])

    def test_a_forward_retry_bytes_are_the_queued_bytes_without_the_bcc(self):
        self.renvoi()
        origine = self.en_file()
        brut = self.store.queued_raw(origine)
        self.vider()
        [essai] = self.essais()
        attendu = strip_header_fields(to_crlf(brut), ("X-ERPLibre-Bcc",))
        self.assertEqual(self.store.queued_raw(essai["id"]), attendu)
        self.assertNotIn(b"X-ERPLibre-Bcc", attendu)

    def test_the_flush_result_equals_a_triple_and_counts_partials(self):
        self.renvoi()
        self.en_file()
        resultat = self.vider()
        self.assertIsInstance(resultat, FlushResult)
        self.assertEqual(resultat, (1, 0, 0))
        partis, retenus, echoues = resultat
        self.assertEqual((partis, retenus, echoues), (1, 0, 0))
        self.assertEqual(resultat.served, (CAROLE,))
        vide = FlushResult()
        self.assertEqual(vide, (0, 0, 0))
        self.assertEqual((vide.partial, vide.refused, vide.retried), (0, 0, 0))

    def test_a_manual_entry_partly_refused_is_counted_without_retry(self):
        msg = build_message(self.account, [CAROLE, TEMP], "Devis", "B")
        self.store.queue_message(
            msg.as_bytes(), ", ".join(recipients(msg)), "Devis"
        )
        resultat = self.vider()
        self.assertEqual(resultat, (1, 0, 0))
        self.assertEqual(
            (resultat.partial, resultat.refused, resultat.retried), (1, 1, 0)
        )
        self.assertEqual(self.store.outbox(), [])

    def test_an_automatic_entry_without_rule_leaves_the_queue_unsent(self):
        """Une entrée automatique sans règle (cache écrit ailleurs) n'est
        jamais envoyée : elle quitte la file sans connexion."""
        self.renvoi()
        msg = build_forward_inline(self.account, ORIGINAL, list(ADRESSES))
        self.store.queue_message(
            msg.as_bytes(),
            ", ".join(recipients(msg)),
            "Tr",
            kind="auto_forward",
            expires_at=self.horloge() + JOUR,
        )
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.smtp.envois, [])

    def test_the_drain_log_names_no_refused_address(self):
        """Une adresse 4xx qu'aucune enveloppe ne saurait porter est
        abandonnée sans que le texte qui la refuse sorte nulle part."""
        illisible = '"refus temporaire"@example.net'
        self.renvoi()
        self.smtp.refus[illisible] = 451
        msg = build_message(self.account, [CAROLE], "Devis", "B")
        msg["X-ERPLibre-Bcc"] = f"{TEMP}, {DEF}, {illisible}"
        self.store.rule_log_claim(
            self.rule.id,
            "k1",
            outcome="pending",
            at=self.horloge(),
            fingerprint=self.rule.fingerprint(),
        )
        self.store.queue_auto(
            msg.as_bytes(),
            ", ".join(recipients(msg)),
            "Devis",
            held=False,
            rule_id=self.rule.id,
            source_key="k1",
            expires_at=self.horloge() + JOUR,
            outcome="queued",
            reason="offline",
            kind="auto_forward",
        )
        with self.assertLogs(level=logging.DEBUG) as journal:
            logging.getLogger("garde").info("vidange")
            self.vider()
            self.smtp.refus.clear()
            self.horloge.instant += 60
            self.vider()
        texte = "\n".join(journal.output)
        self.assertIn("partie", texte)
        for adresse in (*ADRESSES, illisible):
            self.assertNotIn(adresse, texte)
        self.assertNotIn("refus temporaire", texte)
        self.assertNotIn("refus.temporaire", texte)
        ligne = self.lire()
        self.assertEqual(ligne["rcpt_dropped"], "451,550")


class TestRetryDeparture(OutboxCase):
    def premier(self, **kw):
        self.renvoi(**kw)
        self.en_file()
        self.vider()
        [essai] = self.essais()
        return essai

    def test_a_retry_leaves_only_to_its_envelope_never_to_the_served(self):
        self.premier()
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(self.smtp.enveloppes(), [list(ADRESSES), [TEMP]])
        tous = [a for e in self.smtp.enveloppes() for a in e]
        self.assertEqual(tous.count(CAROLE), 1)
        self.assertEqual(self.store.outbox(), [])

    def test_a_retry_is_never_filed_in_sent(self):
        self.premier()
        self.assertEqual(len(self.classes), 1)
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.vider()
        self.assertEqual(len(self.classes), 1)

    def test_a_retry_served_to_all_logs_sent_after_retry(self):
        self.smtp.refus = {TEMP: 450}
        self.premier()
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.vider()
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("sent", "rcpt_retried")
        )
        self.assertIsNone(ligne["rcpt_pending"])

    def test_a_retry_served_to_all_after_a_5xx_stays_partial_refused(self):
        self.premier()
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.vider()
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_refused")
        )
        self.assertEqual(ligne["rcpt_dropped"], "550")

    def test_a_retry_wholly_refused_for_now_stays_queued(self):
        essai = self.premier()
        avant = self.lire()
        self.horloge.instant += 60
        self.assertEqual(self.vider(), (0, 0, 1))
        self.assertEqual([e["id"] for e in self.store.outbox()], [essai["id"]])
        self.assertEqual(self.lire(), avant)

    def test_a_retry_departure_sets_retry_sent_at_and_keeps_sent_at(self):
        self.premier()
        premier = self.horloge()
        self.smtp.refus.clear()
        self.horloge.instant += 900
        self.vider()
        ligne = self.lire()
        self.assertEqual(
            (ligne["sent_at"], ligne["retry_sent_at"]),
            (premier, premier + 900),
        )

    def test_a_redirect_retry_sends_the_same_bytes_to_the_4xx_alone(self):
        self.renvoi(mode="redirect")
        self.en_file(mode="redirect")
        self.vider()
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.vider()
        [(env1, octets1), (env2, octets2)] = self.smtp.envois
        self.assertEqual((env1, env2), (list(ADRESSES), [TEMP]))
        self.assertEqual(octets1, octets2)
        self.assertEqual(octets2.count(b"Resent-From:"), 1)


class TestRetryClosure(OutboxCase):
    def premier(self, **kw):
        self.renvoi(**kw)
        self.en_file()
        self.vider()
        [essai] = self.essais()
        return essai

    def test_an_expired_retry_keeps_the_line_partial_with_reason_expired(self):
        essai = self.premier()
        self.horloge.instant = essai["expires_at"] + 1
        self.smtp.refus.clear()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "expired")
        )
        self.assertEqual(ligne["rcpt_dropped"], "450,550")
        self.assertIsNone(ligne["rcpt_pending"])

    def test_a_retry_of_a_disabled_rule_is_dropped_and_the_line_stays_partial(
        self,
    ):
        self.premier()
        self.rule.enabled = False
        storage.upsert_rule("perso", self.rule, base=self.base)
        self.smtp.refus.clear()
        self.vider()
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rule_disabled")
        )

    def test_a_retry_of_a_changed_rule_is_dropped_and_the_line_stays_partial(
        self,
    ):
        self.premier()
        self.rule.action.body = "Autre introduction."
        storage.upsert_rule("perso", self.rule, base=self.base)
        self.smtp.refus.clear()
        self.vider()
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rule_changed")
        )

    def test_three_permanent_failures_close_the_retry_as_attempts_exhausted(
        self,
    ):
        """Un refus permanent qui ne nomme aucun destinataire (DATA) est
        borné par `max_attempts` ; les codes en attente passent aux
        abandonnés."""
        import smtplib

        self.premier()
        self.smtp.panne = smtplib.SMTPDataError(554, b"rejet")
        for _ in range(3):
            self.horloge.instant += 60
            self.assertEqual(self.vider(), (0, 0, 1))
        self.assertEqual(self.store.outbox(), [])
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]),
            ("partial", "attempts_exhausted"),
        )
        self.assertEqual(ligne["rcpt_dropped"], "450,550")
        self.assertIsNone(ligne["rcpt_pending"])

    def test_a_retry_refused_for_good_is_closed_at_its_first_refusal(self):
        self.premier()
        self.smtp.refus[TEMP] = 550
        self.horloge.instant += 60
        self.assertEqual(self.vider(), (0, 0, 1))
        self.assertEqual(self.store.outbox(), [])
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "smtp_permanent")
        )
        self.assertEqual(ligne["rcpt_dropped"], "550,550")
        self.assertIsNone(ligne["rcpt_pending"])
        self.horloge.instant += 60
        self.vider()
        self.assertEqual(self.smtp.enveloppes(), [list(ADRESSES), [TEMP]])

    def test_closing_a_retry_logs_the_reason_not_a_generic_outcome(self):
        essai = self.premier()
        self.horloge.instant = essai["expires_at"] + 1
        with self.assertLogs(level=logging.INFO) as journal:
            self.vider()
        texte = "\n".join(journal.output)
        self.assertIn("nouvel essai clos (expired), ligne partial", texte)
        self.assertNotIn("expired/expired", texte)

    def test_a_mixed_whole_refusal_narrows_the_retry_to_its_4xx(self):
        self.smtp.refus = {TEMP: 450, DEF: 451}
        essai = self.premier()
        self.assertEqual(essai["to"], f"{TEMP}, {DEF}")
        self.smtp.refus = {TEMP: 450, DEF: 550}
        self.horloge.instant += 60
        self.assertEqual(self.vider(), (0, 0, 1))
        [apres] = self.store.outbox()
        self.assertEqual((apres["id"], apres["to"]), (essai["id"], TEMP))
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(
            (ligne["rcpt_pending"], ligne["rcpt_dropped"]), ("450", "550")
        )
        self.horloge.instant += 60
        self.vider()
        self.assertEqual(self.smtp.enveloppes()[-1], [TEMP])
        tentes = [a for e in self.smtp.enveloppes() for a in e]
        self.assertEqual(tentes.count(DEF), 2)

    def test_closing_a_retry_is_atomic(self):
        import sqlite3 as sq

        essai = self.premier()
        avant = self.lire()
        vrai = sq.connect

        class Panne(sq.Connection):
            def execute(self, sql, *args):
                if sql.startswith("UPDATE rule_log SET reason"):
                    raise sq.OperationalError("disk I/O error")
                return super().execute(sql, *args)

        self.store.close()
        with mock.patch(
            "script.todo.mail.store.sqlite3.connect",
            lambda *a, **k: vrai(*a, factory=Panne, **k),
        ):
            self.store.open()
        self.horloge.instant = essai["expires_at"] + 1
        with self.assertLogs(level=logging.ERROR):
            self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual([e["id"] for e in self.store.outbox()], [essai["id"]])
        self.assertIsNone(self.store.outbox()[0]["claimed_at"])
        self.assertEqual(self.lire(), avant)


class TestRetryGuards(OutboxCase):
    def premier(self):
        self.renvoi()
        self.en_file()
        self.vider()
        [essai] = self.essais()
        self.smtp.refus.clear()
        self.horloge.instant += 60
        return essai

    def test_an_ordinary_entry_whose_line_is_partial_leaves_without_sending(
        self,
    ):
        essai = self.premier()
        msg = build_forward_inline(self.account, ORIGINAL, list(ADRESSES))
        egaree = self.store.queue_auto(
            msg.as_bytes(),
            ", ".join(recipients(msg)),
            "Tr",
            held=False,
            rule_id=self.rule.id,
            source_key="k1",
            expires_at=self.horloge() + JOUR,
            outcome="queued",
            reason="offline",
            kind="auto_forward",
        )
        self.assertEqual(self.lire()["outcome"], "partial")
        self.vider()
        restants = [e["id"] for e in self.store.outbox()]
        self.assertNotIn(egaree, restants)
        self.assertNotIn(essai["id"], restants)
        self.assertEqual(self.smtp.enveloppes(), [list(ADRESSES), [TEMP]])

    def test_a_retry_whose_line_is_not_partial_leaves_without_sending(self):
        self.premier()
        db = self.store._db()
        db.execute("UPDATE rule_log SET outcome = 'sent' WHERE msg_key = 'k1'")
        db.commit()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)

    def test_a_retry_whose_line_no_longer_waits_leaves_without_sending(self):
        self.premier()
        db = self.store._db()
        db.execute(
            "UPDATE rule_log SET reason = 'rcpt_refused' WHERE msg_key = 'k1'"
        )
        db.commit()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)

    def test_a_retry_the_line_does_not_point_to_leaves_without_sending(self):
        essai = self.premier()
        db = self.store._db()
        db.execute(
            "UPDATE rule_log SET queue_id = ? WHERE msg_key = 'k1'",
            (essai["id"] + 100,),
        )
        db.commit()
        avant = self.lire()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(len(self.smtp.envois), 1)
        self.assertEqual(self.lire(), avant)

    def test_a_retry_with_an_unreadable_envelope_is_closed_as_build_error(
        self,
    ):
        essai = self.premier()
        db = self.store._db()
        db.execute(
            "UPDATE outbox SET sealed_to = ? WHERE id = ?",
            (self.store._seal("pas une adresse"), essai["id"]),
        )
        db.commit()
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "build_error")
        )


class TestRetryCaps(OutboxCase):
    def test_a_retry_waits_when_other_sends_fill_the_hour(self):
        self.renvoi()
        self.plafonds(per_hour=2)
        self.en_file()
        self.vider()
        self.store.rule_log_claim(
            "autre", "x", outcome="sent", at=self.horloge()
        )
        self.smtp.refus.clear()
        self.horloge.instant += 60
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(len(self.essais()), 1)
        self.assertIsNone(self.essais()[0]["claimed_at"])

    def test_a_retry_waits_while_its_own_first_departure_fills_the_hour(self):
        self.renvoi()
        self.plafonds(per_hour=1)
        self.en_file()
        depart = self.horloge()
        self.assertEqual(self.vider(), (1, 0, 0))
        self.smtp.refus.clear()
        self.horloge.instant = depart + 600
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(len(self.essais()), 1)
        self.horloge.instant = depart + HOUR + 1
        self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(self.essais(), [])

    def test_ten_retries_cannot_double_the_hourly_cap(self):
        self.renvoi()
        self.plafonds(per_pass=20, per_hour=10)
        for rang in range(10):
            self.en_file(f"k{rang}")
        resultat = self.vider()
        self.assertEqual((resultat[0], resultat.retried), (10, 10))
        self.smtp.refus.clear()
        self.horloge.instant += 600
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(len(self.essais()), 10)
        self.assertEqual(self.store.rule_log_sent_since(T0), 10)

    def test_a_retry_takes_one_slot_of_the_drain_pass_cap(self):
        self.renvoi()
        self.en_file("k1")
        self.vider()
        [essai] = self.essais()
        autre = self.en_file("k2")
        self.plafonds(per_pass=1)
        self.smtp.refus.clear()
        self.horloge.instant += 60
        resultat = self.vider()
        self.assertEqual(resultat[0], 1)
        restants = [e["id"] for e in self.store.outbox()]
        self.assertEqual(restants, [autre])
        self.assertNotIn(essai["id"], restants)


class TestConcurrentDrains(OutboxCase):
    """Deux vidanges sur le même cache (client et service) : un nouvel
    essai réduit par l'une ne repart jamais de l'autre vers son ancienne
    enveloppe, et ses codes abandonnés ne comptent qu'une fois."""

    def setUp(self):
        super().setUp()
        self.renvoi()
        self.smtp.refus = {TEMP: 450, DEF: 451}
        self.en_file()
        self.vider()
        self.smtp.refus = {TEMP: 450, DEF: 550}
        self.horloge.instant += 60
        self.autre = Store(self.account, mode="clear", base=self.base)
        self.autre.open()
        self.addCleanup(self.autre.close)
        self.session2 = Session(
            self.account, self.autre, self.syncer, password="x"
        )

    def vider_autre(self):
        return flush_outbox(
            self.session2,
            connect_fn=lambda a, p: self.smtp,
            now=self.horloge,
        )

    def verifier_une_seule_reduction(self):
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_retry")
        )
        self.assertEqual(
            (
                ligne["rcpt_total"],
                ligne["rcpt_dropped"],
                ligne["rcpt_pending"],
            ),
            (3, "550", "450"),
        )
        tentes = [a for e in self.smtp.enveloppes() for a in e]
        self.assertEqual(tentes.count(DEF), 2)

    def test_a_stale_snapshot_never_sends_the_narrowed_envelope(self):
        instantane = self.autre.outbox()
        self.vider()
        self.horloge.instant += 60
        with mock.patch.object(self.autre, "outbox", lambda: instantane):
            self.vider_autre()
        self.assertEqual(self.smtp.enveloppes()[-1], [TEMP])
        self.verifier_une_seule_reduction()

    def test_the_claim_holds_until_the_refusal_is_written(self):
        vrai = self.store.record_send_failure
        pendant = []

        def echec(*args, **kw):
            compteurs = vrai(*args, **kw)
            if not pendant:
                pendant.append(tuple(self.vider_autre()))
            return compteurs

        with mock.patch.object(self.store, "record_send_failure", echec):
            self.assertEqual(self.vider(), (0, 0, 1))
        self.assertEqual(pendant, [(0, 0, 0)])
        self.assertIsNone(self.store.outbox()[0]["claimed_at"])
        self.verifier_une_seule_reduction()


class TestAfterDeparture(OutboxCase):
    def test_a_failed_log_write_after_departure_never_resends_to_the_served(
        self,
    ):
        self.verifier(ValueError("refus.temporaire@example.net"))

    def test_a_cache_failure_after_departure_never_resends_to_the_served(
        self,
    ):
        self.verifier(sqlite3.OperationalError("disk I/O error"))

    def verifier(self, erreur):
        self.renvoi()
        cle = f"k-{type(erreur).__name__}"
        origine = self.en_file(cle)
        envois = len(self.smtp.envois)
        with (
            mock.patch.object(
                self.store, "rule_log_rcpt_result", side_effect=erreur
            ),
            self.assertLogs(level=logging.ERROR) as journal,
        ):
            resultat = self.vider()
        self.assertEqual(resultat[0], 1)
        self.assertNotIn(origine, [e["id"] for e in self.store.outbox()])
        self.assertEqual(
            self.store.rule_log_state(self.rule.id, cle)["outcome"], "sent"
        )
        texte = "\n".join(journal.output)
        for adresse in ADRESSES:
            self.assertNotIn(adresse, texte)
        self.horloge.instant += 601
        self.smtp.refus.clear()
        self.vider()
        self.assertEqual(len(self.smtp.envois), envois + 1)

    def test_a_failure_building_the_retry_logs_the_departure_without_it(
        self,
    ):
        """Le calcul des octets du nouvel essai lève : le repli inscrit le
        départ, refusés tous abandonnés, et retire l'entrée."""
        self.renvoi()
        origine = self.en_file()
        with (
            mock.patch(
                "script.todo.mail.smtp_send.strip_header_fields",
                side_effect=ValueError("octets"),
            ),
            self.assertLogs(level=logging.ERROR),
        ):
            resultat = self.vider()
        self.assertEqual((resultat[0], resultat.retried), (1, 0))
        self.assertEqual(self.store.outbox(), [])
        self.assertNotIn(origine, [e["id"] for e in self.store.outbox()])
        ligne = self.lire()
        self.assertEqual(
            (ligne["outcome"], ligne["reason"]), ("partial", "rcpt_refused")
        )
        self.assertEqual(ligne["rcpt_dropped"], "450,550")

    def test_a_retry_left_when_both_log_writes_fail_counts_in_its_hour(self):
        """Le repli d'un nouvel essai parti dont le journal ne s'écrit pas
        inscrit quand même son départ : le plafond par heure le voit."""
        self.renvoi()
        self.en_file()
        depart = self.horloge()
        self.vider()
        self.smtp.refus.clear()
        self.horloge.instant = depart + 600
        with (
            mock.patch.object(
                self.store,
                "rule_log_rcpt_result",
                side_effect=ValueError("x"),
            ),
            self.assertLogs(level=logging.ERROR),
        ):
            self.assertEqual(self.vider(), (1, 0, 0))
        self.assertEqual(len(self.smtp.envois), 2)
        self.assertEqual(self.store.outbox(), [])
        self.assertEqual(self.store.rule_log_sent_since(depart - HOUR), 2)
        self.assertEqual(self.store.rule_log_recent_sends(depart - HOUR), 2)
        self.assertEqual(self.lire()["retry_sent_at"], depart + 600)

    def test_a_retry_created_by_the_drain_keeps_the_decision_deadline(self):
        self.renvoi()
        decision = self.horloge()
        entree = self.en_file(held=True)
        self.store.set_held(entree, False)
        self.horloge.instant = decision + 23 * HOUR
        resultat = self.vider(only_ids=[entree])
        self.assertEqual(resultat.retried, 1)
        [essai] = self.essais()
        self.assertEqual(essai["expires_at"], decision + JOUR)


class TestReleased(OutboxCase):
    def test_a_released_retry_reports_a_partial_status(self):
        self.renvoi()
        instant = int(time.time())
        entree = self.en_file(at=instant, held=True, expires=instant + HOUR)
        self.store.set_held(entree, False)
        texte = send_released(
            self.session, entree, connect_fn=lambda a, p: self.smtp
        )
        self.assertEqual(
            texte,
            f"{t('mail_outbox_release_partial')} 2"
            f" — {t('mail_sent_to')} {CAROLE}"
            f" — {t('mail_outbox_release_retried')}",
        )
        self.assertNotIn(TEMP, texte)

    def test_send_released_reads_a_plain_triple_double(self):
        self.renvoi()
        entree = self.en_file()
        with mock.patch(
            "script.todo.mail.tui.flush_outbox", return_value=(1, 0, 0)
        ):
            texte = send_released(self.session, entree)
        self.assertTrue(texte.startswith(t("mail_sent_to")))

    def test_releasing_an_expired_retry_never_says_partly_sent(self):
        self.renvoi()
        self.smtp.refus = {TEMP: 450}
        self.en_file()
        self.vider()
        [essai] = self.essais()
        self.store.set_held(essai["id"], True)
        self.horloge.instant = essai["expires_at"] + 5
        self.store.set_held(essai["id"], False)
        with mock.patch("script.todo.mail.tui.time.time", self.horloge):
            texte = send_released(
                self.session,
                essai["id"],
                connect_fn=lambda a, p: self.smtp,
                entree=essai,
            )
        self.assertEqual(texte, t("mail_outbox_release_retry_closed"))
        self.assertEqual(len(self.smtp.envois), 1)
        self.assertEqual(
            (self.lire()["outcome"], self.lire()["reason"]),
            ("partial", "expired"),
        )

    def test_a_gone_retry_closed_without_leaving_is_not_partly_sent(self):
        self.renvoi()
        self.en_file()
        self.vider()
        [essai] = self.essais()
        for raison in ("expired", "rule_disabled", "rule_changed"):
            with self.subTest(raison=raison):
                db = self.store._db()
                db.execute(
                    "UPDATE rule_log SET reason = ? WHERE msg_key = 'k1'",
                    (raison,),
                )
                db.commit()
                self.assertEqual(
                    _released_gone_text(self.store, essai),
                    t("mail_outbox_release_retry_closed"),
                )
                # L'entrée d'origine, elle, est bien partie en partie.
                origine = {"rule_id": self.rule.id, "source_key": "k1"}
                self.assertEqual(
                    _released_gone_text(self.store, origine),
                    t("mail_outbox_release_gone_partial"),
                )
        for raison in ("rcpt_retry", "rcpt_refused"):
            with self.subTest(raison=raison):
                db = self.store._db()
                db.execute(
                    "UPDATE rule_log SET reason = ? WHERE msg_key = 'k1'",
                    (raison,),
                )
                db.commit()
                self.assertEqual(
                    _released_gone_text(self.store, essai),
                    t("mail_outbox_release_gone_partial"),
                )

    def test_a_gone_entry_whose_line_is_partial_says_partly_sent(self):
        self.renvoi()
        self.en_file()
        self.vider()
        entree = {"rule_id": self.rule.id, "source_key": "k1", "to": CAROLE}
        self.assertEqual(
            _released_gone_text(self.store, entree),
            t("mail_outbox_release_gone_partial"),
        )


if __name__ == "__main__":
    unittest.main()
