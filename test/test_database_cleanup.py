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
    """Volontairement SANS `savepoint` : c'est l'invariant du correctif.

    Le module OCA valide de lui-même — `purge_modules.find()` purge (ligne
    91) et `purge_columns.purge()` appelle `cr.commit()` (ligne 57). Un
    COMMIT détruit tous les points de reprise. En reprendre un ici ferait
    revivre le défaut sans que rien ne le dise ; l'absence de la méthode
    le fait échouer tout de suite.
    """

    def __init__(self, journal):
        self.journal = journal

    def commit(self):
        self.journal.append(("commit", None))

    def rollback(self):
        self.journal.append(("rollback", None))


class AbortingCursor(FakeCursor):
    """Ce que PostgreSQL fait VRAIMENT après une erreur.

    La transaction reste avortée et refuse tout ordre jusqu'au rollback.
    C'est ce qui changeait une panne sur « modules » en sept catégories
    mortes, toutes sur « current transaction is aborted ».
    """

    def __init__(self, journal):
        super().__init__(journal)
        self.aborted = False

    def commit(self):
        if self.aborted:
            raise RuntimeError(
                "current transaction is aborted, commands ignored"
                " until end of transaction block"
            )
        super().commit()

    def rollback(self):
        super().rollback()
        self.aborted = False


class CommittingLine(FakeLine):
    """Une purge qui valide toute seule, comme `purge_columns` le fait.

    Le COMMIT emporte le point de reprise ; l'ordre suivant meurt sur
    « savepoint ... does not exist » et laisse la transaction avortée.
    """

    def __init__(self, name, cursor, journal=None):
        super().__init__(name, journal=journal)
        self.cursor = cursor

    def purge(self):
        self.journal.append(("purge", self.name))
        self.cursor.commit()
        self.cursor.aborted = True
        raise RuntimeError('savepoint "10eb69719a9211f1" does not exist')


class FakeEnv(dict):
    def __init__(self, mapping, journal, cursor=None):
        super().__init__(mapping)
        self.cr = cursor if cursor is not None else FakeCursor(journal)


class UserError(Exception):
    """Celle que le script poussé importera : on fournit odoo.exceptions.

    Refaire une classe de son côté ne servirait à rien — « except » compare
    des identités, pas des noms, et le test passerait à côté.
    """


def install_fake_odoo_exceptions(case):
    """Rendre `from odoo.exceptions import UserError` possible ici."""
    import types

    odoo = sys.modules.get("odoo") or types.ModuleType("odoo")
    exceptions = types.ModuleType("odoo.exceptions")
    exceptions.UserError = UserError
    avant_odoo = sys.modules.get("odoo")
    avant_exc = sys.modules.get("odoo.exceptions")
    sys.modules["odoo"] = odoo
    sys.modules["odoo.exceptions"] = exceptions

    def remettre():
        for nom, valeur in (
            ("odoo", avant_odoo),
            ("odoo.exceptions", avant_exc),
        ):
            if valeur is None:
                sys.modules.pop(nom, None)
            else:
                sys.modules[nom] = valeur

    case.addCleanup(remettre)


def run_script(models, max_round=10, dry_run=False, cursor=None):
    """Exécuter le script réellement poussé, et rendre (rapport, journal)."""
    import json

    journal = cursor.journal if cursor is not None else []
    env = FakeEnv(models, journal, cursor=cursor)
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
    def test_each_entry_is_committed_on_its_own(self):
        # Sans cela, le premier refus emporterait tout ce que la passe avait
        # déjà réparé — et un rollback, ici, remonte jusqu'au début.
        journal = []
        lines = [
            FakeLine("a", journal=journal),
            FakeLine("b", journal=journal),
        ]
        models = {cleanup.ORDER[0][1]: FakeModel(lines)}
        _report, got = run_script(models, max_round=1)
        # Une validation par entrée, PLUS une après la création : `find()`
        # peut avoir purgé de lui-même, et ce travail-là doit tenir.
        self.assertEqual(got.count(("commit", None)), 3)

    def test_a_refusal_gives_up_only_its_own(self):
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
        self.assertEqual(got.count(("rollback", None)), 1)
        # Deux entrées purgées + la création : trois validations.
        self.assertEqual(got.count(("commit", None)), 3)

    def test_the_script_never_takes_a_savepoint(self):
        # L'invariant du correctif, dit une fois pour toutes : le module OCA
        # valide de lui-même, et un COMMIT détruit le point de reprise
        # qu'on aurait pris. Le reprendre serait revenir au défaut.
        self.assertNotIn("env.cr.savepoint", cleanup.build_script(1, False))

    def test_a_wizard_that_cannot_even_be_created_is_recorded(self):
        models = {cleanup.ORDER[0][1]: FakeModel([], raise_on_create="boom")}
        report, _got = run_script(models, max_round=1)
        self.assertEqual(report["failed"][0][0], "models")
        self.assertIn("boom", report["failed"][0][2])


