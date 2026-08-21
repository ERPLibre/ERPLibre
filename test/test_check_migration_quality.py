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
        # Une table NEUTRE : le mécanisme se teste sans la carte
        # sémantique, qui a ses propres tests.
        diff = quality.compare(
            snapshot(table={"ma_table": 651}),
            snapshot(table={"ma_table": 0}),
        )
        self.assertEqual(diff["rows_lost"], [("ma_table", 651, 0, None)])

    def test_a_table_that_disappears_counts_as_emptied(self):
        diff = quality.compare(
            snapshot(table={"ma_table": 651}), snapshot(table={})
        )
        self.assertEqual(diff["rows_lost"], [("ma_table", 651, 0, None)])

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
        self.assertIn(("muk_dms_directory", 7, 0, None), diff["rows_lost"])

    def test_the_report_says_it_is_only_probable(self):
        diff = quality.compare(
            snapshot(table={"muk_dms_directory": 7}),
            snapshot(table={"dms_directory": 7}),
        )
        texte = "\n".join(quality.render_compare(diff, colour=False))
        self.assertIn("muk_dms_directory", texte)
        self.assertIn("probably renamed", texte)


class TestTheSemanticMap(Base):
    """« 81 tables ont perdu des lignes » noyait les vraies questions.

    La plus grosse d'entre elles — `ir_translation`, 32 984 lignes — est
    une refonte voulue par Odoo en 16. Mettre les refontes et les pertes
    réelles sur le même plan est la façon la plus sûre de ne pas voir les
    secondes.
    """

    def perte(
        self,
        table,
        avant_n,
        apres_n,
        version="18.0",
        cible=None,
        cible_avant=0,
        cible_apres=0,
    ):
        tbl_avant = {table: avant_n}
        tbl_apres = {} if apres_n == 0 else {table: apres_n}
        if cible:
            tbl_avant[cible] = cible_avant
            tbl_apres[cible] = cible_apres
        return quality.compare(
            snapshot(odoo="12.0", table=tbl_avant),
            snapshot(odoo=version, table=tbl_apres),
        )

    def test_a_known_merge_is_explained(self):
        diff = self.perte(
            "account_invoice",
            651,
            0,
            cible="account_move",
            cible_avant=1371,
            cible_apres=1812,
        )
        connu = [x for x in diff["rows_lost"] if x[0] == "account_invoice"][0]
        self.assertIsNotNone(connu[3])
        self.assertEqual(connu[3]["into"], "account_move")
        self.assertEqual(connu[3]["gained"], 441)

    def test_a_retired_table_is_explained_without_a_target(self):
        diff = self.perte("ir_translation", 32984, 0)
        connu = [x for x in diff["rows_lost"] if x[0] == "ir_translation"][0]
        self.assertIsNotNone(connu[3])
        self.assertIsNone(connu[3]["into"])

    def test_the_map_does_not_apply_BEFORE_its_version(self):
        """Une refonte de la 16 n'explique rien d'un palier 12 → 13.

        L'accepter ferait taire une vraie perte sous prétexte que la table
        porte le nom d'une autre, refondue trois versions plus tard.
        """
        diff = self.perte("ir_translation", 32984, 0, version="13.0")
        connu = [x for x in diff["rows_lost"] if x[0] == "ir_translation"][0]
        self.assertIsNone(connu[3])

    def test_it_applies_AT_its_version(self):
        diff = self.perte("ir_translation", 32984, 0, version="16.0")
        connu = [x for x in diff["rows_lost"] if x[0] == "ir_translation"][0]
        self.assertIsNotNone(connu[3])

    def test_an_explained_loss_is_STILL_in_the_list(self):
        # La règle qui vaut plus que tout : expliquer n'est pas cacher.
        diff = self.perte("ir_translation", 32984, 0)
        self.assertIn("ir_translation", [x[0] for x in diff["rows_lost"]])

    def test_the_partition_loses_nothing(self):
        diff = quality.compare(
            snapshot(
                odoo="12.0", table={"ir_translation": 100, "ma_table": 50}
            ),
            snapshot(odoo="18.0", table={}),
        )
        perdues = diff["rows_lost"]
        ouvertes = [x for x in perdues if not x[3]]
        connues = [x for x in perdues if x[3]]
        self.assertEqual(len(perdues), len(ouvertes) + len(connues))
        self.assertEqual(len(perdues), 2)

    def test_a_merge_whose_target_gained_NOTHING_is_flagged(self):
        """Le cas qui compte : la carte dit où les données sont allées.

        Si elles n'y sont pas, l'explication ne tient pas — et la classer
        « attendue » puis passer à autre chose serait exactement l'erreur
        que la carte devait empêcher.
        """
        diff = self.perte(
            "account_invoice",
            651,
            0,
            cible="account_move",
            cible_avant=1371,
            cible_apres=1371,
        )
        connu = [x for x in diff["rows_lost"] if x[0] == "account_invoice"][0]
        self.assertEqual(connu[3]["gained"], 0)
        texte = "\n".join(quality.render_compare(diff, colour=False))
        self.assertIn("gained nothing", texte)

    def test_the_report_puts_the_unexplained_FIRST(self):
        diff = quality.compare(
            snapshot(
                odoo="12.0", table={"ir_translation": 100, "ma_table": 50}
            ),
            snapshot(odoo="18.0", table={}),
        )
        texte = "\n".join(quality.render_compare(diff, colour=False))
        self.assertLess(
            texte.index(todo_i18n.t("table(s) lost rows, unexplained")),
            texte.index(todo_i18n.t("table(s) explained by an Odoo change")),
        )

    def test_needaction_became_notifications_in_15(self):
        """Vérifiée palier par palier, pas déduite d'un nom qui se ressemble.

        1269 lignes en 12, 13 et 14 ; la table disparaît en 15 et
        `mail_notification` en compte exactement 1269. Pas une perdue.
        C'est ce report à l'unité près qui autorise l'entrée — un nom
        voisin n'aurait rien prouvé.
        """
        diff = self.perte(
            "mail_message_res_partner_needaction_rel",
            1269,
            0,
            version="15.0",
            cible="mail_notification",
            cible_avant=0,
            cible_apres=1269,
        )
        connu = diff["rows_lost"][0][3]
        self.assertIsNotNone(connu)
        self.assertEqual(connu["into"], "mail_notification")
        self.assertEqual(connu["gained"], 1269)

    def test_it_is_not_explained_at_the_14_bump(self):
        # La table est encore pleine en 14 : une entrée qui s'appliquerait
        # plus tôt masquerait une perte survenue avant la refonte.
        diff = self.perte(
            "mail_message_res_partner_needaction_rel",
            1269,
            0,
            version="14.0",
        )
        self.assertIsNone(diff["rows_lost"][0][3])

    def test_an_unknown_table_stays_unexplained(self):
        diff = self.perte("ma_table_a_moi", 50, 0)
        self.assertIsNone(diff["rows_lost"][0][3])

    def test_every_entry_of_the_map_is_complete(self):
        # Une entrée sans « why » expliquerait sans dire pourquoi.
        for entree in quality.SEMANTIC_MAP:
            for cle in ("since", "table", "into", "kind", "why"):
                self.assertIn(cle, entree, entree)
            self.assertTrue(entree["why"], entree)
            self.assertIn(
                entree["kind"], ("merged", "renamed", "retired", "pruned")
            )

    def test_a_pruned_entry_never_claims_a_destination(self):
        # « pruned » dit que les lignes ne continuent NULLE PART. Lui donner
        # un « into » ferait passer une perte réelle pour une fusion.
        for entree in quality.SEMANTIC_MAP:
            if entree["kind"] == "pruned":
                self.assertIsNone(entree["into"], entree)

    def test_properties_became_jsonb_columns_in_18(self):
        """La table ne se vide pas : elle GROSSIT, puis disparaît d'un coup.

        211 lignes en 12, 457 en 17, table absente en 18. Les champs
        qu'elle portait sont des colonnes jsonb en 18 — vérifié sur
        res_partner.property_payment_term_id.
        """
        diff = self.perte("ir_property", 457, 0, version="18.0")
        connu = diff["rows_lost"][0][3]
        self.assertIsNotNone(connu)
        self.assertEqual(connu["kind"], "retired")
        self.assertIsNone(connu["into"])

    def test_properties_are_not_explained_at_the_17_bump(self):
        # En 17 la table est à son maximum (457). Dater l'entrée plus tôt
        # ferait passer pour attendue une perte qui ne l'est pas.
        diff = self.perte("ir_property", 273, 100, version="17.0")
        self.assertIsNone(diff["rows_lost"][0][3])

    def test_tracking_values_were_pruned_in_14(self):
        """Le champ suivi passe de varchar à clé étrangère au palier 14.

        En 14 aucune ligne n'a de clé nulle ni cassée : ce qui ne se
        résolvait pas a été supprimé. La table SURVIT — 13833 lignes — donc
        l'explication ne doit pas prétendre qu'elle a disparu.
        """
        diff = self.perte("mail_tracking_value", 16169, 13833, version="14.0")
        table, avant, apres, connu = diff["rows_lost"][0]
        self.assertEqual((avant, apres), (16169, 13833))
        self.assertIsNotNone(connu)
        self.assertEqual(connu["kind"], "pruned")

    def test_tracking_values_are_not_explained_at_the_13_bump(self):
        # 16167 en 12, 16169 en 13 : rien n'a encore été élagué.
        diff = self.perte("mail_tracking_value", 16167, 10000, version="13.0")
        self.assertIsNone(diff["rows_lost"][0][3])

    def test_a_pruned_loss_is_not_rendered_as_retired(self):
        # « retirée de la base » serait faux : la table est toujours là.
        diff = self.perte("mail_tracking_value", 16169, 13833, version="14.0")
        texte = "\n".join(quality.render_compare(diff, False, 8))
        self.assertIn("mail_tracking_value", texte)
        self.assertNotIn(todo_i18n.t("retired from the database"), texte)
        self.assertIn(todo_i18n.t("rows dropped, the table remains"), texte)

    def test_the_column_counts_only_what_needs_an_answer(self):
        # Afficher 81 quand 14 sont des refontes voulues ferait fuir le
        # lecteur du seul chiffre qui demande une réponse.
        lst = [
            snapshot(
                odoo="12.0", table={"ir_translation": 100, "ma_table": 50}
            ),
            snapshot(odoo="18.0", table={}),
        ]
        self.assertEqual(qtui.rows(lst)[1]["detail"], "1")


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


