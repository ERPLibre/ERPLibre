#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import sys

from git import Repo
from retrying import retry  # pip install retrying

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git.git_tool import GitTool

_logger = logging.getLogger(__name__)
CST_EL_GITHUB_TOKEN = "EL_GITHUB_TOKEN"


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
        "--github_token",
        dest="github_token",
        default=config.get(CST_EL_GITHUB_TOKEN),
        help="GitHub token generated by user",
    )
    parser.add_argument(
        "--open_web_browser",
        action="store_true",
        help="Open web browser for each repo.",
    )
    parser.add_argument(
        "--generate_only_generate_config",
        action="store_true",
        help="Only generate script generate_config.sh.",
    )
    parser.add_argument(
        "--sync_to",
        dest="sync_to",
        help="Only synchronize matching repo, use path compare to repo.",
    )
    parser.add_argument(
        "--dry_sync",
        dest="dry_sync",
        action="store_true",
        help="Don't apply modification when sync_to.",
    )
    parser.add_argument(
        "--sync_with_submodule",
        dest="sync_with_submodule",
        action="store_true",
        help="Remote directory use submodule to sync.",
    )
    args = parser.parse_args()
    return args


def main():
    # repo = Repo(root_path)
    # lst_repo = get_all_repo()
    config = get_config()

    if config.generate_only_generate_config:
        print("Generate config file locally.")
        gt = GitTool()
        gt.generate_generate_config()
        return

    if config.sync_to:
        if config.sync_to[-1] != "/":
            config.sync_to += "/"
        gt = GitTool()
        result = gt.get_matching_repo(
            repo_compare_to=config.sync_to,
            force_normalize_compare=True,
            sync_with_submodule=config.sync_with_submodule,
        )
        gt.sync_to(result, checkout_when_diff=not config.dry_sync)
        return

    # repo_root = Repo(".")
    lst_repo = GitTool.get_repo_info(repo_path=config.dir)
    i = 0
    total = len(lst_repo)
    for repo in lst_repo:
        i += 1
        print(f"Nb element {i}/{total}")
        url = repo.get("url")
        repo_dir_root = repo.get("path")
        upstream_name = "MathBenTech"
        organization_name = "ERPLibre"

        if config.open_web_browser:
            GitTool.open_repo_web_browser(repo.get("url_https"))

        # Create the remote upstream
        split_url = url.split("/")
        split_url[-2] = upstream_name
        upstream_url = "/".join(split_url)

        cloned_repo = Repo(repo_dir_root)
        # Checkout branch 12.0
        # try:
        #     cloned_repo.git.checkout(cloned_repo.head.commit.hexsha)
        #     cloned_repo.delete_head("12.0")
        #     cloned_repo.git.checkout("MathBenTech/12.0", b="12.0", force=True)
        # except:
        #     # cloned_repo.git.checkout("MathBenTech/12.0", b="12.0", force=True)
        #     print(f"Cannot change branch for {repo_dir_root}")
        #     # try:
        #     #     cloned_repo.git.checkout("12.0")
        #     # except:
        #     #     print(f"ERROR, missing branch 12.0 for {repo_dir_root}")

        _logger.info(
            f"Fork {url} on dir {repo_dir_root} for organization"
            f" {organization_name}"
        )

        try:
            upstream_remote = cloned_repo.remote(upstream_name)
            print(
                'Remote "%s" already exists in %s'
                % (upstream_name, repo_dir_root)
            )
        except ValueError:
            upstream_remote = retry(
                wait_exponential_multiplier=1000, stop_max_delay=15000
            )(cloned_repo.create_remote)(upstream_name, upstream_url)
            print('Remote "%s" created for %s' % (upstream_name, upstream_url))

        try:
            # Fetch the remote upstream
            retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
                upstream_remote.fetch
            )()
            print('Remote "%s" fetched' % upstream_name)
        except Exception:
            print(
                f"ERROR git {repo_dir_root} remote {upstream_name} not exist."
            )
            upstream_remote.remove(cloned_repo, upstream_name)


if __name__ == "__main__":
    main()
