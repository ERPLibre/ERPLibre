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
    # Déploiement minimal (clé SSH, aucun mot de passe)
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
import shutil
import subprocess
import sys
import tempfile
import textwrap
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
}

CLOUD_IMG_BASE = "https://cloud-images.ubuntu.com"


def image_url(codename: str, arch: str) -> str:
    """URL de l'image cloud « current » pour un nom de code + architecture."""
    return f"{CLOUD_IMG_BASE}/{codename}/current/{codename}-server-cloudimg-{arch}.img"


# --------------------------------------------------------------------------- #
# Utilitaires d'exécution
# --------------------------------------------------------------------------- #
class Runner:
    """Exécute (ou affiche, en dry-run) les commandes, avec sudo au besoin."""

    def __init__(self, use_sudo: bool, dry_run: bool) -> None:
        self.use_sudo = use_sudo
        self.dry_run = dry_run

    def run(self, cmd: list[str], *, privileged: bool = False) -> None:
        if privileged and self.use_sudo:
            cmd = ["sudo", *cmd]
        printable = " ".join(cmd)
        if self.dry_run:
            print(f"  [dry-run] {printable}")
            return
        print(f"  $ {printable}")
        subprocess.run(cmd, check=True)


def need_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"Erreur : outil requis introuvable dans le PATH : {name!r}")


