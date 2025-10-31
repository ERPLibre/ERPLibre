#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import subprocess
import sys

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


def execute_shell(cmd):
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    return out.decode().strip() if out else ""


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Drop all database, caution!
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--test_only",
        help="test and test_* and other by system test.",
        action="store_true",
    )
    parser.add_argument(
        "--database",
        help="Specify database to delete, separate by coma",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()

    out_db = execute_shell("./odoo_bin.sh db --list")
    lst_db = out_db.split("\n")

    lst_database_to_delete = []
    if config.database:
        lst_database_to_delete = [
            a.strip() for a in config.database.split(",")
        ]

    cmd_all = "parallel :::"
    cmd_end = ""
    lst_db_name = []
    for db_name in lst_db:
        if config.test_only and not (
            db_name in ("test",)
            or db_name.startswith("test_")
            or db_name.startswith("new_project_")
        ):
            continue
        if lst_database_to_delete and db_name not in lst_database_to_delete:
            continue

        cmd_end += f' "./odoo_bin.sh db --drop --database {db_name}"'
        lst_db_name.append(db_name)
    if cmd_end:
        execute_shell(cmd_all + cmd_end)
        print("Database deleted :")
        for db_name in lst_db_name:
            print(db_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
