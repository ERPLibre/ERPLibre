#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Construit l'ISO ERPLibre Arch Linux x86_64 (archiso, profil releng).

L'ISO démarre en BIOS comme en UEFI, s'écrit telle quelle sur une clé USB
(image hybride, « dd »), et ouvre sur tty1 un installateur qui pose Arch
Linux + GNOME (gdm) + ERPLibre selon le profil choisi à l'installation.

Deux façons de construire (--builder) :
  - container (défaut) : dans une image Arch à jour (Podman de préférence,
    sinon Docker), construite par container/Containerfile et reprise tant
    qu'elle a moins de container_build.IMAGE_MAX_AGE_DAYS jours. Le
    conteneur relance ce script en « --builder host » ; voir
    container_build.py pour les montages et les droits. L'hôte n'a besoin
    ni d'archiso ni d'une base pacman à jour, ni même d'être une Arch.
  - host : mkarchiso de l'hôte, étapes ci-dessous ;
  - auto : container si un moteur répond, host sinon.

Étapes en mode host :
  1. Vérifie mkarchiso (paquet archiso) ; absent, affiche la commande
     pacman et sort en 2.
  2. Copie /usr/share/archiso/configs/releng dans WORK/profile, y superpose
     profile/ (ce répertoire), complète packages.x86_64, profiledef.sh,
     /root/.zlogin, les entrées de démarrage, écrit profiles.json et copie
     le checkout ERPLibre du TODO embarqué (checkout_files).
  3. Lance « mkarchiso -v [-r] -w WORK/build -o OUTDIR WORK/profile », en
     utilisateur (archiso >= 89 passe par unshare), par sudo sinon. « -r »
     (sauf --keep-work) fait effacer WORK/build par mkarchiso lui-même,
     dans l'espace de noms qui en possède les fichiers.
  4. Écrit OUTDIR/<iso>.sha256 au format de sha256sum, puis efface
     WORK/profile et WORK (sauf --keep-work).

Les profils ERPLibre viennent de QemuInstallMixin._qemu_install_profiles
(script/todo/qemu_install.py), la même table que le déploiement QEMU, et
l'unité erplibre.service de _qemu_odoo_service_cmd.

Exemples
--------
    ./script/iso/archlinux/build_iso.py --dry-run
    ./script/iso/archlinux/build_iso.py --refresh-image
    ./script/iso/archlinux/build_iso.py --builder host --branch develop
    .venv.erplibre/bin/python script/iso/archlinux/build_iso.py \\
        --output-dir /tmp/iso --lang en
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script.iso.archlinux import container_build  # noqa: E402

OVERLAY_DIR = HERE / "profile"
# Le profil machine (machine_profile.py, facts.py, profiles/*.json) : une
# seule source, partagée par le menu TODO et l'installateur, copiée dans
# l'ISO à la construction sous MACHINE_ISO_DIR.
MACHINE_DIR = HERE / "machine"
RELENG_DIR = Path("/usr/share/archiso/configs/releng")

ARCH = "x86_64"
ISO_NAME = "erplibre-archlinux"
DEFAULT_GIT_URL = "https://github.com/erplibre/erplibre"
DEFAULT_BRANCH = "master"
DEFAULT_OUTPUT_DIR = Path("~/.erplibre/iso")
# Répertoire par défaut de la variante de test (--auto-default). Le
# catalogue USB du TODO prend l'ISO la plus récente de DEFAULT_OUTPUT_DIR
# sans descendre dans ses sous-répertoires : la variante qui efface le
# disque n'y entre jamais.
AUTOTEST_OUTPUT_DIR = DEFAULT_OUTPUT_DIR / "autotest"
DEFAULT_AUTO_PROFILE = "odoo18"
# Cache pacman du mode container, monté sur /var/cache/pacman/pkg : une
# reconstruction ne retélécharge que les paquets qui ont changé. Il n'est
# jamais purgé par ce script.
DEFAULT_PKG_CACHE = DEFAULT_OUTPUT_DIR / "pkgcache"

BUILDER_CONTAINER = "container"
BUILDER_HOST = "host"
BUILDER_AUTO = "auto"
BUILDERS = (BUILDER_CONTAINER, BUILDER_HOST, BUILDER_AUTO)

# mkarchiso tourne sans root depuis archiso 89 (unshare --map-auto) ; avant,
# il exige root.
ARCHISO_ROOTLESS_MIN = 89
ARCHISO_INSTALL_CMD = ["sudo", "pacman", "-S", "--needed", "archiso"]

# Paquets que l'ISO LIVE exige en plus de releng. Ceux de l'étape ERPLibre
# (git, make, base-devel…) vont sur le système CIBLE par les « packages »
# d'archinstall : le live ne clone ni ne compile rien. python est déjà tiré
# par archinstall ; il est nommé parce qu'erplibre-install-config en
# dépend directement. python-textual porte l'écran de l'installateur.
#
# Le reste sert le TODO de la clé, qui tourne sur le Python du live avec
# des paquets Arch plutôt qu'un « pip install --target » des requirements
# d'ERPLibre : ceux-là sont construits pour CE Python et signés, au lieu
# de roues PyPI liées à une version de Python qu'une mise à jour d'Arch
# entre l'image de construction et l'ISO peut changer, et seul ce que le
# TODO importe au démarrage entre dans l'ISO. Les requirements entiers
# pèsent environ 480 Mio installés, 87 Mio en squashfs xz ; ces paquets,
# quelques Mio. La liste est la fermeture des imports de todo.py :
#   - REQUIRED_MODULES de todo.py (click, colorama, dotenv, humanize,
#     urwid) ;
#   - gitpython, xmltodict, retrying, qu'importe script/git/git_tool.py
#     par todo_upgrade : sans eux l'import échoue et crash_diagnostic
#     ouvre le menu d'installation d'Odoo au lieu du TODO ;
#   - tk, pour tkinter qu'importe kdbx_manager au chargement ;
#   - git, sans lequel todo.py refuse de démarrer.
# libisoburn fournit xorriso, par lequel le menu Clé USB du TODO écrit un
# profil machine dans une ISO dérivée.
# nftables porte le détournement de l'installation hors ligne
# (erplibre_offline) ; son DNS, dnsmasq, est déjà dans releng.
# Un menu qui importe autre chose à l'usage (assistant, courriel, KDBX)
# rend son erreur d'import sur le live, sans toucher au reste du TODO.
EXTRA_LIVE_PACKAGES = (
    "python",
    "python-textual",
    "python-click",
    "python-colorama",
    "python-dotenv",
    "python-humanize",
    "python-urwid",
    "python-gitpython",
    "python-xmltodict",
    "python-retrying",
    "tk",
    "git",
    "libisoburn",
    "nftables",
)

SHARE_DIR = "usr/local/share/erplibre-install"
PROFILES_JSON = f"{SHARE_DIR}/profiles.json"
MACHINE_ISO_DIR = f"{SHARE_DIR}/machine"
MACHINE_FILES = ("*.py", "profiles/*.json")

# Catalogue français de l'interface de l'installateur (erplibre_ui_i18n) :
# chaque phrase passée à tr() ou marquée N_() dans UI_MODULES, plus celles
# du profil machine, avec sa traduction prise dans todo_i18n.
CATALOGUE_JSON = f"{SHARE_DIR}/messages.fr.json"
CATALOGUE_VERSION = 1
UI_MODULES = (
    "erplibre_ui.py",
    "erplibre_ui_flow.py",
    "erplibre_ui_plain.py",
    "erplibre_ui_tui.py",
)
UI_MARKERS = frozenset({"tr", "N_"})