class TestTheReportSurvivesAnything(unittest.TestCase):
    """Sans rapport, on ne sait même pas si la base a été touchée.

    Vécu : `create({})` échouait, l'erreur était notée mais la transaction
    restait AVORTÉE. La lecture de nom suivante mourait dessus, hors de tout
    garde, et le script entier s'arrêtait — aucun rapport, juste une trace.
    """

    def test_reading_the_names_is_inside_the_guard(self):
        # C'est la lecture des noms qui déclenche la requête, pas la
        # création : la laisser hors du `try` était le défaut — elle mourait
        # sur une transaction déjà avortée, sans rien pour la rattraper.
        source = cleanup.build_script(1, False)
        creation = source.index("wizard = env[model].create({})")
        garde = source.rindex("try:", 0, creation)
        noms = source.index("line.name or str(line.id)")
        rattrapage = source.index("except UserError:", noms)
        self.assertLess(garde, creation)
        self.assertLess(creation, noms)
        self.assertLess(noms, rattrapage)

    def test_a_failure_on_create_does_not_kill_the_run(self):
        models = {
            cleanup.ORDER[0][1]: FakeModel([], raise_on_create="boom"),
            cleanup.ORDER[2][1]: FakeModel([FakeLine("colonne")]),
        }
        report, _got = run_script(models, max_round=1)
        # La catégorie suivante a bien travaillé malgré l'échec de la
        # première.
        purged = {e["kind"]: e["purged"] for e in report["rounds"][0]}
        self.assertEqual(purged.get("columns"), 1)
        self.assertEqual(report["failed"][0][0], "models")

    def test_an_unexpected_failure_still_yields_a_report(self):
        class Explosive(dict):
            def __init__(self, journal):
                super().__init__()
                self.cr = FakeCursor(journal)

            def __contains__(self, key):
                raise RuntimeError("registre en miettes")

        import json as _json

        journal = []
        namespace = {"env": Explosive(journal)}
        exec(cleanup.build_script(1, False), namespace)  # noqa: S102
        report = _json.loads(_json.dumps(namespace["report"]))
        self.assertEqual(report["failed"][0][:2], ["*", "fatal"])
        self.assertIn("miettes", report["failed"][0][2])


class TestTheCascadeThatKilledEverything(unittest.TestCase):
    """Vécu, sur test_neutralize_upgrade_13 : sept catégories mortes d'une.

       passe 1 : 0 purgés
    ⚠️ 0 purgés ; 7 n'ont pas pu l'être :
       - [modules] - : savepoint "10eb6971..." does not exist
       - [columns] - : current transaction is aborted, commands ignored
       ... et ainsi de suite jusqu'à la dernière.

    Une seule panne, six victimes. La cause n'était pas dans OCA mais chez
    nous : on n'a jamais remis la transaction d'aplomb après l'échec.
    """

    def build(self):
        journal = []
        cursor = AbortingCursor(journal)
        coupable = CommittingLine("colonne_morte", cursor, journal=journal)
        models = {
            cleanup.ORDER[1][1]: FakeModel([coupable]),
            cleanup.ORDER[2][1]: FakeModel(
                [FakeLine("suivante", journal=journal)]
            ),
            cleanup.ORDER[3][1]: FakeModel(
                [FakeLine("encore", journal=journal)]
            ),
        }
        return run_script(models, max_round=1, cursor=cursor)

    def test_the_categories_after_it_still_work(self):
        report, _got = self.build()
        purged = {e["kind"]: e["purged"] for e in report["rounds"][0]}
        self.assertEqual(purged.get("columns"), 1)
        self.assertEqual(purged.get("tables"), 1)

    def test_nobody_else_reports_an_aborted_transaction(self):
        # C'est la SIGNATURE de la cascade : six lignes qui ne disent rien
        # de leur propre catégorie, seulement qu'une autre a échoué avant.
        report, _got = self.build()
        contamines = [
            entry
            for round_ in report["rounds"]
            for entry in round_
            for _name, message in entry["errors"]
            if "transaction is aborted" in message
        ]
        self.assertEqual(contamines, [])
        self.assertEqual(report["failed"], [])

    def test_the_real_failure_is_still_reported(self):
        # Rattraper ne veut pas dire taire : la colonne n'a PAS été purgée.
        report, _got = self.build()
        entry = [e for e in report["rounds"][0] if e["kind"] == "modules"][0]
        self.assertEqual(entry["purged"], 0)
        self.assertIn("savepoint", entry["errors"][0][1])

    def test_the_transaction_is_put_back_on_its_feet(self):
        _report, got = self.build()
        self.assertIn(("rollback", None), got)


