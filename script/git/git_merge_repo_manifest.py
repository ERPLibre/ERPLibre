#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
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
from script.git.manifest_freeze import FREEZE_ATTR, apply_freeze
from script.version.erplibre_state import get_version_extra

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
MOBILE_PATH = os.path.join("mobile", "erplibre_home_mobile")
ODOO_VERSION_PATH = ".odoo-version"


def get_config(argv=None):
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
    parser.add_argument(
        "--with_extra",
        action="store_true",
        help=(
            "Add extra modules manifest for current Odoo version"
            " (e.g. CybroOdoo). Version read from .odoo-version."
        ),
    )
    parser.add_argument(
        "--with_new_manifest",
        action="store_true",
        help="Will overwrite local manifest",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help=(
            f"Pin every project to the commit of its @{FREEZE_ATTR},"
            " keeping its branch in @upstream and @dest-branch. A project"
            " without one follows its branch, with a warning."
        ),
    )
    args = parser.parse_args(argv)
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    if config.input:
        input_paths = [a for a in config.input.split(";") if a]
    else:
        input_paths = default_input_paths(
            with_OCA=config.with_OCA,
            with_mobile=config.with_mobile,
            with_extra=config.with_extra,
            with_new_manifest=config.with_new_manifest,
        )

    remotes_total = {}
    projects_total = {}
    default_remote_total = None

    # Un fichier cité deux fois ne compte qu'une fois, à sa première place.
    # L'ordre reste celui de la liste : le dernier fichier qui définit un
    # projet l'emporte, et un ensemble rendrait ce gagnant aléatoire.
    input_paths = list(dict.fromkeys(input_paths))

    for index, input_path in enumerate(input_paths):
        (
            remotes,
            projects,
            default_remote,
        ) = git_tool.get_manifest_xml_info(filename=input_path, add_root=True)

        # Support multiple version odoo
        projects_copy = projects
        projects = {}
        for key, value in projects_copy.items():
            new_key = f"{key}+{value.get('@path')}"
            projects[new_key] = value

        if len(input_paths) == 1:
            # Only 1 input, same output
            remotes_total = remotes
            projects_total = projects
            break
        elif not index:
            # Preparation to accumulate data
            remotes_total = copy.deepcopy(remotes)
            projects_total = copy.deepcopy(projects)
            continue
        for key, value in projects.items():
            if key in projects_total:
                # Le commit gelé suit la définition qui l'emporte : celui
                # d'un fichier antérieur ne survit pas à une redéfinition
                # qui n'en porte pas, et qui peut changer de branche.
                projects_total[key].pop(f"@{FREEZE_ATTR}", None)
                if config.att_revision_only:
                    revision = value.get("@revision")
                    if revision:
                        projects_total[key]["@revision"] = revision
                    sha = value.get(f"@{FREEZE_ATTR}")
                    if sha:
                        projects_total[key][f"@{FREEZE_ATTR}"] = sha
                else:
                    projects_total[key].update(value)
            else:
                projects_total[key] = copy.deepcopy(value)

        for key, value in remotes.items():
            if key in remotes_total:
                remotes_total[key].update(value)
            else:
                remotes_total[key] = copy.deepcopy(value)

    geles, manquants = apply_freeze(projects_total, config.freeze)
    if config.freeze:
        print(f"Freeze: {len(geles)} projects pinned to their commit.")
        if manquants:
            print(
                f"WARNING: {len(manquants)} projects have no"
                f" {FREEZE_ATTR} and follow their branch:"
            )
            for cle in sorted(manquants):
                print(f"  - {cle}")

    git_tool.generate_repo_manifest(
        remotes_config=remotes_total,
        projects_config=projects_total,
        output=config.output,
        default_remote=default_remote_total,
    )


def default_input_paths(
    with_OCA=False,
    with_mobile=False,
    with_extra=False,
    with_new_manifest=False,
):
    """Les fichiers sources du manifeste local, dans leur ordre de fusion.

    Sans `with_new_manifest`, les drapeaux se déduisent du checkout : la
    version d'Odoo active, les versions installées, l'application mobile,
    les modules extra. Un fichier cité deux fois n'est gardé qu'à sa
    PREMIÈRE place, et l'ordre est celui de la liste : lors de la fusion,
    le dernier fichier qui définit un projet l'emporte.
    """
    odoo_version = None
    if os.path.isfile(ODOO_VERSION_PATH):
        with open(ODOO_VERSION_PATH, "r") as f:
            odoo_version = f.readline().strip()

    # Add local manifest
    if not with_new_manifest:
        if odoo_version:
            with_OCA = True
        if os.path.isdir(MOBILE_PATH):
            with_mobile = True
        if odoo_version and get_version_extra(odoo_version.strip()):
            with_extra = True

    input_paths = []
    if with_OCA:
        append_file_path_manifest(input_paths, DEFAULT_PATH_MANIFEST_ODOO_CONF)
        if os.path.exists(".odoo-version"):
            if odoo_version:
                path_manifest_odoo_version = os.path.join(
                    "manifest", f"git_manifest_odoo{odoo_version}.xml"
                )
                if os.path.exists(path_manifest_odoo_version):
                    input_paths.append(path_manifest_odoo_version)
                else:
                    print(
                        f"ERROR: {path_manifest_odoo_version} does not exist"
                    )
                path_manifest_odoo_version = os.path.join(
                    "manifest", f"git_manifest_odoo{odoo_version}_dev.xml"
                )
                if os.path.exists(path_manifest_odoo_version):
                    input_paths.append(path_manifest_odoo_version)

        if os.path.exists(DEFAULT_PATH_INSTALLED_ODOO_VERSION):
            with open(DEFAULT_PATH_INSTALLED_ODOO_VERSION, "r") as f:
                installed_versions = [a.strip() for a in f.readlines()]
            if installed_versions:
                for installed_odoo_version in installed_versions:
                    path_manifest_odoo_version = os.path.join(
                        "manifest",
                        f"git_manifest_{installed_odoo_version}.xml",
                    )
                    if os.path.exists(path_manifest_odoo_version):
                        input_paths.append(path_manifest_odoo_version)
                    else:
                        print(
                            f"ERROR: {path_manifest_odoo_version} does not exist"
                        )
                    path_manifest_odoo_version = os.path.join(
                        "manifest",
                        f"git_manifest_{installed_odoo_version}_dev.xml",
                    )
                    if os.path.exists(path_manifest_odoo_version):
                        input_paths.append(path_manifest_odoo_version)

    if with_mobile:
        append_file_path_manifest(
            input_paths, DEFAULT_PATH_MANIFEST_MOBILE_CONF
        )
    if with_extra and odoo_version:
        path_extra = os.path.join(
            "manifest",
            f"git_manifest_extra_odoo{odoo_version.strip()}.xml",
        )
        if os.path.exists(path_extra):
            input_paths.append(path_extra)
        else:
            print(f"WARNING: {path_extra} does not exist, skipping extra")
    if not with_mobile or not with_OCA:
        append_file_path_manifest(input_paths, DEFAULT_PATH_MANIFEST_CONF)
    append_file_path_manifest(input_paths, DEFAULT_PATH_MANIFEST_PRIVATE_CONF)

    return list(dict.fromkeys(input_paths))


def append_file_path_manifest(input_paths, path_manifest):
    if os.path.exists(path_manifest):
        with open(path_manifest, "r") as f:
            csv_file = csv.DictReader(f)
            for row in csv_file:
                filepath = row.get("filepath")
                input_paths.append(filepath)


if __name__ == "__main__":
    main()
