#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Home s'installe-t-il, extension ACTIVE, sur chaque distribution ?

Une VM par version de distribution, l'une après l'autre. Chacune reçoit le
bureau GNOME par la commande du menu, le code du checkout par un bundle git,
puis la base d'ERPLibre Home par `script/install/install_erplibre_home.sh`.
Une session GNOME s'ouvre par autologin, et le verdict est ce que GNOME Shell
répond à `GetExtensionInfo` : état 1 et erreur vide. Figurer dans
`enabled-extensions` ne suffit pas — une extension qui lève dans `enable()`
y reste listée, en ERREUR.

Sur la même VM passent ensuite cinq étapes (ETAPES) : la base, l'ajout du
niveau Stream Deck avec son service, son retrait seul, le retrait de tout,
puis la base de nouveau. Chacune lance une commande de l'installateur et
ses contrôles ; le premier échec arrête la VM et nomme la commande ou le
contrôle.

Il vit dans long_test/ et non dans test/ : il crée de vraies machines et
prend des heures.

CE QU'IL INSTALLE : HEAD, ET RIEN D'AUTRE

Le code part du checkout par « git bundle create … HEAD », et la VM ne joint
jamais GitHub pour lui. Un fichier suivi et modifié fait refuser la course :
ce qui serait installé ne serait pas ce qui est commité.

  ./long_test/install_erplibre_home.py                 # toute la matrice
  ./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
  ./long_test/install_erplibre_home.py --extras        # + --with-extras
  ./long_test/install_erplibre_home.py --dry-run       # le plan, rien de créé
  ./long_test/install_erplibre_home.py --garder        # garder les VM
  ./long_test/install_erplibre_home.py --detruire      # défaire la course
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    Famille,
    capacite_hote,
    cle_publique,
    detruire,
    detruire_etage1,
    dire,
    drapeaux_cache,
    retirer_alias,
)

# Les listes que gsettings affiche se lisent par le lecteur que partagent
# les outils de l'extension.
sys.path.insert(
    0, os.path.join(RACINE, "script/gnome-extension/erplibre_home/tools")
)
from gsettings_strv import parse_strv  # noqa: E402

OUTIL = "install_erplibre_home"
NOM_BASE = "long-sd"
UUID_EXTENSION = "erplibre-home@technolibre.ca"
# L'utilisateur que deploy_qemu.py crée par défaut : celui de ssh, celui de
# l'autologin, donc celui dont le bus de session est sondé.
UTILISATEUR = "erplibre"
# Le seul système où « --extras » ajoute « --with-extras » à l'installation.
SYSTEME_EXTRAS = "ubuntu:24.04"

# Le gabarit de chaque VM. deploy_qemu.py n'ajoute rien pour un bureau : la
# taille se pose donc ici. « --gpu off » est le cas le plus contraint, le
# rendu logiciel, et un verdict obtenu là tient sur un hôte sans nœud de
# rendu.
VCPUS = 2
MEMOIRE_MO = 4096
DISQUE_GO = 26


def _entree(distro, version, gnome, roulante=False):
    return {
        "distro": distro,
        "version": version,
        "gnome_attendu": gnome,
        "roulante": roulante,
    }


# La matrice, dans l'ordre où les VM se succèdent. La clé « distro:version »
# est celle que deploy_qemu.py accepte et que « --only » reçoit.
#
# « gnome_attendu » est une AFFIRMATION, pas une mesure : chaque VM mesure
# « gnome-shell --version », le rapport porte les deux, et c'est d'après ces
# rapports que la colonne se corrige.
#
# « roulante » : la distribution avance sans numéro. Un GNOME au-delà de
# « shell-version » y rend UNSUPPORTED, et c'est le signal attendu pour mettre
# metadata.json à jour, non une panne.
MATRICE = [
    _entree("ubuntu", "24.04", "46"),
    _entree("ubuntu", "25.10", "49"),
    _entree("ubuntu", "26.04", "50"),
    _entree("debian", "13", "48"),
    _entree("fedora", "41", "47"),
    _entree("fedora", "42", "48"),
    _entree("fedora", "43", "49"),
    _entree("fedora", "44", "50"),
    _entree("almalinux", "10", "47"),
    _entree("rocky", "10", "47"),
    _entree("opensuse", "16.0", "48"),
    _entree("arch", "latest", "51", roulante=True),
    _entree("opensuse", "tumbleweed", "50", roulante=True),
]

# Hors champ, sans VM : le rapport les porte UNSUPPORTED avec leur raison. Les
# versions de GNOME viennent des notes de version amont, pas d'une mesure.
NON_SUPPORTES = [
    {"distro": "debian", "version": "12", "raison": "GNOME 43 < 45"},
    {"distro": "almalinux", "version": "9", "raison": "GNOME 40 < 45"},
    {"distro": "rocky", "version": "9", "raison": "GNOME 40 < 45"},
    {
        "distro": "nixos",
        "version": "25.11",
        "raison": "no GNOME desktop path in the QEMU installer",
    },
    {
        "distro": "proxmox",
        "version": "9",
        "raison": "hypervisor host, out of scope",
    },
]
ARCHITECTURES_HORS_CHAMP = ("arm64", "s390x", "ppc64le")

# La famille de chaque distribution de la matrice : elle choisit le
# gestionnaire de paquets et le fichier d'autologin.
FAMILLE = {
    "ubuntu": "debian",
    "debian": "debian",
    "fedora": "rhel",
    "almalinux": "rhel",
    "rocky": "rhel",
    "opensuse": "suse",
    "arch": "arch",
}

# git, que le chemin « bureau seul » du menu n'installe pas et que les images
# cloud minimales n'embarquent pas toujours.
COMMANDE_GIT = {
    "debian": "command -v git >/dev/null || sudo DEBIAN_FRONTEND="
    "noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y git",
    "rhel": "command -v git >/dev/null || sudo dnf install -y git",
    "suse": "command -v git >/dev/null || sudo zypper --non-interactive"
    " install git",
    "arch": "command -v git >/dev/null || sudo pacman -S --needed"
    " --noconfirm git",
}

# Le fichier que lit le gestionnaire de connexion de chaque famille.
FICHIER_AUTOLOGIN = {
    "debian": "/etc/gdm3/custom.conf",
    "rhel": "/etc/gdm/custom.conf",
    "arch": "/etc/gdm/custom.conf",
    "suse": "/etc/sysconfig/displaymanager",
}
# Là où une distribution s'écarte de sa famille : le paquet gdm3 de Debian
# livre daemon.conf et n'a pas de custom.conf, nom que n'a que le gdm3
# patché d'Ubuntu. Une distribution absente d'ici suit sa famille.
FICHIER_AUTOLOGIN_DISTRO = {
    "debian": "/etc/gdm3/daemon.conf",
}

