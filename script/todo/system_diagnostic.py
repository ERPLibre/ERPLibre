#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les faits d'un poste : identité, matériel, disques, charge, ERPLibre.

Lecture seule, jamais sudo : tout vient de /proc, de /etc/os-release et de
commandes qu'un utilisateur lance sans privilège (hostnamectl, lscpu,
lspci, lsblk). Une commande absente ou muette rend None, et la valeur
correspondante manque : l'appelant dit « indisponible » au lieu d'afficher
une ligne vide ou de lever.

Ce module ne rend que des FAITS — des nombres, des chaînes lues —, jamais
une phrase : la mise en forme et la langue appartiennent au menu.

Les commandes sont lancées sous LC_ALL=C : lscpu et hostnamectl traduisent
leurs libellés, et ce sont ces libellés qu'on lit.
"""

import json
import os
import platform
import re
import shutil
import subprocess

# Les systèmes de fichiers qui portent des données ; les autres entrées de
# /proc/mounts (proc, tmpfs, cgroup, overlay…) ne sont pas des disques.
FS_DISQUES = {
    "ext2",
    "ext3",
    "ext4",
    "xfs",
    "btrfs",
    "zfs",
    "f2fs",
    "vfat",
    "exfat",
    "ntfs",
    "ntfs3",
    "fuseblk",
    "reiserfs",
    "jfs",
}


def commande(args, timeout=5, codes_ok=(0,)):
    """La sortie de `args`, ou None si la commande manque, ou sort sur un
    code hors de `codes_ok`."""
    if shutil.which(args[0]) is None:
        return None
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(os.environ, LC_ALL="C", LANG="C"),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode in codes_ok else None


def lire(chemin):
    """Le contenu d'un fichier texte, ou None."""
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def os_release(chemin="/etc/os-release"):
    """{CLÉ: valeur} de /etc/os-release."""
    valeurs = {}
    for ligne in (lire(chemin) or "").splitlines():
        cle, egal, valeur = ligne.partition("=")
        if egal:
            valeurs[cle.strip()] = valeur.strip().strip('"')
    return valeurs


def identite():
    """Nom, système, noyau, architecture, virtualisation, matériel.

    hostnamectl en JSON d'abord ; à défaut, /etc/os-release et uname, qui
    ne disent rien du matériel."""
    brut = commande(["hostnamectl", "--json=short"])
    donnees = {}
    if brut:
        try:
            donnees = json.loads(brut)
        except ValueError:
            donnees = {}
    osr = os_release()
    # Le fabricant et le modèle se lisent tels quels dans /sys, sans
    # privilège ; hostnamectl remplace leurs parenthèses par des soulignés.
    dmi = "/sys/class/dmi/id"
    fabricant = (lire(f"{dmi}/sys_vendor") or "").strip()
    modele = (lire(f"{dmi}/product_name") or "").strip()
    virtualisation = donnees.get("Virtualization")
    if not virtualisation:
        # « none » sur une machine physique : c'est une réponse, pas un
        # manque, que systemd-detect-virt donne pourtant avec le code 1.
        virtualisation = (
            commande(["systemd-detect-virt"], codes_ok=(0, 1)) or ""
        ).strip()
    return {
        "hostname": donnees.get("StaticHostname")
        or donnees.get("Hostname")
        or platform.node()
        or None,
        "os": donnees.get("OperatingSystemPrettyName")
        or osr.get("PRETTY_NAME"),
        "kernel": " ".join(
            x
            for x in (
                donnees.get("KernelName") or platform.system(),
                donnees.get("KernelRelease") or platform.release(),
            )
            if x
        )
        or None,
        "architecture": platform.machine() or None,
        "chassis": donnees.get("Chassis"),
        "virtualization": virtualisation or None,
        "vendor": fabricant or donnees.get("HardwareVendor"),
        "model": modele or donnees.get("HardwareModel"),
    }


def processeur():
    """Modèle, cœurs logiques et physiques (ou None pour ce qu'on ignore)."""
    champs = {}
    brut = commande(["lscpu", "--json"])
    if brut:
        try:
            for entree in json.loads(brut).get("lscpu", []):
                champs[entree["field"].rstrip(":").strip()] = entree["data"]
        except (ValueError, KeyError, AttributeError):
            champs = {}
    modele = champs.get("Model name")
    if not modele:
        for ligne in (lire("/proc/cpuinfo") or "").splitlines():
            if ligne.startswith("model name"):
                modele = ligne.partition(":")[2].strip()
                break
    physiques = None
    try:
        physiques = int(champs["Core(s) per socket"]) * int(
            champs.get("Socket(s)", 1)
        )
    except (KeyError, ValueError):
        pass
    return {
        "model": modele or None,
        "logical": os.cpu_count(),
        "physical": physiques,
    }


