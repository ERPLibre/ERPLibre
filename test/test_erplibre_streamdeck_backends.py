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
from erplibre_streamdeck import settings  # noqa: E402
from erplibre_streamdeck.plugins import bluetooth, sound  # noqa: E402
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
