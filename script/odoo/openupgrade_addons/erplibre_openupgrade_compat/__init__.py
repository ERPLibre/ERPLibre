# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Correctifs d'openupgradelib, appliqués à l'import de ce module.

todo_upgrade.py charge ce module par --load pendant OpenUpgrade 14 et plus,
à côté d'openupgrade_framework. Les scripts de migration appellent
`openupgrade.<fonction>` au moment de l'appel : remplacer l'attribut du
module suffit.

lift_constraints : PostgreSQL 18 catalogue chaque NOT NULL dans
pg_constraint (contype 'n', nommé <table>_<colonne>_not_null). La requête
d'openupgradelib les ramasse avec le reste ; sur une clé primaire, le
NOT NULL passe avant la clé et PostgreSQL refuse de le retirer
(« column "id" is in a primary key ») : OpenUpgrade 19 s'arrête dans
stock_account et hr_recruitment. La version ci-dessous exclut contype 'n',
ce qui rend exactement les ordres de PostgreSQL 17 et plus ancien. Elle ne
remplace rien quand la bibliothèque filtre déjà contype.
"""
import inspect
import logging

from psycopg2.extensions import AsIs

_logger = logging.getLogger(__name__)


def lift_constraints(cr, table, column, cascade=False):
    """openupgradelib.openupgrade.lift_constraints, sans les NOT NULL.

    Même contrat : retire les contraintes qui portent sur column de table,
    et celles qui la référencent ; cascade=True pour une clé primaire.
    """
    cr.execute(
        "select relname, array_agg(conname) from "
        "(select t1.relname, c.conname "
        "from pg_constraint c "
        "join pg_attribute a "
        "on c.confrelid=a.attrelid and a.attnum=any(c.conkey) "
        "join pg_class t on t.oid=a.attrelid "
        "join pg_class t1 on t1.oid=c.conrelid "
        "where t.relname=%(table)s and attname=%(column)s "
        "and c.contype <> 'n' "
        "union select t.relname, c.conname "
        "from pg_constraint c "
        "join pg_attribute a "
        "on c.conrelid=a.attrelid and a.attnum=any(c.conkey) "
        "join pg_class t on t.oid=a.attrelid "
        "where relname=%(table)s and attname=%(column)s "
        "and c.contype <> 'n') in_out "
        "group by relname",
        {
            "table": table,
            "column": column,
        },
    )
    for table_name, constraints in cr.fetchall():
        cr.execute(
            "alter table %s drop constraint if exists %s",
            (
                AsIs(table_name),
                AsIs(
                    ", drop constraint if exists ".join(
                        (constraint + " cascade") if cascade else constraint
                        for constraint in constraints
                    )
                ),
            ),
        )


def appliquer(openupgrade):
    """Remplace ce qui manque à openupgradelib ; rend les noms remplacés."""
    remplaces = []
    try:
        source = inspect.getsource(openupgrade.lift_constraints)
    except (OSError, TypeError):
        source = ""
    if "contype" not in source:
        openupgrade.lift_constraints = lift_constraints
        remplaces.append("lift_constraints")
    return remplaces


try:
    from openupgradelib import openupgrade as _openupgrade
except ImportError:
    _openupgrade = None

if _openupgrade is not None:
    _remplaces = appliquer(_openupgrade)
    if _remplaces:
        _logger.info(
            "openupgradelib: %s skip the NOT NULL constraints"
            " of PostgreSQL 18",
            ", ".join(_remplaces),
        )
