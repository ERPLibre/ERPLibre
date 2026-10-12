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
import sys
import tempfile
import unittest
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
            P.resolve_marker("paquet==1.2.3", "3.12.10"),
            ("paquet==1.2.3", None, ""),
        )

    def test_python_version_marker_of_the_target_is_kept_bare(self):
        self.assertEqual(
            P.resolve_marker(
                "paquet==2.0.0 ; python_version >= '3.12'", "3.12.10"
            ),
            ("paquet==2.0.0", "paquet", ""),
        )

    def test_python_version_marker_of_another_python_is_dropped(self):
        self.assertIsNone(
            P.resolve_marker(
                "paquet==1.0.0; python_version < '3.12'", "3.12.10"
            )
        )

    def test_target_python_wins_over_the_running_one(self):
        # Le Python qui lance le script n'a pas d'importance : la cible 3.8
        # retient la branche « < 3.12 », quel que soit l'interpréteur courant.
        self.assertEqual(
            P.resolve_marker(
                "paquet==1.0.0; python_version < '3.12'", "3.8.20"
            ),
            ("paquet==1.0.0", "paquet", ""),
        )

    def test_platform_machine_marker_is_kept_for_poetry(self):
        line, name, marker = P.resolve_marker(
            "paquet>=6.8 ; platform_machine != 's390x'", "3.12.10"
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
        self.assertEqual(
            P.version_clauses("paquet==2.0.*"), [("==", P.Version("2.0"))]
        )
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
            set_version_odoo="18.0", set_version_python="3.12.10"
        )

    def test_marker_lines_join_the_bare_name(self):
        dct = defaultdict(set)
        dct["paquet"].add("paquet==3.0.0")
        result = P.get_manifest_external_dependencies(
            self.config, dct, LST_SIGN
        )
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


if __name__ == "__main__":
    unittest.main()
