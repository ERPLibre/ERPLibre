#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce source parse-t-il sous le Python de conf/python-erplibre-version ?

Un fichier dont la syntaxe dépasse cet interpréteur ne casse qu'au chargement,
et black ne le voit pas : sa cible borne ce qu'il ÉCRIT, jamais ce qu'il
accepte. L'interpréteur courant compile les fichiers quand sa majeure.mineure
convient, sinon un Python déjà installé le fait ; l'outil n'installe rien et
sort en 0.
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
VERSION = os.path.join(RACINE, "conf", "python-erplibre-version")
EXCLU = re.compile(
    r"(^|/)(\.git|\.venv[^/]*|node_modules|\.repo|__pycache__|addons)/"
)

try:
    sys.path.append(RACINE)
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible
    t = str


# Lu par l'interpréteur visé : n'emploie que de la syntaxe ancienne.
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


def version_voulue():
    """La première ligne ni vide ni commentée du fichier version, ou None."""
    if not os.path.isfile(VERSION):
        return None
    with open(VERSION, encoding="utf-8") as fh:
        lignes = [ligne.strip() for ligne in fh]
    return next((x for x in lignes if x and not x.startswith("#")), None)


def interpreteur(version):
    """Un python `version` déjà là : celui qui tourne, mise, pyenv, le PATH.

    La majeure.mineure suffit : elle seule décide de la grammaire acceptée.
    Lancé depuis .venv.erplibre, l'outil se prend donc lui-même et ne cherche
    nulle part ailleurs."""
    majeure_mineure = ".".join(version.split(".")[:2])
    if ".".join(map(str, sys.version_info[:2])) == majeure_mineure:
        return sys.executable
    if shutil.which("mise"):
        # MISE_OFFLINE : résoudre la version sans interroger le réseau.
        env = dict(os.environ, MISE_OFFLINE="1")
        commande = ["mise", "where", "python@" + version]
        prefixe = lance(commande, env=env, stderr=subprocess.DEVNULL)
        exe = os.path.join(prefixe.strip(), "bin", "python3")
        if prefixe and os.access(exe, os.X_OK):
            return exe
    pyenv = os.environ.get("PYENV_ROOT") or os.path.expanduser("~/.pyenv")
    motif = os.path.join(pyenv, "versions", version + "*", "bin", "python")
    trouves = sorted(p for p in glob.glob(motif) if os.access(p, os.X_OK))
    if trouves:
        return trouves[-1]
    return shutil.which("python" + majeure_mineure)


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
        description=t("does this source parse under the repository Python")
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
    version = version_voulue()
    if not version:
        avis = t("no conf/python-erplibre-version: nothing checked")
        print(avis, file=sys.stderr)
        return 0
    chemins = fichiers(args)
    exe = chemins and interpreteur(version)
    if chemins and not exe:
        avis = t("not checked (no Python %s): mise install python@%s")
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
        bilan = t("%s file(s) refused by Python %s")
        print("\n" + bilan % (refuses, version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
