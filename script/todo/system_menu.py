#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Système : le diagnostic du poste, l'espace qu'on peut récupérer et
la mémoire d'échange.

Les faits viennent de system_diagnostic et les candidats de
system_cleanup ; ce fichier les met en phrases, pose les questions et tient
le formulaire. Rien n'est effacé sans une case cochée ET une confirmation.
Les plans de swap et de zram viennent de system_swap : ce fichier les
montre, et ne les lance qu'après un oui.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import collections
import datetime
import os
import shlex
import subprocess
import sys
import tempfile
import time

import click

from script.todo import (
    system_cleanup,
    system_cpu,
    system_diagnostic,
    system_gpu,
)
from script.todo import system_swap as ss
from script.todo.todo_i18n import t

# Les jours d'inactivité au-delà desquels un reste de /tmp ou une session
# web d'Odoo devient un candidat.
JOURS_INACTIFS = 2

LIBELLES_CATEGORIE = {
    system_cleanup.CACHE: "Cache",
    system_cleanup.TMP: "Temporary leftover",
    system_cleanup.FILESTORE: "Orphan filestore",
    system_cleanup.SESSIONS: "Odoo web sessions",
    system_cleanup.VENV: "Other Odoo venv",
    system_cleanup.VENV_AUTRE: "Venv of another checkout",
    system_cleanup.INCONNU: "Unknown cache",
    system_cleanup.CORBEILLE: "Trash",
}

MISES_EN_GARDE = {
    "reinstall": "reinstall to switch back to this version",
    "recent": "recent: its database may be being created",
    "download": "downloaded again on next use",
    "unknown": "contents unknown: look before deleting",
    "reinstall-checkout": "that checkout needs a reinstall to run",
}

RAISONS = {
    "link": "path is or crosses a link",
    "owner": "not yours",
    "protected": "private/ or tasks/",
    "outside": "outside the allowed directories",
    "missing": "already gone",
    "database": "its database exists again",
    "no-database-list": "database list unavailable",
    "mount": "a filesystem is mounted on it or under it",
    "in-use": "a process is using it",
}


def octets(n):
    """1536 -> « 1.5 Kio » ; None -> None."""
    if n is None:
        return None
    for unite in ("o", "Kio", "Mio", "Gio", "Tio"):
        if abs(n) < 1024 or unite == "Tio":
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}"
        n /= 1024
    return None


def duree(secondes):
    """Secondes -> « 3 j 4 h », « 5 h 12 min », « 7 min »."""
    if secondes is None:
        return None
    minutes = int(secondes // 60)
    jours, minutes = divmod(minutes, 1440)
    heures, minutes = divmod(minutes, 60)
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes} min"
    return f"{minutes} min"


def lignes_diagnostic(faits):
    """Le diagnostic en lignes de texte, section par section."""
    absent = t("unavailable")

    def val(x):
        return absent if x in (None, "", []) else str(x)

    ident = faits["identity"]
    cpu = faits["cpu"]
    mem = faits["memory"]
    charge = faits["load"]
    erp = faits["erplibre"]
    materiel = " ".join(x for x in (ident["vendor"], ident["model"]) if x)
    lignes = [
        f"── {t('Identity')} ──",
        f"  {t('Host name')} : {val(ident['hostname'])}",
        f"  {t('Operating system')} : {val(ident['os'])}",
        f"  {t('Kernel')} : {val(ident['kernel'])}",
        f"  {t('Architecture')} : {val(ident['architecture'])}",
        f"  {t('Chassis')} : {val(ident['chassis'])}",
        f"  {t('Virtualization')} : {val(ident['virtualization'])}",
        f"  {t('Hardware')} : {val(materiel)}",
        "",
        f"── {t('Processor and memory')} ──",
        f"  {t('Processor')} : {val(cpu['model'])}",
        f"  {t('Cores (physical / logical)')} :"
        f" {val(cpu['physical'])} / {val(cpu['logical'])}",
        f"  {t('Memory')} : {val(octets(mem['available']))}"
        f" {t('available of')} {val(octets(mem['total']))}",
        f"  {t('Swap')} : {val(octets(mem['swap_free']))}"
        f" {t('free of')} {val(octets(mem['swap_total']))}",
    ]
    gpu = faits["gpu"]
    lignes.append(
        f"  {t('Graphics')} : "
        + (
            t("lspci not installed")
            if gpu is None
            else (", ".join(gpu) if gpu else absent)
        )
    )
    lignes += ["", f"── {t('Disks')} ──"]
    for p in faits["partitions"] or []:
        pct = 100 * p["used"] / p["total"] if p["total"] else 0
        repere = f"  ← {t('repository')}" if p["repo"] else ""
        if p.get("others"):
            repere += f"  (+ {', '.join(p['others'])})"
        lignes.append(
            f"  {p['mountpoint']:<20} {p['fstype']:<6}"
            f" {octets(p['free']):>10} {t('free of')}"
            f" {octets(p['total']):>10} ({pct:.0f} %){repere}"
        )
    if not faits["partitions"]:
        lignes.append(f"  {absent}")
    moyennes = charge["load"]
    lignes += [
        "",
        f"── {t('Load')} ──",
        f"  {t('Load (1, 5, 15 min)')} : "
        + (" ".join(f"{x:.2f}" for x in moyennes) if moyennes else absent),
        f"  {t('Uptime')} : {val(duree(charge['uptime']))}",
        "",
        "── ERPLibre ──",
        f"  ERPLibre : {val(erp['erplibre'])}   Odoo : {val(erp['odoo'])}"
        f"   Python : {val(erp['python'])}",
        f"  {t('Active venv')} : {val(erp['active_venv'])}",
        f"  {t('Venvs')} : {val(', '.join(erp['venvs']))}",
    ]
    return lignes


def _tri_memoire(p):
    """Clé de tri : la plus grosse mémoire d'abord, l'inconnue à la fin."""
    total = p.get("memoire")
    if total is None and p.get("regions"):
        total = sum(p["regions"].values())
    return (total is None, -(total or 0), p["pid"])


def entier(texte):
    """`texte` en entier s'il n'est fait que de chiffres ASCII ; None
    sinon. str.isdigit() accepte aussi « ² » ou les chiffres d'autres
    écritures, sur lesquels int() lève ValueError."""
    if texte and texte.isascii() and texte.isdigit():
        return int(texte)
    return None


def affichable(texte):
    """`texte` sans caractère de contrôle : chacun devient « ? ».

    Le nom (comm) et la ligne de commande d'un processus sont choisis par
    le compte qui le lance. Après la relecture sudo, ou par nvidia-smi, ce
    sont ceux de TOUS les comptes : une séquence d'échappement ou un saut
    de ligne y écrirait dans le terminal de qui lit le rapport, ou y
    forgerait une ligne."""
    if texte is None:
        return None
    return "".join(c if c.isprintable() else "?" for c in str(texte))


def _ligne_processus(p, memoire):
    """« PID  mémoire  compte  commande », colonnes alignées."""
    qui = affichable(p.get("compte")) or "?"
    quoi = affichable(p.get("commande") or p.get("nom")) or "?"
    return f"  {p['pid']:>8}  {memoire}  {qui:<12} {quoi}"


