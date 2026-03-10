#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import getpass
import logging
import os
import zipfile

import click

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

try:
    from script.todo import todo_file_browser
except Exception:
    todo_file_browser = None


class DatabaseManager:
    def __init__(self, execute, fill_help_info) -> None:
        self._execute = execute
        self._fill_help_info = fill_help_info
        self._dir_path: str | None = None

    def _on_dir_selected(self, path: str) -> None:
        self._dir_path = path

    def select_database(self) -> str | bool:
        cmd_server = "./odoo_bin.sh db --list"
        status, databases = self._execute.exec_command_live(
            cmd_server,
            return_status_and_output=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )
        choices = [{"prompt_description": a.strip()} for a in databases]
        help_info = self._fill_help_info(choices)
        valid_choices = [str(a) for a in range(len(choices) + 1) if a]

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status in valid_choices:
                database_name = databases[int(status) - 1].strip()
                print(database_name)
                return database_name
            else:
                print(t("cmd_not_found"))

    def restore_from_database(self, show_remote_list: bool = True) -> None:
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print("[1] By filename from image_db")
        print(f"[] Browser image_db {path_image_db}")
        status = input("\U0001f4ac Select : ")
        if status == "1":
            file_name = status
        else:
            file_name = self.open_file_image_db()

        default_database_name = file_name.replace(" ", "_")
        if default_database_name.endswith(".zip"):
            default_database_name = default_database_name[:-4]

        database_name = input(
            f"\U0001f4ac Database name (default={default_database_name}) : "
        )
        if not database_name:
            database_name = default_database_name

        status = (
            input("\U0001f4ac Would you like to neutralize database (n/N)? ")
            .strip()
            .lower()
        )
        is_neutralize = False
        more_arg = ""
        if status != "n":
            more_arg = "--neutralize "
            is_neutralize = True
            database_name += "_neutralize"
        status, output_lines = self._execute.exec_command_live(
            f"python3 ./script/database/db_restore.py -d {database_name} "
            f"{more_arg}--ignore_cache --image {file_name}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if is_neutralize:
            status, output_lines = self._execute.exec_command_live(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
        status = (
            input("\U0001f4ac Would you like to update all addons (y/Y)? ")
            .strip()
            .lower()
        )
        if status == "y":
            status, output_lines = self._execute.exec_command_live(
                f"./script/addons/update_addons_all.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )

    def create_backup_from_database(
        self, show_remote_list: bool = True
    ) -> None:
        database_name = self.select_database()
        backup_name = input(
            "\U0001f4ac Backup name (default = name+date.zip) : "
        )
        if not backup_name:
            backup_name = (
                database_name
                + "_"
                + datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
                + ".zip"
            )

        if not backup_name.endswith(".zip"):
            backup_name = backup_name + ".zip"

        print(backup_name)

        cmd = (
            f"./odoo_bin.sh db --backup --database {database_name}"
            f" --restore_image {backup_name}"
        )
        status, output_lines = self._execute.exec_command_live(
            cmd,
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )

    def open_file_image_db(self) -> str:
        self._dir_path = ""
        path_image_db = os.path.join(os.getcwd(), "image_db")

        file_browser = todo_file_browser.FileBrowser(
            path_image_db, self._on_dir_selected
        )
        file_browser.run_main_frame()
        file_name = os.path.basename(self._dir_path)
        print(file_name)
        return file_name

    def download_database_backup_cli(
        self, show_remote_list: bool = True
    ) -> tuple[int, str, str]:
        database_domain = input("Domain Odoo (ex. https://mondomain.com) : ")
        if show_remote_list:
            status, output_lines = self._execute.exec_command_live(
                f"python3 ./script/database/list_remote.py --raw"
                f" --odoo-url {database_domain}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            if len(output_lines) > 1:
                for index, output in enumerate(output_lines):
                    print(f"{index + 1} - {output}")
                database_name = input("Select id of database :").strip()
            elif len(output_lines) == 1:
                database_name = output_lines[0].strip()
            else:
                database_name = input(
                    "Cannot read remote database, Database name :\n"
                )
        else:
            database_name = input("Database name :\n")

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
        default_output_path = f"./image_db/{database_name}_{timestamp}.zip"
        output_path = input(
            f"Output path (default: {default_output_path}) : "
        ).strip()
        if not output_path:
            output_path = default_output_path

        master_password = getpass.getpass(prompt="Master password : ")

        cmd = "script/database/download_remote.sh --quiet"
        my_env = os.environ.copy()
        my_env["MASTER_PWD"] = master_password
        my_env["DATABASE_NAME"] = database_name
        my_env["OUTPUT_FILE_PATH"] = output_path
        my_env["ODOO_URL"] = database_domain
        status, cmd_executed = self._execute.exec_command_live(
            cmd,
            source_erplibre=False,
            return_status_and_command=True,
            new_env=my_env,
        )
        try:
            with zipfile.ZipFile(default_output_path, "r") as zip_ref:
                manifest_file_1 = zip_ref.open("manifest.json")
            _logger.info(
                f"Log file '{default_output_path}' is complete"
                " and validated."
            )
        except Exception as e:
            _logger.error(e)
            _logger.error(
                "Failed to read manifest.json from backup file"
                f" '{default_output_path}'."
            )
        return status, output_path, database_name
