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

try:
    import humanize
except ModuleNotFoundError as e:
    humanize = None

VENV_ERPLIBRE = ".venv.erplibre"

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
    def __init__(self) -> None:
        self.cmd_source_erplibre: str = ""
        self.cmd_source_default: str = ""
        exec_path_gnome_terminal = shutil.which("gnome-terminal")
        if exec_path_gnome_terminal:
            self.cmd_source_erplibre = (
                f"gnome-terminal -- bash -c 'source"
                f" ./{VENV_ERPLIBRE}/bin/activate;%s'"
            )
            self.cmd_source_default = "gnome-terminal -- bash -c '" f"%s'"
        else:
            exec_path_tell = shutil.which("osascript")
            if exec_path_tell:
                self.cmd_source_erplibre = (
                    "osascript -e 'tell application \"Terminal\"'"
                )
                self.cmd_source_erplibre += " -e 'tell application \"System Events\" to keystroke \"t\" using {command down}' -e 'delay 0.1' -e 'do script \""
                self.cmd_source_erplibre += f"cd {os.getcwd()}; source ./{VENV_ERPLIBRE}/bin/activate; %s\" in front window'"
                self.cmd_source_erplibre += " -e 'end tell'"
            else:
                self.cmd_source_erplibre = (
                    f"source ./{VENV_ERPLIBRE}/bin/activate;%s"
                )

    def exec_command_live(
        self,
        command: str,
        source_erplibre: bool = True,
        quiet: bool = False,
        single_source_erplibre: bool = False,
        new_window: bool = False,
        single_source_odoo: bool = False,
        source_odoo: str = "",
        new_env: dict | None = None,
        return_status_and_command: bool = False,
        return_status_and_output: bool = False,
        return_status_and_output_and_command: bool = False,
    ) -> (
        int
        | tuple[int, str]
        | tuple[int, list[str]]
        | tuple[int, str, list[str]]
    ):
        """
        Execute a command and display its output live.

        Args:
            command (str): The command to execute.
        """

        my_env = os.environ.copy()
        if new_env:
            my_env.update(new_env)

        process_start_time = time.time()
        exit_code = None
        if source_erplibre:
            # command = f"source ./{VENV_ERPLIBRE}/bin/activate && " + command
            # cmd = (
            #     f"gnome-terminal --tab -- bash -c 'source"
            #     f" ./{VENV_ERPLIBRE}/bin/activate;{command}'"
            # )
            command = self.cmd_source_erplibre % command
            # os.system(f"./script/terminal/open_terminal.sh {command}")
        elif single_source_erplibre:
            command = f"source ./{VENV_ERPLIBRE}/bin/activate && %s" % command
        elif single_source_odoo:
            if not source_odoo and os.path.exists("./.erplibre-version"):
                with open("./.erplibre-version") as f:
                    source_odoo = f.read()
            if not source_odoo:
                _logger.error(
                    f"You cannot execute Odoo command if no version is installed. Command : {command}"
                )
                return -1
            command = f"source ./.venv.{source_odoo}/bin/activate && {command}"
        if new_window and self.cmd_source_default:
            command = self.cmd_source_default % command

        if not quiet:
            print("🏠 ⬇ Execute command :")
            print(command)
        output_lines = []

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                executable="/bin/bash",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # Disable buffering for live output
                universal_newlines=True,  # Handle line breaks correctly
                env=my_env,
            )

            while True:
                line = process.stdout.readline()
                if not line:
                    break
                if not quiet:
                    print(line, end="")
                if (
                    return_status_and_output
                    or return_status_and_output_and_command
                ):
                    # Remove last \n char
                    output_lines.append(
                        line.removesuffix("\r\n")
                        .removesuffix("\n")
                        .removesuffix("\r")
                    )

            process.wait()
            exit_code = process.returncode
            if process.returncode != 0 and not quiet:
                print("Command returned error code:" f" {process.returncode}")

        except FileNotFoundError:
            if not quiet:
                if "password" in command:
                    print(
                        f"Error: Command '{command.split(' ')[0]}'[...]"
                        " not found."
                    )
                else:
                    print(f"Error: Command '{command}' not found.")
        except Exception as e:
            if not quiet:
                print(f"An error occurred: {e}")
        process_end_time = time.time()
        duration_sec = process_end_time - process_start_time
        if humanize:
            duration_delta = datetime.timedelta(seconds=duration_sec)
            human_time = humanize.precisedelta(duration_delta)
            if not quiet:
                print(f"🏠 ⬆ Executed ({human_time}) :")
        else:
            if not quiet:
                print(f"🏠 ⬆ Executed ({duration_sec:.2f} sec.) :")
        if not quiet:
            print(command)
            print()
        if return_status_and_output_and_command:
            return exit_code, command, output_lines
        if return_status_and_command:
            return exit_code, command
        if return_status_and_output:
            return exit_code, output_lines
        return exit_code
