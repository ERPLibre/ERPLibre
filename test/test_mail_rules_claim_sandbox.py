#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Deux machines, une boîte : la revendication de bout en bout.

Chaque « machine » a sa propre base (cache et règles dans un dossier
temporaire distinct) et sa propre connexion au MÊME bac à sable IMAP ; le
SMTP est commun. La même règle (même identifiant, même empreinte) est
enregistrée dans les deux bases, armée avant les messages et
pré-approuvée. Avec et sans CONDSTORE, puis sur un serveur qui refuse les
mots-clés.
"""

import calendar
import unittest
from pathlib import Path
from unittest import mock

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import (
        PASSWORD,
        Interfere,
        MailSandboxCase,
        sandbox_account,
    )

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
BRUNO = "bruno.filtre@example.net"
KEYWORD = "$ErpLibreRule"
RECU = calendar.timegm((2026, 10, 27, 10, 0, 0))
RECU_IMAP = b"27-Oct-2026 10:00:00 +0000"


class Crash(BaseException):
    """Un processus tué : rien ne l'attrape dans le moteur."""


def brut(frm, uid):
    return (
        f"From: {frm}\r\nTo: {OWN}\r\nSubject: Question {uid}\r\n"
        f"Message-ID: <{uid}@example.net>\r\n\r\nBonjour, une question.\r\n"
    ).encode()


class Machine:
    """Une base locale et sa session sur le bac à sable."""

    def __init__(self, case, rule, *, approuvee=True):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.rules import storage
        from script.todo.mail.tui import Session

        self.case = case
        self.account = sandbox_account(
            imap_port=case.imap.port,
            smtp_port=case.smtp.port,
            name="perso",
            address=OWN,
        )
        self.store = case.temp_store(self.account)
        self.base = Path(self.store.root).parent
        transport = imap_transport.connect(self.account, PASSWORD)
        case.addCleanup(transport.logout)
        self.session = Session(
            self.account,
            self.store,
            Syncer(self.store, transport),
            password=PASSWORD,
        )
        storage.upsert_rule("perso", rule, rearm=rule.armed, base=self.base)
        if approuvee:
            self.approuver(rule)

    def approuver(self, rule):
        self.store.rule_log_claim(
            rule.id,
            "pre-approuvee",
            outcome="sent",
            at=RECU - 30 * 86400,
            fingerprint=rule.fingerprint(),
        )

    def passe(self, **kw):
        from script.todo.mail.rules import engine

        return engine.run_pass(
            self.session,
            report=self.session.sync(),
            all_accounts=[],
            now=lambda: RECU + 600,
            **kw,
        )

    def ligne(self, rule, uid=1):
        cle = self.store.message_key(f"<{uid}@example.net>", 42, uid)
        etat = self.store.rule_log_state(rule.id, cle)
        return None if etat is None else (etat["outcome"], etat["reason"])

    def etat(self):
        from script.todo.mail.rules import storage

        return storage.load_state("perso", self.base)


