#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Formulaire Textual de déploiement QEMU, et vue de progression.

Deux interfaces mènent au même déploiement : les invites en ligne de
`todo.py` et ce formulaire. Toutes deux produisent la MÊME structure — la
« spec » — que `TODO._qemu_run_spec` consomme. Rien n'est décidé ici qui ne
puisse l'être là-bas, et réciproquement.

- build_vms(...) / plan_rows(...) : logique pure, testable sans terminal.
- run_deploy_form(ctx, run_app=True) : le formulaire ; renvoie une spec ou None.
- run_deploy_progress(jobs, ...) : blocs repliables par VM pendant le
  déploiement, avec copie du log vers le presse-papiers (OSC 52).

Le formulaire ne lance AUCUNE commande privilégiée ni réseau : tout appel
`virsh` passe par sudo et une invite de mot de passe casserait l'affichage
Textual. Les données coûteuses (domaines existants, branches distantes) sont
préchargées par l'appelant et arrivent dans `ctx`.
"""
from __future__ import annotations

import os
import time

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# --------------------------------------------------------------------------- #
# Logique pure — aucune dépendance à Textual, testable telle quelle
# --------------------------------------------------------------------------- #
def entry_key(entry) -> tuple:
    """Identité stable d'une entrée de catalogue, indépendante de son rang :
    les surcharges par VM y survivent quand la sélection change."""
    return (entry["distro"], entry["version"], entry["arch"])


def parse_disk(value):
    """« 60 », « 60G », « 1T », « 1,5T » -> « <n>G », ou None si invalide.
    Même règle que `TODO._qemu_parse_disk` : tout le reste de la chaîne
    raisonne en gigaoctets."""
    txt = str(value).strip().upper().replace(",", ".")
    factor = 1
    if txt.endswith("T"):
        factor, txt = 1024, txt[:-1]
    elif txt.endswith("G"):
        txt = txt[:-1]
    try:
        gigs = int(float(txt) * factor)
    except ValueError:
        return None
    return f"{gigs}G" if gigs > 0 else None


def disk_gb(value) -> int:
    """« 60G » -> 60 (best effort), pour les totaux."""
    parsed = parse_disk(value)
    return int(parsed[:-1]) if parsed else 0


def apply_profile(entries, profile, base_vcpus, host_cpu, custom=None):
    """Applique le profil de ressources aux entrées choisies.

    Reproduit à l'identique `TODO._qemu_prompt_resources` : un multiplicateur
    monte la RAM minimale du catalogue et les vCPU en se bornant aux cœurs de
    l'hôte ; « custom » impose les mêmes valeurs à tout le parc, une valeur
    absente gardant celle du catalogue."""
    out = []
    for e in entries:
        if profile == "custom":
            cus = custom or {}
            ram = cus.get("ram") or e["ram"]
            disk = cus.get("disk") or e["disk"]
            vcpus = cus.get("vcpus") or base_vcpus
        else:
            mult = int(profile)
            ram = e["ram"] * mult
            disk = e["disk"]
            vcpus = min(base_vcpus * mult, host_cpu)
        out.append(
            {
                "name": e["name"],
                "distro": e["distro"],
                "version": e["version"],
                "arch": e["arch"],
                "ram": ram,
                "disk": disk,
                "vcpus": vcpus,
            }
        )
    return out


def apply_overrides(vms, entries, overrides):
    """Réapplique les réglages par VM (nom, vCPU, RAM, disque) après un
    recalcul du profil. `overrides` est indexé par `entry_key`."""
    for vm, e in zip(vms, entries):
        for field, value in (overrides.get(entry_key(e)) or {}).items():
            vm[field] = value
    return vms


def build_vms(entries, profile, base_vcpus, host_cpu, custom, overrides):
    """Catalogue choisi + profil + surcharges -> liste de VM de la spec."""
    return apply_overrides(
        apply_profile(entries, profile, base_vcpus, host_cpu, custom),
        entries,
        overrides,
    )


def vm_status(name, domains):
    """État d'un nom face à l'existant : ('new'|'exists'|'orphan', message).

    Les deux collisions n'ont pas la même gravité — une VM définie est
    ignorée, un qcow2 resté seul fait échouer deploy_qemu, qui refuse
    d'écraser sans --force."""
    if name in domains:
        return "exists", t("exists - skipped")
    if os.path.exists(f"/var/lib/libvirt/images/{name}.qcow2"):
        return "orphan", t("orphan disk - will FAIL")
    return "new", ""


