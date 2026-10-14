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
- journal : {"read": bool, "failed": [id d'indicateur]} ;
- unit_enabled, unit_active : sortie de systemctl is-enabled / is-active,
  "" quand l'unité n'est pas installée ou que systemctl n'a rien rendu ;
- settings : les réglages du service, défauts compris ;
- lock : (pid, programme) du détenteur du verrou du deck, ou None ;
- decks : [{"product": str, "id_product": str}], vendeur 0fd9.
"""

import glob
import importlib.util
import os
import re

from script.todo import erplibre_home_service as service
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
STREAMDECK_INSTALL = "make erplibre_home_streamdeck_install"


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
    """{"read": bool, "failed": [id]} : read quand la ligne
    « [ERPLibreHome] enabled » y est, preuve que le journal de la session a
    été lu ; failed, les indicateurs non montés, triés, sans doublon."""
    lignes = (text or "").splitlines()
    return {
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


def plugged_decks(sysfs="/sys"):
    """Les périphériques USB du vendeur 0fd9 sous `sysfs`, triés par
    chemin : {"product": nom lu dans « product », "" s'il manque,
    "id_product": idProduct}."""
    decks = []
    motif = os.path.join(sysfs, "bus/usb/devices/*/idVendor")
    for fichier in sorted(glob.glob(motif)):
        if _lire(fichier) != DECK_VENDOR:
            continue
        dossier = os.path.dirname(fichier)
        decks.append(
            {
                "product": _lire(os.path.join(dossier, "product")),
                "id_product": _lire(os.path.join(dossier, "idProduct")),
            }
        )
    return decks


def _deck_lock(root):
    """script/stream_deck/deck_lock.py chargé par son chemin :
    script/stream_deck n'est pas un paquet."""
    chemin = os.path.join(root, "script", "stream_deck", "deck_lock.py")
    spec = importlib.util.spec_from_file_location("deck_lock", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(
    run,
    root,
    environ=None,
    sysfs="/sys",
    udev_rule=UDEV_RULE,
    lock_path=None,
):
    """Les faits du poste. `run(argv)` rend (code, sortie) ; `root` est la
    racine du dépôt. systemctl n'est appelé que si l'unité est installée.
    `lock_path` None prend le chemin que lit deck_lock."""
    environ = os.environ if environ is None else environ
    lien = os.path.join(
        environ.get("HOME", ""),
        ".local/share/gnome-shell/extensions",
        EXTENSION_UUID,
    )
    python = os.path.join(root, ".venv.streamdeck", "bin", "python")
    unit_file = os.path.exists(service.unit_path(environ))
    deck_lock = _deck_lock(root)
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
        "lock": deck_lock.holder(lock_path or deck_lock.lock_path(environ)),
        "decks": plugged_decks(sysfs),
    }


def _actif(extension):
    return extension["state"] == 1 and extension["error"] == ""


def status_lines(facts):
    """Une ligne par sonde, dans la langue de l'utilisateur."""
    if not facts["extension_linked"]:
        niveau = t("Level: not installed")
    elif facts["venv"]:
        niveau = t("Level: Stream Deck")
    else:
        niveau = t("Level: base")
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
    if not journal["read"]:
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
    else:
        unite = t("Service: not installed")
    if facts["lock"]:
        verrou = "%s %s (PID %s)" % (
            t("Deck lock: held by"),
            facts["lock"][1],
            facts["lock"][0],
        )
    else:
        verrou = t("Deck lock: free")
    if facts["decks"]:
        decks = "%s %s" % (
            t("Decks plugged in:"),
            ", ".join(
                d["product"] or d["id_product"] or "?" for d in facts["decks"]
            ),
        )
    else:
        decks = t("Decks plugged in: none")
    return [
        niveau,
        ligne_ext,
        indicateurs,
        unite,
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
    automatique est un choix d'installation. Un état de l'unité que
    systemctl n'a pas rendu (pas de bus utilisateur, par ssh ou sudo) est
    dit illisible, non faux. Sans
    l'extension, ou sans le niveau Stream Deck, la liste s'arrête là : ce
    qui suit en dépend."""
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
                t("TODO › Stream Deck › Deck program"),
            )
        )
    if not facts["decks"]:
        problemes.append(
            (t("No Stream Deck plugged in"), t("plug a Stream Deck in"))
        )
    elif (
        programme != "none"
        and facts["unit_active"]
        and facts["unit_active"] != "active"
    ):
        if facts["lock"]:
            pid, detenteur = facts["lock"]
            problemes.append(
                (
                    "%s %s (PID %s)"
                    % (t("The deck is held by"), detenteur, pid),
                    "%s kill %s" % (t("close it, or:"), pid),
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
