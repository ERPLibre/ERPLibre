#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une base n'a pas, alors que l'installation par défaut l'aurait.

`conf/module_list_image_db_odoo.json` dit ce qu'ERPLibre embarque : le
package `odoo18.0_base` suggère quinze modules. Rien ne vérifiait qu'une
base DONNÉE les a. C'est pourtant la question qu'on se pose devant une
instance migrée depuis la 12 : elle a traversé six paliers, des modules
ont été désinstallés en chemin pour débloquer une mise à jour, et
personne ne sait plus ce qui manque par rapport à une installation neuve.

Pourquoi pas `image_db.py --check_addons_exist`
-----------------------------------------------
Il répond à une autre question : le module est-il sur le DISQUE. Un
module peut être présent dans le chemin des addons et absent de la base,
ou l'inverse — connu de la base parce qu'il y fut installé, mais son code
n'est plus là. Les deux outils sont complémentaires, aucun ne remplace
l'autre.

Cinq verdicts, pas un seul « manquant »
---------------------------------------
Les confondre rendrait le rapport inutile, car l'action diffère à chaque
fois : un module `available` s'installe d'un clic ; un module `unknown`
demande d'abord de réparer le chemin des addons ; un `uninstallable` a
une dépendance cassée qu'aucune installation ne contournera. Un rapport
qui dit « 7 modules manquants » sans distinguer ces cas oblige à tout
reprendre à la main.

Lecture seule, garantie par le serveur — on inspecte parfois des bases de
migration dont c'est la seule copie.

Codes de sortie : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

import json
import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


SEP = "\x1f"

# Résolu depuis CE fichier, pas depuis le répertoire courant : l'outil est
# lancé aussi bien depuis la racine du dépôt que depuis le menu TODO ou un
# /tmp, et un chemin relatif le faisait échouer en disant « fichier de
# packages illisible » — un diagnostic qui envoyait chercher au mauvais
# endroit.
REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
PACKAGE_FILE = os.path.join(
    REPO_ROOT, "conf", "module_list_image_db_odoo.json"
)

# L'ordre EST la gravité : c'est lui qui décide de la lecture du rapport.
VERDICTS = ("unknown", "uninstallable", "pending", "available", "installed")

# Les états d'`ir_module_module` qu'Odoo peut porter, rangés par verdict.
# Une base en cours de mise à jour reste dans « to install » ou « to
# remove » : ce n'est ni installé ni disponible, c'est inachevé, et le
# dire évite de proposer d'installer ce qui est déjà en route.
ETAT_VERS_VERDICT = {
    "installed": "installed",
    "to upgrade": "installed",
    "to install": "pending",
    "to remove": "pending",
    "uninstalled": "available",
    "uninstallable": "uninstallable",
}

ICONE = {
    "installed": "✅",
    "available": "○",
    "pending": "⏳",
    "uninstallable": "⛔",
    "unknown": "❌",
}


def run_psql(database, sql):
    """Interroger la base en lecture seule, garantie par le SERVEUR.

    `default_transaction_read_only` n'est pas une promesse de l'outil :
    PostgreSQL refusera l'écriture même si le SQL en contenait une.
    """
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAF", SEP, "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return [ligne.split(SEP) for ligne in done.stdout.splitlines() if ligne]


