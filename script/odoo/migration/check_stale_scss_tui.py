#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Full-screen browsing of the customized SCSS a version bump would break.

Two things have to be read before answering « reset it »: what the copy
changed — the only thing resetting gives up — and which variables the target
no longer defines, which is why it breaks at all. Space switches between them.

The text report says the same, but a 1000-line diff in a terminal scrollback
is not something anyone reads before deciding.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from check_stale_scss import render_diff, reset_command  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#files { width: 42; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def render_missing(finding):
    """Pourquoi ça casse : ce que la cible ne définit plus."""
    lines = [
        f"── id={finding['id']} {finding['url']} ──",
        "",
        f"  {t('This copy uses variables that')} {finding['version_dir']}"
        f" {t('no longer defines')} :",
        "",
    ]
    for name in finding["missing"]:
        lines.append(f"      ${name}")
    lines += [
        "",
        f"  {t('The copy was written against an older version and frozen')}",
        f"  {t('there. The module has since renamed what it relies on.')}",
        "",
        f"  {t('Resetting restores')} :",
        f"      {finding['module_path'] or t('(nothing: the target no longer ships this file)')}",
    ]
    return "\n".join(lines)


def build_app(lst_finding):
    """Build the application. Textual is imported here, not at module level.

    The module stays importable — and therefore testable — on a machine
    without Textual, which is also what lets the caller fall back to the text
    report rather than fail.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class StaleScssApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", "Quit"),
            ("space,tab", "toggle", "Diff / why"),
            ("c", "copy", "Copy reset command"),
        ]

        def __init__(self, lst_finding):
            super().__init__()
            self.lst_finding = lst_finding
            self.why = False
            self.index = 0

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="files", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Footer()

        def on_mount(self):
            self.title = "Customized SCSS at risk"
            table = self.query_one("#files", DataTable)
            table.add_columns("file", "+/-", "missing")
            for finding in self.lst_finding:
                table.add_row(
                    os.path.basename(finding["url"])[:30],
                    self._weight(finding),
                    str(len(finding["missing"])),
                    key=str(finding["id"]),
                )
            self._show()

        def _weight(self, finding):
            """Combien la copie s'écarte, pour trier d'un coup d'œil."""
            if not finding["module_path"]:
                return "—"
            import difflib

            diff = list(
                difflib.unified_diff(
                    finding["module_content"].splitlines(),
                    finding["custom"].splitlines(),
                    lineterm="",
                    n=0,
                )
            )
            plus = sum(
                1 for x in diff if x[:1] == "+" and not x.startswith("+++")
            )
            minus = sum(
                1 for x in diff if x[:1] == "-" and not x.startswith("---")
            )
            return f"+{plus}/-{minus}"

        def _show(self):
            if not self.lst_finding:
                return
            finding = self.lst_finding[self.index]
            which = "why it breaks" if self.why else "what the copy changed"
            self.query_one("#head", Static).update(
                f"{finding['url']}  ·  id={finding['id']}\n"
                f"[{which}]  —  space to switch, c to copy the reset command"
            )
            render = render_missing if self.why else render_diff
            self.query_one("#content", Static).update(render(finding))

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "files" and self.lst_finding:
                self.index = event.cursor_row
                self._show()

        def action_toggle(self):
            self.why = not self.why
            self._show()

        def action_copy(self):
            """Mettre la commande de réparation dans le presse-papier.

            Sans cela il faut la recopier à la main depuis un plein écran,
            avec deux arguments dont une faute ne se voit pas.
            """
            finding = self.lst_finding[self.index]
            command = reset_command([finding], finding["database"])
            try:
                self.copy_to_clipboard(command)
                self.notify(t("Reset command copied."))
            except Exception:
                self.notify(command, timeout=20)

    return StaleScssApp(lst_finding)


def run_tui(lst_finding, run_app=True):
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
        app = build_app(lst_finding)
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
