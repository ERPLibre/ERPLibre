#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur des règles, de la synchronisation à la sortie de la réponse.

Chaque test monte un vrai cache clair dans un dossier temporaire (la base
des règles en découle), un serveur IMAP en mémoire, une horloge injectée et
un `deliver` espion. La retenue du premier envoi ne se désactive pas :
un test qui attend un envoi DIRECT inscrit d'abord au journal un envoi
`sent` fictif sous l'empreinte de la règle (`deja_approuvee`).
"""

import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_mail_sync import FakeImapTransport

from script.todo.mail import accounts as mail_accounts
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import HeaderInfo, Syncer
from script.todo.mail.imap_transport import ImapError
from script.todo.mail.rules import engine, storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import Armed, Condition, Group, new_rule
from script.todo.mail.smtp_send import SmtpError, recipients
from script.todo.mail.store import Store
from script.todo.mail.tui import Session, flush_outbox
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
REPONDEUR = "service.repondeur@example.com"
RELAIS = "relais.auto@example.com"
DENIS = "denis.tri@example.org"
T0 = 1_790_000_000
HOUR = 3600


class Horloge:
    def __init__(self, instant):
        self.instant = instant

    def __call__(self):
        return self.instant


class Imap(FakeImapTransport):
    """Le serveur en mémoire, avec les champs v6 et des compteurs."""

    def __init__(self):
        super().__init__(
            {"INBOX": {"uidvalidity": 1, "messages": {}, "bodies": {}}}
        )
        self.body_fetches = []
        self.header_fetches = []
        self.body_errors = set()

    def recevoir(
        self,
        uid,
        *,
        frm=CAROLE,
        to=OWN,
        subject=None,
        internaldate=None,
        extra=None,
        msgid=None,
        references="",
        body="Bonjour, une question.",
    ):
        raw = (
            f"From: {frm}\r\nTo: {to}\r\nSubject: s\r\n\r\n{body}\r\n"
        ).encode()
        boite = self.folders["INBOX"]
        boite["messages"][uid] = HeaderInfo(
            uid=uid,
            date=internaldate or T0 + uid,
            size=len(raw),
            flags="",
            msgid=f"<{uid}@example.net>" if msgid is None else msgid,
            frm=frm,
            to=to,
            subject=subject or f"Question {uid}",
            references=references,
            internaldate=T0 + uid if internaldate is None else internaldate,
            extra=dict(extra or {}),
        )
        boite["bodies"][uid] = raw

    def fetch_headers(self, uids):
        self.header_fetches.append(list(uids))
        return super().fetch_headers(uids)

    def fetch_body(self, uid):
        self.body_fetches.append(uid)
        if uid in self.body_errors:
            raise ImapError(f"no body {uid}")
        return super().fetch_body(uid)


class FauxSmtp:
    def quit(self):
        pass


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.account = account_from_preset("perso", OWN, "generic")
        self.store = Store(self.account, mode="clear", base=self.base)
        self.store.open()
        self.imap = Imap()
        self.syncer = Syncer(self.store, self.imap)
        self.session = Session(
            self.account, self.store, self.syncer, password="x"
        )
        self.horloge = Horloge(T0 + 1000)
        self.envois = []

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    # -- aides -----------------------------------------------------------

    def espion(self, session, msg, verrou=None, **_kw):
        self.envois.append(msg)
        return "ok"

    def regle(self, *, approuvee=True, armed=None, **champs):
        """Une règle « réponse » enregistrée et armée avant les messages."""
        rule = new_rule("reply", champs.pop("name", "Absence"))
        rule.action.format = "text"
        rule.action.body = champs.pop("body", "Je suis absente.")
        for cle, valeur in champs.items():
            setattr(rule, cle, valeur)
        armed = armed or Armed(1, 1, T0 - HOUR)
        storage.upsert_rule("perso", rule, rearm=armed, base=self.base)
        rule.armed = armed
        if approuvee:
            self.deja_approuvee(rule)
        return rule

    def deja_approuvee(self, rule):
        self.store.rule_log_claim(
            rule.id,
            f"pre-{rule.id}-{rule.fingerprint()}",
            outcome="sent",
            at=T0 - 30 * 86400,
            fingerprint=rule.fingerprint(),
        )

    def passe(self, report="sync", **kw):
        rapport = self.session.sync() if report == "sync" else report
        kw.setdefault("deliver_fn", self.espion)
        kw.setdefault("all_accounts", [])
        return engine.run_pass(
            self.session, report=rapport, now=self.horloge, **kw
        )

    def etat(self):
        return storage.load_state("perso", self.base)

    def destinataires(self):
        return [m["To"] for m in self.envois]


class TestIdempotenceAndArming(EngineCase):
    def test_two_passes_send_a_single_reply(self):
        self.regle()
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(len(self.envois), 1)

    def test_the_backlog_before_arming_gets_no_reply(self):
        """Une règle armée à sa première passe n'agit que sur ce qui
        arrive APRÈS : l'arriéré déjà en boîte reste sans réponse."""
        self.imap.recevoir(1)
        self.imap.recevoir(2, frm=BRUNO)
        self.session.sync()
        rule = new_rule("reply", "Absence")
        rule.action.format = "text"
        rule.action.body = "Absente."
        storage.upsert_rule("perso", rule, base=self.base)
        self.deja_approuvee(rule)
        self.assertEqual(self.passe().sent, 0)
        armed = storage.load("perso", self.base)[0].armed
        self.assertEqual((armed.uidvalidity, armed.uidnext), (1, 3))
        self.horloge.instant += 100
        self.imap.recevoir(3, frm=DENIS, internaldate=self.horloge() - 10)
        self.assertEqual(self.passe().sent, 1)
        self.assertEqual(self.destinataires(), [DENIS])

    def test_a_message_older_than_the_limit_is_logged_too_old(self):
        rule = self.regle(armed=Armed(1, 1, T0 - 100 * HOUR))
        self.imap.recevoir(1, internaldate=self.horloge() - 49 * HOUR)
        rapport = self.passe()
        self.assertEqual(rapport.sent, 0)
        self.assertEqual(rapport.skipped["too_old"], 1)
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"], "too_old"
        )


