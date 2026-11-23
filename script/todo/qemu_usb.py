#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Périphériques USB de l'hôte passés à une VM libvirt : logique pure.

Deux voies mènent un périphérique USB — un Stream Deck d'abord — dans une
VM :

- <hostdev> : le périphérique est branché sur l'HÔTE LIBVIRT, et QEMU le
  prend à l'hôte. virsh attach-device / detach-device, en live, en config,
  ou les deux.
- SPICE usbredir : le périphérique est branché sur le poste qui ouvre
  virt-viewer, et spice-gtk le transporte dans la session SPICE jusqu'aux
  emplacements <redirdev type='spicevmc'> de la VM.

Ce module ne lance RIEN. Il lit sysfs et des textes XML, et rend des
argv et des plans ; le menu (qemu_usb_menu.py) et le CLI autonome
(script/qemu/usb_qemu.py) les exécutent, sous sudo ou en root. Le plan se
vérifie donc sans hyperviseur ni périphérique.

Le CLI charge ce fichier par son chemin, depuis le dépôt ou depuis sa copie
dans LIBEXEC_DIR, hors de tout paquet Python : à l'import, seule la
bibliothèque standard est requise, et t() comme DECK_VENDOR ont un repli.

Contrat des plans, commun à usb_plan, reattach_plan et spice_usbredir_plan :
une liste de dicts, dans l'ordre d'exécution.

- {"what": str, "view": "live"|"config"|"", "argv": [...], "xml": str} :
  une commande à lancer. argv porte XML_PLACEHOLDER à la place du fichier
  XML : virsh ne lit le XML que depuis un FICHIER. L'appelant écrit "xml"
  dans un fichier temporaire, remplace le jeton par bind_xml(argv, chemin),
  et ajoute sudo devant pour qemu:///system quand il n'est pas root. Avec
  qemu+ssh, virsh lit le fichier localement et l'envoie par le RPC : aucune
  copie sur l'hyperviseur.
- {"what": str, "view": ..., "skip": str} : demandé, mais sans objet, avec
  la raison. Rien n'est lancé.

Une liste sans entrée "argv" ne lance rien.
"""

from __future__ import annotations

import glob
import io
import json
import os
import re
import xml.etree.ElementTree as ET

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - chargé hors du dépôt, ou en root

    def t(key: str) -> str:
        return key


try:
    from script.todo.erplibre_home_status import DECK_VENDOR
except Exception:  # pragma: no cover - même repli
    DECK_VENDOR = "0fd9"


# URI par défaut : les domaines du parc vivent dans qemu:///system, jamais
# dans qemu:///session.
DEFAULT_URI = "qemu:///system"

# Jeton que les argv portent à la place du fichier XML ; bind_xml() le
# remplace. Lisible tel quel quand le menu affiche la commande avant de la
# lancer.
XML_PLACEHOLDER = "<xml-file>"

# Vendeur des concentrateurs racines du noyau (Linux Foundation) et classe
# USB des concentrateurs : ni l'un ni l'autre ne se passe à une VM.
ROOT_HUB_VENDOR = "1d6b"
HUB_CLASS = "09"

# Contrôleur USB posé quand la VM n'en a aucun : celui que virt-install
# choisit pour un invité qui connaît l'USB 3, et le nombre de ports qu'il
# lui donne.
USB_CONTROLLER_MODEL = "qemu-xhci"
USB_CONTROLLER_PORTS = "15"

# Canal de l'agent SPICE (presse-papiers, taille de l'écran). virt-install le
# pose avec tout affichage SPICE ; la redirection USB n'en dépend pas, mais
# une VM SPICE sans lui perd ce que virt-viewer offre d'autre.
SPICE_CHANNEL = "com.redhat.spice.0"

# Rattachement automatique au rebranchement, sur l'hôte libvirt.
MAPPING = "/etc/erplibre/usb-passthrough.json"
UDEV_RULE_NAME = "85-erplibre-usb-passthrough.rules"
UDEV_RULE_PATH = "/etc/udev/rules.d/" + UDEV_RULE_NAME
UNIT_NAME = "erplibre-usb-reattach@.service"
UNIT_PATH = "/etc/systemd/system/" + UNIT_NAME
# Le CLI et ce module sont COPIÉS hors du dépôt : une unité root n'exécute
# pas un fichier que l'utilisateur peut réécrire dans son checkout.
LIBEXEC_DIR = "/usr/local/libexec/erplibre-usb/"
LIBEXEC_CLI = LIBEXEC_DIR + "usb_qemu.py"
LIBEXEC_LIB = LIBEXEC_DIR + "qemu_usb.py"

# Espaces de noms que libvirt et virt-install écrivent dans un domaine.
# ElementTree renomme en ns0, ns1… tout préfixe qu'il ne connaît pas ; les
# déclarer garde un XML redéfini lisible et identique au reste.
_KNOWN_NS = {
    "qemu": "http://libvirt.org/schemas/domain/qemu/1.0",
    "libosinfo": "http://libosinfo.org/xmlns/libvirt/domain/1.0",
}

_HEX4 = re.compile(r"^(?:0x)?([0-9a-fA-F]{1,4})$")
_VIDPID = re.compile(
    r"^\s*(?:0x)?([0-9a-fA-F]{4}):(?:0x)?([0-9a-fA-F]{4})\s*$"
)
_BUSDEV = re.compile(r"^\s*(\d{1,3})\.(\d{1,3})\s*$")
# Nom sysfs d'un périphérique USB : bus-port[.port…]. Les interfaces
# (« 3-2:1.0 ») et les racines (« usb3 ») n'y répondent pas, et aucun « / »
# ni « .. » ne passe : le nom vient d'udev et finit dans un chemin lu en
# root.
_SYSNAME = re.compile(r"^\d{1,3}-\d{1,3}(?:\.\d{1,3}){0,6}$")


# ---------------------------------------------------------------------------
# Identifiants


def norm_hex(value) -> str:
    """« 0x0FD9 », « fd9 », 0xfd9 -> « 0fd9 » ; "" quand ce n'est pas un
    identifiant USB de 16 bits."""
    if isinstance(value, int):
        return f"{value:04x}" if 0 <= value <= 0xFFFF else ""
    m = _HEX4.match(str(value or "").strip())
    return m.group(1).lower().zfill(4) if m else ""


def _int(value):
    try:
        return int(str(value).strip(), 10)
    except (TypeError, ValueError):
        return None


def device_id(vid, pid, bus=None, dev=None) -> str:
    """« 0fd9:0080 », suivi de « @ 003.005 » quand l'adresse épingle le
    périphérique — la forme que virt-install accepte pour --hostdev."""
    text = f"{norm_hex(vid) or '?'}:{norm_hex(pid) or '?'}"
    if bus is not None and dev is not None:
        text += f" @ {int(bus):03d}.{int(dev):03d}"
    return text


def device_label(dev: dict) -> str:
    """Nom lisible : fabricant et produit lus dans sysfs, sinon VID:PID.

    Aucun catalogue de PID : le nom que le périphérique annonce suffit, et
    il suit les nouveaux modèles sans qu'on touche au code."""
    maker, product = dev.get("manufacturer") or "", dev.get("product") or ""
    if maker and product.startswith(maker):
        maker = ""
    parts = [p for p in (maker, product) if p]
    return " ".join(parts) or device_id(dev.get("vid"), dev.get("pid"))


