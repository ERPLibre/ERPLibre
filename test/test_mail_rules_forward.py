#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Transfert et redirection par une règle : lecture du message complet,
passe du moteur et essai.

Ce que ces tests figent : le chargeur d'octets ne télécharge rien pour un
message trop gros dont la taille est connue, refuse après coup un message
trop gros dont elle ne l'était pas, ne fait qu'un FETCH pour plusieurs
appels comme pour le chargeur de corps du même message, laisse un trou
hors ligne et mémorise un échec en ligne.

Une passe relaie le message de Bruno à Carole et Denis selon le mode de la
règle, jamais à Bruno lui-même ; elle passe par les mêmes plafonds,
retenue et file qu'une réponse, et s'arrête sur ses propres envois, sur
les réponses à ses transferts et sur une redirection revenue. L'essai
montre les destinations retenues et retirées, et n'envoie qu'à soi-même.
"""

import dataclasses
import email
import email.policy
import functools
import json
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
)

from script.todo.mail.imap_sync import HeaderInfo
from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.filter import BodyUnavailable
from script.todo.mail.rules.guards import SEND
from script.todo.mail.rules.model import (
    FORWARD_MAX_BYTES,
    Armed,
    Condition,
    Group,
    RuleError,
    new_rule,
)
from script.todo.mail.smtp_send import RawOutgoing, recipients
from script.todo.mail.tui import Session, flush_outbox
from script.todo.todo_i18n import t

TEMOIN = "temoin.cci@example.com"
NOREPLY = "noreply@example.net"


class TestRawLoader(EngineCase):
    def setUp(self):
        super().setUp()
        self.imap.recevoir(1, body="Bonjour, une question longue.")
        self.session.sync()
        self.brut = self.imap.folders["INBOX"]["bodies"][1]

    def chargeur(self, session=None, **kw):
        return engine.make_raw_loader(
            session or self.session, "INBOX", 1, **kw
        )

    def test_size_above_the_cap_never_fetches(self):
        for kw in (
            {"size": FORWARD_MAX_BYTES + 1},
            {"size": 100, "max_bytes": 99},
        ):
            with self.subTest(**kw):
                charger = self.chargeur(**kw)
                for _ in range(2):
                    with self.assertRaises(engine.MessageTooBig) as ctx:
                        charger()
                    self.assertEqual(ctx.exception.size, kw["size"])
        self.assertEqual(self.imap.body_fetches, [])

    def test_downloaded_size_above_the_cap_is_refused(self):
        """Taille inconnue (0) : le contrôle vient après le FETCH."""
        charger = self.chargeur(max_bytes=len(self.brut) - 1)
        for _ in range(2):
            with self.assertRaises(engine.MessageTooBig) as ctx:
                charger()
            self.assertEqual(ctx.exception.size, len(self.brut))
        self.assertEqual(self.imap.body_fetches, [1])

    def test_a_size_at_the_cap_is_loaded(self):
        charger = self.chargeur(size=len(self.brut), max_bytes=len(self.brut))
        self.assertEqual(charger(), self.brut)

    def test_one_fetch_for_several_calls(self):
        charger = self.chargeur(size=len(self.brut))
        self.assertEqual(charger(), self.brut)
        self.assertEqual(charger(), self.brut)
        self.assertEqual(self.imap.body_fetches, [1])

    def test_offline_is_a_hole(self):
        hors_ligne = Session(self.account, self.store, None, password="x")
        charger = self.chargeur(hors_ligne)
        with self.assertRaises(BodyUnavailable) as ctx:
            charger()
        self.assertFalse(ctx.exception.online)
        self.assertEqual(self.imap.body_fetches, [])

    def test_a_failed_fetch_is_remembered(self):
        self.imap.body_errors.add(1)
        charger = self.chargeur()
        for _ in range(2):
            with self.assertRaises(BodyUnavailable) as ctx:
                charger()
            self.assertTrue(ctx.exception.online)
        self.assertEqual(self.imap.body_fetches, [1])

    def test_the_body_loader_and_the_raw_loader_share_one_fetch(self):
        self.assertEqual(self.chargeur()(), self.brut)
        texte = engine.make_body_loader(self.session, "INBOX", 1)()
        self.assertIn("Bonjour, une question longue.", texte)
        self.assertEqual(self.imap.body_fetches, [1])
        # Dans l'autre ordre, sur un second message.
        self.imap.recevoir(2)
        self.session.sync()
        engine.make_body_loader(self.session, "INBOX", 2)()
        brut = engine.make_raw_loader(self.session, "INBOX", 2)()
        self.assertEqual(brut, self.imap.folders["INBOX"]["bodies"][2])
        self.assertEqual(self.imap.body_fetches, [1, 2])


def original(
    uid,
    *,
    frm=BRUNO,
    subject=None,
    in_reply_to="",
    entetes=(),
    corps="Bonjour, une question.",
):
    """Les octets d'un message reçu, avec un Cc et un Cci tiers."""
    lignes = [
        f"Return-Path: <{frm}>",
        f"From: {frm}",
        f"To: {OWN}",
        f"Cc: {TEMOIN}",
        f"Bcc: {TEMOIN}",
        f"Subject: {subject or f'Question {uid}'}",
        f"Message-ID: <{uid}@example.net>",
        *([f"In-Reply-To: {in_reply_to}"] if in_reply_to else []),
        *entetes,
        "",
        corps,
        "",
    ]
    return "\r\n".join(lignes).encode()


