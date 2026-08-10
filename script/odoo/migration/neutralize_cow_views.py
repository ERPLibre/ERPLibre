#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Neutralize the website COW views that would break a version bump.

How it works
------------
``key`` is the only thing that pairs a website copy with the module view it
came from. A copy whose key matches nothing is never paired, so it never
receives the new ``inherit_id``, never changes shape, and never takes part in
any view combination. Renaming the key is therefore enough to take a copy out
of the way::

    UPDATE ir_ui_view SET key = '<prefix>.' || key, active = false WHERE id = ?

Setting ``active = false`` alone would NOT work: an inactive copy that keeps
the same key still shadows the module view.

Nothing is deleted, so ``inherit_id ondelete='restrict'`` and the
``website_page`` foreign keys are never touched, and the 12.0 arch stays in
database as a readable archive. ``--restore`` puts everything back.

Plain psql on purpose: this must run on a database that has not been migrated
yet, where starting an Odoo shell of the target version is not guaranteed.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_cow_views import analyse  # noqa: E402

DEFAULT_PREFIX = "zz_cow_archive"


def run_psql(database, sql):
    """Run a statement and return stdout, raising on failure."""
    result = subprocess.run(
        ["psql", "-d", database, "-tAc", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Query failed on '{database}': {result.stderr.strip()}"
        )
    return result.stdout.strip()


def neutralize(database, lst_view_id, prefix):
    """Rename the key of the given views and deactivate them."""
    if not lst_view_id:
        return 0
    ids = ",".join(str(view_id) for view_id in lst_view_id)
    output = run_psql(
        database,
        "WITH updated AS ("
        f" UPDATE ir_ui_view SET key = '{prefix}.' || key, active = false"
        f" WHERE id IN ({ids}) AND key NOT LIKE '{prefix}.%'"
        " RETURNING 1) SELECT count(*) FROM updated;",
    )
    return int(output or 0)


def restore(database, prefix):
    """Undo a neutralization: strip the prefix and reactivate."""
    output = run_psql(
        database,
        "WITH updated AS ("
        f" UPDATE ir_ui_view SET key = substring(key from {len(prefix) + 2}),"
        "  active = true"
        f" WHERE key LIKE '{prefix}.%'"
        " RETURNING 1) SELECT count(*) FROM updated;",
    )
    return int(output or 0)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Neutralize the website COW views that would break a version"
            " bump, by renaming their key. Dry-run unless --apply."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "-t",
        "--target_version",
        help="target Odoo source directory, e.g. odoo13.0",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"archive prefix for the key (default: {DEFAULT_PREFIX})",
    )
    parser.add_argument(
        "--apply", action="store_true", help="actually write to the database"
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="undo a previous neutralization and reactivate the copies",
    )
    config = parser.parse_args()

    if config.restore:
        count = restore(config.database, config.prefix)
        print(f"✅ -> {count} COW view(s) restored on '{config.database}'.")
        return 0

    if not config.target_version:
        parser.error("--target_version is required unless --restore is used")
    if not os.path.isdir(config.target_version):
        print(
            f"❌ Target version directory '{config.target_version}' not found."
        )
        return 1

    lst_at_risk, _, _ = analyse(config.database, config.target_version)
    if not lst_at_risk:
        print("✅ -> No website COW view to neutralize.")
        return 0

    print(
        f"⚠️ {len(lst_at_risk)} website COW view(s) would break the bump to"
        f" {config.target_version}:"
    )
    lst_view_id = []
    for view_id, key, mode, target_mode, website_id, reason in lst_at_risk:
        lst_view_id.append(view_id)
        print(
            f"   - id={view_id} website={website_id} {key}"
            f" : {mode} -> {target_mode} ({reason})"
        )

    if not config.apply:
        print(
            "ℹ Dry-run. Add --apply to rename their key to"
            f" '{config.prefix}.<key>' and deactivate them. Reversible with"
            " --restore; the arch stays in database."
        )
        return 0

    count = neutralize(config.database, lst_view_id, config.prefix)
    print(
        f"✅ -> {count} COW view(s) neutralized (key prefixed with"
        f" '{config.prefix}.', deactivated). The arch is kept as an archive;"
        " use --restore to undo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
