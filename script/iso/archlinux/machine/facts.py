#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les faits du matériel dont machine_profile.resolve() tire chaque
« auto » : micrologiciel, processeur, mémoire, disques, cartes
graphiques, châssis, batterie, Wi-Fi.

Deux moitiés. snapshot() est la seule à toucher la machine : elle lit des
fichiers sous `root` et lance des commandes par `run`, et rend le texte
brut, rangé par source. facts_from() est pure : elle analyse ce brut et
rend les faits normalisés. Un test donne à snapshot() un faux /sys
construit dans un dossier temporaire et un `run` qui rend un JSON
inventé, ou donne directement son brut à facts_from().

Bibliothèque standard seulement, et aucun import de script.todo : ce
fichier est copié dans le live, à côté de machine_profile. Rien ici ne
demande root, sauf nvme id-ns ; sans root il échoue, et le disque n'a
alors pas de faits NVMe.

Aucun numéro de série n'est lu : ni lsblk SERIAL, ni
/sys/class/dmi/id/product_serial. Les faits restent sur la machine.
"""

import glob
import json
import os
import re
import subprocess

LSBLK_COLUMNS = (
    "NAME,PATH,TYPE,TRAN,RM,RO,ROTA,SIZE,LOG-SEC,PHY-SEC,DISC-GRAN,"
    "MODEL,LABEL,UUID,MOUNTPOINTS"
)
LSBLK_COMMAND = ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS]
LSPCI_COMMAND = ["lspci", "-nn", "-mm"]

# Le live archiso monte son support ici ; un disque qui porte ce montage,
# à quelque profondeur que ce soit, est le support de démarrage.
BOOT_MOUNT = "/run/archiso/bootmnt"

# Les paramètres du noyau qu'archiso pose : leur présence dit que la
# machine tourne sur un live, qui a donc un support de démarrage à
# reconnaître parmi les disques.
ARCHISO_PARAMS = ("archisobasedir", "archisolabel", "archisosearchuuid")

# Les types de châssis SMBIOS d'un portable : Portable, Laptop, Notebook,
# Sub Notebook, Tablet, Convertible, Detachable.
PORTABLE_CHASSIS = frozenset({8, 9, 10, 14, 30, 31, 32})

PCI_VENDORS = {"10de": "nvidia", "1002": "amd", "8086": "intel"}

TIMEOUT = 30


# Lecture (impure)


def _read(root, *parts):
    """Le texte du fichier root/parts, sans espaces de bord ; None s'il
    manque ou ne se lit pas."""
    try:
        with open(
            os.path.join(root, *parts), encoding="utf-8", errors="replace"
        ) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _run(run, argv):
    """La sortie standard de `argv`, ou None si la commande manque, dépasse
    TIMEOUT ou sort sur un code non nul."""
    try:
        res = run(
            argv, capture_output=True, text=True, check=False, timeout=TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def _first_cpu(text):
    """Le premier bloc de /proc/cpuinfo : les autres le répètent par
    cœur."""
    if text is None:
        return None
    return text.split("\n\n", 1)[0]


def _pci_sysfs(root):
    devices = []
    for chemin in sorted(
        glob.glob(os.path.join(root, "sys", "bus", "pci", "devices", "*"))
    ):
        devices.append(
            {
                "slot": os.path.basename(chemin),
                "vendor": _read(chemin, "vendor"),
                "device": _read(chemin, "device"),
                "class": _read(chemin, "class"),
                "boot_vga": _read(chemin, "boot_vga"),
            }
        )
    return devices


def _power_supplies(root):
    return [
        {
            "name": os.path.basename(chemin),
            "type": _read(chemin, "type"),
            "scope": _read(chemin, "scope"),
        }
        for chemin in sorted(
            glob.glob(os.path.join(root, "sys", "class", "power_supply", "*"))
        )
    ]


def _wireless(root):
    return [
        os.path.basename(chemin)
        for chemin in sorted(
            glob.glob(os.path.join(root, "sys", "class", "net", "*"))
        )
        if os.path.exists(os.path.join(chemin, "wireless"))
        or os.path.exists(os.path.join(chemin, "phy80211"))
    ]


def _blockdevices(lsblk_text):
    """Les nœuds de premier niveau du JSON de lsblk, seulement ceux qui
    sont des objets. Un texte illisible, ou un JSON qui n'a pas la forme
    {"blockdevices": [...]}, donne une liste vide."""
    try:
        donnees = json.loads(lsblk_text or "")
    except ValueError:
        return []
    if not isinstance(donnees, dict):
        return []
    noeuds = donnees.get("blockdevices")
    if not isinstance(noeuds, list):
        return []
    return [n for n in noeuds if isinstance(n, dict)]


def _nvme_paths(lsblk_text):
    return [
        n.get("path") or "/dev/" + str(n.get("name"))
        for n in _blockdevices(lsblk_text)
        if n.get("type") == "disk"
        and str(n.get("name", "")).startswith("nvme")
    ]


def snapshot(root="/", run=subprocess.run):
    """Le brut de la machine, rangé par source : textes des fichiers de
    /sys et /proc sous `root`, sorties de lsblk, de nvme id-ns (par espace
    de noms NVMe) et de lspci (seulement si /sys ne liste aucun
    périphérique PCI). Une source absente vaut None ou une liste vide."""
    lsblk = _run(run, LSBLK_COMMAND)
    nvme = {}
    for chemin in _nvme_paths(lsblk):
        sortie = _run(run, ["nvme", "id-ns", "-o", "json", chemin])
        if sortie is not None:
            nvme[chemin] = sortie
    pci = _pci_sysfs(root)
    efi = os.path.join(root, "sys", "firmware", "efi")
    return {
        "efi": os.path.isdir(efi),
        "fw_platform_size": _read(efi, "fw_platform_size"),
        "cpuinfo": _first_cpu(_read(root, "proc", "cpuinfo")),
        "meminfo": _read(root, "proc", "meminfo"),
        "cmdline": _read(root, "proc", "cmdline"),
        "lsblk": lsblk,
        "nvme": nvme,
        "pci": pci,
        "lspci": None if pci else _run(run, LSPCI_COMMAND),
        "power_supply": _power_supplies(root),
        "chassis_type": _read(
            root, "sys", "class", "dmi", "id", "chassis_type"
        ),
        "wireless": _wireless(root),
    }


# Analyse (pure)


def _bool(valeur):
    if isinstance(valeur, str):
        return valeur.strip().lower() in ("1", "true", "yes")
    return bool(valeur)


def _int(valeur):
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur
    if isinstance(valeur, str) and valeur.strip().isdigit():
        return int(valeur.strip())
    return None


def _cpuinfo_field(texte, nom):
    for ligne in (texte or "").splitlines():
        cle, _, valeur = ligne.partition(":")
        if cle.strip() == nom:
            return valeur.strip()
    return None


def cpu_from(cpuinfo):
    """{"vendor": "amd" | "intel" | None, "hypervisor": bool} depuis le
    premier bloc de /proc/cpuinfo : vendor_id, et le drapeau hypervisor
    qu'un processeur virtuel annonce."""
    fabricant = {"AuthenticAMD": "amd", "GenuineIntel": "intel"}.get(
        _cpuinfo_field(cpuinfo, "vendor_id")
    )
    drapeaux = (_cpuinfo_field(cpuinfo, "flags") or "").split()
    return {"vendor": fabricant, "hypervisor": "hypervisor" in drapeaux}


