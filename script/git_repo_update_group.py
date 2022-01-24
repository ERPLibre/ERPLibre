#!./.venv/bin/python
import argparse
import logging
import os
import sys

import git
from git import Repo

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(new_path)

from script.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    config = GitTool.get_project_config()

    # TODO update description
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
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    filter_group = config.group if config.group else None

    git_tool.generate_generate_config(filter_group=filter_group)


if __name__ == "__main__":
    main()
