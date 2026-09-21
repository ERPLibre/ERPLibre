#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que la machine EST, et ce qu'elle SAIT FAIRE.

Le dépôt déduisait les deux à plusieurs endroits, qui divergeaient déjà : le
jeton d'architecture existait en deux exemplaires identiques, et rien ne
répondait à « qu'est-ce que cet hôte peut déployer ». Un seul module le dit
désormais, et les menus s'y branchent au lieu de le redéduire.

Ce module fait la DÉTECTION et les CAPACITÉS, rien d'autre. Il ne dispatche
pas de verbes par système : installer un paquet, lire un secret ou poser une
règle de pare-feu ont déjà leur maison dans ce dépôt, et une façade qui les
réunirait n'ajouterait qu'une indirection.

Deux invariants :

1. Aucune sonde ne lance de sous-processus et aucune ne lève. Une capacité
   se mesure en regardant le PATH et le système de fichiers ; lancer un
   binaire pour savoir s'il existe coûte des secondes sur un menu, et une
   sonde qui lève transforme un rapport en trace.
2. « /etc/os-release » se LIT, jamais ne s'exécute. C'est un fichier de
   configuration, pas un script, et le sourcer exécuterait ce qu'il porte.
"""

from __future__ import annotations

import os
import re
import shutil

from script.todo.devstack_report import DS_OK, DS_SKIP, Capability, diag
from script.todo.todo_i18n import t

# Les jetons d'hôte. « unknown » n'est pas un échec : c'est un système que ce
# dépôt ne sait pas encore nommer, et les menus qui en dépendent s'y retirent.
MACOS = "macos"
DEBIAN = "debian"
ARCH = "arch"
PROXMOX = "proxmox"
UNKNOWN = "unknown"
HOSTS = (MACOS, DEBIAN, ARCH, PROXMOX, UNKNOWN)

# Coutures de test. Résolues à CHAQUE appel : figées à l'import, une valeur
# posée par un test après le chargement ne serait jamais vue.
HOST_OS_VAR = "EL_HOST_OS"
OS_RELEASE_VAR = "EL_OS_RELEASE"
OS_RELEASE = "/etc/os-release"

# Ce qui trahit un nœud Proxmox. Sondé AVANT Debian : un nœud PVE porte
# « ID=debian » dans son os-release, et l'ordre inverse le classerait Debian.
PROXMOX_INDICES = ("/etc/pve",)
PROXMOX_BINAIRE = "pveversion"

# Les familles que ce dépôt sait nommer, par ID puis par ID_LIKE.
_PAR_ID = {
    "debian": DEBIAN,
    "ubuntu": DEBIAN,
    "raspbian": DEBIAN,
    "linuxmint": DEBIAN,
    "arch": ARCH,
    "archarm": ARCH,
    "endeavouros": ARCH,
    "manjaro": ARCH,
    "cachyos": ARCH,
}
_PAR_ID_LIKE = ((("debian", "ubuntu"), DEBIAN), (("arch",), ARCH))

# Le jeton d'architecture est celui que portent les NOMS de VM ; le changer
# renommerait un parc. « amd64 » par défaut : c'est ce que les deux copies
# absorbées rendaient déjà pour une machine qu'elles ne reconnaissaient pas.
_ARCHS = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "s390x": "s390x",
}
ARCH_DEFAUT = "amd64"

_override_fautif_dit = False


def _chemin_os_release() -> str:
    return os.environ.get(OS_RELEASE_VAR) or OS_RELEASE


def os_release(chemin: str = "") -> dict:
    """Les champs de « os-release », lus au motif et JAMAIS exécutés.

    Rend un dictionnaire vide si le fichier est illisible : sur un système
    qui n'en a pas, l'absence est une réponse et non une panne.
    """
    chemin = chemin or _chemin_os_release()
    champs = {}
    try:
        with open(chemin, encoding="utf-8", errors="replace") as handle:
            contenu = handle.read()
    except OSError:
        return champs
    for ligne in contenu.split("\n"):
        trouve = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", ligne)
        if not trouve:
            continue
        valeur = trouve.group(2).strip().strip("\"'")
        champs[trouve.group(1)] = valeur
    return champs


def _override() -> str:
    """Le jeton imposé par la couture, ou une chaîne vide.

    Un jeton hors vocabulaire est DIT une fois puis ignoré : le propager
    ferait échouer toutes les capacités sur une faute de frappe, sans que
    rien ne dise laquelle.
    """
    global _override_fautif_dit
    valeur = (os.environ.get(HOST_OS_VAR) or "").strip()
    if not valeur:
        return ""
    if valeur in HOSTS:
        return valeur
    if not _override_fautif_dit:
        _override_fautif_dit = True
        diag(f"⚠ {HOST_OS_VAR}={valeur!r} : jeton inconnu, ignoré.")
    return ""


def host_os() -> str:
    """Le jeton de l'hôte. L'ORDRE des épreuves est le contrat.

    Darwin d'abord, puis Proxmox AVANT Debian, puis « os-release » par ID et
    par ID_LIKE. Intervertir les deux du milieu classe un nœud PVE en Debian
    et lui propose un menu qui ne s'applique pas à lui.
    """
    impose = _override()
    if impose:
        return impose
    try:
        if os.uname().sysname == "Darwin":
            return MACOS
    except (AttributeError, OSError):
        pass
    if any(os.path.exists(indice) for indice in PROXMOX_INDICES):
        return PROXMOX
    if shutil.which(PROXMOX_BINAIRE):
        return PROXMOX
    champs = os_release()
    jeton = _PAR_ID.get(champs.get("ID", "").strip().lower())
    if jeton:
        return jeton
    parents = champs.get("ID_LIKE", "").strip().lower()
    for familles, cible in _PAR_ID_LIKE:
        if any(famille in parents for famille in familles):
            return cible
    return UNKNOWN


def is_macos() -> bool:
    """Vrai sur macOS, couture comprise."""
    return host_os() == MACOS


def is_linux() -> bool:
    """Vrai sur tout noyau Linux, y compris un système sans jeton."""
    if host_os() in (DEBIAN, ARCH, PROXMOX):
        return True
    if host_os() == MACOS:
        return False
    try:
        return os.uname().sysname == "Linux"
    except (AttributeError, OSError):
        return False


def arch_token() -> str:
    """L'architecture en jeton générique : amd64, arm64 ou s390x.

    Ce jeton entre dans le NOM des VM : le changer pour la valeur brute
    d'« uname » renommerait un parc entier. Une machine non reconnue rend
    « amd64 », ce que les deux copies absorbées rendaient déjà.
    """
    try:
        machine = os.uname().machine
    except (AttributeError, OSError):
        machine = ""
    return _ARCHS.get(machine, ARCH_DEFAUT)


def require_host(*permis: str) -> int:
    """DS_OK si l'hôte figure parmi `permis`, sinon DS_SKIP après un mot.

    Le retrait est un SAUT et non un échec : un menu qui ne s'applique pas à
    ce système n'a rien raté.
    """
    courant = host_os()
    if courant in permis:
        return DS_OK
    diag(t("This menu is not available on {os}").format(os=courant))
    return DS_SKIP


def _capacite_binaire(nom: str, remede: str = "") -> Capability:
    """Une capacité qui tient à la présence d'un binaire dans le PATH."""
    chemin = shutil.which(nom)
    return Capability(
        nom,
        bool(chemin),
        chemin or "",
        remede,
    )


def capabilities(kdbx_path: str = "") -> list:
    """Ce que cet hôte sait faire, sans rien lancer ni rien lever.

    Chaque sonde regarde le PATH ou le système de fichiers. `kdbx_path` est
    le chemin de coffre que la configuration porte, ou une chaîne vide.
    """
    jeton = host_os()
    trouvees = [_capacite_binaire("git")]

    gestionnaire = {
        MACOS: "brew",
        DEBIAN: "apt-get",
        PROXMOX: "apt-get",
        ARCH: "pacman",
    }.get(jeton)
    if gestionnaire:
        trouvees.append(_capacite_binaire(gestionnaire))

    trouvees.append(_capacite_binaire("virsh"))
    trouvees.append(
        Capability(
            "kvm",
            os.path.exists("/dev/kvm"),
            "/dev/kvm",
            t("Load the kvm module, or join the kvm group"),
        )
    )
    trouvees.append(_capacite_binaire("limactl"))
    trouvees.append(
        Capability(
            "kdbx",
            bool(kdbx_path) and os.path.exists(kdbx_path),
            kdbx_path or "",
            t("Configure the vault path"),
        )
    )
    return trouvees
