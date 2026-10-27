#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une règle de réponse, de bout en bout, sur un vrai IMAP et un vrai SMTP.

La boîte de réception reçoit un message ordinaire, un message de liste et
une réponse automatique. Seul le premier reçoit une réponse : un message
SMTP, adressé à l'expéditeur, conforme à la RFC 3834, HTML avec son image
en ligne, copié dans Envoyés. Le corps lu par la règle descend par
BODY.PEEK : l'original reste non lu. Une seconde passe n'envoie rien.

Les INTERNALDATE sont posées explicitement, après l'armement et près de
l'horloge injectée : la date fixe du bac à sable rendrait les messages
antérieurs à l'armement ou trop vieux.
"""

import calendar
import tempfile
import unittest
from pathlib import Path

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import PASSWORD, MailSandboxCase, sandbox_account

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
LISTE = "liste-annonces@example.net"
REPONDEUR = "service.repondeur@example.com"
RECU = calendar.timegm((2026, 10, 27, 10, 0, 0))
RECU_IMAP = b"27-Oct-2026 10:00:00 +0000"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def brut(frm, uid, *entetes):
    lignes = [
        f"From: {frm}",
        f"To: {OWN}",
        f"Subject: Question {uid}",
        f"Message-ID: <{uid}@example.net>",
        *entetes,
        "",
        "Bonjour, une question.",
        "",
    ]
    return "\r\n".join(lignes).encode()


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestReplyRuleEndToEnd(MailSandboxCase):
    def setUp(self):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import (
            Armed,
            Condition,
            Group,
            new_rule,
        )
        from script.todo.mail.tui import Session

        self.imap = self.imap_server()
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.sent = self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        self.inbox.deliver(
            brut(f"Carole <{CAROLE}>", 1), uid=1, internal_date=RECU_IMAP
        )
        self.inbox.deliver(
            brut(LISTE, 2, "List-Id: <annonces.example.net>"),
            uid=2,
            internal_date=RECU_IMAP,
        )
        self.inbox.deliver(
            brut(REPONDEUR, 3, "Auto-Submitted: auto-replied"),
            uid=3,
            internal_date=RECU_IMAP,
        )
        self.account = sandbox_account(
            imap_port=self.imap.port,
            smtp_port=self.smtp.port,
            name="perso",
            address=OWN,
        )
        self.store = self.temp_store(self.account)
        self.base = Path(self.store.root).parent
        transport = imap_transport.connect(self.account, PASSWORD)
        self.addCleanup(transport.logout)
        self.session = Session(
            self.account,
            self.store,
            Syncer(self.store, transport),
            password=PASSWORD,
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logo = Path(tmp.name) / "logo.png"
        logo.write_bytes(PNG)
        ref = storage.import_media("perso", logo, base=self.base)
        rule = new_rule("reply", "Absence")
        rule.action.format = "html"
        rule.action.body = '<p>Je suis absente.</p><img src="logo.png">'
        rule.action.images = [ref]
        rule.filter = Group("all", [Condition("body", "bonjour")])
        storage.upsert_rule(
            "perso", rule, rearm=Armed(42, 1, RECU - 3600), base=self.base
        )
        self.store.rule_log_claim(
            rule.id,
            "pre-approuvee",
            outcome="sent",
            at=RECU - 30 * 86400,
            fingerprint=rule.fingerprint(),
        )

    def passe(self):
        from script.todo.mail.rules import engine

        return engine.run_pass(
            self.session,
            report=self.session.sync(),
            all_accounts=[],
            now=lambda: RECU + 600,
        )

    def test_one_reply_reaches_the_sender_and_is_filed(self):
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(bilan.skipped["list"], 1)
        self.assertEqual(bilan.skipped["auto_submitted"], 1)
        self.assertEqual(len(self.smtp.messages), 1)
        sorti = self.smtp.messages[0]
        self.assertEqual(sorti.rcpt_tos, [CAROLE])
        self.assertEqual(sorti.mail_from, OWN)
        entetes = sorti.headers()
        self.assertEqual(entetes["Auto-Submitted"], "auto-replied")
        self.assertEqual(entetes["X-Auto-Response-Suppress"], "All")
        self.assertIn("erplibre-rules", entetes["X-Loop"])
        self.assertEqual(entetes["In-Reply-To"], "<1@example.net>")
        types = [part.get_content_type() for part in entetes.walk()]
        self.assertIn("multipart/related", types)
        self.assertIn("image/png", types)
        self.assertEqual(len(self.sent.appended), 1)

    def test_the_originals_stay_unread(self):
        self.passe()
        # Le corps a bien été lu par la règle : il est en cache.
        self.assertIsNotNone(self.store.read_body("INBOX", 1))
        for message in self.inbox.messages:
            self.assertNotIn("\\Seen", message.flags)

    def test_a_second_pass_sends_nothing(self):
        self.passe()
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(len(self.smtp.messages), 1)


if __name__ == "__main__":
    unittest.main()
