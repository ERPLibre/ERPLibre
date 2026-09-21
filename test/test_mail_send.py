#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import email
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import (
    SmtpError,
    build_forward,
    build_message,
    build_reply,
    connect,
    recipients,
    send,
    without_bcc,
)

FIXED_DATE = "Fri, 01 Aug 2026 10:41:00 +0000"
FIXED_MSGID = "<fixe@erplibre>"


def account():
    return account_from_preset(
        "perso", "moi@x.ca", "generic", display_name="Mathieu Benoit"
    )


def original(subject="Devis", frm="Alice <alice@y.ca>", to="moi@x.ca", cc=""):
    raw = (
        f"From: {frm}\r\nTo: {to}\r\n"
        + (f"Cc: {cc}\r\n" if cc else "")
        + f"Subject: {subject}\r\n"
        f"Message-ID: <origine@y.ca>\r\n"
        f"Date: {FIXED_DATE}\r\n\r\nLe corps d'origine.\r\n"
    )
    return email.message_from_string(raw)


class FakeSmtp:
    def __init__(self, fail=False):
        self.sent = []
        self.quit_called = False
        self.fail = fail

    def send_message(self, msg, from_addr, to_addrs):
        if self.fail:
            raise OSError("550 destinataire refusé")
        self.sent.append((msg, from_addr, list(to_addrs)))

    def quit(self):
        self.quit_called = True


