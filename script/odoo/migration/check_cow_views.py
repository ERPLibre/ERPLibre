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

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


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


def run_sql(database, sql):
    """Le texte brut d'une requête. RuntimeError si la base ne répond pas."""
    result = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tA", "-c", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"Cannot read '{database}': {result.stderr.strip()}"
        )
    return result.stdout


def query_cow_archs(database):
    """[(id, clé, mode, website_id, {langue: arch})] — arch ENTIÈRES.

    `query_cow_views` tronque à 400 caractères : assez pour lire la
    première balise, pas pour évaluer un xpath — un fragment coupé n'est
    même pas du XML. Et `arch_db` est un jsonb par langue depuis la 17 :
    une page cassée en fr_CA et saine en en_US, cela existe, on l'a vu.
    """
    jsonb = "jsonb" in run_sql(
        database,
        "SELECT data_type FROM information_schema.columns"
        " WHERE table_name='ir_ui_view' AND column_name='arch_db'",
    )
    expr = "arch_db" if jsonb else "json_build_object('', arch_db)"
    brut = run_sql(
        database,
        "SELECT coalesce(json_agg(json_build_object("
        "'id', id, 'key', coalesce(key, ''), 'mode', mode,"
        f" 'website_id', website_id, 'arch', {expr})), '[]')"
        " FROM ir_ui_view WHERE website_id IS NOT NULL",
    )
    try:
        lignes = json.loads(brut.strip() or "[]")
    except ValueError:
        return []
    return [
        (
            ligne["id"],
            ligne["key"],
            ligne["mode"],
            ligne["website_id"],
            ligne["arch"] if isinstance(ligne["arch"], dict) else {},
        )
        for ligne in lignes
    ]


def installed_modules(database):
    """Les modules installés. Sans eux le balayage des sources est vain.

    Un enfant peut vivre dans N'IMPORTE quel module — `website_crm` hérite
    de `website.contactus` — donc il faut balayer large. Mais balayer TOUT
    l'arbre cible coûterait des milliers de fichiers pour rien : seuls les
    modules installés produiront des vues.
    """
    output = run_sql(
        database,
        "SELECT name FROM ir_module_module WHERE state IN"
        " ('installed', 'to upgrade')",
    )
    return [ligne.strip() for ligne in output.splitlines() if ligne.strip()]


def full_key(module_name, valeur):
    """« contactus » dans le module website devient « website.contactus »."""
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    return valeur if "." in valeur else f"{module_name}.{valeur}"


def scan_target_views(target_version, lst_module):
    """(déclarés, héritages) tels que la version CIBLE les livre.

    `déclarés` : les clés de gabarit que la cible fournit. Sert à repérer
    un `t-call` vers un gabarit qui n'existe plus.

    `héritages` : {clé parente: [expressions xpath]}. C'est le manque qui
    a coûté quatre paliers de silence — la cible ajoute un ancrage dans
    une vue module, sa vue héritière le vise, et la copie de site, qui
    n'est jamais réécrite, ne l'a pas.
    """
    declares = set()
    heritages = {}
    for module_name in lst_module:
        module_dir = find_module_dir(target_version, module_name)
        if module_dir is None:
            continue
        motif = os.path.join(module_dir, "**", "*.xml")
        for file_path in sorted(glob.glob(motif, recursive=True)):
            try:
                racine = ET.parse(file_path).getroot()
            except ET.ParseError:
                continue
            for element in racine.iter("template"):
                cle = full_key(module_name, element.get("id"))
                if cle:
                    declares.add(cle)
                parent = full_key(module_name, element.get("inherit_id"))
                if not parent:
                    continue
                exprs = [
                    noeud.get("expr")
                    for noeud in element.iter("xpath")
                    if noeud.get("expr")
                ]
                if exprs:
                    heritages.setdefault(parent, []).extend(exprs)
    return declares, heritages


