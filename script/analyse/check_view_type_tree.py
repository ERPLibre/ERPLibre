#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le type de vue « tree » qui survit dans un module, et casse à l'usage.

Odoo 18 a supprimé le type `tree`. La sélection de `ir.ui.view.type` est
`list, form, graph, pivot, calendar, kanban, search, qweb`
(ir_ui_view.py:153), et le noyau ne porte AUCUNE conversion de
compatibilité — vérifié par balayage : la seule occurrence hors `etree`
est `odoo/tests/form.py:261`, sans rapport.

Pourquoi cet outil-ci ne lit pas la base
----------------------------------------
C'est l'angle mort de tous les autres. Un module resté sur `<tree>` ne
s'installe pas : il n'y a donc RIEN à lire en base, et un rapport tiré de
la base dit « tout va bien » avec assurance. Le défaut est sur le DISQUE,
et il revient à chaque resynchronisation de Google Repo.

Le piège, et pourquoi ni grep ni regex
--------------------------------------
« tree » est d'abord un morceau d'IDENTIFIANT. Sur 465 occurrences
mesurées dans `odoo18.0/addons`, une soixantaine cassent ; le reste est
un id de `<record>`, un `<field name="name">`, un `env.ref()`, un nom de
variable. Et ce n'est pas de la négligence : le noyau 18 a gardé ses
propres identifiants historiques en ne renommant que les balises —
`account.view_invoice_tree` existe toujours, son arch en `<list>`.

La démonstration tient en deux lignes du même dépôt :

    openeducat_admission/models/admission.py:420
        (tree_view and tree_view.id or False, 'list')     ← sain
    openeducat_fees/models/student.py:142
        (tree_view and tree_view.id or False, 'tree')     ← cassé

Même nom de variable, même forme. Seul le littéral en POSITION de type
décide. D'où la règle : lxml et `ast`, jamais la ligne brute. Le bénéfice
est double — les commentaires disparaissent d'eux-mêmes, puisque ni l'un
ni l'autre ne construit de nœud pour eux.

Trois portes avant tout motif
-----------------------------
Ce sont elles qui font le tri, pas les motifs.

1. VERSION — rien à faire sous la 18 : `tree` y est valide.
2. MODULE — un fichier ne compte que sous un `__manifest__.py`, lu par
   `literal_eval`. `installable: False` disqualifie le module entier.
3. CHARGEMENT — un XML doit figurer dans `data` ou `demo` ; un Python
   doit être ATTEIGNABLE depuis `__init__.py`. Un fichier que personne ne
   charge ne casse rien, et `literal_eval` fait disparaître d'elle-même
   toute entrée commentée du manifeste.