# Le TODO d'ERPLibre embarqué : un checkout du dépôt sous TODO_ISO_DIR,
# lancé par /usr/local/bin/erplibre-todo. Il porte l'état COURANT de
# l'arbre de travail tel que git le voit (checkout_files) :
#   - les fichiers suivis, copiés depuis l'arbre de travail, donc avec
#     leurs modifications non commitées ;
#   - les fichiers non suivis que .gitignore n'écarte pas : les nouveaux
#     fichiers d'une branche, pas encore indexés.
# git ls-files fait foi plutôt qu'un parcours du disque : venvs, addons
# posés par Google Repo, bases, ISO construites, caches et tout ce que
# .gitignore écarte n'y entrent jamais. Le dossier n'est pas un dépôt git :
# .git n'est pas copié.
TODO_ISO_DIR = "opt/erplibre"
CHECKOUT_LS_TRACKED = ("ls-files", "-z", "--cached")
CHECKOUT_LS_UNTRACKED = ("ls-files", "-z", "--others", "--exclude-standard")
# Écartés même suivis ou non ignorés : private/ porte les données propres
# à une installation, tasks/ le carnet de travail. De private/ ne passent
# que CHECKOUT_PRIVATE_KEPT : son .gitignore, et le __init__.py qui en
# fait un paquet importable.
CHECKOUT_EXCLUDED_DIRS = ("private", "tasks")
CHECKOUT_PRIVATE_KEPT = frozenset(
    {"private/.gitignore", "private/__init__.py"}
)
CHECKOUT_EXCLUDED_PARTS = frozenset({"__pycache__", ".git"})
CHECKOUT_EXCLUDED_SUFFIXES = (".pyc", ".pyo")
CHECKOUT_REQUIRED = "script/todo/todo.py"
# Un fichier NON SUIVI et non ignoré dont le nom (sans le dossier, casse
# ignorée) répond à l'un de ces motifs fnmatch n'entre jamais dans l'ISO :
# il a la forme d'un secret (clé, certificat, jeton, fichier
# d'environnement, base de mots de passe) ou d'une donnée (vidage SQL,
# archive, base SQLite) oubliée dans le checkout, et une clé USB se perd.
# Un fichier suivi est déjà publié avec le dépôt : la règle ne le touche
# pas. Les fichiers non suivis retenus sont nommés un par un dans le plan.
CHECKOUT_UNTRACKED_DENIED = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    "*.gpg",
    "*.asc",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*credential*",
    "*secret*",
    "*token*",
    "*password*",
    "accounts.json",
    "*.sql",
    "*.sql.*",
    "*.dump",
    "*.backup",
    "*.bak",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.zip",
    "*.tar",
    "*.tar.*",
    "*.tgz",
    "*.7z",
    "*.rar",
)
# En mode container, git tourne sur l'HÔTE et la liste retenue passe au
# build_iso du conteneur dans ce fichier du répertoire de sortie, monté
# sur /out. L'image n'a ainsi pas besoin de git, et un worktree, dont le
# .git renvoie hors du dépôt monté sur /src, se liste quand même. Chemins
# séparés par un octet nul, comme « git ls-files -z ».
CHECKOUT_LIST_NAME = ".erplibre-checkout-{epoch}.list"

# Fichiers de la surcouche qui doivent être exécutables dans l'ISO :
# mkarchiso copie airootfs sans ses modes (--no-preserve=mode) et ne
# rétablit que ceux de file_permissions.
INSTALLER_PERMISSIONS = {
    "/usr/local/bin/erplibre-install": "0:0:755",
    "/usr/local/bin/erplibre-install-config": "0:0:755",
    "/usr/local/bin/erplibre-installer": "0:0:755",
    "/usr/local/bin/erplibre-installer-ui": "0:0:755",
    "/usr/local/bin/erplibre-offline": "0:0:755",
    "/usr/local/bin/erplibre-todo": "0:0:755",
    f"/{SHARE_DIR}/erplibre-stage.sh": "0:0:755",
}

# Valeurs de profiledef.sh, en texte bash. iso_name donne le nom du fichier
# produit par mkarchiso : <iso_name>-<iso_version>-<arch>.iso. L'étiquette
# ISO 9660 reste sous 32 caractères.
PROFILEDEF_VALUES = {
    "iso_name": f'"{ISO_NAME}"',
    "iso_label": (
        '"ERPLIBRE_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"'
    ),
    "iso_publisher": '"ERPLibre <https://erplibre.ca>"',
    "iso_application": '"ERPLibre Arch Linux installer"',
}

# Ajout à /root/.zlogin de releng : l'installateur s'ouvre sur tty1, une
# fois par démarrage. Le repère sert à ne jamais l'ajouter deux fois.
ZLOGIN_MARKER = "# ERPLibre installer"
ZLOGIN_BLOCK = f"""
{ZLOGIN_MARKER} : sur tty1, une fois par démarrage ; « erplibre-install »
# le relance à la main.
if [[ $(tty) == "/dev/tty1" && ! -e /run/erplibre-install.started ]]; then
    /usr/local/bin/erplibre-install
fi
"""

SYSLINUX_SYS = "syslinux/archiso_sys.cfg"
SYSLINUX_AUTO_LABEL = "erplibreauto"
EFIBOOT_LOADER_CONF = "efiboot/loader/loader.conf"
SYSLINUX_LINUX_INCLUDE = "INCLUDE archiso_sys-linux.cfg"
SYSLINUX_AUTO_FILE = "archiso_sys-erplibre.cfg"
EFIBOOT_AUTO_FILE = "efiboot/loader/entries/04-erplibre-auto-linux.conf"
AUTO_TITLE = "ERPLibre automatic install (erases first disk)"
AUTO_KERNEL_PARAMS = "console=ttyS0,115200 console=tty0"

# Variante de TEST (--auto-default) : la SEULE qui porte l'entrée
# automatique, devenue celle par défaut avec un délai court ; elle ouvre
# sshd sur la cible (« erplibre.ssh ») pour que le test long l'inspecte
# après redémarrage. Elle efface le premier disque sans rien demander et
# crée un compte au mot de passe connu : le fichier porte un nom distinct
# pour ne jamais passer pour l'ISO d'installation, et AUTOTEST_MARKER,
# absent de l'ISO d'installation, est ce sans quoi erplibre-install refuse
# le mode « erplibre.auto » même tapé à la main sur la ligne du noyau.
AUTOTEST_ISO_NAME = f"{ISO_NAME}-autotest"
AUTOTEST_KERNEL_PARAM = "erplibre.ssh"
AUTOTEST_TIMEOUT_S = 3
AUTOTEST_MARKER = f"/{SHARE_DIR}/autotest"

# Clés de profil de l'ISO -> repère de la commande dans la table QEMU. Les
# libellés y sont traduits, les commandes non : on reconnaît le profil à sa
# commande.
_QEMU_PROFILE_MATCH = {
    "odoo18": lambda cmd: cmd.endswith("make install_odoo_18"),
    "home": lambda cmd: cmd.endswith("install_erplibre_home.sh"),
    "deployment": lambda cmd: "make install_dev" in cmd,
}

# Libellés propres à l'ISO (fr, en) : le profil Dev est dérivé du profil
# Déploiement QEMU, et « GNOME seul » n'existe pas côté QEMU.
_DEV_LABEL = {
    "fr": "ERPLibre Dev (make install_dev, sans service)",
    "en": "ERPLibre Dev (make install_dev, no service)",
}
_GNOME_LABEL = {
    "fr": "GNOME seul (sans ERPLibre)",
    "en": "GNOME only (no ERPLibre)",
}


def _qemu_mixin():
    """QemuInstallMixin, importé depuis la racine du dépôt. L'import ne tire
    que la bibliothèque standard et trois modules de script/todo."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from script.todo.qemu_install import QemuInstallMixin

    return QemuInstallMixin


def qemu_profiles_by_lang(langs=("fr", "en")):
    """{lang: [(libellé, commande)]} de _qemu_install_profiles, une liste
    par langue. La langue de todo_i18n est forcée le temps de l'appel, puis
    rétablie : rien n'est écrit dans env_var.sh."""
    mixin = _qemu_mixin()
    from script.todo import todo_i18n

    saved = todo_i18n._current_lang
    out = {}
    try:
        for lang in langs:
            todo_i18n._current_lang = lang
            out[lang] = list(mixin()._qemu_install_profiles())
    finally:
        todo_i18n._current_lang = saved
    return out


