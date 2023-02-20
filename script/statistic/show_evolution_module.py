#!./.venv/bin/python
import argparse
import datetime
import logging
import os
import shutil
import sys
import csv
from collections import defaultdict

from dateutil.relativedelta import relativedelta

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script import lib_asyncio

FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"), format=FORMAT)

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
VENV_PATH = "./.venv"
CACHE_CLONE_PATH = os.path.join(VENV_PATH, "stat_repo")
CST_FILE_SOURCE_REPO_ADDONS = "source_repo_addons.csv"
MAX_COROUTINE = 300
IGNORE_REPO_LIST = (
    "https://github.com/OCA/odoo-module-migrator.git",
    "https://github.com/OCA/maintainer-tools.git",
    "https://github.com/itpp-labs/odoo-development.git",
    "https://github.com/itpp-labs/odoo-port-docs.git",
    "https://github.com/itpp-labs/odoo-test-docs.git",
    "https://github.com/odoo/documentation.git",
    "https://github.com/ERPLibre/ERPLibre_image_db.git",
    "https://github.com/muk-it/muk_docs.git",
)
DCT_CHANGE_ADDONS_PATH = {"odoo_odoo": ["/addons/", "/odoo/addons/"]}
DCT_VERSION_RELEASE = {
    "1.0": datetime.datetime.strptime("2005-02-01", "%Y-%m-%d").date(),
    "2.0": datetime.datetime.strptime("2005-03-01", "%Y-%m-%d").date(),
    "3.0": datetime.datetime.strptime("2005-09-01", "%Y-%m-%d").date(),
    "4.0": datetime.datetime.strptime("2006-12-01", "%Y-%m-%d").date(),
    "5.0": datetime.datetime.strptime("2009-04-01", "%Y-%m-%d").date(),
    "6.0": datetime.datetime.strptime("2009-10-01", "%Y-%m-%d").date(),
    "6.1": datetime.datetime.strptime("2012-02-27", "%Y-%m-%d").date(),
    "7.0": datetime.datetime.strptime("2012-12-01", "%Y-%m-%d").date(),
    "8.0": datetime.datetime.strptime("2014-09-01", "%Y-%m-%d").date(),
    "9.0": datetime.datetime.strptime("2015-11-01", "%Y-%m-%d").date(),
    "10.0": datetime.datetime.strptime("2016-10-01", "%Y-%m-%d").date(),
    "11.0": datetime.datetime.strptime("2017-10-01", "%Y-%m-%d").date(),
    "12.0": datetime.datetime.strptime("2018-10-01", "%Y-%m-%d").date(),
    "13.0": datetime.datetime.strptime("2019-10-01", "%Y-%m-%d").date(),
    "14.0": datetime.datetime.strptime("2020-10-01", "%Y-%m-%d").date(),
    "15.0": datetime.datetime.strptime("2021-10-01", "%Y-%m-%d").date(),
    "16.0": datetime.datetime.strptime("2022-10-01", "%Y-%m-%d").date(),
}
CSV_HEADER_MODULE_NAME = "Nom technique"
# TODO use rich progress bar when clone
# TODO support conflict repo name


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Clone all OCA repo from file 'source_repo_addons.csv', checkout branch from param --branches
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--clean_all",
        action="store_true",
        help=f"Wipe all data from path '{CACHE_CLONE_PATH}'",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=f"More information",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable asyncio debugging",
    )
    parser.add_argument(
        "--ignore_release_date",
        action="store_true",
        help=(
            f"Give result without release date logic, this means it gives"
            f" result in past of release version."
        ),
    )
    parser.add_argument(
        "--no_parallel",
        action="store_true",
        help=(
            f"By default run in parallel with all CPU, this disable"
            f" parallelism with asyncio"
        ),
    )
    parser.add_argument(
        "--force_git_fetch",
        action="store_true",
        help=f"Force git fetch to update it all remote.",
    )
    parser.add_argument(
        "-p",
        "--max_process",
        type=int,
        default=0,
        help="Max processor to use. If 0, use max.",
    )
    parser.add_argument(
        "--history_length",
        default=0,
        type=int,
        help=(
            f"Set to 0 to clone all history, default 0. Can be another number."
            f" This broke other version."
        ),
    )
    parser.add_argument(
        "--more_year",
        default=0,
        type=int,
        help=(
            f"At 0, search only present before_date, > 0, add year to"
            f" before_date for multiple stat. Depend on param 'before_date'"
        ),
    )
    parser.add_argument(
        "--before_date",
        type=lambda d: datetime.datetime.strptime(d, "%Y-%m-%d").date(),
        default=None,
        help=f"Set a check date before, example '2020-01-01'",
    )
    parser.add_argument(
        "--filter",
        default="",
        help=f"keyword to ignore separate by ','. Suggest /OCA/",
    )
    parser.add_argument(
        "-b",
        "--branches",
        default="6.1,7.0,8.0,9.0,10.0,11.0,12.0,13.0,14.0,15.0,16.0",
        help="Branch to analyse, separate by ','",
    )
    parser.add_argument(
        "--compare_csv",
        help=(
            "Path of CSV, search column 'Nom technique' and give list of"
            " difference module, missing from CSV. Need only 1 branches and no"
            " more_year."
        ),
    )
    args = parser.parse_args()

    die(
        args.history_length < 0,
        f"Argument 'history_length' need to be positive",
    )
    die(
        args.more_year < 0,
        f"Argument 'more_year' need to be positive",
    )
    die(
        args.before_date is None and args.more_year > 0,
        f"Cannot specify more_year when before_date is not set.",
    )
    # clean parameter
    args.branches = ",".join([a for a in args.branches.split(",") if a])
    die(
        any(
            [
                a
                for a in args.branches.split(",")
                if a not in DCT_VERSION_RELEASE.keys()
            ]
        ),
        "The params branches contain not supported version, check"
        f" DCT_VERSION_RELEASE : {list(DCT_VERSION_RELEASE.keys())}",
    )
    die(
        args.compare_csv
        and (args.more_year > 0 or len(args.branches.split(",")) > 1),
        f"When use param compare_csv, cannot use more_year and only 1 branch.",
    )
    if args.compare_csv:
        die(
            not os.path.isfile(args.compare_csv),
            f"Path of {args.compare_csv} need to be a file path.",
        )
    return args


