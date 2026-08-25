#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les index que la 17 a créés en double et n'a jamais retirés.

Odoo 17 a changé sa convention de nommage : `make_index_name` rend
désormais `{table}__{colonne}_index` — deux soulignés — là où les
versions d'avant écrivaient `{table}_{colonne}_index`. Le nouvel index
est créé, l'ancien reste. Mesuré sur une chaîne 12 → 18 :

    test_neutralize (12)   1 paire
    _16                    3
    _17                  370      ← la bascule
    _18                  365

Inerte à la lecture, coûteux à l'écriture : chaque INSERT et chaque
UPDATE sur ces tables entretient deux arbres B identiques. Ici 9,6 Mo et
une base vide ; sur une production le coût croît avec les lignes. C'est
le seul défaut de cette famille qui empire tout seul.

Ce que l'outil REFUSE de toucher, et pourquoi :

  adossé à une contrainte   PostgreSQL le recréerait, ou la contrainte
                            tomberait avec lui.
  clé primaire              même raison, en pire.
  index partiel ou calculé  `indpred` / `indexprs` : deux index sur les
                            mêmes colonnes n'y font pas le même travail.
  méthode différente        un gin et un btree sur la même colonne ne se
                            remplacent pas.
  convention ambiguë        aucun des deux noms — ou les deux — suit la
                            convention de la cible : on ne devine pas
                            lequel Odoo recréera.

Lecture seule par défaut. `--apply` supprime, puis RELIT pour vérifier.
"""

import argparse
import json
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


# Les paires strictement identiques : même table, mêmes colonnes, même
# unicité, même méthode d'accès, mêmes classes d'opérateurs. Sans un seul
# de ces critères on comparerait des index qui ne font pas le même travail.
DETECTION = """
WITH idx AS (
  SELECT i.indexrelid,
         i.indrelid,
         i.indkey::text        AS cols,
         i.indclass::text      AS classes,
         i.indisunique         AS unique_,
         am.amname             AS methode,
         c.relname             AS nom,
         t.relname             AS tbl,
         pg_relation_size(i.indexrelid) AS taille,
         EXISTS (SELECT 1 FROM pg_constraint k
                 WHERE k.conindid = i.indexrelid) AS contrainte
  FROM pg_index i
  JOIN pg_class c   ON c.oid = i.indexrelid
  JOIN pg_class t   ON t.oid = i.indrelid
  JOIN pg_am am     ON am.oid = c.relam
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public'
    AND i.indpred IS NULL
    AND i.indexprs IS NULL
    AND NOT i.indisprimary
    AND i.indisvalid
)
SELECT coalesce(json_agg(json_build_object(
         'table', a.tbl,
         'a', a.nom, 'a_size', a.taille, 'a_ctr', a.contrainte,
         'b', b.nom, 'b_size', b.taille, 'b_ctr', b.contrainte
       )), '[]')
FROM idx a
JOIN idx b
  ON a.indrelid = b.indrelid
 AND a.cols     = b.cols
 AND a.classes  = b.classes
 AND a.unique_  = b.unique_
 AND a.methode  = b.methode
 AND a.indexrelid < b.indexrelid
