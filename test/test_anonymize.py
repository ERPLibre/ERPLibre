#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Anonymiser : ce qui compte, c'est ce qu'on REFUSE de toucher.

Remplacer des mots est facile. Ce qui casse une base, c'est de croire que
« tous les champs string » veut dire quelque chose. Mesuré sur une base
réelle en 18 : 505 champs `selection` sont stockés en varchar
(`res.partner.lang`, `sale.order.invoice_status`), 2693 many2one sont des
entiers, 194 textes sont des `jsonb` par langue, et 301 contraintes
d'unicité attendent une collision.

Trois de ces pièges ont été trouvés en LANÇANT l'outil sur une copie
jetable, pas en le relisant : PostgreSQL refuse d'indexer un
`ARRAY[...]` sans parenthèses, `res_partner.credit_limit` est un jsonb
alors qu'Odoo l'appelle `float`, et `crm_lead.probability` porte un CHECK
qui interdit 1000. Chacun aurait fait échouer l'écriture — et l'écriture
étant transactionnelle, chaque fois la base est restée intacte. Ce
fichier fige ces trois-là pour qu'ils ne reviennent pas.

Le plancher est l'objet du premier bloc : aucun mode, aucune liste
blanche, aucune insistance ne doit permettre d'écrire dans `ir.*`.
"""

import ast
import unittest
from pathlib import Path

from script.analyse import anonymize as anon

MOTEUR = (
    Path(__file__).resolve().parent.parent
    / "script"
    / "analyse"
    / "anonymize.py"
)


def champ(
    nom,
    ttype="char",
    pg="character varying",
    unique=False,
    checked=False,
    modele="res.partner",
):
    return {
        "model": modele,
        "name": nom,
        "ttype": ttype,
        "pg_type": pg,
        "unique": unique,
        "checked": checked,
    }


class TestTheFloorNobodyCanLift(unittest.TestCase):
    """`ir.*` reste intouchable, quel que soit le chemin."""

    def test_ir_models_are_refused_even_when_whitelisted(self):
        tous = {"ir.ui.view", "ir.model.fields", "res.partner"}
        for mode in anon.MODES:
            choisis = anon.choisir_modeles(
                tous, mode, whitelist=list(tous), blacklist=[]
            )
            self.assertNotIn("ir.ui.view", choisis, mode)
            self.assertNotIn("ir.model.fields", choisis, mode)

    def test_languages_and_currencies_are_refused_too(self):
        """Ce ne sont pas des données personnelles, et les casser casse
        les adresses et les montants."""
        tous = {"res.lang", "res.currency", "res.country", "res.partner"}
        choisis = anon.choisir_modeles(tous, "whitelist", whitelist=list(tous))
        self.assertEqual(choisis, ["res.partner"])

    def test_a_blacklist_of_nothing_still_respects_the_floor(self):
        tous = {"ir.ui.view", "res.partner", "res.lang"}
        self.assertEqual(
            anon.choisir_modeles(tous, "blacklist", blacklist=[]),
            ["res.partner"],
        )


class TestWhatIsNeverReplaced(unittest.TestCase):
    """Le cœur : distinguer un vrai texte d'un varchar qui n'en est pas un."""

    def test_a_selection_stored_as_varchar_is_left_alone(self):
        """505 dans la base mesurée. Y écrire un mot casse l'ORM."""
        self.assertFalse(anon.champ_retenu(champ("lang", "selection")))
        self.assertFalse(
            anon.champ_retenu(champ("invoice_status", "selection"))
        )

    def test_a_many2one_is_left_alone(self):
        """2693 entiers qui sont des relations."""
        self.assertFalse(
            anon.champ_retenu(champ("parent_id", "many2one", "integer"))
        )

    def test_a_many2one_is_refused_by_its_type_not_only_its_name(self):
        """Sur la base mesurée, tous les many2one finissent par `_id` — mais
        un module maison peut en nommer un `owner`, et la convention ne
        peut pas être la seule barrière. C'est le TYPE qui décide."""
        self.assertFalse(
            anon.champ_retenu(champ("owner", "many2one", "integer"))
        )
        self.assertFalse(
            anon.champ_retenu(champ("responsable", "many2one", "integer"))
        )

    def test_anything_named_like_a_relation_is_left_alone(self):
        for nom in ("company_id", "tag_ids", "partner_id"):
            self.assertFalse(anon.champ_retenu(champ(nom, "integer")), nom)

    def test_a_number_living_in_a_jsonb_is_left_alone(self):
        """Mesuré : res_partner.credit_limit est un float DANS un jsonb."""
        self.assertFalse(
            anon.champ_retenu(champ("credit_limit", "float", "jsonb"))
        )

    def test_a_column_under_a_check_constraint_is_left_alone(self):
        """Mesuré : crm_lead.probability doit rester entre 0 et 100."""
        self.assertFalse(
            anon.champ_retenu(
                champ("probability", "float", "numeric", checked=True)
            )
        )

    def test_technical_columns_are_left_alone(self):
        for nom in (
            "id",
            "create_uid",
            "write_date",
            "state",
            "sequence",
            "arch_db",
            "active",
        ):
            self.assertFalse(anon.champ_retenu(champ(nom, "char")), nom)

    def test_logins_stay_unless_asked(self):
        """Sinon personne ne peut plus ouvrir la copie qu'on anonymise."""
        self.assertFalse(anon.champ_retenu(champ("login")))
        self.assertTrue(
            anon.champ_retenu(champ("login"), inclure_connexion=True)
        )

    def test_a_real_text_is_taken(self):
        for ttype in ("char", "text", "html"):
            self.assertTrue(anon.champ_retenu(champ("name", ttype)), ttype)

    def test_a_real_number_is_taken(self):
        for ttype in ("integer", "float", "monetary"):
            self.assertTrue(
                anon.champ_retenu(champ("amount", ttype, "numeric")), ttype
            )


