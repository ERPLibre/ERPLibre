#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sauvegarder une instance Dolibarr : base, documents, conf.php, custom/.

    ./script/dolibarr/backup.py create --instance erp [--dest DOSSIER]
    ./script/dolibarr/backup.py list [--instance erp]
    ./script/dolibarr/backup.py restore --instance erp --archive CHEMIN \
        --confirm erp

La restauration écrase l'instance : voir restore.py.

Une archive <instance>-<AAAAMMJJ-HHMMSS>.tar.gz porte manifest.json, db.sql,
documents.tar, conf.php et custom.tar. conf.php y est parce que sa clé
d'instance chiffre des valeurs en base : sans elle, une base restaurée
garde des constantes illisibles.

Par défaut sous private/dolibarr/backups/<instance>/ : elle porte les
données d'un client. Archive 0600, dossier 0700 ; un vidage qui échoue ne
laisse ni archive ni morceau. private/ est versionné, ce dossier-ci est
ignoré par private/.gitignore, et create refuse tout dossier où git
pourrait commiter l'archive : elle porte le mot de passe de la base.

La base se vide avec le compte de l'instance en développement natif (mot
de passe par l'environnement, jamais sur argv), par sudo en production, et
dans le conteneur de la base pour une instance en conteneurs, qui y lit
son propre secret.

L'écriture atomique, le refus d'un dossier commitable et le classement
des archives viennent de script/erp_common/archive ; ce module fournit le
plan des membres propre à Dolibarr.
"""

import argparse
import datetime
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import lib_dolibarr  # noqa: E402
from script.erp_common import archive as common_archive  # noqa: E402
from script.erp_common.archive import (  # noqa: E402,F401
    MARIADB_DUMP,
    PG_DUMP,
    committable,
)

ROOT = new_path
_private_dir = common_archive.private_dir
ERP = lib_dolibarr.ERP
BACKUPS = common_archive.backups_dir(ERP)


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


class System(common_archive.System):
    """Commandes, HTTP et moteur réels ; les tests en passent un factice."""

    def http_get(self, url, host):
        from script.dolibarr import native_prod

        return native_prod.http_get(url, host)


def _secrets(entry):
    """{NOM: valeur} du secrets.env d'une instance de développement."""
    path = entry.get("secrets", "").removeprefix("file:")
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                name, sep, value = line.rstrip("\n").partition("=")
                if sep:
                    values[name.strip()] = value
    except OSError:
        pass
    return values


def _tar(directory, sudo=False):
    return (["sudo"] if sudo else []) + [
        "tar",
        "-C",
        directory,
        "-cf",
        "-",
        ".",
    ]


def plan(name, entry, system):
    """[(membre, argv, env)] : ce que produit chaque morceau de l'archive.

    argv vaut un chemin (str) quand le morceau est un fichier lisible tel
    quel : il est copié, sans commande."""
    if entry.get("runtime") == "container":
        from script.todo import container_runtime

        fiche = system.engine(entry["engine"])
        db, web = entry["containers"][0], entry["containers"][1]

        def engine(args):
            return container_runtime.commande(fiche, args)

        dump = " ".join(MARIADB_DUMP + ["-uroot", f"dolibarr_{name}"])
        custom = (
            _tar(entry["custom_dir"])
            if entry.get("custom_dir")
            else engine(
                [
                    "exec",
                    web,
                    "tar",
                    "-C",
                    "/var/www/html/custom",
                    "-cf",
                    "-",
                    ".",
                ]
            )
        )
        return [
            (
                "db.sql",
                engine(
                    [
                        "exec",
                        db,
                        "sh",
                        "-c",
                        'MYSQL_PWD="$(cat /run/secrets/db_root_password)" exec '
                        + dump,
                    ]
                ),
                None,
            ),
            (
                "documents.tar",
                engine(
                    [
                        "exec",
                        web,
                        "tar",
                        "-C",
                        "/var/www/documents",
                        "-cf",
                        "-",
                        ".",
                    ]
                ),
                None,
            ),
            (
                "conf.php",
                engine(["exec", web, "cat", "/var/www/html/conf/conf.php"]),
                None,
            ),
            ("custom.tar", custom, None),
        ]
    prod = entry.get("mode") == "prod"
    db_name = entry["db_name"]
    htdocs = os.path.join(entry["code_root"], "htdocs")
    if prod:
        dump = (
            ["sudo"] + MARIADB_DUMP + [db_name]
            if entry["db"] == "mariadb"
            else ["sudo", "-u", "postgres"] + PG_DUMP + [db_name]
        )
        env = None
    else:
        password = _secrets(entry).get("DB_PASSWORD", "")
        if entry["db"] == "mariadb":
            dump = MARIADB_DUMP + ["-u", db_name, db_name]
            env = {"MYSQL_PWD": password}
        else:
            dump = PG_DUMP + ["-h", "127.0.0.1", "-U", db_name, db_name]
            env = {"PGPASSWORD": password}
    return [
        ("db.sql", dump, env),
        ("documents.tar", _tar(entry["data_root"], sudo=prod), None),
        (
            "conf.php",
            (
                ["sudo", "cat", os.path.join(htdocs, "conf", "conf.php")]
                if prod
                else os.path.join(htdocs, "conf", "conf.php")
            ),
            None,
        ),
        ("custom.tar", _tar(os.path.join(htdocs, "custom")), None),
    ]