def _match_qemu(profiles, key):
    """(index, commande) du profil QEMU que `key` désigne."""
    for i, (_label, cmd) in enumerate(profiles):
        if _QEMU_PROFILE_MATCH[key](cmd):
            return i, cmd
    raise LookupError(f"QEMU install profile not found: {key}")


def iso_profiles(by_lang, qemu_pkgs_suffix):
    """Profils de l'installateur, dans l'ordre du menu, le premier étant le
    défaut. Chaque profil : key, label {fr, en}, command, service (unité
    erplibre.service), postgresql (serveur démarré avant la commande).

    - odoo18 et home : commande et libellés de la table QEMU, tels quels ;
    - dev : la commande du profil Déploiement QEMU, privée de la préparation
      de l'hôte QEMU (`qemu_pkgs_suffix`), qui démarre libvirt et
      redémarre la machine, deux choses impossibles dans le chroot
      d'archinstall ;
    - gnome : aucune commande.

    PostgreSQL est requis par toute commande qui passe par « make
    install_os » : l'installeur Arch y crée le rôle de l'utilisateur."""
    langs = list(by_lang)
    base = by_lang[langs[0]]
    result = []
    for key in ("odoo18", "home"):
        idx, cmd = _match_qemu(base, key)
        result.append(
            {
                "key": key,
                "label": {lang: by_lang[lang][idx][0] for lang in langs},
                "command": cmd,
                "service": key == "odoo18",
            }
        )
    _idx, deploy_cmd = _match_qemu(base, "deployment")
    suffix = " && " + qemu_pkgs_suffix
    if not deploy_cmd.endswith(suffix):
        raise LookupError("QEMU deployment profile changed shape")
    result.append(
        {
            "key": "dev",
            "label": dict(_DEV_LABEL),
            "command": deploy_cmd[: -len(suffix)],
            "service": False,
        }
    )
    result.append(
        {
            "key": "gnome",
            "label": dict(_GNOME_LABEL),
            "command": "",
            "service": False,
        }
    )
    for profile in result:
        profile["postgresql"] = "make install_os" in profile["command"]
    return result


def service_unit_template(service_cmd):
    """Texte de l'unité erplibre.service extrait du snippet de
    _qemu_odoo_service_cmd : le document en ligne entre « <<UNIT » et
    « UNIT ». Ses variables ($SVC_USER, $SVC_GROUP, $SVC_DIR,
    $SELINUX_LINE) restent telles quelles ; l'étape ERPLibre les remplace."""
    match = re.search(r"<<UNIT\n(.*?)\nUNIT\n", service_cmd, re.S)
    if not match:
        raise LookupError("erplibre.service heredoc not found")
    return match.group(1)


def profiles_document(git_url, branch, lang, auto_profile):
    """Contenu de profiles.json, lu par l'installateur de l'ISO."""
    mixin = _qemu_mixin()
    profiles = iso_profiles(qemu_profiles_by_lang(), mixin._QEMU_QEMU_PKGS)
    keys = [p["key"] for p in profiles]
    if auto_profile not in keys:
        raise ValueError(f"unknown profile {auto_profile!r}: {keys}")
    return {
        "version": 1,
        "lang": lang,
        "default_profile": profiles[0]["key"],
        "auto_profile": auto_profile,
        # Source réseau de l'étape ERPLibre : le seul endroit à changer
        # pour cloner ailleurs (voir el_network_source_prepare).
        "network_source": {"git_url": git_url, "branch": branch},
        "profiles": profiles,
        "service_unit": service_unit_template(
            mixin()._qemu_odoo_service_cmd(prod=False)
        ),
    }


def merge_packages(text, extra):
    """packages.x86_64 avec `extra` ajoutés à la fin, sans doublon. Les
    commentaires et lignes vides d'origine sont gardés."""
    present = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    added = [pkg for pkg in extra if pkg not in present]
    if not added:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "".join(f"{pkg}\n" for pkg in added)


def edit_profiledef(text, values, permissions):
    """profiledef.sh avec les affectations de `values` remplacées et les
    entrées de `permissions` posées dans file_permissions=( … ).

    Une clé de `values` absente du fichier, ou un tableau file_permissions
    introuvable, lève ValueError : releng a changé de forme, et une ISO au
    mauvais nom ou aux scripts non exécutables ne doit pas sortir."""
    for key, value in values.items():
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        if not pattern.search(text):
            raise ValueError(f"profiledef.sh: {key}= not found")
        text = pattern.sub(lambda _m, k=key, v=value: f"{k}={v}", text, 1)
    lines = text.splitlines(keepends=True)
    start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.startswith("file_permissions=(")
        ),
        None,
    )
    if start is None:
        raise ValueError("profiledef.sh: file_permissions=( not found")
    end = next(
        (i for i in range(start, len(lines)) if lines[i].strip() == ")"),
        None,
    )
    if end is None:
        raise ValueError("profiledef.sh: file_permissions not closed")
    body = [
        ln
        for ln in lines[start + 1 : end]
        if not any(f'["{path}"]' in ln for path in permissions)
    ]
    body += [f'  ["{path}"]="{mode}"\n' for path, mode in permissions.items()]
    return "".join(lines[: start + 1] + body + lines[end:])


def edit_zlogin(text):
    """/root/.zlogin avec l'appel de l'installateur, ajouté une fois."""
    if ZLOGIN_MARKER in text:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ZLOGIN_BLOCK


def edit_syslinux_sys(text):
    """archiso_sys.cfg qui inclut l'entrée automatique APRÈS les entrées
    normales : DEFAULT ne change pas."""
    include = f"INCLUDE {SYSLINUX_AUTO_FILE}"
    if include in text:
        return text
    if SYSLINUX_LINUX_INCLUDE not in text:
        raise ValueError(f"{SYSLINUX_SYS}: {SYSLINUX_LINUX_INCLUDE} missing")
    return text.replace(
        SYSLINUX_LINUX_INCLUDE, f"{SYSLINUX_LINUX_INCLUDE}\n{include}", 1
    )


def auto_kernel_params(profile_key, test=False):
    params = f"erplibre.auto={profile_key} {AUTO_KERNEL_PARAMS}"
    return f"{params} {AUTOTEST_KERNEL_PARAM}" if test else params


def syslinux_auto_entry(profile_key, test=False):
    """Entrée BIOS (syslinux) du mode automatique. Les %…% sont remplacés
    par mkarchiso, comme dans archiso_sys-linux.cfg."""
    return (
        f"LABEL {SYSLINUX_AUTO_LABEL}\n"
        "TEXT HELP\n"
        "ERPLibre automatic install: ERASES the first disk without asking.\n"
        "Made for automated tests. Serial console on ttyS0.\n"
        "ENDTEXT\n"
        f"MENU LABEL {AUTO_TITLE} (%ARCH%, BIOS)\n"
        "LINUX /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux\n"
        "INITRD /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img\n"
        "APPEND archisobasedir=%INSTALL_DIR% "
        "archisosearchuuid=%ARCHISO_UUID% "
        f"{auto_kernel_params(profile_key, test)} %KERNEL_PARAMS%\n"
    )


def efiboot_auto_entry(profile_key, test=False):
    """Entrée UEFI (systemd-boot) du mode automatique. loader.conf de
    releng garde « default 01-archiso-linux.conf »."""
    return (
        f"title    {AUTO_TITLE} (%ARCH%, UEFI)\n"
        "sort-key 04\n"
        "linux    /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux\n"
        "initrd   /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img\n"
        "options  archisobasedir=%INSTALL_DIR% "
        "archisosearchuuid=%ARCHISO_UUID% "
        f"{auto_kernel_params(profile_key, test)} %KERNEL_PARAMS%\n"
    )


def _set_directive(text, pattern, line, where):
    """`text` dont l'unique ligne qui correspond à `pattern` devient
    `line` ; ValueError si elle manque."""
    regex = re.compile(pattern, re.M)
    if not regex.search(text):
        raise ValueError(f"{where}: {pattern} not found")
    return regex.sub(lambda _m: line, text, 1)


