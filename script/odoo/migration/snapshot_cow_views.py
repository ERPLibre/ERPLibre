#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Snapshot the website COW views, and diff two snapshots.

Why
---
A version bump rewrites website views in ways nobody announces: OpenUpgrade
converts Bootstrap markup on every ``website_id IS NOT NULL`` view, modules
rewrite the copies they own, and some copies simply disappear. Without a
before/after record, "the site looks wrong" is unanswerable.

Taking a snapshot before and after each jump turns that into a diff: which copy
lost its arch, which changed mode, which was renamed, which vanished.

Snapshots hold customer template content, so they belong under ``private/``
and are never versioned.

Usage::

    snapshot_cow_views.py -d <database> --label before_13
    snapshot_cow_views.py -d <database> --label after_13
    snapshot_cow_views.py --diff <before.json> <after.json>
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

# Columns worth recording. ir_ui_view does not expose the same set across 12.0
# to 18.0, so the query keeps only those that actually exist.
WANTED_COLUMN = [
    "id",
    "key",
    "name",
    "type",
    "mode",
    "active",
    "priority",
    "website_id",
    "inherit_id",
    "arch_fs",
    "arch_updated",
]
DEFAULT_DIR = os.path.join("private", "odoo", "migration")


def run_psql(database, sql):
    """Run a read-only query and return stdout."""
    result = subprocess.run(
        ["psql", "-d", database, "-tAc", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Query failed on '{database}': {result.stderr.strip()}"
        )
    return result.stdout


def existing_columns(database):
    """Column names of ir_ui_view present in this database."""
    output = run_psql(
        database,
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'ir_ui_view';",
    )
    return {line.strip() for line in output.splitlines() if line.strip()}


def collect(database):
    """Return the list of COW views as plain dicts, arch included.

    The rows come back as JSON straight from Postgres: an arch holds newlines
    and pipes, so no hand-made separator survives it.
    """
    available = existing_columns(database)
    lst_column = [name for name in WANTED_COLUMN if name in available]
    select = ", ".join(lst_column) + ", arch_db::text AS arch_db"
    output = run_psql(
        database,
        "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM ("
        f" SELECT {select} FROM ir_ui_view"
        " WHERE website_id IS NOT NULL ORDER BY id) t;",
    )
    lst_view = json.loads(output or "[]")
    for view in lst_view:
        arch = view.pop("arch_db", None) or ""
        view["arch_md5"] = hashlib.md5(arch.encode("utf-8")).hexdigest()
        view["arch_len"] = len(arch)
        view["arch_db"] = arch
    return lst_view


def save(database, label, output_dir):
    """Write a snapshot and return its path."""
    directory = output_dir or os.path.join(
        DEFAULT_DIR, database, "cow_snapshots"
    )
    os.makedirs(directory, exist_ok=True)
    lst_view = collect(database)
    payload = {
        "database": database,
        "label": label,
        "taken_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "count": len(lst_view),
        "views": lst_view,
    }
    file_path = os.path.join(directory, f"{label}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"✅ -> {len(lst_view)} COW view(s) recorded in {file_path}")
    return file_path


def load(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def diff(path_before, path_after):
    """Print what changed between two snapshots."""
    before = load(path_before)
    after = load(path_after)
    map_before = {view["id"]: view for view in before["views"]}
    map_after = {view["id"]: view for view in after["views"]}

    removed = sorted(set(map_before) - set(map_after))
    added = sorted(set(map_after) - set(map_before))
    common = sorted(set(map_before) & set(map_after))

    print(
        f"📊 {before.get('label')} ({before.get('count')} views)"
        f" -> {after.get('label')} ({after.get('count')} views)"
    )

    if removed:
        print(f"❌ {len(removed)} COW view(s) disappeared:")
        for view_id in removed:
            view = map_before[view_id]
            print(f"   - id={view_id} {view.get('key')}")

    if added:
        print(f"➕ {len(added)} COW view(s) appeared:")
        for view_id in added:
            view = map_after[view_id]
            print(f"   - id={view_id} {view.get('key')} ({view.get('mode')})")

    lst_changed = []
    for view_id in common:
        old, new = map_before[view_id], map_after[view_id]
        lst_field = []
        for field in ("key", "mode", "inherit_id", "active", "arch_md5"):
            if old.get(field) != new.get(field):
                if field == "arch_md5":
                    lst_field.append(
                        f"arch rewritten ({old.get('arch_len')} ->"
                        f" {new.get('arch_len')} chars)"
                    )
                else:
                    lst_field.append(
                        f"{field}: {old.get(field)} -> {new.get(field)}"
                    )
        if lst_field:
            lst_changed.append((view_id, new.get("key"), lst_field))

    if lst_changed:
        print(f"✏️ {len(lst_changed)} COW view(s) changed:")
        for view_id, key, lst_field in lst_changed:
            print(f"   - id={view_id} {key}")
            for change in lst_field:
                print(f"       {change}")

    if not (removed or added or lst_changed):
        print("✅ -> No change on the website COW views.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot website COW views, or diff two snapshots."
    )
    parser.add_argument("-d", "--database", help="database to snapshot")
    parser.add_argument(
        "-l", "--label", help="snapshot name, e.g. before_13 or after_13"
    )
    parser.add_argument(
        "-o", "--output_dir", help="where to write (default: private/...)"
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("BEFORE", "AFTER"),
        help="compare two snapshot files instead of taking one",
    )
    config = parser.parse_args()

    if config.diff:
        return diff(*config.diff)
    if not config.database or not config.label:
        parser.error("--database and --label are required to take a snapshot")
    save(config.database, config.label, config.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
