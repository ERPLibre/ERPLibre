#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import re


def odoo_tree_layout(racine):
    """Le lanceur et le dossier d'addons du cœur d'un arbre Odoo complet.

    OpenUpgrade jusqu'à 13 est un tel arbre. En 9.0 et avant, le paquet
    s'appelle openerp : lanceur openerp-server, cœur openerp/addons. Depuis
    10.0 : odoo-bin et odoo/addons. Les chemins gardent la forme de racine.
    """
    if os.path.isdir(os.path.join(racine, "openerp")):
        return (
            os.path.join(racine, "openerp-server"),
            os.path.join(racine, "openerp", "addons"),
        )
    return os.path.join(racine, "odoo-bin"), os.path.join(
        racine, "odoo", "addons"
    )


VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
INSTALLED_ODOO_VERSION_FILE = os.path.join(
    ".repo", "installed_odoo_version.txt"
)
ODOO_VERSION_FILE = ".odoo-version"


def cle_naturelle(erplibre_version):
    """Clé de tri qui compare les nombres d'une version d'ERPLibre comme des
    nombres : « odoo8.0 » avant « odoo20.0 », « python3.12.9 » avant
    « python3.12.10 ». Un tri de texte rend l'inverse dans les deux cas."""
    return [
        int(p) if p.isdigit() else p
        for p in re.split(r"(\d+)", erplibre_version)
    ]


def get_odoo_version() -> tuple[list[dict], list[str], str | None]:
    """
    Read version configuration and return sorted versions,
    installed versions, and current version.
    """
    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)

    if not data_version:
        raise Exception(
            "Internal error, no Odoo version is supported,"
            f" please validate file '{VERSION_DATA_FILE}'"
        )
    version_entries = []
    for key, value in data_version.items():
        version_entries.append(value)
        value["erplibre_version"] = key

    installed_versions = []
    if os.path.exists(INSTALLED_ODOO_VERSION_FILE):
        with open(INSTALLED_ODOO_VERSION_FILE) as txt:
            installed_versions = sorted(txt.read().splitlines())

    odoo_installed_version = None
    if os.path.exists(ODOO_VERSION_FILE):
        with open(ODOO_VERSION_FILE) as txt:
            odoo_installed_version = f"odoo{txt.read().strip()}"

    versions = sorted(
        version_entries, key=lambda k: cle_naturelle(k["erplibre_version"])
    )

    return versions, installed_versions, odoo_installed_version


def postgresql_requise(odoo_version) -> int | None:
    """La version majeure MINIMALE de PostgreSQL qu'exige `odoo_version`
    (« 18.0 »), lue dans le champ « postgresql_version » du catalogue.

    None quand l'entrée ne porte pas ce champ, ou qu'aucune entrée ne
    correspond : l'installeur garde alors son propre plancher. Plusieurs
    entrées de la même Odoo (deux patchs de Python) rendent la plus exigeante.
    """
    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)
    requises = [
        int(value["postgresql_version"])
        for value in data_version.values()
        if value.get("odoo_version") == odoo_version
        and value.get("postgresql_version")
    ]
    return max(requises) if requises else None


def odoo_par_defaut() -> str | None:
    """La version d'Odoo (« 18.0 ») de l'entrée du catalogue marquée
    « default » : celle qu'installe un clone neuf. None si aucune ne l'est."""
    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)
    for value in data_version.values():
        if value.get("default"):
            return value.get("odoo_version")
    return None


def diagnostiquer_version(version_active, versions):
    """Situe la version active (.erplibre-version) parmi les supportées.

    `versions` est la liste que rend get_odoo_version(). Rend
    {"active", "supportee", "remplacante"} : « remplacante » est l'entrée
    supportée de la MÊME version d'Odoo quand l'active ne l'est pas — un
    Python d'un autre patch, typiquement, dont aucun lock ni venv n'est
    fourni —, et None sinon.
    """
    supportee = any(v["erplibre_version"] == version_active for v in versions)
    remplacante = None
    if version_active and not supportee:
        odoo = version_active.split("_python", 1)[0].removeprefix("odoo")
        for version in versions:
            if version.get("odoo_version") == odoo:
                remplacante = version
    return {
        "active": version_active,
        "supportee": supportee,
        "remplacante": remplacante,
    }


