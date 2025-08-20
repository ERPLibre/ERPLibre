#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import logging
import os
import shutil
import zipfile

import click
import todo_file_browser

_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv.erplibre/bin/python3"
UPGRADE_CONFIG_LOG = ".venv.erplibre/odoo_migration_log.json"
VENV_NAME_MODULE_MIGRATOR = ".venv.odoo_module_migrator"
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


class TodoUpgrade:
    def __init__(self, todo):
        self.file_path = None
        self.todo = todo
        self.dct_progression = {}

    def write_config(self):
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
        lst_command_executed = []

        if os.path.exists(UPGRADE_CONFIG_LOG):
            erase_progression_input = input(
                "💬 Detected migration, would you like to erase progression for a new migration (y/Y) or continue it (anything) : "
            )
            if erase_progression_input.strip().lower() not in ["y", "yes"]:
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
                "💬 Give the path of file, or empty to use a File Browser : "
            )
            if not self.file_path.strip():
                self.file_path = None
            if not self.file_path:
                initial_dir = os.getcwd()
                file_browser = todo_file_browser.FileBrowser(
                    initial_dir, self.on_file_selected
                )
                file_browser.run_main_frame()

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
        # TODO need support minor version, example 18.2, the .2 (no need for OCE OCB)

        print("✨ Show documentation version :")
        # TODO Generate it locally and show it if asked

        for next_version in range_version:
            print(
                f"https://oca.github.io/OpenUpgrade/coverage_analysis/modules{next_version*10}-{(next_version+1)*10}.html"
            )

        # ⚠️ ℹ 💬 ❗ 🔷 ✨ 🟦 🔹 🔵 ⟳ ⧖ ⚙ ✔ ✅ ❌ ⏵ ⏸ ⏹ ◆ ◇ … ➤ ⚑ ★ ☆ ☰ ⬍ ⍟ ⊗ ⌘ ⏻ ⍰
        print("🔷0- Inspect zip")
        print("✅ -> Search odoo version")
        print("✅ -> Find good environment, read the .zip file")
        filename_odoo_version = ".odoo-version"

        is_state_4_reach_open_upgrade = self.dct_progression.get(
            "state_4_reach_open_upgrade"
        )
        if not is_state_4_reach_open_upgrade and os.path.exists(
            filename_odoo_version
        ):
            with open(filename_odoo_version, "r") as f:
                actual_odoo_version = f.readline().strip()
            # TODO and don't switch if ready to upgrade (after first duplicate BD)
            if actual_odoo_version != odoo_actual_version:
                print(
                    f"⧖ -> Was odoo'{actual_odoo_version}', Switch to odoo.'{odoo_actual_version}'"
                )
                major_odoo_actual_version = int(float(odoo_actual_version))
                self.todo_upgrade_execute(
                    f"make switch_odoo_{major_odoo_actual_version}",
                    lst_command_executed,
                )
                self.todo_upgrade_execute(
                    f"make config_gen_all", lst_command_executed
                )
        if not self.dct_progression.get("state_0_install_odoo"):
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
                    f"make install_odoo_{iter_range_version}",
                    lst_command_executed,
                )
                if not status:
                    # TODO print why not working
                    want_continue = input(
                        f"💬 Error at installing '{odoo_version_to_install}', would you like to continue (y/Y) : "
                    )
                    if want_continue.strip().lower() != "y":
                        return

                if not os.path.isfile(filename_odoo_version):
                    print(
                        "⚠️ You need an installed system before continue, check your Odoo installation."
                    )
                    return

        self.dct_progression["state_0_install_odoo"] = True
        self.write_config()

        if not self.dct_progression.get("state_0_switch_odoo"):
            print(f"⧖ -> Switch to odoo.'{odoo_actual_version}'")
            self.todo_upgrade_execute(
                f"make switch_odoo_{start_version}", lst_command_executed
            )
            self.dct_progression["state_0_switch_odoo"] = True
            self.write_config()

        print("✅ -> Install environment if missing")
        # TODO + afficher information du reach

        if not self.dct_progression.get("state_0_search_missing_module"):
            dct_bd_modules = json_manifest_file_1.get("modules")
            lst_module_missing = []
            # TODO support async and not parallel
            for bd_module in dct_bd_modules.keys():
                status, cmd_executed = self.todo_upgrade_execute(
                    f"{PYTHON_BIN} ./script/addons/check_addons_exist.py -m {bd_module}",
                    lst_command_executed,
                )

                if status:
                    lst_module_missing.append(bd_module)

            self.dct_progression["len_lst_module_missing"] = len(
                lst_module_missing
            )
            self.dct_progression["lst_module_missing"] = lst_module_missing
            self.write_config()
            if lst_module_missing:
                print(lst_module_missing)
                want_continue = input(
                    "💬 Detect error, do you want to continue? (Y/N): "
                )
                if want_continue.strip().lower() != "y":
                    return

            self.dct_progression["state_0_search_missing_module"] = True
            self.write_config()

        print("✅ -> Search missing module")

        print(
            "❌ -> Install missing module, do a research or ask to uninstall it (can break data)"
        )

        print("🔷1- Import database from zip")

        database_name = self.dct_progression.get("database_name")
        if not database_name:
            database_name = (
                input(
                    "💬 With database name do you want to work with? Default (test) : "
                ).strip()
                or "test"
            )
            self.dct_progression["database_name"] = database_name
            self.write_config()

        print(f"★ Work with database '{database_name}'")

        if not self.dct_progression.get("state_1_restore_database"):
            # TODO move self.file_path to image_db if not already here and get only the filename
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

            self.todo_upgrade_execute(
                f"./script/database/db_restore.py --database {database_name} --image {file_name} --ignore_cache",
                lst_command_executed,
                single_source_odoo=True,
            )

            if not status:
                self.dct_progression["state_1_restore_database"] = True
                self.write_config()
            else:
                return

        print("✅ -> Restore database")

        if not self.dct_progression.get("state_1_neutralize_database"):
            self.todo_upgrade_execute(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                lst_command_executed,
                single_source_odoo=True,
            )

            if not status:
                self.dct_progression["state_1_neutralize_database"] = True
                self.write_config()
            else:
                return

        print("✅ -> Neutralize database")

        config_state_1_uninstall_module = self.dct_progression.get(
            "config_state_1_uninstall_module"
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
                uninstall_module = ",".join(lst_module_to_uninstall)
                self.todo_upgrade_execute(
                    f"./script/addons/uninstall_addons.sh {database_name} {uninstall_module}",
                    lst_command_executed,
                    single_source_odoo=True,
                )
                self.dct_progression["state_1_uninstall_module"] = True

        self.dct_progression["config_state_1_uninstall_module"] = (
            config_state_1_uninstall_module
        )
        self.write_config()

        print("✅ -> Uninstall module")

        print("🔷2- Succeed update all addons")

        if not self.dct_progression.get("state_2_update_all"):
            self.todo_upgrade_execute(
                f"./script/addons/update_addons_all.sh {database_name}",
                lst_command_executed,
                single_source_odoo=True,
            )

            if not status:
                self.dct_progression["state_2_update_all"] = True
                self.write_config()
            else:
                return

        print("🔷3- Clean up database before data migration")

        if not self.dct_progression.get("state_3_install_clean_database"):
            self.todo_upgrade_execute(
                f"./script/addons/install_addons.sh {database_name} database_cleanup",
                lst_command_executed,
                single_source_odoo=True,
            )

            if not status:
                self.dct_progression["state_3_install_clean_database"] = True
                self.write_config()
            else:
                return

        if not self.dct_progression.get("state_3_clean_database"):
            print(
                "✨ Aller dans «configuration/Technique/Nettoyage.../Purger» les modules obsolètes"
            )
            status = input(
                "💬 Did you finish to clean database (y/Y) : "
            ).strip()
            if status.lower() != "y":
                return

            self.dct_progression["state_3_clean_database"] = True
            self.write_config()

        print("🔷4- Upgrade version with OpenUpgrade")
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
        for index, next_version in enumerate(lst_next_version):
            if not database_name_upgrade:
                last_database_name = database_name
            else:
                last_database_name = database_name_upgrade
            database_name_upgrade = lst_database_name_upgrade[index]

            if not lst_clone_odoo[index]:
                print(
                    f"⧖ -> Clone to odoo.'{next_version}', from '{database_name}' to '{database_name_upgrade}'."
                )
                # Delete if exist database
                self.todo_upgrade_execute(
                    f"./script/database/db_restore.py -d {database_name_upgrade} --only_drop",
                    lst_command_executed,
                )

                # Duplicate database
                cmd_clone_database = f"./odoo_bin.sh db --clone --from_database {last_database_name} --database {database_name_upgrade}"
                self.todo_upgrade_execute(
                    cmd_clone_database, lst_command_executed
                )

                lst_clone_odoo[index] = True
                self.dct_progression["state_4_clone_odoo_lst"] = lst_clone_odoo
                self.write_config()
                print(f"✅ -> Clone Odoo{next_version} done")
            else:
                print(f"✅ -> Clone Odoo{next_version} - nothing")

            if not lst_switch_odoo[index]:
                print(f"⧖ -> Switch to odoo.'{next_version}'")
                self.todo_upgrade_execute(
                    f"make switch_odoo_{next_version}", lst_command_executed
                )

                lst_switch_odoo[index] = True
                self.dct_progression["state_4_switch_odoo_lst"] = (
                    lst_switch_odoo
                )
                self.write_config()
                print(f"✅ -> Switch Odoo{next_version} done with update")
            else:
                print(f"✅ -> Switch Odoo{next_version} - nothing")

            if not lst_module_migrate_odoo[index]:
                # TODO Searching module
                #  search addons/addons
                #  search read manifest and detect branch difference, manifest into private?
                #  Extract module name and run migration to another list
                #  Maybe check if already exist and show list or continue with overwrite
                #  Expliquer pourquoi on ne fait pas le oca-port, c'est

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
                    self.todo_upgrade_execute(
                        f"cd '{source_module_path}' && git stash && cd -",
                        lst_command_executed,
                    )

                target_module_path = dct_module_result.get(
                    "target_module_path"
                )
                if not target_module_path:
                    _logger.error(
                        f"Missing target module path '{target_module_path}'"
                    )
                else:
                    self.todo_upgrade_execute(
                        f"cd '{target_module_path}' && git stash && cd -",
                        lst_command_executed,
                    )

                self.install_OCA_odoo_module_migrator(lst_command_executed)

                has_cmd = False
                cmd_parallel = "parallel :::"
                lst_module_to_migrate = dct_module_result.get("lst_module")
                for dct_module in lst_module_to_migrate:
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
                    target_module_path_to_copy = dct_module.get(
                        "target_addons_path"
                    )
                    cmd_migration = (
                        f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && "
                        f"python -m odoo_module_migrate --directory {len(LST_PATH_OCA_ODOO_MODULE_MIGRATOR) * '../'}{source_addons_path} --modules {module_name} "
                        f"--init-version-name {source_version_odoo} --target-version-name {target_version_odoo} "
                        f"--no-commit && cd - && "
                        f"cp -r {source_module_path_to_copy} {target_module_path_to_copy}"
                        # f"cp -r {source_module_path_to_copy} {target_module_path_to_copy} && "
                        # f"cd {target_module_path_to_copy} && git commit -am '[MIG] {module_name}: Migration to {target_version_odoo}' && cd -"
                    )
                    cmd_parallel += f' "{cmd_migration}"'
                    has_cmd = True

                if has_cmd:
                    self.todo_upgrade_execute(
                        cmd_parallel, lst_command_executed
                    )

                source_module_path = dct_module_result.get(
                    "source_module_path"
                )
                if not source_module_path:
                    _logger.error(
                        f"Missing source module path '{source_module_path}'"
                    )
                else:
                    self.todo_upgrade_execute(
                        f"cd '{source_module_path}' && git stash && cd -",
                        lst_command_executed,
                    )

                target_module_path = dct_module_result.get(
                    "target_module_path"
                )
                if not target_module_path:
                    _logger.error(
                        f"Missing target module path '{target_module_path}'"
                    )
                else:
                    # TODO check if has file to commit
                    self.todo_upgrade_execute(
                        f"cd '{target_module_path}' && git commit -am '[MIG] {len(lst_module_to_migrate)} modules: Migration to {next_version}' && cd -",
                        lst_command_executed,
                    )

                #
                # TODO copie to next odoo version
                #  do commit and continue
                #  continue migration to loop
                lst_module_migrate_odoo[index] = True
                self.dct_progression["state_4_module_migrate_odoo_lst"] = (
                    lst_module_migrate_odoo
                )
                self.write_config()
                print(f"✅ -> Module upgrade Odoo{next_version} done")
            else:
                print(f"✅ -> Module upgrade Odoo{next_version} - nothing")

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
                        lst_command_executed,
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

            if not lst_upgrade_odoo[index]:
                # The technique change at version 14
                # TODO generate ./config.conf for migration context
                # TODO add path odoo.addons.openupgrade_framework
                # []/odoo15.0/OCA_OpenUpgrade
                path_addons_openupgrade = os.path.join(
                    os.getcwd(), f"odoo{next_version}.0", "OCA_OpenUpgrade"
                )
                print("🚸 Please, validate commits after code migration.")
                status = input(
                    f"💬 A migration bug, please add addons_path into config.conf : '{path_addons_openupgrade}' press to continue : "
                ).strip()
                if next_version <= 13:
                    cmd_upgrade = f"./.venv/bin/python ./odoo{next_version}.0/OCA_OpenUpgrade/odoo-bin -c ./config.conf --update all --stop-after-init -d {database_name_upgrade}"
                else:
                    cmd_upgrade = f"./run.sh --upgrade-path=./odoo{next_version}.0/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all -c config.conf --stop-after-init --load=base,web,openupgrade_framework -d {database_name_upgrade}"
                lst_upgrade_odoo[index] = cmd_upgrade

                self.todo_upgrade_execute(
                    cmd_upgrade,
                    lst_command_executed,
                    new_env={
                        "OPENUPGRADE_TARGET_VERSION": f"{next_version}.0"
                    },
                )

                self.dct_progression["state_4_upgrade_odoo_lst"] = (
                    lst_upgrade_odoo
                )
                self.write_config()
                print(f"✅ -> Database upgrade Odoo{next_version} done")
            else:
                print(f"✅ -> Database upgrade Odoo{next_version} - nothing")

        #
        # waiting_input = input("💬 Press any keyboard key to continue...")
        print("")

        print("🔷5- Cleaning up database after upgrade")
        print(
            "✨ Re-update i18n, purger data, tables (except mail_test and mail_test_full)"
        )
        # waiting_input = input("💬print Press any keyboard key to continue...")
        print("")

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

    def install_OCA_odoo_module_migrator(self, lst_command_executed):
        if not os.path.exists(PATH_VENV_MODULE_MIGRATOR):
            self.todo_upgrade_execute(
                f"cd {PATH_OCA_ODOO_MODULE_MIGRATOR} && python -m venv {VENV_NAME_MODULE_MIGRATOR} && source {VENV_NAME_MODULE_MIGRATOR}/bin/activate && pip3 install -r requirements.txt",
                lst_command_executed,
            )

    def todo_upgrade_execute(
        self,
        cmd,
        lst_command_executed,
        single_source_odoo=False,
        new_env=None,
        quiet=False,
    ):
        status, cmd_executed = self.todo.executer_commande_live(
            cmd,
            source_erplibre=False,
            single_source_odoo=single_source_odoo,
            new_env=new_env,
            return_status_and_command=True,
            quiet=quiet,
        )
        lst_command_executed.append(cmd_executed)
        self.dct_progression["command_executed"] = lst_command_executed
        self.write_config()
        return status, cmd_executed
