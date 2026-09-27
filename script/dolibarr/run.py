#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lancer, arrêter, surveiller une instance Dolibarr de développement.

    ./script/dolibarr/run.py start  --instance erp
    ./script/dolibarr/run.py stop   --instance erp
    ./script/dolibarr/run.py status [--instance erp]
    ./script/dolibarr/run.py logs   --instance erp [--lines 40]

Une instance de développement fait tourner PHP-FPM et nginx sous le compte
de l'utilisateur, avec les configurations que install_native.py a écrites
dans son dossier run/ ; leurs pid y sont aussi. L'état se lit en trois
valeurs : lancée, arrêtée, ou à moitié lancée quand un seul des deux démons
vit. Une instance de production relève de systemd, pas de ce script.
"""

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import lib_dolibarr, packages  # noqa: E402

ROOT = new_path

_TITLE = re.compile(r"<title>[^<]*@\s*([0-9][0-9.]*)\s*</title>")


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


def fpm_binary(family, php_version, exists=os.path.exists):
    """Chemin du binaire PHP-FPM de la famille, ou None s'il manque."""
    try:
        path = packages.fpm_layout(family, php_version)["binary"]
    except ValueError:
        return None
    return path if exists(path) else None


def nginx_binary(exists=os.path.exists):
    """nginx de /usr/sbin (Debian, Fedora, openSUSE) ou /usr/bin (Arch)."""
    for path in ("/usr/sbin/nginx", "/usr/bin/nginx"):
        if exists(path):
            return path
    return None


def served_version(html):
    """La version que la page de connexion annonce (« Login @ 24.0.1 »)."""
    m = _TITLE.search(html or "")
    return m.group(1) if m else None


