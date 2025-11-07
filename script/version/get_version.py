#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import json
import logging
import os
import shutil
import sys
import time

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"""\
        Change environnement from supported version, check file {VERSION_DATA_FILE}.

""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all supported version.",
    )
    # parser.add_argument(
    #     "--python_version",
    #     help="Select the python version.",
    # )
    # parser.add_argument(
    #     "--poetry_version",
    #     help="Select the poetry version.",
    # )
    parser.add_argument(
        "--odoo_version",
        help="Select the odoo version.",
    )
    # parser.add_argument(
    #     "--erplibre_version",
    #     help="Select the erplibre version.",
    # )
    args = parser.parse_args()

    return args


def main():
    die(
        not os.path.isfile(VERSION_DATA_FILE),
        f"Missing {VERSION_DATA_FILE} path, are you sure you run this"
        " script at root of the project?",
    )

    config = get_config()

    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)

    # detect no argument
    # if (
    #     not config.python_version
    #     or not config.poetry_version
    #     or not config.odoo_version
    #     or not config.erplibre_version
    # ):
    if not config.odoo_version:
        config.list = True

    if config.list:
        for key, value in data_version.items():
            print(f"{key}: {value}")

    if config.odoo_version:
        for key, value in data_version.items():
            if value.get("odoo_version") == config.odoo_version:
                print(
                    f"{value.get('odoo_version')}\n"
                    f"{value.get('poetry_version')}\n"
                    f"{value.get('python_version')}\n"
                    f"{key}\n"
                )


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
