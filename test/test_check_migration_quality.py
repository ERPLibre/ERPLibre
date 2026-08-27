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
        #
        # La garde porte sur le CODE, fonction par fonction, et non sur le
        # texte du fichier : la revue CITE « ./odoo_bin.sh shell » comme
        # étape à faire soi-même, et interdire le mot interdirait de le
        # nommer. Ce qu'on veut garantir est que rien ici ne le LANCE.
        import inspect

        for nom, objet in vars(quality).items():
            if not inspect.isfunction(objet):
                continue
            if objet.__module__ != quality.__name__:
                continue
            source = inspect.getsource(objet)
            for interdit in ("odoo_bin", "run.sh", "--update", "-u all"):
                self.assertNotIn(interdit, source, f"{nom} → {interdit}")

    def test_the_only_process_it_launches_is_psql(self):
        # Complément du précédent : une donnée peut nommer un programme,
        # un `subprocess.run` le lance. Il n'y en a qu'un, et c'est psql.
        import ast
        import inspect

        arbre = ast.parse(inspect.getsource(quality))
        lances = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and getattr(n.func.value, "id", "") == "subprocess"
        ]
        self.assertEqual(1, len(lances))
        premier = lances[0].args[0]
        self.assertEqual("psql", premier.elts[0].value)


class TestTheFullScreen(Base):
    def test_one_row_per_step_then_the_overall(self):
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        lignes = qtui.rows(lst, {})
        debut = [x["kind"] for x in lignes][:3]
        self.assertEqual(debut, ["step", "step", "overall"])

    def test_the_overall_closes_the_steps(self):
        # On descend la liste comme on a vécu la migration ; « qu'en
        # reste-t-il » se pose une fois le chemin vu. Ce qui suit — les
        # verdicts, où les lire, quoi vérifier — répond à « et après ».
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        genres = [x["kind"] for x in qtui.rows(lst, {})]
        rang = genres.index("overall")
        self.assertEqual(set(genres[:rang]), {"step"})
        self.assertNotIn("step", genres[rang:])

    def test_the_review_sections_come_after_the_overall(self):
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        genres = [x["kind"] for x in qtui.rows(lst, {})]
        apres = set(genres[genres.index("overall") + 1 :])
        self.assertTrue(apres <= set(qtui.EXTRA_KINDS) | {"header"}, apres)

    def test_the_screen_does_not_depend_on_this_machine(self):
        # Sans `dct`, la liste refléterait ce qu'une migration a laissé
        # sur CE poste : deux exécutions ne rendraient pas la même chose.
        lst = [snapshot(odoo="12.0"), snapshot(odoo="18.0")]
        avec = qtui.rows(lst, {"lst_event": []})
        self.assertNotIn("verdict", [x["kind"] for x in avec])

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


class TestTheOpenUpgradeOverlay(unittest.TestCase):
    """Le théorique posé sur le pratique.

    Le rapport comptait des « + » et des « − ». Un champ devenu calculé
    n'est ni l'un ni l'autre : il perd sa colonne et garde son existence.
    Sans troisième état, on alarmait à chaque palier.
    """

    INDEX = {
        "models_new": {"product.combo"},
        "models_obsolete": {"account.unreconcile"},
        "models_renamed": {"pos.combo": "product.combo"},
        "fields_new": set(),
        "fields_del": {"account.journal.secure_sequence_id"},
        "fields_unstored": {"account.account.code"},
        "fields_stored": set(),
        "fields_moved": {"pos.combo.base_price": "product"},
        "fields_company_dependent": {"account.cash.rounding.loss_account_id"},
        "fields_other": {},
        "xml_new": 0,
        "xml_del": 0,
        "modules": 402,
    }

    def setUp(self):
        quality._CACHE_DECLARE[18] = self.INDEX
        from script.analyse import openupgrade_analysis as oa

        self.vrai = oa.analysed_modules
        oa.analysed_modules = lambda version, root=None: {"account", "sale"}
        self.oa = oa

    def tearDown(self):
        quality._CACHE_DECLARE.pop(18, None)
        self.oa.analysed_modules = self.vrai

    def pose(self, modeles=(), champs=(), origines=None):
        return quality.overlay_declared(
            18, list(modeles), list(champs), origines
        )

    def test_a_declared_obsolete_model_is_not_a_finding(self):
        d = self.pose(modeles=["account.unreconcile"])
        self.assertEqual(d["models"]["obsolete"], ["account.unreconcile"])
        self.assertEqual(d["models"]["undeclared"], [])

    def test_a_renamed_model_names_its_destination(self):
        d = self.pose(modeles=["pos.combo"])
        self.assertEqual(
            d["models"]["renamed"], [("pos.combo", "product.combo")]
        )

    def test_an_unknown_model_stays_undeclared(self):
        d = self.pose(modeles=["ma.bebelle"])
        self.assertEqual(d["models"]["undeclared"], ["ma.bebelle"])

    def test_a_field_that_became_computed_is_its_own_category(self):
        # NI perte NI gain : le champ demeure, la colonne non. C'est tout
        # l'objet de l'ajout.
        d = self.pose(champs=["account.account.code"])
        self.assertEqual(d["fields"]["unstored"], ["account.account.code"])
        self.assertEqual(d["fields"]["undeclared"], [])

    def test_declared_removals_and_moves_land_apart(self):
        d = self.pose(
            champs=[
                "account.journal.secure_sequence_id",
                "pos.combo.base_price",
                "account.cash.rounding.loss_account_id",
            ]
        )
        self.assertEqual(
            d["fields"]["del"], ["account.journal.secure_sequence_id"]
        )
        self.assertEqual(
            d["fields"]["moved"], [("pos.combo.base_price", "product")]
        )
        self.assertEqual(
            d["fields"]["company_dependent"],
            ["account.cash.rounding.loss_account_id"],
        )

    def test_a_field_whose_model_vanished_is_not_counted_again(self):
        # 544 champs pour un seul modèle disparu, mesuré sur un vrai
        # palier : listés un par un, ils cachaient les vingt vraies
        # trouvailles.
        d = self.pose(
            modeles=["account.unreconcile"],
            champs=["account.unreconcile.name"],
        )
        self.assertEqual(
            d["fields"]["model_gone"], ["account.unreconcile.name"]
        )
        self.assertEqual(d["fields"]["undeclared"], [])

    def test_a_field_of_an_unanalysed_module_is_not_accused(self):
        # OpenUpgrade n'analyse que le cœur : dire « non déclaré » d'un
        # champ OCA est vrai à la lettre et faux en esprit.
        d = self.pose(
            champs=["x.mon_champ"],
            origines={"x.mon_champ": ["mon_module_oca"]},
        )
        self.assertEqual(d["fields"]["not_analysed"], ["x.mon_champ"])
        self.assertEqual(d["fields"]["undeclared"], [])

    def test_a_core_field_with_no_declaration_SURVIVES_as_undeclared(self):
        # Le signal ne doit pas se faire absorber par les catégories
        # rassurantes : c'est la seule ligne qui demande un examen.
        d = self.pose(
            champs=["account.account.mystere"],
            origines={"account.account.mystere": ["account"]},
        )
        self.assertEqual(
            d["fields"]["undeclared"], ["account.account.mystere"]
        )

    def test_no_analysis_is_said_not_shown_as_zero(self):
        # « 0 déclaré » et « analyse absente » se ressemblent à l'œil.
        quality._CACHE_DECLARE[18] = dict(self.INDEX, modules=0)
        d = self.pose(modeles=["x.y"])
        self.assertFalse(d["available"])
        self.assertEqual(d["reason"], "missing")
        texte = "\n".join(quality.render_declared(d, False))
        self.assertIn(
            todo_i18n.t("No OpenUpgrade analysis for this step."), texte
        )

    def test_an_unknown_version_declares_nothing_quietly(self):
        d = quality.overlay_declared(None, ["x.y"], [])
        self.assertFalse(d["available"])
        self.assertEqual(quality.render_declared(d, False), [])