def edit_syslinux_default_auto(text):
    """archiso_sys.cfg de la variante de test : DEFAULT et TIMEOUT
    (dixièmes de seconde) désignent l'entrée automatique."""
    text = _set_directive(
        text, r"^DEFAULT .*$", f"DEFAULT {SYSLINUX_AUTO_LABEL}", SYSLINUX_SYS
    )
    return _set_directive(
        text,
        r"^TIMEOUT .*$",
        f"TIMEOUT {AUTOTEST_TIMEOUT_S * 10}",
        SYSLINUX_SYS,
    )


def edit_loader_conf_default_auto(text):
    """loader.conf de la variante de test : systemd-boot démarre l'entrée
    automatique."""
    text = _set_directive(
        text,
        r"^default .*$",
        f"default {Path(EFIBOOT_AUTO_FILE).name}",
        EFIBOOT_LOADER_CONF,
    )
    return _set_directive(
        text,
        r"^timeout .*$",
        f"timeout {AUTOTEST_TIMEOUT_S}",
        EFIBOOT_LOADER_CONF,
    )


def iso_version(epoch):
    """iso_version de releng : date UTC de SOURCE_DATE_EPOCH.

    profiledef.sh la calcule avec « date », donc dans le fuseau du
    processus mkarchiso ; le plan pose TZ=UTC pour que le nom prédit ici
    soit celui que mkarchiso écrit, en conteneur (UTC par défaut) comme
    sur l'hôte (fuseau local, sinon décalé d'un jour en soirée).
    """
    return time.strftime("%Y.%m.%d", time.gmtime(epoch))


def iso_basename(epoch, name=ISO_NAME):
    return f"{name}-{iso_version(epoch)}-{ARCH}.iso"


def parse_archiso_version(text):
    """« archiso 92-1 » (pacman -Q) ou « mkarchiso 92 » -> 92 ; None sinon."""
    match = re.search(r"\b(\d+)(?:[-.]\d+)*\s*$", (text or "").strip())
    return int(match.group(1)) if match else None


def archiso_version(run=subprocess.run):
    """Version majeure d'archiso installée, None si mkarchiso manque, 0 si
    pacman ne la donne pas. mkarchiso n'a pas d'option de version : 0 est
    traité comme une version ancienne, donc par sudo."""
    if not shutil.which("mkarchiso"):
        return None
    try:
        out = run(
            ["pacman", "-Q", "archiso"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return 0
    version = parse_archiso_version(out.stdout)
    return version if out.returncode == 0 and version else 0


def needs_sudo(version, euid=None):
    """sudo n'est utile qu'à un utilisateur ordinaire sous archiso < 89."""
    if euid is None:
        euid = os.geteuid()
    return euid != 0 and version < ARCHISO_ROOTLESS_MIN


def build_plan(
    work,
    output_dir,
    epoch,
    version,
    keep_work,
    euid=None,
    iso_name=ISO_NAME,
):
    """Ce que la construction fera, en données : chemins, commande
    mkarchiso, environnement et nettoyage. Sert à --dry-run comme à
    l'exécution.

    « clean » est le répertoire que build_iso efface après une réussite,
    ou None (--keep-work). Il ne contient alors plus que WORK/profile,
    écrit par build_iso : WORK/build, dont les fichiers appartiennent à
    root ou aux sous-UID de l'utilisateur (unshare --map-auto), est effacé
    par mkarchiso lui-même grâce à « -r »."""
    work = Path(work)
    profile_dir = work / "profile"
    build_dir = work / "build"
    if euid is None:
        euid = os.geteuid()
    sudo = needs_sudo(version, euid)
    mkarchiso = (
        ["mkarchiso", "-v"]
        + ([] if keep_work else ["-r"])
        + ["-w", str(build_dir), "-o", str(output_dir), str(profile_dir)]
    )
    # SOURCE_DATE_EPOCH fixe la date dans iso_version et iso_label : le nom
    # du fichier produit est connu d'avance. Par sudo, l'environnement ne
    # passe pas : « env » le pose.
    env = {"SOURCE_DATE_EPOCH": str(epoch), "TZ": "UTC"}
    env_assign = [f"{k}={v}" for k, v in env.items()]
    argv = (["sudo", "env", *env_assign] if sudo else []) + mkarchiso
    iso = Path(output_dir) / iso_basename(epoch, iso_name)
    return {
        "work": str(work),
        "profile_dir": str(profile_dir),
        "build_dir": str(build_dir),
        "output_dir": str(output_dir),
        "iso": str(iso),
        "sha256": str(iso) + ".sha256",
        "sudo": sudo,
        "env": env,
        "mkarchiso": argv,
        "clean": None if keep_work else str(work),
    }


# Ce que la surcouche ne doit jamais porter dans l'ISO : le cache que
# Python écrit à côté d'un script importé (les tests chargent
# erplibre-install-config), propre à l'hôte et porteur de son chemin.
OVERLAY_IGNORE = ("__pycache__", "*.pyc")


def profile_edits(auto_default=False, permissions=None):
    """[(chemin relatif, fonction texte -> texte)] appliquées aux fichiers
    de releng, dans l'ordre. Chaque fonction lève ValueError si releng a
    changé de forme. `permissions` va dans file_permissions de
    profiledef.sh (INSTALLER_PERMISSIONS par défaut, voir
    iso_permissions)."""
    values = dict(PROFILEDEF_VALUES)
    if auto_default:
        values["iso_name"] = f'"{AUTOTEST_ISO_NAME}"'
    if permissions is None:
        permissions = INSTALLER_PERMISSIONS
    edits = [
        ("packages.x86_64", lambda t: merge_packages(t, EXTRA_LIVE_PACKAGES)),
        (
            "profiledef.sh",
            lambda t: edit_profiledef(t, values, permissions),
        ),
        ("airootfs/root/.zlogin", edit_zlogin),
    ]
    if auto_default:
        edits += [
            (SYSLINUX_SYS, edit_syslinux_sys),
            (SYSLINUX_SYS, edit_syslinux_default_auto),
            (EFIBOOT_LOADER_CONF, edit_loader_conf_default_auto),
        ]
    return edits


def check_releng(releng, auto_default=False):
    """Applique profile_edits aux fichiers de `releng` en mémoire, sans
    rien écrire : lève OSError (fichier absent) ou ValueError (forme
    changée) là où prepare_profile échouerait. Sert à --dry-run et à
    refuser avant de créer le répertoire de travail."""
    texts = {}
    for rel, func in profile_edits(auto_default):
        if rel not in texts:
            texts[rel] = (Path(releng) / rel).read_text(encoding="utf-8")
        texts[rel] = func(texts[rel])


def prepare_profile(
    releng,
    overlay,
    profile_dir,
    doc,
    auto_profile,
    auto_default=False,
    checkout=None,
):
    """Écrit le profil archiso complet dans `profile_dir` : copie de
    releng, surcouche (sans OVERLAY_IGNORE), puis les fichiers édités ou
    générés, et le checkout du TODO. `auto_default` produit la variante
    de test (voir AUTOTEST_ISO_NAME). `checkout` est la liste de
    checkout_files ; None la calcule sur REPO_ROOT."""
    if checkout is None:
        checkout = checkout_files(REPO_ROOT)
    permissions = iso_permissions(REPO_ROOT, checkout)
    profile_dir = Path(profile_dir)
    shutil.copytree(releng, profile_dir, symlinks=True)
    shutil.copytree(
        overlay,
        profile_dir,
        symlinks=True,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*OVERLAY_IGNORE),
    )
    for rel, func in profile_edits(auto_default, permissions):
        path = profile_dir / rel
        path.write_text(func(path.read_text(encoding="utf-8")), "utf-8")
    if auto_default:
        (profile_dir / "syslinux" / SYSLINUX_AUTO_FILE).write_text(
            syslinux_auto_entry(auto_profile, auto_default), "utf-8"
        )
        (profile_dir / EFIBOOT_AUTO_FILE).write_text(
            efiboot_auto_entry(auto_profile, auto_default), "utf-8"
        )
        marque = profile_dir / "airootfs" / AUTOTEST_MARKER.lstrip("/")
        marque.parent.mkdir(parents=True, exist_ok=True)
        marque.write_text(f"{auto_profile}\n", "utf-8")
    target = profile_dir / "airootfs" / PROFILES_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8"
    )
    copy_machine(MACHINE_DIR, profile_dir / "airootfs" / MACHINE_ISO_DIR)
    catalogue, manquantes = catalogue_document(catalogue_strings())
    for phrase in manquantes:
        print(
            f"messages.fr.json : sans traduction : {phrase}", file=sys.stderr
        )
    (profile_dir / "airootfs" / CATALOGUE_JSON).write_text(
        json.dumps(catalogue, indent=1, ensure_ascii=False, sort_keys=True)
        + "\n",
        "utf-8",
    )
    copy_checkout(REPO_ROOT, profile_dir / "airootfs" / TODO_ISO_DIR, checkout)


