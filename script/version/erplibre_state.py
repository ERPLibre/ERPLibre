#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""
Utility module for reading and writing .erplibre-state.json.

This file tracks what is installed in the current ERPLibre workspace:
  - Which Odoo versions are installed, and with which options (extra, etc.)
  - Whether the mobile project is active
  - The currently active Odoo version

`update_env_version.py` imports this module as the FIRST thing `make
install_os` runs, donc avant pyenv : il s'exécute sur le Python DU SYSTÈME,
3.8 sur Ubuntu 20.04. Les annotations doivent rester différées — sans quoi
« str | None » (PEP 604) ou « list[str] » (PEP 585) sont évaluées à
l'import et lèvent un TypeError avant même que l'installation commence.
"""

from __future__ import annotations

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

# How the workspace follows its repositories. "dev" moves each project to the
# tip of its branch; "fige" pins each project to the commit recorded in a
# freeze file. Both readings come from the SAME freeze file, which carries the
# commit in @revision and the branch in @upstream — hence one file, two
# projections, and no pair of manifests drifting apart.
MODE_DEV = "dev"
MODE_FIGE = "fige"

_EMPTY_GIT_REPO = {
    "mode": MODE_DEV,
    "gel": None,
}

_EMPTY_STATE = {
    "current_odoo_version": None,
    "mobile": {
        "active": False,
        "installed_at": None,
    },
    "odoo_versions": {},
    "git_repo": {
        "mode": MODE_DEV,
        "gel": None,
    },
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
    entry = state["odoo_versions"].get(
        odoo_version, _deep_copy(_EMPTY_VERSION_ENTRY)
    )
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
    entry = state["odoo_versions"].get(
        odoo_version, _deep_copy(_EMPTY_VERSION_ENTRY)
    )
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


def get_git_repo() -> dict:
    """Return the git-repo settings, filled with defaults.

    A state file written before these settings existed has no such key, and
    a workspace that predates them must keep following its branches rather
    than fail: the default is therefore "dev" and no freeze file.
    """
    entry = _deep_copy(_EMPTY_GIT_REPO)
    entry.update(read_state().get("git_repo") or {})
    if entry.get("mode") not in (MODE_DEV, MODE_FIGE):
        entry["mode"] = MODE_DEV
    return entry


def set_git_repo_mode(mode: str) -> None:
    """Record whether the workspace follows branches or a freeze file.

    An unknown mode is refused rather than written: the merge step reads
    this value to decide which revision every project gets, and a typo
    there would silently move the whole workspace.
    """
    if mode not in (MODE_DEV, MODE_FIGE):
        raise ValueError(f"unknown git_repo mode: {mode}")
    state = read_state()
    entry = _deep_copy(_EMPTY_GIT_REPO)
    entry.update(state.get("git_repo") or {})
    entry["mode"] = mode
    state["git_repo"] = entry
    write_state(state)
    _logger.info(f"State updated: git_repo mode={mode}")


def set_git_repo_gel(gel) -> None:
    """Record which freeze file the workspace pins itself to, or None."""
    state = read_state()
    entry = _deep_copy(_EMPTY_GIT_REPO)
    entry.update(state.get("git_repo") or {})
    entry["gel"] = gel
    state["git_repo"] = entry
    write_state(state)
    _logger.info(f"State updated: git_repo gel={gel}")


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
