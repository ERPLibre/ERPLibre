#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Rendre visibles les documents DMS qu'une migration a rendus muets.

Le symptôme : après le palier 13, les documents DMS « ont disparu ». Ils
n'ont pas disparu. Mesuré sur une base migrée : 69 fichiers, 16 dossiers,
23 Mo de `content_binary`, présents à l'identique de la 12 à la 18. Rien
n'a été perdu.

Ce qui a changé, c'est le MODÈLE DE SÉCURITÉ. En 12, MuK DMS ne filtrait
que sur la société :

    ['|', ('company','=',False), ('company','child_of',[...])]

OCA DMS, à partir de la 13, ajoute des règles GLOBALES sur une permission
calculée :

    [('permission_read', '=', user.id)]

`_search_permission_read` n'accorde l'accès que par deux portes :

1. Une `dms.access.group` dont l'utilisateur est membre, reliée au
   dossier — la migration n'en a créé AUCUNE, parce que MuK n'en avait
   aucune à convertir.
2. L'héritage depuis l'enregistrement lié, qui exige
   `storage.save_type = 'attachment'` — or les stockages migrés sont en
   `database`.

Les deux portes fermées, la règle globale filtre TOUT. Pas un dossier,
pas un fichier, pour personne — l'administrateur compris, car `admin`
n'est pas le super-utilisateur au sens d'Odoo.

Ce que fait la réparation
-------------------------
Une seule `dms.access.group`, adossée au groupe Odoo `dms.group_dms_user`
plutôt qu'à une liste d'utilisateurs — ainsi l'appartenance continue de
suivre le groupe, comme avant la migration —, reliée aux dossiers
RACINES. Les enfants héritent : ils portent tous
`inherit_group_ids = true`.

Ce qu'elle ne fait pas : inventer une granularité que MuK n'avait pas.
L'ancien modèle ne connaissait pas d'ACL par dossier ; en fabriquer une
ici serait décider à la place de l'utilisateur, sur des données qu'il
n'a jamais saisies.

Codes de sortie : 0 rien à faire, 1 il y a à faire (ou c'est fait), 2 échec.
"""

import argparse
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

from script.odoo.migration import database_cleanup  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Les sentinelles de `run_shell`, pas les nôtres : il les impose, et
# elles ne servent qu'à isoler le rapport des journaux d'Odoo. En
# inventer une seconde paire aurait créé un contrat parallèle à tenir.
DEBUT = database_cleanup.START
FIN = database_cleanup.END
NOM_GROUPE = "Migration MuK → DMS"

# Le script poussé dans `odoo-bin shell`. Il compte AVANT et APRÈS avec un
# vrai utilisateur : c'est la seule preuve qui vaille — la règle globale
# ne s'applique pas au super-utilisateur, donc un compte fait en sudo
# dirait « tout va bien » alors que personne ne voit rien.
SCRIPT = """
import json
DRY = {dry}
NOM = {nom!r}
rapport = {{"dry_run": DRY}}
try:
    Dossier = env["dms.directory"].sudo()
    Fichier = env["dms.file"].sudo()
    Groupe = env["dms.access.group"].sudo()
    rapport["files"] = Fichier.search_count([])
    rapport["directories"] = Dossier.search_count([])
    rapport["access_groups_before"] = Groupe.search_count([])

    # Un vrai utilisateur, pas le super-utilisateur : la règle globale ne
    # s'applique qu'à lui, et c'est justement ce qu'on mesure.
    membres = env.ref("dms.group_dms_user").users.filtered(
        lambda u: u.id != 1 and u.active
    )
    temoin = membres[:1]
    rapport["witness"] = temoin.login if temoin else None

    def visible():
        if not temoin:
            return None
        return {{
            "directories": Dossier.with_user(temoin).search_count([]),
            "files": Fichier.with_user(temoin).search_count([]),
        }}

    rapport["before"] = visible()
    racines = Dossier.search([("is_root_directory", "=", True)])
    rapport["roots"] = racines.mapped("name")
    deja = Groupe.search([("name", "=", NOM)])
    rapport["already_repaired"] = bool(deja)

    if not DRY and not deja and racines:
        Groupe.create({{
            "name": NOM,
            "perm_create": True,
            "perm_write": True,
            "perm_unlink": True,
            "group_ids": [(6, 0, [env.ref("dms.group_dms_user").id])],
            "directory_ids": [(6, 0, racines.ids)],
        }})
        env.cr.commit()
        env.registry.clear_cache()
        rapport["created"] = True
        rapport["after"] = visible()
    rapport["access_groups_after"] = Groupe.search_count([])
except Exception as exc:
    rapport["error"] = "%s: %s" % (type(exc).__name__, exc)
print({debut!r})
print(json.dumps(rapport))
print({fin!r})
"""


def build_script(dry_run):
    return SCRIPT.format(
        dry="True" if dry_run else "False",
        nom=NOM_GROUPE,
        debut=DEBUT,
        fin=FIN,
    )


def render(rapport, dry_run):
    lignes = [
        f"📁 {t('DMS documents in the database')} :"
        f" {rapport.get('files', '?')} {t('file(s)')},"
        f" {rapport.get('directories', '?')} {t('folder(s)')}"
    ]
    avant = rapport.get("before")
    temoin = rapport.get("witness")
    if avant is None:
        lignes.append(f"   ⚠ {t('No DMS user to test visibility with.')}")
    else:
        lignes.append(
            f"   {t('Visible to')} {temoin} :"
            f" {avant['directories']} {t('folder(s)')},"
            f" {avant['files']} {t('file(s)')}"
        )
    lignes.append(
        f"   {t('DMS access groups:')} {rapport.get('access_groups_before', '?')}"
    )
    if rapport.get("already_repaired"):
        lignes.append(f"   ℹ️  {t('Already repaired: the group exists.')}")
        return lignes
    if dry_run:
        lignes.append(
            f"   → {t('Would create one access group over')}"
            f" {len(rapport.get('roots') or [])} {t('root folder(s)')} :"
            f" {', '.join(rapport.get('roots') or [])}"
        )
        lignes.append(f"   {t('Nothing written. Re-run with --apply.')}")
        return lignes
    apres = rapport.get("after")
    if apres:
        lignes.append(
            f"   ✅ {t('Now visible to')} {temoin} :"
            f" {apres['directories']} {t('folder(s)')},"
            f" {apres['files']} {t('file(s)')}"
        )
    return lignes


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Restore visibility of DMS documents after a MuK DMS to OCA DMS"
            " migration. Reports without writing unless --apply is given."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="config.conf")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually create the access group (default: report only)",
    )
    config = parser.parse_args(argv)

    # Le même garde-fou que partout ailleurs : un Odoo d'une autre version
    # ÉCRIT dans la base avant d'échouer.
    souci = database_cleanup.require_matching_version(config.database)
    if souci:
        print(f"❌ {souci}")
        return 2

    try:
        rapport = database_cleanup.run_shell(
            config.database,
            config.config,
            build_script(not config.apply),
            echo=lambda texte: print(f"⧖ {texte}", flush=True),
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    if rapport.get("error"):
        print(f"❌ {rapport['error']}")
        return 2
    print("\n".join(render(rapport, not config.apply)))
    avant = rapport.get("before") or {}
    return 1 if not avant.get("files") else 0


if __name__ == "__main__":
    sys.exit(main())
