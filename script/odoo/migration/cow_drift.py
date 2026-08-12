#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Show what a website COW copy holds, and why the next version breaks it.

Read-only. Answers the two questions someone asks before neutralizing a copy,
and neither is answerable from the warning alone:

**What do I lose?** The copy is compared with the module view it shadows. That
is the customization someone made, and often it is three lines — an id, a
container width — for which nobody would hold up a migration.

**Why does it break?** The module declaration is shown in the current version
and in the target. The pair is the whole explanation: a template declared
without ``inherit_id`` is a standalone document, one declared with it must
hold inheritance specs. A copy frozen in the first shape cannot be applied in
the second, and Odoo stops on « cannot be located in parent view ».

Nothing here writes. Neutralizing is ``neutralize_cow_views.py --apply``, and
undoing it is ``--restore``.
"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from check_cow_views import analyse, find_module_dir  # noqa: E402

# The declaration of a template spans a few lines; showing the opening tag and
# what follows is enough to see its shape, and short enough to compare two
# versions side by side without scrolling.
DECL_LINES = 4


def run_psql(database, sql):
    """Run a statement and return stdout, raising on failure."""
    result = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAc", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Query failed on '{database}': {result.stderr.strip()}"
        )
    return result.stdout


def unwrap_arch(value):
    """The arch as text, whatever the column type.

    ``arch_db`` is text up to 15.0 and jsonb from 16.0. The same unwrapping as
    the sibling scripts, kept identical on purpose: a second reading of the
    same column that differs on an edge case would report a drift nobody made.
    """
    text = (value or "").strip()
    if text.startswith("{") and '"' in text:
        try:
            data = json.loads(text)
        except ValueError:
            return value or ""
        if isinstance(data, dict) and data:
            for lang in ("en_US", *sorted(data)):
                if isinstance(data.get(lang), str):
                    return data[lang]
    return value or ""


def fetch_arch(database, view_id):
    """The stored arch of one view."""
    return unwrap_arch(
        run_psql(
            database,
            f"SELECT arch_db::text FROM ir_ui_view WHERE id = {int(view_id)};",
        )
    )


def fetch_module_view(database, key):
    """(id, arch) of the module view a copy shadows, or (None, '').

    The module view is the one carrying that key WITHOUT a website: that is
    exactly the pairing Odoo itself makes, and the reason renaming a key is
    enough to unpair a copy.
    """
    safe = key.replace("'", "''")
    out = run_psql(
        database,
        "SELECT id, arch_db::text FROM ir_ui_view"
        f" WHERE key = '{safe}' AND website_id IS NULL"
        " ORDER BY id LIMIT 1;",
    ).strip()
    if not out:
        return None, ""
    view_id, _, arch = out.partition("|")
    return int(view_id), unwrap_arch(arch)


def declaration(version_dir, key):
    """(path, snippet) of how the sources of one version declare this key.

    Returns None when the module or the node is not found — a fact worth
    showing as such, since « the module no longer declares it » is itself a
    reason a copy breaks.
    """
    module_name, _, template_id = key.partition(".")
    if not template_id:
        return None
    module_dir = find_module_dir(version_dir, module_name)
    if module_dir is None:
        return None
    try:
        from lxml import etree
    except ImportError:
        return None

    pattern = os.path.join(module_dir, "**", "*.xml")
    import glob

    for path in sorted(glob.glob(pattern, recursive=True)):
        try:
            tree = etree.parse(path)
        except etree.XMLSyntaxError:
            continue
        for element in tree.getroot().iter():
            if element.get("id") != template_id:
                continue
            if element.tag not in ("template", "record"):
                continue
            # The source line, not a re-serialization: what the file actually
            # says is what a reader will grep for.
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
            start = max((element.sourceline or 1) - 1, 0)
            return path, "\n".join(lines[start : start + DECL_LINES])
    return None


def database_version_dir(database):
    """The odoo<x>.0 directory matching what the DATABASE says it is.

    Not `.odoo-version`: the checkout is switched to the TARGET before this
    runs, so reading it would compare the target with itself and show the same
    declaration twice — which is what it did until this was measured on a real
    migration. The database, at that moment, is still on the previous version
    and says so in ir_module_module.
    """
    try:
        out = run_psql(
            database,
            "SELECT latest_version FROM ir_module_module"
            " WHERE name = 'base';",
        ).strip()
    except RuntimeError:
        return None
    if not out:
        return None
    parts = out.split(".")
    if len(parts) < 2:
        return None
    return f"odoo{parts[0]}.{parts[1]}"


def collect(database, target_version, current_version=None):
    """Everything needed to judge each at-risk copy. No writes."""
    current_version = current_version or database_version_dir(database)
    lst_at_risk, _, _ = analyse(database, target_version)
    lst_finding = []
    for view_id, key, mode, target_mode, website_id, reason in lst_at_risk:
        module_id, module_arch = fetch_module_view(database, key)
        lst_finding.append(
            {
                "id": view_id,
                "key": key,
                "mode": mode,
                "target_mode": target_mode,
                "website_id": website_id,
                "reason": reason,
                "copy_arch": fetch_arch(database, view_id),
                "module_id": module_id,
                "module_arch": module_arch,
                "decl_current": (
                    declaration(current_version, key)
                    if current_version
                    else None
                ),
                "decl_target": declaration(target_version, key),
                "current_version": current_version,
                "target_version": target_version,
            }
        )
    return lst_finding