def ram_mib_from(meminfo):
    """MemTotal de /proc/meminfo en MiB (le noyau l'écrit en kB, soit
    KiB) ; 0 si absent."""
    m = re.search(r"^MemTotal:\s+(\d+)\s*kB", meminfo or "", re.M)
    return int(m.group(1)) // 1024 if m else 0


def cmdline_params(cmdline):
    """Les paramètres clé=valeur de /proc/cmdline."""
    params = {}
    for morceau in (cmdline or "").split():
        cle, egal, valeur = morceau.partition("=")
        if egal:
            params[cle] = valeur
    return params


def nvme_from(texte):
    """{"current": indice, "formats": [{"id", "ds", "rp", "ms"}]} depuis
    la sortie JSON de nvme id-ns, ou None. ds est le log2 de la taille de
    secteur (9 = 512 o, 12 = 4 KiB), rp la performance relative (0 est la
    meilleure) ; les 4 bits bas de flbas donnent le format en service."""
    try:
        donnees = json.loads(texte or "")
    except ValueError:
        return None
    if not isinstance(donnees, dict):
        return None
    formats = [
        {
            "id": i,
            "ds": _int(f.get("ds")),
            "rp": _int(f.get("rp")),
            "ms": _int(f.get("ms")) or 0,
        }
        for i, f in enumerate(donnees.get("lbafs") or [])
        if isinstance(f, dict)
    ]
    flbas = _int(donnees.get("flbas"))
    return {
        "current": flbas & 0xF if flbas is not None else None,
        "formats": formats,
    }


