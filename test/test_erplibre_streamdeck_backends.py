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
from erplibre_streamdeck.plugins import bluetooth  # noqa: E402
from erplibre_streamdeck.ui import render  # noqa: E402


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "")


def by_argv(answers):
    """A subprocess.run stand-in answering by the first two argv words."""

    def run(argv, **kwargs):
        return answers.get(tuple(argv[:2]), done("", 1))

    return run


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
