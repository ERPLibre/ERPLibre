#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fichiers statiques de l'interface web de TODO.

OWL, xterm.js et son addon « fit » sont vendorés sans modification : leurs
fichiers doivent rester ceux des paquets npm, dont chaque README de
provenance note les empreintes. La page, elle, est servie depuis la table
que le hub charge au démarrage, sous une CSP qui n'autorise que l'import
map par son hash. Les fonctions pures des vues (`static/src/model.js`,
`static/src/metrics.js`, `static/src/session.js`,
`static/src/history.js`, `static/src/prompt.js`) tournent sous node, quand
il est installé. Les mots de la page sont vérifiés par
`test_todo_web_i18n.py`.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from script.todo.ui import port
from script.todo.web import protocol, server

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

    def test_a_masked_field_keeps_its_value_nowhere(self):
        # Ni t-model ni état : la valeur part au terminal ou au worker, puis
        # s'efface. Sans formulaire, un gestionnaire de mots de passe n'a
        # rien à enregistrer.
        fields = {}
        for path in sorted(SRC.glob("*.js")):
            source = path.read_text(encoding="utf-8")
            found = re.findall(r'<input\b[^>]*\btype="password"[^>]*>', source)
            fields[path.name] = len(found)
            for field in found:
                self.assertNotIn("t-model", field)
                self.assertIn('autocomplete="off"', field)
            self.assertNotIn("<form", source)
        masked = {name: n for name, n in fields.items() if n}
        self.assertEqual(
            masked, {"question_view.js": 1, "sessions_view.js": 1}
        )
        # Une page qui s'en va vide d'abord ses champs masqués.
        view = (SRC / "sessions_view.js").read_text(encoding="utf-8")
        self.assertIn('addEventListener("pagehide"', view)

    def test_the_history_shows_a_log_as_text_only(self):
        # Une ligne de journal vient d'un programme quelconque : aucune
        # n'entre dans la page autrement que par textContent (t-esc).
        source = (SRC / "history_view.js").read_text(encoding="utf-8")
        for unsafe in ("t-out", "t-raw", "innerHTML", "markup"):
            self.assertNotIn(unsafe, source)
        self.assertIn('<span t-esc="text(record)"/>', source)

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

    def test_the_page_says_each_reason_of_a_drop(self):
        # Une raison que la page ne nomme pas s'afficherait comme `unread`.
        source = (SRC / "sessions_view.js").read_text(encoding="utf-8")
        block = re.search(
            r"^const DROP_LABELS = \{(.*?)^\};", source, re.M | re.S
        )
        named = re.findall(r"^\s+(\w+): \"", block[1], re.M)
        self.assertEqual(tuple(named), protocol.DROP_REASONS)

    def test_the_tree_toggle_is_named_after_its_node(self):
        # Le bouton ne montre que ▸ ou ▾ : un lecteur d'écran annonce son
        # nom accessible, le libellé du nœud.
        source = (SRC / "tree_view.js").read_text(encoding="utf-8")
        [button] = re.findall(r"<button\b[^>]*>", source)
        self.assertIn('t-att-aria-label="props.node.label"', button)


# Prélude des scripts node : le module nommé en argument, importé sous `m`
# par une URL data:, toujours lue comme un module ES — un .js hors d'un
# paquet « type: module » ne l'est pas avant node 22. Un module qu'il
# importe par « ./ » devient lui aussi une URL data:, qu'une URL data:
# peut importer, là où un chemin relatif ne se résout pas.
NODE_PRELUDE = r"""
const {readFileSync} = await import("node:fs");
const {dirname, join} = await import("node:path");
const url = (file) => {
    const code = readFileSync(file, "utf8").replace(/from "\.\/([\w.]+)"/g,
        (_, name) => `from "${url(join(dirname(file), name))}"`);
    return `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
};
const m = await import(url(process.argv[1]));
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
    history: m.readFragment("#view=history").view,
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
            self.view,
            {
                "view": "system",
                "sort": None,
                "sessions": "sessions",
                "history": "history",
            },
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


HISTORY_CHECK = r"""
const t = (key) => `<${key}>`;
const task = {crumbs: ["TODO", "Code"], entry: "Show code status",
    commands: [{cmd: "make forged", rc: 0}, {cmd: "make other", rc: 3},
        {cmd: "make last", rc: 2}]};
