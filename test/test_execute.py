#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import unittest
from unittest.mock import patch

from script.execute.execute import Execute


class TestExecuteInit(unittest.TestCase):
    """Test Execute class initialization."""

    @patch("shutil.which")
    def test_init_with_gnome_terminal(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
        )
        exe = Execute()
        self.assertIn("gnome-terminal", exe.cmd_source_erplibre)
        self.assertIn(".venv.erplibre", exe.cmd_source_erplibre)
        self.assertIn("gnome-terminal", exe.cmd_source_default)

    @patch("shutil.which")
    def test_init_with_osascript(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/osascript" if x == "osascript" else None
        )
        exe = Execute()
        self.assertIn("osascript", exe.cmd_source_erplibre)

    @patch("shutil.which", return_value=None)
    def test_init_fallback_source(self, mock_which):
        exe = Execute()
        self.assertIn(".venv.erplibre/bin/activate", exe.cmd_source_erplibre)
        self.assertEqual(exe.cmd_source_default, "")


class TestExecCommandLive(unittest.TestCase):
    """Test exec_command_live method."""

    def setUp(self):
        with patch("shutil.which", return_value=None):
            self.exe = Execute()

    def test_simple_command_returns_zero(self):
        result = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 0)

    def test_failing_command_returns_nonzero(self):
        result = self.exe.exec_command_live(
            "exit 42",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 42)

    def test_return_status_and_output(self):
        status, output = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["hello"])

    def test_return_status_and_output_multiline(self):
        status, output = self.exe.exec_command_live(
            "echo -e 'line1\nline2\nline3'",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["line1", "line2", "line3"])

    def test_return_status_and_command(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo test")

    def test_return_status_and_output_and_command(self):
        status, cmd, output = self.exe.exec_command_live(
            "echo result",
            source_erplibre=False,
            quiet=True,
            return_status_and_output_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo result")
        self.assertEqual(output, ["result"])

    def test_source_erplibre_prepends_activate(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)

    def test_single_source_erplibre(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)
        self.assertIn("echo test", cmd)

    def test_single_source_odoo_no_version_returns_error(self):
        with patch("os.path.exists", return_value=False):
            result = self.exe.exec_command_live(
                "echo test",
                source_erplibre=False,
                single_source_odoo=True,
                source_odoo="",
                quiet=True,
            )
        self.assertEqual(result, -1)

    def test_single_source_odoo_with_version(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_odoo=True,
            source_odoo="odoo18",
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.odoo18/bin/activate", cmd)

    def test_new_env_passed_to_subprocess(self):
        status, output = self.exe.exec_command_live(
            "echo $MY_TEST_VAR",
            source_erplibre=False,
            quiet=True,
            new_env={"MY_TEST_VAR": "test_value_123"},
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["test_value_123"])

    def test_empty_output_command(self):
        status, output = self.exe.exec_command_live(
            "true",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, [])


if __name__ == "__main__":
    unittest.main()
