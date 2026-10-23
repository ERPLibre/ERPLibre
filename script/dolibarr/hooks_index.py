#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les hooks et déclencheurs de Dolibarr, à un commit ou entre deux.

    ./script/dolibarr/hooks_index.py list [--at 24.0.0] [--kind hook]
        [--filter REGEX]
    ./script/dolibarr/hooks_index.py diff --from 23.0.4 [--to 24.0.1]

Quatre genres, lus par git grep sans rien extraire :
- hook : le nom passé à executeHooks (la méthode qu'un module définit) ;
- context : les contextes littéraux d'initHooks (ceux qu'un module déclare
  dans module_parts['hooks']) ; un contexte calculé n'est pas vu ;
- trigger : les codes littéraux passés à call_trigger ;
- agenda : les codes de llx_c_action_trigger.sql, ceux que l'agenda
  propose.
Le gabarit du ModuleBuilder est exclu : ses contextes sont des jetons.

Une version se désigne par un tag, une branche ou un commit ; sans --at ni
--to, c'est le commit épinglé. Il se lit dans le checkout. Toute autre
version se récupère une fois, à profondeur 1, dans un dépôt d'index à
part (~/.erplibre/dolibarr_index.git) qui emprunte les objets du checkout :
le dépôt que gère Google Repo n'est jamais écrit. Un tag ou un commit
récupéré sert ensuite sans réseau ; une branche se relit à chaque fois.
"""

import argparse
import os
import re
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.dolibarr import backup, lib_dolibarr  # noqa: E402
from script.dolibarr.pin import UPSTREAM  # noqa: E402

ROOT = new_path
t = backup.t

KINDS = ("hook", "context", "trigger", "agenda")
AGENDA_SQL = "htdocs/install/mysql/data/llx_c_action_trigger.sql"
_PATHS = ["htdocs/*.php", ":!htdocs/modulebuilder/template"]
_HOOK = re.compile(r"executeHooks\(\s*['\"](\w+)['\"]")
_CONTEXTS = re.compile(r"initHooks\(\s*(?:array\(|\[)([^)\]]*)")
_QUOTED = re.compile(r"['\"](\w+)['\"]")
_TRIGGER = re.compile(r"call_trigger\(\s*['\"]([A-Z0-9_]+)['\"]")
_AGENDA = re.compile(r"values\s*\(\s*'([A-Z0-9_]+)'", re.I)
_SHA = re.compile(r"^[0-9a-f]{40}$")


class IndexError_(Exception):
    """Une version introuvable ou illisible : sortie 2."""


def parse_grep(lines):
    """{genre: {nom: [fichiers]}} des lignes « commit:fichier:ligne:texte »
    de git grep."""
    index = {"hook": {}, "context": {}, "trigger": {}}

    def add(kind, name, path):
        paths = index[kind].setdefault(name, [])
        if path not in paths:
            paths.append(path)

    for line in lines:
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        path, text = parts[1], parts[3]
        for name in _HOOK.findall(text):
            add("hook", name, path)
        for inside in _CONTEXTS.findall(text):
            for name in _QUOTED.findall(inside):
                add("context", name, path)
        for name in _TRIGGER.findall(text):
            add("trigger", name, path)
    for names in index.values():
        for paths in names.values():
            paths.sort()
    return index


def _lines(path):
    try:
        with open(path or "", encoding="utf-8") as f:
            return [x.strip() for x in f if x.strip()]
    except OSError:
        return []


def parse_agenda(sql):
    return set(_AGENDA.findall(sql))


def diff(before, after):
    """{genre: (ajoutés, retirés)}, noms triés."""
    return {
        kind: (
            sorted(set(after.get(kind, {})) - set(before.get(kind, {}))),
            sorted(set(before.get(kind, {})) - set(after.get(kind, {}))),
        )
        for kind in sorted(set(before) | set(after))
    }


class Repository:
    """Le dépôt d'index : nu, ses objets empruntés au checkout s'il est là,
    ce qui manque récupéré à profondeur 1 depuis `upstream`."""

    def __init__(self, system, path, checkout, upstream):
        self.system, self.path, self.upstream = system, path, upstream
        if not os.path.exists(os.path.join(path, "HEAD")):
            self._git_ok(["init", "-q", "--bare", path], here=False)
        if checkout and os.path.isdir(checkout):
            objects = self._git_path(checkout, "objects")
            if objects:
                info = os.path.join(path, "objects", "info")
                os.makedirs(info, exist_ok=True)
                with open(os.path.join(info, "alternates"), "w") as f:
                    f.write(objects + "\n")
                self._borrow_shallow(self._git_path(checkout, "shallow"))

    def _git_path(self, checkout, name):
        code, out = self.system.run(
            ["git", "-C", checkout, "rev-parse"]
            + ["--path-format=absolute", "--git-path", name]
        )
        return out.strip() if code == 0 else None

    def _borrow_shallow(self, source):
        """Les commits de bord du checkout, sans leurs parents : sans eux,
        git offre ces commits au serveur et descend vers un parent absent.
        Ceux d'un emprunt passé partent : le checkout a pu avancer."""
        borrowed = set(_lines(source))
        record = os.path.join(self.path, "erplibre-borrowed-shallow")
        own = set(_lines(os.path.join(self.path, "shallow")))
        own -= set(_lines(record))
        with open(os.path.join(self.path, "shallow"), "w") as f:
            f.writelines(f"{sha}\n" for sha in sorted(own | borrowed))
        with open(record, "w") as f:
            f.writelines(f"{sha}\n" for sha in sorted(borrowed))

    def git(self, args):
        return self.system.run(["git", "-C", self.path] + args)

    def _git_ok(self, args, here=True):
        code, out = self.git(args) if here else self.system.run(["git"] + args)
        if code:
            raise IndexError_(out.strip()[-300:])
        return out

    def _has(self, sha):
        return self.git(["cat-file", "-e", sha + "^{tree}"])[0] == 0

    def _fetch(self, refspec):
        return self.git(
            [
                "fetch",
                "-q",
                "--depth",
                "1",
                "--no-tags",
                self.upstream,
                refspec,
            ]
        )[0]

    def resolve(self, ref):
        """Le commit de `ref` (sha, tag, branche), récupéré s'il manque."""
        if _SHA.match(ref):
            if not self._has(ref) and (self._fetch(ref) or not self._has(ref)):
                raise IndexError_(t("Version %s not found upstream.") % ref)
            return ref
        code, out = self.git(
            ["rev-parse", "-q", "--verify", f"refs/tags/{ref}^{{commit}}"]
        )
        if code == 0:
            return out.strip()
        if self._fetch(f"refs/tags/{ref}:refs/tags/{ref}") == 0:
            return self._git_ok(
                ["rev-parse", f"refs/tags/{ref}^{{commit}}"]
            ).strip()
        if self._fetch(f"refs/heads/{ref}") == 0:
            return self._git_ok(["rev-parse", "FETCH_HEAD^{commit}"]).strip()
        raise IndexError_(t("Version %s not found upstream.") % ref)

    def index(self, sha):
        code, out = self.git(
            ["grep", "-I", "-n", "-E"]
            + [
                "-e",
                r"executeHooks\(",
                "-e",
                r"initHooks\(",
                "-e",
                r"call_trigger\(",
            ]
            + [sha, "--"]
            + _PATHS
        )
        if code not in (0, 1):
            raise IndexError_(out.strip()[-300:])
        index = parse_grep(out.splitlines())
        code, sql = self.git(["show", f"{sha}:{AGENDA_SQL}"])
        index["agenda"] = {
            c: [AGENDA_SQL] for c in parse_agenda(sql if code == 0 else "")
        }
        return index


