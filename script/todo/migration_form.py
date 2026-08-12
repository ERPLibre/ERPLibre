#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écran de reprise de migration Odoo, en TUI.

Pendant de `qemu_deploy_form` pour l'outil de migration. Deux interfaces
posent la MÊME première question — « où en est-on, et par où reprend-on ? » —
et renvoient les MÊMES chaînes de réponse (« c », « n », « r », « q »,
« 0 »..« 4 », « 4.<version> ») que `TodoUpgrade.apply_resume_answer` traduit
en progression. La décision est donc écrite une seule fois.

- run_resume_tui(ctx, run_app=True) : renvoie la réponse, ou None pour
  retomber sur les invites en ligne.

`ctx` vient de `TodoUpgrade.resume_context()` : pure donnée, aucun accès à la
base ni au disque depuis l'affichage.
"""
from __future__ import annotations

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def version_line(versions):
    """« 13✓ 14✓ 15 16 17 18 » — l'avancement des montées de version."""
    return "  ".join(
        f"{v['version']}{'✓' if v['done'] else ''}" for v in versions
    )


def next_version(versions):
    """Première version pas encore migrée : celle que « continuer » reprend."""
    for item in versions:
        if not item["done"]:
            return item["version"]
    return None


def run_resume_tui(ctx, run_app: bool = True):
    """Écran de reprise. Renvoie la réponse choisie, ou None si annulé.
    `run_app=False` renvoie l'instance sans la lancer (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        OptionList,
        Static,
    )
    from textual.widgets.option_list import Option

    result = {"answer": None}

    class Resume(App):
        CSS = """
        #head { height: auto; padding: 0 1; color: $text-muted; }
        #steps { height: auto; max-height: 12; border: solid $accent; }
        #bumps { height: auto; max-height: 10; border: solid $panel; }
        .grouptitle { color: $accent; text-style: bold; padding: 1 1 0 1; }
        #actions { height: auto; padding: 1 1 0 1; }
        #hint { height: auto; color: $text-muted; padding: 0 1; }
        """
        BINDINGS = [
            ("c", "cont", t("Continue where it stopped")),
            ("b", "back_step", t("Go back to a step")),
            ("n", "new", t("New migration, erase everything")),
            ("r", "keep_zip", t("Keep the zip only")),
            ("q", "quit_nothing", t("Quit without doing anything")),
            ("escape", "quit_nothing", t("Quit without doing anything")),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(
                f"  {t('File'):<9}: {ctx['file']}\n"
                f"  {t('Database'):<9}: {ctx['database']}"
                f"   ·   {t('Target')} : {ctx['target']}\n"
                f"  {t('Started'):<9}: {ctx['started']}",
                id="head",
            )
            yield Static(f"{t('Steps')}", classes="grouptitle")
            yield DataTable(id="steps")
            if ctx["versions"]:
                yield Static(
                    f"{t('Version bumps')}  ({version_line(ctx['versions'])})",
                    classes="grouptitle",
                )
                yield OptionList(id="bumps")
            with Vertical():
                with Horizontal(id="actions"):
                    yield Button(
                        t("Continue where it stopped"),
                        variant="primary",
                        id="a_cont",
                    )
                    yield Button(t("New migration"), id="a_new")
                    yield Button(t("Go back to a step"), id="a_back")
                    yield Button(t("Keep the zip only"), id="a_keep")
                    yield Button(t("Quit"), id="a_quit")
                yield Static(
                    f"  {t('Enter on a step or a version = replay from there')}"
                    f"   ·   b = {t('Go back to a step')}",
                    id="hint",
                )
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("Migration in progress")
            table = self.query_one("#steps", DataTable)
            table.cursor_type = "row"
            table.add_columns("", "", t("Step"), t("Detail"))
            for item in ctx["steps"]:
                table.add_row(
                    f"[{item['step']}]",
                    item["icon"],
                    item["label"],
                    item["detail"],
                )
            # Curseur sur la première étape inachevée : c'est là que ça a
            # calé, donc là qu'on veut probablement rejouer.
            for index, item in enumerate(ctx["steps"]):
                if item["icon"] != "✅":
                    table.move_cursor(row=index)
                    break
            if ctx["versions"]:
                bumps = self.query_one("#bumps", OptionList)
                for item in ctx["versions"]:
                    mark = "✓" if item["done"] else " "
                    bumps.add_option(
                        Option(
                            f" {mark} Odoo {item['version']}.0 — "
                            f"{t('rebuilds the intermediate database')}",
                            id=str(item["version"]),
                        )
                    )
                upcoming = next_version(ctx["versions"])
                if upcoming is not None:
                    bumps.highlighted = [
                        v["version"] for v in ctx["versions"]
                    ].index(upcoming)

        # -- choix ------------------------------------------------------ #
        def _answer(self, value):
            result["answer"] = value
            self.exit()

        def on_data_table_row_selected(self, event) -> None:
            index = event.cursor_row
            if 0 <= index < len(ctx["steps"]):
                self._answer(str(ctx["steps"][index]["step"]))

        def on_option_list_option_selected(self, event) -> None:
            self._answer(f"4.{event.option.id}")

        def on_button_pressed(self, event) -> None:
            if event.button.id == "a_back":
                self.action_back_step()
                return
            mapping = {
                "a_cont": "c",
                "a_new": "n",
                "a_keep": "r",
                "a_quit": "q",
            }
            value = mapping.get(event.button.id)
            if value:
                self._answer(value)

        def action_back_step(self) -> None:
            """Amener au tableau des étapes, où le choix se fait déjà.

            Le mécanisme existait — Entrée sur une ligne — mais vivait dans une
            ligne d'astuce sous quatre boutons nommés. Une capacité qu'il faut
            deviner n'est pas offerte ; celle-ci porte donc une touche, un
            bouton et un message, comme les autres.
            """
            table = self.query_one("#steps", DataTable)
            table.focus()
            self.notify(t("Choose a step, Enter replays from there."))

        def action_cont(self) -> None:
            self._answer("c")

        def action_new(self) -> None:
            self._answer("n")

        def action_keep_zip(self) -> None:
            self._answer("r")

        def action_quit_nothing(self) -> None:
            self._answer("q")

    app = Resume()
    app._result = result  # lecture par les tests headless
    if not run_app:
        return app
    app.run()
    return result["answer"]
