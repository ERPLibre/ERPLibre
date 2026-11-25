# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Instances d'un ERP : validation des saisies et registre local.

Fonctions pures : aucune sortie, aucune commande lancée. Le nom de l'ERP,
reçu en premier argument, fixe la borne du nom d'instance et le chemin du
registre, private/<erp>/instances.json.
"""

import json
import os
import re

# Longueur maximale d'un nom de compte système portable : useradd refuse un
# 33e caractère jusqu'à shadow 4.13 ; les versions suivantes acceptent
# jusqu'à 255.
_ACCOUNT_MAX = 32

# Identifiant de l'administrateur : il part dans argv et dans la base de
# l'ERP. ASCII, un premier caractère alphanumérique (pas d'option déguisée
# comme « -x »), 50 caractères au plus.
_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,49}$")


def instance_name_max(erp):
    """Longueur maximale d'un nom d'instance de l'ERP `erp`.

    Le nom d'instance devient, préfixé de « <erp>_ », un nom de base, de
    pool, d'unité systemd, de répertoire et de compte système : le préfixe
    compris, il tient dans _ACCOUNT_MAX caractères.
    """
    return _ACCOUNT_MAX - len(erp) - 1


def valid_instance_name(erp, name):
    """Vrai si `name` peut nommer une base, un pool, une unité et un dossier.

    Minuscules, chiffres et _, une lettre en tête, de 2 caractères à
    instance_name_max(erp). Lève ValueError si `erp` est trop long pour
    laisser place à un nom de 2 caractères.
    """
    longest = instance_name_max(erp)
    if longest < 2:
        raise ValueError(f"ERP name {erp!r} leaves no room for an instance")
    pattern = r"^[a-z][a-z0-9_]{1,%d}$" % (longest - 1)
    return bool(re.match(pattern, name or ""))


def valid_login(login):
    """Vrai si `login` peut servir d'identifiant d'administrateur."""
    return bool(_LOGIN.match(login or ""))


def parse_port(text, default):
    """Port saisi (vide = `default`), ou None s'il est invalide.

    Sous 1024, un port est privilégié : le compte de l'utilisateur ne
    l'ouvre pas, et la production passe de toute façon par nginx.
    """
    text = (text or "").strip()
    if not text:
        return default
    if not text.isdigit():
        return None
    port = int(text)
    if 1024 <= port <= 65535:
        return port
    return None


def free_port(start, is_free, limit=100):
    """Premier port >= `start` que `is_free(port)` déclare libre, ou None."""
    for port in range(start, start + limit):
        if is_free(port):
            return port
    return None


def registry_path(erp):
    """Chemin du registre des instances de `erp`, relatif à la racine.

    Chemins, hôtes et URL d'une production sont des données de client, d'où
    private/, seul endroit du dépôt permis pour elles. Le registre décrit
    une machine : une règle de private/.gitignore propre à chaque ERP
    l'exclut du dépôt versionné.
    """
    return os.path.join("private", erp, "instances.json")


class RegistryError(Exception):
    """Le registre existe mais ne se lit pas."""


def load_registry(erp, root):
    """Instances connues de `erp` sous la racine `root`, {nom: fiche}.

    {} s'il n'y a pas de registre. Un registre illisible LÈVE RegistryError,
    dont le message nomme le chemin relatif : le rendre vide ferait croire
    qu'aucune instance n'existe, et laisserait installer par-dessus une
    instance vivante.
    """
    rel = registry_path(erp)
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RegistryError(f"{rel}: {e}") from e
    instances = data.get("instances") if isinstance(data, dict) else None
    if not isinstance(instances, dict):
        raise RegistryError(f"{rel}: no 'instances' object")
    return instances
