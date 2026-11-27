#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Configuration et justificatifs d'archinstall 4.5 pour une cible montée
à l'avance par l'étape disque (erplibre_disk) et finie par le greffon
(erplibre_plugin).

machine_config() part de la configuration de l'installateur 1b
(erplibre-install-config : GNOME + gdm, NetworkManager, pipewire, étape
ERPLibre en custom_commands, paquets de l'étape) et y pose ce que le
profil machine résolu décide :

- disk_config « pre_mounted_config » sur le point de montage : archinstall
  ne partitionne, ne chiffre ni ne monte rien ;
- bootloader_config « Systemd-boot » en UEFI 64 bits, « Grub » sinon : ce
  sont les deux valeurs qu'archinstall valide sans --skip-boot ; le greffon
  les remplace entièrement (on_add_bootloader rend True avant toute
  détection de partition). uki reste faux : avec uki, archinstall saute
  l'appel à mkinitcpio, donc on_mkinitcpio ; le greffon gère l'UKI ;
- swap désactivé : zram appartient au greffon (voir erplibre_plugin) ;
- noyaux, paquets, locale, clavier, fuseau, hôte, services, impression,
  profil de bureau (Minimal sans GNOME).

credentials() rend le contenu du fichier --creds : le compte (sudo selon
le profil) et, si la politique root est « password », le mot de passe
root. Les mots de passe y sont en clair ; archinstall les hache
(yescrypt) avant chpasswd. Le fichier ne vit que sur /run (tmpfs), en
0600, et shred() l'efface après archinstall.

Bibliothèque standard seulement.
"""

import copy
import json
import os

PRE_MOUNTED = "pre_mounted_config"
LOADER_SYSTEMD = "Systemd-boot"
LOADER_GRUB = "Grub"

ROOT_LOCK = "lock"
ROOT_PASSWORD = "password"
ROOT_POLICIES = (ROOT_LOCK, ROOT_PASSWORD)

APPARMOR_EXTRA_PACKAGES = ("audit",)
APPARMOR_EXTRA_SERVICES = ("auditd.service",)
# L'assistant AUR se construit au premier démarrage : git pour le clone,
# base-devel pour makepkg.
AUR_BUILD_PACKAGES = ("git", "base-devel")


def _get(settings, path, default=None):
    courant = settings
    for morceau in path.split("."):
        if not isinstance(courant, dict) or morceau not in courant:
            return default
        courant = courant[morceau]
    return courant


def _unique(elements):
    vus, resultat = set(), []
    for e in elements:
        if e and e not in vus:
            vus.add(e)
            resultat.append(e)
    return resultat


def bootloader_config(settings):
    nom = (
        LOADER_SYSTEMD
        if _get(settings, "boot.loader") == "systemd-boot"
        else LOADER_GRUB
    )
    return {"bootloader": nom, "uki": False, "removable": False}


def profile_config(settings):
    """GNOME + gdm, ou Minimal. Le pilote graphique n'est pas demandé à
    archinstall : les paquets résolus par le profil machine (mesa,
    vulkan-*, nvidia-open-dkms…) le remplacent."""
    if _get(settings, "desktop.env") == "gnome":
        return {
            "greeter": "gdm",
            "profile": {"main": "Desktop", "details": ["GNOME"]},
        }
    return {"profile": {"main": "Minimal"}}


def target_packages(settings, base_packages=()):
    """Les paquets de la cible : ceux de la configuration de départ
    (étape ERPLibre), puis ceux que resolve() a retenus, sans les noyaux
    (archinstall les pose dans le pacstrap de base), puis ceux
    qu'AppArmor et l'assistant AUR exigent."""
    noyaux = set(_get(settings, "system.kernels") or [])
    derives = (settings.get("derived") or {}).get("packages") or []
    paquets = list(base_packages) + [p for p in derives if p not in noyaux]
    if _get(settings, "security.apparmor"):
        paquets += APPARMOR_EXTRA_PACKAGES
    if _get(settings, "firstboot.aur_helper"):
        paquets += AUR_BUILD_PACKAGES
    return _unique(paquets)


def target_services(settings, base_services=()):
    derives = (settings.get("derived") or {}).get("services") or []
    services = list(base_services) + list(derives)
    if _get(settings, "security.apparmor"):
        services += APPARMOR_EXTRA_SERVICES
    return _unique(services)


def machine_config(base, settings, mountpoint):
    """La configuration archinstall : `base` (dict de
    erplibre-install-config.build_config, non modifié) plus les réglages
    résolus `settings`, cible pré-montée sur `mountpoint`."""
    config = copy.deepcopy(base)
    config["disk_config"] = {
        "config_type": PRE_MOUNTED,
        "mountpoint": str(mountpoint),
    }
    config["bootloader_config"] = bootloader_config(settings)
    config["kernels"] = list(_get(settings, "system.kernels") or ["linux"])
    config["packages"] = target_packages(
        settings, config.get("packages") or []
    )
    config["services"] = target_services(
        settings, config.get("services") or []
    )
    config["hostname"] = _get(settings, "system.hostname")
    config["timezone"] = _get(settings, "system.timezone")
    config["locale_config"] = {
        "kb_layout": _get(settings, "system.console_keymap"),
        "sys_lang": _get(settings, "system.lang"),
        "sys_enc": "UTF-8",
    }
    config["ntp"] = True
    config["swap"] = {"enabled": False, "algorithm": "zstd"}
    config["profile_config"] = profile_config(settings)
    app = dict(config.get("app_config") or {})
    app["print_service_config"] = {
        "enabled": bool(_get(settings, "desktop.printing"))
    }
    config["app_config"] = app
    return config


def credentials(settings, secrets, root_policy):
    """Le contenu de --creds. `secrets` : {"user_password",
    "root_password"}. La politique « lock » n'envoie aucun mot de passe
    root ; le greffon verrouille le compte."""
    creds = {
        "users": [
            {
                "username": _get(settings, "user.name"),
                "!password": secrets["user_password"],
                "sudo": bool(_get(settings, "user.sudo", True)),
                "groups": [],
            }
        ]
    }
    if root_policy == ROOT_PASSWORD:
        creds["!root-password"] = secrets["root_password"]
    return creds


def write_private_json(path, data):
    """Écrit `data` en JSON dans `path`, créé en 0600 avant toute écriture :
    le contenu n'est jamais lisible par un autre compte, même un instant."""
    os.makedirs(
        os.path.dirname(os.path.abspath(path)), mode=0o700, exist_ok=True
    )
    if os.path.exists(path):
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def shred(path):
    """Écrase `path` de zéros sur toute sa taille, le synchronise, puis le
    supprime ; rend vrai s'il existait. Sur tmpfs l'écrasement vide les
    pages avant leur libération ; l'effacement est ce qui compte."""
    try:
        taille = os.path.getsize(path)
    except OSError:
        return False
    try:
        with open(path, "r+b") as fh:
            fh.write(b"\0" * taille)
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    os.unlink(path)
    return True
