#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Deux données de vue qu'Odoo refuse, et qu'aucune mise à jour ne répare.

A — le `type` stocké contredit l'héritage
=========================================

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

B — un `<tree>` survit dans une base Odoo 18
============================================
La 18 a renommé le type `tree` en `list`, balise comprise. OpenUpgrade
convertit la COLONNE :

    def _fix_list_view_type(cr):
        '''Former tree views have view type list now.'''
        cr.execute("UPDATE ir_ui_view SET type='list' WHERE type='tree'")

…et jamais l'ARCH. Le chargement meurt alors sur

    Le nœud racine d'une vue list devrait être <list>, et non <tree>

Une vue de module s'en remet à la première mise à jour du module, qui
réécrit son arch depuis le XML. Une vue SANS xmlid — une liste faite à
la main, une copie de site — n'est réécrite par rien : elle reste
cassée pour toujours.

Le remplacement porte sur TOUTES les occurrences, pas seulement la
racine : un `<tree>` imbriqué dans un formulaire (une liste one2many)
est tout aussi refusé. Vérifié : les addons d'Odoo 18 n'en contiennent
plus une seule, donc tout `<tree>` d'une base 18 est un reste.

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


# La 18 renomme `tree` en `list`. Avant, la balise est légitime.
PREMIERE_VERSION_LIST = 18


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


def db_major(database):
    """La version majeure d'Odoo de cette base, ou None.

    Celle qu'Odoo inscrit, pas celle du checkout : on répare une base,
    pas un répertoire.
    """
    lignes = run_psql(
        database,
        "SELECT latest_version FROM ir_module_module WHERE name = 'base'",
    )
    if not lignes or not lignes[0][0]:
        return None
    try:
        return int(lignes[0][0].split(".")[0])
    except ValueError:
        return None


def arch_is_jsonb(database):
    """`arch_db` est un jsonb depuis la 16, un texte avant."""
    lignes = run_psql(
        database,
        "SELECT data_type FROM information_schema.columns"
        " WHERE table_name = 'ir_ui_view' AND column_name = 'arch_db'",
    )
    return bool(lignes) and lignes[0][0] == "jsonb"


def arch_as_text(jsonb):
    """L'expression SQL qui rend l'arch en texte, quelle que soit sa forme."""
    return "arch_db::text" if jsonb else "coalesce(arch_db, '')"


def find_tree(database, jsonb):
    """Les vues qui portent encore un `<tree>`. [] hors des bases 18+."""
    texte = arch_as_text(jsonb)
    lignes = run_psql(
        database,
        f"SELECT v.id::text, v.type,"
        f" coalesce(d.module || '.' || d.name, '-'),"
        f" coalesce(v.model, '-'),"
        f" CASE WHEN d.id IS NULL THEN 'custom' ELSE 'module' END"
        f" FROM ir_ui_view v"
        f" LEFT JOIN ir_model_data d"
        f"        ON d.model = 'ir.ui.view' AND d.res_id = v.id"
        f" WHERE {texte} LIKE '%<tree%'"
        f" ORDER BY v.id",
    )
    if lignes is None:
        return None
    return [
        {
            "id": int(ligne[0]),
            "type": ligne[1],
            "xmlid": ligne[2],
            "model": ligne[3],
            "origin": ligne[4],
        }
        for ligne in lignes
        if len(ligne) >= 5
    ]


def repair_tree_sql(vues, jsonb):
    """Le SQL qui remplace `<tree>` par `<list>`, ou "".

    TOUTES les occurrences : un `<tree>` imbriqué dans un formulaire est
    refusé autant que celui de la racine. Les addons d'Odoo 18 n'en
    contiennent plus une seule, donc il n'y a rien de légitime à épargner.
    """
    if not vues:
        return ""
    liste = ", ".join(str(vue["id"]) for vue in vues)
    if jsonb:
        # jsonb : reconstruire l'objet, langue par langue. Une traduction
        # oubliée laisserait la vue cassée dans cette langue seulement —
        # une panne qui ne se montre qu'à certains.
        remplace = (
            "(SELECT jsonb_object_agg(cle,"
            " replace(replace(valeur, '<tree', '<list'),"
            " '</tree>', '</list>'))"
            " FROM jsonb_each_text(arch_db) AS paires(cle, valeur))"
        )
    else:
        remplace = (
            "replace(replace(arch_db, '<tree', '<list'),"
            " '</tree>', '</list>')"
        )
    return f"UPDATE ir_ui_view SET arch_db = {remplace} WHERE id IN ({liste})"


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
        return []
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


def render_tree(vues, applique=False):
    if not vues:
        return []
    lignes = [
        f"🩹 {len(vues)} {t('view(s) still carry a <tree> tag Odoo 18')}"
        f" {t('renamed to <list>')} :"
    ]
    for vue in vues:
        # L'ORIGINE est le renseignement utile : une vue de module se
        # répare d'une mise à jour, une vue sans xmlid n'est réécrite
        # par rien et reste cassée pour toujours.
        marque = (
            t("custom — nothing will ever rewrite it")
            if vue["origin"] == "custom"
            else t("from a module — a module update also fixes it")
        )
        lignes.append(
            f"       {vue['id']:<7} {vue['xmlid'][:40]:<42}"
            f" {vue['type']:<8} {vue['model'][:22]:<24} {marque}"
        )
    if applique:
        lignes.append(f"   ✅ {t('Corrected.')}")
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
    # Le renommage `tree` → `list` n'a de sens qu'à partir de la 18 :
    # avant, la balise est parfaitement légitime et la « corriger »
    # casserait des vues saines.
    jsonb = arch_is_jsonb(config.database)
    majeure = db_major(config.database)
    arbres = []
    if majeure and majeure >= PREMIERE_VERSION_LIST:
        arbres = find_tree(config.database, jsonb) or []

    if not vues and not arbres:
        print(f"✅ {t('Every view agrees with what Odoo expects.')}")
        return 0
    if not config.apply:
        print("\n".join(render(vues) + render_tree(arbres)))
        return 1

    for sql in (repair_sql(vues), repair_tree_sql(arbres, jsonb)):
        if sql and run_psql(config.database, sql, read_only=False) is None:
            print(f"❌ {t('The correction failed.')}")
            return 2
    # Relire APRÈS : annoncer « corrigé » sans vérifier ferait relancer
    # la migration sur le même mur.
    if find(config.database) or (arbres and find_tree(config.database, jsonb)):
        print(f"❌ {t('The correction failed.')}")
        return 2
    print(
        "\n".join(
            render(vues, applique=True) + render_tree(arbres, applique=True)
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
