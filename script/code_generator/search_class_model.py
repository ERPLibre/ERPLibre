#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import ast
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Search all method class and give a list separate by ;
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-d",
        "--directory",
        dest="directory",
        required=True,
        help="Directory to execute search in recursive.",
    )
    parser.add_argument(
        "-t",
        "--template_dir",
        dest="template_dir",
        help=(
            "Overwrite value template_model_name in template module, give only"
            " template source directory, will update file hooks.py"
        ),
    )
    parser.add_argument(
        "--with_inherit",
        action="store_true",
        help="Will search inherit model",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Return result in json",
    )
    parser.add_argument(
        "--format_json",
        action="store_true",
        help="If --json is enabled, will format json for human reader.",
    )
    parser.add_argument(
        "--show_error_json",
        action="store_true",
        help="Will show error when --json is enabled.",
    )
    parser.add_argument(
        "--extract_field",
        action="store_true",
        help=(
            "Return list of field for each model, detected. With inherit"
            " information"
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Don't show output of found model.",
    )
    args = parser.parse_args()
    return args


def search_and_replace(
    f_lines, hooks_file_path, models_name, search_word="template_model_name"
):
    if not models_name:
        return f_lines
    t_index = f_lines.find(search_word)
    if t_index == -1:
        _logger.error(f"Cannot find {search_word} in file {hooks_file_path}")
        return -1
    t_index_equation = f_lines.index("=", t_index + 1)
    if t_index_equation == -1:
        _logger.error(f"Cannot find {search_word} = in file {hooks_file_path}")
        return -1
    # find next character
    i = 1
    while f_lines[t_index_equation + i] in (" ", "\n"):
        i += 1
    first_char = f_lines[t_index_equation + i]
    if first_char == "(":
        second_char = ")"
    elif f_lines[t_index_equation + i : t_index_equation + i + 3] == '"""':
        first_char = '"""'
        second_char = '"""'
    else:
        second_char = first_char
    # t_index_first_quote = f_lines.index(first_char, t_index + 1)
    t_index_second_quote = f_lines.index(first_char, t_index_equation + i)
    if t_index_second_quote == -1:
        _logger.error(
            f'Cannot find {search_word} = "##" in file {hooks_file_path}'
        )
        return -1
    t_index_third_quote = f_lines.index(second_char, t_index_second_quote + 1)
    if t_index_third_quote == -1:
        _logger.error(f"Cannot find third quote in file {hooks_file_path}")
        return -1
    # if "\n" in models_name:
    #     new_file_content = (
    #         f'{f_lines[:t_index_second_quote]}"""{models_name}"""{f_lines[t_index_third_quote + len(second_char):]}'
    #     )
    # else:
    #     new_file_content = (
    #         f'{f_lines[:t_index_second_quote]}"{models_name}"{f_lines[t_index_third_quote + len(second_char):]}'
    #     )
    new_file_content = f'{f_lines[:t_index_second_quote]}"{models_name}"{f_lines[t_index_third_quote + len(second_char):]}'
    return new_file_content


def extract_lambda(node):
    result = ast.unparse(node)
    if result[0] == "(" and result[-1] == ")":
        result = result[1:-1]
    return result


def fill_search_field(ast_obj, var_name="", py_filename=""):
    ast_obj_type = type(ast_obj)
    result = None
    if ast_obj_type is ast.Constant:
        result = ast_obj.value
    elif ast_obj_type is ast.Lambda:
        result = extract_lambda(ast_obj)
    elif ast_obj_type is ast.UnaryOp:
        if type(ast_obj.op) is ast.USub:
            # value is negative
            result = ast_obj.operand.n * -1
        else:
            _logger.warning(
                f"Cannot support keyword of variable {var_name} type"
                f" {ast_obj_type} operator {type(ast_obj.op)} in filename"
                f" {py_filename}."
            )
    elif ast_obj_type is ast.Name:
        result = ast_obj.id
    elif ast_obj_type is ast.Attribute:
        # Support -> fields.Date.context_today
        parent_node = ast_obj
        lst_call_lambda = []
        if hasattr(parent_node, "id"):
            while hasattr(parent_node, "value"):
                lst_call_lambda.insert(0, parent_node.attr)
                parent_node = parent_node.value
            lst_call_lambda.insert(0, parent_node.id)
            result = ".".join(lst_call_lambda)
        else:
            # default=uuid.uuid4().hex
            _logger.warning(
                f"Cannot support keyword of variable {var_name} type"
                f" {ast_obj_type} in filename {py_filename}, because"
                " parent_node is type ast.Call."
            )
    elif ast_obj_type is ast.List:
        result = [fill_search_field(a, var_name) for a in ast_obj.elts]
    elif ast_obj_type is ast.Dict:
        result = {
            fill_search_field(k, var_name): fill_search_field(
                ast_obj.values[i], var_name
            )
            for (i, k) in enumerate(ast_obj.keys)
        }
    elif ast_obj_type is ast.Tuple:
        result = tuple([fill_search_field(a, var_name) for a in ast_obj.elts])
    else:
        _logger.warning(
            f"Cannot support keyword of variable {var_name} type"
            f" {ast_obj_type} in filename {py_filename}."
        )
    return result


def main():
    config = get_config()
    if not os.path.exists(config.directory):
        _logger.error(f"Path directory {config.directory} not exist.")
        return -1
    lst_model_name = []
    lst_model_inherit_name = []
    lst_search_target = ("_name",)
    dct_model = {}

    lst_search_inherit_target = ("_inherit",) if config.with_inherit else []

    # lst_py_file = glob.glob(os.path.join(config.directory, "***", "*.py"))
    lst_py_file = Path(config.directory).rglob("*.py")
    for py_file in lst_py_file:
        if py_file == "__init__.py":
            continue
        with open(py_file, "r") as source:
            f_lines = source.read()
            try:
                f_ast = ast.parse(f_lines)
            except Exception as e:
                _logger.error(f"Cannot parse file {py_file}")
                continue
            for children in f_ast.body:
                if type(children) == ast.ClassDef:
                    # Detect good _name
                    for node in children.body:
                        # Search models
                        if (
                            type(node) is ast.Assign
                            and node.targets
                            and type(node.targets[0]) is ast.Name
                            # and node.targets[0].id in ("_name",)
                            # and node.targets[0].id in ("_name", "_inherit")
                            and type(node.value) is ast.Constant
                        ):
                            model_name = ""
                            is_inherit = False
                            if (
                                lst_search_target
                                and node.targets[0].id in lst_search_target
                            ):
                                if node.value.value in lst_model_name:
                                    is_duplicated = True
                                    _logger.warning(
                                        "Duplicated model name"
                                        f" {node.value.value} from file {py_file}"
                                    )
                                else:
                                    model_name = node.value.value
                                    lst_model_name.append(node.value.value)

                            if (
                                lst_search_inherit_target
                                and node.targets[0].id
                                in lst_search_inherit_target
                            ):
                                is_inherit = True
                                if node.value.value in lst_model_inherit_name:
                                    _logger.warning(
                                        "Duplicated model inherit name"
                                        f" {node.value.value} from file {py_file}"
                                    )
                                else:
                                    model_name = node.value.value
                                    lst_model_inherit_name.append(
                                        node.value.value
                                    )
                            dct_fields = {}
                            if model_name:
                                dct_model[model_name] = {
                                    "fields": dct_fields,
                                    "model_name": model_name,
                                    "is_inherit": is_inherit,
                                }
                            # Detect fields
                            # TODO do it!
                            if model_name and (
                                type(node.value) is ast.Constant
                                and node.value.value == model_name
                                or type(node.value) is ast.List
                                and model_name
                                in [a.s for a in node.value.elts]
                            ):
                                find_children = children
                                for sequence, node in enumerate(
                                    find_children.body
                                ):
                                    if (
                                        type(node) is ast.Assign
                                        and type(node.value) is ast.Call
                                        and node.value.func.value.id
                                        == "fields"
                                    ):
                                        var_name = node.targets[0].id
                                        d = {
                                            "name": var_name,
                                            "type": node.value.func.attr,
                                            "sequence": sequence,
                                        }
                                        dct_fields[var_name] = d
                                        for keyword in node.value.keywords:
                                            value = fill_search_field(
                                                keyword.value, var_name
                                            )
                                            if value is not None:
                                                d[keyword.arg] = value
    lst_model_name.sort()
    lst_model_inherit_name.sort()
    models_name = "; ".join(lst_model_name)
    # TODO temporary fix, remove this when it's supported
    lst_ignored_inherit = ["portal.mixin", "mail.thread"]
    for ignored_inherit in lst_ignored_inherit:
        if ignored_inherit in lst_model_inherit_name:
            lst_model_inherit_name.remove(ignored_inherit)
    models_inherit_name = "; ".join(lst_model_inherit_name)
    if not config.json:
        if not config.quiet:
            # _logger.info(models_name)
            print(models_name)
            print(models_inherit_name)
    else:
        if config.format_json:
            output = json.dumps(dct_model, indent=4, sort_keys=True)
        else:
            output = json.dumps(dct_model)
        print(output)

    if config.template_dir:
        if not os.path.exists(config.template_dir):
            _logger.error(
                f"Path template dir {config.template_dir} not exist."
            )
            return -1
        hooks_file_path = os.path.join(config.template_dir, "hooks.py")
        if not os.path.exists(hooks_file_path):
            _logger.error(
                f"Path template hooks.py file {hooks_file_path} not exist."
            )
            return -1

        with open(hooks_file_path, "r") as source:
            f_lines = source.read()
            # Throw exception if not found
            new_file_content = search_and_replace(
                f_lines, hooks_file_path, models_name
            )
            if models_inherit_name:
                new_file_content = search_and_replace(
                    new_file_content,
                    hooks_file_path,
                    models_inherit_name,
                    search_word="template_inherit_model_name",
                )

        with open(hooks_file_path, "w") as source:
            source.write(new_file_content)

        # Call format all file
        os.system(f"./script/maintenance/format.sh {hooks_file_path}")

    return 0


if __name__ == "__main__":
    status = main()
    sys.exit(status)
