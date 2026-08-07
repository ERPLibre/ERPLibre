#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Inventaire des vues personnalisées d'une base Odoo, copies COW comprises.

Ce que l'outil répond : parmi les milliers de vues d'une base, lesquelles ne
viennent pas telles quelles d'un module. Ce sont elles qu'une montée de version
peut casser, et elles seules qu'un intégrateur doit relire.

Ce qu'il ne répond PAS encore
-----------------------------
Il ne compare pas l'arch en base à celle que déclare le module. Une vue portant
le drapeau ``arch_updated`` est donc dite **signalée**, pas **modifiée** : le
drapeau vient d'Odoo, mais il est incomplet dans les deux sens — un ``write``
SQL direct ne l'arme pas, et ``reset_arch(mode='hard')`` l'efface. Conclure
demande de comparer, ce que fera l'outil suivant. Nommer « modifiée » ce qui
n'est que « signalée » serait une affirmation que rien ici ne soutient.

Les copies COW, et ce qui les distingue de l'outillage existant
---------------------------------------------------------------
Personnaliser une vue de site web ne la modifie pas : Odoo en fait une copie
liée à un ``website_id``. Quatre outils du dépôt s'en occupent déjà, chacun
pour une question de MIGRATION — ``check_cow_views.py`` prédit lesquelles
casseront à la version suivante, ``reset_stale_cow_views.py`` trouve celles qui
ont dérivé de leur jumelle et sait les réinitialiser, ``neutralize_cow_views.py``
les met hors circuit, ``snapshot_cow_views.py`` compare un avant et un après.

Aucun ne fait l'inventaire, et c'est le trou que celui-ci comble : combien de
vues sont personnalisées, par quel chemin, et lesquelles méritent un regard.
Il ne rejuge donc pas les copies COW — il les compte, dit si chacune a une
jumelle module, et renvoie vers l'outil qui tranche.

Une vue, une seule catégorie
----------------------------
Une copie COW peut aussi porter ``arch_updated`` ; une vue Studio peut être une
copie COW. Les classer plusieurs fois ferait un total supérieur au nombre de
vues, et un rapport dont les chiffres ne s'additionnent pas ne se lit pas. La
catégorie retenue est donc la plus spécifique, dans l'ordre de ``CATEGORIES``,
et le reste de ce qu'on sait vit dans ``reason``.
"""

import argparse
import json
import os
import sys
import textwrap

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.analyse.lib_analyse import (  # noqa: E402
    REPO_ROOT,
    AnalyseError,
    arch_differs,
    column_types,
    diff_stats,
    existing_columns,
    json_query,
    odoo_shell_json,
    require_odoo_database,
    scalar_query,
    side_by_side,
    t,
    tr_col,
)

# Le script poussé dans « odoo-bin shell » pour obtenir l'arch de référence.
SHELL_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "shell", "view_file_arch.py"
)

# Le registre se charge par lots : la ligne de commande et la sortie restent
# bornées, et une vue cassée n'emporte que son lot.
BATCH = 100

# Modules d'identifiants externes qui ne sont pas des modules : Odoo y range ce
# qui vient d'un import, d'un export, ou de Studio.
STUDIO_MODULE = "studio_customization"
NOT_A_MODULE = ("__export__", "__import__", "__custom__")

# L'ordre EST la précédence : la première catégorie qui s'applique gagne. Du
# plus spécifique au plus général, pour qu'une vue Studio copiée par le site web
# soit comptée comme copie COW — c'est ce qu'un intégrateur ira regarder en
# premier — et non comme une vue Studio de plus.
CATEGORIES = (
    "theme_installed",
    "website_cow_copy",
    "studio",
    "imported_or_exported",
    "ui_created",
    "module_view_drifted",
    "module_view_flagged",
    "module_view",
)

# Les catégories qui demandent un regard. « module_view » n'y est pas : une vue
# qui vient d'un module et que rien ne signale est le cas normal, et il compte
# pour l'écrasante majorité.
ACTIONABLE = (
    "module_view_drifted",
    "module_view_flagged",
    "ui_created",
    "studio",
    "imported_or_exported",
    "website_cow_copy",
    "theme_installed",
)

TOP_DEFAULT = 20


def wrap_note(prefix, text, width=79):
    """Replier une phrase à l'affichage, sans la découper en clés."""
    lines = textwrap.wrap(text, width=width - len(prefix)) or [""]
    pad = " " * len(prefix)
    return [prefix + lines[0]] + [pad + line for line in lines[1:]]


