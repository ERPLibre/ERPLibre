#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cluster PostgreSQL 16 de migration, possédé par le compte ERPLibre.

OpenUpgrade a été écrit pour un PostgreSQL qui ne catalogue pas les NOT
NULL ; la migration peut donc tourner sur un second cluster 16, à côté du
serveur du système. Ce cluster vit dans private/postgresql/16 : ses bases
sont des copies de bases clientes. Il n'écoute que sur un socket Unix de
private/postgresql/16/run, sur son propre port : le répertoire de socket
des paquets (/run/postgresql) appartient à l'utilisateur postgres.

Un client s'y branche par PGHOST et PGPORT (commande « env ») : Odoo, psql
et pg_dump les suivent tant que config.conf laisse db_host et db_port à
False, ce qu'écrit generate_config.sh.

Un dump fait par PostgreSQL 17 ou plus récent ne se restaure pas dans un
16 : « dump-version » lit la version d'origine inscrite en tête du
dump.sql d'une sauvegarde.

Codes de sortie : 0 réussi, 1 refusé ou arrêté, 2 binaires 16 introuvables.
"""

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import zipfile

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key):
        return key


VERSION = 16
PORT = 5433
RACINE = os.path.join("private", "postgresql", str(VERSION))
# Ce que le cluster exige de son répertoire de binaires : le serveur et ses
# outils de gestion. Les clients (psql, pg_dump) du système, plus récents,
# savent parler à un serveur 16.
EXECUTABLES = ("initdb", "pg_ctl", "postgres")


def candidats_bindir(version=VERSION, environ=None):
    """Les répertoires où chercher les binaires, dans l'ordre d'essai.

    EL_PG<version>_BINDIR d'abord, puis Debian et Ubuntu (distribution ou
    PGDG), l'AUR d'Arch (postgresql16), le RPM PGDG, et enfin ce que
    déclare un pg_config trouvé dans le PATH.
    """
    environ = os.environ if environ is None else environ
    lst = []
    force = environ.get(f"EL_PG{version}_BINDIR")
    if force:
        lst.append(force)
    lst += [
        f"/usr/lib/postgresql/{version}/bin",
        f"/opt/postgresql{version}/bin",
        f"/usr/pgsql-{version}/bin",
    ]
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
    return list(dict.fromkeys(lst))


def version_majeure(bindir):
    """La version majeure du serveur de bindir, ou None."""
    try:
        sortie = subprocess.run(
            [os.path.join(bindir, "postgres"), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    trouve = re.search(r"\)\s+(\d+)", sortie)
    return int(trouve.group(1)) if trouve else None


def trouver_bindir(version=VERSION, environ=None):
    """Le premier répertoire complet dont le serveur est de cette version."""
    for bindir in candidats_bindir(version, environ):
        if not all(
            os.access(os.path.join(bindir, nom), os.X_OK)
            for nom in EXECUTABLES
        ):
            continue
        if version_majeure(bindir) == version:
            return bindir
    return None


def chemins(racine=RACINE):
    """data, run (socket) et journal du cluster, en chemins absolus."""
    racine = os.path.abspath(racine)
    return (
        os.path.join(racine, "data"),
        os.path.join(racine, "run"),
        os.path.join(racine, "postgresql.log"),
    )


def environnement(racine=RACINE, port=PORT):
    """Les variables qui branchent un client libpq sur le cluster."""
    return {"PGHOST": chemins(racine)[1], "PGPORT": str(port)}


def en_marche(bindir, racine=RACINE):
    data = chemins(racine)[0]
    if not os.path.isfile(os.path.join(data, "PG_VERSION")):
        return False
    done = subprocess.run(
        [os.path.join(bindir, "pg_ctl"), "-D", data, "status"],
        capture_output=True,
        text=True,
    )
    return done.returncode == 0


def demarrer(bindir, racine=RACINE, port=PORT):
    """Initialise le cluster s'il n'existe pas, puis le démarre.

    Rend le code de retour de la dernière commande ; 0 s'il tournait déjà.
    """
    data, run, journal = chemins(racine)
    if en_marche(bindir, racine):
        return 0
    os.makedirs(run, exist_ok=True)
    if not os.path.isfile(os.path.join(data, "PG_VERSION")):
        # --no-locale : encodage UTF8 sans dépendre des locales installées ;
        # trust sur le seul socket local, le cluster n'écoute pas en TCP.
        done = subprocess.run(
            [
                os.path.join(bindir, "initdb"),
                "-D",
                data,
                "-U",
                getpass.getuser(),
                "-E",
                "UTF8",
                "--no-locale",
                "--auth=trust",
            ],
            capture_output=True,
            text=True,
        )
        if done.returncode:
            print(done.stdout + done.stderr, file=sys.stderr)
            return done.returncode
    done = subprocess.run(
        [
            os.path.join(bindir, "pg_ctl"),
            "-D",
            data,
            "-l",
            journal,
            "-w",
            "-o",
            f"-p {port} -k {run} -c listen_addresses=''",
            "start",
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode:
        print(done.stdout + done.stderr, file=sys.stderr)
    return done.returncode


def arreter(bindir, racine=RACINE):
    if not en_marche(bindir, racine):
        return 0
    return subprocess.run(
        [
            os.path.join(bindir, "pg_ctl"),
            "-D",
            chemins(racine)[0],
            "-w",
            "stop",
        ],
        capture_output=True,
        text=True,
    ).returncode


def version_du_dump(chemin_zip):
    """La version majeure du serveur qui a produit le dump.sql, ou None."""
    try:
        with zipfile.ZipFile(chemin_zip) as archive:
            with archive.open("dump.sql") as dump:
                tete = dump.read(4096).decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    trouve = re.search(r"Dumped from database version (\d+)", tete)
    return int(trouve.group(1)) if trouve else None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="PostgreSQL 16 cluster owned by this account, for"
        " migrations."
    )
    parser.add_argument(
        "commande",
        choices=["bindir", "start", "stop", "status", "env", "dump-version"],
    )
    parser.add_argument("zip", nargs="?", help="backup, for dump-version")
    parser.add_argument("--root", default=RACINE)
    parser.add_argument("--port", type=int, default=PORT)
    config = parser.parse_args(argv)

    if config.commande == "dump-version":
        version = version_du_dump(config.zip or "")
        if version is None:
            print(f"❌ {t('No PostgreSQL version in this backup.')}")
            return 1
        print(version)
        return 0
    if config.commande == "env":
        for cle, valeur in environnement(config.root, config.port).items():
            print(f"export {cle}={valeur}")
        return 0

    bindir = trouver_bindir()
    if not bindir:
        print(f"❌ {t('PostgreSQL 16 server binaries not found.')}")
        print(f"   {t('Install them with')}")
        print("   ./script/install/install_postgresql_migration.sh")
        return 2
    if config.commande == "bindir":
        print(bindir)
        return 0
    if config.commande == "status":
        return 0 if en_marche(bindir, config.root) else 1
    if config.commande == "stop":
        return arreter(bindir, config.root)
    return demarrer(bindir, config.root, config.port)


if __name__ == "__main__":
    sys.exit(main())