class ForwardCase(EngineCase):
    """Le socle du moteur, avec un dépôt de messages complets et des
    règles de redirection approuvées."""

    def deposer(
        self,
        uid,
        *,
        frm=BRUNO,
        subject=None,
        in_reply_to="",
        extra=None,
        size=None,
        entetes=(),
    ):
        """Range un message complet dans INBOX ; `extra` (en-têtes
        supplémentaires vus par les garde-fous) part toujours du
        Return-Path, et `size` remplace la taille annoncée."""
        brut = original(
            uid,
            frm=frm,
            subject=subject,
            in_reply_to=in_reply_to,
            entetes=entetes,
        )
        boite = self.imap.folders["INBOX"]
        boite["messages"][uid] = HeaderInfo(
            uid=uid,
            date=T0 + uid,
            size=len(brut) if size is None else size,
            flags="",
            msgid=f"<{uid}@example.net>",
            frm=frm,
            to=OWN,
            cc=TEMOIN,
            subject=subject or f"Question {uid}",
            in_reply_to=in_reply_to,
            internaldate=T0 + uid,
            extra={"return-path": f"<{frm}>", **(extra or {})},
        )
        boite["bodies"][uid] = brut
        return brut

    def renvoi(
        self,
        targets=(CAROLE, DENIS),
        mode="inline",
        *,
        approuvee=True,
        **champs,
    ):
        """Une règle `forward` enregistrée, armée avant les messages."""
        rule = new_rule("forward", champs.pop("name", "Renvoi"))
        rule.action.body = champs.pop("body", "Message reçu par la boîte.")
        rule.action.options.update(
            targets=list(targets),
            mode=mode,
            skip_lists=champs.pop("skip_lists", False),
        )
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        armed = Armed(1, 1, T0 - HOUR)
        storage.upsert_rule("perso", rule, rearm=armed, base=self.base)
        rule.armed = armed
        if approuvee:
            self.deja_approuvee(rule)
        return rule

    def journal(self, rule):
        """(issue, raison) des lignes du journal de `rule`, dans l'ordre,
        sans l'envoi fictif d'approbation."""
        return [
            (e["outcome"], e["reason"])
            for e in reversed(self.store.rule_log_entries(rule.id))
            if e["at"] >= T0
        ]

    def analyser(self, msg):
        return email.message_from_bytes(
            msg.as_bytes(), policy=email.policy.default
        )


