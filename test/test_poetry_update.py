#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Marqueurs d'environnement dans la génération du pyproject.

`resolve_marker()` évalue un marqueur « python_version » contre le Python
CIBLE, et conserve tel quel un marqueur « platform_machine ». Les deux
sources de dépendances y passent : les requirements.txt et les
`external_dependencies` des manifests. Une ligne de manifest non évaluée
deviendrait une clé à part, hors de l'arbitrage des versions, et parviendrait
brute à « poetry add », qui garde la dernière contrainte d'un même nom.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from collections import defaultdict
from types import SimpleNamespace

# poetry_update importe « iscompatible », module voisin qu'il trouve parce
# qu'il se lance depuis script/poetry/.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "script",
        "poetry",
    ),
)

from script.poetry import poetry_update as P  # noqa: E402

LST_SIGN = ("==", "!=", ">=", "<=", "<", ">", ";", "~=")


class TestResolveMarker(unittest.TestCase):
    def test_line_without_marker_is_unchanged(self):
        self.assertEqual(
            P.resolve_marker("paquet==1.2.3", "3.12.16"),
            ("paquet==1.2.3", None, ""),
        )

    def test_python_version_marker_of_the_target_is_kept_bare(self):
        self.assertEqual(
            P.resolve_marker("paquet==2.0.0 ; python_version >= '3.12'", "3.12.16"),
            ("paquet==2.0.0", "paquet", ""),
        )

    def test_python_version_marker_of_another_python_is_dropped(self):
        self.assertIsNone(
            P.resolve_marker("paquet==1.0.0; python_version < '3.12'", "3.12.16")
        )

    def test_target_python_wins_over_the_running_one(self):
        # Le Python qui lance le script n'a pas d'importance : la cible 3.8
        # retient la branche « < 3.12 », quel que soit l'interpréteur courant.
        self.assertEqual(
            P.resolve_marker("paquet==1.0.0; python_version < '3.12'", "3.8.20"),
            ("paquet==1.0.0", "paquet", ""),
        )

    def test_platform_machine_marker_is_kept_for_poetry(self):
        line, name, marker = P.resolve_marker(
            "paquet>=6.8 ; platform_machine != 's390x'", "3.12.16"
        )
        self.assertEqual(name, "paquet")
        self.assertEqual(marker, 'platform_machine != "s390x"')
        self.assertEqual(line, 'paquet>=6.8 ; platform_machine != "s390x"')


class TestVersionClauses(unittest.TestCase):
    def test_every_clause_of_a_range_is_kept(self):
        self.assertEqual(
            P.version_clauses("paquet>=1.7.1,<2.9.0"),
            [(">=", P.Version("1.7.1")), ("<", P.Version("2.9.0"))],
        )

    def test_spaces_around_the_comma_are_accepted(self):
        self.assertEqual(
            P.version_clauses("paquet>=1.0, <2"),
            [(">=", P.Version("1.0")), ("<", P.Version("2"))],
        )

    def test_single_clause_and_wildcard(self):
        self.assertEqual(P.version_clauses("paquet==2.0.*"), [("==", P.Version("2.0"))])
        self.assertEqual(
            P.version_clauses("paquet==3.0.0b7"),
            [("==", P.Version("3.0.0b7"))],
        )

    def test_name_without_version_has_no_clause(self):
        self.assertEqual(P.version_clauses("paquet"), [])


