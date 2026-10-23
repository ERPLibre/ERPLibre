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
import time

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import (  # noqa: E402
    backup,
    container_plan,
    lib_dolibarr,
    packages,
    restore,
)
from script.dolibarr.run import served_version  # noqa: E402

ROOT = new_path
SYNC_SCRIPT = "./script/manifest/update_manifest_local_dolibarr.sh"
_CONST = "SELECT value FROM llx_const WHERE entity = 0 AND name = '{name}'"
_ROOTPW = 'MYSQL_PWD="$(cat /run/secrets/db_root_password)"'
# Relancée sur une nouvelle image, l'entrée migre la base en quelques
# secondes avant d'ouvrir Apache.
WAIT_TRIES = 90
WAIT_PAUSE = 2.0
# Laissés dans le volume par l'entrée de l'image : un vidage complet
# (hachés compris) et le journal HTML de la migration.
_LEFTOVERS = (
    "/var/www/documents/backup-before-upgrade.sql",
    "/var/www/documents/migration_error.html",
)

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


def host_facts(system):
    from script.dolibarr import fleet

    return fleet.host_facts(system)


def _query(entry, system, name):
    """Valeur de la constante `name` (entité 0), ou "" si illisible."""
    sql = _CONST.format(name=name)
    if entry.get("runtime") == "container":
        from script.todo import container_runtime

        fiche = system.engine(entry["engine"])
        db = entry["containers"][0]
        dbn = "dolibarr_" + db.removeprefix("erplibre-dolibarr-").removesuffix(
            "-db"
        )
        code, out = system.run(
            container_runtime.commande(
                fiche,
                [
                    "exec",
                    db,
                    "sh",
                    "-c",
                    f'{_ROOTPW} exec mariadb -uroot -N -D {dbn} -e "{sql}"',
                ],
            )
        )
        return out.strip() if not code else ""
    db = entry["db_name"]
    mariadb = entry.get("db", "mariadb") == "mariadb"
    if entry.get("mode") == "prod":
        argv = (
            ["sudo", "mariadb", "-N", "-D", db, "-e", sql]
            if mariadb
            else ["sudo", "-u", "postgres", "psql", "-d", db, "-Atc", sql]
        )
        code, out = system.run(argv)
        return out.strip() if not code else ""
    password = backup._secrets(entry).get("DB_PASSWORD", "")
    if mariadb:
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

    def target(self):
        """(version visée, identité) : l'identité distingue deux commits
        d'une même version."""
        return self.pin["version"], self.pin["commit"]

    def current(self):
        return self.entry.get("commit")

    def recorded(self):
        return {"version": self.pin["version"], "commit": self.pin["commit"]}


