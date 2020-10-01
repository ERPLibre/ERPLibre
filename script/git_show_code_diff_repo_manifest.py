#!./.venv/bin/python
import os
import sys
import argparse
import logging
from git import Repo
from git.exc import GitCommandError

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
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
        epilog='''\
'''
    )
    parser.add_argument('-m', '--manifest', required=True,
                        help="The manifest to compare with actual code.")
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    dct_remote, dct_project, default_remote = git_tool.get_manifest_xml_info(filename=config.manifest, add_root=True)
    default_branch_name = default_remote.get("@revision", git_tool.default_branch)
    i = 0
    total = len(dct_project)
    for name, project in dct_project.items():
        i += 1
        path = project.get("@path")
        print(f"{i}/{total} - {path}")
        branch_name = project.get("@revision", default_branch_name)
        organization = project.get("@remote")
        if not organization:
            print(f"ERROR missing @remote on project {path}.")
            continue

        git_repo = Repo(path)
        value = git_repo.git.branch("--show-current")
        if not value:
            # TODO maybe need to check divergence with local branch and not remote branch
            commit_head = git_repo.git.rev_parse("HEAD")
            try:
                commit_branch = git_repo.git.rev_parse(f"{organization}/{branch_name}")
            except GitCommandError:
                print("ERROR Something wrong with this repo.")
                continue
            if commit_branch != commit_head:
                print("WARNING Not on specified branch, got a divergence.")
            else:
                print("PASS Not on specified branch, no divergence.")
        elif branch_name != value:
            print(f"ERROR, manifest revision is {branch_name} and actual revision is {value}.")
        else:
            print("PASS")


if __name__ == '__main__':
    main()