def lignes_gpu(faits):
    """La mémoire GPU en lignes de texte : les cartes, puis les processus
    par source, le plus gros d'abord, puis ce que la lecture n'a pas vu."""
    absent = t("unavailable")
    lignes = [f"── {t('Graphics cards')} ──"]
    for c in faits["cartes"]:
        ligne = (
            f"  {c['carte']} · {c['fabricant'] or absent}"
            f" · {c['modele'] or c['pci']}"
            f" · {t('driver')} {c['pilote']}"
        )
        lignes.append(ligne)
        if c["vram_totale"]:
            lignes.append(
                f"      VRAM : {octets(c['vram_utilisee']) or absent}"
                f" {t('used of')} {octets(c['vram_totale'])}"
            )
    if not faits["cartes"]:
        lignes.append(f"  {t('No graphics card found.')}")
    if faits["nvidia_sans_reponse"]:
        lignes.append(
            f"  ⚠ {t('An NVIDIA card is present, but nvidia-smi is missing or fails: install the NVIDIA driver utilities.')}"
        )

    nv = faits["nvidia"]
    if nv:
        lignes += ["", f"── NVIDIA ({nv['source']}) ──"]
        if "compute-apps" in nv["source"]:
            lignes.append(
                f"  ⚠ {t('Compute processes only: graphics processes are not listed.')}"
            )
        for gpu in nv["gpus"]:
            lignes.append(
                f"  GPU {gpu['index']} · {gpu['nom'] or absent} :"
                f" {octets(gpu['utilisee']) or absent}"
                f" {t('used of')} {octets(gpu['totale']) or absent}"
            )
            if not gpu["processus"]:
                lignes.append(f"      {t('No process uses this card.')}")
                continue
            lignes.append(
                f"  {'PID':>8}  {'Type':<4} {t('Memory'):>10}"
                f"  {t('Account'):<12} {t('Process')}"
            )
            for p in sorted(gpu["processus"], key=_tri_memoire):
                memoire = f"{p['type'] or '?':<4} {octets(p['memoire']) or 'N/A':>10}"
                lignes.append(_ligne_processus(p, memoire))
            connues = [p["memoire"] for p in gpu["processus"]]
            if gpu["utilisee"] is not None and None not in connues:
                reste = gpu["utilisee"] - sum(connues)
                if reste > 0:
                    lignes.append(
                        f"  {t('Not attributed to a listed process (driver, contexts, other containers)')} :"
                        f" {octets(reste)}"
                    )

    d = faits["drm"]
    if d is not None:
        source = "/proc/*/fdinfo, sudo" if d.get("sudo") else "/proc/*/fdinfo"
        lignes += ["", f"── DRM ({source}) ──"]
        par_carte = {}
        for p in d["processus"]:
            par_carte.setdefault((p["pci"], p["pilote"]), []).append(p)
        for (pci, pilote), liste in sorted(
            par_carte.items(), key=lambda x: str(x[0])
        ):
            lignes.append(
                f"  {pci or absent} · {t('driver')} {pilote or absent}"
            )
            lignes.append(
                f"  {'PID':>8}  {t('Memory'):<28}  {t('Account'):<12}"
                f" {t('Process')}"
            )
            for p in sorted(liste, key=_tri_memoire):
                memoire = (
                    " · ".join(
                        f"{region} {octets(n)}"
                        for region, n in sorted(
                            p["regions"].items(), key=lambda x: -x[1]
                        )
                        if n
                    )
                    or "0"
                )
                lignes.append(_ligne_processus(p, f"{memoire:<28}"))
        if not d["processus"] and not d["sans_stats"]:
            lignes.append(
                f"  {t('No process of this account uses a DRM card.')}"
            )
        if d["sans_stats"]:
            noms = ", ".join(
                f"{affichable(p['nom']) or '?'} ({p['pid']})"
                for p in d["sans_stats"]
            )
            lignes.append(
                f"  ⚠ {len(d['sans_stats'])}"
                f" {t('process(es) hold a card whose driver publishes no per-process memory:')}"
                f" {noms}"
            )
        if d["illisibles"]:
            lignes.append(
                f"  ⚠ {d['illisibles']}"
                f" {t('processes of other accounts cannot be read without root: their GPU memory is not counted.')}"
            )
    return lignes


def libelle(candidat):
    """Une ligne du formulaire : taille, catégorie, nom, mise en garde."""
    nom = candidat.nom
    if len(candidat.chemins) > 1:
        nom += f" ({len(candidat.chemins)})"
    ligne = (
        f"{octets(candidat.taille):>10}  "
        f"{t(LIBELLES_CATEGORIE[candidat.categorie])} : {nom}"
    )
    if candidat.age:
        ligne += f"  · {duree(candidat.age)}"
    if candidat.mise_en_garde:
        ligne += f"  ⚠ {t(MISES_EN_GARDE[candidat.mise_en_garde])}"
    return ligne


def choisir_au_formulaire(candidats):
    """Les indices cochés dans un formulaire Textual ; None si on annule,
    « sans-tui » si Textual manque (l'appelant pose alors la question en
    ligne)."""
    app = formulaire(candidats)
    return "sans-tui" if app is None else app.run()


def formulaire(candidats):
    """L'application Textual du choix, ou None si Textual manque. À part
    de son lancement pour qu'un test la pilote."""
    try:
        from rich.text import Text
        from textual.app import App
        from textual.containers import Horizontal
        from textual.widgets import (
            Button,
            Footer,
            Header,
            SelectionList,
            Static,
        )
        from textual.widgets.selection_list import Selection
    except ImportError:
        return None

    class Formulaire(App):
        TITLE = t("Space to reclaim")
        CSS = """
        SelectionList { height: 1fr; }
        #boutons { height: auto; padding: 1 0 0 0; }
        Button { margin: 0 2 0 0; }
        """
        BINDINGS = [("escape", "annuler", t("Cancel"))]

        def compose(self):
            yield Header()
            # Du texte brut : un chemin porte parfois des crochets, que le
            # balisage de Textual prendrait pour les siens.
            yield Static(Text(t("Check what to delete, then choose Delete.")))
            yield SelectionList(
                *(
                    Selection(Text(libelle(c)), i, c.coche)
                    for i, c in enumerate(candidats)
                )
            )
            with Horizontal(id="boutons"):
                yield Button(t("Delete"), id="effacer", variant="error")
                yield Button(t("Cancel"), id="annuler")
            yield Footer()

        def on_button_pressed(self, event):
            if event.button.id == "effacer":
                self.exit(list(self.query_one(SelectionList).selected))
            else:
                self.exit(None)

        def action_annuler(self):
            self.exit(None)

    return Formulaire()


def choisir_en_ligne(candidats):
    """La même chose sans terminal plein écran : une liste numérotée."""
    for i, c in enumerate(candidats, 1):
        print(f"  [{i}] {'☑' if c.coche else '☐'} {libelle(c)}")
    reponse = input(
        t(
            "Numbers to delete (e.g. 1,3), Enter for the checked ones, c to cancel: "
        )
    ).strip()
    if reponse.lower() == "c":
        return None
    if not reponse:
        return [i for i, c in enumerate(candidats) if c.coche]
    choisis = []
    for morceau in reponse.replace(" ", "").split(","):
        numero = entier(morceau)
        if numero is not None and 1 <= numero <= len(candidats):
            choisis.append(numero - 1)
    return sorted(set(choisis))


