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
    """{numéro: nom_de_méthode} depuis les branches « status == "N": self.X() »."""
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
                for n in ast.walk(stmt):
                    if (
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "self"
                    ):
                        out[num] = n.func.attr
                        break
                if num in out:
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
            target = disp[num]
            if target in labels:  # sous-menu
                node["children"].append(build(target))
            else:  # commande (feuille)
                lab = (
                    clabels[num - 1]
                    if 0 <= num - 1 < len(clabels)
                    else target.lstrip("_").replace("_", " ")
                )
                node["children"].append(
                    {"label": lab, "is_menu": False, "children": []}
                )
        seen.discard(method)
        return node

    return build("run")


def run_tui(run_app: bool = True):
    """Ouvre le TUI arborescent. `run_app=False` renvoie l'app (tests)."""
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Header, Static, Tree

    class Telemetry(App):
        CSS = """
        #summary { height: 1; color: $text-muted; }
        Tree { border: solid $accent; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter"),
            ("r", "reset", "Réinitialiser"),
            ("e", "expand_all", "Tout déplier"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="summary")
            yield Tree("📍 TODO", id="nav")
            yield Footer()

        def on_mount(self):
            self.title = t("TODO navigation telemetry")
            self._populate()

        def _populate(self):
            data = load()
            paths = data.get("paths", {})
            total = sum(paths.values())
            tree = self.query_one("#nav", Tree)
            tree.clear()
            code_tree = build_code_tree()
            if code_tree is not None:
                # Structure RÉELLE issue du code + compteurs de visites.
                cnt = paths.get("TODO", 0)
                tree.root.set_label(f"📍 TODO  ({cnt})")
                self._add_code(tree.root, code_tree["children"], "TODO", paths)
                src = t("tree from code")
            else:
                # Repli : arbre des seuls chemins visités.
                nested = _nested(paths)
                todo = nested.get("TODO", {"count": 0, "children": nested})
                tree.root.set_label(f"📍 TODO  ({todo['count']})")
                self._add_visited(tree.root, todo["children"])
                src = t("visited paths only")
            tree.root.expand()
            self.query_one("#summary", Static).update(
                f"  {total} {t('navigations')} · {len(paths)} "
                f"{t('menus')} · {src}"
            )

        def _add_code(self, tnode, children, parent_path, paths):
            """Nœuds depuis le code : menus (avec compteur de visites) et
            commandes (feuilles préfixées « · »)."""
            for c in children:
                if c["is_menu"]:
                    path = f"{parent_path} › {c['label']}"
                    cnt = paths.get(path, 0)
                    child = tnode.add(f"{c['label']}  ({cnt})", expand=True)
                    self._add_code(child, c["children"], path, paths)
                else:
                    tnode.add_leaf(f"· {c['label']}")

        def _add_visited(self, tnode, children):
            for name, node in sorted(
                children.items(), key=lambda kv: -kv[1]["count"]
            ):
                child = tnode.add(f"{name}  ({node['count']})", expand=True)
                self._add_visited(child, node["children"])

        def action_reset(self):
            reset()
            self._populate()
            self.notify(t("Telemetry reset."))

        def action_expand_all(self):
            self.query_one("#nav", Tree).root.expand_all()

    app = Telemetry()
    if run_app:
        app.run()
    return app