class TestForwardPass(ForwardCase):
    def test_inline_forward_reaches_every_target_with_reply_to(self):
        rule = self.renvoi()
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (1, 0))
        self.assertEqual(len(self.envois), 1)
        msg = self.envois[0]
        self.assertNotIsInstance(msg, RawOutgoing)
        self.assertEqual(recipients(msg), [CAROLE, DENIS])
        self.assertEqual(msg["To"], "undisclosed-recipients:;")
        self.assertEqual(msg["Reply-To"], BRUNO)
        self.assertEqual(msg["Subject"], "Fwd: Question 1")
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")
        texte = self.analyser(msg).get_body(("plain",)).get_content()
        self.assertTrue(texte.startswith("Message reçu par la boîte."))
        self.assertIn("Bonjour, une question.", texte)
        self.assertEqual(self.journal(rule), [("sent", None)])

    def test_attachment_mode_sends_an_rfc822_part(self):
        self.renvoi(mode="attachment")
        self.deposer(1)
        self.assertEqual(self.passe().sent, 1)
        msg = self.analyser(self.envois[0])
        types = [part.get_content_type() for part in msg.walk()]
        self.assertIn("message/rfc822", types)
        self.assertEqual(recipients(self.envois[0]), [CAROLE, DENIS])
        # Le Cc d'origine se lit, le Cci jamais.
        self.assertNotIn(b"\nBcc:", self.envois[0].as_bytes())

    def test_redirect_hands_over_raw_bytes_and_an_explicit_envelope(self):
        self.renvoi(mode="redirect")
        brut = self.deposer(1)
        self.assertEqual(self.passe().sent, 1)
        sortie = self.envois[0]
        self.assertIsInstance(sortie, RawOutgoing)
        self.assertEqual(sortie.envelope, (CAROLE, DENIS))
        self.assertEqual(sortie.subject, "Question 1")
        self.assertTrue(sortie.raw.startswith(b"Resent-From: "))
        corps = brut.split(b"\r\n\r\n", 1)[1]
        self.assertTrue(sortie.raw.endswith(b"\r\n\r\n" + corps))
        self.assertNotIn(b"Bcc:", sortie.raw)
        self.assertNotIn(b"Return-Path:", sortie.raw)

    def test_no_return_to_the_sender(self):
        rule = self.renvoi(targets=(BRUNO, CAROLE))
        self.deposer(1)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(recipients(self.envois[0]), [CAROLE])
        self.assertEqual(self.journal(rule), [("sent", None)])

    def test_the_sender_as_only_target_logs_no_forward_target(self):
        rule = self.renvoi(targets=(BRUNO,))
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual(
            (bilan.sent, bilan.skipped["no_forward_target"]), (0, 1)
        )
        self.assertEqual(
            self.journal(rule), [("skipped", "no_forward_target")]
        )
        self.assertEqual(self.imap.body_fetches, [])

    def test_a_forward_is_marked_auto_sent_and_a_redirect_is_not(self):
        transfert = self.renvoi(name="Transfert")
        redirection = self.renvoi(name="Redirection", mode="redirect")
        self.deposer(1)
        self.assertEqual(self.passe().sent, 2)
        msg, brut = self.envois
        self.assertTrue(
            self.store.is_rule_send(msg["Message-ID"], [transfert.id])
        )
        self.assertFalse(self.store.is_rule_send("<1@example.net>"))
        self.assertFalse(
            self.store.is_auto_sent(self.store._msgid_hash("<1@example.net>"))
        )
        self.assertIsInstance(brut, RawOutgoing)
        self.assertEqual(self.journal(redirection), [("sent", None)])

    def test_a_known_size_above_the_cap_skips_without_fetch(self):
        rule = self.renvoi()
        self.deposer(1, size=FORWARD_MAX_BYTES + 1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["too_big"]), (0, 1))
        self.assertEqual(self.journal(rule), [("skipped", "too_big")])
        self.assertEqual(self.imap.body_fetches, [])

    def test_a_size_found_after_download_is_logged_too_big(self):
        rule = self.renvoi()
        brut = self.deposer(1, size=0)
        petit = functools.partial(
            engine.make_raw_loader, max_bytes=len(brut) - 1
        )
        with mock.patch.object(engine, "make_raw_loader", petit):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["too_big"]), (0, 1))
        self.assertEqual(self.journal(rule), [("skipped", "too_big")])
        self.assertEqual(self.imap.body_fetches, [1])
        self.assertEqual(self.etat().cursor, 1)

    def test_offline_bytes_leave_a_hole_and_the_cursor_waits(self):
        rule = self.renvoi()
        self.deposer(1)
        rapport = self.session.sync()
        syncer, self.session.syncer = self.session.syncer, None
        bilan = self.passe(report=rapport)
        self.assertEqual((bilan.sent, bilan.queued, bilan.failed), (0, 0, 0))
        self.assertEqual(bilan.status, "offline")
        self.assertEqual(self.etat().cursor, 0)
        self.assertEqual(self.journal(rule), [])
        self.session.syncer = syncer
        self.assertEqual(self.passe(report=None).sent, 1)
        self.assertEqual(self.etat().cursor, 1)

    def test_a_failed_fetch_logs_body_unavailable(self):
        rule = self.renvoi()
        self.deposer(1)
        self.deposer(2)
        self.imap.body_errors.add(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (1, 1))
        self.assertEqual(
            self.journal(rule),
            [("failed", "body_unavailable"), ("sent", None)],
        )
        self.assertEqual(self.etat().cursor, 2)

    def test_the_first_forward_is_held(self):
        rule = self.renvoi(approuvee=False)
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (0, 1))
        entree = self.store.outbox()[0]
        self.assertEqual(entree["kind"], "auto_forward")
        self.assertEqual(entree["to"], f"{CAROLE}, {DENIS}")
        self.assertEqual(entree["subject"], "Fwd: Question 1")
        self.assertEqual(self.journal(rule), [("held", "hold_first")])
        self.store.set_held(entree["id"], False)
        partis = []
        flush_outbox(
            self.session,
            send_fn=lambda a, m, tr: partis.append(m) or recipients(m),
            connect_fn=lambda a, p: mock.Mock(),
            now=self.horloge,
        )
        self.assertEqual(len(partis), 1)
        self.assertEqual(self.journal(rule), [("sent", None)])

    def test_a_held_redirect_keeps_its_envelope_in_the_queue(self):
        self.renvoi(mode="redirect", approuvee=False)
        brut = self.deposer(1)
        self.assertEqual(self.passe().held, 1)
        entree = self.store.outbox()[0]
        self.assertEqual(entree["kind"], "auto_redirect")
        self.assertEqual(entree["to"], f"{CAROLE}, {DENIS}")
        self.assertEqual(entree["subject"], "Question 1")
        octets = self.store.queued_raw(entree["id"])
        self.assertTrue(octets.startswith(b"Resent-From: "))
        self.assertTrue(octets.endswith(brut.split(b"\r\n\r\n", 1)[1]))

    def test_caps_apply_to_forwards(self):
        self.renvoi()
        storage.save_caps(
            "perso", storage.Caps(per_pass=2, per_hour=60), base=self.base
        )
        for uid in (1, 2, 3):
            self.deposer(uid)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (2, 1))
        self.assertIn(t("mail_rules_cap_warning"), bilan.warnings)
        self.assertEqual(self.store.outbox()[0]["kind"], "auto_forward")

    def test_capped_forwards_beyond_the_queue_bound_are_not_downloaded(self):
        rule = self.renvoi()
        storage.save_caps(
            "perso", storage.Caps(per_pass=1, per_hour=60), base=self.base
        )
        for uid in (1, 2, 3, 4, 5):
            self.deposer(uid)
        with mock.patch.object(engine, "FORWARD_CAP_HELD_MAX", 2):
            bilan = self.passe()
        self.assertEqual(
            (bilan.sent, bilan.held, bilan.skipped["pass_cap"]), (1, 2, 2)
        )
        self.assertIn(t("mail_rules_cap_warning"), bilan.warnings)
        self.assertEqual(self.imap.body_fetches, [1, 2, 3])
        self.assertEqual(len(self.store.outbox()), 2)
        self.assertEqual(
            self.journal(rule),
            [
                ("sent", None),
                ("held", "pass_cap"),
                ("held", "pass_cap"),
                ("skipped", "pass_cap"),
                ("skipped", "pass_cap"),
            ],
        )
        self.assertEqual(self.etat().cursor, 5)

    def test_one_download_serves_two_forward_rules(self):
        self.renvoi(
            name="Transfert",
            filter=Group("all", [Condition("body", "bonjour")]),
        )
        self.renvoi(name="Redirection", mode="redirect")
        self.deposer(1)
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual(self.imap.body_fetches, [1])

    def test_a_reply_to_our_forward_is_skipped_as_own_message(self):
        rule = self.renvoi()
        self.deposer(1)
        self.passe()
        transfert = self.envois[0]["Message-ID"]
        self.deposer(
            2, frm=CAROLE, subject="Re: Fwd: Question 1", in_reply_to=transfert
        )
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["own_message"]), (0, 1))
        self.assertEqual(self.journal(rule)[-1], ("skipped", "own_message"))

    def test_our_own_forward_coming_back_is_own_message(self):
        """Le transfert lui-même revenu dans INBOX (destination qui le
        renvoie tel quel), sans l'`X-Loop` qu'un relais aurait ôté."""
        rule = self.renvoi()
        self.deposer(1)
        self.passe()
        msgid = self.envois[0]["Message-ID"]
        self.deposer(2, frm=CAROLE)
        boite = self.imap.folders["INBOX"]["messages"]
        boite[2] = dataclasses.replace(boite[2], msgid=msgid)
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(self.journal(rule)[-1], ("skipped", "own_message"))

    def test_a_redirect_coming_back_is_skipped_by_a_reply_rule_too(self):
        reponse = self.regle()
        renvoi = self.renvoi(mode="redirect")
        self.deposer(1, extra={"resent-from": f"Boîte <{OWN}>"})
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["resent_loop"]), (0, 2))
        self.assertEqual(self.journal(reponse), [("skipped", "resent_loop")])
        self.assertEqual(self.journal(renvoi), [("skipped", "resent_loop")])

    def test_a_build_error_still_stops_here(self):
        self.renvoi(stop_after=True)
        suivante = self.regle(name="Seconde")
        self.deposer(1)
        self.imap.folders["INBOX"]["bodies"][1] = b""
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        self.assertEqual(self.envois, [])
        self.assertEqual(self.journal(suivante), [])
        self.assertEqual(self.etat().cursor, 1)

    def test_a_hand_edited_invalid_target_fails_as_build_error(self):
        rule = self.renvoi(stop_after=True)
        suivante = self.regle(name="Seconde")
        chemin = storage.rules_path("perso", self.base)
        donnees = json.loads(chemin.read_text())
        for regle in donnees["rules"]:
            if regle["id"] == rule.id:
                regle["action"]["options"]["targets"] = ["carole regle"]
        chemin.write_text(json.dumps(donnees))
        self.deposer(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        self.assertEqual(self.journal(rule), [("failed", "build_error")])
        self.assertEqual(self.journal(suivante), [])
        self.assertEqual(self.envois, [])
        self.assertEqual(self.imap.body_fetches, [])

    def test_a_human_reply_to_an_auto_reply_is_forwarded(self):
        self.regle(filter=Group("all", [Condition("subject", "Question")]))
        self.renvoi(filter=Group("all", [Condition("subject", "Suite")]))
        self.deposer(1)
        self.assertEqual(self.passe().sent, 1)
        reponse = self.envois[0]
        self.assertEqual(reponse["To"], BRUNO)
        self.deposer(2, subject="Suite", in_reply_to=reponse["Message-ID"])
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(recipients(self.envois[1]), [CAROLE, DENIS])

    def test_reply_to_follows_the_original_reply_to(self):
        self.renvoi()
        self.deposer(1, frm=NOREPLY, extra={"reply-to": f"Bruno <{BRUNO}>"})
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.envois[0]["Reply-To"], BRUNO)

    def test_a_reply_to_pointing_at_us_falls_back_to_from(self):
        self.renvoi()
        self.deposer(1, extra={"reply-to": OWN})
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.envois[0]["Reply-To"], BRUNO)


