#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Des menus de TODO rendent leurs rendus de référence : l'entrée [4]
(Navigation telemetry), Configuration, la famille Execute : Execute,
Code, Config, Process, Test et Update, la famille Run : Run, Database et
son menu d'effacement, Analyse, Transform data et Doc, et la famille
Git : Git, Git local server et ses deux menus Actions, GPT code, Claude
configs, Plugins, Claude Code, RTK et Automation.

test/todo_menu_golden.json fige, pour chacun, les octets du terminal en
français et en anglais, ce que rend [0], les clés de télémétrie, les
sondes du hub web, et les messages `menu` d'une session web ;
test/todo_menu_golden.py dit comment ils se capturent (configuration,
préférences, hub arrêté, HOME temporaire) et les réécrit. La session web
se compare par ses messages `menu`, le fil d'Ariane de chaque menu
traversé et les clés de télémétrie, le vrai TODO tournant à part sous la
capture, comme dans le worker.

`TestCapture` tient les garde-fous de la capture sur un menu factice mis
à la place de [4] : une question au terminal lève au lieu de bloquer, et
une étape de WALK absente de son menu est nommée.
"""

import getpass
import io
import json
import sys
import unittest
from unittest.mock import patch

import click
import todo_menu_golden as golden


class TestGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = golden.GOLDEN.read_text(encoding="utf-8")
        cls.reference = json.loads(text)

    def test_the_reference_covers_each_menu_in_both_languages(self):
        # Une session passe par Execute et Code plus d'une fois : chaque
        # menu de CRUMBS y a au moins un message.
        for lang in golden.LANGS:
            terminal = self.reference["terminal"][lang]
            self.assertEqual(sorted(terminal), sorted(golden.MENUS))
            session = self.reference["session"][lang]
            crumbs = {menu["crumbs"][-1] for menu in session["menus"]}
            self.assertEqual(crumbs, set(golden.CRUMBS))

    def test_the_terminal_shows_the_same_bytes(self):
        for lang in golden.LANGS:
            for method in golden.MENUS:
                with self.subTest(lang=lang, menu=method):
                    self.assertEqual(
                        golden.terminal(method, lang),
                        self.reference["terminal"][lang][method],
                    )

    def test_a_session_sees_the_same_menus_and_keys(self):
        for lang in golden.LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(
                    golden.session(lang), self.reference["session"][lang]
                )


class TestCapture(unittest.TestCase):
    def captured(self, menu) -> dict:
        """Ce que `golden.terminal` rend quand `menu(todo)` tient la place
        de l'entrée [4]."""
        from script.todo.todo import TODO

        with patch.object(TODO, "prompt_telemetry", menu):
            return golden.terminal("prompt_telemetry", "en")

    def test_a_question_on_the_terminal_raises_instead_of_blocking(self):
        for name, menu in (
            ("input", lambda todo: input("Forged: ")),
            (
                "hidden_prompt",
                lambda todo: click.prompt("Forged", hide_input=True),
            ),
            ("getpass", lambda todo: getpass.getpass("Forged: ")),
        ):
            with (
                self.subTest(name),
                self.assertRaisesRegex(AssertionError, name),
            ):
                self.captured(menu)

    def test_the_standard_input_is_empty_during_the_capture(self):
        seen, stdin = [], sys.stdin
        self.captured(lambda todo: seen.append(sys.stdin))
        [during] = seen
        self.assertIsInstance(during, io.StringIO)
        self.assertEqual(during.read(), "")
        self.assertIs(sys.stdin, stdin)

    def test_a_step_absent_from_its_menu_is_named(self):
        # Le menu principal n'a aucune entrée de ce libellé : la session
        # s'arrête là, sans répondre à rien.
        walk = (["Forged absent step"], "0")
        with patch.object(golden, "WALK", walk):
            with self.assertRaisesRegex(EOFError, "Forged absent step"):
                golden.session("en")


if __name__ == "__main__":
    unittest.main()
