#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from collections import OrderedDict
from unittest.mock import MagicMock, mock_open, patch

from script.git.git_tool import (
    CST_EL_GITHUB_TOKEN,
    CST_FILE_SOURCE_REPO_ADDONS,
    DEFAULT_PROJECT_NAME,
    DEFAULT_REMOTE_URL,
    DEFAULT_WEBSITE,
    GitTool,
    Struct,
)


class TestStruct(unittest.TestCase):
    def test_basic_attributes(self):
        s = Struct(a=1, b="hello")
        self.assertEqual(s.a, 1)
        self.assertEqual(s.b, "hello")

    def test_empty_struct(self):
        s = Struct()
        self.assertEqual(s.__dict__, {})

    def test_override_existing(self):
        s = Struct(x=10)
        self.assertEqual(s.x, 10)


class TestGetUrl(unittest.TestCase):
    def test_https_to_git(self):
        url, url_https, url_git = GitTool.get_url(
            "https://github.com/OCA/server-tools.git"
        )
        self.assertEqual(url, "https://github.com/OCA/server-tools.git")
        self.assertEqual(url_https, "https://github.com/OCA/server-tools.git")
        self.assertEqual(url_git, "git@github.com:OCA/server-tools.git")

    def test_git_to_https(self):
        url, url_https, url_git = GitTool.get_url(
            "git@github.com:OCA/server-tools.git"
        )
        self.assertEqual(url_https, "https://github.com/OCA/server-tools.git")
        self.assertEqual(url_git, "git@github.com:OCA/server-tools.git")

    def test_https_without_git_suffix(self):
        url, url_https, url_git = GitTool.get_url(
            "https://github.com/ERPLibre/ERPLibre"
        )
        self.assertEqual(url_https, "https://github.com/ERPLibre/ERPLibre")
        self.assertEqual(url_git, "git@github.com:ERPLibre/ERPLibre")


class TestGetTransformedRepoInfo(unittest.TestCase):
    def setUp(self):
        self.gt = GitTool()

    def test_https_url_as_submodule(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            repo_path=".",
            get_obj=False,
        )
        self.assertEqual(result["organization"], "OCA")
        self.assertEqual(result["repo_name"], "server-tools")
        self.assertEqual(result["project_name"], "server-tools.git")
        self.assertEqual(result["path"], "addons/OCA_server-tools")
        self.assertTrue(result["is_submodule"])

    def test_git_url_as_submodule(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "git@github.com:ERPLibre/erplibre_addons.git",
            repo_path=".",
            get_obj=False,
        )
        self.assertEqual(result["organization"], "ERPLibre")
        self.assertEqual(result["repo_name"], "erplibre_addons")

    def test_not_submodule(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            repo_path="/tmp/test",
            get_obj=False,
            is_submodule=False,
        )
        self.assertEqual(result["path"], "/tmp/test")
        self.assertFalse(result["is_submodule"])

    def test_get_obj_true_returns_struct(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/web.git",
            get_obj=True,
        )
        self.assertIsInstance(result, Struct)
        self.assertEqual(result.organization, "OCA")

    def test_organization_force(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            get_obj=False,
            organization_force="MyOrg",
        )
        self.assertEqual(result["organization"], "MyOrg")
        self.assertEqual(result["original_organization"], "OCA")
        self.assertIn("MyOrg", result["url_https"])

    def test_custom_sub_path(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            get_obj=False,
            sub_path="custom",
        )
        self.assertEqual(result["path"], "custom/OCA_server-tools")

    def test_empty_sub_path(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            get_obj=False,
            sub_path="",
        )
        self.assertEqual(result["path"], "server-tools")

    def test_dot_sub_path(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools.git",
            get_obj=False,
            sub_path=".",
        )
        self.assertEqual(result["path"], "server-tools")

    def test_revision_and_clone_depth(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/web.git",
            get_obj=False,
            revision="16.0",
            clone_depth="1",
        )
        self.assertEqual(result["revision"], "16.0")
        self.assertEqual(result["clone_depth"], "1")

    def test_url_without_git_suffix(self):
        result = self.gt.get_transformed_repo_info_from_url(
            "https://github.com/OCA/server-tools",
            get_obj=False,
        )
        self.assertEqual(result["repo_name"], "server-tools")


class TestDefaultProperties(unittest.TestCase):
    def test_default_project_name(self):
        gt = GitTool()
        self.assertEqual(gt.default_project_name, DEFAULT_PROJECT_NAME)

    def test_default_website(self):
        gt = GitTool()
        self.assertEqual(gt.default_website, DEFAULT_WEBSITE)

    def test_default_remote_url(self):
        gt = GitTool()
        self.assertEqual(gt.default_remote_url, DEFAULT_REMOTE_URL)

    @patch(
        "builtins.open",
        mock_open(read_data="18.0"),
    )
    def test_odoo_version(self):
        gt = GitTool()
        self.assertEqual(gt.odoo_version, "18.0")

    @patch(
        "builtins.open",
        mock_open(read_data="16.0"),
    )
    def test_odoo_version_long(self):
        gt = GitTool()
        self.assertEqual(gt.odoo_version_long, "odoo16.0")


