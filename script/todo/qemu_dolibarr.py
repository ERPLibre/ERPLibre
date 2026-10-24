#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""VM Dolibarr des formulaires de déploiement QEMU et Proxmox.

Le profil d'installation « Dolibarr » installe, dans la VM, une instance de
développement native sur MariaDB, sans Odoo. Ce module en tient la partie
pure : la commande du profil, qui le reconnaît par égalité et non par une
sous-chaîne ; la table système → famille de paquets que juge
lib_dolibarr.native_support ; les refus d'une spec avant toute création ;
la commande qui relance l'instance dans l'invité.
"""

import shlex

from script.dolibarr import lib_dolibarr

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - i18n absent hors du TUI

    def t(key):
        return key


APP_ODOO = "odoo"
APP_DOLIBARR = "dolibarr"
INSTANCE = "dolibarr"
# Port de l'instance de dev dans l'invité, sur 127.0.0.1 seulement ; le
# suivi l'atteint par un tunnel SSH ouvert sur TUNNEL_PORT de l'hôte.
PORT = 8080
# Identifiant que pose install_native.py sans --admin-login, et le fichier
# de l'invité qui garde le mot de passe généré.
ADMIN_LOGIN = "admin"
SECRETS_FILE = f"$HOME/.local/share/ERPLibre/dolibarr/{INSTANCE}/secrets.env"
TUNNEL_PORT = 18080
PYTHON = lib_dolibarr.PYTHON

# Commande du profil, lancée depuis le clone ERPLibre de l'invité.
# install_erplibre.sh crée le venv dont l'installateur a besoin ; --yes
# évite la confirmation des paquets, qui bloquerait sous « ssh -n » ; -u
# rend sa sortie au journal du suivi au fil de l'eau. Le mot de passe admin
# est généré dans l'invité et n'y quitte pas secrets.env.
INSTALL_CMD = (
    "make install_os && ./script/install/install_erplibre.sh"
    f" && {PYTHON} -u script/dolibarr/install_native.py --mode dev"
    f" --db mariadb --instance {INSTANCE} --port {PORT} --yes"
    f" && {PYTHON} script/dolibarr/run.py start --instance {INSTANCE}"
)

# Clés i18n : l'appelant les traduit par t().
PROFILE_LABEL = "Dolibarr (development, MariaDB)"
OFFLINE_REFUSAL = (
    "Dolibarr is not deployed offline: its source is not in the download"
    " cache."
)
PROD_NOTE = "Dolibarr installs in development only: production does not apply."

# Famille de paquets de chaque système du catalogue DISTROS qui reçoit
# Dolibarr. Un système absent (NixOS, l'hyperviseur Proxmox VE, tout ajout
# au catalogue) est refusé avec la raison de native_support.
DISTRO_FAMILY = {
    "ubuntu": "apt-get",
    "debian": "apt-get",
    "fedora": "dnf",
    "almalinux": "dnf",
    "rocky": "dnf",
    "opensuse": "zypper",
    "arch": "pacman",
}


def profile_app(cmd):
    """APP_DOLIBARR si `cmd` est la commande du profil, sinon APP_ODOO."""
    return APP_DOLIBARR if (cmd or "").strip() == INSTALL_CMD else APP_ODOO


def app_of(entry):
    """L'application d'une entrée de manifeste ; sans clé « app », Odoo."""
    return (entry or {}).get("app") or APP_ODOO


def distro_refusal(distro):
    """La raison traduite du refus de `distro`, ou une chaîne vide."""
    ok, reason = lib_dolibarr.native_support(
        "Linux", DISTRO_FAMILY.get(distro, ""), distro == "nixos", True, "dev"
    )
    if ok:
        return ""
    return t("Native is not offered here: %s") % t(reason)


def restart_cmd(el_dir):
    """Relance l'instance depuis le clone `el_dir` de l'invité.

    Sans clone, la commande échoue sans rien lancer. run.py start se
    détache : l'instance survit à la fin de la session SSH.
    """
    return (
        f"cd {el_dir} || exit 1; "
        f"{PYTHON} script/dolibarr/run.py start --instance {INSTANCE}"
    )


def credentials_cmd():
    """Commande de l'invité qui affiche l'identifiant et le mot de passe
    admin, lus dans SECRETS_FILE ; sans ce fichier, le dit et sort en 1.
    Le mot de passe n'apparaît qu'à l'écran de l'invité, jamais sur l'hôte.
    """
    login = shlex.quote(f"{t('Login:')} {ADMIN_LOGIN}")
    mdp = shlex.quote(t("Password:"))
    absent = shlex.quote(
        t("No %s: the Dolibarr install has not finished.") % SECRETS_FILE
    )
    return (
        f'f="{SECRETS_FILE}"; '
        f'if [ ! -r "$f" ]; then echo {absent}; exit 1; fi; '
        f"echo {login}; "
        f"printf '%s ' {mdp}; "
        "sed -n 's/^ADMIN_PASSWORD=//p' \"$f\""
    )


def install_refusals(spec):
    """Les raisons de refuser `spec` avant de créer quoi que ce soit.

    Une VM Dolibarr sur un système refusé donne « <nom>: <raison> » ; une
    spec hors ligne qui contient une VM Dolibarr ajoute OFFLINE_REFUSAL,
    car la source Dolibarr n'est pas dans le cache. Rend [] sans
    installation.
    """
    install = spec.get("install")
    if not install:
        return []
    refus = []
    dolibarr = False
    for vm in spec.get("vms") or []:
        cmd = vm.get("install_cmd") or install.get("cmd")
        if profile_app(cmd) != APP_DOLIBARR:
            continue
        dolibarr = True
        raison = distro_refusal(vm.get("distro", ""))
        if raison:
            refus.append(f"{vm['name']}: {raison}")
    if dolibarr and spec.get("offline"):
        refus.append(t(OFFLINE_REFUSAL))
    return refus
