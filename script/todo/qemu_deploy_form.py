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
    """Identité stable d'une VM du plan, indépendante de son rang d'affichage :
    surcharges et verrous y survivent quand la sélection change.

    Le quatrième membre est le numéro d'EXEMPLAIRE. Sans lui, deux copies de
    la même entrée de catalogue partageaient une identité : régler la première
    réglait la seconde, et les verrous se marchaient dessus."""
    return (
        entry["distro"],
        entry["version"],
        entry["arch"],
        entry.get("instance", 0),
    )


def copy_name(base: str, instance: int) -> str:
    """Nom du n-ième exemplaire. Le premier garde le nom du catalogue, pour
    que les déploiements d'avant gardent le leur."""
    return base if not instance else f"{base}-{instance + 1}"


def expand_copies(entries, copies):
    """[entrée] + {clé de base: exemplaires en plus} -> [entrée par VM].

    Chaque exemplaire est une COPIE du dictionnaire, avec son numéro et son
    nom : rien n'est partagé, donc régler l'un ne touche pas l'autre."""
    out = []
    for e in entries:
        base = (e["distro"], e["version"], e["arch"])
        for i in range(1 + max(0, (copies or {}).get(base, 0))):
            item = dict(e)
            item["instance"] = i
            item["name"] = copy_name(e["name"], i)
            out.append(item)
    return out


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