def will_not_render(database, target_version):
    """Les copies qui passeront la migration et rendront 500 ensuite.

    Deux ruptures que `analyse` ne voit pas, parce qu'elles ne touchent
    pas la FORME de la copie :

      ancrage manquant   un enfant de la CIBLE vise `//t[@t-set='x']` que
                         la copie n'a pas.
      t-call pendant     la copie appelle un gabarit que la cible ne
                         livre plus.

    Celles-là ne se neutralisent PAS : la copie porte une page écrite par
    quelqu'un, et la mettre de côté l'effacerait du site. Elles se
    réparent — `fix_cow_render.py` remet l'ancrage depuis la vue module
    et retire l'appel mort, sans toucher au contenu.
    """
    from fix_cow_render import dangling_calls, locates

    copies = query_cow_archs(database)
    if not copies:
        return []
    declares, heritages = scan_target_views(
        target_version, installed_modules(database)
    )
    connus = declares | {cle for _i, cle, _m, _w, _a in copies if cle}
    risques = []
    for view_id, key, mode, website_id, langues in copies:
        if not key:
            continue
        # Chaque langue : une page peut être cassée en fr_CA et saine en
        # en_US, et c'est celle du site qui décide de ce qu'on voit.
        manques = set()
        pendants = []
        for texte in langues.values():
            for expr in heritages.get(key, []):
                if not locates(texte, expr):
                    manques.add(expr)
            for nom in dangling_calls(texte, connus):
                if nom not in pendants:
                    pendants.append(nom)
        for expr in sorted(manques):
            risques.append(
                (
                    view_id,
                    key,
                    mode,
                    mode,
                    website_id,
                    f"a child of the target needs an anchor this copy lacks:"
                    f" {expr}",
                )
            )
        for nom in pendants:
            risques.append(
                (
                    view_id,
                    key,
                    mode,
                    mode,
                    website_id,
                    f"calls a template the target no longer ships: {nom}",
                )
            )
    return risques


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
            # La clé anglaise est stockée, la traduction se fait à
            # l'affichage : cow_drift et neutralize la relisent, et une
            # valeur déjà traduite les obligerait à traduire en sens inverse.
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
            f"❌ {t('Target version directory not found')} :"
            f" '{config.target_version}'"
        )
        return 2

    lst_at_risk, lst_module_absent, lst_no_counterpart = analyse(
        config.database, config.target_version
    )
    # L'autre famille de rupture : la copie garde sa forme et cesse de se
    # RENDRE. Elle ne se neutralise pas — la copie porte une page écrite
    # par quelqu'un — elle se répare.
    lst_no_render = will_not_render(config.database, config.target_version)
    database = config.database
    target_version = config.target_version

    if lst_no_render:
        print(
            f"⚠️ {len(lst_no_render)}"
            f" {t('website COW view(s) will survive the bump and then fail')}"
            f" {t('to render:')}"
        )
        for view_id, key, _mode, _cible, website_id, raison in lst_no_render:
            print(f"   - id={view_id} website={website_id} {key}")
            print(f"     {t(raison)}")
        print(
            f"   {t('Repair rather than neutralize — the copy holds a page')}"
            f" {t('someone wrote:')}"
            f" ./script/odoo/migration/fix_cow_render.py -d {config.database}"
        )
        print("")

    if not lst_at_risk:
        print(
            f"✅ -> {t('No website COW view changes shape in')}"
            f" {config.target_version}."
        )
    else:
        print(
            f"⚠️ {len(lst_at_risk)}"
            f" {t('website COW view(s) will break when moving to')}"
            f" {config.target_version} :"
            f" {t('the copy keeps an arch whose shape no longer matches what')}"
            f" {t('the target module view expects.')}"
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
                f" : {mode} -> {target_mode} ({t(reason)})"
            )
        # La base et la version cible sont connues ici : les remplacer par
        # « DB » et « odooXX.0 » oblige à les retrouver, au moment précis où
        # l'on veut juste copier-coller la commande.
        print(
            f"   {t('The migration offers to neutralize them, and shows what')}"
            f" {t('each copy holds before you answer. To look now:')}"
            f"\n     ./script/odoo/migration/cow_drift.py -d {database}"
            f" -t {target_version}          ({t('what each copy holds')})"
            f"\n     ./script/odoo/migration/cow_drift.py -d {database}"
            f" -t {target_version} --shape  ({t('why it breaks')})"
            f"\n     ./script/odoo/migration/neutralize_cow_views.py"
            f" -d {database} -t {target_version} --apply"
            f"   ({t('reversible with --restore')})"
        )
        print(
            f"   {t('Or by hand. To neutralize a copy, rename its key')}"
            " (UPDATE ir_ui_view SET key='zz_cow_archive.'||key,"
            f" active=false) : {t('an unmatched key is never paired with the')}"
            f" {t('module view, so the copy never receives the new')}"
            f" inherit_id. {t('Setting active=false alone is NOT enough:')}"
            f" {t('an inactive copy keeping the same key still shadows it.')}"
        )

    if lst_module_absent:
        print(
            f"ℹ {len(lst_module_absent)}"
            f" {t('COW view(s) belong to a module absent from')}"
            f" {config.target_version} :"
        )
        for view_id, key, mode, website_id in lst_module_absent:
            print(f"   - id={view_id} website={website_id} {key} ({mode})")

    if lst_no_counterpart:
        print(
            f"ℹ {len(lst_no_counterpart)}"
            f" {t('COW view(s) are pages or records made in the website')}"
            f" {t('editor (no module view of that name): not at risk.')}"
            + ("" if config.verbose else f" {t('Use -v to list them.')}")
        )
        if config.verbose:
            for view_id, key, mode, website_id in lst_no_counterpart:
                print(f"   - id={view_id} website={website_id} {key} ({mode})")

    # 0 = rien à signaler, 1 = des copies casseront, 2 = l'outil a échoué.
    # Le pilote lisait le texte anglais de cette sortie pour savoir s'il
    # devait poser sa question : traduire le message le rendait aveugle.
    # Les deux familles comptent : une copie qui rendra 500 est une
    # trouvaille, même si la migration, elle, ne s'arrêtera pas.
    return 1 if (lst_at_risk or lst_no_render) else 0


if __name__ == "__main__":
    sys.exit(main())
