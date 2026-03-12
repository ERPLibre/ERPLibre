#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from script.config.config_file import ConfigFile


class TestDeepMergeWithLists(unittest.TestCase):
    def setUp(self):
        self.cfg = ConfigFile()

    def test_empty_dicts(self):
        result = self.cfg.deep_merge_with_lists({}, {})
        self.assertEqual(result, {})

    def test_dest_only(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": 1, "b": 2}, {}
        )
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_src_only(self):
        result = self.cfg.deep_merge_with_lists(
            {}, {"a": 1, "b": 2}
        )
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_simple_merge(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": 1}, {"b": 2}
        )
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_src_overrides_dest_string(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": "old"}, {"a": "new"}
        )
        self.assertEqual(result, {"a": "new"})

    def test_empty_src_string_keeps_dest(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": "old"}, {"a": ""}
        )
        self.assertEqual(result, {"a": "old"})

    def test_nested_dict_merge(self):
        dest = {"a": {"x": 1, "y": 2}}
        src = {"a": {"y": 3, "z": 4}}
        result = self.cfg.deep_merge_with_lists(dest, src)
        self.assertEqual(result, {"a": {"x": 1, "y": 3, "z": 4}})

    def test_deeply_nested_dict_merge(self):
        dest = {"a": {"b": {"c": 1}}}
        src = {"a": {"b": {"d": 2}}}
        result = self.cfg.deep_merge_with_lists(dest, src)
        self.assertEqual(result, {"a": {"b": {"c": 1, "d": 2}}})

    def test_list_replace_strategy(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": [1, 2]}, {"a": [3, 4]}, list_strategy="replace"
        )
        self.assertEqual(result, {"a": [3, 4]})

    def test_list_extend_strategy(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": [1, 2]}, {"a": [3, 4]}, list_strategy="extend"
        )
        self.assertEqual(result, {"a": [1, 2, 3, 4]})

    def test_dest_dict_not_mutated(self):
        dest = {"a": {"x": 1}}
        src = {"a": {"y": 2}}
        self.cfg.deep_merge_with_lists(dest, src)
        self.assertEqual(dest, {"a": {"x": 1}})

    def test_src_overrides_non_string_non_dict_non_list(self):
        result = self.cfg.deep_merge_with_lists(
            {"a": 1}, {"a": 2}
        )
        self.assertEqual(result, {"a": 2})


class TestGetConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = ConfigFile()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.tmpdir):
            os.remove(os.path.join(self.tmpdir, f))
        os.rmdir(self.tmpdir)

    def _write_json(self, filename, data):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_get_config_base_only(self):
        base_path = self._write_json(
            "base.json", {"instance": [{"name": "test"}]}
        )
        with patch(
            "script.config.config_file.CONFIG_FILE", base_path
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            os.path.join(self.tmpdir, "nonexistent1.json"),
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            os.path.join(self.tmpdir, "nonexistent2.json"),
        ):
            result = self.cfg.get_config("instance")
        self.assertEqual(result, [{"name": "test"}])

    def test_get_config_returns_none_for_missing_key(self):
        base_path = self._write_json("base.json", {"a": 1})
        with patch(
            "script.config.config_file.CONFIG_FILE", base_path
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            os.path.join(self.tmpdir, "nonexistent1.json"),
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            os.path.join(self.tmpdir, "nonexistent2.json"),
        ):
            result = self.cfg.get_config("missing")
        self.assertIsNone(result)

    def test_get_config_override_merges(self):
        base_path = self._write_json(
            "base.json",
            {"instance": [{"name": "base"}]},
        )
        override_path = self._write_json(
            "override.json",
            {"instance": [{"name": "override"}]},
        )
        with patch(
            "script.config.config_file.CONFIG_FILE", base_path
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            override_path,
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            os.path.join(self.tmpdir, "nonexistent.json"),
        ):
            result = self.cfg.get_config("instance")
        # Lists with extend: base + override
        self.assertEqual(
            result,
            [{"name": "base"}, {"name": "override"}],
        )

    def test_get_config_private_merges(self):
        base_path = self._write_json(
            "base.json",
            {"data": {"key": "base_val"}},
        )
        private_path = self._write_json(
            "private.json",
            {"data": {"key": "private_val"}},
        )
        with patch(
            "script.config.config_file.CONFIG_FILE", base_path
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            os.path.join(self.tmpdir, "nonexistent.json"),
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            private_path,
        ):
            result = self.cfg.get_config("data")
        self.assertEqual(result, {"key": "private_val"})

    def test_get_config_all_three_files(self):
        base_path = self._write_json(
            "base.json",
            {"items": [1], "meta": {"a": "base"}},
        )
        override_path = self._write_json(
            "override.json",
            {"items": [2], "meta": {"b": "override"}},
        )
        private_path = self._write_json(
            "private.json",
            {"items": [3], "meta": {"a": "private"}},
        )
        with patch(
            "script.config.config_file.CONFIG_FILE", base_path
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            override_path,
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            private_path,
        ):
            result_items = self.cfg.get_config("items")
            result_meta = self.cfg.get_config("meta")
        # Merge order: base + private, then + override
        # Lists extend: [1] + [3] = [1,3], then [1,3] + [2] = [1,3,2]
        self.assertEqual(result_items, [1, 3, 2])
        # Dict merge: {a: base} + {a: private} = {a: private}
        # then {a: private} + {b: override} = {a: private, b: override}
        self.assertEqual(
            result_meta, {"a": "private", "b": "override"}
        )

    def test_no_config_files_exist(self):
        with patch(
            "script.config.config_file.CONFIG_FILE",
            os.path.join(self.tmpdir, "nope1.json"),
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_FILE",
            os.path.join(self.tmpdir, "nope2.json"),
        ), patch(
            "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
            os.path.join(self.tmpdir, "nope3.json"),
        ):
            result = self.cfg.get_config("anything")
        self.assertIsNone(result)


class TestGetConfigValue(unittest.TestCase):
    def setUp(self):
        self.cfg = ConfigFile()

    def test_nested_value(self):
        with patch.object(
            self.cfg,
            "get_config",
            return_value={"level1": {"level2": "found"}},
        ):
            result = self.cfg.get_config_value(
                ["root", "level1", "level2"]
            )
        self.assertEqual(result, "found")

    def test_single_key(self):
        with patch.object(
            self.cfg,
            "get_config",
            return_value={"key": "value"},
        ):
            result = self.cfg.get_config_value(["root"])
        self.assertEqual(result, {"key": "value"})


class TestGetLogoAsciiFilePath(unittest.TestCase):
    def test_returns_logo_path(self):
        cfg = ConfigFile()
        result = cfg.get_logo_ascii_file_path()
        self.assertEqual(result, "./script/todo/logo_ascii.txt")


if __name__ == "__main__":
    unittest.main()
