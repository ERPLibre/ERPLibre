#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le nettoyage OCA, en ordre, jusqu'à ce que plus rien ne bouge.

Les huit purges ne sont pas indépendantes : purger un modèle libère les
colonnes qui le référençaient, purger une table libère les données qui la
visaient. Une seule passe ne suffit jamais, et l'ordre compte.

Les erreurs sont ATTENDUES — une clé étrangère tient encore, un module
refuse. Purger la liste d'un bloc perdrait tout au premier refus : chaque
entrée passe donc dans son propre point de reprise. Ce que la passe n'a pas
réparé, la suivante le peut, une fois les voisines parties.

Ces tests exécutent le script réellement poussé dans le shell, sur un `env`
simulé. C'est la seule façon de vérifier l'ordre, l'isolement des refus et
l'arrêt de la boucle sans lancer Odoo sur une vraie base.
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))

import database_cleanup as cleanup  # noqa: E402


class FakeLine:
    def __init__(self, name, fails=0, journal=None):
        self.name = name
        self.id = abs(hash(name)) % 10000
        self.fails = fails  # nombre de refus avant de céder
        self.journal = journal if journal is not None else []

    def purge(self):
        self.journal.append(("purge", self.name))
        if self.fails > 0:
            self.fails -= 1
            raise RuntimeError(f"refus sur {self.name}")


class FakeWizard:
    def __init__(self, lines):
        self.purge_line_ids = lines


class FakeModel:
    def __init__(self, lines, raise_on_create=None):
        self._lines = lines
        self._raise = raise_on_create

    def create(self, values):
        if self._raise:
            raise RuntimeError(self._raise)
        # Les lignes déjà purgées ne reviennent pas : find() les recalcule.
        return FakeWizard([ln for ln in self._lines if ln.fails >= 0])


class FakeCursor:
    def __init__(self, journal):
        self.journal = journal

    def savepoint(self):
        journal = self.journal

        class Guard:
            def __enter__(self_inner):
                journal.append(("savepoint", "enter"))
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                journal.append(
                    ("savepoint", "rollback" if exc_type else "release")
                )
                return False

        return Guard()

    def commit(self):
        self.journal.append(("commit", None))


class FakeEnv(dict):
    def __init__(self, mapping, journal):
        super().__init__(mapping)
        self.cr = FakeCursor(journal)


def run_script(models, max_round=10, dry_run=False):
    """Exécuter le script réellement poussé, et rendre (rapport, journal)."""
    import json

    journal = []
    env = FakeEnv(models, journal)
    namespace = {"env": env}
    exec(cleanup.build_script(max_round, dry_run), namespace)  # noqa: S102
    # Le script imprime le rapport entre deux sentinelles ; ici on le relit
    # dans son espace de noms, ce qui teste la MÊME structure.
    return json.loads(json.dumps(namespace["report"])), journal


class TestTheOrder(unittest.TestCase):
    def test_the_requested_order_is_kept(self):
        # Purger un modèle libère des colonnes : l'inverse ne marcherait pas.
        self.assertEqual(
            [kind for kind, _model in cleanup.ORDER],
            [
                "models",
                "modules",
                "columns",
                "tables",
                "data",
                "menus",
                "indexes",
                "properties",
            ],
        )

    def test_indexes_come_after_the_purges(self):
        kinds = [kind for kind, _ in cleanup.ORDER]
        self.assertGreater(kinds.index("indexes"), kinds.index("tables"))

    def test_a_pass_visits_the_kinds_in_that_order(self):
        models = {
            model: FakeModel([FakeLine(f"{kind}-1")])
            for kind, model in cleanup.ORDER
        }
        report, _journal = run_script(models, max_round=1)
        self.assertEqual(
            [entry["kind"] for entry in report["rounds"][0]],
            [kind for kind, _ in cleanup.ORDER],
        )


class TestOneEntryCannotSinkThePass(unittest.TestCase):
    def test_each_entry_gets_its_own_savepoint(self):
        # Sans cela, le premier refus emporterait tout ce que la passe avait
        # déjà réparé.
        journal = []
        lines = [
            FakeLine("a", journal=journal),
            FakeLine("b", journal=journal),
        ]
        models = {cleanup.ORDER[0][1]: FakeModel(lines)}
        _report, got = run_script(models, max_round=1)
        self.assertEqual(got.count(("savepoint", "enter")), 2)

    def test_a_refusal_rolls_back_only_its_own(self):
        journal = []
        lines = [
            FakeLine("ok1", journal=journal),
            FakeLine("bad", fails=99, journal=journal),
            FakeLine("ok2", journal=journal),
        ]
        models = {cleanup.ORDER[0][1]: FakeModel(lines)}
        report, got = run_script(models, max_round=1)
        entry = report["rounds"][0][0]
        self.assertEqual(entry["purged"], 2)
        self.assertEqual([name for name, _msg in entry["errors"]], ["bad"])
        self.assertEqual(got.count(("savepoint", "rollback")), 1)
        self.assertEqual(got.count(("savepoint", "release")), 2)

    def test_a_wizard_that_cannot_even_be_created_is_recorded(self):
        models = {cleanup.ORDER[0][1]: FakeModel([], raise_on_create="boom")}
        report, _got = run_script(models, max_round=1)
        self.assertEqual(report["failed"][0][0], "models")
        self.assertIn("boom", report["failed"][0][2])


