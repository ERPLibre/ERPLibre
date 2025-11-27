#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import subprocess
import sys

IGNORE_EXTENSION = []
IGNORE_FILE_NAME = ["Makefile"]


def execute_shell(cmd):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def get_modified_files():
    lst_cmd_git_status = ["git", "status", "--porcelain"]
    path_repo_bin = ".venv.erplibre/bin/repo"
    if os.path.exists(path_repo_bin):
        lst_cmd_git_status_repo = [
            path_repo_bin,
            "forall",
            "-p",
            "-c",
            "git status -s",
        ]
    else:
        lst_cmd_git_status_repo = []
    try:
        print(" ".join(lst_cmd_git_status))
        result = subprocess.run(
            lst_cmd_git_status,
            capture_output=True,
            text=True,
            check=True,
        )
        lines_local = result.stdout.strip().split("\n")

        lst_lines = [(".", lines_local)]

        if lst_cmd_git_status_repo:
            print(" ".join(lst_cmd_git_status_repo))

            result = subprocess.run(
                lst_cmd_git_status_repo,
                capture_output=True,
                text=True,
                check=True,
            )
            lines_project = result.stdout.strip().split("\n\n")
        else:
            lines_project = []

        if os.path.isfile(".odoo-version"):
            with open(".odoo-version") as txt:
                odoo_version = txt.read()
            path_addons = os.path.join(
                f"odoo{odoo_version}", "addons", "addons"
            )
            if os.path.exists(os.path.join(path_addons, ".git")):
                # Detected hidden private repository
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=path_addons,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                output = result.stdout.strip()
                if output:
                    lines_addons_project = f"project {path_addons}/\n" + output
                    lines_project.append(lines_addons_project)

        for str_project_line in lines_project:
            line_repo = str_project_line.split("\n")
            projet_name = line_repo[0]
            lines_local = line_repo[1:]
            directory_project = projet_name[len("project ") :]
            lst_lines.append((directory_project, lines_local))

        modified_files = []
        for directory, lines in lst_lines:
            for line in lines:
                if not line:
                    continue

                try:
                    has_space = False
                    file_path_space = ""
                    if '"' in line:
                        has_space = True
                        file_path_space = line[
                            line.index('"') + 1 : line.rindex('"')
                        ]
                        line = line.replace(f'"{file_path_space}"', "replace")
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
                    if has_space:
                        file_path = file_path_space
                    # Remove ignoring
                    if (
                        file_path.endswith(".zip")
                        or file_path.endswith(".tar.gz")
                        or file_path.endswith("__pycache__/")
                    ):
                        continue
                    file_path = os.path.join(directory, file_path)

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
        status, output = execute_shell(cmd_format)
        if status != 0:
            print(output)
        sys.exit(status)
