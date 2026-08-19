#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'état d'une migration, en plein écran.

Le rapport texte dit tout, mais il dit tout D'UN COUP : sur une migration
de six paliers il fait plusieurs centaines de lignes, et ce qu'on cherche —
l'étape où ça a cassé, ce que le test de fumée a conclu — se trouve
quelque part au milieu. Un écran qui se parcourt règle exactement cela.

Les données viennent de `migration_status`, comme le rapport texte. Deux
assemblages séparés dériveraient l'un de l'autre sans que rien ne le dise,
et l'on finirait par lire deux états contradictoires de la même migration.
"""

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.todo import migration_status as status  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 4; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#left { width: 46; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def head_text(dct):
    """Ce qui identifie la migration. Toujours visible, jamais à chercher."""
    info = status.overview(dct)
    lst_test = status.tests_summary(dct)
    casse = [x for x in lst_test if x.get("status")]
    return (
        f"{info['database']}  ·  {info['file']}\n"
        f"{t('current step')} : {info['step']}\n"
        f"{t('last written')} : {info['updated']}"
        f"   ·   {len(status.failures(dct))} {t('failed')}"
        f"   ·   {len(casse)}/{len(lst_test)} {t('Test results')}"
    )


def rows(dct):
    """Les lignes du panneau de gauche : tests d'abord, puis les étapes.

    Les tests en tête parce que c'est la question qu'on se pose en ouvrant
    cet écran ; les étapes ensuite parce que c'est là qu'on cherche le
    détail une fois qu'on sait QUOI chercher.
    """
    lst = []
    for item in status.tests_summary(dct):
        icone, _phrase = status.verdict(item.get("status"))
        lst.append(
            {
                "kind": "test",
                "label": f"{icone} {item['name']}",
                "detail": str(item.get("runs", 1)),
                "data": item,
            }
        )
    for section in status.journal_by_step(dct):
        lst.append(
            {
                "kind": "step",
                "label": section["step"],
                "detail": str(len(section["lst_cmd"])),
                "data": section,
            }
        )
    return lst


def pane_text(dct, row):
    """Le détail de la ligne choisie."""
    if row is None:
        return t("Nothing to show yet.")
    if row["kind"] == "test":
        item = row["data"]
        icone, phrase = status.verdict(item.get("status"))
        lignes = [
            f"{icone} {item['name']}",
            f"   {phrase}  ({t('exit code')} {item.get('status')})",
            f"   {t('runs')} : {item.get('runs')}",
            f"   {t('current step')} : {item.get('step') or '?'}",
            f"   {item.get('at') or ''}",
        ]
        return "\n".join(lignes)
    section = row["data"]
    lignes = [f"{section['step']}", ""]
    lst_failure = [
        item
        for item in status.failures(dct)
        if (item.get("step") or "") == section["step"]
    ]
    if lst_failure:
        lignes.append(f"❌ {t('Commands that failed')} :")
        for item in lst_failure:
            lignes.append(f"   {item.get('name')}")
        lignes.append("")
    if not section["lst_cmd"]:
        lignes.append(t("No tool has run yet."))
    for cmd in section["lst_cmd"]:
        lignes.append(f"· {cmd}")
    return "\n".join(lignes)


def build_app(dct):
    """Textual est importé ICI, pas au chargement du module.

    Le module reste importable — donc testable — sur une machine sans
    Textual, et c'est aussi ce qui permet à l'appelant de retomber sur le
    rapport texte plutôt que d'échouer.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class StatusApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [("q,escape", "quit", "Quit")]

        def __init__(self, dct):
            super().__init__()
            self.dct = dct
            self.lst_row = rows(dct)
            self.index = 0

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="left", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Footer()

        def on_mount(self):
            self.title = t("Migration state")
            table = self.query_one("#left", DataTable)
            table.add_columns(t("Test results"), "#")
            for row in self.lst_row:
                table.add_row(row["label"][:38], row["detail"])
            self.query_one("#head", Static).update(head_text(self.dct))
            self._show()

        def _show(self):
            row = self.lst_row[self.index] if self.lst_row else None
            self.query_one("#content", Static).update(pane_text(self.dct, row))

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "left" and self.lst_row:
                self.index = event.cursor_row
                self._show()

    return StatusApp(dct)


def run_tui(dct, run_app=True):
    """Ouvrir l'écran. False si l'on n'a pas pu — et alors on DIT pourquoi.

    Se taire ferait réafficher le rapport texte à la place de l'écran
    demandé, sans rien qui distingue les deux.
    """
    if not dct:
        return False
    if not sys.stdout.isatty():
        print(f"ℹ️  {t('Not a terminal: showing the text report instead.')}")
        return False
    try:
        from script.todo import textual_setup
    except Exception:
        textual_setup = None
    if textual_setup and not textual_setup.ensure():
        return False
    try:
        app = build_app(dct)
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