def render_diff(finding):
    """What the copy changed, compared with the module view it shadows."""
    lines = [
        f"── id={finding['id']} {finding['key']}"
        f" (website={finding['website_id']}) ──",
        "",
    ]
    if finding["module_id"] is None:
        lines += [
            "  No module view carries this key, so there is nothing to compare",
            "  against: this copy is a page made in the website editor.",
        ]
        return "\n".join(lines)

    left = finding["module_arch"].splitlines()
    right = finding["copy_arch"].splitlines()
    diff = [
        line
        for line in difflib.unified_diff(
            left,
            right,
            fromfile=f"module id={finding['module_id']}",
            tofile=f"copy id={finding['id']}",
            lineterm="",
            n=1,
        )
    ]
    if len(diff) <= 2:
        lines.append("  The copy is identical to the module view.")
        return "\n".join(lines)
    lines += [f"  {line}" for line in diff]
    n_plus = sum(
        1 for x in diff if x.startswith("+") and not x.startswith("+++")
    )
    n_minus = sum(
        1 for x in diff if x.startswith("-") and not x.startswith("---")
    )
    lines += [
        "",
        f"  {n_plus} line(s) added, {n_minus} removed — this is what"
        " neutralizing gives up.",
    ]
    return "\n".join(lines)


def render_shape(finding):
    """Why it breaks: the declaration in each version, side by side."""
    lines = [
        f"── id={finding['id']} {finding['key']} ──",
        "",
        f"  {finding['reason']}",
        "",
    ]
    for label, decl in (
        (finding["current_version"], finding["decl_current"]),
        (finding["target_version"], finding["decl_target"]),
    ):
        lines.append(f"  <!-- {label or '?'} -->")
        if decl is None:
            lines += [
                "      (the module no longer declares this template)",
                "",
            ]
            continue
        path, snippet = decl
        lines.append(f"  <!-- {path} -->")
        lines += [f"  {line}" for line in snippet.splitlines()]
        shape = (
            "inheritance specs (needs inherit_id)"
            if re.search(r"inherit_id\s*=", snippet)
            else "a standalone template"
        )
        lines += [f"      -> {shape}", ""]
    lines += [
        "  Odoo changing the shape of its own template is NOT the problem: on a",
        "  database without a copy, the module upgrade rewrites the view and",
        "  nothing breaks. It breaks here because a COPY exists and froze the",
        "  old shape — the copy follows the module and becomes an extension,",
        "  while still holding a standalone template. Odoo then applies that",
        "  template as an inheritance spec and stops on « cannot be located in",
        "  parent view ».",
        "",
    ]
    # Sans ceci, cette vue se lit comme « du code Odoo qui change », et l'on
    # se demande pourquoi c'est notre affaire. Ce qui la rend nôtre est ce que
    # la copie contient — la seule chose que neutraliser ferait perdre.
    lines += _what_the_copy_holds(finding)
    return "\n".join(lines)


def _what_the_copy_holds(finding):
    """Ce que la copie porte en propre, dit en une ou deux lignes.

    Relie les deux moitiés de la question : le mécanisme explique POURQUOI ça
    casse, ceci dit CE QU'IL EN COÛTE. Une copie identique à sa jumelle ne
    coûte rien, et le savoir change la décision.
    """
    if finding["module_id"] is None:
        return [
            "  This copy has no module view of that name: it is a page made in",
            "  the website editor, and nothing else holds its content.",
        ]
    left = finding["module_arch"].splitlines()
    right = finding["copy_arch"].splitlines()
    diff = [
        line
        for line in difflib.unified_diff(left, right, lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    if not diff:
        return [
            "  This copy is IDENTICAL to the module view it shadows: it holds no",
            "  customization at all, so neutralizing it loses nothing.",
        ]
    n_plus = sum(1 for x in diff if x.startswith("+"))
    n_minus = sum(1 for x in diff if x.startswith("-"))
    return [
        f"  This copy differs from the module view by +{n_plus}/-{n_minus}"
        " line(s):",
        "  that is the customization, and all that neutralizing gives up.",
        "  Run without --shape to read it.",
    ]


def render_all(lst_finding, shape=False):
    """The whole report, one block per finding."""
    if not lst_finding:
        return "✅ No website COW view is at risk.\n"
    render = render_shape if shape else render_diff
    return "\n\n".join(render(f) for f in lst_finding) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Show what each at-risk website COW copy holds, and why the next"
            " version breaks it (read-only)."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "-t",
        "--target_version",
        required=True,
        help="target Odoo source directory, e.g. odoo13.0",
    )
    parser.add_argument(
        "--current",
        default=None,
        help="current Odoo source directory (default: from .odoo-version)",
    )
    parser.add_argument(
        "--shape",
        action="store_true",
        help="show the declarations instead of the customization diff",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="browse full screen, switching between the two views",
    )
    config = parser.parse_args(argv)

    if not os.path.isdir(config.target_version):
        print(f"❌ Target version '{config.target_version}' not found.")
        return 2
    try:
        lst_finding = collect(
            config.database, config.target_version, config.current
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2

    if config.tui and lst_finding:
        from cow_drift_tui import run_tui

        if run_tui(lst_finding):
            return 1
    print(render_all(lst_finding, shape=config.shape))
    return 1 if lst_finding else 0


if __name__ == "__main__":
    sys.exit(main())
