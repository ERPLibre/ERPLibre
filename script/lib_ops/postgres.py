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
    "'to_upgrade', (SELECT json_agg(name ORDER BY name)"
    " FROM ir_module_module WHERE state = 'to upgrade'),"
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

# Les tâches planifiées actives des modules qui sauvegardent depuis Odoo,
# comptées par modèle sous `auto_backup_crons` ({modèle: nombre}) :
# `db.backup` (auto_backup) et `db.backup.configure` (auto_database_backup).
# `ir.cron` hérite de `ir.actions.server` par `ir_actions_server_id` de la
# 12.0 à la 18.0 ; sans module, aucun modèle ne répond et la clé est nulle.
REQUETE_AUTO_BACKUP = (
    "SELECT json_build_object('auto_backup_crons', (SELECT"
    " json_object_agg(s.model, s.n) FROM (SELECT m.model, count(*) AS n"
    " FROM ir_cron c JOIN ir_act_server a ON a.id = c.ir_actions_server_id"
    " JOIN ir_model m ON m.id = a.model_id"
    " WHERE c.active AND m.model IN ('db.backup', 'db.backup.configure')"
    " GROUP BY m.model) s))"
)

# Les configurations qui donnent du travail à ces tâches, sous la clé
# `configured`, par modèle de REQUETE_AUTO_BACKUP : une tâche active sans
# configuration ne sauvegarde rien (auto_backup installe la sienne active,
# et elle parcourt les enregistrements `db.backup`). auto_database_backup
# ne lance que ses configurations actives ; `row_to_json` lit `active` sans
# échouer là où la colonne manque, et l'y tient pour vraie. Chaque requête
# ne se lance que si son modèle existe, donc sa table aussi.
REQUETES_CONFIG_AUTO_BACKUP = {
    "db.backup": (
        "SELECT json_build_object('configured',"
        " (SELECT count(*) FROM db_backup))"
    ),
    "db.backup.configure": (
        "SELECT json_build_object('configured', (SELECT count(*)"
        " FROM db_backup_configure t"
        " WHERE COALESCE((row_to_json(t)->>'active')::boolean, true)))"
    ),
}

# Les modules installés de la base et ceux marqués `to upgrade`, sous les
# clés `modules` et `to_upgrade` de REQUETE_FAITS : la mise à jour les lit
# quand elle ne sauvegarde pas. `-u` met à jour les uns et les autres.
REQUETE_MODULES = (
    "SELECT json_build_object("
    "'modules', (SELECT json_object_agg(name, latest_version ORDER BY name)"
    " FROM ir_module_module WHERE state = 'installed'),"
    "'to_upgrade', (SELECT json_agg(name ORDER BY name)"
    " FROM ir_module_module WHERE state = 'to upgrade'))"
)

# Les sessions des clients connectés à la base, la sienne exclue. Les
# processus de fond (autovacuum, réplication) portent aussi `datname` :
# seul un `backend_type` « client backend » compte. PostgreSQL 9.x n'a pas
# cette colonne ; `row_to_json` la rend alors nulle, et toute session y
# compte. Un rôle qui n'est pas superutilisateur voit le pid, le rôle et
# l'application des sessions des autres rôles ; leur état est nul.
REQUETE_SESSIONS = (
    "SELECT json_build_object('sessions', (SELECT json_agg(json_build_object("
    "'pid', a.pid, 'user', a.usename, 'application', a.application_name,"
    " 'client', a.client_addr::text, 'state', a.state) ORDER BY a.pid)"
    " FROM pg_stat_activity a WHERE a.datname = current_database()"
    " AND a.pid <> pg_backend_pid()"
    " AND COALESCE(row_to_json(a)->>'backend_type', 'client backend')"
    " = 'client backend'))"
)

REQUETE_BASES = "SELECT datname FROM pg_database"

# Le nombre de sessions de clients de chaque base du serveur, la sienne
# exclue, sous la clé `databases` ({base: nombre}) : redémarrer le serveur
# les coupe toutes. `datname` et `backend_type` se lisent pour les
# sessions de tous les rôles ; PostgreSQL 9.x n'a pas `backend_type`, et
# toute session y compte.
REQUETE_CONNEXIONS = (
    "SELECT json_build_object('databases', (SELECT json_object_agg(d, n)"
    " FROM (SELECT a.datname AS d, count(*) AS n FROM pg_stat_activity a"
    " WHERE a.datname IS NOT NULL AND a.pid <> pg_backend_pid()"
    " AND COALESCE(row_to_json(a)->>'backend_type', 'client backend')"
    " = 'client backend' GROUP BY a.datname) s))"
)

# Le renommage d'une base, lu par psql sur son entrée : les noms viennent
# des variables `ancienne` et `nouvelle` (`-v`), que psql cite comme
# identifiants (`:"nom"`) ; aucun nom n'est interpolé ici.
SCRIPT_RENOMMAGE = 'ALTER DATABASE :"ancienne" RENAME TO :"nouvelle";\n'

