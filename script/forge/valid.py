#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Contrôler l'adresse d'une forge avant qu'un jeton parte dedans.

Le module partagé `script/lib_valid` porte les formats communs. Ce qui vit
ici n'appartient qu'à une forge : son URL de base, et la question qu'elle
pose et qu'aucun autre format ne pose — un jeton d'API voyage dans un
en-tête, donc l'adresse décide de qui peut le lire.

QUATRE REFUS, ET CHACUN A SA RAISON.

Un IDENTIFIANT DANS L'URL — « https://compte:motdepasse@forge/ » — met un
secret dans un fichier de configuration, alors que le coffre existe pour ça
et que le fichier, lui, se relit, se copie et se montre.

UN SCHÉMA AUTRE QU'HTTP OU HTTPS n'est pas une forge. « file:// » et
« ssh:// » se glissent par copier-coller depuis un remote git.

HTTP EN CLAIR VERS UNE ADRESSE DISTANTE expose le jeton à tout le segment :
il part dans un en-tête, à chaque appel. Vers la boucle locale rien ne passe
sur un câble, donc rien à exiger. Ailleurs, c'est un choix qui se déclare.

UN NOM D'HÔTE POUR « BOUCLE LOCALE » n'en est pas un. « localhost » se
résout où le résolveur le dit ; seule une adresse littérale prouve que le
jeton ne quittera pas la machine.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from script.lib_valid import ValidationError  # noqa: F401

# Ce qu'une forge peut parler. Volontairement court.
SCHEMAS = ("https", "http")


def _est_boucle_locale(hote: str) -> bool:
    """Vrai pour une adresse littérale de boucle locale, et pour elle seule.

    Un nom d'hôte rend faux, « localhost » compris : il se résout où le
    résolveur le dit, et un jeton envoyé en clair vers un « localhost »
    pointant ailleurs a quitté la machine sans que rien ne le dise.
    """
    if not hote:
        return False
    try:
        return ipaddress.ip_address(hote.strip("[]")).is_loopback
    except ValueError:
        return False


def base_url(record, key, label, required=True):
    """Normalise l'URL de base d'une forge, ou lève ValidationError.

    Rend l'adresse SANS barre oblique finale : les appels y ajoutent
    « /api/v1/… », et une barre en trop donne un chemin doublé que certains
    serveurs acceptent et d'autres non — une panne qui ne se voit que sur
    l'une des deux forges.

    `record["allow_plaintext"]`, à vrai, accepte http vers une adresse
    distante. C'est le seul moyen d'y arriver.
    """
    brut = (record.get(key) or "").strip()
    if not brut:
        if required:
            raise ValidationError(f"{label} : adresse requise.")
        record[key] = ""
        return ""
    if any(caractere.isspace() for caractere in brut):
        raise ValidationError(f"{label} : une adresse ne porte pas d'espace.")

    decoupe = urlsplit(brut)
    if decoupe.scheme not in SCHEMAS:
        raise ValidationError(
            f"{label} : schéma « {decoupe.scheme or 'aucun'} » refusé,"
            f" attendu {' ou '.join(SCHEMAS)}."
        )
    if decoupe.username or decoupe.password:
        raise ValidationError(
            f"{label} : un identifiant dans l'adresse finirait en clair dans"
            " un fichier de configuration ; le coffre porte les secrets."
        )
    if not decoupe.hostname:
        raise ValidationError(f"{label} : aucun hôte dans l'adresse.")
    if decoupe.query or decoupe.fragment:
        raise ValidationError(
            f"{label} : une adresse de base ne porte ni requête ni ancre."
        )
    if ".." in decoupe.path.split("/"):
        raise ValidationError(
            f"{label} : « .. » n'a rien à faire dans un" " chemin de base."
        )
    if decoupe.scheme == "http" and not _est_boucle_locale(decoupe.hostname):
        if not record.get("allow_plaintext"):
            raise ValidationError(
                f"{label} : http vers « {decoupe.hostname} » expose le jeton"
                " d'API à tout le segment, il voyage dans un en-tête à chaque"
                " appel. Poser « allow_plaintext » pour l'accepter quand"
                " même."
            )

    propre = f"{decoupe.scheme}://{decoupe.netloc}{decoupe.path.rstrip('/')}"
    record[key] = propre
    return propre
