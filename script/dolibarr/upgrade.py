#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Monter une instance Dolibarr à la version épinglée.

    ./script/dolibarr/upgrade.py --instance erp [--yes]

La cible est l'épinglage (commit et version ; l'image pour un conteneur).
Descendre est refusé. Même version et même commit : rien à faire. Même
version, autre commit : le schéma a pu changer entre deux commits d'une
même version, la montée se joue quand même (upgrade.php X X).

Une sauvegarde précède tout ; son échec arrête tout. La base dit d'où l'on
part : le plus récent de MAIN_VERSION_LAST_UPGRADE et LAST_INSTALL, qui
reste à la version installée après une montée. upgrade.php et upgrade2.php
se jouent un saut majeur à la fois (upgrade.php ne prend que les scripts
FROM.0.0-* et *-TO.0.0), step5.php une fois.

Les scripts se déverrouillent par upgrade.unlock dans le dossier de
données : dans htdocs, step5 le laisserait et /install s'ouvrirait en
HTTP. Verrouillés, ils sortent 0 sans rien faire, et step5 sort 0 même base
tombée : la réussite se juge au premier code non nul, PUIS à
MAIN_VERSION_LAST_UPGRADE, qui doit valoir la cible. Sinon, retour
arrière : l'ancien code revient et la sauvegarde est restaurée, car un
retour du code seul laisserait une base en avance que rien ne signale.
Le registre ne change qu'après une montée réussie.
"""

import argparse
import json
import os
import re
import shlex
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, lib_dolibarr, restore  # noqa: E402

ROOT = new_path
SYNC_SCRIPT = "./script/manifest/update_manifest_local_dolibarr.sh"
_CONST = "SELECT value FROM llx_const WHERE entity = 0 AND name = '{name}'"

t = backup.t


class UpgradeError(Exception):
    """La montée ne peut pas continuer ; le message dit pourquoi."""


def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def hops(from_v, to_v):
    """[(de, vers)] pour upgrade.php et upgrade2.php, un majeur à la fois."""
    first, last = _version(from_v)[0], _version(to_v)[0]
    points = [from_v] + [f"{m}.0.0" for m in range(first + 1, last)] + [to_v]
    return list(zip(points, points[1:]))


def stop_dev(name, root):
    from script.dolibarr import run

    run.main(["stop", "--instance", name], root=root)


def start_dev(name, root):
    from script.dolibarr import run

    return run.main(["start", "--instance", name], root=root)


def _query(entry, system, name):
    """Valeur de la constante `name` (entité 0), ou "" si illisible."""
    sql = _CONST.format(name=name)
    db = entry["db_name"]
    password = backup._secrets(entry).get("DB_PASSWORD", "")
    if entry.get("db", "mariadb") == "mariadb":
        argv = ["mariadb", "-u", db, "-N", "-D", db, "-e", sql]
        env = {"MYSQL_PWD": password}
    else:
        argv = ["psql", "-h", "127.0.0.1", "-U", db, "-d", db, "-Atc", sql]
        env = {"PGPASSWORD": password}
    code, out = system.run(argv, env=env)
    return out.strip() if not code else ""


def _db_version(entry, system):
    found = [
        _query(entry, system, n)
        for n in ("MAIN_VERSION_LAST_UPGRADE", "MAIN_VERSION_LAST_INSTALL")
    ]
    found = [v for v in found if _version(v)]
    return max(found, key=_version) if found else entry.get("version", "")


def _record(root, name, **fields):
    registry = os.path.join(root, lib_dolibarr.REGISTRY)
    known = lib_dolibarr.load_registry(root)
    known[name].update(fields)
    with open(registry, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"instances": known}, indent=4, sort_keys=True) + "\n"
        )


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _run(system, label, argv, env=None):
    code, out = system.run(argv, env=env)
    if code:
        raise UpgradeError(f"{t(label)} — {out.strip()[-500:]}")
    return out


class NativeDev:
    """Le checkout est le code : il bascule sur le commit épinglé."""

    def __init__(self, name, entry, pin, system, root):
        self.name, self.entry, self.pin = name, entry, pin
        self.system, self.root = system, root
        self.git = ["git", "-C", entry["code_root"]]
        self.htdocs = os.path.join(entry["code_root"], "htdocs")
        self.swapped = False

    def check(self):
        code, out = self.system.run(
            self.git + ["status", "--porcelain", "--untracked-files=no"]
        )
        if code or out.strip():
            raise UpgradeError(
                t("The core is modified in %s: commit or set it aside first.")
                % self.entry["code_root"]
            )

    def run(self, from_v, to_v):
        stop_dev(self.name, self.root)
        commit = self.pin["commit"]
        present = self.git + ["cat-file", "-e", f"{commit}^{{commit}}"]
        if self.system.run(present)[0]:
            _run(self.system, "Checkout synchronized", ["bash", SYNC_SCRIPT])
        _run(
            self.system,
            "Code at the pinned commit",
            self.git + ["checkout", "--detach", commit],
        )
        self.swapped = True
        unlock = os.path.join(self.entry["data_root"], "upgrade.unlock")
        open(unlock, "w").close()
        install = os.path.join(self.htdocs, "install")
        env = None
        for a, b in hops(from_v, to_v):
            for script in ("upgrade.php", "upgrade2.php"):
                self._php(install, f"php {script} {a} {b}", env)
        self._php(install, f"php step5.php {from_v} {to_v}", env)
        got = _query(self.entry, self.system, "MAIN_VERSION_LAST_UPGRADE")
        if got != to_v:
            raise UpgradeError(
                t("The database reads %s, %s expected.") % (got or "?", to_v)
            )
        self.relock()
        start_dev(self.name, self.root)

    def _php(self, directory, command, env):
        _run(
            self.system,
            "Upgrade scripts",
            ["sh", "-c", f"cd {shlex.quote(directory)} && exec {command}"],
            env,
        )

    def relock(self):
        for path in (
            os.path.join(self.entry["data_root"], "upgrade.unlock"),
            os.path.join(self.htdocs, "upgrade.unlock"),
        ):
            _remove(path)
        log = "/tmp/dolibarr_install.log"
        try:
            if os.stat(log).st_uid == os.getuid():
                os.remove(log)
        except OSError:
            pass

    def rollback(self):
        self.relock()
        if self.swapped:
            self.system.run(
                self.git + ["checkout", "--detach", self.entry["commit"]]
            )

    def restart(self):
        start_dev(self.name, self.root)

    def recorded(self):
        return {"version": self.pin["version"], "commit": self.pin["commit"]}


def _runtime(name, entry, pin, system, root):
    if entry.get("runtime") == "native" and entry.get("mode") != "prod":
        return NativeDev(name, entry, pin, system, root)
    raise UpgradeError(t("This runtime is not upgraded by this tool yet."))


def upgrade(name, entry, pin, system, root, stamp):
    """Monte `name` à l'épinglage ; 0 (fait ou rien à faire) ou 1."""
    target, commit = pin["version"], pin["commit"]
    current = entry.get("version", "")
    if _version(target) < _version(current):
        print(
            t("The pin (%s) is older than the instance (%s): no downgrade.")
            % (target, current)
        )
        return 1
    if target == current and commit == entry.get("commit"):
        print(t("Already at %s (%s).") % (target, commit[:7]))
        return 0
    backup_path = None
    try:
        work = _runtime(name, entry, pin, system, root)
        work.check()
        from_v = _db_version(entry, system)
        dest = os.path.join(root, backup.BACKUPS, name)
        backup_path = backup.create(
            name, entry, system, dest, f"pre-upgrade-{stamp}"
        )
        if not backup_path:
            raise UpgradeError(t("The backup failed: nothing was upgraded."))
        print(t("Backup before the upgrade: %s") % backup_path)
        print(t("Upgrading %s from %s to %s.") % (name, from_v, target))
        work.run(from_v, target)
    except UpgradeError as e:
        print(t("Upgrade stopped: %s") % e)
        if backup_path and getattr(work, "swapped", False):
            work.rollback()
            print(t("Rolling back to the backup…"))
            restore.restore(
                name, entry, backup_path, name, system, root, stamp
            )
            work.restart()
        return 1
    _record(root, name, **work.recorded())
    print(t("Dolibarr %s upgraded to %s.") % (name, target))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("--instance", required=True)
    return parser


def main(argv=None, root=None, system=None, now=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    try:
        known = lib_dolibarr.load_registry(root)
        pin = lib_dolibarr.read_pin(root)
    except (lib_dolibarr.RegistryError, lib_dolibarr.PinError) as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    if args.instance not in known:
        print(t("No instance named %s.") % args.instance)
        return 2
    return upgrade(
        args.instance,
        known[args.instance],
        pin,
        system or backup.System(),
        root,
        (now or backup._now)(),
    )


if __name__ == "__main__":
    sys.exit(main())
