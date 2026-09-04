#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Profils VPN : tout ce qui n'est PAS un secret.

Le partage est net et c'est le cœur du dispositif : l'hôte, l'utilisateur
PPP, les routes et le MTU vivent ici, en JSON lisible ; la clé PSK et les
mots de passe vivent dans le coffre KeePassXC (voir `secrets.py`). Un profil
peut donc être lu, montré, comparé, versionné chez un client — sans jamais
exposer de quoi monter le tunnel.

Le fichier d'écriture est `private/todo/todo_override_private.json`, le SEUL
des trois fichiers fusionnés par `ConfigFile.get_config` qui soit gitignored,
et que `set_config_value` écrit en 0600 atomique. La lecture, elle, passe par
la fusion : un profil peut aussi venir de `script/todo/todo.json` (partagé
par l'équipe) ou de `private/todo/todo_override.json`.

Toute valeur est VALIDÉE avant d'être écrite : elle finira dans un fichier de
configuration et dans une ligne de commande lancée par sudo. Un nom d'hôte
avec une espace ou un point-virgule n'y arrivera pas.
"""
from __future__ import annotations

import json
import os

# Le MODULE, pas la constante : `CONFIG_OVERRIDE_PRIVATE_FILE` importée par
# valeur figerait le chemin à l'import, et les tests — qui le déplacent dans
# un répertoire temporaire — écriraient dans le vrai fichier de l'utilisateur.
from script.config import config_file as config_module
from script.config.config_file import ConfigFile
from script.vpn import valid
from script.vpn.valid import NAME_RE, SERVER_RE, ProfileError  # noqa: F401

# La clé de section, dans les trois fichiers de configuration.
CONFIG_KEY = "vpn"

# Valeurs par défaut COMMUNES à toutes les technologies. Ce qui n'appartient
# qu'à une seule vit dans les `defaults` de son pilote : un profil WireGuard
# n'a rien à faire d'un « port L2TP local », et une liste de champs qui les
# additionne tous devient illisible au troisième pilote.
#
# `default_route` est FAUX par défaut : un tunnel qui capte tout le trafic
# coupe la session SSH en cours et n'est pas ce qu'un déploiement ERPLibre
# distant demande. C'est un choix explicite.
DEFAULTS = {
    "driver": "l2tp_ipsec",
    "server": "",
    "routes": [],
    "default_route": False,
    "mtu": 1280,
    # Adresse TÉMOIN, joignable uniquement à travers le tunnel. Vide,
    # « ça marche » reste une impression ; remplie, le diagnostic peut
    # le PROUVER.
    "probe": "",
}


def secret_title(name: str) -> str:
    """Titre de l'entrée KeePassXC qui porte les secrets du profil.

    Dérivé du nom plutôt que stocké : deux sources de vérité pour un même
    lien finissent toujours par diverger, et un profil renommé chercherait
    un secret sous l'ancien titre sans le dire."""
    return f"ERPLibre VPN / {name}"


def load_all(config=None) -> list[dict]:
    """Tous les profils, dans l'ordre de fusion. Jamais None."""
    cfg = config or ConfigFile()
    data = cfg.get_config(CONFIG_KEY)
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict) and p.get("name")]


def load(name: str, config=None) -> dict | None:
    """Le profil `name`, complété par les défauts, ou None."""
    for profile in load_all(config):
        if profile.get("name") == name:
            return with_defaults(profile)
    return None


def with_defaults(profile: dict) -> dict:
    """Copie du profil où chaque clé connue a une valeur.

    Les défauts du PILOTE sont ajoutés à ceux du format : c'est ce qui
    permet à chaque technologie d'avoir ses propres réglages sans que le
    format les connaisse. Un pilote inconnu ne fait pas échouer la lecture —
    `validate` le dira, avec la liste des pilotes connus.
    """
    from script.vpn.drivers import get_driver

    full = dict(DEFAULTS)
    driver = get_driver(str(profile.get("driver") or DEFAULTS["driver"]))
    if driver is not None:
        full.update(driver.defaults)
    full.update({k: v for k, v in profile.items() if v is not None})
    return full


def names(config=None) -> list[str]:
    return [p["name"] for p in load_all(config)]


def _load_private() -> dict:
    """Contenu brut du fichier privé, {} s'il est absent ou illisible."""
    path = config_module.CONFIG_OVERRIDE_PRIVATE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def private_profiles() -> list[dict]:
    """Les profils du fichier privé SEULS.

    L'écriture doit repartir de cette liste et non de la fusion : réécrire
    la fusion recopierait dans le fichier privé les profils venus de
    `todo.json`, qui se retrouveraient alors en double à la lecture
    suivante (la fusion étend les listes, elle ne les déduplique pas).
    """
    data = _load_private().get(CONFIG_KEY)
    return (
        [p for p in data if isinstance(p, dict)]
        if isinstance(data, list)
        else []
    )


def save(profile: dict, config=None) -> dict:
    """Valide puis écrit le profil dans le fichier privé. Rend le profil
    normalisé. Lève ProfileError si quelque chose ne va pas."""
    clean = validate(profile)
    cfg = config or ConfigFile()
    profiles = [
        p for p in private_profiles() if p.get("name") != clean["name"]
    ]
    profiles.append(clean)
    cfg.set_config_value([CONFIG_KEY], profiles)
    return clean


def delete(name: str, config=None) -> bool:
    """Retire le profil du fichier privé. Rend False s'il n'y était pas —
    un profil venu de `todo.json` n'est pas supprimable d'ici, et le dire
    vaut mieux que de faire semblant."""
    profiles = private_profiles()
    kept = [p for p in profiles if p.get("name") != name]
    if len(kept) == len(profiles):
        return False
    cfg = config or ConfigFile()
    cfg.set_config_value([CONFIG_KEY], kept)
    return True


def validate(profile: dict) -> dict:
    """Profil normalisé, ou ProfileError.

    Deux étages : ce qui vaut pour toute technologie est jugé ici, le reste
    par `validate_profile` du pilote — qui normalise ses champs en place.
    """
    from script.vpn.drivers import driver_names, get_driver

    full = with_defaults(profile)

    valid.text(full, "name", "Nom de profil", pattern=NAME_RE)

    driver_name = str(full.get("driver") or "").strip()
    driver = get_driver(driver_name)
    if driver is None:
        raise ProfileError(
            f"Pilote inconnu : « {driver_name} »."
            f" Connus : {', '.join(driver_names())}."
        )
    full["driver"] = driver_name

    valid.text(full, "server", "Adresse du serveur", pattern=SERVER_RE)
    full["routes"] = valid.cidr_list(full.get("routes"))
    valid.flag(full, "default_route")
    valid.integer(full, "mtu", "MTU", 576, 1500)
    valid.ip_address(full, "probe", "Adresse témoin")

    if (
        driver.needs_routes
        and not full["routes"]
        and not full["default_route"]
    ):
        raise ProfileError(
            "Un tunnel sans route ne sert à rien : déclarer au moins un"
            " réseau à joindre, ou demander la route par défaut."
        )

    driver.validate_profile(full)
    return full
