#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Full-screen browsing of the COW copies that drifted from their module view.

Two things decide whether to reset a copy, and the text report puts them a
thousand lines apart: what the copy holds that the module view does not — the
only thing a reset gives up — and which child no longer finds its anchor,
which is why anything breaks at all. Space switches between them.

The reset command is on « c »: it takes a key, and copying a key by hand out
of a scrolled diff is where a character goes missing. A key matching no copy
is not an error for the tool — it runs and does nothing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from reset_stale_cow_views import render_broken, render_diff  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#copies { width: 44; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def weight(cow_view, module_view):
    """Combien la copie s'écarte, pour trier d'un coup d'œil."""
    if not module_view:
        return "—"
    import difflib

    diff = list(
        difflib.unified_diff(
            module_view["arch"].splitlines(),
            cow_view["arch"].splitlines(),
            lineterm="",
            n=0,
        )
    )
    plus = sum(1 for x in diff if x[:1] == "+" and not x.startswith("+++"))
    minus = sum(1 for x in diff if x[:1] == "-" and not x.startswith("---"))
    return f"+{plus}/-{minus}"


def build_app(lst_finding, database):
    """Build the application. Textual is imported here, not at module level.

    The module stays importable — and therefore testable — on a machine
    without Textual, which is also what lets the caller fall back to the text
    report rather than fail.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class StaleCowApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", "Quit"),
            ("space,tab", "toggle", "Diff / why"),
            ("c", "copy", "Copy reset command"),
        ]

        def __init__(self, lst_finding, database):
            super().__init__()
            self.lst_finding = lst_finding
            self.database = database
            self.why = False
            self.index = 0

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="copies", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Footer()

        def on_mount(self):
            self.title = "COW copies drifted from their module view"
            table = self.query_one("#copies", DataTable)
            table.add_columns("copy", "+/-", "broken")
            for cow_view, module_view, broken in self.lst_finding:
                table.add_row(
                    (cow_view["key"] or str(cow_view["id"]))[:30],
                    weight(cow_view, module_view),
                    str(len(broken)),
                    key=str(cow_view["id"]),
                )
            self._show()

        def _show(self):
            if not self.lst_finding:
                return
            cow_view, module_view, broken = self.lst_finding[self.index]
            which = "why it breaks" if self.why else "what the copy holds"
            self.query_one("#head", Static).update(
                f"{cow_view['key']}  ·  id={cow_view['id']}"
                f"  ·  website={cow_view.get('website_id')}\n"
                f"[{which}]  —  space to switch, c to copy the reset command"
            )
            if self.why:
                text = render_broken(cow_view, module_view, broken)
            elif module_view:
                text = render_diff(module_view, cow_view, indent="  ")
            else:
                text = (
                    f"  {t('No module view carries this key: nothing to reset')}"
                    f" {t('onto.')}"
                )
            self.query_one("#content", Static).update(text)

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "copies" and self.lst_finding:
                self.index = event.cursor_row
                self._show()

        def action_toggle(self):
            self.why = not self.why
            self._show()

        def action_copy(self):
            """Mettre la commande de réinitialisation dans le presse-papier.

            Elle prend une CLÉ, et recopier une clé à la main depuis un diff
            défilé est l'endroit où un caractère se perd — l'outil ne dirait
            rien, il ne trouverait simplement aucune copie.
            """
            cow_view = self.lst_finding[self.index][0]
            command = (
                "./script/odoo/migration/reset_stale_cow_views.py"
                f" -d {self.database} --reset {cow_view['key']} --apply"
            )
            try:
                self.copy_to_clipboard(command)
                self.notify(t("Reset command copied."))
            except Exception:
                self.notify(command, timeout=20)

    return StaleCowApp(lst_finding, database)


def run_tui(lst_finding, database, run_app=True):
    """Ouvrir l'écran. False si on n'a pas pu — et alors on DIT pourquoi.

    Trois refus, trois raisons, aucune n'est une panne : rien à montrer, pas
    de terminal, ou Textual absent. Se taire ferait réafficher le rapport
    texte à la place de l'écran demandé, sans rien qui distingue les deux.
    """
    if not lst_finding:
        return False
    if not sys.stdout.isatty():
        print(f"ℹ️  {t('Not a terminal: showing the text report instead.')}")
        return False
    try:
        from script.todo import textual_setup
    except Exception:
        textual_setup = None
    if textual_setup and not textual_setup.available():
        if not textual_setup.in_venv():
            print(
                f"ℹ️  {t('Textual is missing from this interpreter:')}"
                f" {sys.executable}"
            )
            print(f"   {t('Run it with')} .venv.erplibre/bin/python3")
    if textual_setup and not textual_setup.ensure():
        return False
    try:
        app = build_app(lst_finding, database)
    except ImportError:
        print(
            f"ℹ️  {t('Textual is missing from this interpreter:')}"
            f" {sys.executable}"
        )
        return False
    if not run_app:
        return app
    app.run()
    return True