def plan_rows(vms, domains, extra_disk_gb=0):
    """Lignes du tableau du plan : une par VM, avec son état."""
    rows = []
    for vm in vms:
        state, note = vm_status(vm["name"], domains)
        rows.append(
            {
                "vm": vm,
                "state": state,
                "note": note,
                "disk_gb": disk_gb(vm["disk"]) + extra_disk_gb,
            }
        )
    return rows


def plan_totals(rows):
    """Totaux des VM RÉELLEMENT créées (les existantes ne consomment rien de
    neuf) : (nb, vcpus, ram_mo, disque_go)."""
    fresh = [r for r in rows if r["state"] != "exists"]
    return (
        len(fresh),
        sum(r["vm"]["vcpus"] for r in fresh),
        sum(r["vm"]["ram"] for r in fresh),
        sum(r["disk_gb"] for r in fresh),
    )


def build_spec(vms, domains, form):
    """Assemble la spec finale, dans la forme exacte que produit la CLI."""
    known = set(domains)
    return {
        "res_label": form["res_label"],
        "vms": [vm for vm in vms if vm["name"] not in known],
        "existing": [vm["name"] for vm in vms if vm["name"] in known],
        "ssh_key": form["ssh_key"],
        "timezone": form.get("timezone", ""),
        "install": form["install"],
        "add_ssh_config": form["add_ssh_config"],
        "parallelism": form["parallelism"],
    }


def fmt_dur(secs) -> str:
    mm, ss = divmod(int(secs), 60)
    if mm >= 60:
        return f"{mm // 60}h{mm % 60:02d}"
    return f"{mm}m{ss:02d}" if mm else f"{ss}s"


# Au-delà, un OSC 52 est tronqué par certains terminaux (xterm notamment).
# On copie alors la FIN du log — la partie qui porte l'erreur.
CLIP_LIMIT = 100_000


def clip_payload(text, limit=CLIP_LIMIT):
    """(texte_à_copier, tronqué?) — on garde la fin, pas le début."""
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


