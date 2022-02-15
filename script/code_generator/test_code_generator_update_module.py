#!./.venv/bin/python
import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Get the list of updating module in a working path,
        for each module, search where it's suppose to generate new code,
         compare if the date change of directory is after the starting date.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-d",
        "--directory",
        dest="directory",
        required=True,
        help="Directory of the module to check.",
    )
    parser.add_argument(
        "-m",
        "--module_list",
        dest="module_list",
        required=True,
        help="List of module, separate by ','",
    )
    parser.add_argument(
        "--datetime",
        dest="datetime",
        required=True,
        help="The datetime to check if the generated module is after.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if not os.path.exists(config.directory):
        _logger.error(f"Path directory {config.directory} not exist.")
        return -1
    lst_module = [a for a in config.module_list.split(",") if a.split()]
    if not lst_module:
        _logger.error(f"No module was selected, be sure to use --module_list")
        return -1

    lst_result_good = []
    lst_result_wrong = []
    for module_name in lst_module:
        if config.directory.endswith(module_name):
            module_path = config.directory
        else:
            module_path = os.path.join(config.directory, module_name)
        if not os.path.exists(module_path):
            _logger.error(
                f"Module '{module_name}' not existing in path"
                f" '{config.directory}'."
            )
            return -1
        stat = os.stat(module_path)
        result = stat.st_mtime > float(config.datetime)
        if result:
            lst_result_good.append(module_name)
        else:
            lst_result_wrong.append(module_name)

    if lst_result_wrong:
        _logger.error(
            "FAIL - Some modules wasn't updated, did you execute the code"
            f" generator? {lst_result_wrong}"
        )
        return -1
    elif lst_result_good:
        _logger.info("SUCCESS - All modules are updated.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
