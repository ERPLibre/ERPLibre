#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qui doit tenir avant de toucher à une base de production.

Deux propriétés portent tout le reste. La première : sans `--apply`,
RIEN ne s'écrit — un outil de diagnostic qui répare tout seul est un
piège. La seconde : le compte de visibilité doit être fait avec un vrai
utilisateur, jamais en sudo, car la règle globale d'OCA DMS ne s'applique
pas au super-utilisateur et un compte en sudo dirait « tout va bien »
alors que personne ne voit rien.
"""

import ast
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo.migration import dms_access_repair as repair  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


class TestTheGeneratedScript(unittest.TestCase):
    def test_the_dry_run_never_creates_anything(self):
        # Le garde vit dans le script POUSSÉ : c'est lui qui décide, pas
        # l'appelant. Un `DRY = True` qui n'entoure pas le `create` ne
        # protège de rien.
        code = repair.build_script(dry_run=True)
        self.assertIn("DRY = True", code)
        arbre = ast.parse(code)
        creations = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "create"
        ]
        self.assertTrue(creations, "aucune création dans le script ?")
        for noeud in creations:
            self.assertTrue(
                self._under_dry_guard(arbre, noeud),
                "une création hors du garde `not DRY`",
            )

    @staticmethod
    def _under_dry_guard(arbre, cible):
        """La création est-elle sous un `if not DRY ...` ?"""
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.If):
                continue
            texte = ast.dump(noeud.test)
            if "DRY" not in texte:
                continue
            for enfant in ast.walk(noeud):
                if enfant is cible:
                    return True
        return False

    def test_apply_lifts_the_guard(self):
        self.assertIn("DRY = False", repair.build_script(dry_run=False))

    def test_the_script_is_valid_python(self):
        for dry in (True, False):
            ast.parse(repair.build_script(dry_run=dry))

    def test_visibility_is_measured_with_a_real_user(self):
        # `with_user` est le point tout entier : en sudo, la règle globale
        # ne s'applique pas et le rapport serait rassurant à tort.
        code = repair.build_script(dry_run=True)
        self.assertIn("with_user(temoin)", code)
        self.assertIn("u.id != 1", code)

    def test_it_reuses_the_shared_sentinels(self):
        from script.odoo.migration import database_cleanup

        self.assertEqual(repair.DEBUT, database_cleanup.START)
        self.assertEqual(repair.FIN, database_cleanup.END)


class TestTheReport(unittest.TestCase):
    PLEIN = {
        "files": 69,
        "directories": 16,
        "access_groups_before": 0,
        "witness": "marie@example.org",
        "before": {"directories": 0, "files": 0},
        "roots": ["CNESST", "Contrat"],
        "already_repaired": False,
    }

    def test_it_shows_what_exists_and_what_is_seen(self):
        texte = "\n".join(repair.render(self.PLEIN, dry_run=True))
        self.assertIn("69", texte)
        self.assertIn("marie@example.org", texte)

    def test_a_dry_run_says_nothing_was_written(self):
        texte = "\n".join(repair.render(self.PLEIN, dry_run=True))
        self.assertIn(
            todo_i18n.t("Nothing written. Re-run with --apply."), texte
        )

    def test_an_applied_run_reports_the_new_visibility(self):
        rapport = dict(self.PLEIN, after={"directories": 16, "files": 69})
        texte = "\n".join(repair.render(rapport, dry_run=False))
        self.assertIn(todo_i18n.t("Now visible to"), texte)

    def test_an_already_repaired_database_says_so_and_stops(self):
        rapport = dict(self.PLEIN, already_repaired=True)
        texte = "\n".join(repair.render(rapport, dry_run=True))
        self.assertIn(
            todo_i18n.t("Already repaired: the group exists."), texte
        )
        self.assertNotIn(
            todo_i18n.t("Would create one access group over"), texte
        )

    def test_no_witness_is_flagged_not_silently_fine(self):
        # Sans utilisateur témoin on ne SAIT pas : le taire ferait passer
        # une base muette pour une base saine.
        rapport = dict(self.PLEIN, before=None, witness=None)
        texte = "\n".join(repair.render(rapport, dry_run=True))
        self.assertIn(
            todo_i18n.t("No DMS user to test visibility with."), texte
        )

    def test_every_translation_key_exists(self):
        with io.open(
            repair.__file__.replace(".pyc", ".py"), encoding="utf-8"
        ) as handle:
            src = handle.read()
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                self.assertIn(node.args[0].value, todo_i18n.TRANSLATIONS)


class TestTheVersionGuard(unittest.TestCase):
    def setUp(self):
        from script.odoo.migration import database_cleanup

        self.cleanup = database_cleanup
        self.vraie = database_cleanup.require_matching_version
        self.vrai_shell = database_cleanup.run_shell
        self.appels = []
        database_cleanup.run_shell = (
            lambda *a, **k: self.appels.append(a) or {}
        )

    def tearDown(self):
        self.cleanup.require_matching_version = self.vraie
        self.cleanup.run_shell = self.vrai_shell

    def test_a_mismatch_stops_before_opening_the_database(self):
        # Un Odoo d'une autre version ÉCRIT avant d'échouer : le refus
        # doit précéder toute ouverture, pas la suivre.
        self.cleanup.require_matching_version = lambda base: "18.0 vs 12.0"
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = repair.main(["-d", "vieille_base"])
        self.assertEqual(code, 2)
        self.assertEqual(self.appels, [])
        self.assertIn("18.0 vs 12.0", tampon.getvalue())


if __name__ == "__main__":
    unittest.main()
