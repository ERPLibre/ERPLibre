#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Faut-il « sudo » pour parler à libvirt ? Une seule réponse pour tout TODO.

Appartenir au groupe libvirt suffit à joindre qemu:///system : préfixer alors
les commandes de « sudo » ne donne aucun droit de plus et réclame un mot de
passe pour rien. La question se tranche en ESSAYANT, jamais en lisant
/etc/group : les groupes d'un processus sont figés à l'ouverture de session,
donc un utilisateur fraîchement ajouté y figure sans que le shell courant en
dispose. L'essai dit ce que le shell peut FAIRE, la table dit ce qui a été
DÉCLARÉ — et c'est l'écart entre les deux qui explique « je suis pourtant
dans le groupe ».
"""

import grp
import os
import shutil
import subprocess

# Réponse du sondage, gardée pour la session : chaque commande du menu la
# demande, et lancer un virsh par entrée de menu se verrait.
_CACHE: bool | None = None

PROBE = ["virsh", "--connect", "qemu:///system", "list", "--name"]


def reset_cache() -> None:
    """Oublie le sondage. À appeler après un changement de droits."""
    global _CACHE
    _CACHE = None


def libvirt_reachable(force: bool = False) -> bool:
    """qemu:///system répond-il SANS sudo ?

    Rend faux quand virsh est absent : il n'y a alors rien à joindre, et le
    dire évite de conclure « il faut sudo » sur une machine sans libvirt.
    """
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    if shutil.which("virsh") is None:
        _CACHE = False
        return _CACHE
    try:
        probe = subprocess.run(
            PROBE, capture_output=True, text=True, timeout=15
        )
        _CACHE = probe.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _CACHE = False
    return _CACHE


def needs_sudo() -> bool:
    """Faut-il préfixer les commandes libvirt de « sudo » ?

    Root n'en a jamais besoin. Sans virsh, il n'y a rien à préfixer : rendre
    faux laisse la commande échouer sur « command not found » plutôt que sur
    une invite de mot de passe qui ne mène nulle part.
    """
    if os.geteuid() == 0:
        return False
    if shutil.which("virsh") is None:
        return False
    return not libvirt_reachable()


def sudo_prefix() -> str:
    """« sudo » et son espace, ou la chaîne vide. À coller devant virsh."""
    return "sudo " if needs_sudo() else ""


# L'URI ne se laisse JAMAIS implicite. Pour un utilisateur non root, libvirt
# choisit « qemu:///session », un hyperviseur séparé où AUCUNE des VM du
# système n'existe : « virsh list --all » y rend une liste vide, sans erreur
# et sans avertissement. Appartenir au groupe libvirt donne le DROIT d'accéder
# à qemu:///system, mais ne change pas l'URI par défaut. Tant que les
# commandes passaient par sudo, l'URI de root masquait l'omission.
LIBVIRT_URI = "qemu:///system"


def virsh_argv(*args: str) -> list:
    """Argv d'un virsh local : sudo si besoin, URI toujours."""
    prefixe = ["sudo"] if needs_sudo() else []
    return prefixe + ["virsh", "--connect", LIBVIRT_URI, *args]


def virsh_cmd(args: str = "") -> str:
    """Même chose, en chaîne pour un shell. « args » est déjà échappé."""
    base = f"{sudo_prefix()}virsh --connect {LIBVIRT_URI}"
    return f"{base} {args}" if args else base


def group_state(user: str = "") -> tuple[bool, bool]:
    """(déclaré, actif) pour le groupe libvirt.

    « déclaré » : le nom figure dans le groupe, d'après la base système.
    « actif » : le processus courant PORTE le groupe. Les deux diffèrent tant
    que la session n'a pas été rouverte, et c'est le cas qui déroute le plus.
    Les deux valent faux quand le groupe n'existe pas — libvirt pas encore
    installé.
    """
    user = user or _current_user()
    try:
        entry = grp.getgrnam("libvirt")
    except KeyError:
        return False, False
    declared = user in entry.gr_mem
    try:
        declared = declared or grp.getgrgid(os.getgid()).gr_name == "libvirt"
    except (KeyError, OSError):
        pass
    return declared, entry.gr_gid in os.getgroups()


def _current_user() -> str:
    """Le nom de l'utilisateur courant, sans lever si l'environnement ment."""
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or ""
