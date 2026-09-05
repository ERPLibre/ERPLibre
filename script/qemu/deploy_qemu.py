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
import base64
import contextlib
import getpass
import grp
import gzip
import hashlib
import ipaddress
import os
import pwd
import re
import shutil
import socket
import stat as stat_mod
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import warnings
import zlib
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
# Disque MINIMUM = 20G partout : un ERPLibre + Odoo installé occupe ~11G, et
# l'installation (caches pip, sync repo, sources Odoo) en consomme plus en
# transitoire. Un VM à 10G tombait « Poetry installation error » (disque
# plein). Le qcow2 est CREUX (sparse) : une taille virtuelle plus grande ne
# consomme rien tant qu'elle n'est pas remplie -> 20G sans surcoût réel.
#
# 20.04 et 22.04 ne sont plus proposées : leur chaîne d'outils ne suffit plus à
# ERPLibre. Le mur le plus net est pikepdf, qui réclame qpdf >= 12.2, lui-même
# en C++20 — focal livre GCC 9. S'y ajoutaient Python 3.8 à l'amorçage, node 10,
# cargo 0.67 et OpenSSL 1.1.1. Chacun avait son contournement ; l'accumulation,
# non.
UBUNTU_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "24.04": ("noble", "ubuntu24.04", 3072, "20G"),
    "25.10": ("questing", "ubuntu25.10", 3072, "20G"),
    "26.04": ("resolute", "ubuntu26.04", 3072, "20G"),
}
DEBIAN_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "11": ("bullseye", "debian11", 1024, "20G"),
    "12": ("bookworm", "debian12", 1024, "20G"),
    "13": ("trixie", "debian13", 1024, "20G"),
}
FEDORA_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "41": ("41", "fedora41", 2048, "20G"),
    "42": ("42", "fedora42", 2048, "20G"),
    "43": ("43", "fedora43", 2048, "20G"),
    "44": ("44", "fedora44", 2048, "20G"),
}
# Dérivés RHEL. Le second champ est l'identifiant libosinfo : « almalinux9 » et
# « almalinux10 » figurent dans osinfo-db, « rocky10 » n'y est pas encore sur
# les hôtes 24.04 — osinfo_arg() replie alors sur une valeur connue.
# RAM : libosinfo demande 1,5 Gio en x86_64 ; on retient 2048 comme Fedora.
ALMALINUX_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "9": ("9", "almalinux9", 2048, "20G"),
    "10": ("10", "almalinux10", 2048, "20G"),
}
ROCKY_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "9": ("9", "rocky9", 2048, "20G"),
    "10": ("10", "rocky10", 2048, "20G"),
}
# openSUSE, deux produits distincts et pas deux versions du même.
#   Leap       NUMÉROTÉ, base SLE, ~2 ans de support. C'est le défaut, et le
#              seul des deux à proposer pour une installation qui doit durer.
#   Tumbleweed ROLLING, sans numéro. Gardé comme banc d'essai des ruptures à
#              venir, pas comme cible. Sa dérive d'instantanés est réelle : deux
#              VM déployées le même jour ont vu git-daemon 2.54 sur s390x et
#              2.55 sur amd64, et l'image livrée est toujours en retard sur les
#              dépôts, d'où le « zypper dup » obligatoire avant toute install.
#
# Les deux dépassent le seuil qpdf de pikepdf : aucune compilation de qpdf, ce
# qui change tout sous émulation s390x.
#
# osinfo : « opensuse16.0 » n'est pas encore dans osinfo-db, qui s'arrête à
# 15.6. osinfo_arg() replie sur le DERNIER id connu de la table — d'où l'ordre,
# Tumbleweed en second servant de repli à Leap.
OPENSUSE_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "16.0": ("16.0", "opensuse16.0", 2048, "20G"),
    "tumbleweed": ("tumbleweed", "opensusetumbleweed", 2048, "20G"),
}
# Arch est en rolling release : une seule « version » (latest).
ARCH_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "latest": ("latest", "archlinux", 1024, "20G"),
}

# Proxmox VE ne publie AUCUNE image cloud : son ISO est un installateur, et la
# voie que l'amont documente pour tout le reste est « Proxmox VE sur Debian ».
# La base est donc l'image cloud Debian, que les paquets pve transforment en
# hyperviseur. Le numéro est celui de PROXMOX, pas de Debian : PVE 9 = trixie.
#
# arm64 est officiel depuis PVE 9 — vérifié dans le dépôt amont, dont le
# Release de trixie annonce « amd64 arm64 » et dont l'index arm64 sert bien
# proxmox-ve. bookworm (PVE 8), lui, est amd64 seulement : d'où une seule
# version au catalogue, celle qui couvre les deux architectures.
#
# s390x n'y figure pas et n'y figurera pas par cette voie : l'index
# « binary-s390x » du dépôt répond 404. Ce n'est pas une difficulté, c'est une
# absence — et ARCH_DISTRO_SUPPORT la dit à la place d'un échec au montage.
#
# RAM/disque : 4 Gio et 32 Go, pas les 1 Gio/20 Go de Debian. Proxmox demande
# 2 Gio pour lui seul, et l'installation télécharge son propre noyau ; 20 Go ne
# laisseraient pas la place d'une seule VM invitée.
PROXMOX_VERSIONS: dict[str, tuple[str, str, int, str]] = {
    "9": ("trixie", "debian13", 4096, "32G"),
}

# Version Debian dont l'image sert de base à chaque version de Proxmox.
PROXMOX_DEBIAN_BASE: dict[str, str] = {"9": "13"}

# distro -> (table des versions, version par défaut).
DISTROS: dict[str, tuple[dict[str, tuple[str, str, int, str]], str]] = {
    "ubuntu": (UBUNTU_VERSIONS, "24.04"),
    "debian": (DEBIAN_VERSIONS, "12"),
    "fedora": (FEDORA_VERSIONS, "42"),
    "almalinux": (ALMALINUX_VERSIONS, "9"),
    "rocky": (ROCKY_VERSIONS, "10"),
    "opensuse": (OPENSUSE_VERSIONS, "16.0"),
    "arch": (ARCH_VERSIONS, "latest"),
    "proxmox": (PROXMOX_VERSIONS, "9"),
}

# Traduction de l'arch générique (amd64/arm64) vers le nom propre à la distro.
# s390x s'écrit « s390x » partout (identité), donc aucune entrée n'est requise.
ARCH_ALIASES: dict[str, dict[str, str]] = {
    "fedora": {"amd64": "x86_64", "arm64": "aarch64"},
    "almalinux": {"amd64": "x86_64", "arm64": "aarch64"},
    "rocky": {"amd64": "x86_64", "arm64": "aarch64"},
    "opensuse": {"amd64": "x86_64", "arm64": "aarch64"},
    "arch": {"amd64": "x86_64", "arm64": "aarch64"},
}

# Architectures non-x86 nécessitant une machine/un amorçage spécifiques (voir
# virt_install). Émulées en TCG (pas de KVM), donc LENTES, quand elles
# diffèrent de l'architecture de l'hôte.
NON_X86_ARCHES: tuple[str, ...] = ("arm64", "s390x")

# Distros publiant des images cloud par architecture (vérifié juillet 2026) :
# - s390x (IBM Z)  : Ubuntu seulement (Debian/Fedora : 404 ; Arch : x86/arm).
# - arm64/aarch64  : Ubuntu, Debian, Fedora (Arch : pas d'image cloud officielle
#   aarch64 sur geo.mirror.pkgbuild.com).
S390X_DISTROS: tuple[str, ...] = (
    "ubuntu",
    "almalinux",
    "rocky",
    "fedora",
    "opensuse",
    # Debian n'a PAS d'image cloud s390x, et n'en aura pas par cette voie :
    # vérifié sur cloud.debian.org, les arborescences bookworm et trixie ne
    # publient que amd64, arm64, ppc64el et riscv64. Le port s390x existe
    # pourtant — « binary-s390x » répond 200 — et debian-installer livre
    # kernel + initrd pour les deux versions. On y passe donc par
    # l'INSTALLATEUR au lieu d'un qcow2 tout fait : voir uses_installer().
    "debian",
)

# Une distro peut ne publier qu'une PARTIE de ses versions sur une
# architecture. Déclaration POSITIVE : hors de cette table, toutes les versions
# du catalogue sont réputées disponibles.
#
# Fedora ne construit s390x que pour la version courante, et sur une
# arborescence à part (« fedora-secondary ») : la 41 et la 42 y sont retirées
# (404 sur le miroir maître), la 44 n'est pour l'instant que sur certains
# miroirs tiers. Seule la 43 est servie par dl.fedoraproject.org — vérifié.
ARCH_ONLY_VERSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    # Debian sur s390x passe par debian-installer, dont les images sont
    # publiées pour bookworm et trixie — vérifié. bullseye est écartée : elle
    # est en fin de vie et son installateur n'a pas été éprouvé ici.
    "s390x": {"fedora": ("43",), "debian": ("12", "13")},
}

# Distros installées par debian-installer plutôt que depuis une image cloud.
# La différence n'est pas cosmétique : pas de qcow2 à convertir, pas de seed
# cloud-init, un disque VIERGE et un amorçage kernel+initrd.
INSTALLER_COMBOS: tuple[tuple[str, str], ...] = (("debian", "s390x"),)

# Plancher mémoire de l'installateur : il déplie un système de fichiers entier
# en RAM, là où une image cloud arrive déjà installée.
INSTALLER_MIN_RAM = 2048

# kernel.debian / initrd.debian du port s390x. « current » suit les mises à
# jour de l'installateur sans figer un numéro qui périmerait.
INSTALLER_URL = (
    "https://deb.debian.org/debian/dists/{code}/main/installer-s390x"
    "/current/images/generic/{fichier}"
)


def uses_installer(distro: str, arch: str) -> bool:
    """Vrai si cette combinaison s'installe par debian-installer."""
    return (distro, arch) in INSTALLER_COMBOS


def arch_versions(distro: str, arch: str, versions) -> list[str]:
    """Versions de `distro` réellement publiées pour `arch`."""
    only = ARCH_ONLY_VERSIONS.get(arch, {}).get(distro)
    return [v for v in versions if only is None or v in only]


ARM64_DISTROS: tuple[str, ...] = (
    "ubuntu",
    "debian",
    "fedora",
    "almalinux",
    "rocky",
    "opensuse",
    "proxmox",
)


# arch générique -> distros la publiant (pour valider --arch tôt).
ARCH_DISTRO_SUPPORT: dict[str, tuple[str, ...]] = {
    "s390x": S390X_DISTROS,
    "arm64": ARM64_DISTROS,
}


def host_arch() -> str:
    """Architecture de l'hôte en jeton générique (amd64/arm64/s390x)."""
    try:
        machine = os.uname().machine
    except (AttributeError, OSError):
        machine = ""
    return {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "s390x": "s390x",
    }.get(machine, "amd64")


# Nœud de rendu DRM : le fichier que le processus QEMU ouvre pour créer un
# contexte OpenGL (virgl) et donner la 3D à la VM. Un hôte sans GPU — ou
# lui-même virtualisé sans GPU transmis — n'expose AUCUN « renderD* », et
# aucune option de ligne de commande ne peut y suppléer : la VM retombe alors
# sur le rendu logiciel. On teste donc la présence du nœud, pas nos droits
# dessus : l'accès est accordé par libvirt au démarrage du domaine (cgroup +
# étiquette), et un test de lecture sous notre propre compte rejetterait à
# tort un hôte où seul le groupe « render » entre.
HOST_DRI_DIR = Path("/dev/dri")


def host_render_nodes(directory=HOST_DRI_DIR) -> list[str]:
    """Nœuds de rendu de l'hôte, triés (ex. ['/dev/dri/renderD128'])."""
    directory = Path(directory)
    try:
        names = sorted(p.name for p in directory.iterdir())
    except OSError:
        return []
    return [str(directory / n) for n in names if n.startswith("renderD")]


def host_gpu_node(directory=HOST_DRI_DIR) -> str:
    """Nœud de rendu à confier à QEMU, ou '' si l'hôte n'a pas de GPU.

    Le premier de la liste : sur une machine à plusieurs cartes, renderD128
    est le nœud du GPU primaire. --gpu-node force un autre choix.
    """
    nodes = host_render_nodes(directory)
    return nodes[0] if nodes else ""


def gpu_decision(mode: str, node: str, screen: bool) -> tuple[bool, str]:
    """(3D activée, message à dire) pour un mode --gpu et un nœud donnés.

    Séparée du reste pour être vérifiable sans hôte : c'est ici que se décide
    « par défaut avec GPU s'il existe », et le silence n'est pas une option —
    une VM en rendu logiciel doit dire pourquoi.
    """
    mode = (mode or "auto").lower()
    if mode == "off":
        return False, ""
    if not screen and mode != "on":
        # Sans écran virtuel, « auto » s'abstient : une VM serveur n'a pas
        # demandé de périphérique vidéo, et lui en poser un d'office change
        # son matériel sans qu'on l'ait voulu.
        return False, ""
    if not node:
        if mode == "on":
            return (
                False,
                "  ⚠ GPU demandé mais l'hôte n'a aucun nœud de rendu"
                " (/dev/dri/renderD*) : la VM démarrerait sans écran."
                " Rendu logiciel.",
            )
        return (
            False,
            "  GPU : aucun sur l'hôte, rendu logiciel (virgl absent).",
        )
    if not screen:
        # 3D demandée sur une VM sans console : le virtio-gpu est POSÉ quand
        # même, et « egl-headless » n'ouvre aucun port — l'invité reçoit un
        # périphérique DRM accéléré sans écran à regarder. C'est ce qui sert
        # au rendu hors écran et à un émulateur qui tourne dans la VM.
        return (
            True,
            f"  GPU : 3D activée par {node} sans écran virtuel"
            " (virtio-gpu accéléré, aucun port ouvert).",
        )
    return True, f"  GPU : 3D activée par {node} (virtio-gpu + egl-headless)."


# Ce que QEMU écrit quand le nœud de rendu existe mais qu'EGL n'y démarre
# pas. Le fichier /dev/dri/renderD* est alors bien là — un GPU virtuel sans
# pile EGL, un pilote sans GBM, une carte que Mesa ne sait pas ouvrir : la
# présence du nœud ne prouve donc PAS que la 3D fonctionne, et rien ne le dit
# avant que QEMU n'essaie.
EGL_ECHEC = (
    "eglInitialize failed",
    "render node init failed",
    "EGL_NOT_INITIALIZED",
)


def egl_failed(output: str) -> bool:
    """La sortie de virt-install accuse-t-elle un EGL inutilisable ?"""
    return any(marque in (output or "") for marque in EGL_ECHEC)


def gpu_apply(
    video: list, mode: str, node: str, screen: bool
) -> tuple[list, list, str]:
    """(video, arguments 3D, message) — pour virt-install.

    Renvoie le `--video` à garder : celui de la 3D REMPLACE le simple
    « --video virtio », il ne s'y ajoute pas. Deux --video donneraient deux
    écrans à la VM, et l'invité n'afficherait le bureau que sur un seul.
    """
    use_gpu, message = gpu_decision(mode, node, screen)
    if not use_gpu:
        return video, [], message
    return [], gpu_install_args(node), message


def gpu_install_args(node: str) -> list[str]:
    """Arguments virt-install qui donnent la 3D à la VM.

    Deux pièces indissociables : l'accélération sur le virtio-gpu, et un
    affichage capable de contexte GL. « egl-headless » joue ce second rôle
    SANS remplacer la console VNC — il n'ouvre aucun port, il n'existe que
    pour porter le contexte OpenGL. C'est la recette documentée pour associer
    3D et VNC, là où <gl enable/> ne vaut que pour SPICE.
    """
    return [
        "--video",
        "model.type=virtio,model.acceleration.accel3d=on",
        "--graphics",
        f"type=egl-headless,gl.rendernode={node}",
    ]


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
ALMALINUX_CLOUD_BASE = "https://repo.almalinux.org/almalinux"
OPENSUSE_BASE = "https://download.opensuse.org"
ROCKY_CLOUD_BASE = "https://dl.rockylinux.org/pub/rocky"
FEDORA_BASE = "https://download.fedoraproject.org/pub/fedora/linux/releases"
# Serveur MAÎTRE (pas de redirection MirrorManager) : repli fiable quand le
# redirecteur envoie sur un miroir incomplet (fréquent en déploiement
# PARALLÈLE : chaque requête peut tomber sur un miroir différent/désynchronisé).
FEDORA_BASE_MASTER = "https://dl.fedoraproject.org/pub/fedora/linux/releases"
# s390x est une architecture SECONDAIRE chez Fedora : ses images ne sont PAS
# sous /pub/fedora/linux/ mais sous /pub/fedora-secondary/, et seule la
# version courante y est construite.
FEDORA_SECONDARY = (
    "https://download.fedoraproject.org/pub/fedora-secondary/releases"
)
FEDORA_SECONDARY_MASTER = (
    "https://dl.fedoraproject.org/pub/fedora-secondary/releases"
)

# Répertoire de cache par défaut des images cloud (cohérent avec --disk-dir /
# --seed-dir). L'écriture y nécessite root : le déploiement tourne de toute
# façon sous sudo (virt-install). Surchargez avec --image-dir au besoin.
# Le pool par défaut de libvirt, et son sous-répertoire de cache d'images.
# Nommés ici et non dans argparse : sudo_facts() doit constater les droits du
# répertoire que le déploiement utilisera VRAIMENT, et deux écritures du même
# chemin divergent dès qu'on en change une.
DEFAULT_DISK_DIR = Path("/var/lib/libvirt/images")
DEFAULT_IMAGE_DIR = DEFAULT_DISK_DIR / "iso"

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
    if distro == "proxmox":
        # C'est bien l'image DEBIAN qu'on télécharge : « proxmox-ve », posé
        # dessus, en fait l'hyperviseur. Le miroir ne connaît que le numéro de
        # Debian, jamais celui de Proxmox.
        return image_candidates(
            "debian", code, arch, PROXMOX_DEBIAN_BASE[version], dry_run
        )
    if distro == "fedora":
        return [resolve_fedora_url(version, arch, dry_run)]
    if distro == "almalinux":
        # Contrairement à Fedora, AlmaLinux publie un lien « latest » STABLE
        # par majeure et par architecture : aucun index HTML à analyser. On
        # vise l'arbre de la MAJEURE (9/, 10/), qui suit la mineure courante —
        # les répertoires mineurs périmés sont retirés du miroir.
        return [
            f"{ALMALINUX_CLOUD_BASE}/{version}/cloud/{a}/images/"
            f"AlmaLinux-{version}-GenericCloud-latest.{a}.qcow2"
        ]
    if distro == "rocky":
        # Même principe : l'alias « .latest » suit le point release courant, et
        # les précédents partent au vault — une URL figée casserait.
        return [
            f"{ROCKY_CLOUD_BASE}/{version}/images/{a}/"
            f"Rocky-{version}-GenericCloud.latest.{a}.qcow2"
        ]
    if distro == "opensuse":
        # zsystems DOUBLE l'architecture dans le nom du fichier — irrégularité
        # vérifiée dans l'index, pas déduite : « .s390x-s390x-Cloud » contre
        # « .x86_64-Cloud ». Elle vaut pour les DEUX produits.
        tag = f"{a}-{a}" if arch == "s390x" else a
        if version == "tumbleweed":
            # Tumbleweed sépare les architectures secondaires sous /ports/.
            port = {"s390x": "ports/zsystems/", "arm64": "ports/aarch64/"}.get(
                arch, ""
            )
            return [
                f"{OPENSUSE_BASE}/{port}tumbleweed/appliances/"
                f"openSUSE-Tumbleweed-Minimal-VM.{tag}-Cloud.qcow2"
            ]
        # Leap, lui, publie TOUTES les architectures dans un seul répertoire :
        # les chemins /ports/ équivalents rendent 404. x86_64, aarch64 et s390x
        # y sont côte à côte (relevé dans l'index de 16.0, les trois en 200).
        return [
            f"{OPENSUSE_BASE}/distribution/leap/{version}/appliances/"
            f"Leap-{version}-Minimal-VM.{tag}-Cloud.qcow2"
        ]
    if distro == "arch":
        # Rolling release : image « latest » officielle (cloud-init inclus).
        return [f"{ARCH_CLOUD_BASE}/Arch-Linux-{a}-cloudimg.qcow2"]
    raise ValueError(f"URL indisponible pour la distro {distro!r}")