class TestThrottleEndToEnd(EngineCase):
    """La limite d'envoi par règle et par expéditeur en trois passes,
    l'horloge avancée entre chacune : elle se mesure depuis l'instant de
    la passe."""

    def scenario(self, *, enabled=True, return_paths=False):
        self.regle(throttle_enabled=enabled, throttle_minutes=10)
        resultats = []
        for uid, decalage in ((1, 0), (2, 300), (3, 660)):
            extra = {}
            if return_paths:
                extra = {"return-path": f"<prvs=00{uid}={CAROLE}>"}
            self.imap.recevoir(uid, internaldate=T0 + decalage, extra=extra)
            self.horloge.instant = T0 + decalage + 1
            rapport = self.passe()
            resultats.append(
                (rapport.sent, rapport.skipped.get("throttled", 0))
            )
        return resultats

    def test_the_second_message_within_the_window_is_throttled(self):
        self.assertEqual(self.scenario(), [(1, 0), (0, 1), (1, 0)])

    def test_a_changing_envelope_does_not_bypass_the_limit(self):
        """BATV : le Return-Path change à chaque message, le From reste."""
        self.assertEqual(
            self.scenario(return_paths=True), [(1, 0), (0, 1), (1, 0)]
        )

    def test_unchecked_box_answers_all_three(self):
        self.assertEqual(self.scenario(enabled=False), [(1, 0)] * 3)


class TestHoldFirst(EngineCase):
    def vider(self):
        return flush_outbox(
            self.session,
            send_fn=lambda a, m, tr: self.envois.append(m) or [CAROLE],
            connect_fn=lambda a, p: FauxSmtp(),
            now=self.horloge,
        )

    def test_first_send_waits_then_the_next_goes_directly(self):
        rule = self.regle(approuvee=False, throttle_enabled=False)
        self.imap.recevoir(1)
        rapport = self.passe()
        self.assertEqual((rapport.sent, rapport.held), (0, 1))
        self.assertEqual(self.envois, [])
        entree = self.store.outbox()[0]
        self.assertTrue(entree["held"])
        self.assertEqual(entree["kind"], "auto_reply")
        self.store.set_held(entree["id"], False)
        self.assertEqual(self.vider()[0], 1)
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["outcome"], "sent"
        )
        self.imap.recevoir(2, frm=BRUNO)
        self.assertEqual(self.passe().sent, 1)

    def test_a_changed_body_drops_the_held_entry_and_holds_again(self):
        rule = self.regle(approuvee=False, throttle_enabled=False)
        self.imap.recevoir(1)
        self.passe()
        rule.action.body = "Nouveau texte."
        storage.upsert_rule("perso", rule, base=self.base)
        self.assertEqual(self.vider(), (0, 0, 0))
        self.assertEqual(self.store.outbox(), [])
        derniere = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (derniere["outcome"], derniere["reason"]),
            ("expired", "rule_changed"),
        )
        self.imap.recevoir(2, frm=BRUNO)
        rapport = self.passe()
        self.assertEqual((rapport.sent, rapport.held), (0, 1))