def _descendants(noeud):
    enfants = noeud.get("children")
    for enfant in enfants if isinstance(enfants, list) else []:
        if not isinstance(enfant, dict):
            continue
        yield enfant
        yield from _descendants(enfant)


def _boot_medium(noeud, params):
    """Vrai si le disque `noeud` porte le support du live : son montage,
    l'étiquette archisolabel ou l'UUID archisosearchuuid de la ligne de
    commande du noyau, sur lui-même (image hybride) ou une partition."""
    etiquette = params.get("archisolabel")
    uuid = params.get("archisosearchuuid")
    for n in [noeud, *_descendants(noeud)]:
        if any(
            m == BOOT_MOUNT or str(m).startswith(BOOT_MOUNT + "/")
            for m in n.get("mountpoints") or [n.get("mountpoint")]
            if m
        ):
            return True
        if etiquette and n.get("label") == etiquette:
            return True
        if uuid and n.get("uuid") == uuid:
            return True
    return False


def disks_from(lsblk_text, nvme_texts=None, cmdline=None):
    """Les disques du JSON de lsblk : {"name", "path", "size",
    "removable", "ro", "rotational", "tran", "log_sec", "phy_sec",
    "disc_gran", "model", "boot_medium", "nvme"}. zram et les nœuds qui ne
    sont pas de type « disk » sont écartés."""
    params = cmdline_params(cmdline)
    nvme_texts = nvme_texts or {}
    disques = []
    for n in _blockdevices(lsblk_text):
        nom = str(n.get("name") or "")
        if n.get("type") != "disk" or nom.startswith("zram"):
            continue
        chemin = n.get("path") or "/dev/" + nom
        modele = n.get("model")
        disques.append(
            {
                "name": nom,
                "path": chemin,
                "size": _int(n.get("size")) or 0,
                "removable": _bool(n.get("rm")),
                "ro": _bool(n.get("ro")),
                "rotational": _bool(n.get("rota")),
                "tran": n.get("tran"),
                "log_sec": _int(n.get("log-sec")),
                "phy_sec": _int(n.get("phy-sec")),
                "disc_gran": _int(n.get("disc-gran")) or 0,
                "model": modele.strip() if isinstance(modele, str) else None,
                "boot_medium": _boot_medium(n, params),
                "nvme": nvme_from(nvme_texts.get(chemin))
                if chemin in nvme_texts
                else None,
            }
        )
    return disques


def _hex(valeur):
    """« 0x10de » ou « 10de » → « 10de » ; None reste None."""
    if not valeur:
        return None
    valeur = str(valeur).strip().lower()
    return valeur[2:] if valeur.startswith("0x") else valeur


