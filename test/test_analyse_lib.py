#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Socle d'analyse : ce qui se teste SANS base de données.

Tout ici est une fonction pure ou une fonction dont le seul effet est de
construire du SQL ou un environnement. C'est délibéré : ces tests doivent
tourner sur une machine sans PostgreSQL, donc dans la suite du dépôt.

Ce qui exige une vraie base — `require_odoo_database`, `database_version`,
`existing_columns`, `column_types`, `public_tables` — n'est pas ici : le test
ne peut pas fabriquer sa base, puisque créer une base est une écriture et que
l'outillage est en lecture seule par construction.

Ces cinq fonctions s'éprouvent à la main sur une base synthétique, ce qui
prend une minute et n'exige aucun Odoo installé :

    createdb erplibre_analyse_selftest
    psql -d erplibre_analyse_selftest -c "
      CREATE TABLE ir_module_module (id serial PRIMARY KEY, name varchar,
        state varchar, latest_version varchar);
      INSERT INTO ir_module_module (name, state, latest_version)
        VALUES ('base', 'installed', '18.0.1.3');
      -- arch_db en jsonb : la forme >= 16.0. Le « | » et le saut de ligne
      -- sont là exprès : ils prouvent que json_query ne coupe pas dessus.
      CREATE TABLE ir_ui_view (id serial PRIMARY KEY, name jsonb,
        arch_db jsonb, website_id integer, arch_fs varchar);
      INSERT INTO ir_ui_view (name, arch_db) VALUES
        ('{\"en_US\":\"Avec un | et un saut\\nde ligne\"}',
         '{\"en_US\":\"<form/>\"}');
      -- une colonne text : la forme <= 15.0, pour éprouver tr_col des deux côtés
      CREATE TABLE res_partner (id serial PRIMARY KEY, ref text);
      -- table dont le nom NE dérive PAS du modèle ir.actions.act_window
      CREATE TABLE ir_act_window (id serial PRIMARY KEY, res_model varchar);"