class TestCaps(EngineCase):
    def test_twenty_per_pass_and_the_rest_held_with_one_warning(self):
        self.regle(throttle_enabled=False)
        for uid in range(1, 26):
            self.imap.recevoir(uid)
        rapport = self.passe()
        self.assertEqual((rapport.sent, rapport.held), (20, 5))
        self.assertEqual(rapport.warnings, [t("mail_rules_cap_warning")])
        raisons = {
            e["reason"]
            for e in self.store.rule_log_entries()
            if e["outcome"] == "held"
        }
        self.assertEqual(raisons, {"pass_cap"})

    def test_the_hourly_cap_from_rules_json_holds_the_excess(self):
        """Plafond horaire : 60 par heure glissante par défaut, réglable."""
        self.regle(throttle_enabled=False)
        storage.save_caps(
            "perso", storage.Caps(per_pass=20, per_hour=3), base=self.base
        )
        for uid in range(1, 6):
            self.imap.recevoir(uid)
        rapport = self.passe()
        self.assertEqual((rapport.sent, rapport.held), (3, 2))
        self.assertIn(t("mail_rules_cap_warning"), rapport.warnings)
        held = [
            e["reason"]
            for e in self.store.rule_log_entries()
            if e["outcome"] == "held"
        ]
        self.assertEqual(held, ["hour_cap", "hour_cap"])

    def test_the_hourly_window_slides(self):
        self.regle(throttle_enabled=False)
        storage.save_caps(
            "perso", storage.Caps(per_pass=20, per_hour=1), base=self.base
        )
        self.imap.recevoir(1)
        self.assertEqual(self.passe().sent, 1)
        self.imap.recevoir(2, frm=BRUNO, internaldate=T0 + HOUR + 500)
        self.horloge.instant = T0 + HOUR + 1001
        self.assertEqual(self.passe().sent, 1)

    def test_caps_are_read_from_the_file_by_default(self):
        caps = storage.load_caps("perso", self.base)
        self.assertEqual((caps.per_pass, caps.per_hour), (20, 60))

    def test_saved_caps_survive_a_rule_update(self):
        rule = self.regle()
        storage.save_caps(
            "perso", storage.Caps(per_pass=4, per_hour=9), base=self.base
        )
        rule.name = "Renommée"
        storage.upsert_rule("perso", rule, base=self.base)
        caps = storage.load_caps("perso", self.base)
        self.assertEqual((caps.per_pass, caps.per_hour), (4, 9))
        self.assertEqual(storage.load("perso", self.base)[0].name, "Renommée")

    def test_an_invalid_cap_is_refused_and_stops_the_pass(self):
        from script.todo.mail.rules.model import RuleError

        with self.assertRaises(RuleError):
            storage.save_caps(
                "perso", storage.Caps(per_pass=0), base=self.base
            )
        self.regle()
        chemin = storage.rules_path("perso", self.base)
        texte = chemin.read_text().replace(
            '"version": 1,', '"version": 1, "caps": {"per_hour": true},'
        )
        chemin.write_text(texte)
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.status, bilan.sent), ("error", 0))

    def test_recent_sends_count_sent_and_queued_only(self):
        for cle, issue, instant in (
            ("a", "sent", T0),
            ("b", "queued", T0),
            ("c", "held", T0),
            ("d", "skipped", T0),
            ("e", "sent", T0 - 2 * HOUR),
        ):
            self.store.rule_log_claim("r", cle, outcome=issue, at=instant)
        self.assertEqual(self.store.rule_log_recent_sends(T0 - HOUR), 2)


