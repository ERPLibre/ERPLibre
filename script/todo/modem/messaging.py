"""SMS par le modem, en passant par ModemManager.

On ne descend PAS en AT ici, contrairement aux appels : ModemManager sait
faire les SMS, gere l'encodage et le decoupage en segments, et il tient
deja les ports. Lui prendre le modem pour refaire ce qu'il fait bien
n'apporterait que des occasions de se tromper.
"""
import re

from .device import _run, mmcli_present


def envoyer(index, numero, texte):
    if not mmcli_present():
        return False, "mmcli absent."
    code, sortie = _run(
        ["mmcli", "-m", str(index), f"--messaging-create-sms=number={numero},text={texte}"]
    )
    if code != 0:
        return False, sortie
    m = re.search(r"/SMS/(\d+)", sortie)
    if not m:
        return False, "SMS cree mais identifiant introuvable : " + sortie
    ident = m.group(1)
    code, sortie = _run(["mmcli", "-s", ident, "--send"], timeout=60)
    return code == 0, sortie


def lister(index):
    """Messages connus du modem, plus recents d'abord."""
    if not mmcli_present():
        return []
    code, sortie = _run(["mmcli", "-m", str(index), "--messaging-list-sms"])
    if code != 0:
        return []
    return list(reversed(re.findall(r"/SMS/(\d+)\s+\((\w+)\)", sortie)))


def lire(ident):
    code, sortie = _run(["mmcli", "-s", str(ident)])
    if code != 0:
        return {}
    res = {}
    for cle, motif in (("numero", r"number:\s*(\S+)"),
                       ("texte", r"text:\s*(.+)"),
                       ("etat", r"state:\s*(\S+)"),
                       ("horodatage", r"timestamp:\s*(\S+)")):
        m = re.search(motif, sortie)
        if m:
            res[cle] = m.group(1).strip()
    return res