Attendu : `database_version` rend « 18.0.1.3 » ; `column_types` distingue
`jsonb` de `text` ; `tr_col` produit `->>'en_US'` d'un côté et `::text` de
l'autre ; `model_table('ir.actions.act_window')` rend `ir_act_window` ;
`require_odoo_database` refuse une base sans `ir_module_module` ; et un
`CREATE TABLE` passé à `run_psql` est refusé par le serveur, pas par nous.
Puis `dropdb erplibre_analyse_selftest`.
"""

import os
import tempfile
import unittest

from script.analyse import lib_analyse as L
from script.todo import todo_i18n


class TestValidDatabaseName(unittest.TestCase):
    def test_accepts_real_names(self):
        for name in ("test", "prod_18", "client.prod", "a-b_c.1"):
            self.assertTrue(L.valid_database_name(name), name)

    def test_rejects_a_traceback_line(self):
        # Le cas qui a motivé le contrôle : un PostgreSQL injoignable faisait
        # remonter sa trace d'appel comme si c'était une liste de bases.
        self.assertFalse(
            L.valid_database_name("Traceback (most recent call last):")
        )

    def test_rejects_shell_injection(self):
        for name in ("a; DROP DATABASE b", "a b", "$(id)", "a|b", "a'b"):
            self.assertFalse(L.valid_database_name(name), name)

    def test_rejects_empty(self):
        self.assertFalse(L.valid_database_name(""))
        self.assertFalse(L.valid_database_name(None))


class TestReadConfig(unittest.TestCase):
    def _write(self, body):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_reads_the_options_section(self):
        path = self._write("[options]\ndb_user = erplibre\ndb_port = 5433\n")
        config = L.read_config(path)
        self.assertEqual(config["db_user"], "erplibre")
        self.assertEqual(config["db_port"], "5433")

    def test_missing_file_is_not_an_error(self):
        # Sur une installation native, psql se connecte par le socket unix sans
        # aucun paramètre : l'absence de config est un cas normal.
        self.assertEqual(L.read_config("/nowhere/absent.conf"), {})

    def test_file_without_options_section(self):
        path = self._write("[other]\nfoo = bar\n")
        self.assertEqual(L.read_config(path), {})


class TestPgEnv(unittest.TestCase):
    def _write(self, body):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_read_only_and_timeout_are_always_set(self):
        env = L.pg_env("/nowhere/absent.conf", timeout=42)
        self.assertIn("default_transaction_read_only=on", env["PGOPTIONS"])
        self.assertIn("statement_timeout=42s", env["PGOPTIONS"])

    def test_psqlrc_is_neutralised(self):
        # Un ~/.psqlrc avec \timing ajoute des lignes à la sortie et casse le
        # parsing JSON.
        self.assertEqual(L.pg_env("/nowhere/absent.conf")["PSQLRC"], "")

    def test_config_values_become_pg_variables(self):
        path = self._write(
            "[options]\ndb_host = pg.example.org\ndb_port = 5433\n"
            "db_user = erplibre\ndb_password = s3cret\ndb_sslmode = require\n"
        )
        env = L.pg_env(path)
        self.assertEqual(env["PGHOST"], "pg.example.org")
        self.assertEqual(env["PGPORT"], "5433")
        self.assertEqual(env["PGUSER"], "erplibre")
        self.assertEqual(env["PGPASSWORD"], "s3cret")
        self.assertEqual(env["PGSSLMODE"], "require")

    def test_literal_false_means_unset(self):
        # Odoo écrit « False » dans config.conf pour dire « pas de valeur ».
        # L'exporter tel quel ferait chercher un hôte nommé « False ».
        path = self._write(
            "[options]\ndb_host = False\ndb_port = False\n"
            "db_password = False\ndb_user = erplibre\n"
        )
        env = L.pg_env(path)
        self.assertNotIn("PGHOST", env)
        self.assertNotIn("PGPORT", env)
        self.assertNotIn("PGPASSWORD", env)
        self.assertEqual(env["PGUSER"], "erplibre")

    def test_overrides_win_over_the_config(self):
        path = self._write("[options]\ndb_host = pg.example.org\n")
        env = L.pg_env(path, overrides={"PGHOST": "127.0.0.1"})
        self.assertEqual(env["PGHOST"], "127.0.0.1")


class TestQuoteLiteral(unittest.TestCase):
    def test_wraps_in_single_quotes(self):
        self.assertEqual(L.quote_literal("ir_ui_view"), "'ir_ui_view'")

    def test_doubles_embedded_quotes(self):
        self.assertEqual(L.quote_literal("a'b"), "'a''b'")


class TestTrCol(unittest.TestCase):
    """Le fragment SQL d'un champ traduit, décidé sur le TYPE réel.

    Pas sur un numéro de version : une base à moitié migrée porte les deux
    formes, et un numéro de version mentirait.
    """

    def test_jsonb_column_is_unpacked(self):
        # La forme >= 16.0 : {"en_US": "..."}
        got = L.tr_col("ir_ui_view", "arch_db", {"arch_db": "jsonb"})
        self.assertEqual(got, '"ir_ui_view"."arch_db"->>\'en_US\'')

    def test_text_column_is_cast(self):
        # La forme <= 15.0 : du texte
        got = L.tr_col("ir_ui_view", "arch_db", {"arch_db": "text"})
        self.assertEqual(got, '"ir_ui_view"."arch_db"::text')

    def test_character_varying_is_cast_too(self):
        got = L.tr_col("ir_model", "name", {"name": "character varying"})
        self.assertEqual(got, '"ir_model"."name"::text')

    def test_unknown_column_yields_null_not_broken_sql(self):
        # Une colonne absente doit donner un champ vide, pas une requête qui
        # explose : c'est ce qui permet de sonder puis d'interroger d'un trait.
        self.assertEqual(L.tr_col("ir_ui_view", "absente", {}), "NULL::text")
        self.assertEqual(L.tr_col("ir_ui_view", "absente", None), "NULL::text")

    def test_other_language(self):
        got = L.tr_col("ir_model", "name", {"name": "jsonb"}, lang="fr_CA")
        self.assertEqual(got, '"ir_model"."name"->>\'fr_CA\'')


class TestModelTable(unittest.TestCase):
    def test_default_derivation(self):
        self.assertEqual(L.model_table("res.partner"), "res_partner")

    def test_override_is_applied(self):
        # replace('.', '_') donnerait ir_actions_act_window, qui n'existe pas.
        self.assertEqual(
            L.model_table("ir.actions.act_window"), "ir_act_window"
        )

    def test_unknown_table_returns_none_not_a_guess(self):
        # None veut dire « je ne sais pas », jamais « il n'y en a pas » : c'est
        # ce qui empêche de classer un modèle abstrait comme une anomalie.
        self.assertIsNone(
            L.model_table("mail.thread", known_tables={"res_partner"})
        )

    def test_known_table_passes_through(self):
        self.assertEqual(
            L.model_table("res.partner", known_tables={"res_partner"}),
            "res_partner",
        )


class TestModelTableOverrideIntegrity(unittest.TestCase):
    """La table de surcharges ne doit pas accumuler d'entrées inutiles.

    Beaucoup de modules déclarent un `_table` égal au défaut. Recopier une
    telle déclaration ici serait du poids mort qui donne l'illusion d'une
    surcharge — et c'est exactement la confusion qui a fait annoncer 22
    surcharges là où il y en a 11.
    """

    def test_no_entry_equals_the_default(self):
        for model, table in L.MODEL_TABLE_OVERRIDE.items():
            self.assertNotEqual(
                table,
                model.replace(".", "_"),
                f"'{model}' n'est pas une surcharge : son _table est le défaut",
            )

    def test_tables_look_like_table_names(self):
        for model, table in L.MODEL_TABLE_OVERRIDE.items():
            self.assertRegex(table, r"^[a-z][a-z0-9_]*$", model)


class TestJsonQuery(unittest.TestCase):
    """L'enveloppe json_agg, sans base : on intercepte run_psql."""

    def setUp(self):
        self.seen = []
        self.reply = "[]"
        self.original = L.run_psql

        def fake_run_psql(database, sql, **kwargs):
            self.seen.append((database, sql))
            return self.reply

        L.run_psql = fake_run_psql
        self.addCleanup(setattr, L, "run_psql", self.original)

    def test_wraps_the_select(self):
        L.json_query("db", "SELECT id FROM ir_ui_view")
        _, sql = self.seen[0]
        self.assertIn("json_agg(row_to_json(t))", sql)
        self.assertIn("FROM (SELECT id FROM ir_ui_view) t", sql)

    def test_strips_a_trailing_semicolon(self):
        # Un « ; » resté dans la sous-requête produirait du SQL invalide.
        L.json_query("db", "SELECT id FROM ir_ui_view;")
        _, sql = self.seen[0]
        self.assertNotIn(";) t", sql)

    def test_empty_output_is_an_empty_list(self):
        self.reply = "   \n"
        self.assertEqual(L.json_query("db", "SELECT 1"), [])

    def test_pipes_and_newlines_survive(self):
        # La raison d'être de l'enveloppe : une arch XML contient des « | » et
        # des sauts de ligne, donc tout séparateur maison couperait au mauvais
        # endroit.
        self.reply = '[{"arch": "a | b\\nc"}]'
        rows = L.json_query("db", "SELECT 1")
        self.assertEqual(rows, [{"arch": "a | b\nc"}])

    def test_unreadable_output_raises_analyse_error(self):
        self.reply = "ERREUR: quelque chose"
        with self.assertRaises(L.AnalyseError):
            L.json_query("db", "SELECT 1")


