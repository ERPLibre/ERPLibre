#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import getpass
import logging
import os
from collections import defaultdict
import uuid
import time
import json
import sys
from subprocess import check_output
import subprocess

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv/bin/python3"

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
        help=(
            "Image name to restore, from directory image_db, filename without"
            " '.zip'. Example, use erplibre_base to use image"
            " erplibre_base.zip. Default value is erplibre_base"
        ),
    )
    parser.add_argument(
        "--odoo_version",
        help=(
            "Force Odoo version, example 12.0 or 16.0, if empty, use from .odoo-version file"
        ),
    )
    parser.add_argument(
        "--generate_list_only",
        action="store_true",
        help=(
            "Generate list command in bash to run all package from odoo_version"
        ),
    )
    parser.add_argument(
        "--generate_bash_cmd_parallel",
        action="store_true",
        help=(
            "Generate list with parallel command in bash to run all package from odoo_version"
        ),
    )
    parser.add_argument(
        "--keep_database",
        action="store_true",
        help="Keep temporary database",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if not config.odoo_version:
        # Fill it from system
        filename_odoo_version = ".odoo-version"
        if not os.path.isfile(filename_odoo_version):
            _logger.error(f"Missing file {filename_odoo_version}")
            sys.exit(1)
        with open(".odoo-version", "r") as f:
            config.odoo_version = f.readline()

    # Open configuration file
    config_file = os.path.join("conf", f"module_list_image_db_odoo.json")
    if not os.path.exists(config_file):
        _logger.error(f"Configuration file {config_file} does not exist.")
        sys.exit(1)

    with open(config_file, "r") as f:
        dct_config_all_image = json.load(f)

    odoo_prefix_version = f"odoo{config.odoo_version}"
    if config.generate_list_only:
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if image_db_name.startswith(odoo_prefix_version):
                # First always need to be a base
                print(f"{PYTHON_BIN} ./script/database/image_db.py --odoo_version {config.odoo_version} --image {image_db_name}")
        sys.exit(0)

    if config.generate_bash_cmd_parallel:
        dct_depend_image = defaultdict(list)
        lst_total_image = []

        lst_distribute_image = []
        lst_queue_parallel = []
        # Search dependency
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if not image_db_name.startswith(odoo_prefix_version):
                continue
            if image_db_name in lst_total_image:
                _logger.error(f"Duplicate image_db_name: {image_db_name}")
                sys.exit(1)
            base_name = dct_image_db.get("base", "")
            dct_depend_image[base_name].append(image_db_name)
            lst_total_image.append(image_db_name)

        # Reorder it
        max_iter = 1000
        i = 0
        while dct_depend_image and i < max_iter:
            i += 1

            if "" in dct_depend_image.keys():
                # Get from empty key for root dependency
                lst_module = dct_depend_image.get("")
                lst_queue_parallel.append(lst_module)
                lst_distribute_image = lst_module[:]
                del dct_depend_image[""]
            else:
                # Search if dependency already into list
                lst_module = []
                lst_key_to_delete = []
                for key_to_check, lst_value in dct_depend_image.items():
                    if key_to_check in lst_distribute_image:
                        # Dependency find
                        lst_key_to_delete.append(key_to_check)
                        lst_distribute_image.extend(lst_value)
                        lst_module.extend(lst_value)
                lst_queue_parallel.append(lst_module)
                for key_to_delete in lst_key_to_delete:
                    del dct_depend_image[key_to_delete]

        # print command to execute
        lst_cmd = []
        for lst_mod in lst_queue_parallel:
            cmd = 'parallel ::: ' + " ".join([f'"./.venv/bin/python3 ./script/database/image_db.py --odoo_version {config.odoo_version} --image {a}"' for a in lst_mod])
            lst_cmd.append(cmd)
        print("\n".join(lst_cmd))
        sys.exit(0)

    image_name_to_generate = config.image if config.image else f"{odoo_prefix_version}_base"
    dct_config_image = dct_config_all_image.get(image_name_to_generate)

    bd_temp_name = f"temp_img_create_{image_name_to_generate}_{uuid.uuid4().hex[:6]}"

    # Summary
    # Step 0, drop and restore
    # Step 1, install addons
    # Step 2, uninstall if need it
    # Step 3, install theme
    # Step 4, create image_db by backup
    # Step 5, loop to 1 with same bd name

    base_image_name = dct_config_image.get("base")
    all_temp_bd = []

    # Step 0, drop and restore
    cmd_drop_db = f"{PYTHON_BIN} ./odoo/odoo-bin db --drop --database {bd_temp_name}"
    all_temp_bd.append(bd_temp_name)
    run_cmd(cmd_drop_db)
    if not base_image_name or base_image_name == image_name_to_generate:
        with_demo = dct_config_image.get("with_demo")
        # Create a new one
        cmd = f"{PYTHON_BIN} ./odoo/odoo-bin db --create --database {bd_temp_name}"
        if with_demo:
            cmd += " --demo"
    else:
        cmd = f"./script/database/db_restore.py --database {bd_temp_name} --image {base_image_name}"
    run_cmd(cmd)
    for dct_value in dct_config_image.get("image_list"):
        pkg_name = dct_value.get("pkg_name", "")
        # Step 1, install addons
        lst_module = ",".join(dct_value.get("module"))
        cmd = f"./script/addons/install_addons.sh {bd_temp_name} {lst_module}"
        run_cmd(cmd)
        # Step 2, uninstall if need it
        # Step 3, install theme
        module_theme = dct_value.get("theme")
        if module_theme:
            cmd = f"./script/addons/install_addons_theme.sh {bd_temp_name} {module_theme}"
            run_cmd(cmd)
        # Step 4, create image_db by backup
        module_image_name = image_name_to_generate if not pkg_name else f"{image_name_to_generate}_{pkg_name}"
        cmd = f"{PYTHON_BIN} ./odoo/odoo-bin db --backup --database {bd_temp_name} --restore_image {module_image_name}"
        run_cmd(cmd)
        # Step 5, loop to 1 with same bd name for next package

    # Step 6, clean if ask
    if not config.keep_database:
        for db_name in all_temp_bd:
            cmd_drop_db = f"{PYTHON_BIN} ./odoo/odoo-bin db --drop --database {db_name}"
            run_cmd(cmd_drop_db)
    _logger.info("End of execution image_db.py")

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
