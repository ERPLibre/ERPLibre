#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Trois menus de TODO rendent leurs rendus de référence : l'entrée [4]
(Navigation telemetry), Configuration et Update.

test/todo_menu_golden.json fige, pour chacun, les octets du terminal en
français et en anglais, ce que rend [0], les clés de télémétrie, les
sondes du hub web, et les messages `menu` d'une session web ;
test/todo_menu_golden.py dit comment ils se capturent (configuration,
préférences, hub arrêté, HOME temporaire) et les réécrit. La session web
se compare par ses messages `menu`, le fil d'Ariane de chaque menu
traversé et les clés de télémétrie, le vrai TODO tournant à part sous la
capture, comme dans le worker.
"""

import json
import unittest

import todo_menu_golden as golden


class TestGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = golden.GOLDEN.read_text(encoding="utf-8")
        cls.reference = json.loads(text)

    def test_the_reference_covers_the_three_menus_in_both_languages(self):
        for lang in golden.LANGS:
            terminal = self.reference["terminal"][lang]
            self.assertEqual(sorted(terminal), sorted(golden.MENUS))
            session = self.reference["session"][lang]
            crumbs = [menu["crumbs"][-1] for menu in session["menus"]]
            self.assertEqual(sorted(crumbs), sorted(golden.CRUMBS))

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


if __name__ == "__main__":
    unittest.main()
