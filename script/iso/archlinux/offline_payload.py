#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Fabrique du paquet hors ligne de la clé USB, côté hôte : ce que
l'installateur du live (erplibre_offline.py) monte et sert.

Le paquet est un répertoire (voir erplibre_offline pour sa forme),
puis une image ext4 LABEL=ERPLIBRE_DATA que le remastering ajoute à
l'ISO comme 3e partition (xorriso -append_partition 3).

Pièces que tout paquet exige :

- le mandataire Go compilé STATIQUE (CGO_ENABLED=0), sur l'hôte, avec la
  chaîne Go du dépôt : le binaire voyage DANS le paquet, à côté du
  magasin qu'il a écrit, et non dans l'ISO. Le format du magasin (clés,
  métadonnées) appartient à la version qui l'a rempli : un binaire de
  l'ISO, construit à une autre date, pourrait ne plus le lire. L'image
  de construction de l'ISO n'a pas de Go, et n'en a pas besoin ;
- l'autorité propre au paquet, créée par le mandataire lui-même
  (--init-ca) : jamais celle du cache de l'hôte, que ses VM approuvent ;
- le manifeste, avec l'empreinte des petites pièces ;
- l'image ext4, par « mkfs.ext4 -d » (sans root, sans montage), sans
  journal : la partition n'est montée qu'en lecture seule.

Fabrication complète (« build ») : une INSTALLATION DE RÉFÉRENCE du
profil ERPLibre, en QEMU, réseau ouvert.

- Le mandataire tourne SUR L'HÔTE en mode enregistrement, sur la boucle
  locale et deux ports libres, avec un magasin vide sous le répertoire de
  travail. --seed-git-mirrors y copie d'abord les miroirs git qu'un
  magasin local tient déjà pour ce profil (reflink quand le système de
  fichiers le permet) : l'installation passe quand même par le
  mandataire, qui les met à jour au lieu de les cloner.
- La VM démarre l'ISO en clé USB par son noyau (réponses par
  « erplibre.answers »), avec une 2e clé LABEL=ERPLIBRE_DATA qui ne porte
  qu'un manifeste d'enregistrement et le certificat de l'autorité :
  l'installateur suit son chemin hors ligne, et nft envoie la sortie
  80/443 du live au mandataire par la passerelle du réseau « user » de
  QEMU (RECORD_GATEWAY), qui mène à la boucle locale de l'hôte.
- Les paquets que le matériel de la VM n'a pas demandés, mais qu'un
  profil machine peut demander (hardware_packages), sont ensuite tirés
  au travers du mandataire depuis l'hôte, leur fermeture calculée par
  « pacman -Sp » sur les bases que l'installation a enregistrées.
- L'extraction (« assemble », relançable seule sur un répertoire de
  travail) : les fichiers pacman du magasin deviennent le dépôt du
  paquet, le reste du magasin est gardé tel quel (liens physiques), et
  seuls les miroirs git que le journal d'accès montre servis restent.

Le mandataire tourne sur l'hôte plutôt que dans le live : le magasin
s'écrit directement dans le répertoire de travail, sans rien à extraire
d'un disque de VM (ni montage root ni debugfs sur des dizaines de Gio),
l'amorçage des miroirs est une copie locale, et rien ne demande root.
C'est le binaire statique du paquet qui enregistre : le magasin a donc le
format que le live lira.

Base du dépôt : la base officielle enregistrée (core.db, extra.db) est
gardée si elle désigne, pour chaque paquet enregistré, un fichier présent
— elle peut dater d'un autre instant que les paquets quand l'étape
ERPLibre resynchronise sur un autre miroir. Sinon le dépôt est reconstruit
par repo-add sur la dernière version enregistrée de chaque paquet : la
base n'est alors pas signée, ce que la configuration d'Arch accepte
(SigLevel « Required DatabaseOptional ») ; chaque paquet reste vérifié par
son « .sig », que le dépôt porte.
"""

import argparse
import base64
import datetime
import email.utils
import importlib.machinery
import importlib.util
import json
import os
import posixpath
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
QEMU_CACHE_SRC = REPO_ROOT / "script" / "qemu_cache"
INSTALLER_SHARE = HERE / "profile/airootfs/usr/local/share/erplibre-install"
MACHINE_DIR = HERE / "machine"
CONFIG_TOOL = HERE / "profile/airootfs/usr/local/bin/erplibre-install-config"
MANIFEST_DIR = REPO_ROOT / "manifest"
for _chemin in (str(MACHINE_DIR), str(INSTALLER_SHARE)):
    if _chemin not in sys.path:
        sys.path.insert(0, _chemin)
import erplibre_offline as offline_mod  # noqa: E402

PROXY_REL = f"bin/{offline_mod.PROXY_NAME}"
CA_DIR_REL = "ca"
REPO_REL = "repo"
STORE_REL = "store"
# Marge de l'image : métadonnées ext4 (inodes, bitmaps) et arrondi des
# blocs, sur un magasin de dizaines de milliers de petits fichiers.
IMAGE_MARGIN = 0.08
IMAGE_MIN_EXTRA = 64 * 1024**2

OUT_ROOT = Path.home() / ".erplibre" / "iso" / "offline"
ISO_DIR = Path.home() / ".erplibre" / "iso"
# Le magasin du service de cache de l'hôte, quand il est installé : la
# valeur proposée à --seed-git-mirrors, lue seulement.
SEED_DEFAULT = "/var/cache/erplibre_go_qemu_cache/git"
# La passerelle du réseau « user » de QEMU : une connexion de la VM vers
# elle arrive sur la boucle locale de l'hôte, où écoute le mandataire.
RECORD_GATEWAY = "10.0.2.2"
RECORD_IMAGE_BYTES = 16 * 1024**2
TARGET_DISK = "vda"
OVMF_CODE = "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
OVMF_VARS = "/usr/share/edk2/x64/OVMF_VARS.4m.fd"
# Disque cible (qcow2, creux) : un profil Odoo clone les dépôts d'addons
# avec leur historique, une vingtaine de Gio.
DEFAULT_DISK_GIB = 32
PROFILE_DISK_GIB = {"odoo18": 96, "dev": 96}
DEFAULT_MEMORY_MIB = 6144
DEFAULT_CPUS = 4
DEFAULT_TIMEOUT_MIN = 240
# Les manifestes Google Repo que l'étape de chaque profil synchronise ;
# sert à l'amorçage seulement, l'installation clone ce qui manque.
SEED_MANIFESTS = {
    "odoo18": (
        "git_manifest_erplibre_odoo.xml",
        "git_manifest_erplibre_odoo_dev.xml",
        "git_manifest_odoo18.0.xml",
        "git_manifest_odoo18.0_dev.xml",
    ),
    "home": (
        "git_manifest_erplibre.xml",
        "git_manifest_erplibre_home_gnome_extension.xml",
    ),
}
SEED_MANIFESTS["dev"] = SEED_MANIFESTS["odoo18"]
# La source de git-repo, que chaque « repo init » clone.
SEED_EXTRA = ("https://gerrit.googlesource.com/git-repo",)
# Profils dont l'étape lance « make install_os », qui demande PostgreSQL
# (voir build_iso.iso_profiles).
POSTGRES_PROFILES = ("odoo18", "dev")
# Ce que hardware_packages() ajoute aux tables : chargeurs (le greffon les
# pose selon le micrologiciel), zram, micrologiciels son, que linux-firmware
# ne porte pas.
HARDWARE_EXTRA = (
    "grub",
    "efibootmgr",
    "zram-generator",
    "apparmor",
    "xfsprogs",
    "lvm2",
    "cryptsetup",
    "sof-firmware",
    "alsa-firmware",
    "alsa-ucm-conf",
)
CLOSURE_MIRROR = "https://geo.mirror.pkgbuild.com"
# Même règle que composantPacman (depotpacman.go), deux-points de l'époque
# compris (« grub-2:2.16-1-x86_64.pkg.tar.zst »).
PACMAN_COMPONENT = re.compile(r"^[A-Za-z0-9@_+.:-]+$")
HEX2 = re.compile(r"^[0-9a-fA-F]{2}$")
PKG_RE = re.compile(r"\.pkg\.tar\.(zst|xz|gz|bz2)$")
GIT_NEGOTIATION = ("/info/refs", "/git-upload-pack")


def proxy_build_command(out):
    """(argv, variables) de la compilation statique du mandataire vers
    `out`, à lancer dans QEMU_CACHE_SRC. -trimpath et un buildid vide :
    le binaire ne porte aucun chemin de l'hôte."""
    argv = [
        "go",
        "build",
        "-trimpath",
        "-ldflags",
        "-s -w -buildid=",
        "-o",
        str(out),
        ".",
    ]
    return argv, {"CGO_ENABLED": "0", "GOFLAGS": "-mod=mod"}


