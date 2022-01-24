#!./.venv/bin/python
import argparse
import asyncio
import datetime
import logging
import os
import sys
import time
import uuid
from typing import Tuple

from colorama import Fore

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)

LOG_FILE = "./.venv/make_test.log"


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Run code generator test in parallel.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--ignore_init_check_git",
        action="store_true",
        help="Will not stop or init check if contain git change.",
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
    lst_error = []
    lst_warning = []

    for i, result in enumerate(tpl_result):
        extract_result(
            result, task_list[i].cr_code.co_name, lst_error, lst_warning
        )

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
    print(f"Log file {LOG_FILE}")


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


async def test_exec(
    path_module_check: str,
    generated_module=None,
    tested_module=None,
    search_class_module=None,
    script_after_init_check=None,
    lst_init_module_name=None,
    test_name=None,
    install_path=None,
) -> Tuple[str, int]:

    test_result = ""
    test_status = 0
    if install_path is None:
        install_path = path_module_check

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
        res, status = await run_command(
            "./script/db_restore.py",
            "--database",
            unique_database_name,
            test_name=test_name,
        )
        test_result += res
        test_status += status
        is_db_create = not status

    if not test_status and lst_init_module_name:
        # Parallel execution here

        # No parallel execution here
        str_test = ",".join(lst_init_module_name)
        script_name = (
            "./script/addons/install_addons_dev.sh"
            if tested_module
            else "./script/addons/install_addons.sh"
        )
        res, status = await run_command(
            script_name,
            unique_database_name,
            str_test,
            test_name=test_name,
        )
        test_result += res
        test_status += status

    if not test_status and search_class_module and generated_module:
        path_template_to_generate = os.path.join(
            path_module_check, tested_module
        )
        path_module_to_generate = os.path.join(
            path_module_check, search_class_module
        )
        # Parallel execution here

        # No parallel execution here
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

    if not test_status and tested_module and generated_module:
        # Parallel execution here

        # No parallel execution here
        res, status = await run_command(
            "./script/code_generator/install_and_test_code_generator.sh",
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
            test_name="Init check_git_change",
        )
    ]
    commands = asyncio.gather(*task_list)
    tpl_result = loop.run_until_complete(commands)
    status = any([a[1] for a in tpl_result])
    loop.close()
    return not status


def print_summary_task(task_list):
    for task in task_list:
        print(task.cr_code.co_name)


# START TEST


async def run_demo_test() -> Tuple[str, int]:
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
        "./addons/TechnoLibre_odoo-code-generator-template",
        lst_init_module_name=lst_test_name,
        test_name="demo_test",
    )

    return res, status


async def run_mariadb_test() -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Migrator
    res, status = await test_exec(
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
    )
    test_result += res
    test_status += status

    # Template
    res, status = await test_exec(
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_mariadb_sql_example_1",
        tested_module="code_generator_template_demo_mariadb_sql_example_1",
        search_class_module="demo_mariadb_sql_example_1",
        lst_init_module_name=[
            "code_generator_portal",
            "demo_mariadb_sql_example_1",
        ],
        test_name="mariadb_test-template",
    )
    test_result += res
    test_status += status

    # Code generator
    res, status = await test_exec(
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="demo_mariadb_sql_example_1",
        lst_init_module_name=[
            "code_generator_portal",
        ],
        tested_module="code_generator_demo_mariadb_sql_example_1",
        test_name="mariadb_test-code-generator",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_multiple_test() -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    lst_generated_module = [
        "code_generator_demo",
        "demo_helpdesk_data",
        "demo_website_data",
        "demo_internal",
        "demo_portal",
        "theme_website_demo_code_generator",
        "demo_website_leaflet",
        "demo_website_snippet",
    ]
    lst_tested_module = [
        "code_generator_demo",
        "code_generator_demo_export_helpdesk",
        "code_generator_demo_export_website",
        "code_generator_demo_internal",
        "code_generator_demo_portal",
        "code_generator_demo_theme_website",
        "code_generator_demo_website_leaflet",
        "code_generator_demo_website_snippet",
    ]
    # Multiple
    res, status = await test_exec(
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_multiple_test",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_inherit_test() -> Tuple[str, int]:
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
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_inherit_test",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_auto_backup_test() -> Tuple[str, int]:
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
        "./addons/OCA_server-tools/auto_backup",
        generated_module=",".join(lst_generated_module),
        tested_module=",".join(lst_tested_module),
        test_name="code_generator_auto_backup_test",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_portal_test() -> Tuple[str, int]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_portal",
        tested_module="code_generator_template_demo_portal",
        # search_class_module="demo_mariadb_sql_example_1",
        lst_init_module_name=[
            "demo_portal",
        ],
        test_name="code_generator_template_demo_portal",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_internal_inherit_test() -> Tuple[
    str, int
]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        "./addons/TechnoLibre_odoo-code-generator-template",
        generated_module="code_generator_demo_internal_inherit",
        tested_module="code_generator_template_demo_internal_inherit",
        # search_class_module="code_generator_demo_internal_inherit",
        lst_init_module_name=[
            "demo_internal_inherit",
        ],
        test_name="code_generator_template_demo_internal_inherit",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_code_generator_template_demo_sysadmin_cron_test() -> Tuple[
    str, int
]:
    test_result = ""
    test_status = 0
    # Template
    res, status = await test_exec(
        "./addons/OCA_server-tools/auto_backup",
        generated_module="code_generator_auto_backup",
        tested_module="code_generator_template_demo_sysadmin_cron",
        # search_class_module="code_generator_demo_internal_inherit",
        lst_init_module_name=[
            "auto_backup",
        ],
        test_name="code_generator_template_demo_sysadmin_cron",
        install_path="./addons/TechnoLibre_odoo-code-generator-template",
    )
    test_result += res
    test_status += status

    return test_result, test_status


async def run_helloworld_test() -> Tuple[str, int]:
    res, status = await run_command(
        "./test/code_generator/hello_world.sh", test_name="helloworld_test"
    )

    return res, status


def run_all_test() -> None:
    task_list = []

    task_list.append(run_demo_test())
    task_list.append(run_helloworld_test())
    task_list.append(run_mariadb_test())
    task_list.append(run_code_generator_multiple_test())
    task_list.append(run_code_generator_inherit_test())
    task_list.append(run_code_generator_auto_backup_test())
    task_list.append(run_code_generator_template_demo_portal_test())
    task_list.append(run_code_generator_template_demo_internal_inherit_test())
    task_list.append(run_code_generator_template_demo_sysadmin_cron_test())

    print_summary_task(task_list)

    if asyncio.get_event_loop().is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
    loop = asyncio.get_event_loop()
    commands = asyncio.gather(*task_list)
    tpl_result = loop.run_until_complete(commands)
    loop.close()
    print_log(task_list, tpl_result)
    check_result(task_list, tpl_result)


def main():
    config = get_config()
    start_time = time.time()
    if not config.ignore_init_check_git:
        success = check_git_change()
    else:
        success = True
    if success:
        run_all_test()
    end_time = time.time()
    diff_sec = end_time - start_time
    # print(f"Time execution {diff_sec:.3f}s")
    print(f"Time execution {datetime.timedelta(seconds=diff_sec)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
