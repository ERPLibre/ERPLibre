#!./.venv/bin/python
import argparse
import logging
import os
import sys

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)

# TODO Check if exist, (A) master[template], (B) replicator[code_generator], (C) module
# TODO if force, recreate from C
# TODO if c is code_generator_demo with a different name, execute it.
# TODO if a exist, execute it, and execute b.
# TODO open commit view


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Get the list of updating module in a working path,
        for each module, search where it's suppose to generate new code,
         compare if the date change of directory is after the starting date.
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "-d",
        "--directory",
        required=True,
        help="Directory of the module.",
    )
    parser.add_argument(
        "-m",
        "--module_name",
        required=True,
        help="Module name to create",
    )
    parser.add_argument(
        "-f",
        "--force",
        required=True,
        help="Force override directory and module.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    if not os.path.exists(config.directory):
        _logger.error(f"Path directory {config.directory} not exist.")
        return -1

    return 0


if __name__ == "__main__":
    sys.exit(main())
