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
            self.query_one("#summary", Static).update(
                f"  {total} {t('navigations')} · {len(paths)} {t('menus')}"
            )
            tree = self.query_one("#nav", Tree)
            tree.clear()
            nested = _nested(paths)
            todo = nested.get("TODO", {"count": 0, "children": nested})
            tree.root.set_label(f"📍 TODO  ({todo['count']})")
            self._add(tree.root, todo["children"])
            tree.root.expand()

        def _add(self, tnode, children):
            # Tri par visites décroissantes : les plus utilisés en tête.
            for name, node in sorted(
                children.items(), key=lambda kv: -kv[1]["count"]
            ):
                child = tnode.add(f"{name}  ({node['count']})", expand=True)
                self._add(child, node["children"])

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
