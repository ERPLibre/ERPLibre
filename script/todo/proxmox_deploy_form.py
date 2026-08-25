#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Formulaire de déploiement sur un hôte Proxmox VE.

Même écran que pour QEMU/KVM — catalogue à gauche, plan à droite, totaux
dessous — parce que c'est le même travail : choisir des systèmes, régler des
ressources, vérifier avant de lancer. Tout ce qui est commun vient de
`deploy_form_lib` (logique pure, socle CSS, fabrique des ressources) et de
`deploy_form_plan` (surcharges, verrous, exemplaires, renommage). Ne reste
ici que ce que Proxmox a en propre :

* l'hôte, choisi AVANT d'ouvrir l'écran — il faut ssh et sudo, et une invite
  de mot de passe pendant que Textual affiche casserait le terminal ;
* le stockage et le pont, LUS SUR L'HÔTE : « local-lvm » n'existe pas partout
  et un pont inventé fait échouer « qm create » ;
* le VMID, et l'adresse qui s'en déduit sur un pont interne.

Le formulaire ne touche à rien : il rend une spec. C'est l'appelant
(`ProxmoxMenuMixin._pve_deploy`) qui exécute.
"""

import os
import re

from script.todo.deploy_form_lib import (
    CSS_BASE,
    FREE,
    RES_FIELDS,
    SELECT_TO_FIELD,
    build_vms,
    disk_note,
    entry_key,
    gib,
    plan_rows,
    plan_totals,
    res_row_widgets,
    t,
)
from script.todo.deploy_form_plan import PlanMixin, preview_screen

# Aucun disque orphelin à craindre : les disques d'un Proxmox distant vivent
# dans un stockage que seul l'hôte connaît, jamais dans /var/lib/libvirt.
PAS_D_ORPHELIN = None


def assign_vmids(rows, used, start, ipconfig):
    """Pose un VMID libre et son adresse sur chaque VM À CRÉER.

    Proxmox refuse un VMID déjà pris, et il le dit APRÈS le téléchargement de
    l'image : on choisit donc avant, d'après ce que l'hôte déclare. Les VM qui
    existent déjà sont sautées — elles ont le leur.

    `ipconfig(vmid)` rend la ligne cloud-init : « ip=dhcp » sur un pont qui
    donne sur le LAN, une adresse fixe dérivée du VMID sur un pont interne.
    """
    pris = {int(v) for v in used or () if str(v).isdigit()}
    suivant = max(int(start or 0), 100)
    for r in rows:
        if r["state"] == "exists":
            continue
        while suivant in pris:
            suivant += 1
        pris.add(suivant)
        r["vm"]["vmid"] = suivant
        r["vm"]["ipconfig"] = ipconfig(suivant) if ipconfig else "ip=dhcp"
        suivant += 1
    return rows


def res_label(profile) -> str:
    """Comment le plan nomme le réglage commun choisi."""
    return t("custom") if profile == "custom" else f"x{profile}"


def build_spec(vms, existants, form):
    """La spec que le déploiement exécutera. Une VM qui existe déjà n'y entre
    pas : Proxmox refuserait le VMID, et on ne veut surtout pas l'écraser."""
    connus = set(existants)
    return {
        "host": form["host"],
        "storage": form["storage"],
        "bridge": form["bridge"],
        "res_label": form["res_label"],
        "vms": [vm for vm in vms if vm["name"] not in connus],
        "existing": [vm["name"] for vm in vms if vm["name"] in connus],
        "ssh_key": form["ssh_key"],
        "user": form.get("user") or "erplibre",
        "start": form["start"],
        "add_ssh_config": form["add_ssh_config"],
        "install": form["install"],
        "monitor": form["monitor"],
        "parallelism": form["parallelism"],
    }