def iso_permissions(repo, checkout):
    """INSTALLER_PERMISSIONS plus chaque fichier de `checkout` que son
    bit x marque exécutable dans `repo` : mkarchiso pose airootfs sans
    les modes, et le TODO lance ses scripts par leur chemin."""
    droits = dict(INSTALLER_PERMISSIONS)
    for rel in checkout:
        if os.access(Path(repo) / rel, os.X_OK):
            droits[f"/{TODO_ISO_DIR}/{rel}"] = "0:0:755"
    return droits


def select_checkout(paths):
    """La règle de sélection du checkout, sur des chemins relatifs au
    dépôt (séparateur « / », tels que git les rend) ; rend la liste triée,
    sans doublon. N'accède pas au disque.

    Écarte :
      - un chemin vide, absolu, ou dont un composant est vide, « . » ou
        « .. » : une liste lue d'un fichier ne sort jamais du dépôt ;
      - un chemin qui finit par « / », ce que « --others » rend pour un
        dépôt git imbriqué, dont le contenu ne se liste pas ;
      - un composant de CHECKOUT_EXCLUDED_PARTS, un suffixe de
        CHECKOUT_EXCLUDED_SUFFIXES ;
      - ce qui vit sous CHECKOUT_EXCLUDED_DIRS, sauf
        CHECKOUT_PRIVATE_KEPT."""
    retenus = set()
    for chemin in paths:
        if not chemin or chemin.startswith("/") or chemin.endswith("/"):
            continue
        parties = chemin.split("/")
        if any(p in ("", ".", "..") for p in parties):
            continue
        if CHECKOUT_EXCLUDED_PARTS.intersection(parties):
            continue
        if chemin.endswith(CHECKOUT_EXCLUDED_SUFFIXES):
            continue
        if (
            parties[0] in CHECKOUT_EXCLUDED_DIRS
            and chemin not in CHECKOUT_PRIVATE_KEPT
        ):
            continue
        retenus.add(chemin)
    return sorted(retenus)


def git_listing(repo, run=subprocess.run):
    """(suivis, non suivis) : les chemins bruts de CHECKOUT_LS_TRACKED et
    CHECKOUT_LS_UNTRACKED dans `repo`. LookupError si git manque ou si
    `repo` n'est pas un checkout git. core.quotePath n'a pas d'effet
    avec -z : les noms arrivent tels quels."""
    listes = []
    for args in (CHECKOUT_LS_TRACKED, CHECKOUT_LS_UNTRACKED):
        argv = ["git", "-C", str(repo), *args]
        try:
            proc = run(argv, capture_output=True, check=False)
        except OSError as err:
            raise LookupError(f"git unavailable: {err}") from err
        if proc.returncode != 0:
            message = os.fsdecode(proc.stderr or b"").strip()
            raise LookupError(f"{repo} is not a git checkout: {message}")
        listes.append(parse_checkout_list(proc.stdout))
    return listes[0], listes[1]


def parse_checkout_list(data):
    """Les chemins d'une liste séparée par des octets nuls (bytes), dans
    l'ordre, sans les entrées vides."""
    return [os.fsdecode(p) for p in data.split(b"\0") if p]


def format_checkout_list(paths):
    """L'inverse de parse_checkout_list : chaque chemin suivi d'un octet
    nul."""
    return b"".join(os.fsencode(p) + b"\0" for p in paths)


def untracked_denied(chemin):
    """Vrai si le fichier non suivi `chemin` (relatif, séparateur « / »)
    répond à un motif de CHECKOUT_UNTRACKED_DENIED."""
    import fnmatch

    nom = chemin.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(nom, m) for m in CHECKOUT_UNTRACKED_DENIED)


def checkout_files(repo=REPO_ROOT, listing=None, run=subprocess.run):
    """Les chemins relatifs du checkout à embarquer, triés :
    select_checkout de `listing` (une liste de chemins déjà lue) ou, à
    défaut, de git_listing(repo), réduite à ce qui est un fichier régulier
    dans `repo`. Un fichier suivi effacé de l'arbre de travail n'y est
    plus ; un lien symbolique est écarté, sa cible pouvant sortir du
    dépôt. LookupError si CHECKOUT_REQUIRED n'en fait pas partie."""
    repo = Path(repo)
    if listing is None:
        suivis, non_suivis = git_listing(repo, run)
        listing = suivis + non_suivis
    fichiers = [
        rel
        for rel in select_checkout(listing)
        if (repo / rel).is_file() and not (repo / rel).is_symlink()
    ]
    if CHECKOUT_REQUIRED not in fichiers:
        raise LookupError(f"{CHECKOUT_REQUIRED} not found in {repo}")
    return fichiers


def copy_checkout(repo, dest, checkout):
    """Copie chaque fichier de `checkout` de `repo` sous `dest`, chemins
    relatifs gardés (contenu seul : mkarchiso pose les modes par
    iso_permissions) ; rend leur nombre."""
    repo, dest = Path(repo), Path(dest)
    for rel in checkout:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / rel, dest / rel)
    return len(checkout)


def checkout_size(repo, checkout):
    """Octets des fichiers de `checkout` dans `repo`, avant compression."""
    return sum((Path(repo) / rel).stat().st_size for rel in checkout)


def ui_strings(paths):
    """Les phrases littérales passées à tr() ou N_() (nom seul ou
    attribut, « self.app.tr(...) ») dans les fichiers `paths`, triées.
    Lu par ast : une phrase écrite sur plusieurs lignes, concaténée par
    Python, compte pour une."""
    import ast

    phrases = set()
    for chemin in paths:
        arbre = ast.parse(Path(chemin).read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call) or not noeud.args:
                continue
            fonction = noeud.func
            nom = (
                fonction.id
                if isinstance(fonction, ast.Name)
                else getattr(fonction, "attr", None)
            )
            premier = noeud.args[0]
            if (
                nom in UI_MARKERS
                and isinstance(premier, ast.Constant)
                and isinstance(premier.value, str)
            ):
                phrases.add(premier.value)
    return sorted(phrases)


def catalogue_strings():
    """Les phrases anglaises du catalogue de l'installateur : celles des
    UI_MODULES, puis celles du profil machine (codes, jetons, libellés
    de plan_summary)."""
    from script.iso.archlinux.machine import machine_profile, profile_messages

    share = OVERLAY_DIR / "airootfs" / SHARE_DIR
    phrases = set(ui_strings([share / nom for nom in UI_MODULES]))
    for table in (
        profile_messages.REASONS,
        profile_messages.WARNINGS,
        profile_messages.TOKENS,
    ):
        phrases.update(table.values())
    phrases.update(machine_profile.SUMMARY_LABELS)
    return sorted(phrases)