def main():
    config = get_config()
    lst_branch = config.branches.split(",")
    before_date = config.before_date
    lst_unique_module = set()
    lst_unique_uninstallable_module = set()

    # Check
    die(
        not os.path.isdir(VENV_PATH),
        f"Missing {VENV_PATH} venv path, did you install ERPLibre?",
    )

    # Setup environment
    _logger.info(f"Setup {CACHE_CLONE_PATH}")
    if config.clean_all and os.path.isdir(CACHE_CLONE_PATH):
        _logger.info(f"Delete directory {CACHE_CLONE_PATH}")
        shutil.rmtree(CACHE_CLONE_PATH)

    if not os.path.isdir(CACHE_CLONE_PATH):
        _logger.info(f"Create directory {CACHE_CLONE_PATH}")
        os.mkdir(CACHE_CLONE_PATH)

    # Get list of Repo
    lst_repo_url = get_OCA_repo_list(config)

    # Clone all repo
    _logger.info(f"Clone repo")
    lst_task_clone = [
        clone_repo(i, a, config.force_git_fetch)
        for i, a in enumerate(lst_repo_url)
    ]
    lst_repo_path = lib_asyncio.execute(
        config, lst_task_clone, use_uvloop=True
    )

    # Extract module list
    _logger.info("Extract module")
    lst_task = []
    for nb_year in range(config.more_year + 1):
        # key is odoo version, value is set of module name
        lst_branch_adapt = lst_branch
        from_date = before_date
        if before_date:
            from_date += relativedelta(years=nb_year)
            if not config.ignore_release_date:
                lst_branch_adapt = get_branches_supported_date(
                    lst_branch, from_date
                )

        # for branch in lst_branch_adapt:
        for repo_name, repo_path in lst_repo_path:
            lst_task.append(
                extract_module(
                    lst_branch_adapt, repo_name, repo_path, from_date
                )
            )
            if config.debug:
                _logger.info(
                    "Setup extract module:"
                    f" {repo_name} {repo_path} {lst_branch_adapt} {from_date}"
                )

    _logger.info(f"Execute extract module with {len(lst_task)} coroutine.")
    # Need to set a max, or crash
    if len(lst_task) / MAX_COROUTINE > 1:
        lst_result = []
        for i in range(int(len(lst_task) / MAX_COROUTINE) + 1):
            min_i = i * MAX_COROUTINE
            max_i = min((i + 1) * MAX_COROUTINE, len(lst_task))
            _logger.info(f"Partial execution {min_i} to {max_i}")
            tpl_result = lib_asyncio.execute(
                config, lst_task[min_i:max_i], use_uvloop=True
            )
            lst_result += tpl_result
        tpl_result = lst_result
    else:
        tpl_result = lib_asyncio.execute(config, lst_task, use_uvloop=True)
    _logger.info("Analyse information")
    dct_result = defaultdict(lambda: defaultdict(int))
    dct_result_unique = defaultdict(set)
    for lst_result_stack in tpl_result:
        for dct_result_module in lst_result_stack:
            # lst_module, branch, path, repo, before_date
            before_date = dct_result_module.get("before_date")
            lst_module = dct_result_module.get("lst_module")
            lst_uninstallable_module = dct_result_module.get(
                "lst_uninstallable_module"
            )
            branch = dct_result_module.get("branch")
            # path = dct_result_module.get("path")
            # repo = dct_result_module.get("repo")
            dct_result[before_date][branch] += len(lst_module)
            dct_result_unique[before_date].update(lst_module)
            lst_unique_module.update(lst_module)
            lst_unique_uninstallable_module.update(lst_uninstallable_module)

    # Show result
    _logger.info("Show result")
    for before_date, dct_branch_result in dct_result.items():
        str_extra = ""
        if before_date:
            str_extra = f" before {before_date}"
        print(f"Stat nb module by branch name{str_extra}")
        for branch_name, count_module in dct_branch_result.items():
            print(f"{branch_name}\t{count_module}")
    for before_date, set_result in dct_result_unique.items():
        str_extra = ""
        if before_date:
            str_extra = f" before {before_date}"
        print(f"Diff nb unique module{str_extra}, length {len(set_result)}")
    print("end of stat")

    if config.compare_csv:
        index_header = -1
        lst_unique_module_csv = set()
        with open(config.compare_csv, "r") as csvfile:
            for csv_module in csv.reader(csvfile):
                if index_header == -1:
                    try:
                        index_header = csv_module.index(CSV_HEADER_MODULE_NAME)
                    except Exception as e:
                        _logger.error(
                            f"Missing header {CSV_HEADER_MODULE_NAME} in CSV."
                        )
                        raise e
                else:
                    module_name = csv_module[index_header]
                    if module_name not in lst_unique_uninstallable_module:
                        lst_unique_module_csv.add(module_name)

        lst_missing_module_repo = lst_unique_module_csv.difference(
            lst_unique_module
        )
        lst_missing_module_csv = lst_unique_module.difference(
            lst_unique_module_csv
        )
        print("CSV compare")
        print(f"Module missing from CSV '{len(lst_missing_module_repo)}':")
        print(lst_missing_module_repo)
        print(f"Module missing into CSV '{len(lst_missing_module_csv)}':")
        print(lst_missing_module_csv)


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


