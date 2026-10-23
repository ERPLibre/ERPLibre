#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les fichiers que l'installateur écrit dans un arbre Dolibarr.

install.forced.php porte TOUS les secrets de l'installation sans
navigateur : rien ne passe par argv. Une valeur mal échappée y deviendrait
du PHP exécuté ; les attentes sont donc écrites à la main, caractère par
caractère.

conf.php est écrit par l'installeur de Dolibarr ; set_conf_values n'en
change que les lignes nommées (prod, force_https…), et ajoute une ligne
absente au lieu de la perdre.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.dolibarr import install_files  # noqa: E402

# Valeurs inventées.
VALEURS = {
    "db_type": "mysqli",
    "db_host": "localhost",
    "db_port": 3306,
    "db_name": "dolibarr_erp",
    "db_user": "dolibarr_erp",
    "db_pass": "Zx9-invente_Q",
    "data_root": "/srv/essai/documents",
    "admin_login": "admin",
    "admin_pass": "adm-invente",
}


class TestPhpSingleQuoted(unittest.TestCase):
    CAS = (
        ("abc", "'abc'"),
        ("", "''"),
        ("l'eau", "'l\\'eau'"),
        ("a\\b", "'a\\\\b'"),
        # Une barre finale ne doit pas avaler le guillemet fermant.
        ("fin\\", "'fin\\\\'"),
        # Tentative d'évasion : elle reste une chaîne.
        ("x';system('id');'", "'x\\';system(\\'id\\');\\''"),
    )

    def test_cases(self):
        for valeur, attendu in self.CAS:
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    install_files.php_single_quoted(valeur), attendu
                )


class TestInstallForced(unittest.TestCase):
    def setUp(self):
        self.texte = install_files.render_install_forced(VALEURS)
        self.lignes = self.texte.splitlines()

    def test_it_is_a_php_file(self):
        self.assertEqual(self.lignes[0], "<?php")

    def test_database_settings_are_forced_and_not_editable(self):
        for ligne in (
            "$force_install_noedit = 2;",
            "$force_install_type = 'mysqli';",
            "$force_install_dbserver = 'localhost';",
            "$force_install_port = 3306;",
            "$force_install_database = 'dolibarr_erp';",
            "$force_install_prefix = 'llx_';",
            "$force_install_databaselogin = 'dolibarr_erp';",
            "$force_install_databasepass = 'Zx9-invente_Q';",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, self.lignes)

    def test_the_installer_creates_neither_database_nor_user(self):
        # La base et son compte sont créés AVANT, avec le bon jeu de
        # caractères ; aucun identifiant root n'est confié à Dolibarr.
        self.assertIn("$force_install_createdatabase = false;", self.lignes)
        self.assertIn("$force_install_createuser = false;", self.lignes)
        self.assertIn("$force_install_databaserootlogin = '';", self.lignes)
        self.assertIn("$force_install_databaserootpass = '';", self.lignes)

    def test_data_root_admin_and_lock(self):
        for ligne in (
            "$force_install_main_data_root = '/srv/essai/documents';",
            "$force_install_dolibarrlogin = 'admin';",
            "$force_install_dolibarrpassword = 'adm-invente';",
            "$force_install_lockinstall = '444';",
        ):
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, self.lignes)

    def test_a_quote_in_the_admin_password_stays_a_string(self):
        texte = install_files.render_install_forced(
            dict(VALEURS, admin_pass="a'b\\c")
        )
        self.assertIn(
            "$force_install_dolibarrpassword = 'a\\'b\\\\c';",
            texte.splitlines(),
        )

    def test_the_port_must_be_an_integer(self):
        with self.assertRaises(ValueError):
            install_files.render_install_forced(dict(VALEURS, db_port="3306;"))

    def test_a_db_password_dolibarr_would_alter_is_refused(self):
        # L'installeur de Dolibarr retire « \\ » et change « \" » en « ' » en
        # écrivant conf.php : la base et conf.php ne s'accorderaient plus.
        for mauvais in ('ab"c', "ab\\c"):
            with self.subTest(mauvais=mauvais):
                with self.assertRaises(ValueError):
                    install_files.render_install_forced(
                        dict(VALEURS, db_pass=mauvais)
                    )


CONF = """<?php
$dolibarr_main_url_root='http://127.0.0.1:8080';
$dolibarr_main_db_pass='secret-invente';
// Security settings
$dolibarr_main_prod='0';
$dolibarr_main_force_https='0';
$dolibarr_main_data_root="/srv/essai/documents";
"""


class TestSetConfValues(unittest.TestCase):
    def test_a_named_line_is_replaced_in_place(self):
        texte = install_files.set_conf_values(CONF, {"prod": "1"})
        self.assertIn("$dolibarr_main_prod='1';", texte.splitlines())
        self.assertNotIn("$dolibarr_main_prod='0';", texte)
        # Le reste ne bouge pas, à la ligne près.
        self.assertEqual(
            texte.replace(
                "$dolibarr_main_prod='1';", "$dolibarr_main_prod='0';"
            ),
            CONF,
        )

    def test_a_double_quoted_line_is_replaced_too(self):
        texte = install_files.set_conf_values(
            CONF, {"data_root": "/srv/autre/documents"}
        )
        self.assertIn(
            "$dolibarr_main_data_root='/srv/autre/documents';",
            texte.splitlines(),
        )
        self.assertNotIn('"/srv/essai/documents"', texte)

    def test_an_absent_setting_is_appended(self):
        texte = install_files.set_conf_values(
            CONF, {"restrict_ip": "10.9.8.7"}
        )
        self.assertTrue(texte.startswith(CONF.rstrip("\n")))
        self.assertEqual(
            texte.splitlines()[-1], "$dolibarr_main_restrict_ip='10.9.8.7';"
        )

    def test_a_commented_line_is_not_taken_for_the_setting(self):
        conf = CONF + "//$dolibarr_main_demo='autologin,autopass';\n"
        texte = install_files.set_conf_values(conf, {"demo": "0"})
        self.assertIn("//$dolibarr_main_demo='autologin,autopass';", texte)
        self.assertEqual(texte.splitlines()[-1], "$dolibarr_main_demo='0';")

    def test_the_setting_name_is_matched_whole(self):
        # prod ne doit pas toucher un réglage dont le nom le prolonge.
        conf = CONF + "$dolibarr_main_prod_extra='x';\n"
        texte = install_files.set_conf_values(conf, {"prod": "1"})
        self.assertIn("$dolibarr_main_prod_extra='x';", texte)


if __name__ == "__main__":
    unittest.main()