class TestOutputs(EngineCase):
    def test_offline_queues_with_a_24h_expiry(self):
        rule = self.regle()
        self.imap.recevoir(1)
        rapport = self.session.sync()
        self.session.syncer = None
        bilan = self.passe(report=rapport)
        self.assertEqual(bilan.queued, 1)
        entree = self.store.outbox()[0]
        self.assertEqual(entree["expires_at"], self.horloge() + 86400)
        self.assertFalse(entree["held"])
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"], "offline"
        )

    def test_going_offline_during_the_send_queues_an_auto_entry(self):
        """La session passe hors ligne entre le contrôle du moteur et
        l'envoi : la réponse entre en file comme réponse AUTOMATIQUE
        (règle, échéance), jamais comme un envoi manuel, et le journal ne
        dit pas `sent`."""
        from script.todo.mail.tui import DeliverOffline

        rule = self.regle()
        self.imap.recevoir(1)
        appels = []

        def tombe(session, msg, verrou=None, **kw):
            appels.append(kw)
            raise DeliverOffline()

        bilan = self.passe(deliver_fn=tombe)
        self.assertEqual(appels, [{"queue_offline": False}])
        self.assertEqual((bilan.sent, bilan.queued), (0, 1))
        entree = self.store.outbox()[0]
        self.assertEqual(entree["kind"], "auto_reply")
        self.assertEqual(entree["rule_id"], rule.id)
        self.assertEqual(entree["expires_at"], self.horloge() + 86400)
        journal = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (journal["outcome"], journal["reason"]), ("queued", "offline")
        )

    def test_a_transient_refusal_queues(self):
        rule = self.regle()
        self.imap.recevoir(1)

        def refuse(session, msg, verrou=None, **_kw):
            raise SmtpError("421 plus tard", code=421)

        bilan = self.passe(deliver_fn=refuse)
        self.assertEqual(bilan.queued, 1)
        entree = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("queued", "smtp_transient")
        )

    def test_a_permanent_refusal_fails_and_queues_nothing(self):
        rule = self.regle()
        self.imap.recevoir(1)

        def refuse(session, msg, verrou=None, **_kw):
            raise SmtpError(f"550 <{CAROLE}> refusé", code=550)

        bilan = self.passe(deliver_fn=refuse)
        self.assertEqual((bilan.failed, bilan.queued), (1, 0))
        self.assertEqual(self.store.outbox(), [])
        entree = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("failed", "smtp_permanent")
        )

    def test_the_log_carries_no_address_after_a_550(self):
        self.regle()
        self.imap.recevoir(1)
        flux = io.StringIO()
        handler = logging.StreamHandler(flux)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("script.todo.mail")
        ancien = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:

            def refuse(session, msg, verrou=None, **_kw):
                raise SmtpError(f"550 <{CAROLE}> refusé", code=550)

            self.passe(deliver_fn=refuse)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(ancien)
        texte = flux.getvalue()
        self.assertIn("smtp_permanent", texte)
        self.assertNotIn("@", texte)

    def test_auto_sent_is_filled_and_no_answered_flag_is_set(self):
        self.regle()
        self.imap.recevoir(1)
        self.passe()
        envoye = self.envois[0]
        cle = self.store._msgid_hash(envoye["Message-ID"].strip())
        self.assertTrue(self.store.is_auto_sent(cle))
        self.assertEqual(self.imap.stored_flags, [])

    def test_the_reply_follows_rfc_3834(self):
        self.regle()
        self.imap.recevoir(1, references="<a@example.net>\r\n <b@example.net>")
        self.passe()
        envoye = self.envois[0]
        self.assertEqual(envoye["To"], CAROLE)
        self.assertEqual(envoye["Auto-Submitted"], "auto-replied")
        self.assertIn("<1@example.net>", envoye["References"])
        self.assertTrue(envoye["Subject"].startswith("Auto:"))


class TestBody(EngineCase):
    def corps(self, valeur="urgent", nier=False):
        cond = Condition("body", valeur)
        racine = Group("all", [Group("not", [cond]) if nier else cond])
        return racine

    def test_no_body_is_fetched_without_a_body_rule(self):
        self.regle()
        self.imap.recevoir(1)
        self.passe()
        self.assertEqual(self.imap.body_fetches, [])

    def test_two_body_rules_fetch_the_body_once(self):
        self.regle(filter=self.corps())
        self.regle(name="Seconde", filter=self.corps(), throttle_enabled=False)
        self.imap.recevoir(1, body="C'est urgent.")
        self.passe()
        self.assertEqual(self.imap.body_fetches, [1])
        self.assertEqual(len(self.envois), 2)

    def test_a_not_body_rule_offline_waits_for_the_link(self):
        """Hors ligne, le corps est inconnu : sous un NON, le tenir pour
        vide déclencherait un envoi sans l'avoir lu."""
        self.regle(filter=self.corps("désabonnement", nier=True))
        self.imap.recevoir(1)
        rapport = self.session.sync()
        syncer, self.session.syncer = self.session.syncer, None
        bilan = self.passe(report=rapport)
        self.assertEqual((bilan.sent, bilan.queued), (0, 0))
        self.assertEqual(bilan.status, "offline")
        self.assertEqual(self.etat().cursor, 0)
        self.session.syncer = syncer
        self.assertEqual(self.passe(report=None).sent, 1)
        self.assertEqual(self.etat().cursor, 1)

    def test_a_failed_body_fetch_is_logged_and_the_next_one_proceeds(self):
        rule = self.regle(filter=self.corps(), throttle_enabled=False)
        self.imap.recevoir(1, body="urgent")
        self.imap.recevoir(2, body="urgent", frm=BRUNO)
        self.imap.body_errors.add(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (1, 1))
        raisons = [
            e["reason"]
            for e in self.store.rule_log_entries(rule.id)
            if e["outcome"] == "failed"
        ]
        self.assertEqual(raisons, ["body_unavailable"])
        self.assertEqual(self.etat().cursor, 2)


