#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Base modules of the deck package: paths, settings, D-Bus client,
display style."""

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import dbus, paths, settings  # noqa: E402
from erplibre_streamdeck.plugin import RepeatLog  # noqa: E402
from erplibre_streamdeck.ui import render  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_repository_files_exist(self):
        self.assertTrue((paths.REPO_ROOT / "script/todo/todo.py").exists())
        self.assertTrue(
            (paths.STREAM_DECK_DIR / "translator_stream.py").exists()
        )

    def test_settings_stay_under_dot_config(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/elsewhere"}):
            self.assertNotIn("/elsewhere", str(paths.SETTINGS_FILE))
        self.assertTrue(
            str(paths.SETTINGS_FILE).endswith(
                "/.config/erplibre-home/settings.json"
            )
        )

    def test_user_plugin_dir_follows_xdg_config_home(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x/conf"}):
            self.assertEqual(
                "/x/conf/erplibre-home/deck-plugins",
                str(paths.user_plugin_dir()),
            )


class DbusTest(unittest.TestCase):
    def run_with(self, **kw):
        done = subprocess.CompletedProcess([], **kw)
        return mock.patch("subprocess.run", return_value=done)

    def test_call_argv_and_true(self):
        with self.run_with(returncode=0, stdout="(true,)\n", stderr="") as r:
            reply = dbus.call("TileWindow", 4, 2, 0, 0, 1, 1, timeout=3)
        argv = r.call_args.args[0]
        self.assertEqual(
            argv[:8],
            [
                "gdbus", "call", "--session", "--dest", dbus.DEST,
                "--object-path", dbus.PATH, "--method",
            ],
        )
        self.assertEqual(argv[8], f"{dbus.IFACE}.TileWindow")
        self.assertEqual(argv[9:], ["4", "2", "0", "0", "1", "1"])
        self.assertTrue(reply.true)

    def test_call_never_raises(self):
        for exc in (
            FileNotFoundError(2, "gdbus"),
            subprocess.TimeoutExpired(["gdbus"], 3),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        ):
            with mock.patch("subprocess.run", side_effect=exc):
                reply = dbus.call("HotReload")
            self.assertIsNone(reply.returncode)
            self.assertFalse(reply.ok)
            self.assertFalse(reply.true)
            self.assertIsNone(reply.string)

    def test_call_strips_the_output_of_its_trailing_newline(self):
        # gdbus ends its error with a newline: kept, a journal line
        # quoting it is followed by an empty one.
        with self.run_with(
            returncode=1, stdout="(false,)\n", stderr="Error: gone\n"
        ):
            reply = dbus.call("ListTrackerTimers")
        self.assertEqual("Error: gone", reply.stderr)
        self.assertEqual("(false,)", reply.stdout)

    def test_string_tuple(self):
        self.assertEqual(
            "a'b\\c", dbus.parse_string_tuple("('a\\'b\\\\c',)\n")
        )
        self.assertIsNone(dbus.parse_string_tuple("(true,)"))


class RepeatLogTest(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.log = RepeatLog(self.lines.append, "Timer list")

    def run_pass(self, *failures):
        with self.log.watch() as log:
            for msg in failures:
                log(msg)

    def test_a_failure_repeated_is_written_once(self):
        for _ in range(5):
            self.run_pass("dbus: UnknownMethod")
        self.assertEqual(["dbus: UnknownMethod"], self.lines)

    def test_recovery_is_written_once(self):
        self.run_pass("dbus: UnknownMethod")
        self.run_pass()
        self.run_pass()
        self.assertEqual(
            ["dbus: UnknownMethod", "Timer list: recovered"], self.lines
        )

    def test_success_without_a_failure_writes_nothing(self):
        self.run_pass()
        self.run_pass()
        self.assertEqual([], self.lines)

    def test_a_different_failure_is_written_again(self):
        self.run_pass("dbus: UnknownMethod")
        self.run_pass("dbus: UnknownMethod")
        self.run_pass("dbus: Timeout")
        self.run_pass("dbus: Timeout")
        self.assertEqual(["dbus: UnknownMethod", "dbus: Timeout"], self.lines)

    def test_a_failure_after_recovery_is_written_again(self):
        self.run_pass("dbus: UnknownMethod")
        self.run_pass()
        self.run_pass("dbus: UnknownMethod")
        self.assertEqual(3, len(self.lines))

    def test_a_message_is_one_line(self):
        self.run_pass("dbus: Error\nsecond line\n")
        self.assertEqual(["dbus: Error second line"], self.lines)

    def test_a_raising_pass_leaves_the_state(self):
        self.run_pass("dbus: UnknownMethod")
        with self.assertRaises(ValueError):
            with self.log.watch():
                raise ValueError("bad")
        self.run_pass("dbus: UnknownMethod")
        self.assertEqual(["dbus: UnknownMethod"], self.lines)


    def test_a_failure_after_a_pause_is_written_again(self):
        """A poll inactive for a while (its page not shown, its plugin
        busy, the deck replugged) may have seen its cause fixed and come
        back: the same failure is news again."""
        now = [0.0]
        self.log = RepeatLog(self.lines.append, "Bluetooth read",
                             clock=lambda: now[0])
        self.run_pass("bluetoothctl show error: X")
        now[0] += RepeatLog.FORGET_SEC + 1
        self.run_pass("bluetoothctl show error: X")
        self.assertEqual(2, len(self.lines))

    def test_a_pass_within_the_pause_keeps_quiet(self):
        now = [0.0]
        self.log = RepeatLog(self.lines.append, "Bluetooth read",
                             clock=lambda: now[0])
        self.run_pass("bluetoothctl show error: X")
        now[0] += RepeatLog.FORGET_SEC - 1
        self.run_pass("bluetoothctl show error: X")
        self.assertEqual(1, len(self.lines))

    def test_a_clean_pass_after_a_pause_writes_nothing(self):
        now = [0.0]
        self.log = RepeatLog(self.lines.append, "Bluetooth read",
                             clock=lambda: now[0])
        self.run_pass("bluetoothctl show error: X")
        now[0] += RepeatLog.FORGET_SEC + 1
        self.run_pass()
        self.assertEqual(["bluetoothctl show error: X"], self.lines)


class StyleTest(unittest.TestCase):
    def test_restore_clamps_and_survives_garbage(self):
        style = render.Style()
        style.restore({"font_scale": 9, "show_labels": 1})
        self.assertEqual(render.FONT_SCALE_MAX, style.font_scale)
        self.assertTrue(style.show_labels)
        style.restore({"font_scale": "big"})
        self.assertEqual(render.FONT_SCALE_DEFAULT, style.font_scale)

    def test_set_font_scale_keeps_other_keys(self):
        with mock.patch.object(
            settings, "load", return_value={"translator_stt": "vosk"}
        ), mock.patch.object(settings, "save") as save:
            render.Style().set_font_scale(1.234, settings)
        self.assertEqual(
            {"translator_stt": "vosk", "font_scale": 1.23},
            save.call_args.args[0],
        )


if __name__ == "__main__":
    unittest.main()
