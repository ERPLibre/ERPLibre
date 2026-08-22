#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une vue dont le `type` stocké contredit son héritage.

Deux propriétés portent l'outil. La première : il travaille en SQL, sans
l'ORM — le registre ne charge plus, et c'est justement ce qu'on répare.
La seconde : il ne corrige QUE ce qu'Odoo lui-même déclare faux — une
vue héritée prend le type de son ancêtre, règle citée dans `create`.
Vérifié sur une installation neuve et quatre bases migrées : zéro écart.
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

from script.odoo.migration import fix_view_type as fvt  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def vue(vid=637, actuel="tree", attendu="search", xmlid="event.x"):
    return {
        "id": vid,
        "type": actuel,
        "expected": attendu,
        "mode": "primary",
        "xmlid": xmlid,
        "model": "event.registration",
    }


class TestTheDetectionQuery(unittest.TestCase):
    def test_it_only_looks_at_inherited_views(self):
        # Une vue racine tient son type de sa balise : la comparer à
        # elle-même n'apprendrait rien.
        self.assertIn("v.inherit_id IS NOT NULL", fvt.DETECTION)

    def test_it_compares_against_the_ROOT_ancestor(self):
        # Pas le parent direct : une chaîne de trois vues doit remonter
        # jusqu'à celle qui porte la balise.
        self.assertIn("WITH RECURSIVE", fvt.DETECTION)
        self.assertIn("v.type <> r.type", fvt.DETECTION)

    def test_the_recursion_is_bounded(self):
        # Un `inherit_id` circulaire ferait tourner PostgreSQL sans fin.
        self.assertIn(f"r.prof < {fvt.PROFONDEUR_MAX}", fvt.DETECTION)
        self.assertGreater(fvt.PROFONDEUR_MAX, 5)

    def test_it_never_writes(self):
        for mot in ("UPDATE", "DELETE", "INSERT", "DROP"):
            self.assertNotIn(mot, fvt.DETECTION.upper().replace("UPDATED", ""))


class TestTheRepairSql(unittest.TestCase):
    def test_it_sets_each_view_to_its_ancestor_type(self):
        sql = fvt.repair_sql([vue(637, "tree", "search")])
        self.assertIn("WHEN 637 THEN 'search'", sql)
        self.assertIn("WHERE id IN (637)", sql)

    def test_several_views_travel_in_ONE_statement(self):
        # Une seule instruction, donc une seule transaction : couper au
        # milieu ne laisse pas une base à moitié réparée.
        sql = fvt.repair_sql(
            [vue(1, "tree", "search"), vue(2, "form", "kanban")]
        )
        self.assertEqual(sql.count("UPDATE"), 1)
        self.assertIn("WHEN 1 THEN 'search'", sql)
        self.assertIn("WHEN 2 THEN 'kanban'", sql)

    def test_nothing_to_fix_gives_no_sql(self):
        self.assertEqual(fvt.repair_sql([]), "")

    def test_it_targets_the_id_never_a_rebuilt_domain(self):
        sql = fvt.repair_sql([vue()])
        self.assertNotIn("inherit_id", sql)
        self.assertNotIn("arch_db", sql)
        self.assertNotIn("arch =", sql)
        self.assertEqual(sql.count("SET "), 1)
        self.assertIn("SET type =", sql)


class TestTheReport(unittest.TestCase):
    def test_a_clean_database_says_so(self):
        texte = "\n".join(fvt.render([]))
        self.assertIn(
            todo_i18n.t("Every view type agrees with its inheritance."), texte
        )

    def test_a_finding_names_the_view_and_both_types(self):
        texte = "\n".join(fvt.render([vue(637, "tree", "search")]))
        self.assertIn("637", texte)
        self.assertIn("tree → search", texte)
        self.assertIn("event.x", texte)

    def test_it_says_no_module_update_will_help(self):
        # C'est le renseignement qui évite de perdre une heure à
        # relancer `-u module` en boucle.
        texte = "\n".join(fvt.render([vue()]))
        self.assertIn(
            todo_i18n.t(
                "No module update will fix this: the type is set once,"
            ),
            texte,
        )

    def test_an_applied_run_does_not_repeat_the_advice(self):
        texte = "\n".join(fvt.render([vue()], applique=True))
        self.assertIn(todo_i18n.t("Corrected."), texte)
        self.assertNotIn(
            todo_i18n.t("at creation. Re-run with --apply."), texte
        )


class TestTheExitCodes(unittest.TestCase):
    def setUp(self):
        self.vrai = fvt.run_psql
        self.ecritures = []

    def tearDown(self):
        fvt.run_psql = self.vrai

    def branche(self, avant, apres=None):
        """`avant` puis `apres` : ce que la détection rend, avant/après."""
        etat = {"tour": 0}

        def faux(database, sql, read_only=True):
            if not read_only:
                self.ecritures.append(sql)
                return []
            etat["tour"] += 1
            lot = avant if etat["tour"] == 1 or apres is None else apres
            if lot is None:
                return None
            return [
                [
                    str(v["id"]),
                    v["type"],
                    v["expected"],
                    v["mode"],
                    v["xmlid"],
                    v["model"],
                ]
                for v in lot
            ]

        fvt.run_psql = faux

    def lance(self, argv):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = fvt.main(argv)
        return code, tampon.getvalue()

    def test_nothing_wrong_exits_zero(self):
        self.branche([])
        code, _ = self.lance(["-d", "db"])
        self.assertEqual(code, 0)
        self.assertEqual(self.ecritures, [])

    def test_a_finding_exits_one_and_writes_nothing(self):
        # Sans --apply, l'outil DIAGNOSTIQUE. Réparer tout seul serait un
        # piège dans un outil qu'on lance pour comprendre.
        self.branche([vue()])
        code, _ = self.lance(["-d", "db"])
        self.assertEqual(code, 1)
        self.assertEqual(self.ecritures, [])

    def test_apply_fixes_and_exits_zero(self):
        self.branche([vue()], apres=[])
        code, sortie = self.lance(["-d", "db", "--apply"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.ecritures), 1)
        self.assertIn(todo_i18n.t("Corrected."), sortie)

    def test_a_correction_that_did_not_take_exits_two(self):
        # Relire APRÈS : annoncer « corrigé » sans vérifier ferait
        # relancer la migration sur le même mur.
        self.branche([vue()], apres=[vue()])
        code, _ = self.lance(["-d", "db", "--apply"])
        self.assertEqual(code, 2)

    def test_an_unreadable_database_exits_two(self):
        self.branche(None)
        code, _ = self.lance(["-d", "db"])
        self.assertEqual(code, 2)


