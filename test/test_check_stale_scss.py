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

    def finding(self, **override):
        data = {
            "id": 1110,
            "url": "/a/b.custom.web.assets_frontend.scss",
            "missing": ["o-theme-font-number"],
            "custom": "a { b: $o-theme-font-number; }",
            "base_url": "/a/b.scss",
            "bundle": "web.assets_frontend",
            "module_path": "odoo13.0/a/b.scss",
            "module_content": "a { b: 1; }",
            "version_dir": "odoo13.0",
            "database": "db",
        }
        data.update(override)
        return data

    def test_nothing_at_risk_says_so(self):
        text = scss.render([], "db", "odoo13.0")
        self.assertIn("✅", text)

    def test_a_finding_names_the_attachment_and_the_variable(self):
        text = scss.render([self.finding()], "db", "odoo13.0")
        self.assertIn("1110", text)
        self.assertIn("$o-theme-font-number", text)

    def test_it_prints_a_command_that_can_be_pasted(self):
        # Un diagnostic sans le geste qui répare oblige à rechercher les deux
        # arguments de reset_asset au pire moment.
        text = scss.render([self.finding()], "mydb", "odoo13.0")
        self.assertIn("reset_asset('/a/b.scss', 'web.assets_frontend')", text)
        self.assertIn("-d mydb", text)

    def test_it_warns_before_dropping(self):
        text = scss.render([self.finding()], "db", "odoo13.0")
        self.assertIn("real customization", text)


class TestTheDiff(unittest.TestCase):
    """Ce que la copie a changé : la seule chose que réinitialiser perd."""

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def finding(self, **override):
        data = {
            "id": 1110,
            "url": "/a/b.custom.web.assets_frontend.scss",
            "missing": ["x"],
            "custom": "a { b: 2; }",
            "base_url": "/a/b.scss",
            "bundle": "web.assets_frontend",
            "module_path": "odoo13.0/a/b.scss",
            "module_content": "a { b: 1; }",
            "version_dir": "odoo13.0",
            "database": "db",
        }
        data.update(override)
        return data

    def test_it_counts_what_would_be_lost(self):
        text = scss.render_diff(self.finding())
        self.assertIn("+1/-1", text)

    def test_an_identical_copy_says_it_loses_nothing(self):
        text = scss.render_diff(self.finding(custom="a { b: 1; }"))
        self.assertIn("identical", text)

    def test_a_missing_module_file_is_said_not_guessed(self):
        # Si la cible ne livre plus le fichier, il n'y a rien sur quoi
        # retomber : le taire ferait accepter une réinitialisation vide.
        text = scss.render_diff(self.finding(module_path=None))
        self.assertIn("no longer ships", text)


class TestThePrompt(unittest.TestCase):
    """Regarder ne doit pas répondre à la question."""

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def finding(self):
        return {
            "id": 1,
            "url": "/a/b.custom.web.assets_frontend.scss",
            "missing": ["x"],
            "custom": "a { b: 2; }",
            "base_url": "/a/b.scss",
            "bundle": "web.assets_frontend",
            "module_path": "odoo13.0/a/b.scss",
            "module_content": "a { b: 1; }",
            "version_dir": "odoo13.0",
            "database": "db",
        }

    def run_prompt(self, answers):
        import contextlib
        import io

        seq = iter(answers)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            wrote = scss.prompt(
                [self.finding()], "db", ask=lambda prompt: next(seq)
            )
        return wrote, out.getvalue()

    def test_enter_writes_nothing(self):
        wrote, text = self.run_prompt([""])
        self.assertFalse(wrote)
        self.assertEqual(text, "")

    def test_v_shows_the_diff_and_asks_again(self):
        # Sans le « asks again », montrer vaudrait réponse : on aurait vu le
        # diff et perdu la main sur la décision.
        wrote, text = self.run_prompt(["v", ""])
        self.assertFalse(wrote)
        self.assertIn("+1/-1", text)

    def test_apply_saves_a_copy_before_writing(self):
        # reset_asset SUPPRIME la pièce jointe : sans sauvegarde préalable,
        # les lignes personnalisées ne seraient plus nulle part.
        import os
        import tempfile

        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(tempfile.mkdtemp())
        seen = {}
        original = scss.apply_reset
        scss.apply_reset = lambda lst, db, cfg="./config.conf": (
            seen.update(called=True),
            (0, "ok"),
        )[1]
        self.addCleanup(setattr, scss, "apply_reset", original)
        wrote, text = self.run_prompt(["a"])
        self.assertTrue(wrote)
        self.assertTrue(seen.get("called"))
        import glob

        saved = glob.glob("private/odoo/migration/db/scss_backup/*")
        self.assertEqual(len(saved), 1)
        with open(saved[0]) as handle:
            self.assertEqual(handle.read(), "a { b: 2; }")

    def test_a_failed_reset_says_nothing_changed(self):
        import os
        import tempfile

        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(tempfile.mkdtemp())
        original = scss.apply_reset
        scss.apply_reset = lambda lst, db, cfg="./config.conf": (1, "boom")
        self.addCleanup(setattr, scss, "apply_reset", original)
        wrote, text = self.run_prompt(["a"])
        self.assertFalse(wrote)
        self.assertIn("nothing was changed", text)


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

    def test_no_call_goes_through_the_piped_executor(self):
        # L'outil pose lui-même ses questions : un TUBE les rendrait
        # injoignables, sans rien signaler — Python met sa sortie en
        # tampon par blocs et l'invite reste invisible.
        #
        # Les DEUX voies terminal conviennent : `run_on_terminal` laisse
        # le vrai terminal, `run_captured` en fabrique un et garde une
        # copie. Seul `todo_upgrade_execute` bufferise.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        depart = 0
        vus = 0
        while True:
            rang = source.find("check_stale_scss.py", depart)
            if rang < 0:
                break
            vus += 1
            avant = source[:rang]
            # L'appel le plus proche EN AMONT : c'est lui qui exécute.
            terminal = max(
                avant.rfind("run_on_terminal("), avant.rfind("run_captured(")
            )
            self.assertGreater(
                terminal,
                avant.rfind("todo_upgrade_execute("),
                "l'outil repasse par l'exécuteur à tube",
            )
            depart = rang + 1
        self.assertEqual(2, vus)