def build_proxy(out, src=QEMU_CACHE_SRC, run=subprocess.run):
    """Compile le mandataire statique dans `out` ; rend le code de go.
    Le cache de compilation et les fichiers de travail de go vivent dans
    un temporaire À CÔTÉ de `out`, pas sous /tmp : un /tmp en tmpfs étroit
    fait échouer la compilation faute de place."""
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    argv, extra = proxy_build_command(out)
    with tempfile.TemporaryDirectory(
        prefix="erplibre-gocache-", dir=str(out.parent)
    ) as cache:
        travail = os.path.join(cache, "tmp")
        os.makedirs(travail)
        env = dict(
            os.environ,
            GOCACHE=os.path.join(cache, "cache"),
            GOTMPDIR=travail,
            **extra,
        )
        return run(argv, cwd=str(src), env=env, check=False).returncode


def sha256_file(path):
    return offline_mod.sha256_file(path)


def tree_size(root):
    """(octets, fichiers) sous `root`, liens non suivis."""
    octets = fichiers = 0
    for dossier, _sous, noms in os.walk(root):
        for nom in noms:
            chemin = os.path.join(dossier, nom)
            if os.path.islink(chemin):
                continue
            octets += os.path.getsize(chemin)
            fichiers += 1
    return octets, fichiers


def part_entry(root, rel, digest):
    """L'entrée du manifeste pour la pièce `rel` : un fichier avec son
    empreinte, ou un arbre avec sa taille et son nombre de fichiers."""
    chemin = Path(root) / rel
    if digest:
        return {
            "path": rel,
            "size": chemin.stat().st_size,
            "sha256": sha256_file(chemin),
        }
    octets, fichiers = tree_size(chemin)
    return {"path": rel, "size": octets, "files": fichiers}


def manifest_document(
    root,
    profile,
    source,
    archinstall_version,
    arch_snapshot,
    proxy_version,
    created=None,
):
    """Le manifeste du paquet sous `root`. `source` : {"git_url",
    "branch", "commit"} du dépôt ERPLibre que l'installation de
    référence a cloné. Lève ValueError si le document ne passe pas
    erplibre_offline.check_manifest."""
    created = created or datetime.datetime.now(datetime.timezone.utc)
    parts = {
        "proxy": part_entry(root, PROXY_REL, True),
        "ca_cert": part_entry(root, f"{CA_DIR_REL}/ca.crt", True),
        "ca_key": part_entry(root, f"{CA_DIR_REL}/ca.key", True),
        "repo": part_entry(root, REPO_REL, False),
        "store": part_entry(root, STORE_REL, False),
    }
    doc = {
        "schema": offline_mod.MANIFEST_SCHEMA,
        "erplibre_profile": profile,
        "created": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arch": offline_mod.ARCH,
        "erplibre": dict(source),
        "archinstall_version": archinstall_version,
        "arch_snapshot": arch_snapshot,
        "proxy_version": proxy_version,
        "parts": parts,
        "sizes": {"total": sum(p["size"] for p in parts.values())},
    }
    erreurs = offline_mod.check_manifest(doc)
    if erreurs:
        raise ValueError("; ".join(erreurs))
    return doc


def readable_modes(root, keep_private=(f"{CA_DIR_REL}/ca.key",)):
    """Rend chaque fichier lisible et chaque dossier traversable par
    « autres » sous `root`, sauf `keep_private` : le mandataire du live
    tourne sous son propre compte, et le magasin, que le mandataire de
    l'hôte écrit en 0600, lui resterait fermé — chaque requête tomberait
    alors en « absent ». La clé de l'autorité reste 0600 : le live la
    copie en root vers le compte du mandataire. Rend le nombre de modes
    changés."""
    prives = {str(Path(root) / rel) for rel in keep_private}
    changes = 0
    for dossier, sous, noms in os.walk(root):
        for nom in sous:
            chemin = os.path.join(dossier, nom)
            mode = os.lstat(chemin).st_mode
            if not os.path.islink(chemin) and mode & 0o555 != 0o555:
                os.chmod(chemin, (mode | 0o555) & 0o7777)
                changes += 1
        for nom in noms:
            chemin = os.path.join(dossier, nom)
            if chemin in prives or os.path.islink(chemin):
                continue
            mode = os.lstat(chemin).st_mode
            if mode & 0o444 != 0o444:
                os.chmod(chemin, (mode | 0o444) & 0o7777)
                changes += 1
    return changes


def image_bytes(content_bytes):
    """La taille de l'image ext4 pour `content_bytes` de contenu, arrondie
    au Mio."""
    brut = int(content_bytes * (1 + IMAGE_MARGIN)) + IMAGE_MIN_EXTRA
    mib = 1024**2
    return (brut + mib - 1) // mib * mib


def mkfs_argv(src, image):
    """mkfs.ext4 qui remplit `image` (déjà à sa taille) depuis `src` :
    étiquette ERPLIBRE_DATA, sans journal ni réserve root, racine à
    root. Les fichiers gardent leurs modes ; le mandataire du live lit
    tout en « autres », d'où des fichiers 0644 et des dossiers 0755."""
    return [
        "mkfs.ext4",
        "-q",
        "-F",
        "-L",
        offline_mod.DATA_LABEL,
        "-O",
        "^has_journal",
        "-m",
        "0",
        "-E",
        "root_owner=0:0",
        "-d",
        str(src),
        str(image),
    ]


def make_image(src, image, run=subprocess.run):
    """Écrit l'image ext4 de `src` dans `image` ; rend le code de
    mkfs.ext4."""
    readable_modes(src)
    octets, _fichiers = tree_size(src)
    with open(image, "wb") as fh:
        fh.truncate(image_bytes(octets))
    return run(mkfs_argv(src, image), check=False).returncode


def _config_tool():
    """L'outil de configuration archinstall de l'ISO, chargé comme le
    cœur le charge : sa liste STAGE_PACKAGES fait foi."""
    nom = "erplibre_install_config"
    chargeur = importlib.machinery.SourceFileLoader(nom, str(CONFIG_TOOL))
    spec = importlib.util.spec_from_loader(nom, chargeur)
    mod = importlib.util.module_from_spec(spec)
    chargeur.exec_module(mod)
    return mod


# Installation de référence (pur)


def mirror_rel(url):
    """« <hôte>/<chemin>.git » : le répertoire du miroir git de `url` sous
    la racine des miroirs, la règle du mandataire (GitMirror.CheminMiroir).
    None si l'URL n'a ni hôte ni chemin, ou porte « . » ou « .. »."""
    morceaux = urllib.parse.urlsplit(url or "")
    chemin = morceaux.path.strip("/")
    if chemin.endswith(".git"):
        chemin = chemin[: -len(".git")]
    segments = chemin.split("/")
    if not morceaux.netloc or not chemin:
        return None
    if any(s in ("", ".", "..") for s in segments):
        return None
    return f"{morceaux.netloc}/{chemin}.git"


def manifest_repos(texte):
    """Les URL des projets d'un manifeste Google Repo (XML) : « fetch » du
    remote (celui du projet, sinon celui de <default>) suivi du nom."""
    racine = ET.fromstring(texte)
    remotes = {
        r.get("name"): r.get("fetch") or ""
        for r in racine.findall("remote")
        if r.get("name")
    }
    defaut = racine.find("default")
    remote_defaut = defaut.get("remote") if defaut is not None else None
    urls = []
    for projet in racine.findall("project"):
        base = remotes.get(projet.get("remote") or remote_defaut)
        nom = projet.get("name")
        if base and nom:
            urls.append(base.rstrip("/") + "/" + nom.lstrip("/"))
    return urls


