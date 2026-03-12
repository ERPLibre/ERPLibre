#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import unittest
from unittest.mock import patch, MagicMock

from script.maintenance.format_file_to_commit import (
    execute_shell,
    get_modified_files,
)

MOD = "script.maintenance.format_file_to_commit"


class TestExecuteShell(unittest.TestCase):
    def test_successful_command(self):
        code, output = execute_shell("echo hello")
        self.assertEqual(code, 0)
        self.assertEqual(output, "hello")

    def test_failed_command(self):
        code, output = execute_shell("exit 42")
        self.assertEqual(code, 42)

    def test_stderr_captured(self):
        code, output = execute_shell("echo err >&2")
        self.assertEqual(code, 0)
        self.assertIn("err", output)

    def test_empty_output(self):
        code, output = execute_shell("true")
        self.assertEqual(code, 0)
        self.assertEqual(output, "")

    def test_multiline_output(self):
        code, output = execute_shell("echo 'a\nb'")
        self.assertEqual(code, 0)
        self.assertIn("a", output)
        self.assertIn("b", output)


class TestGetModifiedFiles(unittest.TestCase):
    def _mock_git(self, git_output):
        """Helper to mock subprocess.run for git status."""
        mock_result = MagicMock()
        mock_result.stdout = git_output
        mock_result.returncode = 0
        return mock_result

    def _no_repo_no_odoo(self, path):
        """Return False for repo bin and .odoo-version, True otherwise."""
        if path in (".venv.erplibre/bin/repo",):
            return False
        return True

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists")
    @patch(f"{MOD}.subprocess.run")
    def test_single_modified_file(self, mock_run, mock_exists, mock_isfile):
        mock_exists.return_value = False
        mock_run.return_value = self._mock_git(" M file.py")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], "M")

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_added_file(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("A  new_file.py")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(files[0][0], "A")

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_deleted_file_ignored(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("D  deleted.py")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 0)

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_zip_file_ignored(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("M  archive.zip")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 0)

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_tar_gz_file_ignored(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("M  archive.tar.gz")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 0)

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_untracked_file(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("?? new_file.txt")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], "??")

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_empty_git_status(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git("")
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 0)

    @patch(f"{MOD}.os.path.isfile", return_value=False)
    @patch(f"{MOD}.os.path.exists", return_value=False)
    @patch(f"{MOD}.subprocess.run")
    def test_multiple_statuses(self, mock_run, mock_exists, mock_isfile):
        mock_run.return_value = self._mock_git(
            " M modified.py\nA  added.py\n?? untracked.py"
        )
        files = get_modified_files()
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 3)

    @patch(f"{MOD}.subprocess.run")
    def test_git_error_returns_none(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        files = get_modified_files()
        self.assertIsNone(files)
