#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le passage USB à une VM tient-il de bout en bout, sans deck réel ?

Un Stream Deck SIMULÉ remplace le vrai : un gadget configfs (0fd9:0080,
« Stream Deck MK.2 », série inventée, une fonction HID de 64 octets) lié à
l'UDC de dummy_hcd. Le noyau de l'hôte l'énumère comme un deck branché, et
le débrancher se fait en vidant l'UDC du gadget : le même événement udev
qu'un câble qu'on retire, au numéro de périphérique près, que le noyau
renouvelle à chaque branchement.

Six étapes, chacune avec son verdict, sur ce que les commandes du dépôt
font réellement — usb_qemu.py, qemu_usb.py, deploy_qemu.py,
erplibre_home_status.py — et non sur une copie de leur logique :

1. emulated-deck : modules, gadget, host_usb_devices() le liste en tête ;
2. libvirt-mechanics : sur un domaine sans système, attach --live,
   --config et les deux, leur idempotence, detach, et « info usb » de QEMU ;
3. spice : spice_usbredir_xml sur un domaine VNC arrêté, défini puis
   démarré ; SPICE en tête, les emplacements de redirection présents ;
4. auto-reattach : install-autoreattach, mapping add, débranchement (le
   <hostdev> d'adresse morte part par l'unité de débranchement),
   rebranchement (rattaché au nouveau numéro), puis remove-autoreattach ne
   laisse rien — /usr/local/libexec dans l'état d'avant ;
5. guest : une vraie Debian 13 (image « generic », le noyau cloud n'a pas
   l'USB) déployée avec --usb-hostdev 0fd9:0080 ; le deck est dans son
   sysfs, plugged_decks() d'erplibre_home_status l'y voit, et il disparaît
   puis revient avec le débranchement et le rebranchement ;
6. host-status : erplibre_home_status dit le deck « passé à la VM ».

Une étape qui échoue arrête celles qui en dépendent (DEPENDANCES), et le
verdict nomme le premier contrôle tombé : FAILED(unplug-detached). Le
nettoyage passe quand même, sauf --garder.

Il vit dans long_test/ et non dans test/ : il charge des modules du noyau,
écrit dans /etc et crée de vraies VM.

CE QU'IL TOUCHE, ET COMMENT IL LE DÉFAIT

Le rapport nomme, AVANT de les créer, le gadget, les modules qu'il charge
(ceux déjà chargés ne lui appartiennent pas), le rattachement automatique
qu'il pose, et chaque domaine avec son UUID. « --detruire » ne défait que
cela. La course refuse de partir quand l'hôte porte déjà ce qu'elle
retirerait : un rattachement automatique posé, une correspondance non vide,
un deck réel, l'UDC de dummy_hcd pris par un autre gadget.

  ./long_test/usb_passthrough.py                 # les six étapes
  ./long_test/usb_passthrough.py --sans-invite   # 1 à 4, quelques minutes
  ./long_test/usb_passthrough.py --dry-run       # le plan, rien de créé
  ./long_test/usb_passthrough.py --garder        # garder VM, gadget, règle
  ./long_test/usb_passthrough.py --detruire      # défaire la course
"""

import argparse
import glob
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from xml.sax.saxutils import escape

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    autre_descente,
    cle_publique,
    descente_vivante,
    detruire_etage1,
    dire,
    drapeaux_cache,
    retirer_alias,
)
from install_erplibre_home import (  # noqa: E402
    adresse_de,
    attendre_ssh,
    rafraichir_sudo,
    ssh_base,
)

from script.todo import qemu_usb as qu  # noqa: E402

OUTIL = "usb_passthrough"
NOM_BASE = "usb-pt"
URI = qu.DEFAULT_URI

# Le deck simulé. La série est inventée : elle ne désigne aucun appareil,
# et c'est elle qui distingue le gadget de tout autre périphérique 0fd9:0080.
VID, PID = "0fd9", "0080"
FABRICANT = "Elgato"
PRODUIT = "Stream Deck MK.2"
SERIE = "LT00USBPT0001"

CONFIGFS = "/sys/kernel/config/usb_gadget"
GADGET = "erplibre-usb-pt"
# Les modules du gadget, dans l'ordre de modprobe ; udc_core vient avec
# dummy_hcd. Le déchargement suit l'ordre inverse des dépendances.
MODULES = ("dummy_hcd", "libcomposite", "usb_f_hid")
ORDRE_DECHARGEMENT = ("usb_f_hid", "dummy_hcd", "libcomposite", "udc_core")
_UDC = re.compile(r"^dummy_udc\.\d+$")

# Descripteur HID d'un périphérique « vendeur » (page 0xff00) : rapports de
# 64 octets en entrée et en sortie, la taille de ceux d'un deck. usbhid de
# l'hôte le prend et crée un hidraw, comme pour un vrai deck.
DESCRIPTEUR_HID = bytes(
    [
        0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x15, 0x00, 0x26, 0xFF,
        0x00, 0x75, 0x08, 0x95, 0x40, 0x09, 0x01, 0x81, 0x02, 0x95, 0x40,
        0x09, 0x01, 0x91, 0x02, 0xC0,
    ]
)  # fmt: skip

DISTRO, VERSION = "debian", "13"
CLI = os.path.join(RACINE, "script/qemu/usb_qemu.py")
DEPLOY = os.path.join(RACINE, "script/qemu/deploy_qemu.py")
PYTHON_VENV = os.path.join(RACINE, ".venv.erplibre/bin/python")
# L'interpréteur des commandes root, celui de l'unité systemd et du menu.
PYTHON_SYSTEME = "/usr/bin/python3"
LIBEXEC_PARENT = "/usr/local/libexec"
# Le verrou que les unités de branchement et de débranchement partagent
# (usb_qemu.LOCK_PATH, recopié : le test lit qemu_usb, pas le CLI ; un test
# unitaire garde les deux égaux). Leur premier lancement le crée ;
# remove-autoreattach le retire.
VERROU_UNITES = "/run/erplibre-usb.lock"
DOSSIER_MAPPING = os.path.dirname(qu.MAPPING)

# Les fichiers que plugged_decks() charge, copiés dans l'invité : la
# fonction de l'hôte y tourne telle quelle, sur le sysfs de l'invité.
FICHIERS_STATUT = (
    "script/__init__.py",
    "script/todo/erplibre_home_status.py",
    "script/todo/erplibre_home_service.py",
    "script/todo/streamdeck_models.py",
    "script/todo/todo_i18n.py",
    "script/todo/qemu_usb.py",
)
DOSSIER_INVITE = "/tmp/erplibre-usb-pt"

# Les étapes, dans l'ordre, et celles dont chacune a besoin. SPICE ne
# dépend de rien : un domaine arrêté n'a pas besoin du deck.
ETAPES = (
    "emulated-deck",
    "libvirt-mechanics",
    "spice",
    "auto-reattach",
    "guest",
    "host-status",
)
DEPENDANCES = {
    "emulated-deck": (),
    "libvirt-mechanics": ("emulated-deck",),
    "spice": (),
    "auto-reattach": ("emulated-deck", "libvirt-mechanics"),
    "guest": ("emulated-deck",),
    "host-status": ("guest",),
}
ETAPES_INVITE = ("guest", "host-status")

DESCRIPTION = {
    "emulated-deck": "deck simulé : modules, gadget configfs, listé en tête",
    "libvirt-mechanics": "attach/detach live, config, les deux, idempotence",
    "spice": "SPICE en tête et emplacements de redirection, domaine arrêté",
    "auto-reattach": "règle udev, débranchement, rebranchement, retrait",
    "guest": f"{DISTRO} {VERSION} avec --usb-hostdev, deck vu dans l'invité",
    "host-status": "erplibre_home_status : deck passé à la VM",
}

# Les attentes, en secondes. Le débranchement et le rebranchement passent
# par udev puis par une unité systemd : une fraction de seconde d'habitude,
# quelques secondes sur un hôte chargé.
DELAI_ENUMERATION = 15
DELAI_UNITE = 30
DELAI_INVITE_USB = 60
DELAI_CREATION = 1800
DELAI_SSH = 600
DELAI_VIRSH = 120


# ---------------------------------------------------------------------------
# Ce qui se calcule sans rien toucher : noms, scripts, analyses.
# ---------------------------------------------------------------------------


def noms(horodatage):
    """Les domaines de la course : {"meca", "spice", "invite"}.

    Chacun porte NOM_BASE, son rôle et l'horodatage de la course : lire
    « virsh list » dit d'où vient chaque machine, et deux courses ne
    nomment jamais le même domaine. [a-z0-9-] seulement : le nom de
    l'invité sert aussi d'alias ssh et de nom d'hôte.
    """
    return {
        "meca": f"{NOM_BASE}-meca-{horodatage}",
        "spice": f"{NOM_BASE}-spice-{horodatage}",
        "invite": f"{NOM_BASE}-{DISTRO}-{VERSION}-{horodatage}",
    }


def xml_domaine_nu(nom):
    """Un domaine libvirt sans système ni disque ni réseau : q35, un
    contrôleur qemu-xhci, un VNC sur 127.0.0.1.

    Le BIOS n'y trouve rien à amorcer et s'arrête là, mais QEMU tourne :
    c'est tout ce qu'un <hostdev> et « info usb » demandent. 256 Mio
    suffisent au firmware.
    """
    return (
        "<domain type='kvm'>\n"
        f"  <name>{escape(nom)}</name>\n"
        "  <memory unit='MiB'>256</memory>\n"
        "  <vcpu>1</vcpu>\n"
        "  <os><type arch='x86_64' machine='q35'>hvm</type></os>\n"
        "  <features><acpi/><apic/></features>\n"
        "  <devices>\n"
        "    <controller type='usb' model='qemu-xhci'/>\n"
        "    <graphics type='vnc' port='-1' listen='127.0.0.1'/>\n"
        "    <video><model type='virtio'/></video>\n"
        "  </devices>\n"
        "</domain>\n"
    )


def operations_gadget(udc, racine=CONFIGFS, nom=GADGET, serie=SERIE):
    """Les écritures configfs qui créent le deck simulé et le branchent sur
    `udc`, dans l'ordre : [("mkdir", chemin) | ("ecrire", chemin, bytes)
    | ("lien", cible, chemin)].

    L'écriture dans UDC vient en dernier : c'est elle qui branche. ValueError
    pour un UDC qui n'a pas la forme d'un UDC de dummy_hcd — le nom finit
    dans un fichier de configfs écrit en root.
    """
    if not _UDC.match(udc or ""):
        raise ValueError(f"UDC inattendu : {udc!r}")
    g = f"{racine}/{nom}"
    fonction = f"{g}/functions/hid.usb0"

    def texte(chemin, valeur):
        return ("ecrire", chemin, f"{valeur}\n".encode())

    return [
        ("mkdir", g),
        texte(f"{g}/idVendor", f"0x{VID}"),
        texte(f"{g}/idProduct", f"0x{PID}"),
        texte(f"{g}/bcdUSB", "0x0200"),
        texte(f"{g}/bcdDevice", "0x0100"),
        ("mkdir", f"{g}/strings/0x409"),
        texte(f"{g}/strings/0x409/manufacturer", FABRICANT),
        texte(f"{g}/strings/0x409/product", PRODUIT),
        texte(f"{g}/strings/0x409/serialnumber", serie),
        ("mkdir", f"{g}/configs/c.1/strings/0x409"),
        texte(f"{g}/configs/c.1/strings/0x409/configuration", "hid"),
        texte(f"{g}/configs/c.1/MaxPower", "100"),
        ("mkdir", fonction),
        texte(f"{fonction}/protocol", "0"),
        texte(f"{fonction}/subclass", "0"),
        texte(f"{fonction}/report_length", "64"),
        ("ecrire", f"{fonction}/report_desc", DESCRIPTEUR_HID),
        ("lien", fonction, f"{g}/configs/c.1/hid.usb0"),
        texte(f"{g}/UDC", udc),
    ]


def _printf_octal(donnees):
    """Le format printf qui écrit exactement `donnees` : chaque octet en
    « \\ooo ». Rien d'autre n'y entre, donc ni « % » ni apostrophe."""
    return "".join(f"\\{octet:03o}" for octet in donnees)


def script_sh(operations):
    """Les opérations de operations_gadget en script sh, qui s'arrête à la
    première erreur. Chaque chemin passe par shlex.quote ; chaque contenu
    par printf en octal, ce qui écrit aussi bien du texte qu'un
    descripteur binaire."""
    lignes = ["set -e"]
    for op in operations:
        if op[0] == "mkdir":
            lignes.append(f"mkdir -p {shlex.quote(op[1])}")
        elif op[0] == "ecrire":
            lignes.append(
                f"printf '{_printf_octal(op[2])}' > {shlex.quote(op[1])}"
            )
        elif op[0] == "lien":
            lignes.append(f"ln -s {shlex.quote(op[1])} {shlex.quote(op[2])}")
        else:
            raise ValueError(f"opération inconnue : {op[0]!r}")
    return "\n".join(lignes) + "\n"


def script_branchement(branche, udc="", racine=CONFIGFS, nom=GADGET):
    """Le script qui branche (`branche` vrai, sur `udc`) ou débranche le
    gadget. Débrancher, c'est écrire une ligne vide dans UDC : le noyau
    retire le périphérique de l'hôte comme un câble qu'on tire."""
    chemin = f"{racine}/{nom}/UDC"
    if branche:
        if not _UDC.match(udc or ""):
            raise ValueError(f"UDC inattendu : {udc!r}")
        return script_sh([("ecrire", chemin, f"{udc}\n".encode())])
    return script_sh([("ecrire", chemin, b"\n")])


def script_retrait_gadget(racine=CONFIGFS, nom=GADGET):
    """Le script qui défait le gadget : débranché, puis ses dossiers
    retirés du plus profond au plus haut — configfs refuse « rm -r ».
    Un gadget absent rend 0, et un UDC déjà vide n'arrête rien."""
    g = shlex.quote(f"{racine}/{nom}")
    return (
        f"[ -d {g} ] || exit 0\n"
        f"printf '\\n' > {g}/UDC 2>/dev/null || true\n"
        f"rm -f {g}/configs/c.1/hid.usb0\n"
        f"rmdir {g}/configs/c.1/strings/0x409 {g}/configs/c.1"
        f" {g}/functions/hid.usb0 {g}/strings/0x409 {g}\n"
    )