class TwoMachinesCase(MailSandboxCase):
    SANDBOX = {}

    def setUp(self):
        from script.todo.mail.rules.model import Armed, new_rule

        self.imap = self.imap_server(**self.SANDBOX)
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        rule = new_rule("reply", "Absence")
        rule.action.format = "text"
        rule.action.body = "Je suis absente."
        rule.armed = Armed(42, 1, RECU - 3600)
        self.rule = rule
        self.recevoir(1)

    def recevoir(self, uid, frm=CAROLE):
        self.inbox.deliver(brut(frm, uid), uid=uid, internal_date=RECU_IMAP)

    def machines(self, *, a_approuvee=True):
        return (
            Machine(self, self.rule, approuvee=a_approuvee),
            Machine(self, self.rule),
        )

    def drapeaux(self, uid=1):
        return list(self.inbox.by_uid(uid).flags)

    def verifier_une_retenue_retiree(self):
        """A retient sans revendiquer, B (approuvée) répond : la passe
        suivante de A retire son entrée, d'après les drapeaux relus."""
        a, b = self.machines(a_approuvee=False)
        self.assertEqual(a.passe().held, 1)
        self.assertEqual(b.passe().sent, 1)
        self.assertEqual(len(self.smtp.messages), 1)
        bilan = a.passe()
        self.assertEqual(a.store.outbox(), [])
        self.assertEqual(a.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertEqual(len(self.smtp.messages), 1)


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestTwoMachinesWithCondstore(TwoMachinesCase):
    SANDBOX = {"condstore": True}

    def test_only_the_first_machine_replies(self):
        a, b = self.machines()
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.smtp.messages[0].rcpt_tos, [CAROLE])
        self.assertIn(KEYWORD, self.drapeaux())

    def test_the_second_machine_logs_claimed_elsewhere(self):
        a, b = self.machines()
        a.passe()
        bilan = b.passe()
        self.assertEqual(bilan.skipped["claimed_elsewhere"], 1)
        self.assertEqual(b.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(a.store.rule_claim_state(42, 1), "owned")

    def test_a_claim_made_between_probe_and_store_is_lost_by_modified(self):
        a, _b = self.machines()
        self.imap.fail(
            Interfere(
                b"STORE",
                action=lambda: self.inbox.marquer_ailleurs(1, KEYWORD),
            )
        )
        bilan = a.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(a.store.rule_claim_state(42, 1), "lost")
        self.assertEqual(a.ligne(self.rule), ("skipped", "claimed_elsewhere"))
        self.assertEqual(self.smtp.messages, [])

    def test_another_flag_between_probe_and_store_loses_no_reply(self):
        a, _b = self.machines()
        self.imap.fail(
            Interfere(
                b"STORE",
                after=0,
                action=lambda: self.inbox.marquer_ailleurs(1, "\\Seen"),
            )
        )
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(sorted(self.drapeaux()), [KEYWORD, "\\Seen"])

    def test_a_machine_that_crashed_after_claiming_replies_alone(self):
        a, b = self.machines()
        vrai = a.store.mark_auto_sent
        coups = []

        def plante(*args, **kw):
            if not coups:
                coups.append(1)
                raise Crash()
            return vrai(*args, **kw)

        with mock.patch.object(a.store, "mark_auto_sent", plante):
            with self.assertRaises(Crash):
                a.passe()
        self.assertEqual(self.smtp.messages, [])
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_held_reply_is_dropped_once_the_other_machine_replied(self):
        self.verifier_une_retenue_retiree()

    def test_hold_first_on_one_machine_no_longer_makes_the_other_abstain(
        self,
    ):
        a, b = self.machines(a_approuvee=False)
        self.assertEqual(a.passe().held, 1)
        self.assertNotIn(KEYWORD, self.drapeaux())
        bilan = b.passe()
        self.assertEqual(b.ligne(self.rule), ("sent", None))
        self.assertEqual((bilan.sent, len(self.smtp.messages)), (1, 1))
        self.assertIn(KEYWORD, self.drapeaux())

    def test_a_held_reply_carries_no_keyword_on_the_server(self):
        a = Machine(self, self.rule, approuvee=False)
        self.assertEqual(a.passe().held, 1)
        self.assertNotIn(KEYWORD, self.drapeaux())
        self.assertIsNone(a.store.rule_claim_state(42, 1))

    def test_the_engine_state_says_atomic(self):
        a, _b = self.machines()
        self.assertEqual(a.passe().claim_mode, "atomic")
        self.assertEqual(a.etat().claim_mode, "atomic")


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestTwoMachinesCondstoreAfterLogin(TwoMachinesCase):
    SANDBOX = {"condstore": True, "condstore_after_login": True}

    def test_condstore_announced_after_login_still_gives_atomic(self):
        a, b = self.machines()
        self.assertEqual(a.passe().claim_mode, "atomic")
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(len(self.smtp.messages), 1)


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestTwoMachinesWithoutCondstore(TwoMachinesCase):
    def test_sequential_passes_still_reply_once(self):
        a, b = self.machines()
        self.recevoir(2, frm=BRUNO)
        self.assertEqual(b.passe().sent, 2)
        self.assertEqual(a.passe().sent, 0)
        self.assertEqual(b.passe().sent, 0)
        self.assertEqual(len(self.smtp.messages), 2)

    def test_a_held_reply_is_dropped_once_the_other_machine_replied(self):
        self.verifier_une_retenue_retiree()

    def test_the_engine_state_says_plain(self):
        a, _b = self.machines()
        a.passe()
        self.assertEqual(a.etat().claim_mode, "plain")

    def test_a_flag_set_between_probe_and_store_goes_unnoticed(self):
        """La limite que l'écran annonce : sans CONDSTORE, un mot-clé posé
        entre la sonde et le STORE simple n'est pas vu, et la machine se
        croit propriétaire."""
        a, _b = self.machines()
        self.imap.fail(
            Interfere(
                b"STORE",
                action=lambda: self.inbox.marquer_ailleurs(1, KEYWORD),
            )
        )
        self.assertEqual(a.passe().sent, 1)
        self.assertEqual(a.store.rule_claim_state(42, 1), "owned")


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestTwoMachinesWithoutKeywords(TwoMachinesCase):
    SANDBOX = {"permanent_flags": ("\\Seen", "\\Flagged")}

    def test_both_machines_reply_and_the_state_says_none(self):
        from script.todo.todo_i18n import t

        a, b = self.machines()
        premiere = a.passe()
        self.assertEqual(premiere.sent, 1)
        self.assertIn(t("mail_rules_claim_none_warning"), premiere.warnings)
        self.assertEqual(b.passe().sent, 1)
        self.assertEqual(len(self.smtp.messages), 2)
        self.assertEqual(a.etat().claim_mode, "none")
        self.assertEqual(b.etat().claim_mode, "none")
        self.assertNotIn(KEYWORD, self.drapeaux())


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestTrialOnTheSandbox(TwoMachinesCase):
    def test_a_trial_sent_to_oneself_sets_no_keyword(self):
        from script.todo.mail.rules import engine

        a = Machine(self, self.rule)
        rapport = a.session.sync()
        entete = next(h for h in rapport.inbox if h.uid == 1)
        sim = engine.simulate(
            a.session,
            self.rule,
            entete,
            uidvalidity=42,
            body_loader=lambda: "Bonjour, une question.",
            all_accounts=[],
            now=lambda: RECU + 600,
        )
        self.assertEqual(sim.claim, "")
        engine.send_trial(a.session, self.rule, sim)
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.smtp.messages[0].rcpt_tos, [OWN])
        self.assertNotIn(KEYWORD, self.drapeaux())
        self.assertIsNone(a.store.rule_claim_state(42, 1))


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestKeywordInTheCache(TwoMachinesCase):
    def test_the_keyword_reaches_the_cache_but_not_the_unread_and_flagged_marks(
        self,
    ):
        from script.todo.mail.tui_text import is_flagged, is_unread

        a = Machine(self, self.rule)
        a.passe()
        a.session.sync()
        dossier = a.store.folder_state("INBOX")["id"]
        meta = next(m for m in a.store.list_messages(dossier) if m.uid == 1)
        self.assertIn(KEYWORD, meta.flags.split())
        self.assertTrue(is_unread(meta.flags))
        self.assertFalse(is_flagged(meta.flags))


if __name__ == "__main__":
    unittest.main()