def catalogue_document(phrases, translations=None):
    """({"version", "fr": {anglais: français}}, phrases sans traduction).
    `translations` est la table de todo_i18n (anglais → {"fr", "en"}) ;
    une phrase sans entrée française est laissée hors du catalogue,
    l'interface l'affiche alors en anglais."""
    if translations is None:
        from script.todo import todo_i18n

        translations = todo_i18n.TRANSLATIONS
    fr, manquantes = {}, []
    for phrase in phrases:
        entree = translations.get(phrase) or {}
        if entree.get("fr"):
            fr[phrase] = entree["fr"]
        else:
            manquantes.append(phrase)
    return {"version": CATALOGUE_VERSION, "fr": fr}, manquantes


def copy_machine(source, dest):
    """Copie dans `dest` les fichiers MACHINE_FILES de `source`, chemins
    relatifs gardés ; rend leur liste triée. Seuls ces motifs passent,
    jamais __pycache__ ni un fichier d'éditeur. LookupError si
    machine_profile.py manque."""
    source, dest = Path(source), Path(dest)
    copies = []
    for motif in MACHINE_FILES:
        for chemin in sorted(source.glob(motif)):
            rel = chemin.relative_to(source)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(chemin, dest / rel)
            copies.append(str(rel))
    if "machine_profile.py" not in copies:
        raise LookupError(f"machine_profile.py not found in {source}")
    return sorted(copies)


def sha256_line(path):
    """« <empreinte>  <nom> », le format que « sha256sum -c » relit."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return f"{digest.hexdigest()}  {Path(path).name}\n"


def _print_checkout(checkout):
    """Les lignes du plan sur le checkout : nombre de fichiers, dont non
    suivis quand on le sait, leur poids avant compression, puis chaque
    fichier non suivi retenu et chaque fichier non suivi écarté par
    CHECKOUT_UNTRACKED_DENIED, par son chemin : un fichier oublié dans
    le checkout se voit avant de partir sur la clé."""
    taille = checkout["bytes"] / 1024**2
    suivis = (
        ""
        if checkout["untracked"] is None
        else f", dont {checkout['untracked']} non suivis"
    )
    print(
        f"  checkout    : {len(checkout['files'])} fichiers{suivis}, "
        f"{taille:.1f} Mio -> /{TODO_ISO_DIR}"
    )
    for chemin in checkout.get("untracked_names") or []:
        print(f"    non suivi : {chemin}")
    for chemin in checkout.get("denied") or []:
        print(f"    écarté    : {chemin} (forme d'un secret ou d'une donnée)")


def _print_plan(plan, doc, checkout):
    print("Plan :")
    print(f"  releng      : {RELENG_DIR}")
    print(f"  surcouche   : {OVERLAY_DIR}")
    print(f"  profil      : {plan['profile_dir']}")
    print(
        f"  source      : {doc['network_source']['git_url']}"
        f" ({doc['network_source']['branch']})"
    )
    print(f"  profils     : {', '.join(p['key'] for p in doc['profiles'])}")
    if Path(plan["iso"]).name.startswith(AUTOTEST_ISO_NAME):
        print(f"  automatique : erplibre.auto={doc['auto_profile']}")
    _print_checkout(checkout)
    if Path(plan["iso"]).name.startswith(AUTOTEST_ISO_NAME):
        print("  ATTENTION   : variante de test, l'entrée par défaut efface")
        print("                le premier disque sans demander")
    print(
        f"  commande    : SOURCE_DATE_EPOCH={plan['env']['SOURCE_DATE_EPOCH']}"
        f" {shlex.join(plan['mkarchiso'])}"
    )
    print(f"  ISO         : {plan['iso']}")
    print(f"  empreinte   : {plan['sha256']}")
    if plan["clean"]:
        print(f"  nettoyage   : mkarchiso -r, puis {plan['clean']}")
    else:
        print(f"  conservé    : {plan['work']}")


def _parser():
    parser = argparse.ArgumentParser(
        description="Construit l'ISO ERPLibre Arch Linux x86_64 (archiso).",
        epilog="Exemple : ./script/iso/archlinux/build_iso.py --dry-run",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"branche ERPLibre clonée sur la cible (défaut {DEFAULT_BRANCH})",
    )
    parser.add_argument(
        "--git-url",
        default=DEFAULT_GIT_URL,
        help=f"dépôt ERPLibre cloné (défaut {DEFAULT_GIT_URL})",
    )
    parser.add_argument(
        "--output-dir",
        help="répertoire de l'ISO et de son .sha256 (défaut "
        f"{DEFAULT_OUTPUT_DIR} ; {AUTOTEST_OUTPUT_DIR} avec --auto-default, "
        "qui refuse le premier)",
    )
    parser.add_argument(
        "--work-dir",
        help="répertoire de travail (défaut ~/.erplibre/iso/work/<date>)",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="garder le répertoire de travail après une réussite",
    )
    parser.add_argument(
        "--auto-default",
        metavar="PROFIL",
        help="TESTS SEULEMENT : ISO « -autotest » dont l'entrée par défaut "
        "est l'installation automatique de PROFIL (efface le premier "
        "disque sans demander) et ouvre sshd sur la cible",
    )
    parser.add_argument(
        "--lang",
        choices=("fr", "en"),
        default=(
            os.environ.get("EL_LANG")
            if os.environ.get("EL_LANG") in ("fr", "en")
            else "fr"
        ),
        help="langue de l'installateur (défaut : EL_LANG, sinon fr)",
    )
    parser.add_argument(
        "--releng",
        default=str(RELENG_DIR),
        help=f"profil archiso de départ (défaut {RELENG_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="afficher le plan sans rien écrire",
    )
    parser.add_argument(
        "--builder",
        choices=BUILDERS,
        default=BUILDER_CONTAINER,
        help="où tourne mkarchiso : container (défaut, image Arch à jour), "
        "host (archiso de l'hôte), auto (container si un moteur répond)",
    )
    parser.add_argument(
        "--runtime",
        choices=container_build.RUNTIME_ORDER,
        help="moteur imposé en mode container (défaut : podman s'il "
        "répond, sinon docker)",
    )
    parser.add_argument(
        "--refresh-image",
        action="store_true",
        help="reconstruire l'image de construction même si elle est "
        f"récente (moins de {container_build.IMAGE_MAX_AGE_DAYS} jours)",
    )
    parser.add_argument(
        "--pkg-cache",
        help="cache pacman gardé d'une construction à l'autre, mode "
        f"container (défaut {DEFAULT_PKG_CACHE})",
    )
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        help="date de l'ISO (nom, étiquette), en secondes depuis 1970 "
        "(défaut : maintenant)",
    )
    parser.add_argument(
        "--chown",
        metavar="UID:GID",
        help="après mkarchiso, donner l'ISO, son empreinte et le travail "
        "gardé à UID:GID (le mode container le pose quand mkarchiso y "
        "tourne en root)",
    )
    parser.add_argument(
        "--checkout-list",
        metavar="FICHIER",
        help="chemins du checkout embarqué, séparés par des octets nuls, "
        "au lieu de git ls-files (le mode container le pose : git tourne "
        "sur l'hôte)",
    )
    parser.add_argument(
        "--chown-tree",
        action="append",
        default=[],
        metavar="CHEMIN",
        help="arbre donné récursivement au propriétaire de --chown",
    )
    return parser


def resolve_output_dir(output_dir, auto_default):
    """Répertoire de sortie : `output_dir`, sinon celui du type d'ISO.
    ValueError si la variante de test viserait DEFAULT_OUTPUT_DIR, où le
    catalogue USB la prendrait pour l'ISO d'installation."""
    default = AUTOTEST_OUTPUT_DIR if auto_default else DEFAULT_OUTPUT_DIR
    path = Path(output_dir or default).expanduser()
    if auto_default and (
        path.resolve() == DEFAULT_OUTPUT_DIR.expanduser().resolve()
    ):
        raise ValueError(
            f"--auto-default refuse {DEFAULT_OUTPUT_DIR} : "
            f"utiliser {AUTOTEST_OUTPUT_DIR}"
        )
    return path


def exit_code(rc):
    """Code de sortie d'un processus fils : un signal (rc négatif de
    subprocess) devient 128 + signal, comme dans un shell."""
    return 128 - rc if rc < 0 else rc


def _iso_state(path):
    """(taille, mtime en ns) de l'ISO, None si elle n'existe pas."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return st.st_size, st.st_mtime_ns


