#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck program's start and stop: build(), read_plugins_off(),
and main()'s shutdown."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

app = S.load_package()
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck import paths  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    LoadedPlugin,
    Plugin,
    PLUGIN_API,
)
from erplibre_streamdeck.ui import render  # noqa: E402

PLUGIN_SRC = (
    "from erplibre_streamdeck.plugin import *\n"
    "from erplibre_streamdeck.ui import colors\n"
    "PLUGIN = Plugin(api=PLUGIN_API, {kw})\n"
)
# Every repository plugin turned off: build() then loads only the user
# plugins a test writes, and no repository plugin reaches the system.
ALL_REPO_OFF = tuple(S.REPO_PLUGINS)


class AppCase(unittest.TestCase):
    def setUp(self):
        S.wipe()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.user = Path(tmp.name)
        self.journal = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contextlib.redirect_stderr(self.journal))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(
            mock.patch.object(K, "dbus_mod", mock.Mock(available=bool))
        )
        style = render.STYLE
        saved = (style.font_scale, style.show_labels)
        self.addCleanup(
            lambda: (setattr(style, "font_scale", saved[0]),
                     setattr(style, "show_labels", saved[1]))
        )
        self.deck = S.FakeDeck(5, 3)

    def put(self, pid, kw):
        (self.user / f"{pid}.py").write_text(
            PLUGIN_SRC.format(kw=kw), encoding="utf-8"
        )

    def build(self, off=()):
        return app.build(
            self.deck, plugins_off=ALL_REPO_OFF + tuple(off),
            user_dir=self.user,
        )


class BuildTest(AppCase):
    def test_returns_a_kernel_of_the_loaded_plugins(self):
        self.put("good", "")
        self.put("skipped", "")
        k = self.build(off=["skipped"])
        self.assertIsInstance(k, K.Kernel)
        self.assertEqual(["good"], [lp.id for lp in k.plugins])
        self.assertIn("skipped: off", self.journal.getvalue())

    def test_refused_plugins_are_journaled(self):
        (self.user / "broken.py").write_text("def (:\n", encoding="utf-8")
        self.put("listed", "home_button=[HomeButton(1, print, print)]")
        self.put("fails", "setup=lambda ctx: 1 / 0")
        k = self.build()
        self.assertEqual([], k.plugins)
        journal = self.journal.getvalue()
        self.assertIn("broken: refused: import: SyntaxError", journal)
        self.assertIn("listed: refused: home_button", journal)
        self.assertIn("plugin fails: refused: setup raised", journal)

    def test_style_restored_from_settings(self):
        render.STYLE.font_scale = render.FONT_SCALE_DEFAULT
        render.STYLE.show_labels = False
        paths.SETTINGS_FILE.write_text(
            json.dumps(
                {"font_scale": render.FONT_SCALE_MAX, "show_labels": True}
            ),
            encoding="utf-8",
        )
        self.build()
        self.assertEqual(render.FONT_SCALE_MAX, render.STYLE.font_scale)
        self.assertTrue(render.STYLE.show_labels)

    def test_tile_face_that_cannot_be_painted_does_not_stop_start(self):
        self.put("tile", (
            "tiles=[TileProvider(1, lambda ctx: ['q'], "
            "lambda ctx, item: KeyFace(colors.OK, 5), "
            "lambda ctx, item: None)]"
        ))
        k = self.build()
        k.render()
        self.assertIn("tile: key 5 paint failed", self.journal.getvalue())


class ReadPluginsOffTest(AppCase):
    def test_one_id_per_line_from_the_settings_library(self):
        conf = S.CONFIG / "erplibre-home" / "streamdeck.conf"
        conf.write_text("DECK_PLUGINS_OFF= a , ,b\n", encoding="utf-8")
        self.assertEqual(["a", "b"], app.read_plugins_off())

    def test_bash_missing_or_timing_out_gives_none_and_a_line(self):
        for exc in (
            FileNotFoundError("bash"),
            subprocess.TimeoutExpired("bash", 10),
        ):
            self.journal.truncate(0)
            with mock.patch.object(
                app.subprocess, "run", side_effect=exc
            ):
                self.assertEqual([], app.read_plugins_off())
            self.assertIn(
                "DECK_PLUGINS_OFF unreadable", self.journal.getvalue()
            )

    def test_library_failing_gives_none_and_its_stderr(self):
        missing = self.user / "no_such_settings.sh"
        with mock.patch.object(app.paths, "SETTINGS_LIB", missing):
            self.assertEqual([], app.read_plugins_off())
        journal = self.journal.getvalue()
        self.assertIn("DECK_PLUGINS_OFF unreadable", journal)
        self.assertIn("no_such_settings.sh", journal)


class RecordingDeck(S.FakeDeck):
    def __init__(self, *a):
        super().__init__(*a)
        self.events = []

    def reset(self):
        self.events.append("reset")

    def close(self):
        self.events.append("close")


class MainTest(AppCase):
    """main() with a deck that is already closed: it builds, renders,
    installs the callback, then goes straight to its shutdown."""

    def run_main(self, kernel_hook):
        deck = RecordingDeck(5, 3)
        self.shut = []
        plugin = LoadedPlugin("p", Plugin(
            api=PLUGIN_API, shutdown=lambda ctx: self.shut.append(1),
        ), "user", Path("p.py"))

        def build(d, plugins_off=()):
            kernel = K.Kernel(d, [plugin])
            kernel_hook(kernel)
            self.kernel = kernel
            return kernel

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(S, "DEVICES", [deck]))
        stack.enter_context(mock.patch.object(app, "build", build))
        stack.enter_context(
            mock.patch.object(app, "read_plugins_off", list)
        )
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(
            mock.patch.object(app, "SHUTDOWN_LOCK_SEC", 0.05, create=True)
        )
        return deck

    def test_shutdown_does_not_wait_forever_for_the_lock(self):
        def hold(kernel):
            kernel.lock.acquire()
            self.addCleanup(kernel.lock.release)

        deck = self.run_main(hold)
        thread = threading.Thread(target=app.main, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "main waits for the lock")
        self.assertEqual([1], self.shut)
        self.assertEqual(["reset", "reset", "close"], deck.events)
        self.assertIn("kernel lock", self.journal.getvalue())
        self.assertEqual(self.kernel.on_key, deck.callback)

    def test_deck_is_reset_when_shutdown_raises(self):
        def broken(kernel):
            kernel.shutdown = mock.Mock(side_effect=RuntimeError("stop"))

        deck = self.run_main(broken)
        with self.assertRaises(RuntimeError):
            app.main()
        self.assertEqual(["reset", "reset", "close"], deck.events)
        self.assertFalse(self.kernel.lock.locked())


if __name__ == "__main__":
    unittest.main()
