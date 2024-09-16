#!./.venv/bin/python
import argparse
import asyncio
import configparser
import datetime
import logging
import os
import sys
import tempfile
import time
import uuid
from typing import Tuple

import aioshutil
import git
from colorama import Fore

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script import lib_asyncio

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)

LOG_FILE = "./.venv/make_test.log"


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
        print(f"{Fore.YELLOW}{len(lst_warning)} WARNING{Fore.RESET}")
        i = 0
        for warning in lst_warning:
            i += 1
            print(f"[{i}]{warning}")

    if lst_error:
        print(f"{Fore.RED}{len(lst_error)} ERROR{Fore.RESET}")
        i = 0
        for error in lst_error:
            i += 1
            print(f"[{i}]{error}")

    if lst_error or lst_warning:
        str_result = (
            f"{Fore.RED}{len(lst_error)} ERROR"
            f" {Fore.YELLOW}{len(lst_warning)} WARNING"
        )
    else:
        str_result = f"{Fore.GREEN}SUCCESS 🍰"

    print(f"{Fore.BLUE}Summary TEST {str_result}{Fore.RESET}")
    return status


def print_log(lst_task, tpl_result):
    if len(lst_task) != len(tpl_result):
        _logger.error("Different length for log... What happen?")
        return
    with open(LOG_FILE, "w") as f:
        for i, task in enumerate(lst_task):
            result = tpl_result[i]
            status_str = "PASS" if not result[1] else "FAIL"
            f.write(
                f"\nTest execution {i + 1} - {status_str} -"
                f" {task.cr_code.co_name}\n\n"
            )
            if result[0]:
                f.write(result[0])
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
    status_str = "FAIL" if process.returncode else "PASS"
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
    config,
    path_module_check: str,
    generated_module=None,
    generate_path=None,
    tested_module=None,
    search_class_module=None,
    script_after_init_check=None,
    lst_init_module_name=None,
    test_name=None,
    install_path=None,
    run_in_sandbox=False,
    restore_db_image_name="erplibre_base",
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    new_destination_path = None
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
        if config.keep_cache:
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
            return (
                f"Error var path_module_check '{path_module_check}' not"
                " exist.",
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
                    return (
                        f"Error cannot find module '{path_module_check}' not"
                        " exist.",
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
        await lib_asyncio.run_command_get_output(
            "./script/maintenance/black.sh", temp_dir_name
        )

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
        return test_result, test_status

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
        if config.coverage:
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
            if config.coverage
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

    return test_result, test_status


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


# START TEST


async def run_demo_test(config) -> Tuple[str, int]:
    lst_test_name = [
        "demo_helpdesk_data",
        "demo_internal",
        "demo_internal_inherit",
        "demo_mariadb_sql_example_1",
        "demo_portal",
        "demo_website_data",
        "demo_website_leaflet",
        "demo_website_snippet",
    ]
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        lst_init_module_name=lst_test_name,
        test_name="demo_test",
    )

    return res, status


async def run_code_generator_migrator_demo_mariadb_sql_example_1_test(
    config,
) -> Tuple[str, int]:
    # Migrator
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="demo_mariadb_sql_example_1",
        tested_module="code_generator_migrator_demo_mariadb_sql_example_1",
        script_after_init_check=(
            "./script/database/restore_mariadb_sql_example_1.sh"
        ),
        lst_init_module_name=[
            "code_generator_portal",
        ],
        test_name="mariadb_test-migrator",
        run_in_sandbox=True,
    )

    return res, status


async def run_code_generator_template_demo_mariadb_sql_example_1_test(
    config,
) -> Tuple[str, int]:
    # Template
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_mariadb_sql_example_1",
        tested_module="code_generator_template_demo_mariadb_sql_example_1",
        search_class_module="demo_mariadb_sql_example_1",
        lst_init_module_name=[
            "code_generator_portal",
            "demo_mariadb_sql_example_1",
        ],
        test_name="mariadb_test-template",
        run_in_sandbox=True,
    )

    return res, status


