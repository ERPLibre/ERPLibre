#!./.venv/bin/python
import argparse
import logging
import os
import sys

from git import Repo

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(new_path)

from script.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Get git diff between manifest repo revision,
        diff revision input1 to input2 """,
        epilog="""\
""",
    )
    parser.add_argument(
        "--input1",
        required=True,
        help="Compare input1 to input2. Input1 is older config.",
    )
    parser.add_argument(
        "--input2",
        required=True,
        help="Compare input1 to input2. Input2 is newer config.",
    )
    # parser.add_argument('--clear', action="store_true",
    #                     help="Create a new manifest and clear old configuration.")
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    git_tool = GitTool()

    (
        dct_remote_1,
        dct_project_1,
        default_remote_1,
    ) = git_tool.get_manifest_xml_info(filename=config.input1, add_root=True)
    (
        dct_remote_2,
        dct_project_2,
        default_remote_2,
    ) = git_tool.get_manifest_xml_info(filename=config.input2, add_root=True)

    set_project_1 = set(dct_project_1.keys())
    set_project_2 = set(dct_project_2.keys())
    lst_same_name_normalize = set_project_1.intersection(set_project_2)
    lst_missing_name_normalize = set_project_2.difference(set_project_1)
    lst_over_name_normalize = set_project_1.difference(set_project_2)

    i = 0
    total = len(lst_same_name_normalize)
    for key in lst_missing_name_normalize:
        i += 1
        print(f"{i}/{total} - {key} from input1 not in input2.")

    i = 0
    total = len(lst_over_name_normalize)
    for key in lst_over_name_normalize:
        i += 1
        print(f"{i}/{total} - {key} from input2 not in input1.")

    i = 0
    total = len(lst_same_name_normalize)
    for key in lst_same_name_normalize:
        value1 = dct_project_1.get(key)
        value2 = dct_project_2.get(key)
        old_revision = value1.get("@revision", git_tool.default_branch)
        new_revision = value2.get("@revision", git_tool.default_branch)

        path1 = value1.get("@path")
        path2 = value2.get("@path")
        if path1 != path2:
            print(
                f"WARNING id {i}, path of git are different. "
                f"Input1 {path1}, input2 {path2}"
            )
            continue

        i += 1
        result = "same" if old_revision == new_revision else "diff"
        print(
            f"{i}/{total} - {result} - "
            f"{path1} {key} old {old_revision} new {new_revision}"
        )
        default_arg = [f"{old_revision}..{new_revision}"]
        if old_revision != new_revision:
            # get git diff
            repo = Repo(path1)
            status = repo.git.diff(*default_arg)
            print(status)


if __name__ == "__main__":
    main()
