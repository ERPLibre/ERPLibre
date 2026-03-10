#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from script.todo.todo import (
    ANDROID_DIR,
    CONFIG_FILE,
    CONFIG_OVERRIDE_FILE,
    ENABLE_CRASH,
    ERROR_LOG_PATH,
    GRADLE_FILE,
    LOGO_ASCII_FILE,
    MOBILE_HOME_PATH,
    STRINGS_FILE,
    TODO,
    VENV_ERPLIBRE,
)
from script.todo.version_manager import (
    INSTALLED_ODOO_VERSION_FILE,
    ODOO_VERSION_FILE,
    VERSION_DATA_FILE,
    get_odoo_version,
)


class TestTODOInit(unittest.TestCase):
    def test_initial_attributes(self):
        todo = TODO()
        self.assertIsNone(todo.dir_path)
        self.assertIsNone(todo.selected_file_path)
        self.assertIsNotNone(todo.config_file)
        self.assertIsNotNone(todo.execute)
        self.assertIsNotNone(todo.kdbx_manager)


class TestFillHelpInfo(unittest.TestCase):
    def setUp(self):
        self.todo = TODO()

    @patch("script.todo.todo.t")
    def test_basic_help_info(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
        }.get(k, k)
        lst_choice = [
            {"prompt_description": "Option A"},
            {"prompt_description": "Option B"},
        ]
        result = self.todo.fill_help_info(lst_choice)
        self.assertIn("[1] Option A", result)
        self.assertIn("[2] Option B", result)
        self.assertIn("[0] Back", result)

    @patch("script.todo.todo.t")
    def test_with_prompt_description_key(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
            "my_key": "Translated Description",
        }.get(k, k)
        lst_choice = [
            {
                "prompt_description": "fallback",
                "prompt_description_key": "my_key",
            },
        ]
        result = self.todo.fill_help_info(lst_choice)
        self.assertIn("[1] Translated Description", result)

    @patch("script.todo.todo.t")
    def test_empty_list(self, mock_t):
        mock_t.side_effect = lambda k: {
            "command": "Command:",
            "back": "Back",
        }.get(k, k)
        result = self.todo.fill_help_info([])
        self.assertIn("Command:", result)
        self.assertIn("[0] Back", result)
        self.assertNotIn("[1]", result)


class TestGetOdooVersion(unittest.TestCase):
    def test_reads_version_data(self):
        version_data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "default": True,
                "is_deprecated": False,
            },
            "odoo16.0_python3.10.18": {
                "odoo_version": "16.0",
                "python_version": "3.10.18",
                "default": False,
                "is_deprecated": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "version.json")
            with open(version_file, "w") as f:
                json.dump(version_data, f)

            odoo_version_file = os.path.join(tmpdir, ".odoo-version")
            with open(odoo_version_file, "w") as f:
                f.write("18.0")

            with patch(
                "script.todo.version_manager.VERSION_DATA_FILE", version_file
            ), patch(
                "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                os.path.join(tmpdir, "nonexistent.txt"),
            ), patch(
                "script.todo.version_manager.ODOO_VERSION_FILE",
                odoo_version_file,
            ):
                lst_version, lst_installed, odoo_current = (
                    get_odoo_version()
                )

            self.assertEqual(len(lst_version), 2)
            self.assertEqual(odoo_current, "odoo18.0")
            # Check erplibre_version was added
            names = [v["erplibre_version"] for v in lst_version]
            self.assertIn("odoo18.0_python3.12.10", names)
            self.assertIn("odoo16.0_python3.10.18", names)

    def test_installed_versions_read(self):
        version_data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "default": True,
                "is_deprecated": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "version.json")
            with open(version_file, "w") as f:
                json.dump(version_data, f)

            installed_file = os.path.join(tmpdir, "installed.txt")
            with open(installed_file, "w") as f:
                f.write("odoo18.0\nodoo16.0\n")

            with patch(
                "script.todo.version_manager.VERSION_DATA_FILE", version_file
            ), patch(
                "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
                installed_file,
            ), patch(
                "script.todo.version_manager.ODOO_VERSION_FILE",
                os.path.join(tmpdir, "nonexistent"),
            ):
                lst_version, lst_installed, odoo_current = (
                    get_odoo_version()
                )

            self.assertEqual(lst_installed, ["odoo16.0", "odoo18.0"])
            self.assertIsNone(odoo_current)

    def test_no_version_data_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            version_file = os.path.join(tmpdir, "empty.json")
            with open(version_file, "w") as f:
                json.dump({}, f)

            with patch("script.todo.version_manager.VERSION_DATA_FILE", version_file):
                with self.assertRaises(Exception):
                    get_odoo_version()


class TestOnDirSelected(unittest.TestCase):
    @patch("script.todo.todo.todo_file_browser", create=True)
    def test_sets_dir_path(self, mock_browser):
        todo = TODO()
        todo.on_dir_selected("/some/path")
        self.assertEqual(todo.dir_path, "/some/path")


