#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Quelle convention de commit vaut pour un dépôt du checkout ?

Trois réponses, une par classe de dépôt :

- ``odoo`` : le cœur d'Odoo (``odoo<version>/odoo``, fork d'OCA/OCB, lui-même
  miroir d'odoo/odoo) et les dépôts de l'organisation odoo. Convention de la
  skill ``odoo-git``.
- ``oca`` : un dépôt de l'OCA, ou un fork d'un dépôt de l'OCA. Convention
  ``odoo-git`` plus les écarts de l'OCA, décrits dans son ``ERPLIBRE.md``.
- ``erplibre`` : tout le reste, ERPLibre lui-même compris. Convention de
  ``/commit`` (``conf/template_claude_commands_commit.md``).

La classe se lit d'abord dans les manifestes Google Repo (``manifest/*.xml``) :
le projet dont le ``path`` est la racine git du dépôt donne son ``remote`` et,
pour un fork, son ``fork-upstream-remote``. Un remote nommé
``<Propriétaire>_origin_<Amont>`` désigne un fork de ``<Amont>``. Un dépôt
absent des manifestes se classe par l'URL de ses remotes git.

Usage : ``commit_convention.py [chemin] [--explain]``. Le chemin vaut le
répertoire courant par défaut ; ``--explain`` ajoute la raison du verdict.
"""

import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ODOO, OCA, ERPLIBRE = "odoo", "oca", "erplibre"

ORIGIN = re.compile(r"^[^_]+_origin_(?P<upstream>.+)$")

# Hôte GitHub en HTTPS comme en SSH : « github.com/OCA/x » ou « github.com:OCA/x ».
URL_OWNER_REPO = re.compile(
    r"github\.com[/:](?P<owner>[^/]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$"
)


def _upstream(remote: str) -> str:
    """Le remote amont d'un nom de remote : « X_origin_OCA » rend « OCA »."""
    match = ORIGIN.match(remote or "")
    return match.group("upstream") if match else (remote or "")


def manifest_projects(root: Path = ROOT) -> dict:
    """``{path: attributs du <project>}`` sur tous les manifestes de ``root``.

    Le ``remote`` absent d'un projet prend celui du ``<default>`` de son
    fichier. Un manifeste illisible est ignoré : il ne doit pas empêcher de
    classer les dépôts que les autres décrivent.
    """
    projects = {}
    for manifest in sorted((root / "manifest").glob("*.xml")):
        try:
            tree = ET.parse(manifest)
        except ET.ParseError:
            continue
        default = tree.find("default")
        default_remote = default.get("remote", "") if default is not None else ""
        for project in tree.iter("project"):
            path = project.get("path") or project.get("name", "")
            attrs = dict(project.attrib)
            attrs.setdefault("remote", default_remote)
            projects.setdefault(path.rstrip("/"), attrs)
    return projects


def classify_project(attrs: dict) -> tuple:
    """``(classe, raison)`` d'un projet de manifeste.

    Le cœur passe en premier : son fork a l'OCA pour amont (OCB), mais son code
    et sa convention sont ceux d'odoo/odoo.
    """
    name = attrs.get("name", "")
    remotes = {
        _upstream(attrs.get("remote", "")),
        attrs.get("fork-upstream-remote", ""),
    }
    if name == "odoo.git" or attrs.get("fork-upstream-name") == "OCB.git":
        return ODOO, "cœur d'Odoo (%s)" % (attrs.get("fork-upstream-name") or name)
    if "odoo" in remotes:
        return ODOO, "remote odoo"
    if "OCA" in remotes:
        return OCA, "remote %s, amont OCA" % attrs.get("remote", "")
    return ERPLIBRE, "remote %s, ni Odoo ni OCA" % attrs.get("remote", "")


def classify_urls(urls: list) -> tuple:
    """``(classe, raison)`` d'après les URL des remotes git d'un dépôt."""
    for url in urls:
        match = URL_OWNER_REPO.search(url)
        if not match:
            continue
        owner, repo = match.group("owner"), match.group("repo")
        if owner == "odoo" or (owner == "OCA" and repo == "OCB"):
            return ODOO, "remote git %s/%s" % (owner, repo)
        if owner == "OCA":
            return OCA, "remote git %s/%s" % (owner, repo)
    return ERPLIBRE, "aucun remote Odoo ni OCA"


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def classify(path: Path, root: Path = ROOT) -> tuple:
    """``(classe, raison)`` du dépôt git qui contient ``path``.

    Un chemin hors de tout dépôt git rend ``erplibre`` : aucun commit n'y est
    possible, la réponse n'engage à rien.
    """
    toplevel = _git(path, "rev-parse", "--show-toplevel")
    if not toplevel:
        return ERPLIBRE, "hors de tout dépôt git"
    top = Path(toplevel).resolve()
    if top == root.resolve():
        return ERPLIBRE, "dépôt ERPLibre"
    try:
        relative = top.relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = None
    if relative is not None:
        attrs = manifest_projects(root).get(relative)
        if attrs is not None:
            verdict, reason = classify_project(attrs)
            return verdict, "manifeste, %s : %s" % (relative, reason)
    urls = _git(top, "remote", "-v").split()
    return classify_urls(urls)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args(argv)
    verdict, reason = classify(Path(args.path))
    print("%s  # %s" % (verdict, reason) if args.explain else verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
