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
    def generer(self, version, paquet, options):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine)
        with open(os.path.join(racine, ".odoo-version"), "w") as handle:
            handle.write(version)
        with open(os.path.join(racine, "env_var.sh"), "w") as handle:
            handle.write(ENV_VAR)
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


if __name__ == "__main__":
    unittest.main()
