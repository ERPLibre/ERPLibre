#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce source parse-t-il sous le Python plancher de conf/python-erplibre-floor ?

Ni black ni flake8 ne voient une syntaxe plus récente que le plancher : elle
ne casse qu'à l'import, sous l'ancien interpréteur. Un Python du plancher déjà
installé compile les fichiers ; l'outil n'installe rien et sort en 0.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from subprocess import PIPE

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PLANCHER = os.path.join(RACINE, "conf", "python-erplibre-floor")
EXCLU = re.compile(
    r"(^|/)(\.git|\.venv[^/]*|node_modules|\.repo|__pycache__|addons)/"
)

try:
    sys.path.append(RACINE)
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible
    t = str


# Lu par l'interpréteur du PLANCHER : n'emploie que sa syntaxe.
SONDE = r"""
import sys
for nom in sys.argv[1:]:
    try:
        with open(nom, "rb") as fh:
            compile(fh.read(), nom, "exec", dont_inherit=True)
    except Exception as exc:
        ligne = getattr(exc, "lineno", None) or 1
        print("%s\t%s\t%s" % (nom, ligne, getattr(exc, "msg", exc)))
"""


def lance(cmd, **options):
    """La sortie standard de cmd, vide sur échec ; l'erreur standard passe."""
    try:
        fin = subprocess.run(cmd, stdout=PIPE, errors="replace", **options)
    except (OSError, subprocess.SubprocessError):
        return ""
    return fin.stdout if fin.returncode == 0 else ""


def plancher():
    """La première ligne ni vide ni commentée du fichier plancher, ou None."""
    if not os.path.isfile(PLANCHER):
        return None
    with open(PLANCHER, encoding="utf-8") as fh:
        lignes = [ligne.strip() for ligne in fh]
    return next((x for x in lignes if x and not x.startswith("#")), None)


def interpreteur(version):
    """Un python `version` déjà installé : mise, pyenv, puis le PATH."""
    if shutil.which("mise"):
        # MISE_OFFLINE : résoudre « 3.10 » sans interroger le réseau.
        env = dict(os.environ, MISE_OFFLINE="1")
        commande = ["mise", "where", "python@" + version]
        prefixe = lance(commande, env=env, stderr=subprocess.DEVNULL)
        exe = os.path.join(prefixe.strip(), "bin", "python3")
        if prefixe and os.access(exe, os.X_OK):
            return exe
    pyenv = os.environ.get("PYENV_ROOT") or os.path.expanduser("~/.pyenv")
    motif = os.path.join(pyenv, "versions", version + "*", "bin", "python")
    trouves = sorted(p for p in glob.glob(motif) if os.access(p, os.X_OK))
    return trouves[-1] if trouves else shutil.which("python" + version)


def est_python(chemin):
    """Suffixe .py, ou fichier sans suffixe dont le hashbang nomme python."""
    if EXCLU.search(chemin) or not os.path.isfile(chemin):
        return False
    if os.path.splitext(chemin)[1]:
        return chemin.endswith(".py")
    with open(chemin, "rb") as fh:
        premiere = fh.readline(200)
    return premiere.startswith(b"#!") and b"python" in premiere


def fichiers(args):
    """Les fichiers Python désignés : l'index git, ou les chemins parcourus."""
    if args.staged:
        git = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
        noms = lance(git, cwd=RACINE).splitlines()
        chemins = [os.path.relpath(os.path.join(RACINE, n)) for n in noms]
        return [c for c in chemins if est_python(c)]
    trouves = []
    for chemin in args.paths:
        trouves += [chemin] if est_python(chemin) else []
        for base, dossiers, noms in os.walk(chemin):
            dossiers[:] = [d for d in dossiers if not EXCLU.search(d + "/")]
            complets = (os.path.join(base, n) for n in sorted(noms))
            trouves += [c for c in complets if est_python(c)]
    return trouves


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t("does this source parse under the floor Python")
    )
    parser.add_argument("paths", nargs="*")
    parser.add_argument(
        "--staged",
        action="store_true",
        help=t("only the files added to the git index"),
    )
    args = parser.parse_args(argv)
    if not args.staged and not args.paths:
        parser.error(t("give a path, or --staged"))
    version = plancher()
    if not version:
        avis = t("no floor in conf/python-erplibre-floor: nothing checked")
        print(avis, file=sys.stderr)
        return 0
    chemins = fichiers(args)
    exe = chemins and interpreteur(version)
    if chemins and not exe:
        avis = t("floor not checked (no Python %s): mise install python@%s")
        print(avis % (version, version), file=sys.stderr)
    if not exe:
        return 0
    fichier, refuses = None, 0
    for ligne in lance([exe, "-c", SONDE, *chemins]).splitlines():
        nom, numero, message = ligne.split("\t", 2)
        if nom != fichier:
            fichier, refuses = nom, refuses + 1
            print(nom)
        print(f"  🔴 {numero:>5}  {message}")
    if refuses:
        bilan = t("%s file(s) refused by Python %s, the floor")
        print("\n" + bilan % (refuses, version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