class TestStrInsert(unittest.TestCase):
    def test_insert_middle(self):
        result = GitTool.str_insert("abcdef", "XY", 3)
        self.assertEqual(result, "abcXYdef")

    def test_insert_beginning(self):
        result = GitTool.str_insert("hello", "X", 0)
        self.assertEqual(result, "Xhello")

    def test_insert_end(self):
        result = GitTool.str_insert("hello", "X", 5)
        self.assertEqual(result, "helloX")


class TestGetProjectConfig(unittest.TestCase):
    def test_reads_github_token(self):
        content = (
            "#!/bin/bash\n"
            'EL_GITHUB_TOKEN="my_token_123"\n'
            'OTHER_VAR="value"\n'
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir="/tmp"
        ) as f:
            f.write(content)
            f.flush()
            tmpdir = os.path.dirname(f.name)
            tmpname = os.path.basename(f.name)
            try:
                # We need env_var.sh in a directory
                env_var_path = os.path.join(tmpdir, "env_var.sh")
                os.rename(f.name, env_var_path)
                result = GitTool.get_project_config(repo_path=tmpdir)
                self.assertEqual(result[CST_EL_GITHUB_TOKEN], "my_token_123")
            finally:
                if os.path.exists(env_var_path):
                    os.unlink(env_var_path)


class TestGetRepoInfoSubmodule(unittest.TestCase):
    def test_parses_gitmodules(self):
        gitmodules_content = (
            '[submodule "addons/OCA_server-tools"]\n'
            "\turl = https://github.com/OCA/server-tools.git\n"
            "\tpath = addons/OCA_server-tools\n"
            "\n"
            '[submodule "addons/OCA_web"]\n'
            "\turl = https://github.com/OCA/web.git\n"
            "\tpath = addons/OCA_web\n"
        )
        gt = GitTool()
        with tempfile.TemporaryDirectory() as tmpdir:
            gitmodules_path = os.path.join(tmpdir, ".gitmodules")
            with open(gitmodules_path, "w") as f:
                f.write(gitmodules_content)

            result = gt.get_repo_info_submodule(
                repo_path=tmpdir, add_root=False
            )
            self.assertEqual(len(result), 2)
            names = [r["name"] for r in result]
            self.assertIn("addons/OCA_server-tools", names)
            self.assertIn("addons/OCA_web", names)

    def test_single_submodule(self):
        gitmodules_content = (
            '[submodule "addons/test"]\n'
            "\turl = https://github.com/Test/repo.git\n"
            "\tpath = addons/test\n"
        )
        gt = GitTool()
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, ".gitmodules"), "w") as f:
                f.write(gitmodules_content)

            result = gt.get_repo_info_submodule(repo_path=tmpdir)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "addons/test")
            self.assertIn("https://", result[0]["url_https"])
            self.assertIn("git@", result[0]["url_git"])


class TestGetManifestXmlInfo(unittest.TestCase):
    def test_parses_manifest(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="OCA" fetch="https://github.com/OCA/"/>
  <default remote="OCA" revision="16.0"/>
  <project name="server-tools.git" path="addons/OCA_server-tools"
           remote="OCA" groups="odoo16.0"/>
</manifest>
"""
        gt = GitTool()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            f.flush()
            try:
                dct_remote, dct_project, default_remote = (
                    gt.get_manifest_xml_info(filename=f.name)
                )
                self.assertIn("OCA", dct_remote)
                self.assertIn("server-tools.git", dct_project)
                self.assertEqual(default_remote["@remote"], "OCA")
            finally:
                os.unlink(f.name)

    def test_empty_manifest(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<manifest/>
"""
        gt = GitTool()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            f.flush()
            try:
                dct_remote, dct_project, default_remote = (
                    gt.get_manifest_xml_info(filename=f.name)
                )
                self.assertEqual(dct_remote, {})
                self.assertEqual(dct_project, {})
                self.assertIsNone(default_remote)
            finally:
                os.unlink(f.name)


class TestConstants(unittest.TestCase):
    def test_file_source_repo_addons(self):
        self.assertEqual(CST_FILE_SOURCE_REPO_ADDONS, "source_repo_addons.csv")

    def test_default_project_name(self):
        self.assertEqual(DEFAULT_PROJECT_NAME, "ERPLibre")

    def test_default_website(self):
        self.assertEqual(DEFAULT_WEBSITE, "erplibre.ca")


if __name__ == "__main__":
    unittest.main()
