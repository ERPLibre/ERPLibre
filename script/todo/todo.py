#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.config import config_file

file_error_path = ".erplibre.error.txt"
cst_venv_erplibre = ".venv.erplibre"
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
INSTALLED_ODOO_VERSION_FILE = os.path.join(
    ".repo", "installed_odoo_version.txt"
)
ODOO_VERSION_FILE = ".odoo-version"
ENABLE_CRASH = False
CRASH_E = None

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
    print("Importation success!")

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
PATH_MOBILE_PROJECT_HOME = "./mobile/technolibre_home_mobile/technolibre_home"


class TODO:
    def __init__(self):
        self.dir_path = None
        self.kdbx = None
        self.init()
        self.file_path = None
        self.config_file = config_file.ConfigFile()

    def init(self):
        # Get command
        self.cmd_source_erplibre = ""
        self.cmd_source_default = ""
        exec_path_gnome_terminal = shutil.which("gnome-terminal")
        if exec_path_gnome_terminal:
            self.cmd_source_erplibre = (
                f"gnome-terminal -- bash -c 'source"
                f" ./{cst_venv_erplibre}/bin/activate;%s'"
            )
            self.cmd_source_default = "gnome-terminal -- bash -c '" f"%s'"
        else:
            exec_path_tell = shutil.which("osascript")
            if exec_path_tell:
                self.cmd_source_erplibre = (
                    "osascript -e 'tell application \"Terminal\"'"
                )
                self.cmd_source_erplibre += " -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \""
                self.cmd_source_erplibre += f"cd {os.getcwd()}; source ./{cst_venv_erplibre}/bin/activate; %s\" in front window'"
                self.cmd_source_erplibre += " -e 'end tell'"
            else:
                self.cmd_source_erplibre = (
                    f"source ./{cst_venv_erplibre}/bin/activate;%s"
                )

    def run(self):
        with open(self.config_file.get_logo_ascii_file_path()) as my_file:
            print(my_file.read())
        print("Ouverture de TODO en cours ...")
        print("🤖 => Entre tes directives par son chiffre et fait Entrée!")
        help_info = """Commande :
[1] Execute
[2] Install
[3] Question
[4] Fork - Ouvre TODO 🤖 dans une nouvelle tabulation
[0] Quitter
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
                self.executer_commande_live(cmd, source_erplibre=True)
            # elif status == "3" or status == "install":
            #     print("install")
            else:
                print("Commande non trouvée 🤖!")

        print(status)
        # manipuler()

    def get_kdbx(self):
        if self.kdbx:
            return self.kdbx
        # Open file
        chemin_fichier_kdbx = self.config_file.get_config(["kdbx", "path"])
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

        mot_de_passe_kdbx = self.config_file.get_config(["kdbx", "password"])
        if not mot_de_passe_kdbx:
            mot_de_passe_kdbx = getpass.getpass(
                prompt="Entrez votre mot de passe : "
            )

        kp = PyKeePass(chemin_fichier_kdbx, password=mot_de_passe_kdbx)

        if kp:
            self.kdbx = kp
        return kp

    def execute_prompt_ia(self):
        while True:
            help_info = """Commande :
[0] Retour
Écrit moi ta question """
            status = click.prompt(help_info)
            print()
            if status == "0":
                return
            kp = self.get_kdbx()
            if not kp:
                return
            nom_configuration = self.config_file.get_config(
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
        help_info = """Commande :
