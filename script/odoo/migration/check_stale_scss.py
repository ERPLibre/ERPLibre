#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Predict which customized SCSS will break the next version bump.

Background
----------
Customizing a website writes SCSS into ``ir_attachment``: files whose URL
carries ``.custom.``. That copy is frozen the day it is written, and it keeps
using the variables of THAT version.

A module can rename its variables between two Odoo versions. Measured on a
real database: ``website/static/src/scss/primary_variables.scss`` declared
``$o-theme-font-number`` in 12.0 and replaced the whole mechanism in 13.0 with
a ``$o-website-values-palettes`` map. A customization written in 2020 still
asked for the old name. The bundle then stops on::

    Error: Undefined variable: "$o-theme-font-number".
    This error occured while compiling the bundle 'web.assets_frontend'

So the rule is the same as for COW views:

    a customization breaks when what it USES stops being DEFINED between
    version N and version N+1.

Why not just start Odoo and open a page
---------------------------------------
Because that only tells you *after* the bump, on a page that renders a
« Style error » with no name attached: not which attachment, not which
variable, not since when. And a page has to be reached at all — a broken
frontend bundle is exactly when it is not.

Reading the stored SCSS against the target sources answers before the bump,
in a second, and names the attachment. Nothing is written here.

What it can miss
----------------
Which files a bundle really contains is decided by Odoo at runtime. This
compares against every SCSS of the INSTALLED modules of the target version,
which is wider: a variable defined in a module file that the bundle does not
include would be counted as defined. That direction is deliberate — it under-
reports rather than crying wolf on every customization.

