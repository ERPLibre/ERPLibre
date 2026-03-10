#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os

VERSION_DATA_FILE = os.path.join("conf", "supported_version_erplibre.json")
INSTALLED_ODOO_VERSION_FILE = os.path.join(
    ".repo", "installed_odoo_version.txt"
)
ODOO_VERSION_FILE = ".odoo-version"


def get_odoo_version() -> tuple[list[dict], list[str], str | None]:
    """
    Read version configuration and return sorted versions,
    installed versions, and current version.
    """
    with open(VERSION_DATA_FILE) as txt:
        data_version = json.load(txt)

    if not data_version:
        raise Exception(
            "Internal error, no Odoo version is supported,"
            f" please validate file '{VERSION_DATA_FILE}'"
        )
    version_entries = []
    for key, value in data_version.items():
        version_entries.append(value)
        value["erplibre_version"] = key

    installed_versions = []
    if os.path.exists(INSTALLED_ODOO_VERSION_FILE):
        with open(INSTALLED_ODOO_VERSION_FILE) as txt:
            installed_versions = sorted(txt.read().splitlines())

    odoo_installed_version = None
    if os.path.exists(ODOO_VERSION_FILE):
        with open(ODOO_VERSION_FILE) as txt:
            odoo_installed_version = f"odoo{txt.read().strip()}"

    versions = sorted(version_entries, key=lambda k: k.get("erplibre_version"))

    return versions, installed_versions, odoo_installed_version
