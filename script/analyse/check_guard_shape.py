#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un garde mesure-t-il une PROPRIÉTÉ, ou l'orthographe du code ?

LA LEÇON QUE CET OUTIL MÉCANISE. Un garde épinglé à son propre ÉCRITURE —
un fragment d'expression recopié du source — est vert le jour où il devrait
être rouge, et rouge le jour d'une amélioration. Le second défaut coûte plus
cher que le premier : un garde qui rougit à tort est un garde qu'on apprend
à désarmer.

Deux cas, et ils vont dans les deux sens. Un contrôle comparait quatre
chaînes exactes pour interdire l'écriture sur disque :
`open(path, "wb")` y passait — le littéral cherché n'en est pas un préfixe —
pendant qu'un COMMENTAIRE nommant l'interdit, comme les conventions
l'exigent, le faisait rougir. Un autre épinglait un fragment de SQL : il
restait vert sur l'inversion des deux bras d'un `coalesce`, qui casse tout
l'appariement, et rougissait sur un changement de préfixe sans conséquence.

CE QUI EST SIGNALÉ, ET CE QUI NE L'EST PAS. L'outil cherche une comparaison
— `assertIn` et ses voisines — dont un argument est le TEXTE SOURCE d'un
module Python, obtenu par `inspect.getsource` ou par la lecture d'un `.py`.
Il ne retient que les littéraux qui sont des FRAGMENTS D'EXPRESSION.

Un NOM seul — `run_psql`, `self._qemu_verify_vm(` — est un contrôle de
CÂBLAGE : « ce chemin passe-t-il par là ». La propriété est réelle, même si
l'arbre syntaxique la tiendrait mieux, et la signaler noierait le signal.

Toute trouvaille est un SIGNAL À RELIRE et jamais une certitude : l'outil ne
sait pas si le fragment cherché EST la propriété — l'ordre de deux gestes,
par exemple, ne se lit qu'ainsi. Il ne tranche pas à la place du lecteur.

Il se signale lui-même : les exemples cités dans cette docstring sont du
texte, pas des appels, donc rien ici ne correspond. Ses propres épreuves,
elles, en portent de vrais — ce sont ses témoins.

Codes de sortie, convention partagée des outils du dépôt : 0 rien à
signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.todo.todo_i18n import t  # noqa: E402

SUFFIXES = (".py",)

# Ce qui rend le TEXTE d'un module. `getsourcefile` est là parce qu'il ouvre
# la porte à une lecture juste après, et que la chercher séparément la
# raterait sur une ligne coupée.
INSPECTE = ("getsource", "getsourcelines", "getsourcefile")

# Les comparaisons qui portent sur du texte. `assertEqual` n'y est pas : sur
# du source entier il ne peut que constater l'identité, ce que personne
# n'écrit, et sur un extrait il compare autre chose.
COMPARE = ("assertIn", "assertNotIn", "assertRegex", "assertNotRegex")

# Un NOM, éventuellement suivi d'un appel SANS ARGUMENT. C'est ce qui
# distingue « ce chemin passe par là » de « ce code s'écrit ainsi ». Les
# parenthèses vides restent un câblage ; dès qu'un argument y entre, c'est
# la forme de l'appel qui est épinglée et non son existence.
NOM = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?:\(\)?)?$")

# Ce qui n'est pas balayé : ce qui n'est pas à nous, et ce qui n'est pas lu.
IGNORES = (
    ".git/",
    ".venv",
    "__pycache__/",
    "addons/",
    "node_modules/",
)


def a_balayer(chemin: str) -> bool:
    nu = chemin.replace(os.sep, "/")
    return not any(motif in nu for motif in IGNORES)


def _nom_appele(noeud) -> str:
    """Le nom de la fonction appelée, quelle que soit la forme de l'accès."""
    cible = noeud.func
    return getattr(cible, "attr", None) or getattr(cible, "id", None) or ""


def _nomme_un_module(noeud) -> bool:
    """L'expression cite-t-elle un fichier `.py` ?"""
    return any(
        isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value.endswith(".py")
        for n in ast.walk(noeud)
    )


def _rend_du_source(noeud, modules) -> bool:
    """Cette expression rend-elle le TEXTE d'un module Python ?

    `modules` porte les noms liés à un chemin `.py` ailleurs dans le
    fichier : la lecture est souvent écrite loin de l'affectation, et exiger
    les deux sur la même ligne raterait la forme la plus courante.
    """
    for n in ast.walk(noeud):
        if not isinstance(n, ast.Call):
            continue
        appele = _nom_appele(n)
        if appele in INSPECTE:
            return True
        if appele in ("read", "read_text") and (
            _nomme_un_module(n)
            or any(
                isinstance(p, ast.Name) and p.id in modules
                for p in ast.walk(n)
            )
        ):
            return True
    return False


