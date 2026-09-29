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


def commande(args, timeout=5):
    """La sortie de `args`, ou None si la commande manque ou échoue."""
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
    return res.stdout if res.returncode == 0 else None


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
        # « none » sur une machine physique : c'est une réponse, pas un manque.
        virtualisation = (commande(["systemd-detect-virt"]) or "").strip()
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


def partitions(racine=".", chemin_mounts="/proc/mounts"):
    """Les partitions de données, avec leur espace, celle de `racine`
    marquée. Un point de montage vu deux fois (bind) ne compte qu'une."""
    racine = os.path.realpath(racine)
    vues = {}
    for ligne in (lire(chemin_mounts) or "").splitlines():
        champs = ligne.split()
        if len(champs) < 3 or champs[2] not in FS_DISQUES:
            continue
        # /proc/mounts échappe l'espace en \040.
        point = champs[1].replace("\\040", " ")
        if point in vues:
            continue
        try:
            usage = shutil.disk_usage(point)
        except OSError:
            continue
        vues[point] = {
            "device": champs[0],
            "mountpoint": point,
            "fstype": champs[2],
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "repo": False,
        }
    # La partition du dépôt : le plus long point de montage qui le contient.
    contenants = [
        p
        for p in vues
        if racine == p or racine.startswith(p.rstrip("/") + "/")
    ]
    if contenants:
        vues[max(contenants, key=len)]["repo"] = True
    return sorted(vues.values(), key=lambda p: p["mountpoint"])


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
