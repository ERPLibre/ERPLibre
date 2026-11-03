#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La connexion PostgreSQL du conteneur passe par un fichier, pas par argv.

`docker/odoo_rc_db.py` écrit une copie privée de la configuration, complétée
des clés db_* absentes à partir de l'environnement ; `wait-for-psql.py` lit
ces clés avec --config. L'entrypoint ne passe plus aucun identifiant sur une
ligne de commande. Les mots de passe sont inventés.
"""

import configparser
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.append(str(RACINE))


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


odoo_rc_db = charger("odoo_rc_db", RACINE / "docker/odoo_rc_db.py")
ENTREE = (RACINE / "docker/entrypoint.sh").read_text(encoding="utf-8")


class TestOdooRcDb(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_odoo_rc_db_")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.source = os.path.join(self.dossier, "odoo.conf")
        self.cible = os.path.join(self.dossier, "odoo_runtime.conf")
        self.environ = {
            "ERPLIBRE_DB_HOST": "db",
            "ERPLIBRE_DB_PORT": "5432",
            "ERPLIBRE_DB_USER": "odoo",
            "ERPLIBRE_DB_PASSWORD": "mdp%invente;8812",
        }

    def ecrire_source(self, texte):
        with open(self.source, "w", encoding="utf-8") as fichier:
            fichier.write(texte)

    def lire_cible(self):
        config = configparser.RawConfigParser()
        config.read(self.cible)
        return dict(config.items("options"))

    def test_les_cles_absentes_viennent_de_l_environnement(self):
        self.ecrire_source("[options]\nhttp_port = 8069\n")
        odoo_rc_db.completer(self.source, self.cible, self.environ)
        options = self.lire_cible()
        self.assertEqual("8069", options["http_port"])
        self.assertEqual("db", options["db_host"])
        self.assertEqual("mdp%invente;8812", options["db_password"])

    def test_une_cle_de_la_configuration_garde_sa_valeur(self):
        self.ecrire_source("[options]\ndb_host = autre_hote\n")
        odoo_rc_db.completer(self.source, self.cible, self.environ)
        self.assertEqual("autre_hote", self.lire_cible()["db_host"])

    def test_la_copie_est_privee_et_la_source_intacte(self):
        self.ecrire_source("[options]\n")
        avant = Path(self.source).read_bytes()
        odoo_rc_db.completer(self.source, self.cible, self.environ)
        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.cible).st_mode))
        self.assertEqual(avant, Path(self.source).read_bytes())

    def test_une_copie_existante_est_remplacee(self):
        self.ecrire_source("[options]\n")
        odoo_rc_db.completer(self.source, self.cible, self.environ)
        self.environ["ERPLIBRE_DB_HOST"] = "nouvel_hote"
        odoo_rc_db.completer(self.source, self.cible, self.environ)
        self.assertEqual("nouvel_hote", self.lire_cible()["db_host"])

    def test_le_mot_de_passe_ne_passe_pas_par_argv(self):
        """Le script est lancé avec deux chemins : rien d'autre ne peut
        porter le secret sur sa ligne de commande."""
        self.ecrire_source("[options]\n")
        sortie = subprocess.run(
            [
                sys.executable,
                str(RACINE / "docker/odoo_rc_db.py"),
                self.source,
                self.cible,
            ],
            env=dict(os.environ, **self.environ),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertEqual("mdp%invente;8812", self.lire_cible()["db_password"])


class TestEntrypoint(unittest.TestCase):
    def test_aucun_identifiant_sur_une_ligne_de_commande(self):
        self.assertNotIn("DB_ARGS", ENTREE)
        self.assertNotIn("--db_password", ENTREE)
        self.assertIn('wait-for-psql.py --config "$ODOO_RC"', ENTREE)


class TestWaitForPsql(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_wait_psql_")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)

    def lancer(self, *argv):
        return subprocess.run(
            [sys.executable, str(RACINE / "docker/wait-for-psql.py"), *argv],
            capture_output=True,
            text=True,
            timeout=60,
        )

    @unittest.skipUnless(
        importlib.util.find_spec("psycopg2"), "psycopg2 absent de ce venv"
    )
    def test_la_configuration_fournit_la_connexion(self):
        """Port 9 : rien n'y écoute, l'échec vient de la connexion et non
        d'un argument manquant."""
        config = os.path.join(self.dossier, "odoo.conf")
        with open(config, "w", encoding="utf-8") as fichier:
            fichier.write(
                "[options]\ndb_host = 127.0.0.1\ndb_port = 9\n"
                "db_user = essai\ndb_password = mdp-invente\n"
            )
        sortie = self.lancer("--config", config, "--timeout", "1")
        self.assertEqual(1, sortie.returncode)
        self.assertIn("Database connection failure", sortie.stderr)

    def test_sans_connexion_complete_il_refuse(self):
        sortie = self.lancer("--db_host", "127.0.0.1", "--timeout", "1")
        self.assertEqual(2, sortie.returncode)
        self.assertIn("db_password", sortie.stderr)


if __name__ == "__main__":
    unittest.main()
