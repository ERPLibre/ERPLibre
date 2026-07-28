#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Dashboard Textual : suivi des installations ERPLibre parallèles sur VM.

Principe « détachable » : chaque installation tourne dans un processus
DÉTACHÉ (setsid) qui écrit un fichier log et, à la fin, un marqueur
« __ERPLIBRE_EXIT__ <code> ». Ce module ne fait que VISUALISER ces fichiers :
quitter le dashboard n'arrête rien, on peut le rouvrir pour ré-attacher.

- launch_installs(...) : lance les process détachés + écrit un manifeste JSON.
- run_monitor(manifest_path) : ouvre le dashboard Textual sur un manifeste.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

EXIT_MARKER = "__ERPLIBRE_EXIT__"
SSH_OPTS = (
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
    "-o ConnectTimeout=8"
)


def session_dir() -> Path:
    """Répertoire des logs/manifestes d'installation (créé au besoin)."""
    base = Path(os.path.expanduser("~/.erplibre/qemu-install"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _launch_one(ip: str, remote_cmd: str, log_path: str) -> None:
    """Lance une install SSH DÉTACHÉE : attend le sshd, exécute, journalise
    la sortie puis écrit le marqueur de fin avec le code de sortie."""
    wrapper = (
        # Attente du sshd (jusqu'à ~5 min) pour éviter « Connection refused ».
        f"for i in $(seq 1 60); do "
        f"ssh {SSH_OPTS} -o BatchMode=yes erplibre@{ip} true "
        f">/dev/null 2>&1 && break; sleep 5; done; "
        f"ssh {SSH_OPTS} erplibre@{ip} {shlex.quote(remote_cmd)} "
        f"> {shlex.quote(log_path)} 2>&1; "
        f'echo "{EXIT_MARKER} $?" >> {shlex.quote(log_path)}'
    )
    # setsid -f : le process survit à la fermeture du menu / du dashboard.
    subprocess.Popen(
        ["setsid", "-f", "bash", "-c", wrapper],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def launch_installs(vms: list[dict], branch: str, remote_cmd: str) -> str:
    """vms : [{name, ip}]. Lance chaque install détachée, écrit un manifeste
    et retourne son chemin. remote_cmd : script exécuté dans chaque VM."""
    sdir = session_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logdir = sdir / stamp
    logdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for vm in vms:
        log_path = str(logdir / f"{vm['name']}.log")
        Path(log_path).write_text("")  # log vide = état « en attente »
        _launch_one(vm["ip"], remote_cmd, log_path)
        entries.append(
            {
                "name": vm["name"],
                "ip": vm["ip"],
                "log": log_path,
                "ssh": f"ssh erplibre@{vm['ip']}",
            }
        )
    manifest = {
        "branch": branch,
        "started": time.time(),
        "vms": entries,
    }
    manifest_path = str(logdir / "session.json")
    Path(manifest_path).write_text(json.dumps(manifest, indent=2))
    return manifest_path


def read_status(log_path: str) -> tuple[str, int | None]:
    """(état, code) d'un log : pending / running / done / failed."""
    try:
        data = Path(log_path).read_text(errors="replace")
    except OSError:
        return "pending", None
    if not data.strip():
        return "pending", None
    for line in reversed(data.splitlines()):
        if EXIT_MARKER in line:
            try:
                code = int(line.split()[-1])
            except ValueError:
                code = 1
            return ("done" if code == 0 else "failed"), code
    return "running", None


# --------------------------------------------------------------------------- #
# Dashboard Textual
# --------------------------------------------------------------------------- #
def run_monitor(manifest_path: str) -> None:
    """Ouvre le dashboard Textual sur un manifeste d'installation."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import DataTable, Footer, Header, RichLog, Static

    manifest = json.loads(Path(manifest_path).read_text())
    started = manifest.get("started", time.time())
    vms = manifest["vms"]

    ICON = {
        "pending": "⏳",
        "running": "⏳",
        "done": "✅",
        "failed": "❌",
    }

    class Monitor(App):
        CSS = """
        DataTable { width: 40; border: solid $accent; }
        RichLog { border: solid $accent; }
        #sshbar { height: 1; color: $text-muted; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter (détaché)"),
            ("s", "ssh", "SSH"),
            ("f", "follow", "Suivre"),
            ("c", "copy_log", "Copier log"),
        ]

        def __init__(self):
            super().__init__()
            self._offsets = {vm["name"]: 0 for vm in vms}
            self._selected = vms[0]["name"] if vms else None
            self._follow = True

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            table = DataTable(id="vms", cursor_type="row")
            # Clés de colonnes explicites : update_cell() les référence.
            table.add_column("VM", key="vm")
            table.add_column("État", key="state")
            table.add_column("Durée", key="elapsed")
            for vm in vms:
                table.add_row(vm["name"], "⏳", "00:00", key=vm["name"])
            self._log = RichLog(id="log", highlight=False, markup=False)
            with Horizontal():
                yield table
                yield self._log
            yield Static("", id="sshbar")
            yield Footer()

        def on_mount(self) -> None:
            self.title = "ERPLibre — suivi d'installation"
            self._refresh_ssh()
            self._load_selected_log(reset=True)
            self.set_interval(1.0, self._tick)

        # -- helpers -------------------------------------------------------- #
        def _vm_by_name(self, name):
            return next((v for v in vms if v["name"] == name), None)

        def _refresh_ssh(self):
            vm = self._vm_by_name(self._selected)
            bar = self.query_one("#sshbar", Static)
            if vm:
                bar.update(
                    f"  {vm['ssh']}   (s = SSH · c = copier le log · "
                    "Maj+glisser = sélectionner)"
                )

        def _load_selected_log(self, reset=False):
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            if reset:
                self._log.clear()
                self._offsets[vm["name"]] = 0
            try:
                data = Path(vm["log"]).read_text(errors="replace")
            except OSError:
                return
            off = self._offsets[vm["name"]]
            new = data[off:]
            if new:
                for line in new.splitlines():
                    if EXIT_MARKER not in line:
                        self._log.write(line)
                self._offsets[vm["name"]] = len(data)

        def _tick(self):
            table = self.query_one("#vms", DataTable)
            for vm in vms:
                state, code = read_status(vm["log"])
                elapsed = time.time() - started
                mm, ss = divmod(int(elapsed), 60)
                label = ICON[state]
                if state == "failed":
                    label = f"❌ ({code})"
                elif state == "done":
                    label = "✅"
                table.update_cell(vm["name"], "state", label)
                if state in ("running", "pending"):
                    table.update_cell(
                        vm["name"], "elapsed", f"{mm:02d}:{ss:02d}"
                    )
            if self._follow:
                self._load_selected_log()

        # -- events --------------------------------------------------------- #
        def on_data_table_row_highlighted(self, event) -> None:
            name = event.row_key.value
            if name and name != self._selected:
                self._selected = name
                self._refresh_ssh()
                self._load_selected_log(reset=True)

        def action_follow(self) -> None:
            self._follow = not self._follow

        def action_ssh(self) -> None:
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            with self.suspend():
                os.system(f"ssh {SSH_OPTS} erplibre@{vm['ip']} || true")

        def action_copy_log(self) -> None:
            """Copie le log complet de la VM sélectionnée dans le
            presse-papiers (OSC 52 ; marche aussi à travers SSH)."""
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            try:
                text = Path(vm["log"]).read_text(errors="replace")
            except OSError:
                return
            self.copy_to_clipboard(text)
            self.notify(
                f"Log de {vm['name']} copié ({len(text)} car.)",
                title="Presse-papiers",
            )

    Monitor().run()
