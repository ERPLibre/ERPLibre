#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les noms de port qu'écrit generate_config.sh, selon l'Odoo actif.

http_port existe depuis Odoo 11, gevent_port depuis 16. Odoo 19 ne lit
plus xmlrpc_port ni longpolling_port et les signale à chaque démarrage ;
Odoo 8 à 10 ne connaissent que ces deux-là. Le script tourne ici pour de
vrai, dans un faux checkout sans venv : il n'y lance pas Odoo.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script", "generate_config.sh")

ENV_VAR = """EL_HOME_ODOO="${PWD}/odoo$(cat .odoo-version)/odoo"
EL_ODOO_VERSION=$(cat .odoo-version)
EL_PORT=8069
EL_LONGPOLLING_PORT=8072
EL_SUPERADMIN=admin
EL_MINIMAL_ADDONS=True
EL_INSTALL_NGINX=False
"""


class TestLesNomsDePort(unittest.TestCase):
    def generer(self, version, paquet, options, extra="", nginx="False"):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine)
        with open(os.path.join(racine, ".odoo-version"), "w") as handle:
            handle.write(version)
        with open(os.path.join(racine, "env_var.sh"), "w") as handle:
            handle.write(
                ENV_VAR.replace(
                    "EL_INSTALL_NGINX=False", f"EL_INSTALL_NGINX={nginx}"
                )
            )
        os.makedirs(os.path.join(racine, "script"))
        shutil.copy(SCRIPT, os.path.join(racine, "script"))
        outils = os.path.join(
            racine, "odoo" + version, "odoo", paquet, "tools"
        )
        os.makedirs(outils)
        with open(os.path.join(outils, "config.py"), "w") as handle:
            handle.write(
                "".join(
                    f'group.add_option("{option}", dest="x")\n'
                    for option in options
                )
                + extra
            )
        done = subprocess.run(
            ["bash", "script/generate_config.sh"],
            cwd=racine,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)
        with open(os.path.join(racine, "config.conf")) as handle:
            return handle.read()

    def test_odoo_8_garde_les_anciens_noms(self):
        conf = self.generer(
            "8.0", "openerp", ["--xmlrpc-port", "--longpolling-port"]
        )
        self.assertIn("xmlrpc_port = 8069\n", conf)
        self.assertIn("longpolling_port = 8072\n", conf)

    def test_odoo_12_passe_a_http_port(self):
        conf = self.generer(
            "12.0",
            "odoo",
            ["--xmlrpc-port", "--http-port", "--longpolling-port"],
        )
        self.assertIn("http_port = 8069\n", conf)
        self.assertIn("longpolling_port = 8072\n", conf)
        self.assertNotIn("xmlrpc_port", conf)

    def test_odoo_19_n_ecrit_que_les_noms_qu_il_lit(self):
        conf = self.generer("19.0", "odoo", ["--http-port", "--gevent-port"])
        self.assertIn("http_port = 8069\n", conf)
        self.assertIn("gevent_port = 8072\n", conf)
        self.assertNotIn("xmlrpc_port", conf)
        self.assertNotIn("longpolling_port", conf)


class TestLInterfaceHttp(unittest.TestCase):
    """Odoo 20 lit un http_interface vide comme 127.0.0.1, là où 11 à 19
    écoutent sur toutes les interfaces. Sans nginx devant, l'instance doit
    rester joignable depuis une autre machine."""

    generer = TestLesNomsDePort.generer

    ODOO_20 = (
        'group.add_option("--http-interface", dest="http_interface",'
        " my_default='127.0.0.1')\n"
    )
    ODOO_18 = (
        'group.add_option("--http-interface", dest="http_interface",'
        " my_default='')\n"
    )

    def test_odoo_20_sans_nginx_ecoute_toutes_les_interfaces(self):
        conf = self.generer("20.0", "odoo", ["--http-port"], self.ODOO_20)
        self.assertIn("http_interface = 0.0.0.0\n", conf)

    # Odoo 19 ne connaît plus xmlrpc_interface et écoute par défaut sur
    # toutes les interfaces.
    ODOO_19 = (
        'group.add_option("--http-interface", dest="http_interface",'
        " my_default='0.0.0.0')\n"
    )
    # De 11 à 18, l'ancien nom reste un alias caché de --http-interface.
    ALIAS_XMLRPC = (
        'group.add_option("--xmlrpc-interface", dest="http_interface")\n'
    )

    def test_derriere_nginx_odoo_19_et_20_ecoutent_la_machine_locale(self):
        for version, defaut in (
            ("19.0", self.ODOO_19),
            ("20.0", self.ODOO_20),
        ):
            with self.subTest(version=version):
                conf = self.generer(
                    version, "odoo", ["--http-port"], defaut, nginx="True"
                )
                self.assertIn("http_interface = 127.0.0.1\n", conf)
                self.assertNotIn("xmlrpc_interface", conf)

    def test_derriere_nginx_odoo_8_et_18_gardent_l_ancien_nom(self):
        for version, paquet, options, extra in (
            ("8.0", "openerp", ["--xmlrpc-port"], 'dest="xmlrpc_interface"\n'),
            (
                "18.0",
                "odoo",
                ["--http-port"],
                self.ODOO_18 + self.ALIAS_XMLRPC,
            ),
        ):
            with self.subTest(version=version):
                conf = self.generer(
                    version, paquet, options, extra, nginx="True"
                )
                self.assertIn("xmlrpc_interface = 127.0.0.1\n", conf)
                self.assertNotIn("http_interface", conf)

    def test_odoo_18_garde_son_defaut(self):
        conf = self.generer("18.0", "odoo", ["--http-port"], self.ODOO_18)
        self.assertNotIn("http_interface", conf)


if __name__ == "__main__":
    unittest.main()