"""


def run_psql(database, sql, read_only=True):
    """Interroger la base. None si elle ne répond pas.

    Lecture seule garantie par le SERVEUR : une suppression qui se trompe
    de base doit être refusée par PostgreSQL, pas par une relecture.
    """
    env = os.environ.copy()
    if read_only:
        env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tA", "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return None
    return done.stdout


def modern_name(table, nom):
    """Ce nom suit-il la convention de la cible ?

    `make_index_name` d'Odoo 18 rend `{table}__{colonne}_index`. Un nom
    trop long est tronqué et suffixé d'un condensat ; celui-là ne se
    reconnaît pas, et l'on préfère s'abstenir que deviner.
    """
    return nom.startswith(f"{table}__")


def classify(paire):
    """(verdict, à garder, à supprimer).

    « safe » exige que l'un des deux noms — et un seul — suive la
    convention : c'est le seul cas où l'on sait lequel Odoo recréera.
    """
    if paire["a_ctr"] or paire["b_ctr"]:
        return "constraint", None, None
    table = paire["table"]
    a_moderne = modern_name(table, paire["a"])
    b_moderne = modern_name(table, paire["b"])
    if a_moderne == b_moderne:
        return "ambiguous", None, None
    if a_moderne:
        return "safe", paire["a"], paire["b"]
    return "safe", paire["b"], paire["a"]


def find(database):
    """[(verdict, table, garder, supprimer, octets)]. None si base muette."""
    sortie = run_psql(database, DETECTION)
    if sortie is None:
        return None
    try:
        paires = json.loads(sortie.strip() or "[]")
    except ValueError:
        return None
    lst = []
    for paire in paires:
        verdict, garder, supprimer = classify(paire)
        octets = (
            paire["b_size"] if supprimer == paire["b"] else paire["a_size"]
        )
        lst.append(
            (verdict, paire["table"], garder, supprimer, octets or 0, paire)
        )
    return sorted(lst, key=lambda x: (x[0], x[1], x[3] or ""))


def safe_only(lst):
    return [item for item in lst if item[0] == "safe"]


def drop_sql(lst):
    """Les suppressions, une par ligne. Vide s'il n'y a rien de sûr.

    `IF EXISTS` : deux paires peuvent nommer le même index à supprimer
    quand une table en porte trois copies, et la deuxième passe ne doit
    pas échouer sur ce qui vient de partir.
    """
    noms = []
    for _v, _tbl, _garder, supprimer, _o, _p in safe_only(lst):
        if supprimer and supprimer not in noms:
            noms.append(supprimer)
    return "\n".join(f'DROP INDEX IF EXISTS "{nom}";' for nom in noms)


def render(lst, applique=False):
    if not lst:
        return [f"✅ {t('No duplicate index.')}"]
    surs = safe_only(lst)
    octets = sum(item[4] for item in surs)
    lignes = [
        f"🗂  {len(lst)} {t('duplicate index pair(s)')}"
        f" — {len(surs)} {t('safe to drop')}"
        f" ({octets // 1024} kB)",
        "",
    ]
    for _v, table, garder, supprimer, taille, _p in surs[:20]:
        lignes.append(
            f"   {table} : {t('drop')} {supprimer}"
            f"  ({taille // 1024} kB), {t('keep')} {garder}"
        )
    if len(surs) > 20:
        lignes.append(f"   … {len(surs) - 20} {t('more')}")
    for genre, texte in (
        ("constraint", t("backed by a constraint — left alone")),
        ("ambiguous", t("neither name follows the convention — your call")),
    ):
        lot = [item for item in lst if item[0] == genre]
        if not lot:
            continue
        lignes.append("")
        lignes.append(f"   ⚠ {len(lot)} {texte}")
        for _v, table, _g, _s, _o, paire in lot[:6]:
            lignes.append(f"      {table} : {paire['a']}  ↔  {paire['b']}")
    if not applique and surs:
        lignes.append("")
        lignes.append(f"   {t('Use --apply to drop them.')}")
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Report the duplicate indexes Odoo 17 left behind when it"
            " renamed its index convention, and optionally drop them."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually drop the safe duplicates (default: report only)",
    )
    parser.add_argument("--json", action="store_true", help="machine output")
    config = parser.parse_args(argv)

    lst = find(config.database)
    if lst is None:
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if config.json:
        print(
            json.dumps(
                [
                    {
                        "verdict": v,
                        "table": tbl,
                        "keep": g,
                        "drop": s,
                        "bytes": o,
                    }
                    for v, tbl, g, s, o, _p in lst
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if lst else 0
    if not lst:
        print("\n".join(render(lst)))
        return 0
    if not config.apply:
        print("\n".join(render(lst)))
        return 1

    sql = drop_sql(lst)
    if sql and run_psql(config.database, sql, read_only=False) is None:
        print(f"❌ {t('The correction failed.')}")
        return 2
    # RELIRE : annoncer « supprimé » sans regarder ferait croire le
    # problème réglé alors qu'un verrou a pu refuser la suppression.
    apres = find(config.database)
    if apres is None:
        print(f"❌ {t('Cannot read the database: ')}{config.database}")
        return 2
    if safe_only(apres):
        print("\n".join(render(apres, applique=True)))
        print(f"⚠️  {t('Some duplicates are still there.')}")
        return 1
    print("\n".join(render(apres, applique=True)))
    print(f"✅ {t('Duplicate indexes dropped.')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
