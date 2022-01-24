#!./.venv/bin/python
import argparse
import logging
import os
import sys

import yaml

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git_tool import GitTool

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    config = GitTool.get_project_config()

    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Update version of docker ready to commit.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--version", required=True, help="Version of ERPLibre."
    )
    parser.add_argument("--base", required=True, help="Docker base name.")
    parser.add_argument("--prod", required=True, help="Docker prod name.")
    parser.add_argument(
        "--docker_compose_file",
        default="./docker-compose.yml",
        help="Docker compose file to update.",
    )
    parser.add_argument(
        "--docker_prod",
        default="./docker/Dockerfile.prod.pkg",
        help="Docker prod file to update.",
    )
    args = parser.parse_args()
    args.base_version = f"{args.base}:{args.version}"
    args.prod_version = f"{args.prod}:{args.version}"
    return args


# def edit_yaml(config):
#     with open(config.docker_compose_file, 'r') as f:
#         docker_info = yaml.safe_load(f)
#     if not docker_info:
#         print(f"ERROR, file {config.docker_compose_file} is empty.")
#         sys.exit(1)
#
#     dct_services = docker_info.get("services")
#     dct_erplibre = dct_services.get("ERPLibre") if dct_services else None
#     if dct_erplibre:
#         dct_erplibre["image"] = config.prod_version
#     with open(config.docker_compose_file, 'w') as f:
#         yaml.dump(docker_info, f)


def edit_text(config):
    with open(config.docker_compose_file, "r") as f:
        lst_docker_info = f.readlines()

    if not lst_docker_info:
        print(f"ERROR, file {config.docker_compose_file} is empty.")
        sys.exit(1)

    is_find = False
    i = 0
    for docker_info in lst_docker_info:
        if is_find:
            key = "image:"
            value = lst_docker_info[i]
            lst_docker_info[
                i
            ] = f"{value[:value.find(key) + len(key)]} {config.prod_version}\n"
            break
        if "ERPLibre" in docker_info:
            is_find = True
        i += 1

    with open(config.docker_compose_file, "w") as f:
        f.writelines(lst_docker_info)


def edit_docker_prod(config):
    with open(config.docker_prod, "r") as f:
        lst_docker_info = f.readlines()

    if not lst_docker_info:
        print(f"ERROR, file {config.docker_compose_file} is empty.")
        sys.exit(1)

    i = 0
    for docker_info in lst_docker_info:
        if "FROM " in docker_info:
            lst_docker_info[i] = f"FROM {config.base_version}\n"
        i += 1

    with open(config.docker_prod, "w") as f:
        f.writelines(lst_docker_info)


def main():
    config = get_config()
    edit_text(config)
    edit_docker_prod(config)


if __name__ == "__main__":
    main()
