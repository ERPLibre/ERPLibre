#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le branchement de la migration sur le cluster PostgreSQL 16.

La préférence choisit au début d'une migration ; le choix se garde pour la
reprise. Une sauvegarde d'un PostgreSQL plus récent que 16 reste sur le
serveur du système. Un nom de base déjà porté par le serveur du système
est refusé : les deux serveurs partagent le filestore par nom.
"""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.todo import todo_upgrade  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402

MC = todo_upgrade.migration_cluster


class Base(unittest.TestCase):
    def setUp(self):
        self.env_avant = {k: os.environ.get(k) for k in ("PGHOST", "PGPORT")}
        self.addCleanup(self.remettre)
        self.upgrade = TodoUpgrade.__new__(TodoUpgrade)
        self.upgrade.dct_progression = {}
        self.upgrade.file_path = "/b.zip"
        self.upgrade.write_config = lambda: None

    def remettre(self):
        for cle, valeur in self.env_avant.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur

    def brancher(self, pref="16", dump=16, bindir="/b", demarre=0):
        with mock.patch.object(
            todo_upgrade.todo_prefs, "get", return_value=pref
        ), mock.patch.object(
            MC, "version_du_dump", return_value=dump
        ), mock.patch.object(
            MC, "trouver_bindir", return_value=bindir
        ), mock.patch.object(
            MC, "demarrer", return_value=demarre
        ) as demarrer, redirect_stdout(
            io.StringIO()
        ) as sortie:
            rendu = self.upgrade.use_migration_cluster()
        return rendu, demarrer, sortie.getvalue()


class TestLeChoix(Base):
    def test_la_preference_systeme_ne_touche_a_rien(self):
        os.environ.pop("PGPORT", None)
        rendu, demarrer, _ = self.brancher(pref="system")
        self.assertTrue(rendu)
        self.assertEqual({}, self.upgrade.dct_progression["config_pg_cluster"])
        demarrer.assert_not_called()
        self.assertNotIn("PGPORT", os.environ)

    def test_un_dump_de_postgresql_18_reste_sur_le_systeme(self):
        rendu, demarrer, sortie = self.brancher(dump=18)
        self.assertTrue(rendu)
        self.assertEqual({}, self.upgrade.dct_progression["config_pg_cluster"])
        demarrer.assert_not_called()
        self.assertIn("18", sortie)

    def test_un_dump_de_16_part_sur_le_cluster(self):
        rendu, demarrer, _ = self.brancher()
        self.assertTrue(rendu)
        demarrer.assert_called_once()
        self.assertEqual(str(MC.PORT), os.environ["PGPORT"])
        self.assertTrue(os.environ["PGHOST"].endswith("run"))

    def test_sans_binaires_la_migration_s_arrete(self):
        rendu, _, sortie = self.brancher(bindir=None)
        self.assertFalse(rendu)
        self.assertIn("install_postgresql_migration.sh", sortie)

    def test_un_cluster_qui_ne_demarre_pas_arrete_tout(self):
        rendu, _, _ = self.brancher(demarre=1)
        self.assertFalse(rendu)


class TestLaReprise(Base):
    def test_le_choix_garde_prime_sur_la_preference(self):
        self.upgrade.dct_progression["config_pg_cluster"] = {
            "root": "/r",
            "port": 5499,
        }
        rendu, demarrer, _ = self.brancher(pref="system")
        self.assertTrue(rendu)
        demarrer.assert_called_once_with("/b", "/r", 5499)
        self.assertEqual("5499", os.environ["PGPORT"])


def psql_disponible():
    try:
        return (
            subprocess.run(
                ["psql", "-X", "-w", "-d", "postgres", "-Atc", "select 1"],
                capture_output=True,
                timeout=20,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


@unittest.skipUnless(psql_disponible(), "pas de PostgreSQL joignable")
class TestLesNomsDuSysteme(unittest.TestCase):
    BASES = (
        "_erplibre_nom_x",
        "_erplibre_nom_x_neutralize",
        "_erplibre_nomAx",
    )

    @classmethod
    def setUpClass(cls):
        for base in cls.BASES:
            subprocess.run(["createdb", base], capture_output=True)

    @classmethod
    def tearDownClass(cls):
        for base in cls.BASES:
            subprocess.run(
                ["dropdb", "--if-exists", base], capture_output=True
            )

    def noms(self, nom, cluster=True):
        upgrade = TodoUpgrade.__new__(TodoUpgrade)
        upgrade.dct_progression = {
            "config_pg_cluster": {"root": "/r", "port": 1} if cluster else {}
        }
        return upgrade.names_on_system_server(nom)

    def test_la_base_et_ses_derivees(self):
        self.assertEqual(
            ["_erplibre_nom_x", "_erplibre_nom_x_neutralize"],
            self.noms("_erplibre_nom_x"),
        )

    def test_le_souligne_n_est_pas_un_joker(self):
        # « _erplibre_nomAx » ne doit pas répondre pour « _erplibre_nom_x ».
        self.assertNotIn("_erplibre_nomAx", self.noms("_erplibre_nom_x"))

    def test_hors_cluster_rien_n_est_verifie(self):
        self.assertEqual([], self.noms("_erplibre_nom_x", cluster=False))

    def test_un_nom_douteux_n_entre_pas_dans_la_requete(self):
        self.assertEqual([], self.noms("x' OR '1'='1"))


if __name__ == "__main__":
    unittest.main()
