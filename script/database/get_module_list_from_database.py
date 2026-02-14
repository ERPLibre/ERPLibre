#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.execute import execute
from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Will print list of installed module from database
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--database",
        required=True,
        help="The database name to extract",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    execute_cmd = execute.Execute()

    if config.database:
        cmd = f"cat ./script/odoo/util/show_installed_module.py | ./odoo_bin.sh shell -d {config.database}"
        status, output = execute_cmd.exec_command_live(
            cmd,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
            return_status_and_output=True,
        )
        has_find = False
        for line in output:
            if has_find:
                print(line.strip())
            if line.strip() == "Installed modules:":
                has_find = True


if __name__ == "__main__":
    main()