def parse_owner(text):
    """« uid:gid » -> (uid, gid) ; ValueError sinon."""
    match = re.fullmatch(r"(\d+):(\d+)", text or "")
    if not match:
        raise ValueError(f"--chown attend UID:GID, pas {text!r}")
    return int(match.group(1)), int(match.group(2))


def chown_outputs(owner, paths, trees):
    """Donne à `owner` (uid, gid) chaque chemin de `paths`, et chaque arbre
    de `trees` récursivement. Un chemin absent est ignoré ; les liens sont
    changés eux-mêmes, jamais leur cible.

    WORK/build n'y figure jamais : ses fichiers portent les propriétaires
    du système de l'ISO, et mkarchiso relancé sur un travail gardé les
    reprendrait tels quels dans une nouvelle image."""
    uid, gid = owner
    for path in paths:
        if os.path.lexists(path):
            os.lchown(path, uid, gid)
    for tree in trees:
        if not os.path.lexists(tree):
            continue
        os.lchown(tree, uid, gid)
        for root, dirs, files in os.walk(tree):
            for name in dirs + files:
                os.lchown(os.path.join(root, name), uid, gid)


def _runtime_facts(forced=None):
    """Fiches container_runtime des moteurs candidats (`forced` seul s'il
    est donné). Isolé pour que les tests le remplacent."""
    from script.todo import container_runtime

    if forced:
        return [container_runtime.etat(forced)]
    return container_runtime.etats()


def _image_tags(fiche):
    """Étiquettes-date de l'image de construction présentes dans le
    moteur. Isolé pour que les tests le remplacent."""
    from script.todo import container_runtime

    argv = container_build.images_argv(fiche, container_runtime.commande)
    code, out = container_runtime.lancer(argv, timeout=60)
    return container_build.parse_image_lines(out) if code == 0 else []


def _commande(fiche, args):
    from script.todo import container_runtime

    return container_runtime.commande(fiche, args)


def _run_live(argv):
    """Lance `argv` en laissant passer sa sortie ; rend le code de sortie
    façon shell.

    Ctrl-C atteint aussi le client du moteur, qui le relaie au conteneur :
    on ATTEND alors sa fin au lieu de le tuer. Tué, le client laisserait le
    conteneur tourner seul, détaché, jusqu'au bout de mkarchiso."""
    sys.stdout.flush()
    proc = subprocess.Popen(argv)
    while True:
        try:
            return exit_code(proc.wait())
        except KeyboardInterrupt:
            continue


def main(argv=None):
    args = _parser().parse_args(argv)
    epoch = (
        args.source_date_epoch
        if args.source_date_epoch is not None
        else int(time.time())
    )
    owner = None
    try:
        output_dir = resolve_output_dir(args.output_dir, args.auto_default)
        if args.chown:
            owner = parse_owner(args.chown)
    except ValueError as err:
        print(f"Erreur : {err}", file=sys.stderr)
        return 2

    auto_profile = args.auto_default or DEFAULT_AUTO_PROFILE
    try:
        doc = profiles_document(
            args.git_url, args.branch, args.lang, auto_profile
        )
        checkout = read_checkout(args.checkout_list)
    except (LookupError, OSError, ValueError) as err:
        print(f"Erreur : {err}", file=sys.stderr)
        return 1

    if args.builder == BUILDER_HOST:
        return _main_host(args, epoch, output_dir, doc, owner, checkout)
    fiche = container_build.pick_runtime(_runtime_facts(args.runtime))
    if fiche is None and args.builder == BUILDER_AUTO:
        print("Aucun moteur de conteneur ne répond : construction sur l'hôte.")
        return _main_host(args, epoch, output_dir, doc, owner, checkout)
    return _main_container(args, fiche, epoch, output_dir, checkout)


def read_checkout(list_path=None, repo=REPO_ROOT, run=subprocess.run):
    """{"files", "untracked", "untracked_names", "denied", "bytes"} du
    checkout à embarquer. Sans `list_path`, la liste vient de git :
    untracked est le nombre de fichiers retenus que git ne suit pas,
    untracked_names leurs chemins, denied les chemins non suivis écartés
    par untracked_denied. Avec `list_path`, la liste vient du fichier que
    l'hôte a écrit après ce même tri (untracked inconnu, None ; listes
    vides). LookupError ou OSError sinon."""
    refuses = []
    if list_path:
        listing = parse_checkout_list(Path(list_path).read_bytes())
        files = checkout_files(repo, listing)
        untracked, noms = None, []
    else:
        suivis, non_suivis = git_listing(repo, run)
        suivis_set = set(suivis)
        refuses = sorted(
            p
            for p in non_suivis
            if p not in suivis_set and untracked_denied(p)
        )
        gardes = [p for p in non_suivis if p not in set(refuses)]
        files = checkout_files(repo, suivis + gardes)
        noms = sorted(set(files).intersection(gardes) - suivis_set)
        untracked = len(noms)
    return {
        "files": files,
        "untracked": untracked,
        "untracked_names": noms,
        "denied": refuses,
        "bytes": checkout_size(repo, files),
    }


def _default_work():
    return DEFAULT_OUTPUT_DIR / "work" / time.strftime("%Y%m%d-%H%M%S")


def _main_host(args, epoch, output_dir, doc, owner, checkout):
    """mkarchiso de l'hôte (ou du conteneur, qui relance ce script en
    « --builder host »)."""
    work = Path(args.work_dir or _default_work()).expanduser()
    auto_profile = args.auto_default or DEFAULT_AUTO_PROFILE
    auto_default = bool(args.auto_default)
    iso_name = AUTOTEST_ISO_NAME if auto_default else ISO_NAME

    version = archiso_version()
    if version is None:
        print("mkarchiso est introuvable (paquet archiso). Pour l'installer :")
        print(f"  {shlex.join(ARCHISO_INSTALL_CMD)}")
        print("ou construire dans un conteneur : --builder container")
        if not args.dry_run:
            return 2
        version = ARCHISO_ROOTLESS_MIN

    plan = build_plan(
        work, output_dir, epoch, version, args.keep_work, iso_name=iso_name
    )
    _print_plan(plan, doc, checkout)

    # Les mêmes refus en --dry-run qu'à l'exécution, sauf releng absent
    # quand archiso l'est aussi : le plan sert alors à préparer l'hôte.
    releng = Path(args.releng)
    if releng.is_dir():
        try:
            check_releng(releng, auto_default)
        except (OSError, ValueError) as err:
            print(f"Erreur : profil releng inattendu : {err}", file=sys.stderr)
            return 2
    elif args.dry_run and not shutil.which("mkarchiso"):
        print(f"  (releng {releng} absent : vient avec archiso)")
    else:
        print(f"Erreur : {releng} introuvable.", file=sys.stderr)
        return 2
    if work.exists():
        print(f"Erreur : {work} existe déjà.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    work.mkdir(parents=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        prepare_profile(
            releng,
            OVERLAY_DIR,
            plan["profile_dir"],
            doc,
            auto_profile,
            auto_default,
            checkout["files"],
        )
    except (OSError, ValueError) as err:
        print(f"Erreur : profil non préparé : {err}", file=sys.stderr)
        shutil.rmtree(work, ignore_errors=True)
        return 1

    iso = Path(plan["iso"])
    sha256 = Path(plan["sha256"])

    def give_back():
        # --chown : ce que cette construction a écrit hors de WORK/build.
        if owner:
            chown_outputs(
                owner,
                [iso, sha256, work],
                [plan["profile_dir"]] + list(args.chown_tree),
            )

    # Une empreinte ne côtoie jamais une ISO qu'elle ne décrit pas :
    # mkarchiso efface puis réécrit l'ISO de même nom (même date), et un
    # échec ou une interruption au milieu laisse une ISO tronquée.
    sha256.unlink(missing_ok=True)
    before = _iso_state(iso)
    env = dict(os.environ, **plan["env"])
    # Le plan s'affiche avant la sortie de mkarchiso, même vers un fichier.
    sys.stdout.flush()
    try:
        rc = subprocess.run(plan["mkarchiso"], env=env, check=False)
        rc = exit_code(rc.returncode)
    except KeyboardInterrupt:
        rc = 130
    if rc != 0 or not iso.is_file():
        # Une ISO que mkarchiso a touchée sans finir est inutilisable ;
        # celle d'une construction antérieure, intacte, reste.
        if _iso_state(iso) not in (None, before):
            iso.unlink(missing_ok=True)
        give_back()
        print(
            f"Erreur : mkarchiso a rendu {rc} ; travail gardé dans {work}",
            file=sys.stderr,
        )
        return rc or 1
    tmp = sha256.with_name(sha256.name + ".tmp")
    tmp.write_text(sha256_line(iso), "utf-8")
    os.replace(tmp, sha256)
    print(f"ISO      : {iso}")
    print(f"SHA256   : {sha256}")
    if plan["clean"]:
        try:
            shutil.rmtree(plan["clean"])
        except OSError as err:
            print(
                f"Avertissement : {work} non effacé : {err}", file=sys.stderr
            )
    give_back()
    return 0


