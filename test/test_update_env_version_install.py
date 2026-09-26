#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une installation interrompue se reprend-elle ?

« make install_odoo_<N> » passe par update_env_version.py --install_dev. Une
installation qui échoue dans poetry install laisse le venv et odooN/addons :
la relance les trouvait, répondait « Nothing to do », rendait 0, et la
version restait à moitié installée. install_locally.sh n'inscrit la version
dans .repo/installed_odoo_version.txt qu'à la fin d'une installation
réussie : c'est ce signal, et lui seul, qui dit qu'il n'y a rien à faire.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.version import update_env_version as uev  # noqa: E402


class TestReprise(unittest.TestCase):
    def setUp(self):
        self._ici = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        # Ce que laisse une installation interrompue : le venv et les addons.
        Path(".venv.odoo11.0_python3.7.17").mkdir()
        Path("odoo11.0/addons").mkdir(parents=True)
        Path(".repo").mkdir()

    def tearDown(self):
        os.chdir(self._ici)
        self._tmp.cleanup()

    def _valide(self, install_dev=True):
        update = uev.Update.__new__(uev.Update)
        update.config = types.SimpleNamespace(install_dev=install_dev)
        update.new_version_odoo = "11.0"
        update.expected_venv_name = ".venv.odoo11.0_python3.7.17"
        update.expected_addons_name = "odoo11.0/addons"
        update.expected_pyproject_path = "x"
        update.expected_poetry_lock_path = "x"
        with mock.patch.object(uev.Update, "update_link_file", return_value=True):
            return update.validate_environment()

    def test_une_installation_interrompue_est_reprise(self):
        self.assertFalse(self._valide())

    def test_une_installation_inscrite_n_a_rien_a_faire(self):
        Path(uev.INSTALLED_ODOO_VERSION_FILE).write_text("odoo11.0\n")
        self.assertTrue(self._valide())

    def test_une_autre_version_inscrite_ne_compte_pas(self):
        Path(uev.INSTALLED_ODOO_VERSION_FILE).write_text("odoo10.0\nodoo19.0\n")
        self.assertFalse(self._valide())

    def test_un_changement_de_version_n_exige_pas_l_inscription(self):
        """--switch sans --install_dev : on bascule, on n'installe pas."""
        self.assertTrue(self._valide(install_dev=False))


if __name__ == "__main__":
    unittest.main()