class TestTheWiring(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self):
        with io.open(
            os.path.join(self.RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ) as handle:
            return handle.read()

    def test_the_error_menu_offers_the_entry(self):
        src = self.source()
        self.assertIn("Fix views whose type contradicts their", src)
        self.assertIn('if wait_status == "5" and database_name:', src)
        self.assertIn("def prompt_fix_view_type", src)

    def test_it_runs_the_tool_twice_report_then_apply(self):
        src = self.source()
        debut = src.index("def prompt_fix_view_type")
        fin = src.index("def prompt_purge_dead_attachments")
        bloc = src[debut:fin]
        self.assertEqual(bloc.count("fix_view_type.py"), 1)
        self.assertIn("--apply", bloc)

    def test_only_a_finding_leads_to_the_question(self):
        # 0 « rien à corriger » et 2 « l'outil a échoué » ne justifient
        # ni la question ni le rejeu de la commande.
        src = self.source()
        debut = src.index("def prompt_fix_view_type")
        fin = src.index("def prompt_purge_dead_attachments")
        self.assertIn("if status != 1:", src[debut:fin])

    def test_every_menu_entry_has_its_branch(self):
        src = self.source()
        debut = src.index("def _prompt_on_error")
        fin = src.index("def prompt_fix_view_type")
        bloc = src[debut:fin]
        for rang in ("1", "2", "3", "4", "5"):
            self.assertTrue(
                f'f"[{rang}] ' in bloc, f"entrée [{rang}] absente du menu"
            )
        for rang in ("2", "3", "4", "5"):
            self.assertTrue(
                f'wait_status == "{rang}"' in bloc,
                f"aiguillage [{rang}] absent",
            )


class TestTheToolIsCalledWithTheRightContract(unittest.TestCase):
    """Pour cet outil, 1 veut dire « trouvailles », pas « échec ».

    `todo_upgrade_execute` ouvre SON menu d'erreur sur tout statut non
    nul. Sans `wait_at_error=False`, ce menu se superpose au nôtre : la
    question « Les corriger ? » n'est jamais posée, et l'on tourne en
    rond. C'est arrivé en vrai, sur une migration bloquée.
    """

    def setUp(self):
        from script.todo import auto_ask
        from script.todo.todo_upgrade import TodoUpgrade

        self.auto_ask = auto_ask
        self.vrai_ask = auto_ask.ask
        self.obj = TodoUpgrade.__new__(TodoUpgrade)
        self.appels = []

        def faux(cmd, **kw):
            self.appels.append((cmd, kw))
            statut = 0 if "--apply" in cmd else 1
            if statut and kw.get("wait_at_error", True):
                # Ce que fait le VRAI : il n'en revient pas avec le
                # statut, il repart dans son propre menu.
                raise AssertionError(
                    "menu d'erreur imbriqué : wait_at_error manquant"
                )
            return statut, cmd

        self.obj.todo_upgrade_execute = faux
        self.obj.ask = lambda prompt, default="": "y"

    def tearDown(self):
        self.auto_ask.ask = self.vrai_ask

    def test_the_report_call_does_not_reopen_the_error_menu(self):
        with redirect_stdout(io.StringIO()):
            self.obj.prompt_fix_view_type("db")
        self.assertTrue(self.appels)
        self.assertIs(self.appels[0][1].get("wait_at_error"), False)

    def test_the_apply_call_does_not_either(self):
        with redirect_stdout(io.StringIO()):
            self.obj.prompt_fix_view_type("db")
        self.assertEqual(len(self.appels), 2)
        self.assertIn("--apply", self.appels[1][0])
        self.assertIs(self.appels[1][1].get("wait_at_error"), False)

    def test_it_returns_true_only_when_the_apply_succeeded(self):
        with redirect_stdout(io.StringIO()):
            self.assertTrue(self.obj.prompt_fix_view_type("db"))

    def test_refusing_runs_no_apply(self):
        self.obj.ask = lambda prompt, default="": "n"
        with redirect_stdout(io.StringIO()):
            self.assertFalse(self.obj.prompt_fix_view_type("db"))
        self.assertEqual(len(self.appels), 1)

    def test_nothing_to_fix_asks_nothing(self):
        demandes = []
        self.obj.ask = (
            lambda prompt, default="": demandes.append(prompt) or "y"
        )
        self.obj.todo_upgrade_execute = lambda cmd, **kw: (0, cmd)
        with redirect_stdout(io.StringIO()):
            self.assertFalse(self.obj.prompt_fix_view_type("db"))
        self.assertEqual(demandes, [])


class TestTranslations(unittest.TestCase):
    def test_every_key_exists(self):
        with io.open(fvt.__file__, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        for node in ast.walk(arbre):
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


if __name__ == "__main__":
    unittest.main()
