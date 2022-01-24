#!./.venv/bin/python
# © 2021 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import argparse
import logging
import os
import shutil
import subprocess
import tempfile

from git import Repo

_logger = logging.getLogger(__name__)


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Copy a directory in a temporary directory to compare with a generated code to understand the difference.""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--directory1",
        required=True,
        help="Compare input1 to input2. Input1 is older config.",
    )
    parser.add_argument(
        "--directory2",
        required=True,
        help="The generated code directory",
    )
    parser.add_argument(
        "--replace_directory",
        action="store_true",
        help="Erase after first commit to see removing file.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Don't show output of difference.",
    )
    parser.add_argument("--git_gui", action="store_true", help="Open git gui.")
    parser.add_argument("--meld", action="store_true", help="Open meld.")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete temporary directory at the end of execution.",
    )
    args = parser.parse_args()
    return args


def main():
    config = get_config()
    # path = tempfile.mkdtemp()
    path = tempfile.NamedTemporaryFile().name
    if os.path.exists(config.directory1) and os.path.exists(config.directory2):
        if config.git_gui:
            shutil.copytree(config.directory1, path)
            shutil.copy2("./.gitignore", path)
            # repo = Repo(path)
            repo = Repo.init(path=path)
            repo.git.add(".")
            repo.git.commit("-m", "First commit")
            # shutil.copy2(config.directory2, path)
            if config.replace_directory:
                subprocess.call(f"rm -r {path}/*", shell=True)
            subprocess.call(f"cp -r {config.directory2}/* {path}", shell=True)
            status = repo.git.diff()
            if not config.quiet:
                print(status)

            try:
                subprocess.call(f"cd {path};git gui", shell=True)
            except:
                pass
            if config.clear:
                shutil.rmtree(path, ignore_errors=True)
        elif config.meld:
            try:
                subprocess.call(f"make clean", shell=True)
                subprocess.call(
                    f"meld {config.directory1} {config.directory2}", shell=True
                )
            except:
                pass
    elif not os.path.exists(config.directory1):
        _logger.error(f"Path is not existing {config.directory1}")
    # elif not os.path.exists(config.directory2):
    else:
        _logger.error(f"Path is not existing {config.directory2}")


if __name__ == "__main__":
    main()
