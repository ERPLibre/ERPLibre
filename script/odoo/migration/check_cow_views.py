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

    a COW view breaks when the shape its arch must have changes between
    version N and version N+1.

The discriminant is NOT ``mode``. What decides the required shape is whether
the target declares an ``inherit_id``: if it does, the arch must be inheritance
specs (``<data>``, ``<xpath>``, ``position=``); if it does not, the arch must be
a standalone template. Comparing ``mode`` alone misses a real case: a view
moving from a root template to ``inherit_id`` + ``primary="True"`` keeps
``mode='primary'`` on both sides yet still has to change shape, and the copy
still breaks.

That is predictable *before* starting a multi-hour migration: the stored arch is
in the database, and the required shape is declared in the target version
sources. This script compares the two and reports the views at risk.

It only reads: no database write, no source modification.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

# A view whose module counterpart cannot be found at all.
MODE_UNKNOWN = "unknown"

# arch_db is text up to 15.0 and jsonb from 16.0 ({"en_US": "<data>..."}).
RE_XML_DECLARATION = re.compile(r"<\?xml.*?\?>", re.DOTALL)
RE_FIRST_TAG = re.compile(r"<\s*([A-Za-z_][\w.:-]*)")
# Tags that carry inheritance specs rather than a standalone template.
SPEC_ROOT_TAG = ("data", "xpath")


def query_cow_views(database):
    """Return [(id, key, mode, website_id, arch)] for every website COW view."""
    sql = (
        "SELECT id, COALESCE(key, ''), mode, website_id,"
        " replace(left(COALESCE(arch_db::text, ''), 400), chr(10), ' ')"
        " FROM ir_ui_view WHERE website_id IS NOT NULL ORDER BY id;"
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
        view_id, key, mode, website_id, arch = line.split("|", 4)
        lst_view.append((int(view_id), key, mode, website_id, arch))
    return lst_view


def arch_is_inheritance_spec(arch):
    """True when the arch holds inheritance specs, not a standalone template.

    This is the real discriminant, not ``mode``. A view declared with an
    ``inherit_id`` must hold specs (``<data>``, ``<xpath>``, or an element with
    a ``position``); a root view holds a full template (``<t t-name=...>``,
    ``<form>``, ...). A copy that keeps the wrong form for what the target
    version expects is exactly what raises « cannot be located in parent view ».
    """
    if not arch:
        return None
    # From 16.0 arch_db is jsonb: take any translation, the structure is shared.
    if arch.lstrip().startswith("{"):
        try:
            translations = json.loads(arch)
            arch = next(iter(translations.values()), "")
        except (ValueError, StopIteration):
            # Truncated jsonb: fall through and look at the raw text.
            pass
    arch = RE_XML_DECLARATION.sub("", arch or "")
    match = RE_FIRST_TAG.search(arch)
    if not match:
        return None
    if match.group(1).lower() in SPEC_ROOT_TAG:
        return True
    # <field name="x" position="after"> style specs.
    return "position=" in arch[: match.end() + 200]


def load_renamed_modules(odoo_version):
    """Return {old_module: new_module} from the target OpenUpgrade apriori.py.

    Without this a module renamed upstream looks absent, and every view of that
    module is misreported as « module gone » instead of being checked.
    """
    pattern = os.path.join(odoo_version, "**", "apriori.py")
    for file_path in sorted(glob.glob(pattern, recursive=True)):
        data_vars = {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                exec(f.read(), data_vars)  # noqa: S102 - upstream data file
        except Exception:
            # A broken or exotic apriori.py must not stop the whole report.
            continue
        renamed = data_vars.get("renamed_modules")
        if isinstance(renamed, dict) and renamed:
            return renamed
    return {}


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


def declared_view_shape(module_dir, template_id):
    """Return (mode, inherits) for a view declared in the sources, else None.

    ``inherits`` is what really matters: a declared inherit_id means the arch
    must be inheritance specs. ``mode`` is kept because it is still worth
    reporting, but it is NOT a reliable discriminant: a view moving from a root
    template to « inherit_id + primary="True" » keeps mode='primary' on both
    sides while its arch shape has to change.
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
                inherits = bool(element.get("inherit_id"))
                if str(element.get("primary", "")).lower() in ("true", "1"):
                    return "primary", inherits
                return ("extension" if inherits else "primary"), inherits
            if (
                element.tag == "record"
                and element.get("model") == "ir.ui.view"
            ):
                mode = None
                inherits = False
                for field in element.findall("field"):
                    if field.get("name") == "mode":
                        mode = (field.text or "").strip()
                    elif field.get("name") == "inherit_id":
                        inherits = True
                if mode:
                    return mode, inherits
                return ("extension" if inherits else "primary"), inherits
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
    cache_shape = {}
    renamed_modules = load_renamed_modules(target_version)

    for view_id, key, mode, website_id, arch in query_cow_views(database):
        if not key or "." not in key:
            continue
        if key not in cache_shape:
            module_name, _, template_id = key.partition(".")
            module_dir = find_module_dir(target_version, module_name)
            if module_dir is None and module_name in renamed_modules:
                module_dir = find_module_dir(
                    target_version, renamed_modules[module_name]
                )
            if module_dir is None:
                cache_shape[key] = MODE_UNKNOWN
            else:
                cache_shape[key] = declared_view_shape(module_dir, template_id)
        shape = cache_shape[key]

        if shape == MODE_UNKNOWN:
            lst_module_absent.append((view_id, key, mode, website_id))
            continue
        if shape is None:
            lst_no_counterpart.append((view_id, key, mode, website_id))
            continue

        target_mode, target_inherits = shape
        is_spec = arch_is_inheritance_spec(arch)

        # The decisive test: the target expects inheritance specs but the copy
        # holds a standalone template, or the reverse.
        if is_spec is not None and target_inherits != is_spec:
            reason = (
                "target inherits, copy holds a standalone template"
                if target_inherits
                else "target is a root view, copy holds inheritance specs"
            )
            lst_at_risk.append(
                (view_id, key, mode, target_mode, website_id, reason)
            )
        elif target_mode != mode:
            # Shape is fine but the mode moves: worth reporting, less severe.
            lst_at_risk.append(
                (
                    view_id,
                    key,
                    mode,
                    target_mode,
                    website_id,
                    "mode changes, arch shape unchanged",
                )
            )
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
            f" to {config.target_version}: the copy keeps an arch whose shape"
            " no longer matches what the target module view expects."
        )
        for (
            view_id,
            key,
            mode,
            target_mode,
            website_id,
            reason,
        ) in lst_at_risk:
            print(
                f"   - id={view_id} website={website_id} {key}"
                f" : {mode} -> {target_mode} ({reason})"
            )
        print(
            "   The migration will offer to neutralize them at the bump, and"
            " shows what each copy holds before you answer. To do it now:"
            "\n     ./script/odoo/migration/cow_drift.py -d DB -t odooXX.0"
            "   (read what they hold)"
            "\n     ./script/odoo/migration/neutralize_cow_views.py -d DB"
            " -t odooXX.0 --apply   (reversible with --restore)"
        )
        print(
            "   Or by hand. To neutralize a copy,"
            " rename its key (UPDATE ir_ui_view SET key='zz_cow_archive.'||key,"
            " active=false): an unmatched key is never paired with the module"
            " view, so the copy never receives the new inherit_id. Setting"
            " active=false alone is NOT enough -- an inactive copy that keeps"
            " the same key still shadows the module view."
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
