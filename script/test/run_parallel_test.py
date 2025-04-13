#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import asyncio
import configparser
import datetime
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from typing import Tuple

import aioshutil
import git
from colorama import Fore, Style

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script import lib_asyncio

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)

LOG_FILE = "./.venv/make_test.log"
CONFIG_TESTCASE_JSON = "./script/test/config_testcase.json"


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Run code generator test in parallel (asyncio).
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--ignore_init_check_git",
        action="store_true",
        help="Will not stop or init check if contain git change.",
    )
    parser.add_argument(
        "--no_parallel",
        action="store_true",
        help="Will run in serial.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Execute coverage file.",
    )
    parser.add_argument(
        "--keep_cache",
        action="store_true",
        help=(
            "Will not delete the temporary directory, check in print and log."
        ),
    )
    parser.add_argument(
        "-p",
        "--max_process",
        type=int,
        default=0,
        help="Max processor to use. If 0, use max.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable asyncio debugging",
    )
    parser.add_argument(
        "--json_model",
        help="Model of data to run test in json",
    )
    parser.add_argument(
        "--output_result_dir",
        help=(
            "A path of existing directory, will export a file per test with"
            " status/result and log."
        ),
    )
    args = parser.parse_args()
    return args


lst_ignore_warning = [
    "have the same label:",
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
]

lst_ignore_error = [
    "fetchmail_notify_error_to_sender",
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_name_unique"',
    'ERROR: constraint "db_backup_db_backup_name_unique" of relation'
    ' "db_backup" does not exist',
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_days_to_keep_positive"',
    'ERROR: constraint "db_backup_db_backup_days_to_keep_positive" of relation'
    ' "db_backup" does not exist',
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
]


def extract_result(result, test_name, lst_error, lst_warning):
    lst_log = result[0].split("\n")
    for log_line in lst_log:
        is_ignore_error = False
        if "error" in log_line.lower():
            # Remove ignore error
            for ignore_error in lst_ignore_error:
                if ignore_error in log_line:
                    is_ignore_error = True
                    break
            if not is_ignore_error:
                lst_error.append(log_line)

        is_ignore_warning = False
        if "warning" in log_line.lower():
            # Remove ignore warning
            for ignore_warning in lst_ignore_warning:
                if ignore_warning in log_line:
                    is_ignore_warning = True
                    break
            if not is_ignore_warning:
                lst_warning.append(log_line)
    if result[1]:
        lst_error.append(f"Return status error for test {test_name}")


def check_result(task_list, tpl_result):
    status = True
    lst_error = []
    lst_warning = []

    for i, result in enumerate(tpl_result):
        extract_result(
            result, task_list[i].cr_code.co_name, lst_error, lst_warning
        )

    if lst_error:
        status = False

    if lst_warning:
        print(f"{Fore.YELLOW}{len(lst_warning)} WARNING{Style.RESET_ALL}")
        i = 0
        for warning in lst_warning:
            i += 1
            print(f"[{i}]{warning}")

    if lst_error:
        print(f"{Fore.RED}{len(lst_error)} ERROR{Style.RESET_ALL}")
        i = 0
        for error in lst_error:
            i += 1
            print(f"[{i}]{error}")

    if lst_error or lst_warning:
        str_result = (
            f"{Fore.RED}{len(lst_error)} ERROR{Style.RESET_ALL}"
            f" {Fore.YELLOW}{len(lst_warning)} WARNING{Style.RESET_ALL}"
        )
    else:
        str_result = f"{Fore.GREEN}SUCCESS{Style.RESET_ALL} 🍰"

    print(f"{Fore.BLUE}Summary TEST {str_result}{Style.RESET_ALL}")
    return status


