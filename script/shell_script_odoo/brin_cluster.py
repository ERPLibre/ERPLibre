#!/usr/bin/env python3
"""
brin_cluster.py — Reorders table rows physically to optimize BRIN indexes.

Strategy:
  1. Check correlation of candidate columns via pg_stats
  2. Pick the best column (highest absolute correlation, ideally create_date)
  3. Create a temporary B-tree index on that column
  4. CLUSTER the table on that index (rewrites rows in physical order)
  5. ANALYZE to refresh statistics
  6. Drop the temporary B-tree index
  7. Report the new correlation

WARNING:
  - CLUSTER acquires an ACCESS EXCLUSIVE lock — the table is fully locked.
  - On large tables, this can take minutes to hours.
  - Run during a maintenance window or off-peak hours.
  - Always pg_dump before running on production.

Usage:
    export MODEL=account.move.line
    cat brin_cluster.py | odoo-bin shell -d my_database --no-http

    # Dry run (no changes, just shows what would be done):
    export MODEL=account.move.line DRY_RUN=1
    cat brin_cluster.py | odoo-bin shell -d my_database --no-http
"""

import os
import time

# ── Constants ─────────────────────────────────────────────────────────────────

# Columns considered as clustering candidates, in priority order.
# create_date is first: it's never updated, so correlation is always perfect.
CANDIDATE_COLUMNS = [
    "create_date",
    "date",
    "invoice_date",
    "write_date",
    "scheduled_date",
    "date_done",
    "in_date",
]

BRIN_IDEAL_THRESHOLD = 0.9

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"


# ── Config ────────────────────────────────────────────────────────────────────

model_name = (
    globals().get("MODEL") or os.environ.get("MODEL") or "account.move.line"
)
dry_run = bool(globals().get("DRY_RUN") or os.environ.get("DRY_RUN"))

if model_name not in env:
    table = model_name.replace(".", "_")
else:
    table = env[model_name]._table

cr = env.cr
cnx = env.cr._cnx

print(f"\n{BOLD}{CYAN}=== BRIN Cluster for: {model_name} ==={RESET}")
print(f"  Table   : {table}")
print(f"  Dry run : {dry_run}\n")


# ── Helpers ───────────────────────────────────────────────────────────────────


def autocommit(sql, params=None):
    """Execute a DDL statement outside the current transaction (AUTOCOMMIT)."""
    old = cnx.isolation_level
    cnx.set_isolation_level(0)
    with cnx.cursor() as c:
        c.execute(sql, params)
    cnx.set_isolation_level(old)


def get_correlations():
    cr.execute(
        """
        SELECT attname, correlation
        FROM pg_stats
        WHERE tablename = %s
          AND attname = ANY(%s)
          AND correlation IS NOT NULL
        ORDER BY ABS(correlation) DESC
    """,
        (table, CANDIDATE_COLUMNS),
    )
    return {row[0]: row[1] for row in cr.fetchall()}


def table_size():
    cr.execute(
        """
        SELECT
            pg_size_pretty(pg_total_relation_size(%s::regclass)),
            reltuples::bigint
        FROM pg_class WHERE relname = %s
    """,
        (table, table),
    )
    return cr.fetchone()


def index_exists(index_name):
    cr.execute(
        """
        SELECT COUNT(*) FROM pg_indexes
        WHERE tablename = %s AND indexname = %s
    """,
        (table, index_name),
    )
    return cr.fetchone()[0] > 0


# ── Step 1: ANALYZE to get fresh stats ───────────────────────────────────────

print(f"  {YELLOW}⟳  ANALYZE {table}...{RESET}", end=" ", flush=True)
autocommit(f"ANALYZE {table}")
print(f"{GREEN}OK{RESET}\n")

size_pretty, row_count = table_size()
print(
    f"  Size    : {BOLD}{size_pretty}{RESET}  (~{row_count:,} estimated rows)\n"
)

# ── Step 2: Check current correlations ───────────────────────────────────────

correlations = get_correlations()

if not correlations:
    print(f"{RED}❌  No date columns found on {table}. Aborting.{RESET}\n")
    raise SystemExit(1)

print(f"{BOLD}Current correlations:{RESET}")
for col, corr in sorted(correlations.items(), key=lambda x: -abs(x[1])):
    if abs(corr) >= BRIN_IDEAL_THRESHOLD:
        icon = f"{GREEN}✅ BRIN ideal{RESET}"
    else:
        icon = f"{YELLOW}⚠️  needs clustering{RESET}"
    print(f"  {col:<25} {corr:+.4f}   {icon}")

# ── Step 3: Pick the best clustering column ───────────────────────────────────

