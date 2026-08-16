#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« Vers quelle version migrer ? » : Entrée doit viser la plus haute.

C'est le choix qu'on fait presque toujours — migrer, c'est aller au bout — et
il fallait le taper. `click.prompt` reçoit donc un défaut : il affiche
« [6] » et rend « 6 » sur Entrée, si bien que la réponse suit le chemin
normal, sans second comportement à tenir d'accord avec le premier.

Deux pièges, tous deux vérifiés ici :

- SANS `default`, click redemande en silence sur une ligne vide. Une valeur
  par défaut ajoutée sans lui n'aurait jamais été atteinte, et rien ne
  l'aurait signalé.
- « 6 » est le rang de 18.0 AUJOURD'HUI. Une version de plus au catalogue le
  déplace ; écrit en dur, il ferait choisir 18.0 quand l'écran propose 19.0.
"""

import ast
import inspect
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


def prompt_call(source):
    """Le voisinage de l'appel à click.prompt, où se joue le défaut."""
    start = source.index("click.prompt(")
    return source[start : start + 240]


class TestTheSource(unittest.TestCase):
    """Le choix se joue dans une boucle interactive de mille lignes.

    On vérifie donc les décisions là où elles s'écrivent : que click reçoive
    un défaut, qu'il soit calculé, et que la question dise la version.
    """

    def source(self):
        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_click_receives_a_default(self):
        # Sans lui, Entrée n'atteint aucun code : click redemande, muet.
        window = prompt_call(self.source())
        self.assertIn("default=", window)
        self.assertIn("default_index", window)

    def test_the_default_is_not_written_by_hand(self):
        window = prompt_call(self.source())
        self.assertNotIn('default="6"', window)
        self.assertNotIn("default=6", window)

    def test_the_rank_is_computed_by_comparison(self):
        # Lire le dernier élément marcherait par chance : l'ordre
        # d'affichage n'est pas une garantie.
        source = self.source()
        self.assertIn("max(", source)
        self.assertIn("range(len(lst_odoo_version))", source)

    def test_an_empty_catalogue_shows_no_default(self):
        # show_default sur une chaîne vide afficherait « [] », qui se lit
        # comme un choix possible.
        self.assertIn(
            "show_default=bool(default_index)", prompt_call(self.source())
        )

    def test_the_question_announces_the_version_not_the_rank(self):
        # click montre « [6] » ; seul le texte dit que c'est 18.0.
        source = self.source()
        self.assertIn("Enter =", source)
        self.assertIn("default_version", source)

    def test_no_special_case_survives(self):
        # click rendant « 6 », le chemin normal suffit. Un cas particulier
        # de plus serait un second comportement à maintenir.
        self.assertNotIn("if not str(status).strip()", self.source())


class TestTheRankItself(unittest.TestCase):
    """Le calcul du défaut, rejoué sur des catalogues réels."""

    def rank(self, lst_version):
        """Le rang affiché de la plus haute version, comme le code le fait."""
        lst_odoo_version = [{"prompt_description": v} for v in lst_version]
        if not lst_odoo_version:
            return None
        return (
            max(
                range(len(lst_odoo_version)),
                key=lambda i: float(
                    lst_odoo_version[i].get("prompt_description")
                ),
            )
            + 1
        )

    def test_the_case_reported(self):
        # Base en 12.0 : la liste proposée va de 13.0 à 18.0, donc [6].
        self.assertEqual(
            self.rank(["13.0", "14.0", "15.0", "16.0", "17.0", "18.0"]), 6
        )

    def test_it_follows_a_new_version(self):
        # LE point : le jour où 19.0 entre au catalogue, le défaut devient
        # [7] sans que personne ne touche au code.
        self.assertEqual(
            self.rank(
                ["13.0", "14.0", "15.0", "16.0", "17.0", "18.0", "19.0"]
            ),
            7,
        )

    def test_an_unsorted_list_points_at_the_highest(self):
        self.assertEqual(self.rank(["18.0", "13.0", "16.0"]), 1)

    def test_versions_compare_as_numbers(self):
        # « 9.0 » se trie après « 18.0 » en chaînes : la comparaison
        # numérique est ce qui évite de proposer une version antérieure.
        self.assertEqual(self.rank(["9.0", "18.0"]), 2)

    def test_a_single_choice(self):
        self.assertEqual(self.rank(["18.0"]), 1)

    def test_no_choice_at_all_has_no_rank(self):
        # Une base déjà à la version maximale : pas de défaut plutôt qu'une
        # erreur là où il n'y a rien à faire.
        self.assertIsNone(self.rank([]))


class TestClickReallyReturnsIt(unittest.TestCase):
    """Ce que click fait vraiment, mesuré et non supposé."""

    def answer(self, typed, default):
        import io
        import sys

        import click

        original = sys.stdin
        sys.stdin = io.StringIO(typed)
        try:
            return click.prompt(
                "", default=default, show_default=True, prompt_suffix=""
            )
        finally:
            sys.stdin = original

    def test_enter_returns_the_default(self):
        self.assertEqual(self.answer("\n", "6"), "6")

    def test_a_typed_value_wins(self):
        self.assertEqual(self.answer("2\n", "6"), "2")

    def test_without_a_default_enter_is_swallowed(self):
        # La raison d'être du `default` : ici click redemande, et c'est la
        # SECONDE ligne qui revient. Entrée n'aurait rien déclenché.
        import io
        import sys

        import click

        original = sys.stdin
        sys.stdin = io.StringIO("\n2\n")
        try:
            self.assertEqual(click.prompt("", prompt_suffix=""), "2")
        finally:
            sys.stdin = original


class TestTheModuleStillParses(unittest.TestCase):
    def test_it_parses(self):
        path = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(path) as handle:
            ast.parse(handle.read())


if __name__ == "__main__":
    unittest.main()
