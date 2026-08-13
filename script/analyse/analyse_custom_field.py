#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Champs et modèles ajoutés hors module : Studio, ou faits à la main.

Ce que l'outil répond : ce qu'un intégrateur devra reporter à la main lors
d'une montée de version, puisque rien ne le recréera. Un champ ``x_`` n'est
déclaré dans aucun fichier ; il ne vit que dans ``ir_model_fields``, et une
migration qui le perd perd aussi les données de sa colonne.

Studio n'est pas nécessaire pour lire ça
-----------------------------------------
``web_studio`` est un module Enterprise, absent de ce dépôt. Les champs qu'il
crée restent pourtant de simples lignes de ``ir_model_fields`` avec
``state = 'manual'``, et une base migrée depuis une instance Enterprise garde
ses identifiants externes ``studio_customization``. Tout se lit en SQL.

Attribuer un champ à Studio demande deux signaux, pas un
---------------------------------------------------------
Un champ peut porter PLUSIEURS identifiants externes. Une jointure plate n'en
rendrait qu'un, choisi au hasard : Studio passerait inaperçu une fois sur
deux. Les modules sont donc agrégés, et l'appartenance testée sur l'ensemble.

Le préfixe ``x_studio_`` est un indice de plus, jamais le seul : un champ créé
à la main en mode développeur s'appelle aussi ``x_quelque_chose``, et ce qui
le distingue est qu'il n'a AUCUN identifiant externe.

Ce qui bloque, et ce qui ne fait que coûter
--------------------------------------------
Un champ stocké dont la colonne physique manque empêche le registre de
charger : c'est un blocage. Un champ dont la relation pointe vers un modèle
disparu aussi. Le reste — des champs remplis à reporter, des champs vides à
supprimer avant de migrer — est du travail, pas une panne, et le rapport ne
les mélange pas.
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
    AnalyseError,
    backup_version,
    column_types,
    existing_columns,
    json_query,
    model_table,
    normalise_arch,
    public_tables,
    read_backup,
    require_odoo_database,
    scalar_query,
    t,
    tr_col,
)

STUDIO_MODULE = "studio_customization"

# Un champ relationnel « vers plusieurs » n'a pas de colonne : il vit dans une
# table de relation. Ne pas l'exclure ferait rapporter chaque one2many et
# chaque many2many comme une colonne manquante.
NO_COLUMN_TYPES = ("one2many", "many2many")

TOP_DEFAULT = 30


def wrap_note(prefix, text, width=79):
    """Replier une phrase à l'affichage, sans la découper en clés."""
    lines = textwrap.wrap(text, width=width - len(prefix)) or [""]
    pad = " " * len(prefix)
    return [prefix + lines[0]] + [pad + line for line in lines[1:]]


def origin_label(name):
    """Libellé traduit d'une provenance. Épelé, pour que le contrôle voie."""
    return {
        "studio": t("Studio"),
        "handmade": t("Made by hand"),
        "module": t("Declared by a module"),
    }.get(name, name)


def blocker_label(name):
    """Libellé traduit d'un blocage. Épelé, comme les provenances."""
    return {
        "missing_column": t("stored, but its column is missing"),
        "dangling_relation": t("points at a model that no longer exists"),
        "model_gone": t("its model no longer exists"),
        "table_unknown": t("its table could not be resolved"),
    }.get(name, name)


def field_origin(row):
    """D'où vient ce champ : Studio, fait à la main, ou déclaré par un module.

    Fonction pure, testable sur fixture.
    """
    lst_module = row.get("xmlid_modules") or []
    if STUDIO_MODULE in lst_module:
        return "studio"
    if not lst_module:
        return "handmade"
    return "module"