class TestForwardReplyTo(unittest.TestCase):
    def view(self, frm=BRUNO, reply_to=None):
        from script.todo.mail.rules.model import MessageView

        extra = {} if reply_to is None else {"reply-to": reply_to}
        return MessageView(
            1, 1, T0, "<1@example.net>", frm, OWN, "", "s", extra=extra
        )

    def test_reply_to_addresses_minus_ours_deduplicated(self):
        own, others = frozenset({OWN}), frozenset({"relais.auto@example.com"})
        texte = (
            f"Bruno <{BRUNO}>, {OWN}, relais.auto@example.com, "
            f"{BRUNO.upper()}, {DENIS}\n{TEMOIN}"
        )
        self.assertEqual(
            engine.forward_reply_to(self.view(reply_to=texte), own, others),
            f"{BRUNO}, {DENIS}",
        )

    def test_without_reply_to_the_from_address(self):
        vue = self.view(frm="Bruno <bruno.filtre@filtré.example.net>")
        self.assertEqual(
            engine.forward_reply_to(vue, frozenset(), frozenset()),
            "bruno.filtre@xn--filtr-fsa.example.net",
        )

    def test_nothing_usable_gives_no_reply_to(self):
        vue = self.view(frm="Inconnu", reply_to='"x y"@example.net')
        self.assertEqual(
            engine.forward_reply_to(vue, frozenset(), frozenset()), ""
        )