class TestPoisonAndCursor(EngineCase):
    def test_a_message_that_cannot_be_built_does_not_block_the_rest(self):
        from script.todo.mail import smtp_send

        rule = self.regle(throttle_enabled=False)
        self.imap.recevoir(1, subject="casse")
        self.imap.recevoir(2, frm=BRUNO)
        vrai = smtp_send.build_auto_reply

        def construire(account, to, subject, *a, **k):
            if "casse" in subject:
                raise ValueError("en-tête invalide")
            return vrai(account, to, subject, *a, **k)

        with mock.patch.object(smtp_send, "build_auto_reply", construire):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (1, 1))
        echec = [
            e
            for e in self.store.rule_log_entries(rule.id)
            if e["outcome"] == "failed"
        ]
        self.assertEqual(echec[0]["reason"], "build_error")
        self.assertEqual(self.etat().cursor, 2)

    def test_a_uid_gone_from_the_server_is_passed_and_not_refetched(self):
        self.regle(throttle_enabled=False)
        self.imap.recevoir(1)
        self.imap.recevoir(2, frm=BRUNO)
        self.session.sync()
        del self.imap.folders["INBOX"]["messages"][2]
        self.imap.header_fetches.clear()
        bilan = self.passe(report=None)
        self.assertEqual((bilan.sent, bilan.skipped["gone"]), (1, 1))
        self.assertEqual(self.etat().cursor, 2)
        self.imap.header_fetches.clear()
        self.passe(report=None)
        self.assertEqual(self.imap.header_fetches, [])

    def test_beyond_the_catch_up_limit_the_cursor_jumps(self):
        self.regle(throttle_enabled=False)
        for uid in range(1, 5):
            self.imap.recevoir(uid)
        self.session.sync()
        with mock.patch.object(engine, "CATCHUP_MAX", 2):
            bilan = self.passe(report=None)
        self.assertEqual(bilan.skipped["catchup_overflow"], 2)
        self.assertIn(t("mail_rules_catchup_warning"), bilan.warnings)
        self.assertEqual(self.etat().cursor, 4)
        self.assertEqual(bilan.sent, 2)

    def test_the_cursor_never_goes_back(self):
        self.regle()
        self.imap.recevoir(1)
        self.session.sync()
        storage.save_state(
            "perso",
            storage.EngineState(uidvalidity=1, cursor=10),
            base=self.base,
        )
        self.passe(report=None)
        self.assertEqual(self.etat().cursor, 10)
        self.assertEqual(self.envois, [])

    def test_a_rule_armed_late_fetches_nothing_below_its_arming(self):
        for uid in range(1, 61):
            self.imap.recevoir(uid)
        self.session.sync()
        self.regle(armed=Armed(1, 50, T0 - HOUR), throttle_enabled=False)
        self.imap.header_fetches.clear()
        self.passe(report=None)
        demandes = [u for lot in self.imap.header_fetches for u in lot]
        self.assertTrue(demandes)
        self.assertGreaterEqual(min(demandes), 50)

    def test_a_report_without_inbox_fields_is_accepted(self):
        self.regle()
        self.imap.recevoir(1)
        self.session.sync()
        bilan = self.passe(report=SimpleNamespace(new_messages=0, errors=[]))
        self.assertEqual(bilan.sent, 1)

    def test_without_report_the_pass_catches_up_from_the_cursor(self):
        self.regle()
        self.imap.recevoir(1)
        self.session.sync()
        self.assertEqual(self.passe(report=None).sent, 1)