# Les commandes de session lisent le bus de l'utilisateur connecté à GNOME :
# ssh n'en hérite pas, il faut le nommer.
BUS = "export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus; "
CMD_SESSION = (
    BUS + "test -S /run/user/$(id -u)/bus && gdbus call --session"
    " --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus"
    " --method org.freedesktop.DBus.NameHasOwner org.gnome.Shell"
)
CMD_INFO = (
    BUS + "gdbus call --session --dest org.gnome.Shell.Extensions"
    " --object-path /org/gnome/Shell/Extensions"
    " --method org.gnome.Shell.Extensions.GetExtensionInfo " + UUID_EXTENSION
)
# L'objet que l'extension exporte elle-même, sur la connexion de GNOME Shell.
OBJET_EXTENSION = "/org/gnome/Shell/Extensions/ERPLibreHome"
INTERFACE_EXTENSION = "org.gnome.Shell.Extensions.ERPLibreHome"
# Les imports des points d'entrée du deck. keyboard s'importe sans root :
# il n'ouvre les périphériques d'entrée qu'au démarrage d'un crochet.
CMD_VENV = (
    "cd ~/git/erplibre && .venv.streamdeck/bin/python -c"
    " 'import StreamDeck, pyudev, PIL, cv2, requests, keyboard;"
    ' print("ok")\''
)
REGLE_UDEV = "/etc/udev/rules.d/70-streamdeck.rules"
VENV_DECK = "~/git/erplibre/.venv.streamdeck"
LIEN_EXTENSION = f"~/.local/share/gnome-shell/extensions/{UUID_EXTENSION}"
CMD_UDEV = (
    f"grep -q uaccess {REGLE_UDEV} && grep -q 0fd9 {REGLE_UDEV} && echo ok"
)
# Les constats d'absence et de présence rendent « ok » ou rien : une sortie
# vide, ssh tombé compris, ne passe jamais pour le constat attendu.
CMD_SANS_REGLE = f"test ! -e {REGLE_UDEV} && echo ok"
CMD_SANS_VENV = f"test ! -e {VENV_DECK} && echo ok"
CMD_LIEN = f"test -L {LIEN_EXTENSION} && echo ok"
CMD_SANS_LIEN = (
    f"test ! -e {LIEN_EXTENSION} && test ! -L {LIEN_EXTENSION} && echo ok"
)
# Le service du deck que pose le niveau Stream Deck, et ses réglages.
UNITE_DECK = "erplibre-home-streamdeck.service"
FICHIER_UNITE = f"~/.config/systemd/user/{UNITE_DECK}"
REGLAGES_DECK = "~/.config/erplibre-home/streamdeck.conf"
# systemctl --user par ssh : le gestionnaire de l'utilisateur se joint par
# XDG_RUNTIME_DIR, qu'une session ssh ne pose pas toujours, ou par le bus.
SYSTEMD_USER = BUS + "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
# L'unité existe et lance le point d'entrée du checkout de la VM, chemin
# entier entre guillemets.
CMD_UNITE = (
    'grep -Fqx "ExecStart=\\"$HOME/git/erplibre/script/install/'
    f'erplibre_home_deck.sh\\"" {FICHIER_UNITE} && echo ok'
)
CMD_AUTOSTART = SYSTEMD_USER + f"systemctl --user is-enabled {UNITE_DECK}"
# Une VM n'a pas de deck : ExecCondition échoue, systemd saute le démarrage
# et l'unité reste inactive avec le résultat « exec-condition ».
CMD_CONDITION = SYSTEMD_USER + (
    f"systemctl --user start {UNITE_DECK};"
    f" systemctl --user show -p ActiveState -p Result {UNITE_DECK}"
)
CMD_SANS_SERVICE = (
    f"test ! -e {FICHIER_UNITE} && test ! -e {REGLAGES_DECK} && echo ok"
)
# « stat » sans « -L » lit le lien lui-même : c'est la date du LIEN que
# l'installateur ne doit pas réécrire, pas celle du dossier qu'il désigne.
CMD_MTIME_LIEN = f"stat -c '%n %Y' {LIEN_EXTENSION}"
CMD_MTIMES = (
    f"stat -c '%n %Y' {REGLE_UDEV} {VENV_DECK} {LIEN_EXTENSION}"
    f" {FICHIER_UNITE} {REGLAGES_DECK}"
)
CMD_JOURNAL = (
    "journalctl --user -b --no-pager 2>&1"
    " | grep -i -e erplibrehome -e erplibre-home -e gnome-shell"
    " | tail -200"
)
CMD_EXT_INFO = BUS + f"gnome-extensions info {UUID_EXTENSION} 2>&1"
# La clé que l'installateur écrit et que la désinstallation vide.
CMD_ENABLED = BUS + "gsettings get org.gnome.shell enabled-extensions"
# Deux sortes de lignes d'extension.js : « mount <id> failed », écrite par
# _mount() quand le constructeur d'un indicateur lève, et « enabled », écrite
# à la fin d'enable(), après les montages. L'extension attrape l'exception et
# continue : elle reste ACTIVE, et ListDevices rend « [] » sans l'indicateur
# des appareils comme sans appareil. « || true » garde le code 0 quand grep
# ne trouve rien ; une sortie sans « enabled » veut alors dire que le journal
# n'a pas été lu (ssh tombé, journal vide), jamais que tout est monté.
CMD_MONTAGES = (
    "journalctl --user -b -o cat --no-pager 2>&1"
    r" | grep -E '\[ERPLibreHome\] (mount [^ ]+ failed|enabled)' || true"
)


def _etape(nom, commande, option, controles):
    return {
        "nom": nom,
        "commande": commande,
        "option": option,
        "controles": controles,
    }


# Les cinq étapes, dans l'ordre où elles passent sur la même VM. « commande »
# nomme l'échec quand l'installateur lancé avec « option » ne rend pas 0 ; la
# base n'en a pas, son installation est celle qui précède l'autologin, et
# « reinstall » est suivie d'un redémarrage. « controles » vient ensuite,
# dans l'ordre. Chaque nom, de commande ou de contrôle, est unique : le champ
# « etape » du rapport dit seul quelle étape est tombée.
ETAPES = (
    _etape(
        "base",
        None,
        None,
        (
            "session",
            "gnome-version",
            "extension-active",
            "extension-dbus",
            "extension-indicators",
            "base-no-udev",
            "base-no-venv",
            "base-idempotent",
        ),
    ),
    _etape(
        "stream-deck",
        "install-stream-deck",
        "--stream-deck --deck-program=tiler --autostart",
        (
            "udev",
            "venv",
            "service-unit",
            "service-enabled",
            "service-condition",
            "stream-deck-active",
            "stream-deck-idempotent",
        ),
    ),
    _etape(
        "partial-uninstall",
        "uninstall-stream-deck",
        "--uninstall --stream-deck",
        (
            "partial-uninstall-gone",
            "partial-uninstall-service-gone",
            "partial-uninstall-kept",
        ),
    ),
    _etape(
        "uninstall",
        "uninstall",
        "--uninstall",
        ("uninstall-gone", "uninstall-service-gone"),
    ),
    _etape(
        "reinstall",
        "reinstall",
        "",
        ("reinstall-active", "reinstall-indicators", "reinstall-no-udev"),
    ),
)
# L'option de l'installateur de chaque commande d'étape.
OPTION = {e["commande"]: e["option"] for e in ETAPES if e["commande"]}


def decrire_etapes(extras=False):
    """Les lignes du plan qui décrivent les cinq étapes d'une VM.

    `extras` : la base s'installe avec « --with-extras » (SYSTEME_EXTRAS).
    """
    base = "install_erplibre_home.sh" + (" --with-extras" if extras else "")
    lignes = []
    for rang, etape in enumerate(ETAPES, 1):
        if etape["commande"] is None:
            quoi = f"{base}, autologin, redémarrage"
        elif etape["option"]:
            quoi = f"{etape['commande']} : install_erplibre_home.sh"
            quoi += f" {etape['option']}"
        else:
            quoi = f"{etape['commande']} : {base}, redémarrage"
        lignes.append(
            f"    étape {rang}, {etape['nom']} — {quoi} —"
            f" {', '.join(etape['controles'])}"
        )
    return lignes


def liste_extensions(sortie):
    """La liste qu'affiche « gsettings get … enabled-extensions », ou None.

    Lue par parse_strv, le lecteur des outils de l'extension : « @as [] »
    pour une liste vide, « ['a', 'b'] » sinon. None quand la sortie est vide
    ou n'est pas une telle liste : une lecture ratée ne passe ni pour une
    liste vide ni pour une liste pleine.
    """
    texte = (sortie or "").strip()
    if not texte:
        return None
    try:
        return parse_strv(texte)
    except (ValueError, SyntaxError):
        return None


def cmd_methode(methode):
    """L'appel d'une méthode de l'extension sur le bus de session."""
    return (
        BUS + "gdbus call --session --dest org.gnome.Shell"
        f" --object-path {OBJET_EXTENSION}"
        f" --method {INTERFACE_EXTENSION}.{methode}"
    )


def cle(entree):
    return f"{entree['distro']}:{entree['version']}"


