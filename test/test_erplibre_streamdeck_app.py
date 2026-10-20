#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck program's start and stop: build(), read_deck_settings(),
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
from erplibre_streamdeck import context  # noqa: E402
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

    def build(self, off=(), settings=None):
        return app.build(
            self.deck, plugins_off=ALL_REPO_OFF + tuple(off),
            user_dir=self.user, settings=settings,
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


class ReadDeckSettingsTest(AppCase):
    DEFAULTS = {"plugins_off": [], "session_refresh_sec": 1.0}

    def conf(self, text):
        path = S.CONFIG / "erplibre-home" / "streamdeck.conf"
        path.write_text(text, encoding="utf-8")

    def test_ids_and_refresh_from_the_settings_library(self):
        self.conf("DECK_PLUGINS_OFF= a , ,b\nDECK_SESSION_REFRESH_SEC=2\n")
        self.assertEqual(
            {"plugins_off": ["a", "b"], "session_refresh_sec": 2.0},
            app.read_deck_settings(),
        )

    def test_missing_file_gives_the_defaults(self):
        self.assertEqual(self.DEFAULTS, app.read_deck_settings())

    def test_invalid_refresh_reads_as_one(self):
        for value in ("0.4", "61", "abc", ""):
            self.conf(f"DECK_SESSION_REFRESH_SEC={value}\n")
            self.assertEqual(
                1.0, app.read_deck_settings()["session_refresh_sec"], value
            )

    def test_half_second_and_sixty_are_kept(self):
        for value, expected in (("0.5", 0.5), ("60", 60.0)):
            self.conf(f"DECK_SESSION_REFRESH_SEC={value}\n")
            self.assertEqual(
                expected, app.read_deck_settings()["session_refresh_sec"]
            )

    def test_bash_missing_or_timing_out_gives_defaults_and_a_line(self):
        for exc in (
            FileNotFoundError("bash"),
            subprocess.TimeoutExpired("bash", 10),
        ):
            self.journal.truncate(0)
            with mock.patch.object(
                app.subprocess, "run", side_effect=exc
            ):
                self.assertEqual(self.DEFAULTS, app.read_deck_settings())
            self.assertIn("deck settings unreadable", self.journal.getvalue())

    def test_library_failing_gives_defaults_and_its_stderr(self):
        missing = self.user / "no_such_settings.sh"
        with mock.patch.object(app.paths, "SETTINGS_LIB", missing):
            self.assertEqual(self.DEFAULTS, app.read_deck_settings())
        journal = self.journal.getvalue()
        self.assertIn("deck settings unreadable", journal)
        self.assertIn("no_such_settings.sh", journal)

    def test_defaults_are_not_shared_between_calls(self):
        with mock.patch.object(
            app.subprocess, "run", side_effect=FileNotFoundError("bash")
        ):
            app.read_deck_settings()["plugins_off"].append("x")
            self.assertEqual([], app.read_deck_settings()["plugins_off"])


class BuildSettingsTest(AppCase):
    def test_settings_reach_the_kernel_and_the_context(self):
        k = self.build(settings={"session_refresh_sec": 2.5})
        self.assertEqual({"session_refresh_sec": 2.5}, k.settings)
        ctx = context.Context(k, "p")
        self.assertEqual(2.5, ctx.setting("session_refresh_sec"))
        self.assertEqual(7, ctx.setting("nope", 7))
        self.assertIsNone(ctx.setting("nope"))

    def test_no_settings_is_an_empty_dict(self):
        self.assertEqual({}, self.build().settings)


class RecordingDeck(S.FakeDeck):
    """A deck that records open, reset, brightness and close. The thread
    that opens it is the one main() runs in: is_open() raises `stop`
    there when it is set (a Ctrl-C or a SIGTERM while the deck runs),
    and answers False otherwise, as a deck the library has closed. Once
    it answered False, reset() raises the library's TransportError, as
    on a vanished device."""

    def __init__(self, *a):
        super().__init__(*a)
        self.events = []
        self.owner = None
        self.stop = None
        self.gone = False
        self.fail_open = False

    def open(self):
        if self.fail_open:
            raise S.TransportError("Could not open HID device.")
        self.owner = threading.get_ident()
        self.events.append("open")

    def set_brightness(self, percent):
        self.events.append(f"brightness {percent}")

    def is_open(self):
        if self.stop is not None and threading.get_ident() == self.owner:
            raise self.stop
        self.gone = self.stop is None
        return False

    def reset(self):
        if self.gone:
            raise S.TransportError("No HID device.")
        self.events.append("reset")

    def close(self):
        self.events.append("close")


class ScriptedManager:
    """DeviceManager().enumerate() answering `script` in turn, one item a
    call: a list of decks, or an exception it raises."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def __call__(self):
        return self

    def enumerate(self):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return list(item)


class MainCase(AppCase):
    def run_main(self, kernel_hook=lambda kernel: None, manager=None):
        """Patch main()'s collaborators: each built kernel runs one
        plugin `p` whose shutdown appends to self.shut, and lands in
        self.kernels; the decks come from `manager`, else S.DEVICES."""
        deck = RecordingDeck(5, 3)
        self.shut = []
        self.kernels = []
        plugin = LoadedPlugin("p", Plugin(
            api=PLUGIN_API, shutdown=lambda ctx: self.shut.append(1),
        ), "user", Path("p.py"))

        def build(d, plugins_off=(), settings=None):
            kernel = K.Kernel(d, [plugin])
            kernel_hook(kernel)
            self.kernel = kernel
            self.kernels.append(kernel)
            return kernel

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(S, "DEVICES", [deck]))
        if manager is not None:
            stack.enter_context(
                mock.patch.object(app, "DeviceManager", manager)
            )
        stack.enter_context(mock.patch.object(app, "build", build))
        stack.enter_context(
            mock.patch.object(
                app, "read_deck_settings",
                lambda: dict(plugins_off=[], session_refresh_sec=1.0),
            )
        )
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(
            mock.patch.object(app, "SHUTDOWN_LOCK_SEC", 0.05, create=True)
        )
        stack.enter_context(
            mock.patch.object(app, "REPLUG_POLL_SEC", 0.001, create=True)
        )
        return deck


class MainTest(MainCase):
    """main() stopped by a Ctrl-C while the deck runs: it builds,
    renders, installs the callback, then goes to its shutdown."""

    def test_shutdown_does_not_wait_forever_for_the_lock(self):
        def hold(kernel):
            kernel.lock.acquire()
            self.addCleanup(kernel.lock.release)

        deck = self.run_main(hold)
        deck.stop = KeyboardInterrupt()
        thread = threading.Thread(target=app.main, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "main waits for the lock")
        self.assertEqual([1], self.shut)
        self.assertEqual(
            ["open", "reset", "brightness 80", "reset", "close"],
            deck.events,
        )
        self.assertIn("kernel lock", self.journal.getvalue())
        self.assertEqual(self.kernel.on_key, deck.callback)

    def test_deck_is_reset_when_shutdown_raises(self):
        def broken(kernel):
            kernel.shutdown = mock.Mock(side_effect=RuntimeError("stop"))

        deck = self.run_main(broken)
        deck.stop = KeyboardInterrupt()
        with self.assertRaises(RuntimeError):
            app.main()
        self.assertEqual(
            ["open", "reset", "brightness 80", "reset", "close"],
            deck.events,
        )
        self.assertFalse(self.kernel.lock.locked())


class ShutdownTest(MainCase):
    def test_a_vanished_deck_is_one_journal_line_not_a_traceback(self):
        deck = RecordingDeck(5, 3)
        deck.gone = True
        kernel = K.Kernel(deck, [])
        app._shutdown(kernel, deck)
        journal = self.journal.getvalue()
        self.assertEqual(1, journal.count("No HID device."), journal)
        self.assertFalse(kernel.lock.locked())

    def test_sigterm_with_the_deck_gone_exits_with_its_code(self):
        deck = self.run_main()
        deck.stop = SystemExit(143)
        deck.reset = mock.Mock(side_effect=[None, S.TransportError("x")])
        with self.assertRaises(SystemExit) as caught:
            app.main()
        self.assertEqual(143, caught.exception.code)
        self.assertEqual([1], self.shut)

    def test_sigterm_while_the_first_kernel_builds_resets_the_deck(self):
        def stop(kernel):
            raise SystemExit(143)

        deck = self.run_main(stop)
        with self.assertRaises(SystemExit) as caught:
            app.main()
        self.assertEqual(143, caught.exception.code)
        self.assertEqual(
            ["open", "reset", "brightness 80", "reset", "close"],
            deck.events,
        )


class ReplugTest(MainCase):
    """The deck vanishes while main() runs: one journal line, a poll of
    DeviceManager every REPLUG_POLL_SEC, and a kernel rebuilt on the deck
    that comes back."""

    def unplugged_lines(self):
        return self.journal.getvalue().count(
            "Stream Deck unplugged, waiting for it to come back"
        )

    def test_a_deck_plugged_back_gets_a_new_kernel(self):
        back = RecordingDeck(5, 3)
        back.stop = SystemExit(143)
        manager = ScriptedManager([], [], [back])
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        with self.assertRaises(SystemExit) as caught:
            app.main()
        self.assertEqual(143, caught.exception.code)
        self.assertEqual(4, manager.calls)
        self.assertEqual(1, self.unplugged_lines())
        self.assertIn("Stream Deck back", self.journal.getvalue())
        self.assertNotIn("Traceback", self.journal.getvalue())
        old, new = self.kernels
        self.assertIs(first, old.deck)
        self.assertFalse(old.running)
        self.assertIs(back, new.deck)
        self.assertEqual(new.on_key, back.callback)
        self.assertTrue(any(back.rendering()), "nothing rendered")
        self.assertEqual(
            ["open", "reset", "brightness 80", "reset", "close"],
            back.events,
        )
        self.assertEqual(["open", "reset", "brightness 80"], first.events)
        self.assertEqual([1, 1], self.shut)

    def test_a_deck_that_fails_to_open_is_tried_again(self):
        bad = RecordingDeck(5, 3)
        bad.fail_open = True
        back = RecordingDeck(5, 3)
        back.stop = SystemExit(143)
        manager = ScriptedManager([bad], [back])
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        with self.assertRaises(SystemExit):
            app.main()
        self.assertEqual(2, len(self.kernels))
        self.assertIs(back, self.kernels[1].deck)

    def test_a_deck_that_never_opens_is_journaled_once(self):
        """A deck plugged in but refused (its hidraw node not
        accessible) is told apart from an unplugged one, without a line
        every poll."""
        bad = RecordingDeck(5, 3)
        bad.fail_open = True
        manager = ScriptedManager([bad], [bad], [bad], KeyboardInterrupt())
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        app.main()
        journal = self.journal.getvalue()
        self.assertEqual(
            1, journal.count("Stream Deck found but not opened"), journal
        )
        self.assertIn("Could not open HID device.", journal)
        self.assertEqual(["close", "close", "close"], bad.events)

    def flapping(self):
        """main() over a deck that comes back three times and vanishes
        at once each time; the delays its waits were given."""
        backs = [RecordingDeck(5, 3) for _ in range(3)]
        backs[-1].stop = SystemExit(143)
        manager = ScriptedManager(*[[d] for d in backs])
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        with mock.patch.object(
            app, "_wait_for_deck", wraps=app._wait_for_deck
        ) as wait, self.assertRaises(SystemExit):
            app.main()
        return [c.args[0] for c in wait.call_args_list]

    def test_a_deck_that_vanishes_again_at_once_backs_off(self):
        """Each rebuild runs every plugin setup: a deck that keeps
        closing as soon as it opens is looked for less and less often,
        up to REPLUG_MAX_SEC."""
        with mock.patch.object(app, "REPLUG_MAX_SEC", 0.003):
            self.assertEqual([0.001, 0.002, 0.003], self.flapping())
        self.assertIn("looking every 0.002 s", self.journal.getvalue())

    def test_a_deck_that_stays_keeps_the_short_poll(self):
        with mock.patch.object(app, "FLAP_SEC", 0.0):
            self.assertEqual([0.001] * 3, self.flapping())

    def test_sigterm_while_the_kernel_is_rebuilt_resets_the_deck(self):
        """The deck that came back is open and lit before its kernel
        exists: a SIGTERM then still resets and closes it."""
        back = RecordingDeck(5, 3)
        manager = ScriptedManager([], [back])
        built = []

        def stop_second(kernel):
            built.append(kernel)
            if len(built) == 2:
                raise SystemExit(143)

        first = self.run_main(stop_second, manager=manager)
        manager.script.insert(0, [first])
        with self.assertRaises(SystemExit) as caught:
            app.main()
        self.assertEqual(143, caught.exception.code)
        self.assertEqual(
            ["open", "reset", "brightness 80", "reset", "close"],
            back.events,
        )
        self.assertEqual(["open", "reset", "brightness 80"], first.events)
        self.assertEqual([1], self.shut)

    def test_sigterm_during_the_wait_stops_cleanly(self):
        manager = ScriptedManager([], SystemExit(143))
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        with self.assertRaises(SystemExit) as caught:
            app.main()
        self.assertEqual(143, caught.exception.code)
        self.assertEqual(1, self.unplugged_lines())
        self.assertNotIn("Stream Deck back", self.journal.getvalue())
        self.assertEqual([1], self.shut)
        self.assertEqual(["open", "reset", "brightness 80"], first.events)
        self.assertFalse(self.kernel.lock.locked())

    def test_ctrl_c_during_the_wait_returns(self):
        manager = ScriptedManager([], KeyboardInterrupt())
        first = self.run_main(manager=manager)
        manager.script.insert(0, [first])
        app.main()
        self.assertEqual([1], self.shut)


if __name__ == "__main__":
    unittest.main()
