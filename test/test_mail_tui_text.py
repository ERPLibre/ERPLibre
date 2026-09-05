#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import unittest

from script.todo.mail.store import MessageMeta
from script.todo.mail.tui_text import (
    extract_body,
    filter_messages,
    format_date,
    format_date_full,
    format_size,
    html_to_text,
    is_unread,
    short_addr,
    truncate,
)

# 2026-08-01 10:41:00 UTC
NOW = 1785580860


def meta(
    uid=1, subject="Devis", frm="Alice <alice@y.ca>", snippet="", flags=""
):
    return MessageMeta(
        uid=uid,
        date=NOW,
        size=100,
        flags=flags,
        msgid=f"<{uid}@x.ca>",
        frm=frm,
        to="moi@x.ca",
        subject=subject,
        snippet=snippet,
    )


class TestHtmlToText(unittest.TestCase):
    def test_strips_tags(self):
        self.assertEqual(html_to_text("<p>Bonjour</p>"), "Bonjour")

    def test_decodes_entities(self):
        self.assertEqual(
            html_to_text("<p>caf&eacute; &amp; th&eacute;</p>"), "café & thé"
        )

    def test_drops_script_and_style(self):
        out = html_to_text(
            "<style>p{color:red}</style><script>alert(1)</script><p>Salut</p>"
        )
        self.assertEqual(out, "Salut")

    def test_br_becomes_newline(self):
        self.assertEqual(html_to_text("a<br>b"), "a\nb")

    def test_block_tags_separate_lines(self):
        self.assertIn("\n", html_to_text("<div>a</div><div>b</div>"))

    def test_collapses_blank_runs(self):
        self.assertNotIn("\n\n\n", html_to_text("<p>a</p>\n\n\n\n\n<p>b</p>"))

    def test_empty_input(self):
        self.assertEqual(html_to_text(""), "")


class TestExtractBody(unittest.TestCase):
    def test_plain_text(self):
        text, atts = extract_body(b"Subject: S\r\n\r\nBonjour Alice")
        self.assertEqual(text.strip(), "Bonjour Alice")
        self.assertEqual(atts, [])

    def test_prefers_plain_over_html(self):
        raw = (
            b'Content-Type: multipart/alternative; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\nversion texte\r\n"
            b"--B\r\nContent-Type: text/html\r\n\r\n<p>version html</p>\r\n"
            b"--B--\r\n"
        )
        text, _ = extract_body(raw)
        self.assertIn("version texte", text)
        self.assertNotIn("html", text)

    def test_falls_back_to_html(self):
        raw = b"Content-Type: text/html\r\n\r\n<p>Bonjour <b>Alice</b></p>"
        text, _ = extract_body(raw)
        self.assertEqual(text.strip(), "Bonjour Alice")

    def test_lists_attachments(self):
        raw = (
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
            b"--B\r\nContent-Type: application/pdf\r\n"
            b'Content-Disposition: attachment; filename="devis.pdf"\r\n\r\n'
            b"%PDF\r\n--B--\r\n"
        )
        _, atts = extract_body(raw)
        self.assertEqual([a.filename for a in atts], ["devis.pdf"])
        self.assertEqual(atts[0].content_type, "application/pdf")

    def test_attachment_without_filename_gets_one(self):
        raw = (
            b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
            b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
            b"--B\r\nContent-Type: application/pdf\r\n"
            b"Content-Disposition: attachment\r\n\r\n%PDF\r\n--B--\r\n"
        )
        _, atts = extract_body(raw)
        self.assertTrue(atts[0].filename)

    def test_broken_message_does_not_raise(self):
        text, atts = extract_body(b"\x00\x01\x02 pas un courriel")
        self.assertIsInstance(text, str)
        self.assertIsInstance(atts, list)

    def test_decodes_charset(self):
        raw = (
            b"Content-Type: text/plain; charset=iso-8859-1\r\n"
            b"Content-Transfer-Encoding: 8bit\r\n\r\nCaf\xe9"
        )
        text, _ = extract_body(raw)
        self.assertIn("Café", text)

    def test_survives_unknown_8bit(self):
        """Étiquette réelle observée en usage, pas seulement un charset
        inventé (voir `script/todo/mail/charset.py`)."""
        raw = (
            b"Content-Type: text/plain; charset=unknown-8bit\r\n\r\n"
            b"Bonjour"
        )
        text, _ = extract_body(raw)
        self.assertIn("Bonjour", text)


class TestShortAddr(unittest.TestCase):
    def test_display_name_wins(self):
        self.assertEqual(
            short_addr("Alice Tremblay <a@example.com>"), "Alice Tremblay"
        )

    def test_bare_address(self):
        self.assertEqual(short_addr("a@example.com"), "a@example.com")

    def test_quoted_display_name(self):
        self.assertEqual(
            short_addr('"Tremblay, Alice" <a@example.com>'), "Tremblay, Alice"
        )

    def test_empty(self):
        self.assertEqual(short_addr(""), "")

    def test_first_of_several(self):
        self.assertEqual(
            short_addr("a@example.com, b@example.com"), "a@example.com"
        )


