#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bilan de santé des instances Dolibarr inscrites au registre.

    ./script/dolibarr/doctor.py --instance erp
    ./script/dolibarr/doctor.py --all

Chaque vérification rend ok, warn ou fail, avec ce qui la fonde ; un seul
fail et le code de sortie vaut 1. Rien n'est modifié, rien ne demande sudo.

Natif : version servie, code (en dév, le checkout contre l'épinglage ; en
production, chaque fichier contre l'archive du commit épinglé, voir
integrity), conf.php (mode et propriétaire), install.lock, PHP dans
l'intervalle épinglé. En production s'y ajoutent /install/ refusé par le
site et la minuterie des tâches, active et sans échec au dernier passage.
Conteneurs : version servie et les trois conteneurs en marche.
"""

import argparse
import collections
import grp
import os
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import integrity, lib_dolibarr  # noqa: E402
from script.dolibarr.run import served_version  # noqa: E402

ROOT = new_path

Result = collections.namedtuple("Result", "key level detail")

LABELS = {
    "served": "Served version",
    "code": "Code",
    "conf": "conf.php",
    "lock": "Install lock",
    "install": "Install page",
    "cron": "Scheduled jobs",
    "php": "PHP",
    "containers": "Instance containers",
}
MARKS = {"ok": "✓", "warn": "!", "fail": "✗"}
PHP_VERSION = ["php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;']
# Au-delà, la liste d'écarts se résume : elle se lit, elle ne s'épluche pas.
SHOWN = 5


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


class System:
    """Commandes, HTTP et moteur réels ; les tests en passent un factice."""

    def run(self, argv):
        try:
            r = subprocess.run(
                argv, capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError) as e:
            return 127, str(e)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def http_get(self, url, host):
        from script.dolibarr import native_prod

        return native_prod.http_get(url, host)

    def engine(self, moteur):
        from script.todo import container_runtime

        return container_runtime.etat(moteur)


def _local_base(entry):
    """(url, Host) où joindre le site depuis cette machine."""
    if entry.get("mode") == "prod" and entry.get("domain"):
        scheme = "http" if entry.get("tls") == "none" else "https"
        return f"{scheme}://127.0.0.1", entry["domain"]
    return entry["url"], "127.0.0.1"


def _listed(paths):
    shown = ", ".join(paths[:SHOWN])
    more = len(paths) - SHOWN
    return shown + (f" (+{more})" if more > 0 else "")


def check_served(entry, system):
    base, host = _local_base(entry)
    version = served_version(system.http_get(base + "/", host))
    if not version:
        return Result(
            "served", "fail", t("no login page at %s") % entry["url"]
        )
    if version != entry.get("version"):
        return Result(
            "served",
            "warn",
            t("%s served, %s expected") % (version, entry.get("version")),
        )
    return Result("served", "ok", f"Dolibarr {version} — {entry['url']}")


def check_dev_code(entry, system):
    git = ["git", "-C", entry["code_root"]]
    _code, head = system.run(git + ["rev-parse", "HEAD"])
    head = head.strip()
    if head != entry.get("commit"):
        return Result(
            "code",
            "warn",
            t("checkout at %s, pinned at %s")
            % (head[:7] or "?", entry.get("commit", "?")[:7]),
        )
    _code, status = system.run(
        git + ["status", "--porcelain", "--untracked-files=no"]
    )
    changed = [line for line in status.splitlines() if line.strip()]
    if changed:
        return Result(
            "code", "warn", t("%d core files modified") % len(changed)
        )
    return Result("code", "ok", t("the pinned commit, unmodified"))


def check_prod_code(entry, pin, root):
    checkout = os.path.join(root, pin["path"])
    try:
        blobs = integrity.archive_blobs(checkout, entry["commit"])
    except integrity.IntegrityError as e:
        return Result(
            "code", "warn", t("cannot read the pinned archive: %s") % e
        )
    diff = integrity.compare_tree(entry["code_root"], blobs)
    for kind, label in (
        ("added", "added"),
        ("modified", "modified"),
        ("missing", "missing"),
    ):
        if diff[kind]:
            return Result("code", "fail", f"{t(label)}: {_listed(diff[kind])}")
    if diff["unreadable"]:
        return Result(
            "code", "warn", f"{t('unreadable')}: {_listed(diff['unreadable'])}"
        )
    detail = t("identical to the pinned archive")
    if diff["custom"]:
        detail += f" — custom/: {', '.join(diff['custom'])}"
    return Result("code", "ok", detail)


def owner_is_expected(st, entry):
    """Production : root, groupe du compte de l'instance ; dév : le compte
    courant."""
    if entry.get("mode") == "prod":
        try:
            group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            return False
        return st.st_uid == 0 and group == entry.get("user")
    return st.st_uid == os.getuid()


def check_conf(entry):
    path = os.path.join(entry["code_root"], "htdocs", "conf", "conf.php")
    try:
        st = os.stat(path)
    except OSError:
        return Result("conf", "fail", t("absent: %s") % path)
    mode = st.st_mode & 0o777
    if mode & 0o007:
        return Result(
            "conf", "fail", t("readable by every account (%o)") % mode
        )
    prod = entry.get("mode") == "prod"
    wanted = 0o440 if prod else 0o600
    if mode != wanted or not owner_is_expected(st, entry):
        return Result(
            "conf",
            "fail" if prod else "warn",
            t("mode %o, %o expected") % (mode, wanted),
        )
    return Result("conf", "ok", f"{mode:o}")


def check_lock(entry):
    path = os.path.join(entry["code_root"], "htdocs", "install.lock")
    if os.path.exists(path):
        return Result("lock", "ok", "htdocs/install.lock")
    level = "fail" if entry.get("mode") == "prod" else "warn"
    return Result("lock", level, t("absent: the installer can run again"))


def check_install_page(entry, system):
    base, host = _local_base(entry)
    page = system.http_get(base + "/install/", host)
    if "403" in page:
        return Result("install", "ok", t("refused (403)"))
    if page.startswith("ERROR"):
        return Result("install", "warn", page[:80])
    return Result("install", "fail", t("the install pages are served"))


def check_cron(entry, system):
    timer = entry.get("cron_timer", "")
    service = timer.removesuffix(".timer") + ".service"
    # is-active ne rend 0 que pour une unité active.
    code, _out = system.run(["systemctl", "is-active", timer])
    if code:
        return Result("cron", "fail", t("timer %s inactive") % timer)
    _code, result = system.run(
        ["systemctl", "show", service, "-p", "Result", "--value"]
    )
    if result.strip() != "success":
        return Result(
            "cron", "fail", t("last run: %s") % (result.strip() or "?")
        )
    return Result("cron", "ok", timer)


def _version_tuple(text):
    return tuple(int(x) for x in text.split(".")[:2])


def check_php(pin, system):
    code, out = system.run(PHP_VERSION)
    version = out.strip()
    if code or not version:
        return Result("php", "warn", t("php does not answer."))
    low, high = pin["php_min"], pin["php_max"]
    if not (
        _version_tuple(low) <= _version_tuple(version) <= _version_tuple(high)
    ):
        return Result(
            "php",
            "fail",
            t("PHP %s is outside what Dolibarr supports (%s to %s).")
            % (version, low, high),
        )
    return Result("php", "ok", version)


def check_containers(entry, system):
    from script.todo import container_runtime

    fiche = system.engine(entry["engine"])
    stopped = []
    for name in entry["containers"]:
        code, out = system.run(
            container_runtime.commande(
                fiche,
                [
                    "container",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    name,
                ],
            )
        )
        if code:
            return Result("containers", "fail", t("missing: %s") % name)
        if out.strip() != "true":
            stopped.append(name)
    if stopped:
        return Result(
            "containers", "warn", t("stopped: %s") % ", ".join(stopped)
        )
    return Result("containers", "ok", t("the three are running"))


def check_instance(name, entry, pin, system, root):
    """Les vérifications de l'instance `name`, dans l'ordre d'affichage."""
    if entry.get("runtime") == "container":
        return [check_served(entry, system), check_containers(entry, system)]
    prod = entry.get("mode") == "prod"
    results = [
        check_served(entry, system),
        check_prod_code(entry, pin, root)
        if prod
        else check_dev_code(entry, system),
        check_conf(entry),
        check_lock(entry),
    ]
    if prod:
        results += [
            check_install_page(entry, system),
            check_cron(entry, system),
        ]
    results.append(check_php(pin, system))
    return results


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--instance")
    which.add_argument("--all", action="store_true")
    return parser


def main(argv=None, root=None, system=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or System()
    try:
        known = lib_dolibarr.load_registry(root)
        pin = lib_dolibarr.read_pin(root)
    except (lib_dolibarr.RegistryError, lib_dolibarr.PinError) as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    if args.instance and args.instance not in known:
        print(t("No instance named %s.") % args.instance)
        return 2
    names = [args.instance] if args.instance else sorted(known)
    if not names:
        print(t("No Dolibarr instance."))
    failed = False
    for name in names:
        print(f"== {name}")
        for r in check_instance(name, known[name], pin, system, root):
            print(f"  {MARKS[r.level]} {t(LABELS[r.key])}: {r.detail}")
            failed = failed or r.level == "fail"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
