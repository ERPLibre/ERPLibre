#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préréglages de site : un profil déjà rempli, sauf ce qui est personnel.

Un préréglage porte ce qu'un établissement publie et qui est le même pour
tout le monde — passerelle, protocole, groupe d'authentification, port,
limites du concentrateur. Il ne porte JAMAIS d'identifiant ni de secret :
c'est ce partage qui lui permet de se distribuer.

C'est donc un profil PARTIEL, sans `name` : le nom appartient à celui qui
crée le profil, parce qu'il aura plusieurs profils sur la même passerelle
(un par identité) et que c'est lui qui les distingue. Un préréglage n'est
pas validé au chargement, seulement quand on l'applique — `profiles.save`
tranche, avec ses messages.

Où ils sont lus, dans l'ordre
-----------------------------
1. `conf/vpn_presets/` — livré avec le dépôt. Il n'y a rien d'identifiant
   dans un dépôt public : ce répertoire ne contient que des gabarits, avec
   des passerelles inventées.
2. `private/vpn/presets/` — ignoré par git. C'est le point de montage d'un
   dépôt privé : les préréglages qui nomment un établissement y vivent, et
   se versionnent là où le dépôt est privé.
3. Les répertoires listés sous `vpn_preset_paths` dans la configuration —
   pour un dépôt privé cloné ailleurs qu'à cet endroit.

Le PLUS TARDIF gagne sur un même identifiant. C'est ce qui permet de
corriger un gabarit du dépôt — une passerelle qui a déménagé, un groupe
renommé — sans modifier un fichier suivi par git, donc sans conflit au
prochain `git pull`.

Un fichier illisible ne fait pas échouer le chargement : il est retenu dans
une liste d'erreurs que l'appelant AFFICHE. Un préréglage fautif rendrait
autrement tous les autres inatteignables, et la panne se lirait « aucun
préréglage » alors qu'il y en a dix.
"""
from __future__ import annotations

import json
import os
import re

from script.config.config_file import ConfigFile
from script.vpn import profiles
from script.vpn.valid import NAME_RE

# Les répertoires livrés, dans l'ordre de lecture. Relatifs à la racine du
# checkout, comme les chemins de `script/config/config_file.py`.
PRESET_DIRS = ("./conf/vpn_presets", "./private/vpn/presets")

# Le seul répertoire où l'outil ÉCRIT. `conf/vpn_presets/` est suivi par
# git et ne reçoit que des gabarits écrits à la main.
PRIVATE_DIR = "./private/vpn/presets"

# Clé de configuration donnant des répertoires SUPPLÉMENTAIRES, lus après
# ceux du dessus.
CONFIG_KEY = "vpn_preset_paths"

# Clés qui décrivent le préréglage lui-même et ne sont pas des champs de
# profil : elles sont retirées par `apply`.
META_KEYS = ("preset", "label", "hint")


def slug_stem(name: str) -> str:
    """Nom de fichier sûr tiré de `name`, « anyconnect » en dernier repli.

    Le nom vient du fichier que l'utilisateur désigne : il finit dans un
    chemin, et « ../../etc/quelque-chose » n'y arrivera pas.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:31]
    return cleaned or "anyconnect"


def save(items: list[dict], stem: str) -> str:
    """Écrit `items` dans `private/vpn/presets/<stem>.json`. Rend le chemin.

    Ce répertoire et pas un autre : `conf/vpn_presets/` est suivi par git,
    et un préréglage importé nomme un établissement, sa passerelle et son
    groupe de connexion. Écrit là, il partirait sur un fork public.

    0600 : rien de tout cela n'est secret, mais rien n'oblige non plus à le
    donner à lire aux autres comptes de la machine.
    """
    os.makedirs(PRIVATE_DIR, mode=0o700, exist_ok=True)
    path = os.path.join(PRIVATE_DIR, f"{stem}.json")
    temporary = f"{path}.tmp"
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as fh:
        json.dump(items, fh, indent=4, ensure_ascii=False)
        fh.write("\n")
    os.replace(temporary, path)
    return path


def preset_dirs(config=None) -> list[str]:
    """Les répertoires à lire, dans l'ordre. Les inexistants restent dans
    la liste : c'est `load_all` qui les saute, et les nommer ici garde
    l'ordre lisible."""
    dirs = list(PRESET_DIRS)
    cfg = config or ConfigFile()
    extra = cfg.get_config(CONFIG_KEY)
    if isinstance(extra, str):
        extra = [extra]
    if isinstance(extra, list):
        dirs += [str(d) for d in extra if isinstance(d, (str, os.PathLike))]
    return dirs


def _read_file(path: str) -> tuple[list[dict], str]:
    """(préréglages, erreur). L'un des deux est vide.

    Un fichier porte un préréglage (objet) ou plusieurs (liste) : un site
    qui en distribue trois n'a pas à ouvrir trois fichiers.
    """
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError) as error:
        return [], f"{path} : {error}"
    items = data if isinstance(data, list) else [data]
    found = []
    for item in items:
        if not isinstance(item, dict):
            return [], f"{path} : un préréglage doit être un objet JSON."
        identifier = str(item.get("preset") or "").strip()
        if not NAME_RE.match(identifier):
            return [], (
                f"{path} : « preset » manquant ou refusé"
                f" (« {identifier} »). Attendu : minuscules, chiffres,"
                " « - » ou « _ »."
            )
        found.append(dict(item, preset=identifier))
    return found, ""


def load_all(config=None) -> tuple[list[dict], list[str]]:
    """(préréglages, erreurs).

    Les préréglages sont rendus dans l'ordre où leur identifiant est
    apparu pour la première fois, et non dans celui du dernier fichier qui
    l'a redéfini : une liste dont les lignes changent de place selon qu'un
    site a surchargé un gabarit se lit mal.
    """
    by_id: dict[str, dict] = {}
    errors: list[str] = []
    for directory in preset_dirs(config):
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".json"):
                continue
            found, error = _read_file(os.path.join(directory, entry))
            if error:
                errors.append(error)
                continue
            for item in found:
                by_id[item["preset"]] = item
    return list(by_id.values()), errors


def load(identifier: str, config=None) -> dict | None:
    """Le préréglage `identifier`, ou None."""
    found, _ = load_all(config)
    for item in found:
        if item["preset"] == identifier:
            return item
    return None


def label(preset: dict) -> str:
    """Ce qu'on affiche. Le `label` s'il est là, l'identifiant sinon : un
    préréglage sans libellé reste choisissable."""
    return str(preset.get("label") or preset["preset"])


def apply(preset: dict, name: str) -> dict:
    """Profil complété par les défauts, prêt pour le formulaire.

    Les clés de description (`META_KEYS`) sont retirées : elles nomment le
    préréglage et n'ont rien à faire dans un profil, où `profiles.validate`
    les ignorerait en silence — et où elles resteraient à traîner dans la
    configuration écrite.

    Un préréglage ne porte ni identifiant ni secret. Ce qui manque est donc
    ce que le formulaire demande ensuite, et c'est voulu.
    """
    draft = {k: v for k, v in preset.items() if k not in META_KEYS}
    draft["name"] = name
    return profiles.with_defaults(draft)