class NativeProd(NativeDev):
    """Le code est exporté dans /opt : le nouveau se prépare à côté, puis
    les deux dossiers permutent avant les scripts, qui incluent depuis
    le document_root de conf.php."""

    def __init__(self, name, entry, pin, system, root):
        super().__init__(name, entry, pin, system, root)
        self.checkout = os.path.join(root, pin["path"])
        self.git = ["git", "-C", self.checkout]
        self.code = entry["code_root"]
        self.user = entry["user"]
        self.timer = entry["cron_timer"]

    def check(self):
        pass

    def run(self, from_v, to_v):
        sudo, code, new = ["sudo"], self.code, self.code + ".new"
        commit = self.pin["commit"]
        present = self.git + ["cat-file", "-e", f"{commit}^{{commit}}"]
        if self.system.run(present)[0]:
            _run(self.system, "Checkout synchronized", ["bash", SYNC_SCRIPT])
        stage = "New code staged"
        for argv in (
            sudo + ["rm", "-rf", new],
            sudo + ["mkdir", "-p", new],
            [
                "bash",
                "-c",
                f"set -o pipefail; git -C {shlex.quote(self.checkout)} archive"
                f" --format=tar {commit} | sudo tar -x -C {shlex.quote(new)}",
            ],
            sudo + ["chown", "-R", "root:root", new],
            sudo + ["chmod", "-R", "go-w", new],
            sudo
            + [
                "cp",
                "-a",
                f"{code}/htdocs/conf/conf.php",
                f"{new}/htdocs/conf/conf.php",
            ],
            sudo
            + [
                "cp",
                "-a",
                "-n",
                f"{code}/htdocs/custom/.",
                f"{new}/htdocs/custom/",
            ],
            sudo
            + [
                "cp",
                "-a",
                f"{code}/htdocs/install.lock",
                f"{new}/htdocs/install.lock",
            ],
        ):
            _run(self.system, stage, argv)
        _run(
            self.system,
            "Scheduled jobs stopped",
            sudo + ["systemctl", "stop", self.timer],
        )
        _run(self.system, "Code swapped", sudo + ["rm", "-rf", f"{code}.prev"])
        _run(self.system, "Code swapped", sudo + ["mv", code, f"{code}.prev"])
        _run(self.system, "Code swapped", sudo + ["mv", new, code])
        self.swapped = True
        data = self.entry["data_root"]
        as_user = ["sudo", "-u", self.user]
        _run(
            self.system,
            "Upgrade scripts",
            as_user + ["touch", f"{data}/upgrade.unlock"],
        )
        install = f"{code}/htdocs/install"
        for a, b in hops(from_v, to_v):
            for script in ("upgrade.php", "upgrade2.php"):
                self._as_user(install, f"php {script} {a} {b}")
        self._as_user(install, f"php step5.php {from_v} {to_v}")
        got = _query(self.entry, self.system, "MAIN_VERSION_LAST_UPGRADE")
        if got != to_v:
            raise UpgradeError(
                t("The database reads %s, %s expected.") % (got or "?", to_v)
            )
        self.relock()
        self.restart()
        base = f"{'http' if self.entry.get('tls') == 'none' else 'https'}://127.0.0.1"
        page = self.system.http_get(base + "/", self.entry.get("domain", ""))
        if served_version(page) != to_v:
            raise UpgradeError(t("The site does not serve %s.") % to_v)

    def _as_user(self, directory, command):
        _run(
            self.system,
            "Upgrade scripts",
            [
                "sudo",
                "-u",
                self.user,
                "sh",
                "-c",
                f"cd {shlex.quote(directory)} && exec {command}",
            ],
        )

    def relock(self):
        data = self.entry["data_root"]
        self.system.run(
            [
                "sudo",
                "rm",
                "-f",
                f"{data}/upgrade.unlock",
                f"{self.code}/htdocs/upgrade.unlock",
            ]
        )
        self.system.run(
            [
                "sudo",
                "find",
                "/tmp",
                "-maxdepth",
                "1",
                "-name",
                "dolibarr_install.log",
                "-user",
                self.user,
                "-delete",
            ]
        )

    def rollback(self):
        self.relock()
        if self.swapped:
            code = self.code
            self.system.run(["sudo", "rm", "-rf", f"{code}.failed"])
            self.system.run(["sudo", "mv", code, f"{code}.failed"])
            self.system.run(["sudo", "mv", f"{code}.prev", code])

    def restart(self):
        facts = host_facts(self.system)
        unit = packages.fpm_layout(facts["family"], facts["php_version"])[
            "unit"
        ]
        self.system.run(["sudo", "systemctl", "reload-or-restart", unit])
        self.system.run(["sudo", "systemctl", "start", self.timer])


