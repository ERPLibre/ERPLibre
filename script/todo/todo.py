#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import configparser
import datetime
import getpass
import grp
import inspect
import json
import logging
import os
import socket
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
from script.todo import todo_prefs
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
        help_info = f"""{self._menu_header()}
[1] {t("Execute")}
[2] {t("Install")}
[3] {t("Assistant")}
[4] {t("Fork - Open TODO in a new tab")}
[5] {t("Navigation telemetry (TUI)")}
[6] {t("Configuration")}
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
                self.prompt_assistant()
            elif status == "4":
                # cmd = (
                #     f"gnome-terminal --tab -- bash -c 'source"
                #     f" ./{VENV_ERPLIBRE}/bin/activate;make todo'"
                # )
                cmd = "make todo"
                self.execute.exec_command_live(cmd, source_erplibre=True)
            elif status == "5":
                self._todo_telemetry_tui()
            elif status == "6":
                self.prompt_configuration()
            # elif status == "3" or status == "install":
            #     print("install")
            else:
                print(t("Command not found !"))

        print(status)
        # manipuler()

    def prompt_assistant(self):
        """Ce qui s'adresse à l'humain : poser une question, lire son courriel."""
        from script.todo.mail.menu import prompt_execute_mail

        while True:
            help_info = f"""{self._menu_header()}