def print_log(lst_task, tpl_result):
    if len(lst_task) != len(tpl_result):
        _logger.error("Different length for log... What happen?")
        return
    with open(LOG_FILE, "w") as f:
        for i, task in enumerate(lst_task):
            result = tpl_result[i]
            status_str = (
                f"{Fore.GREEN}PASS{Style.RESET_ALL}"
                if not result[1]
                else f"{Fore.RED}FAIL{Style.RESET_ALL}"
            )
            f.write(
                f"\nTest execution {i + 1} - {status_str} -"
                f" {task.cr_code.co_name}\n\n"
            )
            if result[0]:
                f.write(result[0])
                f.write("\n")


def print_log_output_into_dir(tpl_result, output_dir):
    date_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i, result in enumerate(tpl_result):
        log = result[0]
        status = result[1]
        test_name = result[2]
        test_name_file_name = test_name.replace(" ", "")
        time_execution = result[3]
        log_file = os.path.join(output_dir, test_name_file_name)
        with open(log_file, "w") as f:
            f.write(f"{status}\n")
            f.write(f"{test_name}\n")
            f.write(f"{time_execution}\n")
            f.write(f"{date_now}\n")
            status_str = (
                f"{Fore.GREEN}PASS{Style.RESET_ALL}"
                if not status
                else f"{Fore.RED}FAIL{Style.RESET_ALL}"
            )
            f.write(
                f"\nTest execution {i + 1} - {status_str} - {test_name}\n\n"
            )
            if log:
                f.write(log)
                f.write("\n")


