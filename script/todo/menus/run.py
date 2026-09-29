#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus de la famille Run, qu'ouvre Execute : Run, Database et son menu
d'effacement, Analyse, Transform data et Doc.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place.
"""

from script.todo.ui.registry import Entry, FromConfig, Menu, Section

RUN = Menu(
    "prompt_execute_instance",
    "Run",
    [
        Entry("Choose your database", "callback_execute_custom_database"),
        FromConfig("instance", "_run_instance", "instance"),
        Entry(
            "Mobile - Compile and run software",
            "callback_make_mobile_home",
            when="_mobile_exists",
        ),
    ],
    render="once",
)

# Chaque action passe la main à la méthode de même nom de `db_manager`.
DATABASE = Menu(
    "prompt_execute_database",
    "Database",
    [
        Section("Backup"),
        Entry("Create backup (.zip)", "create_backup_from_database"),
        Entry(
            "Download database to create backup (.zip)",
            "download_database_backup_cli",
        ),
        Section("Restore"),
        Entry("Restore from backup (.zip)", "restore_from_database"),
        Section("Duplicate"),
        Entry("Duplicate a database", "duplicate_database"),
        Section("Danger zone"),
        Entry("Erase a database", "drop_database", danger=True),
    ],
    intro="Make changes to databases!",
    render="once",
)

# Ouvert par `DatabaseManager.drop_database`, dont il nomme les méthodes.
ERASE = Menu(
    "drop_database",
    None,
    [
        Entry(
            "Erase ALL databases (make db_drop_all)",
            "_drop_all_databases",
            danger=True,
        ),
        Entry("Erase a single database", "_drop_single_database", danger=True),
    ],
    intro="Erase a database — irreversible operation!",
    mark="⚠️ ",
    back=None,
    render="once",
    closes=True,
)
