#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers statiques de l'interface web de TODO.

OWL, xterm.js et son addon « fit » sont vendorés sans modification : leurs
fichiers doivent rester ceux des paquets npm, dont chaque README de
provenance note les empreintes. La page, elle, est servie depuis la table
que le hub charge au démarrage, sous une CSP qui n'autorise que l'import
map par son hash. Les fonctions pures des vues (`static/src/model.js`,
`static/src/metrics.js`, `static/src/session.js`) tournent sous node,
quand il est installé.
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
XTERM = STATIC / "lib" / "xterm-5.5.0"
FIT = STATIC / "lib" / "addon-fit-0.10.0"
SRC = STATIC / "src"


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded(name, lib=OWL):
    """sha256 que le README de provenance de `lib` donne pour `name`, ou
    None."""
    text = (lib / "README.md").read_text(encoding="utf-8")
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


class TestVendoredXterm(unittest.TestCase):
    def test_files_are_the_published_ones(self):
        vendored = {
            XTERM: ("xterm.js", "xterm.css", "LICENSE"),
            FIT: ("addon-fit.js", "LICENSE"),
        }
        for lib, names in vendored.items():
            for name in names:
                with self.subTest(lib=lib.name, name=name):
                    self.assertEqual(_sha256(lib / name), _recorded(name, lib))

    def test_both_builds_define_the_globals_the_page_reads(self):
        # Scripts classiques UMD, sans module ES : hors CommonJS et AMD,
        # xterm.js pose `Terminal` sur globalThis, addon-fit.js `FitAddon`.
        xterm = (XTERM / "xterm.js").read_text(encoding="utf-8")
        fit = (FIT / "addon-fit.js").read_text(encoding="utf-8")
        self.assertTrue(xterm.startswith("!function(e,t){"))
        self.assertIn("}(globalThis,", xterm)
        self.assertIn("e.Terminal=", xterm)
        self.assertIn(":e.FitAddon=t()}(self,", fit)


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
        # En ligne, les styles de xterm.js seulement ; jamais un script.
        self.assertIn("style-src 'self' 'unsafe-inline';", csp)
        self.assertEqual(csp.count("'unsafe-inline'"), 1)

    def test_xterm_loads_before_the_page_modules(self):
        # Scripts classiques : leurs globales existent quand main.js tourne.
        scripts = re.findall(
            rb'<script(?: type="(\w+)")? src="([^"]+)"', self.index
        )
        self.assertEqual(
            scripts,
            [
                (b"", b"/static/lib/xterm-5.5.0/xterm.js"),
                (b"", b"/static/lib/addon-fit-0.10.0/addon-fit.js"),
                (b"module", b"/static/src/main.js"),
            ],
        )
        self.assertIn(b'href="/static/lib/xterm-5.5.0/xterm.css"', self.index)

    def test_no_inline_script_or_style_besides_the_import_map(self):
        for attrs in re.findall(rb"<script([^>]*)>", self.index):
            self.assertTrue(
                b" src=" in attrs or attrs == b' type="importmap"', attrs
            )
        for path in [STATIC / "index.html", *SRC.glob("*.js")]:
            self.assertNotIn("style=", path.read_text(encoding="utf-8"))

    def test_the_masked_field_keeps_its_value_nowhere(self):
        # Ni t-model ni état : la valeur part au terminal, puis s'efface.
        # Sans formulaire, un gestionnaire de mots de passe n'a rien à
        # enregistrer.
        source = (SRC / "sessions_view.js").read_text(encoding="utf-8")
        [field] = re.findall(r'<input type="password"[^>]*>', source)
        self.assertNotIn("t-model", field)
        self.assertIn('autocomplete="off"', field)
        self.assertNotIn("<form", source)

    def test_a_hidden_session_never_covers_the_page(self):
        # « display » l'emporterait sur l'attribut hidden : le plein écran
        # ne vaut que pour une vue Sessions visible.
        css = (STATIC / "css" / "todo.css").read_text(encoding="utf-8")
        fixed = re.findall(r"^([^{}\n]+)\{[^}]*position: fixed", css, re.M)
        self.assertEqual(fixed, [".sessions.fullscreen:not([hidden]) "])

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
        labels = re.compile(r"^const \w+_LABELS = \{.*?\};$", re.M | re.S)
        for path in SRC.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            keys |= {m[1] for m in re.findall(r"\bt\((['\"])(.+?)\1\)", text)}
            for block in labels.findall(text):
                keys |= set(re.findall(r'"([^"]+)"', block))
        # Les clés d'un objet sur plusieurs lignes sont lues aussi.
        self.assertIn("Connection lost.", keys)
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