def category_label(name):
    """Libellé traduit d'une catégorie.

    Un `t(variable)` serait plus court, mais il rendrait le contrôle de
    couverture aveugle : celui-ci relit les sources et ne voit que les appels
    à littéral. Une clé manquante repasserait alors en silence, en anglais.
    Les catégories sont donc épelées, une par une.
    """
    return {
        "theme_installed": t("From an installed theme"),
        "website_cow_copy": t("Website copy (COW)"),
        "studio": t("Made with Studio"),
        "imported_or_exported": t("Imported or exported"),
        "ui_created": t("Created from the interface"),
        "module_view_drifted": t("From a module, silently drifted"),
        "module_view_flagged": t("From a module, flagged as touched"),
        "module_view": t("Straight from a module"),
    }.get(name, name)


def classify(row):
    """(catégorie, raisons) d'une vue. Fonction pure, testable sur fixture.

    ``raisons`` porte tout ce qu'on sait et que la catégorie ne dit pas : une
    copie COW qui est aussi signalée le mentionne, sinon l'information se
    perdrait au profit de la seule catégorie retenue.
    """
    lst_module = row.get("xmlid_modules") or []
    has_xmlid = bool(lst_module)
    lst_reason = []

    if row.get("arch_updated"):
        lst_reason.append("arch_updated")
    if row.get("noupdate"):
        lst_reason.append("noupdate")
    if row.get("has_arch_prev"):
        lst_reason.append("has_arch_prev")
    if not row.get("active"):
        lst_reason.append("inactive")

    if row.get("theme_template_id"):
        return "theme_installed", lst_reason
    if row.get("website_id"):
        if not row.get("has_module_twin"):
            lst_reason.append("no_module_twin")
        return "website_cow_copy", lst_reason
    if STUDIO_MODULE in lst_module:
        return "studio", lst_reason
    if any(module in NOT_A_MODULE for module in lst_module):
        return "imported_or_exported", lst_reason
    if not has_xmlid and not row.get("arch_fs"):
        return "ui_created", lst_reason
    # `arch_updated` SEUL fait basculer une vue de module. `noupdate` reste une
    # raison, jamais un motif : toute vue déclarée dans un bloc
    # <odoo noupdate="1"> le porte — les données de mail, d'account, de website
    # en sont pleines — et rien n'y a été touché. L'y inclure noierait la
    # catégorie qui compte sous des centaines de vues parfaitement normales.
    if row.get("arch_fs") and row.get("arch_updated"):
        return "module_view_flagged", lst_reason
    return "module_view", lst_reason