def run_proxmox_form(ctx, run_app: bool = True):
    """Formulaire Proxmox. Renvoie une spec, None si annulé, {} pour retomber
    sur les invites textuelles. `run_app=False` rend l'instance sans la lancer
    (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Button,
        Checkbox,
        Footer,
        Header,
        Input,
        RadioButton,
        RadioSet,
        Select,
        SelectionList,
        Static,
    )

    SELECT_NULL = getattr(Select, "NULL", Select.BLANK)
    arches = ctx["arches"]
    catalog = ctx["catalog"]
    noms_pris = ctx["names"]
    vmids_pris = ctx["vmids"]
    branches = ctx.get("branches") or ["master"]
    profiles = ctx.get("install_profiles") or []
    stockages = ctx.get("storages") or []
    ponts = ctx.get("bridges") or []
    # {système: (libellé, commande)} — ce qu'un système impose d'installer.
    distro_profiles = ctx.get("distro_profiles") or {}
    # Les commandes qui ne posent PAS ERPLibre : sa marge disque ne les suit
    # pas. DÉDUITES des profils imposés — une seconde clé de contexte à tenir
    # en accord avec la première aurait fini par en différer, et la marge
    # serait revenue sans qu'on le voie. Jugé sur la commande effective de la
    # rangée : un choix explicite compte donc autant que la règle du système.
    no_erplibre = {
        impose[1].strip() for impose in distro_profiles.values() if impose
    }

    def entry_label(e):
        return f"{e['distro']} {e['version']}  [{e['arch']}]  {e['name']}"

    class ProxmoxForm(PlanMixin, App):
        TITLE = t("Deploy one or more ERPLibre VMs on Proxmox VE!")
        BINDINGS = [
            ("f5", "deploy", t("Deploy")),
            ("f4", "clear_vm", t("Reset VM")),
            ("f3", "preview", t("Preview")),
            ("f6", "select_all", t("All")),
            ("f8", "select_none", t("None")),
            ("escape", "cancel", t("Cancel")),
        ]
        # Le socle porte la mise en page et les modales ; ne reste ici que ce
        # qui nomme les widgets propres à Proxmox.
        CSS = (
            CSS_BASE
            + """
        SelectionList { height: 10; border: solid $panel; }
        RadioSet { height: auto; layout: horizontal; }
        .vmrow Select.vmbranch { width: 34; }
        #hostline { height: 1; color: $accent; padding: 0 1; }
        """
        )

        def __init__(self):
            super().__init__()
            self.arch = ctx.get("native") or arches[0]
            self.profile = "1"
            self.custom = {}
            self.overrides = {}
            self.locked = set()
            self.copies = {}
            self.rows = []
            self.vms = []
            self.result = None
            # Génération des widgets de rangée : un message qui arrive d'un
            # jeu périmé ne doit pas être pris pour une saisie.
            self._gen = 0
            self._shown_ids = ()
            self._syncing = False

        # ---------------------------------------------------------------- #
        # L'écran
        # ---------------------------------------------------------------- #
        def compose(self) -> ComposeResult:
            yield Header()
            hote = ctx["host"].get("label") or ctx["host"]["target"]
            yield Static(
                f"  {t('Proxmox host')} : {hote}"
                f"   {t('node')} : {ctx.get('node') or '?'}",
                id="hostline",
            )
            with Horizontal(id="body"):
                with VerticalScroll(id="fields"):
                    yield Static(t("Architecture"), classes="grouptitle")
                    with RadioSet(id="f_arch"):
                        for a in arches:
                            label = a if a != "all" else t("all archs")
                            yield RadioButton(label, value=a == self.arch)
                    yield Static(t("Catalog"), classes="grouptitle")
                    yield SelectionList(id="f_catalog")
                    yield Static(
                        t("Resources — applied to ALL VMs"),
                        classes="grouptitle",
                    )
                    with RadioSet(id="f_profile"):
                        for label in ("x1", "x2", "x3", "x4"):
                            yield RadioButton(label, value=label == "x1")
                        yield RadioButton(t("custom"))
                    # Les mêmes trois ressources qu'ailleurs, montées par la
                    # même fabrique : « libre… » révèle la saisie du dessous.
                    for champ, presets, etiquette in (
                        ("vcpus", ctx["cpu_presets"], t("vCPU")),
                        ("ram", ctx["ram_presets"], t("RAM: 2048 or 8G")),
                        ("disk", ctx["disk_presets"], t("Disk")),
                    ):
                        yield Select(
                            [
                                (
                                    (
                                        f"{v // 1024}G"
                                        if champ == "ram"
                                        else str(v)
                                    ),
                                    v,
                                )
                                for v in presets
                            ]
                            + [(t("free value…"), FREE)],
                            prompt=etiquette,
                            id=RES_FIELDS[champ][0][1:],
                            disabled=True,
                        )
                        yield Input(
                            placeholder=etiquette,
                            id=RES_FIELDS[champ][1][1:],
                            classes="freeval",
                            disabled=True,
                        )
                    yield Static(t("Proxmox VE"), classes="grouptitle")
                    yield Select(
                        [(s, s) for s in stockages],
                        value=(
                            ctx.get("storage")
                            or (stockages[0] if stockages else SELECT_NULL)
                        ),
                        prompt=t("Storage"),
                        allow_blank=not stockages,
                        id="f_storage",
                    )
                    yield Select(
                        [(b, b) for b in ponts],
                        value=(
                            ctx.get("bridge")
                            or (ponts[0] if ponts else SELECT_NULL)
                        ),
                        prompt=t("Bridge"),
                        allow_blank=not ponts,
                        id="f_bridge",
                    )
                    yield Static(f"  {t('First VMID')}")
                    yield Input(
                        value=str(ctx.get("next_vmid") or 100),
                        placeholder="100",
                        id="f_vmid",
                    )
                    yield Static(t("Access"), classes="grouptitle")
                    yield Static(f"  {t('SSH public key')}")
                    yield Input(
                        value=ctx.get("ssh_key") or "",
                        placeholder="~/.ssh/id_ed25519.pub",
                        id="f_key",
                    )
                    yield Checkbox(
                        t("Start the VM after creating it"),
                        value=True,
                        id="f_start",
                    )
                    yield Checkbox(
                        t("Add an entry to ~/.ssh/config"),
                        value=True,
                        id="f_sshcfg",
                    )
                    # La case commande TOUTE installation — ERPLibre, Odoo,
                    # mais aussi l'hyperviseur Proxmox VE d'une VM imbriquée.
                    # Nommée « ERPLibre », elle laissait croire qu'un système
                    # Proxmox s'installerait quand même.
                    yield Static(
                        t("Installation"),
                        id="t_install",
                        classes="grouptitle",
                    )
                    yield Checkbox(
                        t("Install software in the VM"),
                        value=True,
                        id="f_install",
                    )
                    yield Select(
                        [(lbl, i) for i, (lbl, _c) in enumerate(profiles)],
                        value=0 if profiles else SELECT_NULL,
                        allow_blank=not profiles,
                        id="f_profile_install",
                    )
                    yield Select(
                        [(b, b) for b in branches],
                        value=branches[0],
                        allow_blank=False,
                        id="f_branch",
                    )
                    # Hors de la section « Installation » : le suivi regarde la
                    # VM ARRIVER, même quand rien ne s'installe. Rangé dedans,
                    # il se serait grisé avec elle.
                    yield Static(
                        t("Monitoring and parallelism"),
                        classes="grouptitle",
                    )
                    yield Checkbox(
                        t("Follow the installation (dashboard)"),
                        value=True,
                        id="f_monitor",
                    )
                    yield Static(f"  {t('Parallelism')}")
                    yield Select(
                        [(str(n), n) for n in (1, 2, 3, 4)],
                        value=1,
                        allow_blank=False,
                        id="f_par",
                    )
                with Vertical(id="right"):
                    yield VerticalScroll(id="plan")
                    yield Static("", id="totals")
                    with Horizontal(id="actions"):
                        yield Button(t("Deploy"), variant="primary", id="go")
                        yield Button(t("Text prompts"), id="prompts")
                        yield Button(t("Cancel"), id="no")
            yield Footer()

        def on_mount(self) -> None:
            self._reload_catalog()
            self._sync_install_deps()

        # ---------------------------------------------------------------- #
        # Le plan
        # ---------------------------------------------------------------- #
        def _entries(self):
            return catalog.get(self.arch) or []

        def _selected_entries(self):
            choisis = set(self.query_one("#f_catalog", SelectionList).selected)
            return [e for e in self._entries() if entry_key(e) in choisis]

        def _presets(self):
            return {
                "vcpus": ctx["cpu_presets"],
                "ram": ctx["ram_presets"],
                "disk": ctx["disk_presets"],
            }

        def _reload_catalog(self) -> None:
            liste = self.query_one("#f_catalog", SelectionList)
            garde = set(liste.selected)
            liste.clear_options()
            for e in self._entries():
                cle = entry_key(e)
                liste.add_option((entry_label(e), cle, cle in garde))
            self._recompute()
            self._mount_rows()

        def _recompute(self) -> None:
            entries = self._plan_entries()
            self.vms = build_vms(
                entries,
                self.profile,
                ctx["base_vcpus"],
                ctx["host_cpu"],
                self.custom,
                self.overrides,
            )
            # Ce qu'un système IMPOSE d'installer, posé sur le MODÈLE : le
            # déploiement lit « install_cmd » VM par VM.
            for vm in self.vms:
                impose = distro_profiles.get(vm["distro"])
                if impose and not vm.get("install_cmd"):
                    vm["install_label"], vm["install_cmd"] = impose
            self.rows = plan_rows(
                self.vms, noms_pris, orphelin=lambda _n: False
            )
            # Le supplément d'ERPLibre ne vaut que pour les VM qui l'auront
            # vraiment : une VM Proxmox ne clonera pas le dépôt.
            if self.query_one("#f_install", Checkbox).value:
                commun = (self._install() or {}).get("cmd") or ""
                for row in self.rows:
                    cmd_vm = row["vm"].get("install_cmd") or commun
                    if cmd_vm.strip() not in no_erplibre:
                        row["disk_gb"] += ctx.get("extra_disk_gb", 0)
            for row, entry in zip(self.rows, entries):
                cle = entry_key(entry)
                row["custom"] = bool(self.overrides.get(cle))
                row["locked"] = cle in self.locked
            assign_vmids(
                self.rows,
                vmids_pris,
                self._vmid_start(),
                lambda vmid: (ctx.get("ipconfig") or (lambda _v: "ip=dhcp"))(
                    self._bridge(), vmid
                ),
            )
            self._render_plan()

        def _vmid_start(self):
            brut = self.query_one("#f_vmid", Input).value.strip()
            return (
                int(brut) if brut.isdigit() else (ctx.get("next_vmid") or 100)
            )

        def _bridge(self):
            valeur = self.query_one("#f_bridge", Select).value
            return "" if valeur is SELECT_NULL else valeur

        def _storage(self):
            valeur = self.query_one("#f_storage", Select).value
            return "" if valeur is SELECT_NULL else valeur

        def _row_head(self, index, row):
            """La ligne de titre du socle, plus ce que Proxmox ajoute : le
            VMID et l'adresse. Les deux sont décidés ICI et pas par l'hôte —
            les montrer avant de lancer est le seul moyen de les vérifier."""
            base = PlanMixin._row_head(self, index, row)
            vm = row["vm"]
            if row["state"] == "exists":
                return base
            adresse = (vm.get("ipconfig") or "").replace("ip=", "")
            return f"{base}   VMID {vm.get('vmid', '?')}   {adresse}"

        def _mount_rows(self) -> None:
            """(Re)construit le panneau droit.

            Le verrou couvre TOUT le montage : poser « value= » sur un Select
            fait émettre un Changed à Textual, que on_select_changed prendrait
            pour une saisie."""
            self._syncing = True
            self._gen += 1
            plan = self.query_one("#plan", VerticalScroll)
            plan.remove_children()
            cartes = []
            for i, r in enumerate(self.rows):
                vm = r["vm"]
                cle = self._row_key(i)
                item = self._plan_entries()[i]
                rangee = Horizontal(
                    Button("+", id=f"p{i}", classes="vmcopy"),
                    Button("✎", id=f"r{i}", classes="vmcopy"),
                    Button(
                        "🔒" if cle in self.locked else "🔓",
                        id=f"l{i}",
                        variant=(
                            "success" if cle in self.locked else "default"
                        ),
                        classes="vmlock",
                    ),
                    *res_row_widgets(
                        i,
                        vm,
                        self._presets(),
                        labels={"vcpus": t("vCPU")},
                        null=SELECT_NULL,
                    ),
                    (
                        Button("−", id=f"m{i}", classes="vmcopy")
                        if item.get("instance")
                        else Static("", classes="vmcopy")
                    ),
                    classes="vmrow",
                )
                cartes.append(
                    Vertical(
                        Static(self._row_head(i, r), id=f"h{i}"),
                        rangee,
                        classes=(
                            "vmcard locked" if cle in self.locked else "vmcard"
                        ),
                    )
                )

            # Marque de génération sur CHAQUE widget : « walk_children() » ne
            # voit rien avant le montage, les enfants attendent dans
            # « _pending_children ».
            def marquer(node):
                node._el_gen = self._gen
                for child in getattr(node, "_pending_children", None) or []:
                    marquer(child)

            for carte in cartes:
                marquer(carte)
            plan.mount_all(cartes)
            self._shown_ids = self._row_ids()
            self.call_after_refresh(self._after_mount_rows)

        def _after_mount_rows(self) -> None:
            self._sync_free_inputs()
            self._syncing = False

        def _render_plan(self) -> None:
            for i, r in enumerate(self.rows):
                try:
                    self.query_one(f"#h{i}", Static).update(
                        self._row_head(i, r)
                    )
                except Exception:
                    pass
            n, cpu, ram, disque = plan_totals(self.rows)
            libre = ctx.get("free_ram") or 0
            # La place du stockage CHOISI : elle change avec la liste, donc
            # elle se relit à chaque rendu plutôt qu'une fois au montage.
            place = gib((ctx.get("storage_avail") or {}).get(self._storage()))
            alertes = []
            if libre and ram > libre:
                alertes.append(t("more RAM than the host has free"))
            if place and disque > place:
                alertes.append(t("more disk than the storage has free"))
            alerte = f"   ⚠ {' · '.join(alertes)}" if alertes else ""
            self.query_one("#totals", Static).update(
                f"  {n} {t('VM')}   {cpu} vCPU   {ram} Mo RAM   "
                f"{disk_note(disque, place)}   {res_label(self.profile)}"
                f"   {t('storage')} {self._storage() or '?'}"
                f"   {t('bridge')} {self._bridge() or '?'}{alerte}"
            )

        def _refresh_after(self, remonter=False) -> None:
            """Recalcule, et ne remonte les rangées que si le JEU a changé :
            un remontage à chaque frappe volerait le focus."""
            self._recompute()
            if remonter or self._row_ids() != self._shown_ids:
                self._mount_rows()
            else:
                self._sync_free_inputs()

        # ---------------------------------------------------------------- #
        # Les messages
        # ---------------------------------------------------------------- #
        def on_selection_list_selected_changed(self, _event) -> None:
            self._refresh_after()

        def on_radio_set_changed(self, event) -> None:
            if event.radio_set.id == "f_arch":
                self.arch = arches[event.index]
                self._reload_catalog()
                return
            if event.radio_set.id == "f_profile":
                choix = ("1", "2", "3", "4", "custom")[event.index]
                self.profile = choix
                sur_mesure = choix == "custom"
                for champ in RES_FIELDS:
                    self.query_one(RES_FIELDS[champ][0], Select).disabled = (
                        not sur_mesure
                    )
                    if not sur_mesure:
                        self._show_free(champ, False)
                # Un réglage commun reprend la main sur les VM non figées :
                # c'est le sens même du mot « commun ».
                self._clear_overrides(tuple(RES_FIELDS))
                self._refresh_after(remonter=True)

        def _sync_install_deps(self) -> None:
            """Grise ce que la case rend sans effet : la branche et le profil.

            Le suivi n'en fait pas partie — il regarde la VM arriver même
            quand rien ne s'installe."""
            installe = self.query_one("#f_install", Checkbox).value
            for cible in ("#f_profile_install", "#f_branch"):
                try:
                    self.query_one(cible).disabled = not installe
                except Exception:
                    pass
            try:
                self.query_one("#t_install").set_class(not installe, "off")
            except Exception:
                pass

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id == "f_install":
                # Le disque d'ERPLibre entre — ou sort — du total.
                self._sync_install_deps()
                self._refresh_after()

        def on_input_changed(self, event) -> None:
            if event.input.id == "f_vmid":
                self._refresh_after()

        def on_input_submitted(self, event) -> None:
            ident = event.input.id or ""
            if ident in {RES_FIELDS[c][1][1:] for c in RES_FIELDS}:
                self._apply_free(ident.split("_", 1)[1])
                self._refresh_after(remonter=True)
                return
            if ident.startswith("c") and "_" in ident:
                rang, champ = ident[1:].split("_", 1)
                if rang.isdigit():
                    self._set_override(
                        int(rang), champ, self._read_row_free(int(rang), champ)
                    )
                    self._refresh_after()

        def on_select_changed(self, event) -> None:
            if self._syncing:
                return
            ident = event.select.id or ""
            # La marque de génération ne concerne QUE les widgets de rangée :
            # un widget global n'en porte pas. L'exiger de tous revenait à
            # ignorer chaque réglage commun — mesuré, ni le stockage, ni la
            # RAM générale n'atteignaient le plan.
            if re.match(r"v\d+_", ident) and not self._is_current(
                event.select
            ):
                return
            if ident in ("f_storage", "f_bridge"):
                self._refresh_after()
                return
            # Réglage commun : « libre… » révèle la saisie, une valeur
            # s'applique à toutes les VM non figées.
            champ = SELECT_TO_FIELD.get(ident)
            if champ:
                if event.value is FREE:
                    self._show_free(champ, True)
                    self.query_one(RES_FIELDS[champ][1], Input).focus()
                elif event.value is not SELECT_NULL:
                    self._show_free(champ, False)
                    self.custom[champ] = event.value
                    self._clear_overrides((champ,))
                    self._refresh_after(remonter=True)
                return
            # Réglage d'UNE rangée.
            if ident.startswith("v") and "_" in ident:
                rang, champ = ident[1:].split("_", 1)
                if not rang.isdigit() or champ not in RES_FIELDS:
                    return
                index = int(rang)
                if event.value is FREE:
                    self._row_free(index, champ, True)
                    self._set_override(
                        index, champ, self._read_row_free(index, champ)
                    )
                elif event.value is not SELECT_NULL:
                    # L'écho du montage n'est pas une saisie : sans ce test,
                    # les trois champs de chaque VM se surchargeaient dès
                    # l'affichage et toutes les rangées portaient la marque ✎.
                    if self._row_echo(index, champ, event.value):
                        return
                    self._row_free(index, champ, False)
                    self._set_override(index, champ, event.value)
                    self._refresh_after()

        def on_button_pressed(self, event) -> None:
            ident = event.button.id or ""
            if ident == "go":
                self.action_deploy()
            elif ident == "no":
                self.action_cancel()
            elif ident == "prompts":
                # Retour aux invites textuelles : {} n'est pas None, et
                # l'appelant sait faire la différence entre « annulé » et
                # « pose-moi les questions à l'ancienne ».
                self.result = {}
                self.exit()
            elif ident.startswith("p") and ident[1:].isdigit():
                self._add_copy(int(ident[1:]), 1)
            elif ident.startswith("m") and ident[1:].isdigit():
                self._add_copy(int(ident[1:]), -1)
            elif ident.startswith("r") and ident[1:].isdigit():
                self._rename(int(ident[1:]))
            elif ident.startswith("l") and ident[1:].isdigit():
                index = int(ident[1:])
                self._set_lock(index, self._row_key(index) not in self.locked)

        # ---------------------------------------------------------------- #
        # Les actions
        # ---------------------------------------------------------------- #
        def _install(self):
            if not self.query_one("#f_install", Checkbox).value:
                return None
            index = self.query_one("#f_profile_install", Select).value
            label, cmd = (
                profiles[index]
                if profiles and isinstance(index, int)
                else ("", "")
            )
            return {
                "branch": self.query_one("#f_branch", Select).value,
                "label": label,
                "cmd": cmd,
            }

        def _form_values(self):
            cle = self.query_one("#f_key", Input).value.strip()
            return {
                "host": ctx["host"],
                "storage": self._storage(),
                "bridge": self._bridge(),
                "res_label": res_label(self.profile),
                "ssh_key": os.path.expanduser(cle) if cle else "",
                "start": self.query_one("#f_start", Checkbox).value,
                "add_ssh_config": self.query_one("#f_sshcfg", Checkbox).value,
                "install": self._install(),
                # Le suivi est demandé au NIVEAU DU DÉPLOIEMENT : une VM sans
                # ERPLibre se suit aussi (cloud-init, puis relevé système).
                "monitor": self.query_one("#f_monitor", Checkbox).value,
                "parallelism": self.query_one("#f_par", Select).value,
            }

        def action_deploy(self) -> None:
            spec = build_spec(self.vms, noms_pris, self._form_values())
            if not spec["vms"]:
                self.notify(t("Nothing to deploy."), severity="warning")
                return
            if not spec["storage"]:
                self.notify(
                    t("No storage able to hold a VM disk."), severity="error"
                )
                return
            if not spec["bridge"]:
                self.notify(t("No bridge on the host."), severity="error")
                return
            self.result = spec
            self.exit()

        def action_preview(self) -> None:
            build = ctx.get("build_command")
            if not build:
                return
            spec = build_spec(self.vms, noms_pris, self._form_values())
            lignes = ["\n".join(build(vm, spec)) for vm in spec["vms"]] or [
                t("Nothing selected.")
            ]
            self.push_screen(preview_screen()(lignes))

        def action_clear_vm(self) -> None:
            """Rend au réglage commun la VM sous le curseur (et son verrou)."""
            index = self._focused_row()
            if index is None:
                return
            cle = self._row_key(index)
            self.locked.discard(cle)
            self.overrides.pop(cle, None)
            self._refresh_after(remonter=True)

        def action_select_all(self) -> None:
            self.query_one("#f_catalog", SelectionList).select_all()

        def action_select_none(self) -> None:
            self.query_one("#f_catalog", SelectionList).deselect_all()

        def action_cancel(self) -> None:
            self.result = None
            self.exit()

    app = ProxmoxForm()
    if not run_app:
        return app
    app.run()
    return app.result
