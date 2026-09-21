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

from script.todo import vm_profiles
from script.todo.deploy_form_extras import ExtrasMixin
from script.todo.deploy_form_lib import (
    CSS_BASE,
    FREE,
    RES_FIELDS,
    SELECT_TO_FIELD,
    branch_default,
    branch_order,
    build_vms,
    disk_note,
    entry_key,
    gib,
    motifs_hors_ligne,
    plan_rows,
    plan_totals,
    res_row_widgets,
    t,
)
from script.todo.deploy_form_plan import PlanMixin, preview_screen

# Aucun disque orphelin à craindre : les disques d'un Proxmox distant vivent
# dans un stockage que seul l'hôte connaît, jamais dans /var/lib/libvirt.
PAS_D_ORPHELIN = None

# Dernier choix du sélecteur de pont : il ne désigne pas un pont, il en crée
# un. Sans lui, l'écran oppose « aucun pont sur l'hôte » et refuse de
# déployer, sans offrir le moindre moyen d'en avoir un.
CREER_PONT = "__creer_pont__"


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
        # Les résolveurs de l'hôte suivent la spec : une VM en adresse fixe
        # n'a pas de DNS sans eux.
        "nameservers": form.get("nameservers") or (),
        "res_label": form["res_label"],
        "vms": [vm for vm in vms if vm["name"] not in connus],
        "existing": [vm["name"] for vm in vms if vm["name"] in connus],
        "ssh_key": form["ssh_key"],
        "user": form.get("user") or "erplibre",
        "start": form["start"],
        # LA POSTURE ET LES DONNÉES RÉELLES traversent jusqu'ici, sans quoi
        # le choix de l'écran s'arrêtait à l'écran : cette fonction ÉNUMÈRE
        # les clés de la spec, et une clé non nommée n'existe pas pour le
        # déploiement, quel que soit le widget qui l'a produite.
        "posture": form.get("posture") or "",
        "real_data": bool(form.get("real_data")),
        "add_ssh_config": form["add_ssh_config"],
        "install": form["install"],
        "python_provider": form.get("python_provider") or "",
        # Ce qui décrit le SYSTÈME INVITÉ, et non l'hyperviseur : il valait
        # déjà sur libvirt, il vaut ici. Sans ces cinq clés, une VM créée sur
        # Proxmox naissait sans bureau, sans outils et en UTC.
        "timezone": form.get("timezone") or "",
        "desktop": form.get("desktop") or "",
        "vm_tools": tuple(form.get("vm_tools") or ()),
        "app_store": form.get("app_store") or "deb",
        "prod": bool((form.get("install") or {}).get("prod")),
        "monitor": form["monitor"],
        "parallelism": form["parallelism"],
        # La coupure d'amont demandée pour TOUT le déploiement, installation
        # comprise. Absente de la spec, le déploiement part en ligne.
        "offline": bool(form.get("offline")),
        # L'écran accéléré, posé à la création de chaque VM.
        "gpu3d": bool(form.get("gpu3d")),
    }