def resolve_fedora_url(version: str, arch: str, dry_run: bool) -> str:
    """Résout l'URL du qcow2 « Fedora Cloud Base Generic » depuis l'index
    HTML des releases (Fedora ne publie pas de lien « latest »). ROBUSTE :
    plusieurs tentatives sur le redirecteur puis repli sur le serveur maître
    (dl.fedoraproject.org) — sinon, en déploiement parallèle, une requête
    tombée sur un miroir incomplet faisait échouer la VM (« image introuvable »)
    alors que l'image existe bel et bien."""
    a = distro_arch("fedora", arch)
    pattern = re.compile(
        rf"Fedora-Cloud-Base-Generic-{version}-[0-9.]+\.{a}\.qcow2"
    )
    # Architecture secondaire (s390x, ppc64le) : autre arborescence.
    primary, master = (
        (FEDORA_SECONDARY, FEDORA_SECONDARY_MASTER)
        if arch == "s390x"
        else (FEDORA_BASE, FEDORA_BASE_MASTER)
    )
    if dry_run:
        index = f"{primary}/{version}/Cloud/{a}/images/"
        return index + f"Fedora-Cloud-Base-Generic-{version}-<build>.{a}.qcow2"
    # On essaie le redirecteur (2 fois : chaque requête peut viser un miroir
    # différent) puis le serveur maître (toujours complet).
    bases = [primary, primary, master]
    last_err = ""
    for base in bases:
        index = f"{base}/{version}/Cloud/{a}/images/"
        try:
            with urllib.request.urlopen(
                index, timeout=30
            ) as resp:  # noqa: S310
                html = resp.read().decode(errors="replace")
        except Exception as exc:  # pragma: no cover - dépend du réseau
            last_err = str(exc)
            continue
        names = sorted(set(pattern.findall(html)))
        if names:
            return index + names[-1]
    sys.exit(
        "Aucune image « Fedora-Cloud-Base-Generic » trouvée pour "
        f"Fedora {version} ({a}) après plusieurs miroirs"
        + (f" (dernière erreur : {last_err})" if last_err else "")
    )


def default_image_name(distro: str, code: str, arch: str, version: str) -> str:
    """Nom de fichier local pour le cache d'image."""
    a = distro_arch(distro, arch)
    if distro == "ubuntu":
        return f"ubuntu-{version}-server-cloudimg-{a}.img"
    if distro == "debian":
        return f"debian-{version}-genericcloud-{a}.qcow2"
    if distro == "proxmox":
        # Le fichier téléchargé EST celui de Debian : lui donner le même nom
        # de cache fait qu'un déploiement Debian 13 et un Proxmox se
        # PARTAGENT le téléchargement (325 Mio) au lieu d'en faire deux. Sans
        # cette branche, le repli de fin nommait l'image « fedora-cloud-9 ».
        return f"debian-{PROXMOX_DEBIAN_BASE[version]}-genericcloud-{a}.qcow2"
    if distro == "arch":
        return f"arch-linux-{a}-cloudimg.qcow2"
    if distro == "opensuse":
        if version == "tumbleweed":
            return f"opensuse-tumbleweed-minimal-vm-{a}.qcow2"
        return f"opensuse-leap-{version}-minimal-vm-{a}.qcow2"
    if distro in ("almalinux", "rocky"):
        # « latest » est MUTABLE : le nom de cache porte donc la majeure, et
        # une image déjà téléchargée sera réutilisée telle quelle. C'est voulu
        # (reproductibilité d'un déploiement à l'autre) ; supprimer le fichier
        # du cache suffit à repartir sur le build courant.
        return f"{distro}-{version}-genericcloud-{a}.qcow2"
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
def repertoire_a_root(chemin: Path) -> tuple | None:
    """(chemin, propriétaire, mode) si l'écriture y est refusée, sinon None.

    L'écriture se TESTE, elle ne se déduit pas du mode : une ACL ou un groupe
    peut l'accorder là où « drwxr-xr-x root root » la refuse en apparence, et
    l'inverse existe aussi. Le propriétaire et le mode ne sont lus qu'ENSUITE,
    pour dire au lecteur ce qui bloque.
    """
    try:
        if not chemin.is_dir() or os.access(chemin, os.W_OK):
            return None
        infos = chemin.stat()
    except OSError:
        return None
    try:
        utilisateur = pwd.getpwuid(infos.st_uid).pw_name
    except (KeyError, OSError):
        utilisateur = str(infos.st_uid)
    try:
        groupe = grp.getgrgid(infos.st_gid).gr_name
    except (KeyError, OSError):
        groupe = str(infos.st_gid)
    return (
        str(chemin),
        f"{utilisateur}:{groupe}",
        stat_mod.filemode(infos.st_mode),
    )


def sudo_facts(disk_dir: Path | None = None, image_dir: Path | None = None):
    """Pourquoi root est nécessaire ici : des FAITS, constatés sur la machine.

    Rend une liste de couples (clé, valeurs) et non des phrases : ce script
    les dit en français, le menu TODO les traduit, et la vérification ne vit
    qu'à un endroit.

    Deux clés. « ecriture » : un répertoire où le déploiement doit écrire et
    ne peut pas — c'est le vrai motif, et il tient au RÉPERTOIRE, pas à
    libvirt. « socket » : qemu:///system répond-il sans sudo, ce qui dit ce
    que le groupe libvirt couvre RÉELLEMENT — appartenir au groupe et en
    disposer dans la session courante sont deux choses.

    Le tout parce que sudo demande un mot de passe sans jamais dire ce qu'il
    sert à faire : l'invite tombe entre deux lignes de journal, et on la subit
    sans savoir si elle porte sur libvirt, sur un paquet ou sur un fichier.
    """
    faits = []
    vus = set()
    for chemin in (
        disk_dir or DEFAULT_DISK_DIR,
        image_dir or DEFAULT_IMAGE_DIR,
    ):
        bloque = repertoire_a_root(Path(chemin))
        if bloque and bloque[0] not in vus:
            vus.add(bloque[0])
            faits.append(("ecriture", bloque))
    # Trois valeurs et non deux : « absent » quand virsh n'est pas là. Rendre
    # « non » y ferait accuser le groupe libvirt d'un défaut qui n'est pas le
    # sien — il n'y a simplement rien à joindre encore.
    if shutil.which("virsh") is None:
        faits.append(("socket", ("absent",)))
    else:
        faits.append(("socket", ("ok" if libvirt_ready(False) else "non",)))
    return faits


def sudo_lignes(faits) -> list[str]:
    """Les faits mis en phrases, en français, pour ce script."""
    lignes = []
    for cle, valeurs in faits:
        if cle == "ecriture":
            chemin, proprio, mode = valeurs
            lignes.append(
                f"écrire dans {chemin} — vérifié : {proprio} {mode},"
                " écriture refusée à cet utilisateur"
            )
    if any(cle == "ecriture" for cle, _v in faits):
        lignes.append(
            "le groupe libvirt ouvre la socket qemu:///system, pas ce"
            " répertoire"
        )
    else:
        lignes.append("les gestes système du script (service, groupe)")
    for cle, valeurs in faits:
        if cle == "socket" and valeurs[0] == "non":
            lignes.append(
                "la socket libvirt ne répond pas non plus sans sudo :"
                " groupe absent de cette session, ou libvirt pas démarré"
            )
    return lignes


# --------------------------------------------------------------------------- #
class Runner:
    """Exécute (ou affiche, en dry-run) les commandes, avec sudo au besoin."""

    def __init__(self, use_sudo: bool, dry_run: bool) -> None:
        self.use_sudo = use_sudo
        self.dry_run = dry_run
        # L'explication n'est due qu'UNE fois : sudo garde sa réponse quelques
        # minutes, et la répéter à chaque étape noierait le journal.
        self._sudo_dit = False

    def _annoncer_sudo(self) -> None:
        """Dit pourquoi root, AVANT que sudo ne réclame le mot de passe.

        Avant et non après : sudo n'explique jamais ce qu'il sert à faire, et
        un mot de passe tapé sans savoir ce qu'il autorise est donné à
        l'aveugle. Les raisons sont constatées sur la machine, pas affirmées —
        voir sudo_facts().
        """
        if self._sudo_dit:
            return
        self._sudo_dit = True
        print("\n🔑 sudo va demander votre mot de passe, pour :")
        for ligne in sudo_lignes(sudo_facts()):
            print(f"     {ligne}")

    def run(
        self,
        cmd: list[str],
        *,
        privileged: bool = False,
        check: bool = True,
        capture: bool = False,
    ):
        """Lance la commande. `capture` rend (code, sortie) au lieu de sortir.

        Sans `capture`, un échec termine le programme : c'est le comportement
        voulu partout où il n'y a rien à rattraper. Avec, l'appelant décide —
        seul l'appel qui SAIT réessayer autrement doit le demander.
        """
        if privileged and self.use_sudo:
            self._annoncer_sudo()
            cmd = ["sudo", *cmd]
        printable = " ".join(cmd)
        if self.dry_run:
            print(f"  [dry-run] {printable}")
            return (0, "") if capture else None
        print(f"  $ {printable}")
        if capture:
            # La sortie est réaffichée telle quelle : le journal garde tout,
            # et l'appelant peut lire ce que l'outil a dit.
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if res.stdout:
                print(res.stdout, end="")
            return res.returncode, res.stdout or ""
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
# URI libvirt visée par TOUS les clients (virsh, virt-install). À ne jamais
# laisser implicite : pour un utilisateur non root, libvirt choisit
# « qemu:///session », où le réseau « default » N'EXISTE PAS — virt-install
# échoue alors sur « --network network=default » de façon incompréhensible.
# Appartenir au groupe libvirt donne le DROIT d'accéder à qemu:///system mais
# ne change PAS l'URI par défaut : il faut l'imposer.
LIBVIRT_URI = "qemu:///system"

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

# Émulateurs QEMU système pour architectures non-x86, requis pour --arch
# <arch> sur un hôte d'architecture différente (émulation TCG). Par arch puis
# par gestionnaire de paquets. NB apt : qemu-system-misc ne contient PAS s390x
# (alpha/avr/… seulement) -> paquet dédié qemu-system-s390x ; qemu-system-arm
# fournit qemu-system-aarch64 ; l'arm64 exige aussi le firmware UEFI AAVMF.
EMULATOR_PACKAGES: dict[str, dict[str, list[str]]] = {
    "s390x": {
        "apt": ["qemu-system-s390x"],
        "dnf": ["qemu-system-s390x"],
        "pacman": ["qemu-emulators-full"],
        "zypper": ["qemu-s390"],
        "brew": [],
    },
    "arm64": {
        "apt": ["qemu-system-arm", "qemu-efi-aarch64"],
        "dnf": ["qemu-system-aarch64", "edk2-aarch64"],
        "pacman": ["qemu-emulators-full", "edk2-aarch64"],
        "zypper": ["qemu-arm", "qemu-uefi-aarch64"],
        "brew": [],
    },
}

# Binaire émulateur par arch (détection de présence).
EMULATOR_BINARY: dict[str, str] = {
    "s390x": "qemu-system-s390x",
    "arm64": "qemu-system-aarch64",
}

# Firmwares UEFI AAVMF possibles (arm64) : au moins un doit exister.
AARCH64_FIRMWARE_PATHS: tuple[str, ...] = (
    "/usr/share/AAVMF/AAVMF_CODE.fd",
    "/usr/share/AAVMF/AAVMF_CODE.no-secboot.fd",
    "/usr/share/edk2/aarch64/QEMU_EFI.fd",
    "/usr/share/edk2/aarch64/QEMU_EFI-silent.fd",
    "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd",
    "/usr/share/edk2-armvirt/aarch64/QEMU_EFI.fd",
)

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


def invoking_user() -> str:
    """Utilisateur réel derrière l'appel, même sous sudo."""
    return os.environ.get("SUDO_USER") or getpass.getuser()


def ensure_libvirt_group(runner: Runner) -> bool:
    """Ajoute l'utilisateur au groupe libvirt. Renvoie True s'il l'était déjà.

    SANS ce groupe, les clients libvirt d'un utilisateur non root retombent sur
    « qemu:///session », où le réseau « default » N'EXISTE PAS : virt-install
    échoue alors sur « --network network=default » alors que tous les paquets
    sont pourtant installés. C'est le trou qui manquait au profil
    « ERPLibre Déploiement » : il installait QEMU sans jamais rendre
    qemu:///system accessible.
    """
    user = invoking_user()
    if user == "root":
        return True
    lst_group = []
    for group in ("libvirt", "kvm"):
        try:
            grp.getgrnam(group)
        except KeyError:
            continue  # groupe absent sur cette distro
        try:
            if user in grp.getgrnam(group).gr_mem:
                continue
        except KeyError:
            pass
        lst_group.append(group)
    if not lst_group:
        print(f"  Utilisateur « {user} » déjà dans les groupes libvirt/kvm.")
        return True
    for group in lst_group:
        print(f"  Ajout de « {user} » au groupe « {group} »…")
        runner.run(
            ["usermod", "-aG", group, user], privileged=True, check=False
        )
    return False


def kernel_modules_stale() -> str:
    """Renvoie un message si les modules du noyau EN COURS ont disparu.

    Sur une distro roulante, « make install_os » met le noyau à jour et le
    gestionnaire de paquets SUPPRIME /lib/modules/<noyau en cours>. Tant qu'on
    n'a pas redémarré, « modprobe bridge » échoue et libvirt ne peut pas créer
    virbr0 : « Unable to create bridge virbr0: Package not installed ». Aucun
    paquet ne corrige ça, seul un redémarrage le fait — d'où ce diagnostic.
    """
    if not shutil.which("uname"):
        return ""
    running = os.uname().release
    path_module = f"/lib/modules/{running}"
    if os.path.isdir(path_module):
        return ""
    return (
        f"Le noyau en cours ({running}) n'a plus ses modules "
        f"({path_module} absent) : il a été mis à jour depuis le démarrage.\n"
        "  libvirt ne pourra pas créer le pont virbr0 tant que la machine\n"
        "  n'aura pas REDÉMARRÉ. Redémarrez, puis relancez --setup-host."
    )


def ensure_ssh_key(runner: Runner) -> None:
    """Garantit que l'utilisateur possède une clé publique SSH.

    Sans clé, cloud-init ne peut en injecter aucune dans la VM créée : elle
    démarre sans accès SSH et l'orchestrateur ne peut plus vérifier son état.
    On en génère donc une (ed25519, sans passphrase) quand il n'y en a pas.

    La clé doit appartenir à l'UTILISATEUR, pas à root : sous sudo, « ~ »
    désigne /root et la clé y serait inutilisable.
    """
    user = invoking_user()
    home = os.path.expanduser(f"~{user}")
    ssh_dir = os.path.join(home, ".ssh")
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        path_pub = os.path.join(ssh_dir, name)
        if os.path.exists(path_pub):
            print(f"  Clé SSH déjà présente : {path_pub}")
            return

    path_key = os.path.join(ssh_dir, "id_ed25519")
    print(f"  Génération d'une clé SSH ed25519 pour « {user} »…")
    # sudo -u : on exécute EN TANT QUE l'utilisateur, pour que la clé et le
    # répertoire lui appartiennent même quand --setup-host tourne sous sudo.
    prefix = (
        ["sudo", "-u", user] if os.geteuid() == 0 and user != "root" else []
    )
    runner.run(prefix + ["mkdir", "-p", "-m", "700", ssh_dir], check=False)
    runner.run(
        prefix
        + [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-N",
            "",
            "-q",
            "-f",
            path_key,
            "-C",
            f"erplibre-deploy@{socket.gethostname()}",
        ],
        check=False,
    )
    if not runner.dry_run and os.path.exists(f"{path_key}.pub"):
        print(f"  Clé créée : {path_key}.pub")


def schedule_reboot(runner: Runner) -> None:
    """Programme un redémarrage DIFFÉRÉ et détaché de la session courante.

    Un « systemctl reboot » immédiat tuerait le SSH de l'installation, et
    l'orchestrateur compterait la VM en échec alors que tout s'est bien passé.
    On laisse donc quelques secondes pour que la commande distante rende la
    main proprement.
    """
    if shutil.which("systemd-run"):
        runner.run(
            ["systemd-run", "--on-active=5", "systemctl", "reboot"],
            privileged=True,
            check=False,
        )
        return
    runner.run(["shutdown", "-r", "+1"], privileged=True, check=False)


