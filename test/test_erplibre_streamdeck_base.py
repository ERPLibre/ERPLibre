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

    def test_string_tuple(self):
        self.assertEqual(
            "a'b\\c", dbus.parse_string_tuple("('a\\'b\\\\c',)\n")
        )
        self.assertIsNone(dbus.parse_string_tuple("(true,)"))


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
