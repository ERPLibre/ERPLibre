#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le test qui aurait vu venir la disparition des documents DMS.

Une propriété porte tout : le comptage se fait avec de VRAIS utilisateurs
internes, jamais avec le super-utilisateur. Les règles ne s'appliquent pas
à lui ; un comptage fait en son nom déclarerait saine une base que
personne ne peut lire — exactement l'erreur qui a laissé passer le cas
DMS pendant six paliers.
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

from script.odoo.migration import check_hidden_models as check  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


class TestTheGeneratedScript(unittest.TestCase):
    def test_it_is_valid_python(self):
        ast.parse(check.build_script())

    def test_the_superuser_is_excluded(self):
        # Sans cette exclusion, tout paraît visible et le test ne sert à
        # rien : c'est le cœur du sujet.
        code = check.build_script()
        self.assertIn('("id", "!=", 1)', code)

    def test_only_internal_users_count(self):
        # Un portail ne voit presque rien par construction : l'inclure
        # ferait crier au loup sur des modèles parfaitement sains.
        self.assertIn('("share", "=", False)', check.build_script())

    def test_only_active_users_count(self):
        self.assertIn('("active", "=", True)', check.build_script())

    def test_it_looks_at_global_rules_only(self):
        # Une règle non globale ne s'applique qu'à certains groupes :
        # qu'elle masque tout pour eux est normal.
        code = check.build_script()
        self.assertIn('("global", "=", True)', code)
        self.assertIn('("active", "=", True)', code)

    def test_empty_models_are_skipped(self):
        # Un modèle sans ligne n'a rien à cacher ; le signaler noierait la
        # vraie trouvaille.
        self.assertIn("if not total:", check.build_script())

    def test_it_stops_at_the_first_user_who_sees_something(self):
        # Sans court-circuit, le coût est modèles × utilisateurs sur une
        # base où presque tout est visible.
        self.assertIn("break", check.build_script())

    def test_the_user_limit_is_honoured(self):
        code = check.build_script(limite=7)
        self.assertIn("LIMITE = 7", code)
        self.assertIn("limit=LIMITE", code)

    def test_technical_models_are_excluded_by_name(self):
        code = check.build_script()
        for nom in ("ir.rule", "ir.model.access"):
            self.assertIn(nom, code)

    def test_the_exclusion_list_never_swallows_business_models(self):
        # Une exclusion trop large rendrait le test muet sans le dire.
        for nom in check.ATTENDUS:
            self.assertTrue(
                nom.startswith(("ir.", "bus.", "res.users.log", "mail.")),
                f"exclusion suspecte : {nom}",
            )

    def test_it_reuses_the_shared_sentinels(self):
        from script.odoo.migration import database_cleanup

        self.assertEqual(check.DEBUT, database_cleanup.START)
        self.assertEqual(check.FIN, database_cleanup.END)


class TestTheReport(unittest.TestCase):
    def test_a_clean_database_says_so(self):
        texte = "\n".join(
            check.render({"models": [], "checked": 85, "users": ["a", "b"]})
        )
        self.assertIn(
            todo_i18n.t("Every one of them is visible to someone."), texte
        )

    def test_a_finding_names_the_model_and_the_volume(self):
        rapport = {
            "models": [
                {"model": "dms.file", "rows": 69},
                {"model": "dms.directory", "rows": 16},
            ],
            "checked": 85,
            "users": ["a"],
        }
        texte = "\n".join(check.render(rapport))
        self.assertIn("dms.file", texte)
        self.assertIn("69", texte)
        self.assertIn(
            todo_i18n.t("The data is there; a global rule hides all of it."),
            texte,
        )

    def test_the_biggest_loss_comes_first(self):
        rapport = {
            "models": [
                {"model": "aaa.petit", "rows": 3},
                {"model": "zzz.gros", "rows": 900},
            ],
            "checked": 2,
            "users": ["a"],
        }
        texte = "\n".join(check.render(rapport))
        self.assertLess(texte.index("zzz.gros"), texte.index("aaa.petit"))

    def test_no_internal_user_is_flagged_not_called_clean(self):
        # Sans utilisateur, on ne SAIT pas. Dire « tout va bien » serait
        # un mensonge tranquille.
        texte = "\n".join(check.render({"no_user": True}))
        self.assertIn(
            todo_i18n.t("No internal user to test visibility with."), texte
        )
        self.assertNotIn(
            todo_i18n.t("Every one of them is visible to someone."), texte
        )

    def test_every_translation_key_exists(self):
        with io.open(check.__file__, encoding="utf-8") as handle:
            src = handle.read()
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                cle = node.args[0].value
                self.assertTrue(
                    cle in todo_i18n.TRANSLATIONS,
                    f"clé sans traduction : {cle!r}",
                )


class TestTheExitCodes(unittest.TestCase):
    def setUp(self):
        from script.odoo.migration import database_cleanup

        self.cleanup = database_cleanup
        self.vraie = database_cleanup.require_matching_version
        self.vrai_shell = database_cleanup.run_shell
        database_cleanup.require_matching_version = lambda base: None

    def tearDown(self):
        self.cleanup.require_matching_version = self.vraie
        self.cleanup.run_shell = self.vrai_shell

    def lance(self, rapport):
        self.cleanup.run_shell = lambda *a, **k: rapport
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = check.main(["-d", "db"])
        return code, tampon.getvalue()

    def test_nothing_hidden_exits_zero(self):
        code, _ = self.lance({"models": [], "checked": 3, "users": ["a"]})
        self.assertEqual(code, 0)

    def test_something_hidden_exits_one(self):
        code, _ = self.lance(
            {
                "models": [{"model": "dms.file", "rows": 69}],
                "checked": 3,
                "users": ["a"],
            }
        )
        self.assertEqual(code, 1)

    def test_a_shell_error_exits_two(self):
        # 2 dit « l'outil a échoué », pas « rien trouvé » : les confondre
        # ferait conclure qu'une migration est saine sans l'avoir vérifiée.
        code, _ = self.lance({"error": "boom"})
        self.assertEqual(code, 2)

    def test_a_version_mismatch_stops_before_opening_the_database(self):
        self.cleanup.require_matching_version = lambda base: "18.0 vs 12.0"
        appels = []
        self.cleanup.run_shell = lambda *a, **k: appels.append(a) or {}
        with redirect_stdout(io.StringIO()):
            code = check.main(["-d", "db"])
        self.assertEqual(code, 2)
        self.assertEqual(appels, [])


class TestTheWiring(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self):
        with io.open(
            os.path.join(self.RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ) as handle:
            return handle.read()

    def test_the_detector_runs_at_every_bump(self):
        src = self.source()
        self.assertIn("check_hidden_models.py", src)

    def test_the_dms_repair_runs_at_the_13_bump_only(self):
        # MuK devient OCA DMS à ce palier-là et à aucun autre. Le lancer
        # partout coûterait un démarrage d'Odoo par palier pour rien.
        src = self.source()
        self.assertIn(
            "if next_version == 13:", src, "le garde de palier a disparu"
        )
        debut = src.index("if next_version == 13:")
        fin = src.index("dms_access_repair.py")
        self.assertLess(debut, fin)
        self.assertLess(fin - debut, 700, "le garde de palier s'est éloigné")

    def test_the_repair_is_applied_not_only_reported(self):
        # Sans --apply il n'écrit rien : câblé sans, il ne réparerait
        # jamais et la migration resterait cassée en silence.
        src = self.source()
        debut = src.index("dms_access_repair.py")
        self.assertIn("--apply", src[debut : debut + 200])


if __name__ == "__main__":
    unittest.main()
