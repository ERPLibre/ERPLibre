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


def module_file(base_url, version_dir):
    """Le fichier du module que la personnalisation masque, ou None.

    Le premier segment de l'URL est le nom du module ; le reste est son
    chemin. C'est ce fichier que reset_asset rendrait, donc c'est contre lui
    que se lit ce que la copie a réellement changé.
    """
    parts = base_url.strip("/").split("/")
    if len(parts) < 2:
        return None
    pattern = os.path.join(version_dir, "**", parts[0], *parts[1:])
    for candidate in glob.iglob(pattern, recursive=True):
        if os.path.isfile(candidate):
            return candidate
    return None


def analyse(database, version_dir, filestore=None):
    """Un dictionnaire par personnalisation à risque.

    Le contenu et le fichier du module y sont joints : l'appelant qui veut
    montrer l'écart ne doit pas relire la base ni retrouver le chemin.
    """
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
        if not missing:
            continue
        base_url, bundle = split_custom_url(url)
        path = module_file(base_url, version_dir)
        module_content = ""
        if path:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                module_content = handle.read()
        lst_finding.append(
            {
                "id": att_id,
                "url": url,
                "missing": missing,
                "custom": content,
                "base_url": base_url,
                "bundle": bundle,
                "module_path": path,
                "module_content": module_content,
                "version_dir": version_dir,
                "database": database,
            }
        )
    return lst_finding


def render_diff(finding):
    """Ce que la copie a changé, comparée au fichier du module de la cible.

    C'est la seule chose qu'abandonner la copie ferait perdre. Sans elle, on
    répond « oui, réinitialise » sans savoir si l'on jette trois lignes ou
    une page entière.
    """
    import difflib

    lines = [
        f"── id={finding['id']} {finding['url']} ──",
        "",
        f"  {t('Missing:')} "
        + ", ".join("$" + name for name in finding["missing"]),
        "",
    ]
    if not finding["module_path"]:
        lines += [
            f"  {t('No module file of that name in')}"
            f" {finding['version_dir']} :",
            f"  {t('the target no longer ships it, so there is nothing to')}",
            f"  {t('fall back on. Read the copy before dropping it.')}",
        ]
        return "\n".join(lines)
    diff = list(
        difflib.unified_diff(
            finding["module_content"].splitlines(),
            finding["custom"].splitlines(),
            fromfile=finding["module_path"],
            tofile=f"custom id={finding['id']}",
            lineterm="",
            n=2,
        )
    )
    if len(diff) <= 2:
        lines.append(f"  {t('The copy is identical to the module file.')}")
        return "\n".join(lines)
    lines += [f"  {line}" for line in diff]
    plus = sum(1 for x in diff if x[:1] == "+" and not x.startswith("+++"))
    minus = sum(1 for x in diff if x[:1] == "-" and not x.startswith("---"))
    lines += [
        "",
        f"  +{plus}/-{minus} {t('line(s): that is what resetting gives up.')}",
    ]
    return "\n".join(lines)


def reset_command(lst_finding, database, config_path="./config.conf"):
    """La commande qui rend les fichiers de module. Rien n'est lancé ici."""
    lines = [f"./odoo_bin.sh shell -c {config_path} -d {database} <<'PY'"]
    for finding in lst_finding:
        lines.append(
            "env['web_editor.assets'].reset_asset"
            f"('{finding['base_url']}', '{finding['bundle']}')"
        )
    lines += ["env.cr.commit()", "PY"]
    return "\n".join(lines)


def apply_reset(lst_finding, database, config_path="./config.conf"):
    """Rendre les fichiers de module. ÉCRIT en base — le seul endroit ici.

    Réversible seulement au sens où la personnalisation peut être réécrite :
    reset_asset supprime la pièce jointe. D'où la sauvegarde préalable, qui
    n'est pas une politesse mais la condition pour dire « oui » sans risque.
    """
    script = "\n".join(
        "env['web_editor.assets'].reset_asset"
        f"('{f['base_url']}', '{f['bundle']}')"
        for f in lst_finding
    )
    done = subprocess.run(
        ["./odoo_bin.sh", "shell", "-c", config_path, "-d", database],
        input=script + "\nenv.cr.commit()\n",
        capture_output=True,
        text=True,
    )
    return done.returncode, done.stdout + done.stderr


