#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import datetime
import logging
import os
import shutil
import subprocess
import sys
import time

import humanize

cst_venv_erplibre = ".venv.erplibre"

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)


logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)


class Execute:
    def __init__(self):
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

    def exec_command_live(
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
        if new_window and self.cmd_source_default:
            commande = self.cmd_source_default % commande

        if not quiet:
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
                if not quiet:
                    print(ligne, end="")
                if (
                    return_status_and_output
                    or return_status_and_output_and_command
                ):
                    # Remove last \n char
                    lst_output.append(
                        ligne.removesuffix("\r\n")
                        .removesuffix("\n")
                        .removesuffix("\r")
                    )

            process.wait()  # Attendre la fin du process
            return_status = process.returncode
            if process.returncode != 0 and not quiet:
                print(
                    "La commande a retourné un code d'erreur :"
                    f" {process.returncode}"
                )

        except FileNotFoundError:
            if not quiet:
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
            if not quiet:
                print(f"Une erreur s'est produite : {e}")
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            humain_time = humanize.precisedelta(duration_delta)
            if not quiet:
                print(f"🏠 ⬆ Executed ({humain_time}) :")
        else:
            if not quiet:
                print(f"🏠 ⬆ Executed ({duration_sec:.2f} sec.) :")
        if not quiet:
            print(commande)
            print()
        if return_status_and_output_and_command:
            return return_status, commande, lst_output
        if return_status_and_command:
            return return_status, commande
        if return_status_and_output:
            return return_status, lst_output
        return return_status
