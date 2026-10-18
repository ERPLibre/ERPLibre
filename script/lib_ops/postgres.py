# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Joindre PostgreSQL comme une instance Odoo le fait, sans psycopg2.

Les outils PostgreSQL (`pg_dump`, `psql`, `createdb`, `dropdb`) se lancent
sous le compte de l'unité, avec les paramètres de connexion de sa
configuration Odoo traduits en variables `PG*` — la même table que
`exec_pg_environ` d'Odoo. Ces variables passent par l'environnement du
processus (`env=` de subprocess), jamais par sa ligne de commande : une
ligne de commande se lit par tous dans `/proc/*/cmdline`, et
`PGPASSWORD` y serait exposé. `runuser -u` sans `-l` garde cet
environnement.

`env_pg` rend seulement les variables à AJOUTER ; l'appelant les pose sur
une copie de son environnement. Une requête de lecture reçoit en plus
`PGOPTIONS` : transaction en lecture seule et durée bornée. pg_dump, la
création, le chargement et la suppression d'une base n'en reçoivent pas —
un `COPY` long serait coupé, une création refusée.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import json
import os
import re

# Paramètres de connexion de la configuration Odoo → variables libpq.
CORRESPONDANCE = (
    ("db_host", "PGHOST"),
    ("db_port", "PGPORT"),
    ("db_user", "PGUSER"),
    ("db_password", "PGPASSWORD"),
    ("db_sslmode", "PGSSLMODE"),
)

# Valeurs de configuration qui veulent dire « non renseigné ».
VIDES = ("", "false", "none")

# Variables d'environnement dont la valeur ne s'affiche jamais.
SECRETS = ("PGPASSWORD",)
MASQUE = "***"

# Un nom de base admis : la règle de `lib_analyse.valid_database_name`, et
# pas d'option déguisée (`-x`). PostgreSQL tronque en silence un nom de
# plus de 63 octets : un `DROP` du nom long viserait alors une AUTRE base.
RE_BASE = re.compile(r"[A-Za-z0-9_.-]+")
LONGUEUR_MAX = 63

# Lignes d'erreur sans conséquence au chargement d'un dump par un rôle qui
# n'est pas superutilisateur : l'extension plpgsql existe déjà et appartient
# au superutilisateur.
ERREURS_BENIGNES = (
    re.compile(r"must be owner of extension"),
    re.compile(r'extension "[^"]+" already exists'),
)
RE_ERREUR = re.compile(r"\bERROR:")

# Ce que la sauvegarde lit de la base, en une requête connectée à la base
# elle-même : aucun nom n'est interpolé dans le SQL.
REQUETE_FAITS = (
    "SELECT json_build_object("
    "'base', (SELECT latest_version FROM ir_module_module"
    " WHERE name = 'base'),"
    "'modules', (SELECT json_object_agg(name, latest_version ORDER BY name)"
    " FROM ir_module_module WHERE state = 'installed'),"
    "'server_version_num', current_setting('server_version_num')::int,"
    "'size', pg_database_size(current_database()),"
    "'stored_attachments', (SELECT count(*) FROM ir_attachment"
    " WHERE store_fname IS NOT NULL))"
)

# Ce qu'une restauration vérifie dans la base chargée.
REQUETE_CONTROLE = (
    "SELECT json_build_object("
    "'tables', (SELECT count(*) FROM information_schema.tables"
    " WHERE table_schema = 'public'),"
    "'base', (SELECT state FROM ir_module_module WHERE name = 'base'),"
    "'modules', (SELECT json_agg(name ORDER BY name) FROM ir_module_module"
    " WHERE state = 'installed'),"
    "'stored_files', (SELECT count(DISTINCT store_fname) FROM ir_attachment"
    " WHERE store_fname IS NOT NULL))"
)

REQUETE_BASES = "SELECT datname FROM pg_database"

# Le dossier de données du serveur : lisible par un superutilisateur ou un
# membre de `pg_read_all_settings`.
REQUETE_DOSSIER = "SHOW data_directory"

# Le compte système propriétaire du serveur sur un hôte où PostgreSQL est
# installé par les paquets de la distribution.
COMPTE_SYSTEME = "postgres"

# `db_host` qui désignent ce même hôte ; une valeur commençant par `/` est
# le dossier d'une socket locale.
HOTES_LOCAUX = ("localhost", "127.0.0.1", "::1")


