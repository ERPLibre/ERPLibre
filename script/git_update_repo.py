#!./.venv/bin/python
import argparse
import logging
import os
import sys

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
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    lst_repo = git_tool.get_source_repo_addons(
        repo_path=config.dir, add_repo_root=False
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

    i = 0
    total = len(lst_repo)
    for repo in lst_repo_organization:
        i += 1
        print(f"\nNb element {i}/{total} - {repo.path}")

        # TODO validate with default to ignore duplicate url, if same remote repo
        if not repo.is_submodule:
            continue
        upstream_name = f"ERPLibre_update_12/{git_tool.default_branch}"
        remote_branch_name = f"{upstream_name}/{git_tool.default_branch}"
        git_repo = Repo(repo.relative_path)
        # 1. Add remote if not exist
        try:
            upstream_remote = git_repo.remote(upstream_name)
            print(
                f'Remote "{upstream_name}" already exists in'
                f" {repo.relative_path}"
            )
        except ValueError:
            upstream_remote = retry(
                wait_exponential_multiplier=1000, stop_max_delay=15000
            )(git_repo.create_remote)(upstream_name, repo.url_https)
            print(
                'Remote "%s" created for %s' % (upstream_name, repo.url_https)
            )

        # 2. Fetch the remote source
        retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
            upstream_remote.fetch
        )()
        print('Remote "%s" fetched' % upstream_name)

        # 3. Rebase actual branch with new branch
        rev = repo.revision if repo.revision else git_tool.default_branch
        try:
            git_repo.git.checkout(rev)
        except:
            if repo.revision:
                rev = f"{repo.original_organization}/{repo.revision}"
            else:
                rev = f"{repo.original_organization}/{git_tool.default_branch}"

            git_repo.git.checkout("--track", rev)
        actual_commit = git_repo.git.rev_parse("HEAD")
        try:
            git_repo.git.rebase(remote_branch_name)
        except Exception as e:
            print(e, file=sys.stderr)
        new_commit = git_repo.git.rev_parse("HEAD")

        if actual_commit == new_commit:
            print("== No diff ==")
        else:
            print(f"== Old commit {actual_commit} - new commit {new_commit}")
            # push
            try:
                retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
                    git_repo.git.push
                )(repo.organization, rev)
            except:
                print(
                    "Cannot push, maybe need to push force or resolv rebase"
                    " conflict",
                    file=sys.stderr,
                )
                print(f"cd {repo.path}")
                print(f"git diff ERPLibre/v#.#.#..HEAD")
                print(f"git push --force {repo.organization} {rev}")
                print(f"cd -")


if __name__ == "__main__":
    main()
