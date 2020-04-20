#!/usr/bin/env python
# © 2020 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import os
from . import addons_repo_origin
import webbrowser
from retrying import retry  # pip install retrying
from agithub.GitHub import GitHub  # pip install agithub
from giturlparse import parse  # pip install giturlparse

from git import Repo
import git
from typing import List

CST_FILE_SOURCE_REPO_ADDONS_ODOO = "source_repo_addons_odoo.csv"
CST_GITHUB_TOKEN = "GITHUB_TOKEN"


class Struct(object):
    def __init__(self, **entries):
        self.__dict__.update(entries)


class GitTool:
    @staticmethod
    def get_url(url: str) -> object:
        """
        Transform an url in git and https.
        :param url: The url to transform in https and git
        :return: (url, url_https, url_git)
        """
        if "https" in url:
            url_git = f"git@{url[8:].replace('/', ':', 1)}"
            url_https = url
        else:
            url_https = f"https://{(url[4:]).replace(':', '/')}"
            url_git = url

        return url, url_https, url_git

    def get_transformed_repo_info_from_url(self, url: str, repo_path: str = "./",
                                           get_obj: bool = True,
                                           is_submodule: bool = True,
                                           organization_force: str = None,
                                           sub_path: str = "addons") -> object:
        """

        :param url:
        :param repo_path:
        :param get_obj:
        :param is_submodule:
        :param path:
        :param organization_force: Keep repo_path and change organization
        :return:
        """
        _, url_https, url_git = self.get_url(url)
        url_split = url_https.split("/")
        organization = url_split[3]
        repo_name = url_split[4]
        if repo_name[-4:] == ".git":
            repo_name = repo_name[:-4]
        if is_submodule:
            if not sub_path or sub_path == ".":
                path = f"{repo_name}"
            else:
                path = f"{sub_path}/{organization}_{repo_name}"
        else:
            path = f"{repo_path}"
        if repo_path[-1] == "/":
            relative_path = f"{repo_path}{path}"
        else:
            relative_path = f"{repo_path}/{path}"
        relative_path = os.path.normpath(relative_path)

        if organization_force:
            organization = organization_force
            url_split = url_https.split("/")
            url_split[3] = organization
            url_https = "/".join(url_split)
            url, _, url_git = self.get_url(url_https)

        d = {
            "url": url,
            "url_git": url_git,
            "url_https": url_https,
            "organization": organization,
            "repo_name": repo_name,
            "path": path,
            "relative_path": relative_path,
            "is_submodule": is_submodule,
            "sub_path": sub_path,
        }
        if get_obj:
            return Struct(**d)
        return d

    @staticmethod
    def get_repo_info_submodule(repo_path: str = "./", add_root: bool = False,
                                upstream: str = "origin") -> list:
        """
        Get information about submodule from repo_path
        :param repo_path: path of repo to get information about submodule
        :param add_root: add information about root repository
        :param upstream: Use this upstream of root
        :return:
        [{
            "url": original_url,
            "url_https": url in https,
            "url_git": url in git,
            "path": path of the submodule
            "relative_path": relative path of the submodule
            "name": name of the submodule
        }]
        """
        filename = f"{repo_path}/.gitmodules"
        lst_repo = []
        with open(filename) as file:
            txt = file.readlines()

        name = ""
        url = ""
        no_line = 0
        first_execution = True
        for line in txt:
            no_line += 1
            if line[:12] == "[submodule \"":
                if not first_execution:
                    data = {
                        "url": url,
                        "url_https": url_https,
                        "url_git": url_git,
                        "path": path,
                        "relative_path": f"{repo_path}/{path}",
                        "name": name,
                    }
                    lst_repo.append(data)
                name = line[12:-3]
                first_execution = False
                continue
            elif line[:7] == "\turl = ":
                url = line[7:-1]
                if "https" in url:
                    url_git = f"git@{url[8:].replace('/', ':', 1)}"
                    url_https = url
                else:
                    url_https = f"https://{(url[4:]).replace(':', '/')}"
                    url_git = url
                continue
            elif line[:8] == "\tpath = ":
                path = line[8:-1]
            else:
                if not line.strip():
                    continue
                raise Exception(".gitmodules seems not correctly formatted.")

        if not first_execution:
            # Get last item
            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": path,
                "relative_path": f"{repo_path}/{path}",
                "name": name,
            }
            lst_repo.append(data)

        if add_root:
            repo_root = Repo(repo_path)
            url = repo_root.git.remote("get-url", "origin")
            if "https" in url:
                url_git = f"git@{url[8:].replace('/', ':', 1)}"
                url_https = url
            else:
                url_https = f"https://{(url[4:]).replace(':', '/')}"
                url_git = url

            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": repo_path,
                "name": "",
            }
            lst_repo.insert(0, data)
        # Sort
        lst_repo = sorted(lst_repo, key=lambda k: k.get("name"))
        return lst_repo

    @staticmethod
    def get_repo_info_from_data_structure(repo_path="./", ignore_odoo=False):
        """
        Deprecated, read file addons_repo_origin to obtains repo list.
        :return:
        [{
            "url": original_url,
            "url_https": url in https,
            "url_git": url in git,
            "path": path of the submodule
            "relative_path": relative path of the submodule
            "name": name of the submodule
        }]
        """
        dct_config = {
            "addons": addons_repo_origin.config_addons
        }
        if not ignore_odoo:
            dct_config[""] = addons_repo_origin.config
        result = []
        for c_path, dct_config in dct_config.items():
            for server, dct_organization in dct_config.items():
                for organization, lst_repo in dct_organization.items():
                    for repo in lst_repo:
                        url = f"https://{server}/{organization}/{repo}.git"
                        url_https = f"https://{server}/{organization}/{repo}.git"
                        url_git = f"git@{server}:{organization}/{repo}.git"
                        if not c_path:
                            path = f"{repo}"
                        else:
                            path = f"{c_path}/{organization}_{repo}"

                        name = path
                        result.append(
                            {
                                "url": url,
                                "url_https": url_https,
                                "url_git": url_git,
                                "relative_path": f"{repo_path}/{path}",
                                "path": path,
                                "name": name,
                            }
                        )
        return result

    @staticmethod
    def get_project_config(repo_path="./"):
        """
        Get information about configuration in env_var.sh
        :param repo_path: path of repo to get information env_var.sh
        :return:
        {
            CST_GITHUB_TOKEN: TOKEN,
        }
        """
        filename = f"{repo_path}env_var.sh"
        with open(filename) as file:
            txt = file.readlines()
        txt = [a[:-1] for a in txt if "=" in a]

        lst_filter = [CST_GITHUB_TOKEN]
        dct_config = {}
        # Take filtered value and get bash string values
        for f in lst_filter:
            for v in txt:
                if f in v:
                    lst_v = v.split("=")
                    if len(lst_v) > 1:
                        dct_config[CST_GITHUB_TOKEN] = v.split("=")[1][1:-1]
        return dct_config

    @staticmethod
    def open_repo_web_browser(dct_repo):
        url = dct_repo.get("url_https")
        if url:
            webbrowser.open_new_tab(url)

    def generate_repo_source_from_building(self, repo_path="./"):
        """
        DEPRECATED
        Generate csv file with information about all source addons repo of Odoo
        :param repo_path: Path to build repo source
        :return:
        """
        file_name = f"{repo_path}{CST_FILE_SOURCE_REPO_ADDONS_ODOO}"
        lst_repo_info = self.get_repo_info_from_data_structure(ignore_odoo=True)
        lst_result = [f"{a.get('url_https')}\n" for a in lst_repo_info]
        with open(file_name, "w") as file:
            file.writelines(lst_result)

    def generate_odoo_install_locally(self, repo_path="./"):
        # lst_repo = self.get_repo_info_from_data_structure(ignore_odoo=True)
        lst_repo = self.get_repo_info_submodule(repo_path=repo_path)
        lst_result = []
        for repo in lst_repo:
            # Exception, ignore addons/OCA_web and root
            if "addons/OCA_web" == repo.get("path") or \
                    "odoo" == repo.get("path"):
                continue
            str_repo = f'    printf "${{OE_HOME}}/{repo.get("path")}," >> ' \
                       f'${{OE_CONFIG_FILE}}\n'
            lst_result.append(str_repo)
        with open(f"{repo_path}script/odoo_install_locally.sh") as file:
            all_lines = file.readlines()
        # search place to add/replace lines
        index = 0
        find_index = False
        index_find = 0
        for line in all_lines:
            if not find_index and "if [[ $MINIMAL_ADDONS = \"False\" ]]; then\n" == line:
                index_find = index + 1
                for insert_line in lst_result:
                    all_lines.insert(index_find, insert_line)
                    index_find += 1
                find_index = True
                # Delete all next line until meet fi
            if find_index and "fi\n" == line:
                # slice it
                all_lines = all_lines[0:index_find] + all_lines[index:]
                break
            index += 1

        # create file
        with open(f"{repo_path}script/odoo_install_locally.sh", mode="w") as file:
            file.writelines(all_lines)

    def generate_git_modules(self, lst_repo: List[Struct], repo_path: str = "./"):
        lst_modules = []
        for repo in lst_repo:
            if repo.is_submodule:
                lst_modules.append(f"[submodule \"{repo.path}\"]\n"
                                   f"\turl = {repo.url_https}\n"
                                   f"\tpath = {repo.path}\n")

        # create file
        with open(f"{repo_path}.gitmodules", mode="w") as file:
            file.writelines(lst_modules)

    def get_source_repo_addons(self, repo_path="./", add_repo_root=False):
        """
        Read file CST_FILE_SOURCE_REPO_ADDONS_ODOO and return structure of data
        :param repo_path: path to find file CST_FILE_SOURCE_REPO_ADDONS_ODOO
        :param add_repo_root: force adding repo root in the list
        :return:
        [{
            "url": original_url,
            "url_https": url in https,
            "url_git": url in git,
            "path": path of the submodule
            "relative_path": relative path of the submodule
            "name": name of the submodule
        }]
        """
        file_name = f"{repo_path}{CST_FILE_SOURCE_REPO_ADDONS_ODOO}"
        lst_result = []
        if add_repo_root:
            # TODO what to do if origin not exist?
            repo = Repo(repo_path)
            url = [a for a in repo.remotes][0].url
            repo_info = self.get_transformed_repo_info_from_url(url,
                                                                repo_path=repo_path,
                                                                get_obj=False,
                                                                is_submodule=False)
            lst_result.append(repo_info)
        with open(file_name) as file:
            all_lines = file.readlines()
            if all_lines:
                # Ignore first line
                all_lines = all_lines[1:]
        for line in all_lines:
            # Separate information with path in tuple
            line_split = line[:-1].split(',')
            if len(line_split) != 2:
                print(f"Error with line {line}, suppose to have only 1 ','.")
                exit(1)
            url, path = line_split
            repo_info = self.get_transformed_repo_info_from_url(url,
                                                                repo_path=repo_path,
                                                                get_obj=False,
                                                                sub_path=path)
            lst_result.append(repo_info)
        return lst_result

    def get_matching_repo(self, actual_repo="./", repo_compare_to="./",
                          force_normalize_compare=False):
        """
        Compare repo with .gitmodules files
        :param actual_repo:
        :param repo_compare_to:
        :param force_normalize_compare: update name of compare repo
        :return:
        """
        lst_repo_info_actual = self.get_repo_info_submodule(actual_repo)
        dct_repo_info_actual = {a.get("name"): a for a in lst_repo_info_actual}
        set_actual = set(dct_repo_info_actual.keys())
        # set_actual_repo = set(
        #     [a[a.find("_") + 1:] for a in dct_repo_info_actual.keys()])

        dct_repo_info_actual_adapted = {key[key.find("_") + 1:]: item for key, item in
                                        dct_repo_info_actual.items()}
        set_actual_repo = set(dct_repo_info_actual_adapted.keys())

        lst_repo_info_compare = self.get_repo_info_submodule(repo_compare_to)
        if force_normalize_compare:
            for repo_info in lst_repo_info_compare:
                url_https = repo_info.get("url_https")
                url_split = url_https.split("/")
                organization = url_split[3]
                repo_name = url_split[4][:-4]
                # name = f"addons/{organization}_{repo_name}"
                name = f"{repo_name}"
                repo_info["name"] = name

        dct_repo_info_compare = {a.get("name"): a for a in lst_repo_info_compare}
        set_compare = set(dct_repo_info_compare.keys())

        # TODO finish the match
        # lst_same_name = set_actual.intersection(set_compare)
        # lst_missing_name = set_compare.difference(set_actual)

        lst_same_name_normalize = set_actual_repo.intersection(set_compare)
        lst_missing_name_normalize = set_compare.difference(set_actual_repo)
        lst_over_name_normalize = set_actual_repo.difference(set_compare)
        print(f"Has {len(lst_same_name_normalize)} sames, "
              f"{len(lst_missing_name_normalize)} missing, "
              f"{len(lst_over_name_normalize)} more.")

        lst_match = []
        for key in lst_same_name_normalize:
            lst_match.append((
                dct_repo_info_actual_adapted[key],
                dct_repo_info_compare[key]
            ))

        return lst_match

    @staticmethod
    def sync_to(lst_compare_repo_info):
        i = 0
        total = len(lst_compare_repo_info)
        lst_same = []
        lst_diff = []
        for original, compare_to in lst_compare_repo_info:
            i += 1
            print(f"Nb element {i}/{total}")
            repo_original = Repo(original.get("relative_path"))
            commit_original = repo_original.head.object.hexsha
            repo_compare = Repo(compare_to.get("relative_path"))
            commit_compare = repo_compare.head.object.hexsha
            if commit_original != commit_compare:
                print(f"DIFF - {original.get('name')}")
                lst_diff.append((original, compare_to))
                repo_original.git.checkout(commit_compare)
            else:
                print(f"SAME - {original.get('name')}")
                lst_same.append((original, compare_to))
        print(f"finish same {len(lst_same)}, diff {len(lst_diff)}")

    @staticmethod
    def add_and_fetch_remote(repo_info: Struct, root_repo: Repo = None,
                             branch_name: str = ""):
        try:
            working_repo = Repo(repo_info.relative_path)
            if repo_info.organization in [a.name for a in working_repo.remotes]:
                print(f"Remote \"{repo_info.organization}\" already exist "
                      f"in {repo_info.relative_path}")
                return
        except git.NoSuchPathError:
            print(f"New repo {repo_info.relative_path}")
            if not root_repo:
                print(f"Missing git repository to root for repo {repo_info.path}")
                return
            if branch_name:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000,
                    stop_max_delay=15000
                )(root_repo.create_submodule)(repo_info.path, repo_info.path,
                                              url=repo_info.url_https,
                                              branch=branch_name)
            else:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000,
                    stop_max_delay=15000
                )(root_repo.create_submodule)(repo_info.path, repo_info.path,
                                              url=repo_info.url_https)
                return
        # Add remote
        upstream_remote = retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
            working_repo.create_remote)(repo_info.organization, repo_info.url_https)
        print('Remote "%s" created for %s' % (
            repo_info.organization, repo_info.url_https))

        # Fetch the remote
        retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
            upstream_remote.fetch)()
        print('Remote "%s" fetched' % repo_info.organization)

    def fork_repo(self, upstream_url: str, github_token: str,
                  organization_name: str = ""):
        # https://developer.github.com/apps/building-integrations/setting-up-and-registering-oauth-apps/about-scopes-for-oauth-apps/
        gh = GitHub(token=github_token)
        parsed_url = parse(upstream_url)

        # Fork the repo
        status, user = gh.user.get()
        user_name = user['login'] if not organization_name else organization_name
        status, forked_repo = gh.repos[user_name][parsed_url.repo].get()
        if status == 404:
            status, upstream_repo = (
                gh.repos[parsed_url.owner][parsed_url.repo].get())
            if status == 404:
                print("Unable to find repo %s" % upstream_url)
                exit(1)
            args = {}
            if organization_name:
                args["organization"] = organization_name
            status, forked_repo = (
                gh.repos[parsed_url.owner][parsed_url.repo].forks.post(**args))
            if status == 404:
                print("Error when forking repo %s" % forked_repo)
                exit(1)
            else:
                print("Forked %s to %s" % (upstream_url, forked_repo['ssh_url']))
        elif status == 202:
            print("Forked repo %s already exists" % forked_repo['full_name'])
        elif status != 200:
            print("Status not supported: %s - %s" % (status, forked_repo))
            exit(1)
        return forked_repo