class TestGroupingByFieldName(unittest.TestCase):
    def test_one_mixin_field_is_one_finding(self):
        # `__last_update` s'est compté 391 fois sur un vrai palier : c'est
        # UN changement.
        groupes = quality.group_by_field_name(
            [f"modele{i}.zz_last_update" for i in range(391)]
            + ["account.account.aa_autre"]
        )
        self.assertEqual(groupes[0][0], "zz_last_update")
        self.assertEqual(groupes[0][1], 391)

    def test_the_most_widespread_comes_first(self):
        groupes = quality.group_by_field_name(
            ["a.zzz", "b.zzz", "c.zzz", "d.aaa"]
        )
        self.assertEqual([nom for nom, _n, _e in groupes], ["zzz", "aaa"])

    def test_a_lone_field_keeps_its_full_key_as_example(self):
        groupes = quality.group_by_field_name(["account.account.seul"])
        self.assertEqual(groupes[0], ("seul", 1, "account.account.seul"))


class TestFieldsThatHeldNoData(TestTheOpenUpgradeOverlay):
    """Un champ sans colonne n'a rien perdu — et il noyait le rapport.

    Mesuré sur une chaîne 12 → 18 : le seau « NON déclarés par
    OpenUpgrade » comptait 565 champs au palier 16 → 17, dont 397
    `__last_update` — un champ magique qu'Odoo 17 cesse d'inscrire et
    qui n'a jamais eu de colonne. Un chiffre de tête qui fait peur pour
    rien fait ignorer le rapport entier.

    Après la règle : 565 → 57, et les 508 autres sont NOMMÉS sous
    « sans donnée propre », en une ligne par nom de champ.
    """

    def declare(self, perdus, stockes, origines=None):
        # Le montage de la classe parente pose l'index déclaré en
        # cache et restreint les modules analysés : sans lui
        # `overlay_declared` sort tout de suite et rien n'est mesuré.
        return quality.overlay_declared(18, [], perdus, origines, stockes)

    def test_an_unstored_field_is_set_aside(self):
        # `store=false` : le champ n'a jamais eu de colonne. Sa
        # disparition ne coûte pas un octet.
        res = self.declare(["res.partner.calcule"], set())
        self.assertEqual(["res.partner.calcule"], res["fields"]["no_data"])
        self.assertEqual([], res["fields"]["undeclared"])

    def test_a_stored_field_stays_a_finding(self):
        res = self.declare(["res.partner.vrai"], {"res.partner.vrai"})
        self.assertEqual(["res.partner.vrai"], res["fields"]["undeclared"])
        self.assertEqual([], res["fields"]["no_data"])

    def test_id_is_set_aside_even_though_it_is_stored(self):
        # `id` porte une donnée, mais pas la SIENNE : elle appartient à
        # la ligne. Odoo 15 cesse de l'inscrire sur les modèles
        # abstraits — 65 « pertes » d'un coup, zéro octet.
        res = self.declare(["res.partner.id"], {"res.partner.id"})
        self.assertEqual(["res.partner.id"], res["fields"]["no_data"])

    def test_a_field_named_id_on_another_model_too(self):
        res = self.declare(["mail.thread.id"], {"mail.thread.id"})
        self.assertEqual(["mail.thread.id"], res["fields"]["no_data"])

    def test_without_the_information_nothing_is_set_aside(self):
        # Un instantané pris par une version antérieure de l'outil n'a
        # pas `field_stored`. Tout verser dans le seau calme ferait
        # taire le rapport au lieu de l'éclaircir.
        res = quality.overlay_declared(18, [], ["res.partner.x"], None, None)
        self.assertEqual([], res["fields"]["no_data"])
        self.assertEqual(["res.partner.x"], res["fields"]["undeclared"])

    def test_it_comes_before_the_not_analysed_bucket(self):
        # « sans donnée propre » est une raison plus forte que « hors du
        # champ d'OpenUpgrade ». Mesuré : le placement avant fait tomber
        # `not_analysed` de 181 à 47 au palier 16 → 17, sans changer
        # `undeclared` — le seau résiduel se réduit au risque réel.
        res = self.declare(
            ["oca_module.model.champ"],
            set(),
            {"oca_module.model.champ": ["un_module_oca_inconnu"]},
        )
        self.assertEqual(["oca_module.model.champ"], res["fields"]["no_data"])
        self.assertEqual([], res["fields"]["not_analysed"])

    def test_the_model_gone_bucket_still_wins(self):
        # Un champ dont le MODÈLE a disparu reste rangé là : c'est UNE
        # trouvaille, pas une par champ.
        res = quality.overlay_declared(
            18, ["res.parti"], ["res.parti.champ"], None, set()
        )
        self.assertEqual(["res.parti.champ"], res["fields"]["model_gone"])
        self.assertEqual([], res["fields"]["no_data"])

    def test_inspect_reads_which_fields_hold_data(self):
        # La règle ne vaut que si le renseignement est LU. En bouchonnant
        # psql on éprouve la requête elle-même : c'est `store` qui
        # décide, et lui seul.
        vues = []

        def faux_psql(database, sql, **kwargs):
            vues.append(" ".join(sql.split()))
            if "WHERE store" in " ".join(sql.split()):
                return [["res.partner.vrai"]]
            if "FROM ir_model_fields ORDER BY" in " ".join(sql.split()):
                return [["res.partner.vrai"], ["res.partner.calcule"]]
            return []

        vrai = quality.run_psql
        self.addCleanup(setattr, quality, "run_psql", vrai)
        quality.run_psql = faux_psql
        etat = quality.inspect("essai")
        self.assertEqual(["res.partner.vrai"], etat["field_stored"])
        self.assertTrue(
            any("WHERE store" in v for v in vues),
            "la requête doit trancher sur `store`, pas sur autre chose",
        )

    def test_the_names_are_shown_grouped_by_field(self):
        # C'est la LIGNE « __last_update × 101 modèle(s) » qui explique le
        # gros chiffre. Sans elle on remplace un nombre effrayant par un
        # nombre opaque, et le lecteur reste sans réponse.
        declare = {
            "available": True,
            "modules": 400,
            "models": {"obsolete": [], "renamed": [], "undeclared": []},
            "fields": {
                "del": [],
                "unstored": [],
                "company_dependent": [],
                "moved": [],
                "model_gone": [],
                "no_data": [
                    "a.__last_update",
                    "b.__last_update",
                    "c.__last_update",
                ],
                "not_analysed": [],
                "undeclared": [],
            },
        }
        texte = "\n".join(quality.render_declared(declare, colour=False))
        self.assertIn("__last_update", texte)
        self.assertIn("3", texte)

    def test_compare_passes_the_stored_fields_along(self):
        # La règle vit dans `overlay_declared`, mais c'est `compare` qui
        # lui donne de quoi trancher : sans la transmission, le seau
        # reste vide et le rapport annonce toujours son gros chiffre.
        commun = {
            "exists": True,
            "installed": [],
            "model": ["res.partner"],
            "table": {},
            "view": 0,
            "view_cow": 0,
            "menu": 0,
            "attachment": 0,
            "cow": [],
            "odoo": "18.0",
            "database": "x",
        }
        avant = dict(
            commun,
            field=["res.partner.calcule", "res.partner.vrai"],
            field_stored=["res.partner.vrai"],
        )
        apres = dict(commun, field=[])
        diff = quality.compare(avant, apres)
        champs = diff["declared"]["fields"]
        self.assertEqual(["res.partner.calcule"], champs["no_data"])
        self.assertEqual(["res.partner.vrai"], champs["undeclared"])

    def test_the_bucket_has_a_label_and_a_quiet_tint(self):
        table = dict(
            (cle, (libelle, teinte))
            for cle, libelle, teinte in quality.DECLARE_CHAMPS
        )
        self.assertIn("no_data", table)
        libelle, teinte = table["no_data"]
        self.assertEqual("dim", teinte, "il doit rassurer, pas attirer l'œil")
        self.assertTrue(quality.t(libelle))


