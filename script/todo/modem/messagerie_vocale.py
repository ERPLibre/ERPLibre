#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La boite vocale de l'OPERATEUR : un message y attend-il ?

Le reseau l'inscrit sur la carte SIM, dans le fichier standard EF_MWIS
(3GPP TS 31.102), que le modem laisse lire sans rien modifier. Le drapeau se
leve quand un message est depose et retombe quand la boite est videe. Il ne
porte pas de compte fiable : on sait « au moins un message », jamais combien.

Deux sources, dans cet ordre :

1. la SIM elle-meme, quand le port AT est libre — l'etat est frais ;
2. le dernier etat ecrit par le service `erplibre-sip-go`, quand c'est lui qui
   tient le port — l'etat porte alors son age, et un etat ancien se dit ancien.

Les regles de lecture sont celles du service (`messagerie.go`) : un statut qui
n'est pas un succes est une ERREUR, jamais une boite vide. Une SIM sans ce
fichier ne peut rien annoncer, et le taire laisserait croire qu'il n'y a rien.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

#: Lecture de l'enregistrement 1 d'EF_MWIS (6FCA = 28618), cinq octets.
COMMANDE = "AT+CRSM=178,28618,1,4,5"

#: Premier bit du premier octet : la messagerie vocale.
BIT_MESSAGERIE = 0x01

#: Au-dela, l'etat laisse par le service n'est plus presente comme courant.
#: Le service relit chaque minute : cinq minutes sans ecriture disent qu'il ne
#: lit plus, et non que rien n'a change.
AGE_MAX_SECONDES = 300

ATTENTE, VIDE, INCONNU = "attente", "vide", "inconnu"

_MOTIF = re.compile(r'\+CRSM:\s*(\d+),\s*(\d+)(?:,\s*"([0-9A-Fa-f]*)")?')

#: Marque que l'outil AT ecrit quand un autre programme tient le port.
MARQUE_PORT_TENU = "PORT_TENU"


def decoder(reponse: str) -> tuple:
    """Rend (etat, explication) a partir d'une reponse brute."""
    trouve = _MOTIF.search(reponse or "")
    if not trouve:
        return INCONNU, "reponse illisible"
    sw1 = int(trouve.group(1))
    if sw1 not in (144, 145):
        return INCONNU, "fichier absent de cette SIM (statut %s,%s)" % (
            trouve.group(1),
            trouve.group(2),
        )
    try:
        octets = bytes.fromhex(trouve.group(3) or "")
    except ValueError:
        return INCONNU, "fichier mal forme"
    if not octets:
        return INCONNU, "fichier vide"
    return (ATTENTE if octets[0] & BIT_MESSAGERIE else VIDE), ""


def chemin_etat_service() -> str:
    """Le fichier ou le service depose sa derniere lecture.

    Meme calcul que `CheminÉtatMessagerie` cote Go : les deux doivent tomber
    sur le meme fichier sans rien se communiquer.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "erplibre", "messagerie.json")


def lire_etat_service(maintenant=None, chemin=None) -> dict | None:
    """Le dernier etat du service, avec son age, ou None s'il n'y en a pas."""
    try:
        with open(chemin or chemin_etat_service(), encoding="utf-8") as flux:
            brut = json.load(flux)
        lu = datetime.fromisoformat(brut["lu_le"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    maintenant = maintenant or datetime.now(timezone.utc)
    age = max(0, int((maintenant - lu).total_seconds()))
    return {
        "etat": ATTENTE if brut.get("attente") else VIDE,
        "source": "service",
        "age": age,
        "perime": age > AGE_MAX_SECONDES,
        "detail": "",
    }


def lire(commande_at=None, maintenant=None, chemin_service=None) -> dict:
    """L'etat de la boite vocale, et d'ou il vient.

    `commande_at` rend (ok, texte), comme `device.commande_at` ; il est
    injectable pour que la logique se verifie sans modem.
    """
    if commande_at is None:
        from script.todo.modem import device

        commande_at = device.commande_at
    ok, texte = commande_at([COMMANDE])
    if MARQUE_PORT_TENU in (texte or ""):
        service = lire_etat_service(maintenant, chemin_service)
        if service:
            return service
        return {
            "etat": INCONNU,
            "source": None,
            "age": None,
            "perime": False,
            "detail": "port tenu par le service, qui n'a encore rien lu",
        }
    etat, detail = decoder(texte)
    if etat == INCONNU and not ok and not detail.startswith("fichier"):
        detail = (
            (texte or "").strip().splitlines()[-1][:80] if texte else detail
        )
    return {
        "etat": etat,
        "source": "sim" if etat != INCONNU else None,
        "age": 0,
        "perime": False,
        "detail": detail,
    }


def age_lisible(secondes: int) -> str:
    if secondes < 90:
        return "%s s" % secondes
    if secondes < 5400:
        return "%s min" % round(secondes / 60)
    return "%s h" % round(secondes / 3600)


#: Numero de la messagerie, tel que la SIM le declare.
COMMANDE_NUMERO = "AT+CSVM?"

_MOTIF_CSVM = re.compile(r'\+CSVM:\s*(\d+),\s*"([^"]*)"')


def numero_messagerie(commande_at=None) -> tuple:
    """Rend (numero, explication) ; numero vide quand il est inconnu.

    Le numero est celui que l'operateur a inscrit sur la SIM, et non une
    valeur saisie : c'est la seule qui mene a coup sur a SA messagerie.
    """
    if commande_at is None:
        from script.todo.modem import device

        commande_at = device.commande_at
    ok, texte = commande_at([COMMANDE_NUMERO])
    if MARQUE_PORT_TENU in (texte or ""):
        return "", "port tenu par le service erplibre-sip-go : arretez-le d'abord"
    trouve = _MOTIF_CSVM.search(texte or "")
    if not trouve or trouve.group(1) == "0" or not trouve.group(2):
        return "", "aucun numero de messagerie inscrit sur la SIM"
    return trouve.group(2), ""
