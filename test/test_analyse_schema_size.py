#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Poids du schéma : ce qui se teste sans base.

Le classement d'une table (modèle / m2m / système / orpheline) vit dans
`collect()`, qui interroge PostgreSQL. Il s'éprouve sur la base synthétique
décrite dans le docstring de `test_analyse_lib.py`, augmentée des quatre cas
qui comptent : une table m2m sans ligne `ir_model` mais listée dans
`ir_model_relation`, un modèle à `_table` surchargé, un modèle abstrait, et
une vraie orpheline. Attendu : une seule orpheline, la vraie.

Ici, les fonctions pures — mise en forme et rendu. `render()` est une
fonction de la donnée vers le texte, donc tout le rapport se teste sur un
dictionnaire écrit à la main.
"""

import unittest

from script.analyse import analyse_schema_size as A
from script.todo import todo_i18n


def fixture(**override):
    """Un résultat de collect() minimal, que chaque test tord à sa guise."""
    data = {
        "tool": "analyse_schema_size",
        "version": 1,
        "database": "prod_18",
        "odoo_version": "18.0.1.3",
        "db_bytes": 12884901888,
        "exact": False,
        "has_relation_table": True,
        "n_tables": 3,
        "n_models": 4,
        "tables": [
            {
                "table_name": "mail_message",
                "total_bytes": 3221225472,
                "table_bytes": 2254857830,
                "index_bytes": 943718400,
                "est_rows": 4183221,
                "exact_rows": None,
                "model": "mail.message",
                "origin": "model",
            },
            {
                "table_name": "res_groups_users_rel",
                "total_bytes": 16384,
                "table_bytes": 8192,
                "index_bytes": 8192,
                "est_rows": -1,
                "exact_rows": None,
                "model": None,
                "origin": "m2m",
            },
            {
                "table_name": "old_module_thing",
                "total_bytes": 431916544,
                "table_bytes": 400000000,
                "index_bytes": 31916544,
                "est_rows": 90211,
                "exact_rows": None,
                "model": None,
                "origin": "orphan",
            },
        ],
        "orphan_tables": [],
        "models_without_table": [],
        "counts": {
            "orphan_tables": 0,
            "models_without_table": 0,
            "m2m_tables": 1,
        },
    }
    data["orphan_tables"] = [
        r for r in data["tables"] if r["origin"] == "orphan"
    ]
    data["counts"]["orphan_tables"] = len(data["orphan_tables"])
    data.update(override)
    return data


class TestFmtBytes(unittest.TestCase):
    def test_zero_and_bytes_have_no_decimal(self):
        self.assertEqual(A.fmt_bytes(0), "0 B")
        self.assertEqual(A.fmt_bytes(512), "512 B")

    def test_scales_to_binary_units(self):
        self.assertEqual(A.fmt_bytes(1024), "1.0 KiB")
        self.assertEqual(A.fmt_bytes(1024**2), "1.0 MiB")
        self.assertEqual(A.fmt_bytes(1024**3), "1.0 GiB")
        self.assertEqual(A.fmt_bytes(1024**4), "1.0 TiB")

    def test_beyond_tebibyte_stays_in_tebibytes(self):
        self.assertEqual(A.fmt_bytes(5 * 1024**4), "5.0 TiB")

    def test_none_is_a_question_mark(self):
        self.assertEqual(A.fmt_bytes(None), "?")


class TestFmtRows(unittest.TestCase):
    def test_never_analyzed_is_not_zero(self):
        # PostgreSQL >= 14 met reltuples à -1 quand aucun ANALYZE n'a tourné.
        # Afficher « 0 » ferait passer une table pleine pour une table vide.
        self.assertEqual(A.fmt_rows(-1), "?")
        self.assertEqual(A.fmt_rows(None), "?")

    def test_zero_stays_zero(self):
        # Une table réellement vide et analysée doit dire 0, pas « ? ».
        self.assertEqual(A.fmt_rows(0), "0")

    def test_groups_thousands_with_spaces(self):
        self.assertEqual(A.fmt_rows(4183221), "4 183 221")


class TestWrapNote(unittest.TestCase):
    def test_short_text_is_one_line(self):
        self.assertEqual(A.wrap_note("  ", "court"), ["  court"])

    def test_continuation_lines_align_under_the_first(self):
        lines = A.wrap_note("  💡 ", "mot " * 40)
        self.assertGreater(len(lines), 1)
        self.assertTrue(lines[0].startswith("  💡 "))
        for line in lines[1:]:
            self.assertTrue(line.startswith(" " * len("  💡 ")), repr(line))

    def test_respects_the_width(self):
        for line in A.wrap_note("  ", "mot " * 60, width=50):
            self.assertLessEqual(len(line), 50, repr(line))

    def test_empty_text_does_not_crash(self):
        self.assertEqual(A.wrap_note("  ", ""), ["  "])


class TestRender(unittest.TestCase):
    """Le rapport, sur une donnée écrite à la main.

    `set_lang` est fixé : `_current_lang` est un état de module alimenté par
    une préférence utilisateur, donc sans cela le test dépendrait de la langue
    de la machine.
    """

    def setUp(self):
        todo_i18n.set_lang("en")
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_reports_the_orphan_and_not_the_m2m(self):
        # Le faux positif à éviter : une table m2m n'a aucune ligne ir_model,
        # et sur une base ordinaire il y en a des centaines.
        out = A.render(fixture())
        self.assertIn("Orphan tables (1)", out)
        orphan_block = out.split("Orphan tables")[1]
        self.assertIn("old_module_thing", orphan_block)
        self.assertNotIn("res_groups_users_rel", orphan_block)

    def test_no_orphan_says_so_plainly(self):
        data = fixture(orphan_tables=[])
        data["counts"]["orphan_tables"] = 0
        out = A.render(data)
        self.assertIn("Every table belongs to an installed model.", out)
        self.assertNotIn("Orphan tables", out)

    def test_models_without_table_is_a_fact_not_a_finding(self):
        # Les modèles abstraits sont dans ir_model et n'ont pas de table : des
        # centaines sur une base ordinaire. La ligne doit l'expliquer.
        data = fixture(models_without_table=[{"model": "mail.thread"}])
        data["counts"]["models_without_table"] = 1
        out = A.render(data)
        self.assertIn("Models without table", out)
        self.assertIn("abstract models have none", out)

    def test_models_without_table_line_is_absent_when_zero(self):
        self.assertNotIn("Models without table", A.render(fixture()))

    def test_warns_when_m2m_cannot_be_told_apart(self):
        # Sans ir_model_relation, chaque table m2m passerait pour orpheline :
        # le rapport doit dire qu'il n'est pas fiable, pas se taire.
        out = A.render(fixture(has_relation_table=False))
        self.assertIn("ir_model_relation is absent", out)

    def test_estimate_warning_only_without_exact(self):
        self.assertIn("estimates from the last ANALYZE", A.render(fixture()))
        self.assertNotIn(
            "estimates from the last ANALYZE",
            A.render(fixture(exact=True)),
        )

    def test_top_limits_the_table_list(self):
        out = A.render(fixture(), top=1)
        self.assertIn("Heaviest tables (1/3)", out)
        self.assertIn("use -v to list them all", out)

    def test_verbose_lists_everything(self):
        out = A.render(fixture(), verbose=True)
        self.assertIn("All tables, heaviest first", out)
        self.assertNotIn("use -v to list them all", out)

    def test_never_analyzed_shows_a_question_mark(self):
        out = A.render(fixture(), verbose=True)
        row = [l for l in out.splitlines() if "res_groups_users_rel" in l][0]
        self.assertTrue(row.rstrip().endswith("?"), repr(row))

    def test_unknown_odoo_version_does_not_crash(self):
        self.assertIn("Odoo ?", A.render(fixture(odoo_version=None)))

    def test_french_differs_from_english(self):
        english = A.render(fixture())
        todo_i18n.set_lang("fr")
        french = A.render(fixture())
        self.assertIn("Tables orphelines", french)
        self.assertNotEqual(english, french)


if __name__ == "__main__":
    unittest.main()