class TestWhyAnAttachmentWentAway(Base):
    """« 409 pièces jointes perdues » n'en recouvrait presque aucune.

    Mesuré sur une chaîne 12 → 18 : des 516 lignes parties au palier 18,
    452 avaient perdu leur CHAMP PORTEUR aux paliers 13 et 14 — elles
    étaient déjà illisibles, Odoo lève un KeyError en les contrôlant. Ce
    ne sont pas des données, ce sont des débris, et la 18 les ramasse.

    On ne DÉCLARE pas cette perte dans SEMANTIC_MAP : cette carte nomme
    une TABLE, et la cause n'est pas la table, ce sont ces lignes-là.
    Déclarée, elle rangerait toute perte future de ir_attachment sous
    « changement d'Odoo » — cinq mille factures comprises.
    """

    def etat(self, lignes, modeles=("res.partner",)):
        return {
            "exists": True,
            "attachment_row": lignes,
            "model": list(modeles),
        }

    def test_a_field_already_gone_is_not_a_loss(self):
        avant = self.etat({"7": ("res.partner", "image", "1", False)})
        seaux = quality.classify_attachments(avant, self.etat({}))
        self.assertEqual(["7"], seaux["field_debt"])
        self.assertEqual([], seaux["undeclared"])

    def test_a_field_removed_at_this_step_is_not_a_loss_either(self):
        avant = self.etat({"7": ("res.partner", "image", "1", True)})
        apres = self.etat({"8": ("res.partner", "image", "2", False)})
        seaux = quality.classify_attachments(avant, apres)
        self.assertEqual(["7"], seaux["field_dropped"])

    def test_a_model_that_left_takes_its_attachments_with_it(self):
        avant = self.etat({"7": ("mail.channel", "image", "1", True)})
        apres = self.etat({}, modeles=["res.partner"])
        seaux = quality.classify_attachments(avant, apres)
        self.assertEqual(["7"], seaux["model_gone"])

    def test_a_live_field_losing_its_attachment_stays_red(self):
        # LE cas qui compte : une donnée lisible a disparu.
        avant = self.etat({"7": ("res.partner", "image_1920", "1", True)})
        apres = self.etat({"8": ("res.partner", "image_1920", "2", True)})
        seaux = quality.classify_attachments(avant, apres)
        self.assertEqual(["7"], seaux["undeclared"])

    def test_an_attachment_that_stayed_is_not_counted(self):
        lignes = {"7": ("res.partner", "image_1920", "1", True)}
        seaux = quality.classify_attachments(
            self.etat(lignes), self.etat(lignes)
        )
        self.assertEqual([], seaux["undeclared"])
        self.assertEqual([], seaux["field_debt"])

    def test_without_the_information_it_says_it_does_not_know(self):
        # Un instantané pris par une version antérieure n'a pas
        # `attachment_row`. Rendre des seaux vides ferait croire à une
        # explication complète.
        self.assertIsNone(
            quality.classify_attachments({"exists": True}, self.etat({}))
        )

    def test_the_red_bucket_is_the_only_one_that_warns(self):
        table = {cle: teinte for cle, _l, teinte in quality.ATTACHMENT_KIND}
        self.assertEqual("warn", table["undeclared"])
        for cle in ("field_debt", "field_dropped", "model_gone"):
            self.assertEqual("dim", table[cle], cle)

    def test_the_report_names_each_cause(self):
        connu = {
            "buckets": {"field_debt": 452, "undeclared": 1},
            "why": "attachments of fields and records already gone",
        }
        texte = "\n".join(quality.render_attachment_kind(connu, colour=False))
        self.assertIn("452", texte)
        self.assertIn("1", texte)
        self.assertIn(
            quality.t("their field was already gone before this step"), texte
        )

    def test_a_bucket_at_zero_is_not_printed(self):
        connu = {"buckets": {"field_debt": 0, "undeclared": 3}}
        texte = "\n".join(quality.render_attachment_kind(connu, colour=False))
        self.assertNotIn(
            quality.t("their field was already gone before this step"), texte
        )

    def test_semantic_map_still_says_nothing_about_attachments(self):
        # Une entrée déclarée rendrait l'outil aveugle : `explain_loss`
        # ne compare que le nom de la table, et `pruned` ne déclenche
        # aucune contre-vérification.
        for entree in quality.SEMANTIC_MAP:
            self.assertNotEqual("ir_attachment", entree.get("table"))


