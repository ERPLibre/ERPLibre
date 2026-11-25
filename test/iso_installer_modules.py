# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les modules du cœur de l'installateur de l'ISO, chargés comme le
lanceur erplibre-installer les charge dans le live : SHARE_DIR et
machine/ en tête de sys.path, sans cache Python (tout ce qui est écrit
dans la surcouche part dans l'ISO).

Les fixtures sont INVENTÉES : modèles, tailles et identifiants n'existent
sur aucune machine.
"""

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARCHLINUX = REPO / "script" / "iso" / "archlinux"
MACHINE_DIR = ARCHLINUX / "machine"
PROFILES_DIR = MACHINE_DIR / "profiles"
AIROOTFS = ARCHLINUX / "profile" / "airootfs"
SHARE_DIR = AIROOTFS / "usr" / "local" / "share" / "erplibre-install"
CONFIG_TOOL = AIROOTFS / "usr" / "local" / "bin" / "erplibre-install-config"

GIB = 1024**3


def load():
    """(machine_profile, facts, erplibre_disk, erplibre_archinstall,
    erplibre_plugin, erplibre_installer)."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for chemin in (str(MACHINE_DIR), str(SHARE_DIR)):
            if chemin not in sys.path:
                sys.path.insert(0, chemin)
        return tuple(
            importlib.import_module(nom)
            for nom in (
                "machine_profile",
                "facts",
                "erplibre_disk",
                "erplibre_archinstall",
                "erplibre_plugin",
                "erplibre_installer",
            )
        )
    finally:
        sys.dont_write_bytecode = saved


def disk(name, size_gib, **fields):
    base = {
        "name": name,
        "path": f"/dev/{name}",
        "size": size_gib * GIB,
        "removable": False,
        "ro": False,
        "rotational": False,
        "tran": "nvme" if name.startswith("nvme") else "sata",
        "log_sec": 512,
        "phy_sec": 512,
        "disc_gran": 512,
        "model": "Disque fictif 9000",
        "boot_medium": False,
        "nvme": None,
    }
    base.update(fields)
    return base


def usb_key():
    return disk(
        "sdz",
        32,
        removable=True,
        tran="usb",
        boot_medium=True,
        model="Clé fictive",
    )


def uefi_laptop(**extra):
    """Portable UEFI 64 bits, AMD, NVMe en 512 o qui propose un format
    4 KiB, la clé de démarrage branchée à côté."""
    facts = {
        "firmware": {"mode": "uefi", "bits": 64},
        "cpu": {"vendor": "amd", "hypervisor": False},
        "virtual": False,
        "ram_mib": 15800,
        "disks": [
            disk(
                "nvme0n1",
                500,
                nvme={
                    "current": 0,
                    "formats": [
                        {"id": 0, "ds": 9, "rp": 2, "ms": 0},
                        {"id": 1, "ds": 12, "rp": 0, "ms": 0},
                    ],
                },
            ),
            usb_key(),
        ],
        "gpus": [{"vendor": "amd"}],
        "laptop": True,
        "battery": True,
        "wifi": True,
    }
    facts.update(extra)
    return facts


def bios_desktop():
    """Poste BIOS Intel à disque SATA rotatif."""
    return {
        "firmware": {"mode": "bios", "bits": None},
        "cpu": {"vendor": "intel", "hypervisor": False},
        "virtual": False,
        "ram_mib": 8000,
        "disks": [
            disk("sda", 1000, rotational=True, disc_gran=0, tran="sata"),
            usb_key(),
        ],
        "gpus": [{"vendor": "intel"}],
        "laptop": False,
        "battery": False,
        "wifi": False,
    }


def luks_profile(**override):
    """Profil chiffré inventé : LVM sur LUKS, volume secret de 4 Gio."""
    profil = {
        "schema": 1,
        "name": "essai-luks",
        "disk": {
            "layout": "lvm_on_luks",
            "esp_mib": 2048,
            "luks": {"iter_time_ms": 2500},
            "lvm": {
                "vg": "vgtest",
                "secret_lv": {"size_gib": 4, "optional": False},
                "vg_free_mib": 512,
            },
        },
        "system": {"timezone": "UTC", "console_keymap": "us"},
        "live": {"keymap": "us"},
        "user": {"name": "camille"},
        "security": {"header_backup": False},
    }
    for cle, valeur in override.items():
        profil[cle] = valeur
    return profil


def plain_profile():
    return {
        "schema": 1,
        "name": "essai-plain",
        "disk": {"layout": "plain"},
        "system": {"timezone": "UTC", "console_keymap": "us"},
        "live": {"keymap": "us"},
        "user": {"name": "camille"},
        "security": {"header_backup": False},
    }