class TestTheStatisticsCarryTheirDelta(Base):
    """Un chiffre seul ne dit rien.

    « 2283 vues » est un nombre ; « +61 » est une information. C'est
    l'écart qu'on lit, pas la valeur.
    """

    def test_each_figure_gets_its_change(self):
        lignes = qtui.statistics(
            snapshot(view=2283, installed=["a"]),
            snapshot(view=2222, installed=["a", "b"]),
        )
        par_nom = {libelle: ecart for libelle, _v, ecart in lignes}
        self.assertEqual(par_nom["views"], 61)
        self.assertEqual(par_nom["modules"], -1)

    def test_the_first_step_has_NO_delta(self):
        # Inventer un écart de zéro laisserait croire à une comparaison
        # qui n'existe pas : il n'y a rien avant le premier palier.
        lignes = qtui.statistics(snapshot(), None)
        self.assertTrue(all(ecart is None for _l, _v, ecart in lignes))

    def test_an_unchanged_figure_shows_zero_not_nothing(self):
        # Zéro est une réponse : « rien n'a bougé » se distingue de « on
        # ne sait pas ».
        lignes = qtui.statistics(snapshot(view=100), snapshot(view=100))
        par_nom = {libelle: ecart for libelle, _v, ecart in lignes}
        self.assertEqual(par_nom["views"], 0)

    def test_every_figure_of_the_pane_is_covered(self):
        libelles = [
            libelle
            for libelle, _v, _e in qtui.statistics(snapshot(), snapshot())
        ]
        for attendu in ("modules", "models", "views", "menus", "attachments"):
            self.assertIn(attendu, libelles)

    def test_the_pane_prints_the_sign(self):
        row = {
            "kind": "step",
            "data": snapshot(view=2283),
            "previous": snapshot(view=2222),
            "diff": None,
        }
        texte = qtui.pane_text([], row)
        self.assertIn("+61", texte)