class System:
    """Processus, ports et HTTP réels ; les tests en passent un factice."""

    def spawn(self, argv, log):
        with open(log, "ab") as out:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return proc.pid

    def call(self, argv):
        r = subprocess.run(argv, capture_output=True, text=True)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def kill(self, pid, sig):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass

    def port_free(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def http_get(self, url):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read(65536).decode("utf-8", "replace")
        except OSError:
            return ""


# Un fichier pid présent mais illisible : ni vivant ni mort, inconnu.
UNREADABLE = -1


def read_pid(path):
    """Le pid du fichier, None s'il n'existe pas, UNREADABLE s'il ne se lit
    pas : une absence dit « arrêté », un fichier abîmé ne dit rien."""
    try:
        with open(path, encoding="utf-8", errors="strict") as f:
            text = f.read().strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return UNREADABLE
    return int(text) if text.isdigit() else UNREADABLE


class Instance:
    """Chemins d'une instance de développement, tirés du registre."""

    def __init__(self, name, entry):
        self.name = name
        self.entry = entry
        self.run = os.path.join(entry["state_dir"], "run")
        self.fpm_conf = os.path.join(self.run, "php-fpm.conf")
        self.nginx_conf = os.path.join(self.run, "nginx.conf")
        self.fpm_pid = os.path.join(self.run, "php-fpm.pid")
        self.nginx_pid = os.path.join(self.run, "nginx.pid")
        self.port = int(entry["port"])
        self.url = entry["url"]

    def nginx_argv(self, nginx, *extra):
        return [nginx, "-p", self.run, "-c", self.nginx_conf, *extra]


def daemons(inst, system):
    """(PHP-FPM, nginx) : pid vivant, None, ou UNREADABLE."""
    out = []
    for path in (inst.fpm_pid, inst.nginx_pid):
        pid = read_pid(path)
        if pid == UNREADABLE:
            out.append(UNREADABLE)
        else:
            out.append(pid if pid and system.alive(pid) else None)
    return tuple(out)


# État interne -> libellé affiché (clé i18n). Des libellés propres aux
# instances : « running » et « stopped » existent déjà, accordés aux VM.
STATE_LABELS = {
    "running": "serving",
    "stopped": "not running",
    "half running": "half running: one daemon is down",
    "unknown": "unknown: a pid file is unreadable",
}


def state(inst, system):
    fpm, nginx = daemons(inst, system)
    if UNREADABLE in (fpm, nginx):
        return "unknown"
    if fpm and nginx:
        return "running"
    if fpm or nginx:
        return "half running"
    return "stopped"


def cmd_start(inst, system, fpm, nginx):
    if state(inst, system) == "unknown":
        print(t(STATE_LABELS["unknown"]))
        print(t("Check %s before starting.") % inst.run)
        return 1
    if state(inst, system) == "running":
        print(t("Already running: %s") % inst.url)
        return 0
    if state(inst, system) == "half running":
        cmd_stop(inst, system, nginx)
    if not system.port_free(inst.port):
        print(t("Port %s is already taken.") % inst.port)
        return 1
    system.spawn(
        [fpm, "-y", inst.fpm_conf], os.path.join(inst.run, "php-fpm.out")
    )
    # nginx se détache seul ; son code dit si la configuration tient.
    code, out = system.call(inst.nginx_argv(nginx))
    if code:
        print(t("nginx does not start:"))
        print(out.strip())
        return 1
    for _ in range(20):
        if state(inst, system) == "running":
            break
        time.sleep(0.25)
    version = served_version(system.http_get(inst.url + "/"))
    print(t("Dolibarr %s serves %s") % (version or "?", inst.url))
    return 0


def cmd_stop(inst, system, nginx):
    fpm_pid, nginx_pid = daemons(inst, system)
    fpm_pid = None if fpm_pid == UNREADABLE else fpm_pid
    nginx_pid = None if nginx_pid == UNREADABLE else nginx_pid
    if nginx_pid:
        system.call(inst.nginx_argv(nginx, "-s", "quit"))
    if fpm_pid:
        system.kill(fpm_pid, signal.SIGQUIT)
    if fpm_pid or nginx_pid:
        print(t("Stopped: %s") % inst.name)
    return 0


def cmd_status(instances, system):
    for inst in instances:
        st = state(inst, system)
        line = f"{inst.name}: {t(STATE_LABELS[st])}"
        if st == "running":
            version = served_version(system.http_get(inst.url + "/"))
            line += f" — {inst.url}, Dolibarr {version or '?'}"
        print(line)
    return 0


def tail_file(path, lines):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return None


def cmd_logs(inst, lines):
    paths = (
        os.path.join(inst.run, "nginx-error.log"),
        os.path.join(inst.run, "php-fpm.log"),
        os.path.join(inst.run, "php-fpm.out"),
        os.path.join(inst.entry["data_root"], "dolibarr.log"),
    )
    for path in paths:
        content = tail_file(path, lines)
        if content is None:
            continue
        print(f"==> {path} <==")
        for line in content:
            print(line)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "stop", "logs"):
        p = sub.add_parser(action)
        p.add_argument("--instance", required=True)
        if action == "logs":
            p.add_argument("--lines", type=int, default=40)
    p = sub.add_parser("status")
    p.add_argument("--instance")
    return parser


def _dev_instances(root):
    known = lib_dolibarr.load_registry(root)
    return {
        name: e
        for name, e in known.items()
        if e.get("mode") == "dev" and e.get("runtime") == "native"
    }


def _local_binaries():
    from script.todo import todo_install

    code = subprocess.run(
        ["php", "-r", 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;'],
        capture_output=True,
        text=True,
    )
    version = code.stdout.strip() if code.returncode == 0 else ""
    family = todo_install.family()
    return fpm_binary(family, version) if family else None, nginx_binary()


def main(argv=None, root=None, system=None, binaries=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or System()
    try:
        dev = _dev_instances(root)
    except lib_dolibarr.RegistryError as e:
        print(t("Dolibarr registry unreadable: %s") % e)
        return 2
    if args.action == "status" and not args.instance:
        if not dev:
            print(t("No development Dolibarr instance."))
        return cmd_status(
            [Instance(n, e) for n, e in sorted(dev.items())], system
        )
    if args.instance not in dev:
        print(t("No development instance named %s.") % args.instance)
        return 2
    inst = Instance(args.instance, dev[args.instance])
    if args.action == "status":
        return cmd_status([inst], system)
    if args.action == "logs":
        return cmd_logs(inst, args.lines)
    fpm, nginx = binaries or _local_binaries()
    if not nginx or (args.action == "start" and not fpm):
        print(t("PHP-FPM or nginx is missing: install the instance again."))
        return 1
    if args.action == "start":
        return cmd_start(inst, system, fpm, nginx)
    return cmd_stop(inst, system, nginx)


if __name__ == "__main__":
    sys.exit(main())