def _field_rows(database, **kwargs):
    """Les champs manuels, avec tout ce qui sert à les juger.

    ``state = 'manual'`` est le critère d'Odoo ; le motif sur le nom l'élargit
    aux bases dont la contrainte n'a pas toujours été posée. Les deux, parce
    qu'aucun n'est complet seul.
    """
    cols = existing_columns(database, "ir_model_fields", **kwargs)
    dct_type = column_types(database, "ir_model_fields", **kwargs)

    def col(column, absent):
        return f"f.{column}" if column in cols else absent

    label = tr_col("f", "field_description", dct_type)
    help_text = tr_col("f", "help", dct_type)
    return json_query(
        database,
        rf"""
        SELECT f.id                                   AS id,
               f.model                                AS model,
               f.name                                 AS name,
               f.ttype                                AS ttype,
               {col("relation", "NULL::text")}        AS relation,
               {col("related", "NULL::text")}         AS related,
               {col("required", "false")}             AS required,
               {col("readonly", "false")}             AS readonly,
               {col("store", "true")}                 AS store,
               {col("index", "false")}                AS indexed,
               {col("translate", "false")}            AS translate,
               {col("company_dependent", "false")}    AS company_dependent,
               ({col("compute", "NULL")} IS NOT NULL
                AND {col("compute", "''")} <> '')     AS is_computed,
               {label}                                AS label,
               {help_text}                            AS help,
               {col("state", "NULL::text")}           AS state,
               x.modules                              AS xmlid_modules,
               {col("create_date", "NULL::timestamp")} AS create_date,
               {col("write_date", "NULL::timestamp")}  AS write_date
          FROM ir_model_fields f
          LEFT JOIN (
              SELECT res_id, array_agg(DISTINCT module) AS modules
                FROM ir_model_data
               WHERE model = 'ir.model.fields'
               GROUP BY res_id
          ) x ON x.res_id = f.id
         WHERE {col("state", "''")} = 'manual' OR f.name LIKE 'x\_%'
         ORDER BY f.model, f.name
        """,
        **kwargs,
    )


def _model_rows(database, **kwargs):
    """Les modèles manuels — ceux que Studio crée comme objets personnalisés."""
    dct_type = column_types(database, "ir_model", **kwargs)
    label = tr_col("m", "name", dct_type)
    return json_query(
        database,
        rf"""
        SELECT m.model     AS model,
               {label}     AS description,
               m.state     AS state,
               m.transient AS transient,
               x.modules   AS xmlid_modules
          FROM ir_model m
          LEFT JOIN (
              SELECT res_id, array_agg(DISTINCT module) AS modules
                FROM ir_model_data
               WHERE model = 'ir.model'
               GROUP BY res_id
          ) x ON x.res_id = m.id
         WHERE m.state = 'manual' OR m.model LIKE 'x\_%'
         ORDER BY m.model
        """,
        **kwargs,
    )


def _selection_rows(database, **kwargs):
    """Valeurs de sélection des champs manuels, si la table existe.

    ``ir_model_fields_selection`` est apparue en cours de route : avant, les
    valeurs vivaient dans une chaîne du champ. On sonde plutôt que de dater.
    """
    if not scalar_query(
        database,
        "SELECT to_regclass('public.ir_model_fields_selection');",
        **kwargs,
    ):
        return {}
    rows = json_query(
        database,
        """
        SELECT f.model AS model, f.name AS name, s.value AS value
          FROM ir_model_fields_selection s
          JOIN ir_model_fields f ON f.id = s.field_id
         WHERE f.state = 'manual'
         ORDER BY f.model, f.name, s.sequence
        """,
        **kwargs,
    )
    dct = {}
    for row in rows:
        dct.setdefault((row["model"], row["name"]), []).append(row["value"])
    return dct


def collect(database, config_path=None, timeout=120):
    """Tout le travail. Donnée pure, sérialisable, aucun affichage."""
    kwargs = {"config_path": config_path, "timeout": timeout}
    require_odoo_database(database, **kwargs)
    odoo_version = scalar_query(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base';",
        **kwargs,
    )

    lst_field = _field_rows(database, **kwargs)
    lst_model = _model_rows(database, **kwargs)
    dct_selection = _selection_rows(database, **kwargs)
    set_table = public_tables(database, **kwargs)
    set_model = {
        row["model"]
        for row in json_query(database, "SELECT model FROM ir_model", **kwargs)
    }

    # Les colonnes réelles, une sonde par table concernée seulement.
    dct_columns = {}
    for row in lst_field:
        table = model_table(row["model"], known_tables=set_table)
        row["table"] = table
        if table and table not in dct_columns:
            dct_columns[table] = existing_columns(database, table, **kwargs)

    lst_blocker = _judge(
        lst_field, set_model, set_table, dct_columns, dct_selection
    )
    return _result(
        database,
        odoo_version,
        lst_field,
        lst_model,
        lst_blocker,
        source="database",
    )


def _judge(lst_field, set_model, set_table, dct_columns, dct_selection):
    """Attribuer et juger chaque champ. Renvoie la liste des bloquants.

    Partagé par la lecture d'une base et celle d'une sauvegarde : les deux
    doivent conclure la même chose des mêmes faits, sinon le zip et la base
    d'où il vient ne diraient pas pareil.
    """
    lst_blocker = []
    for row in lst_field:
        row["origin"] = field_origin(row)
        row["selection"] = dct_selection.get((row["model"], row["name"]))
        row["blocker"] = None

        if row["table"] is None:
            # Table non résolue : un fait, pas une anomalie. Le modèle peut
            # avoir un _table surchargé qu'on ne connaît pas, ou ne plus
            # exister du tout — deux choses qu'on ne confond pas ici.
            row["blocker"] = (
                "model_gone"
                if row["model"] not in set_model
                else "table_unknown"
            )
        elif (
            row["store"]
            and row["ttype"] not in NO_COLUMN_TYPES
            and row["name"] not in dct_columns[row["table"]]
        ):
            # Un champ stocké sans sa colonne empêche le registre de charger.
            row["blocker"] = "missing_column"
        elif row["relation"] and row["relation"] not in set_model:
            row["blocker"] = "dangling_relation"

        if row["blocker"] in (
            "missing_column",
            "dangling_relation",
            "model_gone",
        ):
            lst_blocker.append(row)

    return lst_blocker