def modules_a_decharger(avant, apres):
    """Les modules que la course a chargés — présents `apres`, absents
    `avant` —, dans ORDRE_DECHARGEMENT. Un module déjà là ne lui appartient
    pas et reste."""
    return [m for m in ORDRE_DECHARGEMENT if m in apres and m not in avant]


def bloquee_par(etape, verdicts):
    """Les étapes dont `etape` dépend et qui n'ont pas réussi, d'après
    `verdicts` ({étape: "PASSED" | "FAILED(…)" | "SKIPPED(…)"}). Vide :
    l'étape peut partir."""
    return [d for d in DEPENDANCES[etape] if verdicts.get(d, "") != "PASSED"]


_PRODUIT_INFO_USB = re.compile(r"Product (.*?)(?:, ID: (\S+))?\s*$")


def parse_info_usb(texte):
    """[(produit, id)] des lignes de « info usb » (moniteur HMP de QEMU) :
    « Device 0.2, Port 2, Speed 12 Mb/s, Product Stream Deck MK.2, ID:
    hostdev0 ». id vaut "" quand QEMU n'en donne pas."""
    vus = []
    for ligne in (texte or "").splitlines():
        m = _PRODUIT_INFO_USB.search(ligne)
        if m and "Device" in ligne:
            vus.append((m.group(1).strip(), m.group(2) or ""))
    return vus


# Une ligne par périphérique USB de l'invité : nom sysfs, VID, PID, série,
# produit, séparés par « | » ; le produit vient en dernier, il peut
# contenir des espaces.
CMD_USB_INVITE = (
    "for d in /sys/bus/usb/devices/*; do"
    ' [ -r "$d/idVendor" ] || continue;'
    ' printf \'%s|%s|%s|%s|%s\\n\' "${d##*/}" "$(cat $d/idVendor)"'
    ' "$(cat $d/idProduct)" "$(cat $d/serial 2>/dev/null)"'
    ' "$(cat $d/product 2>/dev/null)"; done'
)


def parse_usb_invite(texte):
    """Les lignes de CMD_USB_INVITE -> [{"sysname", "vid", "pid",
    "serial", "product"}]. Une ligne qui n'a pas ses cinq champs est
    ignorée."""
    vus = []
    for ligne in (texte or "").splitlines():
        champs = ligne.split("|", 4)
        if len(champs) != 5:
            continue
        sysname, vid, pid, serie, produit = (c.strip() for c in champs)
        vus.append(
            {
                "sysname": sysname,
                "vid": vid.lower(),
                "pid": pid.lower(),
                "serial": serie,
                "product": produit,
            }
        )
    return vus


