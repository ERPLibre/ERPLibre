#!./.venv/bin/python
import argparse

# import glob
import ast
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
    new_file_content = (
        f'{f_lines[:t_index_second_quote]}"{models_name}"{f_lines[t_index_third_quote + len(second_char):]}'
    )
    return new_file_content


def main():
    config = get_config()
    if not os.path.exists(config.directory):
        _logger.error(f"Path directory {config.directory} not exist.")
        return -1
    lst_model_name = []
    lst_model_inherit_name = []
    lst_search_target = ("_name",)

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
                        if (
                            type(node) is ast.Assign
                            and node.targets
                            and type(node.targets[0]) is ast.Name
                            # and node.targets[0].id in ("_name",)
                            and type(node.value) is ast.Str
                        ):
                            if (
                                lst_search_target
                                and node.targets[0].id in lst_search_target
                            ):
                                if node.value.s in lst_model_name:
                                    _logger.warning(
                                        "Duplicated model name"
                                        f" {node.value.s} from file {py_file}"
                                    )
                                else:
                                    lst_model_name.append(node.value.s)

                            if (
                                lst_search_inherit_target
                                and node.targets[0].id
                                in lst_search_inherit_target
                            ):
                                if node.value.s in lst_model_inherit_name:
                                    _logger.warning(
                                        "Duplicated model inherit name"
                                        f" {node.value.s} from file {py_file}"
                                    )
                                else:
                                    lst_model_inherit_name.append(node.value.s)
    lst_model_name.sort()
    lst_model_inherit_name.sort()
    models_name = "; ".join(lst_model_name)
    # TODO temporary fix, remove this when it's supported
    lst_ignored_inherit = ["portal.mixin", "mail.thread"]
    for ignored_inherit in lst_ignored_inherit:
        if ignored_inherit in lst_model_inherit_name:
            lst_model_inherit_name.remove(ignored_inherit)
    models_inherit_name = "; ".join(lst_model_inherit_name)
    if not models_name:
        _logger.warning(f"Missing models class in {config.directory}")
    elif not config.quiet:
        # _logger.info(models_name)
        print(models_name)
        print(models_inherit_name)

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

        # Call black
        os.system(f"./script/maintenance/black.sh {hooks_file_path}")

    return 0


if __name__ == "__main__":
    status = main()
    sys.exit(status)