def device_line(dev: dict) -> str:
    """Une ligne de liste : « 003.005  0fd9:0080  Nom  [série] »."""
    line = (
        f"{dev.get('busnum', 0):03d}.{dev.get('devnum', 0):03d}  "
        f"{dev.get('vid')}:{dev.get('pid')}  {device_label(dev)}"
    )
    if dev.get("serial"):
        line += f"  [{dev['serial']}]"
    return line


# ---------------------------------------------------------------------------
# Hôte : sysfs


def _lire(chemin):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def valid_sysname(name) -> bool:
    """Vrai pour un nom sysfs de périphérique USB (« 3-2 », « 1-4.1 »)."""
    return bool(_SYSNAME.match(str(name or "")))


def read_usb_device(sysname: str, sysfs_root: str = "/sys"):
    """Le périphérique `sysname` lu sous sysfs_root/bus/usb/devices, ou
    None : nom invalide, dossier absent, identifiants illisibles.

    Rend un dict : sysname, busnum:int, devnum:int, vid, pid (4 hex
    minuscules), product, manufacturer, serial ("" quand absents),
    device_class (2 hex, "" si absent), is_deck (vendeur DECK_VENDOR).
    Les concentrateurs ne sont PAS filtrés ici : is_usable() le fait.
    """
    if not valid_sysname(sysname):
        return None
    dossier = os.path.join(sysfs_root, "bus/usb/devices", sysname)
    vid = norm_hex(_lire(os.path.join(dossier, "idVendor")))
    pid = norm_hex(_lire(os.path.join(dossier, "idProduct")))
    busnum = _int(_lire(os.path.join(dossier, "busnum")))
    devnum = _int(_lire(os.path.join(dossier, "devnum")))
    if not vid or not pid or busnum is None or devnum is None:
        return None
    return {
        "sysname": sysname,
        "busnum": busnum,
        "devnum": devnum,
        "vid": vid,
        "pid": pid,
        "product": _lire(os.path.join(dossier, "product")),
        "manufacturer": _lire(os.path.join(dossier, "manufacturer")),
        "serial": _lire(os.path.join(dossier, "serial")),
        "device_class": _lire(os.path.join(dossier, "bDeviceClass")).lower(),
        "is_deck": vid == DECK_VENDOR,
    }


def is_usable(dev: dict) -> bool:
    """Faux pour un concentrateur racine (1d6b) ou un concentrateur
    (bDeviceClass 09) : passer l'un ou l'autre ne mène à rien."""
    return (
        dev.get("vid") != ROOT_HUB_VENDOR
        and dev.get("device_class") != HUB_CLASS
    )


def sort_devices(devs):
    """Decks (vendeur DECK_VENDOR) d'abord, puis par bus et numéro."""
    return sorted(
        devs,
        key=lambda d: (not d.get("is_deck"), d["busnum"], d["devnum"]),
    )


def host_usb_devices(sysfs_root: str = "/sys") -> list:
    """Les périphériques USB passables de l'hôte, decks en tête.

    Balaie sysfs_root/bus/usb/devices/* : les interfaces (« 3-2:1.0 ») et
    les racines (« usb3 ») n'ont pas un nom de périphérique et sont
    écartées par leur nom ; les concentrateurs par is_usable(). lsusb n'est
    pas requis. Chaque dict a la forme de read_usb_device().
    """
    devs = []
    motif = os.path.join(sysfs_root, "bus/usb/devices/*")
    for dossier in glob.glob(motif):
        dev = read_usb_device(os.path.basename(dossier), sysfs_root)
        if dev and is_usable(dev):
            devs.append(dev)
    return sort_devices(devs)


# ---------------------------------------------------------------------------
# Sélection


def parse_selector(text):
    """Sélecteur tapé par l'utilisateur -> dict, ou None s'il ne se lit
    pas.

    - « 0fd9:0080 » (préfixes 0x admis) -> {"vid": "0fd9", "pid": "0080"}
    - « 3.5 », « 003.005 » (bus.périphérique, la forme de virt-install)
      -> {"bus": 3, "dev": 5}

    « 3-5 » est refusé exprès : c'est la forme d'un nom sysfs, où le
    second nombre est un PORT et non un numéro de périphérique.
    """
    m = _VIDPID.match(str(text or ""))
    if m:
        return {"vid": m.group(1).lower(), "pid": m.group(2).lower()}
    m = _BUSDEV.match(str(text or ""))
    if m:
        return {"bus": int(m.group(1)), "dev": int(m.group(2))}
    return None


