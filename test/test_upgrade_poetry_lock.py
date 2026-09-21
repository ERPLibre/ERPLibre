#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le lock de référence n'est remplacé que s'il y a de quoi le remplacer.

`requirement/poetry.<version>.lock` est SUIVI par git. Il était retiré
AVANT la commande censée le reconstituer : celle-ci échoue — résolution
impossible, réseau coupé, poetry absent — et le dépôt restait amputé d'un
fichier que personne n'avait demandé à supprimer, sans qu'un mot le dise.
Son code de retour n'était pas lu non plus.

Aucune commande n'est lancée : l'exécution est remplacée, et le répertoire
de travail est un temporaire.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402

VERSION = "odoo18.0_python3.12.10"


class Bancal:
    """Une exécution de banc : elle retient, et rend le code demandé."""

    def __init__(self, code=0, ecrit_le_lock=True, racine=""):
        self.vues = []
        self.code = code
        self.ecrit_le_lock = ecrit_le_lock
        self.racine = racine

    def exec_command_live(self, command, **kwargs):
        self.vues.append(command)
        # LE LOCK PEUT EXISTER MALGRÉ L'ÉCHEC. La commande est une chaîne
        # « pip install && poetry_update » : pip passe, poetry cède APRÈS
        # avoir écrit un lock partiel. Sans ce cas, l'absence du fichier
        # suffisait à tout arrêter et le code de retour ne prouvait rien.
        if "poetry_update" in command and self.ecrit_le_lock:
            with open(os.path.join(self.racine, "poetry.lock"), "w") as fh:
                fh.write("partiel\n" if self.code else "neuf\n")
        return self.code


class CasDuLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avant = os.getcwd()
        self.addCleanup(os.chdir, self.avant)
        os.chdir(self.tmp.name)
        os.mkdir("requirement")
        # La fin de ligne est celle du vrai fichier du dépôt.
        with open(".erplibre-version", "w") as fh:
            fh.write(VERSION + "\n")
        self.reference = f"./requirement/poetry.{VERSION}.lock"
        with open(self.reference, "w") as fh:
            fh.write("reference\n")
        with open("poetry.lock", "w") as fh:
            fh.write("vieux\n")

    def jouer(self, code=0, ecrit_le_lock=True):
        todo = TODO.__new__(TODO)
        todo.execute = Bancal(code, ecrit_le_lock, self.tmp.name)
        todo._is_yes = lambda _r: False
        import contextlib
        import io

        tampon = io.StringIO()
        with mock.patch("builtins.input", return_value="n"):
            with contextlib.redirect_stdout(tampon):
                todo.upgrade_poetry()
        return todo.execute, tampon.getvalue()

    def reference_lue(self):
        with open(self.reference) as fh:
            return fh.read()


class TestLaRegenerationQuiEchoue(CasDuLock):
    def test_the_tracked_lock_is_still_there(self):
        """Le défaut lui-même : le fichier partait avant la commande."""
        self.jouer(code=1)
        self.assertTrue(os.path.exists(self.reference))

    def test_it_still_carries_what_it_carried(self):
        """Présent mais vidé serait pire : git verrait une modification que
        personne n'a faite. Le banc écrit ici un lock PARTIEL malgré son
        échec, ce qui est la forme réelle — pip passe, poetry cède
        ensuite — et c'est ce cas-là que seule la lecture du code attrape.
        """
        self.jouer(code=1)
        self.assertEqual("reference\n", self.reference_lue())

    def test_it_is_said(self):
        """Se taire ferait chercher plus tard pourquoi git signale un
        fichier supprimé."""
        _banc, affiche = self.jouer(code=1)
        self.assertIn("❌", affiche)
        self.assertNotIn("✅", affiche)

    def test_a_command_that_wrote_no_lock_replaces_nothing(self):
        """Code zéro et pourtant aucun lock : la commande peut réussir sans
        avoir produit ce qu'on attend d'elle."""
        self.jouer(code=0, ecrit_le_lock=False)
        self.assertEqual("reference\n", self.reference_lue())


class TestLaRegenerationQuiAboutit(CasDuLock):
    def test_the_reference_is_replaced(self):
        """Contrôle positif : ne jamais remplacer passerait tous les
        précédents."""
        self.jouer()
        self.assertEqual("neuf\n", self.reference_lue())

    def test_the_working_lock_is_removed_first(self):
        """C'est son absence qui force une résolution neuve."""
        banc, _affiche = self.jouer()
        # La commande a vu un répertoire SANS l'ancien lock : elle l'a
        # réécrit elle-même, et son contenu n'est plus « vieux ».
        self.assertTrue(any("poetry_update" in c for c in banc.vues))
        self.assertNotIn("vieux", self.reference_lue())


class TestLaVersionDuCheckout(CasDuLock):
    def test_the_version_is_stripped(self):
        """La fin de ligne se retrouvait au MILIEU du chemin composé, qui
        ne désignait alors aucun fichier existant."""
        self.jouer()
        self.assertEqual("neuf\n", self.reference_lue())

    def test_without_a_version_nothing_is_replaced(self):
        """Le chemin serait « poetry..lock » : aucune version supportée."""
        os.remove(".erplibre-version")
        self.jouer()
        self.assertFalse(os.path.exists("./requirement/poetry..lock"))
        self.assertEqual("reference\n", self.reference_lue())


if __name__ == "__main__":
    unittest.main()
