#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
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
from script.todo.database_manager import DatabaseManager
from script.todo.kdbx_manager import KdbxManager
from script.todo.todo_i18n import get_lang, lang_is_configured, set_lang, t
from script.todo.version_manager import get_odoo_version

ERROR_LOG_PATH = ".erplibre.error.txt"
VENV_ERPLIBRE = ".venv.erplibre"
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
        self.selected_file_path = None
        self.config_file = config_file.ConfigFile()
        self.execute = execute.Execute()
        self.kdbx_manager = KdbxManager(self.config_file)
        self.db_manager = DatabaseManager(self.execute, self.fill_help_info)

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
        print(t("Choose language / Choisir la langue") + ":")
        print(f"[1] {t('French')}")
        print(f"[2] {t('English')}")
        print(f"[0] {t('Back')}")
        choice = ""
        while choice not in ("0", "1", "2"):
            choice = input(t("Select: ")).strip()
        if choice == "0":
            return False
        elif choice == "1":
            set_lang("fr")
        else:
            set_lang("en")
        print(t("Language changed to: English"))

    def run(self):
        with open(self.config_file.get_logo_ascii_file_path()) as my_file:
            print(my_file.read())
        self._ask_language()
        print(t("Opening TODO ..."))
        print(f"🤖 {t('=> Enter your choice by number and press Enter!')}")
        help_info = f"""{t("Command:")}
[1] {t("Execute")}
[2] {t("Install")}
[3] {t("Question")}
[4] {t("Fork - Open TODO in a new tab")}
[0] {t("Quit")}
"""
        while True:
            try:
                status = click.prompt(help_info)
            except NameError:
                print("Do")
                print(f"source ./{VENV_ERPLIBRE}/bin/activate && make")
                sys.exit(1)
            except ImportError:
                print("Do")
                print(f"source ./{VENV_ERPLIBRE}/bin/activate && make")
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
                #     f" ./{VENV_ERPLIBRE}/bin/activate;make todo'"
                # )
                cmd = "make todo"
                self.execute.exec_command_live(cmd, source_erplibre=True)
            # elif status == "3" or status == "install":
            #     print("install")
            else:
                print(t("Command not found !"))

        print(status)
        # manipuler()

    def execute_prompt_ia(self):
        while True:
            help_info = f"""{t("Command:")}
[0] {t("Back")}
{t("Write your question ")}"""
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            kp = self.kdbx_manager.get_kdbx()
            if not kp:
                return
            config_name = self.config_file.get_config_value(
                ["kdbx_config", "openai", "kdbx_key"]
            )
            entry = kp.find_entries_by_title(config_name, first=True)

            client = openai.OpenAI(api_key=entry.password)
            prompt_update = status
            completion = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt_update}],
            )

            print(completion.choices[0].message.content)
            print()

    def prompt_execute(self):
        help_info = f"""{t("Command:")}
[1] {t("Automation - Demonstration of developed features")}
[2] {t("Code - Developer tools")}
[3] {t("Config - Configuration file management")}
[4] {t("Database - Database tools")}
[5] {t("Doc - Documentation search")}
[6] {t("Git - Git tools")}
[7] {t("GPT code - AI assistant tools")}
[8] {t("Language - Change language / Changer la langue")}
[9] {t("Network - Network tools")}
[10] {t("Process - Execution tools")}
[11] {t("Run - Execute and install an instance")}
[12] {t("Security - Dependency security audit")}
[13] {t("Test - Test an Odoo module")}
[14] {t("Update - Update all developed staging source code")}
[15] {t("Deploy - Deploy ERPLibre locally")}
[0] {t("Back")}
"""
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            elif status == "1":
                status = self.prompt_execute_function()
                if status is not False:
                    return
            elif status == "2":
                status = self.prompt_execute_code()
                if status is not False:
                    return
            elif status == "3":
                status = self.prompt_execute_config()
                if status is not False:
                    return
            elif status == "4":
                status = self.prompt_execute_database()
                if status is not False:
                    return
            elif status == "5":
                status = self.prompt_execute_doc()
                if status is not False:
                    return
            elif status == "6":
                status = self.prompt_execute_git()
                if status is not False:
                    return
            elif status == "7":
                status = self.prompt_execute_gpt_code()
                if status is not False:
                    return
            elif status == "8":
                status = self._change_language()
                if status is not False:
                    return
            elif status == "9":
                status = self.prompt_execute_network()
                if status is not False:
                    return
            elif status == "10":
                status = self.prompt_execute_process()
                if status is not False:
                    return
            elif status == "11":
                status = self.prompt_execute_instance()
                if status is not False:
                    return
            elif status == "12":
                status = self.prompt_execute_security()
                if status is not False:
                    return
            elif status == "13":
                status = self.prompt_execute_test()
                if status is not False:
                    return
            elif status == "14":
                status = self.prompt_execute_update()
                if status is not False:
                    return
            elif status == "15":
                status = self.prompt_execute_deploy()
                if status is not False:
                    return
            else:
                print(t("Command not found !"))

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
        commands_begin = {
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
                f"0: {t('Quit')}",
            ),
        }
        commands_end = {}
        versions, installed_versions, odoo_installed_version = (
            get_odoo_version()
        )

        for version_info in versions[::-1]:
            key_i += 1
            key_s = str(key_i)
            label = f"{key_s}: Odoo {version_info.get('odoo_version')}"

            odoo_version = f"odoo{version_info.get('odoo_version')}"
            if odoo_version in installed_versions:
                label += " - Installed"
            if odoo_version == odoo_installed_version:
                label += " - Actual"
            if version_info.get("Default"):
                label += " - Default"
            if version_info.get("is_deprecated"):
                label += " - Deprecated"
            erplibre_version = version_info.get("erplibre_version")
            commands_begin[key_s] = (
                key_s,
                label,
                f"./script/version/update_env_version.py --erplibre_version {erplibre_version} --install_dev",
            )

        # Add final command
        install_commands = {**commands_begin, **commands_end}

        # Show command
        odoo_version_input = ""
        while odoo_version_input not in install_commands:
            if odoo_version_input:
                print(
                    f"{t('Error, cannot understand value')} '{odoo_version_input}'"
                )
            str_input_dyn_odoo_version = (
                f"💬 {t('Choose a version:')}\n\t"
                + "\n\t".join([a[1] for a in install_commands.values()])
                + f"\n{t('Select: ')}"
            )
            odoo_version_input = (
                input(str_input_dyn_odoo_version).strip().lower()
            )

        if odoo_version_input == "0":
            return

        cmd_intern = install_commands.get(odoo_version_input)[2]
        print(f"{t('Will execute:')}\n{cmd_intern}")

        # TODO use external script to detect terminal to use on system
        # TODO check script open_terminal_code_generator.sh
        # cmd_extern = f"gnome-terminal -- bash -c '{cmd_intern};bash'"
        try:
            subprocess.run(
                cmd_intern, shell=True, executable="/bin/bash", check=True
            )
        except subprocess.CalledProcessError as e:
            print(
                f"{t('The Bash script failed with return code')} {e.returncode}."
            )
            print("Wait after installation and open projects by terminal.")
            print("make open_terminal")
            self.restart_script(str(e))

    def execute_from_configuration(
        self, instance, exec_run_db=False, ignore_makefile=False
    ):
        # exec_run_db need argument database
        kdbx_key = instance.get("kdbx_key")
        odoo_user = instance.get("user")
        odoo_password = instance.get("password")

        if kdbx_key:
            extra_cmd_web_login = self.kdbx_manager.get_extra_command_user(
                kdbx_key
            )
        elif odoo_user and odoo_password:
            extra_cmd_web_login = (
                f" --default_email_auth {odoo_user} --default_password_auth"
                f" '{odoo_password}'"
            )
        else:
            extra_cmd_web_login = ""

        makefile_cmd = instance.get("makefile_cmd")
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
            db_name = instance.get("database")
            self.prompt_execute_selenium_and_run_db(
                db_name, extra_cmd_web_login=extra_cmd_web_login
            )

        bash_command = instance.get("bash_command")
        if bash_command:
            print(f"{t('Will execute:')} {bash_command}")
            self.execute.exec_command_live(bash_command, source_erplibre=False)

        command = instance.get("Command:")
        if command:
            self.prompt_execute_selenium(
                command=command, extra_cmd_web_login=extra_cmd_web_login
            )

        callback = instance.get("callback")
        if callback:
            callback(instance)

    def fill_help_info(self, choices):
        help_info = t("Command:") + "\n"
        help_end = f"[0] {t('Back')}\n"
        for i, instance in enumerate(choices):
            desc_key = instance.get("prompt_description_key")
            if desc_key:
                desc = t(desc_key)
            else:
                desc = instance["prompt_description"]
            help_info += f"[{i + 1}] " + desc + "\n"
        help_info += help_end
        return help_info

    def prompt_execute_instance(self):
        # TODO proposer le déploiement à distance
        # TODO proposer l'exécution de docker
        # TODO proposer la création de docker
        choices = self.config_file.get_config("instance")
        init_len = len(choices)

        # Support mobile ERPLibre
        if os.path.exists(MOBILE_HOME_PATH):
            menu_entry = {
                "prompt_description": t("Mobile - Compile and run software"),
                "callback": self.callback_make_mobile_home,
            }
            choices.append(menu_entry)

        # Support custom database to execute
        menu_entry = {
            "prompt_description": t("Choose your database"),
            "callback": self.callback_execute_custom_database,
        }
        choices.insert(0, menu_entry)
        help_info = self.fill_help_info(choices)

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
                        status = click.confirm(
                            t("Do you want a new instance?")
                        )
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(
                            instance,
                            exec_run_db=True,
                            ignore_makefile=not bool(status),
                        )
                    elif int_cmd <= len(choices) or 1 == int_cmd:
                        cmd_no_found = False
                        # Execute dynamic instance
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(
                            instance,
                        )
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def prompt_execute_function(self):
        choices = self.config_file.get_config("function")
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(choices):
                        cmd_no_found = False
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def prompt_execute_update(self):
        # self.execute.exec_command_live(f"make {makefile_cmd}")
        print(f"🤖 {t('Development update')}")
        # TODO détecter les modules en modification pour faire la mise à jour en cours
        # TODO demander sur quel BD faire la mise à jour
        # TODO proposer les modules manuelles selon la configuration à mettre à jour
        # TODO proposer la mise à jour de l'IDE
        # TODO proposer la mise à jour des git-repo
        # TODO faire la mise à jour de ERPLibre
        # TODO faire l'upgrade d'un odoo vers un autre

        choices = self.config_file.get_config("update_from_makefile")
        menu_entry = {
            "prompt_description": t("Upgrade Odoo - Migration Database"),
        }
        choices.append(menu_entry)
        poetry_entry = {
            "prompt_description": t("Upgrade Poetry - Dependency of Odoo"),
        }
        choices.append(poetry_entry)
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(choices) - 1):
                upgrade = todo_upgrade.TodoUpgrade(self)
                upgrade.execute_odoo_upgrade()
            elif status == str(len(choices)):
                self.upgrade_poetry()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status) - 1
                    if 0 < int_cmd <= len(choices):
                        cmd_no_found = False
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def prompt_execute_deploy(self):
        print(f"🤖 {t('Deploy ERPLibre to a local directory!')}")
        choices = [
            {"prompt_description": t("Clone ERPLibre locally (git clone)")},
            {"prompt_description": t("Configure sshfs")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._deploy_clone_erplibre()
            elif status == "2":
                self._configure_sshfs()
            else:
                print(t("Command not found !"))

    def _deploy_clone_erplibre(self):
        default_path = os.path.expanduser("~/erplibre")
        target_path = (
            input(t("Target directory path (default: ~/erplibre): ")).strip()
            or default_path
        )
        target_path = os.path.expanduser(target_path)
        if os.path.exists(target_path):
            print(f"{t('Directory already exists: ')}{target_path}")
            return
        print(t("Cloning ERPLibre..."))
        cmd = (
            "git clone"
            " https://github.com/erplibre/erplibre"
            f" {target_path}"
        )
        print(f"{t('Will execute:')} {cmd}")
        try:
            self.execute.exec_command_live(cmd, source_erplibre=False)
            print(f"{t('ERPLibre cloned successfully to: ')}" f"{target_path}")
        except Exception as e:
            print(f"{t('Error cloning ERPLibre: ')}{e}")

    def _configure_sshfs(self):
        import getpass
        import re
        from datetime import datetime

        print(f"\n{t('SSH address input method')}")
        print(f"[1] {t('Manual entry')}")
        print(f"[2] {t('From ~/.ssh/config')}")
        choice = input(t("Your choice (1/2): ")).strip()

        user = None
        hostname = None
        ssh_name = None

        if choice == "2":
            ssh_config_path = os.path.expanduser("~/.ssh/config")
            hosts = []
            if os.path.exists(ssh_config_path):
                current_host = None
                current_info = {}
                with open(ssh_config_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.lower().startswith("host "):
                            host_val = line.split(None, 1)[1].strip()
                            if host_val != "*":
                                if current_host:
                                    hosts.append((current_host, current_info))
                                current_host = host_val
                                current_info = {}
                        elif current_host:
                            key = line.split(None, 1)
                            if len(key) == 2:
                                k = key[0].lower()
                                v = key[1].strip()
                                if k == "hostname":
                                    current_info["hostname"] = v
                                elif k == "user":
                                    current_info["user"] = v
                if current_host:
                    hosts.append((current_host, current_info))

            if not hosts:
                print(t("No SSH hosts found in ~/.ssh/config"))
                return

            print()
            for i, (host, info) in enumerate(hosts, 1):
                hn = info.get("hostname", host)
                u = info.get("user", "")
                desc = host
                if hn != host:
                    desc += f" ({hn})"
                if u:
                    desc += f" [{u}]"
                print(f"[{i}] {desc}")

            sel = input(t("Select SSH host number: ")).strip()
            try:
                idx = int(sel) - 1
                if idx < 0 or idx >= len(hosts):
                    print(t("Invalid selection!"))
                    return
            except ValueError:
                print(t("Invalid selection!"))
                return

            host_name, host_info = hosts[idx]
            hostname = host_info.get("hostname", host_name)
            user = host_info.get("user", getpass.getuser())
            ssh_name = host_name
            target = f"{host_name}:/"
        else:
            ssh_host = input(
                t("SSH host (e.g.: user@192.168.1.100): ")
            ).strip()
            if not ssh_host:
                print(t("SSH host is required!"))
                return
            if "@" in ssh_host:
                user, hostname = ssh_host.split("@", 1)
            else:
                hostname = ssh_host
                user = getpass.getuser()
            ssh_name = hostname
            target = f"{user}@{hostname}:/"

        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", ssh_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mount_point = f"/tmp/sshfs_{safe_name}_{timestamp}"
        os.makedirs(mount_point, exist_ok=True)

        cmd = f"sshfs {target} {mount_point}"
        print(f"{t('Mounting sshfs on: ')}{mount_point}")
        print(f"{t('Will execute:')} {cmd}")
        try:
            self.execute.exec_command_live(cmd, source_erplibre=False)
            print(f"{t('Mounted on: ')}{mount_point}")
            print(f"mount | grep sshfs")
            print(f"{t('To unmount: ')}" f"fusermount -u {mount_point}")
            print(f"nautilus {mount_point}/home/{user}")
        except Exception as e:
            print(f"{t('Error mounting sshfs: ')}{e}")

    def prompt_execute_code(self):
        print(f"🤖 {t('What do you need for development?')}")
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

        choices = self.config_file.get_config("code_from_makefile")

        menu_entry = {
            "prompt_description": t("Open SHELL"),
        }
        choices.append(menu_entry)

        menu_entry = {
            "prompt_description": t("Upgrade Module"),
        }
        choices.append(menu_entry)

        choices.append(
            {
                "prompt_description": t("Debug"),
            }
        )

        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(choices)):
                self.debug_ide()
            elif status == str(len(choices) - 1):
                self.upgrade_module()
            elif status == str(len(choices) - 2):
                self.open_shell_on_database()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(choices):
                        cmd_no_found = False
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def prompt_execute_git(self):
        print(f"🤖 {t('Git management tools!')}")
        choices = [
            {"prompt_description": t("Local git server")},
            {"prompt_description": t("Add a remote to a local repository")},
        ]

        # Append config-driven entries
        config_entries = self.config_file.get_config("git_from_makefile")
        if config_entries:
            choices.extend(config_entries)

        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.prompt_execute_git_local_server()
            elif status == "2":
                self._git_add_remote()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(choices):
                        cmd_no_found = False
                        instance = choices[int_cmd - 1]
                        self.execute_from_configuration(instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    def _git_add_remote(self):
        remote_name = (
            input(t("Remote name (default: localhost): ")).strip()
            or "localhost"
        )
        remote_url = input(
            t("Repository address (e.g.: git://192.168.1.100/my-repo.git): ")
        ).strip()
        if not remote_url:
            print(t("Repository address is required!"))
            return
        cmd = f"git remote add {remote_name} {remote_url}"
        print(f"{t('Will execute:')} {cmd}")
        try:
            self.execute.exec_command_live(cmd, source_erplibre=False)
            print(t("Remote added successfully!"))
        except Exception as e:
            print(f"{t('Error adding remote: ')}{e}")

    def prompt_execute_git_local_server(self):
        print(f"🤖 {t('Manage local git repository server!')}")
        choices = [
            {
                "prompt_description": t(
                    "Deploy a local git server (~/.git-server)"
                )
            },
            {
                "prompt_description": t(
                    "Deploy a production git server (/srv/git, root required)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def _prompt_git_server_actions(self, production_ready=False):
        mode = (
            t("Production mode (/srv/git, root required)")
            if production_ready
            else t("Local mode (~/.git-server)")
        )
        print(f"🤖 {mode}")
        choices = [
            {
                "prompt_description": t(
                    "Run all (init + remote + push + serve)"
                )
            },
            {"prompt_description": t("Init - Create bare repos")},
            {"prompt_description": t("Remote - Add local remotes")},
            {"prompt_description": t("Push - Push to local server")},
            {"prompt_description": t("Serve - Start git daemon")},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def _deploy_git_server(self, production_ready=False, action="all"):
        print(t("Starting git server deployment..."))
        cmd = (
            "python3 ./script/git/git_local_server.py -v" f" --action {action}"
        )
        if production_ready:
            cmd += " --production-ready"
        self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
        )

    def prompt_execute_gpt_code(self):
        print(f"🤖 {t('AI assistant tools for development!')}")
        choices = [
            {"prompt_description": t("Configure Claude Code configurations")},
            {
                "prompt_description": t(
                    "Add an automation with Claude in todo.py"
                )
            },
            {
                "prompt_description": t(
                    "RTK - CLI proxy to reduce LLM token consumption"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._prompt_claude_configs()
            elif status == "2":
                self._claude_add_automation()
            elif status == "3":
                self.prompt_execute_rtk()
            else:
                print(t("Command not found !"))

    def _prompt_claude_configs(self):
        print(f"🤖 {t('Deploy Claude Code commands!')}")
        choices = [
            {"prompt_description": t("Commit - OCA/Odoo commit command")},
            {
                "prompt_description": t(
                    "Todo Add Command - Add a command to todo.py menu"
                )
            },
            {"prompt_description": t("Show installed custom commands")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._setup_claude_command(
                    "commit",
                    "template_claude_commands_commit.md",
                    personalize=True,
                )
            elif status == "2":
                self._setup_claude_command(
                    "todo_add_command",
                    "template_claude_commands_todo_add_command.md",
                )
            elif status == "3":
                self._list_claude_commands()
            else:
                print(t("Command not found !"))

    def _list_claude_commands(self):
        commands_dir = os.path.expanduser("~/.claude/commands")
        if not os.path.isdir(commands_dir):
            print(t("No custom commands found in ~/.claude/commands/"))
            return
        files = sorted(
            f for f in os.listdir(commands_dir) if f.endswith(".md")
        )
        if not files:
            print(t("No custom commands found in ~/.claude/commands/"))
            return
        print(t("Claude Code custom commands:"))
        print("-" * 50)
        for f in files:
            filepath = os.path.join(commands_dir, f)
            mtime = os.path.getmtime(filepath)
            date_str = datetime.datetime.fromtimestamp(mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
            name = f[:-3]  # remove .md
            print(f"  /{name:<30} {date_str}")
        print("-" * 50)
        print(f"{t('Total:')}" f" {len(files)}")

    def _setup_claude_command(
        self, command_name, template_filename, personalize=False
    ):
        dest_dir = os.path.expanduser("~/.claude/commands")
        dest_file = os.path.join(dest_dir, f"{command_name}.md")

        if os.path.exists(dest_file):
            print(f"{t('File already exists: ')}{dest_file}")
            overwrite = input(
                t("Do you want to overwrite the file? (y/Y): ")
            ).strip()
            if overwrite not in ("y", "Y"):
                print(t("Nothing to do."))
                return

        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "conf",
            template_filename,
        )
        try:
            with open(template_path) as f:
                content = f.read()

            if personalize:
                name = input(t("Enter your full name: ")).strip()
                email = input(t("Enter your email: ")).strip()
                content = content.replace(
                    "Your Name <your@email.com>",
                    f"{name} <{email}>",
                )
                content = content.replace(
                    "Your Name ",
                    f"{name} ",
                )

            os.makedirs(dest_dir, exist_ok=True)
            with open(dest_file, "w") as f:
                f.write(content)

            print(f"{t('File created successfully: ')}{dest_file}")
        except Exception as e:
            print(f"{t('Error creating file: ')}{e}")

    def _claude_add_automation(self):
        description = input(t("Description of the command to add: ")).strip()
        if not description:
            return
        command = input(t("Bash command to execute: ")).strip()
        if not command:
            return
        section = (
            input(
                t("Menu section (git/code/config/network/process): ")
            ).strip()
            or "git"
        )
        section_key = f"{section}_from_makefile"
        config_path = os.path.join(os.path.dirname(__file__), "todo.json")
        try:
            with open(config_path) as f:
                config = json.load(f)
            if section_key not in config:
                config[section_key] = []
            config[section_key].append(
                {
                    "prompt_description": description,
                    "bash_command": command,
                }
            )
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
                f.write("\n")
            print(t("Automation added successfully in todo.json!"))
        except Exception as e:
            print(f"{t('Error adding automation: ')}{e}")

    def prompt_execute_doc(self):
        print(f"🤖 {t('Looking for documentation?')}")
        choices = [
            {"prompt_description": t("Migration module coverage")},
            {"prompt_description": t("What change between version")},
            {"prompt_description": t("OCA guidelines")},
            {"prompt_description": t("OCA migration Odoo 19 milestone")},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def prompt_execute_database(self):
        print(f"🤖 {t('Make changes to databases!')}")
        choices = [
            {
                "prompt_description": t(
                    "Download database to create backup (.zip)"
                )
            },
            {"prompt_description": t("Restore from backup (.zip)")},
            {"prompt_description": t("Create backup (.zip)")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.db_manager.download_database_backup_cli()
            elif status == "2":
                self.db_manager.restore_from_database()
            elif status == "3":
                self.db_manager.create_backup_from_database()
            else:
                print(t("Command not found !"))

    def prompt_execute_process(self):
        print(f"🤖 {t('Manage execution processes!')}")
        choices = [
            {"prompt_description": t("Kill Odoo process from actual port")},
            {"prompt_description": t("Kill git daemon server process")},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def process_kill_git_daemon(self):
        self.execute.exec_command_live(
            "pkill -f 'git daemon'",
            source_erplibre=False,
        )
        print(t("Git daemon process killed."))

    def prompt_execute_rtk(self):
        print(
            f"🤖 {t('Manage RTK (Rust Token Killer) for token optimization!')}"
        )
        choices = [
            {"prompt_description": t("Install RTK")},
            {"prompt_description": t("Check RTK version")},
            {"prompt_description": t("Show cumulative token savings")},
            {"prompt_description": t("Discover optimization opportunities")},
            {"prompt_description": t("Initialize global auto-rewrite hook")},
            {"prompt_description": t("Check RTK status")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.rtk_install()
            elif status == "2":
                self.rtk_check_version()
            elif status == "3":
                self.rtk_show_gain()
            elif status == "4":
                self.rtk_discover()
            elif status == "5":
                self.rtk_init_global()
            elif status == "6":
                self.rtk_check_status()
            else:
                print(t("Command not found !"))

    def rtk_install(self):
        print(f"🤖 {t('Installation method:')}")
        choices = [
            {"prompt_description": t("curl - Automatic install script")},
            {"prompt_description": t("brew - Homebrew (macOS/Linux)")},
            {
                "prompt_description": t(
                    "cargo - Build from source (Rust required)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        status = click.prompt(help_info)
        print()
        if status == "0":
            return
        elif status == "1":
            self.execute.exec_command_live(
                "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh",
                source_erplibre=False,
            )
        elif status == "2":
            self.execute.exec_command_live(
                "brew install rtk",
                source_erplibre=False,
            )
        elif status == "3":
            self.execute.exec_command_live(
                "cargo install --git https://github.com/rtk-ai/rtk",
                source_erplibre=False,
            )
        else:
            print(t("Command not found !"))

    def rtk_check_version(self):
        self.execute.exec_command_live(
            "rtk --version",
            source_erplibre=False,
        )

    def rtk_show_gain(self):
        self.execute.exec_command_live(
            "rtk gain",
            source_erplibre=False,
        )

    def rtk_discover(self):
        self.execute.exec_command_live(
            "rtk discover",
            source_erplibre=False,
        )

    def rtk_init_global(self):
        self.execute.exec_command_live(
            "rtk init --global",
            source_erplibre=False,
        )

    def rtk_check_status(self):
        rtk_path = shutil.which("rtk")
        if rtk_path is None:
            print(t("RTK is not installed. Use option 1 to install it."))
            return

        result = self.execute.exec_command_live(
            "rtk --version",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        if isinstance(result, tuple) and result[0] == 0:
            version_output = " ".join(result[1]).strip()
            print(f"{t('RTK is installed, version: ')}{version_output}")
        else:
            print(f"{t('RTK is installed, version: ')}?")

        config_path = os.path.expanduser("~/.config/rtk/config.toml")
        if os.path.exists(config_path):
            print(t("Global auto-rewrite hook: active"))
        else:
            print(t("Global auto-rewrite hook: inactive"))

    def prompt_execute_config(self):
        print(f"🤖 {t('Manage ERPLibre and Odoo configuration!')}")
        choices = [
            {"prompt_description": t("Generate all configuration")},
            {"prompt_description": t("Generate from pre-configuration")},
            {"prompt_description": t("Generate from backup file")},
            {"prompt_description": t("Generate from database")},
            {"prompt_description": t("Setup queue job for parallelism")},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def prompt_execute_network(self):
        print(f"🤖 {t('Network tools!')}")
        choices = [
            {"prompt_description": t("SSH port-forwarding")},
            {
                "prompt_description": t(
                    "Network performance request per second"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

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
        print(f"🤖 {t('Dependency security audit!')}")
        choices = [
            {
                "prompt_description": t(
                    "pip-audit - Check vulnerabilities on Python environments"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_pip_audit()
            else:
                print(t("Command not found !"))

    def prompt_execute_test(self):
        print(f"🤖 {t('Test an Odoo module on a temporary database!')}")
        choices = [
            {"prompt_description": t("Test a module")},
            {"prompt_description": t("Test a module with code coverage")},
            {"prompt_description": t("ERPLibre unit tests")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_test_module(coverage=False)
            elif status == "2":
                self.execute_test_module(coverage=True)
            elif status == "3":
                self.execute_unit_tests()
            else:
                print(t("Command not found !"))

    def execute_test_module(self, coverage=False):
        # Module name
        module_name = input(t("Module name to test: ")).strip()
        if not module_name:
            print(t("Module name is required!"))
            return

        # Database name
        db_name = input(
            t("Temporary database name (default: test_todo_tmp): ")
        ).strip()
        if not db_name:
            db_name = "test_todo_tmp"

        # Extra modules
        extra_modules = input(
            t("Extra modules to install (comma-separated, empty for none): ")
        ).strip()

        # Log level
        log_level = input(t("Log level (default: test): ")).strip()
        if not log_level:
            log_level = "test"

        # Build module list
        modules_to_install = module_name
        if extra_modules:
            modules_to_install += f",{extra_modules}"

        # Step 1: Create temp DB
        print(f"\n--- {t('Creating temporary database')} '{db_name}' ---")
        cmd_restore = f"./script/database/db_restore.py --database {db_name}"
        self.execute.exec_command_live(
            cmd_restore,
            source_erplibre=False,
            single_source_erplibre=True,
        )

        # Step 2: Install modules
        print(f"\n--- {t('Installing modules')}: {modules_to_install} ---")
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
        print(f"\n--- {t('Running tests')}: {module_name} ---")
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
            print(f"\n✅ {t('Tests completed successfully!')}")
        else:
            print(f"\n❌ {t('Tests failed with return code')} {status_code}")

        # Step 4: Cleanup
        lang = get_lang()
        keep_input = (
            input(t("Keep the temporary database? (y/N): ")).strip().lower()
        )
        keep = keep_input in (("o", "oui") if lang == "fr" else ("y", "yes"))
        if keep:
            print(f"{t('Database kept')}: {db_name}")
        else:
            print(
                f"\n--- {t('Cleaning up temporary database')} '{db_name}' ---"
            )
            cmd_drop = f"./odoo_bin.sh db --drop --database {db_name}"
            self.execute.exec_command_live(
                cmd_drop,
                source_erplibre=False,
                single_source_erplibre=True,
            )

    def execute_unit_tests(self):
        print(f"\n--- {t('Running unit tests')} ---")
        cmd = (
            ".venv.erplibre/bin/python -m unittest discover"
            " -s test -p 'test_*.py' -v"
        )
        status_code, output = self.execute.exec_command_live(
            cmd,
            source_erplibre=False,
            return_status_and_output=True,
        )
        if status_code == 0:
            print(f"\n✅ {t('All unit tests passed')}")
        else:
            print(
                f"\n❌ {t('Some unit tests failed, exit code')}: {status_code}"
            )

    def execute_pip_audit(self):
        versions, installed_versions, odoo_installed_version = (
            get_odoo_version()
        )

        # Build list of installed environments
        environments = {}
        key_i = 0
        for version_info in versions[::-1]:
            erplibre_version = version_info.get("erplibre_version")
            venv_path = f".venv.{erplibre_version}"
            req_path = f"requirement/requirements.{erplibre_version}.txt"
            odoo_version = f"odoo{version_info.get('odoo_version')}"

            if not os.path.isdir(venv_path):
                continue

            key_i += 1
            key_s = str(key_i)
            label = f"{key_s}: {erplibre_version}"
            if odoo_version == odoo_installed_version:
                label += f" - {t('Current')}"
            if version_info.get("Default"):
                label += f" - {t('Default')}"

            environments[key_s] = {
                "label": label,
                "venv_path": venv_path,
                "req_path": req_path,
                "erplibre_version": erplibre_version,
            }

        if not environments:
            print(
                t(
                    "No installed environment found. Install an Odoo version first."
                )
            )
            return

        # Show selection menu
        str_input = (
            f"💬 {t('Choose an environment for the audit:')}\n\t"
            + "\n\t".join([v["label"] for v in environments.values()])
            + f"\n\t0: {t('Back')}"
            + f"\n{t('Select: ')}"
        )
        env_input = ""
        while env_input not in environments and env_input != "0":
            if env_input:
                print(
                    f"{t('Error, cannot understand value')}" f" '{env_input}'"
                )
            env_input = input(str_input).strip()

        if env_input == "0":
            return

        selected = environments[env_input]
        venv_path = selected["venv_path"]
        req_path = selected["req_path"]

        if not os.path.isfile(req_path):
            print(f"{t('Dependencies file not found: ')}{req_path}")
            return

        # TODO support bash from parameter if open gnome-terminal
        cmd = f"pip-audit -r {req_path} -l;bash"
        print(f"{t('Execution: ')}{cmd}")
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
        choices = [
            {"prompt_description": t("base")},
            {"prompt_description": t("base + code_generator")},
            {"prompt_description": t("base + image_db")},
            {"prompt_description": t("all")},
            # {"prompt_description": "base + migration"},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def debug_ide(self):
        choices = [
            {"prompt_description": t("Debug todo.py")},
        ]
        help_info = self.fill_help_info(choices)

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
                print(t("Command not found !"))

    def generate_config_from_backup(self):
        file_name = self.db_manager.open_file_image_db()
        add_arg = f"--from_backup_name {file_name} --add_repo odoo18.0/addons/MathBenTech_development"
        self.generate_config(add_arg=add_arg)

    def generate_config_from_database(self):
        database_name = self.db_manager.select_database()
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

    def prompt_execute_selenium_and_run_db(
        self, db_name, extra_cmd_web_login=""
    ):
        cmd_server = f"./run.sh -d {db_name};bash"
        self.execute.exec_command_live(cmd_server)
        cmd_client = (
            f"sleep 3;./script/selenium/web_login.py{extra_cmd_web_login};bash"
        )
        self.execute.exec_command_live(cmd_client)

    def prompt_execute_selenium(self, command=None, extra_cmd_web_login=""):
        commands = []
        if not command:
            cmd = "./script/selenium/web_login.py"
        else:
            cmd = command

        if type(extra_cmd_web_login) is list:
            for item in extra_cmd_web_login:
                commands.append(cmd + item)
        else:
            commands.append(cmd + extra_cmd_web_login)

        if len(commands) == 1:
            self.execute.exec_command_live(commands[0])
        elif len(commands) > 1:
            new_cmd = "parallel ::: "
            for i, cmd in enumerate(commands):
                new_cmd += f' "sleep {1 * i};{cmd}"'
            self.execute.exec_command_live(new_cmd)

    def crash_diagnostic(self, e):
        # TODO show message at start if os.path.exists(ERROR_LOG_PATH)
        if os.path.exists(ERROR_LOG_PATH) and not os.path.exists(
            VENV_ERPLIBRE
        ):
            print("Got error : ")
            print(e)
            print("Got error at first execution.", ERROR_LOG_PATH)
            try:
                file = open(ERROR_LOG_PATH, "r")
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
        if os.path.exists(VENV_ERPLIBRE):
            print("Import error : ")
            print(e)
            # TODO auto-detect gnome-terminal, or choose another. Is it done already?
            self.restart_script(e)
            # self.prompt_install()

            # print(
            #     f"You forgot to activate source \nsource ./{VENV_ERPLIBRE}/bin/activate"
            # )
            # time.sleep(0.5)
            # cmd = "./script/todo/source_todo.sh"
            print("Re-execute TODO 🤖 or execute :")
            print()
            print(f"source {VENV_ERPLIBRE}/bin/activate;make")
            print()
            cmd = "./script/todo/todo.py"
            # # self.restart_script(e)
            try:
                # TODO duplicate
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
        database = self.db_manager.select_database()
        if database:
            cmd_server = f"./odoo_bin.sh shell -d {database}"
            status, databases = self.execute.exec_command_live(
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

    def callback_execute_custom_database(self, config):
        database_name = self.db_manager.select_database()
        self.prompt_execute_selenium_and_run_db(database_name)

    def process_kill_from_port(self):
        cfg = configparser.ConfigParser()
        cfg.read("./config.conf")
        http_port = cfg.getint("options", "http_port")

        status = self.execute.exec_command_live(
            f"./script/process/kill_process_by_port.py {http_port} --kill-tree --nb_parent 2",
            source_erplibre=False,
        )

    def restart_script(self, last_error):
        print(f"🤖 {t('Reboot TODO ...')}")
        # os.execv(sys.executable, ['python'] + sys.argv)
        # TODO mettre check que le répertoire est créé, s'il existe, auto-loop à corriger
        if os.path.exists(VENV_ERPLIBRE) and not os.path.exists(
            ERROR_LOG_PATH
        ):
            # TODO mettre check import suivant ne vont pas planter
            try:
                with open(ERROR_LOG_PATH, "w") as f_file:
                    f_file.write(str(last_error))
                    pass  # The file is created and closed here, no content is written
                print(
                    f"Try to reopen process with before :\nsource ./{VENV_ERPLIBRE}/bin/activate && exec python "
                    + " ".join(sys.argv)
                )
                os.execv(
                    "/bin/bash",
                    [
                        "/bin/bash",
                        "-c",
                        f"source ./{VENV_ERPLIBRE}/bin/activate && exec python "
                        + " ".join(sys.argv),
                    ],
                )
            except Exception as e:
                print("Error detect at first execution.")
                print(e)

    def on_dir_selected(self, dir_path):
        self.dir_path = dir_path
        todo_file_browser.exit_program()

    def callback_make_mobile_home(self, config):
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
        print(t("Keyboard interrupt"))
    finally:
        end_time = time.time()
        duration_sec = end_time - start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            humain_time = humanize.precisedelta(duration_delta)
            print(f"\n{t('TODO execution time')} {humain_time}\n")
        else:
            print(f"\n{t('TODO execution time')} {duration_sec:.2f} sec.\n")
