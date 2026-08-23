#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire ce qu'OpenUpgrade déclare, sans le déformer.

La catégorie qui porte tout l'outil est « unstored » : le champ EXISTE
encore, il n'a plus de colonne parce qu'il est calculé. Le ranger avec
les suppressions ferait crier au loup à chaque palier ; l'oublier
masquerait une vraie perte.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import openupgrade_analysis as oa  # noqa: E402

EXEMPLE = """---Models in module 'account'---
obsolete model account.unreconcile [transient]
new model account.code.mapping [sql_view]
new model product.combo (renamed from pos.combo in module point_of_sale)
---Fields in module 'account'---
account      / account.account          / _order                        : _order is now 'code' ('id')
account      / account.account          / code (char)                   : not stored anymore
account      / account.account          / code_store (char)             : NEW
account      / account.journal          / secure_sequence_id (many2one) : DEL relation: ir.sequence
account      / account.account          / company_id (many2one)         : is now stored
account      / account.cash.rounding    / loss_account_id (many2one)    : needs conversion to v18-style company dependent
account      / pos.combo                / base_price (float)            : module is now 'product' ('point_of_sale')
account      / account.journal          / type (selection)              : selection_keys added: [credit]
---XML records in module 'account'---
NEW ir.ui.view: account.view_x
DEL ir.ui.view: account.view_y
DEL ir.ui.view: account.view_z
"""


class TestParsing(unittest.TestCase):
    def setUp(self):
        self.index = oa.parse(EXEMPLE)

    def test_obsolete_and_new_models(self):
        self.assertIn("account.unreconcile", self.index["models_obsolete"])
        self.assertIn("account.code.mapping", self.index["models_new"])

    def test_a_rename_is_read_from_the_NEW_side(self):
        # OpenUpgrade ne note le renommage que sur le nouveau modèle ;
        # l'ancien n'apparaît jamais comme « obsolete ». Sans cette
        # lecture, sa disparition passerait pour une perte sèche.
        self.assertEqual(
            self.index["models_renamed"].get("pos.combo"), "product.combo"
        )

    def test_each_field_lands_in_its_category(self):
        for cle, categorie in (
            ("account.account.code", "fields_unstored"),
            ("account.account.code_store", "fields_new"),
            ("account.journal.secure_sequence_id", "fields_del"),
            ("account.account.company_id", "fields_stored"),
            (
                "account.cash.rounding.loss_account_id",
                "fields_company_dependent",
            ),
        ):
            self.assertIn(cle, self.index[categorie], f"{cle} → {categorie}")

    def test_a_moved_field_keeps_its_new_module(self):
        self.assertEqual(
            self.index["fields_moved"].get("pos.combo.base_price"), "product"
        )

    def test_pseudo_fields_are_not_fields(self):
        # `_order` n'est pas dans `ir_model_fields` : le compter fausserait
        # le rapprochement avec la base.
        for cle in list(self.index["fields_other"]) + list(
            self.index["fields_new"]
        ):
            self.assertNotIn("._order", cle)

    def test_an_unclassified_change_is_kept_not_dropped(self):
        # « selection_keys added » n'a pas de catégorie : le perdre
        # silencieusement ferait mentir les totaux.
        self.assertIn("account.journal.type", self.index["fields_other"])

    def test_xml_records_are_counted(self):
        self.assertEqual(self.index["xml_new"], 1)
        self.assertEqual(self.index["xml_del"], 2)


class TestClassify(unittest.TestCase):
    def test_new_with_details_is_still_new(self):
        self.assertEqual(
            oa.classify("NEW relation: res.company, required"), "new"
        )

    def test_not_stored_is_not_confused_with_stored(self):
        # « not stored anymore » CONTIENT « stored » : tester par
        # appartenance de sous-chaîne inverserait le sens.
        self.assertEqual(oa.classify("not stored anymore"), "unstored")
        self.assertEqual(oa.classify("is now stored"), "stored")

    def test_an_unknown_wording_falls_back_to_other(self):
        self.assertEqual(oa.classify("something brand new"), "other")


class TestFindingTheFiles(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        base = os.path.join(
            self.racine,
            "odoo18.0",
            "OCA_OpenUpgrade",
            "openupgrade_scripts",
            "scripts",
        )
        for module, release in (
            ("account", "18.0.1.0"),
            ("account", "17.0.1.0"),
            ("sale", "18.0.2.0"),
            ("tests", "18.0.1.0"),
        ):
            dossier = os.path.join(base, module, release)
            os.makedirs(dossier)
            with open(
                os.path.join(dossier, "upgrade_analysis.txt"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(EXEMPLE)

    def tearDown(self):
        shutil.rmtree(self.racine)

    def test_only_the_target_version_is_read(self):
        # À côté des `18.0.x` vivent des dossiers d'autres paliers : les
        # mélanger attribuerait à la 18 des changements de la 17.
        trouves = oa.analysis_files(18, self.racine)
        self.assertTrue(all("18.0" in c for c in trouves), trouves)
        self.assertEqual(len(trouves), 3)

    def test_a_missing_checkout_is_empty_not_a_crash(self):
        self.assertEqual(oa.analysis_files(13, self.racine), [])
        self.assertEqual(oa.load(13, self.racine)["modules"], 0)

    def test_the_module_list_comes_from_the_directories(self):
        modules = oa.analysed_modules(18, self.racine)
        self.assertIn("account", modules)
        self.assertIn("sale", modules)

    def test_loading_counts_the_modules_it_read(self):
        self.assertEqual(oa.load(18, self.racine)["modules"], 3)


class TestTheRealCheckout(unittest.TestCase):
    """Le dépôt lui-même, quand il est là. Sinon on ne prétend rien."""

    def setUp(self):
        if not oa.analysis_files(18):
            self.skipTest("OCA_OpenUpgrade absent du checkout 18.0")

    def test_it_reads_hundreds_of_core_modules(self):
        index = oa.load(18)
        self.assertGreater(index["modules"], 300)

    def test_it_finds_the_company_dependent_conversion(self):
        # C'est la refonte qui a fait disparaître `ir_property` en 18 :
        # si l'outil ne la voit pas, il ne sert à rien sur ce palier-là.
        index = oa.load(18)
        self.assertTrue(
            any(
                cle.startswith("account.cash.rounding.")
                for cle in index["fields_company_dependent"]
            ),
            sorted(index["fields_company_dependent"])[:5],
        )


if __name__ == "__main__":
    unittest.main()