def container_passthrough(args, checkout_list=None):
    """Options transmises au build_iso du conteneur : celles qui ne
    désignent aucun chemin de l'hôte, plus `checkout_list`, le nom de la
    liste du checkout dans le répertoire de sortie (lue sous /out)."""
    out = [
        "--branch",
        args.branch,
        "--git-url",
        args.git_url,
        "--lang",
        args.lang,
    ]
    if args.auto_default:
        out += ["--auto-default", args.auto_default]
    if checkout_list:
        out += [
            "--checkout-list",
            f"{container_build.OUT}/{checkout_list}",
        ]
    return out


def container_plan(args, fiche, epoch, output_dir, tags, today):
    """Le plan du mode container, en données : moteur, image (reprise ou
    à construire), argv de « build », de « run », chemins de l'hôte.
    ValueError si une option ou un chemin ne s'y prête pas."""
    if args.releng != str(RELENG_DIR):
        raise ValueError("--releng ne vaut qu'avec --builder host")
    mode = container_build.strategy(fiche)
    pkg_cache = Path(args.pkg_cache or DEFAULT_PKG_CACHE).expanduser()
    work = None
    if args.keep_work or args.work_dir:
        work = Path(args.work_dir or _default_work()).expanduser().absolute()
    tag = (
        None if args.refresh_image else container_build.fresh_tag(tags, today)
    )
    build = None
    if tag is None:
        tag = container_build.date_tag(today)
        build = container_build.build_argv(fiche, _commande, tag)
    owner = (
        container_build.owner_of_caller()
        if mode == container_build.STRATEGY_ROOT
        else None
    )
    checkout_list = CHECKOUT_LIST_NAME.format(epoch=epoch)
    inner = container_build.inner_argv(
        container_passthrough(args, checkout_list),
        epoch,
        work_name=work.name if work else None,
        keep_work=args.keep_work,
        owner=owner,
    )
    iso_name = AUTOTEST_ISO_NAME if args.auto_default else ISO_NAME
    iso = output_dir.absolute() / iso_basename(epoch, iso_name)
    return {
        "runtime": fiche["moteur"],
        "strategy": mode,
        "image": container_build.image_ref(tag),
        "build": build,
        "prune": [t for t in tags if t != tag] if build else [],
        "run": container_build.run_argv(
            fiche,
            _commande,
            container_build.image_ref(tag),
            REPO_ROOT,
            output_dir.absolute(),
            pkg_cache.absolute(),
            inner,
            work_parent=work.parent if work else None,
        ),
        "output_dir": str(output_dir.absolute()),
        "pkg_cache": str(pkg_cache.absolute()),
        "work": str(work) if work else None,
        "iso": str(iso),
        "sha256": str(iso) + ".sha256",
        "checkout_list": str(output_dir.absolute() / checkout_list),
    }


def _print_container_plan(plan):
    print("Plan (conteneur) :")
    print(f"  moteur      : {plan['runtime']} ({plan['strategy']})")
    if plan["build"]:
        print(f"  image       : {plan['image']} (à construire)")
        print(f"  build       : {shlex.join(plan['build'])}")
    else:
        print(f"  image       : {plan['image']} (reprise)")
    print(f"  run         : {shlex.join(plan['run'])}")
    print(f"  cache       : {plan['pkg_cache']}")
    if plan["work"]:
        print(f"  travail     : {plan['work']}")
    print(f"  ISO         : {plan['iso']}")
    print(f"  empreinte   : {plan['sha256']}")
    if Path(plan["iso"]).name.startswith(AUTOTEST_ISO_NAME):
        print("  ATTENTION   : variante de test, l'entrée par défaut efface")
        print("                le premier disque sans demander")


def _work_removal_hint(plan):
    """Commande qui efface un travail gardé : WORK/build appartient aux
    UID du conteneur, que le compte ne peut pas effacer lui-même."""
    if plan["strategy"] == container_build.STRATEGY_USERNS:
        return shlex.join(["podman", "unshare", "rm", "-rf", plan["work"]])
    return shlex.join(["sudo", "rm", "-rf", plan["work"]])


def _main_container(args, fiche, epoch, output_dir, checkout):
    if fiche is None:
        print(
            "Erreur : ni podman ni docker ne répond (voir le menu Conteneurs "
            "du TODO) ; --builder host construit avec l'archiso de l'hôte.",
            file=sys.stderr,
        )
        return 2
    started = time.monotonic()
    # Lues même sur --refresh-image : elles sont retirées après la
    # reconstruction.
    tags = _image_tags(fiche)
    try:
        plan = container_plan(
            args, fiche, epoch, output_dir, tags, datetime.date.today()
        )
    except ValueError as err:
        print(f"Erreur : {err}", file=sys.stderr)
        return 2
    _print_container_plan(plan)
    _print_checkout(checkout)
    if plan["work"] and Path(plan["work"]).exists():
        print(f"Erreur : {plan['work']} existe déjà.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    # Créés ici, au nom de l'appelant : un moteur crée sinon en root le
    # point de montage absent, ou refuse de démarrer.
    output_dir.mkdir(parents=True, exist_ok=True)
    Path(plan["pkg_cache"]).mkdir(parents=True, exist_ok=True)
    if plan["work"]:
        Path(plan["work"]).parent.mkdir(parents=True, exist_ok=True)

    if plan["build"]:
        rc = _run_live(plan["build"])
        if rc != 0:
            print(f"Erreur : construction de l'image : {rc}", file=sys.stderr)
            return rc
        for old in plan["prune"]:
            argv = container_build.rmi_argv(fiche, _commande, old)
            subprocess.run(argv, check=False, capture_output=True)

    # La liste ne vit que le temps du conteneur : elle est retirée quelle
    # que soit l'issue, Ctrl-C compris.
    liste = Path(plan["checkout_list"])
    liste.write_bytes(format_checkout_list(checkout["files"]))
    try:
        rc = _run_live(plan["run"])
    finally:
        liste.unlink(missing_ok=True)
    iso = Path(plan["iso"])
    if plan["work"] and Path(plan["work"]).exists():
        print(f"Travail gardé : {plan['work']}")
        print(f"  pour l'effacer : {_work_removal_hint(plan)}")
    if rc != 0 or not iso.is_file():
        print(
            f"Erreur : construction dans le conteneur : {rc}", file=sys.stderr
        )
        return rc or 1
    minutes, seconds = divmod(int(time.monotonic() - started), 60)
    print(f"ISO      : {iso} ({iso.stat().st_size} octets)")
    print(f"SHA256   : {plan['sha256']}")
    print(f"Durée    : {minutes} min {seconds:02d} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
