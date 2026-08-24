#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Socle commun des formulaires de déploiement (QEMU/KVM et Proxmox VE).

Ce fichier existe pour une raison simple : les deux formulaires posent les
mêmes questions de fond — combien de processeurs, combien de mémoire, quel
disque, quelles machines, et montre-moi le plan avant de lancer. Seul CE QUI
VARIE reste dans les fichiers de formulaire : le catalogue et les options
propres à chaque hyperviseur.

Trois couches, du plus sûr au plus fragile :

1. La LOGIQUE PURE (lecture d'une taille, d'un entier, calcul du plan et des
   totaux, assemblage de la spec). Aucune dépendance à Textual, donc
   vérifiable sans terminal — c'est là que vivent les pièges déjà payés :
   « 128G » qui rendait 0, une spec qui perdait une clé.
2. Le SOCLE VISUEL : les règles CSS que les deux formulaires partagent, et les
   fabriques des sélecteurs « préréglages + saisie libre ».
3. La VUE DE PROGRESSION (`run_deploy_progress`), déjà générique : elle prend
   des travaux « (id, nom, argv) » et rend « (nom, code, sortie, durée) ».
   Elle ne sait rien de libvirt ni de qm, et sert donc les deux tels quels.

Compatibilité : `qemu_deploy_form` réexporte ce module, si bien que les
appelants historiques (`from script.todo.qemu_deploy_form import parse_ram`)
continuent de fonctionner.
"""

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


def parse_ram(value):
    """« 2048 », « 128G », « 1,5G » -> mébioctets, ou 0 si invalide.

    Les valeurs proposées s'affichent en G — « 2G », « 16G » — alors que la
    saisie libre comptait en Mo. Taper « 128G », ce que l'affichage invite à
    faire, rendait 0 : la surcharge était alors RETIRÉE et la VM revenait à la
    valeur du catalogue, sans un mot. On accepte donc les deux écritures, un
    nombre nu restant des mébioctets."""
    txt = str(value or "").strip().upper().replace(",", ".")
    factor = 1
    if txt.endswith("GI"):
        factor, txt = 1024, txt[:-2]
    elif txt.endswith(("G", "T")):
        factor = 1024 * (1024 if txt.endswith("T") else 1)
        txt = txt[:-1]
    elif txt.endswith(("M", "MI")):
        txt = txt.rstrip("IM")
    try:
        mib = int(float(txt) * factor)
    except ValueError:
        return 0
    return mib if mib > 0 else 0


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
                # Libelle du profil, pour que le recapitulatif puisse dire
                # « Odoo 18 » sans connaitre la liste des profils.
                "install_label": "",
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


def libvirt_orphan(name) -> bool:
    """Un disque qcow2 sans domaine, sur CETTE machine.

    Propre à QEMU/KVM : un Proxmox distant n'a pas ce répertoire, et ses
    disques vivent dans un stockage que seul l'hôte connaît.
    """
    return os.path.exists(f"/var/lib/libvirt/images/{name}.qcow2")


def vm_status(name, domains, orphelin=None):
    """État d'un nom face à l'existant : ('new'|'exists'|'orphan', message).

    Les deux collisions n'ont pas la même gravité — une VM définie est
    ignorée, un qcow2 resté seul fait échouer deploy_qemu, qui refuse
    d'écraser sans --force.

    `orphelin` dit comment reconnaître un disque resté seul. Le défaut regarde
    le répertoire de libvirt ; un hyperviseur distant passe le sien, ou
    `lambda _n: False` s'il n'a pas de disque orphelin à craindre."""
    if name in domains:
        return "exists", t("exists - skipped")
    if (orphelin or libvirt_orphan)(name):
        return "orphan", t("orphan disk - will FAIL")
    return "new", ""


def plan_rows(vms, domains, extra_disk_gb=0, orphelin=None):
    """Lignes du tableau du plan : une par VM, avec son état."""
    rows = []
    for vm in vms:
        state, note = vm_status(vm["name"], domains, orphelin)
        rows.append(
            {
                "vm": vm,
                "state": state,
                "note": note,
                "disk_gb": disk_gb(vm["disk"]) + extra_disk_gb,
            }
        )
    return rows


def gib(nbytes) -> int:
    """Octets -> Gio entiers. Le plan compte en Go partout ailleurs : mêler
    des unités sur la même ligne de totaux la rendrait illisible."""
    try:
        return int(nbytes) // (1 << 30)
    except (TypeError, ValueError):
        return 0


def disk_note(plan_gb, free_gb, total_gb=0) -> str:
    """« ~50 G / 20 G libres sur 270 G » — la demande, le reste, la capacité.

    La demande seule ne dit pas si ça rentre : c'est le rapprochement qui
    décide, et c'est pourquoi la place s'affiche là même où la demande était
    déjà écrite. Les deux nombres ne sont pas redondants — 20 Go libres sur
    270 se lit autrement que 20 sur 24. Sans mesure (0), on n'invente rien :
    la demande s'affiche seule.
    """
    if not free_gb:
        return f"~{plan_gb} G"
    if not total_gb:
        return f"~{plan_gb} G / {free_gb} G {t('free')}"
    return f"~{plan_gb} G / {free_gb} G {t('free of')} {total_gb} G"


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
        "vm_tools": tuple(form.get("vm_tools") or ()),
        "python_provider": form.get("python_provider", ""),
        "app_store": form.get("app_store", "deb"),
        "install": form["install"],
        # Au NIVEAU DU DÉPLOIEMENT, pas de l'installation : une VM sans
        # ERPLibre se suit aussi (cloud-init, puis relevé système). Absent de
        # cette assemblée, le choix du formulaire n'atteignait jamais la spec.
        "monitor": form.get("monitor", True),
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
# Socle visuel — ce que les deux formulaires partagent
# --------------------------------------------------------------------------- #
# Sentinelle du dernier choix d'une liste de ressources : il ne porte pas de
# valeur, il révèle la saisie libre placée juste dessous. Partagée pour que les
# deux formulaires se comportent pareil devant « autre… ».
FREE = "__free__"

# Règles communes : la mise en page (panneau de champs à gauche, plan à droite,
# totaux dessous) et les fenêtres modales. Chaque formulaire y ajoute ses
# propres règles — celles qui nomment SES widgets.
#
# Extrait du formulaire QEMU, où elles étaient mêlées à ses spécificités. Le
# rendu du formulaire QEMU a été comparé caractère par caractère avant/après
# l'extraction : identique.
CSS_BASE = """
#body { height: 1fr; }
#fields { width: 62; border: solid $accent; overflow-y: auto; }
#right { width: 1fr; }
#plan {
    height: 1fr; border: solid $accent;
    overflow-x: auto; scrollbar-size-horizontal: 1;
}
#totals { height: auto; color: $text-muted; padding: 0 1; }
.grouptitle { color: $accent; text-style: bold; padding: 1 0 0 0; }
.freeval { display: none; width: 9; }
/* « width: auto » sur la CARTE, pas seulement sur la rangée. Un conteneur
Textual vaut « width: 1fr » par défaut : la carte se bornait donc au panneau,
et c'est ELLE que « #plan » mesure pour sa largeur virtuelle. La rangée avait
beau être en « auto », son débordement était coupé dans une carte qui ne
grandissait pas, et la barre horizontale n'apparaissait jamais. */
.vmcard {
    height: auto; width: auto;
    border-bottom: solid $panel; padding: 0 1;
}
/* Une VM figée se voit à la LIGNE, pas à une case perdue au bout : c'est ce
qui permet de balayer le plan et de savoir d'un coup ce qui échappe au
profil. */
.vmcard.locked { background: $success 20%; }
.vmlock { width: 5; min-width: 5; }
.vmcopy { width: 5; min-width: 5; }
.vmhead { height: 1; }
/* « width: auto » et le défilement du plan : sans eux, une rangée plus large
que le panneau est COUPÉE au lieu d'être atteignable. */
.vmrow { height: 3; width: auto; align-vertical: middle; }
.vmrow Select { width: 15; }
.vmrow Input { width: 11; }
#reslabel { color: $text-muted; }
PreviewScreen { align: center middle; }
#prevbox {
    width: 90%; height: 70%; padding: 1 2;
    border: thick $accent; background: $surface;
}
#prevtitle { height: 1; color: $accent; text-style: bold; }
#prevbody { height: 1fr; overflow-y: auto; }
RenameScreen { align: center middle; }
#renbox {
    width: 60; height: auto; padding: 1 2;
    border: thick $accent; background: $surface;
}
#rentitle { color: $accent; text-style: bold; }
#renhint { color: $text-muted; }
#renbtns { height: auto; padding-top: 1; }
"""


def res_choices(presets, fmt=None):
    """[(libellé, valeur)] d'une liste de préréglages, « autre… » en dernier.

    Le dernier choix est la sentinelle FREE : c'est lui qui révèle la saisie
    libre. Les deux formulaires l'utilisent, donc « autre… » se présente et se
    comporte pareil partout.
    """
    faire = fmt or (lambda v: str(v))
    return [(faire(v), str(v)) for v in presets] + [(t("other…"), FREE)]


def res_value(choix, libre, defaut, lecteur=None):
    """Valeur retenue d'un couple (liste, saisie libre).

    « autre… » sans rien taper ne veut pas dire zéro : il veut dire « laisse
    comme avant ». Ce repli est la raison d'être de cette fonction — sans lui,
    valider un formulaire à peine ouvert rétrécissait les machines.
    """
    lire = lecteur or (lambda v: positive_int(v, 0))
    if choix == FREE or choix is None:
        return lire(libre) or defaut
    return lire(choix) or defaut


# Les trois ressources que TOUT déploiement demande, et les deux widgets par
# lesquels chacune se règle : une liste de préréglages (« #f_ram ») et la
# saisie libre qu'elle révèle (« #c_ram »). Une seule table, pour que le
# lecteur d'un formulaire trouve les champs de l'autre au même endroit.
RES_FIELDS = {
    "vcpus": ("#f_vcpus", "#c_vcpus"),
    "ram": ("#f_ram", "#c_ram"),
    "disk": ("#f_disk", "#c_disk"),
}
SELECT_TO_FIELD = {sel[1:]: f for f, (sel, _i) in RES_FIELDS.items()}
INPUT_TO_FIELD = {inp[1:]: f for f, (_s, inp) in RES_FIELDS.items()}

# La mémoire s'affiche en Go alors qu'elle se compte en Mo : c'est la seule
# ressource dont la valeur ne se lit pas telle quelle.
RES_FMT = {
    "vcpus": lambda v: str(v),
    "ram": lambda v: f"{v // 1024}G",
    "disk": lambda v: str(v),
}


def res_labels():
    """Libellés des trois ressources, traduits à l'APPEL.

    Pas une constante de module : la langue est choisie après l'import, et une
    table figée à l'import resterait en anglais.
    """
    return {
        "vcpus": t("vCPU"),
        "ram": t("RAM: 2048 or 8G"),
        "disk": t("Disk"),
    }


def res_row_widgets(index, vm, presets, labels=None, null=None):
    """Les six widgets du triplet vCPU / RAM / disque d'une rangée de plan.

    Chaque ressource se présente pareil : une liste de préréglages, plus une
    saisie libre masquée que « valeur libre… » révèle. Les deux formulaires
    appellent cette fabrique, donc les ids se correspondent d'un formulaire à
    l'autre — « v3_ram » pour la liste de la quatrième rangée, « c3_ram » pour
    sa saisie libre — et le code qui relit les surcharges n'a pas à savoir
    quel formulaire a monté la rangée.

    `presets` donne les choix par champ ; `labels` permet à l'appelant de
    garder ses propres mots. `null` est la sentinelle « rien de sélectionné »
    de Textual, que l'appelant a déjà résolue selon sa version.
    """
    from textual.widgets import Input, Select

    if null is None:  # pragma: no cover - dépend de la version de Textual
        null = getattr(Select, "NULL", Select.BLANK)
    mots = res_labels()
    mots.update(labels or {})
    widgets = []
    for champ in ("vcpus", "ram", "disk"):
        choix = presets[champ]
        valeur = vm[champ]
        # « valeur dans les préréglages » décide de TOUT : la liste montre la
        # valeur, ou elle se met en retrait et la saisie libre la porte.
        connue = valeur in choix
        widgets.append(
            Select(
                [(RES_FMT[champ](c), c) for c in choix]
                + [(t("free value…"), FREE)],
                value=valeur if connue else null,
                prompt=mots[champ],
                id=f"v{index}_{champ}",
            )
        )
        widgets.append(
            Input(
                value="" if connue else str(valeur),
                placeholder=mots[champ],
                id=f"c{index}_{champ}",
                classes="freeval",
            )
        )
    return widgets


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
