#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool

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
        "--clear",
        action="store_true",
        help="Create a new manifest and clear old configuration.",
    )
    parser.add_argument(
        "--keep_origin",
        action="store_true",
        help="Create origin remote. TODO.",
    )
    parser.add_argument(
        "-m",
        "--manifest",
        default="manifest/default.dev.xml",
        help="The manifest file path to generate.",
    )
    parser.add_argument(
        "--default_branch",
        default=False,
        help="The manifest default branch.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    lst_repo = git_tool.get_source_repo_addons(
        repo_path=config.dir, add_repo_root=True
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

    # Update origin to new repo
    if not config.clear:
        dct_remote, dct_project, _ = git_tool.get_manifest_xml_info(
            repo_path=config.dir, add_root=True
        )
    else:
        dct_remote = {}
        dct_project = {}
    kwargs = {}
    if config.default_branch:
        kwargs["default_branch"] = config.default_branch
    git_tool.generate_repo_manifest(
        lst_repo_organization,
        output=f"{config.dir}{config.manifest}",
        dct_remote=dct_remote,
        dct_project=dct_project,
        keep_original=config.keep_origin,
        **kwargs,
    )
    git_tool.generate_generate_config()


if __name__ == "__main__":
    main()