def read_packages(path=PACKAGE_FILE):
    """Le fichier des packages, ou {} s'il est illisible."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            dct = json.load(handle)
    except (OSError, ValueError):
        return {}
    return dct if isinstance(dct, dict) else {}


def package_chain(name, packages):
    """De la racine à `name`, en suivant `base`.

    Un package hérite du sien : `odoo12.0_website` est construit SUR
    l'image `odoo12.0_base`, donc ses modules s'ajoutent à ceux-là. Ne
    lire que le maillon nommé sous-estimerait ce qu'une installation
    embarque, et l'outil déclarerait « rien ne manque » à tort.

    Une boucle dans `base` ferait tourner l'outil indéfiniment : on
    s'arrête au premier nom déjà vu plutôt que de faire confiance au
    fichier.
    """
    chaine = []
    vus = set()
    courant = name
    # Borné par le NOMBRE de packages : une chaîne ne peut pas être plus
    # longue que ce qui existe. La terminaison ne dépend donc pas de la
    # garde `vus` — retirer l'une des deux donne un résultat FAUX, que le
    # test attrape, au lieu d'un outil qui pend, que rien n'attrape.
    for _ in range(len(packages) + 1):
        if not courant or courant not in packages or courant in vus:
            break
        vus.add(courant)
        chaine.append(courant)
        courant = (packages[courant] or {}).get("base") or ""
    chaine.reverse()
    return chaine


def package_modules(name, packages):
    """{module: package qui le suggère}, héritage compris.

    Le package d'ORIGINE est retenu, pas le dernier vu : savoir qu'un
    module vient de `odoo16.0_base` et non de `odoo16.0_website` dit s'il
    est fondamental ou accessoire.
    """
    trouve = {}
    for maillon in package_chain(name, packages):
        for groupe in (packages[maillon] or {}).get("image_list") or []:
            for module in (groupe or {}).get("module") or []:
                trouve.setdefault(module, maillon)
    return trouve


def db_version(database):
    """« 18.0 » d'après le module `base`, ou None.

    C'est la version qu'Odoo lui-même inscrit, pas celle du checkout : une
    base de palier 15 lue depuis un checkout 18 doit se comparer au
    package 15, sans quoi le rapport nommerait des modules qui n'existaient
    pas encore.
    """
    lignes = run_psql(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base'",
    )
    if not lignes or not lignes[0][0]:
        return None
    morceaux = lignes[0][0].split(".")
    if len(morceaux) < 2:
        return None
    return f"{morceaux[0]}.{morceaux[1]}"


def default_package(version):
    """« 18.0 » -> « odoo18.0_base ». None si l'on ne sait pas."""
    return f"odoo{version}_base" if version else None


def column_types(database, table):
    """{colonne: type} pour une table. {} si la base ne répond pas."""
    lignes = run_psql(
        database,
        "SELECT column_name, data_type FROM information_schema.columns"
        f" WHERE table_name = '{table}'",
    )
    return {ligne[0]: ligne[1] for ligne in lignes or [] if len(ligne) >= 2}


def as_text(colonne, types):
    """Lire une colonne en texte, qu'elle soit varchar ou jsonb.

    Les champs traduisibles d'Odoo sont passés en jsonb à la 16 :
    `shortdesc` est un varchar en 12-15 et un `{"en_US": "…"}` ensuite.
    Cet outil vise les bases de PALIER d'une migration, donc les deux
    formes se présentent dans la même session — supposer l'une fait
    échouer la requête entière sur l'autre, et l'outil déclare alors la
    base illisible alors qu'elle se porte bien.
    """
    if types.get(colonne) == "jsonb":
        return (
            f"coalesce({colonne} ->> 'en_US', {colonne} ->> 'fr_FR',"
            f" {colonne} ->> 'fr_CA', '')"
        )
    return f"coalesce({colonne}, '')"


def census(database):
    """{module: (état, résumé, application, auteur)} pour TOUTE la base.

    None si la base ne répond pas — à distinguer d'une base vide, qui
    rendrait un dictionnaire vide et ne veut pas dire la même chose.
    """
    types = column_types(database, "ir_module_module")
    if "name" not in types:
        return None
    lignes = run_psql(
        database,
        f"SELECT name, state, {as_text('shortdesc', types)},"
        " case when application then '1' else '0' end,"
        f" {as_text('author', types)} FROM ir_module_module",
    )
    if lignes is None:
        return None
    return {
        ligne[0]: (ligne[1], ligne[2], ligne[3] == "1", ligne[4])
        for ligne in lignes
        if len(ligne) >= 5
    }


def dependencies(database):
    """{module: [ce dont il dépend]}. {} si la table ne répond pas."""
    lignes = run_psql(
        database,
        "SELECT m.name, d.name FROM ir_module_module_dependency d"
        " JOIN ir_module_module m ON m.id = d.module_id",
    )
    if not lignes:
        return {}
    dct = {}
    for ligne in lignes:
        if len(ligne) >= 2:
            dct.setdefault(ligne[0], []).append(ligne[1])
    return dct


def verdict_of(module, connus):
    """Le verdict d'un module suggéré, d'après ce que la base en sait."""
    if module not in connus:
        return "unknown"
    return ETAT_VERS_VERDICT.get(connus[module][0], "uninstallable")


def blocking_dependencies(module, connus, depend):
    """Ce qu'installer `module` réclamerait et que la base n'a pas.

    Un module « disponible » ne l'est pas toujours vraiment : si trois de
    ses dépendances sont absentes du chemin des addons, l'installer
    échouera. Le dire ici évite de le découvrir en cliquant.
    """
    manquantes = []
    for nom in sorted(set(depend.get(module) or [])):
        if verdict_of(nom, connus) in ("unknown", "uninstallable"):
            manquantes.append(nom)
    return manquantes