class TestRulesLifecycle(EngineCase):
    def lock_and_state(self):
        dossier = self.base / ".rules" / "perso"
        return (dossier / "lock").exists(), (dossier / "state.json").exists()

    def test_no_active_rule_creates_neither_lock_nor_state(self):
        rule = self.regle()
        storage.set_enabled(
            "perso", rule.id, False, armed=None, base=self.base
        )
        (self.base / ".rules" / "perso" / "lock").unlink()
        self.imap.recevoir(1)
        self.assertEqual(self.passe().status, "no_rules")
        self.assertEqual(self.lock_and_state(), (False, False))

    def test_no_rules_file_at_all(self):
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.status, bilan.active_rules), ("no_rules", 0))
        self.assertFalse((self.base / ".rules").exists())

    def test_a_rule_disabled_before_the_lock_does_not_act(self):
        rule = self.regle()
        self.imap.recevoir(1)
        vrai = storage.load
        appels = []

        def charger(name, base=None):
            regles = vrai(name, base)
            if not appels:
                storage.set_enabled(
                    name, rule.id, False, armed=None, base=base
                )
            appels.append(1)
            return regles

        with mock.patch.object(engine.storage, "load", charger):
            bilan = self.passe()
        self.assertEqual(bilan.status, "no_rules")
        self.assertEqual(self.envois, [])

    def test_a_rebuilt_cache_holds_until_the_window_passes(self):
        self.regle(throttle_minutes=60)
        self.passe()
        db = self.store._db()
        db.execute("UPDATE meta SET value = 'autre' WHERE key = 'cache_epoch'")
        db.commit()
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.held), (0, 1))
        self.assertIn(t("mail_rules_cache_rebuilt"), bilan.warnings)
        self.assertEqual(
            self.store.rule_log_entries()[0]["reason"], "cache_rebuilt"
        )
        self.horloge.instant += 2 * HOUR
        self.imap.recevoir(2, frm=BRUNO, internaldate=self.horloge() - 5)
        self.assertEqual(self.passe().sent, 1)

    def test_stop_after_halts_the_following_rules(self):
        premiere = self.regle(name="Première", stop_after=True)
        seconde = self.regle(name="Seconde")
        self.imap.recevoir(1)
        self.passe()
        self.assertEqual(len(self.envois), 1)
        recentes = [
            e
            for e in self.store.rule_log_entries(seconde.id)
            if e["at"] > T0 - HOUR
        ]
        self.assertEqual(recentes, [])
        self.assertEqual(
            self.store.rule_log_entries(premiere.id)[0]["outcome"], "sent"
        )

    def test_rules_apply_in_their_order(self):
        un = self.regle(name="Un")
        deux = self.regle(name="Deux")
        un.action.subject = "un {subject}"
        deux.action.subject = "deux {subject}"
        storage.upsert_rule("perso", un, base=self.base)
        storage.upsert_rule("perso", deux, base=self.base)
        self.deja_approuvee(un)
        self.deja_approuvee(deux)
        storage.move_rule("perso", deux.id, -1, base=self.base)
        self.imap.recevoir(1)
        self.passe()
        self.assertEqual(
            [m["Subject"].split()[0] for m in self.envois], ["deux", "un"]
        )

    def test_an_ephemeral_cache_disables_rules(self):
        session = SimpleNamespace(
            account=self.account,
            store=SimpleNamespace(mode="ephemeral"),
            syncer=None,
            online=False,
        )
        bilan = engine.run_pass(session, now=self.horloge)
        self.assertEqual(bilan.status, "ephemeral")

    def test_forward_rules_are_run(self):
        rule = new_rule("forward", "forward")
        rule.action.options["targets"] = [DENIS]
        storage.upsert_rule(
            "perso", rule, rearm=Armed(1, 1, T0 - HOUR), base=self.base
        )
        self.deja_approuvee(rule)
        self.imap.recevoir(1)
        bilan = self.passe()
        self.assertEqual((bilan.status, bilan.sent), ("ok", 1))
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(recipients(self.envois[0]), [DENIS])

    def test_a_renumbered_inbox_rearms_and_sends_nothing(self):
        rule = self.regle()
        self.imap.recevoir(1)
        self.passe()
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        self.imap.recevoir(2, frm=BRUNO)
        bilan = self.passe()
        self.assertEqual((bilan.status, bilan.sent), ("rearmed", 0))
        armed = storage.load("perso", self.base)[0].armed
        self.assertEqual(armed.uidvalidity, 2)
        self.assertEqual(len(self.envois), 1)
        self.assertEqual(rule.id, storage.load("perso", self.base)[0].id)

    def test_a_lock_held_elsewhere_then_the_next_pass_catches_up(self):
        self.regle()
        self.imap.recevoir(1)
        rapport = self.session.sync()
        verrou = storage.lock_path("perso", self.base)
        with file_lock(verrou, wait=0) as tenu:
            self.assertTrue(tenu)
            bilan = self.passe(report=rapport, lock_wait=0.05)
        self.assertEqual(bilan.status, "locked")
        self.assertEqual(self.envois, [])
        self.assertEqual(self.passe(report=None).sent, 1)

    def test_empty_message_ids_are_two_distinct_messages(self):
        self.regle(throttle_enabled=False)
        self.imap.recevoir(1, msgid="")
        self.imap.recevoir(2, msgid="", frm=BRUNO)
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual(self.passe(report=None).sent, 0)
        self.assertEqual(sorted(self.destinataires()), [BRUNO, CAROLE])


class TestGuardsWiring(EngineCase):
    def raison(self, **message):
        rule = self.regle()
        self.imap.recevoir(1, **message)
        bilan = self.passe(all_accounts=self.comptes())
        self.assertEqual(bilan.sent, 0)
        return self.store.rule_log_entries(rule.id)[0]["reason"]

    def comptes(self):
        return []

    def test_our_own_address_is_self(self):
        self.assertEqual(self.raison(frm=OWN), "self")

    def test_an_x_loop_from_another_instance(self):
        extra = {"x-loop": f"erplibre-rules {RELAIS}"}
        self.assertEqual(self.raison(extra=extra), "x_loop")

    def test_an_auto_reply_is_not_answered(self):
        extra = {"auto-submitted": "auto-replied"}
        self.assertEqual(
            self.raison(frm=REPONDEUR, extra=extra), "auto_submitted"
        )


class TestOtherAccountFromAccountsFile(EngineCase):
    """`all_accounts=None` : les autres comptes viennent de
    `accounts.json`, lu dans un dossier personnel temporaire."""

    def setUp(self):
        super().setUp()
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        autre = account_from_preset("relais", RELAIS, "generic")
        mail_accounts.save([self.account, autre])

    def tearDown(self):
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()
        super().tearDown()

    def test_a_message_from_another_configured_account(self):
        rule = self.regle()
        self.imap.recevoir(1, frm=RELAIS)
        bilan = engine.run_pass(
            self.session,
            report=self.session.sync(),
            now=self.horloge,
            deliver_fn=self.espion,
        )
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(
            self.store.rule_log_entries(rule.id)[0]["reason"], "other_account"
        )


