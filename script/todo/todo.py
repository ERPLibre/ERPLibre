#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import configparser
import datetime
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.config import config_file
from script.execute import execute
from script.todo.todo_i18n import get_lang, lang_is_configured, set_lang, t

file_error_path = ".erplibre.error.txt"
cst_venv_erplibre = ".venv.erplibre"
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
INSTALLED_ODOO_VERSION_FILE = os.path.join(
    ".repo", "installed_odoo_version.txt"
)
ODOO_VERSION_FILE = ".odoo-version"
ENABLE_CRASH = False
CRASH_E = None
# Support mobile ERPLibre
ANDROID_DIR = "android"
MOBILE_HOME_PATH = "./mobile/erplibre_home_mobile"
STRINGS_FILE = os.path.join(
    MOBILE_HOME_PATH, ANDROID_DIR, "app/src/main/res/values/strings.xml"
)
GRADLE_FILE = os.path.join(MOBILE_HOME_PATH, ANDROID_DIR, "app/build.gradle")


try:
    import tkinter as tk
    from tkinter import filedialog

    import click
    import dotenv
    import humanize
    import openai
    import todo_file_browser

    # import urwid
    # TODO implement rich for beautiful print and table
    # import rich
    import todo_upgrade
    from pykeepass import PyKeePass
except ModuleNotFoundError as e:
    humanize = None
    ENABLE_CRASH = True
    CRASH_E = e

if not ENABLE_CRASH:
    print(t("Importation success!"))

logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)

CONFIG_FILE = "./script/todo/todo.json"
CONFIG_OVERRIDE_FILE = "./private/todo/todo.json"
LOGO_ASCII_FILE = "./script/todo/logo_ascii.txt"