class TestForwardTrial(ForwardCase):
    def simuler(self, rule, uid, *, chargeur=True, **kw):
        header = self.imap.folders["INBOX"]["messages"][uid]
        if chargeur:
            kw["raw_loader"] = engine.make_raw_loader(
                self.session, "INBOX", uid, size=header.size
            )
        kw.setdefault("all_accounts", [])
        return engine.simulate(
            self.session,
            rule,
            header,
            uidvalidity=1,
            now=self.horloge,
            rules_base=self.base,
            **kw,
        )

    def auto_sent(self):
        return (
            self.store._db()
            .execute("SELECT COUNT(*) FROM auto_sent")
            .fetchone()[0]
        )

    def test_simulate_shows_targets_mode_and_size(self):
        rule = self.renvoi(mode="attachment")
        brut = self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        self.assertTrue(sim.executable)
        self.assertEqual((sim.reason, sim.error), (SEND, ""))
        apercu = sim.forward
        self.assertEqual(apercu.mode, "attachment")
        self.assertEqual(apercu.targets, (CAROLE, DENIS))
        self.assertEqual(apercu.removed, ())
        self.assertEqual(apercu.size, len(brut))
        self.assertEqual(apercu.reply_to, BRUNO)
        self.assertEqual(recipients(apercu.outgoing), [CAROLE, DENIS])
        self.assertFalse(apercu.preview_self)
        self.assertEqual(apercu.raw, brut)
        self.assertTrue(sim.sendable)
        self.assertEqual(sim.kind, "forward")

    def test_simulate_with_unreadable_options_names_no_recipient(self):
        from script.todo.mail.tui import rule_trial_lines

        rule = self.renvoi()
        rule.action.options["mode"] = "relais"
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        self.assertIsNone(sim.forward)
        self.assertEqual(sim.kind, "forward")
        textes = [texte for texte, _ in rule_trial_lines(sim)]
        self.assertFalse(any(BRUNO in texte for texte in textes))
        self.assertFalse(
            any(
                texte.startswith(t("mail_rules_trial_target"))
                for texte in textes
            )
        )
        self.assertEqual(textes[-1], sim.error)
        self.assertIsNone(sim.rendered)

    def test_simulate_lists_removed_targets_with_their_reason(self):
        rule = self.renvoi(targets=(BRUNO, CAROLE))
        self.deposer(1)
        self.session.sync()
        apercu = self.simuler(rule, 1).forward
        self.assertEqual(apercu.targets, (CAROLE,))
        self.assertEqual(apercu.removed, ((BRUNO, "sender"),))

    def test_simulate_too_big_does_not_download(self):
        rule = self.renvoi()
        self.deposer(1, size=FORWARD_MAX_BYTES + 1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        self.assertEqual(sim.reason, "too_big")
        self.assertEqual(sim.forward.error, t("mail_rules_reason_too_big"))
        self.assertIsNone(sim.forward.raw)
        self.assertFalse(sim.sendable)
        self.assertEqual(self.imap.body_fetches, [])
        sans = self.simuler(rule, 1, chargeur=False)
        self.assertEqual(sans.forward.error, t("mail_rules_reason_too_big"))

    def test_simulate_without_a_loader_says_the_message_is_unavailable(self):
        rule = self.renvoi()
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1, chargeur=False)
        self.assertEqual(
            sim.forward.error, t("mail_rules_reason_body_unavailable")
        )
        self.assertFalse(sim.sendable)

    def test_simulate_without_kept_target_previews_to_oneself(self):
        rule = self.renvoi(targets=(BRUNO,))
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        self.assertEqual(sim.reason, "no_forward_target")
        apercu = sim.forward
        self.assertTrue(apercu.preview_self)
        self.assertEqual(apercu.targets, ())
        self.assertEqual(recipients(apercu.outgoing), [OWN])
        self.assertTrue(sim.sendable)

    def test_simulate_shows_own_message_for_a_reply_to_our_forward(self):
        """La règle essayée n'est pas encore enregistrée : ses envois
        comptent quand même comme les nôtres."""
        rule = self.renvoi()
        self.deposer(1)
        self.passe()
        essayee = dataclasses.replace(rule, id="essai0000000")
        self.store.mark_auto_sent("<f@example.org>", essayee.id, T0)
        self.deposer(2, frm=CAROLE, in_reply_to="<f@example.org>")
        self.session.sync()
        self.assertEqual(self.simuler(essayee, 2).reason, "own_message")

    def test_send_trial_forward_goes_to_oneself_only(self):
        rule = self.renvoi()
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        partis = []

        def espion(session, msg, verrou=None, **kw):
            partis.append((msg, kw))
            return "parti"

        statut = engine.send_trial(
            self.session, rule, sim, deliver_fn=espion, now=self.horloge
        )
        self.assertEqual(statut, "parti")
        msg, kw = partis[0]
        self.assertEqual(kw, {"queue_offline": False})
        self.assertEqual(recipients(msg), [OWN])
        self.assertNotIn(CAROLE.encode(), msg.as_bytes())
        self.assertTrue(
            msg["Subject"].startswith(
                f"{t('mail_rules_trial_subject_prefix')} Fwd:"
            )
        )
        self.assertEqual(msg["Reply-To"], BRUNO)
        self.assertTrue(self.store.is_rule_send(msg["Message-ID"]))
        self.assertEqual(self.journal(rule), [])
        self.assertEqual(self.store.outbox(), [])

    def test_send_trial_redirect_goes_to_oneself_only(self):
        rule = self.renvoi(mode="redirect")
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        avant = self.auto_sent()
        partis = []
        engine.send_trial(
            self.session,
            rule,
            sim,
            deliver_fn=lambda s, m, **kw: partis.append(m) or "parti",
            now=self.horloge,
        )
        sortie = partis[0]
        self.assertIsInstance(sortie, RawOutgoing)
        self.assertEqual(sortie.envelope, (OWN,))
        self.assertEqual(sortie.subject, "Question 1")
        self.assertIn(b"\r\nSubject: Question 1\r\n", sortie.raw)
        self.assertEqual(self.auto_sent(), avant)
        self.assertEqual(self.journal(rule), [])

    def test_send_trial_offline_raises(self):
        rule = self.renvoi()
        self.deposer(1)
        self.session.sync()
        sim = self.simuler(rule, 1)
        hors_ligne = Session(self.account, self.store, None, password="x")
        with self.assertRaises(RuleError) as pris:
            engine.send_trial(hors_ligne, rule, sim, now=self.horloge)
        self.assertEqual(str(pris.exception), t("mail_rules_trial_offline"))
        self.assertEqual(self.store.outbox(), [])

    def test_simulate_writes_nothing(self):
        rule = self.renvoi()
        self.deposer(1)
        self.session.sync()
        regles = storage.rules_path("perso", self.base).read_bytes()
        etat = storage.state_path("perso", self.base)
        avant = (
            self.journal(rule),
            etat.read_bytes() if etat.exists() else None,
            self.auto_sent(),
            self.store.outbox(),
        )
        sim = self.simuler(rule, 1)
        self.assertIsNotNone(sim.forward.outgoing)
        apres = (
            self.journal(rule),
            etat.read_bytes() if etat.exists() else None,
            self.auto_sent(),
            self.store.outbox(),
        )
        self.assertEqual(apres, avant)
        self.assertEqual(
            storage.rules_path("perso", self.base).read_bytes(), regles
        )
        self.assertEqual(self.envois, [])


if __name__ == "__main__":
    unittest.main()