[1] Run - Exécuter et installer une instance
[2] Exec - Automatisation - Démonstration des fonctions développées
[3] Mise à jour - Update all developed staging source code
[4] Code - Outil pour développeur
[5] Doc - Recherche de documentation
[6] Database - Outils sur les bases de données
[0] Retour
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
            else:
                print("Commande non trouvée 🤖!")

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
            self.executer_commande_live(cmd, source_erplibre=True)
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
                self.executer_commande_live(
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
                "0: Quitter",
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
                print(f"Error, cannot understand value '{odoo_version_input}'")
            str_input_dyn_odoo_version = (
                "💬 Choose a version:\n\t"
                + "\n\t".join([a[1] for a in dct_cmd_intern.values()])
                + "\nSelect : "
            )
            odoo_version_input = (
                input(str_input_dyn_odoo_version).strip().lower()
            )

        if odoo_version_input == "0":
            return

        cmd_intern = dct_cmd_intern.get(odoo_version_input)[2]
        print(f"Will execute :\n{cmd_intern}")

        # TODO use external script to detect terminal to use on system
        # TODO check script open_terminal_code_generator.sh
        # cmd_extern = f"gnome-terminal -- bash -c '{cmd_intern};bash'"
        try:
            subprocess.run(
                cmd_intern, shell=True, executable="/bin/bash", check=True
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Le script Bash «{cmd_intern}» a échoué avec le code de retour {e.returncode}."
            )
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
            self.executer_commande_live(
                f"make {makefile_cmd}",
                source_erplibre=False,
                single_source_erplibre=True,
            )

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

    def fill_help_info(self, lst_instance):
        help_info = "Commande :\n"
        help_end = "[0] Retour\n"
        for i, dct_instance in enumerate(lst_instance):
            help_info += (
                f"[{i + 1}] " + dct_instance["prompt_description"] + "\n"
            )
        help_info += help_end
        return help_info

    def prompt_execute_instance(self):
        # TODO proposer le déploiement à distance
        # TODO proposer l'exécution de docker
        # TODO proposer la création de docker
        lst_instance = self.config_file.get_config(["instance"])
        init_len = len(lst_instance)

        if os.path.exists(PATH_MOBILE_PROJECT_HOME):
            dct_upgrade_odoo_database = {
                "prompt_description": "Mobile - Compile and run software",
                "callback": self.callback_make_mobile_home,
            }
            lst_instance.append(dct_upgrade_odoo_database)
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= init_len:
                        cmd_no_found = False
                        status = click.confirm(
                            "Voulez-vous une nouvelle instance?"
                        )
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(
                            dct_instance,
                            exec_run_db=True,
                            ignore_makefile=not bool(status),
                        )
                    elif int_cmd <= len(lst_instance):
                        # Execute dynamic instance
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(
                            dct_instance,
                        )
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

    def prompt_execute_fonction(self):
        lst_instance = self.config_file.get_config(["function"])
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_instance):
                        cmd_no_found = False
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

    def prompt_execute_update(self):
        # self.executer_commande_live(f"make {makefile_cmd}")
        print("🤖 Mise à jour du développement")
        # TODO détecter les modules en modification pour faire la mise à jour en cours
        # TODO demander sur quel BD faire la mise à jour
        # TODO proposer les modules manuelles selon la configuration à mettre à jour
        # TODO proposer la mise à jour de l'IDE
        # TODO proposer la mise à jour des git-repo
        # TODO faire la mise à jour de ERPLibre
        # TODO faire l'upgrade d'un odoo vers un autre

        lst_instance = self.config_file.get_config(["update_from_makefile"])
        dct_upgrade_odoo_database = {
            "prompt_description": "Upgrade Odoo - Migration Database",
        }
        lst_instance.append(dct_upgrade_odoo_database)
        dct_upgrade_poetry = {
            "prompt_description": "Upgrade Poetry - Dependency of Odoo",
        }
        lst_instance.append(dct_upgrade_poetry)
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(lst_instance) - 1):
                upgrade = todo_upgrade.TodoUpgrade(self)
                upgrade.execute_odoo_upgrade()
            elif status == str(len(lst_instance)):
                self.upgrade_poetry()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status) - 1
                    if 0 < int_cmd <= len(lst_instance):
                        cmd_no_found = False
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

    def prompt_execute_code(self):
        print("🤖 Qu'avez-vous de besoin pour développer?")
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

        lst_instance = self.config_file.get_config(["code_from_makefile"])
        dct_upgrade_odoo_database = {
            "prompt_description": "Upgrade Module",
        }
        lst_instance.append(dct_upgrade_odoo_database)
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(lst_instance)):
                self.upgrade_module()
            else:
                cmd_no_found = True
                try:
                    int_cmd = int(status)
                    if 0 < int_cmd <= len(lst_instance):
                        cmd_no_found = False
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(dct_instance)
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

    def prompt_execute_doc(self):
        print("🤖 Vous cherchez de la documentation?")
        lst_instance = [
            {"prompt_description": "Migration module coverage"},
            {"prompt_description": "What change between version"},
            {"prompt_description": "OCA guidelines"},
            {"prompt_description": "OCA migration Odoo 19 milestone"},
        ]
        help_info = self.fill_help_info(lst_instance)

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
                print("Commande non trouvée 🤖!")

    def prompt_execute_database(self):
        print("🤖 Faites des modifications sur les bases de données!")
        lst_instance = [
            {
                "prompt_description": "Download database to create backup (.zip)"
            },
            {"prompt_description": "Restore from backup (.zip)"},
        ]
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.download_database_backup_cli()
            elif status == "2":
                self.restore_from_database()
            else:
                print("Commande non trouvée 🤖!")

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
        # self.executer_commande_live(cmd)
        cmd_server = f"./run.sh -d {bd};bash"
        self.executer_commande_live(cmd_server)
        cmd_client = (
            f"sleep 3;./script/selenium/web_login.py{extra_cmd_web_login};bash"
        )
        self.executer_commande_live(cmd_client)

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
            self.executer_commande_live(lst_cmd[0])
        elif len(lst_cmd) > 1:
            new_cmd = "parallel ::: "
            for i, cmd in enumerate(lst_cmd):
                new_cmd += f' "sleep {1 * i};{cmd}"'
            self.executer_commande_live(new_cmd)

    def executer_commande_live(
        self,
        commande,
        source_erplibre=True,
        quiet=False,
        single_source_erplibre=False,
        new_window=False,
        single_source_odoo=False,
        source_odoo="",
        new_env=None,
        return_status_and_command=False,
        return_status_and_output=False,
        return_status_and_output_and_command=False,
    ):
        """
        Exécute une commande et affiche la sortie en direct.

        Args:
            commande (str): La commande à exécuter (sous forme de chaîne de caractères).
        """

        my_env = os.environ.copy()
        if new_env:
            my_env.update(new_env)

        process_start_time = time.time()
        return_status = None
        if source_erplibre:
            # commande = f"source ./{cst_venv_erplibre}/bin/activate && " + commande
            # cmd = (
            #     f"gnome-terminal --tab -- bash -c 'source"
            #     f" ./{cst_venv_erplibre}/bin/activate;{commande}'"
            # )
            commande = self.cmd_source_erplibre % commande
            # os.system(f"./script/terminal/open_terminal.sh {commande}")
        elif single_source_erplibre:
            commande = (
                f"source ./{cst_venv_erplibre}/bin/activate && %s" % commande
            )
        elif single_source_odoo:
            if not source_odoo and os.path.exists("./.erplibre-version"):
                with open("./.erplibre-version") as f:
                    source_odoo = f.read()
            if not source_odoo:
                _logger.error(
                    f"You cannot execute Odoo command if no version is installed. Command : {commande}"
                )
                return -1
            commande = (
                f"source ./.venv.{source_odoo}/bin/activate && {commande}"
            )
        elif new_window:
            commande = self.cmd_source_default % commande

        print("🏠 ⬇ Execute command :")
        print(commande)
        lst_output = []

        try:
            process = subprocess.Popen(
                commande,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Désactive la mise en tampon pour la sortie en direct
                universal_newlines=True,  # Pour traiter les sauts de lignes correctement
                env=my_env,
            )

            while True:
                ligne = process.stdout.readline()
                if not ligne:
                    break
                print(ligne, end="")
                if (
                    return_status_and_output
                    or return_status_and_output_and_command
                ):
                    lst_output.append(ligne)

            process.wait()  # Attendre la fin du process
            return_status = process.returncode
            if process.returncode != 0 and not quiet:
                print(
                    "La commande a retourné un code d'erreur :"
                    f" {process.returncode}"
                )

        except FileNotFoundError:
            if "password" in commande:
                print(
                    f"Erreur : La commande '{commande.split(' ')[0]}'[...] n'a"
                    " pas été trouvée."
                )
            else:
                print(
                    f"Erreur : La commande '{commande}' n'a pas été trouvée."
                )
        except Exception as e:
            print(f"Une erreur s'est produite : {e}")
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            humain_time = humanize.precisedelta(duration_delta)
            print(f"🏠 ⬆ Executed ({humain_time}) :")
        else:
            print(f"🏠 ⬆ Executed ({duration_sec:.2f} sec.) :")
        print(commande)
        print()
        if return_status_and_output_and_command:
            return return_status, commande, lst_output
        if return_status_and_command:
            return return_status, commande
        if return_status_and_output:
            return return_status, lst_output
        return return_status

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
            self.executer_commande_live(cmd, source_erplibre=True)
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
                self.executer_commande_live(cmd, source_erplibre=True)
                sys.exit(1)
            print("No error")
        else:
            self.prompt_install()

    def upgrade_module(self):
        upgrade = todo_upgrade.TodoUpgrade(self)
        upgrade.execute_module_upgrade()

    def upgrade_poetry(self):
        # Only show the version to the user
        status = self.executer_commande_live(
            f"make version",
            source_erplibre=False,
        )
        # TODO maybe autodetect to update it
        git_repo_update_input = input(
            "💬 Would you like to fetch all your git repositories, you need it (y/Y) : "
        )
        if git_repo_update_input.strip().lower() == "y":
            status = self.executer_commande_live(
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

        status = self.executer_commande_live(
            f"pip install -r requirement/erplibre_require-ments-poetry.txt && "
            f"./script/poetry/poetry_update.py -f",
            source_erplibre=False,
            single_source_erplibre=False,
            single_source_odoo=True,
            source_odoo=odoo_long_version,
        )

        if os.path.exists(poetry_lock):
            shutil.copy2(poetry_lock, path_file_odoo_lock)

    def restore_from_database(self, show_remote_list=True):
        path_image_db = os.path.join(os.getcwd(), "image_db")
        print("[1] By filename from image_db")
        print(f"[] Browser image_db {path_image_db}")
        status = input("💬 Select : ")
        if status == "1":
            file_name = status
        else:
            self.dir_path = ""

            file_browser = todo_file_browser.FileBrowser(
                path_image_db, self.on_dir_selected
            )
            file_browser.run_main_frame()
            file_name = os.path.basename(self.dir_path)
            print(file_name)

        database_name = input("💬 Database name : ")
        if not database_name:
            _logger.error("Missing database name")
            return
        status, lst_output = self.executer_commande_live(
            f"python3 ./script/database/db_restore.py -d {database_name} --ignore_cache --image {file_name}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        status = (
            input("💬 Would you like to neutralize database (y/Y)? ")
            .strip()
            .lower()
        )
        if status == "y":
            status, lst_output = self.executer_commande_live(
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
            status, lst_output = self.executer_commande_live(
                f"./script/addons/update_addons_all.sh {database_name}",
                return_status_and_output=True,
                single_source_erplibre=True,
                source_erplibre=False,
            )

    def download_database_backup_cli(self, show_remote_list=True):
        database_domain = input("Domain Odoo (ex. https://mondomain.com) : ")
        if show_remote_list:
            status, lst_output = self.executer_commande_live(
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
        status, cmd_executed = self.executer_commande_live(
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
        print("Reboot TODO 🤖...")
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
        default_project_name = "ERPLibre"
        default_project_url_name = "https://erplibre.ca"
        default_debug = False
        project_name = default_project_name
        project_url_name = default_project_url_name
        do_debug = default_debug

        do_personalize = input(
            "Do you want to personalize the mobile application (Y) : "
        )
        if do_personalize.strip().lower() == "y":
            project_name = (
                input(
                    f"Your project name, default {default_project_name} : "
                ).strip()
                or default_project_name
            )
            project_url_name = (
                input(
                    f"Your project url website, default {default_project_url_name} : "
                ).strip()
                or default_project_url_name
            )
            do_debug = (
                input("Do you want debug information (Y) :").strip().lower()
                == "y"
            )

        dotenv_file = dotenv.find_dotenv(
            filename=os.path.join(
                PATH_MOBILE_PROJECT_HOME, "src", ".env.production"
            )
        )
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
            "VITE_DEBUG_DEV",
            "true" if do_debug else "false",
            quote_mode="never",
        )
        status = self.executer_commande_live(
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
        print("Keyboard interrupt")
    finally:
        end_time = time.time()
        duration_sec = end_time - start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            humain_time = humanize.precisedelta(duration_delta)
            print(f"\nTODO execution time {humain_time}\n")
        else:
            print(f"\nTODO execution time {duration_sec:.2f} sec.\n")
