#!./.venv/bin/python
# © 2020 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import os
import webbrowser
from collections import OrderedDict
from typing import List

import git
import xmltodict
from agithub.GitHub import GitHub  # pip install agithub
from git import Repo
from giturlparse import parse  # pip install giturlparse
from retrying import retry  # pip install retrying

CST_FILE_SOURCE_REPO_ADDONS = "source_repo_addons.csv"
CST_EL_GITHUB_TOKEN = "EL_GITHUB_TOKEN"
DEFAULT_PROJECT_NAME = "ERPLibre"
DEFAULT_WEBSITE = "erplibre.ca"
DEFAULT_REMOTE_URL = "https://github.com/ERPLibre/ERPLibre.git"
DEFAULT_BRANCH = "12.0"


class Struct(object):
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
        return DEFAULT_BRANCH

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
        repo_path: str = "./",
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

        d = {
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
            return Struct(**d)
        return d

    def get_repo_info(
        self,
        repo_path: str = "./",
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
        self, repo_path: str = "./", add_root: bool = False
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
            if line[:12] == '[submodule "':
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
                "relative_path": f"{repo_path}/{path}",
                "name": name,
            }
            lst_repo.append(data)

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
            lst_repo.insert(0, data)
        # Sort
        lst_repo = sorted(lst_repo, key=lambda k: k.get("name"))
        return lst_repo

    def get_repo_info_manifest_xml(
        self, repo_path: str = "./", add_root: bool = False, filter_group=None
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
        lst_filter_group = filter_group.split(",") if filter_group else []
        manifest_file = self.get_manifest_file(repo_path=repo_path)
        filename = f"{repo_path}{manifest_file}"
        lst_repo = []
        with open(filename) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string, dict_constructor=dict)
            dct_manifest = xml_dict.get("manifest")
        default_remote = dct_manifest.get("default").get("@remote")
        lst_remote = dct_manifest.get("remote")
        if type(lst_remote) is dict:
            lst_remote = [lst_remote]
        lst_project = dct_manifest.get("project")
        if type(lst_project) is dict:
            lst_project = [lst_project]
        dct_remote = {a.get("@name"): a.get("@fetch") for a in lst_remote}
        for project in lst_project:
            groups = project.get("@groups")
            lst_group = groups.split(",") if groups else []
            # Continue if lst_filter exist and group in filter
            for group in lst_group:
                if lst_filter_group and group not in lst_filter_group:
                    continue
                else:
                    break
            else:
                continue

            # get name and remote .git
            path = project.get("@path")
            name = path
            url_prefix = dct_remote.get(project.get("@remote"))
            if not url_prefix:
                # get default remote
                url_prefix = dct_remote.get(default_remote)
            url = f"{url_prefix}{project.get('@name')}"
            url, url_https, url_git = self.get_url(url)
            data = {
                "url": url,
                "url_https": url_https,
                "url_git": url_git,
                "path": path,
                "relative_path": f"{repo_path}/{path}",
                "name": name,
                "group": group,
            }
            lst_repo.append(data)

        if add_root:
            repo_root = Repo(repo_path)
            try:
                url = repo_root.git.remote("get-url", "origin")
            except Exception as e:
                print(
                    "WARNING: Missing origin remote, use default url "
                    f"{DEFAULT_REMOTE_URL}. Suggest to add a remote origin: \n"
                    f"> git remote add origin {DEFAULT_REMOTE_URL}"
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
            lst_repo.insert(0, data)
        # Sort
        lst_repo = sorted(lst_repo, key=lambda k: k.get("name"))
        return lst_repo

    def get_manifest_xml_info(
        self, repo_path: str = "./", filename=None, add_root: bool = False
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
            filename = f"{repo_path}/{manifest_file}"
        with open(filename) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string, dict_constructor=dict)
            dct_manifest = xml_dict.get("manifest")
        default_remote = dct_manifest.get("default")
        lst_remote = dct_manifest.get("remote")
        lst_project = dct_manifest.get("project")
        dct_remote = {a.get("@name"): a for a in lst_remote}
        dct_project = {a.get("@name"): a for a in lst_project}
        return dct_remote, dct_project, default_remote

    @staticmethod
    def get_project_config(repo_path="./"):
        """
        Get information about configuration in env_var.sh
        :param repo_path: path of repo to get information env_var.sh
        :return:
        {
            CST_EL_GITHUB_TOKEN: TOKEN,
        }
        """
        filename = f"{repo_path}env_var.sh"
        with open(filename) as file:
            txt = file.readlines()
        txt = [a[:-1] for a in txt if "=" in a]

        lst_filter = [CST_EL_GITHUB_TOKEN]
        dct_config = {}
        # Take filtered value and get bash string values
        for f in lst_filter:
            for v in txt:
                if f in v:
                    lst_v = v.split("=")
                    if len(lst_v) > 1:
                        dct_config[CST_EL_GITHUB_TOKEN] = v.split("=")[1][1:-1]
        return dct_config

    @staticmethod
    def open_repo_web_browser(dct_repo):
        url = dct_repo.get("url_https")
        if url:
            webbrowser.open_new_tab(url)

    def generate_generate_config(self, repo_path="./", filter_group=None):
        filename_locally = f"{repo_path}script/generate_config.sh"
        lst_repo = self.get_repo_info(
            repo_path=repo_path, filter_group=filter_group
        )
        lst_result = []
        for repo in lst_repo:
            # Exception, ignore addons/OCA_web and root
            if repo.get("path") in ["addons/OCA_web", "odoo", "image_db"]:
                continue
            str_repo = (
                f'    printf "${{EL_HOME}}/{repo.get("path")}," >> '
                "${EL_CONFIG_FILE}\n"
            )
            lst_result.append(str_repo)
        with open(filename_locally) as file:
            all_lines = file.readlines()
        # search place to add/replace lines
        index = 0
        find_index = False
        index_find = 0
        for line in all_lines:
            if (
                not find_index
                and 'if [[ ${EL_MINIMAL_ADDONS} = "False" ]]; then\n' == line
            ):
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
        lst_repo: List[Struct] = [],
        output: str = "",
        dct_remote={},
        dct_project={},
        default_remote=None,
        keep_original=False,
    ):
        """
        Generate repo manifest
        :param lst_repo: optional, update manifest with list_repo
        :param output: filename to write output
        :param dct_remote: dict of remote information
        :param dct_project: dict of project information
        :param default_remote: dict of default remote
        :param keep_original: if True, can manage multiple organization with same name,
           but with different fetch url
        :return:
        """
        if not output:
            raise Exception(
                "Cannot generate manifest with missing output filename."
            )
        lst_remote = []
        lst_remote_name = []
        lst_project = []
        lst_project_name = []
        lst_default = []

        # Fill with configuration
        for dct_value in dct_remote.values():
            lst_remote.append(
                OrderedDict(
                    [
                        ("@name", dct_value.get("@name")),
                        ("@fetch", dct_value.get("@fetch")),
                    ]
                )
            )
            lst_remote_name.append(dct_value.get("@name"))
        for dct_value in dct_project.values():
            lst_project_info = [
                ("@name", dct_value.get("@name")),
                ("@path", dct_value.get("@path")),
            ]
            if "@remote" in dct_value.keys():
                lst_project_info.append(("@remote", dct_value.get("@remote")))
            if "@revision" in dct_value.keys():
                lst_project_info.append(
                    ("@revision", dct_value.get("@revision"))
                )
            if "@clone-depth" in dct_value.keys():
                lst_project_info.append(
                    ("@clone-depth", dct_value.get("@clone-depth"))
                )
            if "@groups" in dct_value.keys():
                lst_project_info.append(("@groups", dct_value.get("@groups")))
            if "@upstream" in dct_value.keys():
                lst_project_info.append(
                    ("@upstream", dct_value.get("@upstream"))
                )
            if "@dest-branch" in dct_value.keys():
                lst_project_info.append(
                    ("@dest-branch", dct_value.get("@dest-branch"))
                )

            lst_project.append(OrderedDict(lst_project_info))
            lst_project_name.append(dct_value.get("@name"))

        for repo in lst_repo:
            if not repo.is_submodule:
                # Default
                if lst_default:
                    raise Exception(
                        "Cannot have many root repo. "
                        "Validate why 2 or more is not submodule."
                    )
                lst_default.append(
                    OrderedDict(
                        [
                            ("@remote", repo.original_organization),
                            ("@revision", DEFAULT_BRANCH),
                            ("@sync-j", "4"),
                            ("@sync-c", "true"),
                        ]
                    )
                )
            else:
                if (
                    keep_original
                    and repo.project_name not in dct_project.keys()
                ):
                    # Exception, create a new remote to keep tracking on original
                    original_organization = (
                        f"{repo.original_organization}_origin"
                    )
                else:
                    original_organization = repo.original_organization
                # Add remote, only unique remote
                if original_organization not in lst_remote_name:
                    lst_remote.append(
                        OrderedDict(
                            [
                                ("@name", original_organization),
                                ("@fetch", repo.url_https_organization + "/"),
                            ]
                        )
                    )
                    lst_remote_name.append(repo.original_organization)
                # Add project, only unique project
                if repo.project_name not in lst_project_name:
                    lst_project_name.append(repo.project_name)
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
                    lst_project.append(OrderedDict(lst_project_info))

        if default_remote and not lst_default:
            lst_default.append(
                OrderedDict(
                    [
                        ("@remote", default_remote.get("@remote")),
                        ("@revision", DEFAULT_BRANCH),
                        ("@sync-j", "4"),
                        ("@sync-c", "true"),
                    ]
                )
            )

        # Order in alphabetic
        lst_order_remote = sorted(lst_remote, key=lambda key: key.get("@name"))
        lst_order_default = sorted(
            lst_default, key=lambda key: key.get("@remote")
        )
        lst_order_project = sorted(
            lst_project, key=lambda key: key.get("@name")
        )

        dct_repo = OrderedDict(
            [
                (
                    "manifest",
                    OrderedDict(
                        [
                            ("remote", lst_order_remote),
                            ("default", lst_order_default),
                            ("project", lst_order_project),
                        ]
                    ),
                )
            ]
        )
        str_xml_text = xmltodict.unparse(dct_repo, pretty=True)

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
        with open(output, mode="w") as file:
            file.writelines(str_xml_text + "\n")

    def generate_git_modules(
        self, lst_repo: List[Struct], repo_path: str = "./"
    ):
        lst_modules = []
        for repo in lst_repo:
            if repo.is_submodule:
                lst_modules.append(
                    f'[submodule "{repo.path}"]\n'
                    f"\turl = {repo.url_https}\n"
                    f"\tpath = {repo.path}\n"
                )

        # create file
        with open(f"{repo_path}.gitmodules", mode="w") as file:
            file.writelines(lst_modules)

    def get_source_repo_addons(self, repo_path="./", add_repo_root=False):
        """
        Read file CST_FILE_SOURCE_REPO_ADDONS and return structure of data
        :param repo_path: path to find file CST_FILE_SOURCE_REPO_ADDONS
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
        file_name = f"{repo_path}{CST_FILE_SOURCE_REPO_ADDONS}"
        lst_result = []
        if add_repo_root:
            # TODO what to do if origin not exist?
            repo = Repo(repo_path)
            url = [a for a in repo.remotes][0].url
            repo_info = self.get_transformed_repo_info_from_url(
                url, repo_path=repo_path, get_obj=False, is_submodule=False
            )
            lst_result.append(repo_info)
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
                print(f"Error with line {line}, suppose to have only 4 ','.")
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
            lst_result.append(repo_info)
        return lst_result

    def get_manifest_file(self, repo_path: str = "./"):
        """
        Find .repo and return default manifest file.
        :param repo_path: path to search .repo
        :return: manifest file used for Repo
        """
        file = f"{repo_path}/.repo/manifest.xml"
        with open(file) as xml:
            xml_as_string = xml.read()
            xml_dict = xmltodict.parse(xml_as_string, dict_constructor=dict)
            manifest_filename = (
                xml_dict.get("manifest").get("include").get("@name")
            )
        return manifest_filename

    def get_matching_repo(
        self,
        actual_repo="./",
        repo_compare_to="./",
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
        lst_repo_info_actual = self.get_repo_info_manifest_xml(actual_repo)
        dct_repo_info_actual = {a.get("name"): a for a in lst_repo_info_actual}
        # set_actual = set(dct_repo_info_actual.keys())
        # set_actual_repo = set(
        #     [a[a.find("_") + 1:] for a in dct_repo_info_actual.keys()])

        dct_repo_info_actual_adapted = {
            key[key.find("_") + 1 :]: item
            for key, item in dct_repo_info_actual.items()
        }
        set_actual_repo = set(dct_repo_info_actual_adapted.keys())

        lst_repo_info_compare = self.get_repo_info(
            repo_compare_to, is_manifest=not sync_with_submodule
        )
        if force_normalize_compare:
            for repo_info in lst_repo_info_compare:
                url_https = repo_info.get("url_https")
                url_split = url_https.split("/")
                organization = url_split[3]
                repo_name = url_split[4]
                if repo_name[-4:] == ".git":
                    repo_name = repo_name[:-4]
                # name = f"addons/{organization}_{repo_name}"
                name = f"{repo_name}"
                repo_info["name"] = name

        dct_repo_info_compare = {
            a.get("name"): a for a in lst_repo_info_compare
        }
        set_compare = set(dct_repo_info_compare.keys())

        # TODO finish the match
        # lst_same_name = set_actual.intersection(set_compare)
        # lst_missing_name = set_compare.difference(set_actual)

        lst_same_name_normalize = set_actual_repo.intersection(set_compare)
        lst_missing_name_normalize = set_compare.difference(set_actual_repo)
        lst_over_name_normalize = set_actual_repo.difference(set_compare)
        print(
            f"Has {len(lst_same_name_normalize)} sames, "
            f"{len(lst_missing_name_normalize)} missing, "
            f"{len(lst_over_name_normalize)} more."
        )

        lst_match = []
        for key in lst_same_name_normalize:
            lst_match.append(
                (dct_repo_info_actual_adapted[key], dct_repo_info_compare[key])
            )

        return lst_match, lst_missing_name_normalize, lst_over_name_normalize

    @staticmethod
    def sync_to(result, checkout_when_diff=False):
        lst_compare_repo_info, lst_missing_info, lst_over_info = result
        total = len(lst_missing_info)
        if total:
            print(f"\nList of missing : {total}")
            i = 0
            for info in lst_missing_info:
                i += 1
                print(f"Nb element {i}/{total}")
                print(f"Missing '{info}'")

        total = len(lst_over_info)
        if total:
            print(f"\nList of over : {total}")
            i = 0
            for info in lst_over_info:
                i += 1
                print(f"Nb element {i}/{total}")
                print(f"Missing '{info}'")

        total = len(lst_compare_repo_info)
        print(f"\nList of normalize : {total}")
        lst_same = []
        lst_diff = []
        i = 0
        for original, compare_to in lst_compare_repo_info:
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
                lst_diff.append((original, compare_to))
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
                lst_same.append((original, compare_to))
        print(f"finish same {len(lst_same)}, diff {len(lst_diff)}")

    @staticmethod
    def add_and_fetch_remote(
        repo_info: Struct, root_repo: Repo = None, branch_name: str = ""
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
                print("Error when forking repo %s" % forked_repo)
                exit(1)
            else:
                print(
                    "Forked %s to %s" % (upstream_url, forked_repo["html_url"])
                )
        elif status == 202:
            print("Forked repo %s already exists" % forked_repo["full_name"])
        elif status != 200:
            print("Status not supported: %s - %s" % (status, forked_repo))
            exit(1)
        return forked_repo
