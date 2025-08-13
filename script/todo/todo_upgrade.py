#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import logging
import os
import zipfile
import todo_file_browser
import click


_logger = logging.getLogger(__name__)

PYTHON_BIN = ".venv.erplibre/bin/python3"


class TodoUpgrade:
    def __init__(self, todo):
        self.file_path = None
        self.todo = todo

    def on_file_selected(self, file_path):
        self.file_path = file_path
        todo_file_browser.exit_program()

    def execute_odoo_upgrade(self):
        # TODO update dev environment for git project
        # TODO Redeploy new production after upgrade
        # 2 upgrades version = 5 environnement. 0-prod init, 1-dev init, 2-dev01, 3-dev02, 4-prod final
        print("Welcome to Odoo upgrade processus with ERPLibre 🤖")

        
        self.file_path = input(
            "Give the path of file, or empty to use a File Browser : "
        )

        print("")
        print("Select the zip file of you database backup.")

        self.file_path = input(
            "Give the path of file, or empty to use a File Browser : "
        )
        if not self.file_path.strip():
            self.file_path = None
        if not self.file_path:
            initial_dir = os.getcwd()
            file_browser = todo_file_browser.FileBrowser(
                initial_dir, self.on_file_selected
            )
            file_browser.run_main_frame()

        print(f"Open file {self.file_path}")
        with zipfile.ZipFile(self.file_path, "r") as zip_ref:
            manifest_file_1 = zip_ref.open("manifest.json")
        json_manifest_file_1 = json.load(manifest_file_1)
        odoo_actual_version = json_manifest_file_1.get("version")
        print(f"Detect version Odoo CE '{odoo_actual_version}'.")

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

        # lst_odoo_version = [{"prompt_description": "I don't know"}] + [
        #     {"prompt_description": a.get("odoo_version")} for a in lst_version
        # ]
        # help_info = self.fill_help_info(lst_odoo_version)
        # odoo_actual_version = None

        # cmd_no_found = True
        # while cmd_no_found:
        #     status = click.prompt(help_info)
        #     try:
        #         int_cmd = int(status)
        #         if 0 < int_cmd <= len(lst_odoo_version):
        #             cmd_no_found = False
        #             if int_cmd > 1:
        #                 odoo_actual_version = lst_odoo_version[int_cmd - 1].get("prompt_description")
        #     except ValueError:
        #         pass
        #     if cmd_no_found:
        #         print("Commande non trouvée 🤖!")

        print("Which version do you want to upgrade to?")
        odoo_reach_version = None
        cmd_no_found = True
        while cmd_no_found:
            status = click.prompt(help_info)
            try:
                int_cmd = int(status)
                if 0 < int_cmd <= len(lst_odoo_version):
                    cmd_no_found = False
                    odoo_reach_version = lst_odoo_version[int_cmd - 1].get(
                        "prompt_description"
                    )
            except ValueError:
                pass
            if cmd_no_found:
                print("Commande non trouvée 🤖!")

        # Search nb diff to use range
        start_version = int(float(odoo_actual_version))
        end_version = int(float(odoo_reach_version))
        range_version = range(start_version, end_version)
        # TODO need support minor version, example 18.2, the .2

        print("Show documentation version :")
        # TODO Generate it locally and show it if asked

        for i in range_version:
            print(
                f"https://oca.github.io/OpenUpgrade/coverage_analysis/modules{i*10}-{(i+1)*10}.html"
            )
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules120-130.html")
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules130-140.html")
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules140-150.html")
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules150-160.html")
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules160-170.html")
        # print("https://oca.github.io/OpenUpgrade/coverage_analysis/modules170-180.html")
        print("Ask the database in zip file")

        print("0- Inspect zip")
        print("  -> Find good environment, read the .zip file")
        print("  -> Search odoo version")
        print("  -> Install environment if missing")
        print("  -> Search missing module")
        dct_bd_modules = json_manifest_file_1.get("modules")
        lst_module_missing = []
        # TODO can be run in async
        for bd_module in dct_bd_modules.keys():
            status = self.todo.executer_commande_live(
                f"{PYTHON_BIN} ./script/addons/check_addons_exist.py -m {bd_module}",
                source_erplibre=False,
                quiet=True,
            )
            lst_module_missing.append(bd_module)
        if lst_module_missing:
            print(lst_module_missing)
            # TODO save
        print(
            "  -> Install missing module, do a research or ask to uninstall it (can break data)"
        )
        waiting_input = input("Press any keyboard key to continue...")
        print("")

        print("1- Import database from zip")
        print("  -> Neutralize data, maybe with")
        print("./script/addons/update_prod_to_dev.sh BD")
        print("  -> Fix running execution")
        waiting_input = input("Press any keyboard key to continue...")
        print("")

        print("2- Succeed update all addons")
        print("./script/addons/update_addons_all.sh BD")
        print("  -> Fix importation error")
        waiting_input = input("Press any keyboard key to continue...")
        print("")

        print("3- Clean up database before data migration")
        print("./script/addons/addons_install.sh database_cleanup")
        print("  -> Run it manually")
        print(
            "Aller dans «configuration/Technique/Nettoyage.../Purger» les modules obsolètes"
        )
        print("Uninstall no need module to next version.")
        waiting_input = input("Press any keyboard key to continue...")
        print("")

        print("4- Upgrade version with OpenUpgrade")
        # Script odoo 13 and before
        # ./.venv/bin/python ./script/OCA_OpenUpgrade/odoo-bin -c ./config.conf --update all --stop-after-init -d BD
        # Script odoo 14 and after
        # ./run.sh --upgrade-path=./script/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --stop-after-init --load=base,web,openupgrade_framework -d BD
        waiting_input = input("Press any keyboard key to continue...")
        print("")

        print("5- Cleaning up database after upgrade")
        print(
            "Re-update i18n, purger data, tables (except mail_test and mail_test_full)"
        )
        waiting_input = input("Press any keyboard key to continue...")
        print("")

