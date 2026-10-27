#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""INTERNALDATE et en-têtes des garde-fous, par un VRAI FETCH.

Les tests de `parse_fetch_headers` décrivent la réponse qu'on croit
recevoir ; ceux-ci la font produire par un serveur IMAP (le bac à sable de
`mail_sandbox.py`) et la lisent par le vrai client. Ce qu'ils couvrent :
l'INTERNALDATE déposée par le serveur revient à la seconde près, jusque dans
le cache, et les en-têtes ajoutés à `HEADER_FIELDS` sont bien demandés et
rendus.

Sans `twisted` ni `aiosmtpd`, tout le fichier se saute proprement.
"""

import calendar
import unittest

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import MailSandboxCase, sandbox_account

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING),
    f"serveurs de test absents ({SANDBOX_MISSING})"
    " : pip install -r requirement/erplibre_require-ments.txt",
)

RECU = b"05-Aug-2026 08:30:15 -0400"
RECU_EPOCH = calendar.timegm((2026, 8, 5, 12, 30, 15))

REPONDEUR = (
    b"From: service.repondeur@example.com\r\n"
    b"To: boite.regles@example.org\r\n"
    b"Cc: bruno.filtre@example.net\r\n"
    b"Subject: Absence du bureau\r\n"
    b"Date: Wed, 05 Aug 2026 12:30:00 +0000\r\n"
    b"Message-ID: <repondeur-1@example.com>\r\n"
    b"Auto-Submitted: auto-replied\r\n"
    b"List-Id: Annonces <liste-annonces.example.net>\r\n"
    b"\r\n"
    b"Je suis absent.\r\n"
)


@requires_servers
class TestInternaldateThroughARealFetch(MailSandboxCase):
    def setUp(self):
        self.imap = self.imap_server()
        self.imap.folder("INBOX").deliver(REPONDEUR, internal_date=RECU)
        self.account = sandbox_account(imap_port=self.imap.port)
        self.store = self.temp_store(self.account)
        self.transport = self.imap_transport(self.imap, self.account)

    def sync(self):
        from script.todo.mail.imap_sync import Syncer

        return Syncer(self.store, self.transport).sync()

    def test_the_internaldate_comes_back_to_the_second(self):
        [entete] = self.sync().inbox
        self.assertEqual(entete.internaldate, RECU_EPOCH)

    def test_the_cache_stores_it_as_received_at(self):
        self.sync()
        fid = self.store.folder_state("INBOX")["id"]
        [message] = self.store.list_messages(fid)
        self.assertEqual(message.received_at, RECU_EPOCH)

    def test_the_rules_headers_are_requested_and_returned(self):
        [entete] = self.sync().inbox
        self.assertEqual(entete.extra.get("auto-submitted"), "auto-replied")
        self.assertEqual(
            entete.extra.get("list-id"),
            "Annonces <liste-annonces.example.net>",
        )
        self.assertNotIn("x-loop", entete.extra)

    def test_cc_is_returned(self):
        [entete] = self.sync().inbox
        self.assertEqual(entete.cc, "bruno.filtre@example.net")

    def test_the_report_names_the_inbox(self):
        self.assertEqual(self.sync().inbox_folder, "INBOX")


if __name__ == "__main__":
    unittest.main()
