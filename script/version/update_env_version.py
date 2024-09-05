#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import json
import os
import shutil
import sys
import time

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
VERSION_PYTHON_FILE = os.path.join(".python-version")
VERSION_ODOO_FILE = os.path.join(".odoo-version")
VENV_FILE = os.path.join(".venv")
MANIFEST_FILE = "default.dev.xml"
MANIFEST_FILE_PATH = os.path.join(".", "manifest", MANIFEST_FILE)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=f"""\
        Change environnement from supported version, check file {VERSION_DATA_FILE}
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
    parser.add_argument(
        "--force_repo",
        action="store_true",
        help="Will erase all repo before install it.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force all, include force_install, force_repo.",
    )
    args = parser.parse_args()

    if args.force:
        args.force_install = True
        args.force_repo = True

    return args


class Update:
    def __init__(self):
        self.execute_log = []
        self.config = get_config()
        self.data_version = None
        self.odoo_version = None
        self.python_version = None
        self.detected_version_erplibre = None
        self.new_version_erplibre = None
        self.new_version_odoo = None
        self.new_version_python = None
        self.new_version_poetry = None
        self.expected_venv_name = None
        self.expected_manifest_name = None
        self.do_backup_venv = False

    def check_version_data(self):
        die(
            not os.path.isfile(VERSION_DATA_FILE),
            f"Missing {VERSION_DATA_FILE} path, are you sure you run this"
            " script at root of the project?",
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
        self.detected_version_erplibre = None
        for key, value in self.data_version.items():
            if (
                value.get("odoo_version") == self.odoo_version
                and value.get("python_version") == self.python_version
            ):
                self.detected_version_erplibre = key
                break
        if not self.detected_version_erplibre:
            _logger.error(
                "The actual version is not configured into"
                f" '{VERSION_DATA_FILE}'. Please update this file before"
                " continue."
            )
            return False
        else:
            _logger.info(
                f"Detected version '{self.detected_version_erplibre}'"
            )

        return True

    def validate_version(self):
        if (
            not self.config.python_version
            and not self.config.poetry_version
            and not self.config.odoo_version
            and not self.config.erplibre_version
            and not self.config.erplibre_package
        ):
            # Take default version
            default_data = [
                key
                for key, value in self.data_version.items()
                if value.get("default")
            ]
            if not default_data:
                _logger.error(
                    "Cannot find default version into file"
                    f" {VERSION_DATA_FILE}"
                )
                sys.exit(1)
            self.data_version = default_data[0]
        has_new_version = False
        if self.config.erplibre_version:
            data = self.data_version.get(self.config.erplibre_version)
            if not data:
                _logger.error(
                    "Missing data for erplibre_version"
                    f" {self.config.erplibre_version}"
                )
                sys.exit(1)
            self.new_version_odoo = data.get("odoo_version")
            self.new_version_python = data.get("python_version")
            self.new_version_poetry = data.get("poetry_version")
            has_new_version = True
        if self.config.python_version:
            self.new_version_python = self.config.python_version
            has_new_version = True
        if self.config.poetry_version:
            self.new_version_poetry = self.config.poetry_version
            has_new_version = True
        if self.config.odoo_version:
            self.new_version_odoo = self.config.odoo_version
            has_new_version = True
        if has_new_version:
            self.new_version_erplibre = (
                f"python{self.new_version_python}_odoo{self.new_version_odoo}"
            )
        else:
            _logger.info(
                "No difference between detected version and new version:"
                f" {self.detected_version_erplibre}"
            )
            self.new_version_erplibre = self.detected_version_erplibre
            self.new_version_odoo = self.odoo_version
            self.new_version_python = self.python_version
            # TODO needs to detect actual poetry? No?

        self.expected_venv_name = f".venv_{self.new_version_erplibre}"
        self.expected_manifest_name = (
            f"default.dev.odoo{self.new_version_odoo}.xml"
        )

        if self.config.erplibre_package:
            _logger.warning("Not supported erplibre_package configuration")

    def validate_environment(self):
        need_relaunch_script_dev = False
        # Validate .venv
        venv_exist = os.path.exists(VENV_FILE)
        if venv_exist:
            actuel_venv_is_symlink = os.path.islink(VENV_FILE)
            actuel_venv_is_dir = os.path.isdir(VENV_FILE)
            if actuel_venv_is_symlink:
                # Validate version at symlink
                ref_symlink_env = os.readlink(VENV_FILE).strip("/")
                if self.expected_venv_name == ref_symlink_env:
                    _logger.info("The system configuration is good.")
                else:
                    _logger.info(
                        "Your environnement is different than expected. You"
                        f" have '{ref_symlink_env}', but we expect"
                        f" '{self.expected_venv_name}'."
                    )
                    if not self.config.install_dev:
                        need_relaunch_script_dev = True
            elif actuel_venv_is_dir:
                self.do_backup_venv = True
            else:
                _logger.warning(
                    f"Don't know what '{VENV_FILE}' file is, can you check?"
                )

        elif not self.config.install_dev:
            need_relaunch_script_dev = True
        # TODO do a validation and take default value
        # Validate manifest
        path_expected_manifest_name = os.path.join(
            ".", "manifest", self.expected_manifest_name
        )
        manifest_expected_exist = os.path.exists(path_expected_manifest_name)
        if manifest_expected_exist:
            # TODO check if link exist, delete it if wrong, else not exist, create it
            actuel_manifest_is_symlink = os.path.islink(MANIFEST_FILE_PATH)
            if actuel_manifest_is_symlink:
                ref_symlink_manifest = os.readlink(MANIFEST_FILE_PATH).strip(
                    "/"
                )
                if self.expected_manifest_name != ref_symlink_manifest:
                    os.system(f"rm -rf {MANIFEST_FILE_PATH}")
                    self.execute_log.append(f"Remove symlink {MANIFEST_FILE_PATH}")
            # Generate a link
            actuel_manifest_is_symlink = os.path.islink(MANIFEST_FILE_PATH)
            if not actuel_manifest_is_symlink:
                cmd_symlink_manifest = (
                    "cd manifest;ln -s"
                    f" {self.expected_manifest_name} {MANIFEST_FILE};cd -"
                )
                os.system(cmd_symlink_manifest)
                self.execute_log.append(
                    f"Create symbolic link {self.expected_manifest_name} to"
                    f" {MANIFEST_FILE}"
                )
        else:
            _logger.error(f"Missing manifest '{path_expected_manifest_name}'")
            return
        if need_relaunch_script_dev:
            _logger.info("Relaunch this script with --install_dev argument.")

    def update_environment(self):
        do_action = bool(any([self.config.install_dev, self.config.install]))
        if self.do_backup_venv and do_action:
            venv_backup_name = (
                f".venv_backup_{time.strftime('%Yy%mm%dd-%Hh%Mm%Ss')}"
            )
            shutil.move(VENV_FILE, venv_backup_name)
            self.execute_log.append(f"Move .venv to backup {venv_backup_name}")
        if self.config.force_repo:
            # TODO add script to check difference before erase all
            os.system("./script/git/clean_repo_manifest.sh")
            self.execute_log.append(
                f"Clear all repo from manifest, everything is deleted"
            )
        if self.config.force_install:
            os.system(f"rm -rf ./{VENV_FILE}")
            self.execute_log.append(f"Remove ./{VENV_FILE}")
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
                shutil.move(VENV_FILE, self.expected_venv_name)
                os.symlink(self.expected_venv_name, VENV_FILE)
                self.execute_log.append(
                    f"Create symbolic link {self.expected_venv_name} to"
                    f" {VENV_FILE}"
                )

    def print_log(self):
        if not self.execute_log:
            _logger.info("Nothing to do")
            return
        _logger.info("List of execution log :")
        for log_info in self.execute_log:
            _logger.info("\t" + log_info)

    def install_erplibre(self, install_system=False, install_dev=False):
        status = 0
        if install_system:
            self.execute_log.append(f"System installation")
            status = os.system("./script/install/install_dev.sh")
        if install_dev and not status:
            self.execute_log.append(f"Dev installation")
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
    update.update_environment()
    update.print_log()


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