# Ce que la mise à jour Python peut faire pour une version supportée.
A_JOUR = "a_jour"  # son venv est complet et actif ou sans rival
MISE_A_JOUR = "mise_a_jour"  # un venv de la même Odoo, autre Python, sert
REPRISE = "reprise"  # son venv existe mais est incomplet
INSTALLATION = "installation"  # aucun venv, mais les sources d'Odoo sont là
SOURCES_ABSENTES = "sources_absentes"  # il faut l'installation complète


def planifier_venvs(versions, venvs, sources, complets=None, active=None):
    """Pour chaque version supportée, ce que la mise à jour Python ferait.

    `versions` est la liste de get_odoo_version() ; `venvs` l'ensemble des
    versions d'ERPLibre qui ont un dossier de venv ; `complets` celles dont
    le venv porte son interpréteur ET son Poetry — par défaut toutes ;
    `sources` les versions d'Odoo dont les sources sont présentes ;
    `active` la version de .erplibre-version.

    Un venv incomplet — une mise à jour interrompue — est proposé à la
    reprise plutôt que donné pour à jour : sans quoi plus rien ne le
    proposerait, et la seule sortie serait l'installation complète. De même,
    un venv supporté complet alors que la version active est encore un
    autre Python de la même Odoo est proposé à l'activation. Sans sources,
    seule l'installation complète, qui synchronise les dépôts git, aide.

    Rend une entrée par version, de la plus récente à la plus ancienne :
    {"cible", "odoo", "python", "poetry", "action", "depuis"}. « depuis »
    est le venv de la même Odoo qu'une mise à jour remplace.
    """
    complets = set(venvs) if complets is None else set(complets)
    plan = []
    for version in sorted(
        versions,
        key=lambda v: cle_naturelle(v["erplibre_version"]),
        reverse=True,
    ):
        cible = version["erplibre_version"]
        odoo = version.get("odoo_version")
        prefixe = f"odoo{odoo}_python"
        autres = sorted(
            (v for v in venvs if v.startswith(prefixe) and v != cible),
            key=cle_naturelle,
        )
        active_rivale = (
            active
            if active and active.startswith(prefixe) and active != cible
            else None
        )
        depuis = None
        if odoo not in sources:
            action = A_JOUR if cible in complets else SOURCES_ABSENTES
        elif cible in venvs and cible not in complets:
            action = REPRISE
        elif cible in complets and active_rivale:
            action, depuis = MISE_A_JOUR, active_rivale
        elif cible in complets:
            action = A_JOUR
        elif autres:
            action, depuis = MISE_A_JOUR, active_rivale or autres[-1]
        else:
            action = INSTALLATION
        plan.append(
            {
                "cible": cible,
                "odoo": odoo,
                "python": version.get("python_version"),
                "poetry": version.get("poetry_version"),
                "action": action,
                "depuis": depuis,
            }
        )
    return plan


if __name__ == "__main__":
    # Depuis la racine du dépôt, une valeur par ligne, vide quand il n'y en
    # a pas :
    #   version_manager.py postgresql_requise 18.0   → la version exigée
    #   version_manager.py odoo_par_defaut           → l'Odoo par défaut
    # Sert aux installeurs shell, qui tournent sur le Python du système
    # avant que le moindre venv existe — d'où rien d'autre que la stdlib ici.
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "postgresql_requise":
        requise = postgresql_requise(sys.argv[2])
        print("" if requise is None else requise)
    elif len(sys.argv) == 2 and sys.argv[1] == "odoo_par_defaut":
        print(odoo_par_defaut() or "")
    else:
        sys.exit(
            f"usage: {sys.argv[0]} postgresql_requise <odoo_version>"
            " | odoo_par_defaut"
        )
