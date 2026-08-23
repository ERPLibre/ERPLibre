#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Poids d'une base Odoo, et tables qui ne correspondent à plus rien.

Ce que l'outil répond : combien pèse cette base, où est le gras, et quelles
tables ne sont réclamées par aucun modèle installé. Ces dernières sont les
reliquats de modules désinstallés sans ``DROP TABLE``, que chaque montée de
version recopie et redéploie sans que personne ne les regarde.

Trois pièges évités, chacun pour une bonne raison
-------------------------------------------------
**Une table m2m n'a aucune ligne dans ``ir_model``.** Les recenser comme
orphelines ferait crier au loup sur ~200 tables d'une base ordinaire. Odoo
tient leur liste dans ``ir_model_relation``, on la lui demande.

**Une table introuvable n'est pas une anomalie, c'est une inconnue.** Un
modèle dont le ``_table`` est surchargé — ``ir.actions.act_window`` vit dans
``ir_act_window`` — serait classé « sans table » par un
``replace('.', '_')`` naïf. ``lib_analyse.model_table()`` connaît les
surcharges, et ce qu'il ne résout pas est marqué inconnu, jamais orphelin.

**Les modèles abstraits SONT dans ``ir_model``.** ``registry.py`` appelle
``_reflect_models()`` sur tous les modèles chargés, sans filtre sur
``_abstract`` ; il n'existe d'ailleurs aucune colonne ``abstract``. Des
centaines de modèles sans table sont donc parfaitement normaux : c'est un
fait rapporté, pas un constat.

Le comptage de lignes est une estimation, et le dit
---------------------------------------------------
``reltuples`` vient du dernier ``ANALYZE``. PostgreSQL 14 et suivants y
mettent ``-1`` quand la table n'a jamais été analysée — afficher ``0`` ferait
passer une table pleine pour une table vide. On affiche ``?``. Le compte exact
est derrière ``--exact`` parce qu'il coûte un balayage complet par table.
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
    json_query,
    model_table,
    normalise_arch,
    quote_literal,
    read_backup,
    require_odoo_database,
    scalar_query,
    t,
    tr_col,
)

# Tables réelles qui n'appartiennent pas à Odoo : une extension PostgreSQL les
# pose dans le schéma public. Les compter comme orphelines enverrait
# l'utilisateur supprimer une table dont dépend PostGIS.
SYSTEM_TABLES = {
    "spatial_ref_sys",  # PostGIS
}

TOP_DEFAULT = 20


def wrap_note(prefix, text, width=79):
    """Replier une phrase à la largeur du terminal, sans la découper en clés.

    Une phrase coupée en trois clés de traduction se replie correctement dans
    la langue où elle a été écrite, et n'importe comment dans l'autre : l'ordre
    des mots et la longueur diffèrent. La phrase reste donc entière côté
    traduction, et c'est l'affichage qui la replie.
    """
    lines = textwrap.wrap(text, width=width - len(prefix)) or [""]
    pad = " " * len(prefix)
    return [prefix + lines[0]] + [pad + line for line in lines[1:]]


def fmt_bytes(value):
    """Taille lisible, en unités binaires — mêmes symboles en fr et en en."""
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return (
                f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            )
        size /= 1024
    return f"{size:.1f} TiB"


def fmt_rows(value):
    """Nombre de lignes, ou « ? » si la table n'a jamais été analysée.

    reltuples vaut -1 depuis PostgreSQL 14 quand aucun ANALYZE n'a tourné.
    Avant, il valait 0 — indistinguable d'une table vide. On rend « ? » dans
    les deux cas plutôt qu'un chiffre auquel personne ne devrait se fier.
    """
    if value is None or value < 0:
        return "?"
    return f"{value:,}".replace(",", " ")


def _table_rows(database, **kwargs):
    """Une ligne par table réelle du schéma public, avec son poids.

    relkind 'r' pour une table ordinaire, 'p' pour une partitionnée. Odoo n'en
    partitionne pas, mais le compte ne doit pas devenir faux en silence le jour
    où cela changera.
    """
    return json_query(
        database,
        """
        SELECT c.relname                        AS table_name,
               pg_total_relation_size(c.oid)    AS total_bytes,
               pg_table_size(c.oid)             AS table_bytes,
               pg_indexes_size(c.oid)           AS index_bytes,
               c.reltuples::bigint              AS est_rows
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
         ORDER BY pg_total_relation_size(c.oid) DESC
        """,
        **kwargs,
    )