def find_devices(
    devs, vid=None, pid=None, serial=None, bus=None, dev=None
) -> list:
    """Les périphériques de `devs` qui répondent à tous les critères
    donnés (None = indifférent), dans l'ordre de `devs`."""
    vid, pid = norm_hex(vid) if vid else None, norm_hex(pid) if pid else None
    found = []
    for d in devs:
        if vid and d.get("vid") != vid:
            continue
        if pid and d.get("pid") != pid:
            continue
        if serial and d.get("serial") != serial:
            continue
        if bus is not None and d.get("busnum") != int(bus):
            continue
        if dev is not None and d.get("devnum") != int(dev):
            continue
        found.append(d)
    return found


def select_devices(devs, text) -> list:
    """Les périphériques que désigne le sélecteur `text` ([] s'il ne se lit
    pas ou ne désigne rien). Plus d'un résultat : sélecteur ambigu."""
    sel = parse_selector(text)
    if not sel:
        return []
    return find_devices(devs, **sel)


def ambiguous(devs, vid, pid) -> bool:
    """Vrai quand plusieurs périphériques branchés portent ce VID:PID.

    libvirt et virt-install refusent alors un <hostdev> par VID:PID seul
    (« corresponds to multiple node devices ») : il faut l'adresse."""
    return len(find_devices(devs, vid=vid, pid=pid)) > 1


def want_for(dev: dict, devs) -> dict:
    """Demande d'attachement pour le périphérique `dev` choisi dans `devs`.

    VID:PID seul quand il est unique : la définition survit au
    rebranchement, qui change le numéro de périphérique. Épinglée par
    bus/numéro quand deux périphériques identiques sont branchés — la
    seule forme que libvirt accepte alors.

    Rend {"vid", "pid", "bus": int|None, "dev": int|None}.
    """
    pin = ambiguous(devs, dev["vid"], dev["pid"])
    return {
        "vid": dev["vid"],
        "pid": dev["pid"],
        "bus": dev["busnum"] if pin else None,
        "dev": dev["devnum"] if pin else None,
    }


# ---------------------------------------------------------------------------
# XML : construction