def seed_repos(profile, git_url, manifest_dir=MANIFEST_DIR):
    """Les dépôts dont un miroir déjà tenu peut amorcer l'enregistrement
    de `profile` : ceux des manifestes du profil (SEED_MANIFESTS), le
    dépôt ERPLibre cloné par l'étape et SEED_EXTRA. Aucun pour un profil
    sans étape. Un manifeste illisible est sauté : l'amorçage n'est qu'un
    raccourci, l'installation clone ce qui manque."""
    if profile not in SEED_MANIFESTS:
        return []
    urls = [git_url, *SEED_EXTRA]
    for nom in SEED_MANIFESTS[profile]:
        try:
            texte = (Path(manifest_dir) / nom).read_text("utf-8")
            urls += manifest_repos(texte)
        except (OSError, ET.ParseError):
            continue
    vus, out = set(), []
    for url in urls:
        rel = mirror_rel(url)
        if rel and rel not in vus:
            vus.add(rel)
            out.append(url)
    return out


def seed_plan(urls, seed_dir, dest_git, isdir=os.path.isdir):
    """[(source, destination)] des miroirs à copier : présents sous
    `seed_dir`, absents sous `dest_git`."""
    out = []
    for url in urls:
        rel = mirror_rel(url)
        if not rel:
            continue
        src = os.path.join(seed_dir, rel)
        dst = os.path.join(dest_git, rel)
        if isdir(src) and not isdir(dst):
            out.append((src, dst))
    return out


def seed_argv(src, dst):
    """Copie d'un miroir : reflink quand le système de fichiers le permet
    (aucun octet dupliqué), copie ordinaire sinon. Propriétaire non
    gardé : le miroir devient celui du compte qui fabrique."""
    return [
        "cp",
        "-r",
        "--reflink=auto",
        "--preserve=mode,timestamps",
        "--",
        src,
        dst,
    ]


def record_manifest(
    profile, source, ca_sha256, ports, created, gateway=RECORD_GATEWAY
):
    """Le manifeste de la clé d'enregistrement : le live y lit le profil,
    la source ERPLibre et l'adresse du mandataire de l'hôte. Lève
    ValueError s'il ne passe pas erplibre_offline.check_manifest."""
    doc = {
        "schema": offline_mod.MANIFEST_SCHEMA,
        "mode": offline_mod.MODE_RECORD,
        "erplibre_profile": profile,
        "created": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arch": offline_mod.ARCH,
        "erplibre": {
            "git_url": source["git_url"],
            "branch": source["branch"],
        },
        "record": {
            "proxy": gateway,
            "http_port": ports[0],
            "tls_port": ports[1],
        },
        "parts": {
            "ca_cert": {"path": f"{CA_DIR_REL}/ca.crt", "sha256": ca_sha256}
        },
    }
    erreurs = offline_mod.check_manifest(doc)
    if erreurs:
        raise ValueError("; ".join(erreurs))
    return doc


def answers_document(profile, password, disk=TARGET_DISK):
    """Les réponses de l'installation de référence (schéma 1 du cœur) :
    profil machine « generic », disque `disk` de la VM, compte et fuseau
    fixes, « offline » vrai pour que le cœur prenne la clé
    d'enregistrement. Le mot de passe est tiré à chaque fabrication : la
    cible est jetée."""
    return {
        "schema": 1,
        "answers": {
            "live.keymap": "us",
            "system.timezone": "UTC",
            "user.name": "erplibre",
            "security.header_backup": False,
            "disk.target": f"/dev/{disk}",
        },
        "erplibre_profile": profile,
        "root": "lock",
        "confirm": {"disk": disk},
        "offline": True,
        "secrets": {"user_password": password},
    }


