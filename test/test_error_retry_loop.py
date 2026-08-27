#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Réparer puis rejouer — et savoir s'arrêter.

Le motif d'échec le plus fréquent d'une migration est une copie COW en
retard sur sa vue module : « Element <xpath …> cannot be located in parent
view ». La réparation est connue, et c'est presque toujours ce qu'on allait
faire. D'où « 3 » par défaut, et le rejeu automatique derrière.

Mais un défaut qui agit doit savoir s'arrêter, et à deux titres :

- réinitialiser quand il n'y a RIEN à réinitialiser puis reproposer la même
  chose est une boucle sans fin. Vécu : « Aucune copie COW n'a dérivé »,
  encore et encore ;
- une réparation qui ne suffit pas relancerait la commande indéfiniment.
  Trois tentatives, puis on rend la main : une migration lancée en
  auto-exécution tournerait sinon toute la nuit sur le même échec.

Ces tests comptent les tours. C'est la seule façon de prouver qu'une
boucle se termine.
"""

import io
import os
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


class Harness(unittest.TestCase):
    """Un pilote dont la commande échoue toujours, et qu'on observe."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def upgrade(self, lst_answer=None, resets=None, echec=True):
        """`resets` : ce que la réinitialisation rend, tour après tour."""
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {}
        obj.lst_command_executed = []
        obj.write_config = lambda: None
        obj.database_from_command = lambda cmd: "db"
        self.lst_run = []
        self.lst_reset = []

        class FauxExecute:
            def exec_command_live(_self, cmd, **kw):
                # Une interrogation de service — la détection de thème —
                # n'est pas un rejeu de la commande : l'inscrire dans
                # `lst_run` doublerait tous les comptes de cette suite.
                if "ir_module_module" in cmd:
                    if kw.get("return_status_and_output_and_command"):
                        return 0, cmd, []
                    return 0, cmd
                self.lst_run.append(cmd)
                # Toujours en échec : c'est le cas qu'on veut borner.
                statut = 1 if echec else 0
                # La FORME du retour suit les drapeaux, comme le vrai :
                # un faux qui rend toujours deux valeurs casse dès qu'un
                # appelant demande la sortie.
                if kw.get("return_status_and_output_and_command"):
                    return statut, cmd, []
                if kw.get("return_status_and_output"):
                    return statut, []
                return statut, cmd

        obj.execute = FauxExecute()
        suite = iter(resets if resets is not None else [])

        def faux_reset(database):
            self.lst_reset.append(database)
            try:
                return next(suite)
            except StopIteration:
                return False

        obj.prompt_reset_stale_cow_views = faux_reset
        obj.check_stale_cow_views = lambda db: None
        obj.run_captured = lambda cmd: 0
        reponses = iter(lst_answer or [])

        def faux_ask(prompt, default=""):
            try:
                return next(reponses)
            except StopIteration:
                # Personne ne répond : c'est le mode auto, et c'est
                # précisément là qu'une boucle sans fin se déclenche.
                return default

        obj.ask = faux_ask
        return obj

    def executer(self, obj):
        out = io.StringIO()
        with redirect_stdout(out):
            obj.todo_upgrade_execute("./script/addons/update_addons_all.sh db")
        return out.getvalue()


class TestRepairingThenReplaying(Harness):
    def test_the_default_repairs(self):
        # Sans réponse, on répare : c'est le geste qu'on allait faire.
        obj = self.upgrade(resets=[True, False])
        self.executer(obj)
        self.assertTrue(self.lst_reset)

    def test_a_successful_repair_replays_the_command(self):
        obj = self.upgrade(resets=[True, False])
        self.executer(obj)
        self.assertGreaterEqual(len(self.lst_run), 2)

    def test_a_repair_that_changed_nothing_does_NOT_replay(self):
        # Rejouer sans avoir rien changé donnerait le même échec.
        obj = self.upgrade(resets=[False])
        self.executer(obj)
        self.assertEqual(len(self.lst_run), 1)


