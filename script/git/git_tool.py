#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import pathlib
import webbrowser
from collections import OrderedDict
from typing import List

import git
import xmltodict
from agithub.GitHub import GitHub  # pip install agithub
from colorama import Fore, Style
from git import Repo
from giturlparse import parse  # pip install giturlparse
from retrying import retry  # pip install retrying

SOURCE_REPO_ADDONS_FILE = "source_repo_addons.csv"
EL_GITHUB_TOKEN = "EL_GITHUB_TOKEN"
DEFAULT_PROJECT_NAME = "ERPLibre"
DEFAULT_WEBSITE = "erplibre.ca"
DEFAULT_REMOTE_URL = "https://github.com/ERPLibre/ERPLibre.git"


class RepoAttrs(object):
    def __init__(self, **entries):
        self.__dict__.update(entries)


class GitTool:
    @property
    def default_project_name(self):
        return DEFAULT_PROJECT_NAME

    @property
    def default_website(self):
        return DEFAULT_WEBSITE

    @property
    def default_remote_url(self):
        return DEFAULT_REMOTE_URL

    @property
    def default_branch(self):
        return self.odoo_version

    @property
    def odoo_version(self):
        with open(".odoo-version", "r") as f:
            default_branch = f.readline()
        return default_branch

    @property
    def odoo_version_long(self):
        return f"odoo{self.odoo_version}"

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

    def get_transformed_repo_info_from_url(
        self,
        url: str,
        repo_path: str = ".",
        get_obj: bool = True,
        is_submodule: bool = True,
        organization_force: str = None,
        sub_path: str = "addons",
        revision: str = "",
        clone_depth: str = "",
    ) -> object:
        """

        :param url:
        :param repo_path:
        :param get_obj:
        :param is_submodule:
        :param organization_force: Keep repo_path and change organization
        :param sub_path:
        :param revision: Tag or branch name. When empty, use default branch.
        :param clone_depth: length of git history to clone. Clone all git when empty.
        Set to 0 to increase speed to clone, set to empty for development.
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
                path = repo_name
            else:
                path = os.path.join(sub_path, f"{organization}_{repo_name}")
        else:
            path = repo_path
        relative_path = os.path.join(repo_path, path)
        # if repo_path[-1] == "/":
        #     relative_path = f"{repo_path}{path}"
        # else:
        #     relative_path = f"{repo_path}/{path}"
        relative_path = os.path.normpath(relative_path)

        original_organization = organization
        url_https_original_organization = url_https[: url_https.rfind("/")]
        project_name = url_https[url_https.rfind("/") + 1 :]
        #     begin_original = url_git[url_git.find(":") + 1:]
        #     original_organization = begin_original[:begin_original.find("/")]
        if organization_force:
            organization = organization_force
            url_split = url_https.split("/")
            url_split[3] = organization
            url_https = "/".join(url_split)
            url, _, url_git = self.get_url(url_https)
        url_https_organization = url_https[: url_https.rfind("/")]

        repo_data = {
            "url": url,
            "url_git": url_git,
            "url_https": url_https,
            "organization": organization,
            "original_organization": original_organization,
            "url_https_organization": url_https_organization,
            "url_https_original_organization": url_https_original_organization,
            "project_name": project_name,
            "revision": revision,
            "clone_depth": clone_depth,
            "repo_name": repo_name,
            "path": path,
            "relative_path": relative_path,
            "is_submodule": is_submodule,
            "sub_path": sub_path,
        }
        if get_obj:
            return RepoAttrs(**repo_data)
        return repo_data

    def get_repo_info(
        self,
        repo_path: str = ".",
        add_root: bool = False,
        is_manifest: bool = True,
        filter_group=None,
    ):
        if is_manifest:
            return self.get_repo_info_manifest_xml(
                repo_path=repo_path,
                add_root=add_root,
                filter_group=filter_group,
            )
        return self.get_repo_info_submodule(
            repo_path=repo_path, add_root=add_root
        )

    def get_repo_info_submodule(
        self, repo_path: str = ".", add_root: bool = False
    ) -> list:
        """
        Get information about submodule from repo_path
        :param repo_path: path of repo to get information about submodule
        :param add_root: add information about root repository
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
        filename = os.path.join(repo_path, ".gitmodules")
        repos = []
        with open(filename) as file:
            txt = file.readlines()

        name = ""
        url = ""
        line_number = 0
        first_execution = True
        for line in txt:
            line_number += 1
            if line[:12] == '[submodule "':
                if not first_execution:
                    data = {
                        "url": url,
                        "url_https": url_https,
                        "url_git": url_git,
                        "path": path,
                        "relative_path": os.path.join(repo_path, path),
                        "name": name,
                    }
                    repos.append(data)
                name = line[12:-3]
                first_execution = False
                continue
            elif line[:7] == "\turl = ":
                url = line[7:-1]
                url, url_https, url_git = self.get_url(url)
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
                "relative_path": os.path.join(repo_path, path),
                "name": name,
            }
            repos.append(data)

        if add_root:
            repo_root = Repo(repo_path)
            url = repo_root.git.remote("get-url", "origin")
            url, url_https, url_git = self.get_url(url)

            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": repo_path,
                "name": "",
            }
            repos.insert(0, data)
        # Sort
        repos = sorted(repos, key=lambda k: k.get("name"))
        return repos

    def get_repo_info_manifest_xml(
        self, repo_path: str = ".", add_root: bool = False, filter_group=None
    ) -> list:
        """
        Get information about manifest of Repo from repo_path
        :param repo_path: path of repo to get information about submodule
        :param add_root: add information about root repository
        :param filter_group: filter manifest by group if exist, separate by comma for multiple group
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
        filter_groups = filter_group.split(",") if filter_group else []
        manifest_file = self.get_manifest_file(repo_path=repo_path)
        if not manifest_file:
            return []
        if os.path.isabs(manifest_file):
            # This is a absolute path
            filename = manifest_file
        else:
            filename = os.path.normpath(os.path.join(repo_path, manifest_file))
        repos = []
        with open(filename) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string)
            manifest_data = xml_dict.get("manifest")
        if not manifest_data:
            return []
        if manifest_data.get("default"):
            default_remote = manifest_data.get("default").get("@remote")
        else:
            default_remote = None
        remotes = manifest_data.get("remote")
        if type(remotes) is dict:
            remotes = [remotes]
        projects = manifest_data.get("project")
        if type(projects) is dict:
            projects = [projects]
        remotes_by_name = {a.get("@name"): a.get("@fetch") for a in remotes}
        for project in projects:
            groups = project.get("@groups")
            project_groups = groups.split(",") if groups else []
            for group in project_groups:
                if filter_groups and group not in filter_groups:
                    continue
                else:
                    break
            else:
                continue

            # get name and remote .git
            path = project.get("@path")
            name = path
            url_prefix = remotes_by_name.get(project.get("@remote"))
            if not url_prefix:
                # get default remote
                url_prefix = remotes_by_name.get(default_remote)
            url = f"{url_prefix}{project.get('@name')}"
            url, url_https, url_git = self.get_url(url)
            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": path,
                "relative_path": os.path.join(repo_path, path),
                "name": name,
                "group": groups,
            }
            repos.append(data)

        if add_root:
            repo_root = Repo(repo_path)
            try:
                url = repo_root.git.remote("get-url", "origin")
            except Exception as e:
                print(
                    f"{Fore.YELLOW}WARNING{Style.RESET_ALL}: Missing origin"
                    f" remote, use default url {DEFAULT_REMOTE_URL}. Suggest"
                    " to add a remote origin: \n> git remote add origin"
                    f" {DEFAULT_REMOTE_URL}"
                )
                url = DEFAULT_REMOTE_URL
            url, url_https, url_git = self.get_url(url)

            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": repo_path,
                "name": "",
            }
            repos.insert(0, data)
        # Sort
        repos = sorted(repos, key=lambda k: k.get("name"))
        return repos

    def get_manifest_xml_info(
        self, repo_path: str = ".", filename=None, add_root: bool = False
    ) -> list:
        """
        Get contain of manifest
        :param repo_path: path of repo to get information about submodule
        :param filename: manifest filename. Default none, or use this instead use repo_path
        :param add_root: add information about root repository
        :return: dct_remote, dct_project, default_remote

        """
        if filename is None:
            manifest_file = self.get_manifest_file(repo_path=repo_path)
            filename = os.path.normpath(os.path.join(repo_path, manifest_file))
        with open(filename) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string)
            manifest_data = xml_dict.get("manifest")
        if not manifest_data:
            return {}, {}, None
        default_remote = manifest_data.get("default")
        remotes = manifest_data.get("remote")
        if type(remotes) is dict:
            remotes = [remotes]
        projects = manifest_data.get("project")
        if type(projects) is dict:
            projects = [projects]
        if remotes:
            remotes_by_name = {a.get("@name"): a for a in remotes}
        else:
            remotes_by_name = {}
        if projects:
            projects_by_name = {a.get("@name"): a for a in projects}
        else:
            projects_by_name = {}
        return remotes_by_name, projects_by_name, default_remote

    @staticmethod
    def get_project_config(repo_path="."):
        """
        Get information about configuration in env_var.sh
        :param repo_path: path of repo to get information env_var.sh
        :return:
        {
            EL_GITHUB_TOKEN: TOKEN,
        }
        """
        filename = os.path.join(repo_path, "env_var.sh")
        with open(filename) as file:
            txt = file.readlines()
        txt = [a[:-1] for a in txt if "=" in a]

        filter_keys = [EL_GITHUB_TOKEN]
        config = {}
        # Take filtered value and get bash string values
        for key in filter_keys:
            for line in txt:
                if key in line:
                    parts = line.split("=")
                    if len(parts) > 1:
                        config[EL_GITHUB_TOKEN] = line.split("=")[1][1:-1]
        return config

    @staticmethod
    def open_repo_web_browser(repo_info):
        url = repo_info.get("url_https")
        if url:
            webbrowser.open_new_tab(url)

    def generate_generate_config(
        self,
        repo_path=".",
        filter_group=None,
        extra_path=None,
        ignore_odoo_path=None,
        add_repos=None,
        whitelist=None,
    ):
        filename_locally = os.path.join(repo_path, "script/generate_config.sh")
        if not filter_group:
            filter_group = self.odoo_version_long
        all_repos = self.get_repo_info(
            repo_path=repo_path, filter_group=filter_group
        )
        if whitelist:
            repos = []
            for repo in all_repos:
                if (
                    repo.get("path") in whitelist
                    or repo.get("path") in add_repos
                ):
                    repos.append(repo)
        else:
            repos = all_repos
        results = []
        if not repos:
            print(
                f"{Fore.YELLOW}WARNING{Style.RESET_ALL}: List of repo is empty when write generate_config."
            )
        for repo in repos:
            update_repo = repo.get("path")
            # Exception, ignore addons/OCA_web and root
            if update_repo in ["addons/OCA_web", "odoo", "image_db"]:
                continue
            # groups = repo.get("group")
            # Use variable instead of hardcoded path
            if update_repo.startswith(
                os.path.join(self.odoo_version_long, "addons")
            ):
                lst_path = update_repo.split("/", 1)
                update_repo = f"${{EL_HOME_ODOO_PROJECT}}/" + lst_path[1]
                # str_repo = (
                #     f'    printf "${{EL_HOME}}/{update_repo}," >> '
                #     '"${EL_CONFIG_FILE}"\n'
                # )
                str_repo = (
                    f'    printf "{update_repo}," >> ' '"${EL_CONFIG_FILE}"\n'
                )
                # Ignore repo if not starting by addons
                # if update_repo.startswith("addons"):
                #     lst_result.append(str_repo)
                results.append(str_repo)
        if extra_path:
            for each_extra_path in extra_path.strip().split(","):
                str_repo = (
                    f'    printf "{each_extra_path}," >> '
                    '"${EL_CONFIG_FILE}"\n'
                )
                results.append(str_repo)
        with open(filename_locally) as file:
            all_lines = file.readlines()
        # search place to add/replace lines
        index = 0
        find_index = False
        index_find = 0
        for line in all_lines:
            if line.startswith('printf "addons_path = '):
                if ignore_odoo_path:
                    new_line = (
                        'printf "addons_path = " >> "${EL_CONFIG_FILE}"\n'
                    )
                else:
                    new_line = 'printf "addons_path = ${EL_HOME_ODOO}/addons,${EL_HOME_ODOO}/odoo/addons,${EL_HOME}/odoo${EL_ODOO_VERSION}/addons/addons," >> "${EL_CONFIG_FILE}"\n'

                all_lines[index] = new_line
            if (
                not find_index
                and 'if [[ ${EL_MINIMAL_ADDONS} = "False" ]]; then\n' == line
            ):
                index_find = index + 1
                for insert_line in results:
                    all_lines.insert(index_find, insert_line)
                    index_find += 1
                if not results:
                    all_lines.insert(index_find, '\tprintf ""\n')
                    index_find += 1
                find_index = True
                # Delete all next line until meet fi
            if find_index and "fi\n" == line:
                # slice it
                all_lines = all_lines[0:index_find] + all_lines[index:]
                break
            index += 1

        if not find_index:
            print(
                f"ERROR cannot regenerate file {filename_locally}, "
                "did you change the header?"
            )

        # create file
        with open(filename_locally, mode="w") as file:
            file.writelines(all_lines)

    @staticmethod
    def str_insert(source_str, insert_str, pos):
        return source_str[:pos] + insert_str + source_str[pos:]

    def generate_repo_manifest(
        self,
        repo_list: List[RepoAttrs] = [],
        output: str = "",
        remotes_config={},
        projects_config={},
        default_remote=None,
        keep_original=False,
        default_branch=None,
    ):
        """
        Generate repo manifest
        :param repo_list: optional, update manifest with list_repo
        :param output: filename to write output
        :param remotes_config: dict of remote information
        :param projects_config: dict of project information
        :param default_remote: dict of default remote
        :param keep_original: if True, can manage multiple organization with same name,
           but with different fetch url
        :param default_branch: default branch name
        :return:
        """
        remote_entries = []
        remote_names = []
        project_entries = []
        project_names = []
        default_entries = []

        # Fill with configuration
        for dct_value in remotes_config.values():
            remote_name = dct_value.get("@name")
            if remote_name not in remote_names:
                remote_entries.append(
                    OrderedDict(
                        [
                            ("@name", remote_name),
                            ("@fetch", dct_value.get("@fetch")),
                        ]
                    )
                )
                remote_names.append(remote_name)
        for dct_value in projects_config.values():
            lst_project_info = [
                ("@name", dct_value.get("@name")),
                ("@path", dct_value.get("@path")),
            ]
            if "@remote" in dct_value:
                lst_project_info.append(("@remote", dct_value.get("@remote")))
            if "@revision" in dct_value:
                lst_project_info.append(
                    ("@revision", dct_value.get("@revision"))
                )
            if "@clone-depth" in dct_value:
                lst_project_info.append(
                    ("@clone-depth", dct_value.get("@clone-depth"))
                )
            if "@groups" in dct_value:
                lst_project_info.append(("@groups", dct_value.get("@groups")))
            if "@upstream" in dct_value:
                lst_project_info.append(
                    ("@upstream", dct_value.get("@upstream"))
                )
            if "@dest-branch" in dct_value:
                lst_project_info.append(
                    ("@dest-branch", dct_value.get("@dest-branch"))
                )

            project_entries.append(OrderedDict(lst_project_info))
            project_names.append(dct_value.get("@name"))

        for repo in repo_list:
            if not repo.is_submodule:
                # Default
                if default_entries:
                    raise Exception(
                        "Cannot have many root repo. "
                        "Validate why 2 or more is not submodule."
                    )
                default_entries.append(
                    OrderedDict(
                        [
                            ("@remote", repo.original_organization),
                            ("@revision", default_branch),
                            ("@sync-j", "4"),
                            ("@sync-c", "true"),
                        ]
                    )
                )
            else:
                if (
                    keep_original
                    and repo.project_name not in projects_config
                ):
                    # Exception, create a new remote to keep tracking on original
                    original_organization = (
                        f"{repo.original_organization}_origin"
                    )
                else:
                    original_organization = repo.original_organization
                # Add remote, only unique remote
                if original_organization not in remote_names:
                    remote_entries.append(
                        OrderedDict(
                            [
                                ("@name", original_organization),
                                ("@fetch", repo.url_https_organization + "/"),
                            ]
                        )
                    )
                    remote_names.append(repo.original_organization)
                # Add project, only unique project
                if repo.project_name not in project_names:
                    project_names.append(repo.project_name)
                    lst_project_info = [
                        ("@name", repo.project_name),
                        ("@path", repo.path),
                        ("@remote", original_organization),
                    ]
                    if repo.revision:
                        lst_project_info.append(("@revision", repo.revision))
                    if repo.clone_depth:
                        lst_project_info.append(
                            ("@clone-depth", repo.clone_depth)
                        )
                    if repo.sub_path == "addons":
                        lst_project_info.append(("@groups", "addons"))
                    else:
                        lst_project_info.append(("@groups", "odoo"))
                    project_entries.append(OrderedDict(lst_project_info))

        if default_remote and not default_entries:
            default_entries.append(
                OrderedDict(
                    [
                        ("@remote", default_remote.get("@remote")),
                        ("@revision", default_branch),
                        ("@sync-j", "4"),
                        ("@sync-c", "true"),
                    ]
                )
            )

        # Order in alphabetic
        sorted_remotes = sorted(remote_entries, key=lambda key: key.get("@name"))
        sorted_defaults = sorted(
            default_entries, key=lambda key: key.get("@remote")
        )
        sorted_projects = sorted(
            project_entries, key=lambda key: key.get("@name") + key.get("@path")
        )

        manifest_dict = OrderedDict(
            [
                (
                    "manifest",
                    OrderedDict(
                        [
                            ("remote", sorted_remotes),
                            ("default", sorted_defaults),
                            ("project", sorted_projects),
                        ]
                    ),
                )
            ]
        )
        str_xml_text = xmltodict.unparse(manifest_dict, pretty=True)

        pos_insert = str_xml_text.rfind("</remote>")
        if pos_insert >= 0:
            pos_insert += len("</remote>")
            str_xml_text = self.str_insert(str_xml_text, "\n  ", pos_insert)

        pos_insert = str_xml_text.rfind("</default>")
        if pos_insert >= 0:
            pos_insert += len("</default>")
            str_xml_text = self.str_insert(str_xml_text, "\n  ", pos_insert)

        # pos_insert = str_xml_text.rfind("</project>")
        # if pos_insert:
        #     pos_insert += len("</project>")
        # str_xml_text = self.str_insert(str_xml_text, "\n  ", pos_insert)

        str_xml_text = str_xml_text.replace("></remote", "/")
        str_xml_text = str_xml_text.replace("></default", "/")
        str_xml_text = str_xml_text.replace("></project", "/")
        str_xml_text = str_xml_text.replace(
            'encoding="utf-8"', 'encoding="UTF-8"'
        )
        str_xml_text = str_xml_text.replace("\t", "  ")

        # create file
        output_dirname = os.path.dirname(output)
        if not os.path.exists(output_dirname):
            pathlib.Path(output_dirname).mkdir(parents=True, exist_ok=True)
        if output:
            with open(output, mode="w") as file:
                file.writelines(str_xml_text + "\n")
        else:
            print(str_xml_text + "\n")

    def generate_git_modules(
        self, repo_list: List[RepoAttrs], repo_path: str = "."
    ):
        modules = []
        for repo in repo_list:
            if repo.is_submodule:
                modules.append(
                    f'[submodule "{repo.path}"]\n'
                    f"\turl = {repo.url_https}\n"
                    f"\tpath = {repo.path}\n"
                )

        # create file
        with open(os.path.join(repo_path, ".gitmodules"), mode="w") as file:
            file.writelines(modules)

    def get_source_repo_addons(self, repo_path=".", add_repo_root=False):
        """
        Read file SOURCE_REPO_ADDONS_FILE and return structure of data
        :param repo_path: path to find file SOURCE_REPO_ADDONS_FILE
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
        file_name = os.path.join(repo_path, SOURCE_REPO_ADDONS_FILE)
        results = []
        if add_repo_root:
            # TODO what to do if origin not exist?
            repo = Repo(repo_path)
            url = [a for a in repo.remotes][0].url
            repo_info = self.get_transformed_repo_info_from_url(
                url, repo_path=repo_path, get_obj=False, is_submodule=False
            )
            results.append(repo_info)
        with open(file_name) as file:
            all_lines = file.readlines()
            if all_lines:
                # Validate first line is supported column
                expected_header = "url,path,revision,clone-depth\n"
                if all_lines[0] != expected_header:
                    raise Exception(
                        f"Not supported csv, please validate {file_name} "
                        f"with first line {expected_header}"
                    )
                # Ignore first line
                all_lines = all_lines[1:]

                # Be sure empty endline at the end of file
                if all_lines[-1][-1] != "\n":
                    all_lines[-1] = all_lines[-1] + "\n"

        for line in all_lines:
            # Separate information with path in tuple
            line = line.strip()
            if not line:
                continue
            line_split = line.split(",")
            if len(line_split) != 4:
                print(
                    f"{Fore.RED}Error{Style.RESET_ALL} with line {line},"
                    " suppose to have only 4 ','."
                )
                exit(1)
            url, path, revision, clone_depth = line_split
            # Validate url
            # If begin by http, need to finish by .git
            if len(url) > 5 and url[0:4] == "http" and url[-4:] != ".git":
                url = f"{url}.git"
            repo_info = self.get_transformed_repo_info_from_url(
                url,
                repo_path=repo_path,
                get_obj=False,
                sub_path=path,
                revision=revision,
                clone_depth=clone_depth,
            )
            results.append(repo_info)
        return results

    def get_manifest_file(self, repo_path: str = "."):
        """
        Find .repo and return default manifest file.
        :param repo_path: path to search .repo
        :return: manifest file used for Repo
        """
        file = os.path.join(
            repo_path, ".repo", "local_manifests", "erplibre_manifest.xml"
        )
        if os.path.exists(file):
            return file
        file = os.path.join(repo_path, ".repo/manifest.xml")
        if not os.path.exists(file):
            return ""
        with open(file) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string)
            manifest_filename = (
                xml_dict.get("manifest").get("include").get("@name")
            )
        return manifest_filename

    def get_matching_repo(
        self,
        actual_repo=".",
        repo_compare_to=".",
        force_normalize_compare=False,
        sync_with_submodule=False,
    ):
        """
        Compare repo with .gitmodules files
        :param actual_repo:
        :param repo_compare_to:
        :param force_normalize_compare: update name of compare repo
        :param sync_with_submodule: force use submodule with repo_compare_to
        :return: (list of matches, list of missing, list of more)
        """
        actual_repos = self.get_repo_info_manifest_xml(actual_repo)
        actual_by_name = {a.get("name"): a for a in actual_repos}

        actual_adapted = {
            key[key.find("_") + 1 :]: item
            for key, item in actual_by_name.items()
        }
        set_actual_repo = set(actual_adapted.keys())

        compare_repos = self.get_repo_info(
            repo_compare_to, is_manifest=not sync_with_submodule
        )
        if force_normalize_compare:
            for repo_info in compare_repos:
                url_https = repo_info.get("url_https")
                url_split = url_https.split("/")
                organization = url_split[3]
                repo_name = url_split[4]
                if repo_name[-4:] == ".git":
                    repo_name = repo_name[:-4]
                # name = f"addons/{organization}_{repo_name}"
                name = f"{repo_name}"
                repo_info["name"] = name

        compare_by_name = {
            a.get("name"): a for a in compare_repos
        }
        set_compare = set(compare_by_name.keys())

        same_names = set_actual_repo.intersection(set_compare)
        missing_names = set_compare.difference(set_actual_repo)
        extra_names = set_actual_repo.difference(set_compare)
        print(
            f"Has {len(same_names)} sames, "
            f"{len(missing_names)} missing, "
            f"{len(extra_names)} more."
        )

        matches = []
        for key in same_names:
            matches.append(
                (actual_adapted[key], compare_by_name[key])
            )

        return matches, missing_names, extra_names

    @staticmethod
    def sync_to(result, checkout_when_diff=False):
        compared_repos, missing_repos, extra_repos = result
        total = len(missing_repos)
        if total:
            print(f"\nList of missing : {total}")
            i = 0
            for info in missing_repos:
                i += 1
                print(f"Nb element {i}/{total}")
                print(f"Missing '{info}'")

        total = len(extra_repos)
        if total:
            print(f"\nList of over : {total}")
            i = 0
            for info in extra_repos:
                i += 1
                print(f"Nb element {i}/{total}")
                print(f"Missing '{info}'")

        total = len(compared_repos)
        print(f"\nList of normalize : {total}")
        same = []
        diffs = []
        i = 0
        for original, compare_to in compared_repos:
            i += 1
            print(f"Nb element {i}/{total}")
            repo_original = Repo(original.get("relative_path"))
            commit_original = repo_original.head.object.hexsha
            repo_compare = Repo(compare_to.get("relative_path"))
            commit_compare = repo_compare.head.object.hexsha
            if commit_original != commit_compare:
                print(
                    f"DIFF - {original.get('name')} - O {commit_original} - "
                    f"R {commit_compare}"
                )
                diffs.append((original, compare_to))
                if checkout_when_diff:
                    # Update all remote
                    for remote in repo_original.remotes:
                        retry(
                            wait_exponential_multiplier=1000,
                            stop_max_delay=15000,
                        )(remote.fetch)()
                    repo_original.git.checkout(commit_compare)
            else:
                print(f"SAME - {original.get('name')}")
                same.append((original, compare_to))
        print(f"finish same {len(same)}, diff {len(diffs)}")

    @staticmethod
    def add_and_fetch_remote(
        repo_info: RepoAttrs, root_repo: Repo = None, branch_name: str = ""
    ):
        """
        Deprecated function, not use anymore git submodule
        :param repo_info:
        :param root_repo:
        :param branch_name:
        :return:
        """
        try:
            working_repo = Repo(repo_info.relative_path)
            if repo_info.organization in [
                a.name for a in working_repo.remotes
            ]:
                print(
                    f'Remote "{repo_info.organization}" already exist '
                    f"in {repo_info.relative_path}"
                )
                return
        except git.NoSuchPathError:
            print(f"New repo {repo_info.relative_path}")
            if not root_repo:
                print(
                    f"Missing git repository to root for repo {repo_info.path}"
                )
                return
            if branch_name:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000, stop_max_delay=15000
                )(root_repo.create_submodule)(
                    repo_info.path,
                    repo_info.path,
                    url=repo_info.url_https,
                    branch=branch_name,
                )
            else:
                submodule_repo = retry(
                    wait_exponential_multiplier=1000, stop_max_delay=15000
                )(root_repo.create_submodule)(
                    repo_info.path, repo_info.path, url=repo_info.url_https
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
        retry(wait_exponential_multiplier=1000, stop_max_delay=15000)(
            upstream_remote.fetch
        )()
        print('Remote "%s" fetched' % repo_info.organization)

    def get_pull_request_repo(
        self, upstream_url: str, github_token: str, organization_name: str = ""
    ):
        """

        :param upstream_url:
        :param github_token:
        :param organization_name:
        :return: List of url if success, else False
        """
        gh = GitHub(token=github_token)
        parsed_url = parse(upstream_url)

        # Fork the repo
        status, user = gh.user.get()
        user_name = (
            user["login"] if not organization_name else organization_name
        )
        status, lst_pull = gh.repos[user_name][parsed_url.repo].pulls.get()
        if type(lst_pull) is dict:
            print(f"For url {upstream_url}, got {lst_pull.get('message')}")
            return False
        else:
            for pull in lst_pull:
                print(pull.get("html_url"))
        return lst_pull

    def fork_repo(
        self, upstream_url: str, github_token: str, organization_name: str = ""
    ):
        # https://developer.github.com/apps/building-integrations/setting-up-and-registering-oauth-apps/about-scopes-for-oauth-apps/
        gh = GitHub(token=github_token)
        parsed_url = parse(upstream_url)

        # Fork the repo
        status, user = gh.user.get()
        user_name = (
            user["login"] if not organization_name else organization_name
        )
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
                print(
                    f"{Fore.RED}Error{Style.RESET_ALL} when forking repo"
                    f" {forked_repo}"
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
            print("Forked repo %s already exists" % forked_repo["full_name"])
        elif status != 200:
            print("Status not supported: %s - %s" % (status, forked_repo))
            exit(1)
        return forked_repo
