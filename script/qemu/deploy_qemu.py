#!/usr/bin/env python3
"""Déploiement rapide de VM Linux (Ubuntu/Debian/Fedora) via cloud-image + qemu-img + cloud-init + virt-install.

Choisissez la distribution avec --distro (ubuntu par défaut, debian, fedora)
et la version avec --version. « --list-images » affiche tout le catalogue et
les specs minimales. Reprend le workflow des notes :
  1. Télécharge l'image cloud (si absente du cache -> pas de double téléchargement).
  2. Convertit/copie l'image en un qcow2 de travail dédié à la VM.
  3. Redimensionne le disque virtuel.
  4. Génère user-data / meta-data et construit le seed.iso (cidata).
  5. Lance virt-install en important le disque + le seed en CD-ROM.

Exemples
--------
    # Le plus simple : image téléchargée automatiquement (chemin déduit de
    # --distro/--version, mis en cache dans /var/lib/libvirt/images/iso) et
    # outils manquants installés après confirmation.
    sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \\
        --ssh-key ~/.ssh/id_ed25519.pub

    # Debian 12 / Fedora 42 (mêmes options, --distro change la source d'image)
    sudo ./script/qemu/deploy_qemu.py --distro debian --version 12 \\
        --name deb12 --ssh-key ~/.ssh/id_ed25519.pub
    sudo ./script/qemu/deploy_qemu.py --distro fedora --version 42 \\
        --name fed42 --ssh-key ~/.ssh/id_ed25519.pub

    # Voir tout le catalogue (distros, versions, specs minimales)
    ./script/qemu/deploy_qemu.py --list-images

    # Télécharger (et vérifier) une image, sans créer de VM
    sudo ./script/qemu/deploy_qemu.py --download-only --version 24.04 --verify

    # Déploiement minimal en fournissant explicitement le chemin d'image
    sudo ./qemu-deploy.py /var/lib/libvirt/images/iso/noble.img \\
        --name test-vm --ssh-key ~/.ssh/id_ed25519.pub

    # Reproduction fidèle des notes (8 Go RAM, 8 vCPU, mot de passe demandé)
    sudo ./qemu-deploy.py /var/lib/libvirt/images/iso/noble.img \\
        --name test-vm --memory 8192 --vcpus 8 --disk-size 120G --ask-password

    # Voir ce qui serait fait, sans rien exécuter
    ./qemu-deploy.py /var/lib/libvirt/images/iso/noble.img --name test-vm --dry-run

    sudo ./script/qemu/deploy_qemu.py /var/lib/libvirt/images/iso/noble.img --name test-vm --memory 8192 --vcpus 8 --disk-size 120G --ask-password --force
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

# --------------------------------------------------------------------------- #
# Registre des distributions : version -> (code, --osinfo, RAM min Mo, disque).
# Le « code » est le nom de code (Ubuntu/Debian) ou le numéro de release
# (Fedora). RAM/disque minimaux proviennent de libosinfo (osinfo-db) : ce sont
# les seuils sous lesquels virt-install avertit. Ils servent de valeurs PAR
# DÉFAUT — la VM démarre au plus juste sans gaspiller la RAM de l'hôte.
# --codename / --osinfo / --memory / --disk-size surchargent au besoin.
# --------------------------------------------------------------------------- #
# NB : les versions intermédiaires (non-LTS) sont RETIRÉES du miroir
# cloud-images une fois EOL (leur /current/ renvoie 404). On ne garde donc
# que les LTS + les intermédiaires encore publiées. À réviser au fil du temps.
UBUNTU_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "20.04": ("focal", "ubuntu20.04", 2048, "5G"),
    "22.04": ("jammy", "ubuntu22.04", 2048, "10G"),
    "24.04": ("noble", "ubuntu24.04", 3072, "20G"),
    "25.10": ("questing", "ubuntu25.10", 3072, "20G"),
    "26.04": ("resolute", "ubuntu26.04", 3072, "20G"),
}
DEBIAN_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "11": ("bullseye", "debian11", 1024, "10G"),
    "12": ("bookworm", "debian12", 1024, "10G"),
    "13": ("trixie", "debian13", 1024, "10G"),
}
FEDORA_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "41": ("41", "fedora41", 2048, "15G"),
    "42": ("42", "fedora42", 2048, "15G"),
    "43": ("43", "fedora43", 2048, "15G"),
    "44": ("44", "fedora44", 2048, "15G"),
}
# Arch est en rolling release : une seule « version » (latest).
ARCH_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "latest": ("latest", "archlinux", 1024, "10G"),
}

# distro -> (table des versions, version par défaut).
DISTROS: dict[str, tuple[dict[str, tuple[str, str, int, str]], str]] = {
    "ubuntu": (UBUNTU_VERSIONS, "24.04"),
    "debian": (DEBIAN_VERSIONS, "12"),
    "fedora": (FEDORA_VERSIONS, "42"),
    "arch": (ARCH_VERSIONS, "latest"),
}

# Traduction de l'arch générique (amd64/arm64) vers le nom propre à la distro.
ARCH_ALIASES: dict[str, dict[str, str]] = {
    "fedora": {"amd64": "x86_64", "arm64": "aarch64"},
    "arch": {"amd64": "x86_64", "arm64": "aarch64"},
}

ARCH_CLOUD_BASE = "https://geo.mirror.pkgbuild.com/images/latest"

CLOUD_IMG_BASE = "https://cloud-images.ubuntu.com"
# Debian : cloud.debian.org est un redirecteur qui, selon le réseau, peut
# renvoyer vers un miroir injoignable. On essaie donc plusieurs bases dans
# l'ordre (le premier miroir qui répond gagne). Les deux acc.umu.se sont des
# miroirs Debian officiels de repli.
DEBIAN_CLOUD_BASES: tuple[str, ...] = (
    "https://cloud.debian.org/images/cloud",
    "https://gemmei.ftp.acc.umu.se/cdimage/cloud",
    "https://laotzu.ftp.acc.umu.se/cdimage/cloud",
)
FEDORA_BASE = "https://download.fedoraproject.org/pub/fedora/linux/releases"

# Répertoire de cache par défaut des images cloud (cohérent avec --disk-dir /
# --seed-dir). L'écriture y nécessite root : le déploiement tourne de toute
# façon sous sudo (virt-install). Surchargez avec --image-dir au besoin.
DEFAULT_IMAGE_DIR = Path("/var/lib/libvirt/images/iso")

# Emplacements de la base osinfo-db (détection d'un --osinfo connu).
OSINFO_DB_DIRS: tuple[str, ...] = (
    "/usr/share/osinfo/os",
    "/usr/local/share/osinfo/os",
    os.path.expanduser("~/.local/share/osinfo/os"),
)


def distro_arch(distro: str, arch: str) -> str:
    """Nom d'architecture attendu par la distro (Fedora utilise x86_64)."""
    return ARCH_ALIASES.get(distro, {}).get(arch, arch)


