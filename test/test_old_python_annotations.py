#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que la migration charge doit se charger sous le plus vieux Python.

Le pilote lance ses outils avec le venv de la version Odoo COURANTE : au
premier palier, c'est celui d'Odoo 12, en Python 3.7. Une annotation
« dict | None » (3.10) ou « tuple[str, str] » (3.9) y est ÉVALUÉE au
chargement du module et lève un TypeError avant que l'outil ait rien
fait — la migration meurt sur la restauration du zip.

`from __future__ import annotations` (disponible depuis 3.7) diffère
l'évaluation : le module se charge partout, et le typage reste lisible.
"""

import ast
import io
import json
import os
import re
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
PILOTE = os.path.join(RACINE, "script", "todo", "todo_upgrade.py")
VERSIONS = os.path.join(RACINE, "conf", "supported_version_erplibre.json")

DIFFERE = "from __future__ import annotations"
GENERIQUES = ("list", "dict", "tuple", "set", "type", "frozenset")


def lire(chemin):
    with io.open(chemin, encoding="utf-8") as handle:
        return handle.read()


def annotations_evaluees(arbre):
    """Les annotations que Python évalue au chargement du module.

    Celles d'une signature le sont toujours. Une `x: T` de corps de
    fonction ne l'est pas — la signaler produirait un faux échec.
    """
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = noeud.args
            for arg in (
                list(getattr(a, "posonlyargs", []))
                + list(a.args)
                + list(a.kwonlyargs)
                + [a.vararg, a.kwarg]
            ):
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation
            if noeud.returns is not None:
                yield noeud.returns
        elif isinstance(noeud, (ast.Module, ast.ClassDef)):
            for petit in noeud.body:
                if isinstance(petit, ast.AnnAssign):
                    yield petit.annotation


def trop_recent(source):
    """Les annotations qu'un Python 3.7 ne saurait pas évaluer."""
    if DIFFERE in source:
        return []
    trouves = []
    for annotation in annotations_evaluees(ast.parse(source)):
        for noeud in ast.walk(annotation):
            if isinstance(noeud, ast.BinOp) and isinstance(
                noeud.op, ast.BitOr
            ):
                trouves.append(f"« a | b » ligne {noeud.lineno}")
            elif (
                isinstance(noeud, ast.Subscript)
                and isinstance(noeud.value, ast.Name)
                and noeud.value.id in GENERIQUES
            ):
                trouves.append(f"« {noeud.value.id}[…] » ligne {noeud.lineno}")
    return trouves


def module_vers_chemin(module):
    chemin = os.path.join(RACINE, module.replace(".", os.sep) + ".py")
    return chemin if os.path.isfile(chemin) else None


def importes(source):
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.ImportFrom):
            if noeud.module and noeud.module.startswith("script"):
                yield noeud.module
                for alias in noeud.names:
                    yield f"{noeud.module}.{alias.name}"
        elif isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.name.startswith("script"):
                    yield alias.name


def points_entree():
    """Les scripts que le pilote lance — lus dans le pilote, pas listés.

    Une liste écrite à la main vieillit en silence : le script ajouté
    demain ne serait pas couvert, et c'est justement celui qui casse.
    """
    trouves = set()
    for ref in re.findall(r"\./script/[a-z0-9_/]+\.py", lire(PILOTE)):
        chemin = os.path.join(RACINE, ref[2:])
        if os.path.isfile(chemin):
            trouves.add(chemin)
    return sorted(trouves)


def fermeture():
    vus, pile = set(), list(points_entree())
    while pile:
        chemin = pile.pop()
        if chemin in vus:
            continue
        vus.add(chemin)
        for module in importes(lire(chemin)):
            suivant = module_vers_chemin(module)
            if suivant:
                pile.append(suivant)
    return sorted(vus)


class TestTheDetectorDetects(unittest.TestCase):
    """Un détecteur qui ne détecte rien ferait passer le test à vide."""

    def test_it_flags_a_union_in_a_signature(self):
        self.assertTrue(trop_recent("def f(x: dict | None = None): pass\n"))

    def test_it_flags_a_builtin_generic_return(self):
        self.assertTrue(trop_recent("def f() -> tuple[int, str]: pass\n"))

    def test_a_runtime_union_is_not_an_annotation(self):
        # « set(a) | b » est une union d'ENSEMBLES, valide depuis toujours.
        self.assertEqual(trop_recent("x = set('ab') | set('cd')\n"), [])

    def test_deferring_makes_it_legal(self):
        self.assertEqual(
            trop_recent(f"{DIFFERE}\ndef f(x: dict | None = None): pass\n"), []
        )

    def test_a_body_annotation_is_never_evaluated(self):
        self.assertEqual(
            trop_recent("def f():\n    x: dict | None = None\n    return x\n"),
            [],
        )


class TestTheFloorIsWhatTheProjectDeclares(unittest.TestCase):
    def test_the_oldest_supported_python_is_still_pre_3_9(self):
        # Le jour où la 12 et la 13 disparaissent, ce garde-fou n'a plus
        # de raison d'être : qu'il le dise plutôt que de survivre seul.
        pythons = []
        for valeur in json.loads(lire(VERSIONS)).values():
            if isinstance(valeur, dict) and valeur.get("python_version"):
                pythons.append(
                    tuple(
                        int(x) for x in valeur["python_version"].split(".")[:2]
                    )
                )
        self.assertTrue(pythons)
        self.assertLess(
            min(pythons),
            (3, 9),
            "plus aucune version sous 3.9 : ce test peut disparaître",
        )


class TestWhatTheMigrationLoads(unittest.TestCase):
    def test_the_scan_is_not_empty(self):
        self.assertGreater(len(points_entree()), 10)
        self.assertGreater(len(fermeture()), 15)

    def test_execute_is_in_the_closure(self):
        # Le module par lequel l'incident est arrivé : s'il sortait de la
        # fermeture, le test passerait sans plus rien garder.
        self.assertIn(
            os.path.join(RACINE, "script", "execute", "execute.py"),
            fermeture(),
        )

    def test_every_loaded_module_survives_python_3_7(self):
        coupables = {}
        for chemin in fermeture():
            trouves = trop_recent(lire(chemin))
            if trouves:
                coupables[os.path.relpath(chemin, RACINE)] = trouves
        self.assertEqual(
            coupables,
            {},
            "annotation évaluée au chargement ; ajouter"
            f" « {DIFFERE} » en tête de ces fichiers",
        )


if __name__ == "__main__":
    unittest.main()
