#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import argparse
import logging
import os
import subprocess
import sys

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ),
)

from script.database import drill_guard  # noqa: E402

logging.basicConfig(level=logging.DEBUG)
_logger = logging.getLogger(__name__)


def execute_shell(cmd):
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


def get_config():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""\
        Drop all database, caution!
""",
        epilog="""\
""",
    )
    parser.add_argument(
        "--test_only",
        help="test and test_* and other by system test.",
        action="store_true",
    )
    parser.add_argument(
        "--database",
        help="Specify database to delete, separate by coma",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Effacer même ce que le contrôle refuse. À n'employer que sur"
            " une base dont on sait, autrement, qu'elle est jetable."
        ),
    )
    args = parser.parse_args()
    return args


def _verdict(db_name, force=False):
    """Le verdict du contrôle, ou le passage en force ASSUMÉ et DIT.

    Le passage en force n'est pas un raccourci : il est nommé sur la sortie,
    parce qu'une destruction qu'on s'autorise sans preuve doit rester
    lisible dans le journal de ce qui s'est passé.
    """
    if force:
        print(f"  ⚠ {db_name} : contrôle passé en force")
        return drill_guard.DRILL
    try:
        return drill_guard.inspect(db_name).verdict
    except Exception as souci:
        # Ce qu'on n'a pas pu lire n'est pas jetable. Un contrôle qui tombe
        # ne doit pas ouvrir la porte qu'il est là pour tenir.
        return f"{drill_guard.UNREADABLE} ({souci})"


def main():
    config = get_config()

    status, out_db = execute_shell("./odoo_bin.sh db --list")
    lst_db = out_db.split("\n")

    lst_database_to_delete = []
    if config.database:
        lst_database_to_delete = [
            a.strip() for a in config.database.split(",")
        ]

    cmd_all = "parallel :::"
    cmd_end = ""
    lst_db_name = []
    refusees = []
    for db_name in lst_db:
        if not db_name:
            continue
        if config.test_only and not (
            db_name in ("test",)
            or db_name.startswith("test_")
            or db_name.startswith("new_project_")
        ):
            continue
        if lst_database_to_delete and db_name not in lst_database_to_delete:
            continue

        # LE NOM NE DONNE PAS LE FEU VERT. Le filtre ci-dessus RESTREINT ce
        # qu'on regarde ; il n'autorise rien. Ce qui autorise, c'est ce que
        # la base dit d'elle-même — et sans argument, ce script effaçait
        # tout ce que l'instance porte, sans une seule question.
        verdict = _verdict(db_name, force=config.force)
        if verdict != drill_guard.DRILL:
            refusees.append((db_name, verdict))
            continue

        cmd_end += f' "./odoo_bin.sh db --drop --database {db_name}"'
        lst_db_name.append(db_name)

    if refusees:
        print("Refusé — ces bases ne se prouvent pas jetables :")
        for db_name, verdict in refusees:
            print(f"  {db_name} : {verdict}")
    if not cmd_end:
        print("Aucune base effacée.")
        return 1 if refusees else 0

    status, sortie = execute_shell(cmd_all + cmd_end)
    if status:
        # « Database deleted » était imprimé quel que soit le résultat :
        # le script annonçait avoir détruit ce qu'il n'avait peut-être pas
        # détruit. Le cas s'atteint dès que « parallel » manque du PATH — le
        # shell rend 127 et pas une base n'est touchée, pendant que la liste
        # s'affiche.
        #
        # LE CODE DU SHELL REMONTE TEL QUEL, et l'échec part sur la sortie
        # d'erreur. Aplati à 1, il ne distingue plus « outil absent » de
        # « base occupée » ; mêlé à la sortie standard, il se perd dans ce
        # qu'un appelant lit pour obtenir la liste des bases effacées.
        print("Database NOT deleted :", file=sys.stderr)
        if sortie:
            print(sortie[-2000:], file=sys.stderr)
        return status
    print("Database deleted :")
    for db_name in lst_db_name:
        print(db_name)
    return 1 if refusees else 0


if __name__ == "__main__":
    sys.exit(main())