def liste_json(sortie):
    """La première ligne de `sortie` qui se lit comme une liste JSON, []
    sans elle. ssh mêle ses avertissements (« Permanently added … ») à la
    sortie de la commande distante, avant comme après elle."""
    for ligne in (sortie or "").splitlines():
        if not ligne.startswith("["):
            continue
        try:
            valeur = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(valeur, list):
            return valeur
    return []


def deck_simule(peripheriques, serie=SERIE):
    """Le périphérique de `peripheriques` qui porte la série du deck
    simulé, ou None. Les dicts ont « serial » (forme read_usb_device ou
    parse_usb_invite)."""
    for p in peripheriques or ():
        if p.get("serial") == serie:
            return p
    return None


def unite(gabarit, instance):
    """Le nom d'une instance d'unité gabarit : `instance` s'insère entre
    l'arobase et le point du nom du gabarit."""
    return gabarit.replace("@.", f"@{instance}.", 1)


def unite_detache(bus, dev):
    """L'unité que la règle udev lance au débranchement du deck à l'adresse
    `bus`, `dev`."""
    return unite(qu.DETACH_UNIT_NAME, f"{VID}-{int(bus):03d}-{int(dev):03d}")


def unite_rattache(sysname):
    """L'unité que la règle udev lance au branchement du deck `sysname`."""
    return unite(qu.UNIT_NAME, sysname)


def commande_decks_invite(dossier=DOSSIER_INVITE):
    """La commande distante qui lance plugged_decks() depuis la copie de
    FICHIERS_STATUT posée dans `dossier`, et imprime son résultat en JSON.
    -I : seul `dossier` s'ajoute au chemin de recherche."""
    code = (
        "import json, sys; "
        f"sys.path.insert(0, {dossier!r}); "
        "from script.todo.erplibre_home_status import plugged_decks; "
        "print(json.dumps(plugged_decks()))"
    )
    return f"python3 -I -c {shlex.quote(code)}"


def archive_statut(racine=RACINE, fichiers=FICHIERS_STATUT):
    """Un tar en mémoire des `fichiers` du dépôt, chemins relatifs gardés."""
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w") as tar:
        for relatif in fichiers:
            tar.add(os.path.join(racine, relatif), arcname=relatif)
    return tampon.getvalue()


def argv_cli(*args, root=False):
    """usb_qemu.py lancé comme le menu le lance : interpréteur système,
    -I et -B. En root par « sudo -n », qui échoue plutôt que d'attendre un
    mot de passe que personne ne tapera."""
    prefixe = ["sudo", "-n"] if root else []
    return [*prefixe, PYTHON_SYSTEME, "-I", "-B", CLI, *args]