def _view_rows(database, **kwargs):
    """Une ligne par vue, sans son arch.

    L'arch n'est pas rapatriée : quelques milliers de vues dont certaines
    dépassent 100 ko tiendraient dans une seule ligne de sortie psql, dupliquée
    par json.loads. La taille et l'empreinte suffisent à cet inventaire ; la
    comparaison, qui a besoin du contenu, ira le chercher pour les seules vues
    retenues.

    Les identifiants externes sont AGRÉGÉS. Une jointure plate multiplierait
    les lignes d'une vue qui en porte plusieurs, et un « premier trouvé »
    déciderait au hasard si elle vient de Studio.
    """
    cols = existing_columns(database, "ir_ui_view", **kwargs)
    dct_type = column_types(database, "ir_ui_view", **kwargs)

    def col(column, absent):
        """« v.colonne » si elle existe, sinon un littéral du bon type.

        Toutes les colonnes passent par ici, y compris celles qu'on croit
        acquises comme create_uid : sur une base rognée ou anonymisée, une
        seule colonne manquante fait échouer la requête entière, et l'outil
        rendrait 2 là où il pouvait encore répondre.
        """
        return f"v.{column}" if column in cols else absent

    name = tr_col("v", "name", dct_type)
    has_website_col = "website_id" in cols
    website = col("website_id", "NULL::integer")
    # La CTE « twin » n'a pas l'alias « v » : il lui faut la colonne nue. Sans
    # le module website, il n'y a aucune copie COW et toute vue à clé est sa
    # propre référence — d'où le « TRUE ».
    twin_filter = "website_id IS NULL" if has_website_col else "TRUE"
    theme = col("theme_template_id", "NULL::integer")
    arch_fs = col("arch_fs", "NULL::text")
    arch_updated = col("arch_updated", "false")
    arch_prev = "(v.arch_prev IS NOT NULL)" if "arch_prev" in cols else "false"
    return json_query(
        database,
        f"""
        WITH xid AS (
          SELECT res_id,
                 array_agg(DISTINCT module)                    AS modules,
                 array_agg(module || '.' || name ORDER BY module, name)
                                                               AS xmlids,
                 bool_or(noupdate)                             AS noupdate
            FROM ir_model_data
           WHERE model = 'ir.ui.view'
           GROUP BY res_id
        ), twin AS (
          SELECT DISTINCT key FROM ir_ui_view
           WHERE key IS NOT NULL AND {twin_filter}
        )
        SELECT v.id                              AS id,
               {name}                            AS name,
               {col("model", "NULL::text")}      AS model,
               {col("type", "NULL::text")}       AS type,
               {col("key", "NULL::text")}        AS key,
               {col("mode", "NULL::text")}       AS mode,
               {col("active", "true")}           AS active,
               {col("inherit_id", "NULL::integer")} AS inherit_id,
               {arch_fs}                         AS arch_fs,
               {arch_updated}                    AS arch_updated,
               {arch_prev}                       AS has_arch_prev,
               {website}                         AS website_id,
               {theme}                           AS theme_template_id,
               x.modules                         AS xmlid_modules,
               x.xmlids                          AS xmlids,
               COALESCE(x.noupdate, false)       AS noupdate,
               (v.key IS NOT NULL
                AND EXISTS (SELECT 1 FROM twin WHERE twin.key = v.key))
                                                 AS has_module_twin,
               {col("create_uid", "NULL::integer")} AS create_uid,
               {col("create_date", "NULL::timestamp")} AS create_date,
               {col("write_uid", "NULL::integer")}  AS write_uid,
               {col("write_date", "NULL::timestamp")} AS write_date,
               octet_length(v.arch_db::text)     AS arch_bytes,
               md5(v.arch_db::text)              AS arch_md5
          FROM ir_ui_view v
          LEFT JOIN xid x ON x.res_id = v.id
         ORDER BY v.id
        """,
        **kwargs,
    )


def checkout_odoo_version():
    """Version Odoo de l'ARBRE SOURCE, qui n'est pas celle de la base."""
    try:
        with open(os.path.join(REPO_ROOT, ".odoo-version")) as handle:
            return handle.read().strip()
    except OSError:
        return None


def same_major(version_a, version_b):
    """Deux versions ont-elles la même majeure ? « 18.0.1.3 » vs « 18.0 »."""
    if not version_a or not version_b:
        return False
    return version_a.split(".")[0] == version_b.split(".")[0]


def add_reference_arch(database, lst_finding, config_path=None, timeout=600):
    """Compléter les constats avec l'arch que déclare le module.

    Ne s'adresse qu'aux vues qui ont un ``arch_fs`` : les autres n'ont aucune
    contrepartie dans les sources, il n'y a rien à comparer.

    Renvoie ``(source, erreur)`` — « orm » si le registre a répondu, « none »
    sinon, avec le message. Jamais d'échec silencieux : une comparaison qui n'a
    pas eu lieu ne doit pas se lire comme une comparaison sans écart.
    """
    lst_todo = [row for row in lst_finding if row.get("arch_fs")]
    if not lst_todo:
        return "none", None

    dct_by_id = {row["id"]: row for row in lst_todo}
    lst_id = sorted(dct_by_id)
    try:
        for start in range(0, len(lst_id), BATCH):
            chunk = lst_id[start : start + BATCH]
            for answer in odoo_shell_json(
                database,
                SHELL_SCRIPT,
                env={"VIEW_IDS": ",".join(str(i) for i in chunk)},
                timeout=timeout,
                config_path=config_path,
            ):
                row = dct_by_id.get(answer["id"])
                if row is None:
                    continue
                row["arch_ref"] = answer.get("arch_file")
                row["arch_db_text"] = answer.get("arch_db")
                row["arch_ref_error"] = answer.get("error")
    except AnalyseError as exc:
        return "none", str(exc)

    for row in lst_todo:
        differs, comparable = arch_differs(
            row.get("arch_ref"), row.get("arch_db_text")
        )
        row["comparable"] = comparable
        row["differs"] = differs
        if comparable:
            row["diff_stats"] = diff_stats(
                side_by_side(row["arch_ref"], row["arch_db_text"])
            )
    return "orm", None


