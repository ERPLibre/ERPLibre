#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le noyau lit d'IMAP et la revendication sur une connexion
`imaplib` nue, sans le transport du client.

N'importe que la bibliothèque standard et `erplibre_mail_core`.
"""

import calendar
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core import imap  # noqa: E402
from erplibre_mail_core.claim import ClaimProbe  # noqa: E402

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"


class ClientDouble:
    """Un client `imaplib` réduit : chaque `uid()` rend la réponse suivante
    de `reponses` et note la commande."""

    def __init__(self, reponses=(), capacites=b"IMAP4rev1"):
        self.reponses = list(reponses)
        self.capacites = capacites
        self.capabilities = ("IMAP4REV1",)
        self.untagged_responses = {}
        self.appels = []

    def select(self, mailbox):
        self.untagged_responses = {"UIDVALIDITY": [b"42"], "UIDNEXT": [b"9"]}
        return "OK", [b"3"]

    def response(self, code):
        return "OK", self.untagged_responses.pop(code, [None])

    def capability(self):
        return "OK", [self.capacites]

    def uid(self, command, *args):
        self.appels.append((command, args))
        reponse = self.reponses.pop(0)
        if isinstance(reponse, BaseException):
            raise reponse
        return reponse


class TestImapConnection(unittest.TestCase):
    def test_claim_on_a_bare_connection(self):
        client = ClientDouble(
            [
                ("OK", [b"1 (UID 1 FLAGS (\\Seen) MODSEQ (7))"]),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen $ErpLibreRule) MODSEQ (8))"]),
            ],
            capacites=b"IMAP4rev1 CONDSTORE",
        )
        connexion = imap.ImapConnection(client)
        sonde = connexion.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "atomic", 7))
        self.assertEqual(connexion.claim_store(1, sonde), "stored")
        commande, args = client.appels[-1]
        self.assertEqual(commande, "STORE")
        self.assertIn("(UNCHANGEDSINCE 7)", args)
        self.assertEqual(args[-2:], ("+FLAGS", "($ErpLibreRule)"))
        self.assertFalse(connexion._sans_condstore)

    def test_select_reads_the_mailbox_numbers(self):
        info = imap.ImapConnection(ClientDouble()).select("INBOX")
        self.assertEqual(
            (info.uidvalidity, info.uidnext, info.exists), (42, 9, 3)
        )


class TestReaders(unittest.TestCase):
    def test_parse_fetch_headers_fills_extra(self):
        brut = (
            f"From: Carole <{CAROLE}>\r\n"
            f"To: {OWN}\r\n"
            "Subject: Question\r\n"
            "Message-ID: <q1@example.org>\r\n"
            "Auto-Submitted: auto-replied\r\n"
            "List-Id: <liste.example.org>\r\n"
            "Precedence: bulk\r\n"
            "Precedence: list\r\n"
            "X-Loop: boucle\r\n\r\n"
        ).encode()
        entetes = imap.parse_fetch_headers(
            [
                (
                    b"1 (UID 12 FLAGS (\\Seen) RFC822.SIZE 900"
                    b' INTERNALDATE "06-Nov-2026 10:00:00 +0000"'
                    b" BODY[HEADER.FIELDS (FROM)] {200}",
                    brut,
                ),
                b")",
            ]
        )
        self.assertEqual(len(entetes), 1)
        entete = entetes[0]
        self.assertIsInstance(entete, imap.HeaderInfo)
        self.assertEqual((entete.uid, entete.size), (12, 900))
        self.assertEqual(
            entete.internaldate, calendar.timegm((2026, 11, 6, 10, 0, 0))
        )
        self.assertEqual(
            entete.extra,
            {
                "auto-submitted": "auto-replied",
                "list-id": "<liste.example.org>",
                "precedence": "bulk\nlist",
                "x-loop": "boucle",
            },
        )
        self.assertEqual(entete.frm_raw, f"Carole <{CAROLE}>")

    def test_extra_headers_names_are_the_guarded_ones(self):
        """Un en-tête que lisent les garde-fous et que le FETCH ne demande
        pas les laisserait tout passer sans rien dire."""
        noms = {nom.lower() for nom in imap.EXTRA_HEADERS}
        for nom in (
            "auto-submitted",
            "precedence",
            "list-id",
            "list-unsubscribe",
            "x-auto-response-suppress",
            "x-loop",
            "authentication-results",
            "x-spam-flag",
            "content-type",
            "resent-from",
            "return-path",
            "reply-to",
        ):
            with self.subTest(nom=nom):
                self.assertIn(nom, noms)
                self.assertIn(nom.upper(), imap.HEADER_FIELDS)

    def test_xoauth2_chain_format(self):
        self.assertEqual(
            imap.xoauth2_chain(OWN, "jeton"),
            f"user={OWN}\x01auth=Bearer jeton\x01\x01".encode(),
        )


if __name__ == "__main__":
    unittest.main()