async def run_code_generator_demo_mariadb_sql_example_1_test(
    config,
) -> Tuple[str, int]:
    # Code generator
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="demo_mariadb_sql_example_1",
        lst_init_module_name=[
            "code_generator_portal",
        ],
        tested_module="code_generator_demo_mariadb_sql_example_1",
        test_name="mariadb_test-code-generator",
        run_in_sandbox=True,
    )

    return res, status


async def run_code_generator_data_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_helpdesk_data",
        # "demo_website_data",
    ]
    lst_tested_module = [
        "code_generator_demo_export_helpdesk",
        # "code_generator_demo_export_website",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_data_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_data_test_part_2(config) -> Tuple[str, int]:
    # TODO merge this test into run_code_generator_data_test
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_website_data",
    ]
    lst_tested_module = [
        "code_generator_demo_export_website",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_data_part_2_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_export_website_attachments_test(
    config,
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_website_attachments_data",
    ]
    lst_tested_module = [
        "code_generator_demo_export_website_attachments",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_export_website_attachments_test",
        run_in_sandbox=True,
        restore_db_image_name="test_website_attachments",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_theme_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "theme_website_demo_code_generator",
    ]
    lst_tested_module = [
        "code_generator_demo_theme_website",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_theme_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_generic_all_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_internal",
        "demo_portal",
        "demo_helpdesk_data",
        "demo_website_data",
        "demo_website_leaflet",
        "demo_website_snippet",
        "theme_website_demo_code_generator",
    ]
    lst_tested_module = [
        "code_generator_demo_internal",
        "code_generator_demo_portal",
        "code_generator_demo_export_helpdesk",
        "code_generator_demo_export_website",
        "code_generator_demo_website_leaflet",
        "code_generator_demo_website_snippet",
        "code_generator_demo_theme_website",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_generic_all_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_website_snippet_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_website_leaflet",
        "demo_website_snippet",
        "demo_website_multiple_snippet",
    ]
    lst_tested_module = [
        "code_generator_demo_website_leaflet",
        "code_generator_demo_website_snippet",
        "code_generator_demo_website_multiple_snippet",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_website_snippet_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    if "code_generator_demo_website_multiple_snippet" in lst_tested_module:
        # Because code_generator_demo_website_multiple_snippet depend on code_generator_demo_portal, it will
        # execute it and this delete file demo_portal/i18n/demo_portal.pot and demo_portal/i18n/fr_CA.po
        lst_file_is_delete = [
            "demo_portal/i18n/demo_portal.pot",
            "demo_portal/i18n/fr_CA.po",
        ]
        path_to_check = os.path.join(
            "addons", "TechnoLibre_odoo-code-generator-template"
        )
        repo_demo_portal = git.Repo(path_to_check)
        status_to_check = repo_demo_portal.git.status("-s")
        if all([f"D {a}" in status_to_check for a in lst_file_is_delete]):
            # Revert it
            for file_name in lst_file_is_delete:
                repo_demo_portal.git.checkout(file_name)
        else:
            test_status += 1
            test_result += (
                f"\n\nFAIL - inspect to delete file ${lst_file_is_delete}"
            )

    return test_result, test_status


async def run_code_generator_demo_generic_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_internal",
        "demo_portal",
    ]
    lst_tested_module = [
        "code_generator_demo_internal",
        "code_generator_demo_portal",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_demo_generic_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_demo_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "code_generator_demo",
    ]
    lst_tested_module = [
        "code_generator_demo",
    ]
    # Multiple
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_demo_test",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_inherit_test(config) -> Tuple[str, int]:
    # TODO can be merge into code_generator_multiple
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "demo_internal_inherit",
    ]
    lst_tested_module = [
        "code_generator_demo_internal_inherit",
    ]
    # Inherit
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_inherit_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_auto_backup_test(config) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "auto_backup",
    ]
    lst_tested_module = [
        "code_generator_auto_backup",
    ]
    # Auto-backup
    res, status = await test_exec(
        config,
        "./addons/OCA_server-tools/auto_backup",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_auto_backup_test",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_portal_test(
    config,
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_portal",
        tested_module="code_generator_template_demo_portal",
        search_class_module="demo_portal",
        lst_init_module_name=[
            "demo_portal",
        ],
        test_name="code_generator_template_demo_portal",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_internal_test(
    config,
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_internal",
        tested_module="code_generator_template_demo_internal",
        search_class_module="demo_internal",
        lst_init_module_name=[
            "demo_internal",
        ],
        test_name="code_generator_template_demo_internal",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_internal_inherit_test(
    config,
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        config,
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_internal_inherit",
        tested_module="code_generator_template_demo_internal_inherit",
        search_class_module="demo_internal_inherit",
        lst_init_module_name=[
            "demo_internal_inherit",
        ],
        test_name="code_generator_template_demo_internal_inherit",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_sysadmin_cron_test(
    config,
) -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        config,
        "./addons/OCA_server-tools/auto_backup",
        generated_module="code_generator_auto_backup",
        generate_path="./addons/OCA_server-tools/",
        tested_module="code_generator_template_demo_sysadmin_cron",
        search_class_module="auto_backup",
        lst_init_module_name=[
            "auto_backup",
        ],
        test_name="code_generator_template_demo_sysadmin_cron",
        install_path="./addons/TechnoLibre_odoo-code-generator-template",
        run_in_sandbox=True,
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_helloworld_test(config) -> Tuple[str, int]:
    res, status = await run_command(
        "./test/code_generator/hello_world.sh", test_name="helloworld_test"
    )

    return res, status


def run_all_test(config) -> None:
    # low in time, at the end for more speed
    task_list = [
        run_code_generator_migrator_demo_mariadb_sql_example_1_test(config),
        run_code_generator_template_demo_mariadb_sql_example_1_test(config),
        run_code_generator_demo_mariadb_sql_example_1_test(config),
        run_code_generator_auto_backup_test(config),
        run_code_generator_template_demo_portal_test(config),
        run_code_generator_template_demo_internal_test(config),
        run_code_generator_template_demo_internal_inherit_test(config),
        run_code_generator_template_demo_sysadmin_cron_test(config),
        run_code_generator_demo_test(config),
        # Begin to run generic test
        # run_code_generator_generic_all_test(config),
        run_code_generator_data_test(config),
        run_code_generator_data_test_part_2(config),
        run_code_generator_export_website_attachments_test(config),
        run_code_generator_theme_test(config),
        run_code_generator_website_snippet_test(config),
        run_code_generator_demo_generic_test(config),
        # End run generic test
        run_code_generator_inherit_test(config),
        run_demo_test(config),
    ]
    task_second_list = [
        # TODO Will cause conflict with the other because write in code_generator_demo/hooks.py
        run_helloworld_test(config),
    ]

    _logger.info("First list task")
    lib_asyncio.print_summary_task(task_list)
    _logger.info("Second list task")
    lib_asyncio.print_summary_task(task_second_list)

    _logger.info("First execution")
    tpl_result = lib_asyncio.execute(config, task_list)
    _logger.info("Second execution")
    tpl_result_second = lib_asyncio.execute(config, task_second_list)

    # Extra
    tpl_result_total = tpl_result + tpl_result_second
    task_list_total = task_list + task_second_list
    print_log(task_list_total, tpl_result_total)
    status = check_result(task_list_total, tpl_result_total)
    if status:
        log_file_print = LOG_FILE
    else:
        log_file_print = f"{Fore.RED}{LOG_FILE}{Fore.RESET}"

    print(f"Log file {log_file_print}")


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
    if success:
        run_all_test(config)
    end_time = time.time()
    diff_sec = end_time - start_time
    # print(f"Time execution {diff_sec:.3f}s")
    print(f"Time execution {datetime.timedelta(seconds=diff_sec)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
