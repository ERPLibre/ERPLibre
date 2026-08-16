#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« Vers quelle version migrer ? » : Entrée doit viser la plus haute.

C'est le choix qu'on fait presque toujours — migrer, c'est aller au bout —
et il fallait le taper. Pire : `click.prompt` sans `default` REDEMANDE sur
une ligne vide, sans rien afficher. Entrée n'atteignait donc aucun code ;
une valeur par défaut ajoutée sans ce `default=""` n'aurait jamais servi et
rien ne l'aurait signalé.

La plus haute se calcule, elle ne se lit pas au bout de la liste : l'ordre
d'affichage n'est pas une garantie, la comparaison en est une.
"""

import ast
import inspect
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class TestTheSource(unittest.TestCase):
    """Le choix se joue dans une boucle interactive de mille lignes.

    On vérifie donc les décisions à la source : que le défaut soit calculé
    par comparaison, et que click puisse rendre une ligne vide.
    """

    def source(self):
        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_click_can_return_an_empty_line(self):
        # SANS cela, click redemande en silence et Entrée n'arrive jamais
        # jusqu'au code qui applique le défaut.
        source = self.source()
        appel = source.index("click.prompt(")
        fenetre = source[appel : appel + 160]
        self.assertIn('default=""', fenetre)

    def test_the_default_is_the_highest_not_the_last(self):
        source = self.source()
        self.assertIn("max(", source)
        self.assertIn('float(a.get("prompt_description"))', source)

    def test_the_default_is_announced(self):
        # Un défaut qu'on ne montre pas est un défaut que personne n'utilise.
        self.assertIn("Enter =", self.source())


class TestTheChoiceItself(unittest.TestCase):
    """Le calcul du défaut, extrait et rejoué sur des listes réelles."""

    def highest(self, lst_version):
        lst_odoo_version = [{"prompt_description": v} for v in lst_version]
        return (
            max(
                lst_odoo_version,
                key=lambda a: float(a.get("prompt_description")),
            ).get("prompt_description")
            if lst_odoo_version
            else None
        )

    def test_the_case_reported(self):
        # Base en 12.0 : la liste proposée va de 13.0 à 18.0.
        self.assertEqual(
            self.highest(["13.0", "14.0", "15.0", "16.0", "17.0", "18.0"]),
            "18.0",
        )

    def test_an_unsorted_list_still_gives_the_highest(self):
        # Prendre le dernier élément marcherait par chance ; comparer marche.
        self.assertEqual(self.highest(["18.0", "13.0", "16.0"]), "18.0")

    def test_a_single_choice(self):
        self.assertEqual(self.highest(["18.0"]), "18.0")

    def test_no_choice_at_all_has_no_default(self):
        # Une base déjà à la version maximale : proposer un défaut
        # inexistant ferait planter là où il n'y a simplement rien à faire.
        self.assertIsNone(self.highest([]))

    def test_two_digit_versions_compare_as_numbers(self):
        # « 9.0 » > « 18.0 » en tri de chaînes : la comparaison numérique
        # est ce qui évite de proposer une version antérieure.
        self.assertEqual(self.highest(["9.0", "18.0"]), "18.0")


class TestTheGuardIsReachable(unittest.TestCase):
    def test_the_empty_answer_is_handled_before_the_int(self):
        # int("") lève ValueError et retomberait sur « Commande non
        # trouvée » : le cas vide doit être traité AVANT.
        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        vide = source.index("if not str(status).strip()")
        conversion = source.index("int_cmd = int(status)")
        self.assertLess(vide, conversion)

    def test_the_module_still_parses(self):
        path = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(path) as handle:
            ast.parse(handle.read())


if __name__ == "__main__":
    unittest.main()
