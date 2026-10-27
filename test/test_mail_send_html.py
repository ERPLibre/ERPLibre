#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Envoi HTML, images en ligne, en-têtes libres et réponse automatique.

Couvre les ajouts de `smtp_send` pour le moteur de règles : la structure
MIME produite par `build_message`, les refus de construction, la réponse
automatique RFC 3834 de `build_auto_reply`, le sujet de
`auto_reply_subject`, et le code SMTP que porte désormais `SmtpError`.
"""

import email
import smtplib
import tempfile
import unittest
from email import policy
from pathlib import Path
from unittest.mock import MagicMock, patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import (
    AUTO_SUBJECT_PREFIX,
    AUTO_SUBMITTED_GENERATED,
    AUTO_SUBMITTED_REPLIED,
    FORBIDDEN_EXTRA_HEADERS,
    MAX_MSGID_LEN,
    X_LOOP_MARKER,
    AttachmentPart,
    InlineImage,
    SmtpError,
    auto_reply_subject,
    build_auto_reply,
    build_message,
    connect,
    send,
    smtp_code,
)
from script.todo.todo_i18n import t

FIXED_DATE = "Fri, 01 Aug 2026 10:41:00 +0000"
FIXED_MSGID = "<fixe@regles.example.org>"
OURS = "boite.regles@example.org"
HUMAN = "carole.regle@example.org"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
HTML = '<p>Bonjour</p><img src="cid:logo@regles">'


def account():
    return account_from_preset("perso", OURS, "generic")


def logo(cid="logo@regles"):
    return InlineImage(
        cid=cid, data=PNG, maintype="image", subtype="png", filename="logo.png"
    )


def pdf_part():
    return AttachmentPart(
        data=b"%PDF-1.4 rien",
        maintype="application",
        subtype="pdf",
        filename="tarifs.pdf",
    )


def reread(msg):
    """Le message tel qu'un destinataire le relit, à partir de ses octets."""
    return email.message_from_bytes(msg.as_bytes(), policy=policy.default)


class FailingSmtp:
    """Transport qui lève l'exception donnée à chaque envoi."""

    def __init__(self, exc):
        self.exc = exc

    def send_message(self, msg, from_addr, to_addrs):
        raise self.exc

    def quit(self):
        pass


