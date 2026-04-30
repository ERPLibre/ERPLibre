#!/usr/bin/env python3
"""Unit tests for the pure helpers in game_tiler.py.

Avoids importing PIL or Stream Deck SDKs by surgically pulling the
helper functions through `importlib` after stubbing the heavy modules
that the file imports unconditionally at top.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_game_tiler():
    """Import game_tiler.py with PIL and StreamDeck stubbed.

    The chunk helpers we test are evaluated at module import time, so
    we cannot let the PIL / StreamDeck imports fail. The stubs below
    expose the bare minimum the import path touches; the helpers we
    actually call are pure-Python.
    """
    if "game_tiler" in sys.modules:
        return sys.modules["game_tiler"]

    here = Path(__file__).resolve().parent

    # Stub PIL with the names the file dereferences at import.
    pil = types.ModuleType("PIL")
    image = types.ModuleType("PIL.Image")
    image_draw = types.ModuleType("PIL.ImageDraw")
    image_font = types.ModuleType("PIL.ImageFont")
    image.new = lambda *a, **kw: None
    image_draw.Draw = lambda *a, **kw: None
    image_font.load_default = lambda *a, **kw: None
    pil.Image = image
    pil.ImageDraw = image_draw
    pil.ImageFont = image_font
    sys.modules.setdefault("PIL", pil)
    sys.modules.setdefault("PIL.Image", image)
    sys.modules.setdefault("PIL.ImageDraw", image_draw)
    sys.modules.setdefault("PIL.ImageFont", image_font)

    sdk = types.ModuleType("StreamDeck")
    devmgr = types.ModuleType("StreamDeck.DeviceManager")
    helpers = types.ModuleType("StreamDeck.ImageHelpers")
    pilhelper = types.ModuleType("StreamDeck.ImageHelpers.PILHelper")
    transport = types.ModuleType("StreamDeck.Transport")
    transport_t = types.ModuleType("StreamDeck.Transport.Transport")

    devmgr.DeviceManager = lambda *a, **kw: None
    pilhelper.to_native_key_format = lambda *a, **kw: None
    pilhelper.create_image = lambda *a, **kw: None

    class _TransportError(Exception):
        pass

    transport_t.TransportError = _TransportError
    sdk.DeviceManager = devmgr
    sdk.ImageHelpers = helpers
    helpers.PILHelper = pilhelper
    sdk.Transport = transport
    transport.Transport = transport_t

    sys.modules.setdefault("StreamDeck", sdk)
    sys.modules.setdefault("StreamDeck.DeviceManager", devmgr)
    sys.modules.setdefault("StreamDeck.ImageHelpers", helpers)
    sys.modules.setdefault("StreamDeck.ImageHelpers.PILHelper",
                           pilhelper)
    sys.modules.setdefault("StreamDeck.Transport", transport)
    sys.modules.setdefault("StreamDeck.Transport.Transport",
                           transport_t)

    # Stub the optional translator dependency next to game_tiler.py.
    sys.modules.setdefault("translator", types.ModuleType("translator"))

    spec = importlib.util.spec_from_file_location(
        "game_tiler", str(here / "game_tiler.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["game_tiler"] = module
    spec.loader.exec_module(module)
    return module


GT = _load_game_tiler()


class ChunkTextForCellsTest(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(GT._chunk_text_for_cells("", 5), [])
        self.assertEqual(GT._chunk_text_for_cells(None, 5), [])
        self.assertEqual(GT._chunk_text_for_cells("hello", 0), [])

    def test_short_text_single_chunk(self):
        self.assertEqual(GT._chunk_text_for_cells("hello", 5), ["hello"])

    def test_breaks_on_word_boundary(self):
        out = GT._chunk_text_for_cells(
            "the quick brown fox", 4, per_cell=10)
        self.assertEqual(out[0], "the quick")
        self.assertTrue(all(" " not in c[-1] for c in out if c))

    def test_truncates_to_num_cells(self):
        out = GT._chunk_text_for_cells(
            "one two three four five six", 2, per_cell=8)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], "one two")

    def test_falls_back_to_hard_cut_when_no_space(self):
        out = GT._chunk_text_for_cells(
            "abcdefghijklmnop", 3, per_cell=5)
        self.assertEqual(out, ["abcde", "fghij", "klmno"])


class WrapChunkTest(unittest.TestCase):
    def test_short_no_wrap(self):
        self.assertEqual(GT._wrap_chunk("abc", line_chars=6), "abc")
        self.assertEqual(GT._wrap_chunk("", line_chars=6), "")

    def test_word_break(self):
        self.assertEqual(
            GT._wrap_chunk("hello world", line_chars=6),
            "hello\nworld")

    def test_hard_break_when_no_space(self):
        self.assertEqual(
            GT._wrap_chunk("abcdefghij", line_chars=4),
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
