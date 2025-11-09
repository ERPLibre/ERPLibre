#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import ast
import logging
import os
import re
import shutil
from collections import OrderedDict, defaultdict
from pathlib import Path

import iscompatible
import toml
from colorama import Fore, Style
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.version import Version

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Update pip dependency in Poetry, clear pyproject.toml, search all dependencies
        from requirements.txt, search conflict version and generate a new list.
        Launch Poetry installation.
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
        "-f",
        "--force",
        action="store_true",
        help="Force create new list of dependency, ignore poetry.lock.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="More information in execution, show stats.",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Don't apply change, only show warning.",
    )
    parser.add_argument(
        "--set_version_poetry",
        help="Force to change poetry version, default is from file './.poetry-version'.",
    )
    parser.add_argument(
        "--set_version_odoo",
        help="Force to change odoo version, default is from file './.odoo-version'.",
    )
    parser.add_argument(
        "--set_version_python",
        help="Force to change python version, default is from file './.python-odoo-version'.",
    )
    parser.add_argument(
        "--set_version_erplibre",
        help="Force to change erplibre version, default is from file './.erplibre-version'.",
    )
    args = parser.parse_args()
    if not args.set_version_poetry:
        with open("./.poetry-version", "r", encoding="utf-8") as fichier:
            args.set_version_poetry = fichier.read().strip()
    if not args.set_version_odoo:
        with open("./.odoo-version", "r", encoding="utf-8") as fichier:
            args.set_version_odoo = fichier.read().strip()
    if not args.set_version_python:
        with open("./.python-odoo-version", "r", encoding="utf-8") as fichier:
            args.set_version_python = fichier.read().strip()
    if not args.set_version_erplibre:
        with open("./.erplibre-version", "r", encoding="utf-8") as fichier:
            args.set_version_erplibre = fichier.read().strip()
    return args


def get_lst_requirements_txt(
    config, ignore_dir_startswith: list = None, force_add_item: list = None
):
    return get_file_from_glob(
        config,
        "requirements.[tT][xX][tT]",
        ignore_dir_startswith=ignore_dir_startswith,
        force_add_item=force_add_item,
    )


def get_lst_manifest_py(config, ignore_dir_startswith: list = None):
    return get_file_from_glob(
        config, "__manifest__.py", ignore_dir_startswith=ignore_dir_startswith
    )


def get_file_from_glob(
    config,
    glob_txt,
    ignore_dir_startswith: list = None,
    force_add_item: list = None,
):
    lst_v = []
    # TODO take all groups odoo##.# from manifest, will create a dependency
    # Hardcode logic from manifest
    lst_path = [
        Path(f"./odoo{config.set_version_odoo}/addons").rglob(glob_txt),
        Path(f"./odoo{config.set_version_odoo}/odoo").rglob(glob_txt),
    ]
    for gen_path in lst_path:
        for a in gen_path:
            a_dirname = os.path.dirname(a)
            if a_dirname.startswith(".repo/") or a_dirname.startswith(".venv"):
                continue
            if ignore_dir_startswith:
                ignore_it = False
                for item_ignore_dir in ignore_dir_startswith:
                    if a_dirname.startswith(item_ignore_dir):
                        ignore_it = True
                        break
                if ignore_it:
                    continue
            lst_v.append(a)
    if force_add_item:
        for item in force_add_item:
            lst_v.append(Path(item))
    return lst_v


