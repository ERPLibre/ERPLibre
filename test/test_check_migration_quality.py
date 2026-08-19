#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'une migration gagne et ce qu'elle perd, palier par palier.

La question qu'on se pose après six paliers n'est pas « a-t-elle fini » —
le journal le dit — mais « qu'est-ce qui a changé en chemin ». Une
migration laisse une base PAR PALIER, et elles existent toutes encore : on
les compare côte à côte plutôt que de rejouer quoi que ce soit.

Le point le plus délicat est le rapprochement des tables renommées. Deux
garde-fous ont été essayés et rejetés SUR UNE VRAIE MIGRATION avant celui
qui tient, et un faux rapprochement ne serait pas une coquetterie : il
ferait DISPARAÎTRE une perte réelle du rapport. D'où la règle qui compte
plus que tout ici — une perte est toujours listée, jamais retirée.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "script", "analyse"))

from script.analyse import check_migration_quality as quality  # noqa: E402
from script.analyse import check_migration_quality_tui as qtui  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def snapshot(**override):
    etat = {
        "database": "db",
        "exists": True,
        "odoo": "13.0",
        "version": 13,
        "installed": ["account", "sale"],
        "module": {"account": "installed", "sale": "installed"},
        "model": ["account.move", "sale.order"],
        "table": {"account_move": 100, "sale_order": 20},
        "model_without_table": [],
        "view": 2000,
        "view_cow": 40,
        "menu": 400,
        "action": 300,
        "attachment": 5000,
        "attachment_stored": 4000,
        "attachment_missing": 0,
        "language": 2,
    }
    etat.update(override)
    return etat


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestFindingTheChain(Base):
    """Les bases se déduisent de ce que la migration a ÉCRIT.

    Le pilote nomme ses bases de palier « <base>_upgrade_<version> » et
    retient sa cible. Redemander ces noms serait redemander ce qu'on sait.
    """

    PROGRESSION = {
        "config_database_name": "test_neutralize",
        "target_odoo_version": "18.0",
        "state_4_upgrade_odoo_lst": [[], [], [], [], [], []],
    }

    def test_it_walks_from_the_start_to_the_target(self):
        lst = quality.chain(self.PROGRESSION)
        self.assertEqual(
            [version for version, _db in lst], [12, 13, 14, 15, 16, 17, 18]
        )

    def test_the_first_one_is_the_origin_database(self):
        # Le palier 12 n'a pas de base « _upgrade_12 » : c'est la base
        # d'origine, celle qu'on a restaurée.
        self.assertEqual(
            quality.chain(self.PROGRESSION)[0][1], "test_neutralize"
        )

    def test_the_others_follow_the_naming_of_the_driver(self):
        noms = [db for _v, db in quality.chain(self.PROGRESSION)]
        self.assertIn("test_neutralize_upgrade_13", noms)
        self.assertIn("test_neutralize_upgrade_18", noms)

    def test_a_migration_not_started_yields_the_origin_alone(self):
        lst = quality.chain(
            {"config_database_name": "db", "target_odoo_version": "18.0"}
        )
        self.assertEqual(lst, [(None, "db")])

    def test_no_progression_yields_nothing(self):
        self.assertEqual(quality.chain({}), [])


