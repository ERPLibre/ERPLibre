"""Appels par le modem cellulaire.

AVERTISSEMENT QUI GOUVERNE CE FICHIER : ces commandes composent pour de vrai,
sur une ligne facturee, vers une personne reelle. Aucune fonction d'ici ne
doit etre appelee sans que quelqu'un ait vu le numero et confirme.

Second point, moins evident et plus decevant : tant que la voix du modem
n'est pas cablee — carte son USB (UAC) ou PCM vers du materiel — un appel
S'ETABLIT sans qu'aucun son ne circule. Le correspondant decroche et
n'entend rien. C'est un etat normal du modem, pas une panne, et l'interface
doit le dire plutot que de laisser croire a un echec.
"""
import re

from . import device

#: Prefixe accepte : plan de numerotation nord-americain.
MOTIF_NUMERO = re.compile(r"^\+?1?([2-9]\d{2}[2-9]\d{6})$")


def numero_valide(brut):
    """Renvoie le numero normalise a 11 chiffres, ou None.

    On valide AVANT de composer : un numero mal forme part quand meme sur le
    reseau, et une erreur de frappe peut joindre quelqu'un qui n'a rien
    demande.
    """
    if not brut:
        return None
    chiffres = re.sub(r"[^\d+]", "", str(brut))
    m = MOTIF_NUMERO.match(chiffres)
    return "1" + m.group(1) if m else None


def appeler(numero):
    """Compose un numero. Le point-virgule d'ATD demande un appel VOIX.

    Sans lui le modem tenterait un appel de DONNEES, qui echoue sur une ligne
    ordinaire — c'est l'erreur classique, et son message ne l'explique pas.
    """
    norm = numero_valide(numero)
    if not norm:
        return False, "Numero invalide (plan nord-americain attendu)."
    ok, sortie = device.commande_at([f"ATD+{norm};"])
    return ok, sortie


def raccrocher():
    return device.commande_at(["ATH"])


def appels_en_cours():
    """Liste les appels vus par le modem, via AT+CLCC.

    Renvoie une liste de dictionnaires. Le champ `etat` suit la numerotation
    de la norme : 0 actif, 2 en composition, 3 sonne chez nous, 4 entrant.
    """
    ok, sortie = device.commande_at(["AT+CLCC"])
    if not ok:
        return []
    appels = []
    for ligne in sortie.splitlines():
        m = re.match(r"\+CLCC:\s*(\d+),(\d+),(\d+),(\d+),(\d+),\"([^\"]*)\"", ligne.strip())
        if m:
            appels.append({
                "index": int(m.group(1)),
                "sortant": m.group(2) == "0",
                "etat": int(m.group(3)),
                "numero": m.group(6),
            })
    return appels


def libelle_etat(code):
    return {
        0: "en communication",
        1: "en attente",
        2: "composition",
        3: "sonnerie",
        4: "entrant",
        5: "en attente d'acceptation",
    }.get(code, f"etat {code}")


def carte_son():
    """Index et nom de la carte son du modem, ou (None, None).

    On rend l'INDEX et pas seulement un booleen : le service qui joue
    l'annonce doit ecrire dans `hw:<index>,0`, et le deduire ailleurs
    dupliquerait la recherche — donc la ferait diverger un jour.
    """
    try:
        with open("/proc/asound/cards", encoding="utf-8") as f:
            lignes = f.read().splitlines()
    except OSError:
        return None, None
    for ligne in lignes:
        # Format : « 1 [EC25AF         ]: USB-Audio - EC25-AF »
        m = re.match(r"\s*(\d+)\s*\[([^\]]+)\]", ligne)
        if not m:
            continue
        index, nom = m.group(1), m.group(2).strip()
        if any(i in nom.upper() for i in ("EC25", "EG25", "QUECTEL")):
            return int(index), nom
    return None, None


def voix_disponible():
    """La voix du modem est-elle cablee quelque part ?

    Deux voies possibles : une carte son USB (UAC), ou du PCM vers du
    materiel. On lit la premiere, qui est la seule verifiable sans ouvrir le
    boitier : si le modem expose une carte son, elle apparait dans
    /proc/asound/cards.

    La carte PRESENTE ne suffit pas : un serveur audio de bureau l'adopte
    volontiers comme micro et la tient ouverte, ce qui la rend inutilisable
    en ALSA direct. On l'ouvre donc pour de vrai, sans quoi l'etat annonce
    « carte detectee » sur une carte qu'aucun appel ne pourra employer.
    """
    index, nom = carte_son()
    if index is None:
        return False, (
            "aucune carte son du modem : un appel s'etablira SANS AUCUN SON."
            " Activez l'UAC par le menu, ou voyez le diagnostic AT."
        )
    from . import audio as audio_mod

    libre, motif = audio_mod.carte_libre(f"hw:{index},0")
    if not libre:
        return False, (
            f"carte son {nom} PRISE par un autre programme ({motif})."
            " Posez la regle audio par le menu."
        )
    return True, f"carte son {nom} (hw:{index},0)"
