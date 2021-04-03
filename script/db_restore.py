#!./.venv/bin/python
import os
import sys
import argparse
import logging
from subprocess import check_output

new_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
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
        description='''\
        Restore database, use cache to clone to improve speed.
''',
        epilog='''\
'''
    )
    # parser.add_argument('-d', '--dir', dest="dir", default="./",
    #                     help="Path of repo to change remote, including submodule.")
    parser.add_argument('--database', help="Database to manipulate.")
    parser.add_argument('--image', default="erplibre_base",
                        help="Image name to restore, from directory image_db, filename without '.zip'. "
                             "Example, use erplibre_base to use image erplibre_base.zip.")
    parser.add_argument('--clean_cache', action="store_true", help="Delete all database cache to clone, "
                                                                   "begin by _cache_.")
    args = parser.parse_args()
    return args


def main():
    config = get_config()

    # Get list of database
    arg = "./.venv/bin/python3 ./odoo/odoo-bin db --list"
    out = check_output(arg.split(" ")).decode()
    lst_db = out.strip().split("\n")
    lst_db_cache = [a for a in lst_db if a.startswith("_cache_")]

    if config.clean_cache:
        for db in lst_db_cache:
            _logger.info(f"## Delete {db} ##")
            arg = f"./.venv/bin/python3 ./odoo/odoo-bin db --drop --database {db}"
            out = check_output(arg.split(" ")).decode()
            print(out)

    if config.database:
        cache_database = f"_cache_{config.image}"
        # Drop db
        if config.database in lst_db:
            _logger.info(f"## Drop {config.database} ##")
            arg = f"./.venv/bin/python3 ./odoo/odoo-bin db --drop --database {config.database}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        # Check cache exist
        if cache_database not in lst_db_cache:
            _logger.info(f"## Create cache {cache_database} from image {config.image} ##")
            arg = f"./.venv/bin/python3 ./odoo/odoo-bin db --restore --restore_image {config.image} " \
                  f"--database {cache_database}"
            out = check_output(arg.split(" ")).decode()
            print(out)
        # Clone database
        _logger.info(f"## Clone cache {cache_database} to database {config.database} ##")
        arg = f"./.venv/bin/python3 ./odoo/odoo-bin db --clone --from_database {cache_database} " \
              f"--database {config.database}"
        out = check_output(arg.split(" ")).decode()
        print(out)


if __name__ == '__main__':
    main()
