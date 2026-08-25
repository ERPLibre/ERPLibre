#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les index qu'Odoo 17 a créés en double et n'a jamais retirés.

`make_index_name` rend `{table}__{colonne}_index` depuis la 17 — deux
soulignés — là où les versions d'avant écrivaient un seul. Le nouvel
index est créé, l'ancien reste. Mesuré sur une chaîne 12 → 18 : 1 paire
en 12, 3 en 16, 370 en 17, 365 en 18.

Ce qui compte ici n'est pas de supprimer, c'est de S'ABSTENIR au bon
endroit. Éprouvé sur une copie de la base réelle : 364 index retirés,
10 Mo libérés, les 6301 contraintes identiques au nom près, Odoo charge
sans une ligne de journal, et un « -u all » complet n'en recrée aucun.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.odoo.migration import fix_duplicate_index as idx  # noqa: E402


def paire(table, a, b, a_ctr=False, b_ctr=False, a_size=100, b_size=90):
    return {
        "table": table,
        "a": a,
        "a_size": a_size,
        "a_ctr": a_ctr,
        "b": b,
        "b_size": b_size,
        "b_ctr": b_ctr,
    }


class TestTheNamingConvention(unittest.TestCase):
    def test_the_modern_name_carries_two_underscores(self):
        # `make_index_name` d'Odoo 18 : f"{table}__{colonne}_index".
        self.assertTrue(
            idx.modern_name("res_partner", "res_partner__name_index")
        )

    def test_the_legacy_name_does_not(self):
        self.assertFalse(
            idx.modern_name("res_partner", "res_partner_name_index")
        )

    def test_a_name_from_another_table_is_not_modern_here(self):
        self.assertFalse(
            idx.modern_name("res_partner", "res_users__name_index")
        )


class TestWhatItAgreesToDrop(unittest.TestCase):
    def test_it_keeps_the_modern_one_and_drops_the_legacy_one(self):
        verdict, garder, supprimer = idx.classify(
            paire(
                "res_partner",
                "res_partner__name_index",
                "res_partner_name_index",
            )
        )
        self.assertEqual("safe", verdict)
        self.assertEqual("res_partner__name_index", garder)
        self.assertEqual("res_partner_name_index", supprimer)

    def test_the_order_of_the_pair_does_not_decide(self):
        # PostgreSQL rend les deux dans l'ordre de leur oid : se fier à
        # « le premier » supprimerait le moderne une fois sur deux.
        verdict, garder, _s = idx.classify(
            paire(
                "res_partner",
                "res_partner_name_index",
                "res_partner__name_index",
            )
        )
        self.assertEqual("safe", verdict)
        self.assertEqual("res_partner__name_index", garder)


class TestWhatItRefusesToTouch(unittest.TestCase):
    """S'abstenir est le cœur de cet outil, pas supprimer."""

    def test_an_index_backing_a_constraint_is_left_alone(self):
        # PostgreSQL le recréerait, ou la contrainte tomberait avec lui.
        for a_ctr, b_ctr in ((True, False), (False, True), (True, True)):
            with self.subTest(a=a_ctr, b=b_ctr):
                verdict, garder, supprimer = idx.classify(
                    paire("m", "m__x_index", "m_x_index", a_ctr, b_ctr)
                )
                self.assertEqual("constraint", verdict)
                self.assertIsNone(supprimer)

    def test_two_legacy_names_are_a_human_decision(self):
        verdict, _g, supprimer = idx.classify(
            paire(
                "mail_notification",
                "mail_notification_email_status_index",
                "mail_notification_notification_status_ind",
            )
        )
        self.assertEqual("ambiguous", verdict)
        self.assertIsNone(supprimer)

    def test_two_modern_names_are_a_human_decision(self):
        # Vu en vrai : deux noms tronqués et suffixés d'un condensat, ou
        # deux colonnes différentes tombées sur le même rang. On ne devine
        # pas lequel Odoo recréera.
        verdict, _g, supprimer = idx.classify(
            paire(
                "stock_move",
                "stock_move__location_dest_id_index",
                "stock_move__location_final_id_index",
            )
        )
        self.assertEqual("ambiguous", verdict)
        self.assertIsNone(supprimer)