# --------------------------------------------------------------------------- #
# Formulaire Textual
# --------------------------------------------------------------------------- #
def run_deploy_form(ctx, run_app: bool = True):
    """Formulaire de déploiement. Renvoie une spec, ou None si annulé.
    `run_app=False` renvoie l'instance sans la lancer (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Footer,
        Header,
        Input,
        Label,
        RadioButton,
        RadioSet,
        Select,
        SelectionList,
        Static,
    )

    catalog = ctx["catalog"]
    arches = ctx["arches"]
    domains = set(ctx.get("domains") or [])
    profiles = ctx.get("install_profiles") or []
    branches = ctx.get("branches") or ["master"]
    host_cpu = ctx.get("host_cpu") or 2
    free_ram = ctx.get("free_ram") or 0
    base_vcpus = ctx.get("base_vcpus") or 2
    extra_disk = ctx.get("extra_disk_gb") or 0
    defaults = ctx.get("defaults") or {}
    result = {"spec": None}

    AUTO = "__auto__"

    def entry_label(e):
        star = " *" if e.get("default") else ""
        return (
            f"{e['distro']} {e['version']}{star} [{e['arch']}]  "
            f"RAM≥{e['ram']}Mo  {e['disk']}"
        )

    class EditVMScreen(ModalScreen):
        """Réglages d'UNE VM. Un champ vide garde la valeur courante."""

        BINDINGS = [("escape", "cancel", t("Cancel"))]

        def __init__(self, vm):
            super().__init__()
            self._vm = vm

        def compose(self) -> ComposeResult:
            with Vertical(id="editbox"):
                yield Static(f"  {self._vm['name']}", id="edittitle")
                yield Label(t("Name"))
                yield Input(value=self._vm["name"], id="e_name")
                yield Label(t("vCPU"))
                yield Input(value=str(self._vm["vcpus"]), id="e_vcpus")
                yield Label(t("RAM (MB)"))
                yield Input(value=str(self._vm["ram"]), id="e_ram")
                yield Label(t("Disk"))
                yield Input(value=str(self._vm["disk"]), id="e_disk")
                with Horizontal(id="editbtns"):
                    yield Button(t("Apply"), variant="primary", id="e_ok")
                    yield Button(t("Cancel"), id="e_cancel")

        def on_button_pressed(self, event) -> None:
            if event.button.id != "e_ok":
                self.dismiss(None)
                return
            out = {}
            name = self.query_one("#e_name", Input).value.strip()
            if name:
                out["name"] = name
            for field, wid in (("vcpus", "#e_vcpus"), ("ram", "#e_ram")):
                raw = self.query_one(wid, Input).value.strip()
                if raw.isdigit() and int(raw) > 0:
                    out[field] = int(raw)
            disk = parse_disk(self.query_one("#e_disk", Input).value)
            if disk:
                out["disk"] = disk
            self.dismiss(out)

        def action_cancel(self) -> None:
            self.dismiss(None)

    class PreviewScreen(ModalScreen):
        """Aperçu des commandes qui seraient lancées (aucune exécution)."""

        BINDINGS = [
            ("escape", "close", t("Close")),
            ("q", "close", t("Close")),
        ]

        def __init__(self, lines):
            super().__init__()
            self._lines = lines

        def compose(self) -> ComposeResult:
            with Vertical(id="prevbox"):
                yield Static(
                    f"  {t('Preview (dry-run):')}   ({t('Esc to close')})",
                    id="prevtitle",
                )
                yield Static("\n\n".join(self._lines), id="prevbody")

        def action_close(self) -> None:
            self.dismiss()

    class DeployForm(App):
        CSS = """
        #body { height: 1fr; }
        #fields { width: 62; border: solid $accent; overflow-y: auto; }
        #right { width: 1fr; }
        #plan { height: 1fr; border: solid $accent; }
        #totals { height: auto; color: $text-muted; padding: 0 1; }
        .grouptitle { color: $accent; text-style: bold; padding: 1 0 0 0; }
        SelectionList { height: 10; border: solid $panel; }
        RadioSet { height: auto; layout: horizontal; }
        #reslabel { color: $text-muted; }
        EditVMScreen { align: center middle; }
        #editbox {
            width: 56; height: auto; padding: 1 2;
            border: thick $accent; background: $surface;
        }
        #edittitle { color: $accent; text-style: bold; }
        #editbtns { height: auto; padding-top: 1; }
        PreviewScreen { align: center middle; }
        #prevbox {
            width: 90%; height: 70%; padding: 1 2;
            border: thick $accent; background: $surface;
        }
        #prevtitle { height: 1; color: $accent; text-style: bold; }
        #prevbody { height: 1fr; overflow-y: auto; }
        """
        # Touches de fonction plutôt que ctrl+lettre : ctrl+p est pris par la
        # palette de commandes de Textual, et une lettre seule serait avalée
        # par le champ de saisie qui a le focus.
        BINDINGS = [
            ("f5", "deploy", t("Deploy")),
            ("f2", "edit_vm", t("Edit VM")),
            ("f3", "preview", t("Preview")),
            ("f6", "select_all", t("All")),
            ("f7", "select_main", t("Main versions")),
            ("f8", "select_none", t("None")),
            ("escape", "cancel", t("Cancel")),
        ]

        def __init__(self):
            super().__init__()
            self.arch = ctx.get("native") or arches[0]
            self.profile = "1"
            self.custom = {}
            self.overrides = {}
            self.vms = []
            self.rows = []

        # -- construction de l'écran ----------------------------------- #
        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal(id="body"):
                with VerticalScroll(id="fields"):
                    yield Static(t("Architecture"), classes="grouptitle")
                    with RadioSet(id="f_arch"):
                        for a in arches:
                            label = a if a != "all" else t("all archs")
                            yield RadioButton(label, value=a == self.arch)
                    yield Static(t("Catalog"), classes="grouptitle")
                    yield SelectionList(id="f_catalog")
                    yield Static(t("Resources per VM"), classes="grouptitle")
                    with RadioSet(id="f_profile"):
                        for label in ("x1", "x2", "x3", "x4"):
                            yield RadioButton(label, value=label == "x1")
                        yield RadioButton(t("custom"))
                    yield Select(
                        [(str(c), c) for c in ctx["cpu_presets"]],
                        prompt=t("vCPU"),
                        id="f_vcpus",
                        disabled=True,
                    )
                    yield Select(
                        [
                            (f"{m} ({m // 1024}G)", m)
                            for m in ctx["ram_presets"]
                        ],
                        prompt=t("RAM (MB)"),
                        id="f_ram",
                        disabled=True,
                    )
                    yield Select(
                        [(d, d) for d in ctx["disk_presets"]],
                        prompt=t("Disk"),
                        id="f_disk",
                        disabled=True,
                    )
                    yield Static("ERPLibre", classes="grouptitle")
                    yield Checkbox(
                        t("Install ERPLibre"),
                        value=defaults.get("install", True),
                        id="f_install",
                    )
                    yield Select(
                        [(b, b) for b in branches],
                        value=(
                            "develop" if "develop" in branches else branches[0]
                        ),
                        allow_blank=False,
                        id="f_branch",
                    )
                    yield Select(
                        [(lbl, i) for i, (lbl, _c) in enumerate(profiles)],
                        value=0 if profiles else Select.BLANK,
                        allow_blank=not profiles,
                        id="f_profile_install",
                    )
                    yield Checkbox(
                        t("Production (/opt, confined)"),
                        value=defaults.get("prod", False),
                        id="f_prod",
                    )
                    yield Checkbox(
                        t("Monitoring dashboard"),
                        value=defaults.get("monitor", True),
                        id="f_monitor",
                    )
                    yield Static(t("Timezone"), classes="grouptitle")
                    yield Input(
                        value=ctx.get("timezone") or "",
                        placeholder=t("Timezone for the VMs"),
                        id="f_tz",
                    )
                    yield Static("SSH", classes="grouptitle")
                    yield Input(
                        value=ctx.get("ssh_key") or "",
                        placeholder=t("SSH public key path"),
                        id="f_key",
                    )
                    yield Checkbox(
                        t("Add each VM to ~/.ssh/config"),
                        value=defaults.get("add_ssh_config", True),
                        id="f_sshcfg",
                    )
                    yield Static(t("Parallelism"), classes="grouptitle")
                    yield Select(
                        [(str(n), n) for n in range(1, host_cpu + 1)],
                        value=min(4, host_cpu),
                        allow_blank=False,
                        id="f_par",
                    )
                with Vertical(id="right"):
                    yield DataTable(id="plan")
                    yield Static("", id="totals")
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("Deploy ERPLibre VM(s)!")
            table = self.query_one("#plan", DataTable)
            table.cursor_type = "row"
            table.add_columns(
                t("Name"),
                t("Distro"),
                t("Version"),
                t("Arch"),
                "vCPU",
                "RAM",
                t("Disk"),
                t("Status"),
            )
            self._reload_catalog(first_load=True)

        # -- catalogue et recalcul ------------------------------------- #
        def _entries(self):
            return catalog.get(self.arch, [])

        def _reload_catalog(self, first_load=False):
            """(Re)charge la liste à cocher.

            RIEN n'est coché d'avance : déployer coûte cher, et une case
            pré-cochée ferait créer une VM que personne n'a demandée. Le « * »
            marque toujours la version principale, et F7 les coche toutes.

            Après un changement d'architecture, les cases déjà cochées sont
            conservées quand l'entrée existe encore — l'identité est
            (distro, version, archi), pas le rang dans la liste."""
            widget = self.query_one("#f_catalog", SelectionList)
            keep = (
                set()
                if first_load
                else {
                    entry_key(self._entries_before[i])
                    for i in widget.selected
                    if i < len(self._entries_before)
                }
            )
            widget.clear_options()
            entries = self._entries()
            for i, e in enumerate(entries):
                widget.add_option((entry_label(e), i, entry_key(e) in keep))
            self._entries_before = entries
            self._recompute()

        def _selected_entries(self):
            widget = self.query_one("#f_catalog", SelectionList)
            entries = self._entries()
            return [entries[i] for i in sorted(widget.selected)]

        def _recompute(self):
            entries = self._selected_entries()
            self.vms = build_vms(
                entries,
                self.profile,
                base_vcpus,
                host_cpu,
                self.custom,
                self.overrides,
            )
            self.rows = plan_rows(
                self.vms,
                domains,
                (
                    extra_disk
                    if self.query_one("#f_install", Checkbox).value
                    else 0
                ),
            )
            self._render_plan()

        def _render_plan(self):
            table = self.query_one("#plan", DataTable)
            table.clear()
            for r in self.rows:
                vm = r["vm"]
                icon = {"new": "", "exists": "⏭ ", "orphan": "❌ "}[r["state"]]
                table.add_row(
                    vm["name"],
                    vm["distro"],
                    vm["version"],
                    vm["arch"],
                    str(vm["vcpus"]),
                    f"{vm['ram']}Mo",
                    f"{r['disk_gb']}G",
                    f"{icon}{r['note']}",
                )
            if not self.rows:
                # Rien de coché : un total à zéro n'apprend rien, on dit
                # plutôt comment remplir la liste.
                self.query_one("#totals", Static).update(
                    f"  {t('Tick what to deploy')} — "
                    f"{t('F7 main versions · F6 all')}"
                )
                return
            n, cpus, ram, disk = plan_totals(self.rows)
            warn = ""
            if free_ram and ram > free_ram:
                warn = f"   ⚠ {t('> host free RAM')}"
            elif cpus > host_cpu:
                warn = f"   ⚠ {t('> host cores')} ({host_cpu})"
            dupes = len({vm["name"] for vm in self.vms}) != len(self.vms)
            dup_txt = (
                f"\n  ⚠ {t('Duplicate names detected; keeping as entered.')}"
                if dupes
                else ""
            )
            self.query_one("#totals", Static).update(
                f"  {n} {t('VMs')} · {cpus} vCPU · {ram} Mo · ~{disk} G"
                f"{warn}{dup_txt}"
            )

        # -- réactions aux champs -------------------------------------- #
        def on_radio_set_changed(self, event) -> None:
            if event.radio_set.id == "f_arch":
                self.arch = arches[event.radio_set.pressed_index]
                self._reload_catalog()
            elif event.radio_set.id == "f_profile":
                index = event.radio_set.pressed_index
                self.profile = "custom" if index == 4 else str(index + 1)
                custom = self.profile == "custom"
                for wid in ("#f_vcpus", "#f_ram", "#f_disk"):
                    self.query_one(wid, Select).disabled = not custom
                self._recompute()

        def on_selection_list_selected_changed(self, event) -> None:
            self._recompute()

        def on_select_changed(self, event) -> None:
            mapping = {"f_vcpus": "vcpus", "f_ram": "ram", "f_disk": "disk"}
            field = mapping.get(event.select.id)
            if field:
                if event.value is not Select.BLANK:
                    self.custom[field] = event.value
                self._recompute()

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id == "f_install":
                self._recompute()  # le disque annoncé inclut le +5 G ERPLibre

        # -- actions ---------------------------------------------------- #
        def action_select_all(self) -> None:
            self.query_one("#f_catalog", SelectionList).select_all()

        def action_select_none(self) -> None:
            self.query_one("#f_catalog", SelectionList).deselect_all()

        def action_select_main(self) -> None:
            """Une VM par distro : la version marquée par défaut."""
            widget = self.query_one("#f_catalog", SelectionList)
            widget.deselect_all()
            for i, e in enumerate(self._entries()):
                if e.get("default"):
                    widget.select(i)

        def action_edit_vm(self) -> None:
            table = self.query_one("#plan", DataTable)
            index = table.cursor_row
            if not (0 <= index < len(self.vms)):
                return
            entries = self._selected_entries()
            key = entry_key(entries[index])

            def apply(changes):
                if changes:
                    self.overrides.setdefault(key, {}).update(changes)
                    self._recompute()

            self.push_screen(EditVMScreen(dict(self.vms[index])), apply)

        def _form_values(self):
            install = None
            if self.query_one("#f_install", Checkbox).value and profiles:
                index = self.query_one("#f_profile_install", Select).value
                label, cmd = profiles[index if isinstance(index, int) else 0]
                install = {
                    "branch": self.query_one("#f_branch", Select).value,
                    "prod": self.query_one("#f_prod", Checkbox).value,
                    "label": label,
                    "cmd": cmd,
                    "monitor": self.query_one("#f_monitor", Checkbox).value,
                }
            key = self.query_one("#f_key", Input).value.strip()
            return {
                "res_label": (
                    t("custom")
                    if self.profile == "custom"
                    else f"x{self.profile}"
                ),
                "ssh_key": os.path.expanduser(key) if key else "",
                # Un champ vidé retombe sur le fuseau de l'hôte plutôt que sur
                # rien : sans valeur, la VM démarrerait en UTC.
                "timezone": self.query_one("#f_tz", Input).value.strip()
                or ctx.get("timezone")
                or "",
                "install": install,
                "add_ssh_config": self.query_one("#f_sshcfg", Checkbox).value,
                "parallelism": self.query_one("#f_par", Select).value,
            }

        def action_preview(self) -> None:
            spec = build_spec(self.vms, domains, self._form_values())
            build = ctx.get("build_command")
            if not build:
                return
            lines = [build(vm, spec, True) for vm in spec["vms"]]
            self.push_screen(PreviewScreen(lines or [t("Nothing selected.")]))

        def action_deploy(self) -> None:
            if not self.vms:
                self.notify(t("Nothing selected."), severity="warning")
                return
            spec = build_spec(self.vms, domains, self._form_values())
            if not spec["vms"]:
                self.notify(
                    t("Nothing to create - every VM already exists."),
                    severity="warning",
                )
                return
            orphans = [r for r in self.rows if r["state"] == "orphan"]
            if orphans and not getattr(self, "_orphan_ack", False):
                # Un qcow2 orphelin fait échouer deploy_qemu : on prévient une
                # première fois, F5 à nouveau vaut confirmation.
                self._orphan_ack = True
                self.notify(
                    t("orphan disk - will FAIL")
                    + f" ({len(orphans)}) — "
                    + t("press F5 again to confirm"),
                    severity="error",
                    timeout=10,
                )
                return
            result["spec"] = spec
            self.exit()

        def action_cancel(self) -> None:
            self.exit()

    app = DeployForm()
    # Exposé pour les tests headless (run_app=False), qui pilotent l'app
    # eux-mêmes et ont besoin de lire la spec produite.
    app._result = result
    if not run_app:
        return app
    app.run()
    return result["spec"]


