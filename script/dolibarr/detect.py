#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Trouver les installations Dolibarr d'une machine, locale ou par SSH.

    ./script/dolibarr/detect.py --local
    ./script/dolibarr/detect.py --ssh hote-a --ssh hote-b [--depth 7]

La sonde (detect_probe.sh, POSIX sh) part sur stdin : un aller-retour par
hôte, rien à installer de l'autre côté, aucun privilège demandé. Elle rend
les installations (chemin, version, base, adresse) et les conteneurs
Dolibarr, jamais un mot de passe. Chaque hôte finit dans un état qui dit
quoi faire : ok, auth (clé refusée), hostkey (clé d'hôte inconnue ou
changée), net (injoignable) ou error (la sonde n'a pas répondu).

Le rapport de chaque hôte est écrit dans private/dolibarr/inventory/
<hôte>.json (0600) : il nomme des machines et des bases, il ne quitte pas
private/.
"""

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

ROOT = new_path
PROBE = os.path.join(os.path.dirname(__file__), "detect_probe.sh")
INVENTORY = os.path.join("private", "dolibarr", "inventory")
DEFAULT_DEPTH = 7

_INSTALL_FIELDS = (
    "path",
    "version",
    "conf",
    "db_type",
    "db_host",
    "db_name",
    "url",
    "data_root",
)
_CONTAINER_FIELDS = ("engine", "name", "image", "state")

# Ce que ssh écrit quand il n'atteint pas la sonde, par cause.
_SSH_FAILURES = (
    ("hostkey", ("Host key verification failed",)),
    ("auth", ("Permission denied (",)),
    (
        "net",
        (
            "Could not resolve hostname",
            "Connection timed out",
            "Connection refused",
            "No route to host",
            "Network is unreachable",
            "timeout",
        ),
    ),
)

# Un nom d'hôte ou d'alias, tel qu'il devient un nom de fichier.
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


def parse_probe(text):
    """{status, installs, containers} de la sortie de la sonde, ou None.

    Ce qui précède l'en-tête (bannière de l'hôte) est ignoré.
    """
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("DOLIBARR\t"):
            break
    else:
        return None
    report = {"status": line.split("\t", 1)[1].strip()}
    report["installs"], report["containers"] = [], []
    for line in lines[i + 1 :]:
        kind, _tab, rest = line.partition("\t")
        if kind == "INSTALL":
            fields = _INSTALL_FIELDS
            target = report["installs"]
        elif kind == "CONTAINER":
            fields = _CONTAINER_FIELDS
            target = report["containers"]
        else:
            continue
        values = rest.split("\t")
        values += [""] * (len(fields) - len(values))
        target.append(dict(zip(fields, values)))
    return report


def classify(code, output):
    """ok, auth, hostkey, net ou error : pourquoi un hôte a (ou n'a pas)
    répondu."""
    if parse_probe(output) is not None:
        return "ok"
    for kind, marks in _SSH_FAILURES:
        if any(mark in (output or "") for mark in marks):
            return kind
    return "error"


def remote_argv(host, roots, depth=DEFAULT_DEPTH):
    """ssh qui lance la sonde reçue sur stdin, sans terminal ni question."""
    from script.proxmox import proxmox_deploy

    remote = " ".join(
        ["sh", "-s", "--", str(depth)] + [shlex.quote(r) for r in roots]
    )
    return proxmox_deploy.ssh_argv(host, remote)


def run_probe(argv, timeout=300):
    """(code, sortie) de la sonde envoyée sur stdin à `argv`."""
    from script.proxmox import proxmox_deploy

    with open(PROBE, encoding="utf-8") as f:
        script = f.read()
    try:
        r = subprocess.run(
            argv, input=script, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 255, "timeout"
    except OSError as e:
        return 255, str(e)
    return r.returncode, proxmox_deploy.strip_ssh_noise(
        (r.stdout or "") + (r.stderr or "")
    )


def save(root, host, state, report, now=None):
    """Écrit le rapport de `host` en 0600 sous private/ ; rend son chemin."""
    directory = os.path.join(root, INVENTORY)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, _SAFE.sub("_", host) + ".json")
    data = {
        "host": host,
        "state": state,
        "date": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
        "report": report,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4, sort_keys=True) + "\n")
    return path


_STATE_LABELS = {
    "ok": "reached",
    "auth": "key refused: check the SSH key of this host",
    "hostkey": "unknown or changed host key: connect once by hand",
    "net": "unreachable",
    "error": "the probe did not answer",
}

_STATUS_LABELS = {
    "yes": "Dolibarr found",
    "no": "no Dolibarr found",
    "denied": "no Dolibarr found, some directories are unreadable",
}


def show(host, state, report):
    print(f"== {host}: {t(_STATE_LABELS[state])}")
    if report is None:
        return
    print(f"   {t(_STATUS_LABELS.get(report['status'], report['status']))}")
    for i in report["installs"]:
        db = "/".join(
            x for x in (i["db_type"], i["db_host"], i["db_name"]) if x
        )
        print(f"   {i['path']}  {i['version'] or '?'}  {db or i['conf']}")
        if i["url"]:
            print(f"      {i['url']}")
    for c in report["containers"]:
        print(f"   [{c['engine']}] {c['name']}  {c['image']}  {c['state']}")


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--ssh", action="append", default=[], metavar="HOST")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--root", action="append", default=[], metavar="DIR")
    return parser


def main(argv=None, root=None, probe=None):
    args = build_parser().parse_args(argv)
    if not args.local and not args.ssh:
        print(t("Name a host with --ssh, or use --local."))
        return 2
    root = root or ROOT
    probe = probe or run_probe
    targets = []
    if args.local:
        targets.append(
            ("local", ["sh", "-s", "--", str(args.depth), *args.root])
        )
    for host in args.ssh:
        targets.append(
            (host, remote_argv({"target": host}, args.root, args.depth))
        )
    worst = 0
    for name, argv in targets:
        code, output = probe(argv)
        state = classify(code, output)
        report = parse_probe(output)
        show(name, state, report)
        path = save(root, name, state, report)
        print(f"   {t('Report:')} {os.path.relpath(path, root)}")
        if state != "ok":
            worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
