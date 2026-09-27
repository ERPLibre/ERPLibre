#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers statiques de l'interface web de TODO.

OWL est vendoré sans modification : ses fichiers doivent rester ceux du
paquet npm, dont le README de provenance note les empreintes. La page, elle,
est servie depuis la table que le hub charge au démarrage, sous une CSP qui
n'autorise que l'import map par son hash.
"""

import ast
import base64
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from script.todo import todo_telemetry
from script.todo.web import server

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "script" / "todo" / "web" / "static"
OWL = STATIC / "lib" / "owl-2.8.1"
SRC = STATIC / "src"


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded(name):
    """sha256 que le README de provenance donne pour `name`, ou None."""
    text = (OWL / "README.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^- {re.escape(name)} sha256: ([0-9a-f]{{64}})$", text, re.M
    )
    return match.group(1) if match else None


def _command_names() -> set:
    """Méthodes que l'arbre de TODO rattache à un menu ou à une feuille.

    Seuls les noms qui contiennent « _ » sont gardés : « run » ou « quit »
    sont aussi des mots courants, un nom composé ne l'est jamais.
    """
    names = set()

    def walk(node):
        if node.get("method"):
            names.add(node["method"])
        for child in node["children"]:
            walk(child)

    walk(todo_telemetry.build_code_tree())
    source = (REPO / "script" / "todo" / "todo.py").read_text(encoding="utf-8")
    cls = next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef)
    )
    names |= set(todo_telemetry._menu_labels(cls))
    return {name for name in names if "_" in name}


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


class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = server.load_static(STATIC)
        cls.index = (STATIC / "index.html").read_bytes()

    def test_index_is_served_at_the_root(self):
        self.assertEqual(self.table["/"][0], self.index)

    def test_import_map_names_the_vendored_module(self):
        body = server.IMPORT_MAP.search(self.index).group(1)
        imports = json.loads(body)["imports"]
        owl = "/static/lib/owl-2.8.1/owl.es.js"
        self.assertEqual(imports, {"@odoo/owl": owl})
        self.assertIn(owl, self.table)

    def test_csp_hash_is_the_hash_of_the_import_map(self):
        body = server.IMPORT_MAP.search(self.index).group(1)
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
        csp = server.content_security_policy(self.index)
        self.assertIn(
            f"script-src 'self' 'sha256-{digest}' 'unsafe-eval';", csp
        )

    def test_no_inline_script_or_style_besides_the_import_map(self):
        for attrs in re.findall(rb"<script([^>]*)>", self.index):
            self.assertTrue(
                b" src=" in attrs or attrs == b' type="importmap"', attrs
            )
        for path in [STATIC / "index.html", *SRC.glob("*.js")]:
            self.assertNotIn("style=", path.read_text(encoding="utf-8"))

    def test_every_reference_of_the_page_is_served(self):
        for ref in re.findall(rb'(?:href|src)="(/static/[^"]+)"', self.index):
            self.assertIn(ref.decode(), self.table)
        for path in SRC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            for rel in re.findall(r'from "\./([^"]+)"', text):
                self.assertIn(f"/static/src/{rel}", self.table, path.name)

    def test_the_whitelist_serves_page_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("a.js", "b.css", "c.html", "d.md", "LICENSE"):
                (base / name).write_text("x")
            for name in ("e.py", "f.json", "g.map", ".env"):
                (base / name).write_text("x")
            (base / "h.js").symlink_to(base / "e.py")
            table = server.load_static(base)
        served = ["LICENSE", "a.js", "b.css", "c.html", "d.md"]
        self.assertEqual(sorted(table), [f"/static/{n}" for n in served])
        self.assertEqual(table["/static/LICENSE"][1], server.LICENSE_TYPE)
        self.assertFalse([url for url in self.table if url.endswith(".py")])

    def test_the_tree_toggle_is_named_after_its_node(self):
        # Le bouton ne montre que ▸ ou ▾ : un lecteur d'écran annonce son
        # nom accessible, le libellé du nœud.
        source = (SRC / "tree_view.js").read_text(encoding="utf-8")
        [button] = re.findall(r"<button\b[^>]*>", source)
        self.assertIn('t-att-aria-label="props.node.label"', button)

    def test_the_page_code_names_no_command(self):
        names = _command_names()
        self.assertGreater(len(names), 50)
        for path in sorted(SRC.glob("*.js")):
            words = set(re.findall(r"\w+", path.read_text(encoding="utf-8")))
            self.assertFalse(words & names, path.name)


if __name__ == "__main__":
    unittest.main()