def get_branches_supported_date(lst_branch, from_date):
    return [a for a in lst_branch if DCT_VERSION_RELEASE[a] < from_date]


async def extract_module(lst_branch, repo, path, before_date):
    # print(f"{branch} - {path} - {before_date}")
    lst_result = []
    for branch in lst_branch:
        return_value = {
            "lst_module": [],
            "branch": branch,
            "path": path,
            "repo": repo,
            "before_date": before_date,
        }
        remote_branch_name = f"origin/{branch}"

        # Detect commit to check
        # git rev-list -n 1 --before 2022-01-01 origin/12.0
        lst_args = ["git", "rev-list", "-n", "1"]
        if before_date:
            lst_args += ["--before", str(before_date)]
        lst_args += [remote_branch_name]
        (
            commit,
            _,
            status,
        ) = await lib_asyncio.run_command_get_output_and_status(
            *lst_args, cwd=path
        )

        if status:
            # The branch doesn't exist
            # _logger.error(f"Receive status 'git rev-list' {status}")
            continue

        # TODO send msg when no result
        if not commit:
            continue

        commit = commit.strip()

        lst_module_installable = []
        lst_module_uninstallable = []
        # List directory
        lst_suffix_path = DCT_CHANGE_ADDONS_PATH.get(repo, "")
        if type(lst_suffix_path) is str:
            lst_suffix_path = [lst_suffix_path]
        for suffix_path in lst_suffix_path:
            adapt_path = path + suffix_path
            lst_args = ["git", "ls-tree", "-d", "--name-only", commit]
            (
                str_folders,
                _,
                status,
            ) = await lib_asyncio.run_command_get_output_and_status(
                *lst_args, cwd=adapt_path
            )
            if status:
                _logger.error(f"Receive status 'git ls-tree' {status}")
                continue

            # TODO send msg when no result
            if not str_folders:
                continue
            lst_module = str_folders.split()
            if not lst_module:
                continue

            if suffix_path:
                suffix_path = suffix_path[1:]

            for module in lst_module:
                # List directory
                lst_args = [
                    "git",
                    "cat-file",
                    "-p",
                    f"{commit}:{suffix_path}{module}/__manifest__.py",
                ]
                (
                    manifest,
                    _,
                    status,
                ) = await lib_asyncio.run_command_get_output_and_status(
                    *lst_args, cwd=path
                )
                if status:
                    # Maybe __openerp__.py
                    lst_args = [
                        "git",
                        "cat-file",
                        "-p",
                        f"{commit}:{module}/__openerp__.py",
                    ]
                    (
                        manifest,
                        _,
                        status,
                    ) = await lib_asyncio.run_command_get_output_and_status(
                        *lst_args, cwd=adapt_path
                    )
                if status:
                    # Ignore, it's not a module
                    # _logger.error(f"Receive status 'git cat-file' {status}")
                    # return return_value
                    continue
                dct_manifest = eval(manifest + "\n")
                if dct_manifest.get("installable", True):
                    lst_module_installable.append(module)
                else:
                    lst_module_uninstallable.append(module)

        return_value["lst_module"] = lst_module_installable
        return_value["lst_uninstallable_module"] = lst_module_uninstallable
        lst_result.append(return_value)
    return lst_result