class TestBuildMessageHtml(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def build(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        return build_message(self.acc, HUMAN, "Devis", "Bonjour", **kw)

    def test_plain_text_only_is_unchanged(self):
        msg = self.build()
        self.assertEqual(msg.get_content_type(), "text/plain")
        self.assertFalse(msg.is_multipart())
        self.assertEqual(msg.get_content(), "Bonjour\n")
        self.assertIsNone(msg["Reply-To"])

    def test_explicit_none_arguments_build_the_same_bytes(self):
        explicit = self.build(
            html=None,
            inline_images=None,
            attachment_parts=None,
            reply_to=None,
            headers=None,
        )
        self.assertEqual(explicit.as_bytes(), self.build().as_bytes())

    def test_html_makes_an_alternative_text_then_html(self):
        msg = self.build(html="<p>Bonjour</p>")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        parts = list(msg.iter_parts())
        self.assertEqual(
            [p.get_content_type() for p in parts], ["text/plain", "text/html"]
        )
        self.assertIn("<p>Bonjour</p>", parts[1].get_content())

    def test_inline_images_make_a_related_part_with_the_content_id(self):
        msg = self.build(html=HTML, inline_images=[logo()])
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        plain, related = list(msg.iter_parts())
        self.assertEqual(plain.get_content_type(), "text/plain")
        self.assertEqual(related.get_content_type(), "multipart/related")
        html_part, image = list(related.iter_parts())
        self.assertEqual(html_part.get_content_type(), "text/html")
        self.assertEqual(image.get_content_type(), "image/png")
        self.assertEqual(image["Content-ID"], "<logo@regles>")
        self.assertEqual(image.get_content_disposition(), "inline")
        self.assertEqual(image.get_filename(), "logo.png")
        self.assertEqual(image.get_content(), PNG)
        self.assertIn("cid:logo@regles", html_part.get_content())

    def test_several_images_share_one_related_part(self):
        msg = self.build(
            html=HTML, inline_images=[logo("un@regles"), logo("deux@regles")]
        )
        related = msg.get_body(("related",))
        cids = [p["Content-ID"] for p in related.iter_parts()][1:]
        self.assertEqual(cids, ["<un@regles>", "<deux@regles>"])

    def test_attachment_parts_wrap_everything_in_a_mixed(self):
        msg = self.build(html="<p>Bonjour</p>", attachment_parts=[pdf_part()])
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        body, piece = list(msg.iter_parts())
        self.assertEqual(body.get_content_type(), "multipart/alternative")
        self.assertEqual(piece.get_content_type(), "application/pdf")
        self.assertEqual(piece.get_filename(), "tarifs.pdf")
        self.assertEqual(piece.get_content_disposition(), "attachment")

    def test_full_structure_nests_alternative_related_and_pieces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("notes")
            msg = self.build(
                html=HTML,
                inline_images=[logo()],
                attachment_parts=[pdf_part()],
                attachments=[path],
            )

        def shape(part):
            if part.is_multipart():
                inner = ", ".join(shape(p) for p in part.iter_parts())
                return f"{part.get_content_type()}[{inner}]"
            return part.get_content_type()

        self.assertEqual(
            shape(msg),
            "multipart/mixed[multipart/alternative[text/plain,"
            " multipart/related[text/html, image/png]],"
            " application/pdf, text/plain]",
        )
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertEqual(names, ["tarifs.pdf", "notes.txt"])

    def test_plain_text_with_attachment_parts_only(self):
        msg = self.build(attachment_parts=[pdf_part()])
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        self.assertEqual(msg.get_body(("plain",)).get_content(), "Bonjour\n")

    def test_reparsed_bytes_give_back_the_html(self):
        msg = self.build(
            html=HTML, inline_images=[logo()], attachment_parts=[pdf_part()]
        )
        again = reread(msg)
        self.assertIn(
            "cid:logo@regles", again.get_body(("html",)).get_content()
        )
        self.assertEqual(
            again.get_body(("plain",)).get_content().strip(), "Bonjour"
        )

    def test_inline_images_without_html_are_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.build(inline_images=[logo()])
        self.assertEqual(str(ctx.exception), t("mail_err_inline_needs_html"))
        self.assertIsNone(ctx.exception.code)

    def test_inline_images_with_empty_html_are_refused(self):
        with self.assertRaises(SmtpError):
            self.build(html="", inline_images=[logo()])

    def test_reply_to_sets_the_header(self):
        msg = self.build(reply_to="bruno.filtre@example.net")
        self.assertEqual(msg["Reply-To"], "bruno.filtre@example.net")

    def test_extra_headers_are_added(self):
        msg = self.build(headers={"X-Regle": "essai", "Auto-Submitted": "no"})
        self.assertEqual(msg["X-Regle"], "essai")
        self.assertEqual(msg["Auto-Submitted"], "no")

    def test_every_reserved_header_is_refused_whatever_its_case(self):
        names = [n.upper() for n in FORBIDDEN_EXTRA_HEADERS] + [
            "Subject",
            "message-id",
            "x-erplibre-bcc",
        ]
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(SmtpError) as ctx:
                    self.build(headers={name: "valeur"})
                self.assertEqual(
                    str(ctx.exception),
                    f"{t('mail_err_header_forbidden')} {name}",
                )

    def test_reserved_bcc_header_cannot_leak_the_hidden_copy(self):
        with self.assertRaises(SmtpError):
            self.build(headers={"Bcc": "denis.tri@example.org"})

    def test_line_break_in_a_header_value_is_refused(self):
        for value in ("a\r\nBcc: denis.tri@example.org", "a\nb", "a\rb"):
            with self.subTest(value=value):
                with self.assertRaises(SmtpError) as ctx:
                    self.build(headers={"X-Regle": value})
                self.assertEqual(
                    str(ctx.exception), t("mail_err_header_newline")
                )

    def test_line_break_in_a_header_name_is_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.build(headers={"X-Regle\r\nBcc": "x"})
        self.assertEqual(str(ctx.exception), t("mail_err_header_newline"))

    def test_header_name_that_is_not_a_field_name_is_refused(self):
        for name in ("To: denis.tri@example.org", "X Regle", "", "X-Règle"):
            with self.subTest(name=name):
                with self.assertRaises(SmtpError):
                    self.build(headers={name: "x"})

    def test_unicode_line_separator_in_a_header_value_is_refused(self):
        # `email` découpe les valeurs avec `str.splitlines`, qui coupe aussi
        # sur ces caractères : sans ce refus, `ValueError` au lieu de
        # `SmtpError`.
        for sep in ("\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\u2029"):
            with self.subTest(sep=repr(sep)):
                with self.assertRaises(SmtpError) as ctx:
                    self.build(headers={"X-Regle": f"a{sep}X-Pirate: 1"})
                self.assertEqual(
                    str(ctx.exception), t("mail_err_header_newline")
                )

    def test_line_break_in_reply_to_is_refused(self):
        for value in (
            "bruno.filtre@example.net\r\nBcc: denis.tri@example.org",
            "bruno.filtre@example.net\u2028X-Pirate: 1",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(SmtpError) as ctx:
                    self.build(reply_to=value)
                self.assertEqual(
                    str(ctx.exception), t("mail_err_header_newline")
                )

    def test_reply_to_header_conflicting_with_reply_to_is_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.build(
                reply_to="bruno.filtre@example.net",
                headers={"reply-to": "denis.tri@example.org"},
            )
        self.assertEqual(
            str(ctx.exception), f"{t('mail_err_header_forbidden')} reply-to"
        )

    def test_reply_to_header_alone_is_accepted(self):
        msg = self.build(headers={"Reply-To": "bruno.filtre@example.net"})
        self.assertEqual(msg["Reply-To"], "bruno.filtre@example.net")

    def test_same_header_twice_whatever_its_case_is_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.build(headers={"Sender": OURS, "sender": HUMAN})
        self.assertEqual(
            str(ctx.exception), f"{t('mail_err_header_forbidden')} sender"
        )

    def test_any_content_header_is_refused(self):
        # `set_content` efface les `Content-*` de la racine : accepté, un
        # tel en-tête disparaîtrait sans erreur.
        for name in ("Content-Language", "content-id", "CONTENT-BASE"):
            with self.subTest(name=name):
                with self.assertRaises(SmtpError) as ctx:
                    self.build(headers={name: "fr", "X-Regle": "1"})
                self.assertEqual(
                    str(ctx.exception),
                    f"{t('mail_err_header_forbidden')} {name}",
                )

    def test_refused_headers_leave_nothing_half_built(self):
        # Le refus arrive avant toute construction : aucune exception de
        # la bibliothèque `email`, seulement `SmtpError`.
        with self.assertRaises(SmtpError):
            self.build(
                html=HTML,
                inline_images=[logo()],
                headers={"X-Regle": "ok", "To": "denis.tri@example.org"},
            )


class TestBuildAutoReply(unittest.TestCase):
    def setUp(self):
        self.acc = account()

    def build(self, **kw):
        kw.setdefault("date", FIXED_DATE)
        kw.setdefault("msgid", FIXED_MSGID)
        kw.setdefault("in_reply_to", "<origine@example.org>")
        kw.setdefault("references", "<debut@example.org>")
        return build_auto_reply(
            self.acc, HUMAN, "Auto: Devis", "Je suis absente.", **kw
        )

    def test_rfc_3834_headers_are_set(self):
        msg = self.build()
        self.assertEqual(msg["Auto-Submitted"], AUTO_SUBMITTED_REPLIED)
        self.assertEqual(msg["Auto-Submitted"], "auto-replied")
        self.assertEqual(msg["X-Auto-Response-Suppress"], "All")
        self.assertEqual(msg["X-Loop"], f"{X_LOOP_MARKER} {OURS}")
        self.assertIn("erplibre-rules", msg["X-Loop"])

    def test_auto_submitted_can_say_generated(self):
        msg = self.build(auto_submitted=AUTO_SUBMITTED_GENERATED)
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")

    def test_addressing_and_subject_are_taken_as_given(self):
        msg = self.build()
        self.assertEqual(msg["To"], HUMAN)
        self.assertEqual(msg["From"], OURS)
        self.assertEqual(msg["Subject"], "Auto: Devis")
        self.assertIsNone(msg["Cc"])
        self.assertIsNone(msg["X-ERPLibre-Bcc"])

    def test_threading_headers_are_chained(self):
        msg = self.build()
        self.assertEqual(msg["In-Reply-To"], "<origine@example.org>")
        self.assertEqual(
            msg["References"], "<debut@example.org> <origine@example.org>"
        )

    def test_without_parent_there_is_no_threading_header(self):
        msg = self.build(in_reply_to="", references="")
        self.assertIsNone(msg["In-Reply-To"])
        self.assertIsNone(msg["References"])

    def test_references_alone_are_kept(self):
        msg = self.build(in_reply_to="")
        self.assertIsNone(msg["In-Reply-To"])
        self.assertEqual(msg["References"], "<debut@example.org>")

    def test_original_is_never_quoted(self):
        msg = self.build()
        text = msg.get_body(("plain",)).get_content()
        self.assertEqual(text, "Je suis absente.\n")
        self.assertFalse(
            any(line.startswith(">") for line in text.splitlines())
        )

    def test_folded_references_are_unfolded_without_value_error(self):
        msg = self.build(
            in_reply_to="<c@d.example>\r\n ",
            references="<a@b.example>\r\n <c@d.example>",
        )
        self.assertEqual(msg["In-Reply-To"], "<c@d.example>")
        self.assertEqual(
            msg["References"], "<a@b.example> <c@d.example> <c@d.example>"
        )
        raw = msg.as_bytes()
        self.assertIn(b"In-Reply-To: <c@d.example>", raw)

    def test_empty_recipient_is_refused(self):
        for to in ("", "   ", None):
            with self.subTest(to=to):
                with self.assertRaises(SmtpError) as ctx:
                    build_auto_reply(
                        self.acc,
                        to,
                        "Auto: Devis",
                        "corps",
                        date=FIXED_DATE,
                        msgid=FIXED_MSGID,
                    )
                self.assertEqual(
                    str(ctx.exception), t("mail_err_message_needs_recipient")
                )

    def test_non_ascii_message_ids_are_dropped(self):
        # Gardés, ils feraient échouer `as_bytes()` bien après la
        # construction, au moment de l'envoi.
        msg = self.build(
            in_reply_to="<é@example.org>",
            references="<debut@example.org> <ü@example.org>",
        )
        self.assertIsNone(msg["In-Reply-To"])
        self.assertEqual(msg["References"], "<debut@example.org>")
        msg.as_bytes()
        msg.as_bytes(policy=policy.SMTP)

    def test_only_non_ascii_ids_give_no_threading_header(self):
        msg = self.build(in_reply_to="<é@example.org>", references="<à@b>")
        self.assertIsNone(msg["In-Reply-To"])
        self.assertIsNone(msg["References"])
        msg.as_bytes()

    def test_unicode_separators_in_message_ids_are_unfolded(self):
        msg = self.build(
            in_reply_to="<c@d.example>\u2028",
            references="<a@b.example>\x85<c@d.example>",
        )
        self.assertEqual(msg["In-Reply-To"], "<c@d.example>")
        self.assertEqual(
            msg["References"], "<a@b.example> <c@d.example> <c@d.example>"
        )

    def test_overlong_message_id_is_dropped(self):
        long_id = "<" + "y" * (MAX_MSGID_LEN + 1) + "@example.org>"
        msg = self.build(
            in_reply_to=long_id, references=f"<debut@example.org> {long_id}"
        )
        self.assertIsNone(msg["In-Reply-To"])
        self.assertEqual(msg["References"], "<debut@example.org>")
        raw = msg.as_bytes(policy=policy.SMTP)
        self.assertLessEqual(max(len(x) for x in raw.split(b"\r\n")), 998)

    def test_message_id_at_the_length_limit_is_kept(self):
        at_limit = "<" + "y" * (MAX_MSGID_LEN - 14) + "@example.org>"
        self.assertEqual(len(at_limit), MAX_MSGID_LEN)
        msg = self.build(in_reply_to=at_limit, references="")
        self.assertEqual(msg["In-Reply-To"], at_limit)

    def test_unicode_separator_in_auto_submitted_is_refused(self):
        with self.assertRaises(SmtpError) as ctx:
            self.build(auto_submitted="auto-replied\u2028X-Pirate: 1")
        self.assertEqual(str(ctx.exception), t("mail_err_header_newline"))

    def test_folded_subject_is_unfolded(self):
        msg = build_auto_reply(
            self.acc,
            HUMAN,
            "Auto: Devis\r\n pour demain",
            "corps",
            date=FIXED_DATE,
            msgid=FIXED_MSGID,
        )
        self.assertEqual(msg["Subject"], "Auto: Devis pour demain")

    def test_html_and_inline_images_pass_through(self):
        msg = self.build(
            html=HTML, inline_images=[logo()], attachment_parts=[pdf_part()]
        )
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        again = reread(msg)
        self.assertIn(
            "cid:logo@regles", again.get_body(("html",)).get_content()
        )
        self.assertEqual(again["Auto-Submitted"], "auto-replied")
        self.assertEqual(again["X-Loop"], f"{X_LOOP_MARKER} {OURS}")

    def test_round_trip_keeps_every_auto_header(self):
        again = reread(self.build())
        self.assertEqual(again["X-Auto-Response-Suppress"], "All")
        self.assertEqual(again["In-Reply-To"], "<origine@example.org>")


class TestAutoReplySubject(unittest.TestCase):
    def test_prefix_is_added(self):
        self.assertEqual(auto_reply_subject("Devis"), "Auto: Devis")
        self.assertTrue(
            auto_reply_subject("x").startswith(AUTO_SUBJECT_PREFIX)
        )

    def test_existing_prefix_is_not_doubled_whatever_its_case(self):
        self.assertEqual(auto_reply_subject("Auto: Devis"), "Auto: Devis")
        self.assertEqual(auto_reply_subject("AUTO: Devis"), "AUTO: Devis")
        self.assertEqual(auto_reply_subject("auto:Devis"), "auto:Devis")

    def test_empty_subject_gives_the_bare_prefix(self):
        self.assertEqual(auto_reply_subject(""), "Auto:")
        self.assertEqual(auto_reply_subject(None), "Auto:")

    def test_template_replaces_the_subject_variable(self):
        self.assertEqual(
            auto_reply_subject("Devis", "Absente — re: {subject}"),
            "Absente — re: Devis",
        )

    def test_blank_template_falls_back_to_the_prefix(self):
        self.assertEqual(auto_reply_subject("Devis", "   "), "Auto: Devis")
        self.assertEqual(auto_reply_subject("Devis", "\r\n"), "Auto: Devis")

    def test_template_without_variable_is_used_as_is(self):
        self.assertEqual(auto_reply_subject("Devis", "Absente"), "Absente")

    def test_braces_of_a_third_party_subject_have_no_effect(self):
        self.assertEqual(
            auto_reply_subject("{0} {subject} {__class__}", "Re {subject}"),
            "Re {0} {subject} {__class__}",
        )

    def test_other_braces_of_the_template_stay_literal(self):
        self.assertEqual(
            auto_reply_subject("Devis", "{0} {sujet} {subject}"),
            "{0} {sujet} Devis",
        )

    def test_line_breaks_are_removed(self):
        self.assertEqual(
            auto_reply_subject("Devis\r\n pour\ndemain"),
            "Auto: Devis pour demain",
        )
        self.assertEqual(
            auto_reply_subject("Devis", "Re\r\n{subject}"), "Re Devis"
        )


class TestSmtpCode(unittest.TestCase):
    def test_recipients_refused_gives_the_smallest_code(self):
        exc = smtplib.SMTPRecipientsRefused(
            {
                HUMAN: (550, b"5.1.1 inconnu"),
                "bruno.filtre@example.net": (450, b"4.2.0 plus tard"),
            }
        )
        self.assertEqual(smtp_code(exc), 450)

    def test_recipients_all_refused_permanently(self):
        exc = smtplib.SMTPRecipientsRefused(
            {HUMAN: (550, b"inconnu"), "denis.tri@example.org": (553, b"")}
        )
        self.assertEqual(smtp_code(exc), 550)

    def test_recipients_refused_without_codes_gives_none(self):
        self.assertIsNone(smtp_code(smtplib.SMTPRecipientsRefused({})))

    def test_response_exception_gives_its_code(self):
        self.assertEqual(smtp_code(smtplib.SMTPDataError(554, b"rejet")), 554)
        self.assertEqual(
            smtp_code(smtplib.SMTPSenderRefused(553, b"", OURS)), 553
        )

    def test_code_at_the_head_of_the_text(self):
        self.assertEqual(smtp_code(OSError("550 destinataire refusé")), 550)
        self.assertEqual(smtp_code(OSError("  421 occupé")), 421)
        self.assertEqual(smtp_code(OSError("250-ok")), 250)

    def test_no_code_gives_none(self):
        self.assertIsNone(smtp_code(OSError("timed out")))
        self.assertIsNone(smtp_code(OSError("erreur 550 plus loin")))
        self.assertIsNone(smtp_code(OSError("5500 trop long")))
        self.assertIsNone(smtp_code(OSError("650 hors plage")))


class TestSmtpErrorCode(unittest.TestCase):
    def test_permanent_only_for_5xx(self):
        self.assertTrue(SmtpError("x", code=550).permanent)
        self.assertTrue(SmtpError("x", code=599).permanent)
        self.assertFalse(SmtpError("x", code=450).permanent)
        self.assertFalse(SmtpError("x", code=600).permanent)
        self.assertFalse(SmtpError("x").permanent)

    def test_message_and_default_code(self):
        exc = SmtpError("refus")
        self.assertEqual(str(exc), "refus")
        self.assertIsNone(exc.code)
        self.assertEqual(str(SmtpError()), "")

    def _msg(self):
        return build_message(
            account(), HUMAN, "S", "B", date=FIXED_DATE, msgid=FIXED_MSGID
        )

    def _send_failing(self, exc):
        with self.assertRaises(SmtpError) as ctx:
            send(account(), self._msg(), FailingSmtp(exc))
        self.assertIs(ctx.exception.__cause__, exc)
        return ctx.exception

    def test_send_raises_a_permanent_error_on_550(self):
        err = self._send_failing(OSError("550 destinataire refusé"))
        self.assertEqual(err.code, 550)
        self.assertTrue(err.permanent)
        self.assertIn("550 destinataire refusé", str(err))

    def test_send_raises_a_transient_error_on_a_mixed_refusal(self):
        err = self._send_failing(
            smtplib.SMTPRecipientsRefused(
                {HUMAN: (451, b"plus tard"), OURS: (550, b"non")}
            )
        )
        self.assertEqual(err.code, 451)
        self.assertFalse(err.permanent)

    def test_send_raises_a_permanent_error_on_a_data_refusal(self):
        err = self._send_failing(smtplib.SMTPDataError(554, b"rejet"))
        self.assertTrue(err.permanent)

    def test_send_network_failure_has_no_code(self):
        err = self._send_failing(OSError("timed out"))
        self.assertIsNone(err.code)
        self.assertFalse(err.permanent)

    def test_connect_failure_is_never_permanent(self):
        acc = account()
        acc.smtp.host = "smtp.example.org"
        acc.smtp.port = 465
        acc.smtp.security = "ssl"
        client = MagicMock()
        client.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"refus"
        )
        with patch("smtplib.SMTP_SSL", return_value=client):
            with self.assertRaises(SmtpError) as ctx:
                connect(acc, "secret")
        self.assertIsNone(ctx.exception.code)
        self.assertFalse(ctx.exception.permanent)


if __name__ == "__main__":
    unittest.main()
