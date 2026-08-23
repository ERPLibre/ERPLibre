# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modules d'une base et leurs dépendances, en plein écran.

Une base porte trois à six cents modules. Le rapport texte les liste tous
et la question qu'on se pose — « celui-ci, qui en dépend » — se trouve
quelque part au milieu de plusieurs milliers de lignes.

Les données viennent de `check_module_dependency`, comme le rapport
texte : un seul assemblage, donc une seule vérité sur la même base.
"""

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import check_module_dependency as dependency  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#left { width: 46; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
#find { display: none; }
#find.visible { display: block; }
"""


def filter_label(filtre):
    return {
        "all": t("all modules"),
        "installed": t("installed only"),
        "absent": t("not installed"),
        "broken": t("broken dependencies"),
    }.get(filtre, filtre)


def mode_label(mode):
    """Le nom du mode courant, pour le sous-titre.

    Un panneau qui change sans dire pourquoi se lit comme un écran cassé.
    """
    if mode is None:
        return t("summary")
    return t(dependency.TITRE_DETAIL.get(mode, mode))


def subtitle(mode, filtre, motif):
    morceaux = [mode_label(mode), filter_label(filtre)]
    if motif:
        morceaux.append(f"« {motif} »")
    return "  ·  ".join(morceaux)


def matching(lst_row, motif):
    """Les lignes dont le nom contient `motif`, sans égard à la casse."""
    if not motif:
        return lst_row
    bas = motif.lower()
    return [row for row in lst_row if bas in row["name"].lower()]


def next_mode(mode):
    """Le mode suivant : résumé → les quatre relations → résumé."""
    suite = (None,) + dependency.DETAILS
    courant = mode if mode in suite else None
    return suite[(suite.index(courant) + 1) % len(suite)]


def next_filter(filtre):
    """Le filtre suivant, en boucle."""
    suite = dependency.FILTRES
    index = suite.index(filtre) if filtre in suite else 0
    return suite[(index + 1) % len(suite)]


def current_name(lst_row, index):
    """Le module sous le curseur, ou None si la liste est vide.

    `index` peut dépasser : la table garde son curseur d'avant quand la
    liste raccourcit, et lire hors bornes ferait tomber l'écran sur une
    IndexError au moment précis où l'on filtre.
    """
    if not lst_row or index is None or not 0 <= index < len(lst_row):
        return None
    return lst_row[index]["name"]


def cursor_for(lst_row, garde):
    """Où replacer le curseur pour retrouver `garde`. None si parti.

    Changer de filtre ramenait le curseur en tête, donc on perdait le
    module qu'on lisait — c'est-à-dire la raison même du filtre.
    """
    if not garde:
        return None
    for index, row in enumerate(lst_row):
        if row["name"] == garde:
            return index
    return None


def populate(table, lst_row, garde=None):
    """Remplir la table, puis y remettre le curseur sur `garde`.

    Prend la table plutôt que l'App : rien ici ne dépend de Textual sauf
    trois appels de méthode, donc un faux objet suffit à l'éprouver.
    """
    table.clear()
    for row in lst_row:
        table.add_row(row["label"][:40], row["detail"])
    place = cursor_for(lst_row, garde)
    if place is not None:
        table.move_cursor(row=place)
    return place


def hide_find(champ, table):
    """Refermer la recherche et rendre le clavier à la liste.

    Le `focus()` explicite n'est pas une précaution : sans lui, Textual
    donne le clavier au premier widget focalisable, et c'est le champ de
    recherche — « display: none » ne le retire pas de ce choix-là. On
    ouvrait donc l'écran en tapant dans une boîte invisible, et « d » ne
    faisait rien. (La TABULATION, elle, saute bien un widget caché :
    mesuré, d'où l'absence de `can_focus` ici — une ligne qu'on ne peut
    pas faire échouer n'a rien à faire dans le fichier.)

    Ne vide PAS le champ : l'appelant décide s'il efface le motif, et
    c'est cet effacement qui redéclenche le filtrage.
    """
    champ.remove_class("visible")
    table.focus()