def setup_host(
    runner: Runner,
    assume_yes: bool,
    no_install: bool,
    reboot_if_needed: bool = False,
    assume_yes_reboot: bool = False,
) -> None:
    """Prépare l'hôte à faire tourner des VM : paquets, démon, groupe, réseau.

    Point d'entrée unique du profil d'installation « ERPLibre Déploiement ».
    Il réutilise les mêmes fonctions que le déploiement, donc les noms de
    paquets restent définis à UN SEUL endroit (TOOL_PACKAGES /
    DAEMON_PACKAGES) et restent valides pour apt, dnf, pacman, zypper et brew.
    """
    print("\n== Préparation de l'hôte pour QEMU/libvirt ==")
    # ensure_tools installe les clients ET, si le démon manque, les paquets de
    # DAEMON_PACKAGES (qemu système + libvirt + firmware UEFI), puis démarre le
    # service. ensure_emulator ne sert QU'À l'émulation croisée (arm64 sur x86)
    # et n'a pas de clé pour l'architecture hôte.
    ensure_tools(runner, assume_yes, no_install, force_daemon=True)
    ensure_libvirt_service(runner)
    already_in_group = ensure_libvirt_group(runner)
    ensure_ssh_key(runner)
    # Diagnostiqué AVANT le réseau : sans les modules du noyau en cours, le
    # pont virbr0 est impossible et l'erreur de virsh est indéchiffrable.
    stale = kernel_modules_stale()
    if stale:
        print(f"\n⚠ {stale}")
    ensure_network("default", runner)

    if runner.dry_run:
        print("\n[dry-run] Rien n'a été modifié, vérification ignorée.")
        return

    print("\n== Vérification ==")
    ok = libvirt_ready(runner.use_sudo)
    print(f"  hyperviseur qemu:///system : {'OK' if ok else 'INJOIGNABLE'}")
    active, autostart = network_state("default", runner.use_sudo)
    # Le sous-réseau est dit ICI parce que c'est de lui que les VM tireront
    # leur adresse : déplacé, il n'est plus celui que la documentation de
    # libvirt fait attendre.
    cidr = network_cidr("default", runner.use_sudo)
    print(
        f"  réseau libvirt « default »  : "
        f"{'actif' if active else 'INACTIF'}"
        f" / {'autostart' if autostart else 'PAS autostart'}"
        + (f" / {cidr}" if cidr else "")
    )
    if not active and stale:
        # Le réseau est déjà « autostart » : après le redémarrage, libvirt le
        # monte tout seul avec les modules du nouveau noyau. Un seul reboot
        # suffit donc à rendre l'hôte utilisable, sans repasser par ici.
        if reboot_if_needed:
            # Le consentement à installer des paquets ne vaut PAS consentement
            # à redémarrer : assume_yes couvre pacman, jamais la machine de
            # celui qui l'a tapé. Une provision sans personne devant l'écran
            # passe --assume-yes-reboot, qui dit explicitement l'autre chose.
            if assume_yes_reboot or prompt_yes_no(
                "\n↻ Redémarrer MAINTENANT ? C'est la seule façon de"
                " retrouver les modules du noyau. Au retour, le réseau"
                " « default » démarrera seul (autostart déjà actif).",
                default=False,
            ):
                print("\n↻ Redémarrage programmé (dans quelques secondes).")
                schedule_reboot(runner)
                return
            sys.exit(
                "Erreur : l'hôte n'est pas prêt, redémarrage refusé.\n"
                f"  {stale}\n"
                "  Redémarrez quand vous le voudrez, puis relancez"
                " --setup-host."
            )
        sys.exit(f"Erreur : l'hôte n'est pas prêt.\n  {stale}")

    if not (ok and active):
        sys.exit(
            "Erreur : l'hôte n'est pas prêt.\n"
            + (f"  {stale}\n" if stale else "")
            + "  Sinon vérifiez :\n"
            "    sudo systemctl enable --now libvirtd\n"
            "    sudo virsh -c qemu:///system net-start default"
        )
    if not already_in_group:
        print(
            f"\n⚠ « {invoking_user()} » vient d'être ajouté au groupe libvirt."
            " Les groupes ne s'appliquent qu'aux NOUVELLES sessions :"
            " reconnectez-vous (ou « newgrp libvirt »), sinon virt-install"
            " continuera d'utiliser qemu:///session et le réseau « default »"
            " restera introuvable."
        )
    print("\nHôte prêt.")


def ensure_tools(
    runner: Runner,
    assume_yes: bool,
    no_install: bool,
    force_daemon: bool = False,
) -> None:
    """Vérifie outils, démon libvirt et émulateur ; installe/démarre ce qui
    manque, puis vérifie la connexion à l'hyperviseur.

    `force_daemon` réinstalle DAEMON_PACKAGES même quand le démon répond déjà.
    Vécu sur Arch : libvirt était présent (posé par un ancien one-liner qui ne
    listait pas dnsmasq), donc daemon_missing() renvoyait False et dnsmasq
    n'était jamais installé -> « Failed to start network default ». Les
    gestionnaires de paquets ignorent ce qui est déjà là : c'est bon marché.
    """
    missing = missing_tools()
    need_daemon = daemon_missing() or force_daemon

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


def emulator_ready(arch: str) -> bool:
    """Vrai si l'émulateur (et, pour arm64, un firmware UEFI AAVMF) est là."""
    if shutil.which(EMULATOR_BINARY[arch]) is None:
        return False
    if arch == "arm64":
        return any(os.path.exists(p) for p in AARCH64_FIRMWARE_PATHS)
    return True


