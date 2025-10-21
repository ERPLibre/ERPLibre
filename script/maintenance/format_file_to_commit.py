#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import subprocess

IGNORE_EXTENSION = []
IGNORE_FILE_NAME = ["Makefile"]


def execute_shell(cmd):
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    return out.decode().strip() if out else ""


def get_modified_files():
    lst_cmd_git_status = ["git", "status", "--porcelain"]
    print(" ".join(lst_cmd_git_status))
    try:
        result = subprocess.run(
            lst_cmd_git_status,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split("\n")

        modified_files = []
        for line in lines:
            if not line:
                continue

            try:
                if "->" in line:
                    # Example : M file_01 -> file_02
                    status, old_file_path, code, file_path = (
                        line.strip().replace("  ", " ").split(" ")
                    )
                else:
                    # Example : M file_01
                    status, file_path = (
                        line.strip().replace("  ", " ").split(" ")
                    )
            except Exception as e:
                print(f"'{line}'")
                raise e

            if (
                status == "M"
                or status == "A"
                or status == "AM"
                or status == "MM"
                or status == "R"
                or status == "RM"
                or status == "??"
            ):
                modified_files.append((status, file_path))
            elif status == "D":
                # Ignore to format removed file
                pass
            else:
                print(f"Not supported status '{status}'")

        return modified_files
    except subprocess.CalledProcessError as e:
        print(f"Error execution with git command: {e}")
        return None


if __name__ == "__main__":
    cmd_format = "parallel ::: "
    has_file = False
    files = get_modified_files()
    if files:
        for status, path in files:
            print(f"Statut: '{status}', Fichier: {path}")
            cmd_format += f"\"./script/maintenance/format.sh '{path}'\" "
            has_file = True
    if has_file:
        print(cmd_format)
        execute_shell(cmd_format)