class TestWhatIsGainedAndLost(Base):
    def test_a_module_uninstalled_is_a_loss(self):
        diff = quality.compare(
            snapshot(installed=["account", "sale"]),
            snapshot(installed=["account"]),
        )
        self.assertEqual(diff["modules_lost"], ["sale"])
        self.assertEqual(diff["modules_gained"], [])

    def test_a_model_that_appears_is_a_gain(self):
        diff = quality.compare(
            snapshot(model=["account.move"]),
            snapshot(model=["account.move", "account.edi"]),
        )
        self.assertEqual(diff["models_gained"], ["account.edi"])

    def test_a_table_that_empties_is_reported(self):
        # LE signal : un module en moins se voit, une table qui passe de
        # cent lignes à zéro ne se voit nulle part.
        diff = quality.compare(
            snapshot(table={"account_invoice": 651}),
            snapshot(table={"account_invoice": 0}),
        )
        self.assertEqual(diff["rows_lost"], [("account_invoice", 651, 0)])

    def test_a_table_that_disappears_counts_as_emptied(self):
        diff = quality.compare(
            snapshot(table={"account_invoice": 651}), snapshot(table={})
        )
        self.assertEqual(diff["rows_lost"], [("account_invoice", 651, 0)])

    def test_an_empty_table_that_disappears_is_not_a_loss(self):
        # Rien à perdre : le signaler noierait les vraies pertes.
        diff = quality.compare(snapshot(table={"vide": 0}), snapshot(table={}))
        self.assertEqual(diff["rows_lost"], [])

    def test_counts_move_with_their_sign(self):
        diff = quality.compare(snapshot(view=2000), snapshot(view=3733))
        self.assertEqual(diff["delta"]["view"], 1733)

    def test_a_missing_database_is_not_comparable(self):
        diff = quality.compare(snapshot(), {"exists": False})
        self.assertTrue(diff["unavailable"])


class TestNotCryingWolfOnRenames(Base):
    """Deux garde-fous rejetés sur une VRAIE migration avant celui-ci."""

    def test_the_row_count_alone_is_not_enough(self):
        # Il accouplait `account_account_tag_account_tax_template_rel` à
        # `dms_directory` : les deux comptaient sept lignes.
        self.assertFalse(
            quality.looks_renamed(
                "account_account_tag_account_tax_template_rel", "dms_directory"
            )
        )

    def test_a_shared_word_is_not_enough_either(self):
        # « cleanup » ne dit rien, « users » non plus.
        self.assertFalse(
            quality.looks_renamed(
                "cleanup_purge_wizard_menu", "cleanup_create_indexes_line"
            )
        )
        self.assertFalse(
            quality.looks_renamed(
                "digest_tip_res_users_rel", "project_allowed_portal_users_rel"
            )
        )

    def test_real_renames_are_recognised(self):
        for un, deux in (
            ("muk_dms_directory", "dms_directory"),
            ("website_redirect", "website_rewrite"),
            (
                "account_invoice_purchase_order_rel",
                "account_move_purchase_order_rel",
            ),
        ):
            self.assertTrue(quality.looks_renamed(un, deux), (un, deux))

    def test_a_rename_needs_the_same_row_count(self):
        # Un nom qui se ressemble mais un compte qui change n'est pas un
        # renommage : c'est un renommage ET une perte, qu'on ne fusionne pas.
        diff = quality.compare(
            snapshot(table={"muk_dms_directory": 10}),
            snapshot(table={"dms_directory": 4}),
        )
        self.assertEqual(diff["renamed"], [])

    def test_a_renamed_table_is_STILL_listed_as_lost(self):
        """La règle qui compte plus que tout ici.

        Retirer une perte parce qu'on croit à un renommage, c'est faire
        disparaître du rapport ce qu'on est venu y chercher — et le
        rapprochement s'est déjà trompé.
        """
        diff = quality.compare(
            snapshot(table={"muk_dms_directory": 7}),
            snapshot(table={"dms_directory": 7}),
        )
        self.assertEqual(
            diff["renamed"], [("muk_dms_directory", "dms_directory", 7)]
        )
        self.assertIn(("muk_dms_directory", 7, 0), diff["rows_lost"])

    def test_the_report_says_it_is_only_probable(self):
        diff = quality.compare(
            snapshot(table={"muk_dms_directory": 7}),
            snapshot(table={"dms_directory": 7}),
        )
        texte = "\n".join(quality.render_compare(diff, colour=False))
        self.assertIn("muk_dms_directory", texte)
        self.assertIn("probably renamed", texte)


