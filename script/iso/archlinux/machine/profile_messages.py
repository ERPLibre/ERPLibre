#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les phrases des codes du profil machine, en anglais : clés de
traduction stables que l'appelant passe à sa fonction de traduction
(t() de todo_i18n dans le menu TODO, le catalogue de l'ISO dans
l'installateur). Les « {champ} » se remplissent par str.format_map avec
les détails du code.

Une seule source pour les deux côtés : ce fichier est copié dans l'ISO
avec machine_profile, d'où la bibliothèque standard seulement.
"""

# Les codes de machine_profile.validate() et de ProfileError.
REASONS = {
    "not-object": "{path}: the profile is not a JSON object.",
    "json": "{path} cannot be read as JSON: {error}",
    "secret": (
        "{path}: passwords, keys and hashes are never stored in a profile; "
        "they are asked during installation."
    ),
    "unknown-key": "{path}: unknown field.",
    "schema": "{path}: schema version {value}, expected {expected}.",
    "name": (
        "{path}: « {value} » is not a valid name (lowercase letters, digits, "
        "- and _)."
    ),
    "type": "{path}: « {value} » has the wrong type ({expected} expected).",
    "choice": "{path}: « {value} » is not one of: {allowed}.",
    "size": "{path}: {value} is below the minimum ({minimum}).",
    "empty": "{path}: the list cannot be empty.",
    "special": "{path}: « {value} » is not accepted for this field.",
    "hostname": "{path}: « {value} » is not a valid host name (RFC 1123).",
    "user-name": (
        "{path}: « {value} » is not a valid user name, or the system reserves"
        " it."
    ),
    "locale": "{path}: « {value} » is not a locale such as en_US.UTF-8.",
    "keymap": "{path}: « {value} » is not a keyboard layout name.",
    "country": "{path}: « {value} » is not a country name.",
    "timezone": "{path}: « {value} » is not a time zone such as Area/City.",
    "device": "{path}: « {value} » is not a /dev/… path.",
    "package": "{path}: « {item} » is not a valid package name.",
    "service": "{path}: « {item} » is not a valid unit name.",
    "kernels": "{path}: choose one or more distinct kernels among: {allowed}.",
    "zram-size": (
        "{path}: « {value} » must be a number of MiB, « ram / N » or « "
        "min(ram / N, M) »."
    ),
    "lang-not-in-locales": (
        "{path}: {value} must also be listed in system.locales."
    ),
    "hibernation-without-swap": "{path}: hibernation needs a swap volume.",
    "required": "{path}: this field is required.",
    "secret-lv-needs-luks": (
        "{path}: a secret volume needs the lvm_on_luks layout."
    ),
    "extends-missing": "The parent profile « {name} » does not exist.",
    "extends-cycle": "The profiles extend each other in a loop: {chain}.",
}

# Les mises en garde de machine_profile.resolve().
WARNINGS = {
    "no-disk": (
        "No internal fixed disk of at least 20 GiB was found (USB disks are "
        "never chosen automatically): the disk will be asked during "
        "installation."
    ),
    "disk-not-found": "{device} is not present on this computer.",
    "disk-is-boot-medium": "{device} is the boot medium.",
    "boot-medium-unknown": (
        "The boot medium was not identified: no disk is chosen "
        "automatically; check that the chosen disk is not the key."
    ),
    "nvme-format-shared": (
        "{device} shares its NVMe controller with other namespaces: "
        "reformatting to 4 KiB sectors is not offered, it could erase them."
    ),
    "disk-is-usb": (
        "{device} is connected by USB: check that it is not a backup disk."
    ),
    "answer-invalid": (
        "{path}: the answer « {value} » is refused; the question stays."
    ),
    "disk-unknown": (
        "The disk is not known yet: sector size, TRIM and swap are computed "
        "again once it is chosen."
    ),
    "swap-capped": (
        "Swap capped at {capped} GiB instead of {requested} GiB (a quarter of"
        " the disk at most): hibernation is off."
    ),
    "hibernation-off": (
        "Hibernation is off: the swap cannot hold all the memory."
    ),
    "hibernation-needs-lvm": (
        "Hibernation is off: the plain layout has no swap volume."
    ),
    "swap-large": (
        "The {swap} GiB swap takes more than a quarter of the {disk} GiB disk."
    ),
    "ram-unknown": (
        "The memory size is unknown: no swap volume is created, and "
        "hibernation is off."
    ),
    "loader-needs-uefi": (
        "systemd-boot needs a 64-bit UEFI boot: this machine boots with BIOS "
        "or 32-bit UEFI."
    ),
    "uefi-32bit": (
        "32-bit UEFI firmware: GRUB is installed for i386-efi; check that the"
        " machine boots before relying on it."
    ),
    "gpu-no-nvidia": (
        "The {driver} driver is chosen but no NVIDIA card was detected."
    ),
}

# Les jetons de valeur de machine_profile.plan_summary() et leur phrase.
TOKENS = {
    "yes": "yes",
    "no": "no",
    "none": "none",
    "ask": "asked during installation",
    "auto": "detected during installation",
}