def evenement(**champs):
    """Un événement du journal de progression, forme réelle."""
    brut = {
        "at": "2026-08-26 03:19:59.846453",
        "step": "4.1.I - Migrate database",
        "kind": "test",
        "name": "smoke_public_url",
        "status": 1,
        "detail": ".venv.erplibre/bin/python3"
        " ./script/odoo/migration/smoke_public_url.py"
        " -d test_neutralize_upgrade_14 --internal-required",
    }
    brut.update(champs)
    return brut


class TestTheVerdictsAreReadFromTheFile(Base):
    """`lst_event` est la SEULE trace persistante d'un échec.

    `command_executed` ne dit que ce qui a été lancé. La sortie d'Odoo,
    elle, part sur le terminal et meurt avec lui.
    """

    def test_a_status_written_as_text_still_counts(self):
        # Le pilote écrit parfois le code en chaîne ; le comparer à zéro
        # sans le convertir ferait passer "0" pour un échec.
        lus = quality.read_events({"lst_event": [evenement(status="1")]})
        self.assertEqual(1, lus[0]["status"])

    def test_a_zero_written_as_text_is_not_a_failure(self):
        lus = quality.read_events({"lst_event": [evenement(status="0")]})
        self.assertEqual([], quality.failures(lus))

    def test_an_unreadable_status_is_read_as_success(self):
        # Mieux vaut taire un verdict illisible que crier un faux échec.
        lus = quality.read_events({"lst_event": [evenement(status="oui")]})
        self.assertEqual(0, lus[0]["status"])

    def test_an_entry_that_is_not_a_record_is_skipped(self):
        lus = quality.read_events({"lst_event": ["cassé", evenement()]})
        self.assertEqual(1, len(lus))

    def test_no_list_at_all_reads_as_no_verdict(self):
        self.assertEqual([], quality.read_events({}))
        self.assertEqual([], quality.read_events({"lst_event": None}))

    def test_a_dialogue_answer_is_not_a_failed_test(self):
        # Les entrées `command` à 1 sont les réponses du pilote — « veux-tu
        # effacer le module manquant ». Les compter comme des échecs
        # noierait les vrais sous une liste qu'on cesse de lire.
        lus = quality.read_events(
            {
                "lst_event": [
                    evenement(kind="command", name="./odoo_bin.sh db --clone"),
                    evenement(kind="test"),
                ]
            }
        )
        ratés = quality.failures(lus)
        self.assertEqual(["smoke_public_url"], [e["name"] for e in ratés])


class TestWhichStepAVerdictBelongsTo(Base):
    def test_the_database_is_read_from_the_command(self):
        self.assertEqual(
            "test_neutralize_upgrade_14",
            quality.event_database(evenement()),
        )

    def test_a_command_without_database_yields_nothing(self):
        self.assertEqual("", quality.event_database(evenement(detail="")))

    def test_the_step_comes_from_the_database_not_the_counter(self):
        # `step` compte les ÉTAPES du pilote — « 4.1.I » — et non les
        # versions d'Odoo : les deux sont décalées d'un rang. Afficher
        # « 4.1 » à côté de « palier » nommerait la mauvaise version.
        self.assertEqual("14", quality.event_step(evenement()))

    def test_without_a_step_database_it_falls_back_to_the_counter(self):
        seul = evenement(detail="", step="4.1.I - Migrate database")
        self.assertEqual("4.1.I", quality.event_step(seul))


class TestTheMapOfTraces(Base):
    """Documenter les chemins EST la fonctionnalité."""

    def test_both_places_are_named_even_when_one_is_empty(self):
        sources = quality.log_sources(
            path="rien.json", journal="rien_non_plus.log"
        )
        self.assertEqual(2, len(sources))
        for _role, _chemin, existe, _quoi in sources:
            self.assertFalse(existe)

    def test_the_missing_journal_is_shown_not_hidden(self):
        # Le taire laisserait chercher un fichier qu'Odoo n'a jamais
        # écrit, faute de `logfile=` dans config.conf.
        chemins = [c for _r, c, _e, _q in quality.log_sources()]
        self.assertIn(quality.JOURNAL_ODOO, chemins)


class TestScanningTheOdooLog(Base):
    def setUp(self):
        super().setUp()
        import tempfile

        self.dossier = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dossier)
        self.journal = os.path.join(self.dossier, "odoo.log")

    def ecrire(self, texte):
        with io.open(self.journal, "w", encoding="utf-8") as handle:
            handle.write(texte)

    def test_a_missing_file_is_not_an_error(self):
        rapport = quality.scan_log(os.path.join(self.dossier, "absent.log"))
        self.assertFalse(rapport["exists"])
        self.assertEqual([], rapport["lines"])

    def test_each_pattern_is_counted(self):
        self.ecrire("INFO ok\nERROR boum\nCRITICAL pire\nTraceback (x)\n")
        rapport = quality.scan_log(self.journal)
        for motif in quality.MOTIFS_ERREUR:
            self.assertEqual(1, rapport["counts"][motif], motif)

    def test_a_clean_log_counts_zero_and_shows_nothing(self):
        self.ecrire("INFO tout va bien\nINFO encore\n")
        rapport = quality.scan_log(self.journal)
        self.assertEqual([], rapport["lines"])
        self.assertEqual(0, rapport["counts"]["ERROR"])

    def test_only_the_last_lines_are_kept(self):
        # Un journal de migration pèse des dizaines de mégaoctets ; ce
        # qu'on cherche est ce qui a échoué en DERNIER.
        self.ecrire("".join("ERROR %d\n" % i for i in range(50)))
        rapport = quality.scan_log(self.journal, limite=3)
        self.assertEqual(3, len(rapport["lines"]))
        self.assertIn("ERROR 49", rapport["lines"][-1])