def _fragments(noeud):
    """Les littéraux comparés qui sont des fragments d'expression."""
    return [
        a.value
        for a in noeud.args
        if isinstance(a, ast.Constant)
        and isinstance(a.value, str)
        and a.value.strip()
        and not NOM.match(a.value)
    ]


def inspect(chemin: str):
    """[{file, line, function, excerpt}] pour ce fichier."""
    with open(chemin, encoding="utf-8") as fichier:
        texte = fichier.read()
    try:
        arbre = ast.parse(texte, chemin)
    except SyntaxError:
        # Un fichier qui ne s'analyse pas n'est pas notre affaire : le reste
        # de l'outillage le dira mieux, et lever ici arrêterait un hook sur
        # un fichier en cours d'écriture.
        return []
    modules = {
        cible.id
        for n in ast.walk(arbre)
        if isinstance(n, ast.Assign) and _nomme_un_module(n.value)
        for cible in n.targets
        if isinstance(cible, ast.Name)
    }
    trouvailles = []
    for fonction in ast.walk(arbre):
        if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        textuels = {
            cible.id
            for n in ast.walk(fonction)
            if isinstance(n, ast.Assign) and _rend_du_source(n.value, modules)
            for cible in n.targets
            if isinstance(cible, ast.Name)
        }
        for n in ast.walk(fonction):
            if not (isinstance(n, ast.Call) and _nom_appele(n) in COMPARE):
                continue
            vise_du_source = any(
                (isinstance(a, ast.Name) and a.id in textuels)
                or _rend_du_source(a, modules)
                for a in n.args
            )
            if not vise_du_source:
                continue
            for fragment in _fragments(n)[:1]:
                trouvailles.append(
                    {
                        "file": os.path.relpath(chemin, RACINE),
                        "line": n.lineno,
                        "function": fonction.name,
                        "excerpt": fragment[:64],
                    }
                )
    return sorted(trouvailles, key=lambda f: (f["file"], f["line"]))


def fichiers_indexes():
    """Les fichiers ajoutés à l'index git, filtrés sur les suffixes lus."""
    sortie = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        cwd=RACINE,
    )
    chemins = []
    for nom in sortie.stdout.split("\n"):
        nom = nom.strip()
        if (
            nom.endswith(SUFFIXES)
            and a_balayer(nom)
            and os.path.isfile(os.path.join(RACINE, nom))
        ):
            chemins.append(os.path.join(RACINE, nom))
    return chemins


def etend(chemins):
    """Les fichiers lisibles d'une liste de chemins, répertoires parcourus."""
    trouves = []
    for chemin in chemins:
        if os.path.isdir(chemin):
            for base, _sous, noms in os.walk(chemin):
                if not a_balayer(base + "/"):
                    continue
                for nom in sorted(noms):
                    complet = os.path.join(base, nom)
                    if nom.endswith(SUFFIXES) and a_balayer(complet):
                        trouves.append(complet)
        elif chemin.endswith(SUFFIXES) and a_balayer(chemin):
            trouves.append(chemin)
    return trouves


def render(trouvailles, colour=True):
    """Le rapport, groupé par fichier."""
    if not trouvailles:
        return ""

    def peindre(texte, code):
        return f"\033[{code}m{texte}\033[0m" if colour else texte

    lignes = []
    fichier = None
    for f in trouvailles:
        if f["file"] != fichier:
            fichier = f["file"]
            lignes.append(peindre(fichier, "1"))
        lignes.append(
            f"  🟡 {f['line']:>5}  {f['function'][:34]:<34} « {f['excerpt']} »"
        )
    lignes.append("")
    lignes.append(
        t("%s guard(s) pinned to the source text — read them again")
        % peindre(len(trouvailles), "33")
    )
    return "\n".join(lignes)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "does a guard measure a property, or the spelling of the code"
        )
    )
    parser.add_argument("paths", nargs="*", default=[])
    parser.add_argument(
        "--staged",
        action="store_true",
        help=t("only the files added to the git index"),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if args.staged:
        chemins = fichiers_indexes()
    elif args.paths:
        chemins = etend(args.paths)
    else:
        parser.error(t("give a path, or --staged"))
        return 2

    trouvailles = []
    for chemin in chemins:
        try:
            trouvailles.extend(inspect(chemin))
        except OSError as exc:
            print(f"❌ {chemin} : {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(
            json.dumps(
                {"scanned": len(chemins), "findings": trouvailles},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        rapport = render(trouvailles, colour=not args.no_color)
        if rapport:
            print(rapport)
    return 1 if trouvailles else 0


if __name__ == "__main__":
    sys.exit(main())