class TestListingTheMissingFiles(Base):
    """« 254 fichiers absents » ne dit pas lesquels.

    Le groupement tranche : deux cent trente-quatre drapeaux de pays sont
    des images livrées par un module, qu'une mise à jour restaure. Une
    pièce jointe d'événement de 255 ko, non. La liste brute mettait les
    deux sur le même plan.
    """

    DETAIL = [
        {
            "store_fname": "aa/1",
            "model": "res.country",
            "field": "image",
            "res_id": "1",
            "mimetype": "image/png",
            "size": 100,
            "name": "fr",
        },
        {
            "store_fname": "aa/2",
            "model": "res.country",
            "field": "image",
            "res_id": "2",
            "mimetype": "image/png",
            "size": 100,
            "name": "ca",
        },
        {
            "store_fname": "aa/4",
            "model": "res.country",
            "field": "image_128",
            "res_id": "1",
            "mimetype": "image/png",
            "size": 50,
            "name": "fr128",
        },
        {
            "store_fname": "bb/3",
            "model": "calendar.event",
            "field": "-",
            "res_id": "1",
            "mimetype": "image/png",
            "size": 255603,
            "name": "photo.png",
        },
    ]

    def render(self, etat=None, **kw):
        original = quality.missing_detail
        quality.missing_detail = lambda db, lst, limit=400: self.DETAIL
        self.addCleanup(setattr, quality, "missing_detail", original)
        return quality.render_missing(
            etat
            or snapshot(
                attachment_missing=3,
                attachment_missing_list=["aa/1", "aa/2", "bb/3"],
            ),
            **kw,
        )

    def test_nothing_missing_says_so_plainly(self):
        texte = quality.render_missing(snapshot(attachment_missing=0))
        self.assertIn("every attachment file is present", texte)

    def test_the_grouping_comes_first(self):
        texte = self.render()
        self.assertLess(
            texte.index("by model and field"), texte.index("one by one")
        )

    def test_the_grouping_counts_by_model_AND_field(self):
        """Le champ est le renseignement le plus utile du lot.

        Il dit QUEL champ a perdu son image : l'`image_1920` d'un pays n'a
        pas le même poids qu'une pièce jointe de facture. Grouper sur le
        seul modèle fondrait `image` et `image_128` en une ligne, et l'on
        perdrait exactement ce qu'on venait chercher.
        """
        entete = self.render().split("one by one")[0]
        lignes = [
            ligne for ligne in entete.splitlines() if "res.country" in ligne
        ]
        self.assertEqual(len(lignes), 2, entete)
        self.assertTrue(any("image_128" in ligne for ligne in lignes))

    def test_the_loudest_group_comes_first(self):
        texte = self.render().split("one by one")[0]
        self.assertLess(texte.index("res.country"), texte.index("calendar"))

    def test_each_file_names_its_record_and_its_path(self):
        texte = self.render()
        self.assertIn("calendar.event#1", texte)
        self.assertIn("bb/3", texte)
        self.assertIn("photo.png", texte)

    def test_a_long_list_is_cut_and_SAYS_so(self):
        texte = self.render(limit=1)
        self.assertIn("more", texte)

    def test_unreadable_metadata_is_admitted(self):
        original = quality.missing_detail
        quality.missing_detail = lambda db, lst, limit=400: []
        self.addCleanup(setattr, quality, "missing_detail", original)
        texte = quality.render_missing(
            snapshot(attachment_missing=3, attachment_missing_list=["a"])
        )
        self.assertIn("Could not read", texte)

    def test_the_metadata_is_read_ONLY_on_demand(self):
        # Une requête de plus par base allongerait un parcours qui tient
        # en quatre secondes, pour ce qu'on ne regarde qu'en le demandant.
        import inspect

        self.assertNotIn("missing_detail", inspect.getsource(quality.inspect))
        self.assertIn(
            "missing_detail", inspect.getsource(quality.render_missing)
        )

    def test_the_names_are_kept_but_bounded(self):
        # Une base peut en aligner des dizaines de milliers ; l'écran n'en
        # montrera jamais tant, et les garder toutes coûterait pour rien.
        import inspect

        source = inspect.getsource(quality.inspect)
        self.assertIn("attachment_missing_list", source)
        self.assertIn("MAX_MISSING", source)

    def test_a_quote_in_a_filename_cannot_break_the_query(self):
        vu = {}
        original = quality.run_psql
        quality.run_psql = lambda db, sql: vu.setdefault("sql", sql) and []
        self.addCleanup(setattr, quality, "run_psql", original)
        quality.missing_detail("db", ["aa/o'brien"])
        self.assertIn("o''brien", vu["sql"])


