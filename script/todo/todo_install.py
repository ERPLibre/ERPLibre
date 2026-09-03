#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser un paquet, une seule fois pour tout le CLI.

Quatre familles de gestionnaires, et trois choses qui changent de l'une à
l'autre : la COMMANDE, le NOM du paquet, et le BINAIRE qu'il pose. Chaque
appelant qui refaisait ce travail chez lui en couvrait un sous-ensemble
différent — d'où un CLI où l'on pouvait installer virt-viewer sous openSUSE
mais pas un navigateur ni lm-sensors.

Deux règles que la composante tient à la place des appelants :

- l'ID de /etc/os-release décide AVANT le PATH. Une machine peut porter
  plusieurs gestionnaires — un poste Debian avec dnf installé pour construire
  un paquet — et c'est l'ID qui dit lequel gouverne le système ;
- la commande s'affiche AVANT la question. On approuve ce qu'on a lu, pas un
  « (y/N) » posé à l'aveugle.
"""

import shlex
import shutil

from script.todo.todo_i18n import t

# Les familles, dans l'ordre où le PATH est interrogé quand l'ID de la
# distribution est inconnu.
FAMILIES = ("apt-get", "dnf", "pacman", "zypper")

# Le préfixe de commande de chaque famille ; les paquets s'ajoutent au bout.
# Tous non interactifs : un menu qui rend la main à un prompt apt bloque.
_INSTALL = {
    "apt-get": ("sudo", "apt-get", "install", "-y"),
    "dnf": ("sudo", "dnf", "install", "-y"),
    "pacman": ("sudo", "pacman", "-S", "--needed", "--noconfirm"),
    "zypper": ("sudo", "zypper", "--non-interactive", "install"),
}

# ID de /etc/os-release -> famille. Les dérivées sont nommées explicitement :
# ID_LIKE existe mais manque ou ment sur assez de distributions pour qu'on ne
# s'y fie pas seul, et le repli par le PATH couvre ce qui n'est pas listé.
_OS_ID_FAMILY = {
    "ubuntu": "apt-get",
    "debian": "apt-get",
    "linuxmint": "apt-get",
    "pop": "apt-get",
    "raspbian": "apt-get",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "almalinux": "dnf",
    "rocky": "dnf",
    "arch": "pacman",
    "manjaro": "pacman",
    "endeavouros": "pacman",
    "opensuse": "zypper",
    "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper",
    "sles": "zypper",
}


def os_id() -> str:
    """L'ID de la distribution hôte, ou '' si /etc/os-release est illisible."""
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


def family() -> str | None:
    """La famille qui gouverne cette machine, ou None si aucune n'est connue.

    L'ID de la distribution d'abord, le PATH ensuite : sur une machine qui
    porte deux gestionnaires, l'ID dit lequel possède le système.
    """
    connue = _OS_ID_FAMILY.get(os_id())
    if connue and shutil.which(connue):
        return connue
    for candidate in FAMILIES:
        if shutil.which(candidate):
            return candidate
    return None


def install_command(paquets, famille=None) -> list | None:
    """La commande d'installation, en liste d'arguments. None si personne.

    `paquets` est une liste de noms, ou un dict {famille: liste} quand le
    paquet ne porte pas le même nom partout (lm-sensors chez Debian,
    lm_sensors chez Fedora et Arch).
    """
    famille = famille or family()
    if not famille:
        return None
    if isinstance(paquets, dict):
        paquets = paquets.get(famille) or []
    paquets = [paquets] if isinstance(paquets, str) else list(paquets)
    if not paquets:
        return None
    return list(_INSTALL[famille]) + paquets


def resolve(binaires, commun=None, par_famille=None, famille=None):
    """(paquets, inconnus) pour les binaires demandés.

    Le nom du binaire n'est presque jamais celui du paquet : `commun` donne la
    correspondance quand elle vaut pour les quatre familles, `par_famille` la
    corrige là où elle diverge. Les paquets sortent dédoublonnés et dans
    l'ordre demandé — trois binaires d'un même paquet ne le demandent qu'une
    fois. `inconnus` liste ce pour quoi aucun paquet n'est déclaré : à dire,
    jamais à deviner.
    """
    famille = famille or family()
    surcharge = (par_famille or {}).get(famille, {})
    commun = commun or {}
    paquets, inconnus = [], []
    for binaire in binaires:
        paquet = surcharge.get(binaire) or commun.get(binaire)
        if not paquet:
            inconnus.append(binaire)
        elif paquet not in paquets:
            paquets.append(paquet)
    return paquets, inconnus


def show_and_ask(cmd, question, is_yes, prefix="  ") -> bool:
    """Afficher la commande, PUIS demander. True si l'opérateur accepte.

    L'ordre est le fond de l'affaire : une question posée avant la commande
    fait approuver à l'aveugle. Centralisé ici pour qu'aucun appelant ne
    puisse l'inverser.
    """
    lisible = cmd if isinstance(cmd, str) else shlex.join(cmd)
    print(f"{prefix}{t('Will execute:')} {lisible}")
    return bool(is_yes(input(question)))


def ask_and_install(execute, cmd, question, is_yes, prefix="  "):
    """Proposer puis lancer. Rend le code de sortie, ou None si rien n'a été
    lancé — refus de l'opérateur, ou aucune commande à proposer.

    `execute` est le lanceur du CLI : exec_command_live REND le code de sortie
    et ne lève rien, donc l'appelant doit tester ce qui revient.
    """
    if not cmd:
        print(f"{prefix}⚠ {t('no known package manager here.')}")
        return None
    if not show_and_ask(cmd, question, is_yes, prefix=prefix):
        print(t("Nothing to do."))
        return None
    lisible = cmd if isinstance(cmd, str) else shlex.join(cmd)
    return execute.exec_command_live(lisible, source_erplibre=False)
