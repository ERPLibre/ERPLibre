#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le correctif de palier 12 → 13, exécuté contre un vrai PostgreSQL.

Une assertion sur le TEXTE d'un fichier SQL ne voit pas ce qu'il fait.
Celui-ci décode des séquences UTF-8 en pourcentage — `%C3%A9` tient sur
DEUX octets — et seule l'exécution prouve qu'on rassemble les octets
avant de convertir, plutôt que de produire deux caractères illisibles.

Ce qu'il répare : OpenUpgrade recolle les `href` d'ancres en sélecteur
CSS, où un `%` est interdit. La migration mourait là.
"""

import os
import shutil
import subprocess
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SQL = os.path.join(
    RACINE,
    "script",
    "odoo",
    "migration",
    "fix_migration_odoo120_to_odoo130.sql",
)


class Base(unittest.TestCase):
    BASE = "tmp_fix_120_130_test"

    @classmethod
    def setUpClass(cls):
        if not shutil.which("psql") or not shutil.which("createdb"):
            raise unittest.SkipTest("PostgreSQL absent")
        subprocess.run(
            ["dropdb", "--if-exists", cls.BASE], capture_output=True
        )
        if subprocess.run(
            ["createdb", cls.BASE], capture_output=True
        ).returncode:
            raise unittest.SkipTest("createdb impossible")

    @classmethod
    def tearDownClass(cls):
        if shutil.which("dropdb"):
            subprocess.run(
                ["dropdb", "--if-exists", cls.BASE], capture_output=True
            )

    def sql(self, requete):
        done = subprocess.run(
            ["psql", "-X", "-w", "-q", "-d", self.BASE, "-tAc", requete],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def prepare(self, lignes):
        """lignes = [(arch, a_une_page)]"""
        self.sql("DROP TABLE IF EXISTS website_page, ir_ui_view")
        self.sql(
            "CREATE TABLE ir_ui_view (id serial PRIMARY KEY, arch_db text)"
        )
        self.sql(
            "CREATE TABLE website_page (id serial PRIMARY KEY, view_id integer)"
        )
        for arch, avec_page in lignes:
            vid = self.sql(
                "INSERT INTO ir_ui_view (arch_db) VALUES ("
                + "'"
                + arch.replace("'", "''")
                + "') RETURNING id"
            )
            if avec_page:
                self.sql(f"INSERT INTO website_page (view_id) VALUES ({vid})")

    def applique(self):
        done = subprocess.run(
            [
                "psql",
                "-X",
                "-w",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                self.BASE,
                "-f",
                SQL,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done.stdout + done.stderr

    def arch(self, vid=1):
        return self.sql(f"SELECT arch_db FROM ir_ui_view WHERE id={vid}")


class TestDecodingTheAnchors(Base):
    def test_an_accented_anchor_is_decoded(self):
        self.prepare([('<a href="#principes-mn%C3%A9moniques">x</a>', True)])
        self.applique()
        self.assertEqual(self.arch(), '<a href="#principes-mnémoniques">x</a>')

    def test_two_byte_sequences_are_assembled_before_converting(self):
        # `%C3%A9` est UN caractère sur DEUX octets. Les décoder
        # séparément rendrait deux caractères illisibles.
        self.prepare([('<a href="#caf%C3%A9-th%C3%A9">x</a>', True)])
        self.applique()
        self.assertEqual(self.arch(), '<a href="#café-thé">x</a>')

    def test_several_anchors_in_one_view(self):
        self.prepare(
            [('<a href="#a%C3%A9">1</a><a href="#b%C3%A8">2</a>', True)]
        )
        self.applique()
        self.assertIn("#aé", self.arch())
        self.assertIn("#bè", self.arch())

    def test_it_is_replayable(self):
        self.prepare([('<a href="#r%C3%A9seau">x</a>', True)])
        self.applique()
        premier = self.arch()
        sortie = self.applique()
        self.assertEqual(self.arch(), premier)
        self.assertNotIn("decodee", sortie)


class TestWhatItMustNotTouch(Base):
    def test_a_percent_outside_an_anchor_is_left_alone(self):
        # Un `%` dans une vraie URL est légitime : le décoder changerait
        # une adresse qui fonctionne.
        arch = '<a href="/page?q=a%20b">x</a>'
        self.prepare([(arch, True)])
        self.applique()
        self.assertEqual(self.arch(), arch)

    def test_a_view_without_a_page_is_left_alone(self):
        # OpenUpgrade ne parcourt que les vues qui portent une page :
        # toucher plus large modifierait du contenu sans raison.
        arch = '<a href="#r%C3%A9seau">x</a>'
        self.prepare([(arch, False)])
        self.applique()
        self.assertEqual(self.arch(), arch)

    def test_a_lone_percent_is_not_an_encoding(self):
        # « 100% » n'est pas une séquence : seuls `%XX` hexadécimaux le
        # sont, et confondre les deux abîmerait du texte.
        arch = '<a href="#remise-100%-ici">x</a>'
        self.prepare([(arch, True)])
        sortie = self.applique()
        self.assertEqual(self.arch(), arch)
        # Et il ne doit pas ANNONCER un décodage qui n'a rien changé :
        # un rapport qui se félicite à vide fait douter du reste.
        self.assertNotIn("decodee", sortie)

    def test_an_anchor_without_any_percent_is_untouched(self):
        arch = '<a href="#simple">x</a>'
        self.prepare([(arch, True)])
        self.applique()
        self.assertEqual(self.arch(), arch)


class TestItLeavesNothingBehind(Base):
    def test_the_decoder_does_not_survive_the_session(self):
        # La fonction vit dans `pg_temp` : elle disparaît avec psql et ne
        # laisse rien dans la base du client.
        self.prepare([('<a href="#a%C3%A9">x</a>', True)])
        self.applique()
        reste = self.sql(
            "SELECT count(*) FROM pg_proc WHERE proname = 'el_url_decode'"
        )
        self.assertEqual(reste, "0")

    def test_a_database_without_the_tables_does_not_crash(self):
        self.sql("DROP TABLE IF EXISTS website_page, ir_ui_view")
        done = subprocess.run(
            [
                "psql",
                "-X",
                "-w",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                self.BASE,
                "-f",
                SQL,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class TestTheFileIsWiredIn(unittest.TestCase):
    def test_the_name_matches_what_the_driver_looks_for(self):
        # Le pilote compose « fix_migration_odoo{(v-1)*10}_to_odoo{v*10} ».
        self.assertTrue(os.path.isfile(SQL), SQL)
        self.assertTrue(SQL.endswith("fix_migration_odoo120_to_odoo130.sql"))

    def test_it_runs_before_openupgrade(self):
        # Il agit sur une base encore en 12 : après OpenUpgrade, il
        # serait trop tard, la migration aurait déjà échoué.
        with open(
            os.path.join(RACINE, "script", "todo", "todo_upgrade.py"),
            encoding="utf-8",
        ) as handle:
            src = handle.read()
        self.assertLess(
            src.index("- Fix migrate code"), src.index("- Migrate database")
        )


if __name__ == "__main__":
    unittest.main()
