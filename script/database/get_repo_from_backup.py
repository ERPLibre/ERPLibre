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
    parser.add_argument("--backup_path", help="Backup file path")
    parser.add_argument("--backup_name", help="Backup file name")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Will show all debug and execution information",
    )
    args = parser.parse_args()

    die(
        not (bool(args.backup_path) or bool(args.backup_name)),
        "Take --backup_path or --backup_name",
    )

    return args


def main():
    config = get_config()

    if config.backup_path:
        file_path = config.backup_path
    elif not config.backup_name.endswith(".zip"):
        file_path = os.path.join("image_db", f"{config.backup_name}.zip")
    else:
        file_path = os.path.join("image_db", config.backup_name)

    with zipfile.ZipFile(file_path, "r") as zip_ref:
        manifest_file = zip_ref.open("manifest.json")

    json_manifest_file = json.load(manifest_file)
    lst_module = set(json_manifest_file.get("modules").keys())
    str_module = ";".join(lst_module)
    cmd = f'./script/database/get_repo_from_module.py --module "{str_module}"'
    execute_cmd = execute.Execute()
    status, output = execute_cmd.exec_command_live(
        cmd,
        source_erplibre=False,
        single_source_erplibre=True,
        return_status_and_output=True,
    )


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
