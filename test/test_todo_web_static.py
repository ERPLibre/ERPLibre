#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers statiques de l'interface web de TODO.

OWL est vendoré sans modification : ses fichiers doivent rester ceux du
paquet npm, dont le README de provenance note les empreintes. La page, elle,
est servie depuis la table que le hub charge au démarrage, sous une CSP qui
n'autorise que l'import map par son hash. Les fonctions pures des vues
(`static/src/model.js`) tournent sous node, quand il est installé.
"""

import ast
import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.todo import todo_i18n, todo_telemetry
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

    def test_every_key_of_the_page_is_translated(self):
        # t() rend une clé inconnue telle quelle : une faute de frappe
        # s'afficherait en anglais dans une page française.
        keys = set()
        labels = re.compile(r"^const \w+_LABELS = \{.*\};$", re.M)
        for path in SRC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            keys |= {m[1] for m in re.findall(r"\bt\((['\"])(.+?)\1\)", text)}
            for line in labels.findall(text):
                keys |= set(re.findall(r'"([^"]+)"', line))
        self.assertGreater(len(keys), 10)
        missing = sorted(keys - set(todo_i18n.TRANSLATIONS))
        self.assertEqual(missing, [])


# Prélude des scripts node : le module nommé en argument, importé sous `m`
# par une URL data:, toujours lue comme un module ES — un .js hors d'un
# paquet « type: module » ne l'est pas avant node 22.
NODE_PRELUDE = r"""
const {readFileSync} = await import("node:fs");
const code = readFileSync(process.argv[1]).toString("base64");
const m = await import(`data:text/javascript;base64,${code}`);
"""


def _node_json(script, module):
    """JSON qu'affiche `script`, lancé sous node, `module` importé en `m`."""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", NODE_PRELUDE + script]
        + [str(SRC / module)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    return json.loads(out)


# Arbre factice aux libellés traduits, comme ceux de /api/telemetry.
MODEL_CHECK = r"""
const leaf = (key, label, parent) =>
    ({key, label, path: `${parent} › ${key}`, menu: false, children: []});
const tree = {key: "TODO", label: "TODO", path: "TODO", menu: true,
    children: [
        {key: "Execute", label: "Exécuter", path: "TODO › Execute",
            menu: true, children: [
                leaf("Quit", "🚪 Quitter", "TODO › Execute"),
                leaf("System", "🖥 Système", "TODO › Execute")]},
        {key: "Install", label: "Installer", path: "TODO › Install",
            menu: true, children: [
                leaf("Apply", "✅ Appliquer", "TODO › Install")]}]};
const counts = {"TODO › Install": 5, "TODO › Execute": 2,
    "TODO › Execute › System": 3};
const keys = (node) =>
    node && {key: node.key, children: node.children.map(keys)};
const paths = (rows) => rows.map((row) => row.path);
const list = (sort, query = "") =>
    paths(m.listRows(tree, counts, query, sort, "fr"));
console.log(JSON.stringify({
    fold: m.fold("Système ÉTÉ"),
    accents: keys(m.filterTree(tree, "SYSTEME")),
    menu: keys(m.filterTree(tree, "install")),
    nothing: m.filterTree(tree, "zzz"),
    root: m.filterTree(tree, "od"),
    blank: m.filterTree(tree, "  ") === tree,
    usage: keys(m.sortTree(tree, counts, "usage")),
    code: m.sortTree(tree, counts, "code") === tree,
    leaves: paths(m.leaves(tree)),
    listUsage: list("usage"),
    listName: list("name"),
    listQuery: list("code", "EXECUT"),
    sorts: [m.effectiveSort("tree", "name"), m.effectiveSort("list", ""),
        m.effectiveSort("tree", "usage")],
    launcher: m.readFragment("#login=x&view=telemetry&lang=fr"),
    reload: m.readFragment("#view=list&sort=name"),
    written: [
        m.writeFragment("#view=telemetry&lang=fr", {view: "list", sort: ""}),
        m.writeFragment("#lang=en", {view: "tree", sort: "usage"})],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestPageModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(MODEL_CHECK, "model.js")

    def test_search_ignores_case_and_accents(self):
        self.assertEqual(self.out["fold"], "systeme ete")
        execute = {
            "key": "Execute",
            "children": [{"key": "System", "children": []}],
        }
        self.assertEqual(
            self.out["accents"], {"key": "TODO", "children": [execute]}
        )

    def test_a_matching_menu_keeps_its_whole_subtree(self):
        install = {
            "key": "Install",
            "children": [{"key": "Apply", "children": []}],
        }
        self.assertEqual(
            self.out["menu"], {"key": "TODO", "children": [install]}
        )
        self.assertIsNone(self.out["nothing"])
        self.assertTrue(self.out["blank"])

    def test_the_root_label_never_matches(self):
        # « od » n'est que dans « TODO », le libellé de la racine.
        self.assertIsNone(self.out["root"])

    def test_tree_by_usage_is_stable_and_by_code_untouched(self):
        usage = self.out["usage"]
        self.assertEqual(
            [c["key"] for c in usage["children"]], ["Install", "Execute"]
        )
        self.assertEqual(
            [c["key"] for c in usage["children"][1]["children"]],
            ["System", "Quit"],
        )
        self.assertTrue(self.out["code"])

    def test_list_flattens_leaves_with_their_translated_path(self):
        code = [
            "Exécuter › 🚪 Quitter",
            "Exécuter › 🖥 Système",
            "Installer › ✅ Appliquer",
        ]
        self.assertEqual(self.out["leaves"], code)
        self.assertEqual(self.out["listUsage"], [code[1], code[0], code[2]])
        self.assertEqual(self.out["listName"], [code[2], code[0], code[1]])
        self.assertEqual(self.out["listQuery"], code[:2])

    def test_view_and_sort_live_in_the_fragment(self):
        self.assertEqual(self.out["sorts"], ["code", "usage", "usage"])
        self.assertEqual(self.out["launcher"], {"view": "tree", "sort": ""})
        self.assertEqual(self.out["reload"], {"view": "list", "sort": "name"})
        self.assertEqual(
            self.out["written"],
            ["#view=list&lang=fr", "#lang=en&view=tree&sort=usage"],
        )


if __name__ == "__main__":
    unittest.main()
