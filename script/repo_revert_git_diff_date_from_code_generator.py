#!./.venv/bin/python
import os
import sys
import argparse
import logging
import git
from unidiff import PatchSet
import re

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(new_path)

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='''\
''',
        epilog='''\
'''
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    # rex = r"\s+(?=\d{2}(?:\d{2})?-\d{1,2}-\d{1,2}\b)"
    rex = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[1-2][0-9]|3[0-1]) (2[0-3]|[01][0-9]):[0-5][0-9]"
    path = "./addons/TechnoLibre_odoo-code-generator-template"
    repo = git.Repo(path)
    supported_ext = [".xml", ".pot", ".po"]
    for diff in repo.index.diff(None, create_patch=True):
        # if diff.change_type == "M":
        file_path = diff.a_path
        filename, file_extension = os.path.splitext(file_path)
        if file_extension in supported_ext:
            file_real_path = os.path.join(path, diff.a_path)
            if not os.path.isfile(file_real_path):
                continue
            str_diff = repo.git.diff(diff.a_path)
            patch = PatchSet(str_diff)
            for modified_file in patch.modified_files:
                lst_to_write = []
                for hunk in modified_file:
                    nb_line_source = len(hunk.source)
                    nb_line_target = len(hunk.target)
                    if nb_line_source != nb_line_target:
                        # TODO support different line
                        continue
                    # try:
                    #     assert nb_line_source == nb_line_target, f"Not the same line of diff:\n{str_diff}"
                    # except Exception as e:
                    #     print(e)
                    for i in range(nb_line_source):
                        result_source = re.split(rex, hunk.source[i])
                        if i > len(hunk.target):
                            result_target = re.split(rex, hunk.target[i])
                        else:
                            result_target = ""
                        if len(result_source) > 1 or len(result_target) > 1:
                            line_to_change = hunk.target_start + i - 1
                            lst_to_write.append((line_to_change, hunk.source[i][1:]))
                # rewrite
                rewrite(file_real_path, lst_to_write)


def rewrite(file_path, lst_to_write):
    # TODO not optimal for big file
    with open(file_path, 'r') as file:
        data = file.readlines()
    for line in lst_to_write:
        data[line[0]] = line[1]
    with open(file_path, 'w') as file:
        file.writelines(data)


if __name__ == '__main__':
    main()