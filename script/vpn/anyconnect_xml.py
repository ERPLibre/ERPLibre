#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lire un profil AnyConnect (`.xml`) et en tirer des préréglages.

Un site qui exploite un concentrateur Cisco distribue un fichier
`AnyConnectProfile` que son client dépose dans
`/opt/cisco/secureclient/vpn/profile/`. Tout ce dont openconnect a besoin
pour joindre le bon service y est déjà écrit, et le retaper à la main est
l'occasion de se tromper sur le seul champ qui compte.

Trois balises sont lues, et RIEN d'autre :

    <HostName>    → le libellé affiché. Un nom de service, pas un hôte,
                    malgré ce que la balise dit.
    <HostAddress> → le nom d'hôte réel du concentrateur.
    <UserGroup>   → le chemin d'URL, donc `--usergroup`. C'est le champ
                    qui décide QUEL service du concentrateur on joint.

Le reste du fichier décrit le comportement du client graphique de Cisco —
sélection de certificat, reconnexion automatique, mise à jour, exclusion
PPP. Rien de cela n'a d'équivalent chez openconnect, et prétendre le
traduire donnerait des champs que rien ne lit.

Ce que le fichier ne porte PAS, et que le formulaire demande ensuite :
l'identifiant, et la méthode d'authentification. Le profil AnyConnect ne
dit pas si le service authentifie par mot de passe ou par SAML — c'est le
concentrateur qui l'annonce à la connexion.

L'espace de noms n'est pas ignoré mais il n'est pas EXIGÉ non plus : les
fichiers vus dans le parc déclarent
`xmlns="http://schemas.xmlsoap.org/encoding/"`, et un site peut en
distribuer un sans. Les balises sont donc cherchées sur leur nom local.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from script.vpn.valid import NAME_RE

# Ce que le pilote openconnect a besoin de savoir et que le fichier ne dit
# pas. Repris tel quel dans chaque préréglage produit, pour qu'il soit
# complet dès sa lecture plutôt que complété au petit bonheur.
BASE = {
    "driver": "openconnect",
    "oc_protocol": "anyconnect",
    "port": 443,
    "routes": [],
    "default_route": False,
}


class ProfileXmlError(ValueError):
    """Fichier refusé. Le message est destiné à l'utilisateur."""


def _local(tag: str) -> str:
    """Nom de balise sans son espace de noms : `{uri}HostName` → `HostName`."""
    return tag.rsplit("}", 1)[-1]


def _text(node, name: str) -> str:
    """Texte de l'enfant direct `name`, "" s'il est absent ou vide.

    Enfant DIRECT et non descendant : un `<HostEntry>` n'imbrique pas ses
    champs, et chercher en profondeur ferait remonter la valeur d'une
    entrée voisine dans un fichier mal formé.
    """
    for child in node:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def slug(label: str, address: str) -> str:
    """Identifiant de préréglage tiré du libellé, sinon de l'hôte.

    Le libellé est le nom que le site a choisi et celui que l'utilisateur
    reconnaît. Réduit à l'alphabet de `NAME_RE`, et replié sur le premier
    élément du nom d'hôte quand il n'en reste rien d'utilisable — un
    libellé entièrement accentué ou vide ne doit pas rendre le fichier
    inimportable.
    """
    for candidate in (label, address.split(".")[0]):
        cleaned = re.sub(r"[^a-z0-9]+", "_", candidate.lower()).strip("_")
        cleaned = cleaned[:31]
        if cleaned and NAME_RE.match(cleaned):
            return cleaned
    return "anyconnect"


def parse(text: str) -> list[dict]:
    """Les préréglages décrits par ce XML. Lève ProfileXmlError.

    Un fichier peut porter plusieurs `<HostEntry>` : un site en distribue
    souvent un par service. Chacun devient un préréglage, et les
    identifiants sont rendus uniques par un suffixe — deux entrées peuvent
    porter le même libellé.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ProfileXmlError(f"XML illisible : {error}")

    entries = [node for node in root.iter() if _local(node.tag) == "HostEntry"]
    if not entries:
        raise ProfileXmlError(
            "Aucun « HostEntry » : ce fichier n'est pas un profil"
            " AnyConnect, ou il ne déclare aucun serveur."
        )

    presets: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        address = _text(entry, "HostAddress")
        label = _text(entry, "HostName")
        if not address:
            # Une entrée sans adresse ne mène nulle part. Sautée plutôt que
            # fatale : les autres entrées du fichier restent utilisables.
            continue
        identifier = slug(label, address)
        if identifier in seen:
            suffix = 2
            while f"{identifier}_{suffix}" in seen:
                suffix += 1
            identifier = f"{identifier}_{suffix}"
        seen.add(identifier)
        presets.append(
            dict(
                BASE,
                preset=identifier,
                label=label or address,
                server=address,
                oc_usergroup=_text(entry, "UserGroup"),
            )
        )
    if not presets:
        raise ProfileXmlError(
            "Chaque « HostEntry » est sans « HostAddress » : aucun serveur"
            " à joindre."
        )
    return presets


def parse_file(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse(fh.read())
    except OSError as error:
        raise ProfileXmlError(f"{path} : {error}")
