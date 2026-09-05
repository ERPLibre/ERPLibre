#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'hôte retenu d'une appliance : deux étages, et ce qui les sépare.

Le cache de processus rend la lecture gratuite ; la préférence la fait
survivre à la fermeture du menu. Oublier doit vider les DEUX, sans quoi le
choix revient au prochain démarrage et l'oubli n'a pas eu lieu.
"""

import os
import sys
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.remote.host_memory import HostMemory  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


class MemoireCase(unittest.TestCase):
    """Les préférences sont remplacées par un dictionnaire de banc."""

    def setUp(self):
        self.prefs = {}
        patcheur = patch.multiple(
            "script.remote.host_memory.todo_prefs",
            get=lambda cle, defaut=None: self.prefs.get(cle, defaut),
            set=lambda cle, valeur: self.prefs.__setitem__(cle, valeur),
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "fr"


class TestLesDeuxEtages(MemoireCase):
    def test_nothing_remembered_answers_none(self):
        """Un None dit à l'appelant qu'il a une question à poser."""
        self.assertIsNone(HostMemory("appliance-a").get())

    def test_what_is_remembered_comes_back(self):
        memoire = HostMemory("appliance-a")
        memoire.remember({"target": "machine", "jump": ""})
        self.assertEqual("machine", memoire.get()["target"])

    def test_it_survives_a_new_instance(self):
        """C'est tout l'intérêt de la préférence : le menu se referme."""
        HostMemory("appliance-a").remember({"target": "machine"})
        self.assertEqual("machine", HostMemory("appliance-a").get()["target"])

    def test_forgetting_clears_both_floors(self):
        """Vider le cache seul ferait revenir le choix au redémarrage."""
        memoire = HostMemory("appliance-a")
        memoire.remember({"target": "machine"})
        memoire.forget()
        self.assertIsNone(memoire.get())
        self.assertIsNone(HostMemory("appliance-a").get())

    def test_an_entry_without_a_target_is_not_a_host(self):
        """Une préférence vidée laisse un dictionnaire, pas une absence."""
        self.prefs["appliance-a"] = {}
        self.assertIsNone(HostMemory("appliance-a").get())

    def test_two_appliances_do_not_overwrite_each_other(self):
        """Une clé unique les ferait s'écraser sur la même station."""
        HostMemory("appliance-a").remember({"target": "machine-a"})
        HostMemory("appliance-b").remember({"target": "machine-b"})
        self.assertEqual(
            "machine-a", HostMemory("appliance-a").get()["target"]
        )
        self.assertEqual(
            "machine-b", HostMemory("appliance-b").get()["target"]
        )


class TestLeLibelle(MemoireCase):
    def test_no_host_is_an_empty_label(self):
        self.assertEqual("", HostMemory("appliance-a").label(None))
        self.assertEqual("", HostMemory("appliance-a").label({}))

    def test_the_target_alone_is_enough(self):
        memoire = HostMemory("appliance-a")
        self.assertEqual("machine", memoire.label({"target": "machine"}))

    def test_the_jump_is_named_when_there_is_one(self):
        memoire = HostMemory("appliance-a")
        libelle = memoire.label({"target": "machine", "jump": "rebond"})
        self.assertIn("machine", libelle)
        self.assertIn("rebond", libelle)

    def test_the_version_carries_the_product_short_name(self):
        memoire = HostMemory("appliance-a", "PVE")
        self.assertIn(
            "PVE 9.2", memoire.label({"target": "machine", "version": "9.2"})
        )

    def test_without_a_short_name_the_version_stays_out(self):
        """Une appliance qui n'en déclare pas n'affiche pas « None 9.2 »."""
        memoire = HostMemory("appliance-a")
        libelle = memoire.label({"target": "machine", "version": "9.2"})
        self.assertEqual("machine", libelle)

    def test_a_missing_target_is_said_and_not_crashed(self):
        self.assertEqual("?", HostMemory("appliance-a").label({"jump": ""}))


class TestElleNeDemandeRien(unittest.TestCase):
    """Choisir un hôte est une conversation, et elle appartient au menu."""

    def test_the_module_neither_prints_nor_prompts(self):
        import ast

        chemin = os.path.join(RACINE, "script", "remote", "host_memory.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertNotIn("print", appels)
        self.assertNotIn("input", appels)


if __name__ == "__main__":
    unittest.main()
