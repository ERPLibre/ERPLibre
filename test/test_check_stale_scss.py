#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un SCSS personnalisé est une copie figée, comme une vue COW.

Personnaliser un site écrit du SCSS dans `ir_attachment`. Cette copie est
figée le jour où elle est écrite et continue d'employer les variables de
CETTE version. Un module peut les renommer d'un palier à l'autre : mesuré,
`website/.../primary_variables.scss` déclarait `$o-theme-font-number` en 12.0
et a remplacé tout le mécanisme en 13.0. Une personnalisation de 2020
demandait encore l'ancien nom, et le bundle s'arrêtait dessus.

Ce qui rend un tel détecteur utilisable n'est pas de trouver — c'est de ne
pas crier à tort. Sur le seul fichier mesuré, la première version rapportait
dix noms dont six n'étaient pas des manques : paramètres de mixin, variables
de boucle, arguments nommés d'`@include`. Ces tests portent surtout là-dessus.
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))

import check_stale_scss as scss  # noqa: E402


class TestWhatCountsAsAUse(unittest.TestCase):
    def test_a_plain_dereference_is_a_use(self):
        self.assertIn("color", scss.used_names("a { b: $color; }"))

    def test_a_declaration_is_not_a_use(self):
        self.assertNotIn("color", scss.used_names("$color: red;"))

    def test_a_named_include_argument_is_not_a_use(self):
        # LE faux positif mesuré : « @include o-position-absolute(
        # $right: 50%) » se lisait comme l'usage d'un $right inexistant.
        source = "@include o-position-absolute($right: 50%, $left: 50%);"
        self.assertEqual(scss.used_names(source), set())

    def test_a_default_value_is_not_a_use(self):
        self.assertNotIn("size", scss.used_names("$size: 3 !default;"))

    def test_the_name_is_not_truncated_to_dodge_the_colon(self):
        # Une négation en tête de motif fait rétrograder le nom : le premier
        # essai rapportait « $botto » au lieu d'écarter « $bottom ».
        names = scss.used_names("a { b: $bottom-margin; }")
        self.assertEqual(names, {"bottom-margin"})

    def test_a_use_after_a_declaration_still_counts(self):
        self.assertEqual(scss.used_names("$a: $b;"), {"b"})


class TestWhatTheFileBindsItself(unittest.TestCase):
    def test_mixin_parameters_are_bound(self):
        source = "@mixin thing($on, $off: 2) { a: $on; b: $off; }"
        self.assertEqual(scss.bound_names(source), {"on", "off"})

    def test_function_parameters_are_bound(self):
        source = "@function f($value) { @return $value; }"
        self.assertIn("value", scss.bound_names(source))

    def test_each_loop_variables_are_bound(self):
        source = "@each $key, $val in $map { a: $key; }"
        bound = scss.bound_names(source)
        self.assertIn("key", bound)
        self.assertIn("val", bound)

    def test_for_loop_variables_are_bound(self):
        source = "@for $counter from 1 through 3 { a: $counter; }"
        self.assertIn("counter", scss.bound_names(source))


class TestTheUrlIsSplitForTheFix(unittest.TestCase):
    """reset_asset veut le fichier ET le bundle ; l'URL porte les deux."""

    def test_a_frontend_customization(self):
        base, bundle = scss.split_custom_url(
            "/website/static/src/scss/website.custom.web.assets_frontend.scss"
        )
        self.assertEqual(base, "/website/static/src/scss/website.scss")
        self.assertEqual(bundle, "web.assets_frontend")

    def test_a_common_customization(self):
        base, bundle = scss.split_custom_url(
            "/website/static/src/scss/options/colors/"
            "user_theme_color_palette.custom.web.assets_common.scss"
        )
        self.assertTrue(base.endswith("user_theme_color_palette.scss"))
        self.assertEqual(bundle, "web.assets_common")


class TestTheReport(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_nothing_at_risk_says_so(self):
        text = scss.render([], "db", "odoo13.0")
        self.assertIn("✅", text)

    def test_a_finding_names_the_attachment_and_the_variable(self):
        text = scss.render(
            [
                (
                    1110,
                    "/a/b.custom.web.assets_frontend.scss",
                    ["o-theme-font-number"],
                )
            ],
            "db",
            "odoo13.0",
        )
        self.assertIn("1110", text)
        self.assertIn("$o-theme-font-number", text)

    def test_it_prints_a_command_that_can_be_pasted(self):
        # Un diagnostic sans le geste qui répare oblige à rechercher les deux
        # arguments de reset_asset au pire moment.
        text = scss.render(
            [(1110, "/a/b.custom.web.assets_frontend.scss", ["x"])],
            "mydb",
            "odoo13.0",
        )
        self.assertIn("reset_asset('/a/b.scss', 'web.assets_frontend')", text)
        self.assertIn("-d mydb", text)

    def test_it_warns_before_dropping(self):
        text = scss.render(
            [(1110, "/a/b.custom.web.assets_frontend.scss", ["x"])],
            "db",
            "odoo13.0",
        )
        self.assertIn("real customization", text)


class TestTheMigrationRunsIt(unittest.TestCase):
    def test_it_is_checked_at_the_same_place_as_the_cow_views(self):
        # Les deux prédictions valent avant le palier, pas après : c'est le
        # seul moment où l'on peut encore arbitrer sans avoir tout rejoué.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertIn("check_stale_scss.py", source)
        self.assertLess(
            source.index("check_stale_scss.py"),
            source.index("4 - Upgrade version with OpenUpgrade"),
        )


if __name__ == "__main__":
    unittest.main()
