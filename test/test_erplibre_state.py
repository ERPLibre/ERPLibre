#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état du checkout : ce qui s'écrit, et ce qui se relit.

LE CHAMP QUE RIEN N'ÉCRIVAIT. `print_state` annonce « Mobile context »
depuis toujours, et son écrivain n'avait aucun appelant : la ligne disait
donc « inactive » sur tout poste, pour toujours, quelle que soit la
réalité. Un champ qu'aucun chemin ne remplit ne rapporte pas un état, il
rapporte son propre défaut.

Le module n'avait aucune épreuve. Ces quelques-là tiennent l'aller-retour
et le câblage.

Rien n'est lancé : l'état vit dans un fichier, et le fichier est isolé.
"""

import ast
import io
import json
import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.version import erplibre_state as E  # noqa: E402


class EtatIsole(unittest.TestCase):
    """Chaque épreuve écrit dans son propre fichier, jamais dans celui du
    checkout — l'état porte la version Odoo active."""

    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        self.avant = E.STATE_FILE
        E.STATE_FILE = os.path.join(self.dossier.name, "etat.json")
        self.addCleanup(setattr, E, "STATE_FILE", self.avant)


class TestLeContexteMobileSEcritEtSeRelit(EtatIsole):
    def test_a_fresh_checkout_reads_inactive(self):
        """Le défaut, et il est honnête : rien n'a encore été lancé."""
        self.assertFalse(E.get_mobile_active())

    def test_what_is_recorded_is_what_is_read_back(self):
        E.set_mobile_active(True)
        self.assertTrue(E.get_mobile_active())
        E.set_mobile_active(False)
        self.assertFalse(E.get_mobile_active())

    def test_an_active_context_dates_its_installation(self):
        """Savoir QUE c'est actif ne dit pas depuis quand, et la date est
        ce qui distingue un lancement d'hier d'un lancement d'il y a un an."""
        E.set_mobile_active(True)
        etat = json.load(io.open(E.STATE_FILE, encoding="utf-8"))
        self.assertIn("installed_at", etat["mobile"])

    def test_turning_it_off_keeps_the_rest_of_the_state(self):
        E.set_version_installed("18.0", True)
        E.set_mobile_active(False)
        self.assertTrue(E.get_version_installed("18.0"))


class TestLeCablageDuLancementMobile(unittest.TestCase):
    """L'état suit le LANCEMENT, et non l'intention.

    Le callback capturait déjà le code de sortie de « compile_and_run.sh »
    dans une variable qu'il n'a jamais relue — la même famille de défaut
    que la restauration, où une variable portait six sens.
    """

    @staticmethod
    def _corps(nom):
        chemin = os.path.join(RACINE, "script", "todo", "todo.py")
        arbre = ast.parse(io.open(chemin, encoding="utf-8").read())
        trouves = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef) and n.name == nom
        ]
        assert len(trouves) == 1, nom
        return trouves[0]

    def test_the_callback_records_the_mobile_context(self):
        corps = self._corps("callback_make_mobile_home")
        appels = [
            n.func.attr
            for n in ast.walk(corps)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertIn("set_mobile_active", appels)


if __name__ == "__main__":
    unittest.main()
