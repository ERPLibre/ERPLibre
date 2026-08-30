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
        self.assertIn('"id"::text', sql)
        self.assertNotIn(
            '"id"::text', anon.expression_texte(champ("ref"), ["a"])
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


class TestTheSqlNeverTravelsThroughArgv(unittest.TestCase):
    """La panne signalée : « OSError: [Errno 7] Argument list too long ».

    Linux plafonne UN SEUL argument à MAX_ARG_STRLEN — 32 pages, soit
    131 072 octets. Mesuré sur une base réelle : le mode hybride produit
    58 Ko de SQL et passait, la liste noire en produit 342 Ko sur 410
    modèles et cassait. Le mode qui couvre le plus était celui qui
    échouait, donc celui qu'aucun de mes essais n'exerçait.

    Le rendu de `render` reste borné, lui ; c'est bien l'exécution qu'il
    faut regarder, et pas seulement le plan.
    """

    def _executer(self, etapes):
        """Lancer `ecrire` avec un faux psql, et rendre ce qu'il a reçu."""
        import script.analyse.anonymize as module

        vu = {}
        vrai_run = module.__dict__.get("subprocess")

        class FauxFait:
            returncode = 0
            stdout = ""
            stderr = ""

        import subprocess as vrai_subprocess

        def espion(cmd, **kwargs):
            vu["cmd"] = list(cmd)
            chemin = cmd[cmd.index("-f") + 1] if "-f" in cmd else None
            if chemin:
                with open(chemin, encoding="utf-8") as handle:
                    vu["fichier"] = handle.read()
                vu["chemin"] = chemin
            return FauxFait()

        vrai_env = anon.lib_analyse.pg_env
        anon.lib_analyse.pg_env = lambda *a, **k: {"PATH": "/usr/bin"}
        vrai_subprocess_run = vrai_subprocess.run
        vrai_subprocess.run = espion
        try:
            erreur = anon.ecrire("une_base", etapes)
        finally:
            vrai_subprocess.run = vrai_subprocess_run
            anon.lib_analyse.pg_env = vrai_env
            del vrai_run
        vu["erreur"] = erreur
        return vu

    def _gros_plan(self, combien=400):
        """Un plan de la taille de celui qui cassait."""
        etapes = []
        for index in range(combien):
            champ = {
                "model": "m.%d" % index,
                "name": "name",
                "ttype": "char",
                "pg_type": "character varying",
                "unique": False,
                "checked": False,
            }
            etapes.append(
                {
                    "model": champ["model"],
                    "fields": [champ],
                    "sql": anon.sql_pour_table("m_%d" % index, [champ], None),
                }
            )
        return etapes

    def test_no_single_argument_comes_close_to_the_kernel_limit(self):
        vu = self._executer(self._gros_plan())
        plus_gros = max(len(a) for a in vu["cmd"])
        self.assertLess(
            plus_gros,
            4096,
            "un argument porte le SQL : c'est ce qui rendait E2BIG",
        )

    def test_the_sql_goes_through_a_file_not_through_c(self):
        vu = self._executer(self._gros_plan(3))
        self.assertIn("-f", vu["cmd"])
        self.assertNotIn("-c", vu["cmd"])
        self.assertIn('UPDATE "m_0"', vu["fichier"])

    def test_the_single_transaction_survives_the_change(self):
        """`--single-transaction` n'est documenté qu'avec -c ou -f : passer
        par l'entrée standard l'aurait perdu en silence."""
        vu = self._executer(self._gros_plan(2))
        self.assertIn("-1", vu["cmd"])
        self.assertIn("ON_ERROR_STOP=1", vu["cmd"])

    def test_the_temporary_file_does_not_survive(self):
        import os as vrai_os

        vu = self._executer(self._gros_plan(2))
        self.assertFalse(vrai_os.path.exists(vu["chemin"]))


class TestABoundedColumnIsNeverOverflowed(unittest.TestCase):
    """`value too long for type character varying(3)`.

    Mesuré sur une base réelle : 13 colonnes texte portent une longueur
    déclarée, dont des codes à 1, 2 et 3 caractères — `res.country.code`,
    `account.journal.code`. Y écrire « jonquille » fait échouer l'UPDATE,
    et comme l'écriture est transactionnelle, TOUTE l'anonymisation.

    Le mode hybride ne touchait aucune de ces colonnes ; la liste noire,
    si. Le mode qui couvre le plus est celui qui cassait.
    """

    def _champ(self, **kw):
        base = {
            "model": "m",
            "name": "code",
            "ttype": "char",
            "pg_type": "character varying",
            "unique": False,
            "checked": False,
            "max_len": None,
        }
        base.update(kw)
        return base

    def test_a_bounded_column_is_truncated(self):
        sql = anon.expression_texte(self._champ(max_len=3), ["jonquille"])
        self.assertIn("left(", sql)
        self.assertIn(", 3)", sql)

    def test_an_unbounded_column_is_left_alone(self):
        sql = anon.expression_texte(self._champ(), ["jonquille"])
        self.assertNotIn("left(", sql)

    def test_a_bounded_unique_column_keeps_the_id_in_front(self):
        """Tronquer par la droite doit laisser l'identifiant intact :
        c'est lui qui porte l'unicité."""
        sql = anon.expression_texte(
            self._champ(max_len=8, unique=True), ["jonquille"]
        )
        self.assertIn("left(\"id\"::text || '-'", sql)

    def test_an_unbounded_unique_column_keeps_the_old_shape(self):
        sql = anon.expression_texte(self._champ(unique=True), ["jonquille"])
        self.assertTrue(sql.rstrip().endswith("|| '-' || \"id\"::text END"))

    def test_the_length_is_read_from_the_database_not_guessed(self):
        """`atttypmod` est la seule source : une longueur devinée serait
        fausse dès qu'un module en change une."""
        self.assertIn("atttypmod", anon.REQUETE_CHAMPS)


class TestReservedWordsCannotBreakTheStatement(unittest.TestCase):
    """`syntax error at or near "user"`.

    Odoo laisse nommer un champ `user`, `order` ou `group`. Un identifiant
    nu fait alors échouer l'analyse syntaxique — et l'écriture étant
    transactionnelle, c'est toute l'anonymisation qui tombe. Trouvé en
    liste noire sur une base réelle, jamais en mode hybride : les quinze
    modèles par défaut n'en portent aucun.
    """

    def _champ(self, nom):
        return {
            "model": "m",
            "name": nom,
            "ttype": "char",
            "pg_type": "character varying",
            "unique": False,
            "checked": False,
            "max_len": None,
        }

    def test_a_column_named_like_a_keyword_is_quoted(self):
        for nom in ("user", "order", "group", "check", "references", "limit"):
            sql = anon.sql_pour_table("t", [self._champ(nom)], ["a"])
            self.assertIn(f'"{nom}" =', sql, nom)
            self.assertNotIn(f" {nom} =", sql, nom)

    def test_a_table_named_like_a_keyword_is_quoted(self):
        sql = anon.sql_pour_table("order", [self._champ("name")], ["a"])
        self.assertTrue(sql.startswith('UPDATE "order" SET'))

    def test_the_row_identifier_is_quoted_too(self):
        """Une seule règle vaut mieux que deux : tout identifiant est cité."""
        sql = anon.expression_texte(self._champ("name"), ["a", "b"])
        self.assertIn('"id"', sql)

    def test_a_quote_inside_an_identifier_cannot_escape(self):
        self.assertEqual(anon.ident('a"b'), '"a""b"')


class TestACheckDoesNotSilenceTheMainField(unittest.TestCase):
    """La règle « écarter toute colonne sous CHECK » était trop large.

    Mesuré : `res_partner.name` porte
        CHECK ((type='contact' AND name IS NOT NULL) OR type<>'contact')
    — une garantie de non-nullité, qu'un mot satisfait. L'écarter rendait
    une anonymisation qui n'anonymisait pas les noms, en annonçant 255
    colonnes écrites. Le pire des deux mondes : silencieux et faux.

    Sur un NOMBRE la distinction s'inverse : `credit * debit = 0` et
    `amount >= 0` bornent la valeur, et un tirage à 1000 les viole.
    """

    def test_the_query_tells_numbers_from_text(self):
        """La règle vit dans le SQL : c'est là qu'elle se vérifie."""
        requete = anon.REQUETE_CHAMPS
        self.assertIn("f.ttype IN ('integer','float','monetary')", requete)
        self.assertIn("pg_get_constraintdef", requete)

    def test_only_shape_constraints_disqualify_text(self):
        for motif in ("char_length", "~~", "jsonb_typeof"):
            self.assertIn(motif, anon.REQUETE_CHAMPS, motif)

    def test_a_field_the_query_cleared_is_anonymised(self):
        """`checked=False` doit suffire : aucune seconde barrière cachée."""
        champ = {
            "model": "res.partner",
            "name": "name",
            "ttype": "char",
            "pg_type": "character varying",
            "unique": False,
            "checked": False,
            "max_len": None,
        }
        self.assertTrue(anon.champ_retenu(champ))

    def test_a_field_the_query_flagged_is_left_alone(self):
        champ = {
            "model": "account.move.line",
            "name": "credit",
            "ttype": "monetary",
            "pg_type": "numeric",
            "unique": False,
            "checked": True,
            "max_len": None,
        }
        self.assertFalse(anon.champ_retenu(champ))


class TestStructuredCharFieldsSurvive(unittest.TestCase):
    """`ValueError: invalid literal for int() with base 10: 'bruyere'`.

    Odoo déclare `parent_path` en `char`, mais y range un CHEMIN
    D'IDENTIFIANTS — « 1/7/12/ » — qu'il reparse :

        int(id) for id in company.parent_path.split('/')
            base/models/res_company.py:117, models.py:203 et :221

    Y écrire un mot fait lever le serveur au premier chargement de page.
    Mesuré : sept modèles `_parent_store` dans une base ordinaire —
    res.company, product.category, stock.location, hr.department,
    website.menu, account.analytic.plan, helpdesk.ticket.category.

    Même chose pour `days_next_month`, qu'Odoo passe à `int()`
    (account/models/account_payment_term.py:321).
    """

    def _champ(self, nom):
        return {
            "model": "res.company",
            "name": nom,
            "ttype": "char",
            "pg_type": "character varying",
            "unique": False,
            "checked": False,
            "max_len": None,
        }

    def test_the_known_parsers_are_named(self):
        self.assertIn("parent_path", anon.CHAMPS_STRUCTURES)
        self.assertIn("days_next_month", anon.CHAMPS_STRUCTURES)

    def test_they_are_never_touched_whatever_the_model(self):
        for nom in anon.CHAMPS_STRUCTURES:
            self.assertFalse(anon.champ_retenu(self._champ(nom)), nom)

    def test_a_phone_number_is_not_mistaken_for_a_structure(self):
        """Le motif EXIGE les barres obliques. Sans elles, un numéro tout
        en chiffres passerait pour une structure et échapperait à
        l'anonymisation — un défaut de confidentialité, pas de robustesse.
        """
        import re

        motif = re.compile(anon.MOTIF_CHEMIN)
        for valeur in ("5141234567", "0", "42", "1234-5678"):
            self.assertIsNone(motif.match(valeur), valeur)
        for valeur in ("1/", "1/7/12/", "3/4/"):
            self.assertIsNotNone(motif.match(valeur), valeur)

    def test_the_probe_asks_once_per_table_not_once_per_column(self):
        """Sur 410 modèles, la différence est de 410 allers-retours au
        lieu de 863."""
        appels = []

        def espion(database, sql, config_path=None):
            appels.append(sql)
            return "0:0\x1f0:0"

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [
            {
                "model": "res.company",
                "fields": [self._champ("name"), self._champ("street")],
                "sql": "x",
            }
        ]
        try:
            anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai
        self.assertEqual(len(appels), 1)
        self.assertIn('"name"', appels[0])
        self.assertIn('"street"', appels[0])

    def test_one_counter_example_is_enough_to_keep_a_column(self):
        """Mieux vaut anonymiser une colonne douteuse que taire une
        donnée personnelle."""

        def espion(database, sql, config_path=None):
            # 10 valeurs remplies, 9 seulement sont des chemins.
            return "10:9"

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [
            {"model": "m", "fields": [self._champ("chemin")], "sql": "x"}
        ]
        try:
            ecartees, _ = anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai
        self.assertEqual(ecartees, {})

    def test_an_all_paths_column_is_dropped_from_the_plan(self):
        def espion(database, sql, config_path=None):
            # Une mesure PAR COLONNE : la sonde compte ce qu'elle
            # reçoit et renonce si le compte ne tombe pas juste.
            return "10:10\x1f10:10"

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [
            {
                "model": "m",
                "fields": [self._champ("chemin"), self._champ("nom")],
                "sql": "x",
            }
        ]
        try:
            ecartees, _ = anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai
        # Les deux colonnes rendent le même compte ici : c'est le principe
        # qu'on vérifie, pas la ligne exacte.
        self.assertIn("m", ecartees)
        propre = anon.appliquer_sondes(etapes, {"m": ["chemin"]}, {}, None)
        self.assertEqual([c["name"] for c in propre[0]["fields"]], ["nom"])
        self.assertNotIn('"chemin"', propre[0]["sql"])

    def test_a_model_entirely_dropped_leaves_no_empty_statement(self):
        etapes = [
            {"model": "m", "fields": [self._champ("chemin")], "sql": "x"}
        ]
        self.assertEqual(
            anon.appliquer_sondes(etapes, {"m": ["chemin"]}, {}, None), []
        )


class TestANumberKeepsItsMeaningfulRange(unittest.TestCase):
    """`ValueError: hour must be in 0..23`.

    `resource.calendar.attendance.hour_from` est un `float` qui vaut une
    heure de la journée — 8,00 à 13,00 dans la base d'origine. Un tirage
    à 957 fait lever Odoo au premier affichage d'un employé :

        time(int(integral), ...)   resource/models/utils.py:45

    Aucune contrainte PostgreSQL ne dit cela : la borne vit dans le code.
    La seule que les DONNÉES déclarent est leur propre étendue, et c'est
    la seule qu'on puisse respecter sans nommer les champs un par un.
    """

    def _champ(self, ttype="float", **kw):
        base = {
            "model": "resource.calendar.attendance",
            "name": "hour_from",
            "ttype": ttype,
            "pg_type": "numeric",
            "unique": False,
            "checked": False,
            "max_len": None,
        }
        base.update(kw)
        return base

    def test_a_measured_range_bounds_the_draw(self):
        sql = anon.expression_nombre(
            self._champ(borne_min="8.0", borne_max="13.0")
        )
        self.assertIn("8.0 + random() * (13.0 - 8.0)", sql)
        self.assertNotIn("1000", sql)

    def test_an_integer_can_reach_its_upper_bound(self):
        sql = anon.expression_nombre(
            self._champ(ttype="integer", borne_min="0", borne_max="5")
        )
        self.assertIn("(5 - 0 + 1)", sql)

    def test_without_a_range_it_falls_back_on_a_thousand(self):
        self.assertIn("1000", anon.expression_nombre(self._champ()))
        self.assertIn(
            "1001", anon.expression_nombre(self._champ(ttype="integer"))
        )

    def test_a_half_known_range_is_not_used(self):
        """Une borne sans l'autre ne borne rien."""
        for kw in ({"borne_min": "8.0"}, {"borne_max": "13.0"}):
            self.assertIn("1000", anon.expression_nombre(self._champ(**kw)))

    def test_a_value_that_is_not_a_number_never_reaches_the_sql(self):
        """Ces bornes viennent de la base et retournent dans du SQL."""
        self.assertTrue(anon.nombre_valide("8.0"))
        self.assertTrue(anon.nombre_valide("-3"))
        for mauvais in ("8.0); DROP TABLE x; --", "", None, "huit"):
            self.assertFalse(anon.nombre_valide(mauvais), mauvais)

    def test_the_probe_reads_the_bounds(self):
        recu = {}

        def espion(database, sql, config_path=None):
            recu["sql"] = sql
            return "8.0:13.0"

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [{"model": "m", "fields": [self._champ()], "sql": "x"}]
        try:
            _, bornes = anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai
        self.assertIn("min(", recu["sql"])
        self.assertIn("max(", recu["sql"])
        self.assertEqual(bornes["m"]["hour_from"], ("8.0", "13.0"))

    def test_an_empty_column_yields_no_bound(self):
        def espion(database, sql, config_path=None):
            return ":"

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [{"model": "m", "fields": [self._champ()], "sql": "x"}]
        try:
            _, bornes = anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai
        self.assertEqual(bornes, {})

    def test_the_bounds_reach_the_generated_sql(self):
        etapes = [{"model": "m", "fields": [self._champ()], "sql": "x"}]
        propre = anon.appliquer_sondes(
            etapes, {}, {"m": {"hour_from": ("8.0", "13.0")}}, None
        )
        self.assertIn("8.0 + random()", propre[0]["sql"])


class TestTheProbeDistrustsWhatItReads(unittest.TestCase):
    """Ce que la sonde reçoit repart dans du SQL : elle le vérifie.

    Deux mutations ont survécu au premier tour, et les deux disaient la
    même chose : j'éprouvais les fonctions de contrôle isolément sans
    vérifier que la sonde s'en sert. Une garde qu'on n'exerce pas ne
    garde rien.
    """

    def _champ(self, nom="hour_from", ttype="float"):
        return {
            "model": "m",
            "name": nom,
            "ttype": ttype,
            "pg_type": "numeric",
            "unique": False,
            "checked": False,
            "max_len": None,
        }

    def _sonder(self, reponse, champs):
        def espion(database, sql, config_path=None):
            return reponse

        vrai = anon.lib_analyse.run_psql
        anon.lib_analyse.run_psql = espion
        etapes = [{"model": "m", "fields": champs, "sql": "x"}]
        try:
            return anon.sonder_colonnes("base", etapes)
        finally:
            anon.lib_analyse.run_psql = vrai

    def test_a_bound_that_is_not_a_number_is_refused(self):
        """La base peut rendre autre chose qu'un nombre ; ces valeurs
        retournent telles quelles dans un littéral SQL."""
        for reponse in ("abc:def", "8.0); DROP TABLE x; --:13", ":13"):
            _, bornes = self._sonder(reponse, [self._champ()])
            self.assertEqual(bornes, {}, reponse)

    def test_a_valid_bound_still_passes(self):
        _, bornes = self._sonder("8.0:13.0", [self._champ()])
        self.assertEqual(bornes["m"]["hour_from"], ("8.0", "13.0"))

    def test_a_short_answer_is_refused_whole(self):
        """Moins de mesures que de colonnes : `zip` tronquerait en silence
        et attribuerait la mesure d'une colonne à une autre."""
        champs = [self._champ("a"), self._champ("b"), self._champ("c")]
        ecartees, bornes = self._sonder("8.0:13.0", champs)
        self.assertEqual(bornes, {})
        self.assertEqual(ecartees, {})

    def test_a_long_answer_is_refused_too(self):
        champs = [self._champ("a")]
        _, bornes = self._sonder("8.0:13.0\x1f1.0:2.0", champs)
        self.assertEqual(bornes, {})

    def test_the_exact_count_is_accepted(self):
        champs = [self._champ("a"), self._champ("b")]
        _, bornes = self._sonder("8.0:13.0\x1f1.0:2.0", champs)
        self.assertEqual(len(bornes["m"]), 2)


if __name__ == "__main__":
    unittest.main()