def audit(database, package=None, packages=None, path=PACKAGE_FILE):
    """Tout ce que le rapport a besoin de savoir, en une passe."""
    packages = read_packages(path) if packages is None else packages
    connus = census(database)
    if connus is None:
        return {"unavailable": True, "database": database}
    version = db_version(database)
    nom = package or default_package(version)
    suggere = package_modules(nom, packages) if nom else {}
    depend = dependencies(database)

    lignes = []
    for module in sorted(suggere):
        verdict = verdict_of(module, connus)
        etat = connus.get(module, ("", "", False, ""))
        lignes.append(
            {
                "module": module,
                "from": suggere[module],
                "verdict": verdict,
                "state": etat[0],
                "shortdesc": etat[1],
                "needs": (
                    blocking_dependencies(module, connus, depend)
                    if verdict == "available"
                    else []
                ),
            }
        )
    par_etat = {}
    for etat, _desc, _app, _auteur in connus.values():
        par_etat[etat] = par_etat.get(etat, 0) + 1
    installes = {
        nom_mod
        for nom_mod, valeur in connus.items()
        if valeur[0] in ("installed", "to upgrade")
    }
    return {
        "database": database,
        "version": version,
        "package": nom,
        "package_known": bool(nom and nom in packages),
        "chain": package_chain(nom, packages) if nom else [],
        "lines": lignes,
        "by_state": par_etat,
        "total": len(connus),
        "installed": sorted(installes),
        "extra": sorted(installes - set(suggere)),
        "authors": authors_of(connus, installes),
    }


def authors_of(connus, installes):
    """[(auteur, combien)] parmi les modules installés, les gros d'abord.

    « L'ensemble des modules » d'une base ne se lit pas en listant trois
    cents noms : l'auteur dit d'où ils viennent — Odoo, OCA, ou la maison.
    """
    compte = {}
    for nom in installes:
        auteur = (connus[nom][3] or t("unknown author")).strip()
        compte[auteur] = compte.get(auteur, 0) + 1
    return sorted(compte.items(), key=lambda item: (-item[1], item[0]))


def missing(rapport):
    """Les lignes qui réclament une action, les plus graves en tête."""
    ordre = {verdict: rang for rang, verdict in enumerate(VERDICTS)}
    return sorted(
        (
            ligne
            for ligne in rapport.get("lines") or []
            if ligne["verdict"] != "installed"
        ),
        key=lambda ligne: (ordre[ligne["verdict"]], ligne["module"]),
    )


def installable(rapport):
    """Les modules qu'on peut RÉELLEMENT installer, dans l'ordre affiché.

    Seuls les « available » : la base les connaît et ils attendent. Un
    « unknown » n'est pas dans le chemin des addons — l'installer échoue
    avant de commencer ; un « uninstallable » a une dépendance cassée
    qu'aucune installation ne contournera ; un « pending » est déjà en
    route. Les proposer ferait une liste plus longue et trois échecs.
    """
    return [
        ligne["module"]
        for ligne in missing(rapport)
        if ligne["verdict"] == "available"
    ]


def parse_selection(answer, candidates):
    """(choisis, jetons refusés) d'après « 1 3 5 », « a », ou rien.

    Les jetons refusés sont RENDUS, jamais avalés : demander cinq modules
    et en recevoir quatre sans que rien ne le dise est la pire issue —
    on croit l'installation complète. L'appelant doit pouvoir le montrer.

    La virgule vaut l'espace : les listes affichées ailleurs par l'outil
    sont séparées par des virgules, et refuser « 1,3 » ne protégerait de
    rien tout en obligeant à retaper.
    """
    reponse = (answer or "").strip()
    if not reponse:
        return [], []
    if reponse.lower() in ("a", "all"):
        return list(candidates), []
    choisis, refuses, vus = [], [], set()
    for jeton in reponse.replace(",", " ").split():
        if not jeton.isdigit():
            refuses.append(jeton)
            continue
        rang = int(jeton)
        if not 1 <= rang <= len(candidates):
            refuses.append(jeton)
            continue
        nom = candidates[rang - 1]
        if nom not in vus:
            vus.add(nom)
            choisis.append(nom)
    return choisis, refuses


