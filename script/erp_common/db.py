# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Serveur de base MariaDB ou PostgreSQL d'un installateur natif.

Ces fonctions rendent des commandes et du SQL ; aucune n'exécute, sauf
db_init_commands qui sonde par le Runner reçu. Le SQL est idempotent :
rejoué, il réaligne le compte sur le mot de passe reçu au lieu d'échouer.

Les noms de base et de compte sont interpolés tels quels dans le SQL et
dans pg_hba.conf : l'appelant les a validés (lettres, chiffres, « _ »).
"""

# Familles dont le PostgreSQL s'initialise avec « ident » pour 127.0.0.1.
_IDENT_FAMILIES = ("dnf", "zypper")


def db_name(erp, instance):
    """Nom de la base et du compte d'une instance : « <erp>_<instance> »."""
    return f"{erp}_{instance}"


def db_unit(db):
    """Unité systemd du serveur `db` (« mariadb » ou « postgresql »)."""
    return "mariadb" if db == "mariadb" else "postgresql"


def _root_path_exists(runner, path):
    """Vrai ou faux vu sous sudo ; None en essai à blanc, sans sonde."""
    res = runner.probe(["sudo", "test", "-e", path])
    return None if res is None else res[0] == 0


def db_init_commands(family, db, runner):
    """Commandes d'initialisation du serveur de base, avant de le démarrer.

    Debian/Ubuntu initialisent au postinst ; Fedora/EL et openSUSE au
    premier démarrage de MariaDB ; Arch jamais. PostgreSQL : initdb sur
    Fedora/EL et Arch, automatique ailleurs. Une commande n'est rendue que
    si la sonde constate l'absence du répertoire de données : en essai à
    blanc, la sonde ne tourne pas et la liste reste vide.
    """
    if family == "pacman" and db == "mariadb":
        if _root_path_exists(runner, "/var/lib/mysql/mysql") is False:
            return [
                [
                    "sudo",
                    "mariadb-install-db",
                    "--user=mysql",
                    "--basedir=/usr",
                    "--datadir=/var/lib/mysql",
                ]
            ]
    if family == "pacman" and db == "postgresql":
        if (
            _root_path_exists(runner, "/var/lib/postgres/data/PG_VERSION")
            is False
        ):
            return [
                [
                    "sudo",
                    "-u",
                    "postgres",
                    "initdb",
                    "--locale=C.UTF-8",
                    "--encoding=UTF8",
                    "--auth-local=peer",
                    "--auth-host=scram-sha-256",
                    "-D",
                    "/var/lib/postgres/data",
                ]
            ]
    if family == "dnf" and db == "postgresql":
        if (
            _root_path_exists(runner, "/var/lib/pgsql/data/PG_VERSION")
            is False
        ):
            return [["sudo", "postgresql-setup", "--initdb"]]
    return []


def mariadb_sql(db_name, user, password, charset, collation):
    """SQL de création idempotent de la base `db_name` et du compte `user`.

    Le compte est « @'localhost' » : le compte anonyme que posent certaines
    distributions refuserait un « @'%' » en local. Le jeu de caractères et
    la collation sont ceux que l'ERP attend ; la base les reçoit
    explicitement plutôt que ceux du serveur.
    """
    return (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}`"
        f" CHARACTER SET {charset} COLLATE {collation};\n"
        f"CREATE USER IF NOT EXISTS '{user}'@'localhost'"
        f" IDENTIFIED BY '{password}';\n"
        f"ALTER USER '{user}'@'localhost' IDENTIFIED BY '{password}';\n"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{user}'@'localhost';\n"
        "FLUSH PRIVILEGES;\n"
    )


def postgresql_role_sql(user, password):
    """Rôle idempotent : créé, ou son mot de passe remis."""
    return (
        "DO $$ BEGIN\n"
        f"  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN\n"
        f"    ALTER ROLE {user} LOGIN PASSWORD '{password}';\n"
        "  ELSE\n"
        f"    CREATE ROLE {user} LOGIN PASSWORD '{password}';\n"
        "  END IF;\n"
        "END $$;\n"
    )


def psql(sql_args):
    """argv de psql sous le compte postgres, arrêté à la première erreur."""
    return [
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
    ] + sql_args


def pg_hba_needs_password_line(family):
    """Fedora/EL et openSUSE initialisent avec « ident » pour 127.0.0.1 :
    un mot de passe par TCP y échoue tant qu'une ligne scram-sha-256 ne
    précède pas les lignes ident."""
    return family in _IDENT_FAMILIES


def pg_hba_lines(db_name, user):
    """Lignes pg_hba.conf : `user` sur `db_name` par mot de passe, en local
    TCP (IPv4 et IPv6). À placer avant les lignes ident."""
    return (
        f"host {db_name} {user} 127.0.0.1/32 scram-sha-256\n"
        f"host {db_name} {user} ::1/128 scram-sha-256\n"
    )
