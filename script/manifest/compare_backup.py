#!./.venv/bin/python
import argparse
import json
import logging
import os
import sys
import zipfile

from colorama import Fore, Style

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(new_path)

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Take two backup and show difference, intersection and complementarity of modules in manifest.json
""",
        epilog="""\
""",
    )
    parser.add_argument("--backup_file_1", help="Backup file path first")
    parser.add_argument("--backup_file_2", help="Backup file path second")
    parser.add_argument("--backup_1", help="Backup name first")
    parser.add_argument("--backup_2", help="Backup name second")
    args = parser.parse_args()

    die(
        bool(args.backup_file_1) and bool(args.backup_1),
        "Take only --backup_file_1 or --backup_1",
    )
    die(
        not bool(args.backup_file_1) and not bool(args.backup_1),
        "Missing --backup_file_1 or --backup_1",
    )
    die(
        bool(args.backup_file_2) and bool(args.backup_2),
        "Take only --backup_file_2 or --backup_2",
    )
    die(
        not bool(args.backup_file_2) and not bool(args.backup_2),
        "Missing --backup_file_2 or --backup_2",
    )

    return args


def main():
    config = get_config()

    if config.backup_file_1:
        file_path_1 = config.backup_file_1
    else:
        file_path_1 = os.path.join("image_db", f"{config.backup_1}.zip")

    if config.backup_file_2:
        file_path_2 = config.backup_file_2
    else:
        file_path_2 = os.path.join("image_db", f"{config.backup_2}.zip")

    with zipfile.ZipFile(file_path_1, "r") as zip_ref:
        manifest_file_1 = zip_ref.open("manifest.json")

    with zipfile.ZipFile(file_path_2, "r") as zip_ref:
        manifest_file_2 = zip_ref.open("manifest.json")

    json_manifest_file_1 = json.load(manifest_file_1)
    json_manifest_file_2 = json.load(manifest_file_2)
    set_1 = set(json_manifest_file_1.get("modules").keys())
    set_2 = set(json_manifest_file_2.get("modules").keys())

    total = set_1.union(set_2)
    same = set_1.intersection(set_2)
    difference_1 = set_1.difference(set_2)
    difference_2 = set_2.difference(set_1)
    print(f"{len(total)} total")
    print(f"{len(same)} same")
    if same:
        print(same)
    print(
        f"{Fore.BLUE}{len(difference_1)}{Style.RESET_ALL} difference manifest"
        " 1 to manifest 2"
    )
    if difference_1:
        print(difference_1)
    print(
        f"{Fore.MAGENTA}{len(difference_2)}{Style.RESET_ALL} difference"
        " manifest 2 to manifest 1"
    )
    if difference_2:
        print(difference_2)


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


if __name__ == "__main__":
    main()