def argv_deploiement(nom, cle_pub="", drapeaux=()):
    """deploy_qemu.py pour l'invité, sans « sudo » : la distribution et
    la version du test, le deck simulé par son VID:PID. --no-upgrade : la
    mise à jour des paquets au premier démarrage n'apprend rien sur l'USB
    et coûte des minutes."""
    argv = [
        PYTHON_VENV,
        DEPLOY,
        "--distro",
        DISTRO,
        "--version",
        VERSION,
        "--name",
        nom,
        "--usb-hostdev",
        f"{VID}:{PID}",
        "--no-upgrade",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(drapeaux)


def chemins_autoreattach():
    """Ce que install-autoreattach pose et que remove-autoreattach doit
    retirer, chemins absolus."""
    return (
        qu.UDEV_RULE_PATH,
        qu.UNIT_PATH,
        qu.DETACH_UNIT_PATH,
        qu.LIBEXEC_CLI,
        qu.LIBEXEC_LIB,
        qu.LIBEXEC_DIR.rstrip("/"),
    )


def restes_autoreattach(hote, existe=os.path.lexists):
    """Les chemins qui restent après remove-autoreattach : un fichier
    posé encore là, le verrou des unités, puis la correspondance,
    /usr/local/libexec ou le dossier de la correspondance dont l'existence
    n'est plus celle d'avant la course (`hote` : « mapping_avant »,
    « libexec_avant », « etc_avant »)."""
    restes = [c for c in chemins_autoreattach() if existe(c)]
    if existe(VERROU_UNITES):
        restes.append(VERROU_UNITES)
    if existe(LIBEXEC_PARENT) != bool(hote.get("libexec_avant")):
        restes.append(LIBEXEC_PARENT)
    if not hote.get("mapping_avant") and existe(qu.MAPPING):
        restes.append(qu.MAPPING)
    if existe(DOSSIER_MAPPING) != bool(hote.get("etc_avant")):
        restes.append(DOSSIER_MAPPING)
    return restes


def verdict_texte(ligne):
    """« PASSED », « FAILED(contrôle) » ou « SKIPPED(raison) »."""
    if ligne.get("detail"):
        return f"{ligne['verdict']}({ligne['detail']})"
    return ligne["verdict"]


def resume(etapes):
    """Le tableau de fin de course, une chaîne par ligne."""
    lignes = [f"  {'étape':<20} {'durée':>7}  verdict"]
    for e in etapes:
        duree = f"{e.get('duree_s', 0):>6.1f}s"
        lignes.append(f"  {e['etape']:<20} {duree}  {verdict_texte(e)}")
    return lignes


def code_sortie(etapes):
    """0 quand chaque étape a réussi, ou a été sautée À LA DEMANDE
    (--sans-invite, --garder) ; 1 sinon, nettoyage compris."""
    for e in etapes:
        if e["verdict"] == "PASSED":
            continue
        if e["verdict"] == "SKIPPED" and e.get("detail") in (
            "--sans-invite",
            "--garder",
        ):
            continue
        return 1
    return 0


# ---------------------------------------------------------------------------
# La course : ce qui touche à l'hôte.
# ---------------------------------------------------------------------------


class Echec(Exception):
    """Le premier contrôle tombé d'une étape : son nom fait le verdict."""


def chemins_de_course():
    """(journal, rapport, horodatage) de la course, sous
    ~/.erplibre/longtest, préfixés de NOM_BASE."""
    horodatage = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.expanduser(f"~/.erplibre/longtest/{NOM_BASE}-{horodatage}")
    os.makedirs(os.path.dirname(base), exist_ok=True)
    return base + ".log", base + ".json", horodatage


def modules_presents():
    """Les modules d'ORDRE_DECHARGEMENT que le noyau porte en ce moment."""
    return [m for m in ORDRE_DECHARGEMENT if os.path.isdir(f"/sys/module/{m}")]


def pilote(sysname, sysfs="/sys"):
    """Le pilote de la première interface du périphérique `sysname` qui en
    a un (« usbhid »), "" sinon."""
    base = os.path.join(sysfs, "bus/usb/devices", sysname)
    for interface in sorted(glob.glob(base + ":*")):
        lien = os.path.join(interface, "driver")
        if os.path.islink(lien):
            return os.path.basename(os.readlink(lien))
    return ""


def udc_dummy():
    """Le premier UDC de dummy_hcd sous /sys/class/udc, "" sans lui."""
    for chemin in sorted(glob.glob("/sys/class/udc/dummy_udc.*")):
        nom = os.path.basename(chemin)
        if _UDC.match(nom):
            return nom
    return ""


def gadgets_sur_dummy(racine=CONFIGFS):
    """Les gadgets configfs liés à un UDC de dummy_hcd : {nom: udc}."""
    pris = {}
    for dossier in glob.glob(os.path.join(racine, "*")):
        try:
            with open(os.path.join(dossier, "UDC"), encoding="utf-8") as fh:
                udc = fh.read().strip()
        except OSError:
            continue
        if udc.startswith("dummy_udc"):
            pris[os.path.basename(dossier)] = udc
    return pris


def gadget_vivant():
    """Vrai quand le gadget de cette pile existe dans configfs."""
    return os.path.isdir(f"{CONFIGFS}/{GADGET}")


def attendre_que(sonde, delai, pas=0.5):
    """La première valeur vraie de `sonde()`, essayée toutes les `pas`
    secondes ; la dernière valeur lue au bout de `delai` secondes."""
    fin = time.time() + delai
    while True:
        valeur = sonde()
        if valeur or time.time() >= fin:
            return valeur
        time.sleep(pas)


class Course:
    """Le rapport et le journal d'une course, et ce qu'elle lance.

    Le rapport suit la forme du défaire partagé (descente.py) : « outil »
    filtre les rapports, « pid » empêche de défaire sous une course vivante,
    « etages » nomme chaque domaine encore en vie avec son UUID. « hote »
    nomme ce que la course a posé hors de libvirt et qui reste à défaire :
    le gadget, les modules chargés, le rattachement automatique.

    Chaque commande passe par `lancer`, qui l'inscrit avec son code et sa
    sortie ; `controle(nom, ok, preuve)` écrit au journal « ── contrôle
    <nom> : réussi|ÉCHEC », la preuve, chaque commande inscrite depuis le
    contrôle précédent et, sur un échec, leurs sorties ; un échec lève
    Echec(nom).
    """

    def __init__(self, args, journal, chemin, horodatage):
        self.args = args
        self.journal = journal
        self.chemin = chemin
        self.noms = noms(horodatage)
        self.lus = []
        self.virsh_prefixe = []
        self.deck = None
        self.udc = ""
        self.rapport = {
            "outil": OUTIL,
            "dry_run": args.dry_run,
            "pid": os.getpid(),
            "horodatage": horodatage,
            "etages": [],
            "hote": {
                "modules_charges": [],
                "gadget": "",
                "autoreattach": False,
                "mapping_avant": os.path.exists(qu.MAPPING),
                "libexec_avant": os.path.exists(LIBEXEC_PARENT),
                "etc_avant": os.path.exists(DOSSIER_MAPPING),
            },
            "etapes": [],
        }

    # -- rapport ----------------------------------------------------------

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=2)

    def hote(self, **valeurs):
        """Met à jour « hote » et récrit le rapport AVANT la suite."""
        self.rapport["hote"].update(valeurs)
        self.ecrire()

    def inscrire(self, nom, alias=""):
        """Inscrit le domaine `nom` avec son UUID dès qu'il existe."""
        etage = {
            "niveau": 1,
            "nom": nom,
            "uuid": Descente.uuid_libvirt(nom),
            "alias": alias,
            "cree": True,
        }
        self.rapport["etages"].append(etage)
        self.ecrire()
        return etage

    def dire(self, message):
        dire(message, self.journal)

    # -- commandes --------------------------------------------------------

    def lancer(self, argv, entree=None, delai=DELAI_VIRSH, env=None):
        """(code, sortie et erreurs mêlées) de `argv`, inscrits pour le
        prochain contrôle. Un délai dépassé ou une commande absente rend
        le code 124 ou 127, jamais une exception."""
        try:
            fini = subprocess.run(
                argv,
                input=entree,
                capture_output=True,
                text=isinstance(entree, str) or entree is None,
                timeout=delai,
                env=env,
            )
            sortie = fini.stdout + fini.stderr
            if isinstance(sortie, bytes):
                sortie = sortie.decode(errors="replace")
            code = fini.returncode
        except FileNotFoundError as souci:
            code, sortie = 127, str(souci)
        except subprocess.TimeoutExpired:
            code, sortie = 124, f"délai de {delai} s dépassé"
        self.lus.append((shlex.join(argv), code, sortie))
        return code, sortie

    def virsh(self, *args, delai=DELAI_VIRSH):
        """virsh sur URI, en LC_ALL=C : ses messages se lisent en anglais
        quelle que soit la langue de l'opérateur."""
        argv = [*self.virsh_prefixe, "virsh", "--connect", URI, *args]
        return self.lancer(argv, delai=delai, env=dict(os.environ, LC_ALL="C"))

    def cli(self, *args, root=False):
        return self.lancer(argv_cli(*args, root=root), delai=DELAI_VIRSH)

    def sh_root(self, script):
        return self.lancer(["sudo", "-n", "sh", "-s"], entree=script)

    def controle(self, nom, ok, preuve=""):
        lignes = [f"── contrôle {nom} : {'réussi' if ok else 'ÉCHEC'}"]
        if preuve:
            lignes.append(f"   {preuve}")
        for commande, code, sortie in self.lus:
            lignes.append(f"   $ {commande}  → {code}")
            if not ok:
                for ligne in (sortie or "(rien)").rstrip().splitlines()[-15:]:
                    lignes.append(f"     {ligne}")
        self.lus = []
        for ligne in lignes:
            self.dire("    " + ligne)
        if not ok:
            raise Echec(nom)
        return True

    # -- lectures ---------------------------------------------------------

    def etat(self, domaine, inactive=False):
        """usb_state() de la vue live, ou de la config avec `inactive`."""
        args = ["dumpxml", domaine] + (["--inactive"] if inactive else [])
        code, xml = self.virsh(*args)
        return qu.usb_state(xml if code == 0 else None)

    def hostdevs_deck(self, domaine, inactive=False):
        """Les <hostdev> du VID:PID du deck dans la vue demandée."""
        return [
            h
            for h in self.etat(domaine, inactive)["hostdevs"]
            if (h["vid"], h["pid"]) == (VID, PID)
        ]

    def info_usb(self, domaine):
        """parse_info_usb() de « info usb », [] quand QEMU ne répond pas."""
        code, sortie = self.virsh(
            "qemu-monitor-command", domaine, "--hmp", "info usb"
        )
        return parse_info_usb(sortie) if code == 0 else []

    def deck_hote(self):
        """Le deck simulé tel que l'hôte le voit maintenant, ou None."""
        return deck_simule(qu.host_usb_devices())

    def attendre_deck(self, ancien_devnum=None):
        """Le deck simulé dès que l'hôte l'énumère, à un autre numéro que
        `ancien_devnum` quand il est donné ; None au bout du délai."""

        def sonde():
            deck = self.deck_hote()
            if deck and deck["devnum"] != ancien_devnum:
                return deck
            return None

        return attendre_que(sonde, DELAI_ENUMERATION)

    def journal_unite(self, nom, depuis):
        """Les lignes que l'unité `nom` a journalisées depuis l'époque
        `depuis`."""
        _code, sortie = self.lancer(
            [
                "sudo",
                "-n",
                "journalctl",
                "-u",
                nom,
                "--since",
                f"@{int(depuis)}",
                "--no-pager",
                "-o",
                "cat",
            ],
            delai=30,
        )
        return sortie

    def attendre_journal(self, nom, depuis, attendu):
        """Vrai dès que le journal de l'unité `nom` contient chaque chaîne
        de `attendu` : journald écrit après la fin de l'unité, et la
        lecture se refait quelques secondes."""
        return bool(
            attendre_que(
                lambda: all(
                    a in self.journal_unite(nom, depuis) for a in attendu
                ),
                10,
                pas=1,
            )
        )

    # -- actions communes ---------------------------------------------------

    def branchement(self, branche):
        code, _ = self.sh_root(script_branchement(branche, self.udc))
        return code == 0

    def definir(self, nom):
        """Définit le domaine sans système `nom` et l'inscrit au rapport."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".xml", prefix="erplibre-usb-pt-", delete=False
        ) as fh:
            fh.write(xml_domaine_nu(nom))
        try:
            code, _ = self.virsh("define", fh.name)
        finally:
            os.unlink(fh.name)
        if code == 0:
            self.inscrire(nom)
        return code == 0

    def assurer_branche(self):
        """Branche le gadget s'il ne l'est pas, et relit le deck ; vrai
        quand l'hôte l'énumère."""
        try:
            with open(f"{CONFIGFS}/{GADGET}/UDC", encoding="utf-8") as fh:
                lie = bool(fh.read().strip())
        except OSError:
            return False
        if not lie and not self.branchement(True):
            return False
        self.deck = self.attendre_deck()
        return bool(self.deck)

    def etat_domaine(self, nom):
        code, sortie = self.virsh("domstate", nom)
        return sortie.strip() if code == 0 else ""


# ---------------------------------------------------------------------------
# Les étapes. Chacune rend la preuve de son dernier contrôle, ou lève Echec.
# ---------------------------------------------------------------------------


def etape_deck(course):
    """Étape 1 : le deck simulé, énuméré par l'hôte, listé en tête."""
    avant = modules_presents()
    # Inscrits AVANT modprobe : une course qui meurt là laisse de quoi les
    # décharger. Ils se recalculent juste après sur ce qui est vraiment
    # apparu.
    course.hote(modules_charges=modules_a_decharger(avant, ORDRE_DECHARGEMENT))
    code, _ = course.lancer(["sudo", "-n", "modprobe", "-a", *MODULES])
    course.hote(modules_charges=modules_a_decharger(avant, modules_presents()))
    course.controle(
        "deck-modules",
        code == 0 and all(m in modules_presents() for m in MODULES),
        f"chargés par la course : {course.rapport['hote']['modules_charges']}",
    )
    course.udc = attendre_que(udc_dummy, 5)
    course.controle(
        "deck-udc",
        bool(course.udc) and not gadgets_sur_dummy(),
        f"UDC {course.udc or '—'}",
    )
    course.hote(gadget=f"{CONFIGFS}/{GADGET}", udc=course.udc)
    code, _ = course.sh_root(script_sh(operations_gadget(course.udc)))
    course.controle("deck-gadget", code == 0, f"{CONFIGFS}/{GADGET}")
    course.deck = course.attendre_deck()
    deck = course.deck or {}
    course.controle(
        "deck-host-sees",
        bool(course.deck)
        and deck.get("product") == PRODUIT
        and (deck.get("vid"), deck.get("pid")) == (VID, PID),
        f"{deck.get('sysname')} {qu.device_line(deck) if deck else '—'}",
    )
    devs = qu.host_usb_devices()
    code, sortie = course.cli("list", "--json")
    try:
        liste = json.loads(sortie) if code == 0 else []
    except ValueError:
        liste = []
    course.controle(
        "deck-listed-first",
        bool(devs)
        and devs[0].get("serial") == SERIE
        and devs[0].get("is_deck")
        and bool(liste)
        and liste[0].get("serial") == SERIE,
        f"en tête : {qu.device_line(devs[0]) if devs else '—'}"
        f" ; {len(devs)} périphérique(s) passables",
    )
    return f"{course.deck['sysname']} @ {course.deck['busnum']:03d}." + (
        f"{course.deck['devnum']:03d}, pilote {pilote(course.deck['sysname'])}"
    )