class TestGoingRoundAgain(unittest.TestCase):
    def test_what_one_pass_refused_the_next_may_take(self):
        # LE point, et la raison même de boucler : une entrée refuse TANT QUE
        # sa voisine est là. Une ligne qui guérirait toute seule n'existe pas
        # — ce qui existe, c'est une dépendance qui tombe.
        etat = {"table_partie": False}

        class Dependante(FakeLine):
            def purge(self):
                if not etat["table_partie"]:
                    raise RuntimeError("la table la retient encore")
                self.fails = -1

        class Liberatrice(FakeLine):
            def purge(self):
                etat["table_partie"] = True
                self.fails = -1

        modele_col, modele_tab = cleanup.ORDER[2][1], cleanup.ORDER[3][1]
        models = {
            modele_col: FakeModel([Dependante("colonne_liee")]),
            modele_tab: FakeModel([Liberatrice("vieille_table")]),
        }
        report, _got = run_script(models, max_round=5)
        # Passe 1 : la colonne refuse, la table part → du progrès, on continue.
        self.assertEqual(report["rounds"][0][0]["purged"], 0)
        self.assertEqual(report["rounds"][0][1]["purged"], 1)
        # Passe 2 : la colonne cède, sa dépendance étant partie.
        self.assertEqual(report["rounds"][1][0]["purged"], 1)

    def test_a_pass_that_repairs_nothing_ends_it(self):
        # Rien n'a changé dans la base : une passe de plus rendrait le même
        # refus. Boucler serait des minutes brûlées pour rien.
        models = {
            cleanup.ORDER[0][1]: FakeModel([FakeLine("never", fails=99)])
        }
        report, _got = run_script(models, max_round=8)
        self.assertEqual(len(report["rounds"]), 1)
        self.assertEqual(len(report["rounds"][0][0]["errors"]), 1)

    def test_the_loop_stops_when_a_pass_repairs_nothing(self):
        # Ce qui résistait au tour d'avant résistera encore : boucler
        # jusqu'à max_round brûlerait des minutes pour rien.
        models = {
            cleanup.ORDER[0][1]: FakeModel([FakeLine("never", fails=99)])
        }
        report, _got = run_script(models, max_round=8)
        self.assertEqual(len(report["rounds"]), 1)

    def test_nothing_to_do_is_one_pass(self):
        models = {cleanup.ORDER[0][1]: FakeModel([])}
        report, _got = run_script(models, max_round=8)
        self.assertEqual(len(report["rounds"]), 1)


class TestWhatIsAbsentIsSkipped(unittest.TestCase):
    def test_a_missing_wizard_is_noted_not_fatal(self):
        # `property` n'existe plus en 18.0 : Odoo y a remplacé ir.property
        # par une colonne jsonb. Échouer dessus arrêterait le nettoyage sur
        # une version où il n'a plus lieu d'être.
        models = {cleanup.ORDER[0][1]: FakeModel([])}
        report, _got = run_script(models, max_round=1)
        self.assertIn("properties", report["missing"])
        self.assertIn("indexes", report["missing"])

    def test_a_kind_is_noted_once(self):
        models = {cleanup.ORDER[0][1]: FakeModel([FakeLine("x", fails=1)])}
        report, _got = run_script(models, max_round=5)
        self.assertEqual(report["missing"].count("properties"), 1)


class TestTheDryRun(unittest.TestCase):
    def test_it_purges_nothing(self):
        journal = []
        lines = [FakeLine("a", journal=journal)]
        models = {cleanup.ORDER[0][1]: FakeModel(lines)}
        report, got = run_script(models, max_round=5, dry_run=True)
        self.assertEqual(journal, [])
        self.assertNotIn(("commit", None), got)
        self.assertEqual(report["rounds"][0][0]["would"], ["a"])

    def test_it_does_a_single_pass(self):
        # Rien ne change, donc rien ne se libère : boucler serait du vent.
        models = {cleanup.ORDER[0][1]: FakeModel([FakeLine("a")])}
        report, _got = run_script(models, max_round=9, dry_run=True)
        self.assertEqual(len(report["rounds"]), 1)