class TestManifestExternalDependencies(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(tmp.name)
        module = os.path.join("odoo18.0", "addons", "depot", "module_a")
        os.makedirs(module)
        os.makedirs(os.path.join("odoo18.0", "odoo"))
        with open(os.path.join(module, "__manifest__.py"), "w") as f:
            f.write(
                "{'name': 'module_a', 'external_dependencies': {'python': ["
                "\"paquet==1.0.0; python_version < '3.12'\", "
                "\"paquet==2.0.0 ; python_version >= '3.12'\", "
                "\"autre>=6.8 ; platform_machine != 's390x'\""
                "]}}"
            )
        self.config = SimpleNamespace(
            set_version_odoo="18.0", set_version_python="3.12.16"
        )

    def test_marker_lines_join_the_bare_name(self):
        dct = defaultdict(set)
        dct["paquet"].add("paquet==3.0.0")
        result = P.get_manifest_external_dependencies(self.config, dct, LST_SIGN)
        # La branche de la cible rejoint la clé « paquet », où l'arbitrage
        # des versions la confronte à l'épingle déjà présente ; l'autre part.
        self.assertEqual(result["paquet"], {"paquet==3.0.0", "paquet==2.0.0"})
        self.assertFalse(
            [k for k in result if k.startswith("paquet") and k != "paquet"]
        )

    def test_platform_machine_line_keeps_its_marker_key(self):
        result = P.get_manifest_external_dependencies(
            self.config, defaultdict(set), LST_SIGN
        )
        self.assertEqual(
            result['autre ; platform_machine != "s390x"'],
            {'autre>=6.8 ; platform_machine != "s390x"'},
        )


class TestMinReleaseAgeExemption(unittest.TestCase):
    """poetry.toml fait attendre 7 jours toute version ; les épingles « == »
    du fichier d'ERPLibre, décisions relues, y échappent."""

    LIGNES = (
        "pypdf==6.21.4\n"
        "Pillow==13.0.0 ; python_version >= '3.12'\n"
        "lxml_html_clean==0.4.6\n"
        "setuptools==84.0.0  # outillage\n"
        "pandas===3.0.6\n"
        "requests>=2\n"
        "# certifi==2026.1.1\n"
        "foo\n"
        "-r autre.txt\n"
        "zed @ git+https://example.invalid/zed.git\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fichier = os.path.join(self.tmp.name, "requirements.txt")
        with open(self.fichier, "w") as f:
            f.write(self.LIGNES)

    def test_pinned_names_are_normalized(self):
        self.assertEqual(
            P.pinned_packages(self.fichier),
            ["lxml-html-clean", "pandas", "pillow", "pypdf", "setuptools"],
        )

    def test_exemption_merges_with_the_environment(self):
        with mock.patch.dict(
            os.environ, {P.ENV_MIN_RELEASE_AGE_EXCLUDE: "numpy, pypdf"}
        ):
            P.exempt_pins_from_min_release_age(self.fichier)
            self.assertEqual(
                os.environ[P.ENV_MIN_RELEASE_AGE_EXCLUDE],
                "lxml-html-clean,numpy,pandas,pillow,pypdf,setuptools",
            )

    def test_missing_file_sets_nothing(self):
        with mock.patch.dict(os.environ, clear=False):
            os.environ.pop(P.ENV_MIN_RELEASE_AGE_EXCLUDE, None)
            absent = os.path.join(self.tmp.name, "absent.txt")
            self.assertEqual(P.exempt_pins_from_min_release_age(absent), [])
            self.assertNotIn(P.ENV_MIN_RELEASE_AGE_EXCLUDE, os.environ)

    def test_poetry_toml_sets_seven_days(self):
        import tomllib

        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, "poetry.toml"), "rb") as f:
            conf = tomllib.load(f)
        self.assertEqual(conf["solver"]["min-release-age"], 7)