# Mémoire d'échange : chaque code que rend system_swap -> sa clé de
# traduction. Les champs {…} reçoivent les « details » du plan, les tailles
# déjà écrites par octets().
RAISONS_SWAP = {
    "container": (
        "Container ({virtualization}): the host owns the swap and the zram, "
        "nothing can be changed from inside."
    ),
    "not_active": "{path} is not an active swap.",
    "zram": "{path} is a zram device: use the zram entries.",
    "partition": (
        "{path} is a swap partition: a partition cannot be resized from "
        "here. A swapfile can be created instead, for instance {suggestion}."
    ),
    "partition_shrink": (
        "{path} is a swap partition: a partition cannot be shrunk from here."
    ),
    "below_floor": "{new} is below the minimum of {floor}.",
    "same_size": "The swap already has this size ({old}).",
    "not_larger": "{new} is not larger than the current {old}.",
    "not_smaller": "{new} is not smaller than the current {old}.",
    "fs_unsupported": "The filesystem {fstype} does not accept a swapfile.",
    "ram_cannot_absorb": (
        "{used} of swap is in use, but the system can absorb only "
        "{capacity} ({available} of available memory, minus a margin of "
        "{margin}, plus {other_swap_free} free in the other disk swaps): "
        "turning it off would exhaust the memory. Close programs, then try "
        "again."
    ),
    "disk_unknown": "The free space of {mountpoint} cannot be read.",
    "disk_full": (
        "Not enough free disk space: {needed} needed, margin included, "
        "{free} free. Largest possible size: {max_size}."
    ),
    "invalid_path": "Invalid path: {path} (absolute, without ..).",
    "already_active": "{path} is already an active swap.",
    "exists": "{path} already exists: choose another path.",
    "parent_missing": "The directory {parent} does not exist.",
    "zram_too_large": (
        "{new} exceeds the zram maximum of {max}, twice the RAM."
    ),
    "no_package_manager": (
        "Unknown package manager ({manager}): install zram-generator by hand."
    ),
    "no_zram": "No zram is active or configured.",
    "zram_reboot_required": (
        "The running kernel ({running}) no longer has its modules: the "
        "kernel package was updated to {installed}. The zram module loads "
        "only after a reboot."
    ),
    "zram_unavailable": ("The running kernel ({running}) has no zram module."),
    "zram_service": (
        "{service} already manages the zram: change its size in that "
        "service's own settings, or disable it (zram - disable) first."
    ),
    "swappiness_range": (
        "{value} is outside what the running kernel ({running}) accepts for "
        "vm.swappiness: 0 to {limit}."
    ),
    "page_cluster_range": (
        "{value} is outside what vm.page-cluster accepts: 0 to {limit}."
    ),
}

ALERTES_SWAP = {
    "hibernation": (
        "Hibernation resumes from this swap (resume={resume}): once the "
        "file is recreated, resume_offset must be updated or resuming fails."
    ),
    "btrfs_snapshot": (
        "The swapfile sits in the subvolume of {subvolume}: it blocks the "
        "snapshots of that subvolume. A dedicated subvolume, such as /swap, "
        "avoids it."
    ),
    "zram_over_ram": (
        "This zram is larger than the RAM ({ram}): it pays off only if the "
        "data compresses well."
    ),
    "disk_priority": (
        "These disk swaps have a priority at least equal to zram's, so they "
        "fill first: {paths}."
    ),
    "dropin_overrides": (
        "These drop-in files redefine zram0 and override the new setting: "
        "{paths}."
    ),
    "zram_tools_conflict": (
        "zram-tools is also installed: both tools claim /dev/zram0. Disable "
        "zramswap.service."
    ),
    "dropin_etc": "These files in /etc still configure a zram: {paths}.",
    "low_swappiness": (
        "vm.swappiness is {value}: below 60, the kernel drops page cache "
        "rather than swap, and the zram stays nearly unused. Swap memory › "
        "Swappiness [7] raises it."
    ),
    "sysctl_dead": (
        "These files also set {key} but are overridden, without effect: "
        "{paths}."
    ),
}

# La raison de la swappiness conseillée (recommandation_swappiness).
RAISONS_SWAPPINESS = {
    "zram": (
        "zram is active or configured: swapping to compressed RAM costs less "
        "than reading evicted page cache back from disk. vm.page-cluster 0: "
        "zram reads single pages faster than clusters."
    ),
    "postgresql": (
        "PostgreSQL is running and the swap is on disk: a low value keeps the "
        "database processes in RAM and swaps only as a last resort."
    ),
    "default": "The swap is on disk: the kernel default.",
    "no_swap": (
        "No swap is active or listed in /etc/fstab: vm.swappiness has no "
        "effect."
    ),
}

VERDICTS_MEMOIRE = {
    "vm": (
        "Virtual machine ({virtualization}): the hypervisor sets the memory. "
        "Increase it from the host."
    ),
    "container": (
        "Container ({virtualization}): the host sets its memory limit. "
        "Change it from the host."
    ),
    "unknown": (
        "The memory slots could not be read: without dmidecode, nothing "
        "says whether RAM can be added."
    ),
    "free_slots": "Yes: {free_slots} free slot(s) out of {slots}.",
    "replace": (
        "Yes, by replacing modules with larger ones: every slot is used, "
        "and the board accepts up to {max_capacity}."
    ),
    "max": "No: the memory is at the maximum the board accepts.",
    "soldered": "No: the memory is soldered to the board, with no slot.",
}

TYPES_SWAP = {"file": "swapfile", "partition": "partition", "zram": "zram"}

# Les champs de details qui portent des octets.
TAILLES_SWAP = {
    "old",
    "new",
    "floor",
    "used",
    "available",
    "margin",
    "other_swap_free",
    "capacity",
    "needed",
    "free",
    "max_size",
    "max",
    "ram",
    "installed",
    "max_capacity",
    "max_addable",
    "swap_growth",
    "size",
}


def _champs(details):
    """details -> valeurs prêtes pour format_map : octets() pour les
    tailles, une liste jointe par des virgules, « ? » pour ce qui manque
    (un champ absent compris)."""
    valeurs = collections.defaultdict(lambda: "?")
    for cle, v in details.items():
        if v is None:
            continue
        if cle in TAILLES_SWAP and isinstance(v, (int, float)):
            valeurs[cle] = octets(v)
        elif isinstance(v, (list, tuple, set)):
            valeurs[cle] = ", ".join(affichable(x) for x in v)
        else:
            valeurs[cle] = affichable(v)
    return valeurs


def _message(table, code, details):
    cle = table.get(code)
    if cle is None:
        return affichable(code) or "?"
    return t(cle).format_map(_champs(details))


def message_refus(res):
    """La phrase qui dit pourquoi un plan de system_swap est refusé."""
    return _message(RAISONS_SWAP, res["reason"], res["details"])


def message_alerte(alerte):
    """La phrase d'une mise en garde ({"code": …, …}) d'un plan."""
    return _message(ALERTES_SWAP, alerte["code"], alerte)


def _persistance(pers, active):
    """Comment la zram revient au démarrage, en une phrase."""
    mode = pers["mode"]
    if mode == "nixos":
        return t("NixOS: zramSwap in configuration.nix")
    if mode == "zram-generator":
        fichier = pers["generator"]["main"] or ", ".join(
            pers["generator"]["dropins"]
        )
        return f"zram-generator ({fichier})"
    if mode == "zram-tools":
        return f"zram-tools ({ss.ZRAMSWAP_DEFAULT})"
    if mode == "service":
        return affichable(pers.get("service"))
    if active:
        return t("none: this zram was set up by hand and is lost at reboot")
    return t("none")


def _setters(setters):
    """[{path, value}, …] -> « chemin (valeur), … »."""
    return ", ".join(
        f"{affichable(s['path'])} ({affichable(s['value'])})" for s in setters
    )


def lignes_sysctl(etat):
    """vm.swappiness et vm.page-cluster en lignes : la valeur en marche, le
    fichier qui la fixe au démarrage, les fichiers écrasés, et une mise en
    garde quand une zram attend une swappiness d'au moins 60. [] si etat
    ne porte pas de sysctl."""
    sysctl = etat.get("sysctl")
    if not sysctl:
        return []
    lignes = []
    for cle in ss.CLES_SYSCTL:
        info = sysctl.get(cle) or {}
        valeur = info.get("value")
        if info.get("source"):
            source = t("set by {path}").format(path=affichable(info["source"]))
        else:
            source = t("kernel default, no file sets it")
        lignes.append(
            f"  {cle} : {t('unavailable') if valeur is None else valeur}"
            f" · {source}"
        )
        if info.get("dead"):
            lignes.append(
                f"      {t('Overridden, without effect:')}"
                f" {_setters(info['dead'])}"
            )
        hors = info.get("outside_boot")
        if hors:
            lignes.append(
                "      "
                + t(
                    "{path} sets {value} too: « sysctl --system » applies "
                    "it, the boot does not."
                ).format_map(_champs(hors))
            )
    valeur = ss.swappiness_actuelle(etat)
    if (
        ss.zram_presente(etat)
        and valeur is not None
        and valeur < ss.SWAPPINESS_DEFAUT
    ):
        lignes.append(
            f"  ⚠ {message_alerte({'code': 'low_swappiness', 'value': valeur})}"
        )
    return lignes