def _result(
    database,
    odoo_version,
    lst_field,
    lst_model,
    lst_blocker,
    source="database",
):
    """La donnée de sortie, une seule forme quelle que soit la provenance."""
    dct_origin = {"studio": 0, "handmade": 0, "module": 0}
    for row in lst_field:
        dct_origin[row["origin"]] += 1

    return {
        "tool": "analyse_custom_field",
        "version": 1,
        "database": database,
        "source": source,
        "odoo_version": odoo_version,
        "n_fields": len(lst_field),
        "n_models": len(lst_model),
        "counts": {
            **dct_origin,
            "blockers": len(lst_blocker),
            "models": len(lst_model),
        },
        "fields": lst_field,
        "models": lst_model,
        "blockers": lst_blocker,
    }


def collect_from_backup(zip_path):
    """Même analyse, mais depuis une sauvegarde .zip, sans rien restaurer.

    Pourquoi cela existe : restaurer la sauvegarde d'une instance Enterprise
    sur une installation Community échoue — Odoo veut charger des modules
    qu'on n'a pas. Les champs Studio, eux, ne sont que des lignes de
    `ir_model_fields`, et un `dump.sql` est du texte. On les lit donc là où
    ils sont, plutôt que d'exiger une restauration impossible.

    Ce que la sauvegarde permet en moins : rien, pour cet outil. Le dump
    contient les `CREATE TABLE`, donc même la colonne physique manquante — le
    seul vrai bloquant — se détecte.
    """
    manifest, dct_rows, dct_columns, _ = read_backup(
        zip_path,
        tables=(
            "ir_model_fields",
            "ir_model",
            "ir_model_data",
            "ir_module_module",
        ),
        with_columns=True,
    )

    # Les identifiants externes, agrégés par champ et par modèle — le même
    # regroupement que fait le SQL, pour que Studio s'attribue pareil.
    dct_xmlid = {}
    for row in dct_rows["ir_model_data"]:
        key = (row.get("model"), row.get("res_id"))
        dct_xmlid.setdefault(key, set()).add(row.get("module"))

    lst_field = []
    for row in dct_rows["ir_model_fields"]:
        name = row.get("name") or ""
        if row.get("state") != "manual" and not name.startswith("x_"):
            continue
        lst_field.append(
            {
                "id": row.get("id"),
                "model": row.get("model"),
                "name": name,
                "ttype": row.get("ttype"),
                "relation": row.get("relation"),
                "related": row.get("related"),
                # Le dump rend « t »/« f » : PostgreSQL écrit les booléens
                # ainsi dans un COPY, et « f » est une chaîne vraie en Python.
                "store": row.get("store") != "f",
                "translate": row.get("translate") == "t",
                "state": row.get("state"),
                # Un champ traduit est du jsonb à partir de 16.0. Depuis une
                # base, tr_col le déballe côté SQL ; depuis un dump, la valeur
                # arrive brute, et « {"en_US": "Code client"} » ne se lit pas.
                # normalise_arch fait ce déballage, et c'est la même fonction
                # des deux côtés — deux implémentations divergeraient.
                "label": normalise_arch(row.get("field_description")),
                "help": normalise_arch(row.get("help")),
                "xmlid_modules": sorted(
                    dct_xmlid.get(("ir.model.fields", row.get("id"))) or []
                ),
                "create_date": row.get("create_date"),
                "write_date": row.get("write_date"),
            }
        )

    lst_model = [
        {
            "model": row.get("model"),
            "description": normalise_arch(row.get("name")),
            "state": row.get("state"),
            "transient": row.get("transient") == "t",
            "xmlid_modules": sorted(
                dct_xmlid.get(("ir.model", row.get("id"))) or []
            ),
        }
        for row in dct_rows["ir_model"]
        if row.get("state") == "manual"
        or (row.get("model") or "").startswith("x_")
    ]

    set_model = {row.get("model") for row in dct_rows["ir_model"]}
    set_table = set(dct_columns)
    for row in lst_field:
        row["table"] = model_table(row["model"], known_tables=set_table)

    lst_blocker = _judge(lst_field, set_model, set_table, dct_columns, {})
    data = _result(
        os.path.basename(zip_path),
        backup_version(dct_rows, manifest),
        lst_field,
        lst_model,
        lst_blocker,
        source="backup",
    )
    data["backup_path"] = zip_path
    data["backup_db_name"] = manifest.get("db_name")
    return data