def hostdev_xml(vid=None, pid=None, bus=None, dev=None, optional=True) -> str:
    """Un <hostdev> USB pour virsh attach-device / detach-device.

    Source par vendor+product, par adresse bus/device, ou les deux ; il en
    faut au moins une. optional pose startupPolicy='optional' : la VM
    démarre même si le périphérique est absent au lieu d'échouer, ce qui
    compte pour une définition --config. Pour un détachement, libvirt
    retrouve le <hostdev> par l'adresse quand elle est donnée, sinon par
    vendor+product : le XML doit reprendre ce que la vue porte.
    """
    vid = norm_hex(vid) if vid else ""
    pid = norm_hex(pid) if pid else ""
    pinned = bus is not None and dev is not None
    if not (vid and pid) and not pinned:
        raise ValueError("hostdev_xml: vid+pid or bus+dev required")
    policy = " startupPolicy='optional'" if optional else ""
    lines = [
        "<hostdev mode='subsystem' type='usb' managed='yes'>",
        f"  <source{policy}>",
    ]
    if vid and pid:
        lines += [
            f"    <vendor id='0x{vid}'/>",
            f"    <product id='0x{pid}'/>",
        ]
    if pinned:
        lines.append(f"    <address bus='{int(bus)}' device='{int(dev)}'/>")
    lines += ["  </source>", "</hostdev>", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# XML : lecture


def _root(domain_xml):
    if domain_xml is None or (
        isinstance(domain_xml, str) and not domain_xml.strip()
    ):
        return None
    try:
        return ET.fromstring(domain_xml)
    except ET.ParseError:
        return None


def usb_state(domain_xml) -> dict:
    """Ce que le domaine porte côté USB, lu dans son XML (une vue : live par
    « virsh dumpxml », config par « dumpxml --inactive »).

    Rend :
    - hostdevs : [{"vid", "pid", "bus": int|None, "dev": int|None,
      "startup_policy": str, "missing": bool}] ; vid/pid "" pour une
      source par adresse seule. La vue live porte aussi l'adresse résolue
      d'un <hostdev> défini par vendor+product ; missing marque celui
      qu'un startupPolicy optionnel a laissé de côté au démarrage, faute
      de périphérique.
    - redirdevs : [type] des <redirdev bus='usb'>, dans l'ordre.
    - usb_controllers : [model] des contrôleurs USB ("" quand libvirt
      choisit ; "none" désactive l'USB).
    - graphics : [type] des affichages, DANS L'ORDRE — virt-viewer ouvre
      le premier.
    - spice_channel : bool, le canal com.redhat.spice.0 est présent.
    - redirfilter : [{"class", "vendor", "product", "version": str,
      "allow": bool}] ; "-1" pour un champ indifférent, vendor et product
      en 4 hex minuscules.
    - arch : architecture de l'invité, "" si absente.

    Un XML vide ou illisible rend l'état vide (aucun contrôleur).
    """
    state = {
        "hostdevs": [],
        "redirdevs": [],
        "usb_controllers": [],
        "graphics": [],
        "spice_channel": False,
        "redirfilter": [],
        "arch": "",
    }
    root = _root(domain_xml)
    if root is None:
        return state
    ostype = root.find("./os/type")
    if ostype is not None:
        state["arch"] = ostype.get("arch", "")
    for h in root.findall("./devices/hostdev[@type='usb']"):
        src = h.find("source")
        if src is None:
            continue
        vendor, product = src.find("vendor"), src.find("product")
        addr = src.find("address")
        state["hostdevs"].append(
            {
                "vid": norm_hex(vendor.get("id"))
                if vendor is not None
                else "",
                "pid": (
                    norm_hex(product.get("id")) if product is not None else ""
                ),
                "bus": _int(addr.get("bus")) if addr is not None else None,
                "dev": _int(addr.get("device")) if addr is not None else None,
                "startup_policy": src.get("startupPolicy", ""),
                "missing": src.get("missing") == "yes",
            }
        )
    for r in root.findall("./devices/redirdev"):
        if r.get("bus", "usb") == "usb":
            state["redirdevs"].append(r.get("type", ""))
    for c in root.findall("./devices/controller[@type='usb']"):
        state["usb_controllers"].append(c.get("model", ""))
    for g in root.findall("./devices/graphics"):
        state["graphics"].append(g.get("type", ""))
    for ch in root.findall("./devices/channel[@type='spicevmc']"):
        target = ch.find("target")
        if target is not None and target.get("name") == SPICE_CHANNEL:
            state["spice_channel"] = True
    for u in root.findall("./devices/redirfilter/usbdev"):
        state["redirfilter"].append(_filter_rule(u.attrib))
    return state


def _filter_rule(attrib) -> dict:
    """Règle <usbdev> d'un <redirfilter> sous une forme comparable : libvirt
    réécrit « 0x0fd9 » en « 0x0FD9 » et pose « -1 » pour un champ omis."""

    def field(name, hexa):
        value = str(attrib.get(name, "-1")).strip()
        if value == "-1" or not value:
            return "-1"
        return (norm_hex(value) or value) if hexa else value.lower()

    return {
        "class": field("class", False),
        "vendor": field("vendor", True),
        "product": field("product", True),
        "version": field("version", False),
        "allow": attrib.get("allow", "no") == "yes",
    }


def has_usb_controller(state: dict) -> bool:
    """Vrai quand la vue a un contrôleur USB actif (modèle autre que
    « none »)."""
    return any(m != "none" for m in state.get("usb_controllers") or [])


def usbredir_ready(state: dict) -> bool:
    """Vrai quand la vue porte un affichage SPICE et au moins un
    <redirdev type='spicevmc'> : virt-viewer peut alors rediriger."""
    return "spice" in (state.get("graphics") or []) and "spicevmc" in (
        state.get("redirdevs") or []
    )


def spice_first(state: dict) -> bool:
    """Vrai quand le PREMIER affichage est SPICE, celui qu'ouvre
    virt-viewer."""
    graphics = state.get("graphics") or []
    return bool(graphics) and graphics[0] == "spice"


# ---------------------------------------------------------------------------
# Plans virsh


def virsh_uri_argv(uri, *args) -> list:
    """["virsh", "--connect", uri, *args] ; uri vide -> DEFAULT_URI. Sans
    sudo : le privilège reste à l'appelant."""
    return ["virsh", "--connect", uri or DEFAULT_URI, *args]


def dumpxml_argv(uri, domain, inactive=False) -> list:
    """argv de lecture du XML. inactive=True lit la config, et ajoute
    --security-info : sans lui, libvirt masque le mot de passe d'un
    affichage, et redéfinir le domaine depuis ce XML l'effacerait."""
    extra = ["--inactive", "--security-info"] if inactive else []
    return virsh_uri_argv(uri, "dumpxml", domain, *extra)


def domstate_argv(uri, domain) -> list:
    """argv de « virsh domstate » ; la sortie « running » dit la VM en
    marche (lancer sous LC_ALL=C)."""
    return virsh_uri_argv(uri, "domstate", domain)


def define_argv(uri) -> list:
    """argv de « virsh define <xml-file> »."""
    return virsh_uri_argv(uri, "define", XML_PLACEHOLDER)


def bind_xml(argv, path) -> list:
    """argv avec XML_PLACEHOLDER remplacé par `path`."""
    return [path if a == XML_PLACEHOLDER else a for a in argv]


def _matches(h: dict, want: dict) -> bool:
    """Le <hostdev> lu `h` désigne-t-il le périphérique `want` ?

    VID:PID égaux quand les deux sont connus ; adresses égales quand les
    deux en portent une. Une adresse absente d'un côté ne contredit rien :
    une config par VID:PID couvre le périphérique épinglé qu'elle désigne.
    """
    wv, wp = norm_hex(want.get("vid")), norm_hex(want.get("pid"))
    if wv and wp and h.get("vid") and h.get("pid"):
        if (h["vid"], h["pid"]) != (wv, wp):
            return False
    wb, wd = want.get("bus"), want.get("dev")
    if wb is not None and wd is not None:
        if h.get("bus") is not None and h.get("dev") is not None:
            return (h["bus"], h["dev"]) == (int(wb), int(wd))
    if not (wv and wp and h.get("vid")):
        # Une adresse sans VID:PID ne se compare que par l'adresse.
        return False
    return True


def usb_plan(
    live_state,
    config_state,
    want: dict,
    live: bool,
    config: bool,
    running: bool,
    domain: str,
    uri: str = DEFAULT_URI,
) -> list:
    """Étapes d'attachement ou de détachement d'un périphérique USB.

    want : {"vid", "pid", "bus"?, "dev"?, "action": "attach"|"detach",
    "optional"?: bool (True par défaut)}. live / config : les vues
    visées. live_state / config_state : usb_state() de chaque vue (None
    si non lue).

    Une étape par vue, idempotente : « attach-device » n'est PAS
    idempotent — deux appels posent deux <hostdev> —, d'où la lecture de
    l'état avant le plan. Attacher saute la vue qui l'a déjà, et la vue
    sans contrôleur USB actif ; détacher saute la vue qui ne l'a pas, et
    rend une étape par <hostdev> concordant, avec le XML de CE <hostdev>
    pour que libvirt le retrouve. --live est sauté quand la VM est
    arrêtée.

    Un <hostdev> « missing » de la vue live est, dans QEMU, un usb-host
    SANS critère (ni vendeur, ni produit, ni adresse) : inerte tant que
    le nœud /dev/bus/usb du périphérique reste hors de l'espace de noms
    de QEMU. Il ne compte pas comme présent pour un attachement ; mais
    dès que libvirt y expose le nœud pour le nouveau <hostdev>, ce
    joker peut saisir le même périphérique, et l'invité en voit deux.
    L'attachement live le détache donc d'abord (libvirt le retrouve par
    vendor+product), et le détachement live le compte comme attaché.
    """
    action = want.get("action", "attach")
    label = device_id(
        want.get("vid"), want.get("pid"), want.get("bus"), want.get("dev")
    )
    if action == "attach":
        what = t("Attach {device} to {domain}").format(
            device=label, domain=domain
        )
    else:
        what = t("Detach {device} from {domain}").format(
            device=label, domain=domain
        )
    plan = []
    views = []
    if live:
        views.append(("live", live_state))
    if config:
        views.append(("config", config_state))
    for view, state in views:
        entry = {"what": f"{what} ({view})", "view": view}
        if view == "live" and not running:
            plan.append({**entry, "skip": t("the VM is not running")})
            continue
        state = state or usb_state(None)
        matching = [h for h in state["hostdevs"] if _matches(h, want)]
        # « missing » n'a de sens que dans la vue live (voir docstring).
        jokers = [h for h in matching if view == "live" and h.get("missing")]
        present = [h for h in matching if h not in jokers]
        flag = "--" + view
        if action == "attach":
            if present:
                plan.append({**entry, "skip": t("already attached")})
            elif not state["usb_controllers"]:
                plan.append(
                    {**entry, "skip": t("the VM has no USB controller")}
                )
            elif not has_usb_controller(state):
                plan.append(
                    {
                        **entry,
                        "skip": t("USB is disabled in the VM (model none)"),
                    }
                )
            else:
                for h in jokers:
                    plan.append(
                        {
                            **entry,
                            "what": t(
                                "Detach empty placeholder {device} from"
                                " {domain}"
                            ).format(
                                device=device_id(h["vid"], h["pid"]),
                                domain=domain,
                            )
                            + f" ({view})",
                            "argv": virsh_uri_argv(
                                uri,
                                "detach-device",
                                domain,
                                XML_PLACEHOLDER,
                                flag,
                            ),
                            "xml": hostdev_xml(
                                h["vid"], h["pid"], optional=False
                            ),
                        }
                    )
                plan.append(
                    {
                        **entry,
                        "argv": virsh_uri_argv(
                            uri, "attach-device", domain, XML_PLACEHOLDER, flag
                        ),
                        "xml": hostdev_xml(
                            want.get("vid"),
                            want.get("pid"),
                            want.get("bus"),
                            want.get("dev"),
                            optional=want.get("optional", True),
                        ),
                    }
                )
            continue
        if not matching:
            plan.append({**entry, "skip": t("not attached")})
        for h in matching:
            plan.append(
                {
                    **entry,
                    "argv": virsh_uri_argv(
                        uri, "detach-device", domain, XML_PLACEHOLDER, flag
                    ),
                    "xml": hostdev_xml(
                        h["vid"],
                        h["pid"],
                        h["bus"],
                        h["dev"],
                        optional=False,
                    ),
                }
            )
    return plan


# ---------------------------------------------------------------------------
# SPICE usbredir


def _register_namespaces(domain_xml: str):
    """Déclare à ElementTree les préfixes du XML lu, et ceux que libvirt
    emploie, pour que la sérialisation les garde au lieu d'écrire ns0."""
    prefixes = dict(_KNOWN_NS)
    try:
        for _ev, (prefix, uri) in ET.iterparse(
            io.BytesIO(domain_xml.encode("utf-8")), events=("start-ns",)
        ):
            if prefix:
                prefixes[prefix] = uri
    except ET.ParseError:
        pass
    for prefix, uri in prefixes.items():
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass


def _indent_tree(el, ws, step="  "):
    """Indente le sous-arbre de `el` comme ElementTree.indent, à partir de
    l'indentation `ws` de `el` lui-même (« \\n » + espaces)."""
    children = list(el)
    if not children:
        return
    inner = ws + step
    el.text = inner
    for child in children:
        _indent_tree(child, inner, step)
        child.tail = inner
    children[-1].tail = ws


def _insert(parent, index, el):
    """Insère `el` à `index` dans `parent` en gardant l'indentation du
    XML lu ; un XML compact reste compact."""
    children = list(parent)
    ws = parent.text if children else None
    if ws is not None and ws.strip():
        ws = None
    if ws is not None:
        _indent_tree(el, ws)
        if index >= len(children):
            el.tail = children[-1].tail
            children[-1].tail = ws
        else:
            el.tail = ws
    parent.insert(index, el)


def _remove(parent, el):
    """Retire `el` de `parent` ; le dernier enfant retiré lègue sa fin de
    ligne à son précédent, pour que la balise fermante reste alignée."""
    children = list(parent)
    idx = children.index(el)
    if idx == len(children) - 1 and idx > 0:
        children[idx - 1].tail = el.tail
    parent.remove(el)
    return idx


def _after_last(devices, tag):
    """Index qui suit le dernier enfant `tag` de devices, sinon la fin."""
    idx = len(devices)
    for i, child in enumerate(list(devices)):
        if child.tag == tag:
            idx = i + 1
    return idx


def spice_usbredir_xml(
    domain_xml: str, redir_slots: int = 2, allow_vendors=None
):
    """Le XML du domaine avec la redirection USB SPICE, et la liste des
    changements (textes lisibles). Idempotent : sur un XML déjà prêt,
    rend le XML d'entrée inchangé et une liste vide.

    Ajoute, chacun seulement s'il manque :
    - <graphics type='spice' listen='127.0.0.1'> AVANT le premier
      affichage existant : virt-viewer ouvre le premier, et le VNC qui
      suit reste là pour les tunnels et la console. Une VM où SPICE
      existe déjà mais n'est pas en tête le voit remonté en tête.
    - un contrôleur USB qemu-xhci ; un contrôleur au modèle « none » passe
      à qemu-xhci ;
    - des <redirdev bus='usb' type='spicevmc'/> jusqu'à redir_slots ;
    - le canal spicevmc com.redhat.spice.0.

    allow_vendors : None ne touche pas au <redirfilter> ; une suite de
    vendeurs pose un filtre qui les autorise et refuse le reste ; une
    suite vide retire le filtre.

    Entrée : le XML de la CONFIG (dumpxml_argv(..., inactive=True)), à
    redéfinir par « virsh define » ; un affichage ne change qu'au
    démarrage suivant. ValueError pour un XML illisible ou un invité
    s390x (pas d'affichage SPICE).
    """
    root = _root(domain_xml)
    if root is None:
        raise ValueError("spice_usbredir_xml: unreadable domain XML")
    ostype = root.find("./os/type")
    if ostype is not None and ostype.get("arch") == "s390x":
        raise ValueError(t("SPICE is not available on s390x"))
    _register_namespaces(domain_xml)
    root = ET.fromstring(domain_xml)
    devices = root.find("devices")
    if devices is None:
        devices = ET.SubElement(root, "devices")
    changes = []

    graphics = devices.findall("graphics")
    spice = [g for g in graphics if g.get("type") == "spice"]
    first_index = (
        list(devices).index(graphics[0]) if graphics else len(devices)
    )
    if not spice:
        g = ET.Element(
            "graphics",
            {"type": "spice", "autoport": "yes", "listen": "127.0.0.1"},
        )
        # Un affichage existant protégé par mot de passe le transmet au
        # SPICE ajouté : sans lui, tout compte local de l'hôte ouvrirait
        # la console que le VNC protège. Le XML doit donc venir de
        # dumpxml --security-info (dumpxml_argv), qui le révèle.
        secret = next(
            (x.get("passwd") for x in graphics if x.get("passwd")), ""
        )
        if secret:
            g.set("passwd", secret)
        ET.SubElement(g, "listen", {"type": "address", "address": "127.0.0.1"})
        _insert(devices, first_index, g)
        if graphics:
            changes.append(
                t("Add a SPICE display (127.0.0.1) before {first}").format(
                    first=graphics[0].get("type", "")
                )
            )
        else:
            changes.append(t("Add a SPICE display (127.0.0.1)"))
    elif graphics[0] is not spice[0]:
        _remove(devices, spice[0])
        first_index = list(devices).index(graphics[0])
        _insert(devices, first_index, spice[0])
        changes.append(
            t("Move the SPICE display before {first}").format(
                first=graphics[0].get("type", "")
            )
        )

    controllers = devices.findall("controller[@type='usb']")
    if not controllers:
        c = ET.Element(
            "controller",
            {
                "type": "usb",
                "model": USB_CONTROLLER_MODEL,
                "ports": USB_CONTROLLER_PORTS,
            },
        )
        _insert(devices, _after_last(devices, "controller"), c)
        changes.append(
            t("Add a USB controller ({model})").format(
                model=USB_CONTROLLER_MODEL
            )
        )
    elif not any(c.get("model") != "none" for c in controllers):
        controllers[0].set("model", USB_CONTROLLER_MODEL)
        controllers[0].set("ports", USB_CONTROLLER_PORTS)
        changes.append(
            t("Enable USB: controller model none -> {model}").format(
                model=USB_CONTROLLER_MODEL
            )
        )

    have = len(
        [
            r
            for r in devices.findall("redirdev")
            if r.get("bus", "usb") == "usb" and r.get("type") == "spicevmc"
        ]
    )
    missing = max(0, int(redir_slots) - have)
    for _i in range(missing):
        r = ET.Element("redirdev", {"bus": "usb", "type": "spicevmc"})
        idx = _after_last(devices, "redirdev")
        if idx == len(devices):
            idx = _after_last(devices, "video")
        _insert(devices, idx, r)
    if missing:
        changes.append(
            t("Add {n} SPICE USB redirection slot(s)").format(n=missing)
        )

    has_channel = any(
        ch.find("target") is not None
        and ch.find("target").get("name") == SPICE_CHANNEL
        for ch in devices.findall("channel[@type='spicevmc']")
    )
    if not has_channel:
        ch = ET.Element("channel", {"type": "spicevmc"})
        ET.SubElement(ch, "target", {"type": "virtio", "name": SPICE_CHANNEL})
        idx = _after_last(devices, "channel")
        if idx == len(devices):
            idx = _after_last(devices, "controller")
        _insert(devices, idx, ch)
        changes.append(t("Add the SPICE agent channel"))

    if allow_vendors is not None:
        vendors = [norm_hex(v) for v in allow_vendors if norm_hex(v)]
        current = devices.find("redirfilter")
        wanted = [
            {
                "class": "-1",
                "vendor": f"0x{v}",
                "product": "-1",
                "version": "-1",
                "allow": "yes",
            }
            for v in vendors
        ]
        if wanted:
            wanted.append(
                {
                    "class": "-1",
                    "vendor": "-1",
                    "product": "-1",
                    "version": "-1",
                    "allow": "no",
                }
            )
        existing = (
            [_filter_rule(u.attrib) for u in current.findall("usbdev")]
            if current is not None
            else []
        )
        if existing != [_filter_rule(w) for w in wanted]:
            if current is not None:
                idx = _remove(devices, current)
            else:
                idx = _after_last(devices, "redirdev")
            if wanted:
                f = ET.Element("redirfilter")
                for rule in wanted:
                    ET.SubElement(f, "usbdev", rule)
                _insert(devices, idx, f)
                changes.append(
                    t(
                        "Restrict USB redirection to vendor(s) {vendors}"
                    ).format(vendors=", ".join(vendors))
                )
            else:
                changes.append(t("Remove the USB redirection filter"))

    if not changes:
        return domain_xml, []
    return ET.tostring(root, encoding="unicode") + "\n", changes


def spice_usbredir_plan(
    domain_xml: str,
    domain: str,
    uri: str = DEFAULT_URI,
    redir_slots: int = 2,
    allow_vendors=None,
) -> list:
    """Plan qui redéfinit le domaine avec la redirection USB SPICE : une
    étape « virsh define » (view "config"), ou [] quand rien ne manque.
    "changes" y liste ce qui change. Effet au prochain démarrage de la VM.
    Lève ValueError comme spice_usbredir_xml."""
    new_xml, changes = spice_usbredir_xml(
        domain_xml, redir_slots=redir_slots, allow_vendors=allow_vendors
    )
    if not changes:
        return []
    return [
        {
            "what": t("Redefine {domain}: {changes}").format(
                domain=domain, changes="; ".join(changes)
            ),
            "view": "config",
            "argv": define_argv(uri),
            "xml": new_xml,
            "changes": changes,
        }
    ]


def usbredir_filter(vendors=(DECK_VENDOR,)) -> str:
    """Filtre spice-gtk qui autorise ces vendeurs et refuse le reste.

    Syntaxe : règles « classe,vendeur,produit,version,autorisé » jointes
    par « | », -1 = indifférent, la première règle qui concorde décide.
    """
    rules = [f"-1,0x{norm_hex(v)},-1,-1,1" for v in vendors if norm_hex(v)]
    rules.append("-1,-1,-1,-1,0")
    return "|".join(rules)


def virt_viewer_argv(uri, domain, usbredir=False, auto_vendors=(DECK_VENDOR,)):
    """argv de virt-viewer pour `domain` sur `uri`.

    usbredir=False rend exactement ["virt-viewer", "-c", uri, domain].
    usbredir=True ajoute les options spice-gtk qui redirigent d'office
    les périphériques des vendeurs auto_vendors : ceux déjà branchés à la
    connexion (--spice-usbredir-redirect-on-connect) et ceux branchés
    ensuite (--spice-usbredir-auto-redirect-filter). Les autres restent
    au choix de l'utilisateur dans le menu USB de virt-viewer.
    auto_vendors vide : aucune option, la sélection reste manuelle.
    """
    argv = ["virt-viewer", "-c", uri]
    vendors = [v for v in (auto_vendors or ()) if norm_hex(v)]
    if usbredir and vendors:
        filt = usbredir_filter(vendors)
        argv += [
            f"--spice-usbredir-auto-redirect-filter={filt}",
            f"--spice-usbredir-redirect-on-connect={filt}",
        ]
    argv.append(domain)
    return argv


# ---------------------------------------------------------------------------
# Rattachement automatique : correspondance, plan, udev, systemd


def _norm_entry(e):
    """Entrée de correspondance normalisée, ou None si elle est invalide."""
    if not isinstance(e, dict):
        return None
    vid, pid = norm_hex(e.get("vid")), norm_hex(e.get("pid"))
    domain = str(e.get("domain") or "").strip()
    if not (vid and pid and domain):
        return None
    out = {"vid": vid, "pid": pid, "domain": domain}
    if e.get("serial"):
        out["serial"] = str(e["serial"])
    if e.get("uri"):
        out["uri"] = str(e["uri"])
    return out


def mapping_loads(text) -> list:
    """Entrées du fichier MAPPING : [{"vid", "pid", "domain", "serial"?,
    "uri"?}]. Accepte {"entries": [...]} ou une liste nue ; texte vide ->
    []. Une entrée incomplète est écartée ; un JSON illisible lève
    ValueError."""
    if not (text or "").strip():
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("entries") or []
    if not isinstance(data, list):
        raise ValueError("mapping: expected a list of entries")
    return [e for e in (_norm_entry(x) for x in data) if e]


def mapping_dumps(entries) -> str:
    """Texte du fichier MAPPING : {"entries": [...]} indenté, clés triées,
    fin de ligne finale. Les entrées invalides sont écartées."""
    clean = [e for e in (_norm_entry(x) for x in entries) if e]
    return json.dumps({"entries": clean}, indent=2, sort_keys=True) + "\n"


def _entry_key(e):
    return (e["vid"], e["pid"], e.get("serial", ""))


def mapping_set(entries, entry) -> list:
    """Copie de `entries` où `entry` remplace celle de même
    (vid, pid, serial) ; ajoutée sinon. ValueError si `entry` est
    invalide."""
    new = _norm_entry(entry)
    if not new:
        raise ValueError("mapping: vid, pid and domain required")
    out = [e for e in (_norm_entry(x) for x in entries) if e]
    out = [e for e in out if _entry_key(e) != _entry_key(new)]
    out.append(new)
    return out


def mapping_remove(entries, vid, pid, serial=None, domain=None) -> list:
    """Copie de `entries` sans les entrées de ce VID:PID (et de ce
    domaine quand il est donné).

    `serial` : None vaut tout numéro de série ; "" ne vaut que l'entrée
    SANS série, celle qui suit n'importe quel exemplaire du modèle ;
    une valeur ne vaut que cette série."""
    vid, pid = norm_hex(vid), norm_hex(pid)
    out = []
    for e in (_norm_entry(x) for x in entries):
        if not e:
            continue
        if (
            (e["vid"], e["pid"]) == (vid, pid)
            and (serial is None or e.get("serial", "") == serial)
            and (domain is None or e["domain"] == domain)
        ):
            continue
        out.append(e)
    return out


def mapping_match(entries, dev: dict):
    """L'entrée qui revient au périphérique `dev`, ou None.

    Une entrée avec série ne vaut que pour ce numéro de série, et passe
    avant une entrée sans série : deux decks identiques vont ainsi à deux
    VM, ce que le <hostdev> de libvirt ne sait pas départager seul."""
    generic = None
    for e in (_norm_entry(x) for x in entries):
        if not e or (e["vid"], e["pid"]) != (dev.get("vid"), dev.get("pid")):
            continue
        if e.get("serial"):
            if e["serial"] == dev.get("serial"):
                return e
        elif generic is None:
            generic = e
    return generic


def reattach_plan(
    dev: dict, entry: dict, running: bool, live_state, host_devs=()
) -> list:
    """Étapes qui rattachent en live le périphérique rebranché `dev` (forme
    read_usb_device) à la VM de `entry` (forme mapping_match).

    1. VM arrêtée -> une étape skip : la config, si elle a été choisie à
       l'attachement, le reprendra au démarrage.
    2. Un <hostdev> du même VID:PID à l'adresse de `dev` -> skip, déjà là.
    3. Chaque <hostdev> du même VID:PID dont l'adresse ne désigne plus
       aucun périphérique branché (absent de host_devs) -> detach --live
       par cette adresse : l'ancien numéro ne revient pas.
    4. attach --live épinglé sur le bus/numéro de `dev`, sans ambiguïté
       possible même avec deux decks identiques ; usb_plan() détache
       d'abord le joker « missing » du même VID:PID.

    Le rattachement est nécessaire : libvirt passe à QEMU un descripteur
    du nœud /dev/bus/usb/BBB/DDD ouvert au démarrage ou à l'attachement.
    Au débranchement, le <hostdev> live garde son adresse morte ; au
    rebranchement, le noyau donne un nouveau numéro et QEMU ne reprend
    rien — le pilote de l'hôte récupère le périphérique.

    Ne touche jamais --config : la persistance a été choisie à
    l'attachement. uri : entry["uri"], sinon DEFAULT_URI.
    """
    domain = entry["domain"]
    uri = entry.get("uri") or DEFAULT_URI
    want = {
        "vid": dev["vid"],
        "pid": dev["pid"],
        "bus": dev["busnum"],
        "dev": dev["devnum"],
        "action": "attach",
        "optional": False,
    }
    if not running:
        return usb_plan(None, None, want, True, False, False, domain, uri)
    state = live_state or usb_state(None)
    plugged = {
        (d["busnum"], d["devnum"])
        for d in host_devs
        if (d.get("vid"), d.get("pid")) == (dev["vid"], dev["pid"])
    }
    plugged.add((dev["busnum"], dev["devnum"]))
    plan = []
    for h in state["hostdevs"]:
        if (h["vid"], h["pid"]) != (dev["vid"], dev["pid"]):
            continue
        if (
            h["bus"] is None
            or h.get("missing")
            or (h["bus"], h["dev"]) in plugged
        ):
            continue
        plan.append(
            {
                "what": t("Detach stale {device} from {domain}").format(
                    device=device_id(h["vid"], h["pid"], h["bus"], h["dev"]),
                    domain=domain,
                )
                + " (live)",
                "view": "live",
                "argv": virsh_uri_argv(
                    uri, "detach-device", domain, XML_PLACEHOLDER, "--live"
                ),
                "xml": hostdev_xml(
                    h["vid"], h["pid"], h["bus"], h["dev"], optional=False
                ),
            }
        )
    plan += usb_plan(state, None, want, True, False, True, domain, uri)
    return plan


def udev_rule_text(vids=(DECK_VENDOR,)) -> str:
    """Contenu de UDEV_RULE_PATH : à l'ajout d'un périphérique USB de ces
    vendeurs, systemd démarre erplibre-usb-reattach@<nom sysfs>.service.

    udev ne lance pas virsh lui-même : il tue un travail long, et le pilote
    nodedev de libvirt attend lui-même les événements udev. L'unité tourne
    hors d'udev. Le nom 85-… passe après 70-streamdeck.rules : les deux
    règles s'appliquent. Vendeurs vides -> ValueError.
    """
    vendors = sorted({norm_hex(v) for v in vids if norm_hex(v)})
    if not vendors:
        raise ValueError("udev_rule_text: at least one vendor required")
    lines = [
        "# ERPLibre : rattache à leur VM les périphériques USB de " + MAPPING,
        "# Généré par TODO, réécrit à chaque pose.",
    ]
    unit = UNIT_NAME.replace("@.", "@%k.")
    for vid in vendors:
        lines.append(
            'ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", '
            f'ATTR{{idVendor}}=="{vid}", TAG+="systemd", '
            f'ENV{{SYSTEMD_WANTS}}+="{unit}"'
        )
    return "\n".join(lines) + "\n"


def unit_text(exec_path: str = LIBEXEC_CLI) -> str:
    """Contenu de UNIT_PATH, l'unité gabarit lancée par la règle udev.

    %i et non %I : l'instance est le nom sysfs brut (« 3-2.1 »), et %I
    déséchapperait chaque « - » en « / ». Root, donc qemu:///system sans
    sudo. -B : root n'écrit aucun __pycache__ à côté de la copie. exec_path
    : chemin absolu sans espace, sinon ValueError.
    """
    if not exec_path.startswith("/") or re.search(r"\s", exec_path):
        raise ValueError("unit_text: absolute path without spaces required")
    return (
        "[Unit]\n"
        "Description=ERPLibre USB passthrough reattach (%i)\n"
        "After=libvirtd.service virtqemud.service\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/python3 -I -B {exec_path}"
        " reattach --sysname %i\n"
    )
