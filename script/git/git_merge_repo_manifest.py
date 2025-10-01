#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import copy
import csv
import logging
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)


DEFAULT_PATH_MANIFEST_CONF = os.path.join("conf", "git_manifest.csv")
DEFAULT_PATH_MANIFEST_MOBILE_CONF = os.path.join(
    "conf", "git_manifest_mobile.csv"
)
DEFAULT_PATH_MANIFEST_ODOO_CONF = os.path.join("conf", "git_manifest_odoo.csv")
DEFAULT_PATH_MANIFEST_PRIVATE_CONF = os.path.join(
    "private", "default_git_manifest.csv"
)
DEFAULT_PATH_INSTALLED_ODOO_VERSION = os.path.join(
    ".repo", "installed_odoo_version.txt"
)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Replace revision field in input2 from input1 if existing, create an output of new manifest.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--input",
        help="First manifest to merge into input2. Second manifest, overwrite by input1.",
    )
    parser.add_argument(
        "--output",
        default=".repo/local_manifests/erplibre_manifest.xml",
        help="Output of new manifest",
    )
    parser.add_argument(
        "--att_revision_only",
        action="store_true",
        help="Output of new manifest",
    )
    parser.add_argument(
        "--with_OCA", action="store_true", help="Add OCA manifest"
    )
    parser.add_argument(
        "--with_mobile",
        action="store_true",
        help="Add mobile project manifest",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    lst_input = config.input
    if not lst_input:
        lst_input = []
        if config.with_OCA:
            append_file_path_manifest(
                lst_input, DEFAULT_PATH_MANIFEST_ODOO_CONF
            )
            if os.path.exists(".odoo-version"):
                with open(".odoo-version", "r") as f:
                    odoo_version = f.readline()
                if odoo_version:
                    path_manifest_odoo_version = os.path.join(
                        "manifest", f"git_manifest_odoo{odoo_version}.xml"
                    )
                    if os.path.exists(path_manifest_odoo_version):
                        lst_input.append(path_manifest_odoo_version)
                    else:
                        print(
                            f"ERROR: {path_manifest_odoo_version} does not exist"
                        )
                    path_manifest_odoo_version = os.path.join(
                        "manifest", f"git_manifest_odoo{odoo_version}_dev.xml"
                    )
                    if os.path.exists(path_manifest_odoo_version):
                        lst_input.append(path_manifest_odoo_version)

            if os.path.exists(DEFAULT_PATH_INSTALLED_ODOO_VERSION):
                with open(DEFAULT_PATH_INSTALLED_ODOO_VERSION, "r") as f:
                    lst_installed_odoo_version = [
                        a.strip() for a in f.readlines()
                    ]
                if lst_installed_odoo_version:
                    for installed_odoo_version in lst_installed_odoo_version:
                        path_manifest_odoo_version = os.path.join(
                            "manifest",
                            f"git_manifest_{installed_odoo_version}.xml",
                        )
                        if os.path.exists(path_manifest_odoo_version):
                            lst_input.append(path_manifest_odoo_version)
                        else:
                            print(
                                f"ERROR: {path_manifest_odoo_version} does not exist"
                            )
                        path_manifest_odoo_version = os.path.join(
                            "manifest",
                            f"git_manifest_{installed_odoo_version}_dev.xml",
                        )
                        if os.path.exists(path_manifest_odoo_version):
                            lst_input.append(path_manifest_odoo_version)

        elif config.with_mobile:
            append_file_path_manifest(
                lst_input, DEFAULT_PATH_MANIFEST_MOBILE_CONF
            )
        else:
            append_file_path_manifest(lst_input, DEFAULT_PATH_MANIFEST_CONF)
        append_file_path_manifest(
            lst_input, DEFAULT_PATH_MANIFEST_PRIVATE_CONF
        )

    dct_remote_total = {}
    dct_project_total = {}
    default_remote_total = None

    # Be sure all input is unique
    lst_input = list(set(lst_input))

    for index, input_path in enumerate(lst_input):
        (
            dct_remote,
            dct_project,
            default_remote,
        ) = git_tool.get_manifest_xml_info(filename=input_path, add_root=True)

        # Support multiple version odoo
        dct_project_copy = dct_project
        dct_project = {}
        for key, value in dct_project_copy.items():
            new_key = f"{key}+{value.get('@path')}"
            dct_project[new_key] = value

        if len(lst_input) == 1:
            # Only 1 input, same output
            dct_remote_total = dct_remote
            dct_project_total = dct_project
            break
        elif not index:
            # Preparation to accumulate data
            dct_remote_total = copy.deepcopy(dct_remote)
            dct_project_total = copy.deepcopy(dct_project)
            continue
        for key, value in dct_project.items():
            if key in dct_project_total.keys():
                if config.att_revision_only:
                    revision = value.get("@revision")
                    if revision:
                        dct_project_total[key]["@revision"] = revision
                else:
                    dct_project_total[key].update(value)
            else:
                dct_project_total[key] = copy.deepcopy(value)

        for key, value in dct_remote.items():
            if key in dct_remote_total.keys():
                dct_remote_total[key].update(value)
            else:
                dct_remote_total[key] = copy.deepcopy(value)

    git_tool.generate_repo_manifest(
        dct_remote=dct_remote_total,
        dct_project=dct_project_total,
        output=config.output,
        default_remote=default_remote_total,
    )


def append_file_path_manifest(lst_input, path_manifest):
    if os.path.exists(path_manifest):
        with open(path_manifest, "r") as f:
            csv_file = csv.DictReader(f)
            for row in csv_file:
                filepath = row.get("filepath")
                lst_input.append(filepath)


if __name__ == "__main__":
    main()
