#!./.venv/bin/python
import argparse
import logging
import os
import sys
from pathlib import Path

from git import Repo  # pip install gitpython
from git.exc import GitCommandError

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import git_tool as g_tool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-d",
        "--dir",
        dest="dir",
        default="./",
        help="Path of repo to change remote, including submodule.",
    )
    parser.add_argument(
        "--addons_dir",
        help=(
            "Path of addons to remove auto_install. If empty, will take all"
            " repo from manifest."
        ),
    )
    parser.add_argument(
        "--ignore_commit",
        action="store_true",
        help="Will not do git commit and push.",
    )
    parser.add_argument(
        "--ignore_push",
        action="store_true",
        help="Will not do git push.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = g_tool.GitTool()

    if not config.addons_dir:
        lst_repo = git_tool.get_source_repo_addons(
            repo_path=config.dir, add_repo_root=False
        )
        lst_repo_organization = [
            git_tool.get_transformed_repo_info_from_url(
                a.get("url"),
                repo_path=config.dir,
                get_obj=True,
                is_submodule=a.get("is_submodule"),
                sub_path=a.get("sub_path"),
                revision=a.get("revision"),
                clone_depth=a.get("clone_depth"),
            )
            for a in lst_repo
        ]
    else:
        organization = os.path.basename(config.addons_dir)
        # TODO information is wrong, need to extract organisation and repo_name
        lst_repo_organization = [
            g_tool.Struct(
                **{
                    "organization": organization,
                    "path": config.addons_dir,
                    "relative_path": config.addons_dir,
                    "repo_name": config.addons_dir,
                }
            )
        ]

    lst_ignore_repo = ["odoo"]

    i = 0
    total = len(lst_repo_organization)
    branch_name = "12.0_dev"
    for repo in lst_repo_organization:
        i += 1
        print(f"\nNb element {i}/{total} - {repo.path}")
        is_checkout_branch = False

        if repo.repo_name in lst_ignore_repo:
            print(f"Ignore {repo.repo_name}.")
            continue

        if not config.ignore_commit:
            git_repo = Repo(repo.relative_path)
            # Force checkout branch if exist
            try:
                git_repo.git.checkout(branch_name)
                is_checkout_branch = True
            except GitCommandError:
                try:
                    git_repo.git.checkout(
                        "-t", f"{repo.organization}/{branch_name}"
                    )
                    is_checkout_branch = True
                except GitCommandError:
                    pass

        has_change = get_manifest_external_dependencies(repo)

        if has_change and not config.ignore_commit:
            if not is_checkout_branch:
                git_repo.git.checkout("-b", branch_name)
            # change branch, commit and push
            git_repo.git.add(".")
            git_repo.git.commit("-m", "Set all module auto_install at False")
            if not config.ignore_push:
                git_repo.git.push("-u", repo.organization, branch_name)


def get_lst_manifest_py(relative_path):
    return list(Path(relative_path).rglob("__manifest__.py"))


def get_manifest_external_dependencies(repo):
    has_change = False
    lst_manifest_file = get_lst_manifest_py(repo.relative_path)
    for manifest_file in lst_manifest_file:
        has_change_manifest = False
        with open(manifest_file, "r") as f:
            lst_content = f.readlines()
            i = 0
            for content in lst_content:
                if "auto_install" in content and "True" in content:
                    has_change_manifest = True
                    has_change = True
                    first_char_index = content.find("auto_install")
                    index = content.find("True", first_char_index)
                    lst_content[i] = (
                        content[:index] + "False" + content[index + 4 :]
                    )
                i += 1

        if has_change_manifest:
            print(f"Update file {manifest_file}")
            with open(manifest_file, "w") as f:
                f.writelines(lst_content)

    return has_change


if __name__ == "__main__":
    main()