def kernel_cmdline(iso_uuid, answers):
    """La ligne du noyau du live : support trouvé par son UUID et gardé
    monté (copytoram=n), console série, réponses en base64."""
    b64 = base64.b64encode(
        json.dumps(answers, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return (
        f"archisobasedir=arch archisosearchuuid={iso_uuid} copytoram=n "
        "console=tty0 console=ttyS0,115200 "
        f"erplibre.answers=b64:{b64}"
    )


def proxy_record_argv(binary, work, ports, lang="fr"):
    """Le mandataire en mode enregistrement : boucle locale seulement,
    magasin et miroirs git du répertoire de travail, journal d'accès (la
    liste de ce que l'installation a tiré). Le fichier d'exceptions est
    celui du travail, qui n'existe pas : jamais celui du service de
    l'hôte. --sans-tunnel : la VM le joint par la passerelle de QEMU, sans
    détournement noyau sur l'hôte, si bien qu'un tunnel n'aurait aucune
    destination ; un client qui refuse une fois l'autorité ne fait donc
    pas perdre l'hôte pour le reste de l'enregistrement."""
    store = os.path.join(work, STORE_REL)
    return [
        str(binary),
        "--ecoute",
        "127.0.0.1",
        "--http-port",
        str(ports[0]),
        "--tls-port",
        str(ports[1]),
        "--cache-dir",
        store,
        "--git-mirror-dir",
        os.path.join(store, "git"),
        "--ca-dir",
        os.path.join(work, CA_DIR_REL),
        "--access-log",
        os.path.join(work, "access.jsonl"),
        "--bypass-file",
        os.path.join(work, "bypass"),
        "--sans-tunnel",
        "--lang",
        lang,
    ]


def qemu_argv(paths, memory_mib, cpus, cmdline, ovmf=None):
    """La VM de référence : noyau et initramfs du live passés
    directement (la ligne du noyau porte les réponses), ISO et clé
    d'enregistrement en clés USB, disque cible virtio (vda), réseau
    « user » de QEMU, console série dans un fichier, arrêt au lieu de
    redémarrer. `ovmf` (code, variables) démarre en UEFI : le chargeur
    installé est alors celui d'une machine UEFI."""
    argv = [
        "qemu-system-x86_64",
        "-machine",
        "q35,accel=kvm",
        "-cpu",
        "host",
        "-m",
        str(memory_mib),
        "-smp",
        str(cpus),
    ]
    if ovmf:
        argv += [
            "-drive",
            f"if=pflash,format=raw,readonly=on,file={ovmf[0]}",
            "-drive",
            f"if=pflash,format=raw,file={ovmf[1]}",
        ]
    argv += [
        "-kernel",
        paths["kernel"],
        "-initrd",
        paths["initrd"],
        "-append",
        cmdline,
        "-device",
        "qemu-xhci,id=xhci",
        "-drive",
        f"if=none,id=boot,file={paths['iso']},format=raw,readonly=on",
        "-device",
        "usb-storage,bus=xhci.0,drive=boot,serial=BOOT0001,removable=on",
        "-drive",
        f"if=none,id=rec,file={paths['record_img']},format=raw,readonly=on",
        "-device",
        "usb-storage,bus=xhci.0,drive=rec,serial=DATA0001,removable=on",
        "-drive",
        f"if=virtio,file={paths['target']},format=qcow2",
        "-nic",
        "user,model=virtio-net-pci",
        "-display",
        "none",
        "-serial",
        f"file:{paths['serial']}",
        "-no-reboot",
    ]
    return argv


def hardware_packages():
    """Les paquets qu'un profil machine peut demander selon le matériel
    ou ses réglages, et qu'une VM ne tire pas : noyaux permis, microcodes,
    pilotes graphiques libres, alimentation, shells, AppArmor, chiffrement
    et systèmes de fichiers, chargeurs, micrologiciels son. Lus dans les
    tables du profil machine et de l'installateur, plus
    HARDWARE_EXTRA ; NVIDIA est écarté (pilote reporté)."""
    import erplibre_archinstall as ai
    import machine_profile as mp

    noms = list(mp.KERNELS)
    noms += offline_mod.UCODE.values()
    for cle, paquets in mp.GPU_PACKAGES.items():
        if not cle.startswith("nvidia"):
            noms += paquets
    for paquets in mp.POWER_PACKAGES.values():
        noms += paquets
    for paquets in mp.SHELL_PACKAGES.values():
        noms += paquets
    noms += ai.APPARMOR_EXTRA_PACKAGES
    noms += ai.AUR_BUILD_PACKAGES
    noms += HARDWARE_EXTRA
    vus, out = set(), []
    for n in noms:
        if n not in vus:
            vus.add(n)
            out.append(n)
    return out


def gate_packages(profile):
    """Les noms que le contrôle d'avant l'effacement chercherait pour une
    installation de ce profil ERPLibre, sur une machine Intel ou AMD, UEFI
    ou BIOS : sert à vérifier le paquet fabriqué. Les paquets de l'étape
    sont ceux de l'outil de configuration de l'ISO."""
    paquets = []
    if profile != "gnome":
        paquets = list(_config_tool().STAGE_PACKAGES)
        if profile in POSTGRES_PROFILES:
            paquets.append("postgresql")
    config = {
        "kernels": ["linux"],
        "packages": paquets,
        "bootloader_config": {"bootloader": "Grub"},
    }
    noms = []
    for fabricant in offline_mod.UCODE:
        for n in offline_mod.required_packages(config, fabricant):
            if n not in noms:
                noms.append(n)
    return noms


# Magasin et dépôt (pur sur des fichiers)


def pacman_target(url):
    """(dépôt, arch, fichier) d'une URL de miroir Arch, la règle du
    mandataire (DepotPacman.Fichier) : les quatre derniers segments du
    chemin sont « <dépôt>/os/<arch>/<fichier> », sans séparateur ni point
    en tête. None pour toute autre URL."""
    chemin = urllib.parse.urlsplit(url or "").path
    morceaux = [m for m in posixpath.normpath("/" + chemin).split("/") if m]
    if len(morceaux) < 4:
        return None
    depot, segment, arch, nom = morceaux[-4:]
    if segment != "os":
        return None
    for composant in (depot, arch, nom):
        if not PACMAN_COMPONENT.match(composant) or composant.startswith("."):
            return None
    return depot, arch, nom


def iter_store(store):
    """(métadonnées, chemin du corps) de chaque objet du magasin : les
    casiers à deux niveaux de deux chiffres hexadécimaux seulement, comme
    le mandataire les range (git/ et la sentinelle sont à côté). Un méta
    illisible est sauté."""
    racine = Path(store)
    if not racine.is_dir():
        return
    for casier in sorted(racine.iterdir()):
        if not casier.is_dir() or not HEX2.match(casier.name):
            continue
        for sous in sorted(casier.iterdir()):
            if not sous.is_dir() or not HEX2.match(sous.name):
                continue
            for meta in sorted(sous.glob("*.meta")):
                try:
                    doc = json.loads(meta.read_text("utf-8"))
                except (OSError, ValueError):
                    continue
                yield doc, meta.with_suffix(".body")


def is_body(doc, body):
    """Vrai pour un corps 200 complet : ni statut seul, ni HEAD, ni corps
    de taille autre que celle du méta."""
    if doc.get("method", "GET") != "GET" or doc.get("status_only"):
        return False
    if doc.get("status") not in (None, 0, 200):
        return False
    try:
        return os.path.getsize(body) == doc.get("size")
    except OSError:
        return False


def pkg_name(fichier):
    """Le nom du paquet d'un fichier « <nom>-<ver>-<rel>-<arch>.pkg.tar.* »,
    None pour un autre fichier."""
    if not PKG_RE.search(fichier):
        return None
    base = PKG_RE.sub("", fichier)
    morceaux = base.rsplit("-", 3)
    return morceaux[0] if len(morceaux) == 4 else None


def db_gaps(index, files):
    """Les paquets enregistrés (fichiers `files`) dont la base `index`
    (erplibre_offline.read_db) désigne un AUTRE fichier, absent : la base
    est d'un autre instant que ces paquets."""
    noms = {pkg_name(f) for f in files} - {None}
    return sorted(
        n
        for n in noms
        if n in index["packages"] and index["packages"][n] not in files
    )


def choose_db(candidates, files):
    """(chemin, manques) de la base retenue parmi `candidates`,
    [(date, chemin, index)] : la plus récente sans manque, sinon celle
    qui manque le moins (alors reconstruite par l'appelant)."""
    meilleur = None
    for date, chemin, index in candidates:
        manques = db_gaps(index, files)
        cle = (len(manques), _neg(date))
        if meilleur is None or cle < meilleur[0]:
            meilleur = (cle, chemin, manques)
    if meilleur is None:
        return None, []
    return meilleur[1], meilleur[2]


def _neg(date):
    """Clé de tri qui place la date la plus récente en premier."""
    return tuple(-ord(c) for c in str(date or ""))


def repo_files(index, files):
    """(gardés, sans signature) : les fichiers que la base `index` désigne
    et que `files` contient, chacun avec son « .sig » s'il est là ; puis
    les paquets dont ni la base ni le dépôt ne portent la signature —
    pacman les refuserait."""
    gardes, sans = [], []
    for nom, fichier in sorted(index["packages"].items()):
        if fichier not in files:
            continue
        gardes.append(fichier)
        if fichier + ".sig" in files:
            gardes.append(fichier + ".sig")
        elif nom not in index.get("signed", ()):
            sans.append(nom)
    return gardes, sans


def newest_per_package(entries):
    """{fichier: date} réduit à la version la plus récemment enregistrée
    de chaque paquet (repo-add n'en garde qu'une), avec les .sig de
    celles-ci."""
    choix = {}
    for fichier, date in entries.items():
        nom = pkg_name(fichier)
        if nom and (nom not in choix or date > choix[nom][1]):
            choix[nom] = (fichier, date)
    out = {}
    for fichier, date in choix.values():
        out[fichier] = date
        if fichier + ".sig" in entries:
            out[fichier + ".sig"] = entries[fichier + ".sig"]
    return out


def git_repos_used(lines):
    """Les miroirs (mirror_rel) que les lignes du journal d'accès montrent
    servis : toute négociation git (info/refs, git-upload-pack)."""
    vus = set()
    for ligne in lines:
        url = ligne.get("url") or ""
        chemin = urllib.parse.urlsplit(url).path
        for suffixe in GIT_NEGOTIATION:
            if chemin.endswith(suffixe):
                base = urllib.parse.urlsplit(url)._replace(
                    path=chemin[: -len(suffixe)], query=""
                )
                rel = mirror_rel(urllib.parse.urlunsplit(base))
                if rel:
                    vus.add(rel)
    return vus


def read_access_log(path):
    """Les lignes JSON du journal d'accès ; une ligne illisible est
    sautée."""
    lignes = []
    try:
        with open(path, encoding="utf-8") as fh:
            for brut in fh:
                try:
                    lignes.append(json.loads(brut))
                except ValueError:
                    continue
    except OSError:
        pass
    return lignes


def pkglist_version(texte, paquet="archinstall"):
    """La version (sans le pkgrel) de `paquet` dans le pkglist.x86_64.txt
    d'une ISO archiso, ou ""."""
    for ligne in texte.splitlines():
        morceaux = ligne.split()
        if len(morceaux) == 2 and morceaux[0] == paquet:
            return morceaux[1].rsplit("-", 1)[0]
    return ""


def snapshot_date(doc):
    """La date (AAAA-MM-JJ) d'une base enregistrée : son Last-Modified,
    sinon la date d'enregistrement."""
    entetes = doc.get("header") or {}
    for valeur in entetes.get("Last-Modified") or []:
        try:
            return email.utils.parsedate_to_datetime(valeur).strftime(
                "%Y-%m-%d"
            )
        except (TypeError, ValueError):
            continue
    return str(doc.get("stored_at") or "")[:10]


def pacman_conf(mirror=CLOSURE_MIRROR):
    """pacman.conf de « pacman -Sp » sur les bases enregistrées : aucune
    vérification (rien n'est installé), core puis extra."""
    return (
        "[options]\n"
        f"Architecture = {offline_mod.ARCH}\n"
        "SigLevel = Never\n"
        "\n[core]\n"
        f"Server = {mirror}/$repo/os/$arch\n"
        "\n[extra]\n"
        f"Server = {mirror}/$repo/os/$arch\n"
    )


def not_found(sortie):
    """Les noms que pacman dit introuvables (« target not found: x »)."""
    return re.findall(r"target not found: (\S+)", sortie or "")


def curl_config(urls, tls_port, ca):
    """La configuration « curl -K » qui tire `urls` au travers du
    mandataire : chaque hôte https est envoyé sur 127.0.0.1:`tls_port`
    (--connect-to), l'autorité du travail approuvée, les corps jetés (le
    mandataire les garde)."""
    lignes = [
        "fail",
        "silent",
        "show-error",
        "location",
        f'cacert = "{ca}"',
    ]
    hotes = sorted({urllib.parse.urlsplit(u).hostname for u in urls} - {None})
    for hote in hotes:
        lignes.append(f'connect-to = "{hote}:443:127.0.0.1:{tls_port}"')
    for url in urls:
        lignes.append(f'url = "{url}"')
        lignes.append('output = "/dev/null"')
    return "\n".join(lignes) + "\n"


# Plan de fabrication (pur)


def work_paths(root):
    """Les chemins d'une fabrication sous `root`
    (OUT_ROOT/<profil>-<horodatage>)."""
    root = Path(root)
    work = root / "work"
    return {
        "root": str(root),
        "work": str(work),
        "store": str(work / STORE_REL),
        "git": str(work / STORE_REL / "git"),
        "ca": str(work / CA_DIR_REL),
        "proxy": str(work / PROXY_REL),
        "record_dir": str(work / "record"),
        "record_img": str(work / "record.img"),
        "boot": str(work / "boot"),
        "kernel": str(work / "boot" / "vmlinuz-linux"),
        "initrd": str(work / "boot" / "initramfs-linux.img"),
        "pkglist": str(work / "boot" / "pkglist.x86_64.txt"),
        "target": str(work / "target.qcow2"),
        "ovmf_vars": str(work / "ovmf_vars.fd"),
        "serial": str(work / "serial.log"),
        "proxy_log": str(work / "proxy.log"),
        "access": str(work / "access.jsonl"),
        "state": str(work / "state.json"),
        "payload": str(root / "payload"),
        "report": str(root / "report.json"),
    }


def build_plan(opts, now, ports, iso_uuid):
    """Le plan d'une fabrication, sans rien lancer : chemins, réglages de
    la VM, dépôts à amorcer et commandes. `opts` : profile, iso, out,
    git_url, branch, seed (ou None), memory, cpus, disk_gib, timeout_min,
    lang. Les réponses n'y portent pas de mot de passe : il est tiré à
    l'exécution."""
    stamp = now.strftime("%Y%m%d-%H%M%S")
    racine = Path(opts["out"]) / f"{opts['profile']}-{stamp}"
    paths = work_paths(racine)
    paths["iso"] = str(opts["iso"])
    disque = opts.get("disk_gib") or PROFILE_DISK_GIB.get(
        opts["profile"], DEFAULT_DISK_GIB
    )
    seeds = []
    if opts.get("seed"):
        seeds = seed_plan(
            seed_repos(opts["profile"], opts["git_url"]),
            opts["seed"],
            paths["git"],
        )
    ovmf = (
        (OVMF_CODE, paths["ovmf_vars"]) if Path(OVMF_CODE).exists() else None
    )
    return {
        "profile": opts["profile"],
        "created": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stamp": stamp,
        "source": _source(opts),
        "ports": list(ports),
        "iso_uuid": iso_uuid,
        "paths": paths,
        "memory": opts["memory"],
        "cpus": opts["cpus"],
        "disk_gib": disque,
        "timeout_min": opts["timeout_min"],
        "lang": opts.get("lang") or "fr",
        "ovmf": list(ovmf) if ovmf else None,
        "seeds": seeds,
        "image": str(
            racine / f"erplibre-offline-{opts['profile']}-{stamp}.img"
        ),
    }


def _source(opts):
    """La source ERPLibre du plan ; avec l'empreinte de la commande du
    profil quand `opts` la donne (command_sha256), que le manifeste
    reprend et que le live compare à la sienne avant d'effacer."""
    source = {"git_url": opts["git_url"], "branch": opts["branch"]}
    if opts.get("command_sha256"):
        source[offline_mod.COMMAND_KEY] = opts["command_sha256"]
    return source


def describe_plan(plan):
    """Les lignes que --dry-run affiche."""
    p = plan["paths"]
    lignes = [
        f"profile      : {plan['profile']}",
        f"ISO          : {p['iso']} (UUID {plan['iso_uuid']})",
        f"source       : {plan['source']['git_url']} "
        f"({plan['source']['branch']})",
        f"directory    : {p['root']}",
        f"VM           : {plan['memory']} MiB, {plan['cpus']} CPU, "
        f"target {plan['disk_gib']} GiB qcow2, "
        + ("UEFI (OVMF)" if plan["ovmf"] else "BIOS"),
        f"proxy        : 127.0.0.1:{plan['ports'][0]}/{plan['ports'][1]}, "
        f"reached from the VM at {RECORD_GATEWAY}",
        f"seeded git   : {len(plan['seeds'])} mirror(s)",
        f"image        : {plan['image']}",
        "",
        "steps:",
        "  1. go build (static proxy) -> " + p["proxy"],
        "  2. proxy --init-ca -> " + p["ca"],
    ]
    n = 3
    if plan["seeds"]:
        lignes.append(f"  {n}. copy seeded mirrors:")
        for src, dst in plan["seeds"][:5]:
            lignes.append(f"       {' '.join(seed_argv(src, dst))}")
        if len(plan["seeds"]) > 5:
            lignes.append(f"       ... {len(plan['seeds']) - 5} more")
        n += 1
    lignes += [
        f"  {n}. record key: {' '.join(mkfs_argv(p['record_dir'], p['record_img']))}",
        f"  {n + 1}. extract kernel, initramfs and pkglist from the ISO",
        f"  {n + 2}. proxy (record): "
        + " ".join(proxy_record_argv(p["proxy"], p["work"], plan["ports"])),
        f"  {n + 3}. reference install (timeout {plan['timeout_min']} min): "
        "qemu-system-x86_64 ... -append '... erplibre.answers=b64:<answers>'",
        f"  {n + 4}. hardware packages through the proxy: "
        + " ".join(hardware_packages()),
        f"  {n + 5}. assemble payload -> {p['payload']}",
        f"  {n + 6}. ext4 image + sha256 -> {plan['image']}",
    ]
    return lignes


# Exécution (impur)


class BuildError(Exception):
    """Une étape de la fabrication a échoué ; le message la nomme."""


def _say(log, message):
    log(f"[offline-payload] {message}")


def _run(argv, log, run=subprocess.run, **kw):
    _say(log, "$ " + " ".join(str(a) for a in argv))
    res = run([str(a) for a in argv], check=False, **kw)
    if res.returncode != 0:
        raise BuildError(f"{argv[0]}: exit code {res.returncode}")
    return res


def free_ports(n=2):
    """`n` ports TCP libres sur la boucle locale, au moment de l'appel."""
    prises, ports = [], []
    try:
        for _i in range(n):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            prises.append(s)
            ports.append(s.getsockname()[1])
    finally:
        for s in prises:
            s.close()
    return ports


def iso_uuid(iso, run=subprocess.run):
    """L'UUID ISO 9660 (archisosearchuuid) lu par blkid, sans root."""
    res = run(
        ["blkid", "-p", "-s", "UUID", "-o", "value", str(iso)],
        capture_output=True,
        text=True,
        check=False,
    )
    return (res.stdout or "").strip()


def newest_iso(iso_dir=ISO_DIR):
    """L'ISO ERPLibre la plus récente de `iso_dir`, ou None."""
    isos = sorted(
        Path(iso_dir).glob("erplibre-archlinux-*-x86_64.iso"),
        key=lambda p: p.stat().st_mtime,
    )
    return isos[-1] if isos else None


def _link(src, dst):
    """Lien physique, copie si les deux chemins ne partagent pas de
    système de fichiers."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _link_tree(src, dst):
    """`src` recopié sous `dst` en liens physiques, répertoires vides
    compris : un miroir git dont les références sont toutes dans
    packed-refs n'a que des refs/heads et refs/tags vides, et git ne
    reconnaît pas un dépôt nu sans refs/ (« repository not found » au
    clone servi hors ligne). Les liens symboliques sont sautés."""
    for dossier, _sous, noms in os.walk(src):
        rel = os.path.relpath(dossier, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for nom in noms:
            chemin = os.path.join(dossier, nom)
            if os.path.islink(chemin):
                continue
            _link(chemin, os.path.join(dst, rel, nom))


def _write_json(path, doc, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.chmod(path, mode)


def _wait_tcp(port, timeout_s=20):
    for _i in range(timeout_s * 4):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _wait_marker(serial, proc, timeout_s, log):
    """Le code de « __ERPLIBRE_EXIT__ <code> » sur la console série, None
    si la VM s'arrête ou le délai passe sans lui."""
    motif = re.compile(r"__ERPLIBRE_EXIT__ (\d+)")
    fin = time.monotonic() + timeout_s
    vu = 0
    while time.monotonic() < fin:
        try:
            texte = Path(serial).read_text("utf-8", "replace")
        except OSError:
            texte = ""
        for ligne in texte[vu:].splitlines():
            if "[erplibre]" in ligne or "ERPLibre" in ligne:
                _say(log, "vm: " + ligne.strip()[:160])
        vu = len(texte)
        m = motif.search(texte)
        if m:
            return int(m.group(1))
        if proc.poll() is not None:
            return None
        time.sleep(5)
    return None


def _print(message):
    print(message, flush=True)


def proxy_init_ca_argv(binary, ca_dir):
    """L'argv qui crée l'autorité du paquet : --ca-paquet lui donne un
    nom distinct de celle du cache de l'hôte et une validité de deux ans,
    début reculé d'une semaine (mitm.go, profilPaquet)."""
    return [binary, "--init-ca", "--ca-paquet", "--ca-dir", ca_dir]


def record(plan, log=_print, run=subprocess.run):
    """L'installation de référence du plan : mandataire, clé
    d'enregistrement, VM. Rend l'état écrit dans state.json ; BuildError
    sur échec, le mandataire et la VM arrêtés."""
    p = plan["paths"]
    for cle in ("work", "store", "git", "boot", "record_dir"):
        os.makedirs(p[cle], exist_ok=True)
    etat = {
        "plan": {k: v for k, v in plan.items() if k != "seeds"},
        "seeded": len(plan["seeds"]),
        "times": {},
    }
    t0 = time.monotonic()
    if build_proxy(p["proxy"], run=run) != 0:
        raise BuildError("go build failed")
    _run(proxy_init_ca_argv(p["proxy"], p["ca"]), log, run=run)
    for src, dst in plan["seeds"]:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _run(seed_argv(src, dst), log, run=run)
    etat["times"]["prepare_s"] = round(time.monotonic() - t0)

    ca_crt = os.path.join(p["ca"], "ca.crt")
    rec_ca = os.path.join(p["record_dir"], CA_DIR_REL, "ca.crt")
    os.makedirs(os.path.dirname(rec_ca), exist_ok=True)
    shutil.copyfile(ca_crt, rec_ca)
    created = datetime.datetime.strptime(plan["created"], "%Y-%m-%dT%H:%M:%SZ")
    doc = record_manifest(
        plan["profile"],
        plan["source"],
        sha256_file(rec_ca),
        plan["ports"],
        created,
    )
    _write_json(os.path.join(p["record_dir"], offline_mod.MANIFEST_NAME), doc)
    with open(p["record_img"], "wb") as fh:
        fh.truncate(RECORD_IMAGE_BYTES)
    _run(mkfs_argv(p["record_dir"], p["record_img"]), log, run=run)

    _run(
        [
            "xorriso",
            "-osirrox",
            "on",
            "-indev",
            p["iso"],
            "-extract",
            "/arch/boot/x86_64/vmlinuz-linux",
            p["kernel"],
            "-extract",
            "/arch/boot/x86_64/initramfs-linux.img",
            p["initrd"],
            "-extract",
            "/arch/pkglist.x86_64.txt",
            p["pkglist"],
        ],
        log,
        run=run,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    etat["archinstall_version"] = pkglist_version(
        Path(p["pkglist"]).read_text("utf-8")
    )
    _run(
        [
            "qemu-img",
            "create",
            "-q",
            "-f",
            "qcow2",
            p["target"],
            f"{plan['disk_gib']}G",
        ],
        log,
        run=run,
    )
    if plan["ovmf"]:
        shutil.copyfile(OVMF_VARS, p["ovmf_vars"])

    journal = open(p["proxy_log"], "ab")
    mandataire = subprocess.Popen(
        proxy_record_argv(p["proxy"], p["work"], plan["ports"], plan["lang"]),
        stdout=journal,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    vm = None
    try:
        if not _wait_tcp(plan["ports"][0]) or not _wait_tcp(plan["ports"][1]):
            raise BuildError("record proxy is not listening")
        reponses = answers_document(plan["profile"], secrets.token_urlsafe(18))
        argv = qemu_argv(
            {**p, "iso": p["iso"]},
            plan["memory"],
            plan["cpus"],
            kernel_cmdline(plan["iso_uuid"], reponses),
            plan["ovmf"],
        )
        _say(log, "reference install: qemu-system-x86_64 (answers hidden)")
        t1 = time.monotonic()
        vm = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=open(os.path.join(p["work"], "qemu.log"), "ab"),
        )
        code = _wait_marker(p["serial"], vm, plan["timeout_min"] * 60, log)
        etat["vm_exit"] = code
        try:
            vm.wait(timeout=180)
        except subprocess.TimeoutExpired:
            vm.kill()
            vm.wait()
        etat["times"]["install_s"] = round(time.monotonic() - t1)
        _write_json(p["state"], etat)
        if code != 0:
            raise BuildError(f"reference install: exit code {code}")
        t2 = time.monotonic()
        etat["hardware"] = fetch_hardware(plan, log, run=run)
        etat["times"]["hardware_s"] = round(time.monotonic() - t2)
    finally:
        if vm is not None and vm.poll() is None:
            vm.kill()
            vm.wait()
        mandataire.terminate()
        try:
            mandataire.wait(timeout=30)
        except subprocess.TimeoutExpired:
            mandataire.kill()
            mandataire.wait()
        journal.close()
    _write_json(p["state"], etat)
    return etat


def _recorded(store):
    """{(dépôt, arch): {"files": {fichier: (date, corps)}, "dbs":
    [(date, corps, méta)]}} des fichiers pacman du magasin."""
    out = {}
    for doc, corps in iter_store(store):
        cible = pacman_target(doc.get("url"))
        if not cible or not is_body(doc, corps):
            continue
        depot, arch, nom = cible
        case = out.setdefault((depot, arch), {"files": {}, "dbs": []})
        date = str(doc.get("stored_at") or "")
        if nom == f"{depot}.db":
            case["dbs"].append((date, str(corps), doc))
        elif nom.endswith(".sig") or pkg_name(nom):
            ancien = case["files"].get(nom)
            if ancien is None or date > ancien[0]:
                case["files"][nom] = (date, str(corps))
    return out


def fetch_hardware(plan, log, run=subprocess.run):
    """Tire au travers du mandataire, depuis l'hôte, la fermeture de
    hardware_packages() que le magasin n'a pas encore : « pacman -Sp » sur
    les dernières bases enregistrées en donne les URL, curl les demande.
    Rend {"requested", "fetched", "unknown"}."""
    p = plan["paths"]
    enregistres = _recorded(p["store"])
    with tempfile.TemporaryDirectory(prefix="closure-", dir=p["work"]) as tmp:
        sync = os.path.join(tmp, "db", "sync")
        os.makedirs(sync)
        os.makedirs(os.path.join(tmp, "db", "local"))
        os.makedirs(os.path.join(tmp, "cache"))
        for depot in ("core", "extra"):
            case = enregistres.get((depot, offline_mod.ARCH)) or {}
            if not case.get("dbs"):
                raise BuildError(f"no recorded {depot}.db")
            _date, corps, _doc = max(case["dbs"], key=lambda c: c[0])
            shutil.copyfile(corps, os.path.join(sync, f"{depot}.db"))
        conf = os.path.join(tmp, "pacman.conf")
        Path(conf).write_text(pacman_conf(), "utf-8")
        noms = hardware_packages()
        inconnus = []
        for _essai in range(10):
            res = run(
                [
                    "pacman",
                    "-Sp",
                    "--config",
                    conf,
                    "--dbpath",
                    os.path.join(tmp, "db"),
                    "--cachedir",
                    os.path.join(tmp, "cache"),
                    "--logfile",
                    "/dev/null",
                    "--noconfirm",
                    *noms,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                break
            absents = not_found(res.stderr)
            if not absents:
                raise BuildError(f"pacman -Sp: {res.stderr.strip()[:300]}")
            inconnus += absents
            noms = [n for n in noms if n not in absents]
        else:
            raise BuildError("pacman -Sp: too many unknown names")
    deja = set()
    for case in enregistres.values():
        deja.update(case["files"])
    urls = []
    for ligne in (res.stdout or "").splitlines():
        ligne = ligne.strip()
        if not ligne.startswith("https://"):
            continue
        nom = ligne.rsplit("/", 1)[-1]
        if nom not in deja:
            urls.append(ligne)
        if nom + ".sig" not in deja:
            urls.append(ligne + ".sig")
    if urls:
        conf_curl = os.path.join(p["work"], "hardware.curlrc")
        Path(conf_curl).write_text(
            curl_config(
                urls, plan["ports"][1], os.path.join(p["ca"], "ca.crt")
            ),
            "utf-8",
        )
        _run(["curl", "-K", conf_curl], log, run=run)
    _say(
        log,
        f"hardware packages: {len(urls)} file(s) fetched, "
        f"unknown: {', '.join(inconnus) or '-'}",
    )
    return {
        "requested": len(hardware_packages()),
        "fetched": len(urls),
        "unknown": inconnus,
    }


def assemble_repo(store, repo_dir, log, run=subprocess.run):
    """Le dépôt pacman du paquet sous `repo_dir`, tiré du magasin : voir
    la docstring du module pour le choix de la base. Rend le relevé par
    dépôt, avec les paquets sans signature (une erreur)."""
    releve = {}
    for (depot, arch), case in sorted(_recorded(store).items()):
        if depot not in ("core", "extra", "multilib"):
            continue
        dossier = os.path.join(repo_dir, depot, "os", arch)
        os.makedirs(dossier, exist_ok=True)
        fichiers = {nom: v[1] for nom, v in case["files"].items()}
        candidats = [
            (date, corps, offline_mod.read_db(corps))
            for date, corps, _doc in case["dbs"]
        ]
        choisi, manques = choose_db(candidats, set(fichiers))
        info = {"packages": 0, "bytes": 0}
        if choisi and not manques:
            index = next(c[2] for c in candidats if c[1] == choisi)
            gardes, sans = repo_files(index, set(fichiers))
            _link(choisi, os.path.join(dossier, f"{depot}.db"))
            doc = next(d for _dt, c, d in case["dbs"] if c == choisi)
            info.update(db="official", snapshot=snapshot_date(doc))
        else:
            dates = {nom: v[0] for nom, v in case["files"].items()}
            gardes = sorted(newest_per_package(dates))
            sans = []
            info.update(db="repo-add", db_gaps=manques)
        for nom in gardes:
            _link(fichiers[nom], os.path.join(dossier, nom))
            info["bytes"] += os.path.getsize(fichiers[nom])
            if not nom.endswith(".sig"):
                info["packages"] += 1
        if info["db"] == "repo-add":
            paquets = [
                os.path.join(dossier, n)
                for n in gardes
                if not n.endswith(".sig")
            ]
            _run(
                [
                    "repo-add",
                    "-q",
                    os.path.join(dossier, f"{depot}.db.tar.gz"),
                    *paquets,
                ],
                log,
                run=run,
            )
            index = offline_mod.read_db(os.path.join(dossier, f"{depot}.db"))
            sans = [
                n
                for n, f in index["packages"].items()
                if n not in index["signed"]
                and not os.path.exists(os.path.join(dossier, f + ".sig"))
            ]
            info["snapshot"] = datetime.date.today().isoformat()
        info["unsigned"] = sans
        info["dropped"] = len(fichiers) - len(gardes)
        releve[depot] = info
    return releve


def prune_store(store, dest, access, log):
    """Le magasin du paquet sous `dest` : chaque objet du magasin
    enregistré sauf les fichiers pacman (servis par le dépôt), et les
    seuls miroirs git que le journal montre servis. Liens physiques."""
    gardes = pacman = 0
    for doc, corps in iter_store(store):
        if pacman_target(doc.get("url")):
            pacman += 1
            continue
        meta = corps.with_suffix(".meta")
        rel = os.path.relpath(meta, store)
        _link(str(meta), os.path.join(dest, rel))
        if corps.exists():
            _link(
                str(corps), os.path.join(dest, os.path.relpath(corps, store))
            )
        gardes += 1
    servis = git_repos_used(read_access_log(access))
    racine_git = os.path.join(store, "git")
    miroirs, ecartes = [], []
    if os.path.isdir(racine_git):
        for dossier, sous, _noms in os.walk(racine_git):
            if dossier.endswith(".git"):
                sous[:] = []
                rel = os.path.relpath(dossier, racine_git)
                if rel in servis:
                    _link_tree(dossier, os.path.join(dest, "git", rel))
                    miroirs.append(rel)
                else:
                    ecartes.append(rel)
    _say(
        log,
        f"store: {gardes} object(s) kept, {pacman} pacman file(s) "
        f"moved to the repo, {len(miroirs)} git mirror(s) kept, "
        f"{len(ecartes)} unused mirror(s) left out",
    )
    return {
        "objects": gardes,
        "pacman": pacman,
        "git_mirrors": len(miroirs),
        "git_unused": ecartes,
    }


def erplibre_commit(store, source, run=subprocess.run):
    """Le commit de la branche ERPLibre : celui du miroir enregistré (ce
    que le paquet servira), sinon celui de l'amont (git ls-remote)."""
    rel = mirror_rel(source["git_url"])
    ref = f"refs/heads/{source['branch']}"
    miroir = os.path.join(store, "git", rel) if rel else None
    if miroir and os.path.isdir(miroir):
        res = run(
            ["git", "--git-dir", miroir, "rev-parse", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    res = run(
        ["git", "ls-remote", source["git_url"], ref],
        capture_output=True,
        text=True,
        check=False,
    )
    return (res.stdout or "").split("\t", 1)[0].strip()


def assemble(paths, log=_print, run=subprocess.run):
    """Le paquet sous paths["payload"] depuis le travail enregistré, puis
    l'image ext4 et son empreinte. Rend le relevé (aussi dans
    report.json)."""
    etat = json.loads(Path(paths["state"]).read_text("utf-8"))
    plan = etat["plan"]
    payload = paths["payload"]
    if os.path.exists(payload):
        shutil.rmtree(payload)
    os.makedirs(payload)
    t0 = time.monotonic()
    depot = assemble_repo(
        paths["store"], os.path.join(payload, REPO_REL), log, run
    )
    magasin = prune_store(
        paths["store"], os.path.join(payload, STORE_REL), paths["access"], log
    )
    os.makedirs(os.path.join(payload, STORE_REL), exist_ok=True)
    _link(paths["proxy"], os.path.join(payload, PROXY_REL))
    os.makedirs(os.path.join(payload, CA_DIR_REL), exist_ok=True)
    for nom in ("ca.crt", "ca.key"):
        shutil.copy2(
            os.path.join(paths["ca"], nom),
            os.path.join(payload, CA_DIR_REL, nom),
        )
    source = dict(plan["source"])
    source["commit"] = erplibre_commit(paths["store"], source, run)
    version = run(
        [paths["proxy"], "--version"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()[-1:]
    snapshot = (depot.get("core") or {}).get("snapshot") or ""
    doc = manifest_document(
        payload,
        plan["profile"],
        source,
        etat.get("archinstall_version") or "",
        snapshot,
        version[0] if version else "",
        datetime.datetime.strptime(plan["created"], "%Y-%m-%dT%H:%M:%SZ"),
    )
    doc["reference"] = {
        "iso": os.path.basename(plan["paths"]["iso"]),
        # L'UUID ISO 9660 (date de volume) de l'ISO enregistrée : le TODO
        # le compare à celui de l'ISO qui recevra le paquet, deux ISO d'un
        # même jour portant le même nom.
        "iso_uuid": plan.get("iso_uuid"),
        "install_seconds": etat["times"].get("install_s"),
        "repo": depot,
        "store": {k: v for k, v in magasin.items() if k != "git_unused"},
        "hardware": etat.get("hardware"),
    }
    _write_json(os.path.join(payload, offline_mod.MANIFEST_NAME), doc)
    manques = offline_mod.check_packages(
        gate_packages(plan["profile"]), payload, doc
    )
    sans_sig = {d: i["unsigned"] for d, i in depot.items() if i["unsigned"]}
    t1 = time.monotonic()
    image = plan["image"]
    if make_image(payload, image, run=run) != 0:
        raise BuildError("mkfs.ext4 failed")
    empreinte = sha256_file(image)
    Path(image + ".sha256").write_text(
        f"{empreinte}  {os.path.basename(image)}\n", "utf-8"
    )
    octets, fichiers = tree_size(payload)
    releve = {
        "profile": plan["profile"],
        "payload": payload,
        "image": image,
        "image_bytes": os.path.getsize(image),
        "image_sha256": empreinte,
        "payload_bytes": octets,
        "payload_files": fichiers,
        "parts": {k: v.get("size") for k, v in doc["parts"].items()},
        "repo": depot,
        "store": magasin,
        "missing_for_gate": manques,
        "unsigned": sans_sig,
        "times": dict(
            etat["times"],
            assemble_s=round(t1 - t0),
            image_s=round(time.monotonic() - t1),
        ),
        "ok": not manques and not sans_sig,
    }
    _write_json(paths["report"], releve)
    return releve


def _parser():
    parser = argparse.ArgumentParser(
        description="ERPLibre offline payload: reference install, static "
        "proxy, manifest, ext4 image."
    )
    sous = parser.add_subparsers(dest="action", required=True)
    f = sous.add_parser(
        "build", help="reference install in QEMU, then payload and image"
    )
    f.add_argument(
        "--profile",
        required=True,
        help="ERPLibre profile (gnome, home, odoo18, dev)",
    )
    f.add_argument(
        "--iso", help=f"ERPLibre ISO (default: newest in {ISO_DIR})"
    )
    f.add_argument(
        "--out",
        default=str(OUT_ROOT),
        help=f"output root (default {OUT_ROOT})",
    )
    f.add_argument(
        "--git-url",
        default=None,
        help="ERPLibre repository cloned by the stage",
    )
    f.add_argument("--branch", default=None, help="ERPLibre branch")
    f.add_argument(
        "--seed-git-mirrors",
        metavar="DIR",
        help="copy the profile's bare git mirrors from this "
        f"directory first (e.g. {SEED_DEFAULT}); read only",
    )
    f.add_argument(
        "--memory", type=int, default=DEFAULT_MEMORY_MIB, help="VM memory, MiB"
    )
    f.add_argument("--cpus", type=int, default=DEFAULT_CPUS)
    f.add_argument(
        "--disk-gib",
        type=int,
        default=None,
        help="target disk size (sparse qcow2)",
    )
    f.add_argument("--timeout-min", type=int, default=DEFAULT_TIMEOUT_MIN)
    f.add_argument(
        "--keep-target",
        action="store_true",
        help="keep the target qcow2 after the build",
    )
    f.add_argument("--lang", default="fr")
    f.add_argument(
        "--dry-run", action="store_true", help="print the plan, run nothing"
    )
    a = sous.add_parser(
        "assemble", help="payload and image again from a build directory"
    )
    a.add_argument("root", help="the build directory (contains work/)")
    b = sous.add_parser("build-proxy", help="static proxy binary")
    b.add_argument("out")
    m = sous.add_parser("manifest", help="write ROOT/manifest.json")
    m.add_argument("root")
    m.add_argument("--profile", required=True)
    m.add_argument("--git-url", required=True)
    m.add_argument("--branch", required=True)
    m.add_argument("--commit", required=True)
    m.add_argument("--archinstall", required=True)
    m.add_argument("--snapshot", required=True, help="Arch snapshot date")
    m.add_argument("--proxy-version", default="")
    i = sous.add_parser("image", help="ext4 image of ROOT")
    i.add_argument("root")
    i.add_argument("image")
    return parser


def _build_iso_module():
    spec = importlib.util.spec_from_file_location(
        "build_iso_defaults", HERE / "build_iso.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def profile_command(profile, mod=None):
    """La commande du profil ERPLibre `profile` telle que build_iso.py
    l'écrit dans profiles.json de l'ISO construite depuis ce dépôt.
    LookupError pour un profil inconnu."""
    mod = mod or _build_iso_module()
    profils = mod.iso_profiles(
        mod.qemu_profiles_by_lang(), mod._qemu_mixin()._QEMU_QEMU_PKGS
    )
    for profil in profils:
        if profil["key"] == profile:
            return profil["command"]
    raise LookupError(f"unknown ERPLibre profile {profile!r}")


def _source_defaults(args):
    """--git-url et --branch : ceux de la construction de l'ISO par
    défaut (build_iso.DEFAULT_GIT_URL, DEFAULT_BRANCH)."""
    mod = _build_iso_module()
    return (
        args.git_url or mod.DEFAULT_GIT_URL,
        args.branch or mod.DEFAULT_BRANCH,
    )


def _build(args):
    iso = Path(args.iso) if args.iso else newest_iso()
    if not iso or not iso.is_file():
        print("no ISO: pass --iso", file=sys.stderr)
        return 2
    if args.seed_git_mirrors and not os.path.isdir(args.seed_git_mirrors):
        print(
            f"--seed-git-mirrors: not a directory: {args.seed_git_mirrors}",
            file=sys.stderr,
        )
        return 2
    git_url, branch = _source_defaults(args)
    try:
        commande = profile_command(args.profile)
    except (LookupError, ImportError) as exc:
        print(f"profile command unreadable: {exc}", file=sys.stderr)
        return 2
    uuid = iso_uuid(iso)
    if not uuid:
        print(f"no ISO 9660 UUID in {iso}", file=sys.stderr)
        return 2
    now = datetime.datetime.now(datetime.timezone.utc)
    plan = build_plan(
        {
            "profile": args.profile,
            "iso": iso.resolve(),
            "out": args.out,
            "git_url": git_url,
            "branch": branch,
            "seed": args.seed_git_mirrors,
            "memory": args.memory,
            "cpus": args.cpus,
            "disk_gib": args.disk_gib,
            "timeout_min": args.timeout_min,
            "lang": args.lang,
            "command_sha256": offline_mod.command_sha256(commande),
        },
        now,
        free_ports(),
        uuid,
    )
    for ligne in describe_plan(plan):
        print(ligne, flush=True)
    if args.dry_run:
        print("dry run: nothing executed")
        return 0
    if args.seed_git_mirrors is None and os.path.isdir(SEED_DEFAULT):
        print(
            f"hint: --seed-git-mirrors {SEED_DEFAULT} would copy "
            "mirrors instead of cloning them"
        )
    t0 = time.monotonic()
    try:
        record(plan)
        releve = assemble(plan["paths"])
    except BuildError as exc:
        print(f"offline payload: FAILED: {exc}", file=sys.stderr)
        print(f"work directory kept: {plan['paths']['work']}", file=sys.stderr)
        return 1
    if not args.keep_target:
        try:
            os.unlink(plan["paths"]["target"])
        except OSError:
            pass
    releve["times"]["total_s"] = round(time.monotonic() - t0)
    _write_json(plan["paths"]["report"], releve)
    print(json.dumps(releve, indent=2, ensure_ascii=False))
    return 0 if releve["ok"] else 1


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.action == "build":
        return _build(args)
    if args.action == "assemble":
        try:
            releve = assemble(work_paths(args.root))
        except BuildError as exc:
            print(f"offline payload: FAILED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(releve, indent=2, ensure_ascii=False))
        return 0 if releve["ok"] else 1
    if args.action == "build-proxy":
        return build_proxy(args.out)
    if args.action == "manifest":
        doc = manifest_document(
            args.root,
            args.profile,
            {
                "git_url": args.git_url,
                "branch": args.branch,
                "commit": args.commit,
            },
            args.archinstall,
            args.snapshot,
            args.proxy_version,
        )
        chemin = Path(args.root) / offline_mod.MANIFEST_NAME
        chemin.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n", "utf-8"
        )
        print(chemin)
        return 0
    return make_image(args.root, args.image)


if __name__ == "__main__":
    sys.exit(main())
