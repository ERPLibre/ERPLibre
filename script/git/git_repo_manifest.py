#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
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
from script.setops import engine as setops_engine

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


def drop_group(remotes, projects, group):
    """(remotes, projects) sans les projets du groupe `group`, ni les
    remotes que seuls ces projets utilisaient.

    Le manifeste lu ici est le manifeste local fusionné, et le fichier
    régénéré — `manifest/default.dev.xml` par défaut — en reprend les
    projets, y compris ceux que le poste y a ajoutés : mobile, versions
    d'Odoo installées, manifeste privé. Seuls en sortent les projets de
    `group` — `setops`, le moteur Set-OPS, qui se rapatrie sur demande — et
    la forge qui ne sert qu'eux : sans ce tri, un `repo init -m` qui
    viserait ce fichier les rapatrierait sans qu'on l'ait demandé. Un
    remote encore utilisé par un projet gardé reste.
    """
    gardes = {
        k: p
        for k, p in projects.items()
        if group not in setops_engine.groups_of(p.get("@groups"))
    }
    utilises = {p.get("@remote") for p in gardes.values()}
    orphelins = {
        p.get("@remote")
        for k, p in projects.items()
        if k not in gardes and p.get("@remote") not in utilises
    }
    return (
        {k: r for k, r in remotes.items() if k not in orphelins},
        gardes,
    )


def main():
    config = get_config()
    git_tool = GitTool()

    repos = git_tool.get_source_repo_addons(
        repo_path=config.dir, add_repo_root=True
    )
    repo_list = [
        git_tool.get_transformed_repo_info_from_url(
            a.get("url"),
            repo_path=config.dir,
            get_obj=True,
            is_submodule=a.get("is_submodule"),
            sub_path=a.get("sub_path"),
            revision=a.get("revision"),
            clone_depth=a.get("clone_depth"),
        )
        for a in repos
    ]

    # Update origin to new repo
    if not config.clear:
        remotes, projects, _ = git_tool.get_manifest_xml_info(
            repo_path=config.dir, add_root=True
        )
        remotes, projects = drop_group(remotes, projects, setops_engine.GROUP)
    else:
        remotes = {}
        projects = {}
    kwargs = {}
    if config.default_branch:
        kwargs["default_branch"] = config.default_branch
    git_tool.generate_repo_manifest(
        repo_list,
        output=f"{config.dir}{config.manifest}",
        remotes_config=remotes,
        projects_config=projects,
        keep_original=config.keep_origin,
        **kwargs,
    )
    git_tool.generate_generate_config()


if __name__ == "__main__":
    main()
