#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import getpass
import logging
import os
import uuid
import time
import json
import sys
from subprocess import check_output
import subprocess

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
    Create image for database restoration to increase speed. Check file

SUGGESTION
    ./script/database/image_db.py --image erplibre_base --odoo_version 16.0
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--image",
        default="erplibre_base",
        help=(
            "Image name to restore, from directory image_db, filename without"
            " '.zip'. Example, use erplibre_base to use image"
            " erplibre_base.zip. Default value is erplibre_base"
        ),
    )
    parser.add_argument(
        "--odoo_version",
        default="16.0",
        help=(
            "Odoo version, example 12.0 or 16.0"
        ),
    )
    parser.add_argument(
        "--generate_list_only",
        action="store_true",
        help=(
            "Generate list for parallel command in bash to run all package from odoo_version"
        ),
    )
    # parser.add_argument(
    #     "--restore_image_db_base",
    #     default="base",
    #     help=(
    #         "Will restore this database before install module. If empty or same of configuration, will create a new one."
    #     ),
    # )
    parser.add_argument(
        "--keep_database",
        action="store_true",
        help="Keep temporary database",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    # Find good conf file
    config_file = os.path.join("conf", f"module_list_image_db_odoo{config.odoo_version}.json")
    if not os.path.exists(config_file):
        _logger.error(f"Configuration file {config_file} does not exist.")
        sys.exit(1)
    with open(config_file, "r") as f:
        dct_config_all_image = json.load(f)
    dct_config_image = dct_config_all_image.get(config.image)

    if config.generate_list_only:
        print("ok")

    python_bin = ".venv/bin/python3"
    bd_temp_name = f"temp_img_create_{config.image}_{uuid.uuid4().hex[:6]}"

    # Summary
    # Step 0, drop and restore
    # Step 1, install addons
    # Step 2, uninstall if need it
    # Step 3, install theme
    # Step 4, create image_db by backup
    # Step 5, loop to 1 with same bd name

    restore_image_db_base = f"odoo{config.odoo_version}_{config.restore_image_db_base}"
    # Step 0, drop and restore
    cmd_drop_db = f"{python_bin} ./odoo/odoo-bin db --drop --database {bd_temp_name}"
    run_cmd(cmd_drop_db)
    if not config.restore_image_db_base or restore_image_db_base == config.image:
        # Create a new one
        cmd = f"{python_bin} ./odoo/odoo-bin db --create --database {bd_temp_name}"
    else:
        cmd = f"{python_bin} ./odoo/odoo-bin db --clone --from_database {restore_image_db_base} --database {bd_temp_name}"
    run_cmd(cmd)
    for component_name, dct_value in dct_config_image.items():
        # Step 1, install addons
        lst_module = ",".join(dct_value.get("module"))
        cmd = f"./script/addons/install_addons.sh {bd_temp_name} {lst_module}"
        run_cmd(cmd)
        # Step 2, uninstall if need it
        # Step 3, install theme
        # Step 4, create image_db by backup
        module_image_name = config.image if not component_name else f"{config.image}_{component_name}"
        cmd = f"{python_bin} ./odoo/odoo-bin db --backup --database {bd_temp_name} --restore_image {module_image_name}"
        run_cmd(cmd)

        # Step 5, loop to 1 with same bd name
    # Step 6, clean if ask
    if not config.keep_database:
        run_cmd(cmd_drop_db)
    print("ok")

def run_cmd(cmd):
    # status = os.system(cmd)
    # if status != 0:
    #     _logger.error(f"Command failed : '{cmd}'")
    #     sys.exit(status)
    _logger.info(f"Run cmd: {cmd}")
    debut = time.time()
    process = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in process.stdout:
        _logger.info(line)
    stdout, stderr = process.communicate()
    fin = time.time()
    status_code = process.returncode
    if stderr:
        _logger.error(stderr)
    execution_time = fin - debut
    _logger.info(f"Time execution: {execution_time:.2f} seconds\n")
    if status_code != 0:
        _logger.error(f"Command failed : '{cmd}'")
        sys.exit(status_code)

if __name__ == "__main__":
    main()
