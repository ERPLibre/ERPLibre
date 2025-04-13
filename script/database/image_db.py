#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv/bin/python3"
IMAGE_DB_BIN = f"{PYTHON_BIN} ./script/database/image_db.py"


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
            "Force Odoo version, example 12.0 or 16.0, if empty, use from"
            " .odoo-version file"
        ),
    )
    parser.add_argument(
        "--generate_list_only",
        action="store_true",
        help=(
            "Generate list command in bash to run all package from"
            " odoo_version"
        ),
    )
    parser.add_argument(
        "--generate_bash_cmd_parallel",
        action="store_true",
        help=(
            "Generate list with parallel command in bash to run all package"
            " from odoo_version"
        ),
    )
    parser.add_argument(
        "--show_list_only",
        action="store_true",
        help="Show list of all package about Odoo version",
    )
    parser.add_argument(
        "--check_addons_exist",
        action="store_true",
        help=(
            "Will return an error and stop execution if detect a non existing"
            " addons from actual odoo version."
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

    if config.show_list_only:
        lst_image_to_show = set()
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if not image_db_name.startswith(
                odoo_prefix_version
            ) or dct_image_db.get("disable"):
                continue
            # First always need to be a base
            image_list = dct_image_db.get("image_list")
            for dct_image in image_list:
                pkg_name = dct_image.get("pkg_name")
                if pkg_name:
                    sub_image_db_name = f"{image_db_name}_{pkg_name}"
                else:
                    sub_image_db_name = image_db_name
                lst_image_to_show.add(sub_image_db_name)

        lst_to_show = sorted(lst_image_to_show)
        for image_to_show in lst_to_show:
            print(image_to_show)
        sys.exit(0)

    if config.generate_list_only:
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if not image_db_name.startswith(
                odoo_prefix_version
            ) or dct_image_db.get("disable"):
                continue
            # First always need to be a base
            print(
                f"{IMAGE_DB_BIN} --odoo_version"
                f" {config.odoo_version} --image {image_db_name}"
            )
        sys.exit(0)

    if config.check_addons_exist:
        lst_module_to_check = set()
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if not image_db_name.startswith(
                odoo_prefix_version
            ) or dct_image_db.get("disable"):
                continue
            lst_image_list = dct_image_db.get("image_list")
            for dct_image_config in lst_image_list:
                lst_module = dct_image_config.get("module")
                lst_module_to_check.update(lst_module)
        lst_module_missing = []
        for module_to_check in lst_module_to_check:
            cmd_check = (
                f"{PYTHON_BIN} ./script/addons/check_addons_exist.py -m"
                f" {module_to_check}"
            )
            status = run_cmd(cmd_check, quiet=True, sys_exit=False)
            if status:
                lst_module_missing.append(module_to_check)
        if lst_module_missing:
            print(f"Missing module :")
            print(sorted(lst_module_missing))
            sys.exit(1)
        else:
            print("No module missing")
        sys.exit(0)

    if config.generate_bash_cmd_parallel:
        dct_depend_image = defaultdict(list)
        lst_total_image = []

        lst_distribute_image = []
        lst_queue_parallel = []
        dct_image_delay = defaultdict(int)
        # Search dependency
        for image_db_name, dct_image_db in dct_config_all_image.items():
            if not image_db_name.startswith(
                odoo_prefix_version
            ) or dct_image_db.get("disable"):
                continue
            if image_db_name in lst_total_image:
                _logger.error(f"Duplicate image_db_name: {image_db_name}")
                sys.exit(1)
            base_name = dct_image_db.get("base", "")
            dct_depend_image[base_name].append(image_db_name)
            lst_total_image.append(image_db_name)
            dct_image_delay[image_db_name] = dct_image_db.get("delay", 0)

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
                lst_distribute_image_to_append = []
                for key_to_check, lst_value in dct_depend_image.items():
                    if key_to_check in lst_distribute_image:
                        # Dependency find
                        # Search for delay
                        has_delay = False
                        for value_module in lst_value:
                            delay = dct_image_delay.get(value_module)
                            if delay:
                                has_delay = True
                                dct_image_delay[value_module] = delay - 1
                            elif value_module not in lst_distribute_image:
                                lst_distribute_image_to_append.append(
                                    value_module
                                )
                                lst_module.append(value_module)
                        if not has_delay:
                            lst_key_to_delete.append(key_to_check)
                lst_distribute_image.extend(lst_distribute_image_to_append)
                if lst_module:
                    lst_queue_parallel.append(lst_module)
                for key_to_delete in lst_key_to_delete:
                    del dct_depend_image[key_to_delete]

        # not finish to empty the queue
        if dct_depend_image:
            _logger.info(
                "Missing dependencies, auto-run all image generation for last"
                " execution"
            )
            for depend_image, lst_module in dct_depend_image.items():
                lst_queue_parallel.append(lst_module)
        # print command to execute
        lst_cmd = []
        for lst_mod in lst_queue_parallel:
            if not lst_mod:
                continue
            str_module = " ".join(lst_mod)
            cmd = f"echo 'Generate imageDB : [{str_module}]'\n"
            if len(lst_mod) > 1:
                cmd += "parallel ::: " + " ".join(
                    [
                        f'"{IMAGE_DB_BIN} --odoo_version'
                        f' {config.odoo_version} --image {a}"'
                        for a in lst_mod
                    ]
                )
            else:
                cmd += (
                    f"{IMAGE_DB_BIN} --odoo_version"
                    f" {config.odoo_version} --image {lst_mod[0]}"
                )
            cmd += "\nstatus=$?; [ $status -ne 0 ] && exit $status"

            lst_cmd.append(cmd)
        print("\n".join(lst_cmd))
        sys.exit(0)

    image_name_to_generate = (
        config.image if config.image else f"{odoo_prefix_version}_base"
    )
    dct_config_image = dct_config_all_image.get(image_name_to_generate)

    if not dct_config_image:
        _logger.error(f"Cannot retrieve image name '{image_name_to_generate}'")
        sys.exit(1)

    if dct_config_image.get("disable"):
        _logger.info("Ignore this image DB generation, because it's disabled.")
        sys.exit(1)

    bd_temp_name = (
        f"temp_img_create_{image_name_to_generate}_{uuid.uuid4().hex[:6]}"
    )

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
    cmd_drop_db = (
        f"{PYTHON_BIN} ./odoo/odoo-bin db --drop --database {bd_temp_name}"
    )
    all_temp_bd.append(bd_temp_name)
    run_cmd(cmd_drop_db)
    if not base_image_name or base_image_name == image_name_to_generate:
        with_demo = dct_config_image.get("with_demo")
        # Create a new one
        cmd = (
            f"{PYTHON_BIN} ./odoo/odoo-bin db --create --database"
            f" {bd_temp_name}"
        )
        if with_demo:
            cmd += " --demo"
    else:
        cmd = (
            "./script/database/db_restore.py --database"
            f" {bd_temp_name} --image {base_image_name}"
        )
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
            cmd = (
                "./script/addons/install_addons_theme.sh"
                f" {bd_temp_name} {module_theme}"
            )
            run_cmd(cmd)
        # Step 4, create image_db by backup
        module_image_name = (
            image_name_to_generate
            if not pkg_name
            else f"{image_name_to_generate}_{pkg_name}"
        )
        cmd = (
            f"{PYTHON_BIN} ./odoo/odoo-bin db --backup --database"
            f" {bd_temp_name} --restore_image {module_image_name}"
        )
        run_cmd(cmd)
        # Step 5, loop to 1 with same bd name for next package

    # Step 6, clean if ask
    if not config.keep_database:
        for db_name in all_temp_bd:
            cmd_drop_db = (
                f"{PYTHON_BIN} ./odoo/odoo-bin db --drop --database {db_name}"
            )
            run_cmd(cmd_drop_db)


def run_cmd(cmd, quiet=False, sys_exit=True):
    # status = os.system(cmd)
    # if status != 0:
    #     _logger.error(f"Command failed : '{cmd}'")
    #     sys.exit(status)
    if not quiet:
        _logger.info(f"Run cmd: {cmd}")
    debut = time.time()
    process = subprocess.Popen(
        cmd,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    fin = time.time()
    status_code = process.returncode
    if stderr and not quiet:
        _logger.error(stderr)
    execution_time = fin - debut
    if not quiet:
        _logger.info(f"Time execution: {execution_time:.2f} seconds\n")
    if status_code != 0:
        if not quiet:
            _logger.error(f"Command failed : '{cmd}'")
        if sys_exit:
            sys.exit(status_code)
    return status_code


if __name__ == "__main__":
    main()
