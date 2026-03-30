#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""
Utility module for reading and writing .erplibre-state.json.

This file tracks what is installed in the current ERPLibre workspace:
  - Which Odoo versions are installed, and with which options (extra, etc.)
  - Whether the mobile project is active
  - The currently active Odoo version
"""

import json
import logging
import os
from datetime import date

_logger = logging.getLogger(__name__)

STATE_FILE = ".erplibre-state.json"

_EMPTY_VERSION_ENTRY = {
    "installed": False,
    "extra": False,
    "python": None,
    "poetry": None,
    "installed_at": None,
    "switched_at": None,
}

_EMPTY_STATE = {
    "current_odoo_version": None,
    "mobile": {
        "active": False,
        "installed_at": None,
    },
    "odoo_versions": {},
}


def read_state() -> dict:
    """Return the current state, or an empty state if the file does not exist."""
    if not os.path.isfile(STATE_FILE):
        return _deep_copy(_EMPTY_STATE)
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning(f"Cannot read {STATE_FILE}: {e}. Using empty state.")
        return _deep_copy(_EMPTY_STATE)


def write_state(state: dict) -> None:
    """Persist state to .erplibre-state.json."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)
        f.write("\n")


def set_version_installed(
    odoo_version: str,
    extra: bool = False,
    python: str = None,
    poetry: str = None,
) -> None:
    """Record that an Odoo version has been installed (or reinstalled)."""
    state = read_state()
    entry = state["odoo_versions"].get(odoo_version, _deep_copy(_EMPTY_VERSION_ENTRY))
    entry["installed"] = True
    entry["extra"] = extra
    if python:
        entry["python"] = python
    if poetry:
        entry["poetry"] = poetry
    entry["installed_at"] = str(date.today())
    state["odoo_versions"][odoo_version] = entry
    state["current_odoo_version"] = odoo_version
    write_state(state)
    _logger.info(
        f"State updated: odoo {odoo_version} installed"
        f" (extra={extra}, python={python}, poetry={poetry})"
    )


def set_version_switched(odoo_version: str) -> None:
    """Record that the workspace was switched to an Odoo version."""
    state = read_state()
    entry = state["odoo_versions"].get(odoo_version, _deep_copy(_EMPTY_VERSION_ENTRY))
    entry["switched_at"] = str(date.today())
    state["odoo_versions"][odoo_version] = entry
    state["current_odoo_version"] = odoo_version
    write_state(state)


def set_mobile_active(active: bool) -> None:
    """Record whether the mobile project is currently synced."""
    state = read_state()
    state["mobile"]["active"] = active
    if active:
        state["mobile"]["installed_at"] = str(date.today())
    write_state(state)
    _logger.info(f"State updated: mobile active={active}")


def get_version_extra(odoo_version: str) -> bool:
    """Return True if the given Odoo version was installed with extra modules."""
    state = read_state()
    entry = state["odoo_versions"].get(odoo_version)
    if entry is None:
        return False
    return bool(entry.get("extra", False))


def get_version_installed(odoo_version: str) -> bool:
    """Return True if the given Odoo version has an installation record."""
    state = read_state()
    entry = state["odoo_versions"].get(odoo_version)
    if entry is None:
        return False
    return bool(entry.get("installed", False))


def get_current_version() -> str | None:
    """Return the currently active Odoo version, or None."""
    return read_state().get("current_odoo_version")


def get_mobile_active() -> bool:
    """Return True if mobile is recorded as active."""
    return bool(read_state().get("mobile", {}).get("active", False))


def print_state() -> None:
    """Log a human-readable summary of the current state."""
    state = read_state()
    current = state.get("current_odoo_version") or "unknown"
    mobile = state.get("mobile", {})
    mobile_status = "active" if mobile.get("active") else "inactive"

    _logger.info(f"Current Odoo version : {current}")
    _logger.info(f"Mobile context       : {mobile_status}")

    versions = state.get("odoo_versions", {})
    if versions:
        installed = [
            f"{v}{' +extra' if d.get('extra') else ''}"
            for v, d in sorted(versions.items())
            if d.get("installed")
        ]
        if installed:
            _logger.info(f"Installed versions   : {', '.join(installed)}")
        else:
            _logger.info("Installed versions   : none recorded")
    else:
        _logger.info("Installed versions   : none recorded")


def _deep_copy(d: dict) -> dict:
    """Simple deep copy for plain dicts/lists (no external deps)."""
    return json.loads(json.dumps(d))
