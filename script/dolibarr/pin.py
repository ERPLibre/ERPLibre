#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relever le commit épinglé de Dolibarr.

    ./script/dolibarr/pin.py show
    ./script/dolibarr/pin.py update [--branch 24.0] [--tag 24.0.2] [--apply]

show dit l'épinglage et la tête de sa branche en amont. update vise la tête
de la branche (ou le commit d'un tag), lit la version à ce commit, et
montre ce qui changerait ; --apply l'écrit. Le manifest (commit, branche)
et conf/supported_version_dolibarr.json (version, branche, images)
changent ensemble : read_pin refuse un couple qui ne s'accorde pas.

Trois images, épinglées par empreinte (dépôt:étiquette@sha256:…) lue au
Hub à chaque update : Dolibarr, MariaDB, et composer pour les outils
qualité. Une image reconstruite sous la même étiquette (correctifs de PHP,
de MariaDB) déplace l'épinglage. L'étiquette de l'image
Dolibarr ne suit la version que si le Hub la publie : l'image officielle
paraît souvent après la version. Un Hub injoignable garde les images.

Codes de sortie : 0 rien à faire ou écrit, 1 refus, 2 épinglage
illisible, 3 (PENDING) des changements montrés et non écrits.

Après --apply, synchroniser le checkout :
./script/manifest/update_manifest_local_dolibarr.sh
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import lib_dolibarr  # noqa: E402
from script.erp_common import pin as common_pin  # noqa: E402
from script.erp_common.pin import (  # noqa: E402,F401
    image_ref,
    refreshed_image,
    split_image,
    target,
)

ROOT = new_path
UPSTREAM = "https://github.com/Dolibarr/dolibarr.git"
RAW = "https://raw.githubusercontent.com/Dolibarr/dolibarr"

# Code de sortie d'un essai à blanc qui a trouvé quoi changer.
PENDING = 3

_MAJOR = re.compile(r"define\('DOL_MAJOR_VERSION',\s*'([0-9]+)'\)")
_MINOR = re.compile(r"define\('DOL_MINOR_VERSION',\s*'([0-9][0-9.]*)'\)")
_FULL = re.compile(r"define\('DOL_VERSION',\s*'([0-9][0-9.]*)'\)")


def t(key):
    """Traduction si l'outillage TODO est là ; la clé sinon."""
    try:
        from script.todo.todo_i18n import t as _t
    except Exception:
        return key
    return _t(key)


def parse_version(text):
    """Version déclarée par version.inc.php (23+) ou filefunc.inc.php."""
    text = text or ""
    major, minor = _MAJOR.search(text), _MINOR.search(text)
    if major and minor:
        return f"{major.group(1)}.{minor.group(1)}"
    full = _FULL.search(text)
    return full.group(1) if full else None


def rewrite_manifest(text, commit, branch):
    """`text` où le projet du groupe dolibarr prend `commit` et `branch`.

    common_pin.rewrite_manifest lié au groupe lib_dolibarr.REPO_GROUP.
    """
    return common_pin.rewrite_manifest(
        text, commit, branch, lib_dolibarr.REPO_GROUP
    )


class Network(common_pin.Network):
    """ls-remote et étiquettes du Hub (common_pin.Network) sur le dépôt
    Dolibarr, plus les fichiers bruts d'un commit chez GitHub."""

    def __init__(self):
        super().__init__(UPSTREAM)

    def raw(self, commit, path):
        """Texte de `path` au commit `commit`, ou None s'il ne se lit pas."""
        try:
            with urllib.request.urlopen(
                f"{RAW}/{commit}/{path}", timeout=30
            ) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError):
            return None


def version_at(net, commit):
    for path in ("htdocs/version.inc.php", "htdocs/filefunc.inc.php"):
        version = parse_version(net.raw(commit, path))
        if version:
            return version
    return None


def cmd_show(pin, net):
    head, _ref = target(net, pin["branch"], None)
    print(
        t("Pinned: Dolibarr %s, branch %s, commit %s")
        % (pin["version"], pin["branch"], pin["commit"][:7])
    )
    if head:
        print(t("Head of %s upstream: %s") % (pin["branch"], head[:7]))
    else:
        print(t("Head of %s upstream: unreachable") % pin["branch"])
    return 0


def cmd_update(root, pin, net, branch, tag, apply):
    commit, ref = target(net, branch, tag)
    if not commit:
        print(t("Nothing upstream at %s.") % ref)
        return 1
    same = commit == pin["commit"] and branch == pin["branch"]
    version = pin["version"] if same else version_at(net, commit)
    if not version:
        print(t("Cannot read the version at %s.") % commit[:7])
        return 1
    if not version.startswith(branch + "."):
        print(
            t("Version %s does not belong to branch %s.") % (version, branch)
        )
        return 1
    # L'image paraît souvent après la version : elle se rattrape même
    # quand le commit, lui, ne bouge plus.
    image = refreshed_image(net, pin["docker_image"], version)
    if split_image(image)[1] != version:
        image = refreshed_image(net, pin["docker_image"])
        print(
            t("No %s image on Docker Hub yet: keeping %s.") % (version, image)
        )
    mariadb = refreshed_image(net, pin["mariadb_image"])
    tools = refreshed_image(net, pin["tools_image"])
    images_same = (
        image == pin["docker_image"]
        and mariadb == pin["mariadb_image"]
        and tools == pin["tools_image"]
    )
    if same and images_same:
        print(t("Already pinned on %s.") % commit[:7])
        return 0
    print(
        t("Commit %s -> %s, version %s -> %s, branch %s -> %s")
        % (
            pin["commit"][:7],
            commit[:7],
            pin["version"],
            version,
            pin["branch"],
            branch,
        )
    )
    for old, new in (
        (pin["docker_image"], image),
        (pin["mariadb_image"], mariadb),
        (pin["tools_image"], tools),
    ):
        if new != old:
            print(t("Image %s -> %s") % (old, new))
    if not apply:
        print(t("Nothing written: add --apply."))
        return PENDING
    manifest_path = os.path.join(root, lib_dolibarr.PIN_MANIFEST)
    json_path = os.path.join(root, lib_dolibarr.PIN_JSON)
    with open(manifest_path, encoding="utf-8") as f:
        manifest = rewrite_manifest(f.read(), commit, branch)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    data.update(
        version=version,
        branch=branch,
        docker_image=image,
        mariadb_image=mariadb,
        tools_image=tools,
    )
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest)
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4) + "\n")
    print(t("Pin written. Sync the checkout with:"))
    print("  ./script/manifest/update_manifest_local_dolibarr.sh")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("show")
    p = sub.add_parser("update")
    p.add_argument("--branch")
    p.add_argument("--tag")
    p.add_argument("--apply", action="store_true")
    return parser


def main(argv=None, root=None, net=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    net = net or Network()
    try:
        pin = lib_dolibarr.read_pin(root)
    except lib_dolibarr.PinError as e:
        print(t("Dolibarr pin unreadable: %s") % e)
        return 2
    if args.action == "show":
        return cmd_show(pin, net)
    branch = args.branch or pin["branch"]
    return cmd_update(root, pin, net, branch, args.tag, args.apply)


if __name__ == "__main__":
    sys.exit(main())
