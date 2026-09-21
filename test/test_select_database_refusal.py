#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le refus de `select_database` doit être lu, partout.

Elle rend FAUX dans trois cas : PostgreSQL illisible, aucune base, et « 0 »
tapé pour renoncer. Composé sans être lu, ce faux devient le mot « False »
dans une ligne de commande — « --database False » — et la commande part
chercher une base de ce nom.

DÉRIVÉ, et non énuméré. Deux appelants l'oubliaient, dont un que le
balayage n'avait pas nommé : la liste des appelants grandit, et une liste
écrite à la main ne la suit pas.
"""

import ast
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

# Les fichiers qui appellent. Trouvés, pas listés.
SOURCES = (
    os.path.join(RACINE, "script", "todo", "database_manager.py"),
    os.path.join(RACINE, "script", "todo", "todo.py"),
)

APPEL = "select_database"


def _nom_appele(noeud):
    """Le nom de la fonction appelée, quelle que soit la forme de l'accès."""
    cible = noeud.func
    return getattr(cible, "attr", None) or getattr(cible, "id", None)


def _lue_en_test(noeud, nom):
    """`nom` apparaît-il en position de TEST dans cette instruction ?

    Un `if not x`, un `return x or None`, un `y if x else None` : dans les
    trois, la valeur est CONFRONTÉE avant d'être employée. Une simple
    mention — `f"--database {x}"` — n'en est pas une, et c'est exactement
    la forme qui composait « False » dans une commande.
    """
    positions = []
    if isinstance(noeud, ast.If):
        positions.append(noeud.test)
    for interne in ast.walk(noeud):
        if isinstance(interne, ast.IfExp):
            positions.append(interne.test)
        elif isinstance(interne, ast.BoolOp):
            positions.extend(interne.values)
        elif isinstance(interne, ast.Compare):
            positions.append(interne.left)
    return any(
        isinstance(n, ast.Name) and n.id == nom
        for position in positions
        for n in ast.walk(position)
    )


def appels_sans_garde():
    """[(fichier, ligne)] pour chaque résultat de `select_database` employé
    sans avoir été confronté juste après."""
    manques = []
    for chemin in SOURCES:
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read(), filename=chemin)
        court = os.path.relpath(chemin, RACINE)
        for noeud in ast.walk(arbre):
            corps = getattr(noeud, "body", None)
            if not isinstance(corps, list):
                continue
            for rang, ligne in enumerate(corps):
                if not (
                    isinstance(ligne, ast.Assign)
                    and isinstance(ligne.value, ast.Call)
                    and _nom_appele(ligne.value) == APPEL
                    and isinstance(ligne.targets[0], ast.Name)
                ):
                    continue
                nom = ligne.targets[0].id
                suivante = corps[rang + 1] if rang + 1 < len(corps) else None
                if suivante is None or not _lue_en_test(suivante, nom):
                    manques.append((court, ligne.lineno))
    return manques


class TestChaqueAppelLitLeRefus(unittest.TestCase):
    def test_no_caller_uses_the_value_before_testing_it(self):
        self.assertEqual([], appels_sans_garde())

    def test_the_scan_actually_finds_the_calls(self):
        """Un analyseur qui ne trouve aucun appel passe le test précédent
        sans rien garder."""
        trouves = 0
        for chemin in SOURCES:
            with open(chemin, encoding="utf-8") as fichier:
                arbre = ast.parse(fichier.read())
            trouves += sum(
                1
                for n in ast.walk(arbre)
                if isinstance(n, ast.Call) and _nom_appele(n) == APPEL
            )
        self.assertGreater(trouves, 4)

    def test_a_bare_use_is_seen_as_missing(self):
        """Contrôle du DÉTECTEUR : composer la valeur sans la confronter
        est exactement le défaut, et il doit se voir."""
        source = (
            "def f(self):\n"
            "    nom = self.select_database()\n"
            "    return f'--database {nom}'\n"
        )
        corps = ast.parse(source).body[0].body
        self.assertFalse(_lue_en_test(corps[1], "nom"))

    def test_the_three_guarded_shapes_are_accepted(self):
        """Contrôle inverse : un détecteur qui refuse tout ferait rougir le
        dépôt entier et s'apprendrait à désarmer."""
        for suite in (
            "    if not nom:\n        return\n",
            "    return nom or None\n",
            "    return (1, nom) if nom else None\n",
            "    if nom is None:\n        return\n",
        ):
            corps = (
                ast.parse(
                    "def f(self):\n    nom = self.select_database()\n" + suite
                )
                .body[0]
                .body
            )
            self.assertTrue(_lue_en_test(corps[1], "nom"), suite.strip())


if __name__ == "__main__":
    unittest.main()
