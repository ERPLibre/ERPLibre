#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Restaurer une sauvegarde sur une instance inscrite : écrase ses données.

    ./script/dolibarr/backup.py restore --instance erp \\
        --archive private/dolibarr/backups/erp/erp-….tar.gz --confirm erp

Rien ne s'écrase sans --confirm égal au nom de l'instance. Avant tout, une
sauvegarde de sûreté de l'état courant (pre-restore-<date>) : si elle
échoue, rien n'est touché ; si la restauration échoue ensuite, le message
la nomme. Une sauvegarde plus récente que le code de l'instance est
refusée : ses tables attendraient un code qui n'est pas là.

La base est recréée puis chargée ; documents/ et custom/ sont vidés puis
extraits ; les tâches planifiées sont arrêtées pendant ce temps. La clé
d'instance de la sauvegarde remplace celle de l'instance quand elles
diffèrent (instance réinstallée, ou clonage vers une instance neuve) : les
valeurs chiffrées en base ne se lisent qu'avec elle. En conteneurs, site et
tâches sont recréés, l'image réécrivant conf.php depuis ses variables.

Une archive dont un membre sortirait de son dossier à l'extraction (chemin
absolu, « .. », lien vers l'extérieur) est refusée avant toute écriture.
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
import time

from script.dolibarr import backup, container_plan, install_files
from script.dolibarr.run import served_version

MEMBERS = {
    "manifest.json",
    "db.sql",
    "documents.tar",
    "conf.php",
    "custom.tar",
}
_UNIQUE_ID = re.compile(
    r"^\$dolibarr_main_instance_unique_id\s*=\s*'([^']*)'", re.M
)
_ROOTPW = 'MYSQL_PWD="$(cat /run/secrets/db_root_password)"'
WAIT_TRIES = 90
WAIT_PAUSE = 2.0

# Remet la clé cron de l'instance en base : restaurée, la base porte celle
# de la sauvegarde, et un clone enverrait la sienne, refusée à chaque
# passage. La clé arrive par stdin ou par le fichier secret, jamais sur
# argv ; %s est le chemin de master.inc.php.
_CRON_KEY_PHP = (
    'require "%s"; require_once DOL_DOCUMENT_ROOT."/core/lib/admin.lib.php";'
    " $k = trim(%s);"
    ' if (!preg_match("/^[A-Za-z0-9]+$/", $k)) exit(1);'
    ' exit(dolibarr_set_const($db, "CRON_KEY", $k, "chaine", 0, "", 0) < 0'
    " ? 1 : 0);"
)

t = backup.t


class RestoreError(Exception):
    """La restauration ne peut pas continuer ; le message dit pourquoi."""


def unique_id(conf_text):
    m = _UNIQUE_ID.search(conf_text or "")
    return m.group(1) if m else None


