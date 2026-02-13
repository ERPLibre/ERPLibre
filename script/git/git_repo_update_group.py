#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.execute import execute
from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Update config.conf file with group specified in manifest file.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--group",
        default="",
        help="Prod by default, use 'dev' for manifest/default.dev.xml",
    )
    parser.add_argument(
        "--extra-addons-path",
        default="",
        help="Separate by , to add extra path for config addons_path",
    )
    parser.add_argument(
        "--ignore-odoo-path",
        action="store_true",
        help="Will remove odoo path, need this feature for OpenUpgrade when Odoo <= 13",
    )
    parser.add_argument(
        "--from_backup_path",
        help="Will read backup path and whitelist the repo",
    )
    parser.add_argument(
        "--from_backup_name",
        help="Will read backup name and whitelist the repo",
    )
    parser.add_argument(
        "--add_repo",
        help="Add repo, separate by ; for list",
    )
    parser.add_argument(
        "--database",
        help="Add repo from module found into database.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()
    execute_cmd = execute.Execute()
    index_to_remove = len(os.getcwd()) + 1

    filter_group = config.group if config.group else None

    lst_whitelist = []
    if config.from_backup_path or config.from_backup_name:
        # script/database/get_repo_from_backup.py
        # --backup_name bpir_prod_5_dec_2025_2026-02-04_14h27m54s.zip
        if config.from_backup_path:
            cmd = f"./script/database/get_repo_from_backup.py --backup_path {config.from_backup_path}"
        else:
            cmd = f"./script/database/get_repo_from_backup.py --backup_name {config.from_backup_name}"
        status, output = execute_cmd.exec_command_live(
            cmd,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
            return_status_and_output=True,
        )
        for line in output:
            repo_name = line[index_to_remove:].strip()
            lst_whitelist.append(repo_name)

    if config.database:
        cmd = f"./script/database/get_module_list_from_database.py --database {config.database}"
        status, output = execute_cmd.exec_command_live(
            cmd,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
            return_status_and_output=True,
        )
        str_module = ";".join(output)
        cmd = f'./script/database/get_repo_from_module.py --module "{str_module}"'
        status, output = execute_cmd.exec_command_live(
            cmd,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
            return_status_and_output=True,
        )
        for line in output:
            repo_name = line[index_to_remove:].strip()
            lst_whitelist.append(repo_name)

    if config.add_repo:
        lst_add_repo = [a.strip() for a in config.add_repo.split(";")]
    else:
        lst_add_repo = []

    git_tool.generate_generate_config(
        filter_group=filter_group,
        extra_path=config.extra_addons_path,
        ignore_odoo_path=config.ignore_odoo_path,
        lst_add_repo=lst_add_repo,
        lst_whitelist=lst_whitelist,
    )


if __name__ == "__main__":
    main()
