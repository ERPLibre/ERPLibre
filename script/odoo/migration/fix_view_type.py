#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une vue dont le `type` stocké contredit son héritage.

Le symptôme est brutal : Odoo refuse de charger la base.

    Le nœud racine d'une vue tree devrait être <tree>, et non <search>
    view: ir.ui.view(637,)  view.parent: ir.ui.view(636,)

La 637 hérite d'une vue `search` et son `type` en base dit `tree`. Odoo
valide alors un `<search>` avec les règles d'un `<tree>`, et échoue.

Pourquoi aucune mise à jour ne le répare
----------------------------------------
`type` n'est PAS un champ calculé. Dans `ir_ui_view.py`, il est rempli
dans `create` — et seulement s'il est absent :

    if not values.get('type'):
        if values.get('inherit_id'):
            values['type'] = self.browse(values['inherit_id']).type

`write` ne le recalcule jamais. Une valeur fausse reste donc fausse pour
toujours, et `-u module` ne la corrigera pas — il échoue avant, sur la
validation qu'elle provoque.

Pourquoi en SQL et pas par l'ORM
--------------------------------
Parce que le registre ne charge plus. Un outil qui aurait besoin d'Odoo
pour réparer ce qui empêche Odoo de démarrer ne servirait à rien.

Ce que la règle garantit
------------------------
Une vue héritée prend le type de son ancêtre — c'est la règle d'Odoo
lui-même, citée plus haut. Vérifié : zéro écart sur une installation 18
neuve et sur quatre bases migrées, un seul sur celle qui refusait de
charger. Le détecteur ne crie pas au loup.

Codes de sortie : 0 rien à signaler, 1 des trouvailles, 2 l'outil a échoué.
"""

import argparse
import os
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


SEP = "\x1f"

# La profondeur borne la récursion : un `inherit_id` circulaire ferait
# tourner PostgreSQL sans fin, et une chaîne de vues n'a jamais vingt
# maillons.
PROFONDEUR_MAX = 20

DETECTION = f"""
WITH RECURSIVE racine AS (
    SELECT id, type, 0 AS prof FROM ir_ui_view WHERE inherit_id IS NULL
    UNION ALL
    SELECT v.id, r.type, r.prof + 1
    FROM ir_ui_view v JOIN racine r ON v.inherit_id = r.id
    WHERE r.prof < {PROFONDEUR_MAX}
)
SELECT v.id::text, v.type, r.type,
       coalesce(v.mode, '-'),
       coalesce(d.module || '.' || d.name, '-'),
       coalesce(v.model, '-')
FROM ir_ui_view v
JOIN racine r ON r.id = v.id
LEFT JOIN ir_model_data d
       ON d.model = 'ir.ui.view' AND d.res_id = v.id
WHERE v.inherit_id IS NOT NULL AND v.type <> r.type
ORDER BY v.id
"""


def run_psql(database, sql, read_only=True):
    """Interroger la base. En lecture seule sauf demande explicite."""
    env = os.environ.copy()
    if read_only:
        env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAF", SEP, "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return [ligne.split(SEP) for ligne in done.stdout.splitlines() if ligne]


def find(database):
    """Les vues fautives. None si la base ne répond pas."""
    lignes = run_psql(database, DETECTION)
    if lignes is None:
        return None
    return [
        {
            "id": int(ligne[0]),
            "type": ligne[1],
            "expected": ligne[2],
            "mode": ligne[3],
            "xmlid": ligne[4],
            "model": ligne[5],
        }
        for ligne in lignes
        if len(ligne) >= 6
    ]


def repair_sql(vues):
    """Le SQL de correction, ou "" s'il n'y a rien à corriger.

    Un `CASE` plutôt qu'un ordre par vue : une seule instruction, donc
    une seule transaction, donc pas de base à moitié réparée si l'on
    coupe au milieu.
    """
    if not vues:
        return ""
    cas = " ".join(
        f"WHEN {vue['id']} THEN '{vue['expected']}'" for vue in vues
    )
    liste = ", ".join(str(vue["id"]) for vue in vues)
    return (
        f"UPDATE ir_ui_view SET type = CASE id {cas} END"
        f" WHERE id IN ({liste})"
    )


def render(vues, applique=False):
    if not vues:
        return [f"✅ {t('Every view type agrees with its inheritance.')}"]
    lignes = [
        f"🩹 {len(vues)} {t('view(s) whose stored type contradicts')}"
        f" {t('their inheritance')} :"
    ]
    for vue in vues:
        lignes.append(
            f"       {vue['id']:<7} {vue['xmlid'][:46]:<48}"
            f" {vue['type']} → {vue['expected']}   {vue['model']}"
        )
    if applique:
        lignes.append(f"   ✅ {t('Corrected.')}")
    else:
        lignes.append(
            f"   {t('No module update will fix this: the type is set once,')}"
            f" {t('at creation. Re-run with --apply.')}"
        )
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Report views whose stored type contradicts the type of the"
            " view they inherit from, and optionally fix them."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually correct the type (default: report only)",
    )
    config = parser.parse_args(argv)

    vues = find(config.database)
    if vues is None:
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if not vues:
        print("\n".join(render(vues)))
        return 0
    if not config.apply:
        print("\n".join(render(vues)))
        return 1
    sql = repair_sql(vues)
    if run_psql(config.database, sql, read_only=False) is None:
        print(f"❌ {t('The correction failed.')}")
        return 2
    reste = find(config.database)
    if reste:
        print(f"❌ {t('The correction failed.')}")
        return 2
    print("\n".join(render(vues, applique=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