def plan(only=None):
    """Les systèmes à mener, copies des entrées de MATRICE.

    `only` : clés « distro:version » séparées par des virgules, dans l'ordre
    voulu ; None ou "" donne toute la matrice. Une clé hors champ ou inconnue
    lève ValueError plutôt que d'être ignorée : un plan amputé en silence
    rendrait vert un système qui n'a jamais tourné.
    """
    if not only:
        return [dict(e) for e in MATRICE]
    connus = {cle(e): e for e in MATRICE}
    refuses = {cle(e): e["raison"] for e in NON_SUPPORTES}
    choisis = []
    for brut in only.split(","):
        k = brut.strip()
        if not k:
            continue
        if k in refuses:
            raise ValueError(f"{k} : UNSUPPORTED ({refuses[k]})")
        if k not in connus:
            raise ValueError(
                f"{k} : inconnu. Clés possibles : {', '.join(connus)}"
            )
        if all(cle(e) != k for e in choisis):
            choisis.append(dict(connus[k]))
    if not choisis:
        raise ValueError("--only ne nomme aucun système")
    return choisis


_ETAT = re.compile(r"'state': <(-?\d+(?:\.\d+)?)>")
_ERREUR = re.compile(
    r"""'error': <(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")>"""
)


def analyser_extension_info(sortie):
    """{"state": float|None, "error": str} lus dans la sortie de gdbus.

    `GetExtensionInfo` rend un a{sv} au format texte de GVariant :
    « ({'uuid': <'…'>, 'state': <1.0>, 'error': <''>, …},) ». Une extension
    inconnue de GNOME Shell rend le dictionnaire vide « (@a{sv} {},) », lu
    comme state None. GVariant cite une chaîne entre apostrophes, ou entre
    guillemets quand elle contient une apostrophe ; les deux sont lus, et
    leurs échappements défaits.
    """
    texte = sortie or ""
    etat = _ETAT.search(texte)
    trouve = _ERREUR.search(texte)
    erreur = ""
    if trouve:
        brut = trouve.group(1)
        if brut is None:
            brut = trouve.group(2)
        erreur = re.sub(r"\\(.)", r"\1", brut)
    return {
        "state": float(etat.group(1)) if etat else None,
        "error": erreur,
    }


def est_active(info):
    """ACTIVE : état 1 et erreur vide. Toute autre forme est un échec."""
    return bool(info) and info.get("state") == 1 and info.get("error") == ""


_MONTAGE_ECHOUE = re.compile(r"\[ERPLibreHome\] mount (\S+) failed")


def indicateurs_en_echec(sortie):
    """Les ids des indicateurs non montés, triés et sans doublon.

    Lus dans les lignes « [ERPLibreHome] mount <id> failed: <message> »
    de la sortie de CMD_MONTAGES ; un indicateur réactivé qui échoue de
    nouveau n'apparaît qu'une fois. Une sortie vide ou None rend [].
    """
    return sorted(set(_MONTAGE_ECHOUE.findall(sortie or "")))


def etat_systemd(sortie):
    """{propriété: valeur} des lignes « Clé=valeur » de systemctl show,
    quel que soit leur ordre ; {} pour une sortie vide ou None."""
    etat = {}
    for ligne in (sortie or "").splitlines():
        cle_, egal, valeur = ligne.strip().partition("=")
        if egal:
            etat[cle_] = valeur
    return etat


def condition_sautee(etat):
    """Vrai quand systemd a sauté le démarrage sur ExecCondition : unité
    inactive, résultat « exec-condition »."""
    return (
        etat.get("ActiveState") == "inactive"
        and etat.get("Result") == "exec-condition"
    )


def journal_lu(sortie):
    """Vrai quand la sortie de CMD_MONTAGES porte la ligne
    « [ERPLibreHome] enabled » qui clôt enable().

    C'est la preuve que le journal de la session a été lu : sans elle, une
    sortie sans « mount <id> failed » ne dit rien des indicateurs.
    """
    return any(
        ligne.strip().endswith("[ERPLibreHome] enabled")
        for ligne in (sortie or "").splitlines()
    )


_NOM_UTILISATEUR = re.compile(r"^[a-z_][a-z0-9_-]*$")

# Le programme awk de GDM : il retire toute ligne AutomaticLogin* existante,
# puis pose les deux clés juste sous « [daemon] », ou ajoute la section à la
# fin quand le fichier n'en a pas. Le rejouer rend le même fichier.
_AWK_GDM = (
    "/^[ \\t]*AutomaticLogin(Enable)?[ \\t]*=/ {next} "
    "{print} "
    "/^[ \\t]*\\[daemon\\][ \\t]*$/ && !fait "
    '{print "AutomaticLoginEnable=true"; print "AutomaticLogin=" u; fait=1} '
    'END {if (!fait) {print "[daemon]"; '
    'print "AutomaticLoginEnable=true"; print "AutomaticLogin=" u}}'
)
# Celui d'openSUSE : la clé sysconfig, retirée puis posée en dernière ligne.
_AWK_SUSE = (
    "/^DISPLAYMANAGER_AUTOLOGIN=/ {next} {print} "
    'END {print "DISPLAYMANAGER_AUTOLOGIN=\\"" u "\\""}'
)


def autologin(famille, user, distro=None):
    """(chemin, commande shell) qui ouvre la session de `user` au démarrage.

    awk et non sed ni crudini : awk est dans l'image de base des quatre
    familles, crudini dans aucune, et une réécriture par awk rend le même
    fichier qu'on la joue une fois ou deux. Le résultat passe par un fichier
    temporaire puis « sudo tee », qui réécrit le fichier EN PLACE et garde
    son inode, donc son contexte SELinux. La commande rend 0 si et seulement
    si l'écriture a abouti.

    `distro` (clé de FAMILLE) affine le fichier quand la distribution
    s'écarte de sa famille (FICHIER_AUTOLOGIN_DISTRO).
    """
    if famille not in FICHIER_AUTOLOGIN:
        raise ValueError(f"famille inconnue : {famille}")
    if not _NOM_UTILISATEUR.match(user or ""):
        raise ValueError(f"nom d'utilisateur refusé : {user!r}")
    chemin = FICHIER_AUTOLOGIN_DISTRO.get(distro) or FICHIER_AUTOLOGIN[famille]
    programme = _AWK_SUSE if famille == "suse" else _AWK_GDM
    commande = (
        f"f={chemin}; t=$(mktemp) && "
        'sudo mkdir -p "$(dirname "$f")" && sudo touch "$f" && '
        f'sudo awk -v u={user} {shlex.quote(programme)} "$f" > "$t" && '
        'sudo tee "$f" < "$t" > /dev/null; '
        'rc=$?; rm -f "$t"; [ "$rc" -eq 0 ]'
    )
    return chemin, commande


def version_gnome(sortie):
    """« 46.0 » lu dans « GNOME Shell 46.0 », ou ""."""
    trouve = re.search(r"GNOME Shell (\d+(?:\.[0-9A-Za-z.]+)?)", sortie or "")
    return trouve.group(1) if trouve else ""


def majeur(version):
    """« 46 » pour « 46.0 », « » pour une version vide."""
    return (version or "").split(".")[0]


def raison_non_supportee(sortie):
    """La raison de la DERNIÈRE ligne « UNSUPPORTED: », ou ""."""
    raison = ""
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("UNSUPPORTED:"):
            raison = ligne[len("UNSUPPORTED:") :].strip()
    return raison


def nom_vm(entree, horodatage):
    """Le nom de domaine libvirt : la base, le système, l'horodatage.

    `horodatage` est celui de la course (Course.horodatage) : deux courses
    ne nomment jamais la même VM, et une VM gardée par l'une ne porte pas le
    nom d'une VM que l'autre crée puis détruit.

    Réduit à [a-z0-9-] : il sert aussi d'alias ssh, et un point de « 24.04 »
    y serait pris pour un nom de domaine DNS.
    """
    brut = f"{NOM_BASE}-{entree['distro']}-{entree['version']}".lower()
    return re.sub(r"[^a-z0-9-]+", "-", brut) + f"-{horodatage}"