class TestTheMissingFilesButton(Base):
    def test_m_is_bound(self):
        app = qtui.build_app([snapshot()])
        touches = {
            touche
            for entree in app.BINDINGS
            for touche in entree[0].split(",")
        }
        self.assertIn("m", touches)

    def test_the_action_exists(self):
        app = qtui.build_app([snapshot()])
        self.assertTrue(hasattr(app, "action_toggle_missing"))

    def test_the_pane_switches_to_the_list(self):
        original = quality.missing_detail
        quality.missing_detail = lambda db, lst, limit=400: []
        self.addCleanup(setattr, quality, "missing_detail", original)
        row = {
            "kind": "step",
            "data": snapshot(
                attachment_missing=3, attachment_missing_list=["a"]
            ),
            "previous": None,
            "diff": None,
        }
        chiffres = qtui.pane_text([], row, mode=None)
        liste = qtui.pane_text([], row, mode="missing")
        self.assertIn("modules", chiffres)
        self.assertNotIn("modules", liste)

    def test_the_pane_tells_you_the_key_exists(self):
        # Une touche que rien n'annonce est une touche que personne ne
        # presse.
        row = {
            "kind": "step",
            "data": snapshot(attachment_missing=254),
            "previous": None,
            "diff": None,
        }
        self.assertIn("press m", qtui.pane_text([], row))