class TestRegexTimeout(EngineCase):
    """Une expression régulière qui dépasse son budget : la règle échoue,
    journalisée, sans envoi ; son verdict inconnu vaut « arrêter ici »."""

    def lente(self, **champs):
        racine = Group(children=[Condition("subject", "x", mode="regex")])
        return self.regle(filter=racine, **champs)

    def passe_lente(self):
        from script.todo.mail.rules.regex_worker import RegexTimeout

        with mock.patch(
            "script.todo.mail.rules.filter.search_any",
            side_effect=RegexTimeout(t("mail_rules_err_regex_timeout")),
        ):
            return self.passe()

    def test_a_timeout_is_logged_and_sends_nothing(self):
        rule = self.lente()
        self.imap.recevoir(1)
        bilan = self.passe_lente()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        entree = self.store.rule_log_entries(rule.id)[0]
        self.assertEqual(
            (entree["outcome"], entree["reason"]), ("failed", "regex_timeout")
        )
        self.assertIn(t("mail_rules_reason_regex_timeout"), bilan.errors[-1])

    def test_a_timeout_on_a_stop_rule_stops_the_next_rules(self):
        self.lente(stop_after=True)
        self.regle(name="Seconde", throttle_enabled=False)
        self.imap.recevoir(1)
        self.assertEqual(self.passe_lente().sent, 0)
        self.assertEqual(self.envois, [])

    def test_a_timeout_on_a_rule_that_does_not_stop_lets_the_next_run(self):
        self.lente(stop_after=False)
        self.regle(name="Seconde", throttle_enabled=False)
        self.imap.recevoir(1)
        self.assertEqual(self.passe_lente().sent, 1)


class TestStopAfterAcrossPasses(EngineCase):
    """« Arrêter ici » tient même quand le message est revu à une autre
    passe, ou que sa réponse n'a pas pu être construite."""

    def rattrapage_en_echec(self):
        """Le cache connaît 1 et 2 ; le rapport ne porte que 2 et le FETCH
        de rattrapage de 1 lève tant que `self.panne` est vrai."""
        from script.todo.mail.imap_sync import SyncReport

        self.imap.recevoir(1, frm=BRUNO)
        self.imap.recevoir(2, frm=CAROLE)
        self.session.sync()
        vrai = self.imap.fetch_headers
        self.panne = True

        def fetch(uids):
            if self.panne and 1 in uids:
                raise ImapError("indisponible")
            return vrai(uids)

        self.imap.fetch_headers = fetch
        deux = self.imap.folders["INBOX"]["messages"][2]
        return SyncReport(inbox_folder="INBOX", inbox=[deux])

    def test_a_message_above_a_gap_is_not_evaluated_twice(self):
        from script.todo.mail.imap_sync import SyncReport

        self.regle(name="Première", stop_after=True)
        seconde = self.regle(name="Seconde")
        rapport = self.rattrapage_en_echec()
        self.assertEqual(self.passe(report=rapport).sent, 1)
        self.assertEqual(self.etat().done, [2])
        self.panne = False
        self.passe(report=SyncReport(inbox_folder="INBOX", inbox=[]))
        self.assertEqual(self.destinataires(), [CAROLE, BRUNO])
        recentes = [
            e
            for e in self.store.rule_log_entries(seconde.id)
            if e["at"] > T0 - HOUR
        ]
        self.assertEqual(recentes, [])
        self.assertEqual((self.etat().cursor, self.etat().done), (2, []))

    def test_a_catch_up_failure_reaches_the_summary(self):
        self.regle()
        bilan = self.passe(report=self.rattrapage_en_echec())
        self.assertIn(t("mail_rules_error"), bilan.warnings)
        self.assertIn(t("mail_rules_error"), engine.summary_line([bilan]))

    def test_a_reply_that_cannot_be_built_still_stops(self):
        from script.todo.mail import smtp_send

        premiere = self.regle(name="Première", stop_after=True)
        self.regle(name="Seconde")
        self.imap.recevoir(1)
        vrai = smtp_send.build_auto_reply
        appels = []

        def construire(*a, **k):
            appels.append(1)
            if len(appels) == 1:
                raise smtp_send.SmtpError("en-tête invalide")
            return vrai(*a, **k)

        with mock.patch.object(smtp_send, "build_auto_reply", construire):
            bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.failed), (0, 1))
        self.assertEqual(self.envois, [])
        self.assertEqual(
            self.store.rule_log_entries(premiere.id)[0]["reason"],
            "build_error",
        )

    def test_the_done_list_is_reset_by_a_renumbered_inbox(self):
        self.regle()
        self.passe(report=self.rattrapage_en_echec())
        self.assertEqual(self.etat().done, [2])
        self.imap.folders["INBOX"]["uidvalidity"] = 2
        self.assertEqual(self.passe().status, "rearmed")
        self.assertEqual(self.etat().done, [])


