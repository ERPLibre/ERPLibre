#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Validation des champs de profil, partagée par le format et les pilotes.

Un module à part, et pour une raison précise : `profiles.py` valide ce qui
est commun, chaque pilote valide ses propres champs, et les deux ont besoin
des mêmes contrôles. Le mettre ici évite un import croisé entre le format et
les pilotes — et surtout, ces contrôles ne sont pas cosmétiques : chaque
valeur finit dans un fichier de configuration système et dans une ligne de
commande lancée par sudo. Un nom d'hôte avec un point-virgule doit être
refusé ICI, pas découvert par `sh`.

Chaque fonction NORMALISE en place (`profile[key]` reçoit la valeur propre)
et lève `ProfileError` avec un message destiné à l'humain.
"""
from __future__ import annotations

import ipaddress
import re

# Le nom sert de nom de connexion, de répertoire et de nom de fichier : il
# reste dans un alphabet sans surprise.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
# Nom d'hôte ou adresse, avec un « utilisateur@ » facultatif — sshuttle vise
# une cible SSH, pas seulement une machine. Volontairement plus strict que la
# RFC : ce qui n'est ni lettre, ni chiffre, ni `.-_` est refusé.
SERVER_RE = re.compile(
    r"^([A-Za-z0-9._-]+@)?[A-Za-z0-9][A-Za-z0-9._-]{0,252}$"
)
# Nom d'hôte seul (domaine de recherche DNS, alias) : pas d'« utilisateur@ ».
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
# Clé WireGuard : 32 octets en base64, donc 43 caractères + « = ».
WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")


class ProfileError(ValueError):
    """Profil refusé. Le message est destiné à l'utilisateur."""


def text(profile, key, label, required=True, pattern=None):
    """Champ texte, sans espace de bord, refusé s'il sort du motif."""
    value = str(profile.get(key) or "").strip()
    if not value:
        if required:
            raise ProfileError(f"{label} : valeur obligatoire.")
        profile[key] = ""
        return ""
    if "\n" in value or "\r" in value:
        raise ProfileError(f"{label} : une seule ligne.")
    if pattern and not pattern.match(value):
        raise ProfileError(f"{label} : « {value} » refusé.")
    profile[key] = value
    return value


def path(profile, key, label, required=True):
    """Chemin de fichier. L'existence n'est PAS exigée ici.

    Un profil peut être écrit sur une machine et joué sur une autre ; c'est
    au montage de dire « ce fichier n'est pas là », avec le chemin sous les
    yeux. Ce qui est refusé ici, c'est ce qui casserait un shell.
    """
    value = str(profile.get(key) or "").strip()
    if not value:
        if required:
            raise ProfileError(f"{label} : chemin obligatoire.")
        profile[key] = ""
        return ""
    if any(char in value for char in "\n\r\0"):
        raise ProfileError(f"{label} : chemin illisible.")
    profile[key] = value
    return value


def integer(profile, key, label, low, high):
    try:
        value = int(profile.get(key))
    except (TypeError, ValueError):
        raise ProfileError(f"{label} : nombre entier attendu.")
    if not low <= value <= high:
        raise ProfileError(f"{label} : hors bornes ({low}-{high}) : {value}.")
    profile[key] = value
    return value


def port(profile, key, label):
    return integer(profile, key, label, 1, 65535)


def flag(profile, key):
    profile[key] = bool(profile.get(key))
    return profile[key]


def ip_address(profile, key, label, required=False):
    """Adresse IP nue (pas de préfixe)."""
    value = str(profile.get(key) or "").strip()
    if not value:
        if required:
            raise ProfileError(f"{label} : adresse obligatoire.")
        profile[key] = ""
        return ""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise ProfileError(f"{label} : « {value} » n'est pas une adresse IP.")
    profile[key] = value
    return value


def ip_interface(profile, key, label, required=True):
    """Adresse AVEC préfixe (10.7.0.2/32) : c'est ce qu'une interface porte.

    Une adresse sans préfixe est acceptée et complétée en /32 — mais dire
    « 10.7.0.2 » quand on veut dire « /24 » est une erreur silencieuse
    coûteuse, alors le message le rappelle en cas de doute.
    """
    value = str(profile.get(key) or "").strip()
    if not value:
        if required:
            raise ProfileError(f"{label} : adresse obligatoire.")
        profile[key] = ""
        return ""
    try:
        parsed = ipaddress.ip_interface(value)
    except ValueError:
        raise ProfileError(
            f"{label} : « {value} » refusé. Attendu une adresse avec"
            " préfixe, par exemple 10.7.0.2/32."
        )
    profile[key] = str(parsed)
    return profile[key]


def wg_key(profile, key, label, required=True):
    """Clé publique WireGuard : 32 octets en base64.

    Vérifiée ici parce que `wg-quick` refuse la configuration ENTIÈRE sur
    une clé mal formée, avec un message qui ne dit pas laquelle.
    """
    value = str(profile.get(key) or "").strip()
    if not value:
        if required:
            raise ProfileError(f"{label} : clé obligatoire.")
        profile[key] = ""
        return ""
    if not WG_KEY_RE.match(value):
        raise ProfileError(
            f"{label} : « {value[:12]}… » n'a pas la forme d'une clé"
            " WireGuard (32 octets en base64, 44 caractères finissant par"
            " « = »)."
        )
    profile[key] = value
    return value


def cidr_list(routes) -> list[str]:
    """Réseaux normalisés en CIDR. Une adresse seule devient un /32."""
    if routes in (None, ""):
        return []
    if isinstance(routes, str):
        routes = [r for r in re.split(r"[\s,]+", routes) if r]
    if not isinstance(routes, list):
        raise ProfileError("Les routes doivent être une liste de réseaux.")
    clean = []
    for route in routes:
        try:
            network = ipaddress.ip_network(str(route).strip(), strict=False)
        except ValueError as error:
            raise ProfileError(f"Route refusée : « {route} » ({error}).")
        text_form = str(network)
        if text_form not in clean:
            clean.append(text_form)
    return clean
