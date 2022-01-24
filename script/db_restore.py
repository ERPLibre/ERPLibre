#!./.venv/bin/python
import argparse
import configparser
import getpass
import logging
import os
import sys
from subprocess import check_output

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
        Restore database, use cache to clone to improve speed.
""",
        epilog="""\
""",
    )
    # parser.add_argument('-d', '--dir', dest="dir", default="./",
    #                     help="Path of repo to change remote, including submodule.")
    parser.add_argument("--database", help="Database to manipulate.")
    parser.add_argument(
        "--image",
        default="erplibre_base",
        help=(
            "Image name to restore, from directory image_db, filename without"
            " '.zip'. Example, use erplibre_base to use image"
            " erplibre_base.zip."
        ),
    )
    parser.add_argument(
        "--clean_cache",
        action="store_true",
        help="Delete all database cache to clone, begin by _cache_.",
    )
    args = parser.parse_args()
    return args


def get_master_password():
    try:
        # _logger.info("You have 5 secondes to add master password...")
        pa = getpass.getpass(prompt="\nEnter master password... ")
        return pa
    except getpass.GetPassWarning:
        _logger.error("Password echoed, danger!")


def get_list_db_cache(arg_base):
    arg = f"{arg_base} --list"
    out = check_output(arg.split(" ")).decode()
    lst_db = out.strip().split("\n")
    lst_db_cache = [a for a in lst_db if a.startswith("_cache_")]
    return lst_db, lst_db_cache


def main():
    config = get_config()

    arg_base = "./.venv/bin/python3 ./odoo/odoo-bin db"

    # check if need master password from config file
    has_config_file = True
    config_path = "./config.py"
    if not os.path.isfile(config_path):
        config_path = "/etc/odoo/odoo.conf"
        if not os.path.isfile(config_path):
            has_config_file = False
    if has_config_file:
        config_parser = configparser.ConfigParser()
        config_parser.read(config_path)

        has_admin_password = config_parser.get("options", "admin_passwd")
        if has_admin_password:
            master_password = get_master_password()
            if not master_password:
                _logger.error("Missing master password, cancel transaction.")
                sys.exit(1)
            else:
                arg_base += f" --master_password={master_password}"
        else:
            _logger.info("No master password needed... Continue")

    # Get list of database
    lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.clean_cache:
        for db in lst_db_cache:
            _logger.info(f"## Delete {db} ##")
            arg = f"{arg_base} --drop --database {db}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        lst_db, lst_db_cache = get_list_db_cache(arg_base)

    if config.database:
        cache_database = f"_cache_{config.image}"
        # Drop db
        if config.database in lst_db:
            _logger.info(f"## Drop {config.database} ##")
            arg = f"{arg_base} --drop --database {config.database}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        # Check cache exist
        if cache_database not in lst_db_cache:
            _logger.info(
                f"## Create cache {cache_database} from image"
                f" {config.image} ##"
            )
            arg = (
                f"{arg_base} --restore"
                f" --restore_image {config.image} --database {cache_database}"
            )
            out = check_output(arg.split(" ")).decode()
            print(out)
        # Clone database
        _logger.info(
            f"## Clone cache {cache_database} to database {config.database} ##"
        )
        arg = (
            f"{arg_base} --clone --from_database"
            f" {cache_database} --database {config.database}"
        )
        out = check_output(arg.split(" ")).decode()
        print(out)


if __name__ == "__main__":
    main()
