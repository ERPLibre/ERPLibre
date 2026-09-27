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

# Nom de base MariaDB/PostgreSQL, de pool php-fpm, d'unité systemd, de
# répertoire et de compte système « dolibarr_<nom> » à la fois : minuscules,
# chiffres et _, une lettre en tête, 2 à 23 caractères, soit 32 préfixe
# compris : la borne portable. useradd refuse un 33e caractère jusqu'à
# shadow 4.13 ; les versions suivantes acceptent jusqu'à 255.
_INSTANCE = re.compile(r"^[a-z][a-z0-9_]{1,22}$")


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
    """Vrai si `name` peut nommer une base, un pool, une unité et un dossier."""
    return bool(_INSTANCE.match(name or ""))


# Identifiant de l'administrateur : il part dans argv et dans la base de
# Dolibarr. ASCII, un premier caractère alphanumérique (pas d'option déguisée
# comme « -x »), 50 caractères au plus.
_LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,49}$")


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


# Familles dont script/todo/todo_install.py monte la commande de paquets, et
# que script/install/install_container.sh sait aussi servir.
LINUX_FAMILIES = ("apt-get", "dnf", "pacman", "zypper")

# Les raisons rendues sont des CLÉS i18n (texte anglais), des fragments que
# l'appelant traduit par t() et place dans « Native is not offered here: %s »
# ou « Docker / Podman is not offered here: %s ».
NO_SYSTEMD = "native production needs systemd"
NO_NATIVE = "unsupported system for a native install"
NIXOS_DECLARE = (
    "on NixOS, declare services.dolibarr in conf/nixos/erplibre.nix"
)
NO_HOMEBREW = "a native install on macOS needs Homebrew"
NO_ENGINE = "no container engine, and none can be installed here"
NO_DESKTOP = "install Docker Desktop first"


def native_support(system, family, is_nixos, has_systemd, mode):
    """(True, "") si l'installation native est proposée, sinon (False, raison).

    `system` est platform.system() ; `family` la famille de paquets (celle de
    todo_install.family(), ou « brew » sous macOS quand Homebrew est là).
    NixOS se DÉCLARE (services.dolibarr) au lieu de s'installer par script.
    La production native exige systemd : pool php-fpm, vhost et minuterie
    cron en dépendent, et macOS n'en a pas.
    """
    if system == "Darwin":
        if family != "brew":
            return False, NO_HOMEBREW
        if mode == "prod":
            return False, NO_SYSTEMD
        return True, ""
    if system != "Linux":
        return False, NO_NATIVE
    if is_nixos:
        return False, NIXOS_DECLARE
    if family not in LINUX_FAMILIES:
        return False, NO_NATIVE
    if mode == "prod" and not has_systemd:
        return False, NO_SYSTEMD
    return True, ""


def container_support(system, family, engine_usable):
    """(True, "") si la voie conteneur est proposée, sinon (False, raison).

    Un moteur qui répond (Docker ou Podman, jugé par container_runtime)
    suffit partout. Sans lui, la voie reste proposée là où
    install_container.sh sait installer un moteur : une famille Linux
    connue. Docker Desktop, lui, ne s'installe pas par script.
    """
    if engine_usable:
        return True, ""
    if system == "Linux":
        if family in LINUX_FAMILIES:
            return True, ""
        return False, NO_ENGINE
    return False, NO_DESKTOP


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


def free_port(start, is_free, limit=100):
    """Premier port >= `start` que `is_free(port)` déclare libre, ou None."""
    for port in range(start, start + limit):
        if is_free(port):
            return port
    return None


# Registre des instances : chemins, hôtes et URL d'une production sont des
# données de client, d'où private/, seul endroit du dépôt permis pour elles.
REGISTRY = os.path.join("private", "dolibarr", "instances.json")


class RegistryError(Exception):
    """Le registre existe mais ne se lit pas."""


def load_registry(root):
    """Instances connues, {nom: fiche}. {} s'il n'y a pas de registre.

    Un registre illisible LÈVE : le rendre vide ferait croire qu'aucune
    instance n'existe, et laisserait installer par-dessus une instance
    vivante.
    """
    path = os.path.join(root, REGISTRY)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RegistryError(f"{REGISTRY}: {e}") from e
    instances = data.get("instances") if isinstance(data, dict) else None
    if not isinstance(instances, dict):
        raise RegistryError(f"{REGISTRY}: no 'instances' object")
    return instances