class TestTheMenuEntryLooksLikeItsNeighbours(Base):
    """Une entrée sans icône au milieu d'un menu qui en a partout se lit
    comme une entrée inachevée."""

    ENTREES = (
        "Structure",
        "Tables and database size",
        "Customisation",
        "Customised views, website copies included",
        "Studio and hand-made x_ fields",
        "Migration",
        "Quality of a migration, step by step",
    )

    def libelle(self, cle, langue):
        from script.todo import todo_i18n

        return todo_i18n.TRANSLATIONS[cle][langue]

    def test_every_entry_carries_an_icon(self):
        import unicodedata

        for cle in self.ENTREES:
            for langue in ("fr", "en"):
                premier = self.libelle(cle, langue)[0]
                self.assertNotEqual(
                    unicodedata.category(premier)[0],
                    "L",
                    f"{cle} ({langue}) : pas d'icône",
                )

    def test_the_spacing_follows_the_width_of_the_icon(self):
        """Convention du menu, découverte en la lisant plutôt qu'écrite.

        Une icône de largeur « neutre » — 🗄, 🖼 — s'affiche sur une
        colonne dans un terminal et prend DEUX espaces pour s'aligner ;
        une icône large — 📏, 📐 — en prend un seul. Se tromper décale la
        ligne, et rien ne le dit avant de l'avoir sous les yeux.
        """
        import unicodedata

        for cle in self.ENTREES:
            for langue in ("fr", "en"):
                texte = self.libelle(cle, langue)
                attendu = (
                    2 if unicodedata.east_asian_width(texte[0]) == "N" else 1
                )
                espaces = len(texte[1:]) - len(texte[1:].lstrip(" "))
                self.assertEqual(
                    espaces, attendu, f"{cle} ({langue}) : {texte!r}"
                )

    def test_the_quality_entry_wears_the_report_s_own_symbol(self):
        # Le même symbole pour la même chose. Un libellé de MENU porte
        # son icône dans la traduction — elle se traduit avec lui.
        self.assertTrue(
            self.libelle(
                "Quality of a migration, step by step", "fr"
            ).startswith("📐")
        )
        # Le titre du rapport, lui, porte son symbole dans le CODE de
        # rendu, à côté de ses voisins 📍, 🧪 et 🔷 : deux conventions
        # distinctes, chacune tenable dans son contexte, et l'on vérifie
        # chacune là où elle vit.
        import inspect

        self.assertIn("📐", inspect.getsource(quality.render_text))


