"""SMS par le modem, en passant par ModemManager.

On ne descend PAS en AT ici, contrairement aux appels : ModemManager sait
faire les SMS, gere l'encodage et le decoupage en segments, et il tient
deja les ports. Lui prendre le modem pour refaire ce qu'il fait bien
n'apporterait que des occasions de se tromper.
"""
import re

from .device import _run, mmcli_present


def proprietes_sms(numero, texte):
    """La chaine de proprietes de mmcli, ou (vide, raison).

    L'analyseur de ModemManager coupe le texte a la premiere espace tant
    qu'il n'est pas entre guillemets : sans eux, « coucou bobo » echoue sur
    « Unexpected content (bobo) after value ». Entre guillemets, l'espace,
    la virgule, le signe egal et les emoji passent.

    Il n'ECHAPPE rien, en revanche : un texte qui porte a la fois le
    guillemet double et l'apostrophe ne peut pas etre exprime. On le refuse
    en le disant, plutot que d'alterer en silence ce que quelqu'un a ecrit.
    """
    if '"' in texte and "'" in texte:
        return "", (
            "le message contient a la fois \" et ' ; ModemManager n'a aucun "
            "moyen de les distinguer. Retirez l'un des deux."
        )
    guillemet = "'" if '"' in texte else '"'
    return "number=%s,text=%s%s%s" % (numero, guillemet, texte, guillemet), ""


def envoyer(index, numero, texte):
    if not mmcli_present():
        return False, "mmcli absent."
    proprietes, raison = proprietes_sms(numero, texte)
    if raison:
        return False, raison
    code, sortie = _run(
        ["mmcli", "-m", str(index), "--messaging-create-sms=" + proprietes]
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
                       # Un message RECU porte « timestamp », un message
                       # ENVOYE porte « discharge timestamp » : l'accuse de
                       # remise. Les deux disent quand, et l'un des deux
                       # manque toujours.
                       ("horodatage", r"(?<!discharge )timestamp:\s*(\S+)"),
                       ("remis_le", r"discharge timestamp:\s*(\S+)")):
        m = re.search(motif, sortie)
        if m:
            res[cle] = m.group(1).strip()
    return res


def supprimer(index, ident):
    """Efface un message de la memoire du modem.

    Elle est petite — quelques dizaines de messages sur la SIM — et une fois
    pleine le modem refuse les suivants en silence. L'appelant n'efface
    qu'apres avoir vu le message enregistre ailleurs : effacer avant le
    perdrait, et un SMS entrant est la piece justificative d'un desabonnement.
    """
    if not mmcli_present():
        return False
    code, _sortie = _run(["mmcli", "-m", str(index), f"--messaging-delete-sms={ident}"])
    return code == 0
