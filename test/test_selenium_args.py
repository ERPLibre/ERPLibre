#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chaque couche réconcilie SES options, et les points d'entrée l'appellent.

LA COUCHE QUI POSSÈDE LES DEUX PILOTES N'AVAIT PAS DE `compute_args`. Sa
réconciliation — « Chrome demandé éteint Firefox » — vivait dans une
fonction que les deux points d'entrée contournaient en appelant
`parse_args()` directement. Conséquence : `--use_chrome_driver` laissait
`use_firefox_driver` à vrai, donc les deux blocs gardés par ce drapeau
appelaient `driver.install_addon`, une API propre à Firefox, sur un pilote
Chrome.

Latent seulement parce qu'aucune cible make n'emploie Chrome — ce qui rend
l'épreuve d'autant plus nécessaire : rien ne l'aurait montré à l'usage.

Ni navigateur ni réseau : seuls les arguments sont calculés.
"""

import argparse
import ast
import io
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.selenium import selenium_lib  # noqa: E402


def analyse(*argv):
    """Les arguments d'une ligne de commande, réconciliés comme en vrai."""
    parser = argparse.ArgumentParser()
    selenium_lib.fill_parser(parser)
    args = parser.parse_args(list(argv))
    selenium_lib.compute_args(args)
    return args


class TestLesDeuxPilotesNeSePartagentPas(unittest.TestCase):
    def test_asking_for_chrome_turns_firefox_off(self):
        """Les deux drapeaux vrais font partir « install_addon », propre à
        Firefox, sur un pilote Chrome."""
        args = analyse("--use_chrome_driver")
        self.assertTrue(args.use_chrome_driver)
        self.assertFalse(args.use_firefox_driver)

    def test_firefox_stays_the_default(self):
        args = analyse()
        self.assertFalse(args.use_chrome_driver)
        self.assertTrue(args.use_firefox_driver)

    def test_asking_for_firefox_leaves_it_alone(self):
        args = analyse("--use_firefox_driver")
        self.assertTrue(args.use_firefox_driver)
        self.assertFalse(args.use_chrome_driver)


class TestChaqueEntreeReconcilieSaBase(unittest.TestCase):
    """Le point d'entrée appelle les `compute_args` de chaque couche qu'il
    a remplie, de la plus basse à la sienne. Sauter la plus basse est ce
    qui laissait la réconciliation des pilotes sans effet."""

    def appels(self, chemin):
        arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
        principal = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef) and n.name == "main"
        ]
        self.assertEqual(1, len(principal), chemin)
        rendus = []
        for noeud in ast.walk(principal[0]):
            if not isinstance(noeud, ast.Call):
                continue
            cible = noeud.func
            if isinstance(cible, ast.Attribute):
                rendus.append(cible.attr)
            elif isinstance(cible, ast.Name):
                rendus.append(cible.id)
        return rendus

    def test_both_entry_points_reconcile_the_base_layer(self):
        for chemin in (
            "script/selenium/web_login.py",
            "script/selenium/scenario/selenium_devops.py",
        ):
            with self.subTest(chemin=chemin):
                rendus = self.appels(os.path.join(RACINE, chemin))
                self.assertIn("fill_parser", rendus)
                self.assertIn("compute_args", rendus)


if __name__ == "__main__":
    unittest.main()
