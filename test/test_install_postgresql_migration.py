#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation des binaires PostgreSQL 16 du cluster de migration.

Le script tourne pour de vrai, dans un faux checkout, avec un faux
/etc/os-release et un PATH de commandes factices qui notent leurs appels :
rien n'est installé ni téléchargé.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(
    RACINE, "script", "install", "install_postgresql_migration.sh"
)


class Base(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine)
        self.trace = os.path.join(self.racine, "trace")
        self.faux = os.path.join(self.racine, "bin")
        os.makedirs(self.faux)
        for nom in ("sudo", "makepkg", "apt-get", "nproc"):
            self.commande(nom, f'echo "{nom} $*" >> "{self.trace}"')
        # git clone … <cible> : la cible doit exister pour le « cd » qui suit.
        self.commande(
            "git",
            f'echo "git $*" >> "{self.trace}"; mkdir -p "${{@: -1}}"',
        )
        self.commande("apt-cache", "exit 1")
        python = os.path.join(self.racine, ".venv.erplibre", "bin")
        os.makedirs(python)
        self.commande("python", f'echo "python $*" >> "{self.trace}"', python)

    def commande(self, nom, corps, dossier=None):
        chemin = os.path.join(dossier or self.faux, nom)
        with open(chemin, "w") as handle:
            handle.write("#!/bin/bash\n" + corps + "\n")
        os.chmod(chemin, 0o755)

    def lancer(self, os_release):
        fichier = os.path.join(self.racine, "os-release")
        with open(fichier, "w") as handle:
            handle.write(os_release)
        env = {
            "PATH": self.faux + ":/usr/bin:/bin",
            "HOME": self.racine,
            "EL_OS_RELEASE": fichier,
        }
        done = subprocess.run(
            ["bash", SCRIPT],
            cwd=self.racine,
            env=env,
            capture_output=True,
            text=True,
        )
        trace = ""
        if os.path.exists(self.trace):
            with open(self.trace) as handle:
                trace = handle.read()
        return done, trace


class TestArch(Base):
    def test_l_aur_est_construit_sans_check_world(self):
        done, trace = self.lancer("ID=arch\n")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("https://aur.archlinux.org/postgresql16.git", trace)
        self.assertIn("makepkg -si --noconfirm --needed --nocheck", trace)
        self.assertIn("migration_cluster.py bindir", trace)

    def test_une_derivee_d_arch_suit_la_meme_voie(self):
        _done, trace = self.lancer("ID=endeavouros\nID_LIKE=arch\n")
        self.assertIn("postgresql16.git", trace)


class TestDebian(Base):
    def test_pgdg_puis_postgresql_16(self):
        done, trace = self.lancer("ID=ubuntu\nID_LIKE=debian\n")
        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("pgdg/apt.postgresql.org.sh -y", trace)
        self.assertIn("apt-get install -y postgresql-16", trace)


class TestLeReste(Base):
    def test_fedora_s_arrete_en_le_disant(self):
        done, trace = self.lancer("ID=fedora\n")
        self.assertEqual(1, done.returncode)
        self.assertIn("EL_PG16_BINDIR", done.stderr)
        self.assertNotIn("python", trace)

    def test_le_script_ne_source_jamais_pgenv(self):
        with open(SCRIPT) as handle:
            code = [
                ligne for ligne in handle if not ligne.lstrip().startswith("#")
            ]
        self.assertNotIn("pgenv.sh", "".join(code))


if __name__ == "__main__":
    unittest.main()
