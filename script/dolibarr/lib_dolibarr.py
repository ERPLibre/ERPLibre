#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cœur pur de script/dolibarr/ : aucune sortie, aucune commande lancée.

Le menu TODO et les scripts d'installation lisent ici ce qu'ERPLibre a
épinglé et valident ce que l'utilisateur saisit. Tout ce qui touche le
système vit dans les scripts appelants.

L'épinglage tient en deux fichiers. manifest/git_manifest_dolibarr.xml porte
le COMMIT, sous la forme revision="<sha>" upstream="<branche>" que Google
Repo sait synchroniser. conf/supported_version_dolibarr.json porte ce que le
commit ne dit pas sans être récupéré : la version affichée, la branche
suivie, les étiquettes d'images, l'intervalle de PHP. read_pin refuse un
couple incohérent plutôt que d'afficher une version fausse.
"""

import json
import os
import re
import xml.etree.ElementTree as ET

from script.erp_common import instances as common_instances
from script.erp_common import support as common_support
from script.erp_common.instances import (  # noqa: F401
    RegistryError,
    free_port,
    parse_port,
    valid_login,
)
from script.erp_common.support import (  # noqa: F401
    LINUX_FAMILIES,
    NO_DESKTOP,
    NO_ENGINE,
    NO_HOMEBREW,
    NO_NATIVE,
    NO_SYSTEMD,
    container_support,
)

# Nom d'ERP que les fonctions de script/erp_common reçoivent d'ici.
ERP = "dolibarr"

PIN_JSON = os.path.join("conf", "supported_version_dolibarr.json")
PIN_MANIFEST = os.path.join("manifest", "git_manifest_dolibarr.xml")

# Groupe Google Repo du projet Dolibarr dans le manifest.
REPO_GROUP = "dolibarr"

PIN_KEYS = (
    "version",
    "branch",
    "docker_image",
    "mariadb_image",
    "tools_image",
    "php_min",
    "php_max",
)

_SHA = re.compile(r"^[0-9a-f]{40}$")


class PinError(Exception):
    """L'épinglage est absent, illisible ou incohérent."""


def read_pin(root):
    """Rend l'épinglage de Dolibarr lu sous la racine du dépôt `root`.

    Clés rendues : celles de PIN_KEYS, plus « commit » (sha complet du
    manifest) et « path » (chemin du checkout relatif à `root`). Lève
    PinError pour tout défaut, et seulement PinError : l'appelant n'a qu'une
    exception à rattraper pour dire pourquoi Dolibarr n'est pas proposé.
    """
    json_path = os.path.join(root, PIN_JSON)
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise PinError(f"{PIN_JSON}: {e}") from e
    if not isinstance(data, dict):
        raise PinError(f"{PIN_JSON}: not a JSON object")
    missing = [k for k in PIN_KEYS if not data.get(k)]
    if missing:
        raise PinError(f"{PIN_JSON}: missing {', '.join(missing)}")

    manifest_path = os.path.join(root, PIN_MANIFEST)
    try:
        tree = ET.parse(manifest_path)
    except (OSError, ET.ParseError) as e:
        raise PinError(f"{PIN_MANIFEST}: {e}") from e
    project = None
    for node in tree.getroot().iter("project"):
        groups = (node.get("groups") or "").split(",")
        if REPO_GROUP in (g.strip() for g in groups):
            project = node
            break
    if project is None:
        raise PinError(f"{PIN_MANIFEST}: no project in group {REPO_GROUP}")

    commit = project.get("revision") or ""
    if not _SHA.match(commit):
        raise PinError(
            f"{PIN_MANIFEST}: revision {commit!r} is not a full commit"
        )
    upstream = project.get("upstream") or ""
    if upstream != data["branch"]:
        raise PinError(
            f"{PIN_MANIFEST} follows {upstream!r},"
            f" {PIN_JSON} declares {data['branch']!r}"
        )

    pin = {k: str(data[k]) for k in PIN_KEYS}
    pin["commit"] = commit
    pin["path"] = project.get("path") or ""
    return pin


def install_label(key, pin, installed):
    """Libellé de l'entrée du menu d'installation, comme ses voisines Odoo."""
    label = f"{key}: Dolibarr {pin['version']} ({pin['commit'][:7]})"
    if installed:
        label += " - Installed"
    return label


def valid_instance_name(name):
    """Vrai si `name` peut nommer une base, un pool, une unité et un dossier.

    Le compte système « dolibarr_<nom> » borne le nom à 23 caractères.
    """
    return common_instances.valid_instance_name(ERP, name)


# Clé i18n de la raison rendue sous NixOS, où Dolibarr se DÉCLARE
# (services.dolibarr) au lieu de s'installer par script.
NIXOS_DECLARE = (
    "on NixOS, declare services.dolibarr in conf/nixos/erplibre.nix"
)


def native_support(system, family, is_nixos, has_systemd, mode):
    """(True, "") si l'installation native est proposée, sinon (False, raison).

    common_support.native_support avec la raison NixOS de Dolibarr. La
    production native exige systemd : pool php-fpm, vhost et minuterie cron
    en dépendent.
    """
    return common_support.native_support(
        system, family, is_nixos, has_systemd, mode, NIXOS_DECLARE
    )


# L'interpréteur des scripts d'outillage, relatif à la racine du dépôt : le
# menu les lance depuis elle, comme ses voisins (VPN, longtest).
PYTHON = "./.venv.erplibre/bin/python"
RUNTIMES = ("native", "container")

# Les couples (mode, exécution) livrés : le menu n'offre qu'eux, jamais un
# choix qui mènerait à « pas encore disponible ». Un couple s'ajoute quand
# son script existe et que son test l'éprouve.
AVAILABLE = frozenset(
    {("dev", "native"), ("prod", "native"), ("dev", "container")}
)

# Le mot de passe saisi voyage par l'environnement, jamais par argv :
# /proc/<pid>/cmdline est lisible par tout compte de la machine.
ENV_ADMIN_PASSWORD = "EL_DOLIBARR_ADMIN_PASSWORD"


def install_argv(choice):
    """(argv, env) du script d'installation qui répond à `choice`.

    `choice` porte runtime, mode, db, instance, port, admin_login,
    admin_password, et pour une production derrière un nom : domain, tls,
    email. Le conteneur ne prend pas --db : l'image officielle ne
    s'installe d'elle-même que sur MariaDB. Un mot de passe vide n'est pas
    transmis, le script en génère un.
    """
    runtime = choice["runtime"]
    if runtime not in RUNTIMES:
        raise ValueError(f"unknown runtime {runtime!r}")
    argv = [
        PYTHON,
        "-u",
        f"script/dolibarr/install_{runtime}.py",
        "--mode",
        choice["mode"],
        "--instance",
        choice["instance"],
    ]
    if runtime == "native":
        argv += ["--db", choice["db"]]
    if choice.get("port"):
        argv += ["--port", str(choice["port"])]
    if choice.get("domain"):
        argv += ["--domain", choice["domain"], "--tls", choice["tls"]]
        if choice.get("email"):
            argv += ["--email", choice["email"]]
    argv += ["--admin-login", choice["admin_login"]]
    env = {}
    if choice.get("admin_password"):
        env[ENV_ADMIN_PASSWORD] = choice["admin_password"]
    return argv, env


# Registre des instances, relatif à la racine : private/dolibarr/.
REGISTRY = common_instances.registry_path(ERP)


def load_registry(root):
    """Instances connues, {nom: fiche}. {} s'il n'y a pas de registre.

    Un registre illisible lève RegistryError (common_instances.load_registry).
    """
    return common_instances.load_registry(ERP, root)
