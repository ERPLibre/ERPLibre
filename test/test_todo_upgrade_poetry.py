#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TODO › Code › Mise à jour Poetry : `upgrade_poetry`.

L'entrée laisse les verrous à poetry_update.py -f, qui résout sans le verrou
actuel et rend à « ./poetry.lock » son lien vers requirement/. Effacer le
lien ici faisait écrire à Poetry un vrai fichier à la racine, recopié
ensuite dans requirement/ : deux verrous qui divergeaient. Le nouveau verrou
n'est pas dans le venv d'Odoo tant qu'il n'est pas installé : l'entrée le
propose, sauf quand la mise à jour a échoué.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from script.todo import todo  # noqa: E402

INSTALLER = "EL_PHASE=poetry ./script/install/install_locally.sh"


class TestUpgradePoetry(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_upgrade_poetry_")
        self.addCleanup(shutil.rmtree, self.dossier, True)
        os.makedirs(os.path.join(self.dossier, "requirement"))
        with open(os.path.join(self.dossier, ".erplibre-version"), "w") as fh:
            fh.write("odooX.0_python3.0.0\n")
        self.cible = "./requirement/poetry.odooX.0_python3.0.0.lock"
        with open(os.path.join(self.dossier, self.cible), "w") as fh:
            fh.write("verrou")
        os.symlink(self.cible, os.path.join(self.dossier, "poetry.lock"))
        avant = os.getcwd()
        os.chdir(self.dossier)
        self.addCleanup(os.chdir, avant)
        self.todo = todo.TODO.__new__(todo.TODO)
        self.todo.execute = MagicMock()
        p = patch("builtins.print")
        p.start()
        self.addCleanup(p.stop)

    def lancer(self, statuts, reponses):
        self.todo.execute.exec_command_live.side_effect = list(statuts)
        with patch("builtins.input", side_effect=list(reponses)) as invite:
            self.todo.upgrade_poetry()
        commandes = [
            c.args[0]
            for c in self.todo.execute.exec_command_live.call_args_list
        ]
        return commandes, invite.call_count

    def test_les_verrous_ne_sont_pas_touches(self):
        self.lancer([0, 0], ["n", "n"])
        self.assertTrue(os.path.islink("poetry.lock"))
        with open(self.cible) as fh:
            self.assertEqual("verrou", fh.read())

    def test_la_version_lue_sans_retour_de_ligne(self):
        self.lancer([0, 0], ["n", "n"])
        appel = self.todo.execute.exec_command_live.call_args_list[1]
        self.assertEqual("odooX.0_python3.0.0", appel.kwargs["source_odoo"])

    def test_installation_proposee_et_acceptee(self):
        commandes, _ = self.lancer([0, 0, 0], ["n", "o"])
        self.assertIn("./script/poetry/poetry_update.py -f", commandes[1])
        self.assertEqual(INSTALLER, commandes[-1])

    def test_installation_refusee(self):
        commandes, _ = self.lancer([0, 0], ["n", "n"])
        self.assertNotIn(INSTALLER, commandes)

    def test_echec_de_la_mise_a_jour_ne_propose_rien(self):
        commandes, questions = self.lancer([0, 1], ["n"])
        self.assertEqual(1, questions)
        self.assertNotIn(INSTALLER, commandes)


if __name__ == "__main__":
    unittest.main()