class TestTheSqlItWrites(unittest.TestCase):
    def test_a_null_stays_null(self):
        """Un NULL devenu mot créerait de la donnée là où il n'y en avait
        pas : la copie mentirait dans l'autre sens."""
        sql = anon.expression_texte(champ("name"), ["a"])
        self.assertIn("IS NULL THEN NULL", sql)
        self.assertIn(
            "IS NULL THEN NULL",
            anon.expression_nombre(champ("x", "integer", "integer")),
        )

    def test_the_array_is_parenthesised(self):
        """PostgreSQL refuse d'indexer un ARRAY[...] nu — mesuré."""
        sql = anon.expression_texte(champ("name"), ["a", "b"])
        self.assertIn("(ARRAY[", sql)
        self.assertNotIn("] ARRAY[", sql)
        self.assertRegex(sql, r"\(ARRAY\[[^\]]*\]\)\[")

    def test_a_unique_column_gets_the_id_appended(self):
        """Deux lignes au même mot feraient échouer TOUT l'UPDATE."""
        sql = anon.expression_texte(champ("ref", unique=True), ["a"])
        self.assertIn("id::text", sql)
        self.assertNotIn(
            "id::text", anon.expression_texte(champ("ref"), ["a"])
        )

    def test_a_translated_column_is_rebuilt_key_by_key(self):
        """Écrire une chaîne dans un jsonb détruirait la colonne."""
        sql = anon.expression_texte(champ("comment", "html", "jsonb"), ["a"])
        self.assertIn("jsonb_object_agg", sql)
        self.assertIn("jsonb_each_text", sql)

    def test_a_plain_text_column_is_not_treated_as_json(self):
        sql = anon.expression_texte(champ("comment", "text", "text"), ["a"])
        self.assertNotIn("jsonb", sql)

    def test_numbers_land_between_zero_and_a_thousand(self):
        entier = anon.expression_nombre(champ("n", "integer", "integer"))
        self.assertIn("1001", entier)
        decimal = anon.expression_nombre(champ("x", "float", "numeric"))
        self.assertIn("1000", decimal)

    def test_a_word_with_a_quote_cannot_break_out(self):
        """Une liste de mots vient d'un fichier : elle n'est pas de confiance."""
        sql = anon.expression_texte(champ("name"), ["l'ete"])
        self.assertIn("'l''ete'", sql)

    def test_one_update_per_table_not_per_column(self):
        sql = anon.sql_pour_table(
            "res_partner", [champ("name"), champ("ref")], None
        )
        self.assertEqual(sql.count("UPDATE"), 1)
        self.assertTrue(sql.endswith(";"))

    def test_no_column_means_no_statement(self):
        self.assertIsNone(anon.sql_pour_table("res_partner", [], None))