def image_url(distro: str, code: str, arch: str, version: str) -> str:
    """URL directe (primaire) de l'image cloud (Ubuntu/Debian)."""
    return image_candidates(distro, code, arch, version, dry_run=True)[0]


def image_candidates(
    distro: str, code: str, arch: str, version: str, dry_run: bool = False
) -> list[str]:
    """Liste ordonnée d'URL candidates pour l'image cloud. Plusieurs miroirs
    pour Debian ; une seule URL pour Ubuntu/Fedora."""
    a = distro_arch(distro, arch)
    if distro == "ubuntu":
        # /releases/<version>/release/ : présent pour toutes les versions
        # publiées (redirige vers l'image datée), contrairement à /current/
        # qui disparaît quand une version intermédiaire devient EOL.
        return [
            f"{CLOUD_IMG_BASE}/releases/{version}/release/"
            f"ubuntu-{version}-server-cloudimg-{a}.img"
        ]
    if distro == "debian":
        return [
            f"{base}/{code}/latest/debian-{version}-genericcloud-{a}.qcow2"
            for base in DEBIAN_CLOUD_BASES
        ]
    if distro == "fedora":
        return [resolve_fedora_url(version, arch, dry_run)]
    if distro == "arch":
        # Rolling release : image « latest » officielle (cloud-init inclus).
        return [f"{ARCH_CLOUD_BASE}/Arch-Linux-{a}-cloudimg.qcow2"]
    raise ValueError(f"URL indisponible pour la distro {distro!r}")


def resolve_fedora_url(version: str, arch: str, dry_run: bool) -> str:
    """Résout l'URL du qcow2 « Fedora Cloud Base Generic » depuis l'index
    HTML des releases (Fedora ne publie pas de lien « latest »)."""
    a = distro_arch("fedora", arch)
    index = f"{FEDORA_BASE}/{version}/Cloud/{a}/images/"
    pattern = re.compile(
        rf"Fedora-Cloud-Base-Generic-{version}-[0-9.]+\.{a}\.qcow2"
    )
    if dry_run:
        return index + f"Fedora-Cloud-Base-Generic-{version}-<build>.{a}.qcow2"
    try:
        with urllib.request.urlopen(index, timeout=30) as resp:  # noqa: S310
            html = resp.read().decode(errors="replace")
    except Exception as exc:  # pragma: no cover - dépend du réseau
        sys.exit(f"Impossible de lister les images Fedora {version} : {exc}")
    names = sorted(set(pattern.findall(html)))
    if not names:
        sys.exit(
            "Aucune image « Fedora-Cloud-Base-Generic » trouvée pour "
            f"Fedora {version} ({a}) dans {index}"
        )
    return index + names[-1]


def default_image_name(distro: str, code: str, arch: str, version: str) -> str:
    """Nom de fichier local pour le cache d'image."""
    a = distro_arch(distro, arch)
    if distro == "ubuntu":
        return f"ubuntu-{version}-server-cloudimg-{a}.img"
    if distro == "debian":
        return f"debian-{version}-genericcloud-{a}.qcow2"
    if distro == "arch":
        return f"arch-linux-{a}-cloudimg.qcow2"
    return f"fedora-cloud-{version}-{a}.qcow2"


def osinfo_known(short_id: str) -> bool:
    """Vrai si l'id osinfo (ex. « ubuntu26.04 ») figure dans osinfo-db."""
    needle = f"<short-id>{short_id}</short-id>"
    for base in OSINFO_DB_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".xml"):
                    continue
                try:
                    with open(
                        os.path.join(root, fn),
                        encoding="utf-8",
                        errors="replace",
                    ) as fh:
                        if needle in fh.read():
                            return True
                except OSError:
                    continue
    return False


def osinfo_arg(osinfo: str, distro: str = "") -> str:
    """Valeur --osinfo résiliente à un osinfo-db périmé. Si l'id est connu on
    l'utilise ; sinon on retombe sur le DERNIER osinfo connu de la même distro
    (meilleures perfs que « generic », pas d'avertissement) ; en dernier
    recours, détection best-effort. Utile pour une version plus récente que la
    base locale (ex. ubuntu26.04, fedora43+)."""
    if "=" in osinfo or "," in osinfo:
        return osinfo  # forme avancée déjà fournie par l'utilisateur
    if osinfo_known(osinfo):
        return osinfo
    # Repli 1 : dernier osinfo connu de la même distro (ordre de la table).
    versions = DISTROS.get(distro, ({}, ""))[0]
    known = [v[1] for v in versions.values() if osinfo_known(v[1])]
    if known:
        fallback = known[-1]
        print(
            f"  osinfo « {osinfo} » inconnu (osinfo-db) — repli sur "
            f"« {fallback} » (proche). « sudo apt upgrade osinfo-db » pour "
            "l'entrée exacte."
        )
        return fallback
    # Repli 2 : détection best-effort (évite l'échec, peut donner generic).
    print(
        f"  osinfo « {osinfo} » inconnu de la base locale (osinfo-db) — repli "
        "sur la détection auto (detect=on,require=off).\n"
        "  Astuce : « sudo apt upgrade osinfo-db » pour des métadonnées à jour."
    )
    return "detect=on,require=off"


def list_images() -> None:
    """Affiche toutes les distros/versions et leurs specs (--list-images)."""
    print("Images cloud disponibles (distro / version / specs) :\n")
    for distro, (versions, default) in DISTROS.items():
        print(f"  {distro}  (défaut : {default})")
        for v, (code, osinfo, ram, disk) in versions.items():
            star = "*" if v == default else " "
            note = (
                ""
                if osinfo_known(osinfo)
                else "  [osinfo local absent → auto]"
            )
            print(
                f"   {star} {v:<7} {code:<10} osinfo={osinfo:<12} "
                f"RAM≥{ram}Mo disque≥{disk}{note}"
            )
        print()
    print("Exemple : deploy_qemu.py --distro debian --version 12 --name vm1")


