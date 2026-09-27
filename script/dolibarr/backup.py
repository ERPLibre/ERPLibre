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
laisse ni archive ni morceau.

La base se vide avec le compte de l'instance en développement natif (mot
de passe par l'environnement, jamais sur argv), par sudo en production, et
dans le conteneur de la base pour une instance en conteneurs, qui y lit
son propre secret.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import lib_dolibarr  # noqa: E402

ROOT = new_path
BACKUPS = os.path.join("private", "dolibarr", "backups")

MARIADB_DUMP = [
    "mariadb-dump",
    "--single-transaction",
    "--routines",
    "--triggers",
    "--no-tablespaces",
]
PG_DUMP = ["pg_dump", "--no-owner", "--no-privileges"]


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


class System:
    """Commandes réelles ; les tests en passent un factice."""

    def run_to_file(self, argv, path, env=None):
        full = dict(os.environ, **env) if env else None
        with open(path, "wb") as out:
            try:
                r = subprocess.run(
                    argv, stdout=out, stderr=subprocess.PIPE, env=full
                )
            except OSError as e:
                return 127, str(e)
        return r.returncode, r.stderr.decode("utf-8", "replace")

    def run(self, argv, env=None, stdin_path=None):
        full = dict(os.environ, **env) if env else None
        stdin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        try:
            r = subprocess.run(
                argv, stdin=stdin, capture_output=True, env=full
            )
        except OSError as e:
            return 127, str(e)
        finally:
            if stdin_path:
                stdin.close()
        out = (r.stdout or b"") + (r.stderr or b"")
        return r.returncode, out.decode("utf-8", "replace")

    def http_get(self, url, host):
        from script.dolibarr import native_prod

        return native_prod.http_get(url, host)

    def engine(self, moteur):
        from script.todo import container_runtime

        return container_runtime.etat(moteur)


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
            ["sudo", "cat", os.path.join(htdocs, "conf", "conf.php")]
            if prod
            else os.path.join(htdocs, "conf", "conf.php"),
            None,
        ),
        ("custom.tar", _tar(os.path.join(htdocs, "custom")), None),
    ]


def _private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def create(name, entry, system, dest, stamp):
    """Écrit l'archive de `name` dans `dest` ; rend son chemin, ou None."""
    _private_dir(dest)
    work = tempfile.mkdtemp(prefix=".partial-", dir=dest)
    try:
        for member, argv, env in plan(name, entry, system):
            target = os.path.join(work, member)
            if isinstance(argv, str):
                try:
                    shutil.copyfile(argv, target)
                    code, err = 0, ""
                except OSError as e:
                    code, err = 1, str(e)
            else:
                code, err = system.run_to_file(argv, target, env)
            if code:
                print(t("Cannot save %s:") % member)
                print(err.strip()[-2000:])
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
        with open(
            os.path.join(work, "manifest.json"), "w", encoding="utf-8"
        ) as f:
            f.write(json.dumps(manifest, indent=4, sort_keys=True) + "\n")
        final = os.path.join(dest, f"{name}-{stamp}.tar.gz")
        partial = final + ".part"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with (
            os.fdopen(fd, "wb") as raw,
            tarfile.open(fileobj=raw, mode="w:gz") as tar,
        ):
            for member in sorted(os.listdir(work)):
                tar.add(os.path.join(work, member), arcname=member)
        os.replace(partial, final)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)
        partial = os.path.join(dest, f"{name}-{stamp}.tar.gz.part")
        if os.path.exists(partial):
            os.remove(partial)


def archives(root, name):
    directory = os.path.join(root, BACKUPS, name)
    try:
        found = [f for f in os.listdir(directory) if f.endswith(".tar.gz")]
    except OSError:
        return []
    return [os.path.join(directory, f) for f in sorted(found, reverse=True)]


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
        for name in [args.instance] if args.instance else sorted(known):
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