def lignes_swap(etat):
    """L'état de la mémoire et de la mémoire d'échange en lignes de texte :
    la RAM, chaque swap actif, la zram et sa persistance, la swappiness,
    l'hibernation, puis la recommandation."""
    absent = t("unavailable")
    mem = etat["memory"]
    lignes = [
        f"── {t('Memory')} ──",
        f"  RAM : {octets(mem['available']) or absent}"
        f" {t('available of')} {octets(mem['total']) or absent}",
        f"  {t('Swap')} : {octets(mem['swap_free']) or absent}"
        f" {t('free of')} {octets(mem['swap_total']) or absent}",
        "",
        f"── {t('Active swaps')} ──",
    ]
    for s in etat["swaps"]:
        lignes.append(
            f"  {affichable(s['path']):<24} {t(TYPES_SWAP[s['type']]):<10}"
            f" {octets(s['size']):>10} {t('used:')} {octets(s['used']):>10}"
            f"  {t('priority')} {s['priority']}"
        )
        if s.get("fs"):
            lignes.append(
                "      "
                + t("on {mountpoint} ({fstype}), {free} free").format_map(
                    _champs(
                        {
                            "mountpoint": s["fs"]["mountpoint"],
                            "fstype": s["fs"]["fstype"],
                            "free": s.get("free"),
                        }
                    )
                )
            )
        if s.get("hibernation"):
            lignes.append(
                f"      ⚠ {t('Hibernation may resume from this swap.')}"
            )
    if not etat["swaps"]:
        lignes.append(f"  {t('No active swap.')}")

    lignes += ["", "── zram ──"]
    for z in etat["zram"]:
        if not z["disksize"]:
            lignes.append(f"  {z['device']} : {t('created, not configured')}")
            continue
        actif = t("in use as swap") if z["active"] else t("not in use")
        lignes.append(
            f"  {z['device']} · {octets(z['disksize'])}"
            f" · {z['algorithm'] or absent} · {actif}"
        )
        if z["orig_data"] is not None:
            ratio = f"{z['ratio']:.1f}" if z["ratio"] else "—"
            lignes.append(
                "      "
                + t(
                    "{stored} stored, compressed to {compressed}, costs "
                    "{ram} of RAM (ratio {ratio})"
                ).format(
                    stored=octets(z["orig_data"]),
                    compressed=octets(z["compr_data"]),
                    ram=octets(z["mem_used"]),
                    ratio=ratio,
                )
            )
    if not etat["zram"]:
        lignes.append(f"  {t('No zram device.')}")
    module = etat.get("zram_module") or {}
    if module.get("state") == "reboot":
        lignes.append(
            "  ⚠ "
            + message_refus(
                {
                    "reason": "zram_reboot_required",
                    "details": {
                        "running": module["running"],
                        "installed": ", ".join(module["installed"]),
                    },
                }
            )
        )
    elif module.get("state") == "missing":
        lignes.append(
            "  ⚠ "
            + message_refus(
                {
                    "reason": "zram_unavailable",
                    "details": {"running": module["running"]},
                }
            )
        )
    pers = etat["persistence"]
    active = any(z["active"] for z in etat["zram"])
    lignes.append(f"  {t('At boot:')} {_persistance(pers, active)}")
    if pers["both"]:
        lignes.append(f"  ⚠ {message_alerte({'code': 'zram_tools_conflict'})}")

    sysctl = lignes_sysctl(etat)
    if sysctl:
        lignes += ["", "── Swappiness ──"] + sysctl

    hib = etat["hibernation"]
    lignes += ["", f"── {t('Hibernation')} ──"]
    if hib["resume"]:
        offset = (
            f" resume_offset={hib['resume_offset']}"
            if hib["resume_offset"] is not None
            else ""
        )
        lignes.append(f"  resume={affichable(hib['resume'])}{offset}")
        lignes.append(
            f"  ⚠ {t('Resizing the swap that holds the hibernation image breaks resuming until resume= and resume_offset= are updated.')}"
        )
    else:
        lignes.append(
            f"  {t('Not configured: no resume= on the kernel command line.')}"
        )

    rec = etat["recommendation"]
    disque = sum(s["size"] for s in ss.cibles_disque(etat))
    lignes += ["", f"── {t('Recommendation')} ──"]
    if rec["swap"]:
        base = (
            t("RAM plus its square root, for hibernation")
            if rec["basis"] == "hibernation"
            else t("from the RAM size, at most 8 GiB")
        )
        lignes.append(
            f"  {t('Disk swap')} : {octets(rec['swap'])} ({base})"
            f" · {t('now')} {octets(disque)}"
        )
        lignes.append(
            f"  zram : {octets(rec['zram'])}"
            f" ({t('half the RAM, at most 8 GiB')})"
        )
    lignes.append(
        "  "
        + t(
            "zram and disk swap coexist: zram gets priority {priority} and "
            "fills first, the disk takes the overflow."
        ).format(priority=ss.PRIORITE_ZRAM)
    )
    croissance = ss.croissance_swap(etat)
    if croissance is not None:
        lignes.append(
            "  "
            + t(
                "The free disk space lets the swap grow by up to {size}."
            ).format(size=octets(croissance))
        )
    return lignes


def lignes_memoire(v):
    """Le verdict de verdict_memoire() en lignes : la RAM installée et ses
    emplacements, la réponse, les réserves, et ce que le swap peut encore
    prendre sur le disque."""
    valeurs = _champs(v)
    lignes = [f"── {t('Adding memory')} ──"]
    lignes.append(f"  RAM : {valeurs['ram']}")
    if v["installed"] is not None:
        lignes.append(
            "  "
            + t(
                "Installed: {installed} in {used_slots} of {slots} slot(s)."
            ).format_map(valeurs)
        )
        details = v["types"] + v["form_factors"]
        if details:
            lignes.append(f"  {', '.join(affichable(d) for d in details)}")
        if v["max_capacity"] is not None:
            lignes.append(
                "  "
                + t(
                    "Maximum Capacity: {max_capacity}, {max_addable} more "
                    "than installed."
                ).format_map(valeurs)
            )
    lignes.append(f"  → {_message(VERDICTS_MEMOIRE, v['verdict'], v)}")
    if v.get("balloon"):
        ballon = t(
            "The virtio_balloon driver is present: the host can change this "
            "VM's RAM while it runs with `virsh setmem <vm> <size> --live`, "
            "up to the <memory> maximum in its definition; raising that "
            "maximum needs the VM shut off."
        )
        lignes.append(f"  {ballon}")
    elif v.get("balloon") is False:
        sans_ballon = t(
            "No virtio_balloon driver: the host changes this VM's RAM only "
            "while it is shut off."
        )
        lignes.append(f"  {sans_ballon}")
    if v["verdict"] == "max" and v["max_capacity"] is None:
        lignes.append(
            f"  {t('The maximum capacity is unknown: larger modules may fit, the board documentation tells.')}"
        )
    if v["verdict"] == "free_slots" and v["max_addable"] is None:
        lignes.append(
            f"  {t('The maximum capacity is unknown: the board documentation tells how much each slot takes.')}"
        )
    if v["partially_soldered"]:
        lignes.append(
            f"  {t('Part of the memory is soldered: only the modules in slots can be replaced.')}"
        )
    if v["max_understated"]:
        lignes.append(
            f"  ⚠ {t('More memory is installed than the Maximum Capacity the firmware reports: that figure is wrong.')}"
        )
    if v["firmware_note"]:
        lignes.append(
            f"  {t('Maximum Capacity comes from the firmware and can be understated: the board documentation has the last word.')}"
        )
    if v["swap_growth"] is not None:
        lignes.append(
            "  "
            + t(
                "The free disk space lets the swap grow by up to {size}."
            ).format(size=octets(v["swap_growth"]))
        )
    return lignes


