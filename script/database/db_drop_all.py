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
    args = parser.parse_args()
    return args


def main():
    config = get_config()

    out_db = execute_shell("./odoo_bin.sh db --list")
    lst_db = out_db.split("\n")
    for db_name in lst_db:
        if config.test_only and not (
            db_name in ("test",)
            or db_name.startswith("test_")
            or db_name.startswith("new_project_")
        ):
            continue
        execute_shell(
            "./odoo_bin.sh db --drop --database"
            f" {db_name}"
        )
        print(f"{db_name} deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
