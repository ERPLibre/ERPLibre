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
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split("\n")

        modified_files = []
        for line in lines:
            if not line:
                continue

            status, file_path = line.strip().split(" ")

            if (
                status == "M"
                or status == "A"
                or status == "AM"
                or status == "MM"
                or status == "D"
                or status == "??"
            ):
                modified_files.append((status, file_path))
            else:
                print("")

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