const records = [
    {n: 1, s: "event", d: {t: "task_start", crumbs: ["TODO"], entry: "Run"}},
    {n: 2, s: "out", d: "<b>not html</b>"},
    {n: 3, s: "event", d: {t: "run_end", rc: null, secs: 65}},
    {n: 4, s: "event", d: {t: "answer", value: "•••"}},
    {n: 5, s: "event", d: {t: "answered"}},
    {n: 6, s: "event", d: {t: "omitted", bytes: 12}},
    {n: 7, s: "event", d: {t: "timeout"}},
];
const rc = (codes) => m.taskRc({commands: codes.map((code) => ({rc: code}))});
console.log(JSON.stringify({
    title: m.taskTitle(task),
    rc: [m.taskRc(task), rc([0, null]), rc([0]), rc([])],
    commands: [m.taskCommands(task), m.taskCommands({commands: []})],
    durations: [5, 65, 7322, -1, null].map(m.duration),
    states: ["done", "interrupted", "open", "session-ended"].map(
        (state) => m.stateLabel(state, t)),
    texts: records.map((record) => m.recordText(record, t)),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestHistoryText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(HISTORY_CHECK, "history.js")

    def test_a_task_reads_as_its_path_first_failure_and_length(self):
        self.assertEqual(self.out["title"], "TODO › Code › Show code status")
        # La première commande en échec, pas la dernière.
        self.assertEqual(self.out["rc"], [3, "?", 0, ""])
        self.assertEqual(self.out["commands"], ["make forged (+2)", ""])
        self.assertEqual(
            self.out["durations"],
            ["5 s", "1 min 05 s", "2 h 02 min", "", ""],
        )
        self.assertEqual(
            self.out["states"],
            ["<done>", "<interrupted>", "<running>", "<Session ended>"],
        )

    def test_each_record_is_one_line_of_text(self):
        self.assertEqual(
            self.out["texts"],
            [
                "▶ TODO › Run",
                "<b>not html</b>",
                "⏎ <Exit code> ? · 1 min 05 s",
                "→ •••",
                "→ (<answered in the terminal>)",
                "… 12 <bytes omitted>",
                "⏱ <timed out>",
            ],
        )


# Un menu de treize entrées, 0 en plus : le filtre paraît, et plus à douze.
# Les clés 10 à 13 prolongent « 1 » ; « 2 » porte un accent.
MENU_CHECK = r"""
const items = [
    ...Array.from({length: 13}, (_, n) => ({key: String(n + 1),
        label: n === 1 ? "🖥 Système" : `Entry ${n + 1}`,
        section: n < 3 ? null : "Other"})),
    {key: "0", label: "🔙 Back", section: null},
];
const keys = items.map((item) => item.key);
const press = (sequence) => {
    let typed = "";
    const chosen = [];
    for (const key of sequence) {
        const out = m.menuKey(keys, typed, key);
        typed = out.typed;
        if (out.choose !== null) chosen.push(out.choose);
    }
    return [typed, chosen];
};
console.log(JSON.stringify({
    groups: m.menuGroups(items).map((g) =>
        [g.section, g.items.map((item) => item.key)]),
    back: [m.backItem(items).key, m.backItem(items.slice(0, 3))],
    filtered: [m.filterItems(items, " SYSTEME ").map((item) => item.key),
        m.filterItems(items, "12").map((item) => item.key),
        m.filterItems(items, "  ").length],
    presses: [["5"], ["1"], ["1", "Enter"], ["1", "2"], ["1", "9"],
        ["1", "Backspace", "0"], ["Tab", "x"], ["Escape"]].map(press),
    pause: [m.menuPause(keys, "1"), m.menuPause(keys, "19")],
    filters: [m.showsFilter(items), m.showsFilter(items.slice(1))],
    screens: [
        {t: "menu", text: "📍 TODO\nCommand:\n[1] Execute\n  [0] 🚪 Quit\n"},
        {t: "menu", text: "Choice [1]: "},
        {t: "menu", text: "[0] Back: "},
        {t: "ask", text: "[1] Execute\n[0] Quit\n"},
    ].map((question) => m.carriesScreen(
        {...question, items: [{key: "1"}, {key: "0"}]})),
    keys: [[false, 900], [false, 1249], [false, 1250], [true, 5000]].map(
        ([repeat, timeStamp]) => m.keyCounts({repeat, timeStamp}, 1000)),
    answerable: [[{qid: 2}, null, 2], [{qid: 2}, null, 1], [{qid: 2}, 2, 2],
        [null, null, 2]].map(([question, pending, qid]) =>
        m.answerable(question, pending, qid)),
    limits: [m.FILTER_FROM, m.PAUSE, m.ANSWER_LIMIT, m.ARM],
    sendable: ["", "forged", "x".repeat(4096), "x".repeat(4097),
        "🧰".repeat(4096), "tab\t", "esc\u001b]0;x", "del\u007f",
        "c1\u009b", "half\ud800"].map(m.sendable),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestMenuWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(MENU_CHECK, "prompt.js")

    def test_entries_group_by_section_with_zero_apart(self):
        rest = [str(n) for n in range(4, 14)]
        self.assertEqual(
            self.out["groups"], [[None, ["1", "2", "3"]], ["Other", rest]]
        )
        self.assertEqual(self.out["back"], ["0", None])

    def test_the_filter_ignores_case_and_accents_or_names_a_key(self):
        self.assertEqual(self.out["filtered"], [["2"], ["12"], 14])
        self.assertEqual(self.out["limits"][0], 12)
        # Treize entrées numérotées montrent le filtre, douze non : l'entrée
        # 0 ne compte pas.
        self.assertEqual(self.out["filters"], [True, False])

    def test_keys_choose_as_in_the_cli(self):
        # « 5 » part seul ; « 1 » attend, 10 à 13 le prolongent ; ce qui ne
        # mène à aucune clé s'efface.
        self.assertEqual(
            self.out["presses"],
            [
                ["", ["5"]],
                ["1", []],
                ["", ["1"]],
                ["", ["12"]],
                ["", []],
                ["", ["0"]],
                ["", []],
                ["", []],
            ],
        )
        self.assertEqual(self.out["pause"], ["1", None])
        self.assertEqual(self.out["limits"][1], 700)

    def test_a_menu_whose_text_lists_its_entries_carries_its_screen(self):
        # Le menu principal passe tout son écran à l'invite ; « Choice
        # [1]: » et « [0] Back: » ne portent que leur invite ; un `ask`
        # n'est pas un menu.
        self.assertEqual(self.out["screens"], [True, False, False, False])

    def test_nothing_answers_until_the_widget_has_been_seen(self):
        # Une touche d'avant son apparition, ou de moins de 250 ms après,
        # visait la question précédente ; une touche tenue se répète.
        self.assertEqual(self.out["keys"], [False, False, True, False])
        self.assertEqual(self.out["limits"][3], 250)

    def test_only_the_open_question_is_answered_once(self):
        # La question ouverte ; une autre ; déjà répondue ; aucune.
        self.assertEqual(self.out["answerable"], [True, False, False, False])

    def test_an_answer_is_what_the_hub_accepts(self):
        self.assertEqual(self.out["limits"][2], protocol.ANSWER_LIMIT)
        self.assertEqual(
            self.out["sendable"],
            [True, True, True, False, True, False, False, False, False, False],
        )


QUESTION_CHECK = r"""
const choose = {kind: "choose", text: "Which?\n[1] alpha\n[2] beta\n: ",
    options: [{key: "1", label: "alpha"}, {key: "2", label: "beta"}]};
const typed = {kind: "typed", text: "Type forged:", expected: "forged"};
console.log(JSON.stringify({
    kinds: m.ASK_KINDS,
    keys: ["y", "Y", "o", "O", "n", "N", "x", "Enter"].map(m.confirmKey),
    typed: ["forged", " forged", "forge", "Forged", ""].map(
        (value) => m.typedReady(typed, value)),
    free: ["", "anything", "tab\t"].map(
        (value) => m.typedReady({kind: "typed"}, value)),
    left: [[10000, 0], [10000, 9001], [10000, 9999], [10000, 10000],
        [10000, 12000]].map(([deadline, now]) => m.secondsLeft(deadline, now)),
    choice: [m.choiceValue(choose.options, ["2", "1"]),
        m.choiceValue(choose.options, [])],
    texts: [m.promptText(choose), m.promptText(typed),
        m.promptText({kind: "text", text: "💬 Name:  \n"}),
        m.promptText({t: "menu", source: "text", text: "Choice [1]: "})],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestQuestionWidgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(QUESTION_CHECK, "prompt.js")

    def test_the_page_shows_every_kind_the_port_asks(self):
        self.assertEqual(self.out["kinds"], list(port.REQUIRES))

    def test_y_o_and_n_answer_a_confirmation(self):
        yes, no = ["y"] * 4, ["n"] * 2
        self.assertEqual(self.out["keys"], [*yes, *no, None, None])

    def test_a_typed_confirmation_waits_for_the_exact_text(self):
        self.assertEqual(self.out["typed"], [True, False, False, False, False])
        # Sans texte attendu, toute réponse que le hub accepte.
        self.assertEqual(self.out["free"], [True, True, False])

    def test_the_countdown_counts_whole_seconds_down_to_zero(self):
        self.assertEqual(self.out["left"], [10, 1, 1, 0, 0])

    def test_a_multiple_choice_answers_its_keys_in_order(self):
        self.assertEqual(self.out["choice"], ["1 2", ""])

    def test_a_choice_shows_its_text_without_its_options(self):
        # Un écran lu montre son invite ; le reste est au terminal.
        self.assertEqual(
            self.out["texts"],
            ["Which?", "Type forged:", "💬 Name:", "Choice [1]:"],
        )


# Le repli d'un état, puis des suites de pas depuis un moment sans question :
# un état qui change, ou le bouton Terminal pressé (« click »), dont le
# choix s'oublie quand la phase change, comme dans SessionsView.receive.
FOLD_CHECK = r"""
const tty = {echo: true, canon: true, reader: false, altscreen: false};
const items = [{key: "1"}, {key: "0"}];
const menu = {qid: 7, t: "menu", text: "[1] Entry\n[0] Back\n", items};
const read = {qid: 8, t: "menu", text: "Choice [1]: ", items};
const idle = {question: null, running: false, altscreen: false, ran: false,
    tty, override: null};
const walk = (steps) => {
    let state = idle;
    return steps.map((step) => {
        if (step === "click") {
            const open = !m.terminalShown(state);
            state = {...state, override: {phase: m.foldPhase(state), open}};
        } else {
            state = {...state, ...step};
            const override = m.heldOverride(state.override, m.foldPhase(state));
            state = {...state, override};
        }
        return m.terminalShown(state);
    });
};
console.log(JSON.stringify({
    phase: m.foldPhase({...idle, question: menu}),
    auto: [idle, {...idle, question: menu},
        {...idle, question: menu, running: true},
        {...idle, question: menu, altscreen: true},
        {...idle, question: menu, ran: true}, {...idle, question: read},
        {...idle, question: {qid: 9, t: "ask", kind: "text"}},
    ].map(m.terminalShown),
    walks: [
        walk([{question: menu}, "click", {question: null},
            {question: {...menu, qid: 8}}]),
        walk([{running: true}, "click", {running: false, ran: true},
            {question: menu}, {question: null, ran: false}, {running: true}]),
        walk(["click", {question: menu}, {question: null}]),
        walk(["click", {tty: {...tty, reader: true}},
            {tty: {...tty, echo: false}}]),
    ],
}));
"""


@unittest.skipUnless(shutil.which("node"), "node absent")
class TestTerminalFold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = _node_json(FOLD_CHECK, "session.js")

    def test_only_a_menu_that_carries_its_screen_folds_the_terminal(self):
        # Rien d'ouvert ; un menu qui porte tout son écran ; pendant une
        # commande ; en écran alternatif ; la première question après une
        # commande ; un menu lu sur la sortie qui précède son invite ; une
        # question texte. Ces deux derniers n'ont que leur invite : ce que
        # TODO a écrit avant elle est au terminal.
        self.assertEqual(
            self.out["auto"], [True, False, True, True, True, True, True]
        )

    def test_the_button_holds_only_for_its_phase(self):
        self.assertEqual(self.out["phase"], "7|false|false")
        # Ouvert sous un menu : la réponse, puis le menu suivant, rendent
        # la main à la règle.
        self.assertEqual(self.out["walks"][0], [False, True, True, False])
        # Replié pendant une commande : la commande suivante se voit.
        self.assertEqual(
            self.out["walks"][1], [True, False, True, True, True, True]
        )
        # Replié sans question : un autre moment sans question le montre.
        self.assertEqual(self.out["walks"][2], [False, False, True])

    def test_a_program_prompt_always_shows_the_terminal(self):
        # Un lecteur, puis l'écho coupé, sans question structurée : le
        # bouton ne cache pas l'invite d'un programme.
        self.assertEqual(self.out["walks"][3], [False, True, True])


if __name__ == "__main__":
    unittest.main()