class TestTheModes(unittest.TestCase):
    TOUS = {"res.partner", "crm.lead", "sale.order", "ir.ui.view"}

    def test_whitelist_takes_only_what_it_names(self):
        self.assertEqual(
            anon.choisir_modeles(self.TOUS, "whitelist", ["crm.lead"]),
            ["crm.lead"],
        )

    def test_blacklist_takes_everything_else(self):
        choisis = anon.choisir_modeles(
            self.TOUS, "blacklist", blacklist=["crm.lead"]
        )
        self.assertNotIn("crm.lead", choisis)
        self.assertIn("res.partner", choisis)

    def test_hybrid_starts_from_the_defaults_and_adjusts(self):
        choisis = anon.choisir_modeles(
            self.TOUS,
            "hybrid",
            whitelist=["sale.order"],
            blacklist=["res.partner"],
        )
        self.assertIn("sale.order", choisis)
        self.assertIn("crm.lead", choisis)  # dans les défauts
        self.assertNotIn("res.partner", choisis)  # retiré

    def test_an_unknown_mode_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            anon.choisir_modeles(self.TOUS, "peut-etre")


class TestTheWordList(unittest.TestCase):
    def test_a_flat_list_is_used_everywhere(self):
        self.assertEqual(anon.mots_pour("name", ["a", "b"]), ("a", "b"))

    def test_a_dictionary_can_answer_per_field(self):
        mots = {"email": ["a@b.c"], "*": ["mot"]}
        self.assertEqual(anon.mots_pour("email", mots), ("a@b.c",))
        self.assertEqual(anon.mots_pour("name", mots), ("mot",))

    def test_an_empty_list_falls_back_to_the_built_in(self):
        self.assertEqual(anon.mots_pour("name", []), anon.MOTS_PAR_DEFAUT)


class TestThereIsNoModelInTheLoop(unittest.TestCase):
    """« sans passer par un GPT » : vérifié sur le code, pas sur parole."""

    def test_the_engine_imports_nothing_that_could_call_out(self):
        arbre = ast.parse(MOTEUR.read_text(encoding="utf-8"))
        interdits = {
            "requests",
            "urllib",
            "urllib3",
            "http",
            "httpx",
            "socket",
            "openai",
            "anthropic",
            "xmlrpc",
            "json",
        }
        for noeud in ast.walk(arbre):
            noms = []
            if isinstance(noeud, ast.Import):
                noms = [a.name.split(".")[0] for a in noeud.names]
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms = [noeud.module.split(".")[0]]
            for nom in noms:
                self.assertNotIn(nom, interdits, nom)

    def test_the_write_is_one_transaction(self):
        """Une collision au dixième modèle laisserait une base à moitié
        anonymisée, que rien ne rattrape sinon une restauration."""
        arbre = ast.parse(MOTEUR.read_text(encoding="utf-8"))
        fonction = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef) and n.name == "ecrire"
        ]
        self.assertEqual(len(fonction), 1)
        # Le corps SANS la docstring : le texte la mentionne, l'argument
        # doit être réellement passé.
        corps = [
            n
            for n in fonction[0].body
            if not (
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
            )
        ]
        litteraux = {
            n.value
            for bloc in corps
            for n in ast.walk(bloc)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        self.assertIn("-1", litteraux)
        self.assertIn("ON_ERROR_STOP=1", litteraux)


class TestTheRefusalToWrite(unittest.TestCase):
    """Le refus doit précéder la connexion.

    Sinon ces deux tests passent au vert parce que la base n'existe pas,
    et ne prouvent rien du garde. On lit donc le message rendu, et l'on
    vérifie qu'aucun psql n'a été appelé.
    """

    def _refus(self, argv):
        import contextlib
        import io as flux

        appels = []
        vrai = anon.lib_analyse.require_odoo_database

        def espion(*a, **k):
            appels.append(a)
            return vrai(*a, **k)

        anon.lib_analyse.require_odoo_database = espion
        sortie = flux.StringIO()
        try:
            with contextlib.redirect_stderr(sortie):
                code = anon.main(argv)
        finally:
            anon.lib_analyse.require_odoo_database = vrai
        return code, sortie.getvalue(), appels

    def test_apply_without_a_matching_confirm_is_refused(self):
        code, message, appels = self._refus(
            ["-d", "une_base", "--apply", "--confirm", "une_autre"]
        )
        self.assertEqual(code, 2)
        self.assertIn(
            anon.t("Refusing to write: --confirm must repeat"), message
        )
        self.assertEqual(appels, [], "la base a été contactée pour refuser")

    def test_apply_with_no_confirm_at_all_is_refused(self):
        code, message, appels = self._refus(["-d", "une_base", "--apply"])
        self.assertEqual(code, 2)
        self.assertIn(
            anon.t("Refusing to write: --confirm must repeat"), message
        )
        self.assertEqual(appels, [])


if __name__ == "__main__":
    unittest.main()
