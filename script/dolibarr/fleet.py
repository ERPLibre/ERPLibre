#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le parc d'instances Dolibarr : les lister, en retirer une.

    ./script/dolibarr/fleet.py list
    ./script/dolibarr/fleet.py remove --instance erp --dry-run
    ./script/dolibarr/fleet.py remove --instance erp --confirm erp

Retirer défait ce que l'installation a posé, selon l'exécution :
- conteneurs : les trois conteneurs, les volumes, le réseau, l'état de
  l'instance ; custom/ d'un développement reste, c'est le code du
  développeur ;
- natif en développement : la base et son compte, l'état de l'instance,
  conf.php et install.lock du checkout, qui redevient libre ;
- natif en production : minuterie et unités, pool PHP-FPM, site nginx,
  base et compte, code, données, secrets, compte système. Un certificat
  certbot reste, avec la commande qui le supprime.

Rien ne part sans --confirm égal au nom ; --dry-run montre chaque étape.
Chaque commande est rejouable : un retrait interrompu se relance, et
l'entrée du registre ne part que lorsque tout a réussi. Proposer une
sauvegarde avant revient au menu, qui la lance avec backup.py.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import (  # noqa: E402
    container_plan,
    lib_dolibarr,
    packages,
)
from script.dolibarr.run import served_version  # noqa: E402

