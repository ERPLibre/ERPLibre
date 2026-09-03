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
import re

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


from script.todo.deploy_form_lib import (  # noqa: F401
    CLIP_LIMIT,
    CSS_BASE,
    FREE,
    INPUT_TO_FIELD,
    RES_FIELDS,
    RES_FMT,
    SELECT_TO_FIELD,
    apply_overrides,
    apply_profile,
    branch_default,
    branch_order,
    build_spec,
    build_vms,
    clean_hostname,
    clip_payload,
    copy_name,
    disk_gb,
    disk_note,
    entry_key,
    expand_copies,
    fmt_dur,
    gib,
    parse_disk,
    parse_ram,
    plan_rows,
    plan_totals,
    positive_int,
    res_choices,
    res_labels,
    res_row_widgets,
    res_value,
    run_deploy_progress,
    vm_name,
    vm_status,
)

# Le socle commun aux deux formulaires (QEMU/KVM et Proxmox VE). Réexporté
# tel quel : les appelants historiques importent encore ces noms ICI.
from script.todo.deploy_form_extras import SERVER, ExtrasMixin
from script.todo.deploy_form_plan import (  # noqa: F401
    PlanMixin,
    preview_screen,
    rename_screen,
)


# --------------------------------------------------------------------------- #
# Formulaire Textual
# --------------------------------------------------------------------------- #
def run_deploy_form(ctx, run_app: bool = True):
    """Formulaire de déploiement. Renvoie une spec, ou None si annulé.
    `run_app=False` renvoie l'instance sans la lancer (tests headless)."""
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

    # Textual 8 a ramené Select.BLANK à un alias déprécié valant False ; le
    # sentinelle « rien de choisi » est Select.NULL. Comparer à BLANK ne
    # filtrait donc plus rien, et NoSelection — dépourvu de __bool__, donc
    # tenu pour vrai — passait pour une valeur jusque dans les totaux.
    SELECT_NULL = getattr(Select, "NULL", Select.BLANK)

    catalog = ctx["catalog"]
    arches = ctx["arches"]
    domains = set(ctx.get("domains") or [])
    profiles = ctx.get("install_profiles") or []
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
    branches = branch_order(
        ctx.get("branches") or ["master"], ctx.get("branch_current")
    )
    host_cpu = ctx.get("host_cpu") or 2
    free_ram = ctx.get("free_ram") or 0
    free_disk = ctx.get("free_disk") or 0
    total_disk = ctx.get("total_disk") or 0
    base_vcpus = ctx.get("base_vcpus") or 2
    extra_disk = ctx.get("extra_disk_gb") or 0
    # {clé de saveur: suffixe de nom}, fourni par todo.py qui décrit les
    # saveurs — on ne le redéfinit pas ici.
    desktop_suffixes = dict(ctx.get("desktop_suffixes") or {})
    defaults = ctx.get("defaults") or {}
    result = {"spec": None}

    AUTO = "__auto__"

    def entry_label(e):
        star = " *" if e.get("default") else ""
        return (
            f"{e['distro']} {e['version']}{star} [{e['arch']}]  "
            f"RAM≥{e['ram']}Mo  {e['disk']}"
        )

    class DeployForm(ExtrasMixin, PlanMixin, App):
        # Le socle porte la mise en page et les modales ; ne reste ici que ce
        # qui nomme les widgets propres à QEMU/KVM.
        CSS = (
            CSS_BASE
            + """
        SelectionList { height: 10; border: solid $panel; }
        RadioSet { height: auto; layout: horizontal; }
        /* Ces deux règles portent « .vmrow Select » EN PLUS de leur classe :
        « .vmrow Select » (une classe + un type) l'emporte sur « .vmbranch »
        (une classe) par spécificité CSS. Écrites simplement, elles étaient
        silencieusement écrasées à 15 — et le test, qui ne vérifiait que la
        présence de la classe, passait sans rien prouver. La branche porte des
        noms longs (« 1.6.0 », « develop », « feature/xyz ») : trop étroite, la
        liste les tronque et on ne sait plus ce qu'on a choisi. */
        .vmrow Select.vmbranch { width: 34; }
        .vmrow Select.vmprof { width: 40; }
        """
        )
        # Touches de fonction plutôt que ctrl+lettre : ctrl+p est pris par la
        # palette de commandes de Textual, et une lettre seule serait avalée
        # par le champ de saisie qui a le focus.
        BINDINGS = [
            ("f5", "deploy", t("Deploy")),
            ("f4", "clear_vm", t("Reset VM")),
            ("f3", "preview", t("Preview")),
            ("f9", "dump_state", t("Diagnostic dump")),
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
            self._free = {}
            self.overrides = {}
            # Vrai pendant qu'on repositionne les widgets nous-mêmes : sans
            # ce verrou, poser une valeur déclencherait on_select_changed, qui
            # réécrirait une surcharge — une boucle qui se nourrit seule.
            self._syncing = False
            # Jeu de VM actuellement monté dans le panneau droit.
            self._shown_ids = ()
            self.extras_init(ctx, branches, profiles)
            # Génération du jeu de rangées monté. Les identifiants de widgets
            # portent un RANG, et le rang se décale quand on coche ou décoche
            # une entrée : un événement émis par un widget déjà détruit
            # s'appliquerait alors à la VM qui a pris sa place. Chaque widget
            # de rangée retient sa génération ; ceux d'une génération périmée
            # sont ignorés.
            self._gen = 0
            # VM dont les ressources sont FIGÉES, par identité de catalogue.
            # Distinct des surcharges : une VM peut être modifiée sans être
            # verrouillée, et le verrou fige TOUT, pas seulement ce qu'on a
            # touché.
            self.locked = set()
            # {clé de base: nombre d'exemplaires EN PLUS du premier}.
            self.copies = {}
            self.rows = []
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
                    yield Static(
                        t("Resources — applied to ALL VMs"),
                        classes="grouptitle",
                    )
                    with RadioSet(id="f_profile"):
                        for label in ("x1", "x2", "x3", "x4"):
                            yield RadioButton(label, value=label == "x1")
                        yield RadioButton(t("custom"))
                    # Chaque ressource offre ses suggestions plus « libre… »,
                    # qui révèle une saisie. C'est l'équivalent TUI de la règle
                    # de la CLI : une lettre choisit une suggestion, un chiffre
                    # vaut pour lui-même.
                    yield Select(
                        [(str(c), c) for c in ctx["cpu_presets"]]
                        + [(t("free value…"), FREE)],
                        prompt=t("vCPU"),
                        id="f_vcpus",
                        disabled=True,
                    )
                    yield Input(
                        placeholder=t("vCPU"),
                        id="c_vcpus",
                        classes="freeval",
                        disabled=True,
                    )
                    yield Select(
                        [
                            (f"{m} ({m // 1024}G)", m)
                            for m in ctx["ram_presets"]
                        ]
                        + [(t("free value…"), FREE)],
                        prompt=t("RAM: 2048 or 8G"),
                        id="f_ram",
                        disabled=True,
                    )
                    yield Input(
                        placeholder=t("RAM: 2048 or 8G"),
                        id="c_ram",
                        classes="freeval",
                        disabled=True,
                    )
                    yield Select(
                        [(d, d) for d in ctx["disk_presets"]]
                        + [(t("free value…"), FREE)],
                        prompt=t("Disk"),
                        id="f_disk",
                        disabled=True,
                    )
                    yield Input(
                        placeholder=t("Disk (e.g. 250G, 1.5T)"),
                        id="c_disk",
                        classes="freeval",
                        disabled=True,
                    )
                    yield Static(
                        f"  {t('The profile and these fields change EVERY VM.')}"
                        f"\n  {t('A VM edited on the right (marked) keeps its own.')}",
                        id="scopetarget",
                    )
                    yield from self.compose_vm_type()
                    # La case commande TOUTE installation — ERPLibre, Odoo, mais
                    # aussi l'hyperviseur Proxmox VE. Nommée « ERPLibre », elle
                    # laissait croire qu'un système Proxmox s'installerait
                    # quand même : rapporté, une VM Proxmox est restée une
                    # Debian nue. Placée SOUS le type de VM, juste avant les
                    # sections qu'elle commande.
                    yield Static(
                        t("Installation"),
                        id="t_install",
                        classes="grouptitle",
                    )
                    yield Checkbox(
                        t("Install software in the VM"),
                        value=defaults.get("install", True),
                        id="f_install",
                    )
                    yield Select(
                        [(b, b) for b in branches],
                        value=branch_default(
                            branches, ctx.get("branch_current")
                        ),
                        allow_blank=False,
                        id="f_branch",
                    )
                    yield Select(
                        [(lbl, i) for i, (lbl, _c) in enumerate(profiles)],
                        value=0 if profiles else SELECT_NULL,
                        allow_blank=not profiles,
                        id="f_profile_install",
                    )
                    yield from self.compose_install_extras()
                    yield from self.compose_timezone()
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
                    yield from self.compose_python()
                    # Hors de la section « Installation » : le suivi
                    # regarde la VM ARRIVER, même quand rien ne s'installe.
                    # Rangé dans cette section, il se serait grisé avec elle —
                    # et décocher ERPLibre avait déjà fait disparaître le
                    # tableau de bord une fois.
                    yield Static(
                        t("Monitoring and parallelism"),
                        id="t_deploy",
                        classes="grouptitle",
                    )
                    yield Checkbox(
                        t("Monitoring dashboard"),
                        value=defaults.get("monitor", True),
                        id="f_monitor",
                    )
                    # Indépendante du type de VM : une machine sans console
                    # peut vouloir un virtio-gpu accéléré — rendu hors écran,
                    # ou émulateur qui tourne dedans. Sans écran,
                    # « egl-headless » n'ouvre aucun port.
                    yield Checkbox(
                        t("3D acceleration (host GPU), even without a screen"),
                        value=defaults.get("gpu3d", False),
                        id="f_gpu3d",
                    )
                    # Le parallélisme reste dans « Déploiement » : c'est le
                    # nombre de VM menées de front, pas une option
                    # d'installation.
                    yield Static(f"  {t('Parallelism')}")
                    # Cochée, la case donne une exécution PAR installation :
                    # le plafond du nombre de CPU ne s'applique plus. Décochée,
                    # le nombre reprend la main, et son défaut suit l'hôte —
                    # la CLI comptait déjà les CPU, la TUI restait figée à 4.
                    yield Checkbox(
                        t("One run per install"),
                        value=defaults.get("par_per_install", True),
                        id="f_par_all",
                    )
                    yield Select(
                        [(str(n), n) for n in range(1, host_cpu + 1)],
                        value=host_cpu,
                        allow_blank=False,
                        disabled=True,
                        id="f_par",
                    )
                with Vertical(id="right"):
                    # Une liste de widgets, pas un tableau : chaque VM porte
                    # SES listes déroulantes, modifiables sur place. Un
                    # DataTable ne sait pas héberger de widget.
                    yield VerticalScroll(id="plan")
                    yield Static("", id="totals")
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("Deploy ERPLibre VM(s)!")
            self._reload_catalog(first_load=True)
            self._sync_install_deps()

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

        # ------------------------------------------------------------ #
        # Ce que le socle du plan attend de nous
        # ------------------------------------------------------------ #
        def _presets(self):
            """Choix offerts par ressource. Le socle s'en sert pour savoir
            quand une valeur est « libre »."""
            return {
                "vcpus": ctx["cpu_presets"],
                "ram": ctx["ram_presets"],
                "disk": ctx["disk_presets"],
            }

        def _auto_name(self, index):
            """Le nom du catalogue, suffixé du bureau : ce que la VM
            reprendrait si on effaçait son nom."""
            return vm_name(
                self._plan_entries()[index]["name"],
                self.rows[index]["vm"].get("desktop"),
                desktop_suffixes,
            )

        def _lock_fields(self, index):
            """TOUT ce que la VM tient d'un choix commun est recopié, pas
            seulement les ressources : la branche et le profil Odoo en font
            partie. Les oublier laissait une VM « figée » changer de version
            d'ERPLibre dès qu'on touchait au choix générique, ce qui vide le
            mot de son sens.

            Les deux se résolvent AVANT d'être figés : « » y signifie « celle
            du formulaire », et geler une chaîne vide ne gèlerait rien."""
            vm = self.rows[index]["vm"]
            return {
                "vcpus": vm["vcpus"],
                "ram": vm["ram"],
                "disk": vm["disk"],
                "desktop": vm.get("desktop") or "",
                "branch": vm.get("branch") or self._branch(),
                "install_cmd": (
                    vm.get("install_cmd") or self._row_default_cmd(index)
                ),
                "install_label": (
                    vm.get("install_label")
                    or (
                        profiles[self._row_profile_index(index)][0]
                        if profiles
                        else ""
                    )
                ),
            }

        def _recompute(self):
            entries = self._plan_entries()
            self.vms = build_vms(
                entries,
                self.profile,
                base_vcpus,
                host_cpu,
                self.custom,
                self.overrides,
                self._default_desktop(),
                desktop_suffixes,
            )
            # Ce qu'un système IMPOSE d'installer, posé sur le MODÈLE et pas
            # seulement à l'écran : le déploiement lit « install_cmd » VM par
            # VM, et une VM Proxmox laissée à vide recevait la commande
            # commune — donc ERPLibre et Odoo 18 sur un hyperviseur.
            for vm in self.vms:
                impose = distro_profiles.get(vm["distro"])
                if impose and not vm.get("install_cmd"):
                    vm["install_label"], vm["install_cmd"] = (
                        impose[0],
                        impose[1],
                    )
            self.rows = plan_rows(self.vms, domains)
            # ERPLibre et GNOME pèsent chacun sur le disque, et se cumulent.
            # Le supplément d'ERPLibre ne vaut que pour les VM qui l'auront
            # VRAIMENT : l'ajouter à une VM Proxmox gonflait son disque de
            # cinq gigaoctets pour un dépôt qu'elle ne clonera pas.
            installe = self.query_one("#f_install", Checkbox).value
            # Le bureau pèse sur le disque de la VM QUI LE PORTE, et d'elle
            # seule : un supplément commun mentait dès que les types
            # différaient d'une machine à l'autre.
            tools = self._vm_tools()
            for i, row in enumerate(self.rows):
                cmd_vm = (
                    row["vm"].get("install_cmd") or self._profile_cmd() or ""
                )
                if installe and cmd_vm.strip() not in no_erplibre:
                    row["disk_gb"] += extra_disk
                # Le bureau et les outils ne pèsent que sur les VM qui
                # les reçoivent RÉELLEMENT : Android Studio n'existe qu'en
                # x86_64, les extensions GNOME n'ont de sens que sous GNOME.
                row["disk_gb"] += self._extras_disk_gb(row["vm"], tools)
            # Le plan doit MONTRER qu'une VM a été personnalisée : sans marque,
            # deux lignes aux ressources différentes n'ont aucune explication à
            # l'écran, et la surcharge est oubliée à la relecture. Le drapeau
            # vit sur la ligne d'affichage, jamais sur la VM : celle-ci part
            # telle quelle dans la spec, que la CLI produit à l'identique.
            for row, entry in zip(self.rows, entries):
                key = entry_key(entry)
                row["custom"] = bool(self.overrides.get(key))
                row["locked"] = key in self.locked
            self._render_plan()
            self.render_extras()

        # -- panneau droit : une rangée de widgets par VM ---------------- #
        def _mount_rows(self) -> None:
            """(Re)construit le panneau droit.

            Le verrou couvre TOUT le montage : poser « value= » sur un Select
            fait émettre un Changed à Textual, que on_select_changed prenait
            pour une saisie. Résultat mesuré — les trois champs de CHAQUE VM
            recevaient une surcharge dès l'affichage, le profil x1..x4 ne
            pouvait plus rien changer, et toutes les lignes portaient la
            marque ✎. Il est relâché après le rafraîchissement, une fois ces
            messages consommés."""
            self._syncing = True
            self._gen += 1
            plan = self.query_one("#plan", VerticalScroll)
            plan.remove_children()
            widgets = []
            for i, r in enumerate(self.rows):
                vm = r["vm"]
                item = self._plan_entries()[i]
                key = entry_key(item)
                row = Horizontal(
                    # « + » ajoute un exemplaire de CETTE entrée ; « - » ne
                    # s'affiche que sur une copie, pour qu'on ne puisse pas
                    # retirer l'original par mégarde.
                    Button("+", id=f"p{i}", classes="vmcopy"),
                    Button("✎", id=f"r{i}", classes="vmcopy"),
                    Button(
                        "🔒" if key in self.locked else "🔓",
                        id=f"l{i}",
                        variant="success" if key in self.locked else "default",
                        classes="vmlock",
                    ),
                    # Le triplet vCPU / RAM / disque vient du socle
                    # commun : c'est la partie que le formulaire Proxmox pose
                    # à l'identique, et la seule que les deux dupliquaient.
                    *res_row_widgets(
                        i,
                        vm,
                        {
                            "vcpus": ctx["cpu_presets"],
                            "ram": ctx["ram_presets"],
                            "disk": ctx["disk_presets"],
                        },
                        labels={"vcpus": "vCPU"},
                        null=SELECT_NULL,
                    ),
                    (
                        Button("−", id=f"m{i}", classes="vmcopy")
                        if item.get("instance")
                        else Static("", classes="vmcopy")
                    ),
                    *self.install_row_widgets(i, SELECT_NULL),
                    classes="vmrow",
                )
                widgets.append(
                    Vertical(
                        Static(self._row_head(i, r), id=f"h{i}"),
                        row,
                        # Pas d'id sur la carte : « remove_children() » est
                        # ASYNCHRONE, les anciennes sont encore là au montage
                        # et Textual refuse deux frères de même id. Les ids
                        # des champs vivent un niveau plus bas, dans un parent
                        # neuf — la collision ne les touche pas. On atteint
                        # donc la carte par son RANG.
                        classes=(
                            "vmcard locked" if key in self.locked else "vmcard"
                        ),
                    )
                )

            # Marque de génération, posée sur CHAQUE widget de rangée.
            # « walk_children() » ne voit RIEN avant le montage : les enfants
            # passés au constructeur attendent dans « _pending_children ».
            def mark(node):
                node._el_gen = self._gen
                for child in getattr(node, "_pending_children", None) or []:
                    mark(child)

            for card in widgets:
                mark(card)
            # Le montage vient APRÈS le marquage, jamais avant : « mount_all »
            # consomme « _pending_children » et le vide. Marquer ensuite était
            # une COURSE — gagnée sur une machine, perdue sur une autre. Perdue,
            # les listes des rangées n'avaient plus de génération, TOUS les
            # changements par VM étaient rejetés en silence, et seuls les
            # réglages globaux semblaient agir.
            if widgets:
                plan.mount_all(widgets)
            self._shown_ids = self._row_ids()
            # Les saisies libres ne se révèlent qu'après le montage : leur
            # style ne peut pas être touché avant qu'elles existent.
            self.call_after_refresh(self._after_mount_rows)

        def _after_mount_rows(self) -> None:
            self._sync_install_deps()
            self._sync_free_inputs()
            self._syncing = False

        def _refresh_row_widgets(self) -> None:
            """Remet les listes de chaque rangée sur ce que la VM vaut MAINTENANT.

            Sans cela, changer le profil x1..x4 mettait les totaux à jour mais
            laissait les listes sur leurs anciennes valeurs : l'écran affichait
            8192 pendant que la VM valait 4096. Les rangées ne sont remontées
            que si le JEU de VM change — pour ne pas voler le focus — donc ce
            rafraîchissement doit se faire à la main.

            Aucun risque de boucle : on_select_changed ignore une valeur déjà
            égale à celle du modèle, et le modèle vient précisément d'être
            recalculé."""
            for i, r in enumerate(self.rows):
                vm = r["vm"]
                for field, presets in (
                    ("vcpus", ctx["cpu_presets"]),
                    ("ram", ctx["ram_presets"]),
                    ("disk", ctx["disk_presets"]),
                ):
                    try:
                        sel = self.query_one(f"#v{i}_{field}", Select)
                    except Exception:
                        continue
                    # Une liste posée sur « libre… » ne doit PAS être remise
                    # sur une valeur : l'utilisateur vient de la choisir, et
                    # tant qu'il n'a rien tapé la VM vaut encore celle du
                    # profil — on la lui reprendrait sous les doigts.
                    if sel.value is FREE:
                        continue
                    # Une valeur libre déjà saisie n'est dans aucune liste :
                    # liste vide, la saisie à côté porte le nombre.
                    sel.value = (
                        vm[field] if vm[field] in presets else SELECT_NULL
                    )
                for wid, value in (
                    (f"#v{i}_type", vm.get("desktop") or SERVER),
                    (f"#v{i}_branch", vm.get("branch") or self._branch()),
                    (f"#v{i}_prof", self._row_profile_index(i)),
                ):
                    try:
                        self.query_one(wid, Select).value = value
                    except Exception:
                        pass
            self._sync_free_inputs()

        def _render_plan(self):
            # Le JEU de VM a-t-il changé ? Si oui on remonte les widgets, sinon
            # on se contente des titres : remonter à chaque frappe volerait le
            # focus au champ en cours de saisie.
            if self._row_ids() != self._shown_ids:
                self._mount_rows()
            else:
                for i, r in enumerate(self.rows):
                    try:
                        self.query_one(f"#h{i}", Static).update(
                            self._row_head(i, r)
                        )
                    except Exception:
                        pass
                self._refresh_row_widgets()
            if not self.rows:
                # Rien de coché : un total à zéro n'apprend rien, on dit
                # plutôt comment remplir la liste.
                self.query_one("#totals", Static).update(
                    f"  {t('Tick what to deploy')} — "
                    f"{t('F7 main versions · F6 all')}"
                )
                return
            n, cpus, ram, disk = plan_totals(self.rows)
            # Une liste et non un seul avertissement : la RAM, les cœurs et le
            # disque sont trois limites distinctes, et n'en montrer qu'une
            # cachait les autres — on corrigeait la première pour découvrir la
            # suivante au déploiement.
            alertes = []
            if free_ram and ram > free_ram:
                alertes.append(t("> host free RAM"))
            if free_disk and disk > free_disk:
                alertes.append(t("> host free disk"))
            if cpus > host_cpu:
                alertes.append(f"{t('> host cores')} ({host_cpu})")
            warn = f"   ⚠ {' · '.join(alertes)}" if alertes else ""
            dupes = len({vm["name"] for vm in self.vms}) != len(self.vms)
            dup_txt = (
                f"\n  ⚠ {t('Duplicate names detected; keeping as entered.')}"
                if dupes
                else ""
            )
            # Une VM DÉJÀ DÉFINIE n'est pas recréée : elle ne consomme rien
            # de neuf, donc plan_totals l'écarte. Mais un total à zéro sans
            # explication se lit comme un bogue — on a cru que les réglages
            # par VM n'avaient aucun effet, alors qu'ils portaient sur une
            # machine qui ne sera pas créée.
            skipped = sum(1 for r in self.rows if r["state"] == "exists")
            skip_txt = (
                f"   ({skipped} {t('already defined, not counted')})"
                if skipped
                else ""
            )
            self.query_one("#totals", Static).update(
                f"  {n} {t('VMs')} · {cpus} vCPU · {ram} Mo · "
                f"{disk_note(disk, free_disk, total_disk)}"
                f"{skip_txt}{warn}{dup_txt}"
            )

        # -- réactions aux champs -------------------------------------- #
        def on_radio_set_changed(self, event) -> None:
            if event.radio_set.id == "f_arch":
                self.arch = arches[event.radio_set.pressed_index]
                self._reload_catalog()
            elif event.radio_set.id == "f_type":
                self._clear_overrides(("desktop",))
                # Le type est l'autre moitié de la décision : un bureau seul
                # garde le magasin d'applications et les outils utiles.
                self._sync_install_deps()
                # Recalcul : le disque annonce inclut le bureau, et la
                # colonne Statut affiche le type de VM.
                self._recompute()
            elif event.radio_set.id == "f_profile":
                index = event.radio_set.pressed_index
                self.profile = "custom" if index == 4 else str(index + 1)
                # Un multiplicateur x1..x4 ne touche QUE les vCPU et la RAM —
                # apply_profile y laisse le disque du catalogue. Y effacer une
                # taille de disque réglée à la main la faisait disparaître sans
                # rien mettre à la place : on revenait à 20G sans l'avoir
                # demandé. Le disque n'est rendu au commun que par le profil
                # « personnalisé », qui en porte un.
                fields = ("vcpus", "ram")
                if self.profile == "custom":
                    fields += ("disk",)
                self._clear_overrides(fields)
                custom = self.profile == "custom"
                for field, (sel, _inp) in RES_FIELDS.items():
                    self.query_one(sel, Select).disabled = not custom
                    self._show_free(field, custom and self._free.get(field))
                self._recompute()

        # -- rangées du panneau droit ------------------------------- #
        def on_selection_list_selected_changed(self, event) -> None:
            self._recompute()

        def on_select_changed(self, event) -> None:
            if self._syncing:
                return
            wid = event.select.id or ""
            row = re.match(r"v(\d+)_(vcpus|ram|disk|type|branch|prof)$", wid)
            if row and not self._is_current(event.select):
                # Widget d'une génération périmée : son rang ne désigne plus
                # la même VM. L'appliquer écraserait le réglage d'une voisine.
                return
            if row:
                index, field = int(row.group(1)), row.group(2)
                if index >= len(self.rows):
                    return
                # Poser « value= » au montage fait émettre un Changed que
                # Textual délivre APRÈS coup : un verrou temporel ne l'attrape
                # pas — mesuré, les trois champs de chaque VM se retrouvaient
                # surchargés dès l'affichage et le profil x1..x4 devenait
                # inopérant. On compare donc à ce que le modèle dit déjà : une
                # valeur identique n'est pas une saisie, c'est l'écho.
                #
                # Cas limite assumé : choisir explicitement la valeur que le
                # profil donne déjà n'enregistre pas de surcharge. La VM
                # suivra donc le profil s'il change — ce qui est aussi le plus
                # attendu quand on n'a rien changé de visible.
                if self.extras_on_row_select(event, index, field):
                    return
                # Ne restent ici que les RESSOURCES : elles n'ont pas de
                # défaut à comparer, mais une saisie libre à révéler.
                if event.value is FREE:
                    self._row_free(index, field, True)
                    self._set_override(
                        index, field, self._read_row_free(index, field)
                    )
                elif event.value is not SELECT_NULL:
                    if self._row_echo(index, field, event.value):
                        return
                    self._row_free(index, field, False)
                    self._set_override(index, field, event.value)
                self._recompute()
                return
            # Les choix GLOBAUX de branche et de profil ne portent aucune
            # valeur de ressource : ils tombaient donc dans le « return »
            # ci-dessous sans rien recalculer, et les rangées restaient sur
            # l'ancienne version. Elles n'en gardent pas de copie — « » y
            # veut dire « celle du formulaire » — il suffit de redessiner.
            if self.extras_on_select(event):
                return
            if event.select.id in ("f_branch", "f_profile_install"):
                self._clear_overrides(
                    ("branch",)
                    if event.select.id == "f_branch"
                    else ("install_cmd",)
                )
                self._recompute()
                return
            field = SELECT_TO_FIELD.get(event.select.id)
            if not field:
                return
            if event.value is FREE:
                # La valeur retenue est celle de la saisie, pas ce choix-ci.
                self._free[field] = True
                self._show_free(field, True)
                self.query_one(RES_FIELDS[field][1], Input).focus()
                self._apply_free(field)
            elif event.value is not SELECT_NULL:
                self._free[field] = False
                self._show_free(field, False)
                self.custom[field] = event.value
                self._clear_overrides((field,))
            self._recompute()

        def on_input_changed(self, event) -> None:
            if self._syncing:
                return
            wid = event.input.id or ""
            row = re.match(r"c(\d+)_(vcpus|ram|disk)$", wid)
            if row and not self._is_current(event.input):
                return
            if row:
                index, field = int(row.group(1)), row.group(2)
                valeur = self._read_row_free(index, field)
                # Même règle que pour les listes : poser « value= » au montage
                # émet un Changed. L'écrire comme surcharge marquait ✎ une
                # rangée que personne n'avait touchée — visible dès qu'une
                # entrée du catalogue porte une taille absente des
                # préréglages, comme les 32 G de Proxmox VE.
                if self._row_echo(index, field, valeur):
                    return
                self._set_override(index, field, valeur)
                self._recompute()
                return
            field = INPUT_TO_FIELD.get(event.input.id)
            if field:
                self._apply_free(field)
                self._recompute()

        def on_button_pressed(self, event) -> None:
            match = re.match(r"([pm])(\d+)$", event.button.id or "")
            if match:
                self._add_copy(
                    int(match.group(2)), 1 if match.group(1) == "p" else -1
                )
                return
            match = re.match(r"r(\d+)$", event.button.id or "")
            if match:
                self._rename(int(match.group(1)))
                return
            match = re.match(r"l(\d+)$", event.button.id or "")
            if match:
                index = int(match.group(1))
                key = self._row_key(index)
                if key is not None:
                    self._set_lock(index, key not in self.locked)

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id == "f_install":
                self._sync_install_deps()
                self._recompute()  # le disque annoncé inclut le +5 G ERPLibre
            elif event.checkbox.id == "f_par_all":
                self.query_one("#f_par", Select).disabled = event.value
            elif str(event.checkbox.id or "").startswith("f_tool_"):
                # Un IDE de plus, c'est un disque plus grand : le plan doit le
                # montrer AVANT de déployer, pas après une heure d'installation.
                self._recompute()

        # -- actions ---------------------------------------------------- #
        def action_clear_vm(self) -> None:
            """Rend au profil commun la VM dont un widget a le focus. Sans
            cette sortie, un réglage posé par erreur ne se défaisait qu'en
            rouvrant le formulaire."""
            index = self._focused_row()
            if index is None:
                return
            key = self._row_key(index)
            if key is None or key not in self.overrides:
                return
            self.overrides.pop(key)
            # Les widgets de la rangée portent encore l'ancienne valeur : on
            # les remonte pour qu'ils disent la vérité.
            self._recompute()
            self._mount_rows()

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
                # Le suivi est demandé au NIVEAU DU DÉPLOIEMENT, pas de
                # l'installation : décocher ERPLibre emportait la case avec
                # elle, et le tableau de bord ne s'ouvrait plus du tout.
                "monitor": self.query_one("#f_monitor", Checkbox).value,
                "gpu3d": self.query_one("#f_gpu3d", Checkbox).value,
                "res_label": (
                    t("custom")
                    if self.profile == "custom"
                    else f"x{self.profile}"
                ),
                "ssh_key": os.path.expanduser(key) if key else "",
                **self.extras_values(),
                "install": install,
                "add_ssh_config": self.query_one("#f_sshcfg", Checkbox).value,
                # Une exécution par installation : le nombre de VM retenues
                # fait foi. Le déploiement le borne ensuite à ce même nombre,
                # donc une valeur haute ne crée jamais de travailleur inutile.
                "parallelism": (
                    max(1, len(self.vms))
                    if self.query_one("#f_par_all", Checkbox).value
                    else self.query_one("#f_par", Select).value
                ),
            }

        def action_preview(self) -> None:
            spec = build_spec(self.vms, domains, self._form_values())
            build = ctx.get("build_command")
            if not build:
                return
            lines = [build(vm, spec, True) for vm in spec["vms"]]
            self.push_screen(
                preview_screen()(lines or [t("Nothing selected.")])
            )

        def action_dump_state(self) -> None:
            """Écrit l'état COMPLET dans un fichier, widgets ET modèle.

            Une capture d'écran ne dit pas si l'écart vient de ce qu'on voit
            ou de ce qui sera déployé. Ce vidage met les deux côte à côte, VM
            par VM : si la liste affiche 16384 et que le modèle dit 1024, le
            défaut est dans la prise en compte ; s'ils s'accordent et que la
            VM déployée diffère, il est en aval."""
            path = os.path.expanduser("~/.erplibre/deploy-form-dump.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            out = [
                "=== formulaire de deploiement ===",
                f"profil={self.profile}  custom={self.custom}",
                f"verrous={sorted(self.locked)}",
                f"surcharges={self.overrides}",
                f"generation={self._gen}  jeu_monte={self._shown_ids}",
                f"branche_globale={self._branch()}",
                f"profil_odoo_global={self._profile_cmd()}",
                "",
                "  # widget -> modele, VM par VM",
            ]
            for i, r in enumerate(self.rows):
                vm = r["vm"]
                shown = {}
                for f in ("vcpus", "ram", "disk", "type", "branch", "prof"):
                    try:
                        shown[f] = self.query_one(f"#v{i}_{f}", Select).value
                    except Exception:
                        shown[f] = "-"
                    try:
                        free = self.query_one(f"#c{i}_{f}", Input)
                        if free.display:
                            shown[f] = f"libre:{free.value!r}"
                    except Exception:
                        pass
                out.append(f"  [{i}] {vm['name']}  etat={r['state']}")
                out.append(f"      widgets = {shown}")
                out.append(
                    f"      modele  = vcpus={vm['vcpus']} ram={vm['ram']} "
                    f"disk={vm['disk']} desktop={vm.get('desktop')!r} "
                    f"branch={vm.get('branch')!r} cmd={vm.get('install_cmd')!r}"
                )
            spec = build_spec(self.vms, domains, self._form_values())
            out.append("")
            out.append("  # spec qui partirait au deploiement")
            for vm in spec["vms"]:
                out.append(
                    f"    {vm['name']}: ram={vm['ram']} vcpus={vm['vcpus']} "
                    f"disk={vm['disk']}"
                )
            out.append(f"    ignorees (existent deja) = {spec['existing']}")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out) + "\n")
            self.notify(f"{t('State written to')} {path}")

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