def exposed(dest, name, stamp):
    """Les chemins que create écrirait dans `dest` et que git pourrait
    commiter ; conf.php représente le dossier de travail, où la base et
    conf.php sont en clair."""
    return common_archive.exposed(dest, name, stamp, "conf.php")


def create(name, entry, system, dest, stamp):
    """Écrit l'archive de `name` dans `dest` ; rend son chemin, ou None.
    Un `dest` que git pourrait commiter est refusé avant toute écriture."""
    refused = exposed(dest, name, stamp)
    if refused:
        print(
            t(
                "Git could commit this backup, which holds the database"
                " and conf.php:"
            )
        )
        for path in refused:
            print(f"   {path}")
        print(
            t(
                "Choose a folder that git ignores, such as %s, or a"
                " folder outside every repository."
            )
            % os.path.join(BACKUPS, name)
        )
        return None
    manifest = {
        "instance": name,
        "date": stamp,
        "mode": entry.get("mode"),
        "runtime": entry.get("runtime"),
        "db": entry.get("db", "mariadb"),
        "version": entry.get("version"),
        "commit": entry.get("commit"),
    }
    return common_archive.write(
        dest,
        name,
        stamp,
        lambda: plan(name, entry, system),
        manifest,
        system,
    )


def archives(root, name):
    """Les archives de `name`, la plus récente d'abord."""
    return common_archive.archives(ERP, root, name)


def saved_instances(root):
    """Les instances qui ont un dossier de sauvegardes, retirées comprises."""
    return common_archive.saved_instances(ERP, root)


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("create")
    p.add_argument("--instance", required=True)
    p.add_argument("--dest")
    p = sub.add_parser("list")
    p.add_argument("--instance")
    p = sub.add_parser("restore")
    p.add_argument("--instance", required=True)
    p.add_argument("--archive", required=True)
    p.add_argument("--confirm", default="")
    return parser


def _now():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def main(argv=None, root=None, system=None, now=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    try:
        known = lib_dolibarr.load_registry(root)
    except lib_dolibarr.RegistryError as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    if args.action == "list":
        names = sorted(set(known) | set(saved_instances(root)))
        for name in [args.instance] if args.instance else names:
            print(f"== {name}")
            for path in archives(root, name):
                print(
                    f"   {os.path.relpath(path, root)}  {os.path.getsize(path)}"
                )
        return 0
    if args.instance not in known:
        print(t("No instance named %s.") % args.instance)
        return 2
    if args.action == "restore":
        from script.dolibarr import restore

        return restore.restore(
            args.instance,
            known[args.instance],
            args.archive,
            args.confirm,
            system or System(),
            root,
            (now or _now)(),
        )
    dest = args.dest or os.path.join(root, BACKUPS, args.instance)
    path = create(
        args.instance,
        known[args.instance],
        system or System(),
        dest,
        (now or _now)(),
    )
    if not path:
        return 1
    print(t("Backup written: %s") % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
