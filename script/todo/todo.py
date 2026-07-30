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
[5] {t("Navigation telemetry (TUI)")}
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
            elif status == "5":
                self._todo_telemetry_tui()
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
        "prompt_execute_deploy_ssh": "SSH",
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
            # Télémétrie de navigation (best-effort, ne casse jamais le menu).
            try:
                from script.todo import todo_telemetry

                todo_telemetry.record(" › ".join(crumbs))
            except Exception:
                pass
        return header + t("Command:")

    def _todo_telemetry_tui(self):
        """Ouvre le TUI de télémétrie (arbre/Kanban). Une commande choisie est
        exécutée au retour (hors du TUI) ; on propose ensuite de REVENIR (l'état
        et la position du curseur sont restaurés) ou de quitter."""
        from script.todo.todo_telemetry import run_tui

        state = None
        while True:
            try:
                result = run_tui(state=state)
            except ImportError:
                print(t("Install textual for the telemetry TUI (pip)."))
                return
            if not result:
                return
            action, state = result
            if not action:
                return  # quitté sans choisir de commande
            method, kwargs = action
            # Fil d'Ariane : la commande étant lancée DEPUIS la télémétrie (et
            # non via la navigation), aucun menu n'a affiché le chemin. On le
            # montre ici (dernier segment traduit + icône) et on l'enregistre.
            path = state.get("path") if isinstance(state, dict) else None
            if path:
                segs = path.split(" › ")
                segs[-1] = t(segs[-1])
                print(f"\n📍 {' › '.join(segs)}")
                try:
                    from script.todo import todo_telemetry

                    todo_telemetry.record(path)
                except Exception:
                    pass
            fn = getattr(self, method, None)
            if not callable(fn):
                print(f"{t('Command not found !')} ({method})")
            else:
                try:
                    fn(**(kwargs or {}))
                except Exception as exc:
                    print(f"{t('Command failed: ')}{exc}")
            # Revenir (curseur restauré) ou quitter ?
            ans = input(
                f"\n{t('Back to telemetry (r) or quit (Enter)? ')}"
            )
            if ans.strip().lower() not in ("r", "revenir", "o", "oui", "y"):
                return

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
            {"section": t("Remote & services")},
            {"prompt_description": t("SSH (remote host)...")},
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
                self.prompt_execute_deploy_ssh()
            elif status == "4":
                self._deploy_ntfy_server()
            elif status == "5":
                self.prompt_execute_qemu()
            else:
                print(t("Command not found !"))

    def prompt_execute_deploy_ssh(self):
        """Sous-menu : opérations de déploiement sur un hôte distant via SSH."""
        print(f"🤖 {t('Deploy ERPLibre to a remote host over SSH!')}")
        choices = [
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
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._deploy_ssh_check()
            elif status == "2":
                self._deploy_ssh_push()
            elif status == "3":
                self._deploy_ssh_install()
            elif status == "4":
                self._deploy_ssh_run()
            elif status == "5":
                self._deploy_ssh_stop()
            elif status == "6":
                self._deploy_ssh_restart()
            elif status == "7":
                self._deploy_ssh_status()
            elif status == "8":
                self._deploy_ssh_logs()
            elif status == "9":
                self._deploy_ssh_make()
            elif status == "10":
                self._deploy_ssh_install_systemd()
            elif status == "11":
                self._deploy_ssh_install_nginx()
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
        print(f"\n{t('Version for')} {distro.capitalize()} :")
        for i, v in enumerate(versions, 1):
            suffix = " *" if v == default else ""
            stat = self._qemu_stat_avg("version", v, distro)
            print(f"  [{i}] {v}{suffix}{stat}")
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

    def _qemu_last_run_line(self):
        """Ligne « dernière install » (distro version [arch] en durée), depuis
        l'historique (.venv.erplibre) ; '' si aucune donnée."""
        try:
            from script.todo import qemu_install_monitor as mon

            r = mon.last_run()
            if r:
                return (
                    f"  ℹ {t('Last install:')} {r.get('distro')} "
                    f"{r.get('version')} [{r.get('arch')}] — "
                    f"{mon._fmt_secs(r.get('seconds', 0))}"
                )
        except Exception:
            pass
        return ""

    def _qemu_stat_avg(self, field, value, distro=None):
        """Suffixe « · ~5m moy (3) » : durée d'install MOYENNE historique pour
        cette archi/distro/version (fichier .venv.erplibre), ou '' si aucune
        donnée. Pour field='version', `distro` est requis."""
        try:
            from script.todo import qemu_install_monitor as mon

            if field == "arch":
                secs, n = mon.avg_by_arch(value)
            elif field == "version":
                secs, n = mon.avg_by_version(distro, value)
            else:
                secs, n = mon.avg_by_distro(value)
            if secs:
                return f"  · ~{mon._fmt_secs(secs)} {t('avg')} ({n})"
        except Exception:
            pass
        return ""

    def _qemu_ask_arch(self, opts, native, allow_all=False):
        """Affiche les architectures `opts` (natif marqué d'un *) et renvoie le
        choix. Si `allow_all`, propose aussi [all] = toutes les archis (renvoie
        « all »). Toute arch non native est ÉMULÉE (TCG, lente)."""
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
            print(f"  [{i}] {label}{self._qemu_stat_avg('arch', a)}")
        if allow_all:
            print(f"  [all] {t('All supported architectures')}")
        sel = (
            input(f"{t('Choice (number or name, blank = native):')} ")
            .strip()
            .lower()
        )
        if not sel:
            return native
        if allow_all and sel in ("all", "*"):
            note = t("(includes emulated architectures — some VMs are slow)")
            print(f"⚠  {note}")
            return "all"
        chosen = None
        for i, a in enumerate(opts, 1):
            if sel in (str(i), a, self._QEMU_ARCH_ALIAS.get(a)):
                chosen = a
                break
        if chosen is None:
            print(f"{t('Invalid selection, using')} {native}")
            return native
        if chosen != native:
            warn = t(
                "This architecture is emulated (TCG): boot and install are"
                " much slower than the native one."
            )
            print(f"⚠  {warn}")
        return chosen

    def _qemu_prompt_infra_arch(self):
        """Architecture du parc (défaut : native de l'hôte, marquée d'un *).
        Toute arch non native est émulée ; le catalogue est ensuite restreint
        aux distros publiant cette arch."""
        native = self._native_arch()
        opts = ["amd64", "arm64", "s390x"]
        if native not in opts:  # hôte exotique : garder le natif en tête
            opts.insert(0, native)
        return self._qemu_ask_arch(opts, native, allow_all=True)

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
            {"prompt_description": t("Deploy VM(s) (one or many)")},
            {
                "prompt_description": t(
                    "Preview a deployment (dry-run, no sudo)"
                )
            },
            {"prompt_description": t("Download a cloud image only")},
            {"section": t("Manage")},
            {"prompt_description": t("List VMs (virsh list --all)")},
            {"prompt_description": t("Show a VM IP address")},
            {"prompt_description": t("Open the console on a VM")},
            {"prompt_description": t("Resize a VM disk")},
            {"prompt_description": t("Delete VM(s)")},
            {"prompt_description": t("Clean up QEMU (orphan files)")},
            {
                "prompt_description": t(
                    "Test a VM (open Odoo in a CLI browser)"
                )
            },
            {
                "prompt_description": t(
                    "Reopen install monitoring (last run / history)"
                )
            },
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
                self._qemu_deploy(dry_run=False)
            elif status == "2":
                self._qemu_deploy(dry_run=True)
            elif status == "3":
                self._qemu_download_image()
            elif status == "4":
                self._qemu_list_vms(ask_advanced=True)
            elif status == "5":
                self._qemu_show_ip()
            elif status == "6":
                self._qemu_console()
            elif status == "7":
                self._qemu_resize_disk()
            elif status == "8":
                self._qemu_delete_vm()
            elif status == "9":
                self._qemu_cleanup()
            elif status == "10":
                self._qemu_test_vm()
            elif status == "11":
                self._qemu_reopen_monitor()
            elif status == "12":
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

    def _qemu_list_vms(self, ask_advanced=False):
        cmd = "sudo virsh list --all"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        if not ask_advanced:
            return
        # Menu contextuel : infos avancées, ou changer l'état de VM.
        print(f"\n{t('What do you want to do?')}")
        print(f"  [1] {t('Advanced info (vCPU, RAM, disk)')}")
        print(f"  [2] {t('Change the state of one or more VMs')}")
        print(f"  [{t('Enter')}] {t('Nothing')}")
        choice = input(t("Choice: ")).strip()
        if choice == "1":
            self._qemu_list_vms_advanced()
        elif choice == "2":
            self._qemu_change_state()

    def _qemu_change_state(self):
        """Démarre (« ouvrir ») ou éteint (« fermer ») une liste de VM saisie
        séparée par des virgules, avec DOUBLE validation."""
        names = self._qemu_list_domains()
        if not names:
            print(f"\n{t('No VM found.')}")
            return
        print(f"\n{t('Available VMs:')} {', '.join(names)}")
        raw = input(t("VMs to change (comma-separated): ")).strip()
        targets = [n.strip() for n in raw.split(",") if n.strip()]
        if not targets:
            print(t("Nothing selected."))
            return
        # Résoudre les ID -> noms et valider l'existence.
        resolved, unknown = [], []
        known = set(names)
        for tgt in targets:
            real = self._qemu_domname(tgt)
            (resolved if real in known else unknown).append(real)
        if unknown:
            print(f"{t('Unknown VM(s):')} {', '.join(unknown)}")
            return
        # Choix de l'état cible : ouvrir (démarrer) ou fermer (éteindre).
        print(f"\n{t('Target state:')}")
        print(f"  [1] {t('Open (start)')}")
        print(f"  [2] {t('Close (shut down)')}")
        st = input(t("Choice: ")).strip()
        if st == "1":
            action, verb = "start", t("start")
        elif st == "2":
            action, verb = "shutdown", t("shut down")
        else:
            print(t("Cancelled."))
            return
        # DOUBLE validation avant d'appliquer.
        summary = f"{verb} -> {', '.join(resolved)}"
        if not self._is_yes(
            input(f"{t('Apply:')} {summary} ? (o/N) : ")
        ):
            print(t("Cancelled."))
            return
        if not self._is_yes(
            input(t("Confirm for real? (y/N): "))
        ):
            print(t("Cancelled."))
            return
        for real in resolved:
            cmd = f"sudo virsh {action} {shlex.quote(real)}"
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    @staticmethod
    def _qemu_dominfo(name):
        """(vcpus, max_mem_kib) via « virsh dominfo », ou (0, 0)."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "dominfo", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return 0, 0
        vcpus, mem = 0, 0
        for line in res.stdout.splitlines():
            if line.startswith("CPU(s):"):
                try:
                    vcpus = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Max memory:"):
                # « 4194304 KiB »
                try:
                    mem = int(line.split(":", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
        return vcpus, mem

    @staticmethod
    def _qemu_disk_sizes(disk):
        """(taille virtuelle, taille réelle sur disque) en octets, via
        qemu-img info -U (lit même VM allumée). (0, 0) si échec."""
        try:
            res = subprocess.run(
                ["sudo", "qemu-img", "info", "-U", "--output=json", disk],
                capture_output=True,
                text=True,
                timeout=20,
            )
            data = json.loads(res.stdout)
            return (
                int(data.get("virtual-size", 0)),
                int(data.get("actual-size", 0)),
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0, 0

    def _qemu_list_vms_advanced(self):
        """Tableau détaillé par VM : état, vCPU, RAM allouée, disque (virtuel
        + réel), plus l'espace total disponible du stockage des images."""
        names = self._qemu_list_domains()
        if not names:
            print(f"\n{t('No VM found.')}")
            return
        g = 1 << 30
        header = (
            f"\n{'VM':<28} {'État':<10} {'vCPU':>4} {'RAM':>8} "
            f"{'Disque':>9} {'Réel':>9}"
        )
        print(header)
        print("─" * len(header.strip()))
        disk_dirs = set()
        for name in names:
            state = self._qemu_domstate(name) or "?"
            vcpus, mem_kib = self._qemu_dominfo(name)
            disk = self._qemu_main_disk(name)
            virt, actual = self._qemu_disk_sizes(disk) if disk else (0, 0)
            if disk:
                disk_dirs.add(os.path.dirname(disk))
            ram_g = (mem_kib * 1024) / g if mem_kib else 0
            print(
                f"{name:<28.28} {state:<10.10} {vcpus:>4} "
                f"{ram_g:>7.1f}G {virt / g:>8.1f}G {actual / g:>8.1f}G"
            )
        # Espace total disponible sur le(s) stockage(s) des disques.
        for d in sorted(disk_dirs) or ["/var/lib/libvirt/images"]:
            try:
                usage = shutil.disk_usage(d)
            except OSError:
                continue
            print(
                f"\n{t('Storage')} {d} : "
                f"{usage.free / g:.1f}G {t('free')} / "
                f"{usage.total / g:.1f}G {t('total')} "
                f"({usage.used / g:.1f}G {t('used')})"
            )

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

    def _qemu_test_vm(self):
        """Teste une VM : résout son IP puis ouvre Odoo (:8069) dans un
        navigateur web EN LIGNE DE COMMANDE choisi par l'utilisateur."""
        self._qemu_list_vms()
        print()
        name = input(t("VM name or ID: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        real = self._qemu_domname(name)
        if not self._qemu_domain_exists(real):
            print(f"{real}: {t('VM not found.')}")
            return
        print(f"\n{t('Resolving VM IP...')}")
        ip = self._qemu_vm_ip(real, timeout=120)
        if not ip:
            print(t("No IP found for this VM."))
            return
        browser = self._qemu_choose_cli_browser()
        if not browser:
            return
        url = f"http://{ip}:8069"
        print(f"→ {browser} {url}")
        # os.system (et NON exec_command_live) : un navigateur texte a besoin
        # du VRAI TTY interactif. exec_command_live redirige la sortie dans un
        # tube -> le navigateur ne fait qu'imprimer sans réagir au clavier.
        rc = os.system(f"{browser} {shlex.quote(url)}")
        if rc != 0:
            msg = t(
                "Page may not have loaded: Odoo not started on :8069, "
                "or network/firewall."
            )
            print(f"⚠  {msg}")

    def _qemu_reopen_monitor(self):
        """Rouvre le suivi d'installation (dashboard) sur un run PASSÉ : le
        dernier par défaut, ou un choix dans l'historique. Utile quand le
        dashboard s'est fermé et qu'on veut reprendre l'analyse."""
        from script.todo import qemu_install_monitor as mon

        runs = mon.list_install_runs()
        if not runs:
            print(t("No install run found in history."))
            return
        print(f"\n{t('Install runs (most recent first):')}")
        for i, r in enumerate(runs, 1):
            names = ", ".join(v.get("name", "?") for v in r["vms"])
            star = " *" if i == 1 else ""
            print(
                f"  [{i}] {r['label']} — {len(r['vms'])} VM{star}\n"
                f"        {names}"
            )
        sel = input(
            t("Choice (number, blank = last): ")
        ).strip()
        run = runs[0]
        if sel:
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(runs):
                    run = runs[idx]
                else:
                    print(t("Invalid selection."))
                    return
            except ValueError:
                print(t("Invalid selection."))
                return
        try:
            mon.run_monitor(run["manifest"])
        except ImportError:
            print(t("Install textual for the dashboard (pip)."))
        except Exception as exc:
            print(f"{t('Command failed: ')}{exc}")

    def _qemu_choose_cli_browser(self):
        """Offre la LISTE des navigateurs CLI installés, plus une option pour
        en INSTALLER un autre, et renvoie celui choisi, sinon None."""
        from script.todo.qemu_install_monitor import CLI_BROWSERS

        available = [b for b in CLI_BROWSERS if shutil.which(b)]
        if not available:
            return self._qemu_install_cli_browser()
        print(f"\n{t('Which browser to view the page?')}")
        for i, b in enumerate(available, 1):
            print(f"  [{i}] {b}{' *' if i == 1 else ''}")
        print(f"  [i] {t('Install another browser')}")
        sel = input(t("Choice (number, blank = first): ")).strip().lower()
        if sel == "i":
            return self._qemu_install_cli_browser()
        if not sel:
            return available[0]
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(available):
                return available[idx]
        except ValueError:
            pass
        return available[0]

    def _qemu_install_cli_browser(self):
        """Demande QUEL navigateur CLI installer, affiche la commande adaptée
        à l'OS, l'exécute après validation. Renvoie le binaire installé ou
        None."""
        from script.todo.qemu_install_monitor import (
            INSTALLABLE_BROWSERS,
            browser_install_command,
        )

        print(f"\n{t('Which browser to install?')}")
        for i, (b, desc) in enumerate(INSTALLABLE_BROWSERS, 1):
            print(f"  [{i}] {desc}{' *' if i == 1 else ''}")
        sel = input(t("Choice (number, blank = w3m): ")).strip()
        browser = INSTALLABLE_BROWSERS[0][0]
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(INSTALLABLE_BROWSERS):
                browser = INSTALLABLE_BROWSERS[idx][0]
        except ValueError:
            pass
        cmd = browser_install_command(browser)
        if not cmd:
            print(t("Unknown package manager; install it manually."))
            return None
        printable = " ".join(cmd)
        print(f"{t('Command:')} {printable}")
        if not self._is_yes(input(t("Install now? (y/N): "))):
            return None
        os.system(printable)
        return browser if shutil.which(browser) else None

    # ------------------------------------------------------------------ #
    # Redimensionnement du disque d'une VM
    # ------------------------------------------------------------------ #
    @staticmethod
    def _qemu_c_env():
        """Environnement forçant LC_ALL=C : la sortie des outils (virsh,
        sgdisk, resize2fs, dumpe2fs…) reste en ANGLAIS quelle que soit la
        locale de l'hôte. Sinon « running » devient « en cours d'exécution »
        (fr) et les comparaisons/parsing d'état cassent."""
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        return env

    @staticmethod
    def _qemu_domstate(name):
        """État libvirt de la VM (« running », « shut off », …) ou ''."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "domstate", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return res.stdout.strip() if res.returncode == 0 else ""

    @staticmethod
    def _qemu_domname(name):
        """Nom canonique de la VM (si on a fourni un ID numérique, le
        résout ; sinon renvoie tel quel). Utile car un ID disparaît une
        fois la VM éteinte."""
        if not str(name).isdigit():
            return name
        try:
            res = subprocess.run(
                ["sudo", "virsh", "domname", str(name)],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return name
        out = res.stdout.strip()
        return out if res.returncode == 0 and out else name

    def _qemu_shutdown_wait(self, name, timeout=120):
        """Arrête la VM par SIGNAL (ACPI power-button, puis agent invité) et
        attend qu'elle soit « shut off » en affichant le temps restant du
        timeout. Si l'arrêt gracieux traîne, propose un arrêt forcé (destroy).
        Renvoie True si la VM est bien éteinte."""
        name = self._qemu_domname(name)
        if self._qemu_domstate(name) == "shut off":
            return True
        # --mode acpi,agent : envoie le SIGNAL d'extinction (bouton ACPI) puis
        # tente l'agent invité si présent — plus fiable qu'un arrêt brutal.
        cmd = f"sudo virsh shutdown {shlex.quote(name)} --mode acpi,agent"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        print(f"{t('Waiting for the VM to shut down...')} "
              f"({t('timeout')}: {timeout} s)")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._qemu_domstate(name) == "shut off":
                # Efface la ligne de compte à rebours puis confirme.
                print(f"\r{' ' * 40}\r✅ {name}: {t('VM is off.')}")
                return True
            remaining = int(deadline - time.time())
            print(f"\r  ⏳ {t('shutting down')}… "
                  f"{remaining:>3d} s {t('remaining')}",
                  end="", flush=True)
            time.sleep(2)
        print()  # newline après le compte à rebours
        # Arrêt gracieux trop long : proposer un arrêt forcé.
        if self._is_yes(
            input(t("Graceful shutdown timed out. Force off (destroy)? "
                    "(y/N): "))
        ):
            cmd = f"sudo virsh destroy {shlex.quote(name)}"
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)
            time.sleep(2)
            return self._qemu_domstate(name) == "shut off"
        return False

    @staticmethod
    def _qemu_main_disk(name):
        """Chemin du disque PRINCIPAL (qcow2) de la VM via domblklist. On
        ignore le seed cloud-init (…-seed.iso, en lecture seule)."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "domblklist", name, "--details"],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return None
        disks = []
        for line in res.stdout.splitlines():
            parts = line.split()
            # Colonnes : Type Device Target Source
            if len(parts) >= 4 and parts[1] == "disk" and parts[3] != "-":
                disks.append(parts[3])
        # Le disque de travail est le .qcow2 (le seed est un .iso).
        for d in disks:
            if d.endswith(".qcow2"):
                return d
        return disks[0] if disks else None

    @staticmethod
    def _qemu_disk_virtual_bytes(disk):
        """Taille VIRTUELLE (octets) du disque via « qemu-img info --json »."""
        try:
            # -U (--force-share) : lit même si la VM tourne (libvirt tient le
            # lock d'écriture). Sans ça : « Failed to get shared write lock ».
            res = subprocess.run(
                ["sudo", "qemu-img", "info", "-U", "--output=json", disk],
                capture_output=True,
                text=True,
                timeout=20,
            )
            data = json.loads(res.stdout)
            return int(data.get("virtual-size", 0))
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0

    def _qemu_resize_disk(self):
        """Redimensionne le disque d'une VM : affiche l'espace actuel, demande
        +NG / -NG / taille cible, applique (à chaud si possible pour agrandir),
        puis propose d'étendre le système de fichiers invité."""
        self._qemu_list_vms()
        print()
        name = input(t("VM name to resize: ")).strip()
        if not name:
            print(t("VM name is required!"))
            return
        if not self._qemu_domain_exists(name):
            print(f"{name}: {t('VM not found.')}")
            return
        # Résout tout de suite le NOM canonique (VM encore allumée -> l'ID est
        # résoluble). Après extinction, un ID numérique disparaît : « virsh
        # start 32 » échouerait. On travaille désormais avec le nom.
        name = self._qemu_domname(name)
        disk = self._qemu_main_disk(name)
        if not disk:
            print(t("Main disk not found for this VM."))
            return

        # 1) Espace actuel (virtuel + réel) + df invité si joignable.
        print(f"\n{t('Current disk:')} {disk}")
        # -U : lecture sûre même VM allumée (sinon « shared write lock »).
        self.execute.exec_command_live(
            f"sudo qemu-img info -U {shlex.quote(disk)}", source_erplibre=False
        )
        cur_bytes = self._qemu_disk_virtual_bytes(disk)
        cur_gb = cur_bytes / (1 << 30)
        state = self._qemu_domstate(name)
        if cur_bytes <= 0:
            print(t("Could not read current disk size; aborting."))
            print(f"{t('VM state:')} {state or '?'}")
            return
        print(f"{t('Current virtual size:')} {cur_gb:.1f} G")
        print(f"{t('VM state:')} {state or '?'}")

        # Espace HÔTE : le qcow2 est creux (sparse), donc on PEUT fixer une
        # taille virtuelle plus grande que l'espace réel — mais si la VM la
        # remplit, l'hôte tombe à court. Max « soutenable » ≈ taille réelle
        # actuelle + espace libre de l'hôte. On l'AFFICHE (avertissement, pas
        # de blocage) pour guider le choix.
        g = 1 << 30
        _virt, actual = self._qemu_disk_sizes(disk)
        try:
            free = shutil.disk_usage(os.path.dirname(disk)).free
        except OSError:
            free = 0
        max_safe_gb = (actual + free) / g if free else 0
        if max_safe_gb:
            print(
                f"{t('Host free space:')} {free / g:.1f} G  ·  "
                f"{t('max sustainable total (before host full):')} "
                f"~{max_safe_gb:.1f} G"
            )

        # 2) Nouvelle taille : +NG (agrandir), -NG (réduire) ou NG (cible).
        guide = t(
            "Enter +NG to grow, -NG to shrink, or NG for a target size "
            "(e.g. +20G, -10G, 60G)."
        )
        print(f"\n{guide}")
        raw = input(t("Resize: ")).strip().upper().replace("G", "")
        try:
            if raw.startswith("+"):
                new_gb = cur_gb + float(raw[1:])
            elif raw.startswith("-"):
                new_gb = cur_gb - float(raw[1:])
            else:
                new_gb = float(raw)
        except ValueError:
            print(t("Invalid size."))
            return
        if new_gb <= 0:
            print(t("Invalid size."))
            return
        new_gb = round(new_gb, 1)
        if abs(new_gb - cur_gb) < 0.05:
            print(t("No change."))
            return
        shrink = new_gb < cur_gb
        print(
            f"\n{t('New virtual size:')} {cur_gb:.1f} G -> {new_gb:.1f} G"
        )
        # Avertissement (NON bloquant) : agrandir au-delà de ce que l'hôte
        # peut soutenir -> surallocation, l'hôte se remplira si la VM utilise
        # tout l'espace.
        if not shrink and max_safe_gb and new_gb > max_safe_gb:
            over = new_gb - max_safe_gb
            msg1 = t("Beyond host capacity by ~%.1f G — overcommit.") % over
            msg2 = t(
                "The qcow2 is thin: fine until the VM fills it, then the "
                "host disk runs out. Max sustainable: ~%.1f G."
            ) % max_safe_gb
            print(f"⚠  {msg1}")
            print(f"   {msg2}")

        # 3) Application selon agrandir/réduire et l'état de la VM.
        was_shut_down = False  # la VM a-t-elle été éteinte pour l'occasion ?
        cmd = None  # commande d'AGRANDISSEMENT (la réduction a son propre flux)
        if shrink:
            # DANGER : qcow2 --shrink ne réduit PAS le FS invité -> perte de
            # données si le FS dépasse la cible. VM éteinte obligatoire.
            danger = t(
                "SHRINKING is DANGEROUS: the guest filesystem is NOT shrunk. "
                "Data beyond the new size is LOST. Shrink the guest FS FIRST, "
                "and only then shrink here."
            )
            print(f"⚠  {danger}")
            if state != "shut off":
                if not self._is_yes(
                    input(t("The VM must be off. Shut it down and retry? "
                            "(y/N): "))
                ):
                    print(t("Cancelled."))
                    return
                if not self._qemu_shutdown_wait(name):
                    print(t("VM is still not off; aborting."))
                    return
                state = "shut off"
                was_shut_down = True
            if not self._is_yes(
                input(t("Type y to confirm you understand the risk (y/N): "))
            ):
                print(t("Cancelled."))
                return
            # Réduction SÛRE (qemu-nbd : réduit FS + partition + GPT, avec
            # sauvegarde optionnelle restaurée en cas d'échec).
            if not self._qemu_safe_shrink(name, disk, new_gb):
                self._qemu_offer_start(name, was_shut_down)
                return
        elif state == "running":
            # Agrandissement À CHAUD : le disque virtuel grossit, le FS invité
            # devra être étendu ensuite.
            cmd = (
                f"sudo virsh blockresize {shlex.quote(name)} "
                f"{shlex.quote(disk)} {new_gb:g}G"
            )
        else:
            cmd = f"sudo qemu-img resize {shlex.quote(disk)} {new_gb:g}G"

        # 4) Agrandissement : exécuter la commande + proposer d'étendre le FS.
        if cmd is not None:
            print(f"{t('Will execute:')} {cmd}")
            if self.execute.exec_command_live(cmd, source_erplibre=False) != 0:
                print(f"❌ {t('Resize failed (see error above).')}")
                return
            print(f"✅ {t('Virtual disk resized.')}")
            if self._is_yes(
                input(t("Grow the guest filesystem now (over SSH)? (y/N): "))
            ):
                self._qemu_grow_guest_fs(name)

        # 5) La VM a été éteinte pour l'opération : proposer de la redémarrer
        #    (l'utilisateur peut ainsi TESTER avant de décider du backup).
        self._qemu_offer_start(name, was_shut_down)

        # 6) Réduction réussie AVEC sauvegarde : proposer de l'effacer une fois
        #    la VM testée (défaut : NON -> on garde le backup par prudence).
        bak = getattr(self, "_shrink_backup", None)
        if shrink and bak and os.path.exists(bak):
            print(f"\n{t('A disk backup was kept:')} {bak}")
            if self._is_yes(
                input(t("Delete this backup now? (y/N): "))
            ):
                subprocess.run(["sudo", "rm", "-f", bak], check=False)
                print(t("Backup deleted."))
            else:
                print(t("Backup kept (delete later via Clean up QEMU)."))
            self._shrink_backup = None

    def _qemu_offer_start(self, name, was_shut_down):
        """Si la VM a été éteinte pour l'opération, le noter et proposer de la
        redémarrer (sinon ne rien demander)."""
        if not was_shut_down:
            return
        print(f"\nℹ  {t('The VM was shut down for the resize.')}")
        if self._is_yes(input(t("Start the VM now? (y/N): "))):
            # `name` est déjà le nom canonique : « virsh start <id> »
            # échouerait car l'ID disparaît quand la VM est éteinte.
            cmd = f"sudo virsh start {shlex.quote(name)}"
            print(f"{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    # Outils requis pour la réduction sûre (tous « base » : e2fsprogs, gdisk,
    # util-linux, qemu-utils) — PAS libguestfs (souvent cassé : appliance
    # supermin sans noyau dans /boot).
    _SHRINK_TOOLS = (
        "qemu-nbd", "e2fsck", "resize2fs", "sgdisk", "partprobe",
        "lsblk", "dumpe2fs", "blockdev",
    )
    _SECT = 512
    _MiB = 1024 * 1024

    def _qemu_safe_shrink(self, name, disk, new_gb):
        """Réduit le disque SANS casser l'OS, via qemu-nbd + resize2fs +
        sgdisk (sans libguestfs) : on réduit le FS (ext), puis la partition,
        puis le conteneur qcow2, puis on répare la GPT de secours. Une COPIE
        .bak est faite AVANT ; en cas d'échec on RESTAURE -> jamais de
        corruption. ext2/3/4 uniquement. Renvoie True si réduit."""
        import math

        missing = [b for b in self._SHRINK_TOOLS if not shutil.which(b)]
        if missing:
            print(
                f"{t('Missing tools for safe shrink:')} {', '.join(missing)}"
            )
            return False
        target = int(round(new_gb * (1 << 30)))
        # Sauvegarde OPTIONNELLE (défaut OUI) : permet de restaurer en cas
        # d'échec, et de tester la VM avant de la supprimer (proposé à la fin).
        self._shrink_backup = None
        bak = None
        if self._is_yes_default_yes(
            input(t("Back up the disk before shrinking? (Y/n): "))
        ):
            bak = f"{disk}.bak"
            print(f"\n{t('Backing up the disk before shrinking…')}")
            if subprocess.run(
                ["sudo", "cp", "--reflink=auto", "--sparse=always", disk, bak]
            ).returncode != 0:
                print(t("Backup failed; aborting."))
                return False
        else:
            print(f"⚠  {t('No backup: a failure could leave the disk broken.')}")
        subprocess.run(["sudo", "modprobe", "nbd", "max_part=16"], check=False)
        dev = None
        try:
            dev = self._qemu_nbd_connect(disk)
            if not dev:
                print(t("Could not attach the disk (nbd); aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            part, start, fstype = self._qemu_root_part(dev)
            if not part:
                print(t("Could not detect the partition to shrink; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            if not fstype.startswith("ext"):
                print(
                    f"{t('Only ext2/3/4 can be shrunk safely; aborting.')}"
                    f" ({fstype})"
                )
                return self._qemu_shrink_revert(bak, disk, changed=False)
            n = self._qemu_part_number(dev, part)
            info = self._qemu_part_info(dev, n)
            # fsck AVANT toute opération.
            subprocess.run(["sudo", "e2fsck", "-f", "-y", part], check=False)
            bs = self._qemu_fs_blocksize(part)
            # Cibles (octets), en gardant 2 Mio pour la GPT de secours + marge.
            part_start_b = start * self._SECT
            max_fs_b = target - part_start_b - 4 * self._MiB
            if max_fs_b <= 0:
                print(t("Target size too small for this layout; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            min_blocks = self._qemu_fs_min_blocks(part)
            if min_blocks and min_blocks * bs > max_fs_b:
                print(t("Not enough used-space margin to shrink; aborting."))
                return self._qemu_shrink_revert(bak, disk, changed=False)
            fs_target_mib = max_fs_b // self._MiB
            print(
                f"\n{t('Shrinking guest ext filesystem')} {part} "
                f"-> {fs_target_mib} MiB…"
            )
            if subprocess.run(
                ["sudo", "resize2fs", part, f"{fs_target_mib}M"]
            ).returncode != 0:
                print(t("resize2fs failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Fin de partition = début + taille RÉELLE du FS + 1 Mio, alignée.
            fs_bytes = self._qemu_fs_blocks(part) * bs
            new_end = start + int(math.ceil((fs_bytes + self._MiB) / self._SECT))
            new_end = ((new_end + 2047) // 2048) * 2048 - 1  # align 2048
            if (new_end + 34) * self._SECT > target:
                print(t("Internal size check failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Réécrit la partition (mêmes type/UUID/nom -> PARTUUID préservé).
            print(f"{t('Shrinking the partition…')} ({part})")
            subprocess.run(["sudo", "sgdisk", "-d", n, dev], check=False)
            rc = subprocess.run(
                ["sudo", "sgdisk", "-n", f"{n}:{start}:{new_end}",
                 "-t", f"{n}:{info['type']}", "-u", f"{n}:{info['uuid']}",
                 "-c", f"{n}:{info['name']}", dev]
            ).returncode
            if rc != 0:
                print(t("Partition rewrite failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            subprocess.run(
                ["sudo", "partprobe", dev], check=False, capture_output=True
            )
            # Détache puis tronque le conteneur qcow2.
            self._qemu_nbd_disconnect(dev)
            dev = None
            print(f"{t('Shrinking the qcow2 container…')} {new_gb:g}G")
            if subprocess.run(
                ["sudo", "qemu-img", "resize", "--shrink", disk,
                 f"{new_gb:g}G"]
            ).returncode != 0:
                print(t("Container shrink failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Répare la GPT de secours (fin du disque) + fsck final.
            dev = self._qemu_nbd_connect(disk)
            if dev:
                subprocess.run(["sudo", "sgdisk", "-e", dev], check=False)
                subprocess.run(
                ["sudo", "partprobe", dev], check=False, capture_output=True
            )
                p2 = self._qemu_root_part(dev)[0]
                if p2:
                    subprocess.run(
                        ["sudo", "e2fsck", "-f", "-y", p2], check=False
                    )
                self._qemu_nbd_disconnect(dev)
                dev = None
            self._shrink_backup = bak  # proposé à la suppression après le boot
            if bak:
                print(
                    f"✅ {t('Disk safely shrunk. Backup kept at:')} {bak}"
                )
            else:
                print(f"✅ {t('Disk safely shrunk.')}")
            return True
        finally:
            if dev:
                self._qemu_nbd_disconnect(dev)

    def _qemu_shrink_revert(self, bak, disk, changed):
        """Restaure le disque depuis la sauvegarde si on l'a modifié (changed)
        et qu'une sauvegarde existe ; sinon retire la sauvegarde inutile.
        Renvoie False (la réduction a échoué)."""
        if changed and bak:
            print(t("Restoring the original disk from backup…"))
            subprocess.run(["sudo", "mv", "-f", bak, disk], check=False)
        elif changed and not bak:
            print(
                f"⚠  {t('No backup to restore; run fsck on the disk before use.')}"
            )
        elif bak:
            subprocess.run(["sudo", "rm", "-f", bak], check=False)
        return False

    @staticmethod
    def _qemu_nbd_connect(disk):
        """Attache `disk` à un /dev/nbdN libre et renvoie le chemin, ou None.
        Attend que les sous-périphériques de partition (nbdNpM) APPARAISSENT
        (sinon lsblk/resize2fs ne voient rien juste après le connect)."""
        for i in range(16):
            dev = f"/dev/nbd{i}"
            # /sys/block/nbdN/pid absent => device libre.
            if os.path.exists(f"/sys/block/nbd{i}/pid"):
                continue
            rc = subprocess.run(
                ["sudo", "qemu-nbd", "-c", dev, disk],
                capture_output=True, text=True,
            ).returncode
            if rc != 0:
                continue
            base = f"nbd{i}"
            for _ in range(15):
                subprocess.run(
                ["sudo", "partprobe", dev], check=False, capture_output=True
            )
                time.sleep(1)
                if any(
                    os.path.exists(f"/sys/class/block/{base}p{n}")
                    for n in range(1, 32)
                ):
                    break
            return dev
        return None

    @staticmethod
    def _qemu_nbd_disconnect(dev):
        subprocess.run(["sudo", "qemu-nbd", "-d", dev], check=False)
        time.sleep(1)

    @staticmethod
    def _qemu_root_part(dev):
        """(partition la plus grosse, secteur de début, type FS) du disque nbd.
        (None, 0, '') si introuvable. Format lsblk -P (paires) : robuste aux
        colonnes VIDES — juste après le connect, FSTYPE peut être vide, et un
        parsing positionnel décalait/ignorait alors toutes les partitions."""
        import re

        try:
            res = subprocess.run(
                ["lsblk", "-Pbno", "NAME,SIZE,TYPE,FSTYPE", dev],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None, 0, ""
        best, best_sz, best_fs = None, -1, ""
        for line in res.stdout.splitlines():
            d = dict(re.findall(r'(\w+)="([^"]*)"', line))
            if d.get("TYPE") != "part":
                continue
            try:
                size = int(d.get("SIZE") or 0)
            except ValueError:
                size = 0
            if size > best_sz:
                best, best_sz, best_fs = d.get("NAME"), size, d.get("FSTYPE", "")
        if not best:
            return None, 0, ""
        part = f"/dev/{best}"
        try:
            start = int(
                open(f"/sys/class/block/{best}/start").read().strip()
            )
        except OSError:
            start = 0
        if not best_fs:
            # FSTYPE pas encore en cache : sonder directement avec blkid.
            best_fs = subprocess.run(
                ["sudo", "blkid", "-o", "value", "-s", "TYPE", part],
                capture_output=True, text=True,
            ).stdout.strip()
        return part, start, best_fs

    @staticmethod
    def _qemu_part_number(dev, part):
        """Numéro de partition (ex. « 1 ») depuis /dev/nbd0p1."""
        return part[len(dev):].lstrip("p")

    @staticmethod
    def _qemu_part_info(dev, n):
        """{type, uuid, name} d'une partition via « sgdisk -i »."""
        info = {"type": "", "uuid": "", "name": ""}
        res = subprocess.run(
            ["sudo", "sgdisk", "-i", n, dev],
            capture_output=True, text=True, env=TODO._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            low = line.lower()
            if low.startswith("partition guid code"):
                info["type"] = line.split(":", 1)[1].split()[0]
            elif low.startswith("partition unique guid"):
                info["uuid"] = line.split(":", 1)[1].strip()
            elif low.startswith("partition name"):
                info["name"] = line.split(":", 1)[1].strip().strip("'")
        return info

    @staticmethod
    def _qemu_fs_blocksize(part):
        res = subprocess.run(
            ["sudo", "dumpe2fs", "-h", part],
            capture_output=True, text=True, env=TODO._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            if line.startswith("Block size:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return 4096

    @staticmethod
    def _qemu_fs_blocks(part):
        res = subprocess.run(
            ["sudo", "dumpe2fs", "-h", part],
            capture_output=True, text=True, env=TODO._qemu_c_env(),
        )
        for line in res.stdout.splitlines():
            if line.startswith("Block count:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        return 0

    @staticmethod
    def _qemu_fs_min_blocks(part):
        """Taille minimale (blocs) du FS via « resize2fs -P »."""
        res = subprocess.run(
            ["sudo", "resize2fs", "-P", part],
            capture_output=True, text=True, env=TODO._qemu_c_env(),
        )
        for tok in res.stdout.replace(":", " ").split():
            if tok.isdigit():
                return int(tok)
        return 0

    # Commande d'extension du FS racine (partition + FS) réutilisée par SSH
    # et par le repli console série.
    _GROW_FS_REMOTE = (
        "set -e; "
        "root=$(findmnt -no SOURCE /); "
        "dev=$(lsblk -no PKNAME \"$root\" | head -1); "
        "part=$(echo \"$root\" | grep -oE '[0-9]+$'); "
        "sudo growpart /dev/$dev $part || true; "
        "fstype=$(findmnt -no FSTYPE /); "
        'case "$fstype" in '
        "ext*) sudo resize2fs \"$root\";; "
        "xfs) sudo xfs_growfs /;; "
        "btrfs) sudo btrfs filesystem resize max /;; "
        'esac; '
        "df -h /"
    )

    def _qemu_grow_guest_fs(self, name):
        """Étend la partition racine + le FS invité. Essaie SSH (IP résolue
        avec BATTEMENT, le boot émulé étant lent) ; en cas d'absence d'IP ou
        d'échec SSH, propose le repli par CONSOLE SÉRIE (commande à coller)."""
        remote = self._GROW_FS_REMOTE
        real = self._qemu_domname(name)
        # 1) SSH : IP résolue avec BATTEMENT (parallèle, boot émulé lent)
        # plutôt qu'un simple timeout court qui abandonnait trop tôt.
        ip = self._qemu_resolve_ips([real], timeout=300).get(real)
        if ip:
            opts = (
                "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                "-o ConnectTimeout=15"
            )
            cmd = f"ssh {opts} erplibre@{ip} {shlex.quote(remote)}"
            print(f"{t('Will execute:')} {cmd}")
            if self.execute.exec_command_live(cmd, source_erplibre=False) == 0:
                return
            print(f"⚠  {t('SSH grow failed; trying the guest agent.')}")
        else:
            print(t("No IP; trying the guest agent (no network)."))
        # 2) Agent invité (virtio, SANS réseau) — nécessite qemu-guest-agent
        # dans la VM (installé au déploiement) + guest-exec autorisé.
        res = self._qemu_guest_exec(real, remote)
        if res is not None:
            rc, out = res
            if out.strip():
                print(out.rstrip())
            if rc == 0:
                print(f"✅ {t('Guest filesystem grown via guest agent.')}")
                return
            print(f"⚠  {t('Guest agent grow failed; falling back to console.')}")
        else:
            print(t("Guest agent unavailable; falling back to serial console."))
        # 3) Console série (commande prête à coller, login interactif).
        self._qemu_grow_via_console(real, remote)

    def _qemu_guest_exec(self, name, script, wait=180):
        """Exécute `script` (sh -c) DANS la VM via l'AGENT INVITÉ (canal
        virtio, sans réseau). Renvoie (code_sortie, sortie) ou None si l'agent
        est indisponible / guest-exec refusé."""
        import base64

        def agent(payload):
            try:
                res = subprocess.run(
                    [
                        "sudo", "virsh", "qemu-agent-command",
                        name, json.dumps(payload),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if res.returncode != 0:
                return None
            try:
                return json.loads(res.stdout).get("return")
            except ValueError:
                return None

        if agent({"execute": "guest-ping"}) is None:
            return None
        start = agent(
            {
                "execute": "guest-exec",
                "arguments": {
                    "path": "/bin/sh",
                    "arg": ["-c", script],
                    "capture-output": True,
                },
            }
        )
        if not start or "pid" not in start:
            return None
        pid = start["pid"]
        deadline = time.time() + wait
        print(t("Running via guest agent (no network)…"))
        while time.time() < deadline:
            st = agent(
                {"execute": "guest-exec-status", "arguments": {"pid": pid}}
            )
            if st and st.get("exited"):
                out = ""
                for k in ("out-data", "err-data"):
                    if st.get(k):
                        try:
                            out += base64.b64decode(st[k]).decode(
                                errors="replace"
                            )
                        except Exception:
                            pass
                return st.get("exitcode", 0), out
            time.sleep(2)
        return None

    def _qemu_grow_via_console(self, name, remote):
        """Repli console série : affiche la commande prête à coller puis ouvre
        la console (login interactif erplibre/erplibre — pas d'automatisation
        fiable de la saisie)."""
        print(f"\n{t('Serial console fallback. Log in, then paste:')}")
        print(f"\n  {remote}\n")
        print(f"💡 {t('To leave the console, press Ctrl+] (then Enter).')}")
        print(
            f"👤 {t('Default login (if set at deploy): erplibre / erplibre')}"
        )
        if not self._is_yes(
            input(t("Open the serial console now? (y/N): "))
        ):
            return
        cmd = f"sudo virsh console {shlex.quote(name)}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

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
        # Sauvegardes de disque laissées par un redimensionnement (.qcow2.bak).
        for size, path in self._qemu_find_files(disk_dir, "*.qcow2.bak"):
            orphans.append((size, path, t("disk backup (resize)")))
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
                    env=self._qemu_c_env(),
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
    def _is_yes_default_yes(ans):
        """Comme _is_yes mais le DÉFAUT (réponse vide) est OUI."""
        a = ans.strip().lower()
        return a == "" or a in ("y", "yes", "o", "oui")

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

    @staticmethod
    def _qemu_lease_candidates(name):
        """Toutes les IPv4 candidates de la VM, agrégées de PLUSIEURS sources :
        - lease : base DHCP de dnsmasq (peut manquer sous forte charge, ou
          contenir plusieurs baux : bail précoce « ubuntu » périmé + bail
          définitif) ;
        - agent : qemu-guest-agent DANS la VM (voit l'IP réelle même quand le
          bail dnsmasq est absent) ;
        - arp : table ARP de l'hôte (VM active sur le réseau).
        On combine pour ne jamais rater une IP que le bail seul manquerait
        (cas observé : 30 VM émulées, bail dnsmasq vide alors que la VM a une
        IP)."""
        ips = []
        for source in ("lease", "agent", "arp"):
            try:
                res = subprocess.run(
                    ["sudo", "virsh", "domifaddr", name, "--source", source],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            for ip in re.findall(r"(\d+\.\d+\.\d+\.\d+)", res.stdout):
                # Ignore la loopback (remontée par --source agent).
                if ip != "127.0.0.1" and ip not in ips:
                    ips.append(ip)
        return ips

    @staticmethod
    def _qemu_ip_reachable(ip, port=22, timeout=2):
        """Vrai si la VM répond sur cette IP (bail ACTIF, pas périmé). On teste
        le PING d'abord : il répond dès que le réseau de la VM est up, BIEN
        AVANT sshd — sinon on attendait le sshd (lent en émulation) et la
        résolution semblait « bloquée » alors que la VM a déjà son IP. Repli
        TCP:port si l'ICMP est filtré."""
        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), ip],
                capture_output=True,
                timeout=timeout + 1,
            )
            if res.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        import socket

        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def _qemu_lease_ip_for_host(name, candidates):
        """Parmi `candidates`, l'IP dont le bail dnsmasq porte le hostname de la
        VM (le bail DÉFINITIF, pas le bail précoce « ubuntu »). None sinon."""
        try:
            res = subprocess.run(
                [
                    "sudo",
                    "sh",
                    "-c",
                    "cat /var/lib/libvirt/dnsmasq/*.status 2>/dev/null",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        # Plusieurs tableaux JSON concaténés : on parse chaque objet {...}.
        for obj in re.findall(r"\{[^{}]*\}", res.stdout or ""):
            if re.search(rf'"hostname":\s*"{re.escape(name)}"', obj):
                m = re.search(r'"ip-address":\s*"([\d.]+)"', obj)
                if m and m.group(1) in candidates:
                    return m.group(1)
        return None

    def _qemu_vm_ip(self, name, timeout=600):
        """IPv4 utilisable d'une VM. Gère le cas des baux multiples (hostname
        changé au boot) : renvoie en priorité le bail dont le hostname == nom
        de la VM, sinon une IP JOIGNABLE (sshd up), pour ne jamais retenir le
        bail précoce périmé. Attend jusqu'à `timeout` (boot émulé lent)."""
        deadline = time.time() + timeout
        cands = []
        while time.time() < deadline:
            cands = self._qemu_lease_candidates(name)
            if cands:
                # 1) bail définitif (hostname == nom de la VM)
                host_ip = self._qemu_lease_ip_for_host(name, cands)
                if host_ip:
                    return host_ip
                # 2) sinon, une IP déjà joignable (sshd up)
                for ip in cands:
                    if self._qemu_ip_reachable(ip):
                        return ip
            time.sleep(3)
        # Meilleur effort : le dernier bail (le plus récent) plutôt que le 1er.
        return cands[-1] if cands else None

    @staticmethod
    def _fmt_dur(secs):
        """Durée lisible : « 45s » ou « 2m05s »."""
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m{secs % 60:02d}s"

    def _qemu_resolve_ips(self, names, labels=None, timeout=300):
        """Résout les IP de plusieurs VM EN PARALLÈLE (le boot émulé est lent),
        en affichant la progression au fur et à mesure. Renvoie {nom: ip|None}.
        `labels` : {nom: « k/N »} pour préfixer chaque ligne d'un ID de suivi.
        `timeout` : délai max PAR VM (borne l'attente d'une VM sans IP). Un
        BATTEMENT toutes les 30 s liste les VM encore en attente -> jamais de
        silence prolongé qui donne l'impression d'un blocage."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from concurrent.futures import TimeoutError as _FTimeout

        labels = labels or {}
        print(f"\n{t('Resolving VM IPs (parallel, emulated boot is slow)...')}")
        result = {}
        t0 = time.time()
        starts = {}
        workers = min(len(names), (os.cpu_count() or 4)) or 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {}
            for n in names:
                starts[n] = time.time()
                futs[pool.submit(self._qemu_vm_ip, n, timeout)] = n
            pending = set(futs)
            done = 0
            while pending:
                try:
                    for fut in as_completed(list(pending), timeout=30):
                        pending.discard(fut)
                        n = futs[fut]
                        try:
                            ip = fut.result()
                        except Exception:
                            ip = None
                        result[n] = ip
                        done += 1
                        tag = f"[{labels[n]}] " if n in labels else ""
                        dur = self._fmt_dur(time.time() - starts[n])
                        print(
                            f"  [{done}/{len(names)}] {tag}{n}: "
                            f"{ip or t('no IP')} ({dur})"
                        )
                except _FTimeout:
                    # Battement : VM encore en attente (boot/DHCP lent).
                    waiting = [futs[f] for f in pending]
                    shown = ", ".join(waiting[:5])
                    if len(waiting) > 5:
                        shown += "…"
                    print(
                        f"  ⏳ {t('still waiting for')} {len(waiting)} VM "
                        f"({self._fmt_dur(time.time() - t0)}): {shown}"
                    )
        got = sum(1 for ip in result.values() if ip)
        print(
            f"  {t('IPs resolved:')} {got}/{len(names)} "
            f"({self._fmt_dur(time.time() - t0)})"
        )
        return result

    def _qemu_vm_arch(self, name):
        """Architecture d'une VM (jeton amd64/arm64/s390x) via virsh dumpxml."""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "dumpxml", name],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        m = re.search(r"<type[^>]*\barch='([^']+)'", res.stdout)
        if not m:
            return None
        return {
            "x86_64": "amd64",
            "aarch64": "arm64",
            "s390x": "s390x",
        }.get(m.group(1), m.group(1))

    def _qemu_vm_meta(self, name, mod):
        """(distro, version, arch) d'une VM déduits de son nom + son arch. Le
        nom suit _qemu_infra_name(distro, version, arch) : on retrouve donc
        (distro, version) en testant les combinaisons du catalogue."""
        arch = self._qemu_vm_arch(name) or "amd64"
        try:
            for d, (versions, _default) in mod.DISTROS.items():
                for v in versions:
                    if self._qemu_infra_name(d, v, arch) == name:
                        return d, v, arch
        except Exception:
            pass
        return None, None, arch

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

    # Paquets QEMU/libvirt pour le profil « Déploiement » (nos 3 gestionnaires).
    # Paquets SYSTÈME du profil « ERPLibre Déploiement » : QEMU/libvirt/
    # virtinst + libguestfs (virt-resize/virt-filesystems, requis pour la
    # RÉDUCTION SÛRE de disque). Ce sont des binaires système (OCaml) : ils ne
    # peuvent PAS vivre dans .venv.erplibre (venv Python) — d'où leur place ici.
    _QEMU_QEMU_PKGS = (
        "(sudo apt-get install -y qemu-kvm libvirt-daemon-system virtinst "
        "cloud-image-utils libguestfs-tools 2>/dev/null || sudo dnf install "
        "-y qemu-kvm libvirt virt-install cloud-utils guestfs-tools "
        "2>/dev/null || sudo pacman -S --needed --noconfirm qemu-desktop "
        "libvirt virt-install libguestfs 2>/dev/null || true)"
    )

    def _qemu_ask_prod(self):
        """Environnement cible : dev (défaut) ou prod. En PROD : ERPLibre est
        installé dans /opt/erplibre (au lieu de ~/git/erplibre) et le service
        systemd reste CONFINÉ par SELinux (pas d'unconfined)."""
        print(f"\n{t('Target environment?')}")
        print(f"  [1] {t('Development (~/git/erplibre, SELinux relaxed)')} *")
        print(f"  [2] {t('Production (/opt/erplibre, SELinux enforced)')}")
        sel = input(t("Choice (1-2, default 1): ")).strip()
        return sel == "2"

    def _qemu_pick_install_profile(self):
        """Choix de CE QU'ON installe sur la VM. Renvoie (label, commande
        finale exécutée dans ~/git/erplibre)."""
        profiles = [
            (
                f"ERPLibre + Odoo {v}",
                f"make install_os && make install_odoo_{v}",
            )
            for v in ("18", "17", "16", "15", "14", "13", "12")
        ]
        profiles += [
            (
                t("ERPLibre + all Odoo versions"),
                "make install_os && make install_odoo_all_version",
            ),
            (
                t("ERPLibre only (no Odoo)"),
                "make install_os && ./script/install/install_erplibre.sh",
            ),
            (
                t("ERPLibre mobile (home)"),
                "make install_os && ./mobile/install_and_run.sh",
            ),
            (
                t("ERPLibre Deployment (+ QEMU + dev)"),
                "make install_os && make install_dev && "
                + self._QEMU_QEMU_PKGS,
            ),
        ]
        print(f"\n{t('What to install on the VM(s)?')}")
        for i, (label, _cmd) in enumerate(profiles, 1):
            print(f"  [{i}] {label}{' *' if i == 1 else ''}")
        sel = input(t("Choice (number, blank = Odoo 18): ")).strip()
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]
        except ValueError:
            pass
        return profiles[0]  # défaut : ERPLibre + Odoo 18

    @staticmethod
    @staticmethod
    def _qemu_install_dir(prod):
        """Répertoire d'installation ERPLibre dans la VM : /opt/erplibre en
        PROD (hors /home -> service SELinux confiné possible), sinon
        ~/git/erplibre (dev)."""
        return "/opt/erplibre" if prod else "$HOME/git/erplibre"

    def _qemu_odoo_service_cmd(self, prod=False):
        """Snippet shell (exécuté dans la VM) qui installe ERPLibre/Odoo comme
        service systemd puis l'active. N'est ajouté QUE pour les profils Odoo.

        DEV : ERPLibre sous ~/home. Un service système ne peut PAS exécuter
        du user_home_t sous SELinux, et « SELinuxContext=unconfined » ne suffit
        pas (transition init_t -> unconfined_t refusée -> toujours 203/EXEC).
        Sur une VM de dev jetable, on passe donc SELinux en PERMISSIF (relâché).
        PROD : ERPLibre sous /opt/erplibre (hors user_home_t) -> le service
        reste CONFINÉ par SELinux ; on restaure les contextes (restorecon)."""
        svc_dir = self._qemu_install_dir(prod)
        selinux_shell = 'SELINUX_LINE=""; '  # pas de SELinuxContext (inefficace)
        if prod:
            pre = (
                "command -v restorecon >/dev/null 2>&1 && "
                "sudo restorecon -R /opt/erplibre >/dev/null 2>&1 || true; "
            )
        else:
            # DEV : SELinux permissif (persistant) si actif -> le service peut
            # exécuter run.sh/venv sous /home.
            pre = (
                "if command -v getenforce >/dev/null 2>&1 && "
                '[ "$(getenforce)" = "Enforcing" ]; then '
                "sudo setenforce 0 || true; "
                "sudo sed -i 's/^SELINUX=enforcing/SELINUX=permissive/' "
                "/etc/selinux/config 2>/dev/null || true; fi; "
            )
        return (
            f'SVC_USER=$(whoami); SVC_GROUP=$(id -gn); SVC_DIR="{svc_dir}"; '
            + pre
            + selinux_shell
            + "sudo tee /etc/systemd/system/erplibre.service >/dev/null <<UNIT\n"
            "[Unit]\n"
            "Description=ERPLibre\n"
            "Requires=postgresql.service\n"
            "After=network.target network-online.target postgresql.service\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            "User=$SVC_USER\n"
            "Group=$SVC_GROUP\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "ExecStart=$SVC_DIR/run.sh\n"
            "WorkingDirectory=$SVC_DIR\n"
            "StandardOutput=journal+console\n"
            "$SELINUX_LINE\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "UNIT\n"
            "sudo systemctl daemon-reload; "
            "sudo systemctl enable --now erplibre.service"
        )

    def _qemu_erplibre_remote_cmd(self, branch, final_cmd=None, prod=False):
        """Script d'installation ERPLibre exécuté DANS la VM (curl/git/make
        puis clone + `final_cmd`). `final_cmd` par défaut : install_os +
        install_odoo_18. `prod` : installe dans /opt/erplibre (au lieu de
        ~/git/erplibre) + service SELinux confiné."""
        if not final_cmd:
            final_cmd = f"make install_os && make {self.ERPLIBRE_ODOO_TARGET}"
        # Profils AVEC Odoo (install_odoo*) uniquement : après l'install, on
        # enregistre Odoo comme service systemd (enable + start). Pas pour
        # « ERPLibre seul », « mobile » ni « Déploiement ».
        if "install_odoo" in final_cmd:
            final_cmd = f"{final_cmd} && {self._qemu_odoo_service_cmd(prod)}"
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
            # Au 1er boot, cloud-init (install qemu-guest-agent) et/ou
            # apt-daily.service tiennent le verrou apt. IMPORTANT :
            # « DPkg::Lock::Timeout » NE couvre PAS le verrou
            # /var/lib/apt/lists/lock -> « apt-get update » échouait AUSSITÔT
            # (« Could not get lock … lists/lock ») -> lists vides -> « Unable
            # to locate package git ». On RÉESSAIE donc update jusqu'à ce que
            # le verrou se libère (et les lists soient peuplées), borné à ~5 min.
            "n=0; until sudo apt-get -o DPkg::Lock::Timeout=120 update -qq; do "
            "n=$((n+1)); [ $n -ge 30 ] && break; "
            'echo "apt verrouille (tentative $n), attente 10s..."; sleep 10; '
            "done; "
            "sudo apt-get -o DPkg::Lock::Timeout=600 install -y $PKGS; "
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
            # Clone : /opt/erplibre en PROD (racine, puis chown à l'utilisateur
            # pour que make/venv s'exécutent sans sudo), ~/git/erplibre en dev.
            + (
                (
                    "sudo mkdir -p /opt; "
                    "if [ ! -d /opt/erplibre/.git ]; then "
                    f"sudo git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} /opt/erplibre; "
                    "sudo chown -R $(id -un):$(id -gn) /opt/erplibre; fi; "
                    f"cd /opt/erplibre && {final_cmd}"
                )
                if prod
                else (
                    "mkdir -p ~/git; "
                    "if [ ! -d ~/git/erplibre/.git ]; then "
                    f"git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} ~/git/erplibre; fi; "
                    f"cd ~/git/erplibre && {final_cmd}"
                )
            )
        )

    def _qemu_install_erplibre_monitored(
        self, names, branch, ip_map=None, final_cmd=None, prod=False
    ):
        """Lance l'install ERPLibre en parallèle DÉTACHÉE sur les VM et ouvre
        le dashboard Textual. Quitter le dashboard n'arrête pas les installs.
        `ip_map` : IP déjà résolues (sinon on résout ici, EN PARALLÈLE).
        `final_cmd` : commande d'install selon le profil choisi.
        `prod` : install /opt/erplibre + service SELinux confiné."""
        from script.todo.qemu_install_monitor import (
            launch_installs,
            run_monitor,
        )

        remote = self._qemu_erplibre_remote_cmd(branch, final_cmd, prod)
        try:
            mod = self._qemu_import_module()
        except Exception:
            mod = None
        if ip_map is None:
            ip_map = self._qemu_resolve_ips(names)
        vms = []
        for name in names:
            ip = ip_map.get(name)
            if ip:
                d, v, a = (
                    self._qemu_vm_meta(name, mod)
                    if mod
                    else (None, None, None)
                )
                vms.append(
                    {
                        "name": name,
                        "ip": ip,
                        "distro": d,
                        "version": v,
                        "arch": a,
                    }
                )
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

    def _qemu_install_erplibre_vm(
        self, name, ssh_key, branch, ip=None, final_cmd=None, prod=False
    ):
        """Clone ERPLibre (branche donnée) dans la VM puis exécute la commande
        d'install du profil choisi (streamé). `ip` : IP déjà résolue ;
        `final_cmd` : commande d'install ; `prod` : /opt + SELinux confiné."""
        if ip is None:
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
        remote = self._qemu_erplibre_remote_cmd(branch, final_cmd, prod)
        ssh_opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=15"
        )
        cmd = f"ssh {ssh_opts} erplibre@{ip} {shlex.quote(remote)}"
        print(
            f"\n  📦 {name} ({ip}): {t('installing ERPLibre')} "
            f"({branch})"
        )
        print(f"  {t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    # vCPU de base (x1) par VM. Le multiplicateur monte de là.
    _QEMU_BASE_VCPUS = 2

    def _qemu_prompt_resource_mult(self, selected, host_cpu, free_ram):
        """Multiplicateur de ressources par VM : x1 (minimum catalogue) .. x4.
        Multiplie la RAM (base = minimum de la version) et les vCPU (base
        _QEMU_BASE_VCPUS), en bornant les vCPU au nombre de cœurs de l'hôte et
        en signalant si la RAM totale dépasse la RAM libre. Renvoie (mult,
        base_vcpus)."""
        base_ram = sum(s[2] for s in selected)  # RAM min totale (x1)
        base_vcpus = self._QEMU_BASE_VCPUS
        print(f"\n{t('Resources per VM (x1 = catalog minimum):')}")
        cpu_txt = f"{host_cpu} vCPU"
        ram_txt = (
            f"~{free_ram} Mo {t('free')}"
            if free_ram
            else t("free RAM unknown")
        )
        print(f"  {t('Host:')} {cpu_txt}, {ram_txt}")
        for n in (1, 2, 3, 4):
            vcpus = min(base_vcpus * n, host_cpu)
            total = base_ram * n
            star = " *" if n == 1 else ""
            warn = ""
            if free_ram and total > free_ram:
                warn = f"   ⚠ {t('> host free RAM')}"
            print(
                f"  [{n}] x{n}{star}  {vcpus} vCPU/VM, "
                f"{t('total RAM')} ~{total} Mo{warn}"
            )
        sel = input(f"{t('Choice (1-4, default 1):')} ").strip()
        try:
            n = int(sel)
            if 1 <= n <= 4:
                return n, base_vcpus
        except ValueError:
            pass
        return 1, base_vcpus

    def _qemu_customize_names(self, selected):
        """Noms des VM (liste parallèle à `selected`). Défaut = nom auto
        (_qemu_infra_name) ; on peut en renommer certains À LA DEMANDE, par
        leurs numéros séparés de virgules (vide = garder tous les noms auto)."""
        names = [
            self._qemu_infra_name(d, v, a) for d, v, _r, _dk, a in selected
        ]
        print(f"\n{t('VM names (default = auto):')}")
        for i, (nm, s) in enumerate(zip(names, selected), 1):
            d, v, _r, _dk, a = s
            print(f"  [{i}] {nm}   ({d} {v} [{a}])")
        raw = input(
            t("Rename which VMs? (numbers, comma-separated; blank = none): ")
        ).strip()
        for tok in re.split(r"[\s,]+", raw):
            if not tok:
                continue
            try:
                i = int(tok) - 1
            except ValueError:
                continue
            if 0 <= i < len(names):
                new = input(f"  {names[i]} {t('->')} ").strip()
                if new:
                    names[i] = new
        if len(set(names)) != len(names):
            print(f"  ⚠ {t('Duplicate names detected; keeping as entered.')}")
        return names

    def _qemu_build_deploy_parts(
        self, d, v, arch, name, eram, evcpus, disk, ssh_key, branch, dry_run
    ):
        """Construit la commande deploy_qemu.py d'UNE VM (utilisée pour l'aperçu
        dry-run ET le déploiement réel)."""
        parts = [] if dry_run else ["sudo"]
        parts += [
            self._qemu_script_path(),
            "--distro", d, "--version", v, "--name", name,
            "--memory", str(eram), "--vcpus", str(evcpus),
            "--password", "erplibre",
        ]
        if not dry_run:
            # --no-wait-ip : ne bloque pas 90s/VM, l'IP est collectée après.
            parts.append("--no-wait-ip")
        if arch and arch != "amd64":
            parts += ["--arch", arch]
        if ssh_key:
            parts += ["--ssh-key", ssh_key]
        if branch:
            # ERPLibre dépasse le minimum : +5 Go de disque.
            bigger = self._parse_disk_gb(disk) + self.ERPLIBRE_EXTRA_DISK_GB
            parts += ["--disk-size", f"{bigger}G"]
        parts.append("--dry-run" if dry_run else "-y")
        return parts

    def _qemu_deploy(self, dry_run=False):
        print(f"🚀 {t('Deploy ERPLibre VM(s)!')}")
        try:
            mod = self._qemu_import_module()
        except Exception as exc:
            print(f"{t('Cannot load QEMU catalog: ')}{exc}")
            return
        distros = list(mod.DISTROS)
        # Rappel de la dernière installation enregistrée (si historique).
        last = self._qemu_last_run_line()
        if last:
            print(last)

        # 0) Architecture du parc (défaut : native ; [all] = TOUTES les archis
        # supportées). Pour une arch précise non-amd64, on restreint le
        # catalogue aux distros qui la publient ; pour [all], chaque distro
        # reçoit uniquement les archis QU'ELLE publie.
        arch = self._qemu_prompt_infra_arch()  # amd64/arm64/s390x/all
        if arch != "all":
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

        def arches_for(distro):
            """Architectures à déployer pour cette distro selon le choix."""
            if arch != "all":
                return [arch]
            out = ["amd64"]
            if distro in self._QEMU_ARM64_DISTROS:
                out.append("arm64")
            if distro in self._QEMU_S390X_DISTROS:
                out.append("s390x")
            return out

        # 1) Distributions : multi-sélection, catalogue complet, principal (la
        # version par défaut de chaque distro, marquée d'un *), ou granulaire
        # (liste à plat de TOUTES les versions × archis, choix par virgules).
        # Avec [all] archis, chaque version se décline en une VM par archi.
        print(f"\n{t('Distributions:')}")
        for i, d in enumerate(distros, 1):
            default_v = mod.DISTROS[d][1]
            vers = ", ".join(
                (v + " *" if v == default_v else v) for v in mod.DISTROS[d][0]
            )
            print(f"  [{i}] {d} ({vers}){self._qemu_stat_avg('distro', d)}")
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

        selected = []  # (distro, version, ram_mb, disk_str, arch)
        if granular:
            # Liste APLATIE distro + version + ARCHITECTURE : on choisit des
            # combinaisons précises par numéros séparés de virgules.
            flat = []  # (distro, version, ram, disk, is_default, arch)
            for d in distros:
                versions_map, default_v = mod.DISTROS[d]
                for v, (_c, _o, ram, disk) in versions_map.items():
                    for a in arches_for(d):
                        flat.append((d, v, ram, disk, v == default_v, a))
            print(f"\n{t('All versions:')}")
            for i, (d, v, ram, disk, isdef, a) in enumerate(flat, 1):
                star = " *" if isdef else ""
                print(f"  [{i}] {d} {v}{star} [{a}]  (RAM≥{ram}Mo, {disk})")
            r = (
                input(t("Selection (comma-separated numbers): "))
                .strip()
                .lower()
            )
            for d, v, ram, disk, _isdef, a in self._parse_index_selection(
                r, flat
            ):
                selected.append((d, v, ram, disk, a))
        elif principal:
            # Une VM par distro (version par défaut) × chaque archi supportée.
            for d in distros:
                versions_map, default_v = mod.DISTROS[d]
                _c, _o, ram, disk = versions_map[default_v]
                for a in arches_for(d):
                    selected.append((d, default_v, ram, disk, a))
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
                    print(f"\n{t('Versions for')} {d.capitalize()} :")
                    for i, v in enumerate(vlist, 1):
                        _c, _o, ram, disk = versions_map[v]
                        stat = self._qemu_stat_avg("version", v, d)
                        print(f"  [{i}] {v}  (RAM≥{ram}Mo, {disk}){stat}")
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
                    for a in arches_for(d):
                        selected.append((d, v, ram, disk, a))
        if not selected:
            print(t("Nothing selected."))
            return

        # 2b) Multiplicateur de ressources par VM (x1 = minimum .. x4) : monte
        # la RAM et les vCPU selon ce que l'hôte peut fournir.
        host_cpu = os.cpu_count() or 2
        free_ram = self._host_free_ram_mb()
        res_mult, base_vcpus = self._qemu_prompt_resource_mult(
            selected, host_cpu, free_ram
        )

        def eff_res(ram):
            """(RAM effective, vCPU) pour une VM selon le multiplicateur."""
            return ram * res_mult, min(base_vcpus * res_mult, host_cpu)

        # 2c) Noms des VM (auto par défaut, renommage granulaire à la demande).
        names = self._qemu_customize_names(selected)

        # 3) Plan + estimation des ressources (avec le multiplicateur appliqué).
        total_ram = sum(s[2] * res_mult for s in selected)
        total_disk = sum(self._parse_disk_gb(s[3]) for s in selected)
        print(f"\n{t('Deployment plan')} ({len(selected)} VM, x{res_mult}) :")
        for i, (d, v, ram, disk, a) in enumerate(selected):
            eram, evcpus = eff_res(ram)
            print(
                f"  - {names[i]:<30} {d} {v:<7} [{a:<5}] "
                f"{evcpus} vCPU  RAM {eram}Mo  {t('disk')} {disk}"
            )
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

        # Aperçu (dry-run) : montre les commandes deploy_qemu sans rien créer
        # (ni sudo, ni installation), puis on s'arrête.
        if dry_run:
            default_key = self._qemu_default_ssh_key()
            print(f"\n{t('Preview (dry-run):')}")
            for i, (d, v, ram, disk, a) in enumerate(selected):
                eram, evcpus = eff_res(ram)
                parts = self._qemu_build_deploy_parts(
                    d, v, a, names[i], eram, evcpus, disk,
                    default_key, None, dry_run=True,
                )
                print("  " + " ".join(shlex.quote(p) for p in parts))
            return

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
        install_prod = False  # dev (~/git, SELinux dev) vs prod (/opt, confiné)
        install_cmd = None  # commande finale selon le profil choisi
        ans = input(
            t("Install ERPLibre into ~/git/erplibre on each VM? (y/N): ")
        )
        if self._is_yes(ans):
            install_branch = self._qemu_pick_branch()
            install_prod = self._qemu_ask_prod()
            _label, install_cmd = self._qemu_pick_install_profile()
            install_monitor = self._is_yes_default_yes(
                input(t("Interactive monitoring dashboard? (y/N): "))
            )

        add_ssh_config = self._is_yes(
            input(t("Add each VM to ~/.ssh/config? (y/N): "))
        )

        # 5) Sépare les VM à CRÉER des déjà existantes AVANT de proposer le
        # parallélisme : on connaît alors le vrai nombre à déployer (affiché
        # dans le prompt) et on peut numéroter chaque tâche.
        pending = []  # (name, d, v, ram, disk, a)
        deployed = []
        for i, (d, v, ram, disk, a) in enumerate(selected):
            name = names[i]
            if self._qemu_domain_exists(name):
                print(f"⏭  {name}: {t('already exists, skipped.')}")
                deployed.append(name)
            else:
                pending.append((name, d, v, ram, disk, a))
        n_jobs = len(pending)

        # Nombre de déploiements en parallèle. Défaut = nombre de CPU de l'hôte
        # (borné par le nombre de VM). On affiche aussi le NB DE VM à déployer.
        default_par = min(n_jobs, os.cpu_count() or 4) or 1
        raw = input(
            f"{t('Parallel deployments (default:')} {default_par}, "
            f"{n_jobs} {t('VMs')}): "
        ).strip()
        try:
            parallelism = max(1, int(raw)) if raw else default_par
        except ValueError:
            parallelism = default_par

        # Confirmation puis déploiement (en parallèle).
        ans = input(f"\n{t('Deploy these VMs now? (y/N): ')}")
        if not self._is_yes(ans):
            print(t("Cancelled."))
            return

        # Jobs numérotés (k/N) : l'ID suit l'ORDRE de préparation, stable même
        # si les résultats reviennent dans le désordre (exécution parallèle).
        jobs = []  # (id, name, parts)
        for k, (name, d, v, ram, disk, a) in enumerate(pending, 1):
            eram, evcpus = eff_res(ram)
            parts = self._qemu_build_deploy_parts(
                d, v, a, name, eram, evcpus, disk,
                ssh_key, install_branch, dry_run=False,
            )
            jobs.append((f"{k}/{n_jobs}", name, parts))

        deploy_start = time.time()
        n_ok = 0
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
                jid, jname, jparts = job
                j0 = time.time()
                res = subprocess.run(jparts, capture_output=True, text=True)
                out = (res.stdout or "") + (res.stderr or "")
                return jid, jname, res.returncode, out, time.time() - j0

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_run, j) for j in jobs]
                # done = ordre de COMPLÉTION (les résultats reviennent dans le
                # désordre) ; jid = ordre de préparation (stable). Durée par VM.
                for done, fut in enumerate(as_completed(futures), 1):
                    jid, jname, rc, out, secs = fut.result()
                    mark = "✅" if rc == 0 else "❌"
                    print(
                        f"\n[{done}/{len(jobs)}] {mark} [{jid}] {jname} "
                        f"(rc={rc}, {self._fmt_dur(secs)})"
                    )
                    tail = [ln for ln in out.strip().splitlines() if ln][-4:]
                    for ln in tail:
                        print(f"    {ln}")
                    if rc == 0:
                        deployed.append(jname)
                        n_ok += 1
            print(
                f"\n{t('Deploy summary:')} {n_ok} OK, "
                f"{len(jobs) - n_ok} {t('failed')}, "
                f"{len(jobs)} {t('VMs')}, {self._fmt_dur(time.time() - deploy_start)}"
            )

        # 6) Résolution des IP EN PARALLÈLE (réutilisée pour ssh_config +
        # install) : une boucle EN SÉRIE bloquait plusieurs minutes par VM
        # émulée SANS sortie -> le dashboard « n'ouvrait jamais ».
        ip_map = {}
        if deployed and (add_ssh_config or install_branch):
            labels = {
                nm: f"{k}/{len(deployed)}"
                for k, nm in enumerate(deployed, 1)
            }
            ip_map = self._qemu_resolve_ips(deployed, labels)

        if add_ssh_config:
            for name in deployed:
                ip = ip_map.get(name)
                if ip:
                    self._write_ssh_config_entry(name, "erplibre", ip)

        # 7) Installation ERPLibre (clone + make) si demandée.
        if install_branch:
            if install_monitor:
                # Installs détachées en parallèle + dashboard Textual.
                self._qemu_install_erplibre_monitored(
                    deployed, install_branch, ip_map, install_cmd,
                    install_prod,
                )
            else:
                print(
                    f"\n{t('Installing ERPLibre on each VM')} "
                    f"({install_branch})…"
                )
                for name in deployed:
                    self._qemu_install_erplibre_vm(
                        name,
                        ssh_key,
                        install_branch,
                        ip_map.get(name),
                        install_cmd,
                        install_prod,
                    )

        # Sommaire TOTAL (déploiement + résolution IP + ssh_config + install
        # synchrone ; l'install monitorée est détachée, non comptée ici).
        print(f"\n{'═' * 60}")
        print(f"  {t('TOTAL summary')}")
        print(f"  {t('VMs deployed:')} {n_ok}/{len(jobs) if jobs else 0}"
              f"  ({t('total incl. existing:')} {len(deployed)})")
        print(f"  {t('Total time:')} {self._fmt_dur(time.time() - deploy_start)}")
        print(f"{'═' * 60}")
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
