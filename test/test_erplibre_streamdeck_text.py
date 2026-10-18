#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Pure helpers of the deck program: text cutting, Claude tile colour and
label, the TODO menu parser. They run against the
single file until the module that owns each helper exists."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

GT = S.load_monolith()
S.install()
from erplibre_streamdeck.ui import text  # noqa: E402


class ChunkTextForCellsTest(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(text.chunk_text_for_cells("", 5), [])
        self.assertEqual(text.chunk_text_for_cells(None, 5), [])
        self.assertEqual(text.chunk_text_for_cells("hello", 0), [])

    def test_short_text_single_chunk(self):
        self.assertEqual(text.chunk_text_for_cells("hello", 5), ["hello"])

    def test_breaks_on_word_boundary(self):
        out = text.chunk_text_for_cells(
            "the quick brown fox", 4, per_cell=10)
        self.assertEqual(out[0], "the quick")
        self.assertTrue(all(" " not in c[-1] for c in out if c))

    def test_truncates_to_num_cells(self):
        out = text.chunk_text_for_cells(
            "one two three four five six", 2, per_cell=8)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], "one two")

    def test_falls_back_to_hard_cut_when_no_space(self):
        out = text.chunk_text_for_cells(
            "abcdefghijklmnop", 3, per_cell=5)
        self.assertEqual(out, ["abcde", "fghij", "klmno"])


class WrapChunkTest(unittest.TestCase):
    def test_short_no_wrap(self):
        self.assertEqual(text.wrap_chunk("abc", line_chars=6), "abc")
        self.assertEqual(text.wrap_chunk("", line_chars=6), "")

    def test_word_break(self):
        self.assertEqual(
            text.wrap_chunk("hello world", line_chars=6),
            "hello\nworld")

    def test_hard_break_when_no_space(self):
        self.assertEqual(
            text.wrap_chunk("abcdefghij", line_chars=4),
            "abcd\nefghij")


class ClaudeColorTest(unittest.TestCase):
    def test_active_default_green(self):
        self.assertEqual(
            GT._claude_color({"status": "active"}),
            GT.COLOR_CLAUDE_ACTIVE)

    def test_await_stop_yellow(self):
        self.assertEqual(
            GT._claude_color({"status": "awaiting_stop"}),
            GT.COLOR_CLAUDE_AWAIT_STOP)

    def test_await_notification_red(self):
        self.assertEqual(
            GT._claude_color({"status": "awaiting_notification"}),
            GT.COLOR_CLAUDE_AWAIT_NOTIFY)

    def test_unknown_falls_back_to_active(self):
        self.assertEqual(
            GT._claude_color({"status": "anything-else"}),
            GT.COLOR_CLAUDE_ACTIVE)


class ClaudeLabelTest(unittest.TestCase):
    def test_short_passthrough(self):
        self.assertEqual(
            GT._claude_label({"description": "hi"}, max_chars=18),
            "hi")

    def test_word_break_truncation(self):
        out = GT._claude_label(
            {"description": "hello world this is long"}, max_chars=18)
        self.assertTrue(len(out) <= 18)
        self.assertFalse(out.endswith(" "))

    def test_no_description(self):
        self.assertEqual(GT._claude_label({}, max_chars=18), "")


class WrapButtonLabelTest(unittest.TestCase):
    def test_short_one_line(self):
        self.assertEqual(text.wrap_button_label("Hi"), "Hi")

    def test_breaks_at_space(self):
        self.assertEqual(
            text.wrap_button_label("Add path", max_chars=8, max_lines=2),
            "Add path")
        self.assertEqual(
            text.wrap_button_label("Add new database",
                max_chars=8, max_lines=2),
            "Add new\ndatabase")

    def test_hard_break_long_word(self):
        out = text.wrap_button_label("supercalifragilistic",
            max_chars=8, max_lines=2)
        # Two lines of <= 8 chars, last truncated with ellipsis.
        self.assertEqual(out.count("\n"), 1)
        for line in out.split("\n"):
            self.assertLessEqual(len(line), 8)
        self.assertTrue(out.endswith("…"))

    def test_empty_input(self):
        self.assertEqual(text.wrap_button_label(""), "")
        self.assertEqual(text.wrap_button_label(None), "")


class TodoMenuParseTest(unittest.TestCase):
    def test_simple_block(self):
        text = (
            "Welcome to TODO\n"
            "[1] Database\n"
            "[2] Add-ons\n"
            "[3] Quit\n"
            "Select: ")
        items, prompt = GT._parse_todo_menu(text)
        self.assertEqual(items,
            [("1", "Database"), ("2", "Add-ons"), ("3", "Quit")])
        self.assertEqual(prompt, "Select:")

    def test_strips_ansi(self):
        text = (
            "\x1b[31m[1] Red\x1b[0m\n"
            "\x1b[32m[2] Green\x1b[0m\n"
            "Choose: ")
        items, _ = GT._parse_todo_menu(text)
        self.assertEqual(items, [("1", "Red"), ("2", "Green")])

    def test_ignores_logo_above_menu(self):
        text = (
            "###  ASCII LOGO ###\n"
            "Random preamble\n"
            "[1] First\n"
            "[2] Second\n")
        items, _ = GT._parse_todo_menu(text)
        self.assertEqual(items, [("1", "First"), ("2", "Second")])

    def test_empty_text(self):
        self.assertEqual(GT._parse_todo_menu(""), ([], ""))
        self.assertEqual(GT._parse_todo_menu(None), ([], ""))


if __name__ == "__main__":
    unittest.main()