class TestTheOverallReport(Base):
    def test_it_compares_the_ENDS_not_the_sum_of_steps(self):
        """Un module retiré en 15 puis remis en 17 n'a rien perdu.

        L'addition des comparaisons deux à deux le compterait deux fois,
        une en perte et une en gain, et le bilan mentirait dans les deux
        sens à la fois.
        """
        lst = [
            snapshot(odoo="12.0", installed=["a", "b"]),
            snapshot(odoo="15.0", installed=["a"]),
            snapshot(odoo="18.0", installed=["a", "b"]),
        ]
        bilan = quality.overall(lst)
        self.assertEqual(bilan["modules_lost"], [])
        self.assertEqual(bilan["modules_gained"], [])

    def test_it_needs_two_databases(self):
        self.assertTrue(quality.overall([snapshot()])["unavailable"])

    def test_missing_databases_are_skipped_not_fatal(self):
        lst = [
            snapshot(odoo="12.0", installed=["a"]),
            {"database": "absente", "exists": False},
            snapshot(odoo="18.0", installed=["a", "b"]),
        ]
        self.assertEqual(quality.overall(lst)["modules_gained"], ["b"])


class TestTheReportItself(Base):
    def test_every_step_is_listed(self):
        texte = quality.render_text(
            [
                snapshot(odoo="12.0", database="a"),
                snapshot(odoo="13.0", database="b"),
            ],
            colour=False,
        )
        self.assertIn("12.0", texte)
        self.assertIn("13.0", texte)

    def test_a_missing_database_is_named_not_hidden(self):
        texte = quality.render_text(
            [snapshot(), {"database": "absente", "exists": False}],
            colour=False,
        )
        self.assertIn("absente", texte)
        self.assertIn("not found", texte)

    def test_missing_attachment_files_are_surfaced(self):
        # La trouvaille faite à la main sur une vraie migration : 254
        # fichiers absents du filestore, que rien ne signalait.
        texte = quality.render_text(
            [snapshot(attachment_missing=254)], colour=False
        )
        self.assertIn("254", texte)

    def test_it_ends_with_the_start_to_finish_comparison(self):
        texte = quality.render_text(
            [snapshot(odoo="12.0"), snapshot(odoo="18.0")], colour=False
        )
        self.assertIn("From start to finish", texte)
        self.assertLess(texte.index("12.0"), texte.index("From start"))


class TestItNeverWrites(Base):
    """Les bases de palier sont parfois la seule copie d'un état."""

    def test_the_connection_is_read_only_at_the_server(self):
        import inspect

        source = inspect.getsource(quality.run_psql)
        self.assertIn("default_transaction_read_only=on", source)

    def test_no_odoo_is_started(self):
        # Six démarrages coûteraient une heure ET écriraient dans les
        # bases. L'inspection en SQL prend moins d'une demi-seconde.
        import inspect

        source = inspect.getsource(quality)
        for interdit in ("odoo_bin", "run.sh", "--update", "-u all"):
            self.assertNotIn(interdit, source, interdit)


class TestTheFullScreen(Base):
    def test_one_row_per_step_plus_the_overall(self):
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        lignes = qtui.rows(lst)
        self.assertEqual(
            [x["kind"] for x in lignes], ["step", "step", "overall"]
        )

    def test_the_overall_comes_LAST(self):
        # On descend la liste comme on a vécu la migration ; « qu'en
        # reste-t-il » se pose une fois le chemin vu.
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        self.assertEqual(qtui.rows(lst)[-1]["kind"], "overall")

    def test_a_missing_database_gets_its_own_row(self):
        lignes = qtui.rows(
            [snapshot(), {"database": "absente", "exists": False}]
        )
        self.assertIn("missing", [x["kind"] for x in lignes])

    def test_the_column_counts_the_lost_tables(self):
        lst = [
            snapshot(odoo="12.0", table={"t": 100}),
            snapshot(odoo="13.0", table={"t": 0}),
        ]
        self.assertEqual(qtui.rows(lst)[1]["detail"], "1")

    def test_a_step_that_lost_nothing_leaves_it_empty(self):
        lst = [snapshot(odoo="12.0"), snapshot(odoo="13.0")]
        self.assertEqual(qtui.rows(lst)[1]["detail"], "")

    def test_the_pane_uses_the_same_comparison_as_the_text(self):
        import inspect

        self.assertIn(
            "quality.render_compare", inspect.getsource(qtui.pane_text)
        )

    def test_a_pipe_is_explained_rather_than_silent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(qtui.run_tui([snapshot()]))
        self.assertTrue(out.getvalue().strip())

    def test_nothing_to_show_stays_silent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(qtui.run_tui([]))
        self.assertEqual(out.getvalue(), "")


