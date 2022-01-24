from __future__ import print_function

import argparse
import os.path
import shutil

import yaml  # pip install PyYAML
from agithub.GitHub import GitHub  # pip install agithub
from git import Repo  # pip install gitpython
from giturlparse import parse  # pip install giturlparse
from retrying import retry  # pip install retrying

DEFAULT_CONFIG_FILENAME = "~/.github/fork_github_repo.yaml"


def github_url_argument(url):
    """Validate a url as a GitHub repo url and raise argparse exceptions if
    validation fails

    :param str url: A GitHub repo URL
    :return: The GitHub repo URL passed in
    """
    parsed_url = parse(url)
    if not parsed_url.valid:
        raise argparse.ArgumentTypeError("%s is not a valid git URL" % url)
    if not parsed_url.github:
        raise argparse.ArgumentTypeError(
            "%s is not a GitHub repo" % parsed_url.url
        )
    return url


def filename_argument(filename):
    return os.path.expanduser(filename)


def get_config():
    """Parse command line arguments, extracting the config file name,
    read the yaml config file and add in the command line arguments,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
Fork a GitHub repo, clone that repo to a local directory, add the upstream
remote, create an optional feature branch and checkout that branch""",
        epilog="""\
The config file with a default location of
~/.github/fork_github_repo.yaml contains the following settings:

-  github_token : The `GitHub personal access token with the public_repo scope
   allowed.
   https://help.github.com/articles/creating-a-personal-access-token-for-the-command-line/
-  repo_dir : The directory path to the directory containing all your cloned
    repos. If this isn't defined, /tmp is used.

The file is YAML formatted and the contents look like this :

github_token: 0123456789abcdef0123456789abcdef01234567
repo_dir: ~/Documents/github.com/example/
organization:
""",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="Filename of the yaml config file (default : %s)"
        % DEFAULT_CONFIG_FILENAME,
        default=filename_argument(DEFAULT_CONFIG_FILENAME),
        type=filename_argument,
    )
    parser.add_argument(
        "url",
        help="GitHub URL of the upstream repo to fork",
        type=github_url_argument,
    )
    parser.add_argument(
        "branch",
        nargs="?",
        default=None,
        help="Name of the feature branch to create",
    )
    args = parser.parse_args()
    if (args.config == filename_argument(DEFAULT_CONFIG_FILENAME)) and (
        not os.path.isfile(args.config)
    ):
        parser.error(
            "Please create a config file at %s or point to one with "
            "the --config option." % DEFAULT_CONFIG_FILENAME
        )
    if not os.path.isfile(args.config):
        raise argparse.ArgumentTypeError(
            "Could not find config file %s." % args.config
        )
    with open(args.config, "r") as f:
        try:
            config = yaml.safe_load(f)
            if isinstance(config, dict):
                config.update(vars(args))
                return config
            else:
                raise argparse.ArgumentTypeError(
                    'Config contains %s of "%s" but it should be a dict'
                    % (type(config), config)
                )
        except yaml.YAMLError:
            raise argparse.ArgumentTypeError(
                "Could not parse YAML in %s" % args.config
            )


def get_list_fork_repo(upstream_url, github_token):
    gh = GitHub(token=github_token)
    parsed_url = parse(upstream_url)
    status, user = gh.user.get()

    # response = gh.repos[user['login']][parsed_url.repo].forks.get(sort="newest")
    response = gh.repos["odoo"][parsed_url.repo].forks.get(sort="newest")
    print(response)


