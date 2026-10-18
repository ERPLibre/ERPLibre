#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Parsers of the system tools the deck plugins read."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import dbus, paths, settings  # noqa: E402
from erplibre_streamdeck.kernel import Kernel  # noqa: E402
from erplibre_streamdeck.plugin import LoadedPlugin  # noqa: E402
from erplibre_streamdeck.plugins import (  # noqa: E402
    bluetooth, claude_sessions, layouts, sound, timers,
)
from erplibre_streamdeck.ui import render  # noqa: E402


WPCTL_STATUS = """\
Audio
 ├─ Devices:
 │      40. Built-in Audio                      [alsa]
 │
 ├─ Sinks:
 │  *   51. Built-in Audio Analog Stereo        [vol: 0.40]
 │      62. Demo Headset                        [vol: 0.70]
 │
 ├─ Sources:
 │  *   52. Built-in Audio Analog Stereo        [vol: 1.00 MUTED]
 │
 ├─ Filters:
"""


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


def by_argv(answers):
    """A subprocess.run stand-in answering by the first two argv words."""

    def run(argv, **kwargs):
        return answers.get(tuple(argv[:2]), done("", 1))

    return run


class WpctlTest(unittest.TestCase):
    def test_get_volume_and_mute(self):
        with mock.patch(
            "subprocess.run", return_value=done("Volume: 0.50 [MUTED]\n")
        ):
            self.assertEqual((50, True), sound._wpctl_get("@X@"))

    def test_get_volume_not_muted(self):
        with mock.patch(
            "subprocess.run", return_value=done("Volume: 1.00\n")
        ):
            self.assertEqual((100, False), sound._wpctl_get("@X@"))

    def test_get_malformed(self):
        with mock.patch("subprocess.run", return_value=done("garbage")):
            self.assertEqual((None, None), sound._wpctl_get("@X@"))

    def test_get_failure(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual((None, None), sound._wpctl_get("@X@"))

    def test_list_devices(self):
        with mock.patch("subprocess.run", return_value=done(WPCTL_STATUS)):
            sinks = sound._wpctl_list_devices("Sinks")
            sources = sound._wpctl_list_devices("Sources")
        self.assertEqual(
            [
                {"id": 51, "default": True,
                 "name": "Built-in Audio Analog Stereo"},
                {"id": 62, "default": False, "name": "Demo Headset"},
            ],
            sinks,
        )
        self.assertEqual([52], [d["id"] for d in sources])

    def test_list_devices_failure(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual([], sound._wpctl_list_devices("Sinks"))

    def test_default_short_is_last_word_cut_to_six(self):
        with mock.patch("subprocess.run", return_value=done(WPCTL_STATUS)):
            self.assertEqual("Stereo", sound._wpctl_default_short("Sinks"))

    def test_default_short_empty_without_devices(self):
        with mock.patch("subprocess.run", return_value=done("", 1)):
            self.assertEqual("", sound._wpctl_default_short("Sinks"))


class BluetoothTest(unittest.TestCase):
    def test_powered_from_bluetoothctl(self):
        shown = done(
            "Controller 00:00:5E:00:53:01\n\tPowered: yes\n"
        )
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", return_value=shown):
            self.assertIs(True, bluetooth._bt_powered())

    def test_powered_off_from_bluetoothctl(self):
        shown = done("Controller 00:00:5E:00:53:01\n\tPowered: no\n")
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", return_value=shown):
            self.assertIs(False, bluetooth._bt_powered())

    def test_powered_falls_back_to_rfkill(self):
        answers = {
            ("bluetoothctl", "show"): done("", 1),
            ("rfkill", "list"): done("0: hci0: Bluetooth\n"
                                     "\tSoft blocked: no\n"),
        }
        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", by_argv(answers)):
            self.assertIs(True, bluetooth._bt_powered())

    def test_powered_unknown_without_any_tool(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(bluetooth._bt_powered())

    def test_paired_merges_connected(self):
        paired = done(
            "Device 00:00:5E:00:53:10 Demo Headphones\n"
            "Device 00:00:5E:00:53:11 Demo Keyboard\n"
        )
        connected = done("Device 00:00:5E:00:53:11 Demo Keyboard\n")

        def run(argv, **kwargs):
            return paired if argv[-1] == "Paired" else connected

        with mock.patch("shutil.which", return_value="/usr/bin/x"), \
                mock.patch("subprocess.run", run):
            devices = bluetooth._bt_list_paired()
        self.assertEqual(
            [
                ("00:00:5E:00:53:10", "Demo Headphones", False),
                ("00:00:5E:00:53:11", "Demo Keyboard", True),
            ],
            devices,
        )

    def test_paired_empty_without_bluetoothctl(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual([], bluetooth._bt_list_paired())


class LayoutsTest(unittest.TestCase):
    def test_save_then_load_round_trips_through_layouts_file(self):
        class Ctx:
            pass

        ctx = Ctx()
        ctx.dbus = dbus
        ctx.log = lambda msg: None
        answers = {
            "ListWindows": done("('[{\"id\": \"1\", \"x\": 0}]',)\n"),
            "ApplyLayout": done("(1,)\n"),
        }
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return answers[argv[8].rsplit(".", 1)[1]]

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "conf"
            with mock.patch.object(paths, "CONFIG_DIR", conf), \
                    mock.patch.object(
                        paths, "LAYOUTS_FILE", conf / "layouts.json"
                    ), mock.patch("subprocess.run", side_effect=run):
                self.assertTrue(layouts._save_layout_slot(ctx, 2))
                saved = layouts._layouts_load()["slots"]["2"]
                self.assertEqual([{"id": "1", "x": 0}], saved["windows"])
                self.assertEqual(1, saved["count"])
                self.assertTrue(layouts._load_layout_slot(ctx, 2))
                self.assertFalse(layouts._load_layout_slot(ctx, 3))
        self.assertTrue(calls[-1][-1].startswith('[{"id"'))


class TimersTest(unittest.TestCase):
    def test_label_is_first_word_and_minutes_seconds(self):
        timer = {"name": "Write report", "elapsed": 125}
        self.assertEqual("Write\n02:05", timers._label_for_timer(timer))

    def test_tracker_answer_gives_one_timer(self):
        class Ctx:
            pass

        ctx = Ctx()
        ctx.dbus = dbus
        ctx.log = lambda msg: None
        answer = done('(\'[{"id": "t1", "running": true}]\',)\n')
        with mock.patch("subprocess.run", return_value=answer):
            found = timers._list_timers(ctx)
        self.assertEqual([{"id": "t1", "running": True}], found)


class SessionsTest(unittest.TestCase):
    def test_bad_pid_file_is_skipped_or_isolated(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "claude"
            state.mkdir()
            (state / "bad.json").write_text(
                json.dumps({"session_id": "s", "pid": "abc"})
            )
            with mock.patch.object(paths, "state_dir", lambda: Path(tmp)):
                # int("abc") escapes load_sessions: it neither skips the
                # file nor drops the others.
                with self.assertRaises(ValueError):
                    claude_sessions.load_sessions()
                loaded = LoadedPlugin(
                    "claude_sessions", claude_sessions.PLUGIN, "repo",
                    Path(claude_sessions.__file__),
                )
                err = io.StringIO()
                with mock.patch.object(dbus, "available", lambda: False):
                    kernel = Kernel(S.FakeDeck(5, 3), [loaded])
                    with contextlib.redirect_stderr(err):
                        kernel.render()
                        kernel.render()
        lines = [
            ln for ln in err.getvalue().splitlines()
            if ln.startswith("[erplibre-home] claude_sessions")
        ]
        # One journal entry for the two renders, not none: the kernel
        # reports the failing provider once and goes on.
        self.assertEqual(1, len(lines))


class SettingsKeepTest(unittest.TestCase):
    def test_font_scale_save_keeps_other_keys(self):
        stored = {"translator_llm": "ollama", "font_scale": 1.0}

        def save(data):
            stored.clear()
            stored.update(data)

        with mock.patch.object(settings, "load", lambda: dict(stored)), \
                mock.patch.object(settings, "save", save):
            render.Style().set_font_scale(1.2, settings)
        self.assertEqual("ollama", stored["translator_llm"])
        self.assertEqual(1.2, stored["font_scale"])


if __name__ == "__main__":
    unittest.main()
