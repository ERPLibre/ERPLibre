#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest

from script.todo.mail.charset import decode_bytes


class TestDecodeBytes(unittest.TestCase):
    def test_known_charset(self):
        self.assertEqual(decode_bytes("café".encode("utf-8"), "utf-8"), "café")

    def test_missing_charset_falls_back_to_utf8(self):
        self.assertEqual(decode_bytes("café".encode("utf-8"), None), "café")

    def test_empty_charset_falls_back_to_utf8(self):
        self.assertEqual(decode_bytes("café".encode("utf-8"), ""), "café")

    def test_unknown_8bit_falls_back_to_utf8(self):
        """La valeur réelle qui a fait tomber la synchro d'un dossier entier
        (voir `imap_transport.decode_header_value` et le rapport de tâche)."""
        self.assertEqual(
            decode_bytes("café".encode("utf-8"), "unknown-8bit"), "café"
        )

    def test_charset_with_a_stray_quote_falls_back(self):
        self.assertEqual(
            decode_bytes("café".encode("utf-8"), 'unknown-8bit"'), "café"
        )

    def test_bogus_charset_name_falls_back(self):
        self.assertEqual(
            decode_bytes("café".encode("utf-8"), "bogus-charset-xyz"), "café"
        )

    def test_wrong_but_known_charset_replaces_undecodable_bytes(self):
        # ascii connu, mais incapable de décoder un octet accentué : c'est
        # `errors="replace"`, pas le repli `LookupError`, qui doit agir ici.
        self.assertIn("�", decode_bytes(b"caf\xe9", "ascii"))


if __name__ == "__main__":
    unittest.main()