def gpus_from_sysfs(devices):
    """Les cartes graphiques (classe PCI 03xx) des fiches sysfs."""
    cartes = []
    for d in devices or []:
        classe = _hex(d.get("class")) or ""
        if not classe.startswith("03"):
            continue
        fournisseur = _hex(d.get("vendor"))
        cartes.append(
            {
                "vendor": PCI_VENDORS.get(fournisseur, "other"),
                "vendor_id": fournisseur,
                "device_id": _hex(d.get("device")),
                "class": classe[:4],
                "boot_vga": _bool(d.get("boot_vga")),
            }
        )
    return cartes


LSPCI_RE = re.compile(
    r'^(?P<slot>\S+)\s+"[^"]*\[(?P<class>[0-9a-fA-F]{4})\]"\s+'
    r'"[^"]*\[(?P<vendor>[0-9a-fA-F]{4})\]"\s+'
    r'"[^"]*\[(?P<device>[0-9a-fA-F]{4})\]"'
)


def gpus_from_lspci(texte):
    """Les cartes graphiques d'une sortie « lspci -nn -mm », le repli
    quand /sys ne liste pas le bus PCI."""
    devices = []
    for ligne in (texte or "").splitlines():
        m = LSPCI_RE.match(ligne.strip())
        if m:
            devices.append(
                {
                    "vendor": m.group("vendor"),
                    "device": m.group("device"),
                    "class": m.group("class"),
                    "boot_vga": None,
                }
            )
    return gpus_from_sysfs(devices)


def battery_from(supplies):
    """Vrai si une batterie alimente le système : type Battery dont la
    portée n'est pas Device (Device est la pile d'une souris ou d'un
    casque)."""
    return any(
        (s.get("type") or "") == "Battery"
        and (s.get("scope") or "System") != "Device"
        for s in supplies or []
    )


def boot_medium_unknown(cmdline, disques):
    """Vrai sur un live archiso (un paramètre ARCHISO_PARAMS sur la ligne
    du noyau) dont aucun disque n'est reconnu comme support de démarrage.
    Les fichiers de l'ISO copiés sur une partition FAT32 en donnent le
    cas : archiso trouve la partition par son fichier « .uuid » et non
    par son UUID, et copytoram démonte BOOT_MOUNT ; ce disque passerait
    alors pour un disque fixe que rien n'empêche d'effacer."""
    params = cmdline_params(cmdline)
    live = any(p in params for p in ARCHISO_PARAMS)
    return live and not any(d.get("boot_medium") for d in disques)


def facts_from(raw):
    """Les faits normalisés d'un brut de snapshot() :

    firmware {"mode": "uefi" | "bios", "bits": 64 | 32 | None},
    cpu {"vendor", "hypervisor"}, virtual, ram_mib, disks (voir
    disks_from), boot_medium_unknown (voir boot_medium_unknown), gpus
    (voir gpus_from_sysfs), chassis_type, battery, laptop (châssis
    portable ou batterie), wifi.
    """
    raw = raw or {}
    uefi = bool(raw.get("efi"))
    cpu = cpu_from(raw.get("cpuinfo"))
    gpus = gpus_from_sysfs(raw.get("pci"))
    if not gpus and raw.get("lspci"):
        gpus = gpus_from_lspci(raw["lspci"])
    chassis = _int(raw.get("chassis_type"))
    batterie = battery_from(raw.get("power_supply"))
    disques = disks_from(raw.get("lsblk"), raw.get("nvme"), raw.get("cmdline"))
    return {
        "firmware": {
            "mode": "uefi" if uefi else "bios",
            "bits": _int(raw.get("fw_platform_size")) if uefi else None,
        },
        "cpu": cpu,
        "virtual": cpu["hypervisor"],
        "ram_mib": ram_mib_from(raw.get("meminfo")),
        "disks": disques,
        "boot_medium_unknown": boot_medium_unknown(
            raw.get("cmdline"), disques
        ),
        "gpus": gpus,
        "chassis_type": chassis,
        "battery": batterie,
        "laptop": chassis in PORTABLE_CHASSIS or batterie,
        "wifi": bool(raw.get("wireless")),
    }