class TestTheReport(unittest.TestCase):
    def setUp(self):
        from script.todo import todo_i18n

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_leftovers_are_a_warning_not_a_failure(self):
        report = {
            "rounds": [
                [
                    {
                        "kind": "models",
                        "purged": 3,
                        "errors": [["x", "held"]],
                        "would": [],
                    }
                ]
            ],
            "missing": [],
            "failed": [],
        }
        text = cleanup.render(report, "db")
        self.assertIn("⚠️", text)
        self.assertIn("not a failure", text)

    def test_all_clean_says_so(self):
        report = {
            "rounds": [
                [{"kind": "models", "purged": 3, "errors": [], "would": []}]
            ],
            "missing": [],
            "failed": [],
        }
        self.assertIn("✅", cleanup.render(report, "db"))

    def test_a_dry_run_is_not_read_as_refusals(self):
        # 586 candidats ne sont pas 586 refus : la première version les
        # affichait comme des échecs.
        report = {
            "rounds": [
                [
                    {
                        "kind": "columns",
                        "purged": 0,
                        "errors": [],
                        "would": ["a", "b"],
                    }
                ]
            ],
            "missing": [],
            "failed": [],
        }
        text = cleanup.render(report, "db")
        self.assertIn("would be purged", text)
        self.assertNotIn("⚠️", text)


class TestTheMigrationRunsItBeforeTheSmokeTest(unittest.TestCase):
    """Interroger les pages sur une base encombrée fait chercher à côté."""

    def source(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_it_runs_before_both_smoke_tests(self):
        source = self.source()
        self.assertEqual(source.count("prompt_database_cleanup"), 2)
        for _ in range(2):
            nettoyage = source.index("prompt_database_cleanup")
            mesure = source.index("prompt_smoke_public_url")
            self.assertLess(nettoyage, mesure)
            source = source[mesure + 1 :]

    def test_it_gets_a_real_terminal(self):
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.prompt_database_cleanup)
        self.assertIn("run_on_terminal", source)
        self.assertNotIn("todo_upgrade_execute", source)

    def test_the_default_cleans_nothing(self):
        # Cela ÉCRIT en base : ce n'est pas à la migration de le décider.
        import contextlib
        import io

        from script.todo import todo_i18n
        from script.todo.todo_upgrade import TodoUpgrade

        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        lst_cmd = []
        upgrade.run_on_terminal = lambda cmd: lst_cmd.append(cmd) or 0
        upgrade.ask_gate = lambda prompt: ""
        with contextlib.redirect_stdout(io.StringIO()):
            upgrade.prompt_database_cleanup("db")
        self.assertEqual(lst_cmd, [])

    def test_yes_runs_it_on_that_database(self):
        from script.todo.todo_upgrade import TodoUpgrade

        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {}
        upgrade.lst_command_executed = []
        upgrade.write_config = lambda: None
        lst_cmd = []
        upgrade.run_on_terminal = lambda cmd: lst_cmd.append(cmd) or 0
        upgrade.ask_gate = lambda prompt: "y"
        upgrade.prompt_database_cleanup("db_upgrade_18")
        self.assertEqual(len(lst_cmd), 1)
        self.assertIn("database_cleanup.py", lst_cmd[0])
        self.assertIn("-d db_upgrade_18", lst_cmd[0])


class TestItRefusesTheWrongOdooVersion(unittest.TestCase):
    """Un Odoo plus ancien sur une base plus récente ÉCRIT avant d'échouer."""

    def test_a_mismatch_is_refused(self):
        original_checkout = cleanup.checkout_version
        original_db = cleanup.database_version
        cleanup.checkout_version = lambda: "14.0"
        cleanup.database_version = lambda database: "17.0"
        self.addCleanup(
            setattr, cleanup, "checkout_version", original_checkout
        )
        self.addCleanup(setattr, cleanup, "database_version", original_db)
        message = cleanup.require_matching_version("db")
        self.assertIsNotNone(message)
        self.assertIn("14.0", message)
        self.assertIn("17.0", message)

    def test_a_match_passes(self):
        original_checkout = cleanup.checkout_version
        original_db = cleanup.database_version
        cleanup.checkout_version = lambda: "17.0"
        cleanup.database_version = lambda database: "17.0"
        self.addCleanup(
            setattr, cleanup, "checkout_version", original_checkout
        )
        self.addCleanup(setattr, cleanup, "database_version", original_db)
        self.assertIsNone(cleanup.require_matching_version("db"))

    def test_not_knowing_does_not_block(self):
        # Refuser sur une supposition empêcherait de nettoyer là où c'est
        # possible.
        original_checkout = cleanup.checkout_version
        cleanup.checkout_version = lambda: None
        self.addCleanup(
            setattr, cleanup, "checkout_version", original_checkout
        )
        self.assertIsNone(cleanup.require_matching_version("db"))


if __name__ == "__main__":
    unittest.main()
