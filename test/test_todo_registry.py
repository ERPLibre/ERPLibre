#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le registre des menus et son navigateur.

Le navigateur tourne sur un double de TODO (`FakeTodo`), dont chaque
action, état, suffixe ou intro note son appel ; les réponses viennent de
`click.prompt` simulé, ou d'un ScriptedPort sous la capture de la session
web.
"""

import io
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import click

from script.todo import todo_i18n
from script.todo.todo_i18n import t
from script.todo.ui import legacy, port
from script.todo.ui.navigator import navigate
from script.todo.ui.registry import Entry, FromConfig, Menu, Section


class FakeTodo:
    """Double de TODO : toute méthode qu'un menu nomme note son appel dans
    `calls` et rend « <nom> » ; `fill_help_info` numérote les entrées comme
    celui de TODO et note ce qu'il reçoit dans `drawn` ;
    `config_file.get_config` rend une copie de `config[clé]`, None pour
    une clé absente, et compte ses lectures dans `reads`."""

    def __init__(self, config=None):
        self.calls, self.drawn, self.reads = [], [], 0
        self.config = config or {}
        self.config_file = types.SimpleNamespace(get_config=self.get_config)

    def get_config(self, key):
        self.reads += 1
        if key not in self.config:
            return None
        return [dict(element) for element in self.config[key]]

    def fill_help_info(self, choices, state=None):
        self.drawn.append((choices, state))
        lines, number = [state] if state else [], 0
        for choice in choices:
            if choice.get("section"):
                lines.append(f"── {choice['section']} ──")
                continue
            number += 1
            key = choice.get("prompt_description_key")
            label = t(key) if key else choice["prompt_description"]
            lines.append(f"[{number}] {label}")
        return "\n".join([*lines, "[0] Back", ""])

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(**kwargs):
            self.calls.append((name, kwargs))
            return f"<{name}>"

        return method


def _english(test):
    saved = todo_i18n._current_lang
    test.addCleanup(setattr, todo_i18n, "_current_lang", saved)
    todo_i18n.use_lang("en")


class TestRegistry(unittest.TestCase):
    def test_a_menu_is_drawn_each_turn_or_once(self):
        self.assertEqual(Menu("forged_menu", "Forged", []).render, "each")
        Menu("forged_menu", "Forged", [], render="once")
        with self.assertRaises(ValueError):
            Menu("forged_menu", "Forged", [], render="twice")

    def test_a_declaration_is_frozen(self):
        entry = Entry("Forged", "forged_action")
        with self.assertRaises(AttributeError):
            entry.action = "other_action"


class TestNavigator(unittest.TestCase):
    def setUp(self):
        _english(self)
        self.out = self.enterContext(redirect_stdout(io.StringIO()))

    def navigate(self, menu, answers, todo=None):
        """Rend (ce que rend `navigate`, le double, les textes posés)."""
        todo = todo or FakeTodo()
        with patch("click.prompt", side_effect=answers) as prompt:
            back = navigate(todo, menu)
        return back, todo, [call.args[0] for call in prompt.call_args_list]

    def test_a_number_runs_the_entry_at_its_place(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                Section("Forged section"),
                Entry("First", "first_action"),
                Section("Other section"),
                Entry("Second", "second_action", kwargs={"key": "b"}),
            ],
        )
        back, todo, texts = self.navigate(menu, ["2", "1", "0"])
        self.assertIs(back, False)
        self.assertEqual(
            todo.calls, [("second_action", {"key": "b"}), ("first_action", {})]
        )
        self.assertEqual(
            texts[0],
            "── Forged section ──\n[1] First\n── Other section ──\n"
            "[2] Second\n[0] Back\n",
        )

    def test_zero_gives_back_what_the_menu_declares(self):
        for back in (None, False):
            menu = Menu("forged_menu", "Forged", [], back=back)
            self.assertIs(self.navigate(menu, ["0"])[0], back)

    def test_any_other_answer_is_not_found_and_asks_again(self):
        menu = Menu("forged_menu", "Forged", [Entry("First", "first")])
        answers = ["2", "01", " 1", "-1", "x", "0"]
        _, todo, texts = self.navigate(menu, answers)
        self.assertEqual(todo.calls, [])
        self.assertEqual(len(texts), 6)
        self.assertEqual(self.out.getvalue().count("Command not found !"), 5)

    def test_each_turn_redraws_and_rereads_the_configuration(self):
        todo = FakeTodo({"forged_list": [{"prompt_description": "One"}]})

        def grow(**kwargs):
            todo.calls.append(("grow", kwargs))
            todo.config["forged_list"].append({"prompt_description": "Two"})

        todo.grow = grow
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                FromConfig("forged_list", "run_element", "element"),
                Entry("Grow", "grow"),
            ],
            state="forged_state",
        )
        _, _, texts = self.navigate(menu, ["2", "3", "0"], todo)
        self.assertEqual(
            texts,
            [
                "<forged_state>\n[1] One\n[2] Grow\n[0] Back\n",
                "<forged_state>\n[1] One\n[2] Two\n[3] Grow\n[0] Back\n",
                "<forged_state>\n[1] One\n[2] Two\n[3] Two\n[4] Grow\n"
                "[0] Back\n",
            ],
        )
        self.assertEqual(todo.reads, 3)
        self.assertEqual(
            [name for name, _ in todo.calls].count("forged_state"), 3
        )

    def test_a_configured_element_is_given_to_its_action(self):
        element = {"prompt_description_key": "Back", "makefile_cmd": "x"}
        todo = FakeTodo({"forged_list": [element]})
        menu = Menu(
            "forged_menu",
            "Forged",
            [FromConfig("forged_list", "run_element", "instance")],
        )
        _, _, texts = self.navigate(menu, ["1", "0"], todo)
        self.assertEqual(todo.calls, [("run_element", {"instance": element})])
        self.assertEqual(texts[0], "[1] 🔙 Back\n[0] Back\n")

    def test_once_draws_and_reads_once_and_the_intro_shows_once(self):
        todo = FakeTodo({"forged_list": [{"prompt_description": "One"}]})
        menu = Menu(
            "forged_menu",
            "Forged",
            [FromConfig("forged_list", "run_element", "element")],
            intro="forged_intro",
            render="once",
        )
        _, _, texts = self.navigate(menu, ["9", "1", "0"], todo)
        self.assertEqual(len(set(texts)), 1)
        self.assertEqual((len(texts), len(todo.drawn), todo.reads), (3, 1, 1))
        self.assertEqual(todo.calls[0], ("forged_intro", {}))
        self.assertEqual(
            [name for name, _ in todo.calls], ["forged_intro", "run_element"]
        )

    def test_a_suffix_is_asked_with_the_entry_kwargs(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [Entry("Pick", "pick", kwargs={"key": "k"}, suffix="pick_label")],
            intro="forged_intro",
        )
        _, todo, texts = self.navigate(menu, ["1", "0"])
        self.assertEqual(texts[0], "[1] Pick  (<pick_label>)\n[0] Back\n")
        self.assertEqual(
            todo.calls,
            [
                ("forged_intro", {}),
                ("pick_label", {"key": "k"}),
                ("pick", {"key": "k"}),
                ("pick_label", {"key": "k"}),
            ],
        )

    def test_a_list_absent_from_the_configuration_adds_no_entry(self):
        menu = Menu(
            "forged_menu",
            "Forged",
            [
                FromConfig("absent_list", "run_element", "element"),
                Entry("Last", "last"),
            ],
        )
        _, todo, texts = self.navigate(menu, ["1", "0"])
        self.assertEqual(texts[0], "[1] Last\n[0] Back\n")
        self.assertEqual(todo.calls, [("last", {})])

    def test_a_language_change_shows_at_the_next_turn(self):
        todo = FakeTodo()
        todo.speak_french = lambda: todo_i18n.use_lang("fr")
        menu = Menu("forged_menu", "Forged", [Entry("Back", "speak_french")])
        _, _, texts = self.navigate(menu, ["1", "0"], todo)
        self.assertEqual(
            texts, ["[1] 🔙 Back\n[0] Back\n", "[1] 🔙 Retour\n[0] Back\n"]
        )

    def test_an_abort_or_an_error_leaves_the_menu_as_before(self):
        # Ctrl+C ou Ctrl+D à la question (Abort de click), une action qui
        # lève : le navigateur ne rattrape rien, comme un menu écrit à la
        # main.
        menu = Menu("forged_menu", "Forged", [Entry("First", "first")])
        with self.assertRaises(click.exceptions.Abort):
            self.navigate(menu, [click.exceptions.Abort()])
        todo = FakeTodo()
        todo.first = lambda: 1 / 0
        with self.assertRaises(ZeroDivisionError):
            self.navigate(menu, ["1"], todo)

    def test_the_menu_goes_through_the_port_of_a_session(self):
        class Wrapped(FakeTodo):
            pass

        legacy.wrap_menus(Wrapped)
        scripted = port.ScriptedPort(["", "1", "0"])
        self.addCleanup(legacy.install(scripted))
        menu = Menu(
            "forged_menu",
            "Forged",
            [Section("Forged section"), Entry("First", "first_action")],
            back=None,
        )
        todo = Wrapped()
        self.assertIsNone(navigate(todo, menu))
        self.assertEqual(todo.calls, [("first_action", {})])
        menus = [e for e in scripted.events if e["t"] == "menu"]
        self.assertEqual(len(menus), 3)
        self.assertEqual(
            [(i["key"], i["label"], i["section"]) for i in menus[0]["items"]],
            [("1", "First", "Forged section"), ("0", "Back", None)],
        )
        self.assertEqual({m["source"] for m in menus}, {"fill_help_info"})


if __name__ == "__main__":
    unittest.main()
