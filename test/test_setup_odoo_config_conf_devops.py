#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import configparser
import glob
import os
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from script.config import setup_odoo_config_conf_devops


class TestSetupOdooConfigConfDevops(unittest.TestCase):
    """main() rewrites ./config.conf: each test runs it inside a temporary
    directory holding its own config.conf, never the checkout's one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(self._restore)

    def _restore(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _run(self, content, *args):
        with open("config.conf", "w") as f:
            f.write(content)
        argv = ["setup_odoo_config_conf_devops.py", *args]
        with patch("sys.argv", argv):
            setup_odoo_config_conf_devops.main()
        parser = configparser.ConfigParser()
        parser.read("config.conf")
        return parser

    def test_existing_channels_are_kept(self):
        parser = self._run(
            "[options]\nworkers = 0\n"
            "server_wide_modules = base,web,queue_job\n\n"
            "[queue_job]\nchannels = root:2,root.mail:1\n"
        )
        self.assertEqual(
            parser.get("queue_job", "channels"), "root:2,root.mail:1"
        )

    def test_section_without_channels_gets_default(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n[queue_job]\njobrunner_db_port = 5432\n"
        )
        self.assertEqual(
            parser.get("queue_job", "channels"), f"root:{os.cpu_count()}"
        )
        self.assertEqual(parser.get("queue_job", "jobrunner_db_port"), "5432")

    def test_missing_section_is_created(self):
        parser = self._run("[options]\nworkers = 4\n")
        self.assertEqual(
            parser.get("queue_job", "channels"), f"root:{os.cpu_count()}"
        )
        self.assertEqual(parser.get("options", "workers"), "0")
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "base,web,queue_job",
        )

    def test_queue_job_appended_to_server_wide_modules(self):
        parser = self._run(
            "[options]\nserver_wide_modules = base,web\n\n"
            "[queue_job]\nchannels = root:1\n"
        )
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "base,web,queue_job",
        )
        self.assertEqual(parser.get("queue_job", "channels"), "root:1")

    def test_channel_added_to_existing(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n[queue_job]\nchannels = root:2\n",
            "--channel",
            "root.ms_graph:1",
        )
        self.assertEqual(
            parser.get("queue_job", "channels"), "root:2,root.ms_graph:1"
        )

    def test_channel_added_to_default(self):
        parser = self._run(
            "[options]\nworkers = 0\n", "--channel", "root.ms_graph:1"
        )
        self.assertEqual(
            parser.get("queue_job", "channels"),
            f"root:{os.cpu_count()},root.ms_graph:1",
        )

    def test_declared_channel_keeps_its_capacity(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n"
            "[queue_job]\nchannels = root:2,root.ms_graph:3\n",
            "--channel",
            "root.ms_graph:1",
            "--channel",
            "root.mail:1",
        )
        self.assertEqual(
            parser.get("queue_job", "channels"),
            "root:2,root.ms_graph:3,root.mail:1",
        )

    def test_short_name_is_same_channel(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n"
            "[queue_job]\nchannels = root:2,ms_graph:1:sequential\n",
            "--channel",
            "root.ms_graph:3",
        )
        self.assertEqual(
            parser.get("queue_job", "channels"),
            "root:2,ms_graph:1:sequential",
        )

    def test_spaces_around_name_are_ignored(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n"
            "[queue_job]\nchannels = root:2, root.ms_graph : 3\n",
            "--channel",
            "root.ms_graph:1",
        )
        self.assertEqual(
            parser.get("queue_job", "channels"), "root:2, root.ms_graph : 3"
        )

    def test_one_channel_per_line(self):
        parser = self._run(
            "[options]\nworkers = 0\n\n"
            "[queue_job]\nchannels =\n    root:2\n    root.ms_graph:3\n",
            "--channel",
            "root.ms_graph:1",
            "--channel",
            "root.mail:1",
        )
        self.assertEqual(
            parser.get("queue_job", "channels").split(),
            ["root:2", "root.ms_graph:3", "root.mail:1"],
        )

    def _set_version(self, version):
        with open(".odoo-version", "w") as f:
            f.write(version)

    def test_odoo19_keeps_rpc_server_wide(self):
        self._set_version("19.0")
        parser = self._run("[options]\nworkers = 4\n")
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "base,rpc,web,queue_job",
        )

    def test_odoo11_default_server_wide(self):
        self._set_version("11.0")
        parser = self._run("[options]\nworkers = 0\n")
        self.assertEqual(
            parser.get("options", "server_wide_modules"), "web,queue_job"
        )

    def test_odoo10_keeps_web_kanban(self):
        self._set_version("10.0")
        parser = self._run("[options]\nworkers = 0\n")
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "web,web_kanban,queue_job",
        )
        self.assertEqual(
            parser.get("queue_job", "channels"), f"root:{os.cpu_count()}"
        )

    def test_odoo8_uses_connector(self):
        self._set_version("8.0")
        parser = self._run("[options]\nworkers = 0\n", "--channel", "root.x:1")
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "web,web_kanban,connector",
        )
        self.assertEqual(
            parser.get("options-connector", "channels"),
            f"root:{os.cpu_count()},root.x:1",
        )
        self.assertFalse(parser.has_section("queue_job"))

    def test_odoo9_connector_appended_to_server_wide_modules(self):
        self._set_version("9.0")
        parser = self._run(
            "[options]\nserver_wide_modules = web,web_kanban\n\n"
            "[options-connector]\nchannels = root:2\n"
        )
        self.assertEqual(
            parser.get("options", "server_wide_modules"),
            "web,web_kanban,connector",
        )
        self.assertEqual(parser.get("options-connector", "channels"), "root:2")
        self.assertFalse(parser.has_section("queue_job"))

    def test_manifest_carries_job_runner(self):
        """Each Odoo manifest clones the repository of the module the
        script adds to server_wide_modules for that version, else Odoo
        fails to load it at every start."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifests = glob.glob(
            os.path.join(root, "manifest", "git_manifest_odoo*.xml")
        )
        manifests = [m for m in manifests if not m.endswith("_dev.xml")]
        self.assertTrue(manifests)
        for manifest in manifests:
            version = os.path.basename(manifest)[len("git_manifest_odoo") : -4]
            major = int(version.split(".")[0])
            module = setup_odoo_config_conf_devops.job_runner(major)[0]
            repo = "OCA_connector" if module == "connector" else "OCA_queue"
            paths = {
                project.get("path")
                for project in ElementTree.parse(manifest).iter("project")
            }
            with self.subTest(version=version):
                self.assertIn(f"odoo{version}/addons/{repo}", paths)

    def test_invalid_channel_refused(self):
        with self.assertRaises(SystemExit):
            self._run("[options]\nworkers = 0\n", "--channel", "root.ms_graph")
        with open("config.conf") as f:
            self.assertNotIn("queue_job", f.read())


if __name__ == "__main__":
    unittest.main()