def _field_block(lst_row, top):
    """Une ligne par champ : modèle, nom, type, provenance."""
    lines = [
        f"  {'model':<28}{'field':<30}{'type':<12}{t('origin')}",
    ]
    for row in lst_row[:top]:
        lines.append(
            f"  {(row['model'] or '')[:27]:<28}{(row['name'] or '')[:29]:<30}"
            f"{(row['ttype'] or '')[:11]:<12}{origin_label(row['origin'])}"
        )
    if len(lst_row) > top:
        lines.append(f"  … {len(lst_row) - top} {t('more')}")
    return lines


def render(data, verbose=False, top=TOP_DEFAULT, hints=True):
    """Rapport texte. Fonction pure : donnée -> chaîne, testable sans base."""
    counts = data["counts"]
    lines = [
        "",
        f"🔬 {t('Fields added outside a module')} — {data['database']}"
        f" (Odoo {data.get('odoo_version') or '?'}"
        f"{', ' + t('from a backup') if data.get('source') == 'backup' else ''})",
        "",
        f"  {t('Custom fields'):<30}: {data['n_fields']}",
    ]
    for name in ("studio", "handmade", "module"):
        if counts.get(name):
            lines.append(f"  {origin_label(name):<30}: {counts[name]}")
    if data["n_models"]:
        lines.append(f"  {t('Custom models'):<30}: {data['n_models']}")

    if not data["n_fields"] and not data["n_models"]:
        lines += [
            "",
            f"✅ {t('No field or model was added outside a module.')}",
        ]
        return "\n".join(lines) + "\n"

    if data["blockers"]:
        lines += ["", f"── ❌ {t('Blocking')} ({len(data['blockers'])}) ──"]
        for row in data["blockers"]:
            lines.append(
                f"  {row['model']}.{row['name']} —"
                f" {blocker_label(row['blocker'])}"
                + (f" → {row['relation']}" if row.get("relation") else "")
            )
        lines.append("")
        lines += wrap_note(
            "  ",
            t(
                "A stored field without its column stops the registry from"
                " loading, so the upgrade will not even start. Settle these"
                " before anything else."
            ),
        )

    lst_show = data["fields"]
    if lst_show:
        lines += [
            "",
            f"── ⚠️  {t('To carry over by hand')} ({len(lst_show)}"
            f"{', ' + str(len(data['blockers'])) + ' ' + t('blocking') if data['blockers'] else ''}) ──",
        ]
        lines += _field_block(lst_show, len(lst_show) if verbose else top)

    if data["models"]:
        lines += ["", f"── 🧱 {t('Custom models')} ({len(data['models'])}) ──"]
        for row in data["models"][: len(data["models"]) if verbose else top]:
            lines.append(
                f"  {row['model']:<32}{(row.get('description') or '')[:40]}"
            )

    lines.append("")
    lines += wrap_note(
        "  ",
        t(
            "Nothing declares these in a file, so no module will recreate"
            " them. What a version upgrade keeps is what someone carried over."
        ),
    )
    if hints and not verbose:
        lines += wrap_note(
            "  ℹ️  ",
            t("Use -v to list them all, --json for the raw data."),
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "List the fields and models added outside a module — Studio or by"
            " hand (read-only)."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("-d", "--database", help=t("database to inspect"))
    source.add_argument(
        "-z",
        "--zip",
        dest="backup",
        help=t("Odoo backup .zip to inspect, without restoring it"),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_DEFAULT,
        help=t("how many to show (default: 30)"),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help=t("list every one")
    )
    parser.add_argument("--json", action="store_true", help=t("output JSON"))
    parser.add_argument(
        "-c", "--config", default=None, help=t("path to an Odoo config file")
    )
    config = parser.parse_args(argv)

    try:
        if config.backup:
            data = collect_from_backup(config.backup)
        else:
            data = collect(config.database, config_path=config.config)
    except AnalyseError as exc:
        print(f"❌ {exc}")
        return 2
    except KeyboardInterrupt:
        print(f"\n{t('Cancelled.')}")
        return 2

    if config.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(render(data, verbose=config.verbose, top=config.top))
    return 1 if (data["fields"] or data["models"]) else 0


if __name__ == "__main__":
    sys.exit(main())