def _compte(course, domaine):
    """(hostdevs live, hostdevs config) du deck dans `domaine`."""
    return (
        len(course.hostdevs_deck(domaine)),
        len(course.hostdevs_deck(domaine, inactive=True)),
    )


def _produit_vu(course, domaine):
    return any(p == PRODUIT for p, _id in course.info_usb(domaine))


def etape_mecanique(course):
    """Étape 2 : attach et detach par le CLI sur un domaine sans système."""
    dom = course.noms["meca"]
    bus_dev = f"{course.deck['busnum']}.{course.deck['devnum']}"
    course.controle("meca-define", course.definir(dom), dom)
    course.virsh("start", dom)
    course.controle(
        "meca-start", course.etat_domaine(dom) == "running", "running"
    )

    code, _ = course.cli("attach", dom, bus_dev, "--live")
    live = course.hostdevs_deck(dom)
    course.controle(
        "attach-live",
        code == 0
        and len(live) == 1
        and (live[0]["bus"], live[0]["dev"])
        == (course.deck["busnum"], course.deck["devnum"])
        and _produit_vu(course, dom),
        f"live : {live}",
    )
    code, _ = course.cli("attach", dom, bus_dev, "--live")
    course.controle(
        "attach-live-again",
        code == 0 and _compte(course, dom) == (1, 0),
        f"(live, config) = {_compte(course, dom)}",
    )
    code, _ = course.cli("attach", dom, bus_dev, "--config")
    course.controle(
        "attach-config",
        code == 0 and _compte(course, dom) == (1, 1),
        f"(live, config) = {_compte(course, dom)}",
    )
    code, _ = course.cli("attach", dom, bus_dev, "--live", "--config")
    course.controle(
        "attach-both-again",
        code == 0 and _compte(course, dom) == (1, 1),
        f"(live, config) = {_compte(course, dom)}",
    )
    code, _ = course.cli("detach", dom, f"{VID}:{PID}", "--live", "--config")
    course.controle(
        "detach-both",
        code == 0
        and _compte(course, dom) == (0, 0)
        and not _produit_vu(course, dom),
        f"(live, config) = {_compte(course, dom)}",
    )
    retour = attendre_que(
        lambda: pilote(course.deck["sysname"]) == "usbhid", DELAI_ENUMERATION
    )
    course.controle(
        "deck-back-to-host",
        retour,
        f"pilote {pilote(course.deck['sysname']) or '—'}",
    )
    code, _ = course.cli("detach", dom, f"{VID}:{PID}", "--live", "--config")
    course.controle(
        "detach-again",
        code == 0 and _compte(course, dom) == (0, 0),
        "rien à détacher, code 0",
    )
    return f"{dom} : 7 opérations, état final (0, 0)"


def etape_spice(course):
    """Étape 3 : la redirection SPICE posée sur un domaine VNC arrêté."""
    dom = course.noms["spice"]
    course.controle("spice-define", course.definir(dom), dom)
    code, xml = course.virsh("dumpxml", dom, "--inactive")
    try:
        plan = qu.spice_usbredir_plan(xml, dom, URI, allow_vendors=(VID,))
    except ValueError as souci:
        plan, xml = [], f"{souci}"
    course.controle(
        "spice-plan",
        code == 0 and len(plan) == 1 and bool(plan[0].get("changes")),
        "; ".join(plan[0]["changes"]) if plan else "aucun plan",
    )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".xml", prefix="erplibre-usb-pt-", delete=False
    ) as fh:
        fh.write(plan[0]["xml"])
    try:
        argv = [*course.virsh_prefixe, *qu.bind_xml(plan[0]["argv"], fh.name)]
        code, _ = course.lancer(argv, env=dict(os.environ, LC_ALL="C"))
    finally:
        os.unlink(fh.name)
    course.controle("spice-redefine", code == 0, "virsh define")
    _code, xml = course.virsh("dumpxml", dom, "--inactive")
    etat = qu.usb_state(xml)
    filtre = etat["redirfilter"]
    course.controle(
        "spice-config",
        qu.spice_first(etat)
        and "vnc" in etat["graphics"]
        and etat["redirdevs"].count("spicevmc") >= 2
        and etat["spice_channel"]
        and qu.usbredir_ready(etat)
        and bool(filtre)
        and filtre[0]["vendor"] == VID
        and filtre[0]["allow"]
        and not filtre[-1]["allow"]
        and qu.spice_usbredir_plan(xml, dom, URI, allow_vendors=(VID,)) == [],
        f"affichages {etat['graphics']}, redirdev {etat['redirdevs']},"
        f" filtre {[(r['vendor'], r['allow']) for r in filtre]}",
    )
    course.virsh("start", dom)
    course.controle(
        "spice-start", course.etat_domaine(dom) == "running", "running"
    )
    live = course.etat(dom)
    ids = [i for _p, i in course.info_usb(dom)]
    course.controle(
        "spice-redir-slots",
        qu.spice_first(live)
        and qu.usbredir_ready(live)
        and sum(1 for i in ids if i.startswith("redir")) >= 2,
        f"live : affichages {live['graphics']} ; info usb : {ids}",
    )
    course.virsh("destroy", dom)
    return f"{dom} : SPICE en tête, {len(ids)} emplacement(s) USB"


def _poser_autoreattach(course, domaine):
    """install-autoreattach puis « mapping add » du deck simulé vers
    `domaine`, chacun son contrôle."""
    course.hote(autoreattach=True)
    code, _ = course.cli("install-autoreattach", root=True)
    course.controle("autoreattach-install", code == 0, "install-autoreattach")
    poses = [c for c in chemins_autoreattach() if os.path.lexists(c)]
    try:
        with open(qu.UDEV_RULE_PATH, encoding="utf-8") as fh:
            regle = fh.read()
    except OSError:
        regle = ""
    course.controle(
        "autoreattach-files",
        len(poses) == len(chemins_autoreattach())
        and 'ACTION=="remove"' in regle
        and "fd9/*" in regle,
        f"{len(poses)}/{len(chemins_autoreattach())} chemins posés",
    )
    code, _ = course.cli(
        "mapping",
        "add",
        domaine,
        f"{VID}:{PID}",
        "--serial",
        SERIE,
        root=True,
    )
    try:
        with open(qu.MAPPING, encoding="utf-8") as fh:
            entrees = qu.mapping_loads(fh.read())
    except (OSError, ValueError):
        entrees = []
    course.controle(
        "mapping-add",
        code == 0
        and any(
            e["domain"] == domaine and e.get("serial") == SERIE
            for e in entrees
        ),
        f"{len(entrees)} entrée(s)",
    )


def _retirer_autoreattach(course):
    """« mapping remove » du deck simulé puis remove-autoreattach, --purge
    quand la correspondance n'existait pas avant la course. --no-restart :
    le service deck de l'hôte n'est pas l'affaire du test."""
    hote = course.rapport["hote"]
    code_m, _ = course.cli(
        "mapping",
        "remove",
        f"{VID}:{PID}",
        "--serial",
        SERIE,
        "--no-restart",
        root=True,
    )
    args = ["remove-autoreattach", "--no-restart"]
    if not hote.get("mapping_avant"):
        args.append("--purge")
    code_r, _ = course.cli(*args, root=True)
    if code_r == 0:
        course.hote(autoreattach=False)
    return code_m == 0 and code_r == 0