def memoire(chemin="/proc/meminfo"):
    """Octets : total, disponible, swap total, swap libre."""
    kio = {}
    for ligne in (lire(chemin) or "").splitlines():
        cle, _, reste = ligne.partition(":")
        morceaux = reste.split()
        if morceaux and morceaux[0].isdigit():
            kio[cle] = int(morceaux[0]) * 1024
    return {
        "total": kio.get("MemTotal"),
        "available": kio.get("MemAvailable"),
        "swap_total": kio.get("SwapTotal"),
        "swap_free": kio.get("SwapFree"),
    }


def cartes_graphiques():
    """Les lignes lspci des contrôleurs d'affichage ; None sans lspci."""
    brut = commande(["lspci"])
    if brut is None:
        return None
    return [
        ligne.split(": ", 1)[-1]
        for ligne in brut.splitlines()
        if any(
            m in ligne for m in ("VGA", "3D controller", "Display controller")
        )
    ]


def desechapper(texte):
    """« /mnt/a\\040b » -> « /mnt/a b » : /proc/mounts et mountinfo écrivent
    en octal l'espace, la tabulation, le saut de ligne et la barre oblique
    inverse d'un point de montage."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), texte)


def partitions(racine=".", chemin_mounts="/proc/mounts"):
    """Les systèmes de fichiers de données, un par appareil, avec leur
    espace, celui de `racine` marqué.

    Un même appareil monté en plusieurs points — sous-volumes btrfs, bind
    mounts — est UNE ligne, ses autres points dans « autres » : additionner
    les lignes ne compte alors chaque disque qu'une fois. Un point monté
    deux fois garde la dernière ligne, celle qui recouvre l'autre. Un
    fichier monté (/etc/hosts dans un conteneur) n'est pas un disque.

    Le dépôt est cherché parmi TOUS les montages : sur NFS, virtiofs ou
    l'overlay d'un conteneur, absents de FS_DISQUES, son système de
    fichiers est ajouté plutôt que d'en marquer un parent."""
    racine = os.path.realpath(racine)
    montes = {}
    for ligne in (lire(chemin_mounts) or "").splitlines():
        champs = ligne.split()
        if len(champs) < 3:
            continue
        montes[desechapper(champs[1])] = (champs[0], champs[2])
    contenants = [
        p
        for p in montes
        if racine == p or racine.startswith(p.rstrip("/") + "/")
    ]
    point_depot = max(contenants, key=len) if contenants else None
    par_appareil = {}
    for point in sorted(montes):
        appareil, fstype = montes[point]
        if fstype not in FS_DISQUES and point != point_depot:
            continue
        if not os.path.isdir(point):
            continue
        try:
            usage = shutil.disk_usage(point)
        except OSError:
            continue
        entree = par_appareil.get(appareil)
        if entree is None:
            entree = par_appareil[appareil] = {
                "device": appareil,
                "mountpoint": point,
                "others": [],
                "fstype": fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "repo": False,
            }
        else:
            entree["others"].append(point)
        if point == point_depot:
            entree["repo"] = True
    return sorted(par_appareil.values(), key=lambda p: p["mountpoint"])


def charge():
    """Charge sur 1, 5 et 15 minutes, et secondes depuis le démarrage."""
    moyennes = (lire("/proc/loadavg") or "").split()[:3]
    uptime = (lire("/proc/uptime") or "").split()[:1]
    try:
        moyennes = [float(x) for x in moyennes]
    except ValueError:
        moyennes = []
    try:
        secondes = float(uptime[0]) if uptime else None
    except ValueError:
        secondes = None
    return {"load": moyennes or None, "uptime": secondes}


def erplibre(racine="."):
    """Versions déclarées par le checkout, et les venvs présents."""

    def version(nom):
        texte = lire(os.path.join(racine, nom))
        return texte.strip() if texte else None

    try:
        venvs = sorted(
            n
            for n in os.listdir(racine)
            if n.startswith(".venv.")
            and os.path.isdir(os.path.join(racine, n))
        )
    except OSError:
        venvs = []
    actif = version(".erplibre-version")
    return {
        "erplibre": version(".erplibre-semver-version"),
        "odoo": version(".odoo-version"),
        "python": version(".python-odoo-version"),
        "active_venv": f".venv.{actif}" if actif else None,
        "venvs": venvs,
    }


def collecter(racine="."):
    """Tout le diagnostic, section par section."""
    return {
        "identity": identite(),
        "cpu": processeur(),
        "memory": memoire(),
        "gpu": cartes_graphiques(),
        "partitions": partitions(racine),
        "load": charge(),
        "erplibre": erplibre(racine),
    }
