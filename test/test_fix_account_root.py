#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Retirer la vue morte account_root, et seulement quand c'est elle.

Odoo 17 créait une VUE SQL pour le modèle `account.root` ; la 18 l'a
orphelinée sans la retirer — son modèle porte `_auto = False` et
`_table_query = '0'`, donc son nom n'entre plus dans aucune requête, et
registry.py exclut ces modèles du contrôle des tables manquantes.

Elle n'est pas seulement morte, elle est FAUSSE : bâtie sur la colonne
`code` que l'ORM 18 n'écrit plus, elle rendait 14 racines là où la donnée
vivante en portait 31. Mesuré sur une migration 12 → 18 réelle.

Et elle est l'unique épingle de deux colonnes héritées : database_cleanup
a purgé 110 colonnes orphelines au palier 18 et n'a échoué que sur
account_account.code et .company_id, dont la vue dépend.

Ce que ce fichier garde, c'est la PRUDENCE du geste. On supprime une vue
sur une base client : les quatre refus comptent autant que la suppression.
"""

import io
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(
    REPO, "script", "odoo", "migration", "fix_migration_odoo170_to_odoo180.sql"
)
BASE = "_erplibre_test_account_root"


def psql_disponible():
    try:
        done = subprocess.run(
            ["psql", "-X", "-w", "-l"], capture_output=True, timeout=20
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(psql_disponible(), "pas de PostgreSQL joignable")
class Base(unittest.TestCase):
    """Une base jetable, remontée à neuf pour chaque cas."""

    @classmethod
    def setUpClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)
        done = subprocess.run(["createdb", BASE], capture_output=True)
        if done.returncode:
            raise unittest.SkipTest(
                "createdb refusé : " + done.stderr.decode()
            )

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)

    def setUp(self):
        self.sql(
            "DROP VIEW IF EXISTS autre_vue",
            "DROP VIEW IF EXISTS account_root",
            "DROP TABLE IF EXISTS account_root",
            "DROP TABLE IF EXISTS account_account",
        )

    def sql(self, *ordres):
        argv = ["psql", "-X", "-w", "-q", "-d", BASE]
        for ordre in ordres:
            argv += ["-c", ordre]
        done = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        return done

    def lire(self, requete):
        done = subprocess.run(
            ["psql", "-X", "-w", "-tA", "-d", BASE, "-c", requete],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        return done.stdout.strip()

    def vue_presente(self):
        return (
            self.lire(
                "SELECT (to_regclass('public.account_root') IS NOT NULL)::text"
            )
            == "true"
        )

    def appliquer(self):
        """Le fichier tel que la migration le lance : ON_ERROR_STOP=1."""
        done = subprocess.run(
            [
                "psql",
                "-X",
                "-w",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                BASE,
                "-f",
                FIX,
            ],
            capture_output=True,
            text=True,
        )
        return done.returncode, done.stderr

    def poser_la_vue_morte(self):
        self.sql(
            "CREATE TABLE account_account ("
            " id serial PRIMARY KEY, code varchar, company_id int)",
            "CREATE VIEW account_root AS SELECT DISTINCT"
            " ascii(code::text) AS id, left(code::text, 2) AS name,"
            " company_id FROM account_account WHERE code::text <> ''",
        )


class TestItRemovesTheDeadView(Base):
    def test_the_view_is_gone_and_psql_is_happy(self):
        self.poser_la_vue_morte()
        self.assertTrue(self.vue_presente())
        code, _err = self.appliquer()
        self.assertEqual(0, code)
        self.assertFalse(self.vue_presente())

    def test_it_says_what_it_did(self):
        # Une suppression silencieuse sur une base client est une
        # suppression qu'on ne retrouve pas six mois plus tard.
        self.poser_la_vue_morte()
        _code, err = self.appliquer()
        self.assertIn("account_root supprimee", err)

    def test_running_it_twice_changes_nothing(self):
        # Le fichier est rejoué à chaque reprise de migration.
        self.poser_la_vue_morte()
        self.appliquer()
        code, err = self.appliquer()
        self.assertEqual(0, code)
        self.assertNotIn("NOTICE", err)


class TestWhatItRefusesToTouch(Base):
    """Les refus comptent autant que la suppression."""

    def test_a_view_that_does_not_read_code_is_left_alone(self):
        # Si une version future d'Odoo recrée un account_root d'une autre
        # forme, il ne nous appartient pas. Le contrôle est STRUCTUREL —
        # pg_depend — et non un examen du texte de la définition.
        self.sql(
            "CREATE TABLE account_account ("
            " id serial PRIMARY KEY, code varchar, code_store jsonb)",
            "CREATE VIEW account_root AS SELECT id, code_store"
            " FROM account_account",
        )
        code, err = self.appliquer()
        self.assertEqual(0, code)
        self.assertTrue(self.vue_presente())
        self.assertIn("ne lit pas account_account.code", err)

    def test_a_view_something_depends_on_is_left_alone(self):
        # Apprendre plutôt que détruire : on le dit, et on passe. Jamais
        # de CASCADE.
        self.poser_la_vue_morte()
        self.sql("CREATE VIEW autre_vue AS SELECT * FROM account_root")
        code, err = self.appliquer()
        self.assertEqual(0, code)
        self.assertTrue(self.vue_presente())
        self.assertIn("1 objet(s) en dependent", err)

    def test_a_table_named_account_root_is_never_dropped(self):
        # relkind = 'v' : une TABLE de ce nom porterait des données.
        self.sql(
            "CREATE TABLE account_account ("
            " id serial PRIMARY KEY, code varchar)",
            "CREATE TABLE account_root (id int, name varchar)",
        )
        code, _err = self.appliquer()
        self.assertEqual(0, code)
        self.assertEqual(
            "r",
            self.lire(
                "SELECT relkind FROM pg_class"
                " WHERE relname = 'account_root'"
            ),
        )

    def test_a_database_without_account_stays_silent(self):
        # Le module account n'est pas installé partout, et le fichier
        # tourne sur toutes les bases.
        code, err = self.appliquer()
        self.assertEqual(0, code)
        self.assertNotIn("account_root", err)


class TestItNeverTouchesTheColumns(unittest.TestCase):
    """Le post-migration d'OpenUpgrade les lit APRÈS ce fichier.

    Il remplit code_store depuis `code` et company_ids depuis `company_id`.
    Les retirer ici casserait les deux. Leur suppression revient à
    database_cleanup, une fois la base chargée en 18.
    """

    def sans_commentaire(self):
        """Le fichier dépouillé de sa prose.

        Les gardes portent sur le CODE : les commentaires disent justement
        « on ne supprime pas les colonnes » et « jamais de CASCADE », et
        les lire suffisait à faire échouer les tests qui l'exigent.
        """
        with io.open(FIX, encoding="utf-8") as handle:
            source = handle.read()
        return "\n".join(
            ligne
            for ligne in source.split("\n")
            if not ligne.strip().startswith("--")
        )

    def test_the_file_carries_no_drop_column(self):
        self.assertNotIn("DROP COLUMN", self.sans_commentaire().upper())

    def test_the_only_drop_is_the_view(self):
        drops = [
            ligne.strip()
            for ligne in self.sans_commentaire().split("\n")
            if "DROP " in ligne.upper()
        ]
        self.assertEqual(["DROP VIEW public.account_root;"], drops)

    def test_it_never_uses_cascade(self):
        self.assertNotIn("CASCADE", self.sans_commentaire().upper())


if __name__ == "__main__":
    unittest.main()