def _model_rows(database, **kwargs):
    """Modèles déclarés, avec leur description traduite.

    ir_model.name est un champ traduit : jsonb à partir de 16.0, texte avant.
    tr_col décide sur le type réel de la colonne.
    """
    dct_type = column_types(database, "ir_model", **kwargs)
    label = tr_col("ir_model", "name", dct_type)
    return json_query(
        database,
        f"""
        SELECT model    AS model,
               {label}  AS description,
               state    AS state,
               transient AS transient
          FROM ir_model
         ORDER BY model
        """,
        **kwargs,
    )


def _relation_tables(database, **kwargs):
    """Tables m2m qu'Odoo revendique, via ir_model_relation.

    Sans elles, toute table de relation passerait pour orpheline. La table peut
    manquer sur une base très ancienne : on sonde plutôt que de supposer.
    """
    if not scalar_query(
        database, "SELECT to_regclass('public.ir_model_relation');", **kwargs
    ):
        return set(), False
    rows = json_query(
        database, "SELECT name AS name FROM ir_model_relation", **kwargs
    )
    return {r["name"] for r in rows if r.get("name")}, True


def _exact_counts(database, lst_table, **kwargs):
    """count(*) réel par table — un balayage complet chacune.

    format('%I') met les identifiants entre guillemets côté PostgreSQL : aucun
    nom de table venu du catalogue ne peut casser la requête ni en détourner
    le sens.
    """
    if not lst_table:
        return {}
    values = ", ".join(f"({quote_literal(name)})" for name in lst_table)
    rows = json_query(
        database,
        f"""
        SELECT v.table_name AS table_name,
               (xpath('/row/c/text()',
                      query_to_xml(
                          format('SELECT count(*) AS c FROM public.%I',
                                 v.table_name),
                          false, true, '')))[1]::text::bigint AS exact_rows
          FROM (VALUES {values}) AS v(table_name)
        """,
        **kwargs,
    )
    return {r["table_name"]: r["exact_rows"] for r in rows}


def collect(database, exact=False, config_path=None, timeout=120):
    """Tout le travail. Donnée pure, sérialisable, aucun affichage."""
    kwargs = {"config_path": config_path, "timeout": timeout}
    require_odoo_database(database, **kwargs)

    db_bytes = scalar_query(
        database,
        "SELECT pg_database_size(current_database());",
        **kwargs,
    )
    odoo_version = scalar_query(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base';",
        **kwargs,
    )

    lst_table = _table_rows(database, **kwargs)
    lst_model = _model_rows(database, **kwargs)
    set_relation, has_relation_table = _relation_tables(database, **kwargs)
    set_table = {row["table_name"] for row in lst_table}

    # Table -> modèle. Une table peut porter plusieurs modèles : les huit
    # ir.actions.* partagent ir_actions. On garde le premier par ordre
    # alphabétique, pour que deux exécutions disent la même chose.
    dct_table_model = {}
    lst_without_table = []
    for row in lst_model:
        table = model_table(row["model"], known_tables=set_table)
        if table is None:
            lst_without_table.append(
                {
                    "model": row["model"],
                    "description": row.get("description"),
                    "state": row.get("state"),
                    "transient": row.get("transient"),
                }
            )
            continue
        dct_table_model.setdefault(table, row["model"])

    lst_orphan = []
    for row in lst_table:
        name = row["table_name"]
        if name in dct_table_model:
            row["model"] = dct_table_model[name]
            row["origin"] = "model"
        elif name in set_relation:
            row["model"] = None
            row["origin"] = "m2m"
        elif name in SYSTEM_TABLES:
            row["model"] = None
            row["origin"] = "system"
        else:
            row["model"] = None
            row["origin"] = "orphan"
            lst_orphan.append(row)
        row["exact_rows"] = None

    if exact:
        dct_exact = _exact_counts(
            database, [r["table_name"] for r in lst_table], **kwargs
        )
        for row in lst_table:
            row["exact_rows"] = dct_exact.get(row["table_name"])

    return {
        "tool": "analyse_schema_size",
        "version": 1,
        "database": database,
        "odoo_version": odoo_version,
        "db_bytes": int(db_bytes) if db_bytes else None,
        "exact": exact,
        "has_relation_table": has_relation_table,
        "n_tables": len(lst_table),
        "n_models": len(lst_model),
        "tables": lst_table,
        "orphan_tables": lst_orphan,
        "models_without_table": lst_without_table,
        "counts": {
            "orphan_tables": len(lst_orphan),
            "models_without_table": len(lst_without_table),
            "m2m_tables": sum(1 for r in lst_table if r["origin"] == "m2m"),
        },
    }