def render(rapport, limit=0):
    """Le rapport, en clair. `limit` borne les listes longues (0 = tout)."""
    if rapport.get("unavailable"):
        return [
            f"❌ {t('Cannot read the database: ')}{rapport['database']}",
        ]
    lignes = [
        f"📦 {t('Modules of')} {rapport['database']}"
        f"  ({t('Odoo')} {rapport['version'] or '?'})",
    ]
    if not rapport["package_known"]:
        # Ne pas se taire : un package inconnu rend TOUT module « manquant »,
        # et l'on croirait à une base vide plutôt qu'à un nom mal choisi.
        lignes.append(
            f"   ⚠ {t('No default package known for this version')}"
            f" ({rapport['package'] or '?'})"
        )
        lignes.append(f"   {t('Compared against nothing — census only.')}")
    else:
        lignes.append(
            f"   {t('Default package:')} {' → '.join(rapport['chain'])}"
            f"  ({len(rapport['lines'])} {t('suggested module(s)')})"
        )
    lignes.append("")

    lignes.append(f"   {t('Census')} : {rapport['total']} {t('known')}")
    for etat, combien in sorted(
        rapport["by_state"].items(), key=lambda item: -item[1]
    ):
        lignes.append(f"       {etat:<16} {combien:>5}")
    if rapport["authors"]:
        lignes.append("")
        lignes.append(f"   {t('Installed modules by author')} :")
        for auteur, combien in rapport["authors"][: limit or None]:
            lignes.append(f"       {auteur[:52]:<54} {combien:>4}")
    lignes.append("")

    absents = missing(rapport)
    if not absents:
        if rapport["package_known"]:
            lignes.append(f"   ✅ {t('Every suggested module is installed.')}")
        return lignes

    lignes.append(
        f"   {len(absents)} {t('suggested module(s) not installed')} :"
    )
    for verdict in VERDICTS:
        groupe = [ligne for ligne in absents if ligne["verdict"] == verdict]
        if not groupe:
            continue
        lignes.append(
            f"     {ICONE[verdict]} {len(groupe)} {t(EXPLICATION[verdict])}"
        )
        for ligne in groupe[: limit or None]:
            detail = (
                f" — {ligne['shortdesc'][:44]}" if ligne["shortdesc"] else ""
            )
            lignes.append(f"         {ligne['module']:<34}{detail}")
            if ligne["needs"]:
                lignes.append(
                    f"             ↳ {t('also needs')} :"
                    f" {', '.join(ligne['needs'][:6])}"
                )
        if limit and len(groupe) > limit:
            lignes.append(f"         … {len(groupe) - limit} {t('more')}")
    return lignes


# Ce qu'il faut FAIRE, pas seulement ce que c'est : un rapport qui nomme
# l'état sans nommer le geste laisse le travail entier à faire.
EXPLICATION = {
    "unknown": "absent from the addons path — sync the repo first",
    "uninstallable": "present but broken — fix the dependency",
    "pending": "half-way — finish the pending update",
    "available": "known to the database — install it",
    "installed": "installed",
}


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "List every module of a database and report which ones the"
            " default ERPLibre package suggests but the database lacks."
        )
    )
    parser.add_argument("-d", "--database", help="database to inspect")
    parser.add_argument(
        "-p",
        "--package",
        help="package to compare against (default: odoo<version>_base)",
    )
    parser.add_argument(
        "--file", default=PACKAGE_FILE, help="package definition file"
    )
    parser.add_argument(
        "--list-packages",
        action="store_true",
        help="print every known package and exit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="cap long lists (0 = no cap)",
    )
    parser.add_argument("--json", action="store_true", help="machine output")
    config = parser.parse_args(argv)

    packages = read_packages(config.file)
    if not packages:
        print(f"❌ {t('Cannot read the package file: ')}{config.file}")
        return 2
    if config.list_packages:
        for nom in sorted(packages):
            combien = len(package_modules(nom, packages))
            marque = (
                " (disabled)" if (packages[nom] or {}).get("disable") else ""
            )
            print(f"{nom:<46} {combien:>4} module(s){marque}")
        return 0
    if not config.database:
        parser.error("--database is required (or use --list-packages)")

    rapport = audit(config.database, package=config.package, packages=packages)
    if rapport.get("unavailable"):
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if config.json:
        print(
            json.dumps(rapport, indent=2, sort_keys=True, ensure_ascii=False)
        )
    else:
        print("\n".join(render(rapport, limit=config.limit)))
    return 1 if missing(rapport) else 0


if __name__ == "__main__":
    sys.exit(main())
