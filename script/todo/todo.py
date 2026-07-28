#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import configparser
import datetime
import getpass
import inspect
import json
import logging
import os
import re
import shlex
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
from script.todo.todo_i18n import lang_is_configured, set_lang, t
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
        help_info = f"""{self._menu_header()}
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
            help_info = f"""{self._menu_header()}
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
        help_info = f"""{self._menu_header()}

── {t("Development")} ──
[1] {t("Code - Developer tools")}
[2] {t("Config - Configuration file management")}
[3] {t("Run - Execute and install an instance")}
[4] {t("Test - Test an Odoo module")}
[5] {t("Process - Execution tools")}

── {t("Data")} ──
[6] {t("Database - Database tools")}

── {t("Sources & documentation")} ──
[7] {t("Git - Git tools")}
[8] {t("Update - Update all developed staging source code")}
[9] {t("Doc - Documentation search")}

── {t("AI & automation")} ──
[10] {t("GPT code - AI assistant tools")}
[11] {t("Automation - Demonstration of developed features")}

── {t("Deployment, network & security")} ──
[12] {t("Deploy - Deploy ERPLibre locally")}
[13] {t("Network - Network tools")}
[14] {t("Security - Dependency security audit")}

── {t("Preferences")} ──
[15] {t("Language - Change language / Changer la langue")}
[0] {t("Back")}
"""
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            elif status == "1":
                status = self.prompt_execute_code()
                if status is not False:
                    return
            elif status == "2":
                status = self.prompt_execute_config()
                if status is not False:
                    return
            elif status == "3":
                status = self.prompt_execute_instance()
                if status is not False:
                    return
            elif status == "4":
                status = self.prompt_execute_test()
                if status is not False:
                    return
            elif status == "5":
                status = self.prompt_execute_process()
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
                status = self.prompt_execute_update()
                if status is not False:
                    return
            elif status == "9":
                status = self.prompt_execute_doc()
                if status is not False:
                    return
            elif status == "10":
                status = self.prompt_execute_gpt_code()
                if status is not False:
                    return
            elif status == "11":
                status = self.prompt_execute_function()
                if status is not False:
                    return
            elif status == "12":
                status = self.prompt_execute_deploy()
                if status is not False:
                    return
            elif status == "13":
                status = self.prompt_execute_network()
                if status is not False:
                    return
            elif status == "14":
                status = self.prompt_execute_security()
                if status is not False:
                    return
            elif status == "15":
                status = self._change_language()
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
        if self._is_yes(first_installation_input):
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
            if self._is_yes(pycharm_configuration_input):
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

        # For numbered version selections, offer extra modules sub-menu
        if odoo_version_input.isdigit():
            extra_choices = {
                "1": (
                    "1",
                    f"1: {t('Standard install (without extra modules)')}",
                ),
                "2": (
                    "2",
                    f"2: {t('Install with extra modules (CybroOdoo - large, slow)')}",
                ),
                "0": ("0", f"0: {t('Back')}"),
            }
            extra_input = ""
            while extra_input not in extra_choices:
                if extra_input:
                    print(
                        f"{t('Error, cannot understand value')} '{extra_input}'"
                    )
                str_extra = (
                    f"💬 {t('Install type:')}\n\t"
                    + "\n\t".join([a[1] for a in extra_choices.values()])
                    + f"\n{t('Select: ')}"
                )
                extra_input = input(str_extra).strip()
            if extra_input == "0":
                return
            if extra_input == "2":
                cmd_intern = cmd_intern + " --with_extra"

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

    # Étiquettes du fil d'Ariane par méthode de menu. Le fil est dérivé de la
    # pile d'appels (aucune méthode de menu à modifier). Labels courts et
    # stables, pensés pour être copiés afin de situer précisément un menu.
    _MENU_LABELS = {
        "run": "TODO",
        "prompt_execute": "Execute",
        "execute_prompt_ia": "Question",
        "prompt_install": "Install",
        "prompt_execute_function": "Automation",
        "prompt_execute_code": "Code",
        "prompt_execute_config": "Config",
        "prompt_execute_database": "Database",
        "prompt_execute_doc": "Doc",
        "prompt_execute_git": "Git",
        "prompt_execute_git_local_server": "Git local server",
        "prompt_execute_gpt_code": "GPT code",
        "prompt_execute_process": "Process",
        "prompt_execute_instance": "Run",
        "prompt_execute_rtk": "RTK",
        "prompt_execute_update": "Update",
        "prompt_execute_deploy": "Deploy",
        "prompt_execute_qemu": "QEMU/KVM",
    }

    def _menu_header(self):
        """En-tête de menu : fil d'Ariane (dérivé de la pile d'appels) suivi de
        la ligne « Commande : ». Le fil situe le menu courant et se copie pour
        décrire sans ambiguïté où l'on se trouve."""
        crumbs = []
        for frame_info in reversed(inspect.stack()):
            if frame_info.frame.f_locals.get("self") is not self:
                continue
            label = self._MENU_LABELS.get(frame_info.function)
            if label and (not crumbs or crumbs[-1] != label):
                crumbs.append(label)
        header = ""
        if crumbs:
            header = "📍 " + " › ".join(crumbs) + "\n"
        return header + t("Command:")

    def fill_help_info(self, choices):
        # Une entrée {"section": "..."} affiche un titre de section SANS
        # consommer de numéro : la numérotation reste continue sur les vraies
        # commandes (compatible avec les elif codés en dur des menus).
        help_info = self._menu_header() + "\n"
        help_end = f"[0] {t('Back')}\n"
        n = 0
        for instance in choices:
            section = instance.get("section")
            if section:
                help_info += f"\n── {section} ──\n"
                continue
            n += 1
            desc_key = instance.get("prompt_description_key")
            if desc_key:
                desc = t(desc_key)
            else:
                desc = instance["prompt_description"]
            help_info += f"[{n}] " + desc + "\n"
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
            {"section": t("Local")},
            {"prompt_description": t("Clone ERPLibre locally (git clone)")},
            {"prompt_description": t("Configure sshfs")},
            {"section": t("SSH (remote host)")},
            {"prompt_description": t("SSH - Check connection")},
            {"prompt_description": t("SSH - Sync files (rsync)")},
            {"prompt_description": t("SSH - Install ERPLibre")},
            {"prompt_description": t("SSH - Start Odoo")},
            {"prompt_description": t("SSH - Stop Odoo")},
            {"prompt_description": t("SSH - Restart Odoo")},
            {"prompt_description": t("SSH - Service status")},
            {"prompt_description": t("SSH - View logs")},
            {"prompt_description": t("SSH - Run make target")},
            {"prompt_description": t("SSH - Install systemd service")},
            {"prompt_description": t("SSH - Configure nginx + SSL")},
            {"section": t("Virtualization & notifications")},
            {
                "prompt_description": t(
                    "Deploy - Install NTFY notification server"
                )
            },
            {
                "prompt_description": t(
                    "QEMU/KVM - Deploy an Ubuntu VM (libvirt)"
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
                self._deploy_clone_erplibre()
            elif status == "2":
                self._configure_sshfs()
            elif status == "3":
                self._deploy_ssh_check()
            elif status == "4":
                self._deploy_ssh_push()
            elif status == "5":
                self._deploy_ssh_install()
            elif status == "6":
                self._deploy_ssh_run()
            elif status == "7":
                self._deploy_ssh_stop()
            elif status == "8":
                self._deploy_ssh_restart()
            elif status == "9":
                self._deploy_ssh_status()
            elif status == "10":
                self._deploy_ssh_logs()
            elif status == "11":
                self._deploy_ssh_make()
            elif status == "12":
                self._deploy_ssh_install_systemd()
            elif status == "13":
                self._deploy_ssh_install_nginx()
            elif status == "14":
                self._deploy_ntfy_server()
            elif status == "15":
                self.prompt_execute_qemu()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------ #
    # QEMU / KVM (libvirt) VM deployment
    # ------------------------------------------------------------------ #
    def _qemu_script_path(self):
        """Chemin absolu vers script/qemu/deploy_qemu.py."""
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "qemu",
            "deploy_qemu.py",
        )
        return os.path.realpath(path)

    def _qemu_default_ssh_key(self):
        """Première clé publique SSH trouvée dans ~/.ssh, sinon ''."""
        for name in ("id_ed25519.pub", "id_rsa.pub"):
            path = os.path.expanduser(f"~/.ssh/{name}")
            if os.path.exists(path):
                return path
        return ""

    # distro -> (versions affichées, version par défaut). Source de vérité =
    # deploy_qemu.py ; ceci ne sert qu'au sélecteur interactif.
    _QEMU_DISTROS = {
        "ubuntu": (
            ["20.04", "22.04", "24.04", "25.10", "26.04"],
            "24.04",
        ),
        "debian": (["11", "12", "13"], "12"),
        "fedora": (["41", "42", "43", "44"], "42"),
        "arch": (["latest"], "latest"),
    }

    def _qemu_prompt_distro(self):
        """Demande la distribution (défaut : ubuntu)."""
        distros = list(self._QEMU_DISTROS)
        print(f"\n{t('Distribution:')}")
        for i, d in enumerate(distros, 1):
            print(f"  [{i}] {d}")
        sel = input(t("Choice (number or name, default: ubuntu): ")).strip()
        if not sel:
            return "ubuntu"
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(distros):
                return distros[idx]
        except ValueError:
            if sel in distros:
                return sel
        print(t("Invalid selection, using ubuntu"))
        return "ubuntu"

    def _qemu_prompt_version(self, distro):
        """Demande la version pour la distro (défaut = version par défaut)."""
        versions, default = self._QEMU_DISTROS.get(distro, ([], ""))
        print(f"\n{t('Version for')} {distro} :")
        for i, v in enumerate(versions, 1):
            suffix = " *" if v == default else ""
            print(f"  [{i}] {v}{suffix}")
        sel = input(
            f"{t('Choice (number or version, blank = default):')} "
        ).strip()
        if not sel:
            return default
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(versions):
                return versions[idx]
        except ValueError:
            if sel in versions:
                return sel
        print(f"{t('Invalid selection, using')} {default}")
        return default

    # Distros publiant des images cloud par architecture (cohérent avec
    # S390X_DISTROS / ARM64_DISTROS de deploy_qemu.py). amd64 : toutes.
    _QEMU_S390X_DISTROS = ("ubuntu",)
    _QEMU_ARM64_DISTROS = ("ubuntu", "debian", "fedora")
    # Alias distro pour l'affichage (jeton générique -> nom courant).
    _QEMU_ARCH_ALIAS = {"amd64": "x86_64", "arm64": "aarch64"}

    @staticmethod
    def _native_arch():
        """Architecture native de l'hôte, en jeton de deploy_qemu.py
        (amd64/arm64/s390x). Défaut amd64 si indéterminée."""
        try:
            machine = os.uname().machine
        except (AttributeError, OSError):
            machine = ""
        return {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
            "s390x": "s390x",
        }.get(machine, "amd64")

    def _qemu_arch_distros(self, arch):
        """Distros supportant `arch` (None = toutes, cas amd64)."""
        if arch == "s390x":
            return self._QEMU_S390X_DISTROS
        if arch == "arm64":
            return self._QEMU_ARM64_DISTROS
        return None

    def _qemu_ask_arch(self, opts, native):
        """Affiche les architectures `opts` (natif marqué d'un *) et renvoie le
        choix. Toute arch non native est ÉMULÉE (TCG, lente)."""
        print(f"\n{t('Architecture:')}")
        for i, a in enumerate(opts, 1):
            alias = self._QEMU_ARCH_ALIAS.get(a)
            label = f"{a} ({alias})" if alias else a
            if a == native:
                label += f" — {t('native')} *"
            elif a == "s390x":
                label += f"  ({t('IBM Z — emulated, slow; Ubuntu only')})"
            elif a == "arm64":
                label += f"  ({t('ARM 64-bit — emulated, slow')})"
            else:
                label += f"  ({t('emulated, slow')})"
            print(f"  [{i}] {label}")
        sel = (
            input(f"{t('Choice (number or name, blank = native):')} ")
            .strip()
            .lower()
        )
        chosen = native
        if sel:
            chosen = None
            for i, a in enumerate(opts, 1):
                if sel in (str(i), a, self._QEMU_ARCH_ALIAS.get(a)):
                    chosen = a
                    break
            if chosen is None:
                print(f"{t('Invalid selection, using')} {native}")
                chosen = native
        if chosen != native:
            warn = t(
                "This architecture is emulated (TCG): boot and install are"
                " much slower than the native one."
            )
            print(f"⚠  {warn}")
        return chosen

    def _qemu_prompt_arch(self, distro):
        """Architecture pour un déploiement de VM unique. Propose amd64, plus
        arm64/s390x si la distro choisie publie ces images."""
        opts = ["amd64"]
        if distro in self._QEMU_ARM64_DISTROS:
            opts.append("arm64")
        if distro in self._QEMU_S390X_DISTROS:
            opts.append("s390x")
        if len(opts) == 1:
            return "amd64"  # rien à demander
        return self._qemu_ask_arch(opts, self._native_arch())

    def _qemu_prompt_infra_arch(self):
        """Architecture du parc (défaut : native de l'hôte, marquée d'un *).
        Toute arch non native est émulée ; le catalogue est ensuite restreint
        aux distros publiant cette arch."""
        native = self._native_arch()
        opts = ["amd64", "arm64", "s390x"]
        if native not in opts:  # hôte exotique : garder le natif en tête
            opts.insert(0, native)
        return self._qemu_ask_arch(opts, native)

    def _qemu_list_images(self):
        """Affiche la liste des distros/versions et leurs specs."""
        cmd = f"{self._qemu_script_path()} --list-images"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def prompt_execute_qemu(self):
        print(f"🤖 {t('Deploy a QEMU/KVM virtual machine (libvirt)!')}")
        script_path = self._qemu_script_path()
        if not os.path.isfile(script_path):
            print(f"{t('QEMU deploy script not found: ')}{script_path}")
            return False
        choices = [
            {"section": t("Deployment")},
            {"prompt_description": t("Deploy a new VM")},
            {
                "prompt_description": t(
                    "Preview a deployment (dry-run, no sudo)"
                )
            },
            {"prompt_description": t("Download a cloud image only")},
            {
                "prompt_description": t(
                    "Deploy ERPLibre infra (one minimal VM per image)"
                )
            },
            {"section": t("Manage")},
            {"prompt_description": t("List VMs (virsh list --all)")},
            {"prompt_description": t("Show a VM IP address")},
            {"prompt_description": t("Open the console on a VM")},
            {"prompt_description": t("Delete VM(s)")},
            {"prompt_description": t("Clean up QEMU (orphan files)")},
            {"section": t("Catalog")},
            {"prompt_description": t("List available images and specs")},
        ]
        config_entries = self.config_file.get_config("qemu_from_makefile")
        if config_entries:
            choices.extend(config_entries)
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._qemu_deploy_vm(dry_run=False)
            elif status == "2":
                self._qemu_deploy_vm(dry_run=True)
            elif status == "3":
                self._qemu_download_image()
            elif status == "4":
                self._qemu_deploy_infra()
            elif status == "5":
                self._qemu_list_vms()
            elif status == "6":
                self._qemu_show_ip()
            elif status == "7":
                self._qemu_console()
            elif status == "8":
                self._qemu_delete_vm()
            elif status == "9":
                self._qemu_cleanup()
            elif status == "10":
                self._qemu_list_images()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    # Ignore les entrées de section pour mapper le numéro
                    # affiché sur la bonne commande (config incluse).
                    real = [c for c in choices if not c.get("section")]
                    if 0 < int_cmd <= len(real):
                        cmd_no_found = False
                        self.execute_from_configuration(real[int_cmd - 1])
                except ValueError:
                    pass
                if cmd_no_found:
                    print(t("Command not found !"))

    @staticmethod
    def _normalize_disk_size(size):
        """« 30 » -> « 30G » (unité par défaut Go). Laisse « 30G », « 1T »… ou
        vide tels quels. Sans unité, qemu-img interpréterait des OCTETS."""
        size = size.strip()
        if re.fullmatch(r"\d+", size):
            return size + "G"
        return size

    def _qemu_deploy_vm(self, dry_run=False):
        script_path = self._qemu_script_path()
        # Distro + version d'abord : permet de proposer un nom par défaut.
        distro = self._qemu_prompt_distro()
        version = self._qemu_prompt_version(distro)
        arch = self._qemu_prompt_arch(distro)
        default_name = self._qemu_infra_name(distro, version, arch)
        name = (
            input(f"{t('VM name (default: ')}{default_name}): ").strip()
            or default_name
        )
        # Laisser vide => le script applique le minimum requis par la version
        # choisie (libosinfo). On n'envoie alors pas le flag.
        memory = input(t("RAM in MB (blank = version minimum): ")).strip()
        vcpus = input(t("vCPUs (default: 2): ")).strip()
        disk_size = self._normalize_disk_size(
            input(t("Disk size (blank = version min; e.g. 30G, 1T): ")).strip()
        )

        default_key = self._qemu_default_ssh_key()
        key_hint = default_key or t("none")
        ssh_key = input(f"{t('SSH public key path')} ({key_hint}): ").strip()
        if not ssh_key:
            ssh_key = default_key
        if ssh_key:
            # Résout ~ avec le HOME de l'utilisateur courant : le script tourne
            # sous sudo (HOME=/root) et ne pourrait pas déduire ~ correctement.
            ssh_key = os.path.expanduser(ssh_key)

        # Mot de passe console (défaut « erplibre ») : permet la connexion par
        # la console série (virsh console) EN PLUS de la clé SSH. Sans lui, le
        # compte est verrouillé et la console refuse tout login.
        password = (
            input(
                t("Console password for 'erplibre' (default: erplibre): ")
            ).strip()
            or "erplibre"
        )

        force = False
        if not dry_run:
            ans = input(t("Overwrite existing VM disk if present? (y/N): "))
            force = self._is_yes(ans)

        parts = []
        if not dry_run:
            parts.append("sudo")
        parts.append(script_path)
        parts += ["--name", name, "--distro", distro, "--version", version]
        if arch and arch != "amd64":
            parts += ["--arch", arch]
        if memory:
            parts += ["--memory", memory]
        if vcpus:
            parts += ["--vcpus", vcpus]
        if disk_size:
            parts += ["--disk-size", disk_size]
        if ssh_key:
            parts += ["--ssh-key", ssh_key]
        if password:
            parts += ["--password", password]
        if force:
            parts.append("--force")
        if dry_run:
            parts.append("--dry-run")
        else:
            parts.append("-y")  # accepte l'installation des dépendances

        cmd = " ".join(shlex.quote(p) for p in parts)
        print(f"{t('Will execute:')} {cmd}")
        if password:
            print(f"🔑 {t('Console/SSH login:')} erplibre / {password}")
        status = self.execute.exec_command_live(cmd, source_erplibre=False)

        # Arrêt net sur erreur : sinon on enchaînait sur l'attente d'IP d'une
        # VM jamais créée (blocage infini), l'utilisateur ne voyant rien.
        if status != 0:
            print(f"\n❌ {t('Deployment failed (see the error above).')}")
            return

        if dry_run:
            return

        # Option : installer ERPLibre (clone + make install_os + install_odoo).
        if self._is_yes(
            input(
                t("Install ERPLibre into ~/git/erplibre on this VM? (y/N): ")
            )
        ):
            branch = self._qemu_pick_branch()
            if self._is_yes(
                input(t("Interactive monitoring dashboard? (y/N): "))
            ):
                self._qemu_install_erplibre_monitored([name], branch)
            else:
                self._qemu_install_erplibre_vm(name, ssh_key, branch)

        # Proposer d'enregistrer la VM dans ~/.ssh/config (après le 1er boot).
        self._qemu_offer_ssh_config(name, "erplibre")

    def _qemu_download_image(self):
        script_path = self._qemu_script_path()
        distro = self._qemu_prompt_distro()
        version = self._qemu_prompt_version(distro)
        ans = input(t("Verify SHA256 after download? (y/N): "))
        parts = [
            "sudo",
            script_path,
            "--download-only",
            "--distro",
            distro,
            "--version",
            version,
        ]
        if self._is_yes(ans):
            parts.append("--verify")
        cmd = " ".join(shlex.quote(p) for p in parts)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_list_vms(self):
        cmd = "sudo virsh list --all"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_show_ip(self):
        # Affiche d'abord les VM (avec leur ID) pour que l'utilisateur sache
        # quel nom/ID saisir, puis demande lequel (ou « all » pour toutes).
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID (or 'all'): ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        if name.lower() in ("all", "tous", "*"):
            targets = self._qemu_list_domains()
            if not targets:
                print(t("No VM found."))
                return
        else:
            targets = [name]
        for tgt in targets:
            cmd = f"sudo virsh domifaddr {shlex.quote(tgt)} --source lease"
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_console(self):
        # Liste les VM, demande laquelle, rappelle comment quitter (Ctrl+])
        # puis ouvre la console série interactive.
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        print(f"\n💡 {t('To leave the console, press Ctrl+] (then Enter).')}")
        print(
            f"👤 {t('Default login (if set at deploy): erplibre / erplibre')}"
        )
        cmd = f"sudo virsh console {shlex.quote(name)}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_offer_ssh_config(self, name, user):
        """Propose d'enregistrer la VM dans ~/.ssh/config (bloc Host name)."""
        if not self._is_yes(input(t("Add this VM to ~/.ssh/config? (y/N): "))):
            return
        print(t("Waiting for the VM IP (DHCP lease)..."))
        ip = self._qemu_vm_ip(name)
        if not ip:
            print(t("No IP yet; add it later once the VM has booted."))
            return
        self._write_ssh_config_entry(name, user, ip)

    def _write_ssh_config_entry(self, host, user, ip):
        """Écrit/remplace un bloc « Host <host> » dans ~/.ssh/config."""
        cfg = os.path.expanduser("~/.ssh/config")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        existing = ""
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                existing = fh.read()
        # Retire un ancien bloc du même Host (ses lignes indentées). Pas de
        # drapeau DOTALL : « . » ne doit PAS traverser les sauts de ligne,
        # sinon .* engloutirait tout jusqu'à la fin du fichier et effacerait
        # les entrées suivantes.
        pattern = re.compile(
            rf"(?m)^[ \t]*Host[ \t]+{re.escape(host)}[ \t]*\n"
            r"(?:[ \t]+[^\n]*\n?)*"
        )
        existing = pattern.sub("", existing).rstrip("\n")
        block = (
            f"Host {host}\n"
            f"    HostName {ip}\n"
            f"    User {user}\n"
            # IP DHCP réutilisées entre VM -> on évite l'erreur de clé d'hôte.
            f"    StrictHostKeyChecking no\n"
            f"    UserKnownHostsFile /dev/null\n"
        )
        content = (existing + "\n\n" + block) if existing else block
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(cfg, 0o600)
        print(f"✅ {t('Added to ~/.ssh/config:')} ssh {host}")

    def _qemu_list_domains(self):
        """Noms des VM libvirt définies (via virsh)."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "list", "--all", "--name"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return [n for n in res.stdout.split() if n.strip()]

    def _qemu_delete_vm(self):
        """Efface une ou plusieurs VM (arrêt + undefine), disques en option."""
        self._qemu_list_vms()
        print()
        names = self._qemu_list_domains()
        if not names:
            print(t("No VM found."))
            return
        print(f"\n{t('Select VMs to delete:')}")
        for i, n in enumerate(names, 1):
            print(f"  [{i}] {n}")
        print(f"  [all] {t('select all')}")
        raw = input(t("Selection (numbers, or 'all'): ")).strip()
        if not raw:
            print(t("Nothing selected."))
            return
        if raw.lower() in ("all", "*"):
            chosen = list(names)
        else:
            chosen = self._parse_index_selection(raw.lower(), names)
        if not chosen:
            print(t("Nothing selected."))
            return

        del_disks = self._is_yes(
            input(t("Also delete disk images (qcow2 + seed ISO)? (y/N): "))
        )

        print(f"\n{t('Will delete:')} {', '.join(chosen)}")
        if del_disks:
            print(f"  + {t('disk images and seed ISOs')}")
        else:
            print(f"  ({t('disks kept')})")
        if not self._is_yes(input(t("Confirm deletion? (y/N): "))):
            print(t("Cancelled."))
            return

        disk_dir = "/var/lib/libvirt/images"
        seed_dir = "/var/lib/libvirt/images/iso"
        for name in chosen:
            q = shlex.quote(name)
            # Éteindre si en cours, puis retirer la définition (+ nvram si
            # UEFI ; repli sans l'option pour les vieilles versions de virsh).
            cmd = (
                f"sudo virsh destroy {q} 2>/dev/null; "
                f"sudo virsh undefine {q} --nvram 2>/dev/null "
                f"|| sudo virsh undefine {q}"
            )
            if del_disks:
                disk = shlex.quote(f"{disk_dir}/{name}.qcow2")
                seed = shlex.quote(f"{seed_dir}/{name}-seed.iso")
                cmd += f"; sudo rm -f {disk} {seed}"
            print(f"\n▶ {name}: {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"\n✅ {t('Deletion done.')}")

    @staticmethod
    def _human_size(n):
        """Octets -> taille lisible (Ko/Mo/Go…)."""
        size = float(n)
        for unit in ("o", "Ko", "Mo", "Go", "To"):
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.0f} Po"

    @staticmethod
    def _qemu_find_files(directory, pattern):
        """(taille, chemin) des fichiers du répertoire (via sudo find)."""
        try:
            res = subprocess.run(
                [
                    "sudo",
                    "find",
                    directory,
                    "-maxdepth",
                    "1",
                    "-type",
                    "f",
                    "-name",
                    pattern,
                    "-printf",
                    "%s\t%p\n",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        out = []
        for line in res.stdout.splitlines():
            if "\t" in line:
                size, path = line.split("\t", 1)
                out.append((int(size), path))
        return out

    def _cleanup_delete_files(self, title, items, prompt):
        """items : [(taille, chemin)]. Liste, confirme, puis « sudo rm -f »."""
        if not items:
            return
        total = sum(s for s, _ in items)
        print(
            f"\n{title} — {self._human_size(total)}, "
            f"{len(items)} {t('files')} :"
        )
        for size, path in sorted(items, key=lambda o: -o[0]):
            print(f"  {self._human_size(size):>9}  {path}")
        if not self._is_yes(input(prompt)):
            print(t("Cancelled."))
            return
        paths = " ".join(shlex.quote(p) for _, p in items)
        cmd = f"sudo rm -f {paths}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"✅ {t('Cleanup done.')}")

    def _qemu_domain_macs(self):
        """MACs de toutes les VM définies (pour repérer les baux périmés)."""
        macs = set()
        for name in self._qemu_list_domains():
            try:
                res = subprocess.run(
                    ["sudo", "virsh", "domiflist", name],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            macs.update(
                m.lower()
                for m in re.findall(
                    r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", res.stdout
                )
            )
        return macs

    def _qemu_cleanup(self):
        """Repère les restes QEMU orphelins et propose de les effacer."""
        print(f"🧹 {t('Scanning for orphan QEMU files...')}")
        disk_dir = "/var/lib/libvirt/images"
        seed_dir = "/var/lib/libvirt/images/iso"
        nvram_dir = "/var/lib/libvirt/qemu/nvram"
        domains = set(self._qemu_list_domains())

        # 1) Fichiers orphelins : disques / seeds / .part / nvram.
        orphans = []  # (taille, chemin, motif)
        for size, path in self._qemu_find_files(disk_dir, "*.qcow2"):
            if os.path.basename(path)[: -len(".qcow2")] not in domains:
                orphans.append((size, path, t("orphan disk")))
        for size, path in self._qemu_find_files(seed_dir, "*-seed.iso"):
            if os.path.basename(path)[: -len("-seed.iso")] not in domains:
                orphans.append((size, path, t("orphan seed")))
        for size, path in self._qemu_find_files(seed_dir, "*.part"):
            orphans.append((size, path, t("partial download")))
        for size, path in self._qemu_find_files(nvram_dir, "*"):
            stem = re.sub(r"(_VARS)?\.fd$", "", os.path.basename(path))
            if stem not in domains:
                orphans.append((size, path, t("orphan UEFI nvram")))
        if orphans:
            total = sum(o[0] for o in orphans)
            print(f"\n{t('Orphan files:')}")
            for size, path, reason in sorted(orphans, key=lambda o: -o[0]):
                print(f"  {self._human_size(size):>9}  {path}  [{reason}]")
            print(
                f"\n  {t('Total:')} {self._human_size(total)} "
                f"({len(orphans)} {t('files')})"
            )
            if self._is_yes(input(t("Delete these orphan files? (y/N): "))):
                paths = " ".join(shlex.quote(o[1]) for o in orphans)
                cmd = f"sudo rm -f {paths}"
                print(f"{t('Will execute:')} {cmd}")
                self.execute.exec_command_live(cmd, source_erplibre=False)
                print(f"✅ {t('Cleanup done.')}")
            else:
                print(t("Cancelled."))
        else:
            print(f"✅ {t('No orphan files found.')}")

        # 2) Domaines fantômes (définis mais disque manquant).
        self._cleanup_ghost_domains()
        # 3) Doublons d'images nommées par codename (avant /releases/).
        dups = [
            (s, p)
            for s, p in self._qemu_find_files(
                seed_dir, "*-server-cloudimg-*.img"
            )
            if not os.path.basename(p).startswith("ubuntu-")
        ]
        self._cleanup_delete_files(
            t("Stale codename-named Ubuntu images (duplicates):"),
            dups,
            t("Delete these duplicate images? (y/N): "),
        )
        # 4) Entrées ~/.ssh/config orphelines (erplibre-* sans VM).
        self._cleanup_ssh_config(domains)
        # 5) Baux DHCP périmés.
        self._cleanup_stale_leases()
        # 6) Tout le cache d'images de base (option lourde : re-téléchargement).
        cached = [
            (s, p)
            for s, p in self._qemu_find_files(seed_dir, "*")
            if not p.endswith("-seed.iso") and not p.endswith(".part")
        ]
        self._cleanup_delete_files(
            t("All cached base images (reusable):"),
            cached,
            t("Delete ALL cached base images? (y/N): "),
        )

    def _cleanup_ghost_domains(self):
        """VM définies dont plus aucun disque n'existe -> propose undefine."""
        ghosts = []
        for name in self._qemu_list_domains():
            try:
                res = subprocess.run(
                    ["sudo", "virsh", "domblklist", name, "--details"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            srcs = []
            for line in res.stdout.splitlines():
                p = line.split()
                if len(p) >= 4 and p[1] == "disk" and p[3] not in ("-", ""):
                    srcs.append(p[3])
            if srcs and all(
                subprocess.run(
                    ["sudo", "test", "-e", s], timeout=10
                ).returncode
                != 0
                for s in srcs
            ):
                ghosts.append(name)
        if not ghosts:
            return
        print(
            f"\n{t('Ghost domains (defined but disk missing):')} "
            f"{', '.join(ghosts)}"
        )
        if not self._is_yes(input(t("Undefine these ghost domains? (y/N): "))):
            print(t("Cancelled."))
            return
        for name in ghosts:
            q = shlex.quote(name)
            cmd = (
                f"sudo virsh destroy {q} 2>/dev/null; "
                f"sudo virsh undefine {q} --nvram 2>/dev/null "
                f"|| sudo virsh undefine {q}"
            )
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"✅ {t('Cleanup done.')}")

    def _cleanup_ssh_config(self, domains):
        """Retire les blocs « Host erplibre-* » sans VM correspondante (on ne
        touche jamais aux autres hôtes SSH personnels)."""
        cfg = os.path.expanduser("~/.ssh/config")
        if not os.path.exists(cfg):
            return
        with open(cfg, encoding="utf-8") as fh:
            content = fh.read()
        hosts = re.findall(r"(?m)^[ \t]*Host[ \t]+(\S+)", content)
        orphans = [
            h for h in hosts if h.startswith("erplibre-") and h not in domains
        ]
        if not orphans:
            return
        print(f"\n{t('Orphan ~/.ssh/config entries:')} {', '.join(orphans)}")
        if not self._is_yes(
            input(t("Remove these ~/.ssh/config entries? (y/N): "))
        ):
            print(t("Cancelled."))
            return
        for h in orphans:
            pat = re.compile(
                rf"(?m)^[ \t]*Host[ \t]+{re.escape(h)}[ \t]*\n"
                r"(?:[ \t]+[^\n]*\n?)*"
            )
            content = pat.sub("", content)
        content = content.strip("\n")
        content = content + "\n" if content else ""
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(cfg, 0o600)
        print(f"✅ {t('Cleanup done.')}")

    def _cleanup_stale_leases(self):
        """Baux DHCP libvirt dont la MAC n'appartient à aucune VM (best-effort :
        les baux expirent d'eux-mêmes)."""
        status = "/var/lib/libvirt/dnsmasq/virbr0.status"
        try:
            res = subprocess.run(
                ["sudo", "cat", status],
                capture_output=True,
                text=True,
                timeout=15,
            )
            leases = json.loads(res.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError):
            return
        if not isinstance(leases, list) or not leases:
            return
        macs = self._qemu_domain_macs()
        stale = [
            ln
            for ln in leases
            if str(ln.get("mac-address", "")).lower() not in macs
        ]
        if not stale:
            return
        print(f"\n{t('Stale DHCP leases (no matching VM):')}")
        for ln in stale:
            print(
                f"  {ln.get('ip-address', '?'):<16} "
                f"{ln.get('mac-address', '?')}  {ln.get('hostname', '')}"
            )
        if not self._is_yes(input(t("Clear these stale leases? (y/N): "))):
            print(t("Cancelled."))
            return
        kept = [ln for ln in leases if ln not in stale]
        tmp = os.path.join("/tmp", f"virbr0.status.{os.getpid()}.json")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(kept, fh)
        cmd = (
            f"sudo cp {shlex.quote(tmp)} {status} && "
            "sudo pkill -HUP -F /var/lib/libvirt/dnsmasq/virbr0.pid "
            "2>/dev/null || true"
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"✅ {t('Cleanup done.')}")

    # ------------------------------------------------------------------ #
    # QEMU : déploiement d'un parc « infra ERPLibre »
    # ------------------------------------------------------------------ #
    ERPLIBRE_GIT_URL = "https://github.com/erplibre/erplibre"

    def _qemu_import_module(self):
        """Importe deploy_qemu.py comme module (source de vérité des specs)."""
        import importlib.util

        path = self._qemu_script_path()
        spec = importlib.util.spec_from_file_location("deploy_qemu", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @classmethod
    def _qemu_infra_name(cls, distro, version, arch=None):
        """Nom de VM stable pour le parc, ex. erplibre-ubuntu-2404. Ajoute un
        suffixe d'architecture quand elle diffère de la native de l'hôte (ex.
        erplibre-ubuntu-2604-s390x sur un hôte amd64) pour éviter les collisions
        de noms entre archis et rendre l'archi visible."""
        base = f"erplibre-{distro}-{version.replace('.', '')}"
        if arch and arch != cls._native_arch():
            base += f"-{arch}"
        return base

    @staticmethod
    def _parse_disk_gb(size):
        """« 20G » -> 20 (Go, best effort)."""
        m = re.match(r"\s*(\d+)", str(size))
        return int(m.group(1)) if m else 0

    @staticmethod
    def _is_yes(ans):
        """Réponse affirmative, FR et EN (o/oui/y/yes)."""
        return ans.strip().lower() in ("y", "yes", "o", "oui")

    @staticmethod
    def _is_no(ans):
        """Réponse négative explicite, FR et EN (n/no/non). Utile pour les
        invites « défaut oui » où tout sauf « non » vaut oui."""
        return ans.strip().lower() in ("n", "no", "non")

    @staticmethod
    def _host_free_ram_mb():
        """RAM disponible de l'hôte en Mo (MemAvailable), 0 si inconnu."""
        try:
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            pass
        return 0

    @staticmethod
    def _parse_index_selection(raw, options):
        """« 1 3 » ou « 1,3 » -> sous-liste d'options (indices 1-based)."""
        chosen = []
        for tok in re.split(r"[\s,]+", raw.strip()):
            if not tok:
                continue
            try:
                idx = int(tok) - 1
            except ValueError:
                if tok in options and tok not in chosen:
                    chosen.append(tok)
                continue
            if 0 <= idx < len(options) and options[idx] not in chosen:
                chosen.append(options[idx])
        return chosen

    def _qemu_domain_exists(self, name):
        """Vrai si une VM libvirt de ce nom est déjà définie."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "dominfo", name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _qemu_vm_ip(self, name, timeout=90):
        """Attend puis renvoie l'IPv4 d'une VM (bail DHCP), sinon None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                res = subprocess.run(
                    ["sudo", "virsh", "domifaddr", name, "--source", "lease"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)", res.stdout)
            if m:
                return m.group(1)
            time.sleep(3)
        return None

    def _qemu_pick_branch(self):
        """Liste les branches distantes d'ERPLibre et en fait choisir une."""
        print(f"\n{t('Fetching ERPLibre branch list...')}")
        branches = []
        try:
            res = subprocess.run(
                ["git", "ls-remote", "--heads", self.ERPLIBRE_GIT_URL],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in res.stdout.splitlines():
                ref = line.split("\t")[-1]
                if ref.startswith("refs/heads/"):
                    branches.append(ref[len("refs/heads/") :])
        except (OSError, subprocess.SubprocessError):
            pass
        default = (
            "master"
            if "master" in branches
            else (branches[0] if branches else "master")
        )
        if not branches:
            return (
                input(f"{t('Branch (default:')} {default}): ").strip()
                or default
            )
        branches.sort()
        print(f"{t('Branches:')}")
        for i, b in enumerate(branches, 1):
            star = " *" if b == default else ""
            print(f"  [{i}] {b}{star}")
        sel = input(f"{t('Choice (number or name, default:')} {default}): ")
        sel = sel.strip()
        if not sel:
            return default
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(branches):
                return branches[idx]
        except ValueError:
            if sel in branches:
                return sel
        return default

    # Cible d'installation Odoo exécutée dans la VM (défaut ERPLibre 1.6.0).
    ERPLIBRE_ODOO_TARGET = "install_odoo_18"
    # Go ajoutés au disque quand on installe ERPLibre (le minimum d'image ne
    # laisse que ~97 Mo libres après l'installation).
    ERPLIBRE_EXTRA_DISK_GB = 5

    @staticmethod
    def _qemu_wait_ssh(ip, user="erplibre", timeout=1200):
        """Attend que sshd réponde ET que cloud-init soit TERMINÉ, via des
        connexions COURTES successives. Au 1er boot, cloud-init régénère les
        clés d'hôte et REDÉMARRE sshd : attendre la fin de cloud-init AVANT de
        lancer l'install évite qu'une session longue soit tuée (« Connection
        closed by remote host », exit 255 — cas Fedora). True si prête."""
        opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=8 -o BatchMode=yes"
        )
        # On imprime toujours l'état (|| true) pour matcher sur le TEXTE :
        # « status: running » n'a pas de code de sortie fiable selon la version.
        probe = (
            "if command -v cloud-init >/dev/null 2>&1; then "
            "cloud-init status 2>/dev/null || true; else echo nocloudinit; fi"
        )
        ready = ("done", "disabled", "error", "degraded", "nocloudinit")
        deadline = time.time() + timeout
        ssh_up = False
        while time.time() < deadline:
            try:
                res = subprocess.run(
                    f"ssh {opts} {user}@{ip} {shlex.quote(probe)}",
                    shell=True,
                    capture_output=True,
                    timeout=20,
                    text=True,
                )
                out = res.stdout or ""
            except (OSError, subprocess.SubprocessError):
                out = ""
            if out.strip():
                ssh_up = True  # sshd a répondu
            if any(k in out for k in ready):
                return True
            time.sleep(5)
        # cloud-init pas confirmé fini dans le délai : on tente quand même si
        # sshd répondait au moins (mieux qu'un abandon silencieux).
        return ssh_up

    def _qemu_erplibre_remote_cmd(self, branch):
        """Script d'installation ERPLibre exécuté DANS la VM (curl/git/make
        puis clone + make install_os + make install_odoo_18)."""
        return (
            "set -e; "
            # Attendre la FIN de cloud-init : pendant sa phase « paquets » il
            # tient le verrou apt/dnf/pacman -> sinon « unable to lock
            # database » (Arch) / « Could not get lock » (apt). timeout pour ne
            # pas bloquer indéfiniment si cloud-init traîne.
            "command -v cloud-init >/dev/null 2>&1 && "
            "sudo timeout 900 cloud-init status --wait >/dev/null 2>&1 "
            "|| true; "
            # Outils d'amorçage (absents des images cloud minimales) : curl,
            # git, make. Chaque branche RAFRAÎCHIT d'abord les dépôts pour que
            # la VM soit la plus rapide possible (miroirs à jour / les plus
            # rapides), puis installe. Supporte apt (Debian/Ubuntu), dnf/yum
            # (Fedora) et pacman (Arch).
            "PKGS='curl git make'; "
            "if command -v apt-get >/dev/null 2>&1; then "
            # update best-effort (|| true) puis install OBLIGATOIRE : sans le
            # « || true », un « apt-get update » en échec (réseau) sautait
            # l'install sans erreur (liste &&) -> git/make absents ensuite.
            "sudo apt-get update -qq || true; "
            "sudo apt-get install -y $PKGS; "
            "elif command -v dnf >/dev/null 2>&1; then "
            # makecache (dnf5 choisit les miroirs les plus rapides) puis
            # install --refresh ; retry avec « clean all » car les images
            # cloud fraîches ratent parfois la vérif GPG/checksum d'un miroir.
            "sudo dnf -q makecache || true; "
            "sudo dnf install -y --refresh $PKGS || "
            "{ sudo dnf clean all; sudo dnf install -y --refresh $PKGS; }; "
            "elif command -v pacman >/dev/null 2>&1; then "
            # Verrou pacman périmé (cloud-init interrompu) : le retirer SEULEMENT
            # si aucun pacman ne tourne, sinon on attend qu'il se libère.
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            # Arch : reflector sélectionne les miroirs HTTPS les plus rapides,
            # puis MISE À JOUR COMPLÈTE (-Syu) : Arch (rolling) ne supporte pas
            # les màj partielles ; sur une image cloud à la glibc ancienne, un
            # « pacman -S <paquet récent> » casse avec « GLIBC_x.yy not found ».
            "sudo pacman -Sy --needed --noconfirm reflector || true; "
            "sudo reflector --latest 20 --protocol https --sort rate "
            "--save /etc/pacman.d/mirrorlist || true; "
            "sudo pacman -Syu --noconfirm || true; "
            "sudo pacman -S --needed --noconfirm $PKGS; "
            "elif command -v yum >/dev/null 2>&1; then "
            "sudo yum makecache -q || true; sudo yum install -y $PKGS; "
            "else echo 'Aucun gestionnaire de paquets "
            "(apt/dnf/pacman/yum)'; exit 1; fi; "
            # Vérifie explicitement que tout est là : erreur nette plutôt
            # qu'un « command not found » cryptique plus loin.
            "for t in curl git make; do command -v $t >/dev/null 2>&1 || "
            '{ echo "Outil manquant apres installation: $t '
            '(reseau de la VM ?)"; exit 1; }; done; '
            "mkdir -p ~/git; "
            "if [ ! -d ~/git/erplibre/.git ]; then "
            f"git clone --branch {shlex.quote(branch)} "
            f"{self.ERPLIBRE_GIT_URL} ~/git/erplibre; fi; "
            # Installation : dépendances système puis Odoo.
            "cd ~/git/erplibre && make install_os && "
            f"make {self.ERPLIBRE_ODOO_TARGET}"
        )

    def _qemu_install_erplibre_monitored(self, names, branch):
        """Lance l'install ERPLibre en parallèle DÉTACHÉE sur les VM et ouvre
        le dashboard Textual. Quitter le dashboard n'arrête pas les installs.
        """
        from script.todo.qemu_install_monitor import (
            launch_installs,
            run_monitor,
        )

        remote = self._qemu_erplibre_remote_cmd(branch)
        vms = []
        for name in names:
            print(f"  {name}: {t('resolving IP...')}")
            ip = self._qemu_vm_ip(name)
            if ip:
                vms.append({"name": name, "ip": ip})
            else:
                print(f"  {name}: {t('no IP, skipped.')}")
        if not vms:
            print(t("No VM to install."))
            return
        manifest = launch_installs(vms, branch, remote)
        print(f"\n🖥  {t('Opening the interactive monitor...')}")
        # Affiche tous les chemins de log (pour les consulter/partager même si
        # on quitte le dashboard avant la fin).
        print(f"  {t('Log files:')}")
        with open(manifest, encoding="utf-8") as _fh:
            for entry in json.load(_fh)["vms"]:
                print(f"    {entry['log']}")
        try:
            run_monitor(manifest)
        except ImportError:
            # textual absent : les installs tournent déjà (détachées), on ne
            # plante pas — on indique juste où sont les logs.
            print(f"  {t('Install textual for the dashboard (pip).')}")
        print(
            f"\n{t('Monitor closed. Installs keep running in the background.')}"
        )
        logdir = os.path.dirname(manifest)
        print(f"  {t('Logs:')} {logdir}")
        # Commande prête à copier pour relire/partager tous les logs.
        print(f"  {t('Read the logs:')} tail -n +1 {logdir}/*.log")

    def _qemu_install_erplibre_vm(self, name, ssh_key, branch):
        """Clone ERPLibre (branche donnée) dans ~/git/erplibre de la VM puis
        exécute « make install_os » et « make install_odoo_18 » (streamé)."""
        ip = self._qemu_vm_ip(name)
        if not ip:
            print(
                f"  {name}: {t('no IP obtained, ERPLibre install skipped.')}"
            )
            return
        # Attend que le SSH soit prêt (évite « Connection refused » quand
        # l'install démarre avant le sshd de la VM).
        print(f"  {name} ({ip}): {t('waiting for SSH...')}")
        if not self._qemu_wait_ssh(ip):
            print(
                f"  {name} ({ip}): "
                f"{t('SSH not reachable, ERPLibre install skipped.')}"
            )
            return
        remote = self._qemu_erplibre_remote_cmd(branch)
        ssh_opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=15"
        )
        cmd = f"ssh {ssh_opts} erplibre@{ip} {shlex.quote(remote)}"
        print(
            f"\n  📦 {name} ({ip}): {t('installing ERPLibre')} "
            f"({branch}, make install_os + {self.ERPLIBRE_ODOO_TARGET})"
        )
        print(f"  {t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_deploy_infra(self):
        print(f"🏗  {t('Deploy ERPLibre infra: one minimal VM per image')}")
        try:
            mod = self._qemu_import_module()
        except Exception as exc:
            print(f"{t('Cannot load QEMU catalog: ')}{exc}")
            return
        distros = list(mod.DISTROS)

        # 0) Architecture du parc (défaut : native de l'hôte). arm64 et s390x
        # n'ont pas d'images pour toutes les distros -> on restreint le
        # catalogue aux distros qui publient l'arch choisie.
        arch = self._qemu_prompt_infra_arch()
        allowed = self._qemu_arch_distros(arch)
        if allowed is not None:
            keep = [d for d in distros if d in allowed]
            dropped = [d for d in distros if d not in keep]
            if dropped:
                print(
                    f"  ⚠ {t('images for this arch only exist for:')} "
                    f"{', '.join(allowed)} "
                    f"({t('ignored:')} {', '.join(dropped)})"
                )
            distros = keep
            if not distros:
                print(t("Nothing selected."))
                return

        # 1) Distributions : multi-sélection, catalogue complet, principal (la
        # version par défaut de chaque distro, marquée d'un *), ou granulaire
        # (liste à plat de TOUTES les versions, choix par virgules).
        print(f"\n{t('Distributions:')}")
        for i, d in enumerate(distros, 1):
            default_v = mod.DISTROS[d][1]
            vers = ", ".join(
                (v + " *" if v == default_v else v) for v in mod.DISTROS[d][0]
            )
            print(f"  [{i}] {d} ({vers})")
        print(f"  [all] {t('Whole catalog (every version)')}")
        print(
            f"  [principal] {t('The main version of each distro (marked *)')}"
        )
        print(
            f"  [granulaire] {t('Pick exact versions (comma-separated list)')}"
        )
        raw = (
            input(
                t(
                    "Selection (numbers, 'all', 'principal' or 'granulaire',"
                    " default: all): "
                )
            )
            .strip()
            .lower()
        )
        catalog_all = raw in ("", "all", "*")
        principal = raw in ("principal", "each", "p")
        granular = raw in ("granulaire", "granular", "g")

        selected = []  # (distro, version, ram_mb, disk_str)
        if granular:
            # Liste APLATIE de toutes les versions (distro + version) : on choisit
            # des versions précises par leurs numéros, séparés par des virgules.
            flat = []  # (distro, version, ram, disk, is_default)
            for d in distros:
                versions_map, default_v = mod.DISTROS[d]
                for v, (_c, _o, ram, disk) in versions_map.items():
                    flat.append((d, v, ram, disk, v == default_v))
            print(f"\n{t('All versions:')}")
            for i, (d, v, ram, disk, isdef) in enumerate(flat, 1):
                star = " *" if isdef else ""
                print(f"  [{i}] {d} {v}{star}  (RAM≥{ram}Mo, {disk})")
            r = (
                input(t("Selection (comma-separated numbers): "))
                .strip()
                .lower()
            )
            for d, v, ram, disk, _isdef in self._parse_index_selection(
                r, flat
            ):
                selected.append((d, v, ram, disk))
        elif principal:
            # Une VM par distro : sa version par défaut.
            for d in distros:
                versions_map, default_v = mod.DISTROS[d]
                _c, _o, ram, disk = versions_map[default_v]
                selected.append((d, default_v, ram, disk))
        else:
            sel_distros = (
                distros
                if catalog_all
                else self._parse_index_selection(raw, distros)
            )
            if not sel_distros:
                print(t("Nothing selected."))
                return
            # 2) Versions par distro (multi-sélection) ; « all » si catalogue.
            for d in sel_distros:
                versions_map = mod.DISTROS[d][0]
                vlist = list(versions_map)
                if catalog_all:
                    chosen = vlist
                else:
                    print(f"\n{t('Versions for')} {d} :")
                    for i, v in enumerate(vlist, 1):
                        _c, _o, ram, disk = versions_map[v]
                        print(f"  [{i}] {v}  (RAM≥{ram}Mo, {disk})")
                    print(f"  [all] {t('select all')}")
                    r = input(
                        t("Selection (numbers, or 'all', default: all): ")
                    ).strip()
                    chosen = (
                        vlist
                        if r.lower() in ("", "all", "*")
                        else self._parse_index_selection(r.lower(), vlist)
                    )
                for v in chosen:
                    _c, _o, ram, disk = versions_map[v]
                    selected.append((d, v, ram, disk))
        if not selected:
            print(t("Nothing selected."))
            return

        # 3) Plan + estimation des ressources.
        total_ram = sum(s[2] for s in selected)
        total_disk = sum(self._parse_disk_gb(s[3]) for s in selected)
        free_ram = self._host_free_ram_mb()
        print(f"\n{t('Deployment plan')} ({len(selected)} VM) :")
        for d, v, ram, disk in selected:
            name = self._qemu_infra_name(d, v, arch)
            print(f"  - {name:<26} {d} {v:<7} RAM {ram}Mo  {t('disk')} {disk}")
        print(f"\n  {t('Total RAM (all running):')} {total_ram} Mo")
        print(f"  {t('Total virtual disk (thin qcow2):')} ~{total_disk} G")
        if free_ram:
            print(f"  {t('Host RAM available:')} {free_ram} Mo")
            if total_ram > free_ram:
                warn = t(
                    "Total RAM exceeds host free RAM: not all VMs will run"
                    " at once."
                )
                print(f"  ⚠ {warn}")

        # Clé SSH (partagée par tout le parc).
        default_key = self._qemu_default_ssh_key()
        key_hint = default_key or t("none")
        ssh_key = input(f"{t('SSH public key path')} ({key_hint}): ").strip()
        if not ssh_key:
            ssh_key = default_key
        if ssh_key:
            ssh_key = os.path.expanduser(ssh_key)

        # 4) Option : installer ERPLibre dans ~/git/erplibre de chaque VM.
        install_branch = None
        install_monitor = False
        ans = input(
            t("Install ERPLibre into ~/git/erplibre on each VM? (y/N): ")
        )
        if self._is_yes(ans):
            install_branch = self._qemu_pick_branch()
            install_monitor = self._is_yes(
                input(t("Interactive monitoring dashboard? (y/N): "))
            )

        add_ssh_config = self._is_yes(
            input(t("Add each VM to ~/.ssh/config? (y/N): "))
        )

        # Nombre de déploiements en parallèle. Défaut = nombre de CPU de
        # l'hôte (borné par le nombre de VM ; repli sur 4 si indéterminé).
        default_par = min(len(selected), os.cpu_count() or 4)
        raw = input(
            f"{t('Parallel deployments (default:')} {default_par}): "
        ).strip()
        try:
            parallelism = max(1, int(raw)) if raw else default_par
        except ValueError:
            parallelism = default_par

        # 5) Confirmation puis déploiement (en parallèle).
        ans = input(f"\n{t('Deploy these VMs now? (y/N): ')}")
        if not self._is_yes(ans):
            print(t("Cancelled."))
            return

        script_path = self._qemu_script_path()
        deployed = []
        jobs = []  # (name, parts) des VM à créer
        for d, v, _ram, disk in selected:
            name = self._qemu_infra_name(d, v, arch)
            if self._qemu_domain_exists(name):
                print(f"⏭  {name}: {t('already exists, skipped.')}")
                deployed.append(name)
                continue
            parts = [
                "sudo",
                script_path,
                "--distro",
                d,
                "--version",
                v,
                "--name",
                name,
                # Mot de passe console « erplibre » (+ clé SSH). --no-wait-ip :
                # ne bloque pas 90s par VM, l'IP est collectée après coup.
                "--password",
                "erplibre",
                "--no-wait-ip",
            ]
            if arch and arch != "amd64":
                parts += ["--arch", arch]
            if ssh_key:
                parts += ["--ssh-key", ssh_key]
            if install_branch:
                # ERPLibre dépasse le minimum : +5 Go de disque (sinon il ne
                # reste que ~97 Mo après l'installation). git/make sont posés
                # par le bootstrap (pas via cloud-init, trop lent au boot).
                bigger = (
                    self._parse_disk_gb(disk) + self.ERPLIBRE_EXTRA_DISK_GB
                )
                parts += ["--disk-size", f"{bigger}G"]
            parts.append("-y")
            jobs.append((name, parts))

        if jobs:
            from concurrent.futures import (
                ThreadPoolExecutor,
                as_completed,
            )

            workers = min(parallelism, len(jobs))
            print(
                f"\n{t('Deploying')} {len(jobs)} VM "
                f"({t('parallel jobs:')} {workers})…"
            )

            def _run(job):
                jname, jparts = job
                res = subprocess.run(jparts, capture_output=True, text=True)
                out = (res.stdout or "") + (res.stderr or "")
                return jname, res.returncode, out

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run, j) for j in jobs]
                for fut in as_completed(futures):
                    jname, rc, out = fut.result()
                    mark = "✅" if rc == 0 else "❌"
                    print(f"\n{mark} {jname} (rc={rc})")
                    tail = [ln for ln in out.strip().splitlines() if ln][-4:]
                    for ln in tail:
                        print(f"    {ln}")
                    if rc == 0:
                        deployed.append(jname)

        # 6) ~/.ssh/config (une fois les VM démarrées et l'IP attribuée).
        if add_ssh_config:
            for name in deployed:
                ip = self._qemu_vm_ip(name)
                if ip:
                    self._write_ssh_config_entry(name, "erplibre", ip)

        # 7) Installation ERPLibre (clone + make) si demandée.
        if install_branch:
            if install_monitor:
                # Installs détachées en parallèle + dashboard Textual.
                self._qemu_install_erplibre_monitored(deployed, install_branch)
            else:
                print(
                    f"\n{t('Installing ERPLibre on each VM')} "
                    f"({install_branch})…"
                )
                for name in deployed:
                    self._qemu_install_erplibre_vm(
                        name, ssh_key, install_branch
                    )

        print(f"\n✅ {t('ERPLibre infra deployment done.')}")
        print(f"   {t('Default login:')} erplibre / erplibre")
        print(f"   {t('Manage with:')} sudo virsh list --all")

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

    def _deploy_ntfy_server(self):
        print(
            f"\n{t('Deploy a local NTFY push notification server (Ubuntu/Arch)')}"
        )
        port = input(t("NTFY server port (default: 8080): ")).strip() or "8080"
        import socket

        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except Exception:
            local_ip = "127.0.0.1"

        default_url = f"http://{local_ip}:{port}"
        base_url = (
            input(f"{t('NTFY base URL')} (default: {default_url}): ").strip()
            or default_url
        )

        script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "install",
            "install_ntfy.sh",
        )
        script_path = os.path.realpath(script_path)

        if not os.path.isfile(script_path):
            print(f"{t('NTFY install script not found: ')}{script_path}")
            return

        print(f"\n{t('Installing NTFY server (requires sudo)...')}")
        cmd = (
            f"sudo NTFY_PORT={port}"
            f" NTFY_BASE_URL={base_url}"
            f" bash {script_path}"
        )
        print(f"{t('Will execute:')} {cmd}\n")
        try:
            self.execute.exec_command_live(cmd, source_erplibre=False)
            print(f"\n{t('NTFY server installed and started successfully!')}")
        except Exception as e:
            print(f"{t('Error installing NTFY server: ')}{e}")

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

    def _get_ssh_params(self):
        """Prompt for SSH connection parameters. Returns dict or None on cancel."""
        host = click.prompt(
            t("Remote host (user@hostname or hostname): ")
        ).strip()
        if not host:
            print(t("SSH host is required!"))
            return None
        user = (
            click.prompt(t("SSH user (default: erplibre): ")).strip()
            or "erplibre"
        )
        port = click.prompt(t("SSH port (default: 22): ")).strip() or "22"
        key = click.prompt(
            t("SSH key path (default: ~/.ssh/id_rsa, empty for none): ")
        ).strip()
        path = (
            click.prompt(
                t("Remote path (default: ~/erplibre_deploy_2): ")
            ).strip()
            or "~/erplibre_deploy_2"
        )
        return {
            "SSH_HOST": host,
            "SSH_USER": user,
            "SSH_PORT": port,
            "SSH_KEY": key,
            "SSH_PATH": path,
        }

    def _build_ssh_make_cmd(self, target, params, extra=None):
        """Build a make SSH command string from params dict."""
        parts = [f"make {target}"]
        for k, v in params.items():
            if v:
                parts.append(f'{k}="{v}"')
        if extra:
            for k, v in extra.items():
                if v:
                    parts.append(f'{k}="{v}"')
        return " ".join(parts)

    def _deploy_ssh_check(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_check", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_push(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_push", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_install(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_install", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_run(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_run", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_stop(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_stop", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_restart(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_restart", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_status(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_status", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_logs(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_logs", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_make(self):
        params = self._get_ssh_params()
        if not params:
            return
        target = click.prompt(t("Make target to run remotely: ")).strip()
        if not target:
            print(t("SSH host is required!"))
            return
        cmd = self._build_ssh_make_cmd(
            "ssh_make", params, extra={"SSH_TARGET": target}
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_install_systemd(self):
        params = self._get_ssh_params()
        if not params:
            return
        cmd = self._build_ssh_make_cmd("ssh_install_systemd", params)
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

    def _deploy_ssh_install_nginx(self):
        params = self._get_ssh_params()
        if not params:
            return
        domain = click.prompt(t("Domain name (e.g.: example.com): ")).strip()
        if not domain:
            print(t("SSH host is required!"))
            return
        email = click.prompt(t("Admin email for SSL certificate: ")).strip()
        cmd = self._build_ssh_make_cmd(
            "ssh_install_nginx",
            params,
            extra={"SSH_DOMAIN": domain, "SSH_ADMIN_EMAIL": email},
        )
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(
            cmd, source_erplibre=False, single_source_erplibre=True
        )

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
            overwrite = input(t("Do you want to overwrite the file? (y/Y): "))
            if not self._is_yes(overwrite):
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
            {"section": t("Backup")},
            {"prompt_description": t("Create backup (.zip)")},
            {
                "prompt_description": t(
                    "Download database to create backup (.zip)"
                )
            },
            {"section": t("Restore")},
            {"prompt_description": t("Restore from backup (.zip)")},
            {"section": t("Danger zone")},
            {"prompt_description": t("Erase a database")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.db_manager.create_backup_from_database()
            elif status == "2":
                self.db_manager.download_database_backup_cli()
            elif status == "3":
                self.db_manager.restore_from_database()
            elif status == "4":
                self.db_manager.drop_database()
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
            {"section": t("Setup")},
            {"prompt_description": t("Install RTK")},
            {"prompt_description": t("Initialize global auto-rewrite hook")},
            {"section": t("Status")},
            {"prompt_description": t("Check RTK version")},
            {"prompt_description": t("Check RTK status")},
            {"prompt_description": t("Show cumulative token savings")},
            {"section": t("Optimize")},
            {"prompt_description": t("Discover optimization opportunities")},
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
                self.rtk_init_global()
            elif status == "3":
                self.rtk_check_version()
            elif status == "4":
                self.rtk_check_status()
            elif status == "5":
                self.rtk_show_gain()
            elif status == "6":
                self.rtk_discover()
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
            {"section": t("Generate")},
            {"prompt_description": t("Generate all configuration")},
            {"prompt_description": t("Generate from pre-configuration")},
            {"prompt_description": t("Generate from backup file")},
            {"prompt_description": t("Generate from database")},
            {"section": t("Advanced")},
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
        keep_input = input(t("Keep the temporary database? (y/N): "))
        keep = self._is_yes(keep_input)
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
        if self._is_yes(git_repo_update_input):
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
        if self._is_yes(do_personalize):
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
            do_debug = self._is_yes(
                input("Compilation with debug information, default No (Y) : ")
            )
            do_change_picture_menu = self._is_yes(
                input(
                    "Want to change picture from menu, you need"
                    " android-studio (Y) : "
                )
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
