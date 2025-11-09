#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

import git
from git import Repo

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    config = GitTool.get_project_config()

    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Update config.conf file with group specified in manifest file.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--group",
        default="",
        help="Prod by default, use 'dev' for manifest/default.dev.xml",
    )
    parser.add_argument(
        "--extra-addons-path",
        default="",
        help="Separate by , to add extra path for config addons_path",
    )
    parser.add_argument(
        "--ignore-odoo-path",
        action="store_true",
        help="Will remove odoo path, need this feature for OpenUpgrade when Odoo <= 13",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    filter_group = config.group if config.group else None

    git_tool.generate_generate_config(
        filter_group=filter_group,
        extra_path=config.extra_addons_path,
        ignore_odoo_path=config.ignore_odoo_path,
    )


if __name__ == "__main__":
    main()
