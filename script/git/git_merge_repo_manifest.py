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
from script.version.erplibre_state import (
    MODE_FIGE,
    get_git_repo,
    get_version_extra,
)

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
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    odoo_version = None
    if os.path.isfile(ODOO_VERSION_PATH):
        with open(ODOO_VERSION_PATH, "r") as f:
            odoo_version = f.readline()

    # Add local manifest
    if not config.with_new_manifest:
        if odoo_version:
            config.with_OCA = True
        if os.path.isdir(MOBILE_PATH):
            config.with_mobile = True
        if odoo_version and get_version_extra(odoo_version.strip()):
            config.with_extra = True

    input_paths = config.input
    if not input_paths:
        input_paths = []
        if config.with_OCA:
            append_file_path_manifest(
                input_paths, DEFAULT_PATH_MANIFEST_ODOO_CONF
            )
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

        if config.with_mobile:
            append_file_path_manifest(
                input_paths, DEFAULT_PATH_MANIFEST_MOBILE_CONF
            )
        if config.with_extra and odoo_version:
            path_extra = os.path.join(
                "manifest",
                f"git_manifest_extra_odoo{odoo_version.strip()}.xml",
            )
            if os.path.exists(path_extra):
                input_paths.append(path_extra)
            else:
                print(f"WARNING: {path_extra} does not exist, skipping extra")
        if not config.with_mobile or not config.with_OCA:
            append_file_path_manifest(input_paths, DEFAULT_PATH_MANIFEST_CONF)
        append_file_path_manifest(
            input_paths, DEFAULT_PATH_MANIFEST_PRIVATE_CONF
        )

    remotes_total = {}
    projects_total = {}
    default_remote_total = None

    # Be sure all input is unique
    input_paths = list(set(input_paths))

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
                if config.att_revision_only:
                    revision = value.get("@revision")
                    if revision:
                        projects_total[key]["@revision"] = revision
                else:
                    projects_total[key].update(value)
            else:
                projects_total[key] = copy.deepcopy(value)

        for key, value in remotes.items():
            if key in remotes_total:
                remotes_total[key].update(value)
            else:
                remotes_total[key] = copy.deepcopy(value)

    # Le gel, s'il est désigné, a le dernier mot sur les révisions : c'est
    # lui qui distingue un plan de travail épinglé d'un plan de travail qui
    # suit ses branches. Sans gel désigné, rien ne change.
    reglages = get_git_repo()
    touches = projeter_gel(
        projects_total, reglages.get("mode"), reglages.get("gel")
    )
    if touches:
        _logger.info(
            f"Freeze '{reglages.get('gel')}' applied in"
            f" '{reglages.get('mode')}' mode: {touches} projects"
        )

    git_tool.generate_repo_manifest(
        remotes_config=remotes_total,
        projects_config=projects_total,
        output=config.output,
        default_remote=default_remote_total,
    )


def lire_gel(chemin_gel):
    """{« nom+chemin »: (revision, upstream)} d'un fichier de gel.

    Le gel est produit par « repo manifest -r -o » : chaque projet y porte
    le COMMIT dans @revision et la BRANCHE dans @upstream. Un seul fichier
    porte donc les deux lectures, ce qui évite d'en tenir deux qui
    dériveraient l'un de l'autre sans que rien ne le dise.
    """
    import xml.etree.ElementTree as ET

    if not chemin_gel or not os.path.isfile(chemin_gel):
        return {}
    try:
        racine = ET.parse(chemin_gel).getroot()
    except ET.ParseError as exc:
        _logger.warning(f"Cannot read freeze file {chemin_gel}: {exc}")
        return {}
    return {
        f"{p.get('name')}+{p.get('path')}": (
            p.get("revision"),
            p.get("upstream"),
        )
        for p in racine.findall("project")
        if p.get("name") and p.get("path")
    }


def projeter_gel(projects, mode, chemin_gel):
    """Réécrit @revision d'après le gel. Rend le nombre de projets touchés.

    En mode figé, chaque projet reçoit le COMMIT du gel : le plan de travail
    se reconstruit à l'identique, des mois plus tard. En mode dev, il reçoit
    la BRANCHE que le gel a enregistrée, donc la pointe du jour.

    Un projet absent du gel n'est pas touché : il est arrivé APRÈS, et lui
    inventer une révision le sortirait de son manifeste.
    """
    gel = lire_gel(chemin_gel)
    if not gel:
        return 0
    touches = 0
    for key, value in projects.items():
        fige = gel.get(key)
        if not fige:
            continue
        revision, upstream = fige
        neuve = revision if mode == MODE_FIGE else upstream
        if neuve and value.get("@revision") != neuve:
            value["@revision"] = neuve
            touches += 1
    return touches


def append_file_path_manifest(input_paths, path_manifest):
    if os.path.exists(path_manifest):
        with open(path_manifest, "r") as f:
            csv_file = csv.DictReader(f)
            for row in csv_file:
                filepath = row.get("filepath")
                input_paths.append(filepath)


if __name__ == "__main__":
    main()