# --------------------------------------------------------------------------- #
# Étapes
# --------------------------------------------------------------------------- #
def download_image(url: str, dest: Path, dry_run: bool) -> None:
    """Télécharge l'image seulement si elle n'existe pas déjà (cache)."""
    if dest.exists() and dest.stat().st_size > 0:
        size_mb = dest.stat().st_size / 1024 / 1024
        print(f"  Image déjà présente ({size_mb:.0f} Mo), téléchargement ignoré : {dest}")
        return
    if dry_run:
        print(f"  [dry-run] téléchargement {url} -> {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Téléchargement {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")

    def _progress(block_num: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, block_num * block_size * 100 // total)
            print(f"\r    {pct:3d}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(url, tmp, _progress)  # noqa: S310 (URL contrôlée)
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
        (line.split()[0] for line in sums.splitlines()
         if line.strip().endswith(filename)),
        None,
    )
    if expected is None:
        sys.exit(f"Empreinte introuvable pour {filename} dans SHA256SUMS")

    h = hashlib.sha256()
    with image.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != expected:
        sys.exit(f"SHA256 NON conforme !\n  attendu : {expected}\n  obtenu  : {h.hexdigest()}")
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
            input=plain + "\n", capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()


def build_cloud_config(args: argparse.Namespace, pw_hash: str | None,
                       ssh_keys: list[str]) -> str:
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
    lines += [f"  - {p}" for p in dict.fromkeys(packages)]  # dédoublonne, ordre gardé
    return "\n".join(lines) + "\n"


def build_seed(cloud_cfg: str, hostname: str, seed_dest: Path,
               runner: Runner) -> None:
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
            runner.run([
                "genisoimage", "-output", str(local_iso),
                "-volid", "cidata", "-joliet", "-rock", str(ud), str(md),
            ])

        seed_dest.parent.mkdir(parents=True, exist_ok=True) if not runner.dry_run else None
        runner.run(["cp", str(local_iso), str(seed_dest)], privileged=True)


def prepare_disk(image: Path, disk: Path, size: str, runner: Runner,
                 force: bool) -> None:
    """Convertit l'image cloud en qcow2 de travail puis redimensionne."""
    if disk.exists() and not force:
        sys.exit(f"Le disque {disk} existe déjà. Utilisez --force pour l'écraser.")
    runner.run([
        "qemu-img", "convert", "-f", "qcow2", "-O", "qcow2",
        str(image), str(disk),
    ], privileged=True)
    runner.run(["qemu-img", "resize", str(disk), size], privileged=True)


def virt_install(args: argparse.Namespace, disk: Path, seed: Path,
                 osinfo: str, runner: Runner) -> None:
    cmd = [
        "virt-install",
        "--name", args.name,
        "--memory", str(args.memory),
        "--vcpus", str(args.vcpus),
        "--import",
        "--disk", f"path={disk},format=qcow2,bus=virtio",
        "--disk", f"path={seed},device=cdrom",
        "--osinfo", osinfo,
        "--network", args.network,
        "--graphics", args.graphics,
        "--console", "pty,target_type=serial",
    ]
    if not args.attach_console:
        cmd.append("--noautoconsole")
    runner.run(cmd, privileged=True)


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
    p.add_argument("image_path", type=Path,
                   help="Chemin de cache de l'image cloud (.img). "
                        "Si le fichier existe, il n'est PAS re-téléchargé.")

    g_img = p.add_argument_group("Image")
    g_img.add_argument("--version", default="24.04", choices=UBUNTU_VERSIONS,
                       help="Version Ubuntu (défaut : 24.04). Voir la liste ci-dessous.")
    g_img.add_argument("--codename", help="Force le nom de code (surcharge --version).")
    g_img.add_argument("--arch", default="amd64",
                       help="Architecture de l'image (défaut : amd64).")
    g_img.add_argument("--verify", action="store_true",
                       help="Vérifie l'empreinte SHA256 après téléchargement (recommandé).")

    g_vm = p.add_argument_group("VM")
    g_vm.add_argument("--name", required=True, help="Nom de la VM (virsh).")
    g_vm.add_argument("--hostname", help="Nom d'hôte interne (défaut : --name).")
    g_vm.add_argument("--memory", type=int, default=8192, help="RAM en Mo (défaut : 8192).")
    g_vm.add_argument("--vcpus", type=int, default=4, help="Nombre de vCPU (défaut : 4).")
    g_vm.add_argument("--disk-size", default="20G",
                      help="Taille du disque virtuel, ex. 120G (défaut : 20G).")
    g_vm.add_argument("--disk-dir", type=Path, default=Path("/var/lib/libvirt/images"),
                      help="Répertoire du qcow2 de travail (défaut : /var/lib/libvirt/images).")
    g_vm.add_argument("--seed-dir", type=Path,
                      default=Path("/var/lib/libvirt/images/iso"),
                      help="Répertoire du seed.iso (défaut : .../images/iso).")
    g_vm.add_argument("--network", default="network=default,model=virtio",
                      help="Argument --network de virt-install.")
    g_vm.add_argument("--graphics", default="none", help="Argument --graphics (défaut : none).")
    g_vm.add_argument("--osinfo", help="Force la valeur --osinfo (sinon déduite).")
    g_vm.add_argument("--attach-console", action="store_true",
                      help="Attache la console série (sinon --noautoconsole).")

    g_cloud = p.add_argument_group("cloud-init")
    g_cloud.add_argument("--user", default="erplibre", help="Utilisateur créé (défaut : erplibre).")
    g_cloud.add_argument("--password", help="Mot de passe en clair (déconseillé : visible).")
    g_cloud.add_argument("--ask-password", action="store_true",
                         help="Demande le mot de passe de façon interactive (sûr).")
    g_cloud.add_argument("--password-hash",
                         help="Empreinte $6$... déjà calculée (openssl passwd -6).")
    g_cloud.add_argument("--ssh-key", action="append", default=[], metavar="FICHIER",
                         help="Fichier de clé publique SSH à injecter (répétable).")
    g_cloud.add_argument("--locale", default="fr_CA.UTF-8", help="Locale (défaut : fr_CA.UTF-8).")
    g_cloud.add_argument("--keyboard-layout", default="ca", help="Disposition clavier (défaut : ca).")
    g_cloud.add_argument("--keyboard-variant", default="multix",
                         help="Variante clavier (défaut : multix).")
    g_cloud.add_argument("--package", action="append", default=[], metavar="PKG",
                         help="Paquet APT additionnel (répétable).")
    g_cloud.add_argument("--no-upgrade", action="store_true",
                         help="N'exécute pas package_upgrade au premier boot.")

    g_run = p.add_argument_group("Exécution")
    g_run.add_argument("--no-sudo", action="store_true",
                       help="N'utilise pas sudo pour les étapes privilégiées.")
    g_run.add_argument("--force", action="store_true",
                       help="Écrase le qcow2 de travail existant.")
    g_run.add_argument("--dry-run", action="store_true",
                       help="Affiche les commandes et le user-data sans rien exécuter.")
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
    args.hostname = args.hostname or args.name

    codename, default_osinfo = UBUNTU_VERSIONS[args.version]
    if args.codename:
        codename = args.codename
    osinfo = args.osinfo or default_osinfo
    url = image_url(codename, args.arch)

    pw_hash = resolve_password(args)
    ssh_keys = load_ssh_keys(args.ssh_key)
    if not pw_hash and not ssh_keys:
        print("ATTENTION : ni mot de passe ni clé SSH -> connexion impossible à la VM.\n"
              "            Ajoutez --ssh-key, --ask-password ou --password-hash.\n",
              file=sys.stderr)

    runner = Runner(use_sudo=not args.no_sudo and os.geteuid() != 0,
                    dry_run=args.dry_run)
    disk = args.disk_dir / f"{args.name}.qcow2"
    seed = args.seed_dir / f"{args.name}-seed.iso"

    if not args.dry_run:
        for tool in ("qemu-img", "virt-install"):
            need_tool(tool)

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
    virt_install(args, disk, seed, osinfo, runner)

    print(f"\nTerminé. Suivi/connexion :\n"
          f"  virsh list --all\n"
          f"  virsh console {args.name}   # Ctrl+] pour quitter")


if __name__ == "__main__":
    main()
