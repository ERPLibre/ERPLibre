# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Voies d'installation proposées selon le système : native, conteneur.

Fonctions pures : le système, la famille de paquets et l'état du moteur de
conteneurs leur arrivent en arguments.

Les raisons rendues sont des CLÉS i18n (texte anglais), des fragments que
l'appelant traduit par t() et place dans « Native is not offered here: %s »
ou « Docker / Podman is not offered here: %s ». La raison propre à NixOS
nomme le service à déclarer : chaque ERP fournit la sienne.
"""

# Familles dont script/todo/todo_install.py monte la commande de paquets, et
# que script/install/install_container.sh sait aussi servir.
LINUX_FAMILIES = ("apt-get", "dnf", "pacman", "zypper")

NO_SYSTEMD = "native production needs systemd"
NO_NATIVE = "unsupported system for a native install"
NO_HOMEBREW = "a native install on macOS needs Homebrew"
NO_ENGINE = "no container engine, and none can be installed here"
NO_DESKTOP = "install Docker Desktop first"


def native_support(system, family, is_nixos, has_systemd, mode, nixos_reason):
    """(True, "") si l'installation native est proposée, sinon (False, raison).

    `system` est platform.system() ; `family` la famille de paquets (celle de
    todo_install.family(), ou « brew » sous macOS quand Homebrew est là).
    NixOS se DÉCLARE au lieu de s'installer par script : la raison rendue
    est alors `nixos_reason`, telle quelle. La production native exige
    systemd, dont ses unités dépendent, et macOS n'en a pas.
    """
    if system == "Darwin":
        if family != "brew":
            return False, NO_HOMEBREW
        if mode == "prod":
            return False, NO_SYSTEMD
        return True, ""
    if system != "Linux":
        return False, NO_NATIVE
    if is_nixos:
        return False, nixos_reason
    if family not in LINUX_FAMILIES:
        return False, NO_NATIVE
    if mode == "prod" and not has_systemd:
        return False, NO_SYSTEMD
    return True, ""


def container_support(system, family, engine_usable):
    """(True, "") si la voie conteneur est proposée, sinon (False, raison).

    Un moteur qui répond (Docker ou Podman, jugé par container_runtime)
    suffit partout. Sans lui, la voie reste proposée là où
    install_container.sh sait installer un moteur : une famille Linux
    connue. Docker Desktop, lui, ne s'installe pas par script.
    """
    if engine_usable:
        return True, ""
    if system == "Linux":
        if family in LINUX_FAMILIES:
            return True, ""
        return False, NO_ENGINE
    return False, NO_DESKTOP
