#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le module de compatibilité chargé pendant OpenUpgrade.

PostgreSQL 18 catalogue les NOT NULL dans pg_constraint ; le
lift_constraints d'openupgradelib les ramasse, et sur une clé primaire
PostgreSQL refuse de retirer le NOT NULL avant la clé. La version du
module les exclut. Elle tourne ici contre le PostgreSQL local, par psql.
"""

import importlib.util
import os
import subprocess
import sys
import types
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.todo.todo_upgrade import (  # noqa: E402
    OPENUPGRADE_COMPAT_MODULE,
    openupgrade_addons,
)

MODULE = os.path.join(
    RACINE,
    "script",
    "odoo",
    "openupgrade_addons",
    OPENUPGRADE_COMPAT_MODULE,
    "__init__.py",
)
BASE = "_erplibre_test_openupgrade_compat"


class AsIs:
    def __init__(self, valeur):
        self.valeur = valeur


def charger(openupgradelib=None):
    """Importe le module avec un faux psycopg2 et, au besoin, un faux
    openupgradelib ; rend le module."""
    faux = types.ModuleType("psycopg2.extensions")
    faux.AsIs = AsIs
    anciens = {
        nom: sys.modules.get(nom)
        for nom in ("psycopg2", "psycopg2.extensions", "openupgradelib")
    }
    sys.modules["psycopg2"] = types.ModuleType("psycopg2")
    sys.modules["psycopg2.extensions"] = faux
    if openupgradelib is not None:
        paquet = types.ModuleType("openupgradelib")
        paquet.openupgrade = openupgradelib
        sys.modules["openupgradelib"] = paquet
        sys.modules["openupgradelib.openupgrade"] = openupgradelib
    try:
        spec = importlib.util.spec_from_file_location("compat_test", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for nom, valeur in anciens.items():
            if valeur is None:
                sys.modules.pop(nom, None)
            else:
                sys.modules[nom] = valeur
        sys.modules.pop("openupgradelib.openupgrade", None)


def psql_disponible():
    try:
        done = subprocess.run(
            ["psql", "-X", "-w", "-d", "postgres", "-Atc", "select 1"],
            capture_output=True,
            timeout=20,
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class CurseurPsql:
    """Le strict nécessaire d'un curseur psycopg2, par psql."""

    def __init__(self, base):
        self.base = base
        self.lignes = []

    def execute(self, requete, parametres=None):
        if isinstance(parametres, dict):
            requete = requete % {
                cle: "'%s'" % valeur for cle, valeur in parametres.items()
            }
        elif parametres:
            requete = requete % tuple(p.valeur for p in parametres)
        done = subprocess.run(
            ["psql", "-X", "-w", "-q", "-At", "-v", "ON_ERROR_STOP=1"]
            + ["-d", self.base, "-c", requete],
            capture_output=True,
            text=True,
        )
        if done.returncode:
            raise RuntimeError(done.stderr)
        self.lignes = [
            (nom, valeurs.strip("{}").split(","))
            for nom, valeurs in (
                ligne.split("|", 1) for ligne in done.stdout.splitlines()
            )
        ]

    def fetchall(self):
        return self.lignes


class TestLeRemplacement(unittest.TestCase):
    def test_une_bibliotheque_sans_filtre_est_corrigee(self):
        bibliotheque = types.ModuleType("openupgrade")
        exec(
            "def lift_constraints(cr, table, column, cascade=False):\n"
            "    return 'amont'\n",
            bibliotheque.__dict__,
        )
        module = charger(bibliotheque)
        self.assertIs(module.lift_constraints, bibliotheque.lift_constraints)

    def test_une_bibliotheque_deja_corrigee_est_laissee(self):
        module = charger()
        bibliotheque = types.ModuleType("openupgrade")
        bibliotheque.lift_constraints = module.lift_constraints
        self.assertEqual([], module.appliquer(bibliotheque))

    def test_sans_openupgradelib_rien_ne_casse(self):
        self.assertTrue(callable(charger().lift_constraints))


@unittest.skipUnless(psql_disponible(), "pas de PostgreSQL joignable")
class TestSurUneClePrimaire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)
        done = subprocess.run(["createdb", BASE], capture_output=True)
        if done.returncode:
            raise unittest.SkipTest("createdb refusé")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["dropdb", "--if-exists", BASE], capture_output=True)

    def setUp(self):
        self.curseur = CurseurPsql(BASE)
        self.curseur.execute(
            "DROP TABLE IF EXISTS enfant, parent;"
            " CREATE TABLE parent (id serial PRIMARY KEY, x int);"
            " CREATE TABLE enfant (id serial PRIMARY KEY,"
            " parent_id int REFERENCES parent(id));"
        )

    def lire(self, requete):
        return subprocess.run(
            ["psql", "-X", "-w", "-At", "-d", BASE, "-c", requete],
            capture_output=True,
            text=True,
        ).stdout.strip()

    def test_la_cle_et_la_reference_tombent_le_not_null_reste(self):
        charger().lift_constraints(self.curseur, "parent", "id", cascade=True)
        self.assertEqual(
            "",
            self.lire(
                "SELECT conname FROM pg_constraint WHERE contype IN"
                " ('p', 'f') AND conrelid::regclass::text"
                " IN ('parent', 'enfant') AND conname <> 'enfant_pkey'"
            ),
        )
        self.assertEqual(
            "t",
            self.lire(
                "SELECT attnotnull FROM pg_attribute WHERE attrelid ="
                " 'parent'::regclass AND attname = 'id'"
            ),
        )


class TestLesCheminsDAddons(unittest.TestCase):
    def test_jusqu_a_13_l_arbre_complet(self):
        chemins = openupgrade_addons("/ou", 13).split(",")
        self.assertEqual("/ou", chemins[0])
        self.assertIn("/ou/addons", chemins)
        self.assertNotIn("openupgrade_addons", ",".join(chemins))

    def test_depuis_14_le_module_de_compatibilite(self):
        chemins = openupgrade_addons("/ou", 19, racine=RACINE).split(",")
        self.assertEqual("/ou", chemins[0])
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    chemins[1], OPENUPGRADE_COMPAT_MODULE, "__manifest__.py"
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