def collect_from_backup(zip_path):
    """Même analyse, depuis une sauvegarde .zip, sans rien restaurer.

    Ce qu'une sauvegarde donne EN MIEUX : le nombre de lignes est exact,
    compté dans le dump, là où une base rend l'estimation du dernier ANALYZE.

    Ce qu'elle ne peut pas donner : le poids sur le disque. Un dump ignore les
    index et le ballonnement, et présenter le poids de ses données comme une
    taille de table tromperait sur ce qui fait grossir une base. La colonne
    affichée est donc « poids dans le dump », et elle est nommée ainsi.
    """
    manifest, dct_rows, _, dct_census = read_backup(
        zip_path,
        tables=("ir_model", "ir_model_relation", "ir_module_module"),
        census=True,
    )
    set_table = set(dct_census)
    set_relation = {
        row.get("name") for row in dct_rows.get("ir_model_relation") or []
    }
    has_relation_table = "ir_model_relation" in dct_census

    dct_table_model = {}
    lst_without_table = []
    for row in dct_rows["ir_model"]:
        table = model_table(row.get("model") or "", known_tables=set_table)
        if table is None:
            lst_without_table.append(
                {
                    "model": row.get("model"),
                    "description": normalise_arch(row.get("name")),
                    "state": row.get("state"),
                    "transient": row.get("transient") == "t",
                }
            )
            continue
        dct_table_model.setdefault(table, row.get("model"))

    lst_table, lst_orphan = [], []
    for name, census in sorted(
        dct_census.items(), key=lambda kv: -kv[1]["dump_bytes"]
    ):
        row = {
            "table_name": name,
            # Aucune de ces trois-là ne se lit dans un dump : les laisser à
            # None fait afficher « ? », ce qui est la vérité, plutôt qu'un
            # zéro qui se lirait comme « cette table est vide ».
            "total_bytes": None,
            "table_bytes": None,
            "index_bytes": None,
            "dump_bytes": census["dump_bytes"],
            "est_rows": census["rows"],
            "exact_rows": census["rows"],
            "model": dct_table_model.get(name),
            "origin": "model",
        }
        if name in dct_table_model:
            pass
        elif name in set_relation:
            row["origin"] = "m2m"
        elif name in SYSTEM_TABLES:
            row["origin"] = "system"
        else:
            row["origin"] = "orphan"
            lst_orphan.append(row)
        lst_table.append(row)

    return {
        "tool": "analyse_schema_size",
        "version": 1,
        "database": os.path.basename(zip_path),
        "source": "backup",
        "backup_path": zip_path,
        "odoo_version": backup_version(dct_rows, manifest),
        "db_bytes": None,
        "dump_bytes": sum(c["dump_bytes"] for c in dct_census.values()),
        "exact": True,
        "has_relation_table": has_relation_table,
        "n_tables": len(lst_table),
        "n_models": len(dct_rows["ir_model"]),
        "tables": lst_table,
        "orphan_tables": lst_orphan,
        "models_without_table": lst_without_table,
        "counts": {
            "orphan_tables": len(lst_orphan),
            "models_without_table": len(lst_without_table),
            "m2m_tables": sum(1 for r in lst_table if r["origin"] == "m2m"),
        },
    }


def _table_block(lst_row, exact, source="database"):
    """Tableau aligné : une ligne par table, colonnes de largeur fixe.

    « heap » plutôt que « table » pour pg_table_size : la colonne « table »
    porte déjà le nom, et le même mot pour deux choses dans le même tableau se
    lit mal. Les quatre en-têtes techniques ne passent pas par t() — ils
    s'écrivent pareil en français et en anglais, contrairement à « rows ».
    """
    if source == "backup":
        # Un dump n'a ni index ni ballonnement : afficher trois colonnes vides
        # ferait croire à une mesure manquante plutôt qu'à une mesure qui
        # n'existe pas.
        lines = [f"  {'table':<44}{t('in the dump'):>14}{t('rows'):>14}"]
        for row in lst_row:
            lines.append(
                f"  {row['table_name']:<44}"
                f"{fmt_bytes(row.get('dump_bytes')):>14}"
                f"{fmt_rows(row['exact_rows']):>14}"
            )
        return lines
    lines = [
        f"  {'table':<34}{'total':>10}{'heap':>10}{'index':>10}"
        f"{t('rows'):>14}"
    ]
    for row in lst_row:
        count = row["exact_rows"] if exact else row["est_rows"]
        lines.append(
            f"  {row['table_name']:<34}"
            f"{fmt_bytes(row['total_bytes']):>10}"
            f"{fmt_bytes(row['table_bytes']):>10}"
            f"{fmt_bytes(row['index_bytes']):>10}"
            f"{fmt_rows(count):>14}"
        )
    return lines