# Libellés sans lettre ni chiffre, comme `build_code_tree` en produit pour
# certaines feuilles (« () », un tiret seul, un point médian) : le tri par
# nom ne doit pas les placer en tête.
NAME_SORT_CHECK = r"""
const leaf = (label) =>
    ({key: label, label, path: label, menu: false, children: []});
const tree = {key: "TODO", label: "TODO", path: "TODO", menu: true,
    children: [
        leaf("🔧 Bravo"), leaf("()"), leaf("🔧 Alpha"), leaf("— "), leaf("·")]};
console.log(JSON.stringify({
    byName: m.listRows(tree, {}, "", "name", "fr").map((row) => row.path),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestNameSortWithLetterlessLabels(unittest.TestCase):
    def test_labels_with_no_letter_sort_last(self):
        out = _node_json(NAME_SORT_CHECK, "model.js")
        self.assertEqual(
            out["byName"], ["🔧 Alpha", "🔧 Bravo", "()", "— ", "·"]
        )


VIEW_CHECK = r"""
console.log(JSON.stringify({
    view: m.readFragment("#view=system").view,
    sort: m.effectiveSort("system", "usage") ?? null,
    sessions: m.readFragment("#view=sessions&session=s1").view,
}));
"""

# Deux échantillons, le premier sans taux ni température, le second complet.
METRICS_CHECK = r"""
const metrics = {cpu: null, net: null, mem: [8e9, 2e9],
    disk: [100e9, 40e9, 60e9], battery: null, temp: null, uptime: 90061,
    load: [0.5, 0.25, 1], ncpu: 4};
const next = {...metrics, cpu: 12, net: [1500, 2e6],
    battery: [85, "Discharging"]};
const rows = (sample, temp, lang = "en") =>
    m.systemRows(sample, temp, (key) => key, lang);