class TestTheReviewChecklist(Base):
    """Une liste de contrôle qu'il faut aller chercher n'est pas suivie."""

    def test_every_step_names_a_question(self):
        for question, _commande, _clef in quality.REVUE:
            self.assertTrue(question.endswith("?"), question)

    def test_a_runnable_step_either_names_a_database_or_reads_the_checkout(
        self,
    ):
        # Une seule étape lit le CHECKOUT et non une base ; toutes les
        # autres doivent nommer la leur, sinon elles s'exécuteraient sur
        # celle du fichier de configuration, qui n'est pas la migrée.
        sans_base = 0
        for _q, commande, clef in quality.REVUE:
            if not clef:
                continue
            if "{db}" in commande:
                continue
            sans_base += 1
            self.assertIn("script/analyse/", commande, commande)
        self.assertTrue(sans_base)

    def test_the_checkout_step_needs_no_database(self):
        # C'est l'angle mort des six autres : elles lisent toutes la BASE
        # et ne peuvent pas voir un dépôt d'addons absent d'un palier.
        sans_base = [
            (q, c) for q, c, k in quality.REVUE if k and "{db}" not in c
        ]
        self.assertTrue(sans_base)
        for _question, commande in sans_base:
            self.assertTrue(commande.startswith("script/analyse/"), commande)

    def test_the_first_step_has_nothing_to_run(self):
        # « La migration est-elle allée jusqu'au bout » se lit dans le
        # fichier ; aucune commande ne le rejoue.
        self.assertIsNone(quality.REVUE[0][2])


class TestTheThreeExtraSections(Base):
    """Elles vivent dans la MÊME table que les paliers."""

    def entetes(self, lst):
        return [r["label"] for r in lst if r["kind"] == "header"]

    def test_the_sections_come_in_the_order_of_the_work(self):
        lst = qtui.extra_rows([], {})
        self.assertEqual(
            [
                f"── {qtui.t('Verdicts')} ──",
                f"── {qtui.t('Validation')} ──",
                f"── {qtui.t('Review')} ──",
            ],
            self.entetes(lst),
        )

    def test_no_verdict_at_all_says_so(self):
        lst = qtui.extra_rows([], {})
        self.assertIn("verdict-none", [r["kind"] for r in lst])

    def test_a_failed_verdict_names_its_step_in_the_label(self):
        # « smoke_public_url » quatre fois de suite ne dit pas lequel a
        # échoué, et c'est la seule chose qu'on veut savoir.
        lst = qtui.extra_rows([], {"lst_event": [evenement()]})
        ligne = [r for r in lst if r["kind"] == "verdict"][0]
        self.assertIn("14", ligne["label"])
        self.assertIn("smoke_public_url", ligne["label"])

    def test_a_failed_verdict_offers_a_way_to_replay_it(self):
        lst = qtui.extra_rows([], {"lst_event": [evenement()]})
        ligne = [r for r in lst if r["kind"] == "verdict"][0]
        self.assertEqual("▶", ligne["detail"])
        self.assertTrue(ligne["command"])

    def premier_entete(self, lst):
        return [r for r in lst if r["kind"] == "header"][0]

    def test_review_steps_target_the_last_database(self):
        presents = [
            {"database": "base_upgrade_17", "exists": True},
            {"database": "base_upgrade_18", "exists": True},
        ]
        lst = qtui.extra_rows(presents, {})
        commandes = [
            r["command"] for r in lst if r["kind"] == "review" and r["command"]
        ]
        self.assertTrue(commandes)
        nommant_une_base = [c for c in commandes if " -d " in c]
        self.assertTrue(nommant_une_base)
        for commande in nommant_une_base:
            self.assertIn("base_upgrade_18", commande)
        for commande in commandes:
            self.assertNotIn("{db}", commande)

    def test_without_a_database_only_the_db_free_step_can_be_run(self):
        # La revue du checkout — manifestes, types de vue — se lance
        # justement AVANT qu'une migration existe. Exiger une base la
        # rendait inerte au seul moment où elle sert.
        lst = qtui.extra_rows([], {})
        lancables = [r for r in lst if r["kind"] == "review" and r["command"]]
        attendu = [c for _q, c, k in quality.REVUE if k and "{db}" not in c]
        self.assertEqual(len(attendu), len(lancables))
        self.assertTrue(lancables)
        for ligne in lancables:
            self.assertNotIn("{db}", ligne["command"])
            self.assertNotIn(" -d ", ligne["command"])

    def test_a_step_that_names_a_database_stays_silent_without_one(self):
        lst = qtui.extra_rows([], {})
        for ligne in [r for r in lst if r["kind"] == "review"]:
            if "{db}" in dict((q, c) for q, c, _k in quality.REVUE).get(
                ligne["question"], ""
            ):
                self.assertEqual("", ligne["command"], ligne["question"])