# Only cluster if at least one *candidate* column is suboptimal.
# Note: a column like `date` (user-editable) may never reach ideal correlation
# regardless of clustering — that's expected and not a reason to cluster.
suboptimal = {
    col: corr
    for col, corr in correlations.items()
    if abs(corr) < BRIN_IDEAL_THRESHOLD
}
ideal = {
    col: corr
    for col, corr in correlations.items()
    if abs(corr) >= BRIN_IDEAL_THRESHOLD
}

if suboptimal:
    print(f"\n  {YELLOW}⚠️  Suboptimal columns: {', '.join(suboptimal)}{RESET}")
    print(
        f"  {CYAN}Note: columns like 'date' or 'invoice_date' may stay suboptimal"
    )
    print(
        f"  after clustering if users enter backdated records — that's expected.{RESET}"
    )
else:
    print(
        f"\n{GREEN}✅  All columns already have ideal correlation. No clustering needed.{RESET}\n"
    )
    raise SystemExit(0)

# Pick the best clustering column: highest absolute correlation among candidates.
# Prefer create_date first (never updated → guaranteed monotonic order),
# then fall back to the column with highest abs(correlation).
cluster_col = None
for preferred in CANDIDATE_COLUMNS:
    if preferred in ideal:  # already ideal → good anchor for physical order
        cluster_col = preferred
        break
if not cluster_col:
    # All candidates are suboptimal — pick the least bad one
    cluster_col = max(suboptimal, key=lambda c: abs(suboptimal[c]))

if not cluster_col:
    print(f"{RED}❌  No suitable clustering column found. Aborting.{RESET}\n")
    raise SystemExit(1)

print(
    f"\n  {BOLD}Clustering column chosen:{RESET} {cluster_col}  "
    f"(current correlation: {correlations[cluster_col]:+.4f})\n"
)

# ── Step 4: Create temporary B-tree index ────────────────────────────────────

tmp_index = f"_brin_cluster_tmp_{table}_{cluster_col}"

if index_exists(tmp_index):
    print(
        f"  {YELLOW}⚠️  Temporary index already exists, dropping it first...{RESET}"
    )
    if not dry_run:
        autocommit(f'DROP INDEX IF EXISTS "{tmp_index}"')

print(
    f"  {YELLOW}⟳  Creating temporary B-tree index on {cluster_col}...{RESET}",
    end=" ",
    flush=True,
)
if not dry_run:
    autocommit(f'CREATE INDEX "{tmp_index}" ON "{table}" ("{cluster_col}")')
    print(f"{GREEN}OK{RESET}")
else:
    print(f"{CYAN}[DRY RUN]{RESET}")

# ── Step 5: CLUSTER ───────────────────────────────────────────────────────────

print(f"\n  {YELLOW}⟳  CLUSTER {table} on {cluster_col}...{RESET}")
print(
    f"  {YELLOW}     (ACCESS EXCLUSIVE lock — table unavailable during this operation){RESET}",
    end=" ",
    flush=True,
)

if not dry_run:
    t0 = time.time()
    autocommit(f'CLUSTER "{table}" USING "{tmp_index}"')
    elapsed = time.time() - t0
    print(f"{GREEN}OK{RESET}  ({elapsed:.1f}s)")
else:
    print(f"{CYAN}[DRY RUN]{RESET}")

# ── Step 6: Drop temporary index ─────────────────────────────────────────────

print(
    f"\n  {YELLOW}⟳  Dropping temporary index...{RESET}", end=" ", flush=True
)
if not dry_run:
    autocommit(f'DROP INDEX IF EXISTS "{tmp_index}"')
    print(f"{GREEN}OK{RESET}")
else:
    print(f"{CYAN}[DRY RUN]{RESET}")

# ── Step 7: ANALYZE again + report new correlations ──────────────────────────

print(
    f"\n  {YELLOW}⟳  ANALYZE after clustering...{RESET}", end=" ", flush=True
)
if not dry_run:
    autocommit(f"ANALYZE {table}")
    print(f"{GREEN}OK{RESET}\n")

    new_correlations = get_correlations()

    print(f"{BOLD}Correlations after clustering:{RESET}")
    print("─" * 55)
    print(f"  {'COLUMN':<25} {'BEFORE':>8}   {'AFTER':>8}   RESULT")
    print("─" * 55)
    for col in sorted(correlations.keys()):
        before = correlations.get(col, 0.0)
        after = new_correlations.get(col, 0.0)
        delta = after - before
        if abs(after) >= BRIN_IDEAL_THRESHOLD:
            result = f"{GREEN}✅ BRIN ideal{RESET}"
        else:
            result = f"{YELLOW}⚠️  still suboptimal{RESET}"
        arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
        print(
            f"  {col:<25} {before:>+8.4f}   {after:>+8.4f} {arrow}  {result}"
        )
    print("─" * 55)
else:
    print(f"{CYAN}[DRY RUN]{RESET}")

print(f"\n{GREEN}✅  Done.{RESET}\n")
