#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import configparser
import os
import tempfile
import unittest
from unittest.mock import patch

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

    def _run(self, content):
        with open("config.conf", "w") as f:
            f.write(content)
        with patch("sys.argv", ["setup_odoo_config_conf_devops.py"]):
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


if __name__ == "__main__":
    unittest.main()
