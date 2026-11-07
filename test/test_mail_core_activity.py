#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les deux prédicats de la collecte, sans le client : message
automatique, message auquel répond un message.

N'importe que la bibliothèque standard et `erplibre_mail_core` : tourne
aussi sous le Python du venv d'Odoo.
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))

from erplibre_mail_core import smtp, stats  # noqa: E402


class TestIsAutomatic(unittest.TestCase):
    def test_is_automatic_matches_the_client_rule(self):
        """Auto-Submitted dont le premier jeton n'est pas « no », sans
        casse et à chaque occurrence, ou X-Loop qui porte la marque des
        règles ; rien d'autre."""
        cases = {
            "auto-replied": ({"auto-submitted": "auto-replied"}, True),
            "auto-generated; x": (
                {"auto-submitted": "auto-generated; x"},
                True,
            ),
            "no": ({"auto-submitted": "no"}, False),
            "No": ({"auto-submitted": "No"}, False),
            "no; x": ({"auto-submitted": "no; x"}, False),
            "no then auto": ({"auto-submitted": "no\nauto-replied"}, True),
            "our x-loop": (
                {"x-loop": f"{smtp.X_LOOP_MARKER} boite.regles@example.org"},
                True,
            ),
            "our x-loop, upper case": (
                {"x-loop": smtp.X_LOOP_MARKER.upper()},
                True,
            ),
            "foreign x-loop": (
                {"x-loop": "liste-annonces@example.net"},
                False,
            ),
            "empty": ({}, False),
            "none": (None, False),
        }
        for label, (extra, expected) in cases.items():
            with self.subTest(case=label):
                self.assertIs(stats.is_automatic(extra), expected)


class TestReplyParent(unittest.TestCase):
    def test_reply_parent_prefers_in_reply_to(self):
        """Le premier identifiant d'In-Reply-To l'emporte sur References."""
        self.assertEqual(
            stats.reply_parent(
                "<p1@example.net> <p2@example.net>",
                "<r1@example.net> <r2@example.net>",
            ),
            "<p1@example.net>",
        )

    def test_reply_parent_falls_back_on_the_last_reference(self):
        """Sans In-Reply-To, le parent est le DERNIER identifiant de
        References, plié ou non."""
        self.assertEqual(
            stats.reply_parent(
                "", "<r1@example.net>\r\n <r2@example.net>\t<r3@example.net>"
            ),
            "<r3@example.net>",
        )
        self.assertEqual(stats.reply_parent("", ""), "")

    def test_reply_parent_ignores_unusable_tokens(self):
        """Un jeton non ASCII ou plus long que la limite ne sert pas ; un
        In-Reply-To sans jeton utilisable laisse la place à References."""
        long = "<" + "a" * smtp.MAX_MSGID_LEN + "@example.net>"
        self.assertEqual(
            stats.reply_parent("<é@example.net>", "<r1@example.net>"),
            "<r1@example.net>",
        )
        self.assertEqual(
            stats.reply_parent(long, f"<r1@example.net> {long}"),
            "<r1@example.net>",
        )
        self.assertEqual(stats.reply_parent("  ", "<é@example.net>"), "")


if __name__ == "__main__":
    unittest.main()