def _version(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def _check_tar(path):
    """Refuse un tar dont un membre sortirait du dossier d'extraction."""
    try:
        with tarfile.open(path) as tar:
            for member in tar.getmembers():
                tarfile.data_filter(member, "/nonexistent-dest")
    except (tarfile.TarError, OSError) as e:
        raise RestoreError(t("Unsafe or unreadable archive: %s") % e)


def read_archive(path, work):
    """Extrait l'archive dans `work`, en vérifie les membres ; rend le
    manifeste."""
    try:
        with tarfile.open(path) as tar:
            names = set(tar.getnames())
            if names != MEMBERS:
                raise RestoreError(t("Not a Dolibarr backup: %s") % path)
            tar.extractall(work, filter="data")
    except (tarfile.TarError, OSError) as e:
        raise RestoreError(t("Unsafe or unreadable archive: %s") % e)
    for member in ("documents.tar", "custom.tar"):
        _check_tar(os.path.join(work, member))
    with open(os.path.join(work, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def _empty(directory):
    for name in os.listdir(directory):
        full = os.path.join(directory, name)
        if os.path.isdir(full) and not os.path.islink(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


def _replace_dir(directory, tar_path):
    os.makedirs(directory, exist_ok=True)
    _empty(directory)
    with tarfile.open(tar_path) as tar:
        tar.extractall(directory, filter="data")


def _sudo_read(system, path):
    code, out = system.run(["sudo", "cat", path])
    if code:
        raise RestoreError(t("Cannot read %s.") % path)
    return out


class Steps:
    """Les opérations, dans l'ordre, pour une instance et une archive."""

    def __init__(self, name, entry, work, system):
        self.name, self.entry, self.work, self.system = (
            name,
            entry,
            work,
            system,
        )
        self.done = []

    def run(self, label, argv, env=None, stdin=None):
        code, out = self.system.run(
            argv,
            env=env,
            stdin_path=os.path.join(self.work, stdin) if stdin else None,
        )
        if code:
            raise RestoreError(f"{t(label)} — {out.strip()[-500:]}")
        self.done.append(label)

    def local(self, label, action, *args):
        try:
            action(*args)
        except OSError as e:
            raise RestoreError(f"{t(label)} — {e}")
        self.done.append(label)

    def backup_key(self):
        with open(os.path.join(self.work, "conf.php"), encoding="utf-8") as f:
            return unique_id(f.read())


def _native_dev(s):
    e = s.entry
    db = e["db_name"]
    password = backup._secrets(e).get("DB_PASSWORD", "")
    if e["db"] == "mariadb":
        env = {"MYSQL_PWD": password}
        s.run(
            "Database recreated",
            [
                "mariadb",
                "-u",
                db,
                "-e",
                f"DROP DATABASE IF EXISTS {db}; CREATE DATABASE {db}"
                " CHARACTER SET utf8 COLLATE utf8_unicode_ci;",
            ],
            env,
        )
        s.run("Database loaded", ["mariadb", "-u", db, db], env, "db.sql")
    else:
        env = {"PGPASSWORD": password}
        psql = [
            "psql",
            "-h",
            "127.0.0.1",
            "-U",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            db,
        ]
        s.run(
            "Database recreated",
            psql + ["-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"],
            env,
        )
        s.run("Database loaded", psql, env, "db.sql")
    htdocs = os.path.join(e["code_root"], "htdocs")
    s.local(
        "Documents replaced",
        _replace_dir,
        e["data_root"],
        os.path.join(s.work, "documents.tar"),
    )
    s.local(
        "Modules replaced",
        _replace_dir,
        os.path.join(htdocs, "custom"),
        os.path.join(s.work, "custom.tar"),
    )
    key = s.backup_key()
    conf = os.path.join(htdocs, "conf", "conf.php")
    with open(conf, encoding="utf-8") as f:
        text = f.read()
    if key and unique_id(text) != key:
        mode = os.stat(conf).st_mode & 0o777
        new = install_files.set_conf_values(text, {"instance_unique_id": key})

        def write():
            with open(conf, "w", encoding="utf-8") as f:
                f.write(new)
            os.chmod(conf, mode)

        s.local("Instance key restored", write)


def _native_prod(s):
    e = s.entry
    db, user, timer = e["db_name"], e["user"], e["cron_timer"]
    htdocs = os.path.join(e["code_root"], "htdocs")
    s.run("Scheduled jobs stopped", ["sudo", "systemctl", "stop", timer])
    if e["db"] == "mariadb":
        s.run(
            "Database recreated",
            [
                "sudo",
                "mariadb",
                "-e",
                f"DROP DATABASE IF EXISTS {db}; CREATE DATABASE {db}"
                " CHARACTER SET utf8 COLLATE utf8_unicode_ci;",
            ],
        )
        s.run("Database loaded", ["sudo", "mariadb", db], stdin="db.sql")
    else:
        psql = [
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            db,
        ]
        s.run(
            "Database recreated",
            psql
            + [
                "-c",
                f"DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION {user};",
            ],
        )
        # Chargé sous le rôle de l'instance : les objets lui appartiennent.
        s.run(
            "Database loaded",
            psql + ["-c", f"SET ROLE {user}", "-f", "-"],
            stdin="db.sql",
        )
    for label, directory, owner, member in (
        (
            "Documents replaced",
            e["data_root"],
            f"{user}:{user}",
            "documents.tar",
        ),
        (
            "Modules replaced",
            os.path.join(htdocs, "custom"),
            "root:root",
            "custom.tar",
        ),
    ):
        s.run(label, ["sudo", "find", directory, "-mindepth", "1", "-delete"])
        s.run(
            label,
            ["sudo", "tar", "-x", "-C", directory, "-f", "-"],
            stdin=member,
        )
        s.run(label, ["sudo", "chown", "-R", owner, directory])
    key = s.backup_key()
    conf = os.path.join(htdocs, "conf", "conf.php")
    text = _sudo_read(s.system, conf)
    if key and unique_id(text) != key:
        new = install_files.set_conf_values(text, {"instance_unique_id": key})
        tmp = os.path.join(s.work, "conf.new")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new)
        s.run(
            "Instance key restored",
            [
                "sudo",
                "install",
                "-m",
                "440",
                "-o",
                "root",
                "-g",
                user,
                "/dev/stdin",
                conf,
            ],
            stdin="conf.new",
        )
        s.run(
            "Instance key restored",
            [
                "sudo",
                "install",
                "-m",
                "400",
                "/dev/stdin",
                f"/etc/erplibre-dolibarr/{s.name}/conf.php.bak",
            ],
            stdin="conf.new",
        )
    env_file = f"/etc/erplibre-dolibarr/{s.name}/cron.env"
    cron_key = ""
    for line in _sudo_read(s.system, env_file).splitlines():
        if line.startswith("CRON_KEY="):
            cron_key = line.split("=", 1)[1].strip()
    key_file = os.path.join(s.work, "cron.key")
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(cron_key + "\n")
    s.run(
        "Scheduled jobs key applied",
        [
            "sudo",
            "-u",
            user,
            "php",
            "-r",
            _CRON_KEY_PHP
            % (os.path.join(htdocs, "master.inc.php"), "fgets(STDIN)"),
        ],
        stdin="cron.key",
    )
    s.run("Scheduled jobs started", ["sudo", "systemctl", "start", timer])


def _container(s):
    from script.todo import container_runtime

    e = s.entry
    fiche = s.system.engine(e["engine"])
    engine = {
        "moteur": fiche["moteur"],
        "rootless": bool(fiche["sans_sudo"] and fiche.get("rootless")),
    }
    db, web, cron = e["containers"]
    dbn = f"dolibarr_{s.name}"

    def cmd(args):
        return container_runtime.commande(fiche, args)

    s.run("Scheduled jobs stopped", cmd(["stop", cron]))
    s.run(
        "Database recreated",
        cmd(
            [
                "exec",
                db,
                "sh",
                "-c",
                f'{_ROOTPW} exec mariadb -uroot -e "DROP DATABASE IF EXISTS {dbn};'
                f" CREATE DATABASE {dbn} CHARACTER SET utf8mb4"
                ' COLLATE utf8mb4_unicode_ci;"',
            ]
        ),
    )
    s.run(
        "Database loaded",
        cmd(
            [
                "exec",
                "-i",
                db,
                "sh",
                "-c",
                f"{_ROOTPW} exec mariadb -uroot {dbn}",
            ]
        ),
        stdin="db.sql",
    )
    s.run(
        "Documents replaced",
        cmd(
            [
                "exec",
                "-i",
                web,
                "sh",
                "-c",
                "find /var/www/documents -mindepth 1 -delete"
                " && tar -x -C /var/www/documents",
            ]
        ),
        stdin="documents.tar",
    )
    if e.get("custom_dir"):
        s.local(
            "Modules replaced",
            _replace_dir,
            e["custom_dir"],
            os.path.join(s.work, "custom.tar"),
        )
    else:
        s.run(
            "Modules replaced",
            cmd(
                [
                    "exec",
                    "-i",
                    web,
                    "sh",
                    "-c",
                    "find /var/www/html/custom -mindepth 1 -delete"
                    " && tar -x -C /var/www/html/custom",
                ]
            ),
            stdin="custom.tar",
        )
    state = e["state_dir"]
    secrets = os.path.join(state, "secrets")
    key = s.backup_key()
    if key:

        def write_key():
            path = os.path.join(secrets, "instance_id")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(key + "\n")

        s.local("Instance key restored", write_key)
    # L'image réécrit conf.php depuis ses variables à chaque création : site
    # et tâches recréés prennent la clé ; install.lock évite la réinstallation.
    s.run("Containers recreated", cmd(["rm", "-f", web, cron]))
    pin = {"docker_image": e["image"]}
    ids = (os.getuid(), os.getgid())
    mode = e.get("mode", "dev")
    s.run(
        "Containers recreated",
        cmd(
            container_plan.run_web(
                s.name,
                pin,
                secrets,
                os.path.join(state, "init.d"),
                mode,
                engine,
                e["port"],
                e["url"],
                e.get("admin_login", "admin"),
                e.get("custom_dir"),
                ids,
            )
        ),
    )
    for attempt in range(WAIT_TRIES):
        if attempt:
            time.sleep(WAIT_PAUSE)
        if served_version(s.system.http_get(e["url"] + "/", "127.0.0.1")):
            break
    else:
        raise RestoreError(t("The site does not serve the login page."))
    s.run(
        "Scheduled jobs key applied",
        cmd(
            [
                "exec",
                web,
                "php",
                "-r",
                _CRON_KEY_PHP
                % (
                    "/var/www/html/master.inc.php",
                    'file_get_contents("/run/secrets/cron_key")',
                ),
            ]
        ),
    )
    s.run(
        "Containers recreated",
        cmd(
            container_plan.run_cron(
                s.name,
                pin,
                secrets,
                mode,
                engine,
                e.get("admin_login", "admin"),
                e.get("custom_dir"),
                ids,
            )
        ),
    )


def restore(name, entry, archive, confirm, system, root, stamp):
    """Restaure `archive` sur `name` ; 0, 1 (échec) ou 2 (non confirmé)."""
    if confirm != name:
        print(
            t("Restoring overwrites %s: retype its name with --confirm.")
            % name
        )
        return 2
    dest = os.path.join(root, backup.BACKUPS, name)
    backup._private_dir(dest)
    work = tempfile.mkdtemp(prefix=".restore-", dir=dest)
    safety = None
    try:
        manifest = read_archive(archive, work)
        if _version(manifest.get("version")) > _version(entry.get("version")):
            raise RestoreError(
                t("The backup comes from %s, newer than the instance (%s).")
                % (manifest.get("version"), entry.get("version"))
            )
        safety = backup.create(
            name, entry, system, dest, f"pre-restore-{stamp}"
        )
        if not safety:
            raise RestoreError(
                t("The safety backup failed: nothing was restored.")
            )
        print(t("Safety backup: %s") % safety)
        steps = Steps(name, entry, work, system)
        if entry.get("runtime") == "container":
            _container(steps)
        elif entry.get("mode") == "prod":
            _native_prod(steps)
        else:
            _native_dev(steps)
        for label in dict.fromkeys(steps.done):
            print(f"  ✓ {t(label)}")
        print(t("Restored from %s.") % os.path.basename(archive))
        return 0
    except RestoreError as e:
        print(t("Restore stopped: %s") % e)
        if safety:
            print(t("The state before the restore is in %s.") % safety)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
