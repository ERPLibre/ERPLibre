#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Naviguer dans les différences entre une vue en base et celle du module.

Lecture seule, sans exception. La touche « r » AFFICHE la commande de
réinitialisation, elle ne l'exécute pas : cet écran sert à décider, et décider
suppose d'avoir lu. Une vue personnalisée porte souvent un travail réel que
personne ne veut perdre d'un appui sur une touche.

Pourquoi un seul DataTable à trois colonnes
--------------------------------------------
Deux panneaux séparés ne défilent pas ensemble : il faudrait synchroniser
deux barres, et une ligne de gauche finirait en face de la mauvaise ligne de
droite — exactement l'erreur qu'un diff doit rendre impossible. Un seul
tableau porte « gauche | marque | droite » sur la même ligne, donc
l'alignement est structurel et non entretenu. Il donne aussi le curseur, la
sélection et l'événement de survol sans rien écrire.

``TextArea`` a été écarté : c'est un éditeur, et il n'y a pas de coloration
XML sans tree-sitter, absent du venv.
"""

import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.analyse.lib_analyse import side_by_side, t  # noqa: E402

CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#views { width: 34; border-right: solid $accent; }
#diff { width: 1fr; }
"""


def diff_rows(finding):
    """Les lignes en écart d'un constat, sans les lignes identiques.

    Le contexte est utile dans un diff unifié qu'on lit en entier ; ici on
    saute d'un écart à l'autre, et les centaines de lignes identiques d'une
    vue de site web ne feraient que les éloigner.
    """
    return [
        (mark, left, right)
        for mark, left, right in side_by_side(
            finding.get("arch_ref"), finding.get("arch_db_text")
        )
        if mark != " "
    ]


def build_app(data):
    """Construire l'application Textual. Importe Textual seulement ici.

    L'import vit dans la fonction pour que le module reste importable — et
    donc testable — sur une machine sans Textual.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import DataTable, Footer, Header, Static

    class DiffApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("n", "only_diff", t("Differences only")),
            ("w", "ignore_indent", t("Ignore indentation")),
            ("c", "copy", t("Copy")),
            ("r", "command", t("Reset command")),
        ]

        def __init__(self, data):
            super().__init__()
            self.data = data
            self.lst_finding = [
                row for row in data["findings"] if row.get("differs")
            ]
            self.only_diff = True
            self.ignore_indent = False
            self.intent = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="views", cursor_type="row")
                yield DataTable(id="diff", cursor_type="row")
            yield Footer()

        def on_mount(self):
            self.title = t("Customised views")
            table = self.query_one("#views", DataTable)
            table.add_columns(t("view"), "+/-/≠")
            for row in self.lst_finding:
                stats = row.get("diff_stats") or {}
                table.add_row(
                    (row.get("key") or str(row["id"]))[:26],
                    f"{stats.get('added', 0)}/{stats.get('removed', 0)}"
                    f"/{stats.get('changed', 0)}",
                    key=str(row["id"]),
                )
            diff = self.query_one("#diff", DataTable)
            diff.add_columns(t("module (file)"), " ", t("database"))
            if self.lst_finding:
                self._show(0)

        def _show(self, index):
            row = self.lst_finding[index]
            stats = row.get("diff_stats") or {}
            self.query_one("#head", Static).update(
                f"{row.get('key') or row['id']}  ·  "
                f"{row.get('arch_fs') or '—'}\n"
                f"+{stats.get('added', 0)} -{stats.get('removed', 0)} "
                f"≠{stats.get('changed', 0)}  ·  "
                f"{', '.join(row.get('reason') or []) or '—'}"
            )
            diff = self.query_one("#diff", DataTable)
            diff.clear()
            for mark, left, right in side_by_side(
                row.get("arch_ref"), row.get("arch_db_text")
            ):
                if self.only_diff and mark == " ":
                    continue
                if self.ignore_indent:
                    left = (left or "").strip()
                    right = (right or "").strip()
                diff.add_row(left or "", mark, right or "")

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "views" and self.lst_finding:
                self._show(event.cursor_row)

        def _refresh(self):
            table = self.query_one("#views", DataTable)
            if self.lst_finding:
                self._show(table.cursor_row)

        def action_only_diff(self):
            self.only_diff = not self.only_diff
            self._refresh()

        def action_ignore_indent(self):
            self.ignore_indent = not self.ignore_indent
            self._refresh()

        def action_copy(self):
            table = self.query_one("#views", DataTable)
            if not self.lst_finding:
                return
            row = self.lst_finding[table.cursor_row]
            text = "\n".join(
                f"{mark} {left or ''} | {right or ''}"
                for mark, left, right in diff_rows(row)
            )
            # Tronqué en gardant la FIN : c'est là que se trouve ce qu'on
            # vient d'ajouter, donc ce qu'on cherche le plus souvent.
            self.copy_to_clipboard(text[-100_000:])
            self.notify(t("Difference copied."))

        def action_command(self):
            """Rendre l'intention à l'appelant : l'écran n'écrit jamais."""
            table = self.query_one("#views", DataTable)
            if not self.lst_finding:
                return
            self.intent = ("command", self.lst_finding[table.cursor_row])
            self.exit()

    return DiffApp(data)


def run_diff_tui(data, run_app=True):
    """Ouvrir l'écran. Renvoie l'intention retenue, ou None.

    ``run_app=False`` construit l'application sans la lancer : c'est ce qui
    permet de la tester sans terminal.
    """
    app = build_app(data)
    if not run_app:
        return app
    app.run()
    return app.intent
