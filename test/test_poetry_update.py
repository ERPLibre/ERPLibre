#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""poetry_update.py fabrique-t-il un verrou juste, et dit-il quand il échoue ?

Deux défauts, que révèle la première version d'Odoo à les rencontrer :

- une ligne de requirements qui désigne un FICHIER — la boîte IoT d'Odoo 19
  déclare une roue livrée avec le module — n'est pas un paquet. Requirement()
  la refuse faute de nom, et l'assemblage entier s'arrêtait sur
  « Expected package name ». Pire, un marqueur vrai pour ce serveur l'aurait
  retenue, alors qu'aucun dépôt ne la sert ;
- quand « poetry add » échoue, le script sautait la suite et rendait 0 :
  aucun verrou produit, et make, comme toute chaîne qui teste le code de
  retour, croyait à une réussite.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
# poetry_update importe « iscompatible », son voisin de dossier, sans
# préfixe : lancé en script, Python met ce dossier dans son chemin.
sys.path.insert(0, str(RACINE / "script" / "poetry"))

from script.poetry import poetry_update  # noqa: E402

VERSION = "odoo19.0_python3.12.10"


class Arbre(unittest.TestCase):
    """Un checkout minimal dans un répertoire temporaire : les fichiers que
    combine_requirements lit, et le venv où il écrit son résultat."""

    def setUp(self):
        self._ici = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        for nom, contenu in {
            ".odoo-version": "19.0",
            ".python-odoo-version": "3.12.10",
            ".erplibre-version": VERSION,
            ".poetry-version": "2.1.3",
        }.items():
            Path(nom).write_text(contenu)
        Path("requirement").mkdir()
        Path(f"requirement/requirements.{VERSION}.txt").write_text("orjson\n")
        Path(f"requirement/ignore_requirements.{VERSION}.txt").write_text("")
        Path("odoo19.0/addons").mkdir(parents=True)
        Path("odoo19.0/odoo").mkdir(parents=True)
        Path(f".venv.{VERSION}").mkdir()

    def tearDown(self):
        os.chdir(self._ici)
        self._tmp.cleanup()

    def _config(self):
        with mock.patch.object(sys, "argv", ["poetry_update.py", "--dry"]):
            return poetry_update.get_config()

    def _dependances(self):
        return Path(f".venv.{VERSION}/build_dependency.txt").read_text()


class TestCheminsLocaux(Arbre):
    def test_une_ligne_chemin_n_arrete_plus_l_assemblage(self):
        Path("odoo19.0/odoo/requirements.txt").write_text(
            "/home/pi/iot/aiortc-1.4.0-py3-none-any.whl;"
            ' sys_platform == "linux"\n'
            "lxml==5.2.1\n"
        )
        poetry_update.combine_requirements(self._config())
        dependances = self._dependances()
        self.assertIn("lxml", dependances)
        self.assertIn("orjson", dependances)

    def test_un_chemin_n_est_jamais_retenu(self):
        """Même avec un marqueur vrai pour ce serveur : un fichier livré avec
        un module ne s'installe depuis aucun dépôt."""
        Path("odoo19.0/odoo/requirements.txt").write_text(
            "./addons/iot/aiortc-1.4.0-py3-none-any.whl;"
            ' sys_platform == "linux"\n'
            "file:///tmp/paquet.whl\n"
            "../voisin/paquet.whl\n"
            "lxml==5.2.1\n"
        )
        poetry_update.combine_requirements(self._config())
        dependances = self._dependances()
        for fragment in (".whl", "file:", "aiortc"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, dependances)


class TestContraintesComposees(Arbre):
    """Un paquet déclaré par deux sources passe par la comparaison des
    versions. Une contrainte à deux clauses — « >=a,<=b », que porte un dépôt
    OCA d'Odoo 10 — y arrêtait tout sur « Invalid version: 'a,<=b' »."""

    def test_une_contrainte_a_deux_clauses_est_comparee(self):
        Path("odoo19.0/odoo/requirements.txt").write_text(
            "invoice2data>=0.2.74,<=0.3.4\n"
        )
        Path("odoo19.0/addons/OCA_edi").mkdir()
        Path("odoo19.0/addons/OCA_edi/requirements.txt").write_text(
            "invoice2data>=0.3.0\n"
        )
        poetry_update.combine_requirements(self._config())
        self.assertIn("invoice2data", self._dependances())


class TestCodeDeRetour(Arbre):
    def _main(self, ajout_reussi):
        Path("pyproject.toml").write_text(
            '[tool.poetry.dependencies]\npython = ">=3.12"\n'
        )
        with (
            mock.patch.object(sys, "argv", ["poetry_update.py", "-f"]),
            mock.patch.object(poetry_update, "combine_requirements"),
            mock.patch.object(
                poetry_update,
                "call_poetry_add_build_dependency",
                return_value=ajout_reussi,
            ),
            mock.patch.object(
                poetry_update, "apply_marker_variants", return_value=False
            ),
        ):
            poetry_update.main()

    def test_un_echec_de_poetry_sort_en_erreur(self):
        """Aucun verrou n'a été produit : rendre 0 le ferait croire."""
        with self.assertRaises(SystemExit) as sortie:
            self._main(ajout_reussi=False)
        self.assertEqual(1, sortie.exception.code)

    def test_une_reussite_ne_sort_pas_en_erreur(self):
        self._main(ajout_reussi=True)


class TestRangementDuVerrou(Arbre):
    """Le verrou produit à la racine se range sous requirement/, même pour une
    version qui n'en a encore aucun."""

    def _main_qui_produit_un_verrou(self):
        Path("pyproject.toml").write_text(
            '[tool.poetry.dependencies]\npython = ">=3.12"\n'
        )

        def poetry_add():
            Path("poetry.lock").write_text("# verrou\n")
            return True

        with (
            mock.patch.object(sys, "argv", ["poetry_update.py", "-f"]),
            mock.patch.object(poetry_update, "combine_requirements"),
            mock.patch.object(
                poetry_update,
                "call_poetry_add_build_dependency",
                side_effect=poetry_add,
            ),
            mock.patch.object(
                poetry_update, "apply_marker_variants", return_value=False
            ),
        ):
            poetry_update.main()

    def test_une_version_nouvelle_voit_son_verrou_range(self):
        cible = Path(f"requirement/poetry.{VERSION}.lock")
        self.assertFalse(cible.exists())
        self._main_qui_produit_un_verrou()
        self.assertTrue(cible.is_file())
        self.assertTrue(Path("poetry.lock").is_symlink())

    def test_un_verrou_existant_est_remplace(self):
        cible = Path(f"requirement/poetry.{VERSION}.lock")
        cible.write_text("# ancien\n")
        self._main_qui_produit_un_verrou()
        self.assertEqual("# verrou\n", cible.read_text())


if __name__ == "__main__":
    unittest.main()