console.log(JSON.stringify({
    first: rows(metrics, null),
    next: rows(next, ["sysfs", [40.2, 55.7]]),
    french: rows(metrics, null, "fr"),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestSystemRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = _node_json(VIEW_CHECK, "model.js")
        out = _node_json(METRICS_CHECK, "metrics.js")
        cls.text = {
            name: {label: value for label, value, _ in rows}
            for name, rows in out.items()
        }
        cls.share = {
            name: {label: share for label, _, share in rows}
            for name, rows in out.items()
        }

    def test_the_system_view_offers_no_sort_hence_no_search(self):
        self.assertEqual(
            self.view, {"view": "system", "sort": None, "sessions": "sessions"}
        )

    def test_the_first_sample_waits_for_rates(self):
        first = self.text["first"]
        self.assertEqual(first["State"], "uptime 1d 1h · load 0.5 / 0.3 / 1")
        self.assertEqual(first["CPU"], "… · 4 cores")
        self.assertEqual(first["Memory"], "2 GB / 8 GB · 25%")
        self.assertEqual(first["Disk /"], "40 GB / 100 GB · 40% · 60 GB free")
        self.assertEqual(first["Network"], "…")
        self.assertEqual(first["Temperature"], "unavailable")
        self.assertNotIn("Battery", first)
        self.assertIsNone(self.share["first"]["CPU"])

    def test_the_next_sample_has_rates_shares_and_temperature(self):
        after = self.text["next"]
        self.assertEqual(after["CPU"], "12% · 4 cores")
        self.assertEqual(after["Network"], "↓ 1.5 kB/s · ↑ 2 MB/s")
        self.assertEqual(after["Battery"], "85% (Discharging)")
        self.assertEqual(after["Temperature"], "56°C (max)")
        shares = self.share["next"]
        self.assertEqual((shares["CPU"], shares["Battery"]), (0.12, 0.85))
        self.assertEqual((shares["Memory"], shares["Disk /"]), (0.25, 0.4))

    def test_units_and_numbers_follow_the_language(self):
        french = self.text["french"]
        self.assertIn("Go", french["Memory"])
        self.assertIn("0,5", french["State"])


SESSION_CHECK = r"""
const hello = {csrf: "c", lang: "fr", cols: 80, rows: 24};
console.log(JSON.stringify({
    open: JSON.parse(m.helloMessage(hello)),
    attach: JSON.parse(m.helloMessage({...hello, session: "s1", after: 0})),
    states: [[1000, {t: "bye"}], [1000, null], [1006, null], [1013, null],
        [4001, null], [4404, null]].map(([code, bye]) =>
            m.closedState(code, bye)),
    read: [m.sessionOf("#view=sessions&session=s1"), m.sessionOf("#lang=fr")],
    frame: m.FRAME,
    frames: m.frames(new Uint8Array(70000)).map((frame) => frame.length),
    written: [m.withSession("#view=sessions&lang=fr", "s1"),
        m.withSession("#view=sessions&session=s1", null)],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestSessionProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(SESSION_CHECK, "session.js")

    def test_hello_opens_or_attaches_from_an_offset(self):
        opened = {"t": "hello", "csrf": "c", "lang": "fr", "cols": 80}
        opened["rows"] = 24
        self.assertEqual(self.out["open"], opened)
        self.assertEqual(
            self.out["attach"], {**opened, "session": "s1", "after": 0}
        )

    def test_each_close_code_names_a_state(self):
        self.assertEqual(
            self.out["states"],
            ["ended", "lost", "lost", "full", "taken", "gone"],
        )

    def test_a_paste_goes_in_frames_the_hub_accepts(self):
        frame = self.out["frame"]
        self.assertLess(frame, server.MAX_BODY)
        self.assertEqual(self.out["frames"], [frame, frame, 70000 - 2 * frame])

    def test_the_session_lives_in_the_fragment(self):
        self.assertEqual(self.out["read"], ["s1", None])
        self.assertEqual(
            self.out["written"],
            ["#view=sessions&lang=fr&session=s1", "#view=sessions"],
        )


QUICK_CHECK = r"""
const lines = [
    "Continue? [y/N]", "Remove it? [Y/n] ", "Supprimer ? (o/N) :",
    "Garder ? (O/n)", "Écraser ? [o/N]", "Proceed (yes/no)?",
    "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
    "Type DELETE to confirm:", "[y/N] is the default", "[sudo] password:", "",
];
console.log(JSON.stringify({
    answers: lines.map((line) => m.quickAnswers(line.trimEnd())),
    last: [m.lastLine(["a", "Continue? [y/N] ", "", "  "]),
        m.lastLine(["", " "])],
    wrapped: m.joinWrapped([{text: "a", wrapped: false},
        {text: "Proceed? [y/", wrapped: false}, {text: "N] ", wrapped: true},
        {text: "", wrapped: false}]),
    secret: [{echo: false, canon: true}, {echo: false, canon: false},
        {echo: true, canon: true}].map(m.asksSecret),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestQuickAnswers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(QUICK_CHECK, "session.js")

    def test_known_prompts_at_the_end_of_the_line_offer_answers(self):
        yes_no = [["y", "n"], ["y", "n"], ["o", "n"], ["o", "n"], ["o", "n"]]
        self.assertEqual(
            self.out["answers"],
            [*yes_no, ["yes", "no"], ["yes", "no"], [], [], [], []],
        )

    def test_the_prompt_is_the_last_line_with_text(self):
        self.assertEqual(self.out["last"], ["Continue? [y/N]", ""])

    def test_a_prompt_the_terminal_wrapped_is_one_line(self):
        self.assertEqual(self.out["wrapped"], ["a", "Proceed? [y/N] ", ""])

    def test_only_a_canonical_terminal_without_echo_asks_a_secret(self):
        self.assertEqual(self.out["secret"], [True, False, False])


if __name__ == "__main__":
    unittest.main()
