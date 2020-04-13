#!/usr/bin/env python
import os
import sys
import webbrowser
import argparse
import logging
from git import Repo

from retrying import retry  # pip install retrying

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(new_path)

from script.git_tool import GitTool
from script import fork_github_repo

_logger = logging.getLogger(__name__)
CST_GITHUB_TOKEN = "GITHUB_TOKEN"


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''\
''',
        epilog='''\
'''
    )
    parser.add_argument('-d', '--dir', dest="dir", default="./",
                        help="Path of repo to change remote, including submodule.")
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    lst_repo = GitTool.get_repo_info_submodule(repo_path=config.dir)
    branch_search = "12.0"
    # repo = Repo(root_path)
    # repo_root = Repo(".")
    lst_result = []

    i = 0
    total = len(lst_repo)
    for repo in lst_repo:
        i += 1
        print(f"Nb element {i}/{total}")
        repo_dir_root = repo.get("path")
        remote_path = f"{config.dir}/{repo_dir_root}"
        repo_root = Repo(remote_path)
        repo_branch_search_sha = [a.object.hexsha for a in repo_root.branches if
                                  branch_search in a.name]
        if repo_branch_search_sha:
            repo_branch_search_sha = repo_branch_search_sha[0]
        else:
            print(f"Error, missing branch {branch_search} in {remote_path}")
            continue
        lst_result.append((remote_path, repo_root.head.commit.hexsha,
                           repo_root.head.commit.hexsha != repo_branch_search_sha))

        # print(repo_root)

        # # Create the remote upstream
        # split_url = url.split("/")
        # split_url[-2] = upstream_name
        # upstream_url = "/".join(split_url)
        #
        # cloned_repo = Repo(repo_dir_root)
        # try:
        #     upstream_remote = cloned_repo.remote(upstream_name)
        #     print('Remote "%s" already exists in %s' %
        #           (upstream_name, repo_dir_root))
        # except ValueError:
        #     upstream_remote = retry(
        #         wait_exponential_multiplier=1000,
        #         stop_max_delay=15000
        #     )(cloned_repo.create_remote)(upstream_name, upstream_url)
        #     print('Remote "%s" created for %s' % (upstream_name, upstream_url))
        #
        # try:
        #     # Fetch the remote upstream
        #     retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
        #         upstream_remote.fetch)()
        #     print('Remote "%s" fetched' % upstream_name)
        # except Exception:
        #     print(f"ERROR git {repo_dir_root} remote {upstream_name} not exist.")
        #     upstream_remote.remove(upstream_remote, upstream_name)

    i = 0
    i_len = len(lst_result)
    for path, hash, diff in lst_result:
        i += 1
        if diff:
            print(f"{i:02d}/{i_len} {diff} {path}\t{hash}")

    # lst_repo = GitTool.get_repo_info_from_data_structure()
    # for repo in lst_repo:
    #     repo_dir_root = repo.get("path")
    #     repo_root = Repo(remote_path)
    #     repo_root.git.checkout()


if __name__ == '__main__':
    main()
