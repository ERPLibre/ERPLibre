#!/usr/bin/env python3
"""Déploiement rapide de VM Ubuntu (cloud-image) avec qemu-img + cloud-init + virt-install.

Reprend le workflow des notes :
  1. Télécharge l'image cloud Ubuntu (si absente du cache -> pas de double téléchargement).
  2. Convertit/copie l'image en un qcow2 de travail dédié à la VM.
  3. Redimensionne le disque virtuel.
  4. Génère user-data / meta-data et construit le seed.iso (cidata).
  5. Lance virt-install en important le disque + le seed en CD-ROM.

Exemples
--------
    # Le plus simple : image téléchargée automatiquement (chemin déduit de
    # --version, mis en cache dans /var/lib/libvirt/images/iso) et outils
    # manquants installés après confirmation.
    sudo ./script/qemu/deploy_qemu.py --name test-vm --version 24.04 \\
        --ssh-key ~/.ssh/id_ed25519.pub

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
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# Table des versions Ubuntu -> (nom de code, valeur --osinfo/libosinfo)
# Le nom de code sert à construire l'URL de l'image cloud. Les valeurs LTS sont
# stables ; --codename et --osinfo permettent de surcharger si la table vieillit.
# --------------------------------------------------------------------------- #
UBUNTU_VERSIONS: dict[str, tuple[str, str]] = {
    "20.04": ("focal", "ubuntu20.04"),
    "22.04": ("jammy", "ubuntu22.04"),
    "24.04": ("noble", "ubuntu24.04"),
    "24.10": ("oracular", "ubuntu24.10"),
    "25.04": ("plucky", "ubuntu25.04"),
    "25.10": ("questing", "ubuntu25.10"),
    # "26.04": ("resolute", "ubuntu26.04"),
}

CLOUD_IMG_BASE = "https://cloud-images.ubuntu.com"

# Répertoire de cache par défaut des images cloud (cohérent avec --disk-dir /
# --seed-dir). L'écriture y nécessite root : le déploiement tourne de toute
# façon sous sudo (virt-install). Surchargez avec --image-dir au besoin.
DEFAULT_IMAGE_DIR = Path("/var/lib/libvirt/images/iso")


def image_url(codename: str, arch: str) -> str:
    """URL de l'image cloud « current » pour un nom de code + architecture."""
    return f"{CLOUD_IMG_BASE}/{codename}/current/{codename}-server-cloudimg-{arch}.img"


