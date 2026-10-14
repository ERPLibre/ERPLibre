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
niveau Stream Deck, son retrait seul, le retrait de tout, puis la base de
nouveau. Chacune lance une commande de l'installateur et ses contrôles ; le
premier échec arrête la VM et nomme la commande ou le contrôle.

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

import os
import re
import shlex
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
# « stat » sans « -L » lit le lien lui-même : c'est la date du LIEN que
# l'installateur ne doit pas réécrire, pas celle du dossier qu'il désigne.
CMD_MTIME_LIEN = f"stat -c '%n %Y' {LIEN_EXTENSION}"
CMD_MTIMES = f"stat -c '%n %Y' {REGLE_UDEV} {VENV_DECK} {LIEN_EXTENSION}"
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
        "--stream-deck",
        ("udev", "venv", "stream-deck-active", "stream-deck-idempotent"),
    ),
    _etape(
        "partial-uninstall",
        "uninstall-stream-deck",
        "--uninstall --stream-deck",
        ("partial-uninstall-gone", "partial-uninstall-kept"),
    ),
    _etape("uninstall", "uninstall", "--uninstall", ("uninstall-gone",)),
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


def autologin(famille, user):
    """(chemin, commande shell) qui ouvre la session de `user` au démarrage.

    awk et non sed ni crudini : awk est dans l'image de base des quatre
    familles, crudini dans aucune, et une réécriture par awk rend le même
    fichier qu'on la joue une fois ou deux. Le résultat passe par un fichier
    temporaire puis « sudo tee », qui réécrit le fichier EN PLACE et garde
    son inode, donc son contexte SELinux. La commande rend 0 si et seulement
    si l'écriture a abouti.
    """
    if famille not in FICHIER_AUTOLOGIN:
        raise ValueError(f"famille inconnue : {famille}")
    if not _NOM_UTILISATEUR.match(user or ""):
        raise ValueError(f"nom d'utilisateur refusé : {user!r}")
    chemin = FICHIER_AUTOLOGIN[famille]
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
