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
import shutil
import subprocess
import time
from pathlib import Path

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


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
    # Sonde de disponibilité : on attend que sshd réponde ET que cloud-init
    # soit TERMINÉ, via des connexions COURTES successives (jusqu'à ~20 min :
    # une architecture ÉMULÉE, s390x/arm64 sur hôte x86, boote lentement).
    # Au 1er boot, cloud-init régénère les clés d'hôte et REDÉMARRE sshd : une
    # session SSH longue (ex. « cloud-init status --wait ») serait alors tuée
    # (« Connection closed by remote host », exit 255 — cas Fedora). Chaque
    # itération étant une connexion neuve, un redémarrage de sshd ne casse que
    # la tentative en cours. On imprime toujours l'état (|| true) pour matcher
    # sur le TEXTE, « status: running » n'ayant pas de code de sortie fiable.
    ci_probe = (
        "if command -v cloud-init >/dev/null 2>&1; then "
        "cloud-init status 2>/dev/null || true; else echo nocloudinit; fi"
    )
    log_q = shlex.quote(log_path)
    # On écrit un message d'attente + un battement toutes les ~30 s : sinon le
    # log reste VIDE pendant tout le boot émulé et paraît « bloqué ».
    msg_wait = t("Waiting for the VM to start (boot + cloud-init)")
    msg_slow = t("(an emulated architecture can be slow; this is normal)")
    msg_ready = t("VM ready - starting the ERPLibre install")
    wrapper = (
        f"echo {shlex.quote('== ' + msg_wait + ' ==')} >> {log_q}; "
        f"echo {shlex.quote('   ' + msg_slow)} >> {log_q}; "
        f"for i in $(seq 1 240); do "
        f"st=$(ssh {SSH_OPTS} -o BatchMode=yes erplibre@{ip} "
        f"{shlex.quote(ci_probe)} 2>/dev/null); "
        f'case "$st" in '
        f"*done*|*disabled*|*error*|*degraded*|*nocloudinit*) break;; "
        f"esac; "
        f'if [ $((i % 6)) -eq 0 ]; then echo "   ... $((i*5))s" >> {log_q}; fi; '
        f"sleep 5; done; "
        f"echo {shlex.quote('== ' + msg_ready + ' ==')} >> {log_q}; "
        f"ssh {SSH_OPTS} erplibre@{ip} {shlex.quote(remote_cmd)} "
        f">> {log_q} 2>&1; "
        f'echo "{EXIT_MARKER} $?" >> {log_q}'
    )
    # setsid -f : le process survit à la fermeture du menu / du dashboard.
    subprocess.Popen(
        ["setsid", "-f", "bash", "-c", wrapper],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _log_header(vm: dict, branch: str, when: str) -> str:
    """En-tête du log : date, VM, distribution, version, architecture, branche.
    Permet d'identifier l'installation d'un coup d'œil (et de ne jamais laisser
    le log vide pendant l'attente du boot)."""
    distro = vm.get("distro") or "?"
    version = vm.get("version") or ""
    arch = vm.get("arch") or "?"
    bar = "=" * 64
    return (
        f"{bar}\n"
        f"  ERPLibre — {t('installation')}\n"
        f"  Date         : {when}\n"
        f"  VM           : {vm['name']}\n"
        f"  Distribution : {distro} {version}\n"
        f"  Architecture : {arch}\n"
        f"  Branche      : {branch}\n"
        f"  IP           : {vm['ip']}\n"
        f"{bar}\n\n"
    )


def launch_installs(vms: list[dict], branch: str, remote_cmd: str) -> str:
    """vms : [{name, ip, distro?, version?, arch?}]. Lance chaque install
    détachée, écrit un manifeste et retourne son chemin. remote_cmd : script
    exécuté dans chaque VM."""
    sdir = session_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    logdir = sdir / stamp
    logdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for vm in vms:
        log_path = str(logdir / f"{vm['name']}.log")
        # En-tête d'emblée (date/distro/version/arch) : le log n'est jamais
        # vide, l'utilisateur voit tout de suite QUOI s'installe.
        Path(log_path).write_text(_log_header(vm, branch, when))
        _launch_one(vm["ip"], remote_cmd, log_path)
        entries.append(
            {
                "name": vm["name"],
                "ip": vm["ip"],
                "distro": vm.get("distro"),
                "version": vm.get("version"),
                "arch": vm.get("arch"),
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
    """(état, code) d'un log : pending / running / done / failed. Ne lit que
    la FIN du fichier (le marqueur de sortie est sur la dernière ligne) : lire
    tout le log de 30 VM chaque seconde saturait la boucle d'événements du TUI
    (lag, interface figée quand l'I/O ralentit)."""
    try:
        size = os.path.getsize(log_path)
        if size == 0:
            return "pending", None
        with open(log_path, "rb") as fh:
            if size > 4096:
                fh.seek(-4096, os.SEEK_END)
            tail = fh.read().decode(errors="replace")
    except OSError:
        return "pending", None
    if not tail.strip():
        return "pending", None
    for line in reversed(tail.splitlines()):
        if EXIT_MARKER in line:
            try:
                code = int(line.split()[-1])
            except ValueError:
                code = 1
            return ("done" if code == 0 else "failed"), code
    return "running", None


# --------------------------------------------------------------------------- #
# Télémétrie, historique de durées (ETA), navigateur CLI
# --------------------------------------------------------------------------- #
def _stats_path() -> Path:
    """Fichier d'historique persistant (durées d'installation par arch)."""
    return session_dir() / "stats.json"


def load_stats() -> dict:
    try:
        return json.loads(_stats_path().read_text())
    except (OSError, ValueError):
        return {}


def record_duration(arch: str, secs: float) -> None:
    """Mémorise la durée d'une install (par architecture) pour estimer l'ETA
    des prochaines. On garde les 20 dernières valeurs par arch."""
    data = load_stats()
    durations = data.setdefault("durations", {})
    key = arch or "unknown"
    lst = durations.setdefault(key, [])
    lst.append(int(secs))
    durations[key] = lst[-20:]
    try:
        _stats_path().write_text(json.dumps(data))
    except OSError:
        pass


def eta_reference(stats: dict, arch: str) -> int | None:
    """Durée d'install de RÉFÉRENCE (médiane) pour cette arch, d'après
    l'historique ; repli sur toutes archis confondues. None si aucun historique."""
    durations = stats.get("durations", {}) or {}
    lst = durations.get(arch or "unknown") or []
    if not lst:
        lst = [x for v in durations.values() for x in v]
    if not lst:
        return None
    s = sorted(lst)
    return s[len(s) // 2]


def _fmt_size(nbytes) -> str:
    """Octets -> « 1.2G » / « 345M » / « 12K »."""
    if nbytes is None:
        return "-"
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if nbytes >= div:
            return f"{nbytes / div:.1f}{unit}"
    return f"{nbytes // 1024}K"


def _fmt_secs(secs) -> str:
    """Secondes -> « 45s » / « 12m » / « 1h05 »."""
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}"


def vm_disk_path(vm: dict) -> str:
    """Chemin du qcow2 de la VM (défaut libvirt si non fourni)."""
    return vm.get("disk") or f"/var/lib/libvirt/images/{vm['name']}.qcow2"


def disk_actual_size(path: str) -> int | None:
    """Taille RÉELLEMENT occupée du qcow2 (creux) via st_blocks."""
    try:
        st = os.stat(path)
        return int(getattr(st, "st_blocks", 0)) * 512
    except OSError:
        return None


# Navigateurs web en ligne de commande, par ordre de préférence (rendu JS
# d'abord — utile pour l'UI Odoo — puis navigateurs texte classiques).
CLI_BROWSERS = ("browsh", "carbonyl", "w3m", "links", "elinks", "lynx")


def cli_browser() -> str | None:
    """Premier navigateur CLI disponible dans le PATH, sinon None."""
    for name in CLI_BROWSERS:
        if shutil.which(name):
            return name
    return None


def virsh_domstates() -> dict:
    """{nom: état} de tous les domaines libvirt (« virsh list --all »). Sert à
    détecter une VM EN PAUSE ou EFFACÉE pendant le suivi. Un seul appel virsh
    pour tout le parc (à interroger à intervalle LENT)."""
    try:
        res = subprocess.run(
            ["sudo", "virsh", "list", "--all"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    states = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        # Ignore l'en-tête (« Id Name State ») et le séparateur (« ---- »,
        # un seul token). Une VM éteinte a « - » en Id : à NE PAS ignorer.
        if len(parts) < 3 or parts[0] == "Id":
            continue
        states[parts[1]] = " ".join(parts[2:])
    return states


# --------------------------------------------------------------------------- #
# Dashboard Textual
# --------------------------------------------------------------------------- #
def run_monitor(manifest_path: str, run_app: bool = True):
    """Ouvre le dashboard Textual sur un manifeste d'installation. `run_app`
    à False renvoie l'instance sans la lancer (tests headless)."""
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
        DataTable { width: 58; border: solid $accent; }
        RichLog { border: solid $accent; }
        #telemetry { height: 1; color: $text-muted; }
        #sshbar { height: 2; color: $text-muted; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter (détaché)"),
            ("s", "ssh", "SSH"),
            ("w", "web", "Web (navigateur CLI)"),
            ("f", "follow", "Suivre"),
            ("c", "copy_log", "Copier log"),
        ]

        def __init__(self):
            super().__init__()
            self._offsets = {vm["name"]: 0 for vm in vms}
            self._selected = vms[0]["name"] if vms else None
            self._follow = True
            # Statuts TERMINAUX mémorisés : une VM finie n'est plus relue
            # (réduit fortement l'I/O sur un gros parc). Valeur = (état, code,
            # durée à la complétion).
            self._final = {}
            # Cache des cellules AFFICHÉES : on n'appelle update_cell (donc on
            # ne re-render) que si la valeur CHANGE -> plus de churn de rendu.
            self._cells = {}
            # Historique de durées (ETA) + dossier disque à surveiller.
            self._stats = load_stats()
            self._disk_dir = os.path.dirname(vm_disk_path(vms[0])) if vms else "/"
            # État libvirt (running/paused/gone), rafraîchi à intervalle LENT.
            self._domstate = {}

        @staticmethod
        def _fmt(secs):
            mm, ss = divmod(int(secs), 60)
            return f"{mm:02d}:{ss:02d}"

        def _set_cell(self, table, name, col, value):
            key = (name, col)
            if self._cells.get(key) == value:
                return
            self._cells[key] = value
            table.update_cell(name, col, value)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            table = DataTable(id="vms", cursor_type="row")
            # Clés de colonnes explicites : update_cell() les référence.
            table.add_column("VM", key="vm")
            table.add_column("État", key="state")
            table.add_column("Durée", key="elapsed")
            table.add_column("Disque", key="disk")
            for vm in vms:
                table.add_row(vm["name"], "⏳", "--:--", "-", key=vm["name"])
            # max_lines borne la mémoire/rendu (un install verbeux × 30 VM).
            self._log = RichLog(
                id="log", highlight=False, markup=False, max_lines=5000
            )
            with Horizontal():
                yield table
                yield self._log
            # Barre de télémétrie hôte (CPU, disque, ETA parc).
            yield Static("", id="telemetry")
            yield Static("", id="sshbar")
            yield Footer()

        def on_mount(self) -> None:
            # Le NOMBRE de VM figure dans le titre ; le sous-titre suit la
            # progression (terminées / total + durée globale).
            self.title = f"ERPLibre — {t('install monitoring')} ({len(vms)} VM)"
            self.sub_title = f"0/{len(vms)} {t('completed')}"
            self._refresh_ssh()
            self._load_selected_log(reset=True)
            # Table toutes les 2 s (30 lectures de fin de log), suivi du log
            # sélectionné toutes les 1 s (une seule lecture incrémentale).
            self.set_interval(2.0, self._tick_table)
            self.set_interval(1.0, self._tick_log)
            # État libvirt (pause / effacée) : check LENT (appel virsh) toutes
            # les 10 s ; le tableau applique le cache à chaque tick (2 s).
            self.set_interval(10.0, self._tick_domstate)
            self._tick_domstate()  # premier relevé immédiat

        # -- helpers -------------------------------------------------------- #
        def _vm_by_name(self, name):
            return next((v for v in vms if v["name"] == name), None)

        def _refresh_ssh(self):
            vm = self._vm_by_name(self._selected)
            bar = self.query_one("#sshbar", Static)
            if vm:
                bar.update(
                    f"  {vm['ssh']}    (s = SSH · w = web :8069 · "
                    "c = copier le log · Maj+glisser = sélectionner)\n"
                    f"  Log : {vm['log']}"
                )

        def _load_selected_log(self, reset=False):
            vm = self._vm_by_name(self._selected)
            if not vm:
                return
            name = vm["name"]
            if reset:
                self._log.clear()
                self._offsets[name] = 0
            # Lecture INCRÉMENTALE (seek à l'offset) : on ne relit pas tout le
            # fichier à chaque rafraîchissement.
            try:
                with open(vm["log"], "r", errors="replace") as fh:
                    fh.seek(self._offsets.get(name, 0))
                    new = fh.read()
                    self._offsets[name] = fh.tell()
            except OSError:
                return
            if new:
                for line in new.splitlines():
                    if EXIT_MARKER not in line:
                        self._log.write(line)

        def _tick_table(self):
            # Protégé : une erreur I/O transitoire (disque plein, log effacé)
            # ne doit pas tuer la boucle et figer l'interface.
            try:
                table = self.query_one("#vms", DataTable)
                now = time.time()
                remaining = []  # ETA restant par VM en cours
                for vm in vms:
                    name = vm["name"]
                    # Disque réel du qcow2 (change lentement -> peu de churn).
                    self._set_cell(
                        table, name, "disk",
                        _fmt_size(disk_actual_size(vm_disk_path(vm))),
                    )
                    if name in self._final:
                        continue  # déjà terminé -> plus de lecture de statut
                    # VM EFFACÉE pendant le suivi -> état terminal « effacé ».
                    ds = self._domstate.get(name)
                    if ds == "gone":
                        self._final[name] = ("deleted", None, now - started)
                        self._set_cell(
                            table, name, "state", f"❌ {t('deleted')}"
                        )
                        continue
                    state, code = read_status(vm["log"])
                    if state in ("done", "failed"):
                        # Fige la durée + MÉMORISE pour l'ETA des prochaines.
                        elapsed = now - started
                        self._final[name] = (state, code, elapsed)
                        if state == "done":
                            record_duration(vm.get("arch"), elapsed)
                            self._stats = load_stats()
                        lbl = "✅" if state == "done" else f"❌ ({code})"
                        self._set_cell(table, name, "state", lbl)
                        self._set_cell(
                            table, name, "elapsed", self._fmt(elapsed)
                        )
                    elif ds == "paused":
                        # VM EN PAUSE (virsh suspend) : l'install ne progresse
                        # pas -> on l'indique (non terminal, peut reprendre).
                        self._set_cell(
                            table, name, "state", f"⏸ {t('paused')}"
                        )
                    else:
                        # running/pending : icône stable -> pas de churn. ETA
                        # = référence historique (par arch) - temps écoulé.
                        self._set_cell(table, name, "state", ICON[state])
                        ref = eta_reference(self._stats, vm.get("arch"))
                        if ref is not None:
                            remaining.append(max(0, ref - (now - started)))
                # Sous-titre : compteur de VM terminées + durée globale.
                done = len(self._final)
                eta = ""
                if remaining:
                    # ETA du parc = la VM en cours la plus longue à finir.
                    eta = f" · ETA ~{_fmt_secs(max(remaining))}"
                self.sub_title = (
                    f"{done}/{len(vms)} {t('completed')} · "
                    f"{self._fmt(now - started)}{eta}"
                )
                self._update_telemetry()
            except Exception:
                pass

        def _update_telemetry(self):
            """Barre de télémétrie hôte : CPU % (charge/CPU) + disque du
            dossier des images (là où les qcow2 grossissent)."""
            try:
                ncpu = os.cpu_count() or 1
                load1 = os.getloadavg()[0]
                cpu_pct = min(999, int(load1 / ncpu * 100))
                du = shutil.disk_usage(self._disk_dir)
                used_pct = int(du.used / du.total * 100) if du.total else 0
                txt = (
                    f"  ⚙ CPU {cpu_pct}% (charge {load1:.1f}/{ncpu})   "
                    f"💽 {self._disk_dir}: {_fmt_size(du.used)}/"
                    f"{_fmt_size(du.total)} ({used_pct}%) · "
                    f"libre {_fmt_size(du.free)}"
                )
                self.query_one("#telemetry", Static).update(txt)
            except Exception:
                pass

        def _tick_log(self):
            if self._follow:
                try:
                    self._load_selected_log()
                except Exception:
                    pass

        def _tick_domstate(self):
            # Relevé LENT de l'état libvirt : une VM absente de « virsh list »
            # est EFFACÉE (« gone ») ; sinon on garde son état (paused, …).
            try:
                states = virsh_domstates()
                for vm in vms:
                    self._domstate[vm["name"]] = states.get(vm["name"], "gone")
            except Exception:
                pass

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

        def action_web(self) -> None:
            """Ouvre l'UI web de la VM (Odoo :8069) dans un navigateur CLI
            (browsh/carbonyl/w3m/links/elinks/lynx). Surtout utile une fois
            l'installation TERMINÉE."""
            vm = self._vm_by_name(self._selected)
            if not vm or not vm.get("ip"):
                self.notify("Pas d'IP pour cette VM.", title="Web")
                return
            browser = cli_browser()
            if not browser:
                self.notify(
                    "Aucun navigateur CLI trouvé. Installez-en un : "
                    "w3m, lynx, links, elinks, browsh ou carbonyl.",
                    title="Web",
                    severity="warning",
                )
                return
            url = f"http://{vm['ip']}:8069"
            with self.suspend():
                os.system(f"{browser} {shlex.quote(url)} || true")

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

    app = Monitor()
    if run_app:
        app.run()
    return app