# La base `base` fermée aux connexions, puis les sessions que ce rôle peut
# terminer coupées : PostgreSQL refuse de renommer une base où une autre
# session est connectée, et attend quelques secondes la fin de celles qui
# se terminent. Une base fermée n'est plus listée par Odoo (`list_dbs`
# exige `datallowconn`) : ni ses crons ni sa file de courriels ne tournent.
# `pg_has_role(…, 'USAGE')` reprend le droit qu'exige
# `pg_terminate_backend` ; une session d'un rôle hors de portée reste, et
# le renommage le dit.
SCRIPT_FERMETURE = (
    'ALTER DATABASE :"base" WITH ALLOW_CONNECTIONS false;\n'
    "SELECT pg_terminate_backend(a.pid) FROM pg_stat_activity a"
    " WHERE a.datname = :'base' AND a.pid <> pg_backend_pid()"
    " AND pg_has_role(a.usesysid, 'USAGE');\n"
)

# La base `base` rouverte aux connexions.
SCRIPT_OUVERTURE = 'ALTER DATABASE :"base" WITH ALLOW_CONNECTIONS true;\n'

# Vrai sous la clé `createdb` quand le rôle connecté peut créer une base
# (CREATEDB ou superutilisateur) : la restauration crée la copie, et
# `ALTER DATABASE … RENAME` exige ce droit en plus de la propriété.
REQUETE_DROITS = (
    "SELECT json_build_object('createdb', (SELECT rolcreatedb OR rolsuper"
    " FROM pg_roles WHERE rolname = current_user))"
)

# L'empreinte des modules de la base, sous la clé `stamp` : nom, état,
# version et date d'écriture de chaque ligne d'`ir_module_module`. Tout
# `-u`, toute installation et toute mise à jour de la liste des
# applications qui change une ligne la changent.
REQUETE_EMPREINTE_MODULES = (
    "SELECT json_build_object('stamp', (SELECT md5(string_agg(name || ':'"
    " || COALESCE(state, '') || ':' || COALESCE(latest_version, '') || ':'"
    " || COALESCE(write_date::text, ''), ',' ORDER BY name))"
    " FROM ir_module_module))"
)

# Le dossier de données du serveur : lisible par un superutilisateur ou un
# membre de `pg_read_all_settings`.
REQUETE_DOSSIER = "SHOW data_directory"

# Le compte système propriétaire du serveur sur un hôte où PostgreSQL est
# installé par les paquets de la distribution.
COMPTE_SYSTEME = "postgres"

# Délai de connexion de libpq, en secondes : un serveur qui ne répond pas
# rend la main par un refus net au lieu d'attendre le délai du
# sous-processus. Sans effet sur une commande déjà connectée, comme un
# pg_dump long. Un PGCONNECT_TIMEOUT non vide de l'environnement l'emporte.
DELAI_CONNEXION = 10

# `db_host` qui désignent ce même hôte ; une valeur commençant par `/` est
# le dossier d'une socket locale.
HOTES_LOCAUX = ("localhost", "127.0.0.1", "::1")


def _renseigne(valeur):
    valeur = str(valeur if valeur is not None else "").strip()
    return "" if valeur.lower() in VIDES else valeur


def _delai_connexion(environ):
    """PGCONNECT_TIMEOUT : celui de `environ` (os.environ par défaut)
    quand il est renseigné, sinon DELAI_CONNEXION."""
    environ = os.environ if environ is None else environ
    return (environ.get("PGCONNECT_TIMEOUT") or "").strip() or str(
        DELAI_CONNEXION
    )


def env_pg(config, lecture_seule=False, delai=120, environ=None):
    """Les variables à ajouter à l'environnement d'un outil PostgreSQL.

    `config` : la section [options] de la configuration Odoo. `PSQLRC` vide
    écarte un ~/.psqlrc qui changerait la sortie. `PGCONNECT_TIMEOUT` borne
    la connexion (voir DELAI_CONNEXION ; `environ` remplace os.environ pour
    les tests). `lecture_seule` ajoute `PGOPTIONS` (lecture seule,
    `statement_timeout` de `delai` secondes).
    """
    variables = {}
    for cle, nom in CORRESPONDANCE:
        valeur = _renseigne(config.get(cle))
        if valeur:
            variables[nom] = valeur
    variables["PSQLRC"] = ""
    variables["PGCONNECT_TIMEOUT"] = _delai_connexion(environ)
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


def env_pg_local(config, delai=120, environ=None):
    """Les variables d'une requête de lecture par le compte système du
    serveur, sur la socket locale : le port de la configuration, et son
    dossier de socket quand `db_host` en est un. Ni rôle ni mot de passe :
    l'authentification est celle du compte (peer). `PGCONNECT_TIMEOUT` y
    est toujours, valeur de `environ` comprise : l'appelant retire les PG*
    hérités avant d'ajouter ces variables."""
    variables = {
        "PSQLRC": "",
        "PGCONNECT_TIMEOUT": _delai_connexion(environ),
    }
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
