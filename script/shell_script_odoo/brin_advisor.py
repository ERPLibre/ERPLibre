#!/usr/bin/env python3
"""
brin_advisor.py — Recommends the optimal index type for an Odoo 18 model

Usage (via odoo-bin shell):
    source .venv/bin/activate
    echo "MODEL='account.move.line'" | cat - brin_advisor.py \
        | odoo-bin shell -d my_database --no-http

    # Or with export:
    export MODEL=mail.message
    cat brin_advisor.py | odoo-bin shell -d my_database --no-http
"""

import os

# ── Constants ─────────────────────────────────────────────────────────────────

DATE_COLUMNS = [
    "date",
    "create_date",
    "write_date",
    "invoice_date",
    "scheduled_date",
    "date_done",
    "in_date",
    "expiration_date",
]

THRESHOLDS = [
    (0.9, "✅ BRIN ideal", "\033[0;32m"),
    (0.5, "⚠️  BRIN acceptable", "\033[1;33m"),
    (0.1, "❌ Prefer B-tree", "\033[0;31m"),
    (-1.0, "❌ B-tree mandatory", "\033[0;31m"),
]

RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"


# ── Helpers ───────────────────────────────────────────────────────────────────


def recommend(correlation):
    for threshold, label, color in THRESHOLDS:
        if correlation >= threshold:
            return label, color
    return THRESHOLDS[-1][1], THRESHOLDS[-1][2]


def model_to_table(model_name):
    """
    Resolve model name to table via the Odoo ORM — more reliable than a plain
    replace('.', '_') since some models override _table explicitly.
    """
    if model_name not in env:
        # Fallback: standard Odoo naming convention
        return model_name.replace(".", "_")
    return env[model_name]._table


# ── Model resolution ──────────────────────────────────────────────────────────
# Priority: MODEL variable defined before the pipe, then environment variable
model_name = (
    globals().get("MODEL") or os.environ.get("MODEL") or "account.move.line"
)
table = model_to_table(model_name)
cr = env.cr  # PostgreSQL cursor provided by odoo-bin shell

print(f"\n{BOLD}{CYAN}=== BRIN Advisor for: {model_name} ==={RESET}\n")
print(f"  Model  : {model_name}")
print(f"  Table  : {table}\n")

# ── Check table exists ────────────────────────────────────────────────────────
cr.execute(
    """
    SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = %s
""",
    (table,),
)
if cr.fetchone()[0] == 0:
    print(f"{RED}❌  Table '{table}' not found in the database.{RESET}\n")
    raise SystemExit(1)

# ── Automatic ANALYZE ─────────────────────────────────────────────────────────
# odoo-bin shell runs inside an open transaction — ANALYZE is not allowed
# inside a transaction, so we temporarily switch to AUTOCOMMIT.
print(
    f"  {YELLOW}⟳  Running ANALYZE on {table}...{RESET}", end=" ", flush=True
)
with env.cr._cnx.cursor() as auto_cr:
    old_isolation = env.cr._cnx.isolation_level
    env.cr._cnx.set_isolation_level(0)  # AUTOCOMMIT
    auto_cr.execute(
        f"ANALYZE {table}"
    )  # table name validated via ORM, no injection risk
    env.cr._cnx.set_isolation_level(old_isolation)
print(f"{GREEN}OK{RESET}\n")

# ── Table size ────────────────────────────────────────────────────────────────
cr.execute(
    """
    SELECT
        pg_size_pretty(pg_total_relation_size(%s::regclass)),
        reltuples::bigint
    FROM pg_class WHERE relname = %s
""",
    (table, table),
)
row = cr.fetchone()
if row:
    size_pretty, row_count = row
    print(
        f"  Size   : {BOLD}{size_pretty}{RESET}  (~{row_count:,} estimated rows)\n"
    )

# ── Correlation analysis ──────────────────────────────────────────────────────
cr.execute(
    """
    SELECT attname, correlation
    FROM pg_stats
    WHERE tablename = %s
      AND attname = ANY(%s)
    ORDER BY ABS(correlation) DESC NULLS LAST
""",
    (table, DATE_COLUMNS),
)
stats = cr.fetchall()

print(f"{BOLD}Date columns found:{RESET}")
print("─" * 70)
print(f"  {'COLUMN':<25} {'CORRELATION':<14} {'IDX SIZE':<12} RECOMMENDATION")
print("─" * 70)

if not stats:
    print(f"  {YELLOW}No standard date columns found on this table.{RESET}")
else:
    for col, corr in stats:
        if corr is None:
            continue
        # Size of existing BRIN index on this column, if any
        cr.execute(
            """
            SELECT pg_size_pretty(pg_relation_size(idx.indexrelid))
            FROM pg_index idx
            JOIN pg_class i ON i.oid = idx.indexrelid
            JOIN pg_attribute a
                ON a.attrelid = %s::regclass
                AND a.attnum = ANY(idx.indkey)
                AND a.attname = %s
            JOIN pg_am am ON am.oid = i.relam AND am.amname = 'brin'
            WHERE idx.indrelid = %s::regclass
            LIMIT 1
        """,
            (table, col, table),
        )
        idx_row = cr.fetchone()
        idx_size = idx_row[0] if idx_row else "none"

        label, color = recommend(corr)
        print(
            f"  {col:<25} {corr:<14.4f} {idx_size:<12} {color}{label}{RESET}"
        )

print("─" * 70)

# ── Existing BRIN indexes ─────────────────────────────────────────────────────
print(f"\n{BOLD}Existing BRIN indexes:{RESET}")
cr.execute(
    """
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = %s
      AND indexdef LIKE '%%USING brin%%'
""",
    (table,),
)
brin_indexes = cr.fetchall()

if not brin_indexes:
    print(f"  {YELLOW}No BRIN indexes found on this table.{RESET}")
else:
    for iname, _ in brin_indexes:
        print(f"  {GREEN}✔{RESET}  {iname}")

print()
