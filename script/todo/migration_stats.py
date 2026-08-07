#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Statistiques d'une migration Odoo, en lecture seule.

Ne touche NI la base NI le fichier de progression : tout se déduit du journal
de migration et des traces laissées sous `private/odoo/migration/<base>/`.
C'est ce qui permet de consulter l'état d'une migration en cours depuis une
autre session sans risquer de la perturber.

`compute()` reçoit le contexte déjà construit par
`TodoUpgrade.resume_context()` — étapes et montées de version — pour ne pas
réimplémenter une seconde fois la lecture des clés « state_* », qui
divergerait de l'écran de reprise.
"""
from __future__ import annotations

import datetime
import glob
import json
import os

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


def _as_int(value):
    """Clé de version en entier. JSON transforme les clés numériques en
    chaînes : « 13 » et 13 désignent la même version."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def fmt_delay(start, end):
    """Écart lisible entre deux horodatages « str(datetime) »."""
    try:
        a = datetime.datetime.fromisoformat(str(start))
        b = datetime.datetime.fromisoformat(str(end))
    except (TypeError, ValueError):
        return "?"
    secs = int(abs((b - a).total_seconds()))
    days, rest = divmod(secs, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} j {hours:02d} h"
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"


def module_evolution(dct_progression):
    """[(version, nb_modules, delta)] du plus ancien au plus récent.

    Montre où les modules disparaissent : un saut qui en perd 15 d'un coup
    n'a pas le même sens qu'un saut qui n'en perd aucun.
    """
    raw = dct_progression.get("dct_module_per_version") or {}
    rows = []
    for key, value in raw.items():
        version = _as_int(key)
        if version is not None and isinstance(value, list):
            rows.append((version, len(value)))
    rows.sort()
    out = []
    previous = None
    for version, count in rows:
        out.append(
            (version, count, None if previous is None else count - previous)
        )
        previous = count
    return out


def cow_snapshots(private_dir, database_name):
    """Instantanés de vues COW enregistrés, du plus ancien au plus récent."""
    directory = os.path.join(private_dir, database_name, "cow_snapshots")
    out = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        out.append(
            {
                "label": data.get("label") or os.path.basename(path)[:-5],
                "count": data.get("count"),
                "taken_at": data.get("taken_at") or "?",
                "path": path,
            }
        )
    out.sort(key=lambda item: item["taken_at"])
    return out


def fix_hooks(ctx, global_dir):
    """Correctifs de migration disponibles, et lesquels ont tourné."""
    applied = ctx.get("_fix_applied") or []
    out = []
    for index, item in enumerate(ctx.get("versions") or []):
        target = item["version"]
        stem = f"fix_migration_odoo{(target - 1) * 10}_to_odoo{target * 10}"
        found = [
            os.path.basename(p)
            for ext in (".sql", ".py")
            for p in [os.path.join(global_dir, stem + ext)]
            if os.path.exists(p)
        ]
        if not found:
            continue
        out.append(
            {
                "version": target,
                "file": found[0],
                "applied": bool(index < len(applied) and applied[index]),
            }
        )
    return out


def journal(dct_progression):
    """Commandes exécutées et décisions annotées (les lignes « # »)."""
    lst = dct_progression.get("command_executed") or []
    comments = [
        c[2:].strip() for c in lst if isinstance(c, str) and c.startswith("# ")
    ]
    commands = [
        c for c in lst if isinstance(c, str) and not c.startswith("# ")
    ]
    return {"commands": commands, "comments": comments}


def compute(
    dct_progression,
    ctx,
    database_name,
    read_uninstall,
    private_dir,
    global_dir,
):
    """Rassemble toutes les statistiques.

    `read_uninstall(version, base)` est la lecture de liste de TodoUpgrade :
    elle résout ELLE-MÊME ses chemins privé puis global, ce qui garantit
    qu'on affiche exactement la liste qui serait appliquée. `private_dir` ne
    sert donc qu'aux instantanés COW, et `global_dir` qu'aux correctifs."""
    versions = [item["version"] for item in (ctx.get("versions") or [])]
    uninstall = {}
    for target in versions:
        try:
            _lst, detail = read_uninstall(target - 1, database_name)
        except Exception:
            detail = []
        if detail:
            uninstall[target] = detail

    evolution = module_evolution(dct_progression)
    origin = dct_progression.get("lst_module_per_version_origin") or []
    return {
        "delay": fmt_delay(
            dct_progression.get("date_create"),
            dct_progression.get("date_update"),
        ),
        "updated": dct_progression.get("date_update") or "?",
        "evolution": evolution,
        "origin_count": len(origin) if isinstance(origin, list) else 0,
        "missing": dct_progression.get("lst_module_missing") or [],
        "duplicate": dct_progression.get("lst_module_duplicate") or [],
        "uninstall": uninstall,
        "removed_total": sum(len(v) for v in uninstall.values()),
        "cow": cow_snapshots(private_dir, database_name),
        "fixes": fix_hooks(
            dict(
                ctx,
                _fix_applied=dct_progression.get(
                    "state_4_fix_migration_odoo_lst"
                )
                or [],
            ),
            global_dir,
        ),
        "journal": journal(dct_progression),
    }


def flat_module_list(uninstall):
    """Tous les modules supprimés, dédupliqués, prêts à copier-coller."""
    seen = []
    for detail in uninstall.values():
        for item in detail:
            name = item[0] if isinstance(item, (list, tuple)) else item
            if name not in seen:
                seen.append(name)
    return seen