def combine_requirements(config):
    """
    Search all module and version in all requirements.txt file in this project.
    For each version, check compatibility and show warning with provenance file
    Generate requirements.txt to "./.venv/build_dependency.txt"
    :param config:
    :return:
    """
    priority_filename_requirement = (
        f"requirement/requirements.{config.set_version_erplibre}.txt"
    )
    second_priority_filename_requirement = (
        f"odoo{config.set_version_odoo}/odoo/requirements.txt"
    )
    except_sign = ";"
    lst_sign = ("==", "!=", ">=", "<=", "<", ">", except_sign, "~=")
    lst_requirements = []
    lst_replace_special_sign = {}
    ignore_requirements = ["sys_platform == 'win32'", "python_version < '3.7'"]
    dct_requirements = defaultdict(set)
    lst_requirements_file = get_lst_requirements_txt(
        config,
        ignore_dir_startswith=["script/"],
        force_add_item=[priority_filename_requirement],
    )
    # lst_requirements_with_condition = set()
    # dct_special_condition = defaultdict(list)

    if not os.path.isfile(priority_filename_requirement):
        _logger.error(f"File {priority_filename_requirement} not found.")

    print(f"Find {len(lst_requirements_file)} requirements.txt files.")

    dct_requirements_module_filename = defaultdict(list)
    for requirements_filename in lst_requirements_file:
        with open(requirements_filename, "r") as f:
            for a in f.readlines():
                b = a.strip()
                if not b or b[0] == "#":
                    continue
                if " @ " in b:
                    # Support when requirement line is like "package @ git+https://URL"
                    b = b.split("@ ")[1]
                if "#" in b:
                    # remove comments at the end of module
                    b = b[: b.index("#")].strip()
                comment_depend = ""
                if except_sign in b:
                    # current_python_version = platform.python_version()
                    # current_platform = sys.platform
                    current_platform_2 = default_environment()
                    current_platform_2["python_version"] = ".".join(
                        config.set_version_python.split(".")[:2]
                    )
                    current_platform_2["python_full_version"] = (
                        config.set_version_python
                    )
                    current_platform_2["implementation_version"] = (
                        config.set_version_python
                    )
                    req = Requirement(b)
                    is_compatible = req.marker.evaluate(current_platform_2)
                    if not is_compatible:
                        continue
                    # this support python_version into comment_depend, check odoo/requirements.txt
                    # b, comment_depend = b.split(except_sign)
                    # b = b.strip()
                    # comment_depend = comment_depend.strip()
                    # print(comment_depend)
                    # Rewrite dependancy : module==version
                    b = req.name + str(req.specifier)

                # Regroup requirement
                for sign in lst_sign:
                    if sign in b:
                        # Exception, some time the sign ; can be first, just check
                        if (
                            sign != except_sign
                            and except_sign in b
                            and b.find(sign) > b.find(except_sign)
                        ):
                            module_name = b[: b.find(except_sign)]
                        else:
                            module_name = b[: b.find(sign)]
                        module_name = module_name.strip()
                        # Special condition for ";", ignore it
                        # if except_sign in b:
                        #     for ignore_string in ignore_requirements:
                        #         if ignore_string in b:
                        #             break
                        #     if ignore_string in b:
                        #         break
                        #     # lst_requirements_with_condition.add(module_name)
                        #     value = b[: b.find(except_sign)].strip()
                        #     # dct_special_condition[module_name].append(b)
                        # else:
                        #     value = b
                        value = b
                        dct_requirements[module_name].add(value)
                        filename = str(requirements_filename)
                        dct_requirements_module_filename[value].append(
                            filename
                        )
                        break
                else:
                    dct_requirements[b].add(b)
                    filename = str(requirements_filename)
                    dct_requirements_module_filename[b].append(filename)
                lst_requirements.append(b)

    dct_requirements = get_manifest_external_dependencies(
        config, dct_requirements, lst_sign
    )

    # Merge all requirement by insensitive
    dct_requirement_insensitive = {}
    copy_dct_requirements = dct_requirements.copy()
    dct_requirements = defaultdict(set)
    for req_name, set_info in copy_dct_requirements.items():
        lower_req_name = req_name.lower()
        associate_req_name = dct_requirement_insensitive.get(lower_req_name)
        if not associate_req_name:
            dct_requirement_insensitive[lower_req_name] = req_name
            dct_requirements[req_name] = set_info
        else:
            dct_requirements[associate_req_name] = set.union(
                dct_requirements[associate_req_name], set_info
            )

    dct_requirements_diff_version = {
        k: v for k, v in dct_requirements.items() if len(v) > 1
    }
    # dct_requirements_same_version = {k: v for k, v in dct_requirements.items() if
    #                                  len(v) == 1}
    if config.verbose:
        # TODO show total repo to compare lst requirements
        print(
            f"Total requirements.txt {len(lst_requirements_file)}, total"
            f" module {len(lst_requirements)}, unique module"
            f" {len(dct_requirements)}, module with different version"
            f" {len(dct_requirements_diff_version)}."
        )

    if dct_requirements_diff_version:
        # Validate compatibility
        for key, lst_requirement in dct_requirements_diff_version.items():
            result = None

            lst_version_requirement = []
            for requirement in lst_requirement:
                # if ".*" in requirement:
                #     requirement = requirement.replace(".*", "")
                if "~=" in requirement:
                    old_requirement = requirement
                    requirement = requirement.replace("~=", "==")
                    lst_replace_special_sign[requirement] = old_requirement

                requirement_begin = requirement.split(except_sign)[0]
                match = re.search(r"[=<>~!]{1,2}(.*)", requirement_begin)
                if not match:
                    # Ignore empty version
                    continue
                match_version = match.group(1).strip()
                if ".*" in match_version:
                    match_version = match_version.replace(".*", "")
                match_sign = match.group(0).strip()[: -len(match_version)]
                match_app_name = requirement[
                    : -(len(match_sign) + len(match_version))
                ]
                match_version_format = match_version.replace("'", "").replace(
                    '"', ""
                )
                result_number = [(match_sign, Version(match_version_format))]
                # result_number = iscompatible.parse_requirements(requirement)
                if not result_number:
                    continue
                lst_version_requirement.append((requirement, result_number))
            # Check compatibility with all possibility
            is_compatible = True
            if len(lst_version_requirement) > 1:
                highest_value = sorted(
                    lst_version_requirement, key=lambda tup: tup[1][0][1]
                )[-1]
                for version_requirement in lst_version_requirement:
                    # TODO support me in iscompatible lib
                    # check after ., because b can appear in number
                    # v_r_split = version_requirement[0].split(".", 1)
                    # if len(v_r_split) > 1 and "b" in v_r_split[1]:
                    #     version_requirement_upd = version_requirement[0][
                    #         : version_requirement[0].rindex("b")
                    #     ]
                    # else:
                    #     version_requirement_upd = version_requirement[0]
                    version_requirement_upd = version_requirement[0]
                    if ".*" in version_requirement_upd:
                        version_requirement_upd = (
                            version_requirement_upd.replace(".*", "")
                        )
                    try:
                        is_compatible &= iscompatible.iscompatible(
                            version_requirement_upd, highest_value[1][0][1]
                        )
                    except Exception as e:
                        _logger.error(e)
                        is_compatible &= iscompatible.iscompatible(
                            version_requirement_upd, highest_value[1][0][1]
                        )
                if is_compatible:
                    result = highest_value[0]
                else:
                    # Find the requirements file and print the conflict
                    # Take the version from Odoo by default, else take the more recent
                    odoo_value = None
                    erplibre_value = None
                    for version_requirement in lst_version_requirement:
                        key_require = version_requirement[0]
                        if key_require in lst_replace_special_sign.keys():
                            key_require = lst_replace_special_sign.get(
                                key_require
                            )
                        filename_1 = dct_requirements_module_filename.get(
                            key_require
                        )
                        if not filename_1:
                            _logger.error(
                                f"Cannot find key '{key_require}' into list of requirements."
                            )
                        else:
                            if priority_filename_requirement in filename_1:
                                erplibre_value = version_requirement[0]
                            elif (
                                second_priority_filename_requirement
                                in filename_1
                            ):
                                odoo_value = version_requirement[0]

                    if erplibre_value:
                        str_result_choose = (
                            f"Select {erplibre_value} because from ERPLibre"
                        )
                        result = erplibre_value
                    elif odoo_value:
                        str_result_choose = (
                            f"Select {odoo_value} because from Odoo"
                        )
                        result = odoo_value
                    else:
                        result = highest_value[0]
                        str_result_choose = f"Select highest value {result}"
                    str_versions = " VS ".join(
                        [
                            f"{a[0]} from"
                            f" {dct_requirements_module_filename.get(a[0])}"
                            for a in lst_version_requirement
                        ]
                    )
                    print(
                        f"{Fore.YELLOW}WARNING{Style.RESET_ALL} - Not"
                        f" compatible {str_versions} - {str_result_choose}."
                    )
            elif len(lst_version_requirement) == 1:
                result = lst_version_requirement[0][0]
            else:
                result = key

            if result:
                dct_requirements[key] = {result}
            else:
                print(f"Internal error, missing result for {lst_requirement}.")

    # Support ignored requirements
    lst_ignore = get_list_ignored()
    lst_ignored_key = []
    for key in dct_requirements.keys():
        for ignored in lst_ignore:
            if ignored == key.strip():
                lst_ignored_key.append(key)
    for key in lst_ignored_key:
        del dct_requirements[key]

    venv_dir = f".venv.{config.set_version_erplibre}"
    with open(f"./{venv_dir}/build_dependency.txt", "w") as f:
        # TODO remove all comment
        f.writelines([f"{list(a)[0]}\n" for a in dct_requirements.values()])


