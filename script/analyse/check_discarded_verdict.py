#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce dépôt lit ce verdict — sauf ici.

UN VERDICT JETÉ SE LIT COMME UN SUCCÈS. Une fonction qui rend un code de
retour, un refus ou un « contenu inconnu » le rend pour qu'on le lise ;
appelée en instruction nue, sa réponse tombe, et l'appelant continue comme
si tout s'était bien passé. C'est ainsi qu'un écran annonce une suppression
qu'un garde venait de refuser, ou qu'une installation part sur une machine
dont les règles de sortie ne se sont pas chargées.

LA PREUVE EST DIFFÉRENTIELLE, ET C'EST CE QUI REND L'OUTIL UTILISABLE. Une
fonction dont le retour est utile se reconnaît à ce que le dépôt le LIT
ailleurs. L'outil ne juge donc pas ce qu'une valeur vaut : il compare les
appels entre eux, et ne signale une instruction nue que là où la MOITIÉ AU
MOINS des autres appels lisent la réponse.

Cela se règle tout seul. Une fonction qui traite sa propre panne — elle
interroge l'opérateur, elle rejoue, elle lève — est ignorée par presque tous
ses appelants, qui ont raison : la part tombe sous la moitié et rien n'est
dit. Une liste d'exemptions aurait fait le même travail en vieillissant.

CE QUI RESTE HORS DE PORTÉE, et le dire vaut mieux que le laisser croire :
l'outil ne résout que ce qu'il voit SANS AMBIGUÏTÉ — une fonction du même
fichier, ou une méthode appelée par `self`. Un verdict qui traverse un
collaborateur, `self.execute.lancer(...)`, lui échappe : deux classes
peuvent porter la même méthode, et deviner ferait crier au loup.

Toute trouvaille est un SIGNAL À RELIRE. Un appelant a parfois raison
d'ignorer ce que les autres lisent, et c'est à lui de le dire — en une
ligne, là où il le fait.

Codes de sortie, convention partagée des outils du dépôt : 0 rien à
signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys

_ICI = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ICI not in sys.path:
    sys.path.insert(0, _ICI)

from script.analyse.lib_check import (  # noqa: E402
    etend,
    fichiers_indexes,
    peindre,
    relatif,
)
from script.todo.todo_i18n import t  # noqa: E402

# Il faut au moins DEUX retours de valeur pour qu'une fonction rende un
# verdict : un seul décrit une fabrique, qui rend toujours la même sorte de
# chose et dont personne n'attend un refus.
RETOURS_MINIMUM = 2

# La part des appels qui LISENT la réponse, au-dessous de laquelle le silence
# est la convention de la maison et non un oubli.
PART_MINIMUM = 0.5


def _retours_de_valeur(fonction):
    """Les `return <valeur>` de cette fonction. `return None` n'en est pas."""
    return [
        n
        for n in ast.walk(fonction)
        if isinstance(n, ast.Return)
        and n.value is not None
        and not (isinstance(n.value, ast.Constant) and n.value.value is None)
    ]


def _cible(appel):
    """Le nom appelé, s'il se résout SANS AMBIGUÏTÉ dans ce fichier.

    Une fonction du module, ou une méthode de `self`. Tout le reste — un
    attribut d'un collaborateur, un alias importé — demanderait de deviner
    quelle définition est visée, et deviner fait crier au loup.
    """
    cible = appel.func
    if isinstance(cible, ast.Name):
        return cible.id
    if (
        isinstance(cible, ast.Attribute)
        and isinstance(cible.value, ast.Name)
        and cible.value.id == "self"
    ):
        return cible.attr
    return ""


def inspect(chemin: str):
    """[{file, line, function, read, ignored}] pour ce fichier."""
    with open(chemin, encoding="utf-8") as fichier:
        texte = fichier.read()
    try:
        arbre = ast.parse(texte, chemin)
    except SyntaxError:
        # Un fichier qui ne s'analyse pas n'est pas notre affaire : lever
        # ici arrêterait un hook sur un fichier en cours d'écriture.
        return []
    rendeuses = {
        f.name
        for f in ast.walk(arbre)
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
        and len(_retours_de_valeur(f)) >= RETOURS_MINIMUM
    }
    if not rendeuses:
        return []
    # Les appels NUS, par nom. Leur ligne sert ensuite à reconnaître les
    # autres : un appel dont la valeur est lue vit dans une expression.
    nus = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            nom = _cible(n.value)
            if nom in rendeuses:
                nus.setdefault(nom, []).append(n.value.lineno)
    lignes_nues = {ligne for v in nus.values() for ligne in v}
    lus = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            nom = _cible(n)
            if nom in rendeuses and n.lineno not in lignes_nues:
                lus[nom] = lus.get(nom, 0) + 1
    trouvailles = []
    for nom, lignes in nus.items():
        combien_lus = lus.get(nom, 0)
        part = combien_lus / (combien_lus + len(lignes))
        if part < PART_MINIMUM:
            continue
        for ligne in lignes:
            trouvailles.append(
                {
                    "file": relatif(chemin),
                    "line": ligne,
                    "function": nom,
                    "read": combien_lus,
                    "ignored": len(lignes),
                }
            )
    return sorted(trouvailles, key=lambda f: (f["file"], f["line"]))


def render(trouvailles, colour=True):
    """Le rapport, groupé par fichier."""
    if not trouvailles:
        return ""
    lignes = []
    fichier = None
    for f in trouvailles:
        if f["file"] != fichier:
            fichier = f["file"]
            lignes.append(peindre(fichier, "1", colour))
        lignes.append(
            f"  🟡 {f['line']:>5}  {f['function'][:34]:<34}"
            f" {t('read %s times here, ignored %s') % (f['read'], f['ignored'])}"
        )
    lignes.append("")
    lignes.append(
        t("%s verdict(s) dropped where this file reads them — read again")
        % peindre(len(trouvailles), "33", colour)
    )
    return "\n".join(lignes)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t("a verdict dropped where the same file reads it")
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