class TestBuildMessage(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def build(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_message(self.acc, "alice@y.ca", "Devis", "Bonjour", **kw)

    def test_from_uses_display_name(self):
        self.assertEqual(self.build()["From"], "Mathieu Benoit <moi@x.ca>")

    def test_from_without_display_name(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        msg = build_message(
            acc, "a@example.com", "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )
        self.assertEqual(msg["From"], "moi@x.ca")

    def test_to_and_subject(self):
        msg = self.build()
        self.assertEqual(msg["To"], "alice@y.ca")
        self.assertEqual(msg["Subject"], "Devis")

    def test_body(self):
        self.assertIn("Bonjour", self.build().get_content())

    def test_accented_subject_survives(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "Devis révisé",
            "B",
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        reparsed = email.message_from_bytes(msg.as_bytes())
        from email.header import decode_header

        # RFC 2047 permet d'encoder seulement le segment non-ASCII d'un
        # en-tête ; `decode_header` rend alors PLUSIEURS morceaux
        # ("Devis ", puis "révisé" encodé), qu'il faut tous rejoindre pour
        # retrouver le texte d'origine — ne lire que le premier le tronque.
        text = "".join(
            (
                chunk.decode(charset or "utf-8")
                if isinstance(chunk, bytes)
                else chunk
            )
            for chunk, charset in decode_header(reparsed["Subject"])
        )
        self.assertEqual(text, "Devis révisé")

    def test_multiple_recipients(self):
        msg = self.build(cc=["bob@y.ca", "carl@y.ca"])
        self.assertEqual(msg["Cc"], "bob@y.ca, carl@y.ca")

    def test_bcc_is_not_in_headers(self):
        """Un Cci qui part dans les en-têtes n'est plus un Cci."""
        msg = self.build(bcc=["secret@y.ca"])
        self.assertIsNone(msg["Bcc"])

    def test_bcc_is_still_a_recipient(self):
        msg = self.build(bcc=["secret@y.ca"])
        self.assertIn("secret@y.ca", recipients(msg))

    def test_message_id_present(self):
        self.assertEqual(self.build()["Message-ID"], FIXED_MSGID)

    def test_generated_message_id_when_absent(self):
        msg = build_message(
            self.acc, "a@example.com", "S", "B", date=FIXED_DATE
        )
        self.assertTrue(msg["Message-ID"].startswith("<"))

    def test_empty_recipient_raises(self):
        with self.assertRaises(SmtpError):
            build_message(self.acc, "", "S", "B")


class TestAttachments(unittest.TestCase):
    def setUp(self):
        self.acc = account()
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.tmp.name) / "devis.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 faux")

    def tearDown(self):
        self.tmp.cleanup()

    def test_message_becomes_multipart(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            attachments=[self.pdf],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertTrue(msg.is_multipart())

    def test_filename_is_kept(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            attachments=[self.pdf],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ["devis.pdf"])

    def test_content_type_is_guessed(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            attachments=[self.pdf],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        part = next(msg.iter_attachments())
        self.assertEqual(part.get_content_type(), "application/pdf")

    def test_unknown_extension_falls_back_to_octet_stream(self):
        blob = Path(self.tmp.name) / "donnees.zzz"
        blob.write_bytes(b"\x00\x01")
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            attachments=[blob],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        part = next(msg.iter_attachments())
        self.assertEqual(part.get_content_type(), "application/octet-stream")

    def test_missing_file_raises(self):
        with self.assertRaises(SmtpError):
            build_message(
                self.acc,
                "a@example.com",
                "S",
                "B",
                attachments=[Path(self.tmp.name) / "absent.pdf"],
                date=FIXED_DATE,
                msgid=FIXED_MSGID,
            )

    def test_body_still_readable(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "Bonjour Alice",
            attachments=[self.pdf],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertIn("Bonjour Alice", msg.get_body(("plain",)).get_content())


class TestReply(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def reply(self, orig=None, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_reply(self.acc, orig or original(), "Ma réponse", **kw)

    def test_subject_gets_re_prefix(self):
        self.assertEqual(self.reply()["Subject"], "Re: Devis")

    def test_subject_not_prefixed_twice(self):
        self.assertEqual(
            self.reply(original(subject="Re: Devis"))["Subject"], "Re: Devis"
        )

    def test_existing_re_case_insensitive(self):
        self.assertEqual(
            self.reply(original(subject="RE: Devis"))["Subject"], "RE: Devis"
        )

    def test_recipient_is_the_sender(self):
        self.assertEqual(self.reply()["To"], "Alice <alice@y.ca>")

    def test_reply_to_header_wins(self):
        orig = original()
        orig["Reply-To"] = "equipe@y.ca"
        self.assertEqual(self.reply(orig)["To"], "equipe@y.ca")

    def test_in_reply_to(self):
        self.assertEqual(self.reply()["In-Reply-To"], "<origine@y.ca>")

    def test_references_starts_the_chain(self):
        self.assertEqual(self.reply()["References"], "<origine@y.ca>")

    def test_references_extends_the_chain(self):
        orig = original()
        orig["References"] = "<premier@y.ca> <second@y.ca>"
        self.assertEqual(
            self.reply(orig)["References"],
            "<premier@y.ca> <second@y.ca> <origine@y.ca>",
        )

    def test_reply_all_adds_the_others(self):
        orig = original(to="moi@x.ca, bob@y.ca", cc="carl@y.ca")
        msg = self.reply(orig, reply_all=True)
        joined = f"{msg['To']} {msg['Cc']}"
        self.assertIn("bob@y.ca", joined)
        self.assertIn("carl@y.ca", joined)

    def test_reply_all_drops_my_own_address(self):
        orig = original(to="moi@x.ca, bob@y.ca")
        msg = self.reply(orig, reply_all=True)
        self.assertNotIn("moi@x.ca", f"{msg['To']} {msg['Cc'] or ''}")

    def test_original_is_quoted(self):
        self.assertIn("> Le corps d'origine.", self.reply().get_content())

    def test_survives_an_unrecognised_charset(self):
        """Un charset mal étiqueté ne doit pas faire tomber la réponse.

        `str.decode(charset, "replace")` lève `LookupError` si le codec est
        inconnu : l'erreur survient à la recherche du codec, AVANT que
        `errors="replace"` ne serve. Un seul message mal étiqueté ne doit
        pas empêcher d'y répondre.
        """
        raw = (
            "From: Alice <alice@y.ca>\r\nTo: moi@x.ca\r\n"
            "Subject: Devis\r\nMessage-ID: <origine@y.ca>\r\n"
            f"Date: {FIXED_DATE}\r\n"
            "Content-Type: text/plain; charset=bogus-charset-xyz\r\n\r\n"
            "Le corps d'origine.\r\n"
        )
        orig = email.message_from_string(raw)
        msg = self.reply(orig)
        self.assertIn("Le corps d'origine.", msg.get_content())

    def test_survives_unknown_8bit(self):
        """Étiquette réelle observée en usage, pas seulement un charset
        inventé (voir `script/todo/mail/charset.py`)."""
        raw = (
            "From: Alice <alice@y.ca>\r\nTo: moi@x.ca\r\n"
            "Subject: Devis\r\nMessage-ID: <origine@y.ca>\r\n"
            f"Date: {FIXED_DATE}\r\n"
            "Content-Type: text/plain; charset=unknown-8bit\r\n\r\n"
            "Le corps d'origine.\r\n"
        )
        orig = email.message_from_string(raw)
        msg = self.reply(orig)
        self.assertIn("Le corps d'origine.", msg.get_content())


class TestForward(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def forward(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_forward(
            self.acc, original(), "bob@z.ca", "Pour info", **kw
        )

    def test_subject_gets_fwd_prefix(self):
        self.assertEqual(self.forward()["Subject"], "Fwd: Devis")

    def test_recipient(self):
        self.assertEqual(self.forward()["To"], "bob@z.ca")

    def test_original_attached_as_rfc822(self):
        types = [
            p.get_content_type() for p in self.forward().iter_attachments()
        ]
        self.assertIn("message/rfc822", types)

    def test_no_in_reply_to(self):
        """Transférer n'est pas répondre : le fil ne doit pas se greffer."""
        self.assertIsNone(self.forward()["In-Reply-To"])


class TestRecipients(unittest.TestCase):
    def test_collects_to_cc_and_bcc(self):
        msg = build_message(
            account(),
            "a@example.com",
            "S",
            "B",
            cc=["b@example.com"],
            bcc=["c@y.ca"],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertEqual(
            sorted(recipients(msg)),
            ["a@example.com", "b@example.com", "c@y.ca"],
        )

    def test_strips_display_names(self):
        msg = build_message(
            account(),
            "Alice <a@example.com>",
            "S",
            "B",
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertEqual(recipients(msg), ["a@example.com"])

    def test_deduplicates(self):
        msg = build_message(
            account(),
            "a@example.com",
            "S",
            "B",
            cc=["a@example.com"],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertEqual(recipients(msg), ["a@example.com"])


class TestSend(unittest.TestCase):
    def setUp(self):
        self.acc = account()
        self.msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            bcc=["c@y.ca"],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )

    def test_passes_envelope_from_and_recipients(self):
        smtp = FakeSmtp()
        served = send(self.acc, self.msg, smtp)
        _, from_addr, to_addrs = smtp.sent[0]
        self.assertEqual(from_addr, "moi@x.ca")
        self.assertEqual(sorted(to_addrs), ["a@example.com", "c@y.ca"])
        self.assertEqual(sorted(served), ["a@example.com", "c@y.ca"])

    def test_failure_is_wrapped(self):
        with self.assertRaises(SmtpError):
            send(self.acc, self.msg, FakeSmtp(fail=True))

    def test_failure_message_keeps_the_server_wording(self):
        with self.assertRaises(SmtpError) as ctx:
            send(self.acc, self.msg, FakeSmtp(fail=True))
        self.assertIn("550", str(ctx.exception))

    def test_no_recipient_raises_before_the_network(self):
        msg = build_message(
            self.acc,
            "a@example.com",
            "S",
            "B",
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        del msg["To"]
        smtp = FakeSmtp()
        with self.assertRaises(SmtpError):
            send(self.acc, msg, smtp)
        self.assertEqual(smtp.sent, [])


class TestWithoutBcc(unittest.TestCase):
    """La copie qui part vers Envoyés emprunte IMAP, pas SMTP : elle doit
    être assainie elle aussi, sinon le Cci est lisible sur le serveur."""

    def setUp(self):
        self.msg = build_message(
            account(),
            "a@example.com",
            "Devis",
            "Bonjour",
            bcc=["secret@y.ca"],
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )

    def test_copy_has_no_internal_bcc_header(self):
        self.assertIsNone(without_bcc(self.msg)["X-ERPLibre-Bcc"])

    def test_bcc_address_is_absent_from_the_serialised_copy(self):
        self.assertNotIn(b"secret@y.ca", without_bcc(self.msg).as_bytes())

    def test_original_is_left_untouched(self):
        without_bcc(self.msg)
        self.assertIn("secret@y.ca", recipients(self.msg))

    def test_message_without_bcc_is_returned_as_is(self):
        plain = build_message(
            account(),
            "a@example.com",
            "S",
            "B",
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertIs(without_bcc(plain), plain)

    def test_body_and_headers_survive(self):
        copy = without_bcc(self.msg)
        self.assertEqual(copy["Subject"], "Devis")
        self.assertIn("Bonjour", copy.get_content())


class TestConnect(unittest.TestCase):
    """`connect` choisit la branche SSL/STARTTLS et convertit les erreurs.

    Aucun de ces tests ne joint le réseau : `smtplib` est remplacé.
    """

    def _account(self, security):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        acc.smtp.host = "smtp.x.ca"
        acc.smtp.port = 465 if security == "ssl" else 587
        acc.smtp.security = security
        return acc

    def test_ssl_branch(self):
        client = MagicMock()
        with patch("smtplib.SMTP_SSL", return_value=client) as ctor:
            connect(self._account("ssl"), "hunter2")
        ctor.assert_called_once_with("smtp.x.ca", 465, timeout=30)
        client.login.assert_called_once_with("moi@x.ca", "hunter2")

    def test_starttls_branch_upgrades(self):
        client = MagicMock()
        with patch("smtplib.SMTP", return_value=client):
            connect(self._account("starttls"), "hunter2")
        client.starttls.assert_called_once()

    def test_plain_branch_does_not_upgrade(self):
        client = MagicMock()
        with patch("smtplib.SMTP", return_value=client):
            connect(self._account("none"), "hunter2")
        client.starttls.assert_not_called()

    def test_login_failure_becomes_an_smtp_error(self):
        client = MagicMock()
        client.login.side_effect = OSError("535 refus")
        with patch("smtplib.SMTP_SSL", return_value=client):
            with self.assertRaises(SmtpError) as ctx:
                connect(self._account("ssl"), "mauvais")
        self.assertIn("535", str(ctx.exception))

    def test_connection_failure_becomes_an_smtp_error(self):
        with patch("smtplib.SMTP_SSL", side_effect=OSError("injoignable")):
            with self.assertRaises(SmtpError):
                connect(self._account("ssl"), "hunter2")


if __name__ == "__main__":
    unittest.main()