def _debrancher(course, nom_controle):
    """Débranche le deck, contrôle `nom_controle` ; rend (bus, dev,
    époque) de l'adresse quittée. L'époque précède d'une seconde
    l'écriture : le journal de l'unité se lit depuis elle."""
    bus, dev = course.deck["busnum"], course.deck["devnum"]
    depuis = time.time() - 1
    course.controle(
        nom_controle,
        course.branchement(False),
        f"UDC vidé, {bus:03d}.{dev:03d} quitté",
    )
    return bus, dev, depuis


def _rebrancher(course, prefixe, ancien):
    """Rebranche le deck ; contrôles `prefixe`-udc et
    `prefixe`-enumerated. Rend (deck au nouveau numéro, époque)."""
    depuis = time.time() - 1
    course.controle(
        f"{prefixe}-udc", course.branchement(True), f"UDC {course.udc}"
    )
    nouveau = course.attendre_deck(ancien_devnum=ancien)
    course.controle(
        f"{prefixe}-enumerated",
        bool(nouveau),
        f"nouveau numéro : {nouveau['devnum'] if nouveau else '—'}",
    )
    course.deck = nouveau
    return nouveau, depuis


def etape_rattachement(course):
    """Étape 4 : le rattachement automatique sur le domaine sans système."""
    dom = course.noms["meca"]
    _poser_autoreattach(course, dom)
    bus_dev = f"{course.deck['busnum']}.{course.deck['devnum']}"
    code, _ = course.cli("attach", dom, bus_dev, "--live")
    course.controle(
        "autoreattach-attach",
        code == 0 and len(course.hostdevs_deck(dom)) == 1,
        f"{bus_dev} → {dom}",
    )

    bus, dev, depuis = _debrancher(course, "unplug-udc")
    parti = attendre_que(
        lambda: not course.hostdevs_deck(dom) and not _produit_vu(course, dom),
        DELAI_UNITE,
    )
    course.controle(
        "unplug-detached",
        parti,
        "plus de <hostdev> live ni de deck dans « info usb »",
    )
    nom_unite = unite_detache(bus, dev)
    course.controle(
        "unplug-journal",
        course.attendre_journal(
            nom_unite, depuis, [qu.device_id(VID, PID, bus, dev), "OK"]
        ),
        nom_unite,
    )

    nouveau, depuis = _rebrancher(course, "replug", dev)
    adresse = (nouveau["busnum"], nouveau["devnum"])
    rattache = attendre_que(
        lambda: (
            [(h["bus"], h["dev"]) for h in course.hostdevs_deck(dom)]
            == [adresse]
            and _produit_vu(course, dom)
        ),
        DELAI_UNITE,
    )
    course.controle(
        "replug-reattached",
        rattache and pilote(nouveau["sysname"]) != "usbhid",
        f"<hostdev> live à {adresse[0]:03d}.{adresse[1]:03d},"
        f" pilote hôte {pilote(nouveau['sysname']) or '—'}",
    )
    nom_unite = unite_rattache(nouveau["sysname"])
    course.controle(
        "replug-journal",
        course.attendre_journal(
            nom_unite, depuis, [qu.device_id(VID, PID, *adresse), "OK"]
        ),
        nom_unite,
    )

    course.controle(
        "autoreattach-remove", _retirer_autoreattach(course), "retiré"
    )
    restes = restes_autoreattach(course.rapport["hote"])
    course.controle(
        "autoreattach-nothing-left",
        not restes,
        f"restes : {restes or 'aucun'}",
    )
    code, _ = course.cli("detach", dom, f"{VID}:{PID}", "--live")
    rendu = attendre_que(
        lambda: pilote(nouveau["sysname"]) == "usbhid", DELAI_ENUMERATION
    )
    course.controle(
        "deck-released",
        code == 0 and rendu and not course.hostdevs_deck(dom),
        "deck rendu à usbhid",
    )
    return f"{dev:03d} → {nouveau['devnum']:03d} rattaché ; rien ne reste"


def _usb_invite(course, cible):
    code, sortie = course.lancer(ssh_base(cible) + [CMD_USB_INVITE], delai=60)
    return parse_usb_invite(sortie) if code == 0 else []


def etape_invite(course):
    """Étape 5 : une vraie Debian reçoit le deck, et le perd puis le
    retrouve au débranchement."""
    dom = course.noms["invite"]
    # Les domaines sans système ont fini leur travail : arrêtés, ils
    # rendent leur mémoire et ne peuvent plus tenir le deck.
    for autre in (course.noms["meca"], course.noms["spice"]):
        if course.etat_domaine(autre) == "running":
            course.virsh("destroy", autre)
    # Une étape précédente tombée entre un débranchement et son
    # rebranchement laisse le gadget hors UDC : l'invité doit le trouver
    # branché à sa création.
    course.controle("guest-deck-plugged", course.assurer_branche(), "")
    if Descente.uuid_libvirt(dom):
        course.controle("guest-vm-name-free", False, f"{dom} existe déjà")
    argv = ["sudo"] + argv_deploiement(dom, cle_publique(), drapeaux_cache())
    course.dire("    $ " + shlex.join(argv))
    # Le nom au rapport AVANT la création : une création interrompue à
    # mi-chemin laisse un domaine que --detruire doit pouvoir nommer.
    etage = course.inscrire(dom, alias=dom)
    try:
        with open(course.journal, "a", encoding="utf-8") as fh:
            fini = subprocess.run(
                argv,
                stdout=fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=DELAI_CREATION,
            )
        ok = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        course.dire(f"    ✗ déploiement interrompu : {souci}")
        ok = False
    etage["uuid"] = Descente.uuid_libvirt(dom)
    course.ecrire()
    course.controle("guest-vm", ok and bool(etage["uuid"]), dom)
    joint = bool(adresse_de(dom, course.journal)) and attendre_ssh(
        dom, course.journal, DELAI_SSH
    )
    course.controle("guest-ssh", joint, dom)

    deck = attendre_que(
        lambda: deck_simule(_usb_invite(course, dom)), 30, pas=3
    )
    course.controle(
        "guest-sees-deck",
        bool(deck)
        and (deck["vid"], deck["pid"]) == (VID, PID)
        and deck["product"] == PRODUIT,
        f"invité : {deck}",
    )
    code, _ = course.lancer(
        ssh_base(dom)
        + [
            f"rm -rf {DOSSIER_INVITE} && mkdir -p {DOSSIER_INVITE}"
            f" && tar -x -C {DOSSIER_INVITE}"
        ],
        entree=archive_statut(),
        delai=60,
    )
    code2, sortie = course.lancer(
        ssh_base(dom) + [commande_decks_invite()], delai=60
    )
    vu = deck_simule(liste_json(sortie) if code2 == 0 else [])
    course.controle(
        "guest-plugged-decks",
        code == 0
        and bool(vu)
        and vu.get("product") == PRODUIT
        and vu.get("id_product") == PID,
        f"plugged_decks() : {vu}",
    )

    _poser_autoreattach(course, dom)
    bus, dev, depuis = _debrancher(course, "guest-unplug-udc")
    parti = attendre_que(
        lambda: (
            not course.hostdevs_deck(dom)
            and not deck_simule(_usb_invite(course, dom))
        ),
        DELAI_INVITE_USB,
        pas=2,
    )
    course.controle(
        "guest-unplug",
        parti
        and course.attendre_journal(
            unite_detache(bus, dev), depuis, [qu.device_id(VID, PID, bus, dev)]
        ),
        "le deck a quitté le sysfs de l'invité",
    )
    nouveau, _depuis = _rebrancher(course, "guest-replug", dev)
    revenu = attendre_que(
        lambda: deck_simule(_usb_invite(course, dom)),
        DELAI_INVITE_USB,
        pas=2,
    )
    course.controle(
        "guest-replug-seen",
        bool(revenu)
        and [(h["bus"], h["dev"]) for h in course.hostdevs_deck(dom)]
        == [(nouveau["busnum"], nouveau["devnum"])],
        f"invité : {revenu} ; hôte {nouveau['busnum']:03d}."
        f"{nouveau['devnum']:03d}",
    )
    return f"{dom} : deck vu, perdu puis retrouvé ({revenu['sysname']})"


