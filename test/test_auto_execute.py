#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Enchaîner la migration sans rester devant à taper Entrée.

Une migration pose des dizaines de questions dont la réponse est presque
toujours celle proposée. Le mode auto attend cinq secondes puis prend le
défaut — assez pour reprendre la main, assez peu pour ne pas immobiliser
quelqu'un des heures.

La question est posée AVANT le choix de version, donc avant la première
décision : activée, elle vaut pour toutes les suivantes, celle-là comprise.

Le test qui compte le plus est le dernier : une invite écrite plus tard en
`input()` nu ne saurait rien du mode auto, et bloquerait la migration sans
que rien ne le signale.
"""

import ast
import inspect
import io
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402


def upgrade(auto, delay=0.2):
    obj = TodoUpgrade.__new__(TodoUpgrade)
    obj.auto_execute = auto
    obj.AUTO_DELAY = delay
    return obj


class EnvCase(unittest.TestCase):
    """Rendre l'environnement comme on l'a trouvé.

    `ask` pose le mode auto dans l'environnement — c'est ainsi qu'il atteint
    les outils lancés à part. Le laisser posé le ferait fuir dans TOUTE la
    suite : une invite sans rapport prendrait son défaut au lieu d'attendre,
    et le test qui échouerait ne serait pas celui qui a fauté.
    """

    def setUp(self):
        from script.todo import auto_ask

        avant = {
            key: os.environ.get(key)
            for key in (auto_ask.ENV_ENABLED, auto_ask.ENV_DELAY)
        }

        def remettre():
            for key, value in avant.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.addCleanup(remettre)


class TestTheTimedRead(EnvCase):
    def setUp(self):
        super().setUp()
        self.original = sys.stdin
        self.addCleanup(setattr, sys, "stdin", self.original)

    def pipe_stdin(self, payload=b""):
        """Un vrai descripteur : `select` ne sait pas lire un faux objet."""
        read_fd, write_fd = os.pipe()
        if payload:
            os.write(write_fd, payload)
        os.close(write_fd)
        handle = os.fdopen(read_fd)
        self.addCleanup(handle.close)
        sys.stdin = handle

    def test_without_auto_it_just_asks(self):
        import builtins

        original = builtins.input
        builtins.input = lambda prompt="": "tapé"
        self.addCleanup(setattr, builtins, "input", original)
        self.assertEqual(upgrade(False).ask("q : ", default="6"), "tapé")

    def test_with_auto_an_answer_wins(self):
        self.pipe_stdin(b"2\n")
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            got = upgrade(True).ask("q : ", default="6")
        finally:
            sys.stdout = real
        self.assertEqual(got, "2")

    def test_a_closed_stdin_gives_the_default(self):
        # Exécution non interactive : le tuyau fermé est lisible TOUT DE
        # SUITE et rend une ligne vide. Sans traiter le vide comme le
        # défaut, le mode auto n'y servirait à rien.
        self.pipe_stdin()
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            got = upgrade(True).ask("q : ", default="6")
        finally:
            sys.stdout = real
        self.assertEqual(got, "6")

    def test_silence_gives_the_default_after_the_delay(self):
        # Le tuyau reste OUVERT : rien à lire, et select doit rendre la main
        # au bout du délai plutôt que d'attendre indéfiniment.
        import time

        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, write_fd)
        handle = os.fdopen(read_fd)
        self.addCleanup(handle.close)
        sys.stdin = handle
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        debut = time.time()
        try:
            got = upgrade(True, delay=0.3).ask("q : ", default="6")
        finally:
            sys.stdout = real
        self.assertEqual(got, "6")
        self.assertGreaterEqual(time.time() - debut, 0.25)

    def test_an_unselectable_stdin_falls_back_to_asking(self):
        # Ne pas deviner quand on ne peut pas mesurer : mieux vaut demander
        # que rendre un défaut que personne n'a voulu.
        import builtins

        class NotSelectable:
            def fileno(self):
                raise ValueError("pas de descripteur")

        sys.stdin = NotSelectable()
        original = builtins.input
        builtins.input = lambda prompt="": "demandé"
        self.addCleanup(setattr, builtins, "input", original)
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            got = upgrade(True).ask("q : ", default="6")
        finally:
            sys.stdout = real
        self.assertEqual(got, "demandé")


class TestTheQuestionThatEnablesIt(EnvCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def answer(self, typed):
        import builtins
        import contextlib

        obj = TodoUpgrade.__new__(TodoUpgrade)
        original = builtins.input
        builtins.input = lambda prompt="": typed
        self.addCleanup(setattr, builtins, "input", original)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            obj.prompt_auto_execute()
        return obj.auto_execute, out.getvalue()

    def test_yes_turns_it_on(self):
        on, text = self.answer("y")
        self.assertTrue(on)
        self.assertIn("Auto-run on", text)

    def test_the_default_is_off(self):
        # Elle prend des décisions à votre place : ce n'est pas le défaut.
        on, text = self.answer("")
        self.assertFalse(on)
        self.assertEqual(text, "")

    def test_anything_else_is_off(self):
        self.assertFalse(self.answer("peut-être")[0])

    def test_the_delay_is_five_seconds(self):
        self.assertEqual(TodoUpgrade.AUTO_DELAY, 5)

    def test_yes_also_arms_the_tools_launched_apart(self):
        # La moitié des invites d'une migration sont posées par d'autres
        # processus. Sans cette variable, ils attendraient une frappe qui
        # ne vient jamais — et l'automatisation s'arrêterait là, en
        # silence, puisque la question a bien été posée.
        from script.todo import auto_ask

        self.answer("y")
        self.assertEqual(os.environ.get(auto_ask.ENV_ENABLED), "1")

    def test_no_leaves_nothing_behind(self):
        from script.todo import auto_ask

        os.environ[auto_ask.ENV_ENABLED] = "1"
        self.answer("")
        self.assertNotIn(auto_ask.ENV_ENABLED, os.environ)


class TestWhereItIsAsked(unittest.TestCase):
    def source(self):
        return inspect.getsource(TodoUpgrade.execute_odoo_upgrade)

    def test_it_comes_before_the_version_choice(self):
        # « avant de choisir la version d'Odoo » : activée, elle vaut aussi
        # pour ce choix-là, qui a désormais un défaut.
        source = self.source()
        self.assertLess(
            source.index("prompt_auto_execute"),
            source.index("Which version do you want to upgrade to?"),
        )

    def test_the_version_choice_goes_through_it(self):
        # click.prompt ne sait pas rendre la main après un délai : le laisser
        # là aurait fait un mode auto qui s'arrête à la première question.
        source = self.source()
        self.assertNotIn("click.prompt(", source)


class TestNoPromptEscapesIt(unittest.TestCase):
    """Une invite en `input()` nu ne saurait rien du mode auto.

    Elle bloquerait la migration sans rien signaler — et c'est précisément
    le genre de chose qu'on n'ajoute pas exprès, mais par habitude.
    """

    def test_every_prompt_of_the_migration_uses_ask(self):
        path = os.path.join(REPO, "script", "todo", "todo_upgrade.py")
        with open(path) as handle:
            tree = ast.parse(handle.read())
        target = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "execute_odoo_upgrade"
        ]
        self.assertEqual(len(target), 1, "fonction introuvable")
        bare = [
            node.lineno
            for node in ast.walk(target[0])
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "input"
        ]
        self.assertEqual(bare, [], "invites hors du mode auto")

    def test_the_gate_uses_it_too(self):
        # `ask_gate` porte le retour en arrière : la laisser en input() nu
        # aurait fait un mode auto qui s'arrête à chaque « b = revenir ».
        source = inspect.getsource(TodoUpgrade.ask_gate)
        self.assertIn("self.ask(", source)
        self.assertNotIn("= input(", source)


if __name__ == "__main__":
    unittest.main()