class TestAttackingTheListFromTheTop(Base):
    """Cinquante-sept pertes se parcourent par le haut, pas par ordre
    alphabétique : la plus grosse est celle qu'on veut voir en premier."""

    def test_the_biggest_loss_comes_first(self):
        # Des noms dont l'ordre alphabétique CONTREDIT celui des volumes :
        # sinon un tri par nom passerait pour un tri par volume, et le
        # test ne prouverait rien.
        diff = quality.compare(
            snapshot(
                odoo="12.0",
                table={
                    "aaa_petite": 10,
                    "zzz_enorme": 5000,
                    "mmm_moyenne": 100,
                },
            ),
            snapshot(odoo="18.0", table={}),
        )
        self.assertEqual(
            [x[0] for x in diff["rows_lost"]],
            ["zzz_enorme", "mmm_moyenne", "aaa_petite"],
        )

    def test_it_sorts_on_what_was_LOST_not_on_what_was_there(self):
        # Une table de dix mille lignes qui en perd deux compte moins
        # qu'une table de mille qui se vide.
        diff = quality.compare(
            snapshot(odoo="12.0", table={"grosse": 10000, "vidée": 1000}),
            snapshot(odoo="18.0", table={"grosse": 9998}),
        )
        self.assertEqual(
            [x[0] for x in diff["rows_lost"]], ["vidée", "grosse"]
        )


class TestTheFullLists(Base):
    """Le résumé coupe à huit entrées, et il a raison.

    Mais quand on cherche si UN module précis a survécu, la liste
    tronquée ne répond pas — et c'est justement là qu'on en a besoin.
    """

    def diff(self):
        return quality.compare(
            snapshot(
                odoo="12.0",
                installed=["a", "b"],
                model=["m.un", "m.deux"],
                field=["m.un.x", "m.un.y"],
                cow=["site.vue"],
                table={"t": 10},
            ),
            snapshot(
                odoo="18.0",
                installed=["a", "c"],
                model=["m.un", "m.trois"],
                field=["m.un.x", "m.trois.z"],
                cow=["site.autre"],
                table={},
            ),
        )

    def test_fields_are_inventoried(self):
        # Un champ perdu est une colonne de données perdue — plus fin
        # qu'un modèle, qui peut survivre vidé de la moitié des siens.
        diff = self.diff()
        self.assertEqual(diff["fields_lost"], ["m.un.y"])
        self.assertEqual(diff["fields_gained"], ["m.trois.z"])

    def test_cow_copies_are_inventoried_by_key(self):
        # C'est la clé qu'on réinitialise, et par elle qu'on les retrouve.
        diff = self.diff()
        self.assertEqual(diff["cow_lost"], ["site.vue"])
        self.assertEqual(diff["cow_gained"], ["site.autre"])

    def test_every_category_renders_in_full(self):
        for categorie in quality.DETAILS:
            texte = quality.render_detail(self.diff(), categorie)
            self.assertTrue(texte.strip(), categorie)

    def test_nothing_is_truncated(self):
        # C'est tout le propos : le résumé coupe, la liste entière non.
        diff = quality.compare(
            snapshot(odoo="12.0", model=[f"m.{i}" for i in range(200)]),
            snapshot(odoo="18.0", model=[]),
        )
        texte = quality.render_detail(diff, "models")
        self.assertIn("m.199", texte)
        self.assertNotIn("…", texte)

    def test_the_table_list_keeps_the_volume_order(self):
        diff = quality.compare(
            snapshot(odoo="12.0", table={"petite": 1, "enorme": 900}),
            snapshot(odoo="18.0", table={}),
        )
        texte = quality.render_detail(diff, "tables")
        self.assertLess(texte.index("enorme"), texte.index("petite"))

    def test_an_unavailable_comparison_says_so(self):
        self.assertIn("not comparable", quality.render_detail(None, "models"))

    def test_the_headings_carry_no_participle(self):
        """« 28 copies COW perdus » ne s'accorde pas, et ne se traduit pas.

        Le signe porte déjà le sens ; un participe devrait s'accorder avec
        une catégorie dont le genre change d'une langue à l'autre.
        """
        texte = quality.render_detail(self.diff(), "cow")
        self.assertIn("−", texte)
        self.assertNotIn("perdus", texte)


