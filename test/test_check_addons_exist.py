#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from script.addons.check_addons_exist import main


class TestMainModuleFound(unittest.TestCase):
    """Test main() when modules exist with valid __manifest__.py."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create a valid addon
        addon_path = os.path.join(self.tmpdir, "my_addon")
        os.makedirs(addon_path)
        with open(os.path.join(addon_path, "__manifest__.py"), "w") as f:
            f.write("{}")
        # Create config.conf
        self.config_path = os.path.join(self.tmpdir, "config.conf")
        with open(self.config_path, "w") as f:
            f.write(f"[options]\naddons_path = {self.tmpdir}\n")

    def test_single_module_found(self):
        with patch(
            "sys.argv",
            ["prog", "-m", "my_addon", "-c", self.config_path],
        ):
            result = main()
        self.assertEqual(result, 0)

    def test_output_json_module_found(self):
        with patch(
            "sys.argv",
            [
                "prog",
                "-m",
                "my_addon",
                "-c",
                self.config_path,
                "--output_json",
            ],
        ):
            result = main()
        self.assertEqual(result, 0)

    def test_format_json_output(self):
        with patch(
            "sys.argv",
            [
                "prog",
                "-m",
                "my_addon",
                "-c",
                self.config_path,
                "--output_json",
                "--format_json",
            ],
        ):
            result = main()
        self.assertEqual(result, 0)


class TestMainModuleMissing(unittest.TestCase):
    """Test main() when modules do not exist."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmpdir, "config.conf")
        with open(self.config_path, "w") as f:
            f.write(f"[options]\naddons_path = {self.tmpdir}\n")

    def test_missing_module_returns_1(self):
        with patch(
            "sys.argv",
            ["prog", "-m", "nonexistent", "-c", self.config_path],
        ):
            result = main()
        self.assertEqual(result, 1)

    def test_missing_module_json(self):
        with patch(
            "sys.argv",
            [
                "prog",
                "-m",
                "nonexistent",
                "-c",
                self.config_path,
                "--output_json",
            ],
        ):
            result = main()
        self.assertEqual(result, 1)


class TestMainDuplicateModule(unittest.TestCase):
    """Test main() when same module exists in multiple addon paths."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        path1 = os.path.join(self.tmpdir, "addons1", "dup_mod")
        path2 = os.path.join(self.tmpdir, "addons2", "dup_mod")
        os.makedirs(path1)
        os.makedirs(path2)
        with open(os.path.join(path1, "__manifest__.py"), "w") as f:
            f.write("{}")
        with open(os.path.join(path2, "__manifest__.py"), "w") as f:
            f.write("{}")
        addons = (
            os.path.join(self.tmpdir, "addons1")
            + ","
            + os.path.join(self.tmpdir, "addons2")
        )
        self.config_path = os.path.join(self.tmpdir, "config.conf")
        with open(self.config_path, "w") as f:
            f.write(f"[options]\naddons_path = {addons}\n")

    def test_duplicate_returns_2(self):
        with patch(
            "sys.argv",
            ["prog", "-m", "dup_mod", "-c", self.config_path],
        ):
            result = main()
        self.assertEqual(result, 2)


class TestMainMissingManifest(unittest.TestCase):
    """Test main() when directory exists but __manifest__.py is absent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        addon_path = os.path.join(self.tmpdir, "empty_addon")
        os.makedirs(addon_path)
        self.config_path = os.path.join(self.tmpdir, "config.conf")
        with open(self.config_path, "w") as f:
            f.write(f"[options]\naddons_path = {self.tmpdir}\n")

    def test_dir_without_manifest_returns_1(self):
        with patch(
            "sys.argv",
            ["prog", "-m", "empty_addon", "-c", self.config_path],
        ):
            result = main()
        self.assertEqual(result, 1)


class TestMainBadConfig(unittest.TestCase):
    """Test main() with invalid config files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_missing_options_section(self):
        config_path = os.path.join(self.tmpdir, "config.conf")
        with open(config_path, "w") as f:
            f.write("[other]\nkey = value\n")
        with patch(
            "sys.argv",
            ["prog", "-m", "mod", "-c", config_path],
        ):
            result = main()
        self.assertEqual(result, -1)

    def test_missing_addons_path_key(self):
        config_path = os.path.join(self.tmpdir, "config.conf")
        with open(config_path, "w") as f:
            f.write("[options]\nother_key = value\n")
        with patch(
            "sys.argv",
            ["prog", "-m", "mod", "-c", config_path],
        ):
            result = main()
        self.assertEqual(result, -1)
