#!/usr/bin/env python3
# © 2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import asyncio
import asyncio.subprocess as asp
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
_logger = logging.getLogger(__name__)

# TODO this script need odoo 18


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """
    # TODO update description
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\

""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--path", required=True, help="Path to directory to migrate all module"
    )
    args = parser.parse_args()

    return args


async def run_cmd(cmd: str):
    """Run a command asynchronously and log output."""
    proc = await asp.create_subprocess_shell(
        cmd,
        stdout=asp.PIPE,
        stderr=asp.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if stdout:
        _logger.info(stdout.decode().strip())
    if stderr:
        _logger.error(stderr.decode().strip())

    return proc.returncode


async def migrate_modules(config):
    """Find Odoo modules and run migration script on each."""
    chemin_du_dossier = Path(config.path)
    if not chemin_du_dossier.exists():
        die(True, f"Path {chemin_du_dossier} does not exist")

    tasks = []
    for element in chemin_du_dossier.iterdir():
        manifest = element / "__manifest__.py"
        if element.is_dir() and manifest.exists():
            cmd = f"./script/code/odoo_upgrade_code_with_single_module_autosearch.sh {element.name}"
            _logger.info("Executing: %s", cmd)
            tasks.append(run_cmd(cmd))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, res in enumerate(results):
            if isinstance(res, Exception):
                _logger.error("Task %d failed with exception: %s", idx, res)
            elif res != 0:
                _logger.error("Task %d exited with code %d", idx, res)
            else:
                _logger.info("Task %d completed successfully", idx)
    else:
        _logger.warning("No modules found in %s", chemin_du_dossier)


def die(cond, message, code=1):
    if cond:
        print(message, file=sys.stderr)
        sys.exit(code)


async def async_main():
    config = get_config()
    await migrate_modules(config)


if __name__ == "__main__":
    asyncio.run(async_main())
