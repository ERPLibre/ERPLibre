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
        f"{t('finished')} : {info['updated']}"
        f"   ·   {t('duration')} {info['elapsed']}"
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
        # Le NUMÉRO de l'étape en tête : une migration lance le même outil
        # à chaque palier, et sans lui la liste montrait six lignes
        # identiques sans dire laquelle appartenait à quel palier.
        numero = (item.get("step") or "").split(" - ")[0]
        tete = f"{numero} " if numero else ""
        lst.append(
            {
                "kind": "test",
                "label": f"{icone} {tete}{item['name']}",
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


def pane_text(dct, row, colour=False, show_log=True):
    """Le détail de la ligne choisie.

    Le coloriage passe par de l'ANSI, que Rich sait décoder — et qui rend
    au passage le texte LITTÉRAL : une commande contenant « [1] » était
    jusqu'ici prise pour du balisage Rich et avalée sans un mot.
    """
    if row is None:
        return t("Nothing to show yet.")
    if row["kind"] == "test":
        item = row["data"]
        icone, phrase = status.verdict(item.get("status"))
        teinte = status.VERDICT_COLOUR.get(item.get("status"), "dim")
        lignes = [
            f"{icone} {status.paint(item['name'], teinte, colour)}",
            f"   {status.paint(item.get('step') or '?', 'step', colour)}",
            f"   {phrase}  ({t('exit code')} {item.get('status')})",
            f"   {t('runs')} : {item.get('runs')}",
            f"   {item.get('at') or ''}",
        ]
        return "\n".join(lignes)
    section = row["data"]
    lignes = [status.paint(section["step"], "step", colour), ""]
    lst_failure = [
        item
        for item in status.failures(dct)
        if (item.get("step") or "") == section["step"]
    ]
    if lst_failure:
        lignes.append(f"❌ {t('Commands that failed')} :")
        for item in lst_failure:
            lignes.append(
                f"   {status.paint(item.get('name') or '', 'fail', colour)}"
            )
        lignes.append("")
    for cmd in section["lst_cmd"]:
        lignes.append(f"· {status.paint(cmd, 'cmd', colour)}")
    # La SORTIE des commandes, relue sur disque. C'est ce qui manquait :
    # la liste des commandes dit ce qui a été lancé, jamais ce que cela a
    # répondu. Mais les deux mélangés dans un même panneau se confondent —
    # d'où « l », qui les sépare.
    tail, total = status.step_log_tail(dct, section["step"])
    if not show_log:
        if total:
            lignes.append("")
            lignes.append(
                f"── {t('server log')} : {total} {t('lines')}"
                f" ({t('press l to show')}) ──"
            )
        return "\n".join(lignes)
    if tail:
        lignes.append("")
        cache = (
            f" — {t('last')} {len(tail)} {t('of')} {total}"
            if total > len(tail)
            else ""
        )
        lignes.append(f"── {t('server log')}{cache} ──")
        lignes.extend(tail)
    elif not section["lst_cmd"]:
        lignes.append(t("No tool has run yet."))
    return "\n".join(lignes)


def build_app(dct, path=None):
    """Textual est importé ICI, pas au chargement du module.

    Le module reste importable — donc testable — sur une machine sans
    Textual, et c'est aussi ce qui permet à l'appelant de retomber sur le
    rapport texte plutôt que d'échouer.
    """
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class StatusApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("r", "refresh", t("Refresh")),
            ("l", "toggle_log", t("Logs")),
            ("p", "toggle_head", t("Panel")),
            ("plus,equal", "wider", t("Wider")),
            ("minus,underscore", "narrower", t("Narrower")),
        ]

        LEFT_MIN = 16
        LEFT_MAX = 110
        LEFT_STEP = 6

        def __init__(self, dct, path=None):
            super().__init__()
            self.dct = dct
            self.path = path
            self.lst_row = rows(dct)
            self.index = 0
            self.show_log = True
            self.left_width = 46

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
            self._fill_table()
            self._show()

        def _fill_table(self):
            table = self.query_one("#left", DataTable)
            table.clear(columns=True)
            table.add_columns(t("Test results"), "#")
            for row in self.lst_row:
                table.add_row(row["label"][:38], row["detail"])
            table.styles.width = self.left_width
            self.query_one("#head", Static).update(head_text(self.dct))

        def _show(self):
            row = self.lst_row[self.index] if self.lst_row else None
            # `from_ansi` fait DEUX choses : il rend les couleurs, et il
            # traite le reste comme du texte LITTÉRAL. Sans lui, une
            # commande contenant « [1] » passait pour du balisage Rich et
            # disparaissait de l'écran sans que rien ne le signale.
            self.query_one("#content", Static).update(
                Text.from_ansi(
                    pane_text(
                        self.dct, row, colour=True, show_log=self.show_log
                    )
                )
            )

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "left" and self.lst_row:
                self.index = event.cursor_row
                self._show()

        def action_refresh(self):
            """Relire le disque. La migration écrit PENDANT qu'on regarde.

            L'écran s'ouvre au milieu d'une migration qui continue : sans
            cela, il fallait le fermer et le rouvrir pour voir le palier
            suivant.
            """
            if not self.path:
                return
            self.dct = status.read(self.path)
            self.lst_row = rows(self.dct)
            self.index = min(self.index, max(0, len(self.lst_row) - 1))
            self._fill_table()
            self._show()

        def action_toggle_log(self):
            self.show_log = not self.show_log
            self._show()

        def action_toggle_head(self):
            head = self.query_one("#head", Static)
            head.display = not head.display

        def action_wider(self):
            self._resize(self.LEFT_STEP)

        def action_narrower(self):
            self._resize(-self.LEFT_STEP)

        def _resize(self, delta):
            # Bornée des deux côtés : une colonne de zéro ne se retrouve
            # plus, et une qui mange tout l'écran ne laisse rien à lire.
            self.left_width = max(
                self.LEFT_MIN, min(self.LEFT_MAX, self.left_width + delta)
            )
            self.query_one("#left", DataTable).styles.width = self.left_width

    return StatusApp(dct, path)


def run_tui(dct, run_app=True, path=None):
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
        app = build_app(dct, path=path)
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
