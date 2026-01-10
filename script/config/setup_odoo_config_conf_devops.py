#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import getpass
import logging
import os
import sys
from subprocess import check_output

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
DESCRIPTION
    Force config.conf file to has workers 0 and support queue

SUGGESTION
    ./script/config/setup_odoo_config_conf_devops.py
""",
        epilog="""\
""",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()

    # check if it needs master password from config file
    has_config_file = True
    config_path = "./config.conf"
    if not os.path.isfile(config_path):
        config_path = "/etc/odoo/odoo.conf"
        if not os.path.isfile(config_path):
            has_config_file = False
    if has_config_file:
        config_parser = configparser.ConfigParser()
        config_parser.read(config_path)

        # Force workers to zero for local running
        if config_parser.has_option("options", "workers"):
            workers = config_parser.get("options", "workers")
            if workers != "0":
                config_parser.set("options", "workers", "0")
        else:
            config_parser.set("options", "workers", "0")

        # Load queue_job
        if config_parser.has_option("options", "server_wide_modules"):
            server_wide_modules = config_parser.get(
                "options", "server_wide_modules"
            )
            if "queue_job" not in server_wide_modules:
                config_parser.set(
                    "options",
                    "server_wide_modules",
                    server_wide_modules + ",queue_job",
                )
        else:
            config_parser.set(
                "options", "server_wide_modules", "base,web,queue_job"
            )

        # Support queue_job size channels
        queue_job_channels = ""
        if config_parser.has_section("queue_job"):
            if config_parser.has_option("options", "queue_job"):
                queue_job_channels = config_parser.get("queue_job", "channels")
        else:
            config_parser.add_section("queue_job")

        if not queue_job_channels:
            config_parser.set(
                "queue_job", "channels", f"root:{os.cpu_count()}"
            )

        with open(config_path, "w") as configfile:
            config_parser.write(configfile)


if __name__ == "__main__":
    main()
