"""Ce que ModemManager ne dit pas : les capacites audio du modem.

Toute la question de la voix tient dans `AT+QCFG="usbcfg"`. Sa reponse est
une liste de parametres ; le DERNIER est l'UAC — la carte son USB. Moins de
sept parametres et le micrologiciel ne sait pas faire de voix par USB.
"""
import re

from . import device

COMMANDES = [
    "ATI",
    'AT+QCFG="usbcfg"',
    "AT+QAUDMOD?",
    "AT+QPCMV?",
    "AT+CLCC",
]


def sonder():
    """Interroge le modem et RESUME ce que ca implique.

    Renvoie (brut, conclusions). On ne se contente pas de rendre la reponse :
    « +QCFG: "usbcfg",0x2C7C,0x0125,1,1,1,1,1,0 » ne dit rien a qui ne connait
    pas la position de l'UAC dans la liste.
    """
    ok, brut = device.commande_at(COMMANDES)
    if not ok:
        return brut, ["Le modem n'a pas repondu : " + brut.strip()[:200]]

    conclusions = []
    m = re.search(r'\+QCFG:\s*"usbcfg"\s*,\s*(.+)', brut)
    if not m:
        conclusions.append(
            "usbcfg sans reponse : ce micrologiciel ne connait pas ce"
            " parametre, donc pas d'UAC."
        )
    else:
        params = [p.strip() for p in m.group(1).split(",")]
        if len(params) < 7:
            conclusions.append(
                "usbcfg a %d parametres : moins de sept, l'UAC n'existe pas"
                " sur ce micrologiciel. La voix par USB est exclue." % len(params)
            )
        else:
            actif = params[-1] not in ("0", "0x0")
            conclusions.append(
                "UAC DISPONIBLE et %s (dernier parametre : %s)."
                % ("ACTIF" if actif else "eteint", params[-1])
            )
            if not actif:
                conclusions.append(
                    "Il s'active en ecrivant usbcfg avec le dernier parametre"
                    " a 1, suivi d'un redemarrage du modem. C'est une ECRITURE"
                    " de configuration : elle n'est pas faite automatiquement."
                )

    m = re.search(r"\+QPCMV:\s*(\d+)", brut)
    if m:
        conclusions.append(
            "PCM %s — voie materielle, utilisable seulement avec un cablage"
            " vers une carte son." % ("actif" if m.group(1) != "0" else "eteint")
        )
    return brut, conclusions


def lire_usbcfg():
    """Renvoie les parametres bruts d'usbcfg, ou None.

    Format documente par Quectel :
      <vid>,<pid>,<diag>,<nmea>,<at>,<modem>,<rmnet>,<adb>,<uac>
    Le dernier est l'UAC. Mesure sur EC25-AF(D) R07A08 :
      +QCFG: "usbcfg",0x2C7C,0x125,1,1,1,1,1,0,0
    """
    ok, brut = device.commande_at(['AT+QCFG="usbcfg"'])
    if not ok:
        return None
    m = re.search(r'\+QCFG:\s*"usbcfg"\s*,\s*(.+)', brut)
    if not m:
        return None
    return [p.strip() for p in m.group(1).split(",")]


def uac_actif(params=None):
    p = params if params is not None else lire_usbcfg()
    if not p or len(p) < 7:
        return None
    return p[-1] not in ("0", "0x0")


def activer_uac(actif=True):
    """Ecrit usbcfg avec l'UAC dans l'etat voulu, puis redemarre le modem.

    On RELIT d'abord les parametres au lieu de les reconstruire : ils portent
    l'identifiant du produit et la composition des ports. Les deviner
    exposerait a poser une composition qui n'est pas celle de cet appareil,
    et un modem mal recompose ne revient pas forcement.

    `AT+CFUN=1,1` reinitialise le module : il disparait du bus USB puis
    reapparait, ce qui prend une trentaine de secondes. C'est normal, et
    c'est la seule facon d'appliquer une nouvelle composition USB.
    """
    params = lire_usbcfg()
    if not params:
        return False, "usbcfg illisible : le modem n'a pas repondu."
    if len(params) < 7:
        return False, (
            "usbcfg n'a que %d parametres : ce micrologiciel ne connait pas"
            " l'UAC." % len(params)
        )
    voulu = "1" if actif else "0"
    if params[-1] == voulu:
        return True, "Deja dans l'etat demande, rien a ecrire."
    params[-1] = voulu
    commande = 'AT+QCFG="usbcfg",' + ",".join(params)
    ok, sortie = device.commande_at([commande, "AT+CFUN=1,1"])
    if not ok:
        return False, sortie
    return True, (
        "Configuration ecrite et modem redemarre. Il disparait du bus USB"
        " puis reapparait — comptez une trentaine de secondes avant que la"
        " carte son soit visible."
    )
