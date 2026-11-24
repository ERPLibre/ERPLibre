# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Lecture des journaux Odoo : quelles lignes sont des erreurs, lesquelles
des avertissements.

Une ligne est une ERREUR si elle contient « error », sans égard à la casse,
et aucune des chaînes de IGNORE_ERREUR ; un AVERTISSEMENT si elle contient
« warning » et aucune de IGNORE_AVERTISSEMENT. Une même ligne peut être les
deux. Les listes d'ignore nomment des messages connus et bénins : une
contrainte que le générateur supprime avant de la recréer, un libellé
partagé par deux champs.

Le verdict des scénarios du générateur en dépend : Odoo journalise une
ERROR et sort pourtant en 0, et un scénario n'est vert que si aucune ligne
d'erreur n'échappe aux listes. L'analyse des journaux d'installation des VM
(script/todo/qemu_install_monitor.py) part des mêmes listes.

Bibliothèque standard seule : importé par le lanceur, le pilote d'un
scénario et le moniteur d'installation, sous des interpréteurs différents.
"""

IGNORE_AVERTISSEMENT = (
    "have the same label:",
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
)

IGNORE_ERREUR = (
    "fetchmail_notify_error_to_sender",
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_name_unique"',
    'ERROR: constraint "db_backup_db_backup_name_unique" of relation'
    ' "db_backup" does not exist',
    'odoo.sql_db: bad query: ALTER TABLE "db_backup" DROP CONSTRAINT'
    ' "db_backup_db_backup_days_to_keep_positive"',
    'ERROR: constraint "db_backup_db_backup_days_to_keep_positive" of relation'
    ' "db_backup" does not exist',
    "odoo.addons.code_generator.extractor_module_file: Ignore next error about"
    " ALTER TABLE DROP CONSTRAINT.",
)


def est_erreur(ligne, ignore=IGNORE_ERREUR):
    """Vrai si `ligne` contient « error » hors des chaînes `ignore`."""
    return "error" in ligne.lower() and not any(i in ligne for i in ignore)


def est_avertissement(ligne, ignore=IGNORE_AVERTISSEMENT):
    """Vrai si `ligne` contient « warning » hors des chaînes `ignore`."""
    return "warning" in ligne.lower() and not any(i in ligne for i in ignore)


def classer_lignes(texte):
    """(erreurs, avertissements) : les lignes de `texte` retenues, dans
    l'ordre. Le texte se découpe sur « \\n » seul : un « \\r » reste dans
    la ligne, comme dans le journal."""
    erreurs = []
    avertissements = []
    for ligne in texte.split("\n"):
        if est_erreur(ligne):
            erreurs.append(ligne)
        if est_avertissement(ligne):
            avertissements.append(ligne)
    return erreurs, avertissements


def extract_result(result, test_name, lst_error, lst_warning):
    """Ajoute à `lst_error` et `lst_warning` ce que retient le résultat
    `result` = (journal, code de retour) d'un test nommé `test_name`.

    Un code non nul ajoute une erreur qui nomme le test, journal compris
    quand il tient sur une ligne."""
    erreurs, avertissements = classer_lignes(result[0])
    lst_error.extend(erreurs)
    lst_warning.extend(avertissements)
    if result[1]:
        if len(result[0].split("\n")) == 1:
            lst_error.append(
                f"Return status error for test {test_name} : {result[0]}"
            )
        else:
            lst_error.append(f"Return status error for test {test_name}")
