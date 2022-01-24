#!./.venv/bin/python
import argparse
import copy
import logging
import os
import sys

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
        description="""Replace revision field in input2 from input1 if existing, create an output of new manifest.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--input1", required=True, help="First manifest to merge into input2."
    )
    parser.add_argument(
        "--input2", required=True, help="Second manifest, overwrite by input1."
    )
    parser.add_argument(
        "--output", required=True, help="Output of new manifest"
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

    dct_remote_3 = copy.deepcopy(dct_remote_2)
    dct_project_3 = copy.deepcopy(dct_project_2)

    for key, value in dct_project_1.items():
        revision = value.get("@revision")
        if revision:
            dct_project_3[key]["@revision"] = revision
        else:
            dct_project_3[key]["@upstream"] = "12.0"
            dct_project_3[key]["@dest-branch"] = "12.0"

    # Update origin to new repo
    git_tool.generate_repo_manifest(
        dct_remote=dct_remote_3,
        dct_project=dct_project_3,
        output=config.output,
        default_remote=default_remote_2,
    )


if __name__ == "__main__":
    main()