def build_app(rapport):
    """Textual est importé ICI : le module reste testable sans lui."""
    from rich.text import Text
    from textual import on
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Input, Static

    class DependencyApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q", "quit", t("Quit")),
            ("escape", "leave", t("Quit")),
            ("d", "cycle_detail", t("Dependencies")),
            ("f", "cycle_filter", t("Filter")),
            ("slash", "find", t("Search")),
        ]

        def __init__(self, rapport):
            super().__init__()
            self.rapport = rapport
            self.mode = None
            self.filtre = "all"
            self.motif = ""
            self.lst_row = []

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="left", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Input(placeholder=t("module name…"), id="find")
            yield Footer()

        def on_mount(self):
            self.title = t("Modules and their dependencies")
            table = self.query_one("#left", DataTable)
            table.add_columns(t("module"), "↓↑")
            hide_find(self.query_one("#find", Input), table)
            self.query_one("#head", Static).update(
                dependency.head_text(self.rapport)
            )
            self._fill()

        def _fill(self):
            """Reconstruire la liste, en gardant le module sous le curseur.

            Sans cela, changer de filtre ramène le curseur en tête et l'on
            perd le module qu'on était en train de lire — c'est-à-dire la
            raison pour laquelle on a filtré.
            """
            garde = self._current_name()
            self.lst_row = matching(
                dependency.rows(self.rapport, self.filtre), self.motif
            )
            populate(self.query_one("#left", DataTable), self.lst_row, garde)
            self._show()

        def _current_name(self):
            table = self.query_one("#left", DataTable)
            return current_name(self.lst_row, table.cursor_row)

        def _show(self):
            self.sub_title = subtitle(self.mode, self.filtre, self.motif)
            self.query_one("#content", Static).update(
                Text.from_ansi(
                    dependency.pane_text(
                        self.rapport,
                        self._current_name(),
                        mode=self.mode,
                        colour=True,
                    )
                )
            )

        def action_cycle_detail(self):
            """Parcourir les quatre relations, puis revenir au résumé.

            « ce dont il dépend » et « ce qui en dépend » répondent à deux
            questions opposées, et les fermetures disent l'ampleur réelle :
            retirer un module en entraîne parfois trente.
            """
            self.mode = next_mode(self.mode)
            self._show()

        def action_cycle_filter(self):
            self.filtre = next_filter(self.filtre)
            self._fill()

        def action_find(self):
            champ = self.query_one("#find", Input)
            champ.add_class("visible")
            champ.focus()

        def action_leave(self):
            """Échap referme la recherche ; il ne quitte que sinon.

            Quitter parce qu'on renonce à une recherche serait une
            surprise coûteuse : on a parfois filtré trois mille modules
            pour arriver là.
            """
            champ = self.query_one("#find", Input)
            if not champ.has_class("visible"):
                self.exit()
                return
            # Vider le champ suffit à tout refaire : l'événement
            # `Input.Changed` remet le motif à zéro et reconstruit la
            # liste. Le refaire ici à la main donnerait deux chemins pour
            # le même état, dont un seul serait jamais éprouvé.
            champ.value = ""
            hide_find(champ, self.query_one("#left", DataTable))

        @on(Input.Changed, "#find")
        def _find_changed(self, event):
            self.motif = event.value.strip()
            self._fill()

        @on(Input.Submitted, "#find")
        def _find_submitted(self, event):
            # Le champ reste VISIBLE : il porte le motif en cours, et le
            # cacher laisserait une liste filtrée sans dire par quoi.
            self.query_one("#left", DataTable).focus()

        @on(DataTable.RowHighlighted, "#left")
        def _row_changed(self, event):
            self._show()

    return DependencyApp(rapport)


def in_event_loop():
    """Une boucle asyncio tourne-t-elle déjà dans CE processus ?"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_tui(rapport, run_app=True):
    """Ouvrir l'écran. False si l'on n'a pas pu — et alors on DIT pourquoi."""
    if not rapport or rapport.get("unavailable"):
        return False
    if not rapport.get("modules"):
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
        app = build_app(rapport)
    except ImportError:
        print(
            f"ℹ️  {t('Textual is missing from this interpreter:')}"
            f" {sys.executable}"
        )
        return False
    if not run_app:
        return app
    if in_event_loop():
        print(
            f"ℹ️  {t('Already inside a running screen: open it in its own')}"
            f" {t('process instead.')}"
        )
        return False
    app.run()
    return True