def sorted_dependency_poetry(pyproject_filename):
    # Open pyproject.toml
    with open(pyproject_filename, "r") as f:
        dct_pyproject = toml.load(f)

    # Get dependencies and update list, sorted
    # [tool.poetry.dependencies]
    tool = dct_pyproject.get("tool")
    if tool:
        poetry = tool.get("poetry")
        if poetry:
            dependencies = poetry.get("dependencies")
            python_dependency = ("python", dependencies.get("python", ""))
            lst_dependency = [
                (k, v) for k, v in dependencies.items() if k != "python"
            ]
            lst_dependency = sorted(lst_dependency, key=lambda tup: tup[0])
            poetry["dependencies"] = OrderedDict(
                [python_dependency] + lst_dependency
            )

    # Rewrite pyproject.toml
    with open(pyproject_filename, "w") as f:
        toml.dump(dct_pyproject, f)


def delete_dependency_poetry(pyproject_filename):
    # Open pyproject.toml
    with open(pyproject_filename, "r") as f:
        dct_pyproject = toml.load(f)

    # Get dependencies and update list, sorted
    # [tool.poetry.dependencies]
    tool = dct_pyproject.get("tool")
    if tool:
        poetry = tool.get("poetry")
        if poetry:
            dependencies = poetry.get("dependencies")
            python_dependency = ("python", dependencies.get("python", ""))
            poetry["dependencies"] = OrderedDict([python_dependency])

    # Rewrite pyproject.toml
    with open(pyproject_filename, "w") as f:
        toml.dump(dct_pyproject, f)


