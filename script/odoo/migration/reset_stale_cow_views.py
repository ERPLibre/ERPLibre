#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Find the website COW copies that have gone stale, and reset them.

The problem
-----------
A COW copy freezes the module view it was copied from. Version after version,
the MODULE view is modernised while the copy is not — it is user data, nothing
rewrites it. The copy keeps working right up to the moment a CHILD view does an
``xpath`` onto something the module added, renamed or re-anchored::

    Element '<xpath expr="//head/script[@id='web.layout.odooscript']">'
    cannot be located in parent view

Observed on ``web.layout`` during 14.0 -> 15.0: the copy dated from 12.0, where
the script tag had no ``id`` and QWeb still said ``t-raw``. It had survived
until then only because the 14.0 module xpath carried a fallback
(``//head/script[@id='…'] | //head/script[last()]``) that 15.0 removed.

What this checks
----------------
Not a heuristic on deprecated syntax, and not an absolute one either: the
DRIFT between a copy and its module twin. For every active child of a COW
copy, each ``xpath`` expression is resolved twice — against the module twin
and against the copy. An expression the twin can satisfy and the copy cannot
is an anchor the copy has lost.

The comparison has to be differential. Odoo resolves an xpath against the
COMBINED arch of the whole inheritance chain, so « does not resolve in this
parent » proves nothing on its own — a child of ``website.layout`` targets
``//header``, which comes from an ancestor.

When it bites
-------------
A reported copy is not necessarily failing right now. Odoo re-validates a COW
copy when its module twin is REWRITTEN — which is what a version bump does —
or when the page is rendered for that website. So a finding is a breakage
already present in the data, waiting for the next bump to surface it. That is
precisely when it is cheap to fix.

Resetting
---------
``--reset`` copies the MODULE arch over the stale copy. The previous arch is
always written to a backup file first, and the diff is printed, because a copy
can hold a genuine customisation — one line among fifty of drift. Read the
diff, reset, then re-apply what mattered as an INHERITING view rather than a
full copy, so the next version bump cannot make it stale again.

Plain psql on purpose: this runs on databases whose Odoo registry does not
load, which is precisely when it is needed.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


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
    return result.stdout


def normalise_arch(value):
    """The arch as a string, whatever the column type.

    Odoo stores ``arch_db`` as text up to 15.0 and as jsonb (one entry per
    language) from 16.0. Casting to text gives ``{"en_US": "<t …"}`` in the
    second case, so unwrap it — the structure is the same in every language,
    and the structure is all this tool looks at.
    """
    if not isinstance(value, str):
        return "" if value is None else str(value)
    text = value.strip()
    if text.startswith("{") and '"' in text:
        try:
            data = json.loads(text)
        except ValueError:
            return value
        if isinstance(data, dict) and data:
            for lang in ("en_US", *sorted(data)):
                if lang in data and isinstance(data[lang], str):
                    return data[lang]
    return value


def fetch_views(database):
    """Every view that matters: COW copies, their module twin, their children.

    One query rather than one per view — these databases hold thousands of
    views. The result comes back as JSON: an arch is multi-line XML, so any
    line-based format would need a record separator the data could forge.
    """
    raw = run_psql(
        database,
        "SELECT COALESCE(json_agg(json_build_object("
        "'id', id, 'key', COALESCE(key, ''), 'inherit_id', inherit_id,"
        "'website_id', website_id, 'active', active,"
        "'arch', arch_db::text))::text, '[]')"
        " FROM ir_ui_view WHERE arch_db IS NOT NULL",
    )
    rows = {}
    for item in json.loads(raw.strip() or "[]"):
        item["arch"] = normalise_arch(item.get("arch"))
        rows[item["id"]] = item
    return rows


XPATH_RE = re.compile(r"<xpath\b[^>]*\bexpr=([\"'])(.*?)\1", re.S)


def child_xpaths(arch):
    """The xpath expressions a view applies to its parent."""
    return [match.group(2) for match in XPATH_RE.finditer(arch)]


def require_lxml():
    """The XPath engine, or a loud failure.

    Never degrade to « everything resolves » when lxml is missing: a checker
    that cannot check must not answer « all clean ». Odoo's own venvs all ship
    lxml; the bare system python3 usually does not.
    """
    try:
        from lxml import etree

        return etree
    except ImportError:
        sys.exit(
            f"❌ {t('lxml is required to resolve the xpath expressions.')}\n"
            "   Run this with an interpreter that has it, e.g.\n"
            "   ./.venv.erplibre/bin/python3 " + os.path.relpath(__file__)
        )


def resolve(etree, arch, expr):
    """True if `expr` matches something in `arch`.

    An arch that does not parse, or an expression lxml cannot evaluate, counts
    as resolvable: this tool reports views that will CERTAINLY break, and must
    never invent a failure it cannot substantiate.
    """
    try:
        tree = etree.fromstring(arch.encode("utf-8"))
    except etree.XMLSyntaxError:
        return True
    try:
        return bool(tree.xpath(expr))
    except etree.XPathEvalError:
        return True


def analyse(database):
    """[(copy, module_twin, [(child_id, failing_expr), ...])] — the COW copies
    that have DRIFTED away from their module twin.

    The test is differential, and it has to be. Odoo resolves an xpath against
    the COMBINED arch of the whole inheritance chain, not against the parent's
    own arch, so « does not resolve here » proves nothing on its own: a child
    of ``website.layout`` legitimately targets ``//header``, which comes from
    an ancestor. Comparing the copy with its module twin removes that whole
    class of noise:

        resolves in the module twin, not in the copy  -> the copy lost an
                                                         anchor: real drift
        resolves in neither                           -> the anchor lives
                                                         further up the chain
        resolves in both                              -> nothing to see

    Inactive children are skipped: Odoo never applies them, so they cannot
    break a load.
    """
    etree = require_lxml()
    views = fetch_views(database)
    module_by_key = {
        v["key"]: v
        for v in views.values()
        if v["website_id"] is None and v["key"]
    }
    children = {}
    for view in views.values():
        if view["inherit_id"]:
            children.setdefault(view["inherit_id"], []).append(view)

    findings = []
    for view in sorted(views.values(), key=lambda v: v["id"]):
        twin = module_by_key.get(view["key"])
        if view["website_id"] is None or twin is None:
            continue
        broken = []
        for child in children.get(view["id"], []):
            if not child.get("active", True):
                continue
            for expr in child_xpaths(child["arch"]):
                if resolve(etree, twin["arch"], expr) and not resolve(
                    etree, view["arch"], expr
                ):
                    broken.append((child["id"], expr))
        if broken:
            findings.append((view, twin, broken))
    return findings


def show_diff(module_view, cow_view):
    """Module arch vs copy: what the copy would gain and lose on a reset."""
    diff = difflib.unified_diff(
        module_view["arch"].splitlines(),
        cow_view["arch"].splitlines(),
        fromfile=f"module id={module_view['id']}",
        tofile=f"cow id={cow_view['id']}",
        lineterm="",
    )
    for line in diff:
        print(f"    {line}")


def backup(database, cow_view, directory):
    """Store the arch about to be replaced, and return the file path."""
    os.makedirs(directory, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(
        directory, f"{cow_view['key']}_{cow_view['id']}_{stamp}.json"
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "database": database,
                "id": cow_view["id"],
                "key": cow_view["key"],
                "website_id": cow_view["website_id"],
                "saved_at": stamp,
                "arch_db": cow_view["arch"],
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
    return path


def reset(database, cow_view, module_view):
    """Copy the module arch over the stale copy. Returns rows updated."""
    sql = (
        "UPDATE ir_ui_view c SET arch_db = m.arch_db "
        "FROM ir_ui_view m "
        f"WHERE c.id = {cow_view['id']} AND m.id = {module_view['id']}"
    )
    run_psql(database, sql)
    return 1


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Report the website COW copies whose children can no longer be"
            " applied, and optionally reset them onto the module view."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--reset",
        metavar="KEY",
        action="append",
        default=[],
        help="reset this key onto its module view ('all' for every finding)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="really write; without it --reset only shows what it would do",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="where the replaced arch is saved"
        " (default private/odoo/migration/<db>/cow_reset)",
    )
    config = parser.parse_args()

    findings = analyse(config.database)
    if not findings:
        print(f"✅ {t('No COW copy has drifted from its module view.')}")
        return 0

    print(
        f"⚠️  {len(findings)} {t('COW copy(ies) drifted from their module')}"
        f" {t('view in')} {config.database}"
    )
    print(
        f"   {t('Odoo surfaces this when the module view is rewritten (a')}"
        f" {t('version bump) or when the page is rendered.')}\n"
    )
    for cow_view, module_view, broken in findings:
        twin = (
            f"module id={module_view['id']}"
            if module_view
            else t("NO module view with this key")
        )
        print(
            f"  id={cow_view['id']} key={cow_view['key']}"
            f" website_id={cow_view['website_id']}  [{twin}]"
        )
        for child_id, expr in broken:
            print(f"      {t('child')} {child_id} {t('cannot apply')}: {expr}")
        if module_view:
            show_diff(module_view, cow_view)
        print()

    if not config.reset:
        print(
            f"{t('Nothing changed. Re-run with --reset <key> --apply to')}"
            f" {t('reset a copy onto its module view.')}"
        )
        return 1

    wanted = set(config.reset)
    directory = config.backup_dir or os.path.join(
        "private", "odoo", "migration", config.database, "cow_reset"
    )
    done = 0
    for cow_view, module_view, _broken in findings:
        if "all" not in wanted and cow_view["key"] not in wanted:
            continue
        if not module_view:
            print(
                f"⏭  {cow_view['key']} :"
                f" {t('no module view to reset onto, skipped.')}"
            )
            continue
        if not config.apply:
            print(
                f"[{t('dry-run')}] {t('would reset')} id={cow_view['id']}"
                f" ({cow_view['key']}) {t('onto')} id={module_view['id']}"
            )
            continue
        path = backup(config.database, cow_view, directory)
        reset(config.database, cow_view, module_view)
        done += 1
        print(f"✅ {t('reset')} id={cow_view['id']} ({cow_view['key']})")
        print(f"   {t('previous arch saved to')} {path}")
    if config.apply and done:
        print(
            f"\n{done} {t('copy(ies) reset. Re-apply any real customisation')}"
            f" {t('as an INHERITING view, not a copy, so it cannot go stale')}"
            f" {t('again.')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