def collect(
    database,
    with_diff=False,
    scope="flagged",
    config_path=None,
    timeout=120,
    shell_timeout=600,
):
    """Tout le travail. Donnée pure, sérialisable, aucun affichage."""
    kwargs = {"config_path": config_path, "timeout": timeout}
    require_odoo_database(database, **kwargs)
    odoo_version = scalar_query(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base';",
        **kwargs,
    )
    has_website = bool(
        scalar_query(
            database,
            "SELECT 1 FROM ir_module_module"
            " WHERE name = 'website' AND state = 'installed';",
            **kwargs,
        )
    )

    lst_view = _view_rows(database, **kwargs)
    dct_count = {name: 0 for name in CATEGORIES}
    lst_finding = []
    for row in lst_view:
        category, lst_reason = classify(row)
        row["category"] = category
        row["reason"] = lst_reason
        dct_count[category] += 1
        if category in ACTIONABLE:
            lst_finding.append(row)

    arch_ref_source, arch_ref_error = "none", None
    checkout = checkout_odoo_version()
    if with_diff:
        if not same_major(odoo_version, checkout):
            # Le shell charge l'arbre du checkout, pas celui de la base : sur
            # une base 13.0 avec un checkout 18.0 le registre ne chargera pas.
            # Le dire en une seconde vaut mieux que trente secondes de
            # chargement pour aboutir à la même conclusion.
            arch_ref_error = (
                f"{t('Database is Odoo')} {odoo_version},"
                f" {t('checkout is')} {checkout}"
            )
        else:
            # « flagged » ne compare que ce qui porte déjà un signe. C'est
            # rapide, et aveugle au cas même que les drapeaux ratent : une vue
            # réécrite en SQL direct n'arme pas arch_updated. « all » compare
            # toute vue ayant un arch_fs et voit cette dérive silencieuse.
            # « flagged » ne compare que ce qui porte déjà un signe : rapide,
            # et ce qu'il rapporte est fiable. « all » compare toute vue ayant
            # un arch_fs, ce qui trouve la dérive qu'aucun drapeau ne signale —
            # une vue réécrite en SQL direct — mais au prix d'un plancher de
            # bruit MESURÉ : sur une base 18.0 fraîchement installée, 160 des
            # 974 vues à arch_fs diffèrent déjà. read_arch_from_file rend le
            # XML brut du fichier, alors que la base porte l'arch APRÈS
            # traitement au chargement : un attribut « groups » est consommé,
            # un <xpath position="attributes"> est appliqué. En « all », un
            # écart est une piste, pas un verdict.
            lst_candidate = (
                lst_finding
                if scope == "flagged"
                else [row for row in lst_view if row.get("arch_fs")]
            )
            arch_ref_source, arch_ref_error = add_reference_arch(
                database,
                lst_candidate,
                config_path=config_path,
                timeout=shell_timeout,
            )

    # Une vue signalée dont la forme canonique égale celle du module n'a rien
    # de modifié : le drapeau disait vrai sur « touchée », faux sur « autre ».
    # C'est tout l'intérêt de comparer, alors elle quitte les constats.
    n_identical = 0
    if arch_ref_source == "orm":
        if scope != "flagged":
            # Une vue sans drapeau dont l'arch diffère de son module a été
            # réécrite sans passer par Odoo. C'est le constat que seule la
            # comparaison peut produire, et le plus intéressant du lot.
            known = {row["id"] for row in lst_finding}
            for row in lst_view:
                if row["id"] in known or not row.get("differs"):
                    continue
                dct_count[row["category"]] -= 1
                row["category"] = "module_view_drifted"
                row["reason"] = row["reason"] + ["differs_from_module"]
                dct_count["module_view_drifted"] += 1
                lst_finding.append(row)
        lst_kept = []
        for row in lst_finding:
            if (
                row["category"] == "module_view_flagged"
                and row.get("comparable")
                and row.get("differs") is False
            ):
                row["category"] = "module_view"
                row["reason"] = row["reason"] + ["identical_after_canonical"]
                dct_count["module_view_flagged"] -= 1
                dct_count["module_view"] += 1
                n_identical += 1
                continue
            lst_kept.append(row)
        lst_finding = lst_kept

    return {
        "tool": "analyse_view_custom",
        "version": 1,
        "database": database,
        "odoo_version": odoo_version,
        "checkout_version": checkout,
        "has_website": has_website,
        "compared_with_module_source": arch_ref_source == "orm",
        "arch_ref_source": arch_ref_source,
        "scope": scope,
        "arch_ref_error": arch_ref_error,
        "n_identical_after_canonical": n_identical,
        "n_views": len(lst_view),
        "counts": dct_count,
        "findings": lst_finding,
    }


