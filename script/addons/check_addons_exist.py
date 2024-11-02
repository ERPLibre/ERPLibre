#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import configparser
import logging
import os
import sys
from collections import defaultdict

logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Check if module exist and is not multiple here to manage conflict.
        Return 0 if success, return 1 if missing module, return 2 if multiple same module
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-m",
        "--module",
        required=True,
        help="Module name to search, a list can be use separate by ,",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="./config.conf",
        help="The config path.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    parser.add_argument(
        "--output_path",
        action="store_true",
        help="Print path if module exist",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config_parser = configparser.ConfigParser()
    config_parser.read(config.config)
    if "options" in config_parser:
        if "addons_path" in config_parser["options"]:
            addons_path = config_parser["options"]["addons_path"]
        else:
            _logger.error(
                "Missing item 'addons_path' in section 'options' in"
                f" '{config.config}'"
            )
            return -1
    else:
        _logger.error(f"Missing section 'options' in '{config.config}'")
        return -1

    lst_addons_path = addons_path.strip(",").split(",")
    lst_module = config.module.strip(",").split(",")

    dct_module_exist = defaultdict(list)
    dct_module_exist_empty = defaultdict(list)
    lst_module_not_exist = []

    for module in lst_module:
        for path in lst_addons_path:
            module_path = os.path.join(path, module)
            manifest_file_path = os.path.join(module_path, "__manifest__.py")
            if os.path.isdir(module_path):
                if os.path.isfile(manifest_file_path):
                    dct_module_exist[module].append(module_path)
                else:
                    dct_module_exist_empty[module].append(module_path)

        if module not in dct_module_exist.keys():
            lst_module_not_exist.append(module)

    is_good = True
    error_missing_module = False
    if lst_module_not_exist:
        is_good = False
        error_missing_module = True
        module_list = "'" + "', '".join(lst_module_not_exist) + "'"
        _logger.error(
            "Missing"
            f" module{'s' if len(lst_module_not_exist) > 1 else ''} {module_list}"
        )
    if dct_module_exist:
        for key, lst_value in dct_module_exist.items():
            is_print_value = False
            if len(lst_value) != 1:
                is_print_value = True
                is_good = False
                module_list = "'" + "', '".join(lst_value) + "'"
                _logger.error(f"Conflict modules: {module_list}")
            elif lst_value and config.output_path:
                is_print_value = True
            if is_print_value:
                for value in lst_value:
                    print(value)

    if dct_module_exist_empty and not config.output_path:
        for key, lst_value in dct_module_exist_empty.items():
            module_list = "'" + "', '".join(lst_value) + "'"
            _logger.warning(
                "Found this directory, but missing __manifest__.py:"
                f" {module_list}"
            )

    if not is_good:
        if error_missing_module:
            return 1
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
