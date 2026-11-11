#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les moniteurs de mémoire par processus (top, htop, btop, glances) : s'ils
sont installés, comment les lancer triés par mémoire, et comment installer
ceux qui manquent sur les systèmes que déploie « todo.py qemu ».

Familles couvertes, par leur gestionnaire de paquets : apt (Debian, Ubuntu,
Proxmox), dnf (Fedora, AlmaLinux, Rocky), pacman (Arch), zypper (openSUSE).
AlmaLinux et Rocky ne portent htop, btop et glances que dans EPEL :
epel-release s'installe d'abord. NixOS n'installe rien de façon impérative :
l'outil s'y lance dans un « nix-shell -p » éphémère.

Ce module ne lance rien : il rend des listes d'arguments, que le menu
montre avant de les exécuter.
"""

import shlex
import shutil

from script.todo.system_diagnostic import os_release

# (nom, binaire, arguments qui trient par mémoire, touche qui le fait dans
# l'outil). btop et glances n'ont pas d'option de tri sûre d'une version à
# l'autre : ils s'ouvrent tels quels et la touche est rappelée.
OUTILS = (
    ("top", "top", ["-o", "%MEM"], "M"),
    ("htop", "htop", ["--sort-key", "PERCENT_MEM"], "M"),
    ("btop", "btop", [], "← →"),
    ("glances", "glances", [], "m"),
)

# Nom du paquet par gestionnaire. top vient de procps, présent sur presque
# tout système, mais il manque dans une image minimale.
PAQUETS = {
    "top": {
        "apt": "procps",
        "dnf": "procps-ng",
        "pacman": "procps-ng",
        "zypper": "procps",
        "nix": "procps",
    },
    "htop": dict.fromkeys(("apt", "dnf", "pacman", "zypper", "nix"), "htop"),
    "btop": dict.fromkeys(("apt", "dnf", "pacman", "zypper", "nix"), "btop"),
    "glances": dict.fromkeys(
        ("apt", "dnf", "pacman", "zypper", "nix"), "glances"
    ),
}

# Gestionnaire -> (binaire à détecter, commande d'installation). L'ordre est
# celui de la détection : le premier binaire présent gagne.
GESTIONNAIRES = (
    ("apt", "apt-get", ["sudo", "apt-get", "install", "-y"]),
    ("dnf", "dnf", ["sudo", "dnf", "install", "-y"]),
    ("pacman", "pacman", ["sudo", "pacman", "-S", "--needed", "--noconfirm"]),
    ("zypper", "zypper", ["sudo", "zypper", "--non-interactive", "install"]),
)

# ID ou ID_LIKE de /etc/os-release -> gestionnaire de la distribution. Un
# hôte peut porter le binaire d'un AUTRE gestionnaire — Arch empaquète apt,
# dnf et zypper pour bâtir des chroots —, qui n'y a aucun dépôt : la
# distribution décide, la présence d'un binaire ne sert que de repli.
PAR_DISTRIBUTION = {
    "debian": "apt",
    "ubuntu": "apt",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "arch": "pacman",
    "suse": "zypper",
    "opensuse": "zypper",
}

# Ce qui précède l'installation : l'index d'apt vieillit, et un paquet
# retiré du miroir y répond 404. dnf et zypper rafraîchissent d'eux-mêmes ;
# pacman ne se rafraîchit que par une mise à jour complète (-Syu), trop
# lourde pour installer un moniteur : son échec le conseille.
AVANT = {"apt": [["sudo", "apt-get", "update"]]}

# Les ID de /etc/os-release dont dnf ne trouve ces outils que dans EPEL.
AVEC_EPEL = {"almalinux", "rocky", "rhel", "centos", "ol"}
EPEL_SEULEMENT = {"htop", "btop", "glances"}


def systeme(chemin="/etc/os-release"):
    """(ID, {ID et ID_LIKE}) de /etc/os-release, en minuscules."""
    valeurs = os_release(chemin)
    ident = valeurs.get("ID", "").lower()
    famille = {ident} | set(valeurs.get("ID_LIKE", "").lower().split())
    return ident, famille - {""}


def gestionnaire(chemin="/etc/os-release"):
    """« nix » sur NixOS ; sinon le gestionnaire de la distribution d'après
    ID puis ID_LIKE, s'il est installé ; à défaut le premier de
    GESTIONNAIRES présent ; None si aucun."""
    ident, famille = systeme(chemin)
    if ident == "nixos":
        return "nix"
    binaires = {cle: binaire for cle, binaire, _ in GESTIONNAIRES}
    for nom in [ident] + sorted(famille - {ident}):
        cle = PAR_DISTRIBUTION.get(nom)
        if cle and shutil.which(binaires[cle]):
            return cle
    for cle, binaire, _ in GESTIONNAIRES:
        if shutil.which(binaire):
            return cle
    return None


def etat():
    """[{nom, chemin, args, touche}] pour chaque outil ; chemin vaut None
    quand l'outil n'est pas dans le PATH."""
    return [
        {
            "nom": nom,
            "chemin": shutil.which(binaire),
            "args": args,
            "touche": touche,
        }
        for nom, binaire, args, touche in OUTILS
    ]


def plan_installation(nom, chemin="/etc/os-release"):
    """Les commandes qui installent `nom`, dans l'ordre, ou [] si le
    système n'est pas reconnu. Sur NixOS, rend [] aussi : voir
    commande_nix()."""
    cle = gestionnaire(chemin)
    if cle in (None, "nix"):
        return []
    paquet = PAQUETS[nom].get(cle)
    if not paquet:
        return []
    install = dict((c, cmd) for c, _, cmd in GESTIONNAIRES)[cle]
    plan = [list(c) for c in AVANT.get(cle, [])]
    _, famille = systeme(chemin)
    if cle == "dnf" and nom in EPEL_SEULEMENT and famille & AVEC_EPEL:
        plan.append(install + ["epel-release"])
    plan.append(install + [paquet])
    return plan


def commande_nix(nom):
    """La commande qui lance `nom` sans l'installer, sur NixOS."""
    args = dict((n, a) for n, _, a, _ in OUTILS)[nom]
    return [
        "nix-shell",
        "-p",
        PAQUETS[nom]["nix"],
        "--run",
        shlex.join([nom] + args),
    ]