def _finding_block(lst_row, top, hints=True):
    """Une ligne par vue : clé, identifiant externe, poids, raisons."""
    lines = [
        f"  {'id':>6}  {'key / xml-id':<44}{'size':>9}  {t('why')}",
    ]
    for row in lst_row[:top]:
        label = row.get("key") or (row.get("xmlids") or [""])[0] or "—"
        size = row.get("arch_bytes")
        lines.append(
            f"  {row['id']:>6}  {label[:44]:<44}"
            f"{(str(size) + ' B') if size else '?':>9}  "
            f"{', '.join(row.get('reason') or []) or '—'}"
        )
    if len(lst_row) > top:
        lines.append(f"  … {len(lst_row) - top} {t('more')}")
    return lines


def render(data, verbose=False, top=TOP_DEFAULT, category=None, hints=True):
    """Rapport texte. Fonction pure : donnée -> chaîne, testable sans base."""
    version = data.get("odoo_version") or "?"
    counts = data["counts"]
    lines = [
        "",
        f"🔬 {t('Customised views')} — {data['database']} (Odoo {version})",
        "",
        f"  {t("Views"):<38}: {data['n_views']}",
    ]
    for name in CATEGORIES:
        if counts.get(name):
            lines.append(f"  {category_label(name):<38}: {counts[name]}")

    n_finding = len(data["findings"])
    if not n_finding:
        lines += [
            "",
            f"✅ {t('Every view comes straight from a module.')}",
        ]
        return "\n".join(lines) + "\n"

    lst_show = data["findings"]
    if category:
        lst_show = [r for r in lst_show if r["category"] == category]
    lines += [
        "",
        f"── ⚠️  {t('Views that did not come straight from a module')}"
        f" ({len(lst_show)}) ──",
    ]
    lines += _finding_block(lst_show, len(lst_show) if verbose else top)

    if counts.get("website_cow_copy"):
        lines.append("")
        lines += wrap_note(
            "  ",
            t(
                "Website copies are user data: Odoo copies a view instead of"
                " editing it. Whether they will survive the next version is"
                " another question, and these tools answer it:"
            ),
        )
        lines += [
            "     ./script/odoo/migration/check_cow_views.py"
            " -d DB -t odooXX.0",
            "     ./script/odoo/migration/reset_stale_cow_views.py -d DB",
        ]

    lines.append("")
    if data.get("compared_with_module_source"):
        if data.get("scope") == "all":
            lines += wrap_note(
                "  ⚠️  ",
                t(
                    "In --scope all, a difference is a lead, not a verdict:"
                    " read_arch_from_file returns the raw file, while the"
                    " database holds the arch AFTER load-time processing."
                    " Measured on a freshly installed 18.0 database, 160 of"
                    " its 974 views already differ this way."
                ),
            )
            lines.append("")
        if data.get("n_identical_after_canonical"):
            lines += wrap_note(
                "  ✅ ",
                f"{data['n_identical_after_canonical']} "
                + t(
                    "views were flagged but hold exactly what their module"
                    " declares: only the comparison could tell."
                ),
            )
        lines += wrap_note(
            "  💡 ",
            t(
                "To restore a view to what its module declares — this WRITES"
                " to the database, so read the difference first:"
            ),
        )
        lines.append(
            "     echo \"env['ir.ui.view'].browse(ID).reset_arch('hard');"
            ' env.cr.commit()" \\'
        )
        lines.append(
            f"       | ./odoo_bin.sh shell -c ./config.conf"
            f" -d {data['database']}"
        )
    elif data.get("arch_ref_error"):
        lines += wrap_note(
            "  ⚠️  ",
            t("No reference arch, so nothing was compared: ")
            + str(data["arch_ref_error"]),
        )
    elif hints:
        lines += wrap_note(
            "  ℹ️  ",
            t(
                "Flags say a view was touched, not how. They are incomplete"
                " both ways: a direct SQL write does not set arch_updated,"
                " and reset_arch clears it. Comparing with the module source"
                " is what settles it — add --diff."
            ),
        )
    else:
        lines += wrap_note(
            "  ℹ️  ",
            t(
                "Flags say a view was touched, not how: only comparing with"
                " the module source settles it."
            ),
        )
    return "\n".join(lines) + "\n"


