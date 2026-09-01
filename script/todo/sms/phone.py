#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire les SMS du téléphone depuis le poste, par `adb`.

Sert à trancher la question qui revient à chaque essai : « le message est-il
vraiment parti ? ». Odoo dit ce qu'il a demandé, le journal de la passerelle
dit ce que l'appareil a fait, mais seule la boîte d'envoi du téléphone dit ce
que la pile téléphonique a réellement enregistré.

On passe par `adb` et non par l'application : lire la boîte SMS depuis une
application demande `READ_SMS`, une permission restreinte qu'Android réserve
à l'application de messagerie par défaut. La passerelle n'a aucune raison de
la réclamer pour un besoin de diagnostic.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


#: Boîtes lisibles et leur URI.
BOITES = {
    "inbox": "content://sms/inbox",
    "sent": "content://sms/sent",
    "all": "content://sms/",
}

#: `Row: 0 address=X, date=123, body=...` — le corps va jusqu'au `Row:`
#: suivant, parce qu'un SMS peut contenir des virgules ET des sauts de ligne.
LIGNE = re.compile(
    r"Row:\s*\d+\s+address=(?P<address>.*?),\s*date=(?P<date>\d+),\s*"
    r"body=(?P<body>.*?)(?=\nRow:\s*\d+\s+address=|\Z)",
    re.S,
)


class PhoneError(RuntimeError):
    """Ce qui empêche de lire, dit en une phrase utile."""


def adb_path() -> str:
    return shutil.which("adb") or ""


def devices() -> list:
    """Les appareils joignables, hors ligne d'en-tête et hors autorisation."""
    if not adb_path():
        return []
    try:
        res = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return []
    trouves = []
    for ligne in (res.stdout or "").splitlines()[1:]:
        parts = ligne.split()
        if len(parts) >= 2 and parts[1] == "device":
            trouves.append(parts[0])
    return trouves


def read_sms(boite: str = "sent", limit: int = 15) -> list:
    """Les messages d'une boîte, du plus récent au plus ancien.

    Renvoie une liste de dicts `{address, at, body}`. `at` est un
    `datetime` local : Android stocke des millisecondes depuis l'époque, et
    les afficher brutes rendrait la lecture inutile.
    """
    if boite not in BOITES:
        raise PhoneError(f"boite inconnue : {boite}")
    if not adb_path():
        raise PhoneError(t("sms_phone_no_adb"))
    if not devices():
        raise PhoneError(t("sms_phone_no_device"))

    try:
        res = subprocess.run(
            [
                "adb",
                "shell",
                "content",
                "query",
                "--uri",
                BOITES[boite],
                "--projection",
                "address:date:body",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PhoneError(str(exc)) from exc

    sortie = res.stdout or ""
    if "No result found" in sortie:
        return []
    if res.returncode != 0 or "Error" in (res.stderr or ""):
        # Le cas courant : l'appareil refuse la lecture du fournisseur SMS.
        raise PhoneError((res.stderr or sortie).strip()[:300])

    messages = []
    for m in LIGNE.finditer(sortie):
        try:
            horodatage = datetime.fromtimestamp(int(m.group("date")) / 1000)
        except (ValueError, OSError, OverflowError):
            horodatage = None
        messages.append(
            {
                "address": m.group("address").strip(),
                "at": horodatage,
                "body": m.group("body").strip(),
            }
        )
    # Android ne garantit pas l'ordre du fournisseur : on trie nous-mêmes.
    messages.sort(key=lambda x: x["at"] or datetime.min, reverse=True)
    return messages[:limit]


def render(messages: list, boite: str) -> str:
    """Les messages, prêts à lire dans un terminal."""
    if not messages:
        return f"  {t('sms_phone_empty')}"
    sens = "→" if boite == "sent" else "←"
    lignes = []
    for msg in messages:
        quand = msg["at"].strftime("%d/%m %H:%M") if msg["at"] else "  ?  "
        corps = " ".join(msg["body"].split())
        if len(corps) > 60:
            corps = corps[:57] + "…"
        lignes.append(f"  {quand}  {sens} {msg['address']:<16} {corps}")
    return "\n".join(lignes)


def ensure_reverse(port: int) -> bool:
    """(Re)pose le renvoi USB vers le poste. Idempotent et silencieux.

    Mesure sur le terrain : le renvoi saute tout seul, plusieurs fois par
    heure, SANS aucun message — la passerelle continue d'interroger dans le
    vide et Odoo reste bloque sur un etat intermediaire qui ressemble a une
    panne d'envoi. Le reposer avant chaque lecture d'etat coute une
    milliseconde et supprime le faux diagnostic.

    Renvoie False sans rien casser si adb ou l'appareil manquent : en mode VM,
    ou sans telephone branche, il n'y a simplement rien a faire.
    """
    if not adb_path() or not devices():
        return False
    try:
        res = subprocess.run(
            ["adb", "reverse", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def host_lan_ip() -> str:
    """L'adresse de CE poste sur le reseau local, ou une chaine vide.

    On la demande a la table de routage plutot que de lister les interfaces :
    une machine de developpement porte souvent un pont libvirt (`virbr0`)
    et des interfaces Docker, qui sont des adresses privees parfaitement
    valides mais que le telephone n'atteindra jamais.
    La route par defaut, elle, designe l'interface qui sort vraiment.
    """
    try:
        res = subprocess.run(
            ["ip", "-4", "route", "get", "1.1.1.1"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", res.stdout or "")
    return m.group(1) if m else ""


def phone_lan_ip() -> str:
    """L'adresse Wi-Fi du telephone branche, ou une chaine vide."""
    if not adb_path() or not devices():
        return ""
    try:
        res = subprocess.run(
            ["adb", "shell", "ip", "-4", "-o", "addr", "show", "wlan0"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", res.stdout or "")
    return m.group(1) if m else ""


def same_subnet(a: str, b: str, prefix: int = 24) -> bool:
    """Les deux adresses partagent-elles le meme /24 ?

    Approximation volontaire : on ne lit pas le masque reel. Elle suffit a
    prevenir le cas courant — telephone sur le Wi-Fi invite, poste sur le
    reseau filaire — sans pretendre remplacer un vrai test de joignabilite.
    """
    if not a or not b or prefix != 24:
        return False
    return a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0]
