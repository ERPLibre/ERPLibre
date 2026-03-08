"""
ERPLibre - Project environment variable reader.

Python equivalent of env_var.sh.
Uses os.getcwd() instead of hardcoded paths.

Note: This module is imported by pyinfra deploys. To support
execution from the project root (pyinfra @local pyinfra/deploy.py)
or from the pyinfra/ directory, it searches for version files
by walking up the tree until .odoo-version is found.
"""

import os
from pathlib import Path


def _find_project_root():
    """Find the ERPLibre project root by looking for .odoo-version."""
    cwd = Path(os.getcwd())
    # Search in current directory then walk up
    for path in [cwd] + list(cwd.parents):
        if (path / ".odoo-version").exists():
            return str(path)
    # Fallback: current directory
    return str(cwd)


def _read_version_file(project_root, filename):
    """Read a version file and return its stripped content."""
    filepath = Path(project_root) / filename
    if filepath.exists():
        return filepath.read_text().strip()
    return ""


def get_env(project_root=None):
    """
    Return a dictionary with all ERPLibre environment variables,
    read from the project version files.

    Uses the current working directory (PWD) if project_root is not
    specified.
    """
    if project_root is None:
        project_root = _find_project_root()

    odoo_version = _read_version_file(project_root, ".odoo-version")
    python_odoo_version = _read_version_file(
        project_root, ".python-odoo-version"
    )
    poetry_version = _read_version_file(project_root, ".poetry-version")
    erplibre_version = _read_version_file(
        project_root, ".erplibre-version"
    )
    python_erplibre_version = _read_version_file(
        project_root, "conf/python-erplibre-version"
    )
    venv_erplibre_name = _read_version_file(
        project_root, "conf/python-erplibre-venv"
    )

    # Major Python version (e.g. "3.12.10" -> "3.12")
    python_version_major = ".".join(python_odoo_version.split(".")[:2])

    return {
        "project_root": project_root,
        "el_user": os.environ.get("USER", "erplibre"),
        "el_home": os.environ.get("HOME", ""),
        "odoo_version": odoo_version,
        "python_odoo_version": python_odoo_version,
        "python_erplibre_version": python_erplibre_version,
        "python_version_major": python_version_major,
        "poetry_version": poetry_version,
        "erplibre_version": erplibre_version,
        "venv_erplibre_name": venv_erplibre_name or ".venv.erplibre",
        "venv_erplibre_path": os.path.join(
            project_root, venv_erplibre_name or ".venv.erplibre"
        ),
        "venv_odoo_name": f".venv.{erplibre_version}",
        "venv_odoo_path": os.path.join(
            project_root, f".venv.{erplibre_version}"
        ),
        "odoo_home": os.path.join(
            project_root, f"odoo{odoo_version}", "odoo"
        ),
    }