async def clone_repo(i, repo_url, force_fetch):
    split_repo_url = repo_url.split("/")
    repo_name = f"{split_repo_url[-2]}_{split_repo_url[-1][:-4]}"
    repo_path = os.path.join(CACHE_CLONE_PATH, repo_name)
    if not os.path.isdir(repo_path):
        await lib_asyncio.run_command_get_output(
            "git", "clone", repo_url, repo_name, cwd=CACHE_CLONE_PATH
        )
        _logger.info(f"[{i}]New clone {repo_path} with {repo_url}")
    elif force_fetch:
        await lib_asyncio.run_command_get_output(
            "git", "fetch", "--all", cwd=CACHE_CLONE_PATH
        )
        _logger.info(f"[{i}]Fetch {repo_path} with {repo_url}")

    return repo_name, repo_path


def get_OCA_repo_list(config):
    with open(CST_FILE_SOURCE_REPO_ADDONS) as file:
        all_lines = file.readlines()
        if all_lines:
            # Validate first line is supported column
            expected_header = "url,path,revision,clone-depth\n"
            if all_lines[0] != expected_header:
                raise Exception(
                    "Not supported csv, please validate"
                    f" {CST_FILE_SOURCE_REPO_ADDONS} with first line"
                    f" {expected_header}"
                )
            # Ignore first line
            all_lines = all_lines[1:]

            # Be sure empty endline at the end of file
            if all_lines[-1][-1] != "\n":
                all_lines[-1] = all_lines[-1] + "\n"
        all_lines = [a.split(",")[0] for a in all_lines]
        # TODO support split(",")
        if config.filter:
            all_lines = [
                a
                for a in all_lines
                if config.filter in a and a not in IGNORE_REPO_LIST
            ]
        else:
            all_lines = [a for a in all_lines if a not in IGNORE_REPO_LIST]
    return all_lines


if __name__ == "__main__":
    main()