class TestWhereItIsOffered(Base):
    def test_the_analyse_menu_offers_it(self):
        chemin = os.path.join(REPO, "script", "todo", "todo.py")
        with open(chemin) as handle:
            texte = handle.read()
        self.assertIn("Quality of a migration, step by step", texte)
        self.assertIn("execute_analyse_migration_quality", texte)

    def test_the_existing_menu_numbers_did_not_move(self):
        # Quelqu'un connaît « 1 », « 2 », « 3 » : les décaler pour insérer
        # une entrée au milieu se paierait à chaque usage.
        import inspect

        from script.todo.todo import TODO

        source = inspect.getsource(TODO.prompt_execute_analyse)
        self.assertLess(
            source.index("Tables and database size"),
            source.index("Quality of a migration"),
        )

    def test_the_state_screen_offers_it_too(self):
        import inspect

        from script.todo import migration_status_tui as stui

        source = inspect.getsource(stui.build_app)
        self.assertIn('"k", "quality"', source)
        self.assertIn("check_migration_quality", source)

    def test_it_hands_the_terminal_over(self):
        # Deux applications Textual ne peuvent pas peindre le même écran.
        import inspect

        from script.todo import migration_status_tui as stui

        source = inspect.getsource(stui.build_app)
        debut = source.index("def action_quality")
        self.assertIn("self.suspend()", source[debut : debut + 1400])

    def test_it_opens_it_in_its_OWN_process(self):
        """Le défaut que « suspend est appelé » ne suffisait pas à attraper.

        `suspend()` rend le terminal mais n'arrête PAS la boucle asyncio.
        `app.run()` appelle `asyncio.run()`, qui refuse de tourner dans une
        boucle déjà en cours : « asyncio.run() cannot be called from a
        running event loop ». Un sous-processus a sa propre boucle.
        """
        import inspect

        from script.todo import migration_status_tui as stui

        source = inspect.getsource(stui.build_app)
        debut = source.index("def action_quality")
        fenetre = source[debut : debut + 1400]
        self.assertIn("subprocess.call", fenetre)
        self.assertNotIn("run_quality(", fenetre)


class TestItRefusesToNestItself(Base):
    """Le filet de sécurité, pour qui rappellerait `run_tui` de l'intérieur.

    Une trace de quarante lignes n'apprend rien ; une phrase qui dit
    d'ouvrir un processus à part, si.
    """

    def test_no_loop_running_is_the_normal_case(self):
        self.assertFalse(qtui.in_event_loop())

    def test_a_running_loop_is_detected(self):
        import asyncio

        async def dedans():
            return qtui.in_event_loop()

        self.assertTrue(asyncio.run(dedans()))

    def test_run_tui_consults_it_before_starting(self):
        import inspect

        source = inspect.getsource(qtui.run_tui)
        self.assertLess(
            source.index("in_event_loop()"), source.index("app.run()")
        )

    def test_the_refusal_says_what_to_do_instead(self):
        import inspect

        source = inspect.getsource(qtui.run_tui)
        self.assertIn("its own", source)


if __name__ == "__main__":
    unittest.main()