class TestEveryVerdictIsListed(Base):
    """N'afficher que les échecs répondait à une autre question.

    Devant une base migrée on se demande « qu'a-t-on vérifié », pas
    seulement « qu'est-ce qui a raté ». Et c'est la seule façon de voir
    qu'un échec du palier 14 a été RATTRAPÉ au 17.
    """

    def journal(self, *statuts):
        lst = []
        for rang, statut in enumerate(statuts):
            version = 13 + rang
            lst.append(
                evenement(
                    status=statut,
                    detail=(
                        "./script/odoo/migration/smoke_public_url.py"
                        " -d base_upgrade_%d" % version
                    ),
                )
            )
        return {
            "lst_event": lst,
            "config_database_name": "base",
            "target_odoo_version": "18.0",
            "state_4_upgrade_odoo_lst": [1, 2, 3, 4, 5, 6],
        }

    def test_a_passing_verdict_gets_its_own_line(self):
        lst = qtui.extra_rows([], self.journal(0, 0))
        lignes = [r for r in lst if r["kind"] == "verdict"]
        self.assertEqual(2, len(lignes))
        for ligne in lignes:
            self.assertIn("✅", ligne["label"])

    def test_a_failure_and_a_success_sit_side_by_side(self):
        lst = qtui.extra_rows([], self.journal(1, 0))
        icones = [
            "❌" if "❌" in r["label"] else "✅"
            for r in lst
            if r["kind"] == "verdict"
        ]
        self.assertEqual(["❌", "✅"], icones)

    def test_the_header_counts_failures_over_the_total(self):
        lst = qtui.extra_rows([], self.journal(1, 0, 0))
        entete = [r for r in lst if r["kind"] == "header"][0]
        self.assertEqual("1/3", entete["detail"])

    def test_an_all_green_run_says_how_many(self):
        lst = qtui.extra_rows([], self.journal(0, 0, 0))
        entete = [r for r in lst if r["kind"] == "header"][0]
        self.assertIn("3", entete["detail"])
        self.assertIn("✅", entete["detail"])

    def test_the_starting_database_gets_its_real_version(self):
        # Elle ne porte pas « _upgrade_ » dans son nom : le palier
        # retombait alors sur le compteur du pilote et affichait « 2 ».
        dct = {
            "lst_event": [
                evenement(
                    status=0,
                    step="2 - Update all addons",
                    detail="./script/odoo/migration/smoke_public_url.py -d base",
                )
            ],
            "config_database_name": "base",
            "target_odoo_version": "18.0",
            "state_4_upgrade_odoo_lst": [1, 2, 3, 4, 5, 6],
        }
        ligne = [
            r for r in qtui.extra_rows([], dct) if r["kind"] == "verdict"
        ][0]
        self.assertIn("12", ligne["label"])
        self.assertNotIn(" 2 ", ligne["label"])

    def test_a_dialogue_answer_is_still_not_a_verdict(self):
        # Les entrées `command` à 1 sont les réponses du pilote ; les
        # lister ferait sept faux échecs par migration.
        dct = self.journal(0)
        dct["lst_event"].append(
            evenement(
                kind="command", name="./odoo_bin.sh db --clone", status=1
            )
        )
        lignes = [
            r for r in qtui.extra_rows([], dct) if r["kind"] == "verdict"
        ]
        self.assertEqual(1, len(lignes))


class TestTheStepLogInThePanel(Base):
    """Ce que le journal contient vraiment, dit sans détour."""

    def setUp(self):
        super().setUp()
        import shutil
        import tempfile

        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)

    def journal(self, lignes):
        chemin = os.path.join(self.dossier, "etape.log")
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lignes) + "\n")
        return chemin

    def ligne_verdict(self, chemin, **champs):
        return {
            "kind": "verdict",
            "label": "",
            "event": evenement(**champs),
            "log": chemin,
            "command": "script/odoo/migration/smoke_public_url.py -d x",
        }

    def test_the_passage_around_the_verdict_is_shown(self):
        chemin = self.journal(
            [
                "2026-08-26 03:19:00,000 INFO odoo: avant",
                "[2026-08-26 03:19:44.166204] $ ./script/odoo/migration/"
                "smoke_public_url.py -d test_neutralize_upgrade_14",
                "[2026-08-26 03:19:59.846406]   -> 1",
                "[2026-08-26 03:19:59.847489] [test] smoke_public_url -> 1",
                "2026-08-26 03:20:00,000 INFO odoo: après",
            ]
        )
        texte = qtui.extra_pane(self.ligne_verdict(chemin))
        self.assertIn("INFO odoo: avant", texte)
        self.assertIn("[test] smoke_public_url -> 1", texte)
        self.assertNotIn("INFO odoo: après", texte)

    def test_it_says_the_tool_output_is_absent(self):
        # Sans cela on cherche un fichier plus complet qui n'existe pas :
        # ce qui passe par run_on_terminal n'a pas de sortie capturable.
        chemin = self.journal(
            [
                "[2026-08-26 03:19:44.166204] $ ./script/odoo/migration/"
                "smoke_public_url.py -d test_neutralize_upgrade_14",
                "[2026-08-26 03:19:59.847489] [test] smoke_public_url -> 1",
            ]
        )
        texte = qtui.extra_pane(self.ligne_verdict(chemin))
        self.assertIn(
            qtui.t("the tool output is not in there: it goes to the"), texte
        )

    def test_the_path_and_the_size_are_documented(self):
        chemin = self.journal(["a"] * 40)
        texte = qtui.extra_pane(self.ligne_verdict(chemin))
        self.assertIn(chemin, texte)
        self.assertIn("40", texte)

    def test_no_log_at_all_says_so(self):
        ligne = self.ligne_verdict(None)
        ligne["log"] = None
        texte = qtui.extra_pane(ligne)
        self.assertIn(qtui.t("no log file for this step"), texte)

    def test_a_verdict_absent_from_the_log_says_so(self):
        chemin = self.journal(["rien à voir", "vraiment rien"])
        texte = qtui.extra_pane(self.ligne_verdict(chemin))
        self.assertIn(qtui.t("this verdict is not in it"), texte)

    def test_the_tool_is_read_from_the_command_not_from_the_name(self):
        # Le nom du test se retrouve dans d'AUTRES lignes du journal — une
        # cible make qui le mentionne, par exemple. Chercher le nom au
        # lieu du script y accroche la mauvaise commande, et l'extrait
        # montre alors un passage qui n'a rien à voir.
        chemin = self.journal(
            [
                "[2026-08-26 03:19:44.000000] $ ./script/odoo/migration/"
                "database_cleanup.py -d test_neutralize_upgrade_14",
                "[2026-08-26 03:19:50.000000] [test] database_cleanup -> 0",
                "[2026-08-26 03:19:52.000000] $ make database_cleanup_all",
                "[2026-08-26 03:19:55.000000]   -> 0",
            ]
        )
        with io.open(chemin, encoding="utf-8") as handle:
            brut = handle.read().splitlines()
        _extrait, rang = quality.event_excerpt(
            brut,
            evenement(
                name="database_cleanup",
                at="2026-08-26 03:19:56.000000",
                detail="./script/odoo/migration/database_cleanup.py"
                " -d test_neutralize_upgrade_14",
            ),
        )
        self.assertEqual(0, rang)

    def test_a_verdict_launched_by_no_script_matches_nothing(self):
        # Sans « .py » dans la commande on ne sait pas quoi chercher ;
        # deviner accrocherait la première ligne venue.
        chemin = self.journal(
            ["[2026-08-26 03:19:44.000000] $ make quelque_chose"]
        )
        with io.open(chemin, encoding="utf-8") as handle:
            brut = handle.read().splitlines()
        _extrait, rang = quality.event_excerpt(
            brut, evenement(name="quelque_chose", detail="make quelque_chose")
        )
        self.assertIsNone(rang)

    def test_a_replayed_migration_shows_the_matching_run(self):
        # Le même test apparaît plusieurs fois : la dernière occurrence
        # peut appartenir à une exécution qui n'est pas celle qu'on
        # regarde. On retient celle qui précède l'horodatage du verdict.
        chemin = self.journal(
            [
                "[2026-08-23 00:43:59.331479] $ ./script/odoo/migration/"
                "smoke_public_url.py -d test_neutralize_upgrade_14",
                "[2026-08-23 00:44:19.776150] [test] smoke_public_url -> 1",
                "premiere execution finie",
                "[2026-08-26 03:19:44.166204] $ ./script/odoo/migration/"
                "smoke_public_url.py -d test_neutralize_upgrade_14",
                "[2026-08-26 03:19:59.847489] [test] smoke_public_url -> 1",
            ]
        )
        with io.open(chemin, encoding="utf-8") as handle:
            brut = handle.read().splitlines()
        _extrait, rang = quality.event_excerpt(
            brut, evenement(at="2026-08-23 00:44:19.776150")
        )
        self.assertEqual(0, rang)