def render(data, verbose=False, top=TOP_DEFAULT, hints=True):
    """Rapport texte. Fonction pure : donnée -> chaîne, testable sans base.

    ``hints`` gouverne les conseils en ligne de commande (« utilisez -v »,
    « --exact »). Ils aident qui a tapé la commande ; ils insultent qui est
    dans un menu, à qui l'on demande de sortir et de retaper autre chose.
    L'appel depuis le menu les coupe et offre les mêmes actions comme choix.
    """
    version = data.get("odoo_version") or "?"
    lines = [
        "",
        f"🔬 {t('Schema analysis')} — {data['database']} (Odoo {version}"
        f"{', ' + t('from a backup') if data.get('source') == 'backup' else ''})",
        "",
        (
            f"  {t('Weight in the dump'):<22}: "
            f"{fmt_bytes(data.get('dump_bytes'))}"
            if data.get("source") == "backup"
            else f"  {t('Database size'):<22}: {fmt_bytes(data['db_bytes'])}"
        ),
        f"  {t('Tables'):<22}: {data['n_tables']}",
        f"  {t('Models'):<22}: {data['n_models']}",
    ]
    n_without = data["counts"]["models_without_table"]
    if n_without:
        lines.append(
            f"  {t('Models without table'):<22}: {n_without}"
            f"  ({t('abstract models have none, by design')})"
        )
    if not data["has_relation_table"]:
        lines += wrap_note(
            "⚠️  ",
            t(
                "ir_model_relation is absent, so m2m tables cannot be told"
                " apart from orphans: the list below is unreliable."
            ),
        )

    lst_table = data["tables"]
    shown = lst_table if verbose else lst_table[:top]
    if shown:
        label = (
            t("All tables, heaviest first")
            if verbose
            else f"{t('Heaviest tables')} ({len(shown)}/{len(lst_table)})"
        )
        lines += ["", f"── {label} ──"]
        lines += _table_block(
            shown, data["exact"], data.get("source", "database")
        )
        if hints and not verbose and len(lst_table) > len(shown):
            lines.append(f"  … {t('use -v to list them all')}")
        elif not verbose and len(lst_table) > len(shown):
            lines.append(f"  … {len(lst_table) - len(shown)} {t('more')}")

    lst_orphan = data["orphan_tables"]
    if not lst_orphan:
        lines += ["", f"✅ {t('Every table belongs to an installed model.')}"]
    else:
        lines += [
            "",
            f"── ⚠️  {t('Orphan tables')} ({len(lst_orphan)}) ──",
        ]
        lines += _table_block(
            lst_orphan, data["exact"], data.get("source", "database")
        )
        lines.append("")
        lines += wrap_note(
            "  ",
            t(
                "No installed model claims these tables. They are usually left"
                " over from modules uninstalled without DROP TABLE, and every"
                " version upgrade carries them along."
            ),
        )
        lines += wrap_note(
            "  💡 ", t("Check what they hold before dropping anything.")
        )

    if not data["exact"] and hints:
        lines.append("")
        lines += wrap_note(
            "  ℹ️  ",
            t(
                "Row counts are estimates from the last ANALYZE. Use --exact"
                " for real counts, at the cost of one full scan per table."
            ),
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "Report the size of an Odoo database and the tables no installed"
            " model claims (read-only)."
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
        "--exact",
        action="store_true",
        help=t("count rows exactly: one full scan per table"),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_DEFAULT,
        help=t("how many tables to show (default: 20)"),
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help=t("list every table")
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
            data = collect(
                config.database, exact=config.exact, config_path=config.config
            )
    except AnalyseError as exc:
        print(f"❌ {exc}")
        return 2
    except KeyboardInterrupt:
        print(f"\n{t('Cancelled.')}")
        return 2

    if config.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(render(data, verbose=config.verbose, top=config.top))
    return 1 if data["orphan_tables"] else 0


if __name__ == "__main__":
    sys.exit(main())
