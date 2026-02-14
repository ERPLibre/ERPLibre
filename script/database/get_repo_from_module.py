#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import json
import logging
import os
import sys
import zipfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.execute import execute

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Extract all repo path from installed module into backup.
        Use --backup_path or --backup_name
""",
        epilog="""\
""",
    )
    parser.add_argument("--module", help="Module list separate by ;")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    return args


def main():
    config = get_config()

    lst_module = set(config.module.split(";"))

    cmd = "parallel ::: " + " ".join(
        [
            f"'./script/addons/check_addons_exist.py --output_path -m \"{a}\"'"
            for a in lst_module
        ]
    )
    execute_cmd = execute.Execute()
    status, output = execute_cmd.exec_command_live(
        cmd,
        quiet=not config.debug,
        source_erplibre=False,
        single_source_erplibre=True,
        return_status_and_output=True,
    )
    set_path_repo = set()
    for line_module_path in output:
        line_repo = os.path.dirname(line_module_path)
        set_path_repo.add(line_repo)
    for path_repo in set_path_repo:
        print(path_repo)


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