class TestKeepingWhatARunWrote(Base):
    """Ce que la migration ne pouvait pas garder, l'écran le peut.

    Le pilote lance par `run_on_terminal`, qui n'a pas de sortie
    capturable — un tube y ferait renoncer les pleins écrans. Mais ce que
    l'on lance SOI-MÊME depuis l'écran, on peut en garder une copie, et
    la relire sans relancer.
    """

    def setUp(self):
        super().setUp()
        import shutil
        import tempfile

        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)

    def fichier(self, contenu):
        chemin = os.path.join(self.dossier, "run.log")
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write(contenu)
        return chemin

    def test_one_file_per_screen_line_not_per_run(self):
        # Deux exécutions de la même étape se remplacent : on veut « ce
        # que ça donne maintenant », pas un historique à trier.
        self.assertEqual(
            qtui.run_log_path("review_residue"),
            qtui.run_log_path("review_residue"),
        )
        self.assertNotEqual(
            qtui.run_log_path("review_residue"),
            qtui.run_log_path("review_state"),
        )

    def test_a_key_that_could_escape_the_directory_cannot(self):
        chemin = os.path.realpath(qtui.run_log_path("../../etc/passwd"))
        dossier = os.path.realpath(
            os.path.join(qtui.REPO_ROOT, qtui.REVIEW_LOG_DIR)
        )
        self.assertEqual(dossier, os.path.dirname(chemin))
        self.assertNotIn(os.sep, os.path.basename(chemin))

    def test_no_key_means_no_file(self):
        self.assertIsNone(qtui.run_log_path(""))

    def test_a_missing_file_reads_as_nothing(self):
        lst, total = qtui.read_run_log(
            os.path.join(self.dossier, "jamais_ecrit.log")
        )
        self.assertEqual(([], 0), (lst, total))

    def test_the_total_is_told_even_when_the_tail_is_kept(self):
        # Montrer la fin SANS dire qu'on en cache se lit « il manque des
        # lignes ».
        chemin = self.fichier("\n".join("l%d" % i for i in range(50)))
        lst, total = qtui.read_run_log(chemin, limite=10)
        self.assertEqual(10, len(lst))
        self.assertEqual(50, total)

    def test_the_whole_output_is_shown_not_a_sample(self):
        # Le panneau DÉFILE : amputer obligerait à relancer dans un
        # terminal pour lire la suite.
        chemin = self.fichier("\n".join("ligne %d" % i for i in range(300)))
        row = {
            "kind": "review",
            "question": "Does Odoo load the database?",
            "command": "x",
            "capture": chemin,
        }
        texte = qtui.extra_pane(row)
        self.assertIn("ligne 0", texte)
        self.assertIn("ligne 299", texte)

    def test_a_line_never_run_says_so(self):
        row = {
            "kind": "review",
            "question": "Does Odoo load the database?",
            "command": "x",
            "capture": os.path.join(self.dossier, "absent.log"),
        }
        self.assertIn(qtui.t("never run from here yet"), qtui.extra_pane(row))

    def test_a_line_with_nothing_to_run_promises_no_log(self):
        row = {
            "kind": "review",
            "question": "Did the migration reach the end?",
            "command": "",
            "capture": os.path.join(self.dossier, "absent.log"),
        }
        self.assertNotIn(
            qtui.t("never run from here yet"), qtui.extra_pane(row)
        )

    def test_the_repl_step_is_not_captured(self):
        # Le passer par un tube lui ferait perdre son invite.
        lignes = qtui.rows([snapshot(odoo="18.0")], {})
        shell = [
            row
            for row in lignes
            if row["kind"] == "review"
            and "shell" in (row.get("command") or "")
        ]
        self.assertTrue(shell)
        self.assertIsNone(shell[0].get("capture"))

    def test_every_other_runnable_step_is_captured(self):
        lignes = qtui.rows([snapshot(odoo="18.0")], {})
        lancables = [
            row
            for row in lignes
            if row["kind"] == "review" and row.get("command")
        ]
        self.assertTrue(lancables)
        sans = [r for r in lancables if not r.get("capture")]
        self.assertEqual(1, len(sans), [r.get("command") for r in sans])