class TestRunPsqlGuards(unittest.TestCase):
    """`_current_lang` est un état de MODULE, pas un état de test.

    Ce test passait seul et tombait dans la suite : un autre fichier avait
    laissé la langue en français, et le message n'est traduit que depuis
    qu'une traduction existe. Toute assertion sur un texte affiché doit donc
    fixer la langue, sinon elle dépend de l'ordre des tests.
    """

    def setUp(self):
        # PAS `set_lang()` : il PERSISTE la langue dans ./env_var.sh, un
        # fichier suivi par git. Un test qui l'appelle modifie l'arbre de
        # travail et laisse la langue changée pour tout ce qui suit —
        # `_current_lang = None` ne défait que la mémoïsation, pas le
        # fichier, et la résolution suivante relit celui-ci. On écrit donc
        # la mémoïsation directement, et on rend la valeur trouvée.
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_hostile_database_name_never_reaches_psql(self):
        with self.assertRaises(L.AnalyseError) as caught:
            L.run_psql("a; DROP DATABASE b", "SELECT 1;")
        self.assertIn("Invalid database name", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TestCanonical(unittest.TestCase):
    """Ce qui décide s'il y a un écart. Le bruit se joue ici."""

    def test_indentation_is_not_a_change(self):
        # Le cas mesuré sur une vraie base : une arch ré-indentée n'est pas
        # une modification, et c'est l'erreur que fait `has_diff` d'Odoo —
        # une comparaison de chaînes brutes — dans son propre assistant.
        left = "<form><field name='a'/></form>"
        right = "<form>\n    <field name='a'/>\n</form>"
        self.assertEqual(L.canonical(left), L.canonical(right))
        self.assertEqual(L.arch_differs(left, right), (False, True))

    def test_attribute_order_is_not_a_change(self):
        self.assertEqual(
            L.canonical("<t a='1' b='2'/>"), L.canonical("<t b='2' a='1'/>")
        )

    def test_comments_are_not_a_change(self):
        self.assertEqual(
            L.canonical("<form><!-- note --><field/></form>"),
            L.canonical("<form><field/></form>"),
        )

    def test_an_added_field_is_a_change(self):
        left = "<form><field name='a'/></form>"
        right = "<form><field name='a'/><field name='x_custom'/></form>"
        self.assertEqual(L.arch_differs(left, right), (True, True))

    def test_changed_text_is_a_change(self):
        # L'espace DANS un libellé est du contenu, pas de la mise en forme.
        self.assertEqual(
            L.arch_differs("<t>Total</t>", "<t>Grand total</t>"), (True, True)
        )

    def test_xpath_expression_spacing_is_normalised(self):
        # L'espace y sépare des jetons : il se replie, il ne disparaît pas.
        self.assertEqual(
            L.canonical('<xpath expr="//div[1]  /span"/>'),
            L.canonical('<xpath expr="//div[1] /span"/>'),
        )

    def test_a_different_xpath_target_is_a_change(self):
        self.assertNotEqual(
            L.canonical('<xpath expr="//div/span"/>'),
            L.canonical('<xpath expr="//div[1]/span"/>'),
        )

    def test_broken_xml_is_not_comparable(self):
        # Ni « identique » ni « différent » : une comparaison qui n'a pas eu
        # lieu ne doit pas se lire comme une comparaison sans écart.
        self.assertIsNone(L.canonical("<form><field></form>"))
        self.assertEqual(
            L.arch_differs("<form/>", "<form><field>"), (None, False)
        )

    def test_empty_arch_is_not_comparable(self):
        self.assertIsNone(L.canonical(""))
        self.assertIsNone(L.canonical(None))

    def test_jsonb_column_is_unwrapped_first(self):
        self.assertEqual(
            L.canonical('{"en_US": "<form/>"}'), L.canonical("<form/>")
        )


class TestSideBySide(unittest.TestCase):
    def test_identical_lines_are_aligned(self):
        rows = L.side_by_side("a\nb", "a\nb")
        self.assertEqual([mark for mark, _, _ in rows], [" ", " "])

    def test_insert_has_no_left_side(self):
        rows = L.side_by_side("a", "a\nb")
        self.assertEqual(rows[-1], ("+", None, "b"))

    def test_delete_has_no_right_side(self):
        rows = L.side_by_side("a\nb", "a")
        self.assertEqual(rows[-1], ("-", "b", None))

    def test_replace_keeps_both_sides_on_one_row(self):
        # Le point de l'affichage côte à côte : les deux versions d'une même
        # ligne se lisent l'une en face de l'autre, sans rien à synchroniser.
        rows = L.side_by_side("a", "b")
        self.assertEqual(rows, [("≠", "a", "b")])

    def test_stats_count_each_kind(self):
        rows = L.side_by_side("a\nb\nc", "a\nB\nc\nd")
        self.assertEqual(
            L.diff_stats(rows), {"added": 1, "removed": 0, "changed": 1}
        )


class TestUnescapeCopy(unittest.TestCase):
    r"""Les valeurs d'un bloc COPY d'un dump.sql.

    C'est ce qui permet de lire une sauvegarde sans la restaurer. Une erreur
    ici corrompt silencieusement une valeur — un « \n » laissé littéral dans
    une aide de champ, un NULL pris pour la chaîne « \N ».
    """

    def test_backslash_n_is_null_not_a_string(self):
        self.assertIsNone(L.unescape_copy("\\N"))
        # Mais « \N » AU MILIEU d'une valeur reste du texte.
        self.assertEqual(L.unescape_copy("a\\Nb"), "aNb")

    def test_plain_value_passes_through(self):
        self.assertEqual(L.unescape_copy("x_studio_code"), "x_studio_code")
        self.assertEqual(L.unescape_copy(""), "")

    def test_newline_and_tab_are_restored(self):
        # Une aide de champ multi-lignes arrive échappée : la laisser telle
        # quelle mettrait « \n » littéral dans le rapport.
        self.assertEqual(L.unescape_copy("a\\nb"), "a\nb")
        self.assertEqual(L.unescape_copy("a\\tb"), "a\tb")
        self.assertEqual(L.unescape_copy("a\\rb"), "a\rb")

    def test_escaped_backslash(self):
        self.assertEqual(L.unescape_copy("a\\\\b"), "a\\b")

    def test_unknown_escape_keeps_the_character(self):
        self.assertEqual(L.unescape_copy("a\\qb"), "aqb")

    def test_trailing_backslash_is_not_an_index_error(self):
        self.assertEqual(L.unescape_copy("a\\"), "a\\")


class TestNotAColumn(unittest.TestCase):
    def test_constraint_lines_are_not_columns(self):
        # Un CREATE TABLE mêle colonnes et contraintes ; prendre le premier
        # mot d'une ligne CONSTRAINT donnerait une colonne qui n'existe pas,
        # et un champ x_ passerait pour ayant sa colonne.
        for word in ("CONSTRAINT", "PRIMARY", "CHECK", "FOREIGN", "UNIQUE"):
            self.assertTrue(f"{word} foo".upper().startswith(L.NOT_A_COLUMN))
        self.assertFalse(
            "name character varying".upper().startswith(L.NOT_A_COLUMN)
        )
