#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cluster PostgreSQL de migration, possédé par le compte ERPLibre.

La détection se teste avec de faux binaires ; le démarrage, avec les vrais
binaires du serveur de l'hôte, sur un port et un répertoire jetables.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.database import migration_cluster as cluster  # noqa: E402


def faux_bindir(dossier, version):
    """Un répertoire de binaires dont postgres annonce cette version."""
    os.makedirs(dossier)
    for nom in cluster.EXECUTABLES:
        chemin = os.path.join(dossier, nom)
        with open(chemin, "w") as handle:
            handle.write(
                "#!/bin/sh\n" f'echo "postgres (PostgreSQL) {version}.4"\n'
            )
        os.chmod(chemin, 0o755)
    return dossier


class Temporaire(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier)


class TestLaDetection(Temporaire):
    def test_la_variable_passe_devant_tout(self):
        lst = cluster.candidats_bindir(
            16, {"EL_PG16_BINDIR": "/a", "PATH": ""}
        )
        self.assertEqual("/a", lst[0])
        self.assertIn("/usr/lib/postgresql/16/bin", lst)
        self.assertIn("/opt/postgresql16/bin", lst)

    def test_seul_un_serveur_16_est_retenu(self):
        d18 = faux_bindir(os.path.join(self.dossier, "d18"), 18)
        d16 = faux_bindir(os.path.join(self.dossier, "d16"), 16)
        env = {"EL_PG16_BINDIR": d18, "PATH": ""}
        self.assertIsNone(cluster.trouver_bindir(16, env))
        env["EL_PG16_BINDIR"] = d16
        self.assertEqual(d16, cluster.trouver_bindir(16, env))

    def test_un_repertoire_incomplet_est_ecarte(self):
        d16 = faux_bindir(os.path.join(self.dossier, "d16"), 16)
        os.remove(os.path.join(d16, "pg_ctl"))
        env = {"EL_PG16_BINDIR": d16, "PATH": ""}
        self.assertIsNone(cluster.trouver_bindir(16, env))


class TestLeDump(Temporaire):
    def archive(self, tete):
        chemin = os.path.join(self.dossier, "b.zip")
        with zipfile.ZipFile(chemin, "w") as archive:
            archive.writestr("dump.sql", tete + "\nCREATE TABLE x ();\n")
        return chemin

    def test_la_version_d_origine_est_lue(self):
        chemin = self.archive("-- Dumped from database version 18.6")
        self.assertEqual(18, cluster.version_du_dump(chemin))

    def test_sans_en_tete_rien(self):
        self.assertIsNone(cluster.version_du_dump(self.archive("-- rien")))

    def test_un_fichier_absent_rend_rien(self):
        absent = os.path.join(self.dossier, "absent.zip")
        self.assertIsNone(cluster.version_du_dump(absent))


class TestLEnvironnement(Temporaire):
    def test_le_socket_est_dans_le_cluster(self):
        env = cluster.environnement(self.dossier, 5433)
        self.assertEqual(os.path.join(self.dossier, "run"), env["PGHOST"])
        self.assertEqual("5433", env["PGPORT"])


def binaires_hote():
    bindir = "/usr/bin"
    if all(
        os.access(os.path.join(bindir, nom), os.X_OK)
        for nom in cluster.EXECUTABLES
    ) and shutil.which("psql"):
        return bindir
    return None


@unittest.skipUnless(binaires_hote(), "pas de serveur PostgreSQL sur l'hôte")
class TestUnVraiCluster(Temporaire):
    """Initialise, démarre, interroge et arrête un cluster jetable."""

    PORT = 55433

    def test_demarrer_puis_arreter(self):
        bindir = binaires_hote()
        racine = os.path.join(self.dossier, "pg")
        self.addCleanup(cluster.arreter, bindir, racine)
        self.assertEqual(0, cluster.demarrer(bindir, racine, self.PORT))
        self.assertTrue(cluster.en_marche(bindir, racine))
        env = dict(os.environ, **cluster.environnement(racine, self.PORT))
        done = subprocess.run(
            ["psql", "-X", "-w", "-d", "postgres", "-Atc", "select 1"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual("1", done.stdout.strip(), done.stderr)
        # Relancer sur un cluster qui tourne ne fait rien.
        self.assertEqual(0, cluster.demarrer(bindir, racine, self.PORT))
        self.assertEqual(0, cluster.arreter(bindir, racine))
        self.assertFalse(cluster.en_marche(bindir, racine))


if __name__ == "__main__":
    unittest.main()