class TestExecuteFromConfiguration(unittest.TestCase):
    def test_with_command(self):
        todo = TODO()
        todo.execute = MagicMock()
        dct = {"command": "./run.sh"}
        todo.execute_from_configuration(dct)
        todo.execute.exec_command_live.assert_called()

    def test_with_makefile_cmd(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 0
        dct = {"makefile_cmd": "run_test"}
        todo.execute_from_configuration(dct)
        call_args = todo.execute.exec_command_live.call_args
        self.assertIn("make run_test", call_args[0][0])

    def test_makefile_cmd_ignored_when_flag(self):
        todo = TODO()
        todo.execute = MagicMock()
        dct = {"makefile_cmd": "run_test"}
        todo.execute_from_configuration(dct, ignore_makefile=True)
        todo.execute.exec_command_live.assert_not_called()

    def test_with_callback(self):
        todo = TODO()
        todo.execute = MagicMock()
        callback = MagicMock()
        dct = {"callback": callback}
        todo.execute_from_configuration(dct)
        callback.assert_called_once_with(dct)

    def test_makefile_error_stops_execution(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = 1
        callback = MagicMock()
        dct = {"makefile_cmd": "broken", "callback": callback}
        todo.execute_from_configuration(dct)
        callback.assert_not_called()


class TestConstants(unittest.TestCase):
    def test_config_file_path(self):
        self.assertEqual(CONFIG_FILE, "./script/todo/todo.json")

    def test_config_override_path(self):
        self.assertEqual(CONFIG_OVERRIDE_FILE, "./private/todo/todo.json")

    def test_logo_path(self):
        self.assertEqual(LOGO_ASCII_FILE, "./script/todo/logo_ascii.txt")

    def test_venv_erplibre(self):
        self.assertEqual(VENV_ERPLIBRE, ".venv.erplibre")

    def test_file_error_path(self):
        self.assertEqual(ERROR_LOG_PATH, ".erplibre.error.txt")

    def test_version_data_file(self):
        self.assertEqual(
            VERSION_DATA_FILE,
            os.path.join("conf", "supported_version_erplibre.json"),
        )

    def test_mobile_paths(self):
        self.assertEqual(ANDROID_DIR, "android")
        self.assertIn("mobile", MOBILE_HOME_PATH)


class TestDeployGitServer(unittest.TestCase):
    def test_local_mode(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo._deploy_git_server(production_ready=False, action="init")
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("--action init", cmd)
        self.assertNotIn("--production-ready", cmd)

    def test_production_mode(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo._deploy_git_server(production_ready=True, action="all")
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("--production-ready", cmd)
        self.assertIn("--action all", cmd)


class TestProcessKillGitDaemon(unittest.TestCase):
    def test_calls_pkill(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.process_kill_git_daemon()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("pkill", cmd)
        self.assertIn("git daemon", cmd)


class TestExecuteUnitTests(unittest.TestCase):
    def test_success_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["OK"])
        with patch("builtins.print") as mock_print:
            todo.execute_unit_tests()
        cmd = todo.execute.exec_command_live.call_args[0][0]
        self.assertIn("unittest discover", cmd)

    def test_failure_path(self):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (1, ["FAIL"])
        with patch("builtins.print") as mock_print:
            todo.execute_unit_tests()
        # Verify it was called - error handling path


class TestKdbxGetExtraCommandUser(unittest.TestCase):
    def test_empty_kdbx_key(self):
        todo = TODO()
        result = todo.kdbx_manager.get_extra_command_user("")
        self.assertEqual(result, "")

    def test_none_kdbx_key(self):
        todo = TODO()
        result = todo.kdbx_manager.get_extra_command_user(None)
        self.assertEqual(result, "")

    def test_kdbx_not_available(self):
        todo = TODO()
        todo.kdbx_manager.get_kdbx = MagicMock(return_value=None)
        result = todo.kdbx_manager.get_extra_command_user("some_key")
        self.assertEqual(result, "")


class TestSetupClaudeCommit(unittest.TestCase):
    def test_existing_file_skips(self):
        todo = TODO()
        with patch("os.path.exists", return_value=True), patch(
            "builtins.print"
        ) as mock_print:
            todo._setup_claude_commit()
        # Should print exists message without asking for input


class TestSelectDatabase(unittest.TestCase):
    @patch("script.todo.todo.click")
    def test_select_database_returns_name(self, mock_click):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (
            0,
            ["db_test", "db_prod"],
        )
        mock_click.prompt.return_value = "1"
        result = todo.select_database()
        self.assertEqual(result, "db_test")

    @patch("script.todo.todo.click")
    def test_select_database_returns_false_on_zero(self, mock_click):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, ["db_test"])
        mock_click.prompt.return_value = "0"
        result = todo.select_database()
        self.assertFalse(result)


class TestRestoreFromDatabase(unittest.TestCase):
    @patch("builtins.input")
    def test_restore_by_filename(self, mock_input):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, [])
        # status="1" (by filename), db name default, no neutralize
        mock_input.side_effect = ["1", "", "n", "n"]
        todo.restore_from_database()
        cmd = todo.execute.exec_command_live.call_args_list[0][0][0]
        self.assertIn("db_restore.py", cmd)

    @patch("builtins.input")
    def test_restore_with_neutralize(self, mock_input):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (0, [])
        mock_input.side_effect = ["1", "mydb", "y", "n"]
        todo.restore_from_database()
        cmd = todo.execute.exec_command_live.call_args_list[0][0][0]
        self.assertIn("--neutralize", cmd)
        self.assertIn("mydb_neutralize", cmd)


class TestCreateBackupFromDatabase(unittest.TestCase):
    @patch("script.todo.todo.click")
    @patch("builtins.input")
    def test_creates_backup_command(self, mock_input, mock_click):
        todo = TODO()
        todo.execute = MagicMock()
        todo.execute.exec_command_live.return_value = (
            0,
            ["test_db"],
        )
        mock_click.prompt.return_value = "1"
        # backup name input
        mock_input.return_value = "backup.zip"
        todo.create_backup_from_database()
        cmd = todo.execute.exec_command_live.call_args_list[-1][0][0]
        self.assertIn("--backup", cmd)
        self.assertIn("test_db", cmd)


if __name__ == "__main__":
    unittest.main()
