#!./.venv/bin/python
import argparse
import logging
import os
import sys
from collections import defaultdict

from colorama import Fore, Style
from git import Repo
from git.exc import GitCommandError, NoSuchPathError

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(new_path)

from script.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Compare actual code with a manifest.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        default="./default.xml",
        help="The manifest to compare with actual code.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    dct_remote, dct_project, default_remote = git_tool.get_manifest_xml_info(
        filename=config.manifest, add_root=True
    )
    default_branch_name = default_remote.get(
        "@revision", git_tool.default_branch
    )
    dct_result = defaultdict(int)
    i = 0
    total = len(dct_project)
    for name, project in dct_project.items():
        i += 1
        path = project.get("@path")
        print(f"{i}/{total} - {path}")
        branch_name = project.get("@revision", default_branch_name)
        organization = project.get("@remote", git_tool.default_project_name)

        try:
            git_repo = Repo(path)
        except NoSuchPathError:
            print(
                f"{Fore.YELLOW}Warning{Style.RESET_ALL} missing project"
                f" {path}."
            )
            dct_result["WARNING"] += 1
            continue

        value = git_repo.git.branch("--show-current")
        if not value:
            # TODO maybe need to check divergence with local branch and not remote branch
            commit_head = git_repo.git.rev_parse("HEAD")
            try:
                commit_branch = git_repo.git.rev_parse(
                    f"{organization}/{branch_name}"
                )
            except GitCommandError:
                # Cannot get information
                if branch_name == commit_head:
                    print(
                        f"{Fore.GREEN}PASS{Style.RESET_ALL} Not on specified"
                        " branch, no divergence"
                    )
                    dct_result["PASS"] += 1
                else:
                    print(
                        f"{Fore.RED}ERROR{Style.RESET_ALL} manifest revision"
                        f" is {branch_name} and commit {commit_head}."
                    )
                    dct_result["ERROR"] += 1
                continue
            if commit_branch != commit_head:
                print(
                    f"{Fore.YELLOW}WARNING{Style.RESET_ALL} Not on specified"
                    " branch, got a divergence."
                )
                dct_result["WARNING"] += 1
            else:
                print(
                    f"{Fore.GREEN}PASS{Style.RESET_ALL} Not on specified"
                    " branch, no divergence"
                )
                dct_result["PASS"] += 1
        elif branch_name != value:
            value_hash = git_repo.git.rev_parse(value)
            if git_repo.git.rev_parse(branch_name) == value_hash:
                print(
                    f"{Fore.GREEN}PASS{Style.RESET_ALL} Not same branch, no"
                    " divergence"
                )
                dct_result["PASS"] += 1
            else:
                # Check if the new branch is pushed
                commit_branch = git_repo.git.rev_parse(
                    f"{organization}/{value}"
                )
                if commit_branch == value_hash:
                    print(
                        f"{Fore.YELLOW}WARNING{Style.RESET_ALL} New branch"
                        f" '{value}', divergence, but it's push on remote."
                    )
                    dct_result["WARNING"] += 1
                else:
                    print(
                        f"{Fore.RED}ERROR{Style.RESET_ALL} manifest revision"
                        f" is {branch_name} and actual revision is {value}."
                    )
                    dct_result["ERROR"] += 1
        else:
            print(f"{Fore.GREEN}PASS{Style.RESET_ALL}")
            dct_result["PASS"] += 1

    str_result = ""
    if dct_result["PASS"]:
        str_result += (
            f"{Fore.GREEN}PASS: {dct_result['PASS']}{Style.RESET_ALL}"
        )
    if dct_result["WARNING"]:
        if str_result:
            str_result += " "
        str_result += (
            f"{Fore.YELLOW}WARNING: {dct_result['WARNING']}{Style.RESET_ALL}"
        )
    if dct_result["ERROR"]:
        if str_result:
            str_result += " "
        str_result += (
            f"{Fore.RED}ERROR: {dct_result['ERROR']}{Style.RESET_ALL}"
        )
    print(str_result)


if __name__ == "__main__":
    main()
