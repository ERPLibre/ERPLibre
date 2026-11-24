#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""État et diagnostic d'ERPLibre Home sur ce poste, pour le menu Stream
Deck de TODO.

collect() interroge le poste — fichiers, systemctl --user, GetExtensionInfo
par gdbus, journal de GNOME Shell, sysfs, verrou du deck — et rend un dict
de faits. status_lines() et diagnosis_lines() n'en font que du texte, sans
rien lancer : les tests les nourrissent de faits écrits à la main et de
sorties de commandes enregistrées.

Les faits :

- extension_linked, venv, udev_rule, unit_file : bool ;
- extension : {"state": float|None, "error": str} ;
- journal : {"read": bool, "failed": [id d'indicateur], "visible": bool} ;
- unit_enabled, unit_active : sortie de systemctl is-enabled / is-active,
  "" quand l'unité n'est pas installée ou que systemctl n'a rien rendu ;
- settings : les réglages du service, défauts compris ;
- deck_program : bool, le programme du deck est posé ; sans lui, le
  verrou ne se lit pas, et lock vaut None ;
- lock : (pid, programme) du détenteur du verrou du deck, ou None ;
- lock_running : bool, le PID de lock désigne encore le processus qui a
  écrit le verrou (deck_lock.holder_running) ; faux quand il est libre ;
- lock_pids : [pid] des processus qui ont le verrou ouvert, [] quand il
  est libre ; pour un jeu, tout son arbre, l'enveloppe fût-elle morte ;
- decks : les périphériques USB du vendeur 0fd9, triés par chemin sysfs,
  chacun {"product": nom annoncé, "" s'il manque ; "id_product" ;
  "model": nom du modèle d'après streamdeck_models, "" s'il est inconnu ;
  "serial" ; "sysname" ; "busnum", "devnum": int|None ; "driver": pilote
  de sa première interface (« usbhid », « usbfs »), "" sans pilote ;
  "owner_uid": propriétaire de /dev/bus/usb/BBB/DDD, None s'il ne se lit
  pas ; "vm": None quand le deck reste à l'hôte, le nom de la VM qui le
  tient, "" quand une VM le tient sans qu'on sache laquelle}.

Un deck passé à une VM se reconnaît sans root. libvirt donne le nœud
/dev/bus/usb/BBB/DDD à l'utilisateur de QEMU dès l'attachement (son
dynamic_ownership, actif par défaut), et QEMU détache usbhid de
l'interface, qui passe à usbfs quand l'invité configure le périphérique.
Le programme du deck de l'hôte, qui parle au deck par
hidapi-libusb, met lui aussi l'interface sous usbfs, mais le nœud reste à
root : seul le propriétaire départage. Le nom de la VM vient des
<hostdev> live des domaines, lus par virsh en lecture seule, sinon de la
correspondance du rattachement automatique (qemu_usb.MAPPING).
"""

import glob
import importlib.util
import os
import re

from script.todo import erplibre_home_service as service
from script.todo.streamdeck_models import model_name
from script.todo.todo_i18n import t

EXTENSION_UUID = "erplibre-home@technolibre.ca"
UDEV_RULE = "/etc/udev/rules.d/70-streamdeck.rules"
DECK_VENDOR = "0fd9"

CMD_EXTENSION_INFO = (
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.Shell.Extensions",
    "--object-path",
    "/org/gnome/Shell/Extensions",
    "--method",
    "org.gnome.Shell.Extensions.GetExtensionInfo",
    EXTENSION_UUID,
)
# Le journal de GNOME Shell pour ce démarrage : l'extension y écrit
# « [ERPLibreHome] enabled » à la fin d'enable() et « mount <id> failed »
# pour un indicateur qui n'a pas pu se monter.
CMD_JOURNAL = (
    "journalctl",
    "--user",
    "-b",
    "-o",
    "cat",
    "--no-pager",
    "_COMM=gnome-shell",
)
JOURNAL_GREP = (
    "journalctl --user -b -o cat _COMM=gnome-shell | grep ERPLibreHome"
)
# Les deux remèdes d'un journal que l'utilisateur ne lit pas ; TODO ne
# passe jamais par sudo, il les montre.
JOURNAL_HINT = (
    "sudo usermod -aG systemd-journal $USER"
    " # or: Storage=persistent in /etc/systemd/journald.conf"
)
STREAMDECK_INSTALL = "make erplibre_home_streamdeck_install"

# Pilote du noyau qui tient l'interface d'un deck resté à l'hôte.
HOST_HID_DRIVER = "usbhid"
# virsh en lecture seule : la socket en lecture seule de libvirtd ne demande
# aucun mot de passe. « timeout » borne une connexion qui ne répond pas, et
# place virsh hors du groupe de premier plan du terminal : une lecture au
# clavier l'arrête au lieu d'attendre une réponse.
LIBVIRT_URI = "qemu:///system"
VIRSH_TIMEOUT_SEC = "5"


def cmd_virsh(*args):
    return (
        "timeout",
        VIRSH_TIMEOUT_SEC,
        "virsh",
        "--readonly",
        "--connect",
        LIBVIRT_URI,
        *args,
    )


CMD_DOMAINS = cmd_virsh("list", "--name")


def cmd_unit(verb):
    return ("systemctl", "--user", verb, service.UNIT_NAME)


_ETAT = re.compile(r"'state': <(-?\d+(?:\.\d+)?)>")
_ERREUR = re.compile(
    r"""'error': <(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")>"""
)
_MONTAGE_ECHOUE = re.compile(r"\[ERPLibreHome\] mount (\S+) failed")


def parse_extension_info(text):
    """{"state": float|None, "error": str} lus dans la sortie de gdbus.

    GetExtensionInfo rend un a{sv} au format texte de GVariant ; une
    extension que GNOME Shell ne connaît pas rend un dictionnaire vide, lu
    comme state None. Une chaîne citée entre guillemets (elle contient une
    apostrophe) est lue aussi, ses échappements défaits."""
    texte = text or ""
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


def parse_journal(text):
    """{"read": bool, "failed": [id], "visible": bool} : read quand la ligne
    « [ERPLibreHome] enabled » y est, preuve que le journal de la session a
    été lu ; failed, les indicateurs non montés, triés, sans doublon ;
    visible quand la requête rend la moindre ligne. Une session GNOME en
    marche écrit toujours dans le journal de gnome-shell : une sortie vide
    veut dire un journal que l'utilisateur ne lit pas (stockage volatil de
    journald, utilisateur hors du groupe systemd-journal), non un journal
    sans indicateur."""
    lignes = (text or "").splitlines()
    return {
        "visible": any(ligne.strip() for ligne in lignes),
        "read": any(
            ligne.strip().endswith("[ERPLibreHome] enabled")
            for ligne in lignes
        ),
        "failed": sorted(set(_MONTAGE_ECHOUE.findall(text or ""))),
    }


def _lire(chemin):
    try:
        with open(chemin, encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _entier(texte):
    try:
        return int(texte, 10)
    except ValueError:
        return None


def _proprietaire(chemin):
    """UID du propriétaire de `chemin`, None quand il ne se lit pas."""
    try:
        return os.stat(chemin).st_uid
    except OSError:
        return None


def _pilote(dossier):
    """Nom du pilote de la première interface (« 3-2:1.0 ») du
    périphérique `dossier` qui en a un, "" quand aucune n'en a."""
    for interface in sorted(glob.glob(dossier + ":*")):
        lien = os.path.join(interface, "driver")
        if os.path.islink(lien):
            return os.path.basename(os.readlink(lien))
    return ""


def plugged_decks(sysfs="/sys", devfs="/dev", owner_of=_proprietaire):
    """Les périphériques USB du vendeur 0fd9 sous `sysfs`, triés par
    chemin, dans la forme de « decks » (vm toujours None : deck_vm la
    remplit). `owner_of(chemin)` rend l'UID du propriétaire du nœud sous
    `devfs`, ou None."""
    decks = []
    motif = os.path.join(sysfs, "bus/usb/devices/*/idVendor")
    for fichier in sorted(glob.glob(motif)):
        if _lire(fichier) != DECK_VENDOR:
            continue
        dossier = os.path.dirname(fichier)
        id_product = _lire(os.path.join(dossier, "idProduct"))
        bus = _entier(_lire(os.path.join(dossier, "busnum")))
        dev = _entier(_lire(os.path.join(dossier, "devnum")))
        noeud = (
            os.path.join(devfs, "bus/usb", "%03d" % bus, "%03d" % dev)
            if bus is not None and dev is not None
            else None
        )
        decks.append(
            {
                "product": _lire(os.path.join(dossier, "product")),
                "id_product": id_product,
                "model": model_name(id_product),
                "serial": _lire(os.path.join(dossier, "serial")),
                "sysname": os.path.basename(dossier),
                "busnum": bus,
                "devnum": dev,
                "driver": _pilote(dossier),
                "owner_uid": owner_of(noeud) if noeud else None,
                "vm": None,
            }
        )
    return decks


def libvirt_usb_holders(run):
    """{(bus, dev): domaine} des <hostdev> USB des domaines en marche de
    LIBVIRT_URI, lus dans leur XML live, où libvirt écrit l'adresse
    résolue ; un <hostdev> laissé de côté au démarrage (missing) n'y entre
    pas. None quand virsh manque, échoue ou dépasse son délai."""
    from script.todo import qemu_usb

    code, sortie = run(CMD_DOMAINS)
    if code != 0:
        return None
    tenus = {}
    for domaine in (sortie or "").split():
        code, xml = run(cmd_virsh("dumpxml", domaine))
        if code != 0:
            continue
        for h in qemu_usb.usb_state(xml)["hostdevs"]:
            if h["missing"] or h["bus"] is None or h["dev"] is None:
                continue
            tenus[(h["bus"], h["dev"])] = domaine
    return tenus


def read_mapping(chemin):
    """Les entrées de la correspondance du rattachement automatique ; []
    quand le fichier manque, ne se lit pas ou n'est pas du JSON valide."""
    from script.todo import qemu_usb

    try:
        return qemu_usb.mapping_loads(_lire(chemin))
    except ValueError:
        return []


def deck_vm(deck, holders, entries, uid):
    """La valeur de « vm » pour `deck` (forme plugged_decks).

    `holders` : {(bus, dev): domaine} de libvirt_usb_holders, ou None.
    Un domaine qui tient l'adresse du deck le nomme. Sinon, un deck que
    usbhid tient reste à l'hôte ; un nœud dont le propriétaire n'est ni
    root ni `uid` est à QEMU, et la VM est celle que `entries` (forme
    qemu_usb.mapping_loads) attribue au deck, "" sans entrée. Le reste
    (usbfs avec un nœud à root : le programme du deck de l'hôte) est à
    l'hôte."""
    from script.todo import qemu_usb

    if holders:
        domaine = holders.get((deck.get("busnum"), deck.get("devnum")))
        if domaine:
            return domaine
    if deck.get("driver") == HOST_HID_DRIVER:
        return None
    proprio = deck.get("owner_uid")
    if proprio is None or proprio in (0, uid):
        return None
    entree = qemu_usb.mapping_match(
        entries,
        {
            "vid": DECK_VENDOR,
            "pid": qemu_usb.norm_hex(deck.get("id_product")),
            "serial": deck.get("serial") or "",
        },
    )
    return entree["domain"] if entree else ""


def decks_with_vm(decks, run, mapping_path, uid):
    """`decks` où « vm » est rempli. virsh et la correspondance ne sont
    lus que si un deck échappe à usbhid."""
    if all(d.get("driver") == HOST_HID_DRIVER for d in decks):
        return decks
    holders = libvirt_usb_holders(run)
    entries = read_mapping(mapping_path)
    return [dict(d, vm=deck_vm(d, holders, entries, uid)) for d in decks]


def _deck_lock(root):
    """deck_lock.py du checkout du programme du deck, chargé par son
    chemin : sa racine n'est pas un paquet. None quand le deck manque."""
    if not service.deck_present(root):
        return None
    chemin = os.path.join(service.deck_dir(root), "deck_lock.py")
    spec = importlib.util.spec_from_file_location("deck_lock", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Les niveaux d'installation d'ERPLibre Home, du moins au plus complet.
LEVEL_NONE = "none"
LEVEL_BASE = "base"
LEVEL_STREAM_DECK = "stream_deck"


def _extension_link(environ):
    """Le lien que l'installateur pose pour l'extension, sous le HOME
    d'`environ`."""
    return os.path.join(
        environ.get("HOME", ""),
        ".local/share/gnome-shell/extensions",
        EXTENSION_UUID,
    )


def _deck_python(root):
    """L'interpréteur de .venv.streamdeck, que seul le niveau Stream Deck
    pose."""
    return os.path.join(root, ".venv.streamdeck", "bin", "python")


def level_of(extension_linked, venv):
    """Le niveau qu'indiquent le lien de l'extension et le venv du deck :
    sans lien, rien n'est installé, même si un venv traîne."""
    if not extension_linked:
        return LEVEL_NONE
    return LEVEL_STREAM_DECK if venv else LEVEL_BASE


def installed_level(root, environ=None):
    """Le niveau installé sur ce poste, lu sur disque sans rien lancer."""
    environ = os.environ if environ is None else environ
    return level_of(
        os.path.islink(_extension_link(environ)),
        os.access(_deck_python(root), os.X_OK),
    )


def collect(
    run,
    root,
    environ=None,
    sysfs="/sys",
    udev_rule=UDEV_RULE,
    lock_path=None,
    devfs="/dev",
    owner_of=_proprietaire,
    mapping_path=None,
    uid=None,
):
    """Les faits du poste. `run(argv)` rend (code, sortie) ; `root` est la
    racine du dépôt. systemctl n'est appelé que si l'unité est installée,
    virsh que si un deck échappe à usbhid. `lock_path` None prend le
    chemin que lit deck_lock ; `mapping_path` None, qemu_usb.MAPPING ;
    `uid` None, celui du processus."""
    environ = os.environ if environ is None else environ
    if mapping_path is None:
        from script.todo import qemu_usb

        mapping_path = qemu_usb.MAPPING
    uid = os.getuid() if uid is None else uid
    lien = _extension_link(environ)
    python = _deck_python(root)
    unit_file = os.path.exists(service.unit_path(environ))
    deck_lock = _deck_lock(root)
    if deck_lock is None:
        verrou, tenu = None, None
    else:
        verrou = lock_path or deck_lock.lock_path(environ)
        tenu = deck_lock.holder(verrou)
    return {
        "extension_linked": os.path.islink(lien),
        "venv": os.access(python, os.X_OK),
        "udev_rule": os.path.exists(udev_rule),
        "extension": parse_extension_info(run(CMD_EXTENSION_INFO)[1]),
        "journal": parse_journal(run(CMD_JOURNAL)[1]),
        "unit_file": unit_file,
        "unit_enabled": (
            run(cmd_unit("is-enabled"))[1].strip() if unit_file else ""
        ),
        "unit_active": (
            run(cmd_unit("is-active"))[1].strip() if unit_file else ""
        ),
        "settings": service.read_settings(service.settings_path(environ)),
        "plugin_ids": service.deck_plugin_ids(root, environ),
        "deck_program": deck_lock is not None,
        "lock": tenu[:2] if tenu else None,
        "lock_running": deck_lock.holder_running(tenu) if tenu else False,
        "lock_pids": deck_lock.holder_pids(verrou) if tenu else [],
        "decks": decks_with_vm(
            plugged_decks(sysfs, devfs, owner_of), run, mapping_path, uid
        ),
    }


def _actif(extension):
    return extension["state"] == 1 and extension["error"] == ""


def _nom_deck(deck):
    """Le nom annoncé, sinon celui du modèle, sinon l'idProduct, et la VM
    qui tient le deck quand il lui est passé."""
    nom = deck["product"] or deck.get("model") or deck["id_product"] or "?"
    vm = deck.get("vm")
    if vm is None:
        return nom
    if vm:
        return "%s (%s %s)" % (nom, t("passed to VM"), vm)
    return "%s (%s)" % (nom, t("passed to a VM"))


def _tous_dans_une_vm(decks):
    """Vrai quand au moins un deck est branché et que tous sont passés à
    une VM : le service de l'hôte n'a alors rien à piloter."""
    return bool(decks) and all(d.get("vm") is not None for d in decks)


def status_lines(facts):
    """Une ligne par sonde, dans la langue de l'utilisateur."""
    niveau = {
        LEVEL_NONE: t("Level: not installed"),
        LEVEL_BASE: t("Level: base"),
        LEVEL_STREAM_DECK: t("Level: Stream Deck"),
    }[level_of(facts["extension_linked"], facts["venv"])]
    extension = facts["extension"]
    if _actif(extension):
        ligne_ext = t("Extension: active")
    elif extension["state"] is None:
        ligne_ext = t("Extension: not loaded in this session")
    else:
        ligne_ext = "%s %g, %s %s" % (
            t("Extension: state"),
            extension["state"],
            t("error:"),
            extension["error"] or "-",
        )
    journal = facts["journal"]
    if not journal["read"] and not journal["visible"]:
        indicateurs = t("Indicators: journal not readable by this user")
    elif not journal["read"]:
        indicateurs = t("Indicators: journal not read")
    elif journal["failed"]:
        indicateurs = "%s %s" % (
            t("Indicators: failed to mount:"),
            ", ".join(journal["failed"]),
        )
    else:
        indicateurs = t("Indicators: all mounted")
    if facts["unit_file"]:
        unite = "%s %s, %s, %s %s" % (
            t("Service:"),
            facts["unit_enabled"] or "?",
            facts["unit_active"] or "?",
            t("program"),
            facts["settings"]["DECK_PROGRAM"],
        )
        if facts["unit_active"] != "active" and _tous_dans_une_vm(
            facts["decks"]
        ):
            unite = "%s — %s" % (unite, t("idle, the deck is in a VM"))
    else:
        unite = t("Service: not installed")
    if not facts["deck_program"]:
        verrou = t("Deck program: not installed")
    elif facts["lock"]:
        pid = facts["lock"][0]
        if not facts["lock_running"]:
            pid = "%s, %s" % (pid, t("no longer running"))
        verrou = "%s %s (PID %s)" % (
            t("Deck lock: held by"),
            facts["lock"][1],
            pid,
        )
    else:
        verrou = t("Deck lock: free")
    if facts["decks"]:
        decks = "%s %s" % (
            t("Decks plugged in:"),
            ", ".join(_nom_deck(d) for d in facts["decks"]),
        )
    else:
        decks = t("Decks plugged in: none")
    valeur_jeux = facts["settings"].get("GAMES", "on")
    if valeur_jeux in service.GAMES_VALUES:
        jeux = "%s %s" % (t("Games:"), valeur_jeux)
    else:
        jeux = "%s %r" % (t("Games: unknown value"), valeur_jeux)
    coupes = service.plugins_off(facts["settings"])
    lignes_plugins = (
        ["%s %s" % (t("Plugins off:"), ", ".join(coupes))] if coupes else []
    )
    periode = service.session_refresh_sec(facts["settings"])
    lignes_rafraichissement = (
        ["%s %g s" % (t("Session refresh:"), periode)]
        if periode != float(service.DEFAULTS["DECK_SESSION_REFRESH_SEC"])
        else []
    )
    return [
        niveau,
        ligne_ext,
        indicateurs,
        unite,
        jeux,
        *lignes_plugins,
        *lignes_rafraichissement,
        verrou,
        decks,
        (
            t("udev rule: present")
            if facts["udev_rule"]
            else t("udev rule: missing")
        ),
        (
            t("Stream Deck venv: present")
            if facts["venv"]
            else t("Stream Deck venv: missing")
        ),
    ]


def diagnosis_lines(facts):
    """[(problème, correction)] pour chaque sonde qui n'est pas comme
    attendu, dans l'ordre où les corriger ; [] quand tout va. Une unité
    installée mais désactivée n'est pas un problème : l'ouverture
    automatique est un choix d'installation. Un deck passé à une VM non
    plus : le service de l'hôte n'a rien à piloter quand tous les decks
    branchés sont dans une VM. Un état de l'unité que systemctl n'a pas
    rendu (pas de bus utilisateur, par ssh ou sudo) est dit illisible, non
    faux. Sans l'extension, ou sans le niveau Stream Deck, la liste
    s'arrête là : ce qui suit en dépend."""
    if not facts["extension_linked"]:
        return [
            (t("ERPLibre Home is not installed"), "make erplibre_home_install")
        ]
    problemes = []
    extension = facts["extension"]
    if extension["state"] is None:
        problemes.append(
            (
                t("The extension is not loaded in this session"),
                t("log out and back in"),
            )
        )
    elif not _actif(extension):
        problemes.append(
            (
                "%s %s"
                % (t("The extension is in error:"), extension["error"]),
                JOURNAL_GREP,
            )
        )
    journal = facts["journal"]
    if not journal["read"] and not journal["visible"]:
        problemes.append(
            (t("The journal is not readable by this user"), JOURNAL_HINT)
        )
    if journal["read"] and journal["failed"]:
        problemes.append(
            (
                "%s %s"
                % (
                    t("Indicators failed to mount:"),
                    ", ".join(journal["failed"]),
                ),
                JOURNAL_GREP,
            )
        )
    if not (facts["venv"] and facts["udev_rule"]):
        problemes.append(
            (t("The Stream Deck level is not installed"), STREAMDECK_INSTALL)
        )
        return problemes
    if not facts["deck_program"]:
        problemes.append(
            (t("The deck program is not installed"), STREAMDECK_INSTALL)
        )
        return problemes
    valeur_jeux = facts["settings"].get("GAMES", "on")
    if valeur_jeux not in service.GAMES_VALUES:
        problemes.append(
            (
                "%s %r" % (t("Unknown GAMES value:"), valeur_jeux),
                t("TODO › ERPLibre Home › Games on/off"),
            )
        )
    for identifiant in service.plugins_off(facts["settings"]):
        if identifiant not in facts["plugin_ids"]:
            problemes.append(
                (
                    "%s %s"
                    % (t("Unknown plugin in DECK_PLUGINS_OFF:"), identifiant),
                    t("TODO › ERPLibre Home › Plugins on/off"),
                )
            )
    brut = facts["settings"].get("DECK_SESSION_REFRESH_SEC")
    if brut is not None and service.parse_session_refresh(brut) is None:
        problemes.append(
            (
                "%s %r" % (t("Invalid DECK_SESSION_REFRESH_SEC:"), brut),
                t("TODO › ERPLibre Home › Session refresh"),
            )
        )
    if not facts["unit_file"]:
        problemes.append(
            (t("The deck service is not installed"), STREAMDECK_INSTALL)
        )
        return problemes
    programme = facts["settings"]["DECK_PROGRAM"]
    if programme not in service.PROGRAMS:
        problemes.append(
            (
                "%s %s" % (t("Unknown DECK_PROGRAM:"), programme),
                t("TODO › ERPLibre Home › Deck program"),
            )
        )
    if not facts["decks"]:
        problemes.append(
            (t("No Stream Deck plugged in"), t("plug a Stream Deck in"))
        )
    elif (
        not _tous_dans_une_vm(facts["decks"])
        and programme != "none"
        and facts["unit_active"]
        and facts["unit_active"] != "active"
    ):
        if facts["lock"]:
            pid, detenteur = facts["lock"]
            # Le PID nommé n'est proposé à « kill » que s'il désigne encore
            # l'auteur du verrou : parti, il a pu être repris par un autre
            # processus. Les processus qui tiennent le verrou le remplacent.
            nomme = [pid] if facts["lock_running"] else []
            if detenteur == "game":
                # Fermer le jeu le laisse finir proprement ; le dernier
                # recours vise chaque processus qui tient le verrou, car
                # l'enveloppe que le verrou nomme peut être déjà morte.
                pids = facts["lock_pids"] or nomme
                ferme = t("close the game")
                sinon = t("close the game; as a last resort:")
            else:
                pids = nomme or facts["lock_pids"]
                ferme = t("close it")
                sinon = t("close it, or:")
            if pids:
                remede = "%s kill %s" % (
                    sinon,
                    " ".join(str(p) for p in pids),
                )
            else:
                remede = ferme
            problemes.append(
                (
                    "%s %s (PID %s)"
                    % (t("The deck is held by"), detenteur, pid),
                    remede,
                )
            )
        else:
            problemes.append(
                (
                    t("The deck service is not running"),
                    "systemctl --user start %s" % service.UNIT_NAME,
                )
            )
    if not (facts["unit_enabled"] and facts["unit_active"]):
        problemes.append(
            (
                t("The deck service state could not be read"),
                t("run it from the desktop session"),
            )
        )
    return problemes