def run_proxmox_form(ctx, run_app: bool = True):
    """Formulaire Proxmox. Renvoie une spec, None si annulé, {} pour retomber
    sur les invites textuelles. `run_app=False` rend l'instance sans la lancer
    (tests headless)."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
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
    # Ordre et défaut partagés avec le formulaire QEMU/KVM : la liste vient
    # de « git ls-remote », alphabétique, et commençait donc par une branche
    # de dependabot — proposée par défaut. Rapporté.
    branches = branch_order(
        ctx.get("branches") or ["master"], ctx.get("branch_current")
    )
    profiles = ctx.get("install_profiles") or []
    # {clé de saveur: suffixe de nom} — décrit par todo.py, source unique.
    desktop_suffixes = dict(ctx.get("desktop_suffixes") or {})
    stockages = ctx.get("storages") or []
    ponts = ctx.get("bridges") or []
    # La case « Sans connexion internet » ne s'offre que là où la coupure a
    # un effet : l'hôte Proxmox est alors une VM de notre pont, et le menu
    # l'a établi avant d'ouvrir cet écran.
    cache_offert = bool(ctx.get("cache_offert"))
    # La 3D ne s'offre que là où l'hôte distant peut la rendre : nœud de
    # rendu et VIRGL. Le menu l'a sondé avant d'ouvrir cet écran.
    gpu_offert = bool(ctx.get("gpu_offert"))
    # Ce qui manque à l'hôte, nommé par la sonde : sans lui, la case
    # disparaîtrait sans que rien ne dise pourquoi.
    gpu_manque = str(ctx.get("gpu_manque") or "")
    # Ce qui s'INSTALLE là-dedans : le nœud de rendu vient du matériel ou
    # d'un GPU transmis, et « apt install noeud » enverrait dans le mur.
    paquets_gpu = " ".join(p for p in gpu_manque.split() if p != "noeud")
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
        # L'étoile marque la version par défaut d'une distribution : c'est
        # elle que « F7 » retient, et sans repère le raccourci choisissait
        # sans qu'on sache quoi.
        star = " *" if e.get("default") else ""
        return (
            f"{e['distro']} {e['version']}{star}  [{e['arch']}]  {e['name']}"
        )

    class ProxmoxForm(ExtrasMixin, PlanMixin, App):
        TITLE = t("Deploy one or more ERPLibre VMs on Proxmox VE!")
        BINDINGS = [
            ("f5", "deploy", t("Deploy")),
            ("f4", "clear_vm", t("Reset VM")),
            ("f3", "preview", t("Preview")),
            ("f6", "select_all", t("All")),
            ("f7", "select_main", t("Main versions")),
            ("f8", "select_none", t("None")),
            ("f1", "help", t("Help")),
            # « ? » aussi, parce que c'est la touche qu'on essaie d'abord.
            # Cachée du pied de page : la même action deux fois s'y lirait
            # comme deux aides. Un champ de saisie qui a le focus l'avale, et
            # c'est pourquoi F1 existe à côté.
            Binding("?", "help", t("Help"), show=False),
            ("escape", "cancel", t("Cancel")),
        ]
        # Le socle porte la mise en page et les modales ; ne reste ici que ce
        # qui nomme les widgets propres à Proxmox.
        CSS = (
            CSS_BASE
            + """
        SelectionList { height: 10; border: solid $panel; }
        RadioSet { height: auto; layout: horizontal; }
        /* Ces deux règles portent « .vmrow Select » EN PLUS de leur
        classe : « .vmrow Select » (une classe + un type) l'emporte sur
        « .vmbranch » (une classe) par spécificité CSS. Écrites simplement,
        elles étaient silencieusement écrasées. La branche porte des noms
        longs (« 1.6.0 », « develop », « feature/xyz ») : trop étroite, la
        liste les tronque et on ne sait plus ce qu'on a choisi. */
        .vmrow Select.vmbranch { width: 34; }
        .vmrow Select.vmprof { width: 40; }
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
            # La liste des ponts GRANDIT : l'écran sait en créer un.
            self._ponts = list(ponts)
            self.extras_init(ctx, branches, profiles)

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
                        self._choix_ponts(),
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
                    # L'écran de la VM se choisit à la CRÉATION : « qm » pose
                    # « --vga virtio-gl » au lieu de la console série, et le
                    # changer ensuite demande d'éteindre la machine. La
                    # console série reste posée dans les deux cas.
                    if gpu_offert:
                        yield Checkbox(
                            t(
                                "3D acceleration (host GPU), even without a"
                                " screen"
                            ),
                            value=False,
                            id="f_gpu3d",
                        )
                    elif gpu_manque:
                        # Une case qui disparaît sans un mot se lit comme une
                        # régression : on dit ce qui manque, et le paquet à
                        # poser sur l'HÔTE, pas dans la VM.
                        yield Static(
                            f"  {t('No 3D: the host lacks')} {gpu_manque}",
                            id="t_gpu_manque",
                        )
                        if paquets_gpu:
                            yield Static(
                                f"    sudo apt install {paquets_gpu}",
                                id="t_gpu_geste",
                            )
                            # Le bouton n'existe que si le menu a fourni de
                            # quoi poser : un bouton sans effet vaut moins
                            # qu'une commande à recopier.
                            if ctx.get("installer_gpu"):
                                yield Button(
                                    t("Install on the host"),
                                    id="f_gpu_poser",
                                )
                    # SOUS LE PONT : la posture décrit ce que le réseau
                    # de la machine atteint, et le pont est ce par quoi
                    # elle l'atteint. On les lit ensemble.
                    yield Static(t("Network posture"), classes="grouptitle")
                    # LES LIBELLÉS, et la valeur reste le nom de posture :
                    # c'est lui que la spec porte, et lui que la règle d'or
                    # relit au déploiement. Le repli sur les noms bruts
                    # garde l'écran utilisable si un contexte plus ancien
                    # ne porte pas encore les choix.
                    choix = ctx.get("posture_choices") or vm_profiles.choices()
                    yield Select(
                        choix,
                        # LE PREMIER CHOIX OFFERT, et non un blanc : un
                        # Select sans blanc autorisé REFUSE une liste vide
                        # et une valeur absente. Le repli d'avant était un
                        # contexte plus ancien — donc une liste vide, donc
                        # l'écran qui ne monte pas du tout.
                        value=ctx.get("posture") or choix[0][1],
                        allow_blank=False,
                        id="f_posture",
                    )
                    # CE QU'ELLE APPLIQUE, sous elle. Un nom sans cette
                    # ligne vend l'assurance que le registre s'interdit de
                    # donner : une politique déclarée sans mécanisme se
                    # comporte comme l'absence de politique.
                    yield Static("", id="t_posture_effet", classes="hint")
                    # Séparée de la posture parce qu'aucune des deux ne se
                    # déduit de l'autre : le déploiement refuse le couple
                    # incohérent, il ne le devine pas.
                    yield Checkbox(
                        t("This machine carries real data"),
                        value=bool(ctx.get("real_data", False)),
                        id="f_real_data",
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
                    yield from self.compose_vm_type()
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
                        value=branch_default(
                            branches, ctx.get("branch_current")
                        ),
                        allow_blank=False,
                        id="f_branch",
                    )
                    yield from self.compose_install_extras()
                    yield from self.compose_timezone()
                    yield from self.compose_python()
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
                    # Cochée, la case donne une exécution PAR installation :
                    # le plafond du nombre de CPU ne s'applique plus.
                    # Décochée, le nombre reprend la main, et son défaut suit
                    # l'HÔTE PROXMOX — l'écran restait figé à quatre choix et
                    # en proposait un, quel que soit le nombre de cœurs.
                    yield Checkbox(
                        t("One run per install"),
                        value=True,
                        id="f_par_all",
                    )
                    yield Select(
                        [(str(n), n) for n in range(1, ctx["host_cpu"] + 1)],
                        value=ctx["host_cpu"],
                        allow_blank=False,
                        disabled=True,
                        id="f_par",
                    )
                    # La coupure est posée ICI, sur le pont local, et non sur
                    # l'hôte Proxmox : ses invités sortent derrière son
                    # adresse, donc couper ce pont les coupe aussi. Offerte
                    # seulement là où cela vaut — le contexte le dit.
                    if cache_offert:
                        yield Static(
                            t("Network"),
                            id="t_network",
                            classes="grouptitle",
                        )
                        yield Checkbox(
                            t("No internet connection"),
                            value=False,
                            id="f_offline",
                        )
                        yield Static(
                            f"  {t('Cuts internet for the cache and the VMs: proves')}"
                        )
                        yield Static(
                            f"  {t('the install builds from what the cache holds.')}"
                        )
                        # Découvert par la case : ce qui suit ne concerne que
                        # celui qui vient de la cocher.
                        yield Static(
                            f"  ⚠ {t('The cut hits every user of the cache:')}",
                            id="t_offline_w1",
                        )
                        yield Static(
                            f"    {t('a deployment run from another terminal')}",
                            id="t_offline_w2",
                        )
                        yield Static(
                            f"    {t('goes offline too, without asking for it.')}",
                            id="t_offline_w3",
                        )
                        yield Static(
                            f"  {t('Nothing is cut before F5: the upstream falls')}",
                            id="t_offline_w4",
                        )
                        yield Static(
                            f"    {t('at launch and comes back when the last install')}",
                            id="t_offline_w5",
                        )
                        yield Static(
                            f"    {t('ends (12 h at most), even with the monitor closed.')}",
                            id="t_offline_w6",
                        )
                        yield Static(
                            f"  {t('The monitor stays ticked: it is what arms that return.')}",
                            id="t_offline_w7",
                        )
                with Vertical(id="right"):
                    yield VerticalScroll(id="plan")
                    yield Static("", id="totals")
                    with Horizontal(id="actions"):
                        yield Button(t("Deploy"), variant="primary", id="go")
                        yield Button(t("Text prompts"), id="prompts")
                        yield Button(t("Cancel"), id="no")
            yield Footer()

        def _choix_ponts(self):
            """Les ponts de l'hôte, plus « en créer un ».

            L'entrée de création reste offerte même quand des ponts existent :
            sur un hôte qui n'en a qu'un, sur le LAN, on peut vouloir un
            réseau interne pour un parc d'essai."""
            choix = [(b, b) for b in self._ponts]
            if ctx.get("make_bridge"):
                nom, cidr = ctx.get("internal_bridge") or ("vmbr0", "")
                choix.append(
                    (
                        f"➕ {t('create an internal')} {nom} ({cidr}) + NAT",
                        CREER_PONT,
                    )
                )
            return choix

        def _creer_pont(self) -> None:
            """Crée le pont sur l'hôte, dans un FIL : l'appel dure des
            secondes, et l'écran doit rester vivant pendant ce temps."""
            self.notify(t("Creating the bridge on the host…"))

            def travail():
                nom, raison = ctx["make_bridge"]()
                self.call_from_thread(self._pont_cree, nom, raison)

            self.run_worker(travail, thread=True)

        def _pont_cree(self, nom, raison) -> None:
            """Retour du fil. Le sélecteur est remis d'aplomb dans les DEUX
            cas : laissé sur « créer », il ne désignerait aucun pont."""
            selecteur = self.query_one("#f_bridge", Select)
            if not nom:
                self.notify(
                    f"{t('The bridge did not come up.')} {raison}",
                    severity="error",
                    timeout=12,
                )
                selecteur.value = (
                    self._ponts[0] if self._ponts else SELECT_NULL
                )
                return
            if nom not in self._ponts:
                self._ponts.append(nom)
            self._syncing = True
            selecteur.set_options(self._choix_ponts())
            selecteur.value = nom
            self._syncing = False
            self.notify(f"✓ {nom}")
            self._refresh_after()

        # L'avertissement que la case « Sans connexion internet » découvre.
        _OFFLINE_WIDGETS = tuple(f"#t_offline_w{n}" for n in range(1, 8))

        def _sync_offline(self) -> None:
            """Montre l'avertissement quand la coupure est demandée, et y
            force le suivi.

            Il dit ce qu'on ne devine pas : la coupure vaut pour TOUS les
            usagers du cache, elle ne tombe qu'au lancement, et elle ne se
            lève qu'à la fin de la dernière installation.

            Cette dernière promesse n'est tenue que par le déploiement suivi,
            le seul qui confie la levée à une unité systemd. Le suivi est donc
            coché et grisé tant que la case l'est ; la décocher le rend
            modifiable, avec la valeur qu'il avait avant.
            """
            case = self.query("#f_offline")
            vu = bool(case) and bool(case.first(Checkbox).value)
            for sel in self._OFFLINE_WIDGETS:
                for widget in self.query(sel):
                    widget.display = vu
            suivi = self.query_one("#f_monitor", Checkbox)
            if vu and not suivi.disabled:
                self._suivi_avant = suivi.value
                suivi.value = True
                suivi.disabled = True
            elif not vu and suivi.disabled:
                suivi.disabled = False
                suivi.value = getattr(self, "_suivi_avant", True)

        def on_mount(self) -> None:
            self._reload_catalog()
            self._sync_install_deps()
            self._sync_offline()
            self._sync_posture()

        def _sync_posture(self) -> None:
            """Écrit sous le sélecteur ce que la posture choisie APPLIQUE.

            La ligne est composée par `vm_profiles` : ici il ne reste
            qu'une affectation, parce que ce fichier est du Textual et
            qu'aucune épreuve unitaire ne le pilote.
            """
            try:
                choisie = self.query_one("#f_posture", Select).value
                ligne = self.query_one("#t_posture_effet", Static)
            except Exception:  # pragma: no cover - widget absent
                return
            # `ctx` est la FERMETURE, comme partout dans ce fichier.
            ligne.update((ctx.get("posture_screen") or {}).get(choisie, ""))

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
                self._default_desktop(),
                desktop_suffixes,
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
            installe = self.query_one("#f_install", Checkbox).value
            commun = (self._install() or {}).get("cmd") or ""
            outils = self._vm_tools()
            for row in self.rows:
                cmd_vm = row["vm"].get("install_cmd") or commun
                if installe and cmd_vm.strip() not in no_erplibre:
                    row["disk_gb"] += ctx.get("extra_disk_gb", 0)
                # Le bureau et les outils ne pèsent que sur les VM qui les
                # reçoivent RÉELLEMENT : Android Studio n'existe qu'en
                # x86_64, les extensions GNOME n'ont de sens que sous GNOME.
                row["disk_gb"] += self._extras_disk_gb(row["vm"], outils)
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
            self.render_extras()

        def _auto_name(self, index):
            """Le nom du catalogue, suffixé du bureau : ce que la VM
            reprendrait si on effaçait le sien."""
            from script.todo.deploy_form_lib import vm_name

            return vm_name(
                self._plan_entries()[index]["name"],
                self.rows[index]["vm"].get("desktop"),
                desktop_suffixes,
            )

        def _vmid_start(self):
            brut = self.query_one("#f_vmid", Input).value.strip()
            return (
                int(brut) if brut.isdigit() else (ctx.get("next_vmid") or 100)
            )

        def _bridge(self):
            valeur = self.query_one("#f_bridge", Select).value
            if valeur is SELECT_NULL or valeur == CREER_PONT:
                # La sentinelle n'est pas un pont : la rendre ferait déployer
                # une VM sur « __creer_pont__ ».
                return ""
            return valeur

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
                    # Branche, profil, type — par VM. On déploie ici le plus
                    # souvent un parc MIXTE : un hyperviseur Proxmox imbriqué
                    # à côté de VM ERPLibre, et l'écran n'offrait qu'un choix
                    # commun pour les deux.
                    *self.install_row_widgets(i, SELECT_NULL),
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
            if event.radio_set.id in ("f_type", "f_store"):
                # Le bureau pèse sur le disque et change le nom des VM.
                self._refresh_after(remonter=True)
                return
            if event.radio_set.id == "f_profile":
                choix = ("1", "2", "3", "4", "custom")[event.index]
                self.profile = choix
                sur_mesure = choix == "custom"
                for champ in RES_FIELDS:
                    self.query_one(
                        RES_FIELDS[champ][0], Select
                    ).disabled = not sur_mesure
                    if not sur_mesure:
                        self._show_free(champ, False)
                # Un réglage commun reprend la main sur les VM non figées :
                # c'est le sens même du mot « commun ».
                self._clear_overrides(tuple(RES_FIELDS))
                self._refresh_after(remonter=True)

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id == "f_install":
                # Le disque d'ERPLibre entre — ou sort — du total.
                self._sync_install_deps()
                self._refresh_after()
            elif event.checkbox.id == "f_par_all":
                self.query_one("#f_par", Select).disabled = event.value
            elif event.checkbox.id == "f_offline":
                self._sync_offline()
            elif str(event.checkbox.id or "").startswith("f_tool_"):
                # Un IDE de plus, c'est un disque plus grand : le plan doit
                # le montrer AVANT de déployer, pas après une heure.
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
            if self.extras_on_select(event):
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
            if ident == "f_posture":
                self._sync_posture()
                return
            if ident == "f_bridge" and event.value == CREER_PONT:
                self._creer_pont()
                return
            if ident in ("f_storage", "f_bridge"):
                self._refresh_after()
                return
            if ident in ("f_branch", "f_profile_install"):
                # Un réglage commun reprend la main sur les VM non figées :
                # c'est le sens même du mot « commun ».
                self._clear_overrides(
                    ("branch",) if ident == "f_branch" else ("install_cmd",)
                )
                self._refresh_after(remonter=True)
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
                if not rang.isdigit():
                    return
                index = int(rang)
                if index >= len(self.rows):
                    return
                if self.extras_on_row_select(event, index, champ):
                    self._refresh_after()
                    return
                if champ not in RES_FIELDS:
                    return
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

        def _poser_gpu(self) -> None:
            """Pose ce qui manque sur l'hôte, terminal rendu, puis RELIT.

            « suspend() » rend le clavier à sudo, qui peut demander un mot de
            passe, et laisse apt s'afficher : la moitié de la confiance tient
            à voir le travail se faire.

            L'hôte est SONDÉ de nouveau au retour. Croire apt sur parole
            offrirait une case que Proxmox refuserait ensuite — et il ne la
            refuse qu'après avoir écrit le disque de la VM.
            """
            poser = ctx.get("installer_gpu")
            if not poser:
                return
            with self.suspend():
                poser(paquets_gpu)
            sonder = ctx.get("sonder_gpu")
            possible, reste = sonder() if sonder else (False, gpu_manque)
            if not possible:
                self.notify(
                    f"{t('Still missing on the host:')} {reste or gpu_manque}",
                    severity="warning",
                )
                return
            # Monter la case AVANT de retirer les lignes : le bloc n'est
            # jamais vide, et l'œil suit ce qui remplace quoi.
            self.query_one("#fields").mount(
                Checkbox(
                    t("3D acceleration (host GPU), even without a screen"),
                    value=True,
                    id="f_gpu3d",
                ),
                after=self.query_one("#t_gpu_manque"),
            )
            for sel in ("#t_gpu_manque", "#t_gpu_geste", "#f_gpu_poser"):
                for widget in self.query(sel):
                    widget.remove()
            self.notify(t("3D is now available: the box is here."))

        def on_button_pressed(self, event) -> None:
            ident = event.button.id or ""
            if ident == "f_gpu_poser":
                self._poser_gpu()
            elif ident == "go":
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
                # /opt et service confiné, comme en QEMU/KVM : le choix ne
                # regarde pas l'hyperviseur, il regarde le système invité.
                "prod": self.query_one("#f_prod", Checkbox).value,
                "label": label,
                "cmd": cmd,
            }

        def _form_values(self):
            cle = self.query_one("#f_key", Input).value.strip()
            # La case n'existe que là où le cache tourne : la chercher sans
            # la trouver vaut « en ligne ».
            offline = bool(
                self.query("#f_offline")
                and self.query_one("#f_offline", Checkbox).value
            )
            # Même règle que pour la coupure : la case n'existe que là où
            # elle a un effet, et son absence vaut « non ».
            gpu3d = bool(
                self.query("#f_gpu3d")
                and self.query_one("#f_gpu3d", Checkbox).value
            )
            return {
                "host": ctx["host"],
                "storage": self._storage(),
                "bridge": self._bridge(),
                "nameservers": ctx.get("nameservers") or (),
                "res_label": res_label(self.profile),
                "ssh_key": os.path.expanduser(cle) if cle else "",
                # La posture et les données réelles : deux CHAMPS, et
                # aucun ne se déduit de l'autre. Le déploiement relit le
                # couple avant que la machine existe.
                "posture": self.query_one("#f_posture", Select).value,
                "real_data": self.query_one("#f_real_data", Checkbox).value,
                "start": self.query_one("#f_start", Checkbox).value,
                "add_ssh_config": self.query_one("#f_sshcfg", Checkbox).value,
                "install": self._install(),
                **self.extras_values(),
                # Le suivi est demandé au NIVEAU DU DÉPLOIEMENT : une VM sans
                # ERPLibre se suit aussi (cloud-init, puis relevé système).
                "offline": offline,
                "gpu3d": gpu3d,
                # Hors ligne, le suivi est d'office : seule sa voie confie la
                # levée de la coupure au guet, qui la tient jusqu'à la fin de
                # la dernière installation.
                "monitor": offline
                or self.query_one("#f_monitor", Checkbox).value,
                # Une exécution par installation : le nombre de VM retenues
                # fait foi. Le déploiement le borne ensuite à ce même nombre,
                # donc une valeur haute ne crée aucun travailleur inutile.
                "parallelism": (
                    max(1, len(self.vms))
                    if self.query_one("#f_par_all", Checkbox).value
                    else self.query_one("#f_par", Select).value
                ),
            }

        def action_deploy(self) -> None:
            spec = build_spec(self.vms, noms_pris, self._form_values())
            if not spec["vms"]:
                self.notify(t("Nothing to deploy."), severity="warning")
                return
            # Hors ligne : ce que le cache ne détient pas, aucune VM ne
            # pourra le lire, et une VM Proxmox échoue aussi loin de son
            # lancement qu'une VM libvirt — à la pose du bureau, une heure
            # plus tard. F5 à nouveau vaut passage outre : le journal peut
            # avoir tourné, ou le magasin avoir été rempli autrement.
            if spec.get("offline") and not getattr(
                self, "_offline_ack", False
            ):
                motifs = motifs_hors_ligne(spec["vms"])
                if motifs:
                    self._offline_ack = True
                    self.notify(
                        " — ".join(motifs + [t("press F5 again to confirm")]),
                        severity="error",
                        timeout=20,
                    )
                    return
            if not spec["storage"]:
                self.notify(
                    t("No storage able to hold a VM disk."), severity="error"
                )
                return
            if not spec["bridge"]:
                self.notify(t("No bridge on the host."), severity="error")
                return
            # LE COUPLE (libellé choisi, installation choisie). Ici, et pas
            # au déploiement : l'écran SAIT sous quel libellé la posture a
            # été choisie — c'est lui qui l'a montré — alors qu'une spec ne
            # porte que la posture. Un avertissement et non un refus :
            # servir autre chose sur la même posture reste légitime, et
            # c'est la raison même pour laquelle le registre les sépare.
            if self._warn_serves_nothing(spec):
                return
            self.result = spec
            self.exit()

        def _warn_serves_nothing(self, spec) -> bool:
            """Vrai quand l'écran vient d'avertir et attend une confirmation.

            La commande examinée est celle que la VM subira VRAIMENT :
            l'installation commune, sauf quand la rangée en a figé une
            autre. Une seule machine qui ne sert rien suffit — la posture
            est commune à toutes, la promesse aussi.
            """
            libelle = vm_profiles.label_of(spec.get("posture", ""))
            commune = (spec.get("install") or {}).get("cmd", "")
            verdicts = {
                vm_profiles.check_install(
                    libelle, vm.get("install_cmd") or commune
                )
                for vm in spec["vms"]
            }
            manque = verdicts - {vm_profiles.INSTALL_OK}
            if not manque or getattr(self, "_serves_ack", False):
                return False
            self._serves_ack = True
            self.notify(
                vm_profiles.install_sentence(sorted(manque)[0])
                + " — "
                + t("press F5 again to confirm"),
                severity="warning",
                timeout=12,
            )
            return True

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

        def action_cancel(self) -> None:
            self.result = None
            self.exit()

    app = ProxmoxForm()
    if not run_app:
        return app
    app.run()
    return app.result