def default_image_name(codename: str, arch: str) -> str:
    """Nom de fichier local dérivé du nom de code + architecture."""
    return f"{codename}-server-cloudimg-{arch}.img"


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
DAEMON_PACKAGES: dict[str, list[str]] = {
    "apt": ["libvirt-daemon-system", "qemu-system-x86"],
    "dnf": ["libvirt-daemon-kvm", "qemu-kvm"],
    "pacman": ["libvirt", "qemu-desktop", "dnsmasq"],
    "zypper": ["libvirt-daemon", "libvirt-daemon-qemu", "qemu-kvm"],
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
def download_image(url: str, dest: Path, dry_run: bool) -> None:
    """Télécharge l'image seulement si elle n'existe pas déjà (cache)."""
    if dest.exists() and dest.stat().st_size > 0:
        size_mb = dest.stat().st_size / 1024 / 1024
        print(
            f"  Image déjà présente ({size_mb:.0f} Mo), téléchargement ignoré : {dest}"
        )
        return
    if dry_run:
        print(f"  [dry-run] téléchargement {url} -> {dest}")
        return

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        sys.exit(
            f"\nPermission refusée pour écrire dans {dest.parent}.\n"
            "  Relancez avec sudo, ou choisissez --image-dir vers un dossier"
            " accessible en écriture."
        )
    print(f"  Téléchargement {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")

    def _progress(block_num: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, block_num * block_size * 100 // total)
            print(f"\r    {pct:3d}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(
            url, tmp, _progress
        )  # noqa: S310 (URL contrôlée)
    except Exception as exc:  # pragma: no cover - dépend du réseau
        tmp.unlink(missing_ok=True)
        sys.exit(f"\nÉchec du téléchargement : {exc}")
    print()
    tmp.replace(dest)


def verify_sha256(url: str, image: Path, dry_run: bool) -> None:
    """Vérifie l'empreinte via le SHA256SUMS publié dans le même répertoire."""
    if dry_run:
        print("  [dry-run] vérification SHA256 ignorée")
        return
    sums_url = url.rsplit("/", 1)[0] + "/SHA256SUMS"
    filename = url.rsplit("/", 1)[1]
    print(f"  Vérification SHA256 via {sums_url}")
    try:
        with urllib.request.urlopen(sums_url) as resp:  # noqa: S310
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
        import crypt  # supprimé en Python 3.13

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
        "    groups: users, admin",
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
    lines.append("package_update: true")
    lines.append(f"package_upgrade: {'false' if args.no_upgrade else 'true'}")

    packages = ["qemu-guest-agent", *args.package]
    lines.append("packages:")
    lines += [
        f"  - {p}" for p in dict.fromkeys(packages)
    ]  # dédoublonne, ordre gardé
    return "\n".join(lines) + "\n"


def build_seed(
    cloud_cfg: str, hostname: str, seed_dest: Path, runner: Runner
) -> None:
    """Génère le seed.iso (cidata) et le copie vers seed_dest."""
    meta_data = f"instance-id: {hostname}\nlocal-hostname: {hostname}\n"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ud = tmp_path / "user-data"
        md = tmp_path / "meta-data"
        local_iso = tmp_path / "seed.iso"

        if runner.dry_run:
            print("  [dry-run] user-data qui serait généré :")
            print(textwrap.indent(cloud_cfg, "      "))
        else:
            ud.write_text(cloud_cfg)
            md.write_text(meta_data)

        if runner.dry_run or shutil.which("cloud-localds"):
            runner.run(["cloud-localds", str(local_iso), str(ud), str(md)])
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


def ensure_network(name: str | None, runner: Runner) -> None:
    """Active le réseau libvirt (idempotent : tolère « déjà actif »)."""
    if not name:
        return
    print(f"  Activation du réseau libvirt '{name}' (si nécessaire)")
    runner.run(["virsh", "net-start", name], privileged=True, check=False)
    runner.run(["virsh", "net-autostart", name], privileged=True, check=False)


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
        "--disk",
        f"path={seed},device=cdrom",
        "--osinfo",
        osinfo,
        "--network",
        args.network,
        "--graphics",
        args.graphics,
        "--console",
        "pty,target_type=serial",
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
        f"    {v:<7} {code:<10} {image_url(code, 'amd64')}"
        for v, (code, _osinfo) in UBUNTU_VERSIONS.items()
    )
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        epilog="Versions Ubuntu disponibles (--version) et URL de l'image cloud :\n"
        + versions_help,
    )
    p.add_argument(
        "image_path",
        type=Path,
        nargs="?",
        default=None,
        help="Chemin de cache de l'image cloud (.img). Optionnel : si absent, "
        "il est déduit de --version/--codename + --arch dans --image-dir. "
        "Si le fichier existe, il n'est PAS re-téléchargé.",
    )

    g_img = p.add_argument_group("Image")
    g_img.add_argument(
        "--version",
        default="24.04",
        choices=UBUNTU_VERSIONS,
        help="Version Ubuntu (défaut : 24.04). Voir la liste ci-dessous.",
    )
    g_img.add_argument(
        "--codename", help="Force le nom de code (surcharge --version)."
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
        "--memory", type=int, default=8192, help="RAM en Mo (défaut : 8192)."
    )
    g_vm.add_argument(
        "--vcpus", type=int, default=4, help="Nombre de vCPU (défaut : 4)."
    )
    g_vm.add_argument(
        "--disk-size",
        default="20G",
        help="Taille du disque virtuel, ex. 120G (défaut : 20G).",
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
    args = build_parser().parse_args()

    codename, default_osinfo = UBUNTU_VERSIONS[args.version]
    if args.codename:
        codename = args.codename
    osinfo = args.osinfo or default_osinfo
    url = image_url(codename, args.arch)

    # Chemin de l'image : déduit automatiquement si non fourni.
    if args.image_path is None:
        args.image_path = args.image_dir / default_image_name(
            codename, args.arch
        )

    runner = Runner(
        use_sudo=not args.no_sudo and os.geteuid() != 0, dry_run=args.dry_run
    )

    # -- Mode téléchargement seul : aucun outil ni VM requis. --------------
    if args.download_only:
        print(
            f"\n== Téléchargement image cloud ({args.version} / {codename}) =="
        )
        print(f"  Destination : {args.image_path}")
        download_image(url, args.image_path, args.dry_run)
        if args.verify:
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

    print(f"\n== 1/5 Image cloud ({args.version} / {codename}) ==")
    download_image(url, args.image_path, args.dry_run)
    if args.verify:
        verify_sha256(url, args.image_path, args.dry_run)

    print(f"\n== 2-3/5 Disque de travail {disk} ({args.disk_size}) ==")
    prepare_disk(args.image_path, disk, args.disk_size, runner, args.force)

    print(f"\n== 4/5 Seed cloud-init {seed} ==")
    cloud_cfg = build_cloud_config(args, pw_hash, ssh_keys)
    build_seed(cloud_cfg, args.hostname, seed, runner)

    print(f"\n== 5/5 virt-install (--osinfo {osinfo}) ==")
    ensure_network(network_name(args.network), runner)
    virt_install(args, disk, seed, osinfo, runner)

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
