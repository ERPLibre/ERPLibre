#!./.venv/bin/python
import argparse
import logging
import os
import sys

from colorama import Fore, Style
from git import Repo  # pip install gitpython
from retrying import retry  # pip install retrying

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
        description="""Push all addons git.""",
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
    i = 0
    total = len(dct_project)
    for name, project in dct_project.items():
        i += 1
        path = project.get("@path")
        print(f"{i}/{total} - {path}")
        organization = project.get("@remote", git_tool.default_project_name)

        try:
            git_repo = Repo(path)
            retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
                git_repo.git.push
            )(organization, "--tags")
        except:
            print(
                f"{Fore.RED}ERROR{Style.RESET_ALL} cannot push --tags for path"
                f" {path} organization {organization}"
            )


if __name__ == "__main__":
    main()
