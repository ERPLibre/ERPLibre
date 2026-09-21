#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le paquet des backends de VM ne connaît ni menu, ni écran, ni terminal.

Chaque module portait déjà sa propre garde, ce qui laisse un trou : le
module SUIVANT n'en a pas tant que personne n'y pense. Cette épreuve porte
sur le PAQUET, donc sur ce qui n'est pas encore écrit.

Ce qu'elle protège n'est pas une élégance. Un backend qui importerait un
module de menu deviendrait inéprouvable sans terminal, et le premier
consommateur d'un deuxième écran en ferait une copie plutôt que de tirer
sur ce fil.
"""

import ast
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

PAQUET = os.path.join(RACINE, "script", "vm")

# Ce que le paquet a le droit d'importer, en plus de la bibliothèque
# standard. Vide : il ne dépend de rien du dépôt, pas même des postures —
# c'est l'appelant qui rapproche les deux.
DEPENDANCES_PERMISES = ()


def modules():
    return sorted(
        os.path.join(PAQUET, nom)
        for nom in os.listdir(PAQUET)
        if nom.endswith(".py")
    )


def racines_importees(chemin):
    with open(chemin, encoding="utf-8") as handle:
        arbre = ast.parse(handle.read())
    vues = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            vues.update(alias.name for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            vues.add(noeud.module)
    return vues


class TestLeModeDEmploiSuitLePaquet(unittest.TestCase):
    """Un backend ajouté sans être documenté est un backend qu'on découvre
    à l'usage.

    Le README du paquet nomme les trois et dit lequel a tourné contre une
    vraie machine. Ajouter le quatrième sans y toucher laisserait croire
    que la liste est complète — et surtout laisserait croire qu'il est
    éprouvé, ce que le drapeau existe précisément pour empêcher.

    Le contrôle porte sur la SOURCE bilingue et sur CHAQUE langue : une
    ligne retirée d'une seule moitié laisserait l'autre complète, et un
    contrôle sur le texte entier ne verrait rien.
    """

    @staticmethod
    def moities():
        chemin = os.path.join(PAQUET, "README.base.md")
        with open(chemin, encoding="utf-8") as fichier:
            texte = fichier.read()
        anglais, _sep, francais = texte.partition("<!-- [fr] -->")
        return anglais, francais

    def test_every_backend_is_named_on_the_line_that_lists_them(self):
        """Sur LA LIGNE, et non quelque part dans la page : un backend
        retiré de la table se retrouve nommé ailleurs dans le texte, et un
        contrôle sur la page entière ne verrait rien."""
        from script.vm import backend

        for moitie in self.moities():
            lignes = [
                ligne
                for ligne in moitie.splitlines()
                if ligne.strip().startswith("| `backend`")
            ]
            self.assertEqual(1, len(lignes), moitie[:40])
            for nom in backend.BACKENDS:
                with self.subTest(backend=nom, langue=moitie[:30]):
                    self.assertIn(f"`{nom}`", lignes[0])

    def test_the_unproven_one_is_named_as_such(self):
        """Le taire ferait lire « trois backends » là où deux ont tourné
        et le troisième n'a que des épreuves unitaires."""
        from script.vm import backend

        self.assertEqual(
            ["lima"],
            [n for n in backend.BACKENDS if not backend.is_proven(n)],
        )
        for moitie in self.moities():
            with self.subTest(langue=moitie[:30]):
                self.assertIn("lima_confront", moitie)

    def test_every_handle_field_is_documented(self):
        from script.vm import backend

        for moitie in self.moities():
            for champ in backend.VmHandle._fields:
                with self.subTest(champ=champ, langue=moitie[:30]):
                    self.assertIn(f"`{champ}`", moitie)


class TestLePaquetNeDependDeRien(unittest.TestCase):
    def test_there_is_something_to_check(self):
        """Sur un paquet vide, toutes les épreuves d'à côté passent."""
        self.assertGreaterEqual(len(modules()), 4)

    def test_no_module_imports_outside_the_standard_library(self):
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                for nom in racines_importees(chemin):
                    racine = nom.split(".")[0]
                    if nom.startswith("script.vm"):
                        continue
                    if nom in DEPENDANCES_PERMISES:
                        continue
                    self.assertIn(
                        racine,
                        sys.stdlib_module_names,
                        f"{os.path.basename(chemin)} importe « {nom} »",
                    )

    def test_no_module_reaches_into_the_menu_layer(self):
        """Le nommer À PART de la garde générale : c'est l'import qui
        arriverait en premier, et celui dont la conséquence est la pire —
        un backend qu'on ne peut plus éprouver sans terminal."""
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                for nom in racines_importees(chemin):
                    self.assertFalse(
                        nom.startswith("script.todo"),
                        f"{os.path.basename(chemin)} importe « {nom} »",
                    )

    def test_no_module_prints_or_prompts(self):
        """Un backend qui parle décide de la langue et du flux à la place
        de l'écran, et deux écrans ne peuvent plus le rendre autrement."""
        for chemin in modules():
            with self.subTest(module=os.path.basename(chemin)):
                with open(chemin, encoding="utf-8") as handle:
                    arbre = ast.parse(handle.read())
                appels = [
                    noeud.func.id
                    for noeud in ast.walk(arbre)
                    if isinstance(noeud, ast.Call)
                    and isinstance(noeud.func, ast.Name)
                ]
                for interdit in ("print", "input"):
                    self.assertNotIn(interdit, appels)


if __name__ == "__main__":
    unittest.main()
