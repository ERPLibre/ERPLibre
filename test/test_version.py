#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from script.version.update_env_version import (
    Update,
    remove_dot_path,
    die,
    ERPLIBRE_TEMPLATE_VERSION,
    VENV_TEMPLATE_FILE,
    MANIFEST_TEMPLATE_FILE,
    PYPROJECT_TEMPLATE_FILE,
    POETRY_LOCK_TEMPLATE_FILE,
    ADDONS_TEMPLATE_FILE,
    ODOO_TEMPLATE_FILE,
)


class TestRemoveDotPath(unittest.TestCase):
    def test_removes_dot_slash(self):
        self.assertEqual(remove_dot_path("./path/to/file"), "path/to/file")

    def test_no_dot_slash(self):
        self.assertEqual(remove_dot_path("path/to/file"), "path/to/file")

    def test_just_dot_slash(self):
        self.assertEqual(remove_dot_path("./"), "")

    def test_nested_dot_slash(self):
        self.assertEqual(
            remove_dot_path("./a/./b"), "a/./b"
        )

    def test_empty_string(self):
        self.assertEqual(remove_dot_path(""), "")

    def test_single_file(self):
        self.assertEqual(remove_dot_path("file.txt"), "file.txt")


class TestDie(unittest.TestCase):
    def test_die_true_exits(self):
        with self.assertRaises(SystemExit) as cm:
            die(True, "error message")
        self.assertEqual(cm.exception.code, 1)

    def test_die_false_no_exit(self):
        die(False, "no error")

    def test_die_custom_code(self):
        with self.assertRaises(SystemExit) as cm:
            die(True, "error", code=42)
        self.assertEqual(cm.exception.code, 42)


class TestConstants(unittest.TestCase):
    def test_erplibre_template_version(self):
        result = ERPLIBRE_TEMPLATE_VERSION % ("18.0", "3.12.10")
        self.assertEqual(result, "odoo18.0_python3.12.10")

    def test_venv_template(self):
        result = VENV_TEMPLATE_FILE % "odoo18.0_python3.12.10"
        self.assertEqual(result, ".venv.odoo18.0_python3.12.10")

    def test_manifest_template(self):
        result = MANIFEST_TEMPLATE_FILE % "18.0"
        self.assertEqual(result, "default.dev.odoo18.0.xml")

    def test_pyproject_template(self):
        result = PYPROJECT_TEMPLATE_FILE % "odoo18.0_python3.12.10"
        self.assertEqual(
            result, "pyproject.odoo18.0_python3.12.10.toml"
        )

    def test_poetry_lock_template(self):
        result = POETRY_LOCK_TEMPLATE_FILE % "odoo18.0_python3.12.10"
        self.assertEqual(
            result, "poetry.odoo18.0_python3.12.10.lock"
        )

    def test_addons_template(self):
        result = ADDONS_TEMPLATE_FILE % "18.0"
        self.assertEqual(result, "odoo18.0/addons")

    def test_odoo_template(self):
        result = ODOO_TEMPLATE_FILE % "18.0"
        self.assertEqual(result, "odoo18.0")


class TestUpdateValidateVersion(unittest.TestCase):
    """Test validate_version() sets expected paths based on version data."""

    def _make_update(self, data_version, config_args=None):
        with patch("sys.argv", ["prog"]):
            update = Update()
        update.data_version = data_version
        if config_args:
            for k, v in config_args.items():
                setattr(update.config, k, v)
        return update

    def test_explicit_erplibre_version(self):
        data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "poetry_version": "2.1.3",
                "default": True,
            }
        }
        update = self._make_update(
            data,
            {"erplibre_version": "odoo18.0_python3.12.10"},
        )
        update.validate_version()
        self.assertEqual(update.new_version_odoo, "18.0")
        self.assertEqual(update.new_version_python, "3.12.10")
        self.assertEqual(update.new_version_poetry, "2.1.3")
        self.assertEqual(
            update.new_version_erplibre, "odoo18.0_python3.12.10"
        )

    def test_explicit_odoo_version(self):
        data = {}
        update = self._make_update(data, {"odoo_version": "17.0"})
        update.new_version_python = "3.10.18"
        update.config.python_version = "3.10.18"
        update.validate_version()
        self.assertEqual(update.new_version_odoo, "17.0")

    def test_default_version_fallback(self):
        data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "poetry_version": "2.1.3",
                "default": True,
            }
        }
        update = self._make_update(data)
        update.detected_version_erplibre = None
        update.validate_version()
        self.assertEqual(update.new_version_odoo, "18.0")

    def test_detected_version_used(self):
        data = {
            "odoo17.0_python3.10.18": {
                "odoo_version": "17.0",
                "python_version": "3.10.18",
                "poetry_version": "1.8.3",
            }
        }
        update = self._make_update(data)
        update.detected_version_erplibre = "odoo17.0_python3.10.18"
        update.validate_version()
        self.assertEqual(update.new_version_odoo, "17.0")
        self.assertEqual(update.new_version_python, "3.10.18")

    def test_expected_paths_set(self):
        data = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
                "poetry_version": "2.1.3",
                "default": True,
            }
        }
        update = self._make_update(
            data,
            {"erplibre_version": "odoo18.0_python3.12.10"},
        )
        update.validate_version()
        self.assertIn("default.dev.odoo18.0.xml", update.expected_manifest_name)
        self.assertIn("requirement", update.expected_pyproject_path)
        self.assertIn("requirement", update.expected_poetry_lock_path)
        self.assertEqual(update.expected_odoo_name, "odoo18.0")


class TestUpdateDetectVersion(unittest.TestCase):
    def test_detect_version_no_files(self):
        with patch("sys.argv", ["prog"]):
            update = Update()
        with patch("os.path.exists", return_value=False):
            result = update.detect_version()
        self.assertFalse(result)

    def test_detect_version_matching(self):
        with patch("sys.argv", ["prog"]):
            update = Update()
        update.data_version = {
            "odoo18.0_python3.12.10": {
                "odoo_version": "18.0",
                "python_version": "3.12.10",
            }
        }
        tmpdir = tempfile.mkdtemp()
        py_file = os.path.join(tmpdir, "python_ver")
        odoo_file = os.path.join(tmpdir, "odoo_ver")
        poetry_file = os.path.join(tmpdir, "poetry_ver")
        with open(py_file, "w") as f:
            f.write("3.12.10")
        with open(odoo_file, "w") as f:
            f.write("18.0")
        with open(poetry_file, "w") as f:
            f.write("2.1.3")
        with patch(
            "script.version.update_env_version.VERSION_PYTHON_FILE",
            py_file,
        ), patch(
            "script.version.update_env_version.VERSION_ODOO_FILE",
            odoo_file,
        ), patch(
            "script.version.update_env_version.VERSION_POETRY_FILE",
            poetry_file,
        ), patch(
            "script.version.update_env_version.INSTALLED_ODOO_VERSION_FILE",
            os.path.join(tmpdir, "nonexist"),
        ):
            result = update.detect_version()
        self.assertTrue(result)
        self.assertEqual(
            update.detected_version_erplibre, "odoo18.0_python3.12.10"
        )


class TestUpdatePrintLog(unittest.TestCase):
    def test_empty_log(self):
        with patch("sys.argv", ["prog"]):
            update = Update()
        update.print_log()

    def test_with_entries(self):
        with patch("sys.argv", ["prog"]):
            update = Update()
        update.execute_log = ["entry1", "entry2"]
        update.print_log()
