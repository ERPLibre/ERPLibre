#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import json
import logging
import os
import shutil
import zipfile
from uuid import uuid4

import click
import todo_file_browser

_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv.erplibre/bin/python3"
UPGRADE_CONFIG_LOG = ".venv.erplibre/odoo_migration_log.json"
VENV_NAME_MODULE_MIGRATOR = ".venv"
LST_PATH_OCA_ODOO_MODULE_MIGRATOR = ["script", "OCA_odoo-module-migrator"]
PATH_OCA_ODOO_MODULE_MIGRATOR = "./" + "/".join(
    LST_PATH_OCA_ODOO_MODULE_MIGRATOR
)
PATH_VENV_MODULE_MIGRATOR = os.path.join(
    PATH_OCA_ODOO_MODULE_MIGRATOR, VENV_NAME_MODULE_MIGRATOR
)
PATH_SOURCE_VENV_MODULE_MIGRATOR = os.path.join(
    PATH_VENV_MODULE_MIGRATOR, "bin", "activate"
)
FILENAME_ODOO_VERSION = ".odoo-version"


class TodoUpgrade:
    def __init__(self, todo):
        self.file_path = None
        self.todo = todo
        self.dct_progression = {}
        self.lst_command_executed = []
        self.dct_module_per_version = {}
        self.dct_module_per_dct_version_path = {}

    def write_config(self):
        if "date_create" not in self.dct_progression.keys():
            self.dct_progression["date_create"] = str(datetime.datetime.now())
        self.dct_progression["date_update"] = str(datetime.datetime.now())
        with open(UPGRADE_CONFIG_LOG, "w") as f:
            json.dump(self.dct_progression, f, indent=4)

    def on_file_selected(self, file_path):
        self.file_path = file_path
        todo_file_browser.exit_program()

    def execute_odoo_upgrade(self):
        # TODO update dev environment for git project
        # TODO Redeploy new production after upgrade
        # 2 upgrades version = 5 environnement. 0-prod init, 1-dev init, 2-dev01, 3-dev02, 4-prod final
        print("Welcome to Odoo upgrade processus with ERPLibre 🤖")
        self.lst_command_executed = []
        self.dct_module_per_version = {}
        self.dct_module_per_dct_version_path = {}
        default_database_name = "test"

        if os.path.exists(UPGRADE_CONFIG_LOG):
            print("✨ Detected migration, please select an option.")
            print("[y] Erase progression for a new migration")
            print("[r] Reuse database with new process")
            print(
                "[d] Reuse database without state_4, before looping on next version"
            )
            erase_progression_input = (
                input("💬 Select an option or press to continue : ")
                .strip()
                .lower()
            )
            if erase_progression_input in ["r", "reuse", "d"]:
                with open(UPGRADE_CONFIG_LOG, "r") as f:
                    try:
                        old_dct_progression = json.load(f)
                        self.dct_progression = {
                            "migration_file": old_dct_progression.get(
                                "migration_file"
                            ),
                            # More useful to ask this question each time
                            # "target_odoo_version": old_dct_progression.get(
                            #     "target_odoo_version"
                            # ),
                            "date_create": old_dct_progression.get(
                                "date_create"
                            ),
                        }
                        for key, value in old_dct_progression.items():
                            if erase_progression_input == "d":
                                if (
                                    key.startswith("state_0")
                                    or key.startswith("state_1")
                                    or key.startswith("state_2")
                                    or key.startswith("state_3")
                                ):
                                    self.dct_progression[key] = value
                                if key.startswith(f"config_state") and not (
                                    key.startswith(f"config_state_0")
                                    or key.startswith(f"config_state_1")
                                    or key.startswith(f"config_state_2")
                                    or key.startswith(f"config_state_3")
                                ):
                                    continue
                            if key.startswith("config_"):
                                self.dct_progression[key] = value
                        # Force to search missing module to fill dict
                        self.dct_progression[
                            "state_0_search_missing_module"
                        ] = False
                    except json.decoder.JSONDecodeError:
                        print(
                            f"⚠️ The config file '{UPGRADE_CONFIG_LOG}' is invalid, ignore it."
                        )

                self.write_config()
            elif erase_progression_input not in ["y", "yes"]:
                with open(UPGRADE_CONFIG_LOG, "r") as f:
                    try:
                        self.dct_progression = json.load(f)
                    except json.decoder.JSONDecodeError:
                        print(
                            f"⚠️ The config file '{UPGRADE_CONFIG_LOG}' is invalid, ignore it."
                        )

        if "migration_file" in self.dct_progression:
            self.file_path = self.dct_progression["migration_file"]
        else:
            print("")
            print("Select the zip file of you database backup.")

            self.file_path = input(
                "💬 Give the path of file, or empty to use a File Browser, or type 'remote' to download from production : "
            )
            if not self.file_path.strip():
                self.file_path = None
            if not self.file_path:
                initial_dir = os.path.join(os.getcwd(), "image_db")
                file_browser = todo_file_browser.FileBrowser(
                    initial_dir, self.on_file_selected
                )
                file_browser.run_main_frame()
            elif self.file_path == "remote":
                status, self.file_path, default_database_name = (
                    self.todo.download_database_backup_cli()
                )
                if status:
                    _logger.error(
                        "Cannot retrieve database from remote, please retry migration."
                    )
                    return

            self.dct_progression["migration_file"] = self.file_path
            self.write_config()

        print(f"✅ Open file {self.file_path}")
        with zipfile.ZipFile(self.file_path, "r") as zip_ref:
            manifest_file_1 = zip_ref.open("manifest.json")
        json_manifest_file_1 = json.load(manifest_file_1)
        odoo_actual_version = json_manifest_file_1.get("version")
        print(f"✅ Detect version Odoo CE '{odoo_actual_version}'.")

        # print("What is your actual Odoo version?")
        lst_version, lst_version_installed, odoo_installed_version = (
            self.todo.get_odoo_version()
        )

        lst_odoo_version = [
            {"prompt_description": a.get("odoo_version")}
            for a in lst_version
            if float(a.get("odoo_version")) > float(odoo_actual_version)
        ]
        help_info = self.todo.fill_help_info(lst_odoo_version)

        if "target_odoo_version" in self.dct_progression:
            odoo_target_version = self.dct_progression["target_odoo_version"]
        else:
            print("💬 Which version do you want to upgrade to?")
            odoo_target_version = None
            cmd_no_found = True
            while cmd_no_found:
                status = click.prompt(help_info)
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_odoo_version):
                        cmd_no_found = False
                        odoo_target_version = lst_odoo_version[
                            int_cmd - 1
                        ].get("prompt_description")
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

            self.dct_progression["target_odoo_version"] = odoo_target_version
            self.write_config()

        # Search nb diff to use range
        start_version = int(float(odoo_actual_version))
        end_version = int(float(odoo_target_version))
        range_version = range(start_version, end_version)
        lst_module = sorted(
            list(set(json_manifest_file_1.get("modules").keys()))
        )
        self.dct_module_per_version[start_version] = lst_module
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.dct_progression["lst_module_per_version_origin"] = lst_module
        # TODO need support minor version, example 18.2, the .2 (no need for OCE OCB)

        print("✨ Show documentation version :")
        # TODO Generate it locally and show it if asked

        for next_version in range_version:
            print(
                f"https://oca.github.io/OpenUpgrade/coverage_analysis/modules{next_version*10}-{(next_version+1)*10}.html"
            )

        # ⚠️ ℹ 💬 ❗ 🔷 ✨ 🟦 🔹 🔵 ⟳ ⧖ ⚙ ✔ ✅ ❌ ⏵ ⏸ ⏹ ◆ ◇ … ➤ ⚑ ★ ☆ ☰ ⬍ ⍟ ⊗ ⌘ ⏻ ⍰
        msg = "0 - Inspect zip"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)
        print("✅ -> Search odoo version")
        print("✅ -> Find good environment, read the .zip file")

        is_state_4_reach_open_upgrade = self.dct_progression.get(
            "state_4_reach_open_upgrade"
        )

        if not is_state_4_reach_open_upgrade and not self.dct_progression.get(
            "state_0_install_odoo"
        ):
            lst_diff_version = sorted(
                list(
                    set([f"odoo{a}.0" for a in range_version]).difference(
                        set(lst_version_installed)
                    )
                )
            )
            for odoo_version_to_install in lst_diff_version:
                iter_range_version = odoo_version_to_install.replace(
                    "odoo", ""
                ).replace(".0", "")
                want_continue = input(
                    f"💬 Would you like to install '{odoo_version_to_install}' (y/Y) : "
                )
                if want_continue.strip().lower() != "y":
                    return
                self.todo_upgrade_execute(
                    f"make install_odoo_{iter_range_version}"
                )

                if not os.path.isfile(FILENAME_ODOO_VERSION):
                    print(
                        "⚠️ You need an installed system before continue, check your Odoo installation."
                    )
                    return

        self.dct_progression["state_0_install_odoo"] = True
        self.write_config()
        # not self.dct_progression.get("state_0_switch_odoo")
        if not is_state_4_reach_open_upgrade:
            self.switch_odoo(odoo_actual_version)
        # self.dct_progression["state_0_switch_odoo"] = True
        # self.write_config()

        print("✅ -> Install environment if missing")

        if not self.dct_progression.get("state_0_search_missing_module"):
            self.switch_odoo(odoo_actual_version)
            dct_bd_modules = json_manifest_file_1.get("modules")
            lst_module_to_check = [a for a in dct_bd_modules.keys()]
            (
                lst_module_missing,
                lst_module_duplicate,
                lst_module_exist,
                lst_module_error,
            ) = self.check_addons_exist(lst_module_to_check, get_all_info=True)
            if not lst_module_missing:
                lst_module_missing = []
            dct_module_exist = {}
            if not lst_module_exist:
                lst_module_exist = []
            else:
                for item_lst_module_exist in lst_module_exist:
                    dct_module_exist[item_lst_module_exist[0]] = (
                        item_lst_module_exist[1].replace(os.getcwd(), ".")
                    )
            if not lst_module_duplicate:
                lst_module_duplicate = []

            lst_module_missing = sorted(list(set(lst_module_missing)))
            self.dct_progression["len_lst_module_missing"] = len(
                lst_module_missing
            )
            self.dct_progression["lst_module_missing"] = lst_module_missing
            self.dct_progression["len_dct_module_exist"] = len(
                lst_module_exist
            )
            self.dct_progression["dct_module_exist"] = dct_module_exist
            lst_module_duplicate = sorted(list(set(lst_module_duplicate)))
            self.dct_progression["len_lst_module_duplicate"] = len(
                lst_module_duplicate
            )

            self.dct_progression["lst_module_duplicate"] = lst_module_duplicate
            self.write_config()
            if lst_module_missing or lst_module_duplicate:
                print("Cannot setup environment to begin.")
                if lst_module_missing:
                    print("Missing module :")
                    print(lst_module_missing)
                if lst_module_duplicate:
                    print("Duplicate module :")
                    print(lst_module_duplicate)
                want_continue = input(
                    "💬 Detect error missing/duplicate module init, do you want to continue? (Y/N): "
                )
                if want_continue.strip().lower() != "y":
                    return

            self.dct_progression["state_0_search_missing_module"] = True
            self.write_config()
        else:
            # TODO fill from config
            lst_module_missing = []

        print("✅ -> Search missing module")

        print(
            "❌ -> Install missing module, do a research or ask to uninstall it (can break data)"
        )

        msg = "1 - Import database from zip"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        database_name = self.dct_progression.get("config_database_name")
        if not database_name:
            database_name = (
                input(
                    f"💬 With database name do you want to work with? Default ({default_database_name}) : "
                ).strip()
                or default_database_name
            )
            self.dct_progression["config_database_name"] = database_name
            self.write_config()

        print(f"★ Work with database '{database_name}'")

        if not self.dct_progression.get("state_1_restore_database"):
            file_name = os.path.basename(self.file_path)
            image_db_file_path = os.path.join("image_db", file_name)
            if os.path.exists(image_db_file_path):
                if not shutil._samefile(self.file_path, image_db_file_path):
                    status_overwrite_image_db = input(
                        f"🤖 will copy '{self.file_path}' to '{image_db_file_path}', "
                        f"a file already exist, do you want to continue (y/Y) : "
                    ).strip()
                    if status_overwrite_image_db.lower() != "y":
                        return
                    os.remove(image_db_file_path)
                    shutil.copy(self.file_path, image_db_file_path)

            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/database/db_restore.py --database {database_name} --image {file_name} --ignore_cache",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_1_restore_database"] = True
                self.write_config()

        print("✅ -> Restore database")

        if not self.dct_progression.get("state_1_neutralize_database"):
            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_1_neutralize_database"] = True
                self.write_config()

        print("✅ -> Neutralize database")

        config_state_1_uninstall_module = self.dct_progression.get(
            "config_state_1_uninstall_module"
        )
        config_state_1_install_module = self.dct_progression.get(
            "config_state_1_install_module"
        )

        if not is_state_4_reach_open_upgrade:
            lst_module_to_uninstall = []
            uninstall_module_list_file = os.path.join(
                "script",
                "odoo",
                "migration",
                f"uninstall_module_list_odoo{start_version * 10}_to_odoo{(start_version + 1) * 10}.txt",
            )
            if os.path.exists(uninstall_module_list_file):
                with open(uninstall_module_list_file, "r") as f:
                    lst_module_to_uninstall = [
                        a.strip() for a in f.readline().split()
                    ]

            if config_state_1_uninstall_module:
                lst_module_to_uninstall = (
                    lst_module_to_uninstall + config_state_1_uninstall_module
                )

            if lst_module_to_uninstall:
                self.uninstall_from_database(
                    lst_module_to_uninstall, database_name, start_version
                )
                self.dct_progression["state_1_uninstall_module"] = True
                self.write_config()

        self.dct_progression["config_state_1_uninstall_module"] = (
            config_state_1_uninstall_module
        )

        self.write_config()

        print("✅ -> Uninstall module")

        print("✅ -> install module")
        if not is_state_4_reach_open_upgrade:
            lst_module_to_install = []
            if config_state_1_install_module:
                lst_module_to_install = (
                    lst_module_to_install + config_state_1_install_module
                )
            if lst_module_to_install:
                self.install_from_database(
                    lst_module_to_install, database_name, start_version
                )
                self.dct_progression["state_1_install_module"] = True
                self.write_config()
        self.dct_progression["config_state_1_install_module"] = (
            config_state_1_install_module
        )
        self.write_config()

        msg = "2 - Succeed update all addons"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        if not self.dct_progression.get("state_2_update_all"):
            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/addons/update_addons_all.sh {database_name}",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_2_update_all"] = True
                self.write_config()

        msg = "3 - Clean up database before data migration"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        if not self.dct_progression.get("state_3_install_clean_database"):
            status, cmd_executed = self.todo_upgrade_execute(
                f"./script/addons/install_addons.sh {database_name} database_cleanup",
                single_source_odoo=True,
            )
            if not status:
                self.dct_progression["state_3_install_clean_database"] = True
                self.write_config()

        if not self.dct_progression.get("state_3_clean_database"):
            print(
                "✨ Aller dans «configuration/Technique/Nettoyage.../Purger» les modules obsolètes"
            )
            status = input(
                "💬 Did you finish to clean database? Press y/Y to open server with selenium, else ignore it : "
            ).strip()

            if status.lower().strip() == "y":
                self.todo.prompt_execute_selenium_and_run_db(database_name)
                status = input("💬 Press to continue state.3 : ").strip()

            self.dct_progression["state_3_clean_database"] = True
            self.write_config()

        msg = "4 - Upgrade version with OpenUpgrade"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        self.dct_progression["state_4_reach_open_upgrade"] = True
        self.write_config()
        lst_next_version = [
            a for a in range(start_version + 1, end_version + 1)
        ]
        lst_database_name_upgrade = [
            f"{database_name}_upgrade_{str(a)}" for a in lst_next_version
        ]
        # Setup lst_switch_odoo
        lst_clone_odoo = self.dct_progression.get(
            "state_4_clone_odoo_lst", [False] * len(lst_next_version)
        )
        lst_switch_odoo = self.dct_progression.get(
            "state_4_switch_odoo_lst", [False] * len(lst_next_version)
        )
        lst_module_migrate_odoo = self.dct_progression.get(
            "state_4_module_migrate_odoo_lst", [False] * len(lst_next_version)
        )
        lst_module_uninstall_module = self.dct_progression.get(
            "state_4_uninstall_module", [False] * len(lst_next_version)
        )
        lst_module_install_module = self.dct_progression.get(
            "state_4_install_module", [False] * len(lst_next_version)
        )
        lst_module_search_missing_module = self.dct_progression.get(
            "state_4_search_missing_module", [False] * len(lst_next_version)
        )

        nb_missing_value_switch_odoo = abs(
            len(lst_switch_odoo) - len(lst_next_version)
        )
        if nb_missing_value_switch_odoo:
            lst_switch_odoo += [False] * nb_missing_value_switch_odoo

        # Setup lst_upgrade_odoo
        lst_upgrade_odoo = self.dct_progression.get(
            "state_4_upgrade_odoo_lst", [[]] * len(lst_next_version)
        )
        lst_fix_migration_odoo = self.dct_progression.get(
            "state_4_fix_migration_odoo_lst", [[]] * len(lst_next_version)
        )
        nb_missing_value_upgrade_odoo = abs(
            len(lst_upgrade_odoo) - len(lst_next_version)
        )
        if nb_missing_value_upgrade_odoo:
            lst_upgrade_odoo += [[]] * nb_missing_value_upgrade_odoo

        database_name_upgrade = None
        lst_module_missing_next_version = []
        lst_module_to_delete = []
        lst_module_to_delete_last_version = []
        for index, next_version in enumerate(lst_next_version):
            # Reinit the list
            lst_module_missing_last_version = lst_module_missing_next_version[
                :
            ]
            lst_module_to_delete_last_version.extend(lst_module_to_delete)
            lst_module_to_delete = []

            msg = f"4.{index} - Ready to work with version {next_version}"
            self.add_comment_progression(msg)

            option_comment = 0
            msg = f"4.{index}.{chr(option_comment + 65)} - Search updated module list to next version"
            self.add_comment_progression(msg)

            if not database_name_upgrade:
                last_database_name = database_name
            else:
                last_database_name = database_name_upgrade
            database_name_upgrade = lst_database_name_upgrade[index]
            lst_module_to_uninstall = []
            lst_module_to_install = []
            lst_module_to_analyse = self.get_rename_module(
                self.dct_module_per_version[next_version - 1],
                next_version,
            )
            self.dct_module_per_version[next_version] = sorted(
                list(set(lst_module_to_analyse))
            )
            self.dct_progression["dct_module_per_version"] = (
                self.dct_module_per_version
            )

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Clone Odoo"
            self.add_comment_progression(msg)

            if not lst_clone_odoo[index]:
                self.switch_odoo(next_version - 1)

                print(
                    f"⧖ -> Clone to odoo.'{next_version}', from '{database_name}' to '{database_name_upgrade}'."
                )
                # Delete if exist database
                self.todo_upgrade_execute(
                    f"./script/database/db_restore.py -d {database_name_upgrade} --only_drop",
                )

                # Duplicate database
                cmd_clone_database = f"./odoo_bin.sh db --clone --from_database {last_database_name} --database {database_name_upgrade}"
                self.todo_upgrade_execute(cmd_clone_database)

                lst_clone_odoo[index] = True
                self.dct_progression["state_4_clone_odoo_lst"] = lst_clone_odoo
                self.write_config()
                print(f"✅ -> Clone Odoo{next_version} done")
            else:
                print(f"✅ -> Clone Odoo{next_version} - nothing")

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Uninstall module"
            self.add_comment_progression(msg)

            config_state_4_uninstall_module = self.dct_progression.get(
                "config_state_4_uninstall_module",
                [False] * len(lst_next_version),
            )

            if not lst_module_uninstall_module[index]:
                lst_module_to_uninstall = config_state_4_uninstall_module[
                    index
                ]

                if lst_module_to_uninstall:
                    self.uninstall_from_database(
                        lst_module_to_uninstall,
                        database_name_upgrade,
                        next_version - 1,
                    )
                    lst_module_uninstall_module[index] = True
                    self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                        lst_module_uninstall_module
                    )
                    self.write_config()

            self.dct_progression["config_state_4_uninstall_module"] = (
                config_state_4_uninstall_module
            )
            self.dct_progression["state_4_uninstall_module"] = (
                lst_module_uninstall_module
            )
            self.write_config()

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Install module"
            self.add_comment_progression(msg)

            config_state_4_install_module = self.dct_progression.get(
                "config_state_4_install_module",
                [False] * len(lst_next_version),
            )

            # Special case to install module to fix migration
            if next_version == 13 and "dms" in lst_module_to_analyse:
                # Force install dms into odoo 12
                if not config_state_4_install_module[index]:
                    config_state_4_install_module[index] = ["dms"]
                elif "dms" not in config_state_4_install_module[index]:
                    config_state_4_install_module[index].append("dms")

            if not lst_module_install_module[index]:
                lst_module_to_install = config_state_4_install_module[index]
                if not lst_module_to_install:
                    lst_module_to_install = []

                if lst_module_to_install:
                    self.install_from_database(
                        lst_module_to_install,
                        database_name_upgrade,
                        next_version - 1,
                    )
                    lst_module_install_module[index] = True
                    self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                        lst_module_install_module
                    )
                    self.write_config()

            self.dct_progression["config_state_4_install_module"] = (
                config_state_4_install_module
            )
            self.dct_progression["state_4_install_module"] = (
                lst_module_install_module
            )
            self.write_config()

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Switch Odoo"
            self.add_comment_progression(msg)

            if not lst_switch_odoo[index]:
                self.switch_odoo(next_version)
                lst_switch_odoo[index] = True
                self.dct_progression["state_4_switch_odoo_lst"] = (
                    lst_switch_odoo
                )
                self.write_config()
                print(f"✅ -> Switch Odoo{next_version} done with update")
            else:
                print(f"✅ -> Switch Odoo{next_version} - nothing")

            lst_state_4_module_migrate_code = self.dct_progression.get(
                "config_state_4_module_to_migrate_code",
                [[]] * len(lst_next_version),
            )
            if (
                "config_state_4_module_to_migrate_code"
                not in self.dct_progression.keys()
            ):
                self.dct_progression[
                    "config_state_4_module_to_migrate_code"
                ] = lst_state_4_module_migrate_code
            lst_module_to_migrate = lst_state_4_module_migrate_code[index]

            option_comment += 1
            msg = (
                f"4.{index}.{chr(option_comment + 65)} - Search missing module"
            )
            self.add_comment_progression(msg)

            if not lst_module_search_missing_module[index]:
                lst_module_to_analyse_updated = []
                for bd_module in lst_module_to_analyse:
                    if (
                        lst_module_to_uninstall
                        and bd_module in lst_module_to_uninstall
                    ):
                        # Ignore check if uninstall before
                        continue
                    lst_module_to_analyse_updated.append(bd_module)

                # TODO remove from list past module deleted
                lst_module_to_check = [
                    a
                    for a in lst_module_to_analyse_updated
                    if a not in lst_module_to_delete_last_version
                ]
                (
                    lst_module_missing_next_version,
                    lst_module_duplicate_next_version,
                ) = self.check_addons_exist(lst_module_to_check)

                lst_module_missing_next_version = sorted(
                    list(set(lst_module_missing_next_version))
                )

                self.dct_progression["state_4_len_lst_module_missing"] = len(
                    lst_module_missing_next_version
                )
                self.dct_progression["state_4_lst_module_missing"] = (
                    lst_module_missing_next_version
                )

                lst_module_duplicate = sorted(
                    list(set(lst_module_duplicate_next_version))
                )

                self.dct_progression["state_4_len_lst_module_duplicate"] = len(
                    lst_module_duplicate
                )
                self.dct_progression["state_4_lst_module_duplicate"] = (
                    lst_module_duplicate
                )

                if lst_module_duplicate:
                    print(f"Duplicate module into odoo{next_version} : ")
                    print(lst_module_duplicate)
                    input(
                        f"💬 Detect error duplicate module, manage this problem manually and press to continue."
                    )
                # if lst_module_missing_next_version and not lst_module_to_migrate:
                if lst_module_missing_next_version:
                    # TODO support when lst_module_to_migrate is fill
                    lst_module_to_migrate = []
                    print(
                        f"👹 Detect error missing module, missing module into odoo{next_version} :"
                    )
                    for index_missing_module, module_missing in enumerate(
                        lst_module_missing_next_version
                    ):
                        old_path = self.dct_progression.get(
                            "dct_module_exist", {}
                        ).get(module_missing)
                        print(
                            f"[{index_missing_module}] {module_missing} - {old_path}"
                        )
                    print("[a] All list above")
                    print("[e] Add extra custom")

                    want_continue = (
                        input(
                            f"💬 Enumerate missing module separate by coma to delete it"
                            f". The others will be migrate : "
                        )
                        .strip()
                        .lower()
                    )

                    is_delete_all = False

                    if want_continue:
                        lst_want_continue = [
                            a.strip() for a in want_continue.split(",")
                        ]
                        if "a" in lst_want_continue:
                            is_delete_all = True
                            lst_module_to_delete = [
                                lst_module_missing_next_version[a]
                                for a in range(
                                    len(lst_module_missing_next_version)
                                )
                            ]
                        else:
                            # TODO show error if the index is wrong
                            lst_want_continue_number = [
                                int(a)
                                for a in lst_want_continue
                                if a.isdigit()
                            ]
                            lst_module_to_delete = [
                                lst_module_missing_next_version[a]
                                for a in lst_want_continue_number
                                if 0
                                <= a
                                < len(lst_module_missing_next_version)
                            ]
                            if len(lst_module_to_delete) == len(
                                lst_module_missing_next_version
                            ):
                                is_delete_all = True

                        if "e" in lst_want_continue:
                            want_continue = (
                                input(
                                    f"💬 Enumerate module name to delete, separate by coma : "
                                )
                                .strip()
                                .lower()
                            )
                            lst_to_extend = [
                                a.strip() for a in want_continue.split(",")
                            ]
                            lst_module_to_delete.extend(lst_to_extend)

                    if lst_module_to_delete:
                        msg = f"4.{index}.{chr(option_comment + 65)}.option - Choose delete missing module"
                        self.add_comment_progression(msg)

                    self.switch_odoo(next_version - 1)

                    if lst_module_to_delete:
                        # Delete if exist database
                        self.todo_upgrade_execute(
                            f"./script/database/db_restore.py -d {database_name_upgrade} --only_drop",
                        )
                        # Duplicate database
                        cmd_clone_database = f"./odoo_bin.sh db --clone --from_database {last_database_name} --database {database_name_upgrade}"
                        self.todo_upgrade_execute(cmd_clone_database)
                        self.uninstall_from_database(
                            lst_module_to_delete,
                            database_name_upgrade,
                            next_version,
                        )
                        self.install_from_database(
                            lst_module_to_install,
                            database_name_upgrade,
                            next_version - 1,
                        )

                    if not is_delete_all:
                        msg = f"4.{index}.{chr(option_comment + 65)}.option - Choose auto-fix (not implemented yet)"
                        self.add_comment_progression(msg)

                        lst_module_to_migrate_code = set(
                            lst_module_missing_next_version
                        ) - set(lst_module_to_delete)
                        (
                            lst_module_missing_last,
                            lst_module_duplicate_last,
                            lst_module_exist_last,
                            lst_module_error_last,
                        ) = self.check_addons_exist(
                            lst_module_to_migrate_code, get_all_info=True
                        )

                        if lst_module_missing_last:
                            print(
                                f"Error missing module : {lst_module_missing_last}"
                            )
                        if lst_module_duplicate_last:
                            print(
                                f"Error duplicate module : {lst_module_duplicate_last}"
                            )
                        if lst_module_error_last:
                            print(
                                f"Error error module : {lst_module_error_last}"
                            )

                        if lst_module_exist_last:
                            odoo_name_last_version = (
                                f"odoo{next_version - 1}.0"
                            )
                            odoo_name_actual_version = f"odoo{next_version}.0"
                            for (
                                module_name,
                                module_path,
                            ) in lst_module_exist_last:
                                module_dir_path = os.path.dirname(module_path)
                                module_dir_path_new_version = (
                                    module_dir_path.replace(
                                        odoo_name_last_version,
                                        odoo_name_actual_version,
                                    )
                                )
                                module_dir_path_manifest = os.path.join(
                                    module_path, "__manifest__.py"
                                )
                                module_dir_new_version = os.path.join(
                                    module_dir_path_new_version, module_name
                                )
                                module_dir_new_version_manifest = os.path.join(
                                    module_dir_new_version, "__manifest__.py"
                                )
                                dct_module_to_migrate_module = {
                                    "source_module_path": module_path,
                                    "source_manifest_path": module_dir_path_manifest,
                                    "source_addons_path": module_dir_path,
                                    "target_module_path": module_dir_new_version,
                                    "target_manifest_path": module_dir_new_version_manifest,
                                    "target_addons_path": module_dir_path_new_version,
                                    "module_name": module_name,
                                    "source_version_odoo": next_version - 1,
                                    "target_version_odoo": next_version,
                                }
                                # TODO move this into config
                                lst_module_to_migrate.append(
                                    dct_module_to_migrate_module
                                )

                    self.dct_progression[
                        "config_state_4_module_to_migrate_code"
                    ][index] = lst_module_to_migrate
                    self.write_config()

                    self.switch_odoo(next_version)
                    # TODO auto-fix
                    # TODO try to migrate module, find in previous version, application la migration vers une nouvelle version
                    # TODO ajouté menu todo qui permet de faire une migration d'un module et migrer le générateur de code.
                    # TODO when check module, reminder provenance
                    # TODO implement asyncio instead of parallel
                    # TODO detect when duplicate path module ou module manquant, prendre décision qui ont efface si dupliqué
                    # TODO pourquoi web_ir_actions_act_multi est doublé dans odoo 13

                lst_module_search_missing_module[index] = True
                self.dct_progression["state_4_search_missing_module"] = (
                    lst_module_search_missing_module
                )
                self.write_config()
            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Migrate module"
            self.add_comment_progression(msg)

            if not lst_module_migrate_odoo[index]:
                # TODO Searching module
                #  search addons/addons
                #  search read manifest and detect branch difference, manifest into private?
                #  Extract module name and run migration to another list
                #  Maybe check if already exist and show list or continue with overwrite
                #  Expliquer pourquoi on ne fait pas le oca-port, c'est

                config_migrate_repo = self.dct_progression.get(
                    "config_migrate_repo", False
                )
                self.dct_progression["config_migrate_repo"] = (
                    config_migrate_repo
                )

                if config_migrate_repo:
                    dct_module_result = self.search_module_to_move(
                        next_version - 1, next_version
                    )

                    # TODO code migration
                    #  git stash
                    #  call odoo-module-migrate, without commit

                    source_module_path = dct_module_result.get(
                        "source_module_path"
                    )
                    if not source_module_path:
                        _logger.error(
                            f"Missing source module path '{source_module_path}'"
                        )
                    else:
                        if os.path.exists(
                            os.path.join(source_module_path, ".git")
                        ):
                            self.todo_upgrade_execute(
                                f"cd '{source_module_path}' && git stash && cd -"
                            )

                    target_module_path = dct_module_result.get(
                        "target_module_path"
                    )
                    if not target_module_path:
                        _logger.error(
                            f"Missing target module path '{target_module_path}'"
                        )
                    else:
                        if os.path.exists(
                            os.path.join(target_module_path, ".git")
                        ):
                            self.todo_upgrade_execute(
                                f"cd '{target_module_path}' && git stash && cd -"
                            )

                    lst_module_to_migrate_all = dct_module_result.get(
                        "lst_module", []
                    )
                else:
                    lst_module_to_migrate_all = []

                self.install_OCA_odoo_module_migrator()

                # TODO remove duplicate au lieu d'extend
                lst_module_to_migrate_all.extend(lst_module_to_migrate)

                lst_path_git_clone_migrate = []

                has_cmd = False
                cmd_parallel = "parallel :::"
                for dct_module in lst_module_to_migrate_all:
                    target_addons_path = dct_module.get("target_addons_path")
                    source_addons_path = dct_module.get("source_addons_path")
                    module_name = dct_module.get("module_name")
                    source_version_odoo = (
                        f'{dct_module.get("source_version_odoo")}.0'
                    )
                    target_version_odoo = (
                        f'{dct_module.get("target_version_odoo")}.0'
                    )
                    source_module_path_to_copy = dct_module.get(
                        "source_module_path"
                    )
                    # Prepare git environment for target
                    if target_addons_path not in lst_path_git_clone_migrate:
                        lst_path_git_clone_migrate.append(target_addons_path)
                        self.check_and_clone_source_to_target_migration_code(
                            next_version,
                            source_addons_path,
                            target_addons_path,
                        )

                    cmd_migration = (
                        f"echo 'odoo_module_migrate {module_name}' && "
                        f"cp -r {source_module_path_to_copy} {target_addons_path} && "
                        f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && "
                        f"python -m odoo_module_migrate --directory {target_addons_path} --modules {module_name} "
                        f"--init-version-name {source_version_odoo} --target-version-name {target_version_odoo} "
                        f"--no-commit && cd - "
                        # f"cp -r {source_module_path_to_copy} {target_module_path_to_copy} && "
                        # f"cd {target_module_path_to_copy} && git commit -am '[MIG] {module_name}: Migration to {target_version_odoo}' && cd -"
                    )
                    cmd_parallel += f' "{cmd_migration}"'
                    has_cmd = True

                if lst_module_to_migrate_all:
                    if has_cmd:
                        self.todo_upgrade_execute(cmd_parallel)
                        print("List of path with migrate code :")
                        print(lst_path_git_clone_migrate)
                        input("💬 Check migration code, press to continue : ")

                    # source_module_path = dct_module_result.get(
                    #     "source_module_path"
                    # )
                    # if not source_module_path:
                    #     _logger.error(
                    #         f"Missing source module path '{source_module_path}'"
                    #     )
                    # else:
                    #     if os.path.exists(
                    #         os.path.join(source_module_path, ".git")
                    #     ):
                    #         self.todo_upgrade_execute(
                    #             f"cd '{source_module_path}' && git stash && cd -",
                    #         )
                    #
                    # target_module_path = dct_module_result.get(
                    #     "target_module_path"
                    # )
                    # if not target_module_path:
                    #     _logger.error(
                    #         f"Missing target module path '{target_module_path}'"
                    #     )
                    # else:
                    #     # TODO check if has file to commit
                    #     self.todo_upgrade_execute(
                    #         f"cd '{target_module_path}' && git commit -am '[MIG] {len(lst_module_to_migrate_all)} modules: Migration to {next_version}' && cd -",
                    #     )

                # TODO copie to next odoo version
                #  do commit and continue
                #  continue migration to loop

                if next_version == 17:
                    status = input(
                        f"💬 Please validate repo is ready to run upgrade views_migration_17, press to continue : "
                    ).strip()
                    # Apply modification with views_migration_17
                    has_cmd = False
                    cmd_serial = ""
                    cmd_parallel = "parallel :::"
                    for dct_module in lst_module_to_migrate_all:
                        database_migration_17_name = (
                            f"migration_odoo_{next_version}_{str(uuid4())[:6]}"
                        )
                        module_name = dct_module.get("module_name")
                        cmd_migration = (
                            f"echo 'views_migration_17 {module_name}' && "
                            f"./run.sh -d {database_migration_17_name} -i {module_name} --load=base,web,views_migration_17 --dev upgrade --no-http --stop-after-init"
                        )
                        cmd_parallel += f' "{cmd_migration}"'
                        cmd_serial += f"{cmd_migration};"
                        has_cmd = True

                    if has_cmd:
                        # self.todo_upgrade_execute(
                        #     cmd_serial
                        # )
                        self.todo_upgrade_execute(cmd_parallel)
                        print("List of module with migration 17 :")
                        print(lst_module_to_migrate_all)
                        input(
                            "💬 Check migration 17 code, press to continue : "
                        )

                lst_module_migrate_odoo[index] = True
                self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                    lst_module_migrate_odoo
                )
                self.write_config()

                print(f"✅ -> Module upgrade Odoo{next_version} done")
            else:
                print(f"✅ -> Module upgrade Odoo{next_version} - nothing")

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Fix migrate code"
            self.add_comment_progression(msg)

            if not lst_fix_migration_odoo[index]:
                print("")
                file_path_fix_migration = os.path.join(
                    "script",
                    "odoo",
                    "migration",
                    f"fix_migration_odoo{(next_version-1)*10}_to_odoo{next_version*10}.py",
                )
                if os.path.exists(file_path_fix_migration):
                    self.todo_upgrade_execute(
                        f"cat ./{file_path_fix_migration} | ./odoo{next_version}.0/odoo/odoo-bin shell -d {database_name_upgrade}",
                        single_source_odoo=True,
                    )

                    lst_fix_migration_odoo[index] = file_path_fix_migration
                    self.dct_progression["state_4_fix_migration_odoo_lst"] = (
                        lst_fix_migration_odoo
                    )
                    self.write_config()
                    print(f"✅ -> Fix migration Odoo{next_version} done")
                else:
                    print(
                        f"✅ -> Fix migration Odoo{next_version} - no fix to execute"
                    )
            else:
                print(f"✅ -> Fix migration Odoo{next_version} - nothing")

            option_comment += 1
            msg = f"4.{index}.{chr(option_comment + 65)} - Migrate database"
            self.add_comment_progression(msg)

            if not lst_upgrade_odoo[index]:
                path_addons_openupgrade = os.path.join(
                    os.getcwd(), f"odoo{next_version}.0", "OCA_OpenUpgrade"
                )

                # Update config with OCA_OpenUpgrade
                ignore_path = (
                    "--ignore-odoo-path " if next_version <= 13 else ""
                )
                extra_addons_path_extra = (
                    f",{path_addons_openupgrade}/addons,{path_addons_openupgrade}/odoo/addons"
                    if next_version <= 13
                    else ""
                )
                cmd_update_config = (
                    f"./script/git/git_repo_update_group.py {ignore_path}"
                    f"--extra-addons-path {path_addons_openupgrade}{extra_addons_path_extra} "
                    f"&& ./script/generate_config.sh"
                )
                self.todo_upgrade_execute(cmd_update_config)

                print("🚸 Please, validate commits after code migration.")
                print("ℹ To show repo status :\nmake repo_show_status")
                print(
                    f"🚸 Please, validate this path into config.conf : '{path_addons_openupgrade}'."
                )
                status = input(f"💬 Press to continue {msg} : ").strip()
                # The technique change at version 14
                if next_version <= 13:
                    erplibre_version = self.install_OCA_openupgrade(
                        next_version
                    )
                    cmd_upgrade = f".venv.{erplibre_version}/bin/python ./odoo{next_version}.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --update all --no-http --stop-after-init -d {database_name_upgrade}"
                else:
                    cmd_upgrade = f"./run.sh --upgrade-path=./odoo{next_version}.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all -c config.conf --stop-after-init --no-http --load=base,web,openupgrade_framework -d {database_name_upgrade}"
                lst_upgrade_odoo[index] = cmd_upgrade

                self.todo_upgrade_execute(
                    cmd_upgrade,
                    new_env={
                        "OPENUPGRADE_TARGET_VERSION": f"{next_version}.0"
                    },
                )
                # TODO detect error

                self.dct_progression["state_4_upgrade_odoo_lst"] = (
                    lst_upgrade_odoo
                )
                self.write_config()

                str_wait_next_version = (
                    " (or wait next version)"
                    if next_version != lst_next_version[-1]
                    else ""
                )

                status = (
                    input(
                        f"💬 Do you want to upgrade all{str_wait_next_version}? Press y/Y to upgrade all addons database : "
                    )
                    .strip()
                    .lower()
                )

                if status == "y":
                    self.todo_upgrade_execute(
                        f"./script/addons/update_addons_all.sh {database_name_upgrade}",
                    )

                print(f"✅ -> Database upgrade Odoo{next_version} done")

                # Update config without OCA_OpenUpgrade
                cmd_update_config = f"./script/git/git_repo_update_group.py && ./script/generate_config.sh"
                self.todo_upgrade_execute(cmd_update_config)
                print("[y] Open server with Selenium")
                status = (
                    input(
                        "💬 Do you want to test this upgrade? Choose or press to ignore it : "
                    )
                    .strip()
                    .lower()
                )
                "make repo_show_status"
                if status == "y":
                    self.todo.prompt_execute_selenium_and_run_db(
                        database_name_upgrade
                    )
                    status = input(
                        f"💬 Press to continue 4.{index} : "
                    ).strip()
            else:
                print(f"✅ -> Database upgrade Odoo{next_version} - nothing")

        #
        # waiting_input = input("💬 Press any keyboard key to continue...")
        print("")

        msg = "5 - Cleaning up database after upgrade"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        print(
            "✨ Re-update i18n, purger data, tables (except mail_test and mail_test_full)"
        )
        # waiting_input = input("💬print Press any keyboard key to continue...")
        msg = "6 - Migration finished"
        print(f"🔷 {msg}")
        self.add_comment_progression(msg)

        cmd_backup_template = f"./odoo_bin.sh db --backup --database {database_name_upgrade} --restore_image"
        cmd_backup = f"{cmd_backup_template} {database_name_upgrade}_finish_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"✨ Can execute backup creation :\n{cmd_backup}")
        status = input(
            "💬 Press y/Y or write filename.zip to export or enter to continue : "
        ).strip()
        if status.lower():
            if status.lower() != "y":
                cmd_backup = f"{cmd_backup_template} {status}"
            self.todo_upgrade_execute(cmd_backup)

        status = input("💬 Test the migration, press y/Y : ")
        if status.lower().strip() == "y":
            self.todo.prompt_execute_selenium_and_run_db(database_name_upgrade)

    def get_rename_module(self, lst_module, next_version):
        path_search = f"odoo{next_version}.0/OCA_OpenUpgrade/"
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            f"find {path_search} -name apriori.py",
            get_output=True,
        )

        if not lst_output:
            _logger.error(
                f"Cannot find renamed module script apriori.py into path '{path_search}'"
            )
            return lst_module
        apriory_py = lst_output[0].strip()

        with open(apriory_py, "r") as f:
            file_content = f.read()

        data_vars = {}
        exec(file_content, data_vars)
        renamed_modules = data_vars.get("renamed_modules", {})
        merged_modules = data_vars.get("merged_modules", {})
        deleted_modules = data_vars.get("deleted_modules", [])

        lst_index_to_delete = []
        for index, module in enumerate(lst_module):
            renamed_module = renamed_modules.get(module)
            merged_module = merged_modules.get(module)
            if renamed_module:
                lst_module[index] = renamed_module
            if merged_module:
                lst_module[index] = merged_module
            if module in deleted_modules:
                lst_index_to_delete.append(index)
        for index_to_delete in lst_index_to_delete[::-1]:
            lst_module.pop(index_to_delete)
        return list(set(lst_module))

    def search_module_to_move(self, source_version_odoo, target_version_odoo):
        lst_module = []
        # lst_path_to_check = [
        #     os.path.join(f"odoo{actual_version_odoo}", "addons"),
        #     os.path.join(f"odoo{target_version_odoo}", "addons"),
        #     os.path.join(f"private", "addons"),
        # ]
        source_path_to_check = os.path.join(
            f"odoo{source_version_odoo}.0", "addons", "addons"
        )
        target_path_to_check = os.path.join(
            f"odoo{target_version_odoo}.0", "addons", "addons"
        )

        # Search
        is_moving_git = False
        if os.path.exists(source_path_to_check):
            if os.path.exists(os.path.join(source_path_to_check, ".git")):
                is_moving_git = True
            if not os.path.exists(target_path_to_check):
                shutil.copytree(source_path_to_check, target_path_to_check)
                # if not is_moving_git:
                #     os.mkdir(path_to_check_target)
                # else:
                #     # TODO clone
                #     pass

            if not is_moving_git:
                # TODO do something
                # Time to compare
                os.listdir(source_path_to_check)

        if os.path.exists(target_path_to_check):
            for dir_name in os.listdir(target_path_to_check):
                source_module_path = os.path.join(
                    source_path_to_check, dir_name
                )
                source_manifest_path = os.path.join(
                    source_module_path, "__manifest__.py"
                )

                target_module_path = os.path.join(
                    target_path_to_check, dir_name
                )
                target_manifest_path = os.path.join(
                    target_module_path, "__manifest__.py"
                )
                if os.path.exists(target_manifest_path):
                    # TODO remove from list when module already exist in version 15
                    dct_module = {
                        "source_module_path": source_module_path,
                        "source_manifest_path": source_manifest_path,
                        "source_addons_path": source_path_to_check,
                        "target_module_path": target_module_path,
                        "target_manifest_path": target_manifest_path,
                        "target_addons_path": target_path_to_check,
                        "module_name": dir_name,
                        "source_version_odoo": source_version_odoo,
                        "target_version_odoo": target_version_odoo,
                    }
                    lst_module.append(dct_module)

        dct_module = {
            "lst_module": lst_module,
            "source_module_path": source_path_to_check,
            "target_module_path": target_path_to_check,
        }
        return dct_module

    def uninstall_from_database(
        self, lst_module_to_uninstall, database_name, actual_version
    ):
        if not lst_module_to_uninstall:
            return
        uninstall_module = ",".join(lst_module_to_uninstall)
        self.todo_upgrade_execute(
            f"./script/addons/uninstall_addons.sh {database_name} {uninstall_module}",
            single_source_odoo=True,
        )

        # Update list installed module
        self.dct_module_per_version[actual_version] = sorted(
            list(
                set(self.dct_module_per_version[actual_version])
                - set(lst_module_to_uninstall)
            )
        )
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.write_config()

    def install_from_database(
        self, lst_module_to_install, database_name, actual_version
    ):
        if not lst_module_to_install:
            return
        install_module = ",".join(lst_module_to_install)
        self.todo_upgrade_execute(
            f"./script/addons/install_addons.sh {database_name} {install_module}",
            single_source_odoo=True,
        )

        # Update list installed module
        self.dct_module_per_version[actual_version] = sorted(
            list(
                set(
                    self.dct_module_per_version[actual_version]
                    + lst_module_to_install
                )
            )
        )
        self.dct_progression["dct_module_per_version"] = (
            self.dct_module_per_version
        )
        self.write_config()

    def check_addons_exist(
        self, lst_module_to_check, ignore_error=True, get_all_info=False
    ):
        str_module_to_check = ",".join(lst_module_to_check)
        status, cmd_executed, dct_output = self.todo_upgrade_execute(
            f"{PYTHON_BIN} ./script/addons/check_addons_exist.py --format_json --output_json -m {str_module_to_check}",
            get_output=True,
            output_is_json=True,
            wait_at_error=not ignore_error,
        )

        lst_module_missing = dct_output.get("missing")
        lst_module_duplicate = dct_output.get("duplicate")
        if get_all_info:
            lst_module_error = dct_output.get("error")
            lst_module_exist = dct_output.get("exist")
            return (
                lst_module_missing,
                lst_module_duplicate,
                lst_module_exist,
                lst_module_error,
            )

        return lst_module_missing, lst_module_duplicate

    def switch_odoo(self, odoo_version):
        int_odoo_version = int(float(odoo_version))

        # Expect odoo_version like 12.0
        lst_version, lst_version_installed, odoo_installed_version = (
            self.todo.get_odoo_version()
        )
        if odoo_installed_version != f"odoo{int_odoo_version}.0":
            print(
                f"⧖ -> Was '{odoo_installed_version}', Switch to odoo{int_odoo_version}.0"
            )
            self.todo_upgrade_execute(f"make switch_odoo_{int_odoo_version}")
            self.todo_upgrade_execute("make config_gen_all")

    def install_OCA_odoo_module_migrator(self):
        if not os.path.exists(PATH_VENV_MODULE_MIGRATOR):
            self.todo_upgrade_execute(
                f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && python -m venv {VENV_NAME_MODULE_MIGRATOR} && source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && pip3 install -r requirements.txt"
            )

    def install_OCA_openupgrade(self, next_version):
        # TODO install odoorpc==0.7.0
        # openupgradelib
        # openupgrade_path = f"odoo{next_version}.0/OCA_OpenUpgrade"
        # venv_oca_path = f"{openupgrade_path}/.venv"
        # if os.path.exists(venv_oca_path):
        #     return
        lst_version, lst_version_installed, odoo_installed_version = (
            self.todo.get_odoo_version()
        )
        extract_version = f"{next_version}.0"
        dct_erplibre_info = [
            a for a in lst_version if a.get("odoo_version") == extract_version
        ]
        if not dct_erplibre_info:
            raise Exception(f"Cannot extract {extract_version}")
        dct_erplibre_info = dct_erplibre_info[0]
        erplibre_version = dct_erplibre_info.get("erplibre_version")
        # self.todo_upgrade_execute(
        #     f".venv.{erplibre_version}/bin/python -m venv {venv_oca_path} && {venv_oca_path}/bin/pip3 install -r {openupgrade_path}/requirements.txt"
        # )
        self.todo_upgrade_execute(
            f".venv.{erplibre_version}/bin/pip install odoorpc==0.7.0"
        )
        self.todo_upgrade_execute(
            f".venv.{erplibre_version}/bin/pip install openupgradelib"
        )
        return erplibre_version

    def todo_upgrade_execute(
        self,
        cmd,
        single_source_odoo=False,
        new_env=None,
        quiet=False,
        get_output=False,
        output_is_json=False,
        wait_at_error=True,
    ):
        if output_is_json and not get_output:
            get_output = True
        output = None
        if get_output:
            status, cmd_executed, output = self.todo.executer_commande_live(
                cmd,
                source_erplibre=False,
                single_source_odoo=single_source_odoo,
                new_env=new_env,
                return_status_and_output_and_command=True,
                quiet=quiet,
            )
        else:
            status, cmd_executed = self.todo.executer_commande_live(
                cmd,
                source_erplibre=False,
                single_source_odoo=single_source_odoo,
                new_env=new_env,
                return_status_and_command=True,
                quiet=quiet,
            )
        self.lst_command_executed.append(cmd_executed)
        self.dct_progression["command_executed"] = self.lst_command_executed
        self.write_config()
        if status and wait_at_error:
            input(
                "💬 Error detected, press to continue or ctrl+c to stop : "
            ).strip()

        if get_output:
            if output_is_json:
                str_output = json.loads("".join(output))
                return status, cmd_executed, str_output
            return status, cmd_executed, output
        return status, cmd_executed

    def check_and_clone_source_to_target_migration_code(
        self, next_version, source_addons_path, target_addons_path
    ):
        if not os.path.exists(os.path.join(source_addons_path, ".git")):
            return
        if os.path.exists(os.path.join(target_addons_path, ".git")):
            return
        source_dir_name = os.path.basename(source_addons_path)
        # Clone a project for next version
        # Get actual branch
        cmd_git_clone_migrate_source = (
            f"cd {source_addons_path} && git branch --show-current && cd -"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source,
            get_output=True,
        )
        branch_source = lst_output[0].strip()
        branch_target = branch_source.replace(
            str(next_version - 1), str(next_version)
        )

        # Get remote branch for actual version
        cmd_git_clone_migrate_source_same_target = (
            f"cd {source_addons_path} "
            f"&& git fetch --all "
            f'&& git branch -vv | grep "{branch_source}" '
            f"&& cd -"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source_same_target,
            get_output=True,
        )
        local_branch, remote, remote_branch = (
            self.get_local_branch_remote_actual_branch_git(lst_output)
        )
        # Get remote branch for next version
        remote_branch_target = f"{remote}/{branch_target}"
        cmd_git_clone_migrate_source_same_target = (
            f"cd {source_addons_path} "
            f"&& git fetch --all "
            f'&& git branch --remotes -vv | grep "{remote_branch_target} " '
            f"&& cd -"
        )
        status, cmd_executed, lst_output = self.todo_upgrade_execute(
            cmd_git_clone_migrate_source_same_target,
            get_output=True,
        )
        has_remote_to_clone = any([a.strip() for a in lst_output])

        # TODO check config if path is added
        if has_remote_to_clone:
            # Get remote branch address
            cmd_remote_address = (
                f"cd {source_addons_path} "
                f"&& git remote get-url {remote} "
                f"&& cd -"
            )
            status, cmd_executed, lst_output = self.todo_upgrade_execute(
                cmd_remote_address,
                get_output=True,
            )

            remote_address = lst_output[0].strip()

            # TODO some time, the clone has error, need to repeat
            cmd_git_clone = (
                f"cd {os.path.dirname(target_addons_path)} "
                f"&& git clone {remote_address} {source_dir_name} -b {branch_target} && cd -"
            )
            status, cmd_executed, lst_output = self.todo_upgrade_execute(
                cmd_git_clone,
                get_output=True,
            )
        else:
            cmd_mkdir = f"mkdir -p {target_addons_path}"
            status, cmd_executed, lst_output = self.todo_upgrade_execute(
                cmd_mkdir,
                get_output=True,
            )

    def get_local_branch_remote_actual_branch_git(self, lst_output):
        for line in lst_output:
            # The current branch is marked with an asterisk (*) at the start of the line
            if not line.strip().startswith("*"):
                continue
            # Split the line to isolate the remote and remote branch name
            parts = line.split()
            if len(parts) >= 4:
                # The remote and remote branch are in the 4th part, e.g., '[origin/main]'
                remote_info = parts[3].strip("[]")
                # Split 'origin/main' into 'origin' and 'main'
                remote, remote_branch = remote_info.split("/", 1)
                return parts[1], remote, remote_branch
        return None, None, None

    def add_comment_progression(self, comment):
        comment_to_add = f"# {comment}"
        self.lst_command_executed.append(comment_to_add)
        self.dct_progression["command_executed"] = self.lst_command_executed
        self.write_config()
