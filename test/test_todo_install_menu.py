#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Installation de TODO : l'ordre des questions et ce qu'il lance.

Le choix se pose AVANT l'étape système. « First system installation? »
installe la pile de l'OS pour Odoo (update_env_version.py --install) ; posée
en premier, elle l'installait aussi pour qui ne voulait qu'une autre
technologie. Elle vient donc après le choix, pour les choix qui en ont
besoin — et pour une version d'Odoo, après les menus de l'environnement et
du type d'installation, qui offrent « 0: Back » : un retour ne doit rien
laisser d'installé.

Rien n'est installé ici : input() répond d'après une liste écrite d'avance,
subprocess.run et exec_command_live sont remplacés par des enregistreurs.
"""

import builtins
import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import todo as todo_module  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

QUESTION_SYSTEME = "First system installation?"


class ExecuteFactice:
    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        return 0


class Banc(unittest.TestCase):
    def jouer(self, reponses):
        """Lance prompt_install ; rend (questions posées, commandes lancées).

        Une question de plus que de réponses fait échouer le test en le
        disant, au lieu d'un StopIteration anonyme.
        """
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        questions = []
        suite = iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None

        lances = []

        def run(cmd, *args, **kwargs):
            lances.append(cmd)
            # « which pycharm » échoue : pas de question PyCharm ici.
            code = 1 if isinstance(cmd, list) and cmd[:1] == ["which"] else 0
            return subprocess.CompletedProcess(cmd, code, "", "")

        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_install()
        commandes = todo.execute.commandes + [
            c for c in lances if isinstance(c, str)
        ]
        return questions, commandes


class TestOrdreDesQuestions(Banc):
    def test_the_choice_comes_before_the_system_question(self):
        questions, commandes = self.jouer(["0"])
        self.assertEqual(len(questions), 1)
        self.assertNotIn(QUESTION_SYSTEME, questions[0])
        self.assertEqual(commandes, [])

    def test_an_odoo_version_asks_the_system_question_last(self):
        # La version, le développement, l'installation standard, puis la
        # question système.
        questions, commandes = self.jouer(["1", "1", "1", "y"])
        self.assertEqual(len(questions), 4)
        for question in questions[:3]:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertIn(
            "./script/version/update_env_version.py --install", commandes
        )
        self.assertTrue(
            any("--install_dev" in c for c in commandes), commandes
        )

    def test_back_from_the_environment_menu_installs_nothing(self):
        """La version, puis « 0: Back » au choix de l'environnement."""
        questions, commandes = self.jouer(["1", "0"])
        self.assertEqual(len(questions), 2)
        for question in questions:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertEqual(commandes, [])

    def test_back_from_the_install_type_menu_installs_nothing(self):
        """La version, le développement, puis « 0: Back » au type."""
        questions, commandes = self.jouer(["1", "1", "0"])
        self.assertEqual(len(questions), 3)
        for question in questions:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertEqual(commandes, [])

    def test_erplibre_only_keeps_the_system_question(self):
        questions, commandes = self.jouer(["q", "n"])
        self.assertIn(QUESTION_SYSTEME, questions[1])
        self.assertEqual(commandes, ["./script/install/install_erplibre.sh"])


class TestPycharmFerme(unittest.TestCase):
    """PyCharm s'ouvre sans bloquer : l'installation attend qu'il soit
    refermé, faute de quoi son analyse du projet, reprise à chaque fichier
    ajouté, ralentit l'installation."""

    def _attendre(self, reponses, pgrep):
        """Lance _wait_pycharm_closed ; rend (questions, appels pgrep, sortie).

        `pgrep` donne le code de chaque appel à pgrep, dans l'ordre : 0, un
        PyCharm tourne encore ; 1, plus aucun."""
        todo = TODO.__new__(TODO)
        questions, appels = [], []
        suite, codes = iter(reponses), iter(pgrep)

        def repondre(prompt=""):
            questions.append(prompt)
            return next(suite)

        def run(cmd, *args, **kwargs):
            appels.append(cmd)
            return subprocess.CompletedProcess(cmd, next(codes), "", "")

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            contextlib.redirect_stdout(sortie),
        ):
            todo._wait_pycharm_closed()
        return questions, appels, sortie.getvalue()

    def test_continues_once_pycharm_is_closed(self):
        questions, appels, _ = self._attendre([""], [1])
        self.assertEqual(len(questions), 1)
        self.assertEqual(appels, [["pgrep", "-f", "-i", "pycharm"]])

    def test_asks_again_while_pycharm_runs(self):
        questions, appels, sortie = self._attendre(["", ""], [0, 1])
        self.assertEqual(len(questions), 2)
        self.assertEqual(len(appels), 2)
        self.assertIn("still running", sortie)

    def test_c_continues_without_checking(self):
        questions, appels, _ = self._attendre(["c"], [])
        self.assertEqual(len(questions), 1)
        self.assertEqual(appels, [])

    def test_the_install_waits_for_pycharm_closed(self):
        """Le parcours entier : PyCharm ouvert, puis l'attente, puis
        seulement la commande d'installation."""
        todo = TODO.__new__(TODO)
        evenements = []

        class Execute:
            def exec_command_live(self, cmd, **kwargs):
                evenements.append(("lance", cmd))
                return 0

        todo.execute = Execute()
        # Version, environnement, type, système non, PyCharm oui, Entrée.
        suite = iter(["1", "1", "1", "n", "y", ""])

        def repondre(prompt=""):
            evenements.append(("question", prompt))
            return next(suite)

        def run(cmd, *args, **kwargs):
            if isinstance(cmd, str):
                # La commande d'installation passe par subprocess.run.
                evenements.append(("lance", cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd[:1] == ["which"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")  # pgrep

        exists = os.path.exists
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            mock.patch.object(
                todo_module.os.path,
                "exists",
                lambda p: False if p == ".idea" else exists(p),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_install()
        rangs = {
            "pycharm": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "lance" and "pycharm" in v
            ),
            "attente": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "question" and "close it" in v
            ),
            "installation": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "lance" and "--install_dev" in v
            ),
        }
        self.assertLess(rangs["pycharm"], rangs["attente"])
        self.assertLess(rangs["attente"], rangs["installation"])


if __name__ == "__main__":
    unittest.main()
