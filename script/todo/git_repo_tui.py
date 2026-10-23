#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Parcourir ce qu'une mise à niveau apporte, dépôt par dépôt.

Lecture seule, sans exception. Cet écran sert à DÉCIDER, et décider
suppose d'avoir lu : les gestes qui écrivent — rebaser, résoudre, revenir
en arrière — vivent dans le menu, derrière une confirmation.

Le rapport texte dit tout, mais il dit tout d'un coup : sur seize dépôts
et quelques centaines de modules apportés, ce qu'on cherche — quel dépôt
demande une décision, quels modules d'un dépôt ne sont que de la
traduction — se trouve quelque part au milieu. Un écran qui se parcourt
règle exactement cela.

Les données viennent du même diagnostic que le rapport texte. Deux
assemblages séparés dériveraient l'un de l'autre sans que rien ne le dise,
et l'on finirait par lire deux états contradictoires de la même passe.
"""

import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


CSS = """
Screen { layout: vertical; }
#head { height: 4; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#depots { width: 46; border-right: solid $accent; }
#detail { width: 1fr; }
"""

# L'ordre de lecture : ce qui demande une décision d'abord, ce qui n'en
# demande pas ensuite. Un écran trié par nom de dépôt obligerait à parcourir
# les quinze dépôts sans objet pour trouver le seul qui compte.
ORDRE = {
    "en_conflit": 0,
    "absorbe": 1,
    "a_rebaser": 2,
    "en_retard": 3,
    "non_comparable": 4,
    "a_jour": 5,
}

ICONES = {
    "en_conflit": "🔴",
    "absorbe": "🟠",
    "a_rebaser": "🟢",
    "en_retard": "🔵",
    "non_comparable": "⚪",
    "a_jour": "⚫",
}


def lignes(lst):
    """Les dépôts dans l'ordre où on veut les lire."""
    return sorted(
        lst, key=lambda x: (ORDRE.get(x.get("verdict"), 9), x.get("chemin"))
    )


def resume(constat):
    """Les trois chiffres qui situent un dépôt : à nous, à eux, en conflit."""
    return (
        f"+{constat.get('nos', 0)}",
        f"−{constat.get('amont_avance', 0)}",
        str(len(constat.get("conflits") or [])),
    )


def detail(constat):
    """Le panneau de droite : ce qu'il faut savoir avant de trancher.

    Les modules apportés ne sont pas listés en entier — quelques centaines
    sur un dépôt d'addons. Le COMPTE des deux classes suffit à décider, et
    la liste nominative se lit dans le rapport texte.
    """
    lignes_detail = []
    amont = constat.get("amont") or {}
    lignes_detail.append(f"{constat.get('chemin')}")
    lignes_detail.append(
        f"{t('upstream')} : {amont.get('url') or '—'}"
        f" @ {amont.get('branche') or '—'}"
    )
    if constat.get("motif"):
        lignes_detail.append(f"⚠  {constat['motif']}")
    lignes_detail.append("")

    commits = constat.get("commits") or []
    if commits:
        lignes_detail.append(f"── {t('Our commits')} ({len(commits)}) ──")
        for court, sujet in commits:
            lignes_detail.append(f"  {court}  {sujet}")
        lignes_detail.append("")

    repris = constat.get("modules_repris") or []
    if repris:
        lignes_detail.append(f"── {t('upstream now carries')} ──")
        for module in repris:
            lignes_detail.append(f"  {module}")
        lignes_detail.append("")

    conflits = constat.get("conflits") or []
    if conflits:
        lignes_detail.append(
            f"── {t('conflicting files')} ({len(conflits)}) ──"
        )
        for fichier in conflits[:40]:
            lignes_detail.append(f"  {fichier}")
        if len(conflits) > 40:
            lignes_detail.append(f"  … {len(conflits) - 40}")
        lignes_detail.append("")

    stats = constat.get("stats_amont")
    if stats:
        doc = len(constat.get("modules_amont_doc") or [])
        code = len(constat.get("modules_amont_code") or [])
        lignes_detail.append(f"── {t('What upstream brings')} ──")
        lignes_detail.append(
            f"  {t('Modules touched')} {doc + code} · "
            f"{t('Documentation and translation only')} {doc} · "
            f"{t('Contains code')} {code}"
        )
        for nom, valeur in list(stats.get("langages", {}).items())[:10]:
            lignes_detail.append(
                f"  {nom:22s} +{valeur['ajouts']} −{valeur['retraits']}"
            )
    return "\n".join(lignes_detail)


def build_app(data):
    """Construire l'application Textual. Importe Textual seulement ici.

    L'import vit dans la fonction pour que le module reste importable — et
    donc testable — sur une machine sans Textual.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class GitRepoApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("f", "filtrer", t("Only what needs a decision")),
            ("c", "copy", t("Copy")),
        ]

        def __init__(self, data):
            super().__init__()
            self.version = data.get("version") or "?"
            self.tout = lignes(data.get("forks") or [])
            self.filtre = False
            self.intent = None

        @property
        def visibles(self):
            if not self.filtre:
                return self.tout
            return [
                x
                for x in self.tout
                if x.get("verdict") in ("en_conflit", "absorbe", "a_rebaser")
            ]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="depots", cursor_type="row")
                with VerticalScroll(id="detail"):
                    yield Static("", id="corps")
            yield Footer()

        def on_mount(self):
            self.title = f"{t('Upgrade dry run')} — Odoo {self.version}"
            table = self.query_one("#depots", DataTable)
            table.add_columns(t("repository"), "+", "−", "⚠")
            self._remplir()

        def _remplir(self):
            table = self.query_one("#depots", DataTable)
            table.clear()
            for constat in self.visibles:
                icone = ICONES.get(constat.get("verdict"), " ")
                nom = (constat.get("chemin") or "").split("/")[-1]
                table.add_row(f"{icone} {nom[:30]}", *resume(constat))
            self._montrer(0)

        def _montrer(self, index):
            lst = self.visibles
            corps = self.query_one("#corps", Static)
            if not lst:
                corps.update(t("Nothing to show."))
                self.query_one("#head", Static).update("")
                return
            constat = lst[min(index, len(lst) - 1)]
            self.query_one("#head", Static).update(
                f"{constat.get('chemin')}\n"
                f"{t(constat.get('verdict') or '')}"
                f"   ·   {len(lst)}/{len(self.tout)} {t('shown')}"
            )
            corps.update(detail(constat))

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "depots":
                self._montrer(event.cursor_row)

        def action_filtrer(self):
            self.filtre = not self.filtre
            self._remplir()

        def action_copy(self):
            lst = self.visibles
            if not lst:
                return
            table = self.query_one("#depots", DataTable)
            texte = detail(lst[min(table.cursor_row, len(lst) - 1)])
            self.copy_to_clipboard(texte[-100_000:])
            self.notify(t("Copied."))

    return GitRepoApp(data)


def run_git_repo_tui(data, run_app=True):
    """Ouvrir l'écran. Rend l'intention retenue, ou None.

    ``run_app=False`` construit l'application sans la lancer : c'est ce qui
    permet de la tester sans terminal.
    """
    app = build_app(data)
    if not run_app:
        return app
    app.run()
    return app.intent
