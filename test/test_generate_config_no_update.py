#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""generate_config.sh ne démarre Odoo (« make config_update ») qu'une fois
ses dépendances posées.

install_locally_dev.sh, dont l'installation régénère config.conf après
« poetry install », exporte EL_CONFIG_NO_UPDATE=1 pour ses deux modes ;
install_locally.sh le transmet sans décider. Les scripts réels tournent dans
un arbre temporaire ; « make » et install_venv.sh y sont des bouchons qui
notent leur appel.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_VAR = """\
EL_ODOO_VERSION=$(cat ".odoo-version")
EL_ERPLIBRE_VERSION=$(cat ".erplibre-version")
EL_POETRY_VERSION=0.0.0
EL_PYTHON_ODOO_VERSION=3.0.0
EL_PYTHON_ERPLIBRE_VERSION=3.0.0
EL_PORT=8069
EL_LONGPOLLING_PORT=8072
EL_SUPERADMIN=admin
EL_MINIMAL_ADDONS=True
EL_INSTALL_NGINX=False
"""

# « make » bouchon : note sa cible, rend 0.
STUB_MAKE = """#!/usr/bin/env bash
echo "$*" >> "${STUB_LOG}"
"""

# install_venv.sh bouchon : échoue, ce qui arrête install_locally.sh juste
# après generate_config.sh, avant tout pip ou poetry.
STUB_VENV = """#!/usr/bin/env bash
exit 1
"""

# generate_config.sh bouchon, pour install_locally.sh : note la variable
# qu'il reçoit.
STUB_GENERATE = """#!/usr/bin/env bash
echo "EL_CONFIG_NO_UPDATE=${EL_CONFIG_NO_UPDATE:-}" >> "${STUB_LOG}"
"""


class _Arbre(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        self.bin = os.path.join(self.racine, "stub_bin")
        self.journal = os.path.join(self.racine, "stub.log")
        os.makedirs(os.path.join(self.racine, "script", "install", "S390x"))
        os.makedirs(os.path.join(self.racine, "conf"))
        os.makedirs(self.bin)
        self.ecrire("env_var.sh", ENV_VAR)
        self.ecrire(".odoo-version", "18.0")
        self.ecrire(".erplibre-version", "odoo18.0_python3.0.0")
        self.ecrire("conf/python-erplibre-venv", ".venv.erplibre")
        self.ecrire("stub_bin/make", STUB_MAKE, executable=True)

    def ecrire(self, chemin, texte, executable=False):
        complet = os.path.join(self.racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w") as f:
            f.write(texte)
        if executable:
            os.chmod(complet, 0o755)

    def copier(self, chemin):
        shutil.copy2(
            os.path.join(ROOT, chemin), os.path.join(self.racine, chemin)
        )

    def installation_presente(self):
        """Le venv d'Odoo et ses sources, sans aucune dépendance."""
        self.ecrire(".venv.odoo18.0_python3.0.0/bin/activate", "")
        self.ecrire("odoo18.0/odoo/odoo-bin", "")

    def lancer(self, commande, **env_extra):
        env = dict(os.environ)
        env.pop("EL_CONFIG_NO_UPDATE", None)
        env.pop("EL_PHASE", None)
        env.update(env_extra)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["STUB_LOG"] = self.journal
        return subprocess.run(
            ["bash", commande],
            cwd=self.racine,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def appels(self):
        if not os.path.exists(self.journal):
            return []
        with open(self.journal) as f:
            return f.read().splitlines()


class TestGenerateConfig(_Arbre):
    def setUp(self):
        super().setUp()
        self.copier("script/generate_config.sh")

    def test_installation_presente_demarre_odoo(self):
        self.installation_presente()
        self.lancer("./script/generate_config.sh")
        self.assertEqual(self.appels(), ["config_update"])

    def test_sans_update_ecrit_le_fichier_sans_odoo(self):
        self.installation_presente()
        sortie = self.lancer(
            "./script/generate_config.sh", EL_CONFIG_NO_UPDATE="1"
        )
        self.assertEqual(self.appels(), [])
        self.assertIn("EL_CONFIG_NO_UPDATE=1", sortie.stdout)
        with open(os.path.join(self.racine, "config.conf")) as f:
            self.assertIn("addons_path = ", f.read())

    def test_sans_venv_rien_a_demarrer(self):
        self.ecrire("odoo18.0/odoo/odoo-bin", "")
        self.lancer("./script/generate_config.sh")
        self.assertEqual(self.appels(), [])


class TestInstallLocallyPhases(_Arbre):
    def setUp(self):
        super().setUp()
        for chemin in (
            "script/install/install_locally.sh",
            "script/install/lib_non_interactive.sh",
            "script/install/lib_pip_provider.sh",
            "script/install/S390x/lib_lowmem.sh",
        ):
            self.copier(chemin)
        self.ecrire("script/generate_config.sh", STUB_GENERATE, True)
        self.ecrire("script/install/install_venv.sh", STUB_VENV, True)

    def test_transmet_la_variable_recue(self):
        self.lancer(
            "./script/install/install_locally.sh",
            EL_PHASE="setup",
            EL_CONFIG_NO_UPDATE="1",
        )
        self.assertEqual(self.appels(), ["EL_CONFIG_NO_UPDATE=1"])

    def test_sans_variable_garde_le_demarrage(self):
        """Phase all, celle d'install_locally_prod.sh : rien ne régénère
        config.conf après elle, l'appel à Odoo reste."""
        self.lancer("./script/install/install_locally.sh")
        self.assertEqual(self.appels(), ["EL_CONFIG_NO_UPDATE="])


class TestInstallLocallyDev(unittest.TestCase):
    """L'export précède les deux modes, parallèle et séquentiel."""

    def setUp(self):
        with open(
            os.path.join(ROOT, "script/install/install_locally_dev.sh")
        ) as f:
            self.lignes = f.read().splitlines()

    def _premiere(self, fragment):
        for i, ligne in enumerate(self.lignes):
            if fragment in ligne and not ligne.lstrip().startswith("#"):
                return i
        self.fail(f"{fragment!r} absent d'install_locally_dev.sh")

    def test_export_avant_les_deux_modes(self):
        export = self._premiere("export EL_CONFIG_NO_UPDATE=1")
        self.assertEqual(self.lignes[export], "export EL_CONFIG_NO_UPDATE=1")
        self.assertLess(export, self._premiere("if [[ ${EL_PARALLEL_INSTALL}"))


if __name__ == "__main__":
    unittest.main()