def get_manifest_external_dependencies(config, dct_requirements, lst_sign):
    lst_manifest_file = get_lst_manifest_py(
        config, ignore_dir_startswith=["script/"]
    )
    print(f"Find {len(lst_manifest_file)} manifest.py files.")
    lst_dct_ext_depend = []
    for manifest_file in lst_manifest_file:
        with open(manifest_file, "r") as f:
            contents = f.read()
            try:
                dct = ast.literal_eval(contents)
            except:
                _logger.error(f"File {manifest_file} contains error, skip.")
                continue
            ext_depend = dct.get("external_dependencies")
            if not ext_depend:
                continue
            python = ext_depend.get("python")
            if not python:
                continue
            for depend in python:
                # TODO duplicate code, check combine_requirements()
                module_name = depend
                for sign in lst_sign:
                    if sign in depend:
                        module_name = depend[: depend.find(sign)].strip()
                requirement = dct_requirements.get(module_name)
                if requirement:
                    requirement.add(depend)
                else:
                    dct_requirements[module_name] = set([depend])

    return dct_requirements


def call_poetry_add_build_dependency():
    """

    :return: True if success
    """
    status = os.system("./script/poetry/poetry_add_build_dependency.sh")
    return status == 0


def get_list_ignored():
    with open("./requirement/ignore_requirements.txt", "r") as f:
        lst_ignore_requirements = [a.strip() for a in f.readlines()]
    return lst_ignore_requirements


def main():
    # repo = Repo(root_path)
    # lst_repo = get_all_repo()
    config = get_config()

    # print(
    #     f"Version: ERPLibre '{config.set_version_erplibre}' : Python ERPLibre '{config.set_version_python_erplibre}' : Poetry '{config.set_version_poetry}' : Odoo '{config.set_version_odoo}' : Python Odoo '{config.set_version_python_odoo}'"
    # )
    print(
        f"Version: Poetry '{config.set_version_poetry}' : Odoo '{config.set_version_odoo}' : Python '{config.set_version_python}' : ERPLibre '{config.set_version_erplibre}'"
    )

    poetry_default_lock_path = "./poetry.lock"
    pyproject_toml_filename = ""
    poetry_target_lock_path = (
        f"./requirement/poetry.{config.set_version_erplibre}.lock"
    )

    if not config.dry:
        pyproject_toml_filename = f"{config.dir}pyproject.toml"
        delete_dependency_poetry(pyproject_toml_filename)
    combine_requirements(config)
    if not config.dry:
        if config.force and os.path.isfile(poetry_default_lock_path):
            os.remove(poetry_default_lock_path)
        status = call_poetry_add_build_dependency()
        if status and pyproject_toml_filename:
            sorted_dependency_poetry(pyproject_toml_filename)
        if (
            config.force
            and not os.path.islink(poetry_default_lock_path)
            and os.path.isfile(poetry_default_lock_path)
            and os.path.isfile(poetry_target_lock_path)
        ):
            # If "./poetry.lock" is not symbolic link, force replace original
            os.remove(poetry_target_lock_path)
            shutil.move(poetry_default_lock_path, poetry_target_lock_path)
            os.symlink(poetry_target_lock_path, poetry_default_lock_path)


if __name__ == "__main__":
    main()