def argv_creation(entree, nom, cle_pub="", drapeaux=()):
    """La ligne de deploy_qemu.py pour une VM de la matrice, sans « sudo »."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        entree["distro"],
        "--version",
        entree["version"],
        "--name",
        nom,
        "--desktop",
        "--gpu",
        "off",
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(drapeaux)


def verdict_systeme(
    entree,
    code_install,
    info,
    gnome_mesure,
    *,
    echec=None,
    raison="",
    duree_s=0,
    journal=None,
):
    """La ligne du rapport d'un système de la matrice.

    `code_install` : le code de sortie de l'installation de la base, ou
    None quand elle n'a pas été lancée ou n'a pas rendu de code. `echec` : le
    nom de la première étape tombée, dans l'ordre du test (vm, ssh, desktop,
    code, autologin, puis les commandes et contrôles d'ETAPES). `raison` : la
    ligne « UNSUPPORTED: » de l'installateur. L'ordre des branches est
    celui des étapes : un échec avant l'installation l'emporte sur tout le
    reste, un code 2 rend UNSUPPORTED, et le verdict ACTIVE exige
    `est_active(info)` : la dernière lecture, celle de la cinquième étape.
    """
    ligne = {
        "distro": entree["distro"],
        "version": entree["version"],
        "gnome_attendu": entree.get("gnome_attendu"),
        "gnome_mesure": gnome_mesure or None,
        "verdict": "ACTIVE",
        "etape": None,
        "duree_s": int(duree_s),
        "journal": journal,
    }
    if code_install is None:
        ligne.update(verdict="FAILED", etape=echec or "install")
    elif code_install == 2:
        ligne.update(verdict="UNSUPPORTED", etape=raison or "install exit 2")
    elif code_install != 0:
        ligne.update(verdict="FAILED", etape="install")
    elif echec:
        ligne.update(verdict="FAILED", etape=echec)
    elif not est_active(info):
        ligne.update(verdict="FAILED", etape="extension-active")
    return ligne


def ligne_non_supportee(entree):
    """La ligne du rapport d'un système hors champ : aucune VM, sa raison."""
    return {
        "distro": entree["distro"],
        "version": entree["version"],
        "gnome_attendu": None,
        "gnome_mesure": None,
        "verdict": "UNSUPPORTED",
        "etape": entree["raison"],
        "duree_s": 0,
        "journal": None,
    }


def code_sortie(systemes):
    """0 quand chaque système de la matrice est ACTIVE, ou UNSUPPORTED là où
    la matrice le permet (une distribution roulante) ; 1 sinon.

    Les lignes hors matrice — NON_SUPPORTES — ne comptent pas : elles n'ont
    jamais eu de VM.
    """
    roulantes = {cle(e): e["roulante"] for e in MATRICE}
    for ligne in systemes:
        k = cle(ligne)
        if k not in roulantes:
            continue
        if ligne["verdict"] == "ACTIVE":
            continue
        if ligne["verdict"] == "UNSUPPORTED" and roulantes[k]:
            continue
        return 1
    return 0


def resume(systemes):
    """Le tableau de fin de course, une chaîne par ligne.

    « ≠ » marque un GNOME mesuré dont la version majeure n'est pas celle de
    la matrice : la colonne est à corriger.
    """
    lignes = [f"  {'système':<22} {'GNOME':<14} verdict"]
    for s in systemes:
        attendu = s.get("gnome_attendu") or "—"
        mesure = s.get("gnome_mesure") or "—"
        ecart = (
            " ≠" if s.get("gnome_mesure") and majeur(mesure) != attendu else ""
        )
        detail = s["verdict"] + (f"({s['etape']})" if s.get("etape") else "")
        gnome = f"{attendu} → {mesure}{ecart}"
        lignes.append(f"  {cle(s):<22} {gnome:<14} {detail}")
    return lignes


def arbre_propre(racine):
    """Vrai quand aucun fichier SUIVI n'est modifié ni indexé sous `racine`.

    Les fichiers non suivis ne comptent pas : ils ne sont ni dans HEAD ni
    dans le bundle, donc ne changent rien à ce que la VM reçoit. Un dossier
    qui n'est pas un dépôt, ou un git qui ne répond pas, rend Faux.
    """
    try:
        fini = subprocess.run(
            [
                "git",
                "-C",
                racine,
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return fini.returncode == 0 and not fini.stdout.strip()


# ---------------------------------------------------------------------------
# La course : ce qui touche aux machines.
# ---------------------------------------------------------------------------

# Chaque attente est bornée : une étape bloquée rend un verdict FAILED et la
# course passe au système suivant au lieu de s'arrêter.
DELAI_CREATION = 1800
DELAI_SSH = 600
DELAI_BUREAU = 5400
DELAI_CODE = 900
DELAI_INSTALL = 1800
# Le temps de taper un mot de passe quand sudo en demande un.
DELAI_SUDO = 300
DELAIS_CONTROLE = {
    "session": 300,
    "extension-active": 120,
    "extension-dbus": 30,
    "extension-indicators": 30,
    "venv": 60,
    "stream-deck-active": 120,
    "partial-uninstall-kept": 120,
    "reinstall-active": 300,
    "reinstall-indicators": 30,
}

# Ce que la machine doit avoir de libre AVANT de créer une VM. Les VM se
# suivent, une seule vit à la fois : la marge vaut pour une. Le disque se
# compare à ce qu'une VM ÉCRIT — un qcow2 n'est pas préalloué — et non à sa
# taille virtuelle. Estimation d'un bureau GNOME et du venv, à corriger
# d'après les rapports.
MARGE_RAM_MO = 1024
DISQUE_ECRIT_GO = 12
MARGE_DISQUE_GO = 8

OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
]
CMD_BOOT_ID = "cat /proc/sys/kernel/random/boot_id"


DELAI_PRESENCE_GNOME = 30


def ssh_base(cible):
    return ["ssh"] + OPTIONS_SSH + [cible]


def chemins_de_course():
    """(journal, dossier) de la course.

    Le dossier porte le même nom que le journal, sans extension : il reçoit
    le bundle et un « .log » par système. `dernier_rapport` ne lit que les
    « .json » du premier niveau de ~/.erplibre/longtest, donc rien de ce qui
    est rangé là n'est jamais pris pour un rapport.
    """
    base = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    os.makedirs(os.path.dirname(base), exist_ok=True)
    return base + ".log", base


def _ajouter(log, texte):
    """Ajoute `texte` au journal d'un système, terminé par un saut de
    ligne."""
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(texte if texte.endswith("\n") else texte + "\n")


class Course:
    """Le rapport d'une course, réécrit à chaque changement.

    Sa forme est le CONTRAT du défaire partagé (descente.py) : « outil »
    filtre les rapports, « pid » empêche de détruire sous une course vivante,
    et « etages » nomme une entrée de niveau 1 par VM encore en vie — c'est
    tout ce que « --detruire » sait reprendre. « systemes » est à ce test
    seul ; descente.py l'ignore.
    """

    def __init__(self, args, journal, dossier):
        self.args = args
        self.journal = journal
        self.dossier = dossier
        # « 20261013-142233 » pour « long-sd-20261013-142233 » : chaque VM
        # de la course le porte dans son nom.
        self.horodatage = os.path.basename(dossier)[len(NOM_BASE) + 1 :]
        self.chemin = journal[:-4] + (
            "-dryrun.json" if args.dry_run else ".json"
        )
        self.head = ""
        self.bundle = ""
        self.rapport = {
            "outil": OUTIL,
            "dry_run": args.dry_run,
            "pid": os.getpid(),
            "head": "",
            "etages": [],
            "systemes": [],
        }

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=2)

    def inscrire(self, etage):
        """Écrit l'étage AVANT la suite : une course qui meurt en cours de
        route laisse de quoi défaire sa VM."""
        self.rapport["etages"].append(etage)
        self.ecrire()

    def retirer(self, etage):
        self.rapport["etages"].remove(etage)
        self.ecrire()

    def noter(self, ligne):
        self.rapport["systemes"].append(ligne)
        self.ecrire()


