#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import hashlib
import sys
import unittest
from unittest.mock import patch

from script.todo.mail.rules import markup
from script.todo.mail.rules.markup import (
    content_id,
    image_refs,
    markdown_to_html,
    render_reply,
    rewrite_image_refs,
    wrap_html_document,
)
from script.todo.mail.rules.model import Action, MediaRef, RuleError
from script.todo.mail.smtp_send import AttachmentPart, InlineImage

LOGO = b"\x89PNG logo"
PHOTO = b"\xff\xd8 photo"
LOGO_REF = MediaRef("logo.png", hashlib.sha256(LOGO).hexdigest(), "image/png")
PHOTO_REF = MediaRef(
    "photo.jpg", hashlib.sha256(PHOTO).hexdigest(), "image/jpeg"
)
MEDIA = {"logo.png": LOGO, "photo.jpg": PHOTO}
DOMAIN = "example.org"


class TestMarkdown(unittest.TestCase):
    """Markdown → HTML, sans jamais laisser passer d'HTML brut."""

    def test_heading_list_and_table(self):
        html = markdown_to_html(
            "# Absence\n\n- lundi\n- mardi\n\n| Jour | Retour |\n|---|---|\n"
            "| lundi | mardi |\n"
        )
        self.assertIn("<h1>Absence</h1>", html)
        self.assertIn("<li>lundi</li>", html)
        self.assertIn("<table>", html)
        self.assertIn("<td>mardi</td>", html)

    def test_raw_html_is_escaped(self):
        html = markdown_to_html(
            '<script>alert(1)</script>\n\n<b onclick="x">gras</b>'
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b ", html)
        self.assertIn("&lt;script&gt;", html)

    def test_fallback_without_markdown_it(self):
        with patch.dict(sys.modules, {"markdown_it": None}):
            html = markdown_to_html("Bonjour <b>vous</b>\nligne 2\n\nFin")
        self.assertEqual(
            html,
            "<p>Bonjour &lt;b&gt;vous&lt;/b&gt;<br>\nligne 2</p>\n<p>Fin</p>\n",
        )

    def test_html_to_text_delegates(self):
        self.assertEqual(
            markup.html_to_text("<p>Un</p><p>Deux</p>"), "Un\nDeux"
        )


class TestDocument(unittest.TestCase):
    def test_fragment_is_wrapped_with_utf8_charset(self):
        html = wrap_html_document("<p>é</p>")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn("<p>é</p>", html)

    def test_full_document_is_left_alone(self):
        document = "<HTML><body>x</body></HTML>"
        self.assertEqual(wrap_html_document(document), document)


class TestImageRefs(unittest.TestCase):
    def test_image_refs_reads_both_quote_styles(self):
        html = (
            '<img src="logo.png"><IMG alt="x" SRC=\'photo.jpg\'><p src="no">'
        )
        self.assertEqual(image_refs(html), {"logo.png", "photo.jpg"})

    def test_rewrite_image_refs(self):
        html = '<p><img src="logo.png" alt="L"><img src="https://x/y.png"></p>'
        rewritten, used = rewrite_image_refs(
            html, {"logo.png": "img-1@example.org"}
        )
        self.assertEqual(used, {"logo.png"})
        self.assertIn('src="cid:img-1@example.org"', rewritten)
        self.assertIn('alt="L"', rewritten)
        self.assertIn('src="https://x/y.png"', rewritten)

    def test_data_src_is_not_rewritten(self):
        html = '<img data-src="logo.png" src="autre.png">'
        rewritten, used = rewrite_image_refs(html, {"logo.png": "c@d"})
        self.assertEqual(used, set())
        self.assertEqual(rewritten, html)

    def test_content_id(self):
        self.assertEqual(
            content_id("0123456789abcdef0123", DOMAIN),
            "img-0123456789abcdef@example.org",
        )


class TestRenderReply(unittest.TestCase):
    """Les trois formats, et le sort des images."""

    def test_markdown_inlines_referenced_and_attaches_the_rest(self):
        action = Action(
            format="markdown",
            body="Bonjour,\n\n![Logo](logo.png)\n",
            images=[LOGO_REF, PHOTO_REF],
        )
        rendered = render_reply(action, MEDIA, DOMAIN)
        self.assertEqual(rendered.text, action.body)
        cid = content_id(LOGO_REF.sha256, DOMAIN)
        self.assertIn(f'src="cid:{cid}"', rendered.html)
        self.assertTrue(rendered.html.startswith("<!DOCTYPE html>"))
        self.assertEqual(
            rendered.inline,
            [InlineImage(cid, LOGO, "image", "png", "logo.png")],
        )
        self.assertEqual(
            rendered.attachments,
            [AttachmentPart(PHOTO, "image", "jpeg", "photo.jpg")],
        )

    def test_html_format_derives_its_text(self):
        action = Action(
            format="html",
            body='<p>Bonjour</p><p><img src="photo.jpg"></p>',
            images=[LOGO_REF, PHOTO_REF],
        )
        rendered = render_reply(action, MEDIA, DOMAIN)
        self.assertEqual(rendered.text, "Bonjour")
        self.assertEqual([i.filename for i in rendered.inline], ["photo.jpg"])
        self.assertEqual(
            [a.filename for a in rendered.attachments], ["logo.png"]
        )

    def test_text_format_attaches_every_image(self):
        action = Action(
            format="text",
            body="Bonjour ![Logo](logo.png)",
            images=[LOGO_REF, PHOTO_REF],
        )
        rendered = render_reply(action, MEDIA, DOMAIN)
        self.assertIsNone(rendered.html)
        self.assertEqual(rendered.text, action.body)
        self.assertEqual(rendered.inline, [])
        self.assertEqual(
            [a.filename for a in rendered.attachments],
            ["logo.png", "photo.jpg"],
        )

    def test_missing_media_is_a_rule_error(self):
        action = Action(format="text", body="x", images=[LOGO_REF])
        with self.assertRaises(RuleError):
            render_reply(action, {}, DOMAIN)

    def test_images_heavier_than_the_total_limit_are_refused(self):
        refs, media = [], {}
        for index in range(3):
            name = f"image{index}.png"
            refs.append(MediaRef(name, f"{index:064x}", "image/png"))
            media[name] = b"x" * (2 * 1024 * 1024)
        action = Action(format="text", body="x", images=refs)
        with self.assertRaises(RuleError):
            render_reply(action, media, DOMAIN)
        action.images = refs[:2]
        self.assertEqual(
            len(render_reply(action, media, DOMAIN).attachments), 2
        )

    def test_raw_html_in_markdown_reply_is_escaped(self):
        action = Action(format="markdown", body="<img src=x onerror=alert(1)>")
        self.assertNotIn("<img", render_reply(action, {}, DOMAIN).html)


if __name__ == "__main__":
    unittest.main()