class TestTheInventoryItself(Base):
    """La comparaison était testée, la COLLECTE ne l'était pas.

    Vider l'inventaire des champs dans `inspect` passait inaperçu, parce
    que tous les tests fabriquaient leurs instantanés à la main. Un test
    qui ne touche jamais le code réel ne garde rien.
    """

    def repondre(self, sql):
        if "ir_model_fields" in sql:
            return [["res.partner.name"], ["res.partner.email"]]
        if "website_id IS NOT NULL" in sql:
            return [["site.vue"]]
        if "FROM ir_model " in sql or sql.strip().endswith("ORDER BY model"):
            return [["res.partner"]]
        if "ir_module_module" in sql:
            return [["base", "installed"]]
        if "latest_version" in sql:
            return [["odoo", "18.0.1.3"]]
        return []

    def inspecter(self):
        for nom, remplacant in (
            ("run_psql", lambda db, sql: self.repondre(sql)),
            ("missing_files", lambda db, lst: []),
            ("table_counts", lambda db: {}),
        ):
            original = getattr(quality, nom)
            setattr(quality, nom, remplacant)
            self.addCleanup(setattr, quality, nom, original)
        return quality.inspect("db")

    def test_the_fields_are_collected(self):
        self.assertEqual(
            self.inspecter()["field"],
            ["res.partner.email", "res.partner.name"],
        )

    def test_the_cow_copies_are_collected(self):
        self.assertEqual(self.inspecter()["cow"], ["site.vue"])

    def test_a_cow_copy_without_a_key_is_still_named(self):
        # Une copie sans clé existe quand même ; la taire ferait un
        # inventaire qui ment sur son propre compte.
        import inspect

        self.assertIn("'id:' || id::text", inspect.getsource(quality.inspect))


class TestTheDetailButton(Base):
    def test_d_is_bound(self):
        app = qtui.build_app([snapshot()])
        touches = {
            touche
            for entree in app.BINDINGS
            for touche in entree[0].split(",")
        }
        self.assertIn("d", touches)

    def test_the_cycle_visits_every_category_and_comes_back(self):
        suite = (None,) + quality.DETAILS
        self.assertEqual(len(suite), 6)
        self.assertEqual(suite[len(suite) % len(suite)], None)

    def test_ONE_mode_not_two_flags(self):
        """« fichiers absents » et « liste des modèles » ne peuvent pas
        être vrais en même temps ; deux booléens laissaient écrire cet
        état impossible."""
        import inspect

        source = inspect.getsource(qtui.build_app)
        self.assertIn("self.mode", source)
        self.assertNotIn("self.show_missing", source)

    def test_every_mode_has_a_name(self):
        # Un panneau qui change sans dire pourquoi se lit comme un écran
        # cassé, et avec sept modes on ne devine pas.
        noms = {
            qtui.mode_label(m) for m in (None, "missing") + quality.DETAILS
        }
        self.assertEqual(len(noms), 7)
        for nom in noms:
            self.assertTrue(nom.strip())

    def test_the_name_is_shown_where_it_stays_visible(self):
        import inspect

        source = inspect.getsource(qtui.build_app)
        self.assertIn("self.sub_title = mode_label", source)


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