async def run_command(*args, test_name=None):
    # Create subprocess
    start_time = time.time()
    cmd_str = " ".join(args)
    process = await asyncio.create_subprocess_exec(
        *args,
        # stdout must a pipe to be accessible as process.stdout
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()
    end_time = time.time()
    diff_sec = end_time - start_time
    # Return stdout + stderr, returncode
    str_out = "\n" + stdout.decode().strip() + "\n" if stdout else ""
    str_err = "\n" + stderr.decode().strip() + "\n" if stderr else ""
    status_str = (
        f"{Fore.RED}FAIL{Style.RESET_ALL}"
        if process.returncode
        else f"{Fore.GREEN}PASS{Style.RESET_ALL}"
    )
    if test_name:
        str_output_init = (
            f"\n\n{status_str} [{test_name}] [{diff_sec:.3f}s] Execute"
            f' "{cmd_str}"\n\n'
        )
    else:
        str_output_init = (
            f'\n\n{status_str} [{diff_sec:.3f}s] Execute "{cmd_str}"\n\n'
        )
    all_output = str_out + str_err
    print(str_output_init)
    if process.returncode:
        lst_error = []
        lst_warning = []
        extract_result(
            (all_output, process.returncode), test_name, lst_error, lst_warning
        )
        for error in lst_error:
            print(f"\t{error}")
        for warning in lst_warning:
            print(f"\t{warning}")
    return str_output_init + all_output, process.returncode


def update_config(
    origin_config,
    new_path_config,
    lst_path_to_add_config=None,
    lst_path_to_remove_config=None,
    module_name=None,
):
    config_parser = configparser.ConfigParser()
    config_parser.read(origin_config)
    str_path = config_parser["options"]["addons_path"].strip(",")
    lst_path = str_path.split(",")

    # Clean path from test
    if lst_path_to_remove_config:
        for remove_key in lst_path_to_remove_config:
            if remove_key.startswith("./"):
                remove_key = remove_key[2:]
            if module_name and remove_key.endswith(module_name):
                remove_key = remove_key[: -(len(module_name) + 1)]
            for s_path in lst_path:
                if s_path.endswith(remove_key):
                    lst_path.remove(s_path)
                    break
    if lst_path_to_add_config:
        for add_path in lst_path_to_add_config:
            if module_name and add_path.endswith(module_name):
                add_path = add_path[: -(len(module_name) + 1)]
            lst_path.insert(0, add_path)
    s_new_path = ",".join(lst_path)
    config_parser["options"]["addons_path"] = s_new_path
    with open(new_path_config, "w") as configfile:
        config_parser.write(configfile)


async def test_exec(
    path_module_check: str,
    generated_module=None,
    generate_path=None,
    tested_module=None,
    search_class_module=None,
    script_after_init_check=None,
    lst_init_module_name=None,
    file_to_restore=None,
    file_to_restore_origin=False,
    test_name=None,
    install_path=None,
    run_in_sandbox=True,
    restore_db_image_name="erplibre_base",
    keep_cache=False,
    coverage=False,
) -> Tuple[str, int, str, float]:
    time_init = datetime.datetime.now()
    test_result = ""
    test_status = 0
    origin_path_module_check = path_module_check
    if search_class_module:
        if install_path is not None:
            path_template_to_generate = os.path.join(
                install_path, tested_module
            )
        elif generate_path:
            path_template_to_generate = os.path.join(
                generate_path, tested_module
            )
        else:
            path_template_to_generate = os.path.join(
                path_module_check, tested_module
            )
        if generate_path is not None:
            path_module_to_generate = os.path.join(
                generate_path, search_class_module
            )
        else:
            path_module_to_generate = os.path.join(
                path_module_check, search_class_module
            )
    else:
        path_template_to_generate = None
        path_module_to_generate = None

    use_test_path_generic = False
    destination_path = None
    temp_dir_name = None
    if run_in_sandbox:
        if keep_cache:
            temp_dir = tempfile.mkdtemp()
            temp_dir_name = temp_dir
        else:
            temp_dir = tempfile.TemporaryDirectory()
            temp_dir_name = temp_dir.name
        print(temp_dir_name)
        temp_dir_name = os.path.join(temp_dir_name, "workspace")
        os.mkdir(temp_dir_name)

        lst_path_to_add_config = []
        lst_path_to_remove_config = []
        if not os.path.exists(path_module_check):
            # TODO wrong return
            return (
                f"{Fore.RED}Error{Style.RESET_ALL} var path_module_check"
                f" '{path_module_check}' not exist.",
                -1,
            )

        copy_path_module_check = path_module_check
        path_module_check = os.path.normpath(
            os.path.join(temp_dir_name, path_module_check)
        )

        if generated_module and path_module_check.endswith(
            "/" + generated_module
        ):
            use_test_path_generic = True
            destination_path = path_module_check[
                : -(len(generated_module) + 1)
            ]
            copy_path = copy_path_module_check[: -(len(generated_module) + 1)]
        elif search_class_module and path_module_check.endswith(
            "/" + search_class_module
        ):
            destination_path = path_module_check[
                : -(len(search_class_module) + 1)
            ]
            copy_path = copy_path_module_check[
                : -(len(search_class_module) + 1)
            ]
        else:
            destination_path = path_module_check
            copy_path = copy_path_module_check

        lst_path_to_add_config.append(destination_path)
        lst_path_to_remove_config.append(copy_path)

        ignore_tree = await aioshutil.ignore_patterns(".git", "setup")
        await aioshutil.copytree(
            copy_path, destination_path, ignore=ignore_tree
        )
        # destination_path_with_git = os.path.join(destination_path, ".git")
        # if os.path.exists(destination_path_with_git):
        #     await aioshutil.rmtree(destination_path_with_git)
        # destination_path_with_setup = os.path.join(destination_path, "setup")
        # if os.path.exists(destination_path_with_setup):
        #     await aioshutil.rmtree(destination_path_with_setup)

        if tested_module:
            lst_module_to_test = tested_module.split(",")
            for module_name in lst_module_to_test:
                # Update path to change new emplacement
                s_lst_path_tested_module = (
                    await lib_asyncio.run_command_get_output(
                        "find", "./addons/", "-name", module_name
                    )
                )
                if not s_lst_path_tested_module:
                    # TODO wrong return
                    return (
                        f"{Fore.RED}Error{Style.RESET_ALL} cannot find module"
                        f" '{path_module_check}' not exist.",
                        -1,
                    )
                else:
                    lst_path_tested_module = (
                        s_lst_path_tested_module.strip().split("\n")
                    )
                    s_first_path = lst_path_tested_module[0]
                    parent_dir = os.path.dirname(s_first_path)
                    # Copy it
                    if copy_path != parent_dir:
                        os.path.basename(parent_dir)
                        new_destination_path = os.path.join(
                            os.path.dirname(destination_path),
                            os.path.basename(parent_dir),
                        )
                        ignore_tree = await aioshutil.ignore_patterns(
                            ".git", "setup"
                        )
                        await aioshutil.copytree(
                            parent_dir,
                            new_destination_path,
                            ignore=ignore_tree,
                        )
                        # destination_path_with_git = os.path.join(
                        #     new_destination_path, ".git"
                        # )
                        # if os.path.exists(destination_path_with_git):
                        #     await aioshutil.rmtree(destination_path_with_git)
                        lst_path_to_add_config.append(new_destination_path)
                        lst_path_to_remove_config.append(parent_dir)

                    new_s_first_path = os.path.normpath(
                        os.path.join(temp_dir_name, s_first_path)
                    )

                    s_lst_path_generated_module = (
                        await lib_asyncio.run_command_get_output(
                            "find",
                            "./addons/",
                            "-name",
                            generated_module,
                            cwd=temp_dir_name,
                        )
                    )
                    if s_lst_path_generated_module:
                        lst_path_generated_module = (
                            s_lst_path_generated_module.strip().split("\n")
                        )
                        s_first_path = os.path.normpath(
                            os.path.join(
                                temp_dir_name,
                                os.path.dirname(lst_path_generated_module[0]),
                            )
                        )
                    else:
                        # TODO This is wrong... bug in template if reach this case
                        s_first_path = destination_path

                    hook_file = os.path.join(new_s_first_path, "hooks.py")
                    if not os.path.exists(hook_file):
                        test_status += 1
                        test_result += f"Hook file '{hook_file}' not exist."
                        delta = datetime.datetime.now() - time_init
                        total_time = delta.total_seconds()
                        return test_result, test_status, test_name, total_time
                    with open(hook_file) as hook:
                        hook_line = hook.read()
                        has_template = (
                            "template_dir = os.path.normpath" in hook_line
                        )

                        # Goal, update path_module_generate, maybe commented
                        # Goal, update template_dir, maybe not exist
                        # TODO need to refactor this and use AST and not string research

                        # try find nb space indentation
                        lst_f_key = [
                            "# path_module_generate = ",
                            "#path_module_generate = ",
                            "path_module_generate = ",
                        ]
                        nb_space_indentation = None
                        first_index = None
                        for f_key in lst_f_key:
                            if f_key in hook_line:
                                first_index = hook_line.find(f_key)
                                f_begin_index = (
                                    hook_line.rfind("\n", 0, first_index) + 1
                                )
                                nb_space_indentation = (
                                    first_index - f_begin_index
                                )
                                break
                        if nb_space_indentation is None:
                            # TODO wrong return
                            return (
                                f"Cannot find keys '{lst_f_key}' in"
                                f" {hook_file}",
                                -1,
                            )
                        end_string = "\n\n"
                        index_end_string = hook_line.find(
                            end_string, first_index
                        )

                        if has_template:
                            new_hook_line = (
                                hook_line[: first_index + len(f_key)]
                                + f'"{s_first_path}"\n'
                                + f'{nb_space_indentation * " "}template_dir ='
                                f' "{s_first_path}/" + MODULE_NAME\n\n'
                                + hook_line[index_end_string:]
                            )
                        else:
                            new_hook_line = (
                                hook_line[: first_index + len(f_key)]
                                + f'"{s_first_path}"\n'
                                + hook_line[index_end_string:]
                            )
                        new_hook_line = new_hook_line.replace(
                            "# path_module_generate = ",
                            "path_module_generate = ",
                        )
                        new_hook_line = new_hook_line.replace(
                            '# "path_sync_code": path_module_generate,',
                            '"path_sync_code": path_module_generate,',
                        )
                    with open(hook_file, "w") as hook:
                        hook.write(new_hook_line)

        # Format editing code before commit
        # await lib_asyncio.run_command_get_output(
        #     "./script/maintenance/format.sh", temp_dir_name
        # )

        # init repo with git
        for dir_to_git in lst_path_to_add_config:
            await lib_asyncio.run_command_get_output(
                "git", "init", ".", cwd=dir_to_git
            )
            await lib_asyncio.run_command_get_output(
                "git", "add", ".", cwd=dir_to_git
            )
            await lib_asyncio.run_command_get_output(
                "git", "commit", "-am", "'first commit'", cwd=dir_to_git
            )

        new_config_path = os.path.join(temp_dir_name, "config.conf")
        update_config(
            "./config.conf",
            new_config_path,
            lst_path_to_add_config=lst_path_to_add_config,
            lst_path_to_remove_config=lst_path_to_remove_config,
            module_name=generated_module,
        )
        if not os.path.exists(new_config_path):
            test_status += 1
            test_result += f"Config file '{new_config_path}' not exist."
            delta = datetime.datetime.now() - time_init
            total_time = delta.total_seconds()
            return test_result, test_status, test_name, total_time
    else:
        new_config_path = None

    if install_path is None:
        install_path = path_module_check
    elif run_in_sandbox:
        install_path = os.path.normpath(
            os.path.join(temp_dir_name, install_path)
        )

    # Check code, init module to install
    if lst_init_module_name:
        for module_name in lst_init_module_name:
            res, status = await run_command(
                "./script/code_generator/check_git_change_code_generator.sh",
                path_module_check,
                module_name,
                test_name=test_name,
            )
            test_result += res
            test_status += status

    # Check code, module to generate
    if tested_module:
        res, status = await run_command(
            "./script/code_generator/check_git_change_code_generator.sh",
            path_module_check,
            tested_module,
            test_name=test_name,
        )
        test_result += res
        test_status += status

    # Leave when detect anomaly in check before start
    if test_status:
        delta = datetime.datetime.now() - time_init
        total_time = delta.total_seconds()
        return test_result, test_status, test_name, total_time

    # Execute script before start
    if script_after_init_check and not test_status:
        res, status = await run_command(script_after_init_check)
        test_result += res
        test_status += status

    is_db_create = False
    unique_database_name = f"test_demo_{uuid.uuid4()}"[:63]
    if not test_status:
        # Create database
        res, status = await run_command(
            "./script/database/db_restore.py",
            "--database",
            unique_database_name,
            "--image",
            restore_db_image_name,
            test_name=test_name,
        )
        test_result += res
        test_status += status
        is_db_create = not status

    if not test_status and lst_init_module_name:
        # Install required module
        str_test = ",".join(lst_init_module_name)
        if coverage:
            script_name = (
                "./script/addons/coverage_install_addons_dev.sh"
                if tested_module
                else "./script/addons/coverage_install_addons.sh"
            )
        else:
            script_name = (
                "./script/addons/install_addons_dev.sh"
                if tested_module
                else "./script/addons/install_addons.sh"
            )
        if new_config_path:
            res, status = await run_command(
                script_name,
                unique_database_name,
                str_test,
                new_config_path,
                test_name=test_name,
            )
        else:
            res, status = await run_command(
                script_name,
                unique_database_name,
                str_test,
                test_name=test_name,
            )
        test_result += res
        test_status += status

    if not test_status and search_class_module and generated_module:
        # Update template with class/model/inherit
        res, status = await run_command(
            "./script/code_generator/search_class_model.py",
            "--quiet",
            "-d",
            path_module_to_generate,
            "-t",
            path_template_to_generate,
            test_name=test_name,
        )
        test_result += res
        test_status += status

    # test_generated_path = (
    #     install_path if destination_path is None else new_destination_path
    # )
    test_generated_path = (
        destination_path if use_test_path_generic else install_path
    )
    # if destination_path is None:
    #     destination_path = install_path

    if not test_status and tested_module and generated_module:
        cmd = (
            "./script/code_generator/coverage_install_and_test_code_generator.sh"
            if coverage
            else "./script/code_generator/install_and_test_code_generator.sh"
        )
        # Finally, the test
        if new_config_path:
            res, status = await run_command(
                cmd,
                unique_database_name,
                tested_module,
                test_generated_path,
                generated_module,
                new_config_path,
                test_name=test_name,
            )
        else:
            res, status = await run_command(
                cmd,
                unique_database_name,
                tested_module,
                install_path,
                generated_module,
                test_name=test_name,
            )
        test_result += res
        test_status += status

    if is_db_create:
        res, status = await run_command(
            "./.venv/bin/python3",
            "./odoo/odoo-bin",
            "db",
            "--drop",
            "--database",
            unique_database_name,
            test_name=test_name,
        )
        test_result += res
        test_status += status

    if file_to_restore:
        lst_file_to_ignore = file_to_restore.strip().split(",")
        if file_to_restore_origin:
            repo_demo_portal = git.Repo(origin_path_module_check)
        else:
            repo_demo_portal = git.Repo(path_module_check)

        status_to_check = repo_demo_portal.git.status("-s")
        if all([f"D {a}" in status_to_check for a in lst_file_to_ignore]):
            # Revert it
            for file_name in lst_file_to_ignore:
                repo_demo_portal.git.checkout(file_name)
        else:
            test_status += 1
            test_result += (
                f"\n\n{Fore.RED}FAIL{Style.RESET_ALL} - inspect to delete file"
                f" {lst_file_to_ignore}"
            )

    delta = datetime.datetime.now() - time_init
    total_time = delta.total_seconds()
    return test_result, test_status, test_name, total_time


def check_git_change():
    """
    return True if success
    """
    loop = asyncio.get_event_loop()
    task_list = [
        run_command(
            "./script/code_generator/check_git_change_code_generator.sh",
            "./addons/TechnoLibre_odoo-code-generator-template",
            test_name=(
                "Init check_git_change"
                " TechnoLibre_odoo-code-generator-template"
            ),
        ),
        run_command(
            "./script/code_generator/check_git_change_code_generator.sh",
            "./addons/OCA_server-tools",
            test_name="Init check_git_change OCA_server-tools",
        ),
    ]
    commands = asyncio.gather(*task_list)
    tpl_result = loop.run_until_complete(commands)
    status = any([a[1] for a in tpl_result])
    loop.close()
    return not status


async def run_test_command(
    script_path: str, test_name: str
) -> Tuple[str, int, str, float]:
    time_init = datetime.datetime.now()
    res, status = await run_command(script_path, test_name=test_name)
    delta = datetime.datetime.now() - time_init
    total_time = delta.total_seconds()
    return res, status, test_name, total_time


def run_all_test(config) -> bool:
    if config.json_model:
        json_model = config.json_model
    else:
        with open(CONFIG_TESTCASE_JSON) as config_json:
            json_model = config_json.read()
    dct_model_test = json.loads(json_model)
    lst_test = dct_model_test.get("lst_test")
    if not lst_test:
        _logger.error("Model missing attribute 'lst_test'.")
        return False
    # Sort test by sequence
    dct_task = defaultdict(list)
    dct_task_name = defaultdict(list)
    for dct_test in lst_test:
        sequence = dct_test.get("sequence", 0)
        cb_coroutine = None
        test_name = None
        if dct_test.get("run_command"):
            test_name = dct_test.get("test_name")
            if not test_name:
                raise ValueError(
                    "Missing attribute 'test_name' into the json_model."
                )
            script = dct_test.get("script")
            if not script:
                raise ValueError(
                    "Missing attribute 'script' into the json_model."
                )
            cb_coroutine = run_test_command(script, test_name)
        elif dct_test.get("run_test_exec"):
            path_module_check = dct_test.get("path_module_check")
            if not path_module_check:
                raise ValueError(
                    "Missing attribute 'path_module_check' into the"
                    " json_model."
                )
            generated_module = dct_test.get("generated_module")
            generate_path = dct_test.get("generate_path")
            tested_module = dct_test.get("tested_module")
            search_class_module = dct_test.get("search_class_module")
            script_after_init_check = dct_test.get("script_after_init_check")
            init_module_name = dct_test.get("init_module_name")
            lst_init_module_name = None
            if init_module_name:
                lst_init_module_name = init_module_name.split(",")
            test_name = dct_test.get("test_name")
            if not test_name:
                raise ValueError(
                    "Missing attribute 'test_name' into the json_model."
                )
            file_to_restore = dct_test.get("file_to_restore")
            file_to_restore_origin = dct_test.get(
                "file_to_restore_origin", False
            )
            install_path = dct_test.get("install_path")
            run_in_sandbox = dct_test.get("run_in_sandbox", True)
            restore_db_image_name = dct_test.get(
                "restore_db_image_name", "erplibre_base"
            )
            keep_cache = config.keep_cache
            coverage = config.coverage
            cb_coroutine = test_exec(
                path_module_check,
                generated_module=generated_module,
                generate_path=generate_path,
                tested_module=tested_module,
                search_class_module=search_class_module,
                script_after_init_check=script_after_init_check,
                lst_init_module_name=lst_init_module_name,
                file_to_restore=file_to_restore,
                file_to_restore_origin=file_to_restore_origin,
                test_name=test_name,
                install_path=install_path,
                run_in_sandbox=run_in_sandbox,
                restore_db_image_name=restore_db_image_name,
                keep_cache=keep_cache,
                coverage=coverage,
            )
        if cb_coroutine:
            dct_task[sequence].append(cb_coroutine)
            dct_task_name[sequence].append(test_name)
    lst_sequence = sorted(list(dct_task.keys()))
    # Print summary
    total_tpl_result = []
    total_tpl_task = []
    # Print summary
    for sequence in lst_sequence:
        lst_task = dct_task[sequence]
        lst_task_name = dct_task_name[sequence]
        print(f"sequence {sequence}")
        lib_asyncio.print_summary_task(lst_task, lst_task_name=lst_task_name)
    # Execute in sequence
    for sequence in lst_sequence:
        lst_task = dct_task[sequence]
        tpl_result, has_asyncio_error = lib_asyncio.execute(config, lst_task)
        if tpl_result:
            total_tpl_result.extend(tpl_result)
        else:
            _logger.error("tpl_result is empty.")
        if lst_task:
            total_tpl_task.extend(lst_task)
        else:
            _logger.error("tpl_task is empty.")

    print_log(total_tpl_task, total_tpl_result)
    status = check_result(total_tpl_task, total_tpl_result)
    if status:
        log_file_print = LOG_FILE
    else:
        log_file_print = f"{Fore.RED}{LOG_FILE}{Style.RESET_ALL}"

    if config.output_result_dir:
        print_log_output_into_dir(total_tpl_result, config.output_result_dir)

    print(f"Log file {log_file_print}")
    return status


def main():
    # TODO configure logger with thread
    # logging.basicConfig(
    #     level=logging.INFO,
    #     format='%(threadName)10s %(name)18s: %(message)s',
    #     stream=sys.stderr,
    # )
    config = get_config()
    start_time = time.time()
    if not config.ignore_init_check_git:
        success = check_git_change()
    else:
        success = True
    status = False
    if success:
        status = run_all_test(config)
    end_time = time.time()
    diff_sec = end_time - start_time
    # print(f"Time execution {diff_sec:.3f}s")
    print(f"Time execution {datetime.timedelta(seconds=diff_sec)}")

    return int(not status)


if __name__ == "__main__":
    sys.exit(main())
