#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Télémétrie de navigation du CLI TODO.

Enregistre les fils d'Ariane visités (« A › B › C » -> compteur) et affiche un
DIAGRAMME arborescent des fonctionnalités dans un TUI Textual, trié par usage.

- record(path) : appelé par Todo._menu_header à chaque affichage de menu ; on
  dédupe les ré-affichages consécutifs pour ne compter que les TRANSITIONS.
- run_tui() : ouvre l'arbre de navigation (compteurs par menu).
"""
from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Dernier chemin enregistré : évite de recompter chaque ré-affichage du même
# menu (une commande qui revient au menu ne compte pas comme une navigation).
_LAST = [None]


def _path() -> Path:
    base = Path(os.path.expanduser("~/.erplibre"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "todo_telemetry.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"paths": {}}


def _save(data: dict) -> None:
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def record(path: str) -> None:
    """Incrémente le compteur du menu `path`. Best-effort : ne lève jamais
    (la télémétrie ne doit jamais casser la navigation)."""
    if not path or path == _LAST[0]:
        return
    _LAST[0] = path
    try:
        data = load()
        paths = data.setdefault("paths", {})
        paths[path] = paths.get(path, 0) + 1
        data["updated"] = int(time.time())
        _save(data)
    except Exception:
        pass


def reset() -> None:
    _save({"paths": {}})


def _nested(paths: dict) -> dict:
    """{« A › B › C »: count} -> arbre {nom: {'count', 'children'}}. Chaque
    menu enregistre son propre chemin, donc chaque nœud a son compteur."""
    root: dict = {}
    for path, count in paths.items():
        cur = root
        parts = path.split(" › ")
        for i, name in enumerate(parts):
            node = cur.setdefault(name, {"count": 0, "children": {}})
            if i == len(parts) - 1:
                node["count"] += count
            cur = node["children"]
    return root


# --------------------------------------------------------------------------- #
# Métadonnées de navigation DÉRIVÉES DU CODE (structure réelle des menus)
# --------------------------------------------------------------------------- #
def _str_of(node) -> str | None:
    """Chaîne d'un nœud AST : littéral, t("…") ou f-string (parties Constant)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "t"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ):
        return node.args[0].value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            p.value
            for p in node.values
            if isinstance(p, ast.Constant) and isinstance(p.value, str)
        )
    return None


def _choice_labels(func) -> list:
    """Libellés NUMÉROTÉS d'un menu « choices = [...] » (dans l'ordre, sections
    exclues car non numérotées par fill_help_info)."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(tg, ast.Name) and tg.id == "choices"
                for tg in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            labels = []
            for el in node.value.elts:
                if not isinstance(el, ast.Dict):
                    continue
                for k, v in zip(el.keys, el.values):
                    if isinstance(k, ast.Constant) and k.value == "prompt_description":
                        s = _str_of(v)
                        if s:
                            labels.append(s)
            return labels
    return []


def _dispatch(func) -> dict:
    """{numéro: (nom_de_méthode, kwargs)} depuis « status == "N": self.X(...) ».
    Les kwargs LITTÉRAUX (ex. dry_run=True) sont capturés pour pouvoir rejouer
    la commande à l'identique depuis la télémétrie."""
    out = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "status"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.comparators[0], ast.Constant)
        ):
            try:
                num = int(test.comparators[0].value)
            except (TypeError, ValueError):
                continue
            for stmt in node.body:
                found = None
                for n in ast.walk(stmt):
                    if (
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "self"
                    ):
                        kwargs = {
                            kw.arg: kw.value.value
                            for kw in n.keywords
                            if kw.arg
                            and isinstance(kw.value, ast.Constant)
                        }
                        found = (n.func.attr, kwargs)
                        break
                if found:
                    out[num] = found
                    break
    return out


def _menu_labels(cls) -> dict:
    """{méthode: label} depuis l'attribut de classe _MENU_LABELS."""
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(tg, ast.Name) and tg.id == "_MENU_LABELS"
                for tg in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            return {
                k.value: v.value
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
    return {}


def build_code_tree(todo_path=None) -> dict | None:
    """Construit l'arbre des menus/commandes EN LISANT le code de todo.py
    (AST). Chaque menu (méthode de _MENU_LABELS) devient un nœud ; ses branches
    « status == N » deviennent des sous-menus (si la cible est un menu) ou des
    commandes (feuilles). None si l'analyse échoue."""
    p = Path(todo_path) if todo_path else (Path(__file__).parent / "todo.py")
    try:
        mod = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    cls = next(
        (n for n in ast.walk(mod) if isinstance(n, ast.ClassDef)), None
    )
    if cls is None:
        return None
    methods = {
        n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)
    }
    labels = _menu_labels(cls)
    if "run" not in methods or not labels:
        return None
    seen = set()

    def build(method):
        node = {
            "label": labels.get(method, method),
            "is_menu": True,
            "children": [],
        }
        if method in seen or method not in methods:
            return node
        seen.add(method)
        func = methods[method]
        disp = _dispatch(func)
        clabels = _choice_labels(func)
        for num in sorted(disp):
            target, kwargs = disp[num]
            if target in labels:  # sous-menu
                node["children"].append(build(target))
            else:  # commande (feuille) exécutable
                lab = (
                    clabels[num - 1]
                    if 0 <= num - 1 < len(clabels)
                    else target.lstrip("_").replace("_", " ")
                )
                node["children"].append(
                    {
                        "label": lab,
                        "is_menu": False,
                        "children": [],
                        "method": target,
                        "kwargs": kwargs,
                    }
                )
        seen.discard(method)
        return node

    return build("run")


