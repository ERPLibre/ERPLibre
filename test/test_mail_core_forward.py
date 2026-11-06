#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le transfert du noyau, sans le client : message construit selon le
mode, `Reply-To` d'un transfert, premier identifiant d'un en-tête
d'enfilage.

N'importe que la bibliothèque standard et `erplibre_mail_core` : tourne
aussi sous le Python du venv d'Odoo.
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core import smtp  # noqa: E402
from erplibre_mail_core.rules import forward, model  # noqa: E402

OWN = "boite.regles@example.org"
BRUNO = "bruno.filtre@example.net"
FRED = "fred.transfert@example.net"
GINA = "gina.copie@example.com"
AUTRE = "relais.auto@example.com"

ORIGINAL = (
    f"From: Bruno <{BRUNO}>\r\n"
    f"To: {OWN}\r\n"
    "Bcc: cache.copie@example.org\r\n"
    "Subject: Commande\r\n"
    "Message-ID: <orig.1@example.net>\r\n"
    "Date: Mon, 02 Nov 2026 10:00:00 +0000\r\n"
    "\r\n"
    "Bonjour.\r\n"
).encode()


class Compte:
    """Le compte que lisent les constructeurs SMTP, par duck typing."""

    email = OWN

    def from_header(self) -> str:
        return f"Boîte <{OWN}>"


def vue(frm=f"Bruno <{BRUNO}>", reply_to=None):
    extra = {} if reply_to is None else {"reply-to": reply_to}
    return model.MessageView(
        1, 1, 0, "<orig.1@example.net>", frm, OWN, "", "s", extra=extra
    )


def options(mode):
    return model.ForwardOptions(
        targets=(FRED, GINA), mode=mode, skip_lists=False
    )


class TestForwardMessage(unittest.TestCase):
    def test_forward_message_inline_attachment_redirect(self):
        """Les trois modes : un message adressé aux destinations en Cci
        interne (dans le corps, en pièce jointe), ou des octets d'origine
        remis à une enveloppe (vraie redirection)."""
        cibles = [FRED, GINA]
        for mode in ("inline", "attachment"):
            with self.subTest(mode=mode):
                msg = forward.forward_message(
                    Compte(), options(mode), ORIGINAL, cibles, intro="Voici."
                )
                self.assertNotIsInstance(msg, smtp.RawOutgoing)
                self.assertEqual(smtp.recipients(msg), cibles)
                self.assertNotIn(b"X-ERPLibre-Bcc", smtp.outgoing_bytes(msg))
                self.assertIn(OWN, msg["From"])
        msg = forward.forward_message(
            Compte(), options("attachment"), ORIGINAL, cibles
        )
        parts = [p.get_content_type() for p in msg.walk()]
        self.assertIn("message/rfc822", parts)
        redirect = forward.forward_message(
            Compte(), options("redirect"), ORIGINAL, cibles, intro="ignorée"
        )
        self.assertIsInstance(redirect, smtp.RawOutgoing)
        self.assertEqual(list(redirect.envelope), cibles)
        octets = smtp.outgoing_bytes(redirect)
        self.assertTrue(octets.startswith(b"Resent-"))
        self.assertIn(b"Message-ID: <orig.1@example.net>", octets)
        self.assertNotIn(b"cache.copie@example.org", octets)
        self.assertNotIn(b"ignor", octets)


class TestReplyTo(unittest.TestCase):
    def test_forward_reply_to_keeps_reply_to_minus_own_addresses(self):
        """Le premier `Reply-To` moins nos adresses, sans doublon ; à
        défaut l'adresse de From ; « » si From est refusé aussi."""
        texte = f"Bruno <{BRUNO}>, {OWN}, {AUTRE}, {BRUNO.upper()}, {GINA}"
        self.assertEqual(
            forward.forward_reply_to(
                vue(reply_to=texte + "\nzeta.second@example.org"),
                frozenset({OWN}),
                frozenset({AUTRE}),
            ),
            f"{BRUNO}, {GINA}",
        )
        self.assertEqual(
            forward.forward_reply_to(
                vue(reply_to=OWN), frozenset({OWN}), frozenset()
            ),
            BRUNO,
        )
        self.assertEqual(
            forward.forward_reply_to(
                vue(frm="Sans adresse"), frozenset(), frozenset()
            ),
            "",
        )


class TestFirstMsgid(unittest.TestCase):
    def test_first_msgid_takes_the_first_token(self):
        """Le premier identifiant d'un en-tête d'enfilage ; « » sans
        identifiant."""
        self.assertEqual(
            forward.first_msgid("<a@example.org> <b@example.net>"),
            "<a@example.org>",
        )
        self.assertEqual(forward.first_msgid(""), "")


if __name__ == "__main__":
    unittest.main()