# --------------------------------------------------------------------------- #
# Utilitaires d'exécution
# --------------------------------------------------------------------------- #
class Runner:
    """Exécute (ou affiche, en dry-run) les commandes, avec sudo au besoin."""

    def __init__(self, use_sudo: bool, dry_run: bool) -> None:
        self.use_sudo = use_sudo
        self.dry_run = dry_run

    def run(
        self, cmd: list[str], *, privileged: bool = False, check: bool = True
    ) -> None:
        if privileged and self.use_sudo:
            cmd = ["sudo", *cmd]
        printable = " ".join(cmd)
        if self.dry_run:
            print(f"  [dry-run] {printable}")
            return
        print(f"  $ {printable}")
        try:
            subprocess.run(cmd, check=check)
        except subprocess.CalledProcessError as exc:
            # Sortie propre plutôt qu'une trace Python illisible.
            sys.exit(
                f"\nÉchec de la commande (code {exc.returncode}) :\n"
                f"  {printable}"
            )


def need_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"Erreur : outil requis introuvable dans le PATH : {name!r}")


# --------------------------------------------------------------------------- #
# Détection et installation des dépendances système
# --------------------------------------------------------------------------- #
# Outils indispensables au déploiement complet (le mode --download-only n'en
# requiert aucun).
REQUIRED_TOOLS: tuple[str, ...] = ("qemu-img", "virt-install", "virsh")
# Pour construire le seed cloud-init il faut AU MOINS un de ces outils.
SEED_TOOLS: tuple[str, ...] = ("cloud-localds", "genisoimage")

# outil -> nom de paquet, selon le gestionnaire de paquets détecté.
TOOL_PACKAGES: dict[str, dict[str, str]] = {
    "apt": {
        "qemu-img": "qemu-utils",
        "virt-install": "virtinst",
        "virsh": "libvirt-clients",
        "cloud-localds": "cloud-image-utils",
        "genisoimage": "genisoimage",
        "openssl": "openssl",
    },
    "dnf": {
        "qemu-img": "qemu-img",
        "virt-install": "virt-install",
        "virsh": "libvirt-client",
        "cloud-localds": "cloud-utils",
        "genisoimage": "genisoimage",
        "openssl": "openssl",
    },
    "pacman": {
        "qemu-img": "qemu-img",
        "virt-install": "virt-install",
        "virsh": "libvirt",
        "cloud-localds": "cloud-image-utils",
        "genisoimage": "cdrtools",
        "openssl": "openssl",
    },
    "zypper": {
        "qemu-img": "qemu-tools",
        "virt-install": "virt-install",
        "virsh": "libvirt-client",
        "cloud-localds": "cloud-utils-cloud-localds",
        "genisoimage": "genisoimage",
        "openssl": "openssl",
    },
    "brew": {
        "qemu-img": "qemu",
        "virt-install": "virt-manager",
        "virsh": "libvirt",
        "cloud-localds": "cdrtools",
        "genisoimage": "cdrtools",
        "openssl": "openssl",
    },
}

# Paquets fournissant le démon libvirt + l'émulateur QEMU système. Ils sont
# INDISPENSABLES pour exécuter la VM : virsh/virt-install (clients) seuls ne
# créent pas le socket /var/run/libvirt/libvirt-sock.
# On inclut le firmware UEFI (OVMF/edk2) : le boot par défaut est UEFI
# (indispensable pour Debian 13+ ; les images récentes n'ont plus de BIOS).
DAEMON_PACKAGES: dict[str, list[str]] = {
    "apt": ["libvirt-daemon-system", "qemu-system-x86", "ovmf"],
    "dnf": ["libvirt-daemon-kvm", "qemu-kvm", "edk2-ovmf"],
    "pacman": ["libvirt", "qemu-desktop", "dnsmasq", "edk2-ovmf"],
    "zypper": [
        "libvirt-daemon",
        "libvirt-daemon-qemu",
        "qemu-kvm",
        "qemu-ovmf-x86_64",
    ],
    "brew": [],
}

# Gestionnaires de paquets, dans l'ordre de préférence :
# (clé TOOL_PACKAGES, binaire à détecter, commande d'installation, sudo, refresh)
PKG_MANAGERS: tuple[
    tuple[str, str, list[str], bool, list[str] | None], ...
] = (
    (
        "apt",
        "apt-get",
        ["apt-get", "install", "-y"],
        True,
        ["apt-get", "update"],
    ),
    ("dnf", "dnf", ["dnf", "install", "-y"], True, None),
    (
        "pacman",
        "pacman",
        ["pacman", "-S", "--needed", "--noconfirm"],
        True,
        None,
    ),
    (
        "zypper",
        "zypper",
        ["zypper", "--non-interactive", "install"],
        True,
        None,
    ),
    ("brew", "brew", ["brew", "install"], False, None),
)


def detect_pkg_manager() -> (
    tuple[str, list[str], bool, list[str] | None] | None
):
    """Retourne (clé, cmd d'install, use_sudo, cmd de refresh) ou None."""
    for key, binary, install_cmd, use_sudo, refresh in PKG_MANAGERS:
        if shutil.which(binary):
            return key, install_cmd, use_sudo, refresh
    return None


