#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

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
    parser.add_argument(
        "--python_version",
        help="Select the python version.",
    )
    parser.add_argument(
        "--poetry_version",
        help="Select the poetry version.",
    )
    parser.add_argument(
        "--odoo_version",
        help="Select the odoo version.",
    )
    parser.add_argument(
        "--erplibre_version",
        help="Select the erplibre version.",
    )
    parser.add_argument(
        "--erplibre_package",
        help=(
            "Select the erplibre package to configure environnement only for"
            " this package."
        ),
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install environnement.",
    )
    parser.add_argument(
        "--install_dev",
        action="store_true",
        help="Install developer environment.",
    )
    parser.add_argument(
        "--force_install",
        action="store_true",
        help="Will erase .venv and create symbolic link after installation.",
    )
    args = parser.parse_args()

    return args


class Update:
    def __init__(self):
        self.has_execute = False
        self.config = get_config()
        self.data_version = None
        self.odoo_version = None
        self.python_version = None
        self.detected_version = None
        self.install_to_version = None

    def check_version_data(self):
        die(
            not os.path.isfile(VERSION_DATA_FILE),
            (
                f"Missing {VERSION_DATA_FILE} path, are you sure you run this"
                " script at root of the project?"
            ),
        )

        with open(VERSION_DATA_FILE) as txt:
            self.data_version = json.load(txt)

        if self.config.list_version:
            for key, value in self.data_version.items():
                print(f"{key}: {value}")

    def detect_version(self):
        # Detect actual version
        with open(VERSION_PYTHON_FILE) as txt:
            self.python_version = txt.read().strip()
        with open(VERSION_ODOO_FILE) as txt:
            self.odoo_version = txt.read().strip()

        # Show actual version
        _logger.info(f"Python version: {self.python_version}")
        _logger.info(f"Odoo version: {self.odoo_version}")

        # Detect key actual version
        self.detected_version = None
        for key, value in self.data_version.items():
            if (
                value.get("odoo_version") == self.odoo_version
                and value.get("python_version") == self.python_version
            ):
                self.detected_version = key
                break
        if not self.detected_version:
            _logger.error(
                "The actual version is not configured into"
                f" '{VERSION_DATA_FILE}'. Please update this file before"
                " continue."
            )
            return False
        else:
            _logger.info(f"Detected version '{self.detected_version}'")

        return True

    def validate_version(self):
        if (
            not self.config.python_version
            and not self.config.poetry_version
            and not self.config.odoo_version
            and not self.config.erplibre_version
            and not self.config.erplibre_package
        ):
            return
        if self.config.python_version:
            print("ok")
        if self.config.poetry_version:
            print("ok")
        if self.config.odoo_version:
            print("ok")
        if self.config.erplibre_version:
            print("ok")
            # TODO update it before install

        if self.config.erplibre_package:
            print("ok")

    def validate_environment(self):
        # Validate actual environment
        expected_venv_name = f".venv_{self.detected_version}"
        venv_exist = os.path.exists(VENV_FILE)
        if venv_exist:
            actuel_venv_is_symlink = os.path.islink(VENV_FILE)
            if actuel_venv_is_symlink:
                # Validate version at symlink
                ref_symlink_env = os.readlink(VENV_FILE).strip("/")
                if expected_venv_name == ref_symlink_env:
                    _logger.info("The system configuration is good.")
                else:
                    _logger.info(
                        "Your environnement is different than expected. You"
                        f" have '{ref_symlink_env}', but we expect"
                        f" '{expected_venv_name}'. Relaunch this script with"
                        " --install_dev argument."
                    )
            if self.config.force_install:
                os.system("rm -rf ./.venv")
            if self.config.install or self.config.install_dev:
                _logger.info("Installation.")
                self.install_erplibre(
                    install_system=self.config.install,
                    install_dev=self.config.install_dev,
                )

            # Re-update if launch installation
            actuel_venv_is_symlink = os.path.islink(VENV_FILE)
            if not actuel_venv_is_symlink:
                # Move it and create a symlink
                shutil.move(VENV_FILE, expected_venv_name)
                os.symlink(expected_venv_name, VENV_FILE)

        else:
            _logger.info(
                "You need to run installation script : make install_dev"
            )
            # TODO do a validation and take default value
        if not self.has_execute:
            _logger.info("Nothing to do")

    def install_erplibre(
        self, install_system=False, install_dev=False
    ):
        status = 0
        if install_system:
            status = os.system("./script/install/install_dev.sh")
        if install_dev and not status:
            status = os.system("./script/install/install_locally_dev.sh")
        return status


def main():
    update = Update()
    _logger.info(f"Work on directory {os.getcwd()}")
    _logger.info("Get data version")
    update.check_version_data()

    _logger.info("Detect version")
    status = update.detect_version()
    if not status:
        return

    _logger.info("Validate version")
    update.validate_version()

    _logger.info("Validate environment")
    update.validate_environment()


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