ROOT = new_path
PHP_VERSION = ["php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;']
# Ce que répond une commande sur un objet déjà parti : le retrait est fait.
_GONE = ("no such", "not found", "does not exist", "unknown")


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
                argv, capture_output=True, text=True, timeout=300
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


def stop_dev(name, root):
    """Arrête les démons d'une instance de développement native."""
    from script.dolibarr import run

    run.main(["stop", "--instance", name], root=root)


def host_facts(system):
    """Famille de paquets et version de PHP : où l'installation a posé le
    pool et le site."""
    from script.todo import todo_install

    _code, out = system.run(PHP_VERSION)
    return {"family": todo_install.family(), "php_version": out.strip()}


class Step:
    """Une commande, ou une action locale décrite pour l'essai à blanc."""

    def __init__(self, argv=None, describe=None, action=None):
        self.argv, self.describe, self.action = argv, describe, action

    def text(self):
        return " ".join(self.argv) if self.argv else self.describe


def _drop_database(entry, sudo_mariadb):
    db = entry["db_name"]
    if entry.get("db", "mariadb") == "mariadb":
        return [
            Step(
                sudo_mariadb
                + [
                    "-e",
                    f"DROP DATABASE IF EXISTS {db};"
                    f" DROP USER IF EXISTS '{db}'@'localhost';",
                ]
            )
        ]
    pg = ["sudo", "-u", "postgres"]
    return [
        Step(pg + ["dropdb", "--if-exists", db]),
        Step(pg + ["dropuser", "--if-exists", db]),
    ]


def _remove_tree(path):
    return Step(
        describe=f"rm -rf {path}",
        action=lambda: shutil.rmtree(path, ignore_errors=True),
    )


def _remove_file(path):
    def action():
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    return Step(describe=f"rm -f {path}", action=action)


def _state_but_custom(state, custom):
    """L'état de l'instance, sauf custom/ : le code du développeur."""

    def action():
        if not os.path.isdir(state):
            return
        for name in os.listdir(state):
            full = os.path.join(state, name)
            if custom and os.path.abspath(full) == os.path.abspath(custom):
                continue
            if os.path.isdir(full) and not os.path.islink(full):
                shutil.rmtree(full)
            else:
                os.remove(full)

    return Step(
        describe=f"rm -rf {state}/* ({t('custom/ kept')})", action=action
    )


def plan(name, entry, system, root):
    """Les étapes du retrait de `name`, dans l'ordre, et un avis final."""
    notice = None
    if entry.get("runtime") == "container":
        from script.todo import container_runtime

        fiche = system.engine(entry["engine"])

        def cmd(args):
            return container_runtime.commande(fiche, args)

        n = container_plan.names(name)
        volumes = [n["volumes"]["dbdata"], n["volumes"]["documents"]]
        if entry.get("mode") == "prod":
            volumes.append(n["volumes"]["custom"])
        steps = [
            Step(cmd(["rm", "-f", *reversed(entry["containers"])])),
            Step(cmd(["volume", "rm", "-f", *volumes])),
            Step(cmd(["network", "rm", n["network"]])),
            _state_but_custom(entry["state_dir"], entry.get("custom_dir")),
        ]
        if entry.get("custom_dir"):
            notice = t("Kept, your modules: %s") % entry["custom_dir"]
        return steps, notice
    if entry.get("mode") != "prod":
        htdocs = os.path.join(entry["code_root"], "htdocs")
        steps = [
            Step(
                describe=f"run.py stop --instance {name}",
                action=lambda: stop_dev(name, root),
            ),
            *_drop_database(entry, ["sudo", "mariadb"]),
            _remove_tree(entry["state_dir"]),
            _remove_file(os.path.join(htdocs, "conf", "conf.php")),
            _remove_file(os.path.join(htdocs, "install.lock")),
        ]
        return steps, None
    facts = host_facts(system)
    timer = entry["cron_timer"]
    service = timer.removesuffix(".timer") + ".service"
    layout = packages.fpm_layout(facts["family"], facts["php_version"])
    site, link = packages.nginx_site(facts["family"], name)
    steps = [
        Step(["sudo", "systemctl", "disable", "--now", timer]),
        Step(
            [
                "sudo",
                "rm",
                "-f",
                f"/etc/systemd/system/{service}",
                f"/etc/systemd/system/{timer}",
            ]
        ),
        Step(["sudo", "systemctl", "daemon-reload"]),
        Step(
            [
                "sudo",
                "rm",
                "-f",
                f"{layout['pool_dir']}/erplibre-dolibarr-{name}.conf",
            ]
        ),
        Step(["sudo", "systemctl", "reload-or-restart", layout["unit"]]),
        Step(["sudo", "rm", "-f", site, *([link] if link else [])]),
        Step(["sudo", "systemctl", "reload", "nginx"]),
        *_drop_database(entry, ["sudo", "mariadb"]),
        Step(["sudo", "rm", "-rf", entry["code_root"]]),
        Step(["sudo", "rm", "-rf", entry["state_dir"]]),
        Step(["sudo", "rm", "-rf", f"/etc/erplibre-dolibarr/{name}"]),
        Step(["sudo", "userdel", entry["user"]]),
        _remove_tree(
            os.path.join(
                os.path.expanduser("~"), ".erplibre", "dolibarr_tls", name
            )
        ),
    ]
    if entry.get("tls") == "certbot":
        domain = entry.get("domain", "")
        notice = (
            t("The certbot certificate of %s is kept; to remove it:") % domain
            + f" sudo certbot delete --cert-name {domain}"
        )
    return steps, notice


def remove(name, entry, confirm, dry_run, system, root):
    if not dry_run and confirm != name:
        print(t("Removing deletes %s: retype its name with --confirm.") % name)
        return 2
    steps, notice = plan(name, entry, system, root)
    failed = []
    for step in steps:
        if dry_run:
            print(f"  [dry-run] {step.text()}")
            continue
        if step.action:
            try:
                step.action()
            except OSError as e:
                failed.append(f"{step.text()} — {e}")
            continue
        code, out = system.run(step.argv)
        if code and not any(g in out.lower() for g in _GONE):
            failed.append(f"{step.text()} — {out.strip()[-300:]}")
    if notice:
        print(notice)
    if dry_run:
        return 0
    if failed:
        print(
            t("Not everything was removed; running the removal again resumes:")
        )
        for line in failed:
            print(f"  ✗ {line}")
        return 1
    registry = os.path.join(root, lib_dolibarr.REGISTRY)
    known = lib_dolibarr.load_registry(root)
    known.pop(name, None)
    with open(registry, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"instances": known}, indent=4, sort_keys=True) + "\n"
        )
    print(t("Instance %s removed.") % name)
    return 0


def _local_base(entry):
    if entry.get("mode") == "prod" and entry.get("domain"):
        scheme = "http" if entry.get("tls") == "none" else "https"
        return f"{scheme}://127.0.0.1", entry["domain"]
    return entry.get("url", ""), "127.0.0.1"


def show(known, system):
    for name in sorted(known):
        entry = known[name]
        base, host = _local_base(entry)
        version = served_version(system.http_get(base + "/", host))
        print(
            f"{name:24} {entry.get('mode', '?'):5} {entry.get('runtime', '?'):10}"
            f" {version or '-':8} {entry.get('url', '')}"
        )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    p = sub.add_parser("remove")
    p.add_argument("--instance", required=True)
    p.add_argument("--confirm", default="")
    p.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None, root=None, system=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or System()
    try:
        known = lib_dolibarr.load_registry(root)
    except lib_dolibarr.RegistryError as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    if args.action == "list":
        return show(known, system)
    if args.instance not in known:
        print(t("No instance named %s.") % args.instance)
        return 2
    return remove(
        args.instance,
        known[args.instance],
        args.confirm,
        args.dry_run,
        system,
        root,
    )


if __name__ == "__main__":
    sys.exit(main())
