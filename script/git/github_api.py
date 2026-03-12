#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import git
from agithub.GitHub import GitHub
from colorama import Fore, Style
from git import Repo
from giturlparse import parse
from retrying import retry


def get_pull_request_repo(
    upstream_url: str,
    github_token: str,
    organization_name: str = "",
) -> list | bool:
    """
    Get pull requests for a repo.
    :param upstream_url: URL of the upstream repo
    :param github_token: GitHub API token
    :param organization_name: optional organization name
    :return: List of PRs if success, else False
    """
    gh = GitHub(token=github_token)
    parsed_url = parse(upstream_url)

    status, user = gh.user.get()
    user_name = (
        user["login"] if not organization_name else organization_name
    )
    status, lst_pull = (
        gh.repos[user_name][parsed_url.repo].pulls.get()
    )
    if type(lst_pull) is dict:
        print(
            f"For url {upstream_url},"
            f" got {lst_pull.get('message')}"
        )
        return False
    else:
        for pull in lst_pull:
            print(pull.get("html_url"))
    return lst_pull


def fork_repo(
    upstream_url: str,
    github_token: str,
    organization_name: str = "",
) -> None:
    gh = GitHub(token=github_token)
    parsed_url = parse(upstream_url)

    status, user = gh.user.get()
    user_name = (
        user["login"] if not organization_name else organization_name
    )
    status, forked_repo = (
        gh.repos[user_name][parsed_url.repo].get()
    )
    if status == 404:
        status, upstream_repo = (
            gh.repos[parsed_url.owner][parsed_url.repo].get()
        )
        if status == 404:
            print("Unable to find repo %s" % upstream_url)
            exit(1)
        args = {}
        if organization_name:
            args["organization"] = organization_name
        status, forked_repo = (
            gh.repos[parsed_url.owner][parsed_url.repo]
            .forks.post(**args)
        )
        if status == 404:
            print(
                f"{Fore.RED}Error{Style.RESET_ALL} when forking"
                f" repo {forked_repo}"
            )
            exit(1)
        else:
            try:
                print(
                    "Forked %s to %s"
                    % (upstream_url, forked_repo["html_url"])
                )
            except Exception as e:
                print(e)
                print(forked_repo)
                print(upstream_url)
    elif status == 202:
        print(
            "Forked repo %s already exists"
            % forked_repo["full_name"]
        )
    elif status != 200:
        print(
            "Status not supported: %s - %s"
            % (status, forked_repo)
        )
        exit(1)


def add_and_fetch_remote(
    repo_info, root_repo: Repo = None, branch_name: str = ""
) -> None:
    """
    Deprecated function, not use anymore git submodule
    """
    try:
        working_repo = Repo(repo_info.relative_path)
        if repo_info.organization in [
            a.name for a in working_repo.remotes
        ]:
            print(
                f'Remote "{repo_info.organization}" already exist'
                f" in {repo_info.relative_path}"
            )
            return
    except git.NoSuchPathError:
        print(f"New repo {repo_info.relative_path}")
        if not root_repo:
            print(
                "Missing git repository to root for repo"
                f" {repo_info.path}"
            )
            return
        if branch_name:
            submodule_repo = retry(
                wait_exponential_multiplier=1000,
                stop_max_delay=15000,
            )(root_repo.create_submodule)(
                repo_info.path,
                repo_info.path,
                url=repo_info.url_https,
                branch=branch_name,
            )
        else:
            submodule_repo = retry(
                wait_exponential_multiplier=1000,
                stop_max_delay=15000,
            )(root_repo.create_submodule)(
                repo_info.path,
                repo_info.path,
                url=repo_info.url_https,
            )
            return
    # Add remote
    upstream_remote = retry(
        wait_exponential_multiplier=1000, stop_max_delay=15000
    )(working_repo.create_remote)(
        repo_info.organization, repo_info.url_https
    )
    print(
        'Remote "%s" created for %s'
        % (repo_info.organization, repo_info.url_https)
    )

    # Fetch the remote
    retry(
        wait_exponential_multiplier=1000, stop_max_delay=15000
    )(upstream_remote.fetch)()
    print('Remote "%s" fetched' % repo_info.organization)
