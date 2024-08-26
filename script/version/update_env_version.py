#!./.venv/bin/python
import argparse
import logging
import json
import os
import shutil
import sys

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
VERSION_PYTHON_FILE = os.path.join(".python-version")
VERSION_ODOO_FILE = os.path.join(".odoo-version")
VENV_FILE = os.path.join(".venv")


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Change environnement from supported version, check file conf/supported_version_erplibre.json
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--list_version",
        action="store_true",
        help="List all supported version.",
    )
    args = parser.parse_args()

    return args


def main():
    has_execute = False
    config = get_config()
    _logger.info(f"Work on directory {os.getcwd()}")

    die(
        not os.path.isfile(VERSION_DATA_FILE),
        (
            f"Missing {VERSION_DATA_FILE} path, are you sure you run this"
            " script at root of the project?"
        ),
    )

    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)

    if config.list_version:
        for key, value in data_version.items():
            print(f"{key}: {value}")

    # Detect actual version
    with open(VERSION_PYTHON_FILE) as txt:
        python_version = txt.read().strip()
    with open(VERSION_ODOO_FILE) as txt:
        odoo_version = txt.read().strip()

    # Show actual version
    _logger.info(f"Python version: {python_version}")
    _logger.info(f"Odoo version: {odoo_version}")

    # Detect key actual version
    detect_version = None
    for key, value in data_version.items():
        if (
            value.get("odoo_version") == odoo_version
            and value.get("python_version") == python_version
        ):
            detect_version = key
            break
    if not detect_version:
        _logger.error(
            f"The actual version is not configured into '{VERSION_DATA_FILE}'."
            " Please update this file before continue."
        )
        return
    else:
        _logger.info(f"Detected version '{detect_version}'")

    # Validate actual environment
    expected_venv_name = f".venv_{detect_version}"
    venv_exist = os.path.exists(VENV_FILE)
    if venv_exist:
        actuel_venv_is_symlink = os.path.islink(VENV_FILE)
        if actuel_venv_is_symlink:
            # Validate version at symlink
            ref_symlink_env = os.readlink(VENV_FILE).strip("/")
            if expected_venv_name == ref_symlink_env:
                _logger.info("The system configuration is good.")
            else:
                _logger.info("Generate environnement")
        else:
            # Move it and create a symlink
            shutil.move(VENV_FILE, expected_venv_name)
            os.symlink(expected_venv_name, VENV_FILE)
    else:
        _logger.info("You need to run installation script : make install_dev")
        # TODO do a validation and take default value
    if not has_execute:
        _logger.info("Nothing to do")


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
