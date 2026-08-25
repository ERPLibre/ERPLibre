# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Demander quelle auscultation lancer — et rien d'autre.

Cet écran ne CONTIENT aucune analyse. Il en choisit une, se referme, et
rend la clé choisie ; l'appelant lance ensuite l'outil, qui dispose alors
du terminal entier et peut ouvrir sa propre TUI.

Deux raisons, toutes deux mesurées dans ce dépôt. `run_tui` refuse de
s'ouvrir quand une boucle asyncio tourne déjà — un écran qui en ouvrirait
un autre afficherait « open it in its own process instead » et rien
d'autre. Et une analyse lourde appelée depuis un gestionnaire de touche
bloque la boucle d'événements : plus de rafraîchissement, plus de frappe,
un écran qui paraît planté pendant des minutes.

Les analyses que la provenance ne permet pas restent AFFICHÉES, grisées,
avec la raison. Les retirer laisserait croire qu'elles n'existent pas ;
les proposer les ferait échouer à l'ouverture.
"""

from __future__ import annotations

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import monitoring  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#left { width: 52; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
.off { color: $text-disabled; }
"""


def rows(kind):
    """Les lignes de l'écran : (clé, étiquette, utilisable, raison).

    Fonction pure, et c'est délibéré — c'est elle qui décide ce qu'on peut
    lancer, et une décision qui ne se teste qu'en ouvrant un terminal ne
    se teste pas.
    """
    lignes = []
    for analyse in monitoring.ANALYSES:
        utilisable = kind in analyse["kinds"]
        lignes.append(
            (
                analyse["key"],
                t(analyse["title"]),
                utilisable,
                "" if utilisable else t(analyse["needs_sql"]),
            )
        )
    return lignes


def detail(key, kind):
    """Le texte du panneau de droite pour cette analyse."""
    analyse = monitoring.analysis_by_key(key)
    if not analyse:
        return ""
    morceaux = [t(analyse["title"]), "", t(analyse["why"]), ""]
    if kind in analyse["kinds"]:
        morceaux.append(f"▶ {t('Enter to run it.')}")
    else:
        morceaux.append(f"✖ {t('Not available for this source.')}")
        morceaux.append(f"   {t(analyse['needs_sql'])}")
    morceaux.append("")
    morceaux.append(f"   {analyse['script']}")
    return "\n".join(morceaux)


def build_app(kind, target):
    """Construire l'écran. ImportError si Textual manque — l'appelant le dit."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import Footer, Header, ListItem, ListView, Static

    lignes = rows(kind)

    class MonitoringChooser(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("enter", "choose", t("Run")),
            ("q", "quit", t("Quit")),
            ("escape", "quit", t("Quit")),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(monitoring.describe_source(kind, target), id="head")
            with Horizontal(id="body"):
                items = []
                for key, label, utilisable, _ in lignes:
                    marque = "  " if utilisable else "✖ "
                    item = ListItem(Static(f"{marque}{label}"))
                    if not utilisable:
                        item.add_class("off")
                    items.append(item)
                yield ListView(*items, id="left")
                yield Static("", id="pane")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#left", ListView).focus()
            self._refresh_pane(0)

        def _refresh_pane(self, index) -> None:
            if 0 <= index < len(lignes):
                self.query_one("#pane", Static).update(
                    detail(lignes[index][0], kind)
                )

        def on_list_view_selected(self, event) -> None:
            # `ListView` consomme Entrée pour émettre `Selected` : la
            # liaison de l'application ne la voit jamais. Sans ceci,
            # l'écran ne répondait pas à Entrée — et aucune fonction pure
            # ne pouvait le montrer.
            self.action_choose()

        def on_list_view_highlighted(self, event) -> None:
            self._refresh_pane(self.query_one("#left", ListView).index or 0)

        def action_choose(self) -> None:
            index = self.query_one("#left", ListView).index
            if index is None or not (0 <= index < len(lignes)):
                return
            key, _, utilisable, raison = lignes[index]
            if not utilisable:
                # Refuser en le DISANT : un Entrée sans effet se lit comme
                # un écran figé, et l'on appuie plus fort.
                self.query_one("#pane", Static).update(
                    f"✖ {t('Not available for this source.')}\n\n   {raison}"
                )
                return
            self.exit(key)

    return MonitoringChooser()


def in_event_loop():
    """Une boucle asyncio tourne-t-elle déjà dans CE processus ?"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_tui(kind, target, run_app=True):
    """Ouvrir le choix. Rendre la clé choisie, ou None — en disant pourquoi."""
    try:
        from script.todo import textual_setup
    except Exception:  # pragma: no cover - repli si l'aide manque
        textual_setup = None
    if textual_setup and not textual_setup.ensure():
        return None
    try:
        app = build_app(kind, target)
    except ImportError:
        print(
            f"ℹ️  {t('Textual is missing from this interpreter:')}"
            f" {sys.executable}"
        )
        return None
    if not run_app:
        return app
    if in_event_loop():
        print(
            f"ℹ️  {t('Already inside a running screen: open it in its own')}"
            f" {t('process instead.')}"
        )
        return None
    return app.run()
