#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import configparser
import datetime
import inspect
import json
import logging
import os
import re
import shlex
import shutil
import socket
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
from script.todo import dev_tools, todo_install, todo_prefs
from script.todo.database_manager import DatabaseManager
from script.todo.kdbx_manager import KdbxManager
from script.todo.longtest_menu import LongTestMenuMixin
from script.todo.proxmox_menu import ProxmoxMenuMixin
from script.todo.qemu_access import QemuAccessMixin
from script.todo.qemu_deploy import QemuDeployMixin
from script.todo.qemu_install import QemuInstallMixin
from script.todo.qemu_manage import QemuManageMixin
from script.todo.qemu_menu import QemuMenuMixin
from script.todo.qemu_recover import QemuRecoverMixin
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


class TODO(
    # L'ordre est celui de la lecture, pas de la résolution : aucun nom n'est
    # défini deux fois (une classe unique jusqu'ici), donc aucune priorité à
    # arbitrer. Chaque fichier porte un sujet, et son en-tête dit sa frontière.
    QemuMenuMixin,
    QemuDeployMixin,
    QemuInstallMixin,
    QemuManageMixin,
    QemuRecoverMixin,
    QemuAccessMixin,
    ProxmoxMenuMixin,
    LongTestMenuMixin,
):
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
[0] 🚪 {t("Quit")}
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
[8] {t("Git - Git and shell tools")}
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

        # Le mot de passe voyage par l'environnement, jamais par argv : la
        # ligne de commande est lisible par tout utilisateur de la machine.
        web_login_env = {}
        if kdbx_key:
            (
                extra_cmd_web_login,
                web_login_env,
            ) = self.kdbx_manager.get_extra_command_user(kdbx_key)
        elif odoo_user and odoo_password:
            web_login_env = {"EL_WEB_LOGIN_PWD_0": odoo_password}
            extra_cmd_web_login = (
                f" --default_email_auth {odoo_user}"
                " --default_password_auth_env EL_WEB_LOGIN_PWD_0"
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
                db_name,
                extra_cmd_web_login=extra_cmd_web_login,
                web_login_env=web_login_env,
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
                command=command,
                extra_cmd_web_login=extra_cmd_web_login,
                web_login_env=web_login_env,
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
        "prompt_execute_proxmox": "Proxmox VE",
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
                    "Proxmox VE - Deploy a VM on a remote host"
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
                self.prompt_execute_proxmox()
            elif status == "7":
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

    @staticmethod
    def _port_in_use(port):
        """Le port est-il déjà pris sur CETTE machine ?

        Un second tunnel sur le même port échouerait, et le message d'ssh
        (« bind: Address already in use ») se perd en mode détaché."""
        with socket.socket() as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", port)) == 0

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
        """Retire de ~/.ssh/config ce qui déclare l'un de `names`.

        On découpe en blocs plutôt que de substituer par expression
        régulière : une ligne Host peut porter PLUSIEURS noms.

        Deux règles, chacune corrigeant une perte de données CONSTATÉE dans
        le fichier d'un utilisateur.

        1. Seuls « Host » et « Match » clôturent un bloc. La règle d'avant —
           « une ligne non indentée clôt le bloc » — prenait l'indentation
           pour de la syntaxe, alors qu'elle est cosmétique dans ce format et
           qu'un fichier écrit à la main s'en passe souvent. Sur un bloc au
           corps non indenté, seule la ligne « Host » partait : HostName,
           User, IdentityFile et « StrictHostKeyChecking no » restaient, sans
           Host au-dessus, et ssh les rattachait au bloc PRÉCÉDENT. La
           vérification de clé d'hôte se retrouvait désactivée sur un serveur
           de production.

        2. Un bloc qui déclare AUSSI des noms qu'on ne retire pas survit,
           amputé de ceux-là seulement. Il partait en entier : « Host prod-db
           vm-a » perdait le prod-db de l'utilisateur, et le surnom qu'on
           ajoute à un bloc généré disparaissait au déploiement suivant.

        La queue du bloc — lignes vides et commentaires — n'est pas emportée :
        elle précède le plus souvent le bloc SUIVANT, et l'utilisateur y met
        ses propres notes.
        """
        drop = set(names)
        out, block, block_names = [], [], []

        def flush():
            if not block:
                return
            restants = [n for n in block_names if n not in drop]
            if restants == block_names:
                out.extend(block)
                return
            fin = len(block)
            while fin > 1 and (
                not block[fin - 1].strip()
                or block[fin - 1].lstrip().startswith("#")
            ):
                fin -= 1
            if restants:
                tete = block[0]
                marge = tete[: len(tete) - len(tete.lstrip())]
                out.append(f"{marge}Host {' '.join(restants)}\n")
                out.extend(block[1:fin])
            out.extend(block[fin:])

        for line in content.splitlines(keepends=True):
            if re.match(r"^[ \t]*Host[ \t]+", line, re.I):
                flush()
                block = [line]
                block_names = line.split()[1:]
            elif re.match(r"^[ \t]*Match[ \t]+", line, re.I):
                # Match ouvre une section qui n'appartient à aucun Host : la
                # garder telle quelle, quel que soit le sort du bloc d'avant.
                flush()
                block, block_names = [], []
                out.append(line)
            elif block:
                block.append(line)
            else:
                out.append(line)
        flush()
        return "".join(out)

    def _write_ssh_config_entry(
        self,
        host,
        user,
        ip,
        proxy_jump=None,
        identity_file=None,
        also_drop=(),
    ):
        """Écrit/remplace un bloc « Host <host> » dans ~/.ssh/config.

        `host` peut être une liste de noms : ils partagent alors un seul bloc.

        `also_drop` : noms dont le bloc doit DISPARAÎTRE sans être réécrit.
        Sert quand une convention de nommage change : l'ancienne entrée ne
        désigne pas le nom qu'on écrit, donc rien ne la retirerait, et deux
        blocs finiraient par mener à la même machine — ce qu'on venait
        justement d'enlever. L'appelant vérifie que l'ancien bloc est BIEN le
        sien avant de le nommer ici.

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
        existing = self._ssh_config_drop_hosts(
            existing, names + [n for n in also_drop if n not in names]
        ).rstrip("\n")
        if not names:
            # Retirer sans réécrire est un appel légitime : les machines
            # n'existent plus. Sans ce retour, un « Host » NU était écrit dans
            # le ~/.ssh/config de l'utilisateur — un bloc sans nom, suivi d'un
            # « HostName » vide, qui s'applique alors à rien et brouille la
            # lecture du fichier.
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write(existing + "\n" if existing else "")
            os.chmod(cfg, 0o600)
            retires = ", ".join(also_drop)
            print(f"🗑  {t('Removed from ~/.ssh/config:')} {retires}")
            return
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

    @staticmethod
    def _human_size(n):
        """Octets -> taille lisible (Ko/Mo/Go…)."""
        size = float(n)
        for unit in ("o", "Ko", "Mo", "Go", "To"):
            if size < 1024:
                return f"{size:.0f} {unit}"
            size /= 1024
        return f"{size:.0f} Po"

    # ------------------------------------------------------------------ #
    # QEMU : déploiement d'un parc « infra ERPLibre »
    # ------------------------------------------------------------------ #
    ERPLIBRE_GIT_URL = "https://github.com/erplibre/erplibre"

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
    def _host_disk_gb(path="/var/lib/libvirt/images"):
        """(libre, total) en Go du système de fichiers qui portera les disques.

        On remonte vers le premier parent qui existe : le répertoire d'images
        n'est créé qu'au premier déploiement, et « /var/lib/libvirt » ou « / »
        répondent de la même partition dans la quasi-totalité des cas. (0, 0)
        si rien ne répond — la place libre s'affiche alors comme inconnue
        plutôt qu'inventée.
        """
        chemin = path
        while chemin and not os.path.isdir(chemin):
            parent = os.path.dirname(chemin)
            if parent == chemin:
                break
            chemin = parent
        try:
            usage = shutil.disk_usage(chemin or "/")
        except OSError:
            return 0, 0
        return usage.free // (1 << 30), usage.total // (1 << 30)

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

    @staticmethod
    def _fmt_dur(secs):
        """Durée lisible : « 45s » ou « 2m05s »."""
        secs = int(secs)
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m{secs % 60:02d}s"

    # Cible d'installation Odoo exécutée dans la VM (défaut ERPLibre 1.6.0).
    ERPLIBRE_ODOO_TARGET = "install_odoo_18"
    # Go ajoutés au disque quand on installe ERPLibre (le minimum d'image ne
    # laisse que ~97 Mo libres après l'installation).
    ERPLIBRE_EXTRA_DISK_GB = 5

    @staticmethod
    def _plural(word, count):
        """Accord simple : « échec » / « échecs ». Vaut pour fr et en."""
        return word if abs(count) <= 1 else f"{word}s"

    # Les trois invites ci-dessous sont posées à DEUX endroits — le profil
    # global « Personnalisé » et la personnalisation par VM. Elles vivent donc
    # ici : une seule définition, mêmes suggestions, mêmes validations.
    # Chacune renvoie None pour « garder la valeur actuelle ».

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

    # ---------------------------------------------------------------- #
    # Déploiement : catalogue (pur) -> collecte (CLI ou TUI) -> exécution
    # ---------------------------------------------------------------- #

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

    @classmethod
    def _ssh_config_block(cls, name):
        """Le bloc « Host … » qui déclare `name`, ou {}.

        Rend ses noms ET ses directives : savoir qu'un nom est pris ne suffit
        pas, il faut savoir PAR QUI. Le ProxyJump distingue notre propre
        entrée — celle d'une VM derrière tel hôte — de celle d'une machine
        qui se trouve porter le même nom.

        {"names": [...], "proxyjump": "...", "hostname": "..."}."""
        path = os.path.expanduser("~/.ssh/config")
        try:
            with open(path, encoding="utf-8") as fh:
                contenu = fh.read()
        except OSError:
            return {}
        bloc = None
        for line in contenu.splitlines():
            if re.match(r"^[ \t]*Host[ \t]+", line):
                if bloc is not None:
                    return bloc
                noms = line.split()[1:]
                bloc = {"names": noms} if name in noms else None
                continue
            if bloc is None:
                continue
            # Une ligne non indentée et non vide clôt le bloc.
            if line.strip() and not line[:1].isspace():
                return bloc
            mots = line.split()
            if len(mots) >= 2 and mots[0].lower() in ("proxyjump", "hostname"):
                bloc[mots[0].lower()] = mots[1]
        return bloc or {}

    @classmethod
    def _ssh_jump_depth(cls, cible, maxi=12):
        """Nombre de rebonds pour joindre `cible`, en suivant la chaîne.

        C'est la mesure de PROFONDEUR d'un hôte imbriqué, et la seule dont on
        dispose de l'extérieur. Elle est exacte pour les hôtes que nous avons
        déployés : c'est nous qui écrivons ces entrées, un ProxyJump par
        étage.

        `maxi` borne le parcours : une boucle dans ~/.ssh/config — A qui
        rebondit par B qui rebondit par A — tournerait sinon sans fin.
        """
        vus, sauts = set(), 0
        courant = cible
        while sauts < maxi:
            bloc = cls._ssh_config_block(courant)
            saut = (bloc or {}).get("proxyjump")
            if not saut or saut in vus:
                break
            vus.add(saut)
            courant = saut
            sauts += 1
        return sauts

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

    # sshfs lit « a+b » comme un CHAÎNAGE d'hôtes — « ssh a, puis ssh b depuis
    # a » — et ne consulte donc PAS ~/.ssh/config pour l'alias entier. Or c'est
    # todo.py qui nomme les VM découvertes « jump+domaine » (voir la marche
    # SSH) : ce sont les alias les plus utiles, et les seuls que sshfs échoue à
    # monter tel quel. Vécu : « read: Connection reset by peer », parce que la
    # seconde moitié du nom est un domaine libvirt, pas un alias SSH du rebond.
    SSHFS_CHAIN_SEP = "+"

    # Options à rendre à sshfs quand on contourne l'alias : exactement celles
    # que todo.py écrit dans l'entrée qu'il génère. Sans elles, une VM dont la
    # clé d'hôte a changé — IP DHCP réutilisée — ferait échouer le montage.
    SSH_FORWARD_OPTS = (
        ("port", "Port"),
        ("proxyjump", "ProxyJump"),
        ("identityfile", "IdentityFile"),
        ("identitiesonly", "IdentitiesOnly"),
        ("stricthostkeychecking", "StrictHostKeyChecking"),
        ("userknownhostsfile", "UserKnownHostsFile"),
    )

    # Ce que dit stderr, et ce qu'il faut aller corriger. L'ordre compte : le
    # premier motif trouvé gagne.
    SSH_FAILURE_HINTS = (
        ("could not resolve hostname", "unknown host name: check HostName"),
        ("name or service not known", "unknown host name: check HostName"),
        ("connection timed out", "no answer: is the server up and reachable?"),
        ("operation timed out", "no answer: is the server up and reachable?"),
        ("no route to host", "no route: check the network or the ProxyJump"),
        ("connection refused", "nothing listening on the SSH port"),
        ("permission denied", "authentication refused: check User and key"),
        ("host key verification failed", "host key changed for this address"),
    )

    @staticmethod
    def _ssh_config_entries(path):
        """[(alias, {hostname, user})] de ~/.ssh/config, dans l'ordre du fichier.

        Pendant de `_ssh_config_hosts`, qui ne rend que les NOMS : ici le menu
        de montage a besoin d'afficher aussi l'adresse et l'utilisateur.

        « Host a b » déclare DEUX alias pour la même machine — c'est ce que
        todo.py écrit lui-même quand une VM porte plusieurs noms. Les prendre
        pour un seul nom donnait un alias « a b », que sshfs ne peut pas
        monter. Les motifs génériques (« * », « web-? ») sont écartés : ils ne
        désignent aucune machine.
        """
        hosts = []
        noms = []
        info = {}

        def clore():
            for nom in noms:
                hosts.append((nom, dict(info)))

        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lignes = fh.readlines()
        except OSError:
            return []
        for ligne in lignes:
            ligne = ligne.strip()
            if ligne.lower().startswith("host "):
                clore()
                noms = [
                    m
                    for m in ligne.split()[1:]
                    if "*" not in m and "?" not in m and not m.startswith("!")
                ]
                info = {}
            elif noms:
                paire = ligne.split(None, 1)
                if len(paire) == 2 and paire[0].lower() in (
                    "hostname",
                    "user",
                ):
                    info[paire[0].lower()] = paire[1].strip()
        clore()
        return hosts

    @staticmethod
    def _ssh_resolve(alias):
        """Configuration RÉSOLUE de l'alias, telle que ssh la voit (ssh -G).

        On délègue à ssh au lieu de relire le fichier : lui seul connaît les
        Include, les Match, l'ordre des motifs et ses propres défauts.
        """
        try:
            res = subprocess.run(
                ["ssh", "-G", alias],
                capture_output=True,
                text=True,
                timeout=15,
                env=TODO._qemu_c_env(),
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if res.returncode != 0:
            return {}
        out = {}
        for ligne in res.stdout.splitlines():
            cle, _, val = ligne.strip().partition(" ")
            # ssh -G répète « identityfile » : la PREMIÈRE est celle qui compte.
            if cle and val and cle.lower() not in out:
                out[cle.lower()] = val
        return out

    def _sshfs_command(self, alias, mount_point, resolved=None):
        """(commande sshfs, alias contourné ?) pour monter cet alias.

        Sans « + » dans le nom, on laisse sshfs faire : c'est ssh qui lit la
        config, et rien ne vaut mieux. Avec un « + », on résout l'alias
        soi-même et on rend à sshfs une cible qu'il ne peut plus mal lire.
        """
        base = "sshfs -o follow_symlinks"
        if self.SSHFS_CHAIN_SEP not in alias:
            return f"{base} {alias}:/ {mount_point}", False
        cfg = resolved if resolved is not None else self._ssh_resolve(alias)
        host = cfg.get("hostname")
        # Un hostname qui contient encore un « + » ne réglerait rien, et un
        # alias non résolu vaut mieux qu'une cible inventée.
        if not host or self.SSHFS_CHAIN_SEP in host:
            return f"{base} {alias}:/ {mount_point}", False
        opts = []
        for cle, nom in self.SSH_FORWARD_OPTS:
            val = cfg.get(cle)
            if val and val.lower() != "none":
                opts.append(f"-o {nom}={val}")
        user = cfg.get("user")
        cible = f"{user}@{host}" if user else host
        pieces = [base] + opts + [f"{cible}:/", mount_point]
        return " ".join(pieces), True

    @classmethod
    def _ssh_failure_hint(cls, stderr):
        """Première ligne utile de stderr, et ce qu'elle désigne."""
        texte = (stderr or "").lower()
        for motif, indice in cls.SSH_FAILURE_HINTS:
            if motif in texte:
                return indice
        return ""

    @staticmethod
    def _ssh_probe(alias, timeout=8):
        """(code, stderr) d'un « ssh <alias> true » sans invite de mot de passe.

        BatchMode : une invite bloquerait le menu. Un refus d'authentification
        se distingue donc d'un hôte injoignable, et le diagnostic le dit.
        """
        try:
            res = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={timeout}",
                    alias,
                    "true",
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 12,
                env=TODO._qemu_c_env(),
            )
        except subprocess.TimeoutExpired:
            return 255, "Connection timed out"
        except (OSError, subprocess.SubprocessError) as exc:
            return 255, str(exc)
        return res.returncode, res.stderr.strip()

    def _sshfs_diagnose(self, alias, mount_point, bypassed):
        """Dit POURQUOI le montage a échoué, et où aller corriger.

        Le message est ciblé, pas une liste de causes possibles : on interroge
        ssh, et selon qu'il passe ou non, le fautif n'est pas le même.
        """
        print(f"\n  ⚠ {t('sshfs mount failed.')}")
        if not alias:
            print(f"  → {t('Check the SSH host and that the server is up.')}")
            return
        print(f"  {t('Checking SSH access…')} ({alias})")
        code, err = self._ssh_probe(alias)
        if code == 0:
            print(f"  ✓ {t('SSH reaches this host: ~/.ssh/config is fine.')}")
            if not bypassed and self.SSHFS_CHAIN_SEP in alias:
                print(f"  → {t('sshfs reads the « + » as host chaining.')}")
                cmd, ok = self._sshfs_command(alias, mount_point)
                if ok:
                    print(f"  → {t('Run this instead:')}")
                    print(f"    {cmd}")
                else:
                    # Annoncer une commande puis n'en donner aucune serait
                    # pire que se taire : on dit ce qui manque.
                    print(
                        f"  → {t('ssh -G resolved nothing: check ~/.ssh/config.')}"
                    )
            else:
                print(f"  → {t('Is sshfs (and fuse) installed here?')}")
            return
        indice = self._ssh_failure_hint(err)
        if indice:
            print(f"  ✗ {t('SSH fails too:')} {t(indice)}")
        else:
            print(
                f"  ✗ {t('SSH fails too:')} {err.splitlines()[0] if err else code}"
            )
        print(f"  → {t('Update ~/.ssh/config, or check the server is up.')}")

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
            hosts = self._ssh_config_entries(ssh_config_path)

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
        # L'alias vient de ~/.ssh/config : c'est lui qui peut porter un « + »,
        # et lui qu'on peut interroger en cas d'échec. Une saisie manuelle est
        # rendue telle quelle — si elle contient un « + », c'est un chaînage
        # demandé exprès.
        alias = ssh_name if choice == "2" else ""
        if alias:
            cmd, bypassed = self._sshfs_command(alias, mount_point)
        else:
            cmd, bypassed = (
                f"sshfs -o follow_symlinks {target} {mount_point}",
                False,
            )
        print(f"{t('Mounting sshfs on: ')}{mount_point}")
        print(f"{t('Will execute:')} {cmd}")
        try:
            status = self.execute.exec_command_live(cmd, source_erplibre=False)
        except Exception as e:
            print(f"{t('Error mounting sshfs: ')}{e}")
            status = 1
        # Le reste ne s'affiche QUE si le montage a réussi : « Monté sur … »
        # après un code 1 envoyait chercher des fichiers dans un répertoire
        # vide, et faisait passer l'échec pour un détail.
        if status:
            self._sshfs_diagnose(alias, mount_point, bypassed)
            # Le point de montage n'a jamais servi : le laisser accumulerait
            # un répertoire vide dans /tmp à chaque tentative.
            try:
                os.rmdir(mount_point)
            except OSError:
                pass
            return
        print(f"{t('Mounted on: ')}{mount_point}")
        print("mount | grep sshfs")
        print(f"{t('To unmount: ')}" f"fusermount -u {mount_point}")
        print(f"nautilus {mount_point}/home/{user}")

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

    # Les hooks que le dépôt fournit. git saute silencieusement un hook qui
    # ne porte pas le bit d'exécution, d'où la vérification à l'installation.
    _GIT_HOOKS = ("commit-msg", "pre-commit")
    _GIT_HOOKS_PATH = os.path.join("script", "git", "hooks")

    def prompt_execute_git(self):
        print(f"🤖 {t('Git and shell management tools!')}")
        choices = [
            {"prompt_description": t("Local git server")},
            {"prompt_description": t("Add a remote to a local repository")},
            {
                "prompt_description": t(
                    "Install git hooks (commit-msg, pre-commit)"
                )
            },
            {
                "prompt_description": t(
                    "Set merge.conflictStyle to zdiff3 (global)"
                )
            },
        ]

        # Append config-driven entries
        config_entries = self.config_file.get_config("git_from_makefile")
        if config_entries:
            choices.extend(config_entries)

        # Starship ferme la liste : c'est un outil de shell, pas de git. Son
        # rang dépend du nombre d'entrées venues de todo.json, donc « method »
        # porte la destination dans l'entrée elle-même — un numéro codé en dur
        # mènerait ailleurs dès qu'une entrée de configuration s'ajoute.
        choices.append(
            {
                "prompt_description": t("Install Starship on Shell"),
                "method": "_shell_install_starship",
            }
        )
        choices.append(
            {
                "prompt_description": t("Install Claude Code"),
                "method": "_shell_install_claude_code",
            }
        )
        choices.append(
            {
                "prompt_description": t("Install opencode"),
                "method": "_shell_install_opencode",
            }
        )

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
            elif status == "3":
                self._git_install_hooks()
            elif status == "4":
                self._git_set_conflict_style()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(choices):
                        cmd_no_found = False
                        instance = choices[int_cmd - 1]
                        method = instance.get("method")
                        if method:
                            getattr(self, method)()
                        else:
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

    def _git_install_hooks(self):
        """Pointer core.hooksPath sur les hooks du dépôt.

        Le bit d'exécution fait partie de l'installation : sans lui git
        ignore le hook sans rien dire, et le garde-fou du message de commit
        passe inaperçu.
        """
        racine = self._claude_context_root()
        absolu = os.path.join(racine, self._GIT_HOOKS_PATH)
        if not os.path.isdir(absolu):
            print(f"{t('Hooks directory is missing: ')}{absolu}")
            return
        actuel = self._git_hooks_path(racine)
        if actuel and actuel != self._GIT_HOOKS_PATH:
            print(f"{t('Another hooks path is already set: ')}{actuel}")
            if not self._is_yes(input(t("Replace it? (y/Y): "))):
                print(t("Nothing to do."))
                return
        for hook in self._GIT_HOOKS:
            chemin = os.path.join(absolu, hook)
            if os.path.isfile(chemin) and not os.access(chemin, os.X_OK):
                os.chmod(chemin, os.stat(chemin).st_mode | 0o111)
                print(f"{t('Execution bit added: ')}{hook}")
        # « -C racine » et non le cwd : lancé depuis un dépôt imbriqué
        # (odoo18.0/addons/…), git écrirait core.hooksPath là-bas et la
        # racine resterait sans garde-fou, sans le moindre message.
        cmd = (
            f"git -C {shlex.quote(racine)} config"
            f" core.hooksPath {self._GIT_HOOKS_PATH}"
        )
        print(f"{t('Will execute:')} {cmd}")
        # exec_command_live RETOURNE le code de sortie, il ne lève rien : sans
        # ce test, un « fatal: not in a git directory » annonçait quand même
        # « Hooks git installés! ». Le rapport qui suit ne rattrape pas, il
        # relit le bit d'exécution et non core.hooksPath.
        status = self.execute.exec_command_live(cmd, source_erplibre=False)
        if status:
            print(f"{t('Error installing hooks: ')}{status}")
            return
        print(t("Git hooks installed!"))
        for hook in self._GIT_HOOKS:
            pose = os.access(os.path.join(absolu, hook), os.X_OK)
            marque = t("hook installed") if pose else t("hook not installed")
            print(f"   {hook:<26} {marque}")

    def _git_set_conflict_style(self):
        """Poser merge.conflictStyle=zdiff3 dans la configuration globale.

        zdiff3 ajoute la base commune aux marqueurs de conflit et sort de la
        zone contestée les lignes que les deux côtés ont en commun : il reste
        moins à arbitrer à la main. Le style demande git 2.35, que toutes les
        plateformes supportées dépassent.

        La valeur est relue après écriture : « git config » ne rend rien à
        l'écriture, et une configuration globale en lecture seule échouerait
        sans que le menu le sache.
        """
        status = self.execute.exec_command_live(
            "git config --global merge.conflictStyle zdiff3",
            source_erplibre=False,
        )
        if status:
            print(
                f"❌ {t('Failed to set merge.conflictStyle, see the output above.')}"
            )
            return
        result = self.execute.exec_command_live(
            "git config --global --get merge.conflictStyle",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        value = (
            " ".join(result[1]).strip() if isinstance(result, tuple) else ""
        )
        print(f"✅ merge.conflictStyle = {value}")

    # Le shell -> son fichier de configuration.
    _SHELL_RC = {
        "bash": "~/.bashrc",
        "zsh": "~/.zshrc",
        "fish": "~/.config/fish/config.fish",
    }

    # Ces quatre tables vivent dans dev_tools : le déploiement QEMU pose les
    # mêmes outils DANS une VM, et deux copies d'une URL amont dérivent dès
    # que l'une change. Les noms de classe restent, ils sont l'interface.
    _STARSHIP_LINE = dev_tools.STARSHIP_LINE
    _STARSHIP_UPSTREAM = dev_tools.STARSHIP_UPSTREAM
    _UPSTREAM_TOOLS = dev_tools.AGENTS

    @staticmethod
    def _shell_name():
        """Le nom du shell de l'utilisateur d'après $SHELL, '' s'il est vide."""
        return os.path.basename(os.environ.get("SHELL", "")).strip()

    def _shell_rc_present(self):
        """Les shells dont le fichier de configuration existe déjà."""
        return [
            nom
            for nom, fichier in self._SHELL_RC.items()
            if os.path.exists(os.path.expanduser(fichier))
        ]

    def _shell_rc_target(self):
        """Le shell à modifier. Ne demande que devant un vrai choix.

        Aucun fichier de configuration présent : bash, sans question — l'appel
        le créera. Un seul présent : celui-là, il n'y a rien à choisir. Deux ou
        trois : à l'opérateur de trancher, le sien proposé par défaut.
        """
        presents = self._shell_rc_present()
        if not presents:
            return "bash"
        if len(presents) == 1:
            return presents[0]
        courant = self._shell_name()
        defaut = courant if courant in presents else presents[0]
        print(f"\n{t('Which shell configuration?')}")
        for i, nom in enumerate(presents, 1):
            print(f"  [{i}] {nom:<5} {self._SHELL_RC[nom]}")
        sel = input(
            f"{t('Choice (number or name, default:')} {defaut}) : "
        ).strip()
        if not sel:
            return defaut
        if sel in presents:
            return sel
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(presents):
                return presents[idx]
        except ValueError:
            pass
        return defaut

    def _shell_rc_append(self, shell, ligne, marqueur):
        """Ajouter la ligne au fichier du shell si le marqueur n'y est pas.

        Rend le chemin du fichier quand la ligne est écrite, None quand le
        marqueur y était déjà. Le marqueur, et non la ligne entière, parce
        qu'une variante écrite à la main ou par un installateur amont compte
        autant : ce qui importe est que l'effet soit là, pas la graphie.
        """
        chemin = os.path.expanduser(self._SHELL_RC[shell])
        contenu = ""
        if os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as fh:
                contenu = fh.read()
        if marqueur in contenu:
            return None
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "a", encoding="utf-8") as fh:
            # Un fichier qui ne finit pas par un saut de ligne collerait la
            # ligne ajoutée à la dernière commande.
            if contenu and not contenu.endswith("\n"):
                fh.write("\n")
            fh.write(f"{ligne}\n")
        return chemin

    def _shell_path_line(self, shell, repertoire):
        """La ligne qui met un répertoire dans le PATH, selon le shell."""
        if shell == "fish":
            return f"fish_add_path {repertoire}"
        return f'export PATH="{repertoire}:$PATH"'

    def _shell_ensure_on_path(self, shell, repertoire):
        """Garantir que le répertoire est dans le PATH du shell choisi.

        Ne fait rien si le répertoire y figure déjà, quelle que soit la
        graphie — les installateurs amont écrivent souvent la ligne eux-mêmes.
        """
        ligne = self._shell_path_line(shell, repertoire)
        chemin = self._shell_rc_append(shell, ligne, repertoire)
        if chemin is None:
            print(f"✅ {t('Already on the PATH: ')}{repertoire}")
            return
        print(f"✅ {t('PATH line added to: ')}{chemin}")
        print(f"   {ligne}")

    def _shell_install_starship(self):
        """Poser starship, puis l'accrocher au shell de l'utilisateur.

        Deux étapes qui échouent séparément : le binaire, que le gestionnaire
        de paquets de la distribution fournit quand il le connaît, et la ligne
        d'initialisation dans le fichier de configuration du shell. Sans la
        seconde, starship est installé et le prompt ne change pas.
        """
        if shutil.which("starship") is None:
            self._shell_install_starship_binary()
        if shutil.which("starship") is None:
            print(
                f"❌ {t('starship is not installed, shell left untouched.')}"
            )
            return
        self._shell_hook_starship()

    def _shell_install_starship_binary(self):
        """Poser le binaire : le paquet de la distribution, sinon l'amont.

        Un refus de l'opérateur arrête là. Un paquet inconnu ou une
        installation en échec passent au recours amont, qui couvre les dépôts
        où starship n'est pas empaqueté.
        """
        cmd = todo_install.install_command(["starship"])
        if cmd:
            status = todo_install.ask_and_install(
                self.execute,
                cmd,
                t("Install starship? (y/N): "),
                self._is_yes,
            )
            if status is None:
                return
            if status == 0 and shutil.which("starship"):
                return
        print(f"  {t('No starship package here, falling back upstream.')}")
        todo_install.ask_and_install(
            self.execute,
            self._STARSHIP_UPSTREAM,
            t("Run the upstream installer? (y/N): "),
            self._is_yes,
        )

    def _shell_hook_starship(self):
        """Ajouter la ligne d'initialisation au fichier du shell choisi.

        La ligne n'est écrite qu'une fois : « starship init » cherché dans le
        fichier couvre les trois shells, dont les lignes diffèrent. L'écriture
        ne demande pas de confirmation — le choix du fichier, quand il y en a
        un à faire, l'a déjà donnée.
        """
        shell = self._shell_rc_target()
        ligne = self._STARSHIP_LINE[shell]
        chemin = self._shell_rc_append(shell, ligne, "starship init")
        if chemin is None:
            fichier = os.path.expanduser(self._SHELL_RC[shell])
            print(f"✅ {t('starship is already hooked into: ')}{fichier}")
            return
        print(f"✅ {t('starship hooked into: ')}{chemin}")
        print(f"   {ligne}")
        print(f"   {t('Open a new shell to see it.')}")

    def _shell_install_claude_code(self):
        self._shell_install_upstream_tool("claude")

    def _shell_install_opencode(self):
        self._shell_install_upstream_tool("opencode")

    def _shell_install_upstream_tool(self, binaire):
        """Lancer l'installateur amont d'un assistant, puis garantir le PATH.

        Ces installateurs posent leur binaire dans un répertoire du HOME que
        le PATH d'un shell ne porte pas toujours : sans la ligne d'export, le
        binaire est là et la commande reste introuvable. Le PATH du processus
        courant, lui, est figé depuis son démarrage — le menu ne verra pas le
        binaire avant d'être relancé.
        """
        commande, repertoire = self._UPSTREAM_TOOLS[binaire]
        status = self.execute.exec_command_live(
            commande,
            source_erplibre=False,
        )
        if status:
            print(f"❌ {t('Installation failed, see the output above.')}")
            return
        self._shell_ensure_on_path(self._shell_rc_target(), repertoire)
        pose = os.path.join(os.path.expanduser(repertoire), binaire)
        if not os.path.exists(pose):
            print(f"⚠ {t('Binary not found at: ')}{pose}")
            return
        print(f"✅ {binaire} : {pose}")
        print(f"   {t('Open a new shell to see it.')}")

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
            {"prompt_description": t("Show the context given to Claude")},
            {
                "prompt_description": t(
                    "Claude Code plugins - marketplaces and ERPLibre list"
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
            elif status == "4":
                self._show_claude_context()
            elif status == "5":
                self.prompt_execute_claude_plugins()
            else:
                print(t("Command not found !"))

    def _prompt_claude_configs(self):
        print(f"🤖 {t('Deploy Claude Code commands!')}")
        choices = [
            {"prompt_description": t("Commit - OCA/Odoo commit command")},
            {
                "prompt_description": t(
                    "Git prepare merge - Git merge preparation command"
                )
            },
            {
                "prompt_description": t(
                    "Todo Add Command + Plan Max - Plan and add a todo.py"
                    " command"
                )
            },
            {
                "prompt_description": t(
                    "Todo Generate Code - Code by the OCA rules at high"
                    " effort"
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
                    "git_prepare_merge",
                    "template_claude_commands_git_prepare_merge.md",
                )
            elif status == "3":
                # Les deux gabarits vont ensemble : /todo_plan_max produit la
                # spécification que /todo_add_command implémente, et l'un sans
                # l'autre laisse la moitié de la chaîne.
                self._setup_claude_command(
                    "todo_plan_max",
                    "template_claude_commands_todo_plan_max.md",
                )
                self._setup_claude_command(
                    "todo_add_command",
                    "template_claude_commands_todo_add_command.md",
                )
            elif status == "4":
                self._setup_claude_command(
                    "todo_generate_code",
                    "template_claude_commands_todo_generate_code.md",
                )
            elif status == "5":
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

    def _claude_context_root(self):
        """La racine du dépôt, deux niveaux au-dessus de ce fichier."""
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )

    def _compte_lignes(self, chemin):
        """Le nombre de lignes d'un fichier ; 0 s'il est illisible."""
        try:
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                return sum(1 for _ in fh)
        except OSError:
            return 0

    def _claude_command_state(self, deployed, template):
        """La copie déployée d'une commande suit-elle encore le gabarit ?

        La comparaison ignore les lignes qui portent une identité git : le
        déploiement y substitue le nom et le courriel, et une égalité stricte
        déclarerait périmée toute commande personnalisée.
        """
        if not os.path.isfile(template):
            return t("not in the repository")
        if not os.path.isfile(deployed):
            return t("missing")

        def stables(chemin):
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                return [x for x in fh if "user.name=" not in x]

        try:
            if stables(deployed) == stables(template):
                return t("up to date")
        except OSError:
            return t("missing")
        return t("redeploy needed")

    def _claude_memory_dir(self):
        """Le répertoire de mémoire de Claude Code pour CE dépôt.

        Le nom du projet est le chemin absolu dont chaque séparateur devient
        un tiret : c'est la convention de Claude Code, pas la nôtre.
        """
        racine = self._claude_context_root()
        projet = racine.replace(os.sep, "-")
        return os.path.expanduser(
            os.path.join("~/.claude/projects", projet, "memory")
        )

    def _show_claude_context(self):
        """Ce que Claude reçoit avant la première question : sources et état.

        Rend None. Écrit un tableau et ne modifie rien. Ne relève que ce qui
        est versionné ou déployé ; ce que `private/` contient n'y figure pas.
        """
        racine = self._claude_context_root()
        largeur = 62
        print(f"🧠 {t('Context given to Claude')}")
        print("-" * largeur)

        instructions = os.path.join(racine, "CLAUDE.md")
        if os.path.isfile(instructions):
            n = self._compte_lignes(instructions)
            print(f"{t('Instructions'):<22} CLAUDE.md  {n} {t('lines')}")
        else:
            print(f"{t('Instructions'):<22} CLAUDE.md  {t('missing')}")

        regles = os.path.join(racine, ".claude", "rules")
        if os.path.isdir(regles):
            noms = sorted(f for f in os.listdir(regles) if f.endswith(".md"))
            total = sum(
                self._compte_lignes(os.path.join(regles, f)) for f in noms
            )
            print(
                f"{t('Rules'):<22} .claude/rules/  {len(noms)}"
                f" {t('files')}, {total} {t('lines')}"
            )
            for nom in noms:
                n = self._compte_lignes(os.path.join(regles, nom))
                print(f"{'':<22}   {nom:<28} {n} {t('lines')}")
        else:
            print(f"{t('Rules'):<22} .claude/rules/  {t('missing')}")

        skills = os.path.join(racine, ".claude", "skills")
        if os.path.isdir(skills):
            noms = sorted(
                d
                for d in os.listdir(skills)
                if os.path.isfile(os.path.join(skills, d, "SKILL.md"))
            )
            print(f"{t('Skills'):<22} .claude/skills/  {len(noms)}")
            for nom in noms:
                print(f"{'':<22}   {nom}")
        else:
            print(f"{t('Skills'):<22} .claude/skills/  {t('missing')}")

        print(f"{t('Deployed commands'):<22} ~/.claude/commands/")
        gabarits = {
            "commit": "template_claude_commands_commit.md",
            "git_prepare_merge": (
                "template_claude_commands_git_prepare_merge.md"
            ),
            "todo_add_command": "template_claude_commands_todo_add_command.md",
            "todo_generate_code": (
                "template_claude_commands_todo_generate_code.md"
            ),
            "todo_plan_max": "template_claude_commands_todo_plan_max.md",
        }
        for nom, gabarit in sorted(gabarits.items()):
            etat = self._claude_command_state(
                os.path.expanduser(f"~/.claude/commands/{nom}.md"),
                os.path.join(racine, "conf", gabarit),
            )
            print(f"{'':<22}   /{nom:<26} {etat}")

        chemin_hooks = self._git_hooks_path(racine)
        print(
            f"{t('Git hooks'):<22}"
            f" {chemin_hooks or t('hook not installed')}"
        )
        if chemin_hooks:
            absolu = os.path.join(racine, chemin_hooks)
            for hook in self._GIT_HOOKS:
                pose = os.access(os.path.join(absolu, hook), os.X_OK)
                marque = (
                    t("hook installed") if pose else t("hook not installed")
                )
                print(f"{'':<22}   {hook:<26} {marque}")

        memoire = self._claude_memory_dir()
        if os.path.isdir(memoire):
            n = len([f for f in os.listdir(memoire) if f.endswith(".md")])
            print(f"{t('Memory'):<22} ~/.claude/projects/…/memory/  {n}")
        else:
            print(f"{t('Memory'):<22} {t('missing')}")

        print("-" * largeur)

    def _git_hooks_path(self, racine):
        """La valeur de core.hooksPath, ou None si git n'en déclare aucune."""
        try:
            sortie = subprocess.run(
                ["git", "config", "--get", "core.hooksPath"],
                capture_output=True,
                text=True,
                cwd=racine,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        chemin = sortie.stdout.strip()
        return chemin or None

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

    # Les plugins qu'ERPLibre pose par défaut, chacun avec la clé qui dit à
    # quoi il sert. Tous viennent du marketplace officiel et travaillent sur
    # le poste : aucun n'appelle un service tiers ni ne réclame de compte.
    _CLAUDE_PREFERRED_PLUGINS = (
        ("superpowers", "brainstorming, subagent-driven development, TDD"),
        ("pyright-lsp", "Python type checking and code intelligence"),
        ("claude-security", "vulnerability scan run entirely in session"),
        (
            "skill-creator",
            "write, improve and evaluate the repository skills",
        ),
    )
    _CLAUDE_MARKETPLACES_DIR = "~/.claude/plugins/marketplaces"

    def prompt_execute_claude_plugins(self):
        print(f"🤖 {t('Manage Claude Code plugins and marketplaces!')}")
        choices = [
            {"section": t("Inventory")},
            {"prompt_description": t("List installed plugins")},
            {"prompt_description": t("List configured marketplaces")},
            {"prompt_description": t("Search a plugin in the marketplaces")},
            {
                "prompt_description": t(
                    "Show a plugin detail and its token cost"
                )
            },
            {"section": t("Install plugins")},
            {"prompt_description": t("Install the ERPLibre preferred list")},
            {"prompt_description": t("Install a plugin by name")},
            {"prompt_description": t("Add a marketplace")},
            {"section": t("Maintenance")},
            {
                "prompt_description": t(
                    "Update the marketplaces and the plugins"
                )
            },
            {"prompt_description": t("Uninstall a plugin")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._claude_plugin_exec("list")
            elif status == "2":
                self._claude_plugin_exec("marketplace list")
            elif status == "3":
                self._claude_plugin_search()
            elif status == "4":
                self._claude_plugin_details()
            elif status == "5":
                self._claude_install_preferred_plugins()
            elif status == "6":
                self._claude_plugin_install_by_name()
            elif status == "7":
                self._claude_marketplace_add()
            elif status == "8":
                self._claude_plugin_update()
            elif status == "9":
                self._claude_plugin_uninstall()
            else:
                print(t("Command not found !"))

    def _claude_plugin_exec(self, args, quiet=False, capture=False):
        """Lance « claude plugin <args> », ou signale que claude est absent.

        Rend le code de sortie, ou le couple (code, lignes) quand capture est
        vrai. Le code 1 sans sortie signale l'absence de l'exécutable : rien
        n'a tourné, et l'appelant ne doit pas conclure à un échec de la
        commande elle-même.
        """
        claude = shutil.which("claude")
        if claude is None:
            print(t("The claude command is not in the PATH."))
            return (1, []) if capture else 1
        return self.execute.exec_command_live(
            f"{shlex.quote(claude)} plugin {args}",
            source_erplibre=False,
            quiet=quiet,
            return_status_and_output=capture,
        )

    def _claude_plugin_is_installed(self, name):
        """Le plugin est-il déjà posé ?

        La liste est lue telle que la CLI l'écrit, et le nom y est cherché
        comme un mot entier : « code-review » ne doit pas se reconnaître dans
        « pr-review-toolkit ». Un doute rend faux, et l'installation qui suit
        est de toute façon idempotente.
        """
        result = self._claude_plugin_exec("list", quiet=True, capture=True)
        if not isinstance(result, tuple) or result[0] != 0:
            return False
        motif = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
        return any(motif.search(ligne) for ligne in result[1])

    def _claude_install_preferred_plugins(self):
        """Pose la liste préférée d'ERPLibre après confirmation.

        L'installation passe par « -y » : la sortie de TODO est un tuyau, pas
        un terminal, et la CLI refuse sans lui toute installation qui exécute
        une commande déclarée par un marketplace. La liste est donc affichée
        AVANT la confirmation, qui est la seule occasion de la lire.
        """
        print(t("ERPLibre preferred plugins:"))
        print("-" * 62)
        for nom, raison in self._CLAUDE_PREFERRED_PLUGINS:
            print(f"  {nom:<18} {t(raison)}")
        print("-" * 62)
        if not self._is_yes(input(t("Install these plugins? (y/Y): "))):
            print(t("Nothing to do."))
            return
        for nom, _ in self._CLAUDE_PREFERRED_PLUGINS:
            print(f"\n📦 {nom}")
            if self._claude_plugin_is_installed(nom):
                print(t("Already installed, skipped."))
                continue
            self._claude_plugin_exec(f"install {shlex.quote(nom)} -y")
        print(f"\n{t('A restart of Claude Code applies the change.')}")

    def _claude_plugin_install_by_name(self):
        nom = input(t("Plugin name: ")).strip()
        if not nom:
            print(t("Nothing to do."))
            return
        self._claude_plugin_exec(f"install {shlex.quote(nom)} -y")
        print(t("A restart of Claude Code applies the change."))

    def _claude_plugin_details(self):
        nom = input(t("Plugin name: ")).strip()
        if not nom:
            print(t("Nothing to do."))
            return
        self._claude_plugin_exec(f"details {shlex.quote(nom)}")

    def _claude_plugin_uninstall(self):
        nom = input(t("Plugin name: ")).strip()
        if not nom:
            print(t("Nothing to do."))
            return
        if not self._is_yes(input(t("Uninstall this plugin? (y/Y): "))):
            print(t("Nothing to do."))
            return
        self._claude_plugin_exec(f"uninstall {shlex.quote(nom)}")
        print(t("A restart of Claude Code applies the change."))

    def _claude_marketplace_add(self):
        source = input(
            t("Marketplace source (URL, path or owner/repo): ")
        ).strip()
        if not source:
            print(t("Nothing to do."))
            return
        self._claude_plugin_exec(f"marketplace add {shlex.quote(source)}")

    def _claude_plugin_update(self):
        """Met à jour les marketplaces, puis les plugins déjà posés.

        Les catalogues passent d'abord : « plugin update » installe la version
        que le catalogue local annonce, et sur un catalogue périmé il ne fait
        rien tout en sortant en 0.
        """
        self._claude_plugin_exec("marketplace update")
        for nom, _ in self._CLAUDE_PREFERRED_PLUGINS:
            if self._claude_plugin_is_installed(nom):
                self._claude_plugin_exec(f"update {shlex.quote(nom)}")
        print(t("A restart of Claude Code applies the change."))

    def _claude_marketplace_catalog(self):
        """Les plugins des marketplaces posés, en triplets (nom, source, mot).

        Le catalogue est lu sur le disque plutôt que par la CLI : la recherche
        reste possible hors ligne, et un marketplace dont le manifeste est
        illisible est sauté sans faire échouer les autres.
        """
        racine = os.path.expanduser(self._CLAUDE_MARKETPLACES_DIR)
        catalogue = []
        if not os.path.isdir(racine):
            return catalogue
        for nom_marche in sorted(os.listdir(racine)):
            manifeste = os.path.join(
                racine, nom_marche, ".claude-plugin", "marketplace.json"
            )
            try:
                with open(manifeste, encoding="utf-8") as fh:
                    contenu = json.load(fh)
            except (OSError, ValueError):
                continue
            for plugin in contenu.get("plugins", []):
                nom = plugin.get("name", "")
                if nom:
                    catalogue.append(
                        (nom, nom_marche, plugin.get("description", ""))
                    )
        return catalogue

    def _claude_plugin_search(self):
        """Cherche un mot-clé dans le nom et la description des plugins."""
        catalogue = self._claude_marketplace_catalog()
        if not catalogue:
            print(t("No marketplace is configured."))
            return
        mot = input(t("Keyword to search: ")).strip().lower()
        if not mot:
            print(t("Nothing to do."))
            return
        trouves = [
            (nom, marche, desc)
            for nom, marche, desc in catalogue
            if mot in nom.lower() or mot in desc.lower()
        ]
        if not trouves:
            print(t("No plugin matches this keyword."))
            return
        print("-" * 78)
        for nom, marche, desc in trouves:
            print(f"  {nom}@{marche}")
            if desc:
                print(f"      {desc[:70]}")
        print("-" * 78)
        print(f"{t('Total:')} {len(trouves)}")

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
            {"section": t("Duplicate")},
            {"prompt_description": t("Duplicate a database")},
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
                self.db_manager.duplicate_database()
            elif status == "5":
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
            {"prompt_description": t("Dependencies between modules")},
            {"section": t("Files")},
            {
                "prompt_description": t(
                    "Attachment files missing from the filestore"
                )
            },
            {"section": t("Instance")},
            {
                "prompt_description": t(
                    "Monitoring - a backup, a remote copy or a live instance"
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
                self.execute_analyse_module_dependency()
            elif status == "7":
                self.execute_analyse_filestore()
            elif status == "8":
                self.execute_analyse_monitoring()
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

    def execute_analyse_module_dependency(self):
        """Qui dépend de qui, pour savoir ce qu'on peut retirer.

        L'écran est ouvert par l'outil lui-même, qui retombe sur son
        rapport texte s'il ne peut pas — terminal absent, Textual absent.

        Pas d'option « sauvegarde .zip » : les dépendances vivent dans
        `ir_module_module_dependency`, qu'un zip n'expose pas sans
        restauration.
        """
        from script.analyse import check_module_dependency as dependency

        database = self._analyse_select_database()
        if not database:
            return
        print(f"⧖ {t('Reading the modules and their dependencies…')}")
        try:
            rapport = dependency.survey(database)
        except Exception as exc:
            print(f"❌ {t('Analysis failed: ')}{exc}")
            return
        if rapport.get("unavailable"):
            print(f"❌ {t('Cannot read the database: ')}{database}")
            return
        try:
            from script.analyse.check_module_dependency_tui import run_tui
        except Exception:
            run_tui = None
        if not (run_tui and run_tui(rapport)):
            # Borné : une base porte trois mille modules, et déverser six
            # mille lignes dans le menu n'est pas un repli.
            print("\n".join(dependency.render_text(rapport, limit=8, cap=40)))

        def handler(rank):
            if rank == 1:
                print("\n".join(dependency.render_text(rapport, limit=0)))
            else:
                self._analyse_export_json(
                    rapport, os.path.basename(database), "module_dependency"
                )

        self._analyse_follow_up(
            [
                {"prompt_description": t("Show every entry")},
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

    def execute_analyse_monitoring(self):
        """Ausculter une instance dont la base n'est pas forcément ici.

        Les analyses existent déjà ; ce qui manquait est le chemin d'avant.
        Une sauvegarde, locale ou distante, se RESTAURE — après quoi tout
        ce que le dépôt sait faire s'applique. Une instance vivante, non :
        on n'a pas la base, on a une session, et ce que RPC laisse lire est
        un sous-ensemble. L'écran de choix le dit au lieu de proposer des
        analyses qui échoueraient à l'ouverture.
        """
        from script.analyse import monitoring, monitoring_tui

        print(f"🛰  {t('Inspect an instance.')}")
        source = self._monitoring_select_source()
        if not source:
            return
        kind, target = source
        print()
        print(monitoring.describe_source(kind, target))
        print()

        choix = monitoring_tui.run_tui(kind, target)
        if not choix:
            return
        analyse = monitoring.analysis_by_key(choix)
        if not analyse:
            return
        if kind not in analyse["kinds"]:
            print(f"✖ {t('Not available for this source.')}")
            return
        extra = None
        if analyse.get("asks_expect"):
            extra = ["--expect", self._monitoring_expect(kind)]
        if analyse.get("writes"):
            self._monitoring_write_flow(analyse, target)
            return
        monitoring.run_analysis(analyse, target, extra=extra)

    def _monitoring_write_flow(self, analyse, database):
        """La seule analyse qui écrit : montrer, puis demander.

        On lance TOUJOURS la marche à blanc d'abord, et l'on demande
        ensuite. Une question posée avant de savoir ce qui sera touché
        n'est pas un consentement : c'est un pari. Le rapport dit combien
        de modèles et de colonnes, et lesquels sont traduits ou uniques.

        La confirmation redemande le NOM de la base. Une frappe sur « o »
        se donne par réflexe ; recopier « sireine_neutralize_upgrade_18 »
        oblige à regarder ce qu'on détruit.
        """
        from script.analyse import monitoring

        choix = self._monitoring_anonymize_options()
        if choix is None:
            return
        print()
        if monitoring.run_analysis(analyse, database, extra=choix) == 2:
            return
        print()
        print(
            f"⚠️  {t('This DESTROYS the data of')} '{database}'"
            f" — {t('there is no undo.')}"
        )
        tape = input(
            f"💬 {t('Type the database name to confirm (empty to cancel): ')}"
        ).strip()
        if tape != database:
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return
        monitoring.run_analysis(
            analyse, database, extra=choix + ["--apply", "--confirm", database]
        )

    def _monitoring_anonymize_options(self):
        """Le mode et ses listes, ou None si l'on renonce."""
        print()
        print(f"[1] {t('Hybrid: the default personal-data models, adjusted')}")
        print(f"[2] {t('Whitelist: only the models I name')}")
        print(f"[3] {t('Blacklist: every model except those I name')}")
        print(f"[0] {t('Back')}")
        answer = click.prompt(t("Command:"))
        print()
        mode = {"1": "hybrid", "2": "whitelist", "3": "blacklist"}.get(answer)
        if not mode:
            return None
        extra = ["--mode", mode]
        invite = (
            t("Models to ADD, comma separated (empty for none): ")
            if mode != "blacklist"
            else t("Models to EXCLUDE, comma separated: ")
        )
        noms = input(f"💬 {invite}").strip()
        if noms:
            extra += ["--exclude" if mode == "blacklist" else "--models", noms]
        elif mode == "whitelist":
            print(f"❌ {t('A whitelist with no model would do nothing.')}")
            return None
        mots = input(
            f"💬 {t('Python file declaring MOTS (empty for the built-in): ')}"
        ).strip()
        if mots:
            if not os.path.isfile(os.path.expanduser(mots)):
                print(f"❌ {t('No such file: ')}{mots}")
                return None
            extra += ["--words", os.path.expanduser(mots)]
        return extra

    def _monitoring_expect(self, kind):
        """Copie de développement, ou instance en service ?

        Zéro cron actif est le SUCCÈS attendu d'une copie et une panne
        totale sur une production ; zéro serveur de courriel rassure sur
        l'une et condamne l'autre. Deviner à la place de l'utilisateur,
        c'est afficher du rouge sur ce qu'il vient de demander — et l'on
        cesse alors de lire le rapport.
        """
        from script.analyse import check_instance_state, monitoring

        if kind == monitoring.KIND_LIVE:
            return check_instance_state.LIVE
        print()
        print(f"[1] {t('A development copy (restored, neutralised)')}")
        print(f"[2] {t('An instance in service')}")
        answer = click.prompt(t("Command:"))
        print()
        return (
            check_instance_state.LIVE
            if answer == "2"
            else check_instance_state.COPY
        )

    def _monitoring_select_source(self):
        """(genre, cible), ou None si l'on renonce.

        Le zip et la sauvegarde distante mènent tous deux à une base
        restaurée : passé la restauration, ils ne se distinguent plus, et
        le reste du code n'a pas à savoir d'où ils venaient.
        """
        from script.analyse import monitoring

        print()
        # La base locale d'abord : c'est la provenance la plus directe, et
        # `_analyse_select_source` du même menu range déjà la base avant la
        # sauvegarde. Deux ordres différents dans un même menu se paient en
        # hésitation à chaque usage.
        print(f"[1] {t('A local database')}")
        print(f"[2] {t('A local backup .zip')}")
        print(f"[3] {t('A remote backup (https + master password)')}")
        print(f"[4] {t('A live remote instance')}")
        print(f"[0] {t('Back')}")
        answer = click.prompt(t("Command:"))
        print()
        if answer == "1":
            database = self.db_manager.select_database()
            return (monitoring.KIND_DATABASE, database) if database else None
        if answer == "2":
            path = self.db_manager.select_backup_path()
            database = self._monitoring_restore(path) if path else None
            return (monitoring.KIND_DATABASE, database) if database else None
        if answer == "3":
            status, path, _name = (
                self.db_manager.download_database_backup_cli()
            )
            if status or not path or not os.path.isfile(path):
                print(f"❌ {t('The download did not produce a usable file.')}")
                return None
            database = self._monitoring_restore(path)
            return (monitoring.KIND_DATABASE, database) if database else None
        if answer == "4":
            return self._monitoring_live()
        return None

    def _monitoring_live(self):
        """Se connecter pour de bon, ou ne pas prétendre l'être.

        Une faute dans l'URL ou dans la clé ne se verrait sinon qu'à la
        première analyse, et passerait pour un défaut de l'analyse.
        """
        import getpass

        from script.analyse import monitoring

        base_url = input(t("Instance URL (ex. https://example.com): ")).strip()
        if not base_url:
            return None
        database = input(t("Database name on that instance: ")).strip()
        if not database:
            return None
        login = input(t("User login: ")).strip()
        if not login:
            return None
        print()
        print(f"[1] {t('An API key')}")
        print(f"[2] {t('A password')}")
        genre = click.prompt(t("Command:"))
        secret = getpass.getpass(
            t("API key: ") if genre == "1" else t("Password: ")
        )
        if not secret:
            return None
        try:
            uid, version = monitoring.live_connect(
                base_url, database, login, secret
            )
        except Exception as exc:
            print(f"❌ {t('Cannot connect: ')}{exc}")
            return None
        print(f"✅ {t('Connected as uid')} {uid}, {t('Odoo')} {version}")
        return (monitoring.KIND_LIVE, f"{base_url} · {database}")

    def _monitoring_restore(self, zip_path):
        """Restaurer la sauvegarde, puis DIRE ce que la neutralisation a pris.

        Mesuré sur sept bases dont le nom portait « neutralize » :
        `database.is_neutralized` absent partout, jusqu'à 35 crons actifs,
        et le domaine de courriel du client toujours en place. Poser la
        question, recevoir oui et ne rien vérifier reproduit exactement
        cette illusion — on relit donc la base.
        """
        from script.analyse import monitoring

        image = self._monitoring_image_name(zip_path)
        if not image:
            return None
        defaut = image
        database = input(
            f"💬 {t('Database name (default=')}{defaut}) : "
        ).strip()
        database = database or defaut

        neutralise = (
            input(f"💬 {t('Neutralize the database (Y/n)? ')}").strip().lower()
        )
        more_arg = ""
        if neutralise != "n":
            more_arg = "--neutralize "
            database += "_neutralize"

        status, _ = self._execute.exec_command_live(
            f"python3 ./script/database/db_restore.py -d {database} "
            f"{more_arg}--ignore_cache --image {image}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if status:
            print(f"❌ {t('The restore failed.')}")
            return None
        if more_arg:
            status, _ = self._execute.exec_command_live(
                f"./script/addons/update_prod_to_dev.sh {database}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )
            print()
            print(
                monitoring.neutralize_report(
                    monitoring.neutralize_state(database), colour=True
                )
            )
            if status:
                # Le compte test/test vient de `user_test`, posé par ce
                # script. S'il n'a pas fini, l'annoncer quand même enverrait
                # se heurter à un refus d'authentification.
                print(
                    f"⚠  {t('update_prod_to_dev did not finish: do not')}"
                    f" {t('count on the test/test account.')}"
                )
            else:
                print(f"ℹ️  {t('You can log in with test / test.')}")
        return database

    def _monitoring_image_name(self, zip_path):
        """db_restore veut un NOM sous image_db/, pas un chemin.

        Une sauvegarde qui vient d'ailleurs n'est donc pas restaurable telle
        quelle. Plutôt que de recopier plusieurs gigaoctets, on propose un
        lien — et on le demande, parce que cela pose un fichier dans un
        répertoire qui n'est pas à nous.
        """
        image_db = os.path.join(os.getcwd(), "image_db")
        nom = os.path.basename(zip_path)
        if nom.endswith(".zip"):
            nom = nom[:-4]
        if os.path.dirname(os.path.abspath(zip_path)) == image_db:
            return nom
        cible = os.path.join(image_db, f"{nom}.zip")
        if os.path.exists(cible):
            print(f"ℹ️  {t('Using the file already in image_db: ')}{cible}")
            return nom
        answer = (
            input(
                f"💬 {t('db_restore only reads image_db/. Link it there')}"
                f" ({cible}) (Y/n)? "
            )
            .strip()
            .lower()
        )
        if answer == "n":
            return None
        try:
            os.makedirs(image_db, exist_ok=True)
            os.symlink(os.path.abspath(zip_path), cible)
        except OSError as exc:
            print(f"❌ {t('Cannot link into image_db: ')}{exc}")
            return None
        print(f"🔗 {cible}")
        return nom

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

    def rtk_locate(self):
        """Localise l'exécutable rtk.

        Rend le couple (chemin, visible_dans_le_PATH). Le chemin vaut None
        quand rtk est introuvable. Le second membre est faux quand le binaire
        existe à l'emplacement où l'installateur le dépose sans que le PATH y
        mène : un processus garde le PATH qu'il avait au démarrage, donc une
        installation faite pendant que TODO tourne lui reste invisible tant
        qu'il n'est pas relancé.
        """
        rtk_path = shutil.which("rtk")
        if rtk_path:
            return rtk_path, True
        # Emplacement par défaut de l'installateur (RTK_INSTALL_DIR le change).
        fallback = os.path.expanduser("~/.local/bin/rtk")
        if os.access(fallback, os.X_OK):
            return fallback, False
        return None, False

    def rtk_exec(self, args):
        """Lance rtk par son chemin absolu, ou signale qu'il est absent.

        Le chemin absolu évite le code 127 d'un « rtk » nu quand le PATH du
        processus ne mène pas à l'emplacement d'installation.
        """
        rtk_path, _ = self.rtk_locate()
        if rtk_path is None:
            print(t("RTK is not installed. Use option 1 to install it."))
            return 1
        return self.execute.exec_command_live(
            f"{shlex.quote(rtk_path)} {args}",
            source_erplibre=False,
        )

    def rtk_version(self, rtk_path):
        """Rend la version qu'annonce le binaire, « ? » s'il ne répond pas."""
        result = self.execute.exec_command_live(
            f"{shlex.quote(rtk_path)} --version",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        if isinstance(result, tuple) and result[0] == 0:
            return " ".join(result[1]).strip()
        return "?"

    def rtk_report_path_warning(self):
        """Dit comment rendre rtk appelable quand le PATH ne le porte pas."""
        print(t("rtk is not in the PATH of this process, restart TODO."))
        print(t("To make it permanent, add to your shell profile:"))
        print('   export PATH="$HOME/.local/bin:$PATH"')

    def rtk_report_install(self, exit_code):
        """Annonce le résultat de l'installation, PATH compris.

        Une installation réussie ne rend pas rtk appelable pour autant : le
        binaire atterrit dans un répertoire que le PATH du processus courant
        peut ignorer. Distinguer les deux cas évite de conclure à un échec
        devant un « commande introuvable » qui ne tient qu'au PATH.
        """
        if exit_code:
            print(f"❌ {t('RTK installation failed, see the output above.')}")
            return
        rtk_path, in_path = self.rtk_locate()
        if rtk_path is None:
            print(
                "❌"
                f" {t('Installation ended without error, but no rtk binary was found.')}"
            )
            return
        print(
            f"✅ {t('RTK is installed, version: ')}{self.rtk_version(rtk_path)}"
        )
        print(f"   {rtk_path}")
        if not in_path:
            self.rtk_report_path_warning()

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
            command = (
                "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/"
                "refs/heads/master/install.sh | sh"
            )
        elif status == "2":
            command = "brew install rtk"
        elif status == "3":
            command = "cargo install --git https://github.com/rtk-ai/rtk"
        else:
            print(t("Command not found !"))
            return
        exit_code = self.execute.exec_command_live(
            command,
            source_erplibre=False,
        )
        self.rtk_report_install(exit_code)

    def rtk_check_version(self):
        self.rtk_exec("--version")

    def rtk_show_gain(self):
        self.rtk_exec("gain")

    def rtk_discover(self):
        self.rtk_exec("discover")

    def rtk_init_global(self):
        self.rtk_exec("init --global")

    def rtk_check_status(self):
        rtk_path, in_path = self.rtk_locate()
        if rtk_path is None:
            print(t("RTK is not installed. Use option 1 to install it."))
            return

        print(
            f"{t('RTK is installed, version: ')}{self.rtk_version(rtk_path)}"
        )
        print(f"   {rtk_path}")
        if not in_path:
            self.rtk_report_path_warning()

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
            # Hors de la suite unitaire, et le libellé le dit : ceux-là créent
            # de vraies machines et durent des heures.
            {"prompt_description": t("Long tests - real VMs, hours")},
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
            elif status == "6":
                self.prompt_execute_longtest()
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
        self, db_name, extra_cmd_web_login="", web_login_env=None
    ):
        cmd_server = f"./run.sh -d {db_name};bash"
        self.execute.exec_command_live(cmd_server)
        cmd_client = (
            f"sleep 3;./script/selenium/web_login.py{extra_cmd_web_login};bash"
        )
        self.execute.exec_command_live(
            cmd_client, new_env=web_login_env or None
        )

    def prompt_execute_selenium(
        self, command=None, extra_cmd_web_login="", web_login_env=None
    ):
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

        env = web_login_env or None
        if len(commands) == 1:
            self.execute.exec_command_live(commands[0], new_env=env)
        elif len(commands) > 1:
            new_cmd = "parallel ::: "
            for i, cmd in enumerate(commands):
                new_cmd += f' "sleep {1 * i};{cmd}"'
            # « parallel » hérite de l'environnement, et chaque entrée lit
            # SA variable : un nom par identifiant, d'où EL_WEB_LOGIN_PWD_N.
            self.execute.exec_command_live(new_cmd, new_env=env)

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
