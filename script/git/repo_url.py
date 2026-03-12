#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os


def get_url(url: str) -> tuple[str, str, str]:
    """
    Transform a url into git and https variants.
    :param url: The url to transform
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
    url: str,
    repo_path: str = ".",
    get_obj: bool = True,
    is_submodule: bool = True,
    organization_force: str | None = None,
    sub_path: str = "addons",
    revision: str = "",
    clone_depth: str = "",
    repo_attrs_class=None,
) -> object:
    """
    Transform a URL into a structured repo info dict or object.
    """
    _, url_https, url_git = get_url(url)
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
    relative_path = os.path.normpath(relative_path)

    original_organization = organization
    url_https_original_organization = url_https[: url_https.rfind("/")]
    project_name = url_https[url_https.rfind("/") + 1 :]
    if organization_force:
        organization = organization_force
        url_split = url_https.split("/")
        url_split[3] = organization
        url_https = "/".join(url_split)
        url, _, url_git = get_url(url_https)
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
    if get_obj and repo_attrs_class:
        return repo_attrs_class(**repo_data)
    return repo_data