class TestTheQueryItself(unittest.TestCase):
    """Les gardes vivent dans le SQL ; les retirer ne se verrait pas."""

    def test_it_ignores_partial_and_computed_indexes(self):
        # Deux index sur les mêmes colonnes n'y font pas le même travail.
        self.assertIn("indpred IS NULL", idx.DETECTION)
        self.assertIn("indexprs IS NULL", idx.DETECTION)

    def test_it_never_looks_at_a_primary_key(self):
        self.assertIn("NOT i.indisprimary", idx.DETECTION)

    def test_it_compares_the_access_method(self):
        # Un gin et un btree sur la même colonne ne se remplacent pas.
        self.assertIn("amname", idx.DETECTION)
        self.assertIn("a.methode  = b.methode", idx.DETECTION)

    def test_it_compares_the_operator_classes(self):
        self.assertIn("indclass", idx.DETECTION)
        self.assertIn("a.classes  = b.classes", idx.DETECTION)

    def test_it_compares_uniqueness(self):
        self.assertIn("a.unique_  = b.unique_", idx.DETECTION)

    def test_it_only_looks_at_valid_indexes(self):
        self.assertIn("i.indisvalid", idx.DETECTION)

    def test_it_pairs_each_couple_once(self):
        # Sans cela chaque paire sortirait deux fois, et le compte
        # annoncé serait le double du vrai.
        self.assertIn("a.indexrelid < b.indexrelid", idx.DETECTION)


class TestTheSqlItWrites(unittest.TestCase):
    def lot(self):
        return [
            ("safe", "m", "m__a_index", "m_a_index", 100, {}),
            ("safe", "m", "m__b_index", "m_b_index", 100, {}),
            ("constraint", "m", None, None, 0, {}),
            ("ambiguous", "m", None, None, 0, {}),
        ]

    def test_it_only_drops_what_it_called_safe(self):
        sql = idx.drop_sql(self.lot())
        self.assertEqual(2, sql.count("DROP INDEX"), sql)
        self.assertIn("m_a_index", sql)
        self.assertIn("m_b_index", sql)

    def test_a_named_but_unsafe_entry_is_still_not_dropped(self):
        # `classify` rend aujourd'hui (None, None) pour tout ce qui n'est
        # pas sûr, ce qui masque la garde. Le jour où il nommera les
        # ambiguës pour les AFFICHER, `drop_sql` ne doit pas se mettre à
        # les supprimer : c'est le verdict qui décide, pas la présence
        # d'un nom.
        lot = [
            ("ambiguous", "m", "m__a_index", "m_a_index", 100, {}),
            ("constraint", "m", "m__b_index", "m_b_index", 100, {}),
        ]
        self.assertEqual("", idx.drop_sql(lot))

    def test_it_never_drops_what_it_keeps(self):
        sql = idx.drop_sql(self.lot())
        self.assertNotIn('"m__a_index"', sql)

    def test_it_tolerates_an_index_already_gone(self):
        # Une table à trois copies produit deux paires nommant le même
        # index à supprimer ; la seconde passe ne doit pas échouer.
        self.assertIn("IF EXISTS", idx.drop_sql(self.lot()))

    def test_the_same_index_is_dropped_once(self):
        lot = [
            ("safe", "m", "m__a_index", "m_a_index", 100, {}),
            ("safe", "m", "m__a2_index", "m_a_index", 100, {}),
        ]
        self.assertEqual(1, idx.drop_sql(lot).count("DROP INDEX"))

    def test_nothing_safe_writes_nothing(self):
        self.assertEqual(
            "", idx.drop_sql([("constraint", "m", None, None, 0, {})])
        )


class TestTheReport(unittest.TestCase):
    def test_a_clean_database_says_so(self):
        self.assertIn("✅", "\n".join(idx.render([])))

    def test_it_separates_the_safe_from_the_rest(self):
        lot = [
            ("safe", "m", "m__a_index", "m_a_index", 16384, {}),
            (
                "constraint",
                "m",
                None,
                None,
                0,
                {"a": "x_uniq", "b": "name_uniq"},
            ),
        ]
        texte = "\n".join(idx.render(lot))
        self.assertIn("m_a_index", texte)
        self.assertIn("name_uniq", texte)
        self.assertIn("2", texte)

    def test_it_offers_the_flag_only_when_there_is_work(self):
        rien = [("constraint", "m", None, None, 0, {"a": "x", "b": "y"})]
        self.assertNotIn("--apply", "\n".join(idx.render(rien)))
        travail = [("safe", "m", "m__a_index", "m_a_index", 0, {})]
        self.assertIn("--apply", "\n".join(idx.render(travail)))


if __name__ == "__main__":
    unittest.main()