def positive_int(value, fallback):
    """Entier strictement positif, sinon `fallback`.

    Ces valeurs viennent de widgets : une liste déroulante sans choix rend un
    sentinelle, une saisie libre rend du texte, éventuellement vide. Aucun des
    deux ne doit atteindre les totaux, qui les additionnent."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def apply_profile(
    entries, profile, base_vcpus, host_cpu, custom=None, desktop=""
):
    """Applique le profil de ressources aux entrées choisies.

    Reproduit à l'identique `TODO._qemu_prompt_resources` : un multiplicateur
    monte la RAM minimale du catalogue et les vCPU en se bornant aux cœurs de
    l'hôte ; « custom » impose les mêmes valeurs à tout le parc, une valeur
    absente gardant celle du catalogue."""
    out = []
    for e in entries:
        if profile == "custom":
            cus = custom or {}
            ram = positive_int(cus.get("ram"), e["ram"])
            disk = parse_disk(cus.get("disk")) or e["disk"]
            vcpus = positive_int(cus.get("vcpus"), base_vcpus)
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
                # Type de VM (« » = serveur). Il vit sur la VM et non sur la
                # spec entière depuis qu'il se choisit machine par machine ;
                # `desktop` n'est plus que le défaut commun.
                "desktop": desktop,
                # Branche ERPLibre. Même raison : « » signifie « celle du
                # formulaire », et une surcharge la remplace pour cette VM.
                "branch": "",
                # Profil d'installation (« ERPLibre + Odoo 18 »). Même
                # convention : « » = celui du formulaire.
                "install_cmd": "",
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


def clean_hostname(value):
    """Nom d'hote valide (RFC 1123) tire de la saisie, ou None.

    Le nom d'une VM devient son NOM D'HOTE : une majuscule ou un point de
    trop et cloud-init l'ignore en silence, la machine reste « ubuntu ».
    Mieux vaut refuser ici que le decouvrir sur une VM deja deployee."""
    txt = str(value or "").strip().lower()
    if not txt or len(txt) > 63:
        return None
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", txt):
        return None
    return txt


def vm_name(base, desktop, suffixes):
    """Nom de VM, suffixé du bureau quand il y en a un.

    Le nom sert de nom d'hôte ET de clé de collision : une VM graphique et sa
    jumelle serveur doivent donc porter des noms différents, sinon la seconde
    est signalée « existe déjà » et silencieusement ignorée. Idempotent, le
    nom étant recalculé à chaque frappe."""
    suffix = (suffixes or {}).get(desktop or "")
    if not suffix or base.endswith(f"-{suffix}"):
        return base
    return f"{base}-{suffix}"


def build_vms(
    entries,
    profile,
    base_vcpus,
    host_cpu,
    custom,
    overrides,
    desktop="",
    suffixes=None,
):
    """Catalogue choisi + profil + surcharges -> liste de VM de la spec."""
    vms = apply_overrides(
        apply_profile(entries, profile, base_vcpus, host_cpu, custom, desktop),
        entries,
        overrides,
    )
    # APRÈS les surcharges : c'est là seulement que le type de chaque VM est
    # connu, puisqu'il se choisit machine par machine.
    for vm, e in zip(vms, entries):
        if (overrides or {}).get(entry_key(e), {}).get("name"):
            # Nom donne a la main : il gagne, sans suffixe ajoute. Y coller
            # « -gnome » reviendrait a corriger l'utilisateur.
            continue
        vm["name"] = vm_name(vm["name"], vm.get("desktop"), suffixes)
    return vms


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
        "desktop": form.get("desktop", ""),
        "python_provider": form.get("python_provider", ""),
        "app_store": form.get("app_store", "deb"),
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
    branches = ctx.get("branches") or ["master"]
    host_cpu = ctx.get("host_cpu") or 2
    free_ram = ctx.get("free_ram") or 0
    base_vcpus = ctx.get("base_vcpus") or 2
    extra_disk = ctx.get("extra_disk_gb") or 0
    desktop_disk = ctx.get("desktop_disk_gb") or 0
    # [(clé, libellé)] — la liste vient de todo.py, source unique.
    desktops = list(ctx.get("desktops") or [])
    # {clé de saveur: suffixe de nom}, fourni par todo.py qui décrit les
    # saveurs — on ne le redéfinit pas ici.
    desktop_suffixes = dict(ctx.get("desktop_suffixes") or {})
    # Architectures pour lesquelles mise publie un binaire.
    mise_arches = set(ctx.get("mise_arches") or ())
    # [(clé, libellé)] des magasins d'applications, et les distributions qui
    # livrent snapd — la question n'a de sens que pour celles-là, graphiques.
    app_stores = list(ctx.get("app_stores") or [])
    snap_distros = set(ctx.get("snap_distros") or ())
    defaults = ctx.get("defaults") or {}
    result = {"spec": None}

    AUTO = "__auto__"
    # Dernier choix de chaque liste de ressources : il ne porte pas de valeur,
    # il révèle la saisie libre placée juste dessous.
    FREE = "__free__"
    # « Serveur » est un CHOIX, pas une absence de choix : lui donner « » le
    # rendrait indistinguable de la sentinelle « rien de sélectionné ».
    SERVER = "__server__"
    RES_FIELDS = {
        "vcpus": ("#f_vcpus", "#c_vcpus"),
        "ram": ("#f_ram", "#c_ram"),
        "disk": ("#f_disk", "#c_disk"),
    }
    SELECT_TO_FIELD = {sel[1:]: f for f, (sel, _i) in RES_FIELDS.items()}
    INPUT_TO_FIELD = {inp[1:]: f for f, (_s, inp) in RES_FIELDS.items()}

    def entry_label(e):
        star = " *" if e.get("default") else ""
        return (
            f"{e['distro']} {e['version']}{star} [{e['arch']}]  "
            f"RAM≥{e['ram']}Mo  {e['disk']}"
        )

    class RenameScreen(ModalScreen):
        """Nom d'une VM. Vide = revenir au nom automatique."""

        BINDINGS = [("escape", "cancel", t("Cancel"))]

        def __init__(self, name, auto):
            super().__init__()
            self._name = name
            self._auto = auto

        def compose(self) -> ComposeResult:
            with Vertical(id="renbox"):
                yield Static(t("Rename the VM"), id="rentitle")
                yield Input(value=self._name, id="renval")
                yield Static(
                    f"  {t('Empty = back to the automatic name:')} "
                    f"{self._auto}",
                    id="renhint",
                )
                with Horizontal(id="renbtns"):
                    yield Button(t("Cancel"), id="ren_no")
                    yield Button(t("Rename"), variant="primary", id="ren_ok")

        def on_button_pressed(self, event) -> None:
            if event.button.id != "ren_ok":
                self.dismiss(None)
                return
            self.dismiss(self.query_one("#renval", Input).value)

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
        #plan {
            height: 1fr; border: solid $accent;
            overflow-x: auto; scrollbar-size-horizontal: 1;
        }
        #totals { height: auto; color: $text-muted; padding: 0 1; }
        .grouptitle { color: $accent; text-style: bold; padding: 1 0 0 0; }
        SelectionList { height: 10; border: solid $panel; }
        RadioSet { height: auto; layout: horizontal; }
        .freeval { display: none; width: 9; }
        .vmcard { height: auto; border-bottom: solid $panel; padding: 0 1; }
        /* Une VM figée se voit à la LIGNE, pas à une case perdue au bout :
        c'est ce qui permet de balayer le plan et de savoir d'un coup ce qui
        échappe au profil. */
        .vmcard.locked { background: $success 20%; }
        .vmlock { width: 5; min-width: 5; }
        /* La branche porte des noms longs (« 1.6.0 », « develop »,
        « feature/xyz ») : trop étroite, la liste les tronque et on ne sait
        plus ce qu'on a choisi. */


        .vmcopy { width: 5; min-width: 5; }
        .vmhead { height: 1; }
        /* « width: auto » et le défilement du plan : sans eux, une rangée
        plus large que le panneau est COUPÉE au lieu d'être atteignable. */
        .vmrow { height: 3; width: auto; align-vertical: middle; }
        .vmrow Select { width: 15; }
        .vmrow Input { width: 11; }
        /* Ces deux règles portent « .vmrow Select » EN PLUS de leur classe :
        « .vmrow Select » (une classe + un type) l'emporte sur « .vmbranch »
        (une classe) par spécificité CSS. Écrites simplement, elles étaient
        silencieusement écrasées à 15 — et le test, qui ne vérifiait que la
        présence de la classe, passait sans rien prouver. */
        .vmrow Select.vmbranch { width: 34; }
        .vmrow Select.vmprof { width: 40; }
        #reslabel { color: $text-muted; }
        RenameScreen { align: center middle; }
        #renbox {
            width: 60; height: auto; padding: 1 2;
            border: thick $accent; background: $surface;
        }
        #rentitle { color: $accent; text-style: bold; }
        #renhint { color: $text-muted; }
        #renbtns { height: auto; padding-top: 1; }
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
            ("f4", "clear_vm", t("Reset VM")),
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
            self._free = {}
            self.overrides = {}
            # Vrai pendant qu'on repositionne les widgets nous-mêmes : sans
            # ce verrou, poser une valeur déclencherait on_select_changed, qui
            # réécrirait une surcharge — une boucle qui se nourrit seule.
            self._syncing = False
            # Jeu de VM actuellement monté dans le panneau droit.
            self._shown_ids = ()
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
                        prompt=t("RAM (MB)"),
                        id="f_ram",
                        disabled=True,
                    )
                    yield Input(
                        placeholder=t("RAM (MB)"),
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
                    # Serveur par défaut : c'est ce que sert une image cloud,
                    # et GNOME ajoute une à deux heures sur une architecture
                    # émulée. Le plan annonce le surcoût disque.
                    yield Static(t("VM type (default):"), classes="grouptitle")
                    with RadioSet(id="f_type"):
                        yield RadioButton(
                            t("Server (no graphical interface)"),
                            value=not defaults.get("desktop", ""),
                        )
                        for key, label in desktops:
                            yield RadioButton(
                                f"{t('Graphical (server + desktop):')} {label}",
                                value=defaults.get("desktop", "") == key,
                            )
                    if app_stores:
                        yield Static(
                            t("Application store:"), classes="grouptitle"
                        )
                        with RadioSet(id="f_store"):
                            for i, (_k, label) in enumerate(app_stores):
                                yield RadioButton(label, value=i == 0)
                        yield Static("", id="storewarn")
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
                        value=0 if profiles else SELECT_NULL,
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
                    # mise pose un CPython précompilé, pyenv le compile.
                    # Grisé quand AUCUNE des VM retenues n'est sur une
                    # architecture que mise sert.
                    yield Static(
                        t("Python interpreter:"), classes="grouptitle"
                    )
                    with RadioSet(id="f_python"):
                        yield RadioButton(
                            t("mise (precompiled, faster)"), value=True
                        )
                        yield RadioButton(t("pyenv (compiles from source)"))
                    yield Static("", id="miswarn")
                    yield Static(t("Parallelism"), classes="grouptitle")
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

        # -- catalogue et recalcul ------------------------------------- #
        def _plan_entries(self):
            """Entrées du plan : la sélection, dépliée en exemplaires."""
            return expand_copies(self._selected_entries(), self.copies)

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
            # ERPLibre et GNOME pèsent chacun sur le disque, et se cumulent.
            grow = 0
            if self.query_one("#f_install", Checkbox).value:
                grow += extra_disk
            self.rows = plan_rows(self.vms, domains, grow)
            # Le bureau pèse sur le disque de la VM QUI LE PORTE, et d'elle
            # seule : un supplément commun mentait dès que les types
            # différaient d'une machine à l'autre.
            for row in self.rows:
                if row["vm"].get("desktop"):
                    row["disk_gb"] += desktop_disk
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
            self._render_mise()
            self._render_store()

        def _render_mise(self):
            """Grise le choix quand aucune VM retenue n'est servie par mise,
            et nomme les architectures qui retomberont sur pyenv."""
            usable = self._mise_usable()
            self.query_one("#f_python", RadioSet).disabled = not usable
            skipped = sorted(
                {
                    vm["arch"]
                    for vm in self.vms
                    if vm["arch"] not in mise_arches
                }
            )
            msg = ""
            if skipped:
                msg = (
                    f"  ⚠ {t('mise has no binary for:')} "
                    f"{', '.join(skipped)} — {t('those VMs use pyenv')}"
                )
            self.query_one("#miswarn", Static).update(msg)

        def _python_provider(self):
            """« mise » ou « pyenv ». Sans architecture servie par mise, le
            choix n'a pas d'objet : on renvoie pyenv."""
            if not self._mise_usable():
                return "pyenv"
            index = self.query_one("#f_python", RadioSet).pressed_index
            return "pyenv" if index == 1 else "mise"

        def _app_store(self):
            """Magasin retenu. Sans VM concernée, la réponse est « deb » :
            elle ne change rien, et laisser passer « snap » réactiverait snapd
            pour rien."""
            if not app_stores or not self._app_store_needed():
                return "deb"
            index = self.query_one("#f_store", RadioSet).pressed_index
            if index is None or not (0 <= index < len(app_stores)):
                return app_stores[0][0]
            return app_stores[index][0]

        def _app_store_needed(self):
            """Au moins une VM graphique sur une distribution qui livre snapd."""
            return any(
                vm.get("desktop") and vm["distro"] in snap_distros
                for vm in self.vms
            )

        def _render_store(self):
            """Grise le choix quand aucune VM ne le concerne, et dit pourquoi."""
            if not app_stores:
                return
            needed = self._app_store_needed()
            self.query_one("#f_store", RadioSet).disabled = not needed
            self.query_one("#storewarn", Static).update(
                ""
                if needed
                else f"  {t('No graphical VM on a snap-based distro.')}"
            )

        def _mise_usable(self):
            return any(vm["arch"] in mise_arches for vm in self.vms)

        def _profile_cmd(self):
            """Commande du profil choisi en haut : le défaut de chaque VM."""
            if not profiles:
                return ""
            index = self.query_one("#f_profile_install", Select).value
            return profiles[index if isinstance(index, int) else 0][1]

        def _row_profile_index(self, i):
            """Rang du profil que la rangée doit AFFICHER."""
            cmd = ""
            if i < len(self.rows):
                cmd = self.rows[i]["vm"].get("install_cmd") or ""
            cmd = cmd or self._profile_cmd()
            for k, (_lbl, c) in enumerate(profiles):
                if c == cmd:
                    return k
            return 0

        def _branch(self):
            """Branche du formulaire : le défaut de chaque VM."""
            value = self.query_one("#f_branch", Select).value
            return value if isinstance(value, str) else branches[0]

        def _default_desktop(self):
            """« » pour un serveur, sinon la clé de la saveur choisie."""
            """Type de VM par défaut. Chaque rangée peut s'en écarter."""
            index = self.query_one("#f_type", RadioSet).pressed_index
            if index is None or index < 1 or index > len(desktops):
                return ""
            return desktops[index - 1][0]

        # -- panneau droit : une rangée de widgets par VM ---------------- #
        def _row_ids(self):
            """Identité du JEU de VM affiché. Reconstruire les widgets à chaque
            frappe ferait perdre le focus en pleine saisie : on ne le fait que
            si la liste elle-même a changé."""
            return tuple(entry_key(e) for e in self._plan_entries())

        def _type_options(self):
            return [(t("Server"), SERVER)] + [
                (label, key) for key, label in desktops
            ]

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
                    Select(
                        [(str(c), c) for c in ctx["cpu_presets"]]
                        + [(t("free value…"), FREE)],
                        value=(
                            vm["vcpus"]
                            if vm["vcpus"] in ctx["cpu_presets"]
                            else SELECT_NULL
                        ),
                        prompt="vCPU",
                        id=f"v{i}_vcpus",
                    ),
                    Input(
                        value=(
                            ""
                            if vm["vcpus"] in ctx["cpu_presets"]
                            else str(vm["vcpus"])
                        ),
                        placeholder="vCPU",
                        id=f"c{i}_vcpus",
                        classes="freeval",
                    ),
                    Select(
                        [(f"{m // 1024}G", m) for m in ctx["ram_presets"]]
                        + [(t("free value…"), FREE)],
                        value=(
                            vm["ram"]
                            if vm["ram"] in ctx["ram_presets"]
                            else SELECT_NULL
                        ),
                        prompt=t("RAM (MB)"),
                        id=f"v{i}_ram",
                    ),
                    Input(
                        value=(
                            ""
                            if vm["ram"] in ctx["ram_presets"]
                            else str(vm["ram"])
                        ),
                        placeholder=t("RAM (MB)"),
                        id=f"c{i}_ram",
                        classes="freeval",
                    ),
                    Select(
                        [(d, d) for d in ctx["disk_presets"]]
                        + [(t("free value…"), FREE)],
                        value=(
                            vm["disk"]
                            if vm["disk"] in ctx["disk_presets"]
                            else SELECT_NULL
                        ),
                        prompt=t("Disk"),
                        id=f"v{i}_disk",
                    ),
                    Input(
                        value=(
                            ""
                            if vm["disk"] in ctx["disk_presets"]
                            else str(vm["disk"])
                        ),
                        placeholder=t("Disk"),
                        id=f"c{i}_disk",
                        classes="freeval",
                    ),
                    (
                        Button("−", id=f"m{i}", classes="vmcopy")
                        if item.get("instance")
                        else Static("", classes="vmcopy")
                    ),
                    Select(
                        [(b, b) for b in branches],
                        classes="vmbranch",
                        # Repli sur la branche du FORMULAIRE, jamais sur
                        # branches[0] : les rangées sont remontées dès que le
                        # jeu de VM change (une entrée cochée, une copie
                        # ajoutée, un renommage), et elles retombaient alors
                        # toutes sur « develop » quel que soit le choix commun.
                        value=(
                            self.rows[i]["vm"].get("branch")
                            if i < len(self.rows)
                            else ""
                        )
                        or self._branch(),
                        allow_blank=False,
                        id=f"v{i}_branch",
                    ),
                    (
                        Select(
                            [(lbl, i) for i, (lbl, _c) in enumerate(profiles)],
                            value=self._row_profile_index(i),
                            allow_blank=False,
                            classes="vmprof",
                            id=f"v{i}_prof",
                        )
                        if profiles
                        else Static("", classes="vmprof")
                    ),
                    Select(
                        self._type_options(),
                        value=vm.get("desktop") or SERVER,
                        allow_blank=False,
                        id=f"v{i}_type",
                    ),
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
            if widgets:
                plan.mount_all(widgets)
            self._shown_ids = self._row_ids()
            # Les saisies libres ne se révèlent qu'après le montage : leur
            # style ne peut pas être touché avant qu'elles existent.
            self.call_after_refresh(self._after_mount_rows)

        def _after_mount_rows(self) -> None:
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

        def _sync_free_inputs(self) -> None:
            for i, r in enumerate(self.rows):
                vm = r["vm"]
                for field, presets in (
                    ("vcpus", ctx["cpu_presets"]),
                    ("ram", ctx["ram_presets"]),
                    ("disk", ctx["disk_presets"]),
                ):
                    try:
                        widget = self.query_one(f"#c{i}_{field}", Input)
                    except Exception:
                        continue
                    # Visible si la valeur EST libre, ou si la liste est
                    # posée sur « libre… » en attente d'une saisie.
                    try:
                        chosen_free = (
                            self.query_one(f"#v{i}_{field}", Select).value
                            is FREE
                        )
                    except Exception:
                        chosen_free = False
                    free = chosen_free or vm[field] not in presets
                    widget.display = free
                    widget.disabled = not free

        def _row_head(self, index, row):
            """Ligne de titre d'une VM : nom, origine, état, marque de
            personnalisation. Sans elle, deux rangées aux réglages différents
            n'ont aucune explication à l'écran."""
            vm = row["vm"]
            icon = {"new": "", "exists": "⏭ ", "orphan": "❌ "}[row["state"]]
            state = "" if row["state"] == "new" else f"  {icon}{row['note']}"
            if row.get("locked"):
                mark = "  🔒 figée"
            elif row.get("custom"):
                mark = "  ✎"
            else:
                mark = ""
            return (
                f"[b]{vm['name']}[/b]  {vm['distro']} {vm['version']} "
                f"[{vm['arch']}]  {row['disk_gb']}G{state}{mark}"
            )

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
            elif event.radio_set.id == "f_type":
                self._clear_overrides(("desktop",))
                # Recalcul : le disque annonce inclut le bureau, et la
                # colonne Statut affiche le type de VM.
                self._recompute()
            elif event.radio_set.id == "f_profile":
                index = event.radio_set.pressed_index
                self.profile = "custom" if index == 4 else str(index + 1)
                self._clear_overrides(("vcpus", "ram", "disk"))
                custom = self.profile == "custom"
                for field, (sel, _inp) in RES_FIELDS.items():
                    self.query_one(sel, Select).disabled = not custom
                    self._show_free(field, custom and self._free.get(field))
                self._recompute()

        # -- rangées du panneau droit ------------------------------- #
        def _focused_row(self):
            """Rang de la VM dont un widget a le focus, ou None. C'est la seule
            désignation qui ait un sens ici : il n'y a plus de curseur unique,
            chaque rangée est éditable directement."""
            wid = getattr(self.focused, "id", "") or ""
            match = re.match(r"[vch](\d+)(?:_|$)", wid)
            if not match:
                return None
            index = int(match.group(1))
            return index if 0 <= index < len(self.rows) else None

        def _row_key(self, index):
            entries = self._plan_entries()
            return entry_key(entries[index]) if index < len(entries) else None

        def _clear_overrides(self, fields) -> None:
            """Rend au choix commun les VM NON figées, pour ces champs-là.

            Le cadenas est la seule chose qui résiste. Une valeur réglée à la
            main sur une rangée cède donc au choix global suivant : c'est ce
            qu'on attend d'un réglage « général », et le verrou existe
            précisément pour dire « pas celle-ci ».

            Par champ, pas en bloc : changer la RAM générale n'a aucune raison
            d'effacer le disque qu'on a réglé sur une VM.

            « name » n'y figure jamais : un renommage est explicite et ne
            découle d'aucune valeur générale."""
            changed = False
            for key in list(self.overrides):
                if key in self.locked:
                    continue
                for field in fields:
                    changed |= self.overrides[key].pop(field, None) is not None
                if not self.overrides[key]:
                    self.overrides.pop(key, None)
            if changed:
                # Forcer le remontage : une rangée peut porter une saisie
                # LIBRE, que le simple rafraîchissement laisse en place — on
                # verrait « 12 » à l'écran pendant que la VM vaut 2. Le
                # remontage rebâtit tout depuis le modèle. Sans risque de vol
                # de focus : ce chemin part d'un widget GLOBAL, jamais d'une
                # rangée.
                self._shown_ids = ()

        def _set_override(self, index, field, value) -> None:
            """Écrit — ou retire — la surcharge d'UNE VM."""
            key = self._row_key(index)
            if key is None:
                return
            if value in ("", 0, None):
                # Saisie vidée ou invalide : on RETIRE la surcharge au lieu
                # d'écrire un zéro, qui donnerait une VM à 0 vCPU.
                self.overrides.get(key, {}).pop(field, None)
                if not self.overrides.get(key):
                    self.overrides.pop(key, None)
            else:
                self.overrides.setdefault(key, {})[field] = value

        def _row_free(self, index, field, visible) -> None:
            widget = self.query_one(f"#c{index}_{field}", Input)
            widget.display = bool(visible)
            widget.disabled = not visible
            if visible:
                widget.focus()

        def _read_row_free(self, index, field):
            raw = self.query_one(f"#c{index}_{field}", Input).value.strip()
            if field == "disk":
                return parse_disk(raw) or ""
            return positive_int(raw, 0)

        def _show_free(self, field, visible) -> None:
            """Montre ou cache la saisie libre d'une ressource."""
            widget = self.query_one(RES_FIELDS[field][1], Input)
            widget.display = bool(visible)
            widget.disabled = not visible

        def on_selection_list_selected_changed(self, event) -> None:
            self._recompute()

        def on_select_changed(self, event) -> None:
            if self._syncing:
                return
            wid = event.select.id or ""
            row = re.match(r"v(\d+)_(vcpus|ram|disk|type|branch|prof)$", wid)
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
                vm_now = self.rows[index]["vm"]
                if field == "prof":
                    cmd = profiles[event.value][1]
                    if cmd == (
                        vm_now.get("install_cmd") or self._profile_cmd()
                    ):
                        return
                    self._set_override(
                        index,
                        "install_cmd",
                        "" if cmd == self._profile_cmd() else cmd,
                    )
                    self._recompute()
                    return
                if field == "branch":
                    # « la branche du formulaire » n'est pas une surcharge :
                    # la VM doit suivre si on la change en haut.
                    current = vm_now.get("branch") or self._branch()
                    if event.value == current:
                        return
                    self._set_override(
                        index,
                        "branch",
                        "" if event.value == self._branch() else event.value,
                    )
                    self._recompute()
                    return
                if field == "type":
                    new_desk = "" if event.value == SERVER else event.value
                    if new_desk == (vm_now.get("desktop") or ""):
                        return
                elif (
                    event.value is not FREE and event.value is not SELECT_NULL
                ):
                    if event.value == vm_now.get(field):
                        return
                if field == "type":
                    self._set_override(
                        index,
                        "desktop",
                        "" if event.value == SERVER else event.value,
                    )
                    # « Serveur » est un choix légitime, pas un retrait : on le
                    # note explicitement pour qu'il tienne face au défaut.
                    if event.value == SERVER:
                        key = self._row_key(index)
                        if key is not None:
                            self.overrides.setdefault(key, {})["desktop"] = ""
                elif event.value is FREE:
                    self._row_free(index, field, True)
                    self._set_override(
                        index, field, self._read_row_free(index, field)
                    )
                elif event.value is not SELECT_NULL:
                    self._row_free(index, field, False)
                    self._set_override(index, field, event.value)
                self._recompute()
                return
            # Les choix GLOBAUX de branche et de profil ne portent aucune
            # valeur de ressource : ils tombaient donc dans le « return »
            # ci-dessous sans rien recalculer, et les rangées restaient sur
            # l'ancienne version. Elles n'en gardent pas de copie — « » y
            # veut dire « celle du formulaire » — il suffit de redessiner.
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

        def _apply_free(self, field) -> None:
            """Relit la saisie libre. Une valeur invalide n'écrase rien : le
            profil retombe alors sur celle du catalogue."""
            raw = self.query_one(RES_FIELDS[field][1], Input).value.strip()
            if field == "disk":
                self.custom[field] = parse_disk(raw) or ""
            else:
                self.custom[field] = positive_int(raw, 0)
            self._clear_overrides((field,))

        def on_input_changed(self, event) -> None:
            if self._syncing:
                return
            wid = event.input.id or ""
            row = re.match(r"c(\d+)_(vcpus|ram|disk)$", wid)
            if row:
                index, field = int(row.group(1)), row.group(2)
                self._set_override(
                    index, field, self._read_row_free(index, field)
                )
                self._recompute()
                return
            field = INPUT_TO_FIELD.get(event.input.id)
            if field:
                self._apply_free(field)
                self._recompute()

        def _set_lock(self, index, on) -> None:
            """Fige — ou libère — les ressources d'une VM.

            Figer, c'est recopier les valeurs EFFECTIVES du moment dans les
            surcharges : le profil commun ne les atteint plus. Libérer les
            retire, et la VM retombe sous le profil. Le mécanisme est celui
            des surcharges, déjà éprouvé ; le verrou n'en est que la commande
            explicite, et il couvre les quatre champs d'un coup."""
            key = self._row_key(index)
            if key is None or index >= len(self.rows):
                return
            if on:
                vm = self.rows[index]["vm"]
                self.locked.add(key)
                # TOUT ce que la VM tient d'un choix commun est recopié, pas
                # seulement les ressources : la branche et le profil Odoo en
                # font partie. Les oublier laissait une VM « figée » changer
                # de version d'ERPLibre dès qu'on touchait au choix générique,
                # ce qui vide le mot de son sens.
                #
                # Les deux se résolvent AVANT d'être figés : « » y signifie
                # « celle du formulaire », et geler une chaîne vide ne
                # gèlerait rien du tout.
                self.overrides[key] = {
                    "vcpus": vm["vcpus"],
                    "ram": vm["ram"],
                    "disk": vm["disk"],
                    "desktop": vm.get("desktop") or "",
                    "branch": vm.get("branch") or self._branch(),
                    "install_cmd": (
                        vm.get("install_cmd") or self._profile_cmd()
                    ),
                }
            else:
                self.locked.discard(key)
                self.overrides.pop(key, None)
            self._recompute()
            # La couleur de la ligne suit le verrou sans tout remonter : un
            # remontage volerait le focus à la case qu'on vient de cocher.
            cards = self.query_one("#plan", VerticalScroll).children
            if index < len(cards):
                cards[index].set_class(on, "locked")
            btn = self.query_one(f"#l{index}", Button)
            btn.label = "🔒" if on else "🔓"
            btn.variant = "success" if on else "default"

        def _add_copy(self, index, delta) -> None:
            """Ajoute ou retire un exemplaire de l'entrée visée.

            Retirer enlève le DERNIER exemplaire, et avec lui ses réglages :
            les garder ferait resurgir d'anciennes valeurs à la copie
            suivante, sans que rien ne l'explique."""
            entries = self._plan_entries()
            if index >= len(entries):
                return
            item = entries[index]
            base = (item["distro"], item["version"], item["arch"])
            count = self.copies.get(base, 0)
            if delta > 0:
                self.copies[base] = count + 1
            else:
                if count <= 0:
                    return
                gone = (*base, count)
                self.overrides.pop(gone, None)
                self.locked.discard(gone)
                self.copies[base] = count - 1
                if not self.copies[base]:
                    self.copies.pop(base, None)
            self._recompute()
            # Le JEU de VM a changé : les rangées doivent être rebâties.
            self._mount_rows()

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

        def _rename(self, index) -> None:
            """Renomme une VM. Le nom saisi devient une surcharge comme les
            autres : il survit au recalcul, et F4 le retire avec le reste."""
            key = self._row_key(index)
            if key is None or index >= len(self.rows):
                return
            entries = self._plan_entries()
            auto = vm_name(
                entries[index]["name"],
                self.rows[index]["vm"].get("desktop"),
                desktop_suffixes,
            )

            def done(value):
                if value is None:
                    return
                if not str(value).strip():
                    self.overrides.get(key, {}).pop("name", None)
                    if not self.overrides.get(key):
                        self.overrides.pop(key, None)
                else:
                    clean = clean_hostname(value)
                    if not clean:
                        self.notify(
                            t("Invalid name: letters, digits, hyphens."),
                            severity="error",
                        )
                        return
                    self.overrides.setdefault(key, {})["name"] = clean
                self._recompute()
                self._mount_rows()

            self.push_screen(
                RenameScreen(self.rows[index]["vm"]["name"], auto), done
            )

        def on_checkbox_changed(self, event) -> None:
            if event.checkbox.id == "f_install":
                self._recompute()  # le disque annoncé inclut le +5 G ERPLibre
            elif event.checkbox.id == "f_par_all":
                self.query_one("#f_par", Select).disabled = event.value

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
                "desktop": self._default_desktop(),
                "python_provider": self._python_provider(),
                "app_store": self._app_store(),
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