def _command_columns(tree, paths):
    """Colonnes du Kanban : (label, chemin, count, [commandes]) pour CHAQUE
    menu qui contient des commandes directes (parcours profondeur d'abord)."""
    cols = []

    def walk(node, path):
        cmds = [c for c in node["children"] if not c["is_menu"]]
        if cmds:
            cols.append((node["label"], path, paths.get(path, 0), cmds))
        for c in node["children"]:
            if c["is_menu"]:
                walk(c, f"{path} › {c['label']}")

    if tree:
        walk(tree, "TODO")
    return cols


# Modes d'affichage du Kanban (F4 les fait défiler).
KANBAN_MODES = ("columns", "swimlanes", "grid")


def run_tui(run_app: bool = True, state: dict | None = None):
    """TUI de télémétrie : vue Arbre (issue du code) et vue Kanban (F3), la
    disposition du Kanban défilant par F4 (colonnes / swimlanes / grille).
    Sélectionner une COMMANDE = l'exécuter. `state` restaure la vue + le
    curseur au retour. Renvoie (action|None, state) ; run_app=False -> l'app."""
    from textual.app import App, ComposeResult
    from textual.containers import (
        Container,
        Grid,
        HorizontalScroll,
        Vertical,
        VerticalScroll,
    )
    from textual.widgets import (
        Footer,
        Header,
        Label,
        ListItem,
        ListView,
        Static,
        Tree,
    )

    paths = load().get("paths", {})
    code_tree = build_code_tree()
    columns = _command_columns(code_tree, paths)  # (label, path, cnt, cmds)
    state = state or {}

    class CmdItem(ListItem):
        """Carte : commande à exécuter + son chemin (pour restaurer le curseur)."""

        def __init__(self, label, method, kwargs, path):
            super().__init__(Label(label))
            self.cmd_method = method
            self.cmd_kwargs = kwargs or {}
            self.cmd_path = path

    class Telemetry(App):
        CSS = """
        #summary { height: 1; color: $text-muted; }
        Tree { border: solid $accent; }
        #kanban { display: none; height: 1fr; }
        .kcol { width: 40; border: solid $accent; margin: 0 1 0 0; }
        .ktitle { height: 1; color: $accent; }
        .lane { height: auto; }
        .lanetitle { height: 1; color: $secondary; }
        .kgrid { grid-size: 3; grid-gutter: 1; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter"),
            ("f3", "toggle_view", "Arbre/Kanban"),
            ("f4", "kanban_layout", "Disposition Kanban"),
            ("e", "expand_all", "Tout déplier"),
            ("r", "reset", "Réinitialiser"),
        ]

        def __init__(self):
            super().__init__()
            self._action = None
            self._mode = state.get("mode", "tree")
            self._kanban_mode = state.get("kanban_mode", "columns")

        # -- helpers de construction de widgets ------------------------------ #
        def _col_widget(self, label, cnt, cmds):
            items = [
                CmdItem(
                    f"· {c['label']}",
                    c.get("method"),
                    c.get("kwargs"),
                    c.get("path"),
                )
                for c in cmds
            ]
            return VerticalScroll(
                Static(f"{label}  ({cnt})", classes="ktitle"),
                ListView(*items),
                classes="kcol",
            )

        def _kanban_layout_widget(self):
            cols = [
                self._col_widget(label, cnt, cmds)
                for (label, _p, cnt, cmds) in columns
            ]
            if not cols:
                return Static(t("No command found."))
            if self._kanban_mode == "grid":
                return Grid(*cols, classes="kgrid")
            if self._kanban_mode == "swimlanes":
                # Une rangée (swimlane) par menu de NIVEAU 1 (Execute, …).
                groups, order = {}, []
                for (label, path, cnt, cmds) in columns:
                    parts = path.split(" › ")
                    g = parts[1] if len(parts) > 1 else "TODO"
                    if g not in groups:
                        groups[g] = []
                        order.append(g)
                    groups[g].append((label, cnt, cmds))
                lanes = []
                for g in order:
                    lane_cols = [
                        self._col_widget(lb, cn, cm) for (lb, cn, cm) in groups[g]
                    ]
                    lanes.append(
                        Vertical(
                            Static(f"━━ {g} ━━", classes="lanetitle"),
                            HorizontalScroll(*lane_cols),
                            classes="lane",
                        )
                    )
                return VerticalScroll(*lanes)
            return HorizontalScroll(*cols)  # columns

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="summary")
            yield Tree("📍 TODO", id="nav")
            yield Container(id="kanban")
            yield Footer()

        def on_mount(self):
            self.title = t("TODO navigation telemetry")
            self._populate_tree()
            self._update_summary()
            # Restaure la vue / la disposition / le curseur au retour.
            self.run_worker(self._restore())

        async def _restore(self):
            if self._mode == "kanban":
                await self._enter_kanban()
            else:
                self.query_one("#nav").display = True
                self.query_one("#kanban").display = False
                self._focus_tree_path(state.get("path"))
            self._update_summary()

        # -- vue Kanban ------------------------------------------------------ #
        async def _enter_kanban(self):
            box = self.query_one("#kanban", Container)
            await box.remove_children()
            await box.mount(self._kanban_layout_widget())
            self.query_one("#nav").display = False
            box.display = True
            self._focus_kanban_path(state.get("path"))

        def _focus_kanban_path(self, path):
            if not path:
                return
            for lv in self.query(ListView):
                for i, item in enumerate(lv.children):
                    if getattr(item, "cmd_path", None) == path:
                        lv.index = i
                        lv.focus()
                        return

        def _focus_tree_path(self, path):
            if not path:
                return
            tree = self.query_one("#nav", Tree)

            def walk(node):
                d = getattr(node, "data", None)
                if isinstance(d, dict) and d.get("path") == path:
                    return node
                for ch in node.children:
                    found = walk(ch)
                    if found:
                        return found
                return None

            node = walk(tree.root)
            if node is not None:
                tree.move_cursor(node)
                tree.scroll_to_node(node)

        def _update_summary(self):
            total = sum(paths.values())
            src = t("tree from code") if code_tree else t("visited paths only")
            extra = (
                f" [{self._kanban_mode}]" if self._mode == "kanban" else ""
            )
            self.query_one("#summary", Static).update(
                f"  {total} {t('navigations')} · {len(paths)} {t('menus')} · "
                f"{src} · {t('view')}: {self._mode}{extra} · "
                f"{t('Enter = run, F3/F4 = views')}"
            )

        def _populate_tree(self):
            tree = self.query_one("#nav", Tree)
            tree.clear()
            if code_tree is not None:
                tree.root.data = {"path": "TODO"}
                tree.root.set_label(f"📍 TODO  ({paths.get('TODO', 0)})")
                self._add_code(tree.root, code_tree["children"], "TODO")
            else:
                nested = _nested(paths)
                todo = nested.get("TODO", {"count": 0, "children": nested})
                tree.root.set_label(f"📍 TODO  ({todo['count']})")
                self._add_visited(tree.root, todo["children"])
            tree.root.expand()

        def _add_code(self, tnode, children, parent_path):
            for c in children:
                path = f"{parent_path} › {c['label']}"
                if c["is_menu"]:
                    child = tnode.add(
                        f"{c['label']}  ({paths.get(path, 0)})",
                        data={"path": path},
                        expand=True,
                    )
                    self._add_code(child, c["children"], path)
                else:
                    # Feuille EXÉCUTABLE : méthode + chemin portés en data.
                    tnode.add_leaf(
                        f"· {c['label']}",
                        data={
                            "method": c.get("method"),
                            "kwargs": c.get("kwargs"),
                            "path": path,
                        },
                    )

        def _add_visited(self, tnode, children):
            for name, node in sorted(
                children.items(), key=lambda kv: -kv[1]["count"]
            ):
                child = tnode.add(f"{name}  ({node['count']})", expand=True)
                self._add_visited(child, node["children"])

        # -- sélection / exécution ------------------------------------------- #
        def _run(self, method, kwargs, path):
            if not method:
                return
            self._action = (method, kwargs or {})
            self._exit_state = {
                "mode": self._mode,
                "kanban_mode": self._kanban_mode,
                "path": path,
            }
            self.exit()

        def on_tree_node_selected(self, event):
            d = getattr(event.node, "data", None)
            if isinstance(d, dict) and d.get("method"):
                self._run(d["method"], d.get("kwargs"), d.get("path"))

        def on_list_view_selected(self, event):
            if isinstance(event.item, CmdItem):
                self._run(
                    event.item.cmd_method,
                    event.item.cmd_kwargs,
                    event.item.cmd_path,
                )

        # -- actions --------------------------------------------------------- #
        async def action_toggle_view(self):
            if self._mode == "tree":
                self._mode = "kanban"
                await self._enter_kanban()
            else:
                self._mode = "tree"
                self.query_one("#kanban").display = False
                self.query_one("#nav").display = True
            self._update_summary()

        async def action_kanban_layout(self):
            if self._mode != "kanban":
                return
            i = KANBAN_MODES.index(self._kanban_mode)
            self._kanban_mode = KANBAN_MODES[(i + 1) % len(KANBAN_MODES)]
            await self._enter_kanban()
            self._update_summary()

        def action_expand_all(self):
            if self._mode == "tree":
                self.query_one("#nav", Tree).root.expand_all()

        def action_reset(self):
            reset()
            paths.clear()
            self._populate_tree()
            self._update_summary()
            self.notify(t("Telemetry reset."))

    app = Telemetry()
    app._exit_state = state
    if run_app:
        app.run()
        return app._action, getattr(app, "_exit_state", state)
    return app
