#!./.venv/bin/python
import argparse
import datetime
import logging
import os
import shutil
import sys
from collections import defaultdict

from dateutil.relativedelta import relativedelta
from git import Repo

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)

PROJECT_NAME = os.path.basename(os.getcwd())
VENV_PATH = "./.venv"
CACHE_CLONE_PATH = os.path.join(VENV_PATH, "stat_OCA")
CST_FILE_SOURCE_REPO_ADDONS = "source_repo_addons.csv"
IGNORE_REPO_LIST = (
    "https://github.com/OCA/odoo-module-migrator.git",
    "https://github.com/OCA/maintainer-tools.git",
    "https://github.com/OCA/connector.git",
    "https://github.com/itpp-labs/odoo-development.git",
    "https://github.com/itpp-labs/odoo-port-docs.git",
    "https://github.com/itpp-labs/odoo-test-docs.git",
    "https://github.com/odoo/documentation.git",
    "https://github.com/OCA/odoo-module-migrator.git",
    "https://github.com/OCA/maintainer-tools.git",
)
DCT_CHANGE_ADDONS_PATH = {"odoo": "/addons/"}
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
        "--ignore_release_date",
        action="store_true",
        help=(
            f"Give result without release date logic, this means it gives"
            f" result in past of release version."
        ),
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
        default="/OCA/",
        help=f"keyword to ignore separate by ','",
    )
    parser.add_argument(
        "-b",
        "--branches",
        default="6.0,6.1,7.0,8.0,9.0,10.0,11.0,12.0,13.0,14.0,15.0,16.0",
        help="Branch to analyse, separate by ','",
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
    return args


def main():
    config = get_config()
    lst_branch = config.branches.split(",")
    before_date = config.before_date

    die(
        not os.path.isdir(VENV_PATH),
        f"Missing {VENV_PATH} venv path, did you install ERPLibre?",
    )

    if config.clean_all and os.path.isdir(CACHE_CLONE_PATH):
        _logger.info(f"Delete directory {CACHE_CLONE_PATH}")
        shutil.rmtree(CACHE_CLONE_PATH)

    if not os.path.isdir(CACHE_CLONE_PATH):
        _logger.info(f"Create directory {CACHE_CLONE_PATH}")
        os.mkdir(CACHE_CLONE_PATH)

    lst_repo_url = get_OCA_repo_list(config)
    dct_repo = clone_all_repo(config, lst_repo_url)
    lst_stat = []
    for nb_year in range(config.more_year + 1):
        # key is odoo version, value is set of module name
        from_date = before_date + relativedelta(years=nb_year)
        if config.ignore_release_date:
            lst_branch_adapt = lst_branch
        else:
            lst_branch_adapt = get_branches_supported_date(
                lst_branch, from_date
            )
        (
            result,
            result_module,
            lst_all_unique_module,
            dct_reverse_lst_module,
            dct_missing_branch,
        ) = extract_module_from_all_version(
            lst_branch_adapt, from_date, dct_repo
        )
        lst_stat.append(
            (
                result,
                result_module,
                lst_all_unique_module,
                dct_reverse_lst_module,
                dct_missing_branch,
            )
        )
    for nb_year, (
        result,
        result_module,
        lst_all_unique_module,
        dct_reverse_lst_module,
        dct_missing_branch,
    ) in enumerate(lst_stat):
        str_extra = ""

        from_date = before_date + relativedelta(years=nb_year)
        if config.ignore_release_date:
            lst_branch_adapt = lst_branch
        else:
            lst_branch_adapt = get_branches_supported_date(
                lst_branch, from_date
            )

        if before_date:
            str_extra = f" before {from_date}"
        # Count remove repo
        count_remove_repo_stat = 0
        for repo_name, list_branch in dct_missing_branch.items():
            if len(list_branch) == len(lst_branch_adapt):
                count_remove_repo_stat += 1

        print(f"Stat nb module by branch name{str_extra}")
        print(f"With {len(lst_repo_url) - count_remove_repo_stat}")
        for branch_name in lst_branch_adapt:
            if branch_name:
                print(f"{branch_name}\t{len(result_module[branch_name])}")
    print("end of stat")


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


def get_branches_supported_date(lst_branch, from_date):
    return [a for a in lst_branch if DCT_VERSION_RELEASE[a] < from_date]


def extract_module_from_all_version(lst_branch, before_date, dct_repo):
    result = defaultdict(dict)
    result_module = {}
    lst_all_unique_module = set()
    dct_reverse_lst_module = defaultdict(list)
    dct_missing_branch = defaultdict(list)

    for branch_name in lst_branch:
        if not branch_name:
            continue
        # TODO bug conflict repo name
        _logger.info(f"Check branch name '{branch_name}'")
        lst_branch_unique_module = set()
        result_module[branch_name] = lst_branch_unique_module
        remote_branch_name = f"origin/{branch_name}"
        for repo_name, repo_git in dct_repo.items():
            try:
                repo_git.git.rev_parse("--verify", remote_branch_name)
            except:
                _logger.warning(
                    f"Missing branch '{branch_name}' for repo '{repo_name}'"
                )
                result[repo_name][branch_name] = None
                dct_missing_branch[repo_name].append(branch_name)
                continue
            if before_date:
                checkout_commit = repo_git.git.rev_list(
                    "-n", "1", "--before", before_date, remote_branch_name
                )
                if not checkout_commit:
                    _logger.warning(
                        f"Branch '{branch_name}' repo '{repo_name}' contain no"
                        f" commit before date {before_date}"
                    )
                    continue
            else:
                checkout_commit = branch_name
            # clean before checkout
            repo_git.git.stash("save")
            repo_git.git.clean("-xdf")
            try:
                repo_git.git.checkout(checkout_commit)
            except Exception as e:
                _logger.error(
                    f"Cannot checkout for branch '{branch_name}' repo"
                    f" '{repo_name}'"
                )
                raise e
            lst_unique_module = set()
            result[repo_name][branch_name] = lst_unique_module

            suffix_path = DCT_CHANGE_ADDONS_PATH.get(repo_name, "")
            repo_path = os.path.join(CACHE_CLONE_PATH, repo_name) + suffix_path
            for dir_name in os.listdir(repo_path):
                path_module_dir = os.path.join(repo_path, dir_name)
                path_module_dir_manifest = os.path.join(
                    path_module_dir, "__manifest__.py"
                )
                path_module_dir_openerp = os.path.join(
                    path_module_dir, "__openerp__.py"
                )
                if os.path.isdir(path_module_dir) and (
                    os.path.isfile(path_module_dir_manifest)
                    or os.path.isfile(path_module_dir_openerp)
                ):
                    lst_unique_module.add(dir_name)
                    lst_all_unique_module.add(dir_name)
                    lst_branch_unique_module.add(dir_name)
                    dct_reverse_lst_module[dir_name].append(
                        f"{branch_name} - {repo_name}"
                    )
    return (
        result,
        result_module,
        lst_all_unique_module,
        dct_reverse_lst_module,
        dct_missing_branch,
    )


def clone_all_repo(config, lst_repo):
    dct_repo = {}
    for i, repo_url in enumerate(lst_repo):
        repo_name = repo_url.split("/")[-1][:-4]
        repo_path = os.path.join(CACHE_CLONE_PATH, repo_name)
        _logger.info(f"{i} - Repo '{repo_name}' url '{repo_url}'")
        if os.path.isdir(repo_path):
            cloned_repo = Repo(repo_path)
            assert cloned_repo.__class__ is Repo
        else:
            if config.history_length:
                cloned_repo = Repo.clone_from(
                    repo_url, repo_path, depth=config.history_length
                )
            else:
                cloned_repo = Repo.clone_from(repo_url, repo_path)
            assert cloned_repo.__class__ is Repo
        dct_repo[repo_name] = cloned_repo
    return dct_repo


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
