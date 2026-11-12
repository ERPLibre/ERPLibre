#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Passer à False tout « auto_install »: True des modules de dépôts d'addons.

Un module en auto_install s'installe tout seul dès que ses dépendances le
sont : dans un dépôt d'addons tiers, il arrive sans qu'on l'ait choisi.
Ce script réécrit la valeur dans chaque __manifest__.py, ligne commentée
exceptée, puis, sauf --ignore_commit, committe SEULEMENT les manifestes
modifiés sur la branche courante du dépôt, et sauf --ignore_push la pousse
vers sa branche suivie. Rien d'autre du dépôt n'est indexé, et aucune
branche n'est changée.

Les dépôts se traitent en parallèle (--jobs) : chacun est un clone à part,
et les git qui y tournent ne se gênent pas.

Le menu TODO › Execute › Analyse module appelle `traiter()` sur les dépôts
qu'on y coche.
"""

import argparse
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MESSAGE = "[UPD] addons: set every module auto_install to False"

# La valeur d'une clé auto_install, dans une ligne qui n'est pas un
# commentaire : « "auto_install": True, » et « 'auto_install' : True ».
MOTIF = re.compile(
    r"""^(?P<avant>[^#\n]*?["']auto_install["']\s*:\s*)True\b""", re.M
)

DELAI_GIT = 120


def manifestes(depot):
    """Les __manifest__.py sous `depot`, hors .git, triés."""
    return sorted(
        p
        for p in Path(depot).rglob("__manifest__.py")
        if ".git" not in p.relative_to(depot).parts
    )


def desactiver(depot):
    """Réécrit les auto_install True de `depot` ; rend les fichiers changés."""
    changes = []
    for manifeste in manifestes(depot):
        texte = manifeste.read_text(encoding="utf-8")
        neuf, nombre = MOTIF.subn(r"\g<avant>False", texte)
        if nombre:
            manifeste.write_text(neuf, encoding="utf-8")
            changes.append(manifeste)
    return changes


def git(depot, *args):
    """(code, sortie) de « git -C depot args »."""
    try:
        res = subprocess.run(
            ["git", "-C", str(depot), *args],
            capture_output=True,
            text=True,
            timeout=DELAI_GIT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return res.returncode, (res.stdout + res.stderr).strip()


def commiter(depot, fichiers, message=MESSAGE):
    """Committe `fichiers`, et eux seuls, sur la branche courante."""
    chemins = [str(Path(f).relative_to(depot)) for f in fichiers]
    code, sortie = git(depot, "add", "--", *chemins)
    if code:
        return code, sortie
    return git(depot, "commit", "-m", message, "--", *chemins)


def traiter(depots, commit=False, push=False, jobs=None, message=MESSAGE):
    """Désactive auto_install dans chaque dépôt, en parallèle ; committe et
    pousse si demandé. Rend, dans l'ordre de `depots`, un dict par dépôt :
    {depot, fichiers, commit, push, erreur} — commit et push valent None
    quand ils n'ont pas été tentés, sinon (code, sortie)."""

    def un(depot):
        res = {
            "depot": depot,
            "fichiers": [],
            "commit": None,
            "push": None,
            "erreur": None,
        }
        try:
            res["fichiers"] = desactiver(depot)
        except OSError as exc:
            res["erreur"] = str(exc)
            return res
        if commit and res["fichiers"]:
            res["commit"] = commiter(depot, res["fichiers"], message)
            if push and not res["commit"][0]:
                res["push"] = git(depot, "push")
        return res

    with ThreadPoolExecutor(max_workers=jobs or os.cpu_count() or 4) as ex:
        return list(ex.map(un, depots))


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument(
        "--addons_dir",
        action="append",
        required=True,
        help="Path of an addons repository; repeat it for several.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Repositories handled at once; 0 for the number of CPUs.",
    )
    parser.add_argument(
        "--ignore_commit",
        action="store_true",
        help="Only rewrite the manifests: no commit, no push.",
    )
    parser.add_argument(
        "--ignore_push",
        action="store_true",
        help="Commit without pushing.",
    )
    return parser.parse_args()


def main():
    config = get_config()
    # Le cœur d'Odoo n'est pas un dépôt d'addons : ses auto_install font
    # partie de son fonctionnement.
    depots = [
        d
        for d in config.addons_dir
        if os.path.basename(os.path.normpath(d)) != "odoo"
    ]
    resultats = traiter(
        depots,
        commit=not config.ignore_commit,
        push=not config.ignore_commit and not config.ignore_push,
        jobs=config.jobs or None,
    )
    code_final = 0
    for res in resultats:
        print(f"{res['depot']} : {len(res['fichiers'])} manifest(s)")
        for fichier in res["fichiers"]:
            print(f"  {fichier}")
        for etape in ("erreur", "commit", "push"):
            valeur = res[etape]
            if etape == "erreur" and valeur:
                print(f"  ❌ {valeur}")
                code_final = 1
            elif etape != "erreur" and valeur and valeur[0]:
                print(f"  ❌ {etape} : {valeur[1]}")
                code_final = 1
    return code_final


if __name__ == "__main__":
    raise SystemExit(main())