def fork_and_clone_repo(
    upstream_url,
    github_token,
    repo_dir_root,
    branch_name=None,
    upstream_name="upstream",
    organization_name=None,
    fork_only=False,
    repo_root=None,
):
    """Fork a GitHub repo, clone that repo to a local directory,
    add the upstream remote, create an optional feature branch and checkout
    that branch

    :param str upstream_url: GitHub URL of the upstream repo
    :param str github_token: GitHub auth token
    :param str repo_dir_root: The local directory path under which clones
    should be written
    :param str branch_name: The name of the git feature branch to create
    :param str upstream_name: The name to use for the remote upstream
    :param str organization_name: The name the organization that replace actual user
    :param bool fork_only: Stop after forking and don't clone
    :param obj repo_root: Repo parent, if not None, use submodule with it
    :return: github3.Head object representing the new feature branch
    """
    # Scope needed is `public_repo` to fork and clone public repos
    # https://developer.github.com/apps/building-integrations/setting-up-and-registering-oauth-apps/about-scopes-for-oauth-apps/
    gh = GitHub(token=github_token)
    parsed_url = parse(upstream_url)

    # Fork the repo
    status, user = gh.user.get()
    user_name = user["login"] if not organization_name else organization_name
    status, forked_repo = gh.repos[user_name][parsed_url.repo].get()
    if status == 404:
        status, upstream_repo = gh.repos[parsed_url.owner][
            parsed_url.repo
        ].get()
        if status == 404:
            print("Unable to find repo %s" % upstream_url)
            exit(1)
        args = {}
        if organization_name:
            args["organization"] = organization_name
        status, forked_repo = gh.repos[parsed_url.owner][
            parsed_url.repo
        ].forks.post(**args)
        if status == 404:
            print("Error when forking repo %s" % forked_repo)
            exit(1)
        else:
            print("Forked %s to %s" % (upstream_url, forked_repo["html_url"]))
    elif status == 202:
        print("Forked repo %s already exists" % forked_repo["full_name"])
    elif status != 200:
        print("Status not supported: %s - %s" % (status, forked_repo))
        exit(1)

    if fork_only:
        return True

    # Clone the repo
    repo_dir = os.path.expanduser(os.path.join(repo_dir_root, parsed_url.repo))
    if repo_root:
        # TODO validate not already submodule
        # forked_repo['ssh_url']
        http_url = f"https://{(forked_repo['ssh_url'][4:]).replace(':', '/')}"
        try:
            if branch_name:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000, stop_max_delay=15000
                )(repo_root.create_submodule)(
                    repo_dir_root,
                    repo_dir_root,
                    url=http_url,
                    branch=branch_name,
                )
            else:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000, stop_max_delay=15000
                )(repo_root.create_submodule)(
                    repo_dir_root, repo_dir_root, url=http_url
                )
        except KeyError as e:
            if os.path.isdir(repo_dir_root):
                print(
                    f"Warning, submodule {repo_dir_root} already exist, "
                    "you need to add it in stage."
                )
            else:
                print(
                    f"\nERROR Cannot create submodule {repo_dir_root}."
                    f"Maybe you need to delete .git/modules/{repo_dir_root}\n"
                )
                return
                # # Delete appropriate submodule and recreate_submodule
                # shutil.rmtree(f".git/modules/{repo_dir_root}", ignore_errors=True)
                # if branch_name:
                #     submodule_repo = retry(
                #         wait_exponential_multiplier=1000,
                #         stop_max_delay=15000
                #     )(repo_root.create_submodule)(repo_dir_root, repo_dir_root,
                #                                   url=http_url,
                #                                   branch=branch_name)
                # else:
                #     submodule_repo = retry(
                #         wait_exponential_multiplier=1000,
                #         stop_max_delay=15000
                #     )(repo_root.create_submodule)(repo_dir_root, repo_dir_root,
                #                                   url=http_url)
                # Update submodule
                # print(f"Try to fix submodule {repo_dir_root} with update them all.")
                # retry(
                #     wait_exponential_multiplier=1000,
                #     stop_max_delay=15000
                # )(repo_root.submodule_update)(recursive=False)
                # if os.path.isdir(repo_dir_root):
                #     print(f"Submodule {repo_dir_root} fixed.")
                # else:
                #     # TODO remove submodule
                #     print(f"Error, submodule {repo_dir_root} is configured, but not "
                #           f"existing. Do git submodule update")

        cloned_repo = Repo(repo_dir_root)
        print("Cloned %s to %s" % (http_url, repo_dir))
        # sm = cloned_repo.create_submodule('mysubrepo', 'path/to/subrepo',
        #                                   url=bare_repo.git_dir, branch='master')
    else:
        if os.path.isdir(repo_dir):
            print(
                "Directory %s already exists, assuming it's a clone" % repo_dir
            )
            cloned_repo = Repo(repo_dir)
        else:
            cloned_repo = retry(
                wait_exponential_multiplier=1000, stop_max_delay=15000
            )(Repo.clone_from)(forked_repo["ssh_url"], repo_dir)
            print("Cloned %s to %s" % (forked_repo["ssh_url"], repo_dir))

    # Create the remote upstream
    try:
        upstream_remote = cloned_repo.remote(upstream_name)
        print('Remote "%s" already exists in %s' % (upstream_name, repo_dir))
    except ValueError:
        upstream_remote = retry(
            wait_exponential_multiplier=1000, stop_max_delay=15000
        )(cloned_repo.create_remote)(upstream_name, upstream_url)
        print('Remote "%s" created for %s' % (upstream_name, upstream_url))

    # Fetch the remote upstream
    retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
        upstream_remote.fetch
    )()
    print('Remote "%s" fetched' % upstream_name)

    # Create and checkout the branch
    if branch_name is None:
        return cloned_repo
    else:
        if branch_name not in cloned_repo.refs:
            branch = cloned_repo.create_head(branch_name)
            print('Branch "%s" created' % branch_name)
        else:
            branch = cloned_repo.heads[branch_name]
            print('Branch "%s" already exists' % branch_name)
        if branch_name not in cloned_repo.remotes.origin.refs:
            cloned_repo.remotes.origin.push(
                refspec="{}:{}".format(branch.path, branch.path)
            )
            print('Branch "%s" pushed to origin' % branch_name)
        else:
            print('Branch "%s" already exists in remote origin' % branch_name)
        if branch.tracking_branch() is None:
            branch.set_tracking_branch(
                cloned_repo.remotes.origin.refs[branch_name]
            )
            print(
                'Tracking branch "%s" setup for branch "%s"'
                % (cloned_repo.remotes.origin.refs[branch_name], branch_name)
            )
        else:
            print(
                'Branch "%s" already setup to track "%s"'
                % (branch_name, cloned_repo.remotes.origin.refs[branch_name])
            )
        branch.checkout()
        print('Branch "%s" checked out' % branch_name)
        return branch
