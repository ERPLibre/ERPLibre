#!./.venv/bin/python
import argparse
import configparser
import logging
import os
import sys
from collections import defaultdict

CONFIG_PATH = "./config.conf"

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
        "--debug",
        action="store_true",
        help="Enable debug output",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config_parser = configparser.ConfigParser()
    config_parser.read(CONFIG_PATH)
    if "options" in config_parser:
        if "addons_path" in config_parser["options"]:
            addons_path = config_parser["options"]["addons_path"]
        else:
            _logger.error(
                "Missing item 'addons_path' in section 'options' in"
                f" '{CONFIG_PATH}'"
            )
            return -1
    else:
        _logger.error(f"Missing section 'options' in '{CONFIG_PATH}'")
        return -1

    lst_addons_path = addons_path.split(",")
    lst_module = config.module.split(",")

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
    if lst_module_not_exist:
        is_good = False
        module_list = "'" + "', '".join(lst_module_not_exist) + "'"
        _logger.error(
            "Missing"
            f" module{'s' if len(lst_module_not_exist) > 1 else ''} {module_list}"
        )
    if dct_module_exist:
        for key, lst_value in dct_module_exist.items():
            if len(lst_value) != 1:
                is_good = False
                module_list = "'" + "', '".join(lst_value) + "'"
                _logger.error(f"Conflict modules: {module_list}")
                for value in lst_value:
                    print(value)

    if dct_module_exist_empty:
        for key, lst_value in dct_module_exist_empty.items():
            module_list = "'" + "', '".join(lst_value) + "'"
            _logger.warning(
                "Found this directory, but missing __manifest__.py:"
                f" {module_list}"
            )

    return 0 if is_good else -1


if __name__ == "__main__":
    sys.exit(main())