def commande_bureau():
    """Le bloc « bureau seul » du menu, pris tel quel : attente de
    cloud-init, coupure des mises à jour automatiques, GNOME et son accès
    distant. Ni clone ni Odoo.

    Importé plutôt que recopié : deux copies d'une installation de bureau
    divergent, et c'est celle du test qui reste verte.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)._qemu_erplibre_remote_cmd(None, desktop="gnome")


def creer_vm(nom, entree, journal, dry_run):
    """La VM, par la CLI du dépôt, sous sudo hors essai à blanc.

    Rend (nom, uuid, ok). Une création qui échoue après avoir défini le
    domaine rend quand même son nom et son UUID, avec ok faux : la VM existe,
    et c'est en l'inscrivant au rapport qu'elle reste défaisable.

    Un nom que libvirt définit déjà n'est pas à cette course : la création
    est refusée et rend (None, "", False), si bien que la VM d'une autre
    course n'entre jamais au rapport et n'est jamais détruite par celle-ci.
    """
    if not dry_run and Descente.uuid_libvirt(nom):
        dire(
            f"      ✗ {nom} existe déjà, elle n'est pas à cette course",
            journal,
        )
        return None, "", False
    argv = ([] if dry_run else ["sudo"]) + argv_creation(
        entree, nom, cle_publique(), drapeaux_cache()
    )
    if dry_run:
        dire("      " + " ".join(shlex.quote(a) for a in argv), journal)
        return nom, "", True
    ok = False
    try:
        fini = subprocess.run(argv, timeout=DELAI_CREATION)
        ok = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"      ✗ la création de {nom} s'est arrêtée : {souci}", journal)
    if not ok:
        dire(f"      ✗ la création de {nom} a échoué", journal)
    uuid = Descente.uuid_libvirt(nom)
    if not ok and not uuid:
        return None, "", False
    return nom, uuid, ok


def adresse_de(nom, journal):
    """L'adresse de la VM, et l'entrée ~/.ssh/config qui la nomme.

    La CLI n'écrit pas cette entrée : sans elle, « ssh <nom> » ne résout
    rien et chaque attente irait à son plein délai.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    todo = TODO.__new__(TODO)
    ip = todo._qemu_vm_ip(nom, timeout=DELAI_SSH)
    if not ip:
        dire(f"      ✗ {nom} créée mais sans adresse", journal)
        return ""
    pub = cle_publique()
    prive = pub[:-4] if pub else None
    todo._write_ssh_config_entry([nom], UTILISATEUR, ip, identity_file=prive)
    dire(f"      {nom} : {ip}", journal)
    return ip