class TestPoetryAddFailure(unittest.TestCase):
    """« poetry add » refusé : le pyproject retrouve ses dépendances, et le
    script sort en erreur au lieu de rendre 0 sur un pyproject vidé."""

    def test_pyproject_restored_and_exit_code(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            pyproject = os.path.join(tmp, "pyproject.toml")
            contenu = (
                '[tool.poetry]\nname = "x"\n\n'
                '[tool.poetry.dependencies]\npython = ">=3.12,<3.13"\n'
                'requests = "2.34.2"\n'
            )
            with open(pyproject, "w") as fh:
                fh.write(contenu)
            config = SimpleNamespace(
                dir=tmp + os.sep,
                dry=False,
                force=False,
                set_version_poetry="2.1.3",
                set_version_odoo="18.0",
                set_version_python="3.12.16",
                set_version_erplibre="odoo18.0_python3.12.16",
            )
            with patch.object(P, "get_config", return_value=config), patch.object(
                P, "combine_requirements"
            ), patch.object(
                P,
                "call_poetry_add_build_dependency",
                return_value=False,
            ):
                with self.assertRaises(SystemExit) as fin:
                    P.main()
            self.assertEqual(fin.exception.code, 1)
            with open(pyproject) as fh:
                self.assertEqual(fh.read(), contenu)


class TestRestoreLockLink(unittest.TestCase):
    """« -f » retire le lien « ./poetry.lock » ; restore_lock_link le rend,
    que le verrou de requirement/ existe encore ou non."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_lock_link_")
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.racine = os.path.join(self.dossier, "poetry.lock")
        os.makedirs(os.path.join(self.dossier, "requirement"))
        self.cible = os.path.join(self.dossier, "requirement", "poetry.X.lock")

    def ecrire(self, chemin, contenu):
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)

    def lire(self, chemin):
        with open(chemin, encoding="utf-8") as fh:
            return fh.read()

    def test_vrai_fichier_remplace_le_verrou_de_requirement(self):
        self.ecrire(self.cible, "ancien")
        self.ecrire(self.racine, "nouveau")
        self.assertTrue(P.restore_lock_link(self.racine, self.cible))
        self.assertTrue(os.path.islink(self.racine))
        self.assertEqual("nouveau", self.lire(self.cible))
        self.assertEqual("nouveau", self.lire(self.racine))

    def test_verrou_de_requirement_absent(self):
        self.ecrire(self.racine, "nouveau")
        self.assertTrue(P.restore_lock_link(self.racine, self.cible))
        self.assertTrue(os.path.islink(self.racine))
        self.assertEqual("nouveau", self.lire(self.cible))

    def test_lien_deja_en_place_laisse_tel_quel(self):
        self.ecrire(self.cible, "verrou")
        os.symlink(self.cible, self.racine)
        self.assertFalse(P.restore_lock_link(self.racine, self.cible))
        self.assertEqual("verrou", self.lire(self.cible))

    def test_racine_sans_verrou(self):
        self.assertFalse(P.restore_lock_link(self.racine, self.cible))
        self.assertFalse(os.path.lexists(self.racine))


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
        with mock.patch.object(sys, "argv", ["P.py", "--dry"]):
            return P.get_config()

    def _dependances(self):
        return Path(f".venv.{VERSION}/build_dependency.txt").read_text()


class TestCheminsLocaux(Arbre):
    def test_une_ligne_chemin_n_arrete_plus_l_assemblage(self):
        Path("odoo19.0/odoo/requirements.txt").write_text(
            "/home/pi/iot/aiortc-1.4.0-py3-none-any.whl;"
            ' sys_platform == "linux"\n'
            "lxml==5.2.1\n"
        )
        P.combine_requirements(self._config())
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
        P.combine_requirements(self._config())
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
        P.combine_requirements(self._config())
        self.assertIn("invoice2data", self._dependances())


class TestLignesDOdoo8Et9(Arbre):
    """Deux formes que portent les dépôts d'Odoo 8 et 9."""

    def test_les_espaces_autour_de_l_operateur_sont_retires(self):
        # « poetry add » 1.1 refuse « pycountry >= 0.19 » d'un ValueError.
        Path("odoo19.0/odoo/requirements.txt").write_text(
            "pycountry >= 0.19\ninvoice2data >= 0.2.74 , <= 0.3.4\n"
        )
        P.combine_requirements(self._config())
        dependances = self._dependances().splitlines()
        self.assertIn("pycountry>=0.19", dependances)
        self.assertIn("invoice2data>=0.2.74,<=0.3.4", dependances)

    def test_un_manifeste_openerp_declare_ses_dependances(self):
        """Odoo 8 et 9 ne lisent que __openerp__.py."""
        module = Path("odoo19.0/addons/OCA_x/module_x")
        module.mkdir(parents=True)
        (module / "__openerp__.py").write_text(
            "{'name': 'x', 'external_dependencies': {'python': ['unidecode']}}"
        )
        self.assertIn(
            str(module / "__openerp__.py"),
            [str(f) for f in P.get_lst_manifest_py(self._config())],
        )


if __name__ == "__main__":
    unittest.main()