class TestTheFixCannotRunTooEarly(unittest.TestCase):
    """Corriger exige la version d'ARRIVÉE, pas celle de départ.

    Mesuré sur une vraie migration : la question a été posée avant le palier,
    alors que le checkout était encore sur odoo12.0. Répondre « a » a lancé
    reset_asset dans un shell Odoo 12, qui ne connaît pas `web_editor.assets`
    — KeyError, rien de modifié, et la migration a continué jusqu'à casser au
    palier suivant.

    Prédire tôt reste juste. C'est corriger tôt qui ne l'est pas.
    """

    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_a_version_without_reset_asset_is_refused(self):
        import os
        import tempfile

        root = tempfile.mkdtemp()
        old = os.path.join(root, "odoo12.0", "addons", "web_editor", "models")
        os.makedirs(old)
        with open(os.path.join(old, "assets.py"), "w") as handle:
            handle.write("class Assets:\n    pass\n")
        self.assertFalse(scss.reset_supported(os.path.join(root, "odoo12.0")))

    def test_a_version_with_it_is_allowed(self):
        import os
        import tempfile

        root = tempfile.mkdtemp()
        new = os.path.join(root, "odoo13.0", "addons", "web_editor", "models")
        os.makedirs(new)
        with open(os.path.join(new, "assets.py"), "w") as handle:
            handle.write("def reset_asset(self, url, bundle):\n    pass\n")
        self.assertTrue(scss.reset_supported(os.path.join(root, "odoo13.0")))

    def test_an_unknown_checkout_does_not_block(self):
        # Rien pour trancher : refuser sur une supposition empêcherait de
        # corriger là où c'est possible.
        self.assertTrue(scss.reset_supported("odoo_no_such_dir_zz"))

    def test_the_prompt_hides_the_fix_when_it_cannot_work(self):
        # Offrir un choix qui échouera, c'est le faire prendre.
        import contextlib
        import io

        original = scss.reset_supported
        scss.reset_supported = lambda odoo_dir=None: False
        self.addCleanup(setattr, scss, "reset_supported", original)
        finding = {
            "id": 1,
            "url": "/a/b.custom.web.assets_frontend.scss",
            "missing": ["x"],
            "custom": "a",
            "base_url": "/a/b.scss",
            "bundle": "web.assets_frontend",
            "module_path": None,
            "module_content": "",
            "version_dir": "odoo13.0",
            "database": "db",
        }
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            wrote = scss.prompt([finding], "db", ask=lambda p: "a")
        self.assertFalse(wrote)
        self.assertIn("KeyError", out.getvalue())
        self.assertNotIn("a = reset", out.getvalue())


class TestTheMigrationAsksAtTheRightMoment(unittest.TestCase):
    """Prédire avant le palier, corriger après — jamais l'inverse."""

    def source(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_the_early_call_cannot_offer_the_fix(self):
        source = self.source()
        premier = source.index("check_stale_scss.py")
        fenetre = source[premier : premier + 400]
        self.assertIn("--report-only", fenetre)

    def test_a_second_call_comes_after_the_bump(self):
        # Sans elle, la prédiction n'aurait jamais de suite : on saurait ce
        # qui va casser sans jamais pouvoir le réparer.
        source = self.source()
        self.assertEqual(source.count("check_stale_scss.py"), 2)
        second = source.rindex("check_stale_scss.py")
        self.assertGreater(second, source.index("state_4_upgrade_odoo_lst"))

    def test_the_second_call_targets_the_upgraded_database(self):
        source = self.source()
        second = source.rindex("check_stale_scss.py")
        fenetre = source[second : second + 300]
        self.assertIn("database_name_upgrade", fenetre)
        self.assertNotIn("--report-only", fenetre)


class TestThePromptStaysOutOfAPipe(unittest.TestCase):
    def test_it_only_asks_in_front_of_a_terminal(self):
        # Une invite dans un tube bloquerait l'appelant sur une question que
        # personne ne voit.
        with open(scss.__file__) as handle:
            source = handle.read()
        self.assertIn("sys.stdin.isatty()", source)


if __name__ == "__main__":
    unittest.main()