class SystemMenuMixin:
    def prompt_execute_system(self):
        print(f"🤖 {t('System and disk space!')}")
        choices = [
            {"prompt_description": t("System diagnostic")},
            {"prompt_description": t("Space to reclaim")},
            {
                "prompt_description": t(
                    "Heavy directories next to the repository"
                )
            },
            {"prompt_description": t("System caches (sudo)")},
            {
                "prompt_description": t(
                    "QEMU download cache - size and cleanup"
                )
            },
            {"prompt_description": t("Containers - size and cleanup")},
            {"prompt_description": t("CPU memory per process")},
            {"prompt_description": t("GPU memory per process")},
            {"prompt_description": t("Swap memory")},
            {
                "prompt_description": t(
                    "Performance audit of this machine (read-only)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._system_diagnostic()
            elif status == "2":
                self._system_espace()
            elif status == "3":
                self._system_depots_lourds()
            elif status == "4":
                self._system_caches_sudo()
            elif status == "5":
                self._system_cache_qemu()
            elif status == "6":
                self._system_conteneurs()
            elif status == "7":
                self._system_cpu()
            elif status == "8":
                self._system_gpu()
            elif status == "9":
                self._system_swap()
            elif status == "10":
                # Le même audit que Production › Audit de l'hôte, avec le
                # profil d'hôte `local` : mesuré sur une durée, là où le
                # diagnostic [1] décrit le poste à un instant.
                self._ops_perf_audit()
            else:
                print(t("Command not found !"))

    def _system_diagnostic(self):
        faits = system_diagnostic.collecter(".")
        lignes = lignes_diagnostic(faits)
        print("\n".join(lignes))
        print()
        if not self._is_yes(
            input(t("Save this report in private/diagnostic/? (y/N): "))
        ):
            return
        dossier = os.path.join("private", "diagnostic")
        os.makedirs(dossier, exist_ok=True)
        nom = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".txt"
        chemin = os.path.join(dossier, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lignes) + "\n")
        print(f"  ✓ {t('Report saved:')} {chemin}")

    def _system_cpu(self):
        """Choisir top, htop, btop ou glances, l'installer s'il manque,
        puis le lancer trié par mémoire quand l'outil le permet."""
        outils = system_cpu.etat()
        nix = system_cpu.gestionnaire() == "nix"
        for i, o in enumerate(outils, 1):
            if o["chemin"]:
                note = f"✓ {o['chemin']}"
            elif nix:
                note = f"✗ {t('not installed: runs in a nix-shell')}"
            elif system_cpu.plan_installation(o["nom"]):
                note = f"✗ {t('not installed: can be installed')}"
            else:
                note = f"✗ {t('not installed, unknown package manager')}"
            print(f"  [{i}] {o['nom']:<8} {note}")
        reponse = input(t("Tool number, Enter for none: ")).strip()
        numero = entier(reponse)
        if numero is None or not 1 <= numero <= len(outils):
            return
        outil = outils[numero - 1]
        if outil["chemin"]:
            commande = [outil["chemin"]] + outil["args"]
        elif nix:
            commande = system_cpu.commande_nix(outil["nom"])
        else:
            if not self._system_cpu_installer(outil["nom"]):
                return
            outil = next(
                o for o in system_cpu.etat() if o["nom"] == outil["nom"]
            )
            if not outil["chemin"]:
                print(f"  ⚠ {outil['nom']} {t('is still not in the PATH.')}")
                return
            commande = [outil["chemin"]] + outil["args"]
        print(
            f"  {t('Will execute:')} {shlex.join(commande)}"
            f"  · {t('sort by memory:')} {outil['touche']}"
        )
        try:
            subprocess.run(commande)
        except OSError as e:
            print(f"  ⚠ {e}")
        except KeyboardInterrupt:
            print()

    def _system_cpu_installer(self, nom):
        """Montre les commandes qui installent `nom` et les lance après un
        oui ; sudo y demande son mot de passe dans le terminal. Rend vrai
        si toutes ont réussi."""
        plan = system_cpu.plan_installation(nom)
        if not plan:
            print(f"  ⚠ {nom} : {t('not installed, unknown package manager')}")
            return False
        for commande in plan:
            print(f"  {t('Will execute:')} {shlex.join(commande)}")
        if not self._is_yes(
            input(t("Install {name}? (y/N): ").format(name=nom))
        ):
            return False
        for commande in plan:
            try:
                res = subprocess.run(commande)
            except (OSError, KeyboardInterrupt):
                return False
            if res.returncode != 0:
                print(
                    f"  ⚠ {t('Installation failed:')} {shlex.join(commande)}"
                )
                if commande[1:2] == ["pacman"]:
                    print(
                        f"  {t('The package database may be stale: run sudo pacman -Syu, then try again.')}"
                    )
                return False
        return True

    def _system_gpu(self):
        print(f"  {t('Reading GPU memory…')}")
        faits = system_gpu.collecter()
        self._system_gpu_sudo(faits)
        print("\n".join(lignes_gpu(faits)))
        print()

    def _system_gpu_sudo(self, faits):
        """Propose de relire en root les processus d'autres comptes que
        fdinfo n'a pas pu lire. Sans réponse oui, sans terminal, déjà root
        ou si sudo échoue, `faits` reste la lecture sans root."""
        d = faits["drm"]
        if not d or not d["illisibles"] or os.geteuid() == 0:
            return
        if not sys.stdin.isatty():
            return
        print(
            f"  ⚠ {d['illisibles']}"
            f" {t('processes of other accounts cannot be read without root: their GPU memory is not counted.')}"
        )
        print(
            f"  {t('Will execute:')} sudo python3 -I -c"
            f" <{t('read-only reading of /proc/*/fdinfo')}>"
        )
        if not self._is_yes(
            input(
                t("Read them with sudo? The password is asked here. (y/N): ")
            )
        ):
            return
        lu = system_gpu.drm_sudo()
        if lu is None:
            print(f"  ⚠ {t('sudo failed: showing what reads without root.')}")
            return
        system_gpu.completer(lu["processus"])
        faits["drm"] = lu

    def _system_bases(self, config_path=None):
        """Les bases que PostgreSQL connaît, ou None s'il ne répond pas.
        La connexion vient de `config_path` (config.conf de ce checkout par
        défaut), en lecture seule."""
        try:
            from script.analyse import lib_analyse

            env = lib_analyse.pg_env(config_path=config_path, timeout=10)
            res = subprocess.run(
                [
                    "psql",
                    "-d",
                    "postgres",
                    "-Atc",
                    "SELECT datname FROM pg_database",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError, ImportError):
            return None
        if res.returncode != 0:
            return None
        return set(res.stdout.split())

    def _system_bases_partagees(self, data_dir):
        """Les bases de TOUS les clusters dont les checkouts écrivent dans
        `data_dir`, réunies ; None si l'un d'eux ne répond pas — sans sa
        liste, ses filestores vivants passeraient pour orphelins."""
        try:
            from script.analyse import lib_analyse
        except ImportError:
            return None
        configs = system_cleanup.configs_partageant(
            os.path.realpath("."), data_dir, lib_analyse.read_config
        )
        reunies, vus = set(), set()
        for config_path in configs:
            options = lib_analyse.read_config(config_path)
            cle = tuple(
                str(options.get(k, "")).strip()
                for k in ("db_host", "db_port", "db_user")
            )
            if cle in vus:
                continue
            vus.add(cle)
            bases = self._system_bases(config_path)
            if bases is None:
                return None
            reunies |= bases
        return reunies

    def _system_data_dir(self):
        try:
            from script.analyse import lib_analyse

            data_dir = str(lib_analyse.read_config().get("data_dir", ""))
        except Exception:
            return None
        return (
            data_dir if data_dir.lower() not in ("", "false", "none") else None
        )

    def _system_espace(self):
        print(f"  {t('Searching for space to reclaim…')}")
        data_dir = self._system_data_dir()
        bases = None
        heritees = [v for v in ("PGHOST", "PGPORT") if os.environ.get(v)]
        if not data_dir:
            print(
                f"  {t('No data_dir in config.conf: Odoo filestores are not proposed.')}"
            )
        elif heritees:
            # Un Odoo lancé d'un autre shell, sans ces variables, parle à
            # un autre cluster : ses filestores passeraient pour orphelins.
            print(
                f"  ⚠ {', '.join(heritees)}"
                f" {t('exported: the cluster of each Odoo is uncertain, Odoo filestores are not proposed.')}"
            )
        else:
            bases = self._system_bases_partagees(data_dir)
            if bases is None:
                print(
                    f"  ⚠ {t('A PostgreSQL that serves this data_dir is unreachable: Odoo filestores are not proposed.')}"
                )
            else:
                print(
                    f"  {t('An orphan filestore is one no PostgreSQL of the neighbouring ERPLibre checkouts knows; an Odoo elsewhere sharing this data_dir is not consulted.')}"
                )
        try:
            with open(".erplibre-version", encoding="utf-8") as fh:
                version = fh.read().strip()
        except OSError:
            version = ""
        # Vide, « .venv. » ne nommerait aucun venv, et tous passeraient
        # pour d'une autre version, l'actif compris.
        actif = f".venv.{version}" if version else None
        candidats = system_cleanup.candidats(
            ".",
            data_dir=data_dir,
            bases=bases,
            actif=actif,
            jours=JOURS_INACTIFS,
        )
        if not candidats:
            print(f"  {t('Nothing to reclaim.')}")
            return
        total = sum(c.taille for c in candidats)
        print(f"  {len(candidats)} → {octets(total)}")
        choisis = None
        if sys.stdin.isatty() and sys.stdout.isatty():
            choisis = choisir_au_formulaire(candidats)
        if choisis == "sans-tui" or not (
            sys.stdin.isatty() and sys.stdout.isatty()
        ):
            choisis = choisir_en_ligne(candidats)
        if not choisis:
            print(f"  {t('Nothing selected.')}")
            return
        retenus = [candidats[i] for i in choisis]
        for c in retenus:
            print(f"  - {libelle(c)}")
        prevu = sum(c.taille for c in retenus)
        if not self._is_yes(
            input(f"{t('Delete these items?')} ({octets(prevu)}) (y/N): ")
        ):
            print(f"  {t('Nothing deleted.')}")
            return
        # La liste des bases est RELUE ici : un filestore dont la base est
        # apparue depuis la recherche ne doit pas partir.
        racine = os.path.realpath(".")
        liberes, laisses = system_cleanup.effacer(
            retenus,
            racine,
            system_cleanup.racines_permises(
                racine, os.path.expanduser("~"), "/tmp", data_dir
            ),
            os.getuid(),
            bases=(
                self._system_bases_partagees(data_dir)
                if bases is not None
                else None
            ),
        )
        print(f"  ✓ {t('Freed:')} {octets(liberes)}")
        if laisses:
            print(f"  {t('Left in place:')}")
            for chemin, raison in laisses:
                print(f"    {chemin} — {t(RAISONS.get(raison, raison))}")

    def _system_depots_lourds(self):
        """Ce qui pèse à côté du dépôt, par dépôt puis par sous-répertoire.
        Un rapport : seuls les venvs des autres checkouts se proposent, au
        formulaire de l'espace à récupérer."""
        parent = os.path.dirname(os.path.realpath("."))
        print(f"  {t('Measuring')} {parent}…")
        depots = system_cleanup.depots_lourds(parent)
        if depots is None:
            print(f"  {t('unavailable')}")
            return
        maintenant = time.time()
        for d in depots:
            quand = (
                f"  · {duree(maintenant - d['commit'])}"
                f" {t('since the last commit')}"
                if d["commit"]
                else ""
            )
            marque = "  ERPLibre" if d["erplibre"] else ""
            print(f"\n  {octets(d['taille']):>10}  {d['nom']}{marque}{quand}")
            for nom, taille in d["enfants"]:
                print(f"    {octets(taille):>10}  {nom}")
        print(
            f"\n  {octets(sum(d['taille'] for d in depots))} {t('in total')}"
        )
        print(
            f"  {t('The venvs of the other ERPLibre checkouts are offered, unchecked, in Space to reclaim.')}"
        )

    def _system_caches_sudo(self):
        """Les caches du système : leur poids et la commande, puis sudo
        après confirmation, cache par cache."""
        caches = system_cleanup.caches_systeme()
        if not caches:
            print(f"  {t('Nothing to reclaim.')}")
            return
        for i, c in enumerate(caches, 1):
            print(
                f"  [{i}] {octets(c['taille']):>10}  {c['nom']:<8}"
                f" {c['chemin']}"
            )
            print(f"      {t('Will execute:')} {shlex.join(c['commande'])}")
        reponse = input(
            t("Numbers to run (e.g. 1,2), Enter for none: ")
        ).strip()
        numeros = [entier(m) for m in reponse.replace(" ", "").split(",")]
        choisis = [
            caches[n - 1]
            for n in numeros
            if n is not None and 1 <= n <= len(caches)
        ]
        if not choisis:
            print(f"  {t('Nothing selected.')}")
            return
        for c in choisis:
            print(f"  - {shlex.join(c['commande'])}")
        if not self._is_yes(input(t("Run these commands with sudo? (y/N): "))):
            print(f"  {t('Nothing deleted.')}")
            return
        for c in choisis:
            statut = self.execute.exec_command_live(
                shlex.join(c["commande"]), source_erplibre=False
            )
            apres, _ = system_cleanup.mesurer(c["chemin"])
            # Un mot de passe refusé, un Ctrl-C ou un verrou du gestionnaire
            # de paquets rendent un statut non nul : ne pas annoncer ✓.
            marque = "⚠" if statut else "✓"
            print(
                f"  {marque} {c['nom']} : {octets(c['taille'])}"
                f" → {octets(apres)}"
            )

    def _system_cache_qemu(self):
        """Le cache de téléchargement des VM : son état et son poids, puis
        le menu d'âge et de nettoyage du cache lui-même."""
        from script.todo import qemu_cache_menu

        if not os.path.isdir(qemu_cache_menu.CACHE_DIR):
            print(f"  {t('Not installed:')} {qemu_cache_menu.CACHE_DIR}")
            return
        print(f"  {self._cache_etat_court()}")
        print(
            f"  {self._cache_poids(qemu_cache_menu.CACHE_DIR):>8}  "
            f"{qemu_cache_menu.CACHE_DIR}"
        )
        print(
            f"  {self._cache_poids(qemu_cache_menu.CACHE_MIROIR_GIT):>8}  "
            f"{qemu_cache_menu.CACHE_MIROIR_GIT}"
        )
        self._cache_age()

    def _system_conteneurs(self):
        """Le poids des images, conteneurs et volumes, puis les nettoyages
        du menu Conteneurs."""
        from script.todo import container_runtime

        fiche = self._container_fiche()
        if not fiche:
            return
        cmd = container_runtime.commande(fiche, ["system", "df"])
        self.execute.exec_command_live(shlex.join(cmd), source_erplibre=False)
        choices = [
            {
                "prompt_description": t(
                    "Remove unused images, containers and volumes"
                )
            },
            {
                "prompt_description": t(
                    "By workspace - a compose project and what it holds"
                )
            },
            {"prompt_description": t("Images one by one")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._container_nettoyage()
            elif status == "2":
                self._container_nettoyer_projets()
            elif status == "3":
                self._container_nettoyer_images()
            else:
                print(t("Command not found !"))

    def _system_swap(self):
        """Le sous-menu de la mémoire d'échange : l'état, le swap sur
        disque, la zram, l'ajout de RAM et la swappiness."""
        choices = [
            {"prompt_description": t("State of memory and swap")},
            {"prompt_description": t("Grow swap")},
            {"prompt_description": t("Shrink swap")},
            {"prompt_description": t("zram - enable or resize")},
            {"prompt_description": t("zram - disable")},
            {"prompt_description": t("Can memory be added?")},
            {"prompt_description": t("Swappiness")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._system_swap_etat()
            elif status == "2":
                self._system_swap_redimensionner("grow")
            elif status == "3":
                self._system_swap_redimensionner("shrink")
            elif status == "4":
                self._system_swap_zram()
            elif status == "5":
                self._system_swap_zram_desactiver()
            elif status == "6":
                self._system_swap_memoire()
            elif status == "7":
                self._system_swap_swappiness()
            else:
                print(t("Command not found !"))

    def _system_swap_etat(self, etat=None):
        print("\n".join(lignes_swap(etat or ss.etat())))
        print()

    def _system_swap_choisir(self, cibles):
        """Le swap sur disque à modifier : le seul s'il n'y en a qu'un,
        sinon celui dont on tape le numéro ; None pour annuler."""
        if len(cibles) == 1:
            return cibles[0]
        for i, s in enumerate(cibles, 1):
            print(
                f"  [{i}] {affichable(s['path']):<24}"
                f" {t(TYPES_SWAP[s['type']]):<10} {octets(s['size']):>10}"
                f"  {t('priority')} {s['priority']}"
            )
        reponse = input(t("Swap number, Enter to cancel: ")).strip()
        numero = entier(reponse)
        if numero is not None and 1 <= numero <= len(cibles):
            return cibles[numero - 1]
        return None

    def _system_swap_taille(self, defaut=None):
        """La taille tapée, en octets ; `defaut` sur Entrée, None pour une
        saisie vide sans défaut ou qui n'est pas une taille."""
        if defaut:
            invite = t(
                "New size, as 16G or 16 GiB, 512M or 512 MiB (a bare number is MiB), Enter for {size}: "
            ).format(size=octets(defaut))
        else:
            invite = t(
                "New size, as 16G or 16 GiB, 512M or 512 MiB (a bare number is MiB), Enter to cancel: "
            )
        reponse = input(invite).strip()
        if not reponse:
            return defaut
        taille = ss.parse_taille(reponse)
        if taille is None:
            print(f"  ⚠ {t('Not a size:')} {affichable(reponse)}")
        return taille

    def _system_swap_redimensionner(self, sens):
        """Agrandir (sens « grow ») ou réduire (« shrink ») un fichier
        d'échange actif. Sans swap sur disque, agrandir crée un fichier ;
        une partition ne se redimensionne pas, et agrandir propose alors un
        fichier en plus."""
        etat = ss.etat()
        refus = ss.refus_conteneur(etat)
        if refus:
            print(f"  ⚠ {message_refus(refus)}")
            return
        cibles = ss.cibles_disque(etat)
        if not cibles:
            if sens == "grow":
                print(
                    f"  {t('No disk swap is active: a swapfile is created.')}"
                )
                self._system_swap_creer(etat)
            else:
                print(f"  {t('No disk swap is active: nothing to shrink.')}")
            return
        cible = self._system_swap_choisir(cibles)
        if cible is None:
            print(f"  {t('Nothing selected.')}")
            return
        if cible["type"] != "file":
            res = ss.plan_redimensionner(
                etat, cible["path"], cible["size"], sens
            )
            print(f"  ⚠ {message_refus(res)}")
            if res["reason"] == "partition" and self._is_yes(
                input(t("Create a swapfile instead? (y/N): "))
            ):
                self._system_swap_creer(etat)
            return
        print(
            "  "
            + t("Current size: {size}, {used} in use.").format(
                size=octets(cible["size"]), used=octets(cible["used"])
            )
        )
        if sens == "grow" and cible.get("max_size"):
            print(
                "  "
                + t("Largest size the free space allows: {size}.").format(
                    size=octets(cible["max_size"])
                )
            )
        # /proc/swaps compte un fichier sans sa page d'en-tête : la
        # comparaison se fait en Mio arrondis, comme celle du plan, pour ne
        # pas proposer la taille qu'il a déjà.
        rec = etat["recommendation"]["swap"]
        defaut = None
        if rec and (
            (sens == "grow" and ss.mio(rec) > ss.mio(cible["size"]))
            or (
                sens == "shrink"
                and rec >= ss.PLANCHER_SWAP
                and ss.mio(rec) < ss.mio(cible["size"])
            )
        ):
            defaut = rec
            print("  " + t("Recommended: {size}.").format(size=octets(rec)))
        taille = self._system_swap_taille(defaut)
        if taille is None:
            return
        self._system_swap_appliquer(
            ss.plan_redimensionner(etat, cible["path"], taille, sens)
        )

    def _system_swap_creer(self, etat):
        """Créer un fichier d'échange : son chemin (le défaut tient compte
        de btrfs), sa taille (la recommandation par défaut), puis le
        plan."""
        defaut = ss.chemin_par_defaut(etat)
        if defaut["reason"] == "btrfs_subvolume":
            print(
                f"  {t('On btrfs, the swapfile goes in a subvolume of its own: a swapfile blocks the snapshots of the subvolume that holds it.')}"
            )
        chemin = (
            input(
                t("Swapfile path, Enter for {path}: ").format(
                    path=defaut["path"]
                )
            ).strip()
            or defaut["path"]
        )
        taille = self._system_swap_taille(etat["recommendation"]["swap"])
        if taille is None:
            return
        self._system_swap_appliquer(ss.plan_creer(etat, chemin, taille))

    def _system_swap_zram(self):
        """Activer la zram ou changer sa taille, la recommandation par
        défaut. Les fichiers de configuration s'écrivent dans un
        répertoire temporaire de l'utilisateur, que « sudo install »
        recopie, puis qui disparaît."""
        etat = ss.etat()
        refus = ss.refus_zram(etat)
        if refus:
            print(f"  ⚠ {message_refus(refus)}")
            return
        actives = [z for z in etat["zram"] if z["active"]]
        for z in actives:
            print(
                f"  {z['device']} · {octets(z['disksize'])}"
                f" · {z['algorithm'] or t('unavailable')}"
            )
        if not actives:
            print(f"  {t('No zram is active.')}")
        taille = self._system_swap_taille(etat["recommendation"]["zram"])
        if taille is None:
            return
        with tempfile.TemporaryDirectory(prefix="erplibre_zram_") as dossier:
            res = ss.plan_zram(etat, taille, dossier)
            if res["ok"] and res["details"].get("install"):
                print(
                    f"  {t('zram-generator is not installed: its package is installed first.')}"
                )
            self._system_swap_appliquer(res)

    def _system_swap_zram_desactiver(self):
        etat = ss.etat()
        with tempfile.TemporaryDirectory(prefix="erplibre_zram_") as dossier:
            self._system_swap_appliquer(ss.plan_zram_desactiver(etat, dossier))

    def _system_swap_appliquer(self, res):
        """Le protocole commun des plans de system_swap : le refus et sa
        raison, ou l'extrait NixOS, ou bien les mises en garde, le contenu
        des fichiers et chaque commande ; puis, sur un oui, les fichiers
        écrits et les commandes lancées une à une, arrêtées à la première
        qui échoue, et l'état relu. Rend vrai si tout a réussi."""
        if not res["ok"]:
            print(f"  ⚠ {message_refus(res)}")
            return False
        details = res["details"]
        if "old" in details and "new" in details:
            print(
                "  "
                + t("Size: {old} → {new}").format(
                    old=octets(details["old"]), new=octets(details["new"])
                )
            )
        for cle, (avant, apres) in details.get("changes", {}).items():
            print(f"  {cle} : {'?' if avant is None else avant} → {apres}")
        for alerte in res["warnings"]:
            print(f"  ⚠ {message_alerte(alerte)}")
        if res["nix"]:
            print(
                f"  {t('NixOS is configured declaratively: add this to /etc/nixos/configuration.nix, then rebuild.')}"
            )
            for ligne in res["nix"].splitlines():
                print(f"    {ligne}")
            return False
        if not res["plan"]:
            print(f"  {t('Nothing to do.')}")
            return False
        if details.get("fstab") == "added":
            print(
                "  "
                + t(
                    "/etc/fstab gets the line « {line} », after a copy to {backup}."
                ).format_map(_champs(details))
            )
        for edite in details.get("edited") or []:
            print(
                "  "
                + t(
                    "{path} is edited in place, after a copy to {backup}."
                ).format_map(_champs(edite))
            )
        fichiers = dict(res["files"])
        if details.get("created"):
            fichiers[details["created"]] = details["content"]
        for chemin, contenu in fichiers.items():
            print(f"  {t('Content to write to')} {chemin} :")
            for ligne in contenu.splitlines() or [""]:
                print(f"    │ {ligne}")
        for cmd in res["plan"]:
            print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(
            input(
                t(
                    "Run these commands? sudo asks its password in the terminal. (y/N): "
                )
            )
        ):
            print(f"  {t('Nothing changed.')}")
            return False
        for chemin, contenu in res["files"].items():
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(contenu)
        reussi = True
        for i, cmd in enumerate(res["plan"]):
            # Un statut non nul (mot de passe refusé, commande en échec) ou
            # un Ctrl-C, qui lève KeyboardInterrupt ici, arrêtent le plan :
            # les commandes suivantes supposent celle-ci faite.
            try:
                statut = self.execute.exec_command_live(
                    shlex.join(cmd), source_erplibre=False
                )
                message = t("Command failed:")
            except KeyboardInterrupt:
                statut = 1
                message = t("Interrupted at:")
            if statut:
                print(f"\n  ⚠ {message} {shlex.join(cmd)}")
                suite = res["plan"][i + 1 :]
                if suite:
                    print(f"  {t('Not run:')}")
                    for reste in suite:
                        print(f"    {shlex.join(reste)}")
                self._system_swap_reprise(res, i)
                reussi = False
                break
        if reussi:
            print(f"  ✓ {t('Done.')}")
        print()
        # btrfs ne publie l'espace d'un fichier créé qu'à la validation de
        # sa transaction, 30 secondes au plus par défaut : sans sync, l'état
        # relu montrerait l'espace libre d'avant la création.
        os.sync()
        self._system_swap_etat()
        return reussi

    def _system_swap_reprise(self, res, echec):
        """Après l'échec de l'étape `echec`, les commandes qui
        reconstruisent le swap quand le plan en porte (details
        recovery_from) et que l'échec suit son extinction."""
        depuis = res["details"].get("recovery_from")
        if depuis is None or echec < depuis:
            return
        print(
            "  "
            + t(
                "{path} is no longer an active swap, and its file may be "
                "missing or incomplete. To rebuild it, run:"
            ).format_map(_champs(res["details"]))
        )
        for cmd in res["plan"][depuis:]:
            print(f"    {shlex.join(cmd)}")

    def _system_swap_memoire(self):
        """Peut-on ajouter de la RAM ? Dans une VM, l'hyperviseur décide ;
        sur du matériel, dmidecode lit les emplacements, avec sudo après
        confirmation, installé d'abord s'il manque."""
        etat = ss.etat()
        dmi = None
        if not etat["virtualization"]:
            dmi = self._system_swap_dmidecode(etat)
        print("\n".join(lignes_memoire(ss.verdict_memoire(etat, dmi))))
        print()

    def _system_swap_dmidecode(self, etat):
        """La sortie analysée de « dmidecode -t memory », ou None si
        dmidecode manque sans pouvoir s'installer, si l'on refuse, ou s'il
        échoue. sudo demande le mot de passe sur le terminal : seule la
        sortie standard est capturée."""
        plan = ss.plan_installer_dmidecode(etat)
        if plan is None:
            print(
                f"  ⚠ dmidecode : {t('not installed, unknown package manager')}"
            )
            return None
        if plan:
            for cmd in plan:
                print(f"  {t('Will execute:')} {shlex.join(cmd)}")
            if not self._is_yes(
                input(t("Install {name}? (y/N): ").format(name="dmidecode"))
            ):
                return None
            for cmd in plan:
                if self.execute.exec_command_live(
                    shlex.join(cmd), source_erplibre=False
                ):
                    print(f"  ⚠ {t('Installation failed:')} {shlex.join(cmd)}")
                    return None
        cmd = ss.commande_dmidecode(etat.get("manager"))
        print(f"  {t('Reading the memory slots needs root (dmidecode).')}")
        print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(
            input(
                t("Read them with sudo? The password is asked here. (y/N): ")
            )
        ):
            return None
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
        except (OSError, KeyboardInterrupt):
            return None
        if res.returncode != 0:
            print(f"  ⚠ {t('dmidecode failed.')}")
            return None
        return ss.analyser_dmidecode(res.stdout)

    def _system_swap_swappiness(self):
        """vm.swappiness : la valeur en marche, le fichier qui la fixe et
        ceux qu'il écrase, la valeur conseillée et sa raison ; puis la
        valeur tapée (Entrée prend la conseillée), vm.page-cluster 0 en plus
        quand une zram est là, et le plan de plan_swappiness()."""
        etat = ss.etat()
        refus = ss.refus_conteneur(etat)
        if refus:
            print(f"  ⚠ {message_refus(refus)}")
            return
        for ligne in lignes_sysctl(etat):
            print(ligne)
        rec = ss.recommandation_swappiness(etat)
        print(
            "  "
            + t("Recommended: {key} = {value}.").format(
                key=ss.SWAPPINESS, value=rec["swappiness"]
            )
        )
        print(f"  {_message(RAISONS_SWAPPINESS, rec['reason'], {})}")
        limite = ss.swappiness_max(etat.get("kernel"))
        reponse = input(
            t("{key}, 0 to {limit}, Enter for {value}: ").format(
                key=ss.SWAPPINESS, limit=limite, value=rec["swappiness"]
            )
        ).strip()
        valeur = entier(reponse) if reponse else rec["swappiness"]
        if valeur is None:
            print(f"  ⚠ {t('Not a number:')} {affichable(reponse)}")
            return
        page_cluster = None
        if rec["page_cluster"] is not None and self._is_yes(
            input(
                t("Also set {key} to {value}? (y/N): ").format(
                    key=ss.PAGE_CLUSTER, value=rec["page_cluster"]
                )
            )
        ):
            page_cluster = rec["page_cluster"]
        self._system_swap_appliquer(
            ss.plan_swappiness(etat, valeur, page_cluster)
        )
