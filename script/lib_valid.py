#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Contrôler une valeur de configuration avant qu'un shell la découvre.

Ces contrôles ne sont pas cosmétiques : chaque valeur finit dans un fichier
de configuration système et dans une ligne de commande lancée par sudo. Un
nom d'hôte portant un point-virgule doit être refusé ICI, pas découvert par
`sh`. Un module à part parce que plusieurs formats en ont besoin, et qu'un
contrôle recopié diverge de sa copie au premier correctif.

Chaque fonction NORMALISE en place (`record[key]` reçoit la valeur propre) et
lève `ValidationError` avec un message destiné à l'humain.

Le paramètre s'appelle `record` : c'est un dictionnaire de champs, et rien
ici ne suppose ce qu'il décrit.
"""
from __future__ import annotations

import ipaddress
import re

# Le nom sert de nom de connexion, de répertoire et de nom de fichier : il
# reste dans un alphabet sans surprise.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
# Nom d'hôte ou adresse, avec un « utilisateur@ » facultatif : une cible SSH
# porte souvent son compte. Volontairement plus strict que la RFC : ce qui
# n'est ni lettre, ni chiffre, ni `.-_` est refusé.
SERVER_RE = re.compile(
    r"^([A-Za-z0-9._-]+@)?[A-Za-z0-9][A-Za-z0-9._-]{0,252}$"
)
# Nom d'hôte seul (domaine de recherche DNS, alias) : pas d'« utilisateur@ ».
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


class ValidationError(ValueError):
    """Valeur refusée. Le message est destiné à l'utilisateur."""


def text(record, key, label, required=True, pattern=None):
    """Champ texte, sans espace de bord, refusé s'il sort du motif."""
    value = str(record.get(key) or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} : valeur obligatoire.")
        record[key] = ""
        return ""
    if "\n" in value or "\r" in value:
        raise ValidationError(f"{label} : une seule ligne.")
    if pattern and not pattern.match(value):
        raise ValidationError(f"{label} : « {value} » refusé.")
    record[key] = value
    return value


def path(record, key, label, required=True):
    """Chemin de fichier. L'existence n'est PAS exigée ici.

    Une fiche peut être écrite sur une machine et jouée sur une autre ;
    c'est à l'usage de dire « ce fichier n'est pas là », avec le chemin sous
    les yeux. Ce qui est refusé ici, c'est ce qui casserait un shell.
    """
    value = str(record.get(key) or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} : chemin obligatoire.")
        record[key] = ""
        return ""
    if any(char in value for char in "\n\r\0"):
        raise ValidationError(f"{label} : chemin illisible.")
    record[key] = value
    return value


def integer(record, key, label, low, high):
    try:
        value = int(record.get(key))
    except (TypeError, ValueError):
        raise ValidationError(f"{label} : nombre entier attendu.")
    if not low <= value <= high:
        raise ValidationError(
            f"{label} : hors bornes ({low}-{high}) : {value}."
        )
    record[key] = value
    return value


def port(record, key, label):
    return integer(record, key, label, 1, 65535)


def flag(record, key):
    record[key] = bool(record.get(key))
    return record[key]


def ip_address(record, key, label, required=False):
    """Adresse IP nue (pas de préfixe)."""
    value = str(record.get(key) or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} : adresse obligatoire.")
        record[key] = ""
        return ""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ValidationError(
            f"{label} : « {value} » n'est pas une adresse IP."
        )
    record[key] = value
    return value


def ip_interface(record, key, label, required=True):
    """Adresse AVEC préfixe (10.7.0.2/32) : c'est ce qu'une interface porte.

    Une adresse sans préfixe est acceptée et complétée en /32 — mais dire
    « 10.7.0.2 » quand on veut dire « /24 » est une erreur silencieuse
    coûteuse, alors le message le rappelle en cas de doute.
    """
    value = str(record.get(key) or "").strip()
    if not value:
        if required:
            raise ValidationError(f"{label} : adresse obligatoire.")
        record[key] = ""
        return ""
    try:
        parsed = ipaddress.ip_interface(value)
    except ValueError:
        raise ValidationError(
            f"{label} : « {value} » refusé. Attendu une adresse avec"
            " préfixe, par exemple 10.7.0.2/32."
        )
    record[key] = str(parsed)
    return record[key]


def cidr_list(routes) -> list[str]:
    """Réseaux normalisés en CIDR. Une adresse seule devient un /32."""
    if routes in (None, ""):
        return []
    if isinstance(routes, str):
        routes = [r for r in re.split(r"[\s,]+", routes) if r]
    if not isinstance(routes, list):
        raise ValidationError("Les routes doivent être une liste de réseaux.")
    clean = []
    for route in routes:
        try:
            network = ipaddress.ip_network(str(route).strip(), strict=False)
        except ValueError as error:
            raise ValidationError(f"Route refusée : « {route} » ({error}).")
        text_form = str(network)
        if text_form not in clean:
            clean.append(text_form)
    return clean
