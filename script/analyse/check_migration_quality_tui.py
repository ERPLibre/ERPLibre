# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La qualité d'une migration, palier par palier, en plein écran.

Le rapport texte dit tout d'un coup : sur six paliers il fait plusieurs
centaines de lignes, et ce qu'on cherche — quel palier a perdu quoi — se
trouve quelque part au milieu. Un écran qui se parcourt règle cela.

Les données viennent de `check_migration_quality`, comme le rapport texte.
Deux assemblages sépareraient les deux vues, et l'on finirait par lire deux
états contradictoires de la même migration.
"""

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import check_migration_quality as quality  # noqa: E402
from script.todo import migration_status as status  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#left { width: 40; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def rows(lst_snapshot):
    """Un palier par ligne, puis le bilan d'ensemble en dernier.

    Le bilan EN DERNIER et non en tête : on descend la liste comme on a
    vécu la migration, et la question « qu'est-ce qu'il en reste » se pose
    une fois qu'on a vu le chemin.
    """
    lst = []
    presents = [x for x in lst_snapshot if x.get("exists")]
    for index, etat in enumerate(lst_snapshot):
        if not etat.get("exists"):
            lst.append(
                {
                    "kind": "missing",
                    "label": f"⚠️ {etat['database'][:30]}",
                    "detail": "",
                    "data": etat,
                }
            )
            continue
        precedent = None
        rang = presents.index(etat)
        if rang:
            precedent = presents[rang - 1]
        diff = quality.compare(precedent, etat) if precedent else None
        perdu = (
            0
            if diff is None or diff.get("unavailable")
            else len(diff["rows_lost"])
        )
        lst.append(
            {
                "kind": "step",
                "label": f"{etat['odoo']:<6} {etat['database'][:24]}",
                "detail": str(perdu) if perdu else "",
                "data": etat,
                "diff": diff,
            }
        )
    if len(presents) >= 2:
        lst.append(
            {
                "kind": "overall",
                "label": f"🏁 {presents[0]['odoo']} → {presents[-1]['odoo']}",
                "detail": "",
                "data": None,
                "diff": quality.overall(lst_snapshot),
            }
        )
    return lst


def head_text(lst_snapshot):
    presents = [x for x in lst_snapshot if x.get("exists")]
    manquants = len(lst_snapshot) - len(presents)
    if not presents:
        return t("No migration in progress.")
    return (
        f"{presents[0]['database']}  ·  {len(presents)} {t('steps')}"
        f"  ·  {presents[0]['odoo']} → {presents[-1]['odoo']}"
        + (
            f"  ·  ⚠️ {manquants} {t('database not found')}"
            if manquants
            else ""
        )
    )


def pane_text(lst_snapshot, row, colour=False):
    """Le détail du palier choisi, ou le bilan d'ensemble."""
    if row is None:
        return t("Nothing to show yet.")
    if row["kind"] == "missing":
        return f"⚠️  {row['data']['database']} : {t('database not found')}"
    lignes = []
    etat = row["data"]
    if etat:
        lignes.append(
            status.paint(f"{etat['odoo']}  {etat['database']}", "step", colour)
        )
        lignes.append("")
        for libelle, valeur in (
            (t("modules"), len(etat["installed"])),
            (t("models"), len(etat["model"])),
            (t("views"), etat["view"]),
            ("  · COW", etat["view_cow"]),
            (t("menus"), etat["menu"]),
            (t("attachments"), etat["attachment"]),
        ):
            lignes.append(f"   {libelle:<28} {valeur:>7}")
        if etat.get("attachment_missing"):
            lignes.append(
                f"   {status.paint('❌ ' + t('attachment files missing from'
                                            ' the filestore'), 'fail', colour)}"
                f" {etat['attachment_missing']}"
            )
        lignes.append("")
    diff = row.get("diff")
    if diff:
        lignes.extend(quality.render_compare(diff, colour, limit=40))
    return "\n".join(lignes)


def build_app(lst_snapshot):
    """Textual est importé ICI : le module reste testable sans lui."""
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class QualityApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [("q,escape", "quit", t("Quit"))]

        def __init__(self, lst_snapshot):
            super().__init__()
            self.lst_snapshot = lst_snapshot
            self.lst_row = rows(lst_snapshot)
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
            self.title = t("Migration quality, step by step")
            table = self.query_one("#left", DataTable)
            table.add_columns(t("steps"), "▼")
            for row in self.lst_row:
                table.add_row(row["label"][:34], row["detail"])
            self.query_one("#head", Static).update(
                head_text(self.lst_snapshot)
            )
            self._show()

        def _show(self):
            row = (
                self.lst_row[self.index]
                if self.lst_row and self.index < len(self.lst_row)
                else None
            )
            self.query_one("#content", Static).update(
                Text.from_ansi(pane_text(self.lst_snapshot, row, colour=True))
            )

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "left" and self.lst_row:
                self.index = event.cursor_row
                self._show()

    return QualityApp(lst_snapshot)


def run_tui(lst_snapshot, run_app=True):
    """Ouvrir l'écran. False si l'on n'a pas pu — et alors on DIT pourquoi."""
    if not lst_snapshot:
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
        app = build_app(lst_snapshot)
    except ImportError:
        print(
            f"ℹ️  {t('Textual is missing from this interpreter:')}"
            f" {sys.executable}"
        )
        return False
    if not run_app:
        return app
    if in_event_loop():
        # Filet de sécurité : `app.run()` appelle `asyncio.run()`, qui
        # lève dans une boucle déjà en cours. Le dire vaut mieux que la
        # trace de quarante lignes que cela produit — et l'appelant doit
        # passer par un sous-processus.
        print(
            f"ℹ️  {t('Already inside a running screen: open it in its own')}"
            f" {t('process instead.')}"
        )
        return False
    app.run()
    return True


def in_event_loop():
    """Une boucle asyncio tourne-t-elle déjà dans CE processus ?"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True