class TODO:
    def __init__(self):
        self.dir_path = None
        self.kdbx = None
        self.file_path = None
        self.config_file = config_file.ConfigFile()
        self.execute = execute.Execute()

    def _ask_language(self):
        if not lang_is_configured():
            print()
            print("Choisir la langue / Choose language:")
            print("[1] Francais")
            print("[2] English")
            choice = ""
            while choice not in ("1", "2"):
                choice = input("Select / Choisir : ").strip()
            if choice == "1":
                set_lang("fr")
            else:
                set_lang("en")

    def _change_language(self):
        print()
        print(t("lang_prompt") + ":")
        print(f"[1] {t('lang_french')}")
        print(f"[2] {t('lang_english')}")
        print(f"[0] {t('back')}")
        choice = ""
        while choice not in ("0", "1", "2"):
            choice = input(t("selection")).strip()
        if choice == "0":
            return False
        elif choice == "1":
            set_lang("fr")
        else:
            set_lang("en")
        print(t("lang_changed"))

    def run(self):
        with open(self.config_file.get_logo_ascii_file_path()) as my_file:
            print(my_file.read())
        self._ask_language()
        print(t("opening"))
        print(f"🤖 {t('enter_directives')}")
        help_info = f"""{t("command")}
[1] {t("menu_execute")}
[2] {t("menu_install")}
[3] {t("menu_question")}
[4] {t("menu_fork")}
[0] {t("menu_quit")}
"""
        while True:
            try:
                status = click.prompt(help_info)
            except NameError:
                print("Do")
                print(f"source ./{cst_venv_erplibre}/bin/activate && make")
                sys.exit(1)
            except ImportError:
                print("Do")
                print(f"source ./{cst_venv_erplibre}/bin/activate && make")
                sys.exit(1)
            except click.exceptions.Abort:
                sys.exit(0)
            print()
            if status == "0":
                break
            elif status == "1":
                self.prompt_execute()
            elif status == "2":
                self.prompt_install()
            elif status == "3":
                self.execute_prompt_ia()
            elif status == "4":
                # cmd = (
                #     f"gnome-terminal --tab -- bash -c 'source"
                #     f" ./{cst_venv_erplibre}/bin/activate;make todo'"
                # )
                cmd = "make todo"
                self.execute.exec_command_live(cmd, source_erplibre=True)
            # elif status == "3" or status == "install":
            #     print("install")
            else:
                print(t("cmd_not_found"))

        print(status)
        # manipuler()

    def get_kdbx(self):
        if self.kdbx:
            return self.kdbx
        # Open file
        chemin_fichier_kdbx = self.config_file.get_config_value(
            ["kdbx", "path"]
        )
        if not chemin_fichier_kdbx:
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            chemin_fichier_kdbx = filedialog.askopenfilename(
                title="Select a File",
                filetypes=(("KeepassX files", "*.kdbx"),),
            )
        if not chemin_fichier_kdbx:
            _logger.error(
                f"KDBX is not configured, please fill {self.config_file.CONFIG_FILE}"
            )
            return

        mot_de_passe_kdbx = self.config_file.get_config_value(
            ["kdbx", "password"]
        )
        if not mot_de_passe_kdbx:
            mot_de_passe_kdbx = getpass.getpass(prompt=t("enter_password"))

        kp = PyKeePass(chemin_fichier_kdbx, password=mot_de_passe_kdbx)

        if kp:
            self.kdbx = kp
        return kp

    def execute_prompt_ia(self):
        while True:
            help_info = f"""{t("command")}
[0] {t("back")}
{t("ia_prompt")}"""
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            kp = self.get_kdbx()
            if not kp:
                return
            nom_configuration = self.config_file.get_config_value(
                ["kdbx_config", "openai", "kdbx_key"]
            )
            entry = kp.find_entries_by_title(nom_configuration, first=True)

            client = openai.OpenAI(api_key=entry.password)
            prompt_update = status
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt_update}],
            )

            print(completion.choices[0].message.content)
            print()

    def prompt_execute(self):
        help_info = f"""{t("command")}
[1] {t("menu_run")}
[2] {t("menu_automation")}
[3] {t("menu_update")}
[4] {t("menu_code")}
[5] {t("menu_doc")}
[6] {t("menu_database")}
[7] {t("menu_git")}
[8] {t("menu_process")}
[9] {t("menu_config")}
[10] {t("menu_network")}
[11] {t("menu_security")}
[12] {t("menu_test")}
[13] {t("menu_lang")}
[0] {t("back")}
"""
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            elif status == "1":
                status = self.prompt_execute_instance()
                if status is not False:
                    return
            elif status == "2":
                status = self.prompt_execute_fonction()
                if status is not False:
                    return
            elif status == "3":
                status = self.prompt_execute_update()
                if status is not False:
                    return
            elif status == "4":
                status = self.prompt_execute_code()
                if status is not False:
                    return
            elif status == "5":
                status = self.prompt_execute_doc()
                if status is not False:
                    return
            elif status == "6":
                status = self.prompt_execute_database()
                if status is not False:
                    return
            elif status == "7":
                status = self.prompt_execute_git()
                if status is not False:
                    return
            elif status == "8":
                status = self.prompt_execute_process()
                if status is not False:
                    return
            elif status == "9":
                status = self.prompt_execute_config()
                if status is not False:
                    return
            elif status == "10":
                status = self.prompt_execute_network()
                if status is not False:
                    return
            elif status == "11":
                status = self.prompt_execute_security()
                if status is not False:
                    return
            elif status == "12":
                status = self.prompt_execute_test()
                if status is not False:
                    return
            elif status == "13":
                status = self._change_language()
                if status is not False:
                    return
            else:
                print(t("cmd_not_found"))

    def prompt_install(self):
        print("Detect first installation from code source.")

        first_installation_input = (
            input(
                "💬 First system installation? This will process system installation"
                " before (Y/N): "
            )
            .strip()
            .lower()
        )
        if first_installation_input == "y":
            cmd = "./script/version/update_env_version.py --install"
            self.execute.exec_command_live(cmd, source_erplibre=True)
            print("Wait after OS installation before continue.")

        # First detect pycharm, need to be open before installation and close to increase speed
        has_pycharm = False
        has_pycharm_community = False
        result = subprocess.run(
            ["which", "pycharm"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0:
            has_pycharm = True
        else:
            result = subprocess.run(
                ["which", "pycharm-community"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            has_pycharm_community = result.returncode == 0
        if (has_pycharm or has_pycharm_community) and not os.path.exists(
            ".idea"
        ):
            pycharm_configuration_input = (
                input("💬 Open Pycharm? (Y/N): ").strip().lower()
            )
            if pycharm_configuration_input == "y":
                pycharm_bin = "pycharm" if has_pycharm else "pycharm-community"

                cmd = f"cd {os.getcwd()} && {pycharm_bin} ./"
                self.execute.exec_command_live(
                    cmd,
                    source_erplibre=False,
                    single_source_erplibre=False,
                    new_window=True,
                )
                print(
                    "👹 WAIT and Close Pycharm when processing is done before continue"
                    " this guide."
                )
        # TODO detect last version supported
        # cmd_intern = "./script/install/install_erplibre.sh"
        # TODO maybe update q to only install erplibre from install_locally
        # TODO problem installing with q, the script depend on odoo
        key_i = 0
        dct_cmd_intern_begin = {
            "q": (
                "q",
                "q: ERPLibre only with system python without Odoo",
                "./script/install/install_erplibre.sh",
            ),
            "w": (
                "w",
                "w: Install all Odoo version with ERPLibre",
                "make install_odoo_all_version",
            ),
            "m": (
                "m",
                "m: ERPLibre with mobile home",
                "./mobile/install_and_run.sh",
            ),
            "0": (
                "0",
                f"0: {t('menu_quit')}",
            ),
        }
        dct_final_cmd_intern = {}
        lst_version, lst_version_installed, odoo_installed_version = (
            self.get_odoo_version()
        )

        for dct_version in lst_version[::-1]:
            key_i += 1
            key_s = str(key_i)
            label = f"{key_s}: Odoo {dct_version.get('odoo_version')}"

            odoo_version = f"odoo{dct_version.get('odoo_version')}"
            if odoo_version in lst_version_installed:
                label += " - Installed"
            if odoo_version == odoo_installed_version:
                label += " - Actual"
            if dct_version.get("default"):
                label += " - Default"
            if dct_version.get("is_deprecated"):
                label += " - Deprecated"
            erplibre_version = dct_version.get("erplibre_version")
            dct_cmd_intern_begin[key_s] = (
                key_s,
                label,
                f"./script/version/update_env_version.py --erplibre_version {erplibre_version} --install_dev",
            )

        # Add final command
        dct_cmd_intern = {**dct_cmd_intern_begin, **dct_final_cmd_intern}

        # Show command
        odoo_version_input = ""
        while odoo_version_input not in dct_cmd_intern.keys():
            if odoo_version_input:
                print(f"{t('error_value')} '{odoo_version_input}'")
            str_input_dyn_odoo_version = (
                f"💬 {t('choose_version')}\n\t"
                + "\n\t".join([a[1] for a in dct_cmd_intern.values()])
                + f"\n{t('selection')}"
            )
            odoo_version_input = (
                input(str_input_dyn_odoo_version).strip().lower()
            )

        if odoo_version_input == "0":
            return

        cmd_intern = dct_cmd_intern.get(odoo_version_input)[2]
        print(f"{t('will_execute')}\n{cmd_intern}")

        # TODO use external script to detect terminal to use on system
        # TODO check script open_terminal_code_generator.sh
        # cmd_extern = f"gnome-terminal -- bash -c '{cmd_intern};bash'"
        try:
            subprocess.run(
                cmd_intern, shell=True, executable="/bin/bash", check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"{t('script_failed')} {e.returncode}.")
            print("Wait after installation and open projects by terminal.")
            print("make open_terminal")
            self.restart_script(str(e))

    def execute_from_configuration(
        self, dct_instance, exec_run_db=False, ignore_makefile=False
    ):
        # exec_run_db need argument database
        kdbx_key = dct_instance.get("kdbx_key")
        odoo_user = dct_instance.get("user")
        odoo_password = dct_instance.get("password")

        if kdbx_key:
            extra_cmd_web_login = self.kdbx_get_extra_command_user(kdbx_key)
        elif odoo_user and odoo_password:
            extra_cmd_web_login = (
                f" --default_email_auth {odoo_user} --default_password_auth"
                f" '{odoo_password}'"
            )
        else:
            extra_cmd_web_login = ""

        makefile_cmd = dct_instance.get("makefile_cmd")
        if makefile_cmd and not ignore_makefile:
            status = self.execute.exec_command_live(
                f"make {makefile_cmd}",
                source_erplibre=False,
                single_source_erplibre=True,
            )
            if status:
                _logger.error(
                    f"Status {status} - exit execute_from_configuration"
                )
                return

        if exec_run_db:
            db_name = dct_instance.get("database")
            self.prompt_execute_selenium_and_run_db(
                db_name, extra_cmd_web_login=extra_cmd_web_login
            )

        command = dct_instance.get("command")
        if command:
            self.prompt_execute_selenium(
                command=command, extra_cmd_web_login=extra_cmd_web_login
            )

        callback = dct_instance.get("callback")
        if callback:
            callback(dct_instance)

    def fill_help_info(self, lst_choice):
        help_info = t("command") + "\n"
        help_end = f"[0] {t('back')}\n"
        for i, dct_instance in enumerate(lst_choice):
            desc_key = dct_instance.get("prompt_description_key")
            if desc_key:
                desc = t(desc_key)
            else:
                desc = dct_instance["prompt_description"]
            help_info += f"[{i + 1}] " + desc + "\n"
        help_info += help_end
        return help_info

    def prompt_execute_instance(self):
        # TODO proposer le déploiement à distance
        # TODO proposer l'exécution de docker
        # TODO proposer la création de docker
        lst_choice = self.config_file.get_config("instance")
        init_len = len(lst_choice)

        # Support mobile ERPLibre
        if os.path.exists(MOBILE_HOME_PATH):
            dct_upgrade_odoo_database = {
                "prompt_description": t("mobile_compile_run"),
                "callback": self.callback_make_mobile_home,
            }
            lst_choice.append(dct_upgrade_odoo_database)

        # Support custom database to execute
        dct_upgrade_odoo_database = {
            "prompt_description": t("choose_database"),
            "callback": self.callback_execute_custom_database,
        }
        lst_choice.insert(0, dct_upgrade_odoo_database)
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 1 < int_cmd <= init_len:
                        cmd_no_found = False
                        status = click.confirm(t("new_instance_confirm"))
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(
                            dct_instance,
                            exec_run_db=True,
                            ignore_makefile=not bool(status),
                        )
                    elif int_cmd <= len(lst_choice) or 1 == int_cmd:
                        cmd_no_found = False
                        # Execute dynamic instance
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(
                            dct_instance,
                        )
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("cmd_not_found"))

    def prompt_execute_fonction(self):
        lst_choice = self.config_file.get_config("function")
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_choice):
                        cmd_no_found = False
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("cmd_not_found"))

    def prompt_execute_update(self):
        # self.execute.exec_command_live(f"make {makefile_cmd}")
        print(f"🤖 {t('update_dev')}")
        # TODO détecter les modules en modification pour faire la mise à jour en cours
        # TODO demander sur quel BD faire la mise à jour
        # TODO proposer les modules manuelles selon la configuration à mettre à jour
        # TODO proposer la mise à jour de l'IDE
        # TODO proposer la mise à jour des git-repo
        # TODO faire la mise à jour de ERPLibre
        # TODO faire l'upgrade d'un odoo vers un autre

        lst_choice = self.config_file.get_config("update_from_makefile")
        dct_upgrade_odoo_database = {
            "prompt_description": t("upgrade_odoo_migration"),
        }
        lst_choice.append(dct_upgrade_odoo_database)
        dct_upgrade_poetry = {
            "prompt_description": t("upgrade_poetry_dependency"),
        }
        lst_choice.append(dct_upgrade_poetry)
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(lst_choice) - 1):
                upgrade = todo_upgrade.TodoUpgrade(self)
                upgrade.execute_odoo_upgrade()
            elif status == str(len(lst_choice)):
                self.upgrade_poetry()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status) - 1
                    if 0 < int_cmd <= len(lst_choice):
                        cmd_no_found = False
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("cmd_not_found"))

    def prompt_execute_code(self):
        print(f"🤖 {t('code_need')}")
        #         help_info = """Commande :
        #         [1] Status Git local et distant
        #         [2] Démarrer le générateur de code
        #         [3] Format - Formatage automatique selon changement [ou manuelle]
        #         [4] Qualité - Qualité logiciel, détecter les fichiers qui manquent les licences AGPLv3
        #         [0] Retour
        # """
        #         help_info = """Commande :
        #         [1] Status Git local et distant
        #         [0] Retour
        # """

        lst_choice = self.config_file.get_config("code_from_makefile")

        dct_upgrade_odoo_database = {
            "prompt_description": t("open_shell"),
        }
        lst_choice.append(dct_upgrade_odoo_database)

        dct_upgrade_odoo_database = {
            "prompt_description": t("upgrade_module"),
        }
        lst_choice.append(dct_upgrade_odoo_database)

        lst_choice.append(
            {
                "prompt_description": t("debug"),
            }
        )

        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(lst_choice)):
                self.debug_ide()
            elif status == str(len(lst_choice) - 1):
                self.upgrade_module()
            elif status == str(len(lst_choice) - 2):
                self.open_shell_on_database()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_choice):
                        cmd_no_found = False
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("cmd_not_found"))

    def prompt_execute_git(self):
        print(f"🤖 {t('git_manage')}")
        lst_choice = [
            {"prompt_description": t("git_local_server")},
        ]

        # Append config-driven entries
        lst_config = self.config_file.get_config("git_from_makefile")
        if lst_config:
            lst_choice.extend(lst_config)

        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.prompt_execute_git_local_server()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_choice):
                        cmd_no_found = False
                        dct_instance = lst_choice[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("cmd_not_found"))

    def prompt_execute_git_local_server(self):
        print(f"🤖 {t('git_repo_manage')}")
        lst_choice = [
            {"prompt_description": t("git_repo_deploy_local")},
            {"prompt_description": t("git_repo_deploy_production")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._prompt_git_server_actions(production_ready=False)
            elif status == "2":
                self._prompt_git_server_actions(production_ready=True)
            else:
                print(t("cmd_not_found"))

    def _prompt_git_server_actions(self, production_ready=False):
        mode = (
            t("git_mode_production")
            if production_ready
            else t("git_mode_local")
        )
        print(f"🤖 {mode}")
        lst_choice = [
            {"prompt_description": t("git_action_all")},
            {"prompt_description": t("git_action_init")},
            {"prompt_description": t("git_action_remote")},
            {"prompt_description": t("git_action_push")},
            {"prompt_description": t("git_action_serve")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._deploy_git_server(
                    production_ready=production_ready,
                    action="all",
                )
            elif status == "2":
                self._deploy_git_server(
                    production_ready=production_ready,
                    action="init",
                )
            elif status == "3":
                self._deploy_git_server(
                    production_ready=production_ready,
                    action="remote",
                )
            elif status == "4":
                self._deploy_git_server(
                    production_ready=production_ready,
                    action="push",
                )
            elif status == "5":
                self._deploy_git_server(
                    production_ready=production_ready,
                    action="serve",
                )
            else:
                print(t("cmd_not_found"))

    def _deploy_git_server(self, production_ready=False, action="all"):
        print(t("git_repo_deploy_starting"))
        cmd = (
            "python3 ./script/git/git_local_server.py -v" f" --action {action}"
        )
        if production_ready:
            cmd += " --production-ready"
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
        )

    def prompt_execute_doc(self):
        print(f"🤖 {t('doc_search')}")
        lst_choice = [
            {"prompt_description": t("migration_module_coverage")},
            {"prompt_description": t("what_change_between_version")},
            {"prompt_description": t("oca_guidelines")},
            {"prompt_description": t("oca_migration_odoo_19")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                str_version = input(
                    "Select version to upgrade Odoo CE (5-17) : "
                )
                try:
                    int_version = int(str_version)
                    print(
                        "https://oca.github.io/OpenUpgrade/coverage_analysis/modules"
                        f"{int_version * 10}-{(int_version + 1) * 10}.html"
                    )
                except ValueError:
                    print(
                        "https://oca.github.io/OpenUpgrade/030_coverage_analysis.html"
                    )
            elif status == "2":
                str_version = input(
                    "Select version to show what change for Odoo CE version 8-18) : "
                )
                try:
                    int_version = int(str_version)
                    print(
                        f"https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-{int_version}.0"
                    )
                except ValueError:
                    print("https://github.com/OCA/maintainer-tools/wiki")
            elif status == "3":
                print(
                    "https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst"
                )
            elif status == "4":
                print("https://github.com/OCA/maintainer-tools/issues/658")
            else:
                print(t("cmd_not_found"))

    def prompt_execute_database(self):
        print(f"🤖 {t('db_modify')}")
        lst_choice = [
            {"prompt_description": t("download_db_backup")},
            {"prompt_description": t("restore_from_backup")},
            {"prompt_description": t("create_backup")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.download_database_backup_cli()
            elif status == "2":
                self.restore_from_database()
            elif status == "3":
                self.create_backup_from_database()
            else:
                print(t("cmd_not_found"))

    def prompt_execute_process(self):
        print(f"🤖 {t('process_manage')}")
        lst_choice = [
            {"prompt_description": t("kill_process_port")},
            {"prompt_description": t("kill_git_daemon")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.process_kill_from_port()
            elif status == "2":
                self.process_kill_git_daemon()
            else:
                print(t("cmd_not_found"))

    def process_kill_git_daemon(self):
        self.execute.exec_command_live(
            "pkill -f 'git daemon'",
            source_erplibre=False,
        )
        print(t("kill_git_daemon_done"))

    def prompt_execute_config(self):
        print(f"🤖 {t('config_manage')}")
        lst_choice = [
            {"prompt_description": t("generate_all_config")},
            {"prompt_description": t("generate_from_preconfig")},
            {"prompt_description": t("generate_from_backup")},
            {"prompt_description": t("generate_from_database")},
            {"prompt_description": t("setup_queue_job_for_parallelism")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.generate_config()
            elif status == "2":
                self.generate_config_from_preconfiguration()
            elif status == "3":
                self.generate_config_from_backup()
            elif status == "4":
                self.generate_config_from_database()
            elif status == "5":
                self.generate_config_queue_job()
            else:
                print(t("cmd_not_found"))

    def prompt_execute_network(self):
        print(f"🤖 {t('network_tools')}")
        lst_choice = [
            {"prompt_description": t("ssh_port_forwarding")},
            {
                "prompt_description": t(
                    "network_performance_request_per_second"
                )
            },
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.generate_network_port_forwarding()
            elif status == "2":
                self.generate_network_performance_test()
            else:
                print(t("cmd_not_found"))

    def generate_network_port_forwarding(self, add_arg=None):
        # ssh -L local_port:localhost:remote_port SSH_connection
        ssh_connection = click.prompt(
            "SSH connection, check ~/.ssh/config or user@address"
        )
        local_port = click.prompt("local port (8069)")
        remote_port = click.prompt("remote port (8069)")
        cmd = f"ssh -L {local_port}:localhost:{remote_port} {ssh_connection}"
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            single_source_erplibre=False,
        )

    def generate_network_performance_test(self, add_arg=None):
        # ./script/performance/test_performance.sh
        address = click.prompt("https address, like https://erplibre.com")
        cmd = f"./script/performance/test_performance.sh {address}"
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def prompt_execute_security(self):
        print(f"🤖 {t('security_audit')}")
        lst_choice = [
            {"prompt_description": t("pip_audit_desc")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_pip_audit()
            else:
                print(t("cmd_not_found"))

    def prompt_execute_test(self):
        print(f"🤖 {t('test_description')}")
        lst_choice = [
            {"prompt_description": t("test_run_module")},
            {"prompt_description": t("test_run_module_coverage")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_test_module(coverage=False)
            elif status == "2":
                self.execute_test_module(coverage=True)
            else:
                print(t("cmd_not_found"))

    def execute_test_module(self, coverage=False):
        # Module name
        module_name = input(t("test_enter_module_name")).strip()
        if not module_name:
            print(t("test_module_required"))
            return

        # Database name
        db_name = input(t("test_db_name")).strip()
        if not db_name:
            db_name = "test_todo_tmp"

        # Extra modules
        extra_modules = input(t("test_install_extra_modules")).strip()

        # Log level
        log_level = input(t("test_log_level")).strip()
        if not log_level:
            log_level = "test"

        # Build module list
        modules_to_install = module_name
        if extra_modules:
            modules_to_install += f",{extra_modules}"

        # Step 1: Create temp DB
        print(f"\n--- {t('test_creating_db')} '{db_name}' ---")
        cmd_restore = f"./script/database/db_restore.py --database {db_name}"
        self.execute.exec_command_live(
            cmd_restore,
            source_erplibre=False,
            single_source_erplibre=True,
        )

        # Step 2: Install modules
        print(
            f"\n--- {t('test_installing_modules')}: {modules_to_install} ---"
        )
        cmd_install = (
            f"./script/addons/install_addons.sh"
            f" {db_name} {modules_to_install}"
        )
        self.execute.exec_command_live(
            cmd_install,
            source_erplibre=False,
            single_source_erplibre=True,
        )

        # Step 3: Run tests
        print(f"\n--- {t('test_running')}: {module_name} ---")
        cmd_test = (
            f"ODOO_MODE_TEST=true"
            f" ./run.sh"
            f" -d {db_name}"
            f" -u {module_name}"
            f" --log-level={log_level}"
        )
        if coverage:
            cmd_test = f"ODOO_MODE_COVERAGE=true {cmd_test}"
        status_code, output = self.execute.exec_command_live(
            cmd_test,
            return_status_and_output=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )

        if status_code == 0:
            print(f"\n✅ {t('test_success')}")
        else:
            print(f"\n❌ {t('test_failed')} {status_code}")

        # Step 4: Cleanup
        lang = get_lang()
        keep_input = input(t("test_keep_db")).strip().lower()
        keep = keep_input in (("o", "oui") if lang == "fr" else ("y", "yes"))
        if keep:
            print(f"{t('test_db_kept')}: {db_name}")
        else:
            print(f"\n--- {t('test_cleaning_db')} '{db_name}' ---")
            cmd_drop = f"./odoo_bin.sh db --drop --database {db_name}"
            self.execute.exec_command_live(
                cmd_drop,
                source_erplibre=False,
                single_source_erplibre=True,
            )

    def execute_pip_audit(self):
        lst_version, lst_version_installed, odoo_installed_version = (
            self.get_odoo_version()
        )

        # Build list of installed environments
        dct_env = {}
        key_i = 0
        for dct_version in lst_version[::-1]:
            erplibre_version = dct_version.get("erplibre_version")
            venv_path = f".venv.{erplibre_version}"
            req_path = f"requirement/requirements.{erplibre_version}.txt"
            odoo_version = f"odoo{dct_version.get('odoo_version')}"

            if not os.path.isdir(venv_path):
                continue

            key_i += 1
            key_s = str(key_i)
            label = f"{key_s}: {erplibre_version}"
            if odoo_version == odoo_installed_version:
                label += f" - {t('current')}"
            if dct_version.get("default"):
                label += f" - {t('default')}"

            dct_env[key_s] = {
                "label": label,
                "venv_path": venv_path,
                "req_path": req_path,
                "erplibre_version": erplibre_version,
            }

        if not dct_env:
            print(t("no_env_installed"))
            return

        # Show selection menu
        str_input = (
            f"💬 {t('choose_env_audit')}\n\t"
            + "\n\t".join([v["label"] for v in dct_env.values()])
            + f"\n\t0: {t('back')}"
            + f"\n{t('selection')}"
        )
        env_input = ""
        while env_input not in dct_env.keys() and env_input != "0":
            if env_input:
                print(f"{t('error_value')}" f" '{env_input}'")
            env_input = input(str_input).strip()

        if env_input == "0":
            return

        selected = dct_env[env_input]
        venv_path = selected["venv_path"]
        req_path = selected["req_path"]

        if not os.path.isfile(req_path):
            print(f"{t('dep_file_not_found')}{req_path}")
            return

        # TODO support bash from parameter if open gnome-terminal
        cmd = f"pip-audit -r {req_path} -l;bash"
        print(f"{t('execution')}{cmd}")
        self.execute.exec_command_live(
            cmd,
            source_erplibre=True,
            single_source_erplibre=False,
        )

    def generate_config(self, add_arg=None):
        # Repeating to get all item before get group
        cmd = (
            f"./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA;"
            f"./script/git/git_repo_update_group.py;"
            f"./script/generate_config.sh"
        )
        if add_arg:
            cmd += (
                f";./script/git/git_repo_update_group.py {add_arg};"
                f"./script/generate_config.sh"
            )
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def generate_config_from_preconfiguration(self):
        lst_choice = [
            {"prompt_description": t("preconfig_base")},
            {"prompt_description": t("preconfig_base_code_generator")},
            {"prompt_description": t("preconfig_base_image_db")},
            {"prompt_description": t("preconfig_all")},
            # {"prompt_description": "base + migration"},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                group = "base"
                str_group = f"--group {group}"
                self.generate_config(add_arg=str_group)
            elif status == "2":
                group = "base,code_generator"
                str_group = f"--group {group}"
                self.generate_config(add_arg=str_group)
            elif status == "3":
                group = "base,image_db"
                str_group = f"--group {group}"
                self.generate_config(add_arg=str_group)
            elif status == "4":
                self.generate_config()
            # elif status == "5":
            #     group = "base,migration"
            #     str_group = f"--group {group}"
            #     self.generate_config(add_arg=str_group)
            else:
                print(t("cmd_not_found"))

    def debug_ide(self):
        lst_choice = [
            {"prompt_description": t("debug_todo_py")},
        ]
        help_info = self.fill_help_info(lst_choice)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.open_pycharm_file(
                    os.getcwd(),
                    os.path.join(os.getcwd(), "script/todo/todo.py"),
                )
            else:
                print(t("cmd_not_found"))

    def generate_config_from_backup(self):
        file_name = self.open_file_image_db()
        add_arg = f"--from_backup_name {file_name} --add_repo odoo18.0/addons/MathBenTech_development"
        self.generate_config(add_arg=add_arg)

    def generate_config_from_database(self):
        database_name = self.select_database()
        str_arg = f"--database {database_name}"
        self.generate_config(add_arg=str_arg)
        return False

    def generate_config_queue_job(self):
        cmd = "./script/config/setup_odoo_config_conf_devops.py"
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def select_database(self):
        cmd_server = f"./odoo_bin.sh db --list"
        status, lst_database = self.execute.exec_command_live(
            cmd_server,
            return_status_and_output=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )
        lst_choice = [{"prompt_description": a.strip()} for a in lst_database]

        help_info = self.fill_help_info(lst_choice)

        lst_str_choice = [str(a) for a in range(len(lst_choice) + 1) if a]

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status in lst_str_choice:
                database_name = lst_database[int(status) - 1].strip()
                print(database_name)
                return database_name
            else:
                print(t("cmd_not_found"))

    def get_odoo_version(self):
        with open(VERSION_DATA_FILE) as txt:
            data_version = json.load(txt)

        if not data_version:
            raise Exception(
                f"Internal error, no Odoo version is supported, please valide file '{VERSION_DATA_FILE}'"
            )
        lst_version_transform = []
        for key, value in data_version.items():
            lst_version_transform.append(value)
            value["erplibre_version"] = key

        lst_version_installed = []
        if os.path.exists(INSTALLED_ODOO_VERSION_FILE):
            with open(INSTALLED_ODOO_VERSION_FILE) as txt:
                lst_version_installed = sorted(txt.read().splitlines())

        odoo_installed_version = None
        if os.path.exists(ODOO_VERSION_FILE):
            with open(ODOO_VERSION_FILE) as txt:
                odoo_installed_version = f"odoo{txt.read().strip()}"

        # Add odoo version installation on command
        lst_version = sorted(
            lst_version_transform, key=lambda k: k.get("erplibre_version")
        )

        return lst_version, lst_version_installed, odoo_installed_version

    def kdbx_get_extra_command_user(self, kdbx_key):
        lst_value = []
        if kdbx_key:
            kp = self.get_kdbx()
            if not kp:
                return ""
            if type(kdbx_key) is not list:
                lst_kdbx_key = [kdbx_key]
            else:
                lst_kdbx_key = kdbx_key
            for key in lst_kdbx_key:
                entry = kp.find_entries_by_title(key, first=True)
                try:
                    odoo_user = entry.username
                except AttributeError:
                    _logger.error(f"Cannot find username from keys {key}")
                try:
                    odoo_password = entry.password
                except AttributeError:
                    _logger.error(f"Cannot find password from keys {key}")
                lst_value.append(
                    " --default_email_auth"
                    f" {odoo_user} --default_password_auth '{odoo_password}'"
                )
        if len(lst_value) == 0:
            return ""
        elif len(lst_value) == 1:
            return lst_value[0]
        return lst_value

    def prompt_execute_selenium_and_run_db(self, bd, extra_cmd_web_login=""):
        # cmd = (
        #     f'parallel ::: "./run.sh -d {bd}" "sleep'
        #     f' 3;./script/selenium/web_login.py{extra_cmd_web_login}"'
        # )
        # self.execute.exec_command_live(cmd)
        cmd_server = f"./run.sh -d {bd};bash"
        self.execute.exec_command_live(cmd_server)
        cmd_client = (
            f"sleep 3;./script/selenium/web_login.py{extra_cmd_web_login};bash"
        )
        self.execute.exec_command_live(cmd_client)

    def prompt_execute_selenium(self, command=None, extra_cmd_web_login=""):
        lst_cmd = []
        if not command:
            cmd = "./script/selenium/web_login.py"
        else:
            cmd = command

        if type(extra_cmd_web_login) is list:
            for item in extra_cmd_web_login:
                lst_cmd.append(cmd + item)
        else:
            lst_cmd.append(cmd + extra_cmd_web_login)

        if len(lst_cmd) == 1:
            self.execute.exec_command_live(lst_cmd[0])
        elif len(lst_cmd) > 1:
            new_cmd = "parallel ::: "
            for i, cmd in enumerate(lst_cmd):
                new_cmd += f' "sleep {1 * i};{cmd}"'
            self.execute.exec_command_live(new_cmd)

    def crash_diagnostic(self, e):
        # TODO show message at start if os.path.exists(file_error_path)
        if os.path.exists(file_error_path) and not os.path.exists(
            cst_venv_erplibre
        ):
            print("Got error : ")
            print(e)
            print("Got error at first execution.", file_error_path)
            try:
                file = open(file_error_path, "r")
                content = file.read()
                # TODO si vide, ajouter notre erreur
                print(content)
            except FileNotFoundError:
                print("Error: File not found.")
            finally:
                if "file" in locals() and file:
                    file.close()
            # Force auto installation
            print("Auto installation")
            time.sleep(0.5)
            cmd = "./script/todo/source_todo.sh"
            # self.restart_script(e)
            self.execute.exec_command_live(cmd, source_erplibre=True)
            sys.exit(1)
        if os.path.exists(cst_venv_erplibre):
            print("Import error : ")
            print(e)
            # TODO auto-detect gnome-terminal, or choose another. Is it done already?
            self.restart_script(e)
            # self.prompt_install()

            # print(
            #     f"You forgot to activate source \nsource ./{cst_venv_erplibre}/bin/activate"
            # )
            # time.sleep(0.5)
            # cmd = "./script/todo/source_todo.sh"
            print("Re-execute TODO 🤖 or execute :")
            print()
            print(f"source {cst_venv_erplibre}/bin/activate;make")
            print()
            cmd = "./script/todo/todo.py"
            # # self.restart_script(e)
            try:
                # TODO duplicate
                import tkinter as tk
                from tkinter import filedialog

                import click
                import humanize
                import openai
                import urwid
                from pykeepass import PyKeePass
            except ImportError:
                print("Rerun and exit")
                self.execute.exec_command_live(cmd, source_erplibre=True)
                sys.exit(1)
            print("No error")
        else:
            self.prompt_install()

    def open_shell_on_database(self):
        database = self.select_database()
        if database:
            cmd_server = f"./odoo_bin.sh shell -d {database}"
            status, lst_database = self.execute.exec_command_live(
                cmd_server,
                return_status_and_output=True,
                source_erplibre=False,
                single_source_erplibre=True,
                new_window=True,
            )

    def open_pycharm_file(self, folder, filename):
        cmd = "~/.local/share/JetBrains/Toolbox/scripts/pycharm"
        # cmd = "/snap/bin/pycharm-community"
        # if pycharm_arg:
        #     cmd += f" {pycharm_arg}"
        if folder:
            cmd += f" {folder}"
        if filename:
            cmd += f" --line 1 {filename}"
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def upgrade_module(self):
        upgrade = todo_upgrade.TodoUpgrade(self)
        upgrade.execute_module_upgrade()

    def upgrade_poetry(self):
        # Only show the version to the user
        status = self.execute.exec_command_live(
            f"make version",
            source_erplibre=False,
        )
        # TODO maybe autodetect to update it
        git_repo_update_input = input(
            "💬 Would you like to fetch all your git repositories, you need it (y/Y) : "
        )
        if git_repo_update_input.strip().lower() == "y":
            status = self.execute.exec_command_live(
                f"./script/manifest/update_manifest_local_dev.sh",
                source_erplibre=False,
            )

        poetry_lock = "./poetry.lock"
        try:
            os.remove(poetry_lock)
        except Exception as e:
            pass
        odoo_long_version = ""
        if os.path.exists("./.erplibre-version"):
            with open("./.erplibre-version") as f:
                odoo_long_version = f.read()
        path_file_odoo_lock = f"./requirement/poetry.{odoo_long_version}.lock"
        if odoo_long_version:
            try:
                os.remove(path_file_odoo_lock)
            except Exception as e:
                pass

        status = self.execute.exec_command_live(
            f"pip install -r requirement/erplibre_require-ments-poetry.txt && "
            f"./script/poetry/poetry_update.py -f",
            source_erplibre=False,
            single_source_erplibre=False,
            single_source_odoo=True,
            source_odoo=odoo_long_version,
        )

        if os.path.exists(poetry_lock):
            shutil.copy2(poetry_lock, path_file_odoo_lock)

    def callback_execute_custom_database(self, dct_config):
        database_name = self.select_database()
        self.prompt_execute_selenium_and_run_db(database_name)

    def restore_from_database(self, show_remote_list=True):
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print("[1] By filename from image_db")
        print(f"[] Browser image_db {path_image_db}")
        status = input("💬 Select : ")
        if status == "1":
            file_name = status
        else:
            file_name = self.open_file_image_db()

        default_database_name = file_name.replace(" ", "_")
        if default_database_name.endswith(".zip"):
            default_database_name = default_database_name[:-4]

        database_name = input(
            f"💬 Database name (default={default_database_name}) : "
        )
        if not database_name:
            database_name = default_database_name

        status = (
            input("💬 Would you like to neutralize database (n/N)? ")
            .strip()
            .lower()
        )
        is_neutralize = False
        more_arg = ""
        if status != "n":
            more_arg = "--neutralize "
            is_neutralize = True
            database_name += "_neutralize"
        status, lst_output = self.execute.exec_command_live(
            f"python3 ./script/database/db_restore.py -d {database_name} {more_arg}--ignore_cache --image {file_name}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if is_neutralize:
            status, lst_output = self.execute.exec_command_live(
                f"./script/addons/update_prod_to_dev.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
        status = (
            input("💬 Would you like to update all addons (y/Y)? ")
            .strip()
            .lower()
        )
        if status == "y":
            status, lst_output = self.execute.exec_command_live(
                f"./script/addons/update_addons_all.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )

    def create_backup_from_database(self, show_remote_list=True):
        database_name = self.select_database()
        str_arg = f"--database {database_name}"

        backup_name = input("💬 Backup name (default = name+date.zip) : ")
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

        cmd = f"./odoo_bin.sh db --backup --database {database_name} --restore_image {backup_name}"
        status, lst_output = self.execute.exec_command_live(
            cmd,
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )

    def open_file_image_db(self):
        self.dir_path = ""
        path_image_db = os.path.join(os.getcwd(), "image_db")

        # self.dir_path is over-write into on_dir_selected
        file_browser = todo_file_browser.FileBrowser(
            path_image_db, self.on_dir_selected
        )
        file_browser.run_main_frame()
        file_name = os.path.basename(self.dir_path)
        print(file_name)
        return file_name

    def process_kill_from_port(self):
        cfg = configparser.ConfigParser()
        cfg.read("./config.conf")
        http_port = cfg.getint("options", "http_port")

        status = self.execute.exec_command_live(
            f"./script/process/kill_process_by_port.py {http_port} --kill-tree --nb_parent 2",
            source_erplibre=False,
        )

    def download_database_backup_cli(self, show_remote_list=True):
        database_domain = input("Domain Odoo (ex. https://mondomain.com) : ")
        if show_remote_list:
            status, lst_output = self.execute.exec_command_live(
                f"python3 ./script/database/list_remote.py --raw --odoo-url {database_domain}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            if len(lst_output) > 1:
                for index, output in enumerate(lst_output):
                    print(f"{index + 1} - {output}")
                database_name = input("Select id of database :").strip()
            elif len(lst_output) == 1:
                database_name = lst_output[0].strip()
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
        status, cmd_executed = self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            return_status_and_command=True,
            new_env=my_env,
        )
        try:
            with zipfile.ZipFile(default_output_path, "r") as zip_ref:
                manifest_file_1 = zip_ref.open("manifest.json")
            _logger.info(
                f"Log file '{default_output_path}' is complete and validated."
            )
        except Exception as e:
            _logger.error(e)
            _logger.error(
                f"Failed to read manifest.json from backup file '{default_output_path}'."
            )
        return status, output_path, database_name

    def restart_script(self, last_error):
        print(f"🤖 {t('reboot_todo')}")
        # os.execv(sys.executable, ['python'] + sys.argv)
        # TODO mettre check que le répertoire est créé, s'il existe, auto-loop à corriger
        if os.path.exists(cst_venv_erplibre) and not os.path.exists(
            file_error_path
        ):
            # TODO mettre check import suivant ne vont pas planter
            try:
                with open(file_error_path, "w") as f_file:
                    f_file.write(str(last_error))
                    pass  # The file is created and closed here, no content is written
                print(
                    f"Try to reopen process with before :\nsource ./{cst_venv_erplibre}/bin/activate && exec python "
                    + " ".join(sys.argv)
                )
                os.execv(
                    "/bin/bash",
                    [
                        "/bin/bash",
                        "-c",
                        f"source ./{cst_venv_erplibre}/bin/activate && exec python "
                        + " ".join(sys.argv),
                    ],
                )
            except Exception as e:
                print("Error detect at first execution.")
                print(e)

    def on_dir_selected(self, dir_path):
        self.dir_path = dir_path
        todo_file_browser.exit_program()

    def callback_make_mobile_home(self, dct_config):
        # Read file
        default_project_name = "ERPLibre"
        default_package_name = "ca.erplibre.home"
        # Read default information
        if os.path.exists(STRINGS_FILE):
            tree = ET.parse(STRINGS_FILE)
            root = tree.getroot()
            for elem in root.findall("string"):
                if elem.get("name") == "app_name":
                    default_project_name = elem.text
                if elem.get("name") == "package_name":
                    default_package_name = elem.text

        default_project_url_name = "https://erplibre.ca"
        # Read default information
        dotenv_file = dotenv.find_dotenv(
            filename=os.path.join(MOBILE_HOME_PATH, "src", ".env.production")
        )
        default_project_url_name = dotenv.get_key(
            dotenv_file, "VITE_WEBSITE_URL"
        )
        default_project_note_subject = dotenv.get_key(
            dotenv_file, "VITE_LABEL_NOTE"
        )

        default_debug = False
        project_name = default_project_name
        project_url_name = default_project_url_name
        project_principal_subject = default_project_note_subject
        package_name = default_package_name
        do_debug = default_debug
        do_change_picture_menu = False

        do_personalize = input(
            "Do you want to personalize the mobile application (Y) : "
        )
        if do_personalize.strip().lower() == "y":
            project_name = (
                input(
                    f'Your project name (Separate by space in title), default "{default_project_name}" : '
                ).strip()
                or default_project_name
            )
            package_name = (
                input(
                    f'Your package name (separate by . lower case, 3 works like DOMAIN.NAME.OBJECT), default "{default_package_name}" : '
                ).strip()
                or default_package_name
            )
            project_url_name = (
                input(
                    f'Your project url website, default "{default_project_url_name}" : '
                ).strip()
                or default_project_url_name
            )
            project_principal_subject = (
                input(
                    f'Your project subject, default "{default_project_note_subject}" : '
                ).strip()
                or default_project_note_subject
            )
            do_debug = (
                input("Compilation with debug information, default No (Y) : ")
                .strip()
                .lower()
                == "y"
            )
            do_change_picture_menu = (
                input(
                    "Want to change picture from menu, you need android-studio (Y) : "
                )
                .strip()
                .lower()
                == "y"
            )

        # Rename with script bash
        cmd_client = f'cd {MOBILE_HOME_PATH} && npx cap init "{project_name}" "{package_name}" && ./rename_android.sh "{project_name}" "{package_name}" && npx cap sync android'
        self.execute.exec_command_live(cmd_client, source_erplibre=False)

        # dotenv_mobile = dotenv.dotenv_values(dotenv_file)
        # dotenv_mobile["VITE_TITLE"] = project_name
        # dotenv_mobile["VITE_WEBSITE_URL"] = project_url_name
        dotenv.set_key(
            dotenv_file, "VITE_TITLE", project_name, quote_mode="always"
        )
        dotenv.set_key(
            dotenv_file,
            "VITE_WEBSITE_URL",
            project_url_name,
            quote_mode="always",
        )
        dotenv.set_key(
            dotenv_file,
            "VITE_LABEL_NOTE",
            project_principal_subject,
            quote_mode="always",
        )
        dotenv.set_key(
            dotenv_file,
            "VITE_DEBUG_DEV",
            "true" if do_debug else "false",
            quote_mode="never",
        )

        if do_change_picture_menu:
            status = self.execute.exec_command_live(
                f"cd {MOBILE_HOME_PATH} && npx cap open android;bash",
                source_erplibre=False,
                new_window=True,
            )
            print(
                "Guide for Android-Studio, wait loading is finish. Right-click to app/New/Image Asset and load your image."
            )
            input(
                "Did you finish to update image with Android-Studio ? Press to continue ..."
            )
            cmd_client = "cp ./mobile/erplibre_home_mobile/android/app/src/main/ic_launcher-playstore.png ./mobile/erplibre_home_mobile/src/assets/company_logo.png"
            self.execute.exec_command_live(cmd_client, source_erplibre=False)
            cmd_client = "cp ./mobile/erplibre_home_mobile/android/app/src/main/ic_launcher-playstore.png ./mobile/erplibre_home_mobile/src/assets/imgs/logo.png"
            self.execute.exec_command_live(cmd_client, source_erplibre=False)

        status = self.execute.exec_command_live(
            "./mobile/compile_and_run.sh", source_erplibre=False
        )


if __name__ == "__main__":
    start_time = time.time()
    try:
        todo = TODO()
        if ENABLE_CRASH:
            todo.crash_diagnostic(CRASH_E)
        todo.run()
    except KeyboardInterrupt:
        print(t("keyboard_interrupt"))
    finally:
        end_time = time.time()
        duration_sec = end_time - start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            humain_time = humanize.precisedelta(duration_delta)
            print(f"\n{t('execution_time')} {humain_time}\n")
        else:
            print(f"\n{t('execution_time')} {duration_sec:.2f} sec.\n")
