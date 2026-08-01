#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Predict which website COW views will break on the next version bump.

Background
----------
When a website view is customized, Odoo makes a copy-on-write (COW) copy tied
to a website_id. That copy freezes the arch AND the structure of the module
view it was copied from.

A module view can change structure between two Odoo versions. Example measured
on a real 12.0 database: ``portal.frontend_layout`` is declared ``primary`` in
12.0 (a full QWeb template) and becomes an ``extension`` in 13.0
(``inherit_id="web.frontend_layout"`` + xpath). During the upgrade the COW copy
follows the module and becomes an extension, but keeps its 12.0 full-template
arch. Odoo then applies the ``<t t-name=...>`` root as an inheritance spec,
cannot find it in the parent, and the whole upgrade stops on::

    ValueError: Element '<t ... t-name="portal.frontend_layout">'
                cannot be located in parent view

So the rule is:

    a COW view breaks when its module counterpart changes ``mode``
    between version N and version N+1.

That is predictable *before* starting a multi-hour migration: the current mode
is in the database, and the target mode is declared in the target version
sources. This script compares the two and reports the views at risk.

It only reads: no database write, no source modification.
"""

import argparse
import glob
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

# A view whose module counterpart cannot be found is reported separately: it is
# usually a view of a module that does not exist in the target version.
MODE_UNKNOWN = "unknown"


def query_cow_views(database):
    """Return [(id, key, mode, website_id)] for every website COW view."""
    sql = (
        "SELECT id, COALESCE(key, ''), mode, website_id FROM ir_ui_view"
        " WHERE website_id IS NOT NULL ORDER BY id;"
    )
    result = subprocess.run(
        ["psql", "-d", database, "-tAF", "|", "-c", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Cannot read views from '{database}': {result.stderr.strip()}"
        )
    lst_view = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        view_id, key, mode, website_id = line.split("|")
        lst_view.append((int(view_id), key, mode, website_id))
    return lst_view


def find_module_dir(odoo_version, module_name):
    """Locate a module directory inside an odoo<version> tree."""
    lst_pattern = [
        os.path.join(odoo_version, "odoo", "addons", module_name),
        os.path.join(odoo_version, "odoo", "odoo", "addons", module_name),
        os.path.join(odoo_version, "addons", "*", module_name),
    ]
    for pattern in lst_pattern:
        for path in sorted(glob.glob(pattern)):
            if os.path.isdir(path):
                return path
    return None


def declared_mode(module_dir, template_id):
    """Return 'primary', 'extension' or None for a view declared in sources.

    Handles both declaration styles: <template id="..."> and
    <record model="ir.ui.view">. A view is an extension when it inherits and is
    not explicitly flagged primary.
    """
    pattern = os.path.join(module_dir, "**", "*.xml")
    for file_path in sorted(glob.glob(pattern, recursive=True)):
        try:
            root = ET.parse(file_path).getroot()
        except ET.ParseError:
            continue
        for element in root.iter():
            if element.get("id") != template_id:
                continue
            if element.tag == "template":
                if str(element.get("primary", "")).lower() in ("true", "1"):
                    return "primary"
                return "extension" if element.get("inherit_id") else "primary"
            if (
                element.tag == "record"
                and element.get("model") == "ir.ui.view"
            ):
                mode = None
                inherit = None
                for field in element.findall("field"):
                    if field.get("name") == "mode":
                        mode = (field.text or "").strip()
                    elif field.get("name") == "inherit_id":
                        inherit = field
                if mode:
                    return mode
                return "extension" if inherit is not None else "primary"
    return None


def analyse(database, target_version):
    """Sort COW views into three buckets by comparing with the target sources.

    - at_risk        : the module view changes mode -> the copy will break
    - module_absent  : the module itself is gone in the target version
    - no_counterpart : no module view with that id, so it is a page or a record
                       created from the editor. Normal, and not at risk.
    """
    lst_at_risk = []
    lst_module_absent = []
    lst_no_counterpart = []
    cache_mode = {}

    for view_id, key, mode, website_id in query_cow_views(database):
        if not key or "." not in key:
            continue
        if key not in cache_mode:
            module_name, _, template_id = key.partition(".")
            module_dir = find_module_dir(target_version, module_name)
            if module_dir is None:
                cache_mode[key] = MODE_UNKNOWN
            else:
                cache_mode[key] = declared_mode(module_dir, template_id)
        target_mode = cache_mode[key]
        if target_mode == MODE_UNKNOWN:
            lst_module_absent.append((view_id, key, mode, website_id))
        elif target_mode is None:
            lst_no_counterpart.append((view_id, key, mode, website_id))
        elif target_mode != mode:
            lst_at_risk.append((view_id, key, mode, target_mode, website_id))
    return lst_at_risk, lst_module_absent, lst_no_counterpart


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Report website COW views that will break on the next Odoo"
            " version bump (read-only)."
        )
    )
    parser.add_argument(
        "-d", "--database", required=True, help="database to inspect"
    )
    parser.add_argument(
        "-t",
        "--target_version",
        required=True,
        help="target Odoo source directory, e.g. odoo13.0",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="also list the editor-made pages, which are not at risk",
    )
    config = parser.parse_args()

    if not os.path.isdir(config.target_version):
        print(
            f"❌ Target version directory '{config.target_version}' not found."
        )
        return 1

    lst_at_risk, lst_module_absent, lst_no_counterpart = analyse(
        config.database, config.target_version
    )

    if not lst_at_risk:
        print(
            "✅ -> No website COW view changes mode in"
            f" {config.target_version}."
        )
    else:
        print(
            f"⚠️ {len(lst_at_risk)} website COW view(s) will break when moving"
            f" to {config.target_version}: the module view changes mode, but"
            " the copy keeps an arch written for the old mode."
        )
        for view_id, key, mode, target_mode, website_id in lst_at_risk:
            print(
                f"   - id={view_id} website={website_id} {key}"
                f" : {mode} -> {target_mode}"
            )
        print(
            "   Arbitrate BEFORE launching the migration: reset the copy on the"
            " module view, deactivate it (active=False, reversible), or rewrite"
            " the customization for the target version."
        )

    if lst_module_absent:
        print(
            f"ℹ {len(lst_module_absent)} COW view(s) belong to a module absent"
            f" from {config.target_version}:"
        )
        for view_id, key, mode, website_id in lst_module_absent:
            print(f"   - id={view_id} website={website_id} {key} ({mode})")

    if lst_no_counterpart:
        print(
            f"ℹ {len(lst_no_counterpart)} COW view(s) are pages or records made"
            " from the website editor (no module view of that name): not at"
            " risk." + ("" if config.verbose else " Use -v to list them.")
        )
        if config.verbose:
            for view_id, key, mode, website_id in lst_no_counterpart:
                print(f"   - id={view_id} website={website_id} {key} ({mode})")

    # Informative only: never fail the migration on a warning.
    return 0


if __name__ == "__main__":
    sys.exit(main())
