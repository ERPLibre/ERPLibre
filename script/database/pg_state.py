#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état du serveur PostgreSQL qu'une migration va utiliser.

Trois défauts font échouer un saut de migration sans que la base y soit
pour rien :

- le serveur en marche n'est plus le binaire installé : une mise à jour du
  paquet remplace les bibliothèques sur disque, mais le serveur démarré
  avant garde l'ancien exécutable. Le premier chargement d'une bibliothèque,
  plpgsql.so par exemple, échoue alors sur « undefined symbol ». Le
  redémarrer suffit ;
- la sauvegarde vient d'un serveur plus récent : un dump ne se restaure que
  dans un serveur de version majeure égale ou supérieure ;
- la cible est Odoo 20 et le serveur est antérieur à 16, le MIN_PG_VERSION
  d'Odoo 20.

`verifier` rend la liste de ces défauts ; les autres fonctions en sont les
pièces, chacune testable sans serveur. Le serveur est joint par psql, avec
l'environnement donné : celui d'Odoo, que db_restore.environnement_pg tire
de config.conf, plus PGHOST et PGPORT du cluster de migration quand la
migration y tourne.

Seul ce qui fera certainement échouer un saut arrête la migration : un
serveur qu'on ne sait pas interroger, ou dont on ne connaît pas le binaire,
n'est qu'un avertissement. Le binaire n'est comparé que pour un serveur
local, joint par son socket Unix : un serveur distant ou dans un conteneur
ne tourne pas sur l'exécutable installé ici.
"""

import os
import re
import shutil
import subprocess

# MIN_PG_VERSION d'Odoo 20 : en dessous, une base échoue sur
# « any_value() n'existe pas ».
PG_MIN_ODOO_20 = 16

ARRET = "arret"
AVERTISSEMENT = "avertissement"

# Ce qu'écrit un serveur qui charge une bibliothèque d'une autre version que
# son exécutable, ou dont la bibliothèque a disparu.
RE_BIBLIOTHEQUE = re.compile(
    r"could not load library|incompatible library", re.IGNORECASE
)
COMMANDE_REDEMARRER = "sudo systemctl restart postgresql"

# Les messages de `verifier`, clés de traduction de todo_i18n.
INJOIGNABLE = "The PostgreSQL server could not be checked: going on."
BINAIRE_INTROUVABLE = (
    "The installed PostgreSQL server binary was not found:"
    " restart PostgreSQL after any update of its package."
)
DECALAGE = (
    "The running PostgreSQL server is not the installed one: restart it."
)
DUMP_PLUS_RECENT = (
    "This backup comes from a newer PostgreSQL than the server:"
    " its restore may fail."
)
TROP_ANCIEN_ODOO_20 = "Odoo 20 needs PostgreSQL 16 or later."


def version_lisible(texte):
    """La version numérique en tête de `texte` (« 18.6 » pour « 18.6
    (Debian 18.6-1.pgdg+1) » ou « postgres (PostgreSQL) 18.6 »), ou None."""
    trouve = re.search(r"(\d+(?:\.\d+)*)", texte or "")
    return trouve.group(1) if trouve else None


def majeure(version):
    """La version majeure d'une version lisible (« 18.6 » → 18), ou None."""
    try:
        return int(str(version).split(".")[0])
    except (TypeError, ValueError):
        return None


