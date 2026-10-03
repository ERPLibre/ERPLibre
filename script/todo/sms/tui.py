#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Tableau de bord de la démonstration SMS.

Une table d'étapes à gauche de leur journal, la touche `r` pour rejouer celle
qu'on a sélectionnée. C'est la même vérité que le menu en ligne — `steps` et
`spec` sont partagés — affichée autrement.

Deux contraintes ont façonné ce fichier :

- L'étape « VM » ouvre SON PROPRE tableau de bord Textual, et deux
  applications Textual ne peuvent pas cohabiter dans un terminal. On lui rend
  donc la main par `suspend()` au lieu de l'exécuter dans un fil.
- Les autres étapes durent des minutes. Elles tournent dans un fil, et TOUTE
  écriture dans l'interface repasse par `call_from_thread` : y toucher
  directement depuis le fil corrompt le rendu.
"""
from __future__ import annotations

from script.todo.sms import menu as menu_mod
from script.todo.sms import spec as spec_mod
from script.todo.sms import steps as steps_mod
from script.todo.sms.steps import ICON, STEPS

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def run_sms_tui(todo, run_app: bool = True):
    """Ouvre le tableau de bord.

    `run_app=False` construit l'application sans la lancer, pour qu'un test
    puisse l'inspecter sans terminal — convention des autres TUI du dépôt.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import DataTable, Footer, Header, RichLog, Static

    class Dashboard(App):
        CSS = """
        #resume { height: auto; padding: 0 1; color: $text-muted; }
        #steps { width: 46%; border: solid $accent; }
        #log { width: 1fr; border: solid $panel; }
        """
        BINDINGS = [
            ("r", "run_selected", t("sms_tui_run")),
            ("a", "run_rest", t("sms_tui_run_rest")),
            ("c", "clear_log", t("sms_tui_clear")),
            ("q", "quit", t("Back")),
            ("escape", "quit", t("Back")),
        ]

        def __init__(self):
            super().__init__()
            self.state = spec_mod.load()
            #: Étape en cours, pour l'icône ⏳ — vide quand rien ne tourne.
            self.running = ""

        # -- composition ------------------------------------------------ #

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="resume")
            with Horizontal():
                yield DataTable(id="steps", cursor_type="row")
                yield RichLog(
                    id="log",
                    highlight=False,
                    markup=False,
                    wrap=True,
                    max_lines=5000,
                )
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one("#steps", DataTable)
            table.add_columns(" ", t("sms_tui_step"), t("sms_tui_detail"))
            self._refresh_table()
            # Curseur sur ce qui reste à faire : c'est là qu'on veut agir.
            suivante = steps_mod.next_step(self.state)
            if suivante is not None:
                table.move_cursor(row=[s.id for s in STEPS].index(suivante.id))
            # Relecture périodique : une installation détachée peut se
            # terminer pendant qu'on regarde, et l'état vit sur le disque.
            self.set_interval(3.0, self._reload_state)

        # -- rendu ------------------------------------------------------ #

        def _reload_state(self) -> None:
            if self.running:
                # Ne pas écraser l'état en mémoire pendant qu'une étape écrit
                # dedans : le disque est en retard tant qu'elle n'a pas fini.
                return
            self.state = spec_mod.load()
            self._refresh_table()

        def _refresh_table(self) -> None:
            table = self.query_one("#steps", DataTable)
            ligne = table.cursor_row
            table.clear()
            for step in STEPS:
                etat = steps_mod.status_of(step, self.state, self.running)
                detail = self.state.errors.get(step.id, "")
                if not detail and step.manual and etat == "pending":
                    detail = t("sms_manual_hint")
                table.add_row(
                    ICON[etat],
                    step.label_for(self.state.spec),
                    detail[:60],
                )
            if 0 <= ligne < len(STEPS):
                table.move_cursor(row=ligne)
            fait, total = steps_mod.progress(self.state)
            adresse = self.state.vm_ip or "—"
            self.query_one("#resume", Static).update(
                f"{t('sms_status')} : {fait}/{total}   "
                f"{t('sms_mode_current')} : {self.state.spec.mode}   "
                f"{t('sms_vm_address')} : {adresse}"
            )

        def _write(self, ligne: str) -> None:
            self.query_one("#log", RichLog).write(ligne)

        # -- actions ---------------------------------------------------- #

        def _selected_step(self):
            index = self.query_one("#steps", DataTable).cursor_row
            return STEPS[index] if 0 <= index < len(STEPS) else None

        def action_clear_log(self) -> None:
            self.query_one("#log", RichLog).clear()

        def action_run_selected(self) -> None:
            step = self._selected_step()
            if step is not None:
                self._start(step)

        def action_run_rest(self) -> None:
            """Enchaîne ce qui reste, en s'arrêtant au premier échec."""
            restantes = [s for s in STEPS if not self.state.is_done(s.id)]
            if restantes:
                self._start(restantes[0], enchainer=True)

        # -- exécution -------------------------------------------------- #

        def _start(self, step, enchainer: bool = False) -> None:
            if self.running:
                self.notify(t("sms_tui_busy"), severity="warning")
                return
            manquant = steps_mod.blocked_by(step, self.state)
            if manquant:
                self.notify(
                    f"{t('sms_blocked_by')} : {', '.join(manquant)}",
                    severity="error",
                )
                return

            if step.id in ("vm", "mobile", "verify"):
                # Ces trois-là veulent le terminal : la VM ouvre son propre
                # tableau de bord, les deux autres posent une question. On
                # rend la main plutôt que de les mutiler.
                self._run_suspended(step, enchainer)
                return

            self.running = step.id
            self._refresh_table()
            self._write(f"── {step.label} ──")
            self.run_worker(
                lambda: self._work(step, enchainer),
                thread=True,
                exclusive=True,
            )

        def _veut_le_terminal(self, step) -> bool:
            """Les étapes qu'on ne peut pas exécuter dans un fil.

            Deux raisons distinctes. La création de VM ouvre SON PROPRE
            tableau de bord Textual, et deux applications Textual ne peuvent
            pas partager un terminal. Les étapes « mobile » et « vérifier »
            posent une question au clavier.

            En mode local, la première étape ne fait que vérifier
            l'environnement : elle n'a besoin de rien et tourne dans un fil
            comme les autres.
            """
            if step.id in ("mobile", "verify"):
                return True
            return step.id == "vm" and self.state.spec.mode != "local"

        def _run_suspended(self, step, enchainer: bool) -> None:
            with self.suspend():
                menu_mod._run_one(todo, self.state, step)
                input(f"\n  {t('sms_tui_resume')}")
            self.state = spec_mod.load()
            self._refresh_table()
            if enchainer and self.state.is_done(step.id):
                self.action_run_rest()

        def _work(self, step, enchainer: bool) -> None:
            """Corps du fil. Rien ici ne touche l'interface directement."""
            try:
                ok, message = menu_mod._dispatch(todo, self.state, step)
            except Exception as exc:  # noqa: BLE001 - on rapporte l'echec
                ok, message = False, f"{type(exc).__name__}: {exc}"
            self.call_from_thread(self._finish, step, ok, message, enchainer)

        def _finish(self, step, ok: bool, message: str, enchainer: bool):
            if ok:
                self.state.mark_done(step.id)
            else:
                self.state.mark_failed(step.id, message)
            spec_mod.save(self.state)
            self.running = ""
            self._write(f"{'✅' if ok else '❌'} {message}")
            self._refresh_table()
            if ok and enchainer:
                self.action_run_rest()

    app = Dashboard()
    if run_app:
        app.run()
    return app
