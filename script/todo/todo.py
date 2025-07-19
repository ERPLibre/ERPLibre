#!/usr/bin/env python3

import getpass
import json
import logging
import os
import sys
import time
import subprocess

file_error_path = ".erplibre.error.txt"
cst_venv_erplibre = ".venv.erplibre"


def restart_script(last_error):
    print("Reboot TODO 🤖...")
    # os.execv(sys.executable, ['python'] + sys.argv)
    # TODO mettre check que le répertoire est créé, s'il existe, auto-loop à corriger
    if os.path.exists(cst_venv_erplibre) and not os.path.exists(file_error_path):
        # TODO mettre check import suivant ne vont pas planter
        try:
            with open(file_error_path, "w") as f_file:
                f_file.write(str(last_error))
                pass  # The file is created and closed here, no content is written
            os.execv("/bin/bash",
                     ["/bin/bash", "-c", f"source ./{cst_venv_erplibre}/bin/activate && exec python " + " ".join(sys.argv)])
        except Exception as e:
            print("Error detect at first execution.")
            print(e)

# TODO show message at start if os.path.exists(file_error_path)
try:
    import tkinter as tk
    from tkinter import filedialog

    import click
    import openai
    from pykeepass import PyKeePass
except ModuleNotFoundError as e:
    if os.path.exists(file_error_path):
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
            if 'file' in locals() and file:
                file.close()
        # Force auto installation
        print("Auto installation")
        time.sleep(0.5)
        subprocess.run(
            "gnome-terminal -- bash -c './script/todo/source_todo.sh'",
            shell=True,
            executable="/bin/bash",
        )
        sys.exit(1)
    if os.path.exists(cst_venv_erplibre):
        print("Got error : ")
        print(e)
        # TODO auto-detect gnome-terminal, or choose another.
        restart_script(e)
        print(f"You forgot to activate source \nsource ./{cst_venv_erplibre}/bin/activate")
        time.sleep(0.5)
        subprocess.run(
            "gnome-terminal -- bash -c './script/todo/source_todo.sh'",
            shell=True,
            executable="/bin/bash",
        )
    else:
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
            subprocess.run(
                "gnome-terminal -- bash -c"
                " './script/version/update_env_version.py --install;bash'",
                shell=True,
                executable="/bin/bash",
            )
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
        if (has_pycharm or has_pycharm_community) and not os.path.exists(".idea"):
            pycharm_configuration_input = (
                input("Open Pycharm? (Y/N): ").strip().upper()
            )
            if pycharm_configuration_input == "Y":
                pycharm_bin = "pycharm" if has_pycharm else "pycharm-community"
                subprocess.run(
                    f"gnome-terminal -- bash -c '{pycharm_bin} .'",
                    shell=True,
                    executable="/bin/bash",
                )
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
            cmd_extern = "gnome-terminal -- bash -c './script/install/install_erplibre.sh;bash'"
            cmd_intern = "./script/install/install_erplibre.sh"
            try:
                subprocess.run(
                    cmd_intern,
                    shell=True,
                    executable="/bin/bash",
                    check=True
                )
            except subprocess.CalledProcessError as e:
                print(f"Le script Bash «{cmd_intern}» a échoué avec le code de retour {e.returncode}.")
                print("Wait after installation and open projects by terminal.")
                print("make open_terminal")
                restart_script(str(e))
        else:
            print("Nothing to do, you need a fresh installation to continue.")
    #     sys.exit(0)
    # sys.exit(1)

# TODO implement urwid to improve text user interface
# import urwid
_logger = logging.getLogger(__name__)

CONFIG_FILE = "./script/todo/todo.json"
CONFIG_OVERRIDE_FILE = "./script/todo/todo_override.json"
LOGO_ASCII_FILE = "./script/todo/logo_ascii.txt"


class TODO:
    def __init__(self):
        self.kdbx = None

    def run(self):
        with open(LOGO_ASCII_FILE) as my_file:
            print(my_file.read())
        print("Ouverture de TODO en cours ...")
        print("🤖 => Entre tes directives par son chiffre et fait Entrée!")
        help_info = """Commande :
[1] Execute
[2] Question
[3] Fork - Ouvre TODO 🤖 dans une nouvelle tabulation
[0] Quitter
"""
        # [3] install
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                break
            elif status == "1":
                self.prompt_execute()
            elif status == "2":
                self.execute_prompt_ia()
            elif status == "3":
                cmd = (
                    f"gnome-terminal --tab -- bash -c 'source"
                    f" ./{cst_venv_erplibre}/bin/activate;make todo'"
                )
                self.executer_commande_live(cmd)
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

        lst_instance = self.get_config(["update_from_makefile"])
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
        # if source_erplibre:
        #     commande = f"source ./{cst_venv_erplibre}/bin/activate && " + commande
        try:
            process = subprocess.Popen(
                commande,
                shell=True,
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


if __name__ == "__main__":
    todo = TODO()
    todo.run()