class TestSmtpDown(EngineCase):
    def test_after_a_transient_failure_the_rest_is_queued_untried(self):
        """Serveur injoignable : un seul essai par passe, le reste en file,
        au lieu d'un délai de connexion par réponse verrou tenu."""
        self.regle(throttle_enabled=False)
        for uid, frm in enumerate((CAROLE, BRUNO, DENIS), start=1):
            self.imap.recevoir(uid, frm=frm)
        essais = []

        def injoignable(session, msg, verrou=None, **_kw):
            essais.append(msg)
            raise SmtpError("délai de connexion dépassé")

        bilan = self.passe(deliver_fn=injoignable)
        self.assertEqual(len(essais), 1)
        self.assertEqual((bilan.sent, bilan.queued), (0, 3))
        self.assertEqual(len(self.store.outbox()), 3)


class TestLockedOrBrokenPassIsShown(EngineCase):
    """Un bilan `locked` ou `error` rendu par le vrai moteur atteint la
    ligne de statut : `summary_line` tait un compte à 0 règle active."""

    def test_a_locked_pass(self):
        self.regle()
        self.imap.recevoir(1)
        rapport = self.session.sync()
        with file_lock(storage.lock_path("perso", self.base), wait=0):
            bilan = self.passe(report=rapport, lock_wait=0.05)
        self.assertEqual((bilan.status, bilan.active_rules), ("locked", 1))
        self.assertIn(t("mail_rules_locked"), engine.summary_line([bilan]))

    def test_an_unreadable_rules_file(self):
        self.regle()
        storage.rules_path("perso", self.base).write_text("{pas du json")
        bilan = self.passe()
        self.assertEqual(bilan.status, "error")
        self.assertGreaterEqual(bilan.active_rules, 1)
        self.assertTrue(bilan.errors)
        self.assertIn(t("mail_rules_error"), engine.summary_line([bilan]))

    def test_rules_disabled_under_the_lock_stay_quiet(self):
        rule = self.regle()
        self.imap.recevoir(1)
        vrai = storage.load
        appels = []

        def charger(name, base=None):
            appels.append(1)
            regles = vrai(name, base)
            if len(appels) > 1:
                for regle in regles:
                    regle.enabled = False
            return regles

        with mock.patch.object(engine.storage, "load", charger):
            bilan = self.passe()
        self.assertEqual((bilan.status, bilan.active_rules), ("no_rules", 0))
        self.assertEqual(rule.id, vrai("perso", self.base)[0].id)


class TestEngineStateDone(EngineCase):
    def test_round_trip_and_refusal(self):
        etat = storage.EngineState(cursor=3, done=[7, 5])
        storage.save_state("perso", etat, base=self.base)
        self.assertEqual(self.etat().done, [5, 7])
        storage.state_path("perso", self.base).write_text(
            '{"version": 1, "done": ["5"]}'
        )
        with self.assertRaises(engine.RuleError):
            self.etat()


class TestSummaryLine(unittest.TestCase):
    def test_a_quiet_account_says_nothing(self):
        rapport = engine.EngineReport(account="perso", active_rules=1)
        self.assertEqual(engine.summary_line([rapport]), "")

    def test_an_account_without_rules_says_nothing_even_on_error(self):
        rapport = engine.EngineReport(account="perso", status="error")
        self.assertEqual(engine.summary_line([rapport]), "")

    def test_accounts_are_separated(self):
        un = engine.EngineReport(account="un", active_rules=1, sent=2)
        deux = engine.EngineReport(
            account="deux", active_rules=1, held=1, status="locked"
        )
        ligne = engine.summary_line([un, deux])
        self.assertIn(f"un : {t('mail_rules_status_sent')} 2", ligne)
        self.assertIn(" · ", ligne)
        self.assertIn(t("mail_rules_locked"), ligne)
        self.assertIn(f"{t('mail_rules_status_held')} 1", ligne)


class TestNeverRaises(unittest.TestCase):
    def test_a_session_without_store_is_without_rules(self):
        session = SimpleNamespace(account=SimpleNamespace(name="x"))
        self.assertEqual(engine.run_pass(session).status, "no_rules")

    def test_an_unexpected_failure_is_an_error_status(self):
        store = mock.MagicMock()
        store.mode = "clear"
        store.root = "/nonexistent-root/perso"
        session = SimpleNamespace(
            account=SimpleNamespace(name="perso"), store=store
        )
        with mock.patch.object(
            engine.storage, "rules_exist", side_effect=OSError("boom")
        ):
            bilan = engine.run_pass(session)
        self.assertEqual(bilan.status, "error")
        self.assertTrue(bilan.errors)


if __name__ == "__main__":
    unittest.main()
