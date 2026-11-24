#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""VM Dolibarr des formulaires de déploiement QEMU et Proxmox.

Le profil d'installation « Dolibarr » installe, dans la VM, une instance de
développement native sur MariaDB, sans Odoo. Ce module en tient la partie
pure : la commande du profil, qui le reconnaît par égalité et non par une
sous-chaîne ; la table système → famille de paquets que juge
lib_dolibarr.native_support ; la commande qui relance l'instance dans
l'invité ; les actions du suivi qu'une VM Dolibarr refuse. APP est son
descripteur dans le registre script.todo.qemu_erp.

Les aides du registre (profile_app, app_of, install_refusals) et ses clés
APP_ODOO, APP_DOLIBARR sont réexportées ici : elles se lisent aussi sous
ce module.
"""

import shlex

from script.dolibarr import lib_dolibarr
from script.todo.qemu_erp import (  # noqa: F401 - réexportés
    APP_DOLIBARR,
    APP_ODOO,
    ErpApp,
    app_of,
    install_refusals,
    profile_app,
    t,
)

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


def action_refusal(kind, parts):
    """La raison de refuser l'action `kind` du suivi, ou une chaîne vide.

    Une VM Dolibarr n'a ni base Odoo à restaurer ni dépendances Python
    d'Odoo à mettre à jour ; la mise à jour du système et du dépôt git lui
    sert, elle."""
    if kind == "dbrestore":
        return t("Dolibarr VM: no Odoo database to restore.")
    if kind == "update" and "python" in (parts or ()):
        return t(
            "Dolibarr VM: the Python dependencies update is Odoo's; untick it."
        )
    return ""


def web_hint(ssh, el_dir):
    """Les lignes qui disent où vérifier l'instance quand le navigateur
    sort en erreur : `ssh` entre dans la VM, `el_dir` est son clone."""
    return [
        t("Dolibarr does not answer in the VM. Check it there:"),
        f"   {ssh} 'cd {el_dir} && python3 script/dolibarr/run.py status'",
    ]


APP = ErpApp(
    key=APP_DOLIBARR,
    name="Dolibarr",
    port=PORT,
    tunnel_port=TUNNEL_PORT,
    restart_button="Restart Dolibarr",
    restart_title="Restarting Dolibarr",
    install_cmd=INSTALL_CMD,
    label=PROFILE_LABEL,
    dev_only=True,
    prod_note=PROD_NOTE,
    offline_refusal=OFFLINE_REFUSAL,
    distro_refusal=distro_refusal,
    guest_probe=True,
    restart_cmd=restart_cmd,
    credentials_cmd=credentials_cmd,
    credentials_button="Show the Dolibarr login and password",
    credentials_title="Dolibarr login",
    action_refusal=action_refusal,
    web_hint=web_hint,
)
