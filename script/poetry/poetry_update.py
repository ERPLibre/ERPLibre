#!./.venv/bin/python
import argparse
import ast
import logging
import os
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import iscompatible
import toml

_logger = logging.getLogger(__name__)


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
    args = parser.parse_args()
    return args


def get_lst_requirements_txt():
    # Ignore some item in list
    lst = [
        a
        for a in Path(".").rglob("requirements.[tT][xX][tT]")
        if not os.path.dirname(a).startswith(".repo/")
        and not os.path.dirname(a).startswith(".venv/")
    ]
    return lst


def get_lst_manifest_py():
    return list(Path(".").rglob("__manifest__.py"))


def combine_requirements(config):
    """
    Search all module and version in all requirements.txt file in this project.
    For each version, check compatibility and show warning with provenance file
    Generate requirements.txt to "./.venv/build_dependency.txt"
    :param config:
    :return:
    """
    priority_filename_requirement = "requirements.txt"
    second_priority_filename_requirement = "odoo/requirements.txt"
    except_sign = ";"
    lst_sign = ("==", "!=", ">=", "<=", "<", ">", except_sign, "~=")
    lst_requirements = []
    lst_replace_special_sign = {}  # the lib iscompatible doesn't support ~=
    ignore_requirements = ["sys_platform == 'win32'", "python_version < '3.7'"]
    dct_requirements = defaultdict(set)
    lst_requirements_file = get_lst_requirements_txt()
    # lst_requirements_with_condition = set()
    # dct_special_condition = defaultdict(list)
    dct_requirements_module_filename = defaultdict(list)
    for requirements_filename in lst_requirements_file:
        with open(requirements_filename, "r") as f:
            for a in f.readlines():
                b = a.strip()
                if not b or b[0] == "#":
                    continue
                if "#" in b:
                    # remove comments at the end of module
                    b = b[: b.index("#")].strip()

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
                        if except_sign in b:
                            for ignore_string in ignore_requirements:
                                if ignore_string in b:
                                    break
                            if ignore_string in b:
                                break
                            # lst_requirements_with_condition.add(module_name)
                            value = b[: b.find(except_sign)].strip()
                            # dct_special_condition[module_name].append(b)
                        else:
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
        dct_requirements, lst_sign
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
                if ".*" in requirement:
                    requirement = requirement.replace(".*", "")
                if "~=" in requirement:
                    old_requirement = requirement
                    requirement = requirement.replace("~=", "==")
                    lst_replace_special_sign[requirement] = old_requirement
                result_number = iscompatible.parse_requirements(requirement)
                if not result_number:
                    # Ignore empty version
                    continue
                # Exception of missing feature in iscompatible
                # TODO support me in iscompatible lib
                no_version = result_number[0][1]
                if "b" in no_version:
                    result_number[0] = (
                        result_number[0][0],
                        no_version[: no_version.find("b")],
                    )
                elif not no_version[no_version.rfind(".") + 1 :].isnumeric():
                    result_number[0] = (
                        result_number[0][0],
                        no_version[: no_version.rfind(".")],
                    )
                result_number = iscompatible.string_to_tuple(
                    result_number[0][1]
                )
                lst_version_requirement.append((requirement, result_number))
            # Check compatibility with all possibility
            is_compatible = True
            if len(lst_version_requirement) > 1:
                highest_value = sorted(
                    lst_version_requirement, key=lambda tup: tup[1]
                )[-1]
                for version_requirement in lst_version_requirement:
                    # TODO support me in iscompatible lib
                    # check after ., because b can appear in number
                    v_r_split = version_requirement[0].split(".", 1)
                    if len(v_r_split) > 1 and "b" in v_r_split[1]:
                        version_requirement_upd = version_requirement[0][
                            : version_requirement[0].rindex("b")
                        ]
                    else:
                        version_requirement_upd = version_requirement[0]
                    try:
                        is_compatible &= iscompatible.iscompatible(
                            version_requirement_upd, highest_value[1]
                        )
                    except Exception as e:
                        print(e)
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
                        if priority_filename_requirement in filename_1:
                            erplibre_value = version_requirement[0]
                        elif (
                            second_priority_filename_requirement in filename_1
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
                        f"WARNING - Not compatible {str_versions} - "
                        f"{str_result_choose}."
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
            if ignored == key:
                lst_ignored_key.append(key)
    for key in lst_ignored_key:
        del dct_requirements[key]

    with open("./.venv/build_dependency.txt", "w") as f:
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


def get_manifest_external_dependencies(dct_requirements, lst_sign):
    lst_manifest_file = get_lst_manifest_py()
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
    with open("./ignore_requirements.txt", "r") as f:
        lst_ignore_requirements = [a.strip() for a in f.readlines()]
    return lst_ignore_requirements


def main():
    # repo = Repo(root_path)
    # lst_repo = get_all_repo()
    config = get_config()

    if not config.dry:
        pyproject_toml_filename = f"{config.dir}pyproject.toml"
        delete_dependency_poetry(pyproject_toml_filename)
    combine_requirements(config)
    if not config.dry:
        if config.force and os.path.isfile("./poetry.lock"):
            os.remove("./poetry.lock")
        status = call_poetry_add_build_dependency()
        if status:
            sorted_dependency_poetry(pyproject_toml_filename)


if __name__ == "__main__":
    main()