def backup_custom(lst_finding, database):
    """Écrire les copies sur disque AVANT de les abandonner.

    reset_asset supprime la pièce jointe : sans ceci, les lignes réellement
    personnalisées ne seraient plus nulle part.
    """
    directory = os.path.join(
        "private", "odoo", "migration", database, "scss_backup"
    )
    os.makedirs(directory, exist_ok=True)
    lst_path = []
    for finding in lst_finding:
        name = f"{finding['id']}_" + finding["url"].strip("/").replace(
            "/", "_"
        )
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(finding["custom"])
        lst_path.append(path)
    return lst_path


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
    for finding in lst_finding:
        lines.append(f"   - id={finding['id']} {finding['url']}")
        lines.append(
            "       " + ", ".join("$" + name for name in finding["missing"])
        )
    lines += [
        f"   {t('Each one is a copy frozen on an older version. Dropping it')}"
        f" {t('restores the module file:')}",
    ]
    lines += [
        "     " + line
        for line in reset_command(lst_finding, database).splitlines()
    ]
    lines.append(
        f"   {t('Read it first: what it holds beyond the stale variable is')}"
        f" {t('a real customization, to re-apply as a small file.')}"
    )
    return "\n".join(lines) + "\n"


def prompt(lst_finding, database, config_path="./config.conf", ask=input):
    """Montrer, puis proposer de corriger. Rend True si l'on a écrit.

    Répondre « oui, réinitialise » sans avoir vu l'écart, c'est accepter de
    perdre on ne sait quoi. L'invite revient donc après chaque lecture :
    regarder ne répond pas à la question.
    """
    while True:
        answer = (
            ask(
                f"💬 {t('What do you want to do with these customizations?')}"
                f" ({t('Enter = nothing')},"
                f" v = {t('what the copy changed')},"
                f" w = {t('full screen')},"
                f" a = {t('reset them onto the module file')}) : "
            )
            .strip()
            .lower()
        )
        if answer == "v":
            for finding in lst_finding:
                print(render_diff(finding))
                print()
            continue
        if answer == "w":
            try:
                from check_stale_scss_tui import run_tui
            except ImportError:
                print(f"ℹ️  {t('Full screen view unavailable.')}")
                continue
            if not run_tui(lst_finding):
                for finding in lst_finding:
                    print(render_diff(finding))
            continue
        if answer == "a":
            lst_path = backup_custom(lst_finding, database)
            print(f"📦 {t('Saved before resetting')} :")
            for path in lst_path:
                print(f"   {path}")
            status, output = apply_reset(lst_finding, database, config_path)
            print(output.strip()[-2000:])
            if status:
                print(f"❌ {t('Reset failed, nothing was changed.')}")
                return False
            print(f"✅ -> {t('Reset done.')}")
            return True
        return False


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
            "Predict which customized SCSS will break on the target version."
            " Read-only unless --apply."
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
    parser.add_argument(
        "-c",
        "--config",
        default="./config.conf",
        help="Odoo config used by the shell for --apply",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="print what each copy changed, without asking",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="browse the differences full screen",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="reset them onto the module file (WRITES; saves a copy first)",
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
    if not lst_finding:
        return 0

    if config.diff:
        for finding in lst_finding:
            print(render_diff(finding))
            print()
    if config.tui:
        from check_stale_scss_tui import run_tui

        if not run_tui(lst_finding):
            for finding in lst_finding:
                print(render_diff(finding))
    if config.apply:
        lst_path = backup_custom(lst_finding, config.database)
        print(f"📦 {t('Saved before resetting')} :")
        for path in lst_path:
            print(f"   {path}")
        status, output = apply_reset(
            lst_finding, config.database, config.config
        )
        print(output.strip()[-2000:])
        if status:
            print(f"❌ {t('Reset failed, nothing was changed.')}")
            return 2
        print(f"✅ -> {t('Reset done.')}")
        return 0

    # Aucun drapeau : on demande, plutôt que d'imprimer un rapport et de
    # laisser retrouver soi-même les deux arguments de reset_asset. Mais
    # seulement devant un terminal — dans un tube, une invite bloquerait
    # l'appelant sans que personne ne voie la question.
    if not (config.diff or config.tui) and sys.stdin.isatty():
        if prompt(lst_finding, config.database, config.config):
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
