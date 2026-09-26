#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers statiques de l'interface web de TODO.

OWL est vendoré sans modification : ses fichiers doivent rester ceux du
paquet npm, dont le README de provenance note les empreintes.
"""

import hashlib
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "script" / "todo" / "web" / "static"
OWL = STATIC / "lib" / "owl-2.8.1"


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded(name):
    """sha256 que le README de provenance donne pour `name`, ou None."""
    text = (OWL / "README.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^- {re.escape(name)} sha256: ([0-9a-f]{{64}})$", text, re.M
    )
    return match.group(1) if match else None


class TestVendoredOwl(unittest.TestCase):
    def test_es_module_is_the_published_file(self):
        self.assertEqual(_sha256(OWL / "owl.es.js"), _recorded("owl.es.js"))

    def test_license_is_the_published_file(self):
        self.assertEqual(_sha256(OWL / "LICENSE"), _recorded("LICENSE"))

    def test_version_is_2_8_1(self):
        source = (OWL / "owl.es.js").read_text(encoding="utf-8")
        self.assertIn('const version = "2.8.1";', source)

    def test_prettier_leaves_vendored_files_alone(self):
        ignored = (REPO / ".prettierignore").read_text().splitlines()
        self.assertIn("script/todo/web/static/lib/", ignored)


if __name__ == "__main__":
    unittest.main()