class TestSwitchingTheCheckoutFirst(Base):
    """Lancer un outil sur une base d'un autre palier ÉCRIT dedans."""

    def dct(self):
        return {
            "config_database_name": "base",
            "target_odoo_version": "18.0",
            "state_4_upgrade_odoo_lst": [1, 2, 3, 4, 5, 6],
        }

    def test_the_same_version_needs_no_switch(self):
        courante = quality.checkout_version()
        self.assertIsNone(
            qtui.switch_needed("base_upgrade_%d" % courante, self.dct())
        )

    def test_another_tier_names_its_make_target(self):
        courante = quality.checkout_version()
        autre = 16 if courante != 16 else 15
        besoin = qtui.switch_needed("base_upgrade_%d" % autre, self.dct())
        self.assertEqual((autre, "switch_odoo_%d" % autre), besoin)

    def test_a_database_outside_the_chain_asks_for_nothing(self):
        # On ne sait pas à quel palier elle est : proposer une bascule au
        # hasard basculerait le checkout pour rien.
        self.assertIsNone(qtui.switch_needed("une_autre_base", self.dct()))

    def test_the_panel_warns_before_the_key_not_after(self):
        courante = quality.checkout_version()
        autre = 16 if courante != 16 else 15
        ligne = {
            "kind": "verdict",
            "label": "",
            "event": evenement(),
            "log": None,
            "command": "script/odoo/migration/smoke_public_url.py -d x",
            "switch": (autre, "switch_odoo_%d" % autre),
        }
        texte = qtui.extra_pane(ligne)
        self.assertIn("switch_odoo_%d" % autre, texte)
        self.assertLess(
            texte.index("switch_odoo_%d" % autre),
            texte.index(qtui.t("press r to run it again")),
        )


class TestTheVerdictPanel(Base):
    def panneau(self, **champs):
        lst = qtui.extra_rows([], {"lst_event": [evenement(**champs)]})
        ligne = [r for r in lst if r["kind"] == "verdict"][0]
        return qtui.extra_pane(ligne)

    def test_the_step_shown_is_the_odoo_version(self):
        # « 4.1.I » est la première étape du quatrième bloc du pilote ; la
        # migration en est alors au palier 14. Afficher le compteur sous
        # le mot « palier » faisait lire une version qui n'existe pas.
        texte = self.panneau()
        self.assertIn(f"{qtui.t('step'):<10} 14", texte)

    def test_the_pilot_counter_is_still_there_in_brackets(self):
        # Il sert à retrouver l'entrée dans le journal ; le perdre
        # obligerait à compter les étapes à la main.
        self.assertIn("(4.1.I - Migrate database)", self.panneau())

    def test_what_a_status_of_one_means_is_spelled_out(self):
        # « status 1 » ne dit pas si c'est un constat ou une panne.
        texte = self.panneau()
        self.assertIn(
            qtui.t("1 means a public page failed — not merely a finding."),
            texte,
        )

    def test_a_tool_we_cannot_replay_says_so(self):
        texte = self.panneau(name="un_outil_inconnu")
        self.assertIn(qtui.t("No known way to replay this one."), texte)
        self.assertNotIn(qtui.t("press r to run it again"), texte)


class TestReplayingAVerdict(Base):
    def test_a_known_tool_is_rebuilt_from_its_name(self):
        self.assertEqual(
            "script/odoo/migration/smoke_public_url.py -d base",
            qtui.rerun_command(evenement(), "base"),
        )

    def test_the_recorded_command_is_not_replayed_as_is(self):
        # Le `detail` porte le venv du PALIER — « .venv.erplibre/bin/python3 »
        # d'alors — qui n'est plus celui du checkout courant.
        commande = qtui.rerun_command(evenement(), "base")
        self.assertNotIn(".venv", commande)
        self.assertNotIn("--internal-required", commande)

    def test_an_unknown_tool_offers_nothing(self):
        self.assertEqual(
            "", qtui.rerun_command(evenement(name="autre_chose"), "base")
        )

    def test_without_a_database_there_is_nothing_to_run(self):
        self.assertEqual("", qtui.rerun_command(evenement(), ""))


class TestRunningATestFromTheScreen(Base):
    """Le test prend le terminal, puis le rend."""

    def setUp(self):
        super().setUp()
        self.appels = []

        class FauxRetour:
            returncode = 0

        def faux_run(argv, cwd=None):
            self.appels.append((argv, cwd))
            return FauxRetour()

        faux = type("M", (), {"run": staticmethod(faux_run)})
        self.addCleanup(setattr, qtui, "subprocess", qtui.subprocess)
        qtui.subprocess = faux

    def lancer(self, commande, wait=False):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            resultat = qtui.run_in_terminal(commande, wait=wait)
        return resultat, tampon.getvalue()

    def test_nothing_to_run_runs_nothing(self):
        (code, tourné), _sortie = self.lancer("")
        self.assertIsNone(code)
        self.assertFalse(tourné)
        self.assertEqual([], self.appels)

    def test_a_python_tool_runs_with_this_checkout_interpreter(self):
        # Le lancer avec le python du système le priverait des dépendances
        # d'ERPLibre : l'outil échouerait à l'import, pas sur la base.
        self.lancer("script/odoo/migration/smoke_public_url.py -d base")
        argv, _cwd = self.appels[0]
        self.assertEqual(sys.executable, argv[0])

    def test_it_runs_from_the_repository_root(self):
        # Les chemins que la commande porte y sont relatifs ; ailleurs,
        # ils sont introuvables.
        self.lancer("script/odoo/migration/smoke_public_url.py -d base")
        _argv, cwd = self.appels[0]
        self.assertEqual(qtui.REPO_ROOT, cwd)
        self.assertTrue(
            os.path.isdir(os.path.join(cwd, "script", "odoo", "migration"))
        )

    def test_a_plain_command_keeps_its_own_program(self):
        self.lancer("./odoo_bin.sh shell -d base")
        argv, _cwd = self.appels[0]
        self.assertEqual("./odoo_bin.sh", argv[0])

    def test_the_exit_code_is_shown_not_swallowed(self):
        (code, _t), sortie = self.lancer("./odoo_bin.sh shell")
        self.assertEqual(0, code)
        self.assertIn(qtui.t("exit code:"), sortie)

    def test_a_missing_program_is_reported_not_raised(self):
        def explose(argv, cwd=None):
            raise OSError("No such file or directory")

        qtui.subprocess = type("M", (), {"run": staticmethod(explose)})
        (code, tourné), sortie = self.lancer("absent.sh")
        self.assertIsNone(code)
        self.assertTrue(tourné)
        self.assertIn("No such file", sortie)


if __name__ == "__main__":
    unittest.main()