[1] {t("mail_ai_question")}
[2] {t("mail_menu")}
[0] {t("Back")}"""
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            if status == "1":
                self._assistant_question()
            elif status == "2":
                prompt_execute_mail(self)
            else:
                print(t("Command not found !"))

    def _assistant_question(self):
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
[7] {t("Analyse - Odoo database analysis")}

── {t("Sources & documentation")} ──
[8] {t("Git - Git tools")}
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
                status = self.prompt_execute_analyse()
                if status is not False:
                    return
            elif status == "8":
                status = self.prompt_execute_git()
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

        # Clé de CONFIGURATION, pas une chaîne d'interface : le passage aux
        # clés i18n en texte anglais (4fc15c3) a renommé celle-ci en
        # « Command: », le libellé affiché. Plus aucune entrée de todo.json
        # ne correspondait, et « Open ERPLibre with TODO 🤖 » ne faisait
        # plus rien — sans erreur, puisque le `if` était simplement faux.
        command = instance.get("command")
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
        "prompt_assistant": "Assistant",
        "prompt_install": "Install",
        "prompt_execute_function": "Automation",
        "prompt_execute_code": "Code",
        "prompt_execute_config": "Config",
        "prompt_execute_database": "Database",
        "prompt_execute_analyse": "Analyse",
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
        "prompt_configuration": "Configuration",
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
        from script.todo import textual_setup
        from script.todo.todo_telemetry import run_tui

        if not textual_setup.ensure():
            return
        state = None
        while True:
            try:
                result = run_tui(state=state)
            except ImportError:
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
            ans = input(f"\n{t('Back to telemetry (r) or quit (Enter)? ')}")
            if ans.strip().lower() not in ("r", "revenir", "o", "oui", "y"):
                return

    # Préférences éditables depuis le menu Configuration : clé, libellé, et
    # valeurs proposées (valeur stockée -> libellé affiché). Une seule table :
    # l'écran, la lecture et l'écriture en découlent.
    _PREF_CHOICES = {
        "qemu_deploy_ui": (
            "QEMU deployment interface",
            (
                ("ask", "Ask every time"),
                ("tui", "TUI form"),
                ("cli", "Classic questions (line by line)"),
            ),
        ),
        "qemu_deploy_progress": (
            "Display while deploying",
            (
                ("cli", "CLI output (easy to copy)"),
                ("tui", "TUI, collapsible blocks per VM"),
            ),
        ),
        "migration_ui": (
            "Odoo migration interface",
            (
                ("ask", "Ask every time"),
                ("tui", "TUI form"),
                ("cli", "Classic questions (line by line)"),
            ),
        ),
    }

    def _pref_label(self, key):
        """Libellé traduit de la valeur courante d'une préférence."""
        value = todo_prefs.get(key)
        for stored, label in self._PREF_CHOICES[key][1]:
            if stored == value:
                return t(label)
        return str(value)

    def _pref_edit(self, key):
        """Fait choisir une valeur parmi celles proposées pour `key`."""
        title, options = self._PREF_CHOICES[key]
        current = todo_prefs.get(key)
        print(f"\n{t(title)} :")
        for i, (stored, label) in enumerate(options, 1):
            star = " *" if stored == current else ""
            print(f"  [{i}] {t(label)}{star}")
        sel = input(f"{t('Choice (number, blank = keep):')} ").strip()
        try:
            idx = int(sel) - 1
        except ValueError:
            return
        if 0 <= idx < len(options):
            todo_prefs.set(key, options[idx][0])
            print(f"  ✅ {t(title)} : {self._pref_label(key)}")

    def prompt_configuration(self):
        """Réglages persistants de l'utilisateur (~/.erplibre/todo_prefs.json).
        La langue vit à part, dans env_var.sh, et garde son propre mécanisme.
        """
        while True:
            lang = "français" if get_lang() == "fr" else "English"
            choices = [
                {"section": t("Interface")},
                {"prompt_description": f"{t('Language / Langue')}  ({lang})"},
                {
                    "prompt_description": (
                        f"{t('QEMU deployment interface')}  "
                        f"({self._pref_label('qemu_deploy_ui')})"
                    )
                },
                {
                    "prompt_description": (
                        f"{t('Display while deploying')}  "
                        f"({self._pref_label('qemu_deploy_progress')})"
                    )
                },
                {
                    "prompt_description": (
                        f"{t('Odoo migration interface')}  "
                        f"({self._pref_label('migration_ui')})"
                    )
                },
                {"section": t("Maintenance")},
                {"prompt_description": t("Reset all preferences")},
            ]
            status = click.prompt(self.fill_help_info(choices))
            print()
            if status == "0":
                return
            elif status == "1":
                self._change_language()
            elif status == "2":
                self._pref_edit("qemu_deploy_ui")
            elif status == "3":
                self._pref_edit("qemu_deploy_progress")
            elif status == "4":
                self._pref_edit("migration_ui")
            elif status == "5":
                n = todo_prefs.reset()
                print(f"✅ {t('Preferences reset')} ({n})")
            else:
                print(t("Command not found !"))

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
                try:
                    upgrade.execute_odoo_upgrade()
                except todo_upgrade.MigrationRewind:
                    # L'état est déjà rembobiné et écrit : il ne reste qu'à
                    # relancer, et l'écran de reprise repartira de l'étape
                    # choisie. Sortir d'ici plutôt que de rappeler la méthode
                    # évite de la reprendre au milieu de son état local.
                    print(
                        f"\n⏪ {t('Rewound.')}"
                        f" {t('Relaunch the migration to resume from there.')}"
                    )
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
            {
                "prompt_description": t(
                    "SSH port forwarding (open Odoo in the browser)"
                )
            },
            {"section": t("Remote & services")},
            {"prompt_description": t("SSH (remote host)...")},
            {
                "prompt_description": t(
                    "QEMU/KVM - Deploy an Ubuntu VM (libvirt)"
                )
            },
            {
                "prompt_description": t(
                    "Deploy - Install NTFY notification server"
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
                self._deploy_port_forward()
            elif status == "4":
                self.prompt_execute_deploy_ssh()
            elif status == "5":
                self.prompt_execute_qemu()
            elif status == "6":
                self._deploy_ntfy_server()
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
        "ubuntu": (["24.04", "25.10", "26.04"], "24.04"),
        "debian": (["11", "12", "13"], "12"),
        "fedora": (["41", "42", "43", "44"], "42"),
        "almalinux": (["9", "10"], "9"),
        "rocky": (["9", "10"], "10"),
        # Leap 16.0 par défaut : numérotée et stable. Tumbleweed reste offerte,
        # comme banc d'essai des ruptures à venir. Voir OPENSUSE_VERSIONS dans
        # deploy_qemu.py, qui fait autorité sur le catalogue.
        "opensuse": (["16.0", "tumbleweed"], "16.0"),
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

    # Repli SEULEMENT : la table qui fait autorité est ARCH_DISTRO_SUPPORT de
    # deploy_qemu.py, lue par _qemu_arch_distros. Ces tuples ont longtemps été
    # une copie à la main, avec le commentaire « cohérent avec deploy_qemu » en
    # guise de garantie — et la cohérence a rompu à la première évolution :
    # Debian a gagné s390x là-bas sans l'obtenir ici, donc l'écran ne le
    # proposait pas. On ne les garde que pour le cas où l'import échoue.
    _QEMU_S390X_DISTROS = (
        "ubuntu",
        "almalinux",
        "rocky",
        "fedora",
        "opensuse",
        "debian",
    )
    _QEMU_ARM64_DISTROS = (
        "ubuntu",
        "debian",
        "fedora",
        "almalinux",
        "rocky",
        "opensuse",
    )
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
        """Distros supportant `arch` (None = toutes, cas amd64).

        Lu dans deploy_qemu.py, qui refuse aussi les combinaisons qu'il
        n'annonce pas : une seule table, donc aucun écran ne peut proposer un
        choix rejeté ensuite. « amd64 » n'y figure pas et rend None, ce qui
        veut bien dire « toutes » — c'est le contrat attendu ici.
        """
        try:
            table = getattr(self._qemu_import_module(), "ARCH_DISTRO_SUPPORT")
        except Exception:
            # Repli sur les copies locales : mieux vaut un catalogue figé
            # qu'un écran vide si deploy_qemu.py est absent ou cassé.
            if arch == "s390x":
                return self._QEMU_S390X_DISTROS
            if arch == "arm64":
                return self._QEMU_ARM64_DISTROS
            return None
        return table.get(arch)

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

    def _qemu_ensure_tools(self):
        """virsh absent : proposer l'installation plutôt que de laisser
        chaque commande échouer sur « sudo: virsh: command not found ».

        deploy_qemu.py --setup-host connaît les paquets de chaque
        distribution ; on ne devine donc rien ici, on le délègue."""
        if shutil.which("virsh"):
            return True
        print(f"\n⚠  {t('virsh is missing: libvirt is not installed here.')}")
        print(f"   {t('Every VM command will fail until it is.')}")
        if not self._is_yes_default_yes(
            input(t("Install the QEMU/libvirt tools now? (Y/n): "))
        ):
            return False
        cmd = f"sudo {self._QEMU_QEMU_PKGS}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)
        if shutil.which("virsh"):
            print(f"✅ {t('libvirt is available.')}")
            return True
        # Sur une distribution à noyau roulant, --setup-host peut demander un
        # redémarrage avant que les modules soient chargeables.
        print(f"⚠  {t('virsh still missing; a reboot may be required.')}")
        return False

    def prompt_execute_qemu(self):
        print(f"🤖 {t('Deploy a QEMU/KVM virtual machine (libvirt)!')}")
        script_path = self._qemu_script_path()
        if not os.path.isfile(script_path):
            print(f"{t('QEMU deploy script not found: ')}{script_path}")
            return False
        self._qemu_ensure_tools()
        choices = [
            {"section": t("Deployment")},
            {"prompt_description": t("Deploy VM(s) (one or many)")},
            {
                "prompt_description": t(
                    "Preview a deployment (dry-run, no sudo)"
                )
            },
            {"prompt_description": t("Download a cloud image only")},
            {
                "prompt_description": t(
                    "Reopen install monitoring (last run / history)"
                )
            },
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
            {"prompt_description": t("Statistics (installs, durations, VMs)")},
            {
                "prompt_description": t(
                    "SSH configuration (~/.ssh/config, ProxyJump)"
                )
            },
            {
                "prompt_description": t(
                    "Remote desktop tunnel (VNC/RDP through SSH)"
                )
            },
            {
                "prompt_description": t(
                    "Android emulator (start, tunnel, scrcpy)"
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
                self._qemu_reopen_monitor()
            elif status == "5":
                self._qemu_list_vms(ask_advanced=True)
            elif status == "6":
                self._qemu_show_ip()
            elif status == "7":
                self._qemu_console()
            elif status == "8":
                self._qemu_resize_disk()
            elif status == "9":
                self._qemu_delete_vm()
            elif status == "10":
                self._qemu_cleanup()
            elif status == "11":
                self._qemu_test_vm()
            elif status == "12":
                self._qemu_stats()
            elif status == "13":
                self._qemu_ssh_config_menu()
            elif status == "14":
                self._qemu_tunnel_menu()
            elif status == "15":
                self._qemu_emulator_menu()
            elif status == "16":
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

    # Compte créé par cloud-init dans les VM déployées ici. Sert de défaut
    # quand ~/.ssh/config ne déclare aucun `User` pour l'hôte adopté.
    QEMU_VM_USER = "erplibre"

    # Profondeur d'exploration par défaut : hôte -> VM -> VM imbriquée. Le
    # profil « ERPLibre Déploiement (+ QEMU + dev) » installe QEMU DANS la VM,
    # donc un parc à deux niveaux est le cas courant.
    _QEMU_SSH_DEPTH = 2
    # Sonde exécutée SUR une machine. Première ligne « LIBVIRT<TAB>yes|no »,
    # puis un couple « nom<TAB>ip » par VM. Une seule connexion SSH par
    # niveau plutôt qu'une par VM ; le bail dnsmasq peut manquer, d'où le
    # repli sur l'agent invité.
    #
    # La première ligne est indispensable : sans virsh, la boucle ne tourne
    # simplement pas et la sonde sortirait VIDE avec un code 0 — impossible
    # alors de distinguer « pas de QEMU ici » de « QEMU présent, aucune VM ».
    # Sonde exécutée à DISTANCE, dans une session SSH non interactive.
    #
    # « sudo virsh » y échoue dès que l'hôte demande un mot de passe — vécu sur
    # erplibre01 (sudo-rs) — et la sonde répondait alors « pas de QEMU » sur une
    # machine qui en fait tourner. On essaie donc virsh SANS sudo d'abord, via
    # qemu:///system : appartenir au groupe libvirt suffit, sans tty.
    #
    # « --connect qemu:///system » est indispensable dans ce cas : sans lui, un
    # utilisateur non root tombe sur qemu:///session, qui répond correctement…
    # une liste VIDE. On aurait alors « QEMU présent, aucune VM », ce qui est
    # pire qu'une erreur puisque c'est plausible.
    #
    # Trois réponses et non deux : « denied » distingue « virsh est là mais
    # inaccessible » de « pas de QEMU ici », deux situations qui appellent des
    # gestes opposés.
    _QEMU_SSH_PROBE = (
        'vsh() { virsh --connect qemu:///system "$@" 2>/dev/null '
        '|| sudo -n virsh --connect qemu:///system "$@" 2>/dev/null; }; '
        "if ! command -v virsh >/dev/null 2>&1; then "
        "printf 'LIBVIRT\\tno\\n'; exit 0; fi; "
        "vms=$(vsh list --all --name) || "
        "{ printf 'LIBVIRT\\tdenied\\n'; exit 0; }; "
        "printf 'LIBVIRT\\tyes\\n'; "
        "for n in $vms; do "
        'ip=$(vsh domifaddr "$n" --source lease '
        "| grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' | head -1); "
        'if [ -z "$ip" ]; then '
        'ip=$(vsh domifaddr "$n" --source agent '
        "| grep -oE '([0-9]{1,3}\\.){3}[0-9]{1,3}' "
        "| grep -v '^127\\.' | head -1); fi; "
        'printf "%s\\t%s\\n" "$n" "$ip"; done'
    )

    def _qemu_ssh_pick_roots(self):
        """D'où partir pour configurer ~/.ssh/config. Renvoie une liste de
        racines [{alias, ip|None}], ou [] pour renoncer.

        Trois provenances, parce que « la machine à configurer » n'est pas
        toujours une VM d'ici : elle peut être un hôte déjà connu de
        ~/.ssh/config, ou une adresse qu'on vient d'obtenir."""
        print(f"\n{t('Where should the machines come from?')}")
        print(f"  [1] {t('Local QEMU VMs (virsh)')} *")
        print(f"  [2] {t('Hosts from ~/.ssh/config')}")
        print(f"  [3] {t('Type a host or an IP')}")
        print(f"  [0] {t('Back')}")
        answer = input(t("Choice (0-3, default 1): ")).strip()
        if answer == "0":
            return []

        if answer == "2":
            hosts = self._ssh_config_hosts()
            if not hosts:
                print(f"  {t('~/.ssh/config holds no host.')}")
                return []
            for i, name in enumerate(hosts, 1):
                print(f"  [{i}] {name}")
            raw = input(
                t("Which hosts? (numbers, comma-separated; blank = all): ")
            ).strip()
            chosen = (
                hosts if not raw else self._parse_index_selection(raw, hosts)
            )
            # Déjà dans ~/.ssh/config : leur adresse y est, rien à réécrire.
            # Le `User` déclaré est repris tel quel : ces hôtes ne sont pas
            # forcément des VM ERPLibre, et leurs invitées suivent la même
            # convention que leur parent.
            return [
                {
                    "alias": name,
                    "ip": None,
                    "user": self._ssh_config_user(name),
                }
                for name in chosen or hosts
            ]

        if answer == "3":
            target = input(f"{t('Host or IP:')} ").strip()
            if not target:
                return []
            if target in self._ssh_config_hosts():
                return [
                    {
                        "alias": target,
                        "ip": None,
                        "user": self._ssh_config_user(target),
                    }
                ]
            # « utilisateur@hôte » est accepté : c'est la forme qu'on tape
            # naturellement, et elle évite une question de plus.
            user, _, address = target.rpartition("@")
            # Une IP brute n'est pas un alias : on lui en donne un, sinon ni
            # le ProxyJump des enfants ni virt-manager n'auraient de nom.
            default_alias = "qemu-" + address.replace(".", "-")
            alias = (
                input(
                    f"{t('Name for ~/.ssh/config')} ({default_alias}): "
                ).strip()
                or default_alias
            )
            if not user:
                user = (
                    input(f"{t('User')} ({self.QEMU_VM_USER}): ").strip()
                    or self.QEMU_VM_USER
                )
            return [{"alias": alias, "ip": address, "user": user}]

        names = self._qemu_pick_domains()
        if not names:
            return []
        ip_map = self._qemu_resolve_ips(names, timeout=60)
        roots = []
        for name in names:
            ip = ip_map.get(name)
            if not ip:
                print(f"  ⏭  {name}: {t('no IP')}")
                continue
            roots.append({"alias": name, "ip": ip})
        return roots

    # Ports du bureau distant, par gestionnaire de paquets de la VM. Ils
    # viennent de _QEMU_DESKTOP_REMOTE, seule source : xrdp sur 3389 partout,
    # sauf Arch qui reçoit TigerVNC sur 5901.
    @classmethod
    def _qemu_desktop_port(cls, distro):
        if distro == "arch":
            return cls._QEMU_DESKTOP_REMOTE["pacman"]["port"], "VNC"
        return cls._QEMU_DESKTOP_REMOTE["apt"]["port"], "RDP"

    @staticmethod
    def _qemu_self_address():
        """Adresse par laquelle l'utilisateur a JOINT cet hôte.

        SSH_CONNECTION porte « ip_client port_client ip_serveur port_serveur » :
        le troisième champ est exactement l'adresse à remettre dans la commande
        de tunnel, bien mieux qu'un « hostname » qui peut ne rien résoudre
        depuis le poste de travail. Hors session SSH, on retombe sur le nom
        d'hôte, en le signalant."""
        conn = os.environ.get("SSH_CONNECTION", "").split()
        if len(conn) >= 3:
            return conn[2], True
        return socket.gethostname(), False

    def _qemu_tunnel_menu(self):
        """Commande de tunnel SSH vers le bureau distant d'une machine.

        La source des cibles est ~/.ssh/config, PAS le libvirt local. La VM
        graphique est souvent imbriquee : un orchestrateur QEMU tourne dans une
        VM, et la machine a bureau vit DANS cet orchestrateur. Le « virsh » du
        poste ne voit alors que l'orchestrateur, et proposer sa liste menait
        droit a la mauvaise machine — vecu.

        ~/.ssh/config, lui, connait les deux, ProxyJump compris : c'est la
        seule vue qui traverse les niveaux. Les domaines libvirt LOCAUX sont
        ajoutes en complement quand ils ne s'y trouvent pas deja.
        """
        print(f"\n🖥  {t('Remote desktop tunnel')}")
        hosts = list(self._ssh_config_hosts())
        targets = [(h, "ssh_config") for h in hosts]
        # Complement local, sans sudo tant qu'on n'en a pas besoin : la
        # plupart des cibles utiles sont deja dans ssh_config.
        if not targets:
            for name in self._qemu_list_domains():
                targets.append((name, "virsh"))
        if not targets:
            print(f"  {t('No host in ~/.ssh/config and no local VM.')}")
            return
        for i, (name, src) in enumerate(targets, 1):
            mark = "" if src == "ssh_config" else f"  ({t('local VM')})"
            print(f"  [{i}] {name}{mark}")
        answer = input(f"{t('Which VM?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not (1 <= int(answer) <= len(targets)):
            print(t("Cancelled."))
            return
        name, src = targets[int(answer) - 1]

        # Le port ne se devine pas pour un hote de ssh_config : on ne connait
        # ni sa distribution ni son bureau. On propose, l'utilisateur tranche.
        print(f"\n  {t('Remote desktop kind:')}")
        print(f"  [1] RDP 3389 (xrdp) *")
        print(f"  [2] VNC 5901 (TigerVNC, Arch)")
        print(
            f"  [3] {t('Hypervisor console (QEMU screen, no guest server)')}"
        )
        print(f"  [4] {t('Android emulator (adb 5555, then scrcpy)')}")
        print(f"  [5] {t('Graphical console (virt-viewer, built-in tunnel)')}")
        kind_answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        if kind_answer == "3":
            self._qemu_console_tunnel(name, src)
            return
        if kind_answer == "4":
            self._qemu_scrcpy_tunnel(name, src)
            return
        if kind_answer == "5":
            self._qemu_virt_viewer(name, src)
            return
        port, kind = (5901, "VNC") if kind_answer == "2" else (3389, "RDP")
        local = port + 1

        print(f"\n  {t('Run this on YOUR workstation:')}")
        if src == "ssh_config":
            # « localhost » est resolu par le DERNIER saut, donc par la machine
            # elle-meme : le ProxyJump de ssh_config traverse les niveaux.
            print(f"\n    ssh -N -L {local}:localhost:{port} {name}\n")
            print(f"  {t('(through the ProxyJump already in ~/.ssh/config)')}")
        else:
            ip = self._qemu_resolve_ips([name]).get(name)
            if not ip:
                print(f"  {t('No IP for this VM; is it running?')}")
                return
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            if not from_ssh:
                print(
                    f"  ⚠ {t('Not in an SSH session: check the host address.')}"
                )
            print(f"\n    ssh -N -L {local}:{ip}:{port} {user}@{host}\n")
            print(f"  ⚠ {t('No ~/.ssh/config entry; see SSH configuration.')}")
        print(
            f"  {t('then point your client at')} localhost:{local}  ({kind})"
        )
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")

    @staticmethod
    def _qemu_ssh_opts(src):
        """Options ssh selon la provenance de la cible.

        Une VM libvirt locale est jointe par son IP, et son IP est recyclée d'un
        déploiement à l'autre : sa clé d'hôte change sous le même adresse, et
        ssh refuse alors de se connecter — « Host key verification failed »,
        vécu. C'est la raison pour laquelle le suivi d'installation et l'attente
        de sshd emploient déjà ces deux options.

        Un hôte de ~/.ssh/config, lui, est une machine que l'utilisateur a
        configurée : on ne touche PAS à sa politique de clés. Sa clé est un
        garde-fou qui lui appartient."""
        if src == "ssh_config":
            return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
        return [
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]

    def _qemu_ssh_target(self, name, src):
        """Destination ssh d'une cible du menu, selon sa provenance.

        Un hôte de ~/.ssh/config se nomme tel quel — c'est lui qui porte le
        ProxyJump, et le réécrire à la main reviendrait à le deviner. Un domaine
        libvirt local, lui, n'a qu'une IP, et l'utilisateur des VM ERPLibre est
        « erplibre ». Renvoie une chaîne vide quand l'IP manque."""
        if src == "ssh_config":
            return name
        ip = self._qemu_resolve_ips([name]).get(name)
        return f"erplibre@{ip}" if ip else ""

    # Commande de l'émulateur dans la VM. Le chemin est ABSOLU : un
    # « ssh hôte 'commande' » ne lit ni ~/.profile ni ~/.bashrc.
    _QEMU_EMULATOR_BIN = "$HOME/android/emulator/emulator"

    # Drapeaux passés à CHAQUE lancement, et non écrits dans le config.ini de
    # l'AVD : l'émulateur réécrit ce fichier depuis le profil du téléphone au
    # premier démarrage, et les hw.lcd.* y étaient effacés — l'AVD repartait en
    # 1080x2400 densité 420, quatre fois les pixels voulus. Mesuré.
    #
    # La résolution et la DENSITÉ vont ensemble, et c'est contre-intuitif :
    # 540x1140 en densité 420 est PIRE que le plein écran — 81 ms de médiane
    # contre 40, et 57 % d'images en retard contre 37, tout étant rendu énorme.
    # Avec la densité 240, la queue s'effondre : 99e centile à 250 ms contre
    # 950, et 32 % d'images en retard.
    #
    # « -no-snapshot-save » : sans lui, un émulateur tué par pkill — ce que ce
    # menu propose lui-même — laisse un instantané en cours, et le lancement
    # SUIVANT meurt sur « A snapshot operation is pending and timeout has
    # expired ». Vécu, et le message ne dit pas quoi faire.
    # « -gpu » reste sur swangle par DÉFAUT, même quand la VM a la 3D : un
    # « -gpu host » qui échoue ne rend pas la main, l'émulateur reste pendu, et
    # ce n'est pas un défaut à imposer sans l'avoir mesuré sur la machine.
    # EL_EMULATOR_GPU permet de l'essayer sans toucher au code, une fois le
    # nœud de rendu présent dans l'invité (voir script/qemu/README).
    _QEMU_EMULATOR_GPU = os.environ.get("EL_EMULATOR_GPU") or "swangle"
    _QEMU_EMULATOR_FLAGS = (
        "-no-audio -no-boot-anim -no-snapshot-save"
        f" -gpu {_QEMU_EMULATOR_GPU}"
        " -skin 540x1140 -prop qemu.sf.lcd_density=240"
    )
    _QEMU_AVD_NAME = "erplibre"

    def _qemu_emulator_running(self, target, src="virsh"):
        """Nombre d'émulateurs en cours dans la VM.

        Deux sur le même AVD, et le second s'arrête sur « Running multiple
        emulators with the same AVD is an experimental feature ». Le savoir
        AVANT de lancer évite de lire cette phrase sans la comprendre — vécu,
        deux fois."""
        try:
            res = subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, "pgrep -c qemu-system 2>/dev/null || echo 0"],
                capture_output=True,
                text=True,
                timeout=25,
            )
            return int((res.stdout or "0").strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return -1

    def _qemu_emulator_ready(self, target, src="virsh"):
        """La VM a-t-elle de quoi émuler ? Rend (prêt, raison).

        Le binaire ET l'AVD, en une seule lecture : sans cette vérification le
        démarrage détaché rendait 0 sur une VM sans SDK, et le menu annonçait
        « Démarré » quand le journal disait « not found ». Une VM déployée sans
        cocher l'outil Émulateur Android est le cas normal, pas une panne."""
        probe = (
            f"test -x {self._QEMU_EMULATOR_BIN} || echo NO_SDK; "
            f"test -d $HOME/.android/avd/{self._QEMU_AVD_NAME}.avd"
            " || echo NO_AVD"
        )
        try:
            res = subprocess.run(
                ["ssh"] + self._qemu_ssh_opts(src) + [target, probe],
                capture_output=True,
                text=True,
                timeout=25,
            )
        except (OSError, subprocess.SubprocessError):
            return False, t("Cannot reach this VM.")
        out = res.stdout or ""
        if "NO_SDK" in out:
            return False, t("No Android SDK in this VM: no emulator binary.")
        if "NO_AVD" in out:
            return False, t("No AVD named erplibre in this VM.")
        return True, ""

    def _qemu_emulator_menu(self):
        """Démarre l'émulateur Android d'une VM, et donne la suite qui va avec.

        La question qui décide de tout est celle de la FENÊTRE :
          - avec fenêtre, l'écran voyage en pixels bruts par X11, et la commande
            doit partir du poste qui possède l'affichage — donc pas d'ici ;
          - sans fenêtre, on peut la lancer d'ici, détachée, et l'image arrive
            ensuite par scrcpy en H.264. C'est la voie fluide.
        """
        print(f"\n📱 {t('Android emulator')}")
        targets = [(h, "ssh_config") for h in self._ssh_config_hosts()]
        if not targets:
            targets = [(n, "virsh") for n in self._qemu_list_domains()]
        if not targets:
            print(f"  {t('No host in ~/.ssh/config and no local VM.')}")
            return
        for i, (nm, sr) in enumerate(targets, 1):
            mark = "" if sr == "ssh_config" else f"  ({t('local VM')})"
            print(f"  [{i}] {nm}{mark}")
        answer = input(f"{t('Which VM?')} [1]: ").strip() or "1"
        if not answer.isdigit() or not (1 <= int(answer) <= len(targets)):
            print(t("Cancelled."))
            return
        name, src = targets[int(answer) - 1]
        target = self._qemu_ssh_target(name, src)
        if not target:
            print(f"  {t('No IP for this VM; is it running?')}")
            return

        running = self._qemu_emulator_running(target, src)
        if running > 0:
            print(f"\n  ⚠ {t('An emulator is already running on this VM.')}")
            print(f"  {t('Only one per AVD; close it first:')}")
            print(f"\n    ssh {target} 'pkill -f \"[q]emu-system-x86_64\"'\n")
            if not self._is_yes(input(t("Close it now? (y/N): "))):
                return
            subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, 'pkill -f "[q]emu-system-x86_64"'],
                capture_output=True,
                timeout=30,
            )
            print(f"  {t('Closed.')}")

        ready, why = self._qemu_emulator_ready(target, src)
        if not ready:
            print(f"\n  ⚠ {why}")
            print(f"  {t('Tick the Android emulator tool when deploying.')}")
            return

        print(f"\n  {t('Show a window?')}")
        print(f"  [1] {t('No window - stream with scrcpy (smoother)')} *")
        print(f"  [2] {t('Window over ssh -X (raw pixels, slower)')}")
        kind = input(f"{t('Choice')} [1]: ").strip() or "1"
        # Sans cette validation, TOUT ce qui n'est pas « 2 » démarrait
        # l'émulateur : une frappe de travers (« n ») lançait le démarrage,
        # observé. Un menu à deux crans n'a pas de troisième réponse.
        if kind not in ("1", "2"):
            print(t("Cancelled."))
            return
        emu = self._QEMU_EMULATOR_BIN
        avd = self._QEMU_AVD_NAME

        if kind == "2":
            # L'affichage appartient au POSTE : cette commande ne peut pas
            # partir d'ici, où il n'y a pas d'écran à lui donner.
            print(f"\n  {t('Run this on YOUR workstation:')}")
            print(
                f"\n    ssh -XC {target} '{emu} -avd {avd} "
                f"{self._QEMU_EMULATOR_FLAGS}'\n"
            )
            print(
                f"  {t('X11 compression is on (-XC); the screen is 540x1140.')}"
            )
            return

        print(f"\n  {t('Starting the emulator without a window...')}")
        # « sg kvm » : l'appartenance au groupe est posée à l'installation, mais
        # une VM créée avant ce correctif ne l'a pas dans sa session — sans KVM
        # l'émulateur refuse de démarrer. setsid le détache, pour qu'il survive
        # à la fermeture de ce ssh.
        start = (
            f'setsid -f sg kvm -c "{emu} -avd {avd} -no-window '
            f"{self._QEMU_EMULATOR_FLAGS}"
            ' > /tmp/erplibre-emulator.log 2>&1"'
        )
        res = subprocess.run(
            ["ssh"] + self._qemu_ssh_opts(src) + [target, start],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode:
            print(f"  ⚠ {t('Could not start it:')} {res.stderr.strip()[:200]}")
            return
        # « setsid » détache : le code de retour ne dit RIEN de l'émulateur.
        # Le menu annonçait « Démarré » pendant que le journal de la VM disait
        # « not found » — mesuré sur une VM sans SDK. On attend donc de voir le
        # processus, et à défaut on rapporte le journal.
        for _ in range(5):
            if self._qemu_emulator_running(target, src) > 0:
                break
            time.sleep(2)
        else:
            print(f"  ⚠ {t('It did not start; the VM log says:')}")
            log = subprocess.run(
                ["ssh"]
                + self._qemu_ssh_opts(src)
                + [target, "tail -5 /tmp/erplibre-emulator.log 2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=25,
            )
            for line in (log.stdout or "").strip().splitlines():
                print(f"    {line}")
            return
        print(
            f"  {t('Started. Boot takes about a minute; log in the VM:')}"
            " /tmp/erplibre-emulator.log"
        )
        self._qemu_scrcpy_tunnel(name, src, started=True)

    def _qemu_scrcpy_tunnel(self, name, src, started=False):
        """Tunnel adb vers l'émulateur Android d'une VM, pour scrcpy.

        Pourquoi cette voie plutôt que « ssh -X » : par X11, chaque image de
        l'écran traverse le réseau en pixels bruts — 0,62 Mpixel par image même
        après réduction, en rendu logiciel. scrcpy, lui, reçoit un flux H.264
        encodé PAR l'appareil et le décode sur le poste. L'émulateur tourne
        alors SANS fenêtre : plus de X11 du tout, ni sur l'hôte ni dans la VM.

        Le port est celui de l'émulateur, pas celui du serveur adb. Un émulateur
        écoute sur 5554 (console) et 5555 (adb), tous deux sur le localhost de
        la VM — vérifié par « ss -ltn ». C'est 5555 qu'il faut, et non 5037 :
        tunneler le serveur adb obligerait à tuer celui du poste, qui occupe le
        même port.

        Vérifié de bout en bout à travers le tunnel : une poignée de main adb
        (paquet CNXN) reçoit « device::ro.product.name=sdk_gphone64_x86 » de
        l'émulateur lui-même — c'est exactement ce que fait « adb connect ».
        """
        port = 5555
        target = self._qemu_ssh_target(name, src)
        if not target:
            print(f"  {t('No IP for this VM; is it running?')}")
            return
        print(f"\n  📱 {t('Android emulator over adb + scrcpy')}")
        if started:
            # Inutile de redire comment le démarrer : on vient de le faire.
            print(f"\n  {t('1. Emulator started, without a window.')}")
        else:
            print(
                f"\n  {t('1. In the VM, start the emulator WITHOUT a window:')}"
            )
            print(
                f"\n    ssh {target} '{self._QEMU_EMULATOR_BIN} "
                f"-avd {self._QEMU_AVD_NAME} -no-window "
                f"{self._QEMU_EMULATOR_FLAGS}'\n"
            )
        print(f"  {t('2. Open the tunnel from YOUR workstation:')}")
        if src == "ssh_config":
            # « localhost » est résolu par le DERNIER saut, donc par la VM
            # elle-même : le ProxyJump de ssh_config traverse les niveaux.
            print(f"\n    ssh -N -L {port}:localhost:{port} {name}\n")
            print(f"  {t('(through the ProxyJump already in ~/.ssh/config)')}")
        else:
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            vm_ip = target.split("@")[-1]
            if not from_ssh:
                print(
                    f"  ⚠ {t('Not in an SSH session: check the host address.')}"
                )
            # DEUX sauts, et non un seul vers l'hyperviseur : l'émulateur
            # n'écoute que sur le 127.0.0.1 de la VM — « ss -ltn » le montre, et
            # l'hyperviseur reçoit un refus sur IP_VM:5555. Or « localhost » se
            # résout sur le DERNIER hôte de la chaîne : la VM doit donc être ce
            # dernier saut, l'hyperviseur n'étant que le relais (-J).
            print(
                f"\n    ssh -N -L {port}:localhost:{port}"
                f" -J {user}@{host} erplibre@{vm_ip}\n"
            )
            print(
                f"  {t('(the hypervisor only relays; -J puts the VM last)')}"
            )
        print(f"  {t('3. Then, still on your workstation:')}")
        print(f"\n    adb connect localhost:{port}")
        print(f"    scrcpy -s localhost:{port}\n")
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")
        print(f"  {t('scrcpy on Debian/Ubuntu:')} sudo apt install scrcpy adb")

        # Ouvrir le tunnel D'ICI n'a de sens que si scrcpy tournera ici : le
        # port ressort sur CETTE machine. On le propose donc en le disant,
        # plutôt que de le faire d'office depuis un hyperviseur sans écran.
        print(f"\n  {t('If scrcpy will run on THIS machine, I can open it.')}")
        if not self._is_yes(input(t("Open the tunnel now? (y/N): "))):
            return
        if self._port_in_use(port):
            print(f"  ⚠ {t('Port already in use here:')} {port}")
            print(
                f"  {t('Close the other tunnel first:')}"
                f' pkill -f "{port}:localhost:{port}"'
            )
            return
        # « ExitOnForwardFailure » : sans lui, un ssh détaché rend 0 alors que
        # la redirection a échoué — un succès annoncé pour un tunnel absent.
        cmd = (
            ["ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes"]
            + self._qemu_ssh_opts(src)
            + ["-L", f"{port}:localhost:{port}", target]
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        if res.returncode:
            print(f"  ⚠ {t('Tunnel failed:')} {res.stderr.strip()[:200]}")
            return
        print(f"  ✅ {t('Tunnel open on localhost:')}{port}")
        print(
            f"  {t('Then:')} adb connect localhost:{port}"
            f" && scrcpy -s localhost:{port}"
        )
        print(f'  {t("To close it:")} pkill -f "{port}:localhost:{port}"')

    @staticmethod
    def _port_in_use(port):
        """Le port est-il déjà pris sur CETTE machine ?

        Un second tunnel sur le même port échouerait, et le message d'ssh
        (« bind: Address already in use ») se perd en mode détaché."""
        with socket.socket() as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    # Un paquet, quatre familles. virt-viewer porte le même nom partout, ce qui
    # est rare et bienvenu : seule la commande d'installation change.
    _QEMU_VIRT_VIEWER_INSTALL = (
        ("apt-get", "sudo apt-get install -y virt-viewer"),
        ("dnf", "sudo dnf install -y virt-viewer"),
        ("pacman", "sudo pacman -S --needed --noconfirm virt-viewer"),
        ("zypper", "sudo zypper --non-interactive install virt-viewer"),
    )

    def _qemu_ensure_virt_viewer(self):
        """virt-viewer sur CETTE machine, installé s'il manque.

        Installé seulement là où il va SERVIR : sur un hyperviseur sans écran,
        poser un client graphique ne rendrait service à personne. C'est
        l'appelant qui a vérifié l'affichage."""
        if shutil.which("virt-viewer"):
            return True
        print(f"\n  {t('virt-viewer is missing here; installing it.')}")
        for tool, cmd in self._QEMU_VIRT_VIEWER_INSTALL:
            if shutil.which(tool):
                print(f"  {t('Will execute:')} {cmd}")
                self.execute.exec_command_live(cmd, source_erplibre=False)
                break
        else:
            print(f"  ⚠ {t('no known package manager here.')}")
            return False
        if shutil.which("virt-viewer"):
            print(f"  ✅ virt-viewer")
            return True
        print(f"  ⚠ {t('virt-viewer still missing after the install.')}")
        return False

    def _qemu_virt_viewer(self, name, src):
        """Ouvre l'écran d'une VM avec virt-viewer, qui monte SON tunnel.

        C'est la voie la plus courte : virt-viewer parle à libvirt par
        « qemu+ssh:// » et n'a besoin d'aucun « ssh -L » à tenir ouvert. Il lit
        aussi le port de l'écran par libvirt, donc rien à deviner.

        La seule question qui compte est celle de l'AFFICHAGE. virt-viewer
        ouvre une fenêtre : il doit tourner là où il y a un écran. Deux cas, et
        c'est l'environnement qui tranche, pas une question de plus :
          - un affichage est là (poste de travail, ou « ssh -X ») : on installe
            virt-viewer au besoin et on le lance, détaché ;
          - aucun affichage : on donne la commande à lancer sur le poste, sous
            la forme qemu+ssh, avec l'adresse par laquelle cette machine a été
            jointe.
        """
        domain = name.rsplit("+", 1)[-1] if src == "ssh_config" else name
        display = os.environ.get("DISPLAY") or os.environ.get(
            "WAYLAND_DISPLAY"
        )
        if src == "ssh_config":
            # L'hyperviseur est le ProxyJump déclaré : c'est lui qui fait
            # tourner le QEMU de cette VM, pas la VM elle-même.
            jump = self._ssh_proxyjump(name)
            if not jump:
                print(
                    f"\n  ⚠ {t('No ProxyJump for this host in ~/.ssh/config.')}"
                )
                print(f"  {t('Cannot tell which machine runs its QEMU.')}")
                return
            uri = f"qemu+ssh://{jump}/system"
        else:
            uri = "qemu:///system"

        if display:
            if not self._qemu_ensure_virt_viewer():
                return
            cmd = ["virt-viewer", "-c", uri, domain]
            print(f"\n  {t('Opening')} : {' '.join(cmd)}")
            try:
                with open("/tmp/erplibre-virt-viewer.log", "ab") as log:
                    subprocess.Popen(
                        cmd,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
            except OSError as exc:
                print(f"  ⚠ {t('Could not start it:')} {exc}")
                return
            print(f"  {t('Window opening on your display')} ({display}).")
            print(f"  {t('Log:')} /tmp/erplibre-virt-viewer.log")
            return

        host, from_ssh = self._qemu_self_address()
        user = os.environ.get("USER", "user")
        print(f"\n  {t('No display here; run this on YOUR workstation:')}")
        print(
            f"\n    virt-viewer -c qemu+ssh://{user}@{host}/system {domain}\n"
        )
        if not from_ssh:
            print(f"  ⚠ {t('Not in an SSH session: check the host address.')}")
        print(f"  {t('A ~/.ssh/config alias works there too.')}")
        print(f"  {t('It builds its own tunnel; no ssh -L to keep open.')}")
        print(
            f"  {t('Missing? Install virt-viewer:')} apt / dnf / pacman"
            " / zypper"
        )

    def _qemu_console_tunnel(self, name, src):
        """Tunnel vers l'ÉCRAN QEMU d'une VM, pas vers un serveur de l'invité.

        Les deux autres choix du menu supposent un service DANS l'invité —
        xrdp, TigerVNC — donc une session de bureau déjà ouverte et un mot de
        passe posé. La console de l'hyperviseur, elle, existe dès l'amorçage et
        ne demande rien à l'invité : c'est ce que montre virt-manager.

        Le port n'est pas devinable : libvirt l'attribue au démarrage. On le
        lit donc, et l'absence de port est un diagnostic à part entière — avec
        « listen=none » QEMU n'ouvre AUCUN socket, et aucun tunnel n'y peut
        rien tant que le domaine n'est pas redéfini.
        """
        if src != "ssh_config":
            jump, domain = "", name
        else:
            # L'écran VNC appartient à QEMU, donc à l'HYPERVISEUR — pas à
            # l'invité. Tunneler vers la VM elle-même ne trouve rien : le
            # socket n'existe pas de ce côté. Vécu, et c'est aussi ce qui
            # rendait le premier jet de ce menu inutile hors machine locale.
            #
            # L'hyperviseur est le ProxyJump déclaré dans ssh_config, lu par
            # « ssh -G » : c'est la seule lecture qui couvre toutes les formes
            # d'écriture (Host, Match, wildcards, includes). Le nom composé
            # « saut+vm » n'est qu'un libellé, il ne fait pas autorité.
            jump = self._ssh_proxyjump(name)
            domain = name.rsplit("+", 1)[-1]
            if not jump:
                print(f"\n  ⚠ {t('No ProxyJump for this host in ~/.ssh/config.')}")
                print(f"  {t('Cannot tell which machine runs its QEMU.')}")
                return
        port = self._qemu_vnc_port(domain, jump)
        # Les commandes de réparation se lancent SUR l'hyperviseur : le préfixe
        # évite de les copier sur la mauvaise machine, l'erreur naturelle ici.
        pre = f"ssh {jump} " if jump else ""
        if not port:
            print(f"\n  ⚠ {t('This VM exposes no VNC port.')}")
            print(f"  {t('Its display is likely spice with listen=none:')}")
            print(f"    {pre}sudo virsh dumpxml {domain} | grep -A2 '<graphics'")
            print(f"  {t('To open it on the loopback (VM restart required):')}")
            print(f"    {pre}sudo virsh destroy {domain}")
            print(f"    {pre}sudo virsh edit {domain}   # <graphics type='vnc'"
                  " port='-1' autoport='yes' listen='127.0.0.1'/>")
            print(f"    {pre}sudo virsh start {domain}")
            print(f"\n  {t('New VMs get this by default; see deploy_qemu.')}")
            return
        if jump:
            target = jump
        else:
            host, from_ssh = self._qemu_self_address()
            user = os.environ.get("USER", "user")
            if not from_ssh:
                print(f"  ⚠ {t('Not in an SSH session: check the host address.')}")
            target = f"{user}@{host}"
        print(f"\n  {t('Run this on YOUR workstation:')}")
        print(f"\n    ssh -N -L {port}:127.0.0.1:{port} {target}\n")
        if jump:
            print(f"  {t('Target is the hypervisor')} ({jump}), "
                  f"{t('not the VM: the socket is QEMU-side.')}")
        print(f"  {t('then point your VNC client at')} localhost:{port}")
        print(f"  {t('The tunnel stays open as long as that ssh runs.')}")

    @staticmethod
    def _ssh_proxyjump(host):
        """ProxyJump effectif d'un hôte, tel que ssh le calcule lui-même.

        « ssh -G » rend la configuration RÉSOLUE : Match, wildcards et Include
        compris. Relire ~/.ssh/config à la main raterait tout cela.
        """
        try:
            res = subprocess.run(
                ["ssh", "-G", host], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        for line in res.stdout.splitlines():
            if line.startswith("proxyjump "):
                value = line.split(None, 1)[1].strip()
                return "" if value.lower() == "none" else value
        return ""

    @staticmethod
    def _qemu_vnc_port(domain, jump=""):
        """Port VNC réel d'un domaine, localement ou sur un hyperviseur distant.

        Il ne se devine pas : libvirt l'attribue au démarrage. « virsh
        vncdisplay » rend « 127.0.0.1:0 », où le suffixe est le NUMÉRO d'écran
        — 0 vaut 5900, 1 vaut 5901.

        Sans sudo d'abord : l'appartenance au groupe libvirt suffit souvent, et
        « sudo -n » distant échouerait sur l'absence de TTY. On ne retombe sur
        « sudo -n » que si le premier essai n'a rien donné.
        """
        base = ["virsh", "--connect", "qemu:///system", "vncdisplay", domain]
        for argv in (base, ["sudo", "-n"] + base):
            cmd = (["ssh", "-o", "BatchMode=yes", jump] + argv) if jump else argv
            try:
                res = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=25
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if res.returncode != 0:
                continue
            disp = res.stdout.strip().rsplit(":", 1)
            if len(disp) == 2 and disp[1].isdigit():
                return 5900 + int(disp[1])
        return 0

    def _qemu_ssh_config_menu(self):
        """Écrit les entrées ~/.ssh/config du parc QEMU.

        Un seul flux : les deux anciennes entrées (« VM locales » et
        « imbriquées, récursif ») écrivaient la même chose et ne différaient
        que par la profondeur — c'est donc une question, pas un menu."""
        print(f"🔑 {t('SSH configuration for QEMU VMs')}")
        roots = self._qemu_ssh_pick_roots()
        if not roots:
            return
        raw = input(
            f"{t('Depth (1 = these machines only, default:')}"
            f" {self._QEMU_SSH_DEPTH}): "
        ).strip()
        try:
            max_depth = max(1, int(raw)) if raw else self._QEMU_SSH_DEPTH
        except ValueError:
            max_depth = self._QEMU_SSH_DEPTH
        # Aucune question sur la clé ici : tant que rien n'a échoué, elle
        # serait prématurée. Elle est posée à la première identité refusée.
        self._qemu_ssh_walk(roots, max_depth)

    def _qemu_pick_domains(self):
        """Fait choisir des VM parmi celles définies. Vide = toutes."""
        names = self._qemu_list_domains()
        if not names:
            print(t("No VM found."))
            return []
        for i, name in enumerate(names, 1):
            print(f"  [{i}] {name}")
        raw = input(
            t("Which VMs? (numbers, comma-separated; blank = all): ")
        ).strip()
        if not raw:
            return names
        chosen = self._parse_index_selection(raw, names)
        return chosen or names

    def _ssh_ensure_key(self):
        """Chemin de la clé PUBLIQUE, générée si aucune n'existe.

        Sans clé, ssh-copy-id n'a rien à déployer. On en crée une ed25519 sans
        passphrase — le même choix que `deploy_qemu.ensure_ssh_key`, pour que
        les VM créées et celles adoptées ici partagent la même clé."""
        existing = self._qemu_default_ssh_key()
        if existing:
            return existing
        path = os.path.expanduser("~/.ssh/id_ed25519")
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        print(f"🔑 {t('Generating an ed25519 SSH key')}: {path}")
        try:
            res = subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", path],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  ⚠ {t('Cannot generate the key')}: {exc}")
            return ""
        if res.returncode != 0:
            print(f"  ⚠ {t('Cannot generate the key')}: {res.stderr.strip()}")
            return ""
        return f"{path}.pub"

    @staticmethod
    def _ssh_key_accepted(alias):
        """Vrai si la connexion par CLÉ passe déjà (aucun mot de passe).

        `PasswordAuthentication=no` est le point clé : sans lui, ssh
        basculerait sur le mot de passe et on croirait la clé installée."""
        try:
            res = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "ConnectTimeout=10",
                    alias,
                    "true",
                ],
                capture_output=True,
                timeout=45,
            )
            return res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _ssh_deploy_keys(self, aliases):
        """Déploie la clé publique sur les hôtes qui ne l'ont pas encore.

        ssh-copy-id passe par ssh, donc par ~/.ssh/config : le ProxyJump d'une
        VM imbriquée s'applique tout seul. Le mot de passe est demandé
        directement dans le terminal (pas de capture de la sortie), sinon
        l'invite serait invisible."""
        if not aliases:
            return
        pub = self._ssh_ensure_key()
        if not pub:
            return
        print(
            f"\n🔑 {t('Deploying the key on')} {len(aliases)} "
            f"{self._plural(t('host'), len(aliases))} ({pub})"
        )
        n_ok = n_skip = n_fail = 0
        for alias in aliases:
            if self._ssh_key_accepted(alias):
                print(f"  ·  {alias}: {t('key already accepted')}")
                n_skip += 1
                continue
            print(f"  ⤴  ssh-copy-id {alias}")
            try:
                res = subprocess.run(
                    ["ssh-copy-id", "-i", pub, alias], timeout=180
                )
                ok = res.returncode == 0
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"     ⚠ {exc}")
                ok = False
            if ok:
                n_ok += 1
            else:
                n_fail += 1
        print(
            f"  {n_ok} {t('deployed')} · {n_skip} {t('already there')} · "
            f"{n_fail} {t('failed')}"
        )

    # Connexions de virt-manager : stockées dans GSettings, pas dans un
    # fichier. Le schéma est le même depuis des années (virt-manager 5.1
    # inclus) ; on LIT d'abord, et on n'écrit que si la lecture a marché.
    _VIRT_MANAGER_SCHEMA = "org.virt-manager.virt-manager.connections"
    # Schéma RELOCATABLE d'UNE connexion : il porte son nom affiché.
    _VIRT_MANAGER_CONN_SCHEMA = "org.virt-manager.virt-manager.connection"

    @staticmethod
    def _virt_manager_conn_path(uri):
        """Chemin dconf des réglages d'une connexion.

        virt-manager ne fait aucun échappement : il retire simplement TOUS
        les « / » de l'URI et s'en sert comme segment unique
        (virtManager/config.py, _make_perconn_key). Le « :», le « @» et le
        « + » restent donc tels quels."""
        return f"/org/virt-manager/virt-manager/conns/{uri.replace('/', '')}/"

    def _virt_manager_set_label(self, uri, label):
        """Fixe le nom affiché d'une connexion. Sans lui, virt-manager
        fabrique un libellé à partir de l'URI, où l'imbrication se lit mal."""
        target = (
            f"{self._VIRT_MANAGER_CONN_SCHEMA}:"
            f"{self._virt_manager_conn_path(uri)}"
        )
        try:
            res = subprocess.run(
                ["gsettings", "set", target, "pretty-name", label],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return res.returncode == 0

    def _virt_manager_uris(self):
        """URI déjà connues de virt-manager, ou None s'il n'est pas là."""
        if not shutil.which("virt-manager") or not shutil.which("gsettings"):
            return None
        try:
            res = subprocess.run(
                ["gsettings", "get", self._VIRT_MANAGER_SCHEMA, "uris"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if res.returncode != 0:
            return None
        # GSettings rend du littéral Python : ['a', 'b'] ou @as [].
        raw = res.stdout.strip()
        if raw.startswith("@as "):
            raw = raw[4:].strip()
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return None
        return [str(item) for item in value] if isinstance(value, list) else []

    def _virt_manager_add(self, uris):
        """Ajoute les URI manquantes à virt-manager. Renvoie le nb ajouté."""
        current = self._virt_manager_uris()
        if current is None:
            return 0
        missing = [uri for uri in uris if uri not in current]
        if not missing:
            print(f"  ·  {t('virt-manager: every connection already there')}")
            return 0
        merged = current + missing
        literal = "[" + ", ".join(f"'{uri}'" for uri in merged) + "]"
        try:
            res = subprocess.run(
                [
                    "gsettings",
                    "set",
                    self._VIRT_MANAGER_SCHEMA,
                    "uris",
                    literal,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  ⚠ virt-manager: {exc}")
            return 0
        if res.returncode != 0:
            print(f"  ⚠ virt-manager: {res.stderr.strip()}")
            return 0
        for uri in missing:
            print(f"  ✅ virt-manager: {uri}")
        return len(missing)

    def _virt_manager_offer(self, hosts):
        """Propose d'ajouter à virt-manager les machines qui font tourner
        libvirt, pour piloter leurs VM depuis l'interface graphique locale.

        On passe par l'ALIAS SSH et non par l'IP : le transport qemu+ssh
        utilise le binaire ssh, donc ~/.ssh/config — l'alias porte déjà
        l'adresse ET le ProxyJump, ce qu'une IP brute ne saurait pas faire
        pour une VM imbriquée. `hosts` = [(alias_chaîné, compte)], de sorte
        que l'imbrication se lise aussi dans l'interface graphique et que le
        compte soit celui de ~/.ssh/config, pas un défaut supposé."""
        if self._virt_manager_uris() is None:
            return
        labels = {
            f"qemu+ssh://{user or self.QEMU_VM_USER}@{alias}/system": alias
            for alias, user in hosts
        }
        uris = ["qemu:///system"] + list(labels)
        print(f"\n🖥  {t('virt-manager detected')}")
        for uri in uris:
            print(f"     {uri}")
        if not self._is_yes_default_yes(
            input(t("Add the missing connections to virt-manager? (Y/n): "))
        ):
            return
        # Le nom affiché est posé AVANT l'ajout à la liste : virt-manager le
        # lit au moment d'afficher la connexion, pas à l'inscription.
        for uri, label in labels.items():
            self._virt_manager_set_label(uri, label)
        added = self._virt_manager_add(uris)
        if added:
            # Le NOM est relu à chaud (virt-manager écoute /pretty-name),
            # mais la liste des connexions est lue au démarrage : une
            # nouvelle entrée n'apparaît qu'au prochain lancement.
            note = t("Restart virt-manager to see the new connections")
            print(f"  ℹ️  {note} ({t('the names apply live')})")

    # Signatures d'un refus d'AUTHENTIFICATION dans la sortie de ssh, par
    # opposition à un hôte éteint ou introuvable. C'est la distinction qui
    # décide s'il vaut la peine de parler de clé SSH.
    _SSH_AUTH_ERRORS = (
        "permission denied",
        "too many authentication failures",
        "no such identity",
        "host key verification failed",
        "publickey",
    )

    @classmethod
    def _ssh_error_kind(cls, stderr):
        """« auth » si ssh a refusé l'identité, « net » sinon.

        Un hôte éteint et une clé absente produisent tous deux « injoignable »
        alors qu'ils n'appellent pas du tout la même réponse."""
        text = (stderr or "").lower()
        if any(marker in text for marker in cls._SSH_AUTH_ERRORS):
            return "auth"
        return "net"

    def _qemu_ssh_retry_with_key(self, alias, message):
        """ssh a refusé l'identité : proposer la clé, puis resonder une fois.

        Posée ICI et pas au début : tant que rien n'échoue, la question est
        prématurée — et si l'accès passe déjà par une clé d'agent ou un autre
        mécanisme, elle n'aurait jamais lieu d'être."""
        print(f"\n  🔒 {alias}: {t('SSH refused the identity.')}")
        print(f"     {message}")
        pub = self._qemu_default_ssh_key()
        if pub:
            print(f"     {t('Existing key:')} {pub}")
            question = t("Deploy it on this host (ssh-copy-id)? (Y/n): ")
        else:
            print(f"     {t('No SSH key in ~/.ssh.')}")
            question = t("Create one and deploy it? (Y/n): ")
        if not self._is_yes_default_yes(input(f"     {question}")):
            return "auth", message
        if not self._ssh_ensure_key():
            return "auth", message
        self._ssh_deploy_keys([alias])
        return self._qemu_ssh_probe_remote(alias)

    def _qemu_ssh_probe_remote(self, alias):
        """Sonde `alias`. Renvoie (statut, données) :

            ("ok", [(nom, ip)])   libvirt répond, voici ses VM
            ("nolibvirt", [])     joignable, mais pas de QEMU
            ("auth", message)     ssh a refusé l'identité
            ("net", message)      injoignable (éteint, DNS, port fermé…)

        Passe par « ssh <alias> », donc par le bloc ~/.ssh/config qu'on vient
        d'écrire : le ProxyJump du parent s'applique tout seul et la même
        sonde marche à n'importe quelle profondeur.

        « libvirt présent » et « a des VM » sont deux choses distinctes : une
        machine avec QEMU mais sans VM mérite quand même sa connexion
        virt-manager, une machine sans QEMU n'en veut aucune."""
        cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            alias,
            self._QEMU_SSH_PROBE,
        ]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=90
            )
        except subprocess.TimeoutExpired:
            return "net", t("timed out")
        except (OSError, subprocess.SubprocessError) as exc:
            return "net", str(exc)
        if res.returncode != 0:
            detail = (res.stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"exit {res.returncode}"
            return self._ssh_error_kind(res.stderr), message
        libvirt = "no"
        found = []
        for line in res.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) != 2 or not parts[0]:
                continue
            if parts[0] == "LIBVIRT":
                libvirt = parts[1].strip()
                continue
            found.append((parts[0], parts[1].strip()))
        if libvirt == "yes":
            return "ok", found
        # « denied » : virsh est installé mais refuse de répondre — sudo
        # interactif, ou utilisateur hors du groupe libvirt. Le confondre avec
        # « pas de QEMU » envoyait chercher un problème qui n'existe pas.
        return ("denied" if libvirt == "denied" else "nolibvirt"), found

    def _qemu_ssh_walk(self, roots, max_depth):
        """Descend le parc depuis `roots` et écrit un ProxyJump par niveau.

        Une VM du profil « Déploiement » héberge elle-même des VM : celles-ci
        n'ont pas d'IP joignable depuis l'hôte, seulement depuis leur parent.
        ProxyJump enchaîne les sauts, et la chaîne se construit d'elle-même
        puisque le parent est déjà dans ~/.ssh/config quand on écrit l'enfant.

        Une racine sans IP est un hôte DÉJÀ décrit dans ~/.ssh/config : son
        adresse y est, on ne la réécrit pas, on part simplement de lui.
        """
        # Clé existante s'il y en a une : elle va dans IdentityFile. Si une
        # clé est créée plus tard, en réaction à un refus, les entrées
        # suivantes la reprendront.
        identity = self._ssh_private_key(self._qemu_default_ssh_key())

        entries = []  # un enregistrement par machine écrite
        taken = set()  # tous les noms d'hôte déjà attribués
        chain_of = {}  # alias -> nom chaîné « parent+enfant »
        user_of = {}  # alias -> compte de connexion
        hosts_libvirt = []  # machines qui font tourner QEMU
        frontier = []
        for root in roots:
            alias, ip = root["alias"], root.get("ip")
            # Le compte vient de ~/.ssh/config quand il y est déclaré : un
            # hôte adopté n'est pas forcément une VM ERPLibre.
            user_of[alias] = root.get("user") or self.QEMU_VM_USER
            if ip:
                self._write_ssh_config_entry(
                    alias, user_of[alias], ip, identity_file=identity
                )
                entries.append(
                    {
                        "names": [alias],
                        "ip": ip,
                        "parent": None,
                        "user": user_of[alias],
                    }
                )
            taken.add(alias)
            chain_of[alias] = alias
            frontier.append(alias)

        # `max_depth` compte les NIVEAUX de machines, racines comprises : une
        # profondeur de 1 s'arrête donc ici, sans rien sonder.
        for depth in range(1, max_depth):
            if not frontier:
                break
            print(
                f"\n🔎 {t('Level')} {depth + 1} — "
                f"{len(frontier)} {t('machines to probe')}"
            )
            next_frontier = []
            for parent in frontier:
                status, found = self._qemu_ssh_probe_remote(parent)
                if status == "auth":
                    # C'EST ici qu'une clé manquante se manifeste, pas avant :
                    # on ne parle d'identité qu'une fois l'identité refusée.
                    status, found = self._qemu_ssh_retry_with_key(
                        parent, found
                    )
                    # Une clé a pu naître de cet échange : les entrées
                    # écrites ensuite doivent la nommer.
                    identity = (
                        self._ssh_private_key(self._qemu_default_ssh_key())
                        or identity
                    )
                if status in ("auth", "net"):
                    label = (
                        t("access refused")
                        if status == "auth"
                        else t("unreachable")
                    )
                    print(f"  ⏭  {parent}: {label} — {found}")
                    continue
                if status == "denied":
                    # virsh est là mais ne répond pas : c'est un DROIT qui
                    # manque, pas un logiciel. Le dire, et donner le geste.
                    print(
                        f"  🔒 {parent}: "
                        f"{t('virsh present but not accessible')}"
                    )
                    print(
                        f"       {t('Add the user to the libvirt group there:')}"
                    )
                    continue
                if status != "ok":
                    print(f"  ·  {parent}: {t('no QEMU/libvirt here')}")
                    continue
                # Une machine avec QEMU vaut sa connexion virt-manager, même
                # sans VM : c'est là qu'on pourra en créer.
                hosts_libvirt.append(parent)
                if not found:
                    print(f"  ·  {parent}: {t('QEMU present, no VM')}")
                    continue
                for child, ip in found:
                    if not ip:
                        print(f"  ⏭  {parent} › {child}: {t('no IP')}")
                        continue
                    # UN SEUL nom, le nom CHAÎNÉ : il dit où vit la VM et ne
                    # peut heurter aucune autre machine. Y ajouter le nom
                    # court ne ferait que répéter la fin de la chaîne.
                    chain = f"{chain_of[parent]}+{child}"
                    if chain in taken:
                        continue  # déjà vu (cycle)
                    # L'invitée hérite du compte de son parent : elle a été
                    # créée par lui, avec la même convention.
                    user_of[chain] = user_of[parent]
                    self._write_ssh_config_entry(
                        chain,
                        user_of[chain],
                        ip,
                        proxy_jump=parent,
                        identity_file=identity,
                    )
                    entries.append(
                        {
                            "names": [chain],
                            "ip": ip,
                            "parent": parent,
                            "user": user_of[chain],
                        }
                    )
                    taken.add(chain)
                    chain_of[chain] = chain
                    next_frontier.append(chain)
            frontier = next_frontier

        print(f"\n── {t('SSH hosts written')} ──")
        for item in entries:
            via = f"  ({t('via')} {item['parent']})" if item["parent"] else ""
            print(
                f"  ssh {' '.join(item['names']):<40}"
                f" {item['user']}@{item['ip']}{via}"
            )

        # Les machines qui hébergent QEMU sont celles qui valent d'être
        # ajoutées à virt-manager : c'est de là qu'on pilote leurs invitées.
        # On y présente le nom CHAÎNÉ, pour que l'imbrication se lise aussi
        # dans l'interface graphique et pas seulement dans ~/.ssh/config.
        self._virt_manager_offer(
            [
                (chain_of.get(alias, alias), user_of.get(alias, ""))
                for alias in hosts_libvirt
            ]
        )

    def _qemu_stats(self):
        """Statistiques d'utilisation de QEMU, et remise à zéro.

        Tout vient de l'historique tenu par le moniteur d'installation
        (.venv.erplibre/qemu_install_stats.json) et de l'état libvirt courant.
        """
        # Cet écran ne lit que des fichiers : il n'a pas besoin de Textual,
        # contrairement au dashboard du même module. Un échec d'import est
        # donc un vrai problème de module, pas une dépendance manquante.
        try:
            from script.todo import qemu_install_monitor as mon
        except ImportError as exc:
            print(f"{t('Command failed: ')}{exc}")
            return

        while True:
            summary = mon.stats_summary()
            print(f"\n📊 {t('QEMU statistics')}")
            if not summary:
                print(f"   {t('No installation recorded yet.')}")
            else:
                rate = 100 * summary["ok"] // max(summary["total"], 1)
                print(f"\n── {t('Installations')} ──")
                print(
                    f"   {t('Total'):<18}: {summary['total']}"
                    f"  ({summary['ok']} {t('succeeded')},"
                    f" {summary['failed']} {t('failed')} — {rate} %)"
                )
                if summary["first_ts"]:
                    days = max(
                        1,
                        (summary["last_ts"] - summary["first_ts"]) // 86400,
                    )
                    print(
                        f"   {t('Period'):<18}:"
                        f" {self._qemu_stamp(summary['first_ts'])}"
                        f" → {self._qemu_stamp(summary['last_ts'])}"
                        f"  ({days} {t('days')})"
                    )
                print(
                    f"   {t('Median duration'):<18}:"
                    f" {mon._fmt_secs(summary['median'])}"
                    f"   ({t('min')} {mon._fmt_secs(summary['min'])} ·"
                    f" {t('max')} {mon._fmt_secs(summary['max'])})"
                )
                print(
                    f"   {t('Cumulated time'):<18}:"
                    f" {mon._fmt_secs(summary['total_secs'])}"
                )
                for field, title in (
                    ("distro", t("By distribution")),
                    ("version", t("By version")),
                    ("arch", t("By architecture")),
                ):
                    rows = mon.stats_by(field)
                    if not rows:
                        continue
                    print(f"\n── {title} ──")
                    for key, count, avg, failed in rows[:8]:
                        # Un groupe sans aucun succès n'a pas de moyenne : « — »
                        # plutôt qu'un « ~0s » trompeur.
                        moy = f"~{mon._fmt_secs(avg)}" if count else "—"
                        fail = (
                            f"   ⚠ {failed} {self._plural(t('failure'), failed)}"
                            if failed
                            else ""
                        )
                        print(f"   {key:<22} {count:>3} ×   {moy:<8}{fail}")

            self._qemu_stats_vms(mon)
            print(f"\n   [r] {t('Reset the statistics')}")
            print(f"   [0] {t('Back')}")
            answer = input(f"💬 {t('Your choice')} : ").strip().lower()
            if answer in ("", "0"):
                return
            if answer == "r":
                if not summary:
                    print(f"   {t('Nothing to reset.')}")
                    continue
                confirm = input(
                    f"   {t('Erase')} {summary['total']}"
                    f" {t('recorded runs')}? (y/N): "
                ).strip()
                if self._is_yes(confirm):
                    count = mon.reset_stats()
                    print(f"   ✅ {count} {t('runs erased')}.")
                else:
                    print(f"   {t('Cancelled.')}")

    @staticmethod
    def _qemu_stamp(ts):
        """Horodatage court « 2026-08-01 »."""
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return "?"

    def _qemu_stats_vms(self, mon):
        """Machines virtuelles actuelles : nombre, états, place disque."""
        try:
            states = mon.virsh_domstates()
        except Exception:
            return
        if not states:
            return
        running = sum(1 for s in states.values() if s == "running")
        total_bytes = 0
        counted = 0
        for name in states:
            try:
                # vm_disk_path attend un dict ; le chemin par défaut de libvirt
                # se déduit du seul nom.
                size = mon.disk_actual_size(mon.vm_disk_path({"name": name}))
            except Exception:
                size = None
            if size:
                total_bytes += size
                counted += 1
        print(f"\n── {t('Virtual machines')} ──")
        print(
            f"   {t('Defined'):<18}: {len(states)}"
            f"  ({running} {t('running')},"
            f" {len(states) - running} {t('stopped')})"
        )
        if counted:
            print(
                f"   {t('Disk used'):<18}:"
                f" {mon._fmt_size(total_bytes)}"
                f"  ({counted} {self._plural(t('image'), counted)})"
            )

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
        # Liste NUMÉROTÉE, comme l'écran de suppression : les noms de VM sont
        # longs et se ressemblent, les retaper invite à la faute de frappe sur
        # une commande qui change l'état d'une machine.
        print(f"\n{t('Available VMs:')}")
        for i, n in enumerate(names, 1):
            print(f"  [{i}] {n}")
        print(f"  [all] {t('select all')}")
        raw = input(t("Selection (numbers, or 'all'): ")).strip()
        if not raw:
            print(t("Nothing selected."))
            return
        if raw.lower() in ("all", "*"):
            resolved = list(names)
        else:
            resolved = self._parse_index_selection(raw.lower(), names)
            # Le parseur ignore en silence ce qu'il ne reconnaît pas. Sur une
            # sélection qui va démarrer ou éteindre des VM, un numéro hors
            # liste doit être dit, pas escamoté.
            unknown = [
                tok
                for tok in re.split(r"[\s,]+", raw.strip())
                if tok and tok not in names and not self._is_index(tok, names)
            ]
            if unknown:
                print(f"{t('Unknown VM(s):')} {', '.join(unknown)}")
                return
        if not resolved:
            print(t("Nothing selected."))
            return
        # Choix de l'état cible : ouvrir (démarrer) ou fermer (éteindre).
        print(f"\n{t('Target state:')}")
        print(f"  [1] {t('Open (start)')}")
        print(f"  [2] {t('Close (shut down)')}")
        print(f"  [3] {t('Adjust hardware only (vCPU, RAM, 3D)')}")
        st = input(t("Choice: ")).strip()
        if st == "1":
            action, verb = "start", t("start")
        elif st == "2":
            action, verb = "shutdown", t("shut down")
        elif st == "3":
            self._qemu_adjust_hardware(resolved)
            return
        else:
            print(t("Cancelled."))
            return
        # Le matériel d'une VM ne se règle QUE pendant qu'elle est éteinte :
        # démarrer est donc le dernier moment pour le faire, et le seul où la
        # question tombe juste.
        if action == "start" and self._is_yes(
            input(f"\n{t('Adjust hardware before starting? (y/N): ')}")
        ):
            self._qemu_adjust_hardware(resolved)
        # DOUBLE validation avant d'appliquer.
        summary = f"{verb} -> {', '.join(resolved)}"
        if not self._is_yes(input(f"{t('Apply:')} {summary} ? (o/N) : ")):
            print(t("Cancelled."))
            return
        if not self._is_yes(input(t("Confirm for real? (y/N): "))):
            print(t("Cancelled."))
            return
        for real in resolved:
            cmd = f"sudo virsh {action} {shlex.quote(real)}"
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    @staticmethod
    def _qemu_dumpxml(name):
        """XML PERSISTANT du domaine, ou '' — source de son état matériel.

        « --inactive » n'est pas décoratif : sur une VM allumée, « dumpxml »
        rend la vue VIVANTE, décorée de ce que libvirt a alloué au démarrage
        (portid du réseau, vnetN, alias). C'est la définition persistante que
        virt-xml modifie, et c'est donc elle qu'il faut lire.
        """
        try:
            res = subprocess.run(
                ["sudo", "virsh", "dumpxml", "--inactive", name],
                capture_output=True,
                text=True,
                timeout=20,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return res.stdout if res.returncode == 0 else ""

    @staticmethod
    def _qemu_autostart(name):
        """Démarrage automatique activé ? (absent du XML : virsh seul le sait)"""
        try:
            res = subprocess.run(
                ["sudo", "virsh", "dominfo", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        for line in res.stdout.splitlines():
            if line.startswith("Autostart:"):
                return line.split(":", 1)[1].strip() == "enable"
        return False

    def _qemu_ask_bool(self, prompt, default):
        """Question fermée dont le DÉFAUT est l'état actuel de la VM.

        Une réponse vide — ou incompréhensible — laisse la VM telle quelle :
        sur un formulaire de matériel, le silence ne doit rien modifier.
        """
        ans = input(prompt).strip()
        if self._is_yes(ans):
            return True
        if self._is_no(ans):
            return False
        return default

    def _qemu_host_gpu_node(self):
        """Nœud de rendu de l'hôte, vu par deploy_qemu (source unique), ou ''."""
        try:
            return self._qemu_import_module().host_gpu_node()
        except (OSError, AttributeError, ImportError):
            return ""

    def _qemu_net_choices(self):
        """Réseaux proposables : réseaux libvirt, puis ponts de l'hôte.

        Les ponts appartenant à un réseau libvirt (virbr0 pour « default »)
        sont écartés : les proposer offrirait DEUX fois le même chemin, dont
        un qui contourne la gestion du réseau par libvirt.
        """
        tokens = []
        nets = self._qemu_cmd_lines(
            ["sudo", "virsh", "net-list", "--all", "--name"]
        )
        owned = set()
        for net in nets:
            tokens.append(f"network:{net}")
            for line in self._qemu_cmd_lines(
                ["sudo", "virsh", "net-info", net]
            ):
                if line.startswith("Bridge:"):
                    owned.add(line.split(":", 1)[1].strip())
        for line in self._qemu_cmd_lines(
            ["ip", "-o", "link", "show", "type", "bridge"]
        ):
            # « 3: br0: <BROADCAST,...» -> br0
            parts = line.split(":")
            bridge = parts[1].strip() if len(parts) > 1 else ""
            if bridge and bridge not in owned:
                tokens.append(f"bridge:{bridge}")
        return tokens

    @staticmethod
    def _qemu_cmd_lines(cmd):
        """Lignes non vides d'une commande, ou [] si elle échoue."""
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0:
            return []
        return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]

    def _qemu_adjust_hardware(self, names):
        """Règle vCPU, RAM, 3D et démarrage automatique de VM ÉTEINTES.

        Les VM allumées sont écartées, en le disant : virt-xml y écrirait une
        définition qui ne prendrait effet qu'au prochain démarrage — un
        réglage qui paraît appliqué et ne l'est pas.
        """
        from script.todo import qemu_hardware as hw

        off, busy = [], []
        for name in names:
            state = self._qemu_domstate(name)
            (off if state == "shut off" else busy).append(name)
        if busy:
            print(
                f"\n  ⚠ {t('Not shut off, hardware left untouched:')}"
                f" {', '.join(busy)}"
            )
        if not off:
            return
        node = self._qemu_host_gpu_node()
        gpu_txt = node or t("none (software rendering)")
        print(f"\n{t('Host GPU:')} {gpu_txt}")
        rows = [
            r
            for r in (
                hw.hw_state(self._qemu_dumpxml(n), self._qemu_autostart(n))
                for n in off
            )
            if r.get("name")
        ]
        if not rows:
            print(f"  ⚠ {t('Unreadable VM definition.')}")
            return
        for r in rows:
            print(f"  {r['name']:<30} {hw.hw_summary(r)}")
        nets = self._qemu_net_choices()
        want = self._qemu_hw_form(rows, node, nets)
        if want is None:
            print(t("Cancelled."))
            return
        if not want:
            want = self._qemu_hw_prompts(rows, node, nets)
        if not want:
            print(t("Cancelled."))
            return
        plan = []
        for r in rows:
            plan += hw.hw_plan(r, want.get(r["name"]) or {}, node)
        for entry in plan:
            if entry.get("skip"):
                print(f"  ⚠ {entry['what']} : {entry['skip']}")
        cmds = [e for e in plan if e.get("cmd")]
        if not cmds:
            print(f"\n{t('Nothing to change.')}")
            return
        print(f"\n{t('Changes:')}")
        for entry in cmds:
            print(f"  - {entry['what']}")
        if not self._is_yes(input(t("Apply these changes? (y/N): "))):
            print(t("Cancelled."))
            return
        for entry in cmds:
            cmd = "sudo " + " ".join(shlex.quote(c) for c in entry["cmd"])
            print(f"\n{t('Will execute:')} {cmd}")
            self.execute.exec_command_live(cmd, source_erplibre=False)

    def _qemu_hw_form(self, rows, node, nets=None):
        """Formulaire TUI d'ajustement. Renvoie l'intention par VM, {} pour
        retomber sur les invites en ligne (textual absent), None si annulé."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return {}
        try:
            from script.todo.qemu_hardware import run_hardware_form

            return run_hardware_form(rows, node, nets)
        except ImportError:
            return {}

    def _qemu_pick(self, title, values, current, labels=None):
        """Liste numérotée dont le DÉFAUT est la valeur actuelle.

        Rendre la valeur actuelle sur une réponse vide, et sur une réponse
        illisible : dans un formulaire de matériel, ne rien comprendre ne doit
        rien changer.
        """
        labels = labels or values
        print(f"{title} :")
        for i, (val, lab) in enumerate(zip(values, labels), 1):
            mark = " ←" if val == current else ""
            print(f"      [{i}] {lab}{mark}")
        ans = input("      " + t("Choice: ")).strip()
        if not ans.isdigit():
            return current
        idx = int(ans)
        return values[idx - 1] if 1 <= idx <= len(values) else current

    def _qemu_hw_prompts(self, rows, node, nets=None):
        """Même ajustement, en invites, quand Textual n'est pas disponible."""
        from script.todo import qemu_hardware as hw

        cpus = hw.cpu_choices(rows)
        reseaux = hw.net_choices(rows, nets)
        want = {}
        for r in rows:
            print(f"\n  {r['name']} — {hw.hw_summary(r)}")
            vcpus = input(f"    vCPU [{r.get('vcpus')}] : ")
            ram = input(f"    RAM [{hw.fmt_mib(r.get('mem_mib'))}] : ")
            reason = hw.gpu_allowed(r, node)
            if reason:
                print(f"    ⚠ {t('3D acceleration (host GPU)')} : {reason}")
                gpu = False
            else:
                gpu = self._qemu_ask_bool(
                    f"    {t('3D acceleration (host GPU)')} ? (o/N) : ",
                    bool(r.get("accel3d")),
                )
            auto = self._qemu_ask_bool(
                f"    {t('Autostart')} ? (o/N) : ", bool(r.get("autostart"))
            )
            cpu = self._qemu_pick(f"    {t('CPU mode')}", cpus, r.get("cpu"))
            heads = ""
            if r.get("video"):
                heads = input(f"    {t('Screens')} [{r.get('heads') or 1}] : ")
            net = r.get("net") or ""
            # Une seule possibilité : rien à demander. C'est le cas d'un hôte
            # sans pont, où le réseau libvirt est la seule voie.
            if len(reseaux) > 1:
                net = self._qemu_pick(
                    f"    {t('Network')}",
                    [tok for tok, _lab in reseaux],
                    net,
                    labels=[lab for _tok, lab in reseaux],
                )
            want[r["name"]] = hw.build_want(
                r, vcpus, ram, gpu, auto, cpu=cpu, heads=heads, net=net
            )
        return want

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

    @staticmethod
    def _fmt_uptime(secs):
        """Durée depuis le démarrage, en six caractères au plus.

        « _fmt_dur » s'arrête aux minutes — bon pour une installation, illisible
        pour une VM debout depuis trois jours. Ici la précision décroît avec la
        durée : personne ne lit les secondes d'un uptime de 19 heures."""
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h{(secs % 3600) // 60:02d}"
        days = secs // 86400
        # Au-delà de 99 jours, les heures ne rentrent plus dans la colonne — et
        # personne ne les lit sur une machine debout depuis un an.
        if days >= 100:
            return f"{days}j"
        return f"{days}j{(secs % 86400) // 3600:02d}h"

    @staticmethod
    def _qemu_domain_uptime(name):
        """Secondes depuis le démarrage du domaine, ou None.

        libvirt n'expose pas l'uptime d'un invité : ni dominfo, ni domstats, ni
        l'agent. Mais le processus QEMU du domaine est né avec lui, et son âge
        est donc exactement celui de la VM. « guest=<nom>, » est le motif que
        libvirt met dans sa ligne de commande — la virgule évite qu'un nom
        préfixe d'un autre matche à sa place."""
        try:
            res = subprocess.run(
                ["pgrep", "-f", f"guest={name},"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            pid = (res.stdout or "").split()[0]
            age = subprocess.run(
                ["ps", "-o", "etimes=", "-p", pid],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return int((age.stdout or "").strip())
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return None

    @staticmethod
    def _qemu_dommemstat(name):
        """(utilisée, totale) en KiO vues par l'INVITÉ, ou (0, 0).

        « available » est ce que l'invité voit, « usable » ce qu'il peut encore
        rendre : leur différence est son « used », à quelques mégaoctets près —
        calibré contre le « free » de deux VM (1186 contre 1216, 4831 contre
        4838). « unused » ne convient pas : il ignore le cache, et donnait
        10,8 Go d'« utilisé » sur une VM qui en occupait 1,2.

        La période de collecte est posée d'abord, et c'est indispensable : sans
        elle le ballon ne rafraîchit rien, et une VM qui occupait 4,8 Go en
        annonçait 490 Mo — vécu. « --live » ne touche pas le XML : le réglage
        disparaît au prochain démarrage du domaine."""
        try:
            subprocess.run(
                [
                    "sudo",
                    "virsh",
                    "dommemstat",
                    name,
                    "--period",
                    "5",
                    "--live",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
            res = subprocess.run(
                ["sudo", "virsh", "dommemstat", name],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return 0, 0
        stat = {}
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    stat[parts[0]] = int(parts[1])
                except ValueError:
                    continue
        total = stat.get("available", 0)
        usable = stat.get("usable", 0)
        if not total or not usable:
            return 0, total
        return max(0, total - usable), total

    def _qemu_list_vms_advanced(self):
        """Tableau détaillé par VM : état, vCPU, RAM allouée, disque (virtuel
        + réel), plus l'espace total disponible du stockage des images."""
        names = self._qemu_list_domains()
        if not names:
            print(f"\n{t('No VM found.')}")
            return
        g = 1 << 30
        # Largeurs serrées pour que la ligne tienne en 80 colonnes AVEC le nom
        # entier : c'est lui qui distingue les machines, et « erplibre-ubuntu-
        # 2604-gno » tronqué ne distingue plus rien.
        header = (
            f"\n{'VM':<26} {'État':<8} {'vCPU':>4} {'RAM':>10} "
            f"{'Disque':>7} {'Réel':>7} {'Uptime':>6}"
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
            # « RAM » dit désormais l'USAGE et non la seule allocation : sur un
            # hyperviseur, savoir qu'une VM de 32 Go n'en occupe que 4,7 décide
            # s'il reste de la place pour la suivante. Deux nombres dans une
            # colonne plutôt que deux colonnes — le tableau tient encore sur
            # une ligne de terminal.
            used_kib, _total_kib = self._qemu_dommemstat(name)
            # Le total sans décimale quand il est entier — une allocation
            # vaut 8, 12 ou 32 Go, jamais 32,0.
            alloc = f"{ram_g:.0f}" if ram_g == int(ram_g) else f"{ram_g:.1f}"
            ram = (
                f"{used_kib * 1024 / g:.1f}G/{alloc}G"
                if used_kib
                else f"-/{alloc}G"
            )
            # L'uptime vient de l'âge du processus QEMU : libvirt ne l'expose
            # nulle part, et ce processus est né avec le domaine.
            up = self._qemu_domain_uptime(name)
            print(
                f"{name:<26.26} {state:<8.8} {vcpus:>4} "
                f"{ram:>10} {virt / g:>6.1f}G {actual / g:>6.1f}G "
                f"{self._fmt_uptime(up) if up else '-':>6}"
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
        sel = input(t("Choice (number, blank = last): ")).strip()
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
        self._qemu_open_monitor(run["manifest"])

    def _qemu_open_monitor(self, manifest):
        """Ouvre le dashboard sur un manifeste, en installant Textual au
        besoin. Deux entrées y mènent — l'historique et la reprise proposée
        avant un déploiement — d'où une seule définition."""
        from script.todo import qemu_install_monitor as mon

        try:
            mon.run_monitor(manifest)
        except ImportError:
            from script.todo import textual_setup

            if textual_setup.ensure():
                mon.run_monitor(manifest)
        except Exception as exc:
            print(f"{t('Command failed: ')}{exc}")

    def _qemu_active_install(self):
        """Propose de reprendre le suivi quand une installation tourne encore.

        Les installs partent détachées (`setsid -f`) : fermer le terminal ne
        les arrête pas, mais faisait perdre la seule vue dessus, et la seule
        issue connue était de tout effacer pour recommencer.

        True si l'on ne doit PAS enchaîner sur un déploiement."""
        try:
            from script.todo import qemu_install_monitor as mon

            run = mon.active_run()
        except Exception:
            return False
        if not run:
            return False
        names = ", ".join(v.get("name", "?") for v in run["vms"])
        print(
            f"\n⏳ {t('An install is still running:')} {run['label']} — "
            f"{run['active']}/{run['total']} {t('VM(s) in progress')}"
        )
        print(f"     {names}")
        if run.get("idle") is not None:
            # Un silence prolongé trahit un run mort dont le marqueur de sortie
            # ne viendra jamais : l'utilisateur tranche mieux que nous.
            print(
                f"     {t('Last activity:')} {mon._fmt_secs(int(run['idle']))}"
            )
        print(f"\n  [1] {t('Reopen that monitoring')} *")
        print(f"  [2] {t('Deploy anyway (new run)')}")
        print(f"  [0] {t('Back')}")
        sel = input(t("Choice (number, blank = reopen): ")).strip()
        if sel == "2":
            return False
        if sel != "0":
            self._qemu_open_monitor(run["manifest"])
        return True

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
        print(
            f"{t('Waiting for the VM to shut down...')} "
            f"({t('timeout')}: {timeout} s)"
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._qemu_domstate(name) == "shut off":
                # Efface la ligne de compte à rebours puis confirme.
                print(f"\r{' ' * 40}\r✅ {name}: {t('VM is off.')}")
                return True
            remaining = int(deadline - time.time())
            print(
                f"\r  ⏳ {t('shutting down')}… "
                f"{remaining:>3d} s {t('remaining')}",
                end="",
                flush=True,
            )
            time.sleep(2)
        print()  # newline après le compte à rebours
        # Arrêt gracieux trop long : proposer un arrêt forcé.
        if self._is_yes(
            input(
                t(
                    "Graceful shutdown timed out. Force off (destroy)? "
                    "(y/N): "
                )
            )
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
        print(f"\n{t('New virtual size:')} {cur_gb:.1f} G -> {new_gb:.1f} G")
        # Avertissement (NON bloquant) : agrandir au-delà de ce que l'hôte
        # peut soutenir -> surallocation, l'hôte se remplira si la VM utilise
        # tout l'espace.
        if not shrink and max_safe_gb and new_gb > max_safe_gb:
            over = new_gb - max_safe_gb
            msg1 = t("Beyond host capacity by ~%.1f G — overcommit.") % over
            msg2 = (
                t(
                    "The qcow2 is thin: fine until the VM fills it, then the "
                    "host disk runs out. Max sustainable: ~%.1f G."
                )
                % max_safe_gb
            )
            print(f"⚠  {msg1}")
            print(f"   {msg2}")

        # 3) Application selon agrandir/réduire et l'état de la VM.
        was_shut_down = False  # la VM a-t-elle été éteinte pour l'occasion ?
        cmd = (
            None  # commande d'AGRANDISSEMENT (la réduction a son propre flux)
        )
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
                    input(
                        t(
                            "The VM must be off. Shut it down and retry? "
                            "(y/N): "
                        )
                    )
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
            if self._is_yes(input(t("Delete this backup now? (y/N): "))):
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
        "qemu-nbd",
        "e2fsck",
        "resize2fs",
        "sgdisk",
        "partprobe",
        "lsblk",
        "dumpe2fs",
        "blockdev",
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
            if (
                subprocess.run(
                    [
                        "sudo",
                        "cp",
                        "--reflink=auto",
                        "--sparse=always",
                        disk,
                        bak,
                    ]
                ).returncode
                != 0
            ):
                print(t("Backup failed; aborting."))
                return False
        else:
            print(
                f"⚠  {t('No backup: a failure could leave the disk broken.')}"
            )
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
            if (
                subprocess.run(
                    ["sudo", "resize2fs", part, f"{fs_target_mib}M"]
                ).returncode
                != 0
            ):
                print(t("resize2fs failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Fin de partition = début + taille RÉELLE du FS + 1 Mio, alignée.
            fs_bytes = self._qemu_fs_blocks(part) * bs
            new_end = start + int(
                math.ceil((fs_bytes + self._MiB) / self._SECT)
            )
            new_end = ((new_end + 2047) // 2048) * 2048 - 1  # align 2048
            if (new_end + 34) * self._SECT > target:
                print(t("Internal size check failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Réécrit la partition (mêmes type/UUID/nom -> PARTUUID préservé).
            print(f"{t('Shrinking the partition…')} ({part})")
            subprocess.run(["sudo", "sgdisk", "-d", n, dev], check=False)
            rc = subprocess.run(
                [
                    "sudo",
                    "sgdisk",
                    "-n",
                    f"{n}:{start}:{new_end}",
                    "-t",
                    f"{n}:{info['type']}",
                    "-u",
                    f"{n}:{info['uuid']}",
                    "-c",
                    f"{n}:{info['name']}",
                    dev,
                ]
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
            if (
                subprocess.run(
                    [
                        "sudo",
                        "qemu-img",
                        "resize",
                        "--shrink",
                        disk,
                        f"{new_gb:g}G",
                    ]
                ).returncode
                != 0
            ):
                print(t("Container shrink failed; reverting."))
                return self._qemu_shrink_revert(bak, disk, changed=True)
            # Répare la GPT de secours (fin du disque) + fsck final.
            dev = self._qemu_nbd_connect(disk)
            if dev:
                subprocess.run(["sudo", "sgdisk", "-e", dev], check=False)
                subprocess.run(
                    ["sudo", "partprobe", dev],
                    check=False,
                    capture_output=True,
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
                print(f"✅ {t('Disk safely shrunk. Backup kept at:')} {bak}")
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
                capture_output=True,
                text=True,
            ).returncode
            if rc != 0:
                continue
            base = f"nbd{i}"
            for _ in range(15):
                subprocess.run(
                    ["sudo", "partprobe", dev],
                    check=False,
                    capture_output=True,
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
                capture_output=True,
                text=True,
                timeout=30,
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
                best, best_sz, best_fs = (
                    d.get("NAME"),
                    size,
                    d.get("FSTYPE", ""),
                )
        if not best:
            return None, 0, ""
        part = f"/dev/{best}"
        try:
            start = int(open(f"/sys/class/block/{best}/start").read().strip())
        except OSError:
            start = 0
        if not best_fs:
            # FSTYPE pas encore en cache : sonder directement avec blkid.
            best_fs = subprocess.run(
                ["sudo", "blkid", "-o", "value", "-s", "TYPE", part],
                capture_output=True,
                text=True,
            ).stdout.strip()
        return part, start, best_fs

    @staticmethod
    def _qemu_part_number(dev, part):
        """Numéro de partition (ex. « 1 ») depuis /dev/nbd0p1."""
        return part[len(dev) :].lstrip("p")

    @staticmethod
    def _qemu_part_info(dev, n):
        """{type, uuid, name} d'une partition via « sgdisk -i »."""
        info = {"type": "", "uuid": "", "name": ""}
        res = subprocess.run(
            ["sudo", "sgdisk", "-i", n, dev],
            capture_output=True,
            text=True,
            env=TODO._qemu_c_env(),
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
            capture_output=True,
            text=True,
            env=TODO._qemu_c_env(),
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
            capture_output=True,
            text=True,
            env=TODO._qemu_c_env(),
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
            capture_output=True,
            text=True,
            env=TODO._qemu_c_env(),
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
        'dev=$(lsblk -no PKNAME "$root" | head -1); '
        "part=$(echo \"$root\" | grep -oE '[0-9]+$'); "
        "sudo growpart /dev/$dev $part || true; "
        "fstype=$(findmnt -no FSTYPE /); "
        'case "$fstype" in '
        'ext*) sudo resize2fs "$root";; '
        "xfs) sudo xfs_growfs /;; "
        "btrfs) sudo btrfs filesystem resize max /;; "
        "esac; "
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
            print(
                f"⚠  {t('Guest agent grow failed; falling back to console.')}"
            )
        else:
            print(
                t("Guest agent unavailable; falling back to serial console.")
            )
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
                        "sudo",
                        "virsh",
                        "qemu-agent-command",
                        name,
                        json.dumps(payload),
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
        if not self._is_yes(input(t("Open the serial console now? (y/N): "))):
            return
        cmd = f"sudo virsh console {shlex.quote(name)}"
        print(f"{t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    @staticmethod
    def _ssh_private_key(pub_path):
        """Clé PRIVÉE correspondant à une clé publique, ou '' si introuvable.
        C'est elle que réclame IdentityFile ; donner le « .pub » ferait
        échouer l'authentification."""
        if not pub_path:
            return ""
        priv = pub_path[:-4] if pub_path.endswith(".pub") else pub_path
        return priv if os.path.exists(os.path.expanduser(priv)) else ""

    @staticmethod
    def _ssh_config_drop_hosts(content, names):
        """Retire les blocs « Host … » qui déclarent l'un de `names`.

        On découpe en blocs plutôt que de substituer par expression
        régulière : une ligne Host peut porter PLUSIEURS noms, et il faut
        alors retirer le bloc entier dès qu'un seul de ses noms est repris —
        sinon le même nom se retrouverait défini deux fois, et ssh
        appliquerait la première définition rencontrée."""
        drop = set(names)
        out, block, block_names = [], [], set()

        def flush():
            if block and not (block_names & drop):
                out.extend(block)

        for line in content.splitlines(keepends=True):
            if re.match(r"^[ \t]*Host[ \t]+", line):
                flush()
                block = [line]
                block_names = set(line.split()[1:])
            elif block:
                # Une ligne non indentée et non vide clôt le bloc (Match,
                # directive globale…) : elle n'appartient à personne.
                if line.strip() and not line[:1].isspace():
                    flush()
                    block, block_names = [], set()
                    out.append(line)
                else:
                    block.append(line)
            else:
                out.append(line)
        flush()
        return "".join(out)

    def _write_ssh_config_entry(
        self, host, user, ip, proxy_jump=None, identity_file=None
    ):
        """Écrit/remplace un bloc « Host <host> » dans ~/.ssh/config.

        `host` peut être une liste de noms : ils partagent alors un seul bloc.
        Sert aux VM imbriquées, joignables par leur nom court ET par leur nom
        chaîné « parent+enfant », qui montre où elles vivent.

        `proxy_jump` : alias du rebond pour une VM imbriquée, dont l'IP n'est
        joignable que depuis son hôte. OpenSSH enchaîne les ProxyJump tout
        seul dès que le parent a lui-même le sien.

        `identity_file` : clé PRIVÉE à présenter. Sans elle, ssh propose
        toutes les identités de l'agent et un parc un peu fourni déclenche
        « Too many authentication failures » avant d'arriver à la bonne."""
        names = [host] if isinstance(host, str) else list(host)
        cfg = os.path.expanduser("~/.ssh/config")
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        existing = ""
        if os.path.exists(cfg):
            with open(cfg, encoding="utf-8") as fh:
                existing = fh.read()
        existing = self._ssh_config_drop_hosts(existing, names).rstrip("\n")
        block = (
            f"Host {' '.join(names)}\n"
            f"    HostName {ip}\n"
            f"    User {user}\n"
            # IP DHCP réutilisées entre VM -> on évite l'erreur de clé d'hôte.
            f"    StrictHostKeyChecking no\n"
            f"    UserKnownHostsFile /dev/null\n"
        )
        if identity_file:
            # IdentitiesOnly : sans lui, IdentityFile s'AJOUTE aux clés de
            # l'agent au lieu de les remplacer, et le serveur coupe après
            # 5 essais infructueux.
            block += (
                f"    IdentityFile {identity_file}\n"
                f"    IdentitiesOnly yes\n"
            )
        if proxy_jump:
            block += f"    ProxyJump {proxy_jump}\n"
        content = (existing + "\n\n" + block) if existing else block
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.chmod(cfg, 0o600)
        print(f"✅ {t('Added to ~/.ssh/config:')} ssh {names[0]}")

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
        """Importe deploy_qemu.py comme module (source de vérité des specs).

        Mémorisé : le catalogue interroge cette source une fois par couple
        (distro, version), et réexécuter un fichier de 2 700 lignes à chaque
        passage se voyait à l'écran.
        """
        cached = getattr(self, "_qemu_mod_cache", None)
        if cached is not None:
            return cached
        import importlib.util

        path = self._qemu_script_path()
        spec = importlib.util.spec_from_file_location("deploy_qemu", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._qemu_mod_cache = mod
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
    def _is_index(token, options):
        """Vrai si le jeton est un numéro valide dans la liste (1-based)."""
        try:
            return 1 <= int(token) <= len(options)
        except ValueError:
            return False

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
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _FTimeout
        from concurrent.futures import as_completed

        labels = labels or {}
        print(
            f"\n{t('Resolving VM IPs (parallel, emulated boot is slow)...')}"
        )
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

    def _qemu_branch_list(self):
        """Branches distantes d'ERPLibre, triées. Vide si le réseau manque.

        Séparé de l'invite : le formulaire TUI a besoin de la LISTE, et cet
        appel réseau (jusqu'à 30 s) doit être fait avant que Textual prenne
        le terminal."""
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
        branches.sort()
        return branches

    def _qemu_pick_branch(self):
        """Liste les branches distantes d'ERPLibre et en fait choisir une."""
        print(f"\n{t('Fetching ERPLibre branch list...')}")
        branches = self._qemu_branch_list()
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

    # Préparation hôte QEMU/libvirt du profil « ERPLibre Déploiement ».
    # Délègue à deploy_qemu.py --setup-host : les noms de paquets y sont déjà
    # définis pour apt/dnf/pacman/zypper/brew (TOOL_PACKAGES, DAEMON_PACKAGES),
    # et il fait ce que l'ancien one-liner ne faisait PAS — démarrer le démon,
    # ajouter l'utilisateur au groupe libvirt et activer le réseau « default ».
    # Sans le groupe, virt-install retombe sur qemu:///session où « default »
    # n'existe pas : la VM échoue alors que tous les paquets sont installés.
    # L'ancien one-liner finissait par « || true » et masquait ses erreurs.
    _QEMU_QEMU_PKGS = (
        "./script/qemu/deploy_qemu.py --setup-host --assume-yes"
        " --reboot-if-needed"
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

    def _qemu_install_profiles(self):
        """Profils installables : [(libellé, commande)]. Le premier est le
        défaut. Partagé par l'invite en ligne et le formulaire TUI."""
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
        return profiles

    def _qemu_pick_install_profile(self):
        """Choix de CE QU'ON installe sur la VM. Renvoie (label, commande
        finale exécutée dans ~/git/erplibre)."""
        profiles = self._qemu_install_profiles()
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
    def _qemu_install_dir(prod):
        """Répertoire d'installation ERPLibre dans la VM : /opt/erplibre en
        PROD (hors /home -> service SELinux confiné possible), sinon
        ~/git/erplibre (dev)."""
        return "/opt/erplibre" if prod else "$HOME/git/erplibre"

    @staticmethod
    def _qemu_guide_dir(prod):
        """Répertoire d'ERPLibre tel que le GUIDE de connexion l'annonce.

        « ~/git/erplibre » plutôt que « $HOME/git/erplibre » : ce chemin n'est
        pas exécuté par un script, il est lu par quelqu'un qui recopie la ligne
        dans son shell — où les deux marchent — et le tilde est la forme qu'il
        reconnaît. En production le chemin est absolu et la question ne se pose
        pas."""
        return "/opt/erplibre" if prod else "~/git/erplibre"

    @staticmethod
    def _qemu_make_target(install_cmd):
        """Cible make qui installe Odoo dans `install_cmd`, pour le guide.

        Les profils s'écrivent « make install_os && make install_odoo_18 » : la
        cible utile est la SECONDE, celle qui installe Odoo, et c'est aussi
        celle qu'on relance après un « git pull ». Les profils qui n'en ont pas
        (« ERPLibre seul », « mobile », « Déploiement ») rendent une chaîne
        vide : le guide s'arrête alors à « git pull » plutôt que d'annoncer une
        cible qui n'est pas celle de cette VM."""
        found = re.findall(r"make\s+(install_odoo\S*)", install_cmd or "")
        return found[-1] if found else ""

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
        selinux_shell = (
            'SELINUX_LINE=""; '  # pas de SELinuxContext (inefficace)
        )
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
            "ExecStart=/bin/bash $SVC_DIR/run.sh\n"
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

    # Bureaux disponibles, par gestionnaire de paquets. Une seule source pour
    # la TUI et la CLI. Les noms ont été relevés distribution par
    # distribution, pas déduits : Arch n'a PAS xrdp dans ses dépôts officiels
    # (AUR seulement) et prend TigerVNC, avec un port et un client différents.
    #
    # Côté dnf on installe un ENVIRONNEMENT, pas un groupe : le groupe
    # « gnome-desktop » d'AlmaLinux apporte gdm et gnome-shell mais PAS
    # « base-x », donc aucun serveur X — vérifié dans son comps.xml. Les
    # environnements diffèrent selon la famille (RHEL / Fedora), d'où la
    # cascade : le premier qui existe gagne.
    _QEMU_DESKTOP = {
        "gnome": {
            "label": "GNOME",
            "apt": "gnome-core dbus-x11",
            "dnf_env": "graphical-server-environment "
            "workstation-product-environment gnome-desktop",
            "pacman": "gnome gdm",
            "zypper": "patterns-gnome-gnome_basic gdm",
            "service": "gdm",
            # Suffixe ajouté au nom de VM, donc au nom d'hôte. Une VM
            # graphique se reconnaît alors d'un « virsh list », et deux VM de
            # même distribution mais de types différents ne se marchent plus
            # dessus — le nom sert aussi de clé de collision.
            "suffix": "gnome",
        },
        "cinnamon": {
            "label": "Cinnamon (Linux Mint)",
            # Le bureau de Linux Mint, depuis les dépôts de la distribution :
            # Ubuntu 24.04 livre Cinnamon 6.0.4, la 25.10 la 6.4.12. Le dépôt
            # de Mint lui-même n'est pas utilisé — il est en HTTP nu et ne
            # publie que i386/amd64, ce qui exclurait arm64 et s390x.
            "apt": "cinnamon-desktop-environment dbus-x11",
            "dnf_env": "cinnamon-desktop",
            "pacman": "cinnamon lightdm lightdm-gtk-greeter",
            "zypper": "cinnamon lightdm",
            "service": "lightdm",
            # « mint » plutôt que « cinnamon » : c'est le nom retenu pour le
            # parc. Le paquet installé reste bien Cinnamon, depuis les dépôts
            # de la distribution et non ceux de Mint.
            "suffix": "mint",
        },
    }
    # Ubuntu remplace trois applications par des paquets de TRANSITION dont le
    # postinst lance « snap install ». Or snapd est coupé juste avant, pour
    # empêcher ses rafraîchissements pendant l'installation : le postinst ne
    # joint alors pas le store et RÉESSAIE UNE MINUTE DURANT TRENTE MINUTES.
    # L'installation paraît figée et rien dans le log ne dit pourquoi.
    #
    # La famille est CLOSE et relevée dans l'index du dépôt, pas devinée : trois
    # paquets sources portent une version « …snap1… », firefox, chromium-browser
    # et thunderbird — avec toutes leurs déclinaisons (firefox-locale-*,
    # chromium-codecs-*). Les corriger un à un a coûté deux VM figées : firefox
    # sous GNOME, puis thunderbird sous Cinnamon.
    #
    # Les trois ne sont que RECOMMANDÉS, et avec des solutions de rechange :
    #   Recommends: firefox-esr | firefox | chromium | epiphany-browser | …
    #   Recommends: thunderbird | evolution | geary | mail-reader
    # On les écarte donc, et on nomme deux vrais .deb pour satisfaire les
    # recommandations. Les nommer rend le résultat déterministe : laissé à apt,
    # le premier repli était « chromium-browser », un paquet de transition lui
    # aussi.
    #
    # Un épinglage apt sur « Pin: version *snap1* » aurait été plus général —
    # essayé en glob et en regex, il ne bloque rien. Mesuré sur une VM 26.04 :
    # avec cette liste, GNOME (844 paquets) et Cinnamon (1167) n'en tirent
    # AUCUN, sans erreur apt.
    _QEMU_APT_NO_SNAP = (
        "epiphany-browser evolution"
        " firefox- chromium- chromium-browser- thunderbird-"
    )

    # Magasin d'applications d'une VM graphique. Ubuntu livre snapd dans son
    # image cloud (vérifié : 2.75.2 en 26.04) et gnome-core RECOMMANDE
    # « firefox », qui n'y est plus qu'un paquet de transition lançant
    # « snap install ». Trois réponses possibles, et il faut choisir :
    #
    #   deb      rien que des .deb. snapd coupé, paquets-snap écartés,
    #            epiphany-browser comme navigateur. Le plus léger, et rien à
    #            télécharger en plus pendant un déploiement déjà long.
    #   flatpak  l'outillage Flatpak en plus, SANS dépôt Flathub ni
    #            installation : la machine est prête, l'administrateur ajoute
    #            les dépôts qu'il veut.
    #   snap     le comportement d'Ubuntu, snapd laissé actif et Firefox en
    #            snap. Lent sous émulation, mais c'est le défaut de la distro.
    #
    # La question n'a de sens que pour une VM Ubuntu GRAPHIQUE : sur un
    # serveur, rien ne tire de snap.
    QEMU_APP_STORES = (
        ("deb", "deb only (epiphany-browser)"),
        ("flatpak", "Flatpak tooling, no Flathub"),
        ("snap", "snap (Ubuntu default, Firefox)"),
    )
    QEMU_SNAP_DISTROS = ("ubuntu",)

    # Fuseaux proposés au déploiement. Des NOMS IANA, pas des décalages :
    # cloud-init écrit /etc/timezone et refuse « UTC-5 », qui ne dit d'ailleurs
    # rien de l'heure d'été. Un nom porte ses propres règles de bascule.
    #
    # Liste courte et ordonnée par usage réel plutôt qu'exhaustive : la base
    # IANA en compte près de six cents, illisibles dans une liste déroulante.
    # Le Québec d'abord, le reste du Canada ensuite, puis les places qu'on
    # rencontre en pratique. La saisie libre reste offerte pour le reste.
    QEMU_TIMEZONES = (
        "America/Montreal",
        "America/Toronto",
        "America/Halifax",
        "America/Winnipeg",
        "America/Edmonton",
        "America/Vancouver",
        "America/St_Johns",
        "UTC",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Sao_Paulo",
        "Europe/London",
        "Europe/Paris",
        "Europe/Brussels",
        "Europe/Zurich",
        "Europe/Madrid",
        "Europe/Berlin",
        "Africa/Casablanca",
        "Asia/Dubai",
        "Asia/Kolkata",
        "Asia/Shanghai",
        "Asia/Tokyo",
        "Australia/Sydney",
    )

    @classmethod
    def _qemu_timezone_choices(cls, current=""):
        """Liste à proposer : le fuseau de l'hôte en tête, sans doublon.

        Le mettre en premier plutôt que de le supposer présent : une machine
        hors de cette liste doit quand même voir le sien en un coup d'œil."""
        out = [current] if current else []
        out += [z for z in cls.QEMU_TIMEZONES if z != current]
        return out

    @classmethod
    def _qemu_desktop_suffixes(cls):
        """{clé de saveur: suffixe de nom}. La TUI le reçoit par son contexte
        plutôt que de le redéfinir : un seul endroit décrit les saveurs."""
        return {k: v["suffix"] for k, v in cls._QEMU_DESKTOP.items()}

    @classmethod
    def _qemu_apt_store_pkgs(cls, app_store):
        """Paquets apt à ajouter au bureau selon le magasin retenu."""
        if app_store == "snap":
            # On ne retire rien : Firefox arrivera en snap, comme sur une
            # Ubuntu ordinaire, et snapd est resté actif pour le servir.
            return ""
        pkgs = cls._QEMU_APT_NO_SNAP
        if app_store == "flatpak":
            # Le greffon donne à GNOME Logiciels la gestion des Flatpak.
            # Aucun « remote-add » ici : le dépôt reste un choix explicite.
            pkgs += " flatpak gnome-software-plugin-flatpak"
        return pkgs

    # Accès distant, indépendant du bureau choisi.
    _QEMU_DESKTOP_REMOTE = {
        "apt": {"packages": "xrdp", "port": 3389, "client": "RDP"},
        "dnf": {"packages": "xrdp", "port": 3389, "client": "RDP"},
        "pacman": {"packages": "tigervnc", "port": 5901, "client": "VNC"},
        "zypper": {"packages": "xrdp", "port": 3389, "client": "RDP"},
    }
    # Place que prend un bureau complet, annoncée dans le plan : sur une image
    # cloud de 40 G, l'oublier remplit le disque en pleine installation.
    QEMU_DESKTOP_EXTRA_DISK_GB = 6

    @staticmethod
    def _qemu_cloud_init_wait():
        """Attend la fin de cloud-init, qui tient le verrou apt/dnf/pacman
        pendant sa phase « paquets ».

        L'attente dure jusqu'à 15 min et n'écrivait RIEN : sur une architecture
        émulée, le log restait muet un quart d'heure juste après avoir annoncé
        le début de l'installation, ce qui se lit comme un blocage. Deux lignes
        l'encadrent, et le « status » final dit si elle a abouti ou expiré."""
        return (
            "if command -v cloud-init >/dev/null 2>&1; then "
            'echo "== '
            + t("Waiting for cloud-init to finish (up to 15 min)")
            + ' =="; '
            "sudo timeout 900 cloud-init status --wait >/dev/null 2>&1 "
            "|| true; "
            + f'echo "   {t("cloud-init:")} $(cloud-init status 2>/dev/null '
            '| head -1)"; '
            "fi; "
        )

    @staticmethod
    def _qemu_no_auto_upgrade(prod, app_store="deb"):
        """Coupe les mises à jour automatiques sur une VM de DÉVELOPPEMENT.

        Vécu sur erplibre-ubuntu-2404 : unattended-upgrades s'est déclenché en
        pleine migration Odoo 12->13 et a redémarré le cluster PostgreSQL
        (« received fast shutdown request » x3) -> OpenUpgrade a perdu sa
        connexion et la base intermédiaire est restée à moitié migrée. Effet
        secondaire bienvenu : les timers apt-daily ne tiennent plus le verrou
        apt pendant l'installation. En PROD on ne touche à rien : les
        correctifs de sécurité automatiques doivent rester actifs."""
        if prod:
            return ""
        return (
            "if command -v apt-get >/dev/null 2>&1; then "
            "sudo systemctl disable --now unattended-upgrades.service "
            "apt-daily.timer apt-daily-upgrade.timer "
            ">/dev/null 2>&1 || true; "
            'printf \'APT::Periodic::Update-Package-Lists "0";\\n'
            'APT::Periodic::Unattended-Upgrade "0";\\n\' '
            "| sudo tee /etc/apt/apt.conf.d/99-erplibre-no-auto-upgrade "
            ">/dev/null; "
            "fi; "
            "if command -v dnf >/dev/null 2>&1; then "
            "sudo systemctl disable --now dnf-automatic.timer "
            "dnf-automatic-install.timer >/dev/null 2>&1 || true; "
            "fi; "
            # snapd : 57 s sur le CHEMIN CRITIQUE du démarrage, mesurés par
            # « systemd-analyze critical-chain » sur une VM s390x —
            # multi-user.target attend snapd.seeded. C'est du temps payé pour
            # rien quand aucun snap n'est voulu. On désactive plutôt que
            # désinstaller, pour rester réversible d'un « systemctl enable ».
            #
            # Sauf si le magasin RETENU est snap : le couper puis laisser un
            # postinst appeler « snap install » est exactement ce qui figeait
            # une VM graphique trente minutes durant.
            + (
                ""
                if app_store == "snap"
                else "sudo systemctl disable --now snapd.seeded.service "
                "snapd.service snapd.socket snapd.apparmor.service "
                ">/dev/null 2>&1 || true; "
            )
        )

    # Miroirs openSUSE préférés, du plus proche au dernier recours. Le
    # redirecteur officiel n'est PAS géographique pour cette distribution :
    # mesuré depuis Montréal sur les métadonnées oss s390x (15 Mo),
    # download.opensuse.org met 23,8 s — il sert depuis l'Europe — contre
    # 2,7 s pour mirrors.rit.edu. Les trois familles dnf, elles, choisissent
    # déjà un miroir canadien toutes seules ; rien à faire de ce côté.
    #
    # Chaque miroir est SONDÉ sur le chemin de l'architecture ET du produit
    # courants, puis le premier qui répond gagne. C'est nécessaire : aucun ne
    # réplique tout. Relevé le 2026-08-12 —
    #   csclub    Leap oui, Tumbleweed non (404)
    #   rit.edu   zsystems oui ; injoignable ce jour-là (curl 7)
    #   leaseweb  Tumbleweed x86_64 et Leap oui, ports zsystems non
    # D'où plusieurs entrées plutôt qu'une : avec la seule rit.edu, sa panne
    # renvoyait tout le monde sur download.opensuse.org, servi d'Europe.
    # Ordonnées par proximité de Montréal. Aucun sondage concluant : on garde
    # les dépôts de l'image, donc le comportement d'avant.
    _QEMU_ZYPPER_MIRRORS = (
        "https://mirror.csclub.uwaterloo.ca/opensuse",
        "https://mirrors.rit.edu/opensuse",
        "https://mirror.us.leaseweb.net/opensuse",
    )

    # Miroirs Arch canadiens, du plus rapide au suivant. Mesuré depuis
    # Montréal sur extra.db : quantum5 2,0 s, xenyth 7,1 s, contre 8,0 s pour
    # geo.mirror.pkgbuild.com — le miroir « géographique » officiel n'est donc
    # pas le meilleur ici. Arch n'est proposé qu'en amd64 dans le catalogue,
    # et ces deux-là ne servent que x86_64 (Arch Linux ARM a ses propres
    # miroirs) : la garde d'architecture le dit quand même.
    _QEMU_PACMAN_MIRRORS = (
        "https://mirror.quantum5.ca/archlinux/$repo/os/$arch",
        "https://mirror.xenyth.net/archlinux/$repo/os/$arch",
    )

    def _qemu_pacman_mirror_cmd(self):
        """Place les miroirs canadiens EN TÊTE de la mirrorlist.

        reflector écrase le fichier avec « --save » : il faut donc écrire
        après lui, pas avant. Ses miroirs restent dessous, comme repli."""
        # « \\n » et non un vrai saut de ligne : la commande distante est UNE
        # chaîne, passée à bash -c après shlex.quote. Un retour littéral y
        # survivrait, mais rendrait la chaîne illisible et fragile à relire.
        # « $repo » et « $arch » restent littéraux : c'est pacman qui les
        # substitue, d'où les guillemets SIMPLES autour du format.
        lines = "".join(f"Server = {m}\\n" for m in self._QEMU_PACMAN_MIRRORS)
        first = self._QEMU_PACMAN_MIRRORS[0].split("/")[2]
        return (
            '[ "$(uname -m)" = x86_64 ] && { '
            # Idempotent : la préparation Arch passe deux fois quand une VM
            # est graphique (bureau puis ERPLibre), et empiler les mêmes
            # miroirs à chaque passage allongerait la liste sans rien gagner.
            f'grep -q "{first}" /etc/pacman.d/mirrorlist 2>/dev/null || {{ '
            f"printf '{lines}' | sudo tee /etc/pacman.d/mirrorlist.el "
            "> /dev/null; "
            "sudo sh -c 'cat /etc/pacman.d/mirrorlist "
            ">> /etc/pacman.d/mirrorlist.el "
            "&& mv /etc/pacman.d/mirrorlist.el /etc/pacman.d/mirrorlist'; "
            "}; }; "
        )

    def _qemu_pacman_prepare_cmd(self):
        """Préparation Arch : verrou, miroirs proches, mise à jour COMPLÈTE.

        Les trois sont indissociables, et il faut les faire AVANT la moindre
        installation. Une image cloud Arch est un instantané dont la base de
        paquets pointe des versions déjà retirées des miroirs : « pacman -S »
        s'y arrête sur « failed retrieving file … 404 » — vécu sur llvm-libs
        et perl. Arch ne supporte pas la mise à jour partielle.

        Ce bloc ne vivait QUE dans le chemin ERPLibre. Or le bureau s'installe
        AVANT lui : une VM graphique échouait donc toujours, sans jamais
        atteindre le code qui l'aurait sauvée."""
        return (
            "if command -v pacman >/dev/null 2>&1; then "
            # Verrou périmé (cloud-init interrompu) : le retirer SEULEMENT si
            # aucun pacman ne tourne, sinon on attend qu'il se libère.
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            # reflector d'abord, nos miroirs ensuite : « --save » écrase le
            # fichier, écrire avant lui ne servirait à rien.
            "sudo pacman -Sy --needed --noconfirm reflector || true; "
            "sudo reflector --latest 20 --protocol https --sort rate "
            "--save /etc/pacman.d/mirrorlist || true; "
            + self._qemu_pacman_mirror_cmd()
            + "sudo pacman -Syu --noconfirm || true; "
            "fi; "
        )

    def _qemu_zypper_mirror_cmd(self):
        """Réécrit l'hôte des dépôts zypper vers un miroir plus proche."""
        mirrors = " ".join(self._QEMU_ZYPPER_MIRRORS)
        # Leap et Tumbleweed n'ont pas le même arbre de dépôts : la rolling
        # isole les architectures secondaires sous /ports/, Leap 16 unifie tout
        # et garde s390x dans l'arbre principal (les /ports/ y rendent 404).
        return (
            ". /etc/os-release; "
            'case "$ID" in *tumbleweed*) zp=tumbleweed; '
            '[ "$(uname -m)" = s390x ] && zp=ports/zsystems/tumbleweed;; '
            '*) zp="distribution/leap/$VERSION_ID";; esac; '
            f"for zm in {mirrors}; do "
            "if curl -fsS --max-time 20 -o /dev/null "
            '"$zm/$zp/repo/oss/repodata/repomd.xml"; then '
            "sudo sed -i "
            '"s|https\\?://download\\.opensuse\\.org|$zm|g" '
            "/etc/zypp/repos.d/*.repo 2>/dev/null || true; "
            f'echo "   {t("openSUSE mirror:")} $zm"; break; fi; done; '
        )

    @staticmethod
    def _qemu_tunnel_hint(port, kind):
        """Deux lignes imprimees DANS la VM : le tunnel a monter depuis le
        poste de travail, avec l'adresse deja remplie.

        Un port annonce sans chemin pour y arriver n'aide personne : le reseau
        libvirt n'est pas route depuis l'exterieur de son hote."""
        local = port + 1
        return (
            "ip=$(hostname -I 2>/dev/null | awk '{print $1}'); "
            f'echo "     {t("From your workstation:")} '
            f'ssh -L {local}:$ip:{port} <user>@<hote-libvirt>"; '
            f'echo "     {t("then point your client at")} '
            f'localhost:{local}  ({kind})"; '
        )

    def _qemu_desktop_remote_cmd(self, flavour="gnome", app_store="deb"):
        """Bloc shell installant le bureau choisi + son accès distant, quelle
        que soit la distribution. Même aiguillage que l'installation ERPLibre,
        et même traitement du verrou apt : cette étape passe par la commande
        distante et non par cloud-init, où ses 1 à 2 Go allongeraient un
        démarrage déjà long sans laisser la moindre trace dans le suivi."""
        de = self._QEMU_DESKTOP.get(flavour) or self._QEMU_DESKTOP["gnome"]
        rem = self._QEMU_DESKTOP_REMOTE
        label = de["label"]
        return (
            f'echo "== {t("Installing the desktop (long):")} {label} =="; '
            "if command -v apt-get >/dev/null 2>&1; then "
            "n=0; until sudo apt-get -o DPkg::Lock::Timeout=120 update -qq; do "
            "n=$((n+1)); [ $n -ge 30 ] && break; sleep 10; done; "
            "sudo DEBIAN_FRONTEND=noninteractive "
            "apt-get -o DPkg::Lock::Timeout=600 install -y "
            f"{de['apt']} {rem['apt']['packages']} "
            f"{self._qemu_apt_store_pkgs(app_store)}; "
            "elif command -v dnf >/dev/null 2>&1; then "
            # Cascade d'environnements : le premier qui existe gagne. Un
            # environnement absent fait rendre 1 à dnf sans rien installer,
            # d'où le « || » plutôt qu'une détection préalable.
            "de_ok=0; "
            f"for e in {de['dnf_env']}; do "
            'sudo dnf -y group install "$e" && { de_ok=1; break; }; done; '
            '[ "$de_ok" = 1 ] || echo "Aucun environnement graphique dnf '
            "trouve pour " + label + '"; '
            f"sudo dnf install -y {rem['dnf']['packages']}; "
            "elif command -v pacman >/dev/null 2>&1; then "
            "pgrep -x pacman >/dev/null 2>&1 "
            "|| sudo rm -f /var/lib/pacman/db.lck; "
            + self._qemu_pacman_prepare_cmd()
            + f"sudo pacman -S --needed --noconfirm {de['pacman']} "
            f"{rem['pacman']['packages']}; "
            "elif command -v zypper >/dev/null 2>&1; then "
            "sudo zypper --non-interactive refresh || true; "
            # « --auto-agree-with-licenses » appartient à la SOUS-COMMANDE
            # install, pas aux options globales : placé avant, zypper répond
            # « The flag --auto-agree-with-licenses is not known ».
            "sudo zypper --non-interactive install "
            f"--auto-agree-with-licenses {de['zypper']} "
            f"{rem['zypper']['packages']}; "
            "else echo 'Gestionnaire de paquets inconnu'; exit 1; fi; "
            # Le bureau ne sert à rien s'il ne démarre pas tout seul : les
            # images cloud démarrent en multi-user.target.
            "sudo systemctl set-default graphical.target || true; "
            f"sudo systemctl enable {de['service']} >/dev/null 2>&1 || true; "
            # Et il faut le DÉMARRER, pas seulement l'activer. Deux raisons,
            # toutes deux mesurées sur erplibre-ubuntu-2604-gnome :
            #
            #   - graphical.target était DÉJÀ atteinte quand le paquet est
            #     arrivé, et une cible active ne rattrape pas un service ajouté
            #     après coup : display-manager.service est resté inactif ;
            #   - sur Debian et Ubuntu, « systemctl enable gdm » rend 0 sans
            #     rien faire — l'unité n'a pas de « WantedBy », seulement
            #     « Alias=display-manager.service » que le paquet a déjà posé.
            #
            # Résultat : GNOME installé, gdm3 installé, cible graphique par
            # défaut… et la console de la VM restait en mode texte jusqu'au
            # premier redémarrage. L'écran, c'est justement ce qu'on est venu
            # chercher sur une VM graphique.
            "if sudo systemctl start display-manager.service 2>/dev/null || "
            f"sudo systemctl start {de['service']} 2>/dev/null; then "
            f'echo "   {t("graphical session started")}"; '
            f'else echo "   ⚠ {t("graphical session not started; reboot the VM")}"; '
            "fi; "
            # xrdp là où il existe ; sur Arch c'est TigerVNC, qui se configure
            # par utilisateur et n'a pas de service à activer d'office.
            "if command -v xrdp >/dev/null 2>&1; then "
            "sudo systemctl enable --now xrdp >/dev/null 2>&1 || true; "
            f'echo "   {t("Remote desktop:")} RDP 3389"; '
            # L'IP est sur le reseau PRIVE de libvirt : annoncer le port sans
            # dire comment l'atteindre ne sert a rien. La VM connait sa propre
            # adresse ; seul le nom de l'hote libvirt manque, et c'est le
            # lecteur qui l'a. La console SPICE, elle, est en « listen=none »
            # et suppose virt-viewer SUR l'hote — inutilisable quand cet hote
            # est lui-meme une VM sans interface graphique.
            + self._qemu_tunnel_hint(3389, "RDP")
            + "elif command -v vncserver >/dev/null 2>&1; then "
            f'echo "   {t("Remote desktop:")} VNC 5901 '
            '(vncpasswd puis vncserver :1)"; '
            + self._qemu_tunnel_hint(5901, "VNC")
            + "fi; "
        )

    # ------------------------------------------------------------------ #
    # Outils de développement d'une VM graphique
    # ------------------------------------------------------------------ #
    # Chacun est une case à cocher, indépendante des autres, et chacun pèse sur
    # le disque — le plan l'annonce AVANT de déployer, sinon l'installation se
    # termine sur un disque plein après une heure d'attente.
    #
    # « disk_gb » compte le PIC, pas l'installé : l'archive téléchargée vit sur
    # le disque le temps de l'extraction. PyCharm, c'est 1,2 Go d'archive et
    # ~3 Go déplié ; Android Studio 1,5 Go et 3,5 Go, plus la place du premier
    # SDK que l'utilisateur téléchargera.
    #
    # « arches » n'est pas une précaution : Google ne publie Android Studio
    # QU'EN x86_64 (vérifié — toutes les variantes aarch64 de l'URL rendent 404,
    # et le product-info.json de l'archive ne déclare qu'une cible
    # « Linux/amd64 »). JetBrains, lui, publie bien une archive aarch64.
    _QEMU_VM_TOOLS = {
        "pycharm": {
            "label": "PyCharm",
            "hint": "Python IDE, opens the ERPLibre checkout",
            "disk_gb": 5,
            "arches": ("amd64", "arm64"),
            "desktops": (),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        "android": {
            "label": "Android Studio",
            "hint": "ERPLibre mobile development (x86_64 only)",
            "disk_gb": 8,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        "gnome_ext": {
            "label": "GNOME extensions",
            "hint": "suggested extensions + extension manager",
            "disk_gb": 1,
            "arches": (),
            "desktops": ("gnome",),
            "needs_desktop": True,
            "families": (),
            "phase": "before",
        },
        # Le seul outil qui ne demande PAS de bureau : il compile, il n'affiche
        # rien. Une VM serveur le prend, une VM graphique aussi — et sur
        # celle-ci le SDK est partagé avec Android Studio plutôt que doublé.
        #
        # « families » le borne à apt, et ce n'est pas un choix : l'installateur
        # du dépôt mobile, install-android.sh, commence par
        # « sudo apt install openjdk-17-jdk ». Ailleurs il s'arrête là. Lever
        # cette limite se fait dans CE script-là, pas ici.
        #
        # Disque : ~1,5 Go de SDK et plateformes, ~2,5 Go de NDK, whisper.cpp
        # et sentencepiece clonés, node_modules, et les artefacts Gradle.
        "mobile": {
            "label": "ERPLibre mobile (build)",
            "hint": "APK debug + Vitest, validates the VM",
            "disk_gb": 12,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": False,
            "families": ("apt",),
            # APRÈS l'installation : le build a besoin du dépôt mobile, que le
            # manifeste ajoute, et du venv d'outils pour le synchroniser.
            "phase": "after",
        },
        # Forgejo est un SERVICE, pas un outil de bureau : une VM serveur le
        # prend aussi bien qu'une VM graphique. Son binaire est STATIQUE — le
        # même fichier sur apt, dnf, pacman et zypper — donc aucune famille de
        # paquets n'est exclue, et c'est ce qui le rend portable sur toutes les
        # plateformes ERPLibre sans une branche par distribution.
        #
        # Les architectures, elles, sont bornées par l'amont : Forgejo publie
        # amd64, arm64 et arm-6, et RIEN pour s390x. Sur celle-là il faudrait le
        # bâtir en Go ; la case se grise plutôt que de poser un binaire qui ne
        # s'exécute pas.
        #
        # Disque : ~115 Mo de binaire (34 Mo téléchargés en .xz), la base SQLite
        # et les dépôts que l'utilisateur y poussera.
        "forgejo": {
            "label": "Forgejo (git forge)",
            "hint": "self-hosted git forge on :3000, SQLite",
            "disk_gb": 2,
            "arches": ("amd64", "arm64"),
            "desktops": (),
            "needs_desktop": False,
            "families": (),
            # APRÈS l'installation : le script vit dans le dépôt, donc après le
            # clone. Rien d'autre ne l'y oblige — Forgejo ne dépend ni du venv
            # ni d'Odoo.
            "phase": "after",
        },
        # L'émulateur n'a pas besoin de bureau DANS la VM : il s'affiche sur
        # l'écran de qui s'y connecte, par « ssh -X ». Il a besoin, lui, de KVM
        # dans la VM — donc de virtualisation imbriquée sur l'hôte, ce que le
        # bloc vérifie et annonce plutôt que de laisser découvrir.
        #
        # Disque : ~1,5 Go d'image système, ~2 Go de données d'AVD, plus
        # l'émulateur lui-même.
        "avd": {
            "label": "Android emulator (Pixel)",
            "hint": "AVD viewable over ssh -X",
            "disk_gb": 6,
            "arches": ("amd64",),
            "desktops": (),
            "needs_desktop": False,
            "families": ("apt",),
            "phase": "after",
        },
    }

    # Famille de paquets de chaque distribution, pour borner un outil à ce qui
    # sait l'installer.
    _QEMU_DISTRO_FAMILY = {
        "ubuntu": "apt",
        "debian": "apt",
        "fedora": "dnf",
        "almalinux": "dnf",
        "rocky": "dnf",
        "opensuse": "zypper",
        "arch": "pacman",
    }

    @classmethod
    def _qemu_vm_tool_choices(cls):
        """[(clé, libellé, indice)] pour le formulaire et l'invite en ligne."""
        return [
            (key, t(spec["label"]), t(spec["hint"]))
            for key, spec in cls._QEMU_VM_TOOLS.items()
        ]

    @classmethod
    def _qemu_tools_for(cls, tools, arch, desktop, distro="", phase=""):
        """Outils RÉELLEMENT applicables à cette VM.

        Un outil demandé pour tout le parc ne convient pas forcément à chaque
        machine : Android Studio n'existe qu'en x86_64, les extensions GNOME
        n'ont pas de sens sous Cinnamon, et la compilation mobile ne sait
        s'installer que sur les distributions apt. Filtrer ici plutôt que dans
        la commande distante évite d'annoncer une installation qui ne se fera
        pas.

        `phase` restreint au moment d'exécution : « before » avant le clone,
        « after » après l'installation. Vide, les deux sont rendus."""
        out = []
        for key in tools or ():
            spec = cls._QEMU_VM_TOOLS.get(key)
            if not spec:
                continue
            if spec["needs_desktop"] and not desktop:
                continue
            if spec["arches"] and arch not in spec["arches"]:
                continue
            if spec["desktops"] and desktop not in spec["desktops"]:
                continue
            family = cls._QEMU_DISTRO_FAMILY.get(distro, "")
            if spec["families"] and distro and family not in spec["families"]:
                continue
            if phase and spec["phase"] != phase:
                continue
            out.append(key)
        return out

    @classmethod
    def _qemu_tools_disk_gb(cls, tools, arch, desktop, distro=""):
        """Go à ajouter au disque pour les outils applicables à cette VM."""
        return sum(
            cls._QEMU_VM_TOOLS[k]["disk_gb"]
            for k in cls._qemu_tools_for(tools, arch, desktop, distro)
        )

    # Archive officielle JetBrains, et non un paquet de distribution : aucun ne
    # couvre les quatre gestionnaires (Arch l'a dans extra, Debian et Ubuntu ne
    # l'ont qu'en snap — coupé ici —, Fedora et openSUSE pas du tout).
    #
    # La ligne COMMUNITY, et non le produit unifié. Mesuré dans une VM :
    # « code=PCC&latest » sert maintenant pycharm-2025.3, le build unifié, qui
    # s'arrête sur sa licence — son journal dit « NoValidIdeLicense » puis
    # « Get licenses: request requires authentication », et le projet ne
    # s'ouvre jamais. Aucune ouverture, donc aucun .idea, donc rien à
    # configurer ensuite. Community ne demande aucun compte, et elle est
    # toujours publiée et corrigée : 2025.2.6.2 date du 2026-07-29.
    #
    # Aucun numéro figé ici : on prend la plus récente archive
    # « pycharm-community- » du flux officiel des versions, pour
    # l'architecture de la VM.
    _QEMU_PYCHARM_FEED = (
        "https://data.services.jetbrains.com/products/releases"
        "?code=PCC&type=release"
    )
    # Repli quand le flux est injoignable : la redirection « dernière version ».
    # Elle sert le build unifié, donc on le DIT — l'utilisateur devra ouvrir un
    # compte JetBrains, et mieux vaut l'apprendre dans le journal qu'au premier
    # lancement.
    _QEMU_PYCHARM_URL = (
        "https://download.jetbrains.com/product?code=PCC&latest&distribution="
    )

    # Android Studio n'a PAS d'URL « latest » : le répertoire de version
    # (2026.1.3.8) et le nom de fichier (quail3-patch1) sont deux jetons
    # INDÉPENDANTS, l'un ne se déduit pas de l'autre, et le flux updates.xml de
    # Google ne publie ni l'un ni l'autre. On lit donc l'URL sur la page
    # officielle, qui la porte en clair, et on retombe sur celle-ci si la page
    # change de forme. Relevée et vérifiée (HTTP 200) le 2026-08-17.
    _QEMU_ANDROID_URL = (
        "https://dl.google.com/dl/android/studio/ide-zips/2026.1.3.8/"
        "android-studio-quail3-patch1-linux.tar.gz"
    )
    _QEMU_ANDROID_PAGE = "https://developer.android.com/studio"

    @staticmethod
    def _qemu_desktop_entry_cmd(name, label, exec_cmd, icon, categories):
        """Écrit un lanceur .desktop. Sans lui, un outil déplié dans /opt
        n'existe pas pour le bureau : il ne se lance qu'en tapant son chemin.
        """
        return (
            f"sudo tee /usr/share/applications/{name}.desktop >/dev/null <<DESK\n"
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            f"Name={label}\n"
            f"Exec={exec_cmd}\n"
            f"Icon={icon}\n"
            "Terminal=false\n"
            f"Categories={categories}\n"
            "StartupNotify=true\n"
            "DESK\n"
        )

    def _qemu_jetbrains_launcher_cmd(self, root, link, alias=""):
        """Lien vers le lanceur de l'archive, quel que soit son nom.

        JetBrains a renommé « bin/pycharm.sh » en « bin/pycharm » (et
        « studio.sh » en « studio ») : les deux existent selon la version, on
        prend celui qui est là.

        `alias` : un second nom pour la même commande. L'archive d'Android
        Studio n'installe que « studio », mais personne ne tape « studio » —
        on cherche « android-studio », on ne trouve rien, et on conclut que
        l'installation a échoué alors qu'elle est bien là. Vécu."""
        return (
            f"b=$(ls {root}/bin/{link}.sh {root}/bin/{link} 2>/dev/null "
            "| head -1); "
            f'[ -n "$b" ] && sudo ln -sf "$b" /usr/local/bin/{link}; '
            + (
                f'[ -n "$b" ] && sudo ln -sf "$b" /usr/local/bin/{alias}; '
                if alias
                else ""
            )
        )

    def _qemu_pycharm_remote_cmd(self, prod=False):
        """Installe PyCharm et lui donne le dépôt ERPLibre comme projet.

        « Configuré sur git/erplibre » veut dire deux choses, et les deux sont
        faites ici : le lanceur du bureau OUVRE ce dépôt, et
        pycharm_configuration.py y écrit le .idea/ du projet (interpréteur,
        configurations d'exécution, dossiers exclus) — la même chose que
        « make pycharm_configure », mais avec le python du venv d'outils, seul à
        disposer de xmltodict.

        Tout le bloc est gardé : un IDE qui ne s'installe pas ne doit pas faire
        échouer l'installation d'ERPLibre, qui elle a duré une heure."""
        el_dir = self._qemu_install_dir(prod)
        return (
            f'echo "== {t("Installing PyCharm (long)")} =="; '
            "{ "
            'case "$(uname -m)" in x86_64) jb=linux;; '
            'aarch64|arm64) jb=linuxARM64;; *) jb="";; esac; '
            # if/else et non « || { …; false; } » : dans un groupe, un échec
            # n'interrompt PAS la suite (set -e est suspendu à gauche d'un
            # « && »), et l'architecture non servie partait quand même
            # télécharger une URL sans valeur de distribution.
            'if [ -z "$jb" ]; then '
            f'echo "   {t("no JetBrains build for")} $(uname -m)"; false; '
            "else "
            # Déjà posé ? On ne retélécharge pas. Rejouer une
            # installation est le cas NORMAL — une qui est morte, un outil
            # ajouté après coup — et le téléchargement en est la partie
            # longue : mesuré, ~5 min pour Android Studio, autant pour
            # PyCharm. Le reste de l'étape (lanceur, alias, raccourci)
            # rejoue de toute façon, lui est idempotent et bon marché.
            "if [ -x /opt/pycharm/bin/pycharm.sh ]; then "
            f'echo "   {t("already there, download skipped")}"; '
            "else "
            # /var/tmp et non /tmp : sur Fedora et dérivés /tmp est un tmpfs, en
            # RAM — 1,2 Go d'archive y tueraient une VM de 3 Go.
            # Le flux dit quelle archive Community prendre pour cette
            # architecture. En python plutôt qu'en shell : il fait la requête,
            # lit le JSON et rend une ligne — sans jq, absent des images cloud.
            "url=$(python3 - \"$jb\" <<'ELPYJB'\n"
            "import json, sys, urllib.request\n"
            "key = sys.argv[1]\n"
            "try:\n"
            f'    with urllib.request.urlopen("{self._QEMU_PYCHARM_FEED}",\n'
            "                                 timeout=30) as fh:\n"
            "        data = json.load(fh)\n"
            "except Exception:\n"
            "    sys.exit(0)\n"
            'for rel in data.get("PCC", []):\n'
            '    link = (rel.get("downloads") or {}).get(key, {}).get("link", "")\n'
            '    if "pycharm-community-" in link:\n'
            "        print(link)\n"
            "        break\n"
            "ELPYJB\n"
            "); "
            'if [ -z "$url" ]; then '
            f'url="{self._QEMU_PYCHARM_URL}$jb"; '
            f'echo "   {t("release feed unreachable: unified build, it will ask for a JetBrains account")}"; '
            "fi; "
            "tmp=$(mktemp -p /var/tmp pycharm-XXXX.tar.gz) && "
            'curl -fsSL "$url" -o "$tmp" && '
            "sudo mkdir -p /opt/pycharm && "
            'sudo tar -xzf "$tmp" -C /opt/pycharm --strip-components=1; '
            'rc=$?; rm -f "$tmp"; [ $rc -eq 0 ]; fi; fi; } && { '
            + self._qemu_jetbrains_launcher_cmd("/opt/pycharm", "pycharm")
            + self._qemu_desktop_entry_cmd(
                "pycharm",
                "PyCharm (ERPLibre)",
                f"/usr/local/bin/pycharm {el_dir}",
                "/opt/pycharm/bin/pycharm.svg",
                "Development;IDE;",
            )
            # AUCUN appel à pycharm_configuration.py ici : l'installation
            # ERPLibre le fait déjà. update_env_version.pycharm_update() teste
            # « os.path.exists('.idea') » puis lance le script — une seule
            # autorité, et elle sait se taire quand le projet n'existe pas
            # encore. Doubler l'appel ne configurait rien de plus : ça écrivait
            # « Missing ./.idea path » dans le journal d'une VM neuve, où
            # PyCharm n'a évidemment jamais ouvert le dépôt.
            + f'echo "   {t("PyCharm installed:")} /opt/pycharm '
            f'({t("command")} pycharm, {t("project")} {el_dir})"; '
            f'echo "   {t("open the project once and close PyCharm; the .idea "
                          "it writes is what the install configures")}"; '
            f'}} || echo "   ⚠ {t("PyCharm not installed (see above)")}"; '
        )

    # Serveur X virtuel, par gestionnaire de paquets. Les noms ne se
    # ressemblent pas d'une famille à l'autre — relevés dans chaque dépôt, pas
    # devinés.
    _QEMU_XVFB_PKG = {
        "apt": "xvfb",
        "dnf": "xorg-x11-server-Xvfb",
        "zypper": "xorg-x11-server-Xvfb",
        "pacman": "xorg-server-xvfb",
    }

    # Attente maximale du .idea, en tours de 5 s — cinq minutes. Mesuré sur une
    # VM Ubuntu 26.04 à 16 Go : le projet est écrit en 195 s, indexation du
    # dépôt en cours. On n'attend donc PAS la fin de cette indexation, qui dure
    # bien plus et dont personne n'a besoin ici : pycharm_configuration.py ne
    # réclame que le .iml et misc.xml.
    _QEMU_PYCHARM_OPEN_TRIES = 60

    def _qemu_xvfb_install_cmd(self):
        """Pose Xvfb avec le gestionnaire de paquets présent, sans bruit."""
        x = self._QEMU_XVFB_PKG
        return (
            "if command -v apt-get >/dev/null 2>&1; then "
            "sudo DEBIAN_FRONTEND=noninteractive apt-get "
            f"-o DPkg::Lock::Timeout=600 install -y {x['apt']} "
            ">/dev/null 2>&1 || true; "
            "elif command -v dnf >/dev/null 2>&1; then "
            f"sudo dnf install -y {x['dnf']} >/dev/null 2>&1 || true; "
            "elif command -v zypper >/dev/null 2>&1; then "
            "sudo zypper --non-interactive install --auto-agree-with-licenses "
            f"{x['zypper']} >/dev/null 2>&1 || true; "
            "elif command -v pacman >/dev/null 2>&1; then "
            f"sudo pacman -S --needed --noconfirm {x['pacman']} "
            ">/dev/null 2>&1 || true; fi; "
        )

    def _qemu_pycharm_project_cmd(self, prod=False):
        """Crée le .idea/ du dépôt en ouvrant PyCharm une fois, sans écran.

        C'est PyCharm, et lui seul, qui écrit ce répertoire : ni le dépôt ni
        pycharm_configuration.py ne savent le fabriquer — ce dernier exige un
        .iml puis un misc.xml, et s'arrête sinon. Sans cette ouverture, l'étape
        pycharm_update() de l'installation ne trouve rien à configurer.

        Xvfb parce que l'IDE réclame un affichage, même pour ouvrir un projet
        et s'arrêter. Il tourne DANS la VM : l'hôte qui orchestre n'a besoin
        d'aucune bibliothèque graphique, et rien ne transite par « ssh -X ».

        TROIS fenêtres bloqueraient une session où personne ne peut cliquer, et
        chacune a été rencontrée avant d'être écartée : politique de
        confidentialité, partage de données, et surtout « faites-vous confiance
        à ce projet ? ». C'est celle-là qui figeait tout — le journal s'arrêtait
        1,3 s après le démarrage, sans jamais ouvrir le projet, et il a fallu
        « idea.trust.all.projects » pour le débloquer. Le consentement, lui, est
        écrit REFUSÉ : aucune statistique ne part.

        Mesuré sur une VM Ubuntu 26.04 à 16 Go : .idea complet en 195 s, et
        pycharm_configuration.py écrit ensuite ses exclusions dans le .iml.

        Tout est gardé. Sans Xvfb, sans PyCharm, ou sans .idea au bout du
        délai, on le dit et l'installation continue : elle n'en dépend pas,
        elle en profite seulement.
        """
        el_dir = self._qemu_install_dir(prod)
        return (
            f'echo "== {t("Creating the PyCharm project (first open)")} =="; '
            "{ if ! command -v pycharm >/dev/null 2>&1; then "
            f'echo "   {t("PyCharm missing, step skipped")}"; false; '
            "else "
            "command -v xvfb-run >/dev/null 2>&1 || { "
            + self._qemu_xvfb_install_cmd()
            + "}; "
            "if ! command -v xvfb-run >/dev/null 2>&1; then "
            f'echo "   {t("no Xvfb here, open PyCharm by hand")}"; false; '
            "else "
            # Réponses aux fenêtres de première ouverture. En python plutôt
            # qu'en shell : l'horodatage en millisecondes et le « <!--…--> » de
            # la propriété se passeraient mal de guillemets imbriqués.
            "python3 - <<'ELPYC' || true\n"
            "import pathlib, time\n"
            "h = pathlib.Path.home()\n"
            'c = h / ".local/share/JetBrains/consentOptions"\n'
            "c.mkdir(parents=True, exist_ok=True)\n"
            '(c / "accepted").write_text(\n'
            '    "rsch.send.usage.stat:1.1:0:%d\\n" % (time.time() * 1000)\n'
            ")\n"
            '(h / ".pycharm-headless.vmoptions").write_text(\n'
            '    "-Djb.privacy.policy.text=<!--999.999-->\\n"\n'
            '    "-Djb.consents.confirmation.enabled=false\\n"\n'
            '    "-Didea.trust.all.projects=true\\n"\n'
            '    "-Didea.suppress.statistics.report=true\\n"\n'
            ")\n"
            "ELPYC\n"
            # « setsid » donne au tout son PROPRE groupe de processus, et
            # c'est le groupe qu'on tuera. Sans lui, « $!  » est le PID de
            # xvfb-run — un script — et le tuer n'atteint ni PyCharm, ni Xvfb,
            # ni les cef_server qu'il a lancés. Mesuré sur
            # erplibre-ubuntu-2604-gnome : PyCharm tournait encore 45 minutes
            # plus tard avec 1,9 Go, et la compilation de l'APK qui suivait
            # s'est fait tuer par le noyau, faute de mémoire.
            # Les watches inotify AVANT d'ouvrir : le dépôt mobile pose
            # 123 000 fichiers d'assets, et la limite par défaut est dépassée
            # dès l'analyse — « inotify_add_watch(...): No space left on
            # device », puis « watch root cannot be watched: -2 », puis aucun
            # .idea écrit. Mesuré sur erplibre-ubuntu-2604-gnome, deux fois.
            # 524288 est la valeur que JetBrains documente lui-même.
            "cur=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null "
            '|| echo 0); if [ "$cur" -lt 524288 ] 2>/dev/null; then '
            'echo "fs.inotify.max_user_watches=524288" '
            "| sudo tee /etc/sysctl.d/60-erplibre-inotify.conf >/dev/null && "
            "sudo sysctl -q -p /etc/sysctl.d/60-erplibre-inotify.conf "
            f'2>/dev/null; echo "   {t("inotify watches raised for the IDE")}"; '
            "fi; "
            # DEUX tentatives, et c'est mesuré : la première ouverture d'un
            # dépôt neuf indexe 212 000 fichiers, plante son configurateur
            # d'interpréteur (« PythonSdkConfigurator - homeDir is null ») et
            # n'écrit AUCUN .idea, même au bout de cinq minutes. La seconde, sur
            # les caches que la première a laissés, l'écrit en 25 secondes —
            # constaté sur deux VM différentes.
            ": > /tmp/pycharm-first-run.log; "
            "for attempt in 1 2; do "
            'PYCHARM_VM_OPTIONS="$HOME/.pycharm-headless.vmoptions" '
            f"setsid xvfb-run -a pycharm {el_dir} "
            ">> /tmp/pycharm-first-run.log 2>&1 & "
            "pid=$!; ok=0; "
            f"for i in $(seq 1 {self._QEMU_PYCHARM_OPEN_TRIES}); do "
            f"if ls {el_dir}/.idea/*.iml >/dev/null 2>&1 && "
            f"[ -f {el_dir}/.idea/misc.xml ]; then ok=1; break; fi; "
            "sleep 5; done; "
            # Cinq secondes de plus : les fichiers apparaissent PENDANT leur
            # écriture, et un TERM à l'instant où misc.xml naît le tronquerait.
            "sleep 5; kill -TERM -$pid 2>/dev/null || "
            "kill -TERM $pid 2>/dev/null; "
            "for i in $(seq 1 12); do kill -0 -$pid 2>/dev/null || break; "
            "sleep 5; done; kill -KILL -$pid 2>/dev/null; "
            # Filet, et il a sa raison d'être : ce qui survit ici mange la
            # mémoire de TOUTES les étapes suivantes.
            #
            # Par NOM de processus (« -x »), jamais par ligne de commande. Un
            # « pkill -f /opt/pycharm » attrape aussi le ssh QUI PORTE cette
            # installation — sa ligne de commande contient le script entier,
            # donc ce chemin. Vécu : une installation est morte en silence, sa
            # session ssh emportée, 48 minutes perdues. Mesuré ensuite : par
            # nom, 3 processus réels attrapés et 0 faux ; par ligne de commande,
            # 4 dont le ssh. Les noms sont ceux relevés dans la VM — pycharm,
            # Xvfb, fsnotifier, cef_server — et « -u » borne au compte courant.
            #
            # « pgrep -c » IMPRIME 0 et rend 1 quand il ne trouve rien : un
            # « || echo 0 » donnerait « 0\n0 », qui n'est pas « 0 ». « wc -l »
            # rend un seul nombre et un code 0.
            'left=$(pgrep -u "$(id -u)" -x '
            '"pycharm|cef_server|fsnotifier|Xvfb" 2>/dev/null | wc -l); '
            '[ "$left" = 0 ] || { '
            f'echo "   {t("closing what survived the first open:")} $left"; '
            'pkill -u "$(id -u)" -x '
            '"pycharm|cef_server|fsnotifier|Xvfb" 2>/dev/null; sleep 2; }; '
            '[ "$ok" = 1 ] && break; '
            f'echo "   {t("no project yet, second try on the warm caches")}"; '
            "done; "
            '[ "$ok" = 1 ]; fi; fi; } && '
            f'echo "   {t("project created, the install will configure it")}" '
            f'|| echo "   ⚠ {t("no .idea: open PyCharm once, then")} '
            'make pycharm_configure"; '
        )

    def _qemu_android_studio_remote_cmd(self):
        """Installe Android Studio, pour le développement mobile ERPLibre.

        L'émulateur, lui, exige KVM DANS la VM, donc la virtualisation
        imbriquée : on le dit plutôt que de laisser découvrir l'échec au premier
        lancement. Compiler et déployer sur un appareil réel par adb n'en
        dépendent pas."""
        return (
            f'echo "== {t("Installing Android Studio (long)")} =="; '
            "{ "
            'if [ "$(uname -m)" != x86_64 ]; then '
            f'echo "   {t("Android Studio: Google publishes x86_64 only")}"; '
            "false; "
            "else "
            # Déjà posé ? On ne retélécharge pas. Rejouer une
            # installation est le cas NORMAL — une qui est morte, un outil
            # ajouté après coup — et le téléchargement en est la partie
            # longue : mesuré, ~5 min pour Android Studio, autant pour
            # PyCharm. Le reste de l'étape (lanceur, alias, raccourci)
            # rejoue de toute façon, lui est idempotent et bon marché.
            "if [ -x /opt/android-studio/bin/studio ]; then "
            f'echo "   {t("already there, download skipped")}"; '
            "else "
            # La page officielle porte l'URL en clair ; le repli garde une
            # version connue qui répond, pour le jour où sa forme change.
            f"url=$(curl -fsSL --max-time 30 {self._QEMU_ANDROID_PAGE} "
            "| grep -oE 'https://[a-z0-9.-]*gvt1\\.com/[^\"]*linux\\.tar\\.gz' "
            "| head -1); "
            f'[ -n "$url" ] || url="{self._QEMU_ANDROID_URL}"; '
            "tmp=$(mktemp -p /var/tmp android-XXXX.tar.gz) && "
            'curl -fsSL "$url" -o "$tmp" && '
            "sudo mkdir -p /opt/android-studio && "
            'sudo tar -xzf "$tmp" -C /opt/android-studio '
            "--strip-components=1; "
            'rc=$?; rm -f "$tmp"; [ $rc -eq 0 ]; fi; fi; } && { '
            + self._qemu_jetbrains_launcher_cmd(
                "/opt/android-studio", "studio", alias="android-studio"
            )
            + self._qemu_desktop_entry_cmd(
                "android-studio",
                "Android Studio",
                "/usr/local/bin/studio",
                "/opt/android-studio/bin/studio.svg",
                "Development;IDE;",
            )
            +
            # Le SDK partagé, vu depuis la SESSION graphique. install-android.sh
            # écrit ses exports dans ~/.bashrc, que GNOME ne lit pas : Android
            # Studio lancé depuis le menu ne verrait donc pas le SDK et
            # proposerait d'en télécharger un second. environment.d est le
            # canal que la session utilisateur lit vraiment.
            "mkdir -p ~/.config/environment.d && "
            "printf 'ANDROID_HOME=%s/android\\nANDROID_SDK_ROOT=%s/android\\n'"
            ' "$HOME" "$HOME" '
            "> ~/.config/environment.d/10-erplibre-android.conf; "
            # repositories.cfg absent, et l'assistant de première ouverture
            # s'arrête sur une erreur au lieu de proposer quoi que ce soit.
            "mkdir -p ~/.android && touch ~/.android/repositories.cfg; "
            + f'echo "   {t("Android Studio installed:")} /opt/android-studio '
            f'({t("command")} studio / android-studio)"; '
            f'echo "   {t("SDK shared through ANDROID_HOME:")} $HOME/android"; '
            "grep -q vmx /proc/cpuinfo 2>/dev/null "
            "|| grep -q svm /proc/cpuinfo 2>/dev/null "
            f'|| echo "   {t("no nested KVM: the emulator will not run")}"; '
            f'}} || echo "   ⚠ {t("Android Studio not installed (see above)")}"; '
        )

    # Extensions GNOME suggérées, par gestionnaire de paquets. Les noms ne sont
    # pas les mêmes d'une famille à l'autre (« dashtodock » sur Debian,
    # « dash-to-dock » sur Fedora), et aucune liste n'existe en entier partout.
    #
    # D'où l'installation UNE PAR UNE : apt, dnf, zypper et pacman échouent tous
    # sur la commande ENTIÈRE dès qu'un seul nom est inconnu. Un paquet absent
    # est donc annoncé et sauté, au lieu de faire tomber les autres avec lui.
    _QEMU_GNOME_EXT_PKGS = {
        "apt": (
            "gnome-shell-extension-manager",
            "gnome-tweaks",
            "gnome-shell-extensions",
            "gnome-shell-extension-dashtodock",
            "gnome-shell-extension-appindicator",
            "gnome-shell-extension-caffeine",
        ),
        "dnf": (
            "gnome-extensions-app",
            "gnome-tweaks",
            "gnome-shell-extension-dash-to-dock",
            "gnome-shell-extension-appindicator",
            "gnome-shell-extension-caffeine",
            "gnome-shell-extension-user-theme",
        ),
        "zypper": (
            "gnome-shell-extensions",
            "gnome-tweaks",
            "gnome-shell-extension-dash-to-dock",
            "gnome-shell-extension-appindicator",
        ),
        "pacman": (
            "extension-manager",
            "gnome-tweaks",
            "gnome-shell-extensions",
        ),
    }

    # Extensions demandées nommément, par leur UUID sur extensions.gnome.org.
    # Aucune n'est empaquetée par une distribution : on passe donc par le site.
    #
    # L'archive dépend de la version de GNOME Shell, et ce n'est pas une
    # précaution de principe : mesuré le 2026-08-17, le même point d'entrée
    # sert gTile v59 pour GNOME 46, v62 pour GNOME 48 et v52 pour GNOME 3.38.
    # Une URL figée poserait donc, tôt ou tard, une archive faite pour une
    # autre version.
    #
    # Ce que le site fait d'une version qu'il ne connaît PAS : il sert la plus
    # récente (vérifié — « shell_version=99 » rend l'archive des GNOME 49/50),
    # il ne répond pas 404. Sans conséquence fâcheuse pour autant : GNOME Shell
    # refuse de CHARGER une extension dont metadata.json ne déclare pas la
    # version courante. Une archive mal appariée reste donc inerte et affichée
    # « obsolète » dans le gestionnaire — elle ne casse pas la session.
    _QEMU_GNOME_EXT_UUIDS = (
        "gTile@vibou",
        "freon@UshakovVasilii_Github.yahoo.com",
        "tracker@aliakseiz.github.com",
    )
    _QEMU_GNOME_EXT_SITE = "https://extensions.gnome.org/download-extension"

    def _qemu_gnome_ext_site_cmd(self):
        """Installe les extensions nommées depuis extensions.gnome.org.

        Celles-là, on les ACTIVE — à la différence des paquets de la
        distribution, dont on ne connaît pas l'UUID. Deux raisons, l'une et
        l'autre vérifiées : le site rend l'archive faite pour le GNOME Shell de
        cette VM, et une archive mal appariée n'est de toute façon jamais
        chargée par GNOME, qui compare metadata.json à sa propre version. Ce
        n'est donc pas l'activation qui peut casser une session.

        Le tout dans un groupe gardé : ni une panne de réseau ni une extension
        retirée du site ne doivent faire échouer une installation d'une heure.
        """
        uuids = " ".join(self._QEMU_GNOME_EXT_UUIDS)
        site = self._QEMU_GNOME_EXT_SITE
        return (
            "{ "
            # « gnome-shell --version » rend « GNOME Shell 48.2 » : le dernier
            # champ suffit, et évite une expression régulière à rallonge.
            "v=$(gnome-shell --version 2>/dev/null | awk '{print $NF}'); "
            'if [ -z "$v" ]; then '
            + f'echo "   {t("GNOME Shell not found, site extensions skipped")}"; '
            + "else "
            # Le site attend le numéro MAJEUR depuis GNOME 40 (« 48 ») et
            # « majeur.mineur » avant (« 3.38 ») : sans la bonne forme, il ne
            # renvoie aucune archive.
            "maj=${v%%.*}; "
            'if [ "$maj" -ge 40 ] 2>/dev/null; then sv="$maj"; '
            'else sv=$(echo "$v" | cut -d. -f1,2); fi; '
            # gnome-extensions écrit dans ~/.local/share, mais l'activation
            # passe par GSettings : sans bus de session — le cas d'un
            # « ssh hôte commande » — dconf ne peut rien écrire.
            # dbus-run-session en fournit un le temps de l'appel, et
            # l'écriture atterrit bien dans le dconf de l'utilisateur.
            'gx() { if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] && '
            "command -v dbus-run-session >/dev/null 2>&1; then "
            'dbus-run-session -- gnome-extensions "$@"; '
            'else gnome-extensions "$@"; fi; }; ' + f"for u in {uuids}; do "
            # « || echo » DANS la substitution : un mktemp qui échoue rendrait
            # l'affectation non nulle, et « set -e » couperait toute la suite.
            + "z=$(mktemp -p /var/tmp gext-XXXX.zip || echo /var/tmp/gext.zip); "
            + 'if curl -fsSL --max-time 120 "'
            + site
            + '/$u.shell-extension.zip?shell_version=$sv" -o "$z" '
            + '&& gx install --force "$z" >/dev/null 2>&1; then '
            + 'gx enable "$u" >/dev/null 2>&1 || true; '
            + f'echo "   {t("installed and enabled:")} $u"; else '
            + f'echo "   {t("not available for this GNOME, skipped:")} '
            + '$u (GNOME $sv)"; fi; rm -f "$z"; done; '
            + f'echo "   {t("log out and back in to load them")}"; '
            + "fi; } || true; "
        )

    def _qemu_gnome_ext_remote_cmd(self):
        """Pose les extensions GNOME suggérées.

        Deux sources, et deux politiques, pour une raison :
          - les paquets de la DISTRIBUTION sont installés sans être activés. On
            ne connaît pas leur UUID de façon fiable, et activer à l'aveugle une
            extension incompatible avec la version de GNOME Shell laisse la
            session sur un écran noir — panne qu'on ne diagnostique pas depuis
            une console série. Le gestionnaire graphique est posé pour choisir ;
          - les extensions nommées par leur UUID sont, elles, ACTIVÉES : le site
            rend l'archive faite pour ce GNOME-là, et une archive mal appariée
            n'est jamais chargée par GNOME plutôt que de casser la session.
        """
        pkgs = self._QEMU_GNOME_EXT_PKGS
        return (
            f'echo "== {t("Suggested GNOME extensions")} =="; '
            "if command -v apt-get >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['apt'])}'; "
            "I='sudo DEBIAN_FRONTEND=noninteractive apt-get "
            "-o DPkg::Lock::Timeout=600 install -y'; "
            "elif command -v dnf >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['dnf'])}'; I='sudo dnf install -y'; "
            "elif command -v zypper >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['zypper'])}'; "
            "I='sudo zypper --non-interactive install "
            "--auto-agree-with-licenses'; "
            "elif command -v pacman >/dev/null 2>&1; then "
            f"EXT='{' '.join(pkgs['pacman'])}'; "
            "I='sudo pacman -S --needed --noconfirm'; "
            'else EXT=""; fi; '
            'for p in $EXT; do $I "$p" >/dev/null 2>&1 '
            f'|| echo "   {t("not in the repos, skipped:")} $p"; done; '
            f'echo "   {t("Enable them from Extension Manager, or:")} '
            'gnome-extensions enable <uuid>"; '
            + self._qemu_gnome_ext_site_cmd()
        )

    # Diagnostic de la compilation mobile : motif rencontré dans le journal
    # détaillé -> cause nommée. Du plus précis au plus général, le premier qui
    # correspond gagne.
    #
    # Cette liste est faite pour GRANDIR. Une compilation Android échoue de
    # cent façons, et le journal fait des dizaines de mégaoctets : sans cette
    # traduction, « la VM est rouge » n'apprend rien et il faut tout rouvrir.
    # Chaque panne rencontrée sur une VM mérite d'y laisser sa ligne.
    _QEMU_MOBILE_DIAG = (
        ("No space left on device", "disk full"),
        ("Failed to find target with hash string", "SDK platform missing"),
        ("SDK location not found", "SDK not found (ANDROID_HOME)"),
        ("have not been accepted", "SDK licences not accepted"),
        ("NDK not configured", "NDK missing"),
        # Vécu : Capacitor 8 réclame un JDK 21 quand l'installateur amont pose
        # un 17, et Gradle s'arrête là.
        (
            "Cannot find a Java installation",
            "JDK required by the project missing",
        ),
        # Vécu aussi : le JDK est là, mais Gradle TOURNE sur un plus ancien.
        ("invalid source release", "Gradle running on too old a JDK"),
        ("cannot overwrite", "SDK already there (upstream installer replays)"),
        # Vécu : sentencepiece bâtit protoc pour la CIBLE et l'exécute sur
        # l'hôte. Le message est cryptique ; la cause, non.
        ("Exec format error", "cross-compiled protoc run on the host"),
        ("Unsupported class file major version", "JDK/Gradle mismatch"),
        ("Could not determine java version", "JDK/Gradle mismatch"),
        (
            "Could not resolve all files for configuration",
            "Gradle dependency unreachable (network?)",
        ),
        ("npm ERR!", "npm dependencies"),
        ("Test Files", "Vitest tests failed"),
        # Vécu : le manifeste rend 0 sans avoir cloné, et l'étape suivante
        # tombe sur un cd impossible. Le motif nomme la vraie cause.
        #
        # SANS APOSTROPHE, et ce n'est pas cosmétique : ces motifs partent dans
        # un « grep -q '<motif>' », entre apostrophes. « can't cd to » fermait
        # la chaîne et rendait tout le bloc invalide — attrapé par bash -n.
        ("cd: can", "mobile repository missing"),
        # Vécu aussi : sans python3.12-venv, .venv.erplibre n'existe pas, et
        # rien de ce qui suit ne peut synchroniser le manifeste.
        ("virtual environment", "ERPLibre venv missing (incomplete install)"),
        ("No module named", "ERPLibre venv incomplete (no pip: python3-venv)"),
        # Vécu sur erplibre-ubuntu-2604-gnome : le noyau a tué le démon Gradle
        # (6,8 Go de RSS sur 12 Go, sans swap), et Gradle n'en sait rien — il
        # dit seulement que son démon « a disparu ». Le motif nomme la mémoire,
        # et le contexte l'établit au lieu de le supposer.
        # Vécu, et c'est en amont : « Too many zip entries 123678 (MAX=65535) ».
        # Un APK est un ZIP classique, borné à 65 535 entrées, et le dépôt
        # mobile embarque 122 684 fichiers sous assets/public/repos — des
        # dépôts Odoo entiers — pour 337 fichiers qui sont l'application. Rien
        # ici ne peut le corriger : c'est au projet mobile de ne pas les
        # empaqueter. On le NOMME, avec le chiffre, plutôt que de laisser lire
        # 5 000 lignes de Gradle.
        (
            "Too many zip entries",
            "too many asset files for one APK (ZIP limit: 65535 entries)",
        ),
        ("daemon disappeared", "Gradle daemon killed: out of memory", "mmem"),
        ("Cannot allocate memory", "out of memory", "mmem"),
        ("Java heap space", "Gradle heap too small", "mmem"),
        ("FAILED", "Gradle task failed"),
    )

    def _qemu_mobile_diag_cmd(self):
        """Fonction shell qui NOMME la cause d'un échec, à partir du journal.

        Un « la VM est rouge » n'apprend rien quand le journal fait des dizaines
        de mégaoctets. On cherche donc les motifs connus, et à défaut on montre
        les dernières lignes — c'est toujours mieux que rien.

        La recherche porte sur la FIN du journal, pas sur tout. Vécu : le
        diagnostic a annoncé « licences SDK non acceptées » quand la panne était
        un JDK manquant — le motif venait de la revue de licences d'une étape
        RÉUSSIE, trois étapes plus haut. Nommer la mauvaise cause coûte plus
        cher que se taire."""
        lines = ""
        for entry in self._QEMU_MOBILE_DIAG:
            pat, cause = entry[0], entry[1]
            extra = f"{entry[2]}; " if len(entry) > 2 else ""
            lines += (
                f"grep -q '{pat}' \"$d\" && {{ "
                f'echo "   {t("probable cause:")} {t(cause)}"; '
                f'{extra}rm -f "$d"; return 0; }}; '
            )
        return (
            # Le contexte mémoire, lu dans /proc et dans le journal du noyau :
            # une cause « mémoire » se PROUVE, l'affirmer sans le compte de
            # l'oom-killer serait une supposition de plus. Pas d'awk ni de sed
            # ici : leurs programmes demandent des guillemets, et tout ceci
            # voyage déjà dans un ssh entre apostrophes.
            "mmem() { m=$(grep MemTotal /proc/meminfo | tr -dc 0-9); "
            "w=$(grep SwapTotal /proc/meminfo | tr -dc 0-9); "
            "k=$(sudo dmesg 2>/dev/null | grep -c oom-kill); "
            f'echo "   {t("memory:")} $((m/1024)) {t("MB RAM,")} '
            f'$((w/1024)) {t("MB swap, kernel OOM kills:")} $k"; }}; '
            'mdiag() { d=$(mktemp); tail -400 "$1" > "$d"; '
            + lines
            + f'echo "   {t("no known pattern, last lines:")}"; '
            'tail -12 "$1" | sed "s/^/     /"; rm -f "$d"; }; '
        )

    def _qemu_android_prologue_cmd(self):
        """Ce que la compilation mobile et l'émulateur partagent : le journal
        détaillé, le coureur d'étapes, le diagnostic, et l'environnement du SDK.

        Écrit UNE fois même quand les deux options sont cochées — deux
        prologues, ce serait deux journaux et deux SDK."""
        return (
            self._qemu_mobile_diag_cmd() +
            # Le détail va dans un fichier À PART. Une compilation Gradle écrit
            # des dizaines de milliers de lignes, dont des centaines portant le
            # mot « error » sans qu'aucune ne soit une panne : les verser dans
            # le journal d'installation rendrait son compteur d'erreurs
            # inutilisable, et le diagnostic illisible.
            'M="$HOME/erplibre-mobile-build.log"; : > "$M"; '
            f'echo "   {t("detailed log in the VM:")} $M"; '
            'mstep() { lbl="$1"; shift; echo "   -> $lbl"; '
            'if sh -c "$*" >> "$M" 2>&1; then return 0; fi; '
            f'echo "   ⚠ {t("FAILED:")} $lbl"; mdiag "$M"; return 1; }}; '
            # Le SDK vit dans $HOME/android, l'emplacement qu'emploie
            # l'installateur du dépôt. Android Studio, s'il est là, le trouvera
            # par ANDROID_HOME : un seul SDK sur la machine, pas deux.
            'export ANDROID_HOME="$HOME/android"; '
            'export ANDROID_SDK_ROOT="$HOME/android"; '
            'export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin'
            ':$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator"; '
            # ~/.bashrc n'est pas lu par un « ssh hôte commande » : ce que
            # l'installateur y écrit ne sert qu'aux sessions futures, pas à la
            # compilation qui suit immédiatement.
            #
            # Le JDK le PLUS RÉCENT installé, et non celui des alternatives.
            # Mesuré : avec JAVA_HOME sur le 17 que pose l'installateur amont,
            # Gradle tourne en 17 et s'arrête sur « invalid source release: 21 »
            # — les modules de Capacitor 8 compilent en 21. Le tri est
            # « sort -V », donc java-21 passe après java-17, pas avant.
            "export JAVA_HOME=$(ls -d /usr/lib/jvm/java-*-openjdk-* "
            "2>/dev/null | sort -V | tail -1); "
            '[ -n "$JAVA_HOME" ] || export JAVA_HOME=$(dirname $(dirname '
            "$(readlink -f $(command -v javac 2>/dev/null "
            "|| command -v java 2>/dev/null) 2>/dev/null) 2>/dev/null) "
            "2>/dev/null); "
            'export PATH="$JAVA_HOME/bin:$PATH"; '
        )

    def _qemu_android_sdk_steps(self, el_dir):
        """Les étapes qui posent le SDK : dépôt mobile, prérequis, installateur
        amont, plateforme réclamée par le projet. Communes aux deux options."""
        return (
            # Le « test -f » n'est pas une ceinture de plus : c'est la seule
            # vérité disponible. update_manifest_local_mobile.sh finit par
            # « kill $DAEMON_PID » et rend donc 0 même quand il n'a rien cloné —
            # vécu, faute de .venv.erplibre. L'étape passait, et c'est le « cd »
            # suivant qui échouait, deux étapes plus loin.
            # Le venv d'ERPLibre d'abord, et nommément : tout ce qui suit en
            # dépend — c'est lui qui porte « repo », qui synchronise le
            # manifeste. Vécu avec le profil « ERPLibre seul », dont le code
            # note lui-même « problem installing with q, the script depend on
            # odoo » : sans venv, le manifeste rendait 0 sans rien cloner et
            # l'échec ne se voyait que deux étapes plus loin.
            f'mstep "{t("ERPLibre venv (everything below needs it)")}" '
            # « activate », et non « bin/python » : sans python3-venv, le venv
            # naît INFIRME — bin/python existe (un lien), mais ni pip ni
            # activate ni site-packages. La sonde passait, et l'échec ne se
            # voyait que deux étapes plus loin, en « No module named git ».
            f"'test -f {el_dir}/.venv.erplibre/bin/activate' && "
            f'mstep "{t("mobile repository (additive manifest)")}" '
            f"'cd {el_dir} && ./script/manifest/update_manifest_local_mobile.sh; "
            "test -f mobile/erplibre_home_mobile/install-android.sh' && "
            f'mstep "{t("prerequisites of the upstream installer")}" '
            # libpulse0 : l'émulateur a DEUX binaires qemu, et seul le
            # « headless » se passe de PulseAudio. Celui qui ouvre une FENÊTRE —
            # le cas d'un « ssh -X » — lie libpulse.so.0, absente des images
            # cloud, et s'arrête sur « cannot open shared object file » même
            # avec « -no-audio ». Mesuré : c'est la SEULE bibliothèque qui
            # manque, tout le reste des dépendances Qt voyage dans le bundle.
            #
            # openjdk-21 EN PLUS du 17 que pose l'installateur amont : mesuré,
            # Gradle s'arrête sur « Cannot find a Java installation matching
            # {languageVersion=21} » — les modules de Capacitor 8 réclament 21.
            # Les deux JDK cohabitent, et Gradle choisit par sa chaîne d'outils.
            # unzip et xauth, eux, manquent des images cloud.
            "'sudo DEBIAN_FRONTEND=noninteractive apt-get "
            "-o DPkg::Lock::Timeout=600 install -y unzip wget xauth "
            "libpulse0 openjdk-21-jdk' && "
            # L'installateur amont n'est PAS idempotent : au second passage il
            # s'arrête sur « mv: cannot overwrite latest/cmdline-tools ». Mesuré.
            # On ne le rejoue donc que s'il reste quelque chose à poser — un
            # déploiement qui se répète ne doit pas échouer sur une réussite
            # précédente.
            f'mstep "{t("Android SDK, licences, NDK")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && "
            "{ [ -x $HOME/android/cmdline-tools/latest/bin/sdkmanager ] "
            "|| ./install-android.sh; }' && "
            f'mstep "{t("SDK platform required by the project")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && "
            'v=$(sed -n "s/.*compileSdkVersion *= *\\([0-9]*\\).*/\\1/p" '
            'android/variables.gradle) && [ -n "$v" ] && '
            'yes | sdkmanager "platforms;android-$v" '
            '"build-tools;$v.0.0"\' && '
        )

    def _qemu_mobile_build_steps(self, el_dir):
        """Étapes de compilation de l'application mobile, puis ses tests.

        C'est la seule étape qui peut faire échouer la VM, et c'est voulu : une
        machine dont l'application ne compile pas n'est pas une machine prête.
        Le code de sortie remonte donc jusqu'au tableau de bord.

        Le dépôt mobile porte son propre installateur Android — JDK, outils en
        ligne de commande, licences acceptées, plateformes, NDK, whisper.cpp et
        sentencepiece. On l'appelle plutôt que de le réécrire : une seconde
        implémentation dériverait de la première sans prévenir. Deux choses lui
        manquent pourtant, et on les ajoute ici :
          - unzip et wget, qu'il suppose présents et qu'aucune image cloud ne
            livre ;
          - la plateforme que le projet réclame VRAIMENT. Son installateur pose
            android-34 quand android/variables.gradle demande compileSdk 36 ;
            plutôt que de figer 36 ici, on lit le chiffre dans le fichier.

        L'étape est bornée à apt (voir _QEMU_VM_TOOLS) : cet installateur
        commence par « sudo apt install openjdk-17-jdk » et s'arrête là
        ailleurs. La lever se fait dans ce script-là, pas ici.
        """
        return (
            # Du swap AVANT de compiler, et ce n'est pas de la prudence : le
            # démon Gradle a atteint 6,8 Go de RSS hors tas — son -Xmx1536m ne
            # le borne pas — sur une VM de 12 Go SANS swap, et le noyau l'a tué
            # deux fois de suite. « --max-workers=2 » n'y a rien changé :
            # mesuré, le pic est passé de 10,3 à 11,2 Go. C'est donc de la marge
            # qu'il faut, pas moins de parallélisme.
            #
            # Jamais bloquant : une image sur btrfs refuse un fichier d'échange
            # ordinaire, et une compilation qui tient en mémoire n'en a pas
            # besoin. On le dit et on continue.
            "w=$(grep SwapTotal /proc/meminfo | tr -dc 0-9); "
            'if [ "$w" -lt 2000000 ]; then '
            "if sudo fallocate -l 4G /swapfile-erplibre 2>/dev/null && "
            "sudo chmod 600 /swapfile-erplibre && "
            "sudo mkswap -q /swapfile-erplibre >/dev/null 2>&1 && "
            "sudo swapon /swapfile-erplibre 2>/dev/null; then "
            "grep -q swapfile-erplibre /etc/fstab 2>/dev/null || "
            'echo "/swapfile-erplibre none swap sw 0 0" '
            "| sudo tee -a /etc/fstab >/dev/null; "
            f'echo "   {t("4 GB of swap added for the build")}"; '
            "else sudo rm -f /swapfile-erplibre 2>/dev/null; "
            f'echo "   {t("no swap could be added; build may run short")}"; '
            "fi; fi; "
            f'mstep "{t("npm dependencies")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm ci' && "
            f'mstep "{t("web bundle (vite build)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm run build' && "
            # Le transfert des dépôts du manifeste DANS l'application est
            # vérifié, et son compte-rendu se lit dans le journal
            # d'installation — d'où l'appel HORS mstep, qui enverrait la sortie
            # dans le journal détaillé de la VM.
            #
            # Ces dépôts entrent en PACKS, et c'est ce qui rend la chose
            # possible : un APK est un ZIP borné à 65535 entrées, quand les
            # 139 dépôts pèsent plus de 116 000 fichiers. Un fichier par source
            # donnait « Too many zip entries 123678 (MAX=65535) » et rien du
            # tout ; regroupés, ils tiennent en 391 tranches — mesuré, avec
            # 3 002 entrées dans l'APK.
            #
            # Lié par « && » : un transfert vide fait échouer la VM, au même
            # titre qu'un APK manquant. Une application qui ne porte pas le code
            # qu'elle est censée montrer n'est pas l'application demandée.
            f'echo "   -> {t("repo transfer into the app")}" && '
            f"(cd {el_dir} && ./script/mobile/check_bundle_transfer.py"
            f" --workspace {el_dir}) && "
            f'mstep "{t("native sync (capacitor)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npx cap sync android' && "
            # UNE seule ABI, celle de la VM — qui est aussi celle de
            # l'émulateur. Deux raisons, la seconde décisive :
            #   - quatre ABI, c'est quatre fois la compilation de whisper.cpp
            #     et de sentencepiece, pour trois qui ne serviront jamais ici ;
            #   - sentencepiece bâtit son « protoc » POUR LA CIBLE puis tente de
            #     l'exécuter sur l'hôte. En arm64 cela donne « Exec format
            #     error » et la compilation s'arrête — mesuré. En x86_64 la
            #     cible et l'hôte coïncident, et le défaut ne se manifeste pas.
            #     Un APK arm64 demandera un correctif au projet mobile.
            f'mstep "{t("debug APK (gradle)")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile/android && "
            "./gradlew --no-daemon assembleDebug "
            "-Pandroid.injected.build.abi=x86_64' && "
            f'mstep "{t("Vitest tests")}" '
            f"'cd {el_dir}/mobile/erplibre_home_mobile && npm test' && "
            # L'APK est la preuve, pas le code de sortie de Gradle : une tâche
            # peut rendre 0 sans avoir rien produit.
            # DEUX emplacements, et il faut les deux. Avec une ABI injectée,
            # AGP écrit dans « intermediates/apk/debug » et non dans
            # « outputs/apk/debug » : mesuré, une compilation RÉUSSIE était
            # rapportée « aucun APK produit » parce que je ne regardais que le
            # second. Un contrôle qui cherche au mauvais endroit ne vaut pas
            # mieux que pas de contrôle.
            f"apk=$(ls {el_dir}/mobile/erplibre_home_mobile/android/app/build"
            "/outputs/apk/debug/*.apk "
            f"{el_dir}/mobile/erplibre_home_mobile/android/app/build"
            "/intermediates/apk/debug/*.apk 2>/dev/null | head -1); "
            'if [ -n "$apk" ]; then '
            f'echo "   ✅ {t("APK built:")} $apk"; '
            # Capacitor sert la même application dans un navigateur : sur une
            # VM graphique, c'est la voie de déverminage sans Android ni
            # émulateur. On la NOMME plutôt que d'imposer Chromium — sur
            # Ubuntu il n'existe qu'en snap, et snapd est justement coupé sur
            # ces VM. Le navigateur du bureau fait l'affaire.
            #
            # DANS la branche de succès, et c'est tout l'enjeu : placé après le
            # « fi », cet echo devenait la dernière commande du bloc et rendait
            # 0 — une VM sans APK repassait au vert.
            f'echo "   {t("browser debugging (no Android):")} '
            f"cd {el_dir}/mobile/erplibre_home_mobile "
            '&& npm start"; else '
            f'echo "   ⚠ {t("no APK produced")}"; false; fi'
        )

    def _qemu_avd_steps(self, el_dir):
        """Étapes créant un émulateur prêt à s'ouvrir depuis le poste de travail.

        Le modèle n'est pas figé : on demande au SDK la liste de ses profils et
        on retient le Pixel le plus récent au plus petit écran — ni Pro, ni XL,
        ni pliant, ni tablette. Sur un écran distant, chaque pixel traverse le
        réseau : le petit modèle n'est pas une coquetterie.

        L'image système suit la plateforme du projet, et redescend si elle n'est
        pas publiée — Google ne fournit pas d'image pour toutes les API.

        Le rendu est réglé en logiciel DANS la configuration de l'AVD plutôt
        qu'en option de lancement : par « ssh -X » il n'y a pas de GLX direct, et
        l'émulateur s'ouvrirait sur un écran noir. Ainsi « emulator -avd
        erplibre » suffit, sans rien à retenir.

        Le mode est « swangle » — ANGLE sur SwiftShader — et non
        « swiftshader_indirect », qui n'existe PLUS : l'émulateur 37.1 répond
        « Selected GPU option 'swiftshader_indirect' is not valid, switching to
        auto », puis « Your GPU drivers may have a bug », avant de retomber de
        lui-même sur swangle. Il fonctionnait, en affichant deux erreurs qui
        laissaient croire à une panne. Les modes valides sont exactement quatre,
        que « emulator -help-gpu » énumère : auto, host, swiftshader, swangle.
        """
        return (
            f'echo "   == {t("Android emulator (AVD)")} =="; '
            # KVM dans la VM : sans lui l'émulateur x86 refuse de démarrer. On
            # le dit ici, où c'est réparable (virtualisation imbriquée sur
            # l'hôte), plutôt qu'au premier lancement.
            "if [ ! -e /dev/kvm ]; then "
            f'echo "   ⚠ {t("no /dev/kvm: nested virtualisation is off on the host")}"; '
            "else "
            # /dev/kvm est en root:kvm 0660 : sans appartenir au groupe,
            # l'émulateur refuse de démarrer sur « ProbeKVM: This user doesn't
            # have permissions to use KVM ». Mesuré. L'appartenance ne prend
            # qu'à la prochaine session — ce qui tombe bien, la session utile
            # est justement celle du « ssh -X » qui viendra ensuite.
            "sudo usermod -aG kvm $(id -un) 2>/dev/null || true; "
            f'echo "   {t("user added to the kvm group (effective at next login)")}"; '
            "fi; "
            f'mstep "{t("emulator and system image")}" '
            '\'v=$(sed -n "s/.*compileSdkVersion *= *\\([0-9]*\\).*/\\1/p" '
            f"{el_dir}/mobile/erplibre_home_mobile/android/variables.gradle); "
            "for a in $v 36 35 34; do "
            'img="system-images;android-$a;google_apis;x86_64"; '
            'if yes | sdkmanager "emulator" "$img"; then '
            'echo "$img" > $HOME/.erplibre-avd-image; break; fi; done; '
            "test -s $HOME/.erplibre-avd-image' && "
            f'mstep "{t("Pixel profile, smallest screen")}" '
            # Le plus récent des Pixel simples : on trie sur le NUMÉRO, pas sur
            # l'ordre d'affichage, et on écarte les grands modèles.
            '\'avdmanager list device | grep -oE "pixel_[0-9]+a?" '
            '| grep -vE "pro|xl|fold|tablet" | sort -t_ -k2 -n | tail -1 '
            "> $HOME/.erplibre-avd-device; test -s $HOME/.erplibre-avd-device' && "
            f'mstep "{t("create the AVD")}" '
            "'img=$(cat $HOME/.erplibre-avd-image); "
            "dev=$(cat $HOME/.erplibre-avd-device); "
            'echo no | avdmanager create avd -n erplibre -k "$img" '
            '-d "$dev" --force && '
            # Rendu logiciel, écrit dans la config : par ssh -X il n'y a pas
            # de GLX direct, et « auto » donnerait un écran noir. Ces deux
            # clés-là SURVIVENT, elles ne viennent pas du profil du téléphone.
            #
            # L'écran, en revanche, ne s'écrit PAS ici : l'émulateur réécrit
            # config.ini depuis le profil Pixel au premier démarrage, et les
            # hw.lcd.* y étaient effacés — l'AVD repartait en 1080x2400
            # densité 420. C'est donc au LANCEMENT qu'il se règle, par
            # _QEMU_EMULATOR_FLAGS, et la commande affichée plus bas les porte.
            'printf "hw.gpu.enabled=yes\\nhw.gpu.mode=swangle\\n" '
            ">> $HOME/.android/avd/erplibre.avd/config.ini' && "
            f'echo "   ✅ {t("AVD ready:")} '
            "$(cat $HOME/.erplibre-avd-device) / "
            '$(cat $HOME/.erplibre-avd-image)"; '
            # La commande à copier, avec l'adresse déjà remplie : un émulateur
            # dont on ignore comment l'ouvrir ne sert à personne.
            "ip=$(hostname -I 2>/dev/null | awk '{print $1}'); "
            # Chemins ABSOLUS, et c'est le point : « ssh hôte 'commande' »
            # ne lit NI ~/.profile NI ~/.bashrc — Ubuntu place même un
            # « return » en tête du second pour les shells non interactifs.
            # Le PATH que l'installateur y écrit ne s'applique donc jamais
            # à ces commandes, et « emulator » y répond « command not
            # found ». Vécu, sur la ligne que ce message affichait lui-même.
            f'echo "   {t("open it from your workstation:")} '
            # « -XC » et non « -X » : la compression X11 change tout sur un
            # écran distant. Les autres drapeaux viennent de la même autorité
            # que le lancement du menu : écran réduit, densité qui va avec, et
            # pas d'instantané en attente si on tue l'émulateur.
            'ssh -XC erplibre@$ip \\"$HOME/android/emulator/emulator '
            f'-avd erplibre {self._QEMU_EMULATOR_FLAGS}\\""; '
            f'echo "   {t("then install the APK:")} '
            # « -t » : l'ABI injectée fait marquer l'APK « testOnly » par AGP,
            # et adb le refuse sans ce drapeau — « INSTALL_FAILED_TEST_ONLY ».
            # Mesuré sur l'émulateur.
            'ssh erplibre@$ip \\"$HOME/android/platform-tools/adb install -r -t '
            f"{el_dir}/mobile/erplibre_home_mobile/android/app/build"
            '/outputs/apk/debug/app-debug.apk\\""; '
            # La voie scrcpy, nommée ici parce que c'est la première
            # question qui vient après « ça se lance mais c'est lent » :
            # X11 transporte des pixels bruts, scrcpy un flux H.264 encodé
            # par l'appareil. Le détail du tunnel vit dans le menu
            # « Remote desktop tunnel », choix 4.
            + f'echo "   {t("smoother, without X11:")} TODO > Execute > Deploy > QEMU/KVM > tunnel > 4"'
        )

    def _qemu_forgejo_steps(self, el_dir):
        """Pose Forgejo dans la VM, par le script dédié du dépôt.

        Tout le travail est DANS le script — architecture, version, somme de
        contrôle, compte système, configuration, service, compte
        administrateur. Ce bloc ne fait que l'appeler : une seule autorité, et
        la même commande sert un déploiement de VM et une installation à la
        main sur une machine existante.

        Pas de garde, comme la compilation mobile : une VM dont la forge
        demandée n'existe pas n'est pas la VM demandée. Le script, lui, est
        rejouable — il ne retélécharge pas un binaire déjà en place et ne
        réécrit jamais une configuration existante.
        """
        return (
            f'echo "== {t("Forgejo (git forge)")} =="; '
            f"{el_dir}/script/forgejo/install_forgejo.sh"
        )

    def _qemu_after_remote_cmd(self, tools, prod=False):
        """Phase d'APRÈS l'installation : prologue commun, SDK commun, puis ce
        qui a été coché.

        Un seul prologue et un seul SDK même quand les deux options le sont :
        deux prologues, et le second tronquerait le journal détaillé du premier.

        Les groupes sont joints par « && » et non par « ; ». C'est ce qui fait
        qu'un APK manquant reste l'échec de la VM : collé par « ; », un
        émulateur créé avec succès effacerait le verdict de la compilation."""
        picked = [
            k
            for k in ("forgejo", "mobile", "avd")
            if k in (tools or ()) and k in self._QEMU_VM_TOOLS
        ]
        if not picked:
            return ""
        el_dir = self._qemu_install_dir(prod)
        parts = []
        # Forgejo d'abord : une minute, contre une heure pour le SDK et l'APK.
        # Un échec rapide se voit tôt plutôt qu'après le long.
        if "forgejo" in picked:
            parts.append(f"{{ {self._qemu_forgejo_steps(el_dir)}; }}")
        groups = []
        if "mobile" in picked:
            groups.append(self._qemu_mobile_build_steps(el_dir))
        if "avd" in picked:
            groups.append(self._qemu_avd_steps(el_dir))
        if groups:
            # UN seul prologue et un seul SDK même quand les deux options le
            # sont : deux prologues, et le second tronquerait le journal
            # détaillé du premier.
            parts.append(
                "{ "
                + f'echo "== {t("ERPLibre mobile, Android SDK (long)")} =="; '
                + self._qemu_android_prologue_cmd()
                + self._qemu_android_sdk_steps(el_dir)
                # Chaque groupe entre ACCOLADES. Sans elles, « && » ne lie que
                # la première commande du groupe suivant : mesuré, un APK
                # manquant laissait tourner l'émulateur puis rendait 0 — la VM
                # repassait au vert alors que rien n'avait compilé.
                + " && ".join(f"{{ {g}; }}" for g in groups)
                + "; }"
            )
        return " && ".join(parts) + "; "

    def _qemu_mobile_remote_cmd(self, prod=False):
        """Compilation mobile seule — la forme que testent les tests."""
        return self._qemu_after_remote_cmd(("mobile",), prod)

    def _qemu_avd_remote_cmd(self, prod=False):
        """Émulateur seul."""
        return self._qemu_after_remote_cmd(("avd",), prod)

    def _qemu_tools_remote_cmd(self, tools, prod=False, phase="before"):
        """Bloc des outils cochés pour cette PHASE, du plus utile au plus lourd.

        « before » : posé avant le clone. Chaque outil s'y garde lui-même —
        aucun ne fait échouer les autres, ni l'installation d'ERPLibre.

        « after » : la compilation mobile, qui vient après l'installation dont
        elle dépend, et qui elle NE se garde PAS. C'est le contrat demandé : une
        VM dont l'application ne compile pas doit être rouge."""
        if phase == "after":
            # Un seul bloc pour les deux options : voir _qemu_after_remote_cmd.
            return self._qemu_after_remote_cmd(tools, prod)
        blocks = {
            "gnome_ext": self._qemu_gnome_ext_remote_cmd,
            "pycharm": lambda: self._qemu_pycharm_remote_cmd(prod),
            "android": self._qemu_android_studio_remote_cmd,
        }
        return "".join(fn() for k, fn in blocks.items() if k in (tools or ()))

    def _qemu_editor_pkg(self):
        """Paquet de l'éditeur de l'hôte, à installer dans la VM.

        L'éditeur atteint déjà la VM par deux chemins, tous deux posés par
        deploy_qemu.py : « core.editor » dans son ~/.gitconfig, et la ligne
        « éditer le serveur » du guide de connexion. Encore faut-il que le
        binaire y soit — les images cloud n'ont ni nano ni vim garantis, et
        certaines n'ont même pas vi. On l'ajoute donc aux outils d'amorçage, avec
        curl, git et make, là où les dépôts viennent d'être rafraîchis.

        La table des éditeurs vit dans deploy_qemu.py : une seule autorité décide
        du paquet installé, de la commande affichée et de core.editor. Sans
        module importable, on n'installe rien plutôt que de deviner un nom."""
        try:
            mod = self._qemu_import_module()
            return mod.vm_editor(mod.invoking_home())[0]
        except Exception:
            return ""

    def _qemu_editor_suffix(self):
        """« vim » -> « vim » précédé d'une espace, rien du tout sinon.

        La liste des outils d'amorçage est une chaîne shell entre apostrophes :
        y concaténer une chaîne vide sans précaution laisserait une espace en
        trop, inoffensive mais visible dans chaque log d'installation."""
        pkg = self._qemu_editor_pkg()
        return f" {pkg}" if pkg else ""

    # mise ne publie de binaire que pour ces architectures : 46 assets à la
    # v2026.8.4, aucun s390x — son propre script d'installation refuse cette
    # plateforme. Ailleurs, le choix « mise » est sans objet et on reste sur
    # pyenv, ce que le formulaire et l'invite disent avant de déployer.
    QEMU_MISE_ARCHES = ("amd64", "arm64")

    def _qemu_mise_remote_cmd(self, python_provider):
        """Pose mise DANS la VM et fixe EL_PYTHON_PROVIDER pour l'installation.

        mise s'installe par défaut dans ~/.local/bin, qui n'est PAS dans le
        PATH d'un « ssh hôte 'commande' » : ni ~/.profile ni ~/.bashrc n'y sont
        lus. On le pose donc dans /usr/local/bin, présent dans le PATH par
        défaut — même raison que pour cargo et rustc.

        Sans mise utilisable, rien n'est écrit : lib_python_provider.sh
        retombe alors sur pyenv toute seule."""
        if python_provider == "pyenv":
            # Explicite : même si mise se trouvait déjà dans l'image, on ne
            # l'utilise pas. Sans cela le mode « auto » du dépôt le prendrait.
            return "export EL_PYTHON_PROVIDER=pyenv; "
        if python_provider != "mise":
            return ""
        return (
            f'echo "== {t("Installing mise (precompiled Python)")} =="; '
            "if command -v mise >/dev/null 2>&1; then "
            'echo "   mise: $(mise --version)"; '
            "else "
            # La variable est passée À sudo, pas exportée avant : « sudo -E »
            # dépend de env_reset dans sudoers et n'est pas garanti.
            "curl -fsSL https://mise.run "
            "| sudo MISE_INSTALL_PATH=/usr/local/bin/mise sh "
            '|| echo "   mise indisponible ici : pyenv prendra le relais"; '
            "fi; "
            # « auto », et non « mise » : si l'installation ci-dessus a échoué,
            # lib_python_provider.sh doit pouvoir retomber sur pyenv.
            "export EL_PYTHON_PROVIDER=auto; "
        )

    def _qemu_erplibre_remote_cmd(
        self,
        branch,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        tools=(),
    ):
        """Script exécuté DANS la VM. `branch` à None n'installe QUE le bureau
        — le choix graphique ne dépend pas d'ERPLibre, et une VM peut être
        voulue en bureau seul.

        `final_cmd` par défaut : install_os + install_odoo_18. `prod` :
        installe dans /opt/erplibre (au lieu de ~/git/erplibre) + service
        SELinux confiné. `desktop` : ajoute GNOME et son accès distant.
        `python_provider` : « mise » pour un CPython précompilé, sinon le
        comportement par défaut du dépôt (pyenv, qui compile). `tools` : outils
        de développement cochés (PyCharm, Android Studio, extensions GNOME),
        posés APRÈS ERPLibre — PyCharm a besoin du venv du dépôt pour écrire la
        configuration du projet."""
        if not branch:
            # Bureau seul : ni clone ni make, mais on garde le prologue —
            # attente de cloud-init et coupure des mises à jour automatiques,
            # sans quoi le verrou apt ferait échouer l'installation du bureau.
            if not desktop:
                return "true"
            # Les outils de la phase « after » vivent DANS le dépôt — la
            # compilation mobile, l'AVD, le script Forgejo. Sans clone, ils
            # n'existent pas ici. Les écarter en silence laissait croire qu'une
            # case cochée avait été honorée : on la NOMME.
            deferred = [
                k
                for k in (tools or ())
                if self._QEMU_VM_TOOLS.get(k, {}).get("phase") == "after"
            ]
            note = (
                f'echo "   ⚠ {t("needs the ERPLibre install, skipped:")}'
                f' {" ".join(deferred)}"; '
                if deferred
                else ""
            )
            return (
                "set -e; "
                + self._qemu_cloud_init_wait()
                + self._qemu_no_auto_upgrade(prod, app_store)
                + self._qemu_desktop_remote_cmd(desktop, app_store)
                + self._qemu_tools_remote_cmd(tools, prod)
                + note
            )
        if not final_cmd:
            final_cmd = f"make install_os && make {self.ERPLIBRE_ODOO_TARGET}"
        # Profils AVEC Odoo (install_odoo*) uniquement : après l'install, on
        # enregistre Odoo comme service systemd (enable + start). Pas pour
        # « ERPLibre seul », « mobile » ni « Déploiement ».
        if "install_odoo" in final_cmd:
            # Le snippet de service est une SUITE d'instructions séparées par
            # « ; ». Collé tel quel après « && », l'opérateur ne lie que la
            # première : tout le reste s'exécute même quand le make a échoué, et
            # comme « systemctl enable » réussit, la commande distante rend 0 —
            # l'install était rapportée ✅ alors qu'elle avait échoué. « set -e »
            # ne rattrape pas : il n'interrompt pas sur un maillon d'une liste
            # « && ». Les accolades font porter le && sur le bloc entier.
            svc = self._qemu_odoo_service_cmd(prod).strip().rstrip(";")
            final_cmd = f"{final_cmd} && {{ {svc}; }}"
        # VM de DÉVELOPPEMENT uniquement : couper les mises à jour automatiques.
        # Vécu sur erplibre-ubuntu-2404 : unattended-upgrades s'est déclenché en
        # pleine migration Odoo 12->13 et a redémarré le cluster PostgreSQL
        # (« received fast shutdown request » x3) -> OpenUpgrade a perdu sa
        # connexion et la base intermédiaire est restée à moitié migrée. Effet
        # secondaire bienvenu : les timers apt-daily ne tiennent plus le verrou
        # apt pendant l'installation. En PROD on ne touche à rien : les
        # correctifs de sécurité automatiques doivent rester actifs.
        no_auto_upgrade = self._qemu_no_auto_upgrade(prod, app_store)
        tools_cmd = self._qemu_tools_remote_cmd(tools, prod, "before")
        # La compilation mobile vient APRÈS l'installation : elle a besoin du
        # dépôt, du venv d'outils qui synchronise le manifeste, et de node que
        # « make install_os » installe. Liée par « && » et NON gardée, pour que
        # son échec soit celui de la VM.
        after_cmd = self._qemu_tools_remote_cmd(tools, prod, "after")
        # APRÈS le make, et c'est mesuré : sur un dépôt cloné mais pas installé,
        # PyCharm n'écrit AUCUN .idea — son configurateur d'interpréteur Python
        # échoue faute de venv, et il renonce. « ⚠ pas de .idea », deux fois de
        # suite sur erplibre-ubuntu-2604-gnome. Le même appel sur un dépôt
        # installé l'écrit en cinq minutes : erplibre.iml, misc.xml,
        # modules.xml, vcs.xml.
        #
        # On ouvre donc quand l'interpréteur existe, puis on demande la
        # configuration explicitement : l'installation est déjà passée, et
        # pycharm_update() n'avait alors rien à configurer.
        open_step = (
            self._qemu_pycharm_project_cmd(prod)
            # Le venv du dépôt, comme le fait update_env_version.
            # pycharm_update() : le script importe xmltodict, absent du python
            # système. Mesuré : « make pycharm_configure » s'arrêtait sur
            # « No module named 'xmltodict' ».
            + "./.venv.erplibre/bin/python "
            "./script/ide/pycharm_configuration.py --init || true; "
            if "pycharm" in (tools or ())
            else ""
        )
        # Le groupe de PyCharm rend toujours 0 — un bonus, pas une condition —
        # là où la phase mobile porte le verdict de la VM.
        chain = [final_cmd]
        if open_step:
            chain.append(f"{{ {open_step} }}")
        if after_cmd:
            chain.append(f"{{ {after_cmd} }}")
        install_chain = " && ".join(chain)
        return (
            "set -e; " + self._qemu_cloud_init_wait()
            # Coupé AVANT les apt-get ci-dessous : sinon apt-daily peut reprendre
            # le verrou entre l'attente cloud-init et l'installation.
            + no_auto_upgrade
            # Le bureau d'abord : il repose sur les dépôts de la distribution,
            # là où l'installation ERPLibre compile longuement. Un échec ici se
            # voit donc tôt plutôt qu'après une heure.
            + (
                self._qemu_desktop_remote_cmd(desktop, app_store)
                if desktop
                else ""
            )
            +
            # Outils d'amorçage (absents des images cloud minimales) : curl,
            # git, make. Chaque branche RAFRAÎCHIT d'abord les dépôts pour que
            # la VM soit la plus rapide possible (miroirs à jour / les plus
            # rapides), puis installe. Supporte apt (Debian/Ubuntu), dnf/yum
            # (Fedora) et pacman (Arch).
            #
            # L'éditeur de l'hôte voyage avec eux : deploy_qemu.py a déjà écrit
            # « core.editor » dans le ~/.gitconfig de la VM et l'a nommé dans le
            # guide de connexion, mais aucune image cloud ne garantit vim ni
            # nano. Le poser ici plutôt que par cloud-init : les dépôts y sont
            # déjà rafraîchis, et une installation de paquet au premier boot
            # retarderait le démarrage sans laisser de trace dans le suivi.
            f"PKGS='curl git make{self._qemu_editor_suffix()}'; "
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
            + self._qemu_pacman_prepare_cmd()
            + "sudo pacman -S --needed --noconfirm $PKGS; "
            "elif command -v zypper >/dev/null 2>&1; then "
            # openSUSE : « --non-interactive » vaut le -y des autres, et
            # « --auto-agree-with-licenses », qui va APRÈS « install »,
            # évite un blocage sur une licence à accepter.
            # Tumbleweed étant rolling, on rafraîchit avant d'installer.
            + self._qemu_zypper_mirror_cmd()
            + "sudo zypper --non-interactive refresh || true; "
            # Tumbleweed est ROLLING et ne supporte pas les mises à jour
            # partielles, exactement comme Arch. L'image cloud est un
            # instantané figé : ses dépôts ont avancé depuis, et un
            # « install » simple bute sur une incohérence — vécu, git 2.54
            # réclamait perl-Git bâti contre un perl-base plus ancien que
            # celui de l'image. zypper proposait alors trois solutions et
            # attendait un choix ; « --non-interactive » prend le défaut,
            # « c » = annuler, et l'installation s'arrêtait là.
            #
            # Sur Leap, « dup » sert à CHANGER de version : l'y appeler irait
            # contre la raison même de la choisir. « up » y suffit, l'image et
            # ses dépôts portant la même version.
            # $ID est déjà posé par le bloc miroir juste au-dessus ; on le
            # relit quand même, pour ne pas dépendre de l'ordre de deux
            # méthodes qui s'ignorent.
            ". /etc/os-release; "
            'case "$ID" in *tumbleweed*) '
            "sudo zypper --non-interactive dup --auto-agree-with-licenses "
            "--allow-vendor-change || true;; "
            "*) sudo zypper --non-interactive up "
            "--auto-agree-with-licenses || true;; esac; "
            "sudo zypper --non-interactive install "
            "--auto-agree-with-licenses $PKGS; "
            "elif command -v yum >/dev/null 2>&1; then "
            "sudo yum makecache -q || true; sudo yum install -y $PKGS; "
            "else echo 'Aucun gestionnaire de paquets "
            "(apt/dnf/pacman/zypper/yum)'; exit 1; fi; "
            # Vérifie explicitement que tout est là : erreur nette plutôt
            # qu'un « command not found » cryptique plus loin.
            "for t in curl git make; do command -v $t >/dev/null 2>&1 || "
            '{ echo "Outil manquant apres installation: $t '
            '(reseau de la VM ?)"; exit 1; }; done; '
            + self._qemu_mise_remote_cmd(python_provider)
            # Les outils AVANT le clone et le make, et l'ordre compte : c'est
            # PyCharm qui écrit le .idea du dépôt, en l'ouvrant une fois, et
            # c'est l'installation qui, ensuite, y lance
            # pycharm_configuration.py. Posés après, ils arrivaient trop tard
            # pour cette étape-là.
            #
            # Le code de sortie de la commande distante reste celui de
            # l'installation : chaque bloc d'outil se garde lui-même et rend 0,
            # donc aucun ne peut faire passer un make échoué pour un succès.
            + tools_cmd
            # Clone : /opt/erplibre en PROD (racine, puis chown à l'utilisateur
            # pour que make/venv s'exécutent sans sudo), ~/git/erplibre en dev.
            + (
                (
                    "sudo mkdir -p /opt; "
                    "if [ ! -d /opt/erplibre/.git ]; then "
                    f"sudo git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} /opt/erplibre; "
                    "sudo chown -R $(id -un):$(id -gn) /opt/erplibre; fi; "
                    f"cd /opt/erplibre && {install_chain}"
                )
                if prod
                else (
                    "mkdir -p ~/git; "
                    "if [ ! -d ~/git/erplibre/.git ]; then "
                    f"git clone --branch {shlex.quote(branch)} "
                    f"{self.ERPLIBRE_GIT_URL} ~/git/erplibre; fi; "
                    f"cd ~/git/erplibre && {install_chain}"
                )
            )
        )

    def _qemu_install_erplibre_monitored(
        self,
        names,
        branch,
        ip_map=None,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        vm_tools=(),
    ):
        """Lance l'install ERPLibre en parallèle DÉTACHÉE sur les VM et ouvre
        le dashboard Textual. Quitter le dashboard n'arrête pas les installs.
        `ip_map` : IP déjà résolues (sinon on résout ici, EN PARALLÈLE).
        `final_cmd` : commande d'install selon le profil choisi.
        `prod` : install /opt/erplibre + service SELinux confiné.
        `vm_tools` : outils cochés pour tout le parc, filtrés machine par
        machine (Android Studio n'existe qu'en x86_64, les extensions GNOME
        n'ont pas de sens sous Cinnamon)."""
        from script.todo.qemu_install_monitor import (
            launch_installs,
            run_monitor,
        )

        # `desktop` accepte une SAVEUR unique (toutes les VM) ou un dict
        # {nom: saveur} depuis que le type se choisit machine par machine. La
        # commande distante en dépend, donc elle se construit par VM ; celle-ci
        # reste le défaut pour les noms absents du dict.
        desk_map = desktop if isinstance(desktop, dict) else {}
        # Même contrat que `desktop` : une chaîne pour tout le parc, ou
        # une carte {nom: branche} quand elles diffèrent d'une VM à l'autre.
        branch_map = branch if isinstance(branch, dict) else {}
        branch_def = "" if branch_map else branch
        # Idem pour le profil : « ERPLibre + Odoo 18 » peut differer d'une
        # machine a l'autre, on valide alors deux versions d'un coup.
        cmd_map = final_cmd if isinstance(final_cmd, dict) else {}
        cmd_def = None if cmd_map else final_cmd
        remote = self._qemu_erplibre_remote_cmd(
            branch_def,
            cmd_def,
            prod,
            "" if desk_map else desktop,
            python_provider,
            app_store,
        )
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
                entry = {
                    "name": name,
                    "ip": ip,
                    "distro": d,
                    "version": v,
                    "arch": a,
                }
                # Les outils imposent une commande PAR VM même quand tout le
                # reste est commun : ils dépendent de l'architecture de la
                # machine et de sa saveur de bureau, que seule cette boucle
                # connaît.
                if desk_map or branch_map or cmd_map or vm_tools:
                    # Le bureau de CETTE VM : sa saveur propre si la carte en
                    # donne une, sinon celle du parc. Prendre « rien » quand la
                    # carte est vide privait de bureau toute VM dont seule la
                    # branche ou le profil différait — la commande par défaut,
                    # elle, l'a toujours porté.
                    vm_desktop = desk_map.get(
                        name, "" if desk_map else desktop
                    )
                    entry["remote_cmd"] = self._qemu_erplibre_remote_cmd(
                        branch_map.get(name, branch_def),
                        cmd_map.get(name, cmd_def),
                        prod,
                        vm_desktop,
                        python_provider,
                        app_store,
                        self._qemu_tools_for(vm_tools, a, vm_desktop, d),
                    )
                vms.append(entry)
            else:
                print(f"  {name}: {t('no IP, skipped.')}")
        if not vms:
            print(t("No VM to install."))
            return
        manifest = launch_installs(
            vms, branch_def or next(iter(branch_map.values()), ""), remote
        )
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
            # plante donc pas — on propose de l'installer pour rouvrir.
            from script.todo import textual_setup

            if textual_setup.ensure():
                run_monitor(manifest)
        print(
            f"\n{t('Monitor closed. Installs keep running in the background.')}"
        )
        logdir = os.path.dirname(manifest)
        print(f"  {t('Logs:')} {logdir}")
        # Commande prête à copier pour relire/partager tous les logs.
        print(f"  {t('Read the logs:')} tail -n +1 {logdir}/*.log")

    def _qemu_install_erplibre_vm(
        self,
        name,
        ssh_key,
        branch,
        ip=None,
        final_cmd=None,
        prod=False,
        desktop=False,
        python_provider="",
        app_store="deb",
        vm_tools=(),
    ):
        """Clone ERPLibre (branche donnée) dans la VM puis exécute la commande
        d'install du profil choisi (streamé). `ip` : IP déjà résolue ;
        `final_cmd` : commande d'install ; `prod` : /opt + SELinux confiné ;
        `vm_tools` : outils de développement cochés."""
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
        # Distribution et architecture de CETTE VM : les outils s'y filtrent
        # (Android Studio n'existe qu'en x86_64, la compilation mobile qu'en
        # apt). Sans module lisible on ne filtre plus sur la distribution
        # plutôt que d'écarter à tort.
        try:
            mod = self._qemu_import_module()
            vm_distro, _v, vm_arch = self._qemu_vm_meta(name, mod)
        except Exception:
            vm_distro, vm_arch = "", self._qemu_vm_arch(name)
        remote = self._qemu_erplibre_remote_cmd(
            branch,
            final_cmd,
            prod,
            desktop,
            python_provider,
            app_store,
            self._qemu_tools_for(
                vm_tools, vm_arch or "amd64", desktop, vm_distro or ""
            ),
        )
        ssh_opts = (
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=15"
        )
        cmd = f"ssh {ssh_opts} erplibre@{ip} {shlex.quote(remote)}"
        print(
            f"\n  📦 {name} ({ip}): {t('installing ERPLibre')} " f"({branch})"
        )
        print(f"  {t('Will execute:')} {cmd}")
        self.execute.exec_command_live(cmd, source_erplibre=False)

    # Suggestions proposées aux invites de taille. Les lettres démarrent à « a »
    # pour ne JAMAIS entrer en conflit avec une valeur tapée directement : toute
    # saisie commençant par un chiffre est lue comme la valeur elle-même.
    _QEMU_DISK_PRESETS = (
        "20G",
        "30G",
        "40G",
        "50G",
        "60G",
        "80G",
        "100G",
        "120G",
        "160G",
        "200G",
        "400G",
        "600G",
        "800G",
        "1T",
        "1.5T",
        "2T",
    )
    # Jusqu'à 256 Go : les hôtes de virtualisation récents dépassent largement
    # 32 Go, et l'invite est en Mo — l'équivalent en Go est donc affiché.
    _QEMU_RAM_PRESETS = (
        1024,
        2048,
        3072,
        4096,
        5120,
        6144,
        7168,
        8192,
        9216,
        10240,
        11264,
        12288,
        13312,
        14336,
        15360,
        16384,
        32768,
        65536,
        131072,
        262144,
    )
    # KVM autorise plus de vCPU que de cœurs (surengagement) : on prévient
    # plutôt que d'écrêter, contrairement au multiplicateur x1..x4 qui, lui,
    # est un calcul automatique et se borne aux cœurs de l'hôte.
    _QEMU_CPU_PRESETS = (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        24,
        32,
    )

    @staticmethod
    def _plural(word, count):
        """Accord simple : « échec » / « échecs ». Vaut pour fr et en."""
        return word if abs(count) <= 1 else f"{word}s"

    @staticmethod
    def _qemu_parse_disk(value):
        """Normalise une taille de disque en « <n>G », ou None si invalide.

        Accepte « 60 », « 60G », « 1T », « 1,5T ». Le suffixe T est converti
        (1 T = 1024 G) : tout le reste de la chaîne — nom de fichier qcow2,
        argument --disk-size — raisonne en gigaoctets.
        """
        txt = value.strip().upper().replace(",", ".")
        factor = 1
        if txt.endswith("T"):
            factor, txt = 1024, txt[:-1]
        elif txt.endswith("G"):
            txt = txt[:-1]
        try:
            gigs = int(float(txt) * factor)
        except ValueError:
            return None
        return f"{gigs}G" if gigs > 0 else None

    @staticmethod
    def _qemu_ram_label(mb):
        """« 65536 (64G) » : l'invite est en Mo, on raisonne en Go."""
        return f"{mb} ({mb // 1024}G)" if mb >= 1024 else str(mb)

    @staticmethod
    def _qemu_ask_value(label, current, presets, fmt=str):
        """Invite avec raccourcis lettrés. Renvoie '' pour « garder ».

        Une lettre choisit une suggestion, un chiffre reste une valeur
        littérale, vide garde la valeur actuelle. Les suggestions sont
        réparties sur plusieurs lignes pour rester lisibles.
        """
        lst_item = [
            f"[{chr(ord('a') + i)}] {fmt(p)}" for i, p in enumerate(presets)
        ]
        for start in range(0, len(lst_item), 5):
            print("    " + "  ".join(lst_item[start : start + 5]))
        answer = input(f"  {label} ({current}): ").strip()
        if not answer:
            return ""
        if len(answer) == 1 and answer.isalpha():
            index = ord(answer.lower()) - ord("a")
            if 0 <= index < len(presets):
                return str(presets[index])
            print(f"    ⚠ {t('Invalid size.')}")
            return ""
        return answer

    # Les trois invites ci-dessous sont posées à DEUX endroits — le profil
    # global « Personnalisé » et la personnalisation par VM. Elles vivent donc
    # ici : une seule définition, mêmes suggestions, mêmes validations.
    # Chacune renvoie None pour « garder la valeur actuelle ».

    def _qemu_ask_disk(self, label, current):
        raw = self._qemu_ask_value(label, current, self._QEMU_DISK_PRESETS)
        if not raw:
            return None
        parsed = self._qemu_parse_disk(raw)
        if not parsed:
            print(f"    ⚠ {t('Invalid size.')}")
        return parsed

    def _qemu_ask_ram(self, label, current):
        raw = self._qemu_ask_value(
            label, current, self._QEMU_RAM_PRESETS, fmt=self._qemu_ram_label
        )
        if not raw:
            return None
        try:
            mb = int(raw)
        except ValueError:
            mb = 0
        if mb <= 0:
            print(f"    ⚠ {t('Invalid size.')}")
            return None
        return mb

    def _qemu_ask_cpu(self, label, current, host_cpu):
        raw = self._qemu_ask_value(label, current, self._QEMU_CPU_PRESETS)
        if not raw:
            return None
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n <= 0:
            print(f"    ⚠ {t('Invalid vCPU count.')}")
            return None
        if n > host_cpu:
            print(f"    ⚠ {t('More vCPU than host cores')} ({host_cpu}).")
        return n

    @staticmethod
    def _qemu_shared_value(values, fmt=str):
        """Valeur commune à toutes les VM, ou « varié » si elles diffèrent.
        Sert d'« actuel » aux invites globales, où une seule réponse couvre un
        parc qui n'est pas forcément homogène."""
        uniq = set(values)
        return fmt(uniq.pop()) if len(uniq) == 1 else t("varies")

    # vCPU de base (x1) par VM. Le multiplicateur monte de là.
    _QEMU_BASE_VCPUS = 2

    def _qemu_prompt_resources(self, selected, host_cpu, free_ram):
        """Ressources par VM : multiplicateur x1..x4, ou « Personnalisé ».

        x1..x4 multiplie la RAM (base = minimum de la version) et les vCPU
        (base _QEMU_BASE_VCPUS) en bornant ces derniers aux cœurs de l'hôte.
        « Personnalisé » pose les mêmes trois questions que la personnalisation
        par VM, mais une seule fois pour tout le parc.

        `selected` = liste de (d, v, ram_min, disk, arch). Renvoie
        (label, selected) où selected porte désormais les valeurs FINALES et
        un vCPU par VM : (d, v, ram, disk, arch, vcpus)."""
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
        print(f"  [5] {t('Custom - set vCPU, RAM and disk')}")
        sel = input(f"{t('Choice (1-5, default 1):')} ").strip()
        try:
            mult = int(sel)
        except ValueError:
            mult = 1
        if not 1 <= mult <= 5:
            mult = 1

        if mult != 5:
            vcpus = min(base_vcpus * mult, host_cpu)
            return f"x{mult}", [
                (d, v, ram * mult, disk, a, vcpus)
                for (d, v, ram, disk, a) in selected
            ]

        # Personnalisé : une réponse vide garde la valeur du catalogue, qui
        # peut différer d'une VM à l'autre — d'où « varié » comme « actuel ».
        cpu = self._qemu_ask_cpu(
            t("vCPU per VM, blank = keep"), base_vcpus, host_cpu
        )
        ram = self._qemu_ask_ram(
            t("New RAM in MB, blank = keep"),
            self._qemu_shared_value([s[2] for s in selected]),
        )
        disk = self._qemu_ask_disk(
            t("New disk size in G, blank = keep"),
            self._qemu_shared_value([s[3] for s in selected]),
        )
        return t("custom"), [
            (
                d,
                v,
                ram or vram,
                disk or vdisk,
                a,
                cpu or base_vcpus,
            )
            for (d, v, vram, vdisk, a) in selected
        ]

    def _qemu_customize_vms(self, selected, host_cpu):
        """Personnalise chaque VM avant déploiement : NOM, DISQUE, RAM et vCPU.
        `selected` = liste de (d, v, ram, disk, a, vcpus) où les valeurs sont
        déjà FINALES (profil de ressources appliqué).
        Renvoie (names, selected_maj). Défaut : rien ne change."""
        names = [
            self._qemu_infra_name(d, v, a) for d, v, _r, _dk, a, _c in selected
        ]
        sel = [list(s) for s in selected]  # mutable

        def show():
            print(f"\n{t('VMs (default = no change):')}")
            for i, (nm, s) in enumerate(zip(names, sel), 1):
                d, v, ram, disk, a, vcpus = s
                print(
                    f"  [{i}] {nm}   ({d} {v} [{a}])  {vcpus} vCPU  "
                    f"RAM {ram}Mo  {t('disk')} {disk}"
                )

        show()
        raw = input(
            t("Modify which VMs? (numbers, comma-separated; blank = none): ")
        ).strip()
        for tok in re.split(r"[\s,]+", raw):
            if not tok:
                continue
            try:
                i = int(tok) - 1
            except ValueError:
                continue
            if not (0 <= i < len(sel)):
                continue
            # Pour la VM i : nom, disque, RAM, vCPU (vide = garder la valeur).
            new = input(
                f"  {names[i]} — {t('new name (blank = keep):')} "
            ).strip()
            if new:
                names[i] = new
            dk = self._qemu_ask_disk(
                t("New disk size in G, blank = keep"), sel[i][3]
            )
            if dk:
                sel[i][3] = dk
            rm = self._qemu_ask_ram(
                t("New RAM in MB, blank = keep"), sel[i][2]
            )
            if rm:
                sel[i][2] = rm
            cpu = self._qemu_ask_cpu(
                t("New vCPU count, blank = keep"), sel[i][5], host_cpu
            )
            if cpu:
                sel[i][5] = cpu
        if len(set(names)) != len(names):
            print(f"  ⚠ {t('Duplicate names detected; keeping as entered.')}")
        return names, [tuple(s) for s in sel]

    def _confirm_or_discard(self, question):
        """Confirmation à défaut OUI, avec double validation sur le NON.

        Un « non » distrait ferait perdre toutes les réponses déjà saisies. On
        ne renonce donc que si l'abandon est confirmé ; sinon on repose la
        question."""
        while True:
            if self._is_yes_default_yes(input(f"\n{question}")):
                return True
            if self._is_yes(
                input(f"  {t('Discard everything and start over? (y/N): ')}")
            ):
                return False

    @staticmethod
    def _qemu_orphan_disks(names):
        """qcow2 présents sans VM définie, parmi `names` : [(nom, chemin)].

        Pur : ni sudo ni virsh — l'appelant fournit déjà les noms qui n'ont
        PAS de domaine. C'est ce qui permet au formulaire TUI de recalculer
        les collisions à chaque frappe sans déclencher d'invite de mot de
        passe."""
        orphans = []
        for name in names:
            path = f"/var/lib/libvirt/images/{name}.qcow2"
            if os.path.exists(path):
                orphans.append((name, path))
        return orphans

    def _qemu_confirm_collisions(self, existing, pending_names):
        """Signale les noms qui heurtent l'existant, et demande confirmation.

        Deux cas, de gravité différente : une VM déjà définie est simplement
        ignorée — rien n'est écrasé — tandis qu'un qcow2 resté seul (VM
        supprimée sans son disque) fait échouer deploy_qemu, qui refuse
        d'écraser sans --force. Défaut NON : on ne poursuit que sur un « oui »
        explicite."""
        orphans = self._qemu_orphan_disks(pending_names)
        if not existing and not orphans:
            return True
        print(f"\n⚠  {t('Name collisions detected')} :")
        skipped = t("VM already defined - SKIPPED, nothing overwritten")
        for name in existing:
            print(f"   {name:<28.28} {skipped}")
        for name, path in orphans:
            print(
                f"   {name:<28.28} "
                f"{t('disk present without VM - deployment will FAIL')}"
            )
            print(f"   {'':<28} {path}")
            print(f"   {'':<28} {t('Remove it by hand, or rename the VM.')}")
        return self._is_yes(
            input(f"{t('Continue despite these collisions? (y/N): ')}")
        )

    def _qemu_print_recap(self, spec, existing):
        """État final soumis à approbation : tout ce qui va changer sur
        l'hôte, y compris ce qui ne changera PAS (VM existantes)."""
        install = spec.get("install")
        branch = install["branch"] if install else None
        print(f"\n── {t('Final review before deployment')} ──")
        print(f"  {t('VMs to create:')} {len(spec['vms'])}")
        for vm in spec["vms"]:
            # Le disque annoncé est celui qui sera réellement créé : ERPLibre
            # ajoute ERPLIBRE_EXTRA_DISK_GB à la demande initiale.
            gigs = self._parse_disk_gb(vm["disk"]) + (
                self.ERPLIBRE_EXTRA_DISK_GB if branch else 0
            )
            # Ce qui S'ECARTE du choix commun se dit sur la ligne de la VM.
            # Sans cela le sommaire annoncait le profil general pour tout le
            # monde, y compris pour une VM figee sur un autre — on lisait
            # « Odoo 15 » avant de deployer une machine en Odoo 18.
            apart = []
            # Seul ce qui DIFFERE vaut d'etre signale : une VM figee sur la
            # meme branche que le global n'a rien de particulier a montrer,
            # et repeter la valeur commune sur chaque ligne la noierait.
            if install and vm.get("branch") and vm["branch"] != branch:
                apart.append(vm["branch"])
            if (
                vm.get("install_label")
                and install
                and vm.get("install_cmd") != install.get("cmd")
            ):
                apart.append(vm["install_label"])
            if vm.get("desktop") and vm["desktop"] != spec.get("desktop"):
                apart.append(
                    (self._QEMU_DESKTOP.get(vm["desktop"]) or {}).get(
                        "label", vm["desktop"]
                    )
                )
            print(
                f"     {vm['name']:<30} {vm['distro']} {vm['version']:<7} "
                f"[{vm['arch']:<5}] {vm['vcpus']} vCPU  RAM {vm['ram']}Mo  "
                f"{t('disk')} {gigs}G"
                + (f"  ⟵ {' · '.join(apart)}" if apart else "")
            )
        if existing:
            print(f"  {t('Existing, left untouched:')} {', '.join(existing)}")
        if install:
            env = (
                t("production (/opt, confined)")
                if install["prod"]
                else t("development (~/git)")
            )
            # « par defaut » : chaque VM peut s'en ecarter, et sa ligne le dit.
            # Ce qui sera REELLEMENT pose, pas le defaut du formulaire. Avec
            # une seule VM figee sur un autre profil, annoncer le defaut
            # revenait a nommer une version que rien n'installe — c'est
            # exactement ce qu'on relit ici pour eviter de se tromper.
            used_br = {vm.get("branch") or branch for vm in spec["vms"]}
            used_lb = {
                vm.get("install_label") or install["label"]
                for vm in spec["vms"]
            }
            varies = t("varies, see each line")
            br_txt = used_br.pop() if len(used_br) == 1 else varies
            lb_txt = used_lb.pop() if len(used_lb) == 1 else varies
            print(
                f"  {t('ERPLibre install:')} {t('branch')} {br_txt}, "
                f"{t('profile')} {lb_txt}, {env}"
            )
        else:
            print(f"  {t('ERPLibre install:')} {t('no')}")
        flavour = spec.get("desktop")
        if flavour:
            label = (self._QEMU_DESKTOP.get(flavour) or {}).get(
                "label", flavour
            )
            print(
                f"  {t('VM type:')} {t('Graphical (server + desktop):')} {label}"
            )
        tools = spec.get("vm_tools") or ()
        if tools:
            # Les Go sont dits ici parce que c'est le dernier écran avant de
            # créer les disques : un IDE de plus, c'est un disque plus grand,
            # et cette page est celle qu'on relit pour s'en apercevoir.
            named = ", ".join(
                f"{t(self._QEMU_VM_TOOLS[k]['label'])} "
                f"(+{self._QEMU_VM_TOOLS[k]['disk_gb']} Go)"
                for k in tools
                if k in self._QEMU_VM_TOOLS
            )
            print(f"  {t('Development tools:')} {named}")
        prov = spec.get("python_provider")
        if prov:
            print(f"  {t('Python interpreter:')} {prov}")
        print(f"  {t('SSH key:')} {spec.get('ssh_key') or t('none')}")
        cfg = (
            t("one entry per VM") if spec["add_ssh_config"] else t("untouched")
        )
        print(f"  {t('~/.ssh/config:')} {cfg}")
        print(f"  {t('Parallelism:')} {spec['parallelism']} {t('at a time')}")

    def _qemu_build_deploy_parts(
        self,
        d,
        v,
        arch,
        name,
        eram,
        evcpus,
        disk,
        ssh_key,
        branch,
        dry_run,
        timezone=None,
        locale=None,
        desktop=False,
        prod=False,
        install_cmd="",
        vm_tools=(),
    ):
        """Construit la commande deploy_qemu.py d'UNE VM (utilisée pour l'aperçu
        dry-run ET le déploiement réel)."""
        parts = [] if dry_run else ["sudo"]
        parts += [
            self._qemu_script_path(),
            "--distro",
            d,
            "--version",
            v,
            "--name",
            name,
            "--memory",
            str(eram),
            "--vcpus",
            str(evcpus),
            "--password",
            "erplibre",
        ]
        if not dry_run:
            # --no-wait-ip : ne bloque pas 90s/VM, l'IP est collectée après.
            parts.append("--no-wait-ip")
        if arch and arch != "amd64":
            parts += ["--arch", arch]
        if ssh_key:
            parts += ["--ssh-key", ssh_key]
        if timezone:
            # Toujours explicite, jamais implicite : la commande affichée en
            # dry-run doit produire la même VM si on la rejoue depuis une autre
            # machine, dont le fuseau serait différent.
            parts += ["--timezone", timezone]
        if locale:
            parts += ["--locale", locale]
        if desktop:
            parts.append("--desktop")
        # Guide affiché à la connexion SSH de la VM : dans la langue du menu, et
        # avec la section ERPLibre seulement là où ERPLibre sera installé — une
        # VM déployée nue n'annonce pas un dépôt qui n'existe pas.
        parts += ["--lang", get_lang()]
        if branch:
            parts += ["--erplibre-dir", self._qemu_guide_dir(prod)]
            target = self._qemu_make_target(install_cmd)
            if target:
                parts += ["--erplibre-make", target]
        extra = 0
        if branch:
            # ERPLibre dépasse le minimum : +5 Go de disque.
            extra += self.ERPLIBRE_EXTRA_DISK_GB
        if desktop:
            # GNOME et ses dépendances pèsent autant qu'ERPLibre : sans cette
            # marge, le disque se remplit en pleine installation du bureau.
            extra += self.QEMU_DESKTOP_EXTRA_DISK_GB
        # Les IDE pèsent plus lourd que tout le reste : PyCharm et Android
        # Studio, c'est l'archive téléchargée PUIS son contenu déplié. Compté
        # ici plutôt qu'au petit bonheur, sinon l'installation se termine sur un
        # disque plein après une heure.
        extra += self._qemu_tools_disk_gb(vm_tools, arch, desktop, d)
        if extra:
            bigger = self._parse_disk_gb(disk) + extra
            parts += ["--disk-size", f"{bigger}G"]
        parts.append("--dry-run" if dry_run else "-y")
        return parts

    def _qemu_deploy_parts_for(self, vm, spec, dry_run=False):
        """Commande deploy_qemu.py d'une VM de la spec.

        POINT DE PASSAGE UNIQUE des deux interfaces : le formulaire TUI et les
        invites en ligne produisent la même spec, donc forcément la même
        commande. C'est ce qui rend leur divergence vérifiable par un test."""
        install = spec.get("install")
        return self._qemu_build_deploy_parts(
            vm["distro"],
            vm["version"],
            vm["arch"],
            vm["name"],
            vm["ram"],
            vm["vcpus"],
            vm["disk"],
            spec.get("ssh_key"),
            install["branch"] if install else None,
            dry_run=dry_run,
            timezone=spec.get("timezone"),
            locale=spec.get("locale"),
            # Le type suit la VM. Repli sur la valeur de spec pour la CLI,
            # qui ne pose la question qu'une fois pour tout le parc.
            #
            # La SAVEUR, et non un booléen : les extensions GNOME n'ont pas de
            # sens sous Cinnamon, et c'est ici que se calcule la place disque
            # des outils. « --desktop » ne regarde que la vérité de la valeur,
            # une chaîne non vide lui va aussi bien.
            desktop=vm.get("desktop", spec.get("desktop")) or "",
            # Les deux servent au guide de connexion : où ERPLibre sera posé, et
            # quelle cible make le remettra à jour.
            prod=bool(install and install.get("prod")),
            install_cmd=(install or {}).get("cmd") or "",
            vm_tools=spec.get("vm_tools") or (),
        )

    # ---------------------------------------------------------------- #
    # Déploiement : catalogue (pur) -> collecte (CLI ou TUI) -> exécution
    # ---------------------------------------------------------------- #

    def _qemu_arches_for(self, distro, arch):
        """Architectures à déployer pour cette distro selon le choix global.
        « all » = uniquement celles que la distro publie réellement."""
        if arch != "all":
            return [arch]
        # Même source que _qemu_arch_distros : « all » ne doit jamais offrir
        # une combinaison que deploy_qemu.py refusera.
        out = ["amd64"]
        for a in ("arm64", "s390x"):
            supported = self._qemu_arch_distros(a)
            if supported and distro in supported:
                out.append(a)
        return out

    def _qemu_catalog_entries(self, mod, distros, arch):
        """Catalogue APLATI : une entrée par (distro, version, architecture).

        Fonction pure, sans I/O : c'est la source unique de ce qui est
        déployable, aussi bien pour la liste granulaire de la CLI que pour la
        liste à cocher du formulaire TUI."""
        flat = []
        # Une distro peut ne publier qu'une partie de ses versions sur une
        # architecture (Fedora ne construit que la courante en s390x). La
        # table vit dans deploy_qemu.py, qui refuse aussi ces combinaisons :
        # une seule source, donc aucun écran n'offre un choix rejeté ensuite.
        only = getattr(mod, "arch_versions", None)
        for d in distros:
            versions_map, default_v = mod.DISTROS[d]
            for v, (_c, _o, ram, disk) in versions_map.items():
                for a in self._qemu_arches_for(d, arch):
                    if only and v not in only(d, a, versions_map):
                        continue
                    flat.append(
                        {
                            "distro": d,
                            "version": v,
                            "arch": a,
                            "ram": ram,
                            "disk": disk,
                            "default": v == default_v,
                        }
                    )
        return flat

    @staticmethod
    def _qemu_make_vm(distro, version, arch, ram, disk, vcpus, name):
        """Une VM de la spec. Un seul endroit décrit sa forme."""
        return {
            "name": name,
            "distro": distro,
            "version": version,
            "arch": arch,
            "ram": ram,
            "disk": disk,
            "vcpus": vcpus,
        }

    def _qemu_split_existing(self, vms, domains):
        """Sépare les VM à créer de celles dont le domaine existe déjà.
        `domains` est la liste des noms libvirt, obtenue UNE fois (un seul
        sudo) et non par VM. Renvoie (à_créer, noms_existants)."""
        known = set(domains)
        pending = [vm for vm in vms if vm["name"] not in known]
        existing = [vm["name"] for vm in vms if vm["name"] in known]
        return pending, existing

    def _qemu_check_libvirt_group(self):
        """Prévient si virsh n'est pas joignable sans sudo, et propose de régler.

        Le suivi d'installation tourne DÉTACHÉ, sans tty : il ne peut pas
        répondre à une demande de mot de passe. « sudo -n » y échoue sur tout
        hôte exigeant une authentification interactive (vécu sur erplibre01 avec
        sudo-rs), et la VM devient alors introuvable dès que son bail DHCP
        change. Le groupe libvirt est la seule voie qui n'exige ni root ni tty.

        Vérifié AVANT de créer quoi que ce soit : découvrir le problème après
        vingt minutes d'installation coûte bien plus cher qu'une question ici.
        """
        probe = subprocess.run(
            ["virsh", "--connect", "qemu:///system", "list", "--name"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return  # joignable sans sudo : rien à signaler

        user = getpass.getuser()
        # Être dans /etc/group ne suffit pas : les groupes d'un processus sont
        # figés à l'ouverture de session. Distinguer les deux cas évite de
        # proposer un usermod déjà fait, et dit la vraie action attendue.
        try:
            declared = user in grp.getgrnam("libvirt").gr_mem
        except KeyError:
            declared = False
        try:
            active = grp.getgrnam("libvirt").gr_gid in os.getgroups()
        except KeyError:
            active = False

        print(f"\n⚠  {t('virsh cannot reach qemu:///system without sudo.')}")
        print(f"   {t('The install monitor runs detached and cannot type a')}")
        print(
            f"   {t('password: it would lose the VM when its lease moves.')}"
        )

        if declared and not active:
            print(
                f"\n   {t('You are in the libvirt group, but this session')}"
            )
            print(f"   {t('predates it. Log out and back in, or run:')}")
            print(f"     newgrp libvirt")
            return
        if active:
            # Groupe présent mais virsh échoue quand même : libvirtd arrêté,
            # socket absente… La cause n'est pas le groupe, ne pas la maquiller.
            print(f"\n   {t('Group is active, so the cause is elsewhere:')}")
            print(f"     {(probe.stderr or '').strip()[:200]}")
            return

        cmd = f"sudo usermod -aG libvirt {shlex.quote(user)}"
        print(f"\n   {t('Add your user to the libvirt group?')}")
        print(f"     {cmd}")
        if not self._is_yes_default_yes(input(t("Run it now? (Y/n): "))):
            return
        if os.system(cmd) != 0:
            print(f"   ⚠ {t('Command failed.')}")
            return
        print(f"\n✅ {t('Added. Log out and back in for it to take effect,')}")
        print(f"   {t('or start a new shell with: newgrp libvirt')}")

    def _qemu_check_kvm(self):
        """Prévient quand les VM seront ÉMULÉES faute de KVM.

        « Même architecture que l'hôte » ne veut pas dire accélérée : dans une
        VM sans virtualisation imbriquée, libvirt bascule en TCG sans le dire.
        Mesuré : une VM s390x sur un hôte s390x lui-même invité KVM est sortie
        en « <domain type='qemu'> » et a démarré en 7 min 30. Le savoir avant
        d'attendre vaut mieux que de chercher la cause après."""
        try:
            mod = self._qemu_import_module()
            if mod.kvm_available():
                return
        except Exception:
            return
        try:
            module = mod.nested_module()
        except Exception:
            module = "kvm"
        print(f"\n⚠  {t('KVM is unavailable: the VMs will be EMULATED.')}")
        print(f"   {t('A boot then takes 10-15 min, not under a minute.')}")
        print(
            f"   {t('Cause: /dev/kvm is missing. This host is itself a VM')}"
        )
        print(
            f"   {t('whose hypervisor does not expose nested virtualization.')}"
        )
        print(f"\n   {t('To fix it ON THE PARENT HYPERVISOR, not here:')}")
        print(
            f'     echo "options {module} nested=1"'
            f" | sudo tee /etc/modprobe.d/kvm-nested.conf"
        )
        print(f"     sudo modprobe -r {module} && sudo modprobe {module}")
        print(
            f"   {t('then set this VM to the host-passthrough CPU mode and')}"
        )
        print(
            f"   {t('stop it and start it again - a reboot is not enough.')}"
        )
        print(
            f"\n   {t('Without access to that hypervisor, nothing to do here.')}"
        )

    def _qemu_ask_ui(self):
        """Interface du déploiement : formulaire TUI ou invites en ligne.
        La préférence peut trancher d'avance (menu Configuration) ; « ask »
        pose la question."""
        pref = todo_prefs.get("qemu_deploy_ui")
        if pref in ("tui", "cli"):
            return pref
        print(f"\n{t('Interface:')}")
        print(f"  [1] {t('TUI form')} *")
        print(f"  [2] {t('Classic questions (line by line)')}")
        print(f"  {t('(change the default in TODO > Configuration)')}")
        sel = input(t("Choice (1-2, default 1): ")).strip()
        return "cli" if sel == "2" else "tui"

    def _qemu_form_context(self, mod):
        """Données préchargées pour le formulaire TUI.

        TOUT ce qui exige sudo (liste des domaines) ou le réseau (branches)
        est fait ICI, pendant que le terminal est encore à nous : une invite
        de mot de passe pendant que Textual affiche casserait l'écran."""
        native = self._native_arch()
        arches = ["amd64", "arm64", "s390x"]
        if native not in arches:
            arches.insert(0, native)
        arches.append("all")

        catalog = {}
        for a in arches:
            distros = list(mod.DISTROS)
            if a != "all":
                allowed = self._qemu_arch_distros(a)
                if allowed is not None:
                    distros = [d for d in distros if d in allowed]
            entries = self._qemu_catalog_entries(mod, distros, a)
            for e in entries:
                # Le nom est calculé ici : le formulaire reste pure donnée.
                e["name"] = self._qemu_infra_name(
                    e["distro"], e["version"], e["arch"]
                )
            catalog[a] = entries

        print(f"\n{t('Loading (VM list, branches)...')}")
        return {
            "catalog": catalog,
            "arches": arches,
            "native": native,
            "domains": self._qemu_list_domains(),
            "branches": self._qemu_branch_list() or ["master"],
            "install_profiles": self._qemu_install_profiles(),
            "ssh_key": self._qemu_default_ssh_key(),
            "timezone": self._qemu_host_timezone(),
            "host_cpu": os.cpu_count() or 2,
            "free_ram": self._host_free_ram_mb(),
            "base_vcpus": self._QEMU_BASE_VCPUS,
            "cpu_presets": self._QEMU_CPU_PRESETS,
            "ram_presets": self._QEMU_RAM_PRESETS,
            "disk_presets": self._QEMU_DISK_PRESETS,
            "extra_disk_gb": self.ERPLIBRE_EXTRA_DISK_GB,
            "desktop_disk_gb": self.QEMU_DESKTOP_EXTRA_DISK_GB,
            "mise_arches": self.QEMU_MISE_ARCHES,
            "app_stores": [(k, t(lbl)) for k, lbl in self.QEMU_APP_STORES],
            "timezones": self._qemu_timezone_choices(
                self._qemu_host_timezone()
            ),
            "snap_distros": self.QEMU_SNAP_DISTROS,
            "vm_tools": self._qemu_vm_tool_choices(),
            "vm_tool_disk": {
                k: v["disk_gb"] for k, v in self._QEMU_VM_TOOLS.items()
            },
            "vm_tool_arches": {
                k: v["arches"] for k, v in self._QEMU_VM_TOOLS.items()
            },
            "vm_tool_desktops": {
                k: v["desktops"] for k, v in self._QEMU_VM_TOOLS.items()
            },
            "vm_tool_needs_desktop": {
                k: v["needs_desktop"] for k, v in self._QEMU_VM_TOOLS.items()
            },
            "vm_tool_families": {
                k: v["families"] for k, v in self._QEMU_VM_TOOLS.items()
            },
            "distro_family": dict(self._QEMU_DISTRO_FAMILY),
            "desktop_suffixes": self._qemu_desktop_suffixes(),
            "desktops": [
                (k, v["label"]) for k, v in self._QEMU_DESKTOP.items()
            ],
            "defaults": {
                "install": True,
                "add_ssh_config": True,
                "monitor": True,
                "prod": False,
            },
            # L'aperçu passe par le MÊME constructeur que le déploiement.
            "build_command": lambda vm, spec, dry: " ".join(
                shlex.quote(p)
                for p in self._qemu_deploy_parts_for(vm, spec, dry_run=dry)
            ),
        }

    def _qemu_deploy(self, dry_run=False):
        """Déploiement d'un parc de VM, en trois temps : collecte des choix
        (formulaire TUI ou invites en ligne), aperçu ou exécution. Les deux
        interfaces produisent la MÊME spec."""
        print(f"🚀 {t('Deploy ERPLibre VM(s)!')}")
        try:
            mod = self._qemu_import_module()
        except Exception as exc:
            print(f"{t('Cannot load QEMU catalog: ')}{exc}")
            return
        # Rappel de la dernière installation enregistrée (si historique).
        last = self._qemu_last_run_line()
        if last:
            print(last)
        # Un aperçu ne crée rien : il n'a pas à interroger sur un run en cours.
        if not dry_run and self._qemu_active_install():
            return

        self._qemu_check_libvirt_group()
        self._qemu_check_kvm()

        if self._qemu_ask_ui() == "tui":
            spec = self._qemu_deploy_form(mod, dry_run)
            if spec is None:
                return
            if spec:  # None = annulé, {} = repli sur la CLI
                self._qemu_run_spec(spec)
                return

        got = self._qemu_collect_vms_cli(mod)
        if not got:
            return
        res_label, vms = got

        if dry_run:
            self._qemu_print_dry_run(vms)
            return

        spec = self._qemu_collect_options_cli(vms, res_label)
        if not spec:
            return
        self._qemu_run_spec(spec)

    def _qemu_deploy_form(self, mod, dry_run):
        """Ouvre le formulaire TUI. Renvoie la spec, None si annulé, ou {}
        pour retomber sur les invites en ligne (textual absent)."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return {}
        try:
            from script.todo.qemu_deploy_form import run_deploy_form

            ctx = self._qemu_form_context(mod)
            spec = run_deploy_form(ctx)
        except ImportError:
            return {}
        if not spec:
            print(t("Cancelled."))
            return None
        if dry_run:
            # L'entrée « aperçu » du menu ne crée rien, même depuis la TUI.
            self._qemu_print_dry_run(spec["vms"])
            return None
        self._qemu_print_recap(spec, spec.get("existing") or [])
        if not self._confirm_or_discard(t("Deploy these VMs now? (Y/n): ")):
            print(t("Cancelled."))
            return None
        return spec

    def _qemu_print_dry_run(self, vms):
        """Aperçu : les commandes deploy_qemu, sans rien créer (ni sudo, ni
        installation). Passe par le point de passage unique, donc montre
        exactement ce qui serait lancé."""
        spec = {"vms": vms, "ssh_key": self._qemu_default_ssh_key()}
        print(f"\n{t('Preview (dry-run):')}")
        for vm in vms:
            parts = self._qemu_deploy_parts_for(vm, spec, dry_run=True)
            print("  " + " ".join(shlex.quote(p) for p in parts))

    def _qemu_collect_vms_cli(self, mod):
        """Invites en ligne : architecture, catalogue, ressources, noms.
        Renvoie (étiquette_de_profil, vms) ou None si rien à faire."""
        distros = list(mod.DISTROS)

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
                    return None

        def arches_for(distro):
            return self._qemu_arches_for(distro, arch)

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
            # combinaisons précises par numéros séparés de virgules. La liste
            # vient du catalogue partagé avec le formulaire TUI.
            flat = self._qemu_catalog_entries(mod, distros, arch)
            print(f"\n{t('All versions:')}")
            for i, e in enumerate(flat, 1):
                star = " *" if e["default"] else ""
                print(
                    f"  [{i}] {e['distro']} {e['version']}{star} "
                    f"[{e['arch']}]  (RAM≥{e['ram']}Mo, {e['disk']})"
                )
            r = (
                input(t("Selection (comma-separated numbers): "))
                .strip()
                .lower()
            )
            for e in self._parse_index_selection(r, flat):
                selected.append(
                    (e["distro"], e["version"], e["ram"], e["disk"], e["arch"])
                )
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
                return None
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
            return None

        # 2b) Ressources par VM : multiplicateur x1..x4 ou « Personnalisé ».
        # Le profil est CUIT dans `selected`, qui porte dès lors les valeurs
        # finales — RAM, disque et vCPU — pour chaque VM.
        host_cpu = os.cpu_count() or 2
        free_ram = self._host_free_ram_mb()
        res_label, selected = self._qemu_prompt_resources(
            selected, host_cpu, free_ram
        )

        # 2c) Personnalisation par VM : nom, disque, RAM, vCPU (à la demande).
        names, selected = self._qemu_customize_vms(selected, host_cpu)

        vms = [
            self._qemu_make_vm(d, v, a, ram, disk, vcpus, names[i])
            for i, (d, v, ram, disk, a, vcpus) in enumerate(selected)
        ]
        self._qemu_print_plan(vms, res_label, host_cpu, free_ram)
        return res_label, vms

    def _qemu_print_plan(self, vms, res_label, host_cpu, free_ram):
        """Plan + estimation des ressources de l'hôte."""
        total_ram = sum(vm["ram"] for vm in vms)
        total_disk = sum(self._parse_disk_gb(vm["disk"]) for vm in vms)
        total_cpu = sum(vm["vcpus"] for vm in vms)
        print(f"\n{t('Deployment plan')} ({len(vms)} VM, {res_label}) :")
        for vm in vms:
            print(
                f"  - {vm['name']:<30} {vm['distro']} {vm['version']:<7} "
                f"[{vm['arch']:<5}] {vm['vcpus']} vCPU  RAM {vm['ram']}Mo  "
                f"{t('disk')} {vm['disk']}"
            )
        cpu_warn = (
            f"   ⚠ {t('> host cores')} ({host_cpu})"
            if (total_cpu > host_cpu)
            else ""
        )
        print(f"\n  {t('Total vCPU (all running):')} {total_cpu}{cpu_warn}")
        print(f"  {t('Total RAM (all running):')} {total_ram} Mo")
        print(f"  {t('Total virtual disk (thin qcow2):')} ~{total_disk} G")
        if free_ram:
            print(f"  {t('Host RAM available:')} {free_ram} Mo")
            if total_ram > free_ram:
                warn = t(
                    "Total RAM exceeds host free RAM: not all VMs will run"
                    " at once."
                )
                print(f"  ⚠ {warn}")

    def _qemu_ask_desktop(self):
        """Serveur, ou serveur plus un bureau. Renvoie "" ou la saveur.

        Serveur par défaut : c'est ce que sert une image cloud, et le bureau
        ajoute une à deux heures d'installation sur une architecture émulée."""
        print(f"\n{t('VM type:')}")
        print(f"  [1] {t('Server (no graphical interface)')} *")
        flavours = list(self._QEMU_DESKTOP)
        for i, key in enumerate(flavours, 2):
            label = self._QEMU_DESKTOP[key]["label"]
            print(f"  [{i}] {t('Graphical (server + desktop):')} {label}")
        sel = input(t("Choice (number, blank = server): ")).strip()
        try:
            index = int(sel) - 2
        except ValueError:
            return ""
        return flavours[index] if 0 <= index < len(flavours) else ""

    @classmethod
    def _qemu_app_store_needed(cls, vms):
        """Vrai si au moins une VM du parc est à la fois graphique et d'une
        distribution qui livre snapd. Ailleurs la question n'a pas d'objet :
        un serveur ne tire aucun snap, et Debian ou Fedora n'en livrent pas."""
        return any(
            vm.get("desktop") and vm.get("distro") in cls.QEMU_SNAP_DISTROS
            for vm in vms
        )

    def _qemu_ask_app_store(self, vms):
        """Magasin d'applications des VM graphiques Ubuntu."""
        if not self._qemu_app_store_needed(vms):
            return "deb"
        print(f"\n{t('Application store (graphical Ubuntu VMs):')}")
        for i, (_key, label) in enumerate(self.QEMU_APP_STORES, 1):
            star = " *" if i == 1 else ""
            print(f"  [{i}] {t(label)}{star}")
        print(f"  ⚠ {t('snap needs the store; slow under emulation.')}")
        answer = input(f"{t('Choice')} [1]: ").strip() or "1"
        if answer.isdigit() and 1 <= int(answer) <= len(self.QEMU_APP_STORES):
            return self.QEMU_APP_STORES[int(answer) - 1][0]
        return "deb"

    def _qemu_ask_vm_tools(self, vms):
        """Outils de développement des VM graphiques : liste à cocher.

        Ne montre que ce qu'au moins une VM du parc peut recevoir : les IDE
        graphiques disparaissent d'un parc de serveurs, où ils n'auraient rien
        pour s'afficher, et la compilation mobile reste offerte — elle compile,
        elle n'affiche pas. La réponse vaut pour tout le parc et sera filtrée
        machine par machine.

        Saisie par numéros séparés par des espaces ou des virgules, « tous »
        pour tout cocher, vide pour rien : quatre questions oui/non de plus
        alourdiraient une séquence d'invites déjà longue."""
        choices = [
            c
            for c in self._qemu_vm_tool_choices()
            if any(
                self._qemu_tools_for(
                    (c[0],),
                    vm.get("arch", "amd64"),
                    vm.get("desktop", ""),
                    vm.get("distro", ""),
                )
                for vm in vms
            )
        ]
        if not choices:
            return ()
        print(f"\n{t('Development tools:')}")
        for i, (_key, label, hint) in enumerate(choices, 1):
            print(f"  [{i}] {label} — {hint}")
        gb = ", ".join(
            f"{label} +{self._QEMU_VM_TOOLS[key]['disk_gb']} Go"
            for key, label, _hint in choices
        )
        # Le mobile fait échouer la VM quand l'application ne compile pas :
        # c'est le but, mais il vaut mieux le savoir avant de cocher.
        if any(k == "mobile" for k, _l, _h in choices):
            print(f"  ⚠ {t('a failed mobile build marks the VM as failed')}")
        print(f"  {t('Disk needed:')} {gb}")
        answer = input(
            f"{t('Numbers separated by spaces, [all], blank = none:')} "
        ).strip()
        if not answer:
            return ()
        if answer.lower() in ("all", "tous", "toutes", "*"):
            return tuple(key for key, _l, _h in choices)
        picked = []
        for token in answer.replace(",", " ").split():
            if token.isdigit() and 1 <= int(token) <= len(choices):
                key = choices[int(token) - 1][0]
                if key not in picked:
                    picked.append(key)
        return tuple(picked)

    def _qemu_ask_python_provider(self, arches):
        """mise (CPython précompilé) ou pyenv (compilation).

        `arches` : les architectures du parc à déployer. mise ne publie pas de
        binaire pour toutes — hors de QEMU_MISE_ARCHES la question n'a pas de
        sens et on ne la pose pas."""
        usable = [a for a in arches if a in self.QEMU_MISE_ARCHES]
        if not usable:
            # Rien, pas « pyenv » : le mode automatique doit rester libre de
            # préférer un Python de la distribution. Voir _python_provider()
            # dans le formulaire, même raisonnement.
            return ""
        print(f"\n{t('Python interpreter:')}")
        print(f"  [1] {t('mise (precompiled, faster)')} *")
        print(f"  [2] {t('pyenv (compiles from source)')}")
        skipped = [a for a in arches if a not in self.QEMU_MISE_ARCHES]
        if skipped:
            # Dit AVANT le déploiement plutôt que découvert dans un log.
            print(
                f"  ⚠ {t('mise has no binary for:')} "
                f"{', '.join(sorted(set(skipped)))} — "
                f"{t('those VMs use pyenv')}"
            )
        sel = input(t("Choice (number, blank = mise): ")).strip()
        return "pyenv" if sel == "2" else "mise"

    def _qemu_host_timezone(self):
        """Fuseau de l'hôte. Défini une seule fois, dans deploy_qemu.py, qui
        est aussi ce qui l'écrit dans le cloud-config : l'invite ne peut donc
        pas proposer un défaut différent de celui réellement appliqué."""
        try:
            mod = self._qemu_import_module()
            return mod.host_timezone()
        except Exception:
            return "UTC"

    def _qemu_ask_timezone(self):
        """Fuseau des VM à créer, celui de l'hôte par défaut.

        Une VM qui hérite du fuseau de son opérateur horodate ses journaux et
        ses bases comme lui ; en UTC l'écart ne se remarque qu'après coup."""
        default = self._qemu_host_timezone()
        answer = input(f"{t('Timezone for the VMs')} ({default}): ").strip()
        if not answer:
            return default
        # Un fuseau inconnu ne casse pas cloud-init : il l'ignore en silence et
        # la VM reste en UTC. Mieux vaut le refuser ici que le découvrir plus
        # tard sur des horodatages faux.
        if not os.path.exists(os.path.join("/usr/share/zoneinfo", answer)):
            print(f"⚠  {t('Unknown timezone, keeping')} {default}")
            return default
        return answer

    def _qemu_ask_locale(self):
        """Locale des VM. « C.UTF-8 » par défaut : les autres déclenchent un
        locale-gen dans l'invité, mesuré à 36 s sur s390x — payé à chaque
        déploiement pour un confort dont une VM jetable n'a pas besoin."""
        default = "C.UTF-8"
        answer = input(f"{t('Locale for the VMs')} ({default}): ").strip()
        return answer or default

    def _qemu_collect_options_cli(self, vms, res_label):
        """Invites en ligne : clé SSH, installation ERPLibre, ~/.ssh/config,
        parallélisme, puis récapitulatif et confirmation.
        Renvoie la spec complète, ou None si l'utilisateur renonce."""
        # Clé SSH (partagée par tout le parc). Sans clé, cloud-init n'en
        # injecte aucune : la VM démarre sans accès SSH, donc sans
        # installation ni vérification possibles. On propose donc d'en créer
        # une plutôt que de laisser passer un déploiement inutilisable.
        default_key = self._qemu_default_ssh_key()
        if not default_key:
            print(f"\n⚠  {t('No SSH public key found in ~/.ssh.')}")
            print(f"   {t('Without one the VMs start with no SSH access.')}")
            if self._is_yes_default_yes(input(t("Generate one now? (Y/n): "))):
                default_key = self._ssh_ensure_key()
        key_hint = default_key or t("none")
        ssh_key = input(f"{t('SSH public key path')} ({key_hint}): ").strip()
        if not ssh_key:
            ssh_key = default_key
        if ssh_key:
            ssh_key = os.path.expanduser(ssh_key)

        timezone = self._qemu_ask_timezone()
        locale = self._qemu_ask_locale()
        desktop = self._qemu_ask_desktop()
        # La CLI ne pose qu'un type pour tout le parc : on le recopie sur chaque
        # VM avant de décider du magasin, qui ne concerne que les graphiques.
        # Le nom suit le type, exactement comme dans le formulaire — c'est la
        # même fonction, pas une seconde implémentation.
        from script.todo.qemu_deploy_form import vm_name

        suffixes = self._qemu_desktop_suffixes()
        for _vm in vms:
            _vm.setdefault("desktop", desktop)
            _vm["name"] = vm_name(_vm["name"], _vm.get("desktop"), suffixes)
        app_store = self._qemu_ask_app_store(vms)
        vm_tools = self._qemu_ask_vm_tools(vms)
        python_provider = self._qemu_ask_python_provider(
            [vm["arch"] for vm in vms]
        )

        # 4) Option : installer ERPLibre dans ~/git/erplibre de chaque VM.
        install = None
        ans = input(
            t("Install ERPLibre into ~/git/erplibre on each VM? (Y/n): ")
        )
        if self._is_yes_default_yes(ans):
            branch = self._qemu_pick_branch()
            # dev (~/git, SELinux relâché) vs prod (/opt, confiné)
            prod = self._qemu_ask_prod()
            label, cmd = self._qemu_pick_install_profile()
            monitor = self._is_yes_default_yes(
                input(t("Interactive monitoring dashboard? (y/N): "))
            )
            install = {
                "branch": branch,
                "prod": prod,
                "label": label,
                "cmd": cmd,
                "monitor": monitor,
            }

        add_ssh_config = self._is_yes_default_yes(
            input(t("Add each VM to ~/.ssh/config? (Y/n): "))
        )

        # 5) Sépare les VM à CRÉER des déjà existantes AVANT de proposer le
        # parallélisme : on connaît alors le vrai nombre à déployer (affiché
        # dans le prompt) et on peut numéroter chaque tâche.
        pending, existing = self._qemu_split_existing(
            vms, self._qemu_list_domains()
        )
        n_jobs = len(pending)

        # Collisions de noms : une VM déjà définie est ignorée (rien n'est
        # écrasé), mais un qcow2 orphelin fera ÉCHOUER deploy_qemu, qui refuse
        # d'écraser sans --force. On le dit avant, pas après l'attente.
        if not self._qemu_confirm_collisions(
            existing, [vm["name"] for vm in pending]
        ):
            print(t("Cancelled."))
            return None
        if not pending:
            print(t("Nothing to create - every VM already exists."))
            return None

        # Nombre de déploiements en parallèle. Par défaut UNE EXÉCUTION PAR
        # INSTALLATION : le plafond du nombre de CPU ne s'applique pas, c'est
        # le nombre de VM qui fait foi. « n » retombe sur ce plafond, et un
        # chiffre vaut pour lui-même — même règle que les autres invites.
        default_par = n_jobs or 1
        cpu_par = min(n_jobs, os.cpu_count() or 4) or 1
        print(f"  [n] {t('limit to host cores')} ({cpu_par})")
        raw = (
            input(
                f"{t('Parallel deployments (default:')} {default_par}, "
                f"{n_jobs} {t('VMs')}): "
            )
            .strip()
            .lower()
        )
        if raw == "n":
            parallelism = cpu_par
        else:
            try:
                parallelism = max(1, int(raw)) if raw else default_par
            except ValueError:
                parallelism = default_par

        spec = {
            "res_label": res_label,
            "vms": pending,
            "existing": existing,
            "ssh_key": ssh_key,
            "timezone": timezone,
            "locale": locale,
            "desktop": desktop,
            "vm_tools": vm_tools,
            "python_provider": python_provider,
            "app_store": app_store,
            "install": install,
            "add_ssh_config": add_ssh_config,
            "parallelism": parallelism,
        }

        # 6) Récapitulatif final, puis confirmation. Toutes les réponses
        # données jusqu'ici sont rassemblées ici : c'est le dernier point où
        # une erreur de saisie se rattrape sans avoir rien créé.
        self._qemu_print_recap(spec, existing)
        if not self._confirm_or_discard(t("Deploy these VMs now? (Y/n): ")):
            print(t("Cancelled."))
            return None
        return spec

    def _qemu_deploy_jobs_cli(self, jobs, workers):
        """Déploiement parallèle, sortie texte. Renvoie
        [(nom, rc, sortie, durée)] — même contrat que la vue TUI."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _run(job):
            jid, jname, jparts = job
            j0 = time.time()
            res = subprocess.run(jparts, capture_output=True, text=True)
            out = (res.stdout or "") + (res.stderr or "")
            return jid, jname, res.returncode, out, time.time() - j0

        outcome = []
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
                for line in [ln for ln in out.strip().splitlines() if ln][-4:]:
                    print(f"    {line}")
                outcome.append((jname, rc, out, secs))
        return outcome

    def _qemu_deploy_jobs_tui(self, jobs, workers):
        """Même chose, en blocs repliables Textual. Renvoie None si textual
        manque, pour que l'appelant retombe sur la sortie texte."""
        from script.todo import textual_setup

        if not textual_setup.ensure():
            return None
        try:
            from script.todo.qemu_deploy_form import run_deploy_progress

            return run_deploy_progress(jobs, workers)
        except ImportError:
            return None

    def _qemu_run_spec(self, spec):
        """Exécute une spec de déploiement : création des VM en parallèle,
        résolution des IP, ~/.ssh/config, installation ERPLibre.

        Ne pose AUCUNE question — tous les choix sont dans la spec, d'où
        qu'elle vienne (invites en ligne ou formulaire TUI)."""
        pending = spec["vms"]
        deployed = list(spec.get("existing") or [])
        install = spec.get("install")
        install_branch = install["branch"] if install else None
        # Le type de VM est choisi machine par machine dans la TUI ; la CLI n'en
        # pose qu'un pour tout le parc. On ramene les deux a la meme carte, et
        # `desktop` reste la reponse a « faut-il installer un bureau quelque
        # part ? », qui declenche la phase d'installation.
        desktop_default = spec.get("desktop") or ""
        desktop_map = {
            vm["name"]: (vm.get("desktop", desktop_default) or "")
            for vm in pending
        }
        for _name in deployed:
            desktop_map.setdefault(_name, desktop_default)
        desktop = next((d for d in desktop_map.values() if d), "")
        python_provider = spec.get("python_provider") or ""
        app_store = spec.get("app_store") or "deb"
        # Outils de développement : cochés une fois pour tout le parc, puis
        # filtrés machine par machine (architecture, saveur de bureau).
        vm_tools = tuple(spec.get("vm_tools") or ())
        # Branche par VM : « » sur une VM veut dire « celle du formulaire ».
        branch_map = {
            vm["name"]: (vm.get("branch") or install_branch or "")
            for vm in pending
        }
        for _n in deployed:
            branch_map.setdefault(_n, install_branch or "")
        branch_multi = len(set(branch_map.values())) > 1
        base_cmd = install["cmd"] if install else None
        cmd_map = {
            vm["name"]: (vm.get("install_cmd") or base_cmd) for vm in pending
        }
        for _n in deployed:
            cmd_map.setdefault(_n, base_cmd)
        cmd_multi = len(set(cmd_map.values())) > 1
        ssh_key = spec.get("ssh_key")
        add_ssh_config = spec["add_ssh_config"]
        parallelism = spec["parallelism"]
        n_jobs = len(pending)

        # Jobs numérotés (k/N) : l'ID suit l'ORDRE de préparation, stable même
        # si les résultats reviennent dans le désordre (exécution parallèle).
        jobs = []  # (id, name, parts)
        for k, vm in enumerate(pending, 1):
            parts = self._qemu_deploy_parts_for(vm, spec, dry_run=False)
            jobs.append((f"{k}/{n_jobs}", vm["name"], parts))

        deploy_start = time.time()
        n_ok = 0
        if jobs:
            workers = min(parallelism, len(jobs))
            print(
                f"\n{t('Deploying')} {len(jobs)} VM "
                f"({t('parallel jobs:')} {workers})…"
            )
            if todo_prefs.get("qemu_deploy_progress") == "tui":
                outcome = self._qemu_deploy_jobs_tui(jobs, workers)
            else:
                outcome = None
            if outcome is None:
                outcome = self._qemu_deploy_jobs_cli(jobs, workers)
            for name, rc, _out, _secs in outcome:
                if rc == 0:
                    deployed.append(name)
                    n_ok += 1
            print(
                f"\n{t('Deploy summary:')} {n_ok} OK, "
                f"{len(jobs) - n_ok} {t('failed')}, "
                f"{len(jobs)} {t('VMs')}, "
                f"{self._fmt_dur(time.time() - deploy_start)}"
            )

        # 6) Résolution des IP EN PARALLÈLE (réutilisée pour ssh_config +
        # install) : une boucle EN SÉRIE bloquait plusieurs minutes par VM
        # émulée SANS sortie -> le dashboard « n'ouvrait jamais ».
        ip_map = {}
        # `desktop` compte aussi : sans IP résolue, l'installation du bureau
        # n'aurait aucune VM à joindre.
        if deployed and (add_ssh_config or install_branch or desktop):
            labels = {
                nm: f"{k}/{len(deployed)}" for k, nm in enumerate(deployed, 1)
            }
            ip_map = self._qemu_resolve_ips(deployed, labels)

        if add_ssh_config:
            # La clé injectée par cloud-init est celle de la spec : c'est
            # elle que doit présenter ssh, pas la première venue de l'agent.
            identity = self._ssh_private_key(ssh_key)
            for name in deployed:
                ip = ip_map.get(name)
                if ip:
                    self._write_ssh_config_entry(
                        name, "erplibre", ip, identity_file=identity
                    )

        # 7) Installation ERPLibre (clone + make) et/ou bureau GNOME. Le bureau
        # ne dépend PAS d'ERPLibre : une VM peut être voulue graphique et nue.
        # Il passe par la même commande distante, donc par le même suivi.
        if install or desktop:
            monitor = install["monitor"] if install else True
            if monitor:
                # Installs détachées en parallèle + dashboard Textual.
                self._qemu_install_erplibre_monitored(
                    deployed,
                    branch_map if branch_multi else install_branch,
                    ip_map,
                    cmd_map if cmd_multi else base_cmd,
                    install["prod"] if install else False,
                    desktop=desktop_map,
                    python_provider=python_provider,
                    app_store=app_store,
                    vm_tools=vm_tools,
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
                        install["cmd"],
                        install["prod"],
                        desktop=desktop_map.get(name, ""),
                        python_provider=python_provider,
                        app_store=app_store,
                        vm_tools=vm_tools,
                    )

        # Sommaire TOTAL (déploiement + résolution IP + ssh_config + install
        # synchrone ; l'install monitorée est détachée, non comptée ici).
        print(f"\n{'═' * 60}")
        print(f"  {t('TOTAL summary')}")
        print(
            f"  {t('VMs deployed:')} {n_ok}/{len(jobs) if jobs else 0}"
            f"  ({t('total incl. existing:')} {len(deployed)})"
        )
        print(
            f"  {t('Total time:')} {self._fmt_dur(time.time() - deploy_start)}"
        )
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

    @staticmethod
    def _ssh_config_hosts():
        """Noms d'hôtes déclarés dans ~/.ssh/config, dans l'ordre du fichier.

        Une ligne « Host » peut porter plusieurs noms : on les rend tous. Les
        motifs (`*`, `?`) sont écartés — ce sont des règles, pas des machines
        auxquelles se connecter."""
        path = os.path.expanduser("~/.ssh/config")
        names = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if not re.match(r"^[ \t]*Host[ \t]+", line):
                        continue
                    for name in line.split()[1:]:
                        if "*" in name or "?" in name or name in names:
                            continue
                        names.append(name)
        except OSError:
            pass
        return names

    @staticmethod
    def _ssh_config_user(host):
        """`User` déclaré pour cet hôte dans ~/.ssh/config, ou "".

        On suit la règle d'OpenSSH : le PREMIER `User` rencontré parmi les
        blocs qui correspondent l'emporte, motifs (`Host *`) compris. Sans
        déclaration on renvoie "" — il n'y a alors rien à copier, et
        l'appelant garde son défaut plutôt que d'inventer le nom de session
        locale."""
        import fnmatch

        path = os.path.expanduser("~/.ssh/config")
        matching = False
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if re.match(r"^Host[ \t]+", stripped):
                        matching = any(
                            fnmatch.fnmatch(host, pattern)
                            for pattern in stripped.split()[1:]
                        )
                        continue
                    if matching:
                        found = re.match(
                            r"^User[ \t]+(\S+)", stripped, re.IGNORECASE
                        )
                        if found:
                            return found.group(1)
        except OSError:
            pass
        return ""

    @staticmethod
    def _port_is_free(port):
        """Vrai si rien n'écoute sur ce port en local."""
        import socket

        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", int(port)))
                return True
            except OSError:
                return False

    @staticmethod
    def _remote_port_open(host, port):
        """Quelqu'un écoute-t-il sur ce port DEPUIS l'hôte distant ?

        True / False / None quand on n'a pas pu conclure (hôte injoignable,
        pas de bash). On teste une vraie connexion TCP vers « localhost » et
        non la table d'écoute : c'est exactement ce que fera le tunnel, y
        compris le choix IPv4/IPv6 de la résolution.
        """
        probe = (
            f"exec 3<>/dev/tcp/localhost/{int(port)} && echo OPEN"
            " || echo CLOSED"
        )
        try:
            res = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    host,
                    f"bash -c {shlex.quote(probe)} 2>/dev/null",
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        out = res.stdout.strip()
        if "OPEN" in out:
            return True
        if "CLOSED" in out:
            return False
        return None

    def _deploy_port_forward(self):
        """Ouvre un tunnel SSH pour joindre un service distant depuis le
        navigateur local.

        Le port distant est vu DEPUIS la machine cible : « -L
        local:localhost:distant ». Un rebond éventuel n'a pas à être indiqué —
        le ProxyJump du bloc ~/.ssh/config s'applique tout seul, ce qui rend
        joignable une VM imbriquée sans route directe."""
        print(f"\n🔌 {t('SSH port forwarding')}")
        hosts = self._ssh_config_hosts()
        if hosts:
            for i, name in enumerate(hosts, 1):
                print(f"  [{i}] {name}")
        host = input(f"{t('Host (number or name):')} ").strip()
        if not host:
            print(t("Cancelled."))
            return
        if host.isdigit() and 1 <= int(host) <= len(hosts):
            host = hosts[int(host) - 1]

        raw = input(f"{t('Remote port (default:')} 8069): ").strip()
        remote = raw if raw.isdigit() else "8069"
        raw = input(f"{t('Local port (default:')} {remote}): ").strip()
        local = raw if raw.isdigit() else remote

        # Sonde AVANT d'ouvrir : sans elle, un service arrêté à l'autre bout
        # ne se manifeste que par un mur de « channel N: open failed » à
        # chaque requête du navigateur, qui ne dit pas d'où vient le refus.
        print(f"  {t('Checking the remote port...')}")
        listening = self._remote_port_open(host, remote)
        if listening is False:
            print(
                f"  ⚠ {t('Nothing is listening on port')} {remote}"
                f" {t('of')} {host}"
            )
            print(f"    {t('Start the service there, or continue anyway.')}")
            if not self._is_yes(input(t("Continue anyway? (y/N): "))):
                return
        elif listening is None:
            print(f"  ℹ️  {t('Could not probe the remote port; going on.')}")

        if not self._port_is_free(local):
            print(f"  ⚠ {t('Local port already in use:')} {local}")
            if not self._is_yes(input(t("Try anyway? (y/N): "))):
                return
        if local != remote:
            # Odoo redirige d'après web.base.url : un port local différent
            # renvoie le navigateur vers une adresse qui n'existe pas chez lui.
            print(f"  ⚠ {t('Local port differs from the remote one.')}")
            print(f"    {t('Odoo redirects using web.base.url; check it')}")
            print(f"    {t('matches http://localhost:')}{local}")

        cmd = f"ssh -N -L {local}:localhost:{remote} {shlex.quote(host)}"
        print(f"\n  🌐 http://localhost:{local}")
        print(f"  {t('Will execute:')} {cmd}")
        print(f"  {t('Ctrl+C closes the tunnel.')}\n")
        try:
            self.execute.exec_command_live(cmd, source_erplibre=False)
        except KeyboardInterrupt:
            pass
        print(f"\n  {t('Tunnel closed.')}")

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

        # -o follow_symlinks : sshfs résout les liens symboliques CÔTÉ SERVEUR.
        # Indispensable pour les dépôts google-repo (ERPLibre) : leur .git est
        # une chaîne de symlinks relatifs profonds (.repo/projects -> project-
        # objects) que git ne peut pas traverser sur un montage sshfs par
        # défaut (« erreur à la lecture de .git » -> git status/commit KO).
        cmd = f"sshfs -o follow_symlinks {target} {mount_point}"
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

        # Déplacé depuis le menu Execute : mise à jour de tout le code source
        # de dev en staging (sous-menu de mise à jour).
        choices.append(
            {
                "prompt_description": t(
                    "Update - Update all developed staging source code"
                ),
            }
        )

        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(choices)):
                self.prompt_execute_update()
            elif status == str(len(choices) - 1):
                self.debug_ide()
            elif status == str(len(choices) - 2):
                self.upgrade_module()
            elif status == str(len(choices) - 3):
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
                content = content.replace("your@email.com", email)
                content = content.replace("Your Name", name)

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

    def prompt_execute_analyse(self):
        """Analyses d'une base Odoo, en lecture seule.

        Toute LECTURE passe par une connexion psql ouverte avec
        `default_transaction_read_only=on` : c'est le serveur qui refuse
        l'écriture, pas une promesse du code.

        Une seule action écrit — installer les modules suggérés, à la fin
        de l'analyse [5]. Elle ne part jamais seule : question explicite,
        défaut à « non », liste à confirmer, et refus net si le checkout
        n'est pas sur la version de la base.
        """
        print(f"🤖 {t('Analyse a database. Reading never writes.')}")
        choices = [
            {"section": t("Structure")},
            {"prompt_description": t("Tables and database size")},
            {"section": t("Customisation")},
            {
                "prompt_description": t(
                    "Customised views, website copies included"
                )
            },
            {"prompt_description": t("Studio and hand-made x_ fields")},
            {"section": t("Migration")},
            {"prompt_description": t("Quality of a migration, step by step")},
            {"section": t("Modules")},
            {
                "prompt_description": t(
                    "Modules missing from the default package"
                )
            },
            {"section": t("Files")},
            {
                "prompt_description": t(
                    "Attachment files missing from the filestore"
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
                self.execute_analyse_schema_size()
            elif status == "2":
                self.execute_analyse_view_custom()
            elif status == "3":
                self.execute_analyse_custom_field()
            elif status == "4":
                self.execute_analyse_migration_quality()
            elif status == "5":
                self.execute_analyse_module_package()
            elif status == "6":
                self.execute_analyse_filestore()
            else:
                print(t("Command not found !"))

    def execute_analyse_module_package(self):
        """Ce que la base n'a pas, alors que l'installation par défaut l'a.

        Pas de choix « sauvegarde .zip » ici, contrairement aux autres
        analyses : l'outil interroge `ir_module_module`, qu'un zip
        n'expose pas sans restauration. Proposer l'option pour la refuser
        ensuite ferait perdre le temps de la choisir.
        """
        from script.analyse import check_module_package as modules

        database = self._analyse_select_database()
        if not database:
            return
        try:
            rapport = modules.audit(database)
        except Exception as exc:
            print(f"❌ {t('Analysis failed: ')}{exc}")
            return
        if rapport.get("unavailable"):
            print(f"❌ {t('Cannot read the database: ')}{database}")
            return
        print("\n".join(modules.render(rapport, limit=8)))
        self._analyse_offer_install(database, rapport)

        def handler(rank):
            if rank == 1:
                print("\n".join(modules.render(rapport, limit=0)))
            elif rank == 2:
                for nom in sorted(modules.read_packages()):
                    print(f"   {nom}")
            else:
                self._analyse_export_json(
                    rapport, os.path.basename(database), "module_package"
                )

        self._analyse_follow_up(
            [
                {"prompt_description": t("Show every entry")},
                {"prompt_description": t("List the known packages")},
                {"prompt_description": t("Export as JSON")},
            ],
            handler,
        )

    def execute_analyse_filestore(self):
        """Ce qui manque au filestore, et ce qu'on peut encore récupérer.

        Pas d'option « sauvegarde .zip » : l'outil compare une BASE à son
        filestore, et un zip porte les deux ensemble par construction —
        il n'y a rien à y trouver.
        """
        from script.analyse import check_filestore as filestore

        database = self._analyse_select_database()
        if not database:
            return
        print(f"⧖ {t('Scanning filestores and backups…')}")
        try:
            rapport = filestore.audit(database)
        except Exception as exc:
            print(f"❌ {t('Analysis failed: ')}{exc}")
            return
        if rapport.get("unavailable"):
            print(f"❌ {t('Cannot read the database: ')}{database}")
            return
        etat = {"rapport": rapport}
        print("\n".join(filestore.render(rapport, limit=20)))

        def relire():
            """Relire APRÈS une réparation.

            Sans cela « Tout afficher » rejouait le rapport d'avant :
            on purgeait, on relisait, et l'on voyait encore ce qui
            venait de disparaître. Pire, on repurgeait des lignes déjà
            effacées en croyant le travail inachevé.
            """
            print(f"⧖ {t('Scanning filestores and backups…')}")
            etat["rapport"] = filestore.audit(database)

        def handler(rank):
            if rank == 1:
                print("\n".join(filestore.render(etat["rapport"], limit=0)))
            elif rank == 2:
                if self._filestore_purge_dead(database, etat["rapport"]):
                    relire()
            elif rank == 3:
                if self._filestore_tidy_nested(etat["rapport"]):
                    relire()
            else:
                self._analyse_export_json(
                    etat["rapport"], os.path.basename(database), "filestore"
                )

        self._analyse_follow_up(
            [
                {"prompt_description": t("Show every entry")},
                {
                    "prompt_description": t(
                        "🧹 Purge attachments whose field no longer exists"
                    )
                },
                {
                    "prompt_description": t(
                        "🧹 Tidy the nested filestore Odoo never reads"
                    )
                },
                {"prompt_description": t("Export as JSON")},
            ],
            handler,
        )

    def _filestore_purge_dead(self, database, rapport):
        """Effacer les pièces jointes dont le champ a disparu.

        La seule ÉCRITURE en base de tout le menu Analyse. Elle porte sur
        des lignes que plus rien ne lit — `res.country.image` est devenu
        `image_url`, calculé, en 13 — mais elle reste une suppression :
        question explicite, défaut à « non », et le compte est relu avant
        de partir.
        """
        from script.analyse import check_filestore as filestore
        from script.todo import auto_ask

        lignes = rapport["groups"]["dead_field"]
        sql = filestore.purge_dead_sql(rapport)
        if not sql:
            print(f"ℹ️  {t('Nothing to purge.')}")
            return False
        print()
        for texte in filestore.summarise(lignes):
            print(f"   {texte}")
        question = (
            f"💬 {t('Delete these')} {len(lignes)}"
            f" {t('attachment row(s) for good?')} (y/N) : "
        )
        if auto_ask.ask(question, default="n").strip().lower() not in (
            "y",
            "yes",
            "o",
        ):
            print(f"ℹ️  {t('Nothing was deleted.')}")
            return False
        status, sortie = self.execute.exec_command_live(
            f'psql -d {database} -c "{sql}"',
            source_erplibre=False,
            single_source_erplibre=True,
            return_status_and_output=True,
        )
        if status:
            print(f"❌ {t('The purge failed.')}")
            return False
        # Le nombre ANNONCÉ par PostgreSQL, pas celui qu'on espérait :
        # rejouer une purge déjà faite rendait « DELETE 0 » et l'outil
        # se félicitait quand même d'avoir supprimé.
        efface = filestore.rows_deleted(sortie)
        if efface is None:
            print(f"⚠ {t('The purge ran but said nothing.')}")
            return True
        print(f"✅ {efface} {t('attachment row(s) deleted.')}")
        return True

    def _filestore_tidy_nested(self, rapport):
        """Remonter ce qui manque, effacer les doublons purs.

        Deux tas, deux gestes. Écraser un fichier présent par une copie
        identique ne gagnerait rien et brouillerait la trace ; c'est
        pourquoi les doublons sont comptés à part et jamais déplacés.
        """
        from script.analyse import check_filestore as filestore
        from script.todo import auto_ask

        remonter, doublons = filestore.tidy_nested_plan(rapport)
        if not remonter and not doublons:
            print(f"ℹ️  {t('No nested filestore to tidy.')}")
            return False
        print()
        print(f"   {len(remonter)} {t('file(s) to move up')}")
        print(f"   {len(doublons)} {t('pure duplicate(s) to delete')}")
        print(f"   {t('Directory:')} {filestore.nested_dir(rapport)}")
        if auto_ask.ask(
            f"💬 {t('Go ahead?')} (y/N) : ", default="n"
        ).strip().lower() not in ("y", "yes", "o"):
            print(f"ℹ️  {t('Nothing was moved.')}")
            return False
        deplaces, effaces = 0, 0
        for source, cible in remonter:
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            shutil.move(source, cible)
            deplaces += 1
        for source, _cible in doublons:
            os.remove(source)
            effaces += 1
        dossier = filestore.nested_dir(rapport)
        if dossier:
            shutil.rmtree(dossier, ignore_errors=True)
        print(
            f"✅ {deplaces} {t('moved up')}, {effaces}"
            f" {t('duplicate(s) removed')}."
        )
        return True

    def _analyse_offer_install(self, database, rapport):
        """Proposer d'installer ce qui manque, quand c'est installable.

        Seuls les modules « available » sont offerts. Le dire est
        nécessaire : le rapport vient d'en annoncer onze, la liste n'en
        montre qu'un, et sans un mot on croirait à un bogue.

        C'est la seule écriture de tout le menu Analyse, d'où trois
        garde-fous : la version du checkout doit être celle de la base —
        un Odoo 18 lancé sur une base 12 la réécrit avant d'échouer —, la
        question par défaut est « non », et la liste choisie est
        confirmée avant que rien ne parte.
        """
        from script.analyse import check_module_package as modules
        from script.odoo.migration import database_cleanup
        from script.todo import auto_ask

        candidats = modules.installable(rapport)
        if not candidats:
            return
        autres = len(modules.missing(rapport)) - len(candidats)

        souci = database_cleanup.require_matching_version(database)
        if souci:
            print(f"\n⚠ {souci}")
            print(f"   {t('Cannot install from here.')}")
            return

        print()
        detail = f" ({autres} {t('need repair first')})" if autres else ""
        question = (
            f"💬 {t('Install some of the')} {len(candidats)}"
            f" {t('suggested module(s) waiting in this database?')}{detail}"
            f" (y/N) : "
        )
        if auto_ask.ask(question, default="n").strip().lower() not in (
            "y",
            "yes",
            "o",
        ):
            return

        print()
        for rang, nom in enumerate(candidats, start=1):
            print(f"   [{rang}] {nom}")
        print(f"   [a] {t('every one of them')}")
        print(f"   {t('Enter = cancel')}")
        choisis, refuses = modules.parse_selection(
            auto_ask.ask(f"💬 {t('Numbers, space separated:')} ", default=""),
            candidats,
        )
        # Un jeton refusé n'est JAMAIS avalé : en demander cinq et en
        # recevoir quatre sans un mot ferait croire l'installation faite.
        if refuses:
            print(f"⚠ {t('Ignored, not in the list:')} {' '.join(refuses)}")
        if not choisis:
            print(f"ℹ️  {t('Nothing selected.')}")
            return

        print()
        print(f"   {t('About to install into')} {database} :")
        print(f"       {', '.join(choisis)}")
        if auto_ask.ask(
            f"💬 {t('Go ahead?')} (y/N) : ", default="n"
        ).strip().lower() not in ("y", "yes", "o"):
            print(f"ℹ️  {t('Nothing selected.')}")
            return
        self.execute.exec_command_live(
            f"./script/addons/install_addons.sh {database}"
            f" {','.join(choisis)}",
            source_erplibre=False,
            single_source_erplibre=True,
        )

    def execute_analyse_migration_quality(self):
        """Ce qu'une migration a gagné et perdu, palier par palier.

        Appelé comme les autres analyses — même interpréteur, aucun
        sous-processus — mais l'écran plein est ouvert par l'outil
        lui-même, qui sait retomber sur son rapport texte s'il ne peut pas.

        Lecture seule de bout en bout : les bases de palier sont parfois la
        seule copie qui reste d'un état intermédiaire.
        """
        from script.analyse import check_migration_quality as quality

        dct = quality.read_progression()
        if not quality.chain(dct):
            print(f"\nℹ️  {t('No migration in progress.')}")
            return
        try:
            lst = quality.survey(
                dct, echo=lambda texte: print(f"⧖ {texte}", flush=True)
            )
        except Exception as exc:
            print(f"❌ {t('Analysis failed: ')}{exc}")
            return
        try:
            from script.analyse.check_migration_quality_tui import run_tui
        except Exception:
            run_tui = None
        if not (run_tui and run_tui(lst)):
            print(quality.render_text(lst))

    def _analyse_select_source(self):
        """(est_une_sauvegarde, cible), ou None si l'on renonce.

        La sauvegarde n'est pas un cas dégradé : restaurer celle d'une
        instance Enterprise sur une installation Community échoue — Odoo veut
        charger des modules qu'on n'a pas — donc c'est souvent la SEULE façon
        de lire ce qu'elle contient.
        """
        print()
        print(f"[1] {t('A database')}")
        print(f"[2] {t('A backup .zip, without restoring it')}")
        print(f"[0] {t('Back')}")
        answer = click.prompt(t("Command:"))
        print()
        if answer == "1":
            database = self._analyse_select_database()
            return (False, database) if database else None
        if answer == "2":
            path = self.db_manager.select_backup_path()
            return (True, path) if path else None
        return None

    def _analyse_select_database(self):
        """Faire choisir la base à analyser, ou None si on abandonne."""
        database = self.db_manager.select_database()
        return database or None

    def _analyse_json_path(self, database, tool):
        """Où écrire un export JSON. Le dossier est créé au besoin."""
        directory = os.path.join("private", "analyse", database)
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, f"{tool}.json")

    def _analyse_export_json(self, data, database, tool):
        """Écrire le résultat brut, et dire où.

        Sous `private/`, qui n'est pas versionné par convention : un rapport
        d'analyse porte des noms de vues, de champs et de sociétés du client.
        """
        path = self._analyse_json_path(database, tool)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        print(f"✅ {t('Written to: ')}{path}")

    def _analyse_follow_up(self, choices, handler):
        """Boucle « aller plus loin » après une analyse.

        Le rapport suggérait « utilisez -v », « --exact », « ajoutez --diff ».
        Dans un menu, c'est demander à l'utilisateur de sortir et de retaper
        une commande pour obtenir ce que le menu pouvait lui offrir. Les
        options sont donc devenues des entrées, et les conseils en ligne de
        commande ne s'affichent plus que dans la vraie ligne de commande.
        """
        help_info = self.fill_help_info(
            [{"section": t("Go further")}] + choices
        )
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            try:
                rank = int(status)
            except ValueError:
                rank = 0
            if not 1 <= rank <= len(choices):
                print(t("Command not found !"))
                continue
            if handler(rank) is False:
                return

    def execute_analyse_schema_size(self):
        """Poids de la base et tables qu'aucun modèle installé ne réclame.

        L'outil est importé et appelé, pas lancé en sous-processus : `todo.py`
        tourne déjà sous le même interpréteur, donc le sous-processus
        n'apporterait aucun isolement et coûterait un second démarrage.

        Contrepartie assumée de cet appel direct : une exception remonterait
        dans la boucle du menu et ferait sortir du TODO. D'où le `try`.
        """
        from script.analyse import analyse_schema_size as analyse

        target = self._analyse_select_source()
        if not target:
            return
        is_backup, database = target
        state = {"data": None, "exact": is_backup}

        def run(exact=False):
            try:
                state["data"] = (
                    analyse.collect_from_backup(database)
                    if is_backup
                    else analyse.collect(database, exact=exact)
                )
                state["exact"] = exact or is_backup
            except Exception as exc:
                print(f"❌ {t('Analysis failed: ')}{exc}")
                return False
            return True

        if not run():
            return
        print(analyse.render(state["data"], hints=False))

        def handler(rank):
            data = state["data"]
            if rank == 1:
                print(analyse.render(data, verbose=True, hints=False))
            elif rank == 2:
                print(f"⏳ {t('Counting rows exactly, one scan per table…')}")
                if run(exact=True):
                    print(analyse.render(state["data"], hints=False))
            else:
                self._analyse_export_json(
                    data, os.path.basename(database), "schema_size"
                )

        self._analyse_follow_up(
            [
                {"prompt_description": t("Show every table")},
                {"prompt_description": t("Count rows exactly (full scan)")},
                {"prompt_description": t("Export as JSON")},
            ],
            handler,
        )

    def execute_analyse_view_custom(self):
        """Vues qui ne viennent pas telles quelles d'un module, COW comprises."""
        from script.analyse import analyse_view_custom as analyse

        target = self._analyse_select_source()
        if not target:
            return
        is_backup, database = target
        state = {"data": None}

        def run(**kwargs):
            try:
                # Une sauvegarde compare déjà ses copies COW à la lecture :
                # les deux arch sont dans le dump, il n'y a rien à demander.
                state["data"] = (
                    analyse.collect_from_backup(database)
                    if is_backup
                    else analyse.collect(database, **kwargs)
                )
            except Exception as exc:
                print(f"❌ {t('Analysis failed: ')}{exc}")
                return False
            return True

        if not run():
            return
        print(analyse.render(state["data"], hints=False))
        if not state["data"]["findings"]:
            return

        # Comparer exige un registre Odoo chargé. Une sauvegarde n'en a pas,
        # et rien ne peut l'y ajouter : proposer quand même la comparaison
        # ferait trois entrées qui ne répondent pas, et une quatrième qui
        # réclamerait indéfiniment une comparaison impossible.
        can_compare = not is_backup
        state["tried"] = False

        def compare(scope):
            print(f"⏳ {t('Loading the Odoo registry, this takes a moment…')}")
            if not run(with_diff=True, scope=scope):
                return
            state["tried"] = True
            data = state["data"]
            print(analyse.render(data, hints=False))
            if data["compared_with_module_source"] and not [
                row for row in data["findings"] if row.get("differs")
            ]:
                print(f"✅ {t('No view differs from its module source.')}")

        def browse():
            """Ouvrir l'écran, ou dire précisément ce qui l'en empêche.

            Trois raisons distinctes, trois messages. Répondre « comparez
            d'abord » à quelqu'un qui vient de comparer lui reproche ce que
            l'outil n'a pas pu faire, et le laisse recommencer sans fin.
            """
            data = state["data"]
            if not state["tried"]:
                print(f"ℹ️  {t('Compare first, then browse.')}")
            elif not data.get("compared_with_module_source"):
                print(
                    f"⚠️  {t('No reference arch, so nothing was compared: ')}"
                    f"{data.get('arch_ref_error') or ''}"
                )
            elif not [row for row in data["findings"] if row.get("differs")]:
                print(f"✅ {t('No view differs from its module source.')}")
            elif not analyse.open_tui(data):
                print(analyse.render(data, verbose=True, hints=False))

        lst_choice = [{"prompt_description": t("Show every view")}]
        # La comparaison des copies COW n'a besoin d'aucun registre : les deux
        # arch sont dans la base, appariées par leur clé. Elle est donc offerte
        # partout, y compris sur une sauvegarde et sur une base dont la version
        # diffère du checkout — là où l'autre comparaison est refusée.
        has_cow = bool(state["data"]["counts"].get("website_cow_copy"))
        if has_cow:
            lst_choice.append(
                {
                    "prompt_description": t(
                        "Compare the website copies with the view they shadow"
                    )
                }
            )
        if can_compare:
            lst_choice += [
                {
                    "prompt_description": t(
                        "Compare the flagged views with the module source"
                    )
                },
                {
                    "prompt_description": t(
                        "Compare every view (slower, noisier)"
                    )
                },
                {"prompt_description": t("Browse the differences (TUI)")},
            ]
        lst_choice.append({"prompt_description": t("Export as JSON")})

        def compare_cow():
            if not run(with_cow_diff=True):
                return
            state["tried"] = True
            data = state["data"]
            print(analyse.render(data, hints=False))
            n = data.get("n_cow_compared") or 0
            n_diff = len([r for r in data["findings"] if r.get("differs")])
            print(
                f"  {n} {t('website copies compared with their module view,')}"
                f" {n_diff} {t('differ.')}"
            )

        def handler(rank):
            data = state["data"]
            offset = 1 if has_cow else 0
            if rank == 1:
                print(analyse.render(data, verbose=True, hints=False))
            elif has_cow and rank == 2:
                compare_cow()
            elif rank == len(lst_choice):
                self._analyse_export_json(
                    data, os.path.basename(database), "view_custom"
                )
            elif can_compare and rank == 2 + offset:
                compare("flagged")
            elif can_compare and rank == 3 + offset:
                compare("all")
            elif can_compare and rank == 4 + offset:
                browse()

        self._analyse_follow_up(lst_choice, handler)

    def execute_analyse_custom_field(self):
        """Champs et modèles ajoutés hors module : Studio, ou faits à la main.

        Deux provenances, parce que la plus utile est souvent la sauvegarde :
        restaurer celle d'une instance Enterprise sur une installation
        Community échoue — Odoo veut charger des modules qu'on n'a pas — alors
        que les champs Studio ne sont que des lignes de `ir_model_fields`, et
        qu'un dump.sql est du texte.
        """
        from script.analyse import analyse_custom_field as analyse

        target = self._analyse_select_source()
        if not target:
            return
        is_backup, database = target
        try:
            data = (
                analyse.collect_from_backup(database)
                if is_backup
                else analyse.collect(database)
            )
        except Exception as exc:
            print(f"❌ {t('Analysis failed: ')}{exc}")
            return
        print(analyse.render(data, hints=False))
        if not data["fields"] and not data["models"]:
            return

        def handler(rank):
            if rank == 1:
                print(analyse.render(data, verbose=True, hints=False))
            else:
                self._analyse_export_json(
                    data, os.path.basename(database), "custom_field"
                )

        self._analyse_follow_up(
            [
                {"prompt_description": t("Show every field")},
                {"prompt_description": t("Export as JSON")},
            ],
            handler,
        )

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
            {"prompt_description": t("Mail unit tests")},
            {"prompt_description": t("Analyse unit tests")},
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
            elif status == "4":
                self.execute_unit_tests("test_mail*.py")
            elif status == "5":
                self.execute_unit_tests("test_analyse*.py")
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

    def execute_unit_tests(self, pattern="test_*.py"):
        """Lance `unittest discover` sur un SOUS-ENSEMBLE de la suite.

        Le motif est le seul paramètre : la suite complète dure plusieurs
        minutes, dominées par les tests TUI montés, et attendre tout pour
        vérifier un coin précis décourage de lancer les tests du tout. Une
        entrée de menu supplémentaire coûte donc un motif, pas une méthode.
        """
        print(f"\n--- {t('Running unit tests')} ---")
        # `-u` : unittest écrit son verdict sur STDERR, les `print()` des
        # tests sur STDOUT. Capturés ensemble, stderr passe sans tampon
        # tandis que stdout est tamponné par blocs — tout le stdout se
        # déversait donc APRÈS le « OK », qui se retrouvait noyé au milieu
        # de la sortie au lieu d'en être le dernier mot. Sans tampon, les
        # deux flux s'entrelacent dans l'ordre réel.
        cmd = (
            ".venv.erplibre/bin/python -u -m unittest discover"
            f" -s test -p '{pattern}' -v"
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
    except (KeyboardInterrupt, click.exceptions.Abort):
        # click.prompt() raises Abort (not a KeyboardInterrupt subclass) on
        # both Ctrl+C and Ctrl+D/EOF. run() only catches it for its own
        # top-level prompt; every submenu's click.prompt() would otherwise
        # let Abort escape here as an uncaught exception.
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