def _show(index, kind, pattern):
    regex = re.compile(pattern) if pattern else None
    for k in KINDS:
        if kind and k != kind:
            continue
        for name in sorted(index.get(k, {})):
            if regex and not regex.search(name):
                continue
            where = index[k][name]
            count = f"  ({len(where)})" if k != "agenda" else ""
            print(f"{k:8} {name}{count}")


def _show_diff(changes, old, new):
    print(t("Dolibarr %s -> %s") % (old, new))
    for kind in KINDS:
        added, removed = changes.get(kind, ([], []))
        for name in added:
            print(f"  + {kind} {name}")
        for name in removed:
            print(f"  - {kind} {name}")
    for kind in KINDS:
        added, removed = changes.get(kind, ([], []))
        print(f"  {kind}: +{len(added)} -{len(removed)}")


def build_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("list")
    p.add_argument("--at")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--filter")
    p = sub.add_parser("diff")
    p.add_argument("--from", dest="old", required=True)
    p.add_argument("--to", dest="new")
    return parser


def main(argv=None, root=None, system=None, cache=None, upstream=None):
    args = build_parser().parse_args(argv)
    root = root or ROOT
    system = system or backup.System()
    cache = cache or os.path.join(
        os.path.expanduser("~"), ".erplibre", "dolibarr_index.git"
    )
    try:
        pin = lib_dolibarr.read_pin(root)
    except lib_dolibarr.PinError as e:
        print(t("Dolibarr pin unreadable: %s") % e)
        return 2
    try:
        repo = Repository(
            system,
            cache,
            os.path.join(root, pin["path"]),
            upstream or UPSTREAM,
        )
        if args.action == "list":
            index = repo.index(repo.resolve(args.at or pin["commit"]))
            _show(index, args.kind, args.filter)
            return 0
        old, new = args.old, args.new or pin["commit"]
        before = repo.index(repo.resolve(old))
        after = repo.index(repo.resolve(new))
    except IndexError_ as e:
        print(e)
        return 2
    _show_diff(diff(before, after), old, new[:12] if _SHA.match(new) else new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