def missing_tools() -> list[str]:
    """Binaires requis absents du PATH (dont un outil de seed si aucun présent)."""
    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if not any(shutil.which(t) for t in SEED_TOOLS):
        missing.append(SEED_TOOLS[0])  # on installera cloud-localds
    return missing


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Question oui/non. Lit /dev/tty pour rester visible même si stdout est
    redirigé (cas d'un lancement depuis le menu todo)."""
    suffix = " [O/n] " if default else " [o/N] "
    prompt = question + suffix
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(prompt)
            tty.flush()
            ans = tty.readline().strip().lower()
    except OSError:
        try:
            ans = input(prompt).strip().lower()
        except EOFError:
            return default
    if not ans:
        return default
    return ans in ("o", "oui", "y", "yes")


def daemon_missing() -> bool:
    """Vrai si le démon libvirt OU l'émulateur QEMU système est absent."""
    libvirtd = shutil.which("libvirtd") or any(
        os.path.exists(p) for p in ("/usr/sbin/libvirtd", "/usr/bin/libvirtd")
    )
    emulator = (
        shutil.which("qemu-system-x86_64")
        or shutil.which("qemu-system-x86")
        or shutil.which("kvm")
    )
    return not (libvirtd and emulator)


def libvirt_ready(use_sudo: bool) -> bool:
    """Vrai si l'hyperviseur qemu:///system répond (démon libvirt démarré)."""
    if shutil.which("virsh") is None:
        return False
    cmd = (["sudo"] if use_sudo else []) + [
        "virsh",
        "-c",
        "qemu:///system",
        "version",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_libvirt_service(runner: Runner) -> None:
    """S'assure que le démon libvirt tourne ; sinon le démarre puis vérifie."""
    if libvirt_ready(runner.use_sudo):
        return
    if shutil.which("systemctl"):
        print(
            "  Démarrage du démon libvirt"
            " (systemctl enable --now libvirtd)…"
        )
        runner.run(
            ["systemctl", "enable", "--now", "libvirtd"],
            privileged=True,
            check=False,
        )
        runner.run(
            ["systemctl", "start", "libvirtd.socket"],
            privileged=True,
            check=False,
        )
    # Le socket peut mettre un instant à apparaître.
    for _ in range(10):
        if libvirt_ready(runner.use_sudo):
            return
        time.sleep(1)
    sys.exit(
        "Erreur : impossible de se connecter à l'hyperviseur libvirt"
        " (/var/run/libvirt/libvirt-sock).\n"
        "  Le démon libvirtd n'est pas démarré. Essayez :\n"
        "    sudo systemctl enable --now libvirtd\n"
        "  puis vérifiez : sudo virsh -c qemu:///system version"
    )


def ensure_tools(runner: Runner, assume_yes: bool, no_install: bool) -> None:
    """Vérifie outils, démon libvirt et émulateur ; installe/démarre ce qui
    manque, puis vérifie la connexion à l'hyperviseur."""
    missing = missing_tools()
    need_daemon = daemon_missing()

    # Tout est là et l'hyperviseur répond : rien à faire.
    if not missing and not need_daemon and libvirt_ready(runner.use_sudo):
        return

    pm = detect_pkg_manager()
    if pm is None:
        sys.exit(
            "  Gestionnaire de paquets non reconnu "
            "(apt/dnf/pacman/zypper/brew).\n"
            "  Installez manuellement : " + ", ".join(missing)
        )
    pm_key, install_cmd, use_sudo, refresh = pm

    pkg_map = TOOL_PACKAGES[pm_key]
    packages = [pkg_map.get(t, t) for t in missing]
    if need_daemon:
        packages += DAEMON_PACKAGES.get(pm_key, [])
    packages = list(dict.fromkeys(packages))  # dédoublonne, ordre gardé

    if packages:
        label = list(missing)
        if need_daemon:
            label.append("démon libvirt / émulateur QEMU")
        print("  Composants manquants : " + ", ".join(label))

        if no_install:
            sys.exit(
                "  Installation automatique désactivée (--no-install-deps).\n"
                "  Installez manuellement : " + " ".join(packages)
            )

        full_cmd = install_cmd + packages
        printable = " ".join(full_cmd)
        if use_sudo and runner.use_sudo:
            printable = "sudo " + printable

        print(f"  Gestionnaire détecté : {pm_key}")
        print(f"  Commande d'installation : {printable}")

        if not assume_yes and not prompt_yes_no(
            "  Installer ces dépendances maintenant ?"
        ):
            sys.exit(
                "  Installation refusée.\n  Commande manuelle : " + printable
            )

        if refresh:
            runner.run(refresh, privileged=use_sudo, check=False)
        runner.run(full_cmd, privileged=use_sudo)

        still = missing_tools()
        # Repli : si seul l'outil de seed manque encore (le nom du paquet
        # cloud-localds varie selon la distro), tente genisoimage.
        if still == [SEED_TOOLS[0]]:
            alt = pkg_map.get("genisoimage", "genisoimage")
            print(f"  Repli sur {alt} (autre outil de seed cloud-init)…")
            runner.run(install_cmd + [alt], privileged=use_sudo, check=False)
            still = missing_tools()
        if still:
            sys.exit(
                "  Outils toujours absents après installation : "
                + ", ".join(still)
                + f"\n  Essayez manuellement : {printable}"
            )
        print("  Dépendances installées avec succès.")

    # Démarre le démon (si nécessaire) et vérifie l'accès à l'hyperviseur.
    ensure_libvirt_service(runner)


# --------------------------------------------------------------------------- #
# Étapes
# --------------------------------------------------------------------------- #
# Délai (s) par opération réseau : au-delà, on abandonne le miroir courant.
# Sans lui, un miroir injoignable ferait pendre le téléchargement à l'infini.
DOWNLOAD_TIMEOUT = 30


def _download_one(url: str, tmp: Path, timeout: int) -> None:
    """Télécharge url -> tmp en streaming, avec timeout et barre de %.
    Lève une exception en cas d'échec réseau (miroir suivant à essayer)."""
    is_tty = sys.stdout.isatty()
    last_pct = -1
    req = urllib.request.Request(
        url, headers={"User-Agent": "erplibre-qemu-deploy"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total <= 0:
                    continue
                pct = min(100, done * 100 // total)
                if pct == last_pct:
                    continue
                last_pct = pct
                # TTY : une ligne réécrite (\r) ; sinon (capturé par le menu
                # todo) au plus 101 lignes, jamais de flot infini.
                if is_tty:
                    print(f"\r    {pct:3d}%", end="", flush=True)
                else:
                    print(f"    {pct:3d}%", flush=True)
    if is_tty:
        print()


def download_image(
    urls, dest: Path, dry_run: bool, timeout: int = DOWNLOAD_TIMEOUT
) -> None:
    """Télécharge l'image (essaie chaque miroir dans l'ordre) si absente du
    cache. Échoue proprement — jamais de blocage infini — grâce au timeout."""
    if isinstance(urls, str):
        urls = [urls]
    if dest.exists() and dest.stat().st_size > 0:
        size_mb = dest.stat().st_size / 1024 / 1024
        print(
            f"  Image déjà présente ({size_mb:.0f} Mo), téléchargement"
            f" ignoré : {dest}",
            flush=True,
        )
        return
    if dry_run:
        print(f"  [dry-run] téléchargement {urls[0]} -> {dest}", flush=True)
        return

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        sys.exit(
            f"\nPermission refusée pour écrire dans {dest.parent}.\n"
            "  Relancez avec sudo, ou choisissez --image-dir vers un dossier"
            " accessible en écriture."
        )
    tmp = dest.with_suffix(dest.suffix + ".part")
    errors = []
    had_404 = False
    for i, url in enumerate(urls, 1):
        tag = "" if len(urls) == 1 else f" (miroir {i}/{len(urls)})"
        print(f"  Téléchargement{tag} : {url}", flush=True)
        try:
            _download_one(url, tmp, timeout)
            tmp.replace(dest)
            return
        except urllib.error.HTTPError as exc:  # image absente sur ce miroir
            tmp.unlink(missing_ok=True)
            had_404 = had_404 or exc.code == 404
            print(f"\n  Échec : HTTP {exc.code}", flush=True)
            errors.append(f"{url} -> HTTP {exc.code}")
        except Exception as exc:  # réseau/timeout : miroir suivant
            tmp.unlink(missing_ok=True)
            print(f"\n  Échec : {exc}", flush=True)
            errors.append(f"{url} -> {exc}")
    hint = (
        "\n  Image introuvable (404) : cette version est probablement EOL et"
        " a été retirée du miroir. Choisissez une version LTS encore"
        " supportée (voir --list-images)."
        if had_404
        else "\n  Vérifiez la connectivité (IPv6 ?), réessayez plus tard, ou"
        " fournissez un chemin d'image local en argument positionnel."
    )
    sys.exit(
        "\nÉchec du téléchargement depuis tous les miroirs :\n  "
        + "\n  ".join(errors)
        + hint
    )


def verify_sha256(url: str, image: Path, dry_run: bool) -> None:
    """Vérifie l'empreinte via le SHA256SUMS publié dans le même répertoire."""
    if dry_run:
        print("  [dry-run] vérification SHA256 ignorée")
        return
    sums_url = url.rsplit("/", 1)[0] + "/SHA256SUMS"
    filename = url.rsplit("/", 1)[1]
    print(f"  Vérification SHA256 via {sums_url}")
    try:
        with urllib.request.urlopen(  # noqa: S310
            sums_url, timeout=DOWNLOAD_TIMEOUT
        ) as resp:
            sums = resp.read().decode()
    except Exception as exc:  # pragma: no cover
        sys.exit(f"Impossible de récupérer SHA256SUMS : {exc}")

    expected = next(
        (
            line.split()[0]
            for line in sums.splitlines()
            if line.strip().endswith(filename)
        ),
        None,
    )
    if expected is None:
        sys.exit(f"Empreinte introuvable pour {filename} dans SHA256SUMS")

    h = hashlib.sha256()
    with image.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != expected:
        image.unlink(
            missing_ok=True
        )  # évite la réutilisation du cache corrompu
        sys.exit(
            f"SHA256 NON conforme ! Image supprimée : {image}\n"
            f"  attendu : {expected}\n  obtenu  : {h.hexdigest()}"
        )
    print("  SHA256 conforme.")


def hash_password(plain: str) -> str:
    """Hash SHA-512 crypt ($6$...) via crypt (< 3.13) ou openssl en repli."""
    try:
        with warnings.catch_warnings():
            # crypt est déprécié (retiré en 3.13) : on masque l'avertissement,
            # le repli openssl couvre les versions récentes de Python.
            warnings.simplefilter("ignore", DeprecationWarning)
            import crypt

        return crypt.crypt(plain, crypt.mksalt(crypt.METHOD_SHA512))
    except (ImportError, AttributeError):
        need_tool("openssl")
        out = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=plain + "\n",
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()


def build_cloud_config(
    args: argparse.Namespace, pw_hash: str | None, ssh_keys: list[str]
) -> str:
    """Construit le contenu #cloud-config (user-data)."""
    lines: list[str] = ["#cloud-config", f"hostname: {args.hostname}"]

    user_block = [
        "users:",
        f"  - name: {args.user}",
        "    sudo: ALL=(ALL) NOPASSWD:ALL",
        # « sudo » existe sur Debian ET Ubuntu ; « admin » n'existe PAS sur
        # Debian -> useradd -G ...,admin échoue et l'utilisateur n'est jamais
        # créé (login/clé SSH KO). C'était la cause du « Debian ne marche pas ».
        "    groups: users, sudo",
        "    shell: /bin/bash",
        "    lock_passwd: false" if pw_hash else "    lock_passwd: true",
    ]
    if pw_hash:
        user_block.append(f'    passwd: "{pw_hash}"')
    if ssh_keys:
        user_block.append("    ssh_authorized_keys:")
        user_block += [f"      - {k}" for k in ssh_keys]
    lines += user_block

    lines.append(f"ssh_pwauth: {'true' if pw_hash else 'false'}")
    lines.append(f"locale: {args.locale}")
    lines += [
        "keyboard:",
        f"  layout: {args.keyboard_layout}",
        f"  variant: {args.keyboard_variant}",
    ]
    # apt update/upgrade désactivés par défaut : sur un réseau lent/instable
    # ils font pendre cloud-init au 1er boot (et retardent la dispo SSH). SSH
    # est déjà présent dans les images cloud ; on l'active via runcmd sans apt.
    # --apt-update réactive apt update (+ upgrade, sauf --no-upgrade).
    do_update = args.apt_update
    do_upgrade = args.apt_update and not args.no_upgrade
    lines.append(f"package_update: {'true' if do_update else 'false'}")
    lines.append(f"package_upgrade: {'true' if do_upgrade else 'false'}")

    # openssh-server : garantit un serveur SSH sur toutes les distros (les
    # images Debian genericcloud notamment ne l'ont pas toujours activé).
    packages = ["qemu-guest-agent", "openssh-server", *args.package]
    lines.append("packages:")
    lines += [
        f"  - {p}" for p in dict.fromkeys(packages)
    ]  # dédoublonne, ordre gardé
    # Active et démarre SSH quel que soit le nom du service (ssh sur
    # Debian/Ubuntu, sshd sur Fedora) — sans quoi la VM peut booter sans SSH.
    lines += [
        "runcmd:",
        "  - systemctl enable --now ssh 2>/dev/null"
        " || systemctl enable --now sshd 2>/dev/null || true",
    ]
    return "\n".join(lines) + "\n"


# network-config (cloud-init v2) : DHCP sur toute interface « e* ». Les images
# Debian genericcloud ne configurent pas toujours le réseau sans ça (le NIC
# reste down -> pas d'IP), contrairement à Ubuntu. Inoffensif pour Ubuntu.
NETWORK_CONFIG = (
    "version: 2\n"
    "ethernets:\n"
    "  primary:\n"
    "    match:\n"
    '      name: "e*"\n'
    "    dhcp4: true\n"
    "    dhcp6: false\n"
)


def build_seed(
    cloud_cfg: str, hostname: str, seed_dest: Path, runner: Runner
) -> None:
    """Génère le seed.iso (cidata) et le copie vers seed_dest."""
    meta_data = f"instance-id: {hostname}\nlocal-hostname: {hostname}\n"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ud = tmp_path / "user-data"
        md = tmp_path / "meta-data"
        nc = tmp_path / "network-config"
        local_iso = tmp_path / "seed.iso"

        if runner.dry_run:
            print("  [dry-run] user-data qui serait généré :")
            print(textwrap.indent(cloud_cfg, "      "))
            print("  [dry-run] network-config :")
            print(textwrap.indent(NETWORK_CONFIG, "      "))
        else:
            ud.write_text(cloud_cfg)
            md.write_text(meta_data)
            nc.write_text(NETWORK_CONFIG)

        if runner.dry_run or shutil.which("cloud-localds"):
            runner.run(
                [
                    "cloud-localds",
                    "--network-config",
                    str(nc),
                    str(local_iso),
                    str(ud),
                    str(md),
                ]
            )
        else:
            need_tool("genisoimage")
            runner.run(
                [
                    "genisoimage",
                    "-output",
                    str(local_iso),
                    "-volid",
                    "cidata",
                    "-joliet",
                    "-rock",
                    str(ud),
                    str(md),
                    str(nc),
                ]
            )

        (
            seed_dest.parent.mkdir(parents=True, exist_ok=True)
            if not runner.dry_run
            else None
        )
        runner.run(["cp", str(local_iso), str(seed_dest)], privileged=True)


def prepare_disk(
    image: Path, disk: Path, size: str, runner: Runner, force: bool
) -> None:
    """Convertit l'image cloud en qcow2 de travail puis redimensionne."""
    if disk.exists() and not force:
        sys.exit(
            f"Le disque {disk} existe déjà. Utilisez --force pour l'écraser."
        )
    runner.run(
        [
            "qemu-img",
            "convert",
            "-f",
            "qcow2",
            "-O",
            "qcow2",
            str(image),
            str(disk),
        ],
        privileged=True,
    )
    runner.run(["qemu-img", "resize", str(disk), size], privileged=True)


def network_name(network_arg: str) -> str | None:
    """Extrait NAME de « network=NAME,... » ; None si c'est un bridge, etc."""
    for part in network_arg.split(","):
        if part.strip().startswith("network="):
            return part.split("=", 1)[1].strip()
    return None


def network_state(name: str, use_sudo: bool) -> tuple[bool, bool]:
    """(actif, autostart) d'un réseau libvirt, via « virsh net-info »."""
    cmd = (["sudo"] if use_sudo else []) + ["virsh", "net-info", name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return (False, False)
    active = bool(re.search(r"Active:\s*yes", res.stdout, re.IGNORECASE))
    autostart = bool(re.search(r"Autostart:\s*yes", res.stdout, re.IGNORECASE))
    return (active, autostart)


def ensure_network(name: str | None, runner: Runner) -> None:
    """Active le réseau libvirt si besoin. On vérifie d'abord son état pour
    éviter le faux « error: network is already active » de virsh quand il
    tourne déjà (message purement bruyant, sans conséquence)."""
    if not name:
        return
    if runner.dry_run:
        print(f"  [dry-run] réseau libvirt '{name}' activé si nécessaire")
        runner.run(["virsh", "net-start", name], privileged=True, check=False)
        runner.run(
            ["virsh", "net-autostart", name], privileged=True, check=False
        )
        return
    active, autostart = network_state(name, runner.use_sudo)
    if active and autostart:
        print(f"  Réseau libvirt '{name}' déjà actif.")
        return
    print(f"  Configuration du réseau libvirt '{name}'…")
    if not active:
        runner.run(["virsh", "net-start", name], privileged=True, check=False)
    if not autostart:
        runner.run(
            ["virsh", "net-autostart", name], privileged=True, check=False
        )


def virt_install(
    args: argparse.Namespace,
    disk: Path,
    seed: Path,
    osinfo: str,
    runner: Runner,
) -> None:
    cmd = [
        "virt-install",
        "--name",
        args.name,
        "--memory",
        str(args.memory),
        "--vcpus",
        str(args.vcpus),
        "--import",
        "--disk",
        f"path={disk},format=qcow2,bus=virtio",
        # Seed cloud-init attaché comme DISQUE virtio en lecture seule (et non
        # en CD-ROM) : le pilote virtio-blk est dans l'initramfs, donc le
        # volume « cidata » est visible dès init-local et cloud-init le lit.
        # En CD-ROM, l'initramfs Debian ne charge pas sr_mod à temps -> le
        # seed n'est pas vu et rien ne s'applique (Ubuntu, lui, tolère le CD).
        "--disk",
        f"path={seed},readonly=on,bus=virtio",
        "--osinfo",
        osinfo,
        "--network",
        args.network,
        "--graphics",
        args.graphics,
        "--console",
        "pty,target_type=serial",
    ]
    # Boot UEFI par défaut : Debian 13 (trixie) et les images cloud récentes
    # n'embarquent plus le chargeur BIOS/GRUB-pc et partent en boucle
    # « Booting... » en SeaBIOS. UEFI (OVMF) fonctionne pour Ubuntu/Debian/
    # Fedora. --bios force l'ancien BIOS si OVMF est indisponible.
    # Secure Boot DÉSACTIVÉ : le chargeur d'Arch (GRUB) n'est pas signé et
    # OVMF Secure Boot le refuse (« Access Denied » -> pas de boot). Ubuntu/
    # Debian/Fedora bootent aussi sans Secure Boot (shim signé non requis).
    if not args.bios:
        cmd += [
            "--boot",
            "uefi,firmware.feature0.name=secure-boot,"
            "firmware.feature0.enabled=no",
        ]
    if not args.attach_console:
        cmd.append("--noautoconsole")
    runner.run(cmd, privileged=True)


def wait_for_ip(name: str, use_sudo: bool, timeout: int) -> str | None:
    """Interroge les baux DHCP libvirt jusqu'à obtenir l'IPv4 de la VM."""
    base = (["sudo"] if use_sudo else []) + [
        "virsh",
        "domifaddr",
        name,
        "--source",
        "lease",
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = subprocess.run(base, capture_output=True, text=True)
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", res.stdout)
        if m:
            return m.group(1)
        time.sleep(3)
    return None


def ssh_command(user: str, ip: str, has_key: bool) -> str:
    """Commande SSH adaptée : clé -> connexion simple ; mot de passe seul ->
    force le mot de passe pour éviter « Too many authentication failures »."""
    if has_key:
        return f"ssh {user}@{ip}"
    return (
        f"ssh -o IdentitiesOnly=yes -o PreferredAuthentications=password "
        f"{user}@{ip}"
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    versions_help = "\n".join(
        f"    {distro:<7} {default:<7} (défaut)   versions : "
        + ", ".join(versions)
        for distro, (versions, default) in DISTROS.items()
    )
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        epilog="Distros et versions (--distro / --version), specs via "
        "--list-images :\n" + versions_help,
    )
    p.add_argument(
        "image_path",
        type=Path,
        nargs="?",
        default=None,
        help="Chemin de cache de l'image cloud. Optionnel : si absent, il est "
        "déduit de --distro/--version/--codename + --arch dans --image-dir. "
        "Si le fichier existe, il n'est PAS re-téléchargé.",
    )

    g_img = p.add_argument_group("Image")
    g_img.add_argument(
        "--distro",
        default="ubuntu",
        choices=DISTROS,
        help="Distribution : ubuntu, debian ou fedora (défaut : ubuntu).",
    )
    g_img.add_argument(
        "--version",
        default=None,
        help="Version de la distro (défaut : la version par défaut de la "
        "distro). Voir --list-images pour la liste complète.",
    )
    g_img.add_argument(
        "--codename",
        help="Force le nom de code / la release (surcharge --version).",
    )
    g_img.add_argument(
        "--arch",
        default="amd64",
        help="Architecture de l'image (défaut : amd64).",
    )
    g_img.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help="Répertoire de cache des images cloud quand image_path est "
        f"omis (défaut : {DEFAULT_IMAGE_DIR}).",
    )
    g_img.add_argument(
        "--verify",
        action="store_true",
        help="Vérifie l'empreinte SHA256 après téléchargement (recommandé).",
    )

    g_vm = p.add_argument_group("VM")
    g_vm.add_argument(
        "--name",
        help="Nom de la VM (virsh). Requis pour déployer ; inutile avec "
        "--download-only.",
    )
    g_vm.add_argument(
        "--hostname", help="Nom d'hôte interne (défaut : --name)."
    )
    g_vm.add_argument(
        "--memory",
        type=int,
        default=None,
        help="RAM en Mo (défaut : minimum requis par la version choisie, "
        "voir --list-images).",
    )
    g_vm.add_argument(
        "--vcpus", type=int, default=2, help="Nombre de vCPU (défaut : 2)."
    )
    g_vm.add_argument(
        "--disk-size",
        default=None,
        help="Taille du disque virtuel, ex. 120G (défaut : minimum requis "
        "par la version choisie, voir --list-images).",
    )
    g_vm.add_argument(
        "--disk-dir",
        type=Path,
        default=Path("/var/lib/libvirt/images"),
        help="Répertoire du qcow2 de travail (défaut : /var/lib/libvirt/images).",
    )
    g_vm.add_argument(
        "--seed-dir",
        type=Path,
        default=Path("/var/lib/libvirt/images/iso"),
        help="Répertoire du seed.iso (défaut : .../images/iso).",
    )
    g_vm.add_argument(
        "--network",
        default="network=default,model=virtio",
        help="Argument --network de virt-install.",
    )
    g_vm.add_argument(
        "--graphics",
        default="none",
        help="Argument --graphics (défaut : none).",
    )
    g_vm.add_argument(
        "--osinfo", help="Force la valeur --osinfo (sinon déduite)."
    )
    g_vm.add_argument(
        "--attach-console",
        action="store_true",
        help="Attache la console série (sinon --noautoconsole).",
    )
    g_vm.add_argument(
        "--bios",
        action="store_true",
        help="Force l'amorçage BIOS hérité au lieu d'UEFI (par défaut UEFI ; "
        "n'utiliser que si le firmware OVMF est absent).",
    )

    g_cloud = p.add_argument_group("cloud-init")
    g_cloud.add_argument(
        "--user",
        default="erplibre",
        help="Utilisateur créé (défaut : erplibre).",
    )
    g_cloud.add_argument(
        "--password", help="Mot de passe en clair (déconseillé : visible)."
    )
    g_cloud.add_argument(
        "--ask-password",
        action="store_true",
        help="Demande le mot de passe de façon interactive (sûr).",
    )
    g_cloud.add_argument(
        "--password-hash",
        help="Empreinte $6$... déjà calculée (openssl passwd -6).",
    )
    g_cloud.add_argument(
        "--ssh-key",
        action="append",
        default=[],
        metavar="FICHIER",
        help="Fichier de clé publique SSH à injecter (répétable).",
    )
    g_cloud.add_argument(
        "--locale",
        default="fr_CA.UTF-8",
        help="Locale (défaut : fr_CA.UTF-8).",
    )
    g_cloud.add_argument(
        "--keyboard-layout",
        default="ca",
        help="Disposition clavier (défaut : ca).",
    )
    g_cloud.add_argument(
        "--keyboard-variant",
        default="multix",
        help="Variante clavier (défaut : multix).",
    )
    g_cloud.add_argument(
        "--package",
        action="append",
        default=[],
        metavar="PKG",
        help="Paquet APT additionnel (répétable).",
    )
    g_cloud.add_argument(
        "--no-upgrade",
        action="store_true",
        help="N'exécute pas package_upgrade au premier boot.",
    )
    g_cloud.add_argument(
        "--apt-update",
        action="store_true",
        help="Exécute « apt update » au 1er boot (package_update). Désactivé "
        "par défaut : évite que cloud-init se bloque sur un miroir lent/"
        "injoignable (SSH est déjà présent dans les images cloud).",
    )

    g_run = p.add_argument_group("Exécution")
    g_run.add_argument(
        "--no-sudo",
        action="store_true",
        help="N'utilise pas sudo pour les étapes privilégiées.",
    )
    g_run.add_argument(
        "--force",
        action="store_true",
        help="Écrase le qcow2 de travail existant.",
    )
    g_run.add_argument(
        "--no-wait-ip",
        action="store_true",
        help="N'attend pas l'attribution de l'IP à la fin.",
    )
    g_run.add_argument(
        "--ip-timeout",
        type=int,
        default=90,
        metavar="SEC",
        help="Délai max d'attente de l'IP DHCP (défaut : 90 s).",
    )
    g_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les commandes et le user-data sans rien exécuter.",
    )
    g_run.add_argument(
        "--download-only",
        action="store_true",
        help="Télécharge (et vérifie si --verify) l'image cloud puis quitte, "
        "sans créer de VM. --name n'est pas requis.",
    )
    g_run.add_argument(
        "-y",
        "--assume-yes",
        action="store_true",
        help="Accepte automatiquement l'installation des dépendances manquantes.",
    )
    g_run.add_argument(
        "--no-install-deps",
        action="store_true",
        help="N'installe jamais les dépendances manquantes (échoue si absentes).",
    )
    g_run.add_argument(
        "--list-images",
        action="store_true",
        help="Liste les distros/versions disponibles et leurs specs, "
        "puis quitte.",
    )
    return p


def resolve_password(args: argparse.Namespace) -> str | None:
    if args.password_hash:
        return args.password_hash
    if args.ask_password:
        pw = getpass.getpass("Mot de passe pour l'utilisateur : ")
        if pw != getpass.getpass("Confirmer : "):
            sys.exit("Les mots de passe ne correspondent pas.")
        return hash_password(pw)
    if args.password:
        return hash_password(args.password)
    return None


def load_ssh_keys(paths: list[str]) -> list[str]:
    keys: list[str] = []
    for path in paths:
        p = Path(path).expanduser()
        if not p.exists():
            sys.exit(f"Clé SSH introuvable : {p}")
        keys.append(p.read_text().strip())
    return keys


def main() -> None:
    # Sortie ligne par ligne même quand stdout est un tube (menu todo) : sinon
    # les en-têtes restent bufferisés et le déploiement paraît « gelé ».
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    args = build_parser().parse_args()

    if args.list_images:
        list_images()
        return

    versions, default_version = DISTROS[args.distro]
    if args.version is None:
        args.version = default_version
    if args.version not in versions:
        sys.exit(
            f"Version {args.version!r} inconnue pour {args.distro}. "
            f"Choix : {', '.join(versions)} (voir --list-images)."
        )
    code, default_osinfo, min_ram, min_disk = versions[args.version]
    if args.codename:
        code = args.codename
    osinfo = args.osinfo or default_osinfo
    # Dimensionnement par défaut = minimum requis par la version (libosinfo).
    if args.memory is None:
        args.memory = min_ram
    if args.disk_size is None:
        args.disk_size = min_disk
    # Un nombre nu (« 30 ») serait pris pour des OCTETS par qemu-img et ferait
    # échouer le resize : on suppose des Go par défaut (« 30 » -> « 30G »).
    if re.fullmatch(r"\d+", str(args.disk_size)):
        args.disk_size = f"{args.disk_size}G"
    urls = image_candidates(
        args.distro, code, args.arch, args.version, args.dry_run
    )
    url = urls[0]
    # --verify s'appuie sur un SHA256SUMS style Ubuntu ; Debian/Fedora
    # publient des sommes dans un autre format -> on saute proprement.
    do_verify = args.verify and args.distro == "ubuntu"
    if args.verify and not do_verify:
        print(
            f"  Note : --verify n'est pris en charge que pour ubuntu "
            f"(ignoré pour {args.distro})."
        )

    # Chemin de l'image : déduit automatiquement si non fourni.
    if args.image_path is None:
        args.image_path = args.image_dir / default_image_name(
            args.distro, code, args.arch, args.version
        )

    runner = Runner(
        use_sudo=not args.no_sudo and os.geteuid() != 0, dry_run=args.dry_run
    )

    # -- Mode téléchargement seul : aucun outil ni VM requis. --------------
    if args.download_only:
        print(
            f"\n== Téléchargement image cloud "
            f"({args.distro} {args.version} / {code}) =="
        )
        print(f"  Destination : {args.image_path}")
        download_image(urls, args.image_path, args.dry_run)
        if do_verify:
            verify_sha256(url, args.image_path, args.dry_run)
        print("\nTerminé (téléchargement seul).")
        return

    # -- Déploiement complet -----------------------------------------------
    if not args.name:
        sys.exit(
            "Erreur : --name est requis pour déployer une VM "
            "(ou utilisez --download-only)."
        )
    args.hostname = args.hostname or args.name

    pw_hash = resolve_password(args)
    ssh_keys = load_ssh_keys(args.ssh_key)
    if not pw_hash and not ssh_keys:
        print(
            "ATTENTION : ni mot de passe ni clé SSH -> connexion impossible à la VM.\n"
            "            Ajoutez --ssh-key, --ask-password ou --password-hash.\n",
            file=sys.stderr,
        )

    disk = args.disk_dir / f"{args.name}.qcow2"
    seed = args.seed_dir / f"{args.name}-seed.iso"

    if not args.dry_run:
        ensure_tools(runner, args.assume_yes, args.no_install_deps)

    print(f"\n== 1/5 Image cloud ({args.distro} {args.version} / {code}) ==")
    download_image(urls, args.image_path, args.dry_run)
    if do_verify:
        verify_sha256(url, args.image_path, args.dry_run)

    print(f"\n== 2-3/5 Disque de travail {disk} ({args.disk_size}) ==")
    prepare_disk(args.image_path, disk, args.disk_size, runner, args.force)

    print(f"\n== 4/5 Seed cloud-init {seed} ==")
    cloud_cfg = build_cloud_config(args, pw_hash, ssh_keys)
    build_seed(cloud_cfg, args.hostname, seed, runner)

    resolved_osinfo = osinfo_arg(osinfo, args.distro)
    print(f"\n== 5/5 virt-install (--osinfo {resolved_osinfo}) ==")
    ensure_network(network_name(args.network), runner)
    virt_install(args, disk, seed, resolved_osinfo, runner)

    has_key = bool(ssh_keys)
    print("\nTerminé. Suivi :")
    print("  virsh list --all")
    print(f"  virsh console {args.name}   # Ctrl+] pour quitter")

    if args.dry_run:
        print("\n  Connexion SSH (IP attribuée au 1er boot) :")
        print(f"    {ssh_command(args.user, '<IP>', has_key)}")
        return
    if args.no_wait_ip:
        print(
            f"\n  Récupérer l'IP : virsh domifaddr {args.name} --source lease"
        )
        return

    print(f"\n  Attente de l'IP (bail DHCP, max {args.ip_timeout} s)…")
    ip = wait_for_ip(args.name, runner.use_sudo, args.ip_timeout)
    if ip:
        print(f"  IP : {ip}")
        print("  Connexion SSH :")
        print(f"    {ssh_command(args.user, ip, has_key)}")
    else:
        print("  IP non obtenue dans le délai (cloud-init encore en cours ?).")
        print(f"  Réessayez : virsh domifaddr {args.name} --source lease")


if __name__ == "__main__":
    main()