class Container:
    """L'entrée de l'image migre la base au démarrage du site, si
    documents/install.lock est absent : ôté, puis le site recréé avec la
    seule image changée. Un saut majeur à la fois."""

    def __init__(self, name, entry, pin, system, root):
        from script.todo import container_runtime

        self.name, self.entry, self.pin = name, entry, pin
        self.system, self.root = system, root
        self.fiche = system.engine(entry["engine"])
        self.cmd = lambda args: container_runtime.commande(self.fiche, args)
        self.db, self.web, self.cron = entry["containers"]
        self.swapped = False
        self.cron_removed = False
        self.unlocked = False

    def target(self):
        image = self.pin["docker_image"]
        return container_plan.image_version(image), image

    def current(self):
        return self.entry.get("image")

    def check(self):
        pass

    def _plan_args(self, image):
        e = self.entry
        state = e["state_dir"]
        engine = {
            "moteur": self.fiche["moteur"],
            "rootless": bool(
                self.fiche["sans_sudo"] and self.fiche.get("rootless")
            ),
        }
        return (
            {"docker_image": image},
            os.path.join(state, "secrets"),
            os.path.join(state, "init.d"),
            e.get("mode", "dev"),
            engine,
        )

    def _web(self, image):
        pin, secrets, init_dir, mode, engine = self._plan_args(image)
        e = self.entry
        return container_plan.run_web(
            self.name,
            pin,
            secrets,
            init_dir,
            mode,
            engine,
            e["port"],
            e["url"],
            e.get("admin_login", "admin"),
            e.get("custom_dir"),
            (os.getuid(), os.getgid()),
        )

    def _cron(self, image):
        pin, secrets, _init, mode, engine = self._plan_args(image)
        e = self.entry
        return container_plan.run_cron(
            self.name,
            pin,
            secrets,
            mode,
            engine,
            e.get("admin_login", "admin"),
            e.get("custom_dir"),
            (os.getuid(), os.getgid()),
        )

    def run(self, from_v, to_v):
        if _version(to_v)[0] - _version(from_v)[0] > 1:
            raise UpgradeError(
                t("The image migrates one major version at a time (%s to %s).")
                % (from_v, to_v)
            )
        image = self.pin["docker_image"]
        _run(self.system, "Image pulled", self.cmd(["pull", image]))
        _run(
            self.system,
            "Containers recreated",
            self.cmd(["rm", "-f", self.cron]),
        )
        self.cron_removed = True
        _run(
            self.system,
            "Install lock removed",
            self.cmd(
                [
                    "exec",
                    self.web,
                    "rm",
                    "-f",
                    "/var/www/documents/install.lock",
                ]
            ),
        )
        self.unlocked = True
        _run(
            self.system,
            "Containers recreated",
            self.cmd(["rm", "-f", self.web]),
        )
        self.swapped = True
        _run(self.system, "Containers recreated", self.cmd(self._web(image)))
        url = self.entry["url"] + "/"
        for attempt in range(WAIT_TRIES):
            if attempt:
                time.sleep(WAIT_PAUSE)
            if served_version(self.system.http_get(url, "127.0.0.1")) == to_v:
                break
        else:
            raise UpgradeError(t("The site does not serve %s.") % to_v)
        got = _query(self.entry, self.system, "MAIN_VERSION_LAST_UPGRADE")
        if got != to_v:
            raise UpgradeError(
                t("The database reads %s, %s expected.") % (got or "?", to_v)
            )
        _run(self.system, "Containers recreated", self.cmd(self._cron(image)))
        self.cron_removed = False
        self.system.run(self.cmd(["exec", self.web, "rm", "-f", *_LEFTOVERS]))

    def rollback(self):
        pass

    def restart(self):
        """Avant la recréation du site : le verrou et les tâches reviennent.
        Après, la restauration a recréé site et tâches sur l'ancienne
        image."""
        if self.swapped:
            return
        if self.unlocked:
            self.system.run(
                self.cmd(
                    [
                        "exec",
                        "-u",
                        "www-data",
                        self.web,
                        "touch",
                        "/var/www/documents/install.lock",
                    ]
                )
            )
        if self.cron_removed:
            self.system.run(self.cmd(self._cron(self.entry["image"])))

    def recorded(self):
        version, image = self.target()
        return {"version": version, "image": image}


def _runtime(name, entry, pin, system, root):
    if entry.get("runtime") == "native" and entry.get("mode") == "prod":
        return NativeProd(name, entry, pin, system, root)
    if entry.get("runtime") == "native":
        return NativeDev(name, entry, pin, system, root)
    if entry.get("runtime") == "container":
        return Container(name, entry, pin, system, root)
    raise UpgradeError(t("This runtime is not upgraded by this tool yet."))


def upgrade(name, entry, pin, system, root, stamp):
    """Monte `name` à l'épinglage ; 0 (fait ou rien à faire) ou 1."""
    try:
        work = _runtime(name, entry, pin, system, root)
    except UpgradeError as e:
        print(t("Upgrade stopped: %s") % e)
        return 1
    target, ident = work.target()
    current = entry.get("version", "")
    if _version(target) < _version(current):
        print(
            t("The pin (%s) is older than the instance (%s): no downgrade.")
            % (target, current)
        )
        return 1
    if target == current and ident == work.current():
        print(t("Already at %s (%s).") % (target, ident[-12:]))
        return 0
    backup_path = None
    try:
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
        if backup_path:
            # Tout ce qui a été arrêté repart ; la base et les fichiers ne
            # reviennent de la sauvegarde que si le code a changé.
            work.rollback()
            if work.swapped:
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