def version_serveur(environ=None, lancer=subprocess.run):
    """La version du serveur joint avec `environ` (« 18.6 »), ou None quand
    il ne répond pas. Se branche sur la base « postgres », que tout cluster
    porte."""
    try:
        fait = lancer(
            [
                "psql",
                "-X",
                "-w",
                "-At",
                "-d",
                "postgres",
                "-c",
                "SHOW server_version",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=environ,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if fait.returncode:
        return None
    return version_lisible(fait.stdout)


def version_binaire(bindir, lancer=subprocess.run):
    """La version de l'exécutable postgres de `bindir`, ou None."""
    executable = os.path.join(bindir, "postgres")
    if not os.access(executable, os.X_OK):
        return None
    try:
        fait = lancer(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if fait.returncode:
        return None
    return version_lisible(fait.stdout)


def candidats_bindir_systeme(version_majeure, environ=None):
    """Les répertoires où chercher l'exécutable du serveur du système, dans
    l'ordre d'essai : celui de Debian et d'Ubuntu pour cette version
    majeure, puis celui que déclare pg_config, puis celui de postgres dans
    le PATH (Arch, Fedora)."""
    environ = os.environ if environ is None else environ
    lst = [f"/usr/lib/postgresql/{version_majeure}/bin"]
    pg_config = shutil.which("pg_config", path=environ.get("PATH"))
    if pg_config:
        try:
            sortie = subprocess.run(
                [pg_config, "--bindir"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sortie = ""
        if sortie:
            lst.append(sortie)
    postgres = shutil.which("postgres", path=environ.get("PATH"))
    if postgres:
        lst.append(os.path.dirname(postgres))
    vus = []
    for chemin in lst:
        if chemin not in vus:
            vus.append(chemin)
    return vus


def version_installee(version_majeure, bindirs, lancer=subprocess.run):
    """La version du premier exécutable de `bindirs` de même version
    majeure que le serveur : un autre majeur installé à côté ne dit rien
    du serveur en marche. None si aucun ne correspond."""
    for bindir in bindirs:
        version = version_binaire(bindir, lancer=lancer)
        if version and majeure(version) == version_majeure:
            return version
    return None


def serveur_local(environ):
    """Vrai quand libpq joint le serveur par un socket Unix : PGHOST vide
    ou un répertoire. Un hôte TCP, même « localhost », peut être un
    conteneur ou une autre machine."""
    hote = (environ or {}).get("PGHOST", "")
    return not hote or hote.startswith("/")


def verifier(
    environ=None,
    bindirs=None,
    version_dump=None,
    cible=None,
    lancer=subprocess.run,
):
    """Les défauts du serveur joint avec `environ`, en liste de
    (gravité, clé, valeurs) : `clé` est le message à traduire, `valeurs`
    ce qui le complète. ARRET quand un saut échouerait à coup sûr,
    AVERTISSEMENT quand la migration peut continuer.

    `bindirs` donne où lire la version installée : le cluster de migration
    connaît le sien. None cherche celui du système, et seulement pour un
    serveur local (serveur_local). `version_dump` est la version majeure
    du serveur qui a produit la sauvegarde, `cible` la version d'Odoo
    visée."""
    environ = os.environ if environ is None else environ
    serveur = version_serveur(environ, lancer=lancer)
    if serveur is None:
        return [(AVERTISSEMENT, INJOIGNABLE, ())]
    defauts = []
    serveur_majeure = majeure(serveur)
    if bindirs is None and serveur_local(environ):
        bindirs = candidats_bindir_systeme(serveur_majeure, environ)
    if bindirs is not None:
        installee = version_installee(serveur_majeure, bindirs, lancer=lancer)
        if installee is None:
            defauts.append((AVERTISSEMENT, BINAIRE_INTROUVABLE, ()))
        elif installee != serveur:
            defauts.append((ARRET, DECALAGE, (serveur, installee)))
    # Un dump plus récent passe souvent, à quelques SET près : la
    # restauration le dira mieux qu'une règle.
    if version_dump is not None and version_dump > serveur_majeure:
        defauts.append(
            (AVERTISSEMENT, DUMP_PLUS_RECENT, (version_dump, serveur_majeure))
        )
    if cible is not None and cible >= 20 and serveur_majeure < PG_MIN_ODOO_20:
        defauts.append((ARRET, TROP_ANCIEN_ODOO_20, (serveur_majeure,)))
    return defauts


def bibliotheque_en_cause(lignes):
    """Vrai quand la sortie `lignes` d'une commande montre un serveur qui
    ne charge pas une de ses bibliothèques : le remède est de le
    redémarrer, pas de toucher la base."""
    return any(RE_BIBLIOTHEQUE.search(ligne or "") for ligne in lignes or ())
