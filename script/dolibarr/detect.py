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
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.erp_common import detect as common_detect  # noqa: E402
from script.erp_common.detect import (  # noqa: E402,F401
    DEFAULT_DEPTH,
    remote_argv,
)

ROOT = new_path
PROBE = os.path.join(os.path.dirname(__file__), "detect_probe.sh")
INVENTORY = common_detect.inventory_dir("dolibarr")
# Première ligne de la sortie de detect_probe.sh : « DOLIBARR\t<statut> ».
HEADER = "DOLIBARR"

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

_STATE_LABELS = common_detect.STATE_LABELS


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


def parse_probe(text):
    """{status, installs, containers} de la sortie de detect_probe.sh, ou
    None ; voir erp_common.detect.parse_probe."""
    return common_detect.parse_probe(HEADER, _INSTALL_FIELDS, text)


def classify(code, output):
    """ok, auth, hostkey, net ou error ; voir erp_common.detect.classify."""
    return common_detect.classify(HEADER, code, output)


def run_probe(argv, timeout=300):
    """(code, sortie) de detect_probe.sh envoyée sur stdin à `argv`."""
    return common_detect.run_probe(PROBE, argv, timeout)


def save(root, host, state, report, now=None):
    """Écrit le rapport de `host` en 0600 sous private/dolibarr/inventory/ ;
    rend son chemin."""
    return common_detect.save("dolibarr", root, host, state, report, now)


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
