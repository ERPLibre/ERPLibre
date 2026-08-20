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
        # Le précédent voyage avec la ligne : le panneau en a besoin pour
        # écrire « 171 (−43) », et le recalculer là-bas ferait deux
        # sources pour la même comparaison.
        # La colonne compte les pertes INEXPLIQUÉES : afficher 81 quand
        # 79 sont des refontes voulues par Odoo ferait fuir le lecteur du
        # seul chiffre qui demande une réponse.
        perdu = (
            0
            if diff is None or diff.get("unavailable")
            else len([item for item in diff["rows_lost"] if not item[3]])
        )
        lst.append(
            {
                "kind": "step",
                "label": f"{etat['odoo']:<6} {etat['database'][:24]}",
                "detail": str(perdu) if perdu else "",
                "data": etat,
                "diff": diff,
                "previous": precedent,
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


def statistics(etat, precedent):
    """[(libellé, valeur, écart)] pour un palier. L'écart est None au départ.

    Un chiffre seul ne dit rien : 2283 vues est un nombre, « +61 » est une
    information. Le premier palier n'a pas de précédent, et inventer un
    écart de zéro y laisserait croire à une comparaison qui n'existe pas.
    """
    lst = [
        (
            t("modules"),
            len(etat["installed"]),
            None if not precedent else len(precedent["installed"]),
        ),
        (
            t("models"),
            len(etat["model"]),
            None if not precedent else len(precedent["model"]),
        ),
        (
            t("views"),
            etat["view"],
            None if not precedent else precedent["view"],
        ),
        (
            "  · COW",
            etat["view_cow"],
            None if not precedent else precedent["view_cow"],
        ),
        (
            t("menus"),
            etat["menu"],
            None if not precedent else precedent["menu"],
        ),
        (
            t("attachments"),
            etat["attachment"],
            None if not precedent else precedent["attachment"],
        ),
    ]
    return [
        (libelle, valeur, None if avant is None else valeur - avant)
        for libelle, valeur, avant in lst
    ]


def pane_text(lst_snapshot, row, colour=False, mode=None):
    """Le détail du palier choisi, ou le bilan d'ensemble.

    UN seul mode, et non deux drapeaux : « montre les fichiers absents »
    et « montre la liste des modèles » ne peuvent pas être vrais en même
    temps, et deux booléens laissaient écrire cet état impossible.
    """
    if row is None:
        return t("Nothing to show yet.")
    if row["kind"] == "missing":
        return f"⚠️  {row['data']['database']} : {t('database not found')}"
    etat = row["data"]
    if mode == "missing":
        if not etat:
            return t("Pick a step to see its missing files.")
        return quality.render_missing(etat, colour)
    if mode in quality.DETAILS:
        return quality.render_detail(row.get("diff"), mode, colour)
    lignes = []
    if etat:
        lignes.append(
            status.paint(f"{etat['odoo']}  {etat['database']}", "step", colour)
        )
        lignes.append("")
        for libelle, valeur, ecart in statistics(etat, row.get("previous")):
            if ecart is None:
                marque = ""
            else:
                marque = status.paint(
                    f"{ecart:+d}", "ok" if ecart >= 0 else "warn", colour
                )
            lignes.append(f"   {libelle:<28} {valeur:>7}   {marque}")
        if etat.get("attachment_missing"):
            lignes.append(
                "   "
                + status.paint(
                    f"❌ {etat['attachment_missing']}"
                    f" {t('attachment files missing from the filestore')}",
                    "fail",
                    colour,
                )
            )
            lignes.append(f"      {t('press m to list them')}")
        lignes.append("")
    diff = row.get("diff")
    if diff:
        lignes.extend(quality.render_compare(diff, colour, limit=40))
    return "\n".join(lignes)


def mode_label(mode):
    """Le nom du mode courant, pour le sous-titre.

    Un panneau qui change de contenu sans dire pourquoi se lit comme un
    écran cassé — et avec sept modes, on ne devine pas.
    """
    if mode is None:
        return t("summary")
    if mode == "missing":
        return t("Missing files")
    return t(mode)


def build_app(lst_snapshot):
    """Textual est importé ICI : le module reste testable sans lui."""
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class QualityApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("m", "toggle_missing", t("Missing files")),
            ("d", "cycle_detail", t("Details")),
        ]

        def __init__(self, lst_snapshot):
            super().__init__()
            self.lst_snapshot = lst_snapshot
            self.lst_row = rows(lst_snapshot)
            self.index = 0
            self.mode = None

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
            self.sub_title = mode_label(self.mode)
            row = (
                self.lst_row[self.index]
                if self.lst_row and self.index < len(self.lst_row)
                else None
            )
            self.query_one("#content", Static).update(
                Text.from_ansi(
                    pane_text(
                        self.lst_snapshot,
                        row,
                        colour=True,
                        mode=self.mode,
                    )
                )
            )

        def action_toggle_missing(self):
            """Basculer entre les chiffres du palier et ses fichiers absents.

            Les métadonnées ne sont lues qu'ICI : une requête de plus par
            base allongerait un parcours qui tient en quatre secondes, pour
            une information qu'on ne regarde qu'en la demandant.
            """
            self.mode = None if self.mode == "missing" else "missing"
            self._show()

        def action_cycle_detail(self):
            """Parcourir les listes ENTIÈRES, une catégorie à la fois.

            Le résumé coupe à huit entrées et il a raison ; mais quand on
            cherche si UN module précis a survécu, la liste tronquée ne
            répond pas. On enchaîne donc résumé → modules → modèles →
            champs → copies COW → tables, et l'on revient.
            """
            suite = (None,) + quality.DETAILS
            courant = self.mode if self.mode in suite else None
            self.mode = suite[(suite.index(courant) + 1) % len(suite)]
            self._show()

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