class TestItAlwaysStops(Harness):
    """La propriété qui compte le plus : la boucle se termine."""

    def test_nothing_to_reset_does_not_loop_forever(self):
        # Vécu : « Aucune copie COW n'a dérivé », reproposé sans fin parce
        # que le défaut restait « 3 ».
        obj = self.upgrade(resets=[False, False, False, False, False])
        self.executer(obj)
        self.assertLessEqual(len(self.lst_reset), 2)

    def test_a_repair_that_never_helps_stops_after_three(self):
        obj = self.upgrade(resets=[True] * 20)
        self.executer(obj)
        self.assertEqual(len(self.lst_run), TodoUpgrade.MAX_ERROR_RETRY)

    def test_giving_up_says_so_out_loud(self):
        # S'arrêter en silence ferait croire que c'est réparé.
        obj = self.upgrade(resets=[True] * 20)
        text = self.executer(obj)
        self.assertIn("needs a developer", text)

    def test_the_loop_is_bounded_STRUCTURALLY(self):
        """Même si la bascule du défaut disparaissait un jour.

        Deux protections pour la même panne, et c'est délibéré : celle-ci
        ne dépend d'aucune logique métier. Une boucle infinie dans une
        migration lancée sans surveillance coûte une nuit, et la seule
        preuve qu'une boucle se termine est de compter ses tours.
        """
        obj = self.upgrade(lst_answer=["2"] * 50, resets=[])
        self.executer(obj)
        self.assertLessEqual(len(self.lst_run), 2)

    def test_the_turn_bound_says_so(self):
        obj = self.upgrade(lst_answer=["2"] * 50, resets=[])
        text = self.executer(obj)
        self.assertIn("Too many turns", text)

    def test_the_bound_is_three(self):
        self.assertEqual(TodoUpgrade.MAX_ERROR_RETRY, 3)

    def test_a_command_that_succeeds_never_asks(self):
        obj = self.upgrade(echec=False)
        self.executer(obj)
        self.assertEqual(self.lst_reset, [])
        self.assertEqual(len(self.lst_run), 1)


class TestTheHumanKeepsTheWheel(Harness):
    def test_typing_one_replays_without_consuming_the_budget(self):
        # Le plafond borne le rejeu AUTOMATIQUE. Quelqu'un qui tape « 1 »
        # sait ce qu'il fait, et se voir refuser un quatrième essai serait
        # une surprise désagréable.
        obj = self.upgrade(lst_answer=["1", "1", "1", "1", ""])
        self.executer(obj)
        self.assertEqual(len(self.lst_run), 5)

    def test_typing_n_continues_without_repairing(self):
        obj = self.upgrade(lst_answer=[""] * 0 + ["x"])
        self.executer(obj)
        self.assertEqual(self.lst_reset, [])
        self.assertEqual(len(self.lst_run), 1)

    def test_the_prompt_says_what_enter_does(self):
        import inspect

        # Le menu d'erreur vit dans `_prompt_on_error`, extrait de
        # `todo_upgrade_execute` quand celui-ci a passé le seuil de
        # complexité. Lire les deux : c'est le CHEMIN d'erreur qu'on
        # éprouve, pas une méthode en particulier.
        source = inspect.getsource(
            TodoUpgrade.todo_upgrade_execute
        ) + inspect.getsource(TodoUpgrade._prompt_on_error)
        self.assertIn('defaut = "3" if database_name else ""', source)
        self.assertIn("default=defaut", source)

    def test_without_a_database_the_default_is_to_continue(self):
        # Les options 2 à 4 ne s'affichent pas : proposer « 3 » viserait
        # une commande qui n'existe pas.
        obj = self.upgrade()
        obj.database_from_command = lambda cmd: None
        self.executer(obj)
        self.assertEqual(self.lst_reset, [])
        self.assertEqual(len(self.lst_run), 1)


class TestTheResetReportsWhatItDid(unittest.TestCase):
    """Sans verdict, on ne peut pas décider de rejouer."""

    def test_nothing_drifted_is_False(self):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.stale_cow_keys = lambda db: []
        with redirect_stdout(io.StringIO()):
            self.assertFalse(obj.prompt_reset_stale_cow_views("db"))

    def test_saying_no_is_False(self):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.stale_cow_keys = lambda db: ["web.layout"]
        obj.ask_gate = lambda prompt, default="": "n"
        with redirect_stdout(io.StringIO()):
            self.assertFalse(obj.prompt_reset_stale_cow_views("db"))

    def test_a_reset_that_ran_is_True(self):
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {}
        obj.write_config = lambda: None
        obj.stale_cow_keys = lambda db: ["web.layout"]
        obj.ask_gate = lambda prompt, default="": default
        obj.run_captured = lambda cmd: 0
        with redirect_stdout(io.StringIO()):
            self.assertTrue(obj.prompt_reset_stale_cow_views("db"))

    def test_a_reset_that_FAILED_is_False(self):
        # Rejouer derrière une réinitialisation qui a échoué, c'est brûler
        # une tentative sur un état inchangé.
        obj = TodoUpgrade.__new__(TodoUpgrade)
        obj.dct_progression = {}
        obj.write_config = lambda: None
        obj.stale_cow_keys = lambda db: ["web.layout"]
        obj.ask_gate = lambda prompt, default="": default
        obj.run_captured = lambda cmd: 2
        with redirect_stdout(io.StringIO()):
            self.assertFalse(obj.prompt_reset_stale_cow_views("db"))


if __name__ == "__main__":
    unittest.main()
