#!/usr/bin/env python3

import datetime
import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
import time

file_error_path = ".erplibre.error.txt"
cst_venv_erplibre = ".venv.erplibre"
VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
INSTALLED_ODOO_VERSION_FILE = os.path.join(
    ".repo", "installed_odoo_version.txt"
)
ODOO_VERSION_FILE = os.path.join(".odoo-version")
ENABLE_CRASH = False
CRASH_E = None

try:
    import tkinter as tk
    from tkinter import filedialog

    import click
    import humanize
    import openai
    from pykeepass import PyKeePass

    # TODO implement urwid to improve text user interface
    # import urwid
    # TODO implement rich for beautiful print and table
    # import rich
except ModuleNotFoundError as e:
    humanize = None
    ENABLE_CRASH = True
    CRASH_E = e

if not ENABLE_CRASH:
    print("Importation success!")

_logger = logging.getLogger(__name__)

CONFIG_FILE = "./script/todo/todo.json"
CONFIG_OVERRIDE_FILE = "./script/todo/todo_override.json"
LOGO_ASCII_FILE = "./script/todo/logo_ascii.txt"


class TODO:
    def __init__(self):
        self.kdbx = None
        self.init()

    def init(self):
        # Get command
        self.cmd_source_erplibre = ""
        exec_path_gnome_terminal = shutil.which("gnome-terminal")
        if exec_path_gnome_terminal:
            self.cmd_source_erplibre = (
                f"gnome-terminal -- bash -c 'source"
                f" ./{cst_venv_erplibre}/bin/activate;%s'"
            )
        else:
            exec_path_tell = shutil.which("osascript")
            if exec_path_tell:
                self.cmd_source_erplibre = (
                    "osascript -e 'tell application \"Terminal\"'"
                )
                self.cmd_source_erplibre += " -e 'tell application \"System Events\" to keystroke \"PATH\" using {command down}' -e 'delay 0.1' -e 'do script \""
                self.cmd_source_erplibre += f"./{cst_venv_erplibre}/bin/activate; %s\" in front window'"
                self.cmd_source_erplibre += " -e 'end tell'"
            else:
                self.cmd_source_erplibre = (
                    f"source ./{cst_venv_erplibre}/bin/activate;%s"
                )

    def run(self):
        with open(LOGO_ASCII_FILE) as my_file:
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
                print("source .venv.erplibre/bin/activate && make")
                sys.exit(1)
            except ImportError:
                print("Do")
                print("source .venv.erplibre/bin/activate && make")
                sys.exit(1)
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
        chemin_fichier_kdbx = self.get_config(["kdbx", "path"])
        if not chemin_fichier_kdbx:
            root = tk.Tk()
            root.withdraw()  # Hide the main window
            chemin_fichier_kdbx = filedialog.askopenfilename(
                title="Select a File",
                filetypes=(("KeepassX files", "*.kdbx"),),
            )
        if not chemin_fichier_kdbx:
            _logger.error(f"KDBX is not configured, please fill {CONFIG_FILE}")
            return

        mot_de_passe_kdbx = self.get_config(["kdbx", "password"])
        if not mot_de_passe_kdbx:
            mot_de_passe_kdbx = getpass.getpass(
                prompt="Entrez votre mot de passe : "
            )

        kp = PyKeePass(chemin_fichier_kdbx, password=mot_de_passe_kdbx)

        if kp:
            self.kdbx = kp
        return kp

    def get_config(self, lst_params):
        # Open file
        config_file = CONFIG_FILE
        if os.path.exists(CONFIG_OVERRIDE_FILE):
            config_file = CONFIG_OVERRIDE_FILE

        with open(config_file) as cfg:
            dct_data = json.load(cfg)
            for param in lst_params:
                try:
                    dct_data = dct_data[param]
                except KeyError:
                    _logger.error(
                        f"KeyError on file {config_file} with keys"
                        f" {lst_params}"
                    )
                    return
        return dct_data

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
            nom_configuration = self.get_config(
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
[1] RUN Exécuter et installer une instance
[2] EXEC Automatisation - Démonstration des fonctions développées
[3] UPD Mise à jour - Update all developed staging source code
[4] Code - Outil pour développeur
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
            else:
                print("Commande non trouvée 🤖!")

    def prompt_install(self):
        print("Detect first installation from code source.")

        first_installation_input = (
            input(
                "First system installation? This will process system installation"
                " before (Y/N): "
            )
            .strip()
            .upper()
        )
        if first_installation_input == "Y":
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
                input("Open Pycharm? (Y/N): ").strip().upper()
            )
            if pycharm_configuration_input == "Y":
                pycharm_bin = "pycharm" if has_pycharm else "pycharm-community"
                self.executer_commande_live(pycharm_bin, source_erplibre=True)
                print(
                    "Close Pycharm when processing is done before continue"
                    " this guide."
                )
        # Propose Odoo installation
        # TODO detect last version supported
        odoo_installation_input = (
            input("Install virtual environment? (Y/N): ").strip().upper()
        )
        if odoo_installation_input == "Y":
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
            }
            dct_final_cmd_intern = {}
            lst_version, lst_version_installed, odoo_installed_version = self.get_odoo_version()

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
                    print(
                        f"Error, cannot understand value '{odoo_version_input}'"
                    )
                str_input_dyn_odoo_version = (
                    "Choose a version:\n\t"
                    + "\n\t".join([a[1] for a in dct_cmd_intern.values()])
                    + "\nSelect : "
                )
                odoo_version_input = (
                    input(str_input_dyn_odoo_version).strip().lower()
                )

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
        else:
            print("Nothing to do, you need a fresh installation to continue.")

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
            self.executer_commande_live(f"make {makefile_cmd}")

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
        lst_instance = self.get_config(["instance"])
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
                        status = click.confirm(
                            "Voulez-vous une nouvelle instance?"
                        )
                        dct_instance = lst_instance[int_cmd - 1]
                        self.execute_from_configuration(
                            dct_instance,
                            exec_run_db=True,
                            ignore_makefile=not bool(status),
                        )
                except ValueError:
                    pass
                if cmd_no_found:
                    print("Commande non trouvée 🤖!")

    def prompt_execute_fonction(self):
        lst_instance = self.get_config(["function"])
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

        lst_instance = self.get_config(["update_from_makefile"])
        dct_upgrade_odoo_database = {
            "prompt_description": "Upgrade Odoo",
        }
        lst_instance.append(dct_upgrade_odoo_database)
        help_info = self.fill_help_info(lst_instance)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == str(len(lst_instance)):
                self.execute_odoo_upgrade()
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
        return False

    def execute_odoo_upgrade(self):
        # TODO update dev environment for git project
        # TODO Redeploy new production after upgrade
        # 2 upgrades version = 5 environnement. 0-prod init, 1-dev init, 2-dev01, 3-dev02, 4-prod final
        print("Welcome to Odoo upgrade processus with ERPLibre 🤖")
        print("")
        print("What is your actual Odoo version?")
        lst_version, lst_version_installed, odoo_installed_version = self.get_odoo_version()
        lst_odoo_version = [{"prompt_description": "I don't know"}] + [{"prompt_description": a.get("odoo_version")} for a in lst_version]
        help_info = self.fill_help_info(lst_odoo_version)
        odoo_actual_version = None
        cmd_no_found = True
        while cmd_no_found:
            status = click.prompt(help_info)
            try:
                int_cmd = int(status)
                if 0 < int_cmd <= len(lst_odoo_version):
                    cmd_no_found = False
                    if int_cmd > 1:
                        odoo_actual_version = lst_odoo_version[int_cmd - 1].get("prompt_description")
            except ValueError:
                pass
            if cmd_no_found:
                print("Commande non trouvée 🤖!")

        print("Which version do you want to upgrade to?")
        odoo_reach_version = None
        cmd_no_found = True
        while cmd_no_found:
            status = click.prompt(help_info)
            try:
                int_cmd = int(status)
                if 0 < int_cmd <= len(lst_odoo_version):
                    cmd_no_found = False
                    if int_cmd > 1:
                        odoo_reach_version = lst_odoo_version[int_cmd - 1].get("prompt_description")
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
            print(f"https://oca.github.io/OpenUpgrade/coverage_analysis/modules{i*10}-{(i+1)*10}.html")
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
        print("  -> Install missing module, do a research or ask to uninstall it (can break data)")
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

        print("1- Import database from zip")
        print("  -> Neutralize data, maybe with")
        print("./script/addons/update_prod_to_dev.sh BD")
        print("  -> Fix running execution")
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

        print("2- Succeed update all addons")
        print("./script/addons/update_addons_all.sh BD")
        print("  -> Fix importation error")
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

        print("3- Clean up database before data migration")
        print("./script/addons/addons_install.sh database_cleanup")
        print("  -> Run it manually")
        print("Aller dans «configuration/Technique/Nettoyage.../Purger» les modules obsolètes")
        print("Uninstall no need module to next version.")
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

        print("4- Upgrade version with OpenUpgrade")
        # Script odoo 13 and before
        # ./.venv/bin/python ./script/OCA_OpenUpgrade/odoo-bin -c ./config.conf --update all --stop-after-init -d BD
        # Script odoo 14 and after
        # ./run.sh --upgrade-path=./script/OCA_OpenUpgrade/openupgrade_scripts/scripts --update all --stop-after-init --load=base,web,openupgrade_framework -d BD
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

        print("5- Cleaning up database after upgrade")
        print("Re-update i18n, purger data, tables (except mail_test and mail_test_full)")
        waiting_input = (
            input(
                "Press any keyboard key to continue..."
            )
        )
        print("")

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
        lst_instance = self.get_config(["code_from_makefile"])
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
        return False

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
        cmd = (
            f'parallel ::: "./run.sh -d {bd}" "sleep'
            f' 3;./script/selenium/web_login.py{extra_cmd_web_login}"'
        )
        self.executer_commande_live(cmd)

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

    def executer_commande_live(self, commande, source_erplibre=True):
        """
        Exécute une commande et affiche la sortie en direct.

        Args:
            commande (str): La commande à exécuter (sous forme de chaîne de caractères).
        """

        if source_erplibre:
            # commande = f"source ./{cst_venv_erplibre}/bin/activate && " + commande
            # cmd = (
            #     f"gnome-terminal --tab -- bash -c 'source"
            #     f" ./{cst_venv_erplibre}/bin/activate;{commande}'"
            # )
            commande = self.cmd_source_erplibre % commande
            print(f"Execute : {commande}")
            # os.system(f"./script/terminal/open_terminal.sh {commande}")
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
            )

            while True:
                ligne = process.stdout.readline()
                if not ligne:
                    break
                print(ligne, end="")

            process.wait()  # Attendre la fin du process

            if process.returncode != 0:
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
                from pykeepass import PyKeePass
            except ImportError:
                print("Rerun and exit")
                self.executer_commande_live(cmd, source_erplibre=True)
                sys.exit(1)
            print("No error")
        else:
            self.prompt_install()

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