Exit codes: 0 nothing to report, 1 customizations at risk, 2 tool failure.
"""

import argparse
import glob
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


# Une variable SCSS commence par $ ; celles dont le nom commence par un tiret
# sont locales au fichier par convention Odoo ($-seen, $-font-numbers) et se
# définissent toujours au-dessus de leur usage.
RE_ANY = re.compile(r"\$([a-zA-Z][\w-]*)")


def used_names(content):
    """Noms LUS par le fichier, sans les liaisons.

    Un « $nom » suivi d'un deux-points est toujours une liaison — déclaration,
    valeur par défaut, ou argument nommé d'un @include — jamais la lecture
    d'une variable. Sans cette réserve, « @include o-position-absolute(
    $right: 50%) » se lisait comme l'usage d'un $right inexistant.

    Le test se fait ici et non par une négation dans le motif : une négation
    en tête de motif fait rétrograder le nom pour satisfaire la condition, et
    rapporte « $botto » au lieu d'écarter « $bottom ». Mesuré.
    """
    names = set()
    for match in RE_ANY.finditer(content):
        if content[match.end() :].lstrip(" \t").startswith(":"):
            continue
        names.add(match.group(1))
    return names


RE_DEF = re.compile(r"^\s*\$([a-zA-Z][\w-]*)\s*:", re.M)

# Une variable peut aussi être LIÉE sans être définie : paramètre de mixin ou
# de fonction, variable de boucle. Les ignorer donnait six faux positifs sur
# le seul fichier mesuré — $bottom, $counter, $off, $on, $right, $value — et
# un détecteur qui crie à tort finit ignoré, ce qui vaut moins que rien.
RE_PARAM = re.compile(r"@(?:mixin|function)\s+[\w-]+\s*\(([^)]*)\)")
RE_EACH = re.compile(r"@each\s+([^i]+?)\s+in\s", re.S)
RE_FOR = re.compile(r"@for\s+\$([\w-]+)\s+from\s")


def bound_names(content):
    """Noms liés par le fichier lui-même, hors définitions « $x: … »."""
    names = set()
    for group in RE_PARAM.findall(content):
        names.update(RE_ANY.findall(group))
    for group in RE_EACH.findall(content):
        names.update(RE_ANY.findall(group))
    names.update(RE_FOR.findall(content))
    return names


def run_psql(database, sql):
    """Interroger la base, lecture seule garantie par le serveur."""
    env = os.environ.copy()
    env["PGOPTIONS"] = (
        "-c default_transaction_read_only=on -c statement_timeout=60000"
    )
    env["PSQLRC"] = ""
    done = subprocess.run(
        [
            "psql",
            "-X",
            "-w",
            "-v",
            "ON_ERROR_STOP=1",
            "-d",
            database,
            "-tAF",
            "\x1f",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or "psql failed")
    return [line.split("\x1f") for line in done.stdout.splitlines() if line]


def filestore_dir(database, override=None):
    if override:
        return override
    return os.path.join(
        os.path.expanduser("~"),
        ".local",
        "share",
        "Odoo",
        "filestore",
        database,
    )


def custom_scss(database, filestore):
    """[(id, url, contenu)] pour chaque SCSS personnalisé lisible."""
    rows = run_psql(
        database,
        "SELECT id, url, COALESCE(store_fname, ''),"
        " COALESCE(encode(db_datas, 'escape'), '') FROM ir_attachment"
        " WHERE url LIKE '%.custom.%' AND url NOT LIKE '%.css'"
        " ORDER BY id;",
    )
    lst = []
    for row in rows:
        if len(row) < 4:
            continue
        att_id, url, store_fname, db_datas = row[0], row[1], row[2], row[3]
        content = ""
        if store_fname:
            path = os.path.join(filestore, store_fname)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as h:
                    content = h.read()
        elif db_datas:
            content = db_datas
        if content:
            lst.append((int(att_id), url, content))
    return lst


def installed_modules(database):
    return {
        row[0]
        for row in run_psql(
            database,
            "SELECT name FROM ir_module_module WHERE state = 'installed';",
        )
        if row and row[0]
    }


def defined_in_sources(version_dir, lst_module):
    """Variables définies par les SCSS des modules installés de la cible.

    Le nom du module est le répertoire qui contient « static » : c'est ce qui
    permet de ne pas compter les variables d'un module absent de la base, dont
    aucune ligne n'atteindra jamais un bundle.
    """
    defined = set()
    pattern = os.path.join(version_dir, "**", "static", "**", "*.scss")
    for path in glob.iglob(pattern, recursive=True):
        parts = path.split(os.sep)
        try:
            module = parts[parts.index("static") - 1]
        except (ValueError, IndexError):
            continue
        if module not in lst_module:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                defined.update(RE_DEF.findall(handle.read()))
        except OSError:
            continue
    return defined


def analyse(database, version_dir, filestore=None):
    """[(id, url, [variables absentes])] pour les personnalisations à risque."""
    filestore = filestore_dir(database, filestore)
    lst_module = installed_modules(database)
    defined = defined_in_sources(version_dir, lst_module)
    lst_finding = []
    for att_id, url, content in custom_scss(database, filestore):
        own = set(RE_DEF.findall(content)) | bound_names(content)
        missing = sorted(
            {
                name
                for name in used_names(content)
                if name not in own and name not in defined
            }
        )
        if missing:
            lst_finding.append((att_id, url, missing))
    return lst_finding


def render(lst_finding, database, version_dir):
    if not lst_finding:
        return (
            f"✅ -> {t('No customized SCSS is at risk in')} {version_dir}.\n"
        )
    lines = [
        f"⚠️ {len(lst_finding)}"
        f" {t('customized SCSS use(s) a variable that')} {version_dir}"
        f" {t('no longer defines: the bundle will not compile.')}"
    ]
    for att_id, url, missing in lst_finding:
        lines.append(f"   - id={att_id} {url}")
        lines.append(f"       {', '.join('$' + m for m in missing)}")
    lines += [
        f"   {t('Each one is a copy frozen on an older version. Dropping it')}"
        f" {t('restores the module file:')}",
        f"     ./odoo_bin.sh shell -c ./config.conf -d {database} <<'PY'",
    ]
    for _att_id, url, _missing in lst_finding:
        base, bundle = split_custom_url(url)
        lines.append(
            f"     env['web_editor.assets'].reset_asset("
            f"'{base}', '{bundle}')"
        )
    lines += [
        "     env.cr.commit()",
        "     PY",
        f"   {t('Read it first: what it holds beyond the stale variable is')}"
        f" {t('a real customization, to re-apply as a small file.')}",
    ]
    return "\n".join(lines) + "\n"


def split_custom_url(url):
    """« /a/b.custom.web.assets_frontend.scss » -> (« /a/b.scss », bundle).

    C'est la convention d'Odoo : le nom du bundle est encastré dans celui du
    fichier. La reconstruire évite de faire deviner à l'utilisateur les deux
    arguments de reset_asset au moment où il veut juste réparer.
    """
    directory, name = os.path.split(url)
    head, _sep, tail = name.partition(".custom.")
    bundle = tail[:-5] if tail.endswith(".scss") else tail
    return os.path.join(directory, head + ".scss"), bundle


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Predict which customized SCSS will break on the target version"
            " (read-only)."
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
        "--filestore",
        default=None,
        help="filestore directory (default: ~/.local/share/Odoo/filestore/<db>)",
    )
    config = parser.parse_args(argv)

    if not os.path.isdir(config.target_version):
        print(
            f"❌ {t('Target version directory not found')} :"
            f" '{config.target_version}'"
        )
        return 2
    try:
        lst_finding = analyse(
            config.database, config.target_version, config.filestore
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    print(render(lst_finding, config.database, config.target_version))
    return 1 if lst_finding else 0


if __name__ == "__main__":
    sys.exit(main())
