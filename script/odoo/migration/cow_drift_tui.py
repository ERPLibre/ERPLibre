#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Full-screen browsing of the at-risk website COW copies.

Read-only, without exception: this screen exists to decide, and deciding
supposes having looked. Neutralizing stays a separate, explicit command.

Two views of the same copy, one key apart
-----------------------------------------
« What do I lose » and « why does it break » are different questions with
different answers, and putting them side by side would halve the width of
each on a screen that already shows XML. They share the pane instead, and
``space`` switches — the header always says which one is showing, because a
diff and a declaration look alike at a glance.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#views { width: 38; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def build_app(lst_finding):
    """Build the application. Textual is imported here, not at module level.

    The module stays importable — and therefore testable — on a machine
    without Textual, which is also what lets the caller fall back to the text
    report rather than fail.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    from cow_drift import render_diff, render_shape

    class DriftApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", "Quit"),
            ("space,tab", "toggle", "Diff / declarations"),
            ("c", "copy", "Copy"),
        ]

        def __init__(self, lst_finding):
            super().__init__()
            self.lst_finding = lst_finding
            self.shape = False
            self.index = 0

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="views", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Footer()

        def on_mount(self):
            self.title = "Website COW copies at risk"
            table = self.query_one("#views", DataTable)
            table.add_columns("copy", "+/-")
            for finding in self.lst_finding:
                table.add_row(
                    (finding["key"] or str(finding["id"]))[:28],
                    self._weight(finding),
                    key=str(finding["id"]),
                )
            self._show()

        def _weight(self, finding):
            """How much the copy diverges, so the list can be triaged."""
            if finding["module_id"] is None:
                return "—"
            import difflib

            diff = list(
                difflib.unified_diff(
                    finding["module_arch"].splitlines(),
                    finding["copy_arch"].splitlines(),
                    lineterm="",
                    n=0,
                )
            )
            plus = sum(
                1
                for x in diff
                if x.startswith("+") and not x.startswith("+++")
            )
            minus = sum(
                1
                for x in diff
                if x.startswith("-") and not x.startswith("---")
            )
            return f"+{plus}/-{minus}"

        def _show(self):
            if not self.lst_finding:
                return
            finding = self.lst_finding[self.index]
            which = "declarations" if self.shape else "what the copy changed"
            self.query_one("#head", Static).update(
                f"{finding['key']}  ·  id={finding['id']}"
                f"  ·  website={finding['website_id']}\n"
                f"[{which}]  —  space to switch"
            )
            render = render_shape if self.shape else render_diff
            self.query_one("#content", Static).update(render(finding))

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "views" and self.lst_finding:
                self.index = event.cursor_row
                self._show()

        def action_toggle(self):
            self.shape = not self.shape
            self._show()

        def action_copy(self):
            if not self.lst_finding:
                return
            from cow_drift import render_diff, render_shape

            render = render_shape if self.shape else render_diff
            # Truncated keeping the END: that is where the added lines are,
            # and what someone is most often after.
            self.copy_to_clipboard(
                render(self.lst_finding[self.index])[-100_000:]
            )
            self.notify("Copied.")

    return DriftApp(lst_finding)


def run_tui(lst_finding, run_app=True):
    """Open the screen. False when it could not be shown.

    False is not a failure: the caller prints the text report instead, which
    is the same information without the navigation.
    """
    if not lst_finding:
        return False
    if not sys.stdout.isatty():
        return False
    try:
        app = build_app(lst_finding)
    except ImportError:
        return False
    if not run_app:
        return app
    app.run()
    return True