class TestTruncate(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate("abc", 10), "abc")

    def test_long_text_gets_ellipsis(self):
        self.assertEqual(truncate("abcdefghij", 5), "abcd…")

    def test_result_never_exceeds_width(self):
        self.assertEqual(len(truncate("abcdefghij", 5)), 5)

    def test_width_of_one(self):
        self.assertEqual(truncate("abcdef", 1), "…")

    def test_zero_width(self):
        self.assertEqual(truncate("abc", 0), "")


class TestFormatDate(unittest.TestCase):
    def test_today_shows_time(self):
        self.assertRegex(format_date(NOW, NOW), r"^\d{2}:\d{2}$")

    def test_this_year_shows_day_and_month(self):
        self.assertRegex(format_date(NOW - 90 * 86400, NOW), r"^\d{2}-\d{2}$")

    def test_older_shows_the_year(self):
        self.assertRegex(
            format_date(NOW - 800 * 86400, NOW), r"^\d{4}-\d{2}-\d{2}$"
        )

    def test_zero_is_blank(self):
        self.assertEqual(format_date(0, NOW), "")

    def test_absurd_epoch_is_blank_and_does_not_raise(self):
        """Le contrat du module : une date d'en-tête aberrante ne lève jamais."""
        for hostile in (10**18, 2**63, -(10**18)):
            self.assertEqual(format_date(hostile, NOW), "")


class TestFormatDateFull(unittest.TestCase):
    """`format_date` reste volontairement compact pour la liste ; l'aperçu
    d'un message a besoin de la date COMPLÈTE, sans ambiguïté à elle seule.

    Ne réutilise pas `format_date` : sa compacité est une propriété
    voulue de la colonne, pas un raccourci disponible ailleurs.
    """

    def test_known_epoch_renders_in_full(self):
        # Calculé de la même façon que l'implémentation (heure locale) :
        # un `assertEqual` sur une chaîne littérale dépendrait du fuseau
        # horaire de la machine qui exécute le test.
        expected = datetime.datetime.fromtimestamp(NOW).strftime(
            "%Y-%m-%d %H:%M"
        )
        self.assertEqual(format_date_full(NOW), expected)

    def test_zero_is_blank(self):
        self.assertEqual(format_date_full(0), "")

    def test_absurd_epoch_is_blank_and_does_not_raise(self):
        """Mêmes trois valeurs que `test_absurd_epoch_is_blank_and_does_not_raise`
        de `TestFormatDate` : ce sont elles qui ont fait lever `format_date`
        avant l'ajout de sa garde — `format_date_full` doit tenir la même
        promesse."""
        for hostile in (10**18, 2**63, -(10**18)):
            self.assertEqual(format_date_full(hostile), "")


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(512), "512 o")

    def test_kilobytes(self):
        self.assertEqual(format_size(2048), "2.0 ko")

    def test_megabytes(self):
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 Mo")

    def test_zero(self):
        self.assertEqual(format_size(0), "0 o")


class TestIsUnread(unittest.TestCase):
    def test_no_flags_is_unread(self):
        self.assertTrue(is_unread(""))

    def test_seen_is_read(self):
        self.assertFalse(is_unread("\\Seen"))

    def test_seen_among_others(self):
        self.assertFalse(is_unread("\\Answered \\Seen"))

    def test_none_is_unread(self):
        self.assertTrue(is_unread(None))


class TestFilterMessages(unittest.TestCase):
    def setUp(self):
        self.metas = [
            meta(1, subject="Devis révisé", frm="Alice <a@example.com>"),
            meta(
                2,
                subject="CR réunion",
                frm="Bob <b@example.com>",
                snippet="ordre du jour",
            ),
        ]

    def test_empty_query_returns_all(self):
        self.assertEqual(len(filter_messages(self.metas, "")), 2)

    def test_matches_subject(self):
        self.assertEqual(
            [m.uid for m in filter_messages(self.metas, "devis")], [1]
        )

    def test_is_case_insensitive(self):
        self.assertEqual(
            [m.uid for m in filter_messages(self.metas, "DEVIS")], [1]
        )

    def test_matches_sender(self):
        self.assertEqual(
            [m.uid for m in filter_messages(self.metas, "bob")], [2]
        )

    def test_matches_snippet(self):
        self.assertEqual(
            [m.uid for m in filter_messages(self.metas, "ordre")], [2]
        )

    def test_accent_insensitive(self):
        self.assertEqual(
            [m.uid for m in filter_messages(self.metas, "revise")], [1]
        )

    def test_no_match(self):
        self.assertEqual(filter_messages(self.metas, "zzz"), [])


if __name__ == "__main__":
    unittest.main()