class TestADeadCreateDoesNotContaminate(unittest.TestCase):
    def test_the_next_category_is_not_dragged_down(self):
        # `create({})` qui échoue laisse la transaction avortée : sans
        # rollback, la catégorie suivante mourait sur l'erreur d'une autre.
        journal = []
        cursor = AbortingCursor(journal)

        class MortAuDepart(FakeModel):
            def create(self, values):
                cursor.aborted = True
                raise RuntimeError("registre indisponible")

        models = {
            cleanup.ORDER[0][1]: MortAuDepart([]),
            cleanup.ORDER[2][1]: FakeModel(
                [FakeLine("colonne", journal=journal)]
            ),
        }
        report, _got = run_script(models, max_round=1, cursor=cursor)
        purged = {e["kind"]: e["purged"] for e in report["rounds"][0]}
        self.assertEqual(purged.get("columns"), 1)
        self.assertEqual(report["failed"][0][0], "models")
        self.assertIn("registre", report["failed"][0][2])


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

    def test_it_undoes_what_merely_looking_caused(self):
        # `purge_modules.find()` PURGE de lui-même : une simulation écrivait
        # donc pour de bon, ce qui lui retire tout son sens. On défait ce
        # que la lecture a provoqué — possible ici, justement parce qu'on
        # n'a validé aucune entrée.
        journal = []
        models = {
            cleanup.ORDER[0][1]: FakeModel([FakeLine("a", journal=journal)])
        }
        _report, got = run_script(models, max_round=5, dry_run=True)
        self.assertIn(("rollback", None), got)
        self.assertNotIn(("commit", None), got)

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


class TestNothingToPurgeIsNotAFailure(unittest.TestCase):
    """Le module signale le VIDE par une exception.

    `raise UserError("No orphaned models found")` : le compter comme un
    échec faisait passer une base saine pour une base cassée, avec quatre
    avertissements sur cinq catégories.
    """

    def test_the_pushed_script_separates_it(self):
        source = cleanup.build_script(1, False)
        self.assertIn("except UserError:", source)
        vide = source.index("except UserError:")
        echec = source.index('note(label, "-", exc)')
        self.assertLess(vide, echec, "l'ordre des except décide")

    def test_it_is_reported_as_zero_not_as_an_error(self):
        install_fake_odoo_exceptions(self)

        class Empty(FakeModel):
            def create(self, values):
                raise UserError("No orphaned models found")

        models = {cleanup.ORDER[0][1]: Empty([])}
        report, _got = run_script(models, max_round=1)
        entry = report["rounds"][0][0]
        self.assertEqual(entry["purged"], 0)
        self.assertEqual(entry["errors"], [])
        self.assertEqual(report["failed"], [])


class TestTheModuleIsInstalledFirst(unittest.TestCase):
    """Sans le module, aucun assistant n'existe et l'outil dit « rien ».

    Ce silence se lit comme un succès. La migration l'installait à l'étape
    3, donc APRÈS le nettoyage de l'étape 2 : l'ordre rendait l'outil
    inutile au premier passage.
    """

    def test_it_checks_the_state_before_cleaning(self):
        import inspect

        source = inspect.getsource(cleanup.main)
        self.assertIn("module_state(", source)
        self.assertLess(
            source.index("module_state("), source.index("run_shell(")
        )

    def test_it_installs_when_absent(self):
        import inspect

        source = inspect.getsource(cleanup.main)
        self.assertIn('state != "installed"', source)
        self.assertIn("install_module(", source)

    def test_a_failed_install_stops_there(self):
        # Nettoyer sans le module rendrait « rien à faire » sur une base qui
        # en avait besoin.
        import inspect

        source = inspect.getsource(cleanup.main)
        install = source.index("install_module(")
        self.assertIn("return 2", source[install : install + 400])


class TestTheMigrationNoLongerAsksTwice(unittest.TestCase):
    def test_the_manual_cleanup_prompt_is_gone(self):
        # Le faire à la main après l'avoir fait automatiquement.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertNotIn("Did you finish to clean database", source)
        self.assertNotIn("Go to Settings / Technical / Cleanup", source)

    def test_the_late_install_is_gone_too(self):
        # Elle arrivait à l'étape 3, après l'usage de l'étape 2 : l'outil
        # pose désormais le module lui-même, au bon moment.
        import inspect

        from script.todo.todo_upgrade import TodoUpgrade

        source = inspect.getsource(TodoUpgrade.execute_odoo_upgrade)
        self.assertNotIn(
            "install_addons.sh {database_name} database_cleanup", source
        )


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