# --------------------------------------------------------------------------- #
# Vue de progression : un bloc repliable par VM
# --------------------------------------------------------------------------- #
def run_deploy_progress(jobs, parallelism, run_app: bool = True):
    """Déploie `jobs` = [(id, nom, argv)] en parallèle, un bloc repliable par
    VM. Renvoie [(nom, rc, sortie, durée)]. `run_app=False` renvoie l'app.

    Un bloc reste DÉPLIÉ tant que la VM tourne, se replie dès qu'elle réussit
    — et reste ouvert si elle échoue, puisque c'est ce qu'on veut lire."""
    import subprocess
    import threading

    from textual.app import App, ComposeResult
    from textual.containers import Vertical, VerticalScroll
    from textual.widgets import (
        Button,
        Collapsible,
        Footer,
        Header,
        RichLog,
        Static,
    )

    results = []

    def slug(name):
        """Identifiant de widget : Textual n'accepte ni point ni tiret en
        tête, et les noms de VM en contiennent."""
        return "vm_" + "".join(c if c.isalnum() else "_" for c in name)

    class Progress(App):
        CSS = """
        #blocks { height: 1fr; }
        RichLog { height: 14; border: solid $panel; }
        #summary { height: auto; color: $accent; padding: 0 1; }
        #hint { height: auto; color: $text-muted; padding: 0 1; }
        """
        BINDINGS = [
            ("c", "copy_current", t("Copy log")),
            ("C", "copy_all", t("Copy all logs")),
            ("q", "quit", t("Quit")),
        ]

        def __init__(self):
            super().__init__()
            self._out = {name: "" for _jid, name, _p in jobs}
            self._done = 0
            self._t0 = time.time()
            self._slots = threading.Semaphore(max(1, parallelism))

        def compose(self) -> ComposeResult:
            yield Header()
            with VerticalScroll(id="blocks"):
                for jid, name, _parts in jobs:
                    with Collapsible(
                        title=f"⏳ [{jid}] {name}",
                        collapsed=False,
                        id=slug(name),
                    ):
                        yield RichLog(
                            id=f"log_{slug(name)}",
                            highlight=False,
                            markup=False,
                            wrap=True,
                        )
            with Vertical():
                yield Static("", id="summary")
                yield Static(
                    f"  {t('c copy log · C copy all · q quit')}", id="hint"
                )
                yield Button(t("Copy all logs"), id="copyall")
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("Deploying")
            self._refresh_summary()
            for jid, name, parts in jobs:
                self.run_job(jid, name, parts)

        def _refresh_summary(self):
            self.query_one("#summary", Static).update(
                f"  {self._done}/{len(jobs)} — "
                f"{fmt_dur(time.time() - self._t0)}"
            )

        # `thread=True` : subprocess.run est bloquant ; le faire dans un
        # thread garde la boucle d'événements Textual fluide. Le sémaphore
        # borne les déploiements SIMULTANÉS — sans lui, demander « 4 en
        # parallèle » en lancerait autant que de VM.
        def run_job(self, jid, name, parts):
            def _job() -> None:
                with self._slots:
                    t0 = time.time()
                    try:
                        res = subprocess.run(
                            parts, capture_output=True, text=True
                        )
                        rc = res.returncode
                        out = (res.stdout or "") + (res.stderr or "")
                    except (OSError, subprocess.SubprocessError) as exc:
                        rc, out = 1, str(exc)
                self.call_from_thread(
                    self._finish, jid, name, rc, out, time.time() - t0
                )

            self.run_worker(_job, thread=True, group="deploy", exclusive=False)

        def _finish(self, jid, name, rc, out, secs):
            self._out[name] = out
            results.append((name, rc, out, secs))
            self._done += 1
            log = self.query_one(f"#log_{slug(name)}", RichLog)
            for line in out.strip().splitlines():
                log.write(line)
            block = self.query_one(f"#{slug(name)}", Collapsible)
            mark = "✅" if rc == 0 else "❌"
            block.title = f"{mark} [{jid}] {name} · {fmt_dur(secs)}" + (
                "" if rc == 0 else f" · rc={rc}"
            )
            # Un succès se replie (il n'y a plus rien à y lire) ; un échec
            # reste ouvert.
            block.collapsed = rc == 0
            self._refresh_summary()

        # -- presse-papiers (OSC 52 : traverse SSH) --------------------- #
        def _copy(self, text, what):
            payload, cut = clip_payload(text)
            if not payload.strip():
                self.notify(t("Nothing to copy."), severity="warning")
                return
            self.copy_to_clipboard(payload)
            note = f"{what} — {len(payload)} {t('chars')}"
            if cut:
                note += f" ({t('tail only, log was truncated')})"
            self.notify(
                note + "\n" + t("Needs an OSC 52 capable terminal."),
                title=t("Clipboard"),
                timeout=8,
            )

        def action_copy_current(self) -> None:
            focused = self.focused
            for _jid, name, _p in jobs:
                node = focused
                while node is not None:
                    if getattr(node, "id", None) == slug(name):
                        self._copy(self._out[name], name)
                        return
                    node = node.parent
            self.action_copy_all()

        def action_copy_all(self) -> None:
            blob = "\n".join(
                f"───── {name} ─────\n{self._out[name]}"
                for _jid, name, _p in jobs
            )
            self._copy(blob, t("all logs"))

        def on_button_pressed(self, event) -> None:
            if event.button.id == "copyall":
                self.action_copy_all()

    app = Progress()
    app._results = results  # lecture par les tests headless
    if not run_app:
        return app
    app.run()
    return results