def render_diff(row, width=78):
    """Le diff d'une vue, côte à côte, pour la sortie texte.

    Calculé sur les arch BRUTES, pas sur les formes canoniques : la forme
    canonique sert à décider s'il y a un écart, elle ne se relit pas.
    """
    lines = [
        "",
        f"── id={row['id']} {row.get('key') or '—'} "
        f"({row.get('arch_fs') or '—'}) ──",
    ]
    half = (width - 4) // 2
    for mark, left, right in side_by_side(
        row.get("arch_ref"), row.get("arch_db_text")
    ):
        if mark == " ":
            continue
        lines.append(
            f"  {mark} {(left or '')[:half]:<{half}} │ {(right or '')[:half]}"
        )
    return lines


def open_tui(data):
    """Ouvrir l'écran de navigation. False si on n'a pas pu — l'appelant imprime.

    Trois refus, trois raisons distinctes, et aucune n'est une panne :
    rien à montrer, pas de terminal, ou Textual absent. Chacune se dit, plutôt
    que d'ouvrir un écran vide ou de laisser des codes d'échappement dans un
    fichier de sortie.
    """
    lst_diff = [row for row in data["findings"] if row.get("differs")]
    if not lst_diff:
        return False
    if not sys.stdout.isatty():
        print(f"ℹ️  {t('Not a terminal: showing the text report instead.')}")
        return False
    try:
        from script.todo import textual_setup
    except Exception:
        textual_setup = None
    if textual_setup and not textual_setup.ensure():
        return False

    from script.analyse.analyse_diff_tui import run_diff_tui

    intent = run_diff_tui(data)
    if intent and intent[0] == "command":
        row = intent[1]
        print(f"\n💡 {t('To restore this view to what its module declares:')}")
        print(
            f"   echo \"env['ir.ui.view'].browse({row['id']})"
            f".reset_arch('hard'); env.cr.commit()\" \\"
        )
        print(
            f"     | ./odoo_bin.sh shell -c ./config.conf"
            f" -d {data['database']}"
        )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "List the views of an Odoo database that did not come straight"
            " from a module, website copies included (read-only)."
        )
    )
    parser.add_argument(
        "-d", "--database", required=True, help=t("database to inspect")
    )
    parser.add_argument(
        "--category",
        choices=CATEGORIES,
        default=None,
        help=t("only show this category"),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_DEFAULT,
        help=t("how many views to show (default: 20)"),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help=t("list every view")
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help=t("compare with the module source (opens an Odoo shell)"),
    )
    parser.add_argument(
        "--scope",
        choices=("flagged", "all"),
        default="flagged",
        help=t("which views to compare (default: flagged)"),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=t("fail if the comparison could not be made"),
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help=t("browse the differences in a full-screen view"),
    )
    parser.add_argument("--json", action="store_true", help=t("output JSON"))
    parser.add_argument(
        "-c", "--config", default=None, help=t("path to an Odoo config file")
    )
    config = parser.parse_args(argv)

    try:
        data = collect(
            config.database,
            with_diff=config.diff or config.tui,
            scope=config.scope,
            config_path=config.config,
        )
    except AnalyseError as exc:
        print(f"❌ {exc}")
        return 2
    except KeyboardInterrupt:
        print(f"\n{t('Cancelled.')}")
        return 2

    if config.strict and not data["compared_with_module_source"]:
        print(
            f"❌ {t('No reference arch, so nothing was compared: ')}"
            f"{data.get('arch_ref_error') or ''}"
        )
        return 2

    if config.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return 1 if data["findings"] else 0

    if config.tui and open_tui(data):
        return 1 if data["findings"] else 0

    print(
        render(
            data,
            verbose=config.verbose,
            top=config.top,
            category=config.category,
        )
    )
    if config.verbose and data["compared_with_module_source"]:
        for row in data["findings"]:
            if row.get("differs"):
                print("\n".join(render_diff(row)))
    return 1 if data["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