def sonder(cible, commande, delai=180):
    """La sortie d'une commande distante, ou "" si elle échoue."""
    try:
        fini = subprocess.run(
            ssh_base(cible) + [commande],
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return fini.stdout.strip() if fini.returncode == 0 else ""


def attendre_ssh(cible, journal, delai=DELAI_SSH):
    """Vrai dès que la machine répond en ssh. Le port s'ouvre avant que
    cloud-init n'ait posé le compte : on attend une commande qui aboutit."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ssh_base(cible) + ["true"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            # Un ssh pendu est un tour d'attente de plus, pas la fin de la
            # course.
            time.sleep(5)
            continue
        if fini.returncode == 0:
            return True
        time.sleep(5)
    dire(f"      ✗ {cible} jamais joignable en {delai} s", journal)
    return False


def lancer(argv, log, delai, entree=None):
    """Lance `argv`, sortie ajoutée au journal du système. Rend le code de
    retour, ou None quand la commande n'a pas abouti dans son délai."""
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fini = subprocess.run(
                argv,
                input=entree,
                text=True,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=delai,
            )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ {argv[0]} interrompu : {souci}")
        return None
    return fini.returncode


def deposer_code(cible, famille, bundle, head, log):
    """git dans la VM, le bundle copié, cloné, HEAD extrait. Rend vrai si
    les trois étapes ont abouti. La VM ne joint jamais GitHub pour le
    code."""
    clone = (
        "test ! -e ~/git/erplibre && mkdir -p ~/git"
        " && git -c advice.detachedHead=false clone -q ~/erplibre_home.bundle"
        f" ~/git/erplibre && git -C ~/git/erplibre checkout -q {head}"
    )
    etapes = (
        ("git", ssh_base(cible) + [COMMANDE_GIT[famille]]),
        (
            "scp",
            ["scp"] + OPTIONS_SSH + [bundle, f"{cible}:erplibre_home.bundle"],
        ),
        ("clone", ssh_base(cible) + [clone]),
    )
    for nom, argv in etapes:
        if lancer(argv, log, DELAI_CODE) != 0:
            _ajouter(log, f"✗ code : {nom}")
            return False
    return True


def installer(cible, log, options=""):
    """L'installateur dans le checkout de la VM, avec `options` (« » pour la
    base, « --stream-deck », « --uninstall »…). Rend (code, sortie).

    La commande et toute sa sortie vont au journal du système : un échec y
    trouve la sortie de chaque commande lancée jusque-là. Le code est None
    quand l'installation n'a pas rendu de code dans son délai.
    """
    commande = "cd ~/git/erplibre && ./script/install/install_erplibre_home.sh"
    if options:
        commande += f" {options}"
    _ajouter(log, f"── {commande}")
    try:
        fini = subprocess.run(
            ssh_base(cible) + [commande],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=DELAI_INSTALL,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ installation interrompue : {souci}")
        return None, ""
    sortie = fini.stdout or ""
    _ajouter(log, sortie)
    _ajouter(log, f"── code de sortie : {fini.returncode}")
    return fini.returncode, sortie


def redemarrer(cible, log):
    """Redémarre la VM et attend qu'elle revienne. Vrai à son retour.

    Le retour se juge à l'identifiant de démarrage du noyau, qui change à
    chaque amorçage : un ssh qui répond encore AVANT l'arrêt ne passe pas
    pour un retour.
    """
    avant = sonder(cible, CMD_BOOT_ID, 30)
    if not avant:
        _ajouter(log, "✗ redémarrage : identifiant de démarrage illisible")
        return False
    try:
        subprocess.run(
            ssh_base(cible) + ["sudo systemctl reboot"],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # La connexion tombe avec la machine : c'est le cas attendu.
        pass
    fin = time.time() + DELAI_SSH
    while time.time() < fin:
        apres = sonder(cible, CMD_BOOT_ID, 30)
        if apres and apres != avant:
            return True
        time.sleep(5)
    _ajouter(log, f"✗ pas de retour du redémarrage en {DELAI_SSH} s")
    return False


def attendre(cible, commande, condition, delai):
    """(vrai, sortie) dès que `condition(sortie)` tient, sondé toutes les
    5 s ; (faux, dernière sortie lue) au bout de `delai` secondes."""
    fin = time.time() + delai
    while True:
        sortie = sonder(cible, commande, 60)
        if condition(sortie):
            return True, sortie
        if time.time() >= fin:
            return False, sortie
        time.sleep(5)


def attendre_extension(cible, delai=DELAIS_CONTROLE["extension-active"]):
    """(info, sortie brute de gdbus) de l'extension, dès qu'elle est
    ACTIVE ou au bout de `delai` secondes."""
    fin = time.time() + delai
    while True:
        brut = sonder(cible, CMD_INFO, 60)
        info = analyser_extension_info(brut)
        if est_active(info) or time.time() >= fin:
            return info, brut
        time.sleep(5)


class Controle:
    """Un contrôle nommé d'une étape, et ce qu'il a lu pour trancher.

    Chaque commande passe par `sonder`, ou par `noter` quand la réponse
    vient d'ailleurs (une attente, l'installateur), et s'inscrit avec sa
    réponse. `clore(ok)` écrit au journal du système une ligne
    « ── contrôle <nom> : réussi|ÉCHEC », puis « $ <commande> » pour chaque
    commande lancée ; sur un échec, la réponse brute de chacune suit sa
    commande. Le journal d'une course nomme ainsi chaque contrôle passé, son
    issue et ce qu'il a lancé.
    """

    def __init__(self, cible, log, nom):
        self.cible = cible
        self.log = log
        self.nom = nom
        self.lus = []

    def noter(self, commande, reponse):
        """Inscrit `commande` et sa réponse ; rend la réponse."""
        self.lus.append((commande, reponse))
        return reponse

    def sonder(self, commande, delai=180):
        """sonder() sur la cible, la commande et sa réponse inscrites."""
        return self.noter(commande, sonder(self.cible, commande, delai))

    def clore(self, ok):
        """Écrit le contrôle au journal du système ; rend `ok`."""
        _ajouter(
            self.log,
            f"── contrôle {self.nom} : {'réussi' if ok else 'ÉCHEC'}",
        )
        for commande, reponse in self.lus:
            _ajouter(self.log, f"   $ {commande}")
            if not ok:
                _ajouter(self.log, f"   → {reponse or '(aucune réponse)'}")
        return ok


def extension_active(controle, delai=DELAIS_CONTROLE["extension-active"]):
    """L'info de l'extension par attendre_extension, la commande
    GetExtensionInfo et sa dernière sortie brute inscrites dans
    `controle`."""
    info, brut = attendre_extension(controle.cible, delai)
    controle.noter(CMD_INFO, brut)
    return info


def indicateurs_non_montes(controle):
    """Les ids des indicateurs que le journal de session dit non montés.

    L'extension attrape l'exception du constructeur d'un indicateur et
    continue : ACTIVE et les réponses D-Bus tiennent même quand aucun
    indicateur n'est monté. Le journal se lit une fois, par `controle` ;
    sans la ligne « [ERPLibreHome] enabled », il n'est pas tenu pour lu et
    la fonction rend ["(journal non lu)"] plutôt qu'une liste vide qui
    passerait pour un succès. Ce qui manque va au journal du système.
    """
    sortie = controle.sonder(
        CMD_MONTAGES, DELAIS_CONTROLE["extension-indicators"]
    )
    if not journal_lu(sortie):
        _ajouter(
            controle.log,
            "✗ journal de session sans « [ERPLibreHome] enabled »",
        )
        return ["(journal non lu)"]
    echecs = indicateurs_en_echec(sortie)
    if echecs:
        _ajouter(
            controle.log, f"✗ indicateurs non montés : {', '.join(echecs)}"
        )
    return echecs


def session_ouverte(cible):
    """(vrai, sortie) quand le bus de l'utilisateur existe et que GNOME
    Shell y a pris son nom ; (faux, dernière sortie) sinon."""
    return attendre(
        cible,
        CMD_SESSION,
        lambda s: s == "(true,)",
        DELAIS_CONTROLE["session"],
    )


def constat(cible, log, nom, commande, delai=180):
    """Le contrôle `nom` : vrai quand `commande` rend « ok »."""
    controle = Controle(cible, log, nom)
    return controle.clore(controle.sonder(commande, delai) == "ok")


def installation(controle, options):
    """L'installateur avec `options`, la commande et son code inscrits dans
    `controle`. Rend le code, None sans code dans le délai."""
    code, _sortie = installer(controle.cible, controle.log, options)
    controle.noter(
        f"install_erplibre_home.sh {options}".rstrip(),
        f"code de sortie {code}",
    )
    return code


def commande_reussie(cible, log, nom, options):
    """Le contrôle `nom` : l'installateur lancé avec `options` rend 0."""
    controle = Controle(cible, log, nom)
    return controle.clore(installation(controle, options) == 0)


def _absents(controle):
    """Vrai quand ni la règle udev ni .venv.streamdeck n'existent."""
    return controle.sonder(CMD_SANS_REGLE) == "ok" and (
        controle.sonder(CMD_SANS_VENV) == "ok"
    )


def _idempotent(controle, options, commande_mtimes):
    """Une seconde installation rend 0 et laisse les dates de
    `commande_mtimes` telles quelles."""
    avant = controle.sonder(commande_mtimes)
    code = installation(controle, options)
    apres = controle.sonder(commande_mtimes)
    return code == 0 and bool(avant) and avant == apres


def _etape_base(cible, entree, log, base):
    """Étape 1, sur la base que l'étape 5 du flux a installée. Rend
    (echec, info, gnome)."""
    info, gnome = None, ""
    controle = Controle(cible, log, "session")
    ouverte, sortie = session_ouverte(cible)
    controle.noter(CMD_SESSION, sortie)
    if not controle.clore(ouverte):
        return "session", info, gnome
    controle = Controle(cible, log, "gnome-version")
    gnome = version_gnome(controle.sonder("gnome-shell --version"))
    if not controle.clore(bool(gnome)):
        return "gnome-version", info, gnome
    attendu = entree["gnome_attendu"]
    if majeur(gnome) != attendu:
        _ajouter(log, f"⚠ GNOME mesuré {gnome}, la matrice dit {attendu}")
    controle = Controle(cible, log, "extension-active")
    info = extension_active(controle)
    if not controle.clore(est_active(info)):
        return "extension-active", info, gnome
    # L'objet D-Bus est exporté avant les réglages : une méthode qui ne les
    # touche pas répondrait même si enable() avait levé ensuite. ListPaths
    # les lit. ListDevices rend « [] » sans appareil branché comme sans
    # indicateur des appareils monté : sa réponse ne prouve pas l'indicateur,
    # d'où la lecture du journal qui suit. Sans venv du deck, celle-ci
    # prouve aussi que les indicateurs du deck se montent quand même.
    controle = Controle(cible, log, "extension-dbus")
    repond = all(
        controle.sonder(
            cmd_methode(methode), DELAIS_CONTROLE["extension-dbus"]
        ).startswith(("('", '("'))
        for methode in ("ListPaths", "ListDevices")
    )
    if not controle.clore(repond):
        return "extension-dbus", info, gnome
    controle = Controle(cible, log, "extension-indicators")
    if not controle.clore(not indicateurs_non_montes(controle)):
        return "extension-indicators", info, gnome
    if not constat(cible, log, "base-no-udev", CMD_SANS_REGLE):
        return "base-no-udev", info, gnome
    if not constat(cible, log, "base-no-venv", CMD_SANS_VENV):
        return "base-no-venv", info, gnome
    controle = Controle(cible, log, "base-idempotent")
    if not controle.clore(_idempotent(controle, base, CMD_MTIME_LIEN)):
        return "base-idempotent", info, gnome
    return None, info, gnome


def _etape_stream_deck(cible, log):
    """Étape 2 : le niveau Stream Deck par-dessus la base, sans
    redémarrage, l'extension étant déjà chargée ; le service du deck est
    posé avec le tiler et activé à la connexion. Rend (echec, info)."""
    option = OPTION["install-stream-deck"]
    if not commande_reussie(cible, log, "install-stream-deck", option):
        return "install-stream-deck", None
    if not constat(cible, log, "udev", CMD_UDEV):
        return "udev", None
    if not constat(cible, log, "venv", CMD_VENV, DELAIS_CONTROLE["venv"]):
        return "venv", None
    if not constat(cible, log, "service-unit", CMD_UNITE):
        return "service-unit", None
    controle = Controle(cible, log, "service-enabled")
    if not controle.clore(controle.sonder(CMD_AUTOSTART) == "enabled"):
        return "service-enabled", None
    controle = Controle(cible, log, "service-condition")
    etat = etat_systemd(controle.sonder(CMD_CONDITION))
    if not controle.clore(condition_sautee(etat)):
        return "service-condition", None
    controle = Controle(cible, log, "stream-deck-active")
    info = extension_active(controle, DELAIS_CONTROLE["stream-deck-active"])
    if not controle.clore(est_active(info)):
        return "stream-deck-active", info
    controle = Controle(cible, log, "stream-deck-idempotent")
    if not controle.clore(_idempotent(controle, option, CMD_MTIMES)):
        return "stream-deck-idempotent", info
    return None, info


def _etape_retrait_partiel(cible, log):
    """Étape 3 : le niveau Stream Deck retiré seul ; l'extension reste liée,
    activée et ACTIVE. Rend (echec, info)."""
    option = OPTION["uninstall-stream-deck"]
    if not commande_reussie(cible, log, "uninstall-stream-deck", option):
        return "uninstall-stream-deck", None
    controle = Controle(cible, log, "partial-uninstall-gone")
    if not controle.clore(_absents(controle)):
        return "partial-uninstall-gone", None
    if not constat(
        cible, log, "partial-uninstall-service-gone", CMD_SANS_SERVICE
    ):
        return "partial-uninstall-service-gone", None
    controle = Controle(cible, log, "partial-uninstall-kept")
    garde = controle.sonder(CMD_LIEN) == "ok" and UUID_EXTENSION in (
        liste_extensions(controle.sonder(CMD_ENABLED)) or []
    )
    info = None
    if garde:
        info = extension_active(
            controle, DELAIS_CONTROLE["partial-uninstall-kept"]
        )
    if not controle.clore(garde and est_active(info)):
        return "partial-uninstall-kept", info
    return None, info


def _etape_retrait(cible, log):
    """Étape 4 : tout retiré. Rend l'échec ou None."""
    if not commande_reussie(cible, log, "uninstall", OPTION["uninstall"]):
        return "uninstall"
    controle = Controle(cible, log, "uninstall-gone")
    liste = liste_extensions(controle.sonder(CMD_ENABLED))
    parti = (
        controle.sonder(CMD_SANS_LIEN) == "ok"
        and liste is not None
        and UUID_EXTENSION not in liste
        and _absents(controle)
    )
    if not controle.clore(parti):
        return "uninstall-gone"
    if not constat(cible, log, "uninstall-service-gone", CMD_SANS_SERVICE):
        return "uninstall-service-gone"
    return None


def _etape_reinstallation(cible, log, base):
    """Étape 5 : la base de nouveau, puis un redémarrage, pour que GNOME
    Shell charge l'extension à neuf plutôt que de réactiver la copie qu'il
    tient de l'étape 1. Rend (echec, info)."""
    controle = Controle(cible, log, "reinstall")
    revenu = False
    if installation(controle, base) == 0:
        # redemarrer() écrit au journal la raison d'un retour manqué.
        revenu = redemarrer(cible, log)
        controle.noter("sudo systemctl reboot", "revenue" if revenu else "")
    if not controle.clore(revenu):
        return "reinstall", None
    controle = Controle(cible, log, "reinstall-active")
    ouverte, sortie = session_ouverte(cible)
    controle.noter(CMD_SESSION, sortie)
    info = None
    if ouverte:
        info = extension_active(controle, DELAIS_CONTROLE["reinstall-active"])
    if not controle.clore(ouverte and est_active(info)):
        return "reinstall-active", info
    controle = Controle(cible, log, "reinstall-indicators")
    if not controle.clore(not indicateurs_non_montes(controle)):
        return "reinstall-indicators", info
    controle = Controle(cible, log, "reinstall-no-udev")
    if not controle.clore(_absents(controle)):
        return "reinstall-no-udev", info
    return None, info


def controler(cible, entree, log, extras=False):
    """Les cinq étapes d'ETAPES, dans l'ordre ; le premier échec, commande
    ou contrôle, arrête les suivantes. Chaque commande et chaque contrôle
    laisse au journal du système son nom, son issue et ce qu'il a lancé
    (Controle).

    `extras` : la base s'installe avec « --with-extras », comme à l'étape 5
    du flux. Rend (echec, info, gnome) : le nom de l'étape tombée ou None,
    la dernière réponse de GetExtensionInfo, la version de GNOME mesurée.
    """
    base = "--with-extras" if extras else ""
    echec, info, gnome = _etape_base(cible, entree, log, base)
    if echec:
        return echec, info, gnome
    for etape in (_etape_stream_deck, _etape_retrait_partiel):
        echec, lue = etape(cible, log)
        info = lue or info
        if echec:
            return echec, info, gnome
    echec = _etape_retrait(cible, log)
    if echec:
        return echec, info, gnome
    echec, lue = _etape_reinstallation(cible, log, base)
    return echec, lue or info, gnome


def joindre_diagnostic(cible, log):
    """Ce qu'un échec joint au journal du système, après la sortie de
    l'installateur qui y est déjà."""
    for titre, commande in (
        ("journalctl --user -b", CMD_JOURNAL),
        (f"gnome-extensions info {UUID_EXTENSION}", CMD_EXT_INFO),
    ):
        _ajouter(log, f"── {titre}\n{sonder(cible, commande) or '(rien)'}")


def journal_systeme(entree):
    """Le nom du journal d'un système dans le dossier de la course."""
    return f"{entree['distro']}-{entree['version']}.log"


def mener_un(course, entree):
    """Un système, de la création de sa VM à son verdict. Rend la ligne du
    rapport ; la VM reste inscrite dans course.rapport["etages"]."""
    debut = time.time()
    log = os.path.join(course.dossier, journal_systeme(entree))
    famille = FAMILLE[entree["distro"]]
    etat = {"code": None, "info": None, "gnome": "", "echec": None}
    raison = ""

    def ligne():
        return verdict_systeme(
            entree,
            etat["code"],
            etat["info"],
            etat["gnome"],
            echec=etat["echec"],
            raison=raison,
            duree_s=time.time() - debut,
            journal=os.path.basename(log),
        )

    dire(
        f"  ── {cle(entree)} (GNOME attendu {entree['gnome_attendu']})",
        course.journal,
    )
    nom, uuid, ok = creer_vm(
        nom_vm(entree, course.horodatage), entree, course.journal, False
    )
    if nom:
        course.inscrire(
            {"niveau": 1, "nom": nom, "uuid": uuid, "alias": nom, "cree": True}
        )
    if not ok:
        etat["echec"] = "vm"
        return ligne()
    if not adresse_de(nom, course.journal) or not attendre_ssh(
        nom, course.journal
    ):
        etat["echec"] = "ssh"
        return ligne()
    bureau = commande_bureau()
    if lancer(ssh_base(nom) + ["bash -s"], log, DELAI_BUREAU, bureau) != 0:
        etat["echec"] = "desktop"
        return ligne()
    # Le script du menu peut rendre 0 après un téléchargement manqué : sur
    # une VM dont le bureau est installé par la course, l'absence de GNOME
    # Shell est un bureau raté, non un système que l'installateur refuse.
    if not sonder(nom, "command -v gnome-shell", DELAI_PRESENCE_GNOME):
        _ajouter(log, "✗ GNOME Shell absent après l'étape du bureau")
        etat["echec"] = "desktop"
        joindre_diagnostic(nom, log)
        return ligne()
    if not deposer_code(nom, famille, course.bundle, course.head, log):
        etat["echec"] = "code"
        return ligne()
    extras = course.args.extras and cle(entree) == SYSTEME_EXTRAS
    etat["code"], sortie = installer(
        nom, log, "--with-extras" if extras else ""
    )
    if etat["code"] == 2:
        raison = raison_non_supportee(sortie)
    if etat["code"] != 0:
        if etat["code"] != 2:
            joindre_diagnostic(nom, log)
        return ligne()
    _chemin, commande = autologin(famille, UTILISATEUR, entree["distro"])
    if lancer(ssh_base(nom) + [commande], log, 120) != 0:
        etat["echec"] = "autologin"
        return ligne()
    if not redemarrer(nom, log):
        etat["echec"] = "ssh"
        return ligne()
    etat["echec"], etat["info"], etat["gnome"] = controler(
        nom, entree, log, extras
    )
    if etat["echec"]:
        joindre_diagnostic(nom, log)
    return ligne()


def rafraichir_sudo(journal):
    """Renouvelle le jeton de sudo. Rend vrai s'il est valide.

    « sudo -v » devant un terminal, qui peut demander le mot de passe ;
    « sudo -n -v » sinon, qui échoue au lieu d'attendre un mot de passe que
    personne ne tapera.
    """
    terminal = sys.stdin is not None and sys.stdin.isatty()
    argv = ["sudo", "-v"] if terminal else ["sudo", "-n", "-v"]
    try:
        fini = subprocess.run(argv, timeout=DELAI_SUDO)
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"  ✗ {' '.join(argv)} : {souci}", journal)
        return False
    if fini.returncode != 0:
        dire(f"  ✗ {' '.join(argv)} a échoué", journal)
    return fini.returncode == 0


def plan_tient(journal):
    """La machine peut-elle héberger une VM ? Le dire AVANT de la créer."""
    coeurs, ram, disque = capacite_hote()
    dire(
        f"  machine locale : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque",
        journal,
    )
    manque = []
    if ram < MEMOIRE_MO + MARGE_RAM_MO:
        manque.append(f"RAM (il en faut {MEMOIRE_MO + MARGE_RAM_MO} Mo)")
    if disque < DISQUE_ECRIT_GO + MARGE_DISQUE_GO:
        manque.append(
            f"disque (il en faut {DISQUE_ECRIT_GO + MARGE_DISQUE_GO} Go"
            f" libres ; le disque virtuel fait {DISQUE_GO} Go, creux)"
        )
    if manque:
        dire(f"  ✗ pas assez de {' ni de '.join(manque)}", journal)
        return False
    return True


def creer_bundle(dossier, journal):
    """(sha de HEAD, chemin du bundle), ou ("", "") si git a échoué."""
    chemin = os.path.join(dossier, "erplibre_home.bundle")
    try:
        head = subprocess.run(
            ["git", "-C", RACINE, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        fini = subprocess.run(
            ["git", "-C", RACINE, "bundle", "create", chemin, "HEAD"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"  ✗ git bundle : {souci}", journal)
        return "", ""
    if head.returncode or fini.returncode:
        dire(f"  ✗ git bundle : {fini.stderr.strip()[:160]}", journal)
        return "", ""
    sha = head.stdout.strip()
    dire(f"  code : HEAD {sha[:12]}, {chemin}", journal)
    return sha, chemin


def annoncer(systemes, args, journal):
    """Le plan : chaque système, le gabarit des VM, ce qui est hors champ."""
    dire(
        f"  {len(systemes)} système(s), un à la fois ; chaque VM :"
        f" {VCPUS} vCPU, {MEMOIRE_MO} Mo, {DISQUE_GO} Go, --desktop --gpu off",
        journal,
    )
    for entree in systemes:
        roulante = " (roulante)" if entree["roulante"] else ""
        extras = (
            " + --with-extras"
            if args.extras and cle(entree) == SYSTEME_EXTRAS
            else ""
        )
        dire(
            f"    {cle(entree):<22} GNOME attendu"
            f" {entree['gnome_attendu']}{roulante}{extras}",
            journal,
        )
    if not args.only:
        for entree in NON_SUPPORTES:
            dire(
                f"    {cle(entree):<22} UNSUPPORTED : {entree['raison']}"
                " (aucune VM)",
                journal,
            )
        dire(
            f"    {', '.join(ARCHITECTURES_HORS_CHAMP)} : UNSUPPORTED,"
            " amd64 seulement",
            journal,
        )
    dire("  sur chaque VM, l'une après l'autre :", journal)
    for ligne in decrire_etapes():
        dire(ligne, journal)
    if args.extras and any(cle(e) == SYSTEME_EXTRAS for e in systemes):
        dire(
            f"  sur {SYSTEME_EXTRAS}, la base des étapes 1 et 5 :"
            " install_erplibre_home.sh --with-extras",
            journal,
        )
    if args.extras and all(cle(e) != SYSTEME_EXTRAS for e in systemes):
        dire(f"  ⚠ --extras ne vaut que pour {SYSTEME_EXTRAS}", journal)


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--only",
        default="",
        help="clés distro:version séparées par des virgules"
        " (défaut : toute la matrice)",
    )
    parseur.add_argument(
        "--extras",
        action="store_true",
        help=f"installer avec --with-extras sur {SYSTEME_EXTRAS}",
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--garder",
        action="store_true",
        help="garder chaque VM après son verdict",
    )
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal, dossier = chemins_de_course()

    # `detruire_une` défait une VM IMBRIQUÉE chez son parent ; ce test n'en
    # crée aucune, et le défaire partagé ne l'appelle donc jamais. Elle le
    # dit plutôt que d'être None : le jour où elle serait appelée, le journal
    # nommerait la raison au lieu de « NoneType is not callable ».
    def pas_d_imbrique(parent_alias, identite, nom, log=None):
        dire(f"      ✗ {nom} : ce test ne crée pas de VM imbriquée", log)
        return False

    if args.detruire:
        famille = Famille(OUTIL, NOM_BASE, pas_d_imbrique)
        return detruire(famille, journal, dry_run=args.dry_run)

    try:
        systemes = plan(args.only or None)
    except ValueError as souci:
        dire(f"  ✗ {souci}", journal)
        return 1

    dire(f"  journal : {journal}", journal)
    annoncer(systemes, args, journal)
    course = Course(args, journal, dossier)
    if not args.only:
        for entree in NON_SUPPORTES:
            course.rapport["systemes"].append(ligne_non_supportee(entree))

    if args.dry_run:
        dire(
            f"  bureau : {len(commande_bureau())} caractères de commande"
            " distante, celle du menu",
            journal,
        )
        for entree in systemes:
            creer_vm(nom_vm(entree, course.horodatage), entree, journal, True)
        if not arbre_propre(RACINE):
            dire(
                "  ⚠ des fichiers suivis sont modifiés : la course réelle"
                " refusera de partir",
                journal,
            )
        course.ecrire()
        dire(f"  rapport : {course.chemin}", journal)
        dire("  --dry-run : rien n'a été créé.", journal)
        return 0

    # La course installe HEAD : un fichier suivi et modifié ne serait pas
    # dans la VM, et le verdict porterait sur autre chose que ce qu'on lit.
    if not arbre_propre(RACINE):
        dire(
            "  ✗ des fichiers suivis sont modifiés ou indexés : commiter ou"
            " remiser d'abord, la VM reçoit HEAD.",
            journal,
        )
        return 1
    if not plan_tient(journal):
        return 1
    os.makedirs(dossier, exist_ok=True)
    course.head, course.bundle = creer_bundle(dossier, journal)
    if not course.bundle:
        return 1
    course.rapport["head"] = course.head
    course.ecrire()
    dire(f"  rapport : {course.chemin}", journal)

    survivante = False
    for entree in systemes:
        try:
            debut = time.time()
            ligne = mener_un(course, entree)
        except Exception as souci:  # noqa: BLE001 - un système, pas la course
            ligne = verdict_systeme(
                entree,
                None,
                None,
                "",
                echec=f"exception ({souci})",
                duree_s=time.time() - debut,
                journal=journal_systeme(entree),
            )
        course.noter(ligne)
        marque = {"ACTIVE": "✅", "UNSUPPORTED": "⚪"}.get(
            ligne["verdict"], "❌"
        )
        etape = f" ({ligne['etape']})" if ligne["etape"] else ""
        dire(f"  {marque} {cle(entree)} : {ligne['verdict']}{etape}", journal)
        if args.garder:
            continue
        # En cours de course, jamais detruire() : il demande « OUI ». Le
        # défaire lit libvirt par « sudo -n » : un jeton expiré le fait
        # échouer, d'où une seconde passe, jeton renouvelé.
        for passe in range(2):
            if passe:
                if not course.rapport["etages"]:
                    break
                rafraichir_sudo(journal)
            for etage in list(course.rapport["etages"]):
                if detruire_etage1(
                    journal, etage["nom"], attendu=etage["uuid"] or None
                ):
                    retirer_alias({"etages": [etage]}, journal, NOM_BASE)
                    course.retirer(etage)
        # Une VM encore en vie arrête la course : plan_tient ne vérifie la
        # place que d'une seule VM, et les suivantes, empilées, tomberaient
        # pour une raison de l'hôte, lue comme une panne de distribution.
        if course.rapport["etages"]:
            survivante = True
            noms = ", ".join(e["nom"] for e in course.rapport["etages"])
            dire(
                f"  ✗ {noms} toujours en vie : la course s'arrête,"
                " --detruire la défait",
                journal,
            )
            for reste in systemes[systemes.index(entree) + 1 :]:
                course.noter(
                    verdict_systeme(
                        reste, None, None, "", echec="previous-vm-still-up"
                    )
                )
            break

    for ligne in resume(course.rapport["systemes"]):
        dire(ligne, journal)
    if course.rapport["etages"]:
        dire(
            f"  {len(course.rapport['etages'])} VM gardée(s) :"
            " --detruire les défait",
            journal,
        )
    if survivante:
        return 1
    return code_sortie(course.rapport["systemes"])


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
