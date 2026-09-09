#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Profils de forge : tout ce qui n'est PAS un secret.

Le partage est net, comme pour les profils VPN : l'adresse de la forge, le
compte propriétaire et la posture TLS vivent ici, en JSON lisible ; le jeton
d'API vit dans le coffre KeePassXC. Un profil peut donc être lu, montré,
comparé et versionné chez un client — sans jamais donner de quoi écrire dans
la forge.

Le fichier d'écriture est `private/todo/todo_override_private.json`, le SEUL
des trois fichiers fusionnés par `ConfigFile.get_config` qui soit gitignored,
et que `set_config_value` écrit en 0600 atomique. La lecture passe par la
fusion : un profil peut aussi venir de `script/todo/todo.json` (partagé par
l'équipe) ou de `private/todo/todo_override.json`.

UN SEUL PILOTE, ET UN CHAMP QUAND MÊME. Forgejo et Gitea servent la même API
v1 — le même client parle aux deux. Le champ « driver » existe pour qu'un
deuxième dialecte n'ait pas à réécrire le format ; il n'en accueille qu'un
pour l'instant, et un nom inconnu est refusé plutôt que deviné.
"""
from __future__ import annotations

import json
import os

# Le MODULE, pas la constante : `CONFIG_OVERRIDE_PRIVATE_FILE` importée par
# valeur figerait le chemin à l'import, et les tests — qui le déplacent dans
# un répertoire temporaire — écriraient dans le vrai fichier de l'utilisateur.
from script.config import config_file as config_module
from script.config.config_file import ConfigFile
from script import lib_valid
from script.forge import valid
from script.lib_valid import NAME_RE, ValidationError

# La clé de section, dans les trois fichiers de configuration.
CONFIG_KEY = "forge"

# Les dialectes d'API connus. Forgejo est un fork de Gitea et sert la même
# API v1 : les distinguer ici serait une différence qui n'existe pas.
DRIVERS = ("forgejo",)


# LE MÊME OBJET, et pas une sous-classe. Un appelant écrit « except
# ProfileError » ou « except ValidationError » selon d'où il vient ; deux
# classes distinctes lui feraient manquer la moitié des refus, et le profil
# invalide passerait pour un profil accepté.
ProfileError = ValidationError


DEFAULTS = {
    "driver": "forgejo",
    # L'adresse de base, sans barre oblique finale — `valid.base_url` la
    # retire : les appels y ajoutent « /api/v1/… ».
    "url": "",
    # Le compte ou l'organisation qui possède les dépôts. Vide, les
    # opérations qui créent un dépôt ne savent pas où le mettre.
    "owner": "",
    # VRAI par défaut. Une forge auto-hébergée porte souvent un certificat
    # signé par soi-même, et la tentation est de couper la vérification pour
    # avancer : le jeton part alors vers qui se présente à la place de la
    # forge. Couper se déclare.
    "verify_tls": True,
    # FAUX par défaut. Autorise http vers une adresse distante, où le jeton
    # voyage en clair dans un en-tête. Vers la boucle locale rien n'est
    # exigé — rien ne passe sur un câble.
    "allow_plaintext": False,
}


# Où le jeton d'un profil est rangé dans le coffre. La forme est celle de
# `script.vault.store`, le magasin de secrets du dépôt : « kdbx:Groupe/Sous/
# Titre ». Pas celle du coffre VPN, qui titre à plat — deux conventions dans
# le même coffre le rendent illisible dans KeePassXC, et un lecteur ne sait
# plus laquelle chercher.
SECRET_GROUP = "ERPLibre/Forge"


def secret_ref(name: str) -> str:
    """Référence du jeton du profil, pour `script.vault.store.SecretStore`.

    Dérivée du nom plutôt que stockée : deux sources de vérité pour un même
    lien finissent toujours par diverger, et un profil renommé chercherait
    son jeton sous l'ancienne référence sans le dire.
    """
    return f"kdbx:{SECRET_GROUP}/{name}"


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

    Une valeur None est IGNORÉE plutôt que recopiée : un champ absent d'un
    fichier JSON et un champ à null décrivent la même chose — « rien de
    dit » — et laisser passer le None écraserait le défaut par lui.
    """
    full = dict(DEFAULTS)
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
    `todo.json`, qui se retrouveraient alors en double à la lecture suivante
    (la fusion étend les listes, elle ne les déduplique pas).
    """
    data = _load_private().get(CONFIG_KEY)
    return (
        [p for p in data if isinstance(p, dict)]
        if isinstance(data, list)
        else []
    )


def save(profile: dict, config=None) -> dict:
    """Valide puis écrit le profil dans le fichier privé.

    Rend le profil normalisé. Lève ProfileError si quelque chose ne va pas —
    et n'écrit RIEN dans ce cas : un profil à moitié valide sur le disque
    est pire qu'un refus, il se relit sans se plaindre.
    """
    clean = validate(profile)
    cfg = config or ConfigFile()
    profiles = [
        p for p in private_profiles() if p.get("name") != clean["name"]
    ]
    profiles.append(clean)
    cfg.set_config_value([CONFIG_KEY], profiles)
    return clean


def delete(name: str, config=None) -> bool:
    """Retire le profil du fichier privé.

    Rend False s'il n'y était pas — un profil venu de `todo.json` n'est pas
    supprimable d'ici, et le dire vaut mieux que de faire semblant.
    """
    profiles = private_profiles()
    kept = [p for p in profiles if p.get("name") != name]
    if len(kept) == len(profiles):
        return False
    cfg = config or ConfigFile()
    cfg.set_config_value([CONFIG_KEY], kept)
    return True


def validate(profile: dict) -> dict:
    """Profil normalisé, ou ProfileError.

    L'ORDRE COMPTE. Les deux drapeaux de posture sont jugés AVANT l'adresse,
    parce que `valid.base_url` lit « allow_plaintext » pour décider si http
    vers une adresse distante passe. Le juger après le laisserait décider
    sur une valeur non normalisée — la chaîne « false », qui est vraie.
    """
    full = with_defaults(profile)
    lib_valid.text(full, "name", "Nom de profil", pattern=NAME_RE)

    pilote = str(full.get("driver") or "").strip()
    if pilote not in DRIVERS:
        raise ProfileError(
            f"Pilote inconnu : « {pilote} »."
            f" Connus : {', '.join(DRIVERS)}."
        )
    full["driver"] = pilote

    lib_valid.flag(full, "verify_tls")
    lib_valid.flag(full, "allow_plaintext")
    valid.base_url(full, "url", "Adresse de la forge")

    lib_valid.text(full, "owner", "Compte propriétaire", pattern=NAME_RE)
    return full