Ce que la balise en sous-vue fait vraiment
------------------------------------------
Un `<tree>` sous un x2many n'est pas ignoré poliment : `ir_ui_view.py`
ne le reconnaît pas, donc ne le RETIRE pas, et ses `<field>` repartent
dans la validation avec le modèle du formulaire PARENT. Le message parle
alors d'un champ inexistant et ne prononce jamais le mot « tree ».
"""

from __future__ import annotations

import ast
import io
import os
import sys
import warnings

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
FICHIER_VERSION = ".odoo-version"
PREMIERE_VERSION_SANS_TREE = (18, 0)
MANIFESTE = "__manifest__.py"

COULEURS = {
    "broken": "\033[31m",
    "watch": "\033[33m",
    "ok": "\033[32m",
    "step": "\033[36m",
    "dim": "\033[90m",
}
RESET = "\033[0m"


def paint(texte, genre, colour):
    """Teinter, ou rendre le texte tel quel quand la couleur est coupée."""
    if not colour:
        return texte
    return f"{COULEURS.get(genre, '')}{texte}{RESET}"


def version_active(racine=REPO_ROOT):
    """(majeur, mineur) du checkout, ou None si illisible."""
    try:
        with io.open(
            os.path.join(racine, FICHIER_VERSION), encoding="utf-8"
        ) as handle:
            brut = handle.read().strip()
    except OSError:
        return None
    morceaux = brut.split(".")
    try:
        return (int(morceaux[0]), int(morceaux[1]))
    except (IndexError, ValueError):
        return None


def concerne(version):
    """La 18 et au-delà. Sous elle, `tree` est valide — au pire déprécié."""
    return bool(version) and version >= PREMIERE_VERSION_SANS_TREE


def lire_manifeste(chemin):
    """Le dict du manifeste, par `literal_eval` — jamais par import.

    Un `__manifest__.py` est une expression, pas un programme : l'évaluer
    exécuterait du code d'un dépôt tiers pour lire quatre clés. Et
    `literal_eval` fait disparaître d'elle-même toute entrée commentée.
    """
    try:
        with io.open(chemin, encoding="utf-8") as handle:
            valeur = ast.literal_eval(handle.read())
    except (OSError, ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return valeur if isinstance(valeur, dict) else None


def modules(racine):
    """[(chemin du module, manifeste)] — ceux qu'Odoo installerait.

    `installable: False` disqualifie : Odoo ne le liste même pas, il ne
    peut casser ni à l'installation ni à l'exécution.
    """
    lst = []
    for dossier, sous, fichiers in os.walk(racine):
        if MANIFESTE not in fichiers:
            continue
        sous[:] = []  # un module ne contient pas un autre module
        manifeste = lire_manifeste(os.path.join(dossier, MANIFESTE))
        if manifeste is None:
            continue
        if manifeste.get("installable", True) is False:
            continue
        lst.append((dossier, manifeste))
    return sorted(lst)


def xml_charges(module, manifeste):
    """Les XML que le manifeste demande de charger, et qui existent."""
    lst, absents = [], []
    for clef in ("data", "demo"):
        for relatif in manifeste.get(clef) or []:
            if not isinstance(relatif, str) or not relatif.endswith(".xml"):
                continue
            chemin = os.path.join(module, relatif)
            (lst if os.path.isfile(chemin) else absents).append(chemin)
    return lst, absents


def py_atteignables(module):
    """Les .py qu'un `import` du module finit par charger.

    On SUIT les `from . import x`, plutôt que de ramasser tout le dossier :
    un fichier que personne n'importe ne s'exécute jamais, et le signaler
    ferait crier sur des brouillons laissés là.
    """
    vus, atteints = set(), []
    pile = [module]
    while pile:
        paquet = pile.pop()
        init = os.path.join(paquet, "__init__.py")
        if init in vus or not os.path.isfile(init):
            continue
        vus.add(init)
        atteints.append(init)
        try:
            with io.open(init, encoding="utf-8") as handle:
                arbre = ast.parse(handle.read())
        except (OSError, SyntaxError, ValueError):
            continue
        for noeud in ast.walk(arbre):
            noms = []
            if isinstance(noeud, ast.ImportFrom) and noeud.level:
                if noeud.module:
                    noms.append(noeud.module)
                noms += [a.name for a in noeud.names]
            elif isinstance(noeud, ast.Import):
                noms = [a.name.split(".")[0] for a in noeud.names]
            for nom in noms:
                relatif = nom.replace(".", os.sep)
                fichier = os.path.join(paquet, relatif + ".py")
                dossier = os.path.join(paquet, relatif)
                if os.path.isfile(fichier) and fichier not in vus:
                    vus.add(fichier)
                    atteints.append(fichier)
                elif os.path.isdir(dossier):
                    pile.append(dossier)
    return [c for c in atteints if os.sep + "tests" + os.sep not in c]


def _modes(texte):
    """« form, tree » → ['form', 'tree'] — le découpage est obligatoire.

    Un simple `in` attraperait aussi un futur « treemap », et raterait
    l'espace après la virgule que les vues réelles écrivent.
    """
    return [x.strip() for x in (texte or "").split(",")]


def ligne_de_la_balise(chemin, sourceline, balise="tree"):
    """lxml rend la ligne où FINIT la balise ouvrante ; on remonte.

    Mesuré : sur une balise étalée sur six lignes, `sourceline` disait 66
    quand `<tree` commençait à 61. Citer la fin envoie chercher au mauvais
    endroit.
    """
    try:
        with io.open(chemin, encoding="utf-8", errors="replace") as handle:
            lignes = handle.readlines()
    except OSError:
        return sourceline
    for rang in range(min(sourceline, len(lignes)) - 1, -1, -1):
        if "<" + balise in lignes[rang]:
            return rang + 1
    return sourceline


def constats_xml(chemin):
    """[(ligne, motif, extrait, correction)] pour UN fichier de vues."""
    from lxml import etree

    try:
        arbre = etree.parse(chemin)
    except (etree.XMLSyntaxError, OSError):
        return None  # illisible : c'est un constat à part, pas un « tree »
    lst = []
    for el in arbre.iter():
        # Ce test, et lui seul, écarte commentaires et instructions de
        # traitement : lxml ne construit pas d'élément pour un <!-- -->.
        if not isinstance(el.tag, str):
            continue
        if el.tag == "tree":
            lst.append(
                (
                    ligne_de_la_balise(chemin, el.sourceline),
                    "xml_balise",
                    "<tree>",
                    "<list>",
                )
            )
            continue
        expr = el.get("expr")
        if expr:
            segments = expr.replace("//", "/").split("/")
            for segment in segments:
                if segment.split("[")[0] == "tree":
                    lst.append((el.sourceline, "xml_xpath", expr[:70], "list"))
                    break
        if el.tag != "field":
            continue
        nom = el.get("name")
        texte = (el.text or "").strip()
        if nom == "view_mode" and "tree" in _modes(texte):
            lst.append(
                (
                    el.sourceline,
                    "xml_view_mode",
                    texte[:60],
                    texte.replace("tree", "list"),
                )
            )
        elif nom == "type" and texte == "tree":
            lst.append((el.sourceline, "xml_type", texte, "list"))
    return lst


def _est_tuple_de_vue(noeud):
    """(id, 'tree') — un couple dont le SECOND membre est le type.

    Le premier membre est un id, False, un Name ou une expression : jamais
    une chaîne. Sans cette condition, la règle crierait sur les couples de
    compatibilité ('list', 'tree'), qui sont du code défensif correct.
    """
    if not isinstance(noeud, (ast.Tuple, ast.List)) or len(noeud.elts) != 2:
        return False
    premier, second = noeud.elts
    if not isinstance(second, ast.Constant) or second.value != "tree":
        return False
    return not (
        isinstance(premier, ast.Constant) and isinstance(premier.value, str)
    )


def constats_py(chemin):
    """[(ligne, motif, extrait, correction)] pour UN fichier python."""
    try:
        with io.open(chemin, encoding="utf-8") as handle:
            source = handle.read()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            arbre = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None
    lst = []
    for noeud in ast.walk(arbre):
        if _est_tuple_de_vue(noeud):
            lst.append(
                (noeud.lineno, "py_views", "(…, 'tree')", "(…, 'list')")
            )
            continue
        if not isinstance(noeud, ast.Dict):
            continue
        paires = {
            clef.value: valeur
            for clef, valeur in zip(noeud.keys, noeud.values)
            if isinstance(clef, ast.Constant) and isinstance(clef.value, str)
        }
        est_action = (
            isinstance(paires.get("type"), ast.Constant)
            and paires["type"].value == "ir.actions.act_window"
        )
        for clef in ("view_mode", "view_type"):
            valeur = paires.get(clef)
            if not isinstance(valeur, ast.Constant):
                continue
            if not isinstance(valeur.value, str):
                continue
            if "tree" not in _modes(valeur.value):
                continue
            # `view_type` sur un dict d'act_window est un vestige d'Odoo 12
            # que la 18 ignore sans bruit. Ailleurs — un `code.generator.
            # view`, dont la sélection ne propose que `list` — il lève.
            if clef == "view_type" and est_action:
                continue
            lst.append(
                (
                    valeur.lineno,
                    "py_" + clef,
                    valeur.value[:60],
                    valeur.value.replace("tree", "list"),
                )
            )
    return lst


def inspect(racine, sous_dossier="addons"):
    """{'findings': […], 'unreadable': […], 'missing': […]} pour un checkout."""
    version = version_active(racine)
    rapport = {
        "version": version,
        "scanned": 0,
        "findings": [],
        "unreadable": [],
        "missing": [],
    }
    if not concerne(version):
        return rapport
    base = os.path.join(racine, "odoo%d.%d" % version, sous_dossier)
    if not os.path.isdir(base):
        return rapport
    for module, manifeste in modules(base):
        rapport["scanned"] += 1
        court = os.path.basename(module)
        charges, absents = xml_charges(module, manifeste)
        for chemin in absents:
            rapport["missing"].append((court, os.path.relpath(chemin, racine)))
        for chemin in charges:
            lst = constats_xml(chemin)
            if lst is None:
                rapport["unreadable"].append(
                    (court, os.path.relpath(chemin, racine))
                )
                continue
            for ligne, motif, extrait, correction in lst:
                rapport["findings"].append(
                    (
                        court,
                        os.path.relpath(chemin, racine),
                        ligne,
                        motif,
                        extrait,
                        correction,
                    )
                )
        for chemin in py_atteignables(module):
            lst = constats_py(chemin)
            if lst is None:
                rapport["unreadable"].append(
                    (court, os.path.relpath(chemin, racine))
                )
                continue
            for ligne, motif, extrait, correction in lst:
                rapport["findings"].append(
                    (
                        court,
                        os.path.relpath(chemin, racine),
                        ligne,
                        motif,
                        extrait,
                        correction,
                    )
                )
    return rapport


def render(rapport, colour=True):
    """Le rapport lisible, groupé par module."""
    lignes = [f"🌲 {t('View type tree, removed in Odoo 18')}", ""]
    if not concerne(rapport["version"]):
        lignes.append(
            paint(
                f"   {t('nothing to do below 18.0 — tree is valid there')}",
                "dim",
                colour,
            )
        )
        return "\n".join(lignes)

    trouves = rapport["findings"]
    if not trouves:
        lignes.append(
            paint(
                f"✅ {t('No module carries it.')}"
                f" ({rapport['scanned']} {t('modules read')})",
                "ok",
                colour,
            )
        )
    par_module = {}
    for module, chemin, ligne, motif, extrait, correction in trouves:
        par_module.setdefault(module, []).append(
            (chemin, ligne, motif, extrait, correction)
        )
    for module in sorted(par_module):
        lst = par_module[module]
        lignes.append(
            paint(f"❌ {str(len(lst)).rjust(4)}  {module}", "broken", colour)
        )
        for chemin, ligne, motif, extrait, correction in sorted(lst):
            lignes.append(paint(f"          {chemin}:{ligne}", "dim", colour))
            lignes.append(f"            {extrait}  →  {correction}")
        lignes.append("")

    # Deux constats voisins, jamais mélangés aux « tree » : ils ont une
    # autre cause et une autre réparation.
    for clef, titre, genre in (
        ("missing", "listed in the manifest, absent from disk", "broken"),
        ("unreadable", "listed in the manifest, unparsable", "watch"),
    ):
        if rapport[clef]:
            lignes.append(paint(f"{t(titre)} :", genre, colour))
            for module, chemin in sorted(rapport[clef]):
                lignes.append(paint(f"      {chemin}", "dim", colour))
            lignes.append("")
    return "\n".join(lignes).rstrip()


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("Modules still carrying the removed tree view type."),
    )
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"❌ {args.root}", file=sys.stderr)
        return 2

    rapport = inspect(args.root)
    if args.json:
        print(
            json.dumps(
                {
                    "odoo": (
                        "%d.%d" % rapport["version"]
                        if rapport["version"]
                        else None
                    ),
                    "modules_read": rapport["scanned"],
                    "findings": [
                        {
                            "module": m,
                            "file": f,
                            "line": ligne,
                            "pattern": motif,
                            "found": extrait,
                            "replace_with": corr,
                        }
                        for m, f, ligne, motif, extrait, corr in rapport[
                            "findings"
                        ]
                    ],
                    "missing_files": [f for _m, f in rapport["missing"]],
                    "unparsable_files": [f for _m, f in rapport["unreadable"]],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(rapport, colour))
    return 1 if rapport["findings"] or rapport["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