def etape_statut(course):
    """Étape 6 : l'état d'ERPLibre Home sur l'hôte nomme la VM."""
    from script.todo import erplibre_home_service as service
    from script.todo import erplibre_home_status as statut
    from script.todo.todo_i18n import t

    dom = course.noms["invite"]
    faits = statut.collect(service.run_command, RACINE)
    deck = deck_simule(faits["decks"]) or {}
    course.controle(
        "status-vm-named",
        deck.get("vm") == dom,
        f"vm={deck.get('vm')!r}, pilote {deck.get('driver')!r},"
        f" propriétaire {deck.get('owner_uid')}",
    )
    attendu = f"{t('passed to VM')} {dom}"
    lignes = [
        ligne for ligne in statut.status_lines(faits) if attendu in ligne
    ]
    course.controle("status-line", bool(lignes), lignes[0] if lignes else "")
    return lignes[0]


FONCTIONS = {
    "emulated-deck": etape_deck,
    "libvirt-mechanics": etape_mecanique,
    "spice": etape_spice,
    "auto-reattach": etape_rattachement,
    "guest": etape_invite,
    "host-status": etape_statut,
}


# ---------------------------------------------------------------------------
# Défaire : la fin de course et --detruire partagent ce code.
# ---------------------------------------------------------------------------


def defaire_hote(rapport, ecrire, journal, garder_vm=False):
    """Défait ce que `rapport` dit posé, dans l'ordre qui le permet :
    rattachement automatique, domaines (sauf `garder_vm`), gadget,
    modules. `ecrire()` récrit le rapport après chaque pièce défaite, si
    bien qu'un défaire interrompu ne refait pas ce qui l'a été. Rend la
    liste de ce qui reste debout."""
    hote = rapport["hote"]
    debout = []

    def lancer(argv, entree=None):
        try:
            fini = subprocess.run(
                argv, input=entree, capture_output=True, text=True, timeout=120
            )
        except (OSError, subprocess.SubprocessError) as souci:
            dire(f"    ✗ {shlex.join(argv)} : {souci}", journal)
            return False
        if fini.returncode:
            dire(
                f"    ✗ {shlex.join(argv)} → {fini.returncode} :"
                f" {(fini.stderr or fini.stdout).strip()[:200]}",
                journal,
            )
        return fini.returncode == 0

    if hote.get("autoreattach"):
        lancer(
            argv_cli(
                "mapping",
                "remove",
                f"{VID}:{PID}",
                "--serial",
                SERIE,
                "--no-restart",
                root=True,
            )
        )
        args = ["remove-autoreattach", "--no-restart"]
        if not hote.get("mapping_avant"):
            args.append("--purge")
        if lancer(argv_cli(*args, root=True)):
            dire("    ✓ rattachement automatique retiré", journal)
            hote["autoreattach"] = False
            ecrire()
        else:
            debout.append("rattachement automatique")

    if not garder_vm:
        for etage in list(rapport["etages"]):
            if detruire_etage1(
                journal, etage["nom"], attendu=etage.get("uuid") or None
            ):
                if etage.get("alias"):
                    retirer_alias({"etages": [etage]}, journal, NOM_BASE)
                rapport["etages"].remove(etage)
                ecrire()
            else:
                debout.append(etage["nom"])
        if hote.get("gadget"):
            if lancer(["sudo", "-n", "sh", "-s"], script_retrait_gadget()):
                dire(f"    ✓ gadget {GADGET}", journal)
                hote["gadget"] = ""
                ecrire()
            else:
                debout.append(f"gadget {GADGET}")
        charges = [m for m in hote.get("modules_charges") or []]
        restants = []
        for module in charges:
            if not os.path.isdir(f"/sys/module/{module}"):
                continue
            if not lancer(["sudo", "-n", "rmmod", module]):
                restants.append(module)
        if charges:
            dire(
                f"    {'✗' if restants else '✓'} modules :"
                f" {restants or charges} {'restent' if restants else ''}",
                journal,
            )
        hote["modules_charges"] = restants
        ecrire()
        debout += [f"module {m}" for m in restants]
    return debout


def a_defaire(rapport):
    """Vrai quand `rapport` nomme quelque chose encore debout."""
    hote = rapport.get("hote") or {}
    return bool(
        rapport.get("etages")
        or hote.get("gadget")
        or hote.get("autoreattach")
        or hote.get("modules_charges")
    )


def dernier_rapport_a_defaire(dossier=None):
    """(chemin, rapport) du rapport le plus récent de cette pile qui nomme
    quelque chose à défaire, ou ("", {}). Un rapport à blanc n'a rien
    créé ; celui d'une course VIVANTE est écarté : défaire sous elle
    retirerait le deck qu'elle est en train de mesurer."""
    dossier = dossier or os.path.expanduser("~/.erplibre/longtest")
    try:
        fichiers = sorted(
            f
            for f in os.listdir(dossier)
            if f.startswith(NOM_BASE + "-") and f.endswith(".json")
        )
    except OSError:
        return "", {}
    for nom in reversed(fichiers):
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                rapport = json.load(fh)
        except (OSError, ValueError):
            continue
        if rapport.get("outil") != OUTIL or rapport.get("dry_run"):
            continue
        if descente_vivante(rapport.get("pid")):
            dire(f"  ⏳ course EN COURS ({rapport['pid']}) : {nom} ignoré")
            continue
        if a_defaire(rapport):
            return chemin, rapport
    return "", {}


def detruire(journal, dry_run=False):
    """--detruire : défait ce que le dernier rapport nomme, après une
    confirmation « OUI ». Le gadget de cette pile, s'il vit sans rapport
    qui le nomme, est défait aussi : son nom est à elle seule."""
    autres = autre_descente()
    if autres:
        dire(
            f"  ⛔ un test long tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera défait.",
            journal,
        )
        return 1
    chemin, rapport = dernier_rapport_a_defaire()
    orphelin = gadget_vivant()
    if not rapport and not orphelin:
        dire("  aucun rapport à défaire : rien à faire.", journal)
        return 0
    if not rapport:
        rapport = {"hote": {"gadget": f"{CONFIGFS}/{GADGET}"}, "etages": []}
    else:
        dire(f"  rapport : {chemin}", journal)
    hote = rapport["hote"]
    if orphelin:
        hote["gadget"] = f"{CONFIGFS}/{GADGET}"
    for etage in rapport.get("etages") or []:
        dire(
            f"    domaine  {etage['nom']} ({etage.get('uuid') or '?'})",
            journal,
        )
    if hote.get("autoreattach"):
        dire("    rattachement automatique (règle, unités, libexec)", journal)
    if hote.get("gadget"):
        dire(f"    gadget   {hote['gadget']}", journal)
    if hote.get("modules_charges"):
        dire(f"    modules  {', '.join(hote['modules_charges'])}", journal)
    if dry_run:
        dire("\n  --dry-run : rien ne sera défait.", journal)
        return 0
    if input("\n  Défaire tout cela ? (tapez OUI) : ").strip() != "OUI":
        dire("  annulé.", journal)
        return 1
    rafraichir_sudo(journal)

    def ecrire():
        if chemin:
            with open(chemin, "w", encoding="utf-8") as fh:
                json.dump(rapport, fh, indent=2)

    debout = defaire_hote(rapport, ecrire, journal)
    if debout:
        dire(f"\n  ⚠ encore debout : {', '.join(debout)}", journal)
        return 1
    dire("\n  tout est défait.", journal)
    return 0


# ---------------------------------------------------------------------------
# Le plan, les prérequis, la course.
# ---------------------------------------------------------------------------


def annoncer(course, sans_invite):
    """Le plan : chaque étape, ce dont elle dépend, et les commandes qui
    créent quelque chose."""
    d = course.dire
    d(f"  deck simulé : {VID}:{PID} « {PRODUIT} », série {SERIE}")
    d(f"  gadget : {CONFIGFS}/{GADGET}, modules {', '.join(MODULES)}")
    d("  domaines :")
    for role, nom in course.noms.items():
        d(f"    {role:<7} {nom}")
    d("  étapes :")
    for rang, etape in enumerate(ETAPES, 1):
        apres = ", ".join(DEPENDANCES[etape]) or "—"
        saut = (
            " (sautée : --sans-invite)"
            if (sans_invite and etape in ETAPES_INVITE)
            else ""
        )
        d(f"    {rang}. {etape:<18} {DESCRIPTION[etape]}{saut}")
        d(f"       après : {apres}")