def _renseigne(valeur):
    valeur = str(valeur if valeur is not None else "").strip()
    return "" if valeur.lower() in VIDES else valeur


def env_pg(config, lecture_seule=False, delai=120):
    """Les variables à ajouter à l'environnement d'un outil PostgreSQL.

    `config` : la section [options] de la configuration Odoo. `PSQLRC` vide
    écarte un ~/.psqlrc qui changerait la sortie. `lecture_seule` ajoute
    `PGOPTIONS` (lecture seule, `statement_timeout` de `delai` secondes).
    """
    variables = {}
    for cle, nom in CORRESPONDANCE:
        valeur = _renseigne(config.get(cle))
        if valeur:
            variables[nom] = valeur
    variables["PSQLRC"] = ""
    if lecture_seule:
        variables["PGOPTIONS"] = (
            "-c default_transaction_read_only=on"
            f" -c statement_timeout={int(delai)}s"
        )
    return variables


def hote_local(config):
    """True si `db_host` de la configuration désigne ce même hôte : vide,
    nom local ou dossier de socket."""
    hote = _renseigne(config.get("db_host"))
    return not hote or hote.startswith("/") or hote in HOTES_LOCAUX


def env_pg_local(config, delai=120):
    """Les variables d'une requête de lecture par le compte système du
    serveur, sur la socket locale : le port de la configuration, et son
    dossier de socket quand `db_host` en est un. Ni rôle ni mot de passe :
    l'authentification est celle du compte (peer)."""
    variables = {"PSQLRC": ""}
    port = _renseigne(config.get("db_port"))
    if port:
        variables["PGPORT"] = port
    hote = _renseigne(config.get("db_host"))
    if hote.startswith("/"):
        variables["PGHOST"] = hote
    variables["PGOPTIONS"] = (
        "-c default_transaction_read_only=on"
        f" -c statement_timeout={int(delai)}s"
    )
    return variables


def masquer(variables):
    """Une copie de `variables` où les secrets sont remplacés par ***."""
    return {
        cle: (MASQUE if cle in SECRETS and valeur else valeur)
        for cle, valeur in variables.items()
    }


def outil(nom, config, existe=os.path.isfile):
    """Le chemin de l'outil `nom` : dans `pg_path` de la configuration
    quand il y est (comme `find_pg_tool` d'Odoo), sinon le nom seul,
    cherché dans le PATH."""
    dossier = _renseigne(config.get("pg_path"))
    if dossier:
        chemin = os.path.join(os.path.expanduser(dossier), nom)
        if existe(chemin):
            return chemin
    return nom


def nom_valide(nom):
    """True si `nom` est un nom de base sûr : caractères admis, pas de
    tiret en tête, au plus 63 octets."""
    return (
        bool(nom)
        and RE_BASE.fullmatch(nom) is not None
        and not nom.startswith("-")
        and len(nom.encode("utf-8")) <= LONGUEUR_MAX
    )


def nom_temporaire(base, horodatage, suffixe="_restoretest_"):
    """`<base><suffixe><horodatage>`, la partie `base` raccourcie pour que
    le tout tienne en 63 octets. L'horodatage reste entier : c'est lui qui
    rend le nom unique."""
    fin = suffixe + horodatage
    place = LONGUEUR_MAX - len(fin.encode("utf-8"))
    return base[: max(place, 1)] + fin


def lire_json(sortie):
    """Le premier objet JSON d'une sortie `psql -tA`, ou None."""
    for ligne in (sortie or "").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("{"):
            try:
                return json.loads(ligne)
            except ValueError:
                return None
    return None


def version_pg(numero):
    """La version courte que le manifeste d'Odoo écrit, depuis
    `server_version_num` : `"%d.%d" % divmod(n / 100, 100)` chez Odoo, soit
    160004 → "16.0", 90624 → "9.6"."""
    numero = int(numero)
    return f"{numero // 10000}.{(numero // 100) % 100}"


def erreurs_graves(lignes):
    """Les lignes `ERROR:` de `lignes` qui ne sont pas bénignes."""
    return [
        ligne
        for ligne in lignes
        if RE_ERREUR.search(ligne)
        and not any(motif.search(ligne) for motif in ERREURS_BENIGNES)
    ]
