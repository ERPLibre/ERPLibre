#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

# This script need only basic importation, it needs to be supported by python of your system
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
VERSION_PYTHON_FILE = os.path.join(".python-odoo-version")
INSTALLED_ODOO_VERSION_FILE = ".repo/installed_odoo_version.txt"
VERSION_ERPLIBRE_FILE = os.path.join(".erplibre-version")
VERSION_ODOO_FILE = os.path.join(".odoo-version")
VERSION_POETRY_FILE = os.path.join(".poetry-version")
ADDONS_PATH = os.path.join("addons")
# ODOO_PATH = os.path.join(".", "odoo%s")
VENV_TEMPLATE_FILE = ".venv.%s"
MANIFEST_FILE = "default.dev.xml"
MANIFEST_TEMPLATE_FILE = "default.dev.odoo%s.xml"
MANIFEST_FILE_PATH = os.path.join(".", "manifest", MANIFEST_FILE)
PYPROJECT_FILE = os.path.join("pyproject.toml")
PYPROJECT_TEMPLATE_FILE = "pyproject.%s.toml"
POETRY_LOCK_FILE = os.path.join("poetry.lock")
POETRY_LOCK_TEMPLATE_FILE = "poetry.%s.lock"
# PIP_REQUIREMENT_FILE = os.path.join("requirements.txt")
PIP_REQUIREMENT_TEMPLATE_FILE = "requirements.%s.txt"
PIP_IGNORE_REQUIREMENT_FILE = os.path.join(
    "requirement", "ignore_requirements.txt"
)
PIP_IGNORE_REQUIREMENT_TEMPLATE_FILE = "ignore_requirements.%s.txt"
ADDONS_TEMPLATE_FILE = "odoo%s/addons"
ODOO_TEMPLATE_FILE = "odoo%s"
ERPLIBRE_TEMPLATE_VERSION = "odoo%s_python%s"


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
        "-l",
        "--list",
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
        "--switch",
        action="store_true",
        help="Will only update the system by switch environnement.",
    )
    parser.add_argument(
        "--switch_update",
        action="store_true",
        help="Work with --switch, will do repo update",
    )
    parser.add_argument(
        "--install_dev",
        action="store_true",
        help="Install developer environment.",
    )
    parser.add_argument(
        "--partial_install",
        action="store_true",
        help="Preparation environment file, without installation. Docker need this",
    )
    parser.add_argument(
        "--force_install",
        action="store_true",
        help="Will erase .venv.odooVersion and create symbolic link after installation.",
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
    args.is_in_installation = args.install or args.install_dev
    args.is_in_switch = args.switch
    args.is_in_switch_force_update = args.switch and args.switch_update
    if not (args.install or args.install_dev) and args.force_install:
        args.force_install = False

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
        self.expected_odoo_name = None
        self.expected_odoo_path = None
        self.expected_addons_name = None
        self.expected_venv_name = None
        self.expected_manifest_name = None
        self.expected_manifest_path = None
        self.expected_pyproject_name = None
        self.expected_pyproject_path = None
        self.expected_poetry_lock_name = None
        self.expected_poetry_lock_path = None

    def check_version_data(self):
        die(
            not os.path.isfile(VERSION_DATA_FILE),
            f"Missing {VERSION_DATA_FILE} path, are you sure you run this"
            " script at root of the project?",
        )

        with open(VERSION_DATA_FILE) as txt:
            self.data_version = json.load(txt)

        if self.config.list:
            for key, value in self.data_version.items():
                print(f"{key}: {value}")

    def detect_version(self):
        # Detect actual version
        if not os.path.exists(VERSION_PYTHON_FILE) or not os.path.exists(
            VERSION_ODOO_FILE
        ):
            _logger.info("New installation, cannot detect actual version.")
            return False
        with open(VERSION_PYTHON_FILE) as txt:
            self.python_version = txt.read().strip()
        with open(VERSION_ODOO_FILE) as txt:
            self.odoo_version = txt.read().strip()
        with open(VERSION_POETRY_FILE) as txt:
            poetry_version = txt.read().strip()

        # Show actual version
        _logger.info(f"Python version: {self.python_version}")
        _logger.info(f"Odoo version: {self.odoo_version}")
        _logger.info(f"Poetry version: {poetry_version}")
        erplibre_version_to_search = ERPLIBRE_TEMPLATE_VERSION % (
            self.odoo_version,
            self.python_version,
        )

        # Detect key actual version
        for key, value in self.data_version.items():
            if (
                value.get("odoo_version") == self.odoo_version
                and value.get("python_version") == self.python_version
            ):
                self.detected_version_erplibre = key
                _logger.info(
                    f"Detected erplibre version {erplibre_version_to_search}"
                )
                break
        if not self.detected_version_erplibre:
            _logger.error(
                f"The actual version '{erplibre_version_to_search}' is not"
                f" configured into '{VERSION_DATA_FILE}'. Please update this"
                " file before continue."
            )
            return False

        if os.path.exists(INSTALLED_ODOO_VERSION_FILE):
            with open(INSTALLED_ODOO_VERSION_FILE) as txt:
                lst_version_installed = sorted(txt.read().splitlines())
                str_installed_version = "Installed version: " + ", ".join(
                    lst_version_installed
                )
                _logger.info(str_installed_version)
        return True

    def validate_version(self):
        dct_data_version = {}
        if (
            not self.config.python_version
            and not self.config.poetry_version
            and not self.config.odoo_version
            and not self.config.erplibre_version
            and not self.config.erplibre_package
        ):
            dct_data_version = {}
            if self.detected_version_erplibre:
                dct_data_version = self.data_version.get(
                    self.detected_version_erplibre
                )
            if not dct_data_version:
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
                dct_data_version = self.data_version.get(default_data[0])

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
            self.new_version_erplibre = ERPLIBRE_TEMPLATE_VERSION % (
                self.new_version_odoo,
                self.new_version_python,
            )
        else:
            _logger.info(
                "No difference between detected version and new version:"
                f" {self.detected_version_erplibre}"
            )
            if not dct_data_version:
                _logger.error("Cannot find dct_data_version")
            else:
                self.new_version_erplibre = ERPLIBRE_TEMPLATE_VERSION % (
                    dct_data_version.get("odoo_version"),
                    dct_data_version.get("python_version"),
                )
                self.new_version_odoo = dct_data_version.get("odoo_version")
                self.new_version_python = dct_data_version.get(
                    "python_version"
                )
                self.new_version_poetry = dct_data_version.get(
                    "poetry_version"
                )
                # self.new_version_erplibre = self.detected_version_erplibre
                # self.new_version_odoo = self.odoo_version
                # self.new_version_python = self.python_version
                # TODO needs to detect actual poetry? No?

        self.expected_venv_name = (
            VENV_TEMPLATE_FILE % self.new_version_erplibre
        )
        self.expected_manifest_name = (
            MANIFEST_TEMPLATE_FILE % self.new_version_odoo
        )
        self.expected_manifest_path = os.path.join(
            ".", "manifest", self.expected_manifest_name
        )
        self.expected_pyproject_name = (
            PYPROJECT_TEMPLATE_FILE % self.new_version_erplibre
        )
        self.expected_pyproject_path = os.path.join(
            ".", "requirement", self.expected_pyproject_name
        )

        self.expected_poetry_lock_name = (
            POETRY_LOCK_TEMPLATE_FILE % self.new_version_erplibre
        )
        self.expected_poetry_lock_path = os.path.join(
            ".", "requirement", self.expected_poetry_lock_name
        )
        self.expected_pip_requirement_name = (
            PIP_REQUIREMENT_TEMPLATE_FILE % self.new_version_erplibre
        )
        self.expected_addons_name = (
            ADDONS_TEMPLATE_FILE % self.new_version_odoo
        )
        self.expected_odoo_name = ODOO_TEMPLATE_FILE % self.new_version_odoo
        self.expected_odoo_path = os.path.join(
            ".", self.expected_odoo_name, "odoo", "."
        )
        self.expected_pip_requirement_path = os.path.join(
            ".", "requirement", self.expected_pip_requirement_name
        )
        self.expected_pip_ignore_requirement_name = (
            PIP_IGNORE_REQUIREMENT_TEMPLATE_FILE % self.new_version_erplibre
        )
        self.expected_pip_ignore_requirement_path = os.path.join(
            ".", "requirement", self.expected_pip_ignore_requirement_name
        )

        if self.config.erplibre_package:
            _logger.warning("Not supported erplibre_package configuration")

    def validate_environment(self):
        status = True
        venv_exist = os.path.exists(self.expected_venv_name)
        if not venv_exist and not self.config.install_dev:
            _logger.info("Relaunch this script with --install_dev argument.")
        # Validate Odoo repo
        # status &= self.update_link_file(
        #     "Odoo repository",
        #     ODOO_PATH,
        #     self.expected_odoo_path,
        #     is_directory=True,
        #     do_delete_source=True,
        # )
        # Validate Git repo
        # status &= self.update_link_file(
        #     "Git repositories",
        #     MANIFEST_FILE_PATH,
        #     self.expected_manifest_path,
        #     do_delete_source=True,
        # )
        # status &= self.update_link_file(
        #     "Pip requirement.txt",
        #     PIP_REQUIREMENT_FILE,
        #     self.expected_pip_requirement_path,
        #     do_delete_source=True,
        # )
        # TODO need to remove this from architecture
        # Validate Poetry and pip
        status &= self.update_link_file(
            "Poetry project toml",
            PYPROJECT_FILE,
            self.expected_pyproject_path,
            do_delete_source=True,
        )
        status &= self.update_link_file(
            "Poetry lock",
            POETRY_LOCK_FILE,
            self.expected_poetry_lock_path,
            do_delete_source=True,
        )
        status &= self.update_link_file(
            "Pip ignore_requirement.txt",
            PIP_IGNORE_REQUIREMENT_FILE,
            self.expected_pip_ignore_requirement_path,
            do_delete_source=True,
        )
        if not os.path.isdir(self.expected_addons_name):
            status = False
        # status &= self.update_link_file(
        #     "Directory 'addons'",
        #     ADDONS_PATH,
        #     self.expected_addons_name,
        #     is_directory=True,
        #     do_delete_source=self.config.install_dev
        #     or self.config.force_install,
        # )
        return status

    def update_environment(self):
        status = True
        if self.config.force_repo:
            # TODO add script to check difference before erase all
            os.system("./script/git/clean_repo_manifest.sh")
            self.execute_log.append(
                f"Clear all repo from manifest, everything is deleted"
            )

        # Always overwrite version
        _logger.info(
            f"Update local file, "
            f"python version '{self.new_version_python}', "
            f"erplibre version '{self.new_version_erplibre}', "
            f"odoo version '{self.new_version_odoo}', "
            f"poetry version '{self.new_version_poetry}'"
        )
        with open(VERSION_PYTHON_FILE, "w") as txt:
            txt.write(self.new_version_python)
        with open(VERSION_ERPLIBRE_FILE, "w") as txt:
            txt.write(self.new_version_erplibre)
        with open(VERSION_ODOO_FILE, "w") as txt:
            txt.write(self.new_version_odoo)
        with open(VERSION_POETRY_FILE, "w") as txt:
            txt.write(self.new_version_poetry)

        if self.config.is_in_installation or self.config.is_in_switch:
            #     addons_path_with_version = (
            #         ADDONS_TEMPLATE_FILE % self.new_version_odoo
            #     )
            #     # To support multiple addons directory, change name before run git repo
            #     for addons_path in os.listdir("."):
            #         if (
            #             addons_path.startswith("addons")
            #             and addons_path != addons_path_with_version
            #         ):
            #             os.rename(addons_path, addons_path + "TEMP")

            # TODO need to be force if installation path is all good, return True
            if self.config.install_dev:
                _logger.info("Installation.")
                status = self.install_erplibre()
            elif (
                self.config.is_in_switch
                and self.config.is_in_switch_force_update
            ):
                _logger.info("Switch")
                self.execute_log.append(f"System update")
                status = os.system(
                    "./script/manifest/update_manifest_local_dev.sh"
                )

            # To support multiple addons directory, remove TEMP
            # for addons_path in os.listdir("."):
            #     if (
            #         addons_path.startswith("addons")
            #         and addons_path != addons_path_with_version
            #         and addons_path.endswith("TEMP")
            #     ):
            #         os.rename(addons_path, addons_path[:-4])
            for addons_path in os.listdir("."):
                if addons_path.startswith("addons"):
                    # In same time, force to create addons if not existing
                    addons_dir_path = os.path.join(addons_path, "addons")
                    if not os.path.isdir(addons_dir_path):
                        os.makedirs(addons_dir_path)

            # Force create addons link
            # if os.path.isdir(ADDONS_PATH):
            #     if os.path.islink(ADDONS_PATH):
            #         os.remove(ADDONS_PATH)
            #     else:
            #         os.rename(
            #             ADDONS_PATH,
            #             ADDONS_PATH
            #             + "_"
            #             + time.strftime("%Yy%mm%dd-%Hh%Mm%Ss"),
            #         )
            # os.symlink(addons_path_with_version, ADDONS_PATH)
        return status

    def print_log(self):
        if not self.execute_log:
            _logger.info("Nothing to do")
            return
        _logger.info("List of execution log :")
        for log_info in self.execute_log:
            _logger.info("\t" + log_info)

    def pycharm_update(self):
        pycharm_is_installed = os.path.exists(".idea")
        if not pycharm_is_installed or not self.execute_log:
            return
        os.system(
            "./.venv.erplibre/bin/python ./script/ide/pycharm_configuration.py --init"
        )

    def install_erplibre(self):
        self.execute_log.append(f"Dev installation")
        status = os.system("./script/install/install_locally_dev.sh")
        return status

    def install_system(self):
        self.execute_log.append(f"System installation")
        status = os.system("./script/install/install_dev.sh")
        return status

    def update_link_file(
        self,
        component_name,
        source_file,
        target_file,
        is_directory=False,
        do_delete_source=False,
    ):
        """Call to create a symbolic link
        0. check if file is symlink or file/directory
        1.
        Case 1 : origin file exist, need to be switched by a symlink and rename it;
        Case 2 : no file, check if new version exist and symlink it;
        Case 3 : source file is symlink, and wrong direction, erase it. If new version exist, symlink it.
        Case 4: origin file exist, but it's a wrong symlink
        Good case : source file is symlink, and good redirection.
        """
        # TODO support case symlink is invalid
        status = False
        if not source_file or not target_file:
            _logger.error(
                f"{component_name}:Source file or target file is empty."
            )
        source_file_exist = os.path.exists(source_file)
        source_file_is_symlink = os.path.islink(source_file)
        target_file_exist = os.path.exists(target_file)
        if not target_file_exist:
            _logger.error(f"'{target_file}' not exist.")
        do_symlink = False
        # Case 4
        if source_file_is_symlink and not source_file_exist:
            _logger.error(
                f"{component_name}:File '{source_file}' is a wrong symlink,"
                " delete it."
            )
            os.system(f"rm {source_file}")
            self.execute_log.append(
                f"{component_name}:Delete file {source_file}"
            )
            source_file_is_symlink = False

        # Case 1
        if source_file_exist:
            if not source_file_is_symlink:
                # Check if source type
                if is_directory:
                    source_file_is_directory = os.path.isdir(source_file)
                    if not source_file_is_directory:
                        _logger.error(
                            f"{component_name} - Source '{source_file}' is"
                            " expected to be a directory and it's not."
                        )
                        os.system(f"ls -lha {source_file}")
                        sys.exit(1)
                    # else:
                    #     do_switch_origin_sim = True
                else:
                    source_file_is_file = os.path.isfile(source_file)
                    if not source_file_is_file:
                        _logger.error(
                            f"{component_name} - Source '{source_file}' is"
                            " expected to be a file and it's not."
                        )
                        os.system(f"ls -lha {source_file}")
                        sys.exit(1)
                #     else:
                #         do_switch_origin_sim = True
                # if do_switch_origin_sim:
                #     # Check if not erase an existing
                #     if target_file_exist:
                #         # Create a backup
                #         new_target_file = f"{target_file}.backup_{time.strftime('%Yy%mm%dd-%Hh%Mm%Ss')}"
                #     else:
                #         new_target_file = target_file
                # Move it and create a symlink
                # shutil.move(source_file, new_target_file)
                # do_symlink = True
            else:
                # Case 3
                # Is symlink
                lst_path_source = [
                    a for a in os.path.split(remove_dot_path(source_file)) if a
                ]
                ref_symlink_source = os.readlink(source_file).strip("/")
                lst_path_symlink_source = [
                    a
                    for a in os.path.split(remove_dot_path(ref_symlink_source))
                    if a
                ]
                if (
                    len(lst_path_source) != len(lst_path_symlink_source)
                    and len(lst_path_symlink_source) == 1
                ):
                    ref_symlink_source_from_root = os.path.join(
                        ".",
                        os.sep.join(lst_path_source[:-1]),
                        ref_symlink_source,
                    )
                else:
                    ref_symlink_source_from_root = ref_symlink_source
                do_delete_source = do_delete_source or os.path.exists(
                    target_file
                )
                if os.path.normpath(
                    ref_symlink_source_from_root
                ) == os.path.normpath(target_file):
                    _logger.info(
                        f"{component_name}:The system configuration is good."
                    )
                    status = True
                elif do_delete_source:
                    _logger.warning(
                        f"{component_name}:The file '{source_file}' link"
                        f" '{ref_symlink_source_from_root}' will be delete and"
                        f" link to '{target_file}'."
                    )
                    # symlink, delete it if wrong
                    os.system(f"rm {source_file}")
                    self.execute_log.append(
                        f"{component_name}:Delete file {source_file}"
                    )
                    if target_file_exist:
                        do_symlink = True
                else:
                    _logger.warning(
                        f"{component_name}:The actual link is"
                        f" '{ref_symlink_source_from_root}', but expect to be"
                        f" '{target_file}'."
                    )

        elif target_file_exist:
            # Case 2
            do_symlink = True
        if do_symlink:
            lst_path_target = [
                a for a in os.path.split(remove_dot_path(target_file)) if a
            ]
            lst_path_source = [
                a for a in os.path.split(remove_dot_path(source_file)) if a
            ]
            if len(lst_path_source) == 1:
                os.symlink(target_file, source_file)
                msg = (
                    f"{component_name}:Create symbolic link {source_file} to"
                    f" {target_file}"
                )
                _logger.info(msg)
                self.execute_log.append(msg)
            else:
                target_file_name = lst_path_target[-1]
                source_file_name = lst_path_source[-1]
                # TODO compare lst_path_source avec lst_path_target, si différent, faire le path
                cd_path_target = (
                    "." + os.sep + os.sep.join(lst_path_target[:-1])
                )
                cmd_symlink_manifest = (
                    f"cd {cd_path_target};ln -s"
                    f" {target_file_name} {source_file_name};cd -"
                )
                os.system(cmd_symlink_manifest)
                msg = (
                    f"{component_name}:Create symbolic link"
                    f" {source_file_name} to {target_file_name} from path"
                    f" {cd_path_target}"
                )
                _logger.info(msg)
                self.execute_log.append(msg)
        return status


def remove_dot_path(path):
    """
    if path is ./path/2, will return path/2
    """
    if path.startswith("./"):
        return path[2:]
    return path


def main():
    update = Update()
    _logger.info(f"Work on directory {os.getcwd()}")
    _logger.info("Get data version")
    update.check_version_data()

    _logger.info("Detect version")
    update.detect_version()

    _logger.info("Validate version")
    update.validate_version()

    _logger.info("Validate environment")
    status = 0
    if (
        update.config.install_dev
        or update.config.partial_install
        or update.config.is_in_switch
    ):
        status = update.validate_environment()
    if update.config.install:
        status = update.install_system()
    if (
        update.config.force_install
        or update.config.install_dev
        or update.config.partial_install
        or update.config.is_in_switch
    ) and not status:
        update.update_environment()
    update.print_log()

    if update.config.install_dev:
        # Update pycharm configuration
        update.pycharm_update()

        # Update OCB configuration
        os.system(
            "./.venv.erplibre/bin/python ./script/git/git_repo_update_group.py"
        )
        os.system("./script/generate_config.sh")
        # TODO ignore this if installation fail

        # TODO this cause an error at first execution, need to source ./.venv.erplibre/bin/activate and rerun
        # subprocess.run(['source', './.venv.erplibre/bin/activate'], shell=True)
        # subprocess.run(['make', 'config_gen_all'])
        # status = os.system(f"make config_gen_all")
        #
        # if not status:
        #     print("Please run:")
        #     print("source ./.venv.erplibre/bin/activate")
        #     print("make config_gen_all")


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