def montrer_commandes(course):
    """Les commandes de la course, telles qu'elles partiront (--dry-run)."""
    d = course.dire
    d("  commandes :")
    d(f"    $ sudo -n modprobe -a {' '.join(MODULES)}")
    script = script_sh(operations_gadget("dummy_udc.0"))
    d(f"    $ sudo -n sh -s   # gadget, {len(script.splitlines())} lignes")
    meca = course.noms["meca"]
    for args in (
        ("attach", meca, "BUS.DEV", "--live"),
        ("attach", meca, "BUS.DEV", "--config"),
        ("detach", meca, f"{VID}:{PID}", "--live", "--config"),
    ):
        d(f"    $ {shlex.join(argv_cli(*args))}")
    for args in (
        ("install-autoreattach",),
        ("mapping", "add", meca, f"{VID}:{PID}", "--serial", SERIE),
        ("remove-autoreattach", "--no-restart", "--purge"),
    ):
        d(f"    $ {shlex.join(argv_cli(*args, root=True))}")
    # Le plan n'écrit rien : la clé jetable n'y est que nommée.
    deploiement = ["sudo"] + argv_deploiement(
        course.noms["invite"], cle_publique(creer=False), drapeaux_cache()
    )
    d(f"    $ {shlex.join(deploiement)}")
    d(f"    invité : {CMD_USB_INVITE}")
    d(f"    invité : {commande_decks_invite()}")


def prerequis(course):
    """[raison] de refuser la course, [] quand l'hôte s'y prête. Chaque
    refus protège ce que la course retirerait sans l'avoir posé, ou ce
    qui fausserait le verdict."""
    raisons = []
    if os.uname().machine != "x86_64":
        raisons.append("le domaine de test est q35 : hôte x86_64 seulement")
    if not os.path.exists("/dev/kvm"):
        raisons.append("/dev/kvm absent")
    if not os.path.ismount(os.path.dirname(CONFIGFS)):
        raisons.append("configfs n'est pas monté sur /sys/kernel/config")
    for module in MODULES:
        fini = subprocess.run(
            ["modinfo", "-n", module], capture_output=True, text=True
        )
        if fini.returncode:
            raisons.append(f"module {module} introuvable")
    if gadget_vivant():
        raisons.append(f"{CONFIGFS}/{GADGET} existe déjà : --detruire d'abord")
    pris = gadgets_sur_dummy()
    if pris:
        raisons.append(f"l'UDC de dummy_hcd est pris par {', '.join(pris)}")
    reels = [d for d in qu.host_usb_devices() if d.get("vid") == VID]
    if reels:
        raisons.append(
            "un deck réel est branché ("
            + ", ".join(qu.device_line(d) for d in reels)
            + ") : il répondrait à 0fd9:0080 à la place du deck simulé"
        )
    poses = [c for c in chemins_autoreattach() if os.path.lexists(c)]
    if poses:
        raisons.append(
            "le rattachement automatique est déjà posé ("
            + ", ".join(poses)
            + ") : le retrait du test l'emporterait"
        )
    try:
        with open(qu.MAPPING, encoding="utf-8") as fh:
            entrees = qu.mapping_loads(fh.read())
    except OSError:
        entrees = []
    except ValueError:
        entrees = ["?"]
    if entrees:
        raisons.append(f"{qu.MAPPING} porte déjà des entrées")
    fini = subprocess.run(
        ["systemctl", "--user", "is-active", "erplibre-home-streamdeck"],
        capture_output=True,
        text=True,
    )
    if fini.stdout.strip() == "active":
        raisons.append(
            "le service deck d'ERPLibre Home tourne : il prendrait le deck"
            " simulé"
        )
    if not os.access(PYTHON_VENV, os.X_OK):
        raisons.append(f"{PYTHON_VENV} absent : deploy_qemu.py s'y lance")
    autres = autre_descente()
    if autres:
        raisons.append(
            f"un autre test long tourne ({', '.join(map(str, autres))})"
        )
    return raisons


def choisir_virsh(course):
    """Le préfixe de virsh : rien quand le compte joint URI (groupe
    libvirt), « sudo -n » sinon."""
    fini = subprocess.run(
        ["virsh", "--connect", URI, "uri"], capture_output=True, text=True
    )
    course.virsh_prefixe = [] if fini.returncode == 0 else ["sudo", "-n"]


def mener_etapes(course):
    """Chaque étape dans l'ordre, sautée quand une dépendance a manqué.
    Rend les lignes du rapport, une par étape."""
    verdicts = {}
    for etape in ETAPES:
        debut = time.time()
        ligne = {"etape": etape, "verdict": "PASSED", "detail": ""}
        manque = bloquee_par(etape, verdicts)
        if course.args.sans_invite and etape in ETAPES_INVITE:
            ligne.update(verdict="SKIPPED", detail="--sans-invite")
        elif manque:
            ligne.update(verdict="SKIPPED", detail=f"after {','.join(manque)}")
        else:
            course.dire(f"  ── {etape} : {DESCRIPTION[etape]}")
            try:
                ligne["preuve"] = FONCTIONS[etape](course)
            except Echec as echec:
                ligne.update(verdict="FAILED", detail=str(echec))
            except Exception as souci:  # noqa: BLE001 - une étape, pas tout
                course.lus = []
                ligne.update(
                    verdict="FAILED",
                    detail=f"exception {type(souci).__name__}",
                )
                course.dire(f"    ✗ {type(souci).__name__} : {souci}")
        # Ce que l'étape a lancé après son dernier contrôle (un arrêt de
        # domaine) va au journal sous elle, pas sous l'étape suivante.
        for commande, code, _sortie in course.lus:
            course.dire(f"       $ {commande}  → {code}")
        course.lus = []
        ligne["duree_s"] = round(time.time() - debut, 1)
        verdicts[etape] = ligne["verdict"]
        course.rapport["etapes"].append(ligne)
        course.ecrire()
        marque = {"PASSED": "✅", "SKIPPED": "⚪"}.get(ligne["verdict"], "❌")
        course.dire(f"  {marque} {etape} : {verdict_texte(ligne)}")
    return course.rapport["etapes"]


def nettoyer(course):
    """Le nettoyage de fin de course, verdict « cleanup » : tout ce que
    le rapport nomme est défait (domaines compris, sauf --garder), puis
    l'hôte est relu pour n'y trouver aucun reste."""
    debut = time.time()
    course.dire("  ── cleanup")
    restes = []
    if not course.args.garder:
        restes += defaire_hote(course.rapport, course.ecrire, course.journal)
        restes += restes_autoreattach(course.rapport["hote"])
        if gadget_vivant():
            restes.append(f"{CONFIGFS}/{GADGET}")
        for nom in course.noms.values():
            if Descente.uuid_libvirt(nom):
                restes.append(f"domaine {nom}")
    ligne = {
        "etape": "cleanup",
        "verdict": "FAILED" if restes else "PASSED",
        "detail": ", ".join(sorted(set(restes)))[:200] if restes else "",
        "duree_s": round(time.time() - debut, 1),
    }
    if course.args.garder:
        ligne.update(verdict="SKIPPED", detail="--garder")
    course.rapport["etapes"].append(ligne)
    course.ecrire()
    marque = {"PASSED": "✅", "SKIPPED": "⚪"}.get(ligne["verdict"], "❌")
    course.dire(f"  {marque} cleanup : {verdict_texte(ligne)}")


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--sans-invite",
        action="store_true",
        help="étapes 1 à 4 seulement : ni Debian ni état de l'hôte",
    )
    parseur.add_argument(
        "--garder",
        action="store_true",
        help="garder domaines, gadget et rattachement après la course",
    )
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal, chemin, horodatage = chemins_de_course()
    if args.detruire:
        return detruire(journal, dry_run=args.dry_run)

    if args.dry_run:
        chemin = chemin[:-5] + "-dryrun.json"
    course = Course(args, journal, chemin, horodatage)
    course.dire(f"  journal : {journal}")
    annoncer(course, args.sans_invite)
    if args.dry_run:
        montrer_commandes(course)
        course.ecrire()
        course.dire(f"  rapport : {chemin}")
        course.dire("  --dry-run : rien n'a été créé.")
        return 0

    raisons = prerequis(course)
    if not raisons and not rafraichir_sudo(journal):
        raisons.append("sudo ne répond pas sans mot de passe")
    if raisons:
        for raison in raisons:
            course.dire(f"  ✗ {raison}")
        course.dire("  la course ne part pas : rien n'a été touché.")
        return 1
    choisir_virsh(course)
    course.ecrire()
    course.dire(f"  rapport : {chemin}")
    try:
        mener_etapes(course)
    finally:
        nettoyer(course)
    for ligne in resume(course.rapport["etapes"]):
        course.dire(ligne)
    if course.args.garder:
        course.dire("  tout est gardé : --detruire le défait")
    return code_sortie(course.rapport["etapes"])


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