def ensure_emulator(
    arch: str, runner: Runner, assume_yes: bool, no_install: bool
) -> None:
    """Vérifie l'émulateur QEMU système pour `arch` (et le firmware UEFI pour
    arm64), requis quand on émule une architecture différente de l'hôte ;
    l'installe au besoin via le gestionnaire de paquets."""
    binary = EMULATOR_BINARY[arch]
    if emulator_ready(arch):
        return
    pm = detect_pkg_manager()
    if pm is None:
        sys.exit(
            f"  Émulateur {arch} introuvable ({binary}) et gestionnaire de "
            "paquets non reconnu.\n  Installez-le manuellement."
        )
    pm_key, install_cmd, use_sudo, refresh = pm
    packages = EMULATOR_PACKAGES.get(arch, {}).get(pm_key, [])
    if not packages:
        sys.exit(
            f"  Émulateur {arch} introuvable ({binary}) : installez le paquet "
            "QEMU système correspondant de votre distribution "
            "(+ firmware UEFI pour arm64)."
        )
    full_cmd = install_cmd + packages
    printable = ("sudo " if use_sudo and runner.use_sudo else "") + " ".join(
        full_cmd
    )
    print(f"  Émulateur {arch} manquant ({binary}).")
    print(f"  Commande d'installation : {printable}")
    if no_install:
        sys.exit(
            "  Installation automatique désactivée (--no-install-deps).\n"
            "  Installez manuellement : " + printable
        )
    if not assume_yes and not prompt_yes_no(
        f"  Installer l'émulateur {arch} maintenant ?"
    ):
        sys.exit("  Installation refusée.\n  Commande manuelle : " + printable)
    if refresh:
        runner.run(refresh, privileged=use_sudo, check=False)
    runner.run(full_cmd, privileged=use_sudo)
    if not emulator_ready(arch):
        sys.exit(
            f"  Émulateur {arch} ({binary}) ou firmware toujours absent après "
            f"installation.\n  Essayez manuellement : {printable}"
        )
    print(f"  Émulateur {arch} installé avec succès.")


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
    # Vérifie la COMPLÉTUDE : si le serveur a annoncé une taille et qu'on a
    # reçu moins (connexion coupée), le .part est TRONQUÉ. Sans ce contrôle,
    # il était validé comme « complet » -> qcow2 valide mais VIDE (juste
    # l'en-tête) -> VM qui ne boote pas, et cache empoisonné réutilisé ensuite.
    if total > 0 and done < total:
        raise OSError(
            f"téléchargement incomplet : {done}/{total} octets reçus "
            "(connexion interrompue)"
        )


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
    # Chemin visé + commande prête à copier pour reprendre le téléchargement
    # manuellement (reprise si un .part existe), puis relancer le déploiement
    # (l'image complète en cache sera réutilisée). curl -C - reprend, -f
    # échoue proprement sur une erreur HTTP.
    resume = (
        f"\n  Destination : {dest}"
        f"\n  Reprendre le téléchargement manuellement :"
        f"\n    sudo curl -fL -C - -o {dest} \\\n      {urls[0]}"
        "\n  puis relancez le déploiement (l'image en cache sera réutilisée)."
    )
    sys.exit(
        "\nÉchec du téléchargement depuis tous les miroirs :\n  "
        + "\n  ".join(errors)
        + hint
        + resume
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


# Miroirs apt, du plus rapide au dernier recours. cloud-init prend le PREMIER
# joignable de la liste « search » : l'ordre est donc la priorité.
#
# Mesuré depuis Montréal sur l'index main/s390x (1,6 Mo) :
#   ports.ubuntu.com              1,61 s   1,0 Mo/s
#   mirror.csclub.uwaterloo.ca    0,32 s   5,2 Mo/s
#   mirror.us.leaseweb.net        0,88 s   1,9 Mo/s
#
# Le chemin diffère selon l'architecture : les arches « ports » (s390x, arm64,
# ppc64el, riscv64) ne sont PAS sur archive.ubuntu.com, et amd64 n'est pas sur
# ports.ubuntu.com. Une seule liste servirait donc la moitié des cas en 404.
APT_MIRRORS_PORTS = [
    "http://mirror.csclub.uwaterloo.ca/ubuntu-ports",
    "http://mirror.us.leaseweb.net/ubuntu-ports",
    "http://ports.ubuntu.com/ubuntu-ports",
]
APT_MIRRORS_MAIN = [
    "http://mirror.csclub.uwaterloo.ca/ubuntu",
    "http://mirror.us.leaseweb.net/ubuntu",
    "http://archive.ubuntu.com/ubuntu",
]
PORTS_ARCHES = ("s390x", "arm64", "aarch64", "ppc64el", "riscv64")


def apt_mirror_lines(arch: str, override: str | None = None) -> list[str]:
    """Bloc « apt: » du cloud-config, ou [] si rien à écrire.

    Ubuntu seulement : Debian, Fedora et Arch ont leurs propres dépôts, et
    « search » y écrirait des URI qui n'existent pas.
    """
    mirrors = (
        [override]
        if override
        else (APT_MIRRORS_PORTS if arch in PORTS_ARCHES else APT_MIRRORS_MAIN)
    )
    lines = ["apt:", "  primary:", "    - arches: [default]", "      search:"]
    lines += [f"        - {m}" for m in mirrors]
    # La sécurité suit le même dépôt pour les arches ports ; sur amd64 elle a
    # son propre hôte, que les miroirs répliquent sous le même chemin.
    lines += ["  security:", "    - arches: [default]", "      search:"]
    lines += [f"        - {m}" for m in mirrors]
    return lines


def kvm_available() -> bool:
    """L'accélération matérielle est-elle réellement utilisable ici ?

    « Même architecture que l'hôte » ne suffit PAS à conclure à KVM : dans une
    VM sans virtualisation imbriquée, libvirt bascule SILENCIEUSEMENT en TCG.
    Mesuré sur erplibre01, lui-même invité KVM : une VM s390x sur hôte s390x
    est sortie en « <domain type='qemu'> », soit de l'émulation intégrale — et
    un démarrage de 7 min 30 au lieu de quelques dizaines de secondes, sans
    que rien ne le signale.

    /dev/kvm est le test que fait QEMU lui-même. Mais l'ACCÈS n'est concluant
    que si on est root : libvirt, lui, tourne en root et se moque de notre
    appartenance au groupe kvm. Tester nos propres droits en non-root ferait
    crier « pas de KVM » à un utilisateur simplement hors du groupe.
    """
    if not os.path.exists("/dev/kvm"):
        return False
    if os.geteuid() == 0:
        return os.access("/dev/kvm", os.R_OK | os.W_OK)
    return True


def nested_module() -> str:
    """Module noyau portant le paramètre « nested » sur CET hôte.

    Le nom change selon l'architecture, et se tromper de module fait lire un
    « 0 » rassurant sur un fichier qui ne commande rien : s390x et arm64
    l'exposent sur « kvm », x86 sur « kvm_intel » ou « kvm_amd » selon le
    fabricant — et /sys/module/kvm/parameters/nested n'y existe même pas.
    """
    arch = host_arch()
    if arch != "amd64":
        return "kvm"
    try:
        info = Path("/proc/cpuinfo").read_text(errors="replace")
    except OSError:
        return "kvm_intel"
    return "kvm_amd" if " svm" in info else "kvm_intel"


def host_timezone() -> str:
    """Fuseau de l'hôte, au format zoneinfo (« America/Montreal »).

    Défaut des VM déployées : une VM qui hérite du fuseau de la machine qui la
    crée horodate ses journaux, ses commits et ses bases comme son opérateur.
    Sans cela elle démarre en UTC, ce qui ne se voit qu'après coup — des commits
    à +0000 alors que tout le reste du dépôt est en -0400.

    Trois sources, de la plus fiable à la plus rustique ; « UTC » en dernier
    recours plutôt qu'une exception, car un fuseau indéterminable ne doit pas
    empêcher un déploiement.
    """
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        tz = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if tz:
            return tz
    except OSError:
        pass
    try:
        # /etc/localtime est un lien vers /usr/share/zoneinfo/<Zone>
        target = Path("/etc/localtime").resolve()
        parts = target.parts
        if "zoneinfo" in parts:
            return "/".join(parts[parts.index("zoneinfo") + 1 :])
    except OSError:
        pass
    return "UTC"


# Groupes qui donnent accès au GPU DANS L'INVITÉ. Le nœud de rendu y
# appartient à « root:render » en 0660, et le compte créé par cloud-init n'en
# fait pas partie : toute application GL retombe alors sur le rendu logiciel,
# alors même que la négociation VIRGL entre l'hôte et l'invité a réussi. Rien
# ne le signale — le matériel virtuel est bien accéléré, seul l'accès manque.
#
# En session graphique locale, logind pose une ACL sur le nœud pour
# l'utilisateur du siège actif et la question ne se pose pas. En SSH ou en
# tty — le cas d'une VM de ce parc — personne ne la pose.
GPU_GROUPS = ("render", "video")


def gpu_group_block() -> list[str]:
    """Bloc « groups: » qui CRÉE les groupes GPU avant leur usage.

    « useradd -G » échoue sur un nom de groupe inconnu, et cloud-init ne crée
    alors pas l'utilisateur du tout : ni mot de passe ni clé SSH, la VM démarre
    et reste inaccessible. « render » est récent et manque des images les plus
    anciennes, donc l'ajouter sans précaution rejouerait cette panne.

    Le déclarer ici le rend certain d'exister : cloud-init crée les groupes
    AVANT les comptes, et passe sans erreur sur ceux qui existent déjà. Le
    groupe est retrouvé par NOM par les règles udev, donc un GID choisi par
    cloud-init plutôt que par la distribution ne change rien.
    """
    return ["groups:"] + [f"  - {nom}" for nom in GPU_GROUPS]


def user_groups(distro: str, gpu: bool = False) -> str:
    """Groupes secondaires du compte créé par cloud-init.

    Le nom du groupe d'administration change d'une famille à l'autre, et un
    nom INCONNU fait échouer « useradd -G » : l'utilisateur n'est alors pas
    créé du tout, donc ni mot de passe ni clé SSH, et la VM démarre
    inaccessible. Le privilège vient de toute façon de la directive « sudo: »
    du cloud-config, pas du groupe — celui-ci n'est qu'une commodité.

    - Debian, Ubuntu : « sudo ».
    - Famille RHEL (AlmaLinux, Rocky, CentOS, Fedora), Arch : « wheel ».
    - openSUSE : aucun. Son cloud-init par défaut n'en met pas, et rien ne
      garantit « wheel » sur une image Minimal-VM — dans le doute on s'abstient
      plutôt que de risquer un compte non créé."""
    if distro in ("ubuntu", "debian"):
        noms = ["users", "sudo"]
    elif distro == "opensuse":
        noms = ["users"]
    else:
        noms = ["users", "wheel"]
    if gpu:
        noms += list(GPU_GROUPS)
    return ", ".join(noms)


# --------------------------------------------------------------------------- #
# Guide de connexion (/etc/motd) et identité git de la VM
# --------------------------------------------------------------------------- #
# Le catalogue couvre quatre gestionnaires de paquets, et l'opérateur change de
# distribution d'un déploiement à l'autre. Le guide met SOUS LES YEUX, à la
# connexion, les commandes de la machine où l'on vient d'entrer : apt là où
# c'est apt, zypper là où c'est zypper.
#
# Le mécanisme est /etc/motd, et il est le même partout. Vérifié dans les images
# cloud elles-mêmes, montées en lecture seule : sshd y est en « PrintMotd no »
# et c'est pam_motd qui affiche le fichier. Trois conséquences tenues pour
# acquises ici :
#   - il suffit d'ÉCRIRE /etc/motd. Ajouter « PrintMotd yes » afficherait le
#     guide DEUX FOIS — sshd lit /etc/motd en dur, PAM le lit aussi ;
#   - « ssh hôte 'commande' » ne l'affiche PAS (openssh coupe les deux chemins
#     dès qu'une commande est passée), donc le suivi d'installation reste net.
#     Un « ssh hôte < script » l'afficherait, lui : aucun n'est utilisé ici ;
#   - openSUSE ajoute son « Have a lot of fun... » APRÈS le guide : il vient de
#     /usr/lib/motd.d/welcome, que pam_motd lit après le fichier. On le laisse.
#
# Ubuntu n'a PAS de /etc/motd (son postinst base-files ne le crée pas, à la
# différence de Debian) : le fichier est donc créé, pas remplacé. Sur Debian il
# écrase les cinq lignes de base-files, ce qui ne fâche pas dpkg — /etc/motd n'y
# est ni un conffile ni même un fichier du paquet.

# Étiquette lisible d'une distribution. openSUSE livre DEUX produits sous un
# seul nom de distro (Leap, numéroté ; Tumbleweed, rolling) : la version tranche.
DISTRO_LABELS: dict[str, str] = {
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "fedora": "Fedora",
    "almalinux": "AlmaLinux",
    "rocky": "Rocky Linux",
    "opensuse": "openSUSE",
    "arch": "Arch Linux",
    "proxmox": "Proxmox VE",
}

# Gestionnaire de paquets de chaque distribution du catalogue.
DISTRO_PKG: dict[str, str] = {
    "ubuntu": "apt",
    "debian": "apt",
    "fedora": "dnf",
    "almalinux": "dnf",
    "rocky": "dnf",
    "opensuse": "zypper",
    "arch": "pacman",
    # Debian dessous : c'est apt qui sert, et le guide de connexion le dit.
    "proxmox": "apt",
}


def distro_label(distro: str, version: str) -> str:
    """« Ubuntu 24.04 », « openSUSE Leap 16.0 », « Arch Linux »…"""
    name = DISTRO_LABELS.get(distro, distro)
    if distro == "opensuse":
        if version == "tumbleweed":
            return f"{name} Tumbleweed"
        return f"{name} Leap {version}"
    if distro == "arch":
        # Rolling release : « latest » n'apprend rien à personne.
        return name
    return f"{name} {version}"


# Aide-mémoire par gestionnaire de paquets : (commande, glose fr, glose en).
# Chaque ligne vient du manuel amont de l'outil, pas de mémoire, et doit
# fonctionner TELLE QUELLE — c'est un guide, pas une piste à vérifier.
#
# dnf : les formes écrites ici valent pour dnf4 (AlmaLinux/Rocky 9 ET 10, tous
# deux en dnf 4.x) comme pour dnf5 (Fedora 41+). Les raccourcis de dnf4 ont
# disparu de dnf5 : « dnf history » seul, « grouplist », « whatprovides »,
# « list installed » sans tirets y échouent tous. Les formes longues passent
# partout, et ne coûtent rien.
PKG_GUIDE: dict[str, tuple[tuple[str, str, str], ...]] = {
    "apt": (
        ("sudo apt update", "rafraîchir l'index", "refresh the index"),
        (
            "sudo apt upgrade",
            "mettre à jour le système",
            "upgrade the system",
        ),
        ("sudo apt install <paquet>", "installer", "install"),
        ("sudo apt remove <paquet>", "retirer", "remove"),
        ("apt search <motif>", "chercher", "search"),
        ("apt show <paquet>", "détails d'un paquet", "package details"),
        ("apt list --installed", "lister l'installé", "list installed"),
        ("sudo apt autoremove", "purger les orphelins", "purge orphans"),
    ),
    "dnf": (
        (
            "sudo dnf upgrade",
            "mettre à jour le système",
            "upgrade the system",
        ),
        ("sudo dnf install <paquet>", "installer", "install"),
        ("sudo dnf remove <paquet>", "retirer", "remove"),
        ("dnf check-update", "mises à jour disponibles", "available updates"),
        ("dnf search <motif>", "chercher", "search"),
        ("dnf info <paquet>", "détails d'un paquet", "package details"),
        ("dnf list --installed", "lister l'installé", "list installed"),
        ("dnf history list", "journal des opérations", "transaction log"),
    ),
    "pacman": (
        (
            "sudo pacman -Syu",
            "mettre à jour le système",
            "upgrade the system",
        ),
        # Jamais « -Sy » seul : la base de paquets serait à jour et le système
        # non, donc une installation tirerait des binaires liés à des
        # bibliothèques absentes. Arch ne supporte que la mise à jour complète,
        # d'où la forme « -Syu <paquet> » pour installer.
        (
            "sudo pacman -Syu <paquet>",
            "installer (jamais « -Sy » seul)",
            "install (never a bare « -Sy »)",
        ),
        ("sudo pacman -Rns <paquet>", "retirer", "remove"),
        ("pacman -Ss <motif>", "chercher", "search"),
        ("pacman -Si <paquet>", "détails d'un paquet", "package details"),
        ("pacman -Q", "lister l'installé", "list installed"),
        ("pacman -Qdtq", "orphelins", "orphans"),
        ("sudo pacman -Sc", "nettoyer le cache", "clean the cache"),
    ),
}


# Assistant AUR posé sur l'invité Arch par l'amorçage d'installation. Les
# formes viennent du manuel de yay : il reprend les options de pacman, sauf
# « -Yc » qui lui est propre. Jamais sous sudo — yay appelle sudo lui-même
# pour la seule étape qui en a besoin, et le lancer en root fait échouer
# makepkg, qui refuse de construire sous cet utilisateur.
AUR_GUIDE: tuple[tuple[str, str, str], ...] = (
    ("yay -Syu", "mettre à jour dépôts + AUR", "upgrade repos and AUR"),
    ("yay -S <paquet>", "installer depuis l'AUR", "install from the AUR"),
    ("yay -Ss <motif>", "chercher dans l'AUR", "search the AUR"),
    ("yay -Yc", "retirer les orphelins", "remove orphans"),
)


def zypper_guide(rolling: bool) -> tuple[tuple[str, str, str], ...]:
    """Aide-mémoire zypper. `rolling` : Tumbleweed plutôt que Leap.

    La ligne de mise à jour n'est PAS la même, et ce n'est pas une préférence de
    style : « up » sur Leap, dont la version est figée, et « dup » sur
    Tumbleweed, où chaque mise à jour est un instantané complet de la
    distribution. La doc amont est catégorique — « on Tumbleweed you will never
    have to use zypper-up » — et « up » y laisse traîner des paquets retirés des
    dépôts, donc des dépendances bancales. Le déploiement sait laquelle des deux
    il installe : autant que le guide le sache aussi.
    """
    upgrade = (
        ("sudo zypper dup", "mettre à jour (rolling)", "upgrade (rolling)")
        if rolling
        else (
            "sudo zypper up",
            "mettre à jour le système",
            "upgrade the system",
        )
    )
    return (
        ("sudo zypper ref", "rafraîchir les dépôts", "refresh the repos"),
        upgrade,
        ("sudo zypper in <paquet>", "installer", "install"),
        ("sudo zypper rm <paquet>", "retirer", "remove"),
        ("zypper se <motif>", "chercher", "search"),
        ("zypper info <paquet>", "détails d'un paquet", "package details"),
        ("zypper se -i", "lister l'installé", "list installed"),
        ("zypper lu", "mises à jour disponibles", "available updates"),
        (
            "sudo zypper ps -s",
            "à redémarrer après MAJ",
            "restart after upgrade",
        ),
    )


# Lignes valables partout, quelle que soit la distribution.
SYSTEM_GUIDE: tuple[tuple[str, str, str], ...] = (
    ("hostname -I", "adresse IP de la VM", "the VM's IP address"),
    ("df -h /", "espace disque", "disk space"),
    ("free -h", "mémoire", "memory"),
)
# Ajoutées SEULEMENT quand il n'y a pas de section ERPLibre : celle-ci montre
# déjà les deux commandes, sur un service qui existe vraiment. Sur une VM
# déployée sans ERPLibre, elles manqueraient.
SERVICE_GUIDE: tuple[tuple[str, str, str], ...] = (
    ("systemctl status <service>", "état d'un service", "a service's state"),
    ("journalctl -u <service> -f", "suivre son journal", "follow its log"),
)


# N'apparaît que sur une VM déployée AVEC un bureau. Vécu : GNOME installé,
# gdm3 installé, cible graphique par défaut… et la console restait en mode texte.
# graphical.target était déjà atteinte quand le paquet est arrivé, et une cible
# active ne rattrape pas un service ajouté après coup. « enable » seul n'y change
# rien sur Debian et Ubuntu — l'unité n'a pas de WantedBy, seulement un alias —
# d'où le « --now », qui démarre.
DESKTOP_GUIDE: tuple[tuple[str, str, str], ...] = (
    (
        "systemctl status display-manager",
        "état du bureau graphique",
        "graphical desktop state",
    ),
    (
        "sudo systemctl enable --now gdm",
        "le démarrer (« --now » : enable seul ne suffit pas)",
        'start it ("--now": enable alone does nothing)',
    ),
)


def erplibre_guide(
    el_dir: str, el_make: str = "", editor: str = ""
) -> tuple[tuple[str, str, str], ...]:
    """Commandes ERPLibre de la VM.

    `el_dir` : racine de l'installation (~/git/erplibre en développement,
    /opt/erplibre en production). Toutes les autres lignes sont relatives à ce
    répertoire, d'où le « cd » en tête.

    `el_make` : cible make qui a installé la VM, réutilisée pour la mettre à
    jour. Vide, le guide s'arrête à « git pull » plutôt que d'annoncer une cible
    qui n'est pas celle du profil retenu.

    `editor` : éditeur de l'hôte, quand il a pu être déterminé. Sans lui on
    nomme le fichier de configuration sans nommer d'éditeur — « vi » n'est pas
    garanti sur toutes les images cloud, et un guide qui propose une commande
    absente est pire que muet.
    """
    rows = [
        (f"cd {el_dir}", "aller au dépôt", "go to the checkout"),
        ("make todo", "menu ERPLibre (TODO)", "ERPLibre menu (TODO)"),
    ]
    if editor:
        rows.append(
            (
                f"{editor} config.conf",
                "éditer le serveur",
                "edit the server",
            )
        )
    else:
        rows.append(
            (
                "config.conf",
                "configuration du serveur",
                "the server's config",
            )
        )
    rows += [
        (
            "sudo systemctl restart erplibre",
            "redémarrer le serveur",
            "restart the server",
        ),
        ("systemctl status erplibre", "état du serveur", "server state"),
        ("journalctl -u erplibre -f", "suivre son journal", "follow its log"),
        ("./run.sh -d <base>", "lancer à la main", "run it by hand"),
        (
            "./script/addons/update_addons_all.sh <base>",
            "mise à jour des modules",
            "update the modules",
        ),
        (
            f"git pull && make {el_make}" if el_make else "git pull",
            (
                "mise à jour ERPLibre/Odoo"
                if el_make
                else "mettre à jour le dépôt"
            ),
            "update ERPLibre/Odoo" if el_make else "update the checkout",
        ),
        ("http://<ip>:8069", "interface web", "web interface"),
    ]
    return tuple(rows)


# Plancher de largeur de l'encadré. Au-dessus, il SUIT le contenu : un cadre
# plus étroit que ce qu'il encadre serait pire qu'un cadre large. C'est au
# contenu de rester sous 80 colonnes — un guide qui se replie sur un terminal
# standard est illisible, et un test le vérifie pour les sept distributions.
MOTD_MIN_WIDTH = 62


def _pick(pair: tuple[str, str], lang: str) -> str:
    """Membre fr ou en d'un couple de libellés."""
    return pair[1] if lang == "en" else pair[0]


def gloss_col(*blocks: tuple[tuple[str, str, str], ...]) -> int:
    """Colonne où commencent les gloses de ces blocs : la commande la plus
    longue, plus deux espaces."""
    return max(len(cmd) for rows in blocks for cmd, _fr, _en in rows) + 2


def motd_block(
    title: str, rows: tuple[tuple[str, str, str], ...], lang: str, col: int
) -> list[str]:
    """Un bloc du guide : un titre, puis « commande <espaces> glose » alignées.

    `col` est donné plutôt que déduit du bloc : les blocs de commandes courtes
    partagent une colonne commune, sans quoi le bloc « système » se tasserait à
    treize caractères là où celui des paquets en occupe trente. Le bloc
    ERPLibre, lui, garde la sienne — sa commande la plus longue fait
    43 caractères, et l'imposer au guide entier ferait déborder les lignes de
    80 colonnes.
    """
    out = [f"  {title}"]
    for cmd, gloss_fr, gloss_en in rows:
        out.append(f"    {cmd.ljust(col)}{_pick((gloss_fr, gloss_en), lang)}")
    return out


def build_motd(
    distro: str,
    version: str,
    arch: str,
    lang: str = "fr",
    el_dir: str = "",
    el_make: str = "",
    editor: str = "",
    desktop: bool = False,
) -> str:
    """Texte du /etc/motd de la VM. Fonction PURE : aucun I/O, donc testable.

    La section ERPLibre n'apparaît qu'avec `el_dir` : une VM déployée sans
    installation ne doit pas annoncer un dépôt et un service qui n'existent pas.
    Le bloc « Bureau » suit la même règle avec `desktop` : sur un serveur, ces
    deux commandes ne mèneraient à aucune unité.
    """
    body: list[str] = []
    mgr = DISTRO_PKG.get(distro, "")
    if mgr == "zypper":
        pkg_rows = zypper_guide(version == "tumbleweed")
    else:
        pkg_rows = PKG_GUIDE.get(mgr, ())
    sys_rows = SYSTEM_GUIDE if el_dir else SYSTEM_GUIDE + SERVICE_GUIDE
    narrow = gloss_col(pkg_rows or sys_rows, sys_rows)
    if pkg_rows:
        body += motd_block(
            f"{_pick(('Paquets', 'Packages'), lang)} — {mgr}",
            pkg_rows,
            lang,
            narrow,
        )
    # yay arrive avec l'amorçage d'installation, pas avec l'image : une VM
    # déployée sans installation n'annonce donc pas une commande absente.
    # C'est la règle du bloc ERPLibre ci-dessous, appliquée au même signal.
    if mgr == "pacman" and el_dir:
        body.append("")
        body += motd_block("AUR — yay", AUR_GUIDE, lang, narrow)
    if el_dir:
        body.append("")
        el_rows = erplibre_guide(el_dir, el_make, editor)
        body += motd_block("ERPLibre", el_rows, lang, gloss_col(el_rows))
    if desktop:
        body.append("")
        body += motd_block(
            _pick(("Bureau", "Desktop"), lang),
            DESKTOP_GUIDE,
            lang,
            gloss_col(DESKTOP_GUIDE),
        )
    body.append("")
    body += motd_block(
        _pick(("Système", "System"), lang), sys_rows, lang, narrow
    )
    title = f"ERPLibre · {distro_label(distro, version)} · {arch}"
    width = max(
        MOTD_MIN_WIDTH, max([len(line) for line in body] + [len(title)]) + 4
    )
    head = [
        "╭" + "─" * (width - 2) + "╮",
        "│ " + title.ljust(width - 4) + " │",
        "╰" + "─" * (width - 2) + "╯",
    ]
    foot = [
        "",
        "  "
        + _pick(
            (
                "Guide écrit au déploiement par",
                "Guide written at deploy time by",
            ),
            lang,
        )
        + " script/qemu/deploy_qemu.py",
    ]
    return "\n".join(head + [""] + body + foot) + "\n"


def invoking_home() -> Path:
    """Foyer de l'utilisateur qui a lancé le script, sudo compris.

    Le script tourne sous sudo : `Path.home()` y renvoie /root, où il n'y a
    aucune configuration git à reprendre.
    """
    try:
        return Path(os.path.expanduser(f"~{invoking_user()}"))
    except (KeyError, RuntimeError):
        return Path.home()


def _git_global(key: str, home: Path) -> str:
    """Valeur d'une clé de la configuration git GLOBALE de `home`.

    HOME est forcé plutôt que de lire ~/.gitconfig à la main : git accepte DEUX
    emplacements pour sa configuration globale (~/.gitconfig et
    ~/.config/git/config), et lui poser la question évite de trancher à sa place.
    """
    try:
        res = subprocess.run(
            ["git", "config", "--global", "--get", key],
            capture_output=True,
            text=True,
            timeout=5,
            env=dict(os.environ, HOME=str(home)),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def host_editor(home: Path) -> str:
    """Éditeur que l'hôte utilise, dans l'ordre où git le résout lui-même.

    core.editor, puis $VISUAL/$EDITOR, puis /usr/bin/editor — le lien des
    alternatives Debian, qui est LA réponse à « quel éditeur ce système
    utilise-t-il » quand rien n'est configuré. Ailleurs ce lien n'existe pas et
    on ne devine pas : mieux vaut ne rien écrire que d'imposer un éditeur.

    GIT_EDITOR est volontairement IGNORÉ. Les outils qui appellent git sans
    interaction le posent à « true » pour empêcher toute ouverture d'éditeur ;
    le recopier dans la VM y désactiverait silencieusement l'éditeur de git.
    """
    editor = _git_global("core.editor", home)
    if not editor:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ""
    if not editor:
        try:
            editor = Path("/usr/bin/editor").resolve(strict=True).name
        except OSError:
            editor = ""
    return editor.strip()


def editor_binary(editor: str) -> str:
    """Binaire seul d'une commande d'éditeur (« code --wait » -> « code »).

    Le guide affiche le binaire, pas la commande complète : les options de git
    (attente de fermeture, fichier temporaire) n'ont pas de sens pour ouvrir un
    fichier de configuration à la main.
    """
    if not editor.strip():
        return ""
    return editor.split()[0].rsplit("/", 1)[-1]


# Éditeurs que la VM sait se donner : binaire de l'hôte -> (paquet, binaire dans
# la VM). Le nom du paquet est le MÊME sur apt, dnf, zypper et pacman pour ces
# trois-là — vérifié pour chacun ; « vi » est fourni par vim, et le paquet
# neovim installe « nvim ».
#
# Cette table est la SEULE autorité, et elle décide de trois choses à la fois :
# le paquet que l'installation ajoute, la commande que le guide affiche, et la
# valeur de core.editor dans la VM. Les tenir liées est le point : un
# « core.editor = code » pointant un binaire absent fait échouer « git commit »
# (« cannot run code »), et un guide qui nomme une commande absente est pire que
# muet. Un éditeur hors de cette table est donc ignoré — pas deviné.
EDITOR_PACKAGES: dict[str, tuple[str, str]] = {
    "vim": ("vim", "vim"),
    "vi": ("vim", "vim"),
    "nvim": ("neovim", "nvim"),
    "neovim": ("neovim", "nvim"),
    "nano": ("nano", "nano"),
}


def vm_editor(home: Path) -> tuple[str, str]:
    """(paquet, binaire) de l'éditeur à donner à la VM, ou deux chaînes vides."""
    return EDITOR_PACKAGES.get(editor_binary(host_editor(home)), ("", ""))


def build_gitconfig(name: str, email: str, editor: str) -> str:
    """~/.gitconfig de la VM. Chaîne vide si l'hôte n'a rien à transmettre.

    Une VM de développement sert à produire des commits, et un commit sans
    identité est refusé par git (« Please tell me who you are ») : reprendre
    celle de l'hôte évite de la retaper sur chaque machine, et surtout évite les
    commits signés d'un « erplibre@<nom-de-vm> » que personne ne reconnaît.

    INDENTATION EN ESPACES, jamais en tabulation. git accepte les deux, mais ce
    texte part dans un scalaire bloc YAML où une tabulation en tête de ligne est
    une erreur FATALE : cloud-init rejette alors le user-data en entier et la VM
    démarre sans utilisateur ni clé SSH, donc inaccessible.
    """
    lines: list[str] = []
    if name or email:
        lines.append("[user]")
        if name:
            lines.append(f"    name = {name}")
        if email:
            lines.append(f"    email = {email}")
    if editor:
        lines += ["[core]", f"    editor = {editor}"]
    return "\n".join(lines) + "\n" if lines else ""


def write_files_lines(
    entries: list[tuple[str, str, str, str]],
) -> list[str]:
    """Bloc « write_files » de cloud-init pour des fichiers TEXTE.

    entries : (chemin, mode, contenu, propriétaire) ; propriétaire vide = root.

    Deux règles YAML dont le non-respect coûte TOUTE la configuration — une
    erreur de syntaxe fait rejeter le user-data en ENTIER, sans message sur la
    console : la VM démarre nue, sans utilisateur ni clé SSH, inaccessible.
      - Le mode est une CHAÎNE, entre guillemets. « permissions: 644 » non quoté
        est lu comme 644 DÉCIMAL et appliqué tel quel, soit 0o1204 soit le bit
        setuid allumé et des droits absurdes, sans le moindre avertissement.
      - Le contenu est un scalaire bloc « | » indenté de six espaces, dont la
        PREMIÈRE ligne non vide fixe l'indentation de référence : les suivantes
        doivent être au moins aussi indentées. Les caractères d'encadrement
        UTF-8 passent sans échappement.

    Un propriétaire impose « defer: true » : write_files tourne à l'étape init,
    AVANT la création des utilisateurs, donc le chown vers le compte de la VM
    échouerait. Reporté à l'étape finale, il passe — et le suivi d'installation
    attend de toute façon la fin de cloud-init avant de se connecter.
    """
    out = ["write_files:"]
    for path, mode, content, owner in entries:
        out.append(f"  - path: {path}")
        out.append(f"    permissions: '{mode}'")
        if owner:
            out.append(f"    owner: {owner}:{owner}")
            out.append("    defer: true")
        out.append("    content: |")
        # textwrap.indent laisse les lignes vides VIDES : six espaces résiduels
        # survivraient au scalaire bloc et se retrouveraient dans le fichier,
        # invisibles en revue et bien présents à l'écran.
        out += textwrap.indent(content.rstrip("\n"), "      ").split("\n")
    return out


# Préfixe des fichiers d'accueil embarqués dans l'initrd de l'installateur.
# Un préfixe, et non un répertoire : le cpio est déplié séquentiellement et les
# répertoires parents manquants ne sont pas créés — une entrée
# « erplibre/etc-motd » sans entrée « erplibre » ferait échouer le dépliage de
# l'initrd ENTIER, donc l'installation. Les fichiers restent à la racine.
INSTALLER_GUIDE_PREFIX = "erplibre-"


def installer_guide_name(path: str) -> str:
    """Nom dans l'initrd du fichier destiné au chemin `path` de la VM.

    « /etc/motd » -> « erplibre-etc-motd ». Un nom PLAT, dérivé du chemin : les
    deux fonctions qui s'en servent (le preseed qui copie, l'initrd qui range)
    le calculent de la même façon, donc elles ne peuvent pas diverger.
    """
    return INSTALLER_GUIDE_PREFIX + path.strip("/").replace("/", "-")


# Où chaque famille de distribution range ses ancres de confiance, et par
# quelle commande elle les relit. La même table vit dans
# script/qemu_cache/rules.go, côté cache ; un test les compare, la dérive
# entre deux copies étant le seul risque de cette duplication.
#
# Les familles portent le nom de leur gestionnaire de paquets, comme
# « _QEMU_DISTRO_FAMILY » du menu.
# Trois valeurs par famille : où poser l'ancre, quelle commande relit le
# magasin, et quel FAISCEAU cette commande régénère.
CACHE_TRUST = {
    "pacman": (
        "/etc/ca-certificates/trust-source/anchors",
        "trust extract-compat",
        "/etc/ssl/certs/ca-certificates.crt",
    ),
    "apt": (
        "/usr/local/share/ca-certificates",
        "update-ca-certificates",
        "/etc/ssl/certs/ca-certificates.crt",
    ),
    "dnf": (
        "/etc/pki/ca-trust/source/anchors",
        "update-ca-trust",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ),
    "zypper": (
        "/etc/pki/trust/anchors",
        "update-ca-certificates",
        "/etc/ssl/certs/ca-certificates.crt",
    ),
}

# pip embarque son propre jeu de certificats et IGNORE le magasin système ;
# npm fait de même. Poser l'autorité suffit à pacman et à apt, pas à eux.
#
# Les variables visent le FAISCEAU, non le certificat du cache : pointer
# celui-là ferait perdre à pip toutes les autres autorités — il échouerait sur
# le premier hôte que le cache ne déchiffre pas, et le jour où le cache
# disparaît alors que la VM garde sa variable.
CACHE_ENV_VARS = ("PIP_CERT", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")

CACHE_CERT_NAME = "erplibre-cache.crt"


def cache_family(distro: str) -> str:
    """Famille de gestionnaire de paquets d'une distribution du catalogue."""
    return {
        "ubuntu": "apt",
        "debian": "apt",
        "linuxmint": "apt",
        "fedora": "dnf",
        "almalinux": "dnf",
        "rocky": "dnf",
        "opensuse": "zypper",
        "arch": "pacman",
    }.get(distro, "")


def cache_files(args: argparse.Namespace) -> list[tuple[str, str, str, str]]:
    """L'autorité du cache, posée par cloud-init à l'étape init.

    Rend une liste vide quand aucune autorité n'est demandée, ou quand la
    distribution n'est pas dans la table : mieux vaut une VM qui télécharge
    en direct qu'une VM dont le magasin de confiance a reçu un fichier au
    mauvais endroit, où il ne servirait à rien sans que rien ne le dise.

    Le fichier est écrit à l'étape INIT, donc avant « runcmd » et avant tout
    téléchargement : ce dépôt n'installe aucun paquet par cloud-init et laisse
    « package_update » à faux, si bien que rien ne sort sur le réseau entre le
    démarrage et la commande de confiance.
    """
    if not args.cache_ca:
        return []
    famille = cache_family(args.distro)
    if famille not in CACHE_TRUST:
        return []
    try:
        with open(args.cache_ca, encoding="utf-8") as fh:
            pem = fh.read()
    except OSError:
        # Une autorité illisible ne doit pas faire échouer un déploiement :
        # sans elle, la VM télécharge en direct, ce qui marche.
        return []
    if "BEGIN CERTIFICATE" not in pem:
        return []
    anchors = CACHE_TRUST[famille][0]
    return [(f"{anchors}/{CACHE_CERT_NAME}", "0644", pem, "")]


def cache_runcmd(args: argparse.Namespace) -> list[str]:
    """Ce qui rend l'autorité effective, et ce que pip et npm exigent en plus.

    Deux gestes, dans cet ordre : relire le magasin de confiance, puis écrire
    les variables dans /etc/environment — que PAM lit pour TOUTE session ssh,
    interactive ou non, ce qui est la seule façon d'atteindre le bootstrap
    d'installation lancé par commande distante.
    """
    if not cache_files(args):
        return []
    _, commande, faisceau = CACHE_TRUST[cache_family(args.distro)]
    lignes = [f"  - {commande} || true"]
    for var in CACHE_ENV_VARS:
        lignes.append(
            f"  - sh -c 'grep -q ^{var}= /etc/environment"
            f" || echo {var}={faisceau} >> /etc/environment'"
        )
    return lignes


def guide_files(args: argparse.Namespace) -> list[tuple[str, str, str, str]]:
    """Fichiers d'accueil de la VM : le guide de connexion, l'identité git.

    Une seule source pour les deux voies de déploiement — cloud-init l'écrit
    par write_files, l'installateur Debian par son late_command.
    """
    home = invoking_home()
    editor = "" if args.no_git_identity else vm_editor(home)[1]
    files = [
        (
            "/etc/motd",
            "0644",
            build_motd(
                args.distro,
                args.version,
                args.arch,
                args.lang,
                args.erplibre_dir,
                args.erplibre_make,
                editor,
                bool(args.desktop),
            ),
            "",
        )
    ]
    if args.no_git_identity:
        return files
    # Ce que le formulaire a saisi PRIME sur l'identité de l'hôte, champ par
    # champ : remplir le seul courriel ne doit pas effacer le nom. Vide, on
    # retombe sur l'hôte, qui reste le comportement par défaut.
    gitconfig = build_gitconfig(
        getattr(args, "git_name", "") or _git_global("user.name", home),
        getattr(args, "git_email", "") or _git_global("user.email", home),
        editor,
    )
    if gitconfig:
        files.append(
            (f"/home/{args.user}/.gitconfig", "0644", gitconfig, args.user)
        )
    return files


def build_cloud_config(
    args: argparse.Namespace, pw_hash: str | None, ssh_keys: list[str]
) -> str:
    """Construit le contenu #cloud-config (user-data)."""
    lines: list[str] = ["#cloud-config", f"hostname: {args.hostname}"]

    # « off » est le seul refus explicite ; « auto » laisse l'hôte décider
    # s'il accélère, mais l'invité porte un virtio-gpu dans les deux cas et
    # l'appartenance aux groupes ne coûte rien quand elle ne sert pas.
    gpu = (getattr(args, "gpu", "auto") or "auto").lower() != "off"
    if gpu:
        lines += gpu_group_block()

    user_block = [
        "users:",
        f"  - name: {args.user}",
        "    sudo: ALL=(ALL) NOPASSWD:ALL",
        # Le groupe d'administration N'A PAS le même nom partout, et un nom
        # inconnu fait échouer « useradd -G » : l'utilisateur n'est alors jamais
        # créé, donc ni mot de passe ni clé SSH — la VM démarre et reste
        # inaccessible. C'était déjà la cause du « Debian ne marche pas »
        # (« admin » n'existe pas sur Debian) ; la famille RHEL et Arch ont le
        # même écart, elles n'ont pas de groupe « sudo » mais « wheel ».
        # Le privilège lui-même vient de la ligne « sudo: » ci-dessus, pas du
        # groupe : celui-ci n'est qu'une commodité.
        f"    groups: {user_groups(args.distro, gpu)}",
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
    lines.append(f"timezone: {args.timezone}")
    if getattr(args, "distro", "ubuntu") == "ubuntu":
        lines += apt_mirror_lines(
            getattr(args, "arch", "amd64"), getattr(args, "apt_mirror", None)
        )
    lines += [
        "keyboard:",
        f"  layout: {args.keyboard_layout}",
        f"  variant: {args.keyboard_variant}",
    ]
    # Guide de connexion et identité git : posés par cloud-init, donc présents
    # dès le PREMIER boot. C'est le point : ils sont là avant l'installation
    # d'ERPLibre, et encore là si elle échoue — le moment où l'on se connecte
    # justement à la main.
    lines += write_files_lines(guide_files(args) + cache_files(args))
    # apt update/upgrade désactivés par défaut : sur un réseau lent/instable
    # ils font pendre cloud-init au 1er boot (et retardent la dispo SSH). SSH
    # est déjà présent dans les images cloud ; on l'active via runcmd sans apt.
    # --apt-update réactive apt update (+ upgrade, sauf --no-upgrade).
    do_update = args.apt_update
    do_upgrade = args.apt_update and not args.no_upgrade
    lines.append(f"package_update: {'true' if do_update else 'false'}")
    lines.append(f"package_upgrade: {'true' if do_upgrade else 'false'}")

    # On n'installe AUCUN paquet via cloud-init : cela exige le réseau au 1er
    # boot et peut bloquer longtemps (dnf/apt/pacman lents sur réseau lent) —
    # cloud-init reste alors « running » et tout ce qui suit attend. sshd est
    # DÉJÀ présent dans toutes les images cloud (Ubuntu/Debian/Fedora/Arch) ;
    # on l'active seulement (runcmd). Les outils nécessaires (curl/git/make…)
    # sont installés — avec dépôts optimisés — par le bootstrap d'installation.
    packages = list(dict.fromkeys(args.package))  # seulement --package
    if packages:
        lines.append("packages:")
        lines += [f"  - {p}" for p in packages]
    # Active et démarre SSH quel que soit le nom du service (ssh sur
    # Debian/Ubuntu, sshd sur Fedora/Arch) — sans quoi la VM peut booter
    # sans SSH accessible.
    lines += ["runcmd:"]
    # En TÊTE : ce qui suit peut télécharger, et sans magasin de confiance à
    # jour un invité rejette le certificat que le cache présente.
    lines += cache_runcmd(args)
    lines += [
        "  - systemctl enable --now ssh 2>/dev/null"
        " || systemctl enable --now sshd 2>/dev/null || true",
        # Getty sur la console qui EXISTE VRAIMENT.
        #
        # Sur s390x, l'image attend /dev/ttysclp0 (généré depuis la ligne de
        # commande noyau) alors que le périphérique réellement présent porte un
        # autre nom : « Timed out waiting for device dev-ttysclp0.device », puis
        # « Dependency failed for serial-getty@ttysclp0 ». La console affiche
        # donc tout le démarrage mais n'offre AUCUNE invite de connexion — elle
        # est en lecture seule par accident, et c'est justement le seul recours
        # quand SSH ne répond pas. On active le getty sur le premier
        # périphérique console présent. Ailleurs (x86/arm64) ttyS0 existe et son
        # getty tourne déjà : « enable --now » n'y change rien.
        "  - for d in ttysclp0 sclp_line0 hvc0 ttyS0; do"
        " test -c /dev/$d && systemctl enable --now serial-getty@$d.service"
        " 2>/dev/null && break; done || true",
        # qemu-guest-agent : installé APRÈS sshd, et surtout HORS de cloud-init.
        #
        # Mesuré sur Ubuntu 26.04 s390x : « apt-get install qemu-guest-agent »
        # tire liburing2, ubuntu-helper-virt-hwe et ubuntu-virt depuis
        # ports.ubuntu.com, et cloud-final tourne 9 min 47. Or le suivi
        # d'installation attend « cloud-init status: done » : dix minutes
        # d'attente pour un paquet accessoire, avant même de commencer le
        # travail utile.
        #
        # systemd-run --no-block rend la main tout de suite : cloud-init termine
        # en quelques secondes et l'agent apparaît quand il apparaît. On saute
        # aussi l'installation quand qemu-ga est déjà là, ce qui est le cas de
        # beaucoup d'images. Repli en ligne si systemd-run manque.
        "  - command -v qemu-ga >/dev/null 2>&1 ||"
        " systemd-run --no-block --unit=erplibre-qga --collect"
        " /bin/sh -c 'command -v apt-get >/dev/null && { apt-get update -qq"
        " || true; apt-get install -y qemu-guest-agent; }"
        " || command -v dnf >/dev/null && dnf install -y qemu-guest-agent"
        " || command -v pacman >/dev/null && pacman -Sy --noconfirm"
        " qemu-guest-agent' 2>/dev/null"
        " || (command -v apt-get >/dev/null && (timeout 120 apt-get update -qq"
        " || true; timeout 300 apt-get install -y qemu-guest-agent)) ||"
        " (command -v dnf >/dev/null && timeout 300 dnf install -y"
        " qemu-guest-agent) || (command -v pacman >/dev/null && timeout 300"
        " pacman -Sy --noconfirm qemu-guest-agent) || true",
        # Autorise guest-exec (bloqué par défaut sur certaines distros).
        # On VIDE la liste de blocage (block-rpcs/blacklist) plutôt que
        # d'utiliser allow-rpcs (liste BLANCHE : casserait les autres RPC).
        # Les deux clés couvrent les versions anciennes (blacklist) et
        # récentes (block-rpcs) de qemu-ga.
        "  - mkdir -p /etc/qemu && printf '[general]\\nblock-rpcs=\\n"
        "blacklist=\\n' > /etc/qemu/qemu-ga.conf || true",
        # Fedora/RHEL bloquent guest-exec via /etc/sysconfig/qemu-ga.
        # « test -f » et NON « [ -f … ] » : en YAML, «  - [ » démarre une
        # séquence en flux -> user-data invalide -> cloud-init rejeté (aucun
        # utilisateur créé, VM figée, login console impossible).
        "  - test -f /etc/sysconfig/qemu-ga && sed -i"
        " 's/^BLACKLIST_RPC=.*/BLACKLIST_RPC=/'"
        " /etc/sysconfig/qemu-ga || true",
        "  - systemctl enable qemu-guest-agent 2>/dev/null"
        " || systemctl enable qemu-ga 2>/dev/null || true",
        # restart (et non enable --now) : recharge la config si l'agent était
        # déjà démarré par l'image cloud.
        "  - systemctl restart qemu-guest-agent 2>/dev/null"
        " || systemctl restart qemu-ga 2>/dev/null || true",
    ]
    return "\n".join(lines) + "\n"


# network-config (cloud-init v2) : DHCP sur toute interface « e* ». Les images
# Debian genericcloud ne configurent pas toujours le réseau sans ça (le NIC
# reste down -> pas d'IP), contrairement à Ubuntu. Inoffensif pour Ubuntu.
# La clé est « eth0 » car le renderer cloud-init d'Arch utilise la CLÉ comme
# nom d'interface (en ignorant « match ») et l'image Arch nomme son NIC eth0 ;
# Debian/Fedora/Ubuntu utilisent bien « match: name: e* » (leur en*).
NETWORK_CONFIG = (
    "version: 2\n"
    "ethernets:\n"
    "  eth0:\n"
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


def _ip_taken(ip: str) -> bool:
    """Adresse déjà occupée, même par une machine qui ne parle pas SSH.

    Un simple essai sur le port 22 ne suffit pas : il laisse passer toute
    machine éteinte au moment du choix, ou dont sshd est filtré. Vécu — une
    adresse attribuée à une VM Debian neuve appartenait déjà à une machine du
    parc, et l'installation ERPLibre s'est déroulée SUR CETTE DERNIÈRE. Le
    journal ne le disait qu'à demi-mot : « git is already the newest
    version », impossible sur un système que d-i vient de poser.

    On interroge donc trois choses : le voisinage ARP de l'hôte, qui connaît
    ce qui a parlé récemment ; ICMP, qui répond même sans service ; puis SSH.
    """
    try:
        neigh = subprocess.run(
            ["ip", "neigh", "show", ip],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        # « FAILED » signifie justement que personne n'a répondu.
        if ip in neigh and "FAILED" not in neigh:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        if (
            subprocess.run(
                ["ping", "-c", "1", "-W", "1", ip],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        ):
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return _ip_reachable(ip, port=22, timeout=1.5)


def static_net_plan(
    net: str | None, use_sudo: bool, name: str
) -> dict[str, str] | None:
    """Adresse fixe libre pour une VM installée par debian-installer.

    L'initrd s390x ne contient QUE « netcfg-static » : le journal de d-i
    montre « Menu item 'netcfg-static' selected », jamais netcfg-dhcp, puis
    « Taking down interface enc1 ». Aucun DHCP n'est tenté — c'est la
    convention IBM Z, où la configuration réseau se donne au parmfile. Il
    faut donc fournir une adresse, et elle doit être libre.

    On la prend en HAUT de la plage : dnsmasq attribue depuis le bas, donc
    les collisions avec un bail futur sont les plus improbables là.
    """
    if not net:
        return None
    cmd = ["virsh", "-c", LIBVIRT_URI, "net-dumpxml", net]
    if use_sudo:
        cmd.insert(0, "sudo")
    try:
        xml = subprocess.run(
            cmd, capture_output=True, text=True, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"<ip address='([\d.]+)' netmask='([\d.]+)'", xml)
    if not m:
        return None
    gateway, netmask = m.group(1), m.group(2)
    base = gateway.rsplit(".", 1)[0]
    taken = {gateway}
    lease_cmd = ["virsh", "-c", LIBVIRT_URI, "net-dhcp-leases", net]
    if use_sudo:
        lease_cmd.insert(0, "sudo")
    try:
        out = subprocess.run(
            lease_cmd, capture_output=True, text=True, timeout=20
        ).stdout
        taken |= set(re.findall(r"(\d+\.\d+\.\d+\.\d+)/\d+", out))
    except (OSError, subprocess.SubprocessError):
        pass
    # Départ DÉTERMINISTE, tiré du nom de la VM. Un simple « première libre
    # en partant du haut » donne la MÊME adresse à deux VM déployées en
    # parallèle : aucune des deux n'est encore montée quand l'autre cherche,
    # donc aucune ne voit l'autre. Vécu — debian-12 et debian-13 ont tous
    # deux pris .250 et se sont disputé l'adresse, une seule survivant.
    # Le nom, lui, diffère toujours, et le tirage reste stable d'un
    # redéploiement à l'autre.
    start = zlib.crc32(name.encode()) % 50
    for offset in range(50):
        last = 200 + (start + offset) % 50
        ip = f"{base}.{last}"
        if ip in taken or _ip_taken(ip):
            continue
        return {
            "ip": ip,
            "netmask": netmask,
            "gateway": gateway,
            "dns": gateway,
        }
    return None


def build_preseed(
    args: argparse.Namespace,
    pw_hash: str | None,
    ssh_keys: list[str],
    static: dict[str, str] | None = None,
) -> str:
    """Preseed debian-installer équivalent au cloud-config des autres distros.

    Il doit couvrir EXACTEMENT ce que cloud-init fait ailleurs : nom d'hôte,
    utilisateur, clés SSH, sudo sans mot de passe, fuseau, paquets de base.
    Tout ce qui manque ici devient une question posée à l'écran, et
    l'installation s'arrête sur une console que personne ne regarde.

    « priority=critical » suffit à ne pas poser les questions restantes ; il
    ne dispense PAS de répondre à celles qui n'ont pas de défaut, d'où le
    partitionnement et le miroir écrits explicitement.
    """
    user = args.user
    # Sans mot de passe utilisable, d-i s'arrête sur la création du compte :
    # « ! » est un hachage volontairement invalide — la connexion se fera par
    # clé, comme le cloud-config le prévoit lui aussi.
    crypted = pw_hash or "!"
    lines = [
        "d-i debian-installer/locale string en_US.UTF-8",
        "d-i keyboard-configuration/xkb-keymap select us",
        # Question propre à s390x, posée par le udeb « s390-netdevice » et
        # inexistante ailleurs : le matériel Z offre ctc, qeth, iucv ou
        # virtio, et d-i ne devine pas. Elle n'a AUCUNE valeur par défaut,
        # donc « priority=critical » ne la saute pas — l'installation se
        # figeait dessus, sur le premier choix de la liste (ctc), en
        # n'affichant rien d'autre qu'un écran bleu. Mesuré.
        "d-i s390-netdevice/choose_networktype select virtio",
        # « auto » évite la question du choix d'interface : sous virtio-ccw
        # elle s'appelle enc1 et non eth0, et le nom n'est pas devinable.
        f"d-i netcfg/get_hostname string {args.hostname}",
        # Adresse fixe : sans elle, netcfg-static pose la question a l'ecran
        # et l'installation s'arrete la, indefiniment.
        *(
            [
                "d-i netcfg/disable_autoconfig boolean true",
                "d-i netcfg/disable_dhcp boolean true",
                f"d-i netcfg/get_ipaddress string {static['ip']}",
                f"d-i netcfg/get_netmask string {static['netmask']}",
                f"d-i netcfg/get_gateway string {static['gateway']}",
                f"d-i netcfg/get_nameservers string {static['dns']}",
                "d-i netcfg/confirm_static boolean true",
            ]
            if static
            else []
        ),
        "d-i netcfg/get_domain string localdomain",
        "d-i netcfg/hostname string " + args.hostname,
        "d-i mirror/country string manual",
        "d-i mirror/http/hostname string deb.debian.org",
        "d-i mirror/http/directory string /debian",
        "d-i mirror/http/proxy string",
        "d-i passwd/root-login boolean false",
        "d-i passwd/user-fullname string ERPLibre",
        f"d-i passwd/username string {user}",
        f"d-i passwd/user-password-crypted password {crypted}",
        # network-console : sur IBM Z, d-i propose systématiquement de
        # poursuivre par SSH — la console y est historiquement limitée. Il
        # refuse un mot de passe vide et bloque l'installation non assistée.
        # Ce secret ne vit QUE le temps de l'installateur, sur le réseau
        # libvirt, et disparaît avec lui : il ne donne accès à rien ensuite.
        "d-i network-console/password password erplibre",
        "d-i network-console/password-again password erplibre",
        "d-i clock-setup/utc boolean true",
        f"d-i time/zone string {args.timezone}",
        "d-i clock-setup/ntp boolean true",
        # Le disque est nommé : sur s390x virtio-ccw il n'y en a qu'un, mais
        # d-i pose quand même la question quand rien ne le désigne.
        # Ce que partman voit reellement, ecrit sur la console : « No root
        # file system is defined » ne distingue pas « disque absent » de
        # « recette non appliquee », et les deux se corrigent differemment.
        # Toute commande preseedee DOIT rendre 0 : d-i bloque sur « Failed to
        # run preseeded command » sinon, et le diagnostic devient le blocage.
        # Vecu — un « ls /dev/dasd* » sans correspondance suffisait.
        "d-i partman/early_command string cat /proc/partitions > /dev/console"
        " ; ls /lib/partman/automatically_partition/ > /dev/console 2>&1"
        " ; true",
        # partman-auto RECLAME explicitement : il n'est pas tire d'office sur
        # s390x, ou la voie attendue est le partitionnement DASD manuel.
        # Mesure dans l'installateur : « /lib/partman/automatically_partition/
        # No such file or directory », et la liste des udebs recuperes montre
        # partman-base, -utils, -partitioning, -target… mais jamais -auto.
        # Sans lui, aucune recette ne s'applique et partman s'arrete sur
        # « No root file system is defined ».
        "d-i anna/choose_modules string partman-auto",
        "d-i partman-auto/disk string /dev/vda",
        "d-i partman-auto/method string regular",
        "d-i partman-auto/choose_recipe select atomic",
        "d-i partman/default_filesystem string ext4",
        "d-i partman-partitioning/confirm_write_new_label boolean true",
        "d-i partman/choose_partition select finish",
        "d-i partman/confirm boolean true",
        "d-i partman/confirm_nooverwrite boolean true",
        "tasksel tasksel/first multiselect ssh-server",
        "d-i pkgsel/include string openssh-server sudo python3"
        " qemu-guest-agent ca-certificates",
        "d-i pkgsel/upgrade select none",
        "popularity-contest popularity-contest/participate boolean false",
        "d-i finish-install/reboot_in_progress note",
    ]
    # late_command : tout ce que le preseed ne sait pas exprimer. « in-target »
    # exécute DANS le système installé ; les redirections, elles, restent dans
    # l'installateur et doivent donc viser /target.
    post = [
        f"in-target usermod -aG sudo {user}",
        f"echo '{user} ALL=(ALL) NOPASSWD:ALL' > /target/etc/sudoers.d/{user}",
        f"chmod 440 /target/etc/sudoers.d/{user}",
    ]
    # Accès au GPU, comme le cloud-config le donne aux autres distributions :
    # sans ces groupes, toute application GL de l'invité retombe sur le rendu
    # logiciel. « groupadd -f » ne fait rien si le groupe existe et ne rend
    # jamais d'erreur, là où « usermod -aG » sur un nom inconnu échoue.
    if (getattr(args, "gpu", "auto") or "auto").lower() != "off":
        post += [f"in-target groupadd -f {nom}" for nom in GPU_GROUPS]
        post.append(f"in-target usermod -aG {','.join(GPU_GROUPS)} {user}")
    if ssh_keys:
        post.append(f"mkdir -p /target/home/{user}/.ssh")
        for key in ssh_keys:
            post.append(
                f"echo '{key}' >> /target/home/{user}/.ssh/authorized_keys"
            )
        post += [
            f"in-target chown -R {user}:{user} /home/{user}/.ssh",
            f"chmod 700 /target/home/{user}/.ssh",
            f"chmod 600 /target/home/{user}/.ssh/authorized_keys",
        ]
    # Guide de connexion et identité git : les mêmes fichiers que sur les autres
    # distributions, mais ici il n'y a pas de cloud-init pour les écrire. Ils
    # voyagent DANS l'initrd, à côté du preseed, et le late_command ne fait que
    # les copier.
    #
    # Pourquoi pas leur contenu dans le preseed : la valeur d'une question tient
    # sur UNE ligne, et celle-ci fait déjà 1165 caractères avec une clé RSA-4096.
    # Y ajouter 1,2 Kio de guide — encodé ou en trente echo, la longueur est la
    # même — doublerait une ligne dont aucune limite n'est documentée pour
    # cdebconf. Et une troncature ne coûterait pas le guide : elle couperait le
    # late_command au milieu, donc ni sudoers ni clé SSH, donc une VM
    # inaccessible.
    for path, mode, _content, owner in guide_files(args):
        src = "/" + installer_guide_name(path)
        post.append(f"cp {src} /target{path} || true")
        post.append(f"chmod {mode} /target{path} || true")
        if owner:
            post.append(f"in-target chown {owner}:{owner} {path} || true")
    # Le code de sortie du late_command est celui de sa DERNIÈRE commande, et
    # d-i s'arrête sur « Failed to run preseeded command » dès qu'il n'est pas
    # nul. Sans ce « true », un chmod qui échoue bloque l'installation sur un
    # écran que personne ne regarde — c'est déjà la garde de
    # partman/early_command, quelques lignes plus haut.
    post.append("true")
    # Diagnostic réseau, écrit sur la console AVANT que netcfg ne décide.
    # netcfg n'essaie aucun DHCP sur s390x et tombe droit sur l'adressage
    # statique ; ses propres traces vont dans le syslog INTERNE de d-i, qu'on
    # ne peut lire qu'en ouvrant un shell à la main. Ces quelques lignes
    # atterrissent, elles, dans le journal de console — donc dans un fichier
    # qu'il suffit de lire après coup. La sonde DHCP est celle de busybox,
    # bornée à trois essais, et ne configure rien de durable.
    early = [
        # LE correctif, pas un diagnostic : on ALLUME la carte.
        #
        # Mesuré dans l'installateur : « enc1: <BROADCAST,MULTICAST> …
        # qdisc noop » — ni UP ni LOWER_UP — alors qu'un udhcpc manuel
        # obtenait un bail en deux secondes. Le réseau n'a jamais été en
        # cause ; netcfg teste l'état du lien AVANT d'essayer, ne le voit
        # pas, saute le DHCP et demande une adresse statique.
        #
        # Sur s390x c'est le udeb s390-netdevice qui active le périphérique.
        # En preseedant sa question pour qu'il ne s'affiche plus, on
        # court-circuite aussi cette activation. On la refait donc ici, avant
        # que netcfg ne décide.
        "ip link set enc1 up > /dev/console 2>&1",
        "echo '=== EL: enc1 activee avant netcfg ===' > /dev/console",
        "ip -o link show enc1 > /dev/console 2>&1",
        # Même garde que partman/early_command : « ip -o link show » rend 1
        # quand l'interface n'existe pas, et le code de sortie du early_command
        # est celui de sa dernière commande. Une ligne de DIAGNOSTIC bloquait
        # donc l'installation qu'elle devait servir à comprendre.
        "true",
    ]
    lines.append("d-i preseed/early_command string " + " ; ".join(early))
    lines.append("d-i preseed/late_command string " + " ; ".join(post))
    return "\n".join(lines) + "\n"


def build_installer_initrd(
    preseed: str,
    initrd_src: Path,
    out: Path,
    runner: Runner,
    guide: list[tuple[str, str, str, str]] | None = None,
) -> None:
    """Glisse le preseed DANS l'initrd de l'installateur.

    Servir le preseed en HTTP est l'autre voie documentée, mais elle ajoute un
    serveur à faire vivre pendant toute l'installation et une dépendance à
    l'ordre d'obtention de l'adresse. Embarquer le fichier ne dépend de rien :
    d-i lit « /preseed.cfg » à la racine de l'initrd avant même le réseau.

    La méthode est celle de la documentation Debian — décompresser, ajouter le
    fichier au cpio, recompresser — et non une concaténation d'archives, que
    le noyau accepte mais que d-i ne parcourt pas de la même façon.

    `guide` : les fichiers d'accueil de la VM (guide de connexion, identité
    git), rangés à côté du preseed. L'initrd EST le système de fichiers de
    l'installateur : le late_command n'a plus qu'à les copier vers /target,
    sans avoir à transporter leur contenu dans une valeur de preseed.
    """
    if runner.dry_run:
        print(f"[dry-run] preseed -> {out}")
        for path, _mode, _content, _owner in guide or []:
            print(f"[dry-run]   + {installer_guide_name(path)} -> {path}")
        return
    if not shutil.which("cpio"):
        sys.exit(
            "cpio est requis pour embarquer le preseed dans l'initrd.\n"
            "  Debian/Ubuntu : sudo apt-get install cpio"
        )
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        # Le mot de passe utilisateur y est HACHÉ (user-password-crypted).
        # Reste celui de network-console, une valeur fixe et publique dont
        # le composant est désactivé plus bas. Le répertoire temporaire est
        # déjà en 0700 ; le mode explicite vaut pour qui lirait ce code.
        cfg = work / "preseed.cfg"
        cfg.touch(mode=0o600)
        cfg.write_text(preseed, encoding="utf-8")
        members = ["preseed.cfg"]
        for path, _mode, content, _owner in guide or []:
            name = installer_guide_name(path)
            (work / name).write_text(content, encoding="utf-8")
            members.append(name)
        # network-console DÉSACTIVÉ, par le levier que d-i prévoit pour cela.
        #
        # Sur IBM Z, d-i propose de poursuivre par SSH — la console y est
        # historiquement limitée. Ce n'est pas une question à laquelle
        # répondre : le composant démarre sshd puis ATTEND une connexion de
        # l'utilisateur « installer », indéfiniment. Preseeder son mot de
        # passe le fait avancer d'un écran, pas davantage — mesuré.
        #
        # Un composant dont « .isinstallable » sort en erreur est retiré du
        # menu. L'original le fait déjà quand sshd tourne ; on le remplace par
        # un refus inconditionnel. Le fichier ajouté APRÈS l'original prend sa
        # place : le noyau déplie le cpio séquentiellement et le dernier
        # écrit gagne.
        gate = work / "var/lib/dpkg/info"
        gate.mkdir(parents=True, exist_ok=True)
        target = gate / "network-console.isinstallable"
        target.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        target.chmod(0o755)
        plain = work / "initrd"
        with gzip.open(initrd_src, "rb") as src, open(plain, "wb") as dst:
            shutil.copyfileobj(src, dst)
        members.append("var/lib/dpkg/info/network-console.isinstallable")
        subprocess.run(
            ["cpio", "-H", "newc", "-o", "-A", "-F", str(plain)],
            input="\n".join(members) + "\n",
            text=True,
            cwd=work,
            check=True,
            capture_output=True,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(plain, "rb") as src, gzip.open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    print(f"  preseed embarqué dans {out} ({out.stat().st_size} octets)")


def create_blank_disk(
    disk: Path, size: str, runner: Runner, force: bool
) -> None:
    """Disque VIERGE : l'installateur écrit tout, il n'y a rien à convertir."""
    if disk.exists() and not force:
        sys.exit(
            f"Le disque {disk} existe déjà. Utilisez --force pour l'écraser."
        )
    runner.run(
        ["qemu-img", "create", "-f", "qcow2", str(disk), size],
        privileged=True,
    )


def network_name(network_arg: str) -> str | None:
    """Extrait NAME de « network=NAME,... » ; None si c'est un bridge, etc."""
    for part in network_arg.split(","):
        if part.strip().startswith("network="):
            return part.split("=", 1)[1].strip()
    return None


def c_locale_env() -> dict[str, str]:
    """L'environnement des commandes dont on PARSE la sortie.

    virsh TRADUIT ses étiquettes : sous une locale française, « net-info »
    répond « Actif : non » et « Démarrage automatique : oui », où un motif
    « Active: yes » lit toujours faux. Un réseau démarré passait alors pour
    éteint, l'hôte était déclaré « pas prêt » quel que soit son état, et le
    message invitait à redémarrer pour rien. Le même geste, pour la même
    raison, est dans script/todo/qemu_manage.py.
    """
    return {**os.environ, "LC_ALL": "C", "LANG": "C"}


def virsh_out(args: list[str], use_sudo: bool, timeout: int = 20) -> str:
    """La sortie d'un virsh, en anglais, ou '' s'il n'a rien pu dire."""
    cmd = (["sudo"] if use_sudo else []) + ["virsh", "-c", LIBVIRT_URI, *args]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=c_locale_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout if res.returncode == 0 else ""


def network_state(name: str, use_sudo: bool) -> tuple[bool, bool]:
    """(actif, autostart) d'un réseau libvirt, via « virsh net-info »."""
    out = virsh_out(["net-info", name], use_sudo, timeout=15)
    active = bool(re.search(r"Active:\s*yes", out, re.IGNORECASE))
    autostart = bool(re.search(r"Autostart:\s*yes", out, re.IGNORECASE))
    return (active, autostart)


# Le troisième octet où commence la recherche d'un /24 libre. 122 est celui du
# « default » de libvirt, 123 celui de beaucoup d'installations toutes faites :
# partir au-dessus des deux coûte un octet. long_test/deep_qemu.py part du même
# nombre, en le déduisant de la profondeur là où il ne peut pas sonder.
LIBVIRT_NET_BASE = 131


def interface_de_ligne(ligne: str) -> str:
    """L'interface que porte une ligne de « ip route » ou « ip -o addr ».

    Deux grammaires pour une seule question. Une route nomme son interface
    après « dev » ; « ip -o -4 addr » la donne en deuxième champ, la ligne
    commençant par son index (« 3: virbr0    inet … »). Le « -o » est ce qui
    rend la seconde lisible : sans lui, l'interface est sur une ligne et ses
    adresses sur les suivantes, plus rattachables l'une à l'autre.
    """
    mots = ligne.split()
    if "dev" in mots:
        i = mots.index("dev")
        if i + 1 < len(mots):
            return mots[i + 1]
    if len(mots) >= 2 and mots[0].rstrip(":").isdigit():
        # « eth0@if12 » sur une interface appairée : le nom est avant l'arobase.
        return mots[1].rstrip(":").split("@")[0]
    return ""


def host_networks(exclure_ponts=()) -> list[ipaddress.IPv4Network]:
    """Les réseaux IPv4 que l'hôte porte ou route déjà.

    Les deux, adresses ET routes : une interface peut router un réseau sans y
    porter d'adresse, et c'est la ROUTE qui décide où part un paquet.

    `exclure_ponts` écarte les interfaces dont le réseau EST celui qu'on
    examine. Un réseau libvirt actif porte son propre /24 sur son pont, et le
    route : compté comme « déjà pris par l'hôte », il se trouve en collision
    avec lui-même. Le verdict était alors le même sur toute machine où le
    réseau tournait, quel que soit son sous-réseau — d'où un déplacement là où
    rien n'entrait en conflit, sous des VM qui perdaient leur passerelle. La
    question posée est « quelqu'un D'AUTRE occupe-t-il ce /24 », et le pont du
    réseau examiné n'est pas quelqu'un d'autre.
    """
    # Un nom vide n'exclut RIEN : network_bridge rend '' quand le XML est
    # illisible, et le garder dans l'ensemble écarterait toute ligne dont
    # l'interface ne se lit pas — soit, sur une grammaire inattendue, la
    # totalité de ce que l'hôte occupe.
    exclure = {pont for pont in (exclure_ponts or ()) if pont}
    vus: list[ipaddress.IPv4Network] = []
    commandes = (
        ["ip", "-4", "route", "show"],
        # « -o » : une adresse par ligne, sinon l'interface est sur la ligne
        # d'en-tête et l'adresse sur la suivante, donc plus rattachables.
        ["ip", "-o", "-4", "addr", "show"],
    )
    for args in commandes:
        try:
            out = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                env=c_locale_env(),
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for ligne in out.splitlines():
            if interface_de_ligne(ligne) in exclure:
                continue
            for cidr in re.findall(r"\b(\d+\.\d+\.\d+\.\d+/\d+)\b", ligne):
                try:
                    vus.append(ipaddress.ip_network(cidr, strict=False))
                except ValueError:
                    continue
    return vus


def network_cidr(name: str, use_sudo: bool) -> str:
    """Le réseau servi par un réseau libvirt (« 192.168.122.0/24 »), ou ''."""
    return cidr_from_network_xml(virsh_out(["net-dumpxml", name], use_sudo))


def bridge_from_network_xml(xml: str) -> str:
    """Le pont déclaré par un XML de réseau libvirt (« virbr0 »), ou ''."""
    m = re.search(r"<bridge[^>]*name='([^']+)'", xml)
    return m.group(1) if m else ""


def network_bridge(name: str, use_sudo: bool) -> str:
    """Le pont que ce réseau libvirt monte, ou ''.

    C'est l'interface qui portera son adresse .1 une fois le réseau démarré :
    la seule que la recherche de collision doit s'interdire de compter.
    """
    return bridge_from_network_xml(virsh_out(["net-dumpxml", name], use_sudo))


def cidr_from_network_xml(xml: str) -> str:
    """Le réseau déclaré par un XML de réseau libvirt, ou ''.

    Le masque est écrit en quatre octets (« 255.255.255.0 ») et non en
    longueur de préfixe : ipaddress accepte les deux formes, le reste du code
    n'en manipule qu'une.
    """
    m = re.search(r"<ip address='([\d.]+)' netmask='([\d.]+)'", xml)
    if not m:
        return ""
    try:
        return str(
            ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False)
        )
    except ValueError:
        return ""


def network_collision(cidr: str, hote: list) -> str:
    """Ce que l'hôte route déjà dans ce réseau, ou '' s'il est libre.

    Le « default » de libvirt sert 192.168.122.0/24. Une machine qui VIT dans
    ce réseau — toute VM déployée par ce dépôt en sert une — ne peut pas le
    servir à son tour : l'adresse .1 du pont est celle de sa propre
    passerelle. virsh refuse d'ailleurs le démarrage (« Network is already in
    use by interface eth0 »), mais seulement quand la route est LÀ : au
    démarrage de la machine, libvirtd monte ses réseaux avant que le bail DHCP
    ne soit arrivé, plus rien ne signale la collision, et l'hôte perd sa
    passerelle au profit du pont.
    """
    if not cidr:
        return ""
    try:
        mien = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return ""
    for autre in hote:
        if mien.overlaps(autre):
            return str(autre)
    return ""


def libvirt_networks_cidrs(name: str, use_sudo: bool) -> list:
    """Les réseaux servis par les AUTRES réseaux libvirt de l'hôte.

    Un réseau inactif ne route rien : il n'apparaît donc pas dans host_networks
    et rien n'empêcherait de lui reprendre son sous-réseau, pour buter dessus
    au premier démarrage des deux.
    """
    out = []
    for autre in virsh_out(["net-list", "--all", "--name"], use_sudo).split():
        if autre == name:
            continue
        cidr = network_cidr(autre, use_sudo)
        if cidr:
            try:
                out.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                pass
    return out


def free_subnet(pris: list) -> str:
    """Un préfixe « 192.168.X » qu'aucun réseau connu ne recouvre, ou ''."""
    for troisieme in range(LIBVIRT_NET_BASE, 255):
        candidat = ipaddress.ip_network(f"192.168.{troisieme}.0/24")
        if not any(candidat.overlaps(autre) for autre in pris):
            return f"192.168.{troisieme}"
    return ""


def moved_network_xml(xml: str, ancien: str, nouveau: str) -> str:
    """Le XML du réseau, son sous-réseau déplacé, le reste INTACT.

    Réécrit plutôt que reconstruit : l'UUID, le nom du pont et son adresse
    MAC restent en place, si bien que le réseau garde son identité au lieu
    d'en prendre une nouvelle — et les domaines qui le nomment le retrouvent.
    """
    return xml.replace(f"{ancien}.", f"{nouveau}.")


@contextlib.contextmanager
def fichier_xml_temporaire(contenu: str, prefixe: str = "erplibre-net-"):
    """Un XML posé sur le disque le temps d'un « virsh net-define », puis ôté.

    Créé par mkstemp, donc à un nom que personne ne peut prédire, et retiré à
    la sortie même si virsh échoue. Un nom composé — d'un nom de réseau, par
    exemple — est un chemin PRÉVISIBLE dans un répertoire où tout le monde
    écrit : qui l'occupe d'avance par un lien symbolique choisit ce que root
    va définir, et le laisser derrière donne à lire la configuration du parc.

    Le fichier est lisible par tous : virsh le lit sous root, et le fichier
    d'un utilisateur non privilégié ne l'est pas toujours. Ce qu'il contient
    ne sort pas de la définition du réseau, que « net-dumpxml » rend à qui
    peut déjà joindre libvirt.
    """
    fd, chemin = tempfile.mkstemp(prefix=prefixe, suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        os.chmod(chemin, 0o644)
        yield chemin
    finally:
        try:
            os.unlink(chemin)
        except OSError:
            pass


def define_network_xml(xml: str, runner: Runner) -> None:
    """Redéfinit un réseau libvirt à partir de son XML."""
    with fichier_xml_temporaire(xml) as chemin:
        runner.run(
            ["virsh", "-c", LIBVIRT_URI, "net-define", chemin],
            privileged=True,
            check=False,
        )


def move_network(name: str, cidr: str, collision: str, runner: Runner) -> str:
    """Redéfinit le réseau sur un /24 libre. Rend le nouveau préfixe, ou ''.

    Une REDÉFINITION et non un démarrage : elle ne demande ni pont ni module
    du noyau, donc elle réussit même sur une machine dont le noyau a été
    remplacé depuis le démarrage. C'est ce qui permet d'armer l'autostart
    avant le redémarrage sans armer une collision.
    """
    xml = virsh_out(["net-dumpxml", name], runner.use_sudo)
    if not xml:
        print(f"  ⚠ réseau « {name} » illisible : rien n'est déplacé.")
        return ""
    ancien = cidr.rsplit(".", 1)[0].rsplit("/", 1)[0]
    libre = free_subnet(
        host_networks(exclure_ponts=[bridge_from_network_xml(xml)])
        + libvirt_networks_cidrs(name, runner.use_sudo)
    )
    if not libre:
        print("  ⚠ aucun /24 libre en 192.168.x : rien n'est déplacé.")
        return ""
    print(
        f"  Le réseau « {name} » sert {cidr}, que l'hôte route déjà"
        f" ({collision})."
    )
    print(
        f"  Déplacé sur {libre}.0/24 : sinon le pont prendrait l'adresse de"
        " la passerelle de cette machine, qui perdrait son accès au réseau"
        " au prochain démarrage."
    )
    define_network_xml(moved_network_xml(xml, ancien, libre), runner)
    return libre


def ensure_network(name: str | None, runner: Runner) -> None:
    """Rend le réseau libvirt utilisable, et SÛR pour le prochain démarrage.

    Trois gestes, et leur ordre est tout :

    0. ABATTRE un réseau actif qui recouvre une route de l'hôte : c'est la
       machine déjà cassée, et son pont porte l'adresse de la passerelle.
    1. DÉPLACER le réseau s'il recouvre ce que l'hôte route déjà. Le
       « default » de libvirt sert 192.168.122.0/24, et toute VM déployée par
       ce dépôt vit dans ce réseau : son pont y prendrait l'adresse .1, celle
       de sa propre passerelle. La redéfinition ne demande ni pont ni module
       du noyau, donc elle passe même quand le démarrage, lui, ne passe pas.
    2. DÉMARRER, puis relire l'état plutôt que de croire le code de retour.
    3. ARMER l'autostart SEULEMENT si le sous-réseau est libre de collision.
       C'est le geste qui cassait la machine : armé sur un réseau en
       collision, libvirtd le monte au démarrage AVANT que le bail DHCP de
       l'hôte ne soit là — plus aucune route ne signale la collision, virbr0
       prend l'adresse de la passerelle, et l'hôte n'a plus de réseau. Un
       réseau qui n'a pas pu démarrer faute de modules du noyau reste, lui,
       armé : c'est ce qui rend l'hôte utilisable en UN seul redémarrage.
    """
    if not name:
        return
    if runner.dry_run:
        print(f"  [dry-run] réseau libvirt '{name}' vérifié et activé")
        print("  [dry-run] sous-réseau déplacé s'il entre en collision")
        runner.run(
            ["virsh", "-c", LIBVIRT_URI, "net-start", name],
            privileged=True,
            check=False,
        )
        runner.run(
            ["virsh", "-c", LIBVIRT_URI, "net-autostart", name],
            privileged=True,
            check=False,
        )
        return
    active, autostart = network_state(name, runner.use_sudo)
    cidr = network_cidr(name, runner.use_sudo)
    # Son propre pont ne compte pas : un réseau démarré porte et route son /24
    # là, et se verrait sinon en collision avec lui-même sur toute machine.
    pont = network_bridge(name, runner.use_sudo)
    collision = network_collision(cidr, host_networks(exclure_ponts=[pont]))

    if collision:
        # Un réseau ACTIF en collision est la machine DÉJÀ privée de réseau :
        # libvirt refuse ce démarrage quand la route est là, donc le pont a
        # pris l'adresse de la passerelle AVANT elle, au démarrage. L'abattre
        # est ce qui rend l'accès au réseau à l'hôte, et tout de suite.
        if active:
            print(
                f"  ⚠ le réseau « {name} » est actif SUR {collision}, que"
                " cette machine route : son pont porte l'adresse de la"
                " passerelle. Arrêté pour rendre l'accès au réseau."
            )
            runner.run(
                ["virsh", "-c", LIBVIRT_URI, "net-destroy", name],
                privileged=True,
                check=False,
            )
            active = False
        libre = move_network(name, cidr, collision, runner)
        if libre:
            cidr = network_cidr(name, runner.use_sudo)
            collision = network_collision(
                cidr, host_networks(exclure_ponts=[pont])
            )

    if active and autostart and not collision:
        print(f"  Réseau libvirt '{name}' déjà actif.")
        return

    if not active:
        print(f"  Configuration du réseau libvirt '{name}'…")
        runner.run(
            ["virsh", "-c", LIBVIRT_URI, "net-start", name],
            privileged=True,
            check=False,
        )
        active, autostart = network_state(name, runner.use_sudo)

    if collision:
        # Rien n'a pu le rendre sûr : le désarmer est la seule chose qui
        # protège le prochain démarrage.
        if autostart:
            print(
                f"  ⚠ autostart RETIRÉ au réseau « {name} » : il recouvre"
                f" {collision}, et le monter au démarrage priverait cette"
                " machine de sa passerelle."
            )
            runner.run(
                [
                    "virsh",
                    "-c",
                    LIBVIRT_URI,
                    "net-autostart",
                    "--disable",
                    name,
                ],
                privileged=True,
                check=False,
            )
        return

    if not autostart:
        runner.run(
            ["virsh", "-c", LIBVIRT_URI, "net-autostart", name],
            privileged=True,
            check=False,
        )


def virt_install(
    args: argparse.Namespace,
    disk: Path,
    seed: Path,
    osinfo: str,
    runner: Runner,
    installer: tuple[Path, Path] | None = None,
) -> None:
    # Émulée (TCG, pas de KVM) si l'arch demandée diffère de celle de l'hôte.
    # Deux causes d'émulation, à ne pas confondre : une architecture étrangère
    # (voulue, on la choisit), et une absence de KVM (subie, et invisible). La
    # seconde ne se déduit PAS de l'architecture — dans une VM sans
    # virtualisation imbriquée, libvirt retombe en TCG sans rien dire.
    emulated = args.arch != host_arch()
    if not emulated and not kvm_available():
        emulated = True
        print(
            "⚠  KVM indisponible (/dev/kvm) : cette VM sera ÉMULÉE, donc TRÈS"
            " lente."
        )
        print(
            "   Cause habituelle : l'hôte est lui-même une VM sans"
            " virtualisation imbriquée."
        )
        print(
            "   Vérifier :  systemd-detect-virt  et"
            '  virsh capabilities | grep "domain type"'
        )
    # s390x n'a pas de port série ISA : la console est SCLP (ttysclp0), et non
    # ttyS0. Ailleurs (x86/arm64), console série classique.
    console_target = "sclp" if args.arch == "s390x" else "serial"
    console_log = f"/var/log/libvirt/qemu/{args.name}-console.log"
    # Écran virtuel pour une VM graphique. s390x en est écarté : QEMU y expose
    # bien « virtio-gpu-ccw », mais rien ne garantit que le noyau s390x de la
    # distribution embarque le pilote DRM virtio-gpu — la VM démarrerait alors
    # sur un écran noir. Le bureau distant, lui, marche partout : c'est la voie
    # retenue pour cette architecture, et le message le dit.
    graphics = args.graphics
    video = []
    if args.desktop and graphics == "none":
        if args.arch == "s390x":
            print(
                "\n  s390x : pas d'écran virtuel (pilote DRM non garanti)."
                "\n  Le bureau sera accessible à distance, par le réseau."
            )
        else:
            # VNC sur la boucle locale, PAS « spice,listen=none ».
            #
            # « listen=none » est le défaut de virt-install et il n'expose
            # rien : QEMU crée l'affichage mais n'ouvre AUCUN socket TCP, seul
            # le canal libvirt y mène. Un virt-manager tournant sur la machine
            # même y accède ; rien d'autre. Or l'hôte QEMU est lui-même une VM
            # ici — la console était donc inatteignable par construction, et
            # aucun « ssh -L » ne pouvait y remédier : il n'y avait pas de port
            # où aboutir.
            #
            # 127.0.0.1 n'expose rien au réseau non plus : le port n'est
            # joignable que depuis l'hôte, donc à travers un tunnel SSH. VNC
            # plutôt que SPICE parce qu'il tient en UN port — un seul « -L »
            # suffit, avec n'importe quel client. Pour revenir au comportement
            # d'avant : --graphics spice,listen=none
            graphics = "vnc,listen=127.0.0.1"
            video = ["--video", "virtio"]
    # 3D : allumée d'office quand l'hôte a un GPU (--gpu auto). Une VM
    # graphique sans accélération rend tout par le processeur — le bureau
    # comme l'émulateur Android qui tourne dedans — et c'est le défaut le plus
    # coûteux qu'on puisse laisser en place sans le dire.
    gpu_node = args.gpu_node or host_gpu_node()
    video_sans_3d = list(video)
    video, gpu_args, gpu_msg = gpu_apply(
        video, args.gpu, gpu_node, graphics != "none"
    )
    if gpu_msg:
        print(gpu_msg)
    cmd = [
        "virt-install",
        # Sans --connect, un utilisateur non root vise qemu:///session : le
        # réseau « default » n'y existe pas et la création échoue même quand
        # tous les paquets sont installés et le réseau actif côté système.
        "--connect",
        LIBVIRT_URI,
        "--name",
        args.name,
        "--memory",
        str(args.memory),
        "--vcpus",
        str(args.vcpus),
    ]
    if installer:
        kernel, initrd = installer
        # « --install » et non « --boot » : virt-install écrit alors DEUX
        # configurations — celle de l'installation, transitoire, et celle du
        # système installé. Avec « --boot kernel=… » la VM repartirait sur
        # l'installateur à chaque démarrage, indéfiniment.
        #
        # console=ttysclp0 : s390x n'a pas de port série ISA. Sans cet
        # argument l'installateur tourne sur une console invisible, et un
        # échec ne laisse aucune trace lisible.
        cmd += [
            "--install",
            f"kernel={kernel},initrd={initrd},"
            # PAS de « auto=true » : il vise le preseed par URL et réordonne
            # l'installation pour monter le réseau AVANT tout le reste. Le
            # nôtre est local, il n'y a rien à aller chercher — et c'est
            # précisément là que netcfg dérapait.
            "kernel_args=priority=critical "
            "preseed/file=/preseed.cfg console=ttysclp0",
        ]
    else:
        cmd.append("--import")
    cmd += [
        "--disk",
        f"path={disk},format=qcow2,bus=virtio",
    ]
    # Le seed n'existe QUE sur la voie image cloud. Sous debian-installer, le
    # preseed voyage dans l'initrd et un second disque ne ferait qu'ajouter un
    # /dev/vdb dont partman-auto devrait être protégé.
    if not installer:
        # Seed cloud-init attaché comme DISQUE virtio en lecture seule (et non
        # en CD-ROM) : le pilote virtio-blk est dans l'initramfs, donc le
        # volume « cidata » est visible dès init-local et cloud-init le lit.
        # En CD-ROM, l'initramfs Debian ne charge pas sr_mod à temps -> le
        # seed n'est pas vu et rien ne s'applique (Ubuntu, lui, tolère le CD).
        # Sur s390x, bus=virtio est mappé en virtio-ccw par libvirt.
        cmd += ["--disk", f"path={seed},readonly=on,bus=virtio"]
    cmd += [
        "--osinfo",
        osinfo,
        "--network",
        args.network,
        "--console",
        # Journal de console pour la voie installateur. Une console « pty »
        # seule ne gardE rien : quand d-i échoue, il l'écrit à l'écran d'une
        # VM que personne ne regarde, et il ne reste RIEN à lire ensuite —
        # exactement « l'installation a échoué, pas de sortie pertinente ».
        # Le fichier, lui, survit à l'arrêt du domaine.
        (
            f"pty,target_type={console_target},log.file={console_log}"
            if installer
            else f"pty,target_type={console_target}"
        ),
        # Canal virtio de l'agent invité (org.qemu.guest_agent.0) : permet à
        # virsh de piloter la VM SANS réseau (ex. étendre le FS invité après
        # un redimensionnement de disque). Inoffensif si l'agent est absent.
        "--channel",
        "unix,target.type=virtio,target.name=org.qemu.guest_agent.0",
    ]
    # « --graphics none » dit « aucun affichage » : le poser à côté d'un
    # « egl-headless », qui EST un affichage, se contredit. Sur une VM sans
    # console dont la 3D est demandée, egl-headless reste donc le seul.
    graphics_omis = bool(gpu_args) and graphics == "none"
    if not graphics_omis:
        cmd += ["--graphics", graphics]
    i_gpu = len(cmd)
    cmd += video + gpu_args
    if args.arch == "s390x":
        # s390x (IBM Z) : machine s390-ccw-virtio, amorçage IPL/zipl depuis le
        # disque (ni BIOS ni UEFI/OVMF -> aucun --boot).
        cmd += ["--arch", "s390x", "--machine", "s390-ccw-virtio"]
    elif args.arch == "arm64":
        # arm64/aarch64 : machine « virt » + UEFI (firmware AAVMF). Les images
        # cloud arm64 n'ont pas de BIOS -> UEFI obligatoire. Secure Boot
        # DÉSACTIVÉ (comme x86) : sinon libvirt sélectionne l'AAVMF « secure »
        # à clés Microsoft enrôlées et la VM RESTE FIGÉE au firmware (aucun
        # boot, aucune IP). secure-boot=no -> AAVMF non-SB, boot OK.
        cmd += [
            "--arch",
            "aarch64",
            "--machine",
            "virt",
            "--boot",
            "uefi,firmware.feature0.name=secure-boot,"
            "firmware.feature0.enabled=no",
        ]
    elif not args.bios:
        # Boot UEFI par défaut (x86) : Debian 13 (trixie) et les images cloud
        # récentes n'embarquent plus le chargeur BIOS/GRUB-pc et partent en
        # boucle « Booting... » en SeaBIOS. UEFI (OVMF) fonctionne pour
        # Ubuntu/Debian/Fedora. --bios force l'ancien BIOS si OVMF est absent.
        # Secure Boot DÉSACTIVÉ : le chargeur d'Arch (GRUB) n'est pas signé et
        # OVMF Secure Boot le refuse (« Access Denied » -> pas de boot).
        # Ubuntu/Debian/Fedora bootent aussi sans Secure Boot.
        cmd += [
            "--boot",
            "uefi,firmware.feature0.name=secure-boot,"
            "firmware.feature0.enabled=no",
        ]
    if emulated:
        # Architecture différente de l'hôte -> émulation logicielle TCG
        # (pas de KVM). LENT.
        cmd += ["--virt-type", "qemu"]
    if not args.attach_console:
        cmd.append("--noautoconsole")
        if installer:
            # Sans « --wait 0 », virt-install RESTE au premier plan jusqu'à la
            # fin de l'installation. Sous émulation s390x elle se compte en
            # heures, et le déploiement parallèle attendrait chaque VM l'une
            # après l'autre. La configuration finale est déjà écrite : rendre
            # la main n'abandonne rien.
            cmd += ["--wait", "0"]
    # virtinst écrit un journal de debug dans ~/.cache/virt-manager ; sous
    # sudo, HOME/cache peut être inaccessible -> l'écriture échoue et Python
    # déverse un « Logging error » (le pavé « Fetched capabilities … »). On
    # force un cache/HOME ÉCRIVABLE via « env VAR=… » (traverse sudo) pour
    # que le journal s'écrive silencieusement.
    # Chemin propre à l'UID : un répertoire partagé finit créé par root lors
    # d'un premier passage sous sudo, puis devient illisible pour l'utilisateur
    # (« Error setting up logfile: No write access to … /virt-manager »).
    cache_dir = f"/var/tmp/erplibre-virtinst-{os.getuid()}"
    try:
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    except OSError:
        pass
    log_env = [
        "env",
        f"XDG_CACHE_HOME={cache_dir}",
        f"HOME={cache_dir}",
    ]
    if not gpu_args:
        runner.run(log_env + cmd, privileged=True)
        return
    # La 3D est le SEUL argument dont l'échec se rattrape : le nœud de rendu
    # existe, mais QEMU n'arrive pas à y démarrer EGL. Rien ne permet de le
    # savoir avant d'essayer, donc on essaie, et on retire la 3D si c'est
    # elle qui a fait tomber le domaine.
    code, sortie = runner.run(log_env + cmd, privileged=True, capture=True)
    if code == 0:
        return
    if not egl_failed(sortie):
        sys.exit(
            f"\nÉchec de la commande (code {code}) :\n"
            f"  {' '.join(log_env + cmd)}"
        )
    # Le repli vaut AUSSI pour « --gpu on ». Une VM qu'on n'a pas est pire
    # qu'une VM sans 3D, et le repli n'est pas silencieux : il le dit, en
    # nommant ce qui a été demandé et ce qui a été obtenu.
    demande = (args.gpu or "auto").lower() == "on"
    print(
        f"\n  ⚠ EGL ne démarre pas sur {gpu_node} :"
        f" {'la 3D DEMANDÉE est retirée' if demande else 'la 3D est retirée'}"
        "\n    et la VM recréée en rendu logiciel."
        " « --gpu off » évite cet essai."
    )
    # Rendre l'affichage écarté plus haut : sans lui, la VM repartirait sans
    # « --graphics none », donc avec le défaut de virt-install, qui n'est pas
    # ce qu'on avait demandé.
    rendu = [] if not graphics_omis else ["--graphics", graphics]
    cmd_sans_3d = (
        cmd[:i_gpu]
        + rendu
        + video_sans_3d
        + cmd[i_gpu + len(video) + len(gpu_args) :]
    )
    # Le domaine défini par l'essai raté doit partir : sans quoi virt-install
    # refuse le nom, et la VM resterait celle qui ne démarre pas.
    runner.run(
        ["virsh", "--connect", LIBVIRT_URI, "undefine", args.name, "--nvram"],
        privileged=True,
        check=False,
    )
    runner.run(log_env + cmd_sans_3d, privileged=True)


def watch_and_restart(name: str, runner: Runner) -> None:
    """Rallume la VM quand debian-installer a fini et l'a éteinte.

    virt-install mène l'installation en DEUX temps : un amorçage transitoire
    sur kernel+initrd, puis la configuration définitive, qui démarre sur le
    disque. Le passage de l'un à l'autre se fait par un arrêt — l'installateur
    redémarre, libvirt détruit le domaine transitoire — et c'est virt-install
    qui rallume ensuite. Avec « --wait 0 » il est déjà parti : le domaine
    reste « shut off », disque installé et XML correct, mais éteint.

    On ne peut pas pour autant laisser virt-install attendre : sous émulation
    l'installation dure des heures, et le déploiement rendrait la main à ce
    rythme-là. Un veilleur détaché fait donc le dernier geste.
    """
    if runner.dry_run:
        print(f"[dry-run] veilleur de redémarrage pour {name}")
        return
    sudo = "sudo " if runner.use_sudo else ""
    # 6 h de garde : bien au-delà d'une installation émulée, et le veilleur
    # meurt de lui-même si quelque chose a mal tourné.
    script = (
        f"for i in $(seq 1 720); do "
        f"  s=$({sudo}virsh -c {LIBVIRT_URI} domstate {name} 2>/dev/null); "
        f'  if [ "$s" = "shut off" ]; then '
        f"    {sudo}virsh -c {LIBVIRT_URI} start {name} >/dev/null 2>&1; "
        f"    exit 0; "
        f"  fi; "
        f"  sleep 30; "
        f"done"
    )
    try:
        subprocess.Popen(
            ["/bin/sh", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  ⚠ veilleur non lancé ({exc}) ; démarrer à la main :")
        print(f"      sudo virsh start {name}")
        return
    print(
        f"  Veilleur lancé : {name} sera rallumée dès que l'installateur"
        " l'aura éteinte."
    )


def _ip_reachable(ip: str, port: int = 22, timeout: float = 3) -> bool:
    """Vrai si le port SSH répond (distingue le bail actif du bail périmé)."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_ip(name: str, use_sudo: bool, timeout: int) -> str | None:
    """Interroge les baux DHCP libvirt jusqu'à obtenir l'IPv4 de la VM. Une VM
    peut avoir PLUSIEURS baux (l'image demande d'abord une IP avec le hostname
    par défaut « ubuntu », puis cloud-init fixe le vrai hostname -> 2e bail) :
    on renvoie une IP JOIGNABLE (sshd up), sinon la plus récente, jamais
    aveuglément la 1re (souvent le bail précoce périmé, « No route to host »).
    """
    base = (["sudo"] if use_sudo else []) + [
        "virsh",
        "domifaddr",
        name,
        "--source",
        "lease",
    ]
    deadline = time.time() + timeout
    ips: list[str] = []
    while time.time() < deadline:
        res = subprocess.run(base, capture_output=True, text=True)
        ips = re.findall(r"(\d+\.\d+\.\d+\.\d+)", res.stdout)
        for ip in ips:
            if _ip_reachable(ip):
                return ip
        time.sleep(3)
    return ips[-1] if ips else None


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
        help="Architecture de l'image (défaut : amd64). amd64/x86_64, "
        "arm64/aarch64 (Ubuntu/Debian/Fedora) ou s390x (Ubuntu). Toute arch "
        "différente de l'hôte est ÉMULÉE (TCG, lente).",
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
        default=DEFAULT_DISK_DIR,
        help=f"Répertoire du qcow2 de travail (défaut : {DEFAULT_DISK_DIR}).",
    )
    g_vm.add_argument(
        "--seed-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help=f"Répertoire du seed.iso (défaut : {DEFAULT_IMAGE_DIR}).",
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
        "--desktop",
        action="store_true",
        help="VM graphique : écran virtuel SPICE là où l'architecture le "
        "permet. Les paquets GNOME sont posés par la commande d'installation, "
        "pas ici.",
    )
    g_vm.add_argument(
        "--gpu",
        choices=("auto", "on", "off"),
        default="auto",
        help="Accélération 3D par le GPU de l'hôte : auto (défaut, activée "
        "si un /dev/dri/renderD* existe), on (forcer), off (rendu logiciel).",
    )
    g_vm.add_argument(
        "--gpu-node",
        default="",
        help="Nœud de rendu à utiliser (défaut : le premier trouvé). Utile "
        "sur un hôte à plusieurs cartes.",
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
        "--apt-mirror",
        metavar="URI",
        help=(
            "Miroir apt unique (Ubuntu). Par défaut, cloud-init essaie dans"
            " l'ordre les miroirs les plus rapides mesurés puis le dépôt"
            " officiel."
        ),
    )
    g_cloud.add_argument(
        "--timezone",
        default=host_timezone(),
        metavar="ZONE",
        help=(
            "Fuseau horaire de la VM, au format zoneinfo "
            f"(défaut : celui de l'hôte, {host_timezone()})."
        ),
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
        "--lang",
        choices=("fr", "en"),
        default="fr",
        help="Langue du guide affiché à la connexion SSH (défaut : fr). "
        "todo.py passe la langue de son menu.",
    )
    g_cloud.add_argument(
        "--erplibre-dir",
        default="",
        metavar="CHEMIN",
        help="Racine d'ERPLibre dans la VM (~/git/erplibre en dev, "
        "/opt/erplibre en prod). Ajoute la section ERPLibre au guide de "
        "connexion. Vide, elle est omise : une VM déployée sans installation "
        "n'annonce pas un dépôt et un service qui n'existent pas.",
    )
    g_cloud.add_argument(
        "--erplibre-make",
        default="",
        metavar="CIBLE",
        help="Cible make qui a installé la VM (ex. install_odoo_18), reprise "
        "dans le guide pour la mettre à jour. Vide : le guide s'arrête à "
        "« git pull » plutôt que d'annoncer une cible qui n'est pas la bonne.",
    )
    g_cloud.add_argument(
        "--git-name",
        default="",
        help="Nom pour le ~/.gitconfig de la VM (défaut : celui de l'hôte).",
    )
    g_cloud.add_argument(
        "--git-email",
        default="",
        help="Courriel pour le ~/.gitconfig de la VM (défaut : l'hôte).",
    )
    g_cloud.add_argument(
        "--no-git-identity",
        action="store_true",
        help="N'injecte pas l'identité git de l'hôte (user.name, user.email, "
        "core.editor) dans le ~/.gitconfig de la VM.",
    )
    g_cloud.add_argument(
        "--cache-ca",
        default="",
        help="Chemin, SUR L'HÔTE, du certificat de l'autorité du cache de "
        "téléchargement (erplibre_go_qemu_cache). Fourni, la VM approuve "
        "cette autorité dès son premier démarrage et ses téléchargements "
        "passent par le cache. Absent, rien n'est posé.",
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
        "--setup-host",
        action="store_true",
        help="Prépare l'hôte (paquets QEMU/libvirt, démon, groupe libvirt, "
        "réseau default) puis quitte. Ne déploie aucune VM.",
    )
    g_run.add_argument(
        "--reboot-if-needed",
        action="store_true",
        help="Avec --setup-host : PROPOSE un redémarrage si le noyau a été "
        "mis à jour depuis le démarrage (sinon libvirt ne peut pas créer "
        "virbr0). La question est posée sur /dev/tty et vaut non par défaut.",
    )
    g_run.add_argument(
        "--assume-yes-reboot",
        action="store_true",
        help="Redémarre sans poser la question. Réservé à une provision "
        "sans personne devant l'écran ; --assume-yes ne l'implique pas.",
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

    # Préparation de l'hôte : aucune image, aucune distro cible, aucun --name.
    # Traité AVANT la résolution de version/image pour rester utilisable seul.
    if args.setup_host:
        setup_host(
            Runner(
                use_sudo=not args.no_sudo and os.geteuid() != 0,
                dry_run=args.dry_run,
            ),
            args.assume_yes,
            args.no_install_deps,
            args.reboot_if_needed,
            args.assume_yes_reboot,
        )
        return

    versions, default_version = DISTROS[args.distro]
    if args.version is None:
        args.version = default_version
    if args.version not in versions:
        sys.exit(
            f"Version {args.version!r} inconnue pour {args.distro}. "
            f"Choix : {', '.join(versions)} (voir --list-images)."
        )
    # Certaines architectures ne sont publiées que par une partie des distros
    # (voir ARCH_DISTRO_SUPPORT) : on valide tôt plutôt qu'échouer au download.
    supported = ARCH_DISTRO_SUPPORT.get(args.arch)
    if supported is not None and args.distro not in supported:
        sys.exit(
            f"Architecture {args.arch} indisponible pour {args.distro!r} : "
            f"images cloud publiées seulement pour {', '.join(supported)}."
        )
    # Toutes les versions d'une distro ne sont pas publiées sur toutes les
    # architectures : le dire ici plutôt que d'échouer au téléchargement.
    ok_versions = arch_versions(args.distro, args.arch, versions)
    if args.version not in ok_versions:
        sys.exit(
            f"{args.distro} {args.version} n'est pas publié en {args.arch}.\n"
            f"  Versions disponibles : {', '.join(ok_versions) or 'aucune'}."
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
        # Émulation requise si l'arch diffère de l'hôte : installe l'émulateur
        # QEMU système adéquat (+ firmware UEFI pour arm64) et prévient de la
        # lenteur.
        if args.arch in EMULATOR_BINARY and args.arch != host_arch():
            ensure_emulator(
                args.arch, runner, args.assume_yes, args.no_install_deps
            )
            print(
                f"  Note : {args.arch} est ÉMULÉ (TCG) sur cet hôte "
                f"({host_arch()}) — le boot et l'installation seront "
                "nettement plus lents que l'architecture native."
            )

    installer: tuple[Path, Path] | None = None
    if uses_installer(args.distro, args.arch):
        # Voie debian-installer : aucune image cloud n'existe pour cette
        # combinaison, on télécharge l'installateur et on part d'un disque nu.
        cache = args.image_path.parent
        kernel = cache / f"debian-{args.version}-s390x-kernel"
        initrd_src = cache / f"debian-{args.version}-s390x-initrd.gz"
        initrd = cache / f"{args.name}-initrd.gz"
        # Le dimensionnement du catalogue vient des images cloud, où le
        # système est DÉJÀ installé. debian-installer, lui, déplie un système
        # de fichiers complet en mémoire avant d'écrire quoi que ce soit :
        # 1024 Mio est le plancher annoncé par Debian, sans marge, et un
        # manque de mémoire s'y manifeste par un écran figé sans message.
        # On relève le plancher, en le disant — un réglage explicite plus haut
        # n'est jamais abaissé.
        if args.memory < INSTALLER_MIN_RAM:
            print(
                f"  Mémoire portée à {INSTALLER_MIN_RAM} Mio pour"
                f" l'installateur (catalogue : {args.memory})."
            )
            args.memory = INSTALLER_MIN_RAM
        print(f"\n== 1/5 Installateur Debian {args.version} ({code}) s390x ==")
        download_image(
            [INSTALLER_URL.format(code=code, fichier="kernel.debian")],
            kernel,
            args.dry_run,
        )
        download_image(
            [INSTALLER_URL.format(code=code, fichier="initrd.debian")],
            initrd_src,
            args.dry_run,
        )

        print(f"\n== 2-3/5 Disque vierge {disk} ({args.disk_size}) ==")
        create_blank_disk(disk, args.disk_size, runner, args.force)

        print(f"\n== 4/5 Preseed embarqué dans l'initrd ==")
        static = static_net_plan(
            network_name(args.network), not args.dry_run, args.name
        )
        if static:
            print(
                f"  Adresse fixe retenue : {static['ip']}"
                f" (passerelle {static['gateway']})"
            )
        else:
            print(
                "  ⚠ Aucune adresse fixe déterminée : netcfg-static posera"
                " la question à l'écran et l'installation s'arrêtera."
            )
        build_installer_initrd(
            build_preseed(args, pw_hash, ssh_keys, static),
            initrd_src,
            initrd,
            runner,
        )
        installer = (kernel, initrd)
    else:
        print(
            f"\n== 1/5 Image cloud ({args.distro} {args.version} / {code}) =="
        )
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
    virt_install(args, disk, seed, resolved_osinfo, runner, installer)
    if installer:
        watch_and_restart(args.name, runner)

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
